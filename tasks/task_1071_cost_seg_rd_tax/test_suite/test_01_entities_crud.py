"""Entity creation, defaults, computed fields, and not-found handling.

Translates queue B (Corner/entities) instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures,
)
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_client_creation_returns_201_with_defaults(api):
    """PRD §3.1: "A new client starts in `status` `ONBOARDING` with `outstanding_fee_cents` at 0."
    PRD §2.4: "a `version`, an integer that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/client_creation_returns_201_with_defaults
    """
    resp = api.create_client(
        f.create_client_payload(legal_name="New Co", entity_type="S_CORP",
                                marginal_tax_rate=0.30), SM)
    data = validate_success(resp, 201)
    assert data["status"] == "ONBOARDING"
    assert data["outstanding_fee_cents"] == 0
    assert data["version"] == 1


def test_get_study_not_found_returns_404(api):
    """PRD §2.7: "The first identifier in the path that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier or business rule is considered."

    Design: Corner/entities/get_study_not_found_returns_404
    """
    resp = api.get_study(NON_EXISTENT, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# NOTE: Corner/entities/property_missing_required_field_rejected is SKIPPED.
# It asserts ERR_VALIDATION for an omitted required field, but PRD names ERR_VALIDATION
# only in the §5 status table and states no prose trigger for a missing/malformed body
# field. Two PRD-only readers could return ERR_VALIDATION, ERR_INVALID_AMOUNT ("not
# positive"), or another 4xx — the outcome is not uniquely derivable. Coverage gap.


def test_study_is_look_back_defaults_false(api):
    """PRD §3.2: "and optionally `is_look_back`, which defaults to false and marks a study as
    eligible for a later amended-return catch-up." and "A new study begins in `status` `DRAFT`."

    Design: Corner/entities/study_is_look_back_defaults_false
    """
    cli = fixtures.create_client(api)
    resp = api.create_study(
        f.create_study_payload(cli["id"], "RD_CREDIT", tax_year=2024), SM)
    data = validate_success(resp, 201)
    assert data["is_look_back"] is False
    assert data["status"] == "DRAFT"


def test_property_depreciable_basis_computed(api):
    """PRD §3.1: "On creation the system computes the property's `depreciable_basis_cents` as
    the purchase price minus the land value."

    Design: Corner/entities/property_depreciable_basis_computed
    """
    cli = fixtures.create_client(api)
    resp = api.create_property(
        f.create_property_payload(cli["id"], building_type="INDUSTRIAL",
                                  purchase_price_cents=120000000, land_value_cents=20000000,
                                  placed_in_service_date="2024-01-01T00:00:00.000Z"), SM)
    data = validate_success(resp, 201)
    assert data["depreciable_basis_cents"] == 100000000
