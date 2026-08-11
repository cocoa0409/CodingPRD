"""Inbound mail: intake, matching, refusal, package acceptance, notification, imaging."""

import math

from flask import Blueprint, request

import calc
import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, listing, ok, touch
from store import DB, insert
from util import (
    CLOCK, MAX_SCAN_RETRIES, NOTIFICATION_SLA_HOURS, SCAN_JOB_MAX_PAGES,
    SCAN_REQUEST_MAX_PAGES, SCAN_TIER_MULTIPLIER, SOP_NOTIFICATION_SLA_HOURS,
    STATUS_ENUMS, add_hours, normalize_name, num_out,
)

bp = Blueprint("mail", __name__)


# ------------------------------------------------------------------ intake
@bp.post("/boxes/<ident>/mail-items")
@L.endpoint(roles=["CmraOperator"], primary="box")
def create_mail_item(box):
    b = L.body()
    # rung 6 -- a carrier_rule_id supplied in the body resolves
    carrier_rule_id = b.get("carrier_rule_id")
    if carrier_rule_id is not None:
        if not isinstance(carrier_rule_id, str) or carrier_rule_id not in DB.carrier_rules:
            raise ApiError("ERR_CARRIER_RULE_NOT_FOUND")
    addressee = L.req_str(b, "addressee_name")                      # rung 9
    L.req_present(b, "item_class")
    weight = L.req_num(b, "actual_weight_lb", minimum=0)
    length = L.req_num(b, "length_in", minimum=0)
    width = L.req_num(b, "width_in", minimum=0)
    height = L.req_num(b, "height_in", minimum=0)
    sig = L.req_bool(b, "signature_required", False)
    consent = L.req_bool(b, "interior_scan_consent", False)
    raw_class = b.get("item_class")
    if raw_class in ("PACKAGE", "SOP") and carrier_rule_id is None:
        L._bad("carrier_rule_id", "is required when item_class is PACKAGE or SOP")
    if raw_class in ("LETTER", "FLAT") and carrier_rule_id is not None:
        L._bad("carrier_rule_id", "is forbidden when item_class is LETTER or FLAT")
    item_class = L.enum_body(b, "item_class", "item_class")         # rung 10
    L.gate_b("mail_item_create", box)                               # rung 12

    row = insert(DB.mail_items, {
        "box_id": box["id"], "addressee_name": addressee, "matched_recipient_id": None,
        "item_class": item_class, "carrier_rule_id": carrier_rule_id,
        "signature_required": sig, "actual_weight_lb": weight,
        "length_in": length, "width_in": width, "height_in": height,
        "received_at": CLOCK.now, "accepted_at": None, "released_at": None,
        "handling_status": "RECEIVED", "storage_status": "FREE_WINDOW",
        "billing_status": "UNBILLED", "notification_status": "NOT_REQUIRED",
        "notification_due_at": None, "notified_at": None,
        "interior_scan_consent": consent, "forward_shipment_id": None,
        "billable_weight_lb": weight, "package_acceptance_fee_cents": None,
        "refusal_reason": None, "metered_storage_days": 0,
    })
    return created(S.mail_item(row))


@bp.get("/boxes/<ident>/mail-items")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def list_box_mail_items(box):
    handling = L.enum_query("handling_status", "handling_status")
    storage = L.enum_query("storage_status", "storage_status")
    data = store.mail_items_of_box(box["id"])
    if handling is not None:
        data = [m for m in data if m["handling_status"] == handling]
    if storage is not None:
        data = [m for m in data if m["storage_status"] == storage]
    items, total, limit, offset = L.paginate(data, S.mail_item)
    return listing(items, total, limit, offset)


