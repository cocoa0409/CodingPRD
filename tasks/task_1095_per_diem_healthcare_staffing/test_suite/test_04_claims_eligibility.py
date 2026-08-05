"""Self-scheduling: the claim eligibility gate stack (duplicate, claim window,
claim quota, weekly hours, overlap, rest, suspension) and the priority ordering
among those gates.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------- #
# Corner: claim state / quota / window / weekly-hours gates
# --------------------------------------------------------------------------- #
def test_withdraw_claim_twice_returns_claim_not_pending(api):
    """PRD 3.4: "Withdrawing a claim that is not `PENDING` is refused with
    `ERR_CLAIM_NOT_PENDING`."

    Design: Corner/state_machines/withdraw_claim_twice_returns_claim_not_pending
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(
        facility_overrides={"name": "Yarrow"}, clock=None,
    )
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id)
    shift = fx.add_shift(order["id"], fac_id)
    claim = fx.place_claim(shift["id"], cl_id)

    first = validate_success(api.withdraw_claim(claim["id"], {}, make_clinician_headers(cl_id)), 200)
    assert first["status"] == "WITHDRAWN"
    after = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)
    assert after["claim_count"] == 0
    version_after_first = after["version"]

    resp = api.withdraw_claim(claim["id"], {}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PENDING.value, 409)
    shift_now = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)
    assert shift_now["version"] == version_after_first


