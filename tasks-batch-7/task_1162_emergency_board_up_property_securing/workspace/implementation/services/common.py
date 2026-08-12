"""Shared helpers: entity serialization, OCC, cross-entity lookups."""
import math
from decimal import Decimal, ROUND_HALF_UP
import db
from db import format_ts, iso_now, parse_ts
from errors import err


def round_half_up_int(value):
    """Round a Decimal or float to integer cents using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def touch(rec):
    """Refresh updated_at and bump version."""
    rec["updated_at"] = iso_now()
    rec["version"] = rec.get("version", 1) + 1


def base_record(rec_id=None):
    now = iso_now()
    return {
        "id": rec_id or db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


# ---------------- Serializers ----------------

def serialize_market(m):
    return dict(m)


def reliability(sub):
    completed = sub.get("completed_job_count", 0)
    breached = sub.get("breached_job_count", 0)
    expired = sub.get("expired_offer_count", 0)
    denom_l = completed + breached
    if denom_l == 0:
        lenient = 1.0000
    else:
        lenient = round_half_up_4dp(Decimal(completed) / Decimal(denom_l))
    denom_s = completed + breached + expired
    if denom_s == 0:
        strict = 1.0000
    else:
        strict = round_half_up_4dp(Decimal(completed) / Decimal(denom_s))
    return lenient, strict


def serialize_subcontractor(s):
    out = dict(s)
    l, st = reliability(s)
    out["reliability_score_lenient"] = l
    out["reliability_score_strict"] = st
    return out


def serialize_coverage(c):
    return dict(c)


def serialize_customer(c):
    return dict(c)


def serialize_property(p):
    return dict(p)


def serialize_job(j):
    return dict(j)


def serialize_assignment(a):
    return dict(a)


def serialize_safety_assessment(s):
    return dict(s)


def serialize_scope_item(s):
    return dict(s)


def serialize_temporary_service(s):
    return dict(s)


def serialize_patrol_visit(v):
    return dict(v)


def serialize_permit_case(p):
    return dict(p)


def serialize_document_package(p):
    return dict(p)


def serialize_invoice(i):
    return dict(i)


# ---------------- Lookups ----------------

def get_or_404(store, rec_id, name="Resource"):
    rec = store.get(rec_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found: %s" % (name, rec_id))
    return rec


def find_job_assignments(job_id):
    return [a for a in db.assignments.values() if a["job_id"] == job_id]


def find_job_scope_items(job_id):
    return [s for s in db.scope_items.values() if s["job_id"] == job_id]


def find_job_services(job_id):
    return [s for s in db.temporary_services.values() if s["job_id"] == job_id]


def find_job_permit_cases(job_id):
    return [p for p in db.permit_cases.values() if p["job_id"] == job_id]


def find_job_document_package(job_id):
    for p in db.document_packages.values():
        if p["job_id"] == job_id:
            return p
    return None


def find_job_invoices(job_id):
    return [i for i in db.invoices.values() if i["job_id"] == job_id]


def find_accepted_or_arrived_assignment(job_id):
    for a in db.assignments.values():
        if a["job_id"] == job_id and a["status"] in ("ACCEPTED", "ARRIVED"):
            return a
    return None


def find_current_assignment(job_id):
    """The job's currently accepted assignment (PRD §2.1): the latest offer that
    was accepted — its status may since have advanced to ARRIVED or COMPLETED,
    but it remains the job's assignee source (e.g. the §3.6 re-secure cycle is
    closed by the same crew after the first securing completed the assignment)."""
    current = None
    for a in db.assignments.values():
        if a["job_id"] == job_id and a["status"] in ("ACCEPTED", "ARRIVED", "COMPLETED"):
            if current is None or a["offer_seq"] > current["offer_seq"]:
                current = a
    return current


def recompute_active_assignment_count(sub_id):
    count = sum(
        1 for a in db.assignments.values()
        if a["subcontractor_id"] == sub_id and a["status"] in ("ACCEPTED", "ARRIVED")
    )
    sub = db.subcontractors.get(sub_id)
    if sub is not None:
        sub["active_assignment_count"] = count
        touch(sub)
    return count


def recompute_job_total_planned_sheets(job_id):
    total = 0
    for s in db.scope_items.values():
        if s["job_id"] == job_id and s["kind"] == "BOARD" and s["status"] in ("PLANNED", "INSTALLED"):
            qty = s.get("planned_qty") or 0
            total += int(qty)
    job = db.jobs.get(job_id)
    if job is not None:
        job["total_planned_sheets"] = total
    return total


def recompute_required_photo_count(job_id):
    pkg = find_job_document_package(job_id)
    if pkg is None:
        return None
    installed = sum(
        1 for s in db.scope_items.values()
        if s["job_id"] == job_id and s["status"] == "INSTALLED"
    )
    pkg["required_photo_count"] = 2 * installed
    touch(pkg)
    return pkg


def maybe_complete_package(pkg):
    if pkg["status"] != "INCOMPLETE":
        return
    if (
        pkg.get("authorization_signed")
        and pkg.get("measurement_sheet_recorded")
        and pkg.get("photo_count", 0) >= pkg.get("required_photo_count", 0)
    ):
        pkg["status"] = "COMPLETE"
        touch(pkg)


# ---------------- Scope quantity calculation ----------------

def compute_scope_qty(kind, measurements, wind_zone):
    """Return (qty, unit). Measurements is a dict with kind-appropriate fields."""
    if kind == "BOARD":
        opening_count = measurements.get("opening_count")
        width_in = measurements.get("width_in")
        height_in = measurements.get("height_in")
        door_count = measurements.get("door_count") or 0
        for v, n in ((opening_count, "opening_count"), (width_in, "width_in"), (height_in, "height_in")):
            if v is None or not isinstance(v, (int, float)) or v <= 0:
                raise err("ERR_INVALID_MEASUREMENT", "BOARD requires positive %s" % n)
        area_sqft_total = Decimal(str(opening_count)) * Decimal(str(width_in)) * Decimal(str(height_in)) / Decimal(144)
        base_sheets = math.ceil(area_sqft_total / Decimal(32))
        sheets = base_sheets + int(door_count)
        if wind_zone == "HIGH":
            sheets = sheets * 2
        if opening_count > 0:
            sheets = max(sheets, 1)
        return sheets, "SHEETS"
    elif kind == "TARP":
        length_ft = measurements.get("length_ft")
        width_ft = measurements.get("width_ft")
        for v, n in ((length_ft, "length_ft"), (width_ft, "width_ft")):
            if v is None or not isinstance(v, (int, float)) or v <= 0:
                raise err("ERR_INVALID_MEASUREMENT", "TARP requires positive %s" % n)
        qty = math.ceil(Decimal(str(length_ft)) * Decimal(str(width_ft)) * Decimal("1.25"))
        return qty, "SQFT"
    elif kind == "FENCE":
        linear_ft = measurements.get("linear_ft")
        if linear_ft is None or not isinstance(linear_ft, (int, float)) or linear_ft <= 0:
            raise err("ERR_INVALID_MEASUREMENT", "FENCE requires positive linear_ft")
        return linear_ft, "LINEAR_FT"
    else:
        raise err("ERR_INVALID_ENUM", "Unknown scope kind: %r" % kind)


PRIORITY_MULTIPLIER = {
    "P1": Decimal("1.50"),
    "P2": Decimal("1.25"),
    "P3": Decimal("1.00"),
}

HAZARD_WEIGHTS = {
    "COLLAPSE": 45,
    "ELECTRICAL": 25,
    "GAS": 20,
    "WATER": 15,
    "ASBESTOS": 10,
}


def compute_hazard_score(hazards):
    score = 0
    for h in hazards:
        score += HAZARD_WEIGHTS.get(h, 0)
    return min(100, score)


def hazard_level(score):
    if score >= 70:
        return "HIGH"
    if score >= 30:
        return "MODERATE"
    return "LOW"
