"""Inspections: FAIL cascade, remediation-gated re-inspection cycle, permit expiry."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_under_review_application, decide, read_application, read_property,
    get_single_permit, get_violation_fine, set_logical_clock, run_daily_sweep,
    setup_review_ready, setup_failed_inspection,
    make_homeowner_headers,
)

MANAGER = TEST_USERS["manager_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestInspectionFailCascade:
    """A recorded FAIL fires the three-link cascade: violation, fine, property."""

    def test_fail_creates_condition_breach_violation(self, api):
        """PRD §3.7: "On a `FAIL`, the inspection moves to `FAILED_REMEDIATION` and a
        three-link cascade fires: a violation is created in `OPEN` status with
        `kind` `CONDITION_BREACH`, carrying both `source_inspection_id` and
        `source_permit_id`; the violation's creation creates its fine in `ACCRUING`
        status per §3.8; and the fine's creation recomputes the property's balance
        and posture."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_violation_fine_property
        """
        bundle = setup_failed_inspection()
        inspection = bundle["inspection"]
        violation = bundle["violation"]
        assert inspection["status"] == "FAILED_REMEDIATION"
        assert violation["kind"] == "CONDITION_BREACH"
        assert violation["status"] == "OPEN"
        assert violation["source_inspection_id"] == inspection["id"]
        assert violation["source_permit_id"] == bundle["permit"]["id"]

    def test_fail_creates_accruing_fine_and_recomputes_property(self, api):
        """PRD §3.8: "`base_cents` copies `base_fine_cents` and seeds the accrued total"
        PRD §3.8: "However a violation arises, it starts `OPEN`, and its creation
        always fires the same cascade: exactly one fine is created for the violation
        ... in `ACCRUING` status, and the property's balance and posture are
        recomputed."
        PRD §2.5: "`compliance_posture` is derived in a fixed order: `LIENED` if any
        lien of the property is in `FILED` status; otherwise `FINES_OUTSTANDING` if
        `outstanding_fine_balance_cents` is greater than zero; otherwise `CLEAR`."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_violation_fine_property
        """
        bundle = setup_failed_inspection()
        fine = bundle["fine"]
        assert fine["status"] == "ACCRUING"
        assert fine["accrued_cents"] == 10000, "accrued starts at the base amount"
        prop = read_property(bundle["property"]["id"])
        assert prop["outstanding_fine_balance_cents"] == 10000
        assert prop["compliance_posture"] == "FINES_OUTSTANDING"


class TestRescheduleGate:
    """The re-inspection gate reads the linked violation's state."""

    def test_reschedule_rejected_while_violation_open(self, api):
        """PRD §3.7: "Rescheduling while that violation remains unremediated fails the
        cross-entity state gate with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/reschedule_gated_by_violation_remediated
        """
        bundle = setup_failed_inspection()
        res = api.reschedule_inspection(bundle["inspection"]["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_inspection(bundle["inspection"]["id"], MANAGER), 200)
        assert after["status"] == "FAILED_REMEDIATION"

    def test_reschedule_succeeds_after_remediation(self, api):
        """PRD §3.7: "Once the violation it created — the violation whose
        `source_inspection_id` points back to this inspection — stands `REMEDIATED`,
        a `Manager` may reschedule: the inspection moves from `FAILED_REMEDIATION`
        back to `SCHEDULED`, `attempt_no` increments by one, `scheduled_at` is
        restamped, `recorded_at` is cleared, and `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/reschedule_gated_by_violation_remediated
        """
        bundle = setup_failed_inspection()
        owner_headers = make_homeowner_headers(bundle["applicant"]["id"])
        validate_success(api.remediate_violation(
            bundle["violation"]["id"], {}, owner_headers), 200)
        rescheduled = validate_success(api.reschedule_inspection(
            bundle["inspection"]["id"], MANAGER), 200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["attempt_no"] == bundle["inspection"]["attempt_no"] + 1


class TestInspectionCycle:
    """SCHEDULED -> FAILED_REMEDIATION -> SCHEDULED, gated by violation remediation."""

    def test_full_cycle_closes_with_attempt_two(self, api):
        """PRD §3.7: "The request creates an inspection in `SCHEDULED` status, bound
        to the inspected permit through its `permit_id`, whose `attempt_no` is one
        plus the number of inspections the permit already has — so a permit's first
        inspection is attempt 1"
        PRD §3.7: "the inspection moves from `FAILED_REMEDIATION` back to
        `SCHEDULED`, `attempt_no` increments by one"
        PRD §3.7: "The re-inspection loop is cyclic and may repeat as often as
        needed."

        Design: Difficulty/non_linear_state_machine/inspection_fail_remediate_reschedule_cycle
        """
        bundle = setup_failed_inspection()
        assert bundle["inspection"]["status"] == "FAILED_REMEDIATION"
        owner_headers = make_homeowner_headers(bundle["applicant"]["id"])

        remediated = validate_success(api.remediate_violation(
            bundle["violation"]["id"], {}, owner_headers), 200)
        assert remediated["status"] == "REMEDIATED"

        rescheduled = validate_success(api.reschedule_inspection(
            bundle["inspection"]["id"], MANAGER), 200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["attempt_no"] == 2

    def test_remediation_stops_the_fine(self, api):
        """PRD §3.8: "The violation moves to `REMEDIATED` with `remediated_at` stamped
        — a terminal state — and its fine, if still `ACCRUING`, halts at the
        remediation date, moving to `STOPPED` with `stopped_at` stamped; the
        property's balance and posture are then recomputed."

        Design: Difficulty/non_linear_state_machine/inspection_fail_remediate_reschedule_cycle
        """
        bundle = setup_failed_inspection()
        owner_headers = make_homeowner_headers(bundle["applicant"]["id"])
        validate_success(api.remediate_violation(
            bundle["violation"]["id"], {}, owner_headers), 200)
        fine = get_violation_fine(bundle["violation"]["id"])
        assert fine["status"] == "STOPPED"
        assert fine.get("stopped_at"), "stopped_at must be stamped on remediation"


def test_permit_expiry_cascade_creates_violation_and_fine(api):
    """A permit past window_end with no PASSED inspection expires and cascades.

    PRD §3.7: "Permits that outlive their windows are caught by the daily
    checkpoint: when the current logical date is later than an `ACTIVE` permit's
    `window_end` and no `PASSED` inspection exists for that permit, the permit moves
    to `EXPIRED`, and the same three-link cascade fires — an `OPEN` violation of
    `kind` `INCOMPLETE_CONSTRUCTION` carrying the `source_permit_id`, its `ACCRUING`
    fine, and the property recompute."
    PRD §3.8: "`accrued_through_date` starts equal to the creation date"

    Design: Corner/state_machines/permit_expiry_cascade_creates_violation_and_fine
    """
    bundle = setup_review_ready(
        app_overrides={"project_type": "PAINT", "guideline_section": "SEC-3.1",
                       "description": "repaint",
                       "requested_window_start": "2026-06-01",
                       "requested_window_end": "2026-06-10"})
    decide(bundle["application"]["id"], conditions=[])
    permit = get_single_permit(bundle["application"]["id"])

    set_logical_clock("2026-06-11T09:00:00Z")  # one day past window_end
    report = run_daily_sweep()
    assert report["permits_expired"] == 1

    expired = validate_success(api.get_permit(permit["id"], MANAGER), 200)
    assert expired["status"] == "EXPIRED"

    violations = validate_paginated(api.list_application_violations(
        bundle["application"]["id"], MANAGER))[0]
    assert len(violations) == 1
    violation = violations[0]
    assert violation["kind"] == "INCOMPLETE_CONSTRUCTION"
    assert violation["status"] == "OPEN"
    assert violation["source_permit_id"] == permit["id"]

    # The expiry step runs after the accrual step, so the new fine holds only base.
    fine = get_violation_fine(violation["id"])
    assert fine["status"] == "ACCRUING"
    assert fine["accrued_cents"] == 10000

    prop = read_property(bundle["property"]["id"])
    assert prop["outstanding_fine_balance_cents"] == 10000
    assert prop["compliance_posture"] == "FINES_OUTSTANDING"
    assert prop["open_permit_count"] == 0
