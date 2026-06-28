"""Entity lifecycles: cyclic state machines (request reassignment loop, filing
reject/resubmit loop), initial states, invalid-transition and terminal-state
lockdown errors, idempotency, and submit/service preconditions.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_server_headers,
    setup_reference_data,
    create_submitted_request,
    offer_to_server,
    log_attempt,
    setup_active_assignment,
    setup_notarized_request,
    create_filing,
    get_request,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Queue A: cyclic state machines ───────────────────────────────────────
def test_reassign_cycles_request_assigned_back_to_submitted(api):
    """PRD 3.3: "Reassigning moves the current `ACTIVE` assignment
    `ACTIVE → REASSIGNED` ... and the request bubbles down from `ASSIGNED` or
    `IN_PROGRESS` back to `SUBMITTED` with its `assignment_id` cleared to null."

    Design: Difficulty/non_linear_state_machine/servicerequest_reassign_cycle_assigned_back_to_submitted
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Yolo", "state_code": "CA", "min_diligent_attempts": 1}
    )
    result = validate_success(api.reassign(sr["id"], DISPATCHER), 200)
    assert result["status"] == "SUBMITTED", f"request should return to SUBMITTED, got {result['status']}"
    assert result["assignment_id"] is None, "assignment_id must be cleared to null"
    asg_after = validate_success(api.get_assignment(asg["id"], DISPATCHER))
    assert asg_after["status"] == "REASSIGNED"


def test_reassigned_request_can_be_reassigned_to_new_server(api):
    """PRD 3.3: "the request bubbles down from `ASSIGNED` ... back to `SUBMITTED`"
    — the cyclic edge means a second server can accept the re-pooled request,
    returning it to `ASSIGNED`.

    Design: Difficulty/non_linear_state_machine/servicerequest_reassign_cycle_assigned_back_to_submitted
    """
    county = get_success_data(
        api.create_county({"name": "Yolo2", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN)
    )
    s1 = get_success_data(api.create_server({"full_name": "S1", "license_no": "PS-4001"}, ADMIN))
    s2 = get_success_data(api.create_server({"full_name": "S2", "license_no": "PS-4002"}, ADMIN))
    get_success_data(api.create_territory(s1["id"], {"county_id": county["id"]}, ADMIN))
    get_success_data(api.create_territory(s2["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Eps Law", "email": "e@law.com"}, ADMIN))
    sr = create_submitted_request(client["id"], county["id"])
    asg1 = offer_to_server(sr["id"], s1["id"], sr["version"])
    get_success_data(api.accept_assignment(asg1["id"], make_server_headers(s1["id"])))
    repooled = validate_success(api.reassign(sr["id"], DISPATCHER), 200)
    assert repooled["status"] == "SUBMITTED"
    # New offer to S2 and accept returns the request to ASSIGNED.
    asg2 = offer_to_server(sr["id"], s2["id"], repooled["version"])
    get_success_data(api.accept_assignment(asg2["id"], make_server_headers(s2["id"])))
    final = get_request(sr["id"])
    assert final["status"] == "ASSIGNED", f"re-accept should move it to ASSIGNED, got {final['status']}"


def test_filing_reject_then_resubmit_increments_reject_count(api):
    """PRD 3.9: "a rejected filing may be resubmitted — `REJECTED → SUBMITTED`,
    the reject-and-resubmit loop ... a successful resubmit increments
    `reject_count` by one, regenerates the `FILING` invoice line, and recomputes
    `final_fee_cents`."

    Design: Difficulty/non_linear_state_machine/filing_reject_resubmit_cycle_on_filing_entity
    """
    county, server, client, sr, asg, aff, filing = _submit_then_reject_filing(api)
    resubmitted = validate_success(api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["reject_count"] == 1, f"reject_count should be 1, got {resubmitted['reject_count']}"


def test_filing_rejected_state_before_resubmit(api):
    """PRD 3.9: "Rejection — `SUBMITTED → REJECTED` — voids this filing's `FILING`
    invoice line and recomputes `final_fee_cents`." The filing sits in REJECTED
    with reject_count still 0 until the resubmit edge fires.

    Design: Difficulty/non_linear_state_machine/filing_reject_resubmit_cycle_on_filing_entity
    """
    county, server, client, sr, asg, aff, filing = _submit_then_reject_filing(api)
    rejected = validate_success(api.get_filing(filing["id"], DISPATCHER))
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_count"] == 0, "reject_count increments only on the resubmit edge"


def _submit_then_reject_filing(api):
    """Drive a NOTARIZED request's filing to SUBMITTED then REJECTED.
    setup_notarized_request returns a 6-tuple; the filing is built here."""
    county, server, client, sr, asg, aff = setup_notarized_request(
        deposit_cents=50_000,
        county_overrides={"name": "Solano", "state_code": "CA", "e_file_enabled": True, "min_diligent_attempts": 1},
        notary_user_id="notary-2",
    )
    filing = create_filing(sr["id"], aff["id"], "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z")
    filing = get_success_data(api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER))
    filing = get_success_data(api.set_filing_state(filing["id"], {"to_status": "REJECTED"}, DISPATCHER))
    return county, server, client, sr, asg, aff, filing


# ─── Queue B: state-machine corners ───────────────────────────────────────
def test_new_request_initial_state_is_draft(api):
    """PRD 3.2: "A `Client` ... or a `Dispatcher` ... creates one in `DRAFT`
    status".

    Design: Corner/state_machines/newly_created_servicerequest_initial_state_draft
    """
    county = get_success_data(api.create_county({"name": "Alpine", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "In Law", "email": "ii@law.com"}, ADMIN))
    sr = validate_success(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "2 St", "service_lat": 38.6, "service_lng": -119.8}, DISPATCHER
        ), 201
    )
    assert sr["status"] == "DRAFT"


