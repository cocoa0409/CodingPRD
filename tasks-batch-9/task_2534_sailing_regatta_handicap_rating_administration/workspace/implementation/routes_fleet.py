"""Divisions, entries, mark boats and duty assignments."""
from flask import Blueprint

import calc
import services
import store
from errors import fail
from pipeline import Ctx, F, list_read, must, no_body, ok, ok_row, soft, validate
from datetime import timedelta

from util import parse_dt, rhu, whole_minutes

bp = Blueprint("fleet", __name__)

ALL_ROLES = ["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "JuryChair", "Competitor"]

DIVISION_PHASES = ("NOR_PUBLISHED", "SI_PUBLISHED")


# --------------------------------------------------------------------------
# Division
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/divisions")
def division_create():
    ctx = Ctx(["RegattaChair"])
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("code", "string", min_len=1, max_len=8, nonblank=True),
            F(
                "boat_type_filter",
                "enum",
                enum=("MONOHULL", "MULTIHULL", "KEELBOAT_SPORT", "ANY"),
            ),
            F("rating_band_low", "number"),
            F("rating_band_high", "number"),
            F("min_entries", "integer", required=False, default=3, ge=2, le=20),
        ],
    )
    if not float(data["rating_band_high"]) > float(data["rating_band_low"]):
        fail("ERR_INVALID_REQUEST", "rating_band_high must be strictly greater than rating_band_low")
    regatta = must("regattas", data["regatta_id"])
    if regatta["status"] not in DIVISION_PHASES:
        fail("ERR_REGATTA_PHASE_INVALID", "divisions are created from NOR_PUBLISHED onwards")
    code = data["code"].strip().lower()
    for other in store.find("divisions", regatta_id=regatta["id"]):
        if other["code"].strip().lower() == code:
            fail("ERR_DUPLICATE_RECORD", "code is already used in this regatta")
    row = store.insert(
        "divisions",
        {
            "regatta_id": regatta["id"],
            "code": data["code"],
            "boat_type_filter": data["boat_type_filter"],
            "rating_band_low": data["rating_band_low"],
            "rating_band_high": data["rating_band_high"],
            "min_entries": data["min_entries"],
            "status": "PROVISIONAL",
            "merged_into_division_id": None,
            "assigned_entry_count": 0,
            "accepted_entry_count": 0,
        },
    )
    return ok_row(row, 201)


def _bump_confirmed_count(regatta):
    """Set the derived count and advance Regatta.version by exactly 1."""
    count = len(
        [d for d in store.find("divisions", regatta_id=regatta["id"]) if d.get("status") == "CONFIRMED"]
    )
    regatta["confirmed_division_count"] = count
    store.touch(regatta)


