"""Validation precedence, cross-entity state dependencies, RBAC, and the error catalogue:
priority pairs, capacity, dispute-not-invoiced, FK/required/window/surcharge, ownership,
plus creation, listing, rating, and assorted error conditions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    provision_med_phone, create_issued_invoice_for_session,
    create_client, create_language_pair, create_rate_plan, create_interpreter,
    add_certification, add_language_grant, create_request, dispatch_request, dispatch_accept,
    create_ended_session, set_clock,
    make_client_headers, make_interpreter_headers, coordinator_headers, admin_headers,
    TEST_USERS, build_user_headers,
    factories, assert_client,
)


# --------------------------------------------------------------------------- #
# Queue A: priority_pair_validation_conflict
# --------------------------------------------------------------------------- #
def test_forbidden_role_beats_invalid_state_on_dispatch(api):
    """PRD 2.6: "Authentication of the headers comes first (ERR_UNAUTHENTICATED), then role
    authorization (ERR_FORBIDDEN_ROLE), then existence of every path-referenced resource
    (ERR_RESOURCE_NOT_FOUND), then resolution of every body foreign key (ERR_FK_NOT_FOUND),
    then well-formedness of the body (ERR_INVALID_REQUEST), then whether the target is in a
    state from which the requested transition is defined (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/auth_vs_state_forbidden_role_beats_invalid_state
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(env["client"]["id"], env["lp"]["id"])
    dispatch_request(req["id"], req["version"])  # request now ASSIGNED (wrong state to dispatch)
    # A ClientAccount (forbidden for dispatch) targets the already-ASSIGNED request.
    resp = api.dispatch_request(
        req["id"], factories.dispatch_payload(req["version"]), make_client_headers(env["client"]["id"])
    )
    # Role check (priority 2) fires before the state check (priority 6).
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_dispatch_already_assigned_request_state_check_not_preempted_by_role(api):
    """PRD 2.6: "then whether the target is in a state from which the requested transition is
    defined (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/auth_vs_state_forbidden_role_beats_invalid_state
    """
    # Control arm: when the caller IS the authorized CoordinatorOps role, the role check passes
    # and the state check at priority 6 governs the already-ASSIGNED request (ERR_INVALID_STATE).
    # This pins that the priority-2 ERR_FORBIDDEN_ROLE in the paired test is the role check
    # firing first, not the state check producing the same code.
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(env["client"]["id"], env["lp"]["id"])
    dispatch_request(req["id"], req["version"])  # request now ASSIGNED
    live = validate_success(api.get_request(req["id"], coordinator_headers()))
    resp = api.dispatch_request(
        req["id"], factories.dispatch_payload(live["version"]), coordinator_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_empty_pool_governs_over_fiscal_on_dispatch(api):
    """PRD 3.3: "If the eligible set is empty for an ordinary reason, dispatch instead drives
    the request from OPEN to UNFULFILLABLE (still incrementing version by 1)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_no_qualified_vs_credit_limit
    """
    # Client over a tiny credit limit AND the only qualified interpreter is OFFLINE, so the
    # eligible set is empty for an ordinary (availability) reason; dispatch must resolve via
    # the selection/safety path (UNFULFILLABLE), not a fiscal rejection.
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL",
                           contact_email="h@x.com", credit_limit_cents=100)
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Offline I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    validate_success(api.set_interpreter_status(itp["id"], {"status": "OFFLINE"}, admin_headers()))
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(client["id"], lp["id"])
    validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers())
    )
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    assert request["status"] == "UNFULFILLABLE", (
        f"safety/selection outcome governs, not fiscal; got {request['status']}"
    )


def test_dispatch_empty_pool_creates_no_assignment_despite_credit_pressure(api):
    """PRD 3.3: "On success the platform creates a single **assignment** in `lifecycle_status`
    `OFFERED` and `billing_status` `UNBILLED`, stamps `offered_at` with the current clock,
    copies the request's scheduling mode into the assignment's `assignment_type`, moves the
    request to `ASSIGNED`, and increments the request's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_no_qualified_vs_credit_limit
    """
    # Same over-credit + qualified-but-OFFLINE interpreter (ordinary-empty pool); assert no
    # Assignment is minted (the selection/safety path resolves to UNFULFILLABLE, never a
    # dispatch success or a fiscal gate).
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL",
                           contact_email="h@x.com", credit_limit_cents=100)
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Offline I")
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    validate_success(api.set_interpreter_status(itp["id"], {"status": "OFFLINE"}, admin_headers()))
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(client["id"], lp["id"])
    validate_success(
        api.dispatch_request(req["id"], factories.dispatch_payload(req["version"]), coordinator_headers())
    )
    data, meta = validate_paginated(
        api.list_assignments(coordinator_headers(), params={"request_id": req["id"]})
    )
    assert meta["total_count"] == 0, f"no assignment should be minted, found {meta['total_count']}"


