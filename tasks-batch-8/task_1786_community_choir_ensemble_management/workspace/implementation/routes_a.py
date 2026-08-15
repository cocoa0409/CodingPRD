"""Routes: clock, seasons, sections, members, auditions."""

from decimal import Decimal

import store
from domain import (
    AUDITION_DECISIONS, MEMBER_STATUS_ACTIONS, POSTURES, SECTION_STATUSES,
    VOICE_PARTS, gate_season, member_departure_cascade, promote_member_waitlist,
    run_checkpoint, sync_member, sync_section, dec, rhu_cents,
)
from envelope import object_response
from errors import ApiError
from routes_common import (
    apply_filters, many, member_ownership_check, one, route,
    scope_member_filter,
)
from serializers import audition_view, member_view, season_view, section_view
from store import all_of, new_row, touch
from timeutil import clock, parse_instant
from validate import check_body, check_enum, get_or_404, resolve_ids

ALL_ROLES = ("President", "Treasurer", "ChoirDirector", "Librarian", "Member")

SEASON_CONFIG_FIELDS = {
    "name": ("string", False),
    "base_dues_cents": ("int", False),
    "early_bird_pct": ("number", False),
    "early_bird_cutoff": ("datetime", False),
    "dues_due_date": ("datetime", False),
    "late_fee_weekly_cents": ("int", False),
    "late_fee_cap_cents": ("int", False),
    "scholarship_pool_cents": ("int", False),
    "audition_slot_minutes": ("int", False),
    "attendance_threshold": ("number", False),
}


# ------------------------------------------------------------------- clock
@route("POST", "/v1/_clock/set_current_utc", roles=["President"])
def set_current_utc(ctx):
    body = check_body(ctx["body"], {"to_iso8601": ("datetime", True)})
    raw = body["to_iso8601"]
    clock.set(parse_instant(raw), raw)
    return object_response({"current_utc": clock.raw}, 200)


# ------------------------------------------------------------------ seasons
@route("POST", "/v1/seasons", roles=["President"], code=201)
def create_season(ctx):
    spec = {
        "name": ("string", True),
        "base_dues_cents": ("int", True),
        "early_bird_pct": ("number", True),
        "early_bird_cutoff": ("datetime", True),
        "dues_due_date": ("datetime", True),
        "late_fee_weekly_cents": ("int", True),
        "late_fee_cap_cents": ("int", True),
        "scholarship_pool_cents": ("int", True),
        "audition_slot_minutes": ("int", False),
        "attendance_threshold": ("number", False),
    }
    body = check_body(ctx["body"], spec)
    season = new_row(
        store.seasons,
        name=body["name"],
        base_dues_cents=body["base_dues_cents"],
        early_bird_pct=body["early_bird_pct"],
        early_bird_cutoff=body["early_bird_cutoff"],
        dues_due_date=body["dues_due_date"],
        late_fee_weekly_cents=body["late_fee_weekly_cents"],
        late_fee_cap_cents=body["late_fee_cap_cents"],
        scholarship_pool_cents=body["scholarship_pool_cents"],
        audition_slot_minutes=body.get("audition_slot_minutes", 30),
        attendance_threshold=body.get("attendance_threshold", 0.75),
        posture="DRAFT",
        ops_week_index=0,
        pool_available_cents=body["scholarship_pool_cents"],
        pool_reserved_cents=0,
        pool_spent_cents=0,
        treasury_balance_cents=0,
    )
    season["_early_bird_cutoff_dt"] = parse_instant(body["early_bird_cutoff"])
    season["_dues_due_dt"] = parse_instant(body["dues_due_date"])
    return one(season_view, season, 201)


@route("GET", "/v1/seasons/{rid}", roles=ALL_ROLES)
def get_season(ctx):
    return one(season_view, get_or_404(store.seasons, ctx["path"]["rid"]))


@route("GET", "/v1/seasons", roles=ALL_ROLES)
def list_seasons(ctx):
    rows = apply_filters(all_of(store.seasons), {"posture": ctx["args"].get("posture")})
    return many(season_view, rows, ctx["args"])


@route("PATCH", "/v1/seasons/{rid}", roles=["President"])
def patch_season(ctx):
    season = get_or_404(store.seasons, ctx["path"]["rid"])
    spec = dict(SEASON_CONFIG_FIELDS)
    spec["expected_season_version"] = ("int", True)
    body = check_body(ctx["body"], spec)
    if body["expected_season_version"] != season["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_season_version does not match the season version")
    gate_season(season, None)
    if "scholarship_pool_cents" in body:
        delta = body["scholarship_pool_cents"] - season["scholarship_pool_cents"]
        season["pool_available_cents"] += delta
    for field, (kind, _req) in SEASON_CONFIG_FIELDS.items():
        if field in body:
            season[field] = body[field]
    if "early_bird_cutoff" in body:
        season["_early_bird_cutoff_dt"] = parse_instant(body["early_bird_cutoff"])
    if "dues_due_date" in body:
        season["_dues_due_dt"] = parse_instant(body["dues_due_date"])
    touch(season)
    return one(season_view, season)


