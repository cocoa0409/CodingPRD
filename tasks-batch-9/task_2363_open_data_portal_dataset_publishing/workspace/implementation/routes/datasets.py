"""Dataset inventory, publication lifecycle, analytics, usage and showcases."""

from flask import Blueprint

import calc
import services
from calc import D
from common import bad_state, dept_scope, find, member_scope
from core import (
    body,
    caller,
    db,
    err,
    new_row,
    now,
    ok,
    opt_datetime,
    opt_enum,
    opt_str,
    page,
    req_enum,
    req_int,
    req_num,
    req_str,
    touch,
)

bp = Blueprint("datasets", __name__)

SHOWCASE_DECISIONS = {
    "APPROVE": "APPROVED",
    "APPROVED": "APPROVED",
    "REJECT": "REJECTED",
    "REJECTED": "REJECTED",
}


def posture_gate(dataset, publish=False):
    """PRD §2.9 / precedence 33."""
    dept = services.dept_of_dataset(dataset)
    if dept is None:
        return
    if dept["compliance_posture"] == "SUSPENDED":
        err("ERR_DEPARTMENT_SUSPENDED", "The owning department's posture is SUSPENDED.")
    if publish and dept["compliance_posture"] == "RESTRICTED":
        if dataset["priority_tier"] not in ("TIER_1", "TIER_2"):
            err(
                "ERR_RESTRICTED_POSTURE_TIER",
                "A RESTRICTED department may not publish a TIER_3 dataset.",
            )


def cleared_assessment(dataset_id):
    rows = services.assessments_of_dataset(dataset_id, ("CLEARED",))
    return rows[0] if rows else None


def accepted_metadata(dataset_id):
    rows = services.metadata_of_dataset(dataset_id, ("ACCEPTED",))
    return rows[0] if rows else None


def aggregation_gate(dataset):
    """PRD §3.3 / precedence 15."""
    assessment = cleared_assessment(dataset["id"])
    if assessment is None or not assessment["aggregation_required"]:
        return
    own = calc.GEO_RANK.get(dataset["aggregation_geography"], 0)
    required = calc.GEO_RANK.get(assessment["min_aggregation_geography"], 0)
    if own < required:
        err(
            "ERR_AGGREGATION_UNMET",
            "The dataset must be aggregated to at least %s."
            % assessment["min_aggregation_geography"],
        )


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
@bp.post("/datasets")
def create_dataset():
    role, user_id = caller("DataCoordinator")
    data = body()
    department_id = req_str(data, "department_id")
    title = req_str(data, "title")
    slug = req_str(data, "slug")
    description = req_str(data, "description")
    update_frequency = req_enum(data, "update_frequency", calc.UPDATE_FREQUENCIES)
    column_count = req_int(data, "column_count", 1)
    sensitivity_class = req_enum(data, "sensitivity_class", calc.SENSITIVITY_CLASSES)
    public_demand_score = req_num(data, "public_demand_score", 0, 100)
    policy_value_score = req_num(data, "policy_value_score", 0, 100)
    embargo = opt_datetime(data, "embargo_until_utc")
    geography = opt_enum(data, "aggregation_geography", calc.GEOGRAPHIES)
    find("departments", department_id)
    dept_scope(user_id, department_id)
    for existing in db.datasets.values():
        if existing["slug"] == slug:
            err("ERR_DUPLICATE_DATASET_SLUG", "Dataset slug %s already exists." % slug)
    row = new_row()
    row.update(
        {
            "department_id": department_id,
            "title": title,
            "slug": slug,
            "description": description,
            "update_frequency": update_frequency,
            "column_count": column_count,
            "sensitivity_class": sensitivity_class,
            "public_demand_score": public_demand_score,
            "policy_value_score": policy_value_score,
            "embargo_until_utc": embargo,
            "aggregation_geography": geography,
            "engagement_index": calc.ZERO,
            "observed_demand_score": calc.ZERO,
            "priority_score": calc.ZERO,
            "priority_score_variant": "AS_DECLARED",
            "priority_tier": "TIER_3",
            "usage_epochs": [],
            "showcase_apps": [],
            "publication_status": "INVENTORIED",
            "currency_status": "CURRENT",
            "public_access_suspended": False,
            "high_value_committed": False,
            "live_row_count": 0,
            "version_index_high_water": 0,
            "last_published_at": None,
            "next_due_at": None,
            "days_overdue": 0,
            "staleness_alert_count": 0,
            "last_staleness_alert_at": None,
            "remediation_opened_at": None,
        }
    )
    db.datasets[row["id"]] = row
    services.recompute_priority(row, "AS_DECLARED")
    return ok(services.dataset_out(row), 201)


