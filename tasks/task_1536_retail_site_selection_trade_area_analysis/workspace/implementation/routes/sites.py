"""Candidate sites: intake, screening gate, committee submission, lifecycle."""

from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    ApiError, not_found, invalid_state, already_terminal, invalid_request,
)
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, sync_market, ser_site, ser_review, quorum_count,
    withdraw_site, rhu_int,
)
from util import (
    get_body, req_str, req_int, req_enum, opt_bool, req_datetime, fk_exists,
    list_response,
)

bp = Blueprint("sites", __name__)

_FORMATS = ("EXPRESS", "STANDARD", "FLAGSHIP")

FORMAT_BANDS = {
    "EXPRESS": (2000, 4000),
    "STANDARD": (8000, 15000),
    "FLAGSHIP": (20000, 45000),
}

WITHDRAWABLE = {
    "DRAFT", "SCREENED", "MODELED", "SCORED", "FORECAST_LOCKED",
    "IN_COMMITTEE", "APPROVED", "REJECTED", "LOI_ACTIVE",
    "LEASE_EXECUTED", "BUILD_OUT",
}


def _get_site(sid):
    rec = db.sites.get(sid)
    if rec is None:
        raise not_found(f"Site not found: {sid}")
    return rec


@bp.post("/api/sites")
def create_site():
    require_roles("RealEstateAnalyst")
    body = get_body(required=True)
    market = fk_exists(body, "market_id", db.markets)
    rec = new_record()
    rec.update({
        "market_id": market["id"],
        "address": req_str(body, "address"),
        "format_type": req_enum(body, "format_type", _FORMATS),
        "square_footage": req_int(body, "square_footage", min_v=1),
        "asking_rent_psf_cents": req_int(body, "asking_rent_psf_cents", min_v=0),
        "cam_psf_cents": req_int(body, "cam_psf_cents", min_v=0),
        "tax_psf_cents": req_int(body, "tax_psf_cents", min_v=0),
        "build_cost_cents": req_int(body, "build_cost_cents", min_v=0),
        "site_status": "DRAFT",
        "consecutive_miss_count": 0,
    })
    db.sites[rec["id"]] = rec
    return ok_object(ser_site(rec), status=201)


@bp.get("/api/sites")
def list_sites():
    require_roles(*ALL_API_ROLES)
    return list_response(db.sites.values(), ser_site,
                         filters=["market_id", "site_status"])


@bp.get("/api/sites/<sid>")
def get_site(sid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_site(_get_site(sid)))


@bp.post("/api/sites/<sid>/run-screening")
def run_screening(sid):
    require_roles("RealEstateAnalyst")
    site = _get_site(sid)
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] != "DRAFT":
        raise invalid_state(
            f"Site in {site['site_status']} cannot be screened")
    # §2.7 layer order: format band (7) -> market QUALIFIED (9) -> rent cap (10)
    lo, hi = FORMAT_BANDS[site["format_type"]]
    if not (lo <= site["square_footage"] <= hi):
        raise ApiError(
            "ERR_FORMAT_SQFT_MISMATCH", 422,
            f"square_footage {site['square_footage']} outside the "
            f"{site['format_type']} band {lo}..{hi}")
    market = db.markets[site["market_id"]]
    if market["market_status"] != "QUALIFIED":
        raise ApiError(
            "ERR_MARKET_NOT_QUALIFIED", 409,
            f"Market is {market['market_status']}, not QUALIFIED")
    if site["asking_rent_psf_cents"] > market["max_rent_psf_cents"]:
        raise ApiError(
            "ERR_ASKING_RENT_ABOVE_MARKET_CAP", 422,
            "asking_rent_psf_cents exceeds the market's max_rent_psf_cents")
    site["site_status"] = "SCREENED"
    touch(site)
    return ok_object(ser_site(site))


