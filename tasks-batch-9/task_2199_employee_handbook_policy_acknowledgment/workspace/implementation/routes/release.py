"""Release packages: assembly, scheduling and the release event."""
from flask import Blueprint

import auth
import calc
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("release", __name__)

PACKAGE_READ = ["HRComplianceAdmin", "PolicyAuthor", "LegalCounsel"]


def _items(package):
    return services.rows_where("release_items", release_package_id=package["id"])


@bp.post("/release-packages")
def create_package():
    auth.authorize(["HRComplianceAdmin"])
    data = validate.body()
    raw_scope = data.get("scope_jurisdiction_ids")
    if isinstance(raw_scope, list):
        for jid in raw_scope:
            if isinstance(jid, str):
                validate.fk("jurisdictions", jid)
    name = validate.req_str(data, "name")
    effective_date = validate.req_datetime(data, "effective_date")
    scope = validate.req_id_array(data, "scope_jurisdiction_ids")
    for row in db.all_rows("release_packages"):
        if row["name"] == name:
            fail("ERR_DUPLICATE_RESOURCE", "name already registered")
    row = db.base_row()
    row.update({
        "name": name,
        "effective_date": effective_date,
        "scope_jurisdiction_ids": list(scope),
        "status": "DRAFT",
        "scheduled_at": None,
        "released_at": None,
        "legal_review_deadline": None,
        "roster_snapshot_size": 0,
        "coverage_snapshot_pct": None,
        "coverage_live_pct": None,
    })
    db.insert("release_packages", row)
    return web.created("release_packages", row)


@bp.get("/release-packages")
def list_packages():
    auth.authorize(PACKAGE_READ)
    rows = validate.query_filter(db.all_rows("release_packages"), "status")
    return web.paged("release_packages", rows)


@bp.get("/release-packages/<release_package_id>")
def read_package(release_package_id):
    auth.authorize(PACKAGE_READ)
    row = validate.path_row("release_packages", release_package_id)
    return web.one("release_packages", row)


@bp.post("/release-packages/<release_package_id>/items")
def add_item(release_package_id):
    auth.authorize(["HRComplianceAdmin"])
    package = validate.path_row("release_packages", release_package_id)
    data = validate.body()
    if "policy_version_id" in data:
        validate.fk("policy_versions", data.get("policy_version_id"))
    policy_version_id = validate.req_str(data, "policy_version_id")
    if package["status"] != "DRAFT":
        fail("ERR_RELEASE_NOT_DRAFT", "package is %s" % package["status"])
    for row in services.rows_where("release_items", release_package_id=package["id"],
                                   policy_version_id=policy_version_id):
        fail("ERR_DUPLICATE_RESOURCE", "version already added to this package")
    row = db.base_row(versioned=False)
    row.update({
        "release_package_id": package["id"],
        "policy_version_id": policy_version_id,
        "supersedes_version_id": None,
    })
    db.insert("release_items", row)
    db.touch(package)
    return web.created("release_items", row)


@bp.get("/release-items")
def list_items():
    auth.authorize(PACKAGE_READ)
    rows = db.all_rows("release_items")
    rows = validate.query_filter(rows, "release_package_id")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "supersedes_version_id")
    return web.paged("release_items", rows)


@bp.get("/release-items/<release_item_id>")
def read_item(release_item_id):
    auth.authorize(PACKAGE_READ)
    row = validate.path_row("release_items", release_item_id)
    return web.one("release_items", row)


@bp.post("/release-packages/<release_package_id>/unschedule")
def unschedule_package(release_package_id):
    auth.authorize(["HRComplianceAdmin"])
    package = validate.path_row("release_packages", release_package_id)
    if package["status"] != "SCHEDULED":
        fail("ERR_RELEASE_NOT_SCHEDULED", "package is %s" % package["status"])
    package["status"] = "DRAFT"
    package["scheduled_at"] = None
    package["legal_review_deadline"] = None
    db.touch(package)
    return web.one("release_packages", package)


@bp.post("/release-packages/<release_package_id>/cancel")
def cancel_package(release_package_id):
    auth.authorize(["HRComplianceAdmin"])
    package = validate.path_row("release_packages", release_package_id)
    if package["status"] not in ("DRAFT", "SCHEDULED"):
        fail("ERR_RELEASE_NOT_CANCELLABLE", "package is %s" % package["status"])
    was_scheduled = package["status"] == "SCHEDULED"
    package["status"] = "CANCELLED"
    if was_scheduled:
        package["legal_review_deadline"] = None
    db.touch(package)
    return web.one("release_packages", package)


