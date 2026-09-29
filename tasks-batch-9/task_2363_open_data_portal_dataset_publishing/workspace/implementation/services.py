"""Domain services: derived-field recomputation, cascades and serialisers."""

from datetime import timedelta
from decimal import Decimal

import calc
from calc import D, q2
from core import db, err, fmt_ts, new_row, now, sort_rows, touch

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def num(value):
    if value is None:
        return None
    return float(D(value))


def dept_of_dataset(dataset):
    return db.departments.get(dataset["department_id"])


def datasets_of_department(department_id):
    return [d for d in db.datasets.values() if d["department_id"] == department_id]


def pipelines_of_dataset(dataset_id):
    return [p for p in db.pipelines.values() if p["dataset_id"] == dataset_id]


def runs_of_pipeline(pipeline_id):
    return [r for r in db.runs.values() if r["pipeline_id"] == pipeline_id]


def versions_of_dataset(dataset_id):
    return [v for v in db.versions.values() if v["dataset_id"] == dataset_id]


def issues_of_dataset(dataset_id):
    return [i for i in db.issues.values() if i["dataset_id"] == dataset_id]


def live_version(dataset_id):
    for version in sort_rows(versions_of_dataset(dataset_id)):
        if version["status"] == "LIVE":
            return version
    return None


def metadata_of_dataset(dataset_id, statuses):
    return [
        m
        for m in sort_rows(db.metadata_records.values())
        if m["dataset_id"] == dataset_id and m["status"] in statuses
    ]


def assessments_of_dataset(dataset_id, statuses):
    return [
        a
        for a in sort_rows(db.assessments.values())
        if a["dataset_id"] == dataset_id and a["status"] in statuses
    ]


# --------------------------------------------------------------------------
# Dataset derived fields
# --------------------------------------------------------------------------
def variant_for(dataset):
    if dataset["publication_status"] in ("PUBLISHED", "UNDER_REMEDIATION"):
        return "AS_OBSERVED"
    return "AS_DECLARED"


def recompute_priority(dataset, variant=None):
    if variant is None:
        variant = variant_for(dataset)
    score = calc.priority_score(dataset, variant, db.requests)
    dataset["priority_score"] = score
    dataset["priority_score_variant"] = variant
    dataset["priority_tier"] = calc.priority_tier(score)
    touch(dataset)
    return score


def recompute_engagement(dataset):
    value = calc.engagement_index(dataset["usage_epochs"])
    dataset["engagement_index"] = value
    dataset["observed_demand_score"] = value
    touch(dataset)
    return value


def has_suspended_pipeline(dataset):
    return any(p["status"] == "SUSPENDED" for p in pipelines_of_dataset(dataset["id"]))


def recompute_currency(dataset):
    """Re-derive next_due_at, days_overdue and currency_status (PRD §3.9)."""
    before = dataset["currency_status"]
    due = calc.next_due_at(dataset["update_frequency"], dataset["last_published_at"])
    overdue = calc.days_overdue(due, now())
    clock = calc.clock_currency(
        due, overdue, dataset["priority_tier"], dataset["high_value_committed"], now()
    )
    floor = "STALE" if has_suspended_pipeline(dataset) else "CURRENT"
    dataset["next_due_at"] = due
    dataset["days_overdue"] = overdue
    dataset["currency_status"] = calc.more_severe(clock, floor)
    touch(dataset)
    return before, dataset["currency_status"]


def emit_staleness_alert(dataset):
    dataset["staleness_alert_count"] = dataset["staleness_alert_count"] + 1
    dataset["last_staleness_alert_at"] = now()
    touch(dataset)


# --------------------------------------------------------------------------
# Department derived fields (PRD §2.9)
# --------------------------------------------------------------------------
def recompute_department(department):
    if department is None:
        return False
    owned = datasets_of_department(department["id"])
    breached = 0
    stale = 0
    remediation = 0
    for dataset in owned:
        published = dataset["publication_status"] in calc.PUBLISHED_STATES
        if published and dataset["currency_status"] == "BREACHED":
            breached += 1
        if published and dataset["currency_status"] == "STALE":
            stale += 1
        if dataset["publication_status"] == "UNDER_REMEDIATION":
            remediation += 1
    overdue = 0
    owned_ids = set(d["id"] for d in owned)
    for issue in db.issues.values():
        if (
            issue["dataset_id"] in owned_ids
            and issue["status"] == "ACCEPTED"
            and issue["correction_breached"]
        ):
            overdue += 1
    points = (
        calc.BREACHED_WEIGHT * breached
        + calc.STALE_WEIGHT * stale
        + calc.REMEDIATION_WEIGHT * remediation
        + calc.OVERDUE_WEIGHT * overdue
    )
    before = department["compliance_posture"]
    department["breached_dataset_count"] = breached
    department["stale_dataset_count"] = stale
    department["remediation_dataset_count"] = remediation
    department["overdue_correction_count"] = overdue
    department["risk_points"] = points
    department["compliance_posture"] = calc.compliance_posture(points)
    touch(department)
    return before != department["compliance_posture"]


