"""Functional lab panels: ordering, wash-out, collection, results and closure."""

from datetime import timedelta

from flask import Blueprint

import config
import ladder
from clock import clock, parse_date, render_date
from errors import ApiError
from store import db, bump, make_immutable_row, make_row, ordered, touch
from services import serializers
from services.dispensary import membership_with_credits
from services.gate import recompute_gate
from services.labs import classify, washout_clearance_date, washout_released

bp = Blueprint("lab_orders", __name__)

OPEN_ORDER_STATES = ("ORDERED", "WASHOUT_HOLD", "COLLECTED")


def _order_patient(order):
    return db.patients.get(order["patient_id"])


def _red_flag_referral(order):
    for referral in ordered(list(db.referrals.values())):
        if (
            referral["referral_type"] == "RED_FLAG_AUTO"
            and referral.get("lab_order_id") == order["id"]
        ):
            return referral
    return None


@bp.route("/lab-orders", methods=["POST"])
def create_lab_order():
    def duplicate_panel(ctx):
        patient = ctx.fk["patient_id"]
        for row in db.lab_orders.values():
            if (
                row["patient_id"] == patient["id"]
                and row["panel_code"] == ctx.body["panel_code"]
                and row["status"] in OPEN_ORDER_STATES
            ):
                raise ApiError("ERR_DUPLICATE_PANEL_ORDER")

    def entitlement(ctx):
        if ctx.body["funding_source"] != "MEMBERSHIP_CREDIT":
            return
        panel = config.LAB_PANELS[ctx.body["panel_code"]]
        membership = membership_with_credits(
            ctx.fk["patient_id"]["id"], panel["lab_credit_cost"]
        )
        if membership is None:
            raise ApiError("ERR_ENTITLEMENT_EXHAUSTED")
        ctx.scratch["membership"] = membership

    def handler(ctx):
        patient = ctx.fk["patient_id"]
        panel_code = ctx.body["panel_code"]
        panel = config.LAB_PANELS[panel_code]
        funding = ctx.body["funding_source"]
        is_cash = funding == "CASH"
        requested = parse_date(ctx.body["requested_collection_date"])
        clearance = washout_clearance_date(patient["id"], panel_code)

        status = "ORDERED"
        if clearance is not None and requested < clearance:
            # CLOSED lower bound: only a strictly earlier date is held.
            status = "WASHOUT_HOLD"

        row = make_row(
            patient_id=patient["id"],
            ordering_practitioner_id=ctx.user_id,
            panel_code=panel_code,
            specimen_type=panel["specimen_type"],
            status=status,
            funding_source=funding,
            price_cents=panel["cash_price_cents"] if is_cash else 0,
            lab_credit_cost=0 if is_cash else panel["lab_credit_cost"],
            requested_collection_date=render_date(requested),
            fasting_attested=bool(ctx.body.get("fasting_attested", False)),
            cycle_day=ctx.body.get("cycle_day"),
            washout_class=panel["washout_class"],
            washout_clearance_date=render_date(clearance),
            collected_at=None,
            has_critical_result=False,
            interpretation_summary=None,
        )
        db.lab_orders[row["id"]] = row

        if is_cash:
            patient["cash_charged_total_cents"] += row["price_cents"]
            touch(patient)
        else:
            membership = ctx.scratch["membership"]
            membership["lab_credits_consumed"] += row["lab_credit_cost"]
            membership["lab_credits_remaining"] -= row["lab_credit_cost"]
            touch(membership)
            row["_membership_id"] = membership["id"]
        return serializers.lab_order(row)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "body_fks": ["patient_id"],
            "gate": lambda ctx: ctx.fk.get("patient_id"),
            "shape": [
                ("patient_id", "string", True),
                ("panel_code", "string", True),
                ("funding_source", "string", True),
                ("requested_collection_date", "date", True),
                ("fasting_attested", "bool", False),
                ("cycle_day", "int", False),
            ],
            "enums": {
                "panel_code": config.PANEL_CODES,
                "funding_source": config.FUNDING_SOURCES,
            },
            "business": [duplicate_panel, entitlement],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/lab-orders/<oid>", methods=["GET"])
