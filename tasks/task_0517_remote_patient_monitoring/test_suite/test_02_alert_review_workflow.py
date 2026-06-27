"""Alert triage, escalation cascade, and the provider review queue.

Covers difficulty rules non_linear_state_machine (alert revert cycle),
transitive_cascade (alert escalate spawns review task), and
cross_entity_state_dependency (resolve blocked by open review task), plus the
corner escalate-WARNING-not-permitted claim.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_vitals_payload, TEST_USERS, ApiErrorId, set_clock,
    setup_enrolled_patient_with_active_device,
    setup_escalated_alert_with_queued_task,
    make_physician_headers, make_clinician_headers,
)

CLIN = TEST_USERS["clinician_headers"]
CC = TEST_USERS["care_coordinator_headers"]
PHYS = TEST_USERS["physician_headers"]


def test_escalate_critical_alert_spawns_urgent_queued_review_task(api):
    """PRD §3.6: "Escalation cascades the creation of a new `ReviewTask` linked to this
    alert through `threshold_alert_id`, carrying the subject `patient_id`, a `priority`
    of `URGENT`, a `status` of `QUEUED`, a null `escalated_from_task_id`, and a null
    `reviewer_user_id`."

    Design: Difficulty/transitive_cascade/alert_escalate_cascade_depth2_spawns_review_task
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-ES-1", serial_number="SN-ES-1", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 190, "2026-06-10T08:00:00Z",
                              secondary_value=100),
        CLIN), 201)
    alert = get_success_data(api.list_alerts(CLIN, params={"vitals_reading_id": reading["id"]}))[0]
    escalated = validate_success(api.escalate_alert(alert["id"], CLIN), 200)
    assert escalated["status"] == "ESCALATED"
    tasks = get_success_data(api.list_review_tasks(PHYS, params={"threshold_alert_id": alert["id"]}))
    assert len(tasks) == 1, "exactly one spawned review task"
    assert tasks[0]["status"] == "QUEUED"
    assert tasks[0]["priority"] == "URGENT"


def test_escalate_critical_alert_sets_escalated_status(api):
    """PRD §3.6: "A `Clinician` may escalate an alert that is either `OPEN` or
    `ACKNOWLEDGED`, advancing it to `ESCALATED`."

    Design: Difficulty/transitive_cascade/alert_escalate_cascade_depth2_spawns_review_task
    """
    ctx = setup_escalated_alert_with_queued_task(mrn="M-ES-2", serial_number="SN-ES-2")
    alert = get_success_data(api.get_alert(ctx["alert"]["id"], CLIN))
    assert alert["status"] == "ESCALATED"
    assert ctx["task"]["threshold_alert_id"] == ctx["alert"]["id"]
    assert ctx["task"]["priority"] == "URGENT"


def test_claiming_task_reverts_escalated_alert_to_acknowledged(api):
    """PRD §3.6: "Claiming also performs a de-escalation cascade: if the linked
    `ThresholdAlert` is currently `ESCALATED`, the act of a provider taking ownership
    reverts the alert `ESCALATED → ACKNOWLEDGED`, bumping the alert's version."
    PRD §3.6: "Claiming a `QUEUED` task advances it `QUEUED → IN_REVIEW` and records the
    claiming physician's `X-User-ID` in `reviewer_user_id`."

    Design: Difficulty/non_linear_state_machine/threshold_alert_escalated_reverts_to_acknowledged_cycle
    """
    ctx = setup_escalated_alert_with_queued_task(mrn="M-AL-1", serial_number="SN-AL-1")
    claimed = validate_success(
        api.claim_review_task(ctx["task"]["id"], make_physician_headers("phys-A")), 200)
    assert claimed["status"] == "IN_REVIEW"
    alert = get_success_data(api.get_alert(ctx["alert"]["id"], CLIN))
    assert alert["status"] == "ACKNOWLEDGED", "claim reverts ESCALATED -> ACKNOWLEDGED"


