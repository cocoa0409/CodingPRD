"""Fire incidents and fire safety reports."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from core import (clock, db, enum_or_422, err, get_body, get_or_404,
                  json_number, mint, now_iso, now_iso_short, opt_int, paginate, pub,
                  req_dt, req_int, req_number, req_str, require_roles,
                  round_half_up_int, success, touch, _MISSING)

bp = Blueprint("fires", __name__)

CAUSE_CATEGORIES = {"COOKING", "ELECTRICAL", "HEATING", "SMOKING_MATERIALS",
                    "OPEN_FLAME", "INTENTIONAL", "UNDETERMINED"}


def _deadline_for_year(report_year):
    return datetime(report_year + 1, 10, 1, 0, 0, 0, tzinfo=timezone.utc)


def _fsr_for_year(year):
    for r in db.fire_safety_reports.values():
        if r["report_year"] == year:
            return r
    return None


def _fire_staleness_cascade(year):
    """FireIncident finalize/adjustment cascade into the year's FSR."""
    fsr = _fsr_for_year(year)
    if fsr is None or fsr["status"] == "DRAFT":
        return
    fsr["totals_stale"] = True
    if fsr["status"] in ("PUBLISHED", "REPUBLISHED"):
        fsr["status"] = "UNDER_AMENDMENT"
    touch(fsr)


@bp.post("/fire-incidents")
@require_roles("CleryCoordinator", "PoliceChief")
def create_fire_incident():
    data = get_body()
    geography_id = req_str(data, "geography_id")
    occurred_raw, occurred_dt = req_dt(data, "occurred_at")
    cause = req_str(data, "cause_category")
    injuries = opt_int(data, "injuries", 0)
    deaths = opt_int(data, "deaths", 0)
    estimated = req_number(data, "estimated_damage_dollars")
    geo = db.geographies.get(geography_id)
    if geo is None:
        err("ERR_REFERENCE_NOT_FOUND", 404, "geography_id does not resolve")
    if geo["status"] != "ACTIVE":
        err("ERR_GEOGRAPHY_RETIRED", 422, "Geography is RETIRED")
    if not geo["is_residential_facility"]:
        err("ERR_RESIDENTIAL_FACILITY_REQUIRED", 422,
            "Fire incidents require a residential facility geography")
    enum_or_422(cause, CAUSE_CATEGORIES, "cause_category")
    if injuries < 0:
        err("ERR_VALIDATION_FAILED", 422, "injuries must be >= 0")
    if deaths < 0:
        err("ERR_VALIDATION_FAILED", 422, "deaths must be >= 0")
    if estimated < 0:
        err("ERR_VALIDATION_FAILED", 422,
            "estimated_damage_dollars must be >= 0")
    fi = mint({"geography_id": geography_id,
               "occurred_at": occurred_raw,
               "cause_category": cause,
               "injuries": injuries,
               "deaths": deaths,
               "estimated_damage_dollars": estimated,
               "adjudicated_damage_dollars": None,
               "final_damage_dollars": None,
               "status": "REPORTED",
               "_occurred_dt": occurred_dt})
    db.fire_incidents[fi["id"]] = fi
    return success(pub(fi), 201)


@bp.get("/fire-incidents")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_fire_incidents():
    items = list(db.fire_incidents.values())
    geo = request.args.get("geography_id")
    if geo is not None:
        items = [e for e in items if e["geography_id"] == geo]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    ry = request.args.get("report_year")
    if ry is not None:
        try:
            ry_i = int(ry)
            items = [e for e in items if e["_occurred_dt"].year == ry_i]
        except ValueError:
            items = []
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/fire-incidents/<fid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_fire_incident(fid):
    return success(pub(get_or_404(db.fire_incidents, fid)), 200)


@bp.post("/fire-incidents/<fid>/finalize")
@require_roles("PoliceChief")
def finalize_fire_incident(fid):
    data = get_body()
    adjudicated = req_number(data, "adjudicated_damage_dollars")
    fi = get_or_404(db.fire_incidents, fid)
    if fi["status"] not in ("REPORTED", "UNDER_ADJUSTMENT"):
        err("ERR_INVALID_STATE", 409,
            "Only a REPORTED or UNDER_ADJUSTMENT fire may be finalized")
    if adjudicated < 0:
        err("ERR_VALIDATION_FAILED", 422,
            "adjudicated_damage_dollars must be >= 0")
    fi["adjudicated_damage_dollars"] = adjudicated
    fi["final_damage_dollars"] = round_half_up_int(adjudicated)
    fi["status"] = "FINALIZED"
    touch(fi)
    _fire_staleness_cascade(fi["_occurred_dt"].year)
    return success(pub(fi), 200)


