"""Unit walks, QA, deficiency findings, and the deferred-maintenance rollup."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_completed_inspection,
    add_finding,
    add_unit,
    create_kicked_off_acquisition,
    get_acquisition,
    get_success_data,
    make_property_ops_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

POL1 = TEST_USERS["property_ops_headers"]
POL2 = make_property_ops_headers("pol-2")
UM1 = TEST_USERS["underwriting_manager_headers"]

BIG_PRICE = 1_000_000_000  # 3% = 30000000; 5% = 50000000


def _big_deal_with_completed_inspection(api):
    acq = create_kicked_off_acquisition(
        property_name="Big Deal", agreed_purchase_price_cents=BIG_PRICE)
    unit = add_unit(acq["id"])
    insp = add_completed_inspection(unit["id"], no_findings=False,
                                    condition_rating=2)
    return acq, unit, insp


class TestMaintenanceEstimateBasisDivergence:
    def test_verified_cost_switches_with_basis_patch(self, api):
        """PRD §3.4: "The base is `inspector_estimate_cents` when the
        acquisition's `maintenance_estimate_basis` is `INSPECTOR_BASIS` and
        `seller_estimate_cents` when it is `SELLER_BASIS`. The base is
        multiplied by a severity multiplier — 1.00 for severity 1 or 2, 1.15
        for severity 3, 1.25 for severity 4, and 1.40 for severity 5 — and
        that product is rounded half up to integer cents before the flat
        category loading is added: plus 15000 cents for `LIFE_SAFETY`, plus
        5000 cents for `CODE_COMPLIANCE`, and nothing for `MAJOR_SYSTEMS` or
        `COSMETIC`."
        PRD §3.4: "changing the acquisition's basis re-derives every finding's
        `verified_cost_cents` and the rollup in one pass."

        Design: Difficulty/dual_variant_calc/maintenance_estimate_basis_divergence
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        finding = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                              seller_estimate_cents=18_000_000,
                              inspector_estimate_cents=20_000_000)

        verified = get_success_data(api.verify_finding(finding["id"], POL1))
        assert verified["verified_cost_cents"] == 28_015_000, (
            "INSPECTOR_BASIS: round(20000000 x 1.40) + 15000"
        )

        patched = get_success_data(api.patch_acquisition(
            acq["id"], {"maintenance_estimate_basis": "SELLER_BASIS"}, UM1))
        assert patched["deferred_maintenance_total_cents"] == 25_215_000, (
            "basis switch re-derives the rollup"
        )
        findings, _ = validate_paginated(
            api.list_inspection_findings(insp["id"], POL1))
        assert findings[0]["verified_cost_cents"] == 25_215_000, (
            "SELLER_BASIS: round(18000000 x 1.40) + 15000"
        )

    def test_basis_variants_diverge_on_identical_finding(self, api):
        """PRD §3.1: "Switching the basis re-derives every finding's
        `verified_cost_cents` and the deferred-maintenance rollup from the
        other estimate column."
        PRD §3.4: "`OPEN`, `DISPUTED`, and `EXCLUDED` findings contribute
        nothing."

        Design: Difficulty/dual_variant_calc/maintenance_estimate_basis_divergence
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        finding = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                              seller_estimate_cents=18_000_000,
                              inspector_estimate_cents=20_000_000)
        get_success_data(api.verify_finding(finding["id"], POL1))
        before = get_acquisition(acq["id"])
        assert before["deferred_maintenance_total_cents"] == 28_015_000

        get_success_data(api.patch_acquisition(
            acq["id"], {"maintenance_estimate_basis": "SELLER_BASIS"}, UM1))
        after = get_acquisition(acq["id"])
        assert after["deferred_maintenance_total_cents"] == 25_215_000
        assert 28_015_000 - 25_215_000 == 2_800_000, (
            "the variant switch moves the rollup by exactly 2800000 with no "
            "new findings"
        )


class TestTieredRollupCrossesPostureThresholds:
    def test_findings_verify_rollup_and_posture_stepwise(self, api):
        """PRD §3.4: "The acquisition's `deferred_maintenance_total_cents` is
        the sum of `verified_cost_cents` over findings in `VERIFIED` status
        whose unit is not `EXCLUDED`."
        PRD §3.9: "Failing that, the posture is `AT_RISK` when any of three
        conditions holds: the deferred-maintenance total is strictly greater
        than 3 percent of the price (price times 0.03 rounded half up); ..."
        PRD §3.9: "Both threshold comparisons are strict: a
        deferred-maintenance total exactly equal to the 3-percent or 5-percent
        threshold does not cross it."

        Design: Difficulty/combinatorial_formula/deferred_maintenance_tiered_rollup_mode_a
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        f1 = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                         seller_estimate_cents=18_000_000,
                         inspector_estimate_cents=20_000_000)
        f2 = add_finding(insp["id"], category="MAJOR_SYSTEMS", severity=4,
                         seller_estimate_cents=4_800_000,
                         inspector_estimate_cents=5_000_000)
        f3 = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                         seller_estimate_cents=11_000_000,
                         inspector_estimate_cents=12_000_000)

        v1 = get_success_data(api.verify_finding(f1["id"], POL1))
        assert v1["verified_cost_cents"] == 28_015_000
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == 28_015_000
        assert acq_now["readiness_posture"] == "ON_TRACK", (
            "28015000 <= 30000000 = 3% of price: still ON_TRACK"
        )

        v2 = get_success_data(api.verify_finding(f2["id"], POL1))
        assert v2["verified_cost_cents"] == 6_250_000
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == 34_265_000
        assert acq_now["readiness_posture"] == "AT_RISK", (
            "34265000 crosses 3% (30000000) but not 5% (50000000)"
        )

        v3 = get_success_data(api.verify_finding(f3["id"], POL1))
        assert v3["verified_cost_cents"] == 16_815_000
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == 51_080_000
        assert acq_now["readiness_posture"] == "BLOCKED", (
            "51080000 crosses the 5% threshold (50000000)"
        )

    def test_severity_tiers_and_category_loadings_combine(self, api):
        """PRD §3.4: "The base is multiplied by a severity multiplier — 1.00
        for severity 1 or 2, 1.15 for severity 3, 1.25 for severity 4, and 1.40
        for severity 5 — and that product is rounded half up to integer cents
        before the flat category loading is added: plus 15000 cents for
        `LIFE_SAFETY`, plus 5000 cents for `CODE_COMPLIANCE`, and nothing for
        `MAJOR_SYSTEMS` or `COSMETIC`."

        Design: Difficulty/combinatorial_formula/deferred_maintenance_tiered_rollup_mode_a
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        # Three findings exercising the non-linear tier jumps and loadings.
        f1 = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                         seller_estimate_cents=18_000_000,
                         inspector_estimate_cents=20_000_000)
        f2 = add_finding(insp["id"], category="MAJOR_SYSTEMS", severity=4,
                         seller_estimate_cents=4_800_000,
                         inspector_estimate_cents=5_000_000)
        f3 = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                         seller_estimate_cents=11_000_000,
                         inspector_estimate_cents=12_000_000)
        costs = []
        for finding in (f1, f2, f3):
            verified = get_success_data(api.verify_finding(finding["id"], POL1))
            costs.append(verified["verified_cost_cents"])
        assert costs == [28_015_000, 6_250_000, 16_815_000], (
            "round(base x multiplier) + category loading, per finding"
        )
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == sum(costs)
        assert acq_now["readiness_posture"] == "BLOCKED"


class TestQaAcceptFindingsRollupCascade:
    def test_qa_accept_cascades_findings_to_verified_and_flips_posture(self, api):
        """PRD §3.4: "Acceptance lands the inspection in the terminal
        `QA_ACCEPTED` state and cascades in order: every finding of this
        inspection still `OPEN` moves to `VERIFIED`; because findings entered
        the rollup, the acquisition's `deferred_maintenance_total_cents`
        recomputes; because the rollup moved, `readiness_posture` recomputes
        and may cross the 3% or 5% thresholds described in §3.9; and the unit's
        `walk_accepted` flag recomputes, possibly promoting the unit."

        Design: Difficulty/transitive_cascade/qa_accept_findings_rollup_posture_cascade
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        f1 = add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                         seller_estimate_cents=18_000_000,
                         inspector_estimate_cents=20_000_000)
        f2 = add_finding(insp["id"], category="MAJOR_SYSTEMS", severity=4,
                         seller_estimate_cents=4_800_000,
                         inspector_estimate_cents=5_000_000)

        accepted = validate_success(api.qa_accept_inspection(insp["id"], POL2))
        assert accepted["status"] == "QA_ACCEPTED"

        findings, _ = validate_paginated(
            api.list_inspection_findings(insp["id"], POL1))
        by_id = {f["id"]: f for f in findings}
        assert by_id[f1["id"]]["status"] == "VERIFIED", (
            "QA accept flips OPEN findings to VERIFIED without per-finding calls"
        )
        assert by_id[f2["id"]]["status"] == "VERIFIED"
        assert by_id[f1["id"]]["verified_cost_cents"] == 28_015_000
        assert by_id[f2["id"]]["verified_cost_cents"] == 6_250_000

        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == 34_265_000
        assert acq_now["readiness_posture"] == "AT_RISK", (
            "34265000 > 30000000 (3% of price) but <= 50000000 (5%)"
        )

    def test_qa_accept_promotes_unit_walk_accepted_flag(self, api):
        """PRD §3.2: "`walk_accepted` is true when the unit's latest
        non-cancelled walk inspection stands at `QA_ACCEPTED`."
        PRD §3.2: "The first time any one of the three flags turns true, the
        unit moves from `REGISTERED` to `CLEARING`."

        Design: Difficulty/transitive_cascade/qa_accept_findings_rollup_posture_cascade
        """
        acq, unit, insp = _big_deal_with_completed_inspection(api)
        add_finding(insp["id"], category="LIFE_SAFETY", severity=5,
                    seller_estimate_cents=18_000_000,
                    inspector_estimate_cents=20_000_000)
        add_finding(insp["id"], category="MAJOR_SYSTEMS", severity=4,
                    seller_estimate_cents=4_800_000,
                    inspector_estimate_cents=5_000_000)

        get_success_data(api.qa_accept_inspection(insp["id"], POL2))
        unit_now = get_success_data(api.get_unit(unit["id"], POL1))
        assert unit_now["walk_accepted"] is True
        assert unit_now["status"] == "CLEARING", (
            "the first readiness flag turning true moves REGISTERED -> CLEARING"
        )
        assert get_acquisition(acq["id"])["readiness_posture"] == "AT_RISK"


