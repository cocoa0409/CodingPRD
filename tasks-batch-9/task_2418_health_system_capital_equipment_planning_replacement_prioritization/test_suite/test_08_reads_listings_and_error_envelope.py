"""Read paths: windowed listings, entity-specific 404s and one uniform error envelope."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_append_only_record,
    assert_cents,
    assert_decimal,
    assert_error_envelope_shape,
    assert_priority_score,
    create_request_payload,
    get_success_data,
    make_asset,
    make_clinical_requester_headers,
    make_cycle,
    make_department,
    make_facility,
    make_request,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    score_rows,
    setup_intake_open_cycle,
    setup_scored_request,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _three_draft_requests_on_one_asset():
    """One CT scanner carries three DRAFT requests: the sibling bar only bites at submit."""
    ctx = setup_intake_open_cycle()
    ctx["requests"] = [
        make_request(
            ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"],
            clinical_justification=(
                f"Option {label}: CT replacement, ageing detector array."
            ),
        )
        for label in ("A", "B", "C")
    ]
    return ctx


def _estate_with_a_draft_cycle():
    """Facility NRH, a CT department, the CT scanner and a cycle still in DRAFT."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-8", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    return {"facility": facility, "department": department, "asset": asset, "cycle": cycle}


# ─── Windowed listings ────────────────────────────────────────────────


