"""Subscription lifecycle: pause/resume cycle, cancellation cascade, skip, and the
optimistic-concurrency guard on scheduling the next fix.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_client_headers,
    create_active_client, setup_styling_fix, setup_preview_fix,
    schedule_fix, client_version, get_client, get_fix, get_product,
)

OPS = TEST_USERS["ops_headers"]


def _item_status(api, fix_id, item_id):
    items = get_success_data(api.list_fix_items(fix_id, headers=OPS))
    match = [it for it in items if it["id"] == item_id]
    assert match, f"item {item_id} not found in fix {fix_id}"
    return match[0]["status"]


# ----------------------------------------- Difficulty: pause/resume revision loop
def test_pause_moves_active_client_to_paused(api):
    """PRD §3.2: "Pausing an ACTIVE subscription moves the client to PAUSED."

    Design: Difficulty/non_linear_state_machine/client_pause_resume_cycle
    """
    client = create_active_client(region_code="CA")
    resp = api.pause_client(client["id"], headers=make_client_headers(client["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "PAUSED", f"expected PAUSED, got {data['status']}"


def test_resume_returns_paused_client_to_active(api):
    """PRD §3.2: "Resuming a PAUSED subscription moves the client back to ACTIVE and
    recomputes the next scheduled_ship_date as the current clock plus one cadence
    interval."

    Design: Difficulty/non_linear_state_machine/client_pause_resume_cycle
    """
    client = create_active_client(region_code="CA")
    hdr = make_client_headers(client["id"])
    validate_success(api.pause_client(client["id"], headers=hdr), 200)
    resp = api.resume_client(client["id"], headers=hdr)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE", f"expected ACTIVE after resume, got {data['status']}"


# --------------------------------------------- Difficulty: cancellation cascade
def test_cancel_cascades_client_fix_item_to_terminal(api):
    """PRD §3.2: "When cancellation proceeds, every fix of the client in REQUESTED,
    STYLING, or PREVIEW is cancelled as a cascade; each cascaded fix releases its
    SELECTED items to RELEASED with the corresponding restock, and each affected
    stylist's active-fix count is recomputed."

    Design: Difficulty/transitive_cascade/client_cancel_releases_items_restocks_products
    """
    ctx = setup_styling_fix(prices=[3000])
    resp = api.cancel_client(ctx["client_id"], headers=make_client_headers(ctx["client_id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"
    assert get_fix(ctx["fix_id"])["status"] == "CANCELLED"
    assert _item_status(api, ctx["fix_id"], ctx["item_ids"][0]) == "RELEASED"


def test_cancel_restocks_released_item_inventory(api):
    """PRD §2.7: "Release (a selected item is removed or released, or a returned item
    is received back): reserved_count decreases by one and available_count increases
    by one."

    Design: Difficulty/transitive_cascade/client_cancel_releases_items_restocks_products
    """
    ctx = setup_styling_fix(prices=[3000])  # product total_stock 5 → available 4, reserved 1
    product_before = get_product(ctx["product_ids"][0])
    assert product_before["available_count"] == 4 and product_before["reserved_count"] == 1
    validate_success(
        api.cancel_client(ctx["client_id"], headers=make_client_headers(ctx["client_id"])), 200)
    product = get_product(ctx["product_ids"][0])
    assert product["available_count"] == 5
    assert product["reserved_count"] == 0
    assert product["sold_count"] == 0


# ------------------------------------------------------------ Corner: cascades
def test_pause_cancels_requested_fix(api):
    """PRD §3.2: "As a side effect, every fix of that client still in REQUESTED is
    cancelled; each cancelled fix releases its SELECTED items to RELEASED, restocking
    each owning product (its reserved_count decreases by one and available_count
    increases by one)."

    Design: Corner/endpoints/pause_cancels_requested_fix_and_restocks
    """
    client = create_active_client(region_code="CA")
    fix = schedule_fix(client["id"])
    resp = api.pause_client(client["id"], headers=make_client_headers(client["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "PAUSED"
    assert get_fix(fix["id"])["status"] == "CANCELLED"


def test_cancel_blocked_by_shipped_fix(api):
    """PRD §3.2: "It is blocked when the client has any fix in SHIPPED or DELIVERED —
    an in-flight box must complete checkout first — and such an attempt is rejected
    with ERR_CLIENT_HAS_INFLIGHT_FIX."

    Design: Corner/state_machines/cancel_blocked_by_inflight_shipped_fix
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    validate_success(api.ship_fix(ctx["fix_id"], headers=OPS), 200)
    resp = api.cancel_client(ctx["client_id"], headers=make_client_headers(ctx["client_id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_INFLIGHT_FIX.value)
    assert get_client(ctx["client_id"])["status"] == "ACTIVE"


def test_skip_without_pending_fix_rejected(api):
    """PRD §3.2: "A subscriber may skip the upcoming box, which requires the client to
    be ACTIVE and to have exactly one REQUESTED fix; if there is no such single
    pending fix, the skip is rejected with ERR_NO_PENDING_FIX."

    Design: Corner/state_machines/skip_without_pending_fix_returns_no_pending
    """
    client = create_active_client(region_code="CA")
    resp = api.skip_client(client["id"], headers=make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_PENDING_FIX.value)


# ---------------------------------------------------- Corner: optimistic concurrency
def test_schedule_with_stale_version_rejected(api):
    """PRD §2.6: "The request must carry expected_client_version, the version of the
    Client the caller last observed. If that value does not match the client's current
    version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_version_on_schedule_returns_412
    """
    client = create_active_client(region_code="CA")
    hdr = make_client_headers(client["id"])
    v = client_version(client["id"])
    validate_success(api.schedule_fix(client["id"], {"expected_client_version": v}, headers=hdr), 201)
    # second schedule reuses the now-stale pre-supersede version
    resp = api.schedule_fix(client["id"], {"expected_client_version": v}, headers=hdr)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_schedule_with_current_version_supersedes_prior_fix(api):
    """PRD §3.2: "Any prior REQUESTED fix of the same client is superseded —
    transitioned to CANCELLED, releasing and restocking its selected items — and the
    client's version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_supersedes_prior_fix
    """
    client = create_active_client(region_code="CA")
    hdr = make_client_headers(client["id"])
    v1 = client_version(client["id"])
    fa = validate_success(
        api.schedule_fix(client["id"], {"expected_client_version": v1}, headers=hdr), 201)
    v2 = client_version(client["id"])
    fb = validate_success(
        api.schedule_fix(client["id"], {"expected_client_version": v2}, headers=hdr), 201)
    assert fb["status"] == "REQUESTED"
    assert get_fix(fa["id"])["status"] == "CANCELLED"
