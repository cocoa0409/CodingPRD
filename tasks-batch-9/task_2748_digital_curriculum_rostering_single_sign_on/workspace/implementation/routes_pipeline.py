"""The rostering pipeline: extract, transform, triage, publish -- plus triage verbs."""
from flask import Blueprint

import auth
import calc
import cascade
import envelope
import serial
import shape
import store
from errors import ApiError
from routes_reads import fetch

bp = Blueprint("pipeline", __name__)

LIVE = ("PENDING_ADD", "ACTIVE", "PENDING_DROP")


def _open_items(run, severity=None, category=None):
    rows = []
    for item in store.sorted_records(store.error_queue_items):
        if item.get("sync_run_id") != run["id"] or item.get("status") != "OPEN":
            continue
        if severity is not None and item.get("severity") != severity:
            continue
        if category is not None and item.get("category") != category:
            continue
        rows.append(item)
    return rows


def _free_allocation_capacity(vendor_id):
    free = 0
    for allocation in store.building_allocations.values():
        if allocation.get("vendor_app_id") != vendor_id:
            continue
        spare = (allocation.get("allocated_seats") or 0) - (allocation.get("consumed_seats") or 0)
        if spare > 0:
            free += spare
    return free


# ----------------------------------------------------------------- extract
@bp.post("/rostering/sync-runs")
def open_sync_run():
    actor = auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    vendor_app_id = shape.req_id(body, "vendor_app_id")
    run_type = shape.req_enum(body, "run_type", shape.RUN_TYPES)
    vendor = fetch(store.vendor_apps, vendor_app_id, "ERR_VENDOR_APP_NOT_FOUND")
    if vendor.get("status") != "ACTIVE":
        raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE", "The license is not ACTIVE.")
    term = store.terms.get(vendor.get("term_id"))
    if run_type in ("FULL", "DELTA"):
        if term is None or term.get("state") != "ACTIVE":
            raise ApiError("ERR_TERM_NOT_ACTIVE", "The license's term is not ACTIVE.")
    elif not calc.archived_read_permitted(term):
        raise ApiError("ERR_ARCHIVE_WINDOW_CLOSED",
                       "The archived-access window for this term is shut.")

    # pre-emption: any earlier open run of this license is inert from now on.
    now = store.fmt_instant(store.clock_now())
    for earlier in cascade.in_flight_runs(vendor_app_id):
        earlier["state"] = "SUPERSEDED"
        store.touch(earlier)
        for item in _open_items(earlier):
            item["status"] = "DISMISSED"
            item["resolution_note"] = "run superseded"
            item["resolved_at"] = now
            store.touch(item)
        cascade.recompute_run_counters(earlier)

    scope = calc.resolve_scope(vendor, run_type)
    record = {
        "vendor_app_id": vendor_app_id,
        "run_type": run_type,
        "state": "EXTRACTED",
        "initiated_by_user_id": actor.user_id,
        "published_by_user_id": None,
        "extracted_section_count": len(scope.sections),
        "extracted_enrollment_count": len(scope.enrollments),
        "transformed_record_count": 0,
        "blocking_error_count": 0,
        "advisory_error_count": 0,
        "projected_seat_delta": None,
        "projected_charge_cents": None,
        "published_seat_delta": None,
        "published_charge_cents": None,
        "transform_count": 0,
        "extracted_at": now,
        "transformed_at": None,
        "published_at": None,
    }
    store.stamp_new(record)
    store.sync_runs[record["id"]] = record
    return envelope.created(serial.sync_run(record))