def recompute_department_of(dataset):
    return recompute_department(dept_of_dataset(dataset))


# --------------------------------------------------------------------------
# Member derived fields (PRD §3.7)
# --------------------------------------------------------------------------
def recompute_member(member, mutate=True):
    accepted = 0
    rejected = 0
    for issue in db.issues.values():
        if issue["reporter_member_id"] != member["id"]:
            continue
        if issue["status"] in ("ACCEPTED", "CORRECTED", "CLOSED"):
            accepted += 1
        elif issue["status"] == "REJECTED":
            rejected += 1
    showcases = 0
    for dataset in db.datasets.values():
        for entry in dataset["showcase_apps"]:
            if entry["submitter_member_id"] == member["id"] and entry["status"] == "APPROVED":
                showcases += 1
    epochs, score, weight = calc.reputation(
        accepted, rejected, showcases, member["last_credited_at"], now()
    )
    member["accepted_issue_count"] = accepted
    member["rejected_issue_count"] = rejected
    member["approved_showcase_count"] = showcases
    member["decay_epochs"] = epochs
    member["reputation_score"] = score
    member["vote_weight"] = weight
    member["status"] = (
        "THROTTLED" if (rejected - accepted) >= calc.THROTTLE_NET_REJECTS else "ACTIVE"
    )
    if mutate:
        touch(member)
    return member


# --------------------------------------------------------------------------
# Dataset request derived fields
# --------------------------------------------------------------------------
def recompute_request(request):
    total = 0
    for vote in request["votes"]:
        total += vote["weight"]
    request["weighted_vote_total"] = total
    request["demand_signal"] = calc.demand_signal(total)
    touch(request)


# --------------------------------------------------------------------------
# Version ledger
# --------------------------------------------------------------------------
def mint_version(dataset, change_type, row_count, notes=None, correction_issue_id=None,
                 source_run_id=None):
    predecessor = live_version(dataset["id"])
    version = new_row()
    index = dataset["version_index_high_water"] + 1
    version.update(
        {
            "dataset_id": dataset["id"],
            "source_run_id": source_run_id,
            "correction_issue_id": correction_issue_id,
            "supersedes_version_id": predecessor["id"] if predecessor else None,
            "version_index": index,
            "version_label": "v%d" % index,
            "change_type": change_type,
            "row_count": row_count,
            "notes": notes,
            "published_at": now(),
            "superseded_at": None,
            "retracted_at": None,
            "status": "LIVE",
        }
    )
    db.versions[version["id"]] = version
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        predecessor["superseded_at"] = now()
        touch(predecessor)
    dataset["version_index_high_water"] = index
    dataset["live_row_count"] = row_count
    dataset["last_published_at"] = now()
    touch(dataset)
    return version


# --------------------------------------------------------------------------
# Pipeline cascades (PRD §3.5, §3.6, §3.7)
# --------------------------------------------------------------------------
def skip_open_runs(pipeline, skip_reason):
    for run in sort_rows(runs_of_pipeline(pipeline["id"])):
        if run["status"] in ("SCHEDULED", "RETRY_QUEUED"):
            run["status"] = "SKIPPED"
            run["finished_at"] = now()
            run["skip_reason"] = skip_reason
            touch(run)


def release_escrow(pipeline, department):
    held = D(pipeline["escrowed_credit_units"])
    if department is not None:
        department["credit_balance_units"] = q2(D(department["credit_balance_units"]) + held)
        department["credits_escrowed_units"] = q2(D(department["credits_escrowed_units"]) - held)
        touch(department)
    pipeline["escrowed_credit_units"] = calc.ZERO


def suspend_pipeline(pipeline, reason):
    """ARMED -> SUSPENDED, with the full cascade of PRD §3.5."""
    dataset = db.datasets.get(pipeline["dataset_id"])
    runner = db.runners.get(pipeline["runner_id"])
    pipeline["status"] = "SUSPENDED"
    pipeline["suspend_reason"] = reason
    touch(pipeline)
    if runner is not None:
        runner["armed_window_count"] = max(0, runner["armed_window_count"] - 1)
        touch(runner)
    skip_open_runs(pipeline, "PIPELINE_SUSPENDED")
    if dataset is not None and dataset["publication_status"] in calc.PUBLISHED_STATES:
        recompute_currency(dataset)
        emit_staleness_alert(dataset)
        recompute_department_of(dataset)


