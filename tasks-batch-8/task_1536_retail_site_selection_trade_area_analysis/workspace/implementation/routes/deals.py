"""LOIs (negotiation rounds + exclusivity windows) and leases."""

from flask import Blueprint

from db import db
from errors import (
    ApiError, not_found, invalid_state, already_terminal, invalid_request,
)
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, effective_annual_rent, loi_windows_overlap,
    crew_windows_conflict, occupancy_ratio_bp, withdraw_site, ser_loi,
    ser_lease,
)
from util import (
    get_body, req_int, opt_int, req_date, fk_exists, list_response,
)

bp = Blueprint("deals", __name__)

LOI_TERMINAL = ("ACCEPTED", "EXPIRED", "WITHDRAWN")


def _get_loi(lid):
    rec = db.lois.get(lid)
    if rec is None:
        raise not_found(f"LOI not found: {lid}")
    return rec


def _check_loi_overlap(site_id, start_d, end_d, exclude_id=None):
    """Half-open [start, end) exclusivity windows of the same site's LOIs in
    SENT/COUNTERED/ACCEPTED may not intersect; adjacency is allowed."""
    for other in db.lois.values():
        if other["site_id"] != site_id or other["id"] == exclude_id:
            continue
        if other["loi_status"] not in ("SENT", "COUNTERED", "ACCEPTED"):
            continue
        if loi_windows_overlap(
                start_d, end_d, other["_start_d"], other["_end_d"]):
            raise ApiError(
                "ERR_LOI_EXCLUSIVITY_OVERLAP", 409,
                "Exclusivity window overlaps another active LOI of the site")


def _check_end_after_clock(end_d):
    """Create/send gate: the end date must be strictly after the clock date."""
    if not (end_d > db.clock.date()):
        raise ApiError(
            "ERR_WINDOW_IN_PAST", 422,
            "Exclusivity end date is not strictly after the logical clock date")


def _check_within_window(loi):
    """Counter/resend/accept gate: clock date on or before the end date."""
    if not (db.clock.date() <= loi["_end_d"]):
        raise ApiError(
            "ERR_WINDOW_IN_PAST", 422,
            "Exclusivity window has passed relative to the logical clock")


@bp.post("/api/lois")
def create_loi():
    require_roles("RealEstateManager")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    rent = req_int(body, "rent_psf_cents", min_v=0)
    escalation = req_int(body, "escalation_pct_bp", min_v=0, max_v=2000)
    term = req_int(body, "term_years", min_v=1, max_v=20)
    ti = opt_int(body, "ti_allowance_cents", default=0, min_v=0)
    free_months = opt_int(body, "free_rent_months", default=0, min_v=0,
                          max_v=term * 12)
    start_raw, start_d = req_date(body, "exclusivity_start_date")
    end_raw, end_d = req_date(body, "exclusivity_end_date")
    if not (end_d > start_d):
        raise invalid_request(
            "exclusivity_end_date must be strictly after exclusivity_start_date")
    # Layer 5: site must be APPROVED or LOI_ACTIVE.
    if site["site_status"] not in ("APPROVED", "LOI_ACTIVE"):
        raise invalid_state(
            f"Site in {site['site_status']} does not accept LOIs")
    # Layer 7: exclusivity overlap; Layer 8: end-date clock gate.
    _check_loi_overlap(site["id"], start_d, end_d)
    _check_end_after_clock(end_d)
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "rent_psf_cents": rent,
        "escalation_pct_bp": escalation,
        "term_years": term,
        "ti_allowance_cents": ti,
        "free_rent_months": free_months,
        "exclusivity_start_date": start_raw,
        "exclusivity_end_date": end_raw,
        "_start_d": start_d,
        "_end_d": end_d,
        "countered_rent_psf_cents": None,
        "agreed_rent_psf_cents": None,
        "round_number": 1,
        "effective_annual_rent_cents": None,
        "loi_status": "DRAFT",
    })
    db.lois[rec["id"]] = rec
    return ok_object(ser_loi(rec), status=201)


@bp.get("/api/lois")
def list_lois():
    require_roles(*ALL_API_ROLES)
    return list_response(db.lois.values(), ser_loi,
                         filters=["site_id", "loi_status"])


@bp.get("/api/lois/<lid>")
def get_loi(lid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_loi(_get_loi(lid)))


