"""Corner validations: uniqueness scopes, referential guards and window boundaries.

Each rule below is probed on both sides of its edge wherever the PRD claims an
edge: the admissible instant and the refused one, the admissible identifier and
the colliding one. Every refusal is also checked to have written nothing.
"""
from test_helpers import (
    ATLAS,
    BEACON,
    ApiErrorId,
    accept_assignment,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_applicant,
    create_applicant_payload,
    create_applicant_with_vehicle,
    create_application_payload,
    create_assignment_cycle_payload,
    create_cancellation_payload,
    create_carrier_payload,
    create_certification_payload,
    create_claim_payload,
    create_exit_notice_payload,
    create_licensing_amendment_payload,
    create_market_rejection_payload,
    create_plan_period_payload,
    create_policy_payload,
    create_producer_payload,
    create_vehicle,
    create_vehicle_payload,
    file_market_rejection,
    make_compliance_examiner_headers,
    make_plan_administrator_headers,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
    place_and_accept,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_carrier,
    read_claim,
    read_plan_period,
    read_policy,
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

CLEAN_T02_DEPOSIT_CENTS = 38939
CLEAN_T02_TOTAL_CHARGE_CENTS = 155754


# ==========================================================================
# every_declared_unique_identifier_is_enforced
# ==========================================================================
def _plan_with_one_of_everything():
    """Two carriers, one producer, one period, one applicant and one vehicle."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    assert env["plan_period"]["period_code"] == "2026-P3"
    assert applicant["driver_license_number"] == "D-99011"
    assert vehicle["vin"] == "1HGCM82633A004360"
    return env, applicant, vehicle


def test_a_second_carrier_on_an_enrolled_naic_code_is_refused():
    """A different legal name does not buy a second claim on NAIC 11111.

    The uniqueness scope is the whole carrier table rather than the name, so
    enrolling "Atlas Mutual of the Bay" on 11111 collides with Atlas Mutual even
    though every other field differs. Nothing is written and the plan still knows
    exactly two carriers.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/every_declared_unique_identifier_is_enforced
    """
    _plan_with_one_of_everything()

    response = api_client.create_carrier(
        create_carrier_payload(name="Atlas Mutual of the Bay", naic_code="11111",
                               voluntary_market_share_bps=3000,
                               licensed_territories=["T01"]),
        ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    _, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
    assert meta["total_count"] == 2


def test_a_second_producer_licence_and_a_second_driver_licence_both_collide():
    """Two different entities, two different fields, one error identifier.

    A rival agency filing on licence PL-4471 and a second applicant filing on
    driver licence D-99011 are each refused with the same identifier and the same
    409, and each leaves the incumbent row untouched.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/every_declared_unique_identifier_is_enforced
    """
    env, applicant, _ = _plan_with_one_of_everything()

    producer_response = api_client.create_producer(
        create_producer_payload(name="Rival Agency", license_number="PL-4471",
                                appointed_territories=["T01"]),
        ADMIN_HEADERS)
    applicant_response = api_client.create_applicant(
        create_applicant_payload(full_name="Owen R Pike", driver_license_number="D-99011",
                                 territory_code="T01",
                                 first_licensed_date="2012-06-01T00:00:00Z"),
        ADMIN_HEADERS)

    validate_error(producer_response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    validate_error(applicant_response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    assert env["producer"]["name"] == "Harbor Agency"
    _, applications_meta = validate_paginated(api_client.list_applications(
        ADMIN_HEADERS, params={"applicant_id": applicant["id"]}))
    assert applications_meta["total_count"] == 0


def test_a_vin_already_on_file_under_another_applicant_is_still_a_duplicate():
    """The VIN namespace is the plan's, not the applicant's.

    Nadia Frost is a brand-new applicant with her own driver licence, and the
    vehicle she tries to add carries the VIN already registered to Owen Pike. The
    collision is refused even though the parent applicant differs, which is what
    stops one car being insured twice through the plan. Her vehicle list stays
    empty and Owen keeps his one vehicle.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/every_declared_unique_identifier_is_enforced
    """
    _, owen, _ = _plan_with_one_of_everything()
    nadia = create_applicant(full_name="Nadia Frost", driver_license_number="D-99012")

    response = api_client.create_vehicle(
        nadia["id"],
        create_vehicle_payload(vin="1HGCM82633A004360", vehicle_class_code="WORK_LT10",
                               garaging_territory_code="T01", model_year=2021),
        ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    _, nadia_meta = validate_paginated(api_client.list_vehicles(nadia["id"], ADMIN_HEADERS))
    assert nadia_meta["total_count"] == 0
    _, owen_meta = validate_paginated(api_client.list_vehicles(owen["id"], ADMIN_HEADERS))
    assert owen_meta["total_count"] == 1


def test_a_reused_period_code_is_refused_even_when_the_windows_do_not_touch():
    """Period codes are labels, and the label is unique whatever the calendar says.

    A second 2026-P3 running January through March 2027 cannot intersect the
    incumbent September-to-November window, so the window-conflict rule has nothing
    to say. The reused `period_code` alone refuses it, and the incumbent period is
    left exactly as it was.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/every_declared_unique_identifier_is_enforced
    """
    env, _, _ = _plan_with_one_of_everything()

    response = api_client.create_plan_period(
        create_plan_period_payload(period_code="2026-P3",
                                   window_start="2027-01-01T00:00:00Z",
                                   window_end="2027-03-31T00:00:00Z",
                                   underserved_territories=[]),
        ADMIN_HEADERS)

    error = validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    assert error["error_id"] != ApiErrorId.ERR_PERIOD_WINDOW_CONFLICT
    incumbent = read_plan_period(env["plan_period"]["id"])
    assert incumbent["window_start"][:10] == "2026-09-01"
    assert incumbent["window_end"][:10] == "2026-11-30"
    assert incumbent["status"] == "OPEN"


# ==========================================================================
# a_policy_number_is_unique_across_carriers
# ==========================================================================
def _two_accepted_assignments_with_different_carriers_and_one_issued_policy():
    """Two T02 risks placed by one run land on the two different carriers.

    The first carrier issues AR-100014, leaving the second carrier holding an
    accepted-but-unissued assignment against which the same number can be tried.
    """
    env = bootstrap_plan()
    first = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-23A")
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        document_prefix="DEC-23B")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert first_assignment["carrier_id"] != second_assignment["carrier_id"]
    accept_assignment(first_assignment["id"], first_assignment["carrier_id"])
    accept_assignment(second_assignment["id"], second_assignment["carrier_id"])
    set_clock("2026-09-15T00:00:00Z")
    first_policy = validate_success(api_client.create_policy(
        create_policy_payload(first_assignment["id"], policy_number="AR-100014"),
        make_servicing_carrier_headers(first_assignment["carrier_id"])), 201)
    assert first_policy["policy_number"] == "AR-100014"
    return {"env": env, "second_application": second["application"],
            "second_assignment": second_assignment, "first_policy": first_policy}


def _issue_second_policy(world, policy_number: str):
    return api_client.create_policy(
        create_policy_payload(world["second_assignment"]["id"], policy_number=policy_number),
        make_servicing_carrier_headers(world["second_assignment"]["carrier_id"]))


def test_a_second_carrier_cannot_mint_a_policy_number_the_first_carrier_used():
    """AR-100014 belongs to the plan's namespace, not to the carrier that used it.

    The second carrier's own assignment is perfectly issuable — accepted, in
    territory, with a lawful annual term — and the only defect is the policy number
    another carrier already wrote. The refusal writes no policy and leaves the
    assignment merely accepted.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/a_policy_number_is_unique_across_carriers
    """
    world = _two_accepted_assignments_with_different_carriers_and_one_issued_policy()

    response = _issue_second_policy(world, "AR-100014")

    validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    assert read_assignment(world["second_assignment"]["id"])["status"] == "ACCEPTED"
    _, meta = validate_paginated(api_client.list_policies(ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_the_refused_carrier_issues_immediately_under_a_free_number():
    """The collision cost the carrier nothing but the number it chose.

    Retrying as AR-100015 succeeds, the policy is rated from scratch at its own
    effective date to the pinned clean T02 figures, its `carrier_id` is the second
    carrier's, and both the assignment and the application advance.

    PRD: "The `ERR_DUPLICATE_IDENTIFIER` rule at priority 11 covers six uniqueness
    constraints, each enforced across all rows of its entity: a carrier's
    `naic_code`, which must be exactly 5 digits; a producer's `license_number`; an
    applicant's `driver_license_number`; a vehicle's `vin`, which must be exactly
    17 characters; a period's `period_code`; and a policy's `policy_number`."
    Design: Corner/validations/a_policy_number_is_unique_across_carriers
    """
    world = _two_accepted_assignments_with_different_carriers_and_one_issued_policy()
    validate_error(_issue_second_policy(world, "AR-100014"),
                   ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)

    second_policy = validate_success(_issue_second_policy(world, "AR-100015"), 201)

    assert second_policy["policy_number"] == "AR-100015"
    assert second_policy["carrier_id"] == world["second_assignment"]["carrier_id"]
    assert second_policy["policy_status"] == "IN_FORCE"
    assert second_policy["total_annual_charge_cents"] == CLEAN_T02_TOTAL_CHARGE_CENTS
    assert read_assignment(world["second_assignment"]["id"])["status"] == "POLICY_ISSUED"
    assert read_application(world["second_application"]["id"])["status"] == "POLICY_ISSUED"
    _, meta = validate_paginated(api_client.list_policies(ADMIN_HEADERS))
    assert meta["total_count"] == 2


# ==========================================================================
# declination_documents_must_name_real_and_distinct_carriers
# ==========================================================================
def _application_with_one_declination_verified_and_fully_paid():
    """One documented declination from NAIC 11111, a verified record, full deposit."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_market_rejection(application["id"], env["producer"]["id"],
                          rejecting_carrier_naic_code="11111",
                          rejection_date="2026-08-10T00:00:00Z",
                          reason_code="UNACCEPTABLE_DRIVING_RECORD",
                          document_reference="DEC-23C-1")
    verify_mvr(application["id"], [])
    record_deposit(application["id"], env["producer"]["id"], CLEAN_T02_DEPOSIT_CENTS)
    application = read_application(application["id"])
    assert application["required_deposit_cents"] == CLEAN_T02_DEPOSIT_CENTS
    assert application["deposit_paid_total_cents"] == CLEAN_T02_DEPOSIT_CENTS
    assert application["distinct_rejection_count"] == 1
    assert application["mvr_verified_at"] is not None
    return env, application


