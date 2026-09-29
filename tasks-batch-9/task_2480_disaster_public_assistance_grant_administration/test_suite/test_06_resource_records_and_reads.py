"""Resource records, their declared defaults, and the read paths that expose them."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    cost_line_item_payload,
    create_applicant,
    create_contract,
    create_disaster,
    create_facility,
    create_labor_resource,
    create_project,
    determine_eligibility,
    disaster_payload,
    facility_payload,
    get_force_account_resource,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_applicant_agent_headers,
    make_auditor_headers,
    project_payload,
    screen_facility,
    set_clock,
    setup_declaration,
    setup_eligible_facility,
    setup_submitted_project,
    submit_project,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_disaster_creation_returns_declared_defaults_and_zeroed_aggregates(api):
    """PRD §4: "Endpoints that bring a new resource row into existence answer with HTTP 201
    and the created resource in `data`; every other successful operation — reads, lists,
    state transitions, amendments and the logical-clock capability — answers with HTTP 200."

    PRD §3.1: "Two economics knobs are optional: `federal_cost_share_pct`, which defaults to
    0.75 and must be one of 0.75, 0.90 or 1.00, and `small_project_threshold_cents`, which
    defaults to 4,000,000 cents — forty thousand dollars — and must be at least 1."

    PRD §3.1: "The declaration is created in status `DECLARED` with every roll-up zeroed:
    `total_validated_loss_cents`, `per_capita_impact_cents`, `total_obligated_cents`,
    `total_drawn_cents`, `enhanced_monitoring_applicant_count` and
    `suspended_applicant_count` all start at 0 and `indicator_met` starts false."

    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by exactly
    1 on every mutation of the row."

    Design: Corner/entities/disaster_creation_returns_declared_defaults_and_zeroed_aggregates
    """
    set_clock("2026-07-01T00:00:00Z")

    response = api.create_disaster(
        disaster_payload(
            declaration_number="DR-4930",
            state_code="TX",
            incident_type="FLOOD",
            incident_start_at="2026-06-10T00:00:00Z",
            incident_end_at="2026-06-25T00:00:00Z",
            population=2_000_000,
        ),
        ADMIN,
    )
    disaster = validate_success(response, 201)

    assert disaster["declaration_number"] == "DR-4930", (
        f"Expected declaration_number 'DR-4930', got {disaster['declaration_number']!r}"
    )
    assert disaster["federal_cost_share_pct"] == 0.75, (
        f"Expected the declared default federal_cost_share_pct 0.75, got "
        f"{disaster['federal_cost_share_pct']}"
    )
    assert disaster["small_project_threshold_cents"] == 4_000_000, (
        f"Expected the declared default small_project_threshold_cents 4000000, got "
        f"{disaster['small_project_threshold_cents']}"
    )
    assert disaster["status"] == "DECLARED", (
        f"Expected status DECLARED at creation, got {disaster['status']}"
    )
    for field in (
        "total_validated_loss_cents",
        "per_capita_impact_cents",
        "total_obligated_cents",
        "total_drawn_cents",
        "enhanced_monitoring_applicant_count",
        "suspended_applicant_count",
    ):
        assert disaster[field] == 0, f"Expected {field} 0 at creation, got {disaster[field]}"
    assert disaster["indicator_met"] is False, (
        f"Expected indicator_met false at creation, got {disaster['indicator_met']!r}"
    )
    assert disaster["version"] == 1, (
        f"Expected version 1 on creation, got {disaster['version']}"
    )


def test_disaster_retrieval_returns_stored_row(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

    PRD §2.6: "Rates and percentages are the exception: `federal_cost_share_pct` (one of
    0.75, 0.90 or 1.00), `fringe_benefit_pct` (a fraction from 0 through 1 inclusive),
    `work_completed_pct` and `pct_complete` (each a number from 0 through 100 inclusive) are
    stored as supplied."

    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by exactly
    1 on every mutation of the row."

    Design: Corner/entities/disaster_retrieval_returns_stored_row
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(
        declaration_number="DR-4931",
        state_code="TX",
        incident_type="WILDFIRE",
        incident_start_at="2026-05-01T00:00:00Z",
        incident_end_at="2026-05-20T00:00:00Z",
        population=500_000,
        federal_cost_share_pct=0.90,
    )

    response = api.get_disaster(disaster["id"], make_auditor_headers())
    read = validate_success(response, 200)

    assert response.json()["response_type"] == "object", (
        f"Expected response_type 'object' for a single resource, got "
        f"{response.json()['response_type']!r}"
    )
    assert read["declaration_number"] == "DR-4931", (
        f"Expected declaration_number 'DR-4931', got {read['declaration_number']!r}"
    )
    assert read["state_code"] == "TX", f"Expected state_code 'TX', got {read['state_code']!r}"
    assert read["incident_type"] == "WILDFIRE", (
        f"Expected incident_type WILDFIRE, got {read['incident_type']}"
    )
    assert is_iso8601_timestamp(read["incident_start_at"]), (
        f"incident_start_at must be an ISO 8601 instant, got {read['incident_start_at']!r}"
    )
    assert is_iso8601_timestamp(read["incident_end_at"]), (
        f"incident_end_at must be an ISO 8601 instant, got {read['incident_end_at']!r}"
    )
    assert read["population"] == 500_000, (
        f"Expected population 500000, got {read['population']}"
    )
    assert read["federal_cost_share_pct"] == 0.90, (
        f"Expected federal_cost_share_pct 0.90 stored as supplied, got "
        f"{read['federal_cost_share_pct']}"
    )
    assert read["version"] == 1, (
        f"Expected version 1 after a read mutates nothing, got {read['version']}"
    )


def test_applicant_list_pagination_envelope(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters."

    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1
    and its maximum accepted value is 100."

    PRD §2.3: "`offset` controls the starting position: it defaults to 0 and its minimum
    accepted value is 0."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`
    and `has_more`, where `total_count` is the number of rows matching the filters before the
    page window is applied and `has_more` is true when rows remain beyond the current window."

    PRD §2.3: "Unless a subsection says otherwise, list results are ordered by `created_at`
    ascending."

    Design: Corner/entities/applicant_list_pagination_and_filter_envelope
    """
    scenario = setup_declaration(
        "2026-07-01T00:00:00Z", declaration_number="DR-4932"
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_a = create_applicant(
        disaster_id,
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    create_applicant(
        disaster_id,
        name="Coastal Tribal Nation",
        applicant_type="TRIBE",
        population_served=8_000,
    )
    create_applicant(
        disaster_id,
        name="State Transport Agency",
        applicant_type="STATE_AGENCY",
        population_served=900_000,
    )
    determine_eligibility(
        applicant_a["id"],
        decision="ELIGIBLE",
        rationale="Local government inside the declared area",
    )

    first_response = api.list_applicants(ADMIN, params={"limit": 2, "offset": 0})
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        f"Expected response_type 'array' for a list endpoint, got "
        f"{first_response.json()['response_type']!r}"
    )
    assert len(first_rows) == 2, f"Expected 2 rows in the first page, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"Expected total_count 3 before the page window, got {first_meta['total_count']}"
    )
    assert first_meta["limit"] == 2, f"Expected limit 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"Expected offset 0, got {first_meta['offset']}"
    assert first_meta["has_more"] is True, (
        f"Expected has_more true with a row beyond the window, got {first_meta['has_more']!r}"
    )

    second_rows, second_meta = validate_paginated(
        api.list_applicants(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, (
        f"Expected 1 row in the second page, got {len(second_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        f"Expected total_count 3 before the page window, got {second_meta['total_count']}"
    )
    assert second_meta["offset"] == 2, f"Expected offset 2, got {second_meta['offset']}"
    assert second_meta["has_more"] is False, (
        f"Expected has_more false at the end of the collection, got "
        f"{second_meta['has_more']!r}"
    )


def test_every_single_resource_get_with_unknown_id_returns_its_own_not_found(api):
    """PRD §2.7: "Resolution of every identifier embedded in the URL path, validated left to
    right."

    PRD §2.7: "The first identifier that does not resolve decides the error:
    `ERR_DISASTER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_DAMAGE_SITE_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_COST_LINE_ITEM_NOT_FOUND`,
    `ERR_RESOURCE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_DRAWDOWN_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`, `ERR_DEOBLIGATION_NOT_FOUND`
    or `ERR_APPEAL_NOT_FOUND` (all 404)."

    PRD §2.1: "Every `GET` endpoint in §4 is readable by all six roles."

    Design: Corner/entities/every_single_resource_get_with_unknown_id_returns_its_own_not_found
    """
    set_clock("2026-07-01T00:00:00Z")

    probes = [
        (api.get_disaster, ApiErrorId.ERR_DISASTER_NOT_FOUND),
        (api.get_applicant, ApiErrorId.ERR_APPLICANT_NOT_FOUND),
        (api.get_facility, ApiErrorId.ERR_FACILITY_NOT_FOUND),
        (api.get_damage_site, ApiErrorId.ERR_DAMAGE_SITE_NOT_FOUND),
        (api.get_project, ApiErrorId.ERR_PROJECT_NOT_FOUND),
        (api.get_cost_line_item, ApiErrorId.ERR_COST_LINE_ITEM_NOT_FOUND),
        (api.get_force_account_resource, ApiErrorId.ERR_RESOURCE_NOT_FOUND),
        (api.get_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_insurance_policy, ApiErrorId.ERR_POLICY_NOT_FOUND),
        (api.get_drawdown, ApiErrorId.ERR_DRAWDOWN_NOT_FOUND),
        (api.get_progress_report, ApiErrorId.ERR_PROGRESS_REPORT_NOT_FOUND),
        (api.get_deobligation, ApiErrorId.ERR_DEOBLIGATION_NOT_FOUND),
        (api.get_appeal, ApiErrorId.ERR_APPEAL_NOT_FOUND),
    ]

    for read_one, expected_error_id in probes:
        response = read_one(NON_EXISTENT_UUID, ADMIN)
        assert response.json().get("response_type") == "error", (
            f"Expected response_type 'error' from {read_one.__name__} on an unknown id, got "
            f"{response.json().get('response_type')!r}"
        )
        validate_error(response, expected_error_id, 404)


def test_applicant_creation_missing_applicant_type_rejected(api):
    """PRD §3.1: "Applicants are registered under a declaration by a `PlatformAdmin`, who
    supplies the `disaster_id` of the declaration, the applicant's non-empty legal `name`,
    its `applicant_type` from `LOCAL_GOVERNMENT`, `TRIBE`, `STATE_AGENCY` and
    `PRIVATE_NONPROFIT`, and a `population_served` of at least 0."

    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed page window
    yields `ERR_INVALID_PAGINATION` (422)."

    Design: Corner/entities/applicant_creation_missing_applicant_type_rejected
    """
    scenario = setup_declaration(
        "2026-07-01T00:00:00Z", declaration_number="DR-4933"
    )

    response = api.create_applicant(
        {
            "disaster_id": scenario["disaster"]["id"],
            "name": "City of Harborview",
            "population_served": 120_000,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(api.list_applicants(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after the rejected create, got {meta['total_count']}"
    )


def test_facility_creation_omitted_flags_apply_declared_defaults(api):
    """PRD §3.2: "Four documentation flags are optional and default in the applicant's favour
    except where noted: `in_active_use` defaults to true, `legal_responsibility_documented`
    defaults to true, `flood_zone` defaults to false, and `prior_disaster_flood_damage`
    defaults to false."

    PRD §3.2: "A newly registered facility sits in `eligibility_status` `PENDING` with
    `screening_failure_reason` null and `screened_at` null."

    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by exactly
    1 on every mutation of the row."

    Design: Corner/entities/facility_creation_omitted_flags_apply_declared_defaults
    """
    scenario = setup_declaration(
        "2026-07-01T00:00:00Z", declaration_number="DR-4934"
    )
    applicant = create_applicant(
        scenario["disaster"]["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )

    response = api.create_facility(
        facility_payload(
            applicant["id"],
            name="Riverside Pump Station",
            facility_type="WATER_CONTROL",
            ownership="PUBLIC",
        ),
        make_applicant_agent_headers(applicant["id"]),
    )
    facility = validate_success(response, 201)

    assert facility["in_active_use"] is True, (
        f"Expected in_active_use true by default, got {facility['in_active_use']!r}"
    )
    assert facility["legal_responsibility_documented"] is True, (
        "Expected legal_responsibility_documented true by default, got "
        f"{facility['legal_responsibility_documented']!r}"
    )
    assert facility["flood_zone"] is False, (
        f"Expected flood_zone false by default, got {facility['flood_zone']!r}"
    )
    assert facility["prior_disaster_flood_damage"] is False, (
        "Expected prior_disaster_flood_damage false by default, got "
        f"{facility['prior_disaster_flood_damage']!r}"
    )
    assert facility["eligibility_status"] == "PENDING", (
        f"Expected eligibility_status PENDING at registration, got "
        f"{facility['eligibility_status']}"
    )
    assert facility["screening_failure_reason"] is None, (
        f"Expected screening_failure_reason null at registration, got "
        f"{facility['screening_failure_reason']!r}"
    )
    assert facility["screened_at"] is None, (
        f"Expected screened_at null at registration, got {facility['screened_at']!r}"
    )
    assert facility["version"] == 1, (
        f"Expected version 1 on creation, got {facility['version']}"
    )


def test_project_computed_basis_fields_start_zeroed_and_work_type_derived_at_submit(api):
    """PRD §3.3: "The project is created in `DRAFT` with `size_class` null, `rfi_round_count`
    0, `last_rfi_question` null, `work_type` not yet derived, and every basis and ledger field
    at its opening value: `repair_eligible_cents`, `anticipated_insurance_cents`,
    `settlement_allocated_cents`, `insurance_reduction_cents`, `mitigation_approved_cents`,
    `eligible_cost_provisional_cents`, `federal_share_obligated_cents`, `deobligated_cents`
    and `pending_deobligation_cents` at 0, and `eligible_cost_final_cents`,
    `federal_share_final_cents`, `closeout_variance_cents`, `cost_reviewed_by_user_id`,
    `obligated_by_user_id` and `denial_reason` all null."

    PRD §3.3: "Mitigation funding — measures that reduce the risk of the same damage
    recurring — is requested at formulation time through the optional
    `mitigation_requested_cents`, which defaults to 0, must be at least 0, and may not exceed
    `estimated_repair_cost_cents`; a larger request is rejected outright with
    `ERR_MITIGATION_EXCEEDS_REPAIR`."

    PRD §3.3: "Submission also derives `work_type` from the category once and for all:
    categories `A` and `B` are `EMERGENCY` work, and categories `C`, `D`, `E`, `F` and `G`
    are `PERMANENT` work."

    PRD §3.3: "Size classification comes next and is a pure comparison of the repair basis
    against the declaration's `small_project_threshold_cents`: strictly below the threshold
    makes `size_class` `SMALL`, and at or above it makes `size_class` `LARGE`."

    PRD §3.3: "Finally, `eligible_cost_provisional_cents` is the repair basis less the
    anticipated insurance offset, floored at 0 so an over-insured project never produces a
    negative figure, plus the approved mitigation component."

    Design: Corner/entities/project_computed_basis_fields_start_zeroed_and_work_type_derived_at_submit
    """
    scenario = setup_eligible_facility(
        "2026-07-01T00:00:00Z", {"declaration_number": "DR-4935"}
    )
    applicant_id = scenario["applicant"]["id"]

    create_response = api.create_project(
        project_payload(
            applicant_id,
            scenario["facility"]["id"],
            category="C",
            title="Pump station intake rebuild",
            scope_of_work="Rebuild intake structure and control panel",
            estimated_repair_cost_cents=5_000_000,
        ),
        make_applicant_agent_headers(applicant_id),
    )
    project = validate_success(create_response, 201)

    assert project["status"] == "DRAFT", (
        f"Expected status DRAFT at formulation, got {project['status']}"
    )
    assert project["size_class"] is None, (
        f"Expected size_class null at formulation, got {project['size_class']!r}"
    )
    for field in (
        "repair_eligible_cents",
        "anticipated_insurance_cents",
        "settlement_allocated_cents",
        "insurance_reduction_cents",
        "mitigation_approved_cents",
        "eligible_cost_provisional_cents",
        "federal_share_obligated_cents",
        "deobligated_cents",
        "pending_deobligation_cents",
    ):
        assert project[field] == 0, (
            f"Expected {field} 0 at formulation, got {project[field]}"
        )
    for field in (
        "eligible_cost_final_cents",
        "federal_share_final_cents",
        "closeout_variance_cents",
        "cost_reviewed_by_user_id",
        "obligated_by_user_id",
        "denial_reason",
    ):
        assert project[field] is None, (
            f"Expected {field} null at formulation, got {project[field]!r}"
        )
    assert project["mitigation_requested_cents"] == 0, (
        f"Expected the declared default mitigation_requested_cents 0, got "
        f"{project['mitigation_requested_cents']}"
    )
    assert project["rfi_round_count"] == 0, (
        f"Expected rfi_round_count 0 at formulation, got {project['rfi_round_count']}"
    )
    assert project["last_rfi_question"] is None, (
        f"Expected last_rfi_question null at formulation, got "
        f"{project['last_rfi_question']!r}"
    )

    submitted = validate_success(
        api.submit_project(project["id"], make_applicant_agent_headers(applicant_id)), 200
    )
    assert submitted["work_type"] == "PERMANENT", (
        f"Expected work_type PERMANENT for category C, got {submitted['work_type']!r}"
    )
    assert submitted["size_class"] == "LARGE", (
        f"Expected size_class LARGE for a 5000000-cent basis against the 4000000-cent "
        f"threshold, got {submitted['size_class']!r}"
    )
    assert submitted["eligible_cost_provisional_cents"] == 5_000_000, (
        f"Expected eligible_cost_provisional_cents 5000000, got "
        f"{submitted['eligible_cost_provisional_cents']}"
    )


def test_applicant_system_fields_are_server_minted(api):
    """PRD §2.4: "`id` — a server-minted UUID."

    PRD §2.4: "It carries no type prefix and clients never supply it."

    PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed
    at creation and never changed."

    PRD §2.4: "`updated_at` — an ISO 8601 UTC timestamp with three fractional digits,
    refreshed on every mutation of the row, including mutations of purely derived fields."

    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by exactly
    1 on every mutation of the row."

    PRD §3.1: "A new applicant starts with `eligibility_status` `PENDING`,
    `monitoring_status` `STANDARD`, `drawdown_status` `ACTIVE`, `audit_requirement` `NONE`,
    `eligibility_rationale` null, `risk_score_screening` 0, `risk_score_monitoring` null,
    `monitoring_scored_at` null, `risk_tier` `LOW`, and every ledger figure —
    `total_obligated_cents`, `total_drawn_cents`, `total_refunded_cents`,
    `cash_on_hand_cents`, `available_drawdown_cents`, `pending_deobligation_cents` and
    `delinquent_report_count` — at 0."

    Design: Corner/entities/applicant_system_fields_are_server_minted
    """
    scenario = setup_declaration(
        "2026-07-01T00:00:00Z", declaration_number="DR-4936"
    )

    payload = {
        "disaster_id": scenario["disaster"]["id"],
        "name": "Coastal Tribal Nation",
        "applicant_type": "TRIBE",
        "population_served": 8_000,
    }
    applicant = validate_success(api.create_applicant(payload, ADMIN), 201)

    assert is_valid_uuid(applicant["id"]), (
        f"Expected a server-minted UUID id, got {applicant['id']!r}"
    )
    assert applicant["id"] not in [str(value) for value in payload.values()], (
        f"The server-minted id must be distinct from every payload value, got "
        f"{applicant['id']!r}"
    )
    assert applicant["version"] == 1, (
        f"Expected version 1 on creation, got {applicant['version']}"
    )
    assert is_iso8601_timestamp(applicant["created_at"]), (
        f"created_at must be an ISO 8601 instant, got {applicant['created_at']!r}"
    )
    assert is_iso8601_timestamp(applicant["updated_at"]), (
        f"updated_at must be an ISO 8601 instant, got {applicant['updated_at']!r}"
    )
    assert applicant["eligibility_status"] == "PENDING", (
        f"Expected eligibility_status PENDING at registration, got "
        f"{applicant['eligibility_status']}"
    )
    assert applicant["eligibility_rationale"] is None, (
        f"Expected eligibility_rationale null at registration, got "
        f"{applicant['eligibility_rationale']!r}"
    )
    assert applicant["monitoring_status"] == "STANDARD", (
        f"Expected monitoring_status STANDARD at registration, got "
        f"{applicant['monitoring_status']}"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected drawdown_status ACTIVE at registration, got "
        f"{applicant['drawdown_status']}"
    )
    assert applicant["audit_requirement"] == "NONE", (
        f"Expected audit_requirement NONE at registration, got "
        f"{applicant['audit_requirement']}"
    )
    assert applicant["risk_score_screening"] == 0, (
        f"Expected risk_score_screening 0 at registration, got "
        f"{applicant['risk_score_screening']}"
    )
    assert applicant["risk_score_monitoring"] is None, (
        f"Expected risk_score_monitoring null at registration, got "
        f"{applicant['risk_score_monitoring']!r}"
    )
    assert applicant["monitoring_scored_at"] is None, (
        f"Expected monitoring_scored_at null at registration, got "
        f"{applicant['monitoring_scored_at']!r}"
    )
    assert applicant["risk_tier"] == "LOW", (
        f"Expected risk_tier LOW at registration, got {applicant['risk_tier']}"
    )


def test_disaster_invalid_incident_type_enum_rejected(api):
    """PRD §3.1: "The declaration carries a `declaration_number` (a non-empty string that
    must be globally unique across every declaration; a repeat is rejected with
    `ERR_DECLARATION_NUMBER_DUPLICATE`), a `state_code` of exactly two uppercase letters
    identifying the state or territory that owns the declaration, an `incident_type` from
    `SEVERE_STORM`, `FLOOD`, `WILDFIRE`, `HURRICANE` and `EARTHQUAKE`, the inclusive incident
    period bounds `incident_start_at` and `incident_end_at`, and a `population` of at least 1
    that serves as the denominator of the per-capita indicator."

    PRD §3.1: "Two economics knobs are optional: `federal_cost_share_pct`, which defaults to
    0.75 and must be one of 0.75, 0.90 or 1.00, and `small_project_threshold_cents`, which
    defaults to 4,000,000 cents — forty thousand dollars — and must be at least 1."

    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed page window
    yields `ERR_INVALID_PAGINATION` (422)."

    Design: Corner/entities/disaster_invalid_incident_type_enum_rejected
    """
    set_clock("2026-07-01T00:00:00Z")

    bad_enum = api.create_disaster(
        disaster_payload(declaration_number="DR-4937", incident_type="TORNADO"), ADMIN
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 422)

    bad_share = api.create_disaster(
        disaster_payload(declaration_number="DR-4938", federal_cost_share_pct=0.8), ADMIN
    )
    validate_error(bad_share, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(api.list_disasters(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 because neither row was created, got {meta['total_count']}"
    )


def test_cost_line_item_type_to_foreign_key_pairing_rejected(api):
    """PRD §2.7: "Request shape: every required body field present, every enum value a member
    of its declared set, every integer inside its declared range, every datetime valid ISO
    8601, `work_end_at` strictly later than `work_start_at`, `quarter_label` of the form four
    digits, a hyphen, the letter `Q`, and a digit from 1 to 4, and the pairing between
    `cost_type` and its foreign key respected — `force_account_resource_id` required and
    `contract_id` null for `FORCE_ACCOUNT_LABOR` and `FORCE_ACCOUNT_EQUIPMENT`, `contract_id`
    required and `force_account_resource_id` null for `CONTRACT`, and both null for
    `MATERIALS`."

    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed page window
    yields `ERR_INVALID_PAGINATION` (422)."

    PRD §3.4: "The claim class selects which foreign key is required:
    `force_account_resource_id` for both force account classes and `contract_id` for a
    contracted cost, with the unused key left null and both left null for materials — a
    mismatch is an invalid request."

    Design: Corner/entities/cost_line_item_type_to_foreign_key_pairing_rejected
    """
    scenario = setup_submitted_project(
        "2026-07-01T00:00:00Z",
        {"declaration_number": "DR-4939"},
        project_overrides={
            "category": "C",
            "title": "Pump station intake rebuild",
            "scope_of_work": "Rebuild intake structure and control panel",
            "estimated_repair_cost_cents": 5_000_000,
        },
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    contract = create_contract(
        applicant_id,
        vendor_name="Bayline Contractors",
        contract_type="SMALL_PURCHASE",
        award_amount_cents=1_000_000,
        awarded_at="2026-06-15T00:00:00Z",
        debarment_check_completed=True,
    )

    missing_fk = api.create_cost_line_item(
        cost_line_item_payload(
            project_id,
            cost_type="FORCE_ACCOUNT_LABOR",
            claimed_cents=50_000,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T16:00:00Z",
            straight_time_hours=8,
        ),
        agent,
    )
    validate_error(missing_fk, ApiErrorId.ERR_INVALID_REQUEST, 422)

    extra_fk = api.create_cost_line_item(
        cost_line_item_payload(
            project_id,
            cost_type="MATERIALS",
            claimed_cents=50_000,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T16:00:00Z",
            contract_id=contract["id"],
        ),
        agent,
    )
    validate_error(extra_fk, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(api.list_cost_line_items(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after both rejected claims, got {meta['total_count']}"
    )


def test_facility_creation_with_unknown_applicant_id_returns_not_found(api):
    """PRD §2.7: "Resolution of every foreign key supplied in the body — `disaster_id`,
    `applicant_id`, `facility_id`, `project_id`, `force_account_resource_id`, `contract_id`,
    `deobligation_id` and `prior_appeal_id` — with the same 404 error identifiers as rung 4."

    PRD §2.1: "When `X-User-Role` is `ApplicantAgent`, `X-User-ID` is the `id` of the acting
    `Applicant`; ownership checks on any resource that references an `Applicant` compare the
    resource's foreign-key field to `X-User-ID`."

    Design: Corner/entities/facility_creation_with_unknown_applicant_id_returns_not_found
    """
    setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4940")

    response = api.create_facility(
        facility_payload(
            NON_EXISTENT_UUID,
            name="Riverside Pump Station",
            facility_type="WATER_CONTROL",
            ownership="PUBLIC",
        ),
        make_applicant_agent_headers(NON_EXISTENT_UUID),
    )
    validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND, 404)

    _rows, meta = validate_paginated(api.list_facilities(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after the rejected registration, got {meta['total_count']}"
    )


def test_cost_line_item_referencing_another_applicants_resource_rejected(api):
    """PRD §3.4: "Cross-aggregate references must stay inside one applicant: the referenced
    force account resource or contract must belong to the same applicant as the project, or
    the claim fails with `ERR_CROSS_APPLICANT_REFERENCE`."

    PRD §2.7: "`ApplicantAgent` ownership scope over every applicant-scoped resource named in
    the path or the body — `ERR_APPLICANT_SCOPE_VIOLATION` (403)."

    PRD §3.4: "Every resource starts with `charged_hours_total` at 0; that field is the
    running total of `straight_time_hours` plus `overtime_hours` plus `equipment_hours`
    across every cost line item that references the resource, and it is refreshed whenever
    one of those lines is reviewed."

    Design: Corner/entities/cost_line_item_referencing_another_applicants_resource_rejected
    """
    scenario = setup_declaration(
        "2026-07-01T00:00:00Z", declaration_number="DR-4941"
    )
    disaster_id = scenario["disaster"]["id"]

    applicant_a = create_applicant(
        disaster_id,
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant_a["id"],
        decision="ELIGIBLE",
        rationale="Local government inside the declared area",
    )
    applicant_b = create_applicant(
        disaster_id,
        name="Coastal Tribal Nation",
        applicant_type="TRIBE",
        population_served=8_000,
    )
    determine_eligibility(
        applicant_b["id"],
        decision="ELIGIBLE",
        rationale="Tribal government inside the declared area",
    )

    facility_a = create_facility(
        applicant_a["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility_a["id"])
    project_a = create_project(
        applicant_a["id"],
        facility_a["id"],
        category="C",
        title="Pump station intake rebuild",
        scope_of_work="Rebuild intake structure and control panel",
        estimated_repair_cost_cents=5_000_000,
    )
    submit_project(project_a["id"], applicant_a["id"])

    resource_b = create_labor_resource(
        applicant_b["id"],
        label="B. Rivera, maintenance II",
        employee_type="TEMPORARY",
        base_hourly_rate_cents=4_000,
        fringe_benefit_pct=0.1,
    )

    response = api.create_cost_line_item(
        cost_line_item_payload(
            project_a["id"],
            cost_type="FORCE_ACCOUNT_LABOR",
            claimed_cents=35_200,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T16:00:00Z",
            force_account_resource_id=resource_b["id"],
            straight_time_hours=8,
        ),
        make_applicant_agent_headers(applicant_a["id"]),
    )
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_CROSS_APPLICANT_REFERENCE,
            ApiErrorId.ERR_APPLICANT_SCOPE_VIOLATION,
        ],
    )

    _rows, meta = validate_paginated(api.list_cost_line_items(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after the rejected claim, got {meta['total_count']}"
    )

    resource_after = get_force_account_resource(resource_b["id"])
    assert resource_after["charged_hours_total"] == 0, (
        f"Expected charged_hours_total 0 because no line was recorded, got "
        f"{resource_after['charged_hours_total']}"
    )