_POSTURE_TRANSITIONS = {
    ("DRAFT", "OPEN"),
    ("DRAFT", "ARCHIVED"),
    ("OPEN", "REHEARSING"),
    ("REHEARSING", "CONCERT_LOCK"),
    ("CONCERT_LOCK", "ARCHIVED"),
}


@route("POST", "/v1/seasons/{rid}/posture", roles=["President"])
def season_posture(ctx):
    season = get_or_404(store.seasons, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"posture": ("string", True)})
    check_enum(body, "posture", POSTURES)
    gate_season(season, None)
    target = body["posture"]
    if (season["posture"], target) not in _POSTURE_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", "posture transition %s -> %s is not legal" % (season["posture"], target))
    if season["posture"] == "OPEN" and target == "REHEARSING":
        for section in all_of(store.sections):
            if section["season_id"] != season["id"] or section["status"] != "OPEN":
                continue
            sync_section(section)
            if not (section["target_min"] <= section["active_count"] <= section["target_max"]):
                raise ApiError("ERR_SECTION_UNBALANCED", "OPEN section fails the balance gate")
        if any(
            store.members[a["member_id"]]["season_id"] == season["id"] and a["status"] == "SCHEDULED"
            for a in store.auditions.values()
        ):
            raise ApiError("ERR_AUDITIONS_PENDING", "SCHEDULED auditions remain")
    if season["posture"] == "CONCERT_LOCK" and target == "ARCHIVED":
        if any(
            c["season_id"] == season["id"] and c["status"] not in ("PERFORMED", "CANCELLED")
            for c in store.concerts.values()
        ):
            raise ApiError("ERR_CONCERTS_OPEN", "non-terminal concerts remain")
    season["posture"] = target
    touch(season)
    return one(season_view, season)


@route("POST", "/v1/seasons/{rid}/checkpoint", roles=["President"])
def season_checkpoint(ctx):
    season = get_or_404(store.seasons, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"expected_season_version": ("int", True)})
    if body["expected_season_version"] != season["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_season_version does not match the season version")
    gate_season(season, None)
    run_checkpoint(season)
    return one(season_view, season)