@bp.post("/regatta-ops/divisions/<rid>/confirm")
def division_confirm(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    division = must("divisions", rid)
    if division["status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", "only a PROVISIONAL division may be confirmed")
    regatta = store.get("regattas", division["regatta_id"])
    if regatta["status"] not in DIVISION_PHASES:
        fail("ERR_REGATTA_PHASE_INVALID", "divisions are confirmed before racing opens")
    services.refresh_counts(division)
    if int(division["assigned_entry_count"]) < services.eff_floor(division, regatta):
        fail("ERR_FLEET_MINIMUM_NOT_MET", "the division is under its effective fleet floor")
    store.apply_changes(division, {"status": "CONFIRMED"})
    _bump_confirmed_count(regatta)
    services.clear_blocked_races(regatta)
    return ok_row(division)


@bp.post("/regatta-ops/divisions/<rid>/merge")
def division_merge(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    division = must("divisions", rid)
    if division["status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", "only a PROVISIONAL division may be merged away")
    regatta = store.get("regattas", division["regatta_id"])
    services.refresh_counts(division)
    if int(division["assigned_entry_count"]) >= services.eff_floor(division, regatta):
        fail("ERR_INVALID_STATE", "a division that meets its floor is confirmed, not merged")
    candidates = calc.merge_candidates(division)
    if not candidates:
        fail("ERR_NO_MERGE_TARGET", "no absorbing division is available")
    target = candidates[0]
    # hop 1
    store.apply_changes(
        division, {"status": "MERGED", "merged_into_division_id": target["id"]}
    )
    # hop 2: every entry of the merged division is re-pointed, whatever its status
    for entry in store.find("entries", division_id=division["id"]):
        store.apply_changes(entry, {"division_id": target["id"]})
    # hop 3
    services.refresh_counts(division)
    services.refresh_counts(target)
    # hop 4
    if target["status"] == "PROVISIONAL":
        if int(target["assigned_entry_count"]) >= services.eff_floor(target, regatta):
            store.apply_changes(target, {"status": "CONFIRMED"})
    _bump_confirmed_count(regatta)
    services.clear_blocked_races(regatta)
    return ok_row(division)


@bp.get("/regatta-ops/divisions/<rid>")
def division_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("divisions", rid))


@bp.get("/regatta-ops/divisions")
def division_list():
    Ctx(ALL_ROLES)
    return list_read(
        "divisions", ["regatta_id", "merged_into_division_id", "status", "boat_type_filter"]
    )


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------

CREW_POSITIONS = ("HELM", "TACTICIAN", "TRIM", "BOW", "FLOATER")


def _competitor_helms(ctx, entry_id):
    """Step 5 for the entry actions reserved to the helming Competitor."""
    if ctx.role != "Competitor":
        return
    entry = soft("entries", entry_id)
    if entry is not None and entry.get("helm_member_id") != ctx.user_id:
        fail("ERR_NOT_ACTING_PARTY", "a competitor acts only on the entries it helms")


@bp.post("/regatta-ops/entries")
def entry_create():
    ctx = Ctx(["RegattaChair", "Competitor"])
    if ctx.role == "Competitor":
        helm = ctx.raw_value("helm_member_id")
        if isinstance(helm, str) and helm != ctx.user_id:
            fail("ERR_NOT_ACTING_PARTY", "a competitor submits only entries it helms")
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("boat_id", "string"),
            F("certificate_id", "string"),
            F("helm_member_id", "string"),
            F("declared_crew_count", "integer", ge=1, le=20),
        ],
    )
    regatta = must("regattas", data["regatta_id"])
    boat = must("boats", data["boat_id"])
    cert = must("rating_certificates", data["certificate_id"])
    must("club_members", data["helm_member_id"])
    # step 12 then step 13
    if regatta["status"] == "DRAFT":
        fail("ERR_REGATTA_PHASE_INVALID", "entries open once the notice of race is published")
    if regatta["status"] in ("RACING", "SCORED"):
        fail("ERR_ENTRIES_CLOSED", "entry submission has closed")
    # step 23
    if cert["boat_id"] != boat["id"]:
        fail("ERR_CROSS_REGATTA_REFERENCE", "the certificate does not belong to the named boat")
    # step 26
    series_start = store.D(regatta, "series_start_utc")
    if not (store.D(cert, "valid_from") <= series_start <= store.D(cert, "valid_until")):
        fail("ERR_CERTIFICATE_EXPIRED", "the certificate does not cover series_start_utc")
    row = store.insert(
        "entries",
        {
            "regatta_id": regatta["id"],
            "boat_id": boat["id"],
            "certificate_id": cert["id"],
            "helm_member_id": data["helm_member_id"],
            "division_id": None,
            "declared_crew_count": data["declared_crew_count"],
            "crew_manifest": [],
            "registered_crew_count": 0,
            "crew_weight_kg": 0,
            "registration_status": "SUBMITTED",
            "inspection_status": "NOT_INSPECTED",
            "equipment_deficiency_code": None,
            "series_points_gross": 0,
            "series_points_net": 0,
            "discarded_race_numbers": [],
            "series_rank": None,
        },
    )
    return ok_row(row, 201)


