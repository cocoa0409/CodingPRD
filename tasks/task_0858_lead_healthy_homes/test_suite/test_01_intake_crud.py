"""Intake CRUD: children, dwellings, blood-lead tests — creation, validation, computed fields.

Queue B / entities.
"""
from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_dwelling_payload, create_child_payload, create_blood_lead_test_payload,
    assert_child, assert_dwelling, assert_blood_lead_test, TEST_USERS,
)

IC = TEST_USERS["intake_headers"]
PA = TEST_USERS["program_admin_headers"]


def _dwelling():
    return validate_success(api_client.create_dwelling(create_dwelling_payload(), PA), 201)


def test_register_child_returns_201_with_fields(api):
    """PRD §3.1: "An `IntakeCoordinator` (or a `ProgramAdmin`) registers a screened
    child by supplying the child's `full_name`, `date_of_birth` as an ISO 8601
    calendar date, the `guardian_name`, the `primary_dwelling_id` naming the child's
    current residence, and the household `income_tier`".
    PRD §2.4: "`version`, an integer that begins at 1 on creation and increments by 1
    on every mutation of the resource."

    Design: Corner/entities/child_creation_returns_201_with_fields
    """
    d = _dwelling()
    res = api_client.create_child(
        create_child_payload(d["id"], full_name="Pat Child", income_tier="LOW"), IC
    )
    child = validate_success(res, 201)
    assert_child(child)
    assert child["full_name"] == "Pat Child"
    assert child["income_tier"] == "LOW"
    assert child["version"] == 1


def test_get_nonexistent_child_returns_not_found(api):
    """PRD §2.8: "every path `id` and every foreign-key target in the body resolves
    to an existing resource, checked left to right in the order they appear; the first
    unresolved reference yields the matching `ERR_<RESOURCE>_NOT_FOUND` (404)."
    PRD §2.10: "A read of a child's blood-lead tests, for instance, first resolves the
    child (else `ERR_CHILD_NOT_FOUND`) before returning the list."

    Design: Corner/entities/child_get_nonexistent_returns_not_found
    """
    res = api_client.get_child(NON_EXISTENT_UUID, IC)
    validate_error(res, "ERR_CHILD_NOT_FOUND")


def test_register_child_missing_income_tier_returns_validation(api):
    """PRD §2.8: "required fields present, enum values legal, numeric fields at least 0,
    `occupant_count` at least 1, and pagination bounds in range, else `ERR_VALIDATION`
    (422)."

    Design: Corner/entities/child_missing_required_income_tier_returns_validation
    """
    d = _dwelling()
    payload = create_child_payload(d["id"])
    del payload["income_tier"]
    res = api_client.create_child(payload, IC)
    validate_error(res, "ERR_VALIDATION")


def test_register_child_default_medicaid_enrolled_false(api):
    """PRD §3.1: "A `medicaid_enrolled` flag may be supplied; when omitted it defaults
    to false, and it drives eligibility reporting."

    Design: Corner/entities/child_default_medicaid_enrolled_false
    """
    d = _dwelling()
    payload = create_child_payload(d["id"], income_tier="LOW")
    payload.pop("medicaid_enrolled", None)
    child = validate_success(api_client.create_child(payload, IC), 201)
    assert child["medicaid_enrolled"] is False


def test_dwelling_pre_1978_computed_input_ignored(api):
    """PRD §3.1: "From the construction year the system derives `pre_1978`, a boolean
    lead-paint presumption that is true exactly when `year_built` is earlier than 1978;
    any client-supplied value for this field is ignored."

    Design: Corner/entities/dwelling_computed_pre_1978_input_ignored
    """
    payload = create_dwelling_payload(street_address="1 Old St", year_built=1950)
    payload["pre_1978"] = False  # client-supplied value must be ignored
    d = validate_success(api_client.create_dwelling(payload, PA), 201)
    assert_dwelling(d)
    assert d["pre_1978"] is True


def test_blood_lead_test_is_immutable_audit_record(api):
    """PRD §2.4: "Two resources are exceptions that carry only `id` and `created_at` —
    they have neither an `updated_at` nor a `version`, because they are immutable audit
    records once written: `BloodLeadTest` and `ClearanceTest`."
    PRD §3.1: "the result is `CLASS_I` when the level is at least 45".

    Design: Corner/entities/bloodleadtest_immutable_has_no_version
    """
    d = _dwelling()
    child = validate_success(api_client.create_child(create_child_payload(d["id"]), IC), 201)
    res = api_client.create_blood_lead_test(
        create_blood_lead_test_payload(
            child["id"], bll_ug_dl=48.0, specimen_type="VENOUS", test_kind="DIAGNOSTIC"
        ), IC,
    )
    test = validate_success(res, 201)
    assert_blood_lead_test(test)
    assert test["result_class"] == "CLASS_I"
    assert "version" not in test
    assert "updated_at" not in test


def test_register_child_invalid_income_tier_enum_returns_validation(api):
    """PRD §2.8: "required fields present, enum values legal, numeric fields at least 0,
    `occupant_count` at least 1, and pagination bounds in range, else `ERR_VALIDATION`
    (422)."

    Design: Corner/entities/child_invalid_enum_income_tier_returns_validation
    """
    d = _dwelling()
    res = api_client.create_child(create_child_payload(d["id"], income_tier="RICH"), IC)
    validate_error(res, "ERR_VALIDATION")
