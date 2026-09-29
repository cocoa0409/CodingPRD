"""Pass-through cost claims: estimate, actual and adjudication (PRD 3.6)."""

from flask import Blueprint

import calc
import derive
import enums
import lookup
import validate
from auth import (ROLE_CPA_ADMINISTRATOR, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  current_user_id, require)
from core import round2
from db import new_entity, public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("passthrough", __name__)

LIST_FILTERS = (
    ("cycle_id", "cycle_id", None),
    ("category", "category", enums.PASSTHROUGH_CATEGORY),
    ("status", "status", enums.PASSTHROUGH_STATUS),
)

LIVE_STATUSES = ("SUBMITTED", "ACTUAL_SUBMITTED", "RECONCILED")


def _cycle_of(claim):
    return store.schedule_cycles[claim["cycle_id"]]


@bp.route("/pass-through-claims", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def open_claim():
    data = validate.body()
    cycle_id = validate.string_field(data, "cycle_id")
    cycle = lookup.reference("schedule_cycles", cycle_id)

    category = validate.enum_field(data, "category", enums.PASSTHROUGH_CATEGORY)
    estimated_amount_usd = validate.money_field(data, "estimated_amount_usd")

    # One live claim per category per month; a REJECTED claim frees the category.
    for other in store.passthrough_claims.values():
        if (other["cycle_id"] == cycle["id"] and other["category"] == category
                and other["status"] != "REJECTED"):
            fail("ERR_DUPLICATE_PASSTHROUGH_CATEGORY")

    claim = new_entity({
        "cycle_id": cycle["id"],
        "category": category,
        "estimated_amount_usd": estimated_amount_usd,
        "actual_amount_usd": None,
        "supporting_doc_ref": None,
        "allowed_amount_usd": None,
        "variance_usd": None,
        "status": "SUBMITTED",
        "actual_submitted_by_user_id": None,
        "reconciled_by_user_id": None,
    })
    store.passthrough_claims[claim["id"]] = claim

    derive.refresh_cycle(cycle)

    return object_response(public(claim), 201)


@bp.route("/pass-through-claims", methods=["GET"])
@any_role()
def list_claims():
    return collection_listing("passthrough_claims", LIST_FILTERS)


@bp.route("/pass-through-claims/<claim_id>", methods=["GET"])
@any_role()
def read_claim(claim_id):
    return object_response(public(lookup.passthrough_claim(claim_id)))


@bp.route("/pass-through-claims/<claim_id>/submit-actual", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER, ROLE_CPA_ADMINISTRATOR)
def submit_actual(claim_id):
    claim = lookup.passthrough_claim(claim_id)
    data = validate.body()
    actual_amount_usd = validate.money_field(data, "actual_amount_usd")
    supporting_doc_ref = validate.string_field(data, "supporting_doc_ref")

    guard_terminal(claim, enums.PASSTHROUGH_TERMINAL)
    guard_state(claim["status"] == "SUBMITTED")
    cycle = _cycle_of(claim)
    guard_state(cycle["status"] in ("OPEN", "CLOSED"),
                "The settlement month does not accept actuals")

    claim["actual_amount_usd"] = actual_amount_usd
    claim["supporting_doc_ref"] = supporting_doc_ref
    claim["variance_usd"] = round2(actual_amount_usd - claim["estimated_amount_usd"])
    claim["status"] = "ACTUAL_SUBMITTED"
    claim["actual_submitted_by_user_id"] = current_user_id()
    touch(claim)

    return object_response(public(claim))


@bp.route("/pass-through-claims/<claim_id>/reconcile", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def reconcile_claim(claim_id):
    claim = lookup.passthrough_claim(claim_id)
    data = validate.body()
    decision = validate.enum_field(data, "decision", enums.RECONCILE_DECISION)

    guard_terminal(claim, enums.PASSTHROUGH_TERMINAL)
    guard_state(claim["status"] == "ACTUAL_SUBMITTED")

    if current_user_id() == claim["actual_submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        claim["status"] = "RECONCILED"
        claim["allowed_amount_usd"] = calc.passthrough_allowed_amount(claim)
    else:
        claim["status"] = "REJECTED"
        claim["allowed_amount_usd"] = None
    claim["reconciled_by_user_id"] = current_user_id()
    touch(claim)

    # Both the month's estimated total and its settlement are rebuilt on the spot,
    # and the month's version moves either way (PRD 3.6).
    cycle = _cycle_of(claim)
    derive.recompute_cycle(cycle)
    touch(cycle)

    return object_response(public(claim))
