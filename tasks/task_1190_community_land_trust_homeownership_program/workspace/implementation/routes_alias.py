"""Canonical top-level aliases and cross-program filtered lists (PRD 2.5)."""
from flask import Blueprint, g, jsonify

from db import store
from auth import require, require_household_owner
from errors import ApiError, ERR_NOT_FOUND
from util import (
    ok_object, paginated, query_bool, query_int, query_str, ser_cert,
    ser_completion, ser_course, ser_fee, ser_household, ser_inspection,
    ser_lease, ser_listing, ser_notice, ser_refi, ser_unit,
    ser_waitlist_entry,
)

bp = Blueprint("alias", __name__)

STAFF5 = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer",
          "LeaseManager", "IntakeSpecialist"]
STAFF5_H = STAFF5 + ["Household"]
UNIT_READ = STAFF5 + ["Inspector"]
UNIT_READ_H = UNIT_READ + ["Household"]
LEASE_READ = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer",
              "LeaseManager", "Household"]
LEASE_STAFF = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer", "LeaseManager"]
INSPECTION_STAFF = ["PlatformAdmin", "ProgramAdmin", "LeaseManager", "Inspector"]
INSPECTION_READ = INSPECTION_STAFF + ["Household"]


def _nf(what):
    raise ApiError(ERR_NOT_FOUND, 404, "%s not found" % what)


# ---------------------------------------------------------------------------
# Get-by-id aliases
# ---------------------------------------------------------------------------

@bp.get("/households/<rid>")
@require(STAFF5_H)
def alias_get_household(rid):
    h = store.households.get(rid)
    if h is None:
        _nf("Household")
    require_household_owner(h["id"])
    return jsonify(ok_object(ser_household(h))), 200


@bp.get("/units/<rid>")
@require(UNIT_READ_H)
def alias_get_unit(rid):
    u = store.units.get(rid)
    if u is None:
        _nf("Unit")
    return jsonify(ok_object(ser_unit(u))), 200


@bp.get("/leases/<rid>")
@require(LEASE_READ)
def alias_get_lease(rid):
    l = store.leases.get(rid)
    if l is None:
        _nf("GroundLease")
    require_household_owner(l["household_id"])
    return jsonify(ok_object(ser_lease(l))), 200


@bp.get("/income-certifications/<rid>")
@require(STAFF5_H)
def alias_get_cert(rid):
    c = store.certs.get(rid)
    if c is None:
        _nf("IncomeCertification")
    require_household_owner(c["household_id"])
    return jsonify(ok_object(ser_cert(c))), 200


@bp.get("/education-courses/<rid>")
@require(UNIT_READ_H)
def alias_get_course(rid):
    c = store.courses.get(rid)
    if c is None:
        _nf("EducationCourse")
    return jsonify(ok_object(ser_course(c))), 200


@bp.get("/education-completions/<rid>")
@require(STAFF5_H)
def alias_get_completion(rid):
    c = store.completions.get(rid)
    if c is None:
        _nf("EducationCompletion")
    require_household_owner(c["household_id"])
    return jsonify(ok_object(ser_completion(c))), 200


@bp.get("/fees/<rid>")
@require(LEASE_READ)
def alias_get_fee(rid):
    f = store.fees.get(rid)
    if f is None:
        _nf("LeaseFee")
    lease = store.leases.get(f["lease_id"])
    if lease:
        require_household_owner(lease["household_id"])
    return jsonify(ok_object(ser_fee(f))), 200


@bp.get("/default-notices/<rid>")
@require(LEASE_READ)
def alias_get_notice(rid):
    n = store.notices.get(rid)
    if n is None:
        _nf("DefaultNotice")
    lease = store.leases.get(n["lease_id"])
    if lease:
        require_household_owner(lease["household_id"])
    return jsonify(ok_object(ser_notice(n))), 200


@bp.get("/inspections/<rid>")
@require(INSPECTION_READ)
def alias_get_inspection(rid):
    i = store.inspections.get(rid)
    if i is None:
        _nf("InspectionRecord")
    return jsonify(ok_object(ser_inspection(i))), 200


@bp.get("/resale-listings/<rid>")
@require(LEASE_READ)
def alias_get_listing(rid):
    l = store.listings.get(rid)
    if l is None:
        _nf("ResaleListing")
    return jsonify(ok_object(ser_listing(l))), 200


@bp.get("/refinance-requests/<rid>")
@require(LEASE_READ)
def alias_get_refi(rid):
    r = store.refis.get(rid)
    if r is None:
        _nf("RefinanceRequest")
    lease = store.leases.get(r["lease_id"])
    if lease:
        require_household_owner(lease["household_id"])
    return jsonify(ok_object(ser_refi(r))), 200


@bp.get("/waitlist-entries/<rid>")
@require(STAFF5_H)
def alias_get_waitlist_entry(rid):
    e = store.waitlist.get(rid)
    if e is None:
        _nf("WaitlistEntry")
    require_household_owner(e["household_id"])
    return jsonify(ok_object(ser_waitlist_entry(e))), 200


# ---------------------------------------------------------------------------
# Cross-program filtered lists
# ---------------------------------------------------------------------------

@bp.get("/households")
@require(STAFF5)
def alias_list_households():
    items = list(store.households.values())
    program_id = query_str("program_id")
    if program_id:
        items = [h for h in items if h["program_id"] == program_id]
    active_lease_id = query_str("active_lease_id")
    if active_lease_id:
        items = [h for h in items if h["active_lease_id"] == active_lease_id]
    waitlist_entry_id = query_str("waitlist_entry_id")
    if waitlist_entry_id:
        items = [h for h in items if h["waitlist_entry_id"] == waitlist_entry_id]
    status = query_str("eligibility_status")
    if status:
        items = [h for h in items if h["eligibility_status"] == status]
    return jsonify(paginated(items, ser_household)), 200