class TestInspectionQaCycle:
    def test_qa_reject_reschedule_cycle(self, api):
        """PRD §3.4: "QA rejection likewise requires a caller different from
        the completer, moves the inspection to `QA_REJECTED`, and forces the
        acquisition's posture to at least `AT_RISK` while any rejected
        inspection exists. Rescheduling a rejected walk supplies a fresh
        `walk_start` and `walk_end` — the inspector-overlap check applies again
        — returns the inspection to `SCHEDULED`, increments `reschedule_count`
        by one, clears `condition_rating` and `no_findings_declared`, and
        recomputes posture."

        Design: Difficulty/non_linear_state_machine/inspection_qa_reject_reschedule_cycle
        """
        acq = create_kicked_off_acquisition(property_name="QA Deal")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)
        get_success_data(api.complete_inspection(insp["id"], 3, True, POL1))

        rejected = validate_success(api.qa_reject_inspection(
            insp["id"], "photos illegible", POL2))
        assert rejected["status"] == "QA_REJECTED"
        assert get_acquisition(acq["id"])["readiness_posture"] == "AT_RISK"

        rescheduled = validate_success(api.reschedule_inspection(
            insp["id"], "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z", POL1))
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["reschedule_count"] == 1

        completed = get_success_data(api.complete_inspection(insp["id"], 4, True, POL1))
        assert completed["status"] == "COMPLETED"
        accepted = get_success_data(api.qa_accept_inspection(insp["id"], POL2))
        assert accepted["status"] == "QA_ACCEPTED", (
            "one full reject/reschedule loop terminates at QA_ACCEPTED"
        )

    def test_reschedule_increments_count_and_clears_completion_fields(self, api):
        """PRD §3.4: "Rescheduling a rejected walk supplies a fresh
        `walk_start` and `walk_end` — the inspector-overlap check applies again
        — returns the inspection to `SCHEDULED`, increments `reschedule_count`
        by one, clears `condition_rating` and `no_findings_declared`, and
        recomputes posture."

        Design: Difficulty/non_linear_state_machine/inspection_qa_reject_reschedule_cycle
        """
        acq = create_kicked_off_acquisition(property_name="QA Deal Two")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)
        get_success_data(api.complete_inspection(insp["id"], 3, True, POL1))
        get_success_data(api.qa_reject_inspection(insp["id"], "blurry", POL2))

        rescheduled = get_success_data(api.reschedule_inspection(
            insp["id"], "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z", POL1))
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["reschedule_count"] == 1
        assert rescheduled.get("condition_rating") is None, (
            "reschedule clears the recorded rating"
        )
        assert rescheduled.get("no_findings_declared") is None, (
            "reschedule clears the no-findings declaration"
        )