def decommission_pipeline(pipeline, skip_reason):
    dataset = db.datasets.get(pipeline["dataset_id"])
    department = dept_of_dataset(dataset) if dataset is not None else None
    runner = db.runners.get(pipeline["runner_id"])
    origin = pipeline["status"]
    pipeline["status"] = "DECOMMISSIONED"
    touch(pipeline)
    if origin in ("ARMED", "SUSPENDED"):
        release_escrow(pipeline, department)
    if origin == "ARMED":
        if runner is not None:
            runner["armed_window_count"] = max(0, runner["armed_window_count"] - 1)
            touch(runner)
        skip_open_runs(pipeline, skip_reason)
    elif origin == "SUSPENDED":
        skip_open_runs(pipeline, skip_reason)
        if dataset is not None:
            recompute_currency(dataset)


# --------------------------------------------------------------------------
# Interval rules (PRD §3.5)
# --------------------------------------------------------------------------
def check_runner_exclusivity(pipeline):
    runner = db.runners.get(pipeline["runner_id"])
    cooldown = runner["cooldown_minutes"] if runner is not None else 0
    start = pipeline["window_start_minute"]
    end = pipeline["window_end_minute"]
    for other in db.pipelines.values():
        if other["id"] == pipeline["id"]:
            continue
        if other["runner_id"] != pipeline["runner_id"]:
            continue
        if other["status"] not in ("ARMED", "SUSPENDED"):
            continue
        occupied_start = other["window_start_minute"]
        occupied_end = other["window_end_minute"] + cooldown
        if start < occupied_end and occupied_start < end:
            err(
                "ERR_RUNNER_WINDOW_CONFLICT",
                "The requested window overlaps a reserved window on this runner.",
            )


def check_department_capacity(pipeline):
    dataset = db.datasets.get(pipeline["dataset_id"])
    if dataset is None:
        return
    department_id = dataset["department_id"]
    spans = []
    for other in db.pipelines.values():
        if other["id"] == pipeline["id"]:
            continue
        if other["status"] != "ARMED":
            continue
        other_dataset = db.datasets.get(other["dataset_id"])
        if other_dataset is None or other_dataset["department_id"] != department_id:
            continue
        spans.append((other["window_start_minute"], other["window_end_minute"]))
    candidate = (pipeline["window_start_minute"], pipeline["window_end_minute"])
    overlapping = 0
    for span in spans:
        if candidate[0] <= span[1] and span[0] <= candidate[1]:
            overlapping += 1
    if overlapping + 1 > calc.DEPARTMENT_WINDOW_CAP:
        err(
            "ERR_DEPARTMENT_WINDOW_CAPACITY",
            "The department already has the maximum number of armed windows over a shared minute.",
        )


# --------------------------------------------------------------------------
# Run settlement (PRD §3.6)
# --------------------------------------------------------------------------
def settle(run, pipeline, department):
    figures = calc.settle_run(run["rows_ingested"], run["alert_dispatched"])
    run.update(figures)
    total = figures["total_charge_credits"]
    held = D(pipeline["escrowed_credit_units"])
    drawn_escrow = held if held < total else total
    drawn_balance = q2(total - drawn_escrow)
    run["escrow_drawn_units"] = q2(drawn_escrow)
    run["balance_drawn_units"] = drawn_balance
    pipeline["escrowed_credit_units"] = q2(held - drawn_escrow)
    touch(pipeline)
    if department is not None:
        department["credits_escrowed_units"] = q2(
            D(department["credits_escrowed_units"]) - drawn_escrow
        )
        department["credit_balance_units"] = q2(
            D(department["credit_balance_units"]) - drawn_balance
        )
        department["credits_consumed_units"] = q2(
            D(department["credits_consumed_units"]) + total
        )
        touch(department)


# --------------------------------------------------------------------------
# Serialisers
# --------------------------------------------------------------------------
def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def department_out(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "code": row["code"],
            "contact_email": row["contact_email"],
            "credits_issued_units": num(row["credits_issued_units"]),
            "credit_balance_units": num(row["credit_balance_units"]),
            "credits_escrowed_units": num(row["credits_escrowed_units"]),
            "credits_consumed_units": num(row["credits_consumed_units"]),
            "breached_dataset_count": row["breached_dataset_count"],
            "stale_dataset_count": row["stale_dataset_count"],
            "remediation_dataset_count": row["remediation_dataset_count"],
            "overdue_correction_count": row["overdue_correction_count"],
            "risk_points": row["risk_points"],
            "compliance_posture": row["compliance_posture"],
        }
    )
    return out


