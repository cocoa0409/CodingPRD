"""Rounds, pace observations, scoring, peer verification and rules cases."""
from datetime import timedelta

from flask import Blueprint

import calc
import listing
import services
import validate
from auth import guard
from envelope import object_response
from errors import ApiError
from store import (
    db, bump, clock, clock_iso, dt_of, find, insert, new_row, public,
)

bp = Blueprint("rounds", __name__)

CASE_ROUND_STATUSES = ("SUBMITTED", "DISPUTED", "PEER_VERIFIED", "CERTIFIED")


def _round_tournament(rnd):
    return db.tournaments.get(rnd["tournament_id"])


def _round_entry(rnd):
    return db.entries.get(rnd["entry_id"])


def _require_round_ownership(caller, rnd):
    if not caller.is_member:
        return
    entry = _round_entry(rnd)
    if entry is None or entry["member_id"] != caller.user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")


def _reopen_window_ok(rnd):
    """A CERTIFIED round may be reopened only within 48 hours of certification."""
    if rnd["status"] != "CERTIFIED":
        return True
    certified = dt_of(rnd["certified_at"])
    if certified is None:
        return True
    return clock() <= certified + timedelta(hours=calc.RULES_REOPEN_WINDOW_HOURS)


@bp.route("/rounds", methods=["POST"])
def create_round():
    guard(("TourAdmin", "ChiefReferee"))
    body = validate.body()
    entry_id = validate.req_id(body, "entry_id")
    round_number = validate.req_int(body, "round_number", minimum=1)
    tee_time = validate.req_dt(body, "tee_time")
    marker_member_id = validate.req_id(body, "marker_member_id")

    entry = find("entries", entry_id, "ERR_ENTRY_NOT_FOUND")
    marker = find("members", marker_member_id, "ERR_MEMBER_NOT_FOUND")
    tournament = db.tournaments.get(entry["tournament_id"])
    if tournament is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND")
    if round_number > tournament["round_count"]:
        validate.bad(
            "Field 'round_number' must not exceed the tournament's round_count"
        )

    if tournament["status"] not in ("FIELD_SET", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if entry["entry_status"] not in ("ACCEPTED", "COMPETING"):
        raise ApiError("ERR_INVALID_ENTRY_STATE")

    # the peer marker: not the entrant, and in the same field
    if marker["id"] == entry["member_id"]:
        raise ApiError("ERR_INVALID_MARKER")
    marker_in_field = False
    for other in services.entries_of_tournament(tournament["id"]):
        if other["member_id"] == marker["id"] and other["entry_status"] in (
            "ACCEPTED",
            "COMPETING",
        ):
            marker_in_field = True
            break
    if not marker_in_field:
        raise ApiError("ERR_INVALID_MARKER")

    # half-open tee slot capacity: [tee_time, tee_time + tee_interval_minutes)
    slot_start = dt_of(tee_time)
    slot_end = slot_start + timedelta(minutes=tournament["tee_interval_minutes"])
    occupants = 0
    for other in services.rounds_of_tournament(tournament["id"]):
        other_time = dt_of(other["tee_time"])
        if other_time is None:
            continue
        if slot_start <= other_time < slot_end:
            occupants += 1
    if occupants >= tournament["tee_group_size"]:
        raise ApiError("ERR_TEE_SLOT_FULL")

    row = new_row()
    row.update(
        {
            "entry_id": entry["id"],
            "tournament_id": tournament["id"],
            "marker_member_id": marker["id"],
            "round_number": round_number,
            "tee_time": tee_time,
            "gross_strokes": None,
            "pace_warning_count": 0,
            "max_minutes_behind": 0,
            "pace_penalty_strokes": 0,
            "rules_penalty_strokes": 0,
            "adjusted_gross": None,
            "scoring_differential": None,
            "dispute_count": 0,
            "open_rules_case_count": 0,
            "status": "SCHEDULED",
            "certified_at": None,
            "certified_by_user_id": None,
        }
    )
    insert("rounds", row)
    return object_response(public(row), 201)


@bp.route("/rounds", methods=["GET"])
def list_rounds():
    guard(("TourAdmin", "RulesOfficial", "ChiefReferee"))
    return listing.listing(
        "rounds", ("entry_id", "tournament_id", "marker_member_id", "round_number", "status")
    )


@bp.route("/rounds/<round_id>", methods=["GET"])
def get_round(round_id):
    caller = guard(("TourAdmin", "RulesOfficial", "ChiefReferee", "Member"))
    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    _require_round_ownership(caller, rnd)
    return object_response(public(rnd))


@bp.route("/rounds/<round_id>/pace-observations", methods=["POST"])
def pace_observation(round_id):
    guard(("RulesOfficial", "ChiefReferee"))
    body = validate.body()
    observation_type = validate.req_str(body, "observation_type", 1, 40)
    minutes_behind = validate.req_int(body, "minutes_behind", minimum=0)
    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    if rnd["status"] not in ("SCHEDULED", "SUBMITTED"):
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if observation_type == "WARNING":
        rnd["pace_warning_count"] += 1
    if minutes_behind > rnd["max_minutes_behind"]:
        rnd["max_minutes_behind"] = minutes_behind
    rnd["pace_penalty_strokes"] = calc.pace_penalty(
        rnd["pace_warning_count"], rnd["max_minutes_behind"]
    )
    if rnd["gross_strokes"] is not None:
        services.refresh_round_numbers(rnd, _round_tournament(rnd))
    bump(rnd)
    return object_response(public(rnd))


@bp.route("/rounds/<round_id>/submit-score", methods=["POST"])
def submit_score(round_id):
    caller = guard(("Member", "RulesOfficial", "ChiefReferee"))
    body = validate.body()
    gross_strokes = validate.req_int(body, "gross_strokes", minimum=50, maximum=130)
    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    _require_round_ownership(caller, rnd)
    tournament = _round_tournament(rnd)
    entry = _round_entry(rnd)
    if tournament is None or tournament["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if entry is None or entry["entry_status"] not in ("ACCEPTED", "COMPETING"):
        raise ApiError("ERR_INVALID_ENTRY_STATE")
    if rnd["status"] not in ("SCHEDULED", "DISPUTED"):
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if entry["fee_status"] not in ("PAID", "AID_COVERED"):
        raise ApiError("ERR_ENTRY_FEE_OUTSTANDING")
    if rnd["status"] == "DISPUTED" and rnd["dispute_count"] >= calc.ROUND_DISPUTE_LIMIT:
        raise ApiError("ERR_INVALID_ROUND_STATE")

    rnd["gross_strokes"] = gross_strokes
    rnd["status"] = "SUBMITTED"
    services.refresh_adjusted_gross(rnd)
    bump(rnd)
    if entry["entry_status"] == "ACCEPTED":
        entry["entry_status"] = "COMPETING"
        bump(entry)
    return object_response(public(rnd))


@bp.route("/rounds/<round_id>/peer-verify", methods=["POST"])
def peer_verify(round_id):
    caller = guard(("Member", "RulesOfficial", "ChiefReferee"))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("VERIFY", "DISPUTE"))
    note = validate.opt_str(body, "note", 1, 2000)
    if decision == "DISPUTE" and note is None:
        validate.bad("Field 'note' is required when disputing a card")
    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    if rnd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if caller.user_id != rnd["marker_member_id"]:
        raise ApiError("ERR_INVALID_MARKER")

    if decision == "VERIFY":
        rnd["status"] = "PEER_VERIFIED"
    else:
        if rnd["dispute_count"] >= calc.ROUND_DISPUTE_LIMIT - 1:
            rnd["dispute_count"] = calc.ROUND_DISPUTE_LIMIT
            rnd["status"] = "NO_CARD"
            rnd["adjusted_gross"] = None
            rnd["scoring_differential"] = None
        else:
            rnd["dispute_count"] += 1
            rnd["status"] = "DISPUTED"
    bump(rnd)
    return object_response(public(rnd))


@bp.route("/rounds/<round_id>/certify", methods=["POST"])
def certify_round(round_id):
    caller = guard(("RulesOfficial", "ChiefReferee"))
    validate.body()
    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    if caller.user_id == rnd["marker_member_id"]:
        raise ApiError("ERR_SELF_ADJUDICATION")
    tournament = _round_tournament(rnd)
    if tournament is None or tournament["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")
    if rnd["status"] != "PEER_VERIFIED":
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if rnd["open_rules_case_count"] != 0:
        raise ApiError("ERR_OPEN_RULES_CASE")

    services.refresh_round_numbers(rnd, tournament)
    rnd["status"] = "CERTIFIED"
    rnd["certified_at"] = clock_iso()
    rnd["certified_by_user_id"] = caller.user_id
    bump(rnd)

    entry = _round_entry(rnd)
    if entry is not None:
        services.recompute_entry_rollup(entry)
        bump(entry)
        if entry["certified_round_count"] >= tournament["round_count"] and entry[
            "entry_status"
        ] == "COMPETING":
            entry["entry_status"] = "FINISHED"
            bump(entry)
            services.recompute_census(tournament)
            bump(tournament)
            services.maybe_complete_tournament(tournament)
    return object_response(public(rnd))


# ---------------------------------------------------------------------------
# rules cases
# ---------------------------------------------------------------------------
@bp.route("/rules-cases", methods=["POST"])
def create_rules_case():
    caller = guard(("RulesOfficial", "ChiefReferee", "Member"))
    body = validate.body()
    round_id = validate.req_id(body, "round_id")
    rule_reference = validate.req_str(body, "rule_reference", 1, 40)
    proposed_disposition = validate.req_enum(
        body, "proposed_disposition", ("PENALTY_STROKES", "DISQUALIFICATION")
    )
    if proposed_disposition == "PENALTY_STROKES":
        penalty_strokes_proposed = validate.req_int(
            body, "penalty_strokes_proposed", minimum=0, maximum=8
        )
    else:
        penalty_strokes_proposed = validate.opt_int(
            body, "penalty_strokes_proposed", minimum=0, maximum=8, default=0
        )
        if penalty_strokes_proposed != 0:
            validate.bad(
                "Field 'penalty_strokes_proposed' must be omitted or zero for a "
                "DISQUALIFICATION proposal"
            )

    rnd = find("rounds", round_id, "ERR_ROUND_NOT_FOUND")
    if rnd["status"] not in CASE_ROUND_STATUSES:
        raise ApiError("ERR_INVALID_ROUND_STATE")
    if not _reopen_window_ok(rnd):
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED")

    row = new_row()
    row.update(
        {
            "round_id": rnd["id"],
            "rule_reference": rule_reference,
            "proposed_disposition": proposed_disposition,
            "penalty_strokes_proposed": penalty_strokes_proposed,
            "reported_by_user_id": caller.user_id,
            "adjudicated_by_user_id": None,
            "status": "REPORTED",
            "decision": None,
            "disposition": None,
            "penalty_strokes_applied": None,
            "appeal_count": 0,
            "decided_at": None,
        }
    )
    insert("rules_cases", row)
    rnd["open_rules_case_count"] += 1
    bump(rnd)
    return object_response(public(row), 201)


@bp.route("/rules-cases", methods=["GET"])
def list_rules_cases():
    guard(("TourAdmin", "RulesOfficial", "ChiefReferee"))
    return listing.listing(
        "rules_cases",
        ("round_id", "status", "decision", "disposition", "proposed_disposition",
         "reported_by_user_id"),
    )


@bp.route("/rules-cases/<case_id>", methods=["GET"])
def get_rules_case(case_id):
    guard(("TourAdmin", "RulesOfficial", "ChiefReferee"))
    case = find("rules_cases", case_id, "ERR_CASE_NOT_FOUND")
    return object_response(public(case))


def _reverse_penalty(case, rnd):
    """Compensate a granted appeal: hand the strokes back."""
    applied = case["penalty_strokes_applied"] or 0
    if applied > 0:
        rnd["rules_penalty_strokes"] = max(0, rnd["rules_penalty_strokes"] - applied)
    case["penalty_strokes_applied"] = 0
    return applied


@bp.route("/rules-cases/<case_id>/adjudicate", methods=["POST"])
def adjudicate_rules_case(case_id):
    caller = guard(("ChiefReferee",))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("UPHELD", "DISMISSED"))
    disposition = validate.req_enum(
        body, "disposition", ("PENALTY_STROKES", "DISQUALIFICATION")
    )
    strokes = validate.opt_int(body, "penalty_strokes_applied", minimum=0, maximum=8)

    case = find("rules_cases", case_id, "ERR_CASE_NOT_FOUND")
    if caller.user_id == case["reported_by_user_id"]:
        raise ApiError("ERR_SELF_ADJUDICATION")
    if case["status"] not in ("REPORTED", "APPEAL_OPEN"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    rnd = db.rounds.get(case["round_id"])
    if rnd is None:
        raise ApiError("ERR_ROUND_NOT_FOUND")
    if not _reopen_window_ok(rnd):
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED")

    from_appeal = case["status"] == "APPEAL_OPEN"
    tournament = _round_tournament(rnd)
    entry = _round_entry(rnd)

    if decision == "UPHELD" and from_appeal:
        # denying an appeal: the recorded disposition must be restated verbatim
        if disposition != case["disposition"]:
            validate.bad(
                "Field 'disposition' must match the disposition already recorded"
            )
        case["status"] = "UPHELD"
        case["decision"] = "UPHELD"
        case["adjudicated_by_user_id"] = caller.user_id
        case["decided_at"] = clock_iso()
        bump(case)
        rnd["open_rules_case_count"] = max(0, rnd["open_rules_case_count"] - 1)
        bump(rnd)
        return object_response(public(case))

    if decision == "UPHELD":
        if disposition == "PENALTY_STROKES" and (strokes is None or strokes < 1):
            validate.bad(
                "Field 'penalty_strokes_applied' must be between 1 and 8 for a "
                "PENALTY_STROKES disposition"
            )
        case["status"] = "UPHELD"
        case["decision"] = "UPHELD"
        case["disposition"] = disposition
        case["adjudicated_by_user_id"] = caller.user_id
        case["decided_at"] = clock_iso()
        rnd["open_rules_case_count"] = max(0, rnd["open_rules_case_count"] - 1)
        if disposition == "PENALTY_STROKES":
            case["penalty_strokes_applied"] = strokes
            rnd["rules_penalty_strokes"] += strokes
            if rnd["gross_strokes"] is not None:
                services.refresh_round_numbers(rnd, tournament)
            bump(case)
            bump(rnd)
            if entry is not None:
                services.recompute_entry_rollup(entry)
                bump(entry)
        else:
            rnd["status"] = "DISQUALIFIED"
            bump(case)
            bump(rnd)
            if entry is not None and tournament is not None:
                services.disqualify_entry_for_round(entry, tournament)
        return object_response(public(case))

    # DISMISSED — from REPORTED it simply closes; from APPEAL_OPEN it compensates
    case["status"] = "DISMISSED"
    case["decision"] = "DISMISSED"
    case["adjudicated_by_user_id"] = caller.user_id
    case["decided_at"] = clock_iso()
    reversed_strokes = _reverse_penalty(case, rnd)
    rnd["open_rules_case_count"] = max(0, rnd["open_rules_case_count"] - 1)
    if reversed_strokes > 0 and rnd["gross_strokes"] is not None and rnd[
        "status"
    ] != "DISQUALIFIED":
        services.refresh_round_numbers(rnd, tournament)
    bump(case)
    bump(rnd)
    if reversed_strokes > 0 and entry is not None:
        services.recompute_entry_rollup(entry)
        bump(entry)
    return object_response(public(case))


@bp.route("/rules-cases/<case_id>/appeal", methods=["POST"])
def appeal_rules_case(case_id):
    caller = guard(("Member", "RulesOfficial"))
    body = validate.body()
    validate.req_str(body, "grounds", 1, 2000)
    case = find("rules_cases", case_id, "ERR_CASE_NOT_FOUND")
    rnd = db.rounds.get(case["round_id"])
    if rnd is None:
        raise ApiError("ERR_ROUND_NOT_FOUND")
    if caller.is_member:
        entry = _round_entry(rnd)
        if entry is None or entry["member_id"] != caller.user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE")
    if case["status"] not in ("UPHELD", "DISMISSED"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    decided = dt_of(case["decided_at"])
    if decided is None or clock() > decided + timedelta(
        hours=calc.RULES_APPEAL_WINDOW_HOURS
    ):
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")
    case["status"] = "APPEAL_OPEN"
    case["appeal_count"] += 1
    bump(case)
    rnd["open_rules_case_count"] += 1
    bump(rnd)
    return object_response(public(case))
