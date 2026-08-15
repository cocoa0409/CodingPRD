"""CSA referral reports."""

from flask import Blueprint, g, request

from core import (clock, db, enum_or_422, err, get_body, get_or_404, mint,
                  now_iso, now_iso_short, opt_dt, paginate, parse_dt, pub,
                  refresh_csa, require_roles, success, touch)

bp = Blueprint("referrals", __name__)

OFFENSE_TYPES = {"CRIMINAL_HOMICIDE", "SEX_OFFENSE", "ROBBERY",
                 "AGGRAVATED_ASSAULT", "BURGLARY", "MOTOR_VEHICLE_THEFT",
                 "ARSON", "DOMESTIC_VIOLENCE", "DATING_VIOLENCE", "STALKING",
                 "HATE_CRIME", "LIQUOR_LAW_REFERRAL", "DRUG_LAW_REFERRAL",
                 "WEAPONS_LAW_REFERRAL", "NON_CLERY"}


@bp.post("/csa-referral-reports")
@require_roles("CampusSecurityAuthority")
def create_referral():
    data = get_body()
    for field in ("occurred_at", "geography_id", "offense_suspicion",
                  "narrative"):
        v = data.get(field)
        if v is None or not isinstance(v, str):
            err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    occurred_raw = data["occurred_at"]
    occurred_dt = parse_dt(occurred_raw)
    end_raw, end_dt = opt_dt(data, "occurred_end_at")
    # Body foreign keys resolve first.
    geo = db.geographies.get(data["geography_id"])
    if geo is None:
        err("ERR_REFERENCE_NOT_FOUND", 404, "geography_id does not resolve")
    # Caller CSA must be certified (ACTIVE).
    csa = db.csas.get(g.user_id)
    if csa is not None:
        refresh_csa(csa)
    if csa is None or csa["status"] != "ACTIVE":
        err("ERR_CSA_NOT_CERTIFIED", 422, "Caller CSA is not in ACTIVE status")
    # Referential: geography must be ACTIVE.
    if geo["status"] != "ACTIVE":
        err("ERR_GEOGRAPHY_RETIRED", 422, "Geography is RETIRED")
    # Field-level constraints.
    enum_or_422(data["offense_suspicion"], OFFENSE_TYPES, "offense_suspicion")
    if end_dt is not None and end_dt < occurred_dt:
        err("ERR_VALIDATION_FAILED", 422,
            "occurred_end_at must be >= occurred_at")
    ts = now_iso_short()
    rec = mint({"csa_id": g.user_id,
                "geography_id": data["geography_id"],
                "occurred_at": occurred_raw,
                "occurred_end_at": end_raw,
                "offense_suspicion": data["offense_suspicion"],
                "narrative": data["narrative"],
                "received_at": ts,
                "forwarded_at": None,
                "forward_overdue": False,
                "status": "RECEIVED",
                "_received_dt": clock.current})
    db.referrals[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/csa-referral-reports")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "CampusSecurityAuthority")
def list_referrals():
    items = list(db.referrals.values())
    if g.user_role == "CampusSecurityAuthority":
        items = [r for r in items if r["csa_id"] == g.user_id]
    csa_id = request.args.get("csa_id")
    if csa_id is not None:
        items = [r for r in items if r["csa_id"] == csa_id]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    geo = request.args.get("geography_id")
    if geo is not None:
        items = [r for r in items if r["geography_id"] == geo]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/csa-referral-reports/<rid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "CampusSecurityAuthority")
def get_referral(rid):
    rec = get_or_404(db.referrals, rid)
    if g.user_role == "CampusSecurityAuthority" and rec["csa_id"] != g.user_id:
        err("ERR_FORBIDDEN", 403, "CSA may only access its own referral reports")
    return success(pub(rec), 200)


@bp.post("/csa-referral-reports/<rid>/forward")
@require_roles("CampusSecurityAuthority")
def forward_referral(rid):
    rec = get_or_404(db.referrals, rid)
    if rec["csa_id"] != g.user_id:
        err("ERR_FORBIDDEN", 403, "CSA may only forward its own referral reports")
    if rec["status"] != "RECEIVED":
        err("ERR_INVALID_STATE", 409,
            "Only a RECEIVED referral may be forwarded")
    rec["forwarded_at"] = now_iso_short()
    rec["forward_overdue"] = (
        (clock.current - rec["_received_dt"]).total_seconds() > 24 * 3600)
    rec["status"] = "FORWARDED"
    touch(rec)
    return success(pub(rec), 200)


@bp.post("/csa-referral-reports/<rid>/mark-duplicate")
@require_roles("CleryCoordinator")
def mark_duplicate(rid):
    rec = get_or_404(db.referrals, rid)
    if rec["status"] not in ("RECEIVED", "FORWARDED"):
        err("ERR_INVALID_STATE", 409,
            "Only a RECEIVED or FORWARDED referral may be marked duplicate")
    rec["status"] = "DUPLICATE"
    touch(rec)
    return success(pub(rec), 200)
