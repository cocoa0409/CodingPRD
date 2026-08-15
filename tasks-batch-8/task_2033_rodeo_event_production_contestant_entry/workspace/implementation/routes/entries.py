"""Entry endpoints: creation with fee ledger, transitions (PRD 3.2)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    ENTRY_NONTERMINAL_DUP,
    charge_entry,
    clock_before,
    get_or_404,
    refund_contribution_and_retention,
    refund_contribution_only,
    refund_full,
    release_entry_assignments,
    rodeo_of_event,
    ser,
    sorted_created,
    stamp,
    touch,
)
from util import body, pagination_args, required

bp = Blueprint("entries", __name__, url_prefix="/api")

_ACTIONS = {"CANCEL_ENTRY", "TURN_OUT", "RE_ENTER", "DRAW_OUT"}
_VALID_FROM = {
    "CANCEL_ENTRY": {"ENTERED"},
    "TURN_OUT": {"DRAWN"},
    "RE_ENTER": {"TURNED_OUT"},
    "DRAW_OUT": {"DRAWN"},
}


@bp.post("/entries")
def create_entry():
    user_id, role = auth(["EntryOffice", "Contestant"])
    data = body()
    # Ownership (priority 2): a Contestant may only enter themself.
    if role == "Contestant" and data.get("contestant_id") != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Contestant may only act on their own entries"
        )
    # Body FK existence (priority 4).
    contestant_id = data.get("contestant_id")
    rodeo_event_id = data.get("rodeo_event_id")
    if contestant_id is not None:
        get_or_404("contestants", contestant_id)
    if rodeo_event_id is not None:
        get_or_404("rodeo_events", rodeo_event_id)
    # Field shape (priority 5).
    if not isinstance(contestant_id, str):
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: contestant_id")
    if not isinstance(rodeo_event_id, str):
        raise ApiError(
            "ERR_VALIDATION", 400, "Missing required field: rodeo_event_id"
        )
    contestant = DB["contestants"][contestant_id]
    event = DB["rodeo_events"][rodeo_event_id]
    # Rodeo posture gate (priority 7).
    rodeo = rodeo_of_event(event)
    if rodeo["posture"] != "ENTRIES_OPEN":
        raise ApiError(
            "ERR_RODEO_NOT_OPEN", 409, "Entries require the rodeo to be ENTRIES_OPEN"
        )
    # Entry window against the logical clock (priority 8).
    if not clock_before(rodeo["_close_dt"]):
        raise ApiError(
            "ERR_ENTRY_WINDOW_CLOSED",
            409,
            "The logical clock is at or after entries_close_at",
        )
    # Contestant standing (priority 9).
    if contestant["status"] != "GOOD_STANDING":
        raise ApiError(
            "ERR_CONTESTANT_SUSPENDED", 409, "Contestant is not in GOOD_STANDING"
        )
    # No second non-terminal entry for the same (contestant, event) (13).
    for e in DB["entries"].values():
        if (
            e["contestant_id"] == contestant_id
            and e["rodeo_event_id"] == rodeo_event_id
            and e["status"] in ENTRY_NONTERMINAL_DUP
        ):
            raise ApiError(
                "ERR_DUPLICATE_ENTRY",
                409,
                "Contestant already holds a non-terminal entry for this event",
            )
    rec = {
        "id": new_id(),
        "contestant_id": contestant_id,
        "rodeo_event_id": rodeo_event_id,
        "status": "ENTERED",
        "entry_fee_cents": 0,
        "purse_contribution_cents": 0,
        "committee_retention_cents": 0,
        "sanction_fee_cents": 0,
        "fee_charges_cents": 0,
        "contribution_charges_cents": 0,
        "refunded_cents": 0,
        "refunded_contribution_cents": 0,
        "turn_out_reason": None,
        "vet_report_id": None,
        "_waitlisted_round": None,
    }
    charge_entry(rec, event["entry_fee_cents"])
    stamp(rec)
    DB["entries"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/entries")
def list_entries():
    auth(ALL_ROLES)
    contestant_id = request.args.get("contestant_id")
    rodeo_event_id = request.args.get("rodeo_event_id")
    status = request.args.get("status")
    vet_report_id = request.args.get("vet_report_id")
    items = DB["entries"].values()
    if contestant_id is not None:
        items = [e for e in items if e["contestant_id"] == contestant_id]
    if rodeo_event_id is not None:
        items = [e for e in items if e["rodeo_event_id"] == rodeo_event_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if vet_report_id is not None:
        items = [e for e in items if e["vet_report_id"] == vet_report_id]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(e) for e in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/entries/<entry_id>")
def get_entry(entry_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("entries", entry_id)))


@bp.post("/entries/<entry_id>/transition")
def transition_entry(entry_id):
    user_id, role = auth(["CommitteeAdmin", "EntryOffice", "Contestant"])
    entry = get_or_404("entries", entry_id)
    if role == "Contestant" and entry["contestant_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Contestant may only act on their own entries"
        )
    data = body()
    action = data.get("action")
    if action not in _ACTIONS:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field action must be one of {sorted(_ACTIONS)}"
        )
    # Per-action authorization: DRAW_OUT is CommitteeAdmin-only; the other
    # actions belong to EntryOffice or the contestant themself.
    if action == "DRAW_OUT":
        if role != "CommitteeAdmin":
            raise ApiError(
                "ERR_FORBIDDEN", 403, "DRAW_OUT is restricted to CommitteeAdmin"
            )
    elif role not in ("EntryOffice", "Contestant"):
        raise ApiError(
            "ERR_FORBIDDEN", 403, f"Role not permitted for action {action}"
        )
    # Body FK existence: vet_report_id when supplied.
    vet_report = None
    if action == "TURN_OUT":
        vet_report_id = data.get("vet_report_id")
        if vet_report_id is not None:
            vet_report = get_or_404("vet_reports", vet_report_id)
    # Field shape: TURN_OUT carries a reason of VOLUNTARY | MEDICAL.
    reason = None
    if action == "TURN_OUT":
        reason = data.get("reason")
        if reason not in ("VOLUNTARY", "MEDICAL"):
            raise ApiError(
                "ERR_VALIDATION", 400, "Field reason must be VOLUNTARY or MEDICAL"
            )
    # State-machine legality.
    if entry["status"] not in _VALID_FROM[action]:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Action {action} is not valid from status {entry['status']}",
        )
    event = DB["rodeo_events"][entry["rodeo_event_id"]]
    rodeo = rodeo_of_event(event)

    if action == "CANCEL_ENTRY":
        refund_contribution_and_retention(entry)
        entry["status"] = "CANCELLED"
    elif action == "TURN_OUT":
        if rodeo["posture"] not in ("DRAW_LOCKED", "IN_PROGRESS"):
            raise ApiError(
                "ERR_RODEO_NOT_OPEN",
                409,
                "Turn-out requires the rodeo to be DRAW_LOCKED or IN_PROGRESS",
            )
        if reason == "MEDICAL":
            if vet_report is None or vet_report["disposition"] != "INJURED_TURNOUT":
                raise ApiError(
                    "ERR_MEDICAL_RELEASE_REQUIRED",
                    409,
                    "MEDICAL turn-out requires a vet report with disposition "
                    "INJURED_TURNOUT",
                )
            refund_contribution_only(entry)
            entry["vet_report_id"] = vet_report["id"]
        else:
            entry["vet_report_id"] = None
        entry["turn_out_reason"] = reason
        release_entry_assignments(entry)
        entry["status"] = "TURNED_OUT"
    elif action == "DRAW_OUT":
        release_entry_assignments(entry)
        refund_full(entry)
        entry["status"] = "DRAWN_OUT"
    else:  # RE_ENTER
        if rodeo["posture"] != "ENTRIES_OPEN":
            raise ApiError(
                "ERR_RODEO_NOT_OPEN",
                409,
                "Re-entry requires the rodeo to be ENTRIES_OPEN",
            )
        if not clock_before(rodeo["_close_dt"]):
            raise ApiError(
                "ERR_ENTRY_WINDOW_CLOSED",
                409,
                "The logical clock is at or after entries_close_at",
            )
        contestant = DB["contestants"][entry["contestant_id"]]
        if contestant["status"] != "GOOD_STANDING":
            raise ApiError(
                "ERR_CONTESTANT_SUSPENDED", 409, "Contestant is not in GOOD_STANDING"
            )
        charge_entry(entry, event["entry_fee_cents"])
        entry["turn_out_reason"] = None
        entry["vet_report_id"] = None
        entry["status"] = "ENTERED"
    touch(entry)
    return ok(ser(entry))
