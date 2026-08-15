"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.

Identity threading (PRD §2.1): weld-pass recording always runs under
make_welder_headers(welder["id"]) because the Welder role is entity-backed.
QCManager/CWI/QualityInspector identities are opaque; fixtures accept
user-id overrides so segregation-sensitive scenarios can thread distinct ids.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SHOP_CLOCK_INIT_ISO
from .factories import (
    DEFAULTS,
    create_consumable_issue_payload,
    create_consumable_lot_payload,
    create_distortion_report_payload,
    create_fixture_payload,
    create_joint_payload,
    create_ndt_inspection_payload,
    create_ndt_vendor_payload,
    create_oven_payload,
    create_pqr_payload,
    create_qualification_payload,
    create_shop_order_payload,
    create_shop_payload,
    create_traveler_sign_off_payload,
    create_vt_inspection_payload,
    create_weld_pass_payload,
    create_welder_payload,
    create_weldment_payload,
    create_wps_payload,
    record_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_cwi_headers,
    make_qc_manager_headers,
    make_quality_inspector_headers,
    make_welder_headers,
)

SHOP_ADMIN = TEST_USERS["shop_admin_headers"]
QC_MANAGER = TEST_USERS["qc_manager_headers"]
WELD_LEAD = TEST_USERS["weld_lead_headers"]
CWI = TEST_USERS["cwi_headers"]
MATERIAL_CONTROLLER = TEST_USERS["material_controller_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
QUALITY_INSPECTOR = TEST_USERS["quality_inspector_headers"]
SHIPPING_CLERK = TEST_USERS["shipping_clerk_headers"]


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and transitions
# ---------------------------------------------------------------------------

def create_shop(shop_name="Test Shop", repair_rate_limit_pct=None):
    """Create a shop (logical clock starts at 2026-08-01T00:00:00Z)."""
    payload = create_shop_payload(shop_name=shop_name)
    if repair_rate_limit_pct is not None:
        payload["repair_rate_limit_pct"] = repair_rate_limit_pct
    return get_success_data(api_client.create_shop(payload, SHOP_ADMIN), 201)


def set_clock(to_iso8601: str):
    """Advance the shop logical clock; runs the continuity/posture sweeps."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, SHOP_ADMIN), 200)


def create_welder(shop_id, stencil="W-1", full_name="Welder One"):
    payload = create_welder_payload(stencil=stencil, full_name=full_name)
    return get_success_data(api_client.create_welder(shop_id, payload,
                                                     SHOP_ADMIN), 201)


def create_ndt_vendor(shop_id, vendor_name="NDT Vendor One",
                      supported_methods=("UT",), hourly_capacity=1):
    payload = create_ndt_vendor_payload(
        vendor_name=vendor_name,
        supported_methods=list(supported_methods),
        hourly_capacity=hourly_capacity)
    return get_success_data(
        api_client.create_ndt_vendor(shop_id, payload, SHOP_ADMIN), 201)


def create_oven(shop_id, oven_code="OV-1", holding_temp_c=None,
                capacity_electrodes_kg=None):
    payload = create_oven_payload(
        oven_code=oven_code,
        holding_temp_c=holding_temp_c or DEFAULTS["OVEN_TEMP_C"],
        capacity_electrodes_kg=(
            capacity_electrodes_kg or DEFAULTS["OVEN_CAPACITY_KG"]))
    return get_success_data(api_client.create_oven(shop_id, payload,
                                                   MATERIAL_CONTROLLER), 201)


def create_pqr(shop_id, pqr_number="PQR-1", process=None, base_metal_spec=None,
               thickness_range_min_mm=None, thickness_range_max_mm=None):
    payload = create_pqr_payload(
        pqr_number=pqr_number,
        process=process or DEFAULTS["PROCESS"],
        base_metal_spec=base_metal_spec or DEFAULTS["BASE_METAL_SPEC"],
        thickness_range_min_mm=(
            thickness_range_min_mm
            if thickness_range_min_mm is not None
            else DEFAULTS["PQR_THICKNESS_MIN_MM"]),
        thickness_range_max_mm=(
            thickness_range_max_mm
            if thickness_range_max_mm is not None
            else DEFAULTS["PQR_THICKNESS_MAX_MM"]))
    return get_success_data(api_client.create_pqr(shop_id, payload,
                                                  QC_MANAGER), 201)


def approve_pqr(shop_id, pqr_id, reviewer_id="qc-reviewer-1"):
    """Approve a DRAFT PQR; records reviewer_id as reviewed_by_user_id."""
    return get_success_data(
        api_client.approve_pqr(shop_id, pqr_id,
                               make_qc_manager_headers(reviewer_id)), 200)


def create_and_approve_pqr(shop_id, reviewer_id="qc-reviewer-1", **kwargs):
    pqr = create_pqr(shop_id, **kwargs)
    return approve_pqr(shop_id, pqr["id"], reviewer_id)


def create_wps(shop_id, pqr_id, wps_number="WPS-1", revision=1, process=None,
               base_metal_spec=None, thickness_min_mm=None,
               thickness_max_mm=None):
    payload = create_wps_payload(
        pqr_id,
        wps_number=wps_number,
        revision=revision,
        process=process or DEFAULTS["PROCESS"],
        base_metal_spec=base_metal_spec or DEFAULTS["BASE_METAL_SPEC"],
        thickness_min_mm=(
            thickness_min_mm if thickness_min_mm is not None
            else DEFAULTS["WPS_THICKNESS_MIN_MM"]),
        thickness_max_mm=(
            thickness_max_mm if thickness_max_mm is not None
            else DEFAULTS["WPS_THICKNESS_MAX_MM"]))
    return get_success_data(api_client.create_wps(shop_id, payload,
                                                  QC_MANAGER), 201)


def approve_wps(shop_id, wps_id, approver_id="qc-approver-1"):
    """Approve a DRAFT WPS, threading the current version (OCC, PRD §2.6)."""
    current = get_success_data(api_client.get_wps(shop_id, wps_id, SHOP_ADMIN))
    return get_success_data(
        api_client.approve_wps(
            shop_id, wps_id,
            {"expected_wps_version": current["version"]},
            make_qc_manager_headers(approver_id)), 200)


def create_and_approve_wps(shop_id, pqr_id, approver_id="qc-approver-1",
                           **kwargs):
    wps = create_wps(shop_id, pqr_id, **kwargs)
    return approve_wps(shop_id, wps["id"], approver_id)


def create_qualification(shop_id, welder_id, wps_id, process=None,
                         qualified_at_utc=None):
    payload = create_qualification_payload(
        welder_id, wps_id,
        process=process or DEFAULTS["PROCESS"],
        qualified_at_utc=qualified_at_utc or DEFAULTS["QUALIFIED_AT_UTC"])
    return get_success_data(
        api_client.create_qualification(shop_id, payload, QC_MANAGER), 201)


def create_consumable_lot(shop_id, oven_id, lot_number="LOT-1",
                          filler_spec="E7018", process=None, received_kg=None):
    payload = create_consumable_lot_payload(
        oven_id,
        lot_number=lot_number,
        filler_spec=filler_spec,
        process=process or DEFAULTS["PROCESS"],
        received_kg=(
            received_kg if received_kg is not None
            else DEFAULTS["LOT_RECEIVED_KG"]))
    return get_success_data(
        api_client.create_consumable_lot(shop_id, payload,
                                         MATERIAL_CONTROLLER), 201)


def issue_consumables(shop_id, lot_id, oven_id, welder_id, issued_kg=None):
    payload = create_consumable_issue_payload(
        lot_id, oven_id, welder_id,
        issued_kg=issued_kg if issued_kg is not None else DEFAULTS["ISSUED_KG"])
    return get_success_data(
        api_client.create_consumable_issue(shop_id, payload,
                                           MATERIAL_CONTROLLER), 201)


def return_issue(shop_id, issue_id):
    return get_success_data(
        api_client.return_consumable_issue(shop_id, issue_id,
                                           MATERIAL_CONTROLLER), 200)


def rebake_lot(shop_id, lot_id):
    return get_success_data(
        api_client.rebake_lot(shop_id, lot_id, {}, MATERIAL_CONTROLLER), 200)


def create_fixture(shop_id, fixture_code="FIX-1", capacity_weldments=None,
                   owner_party="SHOP"):
    payload = create_fixture_payload(
        fixture_code=fixture_code,
        capacity_weldments=(
            capacity_weldments
            if capacity_weldments is not None
            else DEFAULTS["FIXTURE_CAPACITY"]),
        owner_party=owner_party)
    return get_success_data(
        api_client.create_fixture(shop_id, payload, PRODUCTION_PLANNER), 201)


def reserve_fixture(shop_id, fixture_id):
    return get_success_data(
        api_client.reserve_fixture(shop_id, fixture_id, PRODUCTION_PLANNER),
        200)


def create_shop_order(shop_id, po_number="PO-1", customer_name="Customer One",
                      promised_ship_date_utc=None):
    payload = create_shop_order_payload(
        po_number=po_number,
        customer_name=customer_name,
        promised_ship_date_utc=(
            promised_ship_date_utc or DEFAULTS["PROMISED_SHIP_DATE"]))
    return get_success_data(
        api_client.create_shop_order(shop_id, payload, PRODUCTION_PLANNER),
        201)


def create_weldment(shop_id, order_id, fixture_id, weldment_serial="WM-1",
                    drawing_revision="R1"):
    payload = create_weldment_payload(
        fixture_id,
        weldment_serial=weldment_serial,
        drawing_revision=drawing_revision)
    return get_success_data(
        api_client.create_weldment(shop_id, order_id, payload,
                                   PRODUCTION_PLANNER), 201)


def create_joint(shop_id, weldment_id, wps_id, joint_number="J-1",
                 base_metal_thickness_mm=None, required_ndt_methods=("VT",)):
    payload = create_joint_payload(
        wps_id,
        joint_number=joint_number,
        base_metal_thickness_mm=(
            base_metal_thickness_mm
            if base_metal_thickness_mm is not None
            else DEFAULTS["JOINT_THICKNESS_MM"]),
        required_ndt_methods=list(required_ndt_methods))
    return get_success_data(
        api_client.create_joint(shop_id, weldment_id, payload, WELD_LEAD),
        201)


def get_joint(shop_id, joint_id):
    return get_success_data(api_client.get_joint(shop_id, joint_id,
                                                 SHOP_ADMIN))


def get_weldment(shop_id, weldment_id):
    return get_success_data(api_client.get_weldment(shop_id, weldment_id,
                                                    SHOP_ADMIN))


def start_fabrication(shop_id, joint_id):
    """Start fabrication, threading the joint's current version (PRD §2.6)."""
    current = get_joint(shop_id, joint_id)
    return get_success_data(
        api_client.start_fabrication(
            shop_id, joint_id,
            {"expected_joint_version": current["version"]},
            WELD_LEAD), 200)


def record_weld_pass(shop_id, joint_id, welder_id, qualification_id, lot_id,
                     consumable_used_kg=None, is_repair=False):
    """Record a weld pass under the welder's own entity identity (PRD §2.1)."""
    payload = create_weld_pass_payload(
        welder_id, qualification_id, lot_id,
        consumable_used_kg=(
            consumable_used_kg
            if consumable_used_kg is not None
            else DEFAULTS["PASS_USED_KG"]),
        is_repair=is_repair)
    return get_success_data(
        api_client.record_weld_pass(shop_id, joint_id, payload,
                                    make_welder_headers(welder_id)), 201)


def weld_out(shop_id, joint_id):
    return get_success_data(api_client.weld_out(shop_id, joint_id, WELD_LEAD),
                            200)


def pass_visual_inspection(shop_id, joint_id, cwi_user_id="cwi-1",
                           start=None, end=None, result_code="OK"):
    """Record an inline VT PASS (VT is in-house; vendor_id stays null)."""
    payload = create_vt_inspection_payload(
        scheduled_start_utc=start or DEFAULTS["VT_START"],
        scheduled_end_utc=end or DEFAULTS["VT_END"],
        result="PASS",
        result_code=result_code)
    return get_success_data(
        api_client.create_inspection(shop_id, joint_id, payload,
                                     make_cwi_headers(cwi_user_id)), 201)


def schedule_ndt(shop_id, joint_id, vendor_id, method="UT",
                 start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z",
                 cwi_user_id="cwi-1"):
    """Schedule a UT/RT inspection against a vendor (result left unset)."""
    payload = create_ndt_inspection_payload(
        vendor_id, method=method, scheduled_start_utc=start,
        scheduled_end_utc=end)
    return get_success_data(
        api_client.create_inspection(shop_id, joint_id, payload,
                                     make_cwi_headers(cwi_user_id)), 201)


def record_inspection_result(shop_id, inspection_id, result="PASS",
                             result_code="OK"):
    return get_success_data(
        api_client.record_inspection_result(
            shop_id, inspection_id,
            record_result_payload(result, result_code), CWI), 200)


def report_distortion(shop_id, weldment_id, joint_id,
                      measured_deviation_mm=5.0, tolerance_mm=2.0,
                      reporter_id="qi-1"):
    payload = create_distortion_report_payload(
        joint_id,
        measured_deviation_mm=measured_deviation_mm,
        tolerance_mm=tolerance_mm)
    return get_success_data(
        api_client.create_distortion_report(
            shop_id, weldment_id, payload,
            make_quality_inspector_headers(reporter_id)), 201)


def disposition_report(shop_id, report_id, disposition="USE_AS_IS"):
    return get_success_data(
        api_client.disposition_distortion_report(
            shop_id, report_id, {"disposition": disposition}, QC_MANAGER),
        200)


def sign_traveler(shop_id, weldment_id, step_code, headers):
    payload = create_traveler_sign_off_payload(step_code)
    return get_success_data(
        api_client.create_traveler_sign_off(shop_id, weldment_id, payload,
                                            headers), 201)


def declare_repair(shop_id, joint_id):
    return get_success_data(
        api_client.declare_repair(shop_id, joint_id, QC_MANAGER), 200)


def unfreeze_weldment(shop_id, weldment_id):
    return get_success_data(
        api_client.unfreeze_weldment(shop_id, weldment_id, QC_MANAGER), 200)


def ship_weldment(shop_id, weldment_id):
    """Ship with the weldment's current version (OCC, PRD §2.6)."""
    current = get_weldment(shop_id, weldment_id)
    return get_success_data(
        api_client.ship_weldment(
            shop_id, weldment_id,
            {"expected_weldment_version": current["version"]},
            SHIPPING_CLERK), 200)


# ---------------------------------------------------------------------------
# Tier 2/3: the fabrication workspace
# ---------------------------------------------------------------------------

def setup_fab_workspace(
        *,
        shop_name="Fab Shop",
        repair_rate_limit_pct=5,
        process="SMAW",
        base_metal_spec="A36",
        pqr_thickness=(3.0, 25.0),
        wps_thickness=(5.0, 20.0),
        qualified_at_utc="2026-08-01T00:00:00Z",
        pqr_reviewer_id="qc-reviewer-1",
        wps_approver_id="qc-approver-1",
        lot_received_kg=100.0,
        issued_kg=50.0,
        issue_lot=True,
        create_joint_count=1,
        joint_thickness_mm=10.0,
        ndt_methods=("VT",),
        vendor_methods=None,
        vendor_hourly_capacity=1,
        fixture_capacity=4,
        reserve=True,
        start_joints=True,
):
    """Full fabrication precondition chain:

    shop → welder → (optional NDT vendor) → approved PQR → approved WPS →
    QUALIFIED qualification → oven → lot → (optional open issue) →
    reserved fixture → shop order → weldment → joints (optionally started).

    Returns a dict of every created entity; `joints` is a list.
    """
    shop = create_shop(shop_name=shop_name,
                       repair_rate_limit_pct=repair_rate_limit_pct)
    shop_id = shop["id"]
    welder = create_welder(shop_id)
    vendor = None
    if vendor_methods is not None:
        vendor = create_ndt_vendor(
            shop_id,
            supported_methods=list(vendor_methods),
            hourly_capacity=vendor_hourly_capacity)
    pqr = create_and_approve_pqr(
        shop_id,
        reviewer_id=pqr_reviewer_id,
        process=process,
        base_metal_spec=base_metal_spec,
        thickness_range_min_mm=pqr_thickness[0],
        thickness_range_max_mm=pqr_thickness[1])
    wps = create_and_approve_wps(
        shop_id,
        pqr_id=pqr["id"],
        approver_id=wps_approver_id,
        process=process,
        base_metal_spec=base_metal_spec,
        thickness_min_mm=wps_thickness[0],
        thickness_max_mm=wps_thickness[1])
    qualification = create_qualification(
        shop_id, welder["id"], wps["id"], process=process,
        qualified_at_utc=qualified_at_utc)
    oven = create_oven(shop_id)
    lot = create_consumable_lot(shop_id, oven["id"], process=process,
                                received_kg=lot_received_kg)
    issue = None
    if issue_lot:
        issue = issue_consumables(shop_id, lot["id"], oven["id"],
                                  welder["id"], issued_kg=issued_kg)
    fixture = create_fixture(shop_id, capacity_weldments=fixture_capacity)
    if reserve:
        reserve_fixture(shop_id, fixture["id"])
    order = create_shop_order(shop_id)
    weldment = create_weldment(shop_id, order["id"], fixture["id"])
    joints = []
    for i in range(create_joint_count):
        joint = create_joint(
            shop_id, weldment["id"], wps["id"],
            joint_number=f"J-{i + 1}",
            base_metal_thickness_mm=joint_thickness_mm,
            required_ndt_methods=ndt_methods)
        if start_joints:
            joint = start_fabrication(shop_id, joint["id"])
        joints.append(joint)
    return {
        "shop": shop,
        "welder": welder,
        "vendor": vendor,
        "pqr": pqr,
        "wps": wps,
        "qualification": qualification,
        "oven": oven,
        "lot": lot,
        "issue": issue,
        "fixture": fixture,
        "order": order,
        "weldment": weldment,
        "joints": joints,
    }


def record_passes(ws, joint, count, is_repair=False, consumable_used_kg=1.0):
    """Record `count` passes on a joint from the workspace's welder/lot."""
    for _ in range(count):
        record_weld_pass(
            ws["shop"]["id"], joint["id"], ws["welder"]["id"],
            ws["qualification"]["id"], ws["lot"]["id"],
            consumable_used_kg=consumable_used_kg, is_repair=is_repair)


def record_normals_then_repairs(ws, joint, normal_count, repair_count):
    """Record normal passes first, repair passes last.

    The repair-rate gate trips the moment the rate reaches the shop limit,
    so repair passes must come last when accumulating a target rate — once
    the weldment enters REPAIR_REVIEW no further passes are accepted.
    """
    record_passes(ws, joint, normal_count, is_repair=False)
    record_passes(ws, joint, repair_count, is_repair=True)


def advance_joint_to_vt_passed(ws, joint_index=0, cwi_user_id="cwi-1"):
    """Weld one pass, weld out, then record an inline VT PASS."""
    shop_id = ws["shop"]["id"]
    joint = ws["joints"][joint_index]
    record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                     ws["qualification"]["id"], ws["lot"]["id"])
    weld_out(shop_id, joint["id"])
    pass_visual_inspection(shop_id, joint["id"], cwi_user_id=cwi_user_id)
    return get_joint(shop_id, joint["id"])


