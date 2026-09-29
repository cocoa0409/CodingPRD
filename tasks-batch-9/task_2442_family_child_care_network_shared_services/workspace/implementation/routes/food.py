"""PRD 3.5 food program claiming and meal reimbursement."""
from flask import Blueprint

import auth
import calculations as calc
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("food", __name__)

MEAL_COUNT_MAX = 2
DAILY_MEAL_CAP = 2
DAILY_SNACK_CAP = 1


def _food_claim(actor, claim_id):
    row = services.find_or_404(
        db.food_claims, claim_id, "ERR_FOOD_CLAIM_NOT_FOUND", "food program claim"
    )
    auth.scope_provider(actor, row["provider_id"])
    return row


@bp.post("/fccn/food-program-claims")
def file_food_claim():
    actor = auth.require_auth(("Provider",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    auth.scope_provider(actor, provider_id)
    provider = services.provider_or_404(provider_id)

    raw_lines = v.req_array(body, "meal_lines")
    meal_lines = []
    for item in raw_lines:
        meal_lines.append({
            "child_ref": v.obj_str(item, "child_ref", "meal_lines"),
            "service_date": v.obj_str(item, "service_date", "meal_lines"),
            "breakfasts": v.obj_int(item, "breakfasts", "meal_lines", 0, MEAL_COUNT_MAX)
            if "breakfasts" in item and item["breakfasts"] is not None else 0,
            "lunches": v.obj_int(item, "lunches", "meal_lines", 0, MEAL_COUNT_MAX)
            if "lunches" in item and item["lunches"] is not None else 0,
            "snacks": v.obj_int(item, "snacks", "meal_lines", 0, MEAL_COUNT_MAX)
            if "snacks" in item and item["snacks"] is not None else 0,
        })
    for line in meal_lines:
        if clock.parse_instant(line["service_date"]) is None:
            v.bad("Each meal line requires an ISO 8601 'service_date'.")
    period_month = v.req_period_month(body, "period_month")
    v.reject_unversioned(body)

    already = [
        f for f in services.provider_children(db.food_claims, provider["id"])
        if f["period_month"] == period_month
    ]
    if already:
        v.bad("This provider has already claimed the month %s." % period_month)

    services.check_posture(provider, restricted_blocks=False)

    known_refs = set(
        e["child_ref"] for e in services.provider_children(db.enrollments, provider["id"])
    )
    for line in meal_lines:
        if line["child_ref"] not in known_refs:
            raise ApiError(
                "ERR_MEAL_LINE_CHILD_UNKNOWN",
                "child_ref '%s' matches no enrollment of this provider." % line["child_ref"],
            )

    per_child_day = {}
    for line in meal_lines:
        key = (line["child_ref"], clock.date_of(line["service_date"]))
        bucket = per_child_day.setdefault(key, {"meals": 0, "snacks": 0})
        bucket["meals"] += line["breakfasts"] + line["lunches"]
        bucket["snacks"] += line["snacks"]
    for bucket in per_child_day.values():
        if bucket["meals"] > DAILY_MEAL_CAP or bucket["snacks"] > DAILY_SNACK_CAP:
            raise ApiError(
                "ERR_MEAL_CAP_EXCEEDED",
                "A child may claim at most two meals and one snack per service date.",
            )

    tiering = calc.food_program_tiering(provider, meal_lines)
    row = db.make_row(
        provider_id=provider["id"],
        period_month=period_month,
        meal_lines=meal_lines,
        tier_applied=tiering["tier_applied"],
        subsidy_enrollment_share=tiering["subsidy_enrollment_share"],
        claimed_amount_cents=tiering["claimed_amount_cents"],
        reimbursed_amount_cents=0,
        disallowed_child_refs=[],
        status="SUBMITTED",
    )
    services.register_new(row)
    db.food_claims[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/food-program-claims/<claim_id>/approve")
def approve_food_claim(claim_id):
    auth.require_auth(("FiscalOfficer",))
    claim = services.find_or_404(
        db.food_claims, claim_id, "ERR_FOOD_CLAIM_NOT_FOUND", "food program claim"
    )
    body = v.get_body()
    v.reject_unversioned(body)
    disallowed = v.opt_array(body, "disallowed_child_refs", None)
    if disallowed is not None:
        for item in disallowed:
            if not isinstance(item, str) or item == "":
                v.bad("'disallowed_child_refs' must contain non-empty strings.")

    if claim["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "Only a SUBMITTED food program claim may be approved."
        )

    if not disallowed:
        claim["status"] = "APPROVED"
        claim["reimbursed_amount_cents"] = claim["claimed_amount_cents"]
    else:
        present = set(line["child_ref"] for line in claim["meal_lines"])
        for ref in disallowed:
            if ref not in present:
                v.bad("Disallowed child_ref '%s' appears on no meal line of this claim." % ref)
        removed = sum(
            calc.meal_line_amount(line, claim["tier_applied"])
            for line in claim["meal_lines"]
            if line["child_ref"] in disallowed
        )
        claim["disallowed_child_refs"] = list(disallowed)
        claim["status"] = "APPROVED_WITH_DISALLOWANCE"
        claim["reimbursed_amount_cents"] = claim["claimed_amount_cents"] - removed
    services.touch(claim)
    services.recompute_revenue(db.providers[claim["provider_id"]])
    return response.ok(claim)


@bp.get("/fccn/food-program-claims/<claim_id>")
def read_food_claim(claim_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return response.ok(_food_claim(actor, claim_id))
