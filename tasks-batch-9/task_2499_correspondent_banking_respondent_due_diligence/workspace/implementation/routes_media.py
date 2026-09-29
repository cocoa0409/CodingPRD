"""Adverse-media logging and triage, with the confirmation cascade (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import OPS, arg, eq, need, need_respondent, paged, start, PREFIX
from errors import fail
from response import ok, ok_list
from validate import body, fdate, fenum, fstr, q2, validate

bp = Blueprint("media", __name__)

CATEGORIES = ("SANCTIONS_EVASION", "MONEY_LAUNDERING", "FRAUD", "REGULATORY_ACTION",
              "LITIGATION", "OTHER")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
RELIABILITY = ("A", "B", "C")


@bp.post(PREFIX + "/respondents/<respondent_id>/adverse-media-events")
def log_event(respondent_id):
    start(("ComplianceAnalyst", "SanctionsOfficer"))
    resp = need_respondent(respondent_id)
    data = body()
    parsed = validate(data, [
        fstr("headline", True, 1, 200),
        fenum("category", CATEGORIES, True),
        fenum("severity_tier", TIERS, True),
        fenum("source_reliability", RELIABILITY, True),
        fdate("event_date", True),
    ])
    cascade.guard_not_closed(resp)
    if parsed["event_date"] > clock.now():
        fail("ERR_EVENT_DATE_IN_FUTURE",
             "event_date lies after the logical clock.")
    row = store.insert("media", {
        "respondent_bank_id": resp["id"],
        "headline": data["headline"],
        "category": data["category"],
        "severity_tier": data["severity_tier"],
        "source_reliability": data["source_reliability"],
        "event_date": data["event_date"],
        "adjudication_state": "NEW",
        "uplift_points": q2("0.00"),
        "triaged_by_user_id": None,
        "triaged_at": None,
    })
    return ok(row, 201)


@bp.get(PREFIX + "/adverse-media-events")
def list_events():
    start(OPS)
    rows = store.all_rows("media")
    rows = eq(rows, "respondent_bank_id", arg("respondent_bank_id"))
    rows = eq(rows, "adjudication_state", arg("adjudication_state"))
    rows = eq(rows, "severity_tier", arg("severity_tier"))
    rows = eq(rows, "category", arg("category"))
    rows.sort(key=lambda r: (store.dt(r, "event_date") or clock.DEFAULT_CLOCK,
                            r["_seq"]))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/adverse-media-events/<event_id>")
def read_event(event_id):
    start(OPS)
    return ok(need("media", event_id))


@bp.post(PREFIX + "/adverse-media-events/<event_id>/triage")
def triage(event_id):
    ctx = start(("ComplianceAnalyst", "SanctionsOfficer"))
    row = need("media", event_id)
    data = body()
    validate(data, [fenum("action", ("CONFIRM", "DISMISS"), True)])
    resp = store.get("respondents", row["respondent_bank_id"])
    action = data["action"]
    if action == "CONFIRM" and resp["dd_state"] in ("DECLINED", "TERMINATED"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent state permits no media confirmation.")
    cascade.guard_not_closed(resp)
    if row["adjudication_state"] != "NEW":
        fail("ERR_INVALID_MEDIA_STATE", "Only a new media item may be triaged.")
    if action == "DISMISS":
        if row["severity_tier"] == "TIER_1" and row["source_reliability"] in ("A", "B"):
            fail("ERR_INVALID_MEDIA_STATE",
                 "A tier-one item from a reliable source cannot be dismissed.")
        row["adjudication_state"] = "DISMISSED"
        row["triaged_by_user_id"] = ctx.user_id
        store.set_dt(row, "triaged_at", clock.now())
        store.touch(row)
        store.touch(resp)
        return ok(row)
    if store.dt(row, "event_date") > clock.now():
        fail("ERR_EVENT_DATE_IN_FUTURE", "event_date lies after the logical clock.")
    _confirm(row, resp, ctx)
    return ok(row)


def _confirm(row, resp, ctx):
    # Hop one — the item itself.
    row["adjudication_state"] = "CONFIRMED"
    row["triaged_by_user_id"] = ctx.user_id
    store.set_dt(row, "triaged_at", clock.now())
    row["uplift_points"] = calc.event_uplift_points(row)
    store.touch(row)
    # Hop two — respondent scores.
    cascade.recompute_media_scores(resp)
    # Hop three — the refresh cadence.
    new_due = cascade.write_refresh_due_date(resp)
    if new_due is not None:
        for cycle in store.by_seq(store.refreshes_of(resp["id"])):
            if cycle["state"] != "SCHEDULED":
                continue
            scheduled = store.dt(cycle, "scheduled_due_date")
            if scheduled is not None and new_due < scheduled:
                cycle["state"] = "CANCELLED"
                cycle["cancelled_reason"] = "SUPERSEDED_BY_ACCELERATION"
                store.touch(cycle)
                cascade.schedule_cycle(resp, "ADVERSE_MEDIA", clock.now(), new_due)
                break
    # Hop four — ownership reverification.
    hop_four = row["category"] == "SANCTIONS_EVASION" or row["severity_tier"] == "TIER_1"
    if hop_four:
        for owner in store.by_seq(store.owners_of(resp["id"])):
            if owner["verification_status"] == "VERIFIED":
                owner["verification_status"] = "PENDING"
                owner["verified_by_user_id"] = None
                store.touch(owner)
        calc.ownership_rollup(resp)
        store.touch(resp)
    # Hop five — the restriction.
    restricted = False
    if hop_four and not resp["ownership_verified"] \
            and resp["dd_state"] in cascade.APPROVED_FAMILY:
        cascade.restrict(resp, "ADVERSE_MEDIA", "BLOCKED")
        restricted = True
    if row["severity_tier"] == "TIER_1" and row["category"] != "SANCTIONS_EVASION":
        if not restricted and resp["dd_state"] in cascade.APPROVED_FAMILY:
            posture = "SCREEN_ONLY" if resp["payment_posture"] in ("OPEN", "SCREEN_ONLY") \
                else resp["payment_posture"]
            cascade.restrict(resp, "ADVERSE_MEDIA", posture)
        live = [c for c in store.refreshes_of(resp["id"])
                if c["state"] in ("SCHEDULED", "IN_PROGRESS")]
        if not live and resp["refresh_due_date"] is not None:
            cascade.schedule_cycle(resp, "ADVERSE_MEDIA", clock.now(),
                                   store.dt(resp, "refresh_due_date"))
