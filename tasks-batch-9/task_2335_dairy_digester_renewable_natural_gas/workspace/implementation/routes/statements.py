from flask import Blueprint, g

import config
from db import db
from errors import fail
from middleware import endpoint, body
from response import created, ok
from routes.common import get_facility, get_statement, paged_list, resolve_refs
from services import cascade, derive
from validation import date_of, require_range

bp = Blueprint("statements", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "DairyPartner",
              "FinanceController", "ProgramAdministrator"]


@bp.post("/revenue-statements")
@endpoint(["FinanceController"])
def create_statement():
    b = body(allow_version_fields=("expected_facility_version",))
    (facility,) = resolve_refs(b, (("facility_id", get_facility),))
    start = b.date("period_start_date")
    end = b.date("period_end_date")
    gas_revenue = b.integer("gas_revenue_cents", ge=0)
    expected = b.integer("expected_facility_version")
    require_range(start, end)
    if expected != facility["version"]:
        fail("ERR_STALE_VERSION", "The facility has moved since it was last read.")

    same_facility = [s for s in db.statements.values()
                     if s["facility_id"] == facility["id"]]
    for other in same_facility:
        if other["status"] not in ("APPROVED", "PAID"):
            continue
        if date_of(other["period_start_date"]) <= end and \
                date_of(other["period_end_date"]) >= start:
            fail("ERR_STATEMENT_PERIOD_OVERLAP",
                 "An approved or paid statement already covers this period.")

    row = db.new_row({
        "facility_id": facility["id"],
        "period_start_date": b.raw["period_start_date"],
        "period_end_date": b.raw["period_end_date"],
        "gas_revenue_cents": gas_revenue,
        "credit_revenue_cents": 0,
        "gross_revenue_cents": 0,
        "management_fee_rate": None,
        "management_fee_cents": 0,
        "after_fee_cents": 0,
        "reserve_sweep_cents": 0,
        "net_distributable_cents": 0,
        "share_lines": [],
        "total_dairy_share_cents": 0,
        "retained_cents": 0,
        "dscr_at_close": None,
        "superseded_by_statement_id": None,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "paid_by_user_id": None,
    })
    db.statements[row["id"]] = row

    stale = [s for s in same_facility
             if s["status"] == "DRAFT"
             and date_of(s["period_start_date"]) <= end
             and date_of(s["period_end_date"]) >= start]
    stale.sort(key=lambda r: (r["_created"], r["_seq"]))
    for old in stale:
        old["status"] = "SUPERSEDED"
        old["superseded_by_statement_id"] = row["id"]
        db.touch(old)

    cascade.compute_statement(row)
    db.touch(facility)
    if derive.rederive_dscr_from_driver(facility):
        db.touch(facility)
    return created(derive.ser_statement(row))


@bp.get("/revenue-statements")
@endpoint(READ_ROLES)
def list_statements():
    return paged_list(db.statements, derive.ser_statement,
                      ("facility_id", "status", "superseded_by_statement_id"))


@bp.get("/revenue-statements/<statement_id>")
@endpoint(READ_ROLES)
def read_statement(statement_id):
    return ok(derive.ser_statement(get_statement(statement_id)))


@bp.post("/revenue-statements/<statement_id>/approve")
@endpoint(["FinanceController"])
def approve_statement(statement_id):
    statement = get_statement(statement_id)
    b = body()
    b.string("approval_note", required=False)
    facility = db.facilities[statement["facility_id"]]

    if statement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT statement may be approved.")
    if facility["distribution_posture"] == "LOCKED":
        fail("ERR_DISTRIBUTION_LOCKED", "Distributions are locked on this facility.")
    if statement["total_dairy_share_cents"] > statement["net_distributable_cents"]:
        fail("ERR_SHARE_EXCEEDS_DISTRIBUTABLE",
             "The dairy share total exceeds the distributable pool.")

    statement["status"] = "APPROVED"
    statement["approved_by_user_id"] = g.user_id
    db.touch(statement)
    return ok(derive.ser_statement(statement))


@bp.post("/revenue-statements/<statement_id>/pay")
@endpoint(["FinanceController"])
def pay_statement(statement_id):
    statement = get_statement(statement_id)
    b = body()
    b.string("payment_reference")
    facility = db.facilities[statement["facility_id"]]

    if statement["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED statement may be paid.")
    if facility["distribution_posture"] == "LOCKED":
        fail("ERR_DISTRIBUTION_LOCKED", "Distributions are locked on this facility.")
    if g.user_id == statement["approved_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The payer must differ from the approver.")
    if facility["distribution_posture"] == "RESTRICTED" and \
            statement["net_distributable_cents"] > config.RESTRICTED_PAY_CAP_CENTS:
        fail("ERR_DISTRIBUTION_RESTRICTED",
             "The distributable amount exceeds the restricted payment cap.")

    statement["status"] = "PAID"
    statement["paid_by_user_id"] = g.user_id
    db.touch(statement)
    facility["reserve_balance_cents"] += int(statement["reserve_sweep_cents"])
    db.touch(facility)
    return ok(derive.ser_statement(statement))


@bp.post("/revenue-statements/<statement_id>/claw-back")
@endpoint(["FinanceController"])
def claw_back_statement(statement_id):
    statement = get_statement(statement_id)
    b = body()
    b.string("claw_back_reason")
    facility = db.facilities[statement["facility_id"]]

    if statement["status"] != "PAID":
        fail("ERR_INVALID_STATE", "Only a PAID statement may be clawed back.")

    statement["status"] = "CLAWED_BACK"
    db.touch(statement)
    facility["reserve_balance_cents"] -= int(statement["reserve_sweep_cents"])
    db.touch(facility)
    if derive.rederive_dscr_from_driver(facility):
        db.touch(facility)
    return ok(derive.ser_statement(statement))
