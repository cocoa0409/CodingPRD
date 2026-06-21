"""Difficulty Rule 1 — dual_variant_calc.

Two variant calculations diverge when their inputs disagree:
  (A) Title insurance premium under variant=standard vs variant=lender_concurrent
      on otherwise-identical PurchaseAgreement + RESOLVED TitleSearch.
  (B) Disbursement waterfall under variant=standard vs variant=exchange_routed
      — same disbursement payload, different routing constraints from the
      linked PurchaseAgreement.exchange_account_id.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    setup_actors,
    set_clock,
    setup_active_agreement,
    setup_resolved_clean_title,
    issue_title_policy,
    create_wire,
    create_exchange_account,
    queue_disbursement,
    setup_locked_wire,
    create_disbursement_payload,
)


class TestTitlePremiumStandardVsLenderConcurrent:
    """At purchase_price_cents=50_000_000 (i.e. $500,000): the per-tier
    formula yields premium=205000 with no LENDER wire present, and the
    same formula with the 0.15 lender-concurrent reduction applied to the
    sum yields premium=174250 when a non-REJECTED LENDER wire exists.
    """

    def _setup_actor_stack(self):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        return actors

    def _setup_resolved_search(self, actors, property_address, purchase_price_cents):
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=purchase_price_cents,
            earnest_money_required_cents=1_000_000,
            scheduled_closing_date="2026-08-01T00:00:00Z",
        )
        agreement = base["agreement"]
        # override the buyer/seller and property_address purely cosmetically;
        # the formula depends only on purchase_price_cents.
        search = setup_resolved_clean_title(actors, agreement["id"])
        return agreement, search

    def test_standard_variant_at_500k_yields_premium_205000(self, api):
        """PRD §3.2: "The price is sliced at three break-points — 100,000 dollars, 500,000 dollars, and 1,000,000 dollars — yielding four tiers with successively lower per-dollar rates: 0.00450 per dollar for the first 100,000 dollars (the cents-equivalent break is 10,000,000 cents), 0.00400 per dollar for the portion from 100,000 dollars up to 500,000 dollars (cents break at 50,000,000), 0.00350 per dollar for the portion from 500,000 dollars up to 1,000,000 dollars (cents break at 100,000,000), and 0.00300 per dollar for any portion above 1,000,000 dollars."
        PRD §3.2: "The amount that falls inside each tier is multiplied by that tier's per-dollar rate (after converting the slice from cents to dollars by dividing by 100), the resulting per-tier cent value is rounded half up to a whole cent, and the four rounded slices are then summed to produce the final ``premium_cents``."
        PRD §3.2: "Issuance creates the policy in ``ISSUED`` with ``version`` 1, sets ``coverage_amount_cents`` equal to the linked agreement's ``purchase_price_cents`` at the instant of issuance"

        Design: Difficulty/dual_variant_calc/title_premium_variant_standard_vs_lender_concurrent
        """
        actors = self._setup_actor_stack()
        _, search = self._setup_resolved_search(actors, "1 Std St", 50_000_000)
        policy = issue_title_policy(actors, search["search_id"], search["version"])
        assert policy["premium_cents"] == 205000, \
            f"$500K standard premium: tier1 45000 + tier2 160000 = 205000, got {policy['premium_cents']}"
        assert policy["coverage_amount_cents"] == 50_000_000, \
            f"coverage_amount_cents must equal purchase_price_cents, got {policy['coverage_amount_cents']}"
        assert policy["status"] == "ISSUED"

    def test_lender_concurrent_variant_at_500k_yields_premium_174250(self, api):
        """PRD §3.2: "The lender-concurrent variant applies if and only if the agreement already carries at least one ``WireInstruction`` whose ``party`` is ``LENDER`` and whose status is anything other than ``REJECTED``. In that case, after the per-tier sum has been computed, the result is reduced by 15 percent (a multiplier of 0.15 is subtracted from the unit factor, equivalently the sum is multiplied by 0.85), and that reduced amount is then rounded half up to a whole cent to yield the final ``premium_cents``."

        Design: Difficulty/dual_variant_calc/title_premium_variant_standard_vs_lender_concurrent
        """
        actors = self._setup_actor_stack()
        agreement, search = self._setup_resolved_search(actors, "2 LC St", 50_000_000)
        # Attach a LENDER wire (status=PROVIDED, which is "anything other than REJECTED").
        create_wire(
            actors, agreement["id"], party="LENDER",
            beneficiary_account_last4="9991",
        )
        policy = issue_title_policy(actors, search["search_id"], search["version"])
        # 0.85 * 205000 = 174250 (exact integer, no rounding effect)
        assert policy["premium_cents"] == 174250, \
            f"$500K lender-concurrent premium: 205000 * 0.85 = 174250, got {policy['premium_cents']}"
        assert policy["coverage_amount_cents"] == 50_000_000


class TestDisbursementWaterfallStandardVsExchangeRouted:
    """Identical disbursement payload (purpose=SELLER_PROCEEDS, amount=40000000)
    succeeds when the agreement has no exchange_account_id, and is rejected
    with 422 ERR_EXCHANGE_ROUTING_REQUIRED when an exchange_account_id is set.
    """

    def test_standard_variant_seller_proceeds_queues_successfully(self, api):
        """PRD §3.5: "Disbursements are queued against the escrow account at any point before close. A queued disbursement carries an ``escrow_account_id``, a ``wire_instruction_id`` (the destination — which must reference a wire instruction whose status is ``LOCKED``, otherwise the queue is rejected with ``ERR_WIRE_NOT_LOCKED``), a ``purpose`` of ``SELLER_PROCEEDS``, ``LENDER_PAYOFF``, ``TITLE_PREMIUM``, ``EXCHANGE_FUNDS``, or ``EARNEST_REFUND``, and an ``amount_cents`` strictly greater than zero. The disbursement lands in ``QUEUED`` with ``version`` 1."

        Design: Difficulty/dual_variant_calc/disbursement_waterfall_standard_vs_exchange_routed
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base_s = setup_active_agreement(actors=actors, purchase_price_cents=50_000_000)
        # Locked SELLER wire — required to queue the disbursement.
        seller_wire = setup_locked_wire(
            actors, base_s["agreement"]["id"], party="SELLER",
            voice_callback_reference="VC-SS",
        )
        disb = queue_disbursement(
            actors, base_s["escrow"]["id"], seller_wire["id"],
            purpose="SELLER_PROCEEDS", amount_cents=40_000_000,
        )
        assert disb["status"] == "QUEUED", \
            f"standard variant: SELLER_PROCEEDS should land in QUEUED, got {disb['status']}"
        assert disb["purpose"] == "SELLER_PROCEEDS"
        assert disb["amount_cents"] == 40_000_000

    def test_exchange_routed_variant_seller_proceeds_rejected(self, api):
        """PRD §3.7: "When an agreement's ``exchange_account_id`` is non-null, the seller's funds at close cannot go directly to the seller — they must route through the qualified intermediary. The system enforces this at queue-time: a disbursement with ``purpose`` of ``SELLER_PROCEEDS`` against an agreement that carries an exchange account is rejected with ``ERR_EXCHANGE_ROUTING_REQUIRED``."

        Design: Difficulty/dual_variant_calc/disbursement_waterfall_standard_vs_exchange_routed
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        exchange = create_exchange_account(actors)
        base_e = setup_active_agreement(
            actors=actors,
            purchase_price_cents=50_000_000,
            exchange_account_id=exchange["id"],
            scheduled_closing_date="2026-08-01T00:00:00Z",
        )
        # Provide and lock a SELLER wire so the ERR_WIRE_NOT_LOCKED check
        # passes and we reach the routing check (PRD §2.10 priority order).
        seller_wire = setup_locked_wire(
            actors, base_e["agreement"]["id"], party="SELLER",
            voice_callback_reference="VC-EE",
        )
        res = api.create_disbursement(
            create_disbursement_payload(
                escrow_account_id=base_e["escrow"]["id"],
                wire_instruction_id=seller_wire["id"],
                purpose="SELLER_PROCEEDS",
                amount_cents=40_000_000,
            ),
            actors["eo"],
        )
        validate_error(res, "ERR_EXCHANGE_ROUTING_REQUIRED", expected_status=422)