@bp.post("/api/lois/<lid>/send")
def send_loi(lid):
    require_roles("RealEstateManager")
    loi = _get_loi(lid)
    if loi["loi_status"] in LOI_TERMINAL:
        raise already_terminal(f"LOI is {loi['loi_status']}")
    if loi["loi_status"] != "DRAFT":
        raise invalid_state(f"LOI in {loi['loi_status']} cannot be sent")
    _check_loi_overlap(loi["site_id"], loi["_start_d"], loi["_end_d"],
                       exclude_id=loi["id"])
    _check_end_after_clock(loi["_end_d"])
    site = db.sites[loi["site_id"]]
    loi["effective_annual_rent_cents"] = effective_annual_rent(
        loi["rent_psf_cents"], loi["escalation_pct_bp"], loi["term_years"],
        loi["ti_allowance_cents"], loi["free_rent_months"],
        site["square_footage"])
    loi["loi_status"] = "SENT"
    touch(loi)
    # The first SENT LOI of a site bubbles it APPROVED -> LOI_ACTIVE.
    if site["site_status"] == "APPROVED":
        site["site_status"] = "LOI_ACTIVE"
        touch(site)
    return ok_object(ser_loi(loi))


@bp.post("/api/lois/<lid>/counter")
def counter_loi(lid):
    require_roles("RealEstateManager")
    loi = _get_loi(lid)
    body = get_body(required=True)
    countered = req_int(body, "countered_rent_psf_cents", min_v=0)
    if loi["loi_status"] in LOI_TERMINAL:
        raise already_terminal(f"LOI is {loi['loi_status']}")
    if loi["loi_status"] != "SENT":
        raise invalid_state(f"LOI in {loi['loi_status']} cannot be countered")
    _check_within_window(loi)
    loi["countered_rent_psf_cents"] = countered
    loi["loi_status"] = "COUNTERED"
    touch(loi)
    return ok_object(ser_loi(loi))


@bp.post("/api/lois/<lid>/resend")
def resend_loi(lid):
    require_roles("RealEstateManager")
    loi = _get_loi(lid)
    body = get_body(required=True)
    rent = req_int(body, "rent_psf_cents", min_v=0)
    if loi["loi_status"] in LOI_TERMINAL:
        raise already_terminal(f"LOI is {loi['loi_status']}")
    if loi["loi_status"] != "COUNTERED":
        raise invalid_state(f"LOI in {loi['loi_status']} cannot be re-sent")
    _check_within_window(loi)
    site = db.sites[loi["site_id"]]
    loi["rent_psf_cents"] = rent
    loi["countered_rent_psf_cents"] = None
    loi["round_number"] += 1
    loi["effective_annual_rent_cents"] = effective_annual_rent(
        rent, loi["escalation_pct_bp"], loi["term_years"],
        loi["ti_allowance_cents"], loi["free_rent_months"],
        site["square_footage"])
    loi["loi_status"] = "SENT"
    touch(loi)
    return ok_object(ser_loi(loi))


@bp.post("/api/lois/<lid>/accept")
def accept_loi(lid):
    require_roles("RealEstateManager")
    loi = _get_loi(lid)
    if loi["loi_status"] in LOI_TERMINAL:
        raise already_terminal(f"LOI is {loi['loi_status']}")
    if loi["loi_status"] not in ("SENT", "COUNTERED"):
        raise invalid_state(f"LOI in {loi['loi_status']} cannot be accepted")
    _check_within_window(loi)
    # The agreed rent pins per the from-state: the broker's own rent from
    # SENT, the landlord's counter from COUNTERED.
    if loi["loi_status"] == "COUNTERED":
        loi["agreed_rent_psf_cents"] = loi["countered_rent_psf_cents"]
    else:
        loi["agreed_rent_psf_cents"] = loi["rent_psf_cents"]
    loi["loi_status"] = "ACCEPTED"
    touch(loi)
    return ok_object(ser_loi(loi))


@bp.post("/api/lois/<lid>/withdraw")
def withdraw_loi(lid):
    require_roles("RealEstateManager")
    loi = _get_loi(lid)
    if loi["loi_status"] in LOI_TERMINAL:
        raise already_terminal(f"LOI is {loi['loi_status']}")
    loi["loi_status"] = "WITHDRAWN"
    touch(loi)
    return ok_object(ser_loi(loi))


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

def _get_lease(lid):
    rec = db.leases.get(lid)
    if rec is None:
        raise not_found(f"Lease not found: {lid}")
    return rec


