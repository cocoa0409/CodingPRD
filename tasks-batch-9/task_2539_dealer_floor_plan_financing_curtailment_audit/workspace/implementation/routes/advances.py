"""Funding advances: the request, the disbursement and its two terminal
compensations (PRD 3.3), plus the ladder materialisation of PRD 3.4."""

from flask import Blueprint, g

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import calc, ledger, serial, spec

bp = Blueprint("advances", __name__)


def _line_occ(line, data):
    expected = validate.req_int(data, "expected_credit_line_version", minimum=0)
    if expected != int(line["version"]):
        raise ApiError(
            "ERR_STALE_CREDIT_LINE_VERSION",
            "expected_credit_line_version %s does not match the credit line." % expected,
        )


def _materialise_ladder(unit, line):
    """One SCHEDULED obligation per non-zero rung, age_days_from ascending."""
    tiers = ledger.unit_tiers(line["id"], unit["inventory_class"])
    floored_at = db.parse_instant(unit["floored_at"])
    created = []
    for tier, projected in calc.forward_projected_schedule(
        int(unit["advance_amount_cents"]), tiers
    ):
        created.append(
            db.insert(
                "curtailment_obligations",
                {
                    "unit_id": unit["id"],
                    "dealer_id": unit["dealer_id"],
                    "supersedes_obligation_id": None,
                    "status": "SCHEDULED",
                    "tier_age_days_from": int(tier["age_days_from"]),
                    "tier_cumulative_paydown_bps": int(tier["cumulative_paydown_bps"]),
                    "due_date": db.fmt_instant(
                        db.add_days(floored_at, int(tier["age_days_from"]))
                    ),
                    "projected_principal_cents": projected,
                    "required_principal_cents": 0,
                    "late_fee_cents": 0,
                    "total_amount_due_cents": 0,
                    "principal_paid_cents": 0,
                    "fee_paid_cents": 0,
                    "became_due_at": None,
                    "became_delinquent_at": None,
                    "extension_days_applied": 0,
                },
            )
        )
    return created


@bp.route("/floorplan/units/<unit_id>/funding-advances", methods=["POST"])
def request_advance(unit_id):
    middleware.require(middleware.DEALER_PRINCIPAL)
    unit = lookup.unit(unit_id)
    middleware.guard_owned(unit)
    data = validate.body()
    requested = validate.req_int(data, "requested_amount_cents", minimum=1)
    invoice_reference = validate.req_str(data, "dealer_invoice_reference")

    line = ledger.unit_line(unit)
    dealer = db.get("dealers", unit["dealer_id"])
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_NOT_ACTIVE")
    if unit["funding_status"] != "REGISTERED":
        raise ApiError("ERR_UNIT_NOT_FLOORED")
    live = [
        a
        for a in db.rows("funding_advances")
        if a["unit_id"] == unit["id"] and a["status"] in ("REQUESTED", "FUNDED")
    ]
    if live:
        raise ApiError("ERR_UNIT_NOT_FLOORED", "The unit already has a live funding advance.")
    if unit["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_UNIT_INELIGIBLE")

    advance = db.insert(
        "funding_advances",
        {
            "unit_id": unit["id"],
            "credit_line_id": unit["credit_line_id"],
            "status": "REQUESTED",
            "requested_amount_cents": requested,
            "approved_advance_amount_cents": 0,
            "effective_advance_rate_bps": 0,
            "rate_adjustment_codes": [],
            "invoice_age_days_at_funding": None,
            "dealer_invoice_reference": invoice_reference,
            "disbursement_reference": None,
            "funded_at": None,
            "funded_by_user_id": None,
            "reason_code": None,
        },
    )
    unit["funding_status"] = "PENDING_FUNDING"
    db.touch(unit)
    return response.created(serial.advance(advance))


@bp.route("/floorplan/funding-advances/<advance_id>/fund", methods=["POST"])
def fund_advance(advance_id):
    user_id, _role = middleware.require(middleware.CREDIT_OFFICER)
    advance = lookup.advance(advance_id)
    data = validate.body()
    disbursement_reference = validate.req_str(data, "disbursement_reference")
    line = db.get("credit_lines", advance["credit_line_id"])
    _line_occ(line, data)

    unit = db.get("inventory_units", advance["unit_id"])
    dealer = db.get("dealers", unit["dealer_id"])
    if advance["status"] != "REQUESTED":
        raise ApiError("ERR_ADVANCE_NOT_PENDING")
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_NOT_ACTIVE")
    if unit["funding_status"] != "PENDING_FUNDING":
        raise ApiError("ERR_UNIT_NOT_FLOORED")
    if unit["title_custody_status"] != "LENDER_HELD":
        raise ApiError("ERR_TITLE_NOT_LENDER_HELD")
    if unit["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_UNIT_INELIGIBLE")

    priced = calc.unit_advance_amount(unit, line, db.now())
    if priced["invoice_age_days"] > spec.MAX_INVOICE_AGE_DAYS:
        raise ApiError("ERR_INVOICE_TOO_OLD_TO_FLOOR")
    tiers = ledger.unit_tiers(line["id"], unit["inventory_class"])
    if not [t for t in tiers if int(t["cumulative_paydown_bps"]) > 0]:
        raise ApiError("ERR_NO_CURTAILMENT_SCHEDULE")

    amount = priced["advance_amount_cents"]
    if amount > int(line["available_credit_cents"]):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
    sublimit = ledger.class_sublimit(line, unit["inventory_class"])
    if sublimit is not None:
        if ledger.class_outstanding(line, unit["inventory_class"]) + amount > sublimit:
            raise ApiError("ERR_CLASS_SUBLIMIT_EXCEEDED")

    advance["status"] = "FUNDED"
    advance["approved_advance_amount_cents"] = amount
    advance["effective_advance_rate_bps"] = priced["effective_advance_rate_bps"]
    advance["rate_adjustment_codes"] = list(priced["rate_adjustment_codes"])
    advance["invoice_age_days_at_funding"] = priced["invoice_age_days"]
    advance["disbursement_reference"] = disbursement_reference
    advance["funded_at"] = db.now_str()
    advance["funded_by_user_id"] = user_id
    db.touch(advance)

    unit["advance_amount_cents"] = amount
    unit["outstanding_principal_cents"] = amount
    unit["floored_at"] = db.now_str()
    unit["funded_by_user_id"] = user_id
    unit["funding_status"] = "FLOORED"
    db.touch(unit)

    _materialise_ladder(unit, line)
    ledger.recompute_availability(line)
    db.touch(line)
    return response.ok(serial.advance(advance))


