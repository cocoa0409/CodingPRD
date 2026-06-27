"""Cascades: the serious-incident 3-hop chain, clinic-cancel 2-hop chain,
membership-cancel enrollment withdrawal, plus single-hop side effects.

Covers the two transitive-cascade difficulty instances and corner instances on
the membership-cancel cascade, incident resolution, and withdraw decrement.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_member, create_membership, create_clinic, create_facility,
    create_member_with_active_membership, create_clinic_with_one_enrollment,
    enroll, set_clock, setup_serious_incident_scenario,
    make_member_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: serious-incident 3-hop cascade ───────────────────────────
def test_serious_incident_three_hop_cascade(api):
    """PRD §3.9: "When the severity is SERIOUS, filing the incident fires a
    three-hop cascade atomically at creation. First, if a certification_id was
    supplied, the referenced certification — when it is in status PASSED or
    EXPIRED — is revoked, moving to REVOKED and bumping that certification's
    version. Second, the involved member's membership, if its access_status is
    ACTIVE or FROZEN, is suspended, moving access_status to SUSPENDED and bumping
    that membership's version. Third, every check-in the member currently has
    ON_FLOOR is automatically checked out, each moving to CHECKED_OUT and
    prompting a recompute of the affected facility's occupancy and a bump of its
    version."

    Design: Difficulty/transitive_cascade/serious_incident_three_hop_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_serious_incident_scenario()
    member, cert = ctx["member"], ctx["cert"]
    membership, facility, checkin = ctx["membership"], ctx["facility"], ctx["checkin"]
    assert cert["status"] == "PASSED"

    validate_success(api.create_incident({
        "member_id": member["id"], "facility_id": facility["id"],
        "severity": "SERIOUS", "description": "Belay slip",
        "certification_id": cert["id"],
    }, ADMIN), 201)

    cert_after = validate_success(api.get_certification(cert["id"], ADMIN), 200)
    assert cert_after["status"] == "REVOKED", "hop 1: cert revoked"
    ms_after = validate_success(api.get_membership(membership["id"], FD), 200)
    assert ms_after["access_status"] == "SUSPENDED", "hop 2: membership suspended"
    ci_after = validate_success(api.get_checkin(checkin["id"], FD), 200)
    assert ci_after["status"] == "CHECKED_OUT", "hop 3: checked off the floor"
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 0, "hop 3: facility occupancy recomputed"


def test_minor_incident_fires_no_cascade(api):
    """PRD §3.9: "A MINOR incident fires no cascade."

    Design: Difficulty/transitive_cascade/serious_incident_three_hop_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_serious_incident_scenario()
    member, cert = ctx["member"], ctx["cert"]
    membership, facility, checkin = ctx["membership"], ctx["facility"], ctx["checkin"]

    validate_success(api.create_incident({
        "member_id": member["id"], "facility_id": facility["id"],
        "severity": "MINOR", "description": "Scraped knee",
        "certification_id": cert["id"],
    }, ADMIN), 201)

    cert_after = validate_success(api.get_certification(cert["id"], ADMIN), 200)
    assert cert_after["status"] == "PASSED", "MINOR: cert untouched"
    ms_after = validate_success(api.get_membership(membership["id"], FD), 200)
    assert ms_after["access_status"] == "ACTIVE", "MINOR: membership untouched"
    ci_after = validate_success(api.get_checkin(checkin["id"], FD), 200)
    assert ci_after["status"] == "ON_FLOOR", "MINOR: still on the floor"


# ─── Difficulty: clinic-cancel 2-hop cascade ──────────────────────────────
def test_clinic_cancel_withdraws_enrollment_cascade(api):
    """PRD §3.8: "Cancelling a clinic is a gym-administrator action valid only
    while the clinic is SCHEDULED (else ERR_INVALID_STATE). It carries
    expected_clinic_version, moves status from SCHEDULED to CANCELLED, withdraws
    every enrollment that is still ENROLLED (each moving to WITHDRAWN), recomputes
    enrolled_count down to 0, and increments the clinic's version."

    Design: Difficulty/transitive_cascade/clinic_cancel_two_hop_enrollment_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, member, enrollment = create_clinic_with_one_enrollment(seat_capacity=8)
    cancelled = validate_success(api.cancel_clinic(
        clinic["id"], {"expected_clinic_version": clinic["version"]}, ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["enrolled_count"] == 0
    en_after = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
    assert en_after["status"] == "WITHDRAWN"


def test_clinic_cancel_recomputes_enrolled_count_to_zero(api):
    """PRD §3.8: "withdraws every enrollment that is still ENROLLED (each moving
    to WITHDRAWN), recomputes enrolled_count down to 0, and increments the
    clinic's version."

    Design: Difficulty/transitive_cascade/clinic_cancel_two_hop_enrollment_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, member, enrollment = create_clinic_with_one_enrollment(seat_capacity=8)
    assert clinic["enrolled_count"] == 1
    cancelled = validate_success(api.cancel_clinic(
        clinic["id"], {"expected_clinic_version": clinic["version"]}, ADMIN), 200)
    assert cancelled["enrolled_count"] == 0


# ─── Corner: membership cancel withdraws active enrollments ───────────────
def test_membership_cancel_withdraws_active_enrollments(api):
    """PRD §3.2: "Cancelling moves billing_status to CANCELLED and, crossing axes,
    moves access_status to TERMINATED. As a cascade, every still-active enrollment
    belonging to this member is withdrawn (each affected enrollment moves to
    WITHDRAWN, and each affected clinic has its enrolled_count recomputed and its
    version bumped)."

    Design: Corner/state_machines/membership_cancel_withdraws_active_enrollments
    """
    set_clock("2026-06-01T00:00:00Z")
    member, membership = create_member_with_active_membership()
    clinic = create_clinic(seat_capacity=5)
    enrollment = enroll(clinic["id"], member["id"], clinic["version"])
    cancelled = validate_success(api.cancel_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        make_member_headers(member["id"])), 200)
    assert cancelled["access_status"] == "TERMINATED"
    en_after = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
    assert en_after["status"] == "WITHDRAWN"
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 0


# ─── Corner: enrollment withdraw decrements count ─────────────────────────
def test_enrollment_withdraw_decrements_count(api):
    """PRD §3.8: "A member may withdraw from a clinic, which moves their
    enrollment from ENROLLED to WITHDRAWN, recomputes the clinic's enrolled_count,
    and bumps the clinic's version."

    Design: Corner/state_machines/enrollment_withdraw_decrements_count
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, member, enrollment = create_clinic_with_one_enrollment(seat_capacity=5)
    assert clinic["enrolled_count"] == 1
    withdrawn = validate_success(api.withdraw_enrollment(
        enrollment["id"], make_member_headers(member["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 0


# ─── Corner: incident resolve OPEN -> RESOLVED ────────────────────────────
def test_resolve_open_incident(api):
    """PRD §3.9: "an open incident is later closed by a gym administrator, moving
    status from OPEN to RESOLVED and incrementing the incident's version;
    resolving is valid only from OPEN, else ERR_INVALID_STATE."

    Design: Corner/state_machines/incident_resolve_open_to_resolved
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    facility = create_facility(name="Inc Wall", floor_capacity=10)
    incident = validate_success(api.create_incident({
        "member_id": member["id"], "facility_id": facility["id"],
        "severity": "MINOR", "description": "Scraped knee",
    }, ADMIN), 201)
    assert incident["status"] == "OPEN"
    resolved = validate_success(api.resolve_incident(incident["id"], ADMIN), 200)
    assert resolved["status"] == "RESOLVED"
