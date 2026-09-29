"""Unfair labor practice charges: the blocking hold, determinations and settlements."""

from flask import Blueprint

import auth
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("charges", __name__)

BASE = "/labor-relations/ulp-charges"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


def _set_notice_posting(petition, anchor, days):
    if petition is None or anchor is None or days is None:
        return
    petition["notice_posting_end_at"] = clockutil.fmt_dt(clockutil.add_days(anchor, days))


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.UNION, auth.DIRECTOR])
def create_charge(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    related_objection_id = schema.reference("related_objection_id", required=False)
    charging_party = schema.enum("charging_party", common.CHARGING_PARTIES)
    charged_party = schema.enum("charged_party", common.CHARGED_PARTIES)
    section_code = schema.enum("section_code", common.SECTION_CODES)
    allegation_summary = schema.string("allegation_summary")
    conduct_occurred_at = schema.datetime("conduct_occurred_at")
    blocking_requested = schema.boolean("blocking_requested", required=False, default=False)

    petition = gates.must_exist("petitions", petition_id)
    if related_objection_id is not None:
        objection = gates.must_exist("objections", related_objection_id)
        objected_round = store.get("election_rounds", objection["election_round_id"])
        if objected_round is not None:
            gates.require_same_petition(petition_id, objected_round["petition_id"])

    counted_blocking = bool(
        blocking_requested and petition["case_status"] not in ("DISMISSED", "CERTIFIED"))

    row = {
        "petition_id": petition_id,
        "related_objection_id": related_objection_id,
        "charging_party": charging_party,
        "charged_party": charged_party,
        "section_code": section_code,
        "allegation_summary": allegation_summary,
        "conduct_occurred_at": conduct_occurred_at,
        "blocking_requested": blocking_requested,
        "status": "FILED",
        "remedy_code": None,
        "settlement_type": None,
        "notice_posting_days": None,
        "filed_at": clockutil.now_dt_str(),
        "determined_at": None,
        "settled_at": None,
        "_counted_blocking": counted_blocking,
    }
    store.insert("ulp_charges", row)

    if counted_blocking:
        petition["blocking_charge_count"] += 1
        gates.blocking_charge_cascade(petition)
        store.touch(petition)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_charges(user_id, role):
    petition_id = validate.query_string("petition_id")
    related_objection_id = validate.query_string("related_objection_id")
    status = validate.query_enum("status", common.CHARGE_STATUSES)
    rows = store.ordered("ulp_charges")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if related_objection_id is not None:
        rows = [r for r in rows if r.get("related_objection_id") == related_objection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<cid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_charge(user_id, role, cid):
    return common.one(gates.must_exist("ulp_charges", cid))


@bp.route(BASE + "/<cid>/determine", methods=["POST"])
@auth.endpoint([auth.BOARD])
def determine_charge(user_id, role, cid):
    schema = validate.Schema(validate.body())
    determination = schema.enum("determination", common.DETERMINATIONS)
    remedy_code = schema.enum("remedy_code", common.REMEDY_CODES,
                              required=(determination == "MERIT"))
    notice_posting_days = schema.integer("notice_posting_days", required=False, minimum=0)

    charge = gates.must_exist("ulp_charges", cid)
    if charge["status"] != "FILED":
        raise ApiError("ERR_CHARGE_STATUS_INVALID",
                       "That charge has already been determined or settled.")

    petition = store.petition(charge["petition_id"])
    now = clockutil.now()
    charge["determined_at"] = clockutil.fmt_dt(now)
    if notice_posting_days is not None:
        charge["notice_posting_days"] = notice_posting_days

    if determination == "MERIT":
        charge["remedy_code"] = remedy_code
        charge["status"] = "MERIT_FOUND"
        store.touch(charge)
        # A merit finding never lowers blocking_charge_count: the hold survives to settlement.
        if remedy_code == "NOTICE_POSTING" and notice_posting_days is not None:
            _set_notice_posting(petition, now, notice_posting_days)
            store.touch(petition)
        return common.one(charge)

    charge["status"] = "DISMISSED"
    store.touch(charge)
    if charge["_counted_blocking"]:
        charge["_counted_blocking"] = False
        if petition["blocking_charge_count"] > 0:
            petition["blocking_charge_count"] -= 1
        gates.unblock_chain(petition)
        store.touch(petition)
    return common.one(charge)


@bp.route(BASE + "/<cid>/settle", methods=["POST"])
@auth.endpoint([auth.COUNSEL, auth.BOARD])
def settle_charge(user_id, role, cid):
    schema = validate.Schema(validate.body())
    settlement_type = schema.enum("settlement_type", common.SETTLEMENT_TYPES)
    notice_posting_days = schema.integer("notice_posting_days", required=False, minimum=0)

    charge = gates.must_exist("ulp_charges", cid)
    if charge["status"] not in ("FILED", "MERIT_FOUND"):
        raise ApiError("ERR_CHARGE_STATUS_INVALID",
                       "Only a filed or meritorious charge may be settled.")

    petition = store.petition(charge["petition_id"])
    now = clockutil.now()
    charge["settled_at"] = clockutil.fmt_dt(now)
    charge["settlement_type"] = settlement_type
    if notice_posting_days is not None:
        charge["notice_posting_days"] = notice_posting_days
    charge["status"] = "SETTLED"
    store.touch(charge)

    petition_touched = False
    if notice_posting_days is not None and notice_posting_days > 0:
        _set_notice_posting(petition, now, notice_posting_days)
        petition_touched = True
    if charge["_counted_blocking"]:
        charge["_counted_blocking"] = False
        if petition["blocking_charge_count"] > 0:
            petition["blocking_charge_count"] -= 1
        gates.unblock_chain(petition)
        petition_touched = True
    if petition_touched:
        store.touch(petition)
    return common.one(charge)