PUBLICATION_STATUSES = (
    "INVENTORIED",
    "SCREENING",
    "READY",
    "PUBLISHED",
    "UNDER_REMEDIATION",
    "RETIRED",
)
CURRENCY_STATUSES = ("CURRENT", "AGING", "STALE", "BREACHED")
PRIORITY_TIERS = ("TIER_1", "TIER_2", "TIER_3")


def _enum_arg(name, allowed):
    from flask import request

    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


@bp.get("/datasets")
def list_datasets():
    from flask import request

    caller()
    department_id = request.args.get("department_id")
    publication_status = _enum_arg("publication_status", PUBLICATION_STATUSES)
    currency_status = _enum_arg("currency_status", CURRENCY_STATUSES)
    priority_tier = _enum_arg("priority_tier", PRIORITY_TIERS)
    sensitivity_class = _enum_arg("sensitivity_class", calc.SENSITIVITY_CLASSES)
    high_value = request.args.get("high_value_committed")
    if high_value is not None:
        lowered = high_value.strip().lower()
        if lowered in ("true", "1"):
            high_value = True
        elif lowered in ("false", "0"):
            high_value = False
        else:
            err("ERR_INVALID_REQUEST", "high_value_committed must be a boolean.")
    rows = list(db.datasets.values())
    if department_id is not None:
        rows = [r for r in rows if r["department_id"] == department_id]
    if publication_status is not None:
        rows = [r for r in rows if r["publication_status"] == publication_status]
    if currency_status is not None:
        rows = [r for r in rows if r["currency_status"] == currency_status]
    if priority_tier is not None:
        rows = [r for r in rows if r["priority_tier"] == priority_tier]
    if sensitivity_class is not None:
        rows = [r for r in rows if r["sensitivity_class"] == sensitivity_class]
    if high_value is not None:
        rows = [r for r in rows if r["high_value_committed"] == high_value]
    return page(rows, services.dataset_out)


@bp.get("/datasets/<dataset_id>")
def get_dataset(dataset_id):
    caller()
    return ok(services.dataset_out(find("datasets", dataset_id)))


@bp.get("/datasets/<dataset_id>/analytics")
def dataset_analytics(dataset_id):
    caller()
    dataset = find("datasets", dataset_id)
    engagement = calc.engagement_index(dataset["usage_epochs"])
    snapshot = dict(dataset)
    snapshot["observed_demand_score"] = engagement
    as_declared = calc.priority_score(snapshot, "AS_DECLARED", db.requests)
    as_observed = calc.priority_score(snapshot, "AS_OBSERVED", db.requests)
    variant = dataset["priority_score_variant"]
    active = as_observed if variant == "AS_OBSERVED" else as_declared
    approved = len([s for s in dataset["showcase_apps"] if s["status"] == "APPROVED"])
    open_issues = len(
        [
            i
            for i in services.issues_of_dataset(dataset_id)
            if i["status"] in ("SUBMITTED", "TRIAGED", "ACCEPTED")
        ]
    )
    return ok(
        {
            "dataset_id": dataset["id"],
            "engagement_index": services.num(engagement),
            "observed_demand_score": services.num(engagement),
            "priority_score": services.num(active),
            "priority_score_variant": variant,
            "priority_tier": calc.priority_tier(active),
            "priority_score_as_declared": services.num(as_declared),
            "priority_score_as_observed": services.num(as_observed),
            "usage_epoch_count": len(dataset["usage_epochs"]),
            "approved_showcase_count": approved,
            "open_issue_count": open_issues,
            "currency_status": dataset["currency_status"],
            "days_overdue": dataset["days_overdue"],
            "next_due_at": services.fmt_ts(dataset["next_due_at"]),
        }
    )


