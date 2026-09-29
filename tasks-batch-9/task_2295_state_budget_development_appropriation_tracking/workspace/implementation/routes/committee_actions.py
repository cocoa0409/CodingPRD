"""Committee actions: every insert replays the whole action set of the line."""

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
    page,
    peek_fk,
    read_enum,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("committee_actions", __name__)


@bp.post("/fiscal/committee-actions")
def create_action():
    auth.authenticate((auth.LEGISLATIVE_FISCAL_OFFICER,))
    body = body_json()

    appropriation = peek_fk(body, "appropriation_id", core.get_appropriation)

    read_id(body, "appropriation_id")
    chamber = read_enum(body, "chamber", C.CHAMBERS)
    committee_name = read_str(body, "committee_name", min_len=1, max_len=120)
    action_type = read_enum(body, "action_type", C.ACTION_TYPES)
    amount_cents = read_int(body, "amount_cents")
    sequence_number = read_int(body, "sequence_number")

    if action_type in ("RESTORE", "STRIKE"):
        if amount_cents != 0:
            bad_amount("amount_cents must be 0 for a %s action." % action_type)
    elif amount_cents <= 0:
        bad_amount("amount_cents must be greater than zero for a %s action." % action_type)
    if sequence_number < 1:
        bad_amount("sequence_number must be at least 1.")

    cycle = core.get_cycle(appropriation["budget_cycle_id"])
    core.require_not_closed(cycle)

    for existing in core.actions_of(appropriation["id"]):
        if existing["sequence_number"] == sequence_number:
            fail(
                "ERR_ACTION_SEQUENCE_DUPLICATE",
                "sequence_number %d is already recorded for this appropriation."
                % sequence_number,
            )

    row = db.new_row(audited=False)
    row.update(
        {
            "appropriation_id": appropriation["id"],
            "chamber": chamber,
            "committee_name": committee_name,
            "action_type": action_type,
            "amount_cents": amount_cents,
            "sequence_number": sequence_number,
            "running_balance_cents": 0,
        }
    )

    merged = core.actions_of(appropriation["id"]) + [row]
    merged.sort(key=lambda r: (r["sequence_number"], r["created_at"], r["_seq"]))
    pairs, final = calc.committee_replay(appropriation, merged)
    if pairs is None:
        fail(
            "ERR_NEGATIVE_APPROPRIATION_BALANCE",
            "The replayed committee balance would go negative.",
        )

    for action, balance in pairs:
        action["running_balance_cents"] = balance
    db.committee_actions[row["id"]] = row

    core.sync(
        cycle,
        appr_extra={appropriation["id"]: {"committee_balance_cents": final}},
        touch_cycle=False,
        force_appr=(appropriation["id"],),
    )
    return response.created(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>/committee-actions")
def list_actions(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    appropriation = core.get_appropriation(appropriation_id)
    ordered = core.actions_of(appropriation["id"])
    window, meta = page(ordered)
    return response.ok_list([db.serialize(r) for r in window], meta)
