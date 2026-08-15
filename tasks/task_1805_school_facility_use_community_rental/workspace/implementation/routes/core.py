"""Clock, sites, facilities, rate policies, renters, insurance, calendar."""
from flask import Blueprint, request

import db
import errors
import response
import services
import util
from middleware import get_auth, require_roles
from validation import (
    body_json, req_string, opt_string, req_int, opt_int, opt_bool, req_enum,
    req_datetime, opt_datetime, init_common, touch, get_site, get_facility,
    get_renter, get_policy, get_event, get_cert, site_of_facility,
    cancel_permit_record, run_waitlist_sweep, now_iso, post_txn,
)

bp = Blueprint("core", __name__)

ALL_ROLES = ("DistrictAdmin", "FacilitiesDirector", "SiteCoordinator",
             "CustodialSupervisor", "RenterOrgRep")
FACILITY_TIERS = {"STANDARD", "PREMIUM", "ATHLETIC"}
RATE_CLASSES = {"INTERNAL", "NONPROFIT", "FOR_PROFIT"}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/district/_clock/set_current_utc")
def set_clock():
    require_roles("DistrictAdmin")
    body = body_json()
    target = req_datetime(body, "to_iso8601")
    db.CLOCK_NOW = target
    services.sweep_clock()
    return response.success({"current_utc": util.iso_z(db.CLOCK_NOW)})


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

def site_out(s):
    return {k: s[k] for k in (
        "id", "created_at", "updated_at", "version", "site_code",
        "display_name", "site_status", "rental_timezone")}


@bp.post("/district/sites")
def create_site():
    require_roles("DistrictAdmin")
    body = body_json()
    site_code = req_string(body, "site_code")
    display_name = req_string(body, "display_name")
    tz = opt_string(body, "rental_timezone")
    for s in db.sites.values():
        if s["site_code"] == site_code:
            raise errors.duplicate("site_code must be unique district-wide")
    rec = init_common()
    rec.update({
        "site_code": site_code,
        "display_name": display_name,
        "site_status": "ACTIVE",
        "rental_timezone": tz if tz else util.DEFAULT_TZ,
    })
    db.sites[rec["id"]] = rec
    return response.success(site_out(rec), 201)


@bp.get("/district/sites/<site_id>")
def get_site_ep(site_id):
    require_roles(*ALL_ROLES)
    return response.success(site_out(get_site(site_id)))


@bp.post("/district/sites/<site_id>/close")
def close_site(site_id):
    require_roles("DistrictAdmin")
    site = get_site(site_id)
    if site["site_status"] != "ACTIVE":
        raise errors.invalid_state("Site is already CLOSED")
    for p in db.permits.values():
        fac = db.facilities.get(p["facility_id"])
        if fac and fac["site_id"] == site_id and \
                p["lifecycle_status"] in ("ISSUED", "ACTIVE"):
            raise errors.invalid_state(
                "Cannot close a site with ISSUED or ACTIVE permits")
    site["site_status"] = "CLOSED"
    touch(site)
    for r in db.requests.values():
        fac = db.facilities.get(r["facility_id"])
        if fac and fac["site_id"] == site_id and r["request_status"] in (
                "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
                "RESUBMITTED", "WAITLISTED"):
            r["request_status"] = "WITHDRAWN"
            touch(r)
    for f in db.facilities.values():
        if f["site_id"] == site_id and f["facility_status"] != "RETIRED":
            f["facility_status"] = "RETIRED"
            touch(f)
    return response.success(site_out(site))


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------

def facility_out(f):
    return {k: f[k] for k in (
        "id", "created_at", "updated_at", "version", "site_id",
        "facility_code", "facility_tier", "capacity", "setup_buffer_minutes",
        "teardown_buffer_minutes", "requires_custodian", "facility_status")}


