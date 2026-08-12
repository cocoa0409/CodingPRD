"""Scoped path-parameter resolution (PRD section 2.5).

Path params validate strictly left to right; each identifier must resolve to a
resource that is a descendant of the resource named by the segment before it,
all within the same program scope. Any mismatch returns ERR_NOT_FOUND.
"""
from db import store
from errors import ApiError, ERR_NOT_FOUND


def _nf(what):
    raise ApiError(ERR_NOT_FOUND, 404, "%s not found in the expected scope" % what)


def get_program_or_404(pid):
    p = store.programs.get(pid)
    if p is None:
        _nf("CLTProgram")
    return p


def get_household_or_404(pid, hid):
    h = store.households.get(hid)
    if h is None or h["program_id"] != pid:
        _nf("Household")
    return h


def get_cert_or_404(pid, hid, cid):
    c = store.certs.get(cid)
    if c is None or c["household_id"] != hid:
        _nf("IncomeCertification")
    return c


def get_course_or_404(pid, cid):
    c = store.courses.get(cid)
    if c is None or c["program_id"] != pid:
        _nf("EducationCourse")
    return c


def get_unit_or_404(pid, uid):
    u = store.units.get(uid)
    if u is None or u["program_id"] != pid:
        _nf("Unit")
    return u


def get_lease_or_404(pid, uid, lid):
    l = store.leases.get(lid)
    if l is None or l["unit_id"] != uid:
        _nf("GroundLease")
    return l


def get_fee_or_404(pid, uid, lid, fid):
    f = store.fees.get(fid)
    if f is None or f["lease_id"] != lid:
        _nf("LeaseFee")
    return f


def get_notice_or_404(pid, uid, lid, nid):
    n = store.notices.get(nid)
    if n is None or n["lease_id"] != lid:
        _nf("DefaultNotice")
    return n


def get_inspection_or_404(pid, uid, iid):
    i = store.inspections.get(iid)
    if i is None or i["unit_id"] != uid:
        _nf("InspectionRecord")
    return i


def get_listing_or_404(pid, uid, rid):
    r = store.listings.get(rid)
    if r is None or r["unit_id"] != uid:
        _nf("ResaleListing")
    return r


def get_refi_or_404(pid, uid, lid, rid):
    r = store.refis.get(rid)
    if r is None or r["lease_id"] != lid:
        _nf("RefinanceRequest")
    return r


def get_waitlist_entry_or_404(pid, wid):
    e = store.waitlist.get(wid)
    if e is None:
        _nf("WaitlistEntry")
    h = store.households.get(e["household_id"])
    if h is None or h["program_id"] != pid:
        _nf("WaitlistEntry")
    return e


# --- program-scope helpers -------------------------------------------------

def program_id_of_household(hid):
    h = store.households.get(hid)
    return h["program_id"] if h else None


def program_id_of_unit(uid):
    u = store.units.get(uid)
    return u["program_id"] if u else None


def program_id_of_lease(lid):
    lease = store.leases.get(lid)
    if not lease:
        return None
    return program_id_of_unit(lease["unit_id"])
