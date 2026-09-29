"""Reference-network endpoints: logical clock, mills, mill contracts, carriers,
insurance certificates, safety findings, trucks, crews and haul routes."""

from flask import Blueprint, request

import derive
from core import (
    ACCESS_CLASSES,
    AXLE_CONFIGS,
    COVERAGE_TYPES,
    CREW_TYPES,
    D,
    GRADES,
    PERMIT_CLASSES,
    RECEIVING_STATUSES,
    ROUTE_STATUSES,
    SEVERITIES,
    SPECIES,
    body,
    clock,
    created,
    db,
    endpoint,
    fail,
    iso_instant,
    new_record,
    ok,
    ordered,
    paginated,
    parse_instant,
    req_date,
    req_enum,
    req_int,
    req_num,
    req_str,
    touch,
)

bp = Blueprint("reference", __name__)

ALL_ROLES = (
    "PlatformAdmin",
    "OperationsManager",
    "MillScaler",
    "SafetyOfficer",
    "SettlementAccountant",
    "HaulContractor",
)


def state_code(payload, name):
    value = req_str(payload, name, min_len=2, max_len=2)
    if not value.isupper() or not value.isalpha():
        fail("ERR_VALIDATION", "%s must be exactly two upper-case letters" % name)
    return value


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformAdmin")
def set_clock(caller):
    payload = body()
    if "to_iso8601" not in payload or payload["to_iso8601"] is None:
        fail("ERR_VALIDATION", "to_iso8601 is required")
    parsed = parse_instant(payload["to_iso8601"])
    if parsed is None:
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant")
    clock.now = parsed
    # Moving the clock re-derives every certificate status and every carrier's
    # rolling-180-day compliance score; both are derived on read.
    return ok({"current_utc": clock.iso()})


# ---------------------------------------------------------------------------
# Mill
# ---------------------------------------------------------------------------
@bp.route("/mills", methods=["POST"])
@endpoint("PlatformAdmin")
def create_mill(caller):
    payload = body()
    name = req_str(payload, "name", 1, 120)
    code = state_code(payload, "state_code")
    receiving = req_enum(payload, "receiving_status", RECEIVING_STATUSES, required=False, default="OPEN")
    rec = new_record()
    rec.update({"name": name, "state_code": code, "receiving_status": receiving})
    db.mills[rec["id"]] = rec
    return created(derive.mill_json(rec))


