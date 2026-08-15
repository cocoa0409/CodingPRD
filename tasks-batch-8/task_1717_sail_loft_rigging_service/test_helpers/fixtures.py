"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a fresh server). Setup calls use the lenient
get_success_data validator so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Identity threading: Customer is entity-backed, so every ownership-gated call
(approve, request-revision, confirm-delivery, warranty claim, confirm-return)
uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOTH_PRICE_PER_SQM_CENTS,
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_INSTALL_DATE,
)
from .test_users import TEST_USERS, make_customer_headers

MGR = TEST_USERS["loft_manager_headers"]
SAIL = TEST_USERS["sailmaker_headers"]
MEAS = TEST_USERS["measurer_headers"]
RIG = TEST_USERS["rigger_headers"]


def _setup_ok(resp, what: str) -> dict:
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed ({what}): {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation / transitions
# ---------------------------------------------------------------------------

def create_customer(full_name="Test Customer", email=None, credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS) -> dict:
    payload = {"full_name": full_name, "email": email or f"{full_name.replace(' ', '.').lower()}@example.com",
               "credit_limit_cents": credit_limit_cents}
    return _setup_ok(api_client.create_customer(payload, MGR), "create_customer")


def create_boat(customer_id, boat_name="Test Boat", hull_length_m=10.0, racing_class="NONE",
                standing_rigging_install_date=DEFAULT_INSTALL_DATE,
                running_rigging_hours_accumulated=0) -> dict:
    payload = {
        "boat_name": boat_name,
        "hull_length_m": hull_length_m,
        "racing_class": racing_class,
        "standing_rigging_install_date": standing_rigging_install_date,
        "running_rigging_hours_accumulated": running_rigging_hours_accumulated,
    }
    return _setup_ok(api_client.create_boat(customer_id, payload, MGR), "create_boat")


def get_boat(boat_id) -> dict:
    return _setup_ok(api_client.get_boat(boat_id, MGR), "get_boat")


def get_customer(customer_id) -> dict:
    return _setup_ok(api_client.get_customer(customer_id, MGR), "get_customer")


def get_work_order(work_order_id) -> dict:
    return _setup_ok(api_client.get_work_order(work_order_id, MGR), "get_work_order")


def get_sail_design(design_id) -> dict:
    return _setup_ok(api_client.get_sail_design(design_id, MGR), "get_sail_design")


def get_production_job(job_id) -> dict:
    return _setup_ok(api_client.get_production_job(job_id, MGR), "get_production_job")


def get_cloth_bolt(bolt_id) -> dict:
    return _setup_ok(api_client.get_cloth_bolt(bolt_id, MGR), "get_cloth_bolt")


def get_rigging_inspection(inspection_id) -> dict:
    return _setup_ok(api_client.get_rigging_inspection(inspection_id, RIG), "get_rigging_inspection")


def get_mast_service_event(event_id) -> dict:
    return _setup_ok(api_client.get_mast_service_event(event_id, RIG), "get_mast_service_event")


def get_storage_contract(contract_id) -> dict:
    return _setup_ok(api_client.get_storage_contract(contract_id, MGR), "get_storage_contract")


def create_measurement_sheet(boat_id, i_height_m=12.0, j_base_m=4.0, p_main_m=15.0, e_main_m=5.0) -> dict:
    payload = {"i_height_m": i_height_m, "j_base_m": j_base_m, "p_main_m": p_main_m, "e_main_m": e_main_m}
    return _setup_ok(api_client.create_measurement_sheet(boat_id, payload, MEAS), "create_measurement_sheet")


def freeze_measurement_sheet(boat_id, sheet_id) -> dict:
    return _setup_ok(api_client.freeze_measurement_sheet(boat_id, sheet_id, MEAS), "freeze_measurement_sheet")


def create_frozen_sheet(boat_id, **dims) -> dict:
    sheet = create_measurement_sheet(boat_id, **dims)
    return freeze_measurement_sheet(boat_id, sheet["id"])


def create_sail_design(boat_id, measurement_sheet_id, cloth_tier="CRUISE", reinforcement_level=1,
                       option_codes=None) -> dict:
    """Create a DRAFT design revision. Reads the boat first to obtain the
    expected_boat_version concurrency token (PRD §2.7)."""
    boat_version = get_boat(boat_id)["version"]
    payload = {
        "measurement_sheet_id": measurement_sheet_id,
        "cloth_tier": cloth_tier,
        "reinforcement_level": reinforcement_level,
        "option_codes": list(option_codes or []),
        "expected_boat_version": boat_version,
    }
    return _setup_ok(api_client.create_sail_design(boat_id, payload, SAIL), "create_sail_design")


def submit_design(boat_id, design_id) -> dict:
    return _setup_ok(api_client.submit_sail_design(boat_id, design_id, SAIL), "submit_design")


def approve_design(boat_id, design_id, customer_id) -> dict:
    return _setup_ok(
        api_client.approve_sail_design(boat_id, design_id, make_customer_headers(customer_id)),
        "approve_design",
    )


def create_cloth_bolt(bolt_code=None, cloth_tier="CRUISE", total_sqm=500.0, price_per_sqm_cents=None) -> dict:
    payload = {
        "bolt_code": bolt_code or f"BOLT-{cloth_tier}-1",
        "cloth_tier": cloth_tier,
        "total_sqm": total_sqm,
        "price_per_sqm_cents": price_per_sqm_cents
        if price_per_sqm_cents is not None
        else CLOTH_PRICE_PER_SQM_CENTS[cloth_tier],
    }
    return _setup_ok(api_client.create_cloth_bolt(payload, MGR), "create_cloth_bolt")


def create_work_order(customer_id, boat_id, order_kind="NEW_SAIL", sail_design_id=None,
                      warranty_flag=None) -> dict:
    payload = {"customer_id": customer_id, "boat_id": boat_id, "order_kind": order_kind}
    if sail_design_id is not None:
        payload["sail_design_id"] = sail_design_id
    if warranty_flag is not None:
        payload["warranty_flag"] = warranty_flag
    return _setup_ok(api_client.create_work_order(payload, MGR), "create_work_order")


def lock_work_order(work_order_id) -> dict:
    return _setup_ok(api_client.lock_design(work_order_id, MGR), "lock_work_order")


def schedule_production_job(work_order_id, bay_code="BAY_A", scheduled_start_date="2026-09-01",
                            scheduled_end_date="2026-09-05") -> dict:
    payload = {
        "bay_code": bay_code,
        "scheduled_start_date": scheduled_start_date,
        "scheduled_end_date": scheduled_end_date,
    }
    return _setup_ok(api_client.create_production_job(work_order_id, payload, SAIL), "schedule_production_job")


def start_cutting(work_order_id, job_id) -> dict:
    return _setup_ok(api_client.start_cutting(work_order_id, job_id, SAIL), "start_cutting")


def advance_job(work_order_id, job_id) -> dict:
    return _setup_ok(api_client.advance_job(work_order_id, job_id, SAIL), "advance_job")


def qc_pass_job(work_order_id, job_id) -> dict:
    return _setup_ok(api_client.qc_pass(work_order_id, job_id, SAIL), "qc_pass_job")


def drive_job_to_finishing(work_order_id, job_id) -> dict:
    """SCHEDULED -> CUTTING -> SEAMING -> FINISHING. Returns the FINISHING job."""
    start_cutting(work_order_id, job_id)
    advance_job(work_order_id, job_id)
    return advance_job(work_order_id, job_id)


def drive_job_to_qc_passed(work_order_id, job_id) -> dict:
    """SCHEDULED -> ... -> QC_PASSED. Returns the QC_PASSED job."""
    drive_job_to_finishing(work_order_id, job_id)
    return qc_pass_job(work_order_id, job_id)


def create_mast_service_event(boat_id, service_kind="TUNE", slot_start_utc="2026-09-01T08:00:00Z",
                              slot_end_utc="2026-09-01T12:00:00Z") -> dict:
    payload = {"service_kind": service_kind, "slot_start_utc": slot_start_utc, "slot_end_utc": slot_end_utc}
    return _setup_ok(api_client.create_mast_service_event(boat_id, payload, RIG), "create_mast_service_event")


def create_rigging_inspection(boat_id, rigging_scope="FULL") -> dict:
    """Schedule an inspection. Reads the boat first for the expected_boat_version
    concurrency token (PRD §2.7)."""
    boat_version = get_boat(boat_id)["version"]
    payload = {"rigging_scope": rigging_scope, "expected_boat_version": boat_version}
    return _setup_ok(api_client.create_rigging_inspection(boat_id, payload, RIG), "create_rigging_inspection")


def report_inspection(boat_id, inspection_id, verdict) -> dict:
    return _setup_ok(api_client.report_inspection(boat_id, inspection_id, {"verdict": verdict}, RIG),
                     "report_inspection")


def close_inspection(boat_id, inspection_id) -> dict:
    return _setup_ok(api_client.close_inspection(boat_id, inspection_id, RIG), "close_inspection")


def create_storage_contract(boat_id, season_code="WINTER_2026", wash_item_codes=None) -> dict:
    payload = {"season_code": season_code, "wash_item_codes": list(wash_item_codes or [])}
    return _setup_ok(api_client.create_storage_contract(boat_id, payload, MGR), "create_storage_contract")


def create_class_certificate(boat_id, measurement_sheet_id, racing_class) -> dict:
    payload = {"measurement_sheet_id": measurement_sheet_id, "racing_class": racing_class}
    return _setup_ok(api_client.create_class_certificate(boat_id, payload, MEAS), "create_class_certificate")


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy composites
# ---------------------------------------------------------------------------

def setup_customer_with_boat(credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS, **boat_kw) -> dict:
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    boat = create_boat(customer["id"], **boat_kw)
    return {"customer": customer, "boat": boat}


def setup_boat_with_frozen_sheet(**kw) -> dict:
    """Customer + boat + FROZEN measurement sheet. dims/ hull/ class via kw."""
    dims = {k: kw.pop(k) for k in ("i_height_m", "j_base_m", "p_main_m", "e_main_m") if k in kw}
    credit = kw.pop("credit_limit_cents", DEFAULT_CREDIT_LIMIT_CENTS)
    ctx = setup_customer_with_boat(credit_limit_cents=credit, **kw)
    ctx["sheet"] = create_frozen_sheet(ctx["boat"]["id"], **dims)
    return ctx


def setup_approved_design(credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS, cloth_tier="CRUISE",
                          reinforcement_level=1, option_codes=None, submit_only=False, **kw) -> dict:
    """Customer + boat + FROZEN sheet + design driven to APPROVED (or SUBMITTED
    when submit_only=True). Returns a context dict."""
    ctx = setup_boat_with_frozen_sheet(credit_limit_cents=credit_limit_cents, **kw)
    design = create_sail_design(
        ctx["boat"]["id"], ctx["sheet"]["id"],
        cloth_tier=cloth_tier, reinforcement_level=reinforcement_level,
        option_codes=option_codes,
    )
    ctx["design"] = submit_design(ctx["boat"]["id"], design["id"])
    if not submit_only:
        ctx["design"] = approve_design(ctx["boat"]["id"], design["id"], ctx["customer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — work-order lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_open_work_order_with_bolt(cloth_total_sqm=500.0, bolt_price_per_sqm_cents=None, **design_kw) -> dict:
    """Approved design + cloth bolt for its tier + OPEN work order pinning the design."""
    ctx = setup_approved_design(**design_kw)
    tier = ctx["design"]["cloth_tier"]
    ctx["bolt"] = create_cloth_bolt(
        cloth_tier=tier, total_sqm=cloth_total_sqm,
        price_per_sqm_cents=bolt_price_per_sqm_cents,
    )
    ctx["work_order"] = create_work_order(
        ctx["customer"]["id"], ctx["boat"]["id"],
        order_kind="NEW_SAIL", sail_design_id=ctx["design"]["id"],
    )
    return ctx


def setup_locked_work_order(**kw) -> dict:
    """Full pipeline through lock-design: quoted_total_cents computed (PRD §3.4)."""
    ctx = setup_open_work_order_with_bolt(**kw)
    ctx["work_order"] = lock_work_order(ctx["work_order"]["id"])
    return ctx


def setup_order_with_qc_passed_job(bay_code="BAY_A", start="2026-09-01", end="2026-09-05", **kw) -> dict:
    """Locked order + one production job driven to QC_PASSED; the parent bubbles
    to READY_FOR_FIT_CHECK (PRD §3.4)."""
    ctx = setup_locked_work_order(**kw)
    job = schedule_production_job(ctx["work_order"]["id"], bay_code=bay_code,
                                  scheduled_start_date=start, scheduled_end_date=end)
    ctx["job"] = drive_job_to_qc_passed(ctx["work_order"]["id"], job["id"])
    ctx["work_order"] = get_work_order(ctx["work_order"]["id"])
    return ctx


def setup_delivered_work_order(fitted_option_codes=None, **kw) -> dict:
    """Full pipeline through confirm-delivery: order DELIVERED, final invoice
    computed, customer balance debited (PRD §3.5)."""
    ctx = setup_order_with_qc_passed_job(**kw)
    ctx["work_order"] = _setup_ok(
        api_client.confirm_delivery(
            ctx["work_order"]["id"],
            {"fitted_option_codes": list(fitted_option_codes or [])},
            make_customer_headers(ctx["customer"]["id"]),
        ),
        "confirm_delivery",
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — rigging safety chain composites
# ---------------------------------------------------------------------------

def setup_boat_with_reported_fail(boat_kw=None, scope="STANDING", mast_event=True,
                                  mast_slot=("2026-09-01T08:00:00Z", "2026-09-01T12:00:00Z")) -> dict:
    """Customer + boat (+ BOOKED mast event) + inspection REPORTED with FAIL:
    boat is OUT_OF_SERVICE and the BOOKED event is on RIGGING_HOLD (PRD §3.6)."""
    ctx = setup_customer_with_boat(**(boat_kw or {}))
    if mast_event:
        ctx["mast_event"] = create_mast_service_event(
            ctx["boat"]["id"], service_kind="UNSTEP",
            slot_start_utc=mast_slot[0], slot_end_utc=mast_slot[1],
        )
    ctx["inspection"] = create_rigging_inspection(ctx["boat"]["id"], rigging_scope=scope)
    ctx["inspection"] = report_inspection(ctx["boat"]["id"], ctx["inspection"]["id"], "FAIL")
    return ctx


def setup_fail_closed_by_replacement(**kw) -> dict:
    """FAIL chain resolved: a passing replacement REPORTED, then the FAIL closed;
    the hold releases (PRD §3.6)."""
    ctx = setup_boat_with_reported_fail(**kw)
    ctx["replacement"] = create_rigging_inspection(ctx["boat"]["id"], rigging_scope=ctx["inspection"]["rigging_scope"])
    ctx["replacement"] = report_inspection(ctx["boat"]["id"], ctx["replacement"]["id"], "PASS")
    ctx["inspection"] = close_inspection(ctx["boat"]["id"], ctx["inspection"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — storage program composites
# ---------------------------------------------------------------------------

def setup_storage_contract(hull_length_m=12.0, wash_item_codes=None, **boat_kw) -> dict:
    ctx = setup_customer_with_boat(hull_length_m=hull_length_m, **boat_kw)
    ctx["contract"] = create_storage_contract(ctx["boat"]["id"], wash_item_codes=wash_item_codes)
    return ctx


def drive_storage_contract_to_out_for_delivery(ctx) -> dict:
    """ENROLLED -> RECEIVED -> WASHED -> STORED -> OUT_FOR_DELIVERY."""
    boat_id = ctx["boat"]["id"]
    cid = ctx["contract"]["id"]
    contract = _setup_ok(api_client.receive_storage_contract(boat_id, cid, MGR), "receive")
    contract = _setup_ok(api_client.complete_wash(boat_id, cid, MGR), "complete_wash")
    contract = _setup_ok(api_client.rack_store(boat_id, cid, MGR), "rack_store")
    contract = _setup_ok(api_client.stage_delivery(boat_id, cid, MGR), "stage_delivery")
    ctx["contract"] = contract
    return ctx


def setup_returned_storage_contract(hull_length_m=12.0, wash_item_codes=None, **boat_kw) -> dict:
    """Full storage lifecycle through confirm-return: contract RETURNED and the
    quoted fee billed to the customer's balance (PRD §3.7)."""
    ctx = setup_storage_contract(hull_length_m=hull_length_m, wash_item_codes=wash_item_codes, **boat_kw)
    drive_storage_contract_to_out_for_delivery(ctx)
    ctx["contract"] = _setup_ok(
        api_client.confirm_return(ctx["boat"]["id"], ctx["contract"]["id"],
                                  make_customer_headers(ctx["customer"]["id"])),
        "confirm_return",
    )
    return ctx
