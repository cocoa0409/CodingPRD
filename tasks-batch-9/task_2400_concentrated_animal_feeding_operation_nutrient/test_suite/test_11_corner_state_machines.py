"""Lifecycle state-machine behaviour: declared initial states, refused
undeclared transitions, terminal-state lockdown and the transitions whose side
effects reach across entities.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client as api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_null,
    assert_posture,
    assert_quantity,
    assert_state,
    assert_storage_balance,
    assert_storage_capacities,
)
from test_helpers.factories import (
    mortality_incident_payload,
    storage_inspection_payload,
)
from test_helpers.fixtures import (
    add_budget,
    approve_plan,
    certify_plan,
    cover_permit,
    create_plan,
    draft_permit,
    file_incident,
    file_soil_test,
    file_storage_inspection,
    initiate_transfer,
    open_annual_report,
    record_application,
    record_intake,
    register_field,
    register_hauler,
    register_operation,
    register_storage,
    schedule_inspection,
    submit_plan,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    PLANNER_2_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_HEADERS,
    make_hauler_headers,
    make_operator_headers,
)


CLOCK = "2026-08-01T00:00:00Z"


def _instant(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant(actual, expected, label="timestamp"):
    assert actual is not None, f"{label} is missing"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Declared initial states
# ---------------------------------------------------------------------------
def test_permit_plan_storage_incident_and_inspection_are_born_in_declared_states():
    """Six lifecycles created against one operation each sit in their own
    declared initial state with every later stamp still null.

    PRD: "A freshly drafted application is born with `coverage_status` of `DRAFT_APPLICATION` and, on the independent compliance dimension, `compliance_status` of `IN_GOOD_STANDING`."
    PRD: "New plans start in `DRAFT` with `revision_count` at 0."
    PRD: "A new structure begins with `cumulative_intake_gallons`, `precipitation_adjustment_gallons`, `cumulative_outflow_gallons`, `current_volume_gallons` and `committed_outflow_gallons` all at 0, `available_capacity_gallons` equal to its operating capacity, `last_inspected_on` null, and `storage_status` of `IN_SERVICE`."
    PRD: "When notification is required, `oral_notification_deadline_at` is 24 hours after `discovered_at` and `written_report_deadline_at` is 5 days after `discovered_at`; when it is not required, both are null."
    PRD: "A scheduled inspection starts with `inspection_status` of `SCHEDULED` and `findings_count` at 0."
    Design: Corner/state_machines/every_lifecycle_starts_in_its_declared_initial_state
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)

    storage = register_storage(operation_id, operator_headers)
    field = register_field(operation_id, PLANNER_HEADERS)

    permit = draft_permit(operation_id, operator_headers)
    assert_state(permit, "coverage_status", "DRAFT_APPLICATION")
    assert_state(permit, "compliance_status", "IN_GOOD_STANDING")
    assert_null(permit, "expiration_on", "renewal_window_opens_on", "renewal_due_on")

    plan = create_plan(operation_id, permit["id"], PLANNER_HEADERS)
    assert_state(plan, "plan_status", "DRAFT")
    assert plan["revision_count"] == 0, "a new plan starts with revision_count 0"
    assert_null(plan, "certified_at", "approved_at", "certifying_planner_user_id")

    assert_state(storage, "storage_status", "IN_SERVICE")
    assert_quantity(storage["current_volume_gallons"], 0.00, "current_volume_gallons")
    assert_null(storage, "last_inspected_on")

    incident = validate_success(
        api_client.create_incident_report(
            mortality_incident_payload(
                operation_id,
                subject_field_id=field["id"],
                discovered_at="2026-07-31T12:00:00Z",
                description="One head lost to heat stress",
                mortality_head_count=1,
            ),
            operator_headers,
        ),
        201,
    )
    assert_state(incident, "incident_status", "OPEN")
    assert incident["requires_oral_notification"] is False, (
        "a 1-head loss is below the 3-head threshold for a 300-head herd"
    )
    assert_null(
        incident, "oral_notification_deadline_at", "written_report_deadline_at"
    )

    inspection = schedule_inspection(
        operation_id,
        permit["id"],
        REVIEWER_HEADERS,
        scheduled_on="2026-08-15T00:00:00Z",
    )
    assert_state(inspection, "inspection_status", "SCHEDULED")
    assert_null(inspection, "inspector_user_id", "conducted_on")
    assert inspection["findings_count"] == 0, "a scheduled inspection has no findings"


