"""Failure-ordering pairs and inclusive numeric boundaries.

Two families of behaviour are exercised here. The first is the total order in
which rules fail (PRD §2.11): when one request breaks two rules, exactly one
error comes back and which one is fully determined, so each ordering claim is
anchored by an isolated single-failure control proving the lower-priority rule
really was violated. The second is the inclusive side of two numeric gates —
the lead-readiness activation threshold and the defibrillator inspection-age
boundary — where the value exactly at the threshold must be accepted and one
unit past it must not.
"""
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import THRESHOLDS, api_client
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId

SESSION_START_UTC = "2026-08-05T12:00:00Z"
SESSION_END_UTC = "2026-08-05T12:55:00Z"
# Inside the 15-minute start grace window of a 12:00Z session, so the
# grace-window check (evaluated last of the five) is satisfied.
INSIDE_START_GRACE_UTC = "2026-08-05T11:50:00Z"


# ==========================================================================
# Private setup chains
# ==========================================================================
def _setup_two_sessions_one_unstaffed():
    """An ACTIVE programme carrying two same-time sessions in two rooms: one
    still SCHEDULED (no assignment at all) and one STAFFED by a confirmed LEAD.

    Returns (scenario, unstaffed_session, staffed_session).
    """
    scenario = scenarios.setup_active_program()
    studio_b = scenarios.add_room(scenario, room_name="Studio B", max_occupancy=30)
    unstaffed = scenarios.schedule_session(
        scenario,
        room_id=scenario["room_id"],
        scheduled_start_utc=SESSION_START_UTC,
        scheduled_end_utc=SESSION_END_UTC,
        forecast_attendance=3,
    )
    staffed = scenarios.schedule_session(
        scenario,
        room_id=studio_b["id"],
        scheduled_start_utc=SESSION_START_UTC,
        scheduled_end_utc=SESSION_END_UTC,
        forecast_attendance=3,
    )
    scenarios.staff_session(scenario, staffed["id"])
    return scenario, unstaffed, scenarios.read_session(staffed["id"])


def _break_the_only_aed(scenario):
    """Take the site's only defibrillator out of service, which is what drives
    its readiness_status to NOT_READY."""
    validate_success(
        api_client.create_service_event(
            scenario["aed_id"],
            {"event_type": "TAKE_OUT_OF_SERVICE", "note": "Self-test fault"},
            scenario["manager_headers"],
        )
    )
    return scenarios.read_asset(scenario["aed_id"])


def _setup_in_progress_session_with_two_blocked_members():
    """An IN_PROGRESS session plus two ELIGIBLE members, each failing exactly
    the check-in gate we want to isolate.

    `unwaivered` has no liability waiver at all and no badge, so both the
    waiver gate and the badge gate fail on one request. `badge_revoked` holds a
    SIGNED waiver but a REVOKED badge, so only the badge gate fails.

    Returns (scenario, session, unwaivered, badge_revoked).
    """
    scenario = scenarios.setup_active_program()
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=SESSION_START_UTC,
        scheduled_end_utc=SESSION_END_UTC,
        forecast_attendance=3,
    )
    scenarios.staff_session(scenario, session["id"])

    unwaivered = scenarios.enrol_member(
        scenario, full_name="Ada Kim", employee_number="E-1001"
    )
    scenarios.verify_member(scenario, unwaivered["id"])

    badge_revoked = scenarios.enrol_member(
        scenario, full_name="Ben Ortiz", employee_number="E-1002"
    )
    scenarios.verify_member(scenario, badge_revoked["id"])
    scenarios.file_waiver(scenario, badge_revoked["id"], expires_on="2027-07-31")
    scenarios.grant_badge(scenario, badge_revoked["id"], badge_number="B-1002")
    validate_success(
        api_client.badge_access(
            badge_revoked["id"], {"action": "REVOKE"}, scenario["manager_headers"]
        )
    )

    scenarios.start_session(scenario, session["id"], clock_at=SESSION_START_UTC)
    return (
        scenario,
        scenarios.read_session(session["id"]),
        scenarios.read_member(unwaivered["id"]),
        scenarios.read_member(badge_revoked["id"]),
    )