@bp.get("/mail-items")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer"])
def list_mail_items():
    handling = L.enum_query("handling_status", "handling_status")
    item_class = L.enum_query("item_class", "item_class")
    data = store.rows(DB.mail_items)
    for key in ("box_id", "matched_recipient_id", "carrier_rule_id", "forward_shipment_id"):
        val = request.args.get(key)
        if val is not None:
            data = [m for m in data if m[key] == val]
    if handling is not None:
        data = [m for m in data if m["handling_status"] == handling]
    if item_class is not None:
        data = [m for m in data if m["item_class"] == item_class]
    items, total, limit, offset = L.paginate(data, S.mail_item)
    return listing(items, total, limit, offset)


@bp.get("/mail-items/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder", "Recipient"],
            primary="mail_item", scope=True)
def read_mail_item(item):
    return ok(S.mail_item(item))


@bp.post("/mail-items/<ident>/match")
@L.endpoint(roles=["CmraOperator"], primary="mail_item")
def match_mail_item(item):
    b = L.body()
    recipient_id = b.get("recipient_id")                            # rung 7
    if recipient_id is not None:
        if not isinstance(recipient_id, str) or recipient_id not in DB.recipients:
            raise ApiError("ERR_RECIPIENT_NOT_FOUND")
    recipient_id = L.req_str(b, "recipient_id")                     # rung 9
    box = store.box_of_item(item)
    L.gate_b("mail_item_match", box)                                # rung 12
    if item["handling_status"] != "RECEIVED":                       # rung 14
        raise ApiError("ERR_INVALID_STATE")
    r = DB.recipients[recipient_id]                                 # rung 16
    if r["box_id"] != item["box_id"] or r["roster_status"] == "REMOVED":
        raise ApiError("ERR_RECIPIENT_NOT_ON_ROSTER")
    target = normalize_name(item["addressee_name"])
    names = [normalize_name(r["legal_name"])] + [normalize_name(a)
                                                 for a in (r["dba_aliases"] or [])]
    if target not in names:
        raise ApiError("ERR_RECIPIENT_NOT_ON_ROSTER")
    item["matched_recipient_id"] = r["id"]
    item["handling_status"] = "HELD" if r["release_eligibility"] == "RELEASABLE" \
        else "AWAITING_CLEARANCE"
    touch(item)
    return ok(S.mail_item(item))


