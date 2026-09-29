"""Derived-state reconciliation: cumulative-file counters, packet reopen cascade,
district counters, disclosure log appends and retention recomputation.

Nothing here is ever half-applied: every helper leaves the whole graph consistent
before the request returns (PRD 1, 2.11, 3.3, 3.9).
"""

from common import STORE, base_row, clock_now, iso, touch
from calc import (completeness_pct, is_eligible_student, retention_anchors)
from domain import (COMPONENT_TYPE_ORDER, DIRECTORY_CATEGORY_ORDER, OPEN_REQUEST_STATUSES,
                    components_of_file, file_of_student, incidents_of_student,
                    schedule_of_file, state_rule_for_student)


# --------------------------------------------------------------------------- #
# Student eligibility (pure function of the clock; not itself a mutation)
# --------------------------------------------------------------------------- #
def refresh_eligibility(student_row):
    student_row["is_eligible_student"] = is_eligible_student(student_row)
    return student_row


def refresh_all_eligibility():
    for row in STORE.students.values():
        refresh_eligibility(row)


# --------------------------------------------------------------------------- #
# District counter
# --------------------------------------------------------------------------- #
def recompute_district_open_count(district_id):
    district = STORE.districts.get(district_id)
    if district is None:
        return
    count = 0
    for row in STORE.records_requests.values():
        if row["responding_district_id"] == district_id and row["status"] in OPEN_REQUEST_STATUSES:
            count += 1
    if district["open_request_count"] != count:
        district["open_request_count"] = count
        touch(district)


# --------------------------------------------------------------------------- #
# Records-request packet cascades
# --------------------------------------------------------------------------- #
def _void_packet(request_row):
    request_row["status"] = "ASSEMBLING"
    request_row["reopen_count"] = int(request_row["reopen_count"]) + 1
    request_row["packet_status"] = "VOID"
    request_row["packet_page_count"] = None
    request_row["included_incident_count"] = None
    request_row["withheld_incident_count"] = None
    request_row["receiving_state_inclusion_count"] = None
    touch(request_row)


def reopen_ready_requests(student_id):
    """Every READY_FOR_RELEASE request of the student reverts to ASSEMBLING."""
    reopened = []
    for row in STORE.records_requests.values():
        if row["student_id"] == student_id and row["status"] == "READY_FOR_RELEASE":
            _void_packet(row)
            reopened.append(row)
    if reopened:
        for incident in incidents_of_student(student_id):
            if incident["transfer_inclusion_state"] != "NOT_EVALUATED":
                incident["transfer_inclusion_state"] = "NOT_EVALUATED"
                touch(incident)
        for row in reopened:
            recompute_district_open_count(row["responding_district_id"])
    return reopened


def bubble_validated_requests(student_id):
    """VALIDATED -> ASSEMBLING as soon as the student's file starts assembling."""
    file_row = file_of_student(student_id)
    if file_row is None or file_row["assembly_status"] not in ("IN_ASSEMBLY", "COMPLETE"):
        return
    for row in STORE.records_requests.values():
        if row["student_id"] == student_id and row["status"] == "VALIDATED":
            row["status"] = "ASSEMBLING"
            touch(row)
            recompute_district_open_count(row["responding_district_id"])


# --------------------------------------------------------------------------- #
# Cumulative file reconciliation
# --------------------------------------------------------------------------- #
def _assembly_status(file_row, components, certified_count):
    student = STORE.students.get(file_row["student_id"])
    required = file_row["required_component_types"]
    all_pending = all(row["status"] == "PENDING" for row in components)
    if all_pending and student is not None and student["enrollment_status"] == "ENROLLED":
        return "NOT_STARTED"
    if len(required) > 0 and certified_count == len(required):
        return "COMPLETE"
    return "IN_ASSEMBLY"


