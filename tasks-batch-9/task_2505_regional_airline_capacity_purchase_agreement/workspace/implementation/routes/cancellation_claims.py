"""Cancellation claims: classification, dispute and finalization (PRD 3.5)."""

from flask import Blueprint

import calc
import derive
import enums
import lookup
import validate
from auth import (ROLE_CPA_ADMINISTRATOR, ROLE_MAINLINE_SCHEDULER,
                  ROLE_REGIONAL_OPS_CONTROLLER, any_role, require)
from db import public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("cancellation_claims", __name__)

LIST_FILTERS = (
    ("cycle_id", "cycle_id", None),
    ("leg_id", "leg_id", None),
    ("status", "status", enums.CLAIM_STATUS),
    ("classification", "classification", enums.CLASSIFICATION),
)


def _cycle_of(claim):
    return store.schedule_cycles[claim["cycle_id"]]


@bp.route("/cancellation-claims", methods=["GET"])
@any_role()
def list_claims():
    return collection_listing("cancellation_claims", LIST_FILTERS)


@bp.route("/cancellation-claims/<claim_id>", methods=["GET"])
@any_role()
def read_claim(claim_id):
    return object_response(public(lookup.cancellation_claim(claim_id)))


@bp.route("/cancellation-claims/<claim_id>/classify", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def classify_claim(claim_id):
    claim = lookup.cancellation_claim(claim_id)
    data = validate.body()
    classification = validate.enum_field(data, "classification", enums.CLASSIFICATION)

    guard_terminal(claim, enums.CLAIM_TERMINAL)
    guard_state(claim["status"] in ("OPEN", "DISPUTED"))

    # The verdict is recorded but effective_classification stays pinned to
    # CONTROLLABLE until finalization, so no cycle counter moves here.
    claim["classification"] = classification
    claim["status"] = "CLASSIFIED"
    touch(claim)

    return object_response(public(claim))


@bp.route("/cancellation-claims/<claim_id>/dispute", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def dispute_claim(claim_id):
    claim = lookup.cancellation_claim(claim_id)
    data = validate.body()
    dispute_note = validate.string_field(data, "dispute_note")

    guard_terminal(claim, enums.CLAIM_TERMINAL)
    guard_state(claim["status"] == "CLASSIFIED")

    if claim["dispute_round"] >= calc.MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED")

    claim["status"] = "DISPUTED"
    claim["dispute_note"] = dispute_note
    claim["dispute_round"] += 1
    touch(claim)

    return object_response(public(claim))


@bp.route("/cancellation-claims/<claim_id>/finalize", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def finalize_claim(claim_id):
    claim = lookup.cancellation_claim(claim_id)

    guard_terminal(claim, enums.CLAIM_TERMINAL)
    guard_state(claim["status"] == "CLASSIFIED" and claim["classification"] is not None,
                "A claim can only be finalized from CLASSIFIED with a verdict")

    # Hop 1: lock the verdict into the attribution the settlement uses.
    claim["status"] = "FINALIZED"
    claim["effective_classification"] = claim["classification"]
    touch(claim)

    # Hops 2-5: counters move, the scorecard goes STALE, its invoices are voided
    # and any settled money unwinds.
    derive.refresh_cycle(_cycle_of(claim), cascade=True)

    return object_response(public(claim))
