"""Resident admission, participation, substitution profile and monitoring."""
from decimal import Decimal

from flask import Blueprint

import serialize
from auth import authenticate, require_own_resident
from clock import clock
from constants import (
    CARE_LEVELS, DINING_STATUSES, FEEDBACK_STATUSES, MEAL_PERIODS,
    RULE_STATUSES, SENTIMENTS, TRIGGER_TYPES,
)
from db import base_row, db, snapshot, sort_created, touch, touch_if_changed
from errors import api_error
from response import created, ok, ok_list
from routes.common import (
    CS, DSM, EVERY_ROLE, PA, RD, RR, SKL, get_community, get_resident,
)
from services import calc, derive
from shape import (
    body_json, opt_decimal, opt_enum, opt_str_array, paginate, q_date, q_enum,
    q_required_date, q_required_enum, req_date, req_decimal, req_enum, req_int,
    req_str,
)

bp = Blueprint("residents", __name__)

ZERO2 = Decimal("0.00")


@bp.get("/residents/<resident_id>")
def read_resident(resident_id):
    ctx = authenticate(EVERY_ROLE)
    require_own_resident(ctx, resident_id)
    return ok(serialize.resident(get_resident(resident_id)))


@bp.get("/residents/<resident_id>/substitution-rules")
def list_rules(resident_id):
    ctx = authenticate([PA, CS, RD, DSM, SKL, RR])
    require_own_resident(ctx, resident_id)
    get_resident(resident_id)
    trigger_type = q_enum("trigger_type", TRIGGER_TYPES)
    status = q_enum("status", RULE_STATUSES)
    rows = [r for r in db.substitution_rules.values() if r["resident_id"] == resident_id]
    if trigger_type is not None:
        rows = [r for r in rows if r["trigger_type"] == trigger_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.substitution_rule, window), pagination)


@bp.get("/residents/<resident_id>/intake-observations")
def list_observations(resident_id):
    ctx = authenticate([PA, CS, RD, DSM, RR])
    require_own_resident(ctx, resident_id)
    get_resident(resident_id)
    from_date = q_date("from_date")
    to_date = q_date("to_date")
    meal_period = q_enum("meal_period", MEAL_PERIODS)
    rows = [o for o in db.observations.values() if o["resident_id"] == resident_id]
    if from_date is not None:
        rows = [o for o in rows if o["observation_date"] >= from_date[0]]
    if to_date is not None:
        rows = [o for o in rows if o["observation_date"] <= to_date[0]]
    if meal_period is not None:
        rows = [o for o in rows if o["meal_period"] == meal_period]
    rows.sort(key=lambda o: (o["observation_date"], o["created_at"], o["_seq"]))
    window, pagination = paginate(rows)
    return ok_list(serialize.many(serialize.observation, window), pagination)


@bp.get("/residents/<resident_id>/committee-feedback")
def list_resident_feedback(resident_id):
    ctx = authenticate([PA, RD, DSM, RR])
    require_own_resident(ctx, resident_id)
    get_resident(resident_id)
    status = q_enum("status", FEEDBACK_STATUSES)
    sentiment = q_enum("sentiment", SENTIMENTS)
    rows = [f for f in db.feedback.values() if f["resident_id"] == resident_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    if sentiment is not None:
        rows = [f for f in rows if f["sentiment"] == sentiment]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.feedback, window), pagination)


@bp.get("/residents/<resident_id>/tray-card")
def read_tray_card(resident_id):
    ctx = authenticate([PA, CS, RD, DSM, SKL, RR])
    require_own_resident(ctx, resident_id)
    resident = get_resident(resident_id)
    service_date_str, service_date = q_required_date("service_date")
    meal_period = q_required_enum("meal_period", MEAL_PERIODS)
    return ok(derive.tray_card_resolution(resident, service_date_str, service_date, meal_period))


@bp.post("/residents")
def create_resident():
    authenticate([PA])
    body = body_json()
    community_id = req_str(body, "community_id")
    full_name = req_str(body, "full_name")
    care_level = req_enum(body, "care_level", CARE_LEVELS)
    baseline_weight_kg = req_decimal(body, "baseline_weight_kg", 1, gt=Decimal("0"))
    allergens = opt_str_array(body, "allergens")
    dislikes = opt_str_array(body, "dislikes")
    strictness = opt_enum(body, "preference_strictness", ["STRICT", "FLEXIBLE"], default="FLEXIBLE")

    community = get_community(community_id)
    if care_level not in community["care_levels_offered"]:
        raise api_error(
            "ERR_CROSS_COMMUNITY_REFERENCE",
            "care_level must be one of the community's care_levels_offered",
        )

    row = base_row()
    row.update({
        "community_id": community_id,
        "full_name": full_name,
        "care_level": care_level,
        "dining_status": "ACTIVE",
        "baseline_weight_kg": baseline_weight_kg,
        "current_weight_kg": baseline_weight_kg,
        "rolling_30d_weight_change_pct": ZERO2,
        "baseline_weight_change_pct": ZERO2,
        "avg_intake_pct_7d": None,
        "intake_risk_score": ZERO2,
        "allergens": allergens,
        "dislikes": dislikes,
        "preference_strictness": strictness,
        "guest_meal_charge_balance_cents": 0,
        "tray_card_state": "CLEAR",
    })
    db.residents[row["id"]] = row
    return created(serialize.resident(row))