def test_new_annual_report_is_born_in_draft_with_its_mass_balance_already_run():
    """The annual report's declared initial state is DRAFT, and the mass balance
    computed at open time reports a full -100 % variance against the design
    figure while a MORTALITY incident leaves the posture OPEN.

    PRD: "A report's `report_status` takes one of four values — `DRAFT`, `SUBMITTED`, `ACCEPTED` and `RETURNED` — and a new report is born in `DRAFT`."
    PRD: "`mass_balance_expected_gallons` is simply the operation's `design_annual_manure_gallons` — what the herd and the lot should have produced."
    PRD: "`variance_classification` is `WITHIN_TOLERANCE` when the absolute value of `variance_pct` is at most 15.00, and `EXCEEDS_TOLERANCE` otherwise."
    PRD: "`open_discharge_incident_count` is the number of incident reports of the operation whose `incident_type` is `DISCHARGE` or `SPILL` and whose `incident_status` is `OPEN`, `NOTIFIED` or `WRITTEN_SUBMITTED`."
    Design: Corner/state_machines/every_lifecycle_starts_in_its_declared_initial_state
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)

    register_storage(operation_id, operator_headers)
    field = register_field(operation_id, PLANNER_HEADERS)
    permit = draft_permit(operation_id, operator_headers)
    plan = create_plan(operation_id, permit["id"], PLANNER_HEADERS)

    validate_success(
        api_client.create_incident_report(
            mortality_incident_payload(
                operation_id,
                subject_field_id=field["id"],
                discovered_at="2026-07-31T12:00:00Z",
                description="One head lost to heat stress",
                mortality_head_count=1,
            ),
            operator_headers,
        ),
        201,
    )

    report = open_annual_report(
        operation_id,
        plan["id"],
        operator_headers,
        beginning_storage_gallons=0,
        ending_storage_gallons=0,
    )
    assert_state(report, "report_status", "DRAFT")
    assert_null(report, "submitted_at")
    assert_quantity(report["recorded_total_gallons"], 0.00, "recorded_total_gallons")
    assert_quantity(
        report["mass_balance_expected_gallons"],
        3374298.00,
        "mass_balance_expected_gallons",
    )
    assert_quantity(report["variance_pct"], -100.00, "variance_pct")
    assert_state(report, "variance_classification", "EXCEEDS_TOLERANCE")

    fresh = validate_success(api_client.get_operation(operation_id, operator_headers))
    assert_posture(fresh, "OPEN", discharges=0)


# ---------------------------------------------------------------------------
# Undeclared transitions on the permit coverage dimension
# ---------------------------------------------------------------------------
def test_undeclared_permit_coverage_transitions_are_refused():
    """From DRAFT_APPLICATION only submit is declared: issuing coverage,
    initiating and completing a renewal all fail, the first submit succeeds and
    a second submit fails the same way, and the compliance dimension is never
    written by any of it.

    PRD: "Any attempt to drive a coverage transition from a state where it is not declared — submitting something already submitted, issuing coverage on a draft, initiating a renewal from `RENEWAL_PENDING`, completing a renewal that was never initiated — is refused with `ERR_PERMIT_STATE_INVALID`."
    PRD: "These two dimensions live on the same permit record but advance entirely independently: a coverage transition never writes `compliance_status`, and a compliance transition never writes `coverage_status`."
    Design: Corner/state_machines/permit_coverage_transitions_from_wrong_state_are_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = draft_permit(operation_id, operator_headers)
    permit_id = permit["id"]

    validate_error(
        api_client.issue_permit_coverage(permit_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_PERMIT_STATE_INVALID,
    )
    validate_error(
        api_client.initiate_permit_renewal(permit_id, operator_headers),
        ApiErrorId.ERR_PERMIT_STATE_INVALID,
    )
    validate_error(
        api_client.complete_permit_renewal(permit_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_PERMIT_STATE_INVALID,
    )

    submitted = validate_success(
        api_client.submit_permit(permit_id, operator_headers), 200
    )
    assert_state(submitted, "coverage_status", "SUBMITTED")

    validate_error(
        api_client.submit_permit(permit_id, operator_headers),
        ApiErrorId.ERR_PERMIT_STATE_INVALID,
    )

    final = validate_success(api_client.get_permit(permit_id, operator_headers))
    assert_state(final, "coverage_status", "SUBMITTED")
    assert_state(final, "compliance_status", "IN_GOOD_STANDING")
    assert_null(final, "expiration_on", "renewal_submitted_at")


# ---------------------------------------------------------------------------
# Plan transitions declared only from later states
# ---------------------------------------------------------------------------
def test_submitting_approving_or_returning_a_draft_plan_is_refused():
    """CERTIFIED is the only state submit is declared from and SUBMITTED the
    only state approve and require-revision are declared from, so all three
    fail on a DRAFT plan even for the owning operator.

    PRD: "The `Operator` then files the certified plan with the agency, advancing `CERTIFIED → SUBMITTED`; this is admissible only when `certifying_planner_user_id` is not null."
    PRD: "Any transition attempted from a `plan_status` where it is not declared is refused with `ERR_PLAN_STATE_INVALID`."
    PRD: "Issuance is what stamps the term: `expiration_on` becomes `effective_on` plus a coverage term of 5 years; `renewal_window_opens_on` becomes `expiration_on` minus 180 days; and `renewal_due_on` becomes `expiration_on` minus 90 days."
    Design: Corner/state_machines/plan_submit_before_certification_is_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    plan = create_plan(operation_id, permit["id"], PLANNER_HEADERS)
    plan_id = plan["id"]

    validate_error(
        api_client.submit_nutrient_plan(plan_id, operator_headers),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
    )
    validate_error(
        api_client.approve_nutrient_plan(plan_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
    )
    validate_error(
        api_client.require_plan_revision(plan_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
    )

    unchanged = validate_success(
        api_client.get_nutrient_plan(plan_id, operator_headers)
    )
    assert_state(unchanged, "plan_status", "DRAFT")
    assert unchanged["revision_count"] == 0, "a refused transition cannot revise"

    covered = validate_success(api_client.get_permit(permit["id"], operator_headers))
    assert_state(covered, "coverage_status", "COVERED")
    assert_instant(covered["expiration_on"], "2031-01-01T00:00:00Z", "expiration_on")


# ---------------------------------------------------------------------------
# Annual report transitions declared only from SUBMITTED
# ---------------------------------------------------------------------------
def test_accepting_or_returning_a_draft_annual_report_is_refused():
    """Accept and return are declared only from SUBMITTED, so both fail on a
    DRAFT report while its mass-balance fields stay exactly as computed when
    the report was opened.

    PRD: "Acceptance advances `SUBMITTED → ACCEPTED` and stamps `accepted_at` from the logical clock; `ACCEPTED` is terminal."
    PRD: "Return advances `SUBMITTED → RETURNED` and stores the supplied `return_reason`."
    PRD: "Any report transition attempted from a `report_status` where it is not declared is refused with `ERR_REPORT_STATE_INVALID`."
    Design: Corner/state_machines/accepting_a_draft_annual_report_is_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = draft_permit(operation_id, operator_headers)
    plan = create_plan(operation_id, permit["id"], PLANNER_HEADERS)
    report = open_annual_report(
        operation_id,
        plan["id"],
        operator_headers,
        beginning_storage_gallons=0,
        ending_storage_gallons=0,
    )
    report_id = report["id"]

    validate_error(
        api_client.accept_annual_report(report_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )
    validate_error(
        api_client.return_annual_report(
            report_id, {"return_reason": "Records incomplete"}, REVIEWER_HEADERS
        ),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )

    final = validate_success(api_client.get_annual_report(report_id, operator_headers))
    assert_state(final, "report_status", "DRAFT")
    assert_null(final, "accepted_at", "return_reason")
    assert_quantity(
        final["recorded_land_applied_gallons"], 0.00, "recorded_land_applied_gallons"
    )
    assert_quantity(
        final["recorded_transferred_gallons"], 0.00, "recorded_transferred_gallons"
    )
    assert_quantity(final["variance_pct"], -100.00, "variance_pct")


# ---------------------------------------------------------------------------
# The incident notification guard
# ---------------------------------------------------------------------------
def test_oral_notification_below_the_mortality_threshold_is_refused():
    """A 2-head loss on a 300-head herd is below the threshold of 3, so
    requires_oral_notification is false, the OPEN to NOTIFIED edge is closed,
    and the written follow-up is unreachable too.

    PRD: "For a `MORTALITY`, the threshold scales with the herd: it is the greater of 2 head and one percent of the operation's `head_count` rounded up to a whole animal, and `requires_oral_notification` is true when `mortality_head_count` is at least that threshold."
    PRD: "An `Operator` records the oral notification, advancing `OPEN → NOTIFIED`, which is admissible only when `requires_oral_notification` is true."
    PRD: "The `Operator` then files the written follow-up, advancing `NOTIFIED → WRITTEN_SUBMITTED`, which is admissible only when `oral_notified_at` is not null."
    Design: Corner/state_machines/oral_notification_on_an_incident_that_needs_none_is_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    field = register_field(operation_id, PLANNER_HEADERS)

    incident = validate_success(
        api_client.create_incident_report(
            mortality_incident_payload(
                operation_id,
                subject_field_id=field["id"],
                discovered_at="2026-07-31T12:00:00Z",
                description="Two head lost to heat stress",
                mortality_head_count=2,
                disposal_method="BURIAL",
            ),
            operator_headers,
        ),
        201,
    )
    incident_id = incident["id"]
    assert incident["requires_oral_notification"] is False, (
        "max(2, ceil(1 % of 300)) is 3, so a 2-head loss needs no notification"
    )
    assert_null(incident, "oral_notification_deadline_at")

    validate_error(
        api_client.record_oral_notification(incident_id, operator_headers),
        ApiErrorId.ERR_INCIDENT_STATE_INVALID,
    )
    validate_error(
        api_client.submit_written_report(incident_id, operator_headers),
        ApiErrorId.ERR_INCIDENT_STATE_INVALID,
    )

    still_open = validate_success(
        api_client.get_incident_report(incident_id, operator_headers)
    )
    assert_state(still_open, "incident_status", "OPEN")
    assert_null(still_open, "oral_notified_at")


def test_incident_below_the_threshold_closes_directly_from_open():
    """The very fact that no notification is required is what makes the
    OPEN to CLOSED shortcut legal, and a MORTALITY never touches the posture.

    PRD: "An incident below the notification threshold — one whose `requires_oral_notification` is false — may be closed directly from `OPEN` with no notification step at all."
    PRD: "`open_discharge_incident_count` is the number of incident reports of the operation whose `incident_type` is `DISCHARGE` or `SPILL` and whose `incident_status` is `OPEN`, `NOTIFIED` or `WRITTEN_SUBMITTED`."
    Design: Corner/state_machines/oral_notification_on_an_incident_that_needs_none_is_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    field = register_field(operation_id, PLANNER_HEADERS)

    incident = validate_success(
        api_client.create_incident_report(
            mortality_incident_payload(
                operation_id,
                subject_field_id=field["id"],
                discovered_at="2026-07-31T12:00:00Z",
                description="Two head lost to heat stress",
                mortality_head_count=2,
                disposal_method="BURIAL",
            ),
            operator_headers,
        ),
        201,
    )

    before = validate_success(api_client.get_operation(operation_id, operator_headers))
    assert_posture(before, "OPEN", discharges=0)

    closed = validate_success(
        api_client.close_incident_report(incident["id"], REVIEWER_HEADERS), 200
    )
    assert_state(closed, "incident_status", "CLOSED")

    after = validate_success(api_client.get_operation(operation_id, operator_headers))
    assert_posture(after, "OPEN", discharges=0)


# ---------------------------------------------------------------------------
# Terminal inspection state
# ---------------------------------------------------------------------------
def test_second_close_of_a_closed_inspection_is_refused():
    """CLOSED is terminal for an inspection, so a second close, a re-conduct
    and a notice of violation are all refused, and closed_by_user_id keeps the
    first closer's identity rather than being restamped.

    PRD: "When `findings_count` is 0, a `StateReviewer` or a `ComplianceAdmin` may instead close the inspection directly, advancing `CONDUCTED → CLOSED` and stamping `closed_by_user_id` with the closing actor's `X-User-ID`, provided that actor differs from the recorded `inspector_user_id`."
    PRD: "Attempting to close a `CONDUCTED` inspection whose `findings_count` is at least 1, or driving any other undeclared inspection transition, is refused with `ERR_INSPECTION_STATE_INVALID`."
    PRD: "`open_finding_count` is the number of inspections of the operation whose status is `NOV_ISSUED` or `RESPONSE_SUBMITTED`."
    Design: Corner/state_machines/closing_an_already_closed_inspection_is_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)

    inspection = schedule_inspection(
        operation_id,
        permit["id"],
        REVIEWER_HEADERS,
        scheduled_on="2026-07-15T00:00:00Z",
    )
    inspection_id = inspection["id"]
    conducted = validate_success(
        api_client.conduct_inspection(
            inspection_id, {"findings_count": 0}, REVIEWER_HEADERS
        ),
        200,
    )
    assert_state(conducted, "inspection_status", "CONDUCTED")

    closed = validate_success(
        api_client.close_inspection(inspection_id, ADMIN_HEADERS), 200
    )
    assert_state(closed, "inspection_status", "CLOSED")
    assert closed["closed_by_user_id"] == "admin-1", (
        "closure stamps the closing actor's X-User-ID"
    )

    validate_error(
        api_client.close_inspection(inspection_id, REVIEWER_2_HEADERS),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID,
    )
    validate_error(
        api_client.conduct_inspection(
            inspection_id, {"findings_count": 3}, REVIEWER_HEADERS
        ),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID,
    )
    validate_error(
        api_client.issue_nov(inspection_id, REVIEWER_HEADERS),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID,
    )

    final = validate_success(api_client.get_inspection(inspection_id, operator_headers))
    assert_state(final, "inspection_status", "CLOSED")
    assert final["findings_count"] == 0, "a refused conduct cannot add findings"
    assert final["closed_by_user_id"] == "admin-1", (
        "the first closer's id survives the refused second close"
    )
    assert final["inspector_user_id"] == "reviewer-1", (
        "conducting stamped the inspecting reviewer"
    )
    assert_instant(final["conducted_on"], CLOCK, "conducted_on")

    fresh_operation = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert_posture(fresh_operation, "OPEN", findings=0)

    fresh_permit = validate_success(
        api_client.get_permit(permit["id"], operator_headers)
    )
    assert_state(fresh_permit, "compliance_status", "IN_GOOD_STANDING")


# ---------------------------------------------------------------------------
# Terminal transfer state and the single release of a commitment
# ---------------------------------------------------------------------------
def test_cancelled_transfer_refuses_every_further_transition_without_double_release():
    """CANCELLED is terminal, so acknowledge, complete, resume and a second
    cancel are all refused, and the commitment released by the first cancel is
    never released a second time.

    PRD: "An `Operator` may cancel a transfer from either `INITIATED` or `SUSPENDED`, reaching the terminal `CANCELLED`, and the counter treatment differs between the two by exactly the amount already released."
    PRD: "Cancelling an `INITIATED` transfer releases `gallons_transferred` from the structure's `committed_outflow_gallons`, restoring `available_capacity_gallons` to its pre-transfer value."
    PRD: "Any transition attempted from a `transfer_status` where it is not declared is refused with `ERR_TRANSFER_STATE_INVALID`."
    Design: Corner/state_machines/cancelled_transfer_rejects_every_further_transition
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    storage_id = storage["id"]
    cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    record_intake(operation_id, storage_id, 1000000, operator_headers)

    hauler = register_hauler(ADMIN_HEADERS, license_number="HL-4417")
    hauler_id = hauler["id"]
    hauler_headers = make_hauler_headers(hauler_id)

    transfer = initiate_transfer(
        operation_id,
        storage_id,
        hauler_id,
        operator_headers,
        recipient_name="Kroeger Row Crops",
        recipient_address="1188 County Road E, Linn",
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )
    transfer_id = transfer["id"]

    cancelled = validate_success(
        api_client.cancel_manure_transfer(transfer_id, operator_headers), 200
    )
    assert_state(cancelled, "transfer_status", "CANCELLED")

    validate_error(
        api_client.acknowledge_manure_transfer(transfer_id, hauler_headers),
        ApiErrorId.ERR_TRANSFER_STATE_INVALID,
    )
    validate_error(
        api_client.complete_manure_transfer(transfer_id, hauler_headers),
        ApiErrorId.ERR_TRANSFER_STATE_INVALID,
    )
    validate_error(
        api_client.resume_manure_transfer(transfer_id, operator_headers),
        ApiErrorId.ERR_TRANSFER_STATE_INVALID,
    )
    validate_error(
        api_client.cancel_manure_transfer(transfer_id, operator_headers),
        ApiErrorId.ERR_TRANSFER_STATE_INVALID,
    )

    final_transfer = validate_success(
        api_client.get_manure_transfer(transfer_id, operator_headers)
    )
    assert_state(final_transfer, "transfer_status", "CANCELLED")
    assert_null(final_transfer, "recipient_ack_signed_at")

    final_storage = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_storage_balance(
        final_storage,
        intake=1000000.00,
        outflow=0.00,
        current=1000000.00,
        committed=0.00,
        available=3488300.00,
        days=377,
    )


# ---------------------------------------------------------------------------
# Verification is ledger-neutral; voiding is the compensation and is terminal
# ---------------------------------------------------------------------------
def _approved_operation_with_one_recorded_application():
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    permit = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    field = register_field(operation_id, PLANNER_HEADERS)
    soil_test = file_soil_test(field["id"], PLANNER_HEADERS)
    plan = create_plan(operation_id, permit["id"], PLANNER_HEADERS)
    budget = add_budget(
        plan["id"], field["id"], soil_test["id"], PLANNER_HEADERS
    )
    certify_plan(plan["id"], PLANNER_HEADERS)
    submit_plan(operation_id, plan["id"], operator_headers)
    approve_plan(plan["id"], REVIEWER_HEADERS)
    record_intake(operation_id, storage["id"], 1000000, operator_headers)
    event = record_application(
        operation_id,
        plan["id"],
        budget["id"],
        storage["id"],
        operator_headers,
        applied_on="2026-07-20T00:00:00Z",
        gallons_applied=300000,
        acres_treated=30,
        applicator_name="J. Kroeger",
    )
    return {
        "operation_id": operation_id,
        "operator_headers": operator_headers,
        "storage_id": storage["id"],
        "budget_id": budget["id"],
        "event_id": event["id"],
    }


def test_verifying_an_application_moves_status_without_moving_either_ledger():
    """RECORDED and VERIFIED both count in the two ledgers, so verification
    changes the event status and nothing else.

    PRD: "It is born `RECORDED`; a `CertifiedPlanner` may verify it, advancing `RECORDED → VERIFIED`, which is admissible only while the owning plan's `plan_status` is `APPROVED` — otherwise `ERR_PLAN_NOT_APPROVED` — and which changes neither ledger, because both the budget's applied total and the structure's outflow total already count `RECORDED` and `VERIFIED` records alike."
    Design: Corner/state_machines/verify_event_leaves_ledgers_untouched_and_void_locks_it
    """
    ctx = _approved_operation_with_one_recorded_application()
    operator_headers = ctx["operator_headers"]

    verified = validate_success(
        api_client.verify_application_event(ctx["event_id"], PLANNER_HEADERS), 200
    )
    assert_state(verified, "event_status", "VERIFIED")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget_id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=300000.00, remaining=114396, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage_id"], operator_headers)
    )
    assert_storage_balance(
        storage, intake=1000000.00, outflow=300000.00, current=700000.00, committed=0.00
    )


def test_voiding_a_verified_application_reverses_ledgers_and_locks_the_event():
    """Voiding credits both ledgers back and makes VOIDED terminal: a further
    verify or void is refused, while the persisted nutrient masses stay
    readable on the voided row.

    PRD: "Only a `ComplianceAdmin` may void a record, and voiding is available from either `RECORDED` or `VERIFIED`; attempting to verify or void a record whose `event_status` is already `VOIDED` is refused with `ERR_EVENT_ALREADY_TERMINAL`, and `VOIDED` is terminal."
    PRD: "The budget's `applied_gallons_to_date` is credited down by `gallons_applied` and its `remaining_gallons` recomputed, restoring the invariant that applied plus remaining equals `allowable_total_gallons`."
    Design: Corner/state_machines/verify_event_leaves_ledgers_untouched_and_void_locks_it
    """
    ctx = _approved_operation_with_one_recorded_application()
    operator_headers = ctx["operator_headers"]
    event_id = ctx["event_id"]

    validate_success(
        api_client.verify_application_event(event_id, PLANNER_HEADERS), 200
    )
    voided = validate_success(
        api_client.void_application_event(event_id, ADMIN_HEADERS), 200
    )
    assert_state(voided, "event_status", "VOIDED")

    validate_error(
        api_client.verify_application_event(event_id, PLANNER_HEADERS),
        ApiErrorId.ERR_EVENT_ALREADY_TERMINAL,
    )
    validate_error(
        api_client.void_application_event(event_id, ADMIN_HEADERS),
        ApiErrorId.ERR_EVENT_ALREADY_TERMINAL,
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget_id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage_id"], operator_headers)
    )
    assert_storage_balance(
        storage, intake=1000000.00, outflow=0.00, current=1000000.00, committed=0.00
    )

    final_event = validate_success(
        api_client.get_application_event(event_id, operator_headers)
    )
    assert_state(final_event, "event_status", "VOIDED")
    assert_quantity(final_event["n_applied_lbs"], 4680.00, "n_applied_lbs")
    assert_quantity(final_event["p2o5_applied_lbs"], 3000.00, "p2o5_applied_lbs")


# ---------------------------------------------------------------------------
# Return to service reads the latest inspection, not the request
# ---------------------------------------------------------------------------
def test_return_to_service_is_refused_while_the_latest_inspection_shows_a_deficit():
    """An 18-inch reading against a 24-inch requirement is a 6-inch deficit,
    which raises the alert and keeps the structure out of service.

    PRD: "Otherwise, when there is a freeboard deficit at all, meaning `freeboard_deficit_in` is greater than 0 while `measured_freeboard_in` remains above 6 inches, a structure in `IN_SERVICE` moves to `FREEBOARD_ALERT` and the operation's posture is recomputed to `RESTRICTED`."
    PRD: "A structure whose latest inspection still shows a deficit, or shows `SEEPAGE`, `EROSION` or `CRACKING` even with adequate freeboard, cannot come back, and neither can a structure that is already `IN_SERVICE`; all three cases are refused with `ERR_STORAGE_STATE_INVALID`."
    Design: Corner/state_machines/return_to_service_requires_the_latest_inspection_to_be_clear
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    storage_id = storage["id"]
    assert_storage_capacities(storage, operating=4488300.00)

    reading = file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-25T00:00:00Z",
        inspector_name="T. Beck",
        measured_freeboard_in=18,
    )
    assert_quantity(
        reading["measured_volume_gallons"], 4712715.00, "measured_volume_gallons"
    )
    assert_quantity(reading["freeboard_deficit_in"], 6.00, "freeboard_deficit_in")
    assert reading["alert_raised"] is True, "a freeboard deficit raises the alert"

    validate_error(
        api_client.return_storage_to_service(storage_id, operator_headers),
        ApiErrorId.ERR_STORAGE_STATE_INVALID,
    )

    still_alerted = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_state(still_alerted, "storage_status", "FREEBOARD_ALERT")

    restricted = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert_posture(restricted, "RESTRICTED")


def test_return_to_service_succeeds_after_a_clear_inspection_and_lifts_the_posture():
    """The guard reads the newest reading by inspected_on, so a later 30-inch
    inspection clears the deficit, lets the same call through, reconciles the
    ledger to what was measured and returns the posture to OPEN.

    PRD: "Returning a structure to service is an `Operator` action available from either `FREEBOARD_ALERT` or `OVERFLOW_IMMINENT`, and it is gated on evidence rather than assertion: the structure's most recent inspection — the one with the greatest `inspected_on`, ties broken by the greatest `created_at` — must show `freeboard_deficit_in` of 0 **and** `visual_condition` of `NORMAL`."
    PRD: "A successful return sets `storage_status` to `IN_SERVICE` and recomputes the operation's posture, which returns to `OPEN` when no other restricting condition remains."
    PRD: "The reconciliation term is then rewritten: `precipitation_adjustment_gallons` becomes `measured_volume_gallons` less `cumulative_intake_gallons` plus `cumulative_outflow_gallons`, rounded half up to 2 decimal places, which is precisely the value that makes the volume-balance invariant exact against what the inspector measured."
    Design: Corner/state_machines/return_to_service_requires_the_latest_inspection_to_be_clear
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    storage_id = storage["id"]

    file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-25T00:00:00Z",
        inspector_name="T. Beck",
        measured_freeboard_in=18,
    )

    clear_reading = validate_success(
        api_client.create_storage_inspection(
            storage_inspection_payload(
                storage_id,
                inspected_on="2026-07-31T00:00:00Z",
                inspector_name="T. Beck",
                measured_freeboard_in=30,
            ),
            operator_headers,
        ),
        201,
    )
    assert_quantity(
        clear_reading["measured_volume_gallons"],
        4263885.00,
        "measured_volume_gallons",
    )
    assert_quantity(
        clear_reading["freeboard_deficit_in"], 0.00, "freeboard_deficit_in"
    )
    assert clear_reading["alert_raised"] is False, (
        "adequate freeboard with a NORMAL condition raises nothing"
    )

    returned = validate_success(
        api_client.return_storage_to_service(storage_id, operator_headers), 200
    )
    assert_state(returned, "storage_status", "IN_SERVICE")
    assert_instant(
        returned["last_inspected_on"], "2026-07-31T00:00:00Z", "last_inspected_on"
    )
    assert_storage_balance(
        returned,
        intake=0.00,
        precipitation=4263885.00,
        outflow=0.00,
        current=4263885.00,
        committed=0.00,
        available=224415.00,
        days=24,
    )

    reopened = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert_posture(reopened, "OPEN")


# ---------------------------------------------------------------------------
# The discharge incident lifecycle and the posture it drives
# ---------------------------------------------------------------------------
def _operation_with_open_discharge():
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    incident = file_incident(
        operation_id,
        operator_headers,
        subject_storage_id=storage["id"],
        discovered_at="2026-07-31T06:00:00Z",
        description="Berm seepage reached the drainage ditch",
        released_gallons=5000,
        reached_water=True,
    )
    return {
        "operation_id": operation_id,
        "operator_headers": operator_headers,
        "storage_id": storage["id"],
        "incident": incident,
    }


def test_open_discharge_incident_suspends_the_operation_and_blocks_intake():
    """A discharge that reached water requires notification and suspends the
    operation the moment it is filed, so an intake is refused outright and the
    structure's counters never move.

    PRD: "For a `DISCHARGE` or a `SPILL`, `requires_oral_notification` is true when `reached_water` is true **or** `released_gallons` is at least 1,000."
    PRD: "When notification is required, `oral_notification_deadline_at` is 24 hours after `discovered_at` and `written_report_deadline_at` is 5 days after `discovered_at`; when it is not required, both are null."
    PRD: "An intake is refused with `ERR_STORAGE_OPERATING_CAPACITY_EXCEEDED` when the resulting `current_volume_gallons` would exceed `operating_capacity_gallons`, and is refused with `ERR_OPERATION_SUSPENDED` when the operation's posture is `SUSPENDED`."
    Design: Corner/state_machines/closing_the_last_discharge_incident_returns_posture_to_open
    """
    ctx = _operation_with_open_discharge()
    incident = ctx["incident"]
    operator_headers = ctx["operator_headers"]

    assert incident["requires_oral_notification"] is True, (
        "a release that reached water always requires oral notification"
    )
    assert_instant(
        incident["oral_notification_deadline_at"],
        "2026-08-01T06:00:00Z",
        "oral_notification_deadline_at",
    )
    assert_instant(
        incident["written_report_deadline_at"],
        "2026-08-05T06:00:00Z",
        "written_report_deadline_at",
    )

    validate_error(
        api_client.record_storage_intake(
            ctx["storage_id"], {"gallons": 100000}, operator_headers
        ),
        ApiErrorId.ERR_OPERATION_SUSPENDED,
    )

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage_id"], operator_headers)
    )
    assert_quantity(
        storage["cumulative_intake_gallons"], 0.00, "cumulative_intake_gallons"
    )

    suspended = validate_success(
        api_client.get_operation(ctx["operation_id"], operator_headers)
    )
    assert_posture(suspended, "SUSPENDED", discharges=1)


