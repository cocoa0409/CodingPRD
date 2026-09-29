"""Allotments: the quarterly cash release pipeline."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import calc
from services import constants as C
from services import core
from validators import (
    bad_amount,
    body_json,
    listing,
    peek_fk,
    query_enum,
    query_int,
    read_bool,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("allotments", __name__)

_OCCUPYING = ("DRAFT", "PREPARED", "APPROVED", "RELEASED")


@bp.post("/fiscal/allotments")
def create_allotment():
    auth.authenticate((auth.BUDGET_ANALYST,))
    body = body_json()

    appropriation = peek_fk(body, "appropriation_id", core.get_appropriation)

    read_id(body, "appropriation_id")
    quarter = read_int(body, "quarter")
    requested_cents = read_int(body, "requested_cents")
    allow_partial = read_bool(body, "allow_partial", required=False, default=False)
    if quarter < 1 or quarter > 4:
        bad_amount("quarter must be between 1 and 4.")
    if requested_cents <= 0:
        bad_amount("requested_cents must be greater than zero.")

    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_not_closed(cycle)
    core.check_quarter(cycle, quarter, exact=False)

    for existing in db.allotments.values():
        if (
            existing["appropriation_id"] == appropriation["id"]
            and existing["quarter"] == quarter
            and existing["status"] in _OCCUPYING
        ):
            fail(
                "ERR_ALLOTMENT_QUARTER_OCCUPIED",
                "Quarter %d of this appropriation already has an active allotment." % quarter,
            )

    row = db.new_row()
    row.update(
        {
            "appropriation_id": appropriation["id"],
            "quarter": quarter,
            "requested_cents": requested_cents,
            "allow_partial": allow_partial,
            "computed_release_cents": 0,
            "binding_constraint": None,
            "released_cents": 0,
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "approved_by_user_id": None,
            "recall_reason": None,
        }
    )
    db.allotments[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/allotments/<allotment_id>")
def read_allotment(allotment_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_allotment(allotment_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>/allotments")
def list_allotments(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    appropriation = core.get_appropriation(appropriation_id)
    status = query_enum("status", C.ALLOTMENT_STATUSES)
    quarter = query_int("quarter", minimum=1, maximum=4)
    rows = []
    for row in db.allotments.values():
        if row["appropriation_id"] != appropriation["id"]:
            continue
        if status is not None and row["status"] != status:
            continue
        if quarter is not None and row["quarter"] != quarter:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/allotments/<allotment_id>/prepare")
def prepare_allotment(allotment_id):
    actor = auth.authenticate((auth.BUDGET_ANALYST, auth.BUDGET_DIRECTOR))
    row = core.get_allotment(allotment_id)
    appropriation = core.get_appropriation(row["appropriation_id"])
    cycle = core.get_cycle(appropriation["budget_cycle_id"])

    core.require_phase(cycle, ("EXECUTION",))
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT allotment may be prepared.")
    if appropriation["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The appropriation is not ENACTED.")
    if appropriation["cash_status"] == "FROZEN":
        fail("ERR_CASH_FROZEN", "Cash is frozen on this appropriation.")
    if appropriation["release_hold"]:
        fail("ERR_RELEASE_HOLD_ACTIVE", "A release hold is active on this appropriation.")

    ceiling, binding = calc.release_ceiling(row, appropriation, cycle)
    if ceiling <= 0:
        fail("ERR_NO_RELEASE_CAPACITY", "The computed release ceiling is not positive.")
    if not row["allow_partial"] and ceiling < row["requested_cents"]:
        fail(
            "ERR_ALLOTMENT_EXCEEDS_CEILING",
            "The ceiling of %d is below the requested %d and allow_partial is false."
            % (ceiling, row["requested_cents"]),
        )

    db.apply_changes(
        row,
        {
            "computed_release_cents": ceiling,
            "binding_constraint": binding,
            "prepared_by_user_id": actor.user_id,
            "status": "PREPARED",
        },
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/allotments/<allotment_id>/approve")
def approve_allotment(allotment_id):
    actor = auth.authenticate((auth.BUDGET_DIRECTOR,))
    row = core.get_allotment(allotment_id)
    appropriation = core.get_appropriation(row["appropriation_id"])
    core.require_not_closed(core.get_cycle(appropriation["budget_cycle_id"]))

    if row["status"] != "PREPARED":
        fail("ERR_INVALID_STATE", "Only a PREPARED allotment may be approved.")
    if appropriation["cash_status"] == "FROZEN":
        fail("ERR_CASH_FROZEN", "Cash is frozen on this appropriation.")
    if actor.user_id == row["prepared_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The preparer of an allotment may not approve it.",
        )

    db.apply_changes(row, {"approved_by_user_id": actor.user_id, "status": "APPROVED"})
    return response.ok(db.serialize(row))


@bp.post("/fiscal/allotments/<allotment_id>/release")
def release_allotment(allotment_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_allotment(allotment_id)
    appropriation = core.get_appropriation(row["appropriation_id"])
    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_not_closed(cycle)

    if row["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED allotment may be released.")
    if appropriation["cash_status"] == "FROZEN":
        fail("ERR_CASH_FROZEN", "Cash is frozen on this appropriation.")
    core.check_quarter(cycle, row["quarter"], exact=True)

    db.apply_changes(
        row,
        {"released_cents": row["computed_release_cents"], "status": "RELEASED"},
    )
    core.sync(
        cycle,
        derive_cash_for=(appropriation["id"],),
        force_cycle=True,
        force_appr=(appropriation["id"],),
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/allotments/<allotment_id>/recall")
def recall_allotment(allotment_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_allotment(allotment_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)

    appropriation = core.get_appropriation(row["appropriation_id"])
    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_not_closed(cycle)

    if row["status"] != "RELEASED":
        fail("ERR_INVALID_STATE", "Only a RELEASED allotment may be recalled.")
    if appropriation["available_cash_cents"] - row["released_cents"] < 0:
        fail(
            "ERR_INSUFFICIENT_CASH_RELEASED",
            "Recalling this allotment would push released cash below expenditures.",
        )

    db.apply_changes(
        row, {"released_cents": 0, "status": "RECALLED", "recall_reason": reason}
    )
    core.sync(
        cycle,
        derive_cash_for=(appropriation["id"],),
        force_cycle=True,
        force_appr=(appropriation["id"],),
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/allotments/<allotment_id>/cancel")
def cancel_allotment(allotment_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_allotment(allotment_id)
    appropriation = core.get_appropriation(row["appropriation_id"])
    core.require_not_closed(core.get_cycle(appropriation["budget_cycle_id"]))

    if row["status"] not in ("DRAFT", "PREPARED"):
        fail(
            "ERR_INVALID_STATE",
            "An allotment in status %s may not be cancelled." % row["status"],
        )

    changed = db.apply_changes(
        row,
        {"status": "CANCELLED", "computed_release_cents": 0, "binding_constraint": None},
    )
    if not changed:
        db.touch(row)
    return response.ok(db.serialize(row))
