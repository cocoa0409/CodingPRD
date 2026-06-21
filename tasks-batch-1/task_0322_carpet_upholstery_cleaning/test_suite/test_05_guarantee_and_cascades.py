"""Re-clean guarantee tests: the GRANTED/DENIED fork-join, the grant cascade
(re-clean job -> room copy -> wallet credit), the inclusive guarantee-window
boundary and its expired twin, grant idempotency, and guarantee RBAC. Also the
DRAFT-only add-on constraints (duplicate add-on, no-rooms quote).

Covers difficulty instances non_linear_state_machine (fork-join), transitive_cascade
(grant cascade), boundary_precision_check (window edge), plus corner state_machine /
validations / rbac instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_completed_job,
    create_customer,
    create_catalog,
    create_crew,
    create_job,
    add_room,
    quote_job,
    book_job,
    start_job,
    complete_job,
    get_customer,
    get_job,
    make_customer_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]


# ─── non_linear_state_machine: grant/deny fork-join ───────────

def test_guarantee_claim_grant_and_deny_diverge(api):
    """PRD §3.5: "On a successful grant, the system mints a re-clean CleaningJob ...
    and it sets the claim's reclean_job_id to the new job's id."
    PRD §3.5: "Denying a claim, which transitions it FILED → DENIED, is
    deliberately the empty mirror of granting: no re-clean job is created, no rooms
    are copied, and no wallet credit is granted."
    PRD §3.5: "it grants a flat goodwill account credit of 2000 cents."

    Two claims on equivalent completed jobs take opposite branches; only GRANTED
    yields a non-null reclean_job_id and the 2000 credit.

    Design: Difficulty/non_linear_state_machine/nonlinear_guarantee_claim_fork_join
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-FJ")
    hdr = make_customer_headers(customer["id"])

    # Grant job: completed at 200, claim filed at 300 (within window 480).
    g = setup_completed_job(rooms=[("RmG", 100, "LIGHT")], customer=customer, catalog=catalog,
                            crew=crew, start_minute=0, end_minute=120, completed_at_minute=200)
    claim_g = validate_success(api.file_claim(
        {"cleaning_job_id": g["job"]["id"], "reason": "still dirty", "filed_at_minute": 300}, hdr), 201)

    # Deny job: completed at 500, claim filed at 600 (within window).
    d = setup_completed_job(rooms=[("RmD", 100, "LIGHT")], customer=customer, catalog=catalog,
                            crew=crew, start_minute=300, end_minute=420, completed_at_minute=500)
    claim_d = validate_success(api.file_claim(
        {"cleaning_job_id": d["job"]["id"], "reason": "buyer remorse", "filed_at_minute": 600}, hdr), 201)

    granted = validate_success(api.grant_claim(claim_g["id"], SERVICE_MANAGER), 200)
    denied = validate_success(api.deny_claim(claim_d["id"], SERVICE_MANAGER), 200)

    assert granted["status"] == "GRANTED"
    assert granted["reclean_job_id"] is not None
    assert denied["status"] == "DENIED"
    assert denied["reclean_job_id"] is None

    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 2000, \
        f"only the grant credits 2000, got {cust_after['wallet_credit_cents']}"


# ─── transitive_cascade: grant -> reclean job -> room copy ────

def test_grant_cascades_to_reclean_job_and_room_copy(api):
    """PRD §3.5: "the system mints a re-clean CleaningJob in DRAFT lifecycle status,
    copying the origin job's customer_id, its service_catalog_id, and its
    recurring_plan_id, and setting the new job's origin_job_id to the origin job's
    id; it copies each of the origin job's room assessments onto the re-clean job."
    PRD §3.5: "it grants a flat goodwill account credit of 2000 cents."

    Origin has TWO rooms; the re-clean is DRAFT, origin_job_id set, both rooms
    copied; the wallet gains 2000.

    Design: Difficulty/transitive_cascade/cascade_grant_to_reclean_job_to_room_copy
    """
    ctx = setup_completed_job(
        rooms=[("Living", 100, "LIGHT"), ("Stairs", 150, "MODERATE")],
        completed_at_minute=800)
    customer = ctx["customer"]
    job_o = ctx["job"]
    hdr = make_customer_headers(customer["id"])

    claim = validate_success(api.file_claim(
        {"cleaning_job_id": job_o["id"], "reason": "resoiled", "filed_at_minute": 900}, hdr), 201)
    granted = validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)
    reclean_id = granted["reclean_job_id"]

    reclean = get_job(reclean_id)
    assert reclean["origin_job_id"] == job_o["id"]
    assert reclean["lifecycle_status"] == "DRAFT"

    rooms_data, rooms_meta = _list(api.list_rooms(reclean_id, SERVICE_MANAGER))
    assert rooms_meta["total_count"] == 2, \
        f"both origin rooms should be copied, got {rooms_meta['total_count']}"

    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 2000