def test_closing_the_discharge_incident_returns_posture_to_open_and_permits_intake():
    """Neither the oral notification nor the written report releases the
    suspension — only the close does, after which the same intake succeeds.

    PRD: "Recording stamps `oral_notified_at` from the logical clock and sets `notification_late` to true exactly when `oral_notified_at` is strictly later than `oral_notification_deadline_at` — a notification recorded at exactly the deadline instant is on time."
    PRD: "`open_discharge_incident_count` is the number of incident reports of the operation whose `incident_type` is `DISCHARGE` or `SPILL` and whose `incident_status` is `OPEN`, `NOTIFIED` or `WRITTEN_SUBMITTED`."
    PRD: "Either closure recomputes the operation's `open_discharge_incident_count` and `compliance_posture`, which returns to `OPEN` when no other restricting condition remains."
    Design: Corner/state_machines/closing_the_last_discharge_incident_returns_posture_to_open
    """
    ctx = _operation_with_open_discharge()
    operation_id = ctx["operation_id"]
    operator_headers = ctx["operator_headers"]
    incident_id = ctx["incident"]["id"]

    notified = validate_success(
        api_client.record_oral_notification(incident_id, operator_headers), 200
    )
    assert_state(notified, "incident_status", "NOTIFIED")
    assert_instant(notified["oral_notified_at"], CLOCK, "oral_notified_at")
    assert notified["notification_late"] is False, (
        "the clock is earlier than the 06:00 deadline"
    )

    written = validate_success(
        api_client.submit_written_report(incident_id, operator_headers), 200
    )
    assert_state(written, "incident_status", "WRITTEN_SUBMITTED")
    mid = validate_success(api_client.get_operation(operation_id, operator_headers))
    assert_posture(mid, "SUSPENDED", discharges=1)

    closed = validate_success(
        api_client.close_incident_report(incident_id, REVIEWER_HEADERS), 200
    )
    assert_state(closed, "incident_status", "CLOSED")

    reopened = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert_posture(reopened, "OPEN", discharges=0)

    storage = validate_success(
        api_client.record_storage_intake(
            ctx["storage_id"], {"gallons": 100000}, operator_headers
        ),
        200,
    )
    assert_storage_balance(storage, intake=100000.00, current=100000.00, days=474)


