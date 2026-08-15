"""Shared helpers: input validation, serialization, pagination, derived fields."""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import invalid_request

HAZARD_CLASSES = ("FLAMMABLE", "OXIDIZER", "CORROSIVE", "TOXIC",
                  "CONTROLLED_SUBSTANCE", "SELECT_AGENT")
QUANTITY_UNITS = ("GAL", "L", "KG", "LB")
AREA_TYPES = ("SAA", "CAA")
WORKER_ROLES = ("PI", "RESEARCHER", "STUDENT")
SEVERITIES_INCIDENT = ("LOW", "MEDIUM", "HIGH")
FINDING_SEVERITIES = ("MAJOR", "MINOR")
MATERIAL_TYPES = ("CONTROLLED_SUBSTANCE", "SELECT_AGENT")

# Calculation constants (scaffold §1.3)
PERMIT_THRESHOLDS_GAL = {
    "FLAMMABLE": Decimal("10.0"),
    "OXIDIZER": Decimal("10.0"),
    "CORROSIVE": Decimal("5.0"),
    "TOXIC": Decimal("1.0"),
    "CONTROLLED_SUBSTANCE": Decimal("0.0"),
    "SELECT_AGENT": Decimal("0.0"),
}
DISPOSAL_RATE_PER_GAL = {
    "FLAMMABLE": Decimal("12.50"),
    "OXIDIZER": Decimal("11.00"),
    "CORROSIVE": Decimal("9.75"),
    "TOXIC": Decimal("21.20"),
    "CONTROLLED_SUBSTANCE": Decimal("45.00"),
    "SELECT_AGENT": Decimal("60.00"),
}
BASE_FEE = Decimal("75.00")
CA_DUE_DAYS = {"MAJOR": 14, "MINOR": 30}
ACCUMULATION_MAX_DAYS = 365
DOCK_BUFFER_MINUTES = 30

TWO_PLACES = Decimal("0.01")


