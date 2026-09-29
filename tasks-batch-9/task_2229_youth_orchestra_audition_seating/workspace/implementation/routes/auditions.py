"""The audition calendar, audition lifecycle and blind rubric sheets."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, endpoint, require_guardian_owns, require_panelist_owns
from envelope import ok, ok_list
from errors import ApiError
from store import clock_now, db
from validate import Body, bad, pagination

bp = Blueprint("auditions", __name__)

BUFFER = timedelta(minutes=calc.ROOM_TURNOVER_BUFFER_MINUTES)


def _buffered_overlap(a_start, a_end, b_start, b_end):
    return a_start < (b_end + BUFFER) and b_start < (a_end + BUFFER)


# --------------------------------------------------------------- audition slots
@bp.route("/audition-slots", methods=["POST"])
@endpoint("RegistrarStaff")
def create_slot():
    body = Body()
    season_id = body.string("season_id", required=True)
    room_code = body.string("room_code", required=True, min_len=1, max_len=16)
    start_at = body.datetime("start_at", required=True)
    end_at = body.datetime("end_at", required=True)
    panelist_ids = body.str_array("panelist_ids", required=True, min_items=2,
                                  max_items=5, distinct=True)
    instrument_focus = body.enum("instrument_focus", calc.INSTRUMENTS, required=True)
    excerpts = body.str_array("required_excerpt_codes", required=False, default=None)
    quorum = body.integer("quorum_required", required=False, default=3,
                          minimum=2, maximum=5)
    capacity = body.integer("capacity", required=False, default=1,
                            minimum=1, maximum=8)
    if end_at <= start_at:
        bad("end_at must be strictly later than start_at.")
    if quorum > len(panelist_ids):
        bad("quorum_required may not exceed the number of panelists.")

    season = svc.season_or_404(season_id)
    panelists = [svc.panelist_or_404(pid) for pid in panelist_ids]

    if season["status"] != "AUDITIONS_OPEN":
        raise ApiError("ERR_SEASON_NOT_ACCEPTING_AUDITIONS",
                       "The season is not accepting auditions.")
    if start_at < season["audition_window_start"] or end_at > season["audition_window_end"]:
        raise ApiError("ERR_SLOT_OUTSIDE_AUDITION_WINDOW",
                       "The slot escapes the season's audition window.")

    for other in svc.ordered(list(db.audition_slots.values())):
        if other["room_code"] != room_code:
            continue
        if _buffered_overlap(start_at, end_at, other["start_at"], other["end_at"]):
            raise ApiError("ERR_ROOM_DOUBLE_BOOKED",
                           "Room %s is already booked around that time." % room_code)

    for panelist in panelists:
        if not panelist["available_for_panels"]:
            raise ApiError("ERR_PANELIST_UNAVAILABLE",
                           "Panelist %s is not available for panels." % panelist["id"])
    for other in svc.ordered(list(db.audition_slots.values())):
        if not _buffered_overlap(start_at, end_at, other["start_at"], other["end_at"]):
            continue
        for panelist in panelists:
            if panelist["id"] in other["panelist_ids"]:
                raise ApiError("ERR_PANELIST_UNAVAILABLE",
                               "Panelist %s is already seated on an overlapping slot."
                               % panelist["id"])

    row = svc.new_row()
    row.update({
        "season_id": season["id"],
        "room_code": room_code,
        "start_at": start_at,
        "end_at": end_at,
        "panelist_ids": list(panelist_ids),
        "instrument_focus": instrument_focus,
        "required_excerpt_codes": list(excerpts) if excerpts else [],
        "quorum_required": quorum,
        "capacity": capacity,
    })
    db.audition_slots[row["id"]] = row
    return ok(svc.slot_json(row), 201)


@bp.route("/audition-slots", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_slots():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.audition_slots.values())),
                             request.args,
                             ["season_id", "room_code", "instrument_focus"])
    if "status" in request.args:
        wanted = (request.args.get("status") or "").strip()
        rows = [r for r in rows if svc.slot_status(r) == wanted]
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.slot_json(r) for r in page], limit, offset, len(rows))


@bp.route("/audition-slots/<slot_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_slot(slot_id):
    return ok(svc.slot_json(svc.slot_or_404(slot_id)))


# -------------------------------------------------------------------- auditions
@bp.route("/auditions", methods=["POST"])
@endpoint("Guardian", "RegistrarStaff")
def create_audition():
    body = Body()
    claimed = body.raw("member_id")
    if isinstance(claimed, str):
        require_guardian_owns(claimed)

    member_id = body.string("member_id", required=True)
    season_id = body.string("season_id", required=True)
    declared_program = body.string("declared_program", required=True,
                                   min_len=1, max_len=200)
    excerpt_ids = body.str_array("excerpt_ids", required=True, min_items=1,
                                 max_items=6, distinct=True)
    scale_attested = body.boolean("scale_attested", default=False)

    member = svc.member_or_404(member_id)
    season = svc.season_or_404(season_id)

    if season["status"] not in ("PLANNING", "AUDITIONS_OPEN"):
        raise ApiError("ERR_SEASON_NOT_ACCEPTING_AUDITIONS",
                       "The season is not accepting audition registrations.")

    for other in db.auditions.values():
        if (other["member_id"] == member["id"] and other["season_id"] == season["id"]
                and other["status"] != "ADJUDICATED"):
            raise ApiError("ERR_DUPLICATE_AUDITION",
                           "This musician already has an open audition this season.")

    row = svc.new_row()
    row.update({
        "member_id": member["id"],
        "season_id": season["id"],
        "slot_id": None,
        "declared_program": declared_program,
        "excerpt_ids": list(excerpt_ids),
        "scale_attested": scale_attested,
        "blind_code": svc.mint_blind_code(member["primary_instrument"]),
        "status": "REQUESTED",
        "revision_round": 0,
        "composite_provisional_score": None,
        "composite_final_score": None,
        "tier_recommendation": None,
    })
    db.auditions[row["id"]] = row
    return ok(svc.audition_json(row), 201)


@bp.route("/auditions", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_auditions():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.auditions.values())), request.args,
                             ["member_id", "season_id", "slot_id", "status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.audition_json(r) for r in page], limit, offset, len(rows))


@bp.route("/auditions/<audition_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_audition(audition_id):
    return ok(svc.audition_json(svc.audition_or_404(audition_id)))


@bp.route("/auditions/<audition_id>/schedule", methods=["POST"])
@endpoint("RegistrarStaff")
def schedule_audition(audition_id):
    audition = svc.audition_or_404(audition_id)
    body = Body()
    slot_id = body.string("slot_id", required=True)
    slot = svc.slot_or_404(slot_id)

    if audition["status"] not in ("REQUESTED", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "An audition in %s cannot be booked." % audition["status"])
    if (audition["status"] == "REVISION_REQUESTED"
            and audition["revision_round"] > calc.MAX_REVISION_ROUNDS):
        raise ApiError("ERR_MAX_REVISION_ROUNDS_REACHED",
                       "This audition has exhausted its revision rounds.")

    season = db.seasons[audition["season_id"]]
    if season["status"] != "AUDITIONS_OPEN":
        raise ApiError("ERR_SEASON_NOT_ACCEPTING_AUDITIONS",
                       "The season is not accepting auditions.")

    member = db.members[audition["member_id"]]
    if member["standing_status"] != "CLEAR":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "The musician's standing blocks a booking.")

    if (slot["season_id"] != audition["season_id"]
            or slot["instrument_focus"] != member["primary_instrument"]):
        raise ApiError("ERR_SLOT_INSTRUMENT_MISMATCH",
                       "The slot does not match this audition.")

    required = slot["required_excerpt_codes"]
    if required:
        prepared = set(audition["excerpt_ids"])
        if not set(required).issubset(prepared) or not audition["scale_attested"]:
            raise ApiError("ERR_REPERTOIRE_REQUIREMENTS_UNMET",
                           "The declared repertoire does not meet the slot's needs.")

    if (slot["start_at"] < season["audition_window_start"]
            or slot["end_at"] > season["audition_window_end"]):
        raise ApiError("ERR_SLOT_OUTSIDE_AUDITION_WINDOW",
                       "The slot escapes the season's audition window.")
    if not slot["start_at"] > clock_now():
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "That slot has already begun.")
    if svc.slot_status(slot) != "OPEN":
        raise ApiError("ERR_AUDITION_SLOT_FULL", "That slot is full.")

    previous = db.audition_slots.get(audition["slot_id"]) if audition["slot_id"] else None
    audition["slot_id"] = slot["id"]
    audition["status"] = "SCHEDULED"
    svc.touch(audition)
    svc.touch(slot)
    if previous is not None and previous["id"] != slot["id"]:
        svc.touch(previous)
    return ok(svc.audition_json(audition))


@bp.route("/auditions/<audition_id>/panel-scores", methods=["POST"])
@endpoint("Panelist")
def create_panel_score(audition_id):
    body = Body()
    claimed = body.raw("panelist_id")
    if isinstance(claimed, str):
        require_panelist_owns(claimed)

    audition = svc.audition_or_404(audition_id)
    panelist_id = body.string("panelist_id", required=True)
    tone = body.integer("tone_score", required=True, minimum=0, maximum=25)
    rhythm = body.integer("rhythm_score", required=True, minimum=0, maximum=25)
    intonation = body.integer("intonation_score", required=True, minimum=0, maximum=25)
    sight_reading = body.integer("sight_reading_score", required=True,
                                 minimum=0, maximum=25)
    panelist = svc.panelist_or_404(panelist_id)

    if audition["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only a SCHEDULED audition may be scored.")

    if audition["member_id"] in panelist["conflict_member_ids"]:
        raise ApiError("ERR_PANEL_CONFLICT_OF_INTEREST",
                       "The adjudicator privately teaches this musician.")

    slot = db.audition_slots.get(audition["slot_id"])
    if (slot is None or panelist["id"] not in slot["panelist_ids"]
            or panelist["instrument_expertise"] != slot["instrument_focus"]):
        raise ApiError("ERR_PANELIST_NOT_ON_PANEL",
                       "The adjudicator is not on this slot's panel.")

    for sheet in db.panel_scores.values():
        if (sheet["audition_id"] == audition["id"]
                and sheet["panelist_id"] == panelist["id"]
                and sheet["revision_round"] == audition["revision_round"]):
            raise ApiError("ERR_DUPLICATE_PANEL_SCORE",
                           "This adjudicator already scored the current round.")

    row = svc.new_row(with_version=False)
    row.update({
        "audition_id": audition["id"],
        "panelist_id": panelist["id"],
        "revision_round": audition["revision_round"],
        "tone_score": tone,
        "rhythm_score": rhythm,
        "intonation_score": intonation,
        "sight_reading_score": sight_reading,
        "weighted_total": calc.weighted_total(tone, rhythm, intonation, sight_reading),
        "blind": True,
    })
    db.panel_scores[row["id"]] = row

    sheets = svc.scores_of_round(audition)
    svc.touch(audition)
    if len(sheets) >= slot["quorum_required"]:
        audition["status"] = "SCORED"
        audition["composite_provisional_score"] = calc.provisional_composite(sheets)
    return ok(svc.score_json(row), 201)


@bp.route("/auditions/<audition_id>/adjudicate", methods=["POST"])
@endpoint("ArtisticDirector")
def adjudicate(audition_id):
    audition = svc.audition_or_404(audition_id)
    if audition["status"] != "SCORED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only a SCORED audition may be adjudicated.")
    season = db.seasons[audition["season_id"]]
    if season["status"] not in ("AUDITIONS_OPEN", "PLACEMENT"):
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "The season phase does not admit adjudication.")
    slot = db.audition_slots.get(audition["slot_id"])
    sheets = svc.scores_of_round(audition)
    if slot is not None and len(sheets) < slot["quorum_required"]:
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "The panel no longer meets quorum.")

    final = calc.final_composite(sheets)
    audition["composite_final_score"] = final
    audition["tier_recommendation"] = calc.tier_recommendation(final)
    audition["status"] = "ADJUDICATED"
    svc.touch(audition)
    return ok(svc.audition_json(audition))


@bp.route("/auditions/<audition_id>/request-revision", methods=["POST"])
@endpoint("ArtisticDirector")
def request_revision(audition_id):
    audition = svc.audition_or_404(audition_id)
    if audition["status"] != "SCORED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only a SCORED audition may be sent back.")
    if audition["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_MAX_REVISION_ROUNDS_REACHED",
                       "This audition has exhausted its revision rounds.")
    season = db.seasons[audition["season_id"]]
    if season["status"] != "AUDITIONS_OPEN":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "A revision may only be requested while auditions are open.")

    previous = db.audition_slots.get(audition["slot_id"]) if audition["slot_id"] else None
    audition["revision_round"] += 1
    audition["composite_provisional_score"] = None
    audition["slot_id"] = None
    audition["status"] = "REVISION_REQUESTED"
    svc.touch(audition)
    if previous is not None:
        svc.touch(previous)
    return ok(svc.audition_json(audition))


# ----------------------------------------------------------------- panel scores
@bp.route("/panel-scores", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_panel_scores():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.panel_scores.values())),
                             request.args,
                             ["audition_id", "panelist_id", "revision_round"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.score_json(r) for r in page], limit, offset, len(rows))


@bp.route("/panel-scores/<score_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_panel_score(score_id):
    return ok(svc.score_json(svc.score_or_404(score_id)))