# --------------------------------------------------------------------------
# Publication lifecycle
# --------------------------------------------------------------------------
@bp.post("/datasets/<dataset_id>/screen")
def screen_dataset(dataset_id):
    role, user_id = caller("DataCoordinator")
    dataset = find("datasets", dataset_id)
    dept_scope(user_id, dataset["department_id"])
    if dataset["publication_status"] != "INVENTORIED":
        bad_state("Only an INVENTORIED dataset may enter SCREENING.")
    posture_gate(dataset)
    dataset["publication_status"] = "SCREENING"
    touch(dataset)
    services.recompute_priority(dataset, "AS_DECLARED")
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/aggregation")
def set_aggregation(dataset_id):
    role, user_id = caller("DataCoordinator")
    dataset = find("datasets", dataset_id)
    data = body()
    geography = req_enum(data, "aggregation_geography", calc.GEOGRAPHIES)
    dept_scope(user_id, dataset["department_id"])
    if dataset["publication_status"] not in ("SCREENING", "READY"):
        bad_state("Aggregation may only be set while the dataset is SCREENING or READY.")
    dataset["aggregation_geography"] = geography
    touch(dataset)
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/mark-ready")
def mark_ready(dataset_id):
    role, user_id = caller("DataCoordinator")
    dataset = find("datasets", dataset_id)
    dept_scope(user_id, dataset["department_id"])
    if dataset["publication_status"] != "SCREENING":
        bad_state("Only a SCREENING dataset may be declared READY.")
    if accepted_metadata(dataset_id) is None:
        err("ERR_METADATA_NOT_ACCEPTED", "The dataset has no ACCEPTED metadata record.")
    if cleared_assessment(dataset_id) is None:
        err(
            "ERR_PRIVACY_CLEARANCE_REQUIRED",
            "The dataset has no CLEARED privacy assessment.",
        )
    aggregation_gate(dataset)
    posture_gate(dataset)
    dataset["publication_status"] = "READY"
    touch(dataset)
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/publish")
def publish_dataset(dataset_id):
    role, user_id = caller("DataCoordinator")
    dataset = find("datasets", dataset_id)
    data = body()
    initial_row_count = req_int(data, "initial_row_count", 0)
    dept_scope(user_id, dataset["department_id"])
    if dataset["publication_status"] != "READY":
        bad_state("Only a READY dataset may be published.")
    record = accepted_metadata(dataset_id)
    if record is None:
        err("ERR_METADATA_NOT_ACCEPTED", "The dataset has no ACCEPTED metadata record.")
    aggregation_gate(dataset)
    license_row = db.licenses.get(record["license_id"])
    if license_row is not None and license_row["retired"]:
        err("ERR_LICENSE_RETIRED", "The backing licence has been retired.")
    if dataset["embargo_until_utc"] is not None and now() < dataset["embargo_until_utc"]:
        err("ERR_EMBARGO_ACTIVE", "The publication embargo has not yet expired.")
    posture_gate(dataset, publish=True)
    dataset["publication_status"] = "PUBLISHED"
    touch(dataset)
    services.mint_version(dataset, "INITIAL", initial_row_count)
    services.recompute_engagement(dataset)
    services.recompute_priority(dataset, "AS_OBSERVED")
    services.recompute_currency(dataset)
    services.recompute_department_of(dataset)
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/retire")
def retire_dataset(dataset_id):
    role, user_id = caller("DataCoordinator")
    dataset = find("datasets", dataset_id)
    data = body()
    opt_str(data, "reason")
    dept_scope(user_id, dataset["department_id"])
    if dataset["publication_status"] not in ("READY", "PUBLISHED"):
        bad_state("Only a READY or PUBLISHED dataset may be retired.")
    for issue in services.issues_of_dataset(dataset_id):
        if issue["status"] in ("SUBMITTED", "TRIAGED", "ACCEPTED"):
            err(
                "ERR_OPEN_ISSUES_BLOCK_RETIRE",
                "Open quality issues must be resolved before retirement.",
            )
    from_published = dataset["publication_status"] == "PUBLISHED"
    dataset["publication_status"] = "RETIRED"
    dataset["public_access_suspended"] = True
    touch(dataset)
    if from_published:
        for pipeline in services.pipelines_of_dataset(dataset_id):
            if pipeline["status"] in ("ARMED", "SUSPENDED"):
                services.decommission_pipeline(pipeline, "DATASET_RETIRED")
        services.recompute_department_of(dataset)
    return ok(services.dataset_out(dataset))


