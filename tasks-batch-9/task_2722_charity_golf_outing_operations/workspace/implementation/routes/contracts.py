"""CourseContract endpoints (PRD 3.1)."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import CHARITY_TREASURER, COURSE_OPERATIONS, TOURNAMENT_DIRECTOR, auth
from envelope import created, ok, paginate
from errors import fail
from lookup import contract as get_contract
from lookup import outing as get_outing
from store import touch

bp = Blueprint("contracts", __name__)

READ_ROLES = (COURSE_OPERATIONS, TOURNAMENT_DIRECTOR, CHARITY_TREASURER)

CREATE_FIELDS = (
    "outing_id", "course_name", "rate_per_player_cents",
    "guaranteed_player_count", "fnb_minimum_cents", "fnb_per_player_cents",
    "course_rating", "slope_rating", "par", "tee_interval_minutes",
    "cart_allowance_count", "rain_date_terms", "rain_date_credit_pct",
    "cancellation_notice_days",
)

RATING_TERMS = ("slope_rating", "course_rating", "par")
MONEY_TERMS = ("rate_per_player_cents", "fnb_minimum_cents",
               "fnb_per_player_cents", "guaranteed_player_count")
AMEND_TERMS = ("rate_per_player_cents", "fnb_minimum_cents",
               "fnb_per_player_cents", "guaranteed_player_count",
               "slope_rating", "course_rating", "par", "tee_interval_minutes",
               "cart_allowance_count", "rain_date_terms",
               "rain_date_credit_pct", "cancellation_notice_days")


@bp.post("/outing-ops/contracts")
def create_contract():
    auth((COURSE_OPERATIONS,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    fields = {
        "outing_id": outing_id,
        "course_name": validate.req_str(body, "course_name"),
        "rate_per_player_cents": validate.req_money(body, "rate_per_player_cents"),
        "guaranteed_player_count": validate.opt_int(
            body, "guaranteed_player_count", default=72, minimum=0),
        "fnb_minimum_cents": validate.opt_money(body, "fnb_minimum_cents", 0),
        "fnb_per_player_cents": validate.opt_money(body, "fnb_per_player_cents", 4500),
        "course_rating": validate.opt_number(body, "course_rating", default=71.4),
        "slope_rating": validate.opt_number(body, "slope_rating", default=128),
        "par": validate.opt_int(body, "par", default=72),
        "tee_interval_minutes": validate.opt_int(
            body, "tee_interval_minutes", default=10, minimum=1),
        "cart_allowance_count": validate.opt_int(
            body, "cart_allowance_count", default=40, minimum=1),
        "rain_date_terms": validate.opt_enum(
            body, "rain_date_terms", enums.RAIN_DATE_TERMS, default="NONE"),
        "rain_date_credit_pct": validate.opt_number(
            body, "rain_date_credit_pct", default=0.5, minimum=0, maximum=1),
        "cancellation_notice_days": validate.opt_int(
            body, "cancellation_notice_days", default=30, minimum=0),
        "status": "DRAFT",
        "signed_at": None,
        "amendment_count": 0,
        "rain_credit_cents": 0,
        "settled_charge_cents": 0,
    }
    get_outing(outing_id)
    if derive.contract_of(outing_id) is not None:
        fail("ERR_CONTRACT_ALREADY_EXISTS",
             "The outing already carries a course contract.")
    row = store.new_row("CourseContract", fields)
    return created(serial.dump(row))


@bp.get("/outing-ops/contracts/<row_id>")
def read_contract(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_contract(row_id)))


@bp.get("/outing-ops/contracts")
def list_contracts():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    rows = store.sorted_rows(store.contracts.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/contracts/<row_id>/lifecycle")
def contract_lifecycle(row_id):
    auth((COURSE_OPERATIONS,))
    body = validate.body()
    validate.only_fields(body, ("action", "void_reason") + AMEND_TERMS)
    action = validate.req_enum(body, "action", enums.CONTRACT_ACTIONS)
    validate.opt_str(body, "void_reason")
    terms = _amend_terms(body)
    contract = get_contract(row_id)
    outing = store.outings.get(contract["outing_id"])
    if action == "SIGN":
        if contract["status"] != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "SIGN is not an edge out of %s." % contract["status"])
        contract["status"] = "SIGNED"
        contract["signed_at"] = store.now_iso()
    elif action == "AMEND":
        _amend(contract, outing, terms)
    else:
        _void(contract, outing, body)
    touch(contract)
    return ok(serial.dump(contract))


def _amend_terms(body):
    supplied = {}
    if "rate_per_player_cents" in body:
        supplied["rate_per_player_cents"] = validate.req_money(
            body, "rate_per_player_cents")
    if "fnb_minimum_cents" in body:
        supplied["fnb_minimum_cents"] = validate.req_money(body, "fnb_minimum_cents")
    if "fnb_per_player_cents" in body:
        supplied["fnb_per_player_cents"] = validate.req_money(
            body, "fnb_per_player_cents")
    if "guaranteed_player_count" in body:
        supplied["guaranteed_player_count"] = validate.req_int(
            body, "guaranteed_player_count", minimum=0)
    if "slope_rating" in body:
        supplied["slope_rating"] = validate.req_number(body, "slope_rating")
    if "course_rating" in body:
        supplied["course_rating"] = validate.req_number(body, "course_rating")
    if "par" in body:
        supplied["par"] = validate.req_int(body, "par")
    if "tee_interval_minutes" in body:
        supplied["tee_interval_minutes"] = validate.req_int(
            body, "tee_interval_minutes", minimum=1)
    if "cart_allowance_count" in body:
        supplied["cart_allowance_count"] = validate.req_int(
            body, "cart_allowance_count", minimum=1)
    if "rain_date_terms" in body:
        supplied["rain_date_terms"] = validate.req_enum(
            body, "rain_date_terms", enums.RAIN_DATE_TERMS)
    if "rain_date_credit_pct" in body:
        supplied["rain_date_credit_pct"] = validate.req_number(
            body, "rain_date_credit_pct", minimum=0, maximum=1)
    if "cancellation_notice_days" in body:
        supplied["cancellation_notice_days"] = validate.req_int(
            body, "cancellation_notice_days", minimum=0)
    return supplied


def _amend(contract, outing, terms):
    status = contract["status"]
    if status == "SIGNED":
        if outing is not None and outing["play_status"] in ("SCORED", "CANCELLED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The outing's play dimension has reached %s."
                 % outing["play_status"])
        contract["status"] = "AMENDED"
    elif status == "AMENDED":
        contract["status"] = "SIGNED"
    else:
        fail("ERR_INVALID_STATE_TRANSITION",
             "AMEND is not an edge out of %s." % status)
    ratings_changed = False
    money_changed = False
    for name, value in terms.items():
        if contract[name] != value:
            if name in RATING_TERMS:
                ratings_changed = True
            if name in MONEY_TERMS:
                money_changed = True
        contract[name] = value
    contract["amendment_count"] = contract["amendment_count"] + 1
    if outing is not None:
        if ratings_changed:
            derive.rating_cascade(outing)
        if money_changed:
            derive.run_rollup(outing)


def _void(contract, outing, body):
    status = contract["status"]
    if status not in ("DRAFT", "SIGNED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "VOID is not an edge out of %s." % status)
    for reg in derive.regs_of(contract["outing_id"]):
        if reg["status"] in derive.REVENUE_STATES:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Registration %s is revenue recognized." % reg["id"])
    if status == "SIGNED":
        deadline = store.parse_ts(outing["scheduled_date"]) - store.days(
            contract["cancellation_notice_days"])
        if store.now_dt() >= deadline:
            fail("ERR_CANCELLATION_NOTICE_VIOLATION",
                 "The cancellation notice window has opened.")
    contract["status"] = "VOIDED"
    if status == "SIGNED" and outing is not None:
        if outing["play_status"] in ("DRAFT", "OPEN"):
            outing["play_status"] = "CANCELLED"
            touch(outing)