def round2(value):
    """Round a Decimal to 2 places, round-half-up."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Convert a JSON number to Decimal without float artifacts."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return None
    return None


# -----------------------------------------------------------------------------
# Input validation helpers (priority 2 -> ERR_INVALID_REQUEST)
# -----------------------------------------------------------------------------

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def require_string(body, field):
    value = body.get(field)
    if not isinstance(value, str) or value == "":
        raise invalid_request(f"Field {field} must be a non-empty string")
    return value


def require_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return value


def optional_enum(body, field, allowed, default=None):
    value = body.get(field, default)
    if value not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return value


def require_positive_number(body, field):
    """quantity_value must be a number > 0."""
    raw = body.get(field)
    value = to_decimal(raw)
    if value is None or value <= 0:
        raise invalid_request(f"Field {field} must be a number greater than zero")
    return value


def require_positive_int(body, field):
    """capacity_containers must be an integer > 0."""
    raw = body.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise invalid_request(f"Field {field} must be an integer greater than zero")
    return raw


def require_datetime(body, field):
    raw = body.get(field)
    parsed = db.parse_iso(raw)
    if parsed is None:
        raise invalid_request(f"Field {field} must be a valid ISO 8601 datetime")
    return parsed


def optional_bool(body, field, default=False):
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise invalid_request(f"Field {field} must be a boolean")
    return value


# -----------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0.
# Out-of-range limit/offset are treated as invalid requests.
# -----------------------------------------------------------------------------

def parse_pagination():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (insertion seq tie-break), then window."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


# -----------------------------------------------------------------------------
# Derived fields / serializers. Each serializer computes the entity's computed
# fields fresh from the source data at read time.
# -----------------------------------------------------------------------------

def _hazard_totals(lab_id):
    physical = {h: Decimal("0") for h in HAZARD_CLASSES}
    regulatory = {h: Decimal("0") for h in HAZARD_CLASSES}
    for c in db.containers.values():
        if c["lab_id"] != lab_id:
            continue
        if c["state"] == "IN_USE":
            physical[c["hazard_class"]] += c["quantity_value"]
            regulatory[c["hazard_class"]] += c["quantity_value"]
        elif c["state"] == "WASTE_TAGGED":
            regulatory[c["hazard_class"]] += c["quantity_value"]
    physical = {h: round2(v) for h, v in physical.items()}
    regulatory = {h: round2(v) for h, v in regulatory.items()}
    return physical, regulatory


def _permit_report_required(regulatory):
    for h in HAZARD_CLASSES:
        total = regulatory[h]
        if total > 0 and total >= PERMIT_THRESHOLDS_GAL[h]:
            return True
    return False


def compute_posture(lab):
    """lab_posture_derivation (PRD §2.6): ordered first-match-wins."""
    now = db.now()
    lab_id = lab["id"]
    if lab["status"] == "DECOMMISSIONED":
        return "FROZEN"
    cas = [ca for ca in db.corrective_actions.values() if ca["lab_id"] == lab_id]
    overdue_ca = [ca for ca in cas
                  if ca["status"] in ("OPEN", "REOPENED") and ca["due_date"] < now]
    if len(overdue_ca) >= 1:
        return "FROZEN"
    completed = [i for i in db.inspections.values()
                 if i["lab_id"] == lab_id and i["status"] == "COMPLETED"]
    if completed:
        # latest completed_at; tie-break earliest created_at
        completed.sort(key=lambda i: (-i["completed_at"].timestamp(), i["created_at"], i["_seq"]))
        latest = completed[0]
        has_major = any(f.get("severity") == "MAJOR" for f in (latest["findings"] or []))
        if latest["outcome"] == "FAIL" and has_major:
            return "FROZEN"
    open_high = [i for i in db.incidents.values()
                 if i["lab_id"] == lab_id and i["status"] == "REPORTED"
                 and i["severity"] == "HIGH"]
    if len(open_high) >= 2:
        return "FROZEN"
    open_ca = [ca for ca in cas if ca["status"] in ("OPEN", "SUBMITTED", "REOPENED")]
    if len(open_ca) >= 1:
        return "RESTRICTED"
    if len(open_high) == 1:
        return "RESTRICTED"
    expired = [t for t in db.training_assignments.values()
               if t["lab_id"] == lab_id and t["status"] == "EXPIRED"]
    if len(expired) >= 1:
        return "RESTRICTED"
    for c in db.containers.values():
        if c["lab_id"] == lab_id and c["state"] == "WASTE_TAGGED" and c["tagged_at"] is not None:
            age_days = (now - c["tagged_at"]).total_seconds() // 86400
            if age_days > ACCUMULATION_MAX_DAYS:
                return "RESTRICTED"
    return "NORMAL"


def refresh_posture(lab):
    """Recompute and store posture; on transition INTO FROZEN, cascade-suspend
    ACTIVE registrations (which recomputes access_blocked on matching
    containers)."""
    new_posture = compute_posture(lab)
    old_posture = lab.get("posture", "NORMAL")
    lab["posture"] = new_posture
    if new_posture == "FROZEN" and old_posture != "FROZEN":
        from services import registration as registration_service
        for reg in list(db.registrations.values()):
            if reg["lab_id"] == lab["id"] and reg["status"] == "ACTIVE":
                registration_service.apply_suspend(reg)


def serialize_lab(lab):
    physical, regulatory = _hazard_totals(lab["id"])
    return {
        "id": lab["id"],
        "name": lab["name"],
        "department": lab["department"],
        "building": lab["building"],
        "room": lab["room"],
        "pi_worker_id": lab["pi_worker_id"],
        "status": lab["status"],
        "posture": lab["posture"],
        "hazard_totals_physical": {h: float(v) for h, v in physical.items()},
        "hazard_totals_regulatory": {h: float(v) for h, v in regulatory.items()},
        "permit_report_required": _permit_report_required(regulatory),
        "created_at": db.iso(lab["created_at"]),
        "updated_at": db.iso(lab["updated_at"]),
        "version": lab["version"],
    }


def serialize_worker(w):
    return {
        "id": w["id"],
        "lab_id": w["lab_id"],
        "full_name": w["full_name"],
        "role_in_lab": w["role_in_lab"],
        "created_at": db.iso(w["created_at"]),
        "updated_at": db.iso(w["updated_at"]),
        "version": w["version"],
    }


def compute_access_blocked(container):
    if container["hazard_class"] not in ("CONTROLLED_SUBSTANCE", "SELECT_AGENT"):
        return False
    for reg in db.registrations.values():
        if (reg["lab_id"] == container["lab_id"]
                and reg["material_type"] == container["hazard_class"]
                and reg["status"] == "ACTIVE"):
            return False
    return True


def serialize_container(c):
    return {
        "id": c["id"],
        "lab_id": c["lab_id"],
        "barcode": c["barcode"],
        "chemical_name": c["chemical_name"],
        "hazard_class": c["hazard_class"],
        "quantity_value": float(round2(c["quantity_value"])),
        "quantity_unit": c["quantity_unit"],
        "state": c["state"],
        "accumulation_area_id": c["accumulation_area_id"],
        "tagged_at": db.iso(c["tagged_at"]),
        "pickup_request_id": c["pickup_request_id"],
        "access_blocked": compute_access_blocked(c),
        "created_at": db.iso(c["created_at"]),
        "updated_at": db.iso(c["updated_at"]),
        "version": c["version"],
    }


def area_container_count(area_id):
    return sum(1 for c in db.containers.values()
               if c["accumulation_area_id"] == area_id and c["state"] == "WASTE_TAGGED")


def area_has_overstay(area_id):
    now = db.now()
    for c in db.containers.values():
        if c["accumulation_area_id"] == area_id and c["state"] == "WASTE_TAGGED" \
                and c["tagged_at"] is not None:
            age_days = (now - c["tagged_at"]).total_seconds() // 86400
            if age_days > ACCUMULATION_MAX_DAYS:
                return True
    return False


def serialize_area(a):
    return {
        "id": a["id"],
        "lab_id": a["lab_id"],
        "name": a["name"],
        "area_type": a["area_type"],
        "capacity_containers": a["capacity_containers"],
        "current_container_count": area_container_count(a["id"]),
        "has_overstay_containers": area_has_overstay(a["id"]),
        "created_at": db.iso(a["created_at"]),
        "updated_at": db.iso(a["updated_at"]),
        "version": a["version"],
    }


def pickup_economics(request_rec):
    """pickup_cost_estimate (PRD §3.4): round each per-item fee to 2 decimals
    FIRST, sum the rounded items, then add BASE_FEE."""
    qty_total = Decimal("0")
    fee_sum = Decimal("0")
    for c in db.containers.values():
        if c["pickup_request_id"] == request_rec["id"] and c["state"] == "WASTE_TAGGED":
            qty_total += c["quantity_value"]
            fee_sum += round2(c["quantity_value"] * DISPOSAL_RATE_PER_GAL[c["hazard_class"]])
    # PRD §3.4: estimated_quantity_total is the plain sum of quantity_value
    # (no rounding prescribed); the 2dp round-half-up rule of §2.7 scopes to
    # the lab hazard-total maps only.
    return qty_total, round2(BASE_FEE + fee_sum)


def serialize_pickup(r):
    qty, cost = pickup_economics(r)
    return {
        "id": r["id"],
        "lab_id": r["lab_id"],
        "status": r["status"],
        "dock_id": r["dock_id"],
        "window_start": db.iso(r["window_start"]),
        "window_end": db.iso(r["window_end"]),
        "rejection_reason": r["rejection_reason"],
        "estimated_quantity_total": float(qty),
        "estimated_cost": float(cost),
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def serialize_inspection(i):
    return {
        "id": i["id"],
        "lab_id": i["lab_id"],
        "inspector_id": i["inspector_id"],
        "scheduled_start": db.iso(i["scheduled_start"]),
        "scheduled_end": db.iso(i["scheduled_end"]),
        "status": i["status"],
        "findings": i["findings"],
        "score_weighted": i["score_weighted"],
        "score_flat": i["score_flat"],
        "outcome": i["outcome"],
        "completed_by_inspector_id": i["completed_by_inspector_id"],
        "completed_at": db.iso(i["completed_at"]),
        "created_at": db.iso(i["created_at"]),
        "updated_at": db.iso(i["updated_at"]),
        "version": i["version"],
    }


def serialize_corrective_action(ca):
    now = db.now()
    overdue = ca["status"] in ("OPEN", "REOPENED") and now > ca["due_date"]
    return {
        "id": ca["id"],
        "inspection_id": ca["inspection_id"],
        "lab_id": ca["lab_id"],
        "description": ca["description"],
        "severity": ca["severity"],
        "status": ca["status"],
        "due_date": db.iso(ca["due_date"]),
        "resolution_note": ca["resolution_note"],
        "verified_by": ca["verified_by"],
        "overdue": overdue,
        "created_at": db.iso(ca["created_at"]),
        "updated_at": db.iso(ca["updated_at"]),
        "version": ca["version"],
    }


def serialize_training(t):
    return {
        "id": t["id"],
        "lab_id": t["lab_id"],
        "worker_id": t["worker_id"],
        "hazard_class": t["hazard_class"],
        "status": t["status"],
        "due_date": db.iso(t["due_date"]),
        "completed_at": db.iso(t["completed_at"]),
        "created_at": db.iso(t["created_at"]),
        "updated_at": db.iso(t["updated_at"]),
        "version": t["version"],
    }


def serialize_incident(i):
    return {
        "id": i["id"],
        "lab_id": i["lab_id"],
        "title": i["title"],
        "description": i["description"],
        "severity": i["severity"],
        "near_miss": i["near_miss"],
        "status": i["status"],
        "reported_by": i["reported_by"],
        "resolution": i["resolution"],
        "created_at": db.iso(i["created_at"]),
        "updated_at": db.iso(i["updated_at"]),
        "version": i["version"],
    }


def serialize_registration(r):
    return {
        "id": r["id"],
        "lab_id": r["lab_id"],
        "material_type": r["material_type"],
        "registration_number": r["registration_number"],
        "status": r["status"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def touch(rec):
    """Bump version by exactly 1 and refresh updated_at (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = db.now()


def get_or_404(store, entity_id, what="Resource"):
    from errors import not_found
    rec = store.get(entity_id)
    if rec is None:
        raise not_found(f"{what} not found: {entity_id}")
    return rec