def setup_supersession_scenario(
        *,
        shop_name="Supersede Shop",
        qualified_at_utc="2026-01-01T00:00:00Z",
        pqr_reviewer_id="qc-reviewer-1",
        wps_approver_id="qc-approver-1",
        start_joint=False):
    """WPS rev 1 APPROVED + rev 2 DRAFT (same wps_number), a PENDING joint
    referencing rev 1, and a QUALIFIED qualification tied to rev 1 whose
    baseline is `qualified_at_utc` (default: old enough that any continuity
    re-evaluation at the startup clock lapses it). Approving rev 2 then
    drives the supersession cascade (PRD §3.1/§3.2).
    """
    shop = create_shop(shop_name=shop_name)
    shop_id = shop["id"]
    welder = create_welder(shop_id)
    pqr = create_and_approve_pqr(shop_id, reviewer_id=pqr_reviewer_id,
                                 pqr_number="PQR-1")
    wps_r1 = create_wps(shop_id, pqr["id"], wps_number="WPS-1", revision=1)
    wps_r1 = approve_wps(shop_id, wps_r1["id"], wps_approver_id)
    wps_r2 = create_wps(shop_id, pqr["id"], wps_number="WPS-1", revision=2)
    qualification = create_qualification(
        shop_id, welder["id"], wps_r1["id"], qualified_at_utc=qualified_at_utc)
    fixture = create_fixture(shop_id)
    reserve_fixture(shop_id, fixture["id"])
    order = create_shop_order(shop_id)
    weldment = create_weldment(shop_id, order["id"], fixture["id"])
    joint = create_joint(shop_id, weldment["id"], wps_r1["id"])
    if start_joint:
        joint = start_fabrication(shop_id, joint["id"])
    return {
        "shop": shop,
        "welder": welder,
        "pqr": pqr,
        "wps_r1": wps_r1,
        "wps_r2": wps_r2,
        "qualification": qualification,
        "fixture": fixture,
        "order": order,
        "weldment": weldment,
        "joint": joint,
    }


