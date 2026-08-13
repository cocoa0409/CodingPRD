"""Enrollment endpoints (create, read, activate, election, terminate,
deposits, ledger entries, tax lots, fees, transfers list, tax report)."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, PARTICIPANT, auth, check_ownership
from response import ok
from services import (
    ELECTIONS,
    ENROLLMENT_STATUSES,
    ENTRY_TYPES,
    FEE_TYPES,
    TRANSFER_STATUSES,
    add_fee,
    add_ledger_entry,
    add_tax_lot,
    election_payload,
    filter_enum,
    get_enrollment,
    get_plan,
    list_response,
    recompute_enrollment,
    ser_enrollment,
    ser_fee,
    ser_ledger_entry,
    ser_tax_lot,
    ser_transfer,
    stamp,
    tax_report,
    terminate_enrollment,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_pos_int,
    as_decimal,
    as_str,
    body,
    required,
    round4,
    round_cents,
)

bp = Blueprint("enrollments", __name__)


def _owning_participant(e, user_id, role):
    check_ownership(e["participant_id"], user_id, role)


@bp.post("/plans/<plan_id>/enrollments")
def create_enrollment(plan_id):
    user_id, role = auth(PARTICIPANT)
    plan = get_plan(plan_id)
    data = body()
    participant_id = as_str(required(data, "participant_id"), "participant_id")
    election = as_enum(required(data, "election"), "election", ELECTIONS)
    if participant_id != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Participant may only enroll themselves"
        )
    if DB["participants"].get(participant_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Participant not found")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    for e in DB["enrollments"].values():
        if (
            e["participant_id"] == participant_id
            and e["plan_id"] == plan_id
            and e["status"] in ("PENDING", "ACTIVE", "SUSPENDED")
        ):
            raise ApiError(
                "ERR_ALREADY_ENROLLED",
                409,
                "Participant already has a non-terminal enrollment in this plan",
            )
    reinvest_pct = election_payload(data, election)
    rec = {
        "id": new_id(),
        "participant_id": participant_id,
        "plan_id": plan_id,
        "status": "PENDING",
        "election": election,
        "reinvest_pct": reinvest_pct,
        "share_balance": Decimal("0"),
        "total_cost_basis_cents": 0,
        "terminated_at": None,
    }
    stamp(rec)
    DB["enrollments"][rec["id"]] = rec
    return ok(ser_enrollment(rec), status=201)


@bp.get("/plans/<plan_id>/enrollments")
def list_plan_enrollments(plan_id):
    auth(ADMIN)
    get_plan(plan_id)
    items = [e for e in DB["enrollments"].values() if e["plan_id"] == plan_id]
    items = filter_enum(
        items, request.args.get("status"), "status", ENROLLMENT_STATUSES, "status"
    )
    return list_response(items, ser_enrollment)


@bp.get("/enrollments/<eid>")
def get_one_enrollment(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    return ok(ser_enrollment(e))


@bp.post("/enrollments/<eid>/activate")
def activate_enrollment(eid):
    auth(ADMIN)
    e = get_enrollment(eid)
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not PENDING")
    plan = get_plan(e["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    e["status"] = "ACTIVE"
    add_fee(
        e["id"], "ENROLLMENT", plan["enrollment_fee_cents"], "ACTIVATION",
        e["id"],
    )
    touch(e)
    return ok(ser_enrollment(e))


@bp.patch("/enrollments/<eid>/election")
def change_election(eid):
    user_id, role = auth(PARTICIPANT)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    data = body()
    expected = as_int(
        required(data, "expected_enrollment_version"),
        "expected_enrollment_version",
    )
    election = as_enum(required(data, "election"), "election", ELECTIONS)
    # OCC guard (PRD section 2.7).
    if expected != e["version"]:
        raise ApiError(
            "ERR_STALE_ENROLLMENT_VERSION",
            412,
            "expected_enrollment_version does not match the enrollment's "
            "current version",
        )
    if e["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE"
        )
    reinvest_pct = election_payload(data, election)
    e["election"] = election
    e["reinvest_pct"] = reinvest_pct
    touch(e)
    return ok(ser_enrollment(e))


@bp.post("/enrollments/<eid>/terminate")
def terminate_enrollment_route(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    data = body()
    sale_price = as_pos_int(
        required(data, "sale_price_cents"), "sale_price_cents"
    )
    if e["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Enrollment is not ACTIVE or SUSPENDED"
        )
    terminate_enrollment(e, sale_price)
    return ok(ser_enrollment(e))


@bp.post("/enrollments/<eid>/deposits")
def create_deposit(eid):
    auth(ADMIN)
    e = get_enrollment(eid)
    data = body()
    qty = round4(as_decimal(required(data, "quantity"), "quantity"))
    if qty <= 0:
        raise ApiError("ERR_VALIDATION", 400, "quantity must be > 0")
    cost = as_pos_int(
        required(data, "cost_per_share_cents"), "cost_per_share_cents"
    )
    if e["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE"
        )
    entry = add_ledger_entry(e["id"], "INITIAL", qty, cost, None, "DEPOSIT", e["id"])
    add_tax_lot(
        e["id"], qty, cost, round_cents(qty * Decimal(cost)), "INITIAL"
    )
    recompute_enrollment(e)
    touch(e)
    return ok(ser_ledger_entry(entry), status=201)


@bp.get("/enrollments/<eid>/ledger-entries")
def list_ledger_entries(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    items = [
        x for x in DB["ledger_entries"].values() if x["enrollment_id"] == eid
    ]
    items = filter_enum(
        items, request.args.get("entry_type"), "entry_type", ENTRY_TYPES,
        "entry_type",
    )
    return list_response(items, ser_ledger_entry)


@bp.get("/enrollments/<eid>/tax-lots")
def list_tax_lots(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    items = [l for l in DB["tax_lots"].values() if l["enrollment_id"] == eid]
    return list_response(items, ser_tax_lot)


@bp.get("/enrollments/<eid>/fees")
def list_fees(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    items = [f for f in DB["fee_assessments"].values() if f["enrollment_id"] == eid]
    items = filter_enum(
        items, request.args.get("fee_type"), "fee_type", FEE_TYPES, "fee_type"
    )
    return list_response(items, ser_fee)


@bp.get("/enrollments/<eid>/transfers")
def list_enrollment_transfers(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    items = [
        t for t in DB["transfers"].values() if t["source_enrollment_id"] == eid
    ]
    items = filter_enum(
        items, request.args.get("status"), "status", TRANSFER_STATUSES, "status"
    )
    return list_response(items, ser_transfer)


@bp.get("/enrollments/<eid>/tax-report")
def get_tax_report(eid):
    user_id, role = auth(ANY_ROLE)
    e = get_enrollment(eid)
    _owning_participant(e, user_id, role)
    raw_year = request.args.get("year")
    if raw_year is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required parameter: year")
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "year must be an integer")
    return ok(tax_report(e, year))