@bp.get("/release-packages/<release_package_id>/coverage")
def read_coverage(release_package_id):
    auth.authorize(["HRComplianceAdmin", "PolicyAuthor"])
    package = validate.path_row("release_packages", release_package_id)
    services.write_coverage(package)
    return web.one("release_packages", package)


def _version_of(item):
    return db.get("policy_versions", item["policy_version_id"])


def _check_translation_coverage(package, items):
    for item in items:
        version = _version_of(item)
        if version is None:
            continue
        for jid in package["scope_jurisdiction_ids"]:
            jurisdiction = db.get("jurisdictions", jid)
            if jurisdiction is None:
                continue
            for language in jurisdiction["required_language_codes"]:
                if services.published_translation(version["id"], language) is None:
                    fail("ERR_TRANSLATION_NOT_PUBLISHED",
                         "no published %s rendition for version %s" % (language, version["id"]))


def _check_window_overlap(package, items):
    candidate = package["effective_date"]
    for item in items:
        version = _version_of(item)
        if version is None:
            continue
        for sibling in services.rows_where("policy_versions",
                                           policy_document_id=version["policy_document_id"]):
            if sibling["id"] == version["id"]:
                continue
            if sibling["status"] == "SUPERSEDED":
                start = sibling["effective_date"]
                end = sibling["window_end_date"]
                if start is None:
                    continue
                if end is None:
                    if candidate >= start:
                        fail("ERR_EFFECTIVE_WINDOW_OVERLAP", "candidate falls inside a sibling window")
                elif start <= candidate < end:
                    fail("ERR_EFFECTIVE_WINDOW_OVERLAP", "candidate falls inside a sibling window")
            elif sibling["status"] == "PUBLISHED":
                start = sibling["effective_date"]
                if start is not None and candidate <= start:
                    fail("ERR_EFFECTIVE_WINDOW_OVERLAP",
                         "candidate must be strictly later than the published sibling")


def _check_lead_time(package, items):
    for item in items:
        version = _version_of(item)
        if version is None:
            continue
        for jid in package["scope_jurisdiction_ids"]:
            if jid not in version["required_jurisdiction_ids"]:
                continue
            jurisdiction = db.get("jurisdictions", jid)
            if jurisdiction is None:
                continue
            review = None
            for candidate in services.rows_where("legal_reviews", policy_version_id=version["id"],
                                                 jurisdiction_id=jid):
                review = candidate
            if review is None or review.get("decided_at") is None:
                continue
            bound = clock.add_days(review["decided_at"], jurisdiction["min_legal_review_days"])
            if bound > package["effective_date"]:
                fail("ERR_LEGAL_REVIEW_LEAD_TIME_SHORT",
                     "statutory lead time for %s is not satisfied" % jurisdiction["state_code"])


@bp.post("/release-packages/<release_package_id>/schedule")
def schedule_package(release_package_id):
    auth.authorize(["HRComplianceAdmin"])
    package = validate.path_row("release_packages", release_package_id)
    if package["status"] != "DRAFT":
        fail("ERR_RELEASE_NOT_DRAFT", "package is %s" % package["status"])
    items = _items(package)
    for item in items:
        version = _version_of(item)
        if version is None or version["status"] != "APPROVED":
            fail("ERR_VERSION_INVALID_STATE", "every item version must be APPROVED")
    _check_translation_coverage(package, items)
    if not items:
        fail("ERR_RELEASE_EMPTY", "package carries no items")
    _check_window_overlap(package, items)
    if not package["effective_date"] > clock.now():
        fail("ERR_EFFECTIVE_DATE_IN_PAST", "effective_date must be strictly later than now")
    _check_lead_time(package, items)
    scope = [db.get("jurisdictions", jid) for jid in package["scope_jurisdiction_ids"]]
    scope = [j for j in scope if j is not None]
    package["status"] = "SCHEDULED"
    package["scheduled_at"] = clock.now()
    if scope:
        package["legal_review_deadline"] = calc.legal_review_deadline(
            scope, package["effective_date"], clock.now())
    db.touch(package)
    return web.one("release_packages", package)


