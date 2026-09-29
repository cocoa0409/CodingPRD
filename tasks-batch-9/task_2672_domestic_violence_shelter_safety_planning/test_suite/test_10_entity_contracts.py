"""Entity-level contracts: what a create stores, what a read returns, how a list pages,
and which shapes the server refuses outright.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    assert_bed_ledger_invariant,
    assert_client,
    assert_hotline_call,
    assert_meta_envelope,
    assert_risk_assessment,
    assert_timestamp_with_millis,
    get_success_data,
    is_valid_uuid,
    make_hotline_advocate_headers,
    seed_client,
    seed_hotline_advocate,
    seed_hotline_call,
    seed_shelter,
    seed_shelter_manager,
    seed_unit,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_CLIENT_ID = "2f4d0000-0000-4000-8000-000000000001"
UNKNOWN_PLAN_ID = "2f4d0000-0000-4000-8000-000000000009"
UNKNOWN_SHELTER_ID = "2f4d0000-0000-4000-8000-00000000000b"
STARTUP_CLOCK = "2026-08-01T00:00:00.000Z"
MODERATE_FACTOR_PAYLOAD = {
    "weapon_access": True,
    "strangulation_history": False,
    "separation_recent": True,
    "threats_to_kill": False,
    "stalking_frequency_per_week": 2,
}


def test_client_create_echoes_every_input_and_initialises_every_computed_field():
    """All seven inputs come back verbatim and all six computed fields take their launch values.

    PRD: "A newly opened record starts with `status` `INTAKE`, `confidentiality_posture`
    `NORMAL`, `current_danger_score` null, `current_risk_band` null, `protective_order_active`
    false, `resource_referral_count` 0 and `version` 1."

    Design: Corner/entities/client_creation_populates_every_declared_field
    """
    advocate = seed_hotline_advocate("Rosa Marin")

    response = api_client.create_client(
        {
            "client_code": "C-1001",
            "legal_name": "Alina Ford",
            "household_size": 4,
            "minor_children_count": 2,
            "accessibility_required": False,
            "location_confidential": True,
            "hmis_disclosure_consent": "DENIED",
        },
        advocate.headers,
    )

    client = validate_success(response, 201)
    body = response.json()
    assert_meta_envelope(body)
    assert body["response_type"] == "object"
    assert client["client_code"] == "C-1001"
    assert client["legal_name"] == "Alina Ford"
    assert client["household_size"] == 4
    assert client["minor_children_count"] == 2
    assert client["accessibility_required"] is False
    assert client["location_confidential"] is True
    assert client["hmis_disclosure_consent"] == "DENIED"
    assert client["status"] == "INTAKE"
    assert client["confidentiality_posture"] == "NORMAL"
    assert client["current_danger_score"] is None
    assert client["current_risk_band"] is None
    assert client["protective_order_active"] is False
    assert client["resource_referral_count"] == 0
    assert client["version"] == 1
    assert is_valid_uuid(client["id"])
    assert_timestamp_with_millis(client["created_at"])
    assert client["created_at"] == client["updated_at"]
    assert_client(client)


def test_reading_a_unit_back_returns_the_stored_row_including_its_ledger():
    """The read path replays the create without recomputation drift.

    PRD: "A new unit begins with `reserved_beds` 0, `occupied_beds` 0, `available_beds` equal
    to its `bed_capacity`, `status` `AVAILABLE` and `version` 1; adding it re-derives the
    owning facility's roll-up counters and posture and increments the facility's `version` by
    1."

    Design: Corner/entities/shelter_unit_retrieval_returns_the_stored_row
    """
    manager = seed_shelter_manager("Dana Whit")
    shelter = seed_shelter(
        manager,
        name="Cedar House",
        confidential_location=True,
        nightly_rate_cents=8500,
        weekend_surcharge_cents=2500,
        child_supplement_cents=1200,
    )
    unit = seed_unit(manager, shelter["id"], unit_label="A1", unit_type="FAMILY_SUITE", bed_capacity=4)

    response = api_client.get_shelter_unit(unit["id"], manager.headers)

    stored = validate_success(response, 200)
    assert stored["id"] == unit["id"]
    assert stored["shelter_id"] == shelter["id"]
    assert stored["unit_label"] == "A1"
    assert stored["unit_type"] == "FAMILY_SUITE"
    assert stored["bed_capacity"] == 4
    assert stored["reserved_beds"] == 0
    assert stored["occupied_beds"] == 0
    assert stored["available_beds"] == 4
    assert stored["status"] == "AVAILABLE"
    assert stored["version"] == 1
    assert stored["updated_at"] == stored["created_at"]
    assert_bed_ledger_invariant(stored)


def test_hotline_call_pages_report_the_filtered_total_not_the_page_size():
    """Three calls across two pages of two: total_count stays 3 and has_more flips to false.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside
    the `meta` object of the envelope, where `total_count` reflects the size of the full
    filtered result set rather than the size of the returned page."

    Design: Corner/entities/hotline_call_listing_paginates_with_total_count_and_has_more
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate,
        client_code="C-1002",
        legal_name="Bea Lang",
        household_size=2,
        minor_children_count=0,
    )
    created = [
        seed_hotline_call(
            advocate,
            client["id"],
            caller_type=caller_type,
            presenting_concerns=concerns,
        )["id"]
        for caller_type, concerns in (
            ("SURVIVOR", "First contact, asking what options exist."),
            ("FAMILY_MEMBER", "Sister calling on her behalf."),
            ("PROFESSIONAL_REFERRAL", "Clinic nurse referring the survivor."),
        )
    ]

    first_rows, first_meta = validate_paginated(
        api_client.list_hotline_calls(
            advocate.headers, params={"client_id": client["id"], "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_hotline_calls(
            advocate.headers, params={"client_id": client["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2
    paged = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert sorted(paged) == sorted(created)
    assert len(set(paged)) == 3
    for row in first_rows + second_rows:
        assert row["status"] == "RECEIVED"
        assert row["taken_by_staff_id"] == advocate.id
        assert row["received_at_utc"] == STARTUP_CLOCK
        assert_hotline_call(row)


def test_unknown_client_id_is_a_not_found_error_envelope():
    """A well-formed UUID matching no row is a 404, not an empty success.

    PRD: "Identifiers embedded in a URL path are resolved strictly left to right, and the
    first one that names no existing row terminates the request with a 404 carrying the error
    specific to that row's type."

    Design: Corner/entities/get_client_with_unknown_id_returns_not_found
    """
    advocate = seed_hotline_advocate("Rosa Marin")

    response = api_client.get_client(UNKNOWN_CLIENT_ID, advocate.headers)

    error = validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)
    assert isinstance(error["message"], str) and error["message"].strip()
    assert set(error.keys()) == {"error_id", "message"}
    assert response.json()["response_type"] == "error"


def test_client_create_without_household_size_is_a_request_shape_failure():
    """household_size has no default, so omitting it is refused and stores nothing.

    PRD: "A `HotlineAdvocate` — or an `AgencyAdmin` doing back-office cleanup — opens one by
    supplying a pseudonymous `client_code` of between 3 and 40 characters, a `legal_name` of
    between 1 and 120 characters, and a `household_size` between 1 and 12 counting the
    survivor plus every dependent who would need a bed."

    Design: Corner/entities/client_create_missing_required_household_size_returns_invalid_request
    """
    advocate = seed_hotline_advocate("Rosa Marin")

    refused = api_client.create_client(
        {"client_code": "C-1003", "legal_name": "Cara Vex"}, advocate.headers
    )

    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    retry = api_client.create_client(
        {"client_code": "C-1003", "legal_name": "Cara Vex", "household_size": 3},
        advocate.headers,
    )
    created = validate_success(retry, 201)
    assert is_valid_uuid(created["id"])
    assert created["household_size"] == 3
    assert created["version"] == 1


def test_omitted_optional_inputs_resolve_to_their_declared_defaults():
    """Every optional input with a declared default lands on exactly that default.

    PRD: "An `AgencyAdmin` registers a staff member with a `full_name` of between 1 and 120
    characters, a `role_type` drawn from `HOTLINE_ADVOCATE`, `SHELTER_MANAGER`,
    `LEGAL_ADVOCATE`, `HOUSING_SPECIALIST` and `PRIVACY_OFFICER`, and an optional
    `max_caseload` ceiling on the number of concurrent approved screenings the member may
    hold, defaulting to 8 and accepted between 1 and 50."

    PRD: "A facility with no units at all therefore has `total_bed_capacity` 0,
    `available_beds` 0 and `capacity_posture` `FULL` — a freshly opened shelter is full until
    somebody adds a room."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    staff = validate_success(
        api_client.create_staff_member(
            {"full_name": "Rosa Marin", "role_type": "HOTLINE_ADVOCATE"}, ADMIN_HEADERS
        ),
        201,
    )
    assert staff["max_caseload"] == 8
    assert staff["active_caseload_count"] == 0
    assert staff["secondary_trauma_index"] == 0.0
    assert staff["wellness_posture"] == "OPEN"
    assert staff["last_wellness_check_at"] is None

    client = validate_success(
        api_client.create_client(
            {"client_code": "C-1004", "legal_name": "Dana Pell", "household_size": 2},
            make_hotline_advocate_headers(staff["id"]),
        ),
        201,
    )
    assert client["minor_children_count"] == 0
    assert client["accessibility_required"] is False
    assert client["location_confidential"] is True
    assert client["hmis_disclosure_consent"] == "DENIED"

    shelter = validate_success(
        api_client.create_shelter(
            {"name": "Birch House", "nightly_rate_cents": 8500}, ADMIN_HEADERS
        ),
        201,
    )
    assert shelter["confidential_location"] is True
    assert shelter["weekend_surcharge_cents"] == 0
    assert shelter["child_supplement_cents"] == 0
    assert shelter["total_bed_capacity"] == 0
    assert shelter["available_beds"] == 0
    assert shelter["capacity_posture"] == "FULL"


def test_submitted_risk_scores_are_discarded_in_favour_of_the_formula():
    """A body carrying its own danger_score of 99.9 changes nothing: the arithmetic wins.

    PRD: "**Fourth**, `danger_score` is the `base_subtotal` multiplied by the
    `escalation_multiplier`, rounded half up to one decimal place, and then capped at 100.0 —
    the cap is applied after the rounding, never before."

    Design: Corner/entities/risk_assessment_computed_score_fields_input_ignored
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate,
        client_code="C-1005",
        legal_name="Elle Doss",
        household_size=2,
        minor_children_count=0,
    )
    call = seed_hotline_call(
        advocate,
        client["id"],
        presenting_concerns="He took the car keys and blocked the door.",
    )

    response = api_client.create_risk_assessment(
        call["id"],
        dict(
            MODERATE_FACTOR_PAYLOAD,
            corroborate_with_history=False,
            danger_score=99.9,
            risk_band="IMMINENT",
            base_subtotal=0.0,
            escalation_multiplier=3.0,
            variant_applied="CORROBORATED_REVIEW",
            corroborating_fact_count=5,
        ),
        advocate.headers,
    )

    assessment = validate_success(response, 201)
    assert assessment["base_subtotal"] == 44.0
    assert assessment["escalation_multiplier"] == 1.10
    assert assessment["danger_score"] == 48.4
    assert assessment["risk_band"] == "MODERATE"
    assert assessment["variant_applied"] == "INTAKE_SNAPSHOT"
    assert assessment["corroborating_fact_count"] == 0
    assert_risk_assessment(assessment)
    refreshed = get_success_data(api_client.get_client(client["id"], advocate.headers))
    assert refreshed["current_danger_score"] == 48.4
    assert refreshed["current_risk_band"] == "MODERATE"
    assert (
        get_success_data(api_client.get_hotline_call(call["id"], advocate.headers))["status"]
        == "RISK_ASSESSED"
    )


def test_hotline_call_identity_clock_and_status_are_server_minted():
    """The decoy staff id, the 2020 timestamp and the pre-set status are all overruled.

    PRD: "The server stamps `taken_by_staff_id` from the acting advocate's identity rather
    than accepting it from the body, sets `received_at_utc` to the logical clock reading, and
    initialises `status` to `RECEIVED` with `disposed_at` null and `version` 1."

    Design: Corner/entities/hotline_call_system_fields_are_server_minted_and_input_ignored
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    decoy = seed_hotline_advocate("Tess Okoye")
    client = seed_client(
        advocate,
        client_code="C-1006",
        legal_name="Fern Ruiz",
        household_size=2,
        minor_children_count=0,
    )

    response = api_client.create_hotline_call(
        {
            "client_id": client["id"],
            "caller_type": "SURVIVOR",
            "presenting_concerns": "Calling from a neighbour's phone.",
            "taken_by_staff_id": decoy.id,
            "received_at_utc": "2020-01-01T00:00:00Z",
            "status": "RISK_ASSESSED",
            "version": 9,
        },
        advocate.headers,
    )

    call = validate_success(response, 201)
    assert call["taken_by_staff_id"] == advocate.id
    assert call["taken_by_staff_id"] != decoy.id
    assert call["received_at_utc"] == STARTUP_CLOCK
    assert call["status"] == "RECEIVED"
    assert call["disposed_at"] is None
    assert call["version"] == 1
    assert is_valid_uuid(call["id"])


def test_client_create_enforces_its_ranges_and_its_enum_vocabulary():
    """Four differently malformed bodies all fail request-shape validation and store nothing.

    PRD: "`minor_children_count` records the dependent children under 18 who are inside
    `household_size`; it defaults to 0, may not exceed 10, and may never exceed
    `household_size` reduced by 1, because the survivor themself always occupies one place in
    the household."

    PRD: "The third value, `REVOKED`, is producible only by a later consent change and is
    refused at intake as an invalid request."

    Design: Corner/entities/client_create_rejects_out_of_range_numbers_and_unknown_enums
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    bodies = [
        {"client_code": "C-1007", "legal_name": "Gia Hall", "household_size": 0},
        {
            "client_code": "C-1007",
            "legal_name": "Gia Hall",
            "household_size": 4,
            "minor_children_count": 4,
        },
        {
            "client_code": "C-1007",
            "legal_name": "Gia Hall",
            "household_size": 4,
            "hmis_disclosure_consent": "MAYBE",
        },
        {
            "client_code": "C-1007",
            "legal_name": "Gia Hall",
            "household_size": 4,
            "hmis_disclosure_consent": "REVOKED",
        },
    ]

    for body in bodies:
        validate_error(
            api_client.create_client(body, advocate.headers),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    accepted = validate_success(
        api_client.create_client(
            {
                "client_code": "C-1007",
                "legal_name": "Gia Hall",
                "household_size": 4,
                "minor_children_count": 3,
            },
            advocate.headers,
        ),
        201,
    )
    assert accepted["minor_children_count"] == 3
    assert accepted["hmis_disclosure_consent"] == "DENIED"


def test_a_risk_assessment_carries_no_version_and_no_updated_at():
    """The append-only scoring event exposes id and created_at and nothing else from the triple.

    PRD: "A `RiskAssessment` likewise carries only `id` and `created_at`, with no `updated_at`
    and no `version` — an assessment is a point-in-time reading and is never revised."

    Design: Corner/entities/risk_assessment_is_immutable_and_carries_no_version_field
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate,
        client_code="C-1008",
        legal_name="Hana Ives",
        household_size=2,
        minor_children_count=0,
    )
    call = seed_hotline_call(
        advocate,
        client["id"],
        presenting_concerns="Threats escalated after she filed for separation.",
    )

    created = validate_success(
        api_client.create_risk_assessment(
            call["id"], dict(MODERATE_FACTOR_PAYLOAD), advocate.headers
        ),
        201,
    )

    assert "version" not in created
    assert "updated_at" not in created
    assert is_valid_uuid(created["id"])
    assert_timestamp_with_millis(created["created_at"])
    rows, meta = validate_paginated(
        api_client.list_risk_assessments(call["id"], advocate.headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0] == created


def test_a_component_under_an_unknown_plan_reports_the_plan_as_missing():
    """The parent path id is resolved first, so the component is never looked for.

    PRD: "Requesting a component under a plan that does not exist yields
    `ERR_SAFETY_PLAN_NOT_FOUND`, never `ERR_PLAN_COMPONENT_NOT_FOUND`; the server does not
    look for the component at all."

    Design: Corner/entities/plan_component_create_under_unknown_plan_returns_not_found
    """
    advocate = seed_hotline_advocate("Rosa Marin")

    response = api_client.create_plan_component(
        UNKNOWN_PLAN_ID,
        {
            "component_type": "RELOCATION",
            "detail": "Move to the far side of the county.",
            "target_completion_date": "2026-08-25",
        },
        advocate.headers,
    )

    validate_error(response, ApiErrorId.ERR_SAFETY_PLAN_NOT_FOUND.value, 404)
    rows, meta = validate_paginated(
        api_client.list_safety_plans(advocate.headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_body_foreign_keys_are_resolved_in_their_declared_order():
    """The unknown client is reported first; fixing it surfaces the unknown shelter next.

    PRD: "Each of `client_id`, `hotline_call_id`, `based_on_risk_assessment_id`,
    `requested_shelter_id`, `shelter_unit_id`, `new_shelter_unit_id`, `screening_request_id`,
    `landlord_partner_id`, `assigned_advocate_id`, `accompanying_advocate_id`,
    `requested_by_staff_id` and `staff_member_id` must resolve to an existing row, and each
    reports the 404 error belonging to its own entity type: `ERR_CLIENT_NOT_FOUND`,
    `ERR_HOTLINE_CALL_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_SHELTER_NOT_FOUND`,
    `ERR_SHELTER_UNIT_NOT_FOUND`, `ERR_SCREENING_REQUEST_NOT_FOUND`,
    `ERR_LANDLORD_PARTNER_NOT_FOUND` and `ERR_STAFF_MEMBER_NOT_FOUND` respectively."

    Design: Corner/entities/screening_request_body_foreign_keys_resolved_left_to_right_not_found
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate,
        client_code="C-1009",
        legal_name="Ida Kerr",
        household_size=2,
        minor_children_count=0,
    )
    call = seed_hotline_call(advocate, client["id"], presenting_concerns="Needs a bed tonight.")
    get_success_data(
        api_client.create_risk_assessment(call["id"], dict(MODERATE_FACTOR_PAYLOAD), advocate.headers)
    )

    both_unknown = api_client.create_screening_request(
        {
            "client_id": UNKNOWN_CLIENT_ID,
            "hotline_call_id": call["id"],
            "requested_shelter_id": UNKNOWN_SHELTER_ID,
            "requested_entry_date": "2026-08-07",
        },
        advocate.headers,
    )
    shelter_unknown = api_client.create_screening_request(
        {
            "client_id": client["id"],
            "hotline_call_id": call["id"],
            "requested_shelter_id": UNKNOWN_SHELTER_ID,
            "requested_entry_date": "2026-08-07",
        },
        advocate.headers,
    )

    validate_error(both_unknown, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)
    validate_error(shelter_unknown, ApiErrorId.ERR_SHELTER_NOT_FOUND.value, 404)
    rows, meta = validate_paginated(
        api_client.list_screening_requests(advocate.headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert rows == []
