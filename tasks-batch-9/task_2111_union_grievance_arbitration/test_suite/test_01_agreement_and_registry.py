"""Standing up an agreement, its clauses, its people and the reference libraries."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_arbitrator,
    assert_bargaining_unit,
    assert_contract_clause,
    assert_employee,
    assert_precedent_case,
    bargaining_unit_payload,
    contract_clause_payload,
    create_bargaining_unit,
    create_contract_clause,
    create_precedent_case,
    employee_payload,
    grievance_payload,
    precedent_case_payload,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_agreement_registration_applies_every_declared_default(api, director_headers):
    """PRD §3.1: "`step1_response_days`, `step2_response_days` and `step3_response_days`
    are the calendar days the employer has to answer a meeting held at each rung of the
    ladder, defaulting to 10, 15 and 20; `appeal_window_days` is the union's window to
    appeal after a step resolves, defaulting to 7; `filing_window_days` is the window
    from discovery within which a grievance must be filed at all, defaulting to 30; and
    `arbitration_demand_days` is the window after step-3 resolution within which
    arbitration must be demanded, defaulting to 21."
    PRD §3.1: "The boolean `tolling_enabled` defaults to false and, while false, forbids
    any step from being scheduled with agreed extension days."

    Design: Corner/entities/bargaining_unit_creation_applies_declared_defaults
    """
    response = api.create_bargaining_unit(bargaining_unit_payload(), director_headers)
    unit = validate_success(response, 201)
    assert_bargaining_unit(unit)

    assert unit["step1_response_days"] == 10
    assert unit["step2_response_days"] == 15
    assert unit["step3_response_days"] == 20
    assert unit["appeal_window_days"] == 7
    assert unit["filing_window_days"] == 30
    assert unit["arbitration_demand_days"] == 21
    assert unit["tolling_enabled"] is False
    assert unit["version"] == 1
    assert unit["open_grievance_count"] == 0


def test_agreement_registration_applies_declared_authority_ceilings(api, director_headers):
    """PRD §3.1: "`director_authority_cents` is the highest settlement exposure a
    `LaborRelationsDirector` may authorize and defaults to 250,000 cents — two and a half
    thousand dollars — while `negotiator_authority_cents` is the corresponding ceiling for
    a `ChiefNegotiator`, defaults to 1,500,000 cents, and must be strictly greater than
    the director's ceiling."
    PRD §3.1: "`precedent_deviation_tolerance_bps` defaults to 2,000 basis points — twenty
    percent — and is the amount by which a settlement may deviate from the precedent it
    cites before the authority required to approve it escalates."

    Design: Corner/entities/bargaining_unit_creation_applies_declared_defaults
    """
    unit = validate_success(
        api.create_bargaining_unit(bargaining_unit_payload(), director_headers), 201
    )

    assert unit["director_authority_cents"] == 250_000
    assert unit["negotiator_authority_cents"] == 1_500_000
    assert unit["precedent_deviation_tolerance_bps"] == 2_000


def test_agreement_read_reports_derived_active_status(api, administrator_headers):
    """PRD §3.1: "A registered agreement reports two derived fields: its `status`, which
    reads `ACTIVE` while the logical clock is before `contract_expiry_date` and `EXPIRED`
    from that instant onward, evaluated afresh at every read and at every write that names
    the unit; and `open_grievance_count`, the number of grievances filed under it whose
    status is not one of `SETTLED`, `WITHDRAWN`, `CONSOLIDATED` or `CLOSED`."

    Design: Corner/entities/bargaining_unit_retrieval_reports_derived_status_active
    """
    unit = create_bargaining_unit()

    body = api.get_bargaining_unit(unit["id"], administrator_headers)
    read = validate_success(body, 200)
    assert_bargaining_unit(read)

    assert read["status"] == "ACTIVE"
    assert read["open_grievance_count"] == 0
    assert body.json()["meta"]["api_request_id"].startswith("req_")


def test_clause_listing_orders_by_clause_number_and_paginates(api, analyst_headers):
    """PRD §2.3: "- Contract clauses of an agreement: ascending `clause_number`."
    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value
    is 1 and its maximum accepted value is 100."

    Design: Corner/entities/contract_clause_listing_paginates_under_its_unit
    """
    unit = create_bargaining_unit()
    create_contract_clause(
        unit["id"], clause_number="ART-19", title="Safety and Health",
        category="SAFETY", monetary_cap_cents=500_000, expedited=True,
    )
    create_contract_clause(
        unit["id"], clause_number="ART-07", title="Subcontracting",
        category="SUBCONTRACTING", is_arbitrable=False,
    )
    create_contract_clause(unit["id"])  # ART-12

    rows, meta = validate_paginated(
        api.list_contract_clauses(unit["id"], analyst_headers, params={"limit": 2, "offset": 0})
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert len(rows) == 2
    assert rows[0]["clause_number"] == "ART-07"
    assert rows[1]["clause_number"] == "ART-12"
    assert rows[0]["is_arbitrable"] is False
    assert rows[1]["is_arbitrable"] is True


def test_clause_listing_filters_by_category(api, analyst_headers):
    """PRD §3.1: "A clause carries a `clause_number` — the article designator, unique
    within its own agreement, colliding with `ERR_DUPLICATE_IDENTIFIER` — a human-readable
    `title`, and a `category` drawn from `DISCIPLINE`, `PAY`, `SENIORITY`, `SAFETY`,
    `LEAVE` and `SUBCONTRACTING`, which is the axis the office's trend analysis reports
    along and the axis the clause listing may be filtered on."

    Design: Corner/entities/contract_clause_listing_paginates_under_its_unit
    """
    unit = create_bargaining_unit()
    create_contract_clause(
        unit["id"], clause_number="ART-19", title="Safety and Health",
        category="SAFETY", monetary_cap_cents=500_000, expedited=True,
    )
    create_contract_clause(unit["id"])  # ART-12, DISCIPLINE

    rows, meta = validate_paginated(
        api.list_contract_clauses(unit["id"], analyst_headers, params={"category": "SAFETY"})
    )

    assert meta["total_count"] == 1
    assert rows[0]["clause_number"] == "ART-19"
    assert rows[0]["expedited"] is True
    assert rows[0]["monetary_cap_cents"] == 500_000
    assert_contract_clause(rows[0])


def test_employee_listing_filters_by_the_self_referential_supervisor(api, analyst_headers):
    """PRD §3.1: "The reporting line is self-referential: `supervisor_id` names another
    person in the registry and is null at the top of the chain, and the people listing may
    be filtered by it as well as by `bargaining_unit_id`, `classification` and
    `employment_status`."
    PRD §2.3: "- People: ascending `employee_number`."

    Design: Corner/entities/employee_self_referential_supervisor_filter_returns_direct_reports
    """
    ctx = setup_base()

    rows, meta = validate_paginated(
        api.list_employees(analyst_headers, params={"supervisor_id": ctx["supervisor"]["id"]})
    )

    assert meta["total_count"] == 2, "only the two direct reports carry that supervisor_id"
    assert rows[0]["employee_number"] == "EMP-1"
    assert rows[1]["employee_number"] == "STW-1"
    assert all(row["id"] != ctx["supervisor"]["id"] for row in rows)
    assert ctx["supervisor"]["supervisor_id"] is None
    assert ctx["grievant"]["supervisor_id"] == ctx["supervisor"]["id"]
    for row in rows:
        assert_employee(row)


def test_employee_registration_defaults_to_active_employment(api, analyst_headers):
    """PRD §3.1: "That last field is the person's employment standing — `ACTIVE`,
    `SUSPENDED`, `TERMINATED` or `REINSTATED` — and defaults to `ACTIVE`."

    Design: Corner/entities/employee_self_referential_supervisor_filter_returns_direct_reports
    """
    ctx = setup_base()

    rows, meta = validate_paginated(
        api.list_employees(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )

    assert meta["total_count"] == 3
    assert ctx["grievant"]["employment_status"] == "ACTIVE"
    assert all(row["employment_status"] == "ACTIVE" for row in rows)


def test_clause_creation_rejects_an_undeclared_category(api, director_headers, analyst_headers):
    """PRD §2.10: "The request body conforms to the operation's input schema — otherwise
    `ERR_INVALID_REQUEST` (HTTP 400). Conformance means: every required field is present;
    every enum-typed field carries a declared member; integers constrained to be
    non-negative or strictly positive respect that constraint; datetimes parse as ISO 8601;
    `panel_memberships` is a non-empty array; `sustained_fraction_bps` is consistent with
    the award `outcome`; `interest_accrual_start` is present whenever `interest_rate_bps`
    is greater than 0; `counter_monetary_cents` is present whenever `decision` is
    `COUNTER`; `granted_amount_cents` is supplied only alongside a `disposition` of
    `GRANTED` or `PARTIAL`; and `reinstatement_effective_date` is supplied only for an
    award that ordered reinstatement."

    Design: Corner/entities/clause_creation_rejects_invalid_enum_category
    """
    unit = create_bargaining_unit()

    response = api.create_contract_clause(
        unit["id"],
        contract_clause_payload(
            clause_number="ART-99", title="Nonexistent category", category="OVERTIME"
        ),
        director_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_contract_clauses(unit["id"], analyst_headers))
    assert meta["total_count"] == 0, "a rejected clause must not be persisted"


def test_precedent_case_carries_no_updated_at_and_no_version(api, negotiator_headers):
    """PRD §2.5: "Two resource types are exceptions and carry only `id` and `created_at`:
    a `PrecedentCase`, which is immutable reference data once recorded, and a
    `PanelStrike`, which is an immutable event record. Neither has an `updated_at` field
    and neither has a `version` field; those keys are absent from their payloads entirely."
    PRD §3.1: "Precedents are immutable reference data — they carry no `updated_at` and no
    `version` — and report one derived counter, `cited_count`, the number of settlement
    offers naming them whose status is anything other than `VOIDED`, which reads 0 for a
    freshly recorded precedent."

    Design: Corner/entities/precedent_case_is_immutable_and_carries_no_version
    """
    unit = create_bargaining_unit()
    clause = create_contract_clause(unit["id"])
    precedent = create_precedent_case(clause["id"])

    read = validate_success(api.get_precedent_case(precedent["id"], negotiator_headers), 200)
    assert_precedent_case(read)

    assert "updated_at" not in read
    assert "version" not in read
    assert read["cited_count"] == 0
    assert read["binding_scope"] == "UNIT_WIDE"
    assert read["monetary_value_cents"] == 200_000

    rows, meta = validate_paginated(
        api.list_precedent_cases(negotiator_headers, params={"clause_id": clause["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == precedent["id"]


def test_arbitrator_registration_applies_roster_defaults(api, administrator_headers):
    """PRD §3.1: "An arbitrator carries a `full_name`, a non-empty `panel_memberships`
    array drawn from `AAA`, `FMCS` and `PERMANENT_UMPIRE`, a strictly positive
    `per_diem_cents` daily fee, a `cancellation_fee_cents` of zero or more charged when a
    scheduled hearing is abandoned, an `earliest_available_at` instant before which the
    arbitrator will accept no work, a `travel_buffer_hours` padding that defaults to 24 and
    is applied on **both** sides of every hearing they already have booked when calendar
    conflicts are tested, a `max_concurrent_cases` engagement ceiling defaulting to 3 and
    at least 1, and an `is_active` roster flag defaulting to true."
    PRD §3.1: "The system maintains `active_case_count` itself, starting at 0 and counting
    the arbitration demands currently engaging that arbitrator, and derives `status` from
    the other three: `INACTIVE` whenever `is_active` is false; otherwise `FULL` once
    `active_case_count` has reached `max_concurrent_cases`; otherwise `AVAILABLE`."

    Design: Corner/entities/arbitrator_creation_defaults_buffer_ceiling_and_active_flag
    """
    payload = {
        "full_name": "Ruth Alvarez",
        "panel_memberships": ["AAA", "FMCS"],
        "per_diem_cents": 250_000,
        "cancellation_fee_cents": 50_000,
        "earliest_available_at": "2026-08-01T00:00:00Z",
    }

    arbitrator = validate_success(api.create_arbitrator(payload, administrator_headers), 201)
    assert_arbitrator(arbitrator)

    assert arbitrator["travel_buffer_hours"] == 24
    assert arbitrator["max_concurrent_cases"] == 3
    assert arbitrator["is_active"] is True
    assert arbitrator["active_case_count"] == 0
    assert arbitrator["status"] == "AVAILABLE"
    assert arbitrator["panel_memberships"] == ["AAA", "FMCS"]
    assert arbitrator["version"] == 1


@pytest.mark.parametrize(
    "call_name, expected_error",
    [
        ("bargaining_unit", ApiErrorId.ERR_BARGAINING_UNIT_NOT_FOUND.value),
        ("employee", ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value),
        ("grievance", ApiErrorId.ERR_GRIEVANCE_NOT_FOUND.value),
        ("step", ApiErrorId.ERR_STEP_NOT_FOUND.value),
        ("offer", ApiErrorId.ERR_OFFER_NOT_FOUND.value),
        ("precedent", ApiErrorId.ERR_PRECEDENT_NOT_FOUND.value),
        ("demand", ApiErrorId.ERR_DEMAND_NOT_FOUND.value),
        ("arbitrator", ApiErrorId.ERR_ARBITRATOR_NOT_FOUND.value),
        ("award", ApiErrorId.ERR_AWARD_NOT_FOUND.value),
        ("cost_entry", ApiErrorId.ERR_COST_ENTRY_NOT_FOUND.value),
        ("witness_assignment", ApiErrorId.ERR_WITNESS_ASSIGNMENT_NOT_FOUND.value),
    ],
)
def test_unknown_path_identifier_returns_its_own_not_found_error(
    api, call_name, expected_error
):
    """PRD §2.9: "The not-found errors are resource-specific —
    `ERR_BARGAINING_UNIT_NOT_FOUND`, `ERR_GRIEVANCE_NOT_FOUND`, `ERR_STEP_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_PRECEDENT_NOT_FOUND`, `ERR_DEMAND_NOT_FOUND`,
    `ERR_ARBITRATOR_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_COST_ENTRY_NOT_FOUND`,
    `ERR_WITNESS_ASSIGNMENT_NOT_FOUND` and `ERR_EMPLOYEE_NOT_FOUND` — and all of them carry
    HTTP 404."

    Design: Corner/entities/unknown_path_identifiers_return_entity_specific_not_found
    """
    director = TEST_USERS["director_headers"]
    analyst = TEST_USERS["analyst_headers"]
    administrator = TEST_USERS["administrator_headers"]
    negotiator = TEST_USERS["negotiator_headers"]

    calls = {
        "bargaining_unit": lambda: api.get_bargaining_unit(UNKNOWN_UUID, director),
        "employee": lambda: api.get_employee(UNKNOWN_UUID, director),
        "grievance": lambda: api.get_grievance(UNKNOWN_UUID, analyst),
        "step": lambda: api.hold_grievance_step(UNKNOWN_UUID, analyst),
        "offer": lambda: api.get_settlement_offer(UNKNOWN_UUID, director),
        "precedent": lambda: api.get_precedent_case(UNKNOWN_UUID, negotiator),
        "demand": lambda: api.get_arbitration_demand(UNKNOWN_UUID, administrator),
        "arbitrator": lambda: api.get_arbitrator(UNKNOWN_UUID, administrator),
        "award": lambda: api.get_award(UNKNOWN_UUID, analyst),
        "cost_entry": lambda: api.void_cost_entry(
            UNKNOWN_UUID, {"void_reason": "no such entry"}, director
        ),
        "witness_assignment": lambda: api.confirm_witness_assignment(UNKNOWN_UUID, director),
    }

    response = calls[call_name]()
    validate_error(response, expected_error)


def test_unknown_body_reference_reports_the_matching_not_found_error(api, analyst_headers):
    """PRD §2.9: "A body naming a `bargaining_unit_id`, `grievant_id`,
    `respondent_supervisor_id`, `supervisor_id`, `clause_id`, `precedent_case_id`,
    `employee_id`, `arbitrator_id` or `consolidated_into_grievance_id` that resolves to
    nothing is rejected with the corresponding not-found error, where a missing clause is
    reported as `ERR_CLAUSE_NOT_FOUND`."

    Design: Corner/entities/unknown_body_references_return_not_found_for_clause_and_employee
    """
    ctx = setup_base()

    unknown_clause = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], UNKNOWN_UUID,
            statement="Unknown clause",
        ),
        ctx["steward_headers"],
    )
    validate_error(unknown_clause, ApiErrorId.ERR_CLAUSE_NOT_FOUND.value)

    unknown_grievant = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], UNKNOWN_UUID, ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Unknown grievant",
        ),
        ctx["steward_headers"],
    )
    validate_error(unknown_grievant, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value)

    _, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 0


def test_globally_unique_identifiers_reject_a_second_use(api, director_headers):
    """PRD §2.10: "Identifier uniqueness holds — otherwise `ERR_DUPLICATE_IDENTIFIER`.
    This guards four creations: a bargaining unit (`local_number` unique across the whole
    system), a contract clause (`clause_number` unique within its unit), a person
    (`employee_number` unique within their unit) and a precedent case (`citation` unique
    across the whole system)."

    Design: Corner/validations/duplicate_identifiers_rejected_across_their_declared_scopes
    """
    ctx = setup_base()
    create_precedent_case(ctx["clause"]["id"])

    duplicate_unit = api.create_bargaining_unit(bargaining_unit_payload(), director_headers)
    validate_error(duplicate_unit, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    duplicate_citation = api.create_precedent_case(
        precedent_case_payload(ctx["clause"]["id"]), director_headers
    )
    validate_error(duplicate_citation, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)


def test_per_unit_identifiers_collide_only_inside_their_own_unit(api, director_headers, analyst_headers):
    """PRD §3.1: "A clause carries a `clause_number` — the article designator, unique
    within its own agreement, colliding with `ERR_DUPLICATE_IDENTIFIER` — a human-readable
    `title`, and a `category` drawn from `DISCIPLINE`, `PAY`, `SENIORITY`, `SAFETY`,
    `LEAVE` and `SUBCONTRACTING`, which is the axis the office's trend analysis reports
    along and the axis the clause listing may be filtered on."
    PRD §3.1: "A person carries a `bargaining_unit_id`, a `full_name`, an `employee_number`
    unique within their own unit (again `ERR_DUPLICATE_IDENTIFIER` on collision), a
    `hire_date`, a `seniority_date` that must be at or after the hire date, an
    `hourly_rate_cents` that must be strictly positive, and a `classification` of
    `PRODUCTION`, `MAINTENANCE`, `CLERICAL` or `SUPERVISOR`."

    Design: Corner/validations/duplicate_identifiers_rejected_across_their_declared_scopes
    """
    ctx = setup_base()
    second_unit = create_bargaining_unit(
        name="Transit Local 2200", local_number="L2200"
    )

    duplicate_clause = api.create_contract_clause(
        ctx["unit"]["id"],
        contract_clause_payload(clause_number="ART-12", title="Duplicate clause"),
        director_headers,
    )
    validate_error(duplicate_clause, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    duplicate_employee = api.create_employee(
        employee_payload(ctx["unit"]["id"], employee_number="EMP-1"), director_headers
    )
    validate_error(duplicate_employee, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    # The same two identifiers are free inside a different agreement.
    reused_clause = api.create_contract_clause(
        second_unit["id"], contract_clause_payload(clause_number="ART-12"), director_headers
    )
    validate_success(reused_clause, 201)
    reused_employee = api.create_employee(
        employee_payload(second_unit["id"], employee_number="EMP-1"), director_headers
    )
    validate_success(reused_employee, 201)

    _, clause_meta = validate_paginated(
        api.list_contract_clauses(ctx["unit"]["id"], analyst_headers)
    )
    assert clause_meta["total_count"] == 1
    _, employee_meta = validate_paginated(
        api.list_employees(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert employee_meta["total_count"] == 3
