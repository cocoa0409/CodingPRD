"""Registration defaults, request-shape validation, uniqueness, and RBAC basics."""
import re

from test_helpers import (
    ADMIN, ApiErrorId, MANAGER, NON_EXISTENT_UUID, build_pipeline,
    create_contract_payload, create_member_payload, create_program_payload,
    create_quality_result_payload, create_risk_score_payload,
    create_span_payload, make_contract, make_member, make_program, make_year,
    make_group, make_span, set_clock, setup_org, validate_error,
    validate_paginated, validate_success,
)
from test_helpers import (
    CLOCK_START, SINGLE_MEASURE_CATALOG, QUALITY_CANONICAL_SINGLE,
)

ISO8601_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_program_create_applies_system_defaults(api, payer_admin_headers):
    """PRD §3.1: "The program's `program_status` field is set to `DRAFT` at creation and transitions `DRAFT → ACTIVE` when the admin activates it."
    PRD §2.5: "`version` — an integer starting at 1, incremented by exactly 1 on every mutation."
    PRD §2.5: "`id` — a server-minted UUID with no type prefix."
    PRD §2.5: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation."

    Design: Corner/entities/program_create_applies_system_defaults
    """
    resp = api.create_program(create_program_payload(), payer_admin_headers)
    data = validate_success(resp, 201)
    assert data["program_status"] == "DRAFT", "program must be created in DRAFT"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert ISO8601_MILLIS.match(data["created_at"]), (
        f"created_at must carry three fractional digits, got {data['created_at']!r}"
    )
    assert ISO8601_MILLIS.match(data["updated_at"]), (
        f"updated_at must carry three fractional digits, got {data['updated_at']!r}"
    )
    # program_status is system-managed: supplying it is an unknown input field.
    bad = dict(create_program_payload(program_name="P2"))
    bad["program_status"] = "ACTIVE"
    resp2 = api.create_program(bad, payer_admin_headers)
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)