def get_lab_order(oid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_PATIENT,
            ],
            "path": [("lab_order", oid)],
            "owner": lambda ctx: ctx.path["lab_order"]["patient_id"],
            "handler": lambda ctx: serializers.lab_order(ctx.path["lab_order"]),
        }
    )


@bp.route("/lab-orders", methods=["GET"])
def list_lab_orders():
    def handler(ctx):
        rows = ordered(db.lab_orders.values())
        for field in ("patient_id", "ordering_practitioner_id", "status"):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.lab_order)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/lab-orders/<oid>/collect", methods=["POST"])
def collect_lab_order(oid):
    def own_state(ctx):
        if ctx.path["lab_order"]["status"] != "ORDERED":
            raise ApiError("ERR_INVALID_STATE")

    def collection_window(ctx):
        order = ctx.path["lab_order"]
        panel = config.LAB_PANELS[order["panel_code"]]
        if panel["fasting_required"] and not order["fasting_attested"]:
            raise ApiError("ERR_COLLECTION_WINDOW_INVALID")
        low = panel["cycle_day_window_start"]
        high = panel["cycle_day_window_end"]
        if low is not None:
            day = order["cycle_day"]
            # CLOSED at both ends.
            if day is None or day < low or day > high:
                raise ApiError("ERR_COLLECTION_WINDOW_INVALID")

    def handler(ctx):
        order = ctx.path["lab_order"]
        order["status"] = "COLLECTED"
        order["collected_at"] = clock.stamp()
        bump(order)
        return serializers.lab_order(order)

    return ladder.run(
        {
            "roles": [config.ROLE_ND, config.ROLE_HEALTH_COACH],
            "path": [("lab_order", oid)],
            "gate": lambda ctx: _order_patient(ctx.path["lab_order"]),
            "own_state": own_state,
            "shape": [],
            "business": [collection_window],
            "handler": handler,
        }
    )


@bp.route("/lab-orders/<oid>/results", methods=["POST"])
def post_result(oid):
    def own_state(ctx):
        if ctx.path["lab_order"]["status"] not in ("COLLECTED", "RESULTED"):
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        order = ctx.path["lab_order"]
        body = ctx.body
        standard_band, optimal_band, is_critical = classify(
            body["value"],
            body["standard_low"],
            body["standard_high"],
            body["optimal_low"],
            body["optimal_high"],
            body["critical_low"],
            body["critical_high"],
        )
        result = make_immutable_row(
            lab_order_id=order["id"],
            analyte_code=body["analyte_code"],
            value=body["value"],
            unit=body["unit"],
            standard_low=body["standard_low"],
            standard_high=body["standard_high"],
            optimal_low=body["optimal_low"],
            optimal_high=body["optimal_high"],
            critical_low=body["critical_low"],
            critical_high=body["critical_high"],
            standard_band=standard_band,
            optimal_band=optimal_band,
            is_critical=is_critical,
        )
        db.lab_results[result["id"]] = result

        if is_critical:
            _escalate(order)
        else:
            order["status"] = "RESULTED"
            touch(order)
        return serializers.lab_result(result)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("lab_order", oid)],
            "own_state": own_state,
            "shape": [
                ("analyte_code", "string", True),
                ("value", "number", True),
                ("unit", "string", True),
                ("standard_low", "number", True),
                ("standard_high", "number", True),
                ("optimal_low", "number", True),
                ("optimal_high", "number", True),
                ("critical_low", "number", True),
                ("critical_high", "number", True),
            ],
            "handler": handler,
            "status": 201,
        }
    )