@bp.post("/api/sites/<sid>/submit-committee")
def submit_committee(sid):
    require_roles("RealEstateManager")
    site = _get_site(sid)
    body = get_body(required=True)
    forecast = fk_exists(body, "sales_forecast_id", db.forecasts)
    sponsor = fk_exists(body, "sponsor_member_id", db.members)
    expires_raw, expires_dt = req_datetime(body, "expires_at")
    chair_override = opt_bool(body, "chair_override", default=False)
    # Layer 5: state permission
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] != "FORECAST_LOCKED":
        raise invalid_state(
            f"Site in {site['site_status']} cannot be submitted to committee")
    # Layer 8: review deadline must be strictly after the logical clock
    if expires_dt <= db.clock:
        raise ApiError(
            "ERR_DEADLINE_IN_PAST", 422,
            "expires_at must be strictly after the current logical clock")
    # Layer 9: pinned forecast must be COMMITTEE_LOCKED and belong to the site
    if (forecast["forecast_status"] != "COMMITTEE_LOCKED"
            or forecast["site_id"] != site["id"]):
        raise ApiError(
            "ERR_FORECAST_NOT_LOCKED", 409,
            "Referenced forecast is not COMMITTEE_LOCKED for this site")
    # Layer 10: fiscal gates
    band = forecast["occupancy_band"]
    if band == "RED":
        raise ApiError(
            "ERR_OCCUPANCY_RATIO_RED", 422,
            "Occupancy band RED blocks committee submission")
    if band == "YELLOW" and not chair_override:
        raise ApiError(
            "ERR_CHAIR_OVERRIDE_REQUIRED", 422,
            "YELLOW occupancy band requires chair_override=true")
    market = db.markets[site["market_id"]]
    sync_market(market)
    cap = rhu_int(
        Decimal(market["annual_capex_budget_cents"]) * 9000 / Decimal(10000))
    if market["committed_capex_cents"] + site["build_cost_cents"] > cap:
        raise ApiError(
            "ERR_BUDGET_CAP_EXCEEDED", 422,
            "Submission would push committed capex past 90% of the budget")
    eligible = sum(
        1 for m in db.members.values()
        if m["member_status"] == "ACTIVE" and m["id"] != sponsor["id"])
    if eligible < 1:
        raise ApiError(
            "ERR_NO_ELIGIBLE_VOTERS", 422,
            "No ACTIVE committee members other than the sponsor")
    review = new_record()
    review.update({
        "site_id": site["id"],
        "sales_forecast_id": forecast["id"],
        "sponsor_member_id": sponsor["id"],
        "chair_override": chair_override,
        "expires_at": expires_raw,
        "expires_dt": expires_dt,
        "review_status": "OPEN",
        "decided_outcome": None,
        "eligible_member_count": eligible,
        "quorum_count": quorum_count(eligible),
        "approve_votes": 0,
        "reject_votes": 0,
        "abstain_votes": 0,
    })
    db.reviews[review["id"]] = review
    site["site_status"] = "IN_COMMITTEE"
    touch(site)
    return ok_object(ser_review(review), status=201)


@bp.post("/api/sites/<sid>/withdraw")
def withdraw_site_route(sid):
    require_roles("RealEstateManager")
    site = _get_site(sid)
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] not in WITHDRAWABLE:
        raise invalid_state(
            f"Site in {site['site_status']} cannot be withdrawn")
    withdraw_site(site)
    return ok_object(ser_site(site))


@bp.post("/api/sites/<sid>/revise")
def revise_site(sid):
    require_roles("RealEstateManager")
    site = _get_site(sid)
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] != "REJECTED":
        raise invalid_state(
            f"Site in {site['site_status']} cannot be revised")
    site["site_status"] = "DRAFT"
    touch(site)
    # Cascade down: retire all analytical work product of the site.
    for m in db.models.values():
        if m["site_id"] == sid and m["model_status"] in ("DRAFT", "LOCKED"):
            m["model_status"] = "SUPERSEDED"
            touch(m)
    for v in db.visits.values():
        if v["site_id"] == sid and v["visit_status"] == "SUBMITTED":
            v["visit_status"] = "SUPERSEDED"
            touch(v)
    for f in db.forecasts.values():
        if (f["site_id"] == sid
                and f["forecast_status"] in ("DRAFT", "COMMITTEE_LOCKED")):
            f["forecast_status"] = "SUPERSEDED"
            touch(f)
    return ok_object(ser_site(site))


@bp.post("/api/sites/<sid>/open")
def open_site(sid):
    require_roles("RealEstateManager")
    site = _get_site(sid)
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] != "BUILD_OUT":
        raise invalid_state(f"Site in {site['site_status']} cannot open")
    bc = next(
        (m for m in db.milestones.values()
         if m["site_id"] == sid and m["milestone_type"] == "BUILD_COMPLETE"),
        None,
    )
    if bc is None or bc["milestone_status"] != "COMPLETED":
        raise ApiError(
            "ERR_BUILD_NOT_COMPLETE", 409,
            "BUILD_COMPLETE milestone is not COMPLETED")
    site["site_status"] = "OPEN"
    touch(site)
    sync_market(db.markets[site["market_id"]])  # open count + saturation check
    return ok_object(ser_site(site))


@bp.post("/api/sites/<sid>/close-out")
def close_out_site(sid):
    require_roles("RealEstateManager")
    site = _get_site(sid)
    if site["site_status"] in ("WITHDRAWN", "CLOSED_OUT"):
        raise already_terminal(f"Site is {site['site_status']}")
    if site["site_status"] not in ("MEASURING", "UNDERPERFORMING"):
        raise invalid_state(
            f"Site in {site['site_status']} cannot be closed out")
    site["site_status"] = "CLOSED_OUT"
    touch(site)
    # open_store_count decrement + capital release + de-saturation check
    sync_market(db.markets[site["market_id"]])
    return ok_object(ser_site(site))