@bp.post("/mail-items/<ident>/refuse")
@L.endpoint(roles=["CmraOperator"], primary="mail_item")
def refuse_mail_item(item):
    b = L.body()
    L.req_present(b, "refusal_reason")
    reason = L.enum_body(b, "refusal_reason", "refusal_reason")
    L.gate_b("mail_item_refuse", store.box_of_item(item))
    if item["handling_status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    item["handling_status"] = "REFUSED"
    item["refusal_reason"] = reason
    domain.end_custody(item)
    if item["billing_status"] == "UNBILLED":
        item["billing_status"] = "WRITTEN_OFF"
    touch(item)
    return ok(S.mail_item(item))


@bp.post("/mail-items/<ident>/package-acceptance")
@L.endpoint(roles=["CmraOperator"], primary="mail_item")
def accept_package(item):
    box = store.box_of_item(item)
    L.gate_b("package_acceptance", box)                             # rung 12
    if item["item_class"] not in ("PACKAGE", "SOP") or item["accepted_at"] is not None:
        raise ApiError("ERR_INVALID_STATE")                         # rung 14
    ra = store.active_ra(box["id"]) if box else None
    if item["item_class"] == "SOP" and ra is None:                  # rung 20
        raise ApiError("ERR_RA_SERVICE_REQUIRED")
    if item["signature_required"]:                                  # rung 22
        r = store.recipient(item["matched_recipient_id"]) if item["matched_recipient_id"] else None
        if r is None or not r["signature_authorization_on_file"]:
            raise ApiError("ERR_SIGNATURE_AUTHORIZATION_MISSING")
    rule = DB.carrier_rules.get(item["carrier_rule_id"])
    if rule is None:
        raise ApiError("ERR_INVALID_STATE", "The piece carries no carrier rule.")
    if item["signature_required"] and not rule["accepts_signature_required"]:   # rung 23
        raise ApiError("ERR_CARRIER_NOT_ACCEPTED")
    if calc.is_oversize(item, rule):                                # rung 24
        raise ApiError("ERR_PACKAGE_OVERSIZE")

    item["billable_weight_lb"] = calc.billable_weight(item, rule)
    item["package_acceptance_fee_cents"] = calc.acceptance_fee(item, rule,
                                                               item["billable_weight_lb"])
    item["accepted_at"] = CLOCK.now
    hours = SOP_NOTIFICATION_SLA_HOURS if (item["item_class"] == "SOP" and ra is not None) \
        else NOTIFICATION_SLA_HOURS
    item["notification_status"] = "PENDING"
    item["notification_due_at"] = add_hours(item["accepted_at"], hours)
    touch(item)
    return ok(S.mail_item(item))


@bp.post("/mail-items/<ident>/notify")
@L.endpoint(roles=["CmraOperator"], primary="mail_item")
def notify_mail_item(item):
    box = store.box_of_item(item)
    L.gate_b("mail_item_notify", box)                               # rung 12
    if item["notification_status"] != "PENDING":                    # rung 14
        raise ApiError("ERR_INVALID_STATE")
    if item["item_class"] == "SOP" and store.active_ra(box["id"]) is None:   # rung 20
        raise ApiError("ERR_RA_SERVICE_REQUIRED")
    item["notification_status"] = "SENT"
    item["notified_at"] = CLOCK.now
    touch(item)
    return ok(S.mail_item(item))


@bp.get("/mail-items/<ident>/usage-entries")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="mail_item", scope=True)
def list_item_usage(item):
    unit = L.enum_query("unit_type", "unit_type")
    data = [e for e in store.entries_of_item(item["id"])
            if unit is None or e["unit_type"] == unit]
    items, total, limit, offset = L.paginate(data, S.usage_entry)
    return listing(items, total, limit, offset)


# ------------------------------------------------------------------ imaging
@bp.post("/mail-items/<ident>/scan-jobs")
@L.endpoint(roles=["BoxHolder"], primary="mail_item", scope=True)
def create_scan_jobs(item):
    b = L.body()
    L.req_present(b, "scan_tier")                                   # rung 9
    pages = L.req_int(b, "requested_pages", 1, SCAN_REQUEST_MAX_PAGES)
    tier = L.enum_body(b, "scan_tier", "scan_tier")                 # rung 10
    box = store.box_of_item(item)
    L.gate_a("scan_jobs_create", box, mail_item=item, scan_tier=tier)   # rung 11
    L.gate_b("scan_jobs_create", box)                               # rung 12
    if tier in ("INTERIOR", "OCR"):                                 # rungs 17-19
        L.gate_c_item(item)
    if item["item_class"] == "SOP" and store.active_ra(box["id"]) is None:   # rung 20
        raise ApiError("ERR_RA_SERVICE_REQUIRED")
    if tier in ("INTERIOR", "OCR") and not item["interior_scan_consent"]:    # rung 21
        raise ApiError("ERR_SCAN_CONSENT_REQUIRED")

    job_count = int(math.ceil(pages / float(SCAN_JOB_MAX_PAGES)))
    first = None
    for i in range(1, job_count + 1):
        page_count = SCAN_JOB_MAX_PAGES if i < job_count \
            else pages - (job_count - 1) * SCAN_JOB_MAX_PAGES
        row = insert(DB.scan_jobs, {
            "mail_item_id": item["id"], "scan_tier": tier, "requested_pages": pages,
            "split_index": i, "split_group_size": job_count, "page_count": page_count,
            "status": "QUEUED", "retry_count": 0,
            "billed_pages_in_tier": None, "billed_pages_overage": None,
            "charge_cents": None,
        })
        if i == 1:
            first = row
    return created(S.scan_job(first))