@bp.post("/residents/<resident_id>/dining-status")
def set_dining_status(resident_id):
    authenticate([PA])
    body = body_json()
    dining_status = req_enum(body, "dining_status", DINING_STATUSES)
    resident = get_resident(resident_id)

    snap = snapshot(resident, ["dining_status", "intake_risk_score"])
    resident["dining_status"] = dining_status
    resident["intake_risk_score"] = calc.intake_risk_score(
        resident, derive.find_active_order(resident_id)
    )
    touch_if_changed(resident, snap)
    return ok(serialize.resident(resident))


@bp.post("/residents/<resident_id>/substitution-rules")
def create_rule(resident_id):
    authenticate([CS])
    body = body_json()
    trigger_type = req_enum(body, "trigger_type", TRIGGER_TYPES)
    match_value = req_str(body, "match_value")
    replacement_item_code = req_str(body, "replacement_item_code")
    priority_rank = req_int(body, "priority_rank", minimum=1)

    resident = get_resident(resident_id)

    if trigger_type == "DISLIKE" and match_value == replacement_item_code:
        raise api_error(
            "ERR_LINKED_RESOURCE_MISMATCH",
            "A DISLIKE rule's replacement_item_code must differ from its match_value",
        )

    if resident["dining_status"] == "DISCHARGED":
        raise api_error(
            "ERR_RESIDENT_NOT_ACTIVE",
            "A DISCHARGED resident cannot receive new substitution rules",
        )

    row = base_row()
    row.update({
        "resident_id": resident_id,
        "trigger_type": trigger_type,
        "match_value": match_value,
        "replacement_item_code": replacement_item_code,
        "priority_rank": priority_rank,
        "status": "ACTIVE",
    })
    db.substitution_rules[row["id"]] = row
    return created(serialize.substitution_rule(row))


@bp.post("/residents/<resident_id>/intake-observations")
def create_observation(resident_id):
    ctx = authenticate([CS])
    body = body_json()
    observation_date_str, observation_date = req_date(body, "observation_date")
    meal_period = req_enum(body, "meal_period", MEAL_PERIODS)
    intake_pct = req_int(body, "intake_pct", minimum=0, maximum=100)
    weight_kg = opt_decimal(body, "weight_kg", 1, gt=Decimal("0"))

    resident = get_resident(resident_id)

    if resident["dining_status"] == "DISCHARGED":
        raise api_error(
            "ERR_RESIDENT_NOT_ACTIVE",
            "A DISCHARGED resident cannot receive new intake observations",
        )
    if observation_date > clock.date():
        raise api_error(
            "ERR_OBSERVATION_FUTURE_DATE",
            "observation_date must not fall after the logical clock date",
        )

    row = base_row(versioned=False)
    row.update({
        "resident_id": resident_id,
        "observation_date": observation_date_str,
        "meal_period": meal_period,
        "intake_pct": intake_pct,
        "weight_kg": weight_kg,
        "recorded_by_user_id": ctx["user_id"],
    })
    db.observations[row["id"]] = row

    _monitoring_cascade(resident, row)
    return created(serialize.observation(row))


def _monitoring_cascade(resident, observation):
    # hop 1 -- recompute the monitoring metrics
    derive.recompute_resident_metrics(resident)

    # hop 2 -- plan-of-care trigger
    rolling = resident["rolling_30d_weight_change_pct"]
    avg_intake = resident["avg_intake_pct_7d"]
    weight_breach = rolling <= Decimal("-5.00")
    intake_breach = avg_intake is not None and avg_intake < Decimal("50.00")
    if not (weight_breach or intake_breach):
        return
    if derive.has_open_review(resident["id"]) is not None:
        return

    if weight_breach and intake_breach:
        reason = "COMBINED"
    elif weight_breach:
        reason = "WEIGHT_LOSS_30D"
    else:
        reason = "LOW_INTAKE_AVG"

    review = base_row()
    review.update({
        "resident_id": resident["id"],
        "trigger_observation_id": observation["id"],
        "trigger_reason": reason,
        "risk_score_at_open": resident["intake_risk_score"],
        "status": "OPEN",
        "outcome": None,
        "note": None,
        "completed_by_user_id": None,
    })
    db.reviews[review["id"]] = review

    # hop 3 -- the ACTIVE order goes back to the dietitian queue
    order = derive.find_active_order(resident["id"])
    if order is None or order["review_status"] != "APPROVED":
        return
    order["review_status"] = "REREVIEW_REQUIRED"
    touch(order)

    # hop 4 -- TEXTURE rules are superseded and the tray card is held
    for rule in db.substitution_rules.values():
        if (
            rule["resident_id"] == resident["id"]
            and rule["trigger_type"] == "TEXTURE"
            and rule["status"] == "ACTIVE"
        ):
            rule["status"] = "SUPERSEDED"
            touch(rule)
    if resident["tray_card_state"] == "CLEAR":
        resident["tray_card_state"] = "HOLD_PENDING_REVIEW"
        touch(resident)