@bp.post("/district/sites/<site_id>/facilities")
def create_facility(site_id):
    require_roles("DistrictAdmin")
    site = get_site(site_id)
    body = body_json()
    code = req_string(body, "facility_code")
    tier = req_enum(body, "facility_tier", FACILITY_TIERS)
    capacity = req_int(body, "capacity")
    setup_buf = opt_int(body, "setup_buffer_minutes")
    teardown_buf = opt_int(body, "teardown_buffer_minutes")
    requires_custodian = opt_bool(body, "requires_custodian", True)
    if capacity < 1:
        raise errors.invalid_request("capacity must be >= 1")
    setup_buf = 30 if setup_buf is None else setup_buf
    teardown_buf = 30 if teardown_buf is None else teardown_buf
    for label, buf in (("setup_buffer_minutes", setup_buf),
                       ("teardown_buffer_minutes", teardown_buf)):
        if buf < 0 or buf % 15 != 0:
            raise errors.invalid_time_window(
                f"{label} must be >= 0 and a multiple of 15")
    if site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    for f in db.facilities.values():
        if f["site_id"] == site_id and f["facility_code"] == code:
            raise errors.duplicate("facility_code must be unique within the site")
    rec = init_common()
    rec.update({
        "site_id": site_id,
        "facility_code": code,
        "facility_tier": tier,
        "capacity": capacity,
        "setup_buffer_minutes": setup_buf,
        "teardown_buffer_minutes": teardown_buf,
        "requires_custodian": requires_custodian,
        "facility_status": "AVAILABLE",
    })
    db.facilities[rec["id"]] = rec
    return response.success(facility_out(rec), 201)


@bp.get("/district/sites/<site_id>/facilities")
def list_site_facilities(site_id):
    require_roles(*ALL_ROLES)
    get_site(site_id)
    status = request.args.get("facility_status")
    rows = [f for f in db.facilities.values() if f["site_id"] == site_id]
    if status:
        rows = [f for f in rows if f["facility_status"] == status]
    rows.sort(key=lambda f: f["created_at"])
    return response.success_list([facility_out(f) for f in rows],
                                 len(rows), len(rows), 0)


@bp.get("/district/facilities")
def list_facilities():
    require_roles(*ALL_ROLES)
    rows = list(db.facilities.values())
    for param in ("site_id", "facility_status", "facility_tier"):
        v = request.args.get(param)
        if v:
            rows = [f for f in rows if f.get(param) == v]
    rows.sort(key=lambda f: f["created_at"])
    return response.paginate([facility_out(f) for f in rows])


@bp.get("/district/facilities/<facility_id>")
def get_facility_ep(facility_id):
    require_roles(*ALL_ROLES)
    return response.success(facility_out(get_facility(facility_id)))


def _withdraw_pending_requests(facility_id, statuses):
    for r in db.requests.values():
        if r["facility_id"] == facility_id and r["request_status"] in statuses:
            r["request_status"] = "WITHDRAWN"
            touch(r)


