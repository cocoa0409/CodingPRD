"""Corner queue - section entities, BeneficialOwner surface."""
from test_helpers import (
    ApiErrorId,
    new_jurisdiction,
    new_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _respondent():
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    return new_respondent("DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
                          expected_monthly_volume_usd=500000.00, expected_monthly_count=100)


def test_create_beneficial_owner_computes_chain_depth_and_effective_pct(api):
    """The look-through multiplies the whole ancestor chain and divides once by 100 raised
    to one less than the node count, so 60.00 over 50.00 is exactly 30.00 at depth 2.

    Design: Corner/entities/create_beneficial_owner_computes_chain_depth_and_effective_pct
    """
    rid = _respondent()["id"]
    parent = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Holdco GmbH", "owner_type": "LEGAL_ENTITY",
             "ownership_pct": 60.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )

    child = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Anna Weber", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 50.00, "country_of_residence": "DE",
             "parent_owner_id": parent["id"]},
            ANALYST,
        ),
        expected_status=201,
    )

    assert child["chain_depth"] == 2
    assert child["effective_ownership_pct"] == 30.00
    assert child["verification_status"] == "PENDING"
    assert parent["chain_depth"] == 1
    assert parent["effective_ownership_pct"] == 60.00


def test_create_beneficial_owner_unknown_parent_owner_returns_not_found(api):
    """A body-supplied `parent_owner_id` resolves to the same error id as the path segment
    would, and it is resolved before any cycle, depth or percentage rule runs.

    Design: Corner/entities/create_beneficial_owner_unknown_parent_owner_returns_not_found
    """
    rid = _respondent()["id"]

    response = api.create_beneficial_owner(
        rid,
        {"owner_name": "Orphan Ltd", "owner_type": "LEGAL_ENTITY", "ownership_pct": 10.00,
         "country_of_residence": "DE",
         "parent_owner_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_BENEFICIAL_OWNER_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_beneficial_owners(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 0


def test_create_beneficial_owner_ownership_pct_zero_rejected(api):
    """The declared domain is open at the bottom - strictly greater than 0.00 - so 0.00 is
    a range violation rather than an accepted zero stake.

    Design: Corner/entities/create_beneficial_owner_ownership_pct_zero_rejected
    """
    rid = _respondent()["id"]

    response = api.create_beneficial_owner(
        rid,
        {"owner_name": "Zero Stake Ltd", "owner_type": "LEGAL_ENTITY", "ownership_pct": 0.00,
         "country_of_residence": "DE"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_FIELD_OUT_OF_RANGE)


def test_create_beneficial_owner_unknown_country_of_residence_returns_not_found(api):
    """`country_of_residence` is one of the seven jurisdiction-code fields, so an
    unresolvable code fails the same referential check as the home jurisdiction does.

    Design: Corner/entities/create_beneficial_owner_unknown_country_of_residence_returns_not_found
    """
    rid = _respondent()["id"]

    response = api.create_beneficial_owner(
        rid,
        {"owner_name": "Offshore Trust", "owner_type": "LEGAL_ENTITY", "ownership_pct": 30.00,
         "country_of_residence": "XX"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_PROFILE_NOT_FOUND)