@bp.get("/income-certifications")
@require(STAFF5)
def alias_list_certs():
    items = list(store.certs.values())
    household_id = query_str("household_id")
    if household_id:
        items = [c for c in items if c["household_id"] == household_id]
    status = query_str("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return jsonify(paginated(items, ser_cert)), 200


@bp.get("/education-completions")
@require(STAFF5)
def alias_list_completions():
    items = list(store.completions.values())
    household_id = query_str("household_id")
    if household_id:
        items = [c for c in items if c["household_id"] == household_id]
    course_id = query_str("course_id")
    if course_id:
        items = [c for c in items if c["course_id"] == course_id]
    return jsonify(paginated(items, ser_completion)), 200


@bp.get("/units")
@require(UNIT_READ)
def alias_list_units():
    items = list(store.units.values())
    program_id = query_str("program_id")
    if program_id:
        items = [u for u in items if u["program_id"] == program_id]
    current_lease_id = query_str("current_lease_id")
    if current_lease_id:
        items = [u for u in items if u["current_lease_id"] == current_lease_id]
    occupancy = query_str("occupancy_status")
    if occupancy:
        items = [u for u in items if u["occupancy_status"] == occupancy]
    flag = query_str("maintenance_flag")
    if flag:
        items = [u for u in items if u["maintenance_flag"] == flag]
    return jsonify(paginated(items, ser_unit)), 200


@bp.get("/leases")
@require(LEASE_STAFF)
def alias_list_leases():
    items = list(store.leases.values())
    unit_id = query_str("unit_id")
    if unit_id:
        items = [l for l in items if l["unit_id"] == unit_id]
    household_id = query_str("household_id")
    if household_id:
        items = [l for l in items if l["household_id"] == household_id]
    status = query_str("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return jsonify(paginated(items, ser_lease)), 200


@bp.get("/fees")
@require(LEASE_STAFF)
def alias_list_fees():
    items = list(store.fees.values())
    lease_id = query_str("lease_id")
    if lease_id:
        items = [f for f in items if f["lease_id"] == lease_id]
    status = query_str("status")
    if status:
        items = [f for f in items if f["status"] == status]
    return jsonify(paginated(items, ser_fee)), 200


@bp.get("/default-notices")
@require(LEASE_STAFF)
def alias_list_notices():
    items = list(store.notices.values())
    lease_id = query_str("lease_id")
    if lease_id:
        items = [n for n in items if n["lease_id"] == lease_id]
    status = query_str("status")
    if status:
        items = [n for n in items if n["status"] == status]
    kind = query_str("notice_kind")
    if kind:
        items = [n for n in items if n["notice_kind"] == kind]
    return jsonify(paginated(items, ser_notice)), 200


@bp.get("/inspections")
@require(INSPECTION_STAFF)
def alias_list_inspections():
    items = list(store.inspections.values())
    unit_id = query_str("unit_id")
    if unit_id:
        items = [i for i in items if i["unit_id"] == unit_id]
    linked_notice_id = query_str("linked_notice_id")
    if linked_notice_id:
        items = [i for i in items if i["linked_notice_id"] == linked_notice_id]
    result = query_str("result")
    if result:
        items = [i for i in items if i["result"] == result]
    return jsonify(paginated(items, ser_inspection)), 200


@bp.get("/resale-listings")
@require(LEASE_STAFF)
def alias_list_listings():
    items = list(store.listings.values())
    unit_id = query_str("unit_id")
    if unit_id:
        items = [l for l in items if l["unit_id"] == unit_id]
    seller_lease_id = query_str("seller_lease_id")
    if seller_lease_id:
        items = [l for l in items if l["seller_lease_id"] == seller_lease_id]
    matched = query_str("matched_waitlist_entry_id")
    if matched:
        items = [l for l in items if l["matched_waitlist_entry_id"] == matched]
    buyer = query_str("buyer_household_id")
    if buyer:
        items = [l for l in items if l["buyer_household_id"] == buyer]
    status = query_str("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return jsonify(paginated(items, ser_listing)), 200


@bp.get("/refinance-requests")
@require(LEASE_STAFF)
def alias_list_refis():
    items = list(store.refis.values())
    lease_id = query_str("lease_id")
    if lease_id:
        items = [r for r in items if r["lease_id"] == lease_id]
    status = query_str("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return jsonify(paginated(items, ser_refi)), 200


@bp.get("/education-courses")
@require(UNIT_READ)
def alias_list_courses():
    items = list(store.courses.values())
    program_id = query_str("program_id")
    if program_id:
        items = [c for c in items if c["program_id"] == program_id]
    is_required = query_bool("is_required")
    if is_required is not None:
        items = [c for c in items if c["is_required"] == is_required]
    status = query_str("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return jsonify(paginated(items, ser_course)), 200


@bp.get("/waitlist-entries")
@require(STAFF5)
def alias_list_waitlist():
    items = list(store.waitlist.values())
    household_id = query_str("household_id")
    if household_id:
        items = [e for e in items if e["household_id"] == household_id]
    matched_unit_id = query_str("matched_unit_id")
    if matched_unit_id:
        items = [e for e in items if e["matched_unit_id"] == matched_unit_id]
    status = query_str("status")
    if status:
        items = [e for e in items if e["status"] == status]
    return jsonify(paginated(items, ser_waitlist_entry)), 200
