"""Access control and optimistic concurrency: role exclusivity, customer peer
isolation, unauthenticated rejection, and the lot/locker version OCC guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ensure_pricing_policy,
    create_cut_type,
    create_customer,
    create_animal_share,
    create_locker,
    receive_lot,
    place_and_confirm_order,
    create_temp_reading_payload,
    make_customer_headers,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ===========================================================================
# Corner: rbac / counterclerk_cannot_draw_line
# ===========================================================================
def test_counterclerk_cannot_draw_line(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the `POST /order-lines/{id}/draw` row authorizes only `Butcher`.

    A CounterClerk calling draw -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/counterclerk_cannot_draw_line
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Rita Role", phone="555-1013")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 1000)])
    lot = receive_lot(cut["id"], received_weight_g=2000)
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
         "expected_inventory_lot_version": lot["version"]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / customer_cannot_cancel_others_claim
# ===========================================================================
def test_customer_cannot_cancel_others_claim(api):
    """PRD §2.1: "a `Customer` may cancel an order or a share claim only when the
    order's or claim's `customer_id` equals `X-User-ID`".
    PRD §3.7: "A customer cancelling a claim they do not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Customer B cancelling customer A's claim -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/customer_cannot_cancel_others_claim
    """
    share = create_animal_share(carcass_weight_g=100000, deposit_cents=8000)
    a = create_customer(full_name="Owner A", phone="555-1014")
    b = create_customer(full_name="Intruder B", phone="555-1015")
    claim = validate_success(
        api.create_share_claim(
            {"animal_share_id": share["id"], "customer_id": a["id"], "fraction": "QUARTER"},
            make_customer_headers(a["id"]),
        ),
        expected_status=201,
    )
    resp = api.cancel_share_claim(claim["id"], make_customer_headers(b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ===========================================================================
# Corner: rbac / missing_auth_headers_unauthenticated
# ===========================================================================
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    A request with an unknown role -> ERR_UNAUTHENTICATED before any other check.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    anon = build_user_headers("anon-1", "Anonymous")
    resp = api.create_cut_type(
        {"code": "RIBEYE", "species": "BEEF", "base_price_cents_per_kg": 4000}, anon
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_lot_version_on_second_draw
# ===========================================================================
def test_occ_stale_lot_version_on_second_draw(api):
    """PRD §2.9: "if another writer (a different order line, or a sausage batch
    reservation) has advanced the lot's `version` since the acting client last read
    the lot, the client's view is stale ... the draw is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412)."

    First draw bumps lot.version 1->2; a second draw carrying the stale
    expected_inventory_lot_version 1 -> ERR_STALE_LOT_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_second_draw
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Stan Stale", phone="555-1016")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 1000), (cut["id"], 1000)])
    lot = receive_lot(cut["id"], received_weight_g=5000)
    stale_version = lot["version"]
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
                       "expected_inventory_lot_version": stale_version}, BUTCHER)
    )
    resp = api.draw_line(
        line_ids[1],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
         "expected_inventory_lot_version": stale_version},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_lot_version_increments_on_success
# ===========================================================================
def test_occ_lot_version_increments_on_success(api):
    """PRD §2.9: "A draw legitimately reduces a lot's `remaining_weight_g` and
    bumps its `version`".
    PRD §3.5: "reduces the lot's `remaining_weight_g` by that amount, increments
    the lot's `version`".

    A successful draw against a version-1 lot leaves it at version 2, remaining
    5000-1000=4000.

    Design: Corner/cross_cutting_complexity_layers/occ_lot_version_increments_on_success
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Vera Version", phone="555-1017")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 1000)])
    lot = receive_lot(cut["id"], received_weight_g=5000)
    assert lot["version"] == 1
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    lot_after = get_success_data(api.get_inventory_lot(lot["id"], BUTCHER))
    assert lot_after["version"] == 2
    assert lot_after["remaining_weight_g"] == 4000


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_locker_version_on_release
# ===========================================================================
def test_occ_stale_locker_version_on_release(api):
    """PRD §3.3: "The manager releases a `QUARANTINED` locker, which must carry
    `expected_dry_age_locker_version` matching the locker's current `version` as
    described in §2.9; a mismatch is rejected with `ERR_STALE_LOCKER_VERSION`
    (HTTP 412)."

    The locker's version advances when the out-of-band reading quarantines it;
    releasing with a version one below the pre-quarantine capture is stale ->
    ERR_STALE_LOCKER_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_locker_version_on_release
    """
    create_cut_type(code="DRY_RIBEYE", species="BEEF",
                    base_price_cents_per_kg=6000, requires_dry_age=True)
    locker = create_locker(name="LOCKER-STALE", capacity_g=20000)
    lv_pre = get_success_data(api.get_locker(locker["id"], MGR))["version"]
    get_success_data(
        api.create_temp_reading(locker["id"],
                                create_temp_reading_payload(temp_c=11.0,
                                                            reading_at="2026-06-02T00:00:00Z"),
                                SAFETY)
    )
    resp = api.release_locker(
        locker["id"], {"expected_dry_age_locker_version": lv_pre - 1}, MGR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOCKER_VERSION.value)