@bp.post("/district/facilities/<facility_id>/hold")
def hold_facility(facility_id):
    require_roles("DistrictAdmin")
    fac = get_facility(facility_id)
    body = body_json(required=False)
    hold_reason = opt_string(body, "hold_reason")
    if fac["facility_status"] != "AVAILABLE":
        raise errors.invalid_state("Facility is not AVAILABLE")
    fac["facility_status"] = "MAINTENANCE_HOLD"
    if hold_reason is not None:
        fac["hold_reason"] = hold_reason
    touch(fac)
    for r in db.requests.values():
        if r["facility_id"] == facility_id and r["request_status"] in (
                "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "RESUBMITTED"):
            r["request_status"] = "WAITLISTED"
            r["hold_reason"] = "MAINTENANCE"
            touch(r)
    return response.success(facility_out(fac))


@bp.post("/district/facilities/<facility_id>/release_hold")
def release_hold_facility(facility_id):
    require_roles("DistrictAdmin")
    fac = get_facility(facility_id)
    if fac["facility_status"] != "MAINTENANCE_HOLD":
        raise errors.invalid_state("Facility is not on MAINTENANCE_HOLD")
    fac["facility_status"] = "AVAILABLE"
    fac.pop("hold_reason", None)
    touch(fac)
    return response.success(facility_out(fac))


@bp.post("/district/facilities/<facility_id>/retire")
def retire_facility(facility_id):
    require_roles("DistrictAdmin")
    fac = get_facility(facility_id)
    if fac["facility_status"] == "RETIRED":
        raise errors.invalid_state("Facility is already RETIRED")
    for p in db.permits.values():
        if p["facility_id"] == facility_id and \
                p["lifecycle_status"] in ("ISSUED", "ACTIVE"):
            raise errors.invalid_state(
                "Cannot retire a facility with ISSUED or ACTIVE permits")
    fac["facility_status"] = "RETIRED"
    touch(fac)
    _withdraw_pending_requests(facility_id, (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "RESUBMITTED", "WAITLISTED"))
    return response.success(facility_out(fac))


# ---------------------------------------------------------------------------
# Rate class policies
# ---------------------------------------------------------------------------

def policy_out(p):
    return {k: p[k] for k in (
        "id", "created_at", "updated_at", "version", "policy_code",
        "rate_class", "facility_tier", "hourly_rate_cents",
        "deposit_basis_points", "deposit_floor_cents",
        "custodial_hourly_cents", "effective_from", "effective_to",
        "policy_status", "unique_key")}


@bp.post("/district/rate_policies")
def create_policy():
    require_roles("DistrictAdmin")
    body = body_json()
    policy_code = req_string(body, "policy_code")
    rate_class = req_enum(body, "rate_class", RATE_CLASSES)
    tier = req_enum(body, "facility_tier", FACILITY_TIERS)
    hourly = req_int(body, "hourly_rate_cents")
    bps = req_int(body, "deposit_basis_points")
    custodial = req_int(body, "custodial_hourly_cents")
    eff_from = req_datetime(body, "effective_from")
    eff_to = opt_datetime(body, "effective_to")
    floor = opt_int(body, "deposit_floor_cents")
    if hourly < 0:
        raise errors.invalid_request("hourly_rate_cents must be >= 0")
    if rate_class == "INTERNAL" and hourly != 0:
        raise errors.invalid_request("INTERNAL hourly_rate_cents must be 0")
    if bps < 0 or bps > 10000:
        raise errors.invalid_request("deposit_basis_points must be in 0..10000")
    if custodial < 0:
        raise errors.invalid_request("custodial_hourly_cents must be >= 0")
    if eff_to is not None and eff_to <= eff_from:
        raise errors.invalid_time_window("effective_to must be > effective_from")
    floor = 10000 if floor is None else floor
    if floor < 0:
        raise errors.invalid_request("deposit_floor_cents must be >= 0")
    unique_key = f"{rate_class}|{tier}|{util.iso_z(eff_from)}"
    for p in db.policies.values():
        if p["policy_code"] == policy_code or p["unique_key"] == unique_key:
            raise errors.duplicate(
                "policy_code and (rate_class, facility_tier, effective_from) must be unique")
    rec = init_common()
    rec.update({
        "policy_code": policy_code,
        "rate_class": rate_class,
        "facility_tier": tier,
        "hourly_rate_cents": hourly,
        "deposit_basis_points": bps,
        "deposit_floor_cents": floor,
        "custodial_hourly_cents": custodial,
        "effective_from": util.iso_z(eff_from),
        "effective_to": util.iso_z(eff_to) if eff_to else None,
        "policy_status": "ACTIVE",
        "unique_key": unique_key,
    })
    # A new ACTIVE policy supersedes any overlapping ACTIVE policy of the pair.
    for p in db.policies.values():
        if p["policy_status"] != "ACTIVE":
            continue
        if p["rate_class"] != rate_class or p["facility_tier"] != tier:
            continue
        p_from = util.parse_iso(p["effective_from"])
        p_to = util.parse_iso(p["effective_to"]) if p.get("effective_to") else None
        if util.overlaps(eff_from, eff_to or util.FAR_FUTURE,
                         p_from, p_to or util.FAR_FUTURE):
            p["policy_status"] = "SUPERSEDED"
            touch(p)
    db.policies[rec["id"]] = rec
    return response.success(policy_out(rec), 201)


@bp.get("/district/rate_policies")
def list_policies():
    require_roles("DistrictAdmin", "FacilitiesDirector", "SiteCoordinator")
    rows = list(db.policies.values())
    for param in ("rate_class", "facility_tier", "policy_status"):
        v = request.args.get(param)
        if v:
            rows = [p for p in rows if p.get(param) == v]
    rows.sort(key=lambda p: p["created_at"])
    return response.paginate([policy_out(p) for p in rows])


@bp.get("/district/rate_policies/<policy_id>")
def get_policy_ep(policy_id):
    require_roles("DistrictAdmin", "FacilitiesDirector", "SiteCoordinator")
    return response.success(policy_out(get_policy(policy_id)))


# ---------------------------------------------------------------------------
# Renter organizations
# ---------------------------------------------------------------------------

def renter_out(r):
    return {k: r[k] for k in (
        "id", "created_at", "updated_at", "version", "org_name", "rate_class",
        "nonprofit_registration_no", "org_standing", "credit_balance_cents",
        "outstanding_balance_cents", "forfeiture_count")}


@bp.post("/district/renters")
def create_renter():
    require_roles("FacilitiesDirector", "DistrictAdmin")
    body = body_json()
    org_name = req_string(body, "org_name")
    rate_class = req_enum(body, "rate_class", RATE_CLASSES)
    reg_no = opt_string(body, "nonprofit_registration_no")
    if rate_class == "NONPROFIT" and not reg_no:
        raise errors.invalid_request(
            "nonprofit_registration_no is required for NONPROFIT rate class")
    if rate_class != "NONPROFIT" and reg_no is not None:
        reg_no = None
    for r in db.renters.values():
        if r["org_name"].lower() == org_name.lower():
            raise errors.duplicate("org_name must be unique case-insensitively")
    rec = init_common()
    rec.update({
        "org_name": org_name,
        "rate_class": rate_class,
        "nonprofit_registration_no": reg_no,
        "org_standing": "GOOD_STANDING",
        "credit_balance_cents": 0,
        "outstanding_balance_cents": 0,
        "forfeiture_count": 0,
    })
    db.renters[rec["id"]] = rec
    return response.success(renter_out(rec), 201)


@bp.get("/district/renters/<org_id>")
def get_renter_ep(org_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    renter = get_renter(org_id)
    if role == "RenterOrgRep" and uid != org_id:
        raise errors.forbidden()
    return response.success(renter_out(renter))


@bp.get("/district/renters")
def list_renters():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.renters.values())
    for param in ("rate_class", "org_standing"):
        v = request.args.get(param)
        if v:
            rows = [r for r in rows if r.get(param) == v]
    rows.sort(key=lambda r: r["created_at"])
    return response.paginate([renter_out(r) for r in rows])


@bp.post("/district/renters/<org_id>/bar")
def bar_renter(org_id):
    require_roles("FacilitiesDirector")
    renter = get_renter(org_id)
    body = body_json()
    req_string(body, "reason")
    if renter["org_standing"] == "BARRED":
        raise errors.invalid_state("Organization is already BARRED")
    renter["org_standing"] = "BARRED"
    touch(renter)
    for r in db.requests.values():
        if r["renter_org_id"] == org_id and r["request_status"] not in (
                "APPROVED", "DENIED", "WITHDRAWN", "EXPIRED"):
            r["request_status"] = "WITHDRAWN"
            touch(r)
    for p in list(db.permits.values()):
        if p["renter_org_id"] == org_id and p["lifecycle_status"] == "ISSUED":
            p["lifecycle_status"] = "CANCELLED"
            cancel_permit_record(p, "ADMINISTRATIVE")
    return response.success(renter_out(renter))


# ---------------------------------------------------------------------------
# Insurance certificates
# ---------------------------------------------------------------------------

def cert_out(c):
    return {k: c[k] for k in (
        "id", "created_at", "updated_at", "version", "renter_org_id",
        "insurer_name", "per_occurrence_limit_cents", "aggregate_limit_cents",
        "effective_from", "effective_to", "cert_status")}


@bp.post("/district/renters/<org_id>/insurance_certificates")
def upload_cert(org_id):
    uid, role = get_auth()
    if role not in ("RenterOrgRep", "FacilitiesDirector"):
        raise errors.forbidden()
    if role == "RenterOrgRep" and uid != org_id:
        raise errors.forbidden()
    get_renter(org_id)
    body = body_json()
    insurer = req_string(body, "insurer_name")
    per_occ = req_int(body, "per_occurrence_limit_cents")
    agg = req_int(body, "aggregate_limit_cents")
    eff_from = req_datetime(body, "effective_from")
    eff_to = req_datetime(body, "effective_to")
    if per_occ <= 0:
        raise errors.invalid_request("per_occurrence_limit_cents must be > 0")
    if agg < per_occ:
        raise errors.invalid_request(
            "aggregate_limit_cents must be >= per_occurrence_limit_cents")
    if eff_to <= eff_from:
        raise errors.invalid_time_window("effective_to must be > effective_from")
    rec = init_common()
    rec.update({
        "renter_org_id": org_id,
        "insurer_name": insurer,
        "per_occurrence_limit_cents": per_occ,
        "aggregate_limit_cents": agg,
        "effective_from": util.iso_z(eff_from),
        "effective_to": util.iso_z(eff_to),
        "cert_status": "VALID",
    })
    db.certificates[rec["id"]] = rec
    return response.success(cert_out(rec), 201)


@bp.get("/district/renters/<org_id>/insurance_certificates")
def list_org_certs(org_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    if role == "RenterOrgRep" and uid != org_id:
        raise errors.forbidden()
    get_renter(org_id)
    status = request.args.get("cert_status")
    rows = [c for c in db.certificates.values() if c["renter_org_id"] == org_id]
    if status:
        rows = [c for c in rows if c["cert_status"] == status]
    rows.sort(key=lambda c: c["created_at"])
    return response.paginate([cert_out(c) for c in rows])


@bp.get("/district/insurance_certificates")
def list_certs():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.certificates.values())
    for param in ("renter_org_id", "cert_status"):
        v = request.args.get(param)
        if v:
            rows = [c for c in rows if c.get(param) == v]
    rows.sort(key=lambda c: c["created_at"])
    return response.paginate([cert_out(c) for c in rows])


@bp.get("/district/insurance_certificates/<cert_id>")
def get_cert_ep(cert_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    cert = get_cert(cert_id)
    if role == "RenterOrgRep" and uid != cert["renter_org_id"]:
        raise errors.forbidden()
    return response.success(cert_out(cert))


@bp.post("/district/insurance_certificates/<cert_id>/revoke")
def revoke_cert(cert_id):
    require_roles("FacilitiesDirector")
    cert = get_cert(cert_id)
    body = body_json()
    req_string(body, "reason")
    if cert["cert_status"] != "VALID":
        raise errors.invalid_state("Certificate is not VALID")
    cert["cert_status"] = "REVOKED"
    touch(cert)
    services._insurance_loss_cascade(cert)
    return response.success(cert_out(cert))


# ---------------------------------------------------------------------------
# School calendar events
# ---------------------------------------------------------------------------

def event_out(e):
    return {k: e[k] for k in (
        "id", "created_at", "updated_at", "version", "site_id", "facility_id",
        "title", "starts_at", "ends_at", "event_priority_tier", "event_status")}


@bp.post("/district/sites/<site_id>/calendar_events")
def create_event(site_id):
    require_roles("DistrictAdmin")
    site = get_site(site_id)
    body = body_json()
    facility_id = opt_string(body, "facility_id")
    title = req_string(body, "title")
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    tier = req_int(body, "event_priority_tier")
    if tier not in (0, 1):
        raise errors.invalid_request("event_priority_tier must be 0 or 1")
    if ends_at <= starts_at:
        raise errors.invalid_time_window("ends_at must be > starts_at")
    if site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    fac = None
    if facility_id is not None:
        fac = get_facility(facility_id)
        if fac["site_id"] != site_id:
            raise errors.reference_invalid(
                "facility_id does not belong to the path site")
    # Non-tier-0 events may not collide with an ISSUED/ACTIVE permit's blocked
    # interval; tier-0 events preempt those permits instead.
    preempt = []
    for p in db.permits.values():
        pf = db.facilities.get(p["facility_id"])
        if pf is None or pf["site_id"] != site_id:
            continue
        if fac is not None and p["facility_id"] != fac["id"]:
            continue
        if p["lifecycle_status"] not in ("ISSUED", "ACTIVE"):
            continue
        if util.overlaps(starts_at, ends_at,
                         util.parse_iso(p["blocked_start"]),
                         util.parse_iso(p["blocked_end"])):
            if tier == 0 and p["lifecycle_status"] == "ISSUED":
                preempt.append(p)
            else:
                raise errors.schedule_conflict(
                    "Event collides with an ISSUED/ACTIVE permit's blocked interval")
    rec = init_common()
    rec.update({
        "site_id": site_id,
        "facility_id": facility_id,
        "title": title,
        "starts_at": util.iso_z(starts_at),
        "ends_at": util.iso_z(ends_at),
        "event_priority_tier": tier,
        "event_status": "SCHEDULED",
    })
    db.calendar_events[rec["id"]] = rec
    for p in preempt:
        p["lifecycle_status"] = "SUPERSEDED"
        p["superseded_by_permit_id"] = None
        cancel_permit_record(p, "ADMINISTRATIVE",
                             zero_refund_status="REFUND_PENDING")
    return response.success(event_out(rec), 201)


@bp.get("/district/sites/<site_id>/calendar_events")
def list_site_events(site_id):
    require_roles(*ALL_ROLES)
    get_site(site_id)
    rows = [e for e in db.calendar_events.values() if e["site_id"] == site_id]
    for param in ("event_status", "facility_id"):
        v = request.args.get(param)
        if v:
            rows = [e for e in rows if (e.get(param) or "") == v]
    rows.sort(key=lambda e: e["created_at"])
    return response.paginate([event_out(e) for e in rows])


@bp.get("/district/calendar_events")
def list_events():
    require_roles(*ALL_ROLES)
    rows = list(db.calendar_events.values())
    for param in ("site_id", "facility_id", "event_status"):
        v = request.args.get(param)
        if v:
            rows = [e for e in rows if (e.get(param) or "") == v]
    rows.sort(key=lambda e: e["created_at"])
    return response.paginate([event_out(e) for e in rows])


@bp.get("/district/calendar_events/<event_id>")
def get_event_ep(event_id):
    require_roles(*ALL_ROLES)
    return response.success(event_out(get_event(event_id)))


@bp.post("/district/calendar_events/<event_id>/cancel")
def cancel_event(event_id):
    require_roles("DistrictAdmin")
    event = get_event(event_id)
    if event["event_status"] != "SCHEDULED":
        raise errors.invalid_state("Calendar event is not SCHEDULED")
    event["event_status"] = "CANCELLED"
    touch(event)
    # Supersession is sticky; the freed window triggers a waitlist sweep.
    if event.get("facility_id"):
        run_waitlist_sweep(event["facility_id"])
    else:
        for f in db.facilities.values():
            if f["site_id"] == event["site_id"]:
                run_waitlist_sweep(f["id"])
    return response.success(event_out(event))
