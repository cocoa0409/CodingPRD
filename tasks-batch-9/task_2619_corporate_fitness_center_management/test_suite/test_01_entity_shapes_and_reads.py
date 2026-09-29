"""Entity field shapes and read paths for the corporate fitness centre API.

Each test drives one create-or-read claim: the declared defaults a create
applies, the values a read hands back, the pagination metadata a filtered
listing reports, and the entity-specific identities the existence and shape
checks produce.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_client_contract,
    assert_facility_asset,
    assert_facility_room,
    assert_liability_waiver,
    assert_member,
    assert_no_type_prefix,
    assert_participation_record,
    assert_program_session,
    assert_three_fractional_digits,
)
from test_helpers.factories import (
    aed_asset_payload,
    client_contract_payload,
    facility_room_payload,
    inspection_payload,
    member_payload,
    participation_payload,
    program_offering_payload,
    program_session_payload,
    waiver_payload,
)

ADMIN = TEST_USERS["operator_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def test_contract_creation_returns_declared_defaults_and_version_one(clock):
    """PRD §3.1: "A newly created contract lands in `DRAFT` with
    `revision_round`, `ytd_billed_cents`, `pending_penalty_cents`,
    `uncovered_session_count`, and `eligible_member_count` all initialised to 0,
    `supersedes_contract_id` null, and `approved_at` null."

    PRD §3.1: "A `COST_PLUS` contract must carry `not_to_exceed_cents` — an
    annual ceiling strictly greater than zero — and must leave
    `management_fee_cents` null."

    PRD §2.4: "Most records additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the record — and `version`, an
    integer that starts at 1 when the record is created and increments by
    exactly 1 on every mutation of that record, including mutations caused by a
    cascade originating elsewhere."

    PRD §2.4: "Identifiers have no type prefix and no embedded semantics;
    clients must never construct one, and any client-supplied `id` on a create
    is ignored."

    Design: Corner/entities/create_client_contract_applies_declared_defaults
    """
    response = api_client.create_client_contract(client_contract_payload(), ADMIN)
    contract = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object", (
        f"a single created contract is an object envelope, got {body['response_type']!r}"
    )
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert body["meta"].get("api_request_timestamp"), (
        "meta.api_request_timestamp must be present"
    )

    assert_client_contract(contract)
    assert contract["status"] == "DRAFT", (
        f"a newly created contract lands in DRAFT, got {contract['status']!r}"
    )
    assert contract["version"] == 1, (
        f"version starts at 1 on creation, got {contract['version']!r}"
    )
    for counter in (
        "revision_round",
        "ytd_billed_cents",
        "pending_penalty_cents",
        "uncovered_session_count",
        "eligible_member_count",
    ):
        assert contract[counter] == 0, (
            f"{counter} is initialised to 0 on creation, got {contract[counter]!r}"
        )
    assert contract["approved_at"] is None, (
        f"approved_at is null until the client approves, got {contract['approved_at']!r}"
    )
    assert contract["supersedes_contract_id"] is None, (
        "supersedes_contract_id is null on an original contract, got "
        f"{contract['supersedes_contract_id']!r}"
    )
    assert contract["management_fee_cents"] is None, (
        "a COST_PLUS contract must leave management_fee_cents null, got "
        f"{contract['management_fee_cents']!r}"
    )

    assert contract["not_to_exceed_cents"] == 5000000, (
        f"not_to_exceed_cents is stored as supplied, got {contract['not_to_exceed_cents']!r}"
    )
    assert contract["budgeted_staff_fte"] == 3.5, (
        f"budgeted_staff_fte is stored as supplied, got {contract['budgeted_staff_fte']!r}"
    )
    assert contract["participation_target_pct"] == 35, (
        "participation_target_pct is stored as supplied, got "
        f"{contract['participation_target_pct']!r}"
    )

    assert_no_type_prefix(contract["id"])
    assert_three_fractional_digits(contract["created_at"])
    assert_three_fractional_digits(contract["updated_at"])


def test_contract_read_path_returns_the_stored_commercial_terms(clock):
    """PRD §3.1: "An `OperatorAdmin` opens one by supplying the corporate
    `client_name` (between 1 and 120 characters), the operator's own `site_code`
    for the location, the commercial `fee_structure`, the `staffing_model`, the
    contracted staffing level as `budgeted_staff_fte`, the client's
    `participation_target_pct` goal, and the term boundaries `term_start_on` and
    `term_end_on` as calendar dates in `YYYY-MM-DD` form."

    PRD §3.1: "A newly created contract lands in `DRAFT` with `revision_round`,
    `ytd_billed_cents`, `pending_penalty_cents`, `uncovered_session_count`, and
    `eligible_member_count` all initialised to 0, `supersedes_contract_id` null,
    and `approved_at` null."

    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/entities/get_client_contract_returns_stored_entity
    """
    created = validate_success(
        api_client.create_client_contract(client_contract_payload(), ADMIN), 201
    )

    response = api_client.get_client_contract(created["id"], AUDITOR)
    contract = validate_success(response)
    body = response.json()

    assert body["response_type"] == "object", (
        f"a single contract read is an object envelope, got {body['response_type']!r}"
    )
    assert_client_contract(contract)
    assert contract["id"] == created["id"], (
        f"the read must return the written row, got {contract['id']!r}"
    )
    assert contract["client_name"] == "Northwind Manufacturing", (
        f"client_name must round-trip unchanged, got {contract['client_name']!r}"
    )
    assert contract["site_code"] == "NWM-01", (
        f"site_code must round-trip unchanged, got {contract['site_code']!r}"
    )
    assert contract["fee_structure"] == "COST_PLUS", (
        f"fee_structure must round-trip unchanged, got {contract['fee_structure']!r}"
    )
    assert contract["term_start_on"] == "2026-07-01", (
        f"term_start_on must round-trip as YYYY-MM-DD, got {contract['term_start_on']!r}"
    )
    assert contract["term_end_on"] == "2027-06-30", (
        f"term_end_on must round-trip as YYYY-MM-DD, got {contract['term_end_on']!r}"
    )
    assert contract["status"] == "DRAFT", (
        f"the contract is still a draft when read back, got {contract['status']!r}"
    )
    assert contract["version"] == 1, (
        f"reading a record does not mutate it, expected version 1, got {contract['version']!r}"
    )


def test_member_listing_filters_by_class_before_paginating(active_contract):
    """PRD §2.3: "`total_count` is the number of rows matching the filters
    before pagination is applied, and `has_more` is true exactly when rows
    remain beyond the current page."

    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum
    accepted value is 1, and its maximum accepted value is 100."

    PRD §3.6: "Member listings can be filtered by `contract_id`, by
    `sponsor_member_id`, by `member_class`, and by either dimension via
    `eligibility_status` and `access_status`."

    Design: Corner/entities/list_members_filtered_by_class_paginates
    """
    scenario = active_contract
    iris = scenarios.enrol_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    jon = scenarios.enrol_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Jon Alvarez",
        employee_number="E-1002",
    )
    pat = scenarios.enrol_member(
        scenario, member_class="RETIREE", full_name="Pat Nowak"
    )

    first_items, first_meta = validate_paginated(
        api_client.list_members(
            scenario["manager_headers"],
            params={
                "contract_id": scenario["contract_id"],
                "member_class": "EMPLOYEE",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert len(first_items) == 1, f"limit 1 returns one row, got {len(first_items)}"
    assert first_meta["limit"] == 1, f"meta.limit echoes the request, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"meta.offset echoes the request, got {first_meta['offset']}"
    assert first_meta["total_count"] == 2, (
        "total_count counts the two EMPLOYEE rows matching the filter, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "one EMPLOYEE row remains beyond the first page, so has_more must be true"
    )

    second_items, second_meta = validate_paginated(
        api_client.list_members(
            scenario["manager_headers"],
            params={
                "contract_id": scenario["contract_id"],
                "member_class": "EMPLOYEE",
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert len(second_items) == 1, f"limit 1 returns one row, got {len(second_items)}"
    assert second_meta["offset"] == 1, (
        f"meta.offset echoes the request, got {second_meta['offset']}"
    )
    assert second_meta["total_count"] == 2, (
        f"the filtered total is unchanged by paging, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "no EMPLOYEE row remains beyond the second page, so has_more must be false"
    )

    paged_ids = [first_items[0]["id"], second_items[0]["id"]]
    assert set(paged_ids) == {iris["id"], jon["id"]}, (
        f"the two pages together return both EMPLOYEE members exactly once, got {paged_ids}"
    )
    assert pat["id"] not in paged_ids, (
        "the RETIREE must never appear in a member_class=EMPLOYEE page"
    )
    for item in first_items + second_items:
        assert_member(item)

    all_items, all_meta = validate_paginated(
        api_client.list_members(
            scenario["manager_headers"],
            params={"contract_id": scenario["contract_id"]},
        )
    )
    assert all_meta["total_count"] == 3, (
        f"unfiltered, all three members of the contract match, got {all_meta['total_count']}"
    )
    assert all_meta["has_more"] is False, (
        "three rows fit inside the default page, so has_more must be false"
    )
    assert all_meta["limit"] == 10, (
        f"limit defaults to 10 when the caller omits it, got {all_meta['limit']}"
    )
    assert len(all_items) == 3, f"the default page carries all three rows, got {len(all_items)}"


def test_staff_member_fetch_with_unknown_uuid_reports_staff_not_found(clock):
    """PRD §2.6: "Existence failures always name the entity type that failed to
    resolve, whether the identifier came from the URL or from the request body:
    `ERR_CONTRACT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_WAIVER_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND` — all HTTP 404."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_staff_member_unknown_id_returns_not_found
    """
    response = api_client.get_staff_member(NON_EXISTENT_UUID, ADMIN)

    error = validate_error(response, ApiErrorId.ERR_STAFF_NOT_FOUND.value)
    body = response.json()
    assert body["response_type"] == "error", (
        f"a failed lookup uses the error envelope, got {body['response_type']!r}"
    )
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"the 404 must carry a human-readable message, got {error.get('message')!r}"
    )


def test_offering_creation_without_participation_target_is_invalid_request(draft_contract):
    """PRD §3.4: "Creating one names the `contract_id` it belongs to, the
    `lead_staff_id` of the instructor or trainer who leads it — who must be a
    staff member of that same contract — the `program_type` (one of
    `GROUP_EXERCISE`, `PERSONAL_TRAINING`, or `WELLNESS_CHALLENGE`), a `title`, a
    `participation_target` greater than zero representing counted participations
    over the program's whole life, a `max_participants_per_session` roster cap
    greater than zero, and the `required_credential_type` that every staff member
    assigned to any of its sessions must hold."

    PRD §2.11: "Request-body shape, types, enum ranges, numeric bounds, date
    formats, and pagination bounds (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_program_offering_missing_target_returns_invalid_request
    """
    scenario = draft_contract
    instructor = scenarios.hire_staff(
        scenario["contract_id"],
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Ravi Patel",
        hourly_cost_cents=4700,
    )

    payload = program_offering_payload(scenario["contract_id"], instructor["id"])
    del payload["participation_target"]

    response = api_client.create_program_offering(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _items, meta = validate_paginated(
        api_client.list_program_offerings(
            ADMIN, params={"contract_id": scenario["contract_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected creation must persist nothing, got {meta['total_count']} offerings"
    )


def test_member_enrolment_defaults_consent_and_both_status_dimensions(draft_contract):
    """PRD §3.6: "Enrolment also accepts `health_data_consent`, which defaults to
    false when omitted, and is the switch that governs whether health-metric
    notes may ever be attached to this person's participation."

    PRD §3.6: "A new enrolment starts at `PENDING_VERIFICATION` and `NO_BADGE`,
    with `incentive_points_balance` at 0, `current_waiver_id` null, and
    `last_check_in_utc` null."

    PRD §3.6: "A `DEPENDENT` must carry a `sponsor_member_id` naming the
    sponsoring employee, and an `EMPLOYEE` or `RETIREE` must leave it null."

    PRD §2.9: "A contract's `eligible_member_count` always equals the number of
    that contract's members whose `eligibility_status` is `ELIGIBLE`."

    Design: Corner/entities/member_creation_applies_declared_defaults
    """
    scenario = draft_contract
    payload = member_payload(
        scenario["contract_id"], full_name="Iris Okafor", employee_number="E-1001"
    )
    del payload["health_data_consent"]

    member = validate_success(
        api_client.create_member(payload, scenario["sponsor_headers"]), 201
    )

    assert_member(member)
    assert member["health_data_consent"] is False, (
        "health_data_consent defaults to false when omitted, got "
        f"{member['health_data_consent']!r}"
    )
    assert member["eligibility_status"] == "PENDING_VERIFICATION", (
        f"a new enrolment starts at PENDING_VERIFICATION, got {member['eligibility_status']!r}"
    )
    assert member["access_status"] == "NO_BADGE", (
        f"a new enrolment starts at NO_BADGE, got {member['access_status']!r}"
    )
    assert member["incentive_points_balance"] == 0, (
        f"the incentive ledger starts empty, got {member['incentive_points_balance']!r}"
    )
    assert member["current_waiver_id"] is None, (
        f"current_waiver_id starts null, got {member['current_waiver_id']!r}"
    )
    assert member["last_check_in_utc"] is None, (
        f"last_check_in_utc starts null, got {member['last_check_in_utc']!r}"
    )
    assert member["sponsor_member_id"] is None, (
        f"an EMPLOYEE leaves sponsor_member_id null, got {member['sponsor_member_id']!r}"
    )
    assert member["version"] == 1, (
        f"version starts at 1 on creation, got {member['version']!r}"
    )

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["eligible_member_count"] == 0, (
        "enrolment alone makes nobody ELIGIBLE, so eligible_member_count stays 0, got "
        f"{contract['eligible_member_count']!r}"
    )


def test_session_scheduled_minutes_derived_from_start_and_end():
    """PRD §3.5: "A new session lands in `SCHEDULED` with `actual_attendance` at
    0, `cancel_reason`, `started_at`, and `completed_at` all null, and a computed
    `scheduled_minutes` equal to the whole number of minutes between its start
    and end instants."

    PRD §3.4: "Its numerator is the count of participation records still in
    `COUNTED` status that belong to sessions of this offering whose status is
    `IN_PROGRESS` or `COMPLETED`, **plus** the sum of `forecast_attendance`
    across every session of this offering still open — that is, still in
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK`."

    PRD §3.4: "Multiply that numerator by 100, divide by `participation_target`,
    round half up, and store the result in `provisional_attainment_pct`."

    PRD §3.4: "Its numerator is the count of participation records still in
    `COUNTED` status belonging to sessions of this offering in `COMPLETED` status
    only; forecasts and open sessions are ignored entirely."

    PRD §3.4: "`counted_participation_total` is the number of participation
    records in `COUNTED` status across all of the offering's sessions,
    incremented on every check-in and decremented on every void."

    Design: Corner/entities/session_scheduled_minutes_is_computed_from_the_schedule
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={
            "participation_target": 8,
            "max_participants_per_session": 6,
            "eligible_member_classes": ["EMPLOYEE"],
        }
    )

    response = api_client.create_program_session(
        program_session_payload(
            scenario["offering_id"],
            scenario["room_id"],
            scheduled_start_utc="2026-08-05T12:00:00Z",
            scheduled_end_utc="2026-08-05T12:55:00Z",
            forecast_attendance=3,
            direct_supply_cost_cents=0,
        ),
        scenario["manager_headers"],
    )
    session = validate_success(response, 201)

    assert_program_session(session)
    assert session["scheduled_minutes"] == 55, (
        "12:00:00Z to 12:55:00Z is 55 whole minutes, got "
        f"{session['scheduled_minutes']!r}"
    )
    assert session["status"] == "SCHEDULED", (
        f"a new session lands in SCHEDULED, got {session['status']!r}"
    )
    assert session["actual_attendance"] == 0, (
        f"actual_attendance starts at 0, got {session['actual_attendance']!r}"
    )
    assert session["forecast_attendance"] == 3, (
        f"forecast_attendance is stored as supplied, got {session['forecast_attendance']!r}"
    )
    assert session["cancel_reason"] is None, (
        f"cancel_reason starts null, got {session['cancel_reason']!r}"
    )
    assert session["started_at"] is None, (
        f"started_at starts null, got {session['started_at']!r}"
    )
    assert session["completed_at"] is None, (
        f"completed_at starts null, got {session['completed_at']!r}"
    )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["provisional_attainment_pct"] == 38, (
        "a forecast of 3 against a target of 8 rounds 37.5 half up to 38, got "
        f"{offering['provisional_attainment_pct']!r}"
    )
    assert offering["final_attainment_pct"] == 0, (
        "no session has completed, so the final figure stays 0, got "
        f"{offering['final_attainment_pct']!r}"
    )
    assert offering["counted_participation_total"] == 0, (
        "nobody has checked in yet, got "
        f"{offering['counted_participation_total']!r}"
    )


def test_waiver_signed_at_status_and_id_ignore_client_supplied_values(active_contract):
    """PRD §2.4: "More generally, fields whose values the server computes or
    assigns are never accepted from the client. When a request body contains such
    a field, the value is silently ignored rather than rejected; the request does
    not fail on that account."

    PRD §2.4: "Identifiers have no type prefix and no embedded semantics; clients
    must never construct one, and any client-supplied `id` on a create is
    ignored."

    PRD §3.6: "On success the new waiver is written in `SIGNED` status with
    `signed_at` stamped from the logical clock, the member's previously `SIGNED`
    waiver — if there was one — moves to `SUPERSEDED`, and the member's
    `current_waiver_id` is repointed at the new waiver while the member's own
    `version` advances."

    PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`, and
    it never falls back to real time."

    Design: Corner/entities/waiver_signed_at_and_status_are_system_owned_input_ignored
    """
    scenario = active_contract
    member = scenarios.enrol_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    scenarios.verify_member(scenario, member["id"])
    expected_version = scenarios.member_version(member["id"])

    supplied_id = "11111111-1111-4111-8111-111111111111"
    payload = waiver_payload(
        expected_version,
        signed_at="2020-01-01T00:00:00Z",
        status="REVOKED",
        id=supplied_id,
    )
    waiver = validate_success(
        api_client.create_waiver(member["id"], payload, scenario["manager_headers"]),
        201,
    )

    assert_liability_waiver(waiver)
    assert waiver["status"] == "SIGNED", (
        "a filed waiver is written in SIGNED status and the supplied REVOKED is "
        f"ignored, got {waiver['status']!r}"
    )
    assert waiver["signed_at"] != "2020-01-01T00:00:00Z", (
        "signed_at is stamped from the logical clock, not from the client's value"
    )
    assert waiver["signed_at"].startswith("2026-08-01T00:00:00"), (
        "signed_at must carry the logical clock instant 2026-08-01T00:00:00Z, got "
        f"{waiver['signed_at']!r}"
    )
    assert waiver["id"] != supplied_id, (
        "the id is server-minted and any client-supplied id is ignored, got "
        f"{waiver['id']!r}"
    )
    assert_no_type_prefix(waiver["id"])

    stored_member = scenarios.read_member(member["id"])
    assert stored_member["current_waiver_id"] == waiver["id"], (
        "current_waiver_id must be repointed at the new waiver, got "
        f"{stored_member['current_waiver_id']!r}"
    )


def test_room_inspection_score_outside_zero_to_hundred_is_invalid_request(active_contract):
    """PRD §3.3: "An inspection supplies the `inspection_on` date, a
    `cleanliness_score` from 0 through 100 inclusive, a `deficiency_count`, and
    optionally free-text `notes`."

    PRD §3.3: "A newly registered room opens for business immediately:
    `room_state` is `OPEN`, `open_deficiency_count` is 0, and both
    `last_inspection_on` and `last_cleanliness_score` are null until the first
    inspection lands."

    PRD §3.3: "An inspection **passes** when the `cleanliness_score` is at least
    85 **and** the `deficiency_count` is exactly 0; anything else — a score below
    85, or any deficiency at all, or both — **fails**."

    PRD §3.3: "Every inspection writes `last_inspection_on`,
    `last_cleanliness_score`, and `open_deficiency_count` onto the room from the
    supplied values; `open_deficiency_count` therefore tracks the deficiencies
    recorded by the *most recent* inspection that have not since been cleared by
    a passing one."

    Design: Corner/entities/room_inspection_score_out_of_range_returns_invalid_request
    """
    scenario = active_contract
    room = scenarios.add_room(scenario, room_name="Studio A")

    validate_error(
        api_client.create_room_inspection(
            room["id"],
            inspection_payload(
                inspection_on="2026-08-01", cleanliness_score=101, deficiency_count=0
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.create_room_inspection(
            room["id"],
            inspection_payload(
                inspection_on="2026-08-01", cleanliness_score=-1, deficiency_count=0
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    untouched = scenarios.read_room(room["id"])
    assert_facility_room(untouched)
    assert untouched["room_state"] == "OPEN", (
        "an out-of-range score is a shape violation, never a failing inspection, so "
        f"the room stays OPEN, got {untouched['room_state']!r}"
    )
    assert untouched["last_inspection_on"] is None, (
        "no inspection landed, so last_inspection_on is still null, got "
        f"{untouched['last_inspection_on']!r}"
    )
    assert untouched["last_cleanliness_score"] is None, (
        "no inspection landed, so last_cleanliness_score is still null, got "
        f"{untouched['last_cleanliness_score']!r}"
    )
    assert untouched["open_deficiency_count"] == 0, (
        f"open_deficiency_count is still 0, got {untouched['open_deficiency_count']!r}"
    )

    validate_success(
        api_client.create_room_inspection(
            room["id"],
            inspection_payload(
                inspection_on="2026-08-01", cleanliness_score=100, deficiency_count=0
            ),
            AUDITOR,
        )
    )

    inspected = scenarios.read_room(room["id"])
    assert inspected["room_state"] == "OPEN", (
        "a score of 100 with no deficiencies passes, so the room stays OPEN, got "
        f"{inspected['room_state']!r}"
    )
    assert inspected["last_cleanliness_score"] == 100, (
        "100 is the inclusive upper bound and is written onto the room, got "
        f"{inspected['last_cleanliness_score']!r}"
    )
    assert inspected["last_inspection_on"] == "2026-08-01", (
        f"last_inspection_on comes from the payload, got {inspected['last_inspection_on']!r}"
    )
    assert inspected["open_deficiency_count"] == 0, (
        f"a passing inspection records zero deficiencies, got {inspected['open_deficiency_count']!r}"
    )


def test_participation_record_read_exposes_no_version_or_updated_at():
    """PRD §2.4: "A participation check-in is an append-only event: it carries
    only `id` and `created_at`, and both `updated_at` and `version` are absent
    from its representation entirely."

    PRD §2.4: "The one mutation a participation record ever undergoes — the
    correction that voids it — does not introduce either field."

    PRD §3.7: "The record is written in `COUNTED` status with `check_in_utc`
    stamped from the logical clock, and the member's `last_check_in_utc` is
    updated to the same instant."

    PRD §3.7: "Which of those happened is recorded on the record itself:
    `recorded_by_role` is derived from the caller's role header and stores
    `MEMBER` for a self check-in and `FITNESS_STAFF` for anybody else."

    PRD §3.7: "The uncapped candidate award is 10 points, plus a further 5 points
    when that distinct-prior-day count is 3 or more."

    Design: Corner/entities/participation_record_carries_no_version_field
    """
    scenario = scenarios.setup_active_program()
    member = scenarios.setup_ready_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    scenario, session, _lead = scenarios.setup_in_progress_session(scenario)

    created = validate_success(
        api_client.create_participation_record(
            participation_payload(member["id"], session["id"]),
            scenario["instructor_headers"],
        ),
        201,
    )

    record = validate_success(
        api_client.get_participation_record(created["id"], scenario["manager_headers"])
    )

    assert_participation_record(record)
    assert record["id"] == created["id"], (
        f"the read must return the written check-in, got {record['id']!r}"
    )
    assert "version" not in record, (
        f"a participation record carries no version field, got {record.get('version')!r}"
    )
    assert "updated_at" not in record, (
        f"a participation record carries no updated_at field, got {record.get('updated_at')!r}"
    )
    assert record["status"] == "COUNTED", (
        f"a new check-in is written in COUNTED status, got {record['status']!r}"
    )
    assert record["recorded_by_role"] == "FITNESS_STAFF", (
        "a check-in taken by fitness staff records FITNESS_STAFF, got "
        f"{record['recorded_by_role']!r}"
    )
    assert record["check_in_utc"].startswith("2026-08-05T12:00:00"), (
        "check_in_utc is stamped from the logical clock instant 2026-08-05T12:00:00Z, got "
        f"{record['check_in_utc']!r}"
    )
    assert record["points_awarded"] == 10, (
        "a first check-in of the week with no prior streak days awards the 10-point "
        f"candidate, got {record['points_awarded']!r}"
    )
    assert record["points_capped"] is False, (
        "10 points sits well inside the 60-point weekly headroom, so points_capped is false"
    )
    assert record["streak_bonus_applied"] is False, (
        "no prior distinct check-in days, so the streak bonus is not earned"
    )

    scenarios.void_participation(scenario, created["id"])
    voided = validate_success(
        api_client.get_participation_record(created["id"], scenario["manager_headers"])
    )
    assert voided["status"] == "VOIDED", (
        f"the correction moves the record to VOIDED, got {voided['status']!r}"
    )
    assert "version" not in voided, (
        "voiding must not introduce a version field, got "
        f"{voided.get('version')!r}"
    )
    assert "updated_at" not in voided, (
        "voiding must not introduce an updated_at field, got "
        f"{voided.get('updated_at')!r}"
    )


def test_session_creation_with_unresolvable_offering_reports_offering_not_found(active_contract):
    """PRD §2.6: "Body-level foreign keys are checked after the request's shape
    has been validated, so a syntactically malformed identifier yields
    `ERR_INVALID_REQUEST` (HTTP 400) while a well-formed identifier that matches
    no row yields the appropriate 404."

    PRD §2.6: "This body-level referential check applies when creating a staff
    member, a staff credential, a facility room, a facility asset, a program
    offering, a program session, a staffing assignment, a member, a participation
    record, an incident report, and a monthly invoice."

    PRD §3.5: "A **program session** is one occurrence of an offering in one room
    at one time."

    Design: Corner/entities/create_session_with_unknown_offering_returns_not_found
    """
    scenario = active_contract
    room = scenarios.add_room(scenario, room_name="Studio A")

    response = api_client.create_program_session(
        program_session_payload(
            NON_EXISTENT_UUID,
            room["id"],
            scheduled_start_utc="2026-08-05T12:00:00Z",
            scheduled_end_utc="2026-08-05T12:55:00Z",
            forecast_attendance=3,
        ),
        scenario["manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_OFFERING_NOT_FOUND.value)

    _items, meta = validate_paginated(
        api_client.list_program_sessions(
            scenario["manager_headers"], params={"room_id": room["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected schedule must persist nothing, got {meta['total_count']} sessions"
    )


def test_asset_registration_with_room_from_another_contract_is_cross_contract(clock):
    """PRD §2.6: "Whenever a request references several entities at once, every
    one of them must belong to the same contract: the room and the offering when a
    session is scheduled, the staff member and the session when an assignment is
    created, the member and the session at check-in, the member and the asset
    named on an incident report, and the room when an asset is registered."

    PRD §2.6: "A mismatch is rejected with `ERR_CROSS_CONTRACT_REFERENCE` (HTTP
    422)."

    PRD §3.3: "Equipment and defibrillators are registered as assets against a
    `contract_id` and a `room_id`, where the room must belong to the same
    contract."

    PRD §3.3: "A newly registered asset is `IN_SERVICE` with
    `out_of_service_since` null and `out_of_service_days_current_period` at 0, and
    its `readiness_status` is computed on the spot."

    PRD §3.3: "Otherwise, if the earlier of `pad_expiry_on` and
    `battery_expiry_on` falls at or before 30 days from today, it is
    `PADS_EXPIRING`. Otherwise it is `READY`."

    Design: Corner/entities/facility_asset_room_from_another_contract_rejected
    """
    contract_a = scenarios.create_draft_contract("COST_PLUS")
    contract_b = scenarios.create_draft_contract("MANAGEMENT_FEE")
    assert contract_a["site_code"] != contract_b["site_code"], (
        "the two sites must carry distinct site codes for this scenario to be meaningful"
    )

    room_a = validate_success(
        api_client.create_facility_room(
            facility_room_payload(contract_a["id"], room_name="Studio A"), ADMIN
        ),
        201,
    )

    validate_error(
        api_client.create_facility_asset(
            aed_asset_payload(contract_b["id"], room_a["id"], asset_tag="AED-01"),
            ADMIN,
        ),
        ApiErrorId.ERR_CROSS_CONTRACT_REFERENCE.value,
    )

    asset = validate_success(
        api_client.create_facility_asset(
            aed_asset_payload(contract_a["id"], room_a["id"], asset_tag="AED-01"),
            ADMIN,
        ),
        201,
    )
    assert_facility_asset(asset)
    assert asset["readiness_status"] == "READY", (
        "consumables far from expiry and an inspection 12 days old make the unit READY, "
        f"got {asset['readiness_status']!r}"
    )
    assert asset["status"] == "IN_SERVICE", (
        f"a newly registered asset is IN_SERVICE, got {asset['status']!r}"
    )
    assert asset["out_of_service_since"] is None, (
        f"out_of_service_since starts null, got {asset['out_of_service_since']!r}"
    )
    assert asset["out_of_service_days_current_period"] == 0, (
        "out_of_service_days_current_period starts at 0, got "
        f"{asset['out_of_service_days_current_period']!r}"
    )

    _items, meta = validate_paginated(
        api_client.list_facility_assets(ADMIN, params={"contract_id": contract_b["id"]})
    )
    assert meta["total_count"] == 0, (
        "the rejected registration must leave the other contract with no assets, got "
        f"{meta['total_count']}"
    )
