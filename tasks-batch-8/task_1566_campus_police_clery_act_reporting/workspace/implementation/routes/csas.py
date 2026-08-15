"""Campus security authorities and their training records."""

from flask import Blueprint, g, request

from core import (clock, db, enum_or_422, err, fmt_dt, get_body, get_or_404,
                  mint, opt_dt, paginate, pub, refresh_csa,
                  refresh_training_record, req_dt, req_int, require_roles,
                  success, touch)

bp = Blueprint("csas", __name__)

CSA_CATEGORIES = {"DEAN", "COACH", "RESIDENT_ADVISOR", "SECURITY_STAFF",
                  "OTHER_OFFICIAL"}
TRAINING_PASS_SCORE = 80


def _valid_to_display(training_year):
    return "%d-09-30T23:59:59Z" % (training_year + 1)


@bp.post("/campus-security-authorities")
@require_roles("SystemAdmin")
def create_csa():
    data = get_body()
    for field in ("full_name", "email", "department", "csa_category"):
        v = data.get(field)
        if v is None or not isinstance(v, str):
            err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    enum_or_422(data["csa_category"], CSA_CATEGORIES, "csa_category")
    csa = mint({"full_name": data["full_name"], "email": data["email"],
                "department": data["department"],
                "csa_category": data["csa_category"],
                "status": "PENDING_TRAINING",
                "certification_expires_at": None,
                "active_training_record_id": None,
                "_cert_expires_dt": None})
    db.csas[csa["id"]] = csa
    return success(pub(csa), 201)


@bp.get("/campus-security-authorities")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief")
def list_csas():
    items = list(db.csas.values())
    for c in items:
        refresh_csa(c)
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    atr = request.args.get("active_training_record_id")
    if atr is not None:
        items = [e for e in items if e.get("active_training_record_id") == atr]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/campus-security-authorities/<cid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "CampusSecurityAuthority")
def get_csa(cid):
    csa = get_or_404(db.csas, cid)
    if g.user_role == "CampusSecurityAuthority" and g.user_id != cid:
        err("ERR_FORBIDDEN", 403, "CSA may only read its own record")
    refresh_csa(csa)
    return success(pub(csa), 200)


@bp.post("/campus-security-authorities/<cid>/training-records")
@require_roles("SystemAdmin")
def create_training_record(cid):
    data = get_body()
    completed_raw, completed_dt = req_dt(data, "completed_at")
    score = req_int(data, "score")
    csa = get_or_404(db.csas, cid)
    refresh_csa(csa)
    # State legality (priority 6): INACTIVE is terminal.
    if csa["status"] == "INACTIVE":
        err("ERR_INVALID_STATE", 409, "CSA is INACTIVE")
    passed = score >= TRAINING_PASS_SCORE
    training_year = completed_dt.year
    valid_from_dt = completed_dt
    import datetime as _dt
    valid_to_dt = _dt.datetime(training_year + 1, 9, 30, 23, 59, 59,
                               tzinfo=_dt.timezone.utc)
    # Structural business constraints (priority 9): training window overlap
    # applies to new passing records against all existing ones.
    if passed:
        for rec in db.training_records.values():
            if rec["csa_id"] != cid:
                continue
            if (rec["_valid_from_dt"] < valid_to_dt
                    and valid_from_dt < rec["_valid_to_dt"]):
                err("ERR_TRAINING_WINDOW_OVERLAP", 409,
                    "Training validity window overlaps an existing record")
    # Field-level value constraints (priority 11).
    if score < 0 or score > 100:
        err("ERR_VALIDATION_FAILED", 422, "score must be in 0..100")
    rec = mint({"csa_id": cid,
                "completed_at": completed_raw,
                "score": score,
                "passed": passed,
                "training_year": training_year,
                "valid_from": completed_raw,
                "valid_to": _valid_to_display(training_year),
                "status": "ACTIVE",
                "_valid_from_dt": valid_from_dt,
                "_valid_to_dt": valid_to_dt})
    db.training_records[rec["id"]] = rec
    if passed:
        csa["status"] = "ACTIVE"
        csa["certification_expires_at"] = rec["valid_to"]
        csa["_cert_expires_dt"] = valid_to_dt
        csa["active_training_record_id"] = rec["id"]
        touch(csa)
    return success(pub(rec), 201)


@bp.get("/campus-security-authorities/<cid>/training-records")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief")
def list_training_records(cid):
    csa = get_or_404(db.csas, cid)
    refresh_csa(csa)
    items = [r for r in db.training_records.values() if r["csa_id"] == cid]
    for r in items:
        refresh_training_record(r)
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.post("/campus-security-authorities/<cid>/deactivate")
@require_roles("SystemAdmin")
def deactivate_csa(cid):
    csa = get_or_404(db.csas, cid)
    refresh_csa(csa)
    if csa["status"] == "INACTIVE":
        err("ERR_INVALID_STATE", 409, "CSA is already INACTIVE")
    csa["status"] = "INACTIVE"
    touch(csa)
    return success(pub(csa), 200)
