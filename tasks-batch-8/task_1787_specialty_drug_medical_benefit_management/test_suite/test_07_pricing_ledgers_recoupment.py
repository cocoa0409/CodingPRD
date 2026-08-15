"""Claim pricing arithmetic, ASP retroactive repricing cascades, and the provider
payment ledger with recoupment posture (PRD §2.6, §2.10, §3.3, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_claim_adjustment,
    assert_provider_account,
    assert_version_incremented,
    get_auth,
    get_claim,
    get_provider,
    list_adjustments_for_claim,
    pay_claim,
    publish_rate,
    setup_approved_scenario,
    submit_claim,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
MPO = TEST_USERS["mpo_headers"]


class TestPerComponentRounding:
    def _scenario_325(self):
        return setup_approved_scenario(
            drug_overrides={"j_code": "J1745", "drug_name": "RoundDrug"},
            rate_cents=325,
            member_id="MEM-3",
        )

    def test_allowed_amount_uses_per_component_rounding(self, api):
        """PRD §3.6: "Rounding is pinned per component: the drug component —
        `billed_units` times the rate times one plus the total add-on — is rounded half-up
        to whole cents; the waste component — `payable_waste_units` times the rate times
        one plus the same add-on — is rounded half-up independently; and
        `allowed_amount_cents` is the sum of the two rounded components. Summing first and
        rounding once is non-conformant: at a 325-cent rate with the six percent base
        add-on, 3 billed units plus 1 payable waste unit yields 1034 plus 345 — an allowed
        amount of 1379 cents — where sum-first arithmetic would yield 1378."

        Design: Difficulty/combinatorial_formula/claim_allowed_per_component_rounding
        """
        scenario = self._scenario_325()
        claim = submit_claim(
            scenario, billed_units=3, waste_units=1, jw_modifier=True
        )
        assert claim["status"] == "APPROVED_FOR_PAYMENT"
        assert claim["payable_waste_units"] == 1
        # round(3 x 325 x 1.06) = 1034 and round(1 x 325 x 1.06) = 345.
        assert claim["allowed_amount_cents"] == 1379, (
            f"per-component rounding must give 1379 (not 1378), got {claim['allowed_amount_cents']}"
        )
        assert claim["asp_rate_cents"] == 325
        assert claim["addon_pct_applied"] == 0.06

    def test_member_cost_share_follows_allowed_amount(self, api):
        """PRD §3.6: "Otherwise it is twenty percent of `allowed_amount_cents`, reduced by
        the `member_copay_waiver_pct` of any `ACTIVE` biosimilar policy covering the
        claim's drug and service date — zero waiver when none — rounded half-up once at
        the end." round(1379 x 0.20) = 276.

        Design: Difficulty/combinatorial_formula/claim_allowed_per_component_rounding
        """
        scenario = self._scenario_325()
        claim = submit_claim(
            scenario, billed_units=3, waste_units=1, jw_modifier=True
        )
        assert claim["allowed_amount_cents"] == 1379
        assert claim["member_cost_share_cents"] == 276


class TestAspRetroCascade:
    def _paid(self):
        # Claim of 2 units at rate 500 -> round(2 x 500 x 1.06) = 1060, PAID.
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J3490", "drug_name": "CascadeDrug"},
            rate_cents=500,
            member_id="MEM-6",
        )
        claim = submit_claim(scenario, billed_units=2, site_of_care="HOPD")
        assert claim["allowed_amount_cents"] == 1060
        claim = pay_claim(claim["id"])
        assert claim["status"] == "PAID"
        return scenario, claim

    def test_new_schedule_supersedes_and_reprices_paid_claim(self, api):
        """PRD §3.3: "Every other `EFFECTIVE` schedule for the same drug becomes
        `SUPERSEDED`"; "A claim already `PAID` or `ADJUSTED` moves to — or remains in —
        `ADJUSTED`; its `allowed_amount_cents` and `asp_schedule_id_used` are updated".
        New rate 600: round(2 x 600 x 1.06) = 1272.

        Design: Difficulty/transitive_cascade/asp_retro_schedule_to_ledger_cascade
        """
        scenario, claim = self._paid()
        sched_2 = publish_rate(scenario["drug"]["id"], asp_rate_cents=600)
        assert sched_2["status"] == "EFFECTIVE"

        sched_1 = validate_success(
            api.get_asp_schedule(scenario["schedule"]["id"], ADMIN)
        )
        assert sched_1["status"] == "SUPERSEDED", "prior EFFECTIVE schedule superseded"

        adjusted = get_claim(claim["id"])
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["allowed_amount_cents"] == 1272
        assert adjusted["asp_schedule_id_used"] == sched_2["id"]

    def test_adjustment_record_and_ledger_sync(self, api):
        """PRD §3.3: "an immutable adjustment record is written carrying `claim_id`, the
        triggering `asp_schedule_id`, `old_allowed_cents`, `new_allowed_cents`, their
        signed difference `delta_cents` (negative when the new rate pays less), and
        `reason` `ASP_RETRO`."
        PRD §2.10: "`cumulative_paid_cents` ... each retroactive repricing adjustment adds
        that adjustment's `delta_cents`, which may be negative."

        Design: Difficulty/transitive_cascade/asp_retro_schedule_to_ledger_cascade
        """
        scenario, claim = self._paid()
        sched_2 = publish_rate(scenario["drug"]["id"], asp_rate_cents=600)

        adjustments = list_adjustments_for_claim(claim["id"])
        assert len(adjustments) == 1
        adj = adjustments[0]
        assert_claim_adjustment(adj)
        assert adj["old_allowed_cents"] == 1060
        assert adj["new_allowed_cents"] == 1272
        assert adj["delta_cents"] == 212
        assert adj["asp_schedule_id"] == sched_2["id"]

        provider = get_provider(scenario["provider"]["id"])
        assert_provider_account(provider)
        # 1060 paid + 212 positive delta; a positive delta creates no recoupment.
        assert provider["cumulative_paid_cents"] == 1272
        assert provider["recoupment_balance_cents"] == 0
        assert provider["status"] == "ACTIVE"


class TestCompensatingInvariant:
    def _scenario_paid(self):
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J3600", "drug_name": "InvariantDrug"},
            rate_cents=500,
            member_id="MEM-16",
        )
        claim = submit_claim(scenario, billed_units=2, site_of_care="HOPD")
        claim = pay_claim(claim["id"])
        return scenario, claim

    def test_compensating_repricing_restores_ledger_exactly(self, api):
        """PRD §2.10: "`cumulative_paid_cents` is the running total the plan has paid the
        provider: a claim payment adds the claim's `allowed_amount_cents`, and each
        retroactive repricing adjustment adds that adjustment's `delta_cents`, which may
        be negative." A 500 -> 600 correction (+212) followed by its 600 -> 500 inverse
        (-212) conserves the ledger at the original 1060 and nets the adjustments to zero.

        Design: Difficulty/compensating_invariant/provider_ledger_adjust_restore_invariant
        """
        scenario, claim = self._scenario_paid()
        publish_rate(scenario["drug"]["id"], asp_rate_cents=600)
        publish_rate(scenario["drug"]["id"], asp_rate_cents=500)

        claim_after = get_claim(claim["id"])
        assert claim_after["status"] == "ADJUSTED"
        assert claim_after["allowed_amount_cents"] == 1060, "claim returns to original price"

        adjustments = list_adjustments_for_claim(claim["id"])
        assert len(adjustments) == 2
        deltas = sorted(a["delta_cents"] for a in adjustments)
        assert deltas == [-212, 212]
        assert sum(a["delta_cents"] for a in adjustments) == 0, "adjustments net to zero"

        provider = get_provider(scenario["provider"]["id"])
        assert provider["cumulative_paid_cents"] == 1060, "ledger exactly conserved"

    def test_negative_delta_recoupment_posture_persists(self, api):
        """PRD §2.10: "`recoupment_balance_cents` accumulates outstanding negative
        repricing deltas as positive cents — money the plan must recover from the
        provider. The moment a repricing leaves `recoupment_balance_cents` greater than
        zero, the account flips automatically from `ACTIVE` to `RECOUPMENT_HOLD`".

        Design: Difficulty/compensating_invariant/provider_ledger_adjust_restore_invariant
        """
        scenario, claim = self._scenario_paid()
        publish_rate(scenario["drug"]["id"], asp_rate_cents=600)
        publish_rate(scenario["drug"]["id"], asp_rate_cents=500)

        provider = get_provider(scenario["provider"]["id"])
        # The -212 delta leaves an outstanding recoupment balance; the hold posture is
        # not part of the conserved quantity and persists until settle-recoupment.
        assert provider["recoupment_balance_cents"] == 212
        assert provider["status"] == "RECOUPMENT_HOLD"


class TestRecoupmentHoldLifecycle:
    def test_recoupment_hold_blocks_pay_until_settled(self, api):
        """PRD §2.10: "while on hold every payment to that provider is refused. Settling
        recoupment zeroes the balance and returns the account to `ACTIVE`."
        PRD §3.3: "While an account is in `RECOUPMENT_HOLD`, payments to it are refused
        with `ERR_PROVIDER_RECOUPMENT_HOLD`"; "attempting settlement on an account not on
        hold fails with `ERR_PROVIDER_NOT_ON_HOLD`". A claim still unpaid "is instead
        repriced in place ... and no adjustment record or ledger movement occurs".

        Design: Corner/state_machines/recoupment_hold_blocks_pay_until_settled
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J8300", "drug_name": "HoldDrug"},
            member_id="MEM-H1",
        )
        claim_a = submit_claim(scenario, billed_units=2, site_of_care="HOPD")
        claim_a = pay_claim(claim_a["id"])
        assert claim_a["allowed_amount_cents"] == 1060
        claim_b = submit_claim(scenario, billed_units=2, site_of_care="HOPD")
        assert claim_b["status"] == "APPROVED_FOR_PAYMENT"

        # Rate cut 500 -> 400: A adjusted (delta -212 -> hold); B repriced in place.
        publish_rate(scenario["drug"]["id"], asp_rate_cents=400)
        provider = get_provider(scenario["provider"]["id"])
        assert provider["status"] == "RECOUPMENT_HOLD"
        assert provider["recoupment_balance_cents"] == 212
        b_after = get_claim(claim_b["id"])
        assert b_after["allowed_amount_cents"] == 848  # round(2 x 400 x 1.06)
        assert list_adjustments_for_claim(claim_b["id"]) == [], "unpaid reprice writes no adjustment"

        resp = api.pay_claim(claim_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_RECOUPMENT_HOLD, 409)

        settled = validate_success(
            api.settle_recoupment(scenario["provider"]["id"], ADMIN)
        )
        assert settled["status"] == "ACTIVE"
        assert settled["recoupment_balance_cents"] == 0

        paid_b = pay_claim(claim_b["id"])
        assert paid_b["status"] == "PAID"
        provider = get_provider(scenario["provider"]["id"])
        # 1060 (A paid) - 212 (A retro delta) + 848 (B paid at repriced amount).
        assert provider["cumulative_paid_cents"] == 1696

        resp = api.settle_recoupment(scenario["provider"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_ON_HOLD, 409)


class TestImmediateConsistency:
    def test_reprice_cascade_visible_in_immediate_reads(self, api):
        """PRD §2: "Every mutation, together with all cascades it triggers, commits
        atomically within the request that caused it." PRD §3.3: the delta "is then
        applied to the provider's ledger per §2.10 ... and once every candidate claim has
        been processed, any provider left with a positive recoupment balance flips to
        `RECOUPMENT_HOLD`."

        Design: Corner/consistency_model/immediate_visibility_after_cascade
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J7700", "drug_name": "ImmDrug"},
            member_id="MEM-K1",
        )
        claim = submit_claim(scenario, billed_units=2, site_of_care="HOPD")
        pay_claim(claim["id"])

        sched_lo = publish_rate(scenario["drug"]["id"], asp_rate_cents=400)

        # The very next reads observe the completed cascade.
        adjusted = get_claim(claim["id"])
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["allowed_amount_cents"] == 848

        adjustments = list_adjustments_for_claim(claim["id"])
        assert len(adjustments) == 1
        assert adjustments[0]["delta_cents"] == -212
        assert adjustments[0]["asp_schedule_id"] == sched_lo["id"]

        provider = get_provider(scenario["provider"]["id"])
        assert provider["cumulative_paid_cents"] == 848
        assert provider["recoupment_balance_cents"] == 212
        assert provider["status"] == "RECOUPMENT_HOLD"


class TestVersionIncrements:
    def test_versions_increment_on_each_mutation(self, api):
        """PRD §2.5: "`version`, a system-managed integer that increments with every
        mutation ... `updated_at`, in the same format, refreshed on every mutation".
        PRD §3.6: "Payment stamps `paid_at` — null until this moment — with the current
        clock timestamp".

        Design: Corner/cross_cutting_layers/claim_version_increments_on_mutation
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J7500", "drug_name": "VerDrug"},
            member_id="MEM-X2",
        )
        auth_v_after_approve = scenario["auth"]["version"]

        claim = submit_claim(scenario, billed_units=10)
        claim_v_at_create = claim["version"]
        assert claim.get("paid_at") is None, "paid_at is null until payment (PRD §3.6)"

        # The administration debit cascades onto the auth: its version must advance.
        auth_after_debit = get_auth(scenario["auth"]["id"])
        assert_version_incremented(auth_after_debit["version"], auth_v_after_approve)

        paid = pay_claim(claim["id"])
        assert paid["version"] == claim_v_at_create + 1, "pay is exactly one mutation"
        assert paid["paid_at"] is not None
        assert paid["paid_at"].startswith("2026-08-01T00:00:00"), (
            "paid_at carries the logical clock timestamp (PRD §2.4 startup value)"
        )
