"""Appropriations: the two independent status dimensions, enactment, emergency
grants, cash freezes and the dual-basis balance summary.
"""

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
    query_str,
    read_enum,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("appropriations", __name__)


def _blank_ledger():
    return {
        "transfers_in_cents": 0,
        "transfers_out_cents": 0,
        "released_cents": 0,
        "expended_cents": 0,
        "reverted_cents": 0,
        "carryforward_cents": 0,
        "available_cash_cents": 0,
    }


@bp.post("/fiscal/appropriations")
def create_appropriation():
    auth.authenticate((auth.LEGISLATIVE_FISCAL_OFFICER,))
    body = body_json()

    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)
    agency = peek_fk(body, "agency_id", core.get_agency)

    read_id(body, "budget_cycle_id")
    read_id(body, "agency_id")
    fund_type = read_enum(body, "fund_type", C.FUND_TYPES)
    program_code = read_str(body, "program_code", min_len=1, max_len=32)
    introduced = read_int(body, "introduced_amount_cents")
    if introduced < 0:
        fail("ERR_INVALID_REQUEST", "introduced_amount_cents must be zero or positive.")

    core.require_not_closed(cycle)

    for existing in db.appropriations.values():
        if (
            existing["budget_cycle_id"] == cycle["id"]
            and existing["agency_id"] == agency["id"]
            and existing["program_code"] == program_code
        ):
            fail(
                "ERR_DUPLICATE_CODE",
                "program_code '%s' is already used by this agency in this cycle."
                % program_code,
            )

    row = db.new_row()
    row.update(_blank_ledger())
    row.update(
        {
            "budget_cycle_id": cycle["id"],
            "agency_id": agency["id"],
            "fund_type": fund_type,
            "program_code": program_code,
            "introduced_amount_cents": introduced,
            "committee_balance_cents": introduced,
            "enacted_amount_cents": 0,
            "available_authority_cents": 0,
            "authority_status": "PENDING",
            "cash_status": "UNRELEASED",
            "pre_freeze_cash_status": None,
            "release_hold": core.initial_release_hold(cycle, fund_type, "UNRELEASED"),
            "is_emergency": False,
            "freeze_reason": None,
        }
    )
    db.appropriations[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>")
def read_appropriation(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_appropriation(appropriation_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/appropriations")
def list_appropriations():
    auth.authenticate(auth.ANY_ROLE)
    cycle_id = query_str("budget_cycle_id")
    agency_id = query_str("agency_id")
    fund_type = query_enum("fund_type", C.FUND_TYPES)
    authority_status = query_enum("authority_status", C.AUTHORITY_STATUSES)
    rows = []
    for row in db.appropriations.values():
        if cycle_id is not None and row["budget_cycle_id"] != cycle_id:
            continue
        if agency_id is not None and row["agency_id"] != agency_id:
            continue
        if fund_type is not None and row["fund_type"] != fund_type:
            continue
        if authority_status is not None and row["authority_status"] != authority_status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/appropriations/<appropriation_id>/enact")
def enact_appropriation(appropriation_id):
    auth.authenticate((auth.LEGISLATIVE_FISCAL_OFFICER,))
    row = core.get_appropriation(appropriation_id)
    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_phase(cycle, ("LEGISLATIVE",))
    if row["authority_status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING appropriation may be enacted.")

    balance = row["committee_balance_cents"]
    core.sync(
        cycle,
        appr_extra={
            row["id"]: {
                "enacted_amount_cents": balance,
                "authority_status": "ENACTED" if balance > 0 else "LAPSED",
            }
        },
        touch_cycle=False,
        force_appr=(row["id"],),
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/appropriations/emergency")
def emergency_appropriation():
    auth.authenticate((auth.BUDGET_DIRECTOR,))
    body = body_json()

    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)
    agency = peek_fk(body, "agency_id", core.get_agency)

    read_id(body, "budget_cycle_id")
    read_id(body, "agency_id")
    program_code = read_str(body, "program_code", min_len=1, max_len=32)
    requested = read_int(body, "requested_amount_cents")
    read_str(body, "justification", min_len=1, max_len=500)
    if requested <= 0:
        bad_amount("requested_amount_cents must be greater than zero.")

    core.require_phase(cycle, ("EXECUTION",))

    capacity = calc.emergency_capacity(cycle)
    if requested > capacity:
        fail(
            "ERR_EMERGENCY_EXCEEDS_RESERVE_CAPACITY",
            "Requested %d exceeds the remaining emergency capacity of %d."
            % (requested, capacity),
        )

    row = db.new_row()
    row.update(_blank_ledger())
    row.update(
        {
            "budget_cycle_id": cycle["id"],
            "agency_id": agency["id"],
            "fund_type": "GENERAL",
            "program_code": program_code,
            "introduced_amount_cents": requested,
            "committee_balance_cents": requested,
            "enacted_amount_cents": requested,
            "available_authority_cents": requested,
            "authority_status": "ENACTED",
            "cash_status": "UNRELEASED",
            "pre_freeze_cash_status": None,
            "release_hold": core.initial_release_hold(cycle, "GENERAL", "UNRELEASED"),
            "is_emergency": True,
            "freeze_reason": None,
        }
    )
    db.appropriations[row["id"]] = row
    core.sync(cycle, force_cycle=True)
    return response.created(db.serialize(row))


@bp.post("/fiscal/appropriations/<appropriation_id>/freeze-cash")
def freeze_cash(appropriation_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_appropriation(appropriation_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)

    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_not_closed(cycle)
    if row["cash_status"] not in ("UNRELEASED", "PARTIALLY_RELEASED", "FULLY_RELEASED"):
        fail("ERR_INVALID_STATE", "Cash is already FROZEN on this appropriation.")
    if row["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The appropriation is not ENACTED.")

    core.sync(
        cycle,
        appr_extra={
            row["id"]: {
                "pre_freeze_cash_status": row["cash_status"],
                "cash_status": "FROZEN",
                "freeze_reason": reason,
            }
        },
        touch_cycle=False,
        force_appr=(row["id"],),
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/appropriations/<appropriation_id>/unfreeze-cash")
def unfreeze_cash(appropriation_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    row = core.get_appropriation(appropriation_id)
    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_not_closed(cycle)
    if row["cash_status"] != "FROZEN":
        fail("ERR_INVALID_STATE", "Cash is not FROZEN on this appropriation.")

    figures, authority = core.ledger_figures(row)
    recomputed = core.derive_cash_status(figures["released_cents"], authority)
    core.sync(
        cycle,
        appr_extra={row["id"]: {"cash_status": recomputed, "freeze_reason": None}},
        touch_cycle=False,
        force_appr=(row["id"],),
    )
    return response.ok(db.serialize(row))


@bp.get("/fiscal/appropriations/<appropriation_id>/balance-summary")
def balance_summary(appropriation_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_appropriation(appropriation_id)
    authority = core.authority_of(row)
    available_cash = row["released_cents"] - row["expended_cents"]
    available_authority = authority - row["expended_cents"]
    return response.ok(
        {
            "appropriation_id": row["id"],
            "authority_cents": authority,
            "released_cents": row["released_cents"],
            "expended_cents": row["expended_cents"],
            "available_cash_cents": available_cash,
            "available_authority_cents": available_authority,
            "basis_delta_cents": available_authority - available_cash,
        }
    )
