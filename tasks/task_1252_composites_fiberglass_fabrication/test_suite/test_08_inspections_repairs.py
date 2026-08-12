"""Inspections and repairs: dispositions, segregation of duties, repair loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    LAMINATOR_USER_ID,
    create_inspection_payload,
    demold,
    make_inspector_headers,
    run_cure,
    schedule_cure,
    setup_work_order_cured,
    setup_work_order_in_inspection,
    setup_work_order_in_repair,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

QI = TEST_USERS["quality_inspector_headers"]
CT = TEST_USERS["cure_technician_headers"]
LAM = TEST_USERS["laminator_headers"]


class TestInspectionDisposition:
    def test_void_content_exactly_2pct_passes(self, api):
        """PRD §3.6: "`PASS` when void content is at most 2.0 with zero delamination
        (a void content of exactly 2.0 with zero delamination passes)". The pass
        moves the order from `IN_INSPECTION` to `ACCEPTED`.

        Design: Difficulty/boundary_precision_check/void_content_exactly_2pct_passes
        """
        ctx = setup_work_order_in_inspection(
            mold_overrides={"mold_code": "MOLD-B2", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-B2"},
            batch_overrides={"batch_code": "BATCH-B2"},
        )
        inspection = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["work_order"]["id"],
                    void_content_pct=2.0,
                    delamination_area_cm2=0.0,
                ),
                QI,
            ),
            201,
        )
        assert inspection["result"] == "PASS"
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], QI), 200)
        assert order["status"] == "ACCEPTED"

    def test_void_content_just_above_2pct_requires_repair(self, api):
        """PRD §3.6: "`REPAIR_REQUIRED` when void content is at most 4.0 and
        delamination area is at most 25.0 (a void content of exactly 4.0 with a
        delamination of exactly 25.0 requires repair); and `FAIL` in every other
        case." A void reading of 2.0001 is past the PASS ceiling but inside the
        repair envelope.

        Design: Difficulty/boundary_precision_check/void_content_exactly_2pct_passes
        """
        ctx = setup_work_order_in_inspection(
            mold_overrides={"mold_code": "MOLD-B2X", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-B2X"},
            batch_overrides={"batch_code": "BATCH-B2X"},
        )
        inspection = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["work_order"]["id"],
                    void_content_pct=2.0001,
                    delamination_area_cm2=0.0,
                ),
                QI,
            ),
            201,
        )
        assert inspection["result"] == "REPAIR_REQUIRED"

    def test_inspection_disposition_repair_range(self, api):
        """PRD §3.6: "otherwise a `Repair` is auto-created in `OPEN` status, stamped
        with the order's `work_order_id`, linked back through `source_inspection_id`
        and echoed on the inspection as `created_repair_id` (null for the other two
        dispositions), assigned the next `repair_seq` — one-based, ordered by
        creation — while `repair_count` increments and the order moves to `REPAIR`".
        Void 3.0 with delamination 10.0 lands in the repair envelope.

        Design: Corner/calculations/inspection_disposition_repair_range
        """
        ctx = setup_work_order_in_inspection(
            mold_overrides={"mold_code": "MOLD-ID1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-ID1"},
            batch_overrides={"batch_code": "BATCH-ID1"},
        )
        inspection = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["work_order"]["id"],
                    method="TAP_TEST",
                    void_content_pct=3.0,
                    delamination_area_cm2=10.0,
                ),
                QI,
            ),
            201,
        )
        assert inspection["result"] == "REPAIR_REQUIRED"
        repair = validate_success(
            api.get_repair(inspection["created_repair_id"], QI), 200
        )
        assert repair["status"] == "OPEN"
        assert repair["repair_seq"] == 1
        assert repair["work_order_id"] == ctx["work_order"]["id"]
        assert repair["source_inspection_id"] == inspection["id"]
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], QI), 200)
        assert order["status"] == "REPAIR"
        assert order["repair_count"] == 1

    def test_inspection_disposition_fail_scraps(self, api):
        """PRD §3.6: "A `FAIL` scraps the order with `scrap_reason` set to
        `INSPECTION_FAIL`, and every `OPEN` repair on it is moved to `SUPERSEDED`."
        Void 5.0 exceeds the 4.0 repair ceiling.

        Design: Corner/calculations/inspection_disposition_fail_scraps
        """
        ctx = setup_work_order_in_inspection(
            mold_overrides={"mold_code": "MOLD-IF1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-IF1"},
            batch_overrides={"batch_code": "BATCH-IF1"},
        )
        inspection = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["work_order"]["id"],
                    void_content_pct=5.0,
                    delamination_area_cm2=10.0,
                ),
                QI,
            ),
            201,
        )
        assert inspection["result"] == "FAIL"
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], QI), 200)
        assert order["status"] == "SCRAPPED"
        assert order["scrap_reason"] == "INSPECTION_FAIL"


class TestRepairLoop:
    def _loop_once(self, api):
        """Order through first REPAIR_REQUIRED, re-cure, second demold."""
        ctx = setup_work_order_in_repair(
            mold_overrides={"mold_code": "MOLD-R1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-R1"},
            batch_overrides={"batch_code": "BATCH-R1"},
        )
        return ctx

    def test_repair_required_auto_creates_repair_and_recure_skips_mold(self, api):
        """PRD §3.6: "otherwise a `Repair` is auto-created in `OPEN` status" and
        "`repair_count` increments and the order moves to `REPAIR`, from which a
        re-cure may be scheduled per §3.5."
        PRD §3.5: "A cycle admitted while the part is still on the tool is marked
        `uses_mold` true; a post-repair bench re-cure is marked false."

        Design: Difficulty/non_linear_state_machine/workorder_repair_loop_cycle
        """
        ctx = self._loop_once(api)
        assert ctx["inspection"]["result"] == "REPAIR_REQUIRED"
        assert ctx["inspection"]["created_repair_id"] is not None
        assert ctx["repair"]["status"] == "OPEN"
        assert ctx["repair"]["repair_seq"] == 1
        recure = schedule_cure(
            ctx,
            scheduled_start="2026-06-01T16:00:00Z",
            scheduled_end="2026-06-01T18:00:00Z",
        )
        assert recure["uses_mold"] is False

    def test_full_repair_loop_closes_back_to_accepted(self, api):
        """PRD §3.6: "A `PASS` accepts the order: it moves from `IN_INSPECTION` to
        `ACCEPTED`, every `OPEN` repair on the order is moved to `CLOSED`".
        PRD §3.7: "an `OPEN` repair is closed by a later passing inspection on the
        same work order".

        Design: Difficulty/non_linear_state_machine/workorder_repair_loop_cycle
        """
        ctx = self._loop_once(api)
        recure = schedule_cure(
            ctx,
            scheduled_start="2026-06-01T16:00:00Z",
            scheduled_end="2026-06-01T18:00:00Z",
        )
        run_cure(recure)
        demold(ctx, 2000.0)
        passing = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["work_order"]["id"],
                    void_content_pct=1.0,
                    delamination_area_cm2=0.0,
                ),
                QI,
            ),
            201,
        )
        assert passing["result"] == "PASS"
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], QI), 200)
        assert order["status"] == "ACCEPTED"
        assert order["repair_count"] == 1
        repair = validate_success(api.get_repair(ctx["repair"]["id"], QI), 200)
        assert repair["status"] == "CLOSED"


class TestRepairLimit:
    def test_second_repair_beyond_limit_rejected(self, api):
        """PRD §3.6: "A `REPAIR_REQUIRED` disposition is gated by the pinned book's
        `max_repair_attempts`: if the order's `repair_count` has already reached that
        ceiling, the inspection itself is rejected with `ERR_REPAIR_LIMIT_EXCEEDED`
        and nothing is recorded". With the ceiling at 1 and one repair already
        recorded, the second repair-requiring inspection is refused.

        Design: Corner/state_machines/second_repair_beyond_limit_rejected
        """
        ctx = setup_work_order_in_repair(
            mold_overrides={"mold_code": "MOLD-RL1", "tooling_phase": "PRODUCTION"},
            ply_book_overrides={"max_repair_attempts": 1},
            work_order_overrides={"work_order_no": "WO-RL1"},
            batch_overrides={"batch_code": "BATCH-RL1"},
        )
        assert ctx["inspection"]["result"] == "REPAIR_REQUIRED"
        # Drive the repair loop back to IN_INSPECTION via a passing re-cure.
        recure = schedule_cure(
            ctx,
            scheduled_start="2026-06-01T16:00:00Z",
            scheduled_end="2026-06-01T18:00:00Z",
        )
        run_cure(recure)
        demold(ctx, 2000.0)
        res = api.create_inspection(
            create_inspection_payload(
                ctx["work_order"]["id"],
                void_content_pct=3.0,
                delamination_area_cm2=10.0,
            ),
            QI,
        )
        validate_error(res, ApiErrorId.ERR_REPAIR_LIMIT_EXCEEDED, expected_status=409)
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], QI), 200)
        assert order["status"] == "IN_INSPECTION"
        assert order["repair_count"] == 1


class TestSegregationOfDuties:
    def test_inspector_who_laid_up_cannot_inspect(self, api):
        """PRD §3.6: "the caller's `X-User-ID` must not equal the `laminator_id` of
        any `ACTIVE` layup session on the same work order — a laminator may never
        inspect their own layup — with violations refused as
        `ERR_SOD_INSPECTOR_LAMINATOR` (HTTP 403)."

        Design: Corner/rbac/inspector_who_laid_up_cannot_inspect
        """
        ctx = setup_work_order_in_inspection(
            mold_overrides={"mold_code": "MOLD-SD1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-SD1"},
            batch_overrides={"batch_code": "BATCH-SD1"},
        )
        # The order's ACTIVE session was recorded by op-lam-1; that same person
        # may not inspect it.
        res = api.create_inspection(
            create_inspection_payload(ctx["work_order"]["id"]),
            make_inspector_headers(LAMINATOR_USER_ID),
        )
        validate_error(res, ApiErrorId.ERR_SOD_INSPECTOR_LAMINATOR, expected_status=403)
        # An independent inspector proceeds.
        inspection = validate_success(
            api.create_inspection(create_inspection_payload(ctx["work_order"]["id"]), QI),
            201,
        )
        assert inspection["result"] == "PASS"


class TestInspectionStateGate:
    def test_inspection_on_cured_workorder_rejected(self, api):
        """PRD §3.6: "The work order must be `IN_INSPECTION`." A `CURED` order has
        not yet demolded, so the inspection is refused as an illegal state
        transition (`ERR_INVALID_STATE` per §2.11's state-machine legality tier).

        Design: Corner/state_machines/inspection_on_cured_workorder_rejected
        """
        ctx = setup_work_order_cured(
            mold_overrides={"mold_code": "MOLD-IC1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-IC1"},
            batch_overrides={"batch_code": "BATCH-IC1"},
        )
        res = api.create_inspection(
            create_inspection_payload(
                ctx["work_order"]["id"], method="VISUAL"
            ),
            QI,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