# ---------------------------------------------------------------------------
# Tier 4/5: threshold targeting and terminal postures
# ---------------------------------------------------------------------------

def setup_weldment_at_repair_rate(*, normal_count, repair_count,
                                  repair_rate_limit_pct=5,
                                  shop_name="Rate Shop"):
    """Weldment with exactly `normal_count` normal + `repair_count` repair
    passes on one joint (normals first so the gate never blocks buildup).

    Returns (ws, joint). Callers then re-read the weldment to observe the
    derived posture.
    """
    ws = setup_fab_workspace(
        shop_name=shop_name,
        repair_rate_limit_pct=repair_rate_limit_pct,
        lot_received_kg=200.0,
        issued_kg=100.0)
    joint = ws["joints"][0]
    record_normals_then_repairs(ws, joint, normal_count, repair_count)
    return ws, joint


def setup_vt_passed_workspace(*, ndt_methods=("VT", "UT"),
                              vendor_methods=("UT",),
                              vendor_hourly_capacity=1,
                              joint_count=1,
                              cwi_user_id="cwi-1",
                              **overrides):
    """Workspace whose joints are advanced to VT_PASSED (or NDT_PASSED when
    the joint requires nothing beyond VT). Returns ws with refreshed joints.
    """
    ws = setup_fab_workspace(
        ndt_methods=ndt_methods,
        vendor_methods=vendor_methods,
        vendor_hourly_capacity=vendor_hourly_capacity,
        create_joint_count=joint_count,
        **overrides)
    refreshed = []
    for i in range(joint_count):
        refreshed.append(
            advance_joint_to_vt_passed(ws, i, cwi_user_id=cwi_user_id))
    ws["joints"] = refreshed
    return ws