def test_contract_create_missing_required_field_returns_400(api, contract_manager_headers):
    """PRD §2.8: "5. **Request shape** — required fields present, no unknown fields, types valid, enum values in their declared domain, scalar ranges satisfied (`birth_year` between 1900 and 2026 inclusive, `score_milli` between 1 and 10000 inclusive, `months_elapsed` between 1 and 11 inclusive); otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.3: "The `benchmark_pmpm_cents` is the per-member-per-month benchmark cost in cents and must be strictly positive."

    Design: Corner/entities/contract_create_missing_required_field_returns_400
    """
    org = setup_org(member_specs=[], practice_count=0)
    payload = create_contract_payload(org["program"]["id"], org["group"]["id"])
    del payload["benchmark_pmpm_cents"]
    resp = api.create_contract(payload, contract_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(api.list_contracts(contract_manager_headers))
    assert data == [], "a rejected create must not persist a contract"


def test_member_duplicate_ref_rejected(api, payer_admin_headers):
    """PRD §3.2: "Each covered life is a `Member`, registered by a `PayerAdmin` with the `program_id` of the covering program, a payer-external `member_ref` unique within that program, and a `birth_year` between 1900 and 2026 inclusive."
    PRD §2.8: "11. **Uniqueness** — `tin` globally (`ERR_DUPLICATE_TIN`), `npi` globally (`ERR_DUPLICATE_NPI`), `member_ref` within a program (`ERR_DUPLICATE_MEMBER_REF`), `contract_ref` within a program (`ERR_DUPLICATE_CONTRACT_REF`), `year_label` within a contract (`ERR_DUPLICATE_YEAR_LABEL`), `claim_ref` within a year (`ERR_DUPLICATE_CLAIM_REF`), one non-`SUPERSEDED` `RiskScore` per (member, year, `model_used`) (`ERR_DUPLICATE_RISK_SCORE`), one non-`EXCLUDED` `QualityMeasureResult` per (year, `measure_code`) (`ERR_DUPLICATE_MEASURE_RESULT`), at most one non-`VOID` `Settlement` per year (`ERR_SETTLEMENT_EXISTS`), and the reported `measure_code` must exist in the contract's `quality_measures` catalog (`ERR_UNKNOWN_MEASURE_CODE`). All 409."

    Design: Corner/entities/member_duplicate_ref_rejected
    """
    p1 = make_program(program_name="P1")
    p2 = make_program(program_name="P2")
    ok = api.create_member(
        create_member_payload(p1["id"], member_ref="M-001", birth_year=1981),
        payer_admin_headers,
    )
    validate_success(ok, 201)
    dup = api.create_member(
        create_member_payload(p1["id"], member_ref="M-001", birth_year=1981),
        payer_admin_headers,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_MEMBER_REF)
    other = api.create_member(
        create_member_payload(p2["id"], member_ref="M-001", birth_year=1981),
        payer_admin_headers,
    )
    validate_success(other, 201)


def test_claim_get_nonexistent_returns_not_found(api, claims_processor_headers):
    """PRD §2.8: "3. **Existence** — path resource identifiers are validated left-to-right; the first missing id produces `ERR_NOT_FOUND` (404). Body foreign-key references are also validated here."

    Design: Corner/entities/claim_get_nonexistent_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, claims_processor_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_claim_create_with_unknown_field_rejected(api, claims_processor_headers):
    """PRD §2.8: "5. **Request shape** — required fields present, no unknown fields, types valid, enum values in their declared domain, scalar ranges satisfied (`birth_year` between 1900 and 2026 inclusive, `score_milli` between 1 and 10000 inclusive, `months_elapsed` between 1 and 11 inclusive); otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.7: "A claim's `claim_status` is created as `RECEIVED`."

    Design: Corner/entities/claim_create_with_unknown_field_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])
    payload = {
        "performance_year_id": year["id"],
        "member_id": org["members"][0]["id"],
        "claim_ref": "CL-1",
        "service_date": "2026-03-10",
        "paid_amount_cents": 1000,
        "claim_status": "PAID",
    }
    resp = api.create_claim(payload, claims_processor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_eligibility_span_inverted_range_rejected(api, payer_admin_headers):
    """PRD §2.8: "12. **Fiscal and rate sanity** — `benchmark_pmpm_cents` strictly positive; all basis-point rates in 0..10000 inclusive; a `TWO_SIDED` contract must carry `shared_loss_rate_bp` and `loss_cap_bp`; `quality_gate_floor_points` strictly less than `quality_gate_excellence_points` with both in 0..100; every entry in `quality_measures` has a positive weight and exactly 9 strictly ascending decile thresholds. Violations of this family produce `ERR_INVALID_RATE_CONFIG` (422). `paid_amount_cents` and `claimed_adjustment_cents` must be strictly positive (`ERR_INVALID_AMOUNT`, 422). Start dates must be strictly before end dates on span, contract, and year creation (`ERR_INVALID_DATE_RANGE`, 422)."

    Design: Corner/entities/eligibility_span_inverted_range_rejected
    """
    program = make_program()
    member = make_member(program["id"])
    resp = api.create_eligibility_span(
        create_span_payload(member["id"], start_date="2026-12-31", end_date="2026-01-01"),
        payer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_score_milli_out_of_range_rejected(api, actuary_analyst_headers):
    """PRD §2.8: "5. **Request shape** — required fields present, no unknown fields, types valid, enum values in their declared domain, scalar ranges satisfied (`birth_year` between 1900 and 2026 inclusive, `score_milli` between 1 and 10000 inclusive, `months_elapsed` between 1 and 11 inclusive); otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.6: "An `ActuaryAnalyst` ingests a `RiskScore` by supplying the `member_id`, the `performance_year_id`, a `model_used` of `PROSPECTIVE` or `CONCURRENT`, and a `score_milli` between 1 and 10000 inclusive."

    Design: Corner/entities/score_milli_out_of_range_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])
    too_big = api.create_risk_score(
        create_risk_score_payload(
            org["members"][0]["id"], year["id"], model_used="PROSPECTIVE", score_milli=20000
        ),
        actuary_analyst_headers,
    )
    validate_error(too_big, ApiErrorId.ERR_INVALID_REQUEST)
    at_boundary = api.create_risk_score(
        create_risk_score_payload(
            org["members"][0]["id"], year["id"], model_used="PROSPECTIVE", score_milli=10000
        ),
        actuary_analyst_headers,
    )
    data = validate_success(at_boundary, 201)
    assert data["score_milli"] == 10000, "the 10000 upper boundary is inclusive"


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value that does not match one of these eleven names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = api.create_program(
        {"program_name": "P1", "line_of_business": "MEDICARE_ADVANTAGE"}, headers={}
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_existence_precedes_state_on_claim_void(api, claims_processor_headers):
    """PRD §2.8: "3. **Existence** — path resource identifiers are validated left-to-right; the first missing id produces `ERR_NOT_FOUND` (404). Body foreign-key references are also validated here."
    PRD §2.8: "Every request traverses a fixed priority cascade; the first failing rule wins and produces the response."

    Design: Corner/validations/existence_precedes_state_on_claim_void
    """
    resp = api.void_claim(NON_EXISTENT_UUID, claims_processor_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_duplicate_year_label_rejected(api, payer_admin_headers):
    """PRD §3.4: "A `PayerAdmin` creates a year by supplying the `contract_id`, an integer `year_label` (unique within the contract), an inclusive `period_start`, and an exclusive `period_end`; the year's `year_status` is set to `SETUP`."
    PRD §2.8: "11. **Uniqueness** — `tin` globally (`ERR_DUPLICATE_TIN`), `npi` globally (`ERR_DUPLICATE_NPI`), `member_ref` within a program (`ERR_DUPLICATE_MEMBER_REF`), `contract_ref` within a program (`ERR_DUPLICATE_CONTRACT_REF`), `year_label` within a contract (`ERR_DUPLICATE_YEAR_LABEL`), `claim_ref` within a year (`ERR_DUPLICATE_CLAIM_REF`), one non-`SUPERSEDED` `RiskScore` per (member, year, `model_used`) (`ERR_DUPLICATE_RISK_SCORE`), one non-`EXCLUDED` `QualityMeasureResult` per (year, `measure_code`) (`ERR_DUPLICATE_MEASURE_RESULT`), at most one non-`VOID` `Settlement` per year (`ERR_SETTLEMENT_EXISTS`), and the reported `measure_code` must exist in the contract's `quality_measures` catalog (`ERR_UNKNOWN_MEASURE_CODE`). All 409."

    Design: Corner/validations/duplicate_year_label_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    c1 = make_contract(
        org["program"]["id"], org["group"]["id"], contract_ref="C-1",
        effective_end="2028-01-01",
    )
    make_year(c1["id"], year_label=2026)
    dup = api.create_performance_year(
        {
            "contract_id": c1["id"],
            "year_label": 2026,
            "period_start": "2027-01-01",
            "period_end": "2028-01-01",
        },
        payer_admin_headers,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_YEAR_LABEL)
    c2 = make_contract(org["program"]["id"], org["group"]["id"], contract_ref="C-2")
    ok = api.create_performance_year(
        {
            "contract_id": c2["id"],
            "year_label": 2026,
            "period_start": "2026-01-01",
            "period_end": "2027-01-01",
        },
        payer_admin_headers,
    )
    validate_success(ok, 201)


def test_unknown_measure_code_rejected(api, quality_analyst_headers):
    """PRD §3.8: "A `QualityAnalyst` reports a `QualityMeasureResult` by supplying the `performance_year_id`, a `measure_code` that must exist in the year's contract `quality_measures` catalog (`ERR_UNKNOWN_MEASURE_CODE`), a `numerator_count`, and a `denominator_count`."

    Design: Corner/validations/unknown_measure_code_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(
        org["program"]["id"], org["group"]["id"], quality_measures=SINGLE_MEASURE_CATALOG
    )
    year = make_year(contract["id"])
    resp = api.create_quality_result(
        create_quality_result_payload(
            year["id"], measure_code="HCC_BETA", numerator_count=1, denominator_count=10
        ),
        quality_analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_MEASURE_CODE)


def test_numerator_exceeds_denominator_rejected(api, quality_analyst_headers):
    """PRD §3.8: "The numerator must not exceed the denominator (`ERR_NUMERATOR_EXCEEDS_DENOMINATOR`), and the denominator must be at least 1 by the time the result is validated (`ERR_EMPTY_DENOMINATOR`)."

    Design: Corner/validations/numerator_exceeds_denominator_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(
        org["program"]["id"], org["group"]["id"], quality_measures=SINGLE_MEASURE_CATALOG
    )
    year = make_year(contract["id"])
    over = api.create_quality_result(
        create_quality_result_payload(
            year["id"], measure_code="HBA1C", numerator_count=1001, denominator_count=1000
        ),
        quality_analyst_headers,
    )
    validate_error(over, ApiErrorId.ERR_NUMERATOR_EXCEEDS_DENOMINATOR)
    equal = api.create_quality_result(
        create_quality_result_payload(
            year["id"], measure_code="HBA1C", numerator_count=1000, denominator_count=1000
        ),
        quality_analyst_headers,
    )
    validate_success(equal, 201)


def test_empty_denominator_validate_rejected(api, quality_analyst_headers):
    """PRD §3.8: "The numerator must not exceed the denominator (`ERR_NUMERATOR_EXCEEDS_DENOMINATOR`), and the denominator must be at least 1 by the time the result is validated (`ERR_EMPTY_DENOMINATOR`)."
    PRD §3.8: "Exclusion is a terminal action available from any of `REPORTED`, `VALIDATED`, or `LOCKED` (transitions `REPORTED → EXCLUDED`, `VALIDATED → EXCLUDED`, and `LOCKED → EXCLUDED`), provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`)."

    Design: Corner/validations/empty_denominator_validate_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(
        org["program"]["id"], org["group"]["id"], quality_measures=SINGLE_MEASURE_CATALOG
    )
    year = make_year(contract["id"])
    created = api.create_quality_result(
        create_quality_result_payload(
            year["id"], measure_code="HBA1C", numerator_count=0, denominator_count=0
        ),
        quality_analyst_headers,
    )
    result = validate_success(created, 201)
    resp = api.validate_quality_result(result["id"], quality_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_DENOMINATOR)
    excluded = api.exclude_quality_result(result["id"], quality_analyst_headers)
    assert validate_success(excluded)["result_status"] == "EXCLUDED"


def test_two_sided_missing_loss_fields_rejected(api, contract_manager_headers):
    """PRD §3.3: "`shared_loss_rate_bp` plays the symmetric role on the downside and is required if and only if the contract is `TWO_SIDED`."
    PRD §2.8: "12. **Fiscal and rate sanity** — `benchmark_pmpm_cents` strictly positive; all basis-point rates in 0..10000 inclusive; a `TWO_SIDED` contract must carry `shared_loss_rate_bp` and `loss_cap_bp`; `quality_gate_floor_points` strictly less than `quality_gate_excellence_points` with both in 0..100; every entry in `quality_measures` has a positive weight and exactly 9 strictly ascending decile thresholds. Violations of this family produce `ERR_INVALID_RATE_CONFIG` (422). `paid_amount_cents` and `claimed_adjustment_cents` must be strictly positive (`ERR_INVALID_AMOUNT`, 422). Start dates must be strictly before end dates on span, contract, and year creation (`ERR_INVALID_DATE_RANGE`, 422)."

    Design: Corner/validations/two_sided_missing_loss_fields_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    two_sided = create_contract_payload(
        org["program"]["id"], org["group"]["id"], contract_ref="C-T", min_loss_rate_bp=200
    )
    del two_sided["shared_loss_rate_bp"]
    del two_sided["loss_cap_bp"]
    resp = api.create_contract(two_sided, contract_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_RATE_CONFIG)

    one_sided = create_contract_payload(
        org["program"]["id"], org["group"]["id"],
        contract_ref="C-O", risk_track="ONE_SIDED_UPSIDE",
    )
    del one_sided["shared_loss_rate_bp"]
    del one_sided["loss_cap_bp"]
    del one_sided["min_loss_rate_bp"]
    ok = api.create_contract(one_sided, contract_manager_headers)
    validate_success(ok, 201)


def test_auditor_cannot_create_program(api, auditor_headers):
    """PRD §2.1: "A request whose role is recognized but which is not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/vbc/programs` | Create a program in DRAFT | PayerAdmin |"

    Design: Corner/rbac/auditor_cannot_create_program
    """
    resp = api.create_program(create_program_payload(), auditor_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_error_envelope_shape_on_not_found(api, payer_admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.8: "3. **Existence** — path resource identifiers are validated left-to-right; the first missing id produces `ERR_NOT_FOUND` (404). Body foreign-key references are also validated here."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    resp = api.get_program(NON_EXISTENT_UUID, payer_admin_headers)
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_contract_activate_twice_rejected(api, contract_manager_headers):
    """PRD §3.3: "A contract's `contract_status` is created as `DRAFT`. Activation (`DRAFT → ACTIVE`) is performed by a `ContractManager` and is guarded by two preconditions evaluated in cascade order: the program must be in `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`) and the contracted group must be in `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`)."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."
    PRD §2.5: "`version` — an integer starting at 1, incremented by exactly 1 on every mutation."

    Design: Corner/state_machines/contract_activate_twice_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(org["program"]["id"], org["group"]["id"], activate=False)
    first = api.activate_contract(contract["id"], contract_manager_headers)
    activated = validate_success(first)
    assert activated["contract_status"] == "ACTIVE"
    assert activated["version"] == 2, "the activation mutation increments version to 2"
    second = api.activate_contract(contract["id"], contract_manager_headers)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reread = validate_success(api.get_contract(contract["id"], contract_manager_headers))
    assert reread["contract_status"] == "ACTIVE"
    assert reread["version"] == 2, "a rejected transition must not mutate the contract"
