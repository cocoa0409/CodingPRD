"""Input-validation corners: each scenario is arranged so that exactly one
business rule can fail, so the error identity the PRD names for that condition
is the only admissible answer and no evaluation order is implied.

Every rejected case is paired with the accepted case immediately inside the
same boundary, which is what proves the rule is a real edge rather than a
blanket refusal.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_DEFAULTS
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_client_contract, assert_member, assert_program_session
from test_helpers.factories import (
    client_contract_payload,
    management_fee_contract_payload,
    member_payload,
    participation_payload,
    program_session_payload,
)


# ==========================================================================
# Fee-term consistency at contract creation
# ==========================================================================
def test_cost_plus_contract_missing_not_to_exceed_rejected(api, clock, operator_admin_headers):
    """PRD §3.1: "A `COST_PLUS` contract must carry `not_to_exceed_cents` — an
    annual ceiling strictly greater than zero — and must leave
    `management_fee_cents` null."

    PRD §3.1: "Either mirror-image mistake, whether at contract creation, at
    amendment creation, or at submission time, is rejected with
    `ERR_FEE_TERMS_INVALID`."

    Design: Corner/validations/fee_terms_mismatch_on_contract_create_rejected
    """
    incomplete = client_contract_payload(site_code="NWM-01")
    incomplete.pop("not_to_exceed_cents")

    rejected = api.create_client_contract(incomplete, operator_admin_headers)
    validate_error(rejected, ApiErrorId.ERR_FEE_TERMS_INVALID.value)

    # Immediately inside the boundary: the very same payload once the annual
    # ceiling the cost-plus model requires is supplied.
    complete = client_contract_payload(site_code="NWM-02")
    created = validate_success(
        api.create_client_contract(complete, operator_admin_headers), 201
    )
    assert_client_contract(created)
    assert created["status"] == "DRAFT", (
        f"expected DRAFT, got {created['status']} for a freshly created cost-plus contract"
    )
    assert created["not_to_exceed_cents"] == TEST_DEFAULTS["NOT_TO_EXCEED_CENTS"], (
        f"expected not_to_exceed_cents {TEST_DEFAULTS['NOT_TO_EXCEED_CENTS']}, "
        f"got {created['not_to_exceed_cents']}"
    )
    assert created["management_fee_cents"] is None, (
        f"a COST_PLUS contract must leave management_fee_cents null, "
        f"got {created['management_fee_cents']}"
    )

    _, meta = validate_paginated(api.list_client_contracts(operator_admin_headers))
    assert meta["total_count"] == 1, (
        f"expected 1 contract, got {meta['total_count']}: the rejected create must "
        "not have written a row"
    )


def test_management_fee_contract_carrying_not_to_exceed_rejected(
    api, clock, operator_admin_headers
):
    """PRD §3.1: "A `MANAGEMENT_FEE` contract must carry `management_fee_cents`
    — a flat monthly amount of at least zero — and must leave
    `not_to_exceed_cents` null."

    PRD §3.1: "Either mirror-image mistake, whether at contract creation, at
    amendment creation, or at submission time, is rejected with
    `ERR_FEE_TERMS_INVALID`."

    Design: Corner/validations/fee_terms_mismatch_on_contract_create_rejected
    """
    overreaching = management_fee_contract_payload(
        site_code="AXL-01", not_to_exceed_cents=TEST_DEFAULTS["NOT_TO_EXCEED_CENTS"]
    )
    rejected = api.create_client_contract(overreaching, operator_admin_headers)
    validate_error(rejected, ApiErrorId.ERR_FEE_TERMS_INVALID.value)

    # Immediately inside the boundary: the flat fee alone, with the annual
    # ceiling left out entirely.
    clean = management_fee_contract_payload(site_code="AXL-02")
    created = validate_success(
        api.create_client_contract(clean, operator_admin_headers), 201
    )
    assert_client_contract(created)
    assert created["status"] == "DRAFT", (
        f"expected DRAFT, got {created['status']} for a freshly created management-fee contract"
    )
    assert created["management_fee_cents"] == TEST_DEFAULTS["MANAGEMENT_FEE_CENTS"], (
        f"expected management_fee_cents {TEST_DEFAULTS['MANAGEMENT_FEE_CENTS']}, "
        f"got {created['management_fee_cents']}"
    )
    assert created["not_to_exceed_cents"] is None, (
        f"a MANAGEMENT_FEE contract must leave not_to_exceed_cents null, "
        f"got {created['not_to_exceed_cents']}"
    )

    _, meta = validate_paginated(api.list_client_contracts(operator_admin_headers))
    assert meta["total_count"] == 1, (
        f"expected 1 contract, got {meta['total_count']}: the rejected create must "
        "not have written a row"
    )


# ==========================================================================
# Dependent sponsorship
# ==========================================================================
def test_dependent_with_eligible_employee_sponsor_enrolled(api):
    """PRD §3.6: "The dependent's sponsor must itself be a member whose
    `member_class` is `EMPLOYEE` and whose `eligibility_status` is `ELIGIBLE`; a
    missing sponsor, a sponsor who is not an eligible employee, or a
    non-dependent that supplies a sponsor at all is refused with
    `ERR_SPONSOR_NOT_ELIGIBLE`."

    PRD §3.6: "A new enrolment starts at `PENDING_VERIFICATION` and `NO_BADGE`,
    with `incentive_points_balance` at 0, `current_waiver_id` null, and
    `last_check_in_utc` null."

    PRD §2.9: "A contract's `eligible_member_count` always equals the number of
    that contract's members whose `eligibility_status` is `ELIGIBLE`."

    Design: Corner/validations/dependent_member_with_eligible_sponsor_succeeds
    """
    scenario = scenarios.setup_active_contract()
    sponsor = scenarios.enrol_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    scenarios.verify_member(scenario, sponsor["id"])
    assert scenarios.read_member(sponsor["id"])["eligibility_status"] == "ELIGIBLE", (
        "the sponsoring employee must be ELIGIBLE before the dependent is enrolled"
    )

    dependent = validate_success(
        api.create_member(
            member_payload(
                scenario["contract_id"],
                member_class="DEPENDENT",
                full_name="Noa Okafor",
                employee_number=None,
                sponsor_member_id=sponsor["id"],
            ),
            scenario["sponsor_headers"],
        ),
        201,
    )
    assert_member(dependent)
    assert dependent["member_class"] == "DEPENDENT", (
        f"expected DEPENDENT, got {dependent['member_class']}"
    )
    assert dependent["sponsor_member_id"] == sponsor["id"], (
        f"expected sponsor_member_id {sponsor['id']}, got {dependent['sponsor_member_id']}"
    )
    assert dependent["eligibility_status"] == "PENDING_VERIFICATION", (
        f"expected PENDING_VERIFICATION, got {dependent['eligibility_status']} "
        "on a fresh dependent enrolment"
    )
    assert dependent["employee_number"] is None, (
        f"a DEPENDENT must leave employee_number null, got {dependent['employee_number']}"
    )

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["eligible_member_count"] == 1, (
        f"expected eligible_member_count 1, got {contract['eligible_member_count']}: only "
        "the verified sponsor counts, the new dependent is still PENDING_VERIFICATION"
    )


def test_dependent_without_sponsor_and_employee_with_sponsor_rejected(api):
    """PRD §3.6: "A `DEPENDENT` must carry a `sponsor_member_id` naming the
    sponsoring employee, and an `EMPLOYEE` or `RETIREE` must leave it null."

    PRD §3.6: "The dependent's sponsor must itself be a member whose
    `member_class` is `EMPLOYEE` and whose `eligibility_status` is `ELIGIBLE`; a
    missing sponsor, a sponsor who is not an eligible employee, or a
    non-dependent that supplies a sponsor at all is refused with
    `ERR_SPONSOR_NOT_ELIGIBLE`."

    Design: Corner/validations/dependent_member_with_eligible_sponsor_succeeds
    """
    scenario = scenarios.setup_active_contract()
    sponsor = scenarios.enrol_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    scenarios.verify_member(scenario, sponsor["id"])

    # Arm one: a dependent that names nobody. Every other field is well-formed,
    # so the sponsorship rule is the only one that can fail.
    no_sponsor = api.create_member(
        member_payload(
            scenario["contract_id"],
            member_class="DEPENDENT",
            full_name="Sam Okafor",
            employee_number=None,
        ),
        scenario["sponsor_headers"],
    )
    validate_error(no_sponsor, ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value)

    # Arm two: the mirror image — an employee that names a sponsor it may not have.
    employee_with_sponsor = api.create_member(
        member_payload(
            scenario["contract_id"],
            member_class="EMPLOYEE",
            full_name="Ben Alvarez",
            employee_number="E-1002",
            sponsor_member_id=sponsor["id"],
        ),
        scenario["sponsor_headers"],
    )
    validate_error(employee_with_sponsor, ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value)

    _, meta = validate_paginated(
        api.list_members(
            scenario["admin_headers"], params={"contract_id": scenario["contract_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1 member, got {meta['total_count']}: neither rejected enrolment "
        "may have written a row"
    )


# ==========================================================================
# Term containment on session scheduling
# ==========================================================================
def test_session_starting_after_the_contract_term_end_rejected(api):
    """PRD §3.5: "**Term containment** forbids backdating and overreach:
    `scheduled_start_utc` must be at or after the current logical clock instant,
    and the session's dates must fall inside the contract's `term_start_on`
    through `term_end_on` window inclusive. A violation of either half is
    refused with `ERR_SESSION_OUT_OF_TERM`."

    PRD §3.5: "A new session lands in `SCHEDULED` with `actual_attendance` at 0,
    `cancel_reason`, `started_at`, and `completed_at` all null, and a computed
    `scheduled_minutes` equal to the whole number of minutes between its start
    and end instants."

    Design: Corner/validations/session_outside_the_contract_term_rejected
    """
    scenario = scenarios.setup_active_program()
    assert scenario["contract"]["term_end_on"] == "2027-06-30", (
        f"expected a term ending 2027-06-30, got {scenario['contract']['term_end_on']}"
    )

    # Five days past the end of the term, and in the future relative to the
    # clock, so overreach is the only half of the rule that can fail.
    overreaching = api.create_program_session(
        program_session_payload(
            scenario["offering_id"],
            scenario["room_id"],
            scheduled_start_utc="2027-07-05T12:00:00Z",
            scheduled_end_utc="2027-07-05T12:55:00Z",
        ),
        scenario["manager_headers"],
    )
    validate_error(overreaching, ApiErrorId.ERR_SESSION_OUT_OF_TERM.value)

    # Immediately inside the boundary: the last calendar day of the term, which
    # the window includes.
    accepted = validate_success(
        api.create_program_session(
            program_session_payload(
                scenario["offering_id"],
                scenario["room_id"],
                scheduled_start_utc="2027-06-30T12:00:00Z",
                scheduled_end_utc="2027-06-30T12:55:00Z",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert_program_session(accepted)
    assert accepted["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {accepted['status']} for a session on the term's last day"
    )
    assert accepted["scheduled_minutes"] == 55, (
        f"expected scheduled_minutes 55, got {accepted['scheduled_minutes']}"
    )

    _, meta = validate_paginated(
        api.list_program_sessions(
            scenario["admin_headers"], params={"offering_id": scenario["offering_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1 session, got {meta['total_count']}: the out-of-term request must "
        "not have written a row"
    )


def test_session_starting_before_the_logical_clock_rejected(api):
    """PRD §3.5: "**Term containment** forbids backdating and overreach:
    `scheduled_start_utc` must be at or after the current logical clock instant,
    and the session's dates must fall inside the contract's `term_start_on`
    through `term_end_on` window inclusive. A violation of either half is
    refused with `ERR_SESSION_OUT_OF_TERM`."

    PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`, and
    it never falls back to real time."

    Design: Corner/validations/session_outside_the_contract_term_rejected
    """
    scenario = scenarios.setup_active_program()

    # 2026-07-15 sits comfortably inside the 2026-07-01 -> 2027-06-30 term, so
    # backdating against the 2026-08-01 clock is the only half that can fail.
    backdated = api.create_program_session(
        program_session_payload(
            scenario["offering_id"],
            scenario["room_id"],
            scheduled_start_utc="2026-07-15T12:00:00Z",
            scheduled_end_utc="2026-07-15T12:55:00Z",
        ),
        scenario["manager_headers"],
    )
    validate_error(backdated, ApiErrorId.ERR_SESSION_OUT_OF_TERM.value)

    # Immediately inside the boundary: a start at exactly the clock instant,
    # which "at or after" admits.
    accepted = validate_success(
        api.create_program_session(
            program_session_payload(
                scenario["offering_id"],
                scenario["room_id"],
                scheduled_start_utc="2026-08-01T00:00:00Z",
                scheduled_end_utc="2026-08-01T00:55:00Z",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert_program_session(accepted)
    assert accepted["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {accepted['status']} for a session starting exactly "
        "at the logical clock instant"
    )
    assert accepted["scheduled_minutes"] == 55, (
        f"expected scheduled_minutes 55, got {accepted['scheduled_minutes']}"
    )

    _, meta = validate_paginated(
        api.list_program_sessions(
            scenario["admin_headers"], params={"offering_id": scenario["offering_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1 session, got {meta['total_count']}: the backdated request must "
        "not have written a row"
    )


# ==========================================================================
# Session roster capacity at check-in
# ==========================================================================
def test_check_in_beyond_the_offering_roster_cap_rejected(api):
    """PRD §3.7: "The session must have room: the number of that session's
    records still in `COUNTED` status must be strictly below the offering's
    `max_participants_per_session`, and a full session is refused with
    `ERR_SESSION_CAPACITY_EXCEEDED`; because voided records are not counted,
    voiding one genuinely frees a slot."

    PRD §2.9: "A member's `incentive_points_balance` always equals the sum of
    `points_awarded` across that member's participation records still in
    `COUNTED` status."

    Design: Corner/validations/session_capacity_exceeded_at_the_offering_maximum
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={"max_participants_per_session": 1}
    )
    first = scenarios.setup_ready_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    second = scenarios.setup_ready_member(
        scenario, full_name="Ben Alvarez", employee_number="E-1002"
    )
    scenario, session, _assignment = scenarios.setup_in_progress_session(
        scenario, forecast_attendance=1
    )

    # Both members are eligible, waivered, badged and of an eligible class, so
    # the single roster slot is the only thing that can fail.
    scenarios.check_in(scenario, first["id"], session["id"])

    overfull = api.create_participation_record(
        participation_payload(second["id"], session["id"]),
        scenario["instructor_headers"],
    )
    validate_error(overfull, ApiErrorId.ERR_SESSION_CAPACITY_EXCEEDED.value)

    after = scenarios.read_session(session["id"])
    assert after["actual_attendance"] == 1, (
        f"expected actual_attendance 1, got {after['actual_attendance']} after the "
        "refused second check-in"
    )
    assert after["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS, got {after['status']}: a refused check-in changes no state"
    )

    _, meta = validate_paginated(
        api.list_participation_records(
            scenario["admin_headers"], params={"session_id": session["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1 participation record, got {meta['total_count']}: the refused "
        "check-in must not have written a row"
    )
    assert scenarios.read_member(second["id"])["incentive_points_balance"] == 0, (
        "the turned-away member must earn no incentive points"
    )
    assert scenarios.read_member(first["id"])["incentive_points_balance"] == 10, (
        "the admitted member keeps the 10 points their check-in awarded"
    )


def test_check_in_at_the_last_free_roster_slot_succeeds(api):
    """PRD §3.7: "The session must have room: the number of that session's
    records still in `COUNTED` status must be strictly below the offering's
    `max_participants_per_session`, and a full session is refused with
    `ERR_SESSION_CAPACITY_EXCEEDED`; because voided records are not counted,
    voiding one genuinely frees a slot."

    PRD §3.7: "The check-in also updates the aggregate figures: the session's
    `actual_attendance` increases by 1, the offering's
    `counted_participation_total` increases by 1, and both of the offering's
    attainment percentages are recomputed."

    Design: Corner/validations/session_capacity_exceeded_at_the_offering_maximum
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={"max_participants_per_session": 2}
    )
    first = scenarios.setup_ready_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    second = scenarios.setup_ready_member(
        scenario, full_name="Ben Alvarez", employee_number="E-1002"
    )
    scenario, session, _assignment = scenarios.setup_in_progress_session(
        scenario, forecast_attendance=2
    )

    scenarios.check_in(scenario, first["id"], session["id"])

    # Immediately inside the boundary: one counted record against a cap of two
    # is strictly below the cap, so the second member is admitted.
    admitted = validate_success(
        api.create_participation_record(
            participation_payload(second["id"], session["id"]),
            scenario["instructor_headers"],
        ),
        201,
    )
    assert admitted["status"] == "COUNTED", (
        f"expected COUNTED, got {admitted['status']} for the last free roster slot"
    )

    after = scenarios.read_session(session["id"])
    assert after["actual_attendance"] == 2, (
        f"expected actual_attendance 2, got {after['actual_attendance']} once the "
        "roster is exactly full"
    )
    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 2, (
        f"expected counted_participation_total 2, got {offering['counted_participation_total']}"
    )


# ==========================================================================
# Health-metric notes and the member's own consent flag
# ==========================================================================
def test_health_metrics_note_for_non_consenting_member_rejected(api):
    """PRD §2.10: "A participation record may carry a free-text
    `health_metrics_note`, but only when the subject member's
    `health_data_consent` flag is true."

    PRD §2.10: "Supplying the note for a member who has not consented is a hard
    rejection with `ERR_HEALTH_DATA_FORBIDDEN` (HTTP 403), not a silent drop of
    the field."

    PRD §3.6: "Enrolment also accepts `health_data_consent`, which defaults to
    false when omitted, and is the switch that governs whether health-metric
    notes may ever be attached to this person's participation."

    Design: Corner/validations/health_metrics_note_requires_member_consent
    """
    scenario = scenarios.setup_active_program()
    member = scenarios.setup_ready_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    scenario, session, _assignment = scenarios.setup_in_progress_session(scenario)

    assert scenarios.read_member(member["id"])["health_data_consent"] is False, (
        "health_data_consent must default to false when enrolment omits it"
    )

    # The member is eligible, badged, waivered and of an eligible class, and the
    # session is in progress with room to spare, so consent is the only gate.
    refused = api.create_participation_record(
        participation_payload(
            member["id"], session["id"], health_metrics_note="RHR 62 bpm, BP 118/74"
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_HEALTH_DATA_FORBIDDEN.value)

    _, meta = validate_paginated(
        api.list_participation_records(
            scenario["admin_headers"], params={"member_id": member["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected 0 participation records, got {meta['total_count']}: the refusal is "
        "a hard rejection, not a silent drop of the note"
    )
    assert scenarios.read_session(session["id"])["actual_attendance"] == 0, (
        "the refused check-in must leave actual_attendance at 0"
    )


def test_health_metrics_note_for_consenting_member_stored(api):
    """PRD §2.10: "A participation record may carry a free-text
    `health_metrics_note`, but only when the subject member's
    `health_data_consent` flag is true."

    PRD §2.10: "`ComplianceAuditor` principals see `health_metrics_note` in
    full, and a `Member` principal sees the note on their own records."

    PRD §3.7: "The uncapped candidate award is 10 points, plus a further 5
    points when that distinct-prior-day count is 3 or more."

    Design: Corner/validations/health_metrics_note_requires_member_consent
    """
    scenario = scenarios.setup_active_program()
    member = scenarios.setup_ready_member(
        scenario,
        full_name="Ben Alvarez",
        employee_number="E-1002",
        health_data_consent=True,
    )
    scenario, session, _assignment = scenarios.setup_in_progress_session(scenario)

    assert scenarios.read_member(member["id"])["health_data_consent"] is True, (
        "the consenting member's health_data_consent must be true"
    )

    # Immediately inside the boundary: the same call, the same note, and the
    # only difference is the subject's own consent flag.
    record = validate_success(
        api.create_participation_record(
            participation_payload(
                member["id"], session["id"], health_metrics_note="RHR 58 bpm, BP 112/70"
            ),
            scenario["instructor_headers"],
        ),
        201,
    )
    assert record["status"] == "COUNTED", (
        f"expected COUNTED, got {record['status']} for a consenting member's check-in"
    )
    assert record["points_awarded"] == 10, (
        f"expected points_awarded 10, got {record['points_awarded']} for a first "
        "check-in with no streak"
    )

    auditor_view = validate_success(
        api.get_participation_record(record["id"], scenario["auditor_headers"])
    )
    assert auditor_view["health_metrics_note"] == "RHR 58 bpm, BP 112/70", (
        f"expected the note to be stored in full, got {auditor_view['health_metrics_note']!r}"
    )
    assert scenarios.read_session(session["id"])["actual_attendance"] == 1, (
        "the accepted check-in must raise actual_attendance to 1"
    )
