"""RBAC role / ownership denials, optimistic-concurrency on the work order,
the response envelope, pagination, and immediate cascade visibility
(PRD 2.1, 2.2, 2.3, 2.7, 2.9)."""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import make_customer_headers, make_technician_headers

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Corner rbac — customer_cannot_create_glass_part
# ---------------------------------------------------------------------------
def test_customer_cannot_create_glass_part(api):
    """PRD 2.1: "A request whose role is authenticated but not permitted to invoke
    the targeted endpoint per the access matrix in Section 4 is rejected with
    ERR_FORBIDDEN." Per Section 4, POST /glass-parts is ShopManager-only.

    Design: Corner/rbac/customer_cannot_create_glass_part
    """
    cust = fx.create_customer()
    headers = make_customer_headers(cust["id"])
    resp = api.create_glass_part(
        f.create_glass_part_payload(oem_part_number="FWSNEAK"), headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner rbac — technician_cannot_accept_assessment
# ---------------------------------------------------------------------------
def test_technician_cannot_accept_assessment(api):
    """PRD 2.1: "A request whose role is authenticated but not permitted to invoke
    the targeted endpoint per the access matrix in Section 4 is rejected with
    ERR_FORBIDDEN." Per Section 4, POST /work-orders/{id}/accept-assessment is
    ServiceAdvisor-only.

    Design: Corner/rbac/technician_cannot_accept_assessment
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician()
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    headers = make_technician_headers(tech["id"])
    resp = api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner rbac — customer_cannot_pay_other_customers_work_order
# ---------------------------------------------------------------------------
def test_customer_cannot_pay_other_customers_work_order(api):
    """PRD 2.1: "A Customer ... may pay only against their own work order ... any
    attempt to act on another customer's resource is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/customer_cannot_pay_other_customers_work_order
    """
    cust_a = fx.create_customer()
    cust_b = fx.create_customer()
    veh = fx.create_vehicle(cust_a["id"], glass_part_number="FWOWN")
    wo = fx.create_work_order(cust_a["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    # Customer B (not the owner) tries to pay customer A's work order.
    headers_b = make_customer_headers(cust_b["id"])
    resp = api.create_payment(f.create_payment_payload(wo["id"], 9657, "CARD"), headers_b)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner rbac — missing_auth_header_unauthenticated
# ---------------------------------------------------------------------------
def test_missing_auth_header_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or whose X-User-Role is not one
    of these four known roles, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    cust = fx.create_customer()
    veh = fx.create_vehicle(cust["id"], glass_part_number="FWNOAUTH")
    # No auth headers at all.
    resp = api.create_work_order(
        f.create_work_order_payload(cust["id"], veh["id"]),
        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner cross_cutting — part_order_stale_work_order_version_412
# ---------------------------------------------------------------------------
def test_part_order_stale_work_order_version_rejected(api):
    """PRD 2.7: "A successful reservation moves stock and increments the work order's
    version ... if a second create still carries the version observed before that
    first reservation, it is operating on a stale view and is refused with
    ERR_STALE_WORK_ORDER_VERSION".

    Design: Corner/cross_cutting/part_order_stale_work_order_version_412
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWOCC1")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    stale_version = wo2["version"]
    part = fx.create_glass_part(oem_part_number="FWOCC1", adas_compatible=False, on_hand_qty=5)
    # First reserve succeeds and bumps the work order version past stale_version.
    validate_success(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], stale_version), ADVISOR), 201)
    # Second create still carrying the stale version is refused.
    resp = api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], stale_version), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)


# ---------------------------------------------------------------------------
# Corner cross_cutting — recalibration_open_stale_work_order_version_412
# ---------------------------------------------------------------------------
def test_recalibration_open_stale_work_order_version_rejected(api):
    """PRD 2.7: "because each successful recalibration create — and the finish-install
    that earlier carried the work order into AWAITING_RECALIBRATION — increments that
    version, a create still carrying the older version is acting on a stale view and
    is rejected with the same ERR_STALE_WORK_ORDER_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/recalibration_open_stale_work_order_version_412
    """
    # Drive a REPLACE+ADAS work order to AWAITING_RECALIBRATION; keep the accept-time version.
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=True, oem="FWOCC2")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    stale_version = wo2["version"]  # observed BEFORE part-reserve / schedule / start / finish bumped it
    tech = fx.create_technician(can_mobile=False, adas_certified=True, home_state="CA")
    th = fx.make_technician_headers(tech["id"])
    install_bay = fx.create_service_bay(name="OCC2 Install", bay_type="INSTALL")
    cbay = fx.create_service_bay(name="OCC2 Calib", bay_type="CALIBRATION")
    part = fx.create_glass_part(oem_part_number="FWOCC2", adas_compatible=True, on_hand_qty=5)
    fx.get_success_data(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    appt = fx.book_appointment(wo["id"], tech["id"], "IN_SHOP",
                               "2026-06-13T08:00:00Z", "2026-06-13T08:59:00Z", service_bay_id=install_bay["id"])
    fx.set_clock("2026-06-13T09:00:00Z")
    fx.schedule(wo["id"], appt["id"])
    fx.get_success_data(api.check_in_appointment(appt["id"], th))
    fx.get_success_data(api.start_service(wo["id"], th))
    fx.get_success_data(api.finish_install(wo["id"], {"temp_c": 25, "humidity_pct": 40}, th))
    # Open a recalibration job carrying the long-superseded accept-time version.
    resp = api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo["id"], tech["id"], "STATIC",
            "2026-06-13T09:10:00Z", "2026-06-13T09:40:00Z", stale_version,
            service_bay_id=cbay["id"]),
        th)
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)