class TestInspectionGates:
    def test_qa_accept_from_scheduled_returns_invalid_state(self, api):
        """PRD §3.4: "Quality assurance then judges the walk." — QA acceptance
        is defined only on a COMPLETED walk.
        PRD §5: `ERR_INVALID_STATE_TRANSITION` is HTTP 409 ("Transition not
        allowed from the entity's current state")."

        Design: Corner/state_machines/qa_accept_from_scheduled_returns_invalid_state
        """
        acq = create_kicked_off_acquisition(property_name="Inv T")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)

        resp = api.qa_accept_inspection(insp["id"], POL2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_inspection(insp["id"], POL1))
        assert after["status"] == "SCHEDULED"

    def test_finding_requires_completed_inspection(self, api):
        """PRD §3.4: "Deficiency findings are recorded against a `COMPLETED`
        inspection — recording against an inspection in any other state is
        rejected with `ERR_INSPECTION_NOT_COMPLETED` — with a `category` of
        `LIFE_SAFETY`, `MAJOR_SYSTEMS`, `CODE_COMPLIANCE`, or `COSMETIC`, ..."

        Design: Corner/validations/finding_requires_completed_inspection
        """
        acq = create_kicked_off_acquisition(property_name="Find Gate")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)

        resp = api.create_finding(
            {"inspection_id": insp["id"], "category": "COSMETIC", "severity": 1,
             "seller_estimate_cents": 100000, "inspector_estimate_cents": 120000},
            POL1)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED, 409)

    def test_qa_accept_requires_findings_when_not_declared(self, api):
        """PRD §3.4: "QA acceptance requires that the caller differ from
        `completed_by_user_id` (else `ERR_SOD_VIOLATION`) and, when
        `no_findings_declared` is false, that at least one deficiency finding
        exist for the inspection (else `ERR_FINDINGS_REQUIRED`)."

        Design: Corner/validations/qa_accept_requires_findings_when_not_declared
        """
        acq = create_kicked_off_acquisition(property_name="NoFind")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)
        get_success_data(api.complete_inspection(insp["id"], 3, False, POL1))

        resp = api.qa_accept_inspection(insp["id"], POL2)
        validate_error(resp, ApiErrorId.ERR_FINDINGS_REQUIRED, 409)
        after = get_success_data(api.get_inspection(insp["id"], POL1))
        assert after["status"] == "COMPLETED"

    def test_qa_accept_by_completer_is_sod_violation(self, api):
        """PRD §2.8: "A walk inspection's QA caller — accept or reject — must
        differ from the `completed_by_user_id` who performed the walk. Each
        breach is rejected with `ERR_SOD_VIOLATION` (HTTP 409)."
        PRD §3.4: "Completing the walk ... stamps `completed_by_user_id` with
        the caller's `X-User-ID`."

        Design: Corner/validations/qa_and_statement_sod_denials
        """
        acq = create_kicked_off_acquisition(property_name="SoD Deal")
        unit = add_unit(acq["id"])
        insp = get_success_data(api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T10:00:00Z"}, POL1), 201)
        get_success_data(api.complete_inspection(insp["id"], 4, True, POL1))

        resp = api.qa_accept_inspection(insp["id"], POL1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)

        accepted = validate_success(api.qa_accept_inspection(insp["id"], POL2))
        assert accepted["status"] == "QA_ACCEPTED"


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §3.4: "Verification and re-verification recompute this cost and
        the acquisition rollup; disputing a verified finding removes it from
        the rollup and recomputes; changing the acquisition's basis re-derives
        every finding's `verified_cost_cents` and the rollup in one pass."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        acq = create_kicked_off_acquisition(
            property_name="Cons Deal", agreed_purchase_price_cents=BIG_PRICE)
        unit = add_unit(acq["id"])
        insp = add_completed_inspection(unit["id"], no_findings=False,
                                        condition_rating=3)
        finding = add_finding(insp["id"], category="COSMETIC", severity=2,
                              seller_estimate_cents=100_000,
                              inspector_estimate_cents=120_000)

        verified = get_success_data(api.verify_finding(finding["id"], POL1))
        assert verified["verified_cost_cents"] == 120_000, (
            "severity 2 -> multiplier 1.00, COSMETIC loading 0"
        )
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deferred_maintenance_total_cents"] == 120_000, (
            "the very next GET reflects the recomputed rollup"
        )
        assert acq_now["readiness_posture"] == "ON_TRACK"
