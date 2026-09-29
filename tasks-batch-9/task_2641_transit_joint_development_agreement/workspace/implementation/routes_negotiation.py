"""Exclusive negotiation periods: direct grants, extension, termination, expiry."""

from flask import Blueprint

import authz
import common
import envelope
import shape
import store
from errors import fail

bp = Blueprint("negotiation", __name__)

MAX_NEGOTIATION_EXTENSIONS = 2


@bp.post("/jda/sites/<site_id>/negotiation-periods")
def grant_period(site_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    proposal_id = shape.as_str(body, "proposal_id")
    start_date = shape.as_date(body, "start_date")
    end_date = shape.as_date(body, "end_date")
    site = store.require("site", site_id)
    proposal = store.require("proposal", proposal_id)
    if site["status"] not in ("SOLICITATION_READY", "UNDER_AGREEMENT"):
        fail("ERR_INVALID_SITE_STATE",
             "Site must be SOLICITATION_READY or UNDER_AGREEMENT")
    if proposal["status"] not in common.RESPONSIVE_STATUSES:
        fail("ERR_PROPOSAL_NOT_ELIGIBLE", "Proposal is neither SUBMITTED nor SHORTLISTED")
    start = store.parse_date(start_date)
    end = store.parse_date(end_date)
    if end <= start:
        fail("ERR_INVALID_INTERVAL", "end_date must be strictly later than start_date")
    if common.period_collides(site_id, start, end):
        fail("ERR_NEGOTIATION_PERIOD_OVERLAP",
             "The interval collides with a live exclusive negotiation period on the site")
    period = store.create("negotiation_period", {
        "site_id": site_id,
        "proposal_id": proposal_id,
        "start_date": start_date,
        "end_date": end_date,
        "extension_count": 0,
        "status": "ACTIVE",
        "termination_reason": None,
    })
    if common.move_site_under_agreement(site):
        # "Other" excludes the solicitation that owns the proposal being granted
        # exclusivity, so a direct grant never cancels its own proposal's
        # solicitation.
        common.cancel_site_solicitations(site_id, ("ISSUED",),
                                         {proposal["solicitation_id"]})
    return envelope.created(common.public(period))


@bp.post("/jda/negotiation-periods/<period_id>/extend")
def extend_period(period_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    new_end_date = shape.as_date(body, "new_end_date")
    period = store.require("negotiation_period", period_id)
    if period["status"] not in common.LIVE_PERIOD_STATUSES:
        fail("ERR_NEGOTIATION_PERIOD_NOT_ACTIVE",
             "Period is neither ACTIVE nor EXTENDED")
    start = store.parse_date(period["start_date"])
    current_end = store.parse_date(period["end_date"])
    new_end = store.parse_date(new_end_date)
    if new_end <= current_end:
        fail("ERR_INVALID_INTERVAL",
             "new_end_date must be strictly later than the current end_date")
    if common.period_collides(period["site_id"], start, new_end, exclude_id=period_id):
        fail("ERR_NEGOTIATION_PERIOD_OVERLAP",
             "The extended interval collides with a sibling period on the site")
    if period["extension_count"] >= MAX_NEGOTIATION_EXTENSIONS:
        fail("ERR_MAX_EXTENSIONS_REACHED",
             "This period has already been extended %d times" % MAX_NEGOTIATION_EXTENSIONS)
    period["end_date"] = new_end_date
    period["extension_count"] += 1
    period["status"] = "EXTENDED"
    store.touch(period)
    return envelope.ok(common.public(period))


@bp.post("/jda/negotiation-periods/<period_id>/terminate")
def terminate_period(period_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    reason = shape.as_str(body, "termination_reason")
    period = store.require("negotiation_period", period_id)
    for agreement in store.all_of("agreement"):
        if (agreement["proposal_id"] == period["proposal_id"]
                and agreement["negotiation_status"] == "EXECUTED"):
            fail("ERR_INVALID_SITE_STATE",
                 "An executed agreement rests on this period and it cannot be terminated")
    if period["status"] not in common.LIVE_PERIOD_STATUSES:
        fail("ERR_NEGOTIATION_PERIOD_NOT_ACTIVE",
             "Period is neither ACTIVE nor EXTENDED")
    period["status"] = "TERMINATED"
    period["termination_reason"] = reason
    store.touch(period)
    # hop 1 — the held proposal drops SELECTED -> REJECTED
    proposal = store.get("proposal", period["proposal_id"])
    if proposal is not None and proposal["status"] == "SELECTED":
        proposal["status"] = "REJECTED"
        store.touch(proposal)
    # hop 2 — conditional: the site returns to the market only when nothing holds it
    site = store.get("site", period["site_id"])
    if site is not None:
        common.release_site_if_free(site)
    return envelope.ok(common.public(period))


# --------------------------------------------------------------- the clock ---
clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    authz.authorize("SystemAdmin")
    body = shape.body()
    to_iso8601 = shape.as_datetime(body, "to_iso8601")
    instant = store.parse_dt(to_iso8601)
    store.set_now(instant)
    expired_ids = []
    touched_sites = []
    for period in store.by_seq(store.all_of("negotiation_period")):
        if period["status"] not in common.LIVE_PERIOD_STATUSES:
            continue
        end = store.parse_date(period["end_date"])
        # A period ending on a given day survives every instant of that day.
        if end is None or not (instant.date() > end):
            continue
        period["status"] = "EXPIRED"
        store.touch(period)
        expired_ids.append(period["id"])
        proposal = store.get("proposal", period["proposal_id"])
        if proposal is not None and proposal["status"] == "SELECTED":
            proposal["status"] = "REJECTED"
            store.touch(proposal)
        if period["site_id"] not in touched_sites:
            touched_sites.append(period["site_id"])
    for site_id in touched_sites:
        site = store.get("site", site_id)
        if site is not None:
            common.release_site_if_free(site)
    return envelope.ok({
        "current_utc": store.fmt_dt(instant),
        "expired_negotiation_period_ids": expired_ids,
    })