# ---------------------------------------------------------------------------
# Corner cross_cutting — occ_version_increments_on_every_mutation
# ---------------------------------------------------------------------------
def test_work_order_version_increments_on_accept(api):
    """PRD 2.4: "an integer that starts at the resource's creation value and
    increments by one on every mutation."
    PRD 3.3: "the price is quoted into total_charge_cents; and the work order's
    version increments by one."

    Design: Corner/cross_cutting/occ_version_increments_on_every_mutation
    """
    cust, veh = fx.setup_customer_and_vehicle()
    wo = fx.create_work_order(cust["id"], veh["id"])
    assert wo["version"] == 1, f"created work order version must be 1, got {wo['version']}"
    asmt = fx.create_assessment(wo["id"])
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    assert wo2["version"] == 2, f"version must increment to 2 after accept-assessment, got {wo2['version']}"


# ---------------------------------------------------------------------------
# Corner cross_cutting — response_envelope_shape_on_create
# ---------------------------------------------------------------------------
def test_response_envelope_shape_on_create(api):
    """PRD 2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format" with meta.api_request_id, meta.api_request_timestamp,
    response_type 'object', and data.

    Design: Corner/cross_cutting/response_envelope_shape_on_create
    """
    resp = api.create_customer(f.create_customer_payload(), ADVISOR)
    validate_success(resp, 201)  # asserts envelope shape internally
    body = resp.json()
    assert "api_request_id" in body["meta"], "meta must carry api_request_id"
    assert "api_request_timestamp" in body["meta"], "meta must carry api_request_timestamp"
    assert body["response_type"] == "object", f"single-resource response_type must be 'object', got {body['response_type']}"
    assert isinstance(body["data"], dict) and body["data"].get("id"), "data must contain the created customer"


# ---------------------------------------------------------------------------
# Corner cross_cutting — pagination_defaults_on_glass_parts_list
# ---------------------------------------------------------------------------
def test_pagination_on_glass_parts_list(api):
    """PRD 2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/cross_cutting/pagination_defaults_on_glass_parts_list
    """
    fx.create_glass_part(oem_part_number=f.unique_oem(), on_hand_qty=1)
    fx.create_glass_part(oem_part_number=f.unique_oem(), on_hand_qty=1)
    resp = api.list_glass_parts(MANAGER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2, f"total_count must be >= 2, got {meta['total_count']}"
    assert meta["limit"] == 1, f"limit must echo 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset must be 0, got {meta['offset']}"
    assert meta["has_more"] is True, f"has_more must be true, got {meta['has_more']}"
    assert len(data) == 1, f"data length must equal limit 1, got {len(data)}"


# ---------------------------------------------------------------------------
# Corner consistency_model — cancel_cascade_visible_immediately
# ---------------------------------------------------------------------------
def test_cancel_cascade_visible_immediately(api):
    """PRD 3.7: "Cancellation cascades to the work order's open satellites: any
    BOOKED appointment for it is moved to CANCELLED".

    Design: Corner/consistency_model/cancel_cascade_visible_immediately
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Imm Bay", bay_type="INSTALL")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])  # REPAIR
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    appt = fx.book_appointment(wo["id"], tech["id"], "IN_SHOP",
                               "2026-06-16T08:00:00Z", "2026-06-16T09:00:00Z", service_bay_id=bay["id"])
    validate_success(api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR), 200)
    wo_cancel = validate_success(api.cancel_work_order(wo["id"], ADVISOR), 200)
    assert wo_cancel["status"] == "CANCELLED"
    appt_after = validate_success(api.get_service_appointment(appt["id"], ADVISOR), 200)
    assert appt_after["status"] == "CANCELLED", (
        f"BOOKED appointment must cascade to CANCELLED immediately, got {appt_after['status']}")