@bp.post("/regatta-ops/entries/<rid>/crew")
def entry_crew_add(rid):
    ctx = Ctx(["RegattaChair", "Competitor"])
    _competitor_helms(ctx, rid)
    data = validate(
        ctx,
        [
            F("member_id", "string"),
            F("position", "enum", enum=CREW_POSITIONS),
            F("weight_kg", "number"),
        ],
    )
    entry = must("entries", rid)
    member = must("club_members", data["member_id"])
    regatta = store.get("regattas", entry["regatta_id"])
    manifest = list(entry.get("crew_manifest") or [])
    candidate = {
        "member_id": member["id"],
        "position": data["position"],
        "weight_kg": data["weight_kg"],
    }
    # step 18 runs over the whole manifest including the new element
    probe = dict(entry)
    probe["crew_manifest"] = manifest + [candidate]
    if not services.crew_safety_ok(probe, regatta):
        fail("ERR_CREW_SAFETY_COURSE_EXPIRED", "a crew member has no valid sea-survival course")
    # step 32
    for element in manifest:
        if element.get("member_id") == member["id"]:
            fail("ERR_DUPLICATE_RECORD", "the member already appears on this manifest")
    if data["position"] == "HELM":
        for element in manifest:
            if element.get("position") == "HELM":
                fail("ERR_DUPLICATE_RECORD", "the manifest already carries a HELM")
    manifest.append(candidate)
    entry["crew_manifest"] = manifest
    entry["registered_crew_count"] = len(manifest)
    entry["crew_weight_kg"] = services.crew_weight(entry)
    store.touch(entry)
    return ok_row(entry)


@bp.delete("/regatta-ops/entries/<rid>/crew/<member_id>")
def entry_crew_remove(rid, member_id):
    ctx = Ctx(["Competitor"])
    _competitor_helms(ctx, rid)
    no_body(ctx)
    # step 8: the entry is resolved first, and only then the manifest element
    entry = must("entries", rid)
    manifest = list(entry.get("crew_manifest") or [])
    keep = [e for e in manifest if e.get("member_id") != member_id]
    if len(keep) == len(manifest):
        fail("ERR_RESOURCE_NOT_FOUND", "the member is not on this manifest")
    entry["crew_manifest"] = keep
    entry["registered_crew_count"] = len(keep)
    entry["crew_weight_kg"] = services.crew_weight(entry)
    store.touch(entry)
    return ok_row(entry)


