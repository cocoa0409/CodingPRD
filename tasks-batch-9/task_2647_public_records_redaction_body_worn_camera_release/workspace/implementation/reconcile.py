"""Derived-field reconciliation (PRD 2.7).

Every count, sum and posture field is defined as a query over the current rows.
This module re-runs every one of those queries after each write so that no
incremental bookkeeping can drift.  Frozen fields -- estimated_review_minutes,
estimated_redaction_minutes, statutory_deadline_at, tolled_days, deposit_due_at,
invoiced_total_cents, every FeeEstimate / DenialLetter / ReleasePackage money
field, and both status dimensions -- are deliberately never touched here.
"""
import calc
from db import store


def _reconcile_tasks():
    for task in store.all("redaction_tasks"):
        if task["status"] != "APPROVED":
            task["approved_labor_minutes"] = 0


def _reconcile_records():
    for record in store.all("responsive_records"):
        claims = calc.claims_of_record(record["id"])
        record["release_posture"] = calc.record_release_posture(record)
        presumptive, adjudicated = calc.record_burdens(record)
        record["presumptive_burden_minutes"] = presumptive
        record["adjudicated_burden_minutes"] = adjudicated
        record["unadjudicated_claim_count"] = sum(
            1 for claim in claims if claim["status"] == "ASSERTED")
        approved = [task for task in calc.tasks_of_record(record["id"])
                    if task["status"] == "APPROVED"]
        record["approved_labor_minutes"] = sum(
            task["approved_labor_minutes"] for task in approved)
        record["redacted_segment_ms"] = sum(
            task["clip_end_ms"] - task["clip_start_ms"] for task in approved)


def _reconcile_requests():
    for request in store.all("requests"):
        records = calc.records_of_request(request["id"])
        request["is_critical_incident"] = calc.request_is_critical_incident(request)
        request["responsive_record_count"] = sum(
            1 for row in records if row["inclusion_status"] != "EXCLUDED")
        request["unadjudicated_claim_count"] = sum(
            1 for claim in calc.claims_of_request(request["id"])
            if claim["status"] == "ASSERTED")
        request["open_notification_count"] = calc.open_notification_count(request["id"])
        request["billable_labor_minutes"] = sum(
            row["approved_labor_minutes"] for row in records)
        figures = calc.ledger_figures(request["id"])
        for key, value in figures.items():
            request[key] = value
        # PRD 3.8: the request's figures "mirror the new estimate's corresponding
        # figures -- and are 0 whenever no ACTIVE estimate exists".
        active = [row for row in calc.estimates_of_request(request["id"])
                  if row["status"] == "ACTIVE"]
        if active:
            estimate = active[-1]
            request["estimated_total_cents"] = estimate["estimated_total_cents"]
            request["deposit_required_cents"] = estimate["deposit_required_cents"]
        else:
            request["estimated_total_cents"] = 0
            request["deposit_required_cents"] = 0


def _reconcile_assets():
    for asset in store.all("video_assets"):
        asset["depicted_individual_count"] = len(
            calc.individuals_of_asset(asset["id"]))
        holds = calc.active_holds_for_incident(asset["incident_number"])
        held_by_open_request = False
        for record in store.all("responsive_records"):
            if record["video_asset_id"] != asset["id"]:
                continue
            if record["inclusion_status"] not in (
                    "CANDIDATE", "RESPONSIVE", "WITHHELD_IN_FULL"):
                continue
            request = store.get("requests", record["request_id"])
            if request is None:
                continue
            if request["processing_status"] not in calc.OPEN_PROCESSING_EXCLUDED:
                held_by_open_request = True
                break
        asset["retention_locked"] = bool(holds) or held_by_open_request
        if asset["disposition_state"] == "PURGED":
            continue
        if holds:
            # The matching ACTIVE hold with the smallest created_at.
            chosen = sorted(holds, key=lambda row: row["_seq"])[0]
            asset["disposition_state"] = "SUSPENDED"
            asset["suspended_by_hold_id"] = chosen["id"]
        else:
            asset["disposition_state"] = "SCHEDULED"
            asset["suspended_by_hold_id"] = None


def _reconcile_holds():
    counts = {}
    for asset in store.all("video_assets"):
        hold_id = asset.get("suspended_by_hold_id")
        if hold_id:
            counts[hold_id] = counts.get(hold_id, 0) + 1
    for hold in store.all("litigation_holds"):
        hold["suspended_asset_count"] = counts.get(hold["id"], 0)


def _reconcile_directory():
    open_counts = {}
    for request in store.all("requests"):
        if request["processing_status"] in calc.OPEN_PROCESSING_EXCLUDED:
            continue
        key = request["requester_id"]
        open_counts[key] = open_counts.get(key, 0) + 1
    for requester in store.all("requesters"):
        requester["open_request_count"] = open_counts.get(requester["id"], 0)

    qa_counts = {}
    for task in store.all("redaction_tasks"):
        if task["status"] != "QA_PENDING":
            continue
        reviewer_id = task.get("qa_reviewer_id")
        if reviewer_id:
            qa_counts[reviewer_id] = qa_counts.get(reviewer_id, 0) + 1
    for member in store.all("staff"):
        member["open_qa_assignment_count"] = qa_counts.get(member["id"], 0)


def reconcile_all():
    """Bring every derived field into agreement.  Idempotent by construction."""
    _reconcile_tasks()
    _reconcile_records()
    _reconcile_assets()
    _reconcile_holds()
    _reconcile_requests()
    _reconcile_directory()
