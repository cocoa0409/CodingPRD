"""The QC revision loop: cycle counting, revision window boundary semantics,
and completion gating while revisions are unresolved."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    drive_order_to_revision_requested,
    get_order,
    open_qc,
    parse_utc,
    record_verdict,
    resubmit,
    set_clock,
    setup_market,
    validate_error,
)

OPS = TEST_USERS["operations_manager_headers"]


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRevisionCycleLoop:
    def test_revision_cycle_increments_cycle_index_and_count(self, api):
        """PRD §3.6: "Opening creates a `QCReview` row whose `cycle_index` is 1
        for the first review on the order, or one greater than the maximum prior
        `cycle_index`."
        PRD §3.6: "It moves the order to `REVISION_REQUESTED`, creates a
        `QCRevisionRequest` row whose `cycle_index` matches the review's, whose
        `due_at` is the verdict instant plus the revision window in hours, and
        whose `outcome` starts `OPEN`; increments the order's `revision_count`;
        and stamps `reviewed_at`."
        PRD §3.7: "the order re-enters the QC cycle from `REPORT_SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/valuation_order_revision_cycle
        """
        env = setup_market("NV", client_code="CLE", broker_code="BRKE",
                           client_overrides={"sla_hours_standard": 96})
        order, qc1, rev1 = drive_order_to_revision_requested(env)
        assert qc1["cycle_index"] == 1
        assert order["revision_count"] == 1

        # Resubmit -> REPORT_SUBMITTED, then loop into a second QC cycle.
        resubmitted = resubmit(order, rev1)
        assert resubmitted["outcome"] in ("RESOLVED_ON_TIME", "RESOLVED_LATE")
        order = get_order(order["id"])
        assert order["fulfillment_status"] == "REPORT_SUBMITTED"

        qc2 = open_qc(order)
        assert qc2["cycle_index"] == 2, (
            f"Second loop must open cycle_index 2, got {qc2['cycle_index']}")
        record_verdict(order, qc2, verdict="REVISE", defects_found=1,
                       notes="fix again")

        order = get_order(order["id"])
        assert order["fulfillment_status"] == "REVISION_REQUESTED"
        assert order["revision_count"] == 2, (
            f"Two REVISE verdicts must drive revision_count to 2, "
            f"got {order['revision_count']}")

    def test_resubmission_marks_revision_resolved_on_time(self, api):
        """PRD §3.7: "On resubmission the request's `resolved_at` is set to the
        current instant, and its `outcome` becomes `RESOLVED_ON_TIME` if that
        instant is on or before its `due_at`, or `RESOLVED_LATE` otherwise"

        Design: Difficulty/non_linear_state_machine/valuation_order_revision_cycle
        """
        env = setup_market("NV", client_code="CLE", broker_code="BRKE",
                           client_overrides={"sla_hours_standard": 96})
        order, qc1, rev1 = drive_order_to_revision_requested(env)

        # Resubmit immediately: the logical clock has not moved past due_at.
        resolved = resubmit(order, rev1)
        assert resolved["outcome"] == "RESOLVED_ON_TIME"
        assert parse_utc(resolved["resolved_at"]) <= parse_utc(resolved["due_at"])
        assert get_order(order["id"])["fulfillment_status"] == "REPORT_SUBMITTED"


class TestRevisionWindowBoundary:
    def test_resubmit_at_exactly_due_at_is_on_time(self, api):
        """PRD §3.7: "its `outcome` becomes `RESOLVED_ON_TIME` if that instant
        is on or before its `due_at`, or `RESOLVED_LATE` otherwise"

        Design: Difficulty/resource_temporal_overlap/revision_due_at_window_uses_closed_interval
        """
        env = setup_market("MI", client_code="CLP", broker_code="BRKP",
                           client_overrides={"sla_hours_standard": 96})
        order, qc1, rev1 = drive_order_to_revision_requested(env)
        due_at = rev1["due_at"]

        # Closed-interval boundary: resubmission at exactly due_at is on time.
        set_clock(due_at)
        resolved = resubmit(order, rev1)
        assert resolved["outcome"] == "RESOLVED_ON_TIME", (
            f"Resubmission at exactly due_at must resolve on time, "
            f"got {resolved['outcome']}")
        assert parse_utc(resolved["resolved_at"]) == parse_utc(due_at)

    def test_resubmit_after_due_at_is_late(self, api):
        """PRD §3.7: "its `outcome` becomes `RESOLVED_ON_TIME` if that instant
        is on or before its `due_at`, or `RESOLVED_LATE` otherwise"

        Design: Difficulty/resource_temporal_overlap/revision_due_at_window_uses_closed_interval
        """
        env = setup_market("MI", client_code="CLP", broker_code="BRKP",
                           client_overrides={"sla_hours_standard": 96})
        order, qc1, rev1 = drive_order_to_revision_requested(env)

        past_due = _iso_z(parse_utc(rev1["due_at"]) + timedelta(hours=1))
        set_clock(past_due)
        resolved = resubmit(order, rev1)
        assert resolved["outcome"] == "RESOLVED_LATE", (
            f"Resubmission past due_at must resolve late, got {resolved['outcome']}")
        assert get_order(order["id"])["fulfillment_status"] == "REPORT_SUBMITTED"


class TestCompletionGatedByRevision:
    def test_complete_rejected_when_open_revision_exists(self, api):
        """PRD §3.7: "Completion is refused with `ERR_INVALID_STATE` unless the
        order is `ACCEPTED`, and refused with `ERR_OPEN_REVISION_EXISTS` while
        any revision request on the order remains `OPEN`."

        Design: Corner/endpoints/complete_rejected_when_open_revision_exists
        """
        env = setup_market("NH", client_code="COR", broker_code="BOR")
        order, qc1, rev1 = drive_order_to_revision_requested(env)
        assert rev1["outcome"] == "OPEN"

        resp = api.complete_order(order["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["fulfillment_status"] == "REVISION_REQUESTED"
