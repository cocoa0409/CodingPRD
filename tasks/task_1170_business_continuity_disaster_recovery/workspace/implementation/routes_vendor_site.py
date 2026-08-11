"""Third parties, assessments, alternate sites, seat reservations
(PRD §3.4, §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from calc import (assessment_compute, create_gap, site_utilization)
from core import (ALL_ROLES, DB, actor, apply_filters, as_dt, as_enum, as_int,
                  as_num, as_str, body, bump, fail, fmt_dt, money2, not_found,
                  now_dt, ok, opt_str, paginate, parse_dt, req,
                  sorted_by_created, stamp_new, validation)
from routes_registry import get_process_or_404
from serializers import (assessment_view, reservation_view, site_view,
                         third_party_view)

bp = Blueprint("vendor_site", __name__)

VENDOR_CRITICALITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ASSESSMENT_TYPES = ["INITIAL", "ANNUAL", "EVENT_DRIVEN"]
SITE_TYPES = ["HOT", "WARM", "COLD", "WORK_AREA_RECOVERY"]
PURPOSES = ["EXERCISE", "INCIDENT"]


def get_vendor_or_404(vendor_id):
    t = DB.third_parties.get(vendor_id)
    if t is None:
        not_found("ERR_VENDOR_NOT_FOUND", "Third party")
    return t


def get_site_or_404(site_id):
    s = DB.sites.get(site_id)
    if s is None:
        not_found("ERR_SITE_NOT_FOUND", "Alternate site")
    return s


# --------------------------------------------------------------------------
# Third parties
# --------------------------------------------------------------------------

@bp.post("/resilience/third-parties")
def create_third_party():
    actor(["VendorManager"])
    payload = body()
    name = as_str(req(payload, "name"), "name")
    service_category = as_str(req(payload, "service_category"),
                              "service_category")
    rating = as_enum(req(payload, "criticality_rating"), "criticality_rating",
                     VENDOR_CRITICALITIES)
    owner_contact_id = req(payload, "owner_contact_id")
    if owner_contact_id not in DB.contacts:
        not_found("ERR_CONTACT_NOT_FOUND", "Contact")
    for t in DB.third_parties.values():
        if t["name"] == name:
            fail("ERR_DUPLICATE", 409, "A third party with this name exists")
    t = {"name": name, "service_category": service_category,
         "criticality_rating": rating, "owner_contact_id": owner_contact_id,
         "status": "ONBOARDING"}
    stamp_new(t)
    DB.third_parties[t["id"]] = t
    return ok(third_party_view(t), status=201)


@bp.get("/resilience/third-parties")
def list_third_parties():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.third_parties.values()), [
        ("status", "status"),
        ("criticality_rating", "criticality_rating"),
        ("owner_contact_id", "owner_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([third_party_view(t) for t in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/third-parties/<thirdPartyId>")
def get_third_party(thirdPartyId):
    actor(ALL_ROLES)
    return ok(third_party_view(get_vendor_or_404(thirdPartyId)))


@bp.post("/resilience/third-parties/<thirdPartyId>/activate")
def activate_third_party(thirdPartyId):
    actor(["VendorManager"])
    t = get_vendor_or_404(thirdPartyId)
    if t["status"] not in ("ONBOARDING", "SUSPENDED"):
        fail("ERR_INVALID_STATE", 409,
             "A vendor may be activated only from ONBOARDING or SUSPENDED")
    t["status"] = "ACTIVE"
    bump(t)
    return ok(third_party_view(t))


@bp.post("/resilience/third-parties/<thirdPartyId>/suspend")
def suspend_third_party(thirdPartyId):
    actor(["VendorManager"])
    t = get_vendor_or_404(thirdPartyId)
    if t["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409,
             "A vendor may be suspended only from ACTIVE")
    t["status"] = "SUSPENDED"
    bump(t)
    return ok(third_party_view(t))


def _flip_referencing_capabilities(capability_type, ref_id):
    """VALIDATED capabilities referencing the entity -> GAP_IDENTIFIED + gap."""
    for cap in DB.capabilities.values():
        if (cap["capability_type"] == capability_type
                and cap["capability_ref_id"] == ref_id
                and cap["status"] == "VALIDATED"):
            cap["status"] = "GAP_IDENTIFIED"
            bump(cap)
            create_gap(
                process_id=cap["process_id"],
                capability_id=cap["id"],
                finding_id=None,
                severity="HIGH",
                description=(f"Referenced {capability_type.lower()} {ref_id} "
                             f"is no longer available"),
                due_date=now_dt() + timedelta(days=90),
            )


@bp.post("/resilience/third-parties/<thirdPartyId>/exit")
def exit_third_party(thirdPartyId):
    actor(["VendorManager"])
    t = get_vendor_or_404(thirdPartyId)
    if t["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", 409,
             "A vendor may exit only from ACTIVE or SUSPENDED")
    _flip_referencing_capabilities("VENDOR_FAILOVER", t["id"])
    t["status"] = "EXITED"
    bump(t)
    return ok(third_party_view(t))


@bp.get("/resilience/third-parties/<thirdPartyId>/assessments")
def vendor_assessments(thirdPartyId):
    actor(ALL_ROLES)
    get_vendor_or_404(thirdPartyId)
    items = [a for a in DB.assessments.values()
             if a["third_party_id"] == thirdPartyId]
    page, meta = paginate(sorted_by_created(items))
    return ok([assessment_view(a) for a in page], response_type="array",
              pagination=meta)


# --------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------

def get_assessment_or_404(assessment_id):
    a = DB.assessments.get(assessment_id)
    if a is None:
        not_found("ERR_ASSESSMENT_NOT_FOUND", "Assessment")
    return a


@bp.post("/resilience/assessments")
def create_assessment():
    actor(["VendorManager"])
    payload = body()
    third_party_id = req(payload, "third_party_id")
    if third_party_id not in DB.third_parties:
        not_found("ERR_VENDOR_NOT_FOUND", "Third party")
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    a_type = as_enum(req(payload, "assessment_type"), "assessment_type",
                     ASSESSMENT_TYPES)
    assessed_rto = as_int(req(payload, "assessed_rto_hours"),
                          "assessed_rto_hours", minv=0)
    assessed_rpo = as_int(req(payload, "assessed_rpo_hours"),
                          "assessed_rpo_hours", minv=0)
    req_rto = as_int(req(payload, "rto_required_hours"), "rto_required_hours",
                     minv=0)
    req_rpo = as_int(req(payload, "rpo_required_hours"), "rpo_required_hours",
                     minv=0)
    evidence = opt_str(payload, "evidence_doc_ref")
    a = {"third_party_id": third_party_id, "process_id": process_id,
         "assessment_type": a_type, "assessed_rto_hours": assessed_rto,
         "assessed_rpo_hours": assessed_rpo, "evidence_doc_ref": evidence,
         "rto_required_hours": req_rto, "rpo_required_hours": req_rpo,
         "score_variant": "PROVISIONAL", "finalized_by_contact_id": None,
         "status": "DRAFT"}
    assessment_compute(a, final=False)
    stamp_new(a)
    DB.assessments[a["id"]] = a
    return ok(assessment_view(a), status=201)


@bp.get("/resilience/assessments")
def list_assessments():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.assessments.values()), [
        ("third_party_id", "third_party_id"),
        ("process_id", "process_id"),
        ("status", "status"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([assessment_view(a) for a in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/assessments/<assessmentId>")
def get_assessment(assessmentId):
    actor(ALL_ROLES)
    return ok(assessment_view(get_assessment_or_404(assessmentId)))


@bp.put("/resilience/assessments/<assessmentId>")
def update_assessment(assessmentId):
    actor(["VendorManager"])
    a = get_assessment_or_404(assessmentId)
    payload = body()
    updates = {}
    for key in ("assessed_rto_hours", "assessed_rpo_hours",
                "rto_required_hours", "rpo_required_hours"):
        if key in payload and payload[key] is not None:
            updates[key] = as_int(payload[key], key, minv=0)
    if "evidence_doc_ref" in payload and payload["evidence_doc_ref"] is not None:
        updates["evidence_doc_ref"] = as_str(payload["evidence_doc_ref"],
                                             "evidence_doc_ref")
    if a["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "An assessment may be updated only while DRAFT")
    for key, value in updates.items():
        a[key] = value
    assessment_compute(a, final=False)
    bump(a)
    return ok(assessment_view(a))


@bp.post("/resilience/assessments/<assessmentId>/finalize")
def finalize_assessment(assessmentId):
    who = actor(["VendorManager"], sod_identity=True)
    a = get_assessment_or_404(assessmentId)
    if a["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "An assessment may be finalized only from DRAFT")
    vendor = DB.third_parties.get(a["third_party_id"])
    if vendor is not None and vendor["owner_contact_id"] == who["id"]:
        fail("ERR_SOD_VIOLATION", 403,
             "The finalizing contact must differ from the vendor owner")
    if vendor is None or vendor["status"] != "ACTIVE":
        fail("ERR_VENDOR_NOT_ACTIVE", 409,
             "The referenced third party must be ACTIVE")
    assessment_compute(a, final=True)
    a["score_variant"] = "FINAL"
    a["finalized_by_contact_id"] = who["id"]
    a["status"] = "FINALIZED"
    bump(a)
    if not a["meets_required_rto"]:
        create_gap(
            process_id=a["process_id"],
            capability_id=None,
            finding_id=None,
            severity="HIGH",
            description=(f"Vendor assessment {a['id']} missed the required "
                         f"RTO for process {a['process_id']}"),
            due_date=now_dt() + timedelta(days=90),
        )
    return ok(assessment_view(a))


# --------------------------------------------------------------------------
# Alternate sites
# --------------------------------------------------------------------------

@bp.post("/resilience/alternate-sites")
def create_site():
    actor(["SiteCoordinator"])
    payload = body()
    name = as_str(req(payload, "name"), "name")
    site_type = as_enum(req(payload, "site_type"), "site_type", SITE_TYPES)
    region = as_str(req(payload, "region"), "region")
    capacity = as_int(req(payload, "capacity_seats"), "capacity_seats", minv=1)
    contracted = as_dt(req(payload, "contracted_through"), "contracted_through")
    cost = money2(as_num(req(payload, "monthly_cost"), "monthly_cost", minv=0))
    for s in DB.sites.values():
        if s["name"] == name:
            fail("ERR_DUPLICATE", 409, "A site with this name already exists")
    s = {"name": name, "site_type": site_type, "region": region,
         "capacity_seats": capacity, "contracted_through": contracted,
         "monthly_cost": cost, "status": "ACTIVE"}
    stamp_new(s)
    DB.sites[s["id"]] = s
    return ok(site_view(s), status=201)


@bp.get("/resilience/alternate-sites")
def list_sites():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.sites.values()), [
        ("site_type", "site_type"),
        ("region", "region"),
        ("status", "status"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([site_view(s) for s in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/alternate-sites/<siteId>")
def get_site(siteId):
    actor(ALL_ROLES)
    return ok(site_view(get_site_or_404(siteId)))


@bp.post("/resilience/alternate-sites/<siteId>/retire")
def retire_site(siteId):
    actor(["ResilienceAdmin"])
    s = get_site_or_404(siteId)
    if s["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "A site may be retired only from ACTIVE")
    if any(r["site_id"] == siteId and r["status"] == "CONFIRMED"
           for r in DB.reservations.values()):
        fail("ERR_SITE_HAS_ACTIVE_RESERVATIONS", 409,
             "The site has CONFIRMED reservations")
    _flip_referencing_capabilities("SITE", siteId)
    s["status"] = "RETIRED"
    bump(s)
    return ok(site_view(s))


@bp.get("/resilience/alternate-sites/<siteId>/reservations")
def site_reservations(siteId):
    actor(ALL_ROLES)
    get_site_or_404(siteId)
    items = [r for r in DB.reservations.values() if r["site_id"] == siteId]
    page, meta = paginate(sorted_by_created(items))
    return ok([reservation_view(r) for r in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/alternate-sites/<siteId>/utilization")
def site_utilization_read(siteId):
    actor(ALL_ROLES)
    s = get_site_or_404(siteId)
    raw_probe = request.args.get("probe_at")
    if raw_probe is None:
        probe = now_dt()
    else:
        probe = parse_dt(raw_probe)
        if probe is None:
            validation("probe_at must be an ISO 8601 UTC timestamp")
    reserved, pct = site_utilization(s, probe)
    return ok({"capacity_seats": s["capacity_seats"],
               "reserved_seats": reserved,
               "utilization_pct": pct,
               "probe_at": fmt_dt(probe)})


# --------------------------------------------------------------------------
# Site reservations
# --------------------------------------------------------------------------

def get_reservation_or_404(reservation_id):
    r = DB.reservations.get(reservation_id)
    if r is None:
        not_found("ERR_RESERVATION_NOT_FOUND", "Site reservation")
    return r


def _windows_overlap_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/resilience/site-reservations")
def create_reservation():
    actor(["SiteCoordinator"])
    payload = body()
    site_id = req(payload, "site_id")
    site = DB.sites.get(site_id)
    if site is None:
        not_found("ERR_SITE_NOT_FOUND", "Alternate site")
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    purpose = as_enum(req(payload, "purpose"), "purpose", PURPOSES)
    seats = as_int(req(payload, "seats_reserved"), "seats_reserved", minv=1)
    starts = as_dt(req(payload, "starts_at"), "starts_at")
    ends = as_dt(req(payload, "ends_at"), "ends_at")
    created_by = req(payload, "created_by_contact_id")
    if created_by not in DB.contacts:
        not_found("ERR_CONTACT_NOT_FOUND", "Contact")
    if ends <= starts:
        validation("ends_at must be strictly after starts_at")
    # Temporal guards (PRD §2.10 layer 12): capacity, same-process overlap,
    # contract currency — in that order.
    overlapping = [r for r in DB.reservations.values()
                   if r["site_id"] == site_id and r["status"] == "CONFIRMED"
                   and _windows_overlap_half_open(r["starts_at"], r["ends_at"],
                                                  starts, ends)]
    if sum(r["seats_reserved"] for r in overlapping) + seats \
            > site["capacity_seats"]:
        fail("ERR_SITE_CAPACITY_EXCEEDED", 422,
             "Aggregate overlapping seats exceed the site capacity")
    if any(r["process_id"] == process_id for r in overlapping):
        fail("ERR_SITE_WINDOW_OVERLAP", 409,
             "The process already holds an overlapping CONFIRMED reservation")
    if ends > site["contracted_through"]:
        fail("ERR_SITE_CONTRACT_EXPIRED", 422,
             "Reservation window extends past the site contract")
    r = {"site_id": site_id, "process_id": process_id, "purpose": purpose,
         "seats_reserved": seats, "starts_at": starts, "ends_at": ends,
         "created_by_contact_id": created_by, "status": "CONFIRMED"}
    stamp_new(r)
    DB.reservations[r["id"]] = r
    return ok(reservation_view(r), status=201)


@bp.get("/resilience/site-reservations")
def list_reservations():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.reservations.values()), [
        ("site_id", "site_id"),
        ("process_id", "process_id"),
        ("status", "status"),
        ("created_by_contact_id", "created_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([reservation_view(r) for r in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/site-reservations/<reservationId>")
def get_reservation(reservationId):
    actor(ALL_ROLES)
    return ok(reservation_view(get_reservation_or_404(reservationId)))


@bp.post("/resilience/site-reservations/<reservationId>/release")
def release_reservation(reservationId):
    who = actor(["SiteCoordinator"], sod_identity=True)
    r = get_reservation_or_404(reservationId)
    if r["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", 409,
             "A reservation may be released only from CONFIRMED")
    if r["created_by_contact_id"] == who["id"]:
        fail("ERR_SOD_VIOLATION", 403,
             "The releasing contact must differ from the creator")
    r["status"] = "RELEASED"
    bump(r)
    return ok(reservation_view(r))
