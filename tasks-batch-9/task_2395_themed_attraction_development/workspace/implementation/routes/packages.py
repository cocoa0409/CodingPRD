"""DesignPackage, SafetyReview and SafetyFinding endpoints."""

from flask import Blueprint

import auth
import calc
import domain
import response
import store
import validate as V
from errors import ApiError
from routes.common import (
    body,
    check_package_version,
    check_project_version,
    no_body,
    page,
    state,
)

bp = Blueprint("packages", __name__)

PACKAGE_READ = (
    auth.OWNER_REP,
    auth.CREATIVE_DIRECTOR,
    auth.RIDE_ENGINEER,
    auth.THIRD_PARTY_REVIEWER,
    auth.CONTRACTOR_PM,
    auth.PROGRAM_ADMIN,
)


def _price(row):
    design_fee, contingency, total = calc.cost_of_work(row["base_construction_cost_cents"])
    row["design_fee_cents"] = design_fee
    row["contingency_cents"] = contingency
    row["total_cost_of_work_cents"] = total


# --------------------------------------------------------------- DesignPackage
@bp.post("/design-packages")
def create_package():
    auth.authenticate((auth.CREATIVE_DIRECTOR,))
    data = body(
        V.ID("project_id"),
        V.ID("ride_system_id"),
        V.S("package_label", min_len=1, max_len=80),
        V.E("discipline_scope", V.DISCIPLINE_SCOPES),
        V.I("base_construction_cost_cents", minimum=1),
        V.I("expected_project_version"),
    )
    project = domain.get_project(data["project_id"])
    system = domain.get_ride_system(data["ride_system_id"])
    check_project_version(project, data["expected_project_version"])
    domain.check_not_frozen(project)
    domain.check_not_restricted(project)
    if system["project_id"] != project["id"]:
        raise ApiError("ERR_RIDE_SYSTEM_PROJECT_MISMATCH", 422)

    row = store.base_row()
    row["project_id"] = project["id"]
    row["ride_system_id"] = system["id"]
    row["package_label"] = data["package_label"]
    row["discipline_scope"] = data["discipline_scope"]
    row["base_construction_cost_cents"] = data["base_construction_cost_cents"]
    _price(row)
    row["pinned_ride_system_version"] = None
    row["submitted_by_user_id"] = None
    row["approved_by_user_id"] = None
    row["revision_round"] = 0
    row["status"] = "DRAFT"
    store.design_packages[row["id"]] = row
    store.touch(project)
    return response.created(store.public(row))


