"""Entity-level contract: declared fields, defaults, system-owned fields, reads and listing."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ERR_CASE_NOT_FOUND,
    ERR_CE_ACTIVITY_NOT_FOUND,
    ERR_CHECKLIST_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DEVICE_NOT_FOUND,
    ERR_ECMO_RUN_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_BACKUP_DEVICE,
    ERR_INVALID_FIELD_VALUE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_PACK_NOT_FOUND,
    ERR_PERFUSIONIST_NOT_FOUND,
    ERR_PREFERENCE_CARD_NOT_FOUND,
    ERR_ROTATION_SLOT_NOT_FOUND,
    ERR_SURGEON_NOT_FOUND,
    NON_EXISTENT_UUID,
    TECH_HEADERS,
    api_client,
    assert_common_fields,
    assert_event_log_fields,
    assert_line_codes_ascending,
    assert_pack_line,
    assert_pagination_meta,
    assert_single_resource_meta,
    assert_success_envelope,
    base_setup,
    build_bypass_case,
    build_ce_activity,
    build_certification,
    build_minimal_hospital_contract,
    build_pack_configuration,
    build_perfusion_device,
    build_preference_card,
    build_pump_checklist,
    create_contract,
    create_device,
    create_perfusionist,
    create_slot,
    create_surgeon,
    make_biomed_tech_headers,
    make_chief_perfusionist_headers,
    make_perfusionist_headers,
    make_surgeon_headers,
    staffed_setup,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_contract_creation_returns_declared_fields_with_system_defaults():
    """Registering a contract with only its required terms returns the whole row.

    PRD 3.1: A freshly registered contract starts commercially inert. Its `coverage_posture` initialises to `UNCOVERED`, because no rotation slot exists yet to cover anything; its `accrued_case_fee_cents` and `accrued_case_count` both start at 0; and its `last_settlement_period` starts as null, a string in four-digit-year-then-two-digit-month form once the first settlement has run.

    Design: Corner/entities/contract_creation_returns_declared_fields_with_system_defaults
    """
    response = api_client.create_hospital_contract(
        build_minimal_hospital_contract(
            hospital_name="St Aldate Cardiac Center",
            staffing_model="COVERAGE_PLUS_PER_CASE",
            per_case_fee_cents=400000,
            ecmo_hourly_fee_cents=90000,
            monthly_case_cap=5,
        ),
        ADMIN_HEADERS,
    )
    contract = validate_success(response, 201)
    assert_success_envelope(response, "object")

    assert contract["hospital_name"] == "St Aldate Cardiac Center"
    assert contract["staffing_model"] == "COVERAGE_PLUS_PER_CASE"
    assert contract["per_case_fee_cents"] == 400000
    assert contract["ecmo_hourly_fee_cents"] == 90000
    assert contract["monthly_case_cap"] == 5

    assert contract["accrued_case_fee_cents"] == 0
    assert contract["accrued_case_count"] == 0
    assert contract["coverage_posture"] == "UNCOVERED"
    assert contract["last_settlement_period"] is None

    assert_common_fields(contract, expected_version=1)


def test_omitted_optional_inputs_take_their_declared_defaults():
    """Every optional input that is omitted comes back holding its documented default.

    PRD 3.1: Five further terms are optional at registration and take documented defaults when omitted.

    PRD 3.1: A commissioned device begins `AVAILABLE`, with `runtime_hours_since_service` and `alarm_count_since_service` at 0, `open_reservation_count` at 0, and `last_service_completed_at` null until its first service is recorded.

    PRD 3.1: A newly onboarded perfusionist has `ce_credits_verified`, `ce_credits_pending`, `readiness_score`, `consecutive_case_count_24h` and `ecmo_hours_rolling_7d` all at 0, and `readiness_variant_last` null.

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    contract = validate_success(
        api_client.create_hospital_contract(
            build_minimal_hospital_contract(
                hospital_name="Brackenridge Heart Institute",
                staffing_model="PER_CASE",
                per_case_fee_cents=380000,
                ecmo_hourly_fee_cents=85000,
                monthly_case_cap=4,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert contract["monthly_coverage_fee_cents"] == 0
    assert contract["prolonged_surcharge_pct"] == pytest.approx(0.15, abs=0.0001)
    assert contract["prolonged_pump_threshold_minutes"] == 180
    assert contract["disposable_markup_pct"] == pytest.approx(0.20, abs=0.0001)
    assert contract["disposable_discount_pct"] == pytest.approx(0.0, abs=0.0001)

    surgeon = validate_success(
        api_client.create_surgeon(
            {
                "full_name": "Dr Imani Cole",
                "npi_code": "NPI-3300110",
                "specialty": "ADULT_CARDIAC",
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    assert surgeon["status"] == "ACTIVE"

    device = validate_success(
        api_client.create_perfusion_device(
            {
                "contract_id": contract["id"],
                "asset_tag": "HLM-010",
                "device_class": "HEART_LUNG_MACHINE",
            },
            TECH_HEADERS,
        ),
        201,
    )
    assert device["service_interval_hours"] == 500
    assert device["status"] == "AVAILABLE"
    assert device["backup_device_id"] is None
    assert device["runtime_hours_since_service"] == pytest.approx(0, abs=0.01)
    assert device["alarm_count_since_service"] == 0
    assert device["open_reservation_count"] == 0
    assert device["last_service_completed_at"] is None

    perfusionist = validate_success(
        api_client.create_perfusionist(
            {"full_name": "Ada Nwosu", "employee_code": "EMP-2001"}, ADMIN_HEADERS
        ),
        201,
    )
    assert perfusionist["employment_status"] == "ACTIVE"
    assert perfusionist["is_chief"] is False
    assert perfusionist["ecmo_privileged"] is False
    assert perfusionist["career_case_count"] == 0
    assert perfusionist["ce_credits_verified"] == pytest.approx(0, abs=0.01)
    assert perfusionist["ce_credits_pending"] == pytest.approx(0, abs=0.01)
    assert perfusionist["readiness_score"] == pytest.approx(0.0, abs=0.001)
    assert perfusionist["readiness_variant_last"] is None
    assert perfusionist["consecutive_case_count_24h"] == 0
    assert perfusionist["ecmo_hours_rolling_7d"] == pytest.approx(0, abs=0.01)

    card = validate_success(
        api_client.create_preference_card(
            {
                "surgeon_id": surgeon["id"],
                "procedure_type": "CABG",
                "standard_pump_minutes": 150,
                "prime_volume_ml": 1500,
                "pack_line_items": [
                    {"line_code": "A_OXYGENATOR", "quantity": 1, "unit_cost_cents": 1000}
                ],
                "required_safety_check_codes": ["ACT_BASELINE"],
                "blood_management_protocol": "STANDARD",
                "min_hematocrit_pct": 22,
            },
            make_surgeon_headers(surgeon["id"]),
        ),
        201,
    )
    assert card["revision"] == 1
    assert card["status"] == "ACTIVE"


def test_case_creation_extra_field_bypass_status_is_ignored_input():
    """Posting server-owned fields on a case creation changes nothing about the row.

    PRD 3.4: A newly scheduled case is almost entirely empty. Its clinical dimension `bypass_status` starts at `SCHEDULED` and its fiscal dimension `billing_status` starts at `UNBILLED`, independently, as §2.9 requires.

    PRD 2.4: Identifiers never carry a type prefix and are never supplied by the client.

    Design: Corner/entities/case_creation_extra_field_bypass_status_is_ignored_input
    """
    env = base_setup(with_case=False)

    payload = build_bypass_case(env["contract"]["id"], env["surgeon"]["id"])
    payload.update(
        {
            "bypass_status": "ON_BYPASS",
            "billing_status": "FINAL_ACCRUED",
            "assigned_perfusionist_id": env["p1"]["id"],
            "accrued_fee_cents": 999999,
            "version": 47,
        }
    )
    case = validate_success(
        api_client.create_bypass_case(payload, env["chief_headers"]), 201
    )

    assert case["bypass_status"] == "SCHEDULED"
    assert case["billing_status"] == "UNBILLED"
    assert case["assigned_perfusionist_id"] is None
    assert case["primary_device_id"] is None
    assert case["backup_device_id"] is None
    assert case["accrued_fee_cents"] == 0
    assert case["provisional_fee_cents"] is None
    assert case["final_fee_cents"] is None
    assert case["readiness_flag"] == "NONE"
    assert case["setup_verified_at"] is None
    assert case["adverse_event_count"] == 0
    assert case["version"] == 1

    contract = validate_success(
        api_client.get_hospital_contract(env["contract"]["id"], ADMIN_HEADERS)
    )
    assert contract["accrued_case_count"] == 0


def test_pack_cost_cents_is_server_computed_extra_field_ignored():
    """The pack's money, lines, pinned card and prime volume are all derived, never accepted.

    PRD 3.5: Money is assigned per line, and the rounding point is per line.

    PRD 3.5: The pack's `pack_cost_cents` is the exact sum of those already-rounded line totals — never the rounding of an unrounded sum, as §2.6 insists.

    PRD 3.5: It records `case_id`, pins the selected card as `applied_preference_card_id`, and copies the card's `prime_volume_ml` verbatim onto itself.

    Design: Corner/entities/pack_cost_cents_is_server_computed_extra_field_ignored
    """
    env = staffed_setup()

    payload = build_pack_configuration(env["d1"]["id"])
    payload.update({"pack_cost_cents": 1, "prime_volume_ml": 99, "approval_status": "APPROVED"})
    pack = validate_success(
        api_client.configure_disposable_pack(
            env["case"]["id"], payload, env["p1_headers"]
        ),
        201,
    )

    assert pack["pack_cost_cents"] == 3741
    assert len(pack["line_items"]) == 3
    assert_line_codes_ascending(pack["line_items"])
    assert_pack_line(pack["line_items"][0], "A_OXYGENATOR", 1, 1055, 1139, False)
    assert_pack_line(pack["line_items"][1], "B_TUBING_PACK", 1, 1155, 1247, False)
    assert_pack_line(pack["line_items"][2], "C_CANNULA_SET", 1, 1255, 1355, False)

    assert pack["applied_preference_card_id"] == env["card"]["id"]
    assert pack["prime_volume_ml"] == 1500
    assert pack["substitutions"] == []
    assert pack["requires_surgeon_approval"] is False
    assert pack["approval_status"] == "NOT_REQUIRED"

    case = validate_success(api_client.get_bypass_case(env["case"]["id"], ADMIN_HEADERS))
    assert case["bypass_status"] == "PACK_CONFIGURED"
    assert case["primary_device_id"] == env["d1"]["id"]
    assert case["backup_device_id"] == env["d2"]["id"]


def test_case_creation_missing_required_fields_returns_invalid_request():
    """An absent required input answers the request-shape gate, never a domain error.

    PRD 2.8: Rung 6 requires that every field an endpoint marks as required be present and non-null on all creating and updating operations, else `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/entities/case_creation_missing_required_fields_returns_invalid_request
    """
    contract = create_contract()
    surgeon = create_surgeon()
    chief = create_perfusionist(
        full_name="Nadia Oyelaran",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    chief_headers = make_chief_perfusionist_headers(chief["id"])

    validate_error(
        api_client.create_bypass_case(
            {
                "contract_id": contract["id"],
                "surgeon_id": surgeon["id"],
                "procedure_type": "CABG",
                "scheduled_start": "2026-08-02T06:00:00Z",
            },
            chief_headers,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_perfusionist({"full_name": "Ada Nwosu"}, ADMIN_HEADERS),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_call_rotation_slot(
            {
                "contract_id": contract["id"],
                "perfusionist_id": chief["id"],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-04T00:00:00Z",
            },
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    _, cases_meta = validate_paginated(api_client.list_bypass_cases(ADMIN_HEADERS))
    assert cases_meta["total_count"] == 0
    _, slots_meta = validate_paginated(api_client.list_call_rotation_slots(ADMIN_HEADERS))
    assert slots_meta["total_count"] == 0


def test_invalid_enum_and_out_of_range_values_are_rejected():
    """Enum membership, numeric bounds and array cardinality all answer the field-value gate.

    PRD 2.8: Rung 7 requires that every supplied field satisfy its declared type, enumeration membership, numeric range, string length and array-cardinality constraints, again on all creating and updating operations, else `ERR_INVALID_FIELD_VALUE` (HTTP 422).

    Design: Corner/entities/invalid_enum_and_out_of_range_values_are_rejected
    """
    env = base_setup(with_slot=False, with_case=False)
    surgeon_headers = make_surgeon_headers(env["surgeon"]["id"])

    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(
                env["contract"]["id"], env["surgeon"]["id"], acuity="SEMI_URGENT"
            ),
            env["chief_headers"],
        ),
        ERR_INVALID_FIELD_VALUE,
        422,
    )
    validate_error(
        api_client.create_ce_activity(
            env["p1"]["id"], build_ce_activity(credit_hours=25), ADMIN_HEADERS
        ),
        ERR_INVALID_FIELD_VALUE,
        422,
    )
    validate_error(
        api_client.create_preference_card(
            build_preference_card(
                env["surgeon"]["id"], procedure_type="VALVE", pack_line_items=[]
            ),
            surgeon_headers,
        ),
        ERR_INVALID_FIELD_VALUE,
        422,
    )
    validate_error(
        api_client.create_preference_card(
            build_preference_card(
                env["surgeon"]["id"], procedure_type="VALVE", min_hematocrit_pct=60
            ),
            surgeon_headers,
        ),
        ERR_INVALID_FIELD_VALUE,
        422,
    )

    perfusionist = validate_success(
        api_client.get_perfusionist(env["p1"]["id"], ADMIN_HEADERS)
    )
    assert perfusionist["ce_credits_pending"] == pytest.approx(20, abs=0.01)

    cards, cards_meta = validate_paginated(api_client.list_preference_cards(ADMIN_HEADERS))
    assert cards_meta["total_count"] == 1
    assert cards[0]["procedure_type"] == "CABG"


def test_contract_and_case_reads_return_the_persisted_row():
    """A read echoes what was persisted and never advances the version counter.

    PRD 3.1: Reading a contract returns all of it, live: the two commercial ledgers and the derived coverage posture as they stand at the moment of the read.

    PRD 2.4: Most resources additionally carry `updated_at`, in the same timestamp format, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every mutation of that resource — including mutations the resource suffers as a consequence of an operation aimed at some other resource.

    Design: Corner/entities/contract_and_case_reads_return_the_persisted_row
    """
    contract = create_contract(monthly_coverage_fee_cents=1200000)
    surgeon = create_surgeon()
    validate_success(
        api_client.create_preference_card(
            build_preference_card(surgeon["id"]), make_surgeon_headers(surgeon["id"])
        ),
        201,
    )
    perfusionist = create_perfusionist(career_case_count=150, ecmo_privileged=None)
    create_slot(contract["id"], perfusionist["id"])
    case = validate_success(
        api_client.create_bypass_case(
            build_bypass_case(contract["id"], surgeon["id"], acuity="URGENT"), ADMIN_HEADERS
        ),
        201,
    )

    first_read = api_client.get_hospital_contract(contract["id"], ADMIN_HEADERS)
    contract_read = validate_success(first_read)
    assert_success_envelope(first_read, "object")
    assert_single_resource_meta(first_read)
    assert contract_read["hospital_name"] == "St Aldate Cardiac Center"
    assert contract_read["monthly_coverage_fee_cents"] == 1200000
    assert contract_read["coverage_posture"] == "THIN"
    assert contract_read["accrued_case_fee_cents"] == 0
    assert contract_read["accrued_case_count"] == 0

    case_response = api_client.get_bypass_case(case["id"], make_surgeon_headers(surgeon["id"]))
    case_read = validate_success(case_response)
    assert_success_envelope(case_response, "object")
    assert case_read["contract_id"] == contract["id"]
    assert case_read["surgeon_id"] == surgeon["id"]
    assert case_read["procedure_type"] == "CABG"
    assert case_read["scheduled_start"] == "2026-08-02T06:00:00Z"
    assert case_read["scheduled_end"] == "2026-08-02T12:00:00Z"
    assert case_read["acuity"] == "URGENT"
    assert case_read["bypass_status"] == "SCHEDULED"
    assert case_read["billing_status"] == "UNBILLED"

    second_read = validate_success(
        api_client.get_hospital_contract(contract["id"], ADMIN_HEADERS)
    )
    assert second_read["version"] == contract_read["version"]
    assert second_read["updated_at"] == contract_read["updated_at"]


def test_case_list_paginates_filters_and_rejects_bad_pagination():
    """The case collection windows its rows, counts the filtered set and refuses bad bounds.

    PRD 2.3: `total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window.

    PRD 2.3: A `limit` outside the inclusive range of 1 to 100, a non-integer `limit` or `offset`, or a negative `offset` is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

    Design: Corner/entities/case_list_paginates_filters_and_rejects_bad_pagination
    """
    contract = create_contract()
    surgeon = create_surgeon()
    validate_success(
        api_client.create_preference_card(
            build_preference_card(surgeon["id"]), make_surgeon_headers(surgeon["id"])
        ),
        201,
    )
    perfusionist = create_perfusionist(career_case_count=150, ecmo_privileged=None)
    create_slot(contract["id"], perfusionist["id"])

    case_a = validate_success(
        api_client.create_bypass_case(
            build_bypass_case(contract["id"], surgeon["id"]), ADMIN_HEADERS
        ),
        201,
    )
    case_b = validate_success(
        api_client.create_bypass_case(
            build_bypass_case(
                contract["id"],
                surgeon["id"],
                scheduled_start="2026-08-02T14:00:00Z",
                scheduled_end="2026-08-02T18:00:00Z",
                acuity="URGENT",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    case_c = validate_success(
        api_client.create_bypass_case(
            build_bypass_case(
                contract["id"],
                surgeon["id"],
                scheduled_start="2026-08-03T06:00:00Z",
                scheduled_end="2026-08-03T12:00:00Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api_client.list_bypass_cases(ADMIN_HEADERS, params={"contract_id": contract["id"]})
    )
    assert_pagination_meta(meta, total_count=3, has_more=False, limit=10, offset=0)
    assert {row["id"] for row in rows} == {case_a["id"], case_b["id"], case_c["id"]}

    page_one, meta_one = validate_paginated(
        api_client.list_bypass_cases(
            ADMIN_HEADERS, params={"contract_id": contract["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page_one) == 2
    assert_pagination_meta(meta_one, total_count=3, has_more=True, limit=2, offset=0)

    page_two, meta_two = validate_paginated(
        api_client.list_bypass_cases(
            ADMIN_HEADERS, params={"contract_id": contract["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page_two) == 1
    assert_pagination_meta(meta_two, total_count=3, has_more=False, limit=2, offset=2)
    windowed = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(windowed)) == 3

    filtered, filtered_meta = validate_paginated(
        api_client.list_bypass_cases(
            ADMIN_HEADERS,
            params={
                "bypass_status": "SCHEDULED",
                "surgeon_id": surgeon["id"],
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert len(filtered) == 1
    assert filtered_meta["total_count"] == 3

    validate_error(
        api_client.list_bypass_cases(ADMIN_HEADERS, params={"limit": 0}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api_client.list_bypass_cases(ADMIN_HEADERS, params={"limit": 101}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api_client.list_bypass_cases(ADMIN_HEADERS, params={"offset": -1}),
        ERR_INVALID_PAGINATION,
        400,
    )


def test_every_entity_get_with_unknown_id_returns_its_own_not_found_code():
    """Each addressable resource answers with its own existence code, never a shared 404.

    PRD 2.8: Rungs 9 through 20 are existence checks, ordered so that path identifiers resolve before body foreign keys.

    Design: Corner/entities/every_entity_get_with_unknown_id_returns_its_own_not_found_code
    """
    seen = []
    probes = [
        (api_client.get_hospital_contract(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_CONTRACT_NOT_FOUND),
        (api_client.get_surgeon(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_SURGEON_NOT_FOUND),
        (
            api_client.get_preference_card(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_PREFERENCE_CARD_NOT_FOUND,
        ),
        (api_client.get_perfusionist(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_PERFUSIONIST_NOT_FOUND),
        (api_client.get_perfusion_device(NON_EXISTENT_UUID, TECH_HEADERS), ERR_DEVICE_NOT_FOUND),
        (
            api_client.get_call_rotation_slot(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_ROTATION_SLOT_NOT_FOUND,
        ),
        (api_client.get_bypass_case(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_CASE_NOT_FOUND),
        (api_client.get_disposable_pack(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_PACK_NOT_FOUND),
        (api_client.get_pump_checklist(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_CHECKLIST_NOT_FOUND),
        (api_client.get_ecmo_run(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_ECMO_RUN_NOT_FOUND),
        (api_client.get_incident_report(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_INCIDENT_NOT_FOUND),
    ]
    for response, expected_error_id in probes:
        error = validate_error(response, expected_error_id, 404)
        seen.append(error["error_id"])

    assert len(set(seen)) == 11


def test_device_event_log_is_append_only_and_carries_no_version():
    """Every append persists a new immutable row and the counter effects accumulate.

    PRD 2.4: A captured device event log is immutable: once appended it is never altered, so it carries only `id` and `created_at`.

    PRD 3.7: A `RUNTIME_TICK` adds its `runtime_hours_delta` to the machine's `runtime_hours_since_service`; for every other code the delta is ignored even when supplied.

    PRD 3.7: An `ALARM_CRITICAL`, an `ALARM_ADVISORY` or a `SELF_TEST_FAIL` raises the machine's `alarm_count_since_service` by one.

    Design: Corner/entities/device_event_log_is_append_only_and_carries_no_version
    """
    contract = create_contract()
    device = create_device(contract["id"])
    tech_headers = make_biomed_tech_headers("tech-op-0001")

    log_one = validate_success(
        api_client.create_device_event_log(
            device["id"],
            {"event_code": "RUNTIME_TICK", "runtime_hours_delta": 6.5, "detail": "first shift"},
            tech_headers,
        ),
        201,
    )
    log_two = validate_success(
        api_client.create_device_event_log(
            device["id"],
            {"event_code": "RUNTIME_TICK", "runtime_hours_delta": 3.5, "detail": "second shift"},
            tech_headers,
        ),
        201,
    )
    log_three = validate_success(
        api_client.create_device_event_log(
            device["id"],
            {"event_code": "ALARM_ADVISORY", "detail": "gas line advisory"},
            tech_headers,
        ),
        201,
    )

    for event in (log_one, log_two, log_three):
        assert_event_log_fields(event)
        assert event["recorded_by_user_id"] == "tech-op-0001"
    assert len({log_one["id"], log_two["id"], log_three["id"]}) == 3
    assert log_three["runtime_hours_delta"] == pytest.approx(0, abs=0.01)

    rows, meta = validate_paginated(api_client.list_device_event_logs(device["id"], tech_headers))
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {log_one["id"], log_two["id"], log_three["id"]}

    read = validate_success(api_client.get_perfusion_device(device["id"], TECH_HEADERS))
    assert read["runtime_hours_since_service"] == pytest.approx(10.0, abs=0.01)
    assert read["alarm_count_since_service"] == 1
    assert read["status"] == "AVAILABLE"


def test_child_creation_under_unknown_parent_returns_parent_not_found():
    """A nested or referenced parent resolves before any domain rule, and children stay scoped.

    PRD 2.4: Nested paths are resolved strictly from left to right, and the first unresolved segment determines the error.

    PRD 2.4: Reading the certification cycles of a perfusionist who does not exist is `ERR_PERFUSIONIST_NOT_FOUND` and never a paginated empty list; capturing an event log against a device that does not exist is `ERR_DEVICE_NOT_FOUND`; configuring a pack on a case that does not exist is `ERR_CASE_NOT_FOUND`, and only once the case has resolved does the service look at whether the machine named in the body exists.

    Design: Corner/entities/child_creation_under_unknown_parent_returns_parent_not_found
    """
    create_contract()
    p1 = create_perfusionist(career_case_count=150, ecmo_privileged=None)
    p2 = create_perfusionist(
        full_name="Ada Nwosu", employee_code="EMP-1003", career_case_count=90, ecmo_privileged=None
    )
    chief = create_perfusionist(
        full_name="Nadia Oyelaran",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    validate_success(
        api_client.create_certification(p1["id"], build_certification(), ADMIN_HEADERS), 201
    )
    ce_activity = validate_success(
        api_client.create_ce_activity(p1["id"], build_ce_activity(), ADMIN_HEADERS), 201
    )

    validate_error(
        api_client.create_certification(NON_EXISTENT_UUID, build_certification(), ADMIN_HEADERS),
        ERR_PERFUSIONIST_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_pump_checklist(
            NON_EXISTENT_UUID,
            build_pump_checklist(
                check_results=[{"check_code": "ACT_BASELINE", "passed": True, "note": "ok"}],
                hematocrit_pct=26,
            ),
            make_perfusionist_headers(p1["id"]),
        ),
        ERR_CASE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_preference_card(
            build_preference_card(NON_EXISTENT_UUID),
            make_chief_perfusionist_headers(chief["id"]),
        ),
        ERR_SURGEON_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.adjudicate_ce_activity(
            NON_EXISTENT_UUID, {"decision": "VERIFIED"}, ADMIN_HEADERS
        ),
        ERR_CE_ACTIVITY_NOT_FOUND,
        404,
    )

    _, p2_meta = validate_paginated(api_client.list_ce_activities(p2["id"], ADMIN_HEADERS))
    assert p2_meta["total_count"] == 0
    p1_rows, p1_meta = validate_paginated(api_client.list_ce_activities(p1["id"], ADMIN_HEADERS))
    assert p1_meta["total_count"] == 1
    assert p1_rows[0]["id"] == ce_activity["id"]

    assert validate_success(api_client.get_perfusionist(p2["id"], ADMIN_HEADERS))[
        "ce_credits_pending"
    ] == pytest.approx(0, abs=0.01)
    assert validate_success(api_client.get_perfusionist(p1["id"], ADMIN_HEADERS))[
        "ce_credits_pending"
    ] == pytest.approx(20, abs=0.01)


def test_device_backup_graph_edge_is_validated_and_reverse_reachable():
    """The self-referential fallback edge is policed on three conditions and reverse-reachable.

    PRD 3.1: `backup_device_id` designates a standing fallback unit — a self-reference to another device row — and may be left null; when supplied it must name a *different* row of the *same* `device_class` stationed at the *same* hospital, and a designation that breaks any of those three conditions is refused with `ERR_INVALID_BACKUP_DEVICE`.

    Design: Corner/entities/device_backup_graph_edge_is_validated_and_reverse_reachable
    """
    contract_one = create_contract()
    contract_two = create_contract(
        hospital_name="Brackenridge Heart Institute",
        staffing_model="PER_CASE",
        per_case_fee_cents=380000,
        ecmo_hourly_fee_cents=85000,
        monthly_case_cap=4,
    )
    d2 = create_device(contract_one["id"], asset_tag="HLM-002")
    other_class = create_device(
        contract_one["id"], asset_tag="CSV-001", device_class="CELL_SAVER"
    )
    d9 = create_device(contract_two["id"], asset_tag="HLM-009")

    d1 = validate_success(
        api_client.create_perfusion_device(
            build_perfusion_device(
                contract_one["id"], asset_tag="HLM-001", backup_device_id=d2["id"]
            ),
            TECH_HEADERS,
        ),
        201,
    )
    assert d1["backup_device_id"] == d2["id"]

    validate_error(
        api_client.create_perfusion_device(
            build_perfusion_device(
                contract_one["id"], asset_tag="HLM-003", backup_device_id=d9["id"]
            ),
            TECH_HEADERS,
        ),
        ERR_INVALID_BACKUP_DEVICE,
        422,
    )
    validate_error(
        api_client.create_perfusion_device(
            build_perfusion_device(
                contract_one["id"], asset_tag="HLM-004", backup_device_id=other_class["id"]
            ),
            TECH_HEADERS,
        ),
        ERR_INVALID_BACKUP_DEVICE,
        422,
    )
    validate_error(
        api_client.create_perfusion_device(
            build_perfusion_device(
                contract_one["id"], asset_tag="HLM-005", backup_device_id=NON_EXISTENT_UUID
            ),
            TECH_HEADERS,
        ),
        ERR_DEVICE_NOT_FOUND,
        404,
    )

    reverse, reverse_meta = validate_paginated(
        api_client.list_perfusion_devices(TECH_HEADERS, params={"backup_device_id": d2["id"]})
    )
    assert reverse_meta["total_count"] == 1
    assert reverse[0]["id"] == d1["id"]

    machines, machines_meta = validate_paginated(
        api_client.list_perfusion_devices(
            TECH_HEADERS,
            params={
                "contract_id": contract_one["id"],
                "device_class": "HEART_LUNG_MACHINE",
                "status": "AVAILABLE",
            },
        )
    )
    assert machines_meta["total_count"] == 2
    assert {row["id"] for row in machines} == {d1["id"], d2["id"]}
