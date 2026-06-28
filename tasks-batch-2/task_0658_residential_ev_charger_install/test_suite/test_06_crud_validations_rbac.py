"""CRUD/defaults, referential integrity, validations, endpoint conditionals, RBAC, and OCC.

Translates the entities, validations, endpoints, errors, rbac, and cross-cutting
(OCC scope change) corner-design instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_base_job,
    setup_blocked_job,
    setup_activated_job,
    setup_assessed_job,
    create_homeowner_payload,
    create_property_payload,
    create_charger_product_payload,
    create_install_job_payload,
    create_quote_payload,
    create_interconnection_request_payload,
    create_warranty_ticket_payload,
    create_electrician,
    create_homeowner,
    create_charger_product,
    create_property,
    make_homeowner_headers,
    make_electrician_headers,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]
UTILITY = TEST_USERS["utility_reviewer_headers"]


# ─── Entities: creation, defaults, immutability, FK, listing ─────────────

def test_create_install_job_returns_201_with_defaults():
    """PRD §3.2: "The job is born with `workflow_status` `CREATED` and `compliance_status`
    `PENDING_REVIEW`."
    PRD §2.4: "a `version` (an integer that begins at its initial value and increments by
    one on every mutation)."

    Design: Corner/entities/create_install_job_returns_201_with_defaults
    """
    homeowner = create_homeowner()
    charger = create_charger_product(rated_amps=32, required_circuit_amps=40)
    prop = create_property(homeowner["id"], main_breaker_amps=200)
    res = validate_success(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR), 201)
    assert res["workflow_status"] == "CREATED"
    assert res["compliance_status"] == "PENDING_REVIEW"
    assert res["requires_panel_upgrade"] is False
    assert res["version"] == 1


def test_get_install_job_not_found():
    """PRD §2.5: "When a request carries a path identifier, the server first confirms that
    the path-referenced resource exists, rejecting with `ERR_RESOURCE_NOT_FOUND` when it
    does not."

    Design: Corner/entities/get_install_job_not_found
    """
    res = api_client.get_install_job(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


def test_create_install_job_missing_required_field():
    """PRD §3.1: "When request bodies for any of these create operations omit a required
    field, carry a value of the wrong type, or carry an enum value outside its permitted
    set, the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_install_job_missing_required_field
    """
    homeowner = create_homeowner()
    prop = create_property(homeowner["id"], main_breaker_amps=200)
    res = api_client.create_install_job({"property_id": prop["id"]}, COORDINATOR)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_property_default_service_voltage_applied():
    """PRD §3.1: "The nominal split-phase `service_voltage` at the panel may be supplied
    but, when omitted, defaults to 240; it must be 240."

    Design: Corner/entities/create_property_default_service_voltage_applied
    """
    homeowner = create_homeowner()
    res = validate_success(api_client.create_property(
        create_property_payload(homeowner["id"], main_breaker_amps=200), COORDINATOR), 201)
    assert res["service_voltage"] == 240


def test_charger_product_immutable_no_version_field():
    """PRD §2.4: "The `ChargerProduct` catalog entry is immutable after creation: it
    carries only `id` and `created_at`, and has neither an `updated_at` nor a `version`."

    Design: Corner/entities/charger_product_immutable_no_version_field
    """
    cp = validate_success(api_client.create_charger_product(
        create_charger_product_payload(sku="IMMUT5", name="Immut", rated_amps=40,
                                       required_circuit_amps=50, msrp_cents=70000), COORDINATOR), 201)
    # PRD §4: "GET /charger-products/{id} — Fetch a charger product by sku" — the
    # path identifier for the charger catalog is the sku, not the entity id.
    got = validate_success(api_client.get_charger_product(cp["sku"], COORDINATOR), 200)
    assert got["sku"] == "IMMUT5"
    assert "version" not in got


def test_install_job_property_fk_not_found():
    """PRD §2.5: "When a request body carries foreign-key fields — `charger_product_sku`,
    `property_id`, `install_job_id`, or `electrician_id` — the server validates that each
    referenced resource exists, rejecting a dangling reference with `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/install_job_property_fk_not_found
    """
    charger = create_charger_product()
    res = api_client.create_install_job(
        {"property_id": "00000000-0000-4000-8000-0000000000aa",
         "charger_product_sku": charger["sku"]}, COORDINATOR)
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_list_install_jobs_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_install_jobs_pagination_envelope
    """
    ctx = setup_base_job()
    data, meta = validate_paginated(api_client.list_install_jobs(
        COORDINATOR, params={"property_id": ctx["property"]["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ─── State machine: invalid transition / terminal lockdown ───────────────

def test_cancel_already_cancelled_job_invalid_state():
    """PRD §3.7: "Attempting to cancel from a state outside the permitted set is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_install_job_from_cancelled_returns_invalid_state
    """
    ctx = setup_base_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.cancel_install_job(ctx["job"]["id"], ho_headers))
    res = api_client.cancel_install_job(ctx["job"]["id"], ho_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_accepted_quote_rejects_further_reject():
    """PRD §3.4: "A quote acceptance whose `SENT` precondition is unmet is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.4: "The homeowner then either accepts or rejects a sent quote."

    Design: Corner/state_machines/terminal_quote_accepted_locked
    """
    ctx = setup_assessed_job()
    quote = get_success_data(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_install_job_version": job["version"]}, ho_headers))
    # Quote now ACCEPTED (terminal). Rejecting it requires SENT -> ERR_INVALID_STATE.
    res = api_client.reject_quote(quote["id"], ho_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_warranty_reopen_limit_reached():
    """PRD §3.9: "A homeowner may reopen a resolved ticket, which is permitted only while
    `reopen_count` is fewer than 2 ... A reopen attempted once the ticket has already been
    reopened twice is rejected with `ERR_REOPEN_LIMIT_REACHED`."

    Design: Corner/state_machines/warranty_reopen_limit_reached
    """
    ctx = setup_activated_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    el_headers = make_electrician_headers(ctx["electrician"]["id"])
    ticket = get_success_data(api_client.create_warranty_ticket(
        create_warranty_ticket_payload(ctx["job"]["id"], summary="issue"), ho_headers))
    for _ in range(2):
        get_success_data(api_client.diagnose_warranty_ticket(ticket["id"], el_headers))
        get_success_data(api_client.resolve_warranty_ticket(ticket["id"], el_headers))
        get_success_data(api_client.reopen_warranty_ticket(ticket["id"], ho_headers))
    # reopen_count == 2 now; advance to RESOLVED again and try a third reopen.
    get_success_data(api_client.diagnose_warranty_ticket(ticket["id"], el_headers))
    get_success_data(api_client.resolve_warranty_ticket(ticket["id"], el_headers))
    res = api_client.reopen_warranty_ticket(ticket["id"], ho_headers)
    validate_error(res, "ERR_REOPEN_LIMIT_REACHED")


# ─── Validations ─────────────────────────────────────────────────────────

def test_circuit_exceeds_panel_on_create_job():
    """PRD §2.10: "If the scoped charger's `required_circuit_amps` exceeds the band allowed
    for the property's panel, the operation is rejected with `ERR_CIRCUIT_EXCEEDS_PANEL`
    (HTTP 422). This check is enforced both when an install job is first created and
    whenever its charger is re-scoped."

    Design: Corner/validations/circuit_exceeds_panel_on_create_job
    """
    homeowner = create_homeowner()
    charger = create_charger_product(rated_amps=40, required_circuit_amps=50)  # needs 50A circuit
    prop = create_property(homeowner["id"], main_breaker_amps=100)  # 100A band allows only 40A
    res = api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR)
    validate_error(res, "ERR_CIRCUIT_EXCEEDS_PANEL")


def test_permit_blocked_when_panel_upgrade_required():
    """PRD §3.5: "a job whose `requires_panel_upgrade` is true (and is therefore `BLOCKED`)
    cannot start permitting and is rejected with `ERR_PANEL_UPGRADE_REQUIRED` (HTTP 409)."

    Design: Corner/validations/permit_blocked_when_panel_upgrade_required
    """
    ctx = setup_blocked_job()
    res = api_client.create_permit_application(
        {"install_job_id": ctx["job"]["id"], "jurisdiction_code": "AHJ1"}, COORDINATOR)
    validate_error(res, "ERR_PANEL_UPGRADE_REQUIRED")


def test_territory_mismatch_on_interconnection_approve():
    """PRD §3.5: "Approval requires that the request's `utility_territory_code` equal the
    property's `utility_territory_code`; a mismatch is rejected with `ERR_TERRITORY_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/territory_mismatch_on_interconnection_approve
    """
    ctx = setup_assessed_job()  # property territory PGE
    # Drive job to QUOTED so the compliance track is reachable
    quote = get_success_data(api_client.create_quote(
        create_quote_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_install_job_version": job["version"]}, ho_headers))
    ic = get_success_data(api_client.create_interconnection_request(
        create_interconnection_request_payload(ctx["job"]["id"], utility_territory_code="SCE"),
        COORDINATOR))
    get_success_data(api_client.start_review_interconnection_request(ic["id"], UTILITY))
    res = api_client.approve_interconnection_request(ic["id"], UTILITY)
    validate_error(res, "ERR_TERRITORY_MISMATCH")


def test_incentive_fully_absorbed_rejected():
    """PRD §3.8: "a `UTILITY_REBATE` claim whose clamped award computes to exactly 0 is
    non-fundable and is rejected at creation with `ERR_INCENTIVE_FULLY_ABSORBED` (HTTP 422)."

    Design: Corner/validations/incentive_fully_absorbed_rejected
    """
    ctx = setup_activated_job()
    # Federal eligible 400000 -> award min(120000,100000)=100000, submitted
    fed = get_success_data(api_client.create_incentive_claim(
        {"install_job_id": ctx["job"]["id"], "program_kind": "FEDERAL_45W",
         "eligible_cost_cents": 400000}, COORDINATOR))
    get_success_data(api_client.submit_incentive_claim(fed["id"], COORDINATOR))
    # Utility eligible 120000 -> stack_cap round(0.80*120000)=96000; util_raw 80000;
    # fed 100000 + 80000 > 96000 -> award max(0, 96000-100000)=0 -> rejected
    res = api_client.create_incentive_claim(
        {"install_job_id": ctx["job"]["id"], "program_kind": "UTILITY_REBATE",
         "eligible_cost_cents": 120000, "utility_program_tier": "PREMIUM",
         "includes_panel_upgrade": True}, COORDINATOR)
    validate_error(res, "ERR_INCENTIVE_FULLY_ABSORBED")


def test_out_of_bounds_main_breaker_amps_rejected():
    """PRD §3.1: "Numeric inputs that fall outside their declared bounds — a
    `main_breaker_amps` not in the permitted set, or a window minute outside its range — are
    rejected with `ERR_VALIDATION_LIMIT`."

    Design: Corner/validations/out_of_bounds_main_breaker_amps_rejected
    """
    homeowner = create_homeowner()
    res = api_client.create_property(
        create_property_payload(homeowner["id"], main_breaker_amps=125), COORDINATOR)
    validate_error(res, "ERR_VALIDATION_LIMIT")


# ─── Endpoints: conditional actions ──────────────────────────────────────

def test_activate_with_wrong_pairing_code_rejected():
    """PRD §3.7: "Activation requires the job to be in `workflow_status` `INSTALLED` and
    the submitted `pairing_code` to equal the job's minted `activation_pairing_code`."

    Design: Corner/endpoints/activate_with_wrong_pairing_code_rejected
    """
    from test_helpers import setup_installed_job
    ctx = setup_installed_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    res = api_client.activate_install_job(
        ctx["job"]["id"], {"pairing_code": "WRONG-CODE"}, ho_headers)
    validate_error(res, "ERR_INVALID_REQUEST")
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["workflow_status"] == "INSTALLED"


def test_close_blocked_by_open_warranty_ticket():
    """PRD §3.7: "Closure requires the job to be in `workflow_status` `ACTIVATED` and no
    warranty ticket on the job to be in `OPEN`, `DIAGNOSING`, or `AWAITING_PARTS` status; an
    unresolved warranty ticket blocks closure and is rejected with
    `ERR_OPEN_WARRANTY_BLOCKS_CLOSE`."

    Design: Corner/endpoints/close_blocked_by_open_warranty_ticket
    """
    ctx = setup_activated_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.create_warranty_ticket(
        create_warranty_ticket_payload(ctx["job"]["id"], summary="open issue"), ho_headers))
    res = api_client.close_install_job(ctx["job"]["id"], COORDINATOR)
    validate_error(res, "ERR_OPEN_WARRANTY_BLOCKS_CLOSE")


# ─── Errors: terminal permit ─────────────────────────────────────────────

def test_permit_rejected_final_acted_on():
    """PRD §3.5: "Acting on a permit already in the terminal `REJECTED` state is rejected
    with `ERR_PERMIT_REJECTED_FINAL`"

    Design: Corner/errors/permit_rejected_final_acted_on
    """
    ctx = setup_assessed_job()
    permit = get_success_data(api_client.create_permit_application(
        {"install_job_id": ctx["job"]["id"], "jurisdiction_code": "AHJ1"}, COORDINATOR))
    for _ in range(3):
        get_success_data(api_client.request_corrections_permit_application(permit["id"], COORDINATOR))
        api_client.resubmit_permit_application(permit["id"], COORDINATOR)
    # After 3rd resubmit at correction_rounds==3 the permit is REJECTED. Act again.
    res = api_client.resubmit_permit_application(permit["id"], COORDINATOR)
    validate_error(res, "ERR_PERMIT_REJECTED_FINAL")


# ─── RBAC ────────────────────────────────────────────────────────────────

def test_electrician_cannot_create_quote():
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/electrician_cannot_create_quote
    """
    ctx = setup_assessed_job()
    el = create_electrician()
    el_headers = make_electrician_headers(el["id"])
    res = api_client.create_quote(create_quote_payload(ctx["job"]["id"]), el_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_homeowner_not_owner_cannot_cancel_others_job():
    """PRD §2.1: "ownership-scoped homeowner actions therefore resolve the job's property
    to its owning homeowner and require that homeowner to equal `X-User-ID`. An owner
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/homeowner_not_owner_cannot_cancel_others_job
    """
    ctx = setup_base_job()
    other = create_homeowner()
    other_headers = make_homeowner_headers(other["id"])
    res = api_client.cancel_install_job(ctx["job"]["id"], other_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    ctx = setup_base_job()
    res = api_client.get_install_job(ctx["job"]["id"], headers={"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── OCC scope-change stale version ──────────────────────────────────────

def test_occ_scope_change_stale_version_rejected():
    """PRD §2.7: "A request to change an install job's scoped charger before quote
    acceptance must include `expected_install_job_version`. If it does not equal the job's
    current `version`, the re-scope is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_scope_change_stale_version_rejected
    """
    homeowner = create_homeowner()
    prop = create_property(homeowner["id"], main_breaker_amps=200)
    cp_a = create_charger_product(rated_amps=32, required_circuit_amps=40)
    cp_b = create_charger_product(rated_amps=40, required_circuit_amps=50)
    cp_c = create_charger_product(rated_amps=48, required_circuit_amps=60)
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], cp_a["sku"]), COORDINATOR))
    v0 = job["version"]
    # First scope change advances version.
    get_success_data(api_client.scope_install_job(
        job["id"], {"charger_product_sku": cp_b["sku"], "expected_install_job_version": v0},
        COORDINATOR))
    # Second scope change still carries stale v0 -> rejected.
    res = api_client.scope_install_job(
        job["id"], {"charger_product_sku": cp_c["sku"], "expected_install_job_version": v0},
        COORDINATOR)
    validate_error(res, "ERR_STALE_JOB_VERSION")
