"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty before each test. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.

Opaque operator ids used throughout (recorded on entities, never compared to
an entity id): PlatformAdmin admin-1 / admin-2, PropertyManager mgr-1 / mgr-2,
UniversityPartner uni-admin-su. Student headers are always built from the
actual Student.id via make_student_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_student_headers, make_manager_headers, make_partner_headers, make_admin_headers,
)
from . import factories as F

ADMIN = make_admin_headers("admin-1")
ADMIN2 = make_admin_headers("admin-2")
MGR = make_manager_headers("mgr-1")
MGR2 = make_manager_headers("mgr-2")


def _d(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Granular builders
# --------------------------------------------------------------------------
def create_university(api, **over):
    return _d(api.create_university(F.create_university_payload(**over), ADMIN))


def create_property(api, university_id, manager_id="mgr-1", **over):
    return _d(api.create_property(
        F.create_property_payload(university_id, **over), make_manager_headers(manager_id)))


def create_unit(api, property_id, manager_id="mgr-1", **over):
    return _d(api.create_unit(
        F.create_unit_payload(property_id, **over), make_manager_headers(manager_id)))


def list_property(api, property_id, manager_id="mgr-1"):
    return _d(api.list_property(property_id, make_manager_headers(manager_id)))


def create_student(api, university_id, email, **over):
    return _d(api.create_student(F.create_student_payload(university_id, email, **over), ADMIN))


def verify_student(api, student_id, partner_id="uni-admin-su"):
    """Drive a student UNVERIFIED -> PENDING -> VERIFIED."""
    api.request_verification(student_id, make_student_headers(student_id))
    api.decide_verification(student_id, {"decision": "APPROVE"}, make_partner_headers(partner_id))
    return _d(api.get_student(student_id, ADMIN))


def set_clock(api, to_iso8601):
    return _d(api.set_clock(to_iso8601, ADMIN))


def get_lease(api, lease_id):
    return _d(api.get_lease(lease_id, ADMIN))


def get_unit(api, unit_id):
    return _d(api.get_unit(unit_id, ADMIN))


def get_property(api, property_id):
    return _d(api.get_property(property_id, ADMIN))


def get_student(api, student_id):
    return _d(api.get_student(student_id, ADMIN))


def rent_installments(api, lease_id, student_id):
    """Return the lease's RENT installments ordered by sequence_number ASC."""
    data, _ = _paginate(api, lease_id, student_id, {"kind": "RENT"})
    return data


def all_installments(api, lease_id, student_id, params=None):
    data, meta = _paginate(api, lease_id, student_id, params or {})
    return data, meta


def _paginate(api, lease_id, student_id, params):
    resp = api.list_lease_installments(lease_id, make_student_headers(student_id),
                                       params={**params, "limit": 100})
    body = resp.json()
    return body["data"], body["meta"]


# --------------------------------------------------------------------------
# Base property fixture (SU / Maple Commons / one 4-bed unit, LISTED)
# --------------------------------------------------------------------------
def base_property(api, verification_required=True, partner_tier="PREFERRED",
                  rent=90000, bed_labels=("A", "B", "C", "D"), unit_over=None,
                  code="SU", partner_admin="uni-admin-su"):
    """Create university SU (PREFERRED, AY 2026-08-15..2027-05-15), property
    Maple Commons owned by mgr-1, one 4-bed unit at `rent`, and list it.

    Returns dict with keys: uni, prop, unit, manager_id, partner_id.
    """
    uni = create_university(api, code=code, partner_tier=partner_tier,
                            verification_required=verification_required,
                            partner_admin_user_id=partner_admin)
    prop = create_property(api, uni["id"])
    unit_kwargs = {"bed_labels": list(bed_labels), "bedroom_count": len(bed_labels),
                   "base_rent_cents_per_bed_monthly": rent}
    if unit_over:
        unit_kwargs.update(unit_over)
    unit = create_unit(api, prop["id"], **unit_kwargs)
    list_property(api, prop["id"])
    return {"uni": uni, "prop": prop, "unit": unit,
            "manager_id": "mgr-1", "partner_id": partner_admin}


def verified_student(api, university_id, email, partner_id="uni-admin-su", **over):
    s = create_student(api, university_id, email, **over)
    verify_student(api, s["id"], partner_id)
    return _d(api.get_student(s["id"], ADMIN))


# --------------------------------------------------------------------------
# Lease lifecycle shortcuts
# --------------------------------------------------------------------------
def draft_lease(api, student_id, unit_id, bed_label="A", **over):
    return _d(api.create_lease(
        F.create_lease_payload(student_id, unit_id, bed_label, **over),
        make_student_headers(student_id)))


def submit_lease(api, lease_id, student_id):
    return _d(api.submit_lease(lease_id, make_student_headers(student_id)))


def sign_lease(api, lease_id, student_id):
    return _d(api.sign_lease(lease_id, make_student_headers(student_id)))


def active_lease(api, student_id, unit_id, bed_label="A", **over):
    """Create -> submit -> sign a lease for a student who is already VERIFIED,
    on a unit whose property is LISTED. Returns the signed (ACTIVE) lease."""
    lease = draft_lease(api, student_id, unit_id, bed_label, **over)
    submit_lease(api, lease["id"], student_id)
    return sign_lease(api, lease["id"], student_id)


def setup_active_lease(api, rent=90000, installment_count=10, bed_label="A",
                       verification_required=True, partner_tier="PREFERRED"):
    """The single most common scenario: base property + one VERIFIED student
    holding an ACTIVE lease on the given bed.

    Returns dict: base, student, lease (all raw entity dicts), plus student_id.
    """
    base = base_property(api, verification_required=verification_required,
                         partner_tier=partner_tier, rent=rent)
    student = verified_student(api, base["uni"]["id"], "ava@su.edu",
                               full_name="Ava Lead", cleanliness_level=4,
                               noise_tolerance=3, sleep_schedule="EARLY")
    lease = active_lease(api, student["id"], base["unit"]["id"], bed_label,
                         installment_count=installment_count)
    return {"base": base, "student": student, "lease": lease,
            "student_id": student["id"], "prop": base["prop"], "unit": base["unit"],
            "uni": base["uni"]}


# --------------------------------------------------------------------------
# Roommate group builder
# --------------------------------------------------------------------------
def build_group_with_accepted_members(api, property_id, lead_student_id, member_ids,
                                      required_size, name="Test Group"):
    """Create a FORMING group led by lead_student_id, invite each member id,
    and have each accept. Returns (group, [membership dicts in invite order])."""
    group = _d(api.create_roommate_group(
        {"property_id": property_id, "name": name, "required_size": required_size},
        make_student_headers(lead_student_id)))
    memberships = []
    for mid in member_ids:
        m = _d(api.invite_to_group(group["id"], {"student_id": mid},
                                   make_student_headers(lead_student_id)))
        memberships.append(m)
    for mid, m in zip(member_ids, memberships):
        api.respond_membership(m["id"], {"decision": "ACCEPT"}, make_student_headers(mid))
    group = _d(api.get_roommate_group(group["id"], ADMIN))
    return group, memberships