@bp.post("/regatta-ops/entries/<rid>/assign-division")
def entry_assign_division(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    entry = must("entries", rid)
    cert = store.get("rating_certificates", entry["certificate_id"])
    boat = store.get("boats", entry["boat_id"])
    # step 25
    if cert is None or cert["status"] != "ISSUED":
        fail("ERR_CERTIFICATE_NOT_ISSUED", "the pinned certificate is not ISSUED")
    # step 29
    eligible = calc.eligible_divisions(entry, cert, boat)
    if not eligible:
        fail("ERR_NO_ELIGIBLE_DIVISION", "no division of the regatta accepts this entry")
    previous = store.get("divisions", entry.get("division_id"))
    store.apply_changes(entry, {"division_id": eligible[0]["id"]})
    if previous is not None and previous["id"] != eligible[0]["id"]:
        services.refresh_counts(previous)
    services.refresh_counts(eligible[0])
    return ok_row(entry)


@bp.post("/regatta-ops/entries/<rid>/inspect")
def entry_inspect(rid):
    ctx = Ctx(["RaceOfficer"])
    data = validate(
        ctx,
        [
            F("outcome", "enum", enum=("PASS", "FAIL")),
            F("equipment_deficiency_code", "string", required=False),
        ],
    )
    if data["outcome"] == "FAIL" and data["equipment_deficiency_code"] is None:
        fail("ERR_INVALID_REQUEST", "equipment_deficiency_code is required for a FAIL outcome")
    entry = must("entries", rid)
    if entry["registration_status"] not in ("SUBMITTED", "ACCEPTED", "RATING_INVALID"):
        fail("ERR_INVALID_STATE", "a withdrawn entry is not inspected")
    current = entry["inspection_status"]
    if data["outcome"] == "PASS":
        if current == "PASSED":
            fail("ERR_INVALID_STATE", "the entry has already passed inspection")
        if current == "NOT_INSPECTED" and int(entry["registered_crew_count"]) < 1:
            fail("ERR_INVALID_STATE", "a first pass needs at least one registered crew member")
        store.apply_changes(
            entry, {"inspection_status": "PASSED", "equipment_deficiency_code": None}
        )
    else:
        if current == "FAILED":
            fail("ERR_INVALID_STATE", "the entry has already failed inspection")
        store.apply_changes(
            entry,
            {
                "inspection_status": "FAILED",
                "equipment_deficiency_code": data["equipment_deficiency_code"],
            },
        )
    return ok_row(entry)


@bp.post("/regatta-ops/entries/<rid>/accept")
def entry_accept(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    entry = must("entries", rid)
    regatta = store.get("regattas", entry["regatta_id"])
    division = store.get("divisions", entry.get("division_id"))
    # step 11
    if entry["registration_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED entry may be accepted")
    if division is None or division["status"] == "MERGED":
        fail("ERR_INVALID_STATE", "the entry has no division able to hold it")
    # step 18
    if not services.crew_safety_ok(entry, regatta):
        fail("ERR_CREW_SAFETY_COURSE_EXPIRED", "a crew member has no valid sea-survival course")
    # step 19
    if entry["inspection_status"] != "PASSED":
        fail("ERR_EQUIPMENT_INSPECTION_NOT_PASSED", "the entry has not passed equipment inspection")
    cert = store.get("rating_certificates", entry["certificate_id"])
    # step 25 then step 26
    if cert is None or cert["status"] != "ISSUED":
        fail("ERR_CERTIFICATE_NOT_ISSUED", "the pinned certificate is not ISSUED")
    series_start = store.D(regatta, "series_start_utc")
    if not (store.D(cert, "valid_from") <= series_start <= store.D(cert, "valid_until")):
        fail("ERR_CERTIFICATE_EXPIRED", "the certificate does not cover series_start_utc")
    # step 27
    manifest = entry.get("crew_manifest") or []
    helms = [e for e in manifest if e.get("position") == "HELM"]
    if int(entry["registered_crew_count"]) != int(entry["declared_crew_count"]):
        fail("ERR_CREW_MANIFEST_INCOMPLETE", "registered_crew_count does not match the declaration")
    if len(helms) != 1 or helms[0].get("member_id") != entry["helm_member_id"]:
        fail("ERR_CREW_MANIFEST_INCOMPLETE", "the manifest carries no matching HELM element")
    # step 28
    boat = store.get("boats", entry["boat_id"])
    key = float(cert["band_key_spm"])
    if not (float(division["rating_band_low"]) <= key < float(division["rating_band_high"])):
        fail("ERR_DIVISION_BAND_MISMATCH", "the pinned band key is outside the division band")
    if division["boat_type_filter"] not in (boat["boat_type"], "ANY"):
        fail("ERR_DIVISION_BAND_MISMATCH", "the hull type no longer matches the division filter")
    store.apply_changes(entry, {"registration_status": "ACCEPTED"})
    services.refresh_counts(division)
    return ok_row(entry)


@bp.post("/regatta-ops/entries/<rid>/withdraw")
def entry_withdraw(rid):
    ctx = Ctx(["RegattaChair", "Competitor"])
    _competitor_helms(ctx, rid)
    no_body(ctx)
    entry = must("entries", rid)
    status = entry["registration_status"]
    if status not in ("SUBMITTED", "ACCEPTED"):
        fail("ERR_INVALID_STATE", "only a SUBMITTED or ACCEPTED entry may be withdrawn")
    if status == "ACCEPTED":
        for race in store.find("races", regatta_id=entry["regatta_id"]):
            if race.get("scoring_status") != "FINAL":
                continue
            for result in store.find("race_results", race_id=race["id"], entry_id=entry["id"]):
                if not result.get("voided"):
                    fail("ERR_INVALID_STATE", "the entry already holds a scored result")
    store.apply_changes(entry, {"registration_status": "WITHDRAWN"})
    division = store.get("divisions", entry.get("division_id"))
    if division is not None:
        services.refresh_division(division)
    return ok_row(entry)


@bp.get("/regatta-ops/entries/<rid>")
def entry_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("entries", rid))


@bp.get("/regatta-ops/entries")
def entry_list():
    Ctx(ALL_ROLES)
    return list_read(
        "entries",
        [
            "regatta_id",
            "boat_id",
            "certificate_id",
            "helm_member_id",
            "division_id",
            "registration_status",
            "inspection_status",
        ],
    )


@bp.get("/regatta-ops/entries/<rid>/series-standing")
def entry_series_standing(rid):
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair", "Competitor"])
    entry = must("entries", rid)
    regatta = store.get("regattas", entry["regatta_id"])
    division = store.get("divisions", entry.get("division_id"))
    row = None
    if division is not None and entry["registration_status"] == "ACCEPTED":
        for candidate in calc.division_standings(regatta, division):
            if candidate["entry"]["id"] == entry["id"]:
                row = candidate
                break
    if row is None:
        row = calc.entry_standing(regatta, entry)
        row["rank"] = None
        row["trace"] = "NO_COUNTED_RACES" if row["completed"] == 0 else "NOT_RANKED"
    return ok(
        {
            "entry_id": entry["id"],
            "division_id": entry.get("division_id"),
            "gross_points": row["gross"],
            "net_points": row["net"],
            "discarded_race_numbers": row["discarded_race_numbers"],
            "races_counted": row["completed"],
            "rank": row["rank"],
            "tie_break_trace": row["trace"],
        }
    )


# --------------------------------------------------------------------------
# MarkBoat
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/mark-boats")
def mark_boat_create():
    ctx = Ctx(["RegattaChair"])
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("call_sign", "string", nonblank=True),
            F("crew_capacity", "integer", ge=1, le=12),
            F("concurrent_assignment_limit", "integer", required=False, default=2, ge=1, le=6),
            F("turnaround_buffer_minutes", "integer", required=False, default=20, ge=0, le=120),
        ],
    )
    regatta = must("regattas", data["regatta_id"])
    call_sign = data["call_sign"].strip().lower()
    for other in store.find("mark_boats", regatta_id=regatta["id"]):
        if other["call_sign"].strip().lower() == call_sign:
            fail("ERR_DUPLICATE_RECORD", "call_sign is already chartered for this regatta")
    row = store.insert(
        "mark_boats",
        {
            "regatta_id": regatta["id"],
            "call_sign": data["call_sign"],
            "crew_capacity": data["crew_capacity"],
            "concurrent_assignment_limit": data["concurrent_assignment_limit"],
            "turnaround_buffer_minutes": data["turnaround_buffer_minutes"],
            "committed_minutes": 0,
        },
    )
    return ok_row(row, 201)


