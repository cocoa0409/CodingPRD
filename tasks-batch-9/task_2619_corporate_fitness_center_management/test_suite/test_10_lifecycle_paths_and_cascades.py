"""Multi-hop lifecycle paths and the deep cascades they drive.

Every test in this file walks a path of several observable hops and asserts the
state at each hop rather than only at the end, and every cascade assertion names
a downstream entity kind the PRD explicitly says the cascade touches.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import TEST_DEFAULTS, api_client
from test_helpers import fixtures as scenarios
from test_helpers.assertions import (
    assert_client_contract,
    assert_liability_waiver,
    assert_member,
    assert_program_offering,
    assert_program_session,
    assert_staff_assignment,
    assert_staff_credential,
    assert_staff_member,
)
from test_helpers.test_users import make_member_headers

# The instant past both the credential expiry on file and inside the 24-hour
# session lock window used by the cascade recipes below.
SWEEP_INSTANT_UTC = "2026-08-20T06:00:00Z"


def _hire_instructor_with_expiring_credential(scenario, expires_on):
    """Hire a GROUP_EX_INSTRUCTOR onto the scenario's site, record a recent
    emergency-response drill, then file and accept a GROUP_EX_CERT that lapses
    on `expires_on`.

    The drill is deliberately recent for the whole recipe so the readiness score
    moves only with the credential component.  Returns (staff, credential).
    """
    instructor = scenarios.hire_staff(
        scenario["contract_id"],
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Ravi Patel",
        hourly_cost_cents=TEST_DEFAULTS["INSTRUCTOR_HOURLY_COST_CENTS"],
    )
    scenarios.record_drill(
        instructor["id"],
        drill_on=TEST_DEFAULTS["DRILL_ON"],
        headers=scenario["manager_headers"],
    )
    credential = scenarios.file_and_verify_credential(
        instructor["id"],
        credential_type="GROUP_EX_CERT",
        issuer="ACE",
        credential_number="ACE-4410",
        expires_on=expires_on,
    )
    return instructor, credential


def _setup_expiring_credential_holder():
    """ACTIVE cost-plus contract, a credentialed site manager, and one
    instructor whose GROUP_EX_CERT expires on 2026-08-15 while the clock still
    reads the startup instant."""
    scenario = scenarios.setup_active_contract()
    instructor, credential = _hire_instructor_with_expiring_credential(
        scenario, "2026-08-15"
    )
    scenario["instructor_id"] = instructor["id"]
    scenario["credential_id"] = credential["id"]
    return scenario


def _setup_expiry_staffing_cascade():
    """ACTIVE management-fee site with an OPEN studio, a READY defibrillator, an
    instructor whose GROUP_EX_CERT expires on 2026-08-15, an ACTIVE offering led
    by them, and two sessions on 2026-08-20 each STAFFED by that instructor."""
    scenario = scenarios.setup_active_site("MANAGEMENT_FEE")
    instructor, credential = _hire_instructor_with_expiring_credential(
        scenario, "2026-08-15"
    )
    scenario["instructor_id"] = instructor["id"]
    scenario["credential_id"] = credential["id"]

    offering = scenarios.add_offering(scenario, title="Lunch Circuit")
    scenarios.activate_offering(scenario, offering["id"])
    scenario["offering_id"] = offering["id"]

    first = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-20T12:00:00Z",
        scheduled_end_utc="2026-08-20T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    second = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-20T14:00:00Z",
        scheduled_end_utc="2026-08-20T14:55:00Z",
        forecast_attendance=2,
        direct_supply_cost_cents=0,
    )
    scenario["session_ids"] = [first["id"], second["id"]]
    scenario["assignment_ids"] = [
        scenarios.staff_session(scenario, first["id"], instructor["id"])["id"],
        scenarios.staff_session(scenario, second["id"], instructor["id"])["id"],
    ]
    return scenario


# ==========================================================================
# The cyclic certification machine: VERIFIED -> EXPIRED -> PENDING -> VERIFIED
# ==========================================================================
def test_credential_expiry_suspends_holder_then_renewal_reopens_verification():
    """PRD §3.9: "Every credential of the contract's staff in `VERIFIED` status
    whose `expires_on` falls at or before today plus 30 days but strictly after
    today moves to `EXPIRING_SOON`; every credential in `VERIFIED` or
    `EXPIRING_SOON` status whose `expires_on` falls at or before today moves to
    `EXPIRED`."

    PRD §3.9: "First, when the expired credential's `credential_type` is one of
    those required for the holder's `role_type`, the holder moves from
    `ACTIVE_DUTY` to `SUSPENDED_FROM_DUTY` and their `readiness_index` is forced
    to 0."

    PRD §3.2: "A record in `EXPIRED` or `REJECTED` status may be re-filed with a
    fresh `credential_number` and `expires_on`, moving it back to
    `PENDING_VERIFICATION` and incrementing `renewal_count` by 1 — the number of
    laps the card has taken around the verification loop."

    PRD §3.2: "Renewal overwrites `expires_on` and `credential_number` with the
    supplied values, clears `verified_at` and `verified_by_user_id` back to null,
    and — when the record was coming out of `REJECTED` — clears
    `rejection_reason` back to null as well."

    Design: Difficulty/non_linear_state_machine/credential_expiry_renew_reverify_cycle_returns_to_verified
    """
    scenario = _setup_expiring_credential_holder()
    credential_id = scenario["credential_id"]
    instructor_id = scenario["instructor_id"]

    # Hop 0 — the first visit to VERIFIED, with the holder on active duty.
    filed = scenarios.read_credential(credential_id)
    assert_staff_credential(filed)
    assert filed["status"] == "VERIFIED", (
        f"expected VERIFIED, got {filed['status']} after accepting the card"
    )
    assert filed["renewal_count"] == 0, (
        f"expected renewal_count 0 on the first lap, got {filed['renewal_count']}"
    )
    assert filed["verified_at"] is not None, (
        "verified_at must be stamped when a pending credential is accepted"
    )
    holder = scenarios.read_staff(instructor_id)
    assert holder["duty_status"] == "ACTIVE_DUTY", (
        f"expected ACTIVE_DUTY, got {holder['duty_status']} before the expiry"
    )

    # Hop 1 — the ops run past the expiry is the only actor that expires a card.
    scenarios.set_clock(SWEEP_INSTANT_UTC)
    tally = scenarios.run_readiness_sweep(scenario["contract_id"])
    assert tally["credentials_expired"] == 1, (
        f"expected 1 credential expired by the run, got {tally['credentials_expired']}"
    )
    assert tally["staff_suspended"] == 1, (
        f"expected 1 staff member suspended by the run, got {tally['staff_suspended']}"
    )

    expired = scenarios.read_credential(credential_id)
    assert expired["status"] == "EXPIRED", (
        f"expected EXPIRED, got {expired['status']} after the run passed 2026-08-15"
    )
    suspended = scenarios.read_staff(instructor_id)
    assert_staff_member(suspended)
    assert suspended["duty_status"] == "SUSPENDED_FROM_DUTY", (
        f"expected SUSPENDED_FROM_DUTY, got {suspended['duty_status']} after the "
        "required credential expired"
    )
    assert suspended["readiness_index"] == 0, (
        f"expected readiness_index 0 for the just-suspended holder, got "
        f"{suspended['readiness_index']}"
    )

    # Hop 2 — renewal re-enters a state the record already left, one lap on.
    renewed = validate_success(
        api_client.renew_credential(
            credential_id,
            {"credential_number": "ACE-9902", "expires_on": "2027-08-31"},
            scenario["manager_headers"],
        )
    )
    assert_staff_credential(renewed)
    assert renewed["status"] == "PENDING_VERIFICATION", (
        f"expected PENDING_VERIFICATION, got {renewed['status']} after renewal"
    )
    assert renewed["renewal_count"] == 1, (
        f"expected renewal_count 1 on the second lap, got {renewed['renewal_count']}"
    )
    assert renewed["expires_on"] == "2027-08-31", (
        f"expected expires_on 2027-08-31, got {renewed['expires_on']} after renewal"
    )
    assert renewed["credential_number"] == "ACE-9902", (
        f"expected credential_number ACE-9902, got {renewed['credential_number']}"
    )
    assert renewed["verified_at"] is None, (
        f"expected verified_at cleared by renewal, got {renewed['verified_at']}"
    )
    assert renewed["verified_by_user_id"] is None, (
        f"expected verified_by_user_id cleared by renewal, got "
        f"{renewed['verified_by_user_id']}"
    )

    # Renewal alone does not put the holder back on duty: PENDING_VERIFICATION
    # is neither VERIFIED nor EXPIRING_SOON.
    still_suspended = scenarios.read_staff(instructor_id)
    assert still_suspended["duty_status"] == "SUSPENDED_FROM_DUTY", (
        f"expected the holder to stay SUSPENDED_FROM_DUTY while the renewed card "
        f"is only pending, got {still_suspended['duty_status']}"
    )


def test_credential_reverification_returns_holder_to_active_duty_and_full_readiness():
    """PRD §3.2: "An `ACCEPT` moves the record `PENDING_VERIFICATION →
    VERIFIED`, stamps `verified_at` with the logical clock instant and
    `verified_by_user_id` with the deciding principal's identifier, and
    recomputes the holder's `readiness_index`."

    PRD §3.2: "If the holder was `SUSPENDED_FROM_DUTY` and, after the
    acceptance, every type in their `required_credential_types` now has a record
    in `VERIFIED` or `EXPIRING_SOON` status, the holder moves
    `SUSPENDED_FROM_DUTY → ACTIVE_DUTY` automatically."

    PRD §3.2: "The three components are combined as one half of the credential
    component plus three tenths of the drill component plus two tenths of the
    workload component, and that weighted sum is rounded half up, exactly once,
    to an integer."

    Design: Difficulty/non_linear_state_machine/credential_expiry_renew_reverify_cycle_returns_to_verified
    """
    scenario = _setup_expiring_credential_holder()
    credential_id = scenario["credential_id"]
    instructor_id = scenario["instructor_id"]

    baseline = scenarios.read_staff(instructor_id)
    assert baseline["readiness_index"] == 100, (
        f"expected readiness_index 100 from a verified card, a 2026-07-15 drill "
        f"and no committed minutes, got {baseline['readiness_index']}"
    )

    scenarios.set_clock(SWEEP_INSTANT_UTC)
    scenarios.run_readiness_sweep(scenario["contract_id"])
    assert scenarios.read_credential(credential_id)["status"] == "EXPIRED", (
        "the ops run must expire the lapsed card before the renewal lap begins"
    )
    assert scenarios.read_staff(instructor_id)["duty_status"] == "SUSPENDED_FROM_DUTY", (
        "the expiry must drive the holder off duty before the renewal lap begins"
    )

    validate_success(
        api_client.renew_credential(
            credential_id,
            {"credential_number": "ACE-9902", "expires_on": "2027-08-31"},
            scenario["manager_headers"],
        )
    )
    assert scenarios.read_credential(credential_id)["status"] == "PENDING_VERIFICATION", (
        "renewal must return the card to PENDING_VERIFICATION for the second lap"
    )

    # The second acceptance closes the cycle back onto VERIFIED.
    reverified = validate_success(
        api_client.verify_credential(
            credential_id, {"decision": "ACCEPT"}, scenario["manager_headers"]
        )
    )
    assert_staff_credential(reverified)
    assert reverified["status"] == "VERIFIED", (
        f"expected VERIFIED on the second lap, got {reverified['status']}"
    )
    assert reverified["verified_at"] is not None, (
        "the second acceptance must stamp verified_at afresh"
    )
    assert reverified["verified_by_user_id"] is not None, (
        "the second acceptance must record the deciding principal"
    )
    assert reverified["renewal_count"] == 1, (
        f"expected renewal_count to stay 1 across re-verification, got "
        f"{reverified['renewal_count']}"
    )
    assert reverified["expires_on"] == "2027-08-31", (
        f"expected the renewed expiry to survive verification, got "
        f"{reverified['expires_on']}"
    )

    restored = scenarios.read_staff(instructor_id)
    assert_staff_member(restored)
    assert restored["duty_status"] == "ACTIVE_DUTY", (
        f"expected ACTIVE_DUTY once every required type is verified again, got "
        f"{restored['duty_status']}"
    )
    assert restored["readiness_index"] == 100, (
        f"expected readiness_index 100 (credential 100, a 2026-07-15 drill 36 "
        f"days old, no committed minutes), got {restored['readiness_index']}"
    )


# ==========================================================================
# The two parallel member dimensions: eligibility and badge access
# ==========================================================================
def test_member_verification_moves_eligibility_while_access_waits_for_a_badge():
    """PRD §3.6: "A new enrolment starts at `PENDING_VERIFICATION` and
    `NO_BADGE`, with `incentive_points_balance` at 0, `current_waiver_id` null,
    and `last_check_in_utc` null."

    PRD §3.6: "It increments the contract's `eligible_member_count` by 1 and
    leaves `access_status` completely untouched — verifying eligibility does not
    hand out a badge."

    PRD §3.6: "On success the new waiver is written in `SIGNED` status with
    `signed_at` stamped from the logical clock, the member's previously `SIGNED`
    waiver — if there was one — moves to `SUPERSEDED`, and the member's
    `current_waiver_id` is repointed at the new waiver while the member's own
    `version` advances."

    PRD §3.6: "A grant leaves `eligibility_status` unchanged."

    Design: Difficulty/non_linear_state_machine/member_eligibility_and_access_dimensions_move_independently
    """
    scenario = scenarios.setup_active_contract()
    contract_id = scenario["contract_id"]

    # Hop 0 — (PENDING_VERIFICATION, NO_BADGE) with the site population empty.
    member = scenarios.enrol_member(
        scenario, full_name="Ada Kim", employee_number="E-1001"
    )
    member_id = member["id"]
    assert_member(member)
    assert member["eligibility_status"] == "PENDING_VERIFICATION", (
        f"expected PENDING_VERIFICATION at enrolment, got "
        f"{member['eligibility_status']}"
    )
    assert member["access_status"] == "NO_BADGE", (
        f"expected NO_BADGE at enrolment, got {member['access_status']}"
    )
    assert member["current_waiver_id"] is None, (
        f"expected current_waiver_id null at enrolment, got "
        f"{member['current_waiver_id']}"
    )
    contract = scenarios.read_contract(contract_id)
    assert_client_contract(contract)
    assert contract["eligible_member_count"] == 0, (
        f"expected eligible_member_count 0 before verification, got "
        f"{contract['eligible_member_count']}"
    )

    # Hop 1 — VERIFY moves eligibility only; access stays where it was.
    verified = scenarios.verify_member(scenario, member_id)
    assert verified["eligibility_status"] == "ELIGIBLE", (
        f"expected ELIGIBLE after VERIFY, got {verified['eligibility_status']}"
    )
    assert verified["access_status"] == "NO_BADGE", (
        f"expected access_status to stay NO_BADGE across VERIFY, got "
        f"{verified['access_status']}"
    )
    assert scenarios.read_contract(contract_id)["eligible_member_count"] == 1, (
        "VERIFY must increment the contract's eligible_member_count by 1"
    )

    # Hop 2 — the waiver the badge grant depends on, filed by the member.
    waiver = scenarios.file_waiver(
        scenario, member_id, headers=make_member_headers(member_id)
    )
    assert_liability_waiver(waiver)
    assert waiver["status"] == "SIGNED", (
        f"expected the filed waiver in SIGNED status, got {waiver['status']}"
    )
    after_waiver = scenarios.read_member(member_id)
    assert after_waiver["current_waiver_id"] == waiver["id"], (
        f"expected current_waiver_id repointed at {waiver['id']}, got "
        f"{after_waiver['current_waiver_id']}"
    )
    assert after_waiver["eligibility_status"] == "ELIGIBLE", (
        "filing a waiver must not move the eligibility dimension"
    )
    assert after_waiver["access_status"] == "NO_BADGE", (
        "filing a waiver must not hand out a badge on its own"
    )

    # Hop 3 — (ELIGIBLE, ACTIVE): the access dimension finally moves.
    granted = scenarios.grant_badge(scenario, member_id, badge_number="B-1001")
    assert granted["access_status"] == "ACTIVE", (
        f"expected ACTIVE after the badge grant, got {granted['access_status']}"
    )
    assert granted["eligibility_status"] == "ELIGIBLE", (
        f"expected eligibility_status unchanged by the grant, got "
        f"{granted['eligibility_status']}"
    )
    assert scenarios.read_contract(contract_id)["eligible_member_count"] == 1, (
        "a badge grant must not move the eligible population count"
    )


def test_member_lapse_revokes_the_badge_but_reinstatement_does_not_restore_it():
    """PRD §3.6: "**Lapsing** takes the member `ELIGIBLE → LAPSED`, decrements
    `eligible_member_count` by 1, and has two cross-cutting consequences: if the
    member's `access_status` was `ACTIVE`, it moves to `REVOKED`, and if the
    member's `member_class` is `EMPLOYEE`, every dependent whose
    `sponsor_member_id` names this member and who is currently `ELIGIBLE` also
    moves to `LAPSED`, each with the same badge consequence and the same
    decrement."

    PRD §3.6: "**Reinstatement** takes the member `LAPSED → ELIGIBLE`, again
    requiring the contract to be `ACTIVE` and, for a dependent, an `ELIGIBLE`
    sponsor, and increments `eligible_member_count` by 1."

    PRD §3.6: "Crucially, reinstatement leaves `access_status` at `REVOKED`: the
    dimensions do not re-couple automatically, and a badge must be granted
    afresh."

    PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from `REVOKED` to
    `ACTIVE`, and is gated twice: the member's `eligibility_status` must be
    `ELIGIBLE`, failing which the request is refused with
    `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a liability waiver
    in `SIGNED` status whose `expires_on` falls at or after today, failing which
    the request is refused with `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/member_eligibility_and_access_dimensions_move_independently
    """
    scenario = scenarios.setup_active_contract()
    contract_id = scenario["contract_id"]

    member = scenarios.enrol_member(
        scenario, full_name="Ada Kim", employee_number="E-1001"
    )
    member_id = member["id"]
    scenarios.verify_member(scenario, member_id)
    waiver = scenarios.file_waiver(
        scenario, member_id, headers=make_member_headers(member_id)
    )
    scenarios.grant_badge(scenario, member_id, badge_number="B-1001")

    starting = scenarios.read_member(member_id)
    assert (starting["eligibility_status"], starting["access_status"]) == (
        "ELIGIBLE",
        "ACTIVE",
    ), (
        f"expected (ELIGIBLE, ACTIVE) before the lapse, got "
        f"({starting['eligibility_status']}, {starting['access_status']})"
    )

    # Hop 1 — (LAPSED, REVOKED): the lapse drags the badge down with it.
    lapsed = validate_success(
        api_client.eligibility_decision(
            member_id,
            {"action": "LAPSE", "reason": "Left the payroll file"},
            scenario["sponsor_headers"],
        )
    )
    assert_member(lapsed)
    assert lapsed["eligibility_status"] == "LAPSED", (
        f"expected LAPSED after the lapse decision, got {lapsed['eligibility_status']}"
    )
    assert lapsed["access_status"] == "REVOKED", (
        f"expected the ACTIVE badge revoked by the lapse, got {lapsed['access_status']}"
    )
    assert scenarios.read_contract(contract_id)["eligible_member_count"] == 0, (
        "the lapse must decrement the contract's eligible_member_count by 1"
    )
    assert scenarios.read_waiver(waiver["id"])["status"] == "SIGNED", (
        "the lapse enumerates its consequences and the waiver is not among them"
    )

    # Hop 2 — (ELIGIBLE, REVOKED): the dimensions deliberately do not re-couple.
    reinstated = validate_success(
        api_client.eligibility_decision(
            member_id, {"action": "REINSTATE"}, scenario["sponsor_headers"]
        )
    )
    assert reinstated["eligibility_status"] == "ELIGIBLE", (
        f"expected ELIGIBLE after reinstatement, got "
        f"{reinstated['eligibility_status']}"
    )
    assert reinstated["access_status"] == "REVOKED", (
        f"expected access_status to stay REVOKED across reinstatement, got "
        f"{reinstated['access_status']}"
    )
    assert scenarios.read_contract(contract_id)["eligible_member_count"] == 1, (
        "reinstatement must increment the contract's eligible_member_count by 1"
    )

    # Hop 3 — (ELIGIBLE, ACTIVE) again, but only via a fresh badge grant.
    regranted = scenarios.grant_badge(scenario, member_id, badge_number="B-1001")
    assert regranted["access_status"] == "ACTIVE", (
        f"expected a fresh grant to move REVOKED back to ACTIVE, got "
        f"{regranted['access_status']}"
    )
    assert regranted["eligibility_status"] == "ELIGIBLE", (
        f"expected eligibility_status unchanged by the second grant, got "
        f"{regranted['eligibility_status']}"
    )
    assert scenarios.read_waiver(waiver["id"])["status"] == "SIGNED", (
        "the waiver signed before the eligibility loop must still be SIGNED"
    )


# ==========================================================================
# Contract suspension: the four-link offering -> session -> assignment -> ledger
# cascade
# ==========================================================================
def test_contract_suspension_cascades_offering_session_assignment_and_committed_minutes():
    """PRD §3.1: "**Suspension** takes the contract `ACTIVE → SUSPENDED` and
    triggers the system's deepest cascade, four links long."

    PRD §3.1: "First, every program offering of the contract in `ACTIVE` status
    moves to `PAUSED`, processed in ascending order of when the offerings were
    created."

    PRD §3.1: "Second, each offering's move to `PAUSED` cancels that offering's
    sessions in `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` status: each moves
    to `CANCELLED_CLIENT` with `cancel_reason` set to `CLIENT_REQUEST`, processed
    in ascending `scheduled_start_utc` order with creation order as the
    tie-break."

    PRD §3.1: "Third, each session cancellation releases that session's staffing
    assignments in `ASSIGNED` or `CONFIRMED` status, moving them to `RELEASED`."

    PRD §3.1: "Fourth, each release subtracts that assignment's `paid_minutes`
    from the staff member's `committed_minutes_current_period` and triggers a
    recomputation of the owning offering's `provisional_attainment_pct`."

    Design: Difficulty/transitive_cascade/contract_suspend_four_link_cascade_offering_session_assignment_ledger
    """
    scenario, session, assignment = scenarios.setup_staffed_session()
    contract_id = scenario["contract_id"]
    offering_id = scenario["offering_id"]
    session_id = session["id"]
    assignment_id = assignment["id"]
    instructor_id = scenario["instructor_id"]

    # Head of the chain, before the trigger.
    assert_program_session(session)
    assert session["status"] == "STAFFED", (
        f"expected STAFFED once the LEAD confirmed, got {session['status']}"
    )
    assert scenarios.read_offering(offering_id)["status"] == "ACTIVE", (
        "the offering must be ACTIVE before the suspension so LINK 1 has work"
    )
    assert scenarios.read_assignment(assignment_id)["status"] == "CONFIRMED", (
        "the lead assignment must be CONFIRMED before the suspension"
    )
    before_staff = scenarios.read_staff(instructor_id)
    assert before_staff["committed_minutes_current_period"] == 70, (
        f"expected 70 committed minutes (55 scheduled plus the 15-minute LEAD "
        f"setup allowance), got {before_staff['committed_minutes_current_period']}"
    )
    before_offering = scenarios.read_offering(offering_id)
    assert before_offering["provisional_attainment_pct"] == 75, (
        f"expected provisional attainment 75 (one open session forecasting 3 "
        f"against a target of 4), got {before_offering['provisional_attainment_pct']}"
    )

    validate_success(
        api_client.service_status(
            contract_id,
            {"action": "SUSPEND", "reason": "Client site shutdown for HVAC works"},
            scenario["admin_headers"],
        )
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {contract['status']} after the suspend action"
    )

    # LINK 1 — the offering pauses.
    paused = scenarios.read_offering(offering_id)
    assert_program_offering(paused)
    assert paused["status"] == "PAUSED", (
        f"expected the ACTIVE offering to move to PAUSED, got {paused['status']}"
    )

    # LINK 2 — the pause cancels the offering's open session.
    cancelled = scenarios.read_session(session_id)
    assert_program_session(cancelled)
    assert cancelled["status"] == "CANCELLED_CLIENT", (
        f"expected CANCELLED_CLIENT from the pause, got {cancelled['status']}"
    )
    assert cancelled["cancel_reason"] == "CLIENT_REQUEST", (
        f"expected cancel_reason CLIENT_REQUEST, got {cancelled['cancel_reason']}"
    )

    # LINK 3 — the cancellation releases the session's confirmed assignment.
    released = scenarios.read_assignment(assignment_id)
    assert_staff_assignment(released)
    assert released["status"] == "RELEASED", (
        f"expected the CONFIRMED assignment RELEASED by the cancellation, got "
        f"{released['status']}"
    )

    # LINK 4 — the release returns the minutes and drops the vanished forecast.
    after_staff = scenarios.read_staff(instructor_id)
    assert after_staff["committed_minutes_current_period"] == 0, (
        f"expected the released assignment's 70 paid minutes returned, got "
        f"{after_staff['committed_minutes_current_period']} committed minutes"
    )
    after_offering = scenarios.read_offering(offering_id)
    assert after_offering["provisional_attainment_pct"] == 0, (
        f"expected provisional attainment 0 once the cancelled session's forecast "
        f"left the numerator, got {after_offering['provisional_attainment_pct']}"
    )


def test_contract_suspension_closes_rooms_without_accruing_a_coverage_penalty():
    """PRD §3.1: "Independently of the four-link chain, every room of the
    contract moves to `CLOSED`, whether it was `OPEN` or `RESTRICTED` at the
    time; rooms that were restricted keep their `open_deficiency_count` intact
    precisely so that a later resume can tell them apart."

    PRD §3.5: "A `cancel_reason` of `CLIENT_REQUEST` moves the session from
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` to `CANCELLED_CLIENT`."

    PRD §3.5: "The contract's `uncovered_session_count` is **not** incremented
    and no penalty accrues."

    Design: Difficulty/transitive_cascade/contract_suspend_four_link_cascade_offering_session_assignment_ledger
    """
    scenario, session, assignment = scenarios.setup_staffed_session()
    contract_id = scenario["contract_id"]
    room_id = scenario["room_id"]

    before_room = scenarios.read_room(room_id)
    assert before_room["room_state"] == "OPEN", (
        f"expected the studio OPEN before the suspension, got "
        f"{before_room['room_state']}"
    )
    before_contract = scenarios.read_contract(contract_id)
    assert before_contract["uncovered_session_count"] == 0, (
        "the contract must start with no uncovered sessions on file"
    )
    assert before_contract["pending_penalty_cents"] == 0, (
        "the contract must start with no penalty accrued"
    )

    validate_success(
        api_client.service_status(
            contract_id,
            {"action": "SUSPEND", "reason": "Client site shutdown for HVAC works"},
            scenario["admin_headers"],
        )
    )

    closed_room = scenarios.read_room(room_id)
    assert closed_room["room_state"] == "CLOSED", (
        f"expected the OPEN studio CLOSED by the suspension, got "
        f"{closed_room['room_state']}"
    )
    assert closed_room["open_deficiency_count"] == 0, (
        f"expected the room's deficiency count untouched at 0, got "
        f"{closed_room['open_deficiency_count']}"
    )

    cancelled = scenarios.read_session(session["id"])
    assert cancelled["status"] == "CANCELLED_CLIENT", (
        f"expected the client branch of cancellation, got {cancelled['status']}"
    )

    after_contract = scenarios.read_contract(contract_id)
    assert after_contract["uncovered_session_count"] == 0, (
        f"a client-caused cancellation must not increment uncovered_session_count, "
        f"got {after_contract['uncovered_session_count']}"
    )
    assert after_contract["pending_penalty_cents"] == 0, (
        f"a client-caused cancellation must accrue no coverage penalty, got "
        f"{after_contract['pending_penalty_cents']}"
    )
    assert scenarios.read_assignment(assignment["id"])["status"] == "RELEASED", (
        "the suspension's session cancellation must still release the lead"
    )


# ==========================================================================
# The ops run: credential -> duty -> assignment -> session -> penalty ledger
# ==========================================================================
def test_readiness_run_expiry_cascades_from_credential_to_uncovered_cancellations():
    """PRD §3.9: "Every credential of the contract's staff in `VERIFIED` status
    whose `expires_on` falls at or before today plus 30 days but strictly after
    today moves to `EXPIRING_SOON`; every credential in `VERIFIED` or
    `EXPIRING_SOON` status whose `expires_on` falls at or before today moves to
    `EXPIRED`."

    PRD §3.9: "First, when the expired credential's `credential_type` is one of
    those required for the holder's `role_type`, the holder moves from
    `ACTIVE_DUTY` to `SUSPENDED_FROM_DUTY` and their `readiness_index` is forced
    to 0."

    PRD §3.9: "Second, every assignment of that suspended person in `ASSIGNED` or
    `CONFIRMED` status on a session in `SCHEDULED`, `STAFFED`, or
    `STAFFING_AT_RISK` status moves to `VACANT_NEEDS_COVER`, each vacancy
    subtracting that assignment's `paid_minutes` from the person's
    `committed_minutes_current_period`."

    PRD §3.9: "Third, every session whose `LEAD` was just vacated moves to
    `STAFFING_AT_RISK` and the owning offering's `coverage_gap_count` increases by
    1."

    PRD §3.9: "Fourth, every session now at risk whose `scheduled_start_utc`
    falls at or before the current instant plus 24 hours is cancelled as an
    uncovered session: it moves to `CANCELLED_NO_COVER` with `cancel_reason` of
    `NO_COVER`, the contract's `uncovered_session_count` increases by 1, the
    contract's `pending_penalty_cents` is recomputed, and the offering's
    `provisional_attainment_pct` is recomputed."

    Design: Difficulty/transitive_cascade/credential_expiry_staffing_cascade_through_daily_readiness_run
    """
    scenario = _setup_expiry_staffing_cascade()
    contract_id = scenario["contract_id"]
    offering_id = scenario["offering_id"]
    instructor_id = scenario["instructor_id"]
    first_session_id, second_session_id = scenario["session_ids"]
    first_assignment_id, second_assignment_id = scenario["assignment_ids"]

    # Head of the chain, before the trigger.
    for session_id in (first_session_id, second_session_id):
        staffed = scenarios.read_session(session_id)
        assert staffed["status"] == "STAFFED", (
            f"expected session {session_id} STAFFED before the run, got "
            f"{staffed['status']}"
        )
    before_staff = scenarios.read_staff(instructor_id)
    assert before_staff["committed_minutes_current_period"] == 140, (
        f"expected 140 committed minutes across two 70-minute LEAD assignments, "
        f"got {before_staff['committed_minutes_current_period']}"
    )
    assert scenarios.read_offering(offering_id)["coverage_gap_count"] == 0, (
        "the offering must start with no coverage gaps recorded"
    )

    scenarios.set_clock(SWEEP_INSTANT_UTC)
    scenarios.run_readiness_sweep(contract_id)

    # LINK 1 — the credential expires and drives its holder off duty.
    expired = scenarios.read_credential(scenario["credential_id"])
    assert expired["status"] == "EXPIRED", (
        f"expected EXPIRED, got {expired['status']} for a card that lapsed on "
        "2026-08-15"
    )
    suspended = scenarios.read_staff(instructor_id)
    assert suspended["duty_status"] == "SUSPENDED_FROM_DUTY", (
        f"expected SUSPENDED_FROM_DUTY from the expiry of a required type, got "
        f"{suspended['duty_status']}"
    )
    assert suspended["readiness_index"] == 0, (
        f"expected readiness_index pinned at 0 for the just-suspended holder, got "
        f"{suspended['readiness_index']}"
    )

    # LINK 2 — the suspension vacates both live assignments and returns minutes.
    # Link 4 then cancels both sessions on the NO_COVER branch, and PRD §3.5
    # fixes that branch's side effects: "assignments in `ASSIGNED`, `CONFIRMED`,
    # **or** `VACANT_NEEDS_COVER` status move to `RELEASED` with the same
    # committed-minutes compensation (and, as always, no double subtraction for
    # one already vacated). ... This is the branch the nightly sweep takes for
    # at-risk sessions inside the lock window."  So the observable end state of a
    # vacated assignment whose session was then cancelled is RELEASED.
    for assignment_id in (first_assignment_id, second_assignment_id):
        vacated = scenarios.read_assignment(assignment_id)
        assert_staff_assignment(vacated)
        assert vacated["status"] == "RELEASED", (
            f"expected assignment {assignment_id} RELEASED once link 4 cancelled "
            f"its session on the NO_COVER branch, got {vacated['status']}"
        )
    assert scenarios.read_staff(instructor_id)["committed_minutes_current_period"] == 0, (
        "both vacancies must subtract their paid_minutes from the holder's ledger"
    )

    # LINK 3 — each vacated LEAD pushed its session into the at-risk state,
    # which the offering's cumulative coverage tally records.
    after_offering = scenarios.read_offering(offering_id)
    assert after_offering["coverage_gap_count"] == 2, (
        f"expected coverage_gap_count 2, one per session whose LEAD was vacated, "
        f"got {after_offering['coverage_gap_count']}"
    )

    # LINK 4 — both at-risk sessions sit inside the 24-hour lock window.
    for session_id in (first_session_id, second_session_id):
        no_cover = scenarios.read_session(session_id)
        assert no_cover["status"] == "CANCELLED_NO_COVER", (
            f"expected session {session_id} CANCELLED_NO_COVER inside the lock "
            f"window, got {no_cover['status']}"
        )
        assert no_cover["cancel_reason"] == "NO_COVER", (
            f"expected cancel_reason NO_COVER, got {no_cover['cancel_reason']}"
        )
    contract = scenarios.read_contract(contract_id)
    assert contract["uncovered_session_count"] == 2, (
        f"expected uncovered_session_count 2, got "
        f"{contract['uncovered_session_count']}"
    )
    assert after_offering["provisional_attainment_pct"] == 0, (
        f"expected provisional attainment 0 once both forecasts left the "
        f"numerator, got {after_offering['provisional_attainment_pct']}"
    )


def test_readiness_run_expiry_cascade_accrues_the_management_fee_coverage_penalty():
    """PRD §3.5: "On a `MANAGEMENT_FEE` contract, first take the contract's
    `uncovered_session_count`, subtract a one-session allowance, and floor the
    result at 0 to obtain the chargeable count."

    PRD §3.5: "Then compute the per-session amount as 1.5 percent of
    `management_fee_cents`, rounded half up to whole cents, and the ceiling as 5
    percent of `management_fee_cents`, likewise rounded half up to whole cents —
    the two roundings are independent of one another."

    PRD §3.5: "The penalty is the chargeable count multiplied by the per-session
    amount, or the ceiling, whichever is smaller."

    PRD §3.9: "The run returns a tally of what it did, so that an operator can
    see the night's damage at a glance: the `contract_id` it ran against, the
    `run_at_utc` instant it ran at, and then `credentials_expiring_soon`,
    `credentials_expired`, `staff_suspended`, `assignments_vacated`,
    `sessions_at_risk`, `sessions_cancelled_no_cover`, `waivers_expired`,
    `badges_revoked`, `assets_maintenance_due`, `aed_not_ready`, and
    `penalty_accrued_cents`."

    PRD §3.9: "Every count is the number of records the run itself transitioned,
    not a standing total, so a second run over an unchanged contract returns
    zeros throughout."

    Design: Difficulty/transitive_cascade/credential_expiry_staffing_cascade_through_daily_readiness_run
    """
    scenario = _setup_expiry_staffing_cascade()
    contract_id = scenario["contract_id"]

    before_contract = scenarios.read_contract(contract_id)
    assert before_contract["pending_penalty_cents"] == 0, (
        f"expected no penalty accrued before the run, got "
        f"{before_contract['pending_penalty_cents']}"
    )

    scenarios.set_clock(SWEEP_INSTANT_UTC)
    tally = scenarios.run_readiness_sweep(contract_id)

    assert tally["contract_id"] == contract_id, (
        f"expected the tally to name the contract it ran against, got "
        f"{tally['contract_id']}"
    )
    assert tally["credentials_expired"] == 1, (
        f"expected 1 credential transitioned to EXPIRED, got "
        f"{tally['credentials_expired']}"
    )
    assert tally["staff_suspended"] == 1, (
        f"expected 1 staff member transitioned off duty, got "
        f"{tally['staff_suspended']}"
    )
    assert tally["assignments_vacated"] == 2, (
        f"expected 2 assignments transitioned to VACANT_NEEDS_COVER, got "
        f"{tally['assignments_vacated']}"
    )
    assert tally["sessions_at_risk"] == 2, (
        f"expected 2 sessions transitioned into STAFFING_AT_RISK by the vacated "
        f"leads, got {tally['sessions_at_risk']}"
    )
    assert tally["sessions_cancelled_no_cover"] == 2, (
        f"expected 2 sessions transitioned to CANCELLED_NO_COVER, got "
        f"{tally['sessions_cancelled_no_cover']}"
    )
    assert tally["penalty_accrued_cents"] == 600, (
        f"expected 600 cents accrued (2 uncovered less the 1-session allowance, "
        f"times 1.5 percent of a 40000-cent fee, under a 2000-cent ceiling), got "
        f"{tally['penalty_accrued_cents']}"
    )

    after_contract = scenarios.read_contract(contract_id)
    assert after_contract["uncovered_session_count"] == 2, (
        f"expected uncovered_session_count 2 on the contract, got "
        f"{after_contract['uncovered_session_count']}"
    )
    assert after_contract["pending_penalty_cents"] == 600, (
        f"expected pending_penalty_cents 600 on the contract, got "
        f"{after_contract['pending_penalty_cents']}"
    )