def recompute_file(file_row, force_bump=False, cascade=True):
    components = components_of_file(file_row["id"])
    required = set(file_row["required_component_types"])

    total = 0
    included = 0
    excluded = 0
    disclosable = 0
    certified_count = 0
    for row in components:
        pages = int(row["page_count"])
        row["disclosable_page_count"] = pages - int(row["redacted_page_count"])
        total += pages
        if row["status"] in ("COLLECTED", "CERTIFIED"):
            included += pages
            disclosable += row["disclosable_page_count"]
        elif row["status"] == "EXCLUDED":
            excluded += pages
        if row["status"] == "CERTIFIED" and row["component_type"] in required:
            certified_count += 1

    previous_status = file_row["assembly_status"]
    new_status = _assembly_status(file_row, components, certified_count)

    updates = {
        "total_page_count": total,
        "included_page_count": included,
        "excluded_page_count": excluded,
        "disclosable_page_count": disclosable,
        "certified_component_count": certified_count,
        "completeness_pct": completeness_pct(certified_count, len(required)),
        "assembly_status": new_status,
    }
    changed = False
    for key, value in updates.items():
        if file_row.get(key) != value:
            file_row[key] = value
            changed = True
    if changed or force_bump:
        touch(file_row)

    if cascade:
        if previous_status == "COMPLETE" and new_status != "COMPLETE":
            reopen_ready_requests(file_row["student_id"])
        if previous_status == "NOT_STARTED" and new_status in ("IN_ASSEMBLY", "COMPLETE"):
            bubble_validated_requests(file_row["student_id"])
        recompute_retention_for_file(file_row)
    return file_row


# --------------------------------------------------------------------------- #
# Retention schedule reconciliation
# --------------------------------------------------------------------------- #
def mirror_disposition(student_row, schedule_row):
    value = schedule_row["destruction_eligible_at"] if schedule_row is not None else None
    if student_row.get("records_disposition_date") != value:
        student_row["records_disposition_date"] = value
        touch(student_row)


def recompute_schedule(schedule_row):
    file_row = STORE.cumulative_files.get(schedule_row["cumulative_file_id"])
    if file_row is None:
        return
    student_row = STORE.students.get(file_row["student_id"])
    if student_row is None:
        return
    last_activity, eligible_at, exit_eligible_at = retention_anchors(
        schedule_row, student_row, file_row)
    changed = False
    for key, value in (("last_activity_at", last_activity),
                       ("destruction_eligible_at", eligible_at),
                       ("exit_anchored_eligible_at", exit_eligible_at)):
        if schedule_row.get(key) != value:
            schedule_row[key] = value
            changed = True
    if changed:
        touch(schedule_row)
    mirror_disposition(student_row, schedule_row)


def recompute_retention_for_file(file_row):
    schedule = schedule_of_file(file_row["id"])
    if schedule is None or schedule["status"] == "DESTROYED":
        return
    recompute_schedule(schedule)


def recompute_retention_for_student(student_id):
    file_row = file_of_student(student_id)
    if file_row is None:
        return
    recompute_retention_for_file(file_row)


# --------------------------------------------------------------------------- #
# Disclosure log (append-only; written only by the operation it documents)
# --------------------------------------------------------------------------- #
def append_disclosure(student_id, disclosure_type, source_type, source_id, recipient_name,
                      disclosed_categories, page_count, logged_by_user_id,
                      legitimate_interest_note=None):
    row = base_row(with_version=False)
    row.update({
        "student_id": student_id,
        "disclosure_type": disclosure_type,
        "source_type": source_type,
        "source_id": source_id,
        "recipient_name": recipient_name,
        "disclosed_categories": list(disclosed_categories or []),
        "page_count": int(page_count or 0),
        "disclosed_at": clock_now(),
        "logged_by_user_id": logged_by_user_id,
        "legitimate_interest_note": legitimate_interest_note,
    })
    STORE.disclosure_entries[row["id"]] = row
    recompute_retention_for_student(student_id)
    return row
