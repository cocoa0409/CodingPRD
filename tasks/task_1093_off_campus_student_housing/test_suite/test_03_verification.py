"""Student enrollment verification state machine, TTL boundary, clock guard,
and the cross-entity verification gate on lease submission.

Translates the student-verification entries of the corner `state_machines`
section (queue B) and the difficulty `cross_entity_state_dependency` instance
`lease_submit_gated_by_student_verification_status` (queue A).
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers, make_partner_headers

ADMIN = TEST_USERS["admin_headers"]
PARTNER = make_partner_headers("uni-admin-su")


def test_student_verification_invalid_state_and_reject_retry_loop(api):
    """PRD §3.1: "requesting from PENDING or VERIFIED is refused with
    ERR_STUDENT_INVALID_STATE." PRD §3.1: "That request stamps
    verification_submitted_at to the current clock and sets
    verification_expires_at to fourteen (14) days later." PRD §3.1: "from
    REJECTED, which is the revert loop that lets a rejected student try again".

    Design: Corner/state_machines/student_verification_invalid_state_and_reject_retry_loop
    """
    uni = fx.create_university(api)
    s = fx.create_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    sid = s["id"]
    validate_error(api.decide_verification(sid, {"decision": "APPROVE"}, PARTNER),
                   ApiErrorId.ERR_STUDENT_INVALID_STATE.value)
    assert fx.get_student(api, sid)["verification_status"] == "UNVERIFIED"
    req = validate_success(api.request_verification(sid, make_student_headers(sid)), 200)
    assert req["verification_status"] == "PENDING"
    assert req["verification_expires_at"] == "2026-05-15T00:00:00.000Z"
    rej = validate_success(api.decide_verification(sid, {"decision": "REJECT",
                           "note": "Enrollment not confirmed"}, PARTNER), 200)
    assert rej["verification_status"] == "REJECTED"
    req2 = validate_success(api.request_verification(sid, make_student_headers(sid)), 200)
    assert req2["verification_status"] == "PENDING"
    appr = validate_success(api.decide_verification(sid, {"decision": "APPROVE"}, PARTNER), 200)
    assert appr["verification_status"] == "VERIFIED"
    assert api.get_university(uni["id"], ADMIN).json()["data"]["verified_student_count"] == 1


def test_student_verification_decision_after_ttl_is_refused_at_boundary(api):
    """PRD §3.1: "the decision must be issued while the current clock is at or
    before verification_expires_at; a decision after that instant is refused
    with ERR_VERIFICATION_EXPIRED." PRD §3.1: "sets verification_expires_at to
    fourteen (14) days later."

    Design: Corner/state_machines/student_verification_decision_after_ttl_is_refused_at_boundary
    """
    uni = fx.create_university(api)
    s1 = fx.create_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.create_student(api, uni["id"], "ben@su.edu", full_name="Ben Two")
    api.request_verification(s1["id"], make_student_headers(s1["id"]))
    fx.set_clock(api, "2026-05-16T00:00:00Z")
    api.request_verification(s2["id"], make_student_headers(s2["id"]))
    fx.set_clock(api, "2026-05-30T00:00:00Z")
    assert fx.get_student(api, s1["id"])["verification_expires_at"] == "2026-05-15T00:00:00.000Z"
    assert fx.get_student(api, s2["id"])["verification_expires_at"] == "2026-05-30T00:00:00.000Z"
    validate_error(api.decide_verification(s1["id"], {"decision": "APPROVE"}, PARTNER),
                   ApiErrorId.ERR_VERIFICATION_EXPIRED.value)
    assert fx.get_student(api, s1["id"])["verification_status"] == "PENDING"
    ok = validate_success(api.decide_verification(s2["id"], {"decision": "APPROVE"}, PARTNER), 200)
    assert ok["verification_status"] == "VERIFIED"
    assert api.get_university(uni["id"], ADMIN).json()["data"]["verified_student_count"] == 1


def test_clock_cannot_move_backwards(api):
    """PRD §2.5: "The new instant must be at or after the current one; a request
    to move the clock backwards is rejected with ERR_CLOCK_BACKWARDS."

    Design: Corner/state_machines/clock_cannot_move_backwards
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.set_clock("2026-05-01T00:00:00Z", ADMIN),
                   ApiErrorId.ERR_CLOCK_BACKWARDS.value)
    ok = validate_success(api.set_clock("2026-06-01T00:00:00Z", ADMIN), 200)
    assert ok["current_utc"] == "2026-06-01T00:00:00.000Z"


def test_lease_submit_rejected_when_student_unverified(api):
    """PRD §3.4: "Submission requires ... that the student is VERIFIED whenever
    their university's verification_required is true (else
    ERR_STUDENT_NOT_VERIFIED)".

    Design: Difficulty/cross_entity_state_dependency/lease_submit_gated_by_student_verification_status
    """
    base = fx.base_property(api, verification_required=True)
    s7 = fx.create_student(api, base["uni"]["id"], "gus@su.edu", full_name="Gus Seven",
                           cleanliness_level=3, noise_tolerance=3, sleep_schedule="EARLY")
    lease = fx.draft_lease(api, s7["id"], base["unit"]["id"], "C")
    validate_error(api.submit_lease(lease["id"], make_student_headers(s7["id"])),
                   ApiErrorId.ERR_STUDENT_NOT_VERIFIED.value)
    assert fx.get_lease(api, lease["id"])["lease_status"] == "DRAFT"
    assert fx.get_unit(api, base["unit"]["id"])["leased_bed_count"] == 0


def test_lease_submit_succeeds_after_verification_and_reserves_bed(api):
    """PRD §3.4: "the lease routes by its guarantor_required flag ... straight
    to PENDING_SIGNATURE when it is not. ... It reserves the slot - recomputing
    the unit rollups". PRD §3.1: "APPROVE moves a PENDING student to VERIFIED,
    ... and increments the university's verified_student_count by 1".

    Design: Difficulty/cross_entity_state_dependency/lease_submit_gated_by_student_verification_status
    """
    base = fx.base_property(api, verification_required=True)
    s7 = fx.create_student(api, base["uni"]["id"], "gus@su.edu", full_name="Gus Seven",
                           cleanliness_level=3, noise_tolerance=3, sleep_schedule="EARLY")
    lease = fx.draft_lease(api, s7["id"], base["unit"]["id"], "C")
    api.submit_lease(lease["id"], make_student_headers(s7["id"]))  # rejected (unverified)
    fx.verify_student(api, s7["id"])
    assert fx.get_student(api, s7["id"])["verification_status"] == "VERIFIED"
    assert api.get_university(base["uni"]["id"], ADMIN).json()["data"]["verified_student_count"] == 1
    ok = validate_success(api.submit_lease(lease["id"], make_student_headers(s7["id"])), 200)
    assert ok["lease_status"] == "PENDING_SIGNATURE"
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["leased_bed_count"] == 1 and unit["occupancy_status"] == "PARTIALLY_LEASED"