# ----------------------------------------------------------------- sections
@route("POST", "/v1/sections", roles=["ChoirDirector"], code=201)
def create_section(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "voice_part": ("string", True),
        "target_min": ("int", True),
        "target_max": ("int", True),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    check_enum(body, "voice_part", VOICE_PARTS)
    gate_season(season, None)
    if any(s["season_id"] == season["id"] and s["voice_part"] == body["voice_part"] for s in store.sections.values()):
        raise ApiError("ERR_DUPLICATE_SECTION", "voice_part already exists for this season")
    section = new_row(
        store.sections,
        season_id=season["id"],
        voice_part=body["voice_part"],
        target_min=body["target_min"],
        target_max=body["target_max"],
        status="OPEN",
        active_count=0,
    )
    return one(section_view, section, 201)


@route("GET", "/v1/sections/{rid}", roles=ALL_ROLES)
def get_section(ctx):
    return one(section_view, get_or_404(store.sections, ctx["path"]["rid"]))


@route("GET", "/v1/sections", roles=ALL_ROLES)
def list_sections(ctx):
    rows = apply_filters(all_of(store.sections), {
        "season_id": ctx["args"].get("season_id"),
        "voice_part": ctx["args"].get("voice_part"),
        "status": ctx["args"].get("status"),
    })
    return many(section_view, rows, ctx["args"])


@route("PATCH", "/v1/sections/{rid}", roles=["ChoirDirector"])
def patch_section(ctx):
    section = get_or_404(store.sections, ctx["path"]["rid"])
    body = check_body(ctx["body"], {
        "target_min": ("int", False),
        "target_max": ("int", False),
        "status": ("string", False),
    })
    check_enum(body, "status", SECTION_STATUSES)
    gate_season(store.seasons[section["season_id"]], None)
    for field in ("target_min", "target_max", "status"):
        if field in body:
            section[field] = body[field]
    touch(section)
    return one(section_view, section)


# ------------------------------------------------------------------ members
@route("POST", "/v1/members", roles=["ChoirDirector"], code=201)
def create_member(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "full_name": ("string", True),
        "email": ("string", True),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    gate_season(season, ("OPEN", "REHEARSING"))
    if any(m["season_id"] == season["id"] and m["email"] == body["email"] for m in store.members.values()):
        raise ApiError("ERR_DUPLICATE_MEMBERSHIP", "email already registered for this season")
    member = new_row(
        store.members,
        season_id=season["id"],
        full_name=body["full_name"],
        email=body["email"],
        section_id=None,
        status="APPLICANT",
        enrolled_at=None,
        attendance_rate=1.0,
        performance_eligible=False,
        dues_balance_cents=0,
        ledger_balance_cents=0,
    )
    member["_enrolled_dt"] = None
    return one(member_view, member, 201)


@route("GET", "/v1/members/{rid}", roles=ALL_ROLES)
def get_member(ctx):
    rid = ctx["path"]["rid"]
    member_ownership_check(ctx, rid)
    return one(member_view, get_or_404(store.members, rid))


@route("GET", "/v1/members", roles=ALL_ROLES)
def list_members(ctx):
    filters = {
        "season_id": ctx["args"].get("season_id"),
        "section_id": ctx["args"].get("section_id"),
        "status": ctx["args"].get("status"),
    }
    if ctx["role"] == "Member":
        rows = [m for m in all_of(store.members) if m["id"] == ctx["uid"]]
    else:
        rows = all_of(store.members)
    return many(member_view, apply_filters(rows, filters), ctx["args"])


@route("POST", "/v1/members/{rid}/status", roles=["ChoirDirector"])
def member_status(ctx):
    member = get_or_404(store.members, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"action": ("string", True)})
    check_enum(body, "action", MEMBER_STATUS_ACTIONS)
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    action = body["action"]
    if action == "DROP":
        if member["status"] == "WAITLISTED":
            member["status"] = "REJECTED"
            touch(member)
            sync_member(member)
            return one(member_view, member)
        if member["status"] not in ("ENROLLED", "ACTIVE", "PROBATION", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", "DROP is not legal from %s" % member["status"])
        member["status"] = "DROPPED"
        touch(member)
        member_departure_cascade(member)
        sync_member(member)
        return one(member_view, member)
    if action == "SUSPEND":
        if member["status"] not in ("ACTIVE", "PROBATION"):
            raise ApiError("ERR_INVALID_STATE", "SUSPEND is not legal from %s" % member["status"])
        member["status"] = "SUSPENDED"
        touch(member)
        sync_member(member)
        return one(member_view, member)
    # REINSTATE
    if member["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "REINSTATE is not legal from %s" % member["status"])
    sync_member(member)
    season = store.seasons[member["season_id"]]
    if member["dues_balance_cents"] != 0 or dec(member["attendance_rate"]) < dec(season["attendance_threshold"]):
        raise ApiError("ERR_INVALID_STATE", "reinstatement requires zero dues balance and attendance at threshold")
    member["status"] = "ACTIVE"
    touch(member)
    sync_member(member)
    return one(member_view, member)


@route("POST", "/v1/members/{rid}/resign", roles=["Member", "ChoirDirector"])
def member_resign(ctx):
    member_ownership_check(ctx, ctx["path"]["rid"])
    member = get_or_404(store.members, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    if member["status"] not in ("ENROLLED", "ACTIVE", "PROBATION", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "resign is not legal from %s" % member["status"])
    member["status"] = "RESIGNED"
    touch(member)
    member_departure_cascade(member)
    sync_member(member)
    return one(member_view, member)


# ----------------------------------------------------------------- auditions
@route("POST", "/v1/auditions", roles=["ChoirDirector"], code=201)
def create_audition(ctx):
    ids = resolve_ids(ctx["body"], (store.members, "member_id"))
    body = check_body(ctx["body"], {
        "member_id": ("string", True),
        "scheduled_at": ("datetime", True),
    })
    member = ids.get("member_id") or get_or_404(store.members, body["member_id"])
    season = store.seasons[member["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    if member["status"] != "APPLICANT":
        raise ApiError("ERR_INVALID_STATE", "auditions can only be booked for an APPLICANT")
    new_dt = parse_instant(body["scheduled_at"])
    buffer = season["audition_slot_minutes"] * 60
    for other in store.auditions.values():
        other_member = store.members[other["member_id"]]
        if other_member["season_id"] != season["id"] or other["status"] == "CANCELLED":
            continue
        if abs((new_dt - other["_scheduled_dt"]).total_seconds()) < buffer:
            raise ApiError("ERR_AUDITION_OVERLAP", "audition slot violates the buffered-slot rule")
    audition = new_row(
        store.auditions,
        member_id=member["id"],
        scheduled_at=body["scheduled_at"],
        status="SCHEDULED",
        tone_score=None,
        pitch_score=None,
        sight_score=None,
        composite_score=None,
        decision="NONE",
    )
    audition["_scheduled_dt"] = new_dt
    member["status"] = "AUDITION_SCHEDULED"
    touch(member)
    sync_member(member)
    return one(audition_view, audition, 201)


@route("GET", "/v1/auditions/{rid}", roles=ALL_ROLES)
def get_audition(ctx):
    return one(audition_view, get_or_404(store.auditions, ctx["path"]["rid"]))


@route("GET", "/v1/auditions", roles=ALL_ROLES)
def list_auditions(ctx):
    rows = apply_filters(all_of(store.auditions), {
        "member_id": ctx["args"].get("member_id"),
        "status": ctx["args"].get("status"),
    })
    return many(audition_view, rows, ctx["args"])


def _audition_write(ctx):
    audition = get_or_404(store.auditions, ctx["path"]["rid"])
    member = store.members[audition["member_id"]]
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    return audition, member


@route("POST", "/v1/auditions/{rid}/score", roles=["ChoirDirector"])
def score_audition(ctx):
    audition = get_or_404(store.auditions, ctx["path"]["rid"])
    body = check_body(ctx["body"], {
        "tone_score": ("int", True),
        "pitch_score": ("int", True),
        "sight_score": ("int", True),
    })
    for name in ("tone_score", "pitch_score", "sight_score"):
        if not (0 <= body[name] <= 10):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be between 0 and 10" % name)
    member = store.members[audition["member_id"]]
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    if audition["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED audition can be scored")
    composite = (
        Decimal("0.40") * body["tone_score"]
        + Decimal("0.35") * body["pitch_score"]
        + Decimal("0.25") * body["sight_score"]
    ).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    audition["tone_score"] = body["tone_score"]
    audition["pitch_score"] = body["pitch_score"]
    audition["sight_score"] = body["sight_score"]
    audition["composite_score"] = float(composite)
    audition["status"] = "COMPLETED"
    touch(audition)
    if member["status"] == "AUDITION_SCHEDULED":
        member["status"] = "AUDITIONED"
        touch(member)
        sync_member(member)
    return one(audition_view, audition)


@route("POST", "/v1/auditions/{rid}/cancel", roles=["ChoirDirector"])
def cancel_audition(ctx):
    audition = get_or_404(store.auditions, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    member = store.members[audition["member_id"]]
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    if audition["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED audition can be cancelled")
    audition["status"] = "CANCELLED"
    touch(audition)
    if member["status"] == "AUDITION_SCHEDULED":
        member["status"] = "APPLICANT"
        touch(member)
        sync_member(member)
    return one(audition_view, audition)


@route("POST", "/v1/auditions/{rid}/decision", roles=["ChoirDirector"])
def decide_audition(ctx):
    audition = get_or_404(store.auditions, ctx["path"]["rid"])
    body = ctx["body"]
    # tier 4: body id existence (section_id) is validated before shape
    section = None
    if isinstance(body, dict) and body.get("section_id") is not None:
        section = get_or_404(store.sections, body["section_id"])
    body = check_body(body, {
        "decision": ("string", True),
        "section_id": ("string", False),
    })
    check_enum(body, "decision", AUDITION_DECISIONS)
    if body["decision"] == "ACCEPT" and section is None:
        raise ApiError("ERR_INVALID_REQUEST", "section_id is required for ACCEPT")
    member = store.members[audition["member_id"]]
    gate_season(store.seasons[member["season_id"]], ("OPEN", "REHEARSING"))
    if audition["status"] != "COMPLETED":
        raise ApiError("ERR_AUDITION_NOT_SCORED", "the audition is not COMPLETED")
    if member["status"] != "AUDITIONED":
        raise ApiError("ERR_INVALID_STATE", "the audition has already been decided")
    decision = body["decision"]
    if decision in ("ACCEPT", "WAITLIST"):
        if dec(audition["composite_score"]) < Decimal("7.0"):
            raise ApiError("ERR_SCORE_BELOW_THRESHOLD", "composite_score is below 7.0")
    if decision == "ACCEPT":
        if section["status"] != "OPEN":
            raise ApiError("ERR_SECTION_CLOSED", "the section is CLOSED")
        sync_section(section)
        if section["active_count"] >= section["target_max"]:
            raise ApiError("ERR_SECTION_FULL", "the section has reached target_max")
        audition["decision"] = "ACCEPTED"
        member["status"] = "ENROLLED"
        member["section_id"] = section["id"]
        member["enrolled_at"] = clock.now_server_string()
        member["_enrolled_dt"] = clock.now
    elif decision == "WAITLIST":
        audition["decision"] = "WAITLISTED"
        member["status"] = "WAITLISTED"
    else:
        audition["decision"] = "REJECTED"
        member["status"] = "REJECTED"
    touch(audition)
    touch(member)
    if decision == "ACCEPT":
        sync_section(section)
    sync_member(member)
    return one(audition_view, audition)
