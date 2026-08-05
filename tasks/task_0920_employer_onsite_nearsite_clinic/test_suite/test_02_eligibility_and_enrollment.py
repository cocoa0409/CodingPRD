"""The eligibility file, the closed coverage span, enrollment and its cascade."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_contract_quota_conservation,
    assert_period_money_conservation,
    assert_same_date,
    assert_site_slot_conservation,
    book,
    create_eligibility_record_payload,
    grant_authorization,
    make_employer_admin_headers,
    new_award,
    new_eligibility,
    new_employer,
    read_period,
    read_site,
    set_clock,
    setup_clinic,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


def test_future_coverage_row_blocks_enrollment():
    """PRD §3.3: "From that reading the server derives `coverage_status`: `FUTURE`
    when the clock date falls strictly before `effective_date`, `EFFECTIVE` when the
    clock date falls on or after `effective_date` and either there is no
    `termination_date` or the clock date falls on or before it, and `EXPIRED` when a
    `termination_date` exists and the clock date falls strictly after it."
    PRD §3.3: "Enrollment is refused with `ERR_NOT_ELIGIBLE_ON_DATE` when the named
    row does not cover the current clock date under the closed rule above — a
    `FUTURE` row and an `EXPIRED` row are both unenrollable."

    Design: Corner/entities/eligibility_coverage_status_future_blocks_enrollment
    """
    set_clock("2026-06-01T00:00:00Z")
    employer = new_employer(legal_name="Future Co", employer_code="FUT")
    headers = make_employer_admin_headers(employer["id"])
    record = new_eligibility(
        employer["id"],
        subscriber_external_id="S-3301",
        member_external_id="M-3301",
        tier="RETIREE",
        effective_date="2026-07-01",
    )

    assert record["coverage_status"] == "FUTURE"

    response = api_client.create_participant(
        {
            "employer_id": employer["id"],
            "eligibility_record_id": record["id"],
            "display_name": "Too Early",
        },
        headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_ELIGIBLE_ON_DATE.value, 422)

    _, meta = validate_paginated(
        api_client.list_participants(headers, params={"employer_id": employer["id"]})
    )
    assert meta["total_count"] == 0, "the refused enrollment must create no participant"


def test_overlapping_eligibility_span_rejected_and_abutting_span_accepted():
    """PRD §3.3: "A new row is refused with `ERR_DUPLICATE_ELIGIBILITY` when another
    row of the same `employer_id` and the same `member_external_id` has a coverage
    span sharing at least one date with the new span — two spans that merely abut,
    one ending the day before the other begins, do not overlap and are both accepted."

    Design: Corner/validations/duplicate_eligibility_row_with_overlapping_closed_span_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    employer = new_employer(legal_name="Dup Co", employer_code="DUP")
    headers = make_employer_admin_headers(employer["id"])
    new_eligibility(
        employer["id"],
        subscriber_external_id="S-4601",
        member_external_id="M-4601",
        effective_date="2026-01-01",
        termination_date="2026-06-30",
    )

    overlapping = api_client.create_eligibility_record(
        create_eligibility_record_payload(
            employer["id"],
            subscriber_external_id="S-4601",
            member_external_id="M-4601",
            effective_date="2026-06-30",
        ),
        headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_DUPLICATE_ELIGIBILITY.value, 409)

    abutting = api_client.create_eligibility_record(
        create_eligibility_record_payload(
            employer["id"],
            subscriber_external_id="S-4601",
            member_external_id="M-4601",
            effective_date="2026-07-01",
        ),
        headers,
    )
    validate_success(abutting, 201)

    _, meta = validate_paginated(
        api_client.list_eligibility_records(headers, params={"member_external_id": "M-4601"})
    )
    assert meta["total_count"] == 2


def test_booking_on_the_termination_date_itself_is_covered():
    """PRD §3.3: "**The coverage span is closed at both ends.** A member is covered
    on the `effective_date` itself, and — this is the part implementations most often
    get wrong — a member is *still covered on the `termination_date` itself*."
    PRD §2.6: "The participant's `enrollment_status` is `ACTIVE` and the backing
    `EligibilityRecord` covers the governing date under the closed-interval rule of
    §2.10. Otherwise `ERR_NOT_ELIGIBLE_ON_DATE`, HTTP 422. The governing date is the
    appointment's `service_date` for booking, rescheduling and check-in; the clock
    date for enrollment and for reinstatement; and `measurement_date` for a health
    assessment."

    Design: Difficulty/resource_temporal_overlap/eligibility_closed_span_covers_the_termination_date_itself
    """
    world = setup_clinic(
        employer={"legal_name": "Closed Span Co", "employer_code": "CSP"},
        site={"site_name": "CSP On-Site Clinic", "daily_slot_capacity": 8},
        eligibility={
            "subscriber_external_id": "S-2101",
            "member_external_id": "M-2101",
            "effective_date": "2026-01-01",
            "termination_date": "2026-06-08",
        },
        participant={"display_name": "Span Tester"},
    )
    api_client.create_staffing_shift(
        {
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "shift_start": "2026-06-09T08:00:00Z",
            "shift_end": "2026-06-09T17:00:00Z",
            "coverage_role": "PRIMARY_CARE",
        },
        world.manager_headers,
    )

    record = validate_success(
        api_client.get_eligibility_record(world.eligibility_id, world.employer_headers)
    )
    assert record["coverage_status"] == "EFFECTIVE"

    appointment = book(
        world.participant_id,
        world.site_id,
        world.clinician_id,
        "2026-06-08T09:00:00Z",
    )
    assert_same_date(appointment["service_date"], "2026-06-08")
    assert appointment["status"] == "BOOKED"
    assert read_site(world.site_id)["slots_held_count"] == 1


