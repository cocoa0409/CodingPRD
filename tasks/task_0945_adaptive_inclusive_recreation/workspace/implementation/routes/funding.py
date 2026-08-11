"""Funding sources, the funding selector and scholarship awards."""

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import (
    Body,
    Refs,
    check_transition,
    check_version,
    endpoint,
    pagination,
    paginate,
    resolve_one,
)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, sort_rows, touch

bp = Blueprint("funding", __name__)

AWARD_TERMINALS = ("DISBURSED", "RELEASED", "LAPSED_NO_FUNDS")


def _sod_award(context):
    return db.get("scholarship_awards", context.params.get("award_id"))


# ---------------------------------------------------------------------------
# funding sources
# ---------------------------------------------------------------------------

@bp.route("/recreation/funding-sources", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def create_source(context):
    period_id = context.body.get("operating_period_id")
    period = None
    if isinstance(period_id, str):
        period = resolve_one("period", period_id)
    body = Body(context.body)
    body.req_string("operating_period_id")
    name = body.req_string("name")
    source_kind = body.req_enum("source_kind", enums.SOURCE_KINDS)
    priority_rank = body.req_int("priority_rank", minimum=1)
    award_mode = body.req_enum("award_mode", enums.AWARD_MODES)
    award_pct_bp = body.opt_int("award_pct_bp", 0, minimum=0, maximum=10000)
    flat_award_cents = body.opt_int("flat_award_cents", 0, minimum=0)
    total_budget_cents = body.req_int("total_budget_cents", minimum=0)
    body.check_enums()
    if period is None:
        period = resolve_one("period", period_id)

    row = insert(
        "funding_sources",
        {
            "operating_period_id": period["id"],
            "name": name,
            "source_kind": source_kind,
            "priority_rank": priority_rank,
            "award_mode": award_mode,
            "award_pct_bp": award_pct_bp,
            "flat_award_cents": flat_award_cents,
            "total_budget_cents": total_budget_cents,
            "available_cents": total_budget_cents,
            "encumbered_cents": 0,
            "disbursed_cents": 0,
            "status": "OPEN",
        },
    )
    return ok(serial.dump(row), 201)


@bp.route("/recreation/funding-sources", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_sources(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("funding_sources"))
    period_id = context.q("operating_period_id")
    source_kind = context.q("source_kind")
    status = context.q("status")
    if period_id is not None:
        rows = [r for r in rows if r["operating_period_id"] == period_id]
    if source_kind is not None:
        rows = [r for r in rows if r["source_kind"] == source_kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/funding-sources/<source_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_source(context, source_id):
    return ok(serial.dump(resolve_one("source", source_id)))


@bp.route("/recreation/funding-sources/<source_id>/close", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def close_source(context, source_id):
    source = resolve_one("source", source_id)
    check_transition(source["status"], ("OPEN", "EXHAUSTED"), ("CLOSED",))
    source["status"] = "CLOSED"
    touch(source)
    engine.lapse_proposed_awards(source)
    return ok(serial.dump(source))


# ---------------------------------------------------------------------------
# the funding selector, exposed as a read
# ---------------------------------------------------------------------------

@bp.route("/recreation/funding-selection", methods=["GET"])
@endpoint(roles=("FundingOfficer", "ProgramAdmin"))
def funding_selection(context):
    enrollment = resolve_one("enrollment", context.q("enrollment_id"))
    source = calc.funding_source_selector()
    if source is None:
        raise ApiError("ERR_INSUFFICIENT_FUNDS")
    charge = L.charge_of_enrollment(enrollment)
    net_need = charge["program_fee_cents"] if charge else 0
    return ok(
        {
            "enrollment_id": enrollment["id"],
            "funding_source_id": source["id"],
            "funding_source_version": source["version"],
            "award_mode": source["award_mode"],
            "net_need_cents": net_need,
            "projected_award_cents": calc.scholarship_award_amount_cents(net_need, source, None),
        }
    )


# ---------------------------------------------------------------------------
# scholarship awards
# ---------------------------------------------------------------------------

@bp.route("/recreation/scholarship-awards", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def create_award(context):
    raw = context.body
    refs = Refs()
    if isinstance(raw.get("enrollment_id"), str):
        refs.add("enrollment", raw["enrollment_id"], path=False)
    if isinstance(raw.get("funding_source_id"), str):
        refs.add("source", raw["funding_source_id"], path=False)
    refs.resolve()

    body = Body(raw)
    enrollment_id = body.req_string("enrollment_id")
    named_source_id = body.opt_string("funding_source_id", None)
    expected_version = body.req_int("expected_funding_source_version")
    requested_amount_cents = body.opt_int("requested_amount_cents", None)
    body.check_enums()

    enrollment = resolve_one("enrollment", enrollment_id)
    source = None
    if named_source_id is not None:
        source = resolve_one("source", named_source_id)
    else:
        source = calc.funding_source_selector()

    if source is not None:
        check_version(expected_version, source)                        # rung 25

    if source is not None:                                             # rung 56
        period = L.period_of_source(source)
        if source["status"] == "CLOSED" or period is None or period["status"] != "OPEN":
            raise ApiError("ERR_FUNDING_PERIOD_CLOSED")

    charge = L.charge_of_enrollment(enrollment)
    net_need = charge["program_fee_cents"] if charge else 0
    if source is None:                                                 # rung 57
        raise ApiError("ERR_INSUFFICIENT_FUNDS")
    amount = calc.scholarship_award_amount_cents(net_need, source, requested_amount_cents)
    if amount < 1 or source["available_cents"] < amount:
        raise ApiError("ERR_INSUFFICIENT_FUNDS")
    if requested_amount_cents is not None and requested_amount_cents > net_need:  # rung 58
        raise ApiError("ERR_AWARD_EXCEEDS_NEED")

    row = insert(
        "scholarship_awards",
        {
            "enrollment_id": enrollment["id"],
            "funding_source_id": source["id"],
            "awarded_by_user_id": context.user_id,
            "disbursed_by_user_id": None,
            "amount_cents": amount,
            "encumbered_cents": 0,
            "disbursed_cents": 0,
            "status": "PROPOSED",
        },
    )
    touch(source)
    if enrollment["funding_status"] in ("UNFUNDED", "RELEASED") and enrollment[
        "enrollment_status"
    ] not in ("WITHDRAWN", "DENIED", "ATTENDED", "NO_SHOW"):
        enrollment["funding_status"] = "QUOTED"
        touch(enrollment)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/scholarship-awards", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_awards(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("scholarship_awards"))
    enrollment_id = context.q("enrollment_id")
    source_id = context.q("funding_source_id")
    status = context.q("status")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if source_id is not None:
        rows = [r for r in rows if r["funding_source_id"] == source_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/scholarship-awards/<award_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_award(context, award_id):
    return ok(serial.dump(resolve_one("award", award_id)))


@bp.route("/recreation/scholarship-awards/<award_id>/encumber", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def encumber_award(context, award_id):
    award = resolve_one("award", award_id)
    check_transition(award["status"], ("PROPOSED",), AWARD_TERMINALS)
    source = L.source_of_award(award)
    period = L.period_of_source(source)
    if source["status"] == "CLOSED" or period is None or period["status"] != "OPEN":
        raise ApiError("ERR_FUNDING_PERIOD_CLOSED")
    if source["available_cents"] < award["amount_cents"] or award["amount_cents"] < 1:
        raise ApiError("ERR_INSUFFICIENT_FUNDS")
    engine.encumber_award(award)
    return ok(serial.dump(award))


@bp.route("/recreation/scholarship-awards/<award_id>/disburse", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True, sod=_sod_award)
def disburse_award(context, award_id):
    award = resolve_one("award", award_id)
    body = Body(context.body)
    amount_cents = body.req_int("amount_cents")
    body.check_enums()
    check_transition(award["status"], ("ENCUMBERED", "PARTIALLY_DISBURSED"), AWARD_TERMINALS)
    outstanding = award["encumbered_cents"] - award["disbursed_cents"]
    if amount_cents < 1 or amount_cents > outstanding:
        raise ApiError("ERR_DISBURSEMENT_EXCEEDS_ENCUMBRANCE")

    source = L.source_of_award(award)
    award["disbursed_cents"] += amount_cents
    award["disbursed_by_user_id"] = context.user_id
    award["status"] = (
        "DISBURSED" if award["disbursed_cents"] == award["encumbered_cents"] else "PARTIALLY_DISBURSED"
    )
    touch(award)
    source["encumbered_cents"] -= amount_cents
    source["disbursed_cents"] += amount_cents
    touch(source)
    enrollment = L.enrollment_of_award(award)
    if award["status"] == "DISBURSED" and enrollment is not None:
        if enrollment["funding_status"] == "ENCUMBERED":
            enrollment["funding_status"] = "DISBURSED"
            touch(enrollment)
    return ok(serial.dump(award))


@bp.route("/recreation/scholarship-awards/<award_id>/release", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def release_award(context, award_id):
    award = resolve_one("award", award_id)
    check_transition(award["status"], ("ENCUMBERED", "PARTIALLY_DISBURSED"), AWARD_TERMINALS)
    engine.release_award(award)
    return ok(serial.dump(award))