def _escalate(order):
    """The five-link freeze cascade (PRD 2.11, 3.5)."""
    order["has_critical_result"] = True
    order["status"] = "CRITICAL_ESCALATED"
    touch(order)

    referral = make_row(
        patient_id=order["patient_id"],
        referring_practitioner_id=order["ordering_practitioner_id"],
        lab_order_id=order["id"],
        referral_type="RED_FLAG_AUTO",
        recipient_name=None,
        specialty=None,
        reason=None,
        status="SENT",
        attempt_no=1,
        due_by_date=render_date(
            clock.today() + timedelta(days=config.RED_FLAG_REFERRAL_DUE_DAYS)
        ),
        acknowledged_at=None,
        report_summary=None,
        report_received_at=None,
        closed_at=None,
        decline_reason=None,
    )
    db.referrals[referral["id"]] = referral

    patient = _order_patient(order)
    if patient is not None:
        recompute_gate(patient)
        touch(patient)


@bp.route("/lab-orders/<oid>/results", methods=["GET"])
def list_results(oid):
    def handler(ctx):
        rows = ordered(
            [
                r
                for r in db.lab_results.values()
                if r["lab_order_id"] == ctx.path["lab_order"]["id"]
            ]
        )
        return ladder.list_result(ctx, rows, serializers.lab_result)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_PATIENT,
            ],
            "path": [("lab_order", oid)],
            "owner": lambda ctx: ctx.path["lab_order"]["patient_id"],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/lab-orders/<oid>/interpret", methods=["POST"])
def interpret_lab_order(oid):
    def own_state(ctx):
        if ctx.path["lab_order"]["status"] not in ("RESULTED", "CRITICAL_ESCALATED"):
            raise ApiError("ERR_INVALID_STATE")

    def red_flag(ctx):
        order = ctx.path["lab_order"]
        if order["status"] != "CRITICAL_ESCALATED":
            return
        referral = _red_flag_referral(order)
        if referral is not None and referral["status"] in (
            "SENT",
            "DECLINED",
            "ABANDONED",
        ):
            raise ApiError("ERR_RED_FLAG_UNACKNOWLEDGED")

    def handler(ctx):
        order = ctx.path["lab_order"]
        order["interpretation_summary"] = ctx.body["interpretation_summary"]
        order["status"] = "INTERPRETED"
        bump(order)
        return serializers.lab_order(order)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("lab_order", oid)],
            "own_state": own_state,
            "shape": [("interpretation_summary", "string", True)],
            "business": [red_flag],
            "handler": handler,
        }
    )


@bp.route("/lab-orders/<oid>/release-washout-hold", methods=["POST"])
def release_washout_hold(oid):
    def own_state(ctx):
        if ctx.path["lab_order"]["status"] != "WASHOUT_HOLD":
            raise ApiError("ERR_INVALID_STATE")

    def washout(ctx):
        if not washout_released(ctx.path["lab_order"]):
            raise ApiError("ERR_WASHOUT_NOT_ELAPSED")

    def handler(ctx):
        order = ctx.path["lab_order"]
        order["status"] = "ORDERED"
        bump(order)
        return serializers.lab_order(order)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("lab_order", oid)],
            "own_state": own_state,
            "shape": [],
            "business": [washout],
            "handler": handler,
        }
    )


@bp.route("/lab-orders/<oid>/cancel", methods=["POST"])
def cancel_lab_order(oid):
    def own_state(ctx):
        if ctx.path["lab_order"]["status"] not in OPEN_ORDER_STATES:
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        order = ctx.path["lab_order"]
        order["status"] = "CANCELLED"
        if order["funding_source"] == "MEMBERSHIP_CREDIT":
            membership = db.memberships.get(order.get("_membership_id"))
            if membership is not None:
                membership["lab_credits_consumed"] -= order["lab_credit_cost"]
                membership["lab_credits_remaining"] += order["lab_credit_cost"]
                touch(membership)
        else:
            patient = _order_patient(order)
            if patient is not None:
                patient["cash_refunded_total_cents"] += order["price_cents"]
                touch(patient)
        bump(order)
        return serializers.lab_order(order)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("lab_order", oid)],
            "own_state": own_state,
            "shape": [("reason", "string", False)],
            "handler": handler,
        }
    )
