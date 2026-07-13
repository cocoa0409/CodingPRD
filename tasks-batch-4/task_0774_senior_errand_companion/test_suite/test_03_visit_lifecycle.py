"""Visit lifecycle: the IN_PROGRESS fork to ESCALATED, append-only visit logs,
and the invalid-transition errors around clock-out, add-on approval, and cancel."""
from test_helpers import (
    setup_in_progress_visit,
    setup_assigned_visit,
    setup_completed_visit,
    create_client,
    create_visit,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_caregiver_headers,
    create_wellness_escalation_payload,
    create_log_payload,
    create_addon_payload,
    assert_visit_log_entry,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestEscalationFork:
    def test_escalate_moves_visit_to_escalated(self, api):
        """PRD §3.5: "Escalation moves the visit IN_PROGRESS → ESCALATED and opens a
        WellnessCheck for the visit's client — carrying the triggering visit_id, the
        client_id, a severity of LOW, MEDIUM, or HIGH, and a free-text reason — but it
        deliberately does not produce an invoice."

        Design: Difficulty/non_linear_state_machine/visit_fork_escalated_produces_no_invoice
        """
        ctx = setup_in_progress_visit(api)
        cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        validate_success(
            api.escalate_visit(ctx["visit"]["id"], create_wellness_escalation_payload(), cg_headers), 201
        )
        visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
        assert visit["status"] == "ESCALATED", f"expected ESCALATED, got {visit['status']}"

    def test_escalate_opens_open_wellness_check(self, api):
        """PRD §3.8: "An escalation in the field opens a WellnessCheck in OPEN status,
        and this is where the family portal earns its keep."

        Design: Difficulty/non_linear_state_machine/visit_fork_escalated_produces_no_invoice
        """
        ctx = setup_in_progress_visit(api)
        cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        wc = validate_success(
            api.escalate_visit(ctx["visit"]["id"], create_wellness_escalation_payload(), cg_headers), 201
        )
        assert wc["status"] == "OPEN", f"expected wellness check OPEN, got {wc['status']}"

    def test_escalate_produces_no_invoice(self, api):
        """PRD §3.5: "Escalation moves the visit IN_PROGRESS → ESCALATED and opens a
        WellnessCheck for the visit's client — carrying the triggering visit_id, the
        client_id, a severity of LOW, MEDIUM, or HIGH, and a free-text reason — but it
        deliberately does not produce an invoice."

        Design: Difficulty/non_linear_state_machine/visit_fork_escalated_produces_no_invoice
        """
        ctx = setup_in_progress_visit(api)
        cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        validate_success(
            api.escalate_visit(ctx["visit"]["id"], create_wellness_escalation_payload(), cg_headers), 201
        )
        data, _meta = validate_paginated(api.list_invoices(BILLING, params={"visit_id": ctx["visit"]["id"]}))
        assert data == [], f"escalation must not create an invoice, found {data}"


def test_visit_log_entries_are_append_only(api):
    """PRD §2.4: "A VisitLogEntry is append-only and immutable after creation: it
    carries only id and created_at, and has neither an updated_at field nor a
    version field."

    Design: Corner/entities/visit_log_entry_append_only_listed_in_order
    """
    ctx = setup_in_progress_visit(api)
    cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
    e1 = validate_success(
        api.create_log(ctx["visit"]["id"], create_log_payload(entry_type="NOTE", note="arrived on time"), cg_headers), 201
    )
    validate_success(
        api.create_log(ctx["visit"]["id"], create_log_payload(entry_type="TASK_DONE", note="groceries delivered"), cg_headers), 201
    )
    assert_visit_log_entry(e1)
    data, meta = validate_paginated(api.list_logs(ctx["visit"]["id"], COORD))
    assert meta["total_count"] == 2, f"expected 2 log entries, got {meta['total_count']}"


def test_clockout_on_scheduled_visit_rejected(api):
    """PRD §3.5: "Clock-out is accepted from either IN_PROGRESS or ESCALATED — both
    paths move the visit to COMPLETED — while any other state is rejected with
    ERR_VISIT_NOT_IN_PROGRESS."

    Design: Corner/state_machines/error_clockout_on_scheduled_visit
    """
    ctx = setup_assigned_visit(api)  # SCHEDULED, never clocked in
    cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
    resp = api.clock_out(ctx["visit"]["id"], {"actual_end": "2026-03-05T12:00:00Z", "mileage_miles": 0}, cg_headers)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_IN_PROGRESS)


def test_approve_already_approved_addon_rejected(api):
    """PRD §3.5: "Dispositioning an add-on that is not REQUESTED is rejected with
    ERR_ADDON_NOT_REQUESTED."

    Design: Corner/state_machines/error_approve_non_requested_addon
    """
    client = create_client(api)
    visit = create_visit(api, client["id"])
    addon = validate_success(
        api.create_addon(visit["id"], create_addon_payload(addon_type="PET_CARE", fee_cents=800), COORD), 201
    )
    validate_success(api.approve_addon(addon["id"], {"outcome": "APPROVE"}, COORD))
    resp = api.approve_addon(addon["id"], {"outcome": "APPROVE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ADDON_NOT_REQUESTED)


def test_cancel_completed_visit_rejected(api):
    """PRD §3.5: "Cancelling a visit that is not SCHEDULED is rejected with
    ERR_VISIT_NOT_SCHEDULED."

    Design: Corner/state_machines/error_cancel_completed_visit_terminal
    """
    ctx = setup_completed_visit(api)
    resp = api.cancel_visit(ctx["visit"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_SCHEDULED)