def test_booking_the_day_after_termination_is_not_eligible():
    """PRD §3.3: "**The coverage span is closed at both ends.** A member is covered
    on the `effective_date` itself, and — this is the part implementations most often
    get wrong — a member is *still covered on the `termination_date` itself*."
    PRD §2.6: "The participant's `enrollment_status` is `ACTIVE` and the backing
    `EligibilityRecord` covers the governing date under the closed-interval rule of
    §2.10. Otherwise `ERR_NOT_ELIGIBLE_ON_DATE`, HTTP 422. The governing date is the
    appointment's `service_date` for booking, rescheduling and check-in; the clock
    date for enrollment and for reinstatement; and `measurement_date` for a health
    assessment."

    Design: Difficulty/resource_temporal_overlap/eligibility_closed_span_covers_the_termination_date_itself
    """
    world = setup_clinic(
        employer={"legal_name": "Closed Span Co", "employer_code": "CSP"},
        site={"site_name": "CSP On-Site Clinic", "daily_slot_capacity": 8},
        eligibility={
            "subscriber_external_id": "S-2101",
            "member_external_id": "M-2101",
            "effective_date": "2026-01-01",
            "termination_date": "2026-06-08",
        },
        participant={"display_name": "Span Tester"},
    )
    api_client.create_staffing_shift(
        {
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "shift_start": "2026-06-09T08:00:00Z",
            "shift_end": "2026-06-09T17:00:00Z",
            "coverage_role": "PRIMARY_CARE",
        },
        world.manager_headers,
    )

    site = read_site(world.site_id, world.participant_headers)
    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-09T09:00:00Z",
            "expected_site_version": site["version"],
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_ELIGIBLE_ON_DATE.value, 422)
    assert read_site(world.site_id)["slots_requested_total"] == 0


def test_reinstatement_inside_grace_window_returns_participant_to_active():
    """PRD §3.3: "**Reinstatement** reverses the enrollment axis, moving the
    participant `TERMINATED → ACTIVE` and clearing `termination_effective_date` back
    to null."
    PRD §3.3: "Reinstatement is **not compensating**: the appointments the
    termination cancelled stay cancelled, the site and contract counters keep their
    post-cancellation values, and forfeited awards stay forfeited."

    Design: Corner/state_machines/participant_reinstated_inside_grace_window_returns_to_active
    """
    world = setup_clinic(
        employer={"legal_name": "Reinstate Co", "employer_code": "RNS"},
        site={"site_name": "RNS Clinic"},
        eligibility={"subscriber_external_id": "S-3801", "member_external_id": "M-3801"},
        participant={"display_name": "Rein Tester"},
    )
    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )

    validate_success(
        api_client.terminate_participant(
            world.participant_id,
            {"termination_effective_date": "2026-06-01"},
            world.employer_headers,
        )
    )
    reinstated = validate_success(
        api_client.reinstate_participant(world.participant_id, world.employer_headers)
    )

    assert reinstated["enrollment_status"] == "ACTIVE"
    assert reinstated["termination_effective_date"] is None

    after = validate_success(
        api_client.get_appointment(appointment["id"], world.participant_headers)
    )
    assert after["status"] == "CANCELLED", "reinstatement never restores an appointment"
    assert after["cancellation_reason"] == "ENROLLMENT_TERMINATED"

    site = read_site(world.site_id)
    assert site["slots_released_count"] == 1
    assert site["slots_held_count"] == 0
    contract = validate_success(
        api_client.get_vendor_contract(world.contract_id, ADMIN)
    )
    assert contract["quota_visits_remaining"] == 10
    assert_contract_quota_conservation(contract)


