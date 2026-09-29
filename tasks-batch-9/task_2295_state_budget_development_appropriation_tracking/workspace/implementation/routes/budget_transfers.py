"""Budget transfers: authority movement under OCC on the source appropriation."""

from flask import Blueprint

import auth
import clock
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
    read_enum,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("budget_transfers", __name__)


def _resync(transfer, source, target):
    """Recompute both sides of a transfer, bumping each appropriation exactly once."""
    cycles = [
        core.get_cycle(source["budget_cycle_id"]),
        core.get_cycle(target["budget_cycle_id"]),
    ]
    core.sync_many(
        cycles,
        touch_cycle=False,
        force_appr=(source["id"], target["id"]),
    )


@bp.post("/fiscal/budget-transfers")
def propose_transfer():
    actor = auth.authenticate((auth.BUDGET_ANALYST, auth.BUDGET_DIRECTOR))
    body = body_json()

    source = peek_fk(body, "source_appropriation_id", core.get_appropriation)
    target = peek_fk(body, "target_appropriation_id", core.get_appropriation)

    read_id(body, "source_appropriation_id")
    read_id(body, "target_appropriation_id")
    amount_cents = read_int(body, "amount_cents")
    transfer_type = read_enum(body, "transfer_type", C.TRANSFER_TYPES)
    justification = read_str(body, "justification", min_len=1, max_len=500)
    expected_version = read_int(body, "expected_source_appropriation_version")
    if amount_cents <= 0:
        bad_amount("amount_cents must be greater than zero.")

    if expected_version != source["version"]:
        fail(
            "ERR_STALE_VERSION",
            "Source appropriation version is %d, not %d."
            % (source["version"], expected_version),
        )

    core.require_not_closed(core.get_cycle(source["budget_cycle_id"]))
    core.require_not_closed(core.get_cycle(target["budget_cycle_id"]))

    if source["id"] == target["id"]:
        fail(
            "ERR_TRANSFER_SAME_APPROPRIATION",
            "The source and target appropriation must differ.",
        )
    if source["fund_type"] != target["fund_type"]:
        fail(
            "ERR_TRANSFER_FUND_TYPE_MISMATCH",
            "Both appropriations must share the same fund_type.",
        )
    same_agency = source["agency_id"] == target["agency_id"]
    if transfer_type == "INTRA_AGENCY" and not same_agency:
        fail(
            "ERR_TRANSFER_TYPE_MISMATCH",
            "INTRA_AGENCY requires both appropriations to share an agency.",
        )
    if transfer_type == "INTER_AGENCY" and same_agency:
        fail(
            "ERR_TRANSFER_TYPE_MISMATCH",
            "INTER_AGENCY requires the appropriations to belong to different agencies.",
        )

    cap = calc.transfer_cap(source)
    if amount_cents > cap:
        fail(
            "ERR_TRANSFER_EXCEEDS_AUTHORITY_CAP",
            "Amount %d exceeds the statutory transfer cap of %d." % (amount_cents, cap),
        )
    if amount_cents > source["available_authority_cents"]:
        fail(
            "ERR_TRANSFER_EXCEEDS_AVAILABLE",
            "Amount %d exceeds the source available authority of %d."
            % (amount_cents, source["available_authority_cents"]),
        )

    row = db.new_row()
    row.update(
        {
            "source_appropriation_id": source["id"],
            "target_appropriation_id": target["id"],
            "amount_cents": amount_cents,
            "transfer_type": transfer_type,
            "justification": justification,
            "status": "PROPOSED",
            "proposed_by_user_id": actor.user_id,
            "approved_by_user_id": None,
            "decision_reason": None,
            "executed_at": None,
        }
    )
    db.budget_transfers[row["id"]] = row
    db.touch(source)
    return response.created(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>/budget-transfers")
def list_transfers(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    appropriation = core.get_appropriation(appropriation_id)
    side = query_enum("side", C.TRANSFER_SIDES)
    status = query_enum("status", C.TRANSFER_STATUSES)
    rows = []
    for row in db.budget_transfers.values():
        is_source = row["source_appropriation_id"] == appropriation["id"]
        is_target = row["target_appropriation_id"] == appropriation["id"]
        if not is_source and not is_target:
            continue
        if side == "SOURCE" and not is_source:
            continue
        if side == "TARGET" and not is_target:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/budget-transfers/<transfer_id>/approve")
def approve_transfer(transfer_id):
    actor = auth.authenticate((auth.BUDGET_DIRECTOR,))
    row = core.get_transfer(transfer_id)
    source = core.get_appropriation(row["source_appropriation_id"])
    core.require_not_closed(core.get_cycle(source["budget_cycle_id"]))

    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED transfer may be approved.")
    if source["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The source appropriation is not ENACTED.")
    if actor.user_id == row["proposed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The proposer of a transfer may not approve it.",
        )
    if row["amount_cents"] > source["available_authority_cents"]:
        fail(
            "ERR_TRANSFER_EXCEEDS_AVAILABLE",
            "Amount %d exceeds the source available authority of %d."
            % (row["amount_cents"], source["available_authority_cents"]),
        )

    db.apply_changes(row, {"status": "APPROVED", "approved_by_user_id": actor.user_id})
    return response.ok(db.serialize(row))


@bp.post("/fiscal/budget-transfers/<transfer_id>/reject")
def reject_transfer(transfer_id):
    auth.authenticate((auth.BUDGET_DIRECTOR,))
    row = core.get_transfer(transfer_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)

    source = core.get_appropriation(row["source_appropriation_id"])
    core.require_not_closed(core.get_cycle(source["budget_cycle_id"]))
    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED transfer may be rejected.")

    db.apply_changes(row, {"status": "REJECTED", "decision_reason": reason})
    return response.ok(db.serialize(row))


@bp.post("/fiscal/budget-transfers/<transfer_id>/execute")
def execute_transfer(transfer_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_transfer(transfer_id)
    source = core.get_appropriation(row["source_appropriation_id"])
    target = core.get_appropriation(row["target_appropriation_id"])
    core.require_not_closed(core.get_cycle(source["budget_cycle_id"]))
    core.require_not_closed(core.get_cycle(target["budget_cycle_id"]))

    if row["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED transfer may be executed.")
    if target["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The target appropriation is not ENACTED.")
    if row["amount_cents"] > source["available_authority_cents"]:
        fail(
            "ERR_TRANSFER_EXCEEDS_AVAILABLE",
            "Amount %d exceeds the source available authority of %d."
            % (row["amount_cents"], source["available_authority_cents"]),
        )

    db.apply_changes(
        row, {"status": "EXECUTED", "executed_at": clock.fmt(clock.get_now())}
    )
    _resync(row, source, target)
    core.recompute_grants_and_agencies(core.impair_commitments(source))
    return response.ok(db.serialize(row))


@bp.post("/fiscal/budget-transfers/<transfer_id>/reverse")
def reverse_transfer(transfer_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_transfer(transfer_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)

    source = core.get_appropriation(row["source_appropriation_id"])
    target = core.get_appropriation(row["target_appropriation_id"])
    core.require_phase(core.get_cycle(source["budget_cycle_id"]), ("EXECUTION",))
    core.require_phase(core.get_cycle(target["budget_cycle_id"]), ("EXECUTION",))

    if row["status"] != "EXECUTED":
        fail("ERR_INVALID_STATE", "Only an EXECUTED transfer may be reversed.")
    if target["available_authority_cents"] < row["amount_cents"]:
        fail(
            "ERR_TRANSFER_EXCEEDS_AVAILABLE",
            "The target no longer holds the %d of authority to give back."
            % row["amount_cents"],
        )

    db.apply_changes(row, {"status": "REVERSED", "decision_reason": reason})
    _resync(row, source, target)
    core.recompute_grants_and_agencies(core.restore_commitments(source))
    return response.ok(db.serialize(row))