def _roster_pairs(package, items):
    """Item x employee pairings, employee created_at ASC then item version created_at ASC."""
    employees = [row for row in db.all_rows("employees")
                 if row["jurisdiction_id"] in package["scope_jurisdiction_ids"]
                 and row["employment_status"] in ("ACTIVE", "ON_LEAVE")]
    employees = db.sort_created(employees)
    ordered_items = sorted(items, key=lambda it: (
        _version_of(it)["created_at"], _version_of(it)["_seq"]))
    pairs = []
    for employee in employees:
        for item in ordered_items:
            pairs.append((employee, item))
    return pairs


def _plan_assignment(package, employee, item):
    version = _version_of(item)
    document = services.document_of_version(version)
    jurisdiction = db.get("jurisdictions", employee["jurisdiction_id"])
    window_start = package["effective_date"]
    due_date = services.mint_due_date(window_start, jurisdiction, document, employee)
    return {
        "employee": employee,
        "item": item,
        "version": version,
        "jurisdiction": jurisdiction,
        "policy_category": document["category"],
        "window_start_date": window_start,
        "due_date": due_date,
    }


def _check_buffer(plan):
    for candidate in plan:
        employee = candidate["employee"]
        buffer_days = candidate["jurisdiction"]["ack_window_buffer_days"]
        for existing in services.rows_where("assignments", employee_id=employee["id"]):
            if existing["policy_category"] != candidate["policy_category"]:
                continue
            if existing["ack_state"] not in ("UNDELIVERED", "PENDING", "ACKNOWLEDGED"):
                continue
            if existing["window_start_date"] <= candidate["window_start_date"]:
                gap = services.window_gap_days(existing["due_date"],
                                               candidate["window_start_date"])
            else:
                gap = services.window_gap_days(candidate["due_date"],
                                               existing["window_start_date"])
            if gap < buffer_days:
                fail("ERR_ACK_WINDOW_BUFFER_CONFLICT",
                     "same-category acknowledgment windows are %d days apart" % gap)


@bp.post("/release-packages/<release_package_id>/release")
def release_package(release_package_id):
    auth.authorize(["HRComplianceAdmin"])
    package = validate.path_row("release_packages", release_package_id)
    data = validate.body()
    expected = validate.req_int(data, "expected_release_package_version")
    if expected != package["version"]:
        fail("ERR_STALE_RELEASE_PACKAGE_VERSION",
             "expected_release_package_version %s does not match %s"
             % (expected, package["version"]))
    if package["status"] != "SCHEDULED":
        fail("ERR_RELEASE_NOT_SCHEDULED", "package is %s" % package["status"])
    if clock.now() < package["effective_date"]:
        fail("ERR_EFFECTIVE_DATE_NOT_REACHED", "effective_date has not been reached")
    items = _items(package)
    for item in items:
        version = _version_of(item)
        if version is None or version["status"] != "APPROVED":
            fail("ERR_VERSION_INVALID_STATE", "every item version must still be APPROVED")
    plan = [_plan_assignment(package, employee, item)
            for employee, item in _roster_pairs(package, items)]
    _check_buffer(plan)
    package["status"] = "RELEASED"
    package["released_at"] = clock.now()
    for item in items:
        services.publish_version(_version_of(item), item, package["effective_date"])
    minted = 0
    for candidate in plan:
        row = db.base_row()
        row.update({
            "release_package_id": package["id"],
            "policy_version_id": candidate["version"]["id"],
            "employee_id": candidate["employee"]["id"],
            "jurisdiction_id": candidate["employee"]["jurisdiction_id"],
            "ack_state": "UNDELIVERED",
            "escalation_state": "NONE",
            "window_start_date": candidate["window_start_date"],
            "due_date": candidate["due_date"],
            "delivered_at": None,
            "acknowledged_at": None,
            "days_overdue": 0,
            "policy_category": candidate["policy_category"],
        })
        db.insert("assignments", row)
        services.adjust_open_ack(candidate["employee"], 1)
        minted += 1
    package["roster_snapshot_size"] = minted
    services.write_coverage(package)
    db.touch(package)
    services.maybe_close_package(package)
    return web.one("release_packages", package)
