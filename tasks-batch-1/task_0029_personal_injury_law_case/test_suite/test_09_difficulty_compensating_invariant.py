"""Difficulty Rule 9 — compensating_invariant.

Conservation invariants across distinct conserved quantities:

  • Settlement-money conservation: gross == fee + lien_payout + net (PRD §3.7)
  • Damages-aggregate consistency: INCLUDE then EXCLUDE leaves the denormalized
    Case.included_damages_total_cents at its pre-include value (PRD §3.3)
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_proposed_damages,
    include_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    create_offer,
    accept_offer,
    get_case_version,
    get_case,
    get_disbursement_for_case,
    assert_money_conservation,
    api_client,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: settlement_money_conservation_gross_equals_fee_plus_liens_plus_net
# =============================================================================


class TestSettlementMoneyConservationGrossEqualsFeePlusLiensPlusNet:
    """Once a case settles and the disbursement is created, the invariant
    Case.gross_settlement_cents == Disbursement.contingency_fee_cents +
    Disbursement.total_lien_payout_cents + Disbursement.net_to_client_cents
    must hold exactly in integer cents."""

    def _settle_canonical_case(self):
        """Pre-suit settle: gross=6_000_000, lien asserted 1_500_000."""
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-9a")
        send_demand_letter(dl["id"], partner_user_id="partner-9a")
        create_lien(case["id"], provider["id"], 1_500_000)
        offer = create_offer(case["id"], 6_000_000, "CARRIER")
        case_v = get_case_version(case["id"])
        accept_offer(offer["id"], case_v, partner_user_id="partner-9a")
        return case["id"]

    def test_money_conservation_holds_after_settle(self, api):
        """PRD §3.7: "The disbursement also captures the contingency fee and
        the `net_to_client_cents`, which is the gross settlement minus the
        contingency fee minus the total lien payout. The order is pinned:
        gross is stamped first, fee is computed against the gross and the
        filed-in-court flag, the distributable-to-liens amount is taken as
        gross minus fee, the waterfall runs against that distributable amount,
        the total lien payout is summed, and the net equals gross minus fee
        minus payout."

        Design: Difficulty/compensating_invariant/settlement_money_conservation_gross_equals_fee_plus_liens_plus_net
        """
        case_id = self._settle_canonical_case()
        case_after = get_case(case_id)
        disb = get_disbursement_for_case(case_id)
        assert_money_conservation(disb, case_after["gross_settlement_cents"])

    def test_money_conservation_with_concrete_numbers(self, api):
        """PRD §3.7: "The disbursement also captures the contingency fee and
        the `net_to_client_cents`, which is the gross settlement minus the
        contingency fee minus the total lien payout. The order is pinned:
        gross is stamped first, fee is computed against the gross and the
        filed-in-court flag, the distributable-to-liens amount is taken as
        gross minus fee, the waterfall runs against that distributable amount,
        the total lien payout is summed, and the net equals gross minus fee
        minus payout."

        Design: Difficulty/compensating_invariant/settlement_money_conservation_gross_equals_fee_plus_liens_plus_net
        """
        case_id = self._settle_canonical_case()
        case_after = get_case(case_id)
        disb = get_disbursement_for_case(case_id)
        # gross=6_000_000, fee=1_999_800, payout=1_500_000, net=2_500_200.
        assert case_after["gross_settlement_cents"] == 6_000_000
        assert disb["contingency_fee_cents"] == 1_999_800
        assert disb["total_lien_payout_cents"] == 1_500_000
        assert disb["net_to_client_cents"] == 2_500_200
        # And the conservation sum.
        assert (
            disb["contingency_fee_cents"]
            + disb["total_lien_payout_cents"]
            + disb["net_to_client_cents"]
        ) == 6_000_000


# =============================================================================
# Instance: damages_total_round_trip_proposed_included_excluded_zero_drift
# =============================================================================


class TestDamagesTotalRoundTripProposedIncludedExcludedZeroDrift:
    """Case.included_damages_total_cents is a denormalized sum over INCLUDED
    items. A PROPOSED→INCLUDED→EXCLUDED round-trip on one item must leave the
    total at its pre-include value — zero drift on the aggregate."""

    def test_include_then_exclude_returns_total_to_pre_include_value(self, api):
        """PRD §3.3: "On inclusion the system recomputes
        `Case.included_damages_total_cents` as the sum of `amount_cents`
        across every `INCLUDED` item on the case (a depth-two cascade off the
        include action) and increments `Case.version` by one."
        PRD §3.3: "Pulling an already-`INCLUDED` item back out is more
        sensitive: only a `ManagingPartner` may move `INCLUDED → EXCLUDED`,
        the case must again be `ACTIVE`, `DEMAND_SENT`, or `IN_NEGOTIATION`,
        and no demand letter on the case may be in `SENT` or `ACKNOWLEDGED`
        status (because a line item that already shaped a transmitted demand
        cannot be silently retracted); failure on the demand-letter check is
        `ERR_CROSS_ENTITY_STATE`. The retraction recomputes
        `Case.included_damages_total_cents` and bumps `Case.version` by one."

        Design: Difficulty/compensating_invariant/damages_total_round_trip_proposed_included_excluded_zero_drift
        """
        from test_helpers import TEST_USERS
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        # Baseline: one INCLUDED MEDICAL_BILLS=500_000.
        create_included_damages(case["id"], "MEDICAL_BILLS", 500_000)
        baseline_case = get_case(case["id"])
        assert baseline_case["included_damages_total_cents"] == 500_000

        # Round-trip a new PROPERTY=300_000 item: INCLUDE then EXCLUDE.
        item = create_proposed_damages(case["id"], "PROPERTY", 300_000)
        include_damages(item["id"])
        mid_case = get_case(case["id"])
        assert mid_case["included_damages_total_cents"] == 800_000

        # EXCLUDE the just-included item via ManagingPartner (the only role
        # allowed to move INCLUDED→EXCLUDED per PRD §3.3).
        partner_headers = TEST_USERS["managing_partner_headers"]
        excl_res = api_client.exclude_damages_item(item["id"], partner_headers)
        validate_success(excl_res, 200)

        final_case = get_case(case["id"])
        assert final_case["included_damages_total_cents"] == 500_000

    def test_excluded_item_status_is_excluded_and_baseline_item_stays_included(self, api):
        """PRD §3.3: "A `PROPOSED` item moves into the case's working damages
        model when the `Attorney` promotes it `PROPOSED → INCLUDED`."
        PRD §3.3: "Pulling an already-`INCLUDED` item back out is more
        sensitive: only a `ManagingPartner` may move `INCLUDED → EXCLUDED`,
        the case must again be `ACTIVE`, `DEMAND_SENT`, or `IN_NEGOTIATION`,
        and no demand letter on the case may be in `SENT` or `ACKNOWLEDGED`
        status (because a line item that already shaped a transmitted demand
        cannot be silently retracted); failure on the demand-letter check is
        `ERR_CROSS_ENTITY_STATE`. The retraction recomputes
        `Case.included_damages_total_cents` and bumps `Case.version` by one."

        Design: Difficulty/compensating_invariant/damages_total_round_trip_proposed_included_excluded_zero_drift
        """
        from test_helpers import TEST_USERS
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        baseline_item = create_included_damages(case["id"], "MEDICAL_BILLS", 500_000)
        rt_item = create_proposed_damages(case["id"], "PROPERTY", 300_000)
        include_damages(rt_item["id"])

        partner_headers = TEST_USERS["managing_partner_headers"]
        attorney_headers = TEST_USERS["attorney_headers"]
        api_client.exclude_damages_item(rt_item["id"], partner_headers)

        # Re-read both items.
        rt_after = validate_success(
            api.get_damages_item(rt_item["id"], attorney_headers), 200
        )
        baseline_after = validate_success(
            api.get_damages_item(baseline_item["id"], attorney_headers), 200
        )
        assert rt_after["status"] == "EXCLUDED"
        assert baseline_after["status"] == "INCLUDED"