@bp.route("/floorplan/funding-advances/<advance_id>/reject", methods=["POST"])
def reject_advance(advance_id):
    middleware.require(middleware.CREDIT_OFFICER)
    advance = lookup.advance(advance_id)
    data = validate.body()
    reason_code = validate.req_enum(data, "reason_code", spec.ADVANCE_REASON_CODES)
    if advance["status"] != "REQUESTED":
        raise ApiError("ERR_ADVANCE_NOT_PENDING")
    advance["status"] = "REJECTED"
    advance["reason_code"] = reason_code
    db.touch(advance)
    unit = db.get("inventory_units", advance["unit_id"])
    if unit is not None and unit["funding_status"] == "PENDING_FUNDING":
        unit["funding_status"] = "REGISTERED"
        db.touch(unit)
    return response.ok(serial.advance(advance))


@bp.route("/floorplan/funding-advances/<advance_id>/reverse", methods=["POST"])
def reverse_advance(advance_id):
    middleware.require(middleware.CREDIT_OFFICER)
    advance = lookup.advance(advance_id)
    data = validate.body()
    reason_code = validate.req_enum(data, "reason_code", spec.ADVANCE_REASON_CODES)
    line = db.get("credit_lines", advance["credit_line_id"])
    _line_occ(line, data)

    if advance["status"] != "FUNDED":
        raise ApiError("ERR_ADVANCE_NOT_PENDING")

    unit = db.get("inventory_units", advance["unit_id"])
    deadline = db.add_days(
        db.parse_instant(advance["funded_at"]), spec.ADVANCE_REVERSAL_WINDOW_DAYS
    )
    obligations = ledger.unit_obligations(unit["id"])
    closed = db.now() > deadline
    closed = closed or int(unit["principal_paid_cents"]) != 0
    closed = closed or bool([o for o in db.rows("observations") if o["unit_id"] == unit["id"]])
    closed = closed or bool(
        [o for o in obligations if o["status"] in ("DUE", "DELINQUENT", "PAID")]
    )
    if closed:
        raise ApiError("ERR_ADVANCE_REVERSAL_WINDOW_CLOSED")

    advance["status"] = "REVERSED"
    advance["reason_code"] = reason_code
    db.touch(advance)

    unit["funding_status"] = "REGISTERED"
    unit["advance_amount_cents"] = 0
    unit["outstanding_principal_cents"] = 0
    unit["floored_at"] = None
    unit["funded_by_user_id"] = None
    db.touch(unit)

    for obligation in obligations:
        if obligation["status"] == "SCHEDULED":
            obligation["status"] = "CANCELLED"
            db.touch(obligation)

    ledger.recompute_availability(line)
    db.touch(line)
    return response.ok(serial.advance(advance))


@bp.route("/floorplan/funding-advances/<advance_id>", methods=["GET"])
def read_advance(advance_id):
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.AUDIT_MANAGER,
        middleware.DEALER_PRINCIPAL,
        middleware.SYSTEM_OPERATOR,
    )
    advance = lookup.advance(advance_id)
    unit = db.get("inventory_units", advance["unit_id"])
    middleware.guard_owned(unit)
    return response.ok(serial.advance(advance))


@bp.route("/floorplan/funding-advances", methods=["GET"])
def list_advances():
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.AUDIT_MANAGER,
        middleware.DEALER_PRINCIPAL,
        middleware.SYSTEM_OPERATOR,
    )
    unit_id = response.filter_value("unit_id")
    credit_line_id = response.filter_value("credit_line_id")
    status = response.filter_value("status", spec.ADVANCE_STATUSES)
    records = response.apply_filters(
        db.rows("funding_advances"),
        [("unit_id", unit_id), ("credit_line_id", credit_line_id), ("status", status)],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        owned = set(u["id"] for u in ledger.dealer_units(scope))
        records = [a for a in records if a["unit_id"] in owned]
    return response.paginate(records, serial.advance)
