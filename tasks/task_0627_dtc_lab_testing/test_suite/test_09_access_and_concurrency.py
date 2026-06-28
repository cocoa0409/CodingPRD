"""Breadth tests for access control (role/ownership/auth), optimistic concurrency
(cart + order versions), derived-field reconciliation, and immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]


# ---------------------------------------------------------------------------
# Corner/rbac/phlebotomy_tech_cannot_create_offering_403
# ---------------------------------------------------------------------------
def test_phlebotomy_tech_cannot_create_offering_403(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    POST /catalog/test-offerings is CatalogAdmin-only; a PhlebotomyTech is denied.

    Design: Corner/rbac/phlebotomy_tech_cannot_create_offering_403
    """
    resp = api.create_test_offering(
        F.create_test_offering_payload(test_code="RB1", display_name="RBAC One", list_price_cents=1000, specimen_type="BLOOD"),
        PHLEB,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# Corner/rbac/patient_cannot_release_result_403
# ---------------------------------------------------------------------------
def test_patient_cannot_release_result_403(api):
    """PRD 2.1: "the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD 2.5: "Header presence and well-formedness is checked first
    (ERR_MISSING_USER_CONTEXT); then role permission for the operation
    (ERR_FORBIDDEN_ROLE)".

    The release endpoint is LabTech-exclusive; a Patient is denied (role checked
    before state).

    Design: Corner/rbac/patient_cannot_release_result_403
    """
    ctx = fx.setup_processed_result(
        analyzer_value=5,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "RB2", "display_name": "RBAC Two", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, res = ctx["patient"], ctx["lab_result"]
    resp = api.release_lab_result(res["id"], make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# Corner/rbac/missing_user_context_returns_401
# ---------------------------------------------------------------------------
def test_missing_user_context_returns_401(api):
    """PRD 2.1: "A request missing or malforming either header is rejected with
    ERR_MISSING_USER_CONTEXT."

    Design: Corner/rbac/missing_user_context_returns_401
    """
    resp = api.list_test_offerings({})
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ---------------------------------------------------------------------------
# Corner/rbac/patient_cannot_act_on_other_patients_cart_403
# ---------------------------------------------------------------------------
def test_patient_cannot_act_on_other_patients_cart_403(api):
    """PRD 2.1: "A Patient acting on a cart, an order, an order's capture or cancel
    action, a cart line edit, or a physician-order resubmission must own the
    targeted resource; when X-User-ID is not the owning patient_id, the request is
    rejected with ERR_NOT_RESOURCE_OWNER."

    Patient B adds a line to Patient A's cart -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/patient_cannot_act_on_other_patients_cart_403
    """
    off = fx.create_offering(api=api, test_code="OW", display_name="Owner Test", list_price_cents=1000, specimen_type="BLOOD")
    p_a = fx.create_patient(api=api, state_code="CA")
    p_b = fx.create_patient(api=api, state_code="CA")
    cart_a = fx.open_cart(p_a["id"], api=api, fund_source="CARD")
    resp = api.create_cart_line(
        F.create_cart_line_payload(cart_a["id"], off["id"]),
        make_patient_headers(p_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_cart_version_on_checkout_412
# ---------------------------------------------------------------------------
def test_occ_stale_cart_version_on_checkout_412(api):
    """PRD 2.8: "Adding or removing a cart line, or changing a cart's fund source,
    legitimately re-prices the cart and increments Cart.version; if the cart's
    current version has advanced past the value the client supplies, the checkout
    is carrying a stale quote and is rejected with ERR_STALE_CART_VERSION (HTTP
    412)".

    Read version after one line, add a second (bumping version), then check out
    with the stale version.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_cart_version_on_checkout_412
    """
    off1 = fx.create_offering(api=api, test_code="OC1", display_name="OCC One", list_price_cents=1000, specimen_type="BLOOD")
    off2 = fx.create_offering(api=api, test_code="OC2", display_name="OCC Two", list_price_cents=1000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    p_headers = make_patient_headers(patient["id"])
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off1["id"], api=api)
    stale = validate_success(api.get_cart(cart["id"], p_headers))["version"]
    fx.add_cart_line(cart["id"], patient["id"], off2["id"], api=api)  # version bumps

    resp = api.create_order(F.create_order_payload(cart["id"], "HOME_KIT", stale), p_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CART_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_correct_cart_version_checkout_succeeds
# ---------------------------------------------------------------------------
def test_occ_correct_cart_version_checkout_succeeds(api):
    """PRD 3.4: "the supplied expected_cart_version must match the cart's current
    version or the placement is rejected with ERR_STALE_CART_VERSION".
    PRD 3.4: "On success, the source cart's status moves to CHECKED_OUT".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_cart_version_checkout_succeeds
    """
    off = fx.create_offering(api=api, test_code="OK1", display_name="OK One", list_price_cents=1000, specimen_type="BLOOD", home_kit_eligible=True)
    patient = fx.create_patient(api=api, state_code="CA")
    p_headers = make_patient_headers(patient["id"])
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_now = validate_success(api.get_cart(cart["id"], p_headers))
    order = validate_success(
        api.create_order(F.create_order_payload(cart["id"], "HOME_KIT", cart_now["version"]), p_headers),
        expected_status=201,
    )
    assert order is not None
    cart_after = validate_success(api.get_cart(cart["id"], p_headers))
    assert cart_after["status"] == "CHECKED_OUT"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_capture_412
# ---------------------------------------------------------------------------
def test_occ_stale_order_version_on_capture_412(api):
    """PRD 2.8: "A result release or specimen rejection legitimately recomputes the
    order's invoiced total and patient-due amount and increments Order.version; if
    the order's current version has advanced past the supplied value, the capture
    would settle an outdated amount and is rejected with ERR_STALE_ORDER_VERSION
    (HTTP 412)."

    Capture a COMPLETED order carrying the pre-release order version.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_capture_412
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "OO", "display_name": "Order OCC", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    p_headers = make_patient_headers(patient["id"])
    stale_v = order["version"]  # version observed pre-release
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 5, api=api)
    get_success_data(api.release_lab_result(res["id"], LAB2))  # bumps Order.version

    resp = api.capture_payment(order["id"], {"expected_order_version": stale_v}, p_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/repeat_discount_lookback_window_boundary
# ---------------------------------------------------------------------------
def test_repeat_discount_applied_within_lookback(api):
    """PRD 3.2: "This flag is set true when, at the moment the line is added, the
    patient already has a RELEASED lab result for the same test_code whose release
    falls within the lookback window — that is, within the 365 days immediately
    before the cart was created."
    PRD 3.3: "the line's net price is the base multiplied by one minus the repeat
    discount rate of 0.15 — that is, fifteen percent off — rounded half-up to a
    whole cent at this point, per line."

    A 4000 line with prior RELEASED history: round_half_up(4000*0.85)=3400.

    Design: Corner/cross_cutting_complexity_layers/repeat_discount_lookback_window_boundary
    """
    off = fx.create_offering(api=api, test_code="RPD", display_name="Repeat Disc", list_price_cents=4000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    fx.give_patient_released_result(patient["id"], off["id"], analyzer_value=5, api=api)
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    line = fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    assert line["repeat_discount_applied"] is True
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["estimated_total_cents"] == 3400


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/derived_cart_total_reconciles_after_line_removal
# ---------------------------------------------------------------------------
def test_derived_cart_total_reconciles_after_line_removal(api):
    """PRD 3.2: "Removing a line is permitted only on an OPEN cart; it sets
    line_count down by one, recomputes totals, and likewise increments Cart.version
    by one."

    Two 1000 lines (subtotal 2000) drop to one line / 1000 after a DELETE.

    Design: Corner/cross_cutting_complexity_layers/derived_cart_total_reconciles_after_line_removal
    """
    off = fx.create_offering(api=api, test_code="DR", display_name="Derived Recon", list_price_cents=1000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    p_headers = make_patient_headers(patient["id"])
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    line2 = fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    after = validate_success(api.delete_cart_line(line2["id"], p_headers))
    assert after["line_count"] == 1
    assert after["estimated_total_cents"] == 1000


# ---------------------------------------------------------------------------
# Corner/consistency_model/immediate_consistency_collect_visible_in_same_request
# ---------------------------------------------------------------------------
def test_immediate_consistency_collect_visible_on_next_get(api):
    """PRD 3.5: "If the order was in AWAITING_COLLECTION, this first collect advances
    its fulfillment_status to IN_PROCESSING."
    PRD 2.6: "The server performs these propagations automatically without requiring
    a separate client request against each affected resource."

    A collect immediately makes the order readable as IN_PROCESSING.

    Design: Corner/consistency_model/immediate_consistency_collect_visible_in_same_request
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "IC", "display_name": "Immediate", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line = ctx["order"], ctx["order_line"]
    fx.collect_line(line["id"], api=api)
    order_after = validate_success(api.get_order(order["id"], ADMIN))
    assert order_after["fulfillment_status"] == "IN_PROCESSING"