# --------------------------------------------------------------- transform
@bp.post("/rostering/sync-runs/<sync_run_id>/transform")
def transform_sync_run(sync_run_id):
    auth.require(auth.ROSTER_OPERATOR)
    run = fetch(store.sync_runs, sync_run_id, "ERR_SYNC_RUN_NOT_FOUND")
    shape.body()
    if run.get("state") == "SUPERSEDED":
        raise ApiError("ERR_SYNC_RUN_SUPERSEDED", "The run has been superseded.")
    if run.get("state") not in ("EXTRACTED", "HELD"):
        raise ApiError("ERR_SYNC_RUN_STATE_INVALID",
                       "Transform is permitted only from EXTRACTED or HELD.")
    if run.get("state") == "HELD":
        if _open_items(run, "BLOCKING", "UNMATCHED_TEACHER"):
            raise ApiError("ERR_BLOCKING_ERRORS_UNRESOLVED",
                           "The unmatched-teacher triage that held this run is open.")

    vendor = store.vendor_apps.get(run.get("vendor_app_id"))
    term = store.terms.get(vendor.get("term_id"))
    scope = calc.resolve_scope(vendor, run.get("run_type"))
    skip = vendor.get("unmatched_teacher_policy") == "SKIP_SECTION"

    # triage pass 1: sections without a usable teacher of record
    for section in scope.sections:
        teacher_id = section.get("primary_teacher_id")
        teacher = store.teachers.get(teacher_id) if teacher_id else None
        if teacher_id is None or teacher is None or teacher.get("employment_status") == "SEPARATED":
            cascade.raise_item(run, "UNMATCHED_TEACHER",
                               "ADVISORY" if skip else "BLOCKING",
                               section.get("sis_section_id"),
                               section_id=section["id"])

    # triage pass 2: duplicate students, one item per duplicate key
    groups = {}
    order = []
    for student in scope.students:
        key = "%s|%s" % ((student.get("last_name") or "").lower(),
                         student.get("date_of_birth"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(student)
    for key in order:
        members = groups[key]
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda s: (s["created_at"], s["_seq"]))
        cascade.raise_item(run, "DUPLICATE_STUDENT", "BLOCKING", key,
                           student_id=members[0]["id"],
                           duplicate_id=members[1]["id"])

    # triage pass 3: students the license's band mapping cannot place
    for student in scope.students:
        if calc.band_for_grade(student.get("grade_level")) is None:
            cascade.raise_item(run, "MISSING_GRADE_BAND", "ADVISORY",
                               student.get("sis_student_id"),
                               student_id=student["id"])

    # triage pass 4: not enough seats left to satisfy the projection
    seat_delta, charge = calc.project_seats_and_charge(vendor, term, scope, "provisional")
    capacity = (vendor.get("unallocated_seats") or 0) + _free_allocation_capacity(vendor["id"])
    if seat_delta > capacity:
        cascade.raise_item(run, "SEAT_SHORTFALL",
                           "ADVISORY" if vendor.get("overage_policy") == "POOL_FALLBACK"
                           else "BLOCKING",
                           vendor.get("vendor_code"))

    held = bool(_open_items(run, "BLOCKING", "UNMATCHED_TEACHER"))
    run["transform_count"] = (run.get("transform_count") or 0) + 1
    run["transformed_at"] = store.fmt_instant(store.clock_now())
    run["transformed_record_count"] = calc.transformed_record_count(scope)
    if held:
        run["state"] = "HELD"
        run["projected_seat_delta"] = None
        run["projected_charge_cents"] = None
    else:
        run["state"] = "TRANSFORMED"
        run["projected_seat_delta"] = seat_delta
        run["projected_charge_cents"] = charge
    store.touch(run)
    cascade.recompute_run_counters(run)

    vendor["sync_health"] = "BLOCKED" if _open_items(run, "BLOCKING") else "OK"
    store.touch(vendor)
    return envelope.ok(serial.sync_run(run))


# ----------------------------------------------------------------- publish
@bp.post("/rostering/sync-runs/<sync_run_id>/publish")
def publish_sync_run(sync_run_id):
    actor = auth.require(auth.DATA_GOVERNANCE_OFFICER)
    run = fetch(store.sync_runs, sync_run_id, "ERR_SYNC_RUN_NOT_FOUND")
    auth.segregation(actor, run.get("initiated_by_user_id"))
    shape.body()
    if run.get("state") == "SUPERSEDED":
        raise ApiError("ERR_SYNC_RUN_SUPERSEDED", "The run has been superseded.")
    if run.get("state") != "TRANSFORMED":
        raise ApiError("ERR_SYNC_RUN_STATE_INVALID",
                       "Publish is permitted only from TRANSFORMED.")
    if _open_items(run, "BLOCKING"):
        raise ApiError("ERR_BLOCKING_ERRORS_UNRESOLVED",
                       "Blocking triage items are still open on this run.")

    vendor = store.vendor_apps.get(run.get("vendor_app_id"))
    term = store.terms.get(vendor.get("term_id"))
    today = store.clock_date()
    now = store.fmt_instant(store.clock_now())
    scope = calc.resolve_scope(vendor, run.get("run_type"))

    # (1) mid-year adds land, dated the later of the request and the publish
    for enrollment in scope.enrollments:
        if enrollment.get("roster_status") != "PENDING_ADD":
            continue
        requested = calc.as_date(enrollment.get("requested_effective_date"))
        if requested > today:
            continue
        enrollment["roster_status"] = "ACTIVE"
        # the later of the two, and the request date is known to be in the past
        enrollment["effective_date"] = store.fmt_date(today)
        store.touch(enrollment)
        cascade.recompute_section_count(store.sections.get(enrollment.get("section_id")))
        cascade.recompute_student_count(store.students.get(enrollment.get("student_id")))

    # (2) mid-year drops land, each running the conditional seat-release cascade
    for enrollment in scope.enrollments:
        if enrollment.get("roster_status") != "PENDING_DROP":
            continue
        drop_date = calc.as_date(enrollment.get("drop_effective_date"))
        if drop_date is None or drop_date > today:
            continue
        enrollment["roster_status"] = "DROPPED"
        store.touch(enrollment)
        student = store.students.get(enrollment.get("student_id"))
        cascade.recompute_section_count(store.sections.get(enrollment.get("section_id")))
        cascade.recompute_student_count(student)
        cascade.release_student_seats(student, drop_date)

    # (3) the final charge variant, evaluated after both cascades
    final_scope = calc.resolve_scope(vendor, run.get("run_type"))
    seat_delta, charge = calc.project_seats_and_charge(vendor, term, final_scope, "final")
    run["published_seat_delta"] = seat_delta
    run["published_charge_cents"] = charge

    # (4) whatever advisory noise is left is dismissed by the publishing officer
    for item in _open_items(run):
        item["status"] = "DISMISSED"
        item["resolved_by_user_id"] = actor.user_id
        item["resolved_at"] = now
        store.touch(item)

    # (5) the run closes and the license is re-scored
    run["state"] = "PUBLISHED"
    run["published_at"] = now
    run["published_by_user_id"] = actor.user_id
    store.touch(run)
    cascade.recompute_run_counters(run)
    cascade.recompute_vendor(vendor, bump_version=False)
    vendor["sync_health"] = "OK"
    store.touch(vendor)
    return envelope.ok(serial.sync_run(run))


# ------------------------------------------------------------------ triage
@bp.post("/rostering/error-queue-items/<error_queue_item_id>/resolve-match")
def resolve_match(error_queue_item_id):
    actor = auth.require(auth.DATA_GOVERNANCE_OFFICER)
    item = fetch(store.error_queue_items, error_queue_item_id,
                 "ERR_ERROR_QUEUE_ITEM_NOT_FOUND")
    body = shape.body()
    replacement_id = shape.req_id(body, "replacement_teacher_id")
    note = shape.opt_str(body, "resolution_note", None, 1, 500)
    replacement = fetch(store.teachers, replacement_id, "ERR_TEACHER_NOT_FOUND")
    run = store.sync_runs.get(item.get("sync_run_id"))

    if replacement.get("employment_status") != "ACTIVE":
        raise ApiError("ERR_TEACHER_SEPARATED", "The replacement teacher is SEPARATED.")
    if run is not None and run.get("state") == "SUPERSEDED":
        raise ApiError("ERR_SYNC_RUN_SUPERSEDED", "The run has been superseded.")
    if item.get("status") != "OPEN" or item.get("category") != "UNMATCHED_TEACHER":
        raise ApiError("ERR_ERROR_QUEUE_ITEM_NOT_OPEN",
                       "The item is not an OPEN unmatched-teacher item.")
    section = store.sections.get(item.get("subject_section_id"))
    if section is None:
        raise ApiError("ERR_ERROR_QUEUE_ITEM_NOT_OPEN",
                       "The item names no section to repair.")
    if calc.teacher_period_conflict(replacement_id, section.get("term_id"),
                                    section.get("period_index"),
                                    section.get("meeting_days"),
                                    exclude_section_id=section["id"]):
        raise ApiError("ERR_TEACHER_PERIOD_CONFLICT",
                       "The replacement already meets within one period of this one.")
    if replacement.get("school_id") != section.get("school_id"):
        raise ApiError("ERR_SCHOOL_MISMATCH",
                       "The replacement teaches in a different building.")

    section["primary_teacher_id"] = replacement_id
    section["roster_health"] = "OK"
    store.touch(section)
    item["status"] = "RESOLVED_MATCHED"
    item["resolved_by_user_id"] = actor.user_id
    item["resolved_at"] = store.fmt_instant(store.clock_now())
    if note is not None:
        item["resolution_note"] = note
    store.touch(item)
    if run is not None:
        cascade.recompute_run_counters(run)
    return envelope.ok(serial.error_queue_item(item))


@bp.post("/rostering/error-queue-items/<error_queue_item_id>/merge-duplicate")
def merge_duplicate(error_queue_item_id):
    actor = auth.require(auth.DATA_GOVERNANCE_OFFICER)
    item = fetch(store.error_queue_items, error_queue_item_id,
                 "ERR_ERROR_QUEUE_ITEM_NOT_FOUND")
    body = shape.body()
    surviving_id = shape.req_id(body, "surviving_student_id")
    note = shape.opt_str(body, "resolution_note", None, 1, 500)
    survivor = fetch(store.students, surviving_id, "ERR_STUDENT_NOT_FOUND")
    run = store.sync_runs.get(item.get("sync_run_id"))

    if run is not None and run.get("state") == "SUPERSEDED":
        raise ApiError("ERR_SYNC_RUN_SUPERSEDED", "The run has been superseded.")
    if item.get("status") != "OPEN" or item.get("category") != "DUPLICATE_STUDENT":
        raise ApiError("ERR_ERROR_QUEUE_ITEM_NOT_OPEN",
                       "The item is not an OPEN duplicate-student item.")

    first_id = item.get("subject_student_id")
    second_id = item.get("duplicate_candidate_student_id")
    first = store.students.get(first_id)
    second = store.students.get(second_id)
    if (surviving_id not in (first_id, second_id) or first is None or second is None
            or first_id == second_id
            or first.get("school_id") != second.get("school_id")):
        raise ApiError("ERR_MERGE_SUBJECT_MISMATCH",
                       "The survivor must be one of two distinct candidates of one building.")
    loser = second if surviving_id == first_id else first
    if survivor.get("enrollment_state") != "ENROLLED":
        raise ApiError("ERR_STUDENT_NOT_ENROLLED", "The survivor is not ENROLLED.")
    if loser.get("enrollment_state") != "ENROLLED":
        raise ApiError("ERR_STUDENT_NOT_ENROLLED", "The loser is not ENROLLED.")

    today = store.clock_date()
    sections_touched = []
    for enrollment in store.sorted_records(store.enrollments):
        if enrollment.get("student_id") != loser["id"]:
            continue
        if enrollment.get("roster_status") not in LIVE:
            continue
        section_id = enrollment.get("section_id")
        clash = False
        for other in store.enrollments.values():
            if (other.get("student_id") == survivor["id"]
                    and other.get("section_id") == section_id
                    and other.get("roster_status") != "DROPPED"):
                clash = True
                break
        if clash:
            enrollment["roster_status"] = "DROPPED"
            enrollment["drop_effective_date"] = store.fmt_date(today)
        else:
            enrollment["student_id"] = survivor["id"]
        store.touch(enrollment)
        section = store.sections.get(section_id)
        if section is not None and section not in sections_touched:
            sections_touched.append(section)
    for section in sections_touched:
        cascade.recompute_section_count(section)

    loser["enrollment_state"] = "MERGED_DUPLICATE"
    loser["duplicate_of_student_id"] = survivor["id"]
    loser["active_enrollment_count"] = sum(
        1 for e in store.enrollments.values()
        if e.get("student_id") == loser["id"] and e.get("roster_status") in LIVE)
    store.touch(loser)
    cascade.recompute_student_count(survivor)

    for account in cascade.student_accounts(loser):
        if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
            continue
        cascade.release_seat(account, today, identity="DEPROVISIONED",
                             deprovision_date=today)
    cascade.recompute_school_headcount(store.schools.get(loser.get("school_id")))

    item["status"] = "RESOLVED_MERGED"
    item["resolved_by_user_id"] = actor.user_id
    item["resolved_at"] = store.fmt_instant(store.clock_now())
    if note is not None:
        item["resolution_note"] = note
    store.touch(item)
    if run is not None:
        cascade.recompute_run_counters(run)
    return envelope.ok(serial.error_queue_item(item))