@bp.post("/fire-incidents/<fid>/begin-adjustment")
@require_roles("PoliceChief")
def begin_adjustment(fid):
    fi = get_or_404(db.fire_incidents, fid)
    if fi["status"] != "FINALIZED":
        err("ERR_INVALID_STATE", 409,
            "Only a FINALIZED fire may begin adjustment")
    fi["status"] = "UNDER_ADJUSTMENT"
    touch(fi)
    _fire_staleness_cascade(fi["_occurred_dt"].year)
    return success(pub(fi), 200)


# -------------------------------------------------------- fire safety ---

@bp.post("/fire-safety-reports")
@require_roles("SystemAdmin")
def create_fsr():
    data = get_body()
    report_year = req_int(data, "report_year")
    for r in db.fire_safety_reports.values():
        if r["report_year"] == report_year:
            err("ERR_DUPLICATE_REPORT_YEAR", 409,
                "A fire safety report already exists for %s" % report_year)
    fsr = mint({"report_year": report_year,
                "total_fires": 0,
                "total_injuries": 0,
                "total_deaths": 0,
                "total_damage_dollars": 0,
                "provisional_total_damage_dollars": 0,
                "totals_stale": False,
                "published_at": None,
                "is_late": False,
                "status": "DRAFT"})
    db.fire_safety_reports[fsr["id"]] = fsr
    return success(pub(fsr), 201)


@bp.get("/fire-safety-reports")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_fsrs():
    items = list(db.fire_safety_reports.values())
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/fire-safety-reports/<fid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_fsr(fid):
    return success(pub(get_or_404(db.fire_safety_reports, fid)), 200)


@bp.post("/fire-safety-reports/<fid>/compile")
@require_roles("CleryCoordinator")
def compile_fsr(fid):
    fsr = get_or_404(db.fire_safety_reports, fid)
    if fsr["status"] not in ("DRAFT", "COMPILED", "UNDER_AMENDMENT"):
        err("ERR_INVALID_STATE", 409,
            "Compile allowed only in DRAFT, COMPILED, or UNDER_AMENDMENT")
    year = fsr["report_year"]
    finalized = [f for f in db.fire_incidents.values()
                 if f["_occurred_dt"].year == year
                 and f["status"] == "FINALIZED"]
    reported = [f for f in db.fire_incidents.values()
                if f["_occurred_dt"].year == year
                and f["status"] == "REPORTED"]
    fsr["total_fires"] = len(finalized)
    fsr["total_injuries"] = sum(f["injuries"] for f in finalized)
    fsr["total_deaths"] = sum(f["deaths"] for f in finalized)
    fsr["total_damage_dollars"] = sum(f["final_damage_dollars"]
                                      for f in finalized)
    prov = Decimal("0")
    for f in reported:
        prov += Decimal(str(f["estimated_damage_dollars"]))
    fsr["provisional_total_damage_dollars"] = json_number(prov)
    fsr["totals_stale"] = False
    if fsr["status"] in ("DRAFT", "COMPILED"):
        fsr["status"] = "COMPILED"
    # UNDER_AMENDMENT stays UNDER_AMENDMENT until publish.
    touch(fsr)
    return success(pub(fsr), 200)


@bp.post("/fire-safety-reports/<fid>/publish")
@require_roles("PoliceChief")
def publish_fsr(fid):
    fsr = get_or_404(db.fire_safety_reports, fid)
    if fsr["status"] == "COMPILED":
        new_status = "PUBLISHED"
    elif fsr["status"] == "UNDER_AMENDMENT" and not fsr["totals_stale"]:
        new_status = "REPUBLISHED"
    else:
        err("ERR_INVALID_STATE", 409,
            "Publish requires COMPILED, or UNDER_AMENDMENT with fresh totals")
    fsr["published_at"] = now_iso_short()
    fsr["is_late"] = clock.current > _deadline_for_year(fsr["report_year"])
    fsr["status"] = new_status
    touch(fsr)
    return success(pub(fsr), 200)


@bp.post("/fire-safety-reports/<fid>/begin-amendment")
@require_roles("CleryCoordinator")
def begin_fsr_amendment(fid):
    fsr = get_or_404(db.fire_safety_reports, fid)
    if fsr["status"] not in ("PUBLISHED", "REPUBLISHED"):
        err("ERR_INVALID_STATE", 409,
            "Only a PUBLISHED or REPUBLISHED report may be amended")
    fsr["status"] = "UNDER_AMENDMENT"
    touch(fsr)
    return success(pub(fsr), 200)