def license_out(row):
    out = _common(row)
    out.update(
        {
            "code": row["code"],
            "name": row["name"],
            "attribution_required": row["attribution_required"],
            "commercial_use_allowed": row["commercial_use_allowed"],
            "share_alike": row["share_alike"],
            "attribution_text_template": row["attribution_text_template"],
            "reuse_permission_class": row["reuse_permission_class"],
            "retired": row["retired"],
        }
    )
    return out


def runner_out(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "cooldown_minutes": row["cooldown_minutes"],
            "armed_window_count": row["armed_window_count"],
            "status": row["status"],
        }
    )
    return out


def dataset_out(row):
    out = _common(row)
    out.update(
        {
            "department_id": row["department_id"],
            "title": row["title"],
            "slug": row["slug"],
            "description": row["description"],
            "update_frequency": row["update_frequency"],
            "column_count": row["column_count"],
            "sensitivity_class": row["sensitivity_class"],
            "public_demand_score": num(row["public_demand_score"]),
            "policy_value_score": num(row["policy_value_score"]),
            "embargo_until_utc": fmt_ts(row["embargo_until_utc"]),
            "aggregation_geography": row["aggregation_geography"],
            "engagement_index": num(row["engagement_index"]),
            "observed_demand_score": num(row["observed_demand_score"]),
            "priority_score": num(row["priority_score"]),
            "priority_score_variant": row["priority_score_variant"],
            "priority_tier": row["priority_tier"],
            "usage_epochs": [
                {
                    "epoch_index": e["epoch_index"],
                    "api_call_count": e["api_call_count"],
                    "download_count": e["download_count"],
                    "recorded_at": fmt_ts(e["recorded_at"]),
                }
                for e in row["usage_epochs"]
            ],
            "showcase_apps": [
                {
                    "label": s["label"],
                    "name": s["name"],
                    "url": s["url"],
                    "submitter_member_id": s["submitter_member_id"],
                    "status": s["status"],
                    "decided_at": fmt_ts(s["decided_at"]),
                }
                for s in row["showcase_apps"]
            ],
            "publication_status": row["publication_status"],
            "currency_status": row["currency_status"],
            "public_access_suspended": row["public_access_suspended"],
            "high_value_committed": row["high_value_committed"],
            "live_row_count": row["live_row_count"],
            "version_index_high_water": row["version_index_high_water"],
            "last_published_at": fmt_ts(row["last_published_at"]),
            "next_due_at": fmt_ts(row["next_due_at"]),
            "days_overdue": row["days_overdue"],
            "staleness_alert_count": row["staleness_alert_count"],
            "last_staleness_alert_at": fmt_ts(row["last_staleness_alert_at"]),
            "remediation_opened_at": fmt_ts(row["remediation_opened_at"]),
        }
    )
    return out


def metadata_out(row):
    out = _common(row)
    out.update(
        {
            "dataset_id": row["dataset_id"],
            "license_id": row["license_id"],
            "data_dictionary_field_count": row["data_dictionary_field_count"],
            "provenance_detail_lines": row["provenance_detail_lines"],
            "contact_email": row["contact_email"],
            "declared_update_frequency": row["declared_update_frequency"],
            "attribution_element_count": row["attribution_element_count"],
            "component_contributions": [num(c) for c in row["component_contributions"]],
            "completeness_score": num(row["completeness_score"]),
            "returned_reason": row["returned_reason"],
            "status": row["status"],
        }
    )
    return out


def assessment_out(row):
    out = _common(row)
    out.update(
        {
            "dataset_id": row["dataset_id"],
            "assessor_user_id": row["assessor_user_id"],
            "decided_by_user_id": row["decided_by_user_id"],
            "declared_quasi_identifier_count": row["declared_quasi_identifier_count"],
            "declared_smallest_cell_size": row["declared_smallest_cell_size"],
            "verified_smallest_cell_size": row["verified_smallest_cell_size"],
            "population_size": row["population_size"],
            "k_anonymity_k": row["k_anonymity_k"],
            "screening_risk_score": num(row["screening_risk_score"]),
            "clearance_risk_score": num(row["clearance_risk_score"]),
            "risk_score": num(row["risk_score"]),
            "aggregation_required": row["aggregation_required"],
            "min_aggregation_geography": row["min_aggregation_geography"],
            "block_reason": row["block_reason"],
            "status": row["status"],
        }
    )
    return out


