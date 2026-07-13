"""All HTTP routes. Validation follows the pinned order of PRD 2.5."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
import validate as v
from auth import authorize, require_account
from errors import ApiError
from response import created, listing, ok
from store import (base_fields, db, dump, dump_all, iso, mutate, now, parse_dt,
                   set_clock)

bp = Blueprint("api", __name__)

PLAN_TIERS = ("FREE", "ESSENTIALS", "STANDARD", "PREMIUM")
USER_ROLES = ("CAMPAIGN_AUTHOR", "COMPLIANCE_APPROVER", "DUAL")
CONSENT_SOURCES = ("SIGNUP_FORM", "IMPORT", "API", "MANUAL")
SEGMENT_CONSENT_STATES = ("PENDING", "CONFIRMED", "UNSUBSCRIBED")
TRIGGER_EVENTS = ("SUBSCRIBE_CONFIRMED", "CAMPAIGN_CLICK")
STEP_KINDS = ("WAIT", "EMAIL", "CONDITION")
EVENT_KINDS = ("DELIVERED", "SOFT_BOUNCE", "HARD_BOUNCE", "COMPLAINT", "OPEN", "CLICK")
DECISIONS = ("APPROVE", "REQUEST_CHANGES")

ALL_ROLES = ("PlatformAdmin", "CampaignAuthor", "ComplianceApprover")


# --------------------------------------------------------------------------
# Lookup helpers (validation priorities 5 and 6)
# --------------------------------------------------------------------------
def find(table, key, err):
    row = table.get(key)
    if row is None:
        raise ApiError(err)
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: r["created_at"])


def scope_filter(ctx, rows, account_of):
    """Tenant isolation on list endpoints for the entity-backed roles."""
    if not ctx.scoped:
        return rows
    return [r for r in rows if account_of(r) == ctx.account_id]


# ==========================================================================
# Accounts
# ==========================================================================
@bp.post("/accounts")
def create_account():
    ctx = authorize(("PlatformAdmin",))
    data = v.body()
    name = v.req_str(data, "name", 1, 120)
    plan_tier = v.opt_enum(data, "plan_tier", PLAN_TIERS, "FREE")
    grant = v.opt_int(data, "initial_send_credits", 0, minimum=0)
    capacity = v.opt_int(data, "hourly_send_capacity", 1000, minimum=1)

    acct = base_fields()
    acct.update({
        "name": name,
        "plan_tier": plan_tier,
        "status": "ACTIVE",
        "suspension_reason": None,
        "hourly_send_capacity": capacity,
        "granted_send_credits": grant,
        "send_credit_balance": grant,
        "reserved_send_credits": 0,
        "consumed_send_credits": 0,
        "billable_contact_count": 0,
        "sender_reputation_score": 100,
    })
    db.accounts[acct["id"]] = acct
    svc.create_billing_cycle(acct["id"], now(), 0)
    return created(dump("account", acct))


@bp.get("/accounts/<aid>")
def get_account(aid):
    ctx = authorize(ALL_ROLES)
    acct = find(db.accounts, aid, "ERR_ACCOUNT_NOT_FOUND")
    require_account(ctx, acct["id"])
    return ok(dump("account", acct))


@bp.post("/accounts/<aid>/users")
def create_account_user(aid):
    ctx = authorize(("PlatformAdmin",))
    data = v.body()
    email = v.req_email(data, "email")
    user_role = v.req_enum(data, "user_role", USER_ROLES)
    acct = find(db.accounts, aid, "ERR_ACCOUNT_NOT_FOUND")
    for u in db.account_users.values():
        if u["account_id"] == acct["id"] and u["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "Email must be unique within the account.")
    user = base_fields()
    user.update({"account_id": acct["id"], "email": email, "user_role": user_role})
    db.account_users[user["id"]] = user
    return created(dump("account_user", user))


@bp.get("/accounts/<aid>/users")
def list_account_users(aid):
    ctx = authorize(("PlatformAdmin",))
    limit, offset = v.pagination()
    acct = find(db.accounts, aid, "ERR_ACCOUNT_NOT_FOUND")
    rows = [u for u in db.account_users.values() if u["account_id"] == acct["id"]]
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("account_user", page), limit, offset, total)


@bp.get("/accounts/<aid>/billing-cycles")
def list_billing_cycles(aid):
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    limit, offset = v.pagination()
    acct = find(db.accounts, aid, "ERR_ACCOUNT_NOT_FOUND")
    require_account(ctx, acct["id"])
    rows = [c for c in db.billing_cycles.values() if c["account_id"] == acct["id"]]
    status = request.args.get("status")
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = sorted(rows, key=lambda c: c["period_start"])
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("billing_cycle", page), limit, offset, total)


@bp.get("/accounts/<aid>/suppressions")
def list_suppressions(aid):
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    limit, offset = v.pagination()
    acct = find(db.accounts, aid, "ERR_ACCOUNT_NOT_FOUND")
    require_account(ctx, acct["id"])
    rows = [e for e in db.suppressions.values() if e["account_id"] == acct["id"]]
    email = request.args.get("email")
    if email:
        rows = [e for e in rows if e["email"] == email]
    reason = request.args.get("reason")
    if reason:
        rows = [e for e in rows if e["reason"] == reason]
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("suppression", page), limit, offset, total)


# ==========================================================================
# Audiences
# ==========================================================================
@bp.post("/audiences")
def create_audience():
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    data = v.body()
    account_id = v.req_str(data, "account_id")
    name = v.req_str(data, "name", 1, 120)
    from_email = v.req_email(data, "default_from_email")
    double_optin = v.opt_bool(data, "double_optin_required", True)
    acct = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    require_account(ctx, acct["id"])

    aud = base_fields()
    aud.update({
        "account_id": acct["id"],
        "name": name,
        "double_optin_required": double_optin,
        "default_from_email": from_email,
        "subscriber_count": 0,
    })
    db.audiences[aud["id"]] = aud
    return created(dump("audience", aud))


@bp.get("/audiences/<aid>")
def get_audience(aid):
    ctx = authorize(ALL_ROLES)
    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])
    return ok(dump("audience", aud))


@bp.get("/audiences")
def list_audiences():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.audiences.values())
    account_id = request.args.get("account_id")
    if account_id:
        rows = [a for a in rows if a["account_id"] == account_id]
    rows = scope_filter(ctx, rows, lambda a: a["account_id"])
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("audience", page), limit, offset, total)


# ==========================================================================
# Subscribers
# ==========================================================================
@bp.post("/audiences/<aid>/subscribers")
def create_subscriber(aid):
    ctx = authorize(("Anonymous", "CampaignAuthor", "PlatformAdmin"))
    data = v.body()
    email = v.req_email(data, "email")
    consent_source = v.req_enum(data, "consent_source", CONSENT_SOURCES)
    first_name = v.opt_str(data, "first_name", None)
    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])
    acct = db.accounts[aud["account_id"]]

    # Suppression is checked first (priority 18), then duplication (priority 20).
    if svc.suppression_for(acct["id"], email) is not None:
        raise ApiError("ERR_EMAIL_SUPPRESSED")
    for s in db.subscribers.values():
        if s["audience_id"] == aud["id"] and s["email"] == email:
            raise ApiError("ERR_SUBSCRIBER_EXISTS")

    sub = svc.create_subscriber(aud, email, first_name, consent_source)
    if sub["consent_state"] == "CONFIRMED":
        svc.fire_enrollments(sub, "SUBSCRIBE_CONFIRMED")
    svc.cascade_consent_change(sub)
    return created(dump("subscriber", sub))


@bp.get("/subscribers/<sid>")
def get_subscriber(sid):
    ctx = authorize(ALL_ROLES)
    sub = find(db.subscribers, sid, "ERR_SUBSCRIBER_NOT_FOUND")
    require_account(ctx, svc.audience_of_subscriber(sub)["account_id"])
    return ok(dump("subscriber", sub))


@bp.get("/subscribers")
def list_subscribers():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.subscribers.values())
    audience_id = request.args.get("audience_id")
    if audience_id:
        rows = [s for s in rows if s["audience_id"] == audience_id]
    consent_state = request.args.get("consent_state")
    if consent_state:
        rows = [s for s in rows if s["consent_state"] == consent_state]
    engagement_state = request.args.get("engagement_state")
    if engagement_state:
        rows = [s for s in rows if s["engagement_state"] == engagement_state]
    rows = scope_filter(
        ctx, rows, lambda s: svc.audience_of_subscriber(s)["account_id"])
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("subscriber", page), limit, offset, total)


@bp.post("/subscribers/<sid>/confirm")
def confirm_subscriber(sid):
    authorize(("Anonymous",))
    data = v.body()
    token = v.req_str(data, "confirmation_token")
    sub = find(db.subscribers, sid, "ERR_SUBSCRIBER_NOT_FOUND")

    if sub["consent_state"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    if sub["confirmation_token"] is None or token != sub["confirmation_token"]:
        raise ApiError("ERR_INVALID_CONFIRMATION_TOKEN")
    deadline = sub["created_at"] + timedelta(hours=calc.CONFIRMATION_TOKEN_TTL_HOURS)
    if not now() < deadline:
        raise ApiError("ERR_CONFIRMATION_EXPIRED")

    sub["consent_state"] = "CONFIRMED"
    sub["consent_confirmed_at"] = now()
    sub["confirmation_token"] = None
    mutate(sub)
    svc.fire_enrollments(sub, "SUBSCRIBE_CONFIRMED")
    # subscriber_count does not move: a PENDING contact was already counted.
    svc.cascade_consent_change(sub)
    return ok(dump("subscriber", sub))


@bp.post("/subscribers/<sid>/unsubscribe")
def unsubscribe_subscriber(sid):
    ctx = authorize(("Anonymous", "CampaignAuthor"))
    data = v.body()
    token = v.req_str(data, "unsubscribe_token")
    sub = find(db.subscribers, sid, "ERR_SUBSCRIBER_NOT_FOUND")
    aud = svc.audience_of_subscriber(sub)
    require_account(ctx, aud["account_id"])

    if sub["consent_state"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_ALREADY_UNSUBSCRIBED")
    if token != sub["unsubscribe_token"]:
        raise ApiError("ERR_INVALID_UNSUBSCRIBE_TOKEN")

    sub["consent_state"] = "UNSUBSCRIBED"
    sub["unsubscribed_at"] = now()
    mutate(sub)
    svc.add_suppression(aud["account_id"], sub["email"], "UNSUBSCRIBE")
    # subscriber_count is untouched: an UNSUBSCRIBED contact remains billable.
    svc.cascade_consent_change(sub)
    return ok(dump("subscriber", sub))


@bp.get("/subscribers/<sid>/enrollments")
def list_subscriber_enrollments(sid):
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    limit, offset = v.pagination()
    sub = find(db.subscribers, sid, "ERR_SUBSCRIBER_NOT_FOUND")
    require_account(ctx, svc.audience_of_subscriber(sub)["account_id"])
    rows = [e for e in db.enrollments.values() if e["subscriber_id"] == sub["id"]]
    status = request.args.get("status")
    if status:
        rows = [e for e in rows if e["status"] == status]
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("enrollment", page), limit, offset, total)


# ==========================================================================
# Import jobs
# ==========================================================================
@bp.post("/audiences/<aid>/import-jobs")
def create_import_job(aid):
    ctx = authorize(("CampaignAuthor",))
    data = v.body()
    rows = data.get("rows")
    if not isinstance(rows, list):
        v.bad()
    if len(rows) < calc.IMPORT_MIN_ROWS or len(rows) > calc.IMPORT_MAX_ROWS:
        v.bad()
    for row in rows:
        if not isinstance(row, dict):
            v.bad()
    expected = v.req_int(data, "expected_audience_version")

    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])
    acct = db.accounts[aud["account_id"]]
    if expected != aud["version"]:
        raise ApiError("ERR_STALE_VERSION")

    job = base_fields()
    job.update({
        "audience_id": aud["id"],
        "rows": rows,
        "status": "PENDING",
        "row_count": len(rows),
        "accepted_count": 0,
        "rejected_count": 0,
        "duplicate_count": 0,
        "suppressed_count": 0,
        "created_subscriber_ids": [],
    })
    db.import_jobs[job["id"]] = job

    existing_emails = {s["email"] for s in db.subscribers.values()
                       if s["audience_id"] == aud["id"]}
    seen_in_batch = set()
    confirmed_subs = []
    for row in rows:
        email = row.get("email")
        # 1. format
        if not isinstance(email, str) or "@" not in email:
            job["rejected_count"] += 1
            continue
        # 2. suppression -- beats duplication
        if svc.suppression_for(acct["id"], email) is not None:
            job["suppressed_count"] += 1
            continue
        # 3. duplication
        if email in seen_in_batch or email in existing_emails:
            job["duplicate_count"] += 1
            continue
        first_name = row.get("first_name")
        if not isinstance(first_name, str):
            first_name = None
        sub = svc.create_subscriber(aud, email, first_name, "IMPORT")
        seen_in_batch.add(email)
        job["created_subscriber_ids"].append(sub["id"])
        job["accepted_count"] += 1
        if sub["consent_state"] == "CONFIRMED":
            confirmed_subs.append(sub)

    if job["accepted_count"] == 0:
        job["status"] = "REJECTED"
    elif job["accepted_count"] == job["row_count"]:
        job["status"] = "COMPLETED"
    else:
        job["status"] = "PARTIAL"
    mutate(job)

    for sub in confirmed_subs:
        svc.fire_enrollments(sub, "SUBSCRIBE_CONFIRMED")

    # All three outcomes increment the audience's version by exactly one.
    aud["subscriber_count"] = sum(
        1 for s in db.subscribers.values()
        if s["audience_id"] == aud["id"]
        and s["consent_state"] in calc.BILLABLE_CONSENT)
    mutate(aud)
    svc.sync_account(acct)
    return created(dump("import_job", job))


@bp.get("/audiences/<aid>/import-jobs")
def list_import_jobs(aid):
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    limit, offset = v.pagination()
    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])
    rows = [j for j in db.import_jobs.values() if j["audience_id"] == aud["id"]]
    status = request.args.get("status")
    if status:
        rows = [j for j in rows if j["status"] == status]
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("import_job", page), limit, offset, total)


@bp.post("/import-jobs/<jid>/rollback")
def rollback_import_job(jid):
    ctx = authorize(("CampaignAuthor",))
    job = find(db.import_jobs, jid, "ERR_IMPORT_JOB_NOT_FOUND")
    aud = db.audiences[job["audience_id"]]
    require_account(ctx, aud["account_id"])

    if job["status"] not in ("COMPLETED", "PARTIAL"):
        raise ApiError("ERR_IMPORT_NOT_ROLLBACKABLE")
    created_ids = set(job["created_subscriber_ids"])
    for send in db.sends.values():
        if send["subscriber_id"] in created_ids:
            raise ApiError("ERR_IMPORT_NOT_ROLLBACKABLE")

    for sub_id in job["created_subscriber_ids"]:
        sub = db.subscribers.get(sub_id)
        if sub is None or sub["consent_state"] == "ARCHIVED":
            continue
        sub["consent_state"] = "ARCHIVED"
        sub["confirmation_token"] = None
        mutate(sub)
    job["status"] = "ROLLED_BACK"
    mutate(job)
    svc.sync_audience(aud)
    svc.sync_account(db.accounts[aud["account_id"]])
    return ok(dump("import_job", job))


# ==========================================================================
# Segments
# ==========================================================================
@bp.post("/audiences/<aid>/segments")
def create_segment(aid):
    ctx = authorize(("CampaignAuthor", "PlatformAdmin"))
    data = v.body()
    name = v.req_str(data, "name", 1, 120)
    states = data.get("consent_states")
    if not isinstance(states, list) or not states:
        v.bad()
    for s in states:
        if s not in SEGMENT_CONSENT_STATES:
            v.bad()
    min_score = v.req_int(data, "min_engagement_score", 0, 100)
    max_days = v.opt_int(data, "max_days_since_open", None, minimum=0)

    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])

    seg = base_fields()
    seg.update({
        "audience_id": aud["id"],
        "name": name,
        "consent_states": states,
        "min_engagement_score": min_score,
        "max_days_since_open": max_days,
        "member_count": 0,
    })
    db.segments[seg["id"]] = seg
    seg["member_count"] = len(svc.segment_members(seg))
    return created(dump("segment", seg))


@bp.get("/audiences/<aid>/segments")
def list_segments(aid):
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    aud = find(db.audiences, aid, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, aud["account_id"])
    rows = [s for s in db.segments.values() if s["audience_id"] == aud["id"]]
    for seg in rows:
        svc.sync_segment(seg)
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("segment", page), limit, offset, total)


# ==========================================================================
# Templates
# ==========================================================================
@bp.post("/templates")
def create_template():
    ctx = authorize(("CampaignAuthor",))
    data = v.body()
    account_id = v.req_str(data, "account_id")
    name = v.req_str(data, "name", 1, 120)
    subject = v.req_str(data, "subject", 1, 200)
    html_body = v.req_str(data, "html_body", 1, 5000)
    acct = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    require_account(ctx, acct["id"])

    tpl = base_fields()
    tpl.update({
        "account_id": acct["id"],
        "name": name,
        "subject": subject,
        "html_body": html_body,
        "has_unsubscribe_link": "{{unsubscribe_url}}" in html_body,
        "status": "DRAFT",
    })
    db.templates[tpl["id"]] = tpl
    return created(dump("template", tpl))


@bp.post("/templates/<tid>/publish")
def publish_template(tid):
    ctx = authorize(("CampaignAuthor",))
    tpl = find(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    require_account(ctx, tpl["account_id"])
    if tpl["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    tpl["status"] = "PUBLISHED"
    tpl["has_unsubscribe_link"] = "{{unsubscribe_url}}" in tpl["html_body"]
    mutate(tpl)
    return ok(dump("template", tpl))


@bp.get("/templates/<tid>")
def get_template(tid):
    ctx = authorize(ALL_ROLES)
    tpl = find(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    require_account(ctx, tpl["account_id"])
    return ok(dump("template", tpl))


@bp.get("/templates")
def list_templates():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.templates.values())
    account_id = request.args.get("account_id")
    if account_id:
        rows = [t for t in rows if t["account_id"] == account_id]
    status = request.args.get("status")
    if status:
        rows = [t for t in rows if t["status"] == status]
    rows = scope_filter(ctx, rows, lambda t: t["account_id"])
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("template", page), limit, offset, total)


# ==========================================================================
# Campaigns
# ==========================================================================
@bp.post("/campaigns")
def create_campaign():
    ctx = authorize(("CampaignAuthor",))
    data = v.body()
    account_id = v.req_str(data, "account_id")
    audience_id = v.req_str(data, "audience_id")
    template_id = v.req_str(data, "template_id")
    name = v.req_str(data, "name", 1, 120)
    segment_id = v.opt_str(data, "segment_id", None, 1)
    ab_enabled = v.opt_bool(data, "ab_test_enabled", False)
    split = v.opt_int(data, "variant_split_pct", 50, minimum=1, maximum=99)
    variant_b_subject = v.opt_str(data, "variant_b_subject", None, 1)
    if ab_enabled and not variant_b_subject:
        v.bad()

    acct = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    aud = find(db.audiences, audience_id, "ERR_AUDIENCE_NOT_FOUND")
    tpl = find(db.templates, template_id, "ERR_TEMPLATE_NOT_FOUND")
    seg = None
    if segment_id:
        seg = find(db.segments, segment_id, "ERR_SEGMENT_NOT_FOUND")

    require_account(ctx, acct["id"])
    require_account(ctx, aud["account_id"])
    require_account(ctx, tpl["account_id"])
    if seg is not None:
        require_account(ctx, db.audiences[seg["audience_id"]]["account_id"])

    if seg is not None and seg["audience_id"] != aud["id"]:
        raise ApiError("ERR_SEGMENT_AUDIENCE_MISMATCH")

    camp = base_fields()
    camp.update({
        "account_id": acct["id"],
        "audience_id": aud["id"],
        "segment_id": seg["id"] if seg else None,
        "template_id": tpl["id"],
        "created_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "name": name,
        "status": "DRAFT",
        "ab_test_enabled": ab_enabled,
        "variant_split_pct": split,
        "variant_b_subject": variant_b_subject,
        "pinned_subject": None,
        "pinned_html_body": None,
        "pinned_template_version": None,
        "review_note": None,
        "scheduled_at": None,
        "send_window_minutes": None,
        "recipient_snapshot_ids": [],
        "recipient_count": 0,
        "reserved_credit_count": 0,
        "send_charge_cents": 0,
        "winning_variant": None,
        "winner_selected_at": None,
    })
    db.campaigns[camp["id"]] = camp
    return created(dump("campaign", camp))


@bp.get("/campaigns/<cid>")
def get_campaign(cid):
    ctx = authorize(ALL_ROLES)
    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])
    return ok(dump("campaign", camp))


@bp.get("/campaigns")
def list_campaigns():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.campaigns.values())
    for key in ("account_id", "audience_id", "segment_id", "template_id",
                "created_by_user_id", "approved_by_user_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [c for c in rows if c[key] == val]
    rows = scope_filter(ctx, rows, lambda c: c["account_id"])
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("campaign", page), limit, offset, total)


@bp.post("/campaigns/<cid>/submit-review")
def submit_review(cid):
    ctx = authorize(("CampaignAuthor",))
    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])
    if camp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    camp["status"] = "IN_REVIEW"
    mutate(camp)
    return ok(dump("campaign", camp))


@bp.post("/campaigns/<cid>/review")
def review_campaign(cid):
    ctx = authorize(("ComplianceApprover",))
    data = v.body()
    decision = v.req_enum(data, "decision", DECISIONS)
    note = v.opt_str(data, "note", None)
    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])

    # Priority 8 (segregation of duties) precedes priority 11 (state guard).
    if ctx.user_id == camp["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if camp["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "APPROVE":
        tpl = db.templates[camp["template_id"]]
        if tpl["status"] != "PUBLISHED":
            raise ApiError("ERR_TEMPLATE_NOT_PUBLISHED")
        if not tpl["has_unsubscribe_link"]:
            raise ApiError("ERR_MISSING_UNSUBSCRIBE_LINK")
        camp["status"] = "APPROVED"
        camp["approved_by_user_id"] = ctx.user_id
        camp["review_note"] = note
        camp["pinned_subject"] = tpl["subject"]
        camp["pinned_html_body"] = tpl["html_body"]
        camp["pinned_template_version"] = tpl["version"]
    else:
        camp["status"] = "DRAFT"
        camp["approved_by_user_id"] = None
        camp["review_note"] = note
        camp["pinned_subject"] = None
        camp["pinned_html_body"] = None
        camp["pinned_template_version"] = None
    mutate(camp)
    return ok(dump("campaign", camp))


@bp.post("/campaigns/<cid>/schedule")
def schedule_campaign(cid):
    ctx = authorize(("CampaignAuthor",))
    data = v.body()
    scheduled_raw = v.req_str(data, "scheduled_at")
    scheduled_at = parse_dt(scheduled_raw)
    if scheduled_at is None:
        v.bad()
    window = v.req_int(data, "send_window_minutes", 1, 1440)
    expected = v.req_int(data, "expected_account_version")

    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])
    acct = db.accounts[camp["account_id"]]

    if expected != acct["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if camp["status"] != "APPROVED":
        raise ApiError("ERR_CAMPAIGN_NOT_APPROVED")
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED")
    if not scheduled_at > now():
        raise ApiError("ERR_SCHEDULE_IN_PAST")

    svc.check_audience_fatigue(camp, scheduled_at)

    snapshot = svc.recipient_snapshot(camp)
    recipient_count = len(snapshot)

    svc.check_send_capacity(camp, acct, scheduled_at, window, recipient_count)

    if recipient_count == 0:
        raise ApiError("ERR_EMPTY_RECIPIENT_SET")
    if acct["send_credit_balance"] < recipient_count:
        raise ApiError("ERR_INSUFFICIENT_SEND_CREDITS")

    camp["scheduled_at"] = scheduled_at
    camp["send_window_minutes"] = window
    camp["recipient_snapshot_ids"] = snapshot
    camp["recipient_count"] = recipient_count
    camp["send_charge_cents"] = calc.send_charge_cents(
        recipient_count, acct["sender_reputation_score"])
    camp["reserved_credit_count"] = recipient_count
    camp["status"] = "SCHEDULED"
    mutate(camp)

    acct["send_credit_balance"] -= recipient_count
    svc.sync_account(acct, force=True)
    return ok(dump("campaign", camp))


@bp.post("/campaigns/<cid>/cancel")
def cancel_campaign(cid):
    ctx = authorize(("CampaignAuthor",))
    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])
    if camp["status"] not in ("SCHEDULED", "SENDING"):
        raise ApiError("ERR_INVALID_STATE")
    acct = db.accounts[camp["account_id"]]

    for send in svc.sends_of_campaign(camp["id"]):
        if send["delivery_status"] in ("QUEUED", "SOFT_BOUNCED"):
            send["delivery_status"] = "CANCELLED"
            mutate(send)

    released = camp["reserved_credit_count"]
    camp["reserved_credit_count"] = 0
    camp["status"] = "CANCELLED"
    mutate(camp)

    acct["send_credit_balance"] += released
    svc.sync_account(acct, force=True)
    return ok(dump("campaign", camp))


@bp.post("/campaigns/<cid>/select-winner")
def select_winner(cid):
    ctx = authorize(("CampaignAuthor",))
    camp = find(db.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")
    require_account(ctx, camp["account_id"])
    if camp["status"] != "SENT" or camp["winning_variant"] is not None:
        raise ApiError("ERR_INVALID_STATE")
    if not camp["ab_test_enabled"]:
        raise ApiError("ERR_AB_NOT_ENABLED")
    svc.select_winner(camp)
    return ok(dump("campaign", camp))


# ==========================================================================
# Sends
# ==========================================================================
@bp.get("/sends/<sid>")
def get_send(sid):
    ctx = authorize(ALL_ROLES)
    send = find(db.sends, sid, "ERR_SEND_NOT_FOUND")
    require_account(ctx, svc.account_id_of_send(send))
    return ok(dump("send", send))


@bp.get("/sends")
def list_sends():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.sends.values())
    for key in ("campaign_id", "journey_id", "subscriber_id", "variant_label",
                "delivery_status", "engagement_status"):
        val = request.args.get(key)
        if val:
            rows = [s for s in rows if s[key] == val]
    rows = scope_filter(ctx, rows, svc.account_id_of_send)
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("send", page), limit, offset, total)


# ==========================================================================
# Journeys
# ==========================================================================
def _validate_steps(raw):
    if not isinstance(raw, list) or len(raw) < 1 or len(raw) > 10:
        v.bad()
    steps = []
    for i, step in enumerate(raw):
        if not isinstance(step, dict):
            v.bad()
        idx = step.get("step_index")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx != i:
            v.bad()
        kind = step.get("kind")
        if kind not in STEP_KINDS:
            v.bad()
        entry = {"step_index": idx, "kind": kind}
        if kind == "WAIT":
            wait_hours = step.get("wait_hours")
            if isinstance(wait_hours, bool) or not isinstance(wait_hours, int) \
                    or wait_hours < 0:
                v.bad()
            entry["wait_hours"] = wait_hours
        elif kind == "EMAIL":
            tid = step.get("template_id")
            if not isinstance(tid, str) or not tid:
                v.bad()
            entry["template_id"] = tid
        else:  # CONDITION
            score = step.get("condition_min_score")
            if isinstance(score, bool) or not isinstance(score, int) \
                    or score < 0 or score > 100:
                v.bad()
            on_true = step.get("on_true_step_index")
            on_false = step.get("on_false_step_index")
            for target in (on_true, on_false):
                if isinstance(target, bool) or not isinstance(target, int):
                    v.bad()
            entry["condition_min_score"] = score
            entry["on_true_step_index"] = on_true
            entry["on_false_step_index"] = on_false
        steps.append(entry)

    # Priority 26: branch targets must be strictly greater than their own index.
    for step in steps:
        if step["kind"] != "CONDITION":
            continue
        if step["on_true_step_index"] <= step["step_index"] or \
                step["on_false_step_index"] <= step["step_index"]:
            raise ApiError("ERR_JOURNEY_STEP_ORDER")
    return steps


@bp.post("/journeys")
def create_journey():
    ctx = authorize(("CampaignAuthor",))
    data = v.body()
    account_id = v.req_str(data, "account_id")
    audience_id = v.req_str(data, "audience_id")
    name = v.req_str(data, "name", 1, 120)
    trigger_event = v.req_enum(data, "trigger_event", TRIGGER_EVENTS)
    steps = _validate_steps(data.get("steps"))

    acct = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    aud = find(db.audiences, audience_id, "ERR_AUDIENCE_NOT_FOUND")
    require_account(ctx, acct["id"])
    require_account(ctx, aud["account_id"])

    journey = base_fields()
    journey.update({
        "account_id": acct["id"],
        "audience_id": aud["id"],
        "name": name,
        "trigger_event": trigger_event,
        "steps": steps,
        "status": "DRAFT",
        "active_enrollment_count": 0,
        "entered_count": 0,
    })
    db.journeys[journey["id"]] = journey
    return created(dump("journey", journey))


@bp.get("/journeys/<jid>")
def get_journey(jid):
    ctx = authorize(ALL_ROLES)
    journey = find(db.journeys, jid, "ERR_JOURNEY_NOT_FOUND")
    require_account(ctx, journey["account_id"])
    return ok(dump("journey", journey))


@bp.get("/journeys")
def list_journeys():
    ctx = authorize(ALL_ROLES)
    limit, offset = v.pagination()
    rows = list(db.journeys.values())
    for key in ("account_id", "audience_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [j for j in rows if j[key] == val]
    rows = scope_filter(ctx, rows, lambda j: j["account_id"])
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("journey", page), limit, offset, total)


@bp.post("/journeys/<jid>/activate")
def activate_journey(jid):
    ctx = authorize(("CampaignAuthor",))
    journey = find(db.journeys, jid, "ERR_JOURNEY_NOT_FOUND")
    require_account(ctx, journey["account_id"])
    if journey["status"] not in ("DRAFT", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE")
    for step in journey["steps"]:
        if step["kind"] != "EMAIL":
            continue
        tpl = db.templates.get(step["template_id"])
        if tpl is None or tpl["status"] != "PUBLISHED" \
                or tpl["account_id"] != journey["account_id"]:
            raise ApiError("ERR_JOURNEY_TEMPLATE_INVALID")
    journey["status"] = "ACTIVE"
    mutate(journey)
    return ok(dump("journey", journey))


@bp.post("/journeys/<jid>/pause")
def pause_journey(jid):
    ctx = authorize(("CampaignAuthor",))
    journey = find(db.journeys, jid, "ERR_JOURNEY_NOT_FOUND")
    require_account(ctx, journey["account_id"])
    if journey["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    journey["status"] = "PAUSED"
    mutate(journey)
    return ok(dump("journey", journey))


@bp.get("/journeys/<jid>/enrollments")
def list_journey_enrollments(jid):
    ctx = authorize(("PlatformAdmin", "CampaignAuthor"))
    limit, offset = v.pagination()
    journey = find(db.journeys, jid, "ERR_JOURNEY_NOT_FOUND")
    require_account(ctx, journey["account_id"])
    rows = [e for e in db.enrollments.values() if e["journey_id"] == journey["id"]]
    status = request.args.get("status")
    if status:
        rows = [e for e in rows if e["status"] == status]
    rows = sort_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all("enrollment", page), limit, offset, total)


# ==========================================================================
# Operations plane
# ==========================================================================
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(("PlatformAdmin",))
    data = v.body()
    raw = v.req_str(data, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        v.bad()
    set_clock(parsed)
    return ok({"current_utc": iso(parsed)})


@bp.post("/_ops/run")
def ops_run():
    authorize(("PlatformAdmin",))
    return ok(svc.run_ops())


@bp.post("/_events/emit")
def emit_event():
    authorize(("PlatformAdmin",))
    data = v.body()
    send_id = v.req_str(data, "send_id")
    kind = v.req_enum(data, "kind", EVENT_KINDS)
    send = find(db.sends, send_id, "ERR_SEND_NOT_FOUND")
    svc.apply_event(send, kind)
    return ok(dump("send", send))