@bp.get("/mail-items/<ident>/scan-jobs")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder", "Recipient"],
            primary="mail_item", scope=True)
def list_scan_jobs(item):
    status = L.enum_query("status", members=STATUS_ENUMS["scan_job"])
    # Not an enum-valued query filter per rung 10's closed list.
    tier = request.args.get("scan_tier")
    data = [j for j in store.scan_jobs_of_item(item["id"])]
    if status is not None:
        data = [j for j in data if j["status"] == status]
    if tier is not None:
        data = [j for j in data if j["scan_tier"] == tier]
    data.sort(key=lambda j: (j["created_at"], j["split_index"], j["id"]))
    items, total, limit, offset = L.paginate(data, S.scan_job)
    return listing(items, total, limit, offset)


@bp.post("/scan-jobs/<ident>/start")
@L.endpoint(roles=["CmraOperator"], primary="scan_job")
def start_scan_job(job):
    L.gate_b("scan_job_start", store.box_of_scan_job(job))
    if job["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE")
    job["status"] = "IN_PROGRESS"
    touch(job)
    return ok(S.scan_job(job))


@bp.post("/scan-jobs/<ident>/complete")
@L.endpoint(roles=["CmraOperator"], primary="scan_job")
def complete_scan_job(job):
    item = store.mail_item(job["mail_item_id"])
    box = store.box_of_item(item)
    L.gate_b("scan_job_complete", box)
    if job["status"] != "IN_PROGRESS":                              # rung 14
        raise ApiError("ERR_INVALID_STATE")
    sop = item["item_class"] == "SOP"
    if not sop:
        domain.raise_quota(box, "SCAN_PAGE", job["page_count"])     # rung 36

    if sop:
        job["billed_pages_in_tier"] = 0
        job["billed_pages_overage"] = 0
        job["charge_cents"] = 0
    else:
        tier = store.tier_of_box(box)
        cycle = store.open_cycle(box["id"])
        consumed = cycle["scan_pages_consumed"] if cycle else 0
        remaining = max(0, tier["included_scan_pages"] - consumed)
        in_tier = min(job["page_count"], remaining)
        overage = job["page_count"] - in_tier
        job["billed_pages_in_tier"] = in_tier
        job["billed_pages_overage"] = overage
        # Adjudication of friction 3 (reading B): the OCR tier multiplier lives
        # on the job's charge_cents only.  The ledger entry keeps the literal
        # declaration `unit_rate_cents == the tier's overage rate for the unit
        # type`, so every declared formula stays observable.
        job["charge_cents"] = (overage * tier["overage_scan_page_cents"]
                               * SCAN_TIER_MULTIPLIER[job["scan_tier"]])
        domain.meter(box, "SCAN_PAGE", job["page_count"], "SCAN_COMPLETED", mail_item=item)
    job["status"] = "COMPLETED"
    touch(job)
    return ok(S.scan_job(job))


@bp.post("/scan-jobs/<ident>/fail")
@L.endpoint(roles=["CmraOperator"], primary="scan_job")
def fail_scan_job(job):
    L.gate_b("scan_job_fail", store.box_of_scan_job(job))
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    job["status"] = "FAILED" if job["retry_count"] < MAX_SCAN_RETRIES else "ABANDONED"
    touch(job)
    return ok(S.scan_job(job))


@bp.post("/scan-jobs/<ident>/retry")
@L.endpoint(roles=["CmraOperator"], primary="scan_job")
def retry_scan_job(job):
    L.gate_b("scan_job_retry", store.box_of_scan_job(job))
    if job["status"] not in ("FAILED", "ABANDONED"):                # rung 14
        raise ApiError("ERR_INVALID_STATE")
    if job["status"] == "ABANDONED":                                # rung 28
        raise ApiError("ERR_SCAN_RETRY_EXHAUSTED")
    job["status"] = "QUEUED"
    job["retry_count"] += 1
    touch(job)
    return ok(S.scan_job(job))
