"""Shared cascades, counters and computed writes."""
import calc
import clock
import db

OPEN_ACK_STATES = ("UNDELIVERED", "PENDING")
OPEN_CASE_STATUSES = ("OPEN", "NOTIFIED", "ESCALATED_HR")


def rows_where(table, **kwargs):
    out = []
    for row in db.all_rows(table):
        if all(row.get(k) == v for k, v in kwargs.items()):
            out.append(row)
    return db.sort_created(out)


def employee_of(row):
    return db.get("employees", row["employee_id"])


def adjust_open_ack(employee, delta):
    employee["open_ack_count"] = employee["open_ack_count"] + delta


def adjust_open_escalation(employee, delta):
    employee["open_escalation_count"] = employee["open_escalation_count"] + delta


def adjust_open_reviews(reviewer, delta):
    reviewer["open_review_count"] = reviewer["open_review_count"] + delta


def document_of_version(version):
    return db.get("policy_documents", version["policy_document_id"])


def close_cases_for_assignment(assignment, status, escalation_state):
    """Close every open EscalationCase on the assignment with the given outcome."""
    closed = False
    for case in rows_where("escalations", assignment_id=assignment["id"]):
        if case["status"] in OPEN_CASE_STATUSES:
            case["status"] = status
            case["closed_at"] = clock.now()
            db.touch(case)
            employee = db.get("employees", case["employee_id"])
            if employee is not None:
                adjust_open_escalation(employee, -1)
            closed = True
    if closed and assignment["escalation_state"] == "ESCALATING":
        assignment["escalation_state"] = escalation_state
    return closed


def void_open_assignments(version):
    """Void every UNDELIVERED / PENDING assignment on the version."""
    packages = []
    for assignment in rows_where("assignments", policy_version_id=version["id"]):
        if assignment["ack_state"] not in OPEN_ACK_STATES:
            continue
        assignment["ack_state"] = "VOIDED"
        db.touch(assignment)
        employee = employee_of(assignment)
        if employee is not None:
            adjust_open_ack(employee, -1)
        close_cases_for_assignment(assignment, "CLOSED_MOOT", "MOOT")
        if assignment["release_package_id"] not in packages:
            packages.append(assignment["release_package_id"])
    for package_id in packages:
        package = db.get("release_packages", package_id)
        if package is not None:
            maybe_close_package(package)


def supersede_prior_version(prior, successor_effective_date):
    """Four-hop supersede cascade on the document's prior published version."""
    prior["status"] = "SUPERSEDED"
    prior["window_end_date"] = successor_effective_date
    db.touch(prior)
    void_open_assignments(prior)


def coverage_numbers(package):
    assignments = rows_where("assignments", release_package_id=package["id"])
    numerator = sum(1 for a in assignments if a["ack_state"] in ("ACKNOWLEDGED", "EXEMPT"))
    denom_live = 0
    for a in assignments:
        if a["ack_state"] == "VOIDED":
            continue
        employee = employee_of(a)
        if employee is not None and employee["employment_status"] in ("ACTIVE", "ON_LEAVE"):
            denom_live += 1
    snap = calc.coverage(numerator, package["roster_snapshot_size"])
    live = calc.coverage(numerator, denom_live)
    return snap, live


def write_coverage(package):
    snap, live = coverage_numbers(package)
    package["coverage_snapshot_pct"] = snap
    package["coverage_live_pct"] = live


def open_assignment_count(package):
    return sum(
        1 for a in rows_where("assignments", release_package_id=package["id"])
        if a["ack_state"] in OPEN_ACK_STATES
    )


def maybe_close_package(package):
    if package["status"] != "RELEASED":
        return False
    if open_assignment_count(package) != 0:
        return False
    package["status"] = "CLOSED"
    write_coverage(package)
    db.touch(package)
    return True


