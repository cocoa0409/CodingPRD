"""Routes: swarm events, removal jobs, subscriptions, invoices, enrollments, incidents."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import services as svc
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION, ERR_SWARM_NOT_ACTIONABLE,
                    ERR_REMOVAL_NOT_ACTIONABLE, ERR_REMOVAL_NOTICE_TOO_SHORT,
                    ERR_CREW_SCHEDULE_CONFLICT, ERR_SITE_HAS_OPEN_INCIDENTS,
                    ERR_SITE_BLOCKED, ERR_SITE_CAPACITY_EXCEEDED, ERR_AGREEMENT_NOT_ACTIVE,
                    ERR_WAIVER_CURRENT_REQUIRED, ERR_OUTSTANDING_BALANCE, ERR_HOST_NOT_ACTIVE,
                    ERR_DUPLICATE_SUBSCRIPTION, ERR_COURSE_PREREQUISITE_NOT_MET,
                    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_INVOICE_NOT_PAYABLE,
                    ERR_INVOICE_NOT_VOIDABLE, ERR_ENROLLMENT_NOT_COMPLETABLE)
from middleware import auth, body, ALL_AUTHENTICATED
from response import success, paginate
from util import new_base, touch, pub, req_str, opt_str, req_int, opt_int, req_enum, req_dt
from routes_core import _get

bp = Blueprint("ops", __name__)

REMOVAL_REASONS = ("RELOCATION", "NUISANCE", "HEALTH", "EXIT")
PLANS = ("BASIC", "PLUS", "PREMIUM")
COURSES = ("HOST-101", "ADV-201", "QUEEN-301")
SEVERITIES = ("MINOR", "SEVERE")


# ---------------------------------------------------------------------------
# Swarm events
# ---------------------------------------------------------------------------

@bp.post("/api/swarm-events")
def create_swarm():
    uid, _ = auth(("Host",))
    b = body()
    site_id = b.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'site_id' is required")
    site = db.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "Site %s not found" % site_id)
    if site["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host may only report swarms on their own sites")
    source_hive_id = b.get("source_hive_id")
    if source_hive_id is not None:
        if not isinstance(source_hive_id, str):
            raise_err(ERR_INVALID_REQUEST, "Field 'source_hive_id' must be a string")
        if db.hives.get(source_hive_id) is None:
            raise_err(ERR_NOT_FOUND, "Hive %s not found" % source_hive_id)
    ev = new_base()
    ev.update({"site_id": site_id, "source_hive_id": source_hive_id,
               "reported_by_host_id": uid, "reported_at": db.now(), "status": "REPORTED",
               "assigned_beekeeper_id": None, "captured_hive_id": None})
    db.swarm_events[ev["id"]] = ev
    return success(pub(ev), 201)


@bp.get("/api/swarm-events/<eid>")
def get_swarm(eid):
    auth(ALL_AUTHENTICATED)
    ev = _get(db.swarm_events, eid)
    svc.lazy_expire_swarm(ev)
    return success(pub(ev), 200)


@bp.get("/api/swarm-events")
def list_swarms():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.swarm_events)
    for ev in items:
        svc.lazy_expire_swarm(ev)
    site_id = request.args.get("site_id")
    source_hive_id = request.args.get("source_hive_id")
    if site_id is not None:
        items = [e for e in items if e["site_id"] == site_id]
    if source_hive_id is not None:
        items = [e for e in items if e.get("source_hive_id") == source_hive_id]
    page, meta = paginate(items)
    return success([pub(e) for e in page], 200, meta)


@bp.post("/api/swarm-events/<eid>/dispatch")
def dispatch_swarm(eid):
    uid, _ = auth(("Beekeeper",))
    ev = _get(db.swarm_events, eid)
    svc.lazy_expire_swarm(ev)
    if ev["status"] != "REPORTED":
        raise_err(ERR_SWARM_NOT_ACTIONABLE, "Swarm event is not REPORTED")
    ev["status"] = "DISPATCHED"
    ev["assigned_beekeeper_id"] = uid
    touch(ev)
    return success(pub(ev), 200)


@bp.post("/api/swarm-events/<eid>/capture")
def capture_swarm(eid):
    uid, _ = auth(("Beekeeper",))
    ev = _get(db.swarm_events, eid)
    svc.lazy_expire_swarm(ev)
    if ev["status"] != "DISPATCHED":
        raise_err(ERR_SWARM_NOT_ACTIONABLE, "Swarm event is not DISPATCHED")
    if ev["assigned_beekeeper_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Only the assigned beekeeper may capture")
    site = db.sites.get(ev["site_id"])
    if site is not None and site["status"] != "CLEAR":
        raise_err(ERR_SITE_BLOCKED, "Site is BLOCKED")
    if site is not None and svc.site_occupancy(site["id"]) >= svc.effective_capacity(site):
        raise_err(ERR_SITE_CAPACITY_EXCEEDED, "Site occupancy has reached effective capacity")
    # Temporal (step 10): an ACTIVE agreement covering the site, term containing now.
    now = db.now()
    agreement = None
    for ag in svc.sorted_all(db.agreements):
        if ag["site_id"] != ev["site_id"]:
            continue
        svc.lazy_expire_agreement(ag)
        if (ag["status"] == "ACTIVE"
                and ag["term_start_date"] <= now <= ag["term_end_date"]):
            agreement = ag
            break
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "No ACTIVE agreement covers this site today")
    hive = new_base()
    hive.update({"site_id": ev["site_id"], "agreement_id": agreement["id"],
                 "parent_hive_id": None, "source_swarm_event_id": ev["id"],
                 "installed_at": now, "lifecycle_status": "ACTIVE",
                 "posture": "STABLE", "provisional_posture": "STABLE",
                 "last_verified_inspection_at": None})
    db.hives[hive["id"]] = hive
    ev["status"] = "CAPTURED"
    ev["captured_hive_id"] = hive["id"]
    touch(ev)
    return success(pub(ev), 200)


@bp.post("/api/swarm-events/<eid>/mark-lost")
def mark_swarm_lost(eid):
    uid, _ = auth(("Beekeeper",))
    ev = _get(db.swarm_events, eid)
    svc.lazy_expire_swarm(ev)
    if ev["status"] != "DISPATCHED":
        raise_err(ERR_SWARM_NOT_ACTIONABLE, "Swarm event is not DISPATCHED")
    if ev["assigned_beekeeper_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Only the assigned beekeeper may mark lost")
    ev["status"] = "LOST"
    touch(ev)
    return success(pub(ev), 200)


# ---------------------------------------------------------------------------
# Removal jobs
# ---------------------------------------------------------------------------

@bp.post("/api/removal-jobs")
def create_removal():
    uid, _ = auth(("Host",))
    b = body()
    hive_id = b.get("hive_id")
    if not isinstance(hive_id, str) or not hive_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'hive_id' is required")
    hive = db.hives.get(hive_id)
    if hive is None:
        raise_err(ERR_NOT_FOUND, "Hive %s not found" % hive_id)
    site = db.sites.get(hive["site_id"])
    if site is None or site["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host may only request removal of their own hives")
    reason = req_enum(b, "reason", REMOVAL_REASONS)
    host = db.hosts.get(uid)
    # Safety (step 7): waiver currency.
    if host is None or not svc.waiver_current(host):
        raise_err(ERR_WAIVER_CURRENT_REQUIRED, "Host waiver is missing or older than 365 days")
    # Referential (step 9): at most one non-terminal removal job per hive.
    for job in db.removal_jobs.values():
        if job["hive_id"] == hive_id and job["status"] in ("REQUESTED", "APPROVED", "SCHEDULED"):
            raise_err(ERR_REMOVAL_NOT_ACTIONABLE, "Hive already has a non-terminal removal job")
    # Fiscal (step 11).
    if svc.host_balance_cents(uid) != 0:
        raise_err(ERR_OUTSTANDING_BALANCE, "Host has unpaid invoices")
    job = new_base()
    job.update({"hive_id": hive_id, "requested_by_host_id": uid, "reason": reason,
                "requested_at": db.now(), "status": "REQUESTED", "decision_reason": None,
                "scheduled_start": None, "crew_id": None, "cancellation_fee_cents": None,
                "completed_at": None})
    db.removal_jobs[job["id"]] = job
    return success(pub(job), 201)


@bp.get("/api/removal-jobs/<jid>")
def get_removal(jid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.removal_jobs, jid)), 200)


@bp.get("/api/removal-jobs")
def list_removals():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.removal_jobs)
    hive_id = request.args.get("hive_id")
    if hive_id is not None:
        items = [j for j in items if j["hive_id"] == hive_id]
    page, meta = paginate(items)
    return success([pub(j) for j in page], 200, meta)


@bp.post("/api/removal-jobs/<jid>/approve")
def decide_removal(jid):
    auth(("ApiaryManager",))
    job = _get(db.removal_jobs, jid)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    reason = opt_str(b, "decision_reason")
    if job["status"] != "REQUESTED":
        raise_err(ERR_REMOVAL_NOT_ACTIONABLE, "Removal job is not REQUESTED")
    if decision == "APPROVE":
        hive = db.hives.get(job["hive_id"])
        site_id = hive["site_id"] if hive else None
        for inc in db.incidents.values():
            if inc["site_id"] == site_id and inc["status"] == "REPORTED":
                raise_err(ERR_SITE_HAS_OPEN_INCIDENTS, "Site has a REPORTED incident")
        job["status"] = "APPROVED"
    else:
        job["status"] = "REJECTED"
        job["cancellation_fee_cents"] = 0
    if reason is not None:
        job["decision_reason"] = reason
    touch(job)
    return success(pub(job), 200)


@bp.post("/api/removal-jobs/<jid>/schedule")
def schedule_removal(jid):
    auth(("ApiaryManager",))
    job = _get(db.removal_jobs, jid)
    b = body()
    scheduled_start = req_dt(b, "scheduled_start")
    crew_id = req_str(b, "crew_id")
    if job["status"] != "APPROVED":
        raise_err(ERR_REMOVAL_NOT_ACTIONABLE, "Removal job is not APPROVED")
    # Business constraint (step 8): crew buffer — 2h job windows, >= 2h gap (exactly 2h allowed).
    two_h = timedelta(hours=2)
    new_end = scheduled_start + two_h
    for other in db.removal_jobs.values():
        if other["id"] == job["id"] or other["status"] != "SCHEDULED":
            continue
        if other["crew_id"] != crew_id:
            continue
        o_start = other["scheduled_start"]
        o_end = o_start + two_h
        if not (o_end <= scheduled_start - two_h or o_start >= new_end + two_h):
            raise_err(ERR_CREW_SCHEDULE_CONFLICT, "Crew has a conflicting scheduled job")
    # Temporal (step 10): 48h minimum notice, boundary inclusive.
    if scheduled_start < db.now() + timedelta(hours=48):
        raise_err(ERR_REMOVAL_NOTICE_TOO_SHORT, "scheduled_start must be at least 48 hours out")
    job["status"] = "SCHEDULED"
    job["scheduled_start"] = scheduled_start
    job["crew_id"] = crew_id
    touch(job)
    return success(pub(job), 200)


@bp.post("/api/removal-jobs/<jid>/complete")
def complete_removal(jid):
    auth(("Beekeeper",))
    job = _get(db.removal_jobs, jid)
    if job["status"] != "SCHEDULED":
        raise_err(ERR_REMOVAL_NOT_ACTIONABLE, "Removal job is not SCHEDULED")
    job["status"] = "COMPLETED"
    job["completed_at"] = db.now()
    touch(job)
    hive = db.hives.get(job["hive_id"])
    if hive is not None and hive["lifecycle_status"] in ("ACTIVE", "QUARANTINED"):
        hive["lifecycle_status"] = "REMOVED"
        touch(hive)
    return success(pub(job), 200)


@bp.post("/api/removal-jobs/<jid>/cancel")
def cancel_removal(jid):
    uid, role = auth(("Host", "PlatformOps"))
    job = _get(db.removal_jobs, jid)
    if role == "Host" and job["requested_by_host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this removal job")
    if job["status"] not in ("REQUESTED", "APPROVED", "SCHEDULED"):
        raise_err(ERR_REMOVAL_NOT_ACTIONABLE, "Removal job cannot be cancelled")
    fee = 0 if db.now() <= job["requested_at"] + timedelta(hours=24) else svc.CANCELLATION_FEE_CENTS
    job["status"] = "CANCELLED"
    job["cancellation_fee_cents"] = fee
    job["_fee_charged"] = False
    touch(job)
    return success(pub(job), 200)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def pub_subscription(sub):
    out = pub(sub)
    out["projected_overwinter_credit_cents"] = svc.projected_overwinter_credit_cents(sub)
    return out


@bp.post("/api/subscriptions")
def create_subscription():
    auth(("PlatformOps",))
    b = body()
    host_id = b.get("host_id")
    if not isinstance(host_id, str) or not host_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'host_id' is required")
    host = db.hosts.get(host_id)
    if host is None:
        raise_err(ERR_NOT_FOUND, "Host %s not found" % host_id)
    plan = req_enum(b, "plan", PLANS)
    if svc.active_subscription(host_id) is not None:
        raise_err(ERR_DUPLICATE_SUBSCRIPTION, "Host already has a non-CANCELLED subscription")
    if plan == "PREMIUM" and not svc.completed_enrollment(host_id, "HOST-101"):
        raise_err(ERR_COURSE_PREREQUISITE_NOT_MET, "PREMIUM requires COMPLETED HOST-101")
    sub = new_base()
    sub.update({"host_id": host_id, "plan": plan, "monthly_fee_cents": svc.FEES[plan],
                "status": "ACTIVE", "pending_plan": None,
                "projected_overwinter_credit_cents": 0, "activated_at": db.now()})
    db.subscriptions[sub["id"]] = sub
    svc.make_invoice(sub, sub["monthly_fee_cents"], 0, 0, 0, db.now())
    return success(pub_subscription(sub), 201)


@bp.get("/api/subscriptions/<sid>")
def get_subscription(sid):
    auth(ALL_AUTHENTICATED)
    return success(pub_subscription(_get(db.subscriptions, sid)), 200)


@bp.get("/api/subscriptions")
def list_subscriptions():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.subscriptions)
    host_id = request.args.get("host_id")
    if host_id is not None:
        items = [s for s in items if s["host_id"] == host_id]
    page, meta = paginate(items)
    return success([pub_subscription(s) for s in page], 200, meta)


@bp.post("/api/subscriptions/<sid>/change-plan")
def change_plan(sid):
    uid, _ = auth(("Host",))
    sub = _get(db.subscriptions, sid)
    if sub["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this subscription")
    b = body()
    plan = req_enum(b, "plan", PLANS)
    expected = b.get("expected_subscription_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_subscription_version' is required")
    if sub["status"] != "ACTIVE":
        raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Subscription is not ACTIVE")
    if expected != sub["version"]:
        raise_err(ERR_STALE_VERSION, "expected_subscription_version does not match current version")
    if plan == "PREMIUM" and not svc.completed_enrollment(sub["host_id"], "HOST-101"):
        raise_err(ERR_COURSE_PREREQUISITE_NOT_MET, "PREMIUM requires COMPLETED HOST-101")
    sub["pending_plan"] = plan
    touch(sub)
    return success(pub_subscription(sub), 200)


@bp.post("/api/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, _ = auth(("Host",))
    sub = _get(db.subscriptions, sid)
    if sub["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this subscription")
    if sub["status"] not in ("ACTIVE", "PAST_DUE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Subscription is already CANCELLED")
    if svc.host_balance_cents(sub["host_id"]) != 0:
        raise_err(ERR_OUTSTANDING_BALANCE, "Host has unpaid invoices")
    sub["pending_plan"] = None
    sub["status"] = "CANCELLED"
    touch(sub)
    return success(pub_subscription(sub), 200)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def _invoice_owner(invoice):
    sub = db.subscriptions.get(invoice["subscription_id"])
    return sub["host_id"] if sub else None


@bp.get("/api/invoices/<iid>")
def get_invoice(iid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.invoices, iid)), 200)


@bp.get("/api/invoices")
def list_invoices():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.invoices)
    sub_id = request.args.get("subscription_id")
    if sub_id is not None:
        items = [i for i in items if i["subscription_id"] == sub_id]
    page, meta = paginate(items)
    return success([pub(i) for i in page], 200, meta)


@bp.post("/api/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = auth(("Host", "PlatformOps"))
    inv = _get(db.invoices, iid)
    if role == "Host" and _invoice_owner(inv) != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this invoice")
    if inv["status"] not in ("OPEN", "OVERDUE"):
        raise_err(ERR_INVOICE_NOT_PAYABLE, "Invoice is PAID or VOID")
    inv["status"] = "PAID"
    inv["paid_at"] = db.now()
    touch(inv)
    sub = db.subscriptions.get(inv["subscription_id"])
    if sub is not None:
        svc.cure_cascade(sub)
    return success(pub(inv), 200)


@bp.post("/api/invoices/<iid>/void")
def void_invoice(iid):
    auth(("PlatformOps",))
    inv = _get(db.invoices, iid)
    if inv["status"] not in ("OPEN", "OVERDUE"):
        raise_err(ERR_INVOICE_NOT_VOIDABLE, "Only an OPEN or OVERDUE invoice can be voided")
    inv["status"] = "VOID"
    touch(inv)
    sub = db.subscriptions.get(inv["subscription_id"])
    if sub is not None:
        svc.cure_cascade(sub)
    return success(pub(inv), 200)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------

COURSE_PREREQS = {"ADV-201": "HOST-101", "QUEEN-301": "ADV-201"}


@bp.post("/api/enrollments")
def create_enrollment():
    uid, _ = auth(("Host",))
    b = body()
    host_id = b.get("host_id")
    if not isinstance(host_id, str) or not host_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'host_id' is required")
    if host_id != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host may only enroll themselves")
    host = db.hosts.get(host_id)
    if host is None:
        raise_err(ERR_NOT_FOUND, "Host %s not found" % host_id)
    course = req_enum(b, "course_code", COURSES)
    # Safety (step 7): waiver currency.
    if not svc.waiver_current(host):
        raise_err(ERR_WAIVER_CURRENT_REQUIRED, "Host waiver is missing or older than 365 days")
    # Business constraint (step 8): prerequisite chain.
    prereq = COURSE_PREREQS.get(course)
    if prereq is not None and not svc.completed_enrollment(host_id, prereq):
        raise_err(ERR_COURSE_PREREQUISITE_NOT_MET, "%s requires COMPLETED %s" % (course, prereq))
    # Fiscal (step 11).
    if host["status"] != "ACTIVE":
        raise_err(ERR_HOST_NOT_ACTIVE, "Host is not ACTIVE")
    en = new_base()
    en.update({"host_id": host_id, "course_code": course, "status": "ENROLLED",
               "quiz_score": None, "completed_at": None})
    db.enrollments[en["id"]] = en
    return success(pub(en), 201)


@bp.get("/api/enrollments/<eid>")
def get_enrollment(eid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.enrollments, eid)), 200)


@bp.get("/api/enrollments")
def list_enrollments():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.enrollments)
    host_id = request.args.get("host_id")
    if host_id is not None:
        items = [e for e in items if e["host_id"] == host_id]
    page, meta = paginate(items)
    return success([pub(e) for e in page], 200, meta)


@bp.post("/api/enrollments/<eid>/complete")
def complete_enrollment(eid):
    auth(("PlatformOps",))
    en = _get(db.enrollments, eid)
    b = body()
    score = req_int(b, "quiz_score", minv=0, maxv=100)
    if en["status"] != "ENROLLED":
        raise_err(ERR_ENROLLMENT_NOT_COMPLETABLE, "Enrollment is already terminal")
    if score >= 80:
        en["status"] = "COMPLETED"
        en["completed_at"] = db.now()
    else:
        en["status"] = "FAILED"
    en["quiz_score"] = score
    touch(en)
    return success(pub(en), 200)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.post("/api/incidents")
def create_incident():
    uid, _ = auth(("Host", "Beekeeper", "ApiaryManager"))
    b = body()
    site_id = b.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'site_id' is required")
    site = db.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "Site %s not found" % site_id)
    severity = req_enum(b, "severity", SEVERITIES)
    occurred_at = req_dt(b, "occurred_at")
    description = req_str(b, "description")
    inc = new_base()
    inc.update({"site_id": site_id, "host_id": site["host_id"], "reporter_id": uid,
                "severity": severity, "occurred_at": occurred_at, "description": description,
                "status": "REPORTED", "liability_cents": 0, "resolved_at": None})
    db.incidents[inc["id"]] = inc
    reported = sum(1 for i in db.incidents.values()
                   if i["site_id"] == site_id and i["status"] == "REPORTED")
    if site["status"] == "CLEAR" and (severity == "SEVERE" or reported >= 3):
        site["status"] = "BLOCKED"
        touch(site)
    return success(pub(inc), 201)


@bp.get("/api/incidents/<iid>")
def get_incident(iid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.incidents, iid)), 200)


@bp.get("/api/incidents")
def list_incidents():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.incidents)
    site_id = request.args.get("site_id")
    host_id = request.args.get("host_id")
    if site_id is not None:
        items = [i for i in items if i["site_id"] == site_id]
    if host_id is not None:
        items = [i for i in items if i["host_id"] == host_id]
    page, meta = paginate(items)
    return success([pub(i) for i in page], 200, meta)


@bp.post("/api/incidents/<iid>/resolve")
def resolve_incident(iid):
    auth(("ApiaryManager",))
    inc = _get(db.incidents, iid)
    b = body()
    outcome = req_enum(b, "outcome", ("AT_FAULT", "NO_FAULT", "DISMISSED"))
    liability = opt_int(b, "liability_cents", default=0, minv=0)
    if inc["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "Incident is not REPORTED")
    inc["liability_cents"] = liability
    if outcome == "AT_FAULT":
        inc["status"] = "RESOLVED_AT_FAULT"
        host = db.hosts.get(inc["host_id"])
        if host is not None:
            penalty = 15 if inc["severity"] == "SEVERE" else 5
            host["reputation_score"] = max(0, host["reputation_score"] - penalty)
            touch(host)
    elif outcome == "NO_FAULT":
        inc["status"] = "RESOLVED_NO_FAULT"
    else:
        inc["status"] = "DISMISSED"
    inc["resolved_at"] = db.now()
    touch(inc)
    return success(pub(inc), 200)