# ==========================================================================
# priority_pair_validation_conflict
#   session_start_state_gate_outranks_aed_safety_gate
# ==========================================================================
def test_session_start_reports_not_staffed_when_the_only_aed_is_also_out_of_service(api):
    """PRD §2.11: "State admissibility sits above every safety rule, so
    attempting to start a session that is not `STAFFED` returns
    `ERR_SESSION_NOT_STAFFED` even when the site simultaneously has no ready
    defibrillator, and a check-in against a session that is not `IN_PROGRESS`
    returns `ERR_SESSION_NOT_IN_PROGRESS` even when the member also lacks a
    waiver."

    PRD §3.5: "Because the state check outranks all three business gates, a
    session that is not `STAFFED` reports `ERR_SESSION_NOT_STAFFED` even when
    the site is also without a ready defibrillator, and the grace-window check
    is evaluated dead last of the five."

    Design: Difficulty/priority_pair_validation_conflict/session_start_state_gate_outranks_aed_safety_gate
    """
    scenario, unstaffed, _staffed = _setup_two_sessions_one_unstaffed()
    aed = _break_the_only_aed(scenario)
    assert aed["status"] == "OUT_OF_SERVICE", (
        f"expected the defibrillator to be OUT_OF_SERVICE, got {aed['status']}"
    )
    assert aed["readiness_status"] == "NOT_READY", (
        "taking the only defibrillator out of service must drive readiness_status "
        f"to NOT_READY, got {aed['readiness_status']}"
    )
    scenarios.set_clock(INSIDE_START_GRACE_UTC)

    response = api.session_status_change(
        unstaffed["id"], {"action": "START"}, scenario["manager_headers"]
    )

    error = validate_error(response, ApiErrorId.ERR_SESSION_NOT_STAFFED.value)
    assert error["error_id"] != ApiErrorId.ERR_AED_NOT_READY.value, (
        "the state gate outranks the defibrillator gate, so the safety error must "
        f"never be the one reported, got {error['error_id']}"
    )
    session = scenarios.read_session(unstaffed["id"])
    assert session["status"] == "SCHEDULED", (
        f"expected the rejected session to stay SCHEDULED, got {session['status']}"
    )