def test_duplicate_claim_on_same_shift_returns_error(api):
    """PRD 3.4: "the clinician must not already hold a claim on this shift in
    `PENDING` or `AWARDED` status, or it fails with `ERR_DUPLICATE_CLAIM`."

    Design: Corner/validations/duplicate_claim_on_same_shift_returns_error
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Vellum"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id)
    shift = fx.add_shift(order["id"], fac_id)
    claim = fx.place_claim(shift["id"], cl_id)

    resp = api.create_claim(shift["id"], {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)
    shift_now = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)
    assert shift_now["claim_count"] == 1
    claims, meta = validate_paginated(api.list_claims(make_scheduler_headers(fac_id), params={"shift_id": shift["id"]}))
    assert meta["total_count"] == 1 and claims[0]["id"] == claim["id"]


def test_claim_at_exactly_two_hours_before_start_is_accepted(api):
    """PRD 3.4: "the current instant must be at or before the shift's
    `scheduled_start` minus 2 hours; exactly at that lock instant a claim is still
    accepted, but one second later it is refused with `ERR_CLAIM_WINDOW_CLOSED`."

    Design: Corner/validations/claim_at_exactly_two_hours_before_start_is_accepted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Wickham"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id)
    shift = fx.add_shift(order["id"], fac_id)
    fx.set_clock("2026-06-08T05:00:00Z")
    resp = api.create_claim(shift["id"], {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"
    assert data["claimed_at"] == "2026-06-08T05:00:00.000Z"
    assert data["reliability_snapshot"] == 100
    shift_now = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)
    assert shift_now["claim_count"] == 1


def test_claim_limit_exceeded_after_five_pending_claims(api):
    """PRD 3.4: "the clinician must currently hold fewer than 5 claims in `PENDING`
    status, or the claim is refused with `ERR_CLAIM_LIMIT_EXCEEDED`."

    Design: Corner/validations/claim_limit_exceeded_after_five_pending_claims
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Xenon"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=6)
    days = ["08", "09", "10", "11", "12", "13"]
    shifts = [
        fx.add_shift(order["id"], fac_id,
                     scheduled_start=f"2026-06-{d}T07:00:00Z", scheduled_end=f"2026-06-{d}T11:00:00Z")
        for d in days
    ]
    for s in shifts[:5]:
        fx.place_claim(s["id"], cl_id)
    resp = api.create_claim(shifts[5]["id"], {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLAIM_LIMIT_EXCEEDED.value, 422)
    claims, meta = validate_paginated(api.list_claims(make_clinician_headers(cl_id), params={"clinician_id": cl_id}))
    assert meta["total_count"] == 5
    assert all(c["status"] == "PENDING" for c in claims)
    s6 = validate_success(api.get_shift(shifts[5]["id"], make_scheduler_headers(fac_id)), 200)
    assert s6["claim_count"] == 0


def test_weekly_hours_cap_sixty_passes_seventy_five_rejected(api):
    """PRD 3.4: "the clinician's total `scheduled_hours` across occupied shifts
    falling in the target shift's ISO week, plus the target shift's own
    `scheduled_hours`, must not exceed 60 hours; exactly 60.00 passes, and more raises
    `ERR_WEEKLY_HOURS_EXCEEDED`."

    Design: Corner/validations/weekly_hours_cap_sixty_passes_and_seventy_five_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Yonder"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=5)
    days = ["08", "09", "10", "11", "12"]
    shifts = [
        fx.add_shift(order["id"], fac_id,
                     scheduled_start=f"2026-06-{d}T04:00:00Z", scheduled_end=f"2026-06-{d}T19:00:00Z")
        for d in days
    ]
    assert shifts[0]["scheduled_hours"] == 15.00
    for s in shifts[:4]:
        claim = fx.place_claim(s["id"], cl_id)
        fx.award(s["id"], fac_id, claim_id=claim["id"])

    resp = api.create_claim(shifts[4]["id"], {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED.value, 422)
    asgs, meta = validate_paginated(api.list_assignments(make_scheduler_headers(fac_id), params={"clinician_id": cl_id}))
    assert meta["total_count"] == 4
    s5 = validate_success(api.get_shift(shifts[4]["id"], make_scheduler_headers(fac_id)), 200)
    assert s5["claim_count"] == 0 and s5["status"] == "OPEN"


# --------------------------------------------------------------------------- #
# Difficulty: half-open adjacency passes overlap but fails the 8-hour rest buffer
# --------------------------------------------------------------------------- #
def _setup_adjacent_shifts():
    """S1 07:00-19:00 CONFIRMED to the clinician, S2 19:00-23:00 OPEN (touching)."""
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Rockford"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=2)
    s1 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    s2 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T19:00:00Z", scheduled_end="2026-06-08T23:00:00Z")
    claim1 = fx.place_claim(s1["id"], cl_id)
    asg1 = fx.award(s1["id"], fac_id, claim_id=claim1["id"])
    fx.confirm(asg1["id"], cl_id)
    return fac_id, cl_id, s1["id"], s2["id"]


def test_rest_buffer_fires_for_touching_shift_not_overlap(api):
    """PRD 3.4: "Back-to-back shifts, where one ends exactly when the next starts, do
    not intersect under this overlap rule."
    PRD 3.4: "the gap between the target shift and every adjacent occupied shift of the
    same clinician (again, occupied means an assignment in `PENDING_CONFIRMATION`,
    `CONFIRMED`, or `WORKED`) must be at least 8 hours; a gap of exactly 8.00 hours
    passes, and anything less raises `ERR_REST_PERIOD_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_adjacency_passes_overlap_but_fails_rest_buffer
    """
    fac_id, cl_id, s1_id, s2_id = _setup_adjacent_shifts()
    resp = api.create_claim(s2_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    err = validate_error(resp, ApiErrorId.ERR_REST_PERIOD_VIOLATION.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_SHIFT_OVERLAP.value


def test_rest_buffer_leaves_second_shift_open(api):
    """PRD 3.4: "the gap between the target shift and every adjacent occupied shift of
    the same clinician (again, occupied means an assignment in `PENDING_CONFIRMATION`,
    `CONFIRMED`, or `WORKED`) must be at least 8 hours; a gap of exactly 8.00 hours
    passes, and anything less raises `ERR_REST_PERIOD_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/clinician_half_open_adjacency_passes_overlap_but_fails_rest_buffer
    """
    fac_id, cl_id, s1_id, s2_id = _setup_adjacent_shifts()
    resp = api.create_claim(s2_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_REST_PERIOD_VIOLATION.value, 422)
    s2 = validate_success(api.get_shift(s2_id, make_scheduler_headers(fac_id)), 200)
    assert s2["claim_count"] == 0 and s2["status"] == "OPEN"
    s1 = validate_success(api.get_shift(s1_id, make_scheduler_headers(fac_id)), 200)
    assert s1["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# Difficulty: claim-window temporal gate beats the overlap constraint
# --------------------------------------------------------------------------- #
def _setup_claim_window_vs_overlap():
    """Clinician CONFIRMED on S1 07:00-19:00; S2 12:00-20:00 intersects S1 and its
    claim lock (10:00Z) has already passed at clock 11:00Z."""
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Pinehurst"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=2)
    s1 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    s2 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T12:00:00Z", scheduled_end="2026-06-08T20:00:00Z")
    claim1 = fx.place_claim(s1["id"], cl_id)
    asg1 = fx.award(s1["id"], fac_id, claim_id=claim1["id"])
    fx.confirm(asg1["id"], cl_id)
    fx.set_clock("2026-06-08T11:00:00Z")
    return fac_id, cl_id, s1["id"], s2["id"], asg1["id"]


def test_claim_window_beats_overlap_error_id(api):
    """PRD 2.7: "then the domain-specific business gates described in Section 3, in the
    order they appear there — credential presence, credential expiry, claim window,
    shift-ended, timesheet window, duplicate claim, shift overlap, rest period, unit
    capacity, headcount, weekly hours, claim limit, rate-card availability,
    billable-timesheet availability, invoice-period overlap, eligible-claim
    availability, dispute limit, and payment-amount match."
    PRD 3.4: "exactly at that lock instant a claim is still accepted, but one second
    later it is refused with `ERR_CLAIM_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_overlap_constraint_on_claim
    """
    fac_id, cl_id, s1_id, s2_id, asg1_id = _setup_claim_window_vs_overlap()
    resp = api.create_claim(s2_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    err = validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_SHIFT_OVERLAP.value


def test_claim_window_beats_overlap_leaves_state_untouched(api):
    """PRD 3.4: "exactly at that lock instant a claim is still accepted, but one second
    later it is refused with `ERR_CLAIM_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_overlap_constraint_on_claim
    """
    fac_id, cl_id, s1_id, s2_id, asg1_id = _setup_claim_window_vs_overlap()
    resp = api.create_claim(s2_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 422)
    s2 = validate_success(api.get_shift(s2_id, make_scheduler_headers(fac_id)), 200)
    assert s2["claim_count"] == 0 and s2["status"] == "OPEN"
    asg1 = validate_success(api.get_assignment(asg1_id, make_scheduler_headers(fac_id)), 200)
    assert asg1["work_status"] == "CONFIRMED"


# --------------------------------------------------------------------------- #
# Difficulty: suspension state gate beats the credential-safety gate
# --------------------------------------------------------------------------- #
def _setup_suspended_clinician_with_revoked_licence():
    """Clinician suspended by two no-shows (provisional 40) whose RN_LICENSE was then
    revoked; a fresh OPEN shift S3 exists for the claim attempt."""
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="North Vale", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Ivo Marek", email="ivo.marek@example.com", specialty="RN")
    cred = fx.add_verified_credential(cl["id"], cred_overrides={"expires_on": "2027-01-01T00:00:00Z"})
    fac_id, cl_id = fac["id"], cl["id"]

    order1 = fx.new_order(fac_id, headcount=2)
    s1 = fx.add_shift(order1["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    s2 = fx.add_shift(order1["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    c1 = fx.place_claim(s1["id"], cl_id)
    a1 = fx.award(s1["id"], fac_id, claim_id=c1["id"])
    fx.confirm(a1["id"], cl_id)
    c2 = fx.place_claim(s2["id"], cl_id)
    a2 = fx.award(s2["id"], fac_id, claim_id=c2["id"])
    fx.confirm(a2["id"], cl_id)

    fx.set_clock("2026-06-09T15:30:00Z")
    fx.no_show(a1["id"], fac_id, note="no call no show")
    fx.no_show(a2["id"], fac_id, note="no call no show again")
    revoke = fx.api_client.revoke_credential(cred["id"], {"reason": "board action pending"}, OFFICER)
    assert revoke.status_code < 300, revoke.text

    order2 = fx.new_order(fac_id, headcount=1, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    s3 = fx.add_shift(order2["id"], fac_id, scheduled_start="2026-06-16T07:00:00Z", scheduled_end="2026-06-16T19:00:00Z")
    return fac_id, cl_id, s3["id"]


def test_suspension_beats_credential_safety_error_id(api):
    """PRD 3.4: "The claiming clinician must be `ACTIVE`; a suspended clinician is
    refused with `ERR_CLINICIAN_SUSPENDED`."
    PRD 2.7: "the clinician-active gate (`ERR_CLINICIAN_SUSPENDED`); the
    optimistic-concurrency check (`ERR_STALE_SHIFT_VERSION` or
    `ERR_STALE_FACILITY_VERSION`); then the domain-specific business gates described in
    Section 3, in the order they appear there — credential presence, credential
    expiry, claim window, shift-ended, timesheet window, duplicate claim, shift
    overlap, rest period, unit capacity, headcount, weekly hours, claim limit,
    rate-card availability, billable-timesheet availability, invoice-period overlap,
    eligible-claim availability, dispute limit, and payment-amount match."

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_credential_safety_on_claim
    """
    fac_id, cl_id, s3_id = _setup_suspended_clinician_with_revoked_licence()
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["status"] == "SUSPENDED"
    assert clinician["provisional_reliability_score"] == 40
    assert clinician["reliability_score"] == 100
    resp = api.create_claim(s3_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    err = validate_error(resp, ApiErrorId.ERR_CLINICIAN_SUSPENDED.value, 409)
    assert err["error_id"] != ApiErrorId.ERR_CREDENTIAL_MISSING.value


def test_suspension_beats_credential_safety_creates_no_claim(api):
    """PRD 3.4: "The claiming clinician must be `ACTIVE`; a suspended clinician is
    refused with `ERR_CLINICIAN_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_credential_safety_on_claim
    """
    fac_id, cl_id, s3_id = _setup_suspended_clinician_with_revoked_licence()
    resp = api.create_claim(s3_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SUSPENDED.value, 409)
    s3 = validate_success(api.get_shift(s3_id, make_scheduler_headers(fac_id)), 200)
    assert s3["claim_count"] == 0
    claims, meta = validate_paginated(api.list_claims(make_scheduler_headers(fac_id), params={"shift_id": s3_id}))
    assert meta["total_count"] == 0