def setup_frozen_weldment(**overrides):
    """Drive a weldment to FROZEN:

    joint VT_PASSED with UT scheduled → clock past the UT slot → two
    distortion reports filed and dispositioned USE_AS_IS (posture returns to
    OPEN) → UT result FAIL (joint NDT_FAILED; freeze criteria recomputed with
    distortion_count == 2 → FROZEN).

    The reports are dispositioned before the FAIL so the weldment is
    unambiguously OPEN at the moment the freeze criteria are recomputed.
    Returns ws plus keys: ut_inspection, reports.
    """
    ws = setup_vt_passed_workspace(
        ndt_methods=("VT", "UT"),
        vendor_methods=("UT",),
        vendor_hourly_capacity=4,
        **overrides)
    shop_id = ws["shop"]["id"]
    joint = ws["joints"][0]
    ut = schedule_ndt(shop_id, joint["id"], ws["vendor"]["id"], method="UT",
                      start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z")
    set_clock("2026-08-03T10:00:01Z")
    weldment_id = ws["weldment"]["id"]
    dr1 = report_distortion(shop_id, weldment_id, joint["id"],
                            measured_deviation_mm=5.0, tolerance_mm=2.0)
    dr2 = report_distortion(shop_id, weldment_id, joint["id"],
                            measured_deviation_mm=4.0, tolerance_mm=2.0)
    disposition_report(shop_id, dr1["id"], "USE_AS_IS")
    disposition_report(shop_id, dr2["id"], "USE_AS_IS")
    record_inspection_result(shop_id, ut["id"], result="FAIL",
                             result_code="CRACK")
    ws["ut_inspection"] = ut
    ws["reports"] = (dr1, dr2)
    ws["joints"] = [get_joint(shop_id, joint["id"])]
    ws["weldment"] = get_weldment(shop_id, weldment_id)
    return ws
