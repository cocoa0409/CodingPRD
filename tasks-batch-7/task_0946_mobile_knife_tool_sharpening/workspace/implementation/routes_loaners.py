"""Loaner inventory, issue and rotation."""

import datetime

from flask import Blueprint

import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import (
    LOANER_DEFAULT_CYCLE_CEILING,
    LOANER_DUE_DAYS,
    LOANER_GRADES,
    LOANER_ISSUE_STATUSES,
    LOANER_UNIT_STATUSES,
)
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("loaners", __name__)

UNIT_SPEC = ladder.Spec(
    required=[("item_class_spec_id", "string"), ("grade", "string")],
    optional=[("cycle_ceiling", "integer")],
    enums={"grade": LOANER_GRADES},
    ranges={"cycle_ceiling": (1, None)},
)

ISSUE_SPEC = ladder.Spec(
    required=[
        ("service_request_id", "string"),
        ("item_class_spec_id", "string"),
        ("requested_grade", "string"),
    ],
    enums={"requested_grade": LOANER_GRADES},
)

RETURN_SPEC = ladder.Spec(optional=[("damage_reported", "boolean")])


@bp.route("/sharpening/loaner-units", methods=["POST"])
def create_unit():
    ctx = ladder.begin("PlatformAdmin")
    UNIT_SPEC.validate(ctx.body)
    spec = ladder.must_exist(
        db.item_class_specs, ctx.body["item_class_spec_id"], "ItemClassSpec"
    )
    # Rung 29.
    if not spec["loaner_eligible"]:
        raise ApiError("ERR_LOANER_NOT_ELIGIBLE")
    row = stamp_new(
        {
            "item_class_spec_id": spec["id"],
            "grade": ctx.body["grade"],
            "cycle_ceiling": ctx.body.get("cycle_ceiling", LOANER_DEFAULT_CYCLE_CEILING),
            "cycle_count": 0,
            "damage_reported": False,
            "status": "IN_STOCK",
        }
    )
    db.loaner_units[row["id"]] = row
    return envelope.created(ser.loaner_unit(row))


@bp.route("/sharpening/loaner-units/<id>", methods=["GET"])
def get_unit(id):
    ctx = ladder.begin("PlatformAdmin", "Technician")
    row = ladder.must_exist(db.loaner_units, id, "LoanerUnit")
    services.acting_technician(ctx)
    return envelope.ok(ser.loaner_unit(row))


@bp.route("/sharpening/loaner-units", methods=["GET"])
def list_units():
    ctx = ladder.begin("PlatformAdmin", "Technician")
    ladder.check_query_enums(
        ctx.query, {"grade": LOANER_GRADES, "status": LOANER_UNIT_STATUSES}
    )
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.loaner_units.values())
    for field in ("item_class_spec_id", "grade", "status"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.loaner_unit(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/loaner-issues
# ---------------------------------------------------------------------------
@bp.route("/sharpening/loaner-issues", methods=["POST"])
def create_issue():
    ctx = ladder.begin("Technician")
    ISSUE_SPEC.validate(ctx.body)
    services.acting_technician(ctx)
    loose_request = db.service_requests.get(ctx.body["service_request_id"])
    services.account_active(
        db.accounts.get(loose_request["account_id"]) if loose_request else None
    )
    request_row = ladder.must_exist(
        db.service_requests, ctx.body["service_request_id"], "ServiceRequest"
    )
    spec = ladder.must_exist(
        db.item_class_specs, ctx.body["item_class_spec_id"], "ItemClassSpec"
    )
    account = db.accounts.get(request_row["account_id"])
    # Rung 11.
    services.credit_gate(account)
    # Rung 29.
    if not spec["loaner_eligible"]:
        raise ApiError("ERR_LOANER_NOT_ELIGIBLE")
    # Rung 51.
    unit = services.select_loaner_unit(spec["id"], ctx.body["requested_grade"])

    issued_at = clockmod.now()
    row = stamp_new(
        {
            "loaner_unit_id": unit["id"],
            "service_request_id": request_row["id"],
            "requested_grade": ctx.body["requested_grade"],
            "issued_at": issued_at,
            "due_at": issued_at + datetime.timedelta(days=LOANER_DUE_DAYS),
            "returned_at": None,
            "delay_attribution": None,
            "late_fee_cents": 0,
            "substituted": unit["grade"] != ctx.body["requested_grade"],
            "status": "OPEN",
        }
    )
    db.loaner_issues[row["id"]] = row
    unit["status"] = "ISSUED"
    touch(unit)
    return envelope.created(ser.loaner_issue(row))


@bp.route("/sharpening/loaner-issues/<id>", methods=["GET"])
def get_issue(id):
    ctx = ladder.begin("PlatformAdmin", "Technician", "AccountOwner")
    row = ladder.must_exist(db.loaner_issues, id, "LoanerIssue")
    request_row = db.service_requests.get(row["service_request_id"])
    services.own_account(ctx, request_row["account_id"] if request_row else None)
    services.acting_technician(ctx)
    return envelope.ok(ser.loaner_issue(row))


@bp.route("/sharpening/loaner-issues", methods=["GET"])
def list_issues():
    ctx = ladder.begin("PlatformAdmin", "Technician", "AccountOwner")
    ladder.check_query_enums(ctx.query, {"status": LOANER_ISSUE_STATUSES})
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.loaner_issues.values())
    for field in ("loaner_unit_id", "service_request_id", "status"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.loaner_issue(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/loaner-issues/{id}/return
# ---------------------------------------------------------------------------
@bp.route("/sharpening/loaner-issues/<id>/return", methods=["POST"])
def return_issue(id):
    ctx = ladder.begin("Technician")
    row = ladder.must_exist(db.loaner_issues, id, "LoanerIssue")
    RETURN_SPEC.validate(ctx.body)
    services.acting_technician(ctx)
    request_row = db.service_requests.get(row["service_request_id"])
    services.account_active(
        db.accounts.get(request_row["account_id"]) if request_row else None
    )
    if row["status"] == "RETURNED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "The loaner issue is not OPEN.")

    services.close_loaner_issue(row, damage_reported=bool(ctx.body.get("damage_reported", False)))
    return envelope.ok(ser.loaner_issue(row))