def test_three_draft_requests_page_two_at_a_time_in_creation_order(api):
    """PRD §2.3: "Rows are always returned sorted by `created_at` ascending."
    PRD §2.3: "Any filters an endpoint declares are combined with logical AND and applied
    before sorting, and the sorted result is then windowed by `offset` and `limit`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`
    (the number of rows matching the filters before windowing) and `has_more` (true when rows
    remain beyond the current window)."
    PRD §3.4: "Requests can be listed filtered by `cycle_id`, `department_id`, `asset_id`,
    `sponsor_member_id`, `status` and `expedited`."
    PRD §3.4: "The request is born in `DRAFT` with all four priority drivers at 0.00,
    `composite_score` 0.00, `expedited` false, `revision_count` 0, `return_count` 0 and
    `funded_amount_cents` 0."

    Design: Corner/entities/list_requests_filters_by_status_and_paginates_created_at_ascending
    """
    ctx = _three_draft_requests_on_one_asset()
    expected_ids = [request["id"] for request in ctx["requests"]]
    query = {"cycle_id": ctx["cycle"]["id"], "status": "DRAFT", "limit": 2}

    first_rows, first_meta = validate_paginated(
        api.list_requests(_PLANNER, params={**query, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert [row["id"] for row in first_rows] == expected_ids[:2]

    second_rows, second_meta = validate_paginated(
        api.list_requests(_PLANNER, params={**query, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_rows[0]["id"] == expected_ids[2]

    for row in first_rows + second_rows:
        assert row["status"] == "DRAFT"
        assert_decimal(row["composite_score"], 0.00, "composite_score")
        assert row["revision_count"] == 0
        assert_cents(row["funded_amount_cents"], 0, "funded_amount_cents")


def test_a_window_wider_than_a_hundred_rows_is_refused_rather_than_clamped(api):
    """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` below 1, a `limit` above 100, an `offset` below 0, or either parameter
    supplied as anything other than an integer is rejected with `ERR_VALIDATION` (HTTP 422)."
    PRD §2.11: "8. Pagination parameters outside their bounds, on every list endpoint —
    `ERR_VALIDATION`, 422."

    Design: Corner/entities/list_facilities_with_limit_above_hundred_returns_422
    """
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )

    validate_error(
        api.list_facilities(_PLANNER, params={"limit": 101}),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )
    validate_error(
        api.list_facilities(_PLANNER, params={"limit": 0}),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )

    rows, meta = validate_paginated(api.list_facilities(_PLANNER, params={"limit": 100}))
    assert len(rows) == 1
    assert rows[0]["id"] == facility["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_the_score_history_keeps_the_superseded_row_and_the_request_mirrors_the_newest(api):
    """PRD §3.1: "A planner may later edit `model_name`, `install_date`,
    `expected_life_years`, `oem_support_end_date` and `acquisition_cost_cents`; every such edit
    re-runs the scoring, re-applies the derate gate, and re-scores any replacement request of
    that asset that is currently `SCORED`, appending a fresh score row whose `reason` is
    `ASSET_CONDITION_CHANGE`."
    PRD §3.5: "Each scoring produces an immutable score row rather than overwriting history."
    PRD §3.5: "The request's own `safety_driver`, `growth_driver`, `regulatory_driver`,
    `eos_driver`, `composite_score` and `expedited` always mirror the row with the highest
    `sequence`, which is the authoritative score."
    PRD §3.5: "The score history of a request is readable in `created_at` ascending order and
    can be filtered by `reason`."
    PRD §3.5: "The **safety driver** is one hundred less the asset's `adjusted_ruls_score`,
    multiplied by seventy-five hundredths, plus four points for every corrective service event
    in the asset's trailing two-year window, the sum rounded half up to two decimals and then
    capped at 100.00."

    Design: Corner/endpoints/the_score_history_sub_resource_is_append_only_with_the_highest_sequence_authoritative
    """
    ctx = setup_scored_request()

    validate_success(api.patch_asset(ctx["asset"]["id"], {"expected_life_years": 10}, _PLANNER))
    after_asset = refresh_asset(ctx["asset"]["id"])
    assert_decimal(after_asset["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(after_asset["adjusted_ruls_score"], 40.00, "adjusted_ruls_score")
    assert after_asset["status"] == "IN_SERVICE"

    history = get_success_data(api.list_request_scores(ctx["request"]["id"], _AUDITOR))
    assert len(history) == 2
    first, second = history
    for row in history:
        assert_priority_score(row)
        assert_append_only_record(row, "score row")

    assert first["sequence"] == 1
    assert first["reason"] == "CYCLE_SCORING"
    assert_decimal(first["asset_adjusted_ruls_snapshot"], 25.00, "asset_adjusted_ruls_snapshot")
    assert_decimal(first["safety_driver"], 56.25, "safety_driver")
    assert_decimal(first["composite_score"], 39.69, "composite_score")

    assert second["sequence"] == 2
    assert second["reason"] == "ASSET_CONDITION_CHANGE"
    assert_decimal(second["asset_adjusted_ruls_snapshot"], 40.00, "asset_adjusted_ruls_snapshot")
    assert_decimal(second["safety_driver"], 45.00, "safety_driver")
    assert_decimal(second["growth_driver"], 100.00, "growth_driver")
    assert_decimal(second["composite_score"], 35.75, "composite_score")

    cycle_scoring_only = get_success_data(
        api.list_request_scores(ctx["request"]["id"], _AUDITOR, params={"reason": "CYCLE_SCORING"})
    )
    assert len(cycle_scoring_only) == 1
    assert cycle_scoring_only[0]["sequence"] == 1

    mirrored = validate_success(api.get_request(ctx["request"]["id"], _AUDITOR))
    assert_decimal(mirrored["safety_driver"], 45.00, "safety_driver")
    assert_decimal(mirrored["composite_score"], 35.75, "composite_score")
    assert mirrored["expedited"] is False
    assert mirrored["status"] == "SCORED"

    assert len(score_rows(ctx["request"]["id"])) == 2
    after_cycle = refresh_cycle(ctx["cycle"]["id"])
    assert after_cycle["status"] == "SCORING"
    assert after_cycle["scored_count"] == 1


# ─── One absent identifier, eleven different answers ──────────────────


def test_the_same_absent_identifier_names_a_different_entity_on_every_read(api):
    """PRD §2.7: "Path parameters are resolved strictly left to right, and the first identifier
    that resolves to no row terminates the request with that entity's own not-found error:
    `ERR_FACILITY_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_GPO_CONTRACT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND` or `ERR_AUDIT_NOT_FOUND`, each at HTTP 404."
    PRD §2.11: "3. A templated path identifier that resolves to no row — that entity's
    not-found error, 404."

    Design: Corner/entities/unknown_uuid_on_every_get_by_id_returns_entity_specific_not_found
    """
    pin_clock(CLOCK)

    reads = (
        (api.get_facility, ApiErrorId.ERR_FACILITY_NOT_FOUND),
        (api.get_department, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND),
        (api.get_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND),
        (api.get_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_asset, ApiErrorId.ERR_ASSET_NOT_FOUND),
        (api.get_request, ApiErrorId.ERR_REQUEST_NOT_FOUND),
        (api.get_committee_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api.get_gpo_contract, ApiErrorId.ERR_GPO_CONTRACT_NOT_FOUND),
        (api.get_quote, ApiErrorId.ERR_QUOTE_NOT_FOUND),
        (api.get_installation_project, ApiErrorId.ERR_PROJECT_NOT_FOUND),
        (api.get_audit, ApiErrorId.ERR_AUDIT_NOT_FOUND),
    )

    seen = set()
    for read, error_id in reads:
        response = read(UNKNOWN_UUID, _PLANNER)
        validate_error(response, error_id.value, 404)
        assert_error_envelope_shape(response.json())
        seen.add(error_id.value)

    assert len(seen) == 11, "each read names its own entity rather than a generic not-found"


# ─── One envelope across every status class ───────────────────────────


def test_a_shape_fault_a_missing_row_a_state_fault_and_a_semantic_fault_share_one_envelope(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.11: "7. A required input absent, a field of the wrong JSON type, an enum value
    outside its declared set, a string outside its length bounds or a number outside its
    declared range, on every write endpoint — `ERR_VALIDATION`, 422."
    PRD §2.11: "14. The capital cycle not in the stage the operation requires, on every cycle
    stage transition and on request submit, screen, vote and fund — `ERR_CYCLE_INVALID_STATE`,
    409."
    PRD §2.11: "13. `regulatory_mandate_flag` true while `mandate_deadline` is null, on request
    creation, request patch and request submit — `ERR_MANDATE_DEADLINE_REQUIRED`, 422."
    PRD §2.11: "Nothing later in the order is evaluated, and no side effect is written."

    Design: Corner/errors/every_error_response_carries_the_same_two_field_envelope_across_status_classes
    """
    ctx = _estate_with_a_draft_cycle()
    requester = make_clinical_requester_headers(ctx["department"]["id"])

    shape_fault = api.create_facility({"name": "Ghost Facility"}, _PLANNER)
    validate_error(shape_fault, ApiErrorId.ERR_VALIDATION.value, 422)

    missing_row = api.get_cycle(UNKNOWN_UUID, _PLANNER)
    validate_error(missing_row, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)

    state_fault = api.close_intake(ctx["cycle"]["id"], _PLANNER)
    validate_error(state_fault, ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409)

    validate_success(api.open_intake(ctx["cycle"]["id"], _PLANNER))

    semantic_fault = api.create_request(
        create_request_payload(
            ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"],
            clinical_justification="Mandated CT dose-monitoring upgrade.",
            regulatory_mandate_flag=True,
        ),
        requester,
    )
    validate_error(semantic_fault, ApiErrorId.ERR_MANDATE_DEADLINE_REQUIRED.value, 422)

    for response in (shape_fault, missing_row, state_fault, semantic_fault):
        body = response.json()
        assert_error_envelope_shape(body)
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert set(body.keys()) == {"meta", "response_type", "data"}, (
            "no top-level error, errors or detail key rides alongside the envelope"
        )

    assert get_success_data(api.list_requests(_PLANNER, params={"cycle_id": ctx["cycle"]["id"]})) == []
    facilities = get_success_data(api.list_facilities(_PLANNER))
    assert len(facilities) == 1
    assert facilities[0]["id"] == ctx["facility"]["id"]

    after = refresh_cycle(ctx["cycle"]["id"])
    assert after["status"] == "INTAKE_OPEN"
    assert after["version"] == 2
