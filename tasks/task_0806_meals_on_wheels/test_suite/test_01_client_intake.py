"""Client intake, eligibility, income tier, and demographic-update tests."""
from test_helpers import (
    api_client,  # noqa: F401
    validate_success, validate_error, is_valid_uuid,
    create_client_payload, update_client_payload,
    assert_client,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
NUTRITION = TEST_USERS["nutritionist_headers"]


def test_client_create_returns_all_computed_fields(api):
    """PRD §3.1: "A freshly intake'd client enters the lifecycle in `INTAKE` status".
    PRD §3.1: "`oaa_eligible` is true exactly when that age in years is at least 60."
    PRD §3.1: "If the ratio is at or below 1.00 the client is `TIER_A`; otherwise if it
    is at or below 1.85 the client is `TIER_B`; otherwise the client is `TIER_C`."
    PRD §2.4: "an integer `version` that begins at 1 on creation".

    Design: Corner/entities/client_create_returns_all_fields
    """
    # income 120000, household 1 -> poverty 125500, ratio 0.956 -> TIER_A; born 1950 -> >= 60.
    resp = api.create_client(create_client_payload(), INTAKE)
    data = validate_success(resp, 201)
    assert_client(data)
    assert is_valid_uuid(data["id"]), "id must be a non-prefixed UUID"
    assert data["enrollment_status"] == "INTAKE"
    assert data["income_tier"] == "TIER_A", f"expected TIER_A, got {data['income_tier']}"
    assert data["oaa_eligible"] is True
    assert data["version"] == 1


def test_client_oaa_eligible_false_when_under_60(api):
    """PRD §3.1: "`oaa_eligible` is true exactly when that age in years is at least 60."

    Design: Corner/entities/client_oaa_eligible_false_when_under_60
    """
    resp = api.create_client(
        create_client_payload(full_name="Young Client", birth_date="2005-01-01", phone="555-0199"),
        INTAKE,
    )
    data = validate_success(resp, 201)
    assert data["oaa_eligible"] is False


def test_income_tier_at_ratio_one_is_tier_a(api):
    """PRD §3.1: "If the ratio is at or below 1.00 the client is `TIER_A`; otherwise if it
    is at or below 1.85 the client is `TIER_B`; otherwise the client is `TIER_C`. Both
    upper boundaries are inclusive."

    Design: Corner/calculations/income_tier_ratio_one_is_tier_a_boundary
    """
    # household 1 -> poverty 125500; income exactly 125500 -> ratio 1.00 -> TIER_A.
    edge_a = validate_success(
        api.create_client(create_client_payload(full_name="Edge A", monthly_income_cents=125500, phone="555-0201"), INTAKE),
        201,
    )
    assert edge_a["income_tier"] == "TIER_A"
    # income 130000 -> ratio 1.0359 > 1.00 -> TIER_B.
    edge_b = validate_success(
        api.create_client(create_client_payload(full_name="Edge B", monthly_income_cents=130000, phone="555-0202"), INTAKE),
        201,
    )
    assert edge_b["income_tier"] == "TIER_B"


def test_client_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "A missing required field or a value of the wrong primitive type yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/client_missing_required_field_returns_invalid_request
    """
    payload = create_client_payload()
    del payload["monthly_income_cents"]
    resp = api.create_client(payload, INTAKE)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_client_not_found_returns_404(api):
    """PRD §2.7: "the client is resolved first; if it does not exist the request fails
    with `ERR_CLIENT_NOT_FOUND` (HTTP 404) before any deeper resource is considered."

    Design: Corner/entities/client_not_found_returns_404
    """
    resp = api.get_client("00000000-0000-4000-8000-000000000000", INTAKE)
    validate_error(resp, "ERR_CLIENT_NOT_FOUND", 404)


def test_client_version_increments_by_one_on_patch(api):
    """PRD §2.4: "an integer `version` that begins at 1 on creation and increases by
    exactly 1 on every mutation that changes the resource".

    Design: Corner/cross_cutting_complexity_layers/client_version_increments_on_patch
    """
    created = validate_success(api.create_client(create_client_payload(), INTAKE), 201)
    assert created["version"] == 1
    resp = api.update_client(created["id"], update_client_payload(created["version"], phone="555-9999"), INTAKE)
    updated = validate_success(resp, 200)
    assert updated["version"] == 2, f"expected version 2, got {updated['version']}"


def test_nutritionist_cannot_create_client(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/nutritionist_cannot_create_client
    """
    resp = api.create_client(create_client_payload(), NUTRITION)
    validate_error(resp, "ERR_UNAUTHORIZED", 403)
