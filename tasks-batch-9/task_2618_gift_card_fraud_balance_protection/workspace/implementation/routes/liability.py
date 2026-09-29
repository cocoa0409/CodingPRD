"""Liability periods, reserves and the conserved net funded liability
(PRD 3.10)."""
import clock
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_period)
from services import liability as liability_svc
from services.liability import FINAL_BASIS, PERIOD_STATES, PROVISIONAL_BASIS

bp = Blueprint("liability", __name__)


@bp.post("/liability-periods")
def open_period():
    authenticate(["LiabilityAccountant"])
    body = validate.body()
    label = validate.string(body, "label", min_len=1, max_len=40)
    period_start = validate.datetime_field(body, "period_start")
    period_end = validate.datetime_field(body, "period_end")
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")
    for existing in db.periods.values():
        if existing["label"] == label:
            fail("ERR_INVALID_REQUEST", "label is already in use.")
    if liability_svc.overlaps(period_start, period_end) is not None:
        fail("ERR_PERIOD_OVERLAP")

    rec = dbm.record({
        "label": label,
        "period_start": period_start,
        "period_end": period_end,
        "state": "OPEN",
        "outstanding_liability_cents": None,
        "gross_exposure_cents": None,
        "reserve_basis_alert_count": None,
        "provisional_reserve_cents": None,
        "final_reserve_cents": None,
        "unauthorized_writeoff_cents": 0,
        "restatement_count": 0,
        "closed_at": None,
        "restated_at": None,
        "close_note": None,
        "restatement_note": None,
    })
    db.periods[rec["id"]] = rec
    return response.created(rec)


@bp.get("/liability-periods")
def list_periods():
    authenticate(READ_ROLES)
    state = validate.query_enum("state", PERIOD_STATES)
    rows = filter_by(list(db.periods.values()), "state", state)
    return listing_response(rows, order_keys=["period_start"])


@bp.get("/liability-periods/<period_id>")
def get_period(period_id):
    authenticate(READ_ROLES)
    return response.ok(require_period(period_id))


@bp.post("/liability-periods/<period_id>/close")
def close_period(period_id):
    authenticate(["LiabilityAccountant"])
    body = validate.body()
    close_note = validate.string(body, "close_note", required=False, min_len=None)
    period = require_period(period_id)
    if period["state"] != "OPEN":
        fail("ERR_INVALID_PERIOD_STATE")
    policy = dbm.policy()
    period["state"] = "CLOSED"
    period["closed_at"] = clock.now()
    period["close_note"] = close_note
    liability_svc.write_basis(period, PROVISIONAL_BASIS,
                              policy["provisional_reserve_rate_bps"],
                              "provisional_reserve_cents")
    dbm.touch(period)
    return response.ok(period)


@bp.post("/liability-periods/<period_id>/restate")
def restate_period(period_id):
    authenticate(["LiabilityAccountant"])
    body = validate.body()
    note = validate.string(body, "restatement_note", min_len=None)
    expected = validate.integer(body, "expected_liability_period_version")
    period = require_period(period_id)
    if expected != period["version"]:
        fail("ERR_STALE_PERIOD_VERSION")
    if period["state"] not in ("CLOSED", "RESTATED"):
        fail("ERR_INVALID_PERIOD_STATE")
    policy = dbm.policy()
    period["state"] = "RESTATED"
    period["restated_at"] = clock.now()
    period["restatement_note"] = note
    period["restatement_count"] = period["restatement_count"] + 1
    # Overwrites the basis figures but NEVER provisional_reserve_cents.
    liability_svc.write_basis(period, FINAL_BASIS,
                              policy["final_reserve_rate_bps"],
                              "final_reserve_cents")
    dbm.touch(period)
    return response.ok(period)


@bp.get("/liability-periods/<period_id>/exposure-summary")
def exposure_summary(period_id):
    authenticate(["RiskManager", "LiabilityAccountant", "PlatformAdmin"])
    period = require_period(period_id)
    funded = liability_svc.funded_cards()
    outstanding = sum(c["current_balance_cents"] for c in funded)
    writeoff = period["unauthorized_writeoff_cents"]
    in_period = liability_svc.in_period_alerts(period)
    confirmed = [a for a in in_period if a["state"] == "CONFIRMED"]
    return response.ok({
        "net_funded_liability_cents": outstanding - writeoff,
        "funded_card_count": len(funded),
        "unauthorized_writeoff_cents": writeoff,
        "outstanding_liability_cents": period["outstanding_liability_cents"],
        "gross_exposure_cents": period["gross_exposure_cents"],
        "provisional_reserve_cents": period["provisional_reserve_cents"],
        "final_reserve_cents": period["final_reserve_cents"],
        "in_period_alert_count": len(in_period),
        "confirmed_alert_count": len(confirmed),
    })