# ---------------------------------------------------------------------------
# Intake keeps volume, capacity and days in lockstep
# ---------------------------------------------------------------------------
def test_successive_intakes_keep_volume_capacity_and_days_in_lockstep():
    """Two intakes into an empty lagoon move current volume, available capacity
    and days of storage together, while the design-basis aggregate on the
    operation ignores contents entirely and stays put.

    PRD: "Recording an intake is how manure arriving from the barn or lot enters the ledger: the `Operator` supplies the volume of `gallons` entering the structure, which is added to `cumulative_intake_gallons`, after which `current_volume_gallons`, `available_capacity_gallons` and `days_of_storage_available` are recomputed."
    PRD: "`current_volume_gallons` is always `cumulative_intake_gallons` plus `precipitation_adjustment_gallons` less `cumulative_outflow_gallons`, and `available_capacity_gallons` is always `operating_capacity_gallons` less `current_volume_gallons` less `committed_outflow_gallons`, both rounded half up to 2 decimal places."
    PRD: "The operation-wide `design_storage_days` is the sum of `operating_capacity_gallons` across every storage structure of the operation, regardless of each structure's `storage_status`, divided by the same effective daily production and floored to a whole day; because it ignores current contents and commitments entirely, it moves only with herd size, structure geometry and the clock's month — and it is this figure that plan certification tests against the 180-day minimum."
    Design: Corner/state_machines/storage_intake_syncs_volume_capacity_and_days_of_storage
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    storage_id = storage["id"]

    after_first = validate_success(
        api_client.record_storage_intake(
            storage_id, {"gallons": 1000000}, operator_headers
        ),
        200,
    )
    assert_storage_balance(
        after_first,
        intake=1000000.00,
        current=1000000.00,
        committed=0.00,
        available=3488300.00,
        days=377,
    )

    after_second = validate_success(
        api_client.record_storage_intake(
            storage_id, {"gallons": 500000}, operator_headers
        ),
        200,
    )
    assert after_second["days_of_storage_available"] == 323, (
        "days of storage shrink as the structure fills"
    )
    assert_storage_balance(
        after_second,
        intake=1500000.00,
        current=1500000.00,
        committed=0.00,
        available=2988300.00,
    )
    assert_storage_capacities(
        after_second, design=5385960.00, reserve=897660.00, operating=4488300.00
    )

    fresh_operation = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert fresh_operation["design_storage_days"] == 485, (
        "the operation-wide figure ignores current contents"
    )


# ---------------------------------------------------------------------------
# Approving a successor plan supersedes its predecessor
# ---------------------------------------------------------------------------
def test_approving_a_successor_plan_supersedes_the_predecessor_and_locks_its_budgets():
    """Approving plan B activates B's budget, drives plan A to its terminal
    SUPERSEDED state and locks A's budget with its ledger numbers frozen.

    PRD: "Approval advances `SUBMITTED → APPROVED`, requires the operation's posture to be exactly `OPEN`, stamps `approved_at` from the logical clock, sets `budget_status` to `ACTIVE` on every field nutrient budget of the plan, and — when the plan names a `supersedes_plan_id` — transitions that referenced predecessor `APPROVED → SUPERSEDED`, which in turn sets `budget_status` to `LOCKED` on every budget of the predecessor."
    PRD: "Locking a budget never disturbs any of the three values — a locked budget simply refuses new applications while preserving its history."
    PRD: "Certification stamps `certifying_planner_user_id` with the acting planner's `X-User-ID` and `certified_at` with the logical clock."
    Design: Corner/state_machines/approving_successor_plan_supersedes_predecessor_and_locks_its_budgets
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    register_storage(operation_id, operator_headers)
    permit = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    field = register_field(operation_id, PLANNER_HEADERS)
    soil_test = file_soil_test(field["id"], PLANNER_HEADERS)

    plan_a = create_plan(
        operation_id,
        permit["id"],
        PLANNER_HEADERS,
        allowed_application_methods=["INJECTION"],
    )
    budget_a = add_budget(
        plan_a["id"], field["id"], soil_test["id"], PLANNER_HEADERS
    )
    certify_plan(plan_a["id"], PLANNER_HEADERS)
    submit_plan(operation_id, plan_a["id"], operator_headers)
    approve_plan(plan_a["id"], REVIEWER_HEADERS)

    plan_b = create_plan(
        operation_id,
        permit["id"],
        PLANNER_HEADERS,
        supersedes_plan_id=plan_a["id"],
    )
    budget_b = add_budget(
        plan_b["id"], field["id"], soil_test["id"], PLANNER_HEADERS
    )
    certified_b = certify_plan(plan_b["id"], PLANNER_2_HEADERS)
    assert certified_b["certifying_planner_user_id"] == "planner-2", (
        "certification stamps the acting planner"
    )
    submit_plan(operation_id, plan_b["id"], operator_headers)

    approved_b = validate_success(
        api_client.approve_nutrient_plan(plan_b["id"], REVIEWER_HEADERS), 200
    )
    assert_state(approved_b, "plan_status", "APPROVED")
    assert_instant(approved_b["approved_at"], CLOCK, "approved_at")
    assert approved_b["supersedes_plan_id"] == plan_a["id"], (
        "the successor keeps its pointer at the predecessor"
    )
    assert approved_b["certifying_planner_user_id"] == "planner-2", (
        "approval does not restamp the certifying planner"
    )

    superseded_a = validate_success(
        api_client.get_nutrient_plan(plan_a["id"], operator_headers)
    )
    assert_state(superseded_a, "plan_status", "SUPERSEDED")
    assert superseded_a["revision_count"] == 0, (
        "superseding is not a revision, so the counter stays put"
    )

    locked = validate_success(
        api_client.get_field_budget(budget_a["id"], operator_headers)
    )
    assert_state(locked, "budget_status", "LOCKED")
    assert_budget_ledger(locked, applied=0.00, remaining=414396, total=414396)

    active = validate_success(
        api_client.get_field_budget(budget_b["id"], operator_headers)
    )
    assert_state(active, "budget_status", "ACTIVE")
    assert_quantity(
        active["allowable_rate_gal_per_acre"], 10800, "allowable_rate_gal_per_acre"
    )
    assert_budget_ledger(active, total=414396)

    fresh_operation = validate_success(
        api_client.get_operation(operation_id, operator_headers)
    )
    assert_posture(fresh_operation, "OPEN")