# ─── boundary_precision_check: guarantee window inclusive edge ─

def test_guarantee_window_inclusive_edge_granted(api):
    """PRD §3.5: "the claim is eligible when the elapsed time since completion — the
    claim's filed_at_minute minus the origin job's completed_at_minute — is no
    greater than that window, with the boundary inclusive, so a claim filed exactly
    at the window's end is still eligible."

    dry_time 240 -> window 480; completed 1000, filed exactly 1480 (= 1000 + 480)
    is inclusive-eligible and grant succeeds (2000 credit).

    Design: Difficulty/boundary_precision_check/boundary_guarantee_window_inclusive_edge
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=1000)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "edge", "filed_at_minute": 1480}, hdr), 201)
    granted = validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)
    assert granted["status"] == "GRANTED"
    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 2000


def test_guarantee_window_expired_rejected(api):
    """PRD §3.5: "A claim filed past the window is rejected with
    ERR_GUARANTEE_WINDOW_EXPIRED."
    PRD §3.5: "the claim is eligible when the elapsed time since completion ... is
    no greater than that window, with the boundary inclusive."

    completed 1000, filed 1481 = window+1; one minute past the inclusive edge.

    Design: Corner/validations/guarantee_window_expired_rejected
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=1000)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "late", "filed_at_minute": 1481}, hdr), 201)
    res = api.grant_claim(claim["id"], SERVICE_MANAGER)
    validate_error(res, "ERR_GUARANTEE_WINDOW_EXPIRED", expected_status=409)


# ─── corner: grant idempotency ────────────────────────────────

def test_grant_already_granted_claim_rejected(api):
    """PRD §3.5: "Both grant and deny require the claim to still be FILED; acting on
    an already-adjudicated claim is rejected with ERR_CLAIM_NOT_FILED."

    Design: Corner/state_machines/grant_already_granted_claim_rejected
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=800)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "x", "filed_at_minute": 900}, hdr), 201)
    validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)
    res = api.grant_claim(claim["id"], SERVICE_MANAGER)
    validate_error(res, "ERR_CLAIM_NOT_FILED", expected_status=409)


# ─── corner: rbac on guarantee adjudication ───────────────────

def test_dispatcher_cannot_grant_claim(api):
    """PRD §4 (endpoint table): "POST /guarantee-claims/{id}/grant ... ServiceManager."
    PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_grant_guarantee_claim
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=800)
    customer = ctx["customer"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": ctx["job"]["id"], "reason": "x", "filed_at_minute": 900}, hdr), 201)
    res = api.grant_claim(claim["id"], DISPATCHER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── corner: DRAFT-stage add-on / quote constraints ───────────

def test_duplicate_addon_type_rejected(api):
    """PRD §3.2: "at most one add-on of each type may exist on a job; a second
    add-on of a type already present is rejected with ERR_DUPLICATE_ADDON."

    Design: Corner/validations/duplicate_addon_type_rejected
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Rm", area_sqft=100, soiling_level="LIGHT")
    hdr = make_customer_headers(customer["id"])
    validate_success(api.add_addon(job["id"], {"addon_type": "STAIN"}, hdr), 201)
    res = api.add_addon(job["id"], {"addon_type": "STAIN"}, hdr)
    validate_error(res, "ERR_DUPLICATE_ADDON", expected_status=409)


def test_quote_roomless_job_rejected(api):
    """PRD §3.2: "Quoting requires the job to have at least one room; quoting a
    roomless job is rejected with ERR_NO_ROOMS."

    Design: Corner/validations/quote_zero_room_job_rejected
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    res = api.quote_job(job["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_NO_ROOMS", expected_status=409)


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
