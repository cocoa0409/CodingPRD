"""Entity surface: envelopes, minted identity, declared defaults and input constraints."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    T02_ADULT_CLEAN,
    api_client,
    assert_applicant,
    assert_application,
    assert_assignment,
    assert_carrier,
    assert_market_rejection,
    assert_ordered_by_created_at,
    assert_pagination_meta,
    assert_plan_period,
    assert_producer,
    bootstrap_plan,
    bring_application_to_certified,
    create_applicant_payload,
    create_applicant_with_vehicle,
    create_application_payload,
    create_carrier_payload,
    create_plan_period_payload,
    create_producer_payload,
    create_vehicle,
    create_vehicle_payload,
    file_two_market_rejections,
    is_iso8601_timestamp,
    make_compliance_examiner_headers,
    make_plan_administrator_headers,
    make_producer_agent_headers,
    read_applicant,
    read_application,
    record_deposit,
    register_producer,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verify_mvr,
)

ADMIN_HEADERS = make_plan_administrator_headers()
EXAMINER_HEADERS = make_compliance_examiner_headers()

CLOCK = "2026-09-01T00:00:00Z"

# A syntactically well-formed UUID that matches no row of any entity type.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

ATLAS_TWO_TERRITORIES = {
    "name": "Atlas Mutual",
    "naic_code": "11111",
    "voluntary_market_share_bps": 6000,
    "licensed_territories": ["T01", "T02"],
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so instants compare regardless of formatting."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rows_and_meta(response, expected_total=None):
    """Validate a list response as an array envelope and return ``(rows, meta)``."""
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", (
        "a list endpoint must declare response_type 'array', got "
        f"{response.json().get('response_type')!r}"
    )
    assert_pagination_meta(meta, expected_total=expected_total)
    return rows, meta


# --------------------------------------------------------------------------
# Carrier enrolment
# --------------------------------------------------------------------------
def test_carrier_enrolment_echoes_the_payload_inside_the_success_envelope():
    """A creation answers 201 and returns the new row inside the standard envelope.

    The first write against an empty database carries the four declared inputs
    back unchanged — and inside ``data``, never at the top level — alongside the
    request-scoped metadata every successful response reports.

    PRD: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    Design: Corner/entities/carrier_enrolment_returns_envelope_with_system_and_computed_defaults
    """
    set_clock(CLOCK)

    response = api_client.create_carrier(
        create_carrier_payload(**ATLAS_TWO_TERRITORIES), ADMIN_HEADERS)

    carrier = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert carrier["name"] == "Atlas Mutual"
    assert carrier["naic_code"] == "11111"
    assert carrier["voluntary_market_share_bps"] == 6000
    assert carrier["licensed_territories"] == ["T01", "T02"]
    assert_carrier(carrier)


def test_a_newly_enrolled_carrier_starts_with_every_derived_field_server_minted():
    """Standing, the enrolment ordinal and every counter are minted by the plan.

    Nothing in the payload speaks to standing, so the carrier opens ACTIVE with a
    perfect score and an OPEN posture, takes the first enrolment ordinal, and
    reports each derived counter at zero: no assignment has been made, no
    voluntary credit earned and no reconciliation penalty levied, so the variance
    is zero and the carrier is not overallocated.

    PRD: "A newly enrolled carrier starts with `status` `ACTIVE`,
    `performance_score` 100 and `posture` `OPEN`, receives the next
    `enrollment_sequence`"
    Design: Corner/entities/carrier_enrolment_returns_envelope_with_system_and_computed_defaults
    """
    set_clock(CLOCK)

    carrier = validate_success(
        api_client.create_carrier(create_carrier_payload(**ATLAS_TWO_TERRITORIES),
                                  ADMIN_HEADERS), 201)

    assert carrier["enrollment_sequence"] == 1
    assert carrier["status"] == "ACTIVE"
    assert carrier["performance_score"] == 100
    assert carrier["posture"] == "OPEN"
    assert carrier["assigned_risk_count"] == 0
    assert carrier["voluntary_credit_units"] == 0
    assert carrier["penalty_balance_cents"] == 0
    assert carrier["quota_target_units"] == 0
    assert carrier["quota_variance_units"] == 0
    assert carrier["overallocated"] is False
    assert carrier["version"] == 1


# --------------------------------------------------------------------------
# Applicant read
# --------------------------------------------------------------------------
def test_an_applicant_read_returns_the_stored_inputs_and_the_initialised_event_date():
    """The read echoes what was stored and seeds the chargeable-event clock.

    An applicant with no applications, no verified violations and no claims has no
    chargeable event at all, so the plan seeds ``last_chargeable_event_date`` from
    the first licensing date, and the voluntary-market flag stays false because no
    policy of this applicant has left the plan.

    PRD: "At creation, the applicant's `last_chargeable_event_date` is initialised
    to `first_licensed_date` and `clean_years_credited` is computed against the
    clock; `voluntary_market_eligible` starts false and turns true only when a
    policy of this applicant leaves the plan for the voluntary market."
    Design: Corner/entities/applicant_read_returns_stored_input_plus_derived_clean_years
    """
    set_clock(CLOCK)
    created = validate_success(
        api_client.create_applicant(create_applicant_payload(), ADMIN_HEADERS), 201)

    applicant = validate_success(api_client.get_applicant(created["id"], EXAMINER_HEADERS))

    assert applicant["full_name"] == "Owen Pike"
    assert applicant["driver_license_number"] == "D-99011"
    assert applicant["territory_code"] == "T02"
    assert applicant["driver_class"] == "ADULT"
    assert _instant(applicant["first_licensed_date"]) == _instant("2010-06-01T00:00:00Z")
    assert _instant(applicant["last_chargeable_event_date"]) == \
        _instant(applicant["first_licensed_date"])
    assert applicant["voluntary_market_eligible"] is False
    assert_applicant(applicant)


def test_clean_years_credited_is_capped_at_five_however_long_the_record_is_clean():
    """Sixteen years of clean driving still credit only five clean years.

    First licensed on 2010-06-01 and read at a clock of 2026-09-01, the applicant
    has more than sixteen whole 365-day years without a chargeable event, but the
    credited figure is the lesser of 5 and that count.

    PRD: "`clean_years_credited` is then the lesser of 5 and the number of whole
    365-day years between `last_chargeable_event_date` and the current clock,
    computed by taking the whole days elapsed, dividing by 365, and truncating
    downward."
    Design: Corner/entities/applicant_read_returns_stored_input_plus_derived_clean_years
    """
    set_clock(CLOCK)
    created = validate_success(
        api_client.create_applicant(create_applicant_payload(), ADMIN_HEADERS), 201)

    applicant = validate_success(api_client.get_applicant(created["id"], EXAMINER_HEADERS))

    assert applicant["clean_years_credited"] == 5
    assert applicant["clean_years_credited"] != 16


# --------------------------------------------------------------------------
# Application listing and pagination
# --------------------------------------------------------------------------
APPLICANT_SPECS = [
    ("Owen Pike", "D-99011", "1HGCM82633A004360"),
    ("Nadia Frost", "D-99012", "1HGCM82633A004361"),
    ("Iris Bell", "D-99013", "1HGCM82633A004362"),
]


def _three_submitted_applications():
    """Three applications for one producer, submitted in a known order."""
    env = bootstrap_plan(clock=CLOCK)
    producer_id = env["producer"]["id"]
    applications = []
    for index, (full_name, licence, vin) in enumerate(APPLICANT_SPECS, start=1):
        applicant, vehicle = create_applicant_with_vehicle(
            {"full_name": full_name, "driver_license_number": licence},
            {"vin": vin},
        )
        application = submit_application(producer_id, applicant["id"], vehicle["id"])
        file_two_market_rejections(application["id"], producer_id,
                                   document_prefix=f"DEC-3{index}")
        verify_mvr(application["id"], [])
        record_deposit(application["id"], producer_id,
                       T02_ADULT_CLEAN["required_deposit_cents"])
        applications.append(read_application(application["id"]))
    return env, applications


def test_application_pages_report_the_filtered_total_and_flag_the_remaining_rows():
    """Three applications read two at a time report the whole set, not the page.

    The first page of two rows reports a total of three and more rows to come; the
    second page returns the single remaining row, reports the same total and flags
    that nothing remains beyond it.

    PRD: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates
    whether rows remain beyond the current page."
    Design: Corner/entities/application_listing_pages_with_total_count_and_has_more
    """
    env, applications = _three_submitted_applications()
    params = {"producer_id": env["producer"]["id"], "limit": 2}

    first_page = api_client.list_applications(ADMIN_HEADERS, params=dict(params, offset=0))
    second_page = api_client.list_applications(ADMIN_HEADERS, params=dict(params, offset=2))

    first_rows, first_meta = _rows_and_meta(first_page, expected_total=3)
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    second_rows, second_meta = _rows_and_meta(second_page, expected_total=3)
    assert len(second_rows) == 1
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False
    assert second_rows[0]["id"] == applications[2]["id"]


def test_application_rows_arrive_in_intake_sequence_order_rather_than_by_id():
    """The gap-free intake ordinal is the order the plan lists applications in.

    The three applications took intake ordinals 1, 2 and 3 in submission order, and
    the first page returns them in exactly that order.

    PRD: "assignment lists break ties on `batch_sequence` ascending, application
    lists on `intake_sequence` ascending, and carrier lists on
    `enrollment_sequence` ascending."
    Design: Corner/entities/application_listing_pages_with_total_count_and_has_more
    """
    env, applications = _three_submitted_applications()
    assert [row["intake_sequence"] for row in applications] == [1, 2, 3]

    rows, _ = _rows_and_meta(
        api_client.list_applications(ADMIN_HEADERS,
                                     params={"producer_id": env["producer"]["id"],
                                             "limit": 2, "offset": 0}),
        expected_total=3)

    assert [row["id"] for row in rows] == [applications[0]["id"], applications[1]["id"]]
    assert [row["intake_sequence"] for row in rows] == [1, 2]
    assert_ordered_by_created_at(rows, tie_break_field="intake_sequence")
    for row in rows:
        assert_application(row)


# --------------------------------------------------------------------------
# Entity-scoped not-found errors
# --------------------------------------------------------------------------
def test_every_unknown_identifier_names_the_entity_it_failed_to_resolve():
    """A well-formed but unknown UUID yields that entity's own 404, never a generic one.

    Against an empty database each read of a well-formed identifier fails on its own
    axis, so eleven top-level endpoints return eleven different entity-scoped
    not-found identifiers, each with HTTP 404 and each inside the error envelope.

    PRD: "The first identifier that fails to resolve determines the error: an
    unresolvable carrier yields `ERR_CARRIER_NOT_FOUND`, a producer
    `ERR_PRODUCER_NOT_FOUND`, an applicant `ERR_APPLICANT_NOT_FOUND`"
    Design: Corner/entities/unknown_identifiers_return_entity_scoped_not_found_errors
    """
    set_clock(CLOCK)

    attempts = [
        (api_client.get_carrier(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_CARRIER_NOT_FOUND),
        (api_client.get_producer(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_PRODUCER_NOT_FOUND),
        (api_client.get_applicant(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_APPLICANT_NOT_FOUND),
        (api_client.get_application(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api_client.get_plan_period(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_PLAN_PERIOD_NOT_FOUND),
        (api_client.run_assignment_cycle(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_ASSIGNMENT_CYCLE_NOT_FOUND),
        (api_client.get_assignment(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api_client.get_policy(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_POLICY_NOT_FOUND),
        (api_client.get_claim(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api_client.get_complaint(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api_client.get_quota_reconciliation(UNKNOWN_UUID, ADMIN_HEADERS),
         ApiErrorId.ERR_QUOTA_RECONCILIATION_NOT_FOUND),
    ]

    for response, expected in attempts:
        error = validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"]


def test_a_nested_write_resolves_the_parent_path_before_the_vehicle_body():
    """Adding a vehicle under an unknown applicant is an applicant miss.

    The payload describes a perfectly valid vehicle, but the parent identifier in
    the path is resolved first, so the refusal names the applicant rather than
    anything about the vehicle.

    PRD: "Path identifiers are resolved strictly left to right, and only after
    path resolution succeeds does the server resolve identifiers carried in the
    request body, again left to right in the order the fields are listed for that
    endpoint."
    Design: Corner/entities/unknown_identifiers_return_entity_scoped_not_found_errors
    """
    set_clock(CLOCK)

    response = api_client.create_vehicle(
        UNKNOWN_UUID, create_vehicle_payload(vin="1HGCM82633A004399"), ADMIN_HEADERS)

    error = validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.ERR_VEHICLE_NOT_FOUND


# --------------------------------------------------------------------------
# Required input fields
# --------------------------------------------------------------------------
def test_an_application_missing_a_declared_input_field_is_a_request_shape_failure():
    """A payload short of any of the five declared inputs is refused at 422.

    The applicant, the producer and the vehicle all exist and agree with each
    other, so nothing but the shape of the request is wrong: dropping
    ``applicant_id`` and, separately, dropping ``requested_effective_date`` are
    both refused before existence or business rules are reached, and neither
    attempt leaves an application row behind.

    PRD: "required body fields present, enum values in range, integers
    non-negative where required, timestamps well-formed ISO 8601, `limit` within 1
    through 100 and `offset` not negative: `ERR_INVALID_REQUEST`, 422."
    Design: Corner/entities/application_creation_rejects_a_payload_missing_any_declared_input_field
    """
    set_clock(CLOCK)
    producer = register_producer()
    applicant, vehicle = create_applicant_with_vehicle()
    producer_headers = make_producer_agent_headers(producer["id"])

    without_applicant = create_application_payload(applicant["id"], producer["id"], vehicle["id"])
    without_applicant.pop("applicant_id")
    without_date = create_application_payload(applicant["id"], producer["id"], vehicle["id"])
    without_date.pop("requested_effective_date")

    validate_error(api_client.create_application(without_applicant, producer_headers),
                   ApiErrorId.ERR_INVALID_REQUEST, 422)
    validate_error(api_client.create_application(without_date, producer_headers),
                   ApiErrorId.ERR_INVALID_REQUEST, 422)

    _rows_and_meta(api_client.list_applications(ADMIN_HEADERS,
                                                params={"producer_id": producer["id"]}),
                   expected_total=0)
    assert read_applicant(applicant["id"])["version"] == applicant["version"]


# --------------------------------------------------------------------------
# Declared defaults for omitted optional inputs
# --------------------------------------------------------------------------
def test_a_period_opened_without_underserved_territories_starts_open_and_at_zero():
    """The only optional period input defaults to an empty territory list.

    Opening a period without naming any underserved territory gives an empty list,
    so no territory earns enhanced voluntary credit this period, and the period
    opens with both frozen totals at zero rather than null: no application has been
    certified into it and no policy has earned exposure against it.

    PRD: "A new period starts with `status` `OPEN` and `total_assignable_units` at
    zero"
    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    set_clock(CLOCK)
    payload = create_plan_period_payload()
    payload.pop("underserved_territories")

    response = api_client.create_plan_period(payload, ADMIN_HEADERS)

    period = validate_success(response, 201)
    assert period["underserved_territories"] == []
    assert period["status"] == "OPEN"
    assert period["total_assignable_units"] == 0
    assert period["total_assignable_car_years"] == 0
    assert period["version"] == 1
    assert_plan_period(period)


