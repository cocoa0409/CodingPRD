"""Exit event and exit consent endpoints (PRD 3.9)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("exits", __name__)


def _consents_of(exit_event_id):
    return [c for c in db.sorted_rows(db.exit_consents)
            if c["exit_event_id"] == exit_event_id]


@bp.post("/exit-events")
def propose_exit():
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    exit_mode = middleware.req_enum(payload, "exit_mode", C.EXIT_MODES)
    gross_price_cents = middleware.req_int(payload, "gross_price_cents", 1)
    selling_costs_cents = middleware.req_int(payload, "selling_costs_cents", 0)
    consent_threshold_pct = middleware.req_ratio(payload, "consent_threshold_pct",
                                                 "0.0001", "1.0000")
    expected_close_on = middleware.req_dt(payload, "expected_close_on")

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("OPERATING",))

    row = db.new_row(db.exit_events, {
        "trust_id": trust["id"],
        "exit_mode": exit_mode,
        "gross_price_cents": gross_price_cents,
        "selling_costs_cents": selling_costs_cents,
        "consent_threshold_pct": consent_threshold_pct,
        "expected_close_on": expected_close_on,
        "consented_units": 0,
        "consent_pct": None,
        "net_proceeds_cents": None,
        "net_proceeds_per_unit_cents": None,
        "closed_at": None,
        "status": "PROPOSED",
    })
    return created_response(db.serialize(row))


@bp.get("/exit-events/<exit_event_id>")
def get_exit_event(exit_event_id):
    return read_one("exit_event", C.READ_TRUST_SIDE, exit_event_id)


@bp.get("/exit-events")
def list_exit_events():
    return listing(db.exit_events, C.READ_TRUST_SIDE,
                   str_filters=("trust_id", "status", "exit_mode"))


@bp.post("/exit-events/<exit_event_id>/tally-consents")
def tally_consents(exit_event_id):
    middleware.actor([C.SPONSOR])
    event = domain.require("exit_event", exit_event_id)
    trust = db.trusts[event["trust_id"]]

    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("OPERATING",))
    if event["status"] != "PROPOSED":
        raise ApiError("ERR_EXIT_INVALID_STATE")
    consents = _consents_of(event["id"])
    if not consents:
        raise ApiError("ERR_NO_CONSENTS_RECORDED")

    consented_units = sum(c["units_at_consent"] for c in consents
                          if c["decision"] == "CONSENT")
    consent_pct, threshold_met = calc.consent_tally(
        consented_units, trust["units_issued"], event["consent_threshold_pct"])

    event["consented_units"] = consented_units
    event["consent_pct"] = consent_pct
    if threshold_met:
        event["status"] = "APPROVED"
    db.touch(event)

    if threshold_met:
        trust["status"] = "WINDING_DOWN"
        trust["springing_llc_armed"] = (event["exit_mode"] == "SECTION_721_CONVERSION")
        domain.recompute_trust(trust, force=True)
    return object_response(db.serialize(event))


@bp.post("/exit-events/<exit_event_id>/abandon")
def abandon_exit(exit_event_id):
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    event = domain.require("exit_event", exit_event_id)
    if event["status"] != "PROPOSED":
        raise ApiError("ERR_EXIT_INVALID_STATE")

    event["status"] = "ABANDONED"
    db.touch(event)
    return object_response(db.serialize(event))


@bp.post("/exit-events/<exit_event_id>/close")
def close_exit(exit_event_id):
    middleware.actor([C.TRUSTEE])
    event = domain.require("exit_event", exit_event_id)
    trust = db.trusts[event["trust_id"]]

    domain.check_trust_status(trust, ("WINDING_DOWN",))
    loan = domain.funded_loan(trust)
    if loan is None:
        raise ApiError("ERR_LOAN_INVALID_STATE")
    if event["status"] != "APPROVED":
        raise ApiError("ERR_EXIT_INVALID_STATE")

    domain.close_exit(event, trust, loan)
    return object_response(db.serialize(event))


@bp.post("/exit-consents")
def record_consent():
    user_id, _role = middleware.actor([C.INVESTOR])

    # rung 3 — the vote must be cast by the subscription's own beneficial owner
    _ok, lenient = middleware.read_body()
    candidate = domain.lookup("subscription", lenient.get("subscription_id"))
    if candidate is not None:
        domain.check_investor_owns(user_id, candidate["investor_id"])

    payload = middleware.body_or_400()
    exit_event_id = middleware.req_str(payload, "exit_event_id")
    subscription_id = middleware.req_str(payload, "subscription_id")
    decision = middleware.req_enum(payload, "decision", C.CONSENT_DECISIONS)

    event = domain.require("exit_event", exit_event_id)
    sub = domain.require("subscription", subscription_id)

    if sub["status"] != "CLOSED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")
    if event["status"] != "PROPOSED":
        raise ApiError("ERR_EXIT_INVALID_STATE")
    for other in _consents_of(event["id"]):
        if other["subscription_id"] == sub["id"]:
            raise ApiError("ERR_DUPLICATE_CONSENT")

    row = db.new_row(db.exit_consents, {
        "exit_event_id": event["id"],
        "subscription_id": sub["id"],
        "decision": decision,
        "units_at_consent": sub["units_requested"],
        "recorded_at": clock.now(),
    }, journal=True)
    return created_response(db.serialize(row))


@bp.get("/exit-consents/<exit_consent_id>")
def get_consent(exit_consent_id):
    return read_one("exit_consent", C.READ_TRUST_SIDE, exit_consent_id)


@bp.get("/exit-consents")
def list_consents():
    return listing(db.exit_consents, C.READ_TRUST_SIDE,
                   str_filters=("exit_event_id", "subscription_id", "decision"))
