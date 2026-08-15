"""Routes: test bays, pressure tests, certificates, exchange units, field jobs."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import DB, CLOCK, make_entity, touch, serialize, sorted_entities, parse_iso8601
from middleware import (
    validate_body, require_auth, require_role, parse_pagination, get_filter,
    get_int_filter, ALL_ROLES,
)
from errors import (
    err_invalid_request, err_invalid_state, err_already_terminal,
    err_stale_version, err_bay_overlap, err_tech_overlap, err_window_past,
    err_pressure_hold, err_segregation, err_certificate_exists,
    err_exchange_not_fulfilled, err_crimp,
)
from helpers import (
    get_or_404, check_customer_owns, WO_TERMINAL, PRESSURE_TEST_TERMINAL,
    CERTIFICATE_TERMINAL, EXCHANGE_TERMINAL, FIELD_JOB_TERMINAL,
)
from calc import (
    shop_config, required_hold_psi, exchange_core_credit, field_service_price, dec,
)
from response import success_object, success_list

bp = Blueprint("quality", __name__)

PRESSURE_CLASSES = ["CLASS_3000", "CLASS_5000"]
CORE_CONDITIONS = ["GOOD", "WORN", "DAMAGED", "SCRAP"]
CORE_COMPLETENESS = ["COMPLETE", "MISSING_PARTS"]
HOSE_TYPES = ["WIRE_BRAID_2SN", "SPIRAL_4SH", "THERMOPLASTIC"]


def _wo_terminal_guard(wo):
    if wo["status"] in WO_TERMINAL:
        raise err_already_terminal("Work order is in terminal state %s" % wo["status"])


# ---------------------------------------------------------------------------
# Test bays
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/test-bays")
def create_test_bay():
    body = validate_body([("name", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    bay = make_entity({"name": body["name"]})
    DB.test_bays[bay["id"]] = bay
    return success_object(serialize(bay), status=201)


@bp.get("/fluid-power/test-bays/<bay_id>")
def get_test_bay(bay_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.test_bays, bay_id)))


# ---------------------------------------------------------------------------
# Pressure tests
# ---------------------------------------------------------------------------

def _bay_window_blocked(bay_id, start, end, buffer_minutes):
    """Closed booking intervals extended by the mandatory buffer on both sides;
    any intersection (inclusive) collides. SCHEDULED and PASSED-pending
    bookings block; FAILED/VOIDED/CANCELLED do not."""
    buf = timedelta(minutes=buffer_minutes)
    new_lo, new_hi = start - buf, end + buf
    for test in DB.pressure_tests.values():
        if test["test_bay_id"] != bay_id:
            continue
        if test["status"] not in ("SCHEDULED", "PASSED"):
            continue
        old_lo = parse_iso8601(test["window_start"]) - buf
        old_hi = parse_iso8601(test["window_end"]) + buf
        if new_lo <= old_hi and old_lo <= new_hi:
            return True
    return False


@bp.post("/fluid-power/pressure-tests")
def create_pressure_test():
    body = validate_body([
        ("work_order_id", ("string", True, False)),
        ("test_bay_id", ("string", True, False)),
        ("window_start", ("datetime", True, False)),
        ("window_end", ("datetime", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["QualityInspector"])
    wo = get_or_404(DB.work_orders, body["work_order_id"])
    get_or_404(DB.test_bays, body["test_bay_id"])
    _wo_terminal_guard(wo)
    if wo["status"] == "ASSEMBLED":
        pass
    elif wo["status"] == "TEST_PENDING":
        # re-entry: allowed only when no SCHEDULED test is outstanding
        for test in DB.pressure_tests.values():
            if test["work_order_id"] == wo["id"] and test["status"] == "SCHEDULED":
                raise err_invalid_state("A SCHEDULED test already exists for the work order")
    else:
        raise err_invalid_state("pressure-test creation requires ASSEMBLED or TEST_PENDING")
    cfg = shop_config()
    start = parse_iso8601(body["window_start"])
    end = parse_iso8601(body["window_end"])
    if _bay_window_blocked(body["test_bay_id"], start, end, cfg["bay_buffer_minutes"]):
        raise err_bay_overlap()
    cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
    test = make_entity({
        "work_order_id": wo["id"],
        "test_bay_id": body["test_bay_id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "required_hold_psi": required_hold_psi(cfg, cylinder["pressure_class"]),
        "measured_hold_psi": None,
        "duration_min": None,
        "leakage_drops": None,
        "status": "SCHEDULED",
    })
    DB.pressure_tests[test["id"]] = test
    if wo["status"] == "ASSEMBLED":
        wo["status"] = "TEST_PENDING"
        touch(wo)
    return success_object(serialize(test), status=201)


@bp.get("/fluid-power/pressure-tests/<test_id>")
def get_pressure_test(test_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.pressure_tests, test_id)))


@bp.get("/fluid-power/pressure-tests")
def list_pressure_tests():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    work_order_id = get_filter("work_order_id")
    test_bay_id = get_filter("test_bay_id")
    status = get_filter("status")
    items = sorted_entities(DB.pressure_tests)
    if work_order_id is not None:
        items = [t for t in items if t["work_order_id"] == work_order_id]
    if test_bay_id is not None:
        items = [t for t in items if t["test_bay_id"] == test_bay_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(t) for t in page], limit, offset, total)


@bp.post("/fluid-power/pressure-tests/<test_id>/record-result")
def record_result(test_id):
    body = validate_body([
        ("measured_hold_psi", ("integer", True, False)),
        ("duration_min", ("integer", True, False)),
        ("leakage_drops", ("integer", True, False)),
        ("passed", ("boolean", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["QualityInspector"])
    test = get_or_404(DB.pressure_tests, test_id)
    if test["status"] in PRESSURE_TEST_TERMINAL:
        raise err_already_terminal("Pressure test is in terminal state %s" % test["status"])
    if test["status"] != "SCHEDULED":
        raise err_invalid_state("Pressure test is not SCHEDULED")
    cfg = shop_config()
    if body["passed"]:
        # safety gate: pass claim consistency (boundary inclusive on pressure
        # and duration; leakage must be exactly zero)
        if not (body["measured_hold_psi"] >= test["required_hold_psi"]
                and body["duration_min"] >= cfg["test_hold_min_minutes"]
                and body["leakage_drops"] == 0):
            raise err_pressure_hold()
    test["measured_hold_psi"] = body["measured_hold_psi"]
    test["duration_min"] = body["duration_min"]
    test["leakage_drops"] = body["leakage_drops"]
    wo = get_or_404(DB.work_orders, test["work_order_id"])
    if body["passed"]:
        test["status"] = "PASSED"
        touch(test)
        wo["status"] = "TEST_PASSED"
        touch(wo)
    else:
        # rework loop: back to IN_REPAIR; cleanliness flag reset, codes retained
        test["status"] = "FAILED"
        touch(test)
        wo["status"] = "IN_REPAIR"
        wo["cleanliness_passed"] = False
        touch(wo)
    return success_object(serialize(test))


@bp.post("/fluid-power/pressure-tests/<test_id>/cancel")
def cancel_pressure_test(test_id):
    actor = require_auth()
    require_role(actor, ["QualityInspector", "ShopAdmin"])
    test = get_or_404(DB.pressure_tests, test_id)
    if test["status"] in PRESSURE_TEST_TERMINAL:
        raise err_already_terminal("Pressure test is in terminal state %s" % test["status"])
    if test["status"] != "SCHEDULED":
        raise err_invalid_state("Pressure test is not SCHEDULED")
    test["status"] = "CANCELLED"
    touch(test)
    return success_object(serialize(test))


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/certificates")
def create_certificate():
    body = validate_body([("work_order_id", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["QualityInspector"])
    wo = get_or_404(DB.work_orders, body["work_order_id"])
    _wo_terminal_guard(wo)
    # PRD 3.7 names ERR_SEGREGATION_OF_DUTIES and ERR_CERTIFICATE_EXISTS for the
    # second-issuance scenario, where the work order has already left TEST_PASSED
    # (issuance cascaded it to CERTIFIED). Evaluating the from-state check first
    # would make both named errors unreachable, so the safety gate (priority 9)
    # and the uniqueness constraint (priority 11) run before it — the same
    # ordering call as teardown-create's report-existence check.
    if actor.user_id == wo["assigned_technician_id"]:
        raise err_segregation()
    for cert in DB.certificates.values():
        if cert["work_order_id"] == wo["id"] and cert["status"] == "ISSUED":
            raise err_certificate_exists()
    if wo["status"] != "TEST_PASSED":
        raise err_invalid_state("Work order is not TEST_PASSED")
    passed_tests = [t for t in DB.pressure_tests.values()
                    if t["work_order_id"] == wo["id"] and t["status"] == "PASSED"]
    passed_tests.sort(key=lambda t: (t["created_at"], t["_seq"]))
    latest = passed_tests[-1]
    cert = make_entity({
        "work_order_id": wo["id"],
        "pressure_test_id": latest["id"],
        "issued_by": actor.user_id,
        "status": "ISSUED",
        "revoke_reason": None,
    })
    DB.certificates[cert["id"]] = cert
    wo["status"] = "CERTIFIED"
    touch(wo)
    return success_object(serialize(cert), status=201)


@bp.get("/fluid-power/certificates/<cert_id>")
def get_certificate(cert_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.certificates, cert_id)))


@bp.get("/fluid-power/certificates")
def list_certificates():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    work_order_id = get_filter("work_order_id")
    pressure_test_id = get_filter("pressure_test_id")
    status = get_filter("status")
    items = sorted_entities(DB.certificates)
    if work_order_id is not None:
        items = [c for c in items if c["work_order_id"] == work_order_id]
    if pressure_test_id is not None:
        items = [c for c in items if c["pressure_test_id"] == pressure_test_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.post("/fluid-power/certificates/<cert_id>/revoke")
def revoke_certificate(cert_id):
    body = validate_body([("reason", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["QualityInspector"])
    cert = get_or_404(DB.certificates, cert_id)
    if cert["status"] in CERTIFICATE_TERMINAL:
        raise err_already_terminal("Certificate is REVOKED")
    if cert["status"] != "ISSUED":
        raise err_invalid_state("Certificate is not ISSUED")
    cert["status"] = "REVOKED"
    cert["revoke_reason"] = body["reason"]
    touch(cert)
    wo = get_or_404(DB.work_orders, cert["work_order_id"])
    wo["status"] = "TEST_PENDING"
    touch(wo)
    test = DB.pressure_tests.get(cert["pressure_test_id"])
    if test is not None and test["status"] == "PASSED":
        test["status"] = "VOIDED"
        touch(test)
    return success_object(serialize(cert))


# ---------------------------------------------------------------------------
# Exchange units
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/exchange-units")
def create_exchange_unit():
    body = validate_body([
        ("bore_mm", ("integer", True, False)),
        ("stroke_mm", ("integer", True, False)),
        ("rod_diameter_mm", ("integer", True, False)),
        ("pressure_class", ("enum", True, False, PRESSURE_CLASSES)),
        ("unit_price_cents", ("integer", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    unit = make_entity({
        "bore_mm": body["bore_mm"],
        "stroke_mm": body["stroke_mm"],
        "rod_diameter_mm": body["rod_diameter_mm"],
        "pressure_class": body["pressure_class"],
        "unit_price_cents": body["unit_price_cents"],
        "status": "IN_POOL",
        "work_order_id": None,
        "provisional_credit_cents": None,
        "condition": None,
        "completeness": None,
        "final_credit_cents": None,
    })
    DB.exchange_units[unit["id"]] = unit
    return success_object(serialize(unit), status=201)


@bp.get("/fluid-power/exchange-units/<unit_id>")
def get_exchange_unit(unit_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.exchange_units, unit_id)))


@bp.get("/fluid-power/exchange-units")
def list_exchange_units():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    status = get_filter("status")
    work_order_id = get_filter("work_order_id")
    bore_mm = get_int_filter("bore_mm")
    items = sorted_entities(DB.exchange_units)
    if status is not None:
        items = [u for u in items if u["status"] == status]
    if work_order_id is not None:
        items = [u for u in items if u.get("work_order_id") == work_order_id]
    if bore_mm is not None:
        items = [u for u in items if u["bore_mm"] == bore_mm]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(u) for u in page], limit, offset, total)


@bp.post("/fluid-power/exchange-units/<unit_id>/release")
def release_exchange_unit(unit_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    unit = get_or_404(DB.exchange_units, unit_id)
    if unit["status"] in EXCHANGE_TERMINAL:
        raise err_already_terminal("Exchange unit is SETTLED")
    if unit["status"] != "RESERVED":
        raise err_invalid_state("Exchange unit is not RESERVED")
    unit["status"] = "IN_POOL"
    unit["work_order_id"] = None
    unit["provisional_credit_cents"] = None
    touch(unit)
    return success_object(serialize(unit))


@bp.post("/fluid-power/exchange-units/<unit_id>/fulfill")
def fulfill_exchange_unit(unit_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    unit = get_or_404(DB.exchange_units, unit_id)
    if unit["status"] in EXCHANGE_TERMINAL:
        raise err_already_terminal("Exchange unit is SETTLED")
    if unit["status"] != "RESERVED":
        raise err_invalid_state("Exchange unit is not RESERVED")
    wo = DB.work_orders.get(unit.get("work_order_id") or "")
    if wo is None or wo["status"] != "EXCHANGE_SELECTED":
        raise err_invalid_state("Linked work order is not EXCHANGE_SELECTED for this unit")
    cfg = shop_config()
    # provisional variant assumes the returned core grades GOOD + COMPLETE
    unit["provisional_credit_cents"] = exchange_core_credit(
        cfg, unit["unit_price_cents"], unit["bore_mm"], "GOOD", "COMPLETE")
    unit["status"] = "FULFILLED"
    touch(unit)
    cylinder = DB.cylinders.get(wo["cylinder_id"])
    if cylinder is not None:
        cylinder["status"] = "EXCHANGED"
        touch(cylinder)
    wo["status"] = "EXCHANGE_FULFILLED"
    touch(wo)
    return success_object(serialize(unit))


@bp.post("/fluid-power/exchange-units/<unit_id>/receive-core")
def receive_core(unit_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    unit = get_or_404(DB.exchange_units, unit_id)
    if unit["status"] in EXCHANGE_TERMINAL:
        raise err_already_terminal("Exchange unit is SETTLED")
    if unit["status"] != "FULFILLED":
        raise err_exchange_not_fulfilled()
    unit["status"] = "CORE_RECEIVED"
    touch(unit)
    return success_object(serialize(unit))


@bp.post("/fluid-power/exchange-units/<unit_id>/evaluate-core")
def evaluate_core(unit_id):
    body = validate_body([
        ("condition", ("enum", True, False, CORE_CONDITIONS)),
        ("completeness", ("enum", True, False, CORE_COMPLETENESS)),
    ])
    actor = require_auth()
    require_role(actor, ["QualityInspector"])
    unit = get_or_404(DB.exchange_units, unit_id)
    if unit["status"] in EXCHANGE_TERMINAL:
        raise err_already_terminal("Exchange unit is SETTLED")
    if unit["status"] != "CORE_RECEIVED":
        raise err_invalid_state("Exchange unit is not CORE_RECEIVED")
    cfg = shop_config()
    unit["condition"] = body["condition"]
    unit["completeness"] = body["completeness"]
    unit["final_credit_cents"] = exchange_core_credit(
        cfg, unit["unit_price_cents"], unit["bore_mm"],
        body["condition"], body["completeness"])
    unit["status"] = "SETTLED"
    touch(unit)
    return success_object(serialize(unit))


# ---------------------------------------------------------------------------
# Field service jobs
# ---------------------------------------------------------------------------

def _validate_assemblies(raw):
    if not isinstance(raw, list):
        raise err_invalid_request("assemblies must be an array")
    normalized = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise err_invalid_request("assemblies[%d] must be an object" % i)
        hose_type = item.get("hose_type")
        if not isinstance(hose_type, str) or hose_type not in HOSE_TYPES:
            raise err_invalid_request("assemblies[%d].hose_type must be one of %s" % (i, HOSE_TYPES))
        length_m = item.get("length_m")
        if not ((isinstance(length_m, int) or isinstance(length_m, float))
                and not isinstance(length_m, bool)):
            raise err_invalid_request("assemblies[%d].length_m must be a number" % i)
        fitting = item.get("fitting_price_cents")
        if not (isinstance(fitting, int) and not isinstance(fitting, bool)):
            raise err_invalid_request("assemblies[%d].fitting_price_cents must be an integer" % i)
        spec = item.get("crimp_spec_mm")
        if not ((isinstance(spec, int) or isinstance(spec, float)) and not isinstance(spec, bool)):
            raise err_invalid_request("assemblies[%d].crimp_spec_mm must be a number" % i)
        normalized.append({
            "hose_type": hose_type,
            "length_m": length_m,
            "fitting_price_cents": fitting,
            "crimp_spec_mm": spec,
            "crimp_measured_mm": None,
            "assembly_result": "PENDING",
        })
    return normalized


@bp.post("/fluid-power/field-service-jobs")
def create_field_job():
    body = validate_body([
        ("customer_id", ("string", True, False)),
        ("site_address", ("string", True, False)),
        ("distance_km", ("integer", True, False)),
        ("assemblies", ("array", True, False)),
    ])
    assemblies = _validate_assemblies(body["assemblies"])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor", "Customer"])
    check_customer_owns(actor, body["customer_id"])
    get_or_404(DB.customers, body["customer_id"])
    cfg = shop_config()
    provisional = field_service_price(cfg, assemblies, body["distance_km"], False)
    job = make_entity({
        "customer_id": body["customer_id"],
        "site_address": body["site_address"],
        "distance_km": body["distance_km"],
        "assemblies": assemblies,
        "technician_id": None,
        "window_start": None,
        "window_end": None,
        "emergency_callout": False,
        "provisional_price_cents": provisional,
        "final_price_cents": None,
        "status": "REQUESTED",
    })
    DB.field_service_jobs[job["id"]] = job
    return success_object(serialize(job), status=201)


@bp.get("/fluid-power/field-service-jobs/<job_id>")
def get_field_job(job_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.field_service_jobs, job_id)))


@bp.get("/fluid-power/field-service-jobs")
def list_field_jobs():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    customer_id = get_filter("customer_id")
    technician_id = get_filter("technician_id")
    status = get_filter("status")
    items = sorted_entities(DB.field_service_jobs)
    if customer_id is not None:
        items = [j for j in items if j["customer_id"] == customer_id]
    if technician_id is not None:
        items = [j for j in items if j["technician_id"] == technician_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(j) for j in page], limit, offset, total)


def _tech_window_blocked(technician_id, start, end, exclude_job_id=None):
    """Half-open [start, end) overlap against the technician's other
    SCHEDULED/DISPATCHED jobs; windows touching at an endpoint do not collide."""
    for job in DB.field_service_jobs.values():
        if job["technician_id"] != technician_id:
            continue
        if exclude_job_id is not None and job["id"] == exclude_job_id:
            continue
        if job["status"] not in ("SCHEDULED", "DISPATCHED"):
            continue
        other_start = parse_iso8601(job["window_start"])
        other_end = parse_iso8601(job["window_end"])
        if start < other_end and other_start < end:
            return True
    return False


@bp.post("/fluid-power/field-service-jobs/<job_id>/schedule")
def schedule_field_job(job_id):
    body = validate_body([
        ("technician_id", ("string", True, False)),
        ("window_start", ("datetime", True, False)),
        ("window_end", ("datetime", True, False)),
        ("expected_technician_version", ("integer", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    job = get_or_404(DB.field_service_jobs, job_id)
    tech = get_or_404(DB.technicians, body["technician_id"])
    # OCC (priority 6) precedes state checks (priority 7)
    if body["expected_technician_version"] != tech["version"]:
        raise err_stale_version()
    if job["status"] in FIELD_JOB_TERMINAL:
        raise err_already_terminal("Field service job is in terminal state %s" % job["status"])
    if job["status"] != "REQUESTED":
        raise err_invalid_state("Field service job is not REQUESTED")
    if not tech["active"] or "FIELD_SERVICE" not in tech["skills"]:
        raise err_invalid_state("Technician is not active or lacks FIELD_SERVICE")
    start = parse_iso8601(body["window_start"])
    end = parse_iso8601(body["window_end"])
    if start < CLOCK.now():
        raise err_window_past()
    if _tech_window_blocked(tech["id"], start, end):
        raise err_tech_overlap()
    cfg = shop_config()
    created_at = parse_iso8601(job["created_at"])
    gap = start - created_at
    job["emergency_callout"] = gap <= timedelta(hours=cfg["emergency_callout_window_hours"])
    job["technician_id"] = tech["id"]
    job["window_start"] = body["window_start"]
    job["window_end"] = body["window_end"]
    job["status"] = "SCHEDULED"
    touch(job)
    touch(tech)  # scheduling increments the technician's version by one
    return success_object(serialize(job))


@bp.post("/fluid-power/field-service-jobs/<job_id>/dispatch")
def dispatch_field_job(job_id):
    actor = require_auth()
    require_role(actor, ["Technician"])
    job = get_or_404(DB.field_service_jobs, job_id)
    if actor.user_id != job["technician_id"]:
        from errors import err_not_owner
        raise err_not_owner("Acting technician is not the job's technician")
    if job["status"] in FIELD_JOB_TERMINAL:
        raise err_already_terminal("Field service job is in terminal state %s" % job["status"])
    if job["status"] != "SCHEDULED":
        raise err_invalid_state("Field service job is not SCHEDULED")
    job["status"] = "DISPATCHED"
    touch(job)
    return success_object(serialize(job))


@bp.post("/fluid-power/field-service-jobs/<job_id>/complete")
def complete_field_job(job_id):
    body = validate_body([("crimp_measurements", ("array", True, False))])
    actor = require_auth()
    require_role(actor, ["Technician"])
    job = get_or_404(DB.field_service_jobs, job_id)
    if actor.user_id != job["technician_id"]:
        from errors import err_not_owner
        raise err_not_owner("Acting technician is not the job's technician")
    if job["status"] in FIELD_JOB_TERMINAL:
        raise err_already_terminal("Field service job is in terminal state %s" % job["status"])
    if job["status"] != "DISPATCHED":
        raise err_invalid_state("Field service job is not DISPATCHED")
    # apply measurements: positional numbers, or {assembly_index, crimp_measured_mm}
    measurements = body["crimp_measurements"]
    assemblies = job["assemblies"]
    positional = 0
    for element in measurements:
        if (isinstance(element, int) or isinstance(element, float)) and not isinstance(element, bool):
            if positional >= len(assemblies):
                raise err_invalid_request("More crimp measurements than assemblies")
            assemblies[positional]["crimp_measured_mm"] = element
            positional += 1
        elif isinstance(element, dict):
            idx = element.get("assembly_index", element.get("index"))
            value = element.get("crimp_measured_mm", element.get("value"))
            if not (isinstance(idx, int) and not isinstance(idx, bool)) or idx < 0 or idx >= len(assemblies):
                raise err_invalid_request("crimp_measurements entry has an invalid assembly index")
            if not ((isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)):
                raise err_invalid_request("crimp_measurements entry has an invalid value")
            assemblies[idx]["crimp_measured_mm"] = value
        else:
            raise err_invalid_request("crimp_measurements entries must be numbers or objects")
    cfg = shop_config()
    tol = dec(cfg["crimp_tolerance_mm"])
    all_pass = True
    for assembly in assemblies:
        measured = assembly["crimp_measured_mm"]
        within = (measured is not None
                  and abs(dec(measured) - dec(assembly["crimp_spec_mm"])) <= tol)
        assembly["assembly_result"] = "PASS" if within else "FAIL"
        if not within:
            all_pass = False
    if not all_pass:
        # measurements persist, out-of-tolerance assemblies marked FAIL,
        # the job remains DISPATCHED
        touch(job)
        raise err_crimp()
    cfg = shop_config()
    job["final_price_cents"] = field_service_price(
        cfg, assemblies, job["distance_km"], job["emergency_callout"])
    job["status"] = "COMPLETED"
    touch(job)
    return success_object(serialize(job))


@bp.post("/fluid-power/field-service-jobs/<job_id>/cancel")
def cancel_field_job(job_id):
    body = validate_body([("reason", ("string", False, True))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor", "Customer"])
    job = get_or_404(DB.field_service_jobs, job_id)
    check_customer_owns(actor, job["customer_id"])
    if job["status"] in FIELD_JOB_TERMINAL:
        raise err_already_terminal("Field service job is in terminal state %s" % job["status"])
    if job["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err_invalid_state("Field service job cannot be cancelled from %s" % job["status"])
    job["status"] = "CANCELLED"
    touch(job)
    return success_object(serialize(job))