@bp.route("/mills/<id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_mill(caller, id):
    rec = db.mills.get(id)
    if rec is None:
        fail("ERR_MILL_NOT_FOUND", "no mill %s" % id)
    return ok(derive.mill_json(rec))


@bp.route("/mills/<id>", methods=["PATCH"])
@endpoint("PlatformAdmin", "MillScaler")
def patch_mill(caller, id):
    payload = body()
    receiving = req_enum(payload, "receiving_status", RECEIVING_STATUSES)
    rec = db.mills.get(id)
    if rec is None:
        fail("ERR_MILL_NOT_FOUND", "no mill %s" % id)
    if caller.role == "MillScaler" and caller.user_id != rec["id"]:
        fail("ERR_SCALER_MILL_MISMATCH", "scaler may only act on its own mill")
    rec["receiving_status"] = receiving
    touch(rec)
    return ok(derive.mill_json(rec))


# ---------------------------------------------------------------------------
# MillContract
# ---------------------------------------------------------------------------
@bp.route("/mill-contracts", methods=["POST"])
@endpoint("PlatformAdmin")
def create_mill_contract(caller):
    payload = body()
    mill_id = req_str(payload, "mill_id")
    species = req_enum(payload, "species", SPECIES)
    grade = req_enum(payload, "grade", GRADES)
    quota_tons = req_num(payload, "quota_tons", minimum=0, exclusive_min=True, max_places=2)
    base_rate = req_int(payload, "base_rate_cents_per_ton", minimum=1)
    period_start = req_date(payload, "period_start")
    period_end = req_date(payload, "period_end")
    overrun = req_num(
        payload, "overrun_tolerance_pct", minimum=0, maximum="0.25", required=False, default=D("0.05")
    )
    if period_end < period_start:
        fail("ERR_VALIDATION", "period_end must be on or after period_start")
    mill = db.mills.get(mill_id)
    if mill is None:
        fail("ERR_MILL_NOT_FOUND", "no mill %s" % mill_id)
    rec = new_record()
    rec.update(
        {
            "mill_id": mill_id,
            "species": species,
            "grade": grade,
            "quota_tons": quota_tons,
            "overrun_tolerance_pct": overrun,
            "base_rate_cents_per_ton": base_rate,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "status": "OPEN",
        }
    )
    db.mill_contracts[rec["id"]] = rec
    return created(derive.mill_contract_json(rec))


@bp.route("/mill-contracts/<id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_mill_contract(caller, id):
    rec = db.mill_contracts.get(id)
    if rec is None:
        fail("ERR_MILL_CONTRACT_NOT_FOUND", "no mill contract %s" % id)
    return ok(derive.mill_contract_json(rec))


@bp.route("/mill-contracts", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "MillScaler", "SafetyOfficer", "SettlementAccountant")
def list_mill_contracts(caller):
    records = ordered(list(db.mill_contracts.values()))
    for key in ("mill_id", "species", "grade", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.mill_contract_json)


@bp.route("/mill-contracts/<id>", methods=["PATCH"])
@endpoint("PlatformAdmin")
def patch_mill_contract(caller, id):
    payload = body()
    # FILLED is derived and may never be requested -- caught on the schema rung.
    status = req_enum(payload, "status", ("OPEN", "SUSPENDED", "CLOSED"))
    req_str(payload, "reason", min_len=0, max_len=500, required=False)
    rec = db.mill_contracts.get(id)
    if rec is None:
        fail("ERR_MILL_CONTRACT_NOT_FOUND", "no mill contract %s" % id)
    current = rec["status"]
    legal = {
        "SUSPENDED": ("OPEN", "FILLED"),
        "OPEN": ("SUSPENDED",),
        "CLOSED": ("OPEN", "FILLED", "SUSPENDED"),
    }
    if current not in legal[status]:
        fail("ERR_INVALID_MILL_CONTRACT_STATE", "cannot move contract %s -> %s" % (current, status))
    rec["status"] = status
    touch(rec)
    if status == "OPEN":
        # Resuming recomputes available_tons and may immediately re-fill.
        derive.sync_contract_status(rec)
    return ok(derive.mill_contract_json(rec))


# ---------------------------------------------------------------------------
# HaulContractor
# ---------------------------------------------------------------------------
@bp.route("/haul-contractors", methods=["POST"])
@endpoint("PlatformAdmin")
def create_haul_contractor(caller):
    payload = body()
    name = req_str(payload, "name", 1, 120)
    dot_number = req_str(payload, "dot_number", 1, 32)
    base_state = state_code(payload, "base_state_code")
    for existing in db.haul_contractors.values():
        if existing["dot_number"] == dot_number:
            fail("ERR_VALIDATION", "dot_number must be unique across carriers")
    rec = new_record()
    rec.update(
        {
            "name": name,
            "dot_number": dot_number,
            "base_state_code": base_state,
            "compliance_status": "COMPLIANT",
        }
    )
    db.haul_contractors[rec["id"]] = rec
    return created(derive.haul_contractor_json(rec))


@bp.route("/haul-contractors/<id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_haul_contractor(caller, id):
    rec = db.haul_contractors.get(id)
    if rec is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    return ok(derive.haul_contractor_json(rec))


@bp.route("/haul-contractors/<id>/insurance-certificates", methods=["POST"])
@endpoint("PlatformAdmin", "HaulContractor")
def create_certificate(caller, id):
    payload = body()
    coverage = req_enum(payload, "coverage_type", COVERAGE_TYPES)
    effective_on = req_date(payload, "effective_on")
    expires_on = req_date(payload, "expires_on")
    limit_cents = req_int(payload, "limit_cents", minimum=1)
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    if caller.role == "HaulContractor" and caller.user_id != contractor["id"]:
        fail("ERR_CONTRACTOR_NOT_OWNER", "carrier may only file its own certificates")
    rec = new_record()
    rec.update(
        {
            "haul_contractor_id": contractor["id"],
            "coverage_type": coverage,
            "effective_on": effective_on.isoformat(),
            "expires_on": expires_on.isoformat(),
            "limit_cents": limit_cents,
            "revoked_at": None,
        }
    )
    db.insurance_certificates[rec["id"]] = rec
    # Filing recomputes the score and advances the carrier's pinned version.
    touch(contractor)
    return created(derive.insurance_certificate_json(rec))


@bp.route("/haul-contractors/<id>/insurance-certificates", methods=["GET"])
@endpoint("PlatformAdmin", "SafetyOfficer", "SettlementAccountant", "HaulContractor")
def list_certificates(caller, id):
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    records = derive.certs_of_contractor(id)
    coverage = request.args.get("coverage_type")
    if coverage is not None:
        records = [r for r in records if r["coverage_type"] == coverage]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if derive.certificate_status(r) == status]
    return paginated(records, derive.insurance_certificate_json)


@bp.route("/insurance-certificates/<id>/revoke", methods=["POST"])
@endpoint("SafetyOfficer")
def revoke_certificate(caller, id):
    payload = body()
    req_str(payload, "reason", 1, 500)
    rec = db.insurance_certificates.get(id)
    if rec is None:
        fail("ERR_INSURANCE_CERTIFICATE_NOT_FOUND", "no insurance certificate %s" % id)
    rec["revoked_at"] = clock.iso()
    touch(rec)
    contractor = db.haul_contractors.get(rec["haul_contractor_id"])
    if contractor is not None:
        uncovered = derive.missing_coverage_count(contractor["id"]) > 0
        if uncovered and contractor["compliance_status"] != "SUSPENDED":
            derive.suspend_contractor(contractor)
        else:
            touch(contractor)
    return ok(derive.insurance_certificate_json(rec))


@bp.route("/haul-contractors/<id>/safety-findings", methods=["POST"])
@endpoint("SafetyOfficer")
def create_safety_finding(caller, id):
    payload = body()
    severity = req_enum(payload, "severity", SEVERITIES)
    points = req_int(payload, "points", minimum=0, maximum=100)
    occurred_on = req_date(payload, "occurred_on")
    note = req_str(payload, "note", min_len=0, max_len=500, required=False, default=None)
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    rec = new_record(with_common=False)
    rec.update(
        {
            "haul_contractor_id": contractor["id"],
            "severity": severity,
            "points": points,
            "occurred_on": occurred_on.isoformat(),
            "note": note,
        }
    )
    db.safety_findings[rec["id"]] = rec
    if severity == "CRITICAL" and contractor["compliance_status"] in ("COMPLIANT", "WARNED"):
        derive.suspend_contractor(contractor)
    elif severity == "MAJOR" and contractor["compliance_status"] == "COMPLIANT":
        contractor["compliance_status"] = "WARNED"
        touch(contractor)
    else:
        touch(contractor)
    return created(derive.safety_finding_json(rec))


@bp.route("/haul-contractors/<id>/safety-findings", methods=["GET"])
@endpoint("PlatformAdmin", "SafetyOfficer", "SettlementAccountant", "HaulContractor")
def list_safety_findings(caller, id):
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    records = ordered([f for f in db.safety_findings.values() if f["haul_contractor_id"] == id])
    severity = request.args.get("severity")
    if severity is not None:
        records = [r for r in records if r["severity"] == severity]
    return paginated(records, derive.safety_finding_json)


@bp.route("/haul-contractors/<id>/suspend", methods=["POST"])
@endpoint("SafetyOfficer")
def suspend_haul_contractor(caller, id):
    payload = body()
    req_str(payload, "reason", 1, 500)
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    derive.suspend_contractor(contractor)
    return ok(derive.haul_contractor_json(contractor))


@bp.route("/haul-contractors/<id>/reinstate", methods=["POST"])
@endpoint("SafetyOfficer")
def reinstate_haul_contractor(caller, id):
    payload = body()
    req_str(payload, "note", min_len=0, max_len=500, required=False)
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    if derive.missing_coverage_count(contractor["id"]) > 0:
        fail(
            "ERR_INSURANCE_COVERAGE_INCOMPLETE",
            "all three required coverages must have an ACTIVE certificate",
        )
    contractor["compliance_status"] = "COMPLIANT"
    touch(contractor)
    for truck in derive.trucks_of_contractor(contractor["id"]):
        touch(truck)
    return ok(derive.haul_contractor_json(contractor))


@bp.route("/haul-contractors/<id>/trucks", methods=["POST"])
@endpoint("PlatformAdmin", "HaulContractor")
def create_truck(caller, id):
    payload = body()
    unit_number = req_str(payload, "unit_number", 1, 32)
    axle_config = req_enum(payload, "axle_config", AXLE_CONFIGS)
    tare = req_int(payload, "tare_weight_lbs", minimum=10000, maximum=60000)
    permit_class = req_enum(payload, "permit_class", PERMIT_CLASSES)
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    if caller.role == "HaulContractor" and caller.user_id != contractor["id"]:
        fail("ERR_CONTRACTOR_NOT_OWNER", "carrier may only add trucks to its own fleet")
    for existing in db.trucks.values():
        if existing["haul_contractor_id"] == contractor["id"] and existing["unit_number"] == unit_number:
            fail("ERR_VALIDATION", "unit_number must be unique within the carrier")
    rec = new_record()
    rec.update(
        {
            "haul_contractor_id": contractor["id"],
            "unit_number": unit_number,
            "axle_config": axle_config,
            "tare_weight_lbs": tare,
            "permit_class": permit_class,
        }
    )
    db.trucks[rec["id"]] = rec
    return created(derive.truck_json(rec))


@bp.route("/haul-contractors/<id>/trucks", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SafetyOfficer", "HaulContractor")
def list_trucks(caller, id):
    contractor = db.haul_contractors.get(id)
    if contractor is None:
        fail("ERR_HAUL_CONTRACTOR_NOT_FOUND", "no haul contractor %s" % id)
    records = derive.trucks_of_contractor(id)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if derive.truck_status(r) == status]
    return paginated(records, derive.truck_json)


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
@endpoint("PlatformAdmin")
def create_crew(caller):
    payload = body()
    name = req_str(payload, "name", 1, 120)
    crew_type = req_enum(payload, "crew_type", CREW_TYPES)
    pieces = req_int(payload, "equipment_pieces", minimum=1, maximum=24)
    daily_rate = req_int(payload, "daily_rate_cents", minimum=1)
    rec = new_record()
    rec.update(
        {
            "name": name,
            "crew_type": crew_type,
            "equipment_pieces": pieces,
            "daily_rate_cents": daily_rate,
            "status": "IDLE",
        }
    )
    db.crews[rec["id"]] = rec
    return created(derive.crew_json(rec))


@bp.route("/crews/<id>", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SafetyOfficer")
def get_crew(caller, id):
    rec = db.crews.get(id)
    if rec is None:
        fail("ERR_CREW_NOT_FOUND", "no crew %s" % id)
    return ok(derive.crew_json(rec))


# ---------------------------------------------------------------------------
# HaulRoute
# ---------------------------------------------------------------------------
@bp.route("/haul-routes", methods=["POST"])
@endpoint("PlatformAdmin")
def create_haul_route(caller):
    payload = body()
    tract_id = req_str(payload, "tract_id")
    mill_id = req_str(payload, "mill_id")
    distance = req_int(payload, "distance_miles", minimum=1, maximum=400)
    legal_weight = req_int(payload, "legal_gross_weight_lbs", minimum=40000, maximum=120000)
    permit_required = req_enum(payload, "permit_class_required", PERMIT_CLASSES)
    frost_start = req_date(payload, "frost_law_start_on", required=False)
    frost_end = req_date(payload, "frost_law_end_on", required=False)
    status = req_enum(payload, "status", ROUTE_STATUSES, required=False, default="OPEN")
    tract = db.tracts.get(tract_id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % tract_id)
    mill = db.mills.get(mill_id)
    if mill is None:
        fail("ERR_MILL_NOT_FOUND", "no mill %s" % mill_id)
    rec = new_record()
    rec.update(
        {
            "tract_id": tract_id,
            "mill_id": mill_id,
            "distance_miles": distance,
            "legal_gross_weight_lbs": legal_weight,
            "permit_class_required": permit_required,
            "frost_law_start_on": frost_start.isoformat() if frost_start else None,
            "frost_law_end_on": frost_end.isoformat() if frost_end else None,
            "status": status,
        }
    )
    db.haul_routes[rec["id"]] = rec
    return created(derive.haul_route_json(rec))


@bp.route("/haul-routes/<id>", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "MillScaler", "SafetyOfficer", "HaulContractor")
def get_haul_route(caller, id):
    rec = db.haul_routes.get(id)
    if rec is None:
        fail("ERR_HAUL_ROUTE_NOT_FOUND", "no haul route %s" % id)
    return ok(derive.haul_route_json(rec))


@bp.route("/haul-routes", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "MillScaler", "SafetyOfficer", "HaulContractor")
def list_haul_routes(caller):
    records = ordered(list(db.haul_routes.values()))
    for key in ("tract_id", "mill_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.haul_route_json)
