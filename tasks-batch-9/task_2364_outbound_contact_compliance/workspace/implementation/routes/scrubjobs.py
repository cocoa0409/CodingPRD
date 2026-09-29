"""Scrub queueing and execution (§3.4)."""

from flask import Blueprint

import lookup
import validation as v
from calculations import LIST_REFRESH_MAX_DAYS, SCRUB_VALIDITY_DAYS
from db import base_row, by_created_at, db, now, public, touch
from derive import jobs_of_campaign, recompute_campaign, rows, touch_campaign
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import add_days, dt_of, iso

bp = Blueprint("scrubjobs", __name__)

LIST_TYPES = ("NATIONAL", "STATE", "INTERNAL")
JOB_STATUSES = ("PENDING", "COMPLETED", "FAILED", "SUPERSEDED", "INVALIDATED")


@bp.post("/compliance/scrub-jobs")
@endpoint(["CampaignManager", "ComplianceOfficer"])
def queue_job():
    body = payload()
    campaign_id = v.req_str(body, "campaign_id")
    list_types = v.req_str_list(body, "list_types", min_len=1, allowed=LIST_TYPES, unique=True)
    expected_campaign_version = v.req_int(body, "expected_campaign_version")

    campaign = lookup.campaign(campaign_id)
    recompute_campaign(campaign)
    if expected_campaign_version != campaign["version"]:
        raise ApiError(
            "ERR_STALE_CAMPAIGN_VERSION",
            "expected_campaign_version does not match the campaign's current version.",
        )
    if campaign["status"] not in ("DRAFT", "PENDING_LAUNCH"):
        raise ApiError(
            "ERR_CAMPAIGN_STATE_INVALID",
            "A scrub may only be queued against a DRAFT or PENDING_LAUNCH campaign.",
        )

    row = base_row()
    row.update(
        {
            "campaign_id": campaign_id,
            "list_types": list(list_types),
            "status": "PENDING",
            "requested_at": row["created_at"],
            "completed_at": None,
            "expires_at": None,
            "contacts_scrubbed_count": 0,
            "contacts_suppressed_count": 0,
            "eligible_target_count": 0,
            "failure_reason": None,
            "invalidation_reason": None,
        }
    )
    db.scrub_jobs[row["id"]] = row
    touch_campaign(campaign)
    return created(public(row))


@bp.get("/compliance/scrub-jobs/<job_id>")
@endpoint(["CampaignManager", "ComplianceOfficer", "PlatformAdmin"])
def read_job(job_id):
    return ok(public(lookup.scrub_job(job_id)))


def _external_lists_current(job, campaign):
    stamp = now()
    floor = add_days(stamp, -LIST_REFRESH_MAX_DAYS)
    for family in ("NATIONAL", "STATE"):
        if family not in job["list_types"]:
            continue
        found = False
        for entry in rows("suppression_entries"):
            if entry["status"] != "ACTIVE" or entry["list_type"] != family:
                continue
            if dt_of(entry["source_refreshed_at"]) < floor:
                continue
            if family == "STATE" and entry.get("state_code") not in campaign["target_state_codes"]:
                continue
            found = True
            break
        if not found:
            return False
    return True


def _resolve_targets(job, campaign):
    scrubbed = 0
    suppressed = 0
    entries = [e for e in rows("suppression_entries") if e["status"] == "ACTIVE"]
    for contact in rows("contacts"):
        if contact["state_code"] not in campaign["target_state_codes"]:
            continue
        scrubbed += 1
        for entry in entries:
            if entry["list_type"] not in job["list_types"]:
                continue
            if entry["phone_number"] != contact["phone_number"]:
                continue
            if entry["list_type"] == "STATE" and entry.get("state_code") != contact["state_code"]:
                continue
            suppressed += 1
            break
    return scrubbed, suppressed


@bp.post("/compliance/scrub-jobs/<job_id>/execute")
@endpoint(["CampaignManager", "ComplianceOfficer"])
def execute_job(job_id):
    payload()
    job = lookup.scrub_job(job_id)
    campaign = db.campaigns.get(job["campaign_id"])
    if campaign is None:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND")
    if campaign["status"] not in ("DRAFT", "PENDING_LAUNCH"):
        raise ApiError(
            "ERR_CAMPAIGN_STATE_INVALID",
            "A scrub may only run against a DRAFT or PENDING_LAUNCH campaign.",
        )
    if job["status"] != "PENDING":
        raise ApiError("ERR_SCRUB_JOB_STATE_INVALID", "Only a PENDING scrub job may be executed.")

    if not _external_lists_current(job, campaign):
        job["status"] = "FAILED"
        job["failure_reason"] = "STALE_OR_EMPTY_LIST"
        touch(job)
        touch_campaign(campaign)
        return ok(public(job))

    scrubbed, suppressed = _resolve_targets(job, campaign)
    completed_at = now()
    job["status"] = "COMPLETED"
    job["contacts_scrubbed_count"] = scrubbed
    job["contacts_suppressed_count"] = suppressed
    job["eligible_target_count"] = scrubbed - suppressed
    job["completed_at"] = iso(completed_at)
    job["expires_at"] = iso(add_days(completed_at, SCRUB_VALIDITY_DAYS))
    touch(job)

    for sibling in by_created_at(jobs_of_campaign(campaign["id"])):
        if sibling["id"] == job["id"]:
            continue
        if sibling["status"] == "COMPLETED":
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    if campaign["status"] == "DRAFT":
        campaign["status"] = "PENDING_LAUNCH"
    touch_campaign(campaign)
    return ok(public(job))


@bp.get("/compliance/campaigns/<campaign_id>/scrub-jobs")
@endpoint(["CampaignManager", "ComplianceOfficer", "PlatformAdmin"])
def list_campaign_jobs(campaign_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", JOB_STATUSES)
    lookup.campaign(campaign_id)

    matches = jobs_of_campaign(campaign_id)
    if status is not None:
        matches = [j for j in matches if j["status"] == status]
    matches = by_created_at(matches)
    matches.sort(key=lambda j: j["requested_at"], reverse=True)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(j) for j in page], limit, offset, total)