def test_clock_closes_enrollment_after_grace_window_and_withdraws_authorization():
    """PRD §3.3: "When a clock advance finds a `TERMINATED` participant whose
    `termination_effective_date` plus thirty days falls strictly before the new clock
    date, the participant moves `TERMINATED → CLOSED` and reinstatement is no longer
    possible. That closure is the one place the enrollment axis reaches the
    authorization axis: whatever `authorization_status` the participant held —
    `NOT_REQUESTED`, `GRANTED` or `REVOKED` — it becomes `WITHDRAWN`, and no further
    authorization decision is accepted from that participant."
    PRD §3.3: "A reinstatement outside that window finds no available transition and
    is refused with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/participant_closes_after_grace_window_and_authorization_is_withdrawn
    """
    world = setup_clinic(
        employer={"legal_name": "Grace Co", "employer_code": "GRC"},
        contract=False,
        shift=False,
        eligibility={"subscriber_external_id": "S-3901", "member_external_id": "M-3901"},
        participant={"display_name": "Grace Tester"},
    )
    grant_authorization(world.participant_id)
    validate_success(
        api_client.terminate_participant(
            world.participant_id,
            {"termination_effective_date": "2026-06-01"},
            world.employer_headers,
        )
    )

    set_clock("2026-07-01T00:00:00Z")
    on_boundary = validate_success(
        api_client.get_participant(world.participant_id, world.employer_headers)
    )
    assert on_boundary["enrollment_status"] == "TERMINATED", (
        "exactly thirty days after the effective date is still inside the window"
    )

    sweep = set_clock("2026-07-02T00:00:00Z")
    assert world.participant_id in sweep["closed_participant_ids"]

    closed = validate_success(
        api_client.get_participant(world.participant_id, world.employer_headers)
    )
    assert closed["enrollment_status"] == "CLOSED"
    assert closed["authorization_status"] == "WITHDRAWN"

    validate_error(
        api_client.reinstate_participant(world.participant_id, world.employer_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )


def test_termination_cancels_booked_appointment_and_releases_site_and_quota():
    """PRD §3.3: "Down the scheduling branch, every appointment of this participant
    standing at `BOOKED` moves to `CANCELLED` with a `cancellation_reason` of
    `ENROLLMENT_TERMINATED`. Each of those cancellations reaches the appointment's
    site, which recomputes `slots_held_count` and `slots_released_count` and advances
    its own `version` by one. Each cancellation then reaches the vendor contract the
    appointment had been pinned to, which recomputes `quota_visits_consumed`,
    `quota_visits_released` and `quota_visits_remaining` — the released quota returns
    to the employer."

    Design: Difficulty/transitive_cascade/participant_termination_cascades_to_slots_quota_and_forfeited_money
    """
    world = setup_clinic(
        employer={"legal_name": "Termination Co", "employer_code": "TRM"},
        site={"site_name": "TRM On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1101", "member_external_id": "M-1101"},
        participant={"display_name": "Ira Bloom"},
        reporting_period={},
    )
    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )

    terminated = validate_success(
        api_client.terminate_participant(
            world.participant_id,
            {"termination_effective_date": "2026-06-01"},
            world.employer_headers,
        )
    )
    assert terminated["enrollment_status"] == "TERMINATED"
    assert_same_date(terminated["termination_effective_date"], "2026-06-01")

    cancelled = validate_success(
        api_client.get_appointment(appointment["id"], world.participant_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "ENROLLMENT_TERMINATED"

    site = read_site(world.site_id)
    assert site["slots_held_count"] == 0
    assert site["slots_released_count"] == 1
    assert site["slots_requested_total"] == 1
    assert_site_slot_conservation(site)

    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["quota_visits_consumed"] == 0
    assert contract["quota_visits_released"] == 1
    assert contract["quota_visits_remaining"] == 20
    assert_contract_quota_conservation(contract)


def test_termination_forfeits_pending_award_and_releases_employer_commitment():
    """PRD §3.3: "Down the money branch, every incentive award of this participant
    standing at `PENDING` moves to `FORFEITED`."
    PRD §3.3: "Each forfeiture reaches the award's reporting period, which recomputes
    `incentive_pending_cents` and `incentive_forfeited_cents` while
    `incentive_awarded_cents` stays put, and the period in turn reaches the employer,
    which recomputes `wellness_budget_committed_cents` and
    `wellness_budget_remaining_cents` because forfeited money is no longer committed."

    Design: Difficulty/transitive_cascade/participant_termination_cascades_to_slots_quota_and_forfeited_money
    """
    world = setup_clinic(
        employer={
            "legal_name": "Termination Co",
            "employer_code": "TRM",
            "wellness_budget_cents": 500000,
        },
        site={"site_name": "TRM On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1101", "member_external_id": "M-1101"},
        participant={"display_name": "Ira Bloom"},
        reporting_period={},
    )
    award = new_award(
        world.participant_id,
        world.employer_id,
        world.period_id,
        award_type="PARTICIPATORY",
    )
    assert award["award_amount_cents"] == 15000

    validate_success(
        api_client.terminate_participant(
            world.participant_id,
            {"termination_effective_date": "2026-06-01"},
            world.employer_headers,
        )
    )

    forfeited = validate_success(
        api_client.get_incentive_award(award["id"], world.employer_headers)
    )
    assert forfeited["status"] == "FORFEITED"

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 15000
    assert period["incentive_pending_cents"] == 0
    assert period["incentive_forfeited_cents"] == 15000
    assert_period_money_conservation(period)

    employer = validate_success(
        api_client.get_employer(world.employer_id, world.employer_headers)
    )
    assert employer["wellness_budget_committed_cents"] == 0
    assert employer["wellness_budget_remaining_cents"] == 500000
