"""PRD 3.8 -- casting weighted endorsements in the open round."""

from flask import Blueprint

import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_JURISDICTION_DELEGATE, guard, require_owned_jurisdiction
from core import clock
from errors import fail

bp = Blueprint("endorsements", __name__)

# SUPERSEDED is never supplied by a client; only the cascade writes it.
CASTABLE_DECISIONS = ("ENDORSED", "CONDITIONED", "VETOED")


@bp.post("/resilience/plan-cycles/<plan_cycle_id>/endorsements")
@guard(ROLE_JURISDICTION_DELEGATE)
def cast_endorsement(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    body = validate.json_body()
    jurisdiction = lookup.need_ref("jurisdiction", body, "jurisdiction_id")
    if jurisdiction is None:
        validate.bad("jurisdiction_id", "is required.")
    require_owned_jurisdiction(jurisdiction["id"], roles=(ROLE_JURISDICTION_DELEGATE,))

    decision = validate.enum_field(body, "decision", CASTABLE_DECISIONS, required=True)
    note = validate.string_field(body, "condition_note", min_len=1, max_len=500)
    if decision != "CONDITIONED" and note is not None:
        validate.bad("condition_note", "must be absent unless the decision is CONDITIONED.")

    if jurisdiction["status"] != "ACTIVE":
        fail("ERR_JURISDICTION_NOT_ACTIVE", "The casting jurisdiction is not ACTIVE.")
    if cycle["status"] != "ENDORSEMENT_ROUND":
        fail("ERR_PLAN_CYCLE_STATE_INVALID", "The cycle has no open endorsement round.")
    for row in lookup.endorsements_of_cycle(cycle["id"], cycle["round_number"]):
        if row["jurisdiction_id"] == jurisdiction["id"] and row["decision"] in cascades.LIVE_DECISIONS:
            fail(
                "ERR_DUPLICATE_ENDORSEMENT",
                "This jurisdiction has already cast a live endorsement in this round.",
            )
    if decision == "CONDITIONED" and note is None:
        fail(
            "ERR_CONDITION_NOTE_REQUIRED",
            "condition_note is required when the decision is CONDITIONED.",
        )

    record = store.insert(store.endorsements, {
        "plan_cycle_id": cycle["id"],
        "jurisdiction_id": jurisdiction["id"],
        "round_number": cycle["round_number"],
        "decision": decision,
        "condition_note": note,
        "weight_at_cast": jurisdiction["endorsement_weight"],
        "cast_at": clock.now(),
    })
    return envelope.created(serialize.endorsement(record))


@bp.get("/resilience/endorsements")
@guard()
def list_endorsements():
    rows = envelope.match(
        store.ordered(store.endorsements),
        plan_cycle_id=envelope.str_filter("plan_cycle_id"),
        jurisdiction_id=envelope.str_filter("jurisdiction_id"),
        decision=envelope.str_filter("decision"),
        round_number=envelope.int_filter("round_number"),
    )
    return envelope.listing(rows, serialize.endorsement)


@bp.get("/resilience/endorsements/<endorsement_id>")
@guard()
def get_endorsement(endorsement_id):
    row = lookup.need("endorsement", endorsement_id)
    return envelope.ok(serialize.endorsement(row))