@bp.get("/design-packages")
def list_packages():
    auth.authenticate(PACKAGE_READ)
    limit, offset = V.pagination()
    project_id = V.string_filter("project_id")
    ride_system_id = V.string_filter("ride_system_id")
    status = V.enum_filter("status", V.PACKAGE_STATUSES)
    rows = store.sorted_rows(list(store.design_packages.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if ride_system_id is not None:
        rows = [r for r in rows if r["ride_system_id"] == ride_system_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/design-packages/<row_id>")
def read_package(row_id):
    auth.authenticate(PACKAGE_READ)
    return response.ok(store.public(domain.get_package(row_id)))


@bp.post("/design-packages/<row_id>/submit")
def submit_package(row_id):
    user_id, _ = auth.authenticate((auth.CREATIVE_DIRECTOR, auth.OWNER_REP))
    no_body()
    package = domain.get_package(row_id)
    state(package, ("DRAFT", "REVISION_REQUESTED"), "ERR_PACKAGE_STATE_INVALID")
    project = domain.get_project(package["project_id"])
    domain.check_not_frozen(project)

    system = store.ride_systems.get(package["ride_system_id"])
    package["pinned_ride_system_version"] = system["version"] if system else None
    package["submitted_by_user_id"] = user_id
    if package["status"] == "REVISION_REQUESTED":
        package["revision_round"] = package["revision_round"] + 1
    package["status"] = "SUBMITTED"
    store.touch(package)
    return response.ok(store.public(package))


@bp.post("/design-packages/<row_id>/request-revision")
def request_revision(row_id):
    auth.authenticate((auth.OWNER_REP,))
    body(V.S("reason", min_len=1))
    package = domain.get_package(row_id)
    state(package, ("SUBMITTED",), "ERR_PACKAGE_STATE_INVALID")
    project = domain.get_project(package["project_id"])
    domain.check_not_frozen(project)

    package["status"] = "REVISION_REQUESTED"
    store.touch(package)
    return response.ok(store.public(package))


@bp.post("/design-packages/<row_id>/revise")
def revise_package(row_id):
    auth.authenticate((auth.CREATIVE_DIRECTOR,))
    data = body(V.I("base_construction_cost_cents", minimum=1), V.I("expected_package_version"))
    package = domain.get_package(row_id)
    check_package_version(package, data["expected_package_version"])
    state(package, ("DRAFT", "REVISION_REQUESTED"), "ERR_PACKAGE_STATE_INVALID")
    project = domain.get_project(package["project_id"])
    domain.check_not_frozen(project)

    package["base_construction_cost_cents"] = data["base_construction_cost_cents"]
    _price(package)
    store.touch(package)
    return response.ok(store.public(package))


@bp.post("/design-packages/<row_id>/approve")
def approve_package(row_id):
    user_id, _ = auth.authenticate((auth.OWNER_REP,))
    data = body(V.I("expected_package_version"))
    package = domain.get_package(row_id)
    check_package_version(package, data["expected_package_version"])
    state(package, ("SUBMITTED",), "ERR_PACKAGE_STATE_INVALID")
    project = domain.get_project(package["project_id"])
    domain.check_not_frozen(project)
    if package["submitted_by_user_id"] is not None and package["submitted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    system = store.ride_systems.get(package["ride_system_id"])
    current_version = system["version"] if system else None
    if package["pinned_ride_system_version"] != current_version:
        raise ApiError("ERR_PINNED_REFERENCE_STALE", 409)
    if project["committed_cost_cents"] + package["total_cost_of_work_cents"] > project["budget_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED", 409)

    package["approved_by_user_id"] = user_id
    package["status"] = "APPROVED"
    store.touch(package)
    for other in domain.packages_of(project["id"]):
        if other["id"] != package["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            store.touch(other)
    domain.mint_ledger_entry(
        project,
        "COMMITMENT",
        package["total_cost_of_work_cents"],
        "COMMITMENT for design package " + package["package_label"],
    )
    domain.refresh_project_exposure(project)
    store.touch(project)
    return response.ok(store.public(package))


@bp.get("/design-packages/<row_id>/safety-reviews")
def package_reviews(row_id):
    auth.authenticate(PACKAGE_READ)
    limit, offset = V.pagination()
    status = V.enum_filter("status", V.REVIEW_STATUSES)
    package = domain.get_package(row_id)
    rows = domain.reviews_of_package(package["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


# ---------------------------------------------------------------- SafetyReview
@bp.post("/safety-reviews")
def create_review():
    user_id, _ = auth.authenticate((auth.THIRD_PARTY_REVIEWER,))
    data = body(
        V.ID("design_package_id"),
        V.E("standard_code", V.SAFETY_STANDARDS),
        V.I("expected_package_version"),
    )
    package = domain.get_package(data["design_package_id"])
    check_package_version(package, data["expected_package_version"])
    state(package, ("SUBMITTED", "APPROVED"), "ERR_PACKAGE_STATE_INVALID")

    row = store.base_row()
    row["design_package_id"] = package["id"]
    row["standard_code"] = data["standard_code"]
    row["reviewer_user_id"] = user_id
    row["open_finding_count"] = 0
    row["cleared_at"] = None
    row["status"] = "IN_REVIEW"
    store.safety_reviews[row["id"]] = row
    store.touch(package)
    return response.created(store.public(row))


@bp.get("/safety-reviews/<row_id>")
def read_review(row_id):
    auth.authenticate(PACKAGE_READ)
    return response.ok(store.public(domain.get_review(row_id)))


@bp.post("/safety-reviews/<row_id>/clear")
def clear_review(row_id):
    auth.authenticate((auth.THIRD_PARTY_REVIEWER,))
    no_body()
    review = domain.get_review(row_id)
    state(review, ("IN_REVIEW", "FINDINGS_ISSUED"), "ERR_REVIEW_STATE_INVALID")
    if review["open_finding_count"] != 0:
        raise ApiError("ERR_OPEN_FINDINGS_PRESENT", 409)

    review["cleared_at"] = store.now_iso()
    review["status"] = "CLEARED"
    store.touch(review)
    return response.ok(store.public(review))


@bp.get("/safety-reviews/<row_id>/findings")
def review_findings(row_id):
    auth.authenticate(PACKAGE_READ)
    limit, offset = V.pagination()
    severity = V.enum_filter("severity", V.SEVERITIES)
    status = V.enum_filter("status", V.FINDING_STATUSES)
    review = domain.get_review(row_id)
    rows = domain.findings_of_review(review["id"])
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


# --------------------------------------------------------------- SafetyFinding
@bp.post("/safety-findings")
def create_finding():
    auth.authenticate((auth.THIRD_PARTY_REVIEWER,))
    data = body(
        V.ID("safety_review_id"),
        V.E("severity", V.SEVERITIES),
        V.S("description", min_len=1, max_len=500),
        V.I("remediation_cost_estimate_cents", minimum=0),
    )
    review = domain.get_review(data["safety_review_id"])
    state(review, ("IN_REVIEW", "FINDINGS_ISSUED"), "ERR_REVIEW_STATE_INVALID")

    row = store.base_row()
    row["safety_review_id"] = review["id"]
    row["severity"] = data["severity"]
    row["description"] = data["description"]
    row["remediation_cost_estimate_cents"] = data["remediation_cost_estimate_cents"]
    row["remediation_note"] = None
    row["waiver_justification"] = None
    row["status"] = "OPEN"
    store.safety_findings[row["id"]] = row

    review["status"] = "FINDINGS_ISSUED"
    review["open_finding_count"] = review["open_finding_count"] + 1
    store.touch(review)
    project = domain.project_of_review(review)
    if project is not None:
        domain.refresh_project_exposure(project)
        store.touch(project)
    return response.created(store.public(row))


@bp.get("/safety-findings/<row_id>")
def read_finding(row_id):
    auth.authenticate(PACKAGE_READ)
    return response.ok(store.public(domain.get_finding(row_id)))


@bp.post("/safety-findings/<row_id>/resolve")
def resolve_finding(row_id):
    auth.authenticate((auth.CONTRACTOR_PM,))
    data = body(V.S("remediation_note", min_len=1, max_len=500))
    finding = domain.get_finding(row_id)
    state(finding, ("OPEN",), "ERR_FINDING_STATE_INVALID")

    finding["remediation_note"] = data["remediation_note"]
    finding["status"] = "RESOLVED"
    store.touch(finding)
    return response.ok(store.public(finding))


@bp.post("/safety-findings/<row_id>/close")
def close_finding(row_id):
    auth.authenticate((auth.THIRD_PARTY_REVIEWER,))
    no_body()
    finding = domain.get_finding(row_id)
    state(finding, ("RESOLVED",), "ERR_FINDING_STATE_INVALID")

    finding["status"] = "CLOSED"
    store.touch(finding)
    _after_finding_closure(finding)
    return response.ok(store.public(finding))


@bp.post("/safety-findings/<row_id>/waive")
def waive_finding(row_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.S("justification", min_len=1, max_len=500))
    finding = domain.get_finding(row_id)
    state(finding, ("OPEN",), "ERR_FINDING_STATE_INVALID")
    if finding["severity"] == "CRITICAL":
        raise ApiError("ERR_CRITICAL_FINDING_NOT_WAIVABLE", 422)

    finding["waiver_justification"] = data["justification"]
    finding["status"] = "WAIVED"
    store.touch(finding)
    _after_finding_closure(finding)
    return response.ok(store.public(finding))


def _after_finding_closure(finding):
    review = store.safety_reviews.get(finding["safety_review_id"])
    if review is not None:
        review["open_finding_count"] = max(0, review["open_finding_count"] - 1)
        store.touch(review)
        project = domain.project_of_review(review)
        if project is not None:
            domain.refresh_project_exposure(project)
            store.touch(project)