@bp.get("/regatta-ops/mark-boats/<rid>")
def mark_boat_read(rid):
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer"])
    return ok_row(must("mark_boats", rid))


@bp.get("/regatta-ops/mark-boats")
def mark_boat_list():
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer"])
    return list_read("mark_boats", ["regatta_id"])


# --------------------------------------------------------------------------
# DutyAssignment
# --------------------------------------------------------------------------

POSITIONS = ("PRO", "TIMEKEEPER", "SIGNALS", "MARK_BOAT_DRIVER", "SAFETY_BOAT")
BOAT_POSITIONS = ("MARK_BOAT_DRIVER", "SAFETY_BOAT")
LIVE_DUTY = ("PROPOSED", "CONFIRMED")


@bp.post("/regatta-ops/duty-assignments")
def duty_create():
    ctx = Ctx(["RegattaChair"])
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("race_id", "string", required=False),
            F("member_id", "string"),
            F("mark_boat_id", "string", required=False),
            F("position", "enum", enum=POSITIONS),
            F("window_start_utc", "datetime"),
            F("window_end_utc", "datetime"),
        ],
    )
    start = parse_dt(data["window_start_utc"])
    end = parse_dt(data["window_end_utc"])
    if not end > start:
        fail("ERR_INVALID_REQUEST", "window_end_utc must be strictly after window_start_utc")
    regatta = must("regattas", data["regatta_id"])
    race = None
    if data["race_id"] is not None:
        race = must("races", data["race_id"])
    member = must("club_members", data["member_id"])
    mark_boat = None
    if data["mark_boat_id"] is not None:
        mark_boat = must("mark_boats", data["mark_boat_id"])
    # step 22
    if data["position"] in BOAT_POSITIONS:
        if mark_boat is None:
            fail("ERR_MARK_BOAT_ASSIGNMENT_INVALID", "mark_boat_id is required for this position")
    elif mark_boat is not None:
        fail("ERR_MARK_BOAT_ASSIGNMENT_INVALID", "mark_boat_id is forbidden for this position")
    if mark_boat is not None and mark_boat["regatta_id"] != regatta["id"]:
        fail("ERR_MARK_BOAT_ASSIGNMENT_INVALID", "the mark boat belongs to another regatta")
    # step 23
    if race is not None and race["regatta_id"] != regatta["id"]:
        fail("ERR_CROSS_REGATTA_REFERENCE", "the race belongs to another regatta")
    # step 34: member windows are half-open, so touching windows do not collide
    for other in store.find("duty_assignments", member_id=member["id"]):
        if other.get("status") not in LIVE_DUTY:
            continue
        if start < store.D(other, "window_end_utc") and store.D(other, "window_start_utc") < end:
            fail("ERR_MEMBER_DUTY_OVERLAP", "the volunteer already holds an overlapping window")
    # step 35: existing mark-boat windows are widened at both ends before the test
    if mark_boat is not None:
        buffer_minutes = int(mark_boat["turnaround_buffer_minutes"])
        delta = timedelta(minutes=buffer_minutes)
        overlapping = 0
        for other in store.find("duty_assignments", mark_boat_id=mark_boat["id"]):
            if other.get("status") not in LIVE_DUTY:
                continue
            wide_start = store.D(other, "window_start_utc") - delta
            wide_end = store.D(other, "window_end_utc") + delta
            if start < wide_end and wide_start < end:
                overlapping += 1
        if overlapping >= int(mark_boat["concurrent_assignment_limit"]):
            fail("ERR_MARK_BOAT_OVERBOOKED", "the mark boat is at its concurrent-assignment limit")
    minutes = whole_minutes(start, end)
    row = store.insert(
        "duty_assignments",
        {
            "regatta_id": regatta["id"],
            "race_id": None if race is None else race["id"],
            "member_id": member["id"],
            "mark_boat_id": None if mark_boat is None else mark_boat["id"],
            "position": data["position"],
            "window_start_utc": data["window_start_utc"],
            "window_end_utc": data["window_end_utc"],
            "status": "PROPOSED",
            "duty_minutes": minutes,
            "release_reason_code": None,
        },
    )
    # a PROPOSED row already counts in both ledgers
    member["assigned_duty_minutes"] = calc.member_duty_minutes(member["id"])
    store.touch(member)
    if mark_boat is not None:
        services.refresh_mark_boat_ledger(mark_boat)
    return ok_row(row, 201)