def test_alert_revert_cycle_records_reviewer(api):
    """PRD §3.6: "Claiming a `QUEUED` task advances it `QUEUED → IN_REVIEW` and records
    the claiming physician's `X-User-ID` in `reviewer_user_id`."
    PRD §3.6: "the act of a provider taking ownership reverts the alert
    `ESCALATED → ACKNOWLEDGED`, bumping the alert's version."

    Design: Difficulty/non_linear_state_machine/threshold_alert_escalated_reverts_to_acknowledged_cycle
    """
    ctx = setup_escalated_alert_with_queued_task(mrn="M-AL-2", serial_number="SN-AL-2")
    before = get_success_data(api.get_alert(ctx["alert"]["id"], CLIN))
    claimed = validate_success(
        api.claim_review_task(ctx["task"]["id"], make_physician_headers("phys-rev")), 200)
    assert claimed["reviewer_user_id"] == "phys-rev"
    after = get_success_data(api.get_alert(ctx["alert"]["id"], CLIN))
    assert after["status"] == "ACKNOWLEDGED"
    assert after["version"] == before["version"] + 1, "alert version bumps on revert"


def test_resolve_blocked_while_linked_review_task_in_review(api):
    """PRD §3.6: "Resolution closes out an alert from `ACKNOWLEDGED → RESOLVED`, but only
    when no linked review task is still in `QUEUED`, `IN_REVIEW`, or `ESCALATED`; an
    attempt to resolve while such an open task exists is refused with
    `ERR_OPEN_REVIEW_TASK`."

    Design: Difficulty/cross_entity_state_dependency/alert_resolve_blocked_by_open_review_task
    """
    ctx = setup_escalated_alert_with_queued_task(mrn="M-CE2-1", serial_number="SN-CE2-1")
    # Claim reverts the alert to ACKNOWLEDGED while the task stays IN_REVIEW (open).
    validate_success(api.claim_review_task(ctx["task"]["id"], make_physician_headers("phys-Z")), 200)
    alert = get_success_data(api.get_alert(ctx["alert"]["id"], CLIN))
    assert alert["status"] == "ACKNOWLEDGED"
    task = get_success_data(api.get_review_task(ctx["task"]["id"], PHYS))
    assert task["status"] == "IN_REVIEW"
    resp = api.resolve_alert(ctx["alert"]["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_REVIEW_TASK.value)


def test_resolve_blocked_returns_open_review_task_error(api):
    """PRD §3.6: "an attempt to resolve while such an open task exists is refused with
    `ERR_OPEN_REVIEW_TASK`."

    Design: Difficulty/cross_entity_state_dependency/alert_resolve_blocked_by_open_review_task
    """
    ctx = setup_escalated_alert_with_queued_task(mrn="M-CE2-2", serial_number="SN-CE2-2")
    validate_success(api.claim_review_task(ctx["task"]["id"], make_physician_headers("phys-Y")), 200)
    resp = api.resolve_alert(ctx["alert"]["id"], CLIN)
    err = validate_error(resp, ApiErrorId.ERR_OPEN_REVIEW_TASK.value)
    assert err["error_id"] == "ERR_OPEN_REVIEW_TASK"


def test_escalate_warning_alert_not_permitted(api):
    """PRD §3.6: "Escalation is the safety-critical branch and is permitted only on a
    `CRITICAL` alert."
    PRD §3.6: "an escalate attempted on a non-critical alert is refused with
    `ERR_ESCALATION_NOT_PERMITTED`."

    Design: Corner/state_machines/escalate_warning_alert_not_permitted
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-SM2-1", serial_number="SN-SM2-1", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 145, "2026-06-10T08:00:00Z",
                              secondary_value=85),
        CLIN), 201)
    alert = get_success_data(api.list_alerts(CLIN, params={"vitals_reading_id": reading["id"]}))[0]
    assert alert["severity"] == "WARNING"
    resp = api.escalate_alert(alert["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_PERMITTED.value)
