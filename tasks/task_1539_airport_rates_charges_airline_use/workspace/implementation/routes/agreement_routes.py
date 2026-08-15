"""AirlineAgreement: create-with-supersede, countersign / decline / suspend /
reinstate transitions, and successor reverse reachability."""
from flask import Blueprint

import errors
import helpers
import services
from db import store
from helpers import (authenticate, get_path, json_body, paginate, resolve_fk,
                     req_string, opt_int, require_ownership, READ_ROLES)
from response import success_object, success_list
from services import (ser_agreement, touch, stamp, now_dt,
                      recompute_fy_rented_space, mii_exclusion_cascade,
                      adopted_rates_setting, COUNTERSIGN_WINDOW_DAYS)
from util import new_id, fmt_iso, parse_iso, days_later

bp = Blueprint("agreements", __name__)


def _get_agreement(agreement_id):
    return get_path(store.agreements, agreement_id, "AirlineAgreement")


def _check_not_superseded(ag):
    if ag["superseded_by_id"] is not None:
        raise errors.agreement_superseded()


@bp.post("/airport/airline_agreements")
def create_agreement():
    authenticate(("AirportFinance",))
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)      # priority 4
    fy = resolve_fk(body, "fiscal_year_id", store.fiscal_years)   # priority 4
    airline_id = req_string(body, "airline_id")                   # priority 5
    fiscal_year_id = req_string(body, "fiscal_year_id")
    rented_space = opt_int(body, "rented_space_sqft", default=0, minimum=0)
    if rented_space is None:
        rented_space = 0
    services.check_fy_open_guard(fy)                              # priority 9
    ts = stamp()
    # create-with-supersede: freeze any prior active agreement for the pair
    prior = services.active_agreement(fiscal_year_id, airline_id)
    ag = {
        "id": new_id(),
        "airline_id": airline["id"],
        "fiscal_year_id": fy["id"],
        "signature_status": "NON_SIGNATORY",
        "credit_standing": "GOOD",
        "rented_space_sqft": rented_space,
        "countersign_deadline": None,
        "superseded_by_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    # if the year's schedule already stands adopted, the deadline is stamped
    # from that adoption (countersign_deadline = adopted_at + 30 days)
    adopted = adopted_rates_setting(fy["id"])
    if adopted is not None and adopted["status"] == "ADOPTED":
        ag["countersign_deadline"] = fmt_iso(
            days_later(adopted["_adopted_dt"], COUNTERSIGN_WINDOW_DAYS))
    store.agreements[ag["id"]] = ag
    if prior is not None:
        prior["superseded_by_id"] = ag["id"]
        touch(prior)
        recompute_fy_rented_space(fy)
    return success_object(ser_agreement(ag), status=201)


@bp.get("/airport/airline_agreements/<agreement_id>")
def get_agreement(agreement_id):
    authenticate(READ_ROLES)
    ag = _get_agreement(agreement_id)
    return success_object(ser_agreement(ag))


@bp.post("/airport/airline_agreements/<agreement_id>/countersign")
def countersign(agreement_id):
    uid, _ = authenticate(("SignatoryAirline",))
    ag = _get_agreement(agreement_id)
    require_ownership(uid, ag["airline_id"])
    _check_not_superseded(ag)
    if ag["signature_status"] == "SIGNATORY":
        raise errors.double_countersign()
    fy = store.fiscal_years[ag["fiscal_year_id"]]
    adopted = adopted_rates_setting(fy["id"])
    if adopted is None or adopted["status"] != "ADOPTED":
        raise errors.invalid_state(
            "The year's rate schedule must stand ADOPTED before countersignature")
    if ag["credit_standing"] == "SUSPENDED":
        raise errors.invalid_state("A SUSPENDED carrier cannot countersign")
    # priority 18: the countersign deadline ranks last of the business rules
    deadline = parse_iso(ag["countersign_deadline"]) if ag["countersign_deadline"] else None
    if deadline is None or now_dt() > deadline:
        raise errors.countersign_lapsed()
    ag["signature_status"] = "SIGNATORY"
    touch(ag)
    recompute_fy_rented_space(fy)
    return success_object(ser_agreement(ag))


@bp.post("/airport/airline_agreements/<agreement_id>/decline-renewal")
def decline_renewal(agreement_id):
    uid, _ = authenticate(("SignatoryAirline",))
    ag = _get_agreement(agreement_id)
    require_ownership(uid, ag["airline_id"])
    _check_not_superseded(ag)
    if ag["signature_status"] != "SIGNATORY":
        raise errors.invalid_state("Only a SIGNATORY agreement can decline renewal")
    ag["signature_status"] = "NON_SIGNATORY"
    touch(ag)
    fy = store.fiscal_years[ag["fiscal_year_id"]]
    recompute_fy_rented_space(fy)
    mii_exclusion_cascade(fy["id"], ag["airline_id"])
    return success_object(ser_agreement(ag))


def _has_pending_line(fy_id, airline_id):
    for line in store.settlement_lines.values():
        settlement = store.settlements.get(line["annual_settlement_id"])
        if (settlement is not None and settlement["fiscal_year_id"] == fy_id
                and line["airline_id"] == airline_id
                and line["payment_status"] == "PENDING"):
            return True
    return False


@bp.post("/airport/airline_agreements/<agreement_id>/suspend")
def suspend(agreement_id):
    authenticate(("AirportFinance",))
    ag = _get_agreement(agreement_id)
    _check_not_superseded(ag)
    if ag["credit_standing"] != "DELINQUENT":
        raise errors.invalid_state("Only a DELINQUENT carrier can be suspended")
    if not _has_pending_line(ag["fiscal_year_id"], ag["airline_id"]):
        raise errors.invalid_state(
            "Suspension requires at least one PENDING settlement line")
    ag["credit_standing"] = "SUSPENDED"
    touch(ag)
    return success_object(ser_agreement(ag))


@bp.post("/airport/airline_agreements/<agreement_id>/reinstate")
def reinstate(agreement_id):
    authenticate(("AirportFinance",))
    ag = _get_agreement(agreement_id)
    _check_not_superseded(ag)
    if ag["credit_standing"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED carrier can be reinstated")
    if _has_pending_line(ag["fiscal_year_id"], ag["airline_id"]):
        raise errors.invalid_state(
            "Reinstatement requires that no settlement line remains PENDING")
    ag["credit_standing"] = "GOOD"
    touch(ag)
    return success_object(ser_agreement(ag))


@bp.get("/airport/airline_agreements/<agreement_id>/successors")
def list_successors(agreement_id):
    authenticate(READ_ROLES)
    ag = _get_agreement(agreement_id)
    items = [a for a in store.agreements.values() if a["superseded_by_id"] == ag["id"]]
    data, meta = paginate(items, ser_agreement)
    return success_list(data, meta)