@bp.post("/regatta-ops/duty-assignments/<rid>/confirm")
def duty_confirm(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    assignment = must("duty_assignments", rid)
    if assignment["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED duty may be confirmed")
    # step 21
    if assignment["position"] == "PRO":
        if services.member_on_seated_panel(assignment["regatta_id"], assignment["member_id"]):
            fail("ERR_JURY_CONFLICT_OF_INTEREST", "the volunteer holds a seat on a seated jury panel")
    store.apply_changes(assignment, {"status": "CONFIRMED"})
    regatta = store.get("regattas", assignment["regatta_id"])
    services.refresh_pending_staffing(regatta)
    return ok_row(assignment)


@bp.post("/regatta-ops/duty-assignments/<rid>/release")
def duty_release(rid):
    ctx = Ctx(["RegattaChair"])
    data = validate(ctx, [F("release_reason_code", "string", nonblank=True)])
    assignment = must("duty_assignments", rid)
    if assignment["status"] not in LIVE_DUTY:
        fail("ERR_INVALID_STATE", "only a PROPOSED or CONFIRMED duty may be released")
    if assignment["status"] == "CONFIRMED":
        for race in store.find("races", regatta_id=assignment["regatta_id"]):
            if race.get("start_status") != "SEQUENCE_STARTED":
                continue
            if assignment.get("race_id") not in (None, race["id"]):
                continue
            window_start, window_end = calc.coverage_window(race)
            if calc.covers(assignment, window_start, window_end):
                fail("ERR_INVALID_STATE", "the race is between the warning signal and the start")
    store.apply_changes(
        assignment, {"status": "RELEASED", "release_reason_code": data["release_reason_code"]}
    )
    member = store.get("club_members", assignment["member_id"])
    if member is not None:
        member["assigned_duty_minutes"] = calc.member_duty_minutes(member["id"])
        store.touch(member)
    mark_boat = store.get("mark_boats", assignment.get("mark_boat_id"))
    if mark_boat is not None:
        services.refresh_mark_boat_ledger(mark_boat)
    regatta = store.get("regattas", assignment["regatta_id"])
    services.refresh_pending_staffing(regatta)
    return ok_row(assignment)


@bp.get("/regatta-ops/duty-assignments/<rid>")
def duty_read(rid):
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair"])
    return ok_row(must("duty_assignments", rid))


@bp.get("/regatta-ops/duty-assignments")
def duty_list():
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair"])
    return list_read(
        "duty_assignments",
        ["regatta_id", "race_id", "member_id", "mark_boat_id", "position", "status"],
    )