# --------------------------------------------------------------------------- #
# Queue A: cross_entity_state_dependency
# --------------------------------------------------------------------------- #
def test_accept_second_offer_at_capacity_rejected(api):
    """PRD 3.4: "an accept that would carry the interpreter to or beyond max_concurrent_load
    is rejected with ERR_INTERPRETER_AT_CAPACITY (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_interpreter_under_capacity
    """
    env = provision_med_phone()  # max_concurrent_load defaults to 1
    set_clock("2026-03-10T09:00:00Z")
    itp_h = make_interpreter_headers(env["interpreter"]["id"])
    # Two requests both offered to the same interpreter while it is AVAILABLE at load 0.
    r1 = create_request(env["client"]["id"], env["lp"]["id"])
    a1 = dispatch_request(r1["id"], r1["version"])
    r2 = create_request(env["client"]["id"], env["lp"]["id"])
    a2 = dispatch_request(r2["id"], r2["version"])
    validate_success(api.accept_assignment(a1["id"], itp_h))  # load -> 1, BUSY (at cap)
    resp = api.accept_assignment(a2["id"], itp_h)
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_AT_CAPACITY.value)


def test_capacity_rejection_leaves_second_offer_offered(api):
    """PRD 3.4: "Accepting moves `lifecycle_status` to `ACCEPTED`, increments the
    interpreter's `active_load` by 1 — and if that brings `active_load` up to
    `max_concurrent_load`, flips the interpreter's `status` to `BUSY` — and recomputes the
    interpreter's `acceptance_pct`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_interpreter_under_capacity
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    itp_h = make_interpreter_headers(env["interpreter"]["id"])
    r1 = create_request(env["client"]["id"], env["lp"]["id"])
    a1 = dispatch_request(r1["id"], r1["version"])
    r2 = create_request(env["client"]["id"], env["lp"]["id"])
    a2 = dispatch_request(r2["id"], r2["version"])
    validate_success(api.accept_assignment(a1["id"], itp_h))
    validate_error(api.accept_assignment(a2["id"], itp_h), ApiErrorId.ERR_INTERPRETER_AT_CAPACITY.value)
    itp = validate_success(api.get_interpreter(env["interpreter"]["id"], coordinator_headers()))
    assert itp["active_load"] == 1 and itp["status"] == "BUSY"
    a2_after = validate_success(api.get_assignment(a2["id"], coordinator_headers()))
    assert a2_after["lifecycle_status"] == "OFFERED", f"got {a2_after['lifecycle_status']}"


def test_dispute_session_on_issued_invoice_rejected(api):
    """PRD 3.8: "a dispute against a session already pulled into an `ISSUED` invoice is
    rejected with `ERR_SESSION_ALREADY_INVOICED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/dispute_requires_session_not_invoiced
    """
    env = create_issued_invoice_for_session()
    resp = api.dispute_session(env["session"]["id"], make_client_headers(env["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_ALREADY_INVOICED.value)
    session = validate_success(api.get_session(env["session"]["id"], coordinator_headers()))
    assert session["status"] == "ENDED", "dispute blocked; session remains ENDED"


def test_dispute_ended_session_not_invoiced_succeeds(api):
    """PRD 3.8: "After a session has ENDED, the owning client may dispute its billing - but
    only before the session has been swept into an issued invoice ... A successful dispute
    moves the session to DISPUTED."

    Design: Difficulty/cross_entity_state_dependency/dispute_requires_session_not_invoiced
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    disputed = validate_success(api.dispute_session(session["id"], make_client_headers(env["client"]["id"])))
    assert disputed["status"] == "DISPUTED"


# --------------------------------------------------------------------------- #
# Queue B: entities (creation, not-found, required, window, surcharge)
# --------------------------------------------------------------------------- #
def test_create_client_returns_defaults(api):
    """PRD 3.1: "the account opens in `ACTIVE` status with an `outstanding_balance_cents` of 0."
    PRD 2.9: "a `credit_limit_cents`, the maximum unpaid invoice balance the client is
    permitted to accumulate, defaulting to 5,000,000 cents (fifty thousand dollars) when not
    supplied at creation."

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    created = validate_success(
        api.create_client(factories.create_client_payload(), admin_headers()), expected_status=201
    )
    assert_client(created)
    assert created["status"] == "ACTIVE"
    assert created["outstanding_balance_cents"] == 0
    assert created["credit_limit_cents"] == 5_000_000
    assert created["version"] == 1


def test_get_interpreter_not_found_returns_404(api):
    """PRD 2.5: "each is validated left to right, and the first that does not exist produces
    ERR_RESOURCE_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_interpreter_not_found_returns_404
    """
    resp = api.get_interpreter(NON_EXISTENT_UUID, admin_headers())
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_create_request_missing_required_tier_returns_invalid_request(api):
    """PRD 3.2: "Supplying window fields on an on-demand request, or omitting them on a
    scheduled one, is malformed input rejected with ERR_INVALID_REQUEST (HTTP 400) - the same
    code that guards bad enum members, a rating score outside its allowed band, any missing
    required field, and a travel surcharge set on a non-onsite rate plan."

    Design: Corner/entities/create_request_missing_required_field_returns_invalid_request
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    payload = {
        "client_id": client["id"], "language_pair_id": lp["id"],
        "modality": "PHONE", "scheduling_mode": "ON_DEMAND",  # required_tier omitted
    }
    resp = api.create_request(payload, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_scheduled_window_end_not_after_start_returns_invalid_window(api):
    """PRD 3.2: "with window_end strictly after window_start; a window whose end is not
    strictly later than its start is rejected with ERR_INVALID_WINDOW (HTTP 400)."

    Design: Corner/entities/scheduled_request_invalid_window_returns_invalid_window
    """
    client = create_client(org_name="County Court", org_type="COURT", contact_email="court@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    set_clock("2026-03-10T08:00:00Z")
    payload = factories.create_request_payload(
        client_id=client["id"], language_pair_id=lp["id"], modality="VIDEO",
        required_tier="COURT", scheduling_mode="SCHEDULED",
        window_start="2026-03-10T12:00:00Z", window_end="2026-03-10T11:00:00Z",
    )
    resp = api.create_request(payload, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_rate_plan_travel_surcharge_on_phone_returns_invalid_request(api):
    """PRD 3.1: "A travel_surcharge_cents (defaulting to 0) is a flat charge applied once per
    onsite session; it must be 0 for any PHONE or VIDEO row, and supplying a non-zero
    surcharge on a non-onsite row is malformed input."

    Design: Corner/entities/rate_plan_surcharge_on_phone_returns_invalid_request
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    payload = factories.create_rate_plan_payload(
        client_id=client["id"], certification_tier="MEDICAL", modality="PHONE",
        billing_mode="PER_MINUTE", rate_cents=195, travel_surcharge_cents=500,
    )
    resp = api.create_rate_plan(payload, admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --------------------------------------------------------------------------- #
# Queue B: calculations (rating aggregate)
# --------------------------------------------------------------------------- #
def test_rating_aggregate_first_then_second(api):
    """PRD 3.9: "rating_count becomes the number of those ratings, and rating_avg becomes the
    sum of their scores divided by that count, rounded half-up to one decimal place."

    Design: Corner/calculations/rating_aggregate_first_then_second
    """
    env = provision_med_phone(max_concurrent_load=2)
    set_clock("2026-03-10T09:00:00Z")
    client_h = make_client_headers(env["client"]["id"])
    # First session, rated 5 -> avg 5.0, count 1.
    _, _, s1 = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    validate_success(api.rate_session(s1["id"], factories.rating_payload(5), client_h), expected_status=201)
    # Second session, rated 4 -> avg (5+4)/2 = 4.5, count 2.
    set_clock("2026-03-10T09:30:00Z")
    _, _, s2 = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:30:00Z", end_iso="2026-03-10T09:50:00Z",
    )
    validate_success(api.rate_session(s2["id"], factories.rating_payload(4), client_h), expected_status=201)
    itp = validate_success(api.get_interpreter(env["interpreter"]["id"], coordinator_headers()))
    assert itp["rating_avg"] == 4.5, f"expected 4.5, got {itp['rating_avg']}"
    assert itp["rating_count"] == 2, f"expected 2, got {itp['rating_count']}"


# --------------------------------------------------------------------------- #
# Queue B: validations
# --------------------------------------------------------------------------- #
def test_create_request_nonexistent_client_fk_returns_fk_not_found(api):
    """PRD 2.5: "when a foreign-key field carried in a request body - for example client_id,
    language_pair_id, interpreter_id, session_id, assignment_id, or request_id - points at a
    resource that does not exist, the body-level reference failure is reported as
    ERR_FK_NOT_FOUND (HTTP 422)."

    Design: Corner/validations/create_request_with_nonexistent_client_fk
    """
    lp = create_language_pair(source_lang="en", target_lang="es")
    payload = factories.create_request_payload(
        client_id=NON_EXISTENT_UUID, language_pair_id=lp["id"],
        modality="PHONE", required_tier="MEDICAL", scheduling_mode="ON_DEMAND",
    )
    resp = api.create_request(payload, build_user_headers(NON_EXISTENT_UUID, "ClientAccount"))
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_second_rating_returns_already_rated(api):
    """PRD 3.9: "Exactly one rating is permitted per session - a second rating attempt on the
    same session is rejected with ERR_ALREADY_RATED (HTTP 409)."

    Design: Corner/validations/second_rating_returns_already_rated
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    _, _, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    client_h = make_client_headers(env["client"]["id"])
    validate_success(api.rate_session(session["id"], factories.rating_payload(5), client_h), expected_status=201)
    resp = api.rate_session(session["id"], factories.rating_payload(3), client_h)
    validate_error(resp, ApiErrorId.ERR_ALREADY_RATED.value)


def test_suspended_client_cannot_file_request(api):
    """PRD 2.9: "a suspended client attempting to file a request or have one dispatched is
    rejected with ERR_CLIENT_SUSPENDED (HTTP 403)."

    Design: Corner/validations/create_request_for_suspended_client
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    validate_success(api.suspend_client(client["id"], admin_headers()))
    payload = factories.create_request_payload(
        client_id=client["id"], language_pair_id=lp["id"],
        modality="PHONE", required_tier="MEDICAL", scheduling_mode="ON_DEMAND",
    )
    resp = api.create_request(payload, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value)


# --------------------------------------------------------------------------- #
# Queue B: rbac
# --------------------------------------------------------------------------- #
def test_interpreter_cannot_dispatch_request(api):
    """PRD 2.1: "When an authenticated role is not among those permitted for the requested
    operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/interpreter_cannot_dispatch_request
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Med I")
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(client["id"], lp["id"])
    resp = api.dispatch_request(
        req["id"], factories.dispatch_payload(req["version"]), make_interpreter_headers(itp["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_client_cannot_cancel_other_clients_request(api):
    """PRD 2.1: "A logged-in entity-backed user acting on a resource they do not own is
    rejected with ERR_NOT_OWNER (HTTP 403)."

    Design: Corner/rbac/client_cannot_cancel_other_clients_request
    """
    ca = create_client(org_name="Client A", org_type="HOSPITAL", contact_email="a@x.com")
    cb = create_client(org_name="Client B", org_type="HOSPITAL", contact_email="b@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(ca["id"], lp["id"])  # owned by A
    resp = api.cancel_request(req["id"], make_client_headers(cb["id"]))  # B attempts cancel
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header — or carrying a malformed one — is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_interpreters(headers={})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------- #
# Queue B: endpoints (listing/pagination)
# --------------------------------------------------------------------------- #
def test_list_requests_filtered_by_client_paginates(api):
    """PRD 2.3: "Each list response surfaces limit, offset, total_count, and has_more in the
    meta block: total_count is the size of the full filtered set before the page window is
    applied, and has_more is true exactly when records remain beyond the current window."

    Design: Corner/endpoints/list_requests_filtered_by_client_paginates
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    set_clock("2026-03-10T09:00:00Z")
    create_request(client["id"], lp["id"])
    create_request(client["id"], lp["id"])
    data, meta = validate_paginated(
        api.list_requests(coordinator_headers(), params={"client_id": client["id"]})
    )
    assert len(data) == 2
    assert all(r["client_id"] == client["id"] for r in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# --------------------------------------------------------------------------- #
# Queue B: errors
# --------------------------------------------------------------------------- #
def test_invoice_create_nothing_to_invoice(api):
    """PRD 3.10: "If there is nothing billable and no pending fees for the client, the open is
    rejected with ERR_NOTHING_TO_INVOICE (HTTP 409)."

    Design: Corner/errors/invoice_create_nothing_to_invoice
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    resp = api.create_invoice(factories.invoice_payload(client["id"]), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_INVOICE.value)


def test_mark_no_show_invalid_party(api):
    """PRD 3.6: "naming the `party` as either `CLIENT` or `INTERPRETER`; any other value is
    rejected with `ERR_INVALID_NO_SHOW_PARTY` (HTTP 400)."

    Design: Corner/errors/mark_no_show_invalid_party
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg = dispatch_accept(env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"])
    session = validate_success(api.start_session(asg["id"], make_interpreter_headers(env["interpreter"]["id"])), expected_status=201)
    resp = api.mark_no_show(session["id"], factories.mark_no_show_payload("BOTH"), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_NO_SHOW_PARTY.value)


def test_dispute_session_not_ended(api):
    """PRD 3.8: "A dispute against a session that is not in `ENDED` state is rejected with
    `ERR_SESSION_NOT_ENDED` (HTTP 409),"

    Design: Corner/errors/dispute_session_not_ended
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg = dispatch_accept(env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"])
    itp_h = make_interpreter_headers(env["interpreter"]["id"])
    session = validate_success(api.start_session(asg["id"], itp_h), expected_status=201)
    validate_success(api.connect_session(session["id"], itp_h))  # ACTIVE, not ENDED
    resp = api.dispute_session(session["id"], make_client_headers(env["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ENDED.value)
