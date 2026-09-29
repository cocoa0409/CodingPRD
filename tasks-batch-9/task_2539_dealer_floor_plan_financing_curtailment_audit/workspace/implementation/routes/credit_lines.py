"""Credit lines, activation, reinstatement and the curtailment ladder."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import ledger, serial, spec

bp = Blueprint("credit_lines", __name__)

READ_ROLES = (
    middleware.CREDIT_OFFICER,
    middleware.CREDIT_RISK_MANAGER,
    middleware.AUDIT_MANAGER,
    middleware.DEALER_PRINCIPAL,
    middleware.SYSTEM_OPERATOR,
)


@bp.route("/floorplan/credit-lines", methods=["POST"])
def create_credit_line():
    middleware.require(middleware.CREDIT_OFFICER)
    data = validate.body()
    dealer_id = validate.req_ref(data, "dealer_id")
    dealer = lookup.dealer(dealer_id)
    credit_limit = validate.req_int(
        data, "credit_limit_cents", minimum=spec.CREDIT_LIMIT_MIN_CENTS
    )
    rates = {}
    ceilings = {}
    for suffix in ("new", "used", "demonstrator"):
        rates[suffix] = validate.req_int(
            data, "advance_rate_bps_" + suffix, minimum=0, maximum=spec.BPS_MAX
        )
        ceilings[suffix] = validate.req_int(data, "max_unit_advance_cents_" + suffix, minimum=1)
    sublimit_used = validate.req_int(data, "class_sublimit_cents_used", minimum=1)
    sublimit_demo = validate.req_int(data, "class_sublimit_cents_demonstrator", minimum=1)
    grace_days = validate.opt_int(
        data,
        "curtailment_grace_days",
        minimum=0,
        maximum=30,
        default=spec.CURTAILMENT_GRACE_DAYS_DEFAULT,
    )

    if ledger.dealer_line(dealer["id"]) is not None:
        raise ApiError(
            "ERR_CREDIT_LINE_NOT_ACTIVE",
            "The dealership already holds a PENDING, ACTIVE or SUSPENDED credit line.",
        )

    record = db.insert(
        "credit_lines",
        {
            "dealer_id": dealer["id"],
            "status": "PENDING",
            "credit_limit_cents": credit_limit,
            "advance_rate_bps_new": rates["new"],
            "advance_rate_bps_used": rates["used"],
            "advance_rate_bps_demonstrator": rates["demonstrator"],
            "max_unit_advance_cents_new": ceilings["new"],
            "max_unit_advance_cents_used": ceilings["used"],
            "max_unit_advance_cents_demonstrator": ceilings["demonstrator"],
            "class_sublimit_cents_used": sublimit_used,
            "class_sublimit_cents_demonstrator": sublimit_demo,
            "curtailment_grace_days": grace_days,
            "outstanding_principal_cents": 0,
            "charged_off_principal_cents": 0,
            "available_credit_cents": credit_limit,
            "eligible_collateral_cents": 0,
            "borrowing_base_deficiency_cents": 0,
            "class_outstanding_cents_used": 0,
            "class_outstanding_cents_demonstrator": 0,
            "activated_at": None,
            "suspension_reason_code": None,
        },
    )
    return response.created(serial.credit_line(record))


@bp.route("/floorplan/credit-lines/<line_id>", methods=["GET"])
def read_credit_line(line_id):
    middleware.require(*READ_ROLES)
    record = lookup.credit_line(line_id)
    middleware.guard_owned(record)
    return response.ok(serial.credit_line(record))


@bp.route("/floorplan/credit-lines", methods=["GET"])
def list_credit_lines():
    middleware.require(*READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    status = response.filter_value("status", spec.LINE_STATUSES)
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    records = response.apply_filters(
        db.rows("credit_lines"), [("dealer_id", dealer_id), ("status", status)]
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [r for r in records if r["dealer_id"] == scope]
    return response.paginate(records, serial.credit_line)


@bp.route("/floorplan/credit-lines/<line_id>/activate", methods=["POST"])
def activate_credit_line(line_id):
    middleware.require(middleware.CREDIT_OFFICER)
    line = lookup.credit_line(line_id)
    validate.body()
    if line["status"] != "PENDING":
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
    tiers = [t for t in db.rows("curtailment_tiers") if t["credit_line_id"] == line["id"]]
    if not tiers:
        raise ApiError("ERR_NO_CURTAILMENT_SCHEDULE")
    line["activated_at"] = db.now_str()
    line["status"] = "ACTIVE"
    ledger.recompute_availability(line)
    db.touch(line)

    dealer = db.get("dealers", line["dealer_id"])
    if dealer is not None:
        if dealer["status"] == "PROSPECT":
            dealer["status"] = "ACTIVE"
        dealer["next_audit_due_at"] = db.fmt_instant(
            db.add_days(db.parse_instant(line["activated_at"]), int(dealer["audit_frequency_days"]))
        )
        db.touch(dealer)
    return response.ok(serial.credit_line(line))


@bp.route("/floorplan/credit-lines/<line_id>/reinstate", methods=["POST"])
def reinstate_credit_line(line_id):
    middleware.require(middleware.CREDIT_RISK_MANAGER)
    line = lookup.credit_line(line_id)
    data = validate.body()
    validate.req_enum(data, "reason_code", spec.REINSTATE_REASONS)
    if line["status"] != "SUSPENDED":
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
    dealer = db.get("dealers", line["dealer_id"])

    open_incidents = ledger.dealer_incidents(dealer["id"], ("OPEN",))
    tests = [t for t in db.rows("covenant_tests") if t["dealer_id"] == dealer["id"]]
    latest = None
    if tests:
        latest = max(tests, key=lambda t: (t["period_end_date"], t["created_at"], t["_seq"]))
    satisfied = (
        not open_incidents
        and int(dealer["open_sot_exposure_cents"]) == 0
        and int(dealer["delinquent_unit_count"]) == 0
        and latest is not None
        and latest["dscr_dealer_adjusted"] >= db.Decimal(spec.DSCR_REINSTATEMENT_MIN)
    )
    if not satisfied:
        raise ApiError("ERR_REINSTATEMENT_CRITERIA_NOT_MET")

    line["status"] = "ACTIVE"
    line["suspension_reason_code"] = None
    db.touch(line)
    if dealer["status"] == "SUSPENDED":
        dealer["status"] = "ACTIVE"
    dealer["covenant_breach_count"] = 0
    db.touch(dealer)
    return response.ok(serial.credit_line(line))


# --------------------------------------------------------------------------
# Curtailment ladder rungs (3.1)
# --------------------------------------------------------------------------


@bp.route("/floorplan/credit-lines/<line_id>/curtailment-tiers", methods=["POST"])
def add_curtailment_tier(line_id):
    middleware.require(middleware.CREDIT_OFFICER)
    line = lookup.credit_line(line_id)
    data = validate.body()
    inventory_class = validate.req_enum(data, "inventory_class", spec.INVENTORY_CLASSES)
    age_days_from = validate.req_int(data, "age_days_from", minimum=0)
    age_days_to = validate.opt_int(data, "age_days_to", minimum=0)
    paydown_bps = validate.req_int(
        data, "cumulative_paydown_bps", minimum=0, maximum=spec.BPS_MAX
    )
    if line["status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")

    existing = ledger.unit_tiers(line["id"], inventory_class)
    new_to = age_days_to
    for rung in existing:
        rung_to = rung["age_days_to"]
        starts_before_other_ends = rung_to is None or age_days_from < int(rung_to)
        other_starts_before_new_ends = new_to is None or int(rung["age_days_from"]) < int(new_to)
        if starts_before_other_ends and other_starts_before_new_ends:
            raise ApiError("ERR_TIER_INTERVAL_OVERLAP")

    if age_days_to is not None and int(age_days_to) <= age_days_from:
        raise ApiError("ERR_TIER_INTERVAL_INVALID")
    for rung in existing:
        if int(rung["age_days_from"]) < age_days_from and paydown_bps <= int(
            rung["cumulative_paydown_bps"]
        ):
            raise ApiError("ERR_TIER_INTERVAL_INVALID")

    record = db.insert(
        "curtailment_tiers",
        {
            "credit_line_id": line["id"],
            "inventory_class": inventory_class,
            "age_days_from": age_days_from,
            "age_days_to": age_days_to,
            "cumulative_paydown_bps": paydown_bps,
        },
        versioned=False,
    )
    return response.created(serial.tier(record))


@bp.route("/floorplan/credit-lines/<line_id>/curtailment-tiers", methods=["GET"])
def list_curtailment_tiers(line_id):
    middleware.require(*READ_ROLES)
    line = lookup.credit_line(line_id)
    middleware.guard_owned(line)
    inventory_class = response.filter_value("inventory_class", spec.INVENTORY_CLASSES)
    records = response.apply_filters(
        [t for t in db.rows("curtailment_tiers") if t["credit_line_id"] == line["id"]],
        [("inventory_class", inventory_class)],
    )
    # Explicit exception to the default ordering: ascending start age.
    records = sorted(records, key=lambda t: (t["age_days_from"], t["_seq"]))
    return response.paginate(records, serial.tier)
