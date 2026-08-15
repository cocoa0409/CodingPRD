"""Performance endpoints: schedule, list, mark PLAYED/CANCELLED with bubble-up."""

from flask import Blueprint, request

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_STOP_NOT_SCHEDULABLE,
                    ERR_PERFORMANCE_INVALID_STATE, ERR_WEEKLY_SHOW_CAP,
                    ERR_DAILY_SHOW_CAP, ERR_PERFORMANCE_OUTSIDE_WEEK,
                    ERR_CURTAIN_GAP_CONFLICT)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain, calc
from util import (get_body, reject_unknown, require_present, as_int, as_enum,
                  parse_iso_date, parse_curtain, paginate)

bp = Blueprint("performances", __name__)

WEEKLY_CAP = 8   # 8th allowed, 9th rejected
DAILY_CAP = 2    # 3rd same-day rejected
TURNAROUND_MIN = 120


def _get_stop_or_404(stop_id):
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    return stop


@bp.route("/stops/<stop_id>/performances", methods=["POST"])
def create_performance(stop_id):
    _, role = authenticate()
    require_roles(role, ("TourManager",))
    stop = _get_stop_or_404(stop_id)
    body = get_body()
    reject_unknown(body, {"perf_date", "curtain_time", "duration_minutes"})
    perf_date_raw = require_present(body, "perf_date")
    perf_date = parse_iso_date(perf_date_raw, "perf_date")
    curtain_raw = require_present(body, "curtain_time")
    curtain_min = parse_curtain(curtain_raw, "curtain_time")
    duration = as_int(require_present(body, "duration_minutes"),
                      "duration_minutes", minv=1)
    # State (priority 5): scheduling requires READY | PLAYING.
    if stop["booking_status"] not in ("READY", "PLAYING"):
        raise err(ERR_STOP_NOT_SCHEDULABLE, 409,
                  "Performances may be scheduled only while the stop is READY or PLAYING")
    pws = parse_iso_date(stop["play_week_start"], "play_week_start")
    pwe = parse_iso_date(stop["play_week_end"], "play_week_end")
    siblings = domain.perfs_of_stop(stop_id)
    live = [p for p in siblings if p["status"] in ("SCHEDULED", "PLAYED")]
    # Business safety (priority 6): weekly cap, then daily cap.
    in_week = [p for p in live
               if pws <= parse_iso_date(p["perf_date"], "perf_date") <= pwe]
    if len(in_week) >= WEEKLY_CAP:
        raise err(ERR_WEEKLY_SHOW_CAP, 422,
                  "The play week already carries %d scheduled/played performances" % WEEKLY_CAP)
    same_day = [p for p in live if p["perf_date"] == perf_date_raw]
    if len(same_day) >= DAILY_CAP:
        raise err(ERR_DAILY_SHOW_CAP, 422,
                  "At most %d performances per date" % DAILY_CAP)
    # Temporal (priority 8): within the play week, then the curtain gap.
    if not (pws <= perf_date <= pwe):
        raise err(ERR_PERFORMANCE_OUTSIDE_WEEK, 422,
                  "perf_date must lie within [play_week_start, play_week_end]")
    for p in same_day:
        p_start = parse_curtain(p["curtain_time"], "curtain_time")
        if curtain_min >= p_start:
            # new is the later show
            if curtain_min < p_start + p["duration_minutes"] + TURNAROUND_MIN:
                raise err(ERR_CURTAIN_GAP_CONFLICT, 422,
                          "Same-day curtain gap is under duration + 120 minutes")
        else:
            if p_start < curtain_min + duration + TURNAROUND_MIN:
                raise err(ERR_CURTAIN_GAP_CONFLICT, 422,
                          "Same-day curtain gap is under duration + 120 minutes")

    rec = db.new_record()
    rec.update({
        "stop_id": stop_id,
        "perf_date": perf_date_raw,
        "curtain_time": curtain_raw,
        "duration_minutes": duration,
        "gross_cents": None,
        "status": "SCHEDULED",
    })
    db.performances[rec["id"]] = rec
    return success(db.serialize("performance", rec), 201)


@bp.route("/stops/<stop_id>/performances", methods=["GET"])
def list_performances(stop_id):
    authenticate()
    _get_stop_or_404(stop_id)
    items = domain.perfs_of_stop(stop_id)
    perf_date = request.args.get("perf_date")
    if perf_date is not None:
        items = [p for p in items if p["perf_date"] == perf_date]
    items.sort(key=lambda p: p["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("performance", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/performances/<perf_id>", methods=["PUT"])
def put_performance(perf_id):
    user_id, role = authenticate()
    body = get_body()
    # Role-for-transition (priority 2): PLAYED is Treasurer, CANCELLED TourManager.
    target = body.get("status")
    if target == "PLAYED":
        require_roles(role, ("Treasurer",))
    elif target == "CANCELLED":
        require_roles(role, ("TourManager",))
    else:
        require_roles(role, ("Treasurer", "TourManager"))
    perf = db.performances.get(perf_id)
    if perf is None:
        raise err(ERR_NOT_FOUND, 404, "Performance not found")
    reject_unknown(body, {"status", "gross_cents"})
    target = as_enum(require_present(body, "status"), "status",
                     ("SCHEDULED", "PLAYED", "CANCELLED"))
    gross = None
    if target == "PLAYED":
        gross = as_int(require_present(body, "gross_cents"), "gross_cents", minv=0)
    elif target == "SCHEDULED":
        raise err(ERR_PERFORMANCE_INVALID_STATE, 409,
                  "No performance transition back to SCHEDULED")
    stop = db.stops[perf["stop_id"]]
    # Marking is gated on the stop still being READY | PLAYING.
    if stop["booking_status"] not in ("READY", "PLAYING"):
        raise err(ERR_STOP_NOT_SCHEDULABLE, 409,
                  "The stop is not READY or PLAYING")
    if perf["status"] != "SCHEDULED":
        raise err(ERR_PERFORMANCE_INVALID_STATE, 409,
                  "PLAYED/CANCELLED are only legal from SCHEDULED")

    if target == "PLAYED":
        perf["gross_cents"] = gross
        perf["status"] = "PLAYED"
        touch(perf)
        stop_touched = False
        # First played flips READY -> PLAYING (bubble-up).
        if stop["booking_status"] == "READY":
            stop["booking_status"] = "PLAYING"
            stop_touched = True
        # Understudy bump: every ACTIVATED coverage on tracks of this tour pays
        # one accrued show to the covering member (calc_understudy_bump_pay).
        for track in domain.tracks_of_tour(stop["tour_id"]):
            for cov in domain.coverages_of_track(track["id"]):
                if cov["status"] != "ACTIVATED":
                    continue
                member = db.cast_members.get(cov["cast_member_id"])
                principal = db.cast_members.get(track.get("principal_member_id") or "")
                if member is None or principal is None:
                    continue
                member["bump_shows_accrued"] += 1
                member["bump_pay_cents"] = (member["bump_shows_accrued"]
                                            * calc.bump_unit_cents(
                                                principal["weekly_salary_cents"]))
                touch(member)
        if stop_touched:
            touch(stop)
        # All resolved -> CLOSED + settlement DRAFT auto-created (bubble-up).
        domain.auto_close_stop_if_resolved(stop)
    else:  # CANCELLED
        perf["status"] = "CANCELLED"
        touch(perf)
        domain.auto_close_stop_if_resolved(stop)
    return success(db.serialize("performance", perf), 200)