def append_retention(acknowledgment, assignment, record_kind, signed_delta):
    jurisdiction = db.get("jurisdictions", assignment["jurisdiction_id"])
    retained_from = clock.now()
    retention_years = jurisdiction["retention_years"] if jurisdiction else 1
    row = db.base_row(versioned=False)
    row.update({
        "acknowledgment_id": acknowledgment["id"],
        "employee_id": assignment["employee_id"],
        "jurisdiction_id": assignment["jurisdiction_id"],
        "record_kind": record_kind,
        "signed_delta": signed_delta,
        "retained_from": retained_from,
        "retention_until": calc.retention_until(retained_from, retention_years),
        "legal_hold": False,
        "hold_reason": None,
    })
    return db.insert("retention_records", row)


def revert_version_to_draft(version):
    """Four-hop cascade fired whenever a version leaves IN_LEGAL_REVIEW for DRAFT."""
    version["status"] = "DRAFT"
    version["revision_round"] = version["revision_round"] + 1
    db.touch(version)
    for review in rows_where("legal_reviews", policy_version_id=version["id"]):
        if review["status"] not in ("REQUESTED", "IN_PROGRESS"):
            continue
        review["status"] = "WITHDRAWN"
        review["decided_at"] = clock.now()
        db.touch(review)
        reviewer = db.get("legal_reviewers", review["reviewer_id"])
        if reviewer is not None:
            adjust_open_reviews(reviewer, -1)
    for addendum in rows_where("addenda", policy_version_id=version["id"]):
        if addendum["status"] != "APPROVED":
            continue
        addendum["status"] = "DRAFT"
        addendum["approved_by_reviewer_id"] = None
        db.touch(addendum)


def retire_addenda(version):
    for addendum in rows_where("addenda", policy_version_id=version["id"]):
        if addendum["status"] in ("DRAFT", "APPROVED"):
            addendum["status"] = "RETIRED"
            db.touch(addendum)


def publish_version(version, item, effective_date):
    """Publish an item version and run the supersede cascade on the prior published one."""
    version["status"] = "PUBLISHED"
    version["effective_date"] = effective_date
    db.touch(version)
    document = document_of_version(version)
    prior_id = document.get("current_published_version_id") if document else None
    if prior_id and prior_id != version["id"]:
        prior = db.get("policy_versions", prior_id)
        if prior is not None and prior["status"] == "PUBLISHED":
            supersede_prior_version(prior, effective_date)
            item["supersedes_version_id"] = prior["id"]
    if document is not None:
        document["current_published_version_id"] = version["id"]


def published_translation(version_id, language_code):
    for track in rows_where("translations", policy_version_id=version_id, language_code=language_code):
        if track["status"] == "PUBLISHED":
            return track
    return None


def intervals_intersect(a_start, a_end, b_start, b_end):
    """Closed-interval intersection on both sides."""
    return a_start <= b_end and b_start <= a_end


def reviewer_capacity_used(reviewer_id, candidate_start, candidate_end, exclude_id=None):
    used = 0
    for review in db.all_rows("legal_reviews"):
        if review["reviewer_id"] != reviewer_id:
            continue
        if exclude_id is not None and review["id"] == exclude_id:
            continue
        if review["status"] not in ("REQUESTED", "IN_PROGRESS"):
            continue
        if intervals_intersect(review["assigned_at"], review["due_at"], candidate_start, candidate_end):
            used += 1
    return used


def window_gap_days(earlier_due, later_start):
    return clock.floor_days(later_start, earlier_due)


def mint_due_date(window_start, jurisdiction, document, employee):
    days = calc.ack_deadline_days(
        jurisdiction["ack_deadline_days"],
        document["max_ack_deadline_days"],
        employee["employment_status"],
        employee["needs_accessible_format"],
        document["category"],
    )
    return clock.add_days(window_start, days)


def reopen_package(assignment):
    """A revocation that returns an assignment to PENDING pulls a CLOSED package back."""
    package = db.get("release_packages", assignment["release_package_id"])
    if package is not None and package["status"] == "CLOSED":
        package["status"] = "RELEASED"
        db.touch(package)
        return True
    return False