# --------------------------------------------------------------------------
# Analytics ingestion, high-value commitment and showcases
# --------------------------------------------------------------------------
@bp.post("/datasets/<dataset_id>/usage-report")
def usage_report(dataset_id):
    caller("PortalAdmin")
    dataset = find("datasets", dataset_id)
    data = body()
    epoch_index = req_int(data, "epoch_index", 0)
    api_call_count = req_int(data, "api_call_count", 0)
    download_count = req_int(data, "download_count", 0)
    for epoch in dataset["usage_epochs"]:
        if epoch["epoch_index"] == epoch_index:
            err("ERR_DUPLICATE_USAGE_EPOCH", "Usage epoch %d already recorded." % epoch_index)
    if dataset["publication_status"] in ("INVENTORIED", "RETIRED"):
        err(
            "ERR_DATASET_NOT_PUBLISHED",
            "Usage may only be recorded from SCREENING onward.",
        )
    dataset["usage_epochs"].append(
        {
            "epoch_index": epoch_index,
            "api_call_count": api_call_count,
            "download_count": download_count,
            "recorded_at": now(),
        }
    )
    touch(dataset)
    services.recompute_engagement(dataset)
    services.recompute_priority(dataset)
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/high-value-commitment")
def high_value_commitment(dataset_id):
    caller("PortalAdmin")
    dataset = find("datasets", dataset_id)
    if dataset["priority_tier"] != "TIER_1" or dataset["publication_status"] not in (
        "READY",
        "PUBLISHED",
    ):
        err(
            "ERR_NOT_HIGH_VALUE_ELIGIBLE",
            "Only a TIER_1 dataset in READY or PUBLISHED may be committed.",
        )
    dataset["high_value_committed"] = True
    touch(dataset)
    return ok(services.dataset_out(dataset))


@bp.post("/datasets/<dataset_id>/showcase-apps")
def submit_showcase(dataset_id):
    role, user_id = caller("CommunityMember")
    dataset = find("datasets", dataset_id)
    data = body()
    label = req_str(data, "label")
    name = req_str(data, "name")
    url = req_str(data, "url")
    submitter_member_id = req_str(data, "submitter_member_id")
    find("members", submitter_member_id)
    member_scope(user_id, submitter_member_id)
    for entry in dataset["showcase_apps"]:
        if entry["label"] == label:
            err("ERR_DUPLICATE_SHOWCASE_LABEL", "Showcase label %s already exists." % label)
    dataset["showcase_apps"].append(
        {
            "label": label,
            "name": name,
            "url": url,
            "submitter_member_id": submitter_member_id,
            "status": "SUBMITTED",
            "decided_at": None,
        }
    )
    touch(dataset)
    return ok(services.dataset_out(dataset), 201)


@bp.post("/datasets/<dataset_id>/showcase-apps/<showcase_label>/decide")
def decide_showcase(dataset_id, showcase_label):
    caller("PortalAdmin")
    dataset = find("datasets", dataset_id)
    entry = None
    for candidate in dataset["showcase_apps"]:
        if candidate["label"] == showcase_label:
            entry = candidate
            break
    if entry is None:
        err("ERR_SHOWCASE_NOT_FOUND", "No showcase entry labelled %s." % showcase_label)
    data = body()
    decision = req_str(data, "decision")
    if decision not in SHOWCASE_DECISIONS:
        err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT.")
    if entry["status"] != "SUBMITTED":
        bad_state("Only a SUBMITTED showcase entry may be moderated.")
    entry["status"] = SHOWCASE_DECISIONS[decision]
    entry["decided_at"] = now()
    touch(dataset)
    if entry["status"] == "APPROVED":
        member = db.members.get(entry["submitter_member_id"])
        if member is not None:
            services.recompute_member(member)
    return ok(services.dataset_out(dataset))
