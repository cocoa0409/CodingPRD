"""Routes: rehearsals, attendance records, music scores, score checkouts."""

import store
from domain import (
    ATTENDANCE_STATUSES, gate_season, sync_member, sync_score,
)
from errors import ApiError
from routes_common import (
    apply_filters, many, member_ownership_check, one, route,
    scope_member_filter,
)
from serializers import (
    attendance_record_view, checkout_view, rehearsal_view, score_view,
)
from store import all_of, new_row, touch
from timeutil import clock, parse_instant
from validate import check_body, check_enum, get_or_404, resolve_ids

ALL_ROLES = ("President", "Treasurer", "ChoirDirector", "Librarian", "Member")
ATTENDANCE_READ_ROLES = ("President", "Treasurer", "ChoirDirector", "Member")
REHEARSAL_WRITE_POSTURES = ("REHEARSING", "CONCERT_LOCK")
CHECKOUT_WRITE_POSTURES = ("OPEN", "REHEARSING", "CONCERT_LOCK")


# ---------------------------------------------------------------- rehearsals
@route("POST", "/v1/rehearsals", roles=["ChoirDirector"], code=201)
def create_rehearsal(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "scheduled_at": ("datetime", True),
        "location": ("string", False),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    gate_season(season, REHEARSAL_WRITE_POSTURES)
    rehearsal = new_row(
        store.rehearsals,
        season_id=season["id"],
        scheduled_at=body["scheduled_at"],
        location=body.get("location"),
        status="SCHEDULED",
    )
    rehearsal["_scheduled_dt"] = parse_instant(body["scheduled_at"])
    return one(rehearsal_view, rehearsal, 201)


@route("GET", "/v1/rehearsals/{rid}", roles=ALL_ROLES)
def get_rehearsal(ctx):
    return one(rehearsal_view, get_or_404(store.rehearsals, ctx["path"]["rid"]))


@route("GET", "/v1/rehearsals", roles=ALL_ROLES)
def list_rehearsals(ctx):
    rows = apply_filters(all_of(store.rehearsals), {
        "season_id": ctx["args"].get("season_id"),
        "status": ctx["args"].get("status"),
    })
    return many(rehearsal_view, rows, ctx["args"])


@route("POST", "/v1/rehearsals/{rid}/cancel", roles=["ChoirDirector"])
def cancel_rehearsal(ctx):
    rehearsal = get_or_404(store.rehearsals, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    gate_season(store.seasons[rehearsal["season_id"]], REHEARSAL_WRITE_POSTURES)
    if rehearsal["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED rehearsal can be cancelled")
    rehearsal["status"] = "CANCELLED"
    touch(rehearsal)
    return one(rehearsal_view, rehearsal)


@route("POST", "/v1/rehearsals/{rid}/attendance", roles=["ChoirDirector"])
def record_attendance(ctx):
    rehearsal = get_or_404(store.rehearsals, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"records": ("array", True)})
    records = body["records"]
    for item in records:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each attendance record must be an object")
        for key in item:
            if key not in ("member_id", "status"):
                raise ApiError("ERR_INVALID_REQUEST", "unknown field on attendance record: %s" % key)
        if "member_id" not in item or not isinstance(item["member_id"], str):
            raise ApiError("ERR_INVALID_REQUEST", "attendance record requires member_id")
    members = [get_or_404(store.members, item["member_id"]) for item in records]
    for item in records:
        if "status" not in item or item["status"] is None:
            raise ApiError("ERR_INVALID_REQUEST", "attendance record requires status")
        check_enum(item, "status", ATTENDANCE_STATUSES)
    gate_season(store.seasons[rehearsal["season_id"]], REHEARSAL_WRITE_POSTURES)
    if rehearsal["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED rehearsal can be recorded")
    seen = set()
    for item in records:
        if item["member_id"] in seen:
            raise ApiError("ERR_DUPLICATE_ATTENDANCE", "member already has a record for this rehearsal")
        seen.add(item["member_id"])
    if rehearsal["_scheduled_dt"] > clock.now:
        raise ApiError("ERR_REHEARSAL_NOT_HELD", "the rehearsal has not taken place yet")
    rehearsal["status"] = "COMPLETED"
    touch(rehearsal)
    for item in records:
        new_row(
            store.attendance_records,
            rehearsal_id=rehearsal["id"],
            member_id=item["member_id"],
            status=item["status"],
            excused_by_user_id=None,
        )
    for member in list(store.members.values()):
        if member["season_id"] == rehearsal["season_id"]:
            sync_member(member)
    return one(rehearsal_view, rehearsal)


# ---------------------------------------------------------- attendance records
@route("GET", "/v1/attendance-records/{rid}", roles=ATTENDANCE_READ_ROLES)
def get_attendance_record(ctx):
    record = get_or_404(store.attendance_records, ctx["path"]["rid"])
    member_ownership_check(ctx, record["member_id"])
    return one(attendance_record_view, record)


@route("GET", "/v1/attendance-records", roles=ATTENDANCE_READ_ROLES)
def list_attendance_records(ctx):
    filters = scope_member_filter(ctx, {
        "rehearsal_id": ctx["args"].get("rehearsal_id"),
        "member_id": ctx["args"].get("member_id"),
        "status": ctx["args"].get("status"),
    })
    rows = apply_filters(all_of(store.attendance_records), filters)
    return many(attendance_record_view, rows, ctx["args"])


@route("POST", "/v1/attendance-records/{rid}/excuse", roles=["ChoirDirector"])
def excuse_attendance_record(ctx):
    record = get_or_404(store.attendance_records, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    rehearsal = store.rehearsals[record["rehearsal_id"]]
    gate_season(store.seasons[rehearsal["season_id"]], REHEARSAL_WRITE_POSTURES)
    if record["status"] != "ABSENT_UNEXCUSED":
        raise ApiError("ERR_INVALID_STATE", "only an ABSENT_UNEXCUSED record can be excused")
    record["status"] = "ABSENT_EXCUSED"
    record["excused_by_user_id"] = ctx["uid"]
    touch(record)
    sync_member(store.members[record["member_id"]])
    return one(attendance_record_view, record)


# -------------------------------------------------------------- music scores
@route("POST", "/v1/music-scores", roles=["Librarian"], code=201)
def create_score(ctx):
    body = check_body(ctx["body"], {
        "title": ("string", True),
        "copy_count": ("int", True),
        "replacement_cost_cents": ("int", True),
        "composer": ("string", False),
    })
    score = new_row(
        store.music_scores,
        title=body["title"],
        composer=body.get("composer"),
        copy_count=body["copy_count"],
        copies_available=body["copy_count"],
        copies_lost=0,
        replacement_cost_cents=body["replacement_cost_cents"],
        status="ACTIVE",
    )
    return one(score_view, score, 201)


@route("GET", "/v1/music-scores/{rid}", roles=ALL_ROLES)
def get_score(ctx):
    return one(score_view, get_or_404(store.music_scores, ctx["path"]["rid"]))


@route("GET", "/v1/music-scores", roles=ALL_ROLES)
def list_scores(ctx):
    rows = apply_filters(all_of(store.music_scores), {"status": ctx["args"].get("status")})
    return many(score_view, rows, ctx["args"])


@route("POST", "/v1/music-scores/{rid}/retire", roles=["Librarian"])
def retire_score(ctx):
    score = get_or_404(store.music_scores, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    if score["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE score can be retired")
    score["status"] = "RETIRED"
    touch(score)
    return one(score_view, score)


# ------------------------------------------------------------ score checkouts
@route("POST", "/v1/score-checkouts", roles=["Librarian"], code=201)
def create_checkout(ctx):
    ids = resolve_ids(ctx["body"], (store.music_scores, "score_id"), (store.members, "member_id"))
    body = check_body(ctx["body"], {
        "score_id": ("string", True),
        "member_id": ("string", True),
        "due_date": ("datetime", True),
    })
    score = ids.get("score_id") or get_or_404(store.music_scores, body["score_id"])
    member = ids.get("member_id") or get_or_404(store.members, body["member_id"])
    gate_season(store.seasons[member["season_id"]], CHECKOUT_WRITE_POSTURES)
    if score["status"] != "ACTIVE":
        raise ApiError("ERR_SCORE_RETIRED", "the score is RETIRED")
    if any(
        c["member_id"] == member["id"] and c["status"] == "OVERDUE"
        for c in store.score_checkouts.values()
    ):
        raise ApiError("ERR_LIBRARY_HOLD", "the member has an OVERDUE checkout")
    sync_score(score)
    if score["copies_available"] <= 0:
        raise ApiError("ERR_NO_COPIES_AVAILABLE", "no copies are available")
    checkout = new_row(
        store.score_checkouts,
        score_id=score["id"],
        member_id=member["id"],
        checked_out_at=clock.now_server_string(),
        due_date=body["due_date"],
        returned_at=None,
        status="CHECKED_OUT",
        fine_cents=0,
        charge_cents=0,
    )
    checkout["_due_dt"] = parse_instant(body["due_date"])
    sync_score(score)
    return one(checkout_view, checkout, 201)


@route("GET", "/v1/score-checkouts/{rid}", roles=ALL_ROLES)
def get_checkout(ctx):
    checkout = get_or_404(store.score_checkouts, ctx["path"]["rid"])
    member_ownership_check(ctx, checkout["member_id"])
    return one(checkout_view, checkout)


@route("GET", "/v1/score-checkouts", roles=ALL_ROLES)
def list_checkouts(ctx):
    filters = scope_member_filter(ctx, {
        "score_id": ctx["args"].get("score_id"),
        "member_id": ctx["args"].get("member_id"),
        "status": ctx["args"].get("status"),
    })
    return many(checkout_view, apply_filters(all_of(store.score_checkouts), filters), ctx["args"])


def _checkout_for_write(ctx):
    checkout = get_or_404(store.score_checkouts, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    member = store.members[checkout["member_id"]]
    gate_season(store.seasons[member["season_id"]], CHECKOUT_WRITE_POSTURES)
    if checkout["status"] not in ("CHECKED_OUT", "OVERDUE"):
        raise ApiError("ERR_CHECKOUT_NOT_ACTIVE", "the checkout is not CHECKED_OUT or OVERDUE")
    return checkout, member


@route("POST", "/v1/score-checkouts/{rid}/return", roles=["Librarian"])
def return_checkout(ctx):
    checkout, member = _checkout_for_write(ctx)
    if checkout["status"] == "OVERDUE" and checkout["fine_cents"]:
        member["ledger_balance_cents"] += checkout["fine_cents"]
        touch(member)
    checkout["status"] = "RETURNED"
    checkout["returned_at"] = clock.now_server_string()
    touch(checkout)
    sync_score(store.music_scores[checkout["score_id"]])
    sync_member(member)
    return one(checkout_view, checkout)


@route("POST", "/v1/score-checkouts/{rid}/mark-lost", roles=["Librarian"])
def mark_lost_checkout(ctx):
    checkout, member = _checkout_for_write(ctx)
    score = store.music_scores[checkout["score_id"]]
    charge = score["replacement_cost_cents"]
    checkout["charge_cents"] = charge
    member["ledger_balance_cents"] += charge
    if checkout["status"] == "OVERDUE":
        member["ledger_balance_cents"] += checkout["fine_cents"]
    checkout["status"] = "LOST"
    touch(checkout)
    score["copies_lost"] += 1
    touch(score)
    sync_score(score)
    touch(member)
    sync_member(member)
    return one(checkout_view, checkout)