@bp.post("/api/leases")
def create_lease():
    require_roles("RealEstateManager")
    body = get_body(required=True)
    loi = fk_exists(body, "loi_id", db.lois)
    crew = fk_exists(body, "crew_id", db.crews)
    final_rent = req_int(body, "final_rent_psf_cents", min_v=0)
    escalation = req_int(body, "escalation_pct_bp", min_v=0, max_v=2000)
    term = req_int(body, "term_years", min_v=1, max_v=20)
    ti = opt_int(body, "ti_allowance_cents", default=0, min_v=0)
    free_months = opt_int(body, "free_rent_months", default=0, min_v=0,
                          max_v=term * 12)
    start_raw, start_d = req_date(body, "build_start_date")
    end_raw, end_d = req_date(body, "build_end_date")
    if not (end_d > start_d):
        raise invalid_request(
            "build_end_date must be strictly after build_start_date")
    # Layer 8: crew build-window conflict (closed interval + 6-day buffer).
    for other in db.leases.values():
        if other["crew_id"] != crew["id"]:
            continue
        if other["lease_status"] not in ("NEGOTIATING", "EXECUTED"):
            continue
        if crew_windows_conflict(start_d, end_d,
                                 other["_b_start"], other["_b_end"]):
            raise ApiError(
                "ERR_CREW_WINDOW_CONFLICT", 409,
                "Build window conflicts with another lease on this crew")
    # Layer 9: LOI ACCEPTED, then crew ACTIVE.
    if loi["loi_status"] != "ACCEPTED":
        raise ApiError(
            "ERR_LOI_NOT_ACCEPTED", 409,
            f"LOI is {loi['loi_status']}, not ACCEPTED")
    if crew["crew_status"] != "ACTIVE":
        raise ApiError(
            "ERR_CREW_NOT_AVAILABLE", 409,
            f"Crew is {crew['crew_status']}, not ACTIVE")
    rec = new_record()
    rec.update({
        "loi_id": loi["id"],
        "final_rent_psf_cents": final_rent,
        "escalation_pct_bp": escalation,
        "term_years": term,
        "ti_allowance_cents": ti,
        "free_rent_months": free_months,
        "crew_id": crew["id"],
        "build_start_date": start_raw,
        "build_end_date": end_raw,
        "_b_start": start_d,
        "_b_end": end_d,
        "effective_annual_rent_cents": None,
        "final_occupancy_ratio_bp": None,
        "lease_status": "NEGOTIATING",
    })
    db.leases[rec["id"]] = rec
    return ok_object(ser_lease(rec), status=201)


@bp.get("/api/leases")
def list_leases():
    require_roles(*ALL_API_ROLES)
    return list_response(db.leases.values(), ser_lease,
                         filters=["loi_id", "crew_id", "lease_status"])


@bp.get("/api/leases/<lid>")
def get_lease(lid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_lease(_get_lease(lid)))


@bp.post("/api/leases/<lid>/execute")
def execute_lease(lid):
    require_roles("RealEstateManager")
    lease = _get_lease(lid)
    if lease["lease_status"] == "TERMINATED":
        raise already_terminal("Lease is TERMINATED")
    if lease["lease_status"] != "NEGOTIATING":
        raise invalid_state(
            f"Lease in {lease['lease_status']} cannot be executed")
    loi = db.lois[lease["loi_id"]]
    site = db.sites[loi["site_id"]]
    # Drift check: final rent may exceed the agreed rent by at most 5%
    # (inclusive boundary, ceiling rounded half-up to whole cents).
    from services import rhu_int
    from decimal import Decimal
    ceiling = rhu_int(
        Decimal(loi["agreed_rent_psf_cents"]) * 10500 / Decimal(10000))
    if lease["final_rent_psf_cents"] > ceiling:
        raise ApiError(
            "ERR_LEASE_TERMS_DRIFT", 422,
            "final_rent_psf_cents exceeds agreed rent * 1.05")
    # Effective rent over the lease's own terms (pinned rounding order).
    lease["effective_annual_rent_cents"] = effective_annual_rent(
        lease["final_rent_psf_cents"], lease["escalation_pct_bp"],
        lease["term_years"], lease["ti_allowance_cents"],
        lease["free_rent_months"], site["square_footage"])
    # FINAL occupancy ratio over the pinned forecast's net annual sales.
    pinned = next(
        (f for f in db.forecasts.values()
         if f["site_id"] == site["id"]
         and f["forecast_status"] == "COMMITTEE_LOCKED"),
        None,
    )
    net = pinned["net_annual_sales_cents"] if pinned is not None else 0
    lease["final_occupancy_ratio_bp"] = occupancy_ratio_bp(
        lease["final_rent_psf_cents"], site["cam_psf_cents"],
        site["tax_psf_cents"], site["square_footage"], net)
    lease["lease_status"] = "EXECUTED"
    touch(lease)
    if site["site_status"] == "LOI_ACTIVE":
        site["site_status"] = "LEASE_EXECUTED"
        touch(site)
    return ok_object(ser_lease(lease))


@bp.post("/api/leases/<lid>/terminate")
def terminate_lease(lid):
    require_roles("RealEstateManager")
    lease = _get_lease(lid)
    if lease["lease_status"] == "TERMINATED":
        raise already_terminal("Lease is TERMINATED")
    if lease["lease_status"] != "EXECUTED":
        raise invalid_state(
            f"Lease in {lease['lease_status']} cannot be terminated")
    lease["lease_status"] = "TERMINATED"
    touch(lease)
    loi = db.lois[lease["loi_id"]]
    site = db.sites[loi["site_id"]]
    if site["site_status"] in ("LEASE_EXECUTED", "BUILD_OUT"):
        withdraw_site(site)  # compensating withdrawal with capital release
    return ok_object(ser_lease(lease))
