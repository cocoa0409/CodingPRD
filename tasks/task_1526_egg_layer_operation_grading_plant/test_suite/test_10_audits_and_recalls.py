"""Compliance audits, audit calendar spacing, and recall scope/close."""
import pytest

from test_helpers import (
    ApiErrorId,
    audit_payload,
    confirm_grading_run,
    record_production_days,
    recall_payload,
    set_clock,
    setup_active_contract,
    setup_confirmed_lot,
    setup_farm,
    setup_two_laying_flocks,
    validate_error,
    validate_paginated,
    validate_success,
    walk_audit_to_findings,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    CONTRACT_MANAGER,
    QA_MANAGER,
    get_contract,
    get_farm,
    get_flock,
    get_lot,
    get_recall,
    get_salmonella_test,
    create_collected_salmonella_test,
    record_test_result,
)


class TestAuditCalendar:
    def test_audit_calendar_29_day_gap_rejected(self, api):
        """PRD §3.8: "Audits of the same farm must be spaced: the new
        `audit_date` must sit at least 30 days away from the `audit_date` of
        every audit of that farm that has not yet reached a closed state — the
        gap applies in either direction, and a gap of exactly 30 days is
        allowed — else `ERR_AUDIT_INTERVAL_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/audit_calendar_minimum_30_day_buffer
        """
        farm = setup_farm(certification_program="PASTURE")
        validate_success(
            api.create_compliance_audit(
                audit_payload(farm["id"], standard="PASTURE_RAISED",
                              audit_date="2026-04-10"),
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        resp = api.create_compliance_audit(
            audit_payload(farm["id"], standard="FDA_EGG_SAFETY",
                          audit_date="2026-05-09"),  # 29 days later
            COMPLIANCE_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_INTERVAL_TOO_SOON)

    def test_audit_calendar_exactly_30_day_gap_allowed(self, api):
        """PRD §3.8: "Audits of the same farm must be spaced: the new
        `audit_date` must sit at least 30 days away from the `audit_date` of
        every audit of that farm that has not yet reached a closed state — the
        gap applies in either direction, and a gap of exactly 30 days is
        allowed — else `ERR_AUDIT_INTERVAL_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/audit_calendar_minimum_30_day_buffer
        """
        farm = setup_farm(certification_program="PASTURE")
        validate_success(
            api.create_compliance_audit(
                audit_payload(farm["id"], standard="PASTURE_RAISED",
                              audit_date="2026-04-10"),
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        a3 = validate_success(
            api.create_compliance_audit(
                audit_payload(farm["id"], standard="FDA_EGG_SAFETY",
                              audit_date="2026-05-10"),  # exactly 30 days later
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        assert a3["status"] == "SCHEDULED"


class TestAuditCloseRules:
    def test_audit_pass_with_open_corrective_actions_rejected(self, api):
        """PRD §3.8: "Closing with `PASSED` requires `corrective_actions_open`
        to be exactly 0, else `ERR_VALIDATION` (HTTP 400)"
        PRD §3.8: "when `corrective_actions_open` is above zero the farm's
        `compliance_posture` moves to `WATCH` — unless the farm is already
        `SUSPENDED`, which stands"

        Design: Corner/validations/audit_pass_with_open_corrective_actions_rejected
        """
        farm = setup_farm(certification_program="CAGE_FREE")
        audit = walk_audit_to_findings(
            farm["id"], standard="USDA_CAGE_FREE", findings_count=3,
            corrective_actions_open=2,
        )
        assert get_farm(farm["id"])["compliance_posture"] == "WATCH"

        resp = api.close_compliance_audit(
            audit["id"], {"outcome": "PASSED"}, COMPLIANCE_OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
        after = validate_success(
            api.get_compliance_audit(audit["id"], COMPLIANCE_OFFICER)
        )
        assert after["status"] == "FINDINGS_RECORDED"
        assert get_farm(farm["id"])["compliance_posture"] == "WATCH", (
            "open corrective actions keep the farm at WATCH, not SUSPENDED"
        )


class TestRecallRules:
    def test_second_open_recall_per_farm_rejected(self, api):
        """PRD §3.8: "A farm may have only one open recall at a time: creating
        a manual recall while the farm already has one in `INITIATED` or
        `SCOPED` is rejected with `ERR_RECALL_ACTIVE` (HTTP 409)."

        Design: Corner/validations/second_open_recall_per_farm_rejected
        """
        farm = setup_farm()
        r1 = validate_success(
            api.create_recall(
                recall_payload(farm["id"], reason="LABELING"), COMPLIANCE_OFFICER
            ),
            201,
        )
        resp = api.create_recall(
            recall_payload(farm["id"], reason="QUALITY"), COMPLIANCE_OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_RECALL_ACTIVE)
        assert get_recall(r1["id"])["status"] == "INITIATED"

    def test_recall_scope_sweeps_only_matching_lots(self, api):
        """PRD §3.8: "The sweep selects egg lots whose `farm_id` equals the
        recall's farm, whose `flock_id` equals `scope_flock_id` when one is
        set (all flocks when null), whose `pack_date` falls within the
        inclusive pack window, and whose `lifecycle_status` is `FRESH`,
        `RELEASED`, or `ALLOCATED` — and it processes them in `pack_date`
        ascending, `created_at` ascending order."
        PRD §3.8: "The recall's `scoped_lot_count` records how many lots were
        swept, and zero is a legitimate outcome"

        Design: Corner/complexity_layers/recall_scope_sweeps_only_matching_lots
        """
        ctx = setup_two_laying_flocks()
        farm_id = ctx["farm"]["id"]
        flock_a = ctx["flock_a"]["id"]
        flock_b = ctx["flock_b"]["id"]
        # Both flocks produce on 2026-07-31; both runs pack at 2026-08-01.
        record_production_days(flock_a, [{"lay_date": "2026-07-31", "eggs_collected": 240}])
        record_production_days(flock_b, [{"lay_date": "2026-07-31", "eggs_collected": 240}])
        ra1, lots_a1 = confirm_grading_run(flock_a, "A", 240)
        rb1, lots_b1 = confirm_grading_run(flock_b, "A", 240)
        # Flock A produces again; the second run packs at 2026-08-03.
        set_clock("2026-08-03T00:00:00Z")
        record_production_days(flock_a, [{"lay_date": "2026-08-02", "eggs_collected": 240}])
        ra2, lots_a2 = confirm_grading_run(flock_a, "A", 240)
        lot_a1, lot_a2, lot_b1 = lots_a1[0], lots_a2[0], lots_b1[0]
        assert lot_a1["pack_date"][:10] == "2026-08-01"
        assert lot_a2["pack_date"][:10] == "2026-08-03"

        recall = validate_success(
            api.create_recall(
                recall_payload(
                    farm_id,
                    reason="QUALITY",
                    pack_window_start="2026-08-01",
                    pack_window_end="2026-08-02",
                    scope_flock_id=flock_a,
                ),
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        scoped = validate_success(api.scope_recall(recall["id"], COMPLIANCE_OFFICER))
        assert scoped["status"] == "SCOPED"
        assert scoped["scoped_lot_count"] == 1, (
            "only lot A1 (flock A, pack inside the window) matches the selector"
        )
        swept = get_lot(lot_a1["id"])
        assert swept["lifecycle_status"] == "RECALLED"
        assert swept["recall_id"] == recall["id"]

        outside_window = get_lot(lot_a2["id"])
        assert outside_window["lifecycle_status"] == "FRESH"
        assert outside_window["recall_id"] is None
        other_flock = get_lot(lot_b1["id"])
        assert other_flock["lifecycle_status"] == "FRESH"
        assert other_flock["recall_id"] is None

    def test_recall_close_resolves_test_and_restores_posture(self, api):
        """PRD §3.8: "When the recall's `salmonella_test_id` is set and that
        test is still `RESULTED` with a `POSITIVE` result, the test moves to
        `RESOLVED` and its flock's `quarantine_status` returns to `CLEAR`."
        PRD §3.8: "The farm's `compliance_posture` is then recomputed and may
        drop out of `SUSPENDED` — provided no other unresolved positive test
        and no recently failed audit still holds it there."
        PRD §3.6: "Reinstatement moves a `SUSPENDED` contract back to `ACTIVE`
        and requires two things: the farm posture must not be `SUSPENDED`,
        else `ERR_FARM_SUSPENDED` (HTTP 409), and `held_allocated_dozen` must
        be zero, else `ERR_LOT_QUALITY_HELD` (HTTP 409)"

        Design: Corner/complexity_layers/recall_close_resolves_test_and_restores_posture
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        contract = setup_active_contract(ctx["farm"]["id"])
        validate_success(api.release_lot(lot_id, QA_MANAGER))
        validate_success(
            api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        )

        test = create_collected_salmonella_test(ctx["flock"]["id"])
        record_test_result(test["id"], "POSITIVE")
        recalls, meta = validate_paginated(
            api.list_recalls(
                COMPLIANCE_OFFICER, params={"salmonella_test_id": test["id"]}
            )
        )
        assert meta["total_count"] == 1, "the positive cascade auto-creates a recall"
        recall = recalls[0]

        validate_success(api.scope_recall(recall["id"], COMPLIANCE_OFFICER))
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "RECALLED"
        assert get_contract(contract["id"])["allocated_dozen"] == 0, (
            "a swept ALLOCATED lot releases its contract volume first"
        )

        validate_success(api.close_recall(recall["id"], COMPLIANCE_OFFICER))
        assert get_salmonella_test(test["id"])["status"] == "RESOLVED"
        assert get_flock(ctx["flock"]["id"])["quarantine_status"] == "CLEAR"
        assert get_farm(ctx["farm"]["id"])["compliance_posture"] == "CLEAR", (
            "with the only positive resolved, posture drops back to CLEAR"
        )

        reinstated = validate_success(
            api.reinstate_contract(contract["id"], CONTRACT_MANAGER)
        )
        assert reinstated["status"] == "ACTIVE"