def test_cancel_already_cancelled_request_returns_invalid_state(api):
    """PRD 3.10: "`COMPLETED` and `CANCELLED` are the request's terminal states."
    PRD 2.6: "a target resource that is not in a state from which the requested
    transition is defined yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_already_cancelled_request_returns_invalid_state
    """
    county = get_success_data(api.create_county({"name": "Calaveras", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Cn Law", "email": "n@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 38.2, "service_lng": -120.6}, DISPATCHER
        )
    )
    get_success_data(api.cancel_request(sr["id"], DISPATCHER))
    validate_error(api.cancel_request(sr["id"], DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_from_terminal_completed_returns_invalid_state(api):
    """PRD 3.11: "Completing a `FILED` request requires the request to be in
    `FILED` status (else `ERR_INVALID_STATE`); completing a `NON_EST` request
    requires it to be in `NON_EST` status." A COMPLETED request is in neither.

    Design: Corner/state_machines/complete_from_terminal_completed_request_returns_invalid_state
    """
    county, server, client = setup_reference_data(
        deposit_cents=50_000,
        county_overrides={"name": "Trinity", "state_code": "CA", "min_diligent_attempts": 1},
    )
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    svr = make_server_headers(server["id"])
    get_success_data(api.accept_assignment(asg["id"], svr))
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    get_success_data(api.non_est(sr["id"], svr))
    get_success_data(api.complete_request(sr["id"], DISPATCHER))
    completed = get_request(sr["id"])
    assert completed["status"] == "COMPLETED"
    validate_error(api.complete_request(sr["id"], DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)


def test_accept_already_active_assignment_returns_invalid_state(api):
    """PRD 3.3: "On a valid accept, the assignment moves `OFFERED → ACCEPTED` and
    then immediately and automatically `ACCEPTED → ACTIVE`". A second accept finds
    it no longer OFFERED.
    PRD 2.6: "a target resource that is not in a state from which the requested
    transition is defined yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/accept_offer_twice_idempotency_second_returns_invalid_state
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Shasta", "state_code": "CA", "min_diligent_attempts": 1}
    )
    validate_error(
        api.accept_assignment(asg["id"], make_server_headers(server["id"])),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_submit_without_document_returns_no_document(api):
    """PRD 3.2: "at least one Document must already be attached, or it is rejected
    with `ERR_NO_DOCUMENT`."

    Design: Corner/state_machines/submit_request_without_document_returns_no_document
    """
    county = get_success_data(api.create_county({"name": "Tuolumne", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Nd Law", "email": "nd@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "5 St", "service_lat": 38.0, "service_lng": -120.2}, DISPATCHER
        )
    )
    validate_error(api.submit_request(sr["id"], DISPATCHER), ApiErrorId.ERR_NO_DOCUMENT.value)


def test_personal_service_without_contact_attempt_returns_error(api):
    """PRD 3.5: "For `PERSONAL` service, the latest non-superseded attempt's
    `outcome` must be `CONTACT_MADE`, or the record is rejected with
    `ERR_NO_CONTACT_ATTEMPT`."

    Design: Corner/state_machines/personal_service_without_contact_attempt_returns_error
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "ElDorado", "state_code": "CA", "min_diligent_attempts": 1}
    )
    svr = make_server_headers(server["id"])
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    validate_error(
        api.record_service(
            sr["id"],
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-01T09:10:00Z"},
            svr,
        ),
        ApiErrorId.ERR_NO_CONTACT_ATTEMPT.value,
    )
