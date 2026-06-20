"""Creation, uniqueness, not-found / existence precedence, RBAC, auth, append-only
entities, and list pagination.

Translates resource_temporal_overlap and the existence>state half of
priority_pair difficulty instances (queue A) plus the entities / errors / rbac /
endpoints corner instances (queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_plan_payload,
    create_filing_payload,
    create_participant,
    add_standard_comp_330k,
    create_submitted_js_election,
    record_spousal_consent,
    setup_terminated_vested_participant_330k,
    build_user_headers,
)

SPONSOR = TEST_USERS["plan_sponsor_headers"]
ACTUARY = TEST_USERS["plan_actuary_headers"]
ADMIN = TEST_USERS["benefits_admin_headers"]
ADM_A = TEST_USERS["benefits_admin_a_headers"]

# A path-shaped but non-existent UUID (matches the design index's chosen value).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / compensation_plan_year_uniqueness_per_participant
# ---------------------------------------------------------------------------
def test_duplicate_compensation_plan_year_rejected(api):
    """PRD §2.10: "an annual compensation row's `plan_year` is unique per participant..."
    PRD §2.10: "A create that would violate any of these yields `ERR_DUPLICATE_RESOURCE`."

    Design: Difficulty/resource_temporal_overlap/compensation_plan_year_uniqueness_per_participant
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    resp = api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 13_000_000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_distinct_compensation_plan_years_allowed(api):
    """PRD §2.10: "an annual compensation row's `plan_year` is unique per participant..."

    Design: Difficulty/resource_temporal_overlap/compensation_plan_year_uniqueness_per_participant
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2022, "gross_comp_cents": 12_000_000}, ADMIN))
    # Different year is not a uniqueness collision.
    resp = api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 13_000_000}, ADMIN)
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# resource_temporal_overlap / filing_plan_year_uniqueness_per_plan
# ---------------------------------------------------------------------------
def test_duplicate_filing_plan_year_rejected(api):
    """PRD §2.10: "a plan-year filing's `plan_year` is unique per plan..."
    PRD §2.10: "A create that would violate any of these yields `ERR_DUPLICATE_RESOURCE`."

    Design: Difficulty/resource_temporal_overlap/filing_plan_year_uniqueness_per_plan
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    get_success_data(api.create_filing(
        create_filing_payload(plan["id"], 2024, 8_000_000_000, 10_000_000_000), ACTUARY))
    resp = api.create_filing(
        create_filing_payload(plan["id"], 2024, 9_000_000_000, 10_000_000_000), ACTUARY)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_distinct_filing_plan_years_allowed(api):
    """PRD §2.10: "a plan-year filing's `plan_year` is unique per plan..."

    Design: Difficulty/resource_temporal_overlap/filing_plan_year_uniqueness_per_plan
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    get_success_data(api.create_filing(
        create_filing_payload(plan["id"], 2024, 8_000_000_000, 10_000_000_000), ACTUARY))
    resp = api.create_filing(
        create_filing_payload(plan["id"], 2025, 9_000_000_000, 10_000_000_000), ACTUARY)
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / existence_beats_state_on_election_approve
# ---------------------------------------------------------------------------
def test_approve_nonexistent_election_is_not_found(api):
    """PRD §2.9: "The server validates the identifiers in such a path strictly left to
    right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource."
    PRD §2.10: "Then path-referenced existence is checked left to right, yielding
    `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_election_approve
    """
    # A real plan exists; the election id does not.
    get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    resp = api.approve_election(MISSING_UUID, TEST_USERS["benefits_admin_b_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_approve_nonexistent_election_returns_404(api):
    """PRD §2.10: "Then path-referenced existence is checked left to right, yielding
    `ERR_NOT_FOUND`. ... Only after these structural checks does the system evaluate
    state-machine legality (`ERR_INVALID_STATE`, HTTP 409)..."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_election_approve
    """
    get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    resp = api.approve_election(MISSING_UUID, TEST_USERS["benefits_admin_b_headers"])
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Corner: entities / create_plan_returns_201_with_system_fields_and_open_posture
# ---------------------------------------------------------------------------
def test_create_plan_returns_201_with_open_posture(api):
    """PRD §3.1: "A new plan is created with `status` of `ACTIVE`, `funding_posture` of
    `OPEN`, and `version` equal to 1."

    Design: Corner/entities/create_plan_returns_201_with_system_fields_and_open_posture
    """
    resp = api.create_plan(create_plan_payload(
        benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015), SPONSOR)
    plan = validate_success(resp, expected_status=201)
    assert plan["status"] == "ACTIVE"
    assert plan["funding_posture"] == "OPEN"
    assert plan["version"] == 1


# ---------------------------------------------------------------------------
# Corner: entities / create_plan_missing_benefit_formula_type_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_plan_missing_benefit_formula_type_invalid_request(api):
    """PRD §3.1: "the variant selector `benefit_formula_type`, which is one of
    `FINAL_AVERAGE_PAY` or `CASH_BALANCE` and permanently pins which benefit calculation
    the plan uses."
    PRD §2.10: "the request body is checked for well-formedness — required fields present,
    enum values legal, amounts non-negative, dates in ISO-8601 form — yielding
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_plan_missing_benefit_formula_type_returns_invalid_request
    """
    resp = api.create_plan(
        {"plan_name": "Acme Bad", "ein_psn": "99-0000002-001", "fap_accrual_rate": 0.015}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: entities / get_participant_nonexistent_returns_not_found
# ---------------------------------------------------------------------------
def test_get_nonexistent_participant_not_found(api):
    """PRD §2.9: "rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_participant_nonexistent_returns_not_found
    """
    resp = api.get_participant("00000000-0000-4000-8000-0000000000aa", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: entities / spousal_consent_immutable_entity_no_version
# ---------------------------------------------------------------------------
def test_spousal_consent_created_without_version(api):
    """PRD §2.4: "A `ServiceCreditAdjustment` is an append-only event and a
    `SpousalConsent` is an immutable record of a witnessed waiver; both carry only `id`
    and `created_at`. Neither one carries `updated_at` and neither carries `version`,
    because once written they are never modified in place."

    Design: Corner/entities/spousal_consent_immutable_entity_no_version
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_submitted_js_election(participant["id"], submitter_headers=ADM_A)
    resp = api.create_spousal_consent(
        election["id"],
        {"consenting_spouse_dob": "1965-01-01", "notary_reference": "NOTARY-1", "waives_qjsa": True},
        ADMIN)
    consent = validate_success(resp, expected_status=201)
    assert consent["waives_qjsa"] is True
    assert "version" not in consent, "SpousalConsent must not carry version"
    assert "updated_at" not in consent, "SpousalConsent must not carry updated_at"


# ---------------------------------------------------------------------------
# Corner: state_machines / participant_terminate_initial_state_is_active
# ---------------------------------------------------------------------------
def test_new_participant_starts_active(api):
    """PRD §3.2: "A new participant starts with `employment_status` of `ACTIVE` and,
    before any service has accrued, `vesting_status` of `UNVESTED`."

    Design: Corner/state_machines/participant_terminate_initial_state_is_active
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    resp = api.create_participant(
        {"plan_id": plan["id"], "ssn_last4": "2006", "date_of_birth": "1962-01-01",
         "hire_date": "2000-01-01"}, ADMIN)
    participant = validate_success(resp, expected_status=201)
    assert participant["employment_status"] == "ACTIVE"
    # Hired 2000-01-01, measured at the 2025-01-01 as-of date -> well past 7y -> FULLY_VESTED.
    assert participant["vesting_status"] == "FULLY_VESTED"


# ---------------------------------------------------------------------------
# Corner: errors / duplicate_ein_psn_on_plan_create
# ---------------------------------------------------------------------------
def test_duplicate_ein_psn_rejected(api):
    """PRD §2.10: "a plan's `ein_psn` is unique across all plans..."
    PRD §2.10: "A create that would violate any of these yields `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/errors/duplicate_ein_psn_on_plan_create
    """
    ein = "99-0000022-001"
    get_success_data(api.create_plan(create_plan_payload(
        ein_psn=ein, benefit_formula_type="FINAL_AVERAGE_PAY", fap_accrual_rate=0.015), SPONSOR))
    resp = api.create_plan(create_plan_payload(
        ein_psn=ein, benefit_formula_type="CASH_BALANCE", fap_accrual_rate=0.0,
        cb_pay_credit_rate=0.05, cb_interest_crediting_rate=0.04), SPONSOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ---------------------------------------------------------------------------
# Corner: rbac / plan_sponsor_cannot_add_participant_forbidden
# ---------------------------------------------------------------------------
def test_plan_sponsor_cannot_add_participant(api):
    """PRD §2.1: "The `BenefitsAdministrator` is the third-party administrator that
    manages the census, compensation and service credit, elections, QDROs, payments, and
    COLA."
    PRD §2.1: "When the headers are present and well-formed but the caller's role is not
    permitted to invoke the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/plan_sponsor_cannot_add_participant_forbidden
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    resp = api.create_participant(
        {"plan_id": plan["id"], "ssn_last4": "2023", "date_of_birth": "1962-01-01",
         "hire_date": "2000-01-01"}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Corner: rbac / benefits_admin_cannot_certify_filing_forbidden
# ---------------------------------------------------------------------------
def test_benefits_admin_cannot_certify_filing(api):
    """PRD §2.1: "The `PlanActuary` is the enrolled actuary who drafts and certifies
    funded-status filings and prepares premium filings; it does not administer benefits or
    approve elections."
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/benefits_admin_cannot_certify_filing_forbidden
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    filing = get_success_data(api.create_filing(
        create_filing_payload(plan["id"], 2024, 8_000_000_000, 10_000_000_000), ACTUARY))
    # RBAC (403) fires before any OCC version check, so expected_plan_version is irrelevant.
    resp = api.certify_filing(filing["id"], {"expected_plan_version": plan["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Corner: rbac / missing_user_headers_unauthenticated
# ---------------------------------------------------------------------------
def test_missing_user_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_user_headers_unauthenticated
    """
    resp = api.get_participant("00000000-0000-4000-8000-0000000000bb", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_participants_filtered_by_plan_id_paginated
# ---------------------------------------------------------------------------
def test_list_participants_filtered_by_plan_id(api):
    """PRD §2.3: "The envelope's `meta` object on list responses carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: "The participant list endpoint accepts the optional query parameters
    `plan_id`, `employment_status`, and `vesting_status`."

    Design: Corner/endpoints/list_participants_filtered_by_plan_id_paginated
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    create_participant(plan["id"], ssn_last4="2101", date_of_birth="1962-01-01", hire_date="2000-01-01")
    create_participant(plan["id"], ssn_last4="2102", date_of_birth="1963-01-01", hire_date="2001-01-01")
    resp = api.list_participants(ACTUARY, params={"plan_id": plan["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert len(data) == 2
