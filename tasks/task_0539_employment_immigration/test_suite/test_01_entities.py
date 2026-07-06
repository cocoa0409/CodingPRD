"""Entity creation, retrieval, validation, defaults, and computed fields (PRD §3).

Queue B / Corner — section `entities`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    is_valid_uuid, assert_employer, assert_beneficiary,
    employer_payload, lca_payload, pwd_payload,
    make_employer_agent_headers, TEST_USERS,
    create_employer,
)

EMPLOYER = TEST_USERS["employer_agent_headers"]


def test_employer_create_returns_201_with_zeroed_ledger_and_version_one(api):
    """PRD §3.1: "On registration the employer's `total_wage_obligation_cents`
    starts at 0 and its `version` starts at 1."
    PRD §4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/employer_create_returns_201_with_zeroed_ledger_and_version_one
    """
    res = api.create_employer(employer_payload(legal_name="Corner Corp", employee_count=10), EMPLOYER)
    emp = validate_success(res, 201)
    assert_employer(emp)
    assert emp["total_wage_obligation_cents"] == 0
    assert emp["version"] == 1


def test_employer_get_returns_stored_entity(api):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/entities/employer_get_returns_stored_entity
    """
    emp = create_employer(legal_name="Readback LLC", employee_count=12)
    res = api.get_employer(emp["id"], make_employer_agent_headers(emp["id"]))
    fetched = validate_success(res, 200)
    assert fetched["legal_name"] == "Readback LLC"
    assert fetched["id"] == emp["id"]


def test_employer_get_nonexistent_returns_404(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource causes an immediate `ERR_NOT_FOUND` (HTTP 404); later references
    are not examined once the first missing one is found."

    Design: Corner/entities/employer_get_nonexistent_returns_404
    """
    res = api.get_employer(NON_EXISTENT_UUID, EMPLOYER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_pwd_employer_survey_missing_survey_wage_rejected(api):
    """PRD §3.2: "When `wage_source` is `EMPLOYER_SURVEY`, the request must also
    carry `survey_wage_cents`, the employer-provided annual survey wage; omitting
    it in that case is an `ERR_VALIDATION` (400)."

    Design: Corner/entities/pwd_employer_survey_missing_survey_wage_rejected
    """
    emp = create_employer()
    payload = pwd_payload(emp["id"], wage_source="EMPLOYER_SURVEY")
    payload.pop("survey_wage_cents", None)
    res = api.create_pwd(payload, make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_employer_h1b_dependent_defaults_false(api):
    """PRD §3.1: "The agent may also set `h1b_dependent`, a boolean flag that
    defaults to false and later drives one of the larger filing-fee add-ons."

    Design: Corner/entities/employer_h1b_dependent_defaults_false
    """
    payload = employer_payload(legal_name="Default Co", employee_count=30)
    payload.pop("h1b_dependent", None)
    emp = validate_success(api.create_employer(payload, EMPLOYER), 201)
    assert emp["h1b_dependent"] is False


def test_lca_hours_per_week_defaults_40(api):
    """PRD §3.4: "an optional `hours_per_week` that defaults to 40 and must fall
    between 1 and 40 inclusive".
    PRD §3.4: "each area's entry in `area_wage_map` is multiplied by
    `hours_per_week`, divided by 40, and rounded half up to whole cents".

    Design: Corner/entities/lca_hours_per_week_defaults_40
    """
    emp = create_employer()
    payload = lca_payload(emp["id"])
    payload.pop("hours_per_week", None)
    lca = validate_success(api.create_lca(payload, make_employer_agent_headers(emp["id"])), 201)
    assert lca["hours_per_week"] == 40
    assert lca["aggregate_wage_obligation_cents"] == 10000000


def test_pwd_invalid_wage_level_enum_rejected(api):
    """PRD §2.9: "required fields present, enums valid, numbers in range, and the
    field-level rules of §2.5/§3 satisfied; otherwise `ERR_VALIDATION` (400)."
    PRD §3.2: "the `wage_level` (one of `LEVEL_I`, `LEVEL_II`, `LEVEL_III`, or
    `LEVEL_IV`)".

    Design: Corner/entities/pwd_invalid_wage_level_enum_rejected
    """
    emp = create_employer()
    res = api.create_pwd(pwd_payload(emp["id"], wage_level="LEVEL_V"),
                         make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_lca_validity_end_not_after_start_rejected(api):
    """PRD §3.4: "the validity window `validity_start` through `validity_end`,
    where `validity_end` must be strictly after `validity_start`."

    Design: Corner/entities/lca_validity_end_not_after_start_rejected
    """
    emp = create_employer()
    res = api.create_lca(
        lca_payload(emp["id"], validity_start="2026-05-01T00:00:00Z",
                    validity_end="2026-05-01T00:00:00Z"),
        make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_lca_area_wage_map_missing_worksite_area_rejected(api):
    """PRD §3.4: "If the `area_wage_map` fails to cover every entry in
    `worksite_areas`, the create is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/lca_area_wage_map_missing_worksite_area_rejected
    """
    emp = create_employer()
    res = api.create_lca(
        lca_payload(emp["id"], worksite_areas=["AREA_A", "AREA_B"],
                    area_wage_map={"AREA_A": 10000000}),
        make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_perm_case_create_unknown_pwd_fk_returns_404(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource causes an immediate `ERR_NOT_FOUND` (HTTP 404); later references
    are not examined once the first missing one is found."

    Design: Corner/entities/perm_case_create_unknown_pwd_fk_returns_404
    """
    emp = create_employer()
    res = api.create_perm_case(
        {"employer_id": emp["id"], "pwd_id": NON_EXISTENT_UUID,
         "job_title": "SWE", "offered_wage_cents": 12000000},
        make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_beneficiary_computed_status_none_at_creation(api):
    """PRD §3.6: "`current_status_code` is `NONE` when the beneficiary has no
    `APPROVED` H-1B petition".
    PRD §3.6: "`status_valid_until` is the maximum `employment_end` across the
    beneficiary's `APPROVED` H-1B petitions, or null when there are none."
    PRD §3.6: "`priority_date` on the beneficiary is the earliest `priority_date`
    across the beneficiary's `APPROVED` green-card petitions (with `created_at`
    ascending as the tie-break), or null when there are none."

    Design: Corner/entities/beneficiary_computed_status_none_at_creation
    """
    emp = create_employer()
    res = api.create_beneficiary({"full_name": "Fresh Worker", "passport_number": "P-CORNER-1"},
                                 make_employer_agent_headers(emp["id"]))
    ben = validate_success(res, 201)
    assert_beneficiary(ben)
    assert ben["current_status_code"] == "NONE"
    assert ben["status_valid_until"] is None
    assert ben["priority_date"] is None


def test_employer_system_fields_generated_ignoring_input(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
    PRD §2.4: "`version` is an integer that begins at 1 on creation and increments
    by one on every mutation".

    Design: Corner/entities/employer_system_fields_generated_ignoring_input
    """
    emp = validate_success(
        api.create_employer(employer_payload(legal_name="SysField Co", employee_count=5), EMPLOYER), 201)
    assert emp["version"] == 1
    assert is_valid_uuid(emp["id"])