def test_a_producer_registered_without_an_explicit_status_may_transact():
    """Status is optional on registration, and the omitted default can transact.

    The producer is registered with only its name, licence number and appointed
    territories, and it immediately submits an application successfully — which the
    plan permits only for an ACTIVE producer, the status the row reports.

    PRD: "a producer whose `status` is `ACTIVE` may transact, while one whose
    `status` is `SUSPENDED` may neither submit nor resubmit an application."
    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    set_clock(CLOCK)
    payload = create_producer_payload()
    assert "status" not in payload

    response = api_client.create_producer(payload, ADMIN_HEADERS)

    producer = validate_success(response, 201)
    assert producer["status"] == "ACTIVE"
    assert producer["version"] == 1
    assert_producer(producer)
    applicant, vehicle = create_applicant_with_vehicle()
    application = validate_success(
        api_client.create_application(
            create_application_payload(applicant["id"], producer["id"], vehicle["id"]),
            make_producer_agent_headers(producer["id"])), 201)
    assert application["status"] == "SUBMITTED"


# --------------------------------------------------------------------------
# Computed estimate fields on an application
# --------------------------------------------------------------------------
def _submitted_adult_pleasure_risk_in_t02():
    """One SUBMITTED ADULT/PLEASURE T02 application with two declinations and no money."""
    env = bootstrap_plan(clock=CLOCK)
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_two_market_rejections(application["id"], env["producer"]["id"],
                               document_prefix="DEC-33")
    return env, read_application(application["id"])


def test_the_application_estimate_is_computed_server_side_from_the_declared_record():
    """The client sends no money and the plan prices the risk anyway.

    An ADULT applicant in T02 with a PLEASURE vehicle garaged in T02 and an empty
    violation list rates at zero surcharge points, so the T02 territory base of
    148337 cents carries a 0.05 expense charge of 7417 cents for an estimated term
    charge of 155754 — every figure derived, none supplied.

    PRD: "On success the application lands in `SUBMITTED`, receives the next
    `intake_sequence`, and is immediately priced: `surcharge_points_estimated`,
    `estimated_annual_premium_cents`, `estimated_expense_charge_cents`,
    `estimated_total_charge_cents` and `required_deposit_cents` are all derived
    from the declared record at a rating date equal to the current clock."
    Design: Corner/entities/application_estimate_and_required_deposit_are_computed_not_supplied
    """
    _, application = _submitted_adult_pleasure_risk_in_t02()

    assert application["status"] == "SUBMITTED"
    assert application["intake_sequence"] == 1
    assert application["surcharge_points_estimated"] == 0
    assert application["estimated_annual_premium_cents"] == 148337
    assert application["estimated_expense_charge_cents"] == 7417
    assert application["estimated_total_charge_cents"] == 155754
    assert_application(application)


def test_the_required_deposit_is_a_quarter_of_the_estimate_rounded_half_up():
    """One quarter of 155754 is 38938.5, which rounds half up to 38939.

    The quarter share lands on an exact half cent, so the plan rounds it up rather
    than down or to even, and the result sits well above the fifteen-thousand-cent
    floor, which therefore does not bind.

    PRD: "How much the plan requires before it will certify the risk is
    `required_deposit_cents`: one quarter of `estimated_total_charge_cents`,
    rounded half up to whole cents, but never less than a fifteen-thousand-cent
    floor"
    Design: Corner/entities/application_estimate_and_required_deposit_are_computed_not_supplied
    """
    _, application = _submitted_adult_pleasure_risk_in_t02()

    assert application["required_deposit_cents"] == 38939
    assert application["required_deposit_cents"] != 38938
    assert application["required_deposit_cents"] == T02_ADULT_CLEAN["required_deposit_cents"]
    assert application["required_deposit_cents"] > 15000


def test_an_application_reports_null_verification_fields_until_the_record_is_pulled():
    """Before the motor-vehicle-record pull both verification fields are null.

    The application has been submitted and documented but no examiner has pulled
    the record, so the verified array and its timestamp are both null and the
    estimate above was rated from the declared record instead.

    PRD: "Until the pull happens, `verified_violations` is null and
    `mvr_verified_at` is null."
    Design: Corner/entities/application_estimate_and_required_deposit_are_computed_not_supplied
    """
    _, application = _submitted_adult_pleasure_risk_in_t02()

    assert application["mvr_verified_at"] is None
    assert application["verified_violations"] is None
    assert application["cure_count"] == 0


# --------------------------------------------------------------------------
# Assignment identity minted by the selector
# --------------------------------------------------------------------------
def _one_placed_risk():
    """Certify one T02 risk and run one cycle, returning the single assignment."""
    env = bootstrap_plan(clock=CLOCK)
    risk = bring_application_to_certified(env, document_prefix="DEC-34")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    response = api_client.list_assignments(
        ADMIN_HEADERS, params={"application_id": risk["application"]["id"]})
    rows, _ = _rows_and_meta(response, expected_total=1)
    return env, risk, cycle, rows[0]


def test_the_selector_mints_every_reference_on_the_assignment_row():
    """No field of an assignment comes from a client; the run writes them all.

    The run places the single certified risk with the larger-share carrier and
    writes the risk, the designated carrier and the originating cycle onto the row
    itself. Because this is a first-time placement rather than a transfer, the row
    is an INITIAL assignment with no predecessor, awaiting the carrier's
    acceptance and carrying the first creation ordinal of the run.

    PRD: "The row records the risk through its `application_id` and the designated
    servicing carrier through its `carrier_id`; both are written by the selector
    and are never accepted from a client. It records the run that produced it
    through `assignment_cycle_id`, its `assignment_kind` is `INITIAL`, and its
    `predecessor_assignment_id` is null."
    Design: Corner/entities/assignment_identity_fields_are_minted_by_the_selector
    """
    env, risk, cycle, assignment = _one_placed_risk()

    assert assignment["application_id"] == risk["application"]["id"]
    assert assignment["carrier_id"] == env["carriers"][0]["id"]
    assert assignment["assignment_cycle_id"] == cycle["id"]
    assert assignment["predecessor_assignment_id"] is None
    assert assignment["assignment_kind"] == "INITIAL"
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    assert assignment["batch_sequence"] == 1
    assert assignment["accepted_at"] is None
    assert assignment["version"] == 1
    assert_assignment(assignment)


def test_the_acceptance_deadline_is_ten_days_after_the_assignment_was_created():
    """The window the carrier has to accept is measured from the row's own birth.

    The deadline is not supplied and not derived from the cycle window: it is
    exactly ten days past the instant the assignment row was inserted.

    PRD: "Its `acceptance_deadline` is ten days after the assignment's
    `created_at`."
    Design: Corner/entities/assignment_identity_fields_are_minted_by_the_selector
    """
    _, _, _, assignment = _one_placed_risk()

    assert is_iso8601_timestamp(assignment["acceptance_deadline"])
    assert _instant(assignment["acceptance_deadline"]) == \
        _instant(assignment["created_at"]) + timedelta(days=10)


def test_the_assignment_snapshots_the_winning_deficit_and_the_estimated_term_charge():
    """The row preserves both the ranking input and the money as they stood.

    Atlas holds 6000 of the 10000 basis points in the market, so a single
    assignable unit apportions entirely to it: its target of 1 against a headcount
    of 0 is a deficit of 1.0, recorded as the audit trail of the ranking. The
    premium snapshot is the application's estimated term charge of 155754 cents.

    PRD: "its `provisional_premium_cents` snapshots the application's
    `estimated_total_charge_cents` as it stood at selection."
    Design: Corner/entities/assignment_identity_fields_are_minted_by_the_selector
    """
    _, risk, _, assignment = _one_placed_risk()

    assert risk["application"]["estimated_total_charge_cents"] == 155754
    assert assignment["provisional_premium_cents"] == 155754
    assert assignment["deficit_score_at_selection"] == 1.0


# --------------------------------------------------------------------------
# Market rejections are immutable documents
# --------------------------------------------------------------------------
def _application_with_two_declinations():
    """One SUBMITTED application carrying two documented declinations."""
    env = bootstrap_plan(clock=CLOCK)
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_two_market_rejections(application["id"], env["producer"]["id"],
                               document_prefix="DEC-35")
    return env, application


def test_a_filed_declination_carries_no_version_and_no_updated_at():
    """A declination is evidence, so it has no mutable audit fields at all.

    Both filings expose the document they evidence — the application they belong
    to, the declining carrier's NAIC code, the date, the reason and the plan
    document control number — alongside an identifier and a creation timestamp, and
    nothing else the plan could later revise.

    PRD: "A `MarketRejection` is an immutable evidentiary filing: it carries only
    `id` and `created_at`. It has no `updated_at` field and no `version` field at
    all."
    Design: Corner/entities/market_rejection_rows_are_immutable_documents
    """
    _, application = _application_with_two_declinations()

    rows, _ = _rows_and_meta(
        api_client.list_market_rejections(application["id"], EXAMINER_HEADERS),
        expected_total=2)

    assert len(rows) == 2
    for row in rows:
        assert row["application_id"] == application["id"]
        assert "updated_at" not in row
        assert "version" not in row
        assert_market_rejection(row)


def test_declinations_are_listed_under_their_application_in_filing_order():
    """The evidentiary trail reads in the order the filings were made.

    The NAIC 11111 declination was filed first and the NAIC 22222 declination
    second, and the collection returns them in that order rather than by
    identifier.

    PRD: "Unless a subsection below states otherwise, list results are ordered by
    `created_at` ascending."
    Design: Corner/entities/market_rejection_rows_are_immutable_documents
    """
    _, application = _application_with_two_declinations()

    rows, _ = _rows_and_meta(
        api_client.list_market_rejections(application["id"], EXAMINER_HEADERS),
        expected_total=2)

    assert [row["rejecting_carrier_naic_code"] for row in rows] == ["11111", "22222"]
    assert [row["reason_code"] for row in rows] == [
        "UNACCEPTABLE_DRIVING_RECORD", "UNDERWRITING_GUIDELINES"]
    assert_ordered_by_created_at(rows)


def test_each_filed_declination_refreshes_the_distinct_rejection_count():
    """Two distinct NAIC codes inside the lookback window count as two.

    Both filings are dated inside the ninety-day window ending at the clock and
    come from different voluntary-market carriers, so the application's count of
    documented declinations stands at two.

    PRD: "Each accepted declination refreshes the application's
    `distinct_rejection_count`. That figure is the number of distinct
    `rejecting_carrier_naic_code` values among the application's declinations whose
    `rejection_date` falls inside a ninety-day lookback window ending at the current
    clock"
    Design: Corner/entities/market_rejection_rows_are_immutable_documents
    """
    _, application = _application_with_two_declinations()

    refreshed = read_application(application["id"])

    assert refreshed["distinct_rejection_count"] == 2


# --------------------------------------------------------------------------
# Cross-entity foreign keys
# --------------------------------------------------------------------------
def _two_applicants_each_owning_one_vehicle():
    """Owen Pike owns VIN ...4360 and Nadia Frost owns VIN ...4361."""
    set_clock(CLOCK)
    producer = register_producer()
    owen, owen_vehicle = create_applicant_with_vehicle()
    nadia = validate_success(
        api_client.create_applicant(
            create_applicant_payload(full_name="Nadia Frost",
                                     driver_license_number="D-99012",
                                     first_licensed_date="2011-06-01T00:00:00Z"),
            ADMIN_HEADERS), 201)
    nadia_vehicle = create_vehicle(nadia["id"], vin="1HGCM82633A004361", model_year=2020)
    return producer, owen, owen_vehicle, nadia, nadia_vehicle


def test_a_vehicle_owned_by_another_applicant_is_a_referential_integrity_failure():
    """The vehicle exists, but it is not this applicant's vehicle.

    Owen Pike's application names Nadia Frost's vehicle. Both rows resolve
    perfectly, so this is not an existence failure but a disagreement between two
    of the application's three independent foreign keys, and no application row is
    written.

    PRD: "The vehicle must belong to the applicant named in the same payload, or
    the request is refused with `ERR_VEHICLE_APPLICANT_MISMATCH` and HTTP 422."
    Design: Corner/entities/cross_entity_foreign_keys_are_validated_not_trusted
    """
    producer, owen, _, nadia, nadia_vehicle = _two_applicants_each_owning_one_vehicle()

    response = api_client.create_application(
        create_application_payload(owen["id"], producer["id"], nadia_vehicle["id"]),
        make_producer_agent_headers(producer["id"]))

    validate_error(response, ApiErrorId.ERR_VEHICLE_APPLICANT_MISMATCH, 422)
    _rows_and_meta(api_client.list_applications(ADMIN_HEADERS,
                                                params={"applicant_id": owen["id"]}),
                   expected_total=0)
    assert nadia_vehicle["applicant_id"] == nadia["id"]


def test_an_unresolvable_producer_outranks_the_vehicle_mismatch():
    """Two things are wrong and the plan reports the existence failure.

    The same mismatched vehicle is submitted with a producer identifier that
    resolves to nothing. Existence is checked before cross-row agreement, so the
    refusal names the missing producer and never mentions the vehicle.

    PRD: "every identifier in the path and then every identifier in the body
    resolves, left to right: the matching not-found error, 404."
    Design: Corner/entities/cross_entity_foreign_keys_are_validated_not_trusted
    """
    producer, owen, _, _, nadia_vehicle = _two_applicants_each_owning_one_vehicle()

    response = api_client.create_application(
        create_application_payload(owen["id"], UNKNOWN_UUID, nadia_vehicle["id"]),
        make_producer_agent_headers(producer["id"]))

    error = validate_error(response, ApiErrorId.ERR_PRODUCER_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.ERR_VEHICLE_APPLICANT_MISMATCH


# --------------------------------------------------------------------------
# Type, range and pagination constraints
# --------------------------------------------------------------------------
def test_out_of_vocabulary_enum_values_and_an_oversized_limit_are_all_refused():
    """An unknown territory, an unknown driver class and limit 101 share one error.

    None of these requests can be repaired by looking at any other row: a
    territory code outside the three the plan recognises, a driver class outside
    the three it approves and a page size above the declared maximum are all
    request-shape failures, while the largest accepted page size is served
    normally.

    PRD: "required body fields present, enum values in range, integers
    non-negative where required, timestamps well-formed ISO 8601, `limit` within 1
    through 100 and `offset` not negative: `ERR_INVALID_REQUEST`, 422."
    Design: Corner/entities/enum_range_and_pagination_constraints_are_enforced
    """
    set_clock(CLOCK)

    bad_territory = api_client.create_carrier(
        create_carrier_payload(name="Bad Territory Mutual", naic_code="44444",
                               licensed_territories=["T09"]), ADMIN_HEADERS)
    bad_class = api_client.create_applicant(
        create_applicant_payload(full_name="Teen Driver", driver_license_number="D-99099",
                                 driver_class="TEEN",
                                 first_licensed_date="2024-06-01T00:00:00Z"), ADMIN_HEADERS)
    oversized_page = api_client.list_carriers(ADMIN_HEADERS, params={"limit": 101, "offset": 0})

    validate_error(bad_territory, ApiErrorId.ERR_INVALID_REQUEST, 422)
    validate_error(bad_class, ApiErrorId.ERR_INVALID_REQUEST, 422)
    validate_error(oversized_page, ApiErrorId.ERR_INVALID_REQUEST, 422)
    _rows_and_meta(api_client.list_carriers(ADMIN_HEADERS, params={"limit": 100, "offset": 0}),
                   expected_total=0)


def test_a_market_share_above_ten_thousand_basis_points_is_refused():
    """The share is a bounded integer, and 10001 basis points is out of range.

    A share above the whole market cannot be apportioned against, so the enrolment
    is refused on the shape of the request and no carrier row is written.

    PRD: "its five-digit `naic_code`, its `voluntary_market_share_bps` between 1
    and 10000, and the `licensed_territories` it may write."
    Design: Corner/entities/enum_range_and_pagination_constraints_are_enforced
    """
    set_clock(CLOCK)

    response = api_client.create_carrier(
        create_carrier_payload(name="Bad Share Mutual", naic_code="44445",
                               voluntary_market_share_bps=10001), ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)
    _rows_and_meta(api_client.list_carriers(ADMIN_HEADERS), expected_total=0)


def test_a_period_whose_window_end_precedes_its_window_start_is_refused():
    """An inverted window is not a conflict but a malformed request.

    No period exists to conflict with, so the only thing wrong is the window
    itself: its end falls nearly three months before its start.

    PRD: "an inclusive `window_start` and an inclusive `window_end` that must be
    no earlier than the start"
    Design: Corner/entities/enum_range_and_pagination_constraints_are_enforced
    """
    set_clock(CLOCK)

    response = api_client.create_plan_period(
        create_plan_period_payload(period_code="2026-BAD",
                                   window_start="2026-11-30T00:00:00Z",
                                   window_end="2026-09-01T00:00:00Z",
                                   underserved_territories=[]), ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)


# --------------------------------------------------------------------------
# Reverse reachability from every declared parent
# --------------------------------------------------------------------------
def test_every_parented_collection_is_reachable_through_its_parent_path():
    """A vehicle, a declination and a cycle are each listed under their own parent.

    One in-force policy implies a whole chain of parented rows, and each child
    collection is addressed under its parent and returns only that parent's
    children: one vehicle under the applicant, two declinations under the
    application and one cycle under the period.

    PRD: "Note that a nested child is addressed under its parent but is not
    filtered by it beyond resolution: listing an applicant's vehicles returns only
    that applicant's vehicles, and listing an application's market rejections only
    that application's filings."
    Design: Corner/entities/child_rows_are_reachable_from_every_declared_parent
    """
    env = setup_policy_in_force(policy_number="AR-100014", document_prefix="DEC-36")

    vehicles, _ = _rows_and_meta(
        api_client.list_vehicles(env["applicant"]["id"], ADMIN_HEADERS), expected_total=1)
    declinations, _ = _rows_and_meta(
        api_client.list_market_rejections(env["application"]["id"], ADMIN_HEADERS),
        expected_total=2)
    cycles, _ = _rows_and_meta(
        api_client.list_assignment_cycles(env["plan_period"]["id"], ADMIN_HEADERS),
        expected_total=1)

    assert [row["id"] for row in vehicles] == [env["vehicle"]["id"]]
    assert all(row["application_id"] == env["application"]["id"] for row in declinations)
    assert [row["id"] for row in cycles] == [env["cycle"]["id"]]


def test_a_parent_with_no_children_answers_two_hundred_with_an_empty_array():
    """No loss has been reported, so the policy's claims collection is empty.

    Listing the claims of a policy that has none is a successful read of an empty
    collection rather than a miss: the plan answers 200 with an empty array and a
    total of zero.

    PRD: "an operation that brings a brand-new resource into existence answers 201
    Created, and every other successful operation — state transitions, cascades,
    ledger writes, reads and lists — answers 200 OK."
    Design: Corner/entities/child_rows_are_reachable_from_every_declared_parent
    """
    env = setup_policy_in_force(policy_number="AR-100014", document_prefix="DEC-36")

    response = api_client.list_claims(env["policy"]["id"], ADMIN_HEADERS)

    assert response.status_code == 200
    rows, meta = _rows_and_meta(response, expected_total=0)
    assert rows == []
    assert meta["has_more"] is False
