"""Workout options and the mission impact score (PRD section 3.9)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import COMMITTEE_MEMBER, LOAN_SERVICER, READ_ALL
from errors import ApiError

bp = Blueprint("workouts", __name__)

PAYMENT_DEFERRAL = "PAYMENT_DEFERRAL"
TERM_EXTENSION = "TERM_EXTENSION"
MISSION_IMPACT_FORBEARANCE = "MISSION_IMPACT_FORBEARANCE"
PARTIAL_FORGIVENESS = "PARTIAL_FORGIVENESS"
OPTIONS = (PAYMENT_DEFERRAL, TERM_EXTENSION, MISSION_IMPACT_FORBEARANCE,
           PARTIAL_FORGIVENESS)

DISTRESSED = ("WATCH", "RESTRICTED", "WORKOUT_GATED")

SCORE_FLOORS = {
    PARTIAL_FORGIVENESS: calc.PARTIAL_FORGIVENESS_MIN_SCORE,
    MISSION_IMPACT_FORBEARANCE: calc.FORBEARANCE_MIN_SCORE,
}


@bp.route("/workout-plans", methods=["POST"])
def create_workout_plan():
    ctx = auth.authenticate((LOAN_SERVICER,))
    b = shapes.body()
    # ladder 11 then 14
    loan = resolve.loan(b.get("loan_id"))
    if loan is None:
        shapes.req_id_field(b, "loan_id")
    predecessor = resolve.workout_plan(b.get("predecessor_workout_plan_id"))
    # ladder 15
    option = shapes.req_enum(b, "option", OPTIONS)
    support_letter = shapes.req_bool(b, "denominational_support_letter")
    narrative = shapes.req_str(b, "narrative")
    expected = shapes.req_int(b, "expected_loan_version", minimum=0)
    deferral_months = None
    extension_months = None
    forgiveness_amount_cents = None
    if option == PAYMENT_DEFERRAL:
        deferral_months = shapes.req_int(b, "deferral_months", minimum=1,
                                        maximum=24)
    elif option == TERM_EXTENSION:
        extension_months = shapes.req_int(b, "extension_months", minimum=1,
                                          maximum=120)
    elif option == PARTIAL_FORGIVENESS:
        forgiveness_amount_cents = shapes.req_int(
            b, "forgiveness_amount_cents", exclusive_minimum=0)
    # ladder 16
    if expected != loan["version"]:
        raise ApiError("ERR_STALE_LOAN_VERSION")
    # ladder 25 — creation is judged by the posture clause alone
    if loan["risk_posture"] not in DISTRESSED:
        raise ApiError("ERR_WORKOUT_INVALID_STATE")
    # ladder 41
    if predecessor is not None:
        if predecessor["loan_id"] != loan["id"] or \
                predecessor["status"] != "APPROVED":
            raise ApiError("ERR_PREDECESSOR_WORKOUT_INVALID")

    application = store.loan_applications.get(loan["loan_application_id"])
    institution = store.institutions.get(
        application["institution_id"]) if application else None
    if institution is None:
        institution = {"id": None, "community_program_count": 0}
    scoring = calc.mission_score(institution, support_letter)

    row = store.base_record()
    row.update({
        "loan_id": loan["id"],
        "predecessor_workout_plan_id": predecessor["id"] if predecessor
                                       else None,
        "option": option,
        "deferral_months": deferral_months,
        "extension_months": extension_months,
        "forgiveness_amount_cents": forgiveness_amount_cents,
        "denominational_support_letter": support_letter,
        "narrative": narrative,
        "status": "PROPOSED",
        "proposed_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "approval_note": None,
    })
    row.update(scoring)
    store.workout_plans[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.workout_plan(row))


@bp.route("/workout-plans/<workout_plan_id>", methods=["GET"])
def get_workout_plan(workout_plan_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.workout_plan(workout_plan_id)
    auth.scope(ctx, auth.owner_of_workout(row))
    return envelope.ok(serializers.workout_plan(row))


@bp.route("/workout-plans", methods=["GET"])
def list_workout_plans():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(
        list(store.workout_plans.values()),
        {"loan_id": "loan_id",
         "predecessor_workout_plan_id": "predecessor_workout_plan_id",
         "option": "option",
         "status": "status"})
    return envelope.listing(envelope.sort_created_asc(rows),
                            serializers.workout_plan)


@bp.route("/workout-plans/<workout_plan_id>/approve", methods=["POST"])
def approve_workout_plan(workout_plan_id):
    ctx = auth.authenticate((COMMITTEE_MEMBER,))
    plan = resolve.workout_plan(workout_plan_id)
    b = shapes.body()
    note = shapes.opt_str(b, "approval_note")
    loan = store.loans[plan["loan_id"]]
    # ladder 25
    if plan["status"] != "PROPOSED" or loan["risk_posture"] not in DISTRESSED:
        raise ApiError("ERR_WORKOUT_INVALID_STATE")
    # ladder 44
    floor = SCORE_FLOORS.get(plan["option"])
    if floor is not None and Decimal(plan["mission_impact_score"]) < floor:
        raise ApiError("ERR_MISSION_IMPACT_SCORE_TOO_LOW")
    # ladder 51
    option = plan["option"]
    if option == PARTIAL_FORGIVENESS:
        if plan["forgiveness_amount_cents"] > loan["outstanding_principal_cents"]:
            raise ApiError("ERR_FORGIVENESS_EXCEEDS_OUTSTANDING")

    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = ctx.user_id
    if note is not None:
        plan["approval_note"] = note
    store.touch(plan)

    if option == TERM_EXTENSION:
        old_term = loan["term_months"]
        new_term = old_term + plan["extension_months"]
        old_ads = loan["annual_debt_service_cents"]
        loan["term_months"] = new_term
        loan["annual_debt_service_cents"] = int(calc.floor_money(
            Decimal(old_ads) * Decimal(old_term) / Decimal(new_term)))
    elif option == PAYMENT_DEFERRAL:
        loan["deferred_payments_count"] += plan["deferral_months"]
    elif option == PARTIAL_FORGIVENESS:
        amount = plan["forgiveness_amount_cents"]
        loan["forgiven_principal_cents"] += amount
        loan["outstanding_principal_cents"] -= amount
        application = store.loan_applications.get(loan["loan_application_id"])
        institution = store.institutions.get(
            application["institution_id"]) if application else None
        if institution is not None:
            institution["cumulative_forgiveness_cents"] = \
                institution.get("cumulative_forgiveness_cents", 0) + amount
            store.touch(institution)
    store.touch(loan)

    predecessor_id = plan.get("predecessor_workout_plan_id")
    if predecessor_id:
        predecessor = store.workout_plans.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            store.touch(predecessor)

    calc.recompute_posture(loan)
    return envelope.ok(serializers.workout_plan(plan))