def _file_declination(env, application, naic_code: str, rejection_date: str,
                      reason_code: str, document_reference: str):
    return api_client.create_market_rejection(
        application["id"],
        create_market_rejection_payload(rejecting_carrier_naic_code=naic_code,
                                        rejection_date=rejection_date,
                                        reason_code=reason_code,
                                        document_reference=document_reference),
        make_producer_agent_headers(env["producer"]["id"]))


def test_a_declination_from_a_naic_code_no_carrier_holds_is_refused():
    """The plan never joins the carrier row into rating, but the code must be real.

    NAIC 99999 belongs to no enrolled carrier, so the filing is refused and the
    application's evidentiary file still holds exactly the one declination it had.

    PRD: "so a `rejecting_carrier_naic_code` matching no enrolled carrier's
    `naic_code` — regardless of that carrier's own `status` — is refused with
    `ERR_REJECTING_CARRIER_UNKNOWN` and HTTP 422."
    Design: Corner/validations/declination_documents_must_name_real_and_distinct_carriers
    """
    env, application = _application_with_one_declination_verified_and_fully_paid()

    response = _file_declination(env, application, "99999", "2026-08-11T00:00:00Z",
                                 "NO_APPETITE_TERRITORY", "DEC-23C-2")

    validate_error(response, ApiErrorId.ERR_REJECTING_CARRIER_UNKNOWN, 422)
    _, meta = validate_paginated(api_client.list_market_rejections(
        application["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert read_application(application["id"])["distinct_rejection_count"] == 1


def test_a_repeat_declination_from_a_carrier_already_on_file_is_refused_not_collapsed():
    """The same carrier declining twice is a filing error, not a silent collapse.

    NAIC 11111 is already on file inside the ninety-day lookback, so a second
    document from that carrier — a different date, a different reason code and a
    different control number — is refused rather than deduplicated. The count stays
    at one.

    PRD: "The plan also refuses a second declination from a NAIC code already on
    file for the same application inside the lookback window, with
    `ERR_DUPLICATE_REJECTING_CARRIER` and HTTP 409."
    Design: Corner/validations/declination_documents_must_name_real_and_distinct_carriers
    """
    env, application = _application_with_one_declination_verified_and_fully_paid()

    response = _file_declination(env, application, "11111", "2026-08-20T00:00:00Z",
                                 "PRIOR_CANCELLATION", "DEC-23C-3")

    validate_error(response, ApiErrorId.ERR_DUPLICATE_REJECTING_CARRIER, 409)
    _, meta = validate_paginated(api_client.list_market_rejections(
        application["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert read_application(application["id"])["distinct_rejection_count"] == 1


def test_certification_on_one_distinct_declination_is_refused_though_the_money_is_posted():
    """Both refused filings left the gate where it was: one distinct declination.

    The record is verified and the full 38939-cent deposit is posted, so the only
    surviving defect is the documentation count. Certification is refused, no
    certification timestamp is stamped and the period gains no assignable unit.

    PRD: "The application's `distinct_rejection_count` must be at least 2 — two
    different voluntary-market carriers must have declined the risk inside the
    ninety-day lookback — failing which the decision is refused with
    `ERR_INSUFFICIENT_MARKET_REJECTIONS` and HTTP 422."
    Design: Corner/validations/declination_documents_must_name_real_and_distinct_carriers
    """
    env, application = _application_with_one_declination_verified_and_fully_paid()
    validate_error(_file_declination(env, application, "99999", "2026-08-11T00:00:00Z",
                                     "NO_APPETITE_TERRITORY", "DEC-23C-2"),
                   ApiErrorId.ERR_REJECTING_CARRIER_UNKNOWN, 422)
    validate_error(_file_declination(env, application, "11111", "2026-08-20T00:00:00Z",
                                     "PRIOR_CANCELLATION", "DEC-23C-3"),
                   ApiErrorId.ERR_DUPLICATE_REJECTING_CARRIER, 409)

    response = api_client.decide_certification(
        application["id"], create_certification_payload("CERTIFY"),
        make_compliance_examiner_headers())

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_MARKET_REJECTIONS, 422)
    refused = read_application(application["id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["certified_at"] is None
    assert refused["distinct_rejection_count"] == 1
    assert refused["deposit_paid_total_cents"] == CLEAN_T02_DEPOSIT_CENTS
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 0


# ==========================================================================
# the_producer_of_record_must_be_active_and_appointed_where_the_risk_lives
# ==========================================================================
def _plan_with_three_producers_and_a_t02_risk():
    """Harbor Agency is fit; Lapsed Agency is suspended; Inland Agency is T01-only.

    The applicant lives in T02 and owns two vehicles, one garaged in T02 and one
    garaged in T01, so the appointment test can be aimed at the applicant's own
    territory rather than the vehicle's.
    """
    env = bootstrap_plan()
    lapsed = register_producer(name="Lapsed Agency", license_number="PL-9002",
                               appointed_territories=["T01", "T02", "T03"],
                               status="SUSPENDED")
    inland = register_producer(name="Inland Agency", license_number="PL-9003",
                               appointed_territories=["T01"])
    applicant, t02_vehicle = create_applicant_with_vehicle()
    t01_vehicle = create_vehicle(applicant["id"], vin="1HGCM82633A004361",
                                 garaging_territory_code="T01")
    assert applicant["territory_code"] == "T02"
    assert lapsed["status"] == "SUSPENDED"
    assert inland["appointed_territories"] == ["T01"]
    return {"env": env, "lapsed": lapsed, "inland": inland, "applicant": applicant,
            "t02_vehicle": t02_vehicle, "t01_vehicle": t01_vehicle}


def _attempt_submission(world, producer, vehicle):
    return api_client.create_application(
        create_application_payload(world["applicant"]["id"], producer["id"], vehicle["id"]),
        make_producer_agent_headers(producer["id"]))


def test_a_suspended_producer_cannot_submit_even_where_it_is_appointed():
    """Lapsed Agency is appointed in all three territories and still cannot transact.

    Its appointment covers T02 exactly, so the territory rule has nothing to say;
    the refusal is about standing alone, and it carries 409 rather than the 422 the
    appointment failure would carry. No application row appears.

    PRD: "The producer of record must be `ACTIVE`, or the request is refused with
    `ERR_PRODUCER_SUSPENDED` and HTTP 409."
    Design: Corner/validations/the_producer_of_record_must_be_active_and_appointed_where_the_risk_lives
    """
    world = _plan_with_three_producers_and_a_t02_risk()

    response = _attempt_submission(world, world["lapsed"], world["t02_vehicle"])

    error = validate_error(response, ApiErrorId.ERR_PRODUCER_SUSPENDED, 409)
    assert error["error_id"] != ApiErrorId.ERR_PRODUCER_TERRITORY_NOT_APPOINTED
    _, meta = validate_paginated(api_client.list_applications(
        ADMIN_HEADERS, params={"applicant_id": world["applicant"]["id"]}))
    assert meta["total_count"] == 0


def test_the_appointment_test_reads_the_applicant_territory_not_the_garage():
    """Inland Agency is active, and the vehicle is garaged exactly where it is appointed.

    The car sits in T01 and Inland Agency is appointed in T01, so a garage-based
    test would let this through. The applicant lives in T02, which is not in the
    agency's appointed territories, and the submission is refused with 422.

    PRD: "And the applicant's `territory_code` must appear in that producer's
    `appointed_territories`, or the request is refused with
    `ERR_PRODUCER_TERRITORY_NOT_APPOINTED` and HTTP 422."
    Design: Corner/validations/the_producer_of_record_must_be_active_and_appointed_where_the_risk_lives
    """
    world = _plan_with_three_producers_and_a_t02_risk()
    assert world["t01_vehicle"]["garaging_territory_code"] == "T01"

    response = _attempt_submission(world, world["inland"], world["t01_vehicle"])

    validate_error(response, ApiErrorId.ERR_PRODUCER_TERRITORY_NOT_APPOINTED, 422)
    _, meta = validate_paginated(api_client.list_applications(
        ADMIN_HEADERS, params={"applicant_id": world["applicant"]["id"]}))
    assert meta["total_count"] == 0


def test_the_fit_producer_submits_and_takes_the_first_intake_sequence():
    """Two refusals consumed no intake ordinal, so the first real submission is 1.

    Harbor Agency is active and appointed in T02, so the same applicant and the
    same T02 vehicle go through. The intake sequence is gap-free and starts at 1,
    which proves neither refused attempt wrote anything.

    PRD: "The producer of record must be `ACTIVE`, or the request is refused with
    `ERR_PRODUCER_SUSPENDED` and HTTP 409."
    Design: Corner/validations/the_producer_of_record_must_be_active_and_appointed_where_the_risk_lives
    """
    world = _plan_with_three_producers_and_a_t02_risk()
    validate_error(_attempt_submission(world, world["lapsed"], world["t02_vehicle"]),
                   ApiErrorId.ERR_PRODUCER_SUSPENDED, 409)
    validate_error(_attempt_submission(world, world["inland"], world["t01_vehicle"]),
                   ApiErrorId.ERR_PRODUCER_TERRITORY_NOT_APPOINTED, 422)

    application = validate_success(
        _attempt_submission(world, world["env"]["producer"], world["t02_vehicle"]), 201)

    assert application["status"] == "SUBMITTED"
    assert application["intake_sequence"] == 1
    assert application["producer_id"] == world["env"]["producer"]["id"]
    _, meta = validate_paginated(api_client.list_applications(
        ADMIN_HEADERS, params={"applicant_id": world["applicant"]["id"]}))
    assert meta["total_count"] == 1


# ==========================================================================
# period_and_cycle_windows_are_closed_intervals_and_the_clock_gates_the_run
# ==========================================================================
def _create_period(period_code: str, window_start: str, window_end: str):
    return api_client.create_plan_period(
        create_plan_period_payload(period_code=period_code, window_start=window_start,
                                   window_end=window_end, underserved_territories=[]),
        ADMIN_HEADERS)


def test_a_period_opening_on_the_incumbent_last_day_shares_it_and_is_refused():
    """Period windows are closed at both ends, so 2026-11-30 cannot belong to two periods.

    The incumbent period runs 2026-09-01 through 2026-11-30 inclusive. A successor
    starting on 2026-11-30 claims that same day, which is a genuine intersection,
    and the plan refuses it. Only one period exists afterwards.

    PRD: "A new period starts with `status` `OPEN` and `total_assignable_units` at
    zero, and its closed window may not intersect the window of any existing period
    — an intersection is refused with `ERR_PERIOD_WINDOW_CONFLICT` and HTTP 409."
    Design: Corner/validations/period_and_cycle_windows_are_closed_intervals_and_the_clock_gates_the_run
    """
    env = bootstrap_plan()
    assert env["plan_period"]["window_end"][:10] == "2026-11-30"

    response = _create_period("2026-P4", "2026-11-30T00:00:00Z", "2027-02-28T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_PERIOD_WINDOW_CONFLICT, 409)
    incumbent = read_plan_period(env["plan_period"]["id"])
    assert incumbent["window_end"][:10] == "2026-11-30"
    assert incumbent["status"] == "OPEN"


def test_a_period_opening_the_day_after_the_incumbent_closes_is_accepted():
    """The first admissible start is the day the incumbent no longer covers.

    Moving the requested start one day later to 2026-12-01 leaves the incumbent's
    closed window intact, so the successor period opens with an empty book: status
    OPEN and no assignable units yet.

    PRD: "A new period starts with `status` `OPEN` and `total_assignable_units` at
    zero, and its closed window may not intersect the window of any existing period
    — an intersection is refused with `ERR_PERIOD_WINDOW_CONFLICT` and HTTP 409."
    Design: Corner/validations/period_and_cycle_windows_are_closed_intervals_and_the_clock_gates_the_run
    """
    bootstrap_plan()
    validate_error(_create_period("2026-P4", "2026-11-30T00:00:00Z", "2027-02-28T00:00:00Z"),
                   ApiErrorId.ERR_PERIOD_WINDOW_CONFLICT, 409)

    successor = validate_success(
        _create_period("2026-P4", "2026-12-01T00:00:00Z", "2027-02-28T00:00:00Z"), 201)

    assert successor["window_start"][:10] == "2026-12-01"
    assert successor["status"] == "OPEN"
    assert successor["total_assignable_units"] == 0


def test_a_cycle_window_reaching_past_the_period_is_refused_and_one_ending_on_it_is_not():
    """Containment is measured against the parent's closed window on both sides.

    A December cycle sits wholly outside a period that closes on 2026-11-30 and is
    refused with 422. A cycle ending exactly on 2026-11-30 is inside that closed
    window, so it schedules, which shows the refusal was about containment rather
    than about the boundary day itself.

    PRD: "The cycle window must lie inside the parent period's window, or the
    request is refused with `ERR_CYCLE_WINDOW_OUTSIDE_PERIOD` and HTTP 422."
    Design: Corner/validations/period_and_cycle_windows_are_closed_intervals_and_the_clock_gates_the_run
    """
    env = bootstrap_plan()

    refused = api_client.create_assignment_cycle(
        create_assignment_cycle_payload(env["plan_period"]["id"],
                                        window_start="2026-12-01T00:00:00Z",
                                        window_end="2026-12-15T00:00:00Z"),
        ADMIN_HEADERS)

    validate_error(refused, ApiErrorId.ERR_CYCLE_WINDOW_OUTSIDE_PERIOD, 422)
    _, meta = validate_paginated(api_client.list_assignment_cycles(
        env["plan_period"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 0
    contained = validate_success(api_client.create_assignment_cycle(
        create_assignment_cycle_payload(env["plan_period"]["id"],
                                        window_start="2026-11-01T00:00:00Z",
                                        window_end="2026-11-30T00:00:00Z"),
        ADMIN_HEADERS), 201)
    assert contained["window_end"][:10] == "2026-11-30"
    assert contained["status"] == "SCHEDULED"


def test_a_cycle_cannot_run_before_its_window_opens_but_runs_on_the_opening_instant():
    """The clock gates the run: one day early is refused, the window_start instant is not.

    The cycle itself is lawful — inside its period and separated from every sibling
    — so the early refusal is purely about the clock reading 2026-09-01 against a
    window that opens on 2026-10-02. The cycle stays SCHEDULED with both counters at
    zero. Moving the clock exactly onto `window_start` lets the same run complete,
    and with nothing certified into the window it places nothing.

    PRD: "It is admissible only while the cycle is still `SCHEDULED`, only once the
    clock has reached the cycle's `window_start` — an earlier attempt is refused
    with `ERR_WINDOW_NOT_REACHED` and HTTP 409 — and only while the parent period's
    `status` is `OPEN`."
    Design: Corner/validations/period_and_cycle_windows_are_closed_intervals_and_the_clock_gates_the_run
    """
    env = bootstrap_plan()
    cycle = schedule_cycle(env["plan_period"]["id"], window_start="2026-10-02T00:00:00Z",
                           window_end="2026-10-31T00:00:00Z")

    early = api_client.run_assignment_cycle(cycle["id"], ADMIN_HEADERS)

    validate_error(early, ApiErrorId.ERR_WINDOW_NOT_REACHED, 409)
    unrun = read_assignment_cycle(cycle["id"])
    assert unrun["status"] == "SCHEDULED"
    assert unrun["assigned_count"] == 0
    assert unrun["run_at"] is None
    set_clock("2026-10-02T00:00:00Z")
    completed = validate_success(api_client.run_assignment_cycle(cycle["id"], ADMIN_HEADERS))
    assert completed["status"] == "COMPLETED"
    assert completed["assigned_count"] == 0
    assert completed["deferred_count"] == 0


# ==========================================================================
# a_plan_term_is_exactly_three_hundred_sixty_five_days_and_never_backdated
# ==========================================================================
def _accepted_assignment_at_the_issuance_clock():
    """One clean T02 risk accepted by its carrier, with the clock at 2026-09-15."""
    env = bootstrap_plan()
    risk = bring_application_to_certified(env, document_prefix="DEC-23D")
    placed = place_and_accept(env, risk["application"]["id"], env["carriers"][0]["id"])
    assert placed["assignment"]["status"] == "ACCEPTED"
    set_clock("2026-09-15T00:00:00Z")
    return env, risk["application"], placed["assignment"]


def _attempt_issuance(env, assignment, effective_date: str, expiration_date: str):
    return api_client.create_policy(
        create_policy_payload(assignment["id"], policy_number="AR-100014",
                              effective_date=effective_date,
                              expiration_date=expiration_date),
        make_servicing_carrier_headers(env["carriers"][0]["id"]))


def test_a_term_one_day_short_and_a_term_one_day_long_are_both_refused():
    """The term rule is an equality, so 364 days is as invalid as 366.

    From 2026-09-15 the only lawful expiration is 2027-09-15. Asking for
    2027-09-14 or 2027-09-16 misses that equality by a single day in either
    direction and both are refused with the same identifier. The assignment is
    still merely accepted and no policy row exists.

    PRD: "The `expiration_date` must be exactly 365 days after the `effective_date`
    and the `effective_date` must not be before the clock, or the request is
    refused with `ERR_POLICY_TERM_INVALID` and HTTP 422."
    Design: Corner/validations/a_plan_term_is_exactly_three_hundred_sixty_five_days_and_never_backdated
    """
    env, _, assignment = _accepted_assignment_at_the_issuance_clock()

    short_term = _attempt_issuance(env, assignment, "2026-09-15T00:00:00Z",
                                   "2027-09-14T00:00:00Z")
    long_term = _attempt_issuance(env, assignment, "2026-09-15T00:00:00Z",
                                  "2027-09-16T00:00:00Z")

    validate_error(short_term, ApiErrorId.ERR_POLICY_TERM_INVALID, 422)
    validate_error(long_term, ApiErrorId.ERR_POLICY_TERM_INVALID, 422)
    assert read_assignment(assignment["id"])["status"] == "ACCEPTED"
    _, meta = validate_paginated(api_client.list_policies(
        ADMIN_HEADERS, params={"assignment_id": assignment["id"]}))
    assert meta["total_count"] == 0


def test_a_backdated_term_of_exactly_the_right_length_is_still_refused():
    """A lawful 365-day term is not enough if it opens before the clock.

    A term running 2026-09-01 to 2027-09-01 is exactly 365 days long, so the length
    equality holds and the only defect is that the effective date precedes the
    clock at 2026-09-15. Backdating is refused with the same identifier and nothing
    is written.

    PRD: "The `expiration_date` must be exactly 365 days after the `effective_date`
    and the `effective_date` must not be before the clock, or the request is
    refused with `ERR_POLICY_TERM_INVALID` and HTTP 422."
    Design: Corner/validations/a_plan_term_is_exactly_three_hundred_sixty_five_days_and_never_backdated
    """
    env, _, assignment = _accepted_assignment_at_the_issuance_clock()

    response = _attempt_issuance(env, assignment, "2026-09-01T00:00:00Z",
                                 "2027-09-01T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_POLICY_TERM_INVALID, 422)
    assert read_assignment(assignment["id"])["status"] == "ACCEPTED"
    _, meta = validate_paginated(api_client.list_policies(
        ADMIN_HEADERS, params={"assignment_id": assignment["id"]}))
    assert meta["total_count"] == 0


def test_the_exact_annual_term_starting_at_the_clock_is_issued():
    """2026-09-15 to 2027-09-15 satisfies both halves of the rule at once.

    The term opens exactly at the clock and closes exactly 365 days later, so
    issuance succeeds — under the very policy number all three refused attempts
    used, which proves none of them wrote a row. The assignment and application
    both advance to POLICY_ISSUED.

    PRD: "The `expiration_date` must be exactly 365 days after the `effective_date`
    and the `effective_date` must not be before the clock, or the request is
    refused with `ERR_POLICY_TERM_INVALID` and HTTP 422."
    Design: Corner/validations/a_plan_term_is_exactly_three_hundred_sixty_five_days_and_never_backdated
    """
    env, application, assignment = _accepted_assignment_at_the_issuance_clock()
    validate_error(_attempt_issuance(env, assignment, "2026-09-15T00:00:00Z",
                                     "2027-09-14T00:00:00Z"),
                   ApiErrorId.ERR_POLICY_TERM_INVALID, 422)
    validate_error(_attempt_issuance(env, assignment, "2026-09-01T00:00:00Z",
                                     "2027-09-01T00:00:00Z"),
                   ApiErrorId.ERR_POLICY_TERM_INVALID, 422)

    policy = validate_success(_attempt_issuance(env, assignment, "2026-09-15T00:00:00Z",
                                                "2027-09-15T00:00:00Z"), 201)

    assert policy["policy_number"] == "AR-100014"
    assert policy["effective_date"][:10] == "2026-09-15"
    assert policy["expiration_date"][:10] == "2027-09-15"
    assert policy["policy_status"] == "IN_FORCE"
    assert read_assignment(assignment["id"])["status"] == "POLICY_ISSUED"
    assert read_application(application["id"])["status"] == "POLICY_ISSUED"


# ==========================================================================
# the_sixty_day_reason_window_is_closed_and_the_term_bounds_the_date
# ==========================================================================
def _policy_sixty_days_into_its_term():
    """A clean T02 policy running 2026-09-15 to 2027-09-15, read at 2026-11-14.

    2026-11-14 is exactly 60 whole days after inception and 2026-11-15 is 61, so
    the restricted-reason boundary can be probed from both sides.
    """
    env = setup_policy_in_force(policy_number="AR-100014")
    assert env["policy"]["total_annual_charge_cents"] == CLEAN_T02_TOTAL_CHARGE_CENTS
    assert env["policy"]["premium_credited_cents"] == CLEAN_T02_DEPOSIT_CENTS
    assert env["policy"]["complaint_freeze_active"] is False
    set_clock("2026-11-14T00:00:00Z")
    return env


def _attempt_cancellation(env, cancellation_effective_date: str):
    return api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("VEHICLE_NOT_GARAGED_IN_STATE",
                                    cancellation_effective_date),
        make_servicing_carrier_headers(env["carrier"]["id"]))


def test_a_cancellation_date_past_expiration_or_behind_the_clock_is_out_of_term():
    """The date is bounded on both sides, and each side reports the same identifier.

    2027-10-01 falls after the term closes on 2027-09-15, and 2026-09-01 falls both
    before inception and behind the clock. Both are refused as out of term, and the
    policy is still in force with nothing settled.

    PRD: "The `cancellation_effective_date` must lie inside the term, on or after
    `effective_date` and on or before `expiration_date`, and must not be earlier
    than the current clock; a date outside those bounds is refused with
    `ERR_CANCEL_DATE_OUT_OF_TERM` and HTTP 422."
    Design: Corner/validations/the_sixty_day_reason_window_is_closed_and_the_term_bounds_the_date
    """
    env = _policy_sixty_days_into_its_term()

    after_expiration = _attempt_cancellation(env, "2027-10-01T00:00:00Z")
    behind_the_clock = _attempt_cancellation(env, "2026-09-01T00:00:00Z")

    validate_error(after_expiration, ApiErrorId.ERR_CANCEL_DATE_OUT_OF_TERM, 422)
    validate_error(behind_the_clock, ApiErrorId.ERR_CANCEL_DATE_OUT_OF_TERM, 422)
    untouched = read_policy(env["policy"]["id"])
    assert untouched["policy_status"] == "IN_FORCE"
    assert untouched["refund_basis"] is None
    assert untouched["earned_premium_cents"] == 0
    assert untouched["premium_credited_cents"] == CLEAN_T02_DEPOSIT_CENTS


def test_a_first_sixty_day_reason_used_sixty_one_days_in_is_refused():
    """One day past the boundary the restricted reason is no longer available.

    A cancellation effective 2026-11-15 is 61 whole days after inception, and
    VEHICLE_NOT_GARAGED_IN_STATE is a first-sixty-day reason only. The date itself
    is inside the term and at the clock or later, so the refusal is about the reason
    code, not the date, and the policy settles nothing.

    PRD: "`VEHICLE_NOT_GARAGED_IN_STATE` and `PLAN_ORDERED` are first-sixty-day
    reasons only, and using either later is refused with
    `ERR_CANCEL_REASON_NOT_PERMITTED` and HTTP 422."
    Design: Corner/validations/the_sixty_day_reason_window_is_closed_and_the_term_bounds_the_date
    """
    env = _policy_sixty_days_into_its_term()

    response = _attempt_cancellation(env, "2026-11-15T00:00:00Z")

    error = validate_error(response, ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED, 422)
    assert error["error_id"] != ApiErrorId.ERR_CANCEL_DATE_OUT_OF_TERM
    untouched = read_policy(env["policy"]["id"])
    assert untouched["policy_status"] == "IN_FORCE"
    assert untouched["refund_paid_cents"] == 0
    assert untouched["balance_due_cents"] == 0
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 1


def test_the_same_reason_exactly_sixty_days_in_is_permitted_and_settles_pro_rata():
    """The boundary is inclusive: at exactly 60 days the restricted reason still holds.

    Shifting the effective date back one day to 2026-11-14 makes the elapsed term
    position exactly 60 whole days, which the plan still treats as the first sixty
    days. The carrier is the initiating party, so settlement is pro-rata: 155754
    times 60 over 365 rounded half up earns 25603 and refunds the remaining 13336
    of the 38939 credited.

    PRD: "The boundary is strict: a cancellation exactly 60 days into the term still
    permits the restricted reasons, and one 61 days in does not."
    Design: Corner/validations/the_sixty_day_reason_window_is_closed_and_the_term_bounds_the_date
    """
    env = _policy_sixty_days_into_its_term()
    validate_error(_attempt_cancellation(env, "2026-11-15T00:00:00Z"),
                   ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED, 422)

    validate_success(_attempt_cancellation(env, "2026-11-14T00:00:00Z"))

    settled = read_policy(env["policy"]["id"])
    assert settled["policy_status"] == "CANCELLED"
    assert settled["cancellation_reason_code"] == "VEHICLE_NOT_GARAGED_IN_STATE"
    assert settled["cancellation_initiated_by"] == "CARRIER"
    assert settled["refund_basis"] == "PRO_RATA"
    assert settled["earned_premium_cents"] == 25603
    assert settled["refund_paid_cents"] == 13336
    assert settled["balance_due_cents"] == 0
    assert settled["premium_settlement_status"] == "REFUND_ISSUED"
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 0


# ==========================================================================
# a_loss_must_fall_between_inception_and_today
# ==========================================================================
def _policy_in_force_with_the_clock_five_days_in():
    """A policy effective 2026-09-15 read at a clock of 2026-09-20."""
    env = setup_policy_in_force(policy_number="AR-100014")
    assert env["policy"]["effective_date"][:10] == "2026-09-15"
    assert env["policy"]["expiration_date"][:10] == "2027-09-15"
    set_clock("2026-09-20T00:00:00Z")
    return env


def _attempt_claim(env, loss_date: str):
    return api_client.create_claim(
        create_claim_payload(env["policy"]["id"], loss_date=loss_date),
        make_servicing_carrier_headers(env["carrier"]["id"]))


def test_a_loss_dated_before_inception_was_never_covered():
    """2026-09-10 predates the term, so the plan refuses to open a claim on it.

    The loss window opens at the policy's own effective date, and a date five days
    earlier falls outside it. No claim row is created under the policy.

    PRD: "The `loss_date` must fall on or after the policy's `effective_date` and no
    later than the current clock; a loss dated before the term opened or in the
    future is refused with `ERR_LOSS_DATE_OUTSIDE_TERM` and HTTP 422."
    Design: Corner/validations/a_loss_must_fall_between_inception_and_today
    """
    env = _policy_in_force_with_the_clock_five_days_in()

    response = _attempt_claim(env, "2026-09-10T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_LOSS_DATE_OUTSIDE_TERM, 422)
    _, meta = validate_paginated(api_client.list_claims(env["policy"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_loss_dated_tomorrow_is_refused_even_though_it_is_inside_the_term():
    """The upper bound is the logical clock, not the expiration date.

    2026-09-25 sits comfortably inside a term that runs to 2027-09-15, yet it is
    five days ahead of the clock at 2026-09-20, so the loss has not happened yet and
    the report is refused. Nothing is written.

    PRD: "The `loss_date` must fall on or after the policy's `effective_date` and no
    later than the current clock; a loss dated before the term opened or in the
    future is refused with `ERR_LOSS_DATE_OUTSIDE_TERM` and HTTP 422."
    Design: Corner/validations/a_loss_must_fall_between_inception_and_today
    """
    env = _policy_in_force_with_the_clock_five_days_in()

    response = _attempt_claim(env, "2026-09-25T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_LOSS_DATE_OUTSIDE_TERM, 422)
    _, meta = validate_paginated(api_client.list_claims(env["policy"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_loss_dated_exactly_at_the_clock_is_accepted_and_starts_the_ten_day_standard():
    """Both ends of the loss window are inclusive, so today's loss is reportable.

    A loss dated exactly at the clock opens a claim in OPEN, stamps `reported_at`
    with that same clock and sets the acknowledgement standard ten days out at
    2026-09-30. The two refused reports left the policy's claim file empty, so this
    is the only claim.

    PRD: "A filed claim begins in `OPEN`, records `reported_at` as the current
    clock, and derives its `acknowledgement_deadline` as ten days after
    `reported_at` — that ten-day window *is* the plan's claim-handling standard."
    Design: Corner/validations/a_loss_must_fall_between_inception_and_today
    """
    env = _policy_in_force_with_the_clock_five_days_in()
    validate_error(_attempt_claim(env, "2026-09-10T00:00:00Z"),
                   ApiErrorId.ERR_LOSS_DATE_OUTSIDE_TERM, 422)
    validate_error(_attempt_claim(env, "2026-09-25T00:00:00Z"),
                   ApiErrorId.ERR_LOSS_DATE_OUTSIDE_TERM, 422)

    claim = validate_success(_attempt_claim(env, "2026-09-20T00:00:00Z"), 201)

    assert claim["loss_date"][:10] == "2026-09-20"
    assert claim["status"] == "OPEN"
    assert read_claim(claim["id"])["standard_breach"] is False
    assert claim["reported_at"][:10] == "2026-09-20"
    assert claim["acknowledgement_deadline"][:10] == "2026-09-30"
    _, meta = validate_paginated(api_client.list_claims(env["policy"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 1


# ==========================================================================
# an_exit_needs_ninety_days_notice_and_only_an_active_carrier_may_file
# ==========================================================================
def _two_active_carriers_at_the_notice_clock():
    """Atlas writing T02 and Beacon writing T03, both ACTIVE, clock at 2026-09-15.

    2026-09-15 plus 90 days is 2026-12-14, which is the earliest admissible exit
    effective date.
    """
    env = bootstrap_plan(clock="2026-09-15T00:00:00Z",
                         carriers=[ATLAS, dict(BEACON, licensed_territories=["T03"])])
    atlas, beacon = env["carriers"]
    assert beacon["status"] == "ACTIVE"
    assert beacon["licensed_territories"] == ["T03"]
    assert beacon["exit_effective_date"] is None
    return env, atlas, beacon


def _file_exit_notice(carrier, exit_effective_date: str):
    return api_client.file_carrier_exit_notice(
        carrier["id"], create_exit_notice_payload(exit_effective_date), ADMIN_HEADERS)


def test_a_forty_seven_day_exit_notice_is_too_short_and_the_carrier_stays_active():
    """The plan needs three months of warning before a carrier may walk.

    An exit effective 2026-11-01 is only 47 days after the clock, well inside the
    ninety-day floor, so the notice is refused. The carrier keeps its ACTIVE status,
    its `exit_effective_date` is still null and its posture is untouched.

    PRD: "A `PlanAdministrator` files the notice with an `exit_effective_date`,
    which is recorded on the carrier and must be at least 90 days after the current
    clock; a shorter notice is refused with `ERR_EXIT_NOTICE_TOO_SHORT` and HTTP
    422."
    Design: Corner/validations/an_exit_needs_ninety_days_notice_and_only_an_active_carrier_may_file
    """
    _, _, beacon = _two_active_carriers_at_the_notice_clock()

    response = _file_exit_notice(beacon, "2026-11-01T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_EXIT_NOTICE_TOO_SHORT, 422)
    unchanged = read_carrier(beacon["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["exit_effective_date"] is None
    assert unchanged["posture"] == "OPEN"


def test_an_exit_notice_exactly_ninety_days_out_is_accepted_and_suspends_the_posture():
    """The floor is inclusive, so 2026-12-14 is the first admissible exit date.

    One day later than the refused attempt would still be short; exactly ninety days
    out is enough. The carrier moves to EXIT_NOTICED and, because a status other
    than ACTIVE is the top rung of the posture ladder, its posture reads SUSPENDED
    while its score is still a perfect 100. Beacon also leaves the apportionment
    denominator, so Atlas alone carries the period's zero assignable units.

    PRD: "A `PlanAdministrator` files the notice with an `exit_effective_date`,
    which is recorded on the carrier and must be at least 90 days after the current
    clock; a shorter notice is refused with `ERR_EXIT_NOTICE_TOO_SHORT` and HTTP
    422."
    Design: Corner/validations/an_exit_needs_ninety_days_notice_and_only_an_active_carrier_may_file
    """
    _, atlas, beacon = _two_active_carriers_at_the_notice_clock()
    validate_error(_file_exit_notice(beacon, "2026-11-01T00:00:00Z"),
                   ApiErrorId.ERR_EXIT_NOTICE_TOO_SHORT, 422)

    noticed = validate_success(_file_exit_notice(beacon, "2026-12-14T00:00:00Z"))

    assert noticed["status"] == "EXIT_NOTICED"
    assert noticed["exit_effective_date"][:10] == "2026-12-14"
    assert noticed["posture"] == "SUSPENDED"
    assert noticed["performance_score"] == 100
    assert read_carrier(atlas["id"])["quota_target_units"] == 0


def test_a_withdrawing_carrier_may_neither_file_again_nor_amend_its_licensing():
    """Once the notice is on file the carrier is no longer ACTIVE, and two doors shut.

    A second exit notice — this one a comfortable four months out — is refused
    because the filing requires an ACTIVE carrier, and so is a licensing amendment
    that would have replaced the carrier's territories. Both carry 409, the recorded
    exit date is unchanged and the carrier still writes only T03.

    PRD: "The carrier's `status` must be `ACTIVE` at the time of the notice, and a
    carrier already withdrawing is refused with `ERR_CARRIER_NOT_ACTIVE` and HTTP
    409."
    Design: Corner/validations/an_exit_needs_ninety_days_notice_and_only_an_active_carrier_may_file
    """
    _, _, beacon = _two_active_carriers_at_the_notice_clock()
    validate_success(_file_exit_notice(beacon, "2026-12-14T00:00:00Z"))

    second_notice = _file_exit_notice(beacon, "2027-01-15T00:00:00Z")
    amendment = api_client.file_carrier_licensing_amendment(
        beacon["id"], create_licensing_amendment_payload(["T01", "T02"]), ADMIN_HEADERS)

    validate_error(second_notice, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, 409)
    validate_error(amendment, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, 409)
    withdrawing = read_carrier(beacon["id"])
    assert withdrawing["status"] == "EXIT_NOTICED"
    assert withdrawing["exit_effective_date"][:10] == "2026-12-14"
    assert withdrawing["licensed_territories"] == ["T03"]
