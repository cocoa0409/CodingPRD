"""Curtailment obligations, the nightly run checkpoint and the forbearance
request lifecycle (PRD 3.4 and 3.5)."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import calc, ledger, serial, spec

bp = Blueprint("obligations", __name__)

READ_ROLES = (
    middleware.CREDIT_OFFICER,
    middleware.CREDIT_RISK_MANAGER,
    middleware.AUDIT_MANAGER,
    middleware.DEALER_PRINCIPAL,
    middleware.SYSTEM_OPERATOR,
)

EXCEPTION_READ_ROLES = (
    middleware.CREDIT_OFFICER,
    middleware.CREDIT_RISK_MANAGER,
    middleware.DEALER_PRINCIPAL,
    middleware.SYSTEM_OPERATOR,
)


@bp.route("/floorplan/curtailment-obligations/<obligation_id>", methods=["GET"])
def read_obligation(obligation_id):
    middleware.require(*READ_ROLES)
    obligation = lookup.obligation(obligation_id)
    middleware.guard_owned(obligation)
    return response.ok(serial.obligation(obligation))


@bp.route("/floorplan/curtailment-obligations", methods=["GET"])
def list_obligations():
    middleware.require(*READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    unit_id = response.filter_value("unit_id")
    status = response.filter_value("status", spec.OBLIGATION_STATUSES)
    supersedes = response.filter_value("supersedes_obligation_id")
    records = response.apply_filters(
        db.rows("curtailment_obligations"),
        [
            ("dealer_id", dealer_id),
            ("unit_id", unit_id),
            ("status", status),
            ("supersedes_obligation_id", supersedes),
        ],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [o for o in records if o["dealer_id"] == scope]
    return response.paginate(records, serial.obligation)


# --------------------------------------------------------------------------
# The nightly run (3.4)
# --------------------------------------------------------------------------


@bp.route("/floorplan/curtailment-runs", methods=["POST"])
def curtailment_run():
    middleware.require(middleware.SYSTEM_OPERATOR)
    data = validate.body()
    dealer_filter = validate.opt_ref(data, "dealer_id")
    as_of = validate.opt_instant(data, "as_of_date")
    if dealer_filter is not None:
        lookup.dealer(dealer_filter)
    run_moment = as_of if as_of is not None else db.now()
    run_day = db.day_of(run_moment)

    dealers = [d for d in db.rows("dealers") if d["status"] in ("ACTIVE", "SUSPENDED")]
    if dealer_filter is not None:
        dealers = [d for d in dealers if d["id"] == dealer_filter]

    processed = []
    due_count = 0
    delinquent_count = 0
    total_required = 0
    flagged_units = 0
    expired_count = 0

    for dealer in dealers:
        processed.append(dealer["id"])
        dealer_mutated = False
        units = [
            u
            for u in ledger.dealer_units(dealer["id"])
            if u["funding_status"] in spec.COLLATERAL_FUNDING_STATUSES
        ]
        units.sort(key=lambda u: (u["floored_at"] or "", u["created_at"], u["_seq"]))
        for unit in units:
            line = ledger.unit_line(unit)
            grace = int(line["curtailment_grace_days"]) if line is not None else 0
            newly_delinquent = 0
            for obligation in ledger.unit_obligations(unit["id"]):
                if obligation["status"] not in ("SCHEDULED", "DUE"):
                    continue
                due_day = db.day_of(db.parse_instant(obligation["due_date"]))
                if obligation["status"] == "SCHEDULED" and due_day <= run_day:
                    required = calc.assessed_requirement(
                        unit, obligation["tier_cumulative_paydown_bps"]
                    )
                    obligation["status"] = "DUE"
                    obligation["became_due_at"] = db.now_str()
                    obligation["required_principal_cents"] = required
                    obligation["total_amount_due_cents"] = required
                    db.touch(obligation)
                    due_count += 1
                    total_required += required
                    dealer_mutated = True
                if obligation["status"] == "DUE" and run_day > db.day_of(
                    db.add_days(db.parse_instant(obligation["due_date"]), grace)
                ):
                    if int(obligation["principal_paid_cents"]) < int(
                        obligation["required_principal_cents"]
                    ):
                        fee = calc.late_fee_cents(int(obligation["required_principal_cents"]))
                        obligation["status"] = "DELINQUENT"
                        obligation["late_fee_cents"] = fee
                        obligation["total_amount_due_cents"] = (
                            int(obligation["required_principal_cents"]) + fee
                        )
                        obligation["became_delinquent_at"] = db.now_str()
                        db.touch(obligation)
                        delinquent_count += 1
                        newly_delinquent += 1
                        dealer_mutated = True
                        for request_row in db.rows("aging_exceptions"):
                            if (
                                request_row["obligation_id"] == obligation["id"]
                                and request_row["status"] == "PENDING"
                            ):
                                request_row["status"] = "EXPIRED"
                                db.touch(request_row)
                                expired_count += 1
            if newly_delinquent and unit["funding_status"] == "FLOORED":
                unit["funding_status"] = "DELINQUENT_CURTAILMENT"
                db.touch(unit)
                flagged_units += 1
                dealer_mutated = True
        if dealer_mutated:
            ledger.recompute_dealer_counters(dealer)
            ledger.recompute_risk(dealer)
            db.touch(dealer)

    return response.ok(
        {
            "run_completed_at": db.now_str(),
            "dealer_ids_processed": processed,
            "obligations_marked_due_count": due_count,
            "obligations_marked_delinquent_count": delinquent_count,
            "total_required_paydown_cents": total_required,
            "units_flagged_delinquent_count": flagged_units,
            "exceptions_expired_count": expired_count,
        }
    )


# --------------------------------------------------------------------------
# Aging exceptions (3.5)
# --------------------------------------------------------------------------


@bp.route("/floorplan/curtailment-obligations/<obligation_id>/aging-exceptions", methods=["POST"])
def file_exception(obligation_id):
    user_id, _role = middleware.require(middleware.DEALER_PRINCIPAL)
    obligation = lookup.obligation(obligation_id)
    middleware.guard_owned(obligation)
    data = validate.body()
    requested_days = validate.req_int(data, "requested_extension_days")
    justification = validate.req_enum(data, "justification_code", spec.JUSTIFICATION_CODES)

    dealer = db.get("dealers", obligation["dealer_id"])
    if dealer is None or dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_NOT_ACTIVE")
    if obligation["status"] not in ("SCHEDULED", "DUE"):
        raise ApiError("ERR_OBLIGATION_NOT_OPEN")
    if requested_days < 1 or requested_days > spec.EXTENSION_DAYS_MAX_PER_REQUEST:
        raise ApiError("ERR_EXTENSION_EXCEEDS_MAX")

    record = db.insert(
        "aging_exceptions",
        {
            "obligation_id": obligation["id"],
            "status": "PENDING",
            "requested_extension_days": requested_days,
            "justification_code": justification,
            "requested_by_user_id": user_id,
            "decided_extension_days": None,
            "decided_by_user_id": None,
            "decided_at": None,
            "reason_code": None,
            "replacement_obligation_id": None,
        },
    )
    return response.created(serial.exception_request(record))


@bp.route("/floorplan/curtailment-obligations/<obligation_id>/aging-exceptions", methods=["GET"])
def list_exceptions(obligation_id):
    middleware.require(*EXCEPTION_READ_ROLES)
    obligation = lookup.obligation(obligation_id)
    middleware.guard_owned(obligation)
    status = response.filter_value("status", spec.EXCEPTION_STATUSES)
    records = response.apply_filters(
        [e for e in db.rows("aging_exceptions") if e["obligation_id"] == obligation["id"]],
        [("status", status)],
    )
    return response.paginate(records, serial.exception_request)


@bp.route("/floorplan/aging-exceptions/<exception_id>/decision", methods=["POST"])
def decide_exception(exception_id):
    user_id, _role = middleware.require(middleware.CREDIT_RISK_MANAGER)
    request_row = lookup.exception_request(exception_id)
    data = validate.body()
    decision = validate.req_enum(data, "decision", spec.DECISIONS)
    decided_days = validate.opt_int(data, "decided_extension_days")
    reason_code = validate.req_enum(data, "reason_code", spec.EXCEPTION_REASON_CODES)

    obligation = db.get("curtailment_obligations", request_row["obligation_id"])
    unit = db.get("inventory_units", obligation["unit_id"])
    dealer = db.get("dealers", obligation["dealer_id"])

    if request_row["status"] != "PENDING":
        raise ApiError("ERR_EXCEPTION_NOT_PENDING")
    if unit.get("funded_by_user_id") is not None and unit["funded_by_user_id"] == user_id:
        raise ApiError("ERR_SOD_EXCEPTION_APPROVER")

    if decision == "DENY":
        request_row["status"] = "DENIED"
        request_row["decided_extension_days"] = None
        request_row["decided_by_user_id"] = user_id
        request_row["decided_at"] = db.now_str()
        request_row["reason_code"] = reason_code
        db.touch(request_row)
        return response.ok(serial.exception_request(request_row))

    if obligation["status"] not in ("SCHEDULED", "DUE"):
        raise ApiError("ERR_OBLIGATION_NOT_OPEN")
    if decided_days is None or decided_days < 1:
        raise ApiError("ERR_EXTENSION_EXCEEDS_MAX")
    if decided_days > int(request_row["requested_extension_days"]):
        raise ApiError("ERR_EXTENSION_EXCEEDS_MAX")
    if (
        int(unit["curtailment_extension_days_total"]) + decided_days
        > spec.EXTENSION_DAYS_MAX_TOTAL
    ):
        raise ApiError("ERR_EXTENSION_EXCEEDS_MAX")
    if int(unit["aging_exception_count"]) >= spec.AGING_EXCEPTION_MAX_PER_UNIT:
        raise ApiError("ERR_EXCEPTION_LIMIT_REACHED")
    if ledger.unit_incidents(unit["id"], ("OPEN",)):
        raise ApiError("ERR_UNIT_HAS_OPEN_SOT")

    replacement = db.insert(
        "curtailment_obligations",
        {
            "unit_id": obligation["unit_id"],
            "dealer_id": obligation["dealer_id"],
            "supersedes_obligation_id": obligation["id"],
            "status": "SCHEDULED",
            "tier_age_days_from": obligation["tier_age_days_from"],
            "tier_cumulative_paydown_bps": obligation["tier_cumulative_paydown_bps"],
            "due_date": db.fmt_instant(
                db.add_days(db.parse_instant(obligation["due_date"]), decided_days)
            ),
            "projected_principal_cents": obligation["projected_principal_cents"],
            "required_principal_cents": 0,
            "late_fee_cents": 0,
            "total_amount_due_cents": 0,
            "principal_paid_cents": 0,
            "fee_paid_cents": 0,
            "became_due_at": None,
            "became_delinquent_at": None,
            "extension_days_applied": decided_days,
        },
    )
    obligation["status"] = "SUPERSEDED"
    db.touch(obligation)

    request_row["status"] = "APPROVED"
    request_row["decided_extension_days"] = decided_days
    request_row["decided_by_user_id"] = user_id
    request_row["decided_at"] = db.now_str()
    request_row["reason_code"] = reason_code
    request_row["replacement_obligation_id"] = replacement["id"]
    db.touch(request_row)

    unit["aging_exception_count"] = int(unit["aging_exception_count"]) + 1
    unit["curtailment_extension_days_total"] = (
        int(unit["curtailment_extension_days_total"]) + decided_days
    )
    db.touch(unit)

    if unit["funding_status"] == "DELINQUENT_CURTAILMENT" and not ledger.unit_obligations(
        unit["id"], ("DELINQUENT",)
    ):
        unit["funding_status"] = "FLOORED"
        db.touch(unit)
        ledger.recompute_dealer_counters(dealer)
        ledger.recompute_risk(dealer)
        db.touch(dealer)
    return response.ok(serial.exception_request(request_row))