def test_session_start_reports_aed_not_ready_once_the_session_is_staffed(api):
    """PRD §3.3: "That requirement bites in two places, and the error is the
    same in both: activating a program offering and changing a session's status
    both require the contract to have at least one asset whose `asset_type` is
    `AED` and whose `readiness_status` is `READY`, failing which the request is
    refused with `ERR_AED_NOT_READY`."

    PRD §3.3: "A `TAKE_OUT_OF_SERVICE` on an asset in either `IN_SERVICE` or
    `MAINTENANCE_DUE` moves it to `OUT_OF_SERVICE` and stamps
    `out_of_service_since` with the current instant; when the asset is a
    defibrillator its `readiness_status` becomes `NOT_READY`, which is what
    silently blocks session starts across the whole site until it is repaired."

    Design: Difficulty/priority_pair_validation_conflict/session_start_state_gate_outranks_aed_safety_gate
    """
    scenario, _unstaffed, staffed = _setup_two_sessions_one_unstaffed()
    assert staffed["status"] == "STAFFED", (
        f"the control session must be STAFFED before the trigger, got {staffed['status']}"
    )
    _break_the_only_aed(scenario)
    scenarios.set_clock(INSIDE_START_GRACE_UTC)

    response = api.session_status_change(
        staffed["id"], {"action": "START"}, scenario["manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_AED_NOT_READY.value)
    session = scenarios.read_session(staffed["id"])
    assert session["status"] == "STAFFED", (
        f"a session refused for defibrillator readiness stays STAFFED, got {session['status']}"
    )
    assert session["started_at"] is None, (
        f"started_at must stay null on a refused start, got {session['started_at']!r}"
    )


def test_session_start_reports_not_staffed_on_its_own_with_a_ready_aed(api):
    """PRD §3.5: "**Starting** moves the session `STAFFED → IN_PROGRESS` and
    stamps `started_at`, and it is gated four ways: the session must be in
    `STAFFED` (else `ERR_SESSION_NOT_STAFFED`), the contract must be `ACTIVE`
    (else `ERR_CONTRACT_NOT_ACTIVE`), the room must be `OPEN` (else
    `ERR_ROOM_NOT_OPEN`), the site must have at least one `READY` defibrillator
    (else `ERR_AED_NOT_READY`), and the clock must have reached at most 15
    minutes before `scheduled_start_utc` — a start attempted earlier than that
    grace window is refused with `ERR_SESSION_START_TOO_EARLY`."

    Design: Difficulty/priority_pair_validation_conflict/session_start_state_gate_outranks_aed_safety_gate
    """
    scenario, unstaffed, _staffed = _setup_two_sessions_one_unstaffed()
    aed = scenarios.read_asset(scenario["aed_id"])
    assert aed["readiness_status"] == "READY", (
        "this control leaves the defibrillator READY so only the state gate can "
        f"fail, got {aed['readiness_status']}"
    )
    scenarios.set_clock(INSIDE_START_GRACE_UTC)

    response = api.session_status_change(
        unstaffed["id"], {"action": "START"}, scenario["manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_SESSION_NOT_STAFFED.value)
    session = scenarios.read_session(unstaffed["id"])
    assert session["status"] == "SCHEDULED", (
        f"expected the rejected session to stay SCHEDULED, got {session['status']}"
    )


# ==========================================================================
# priority_pair_validation_conflict
#   checkin_waiver_safety_outranks_badge_access_constraint
# ==========================================================================
def test_checkin_reports_waiver_required_when_the_badge_is_also_missing(api):
    """PRD §2.11: "Rules are evaluated in one total order, and the **first**
    violated rule decides the response; later violations are never reported and
    never merged into the message."

    PRD §2.11: "17. Signed and unexpired liability waiver
    (`ERR_WAIVER_REQUIRED`)."

    PRD §2.11: "27. Badge and eligibility active at check-in
    (`ERR_ACCESS_NOT_ACTIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/checkin_waiver_safety_outranks_badge_access_constraint
    """
    scenario, session, unwaivered, _revoked = (
        _setup_in_progress_session_with_two_blocked_members()
    )
    assert unwaivered["eligibility_status"] == "ELIGIBLE", (
        "the subject must be ELIGIBLE so the eligibility half of the badge gate is "
        f"not what fails, got {unwaivered['eligibility_status']}"
    )
    assert unwaivered["access_status"] == "NO_BADGE", (
        f"expected the subject to hold no badge, got {unwaivered['access_status']}"
    )
    assert unwaivered["current_waiver_id"] is None, (
        "the subject must have no waiver at all, got "
        f"{unwaivered['current_waiver_id']!r}"
    )
    assert session["status"] == "IN_PROGRESS", (
        f"check-ins are only state-legal on an IN_PROGRESS session, got {session['status']}"
    )

    response = api.create_participation_record(
        {"member_id": unwaivered["id"], "session_id": session["id"]},
        scenario["instructor_headers"],
    )

    error = validate_error(response, ApiErrorId.ERR_WAIVER_REQUIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_ACCESS_NOT_ACTIVE.value, (
        "the waiver gate outranks the badge gate, so the access error must never be "
        f"the one reported, got {error['error_id']}"
    )


def test_checkin_reports_access_not_active_when_the_waiver_is_signed(api):
    """PRD §3.7: "The member must have `access_status` of `ACTIVE` **and**
    `eligibility_status` of `ELIGIBLE` at the moment of check-in, and a failure
    of either is refused with `ERR_ACCESS_NOT_ACTIVE` — a revoked badge blocks
    participation even for someone whose eligibility is intact."

    PRD §3.7: "The member must hold a liability waiver in `SIGNED` status whose
    `expires_on` falls at or after today, or `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/checkin_waiver_safety_outranks_badge_access_constraint
    """
    scenario, session, _unwaivered, revoked = (
        _setup_in_progress_session_with_two_blocked_members()
    )
    assert revoked["access_status"] == "REVOKED", (
        f"expected the control member's badge to be REVOKED, got {revoked['access_status']}"
    )
    assert revoked["eligibility_status"] == "ELIGIBLE", (
        "revoking a badge leaves eligibility untouched, got "
        f"{revoked['eligibility_status']}"
    )
    waiver = scenarios.read_waiver(revoked["current_waiver_id"])
    assert waiver["status"] == "SIGNED", (
        "the control member's waiver must stay SIGNED so only the badge gate can "
        f"fail, got {waiver['status']}"
    )

    response = api.create_participation_record(
        {"member_id": revoked["id"], "session_id": session["id"]},
        scenario["instructor_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ACCESS_NOT_ACTIVE.value)


def test_checkin_gate_order_leaves_no_participation_behind_on_either_rejection(api):
    """PRD §3.7: "Six gates stand in front of a check-in, and their relative
    order — fixed by §2.11 — is the part most likely to be implemented
    wrongly."

    PRD §3.7: "The check-in also updates the aggregate figures: the session's
    `actual_attendance` increases by 1, the offering's
    `counted_participation_total` increases by 1, and both of the offering's
    attainment percentages are recomputed."

    Design: Difficulty/priority_pair_validation_conflict/checkin_waiver_safety_outranks_badge_access_constraint
    """
    scenario, session, unwaivered, revoked = (
        _setup_in_progress_session_with_two_blocked_members()
    )

    first = api.create_participation_record(
        {"member_id": unwaivered["id"], "session_id": session["id"]},
        scenario["instructor_headers"],
    )
    second = api.create_participation_record(
        {"member_id": revoked["id"], "session_id": session["id"]},
        scenario["instructor_headers"],
    )

    validate_error(first, ApiErrorId.ERR_WAIVER_REQUIRED.value)
    validate_error(second, ApiErrorId.ERR_ACCESS_NOT_ACTIVE.value)
    refreshed_session = scenarios.read_session(session["id"])
    assert refreshed_session["actual_attendance"] == 0, (
        "no participation record was created, so actual_attendance must stay 0, got "
        f"{refreshed_session['actual_attendance']}"
    )
    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 0, (
        "no participation record was created, so counted_participation_total must "
        f"stay 0, got {offering['counted_participation_total']}"
    )


# ==========================================================================
# boundary_precision_check
#   offering_activation_readiness_exactly_at_threshold_is_allowed
# ==========================================================================
def _setup_two_leads_astride_the_readiness_threshold():
    """One site, two GROUP_EX_INSTRUCTOR leads and one DRAFT offering each.

    `lead_at_threshold` holds a VERIFIED GROUP_EX_CERT, has never drilled and
    has no committed minutes, so the weighted score lands exactly on the
    activation threshold. `lead_below` holds a card expiring inside the warning
    window (moved to EXPIRING_SOON by one readiness run) and drilled 122 days
    ago, so the score lands two points under it.

    Returns (scenario, lead_at_threshold, offering_at_threshold, lead_below,
    below_credential, offering_below).
    """
    scenario = scenarios.setup_active_site()

    at_threshold = scenarios.hire_staff(
        scenario["contract_id"],
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Nia Brooks",
        hourly_cost_cents=4700,
    )
    scenarios.file_and_verify_credential(
        at_threshold["id"],
        credential_type="GROUP_EX_CERT",
        issuer="ACE",
        credential_number="ACE-7001",
        expires_on="2027-05-31",
    )

    below = scenarios.hire_staff(
        scenario["contract_id"],
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Owen Diaz",
        hourly_cost_cents=4700,
    )
    scenarios.record_drill(
        below["id"], drill_on="2026-04-01", headers=scenario["manager_headers"]
    )
    below_credential = scenarios.file_and_verify_credential(
        below["id"],
        credential_type="GROUP_EX_CERT",
        issuer="ACE",
        credential_number="ACE-7002",
        expires_on="2026-08-20",
    )
    scenarios.run_readiness_sweep(scenario["contract_id"])

    offering_at_threshold = scenarios.add_offering(
        scenario, at_threshold["id"], title="Sunrise Mobility"
    )
    offering_below = scenarios.add_offering(
        scenario, below["id"], title="Evening Strength"
    )
    return (
        scenario,
        scenarios.read_staff(at_threshold["id"]),
        offering_at_threshold,
        scenarios.read_staff(below["id"]),
        scenarios.read_credential(below_credential["id"]),
        offering_below,
    )


def test_offering_activates_when_lead_readiness_is_exactly_seventy(api):
    """PRD §3.2: "The threshold that matters is 70: an offering may only be
    activated when its lead's `readiness_index` is at least 70, so exactly 70
    passes and 69 fails."

    PRD §3.2: "The three components are combined as one half of the credential
    component plus three tenths of the drill component plus two tenths of the
    workload component, and that weighted sum is rounded half up, exactly once,
    to an integer."

    PRD §3.2: "A person with every required credential verified, no drill on
    file, and 90 hours of committed time therefore scores 70; the same person
    with 100 hours and 30 minutes committed scores 69, because one part-hour
    beyond the cap costs 5 points of the workload component and thus 1 point of
    the total."

    Design: Difficulty/boundary_precision_check/offering_activation_readiness_exactly_at_threshold_is_allowed
    """
    (
        scenario,
        lead,
        offering,
        _lead_below,
        _below_credential,
        _offering_below,
    ) = _setup_two_leads_astride_the_readiness_threshold()
    assert lead["last_drill_on"] is None, (
        f"this lead must have no drill on file, got {lead['last_drill_on']!r}"
    )
    assert lead["committed_minutes_current_period"] == 0, (
        "this lead must carry no committed minutes, got "
        f"{lead['committed_minutes_current_period']}"
    )
    assert lead["readiness_index"] == THRESHOLDS["ACTIVATION_MIN_READINESS"], (
        "a verified credential, no drill and no committed time weigh out to exactly "
        f"{THRESHOLDS['ACTIVATION_MIN_READINESS']}, got {lead['readiness_index']}"
    )

    response = api.offering_status_change(
        offering["id"], {"action": "ACTIVATE"}, scenario["manager_headers"]
    )

    data = validate_success(response)
    assert data["status"] == "ACTIVE", (
        "the activation gate is 'at least 70', so a readiness index of exactly 70 "
        f"must activate, got status {data['status']}"
    )
    assert scenarios.read_offering(offering["id"])["status"] == "ACTIVE", (
        "the offering must be persisted as ACTIVE after activation at the boundary"
    )


def test_offering_activation_rejected_when_lead_readiness_is_two_below_threshold(api):
    """PRD §3.2: "**Credential currency** contributes half the weight and takes
    the worst required type: if any required credential type has no record at
    all, or its newest record is `EXPIRED` or `REJECTED`, the credential
    component is 0; otherwise, if any required type's newest record is
    `EXPIRING_SOON`, the component is 60; only when every required type is
    `VERIFIED` does the component reach 100."

    PRD §3.2: "**Drill recency** contributes three tenths of the weight and
    reads the age in days of `last_drill_on` measured against today: an age of
    at most 90 days scores 100, an age greater than 90 days but at most 180 days
    scores 60, and anything older scores 0."

    PRD §3.4: "Note that `EXPIRING_SOON` is deliberately acceptable for the
    certification gate — a card 30 days from expiry still certifies the holder —
    while it simultaneously drags the lead's `readiness_index` down to a level
    that may fail the threshold gate; the two rules are independent and the
    certification gate is evaluated first."

    Design: Difficulty/boundary_precision_check/offering_activation_readiness_exactly_at_threshold_is_allowed
    """
    (
        scenario,
        _lead_at_threshold,
        _offering_at_threshold,
        lead,
        credential,
        offering,
    ) = _setup_two_leads_astride_the_readiness_threshold()
    assert credential["status"] == "EXPIRING_SOON", (
        "a card expiring inside the warning window must sit at EXPIRING_SOON after "
        f"the readiness run, got {credential['status']}"
    )
    assert lead["last_drill_on"] == "2026-04-01", (
        f"expected the stale drill date to stand, got {lead['last_drill_on']!r}"
    )
    assert lead["readiness_index"] == 68, (
        "60 credential, 60 drill and 100 workload weigh out to 68, got "
        f"{lead['readiness_index']}"
    )

    response = api.offering_status_change(
        offering["id"], {"action": "ACTIVATE"}, scenario["manager_headers"]
    )

    error = validate_error(response, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD.value)
    assert error["error_id"] != ApiErrorId.ERR_CREDENTIAL_NOT_VERIFIED.value, (
        "an EXPIRING_SOON card still satisfies the certification gate, so the "
        f"credential error must not be reported, got {error['error_id']}"
    )
    assert scenarios.read_offering(offering["id"])["status"] == "DRAFT", (
        "a refused activation leaves the offering in DRAFT"
    )


def test_offering_activation_rejected_when_lead_readiness_is_one_below_threshold(api):
    """PRD §3.2: "**Workload headroom** contributes the remaining two tenths and
    reads `committed_minutes_current_period` against a soft cap of 100 hours: at
    or below 100 hours of committed time the component is 100; above it, take the
    excess minutes beyond the cap, divide by 60 and round up to a whole number of
    hours, multiply by 5, subtract that from 100, and floor the result at 0."

    PRD §3.2: "A person with every required credential verified, no drill on
    file, and 90 hours of committed time therefore scores 70; the same person
    with 100 hours and 30 minutes committed scores 69, because one part-hour
    beyond the cap costs 5 points of the workload component and thus 1 point of
    the total."

    PRD §3.2: "The threshold that matters is 70: an offering may only be
    activated when its lead's `readiness_index` is at least 70, so exactly 70
    passes and 69 fails."

    Design: Difficulty/boundary_precision_check/offering_activation_readiness_exactly_at_threshold_is_allowed
    """
    scenario = scenarios.setup_active_program()
    lead = scenarios.hire_staff(
        scenario["contract_id"],
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Priya Shah",
        hourly_cost_cents=4700,
    )
    scenarios.file_and_verify_credential(
        lead["id"],
        credential_type="GROUP_EX_CERT",
        issuer="ACE",
        credential_number="ACE-7003",
        expires_on="2027-05-31",
    )
    # 100 hours and 30 minutes of paid time: one part-hour past the soft cap.
    scenarios.add_committed_minutes(
        scenario, lead["id"], THRESHOLDS["WORKLOAD_SOFT_CAP_MINUTES"] + 30
    )
    offering = scenarios.add_offering(scenario, lead["id"], title="Evening Mobility")

    booked = scenarios.read_staff(lead["id"])
    assert booked["committed_minutes_current_period"] == 6030, (
        "the lead must be booked for exactly 100 hours and 30 minutes, got "
        f"{booked['committed_minutes_current_period']}"
    )
    assert booked["last_drill_on"] is None, (
        f"this lead must have no drill on file, got {booked['last_drill_on']!r}"
    )
    assert booked["readiness_index"] == 69, (
        "one part-hour beyond the cap costs 1 point of the total, so the index is "
        f"69, got {booked['readiness_index']}"
    )

    response = api.offering_status_change(
        offering["id"], {"action": "ACTIVATE"}, scenario["manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD.value)
    assert scenarios.read_offering(offering["id"])["status"] == "DRAFT", (
        "an index of 69 is one unit short of the gate, so the offering stays DRAFT"
    )


# ==========================================================================
# boundary_precision_check
#   aed_inspection_age_exactly_thirty_days_still_ready
# ==========================================================================
def _setup_site_without_a_defibrillator():
    """An ACTIVE contract with one OPEN room and no assets at all, so each test
    registers exactly the defibrillators whose boundary it is probing. The
    logical clock sits at its documented startup instant, 2026-08-01."""
    scenario = scenarios.setup_active_contract()
    room = scenarios.add_room(scenario, room_name="Studio A", max_occupancy=30)
    scenario["room"] = room
    scenario["room_id"] = room["id"]
    return scenario


def test_defibrillator_inspected_exactly_thirty_days_ago_is_ready(api):
    """PRD §3.3: "The inspection-age boundary is inclusive on the ready side: a
    unit last inspected exactly 30 days ago is still eligible for `READY`, and
    one day older is `NOT_READY`."

    PRD §3.3: "A newly registered asset is `IN_SERVICE` with
    `out_of_service_since` null and `out_of_service_days_current_period` at 0,
    and its `readiness_status` is computed on the spot."

    Design: Difficulty/boundary_precision_check/aed_inspection_age_exactly_thirty_days_still_ready
    """
    scenario = _setup_site_without_a_defibrillator()
    assert THRESHOLDS["AED_INSPECTION_MAX_AGE_DAYS"] == 30, (
        "this boundary reads the 30-day inspection-age ceiling"
    )

    # 2026-07-02 is exactly 30 days before the clock's 2026-08-01.
    created = scenarios.add_ready_aed(
        scenario,
        scenario["room_id"],
        asset_tag="AED-30",
        pad_expiry_on="2027-03-31",
        battery_expiry_on="2027-03-31",
        last_inspection_on="2026-07-02",
    )

    assert created["readiness_status"] == "READY", (
        "an inspection age of exactly 30 days is on the ready side of the boundary, "
        f"got readiness_status {created['readiness_status']}"
    )
    assert created["status"] == "IN_SERVICE", (
        f"a newly registered asset is IN_SERVICE, got {created['status']}"
    )
    fetched = validate_success(
        api.get_facility_asset(created["id"], scenario["manager_headers"])
    )
    assert fetched["readiness_status"] == "READY", (
        "the single-asset read must report the same readiness verdict, got "
        f"{fetched['readiness_status']}"
    )


def test_defibrillator_inspected_thirty_one_days_ago_is_not_ready(api):
    """PRD §3.3: "It is `NOT_READY` if any of the following holds: its `status`
    is anything other than `IN_SERVICE`; `pad_expiry_on` falls at or before
    today; `battery_expiry_on` falls at or before today; `last_inspection_on` is
    null; or the number of days from `last_inspection_on` to today exceeds 30."

    PRD §3.3: "The inspection-age boundary is inclusive on the ready side: a
    unit last inspected exactly 30 days ago is still eligible for `READY`, and
    one day older is `NOT_READY`."

    Design: Difficulty/boundary_precision_check/aed_inspection_age_exactly_thirty_days_still_ready
    """
    scenario = _setup_site_without_a_defibrillator()

    # 2026-07-01 is 31 days before the clock's 2026-08-01 — one day past the gate.
    created = scenarios.add_ready_aed(
        scenario,
        scenario["room_id"],
        asset_tag="AED-31",
        pad_expiry_on="2027-03-31",
        battery_expiry_on="2027-03-31",
        last_inspection_on="2026-07-01",
    )

    assert created["readiness_status"] == "NOT_READY", (
        "an inspection age of 31 days exceeds the 30-day ceiling, so the unit is "
        f"NOT_READY, got {created['readiness_status']}"
    )
    assert created["status"] == "IN_SERVICE", (
        "status and readiness_status are independent axes: a stale inspection does "
        f"not move the unit out of service, got {created['status']}"
    )
    fetched = validate_success(
        api.get_facility_asset(created["id"], scenario["manager_headers"])
    )
    assert fetched["readiness_status"] == "NOT_READY", (
        "the single-asset read must report the same readiness verdict, got "
        f"{fetched['readiness_status']}"
    )


def test_defibrillator_inspection_boundary_pair_differs_by_one_day(api):
    """PRD §3.3: "The inspection-age boundary is inclusive on the ready side: a
    unit last inspected exactly 30 days ago is still eligible for `READY`, and
    one day older is `NOT_READY`."

    PRD §3.3: "Defibrillator readiness is a four-valued judgement recomputed at
    registration, on every service event, and by the nightly sweep."

    Design: Difficulty/boundary_precision_check/aed_inspection_age_exactly_thirty_days_still_ready
    """
    scenario = _setup_site_without_a_defibrillator()

    on_boundary = scenarios.add_ready_aed(
        scenario,
        scenario["room_id"],
        asset_tag="AED-30",
        pad_expiry_on="2027-03-31",
        battery_expiry_on="2027-03-31",
        last_inspection_on="2026-07-02",
    )
    one_day_older = scenarios.add_ready_aed(
        scenario,
        scenario["room_id"],
        asset_tag="AED-31",
        pad_expiry_on="2027-03-31",
        battery_expiry_on="2027-03-31",
        last_inspection_on="2026-07-01",
    )

    assert on_boundary["readiness_status"] == "READY", (
        "the unit inspected exactly 30 days ago must be READY, got "
        f"{on_boundary['readiness_status']}"
    )
    assert one_day_older["readiness_status"] == "NOT_READY", (
        "the unit inspected one day earlier must be NOT_READY, got "
        f"{one_day_older['readiness_status']}"
    )
    assert on_boundary["readiness_status"] != one_day_older["readiness_status"], (
        "two units differing only by one day of inspection age must land on "
        "opposite sides of the boundary"
    )


def test_defibrillator_pads_expiring_exactly_at_the_warning_boundary(api):
    """PRD §3.3: "Otherwise, if the earlier of `pad_expiry_on` and
    `battery_expiry_on` falls at or before 30 days from today, it is
    `PADS_EXPIRING`."

    PRD §3.3: "`PADS_EXPIRING` is a warning, not a pass — where this document
    requires a ready defibrillator, only `READY` satisfies the requirement."

    Design: Difficulty/boundary_precision_check/aed_inspection_age_exactly_thirty_days_still_ready
    """
    scenario = _setup_site_without_a_defibrillator()
    assert THRESHOLDS["AED_PADS_WARNING_DAYS"] == 30, (
        "this boundary reads the 30-day consumable warning window"
    )

    # Inspected yesterday, but the pads expire exactly 30 days from today.
    created = scenarios.add_ready_aed(
        scenario,
        scenario["room_id"],
        asset_tag="AED-PAD",
        pad_expiry_on="2026-08-31",
        battery_expiry_on="2027-03-31",
        last_inspection_on="2026-07-31",
    )

    assert created["readiness_status"] == "PADS_EXPIRING", (
        "pads expiring exactly 30 days out land the unit on the warning verdict, "
        f"got {created['readiness_status']}"
    )
    assert created["status"] == "IN_SERVICE", (
        f"a newly registered asset is IN_SERVICE, got {created['status']}"
    )
    fetched = validate_success(
        api.get_facility_asset(created["id"], scenario["manager_headers"])
    )
    assert fetched["readiness_status"] == "PADS_EXPIRING", (
        "the single-asset read must report the same readiness verdict, got "
        f"{fetched['readiness_status']}"
    )