def pipeline_out(row):
    out = _common(row)
    out.update(
        {
            "dataset_id": row["dataset_id"],
            "runner_id": row["runner_id"],
            "superseded_pipeline_id": row["superseded_pipeline_id"],
            "cadence": row["cadence"],
            "window_start_minute": row["window_start_minute"],
            "window_duration_minutes": row["window_duration_minutes"],
            "window_end_minute": row["window_end_minute"],
            "alert_email": row["alert_email"],
            "escrow_required_units": num(row["escrow_required_units"]),
            "escrowed_credit_units": num(row["escrowed_credit_units"]),
            "consecutive_failure_count": row["consecutive_failure_count"],
            "suspend_reason": row["suspend_reason"],
            "status": row["status"],
        }
    )
    return out


def run_out(row):
    out = _common(row)
    out.update(
        {
            "pipeline_id": row["pipeline_id"],
            "scheduled_for_utc": fmt_ts(row["scheduled_for_utc"]),
            "started_at": fmt_ts(row["started_at"]),
            "finished_at": fmt_ts(row["finished_at"]),
            "rows_ingested": row["rows_ingested"],
            "failure_code": row["failure_code"],
            "alert_dispatched": row["alert_dispatched"],
            "consecutive_failure_index": row["consecutive_failure_index"],
            "compute_credits": num(row["compute_credits"]),
            "alert_credits": num(row["alert_credits"]),
            "subtotal_credits": num(row["subtotal_credits"]),
            "reliability_discount_pct": num(row["reliability_discount_pct"]),
            "discount_credits": num(row["discount_credits"]),
            "total_charge_credits": num(row["total_charge_credits"]),
            "escrow_drawn_units": num(row["escrow_drawn_units"]),
            "balance_drawn_units": num(row["balance_drawn_units"]),
            "skip_reason": row["skip_reason"],
            "status": row["status"],
        }
    )
    return out


def version_out(row):
    out = _common(row)
    out.update(
        {
            "dataset_id": row["dataset_id"],
            "source_run_id": row["source_run_id"],
            "correction_issue_id": row["correction_issue_id"],
            "supersedes_version_id": row["supersedes_version_id"],
            "version_index": row["version_index"],
            "version_label": row["version_label"],
            "change_type": row["change_type"],
            "row_count": row["row_count"],
            "notes": row["notes"],
            "published_at": fmt_ts(row["published_at"]),
            "superseded_at": fmt_ts(row["superseded_at"]),
            "retracted_at": fmt_ts(row["retracted_at"]),
            "status": row["status"],
        }
    )
    return out


def issue_out(row):
    out = _common(row)
    out.update(
        {
            "dataset_id": row["dataset_id"],
            "reporter_member_id": row["reporter_member_id"],
            "resolution_version_id": row["resolution_version_id"],
            "severity": row["severity"],
            "category": row["category"],
            "description": row["description"],
            "triage_due_at": fmt_ts(row["triage_due_at"]),
            "triaged_at": fmt_ts(row["triaged_at"]),
            "accepted_at": fmt_ts(row["accepted_at"]),
            "correction_due_at": fmt_ts(row["correction_due_at"]),
            "triage_breached": row["triage_breached"],
            "correction_breached": row["correction_breached"],
            "reject_reason": row["reject_reason"],
            "status": row["status"],
        }
    )
    return out


def member_out(row):
    out = _common(row)
    out.update(
        {
            "email": row["email"],
            "display_name": row["display_name"],
            "organization": row["organization"],
            "accepted_issue_count": row["accepted_issue_count"],
            "rejected_issue_count": row["rejected_issue_count"],
            "approved_showcase_count": row["approved_showcase_count"],
            "last_credited_at": fmt_ts(row["last_credited_at"]),
            "decay_epochs": row["decay_epochs"],
            "reputation_score": num(row["reputation_score"]),
            "vote_weight": row["vote_weight"],
            "status": row["status"],
        }
    )
    return out


def request_out(row):
    out = _common(row)
    out.update(
        {
            "requester_member_id": row["requester_member_id"],
            "linked_dataset_id": row["linked_dataset_id"],
            "title": row["title"],
            "rationale": row["rationale"],
            "votes": [
                {
                    "member_id": v["member_id"],
                    "weight": v["weight"],
                    "cast_at": fmt_ts(v["cast_at"]),
                }
                for v in row["votes"]
            ],
            "weighted_vote_total": row["weighted_vote_total"],
            "demand_signal": num(row["demand_signal"]),
            "decision_note": row["decision_note"],
            "status": row["status"],
        }
    )
    return out
