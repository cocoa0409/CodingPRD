"""Events, tournament entries, weigh-ins, seeding and eligibility checks."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookups
import serialize
import validate as V
from auth import endpoint, require_team_owner, user_id
from envelope import ok, ok_list
from errors import ApiError
from routes.core import require_open
from store import (
    DB,
    clock_date,
    clock_iso,
    day_start,
    fmt_date,
    new_row,
    parse_date,
    touch,
)

bp = Blueprint("compete", __name__)

EVENT_TYPES = ("DUAL", "TOURNAMENT", "STATE_CHAMPIONSHIP")
EVENT_STATUSES = ("SCHEDULED", "WEIGH_IN_OPEN", "WEIGH_IN_CLOSED", "SEEDED",
                  "COMPLETED", "CANCELLED")
ENTRY_STATUSES = ("ENTERED", "WEIGHED_IN", "SEEDED", "SCRATCHED", "DISQUALIFIED")
WEIGH_IN_RESULTS = ("PASS", "PASS_WITH_ALLOWANCE", "FAIL")
CHECK_OUTCOMES = ("CLEARED", "BLOCKED_DISQUALIFIED", "BLOCKED_NOT_CERTIFIED",
                  "BLOCKED_ESCALATED_FLAG", "BLOCKED_CLASS_BELOW_MINIMUM",
                  "BLOCKED_PLAN_BREACHED", "BLOCKED_TEAM_PROBATION")


def _competition_window(event):
    start = parse_date(event.get("event_date"))
    days = int(event.get("competition_days") or 1)
    return day_start(start), day_start(start + timedelta(days=days))


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------

@bp.post("/seasons/<season_id>/events")
@endpoint("StateOffice")
def create_event(season_id):
    season = lookups.season(season_id)
    body = V.get_body()
    name = V.req_str(body, "name", max_len=160, allow_empty=False)
    event_type = V.req_enum(body, "event_type", EVENT_TYPES)
    event_date = V.req_date(body, "event_date")
    competition_days = V.opt_int(body, "competition_days", minimum=1, maximum=4, default=1)
    weigh_in_days = V.opt_int(body, "weigh_in_days", minimum=1, maximum=4, default=1)
    allowance = V.opt_num(body, "consecutive_day_allowance_lbs",
                          minimum=0, maximum=2.0, default=1.0)
    require_open(season)
    row = new_row()
    row.update({
        "season_id": season["id"],
        "name": name,
        "event_type": event_type,
        "event_date": fmt_date(event_date),
        "competition_days": competition_days,
        "weigh_in_days": weigh_in_days,
        "consecutive_day_allowance_lbs": allowance,
        "status": "SCHEDULED",
        "bracket_locked": False,
        "reseed_required": False,
    })
    DB.events[row["id"]] = row
    return ok(serialize.event(row), 201)


@bp.get("/events/<event_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_event(event_id):
    return ok(serialize.event(lookups.event(event_id)))


@bp.get("/events")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_events():
    season_id = V.q_str("season_id")
    status = V.q_enum("status", EVENT_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.events.values())
    if season_id is not None:
        rows = [r for r in rows if r.get("season_id") == season_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.event(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/events/<event_id>/status")
@endpoint("StateOffice")
def event_status(event_id):
    event = lookups.event(event_id)
    body = V.get_body()
    target = V.req_enum(body, "status", EVENT_STATUSES)
    current = event.get("status")
    season = lookups.season_of_event(event)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    def invalid():
        raise ApiError(
            "ERR_EVENT_INVALID_STATE",
            "Transition '%s' is not declared out of '%s'." % (target, current),
        )

    entries = sorted(lookups.entries_of_event(event["id"]),
                     key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))

    if target == "WEIGH_IN_OPEN":
        if current != "SCHEDULED":
            invalid()
        require_open(season)
        event["status"] = "WEIGH_IN_OPEN"
        touch(event)
    elif target == "WEIGH_IN_CLOSED":
        if current != "WEIGH_IN_OPEN":
            invalid()
        for entry in entries:
            status = entry.get("status")
            if status not in ("ENTERED", "WEIGHED_IN"):
                continue
            latest = cascade.most_recent_weigh_in(entry["id"])
            failed = latest is not None and latest.get("result") == "FAIL"
            if status == "ENTERED":
                entry["status"] = "SCRATCHED"
                entry["scratch_reason"] = "WEIGH_IN_FAILED" if failed else "NO_WEIGH_IN"
                touch(entry)
            elif failed:
                entry["status"] = "SCRATCHED"
                entry["scratch_reason"] = "WEIGH_IN_FAILED"
                touch(entry)
        event["status"] = "WEIGH_IN_CLOSED"
        touch(event)
    elif target == "CANCELLED":
        if current not in ("SCHEDULED", "WEIGH_IN_OPEN"):
            invalid()
        for entry in entries:
            if entry.get("status") not in ("ENTERED", "WEIGHED_IN"):
                continue
            entry["status"] = "SCRATCHED"
            entry["scratch_reason"] = "EVENT_CANCELLED"
            touch(entry)
        event["status"] = "CANCELLED"
        touch(event)
    elif target == "COMPLETED":
        if current not in ("WEIGH_IN_CLOSED", "SEEDED"):
            invalid()
        if event.get("reseed_required"):
            raise ApiError("ERR_RESEED_REQUIRED",
                           "The bracket has been invalidated and must be reseeded.")
        event["status"] = "COMPLETED"
        touch(event)
    else:
        invalid()
    return ok(serialize.event(event))


@bp.post("/events/<event_id>/seed")
@endpoint("StateOffice")
def seed_event(event_id):
    event = lookups.event(event_id)
    current = event.get("status")
    if current == "WEIGH_IN_CLOSED":
        admitted = ("WEIGHED_IN",)
        initial = True
    elif current == "SEEDED" and event.get("reseed_required"):
        admitted = ("WEIGHED_IN", "SEEDED")
        initial = False
    else:
        raise ApiError("ERR_EVENT_INVALID_STATE",
                       "Seeding is accepted out of WEIGH_IN_CLOSED, or out of SEEDED "
                       "when a reseed is required.")

    all_entries = lookups.entries_of_event(event["id"])
    pool = [e for e in all_entries if e.get("status") in admitted]
    if not pool:
        raise ApiError("ERR_NO_SEEDABLE_ENTRIES",
                       "No entry of this event is eligible for a bracket position.")

    # Excluded entries never keep a seed number.
    pool_ids = {e["id"] for e in pool}
    for entry in all_entries:
        if entry["id"] not in pool_ids and entry.get("seed_number") is not None:
            entry["seed_number"] = None
            touch(entry)

    for entry, seed_number in calc.seed_assignment(pool):
        entry["seed_number"] = seed_number
        entry["status"] = "SEEDED"
        touch(entry)

    event["status"] = "SEEDED"
    if initial:
        event["bracket_locked"] = True
    event["reseed_required"] = False
    touch(event)
    return ok(serialize.event(event))


# --------------------------------------------------------------------------
# tournament entries
# --------------------------------------------------------------------------

@bp.post("/events/<event_id>/entries")
@endpoint("TeamCoach")
def create_entry(event_id):
    event = lookups.event(event_id)
    body = V.get_body()
    wrestler = lookups.wrestler(V.req_id_ref(body, "wrestler_id"))
    require_team_owner(wrestler.get("team_id"))

    season = lookups.season_of_event(event)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    weight_class_lbs = V.weight_class(body, "weight_class_lbs", season)
    season_win_count = V.opt_int(body, "season_win_count", minimum=0, default=0)

    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler cannot be entered in a competition.")
    require_open(season)

    if wrestler.get("certification_status") in ("UNCERTIFIED", "SUSPENDED"):
        raise ApiError("ERR_WRESTLER_NOT_CERTIFIED",
                       "The wrestler has no validated source assessment on file.")
    if cascade.has_escalated_flag(wrestler["id"]):
        raise ApiError("ERR_UNHEALTHY_WEIGHT_MANAGEMENT",
                       "The wrestler carries an ESCALATED health flag.")

    event_date = parse_date(event.get("event_date"))
    floor = calc.lowest_eligible_class_at_date(season, wrestler, event_date)
    lowest = floor["lowest_eligible_class_lbs"]
    if lowest is None:
        raise ApiError("ERR_NO_ELIGIBLE_WEIGHT_CLASS",
                       "No class in the season satisfies the wrestler's floor.")
    if int(weight_class_lbs) < int(lowest):
        raise ApiError("ERR_CLASS_BELOW_CERTIFIED_MINIMUM",
                       "weight_class_lbs is below the wrestler's lowest eligible class.")

    if serialize.team_posture(wrestler.get("team_id")) == "PROBATION":
        raise ApiError("ERR_TEAM_ON_PROBATION",
                       "A team on PROBATION may not enter wrestlers.")
    if event.get("bracket_locked"):
        raise ApiError("ERR_BRACKET_LOCKED",
                       "The event's bracket is locked; no new entry may be added.")

    opens, closes = _competition_window(event)
    for other in lookups.entries_of_wrestler(wrestler["id"]):
        if other.get("status") == "SCRATCHED":
            continue
        other_event = DB.events.get(other.get("event_id"))
        if other_event is None or other_event["id"] == event["id"]:
            continue
        o_opens, o_closes = _competition_window(other_event)
        if opens < o_closes and o_opens < closes:
            raise ApiError("ERR_ENTRY_WINDOW_CONFLICT",
                           "The wrestler already competes inside an overlapping window.")

    for other in lookups.entries_of_event(event["id"]):
        if (other.get("wrestler_id") == wrestler["id"]
                and other.get("status") != "SCRATCHED"):
            raise ApiError("ERR_DUPLICATE_ENTRY",
                           "The wrestler already holds a live entry on this event.")

    row = new_row()
    row.update({
        "event_id": event["id"],
        "wrestler_id": wrestler["id"],
        "weight_class_lbs": weight_class_lbs,
        "season_win_count": season_win_count,
        "status": "ENTERED",
        "seed_number": None,
        "latest_effective_weight_lbs": None,
        "weight_class_change_count": 0,
        "scratch_reason": None,
    })
    DB.entries[row["id"]] = row
    return ok(serialize.entry(row), 201)


@bp.get("/entries/<entry_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_entry(entry_id):
    return ok(serialize.entry(lookups.entry(entry_id)))


@bp.get("/entries")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_entries():
    event_id = V.q_str("event_id")
    wrestler_id = V.q_str("wrestler_id")
    status = V.q_enum("status", ENTRY_STATUSES)
    weight_class_lbs = V.q_int("weight_class_lbs")
    limit, offset = V.pagination()
    rows = list(DB.entries.values())
    if event_id is not None:
        rows = [r for r in rows if r.get("event_id") == event_id]
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if weight_class_lbs is not None:
        rows = [r for r in rows if int(r.get("weight_class_lbs") or 0) == weight_class_lbs]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.entry(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/entries/<entry_id>/weight-class-change")
@endpoint("StateOffice")
def change_weight_class(entry_id):
    entry = lookups.entry(entry_id)
    event = DB.events.get(entry.get("event_id"))
    if event is None:
        raise ApiError("ERR_EVENT_NOT_FOUND")
    wrestler = DB.wrestlers.get(entry.get("wrestler_id"))
    if wrestler is None:
        raise ApiError("ERR_WRESTLER_NOT_FOUND")
    season = lookups.season_of_event(event)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    body = V.get_body()
    new_class = V.weight_class(body, "weight_class_lbs", season)
    expected = V.req_int(body, "expected_entry_version")
    if expected != int(entry.get("version") or 0):
        raise ApiError(
            "ERR_STALE_ENTRY_VERSION",
            "expected_entry_version %s does not match the entry's stored version %s."
            % (expected, entry.get("version")),
        )
    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler's entry cannot be moved.")

    if entry.get("status") != "SEEDED":
        raise ApiError("ERR_ENTRY_INVALID_STATE",
                       "Only a SEEDED entry may be moved between weight classes.")
    if not event.get("bracket_locked"):
        raise ApiError("ERR_EVENT_INVALID_STATE",
                       "A weight-class change requires a locked bracket.")

    if cascade.has_escalated_flag(wrestler["id"]):
        raise ApiError("ERR_UNHEALTHY_WEIGHT_MANAGEMENT",
                       "The wrestler carries an ESCALATED health flag.")

    event_date = parse_date(event.get("event_date"))
    floor = calc.lowest_eligible_class_at_date(season, wrestler, event_date)
    lowest = floor["lowest_eligible_class_lbs"]
    if lowest is None or int(new_class) < int(lowest):
        raise ApiError("ERR_CLASS_BELOW_CERTIFIED_MINIMUM",
                       "weight_class_lbs is below the wrestler's lowest eligible class.")

    old_class = int(entry.get("weight_class_lbs"))
    entry["weight_class_lbs"] = new_class
    entry["weight_class_change_count"] = int(entry.get("weight_class_change_count") or 0) + 1
    touch(entry)

    cascade.reseed_classes(event, (old_class, new_class), skip_entry_id=entry["id"])
    touch(event)
    return ok(serialize.entry(entry))


# --------------------------------------------------------------------------
# weigh-ins
# --------------------------------------------------------------------------

@bp.post("/events/<event_id>/weigh-ins")
@endpoint("WeighInOfficial", "StateOffice")
def record_weigh_in(event_id):
    event = lookups.event(event_id)
    body = V.get_body()
    entry = lookups.entry(V.req_id_ref(body, "entry_id"))
    if entry.get("event_id") != event["id"]:
        raise ApiError("ERR_ENTRY_NOT_FOUND",
                       "The referenced entry does not belong to this event.")
    wrestler = DB.wrestlers.get(entry.get("wrestler_id"))
    if wrestler is None:
        raise ApiError("ERR_WRESTLER_NOT_FOUND")
    season = lookups.season_of_event(event)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    day_index = V.req_int(body, "day_index", minimum=0)
    recorded_weight_lbs = V.req_num(body, "recorded_weight_lbs",
                                    minimum=60.0, maximum=400.0)

    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler cannot be weighed in.")
    require_open(season)

    if event.get("status") != "WEIGH_IN_OPEN":
        raise ApiError("ERR_EVENT_INVALID_STATE",
                       "A weigh-in may only be recorded while the event is WEIGH_IN_OPEN.")
    if entry.get("status") in ("SCRATCHED", "DISQUALIFIED"):
        raise ApiError("ERR_ENTRY_INVALID_STATE",
                       "A scratched or disqualified entry cannot be weighed.")
    if wrestler.get("certification_status") in ("UNCERTIFIED", "SUSPENDED"):
        raise ApiError("ERR_WRESTLER_NOT_CERTIFIED",
                       "The wrestler has no validated source assessment on file.")

    event_date = parse_date(event.get("event_date"))
    if day_index > int(event.get("weigh_in_days") or 1) - 1:
        raise ApiError("ERR_WEIGH_IN_DAY_OUT_OF_RANGE",
                       "day_index exceeds the event's permitted weigh-in days.")
    if clock_date() != event_date + timedelta(days=day_index):
        raise ApiError("ERR_WEIGH_IN_DAY_OUT_OF_RANGE",
                       "recorded_at must fall on the event date advanced by day_index days.")

    for existing in lookups.weighins_of_entry(entry["id"]):
        if int(existing.get("day_index") or 0) == day_index:
            raise ApiError("ERR_DUPLICATE_WEIGH_IN",
                           "A weigh-in already exists for that entry and day index.")

    allowance, effective_limit, result, below_minimum = calc.weigh_in_allowance_and_result(
        season, event, entry, wrestler, day_index, recorded_weight_lbs)

    row = new_row(common=False)
    row.update({
        "event_id": event["id"],
        "wrestler_id": wrestler["id"],
        "entry_id": entry["id"],
        "day_index": day_index,
        "recorded_weight_lbs": recorded_weight_lbs,
        "recorded_at": clock_iso(),
        "official_user_id": user_id(),
        "allowance_lbs": allowance,
        "effective_limit_lbs": effective_limit,
        "result": result,
        "below_minimum": below_minimum,
    })
    DB.weighins[row["id"]] = row

    if result in ("PASS", "PASS_WITH_ALLOWANCE"):
        entry["status"] = "WEIGHED_IN"
        cascade.refresh_latest_effective_weight(entry)
        touch(entry)

    if below_minimum:
        cascade.raise_flag(wrestler, "WEIGH_IN_DEFICIT", weigh_in_id=row["id"])

    return ok(serialize.weigh_in(row), 201)


@bp.get("/weigh-ins/<weigh_in_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_weigh_in(weigh_in_id):
    return ok(serialize.weigh_in(lookups.weigh_in(weigh_in_id)))


@bp.get("/weigh-ins")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_weigh_ins():
    event_id = V.q_str("event_id")
    wrestler_id = V.q_str("wrestler_id")
    entry_id = V.q_str("entry_id")
    result = V.q_enum("result", WEIGH_IN_RESULTS)
    limit, offset = V.pagination()
    rows = list(DB.weighins.values())
    if event_id is not None:
        rows = [r for r in rows if r.get("event_id") == event_id]
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if entry_id is not None:
        rows = [r for r in rows if r.get("entry_id") == entry_id]
    if result is not None:
        rows = [r for r in rows if r.get("result") == result]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.weigh_in(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


# --------------------------------------------------------------------------
# eligibility checks (the standalone certification-database check)
# --------------------------------------------------------------------------

@bp.post("/wrestlers/<wrestler_id>/eligibility-checks")
@endpoint("StateOffice", "TeamCoach", "WeighInOfficial")
def create_eligibility_check(wrestler_id):
    wrestler = lookups.wrestler(wrestler_id)
    body = V.get_body()
    event = lookups.event(V.req_id_ref(body, "event_id"))
    season = lookups.season_of_event(event)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    requested_class_lbs = V.weight_class(body, "requested_class_lbs", season)

    as_of_date = parse_date(event.get("event_date"))
    figures = calc.lowest_eligible_class_at_date(season, wrestler, as_of_date)
    lowest = figures["lowest_eligible_class_lbs"]

    # The wrestler's own derived field is refreshed; this is a derived-figure
    # refresh and deliberately does not bump the wrestler's version.
    wrestler["lowest_eligible_class_lbs"] = lowest

    status = wrestler.get("certification_status")
    plan = figures["plan"]
    if status == "DISQUALIFIED":
        outcome, blocking = "BLOCKED_DISQUALIFIED", "ERR_WRESTLER_DISQUALIFIED"
    elif status in ("UNCERTIFIED", "SUSPENDED"):
        outcome, blocking = "BLOCKED_NOT_CERTIFIED", "ERR_WRESTLER_NOT_CERTIFIED"
    elif cascade.has_escalated_flag(wrestler["id"]):
        outcome, blocking = "BLOCKED_ESCALATED_FLAG", "ERR_UNHEALTHY_WEIGHT_MANAGEMENT"
    elif lowest is None or int(requested_class_lbs) < int(lowest):
        blocking = "ERR_CLASS_BELOW_CERTIFIED_MINIMUM"
        if plan is not None and plan.get("status") == "BREACHED":
            outcome = "BLOCKED_PLAN_BREACHED"
        else:
            outcome = "BLOCKED_CLASS_BELOW_MINIMUM"
    elif serialize.team_posture(wrestler.get("team_id")) == "PROBATION":
        outcome, blocking = "BLOCKED_TEAM_PROBATION", "ERR_TEAM_ON_PROBATION"
    else:
        outcome, blocking = "CLEARED", None

    row = new_row(common=False)
    row.update({
        "wrestler_id": wrestler["id"],
        "event_id": event["id"],
        "requested_class_lbs": requested_class_lbs,
        "checked_at": clock_iso(),
        "as_of_date": fmt_date(as_of_date),
        "growth_allowance_lbs": figures["growth_allowance_lbs"],
        "schedule_allowable_weight_lbs": figures["schedule_allowable_weight_lbs"],
        "lowest_eligible_class_lbs": lowest,
        "outcome": outcome,
        "blocking_error_id": blocking,
    })
    DB.checks[row["id"]] = row
    return ok(serialize.eligibility_check(row), 201)


@bp.get("/eligibility-checks/<check_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_eligibility_check(check_id):
    return ok(serialize.eligibility_check(lookups.check(check_id)))


@bp.get("/eligibility-checks")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_eligibility_checks():
    wrestler_id = V.q_str("wrestler_id")
    event_id = V.q_str("event_id")
    outcome = V.q_enum("outcome", CHECK_OUTCOMES)
    limit, offset = V.pagination()
    rows = list(DB.checks.values())
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if event_id is not None:
        rows = [r for r in rows if r.get("event_id") == event_id]
    if outcome is not None:
        rows = [r for r in rows if r.get("outcome") == outcome]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.eligibility_check(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)
