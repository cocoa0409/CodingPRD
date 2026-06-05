"""Queue B (breadth) — entity-level creation, defaults, computed fields,
type constraints, immutability, and listing envelopes.
"""
from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_region, create_landlord, create_unit, make_eligible_household,
    create_region_payload, create_household_payload, create_payment_standard_payload,
    create_voucher_payload, create_rent_reasonableness_payload, create_payment_standard,
    ADMIN, CASEWORKER,
)


def test_create_region_returns_201_with_fields():
    """PRD §2.9: "It is created with a code ... a human-readable name, an
    fmr_year ... and an is_special_mobility_area flag that, when omitted,
    defaults to false". PRD §2.4: "version — an integer that begins at its
    initial value on creation".

    Design: Corner/entities/create_region_returns_201_with_fields
    """
    region = validate_success(
        api_client.create_region(
            create_region_payload(code="REGION_ONE", name="Region One", fmr_year=2026), ADMIN
        ),
        201,
    )
    assert region["code"] == "REGION_ONE"
    assert region["version"] == 1
    assert region["is_special_mobility_area"] is False


def test_get_household_not_found_returns_404():
    """PRD §2.8: "The first referenced resource that does not exist causes the
    request to be rejected with ERR_NOT_FOUND (HTTP 404) before any business
    rule is evaluated."

    Design: Corner/entities/get_household_not_found_returns_404
    """
    validate_error(
        api_client.get_household(NON_EXISTENT_UUID, CASEWORKER), "ERR_NOT_FOUND", 404
    )


def test_create_household_missing_required_field_returns_400():
    """PRD §3.2: "A Caseworker registers a household application by supplying the
    head of household's head_name, the family_size (the number of persons, at
    least one)". PRD §2.8: "the catch-all structural check — required body fields
    present, correctly typed ... surfaces as ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/create_household_missing_required_field_returns_400
    """
    region = create_region(code="RQA")
    payload = {"head_name": "No Size", "annual_income_cents": 1000000, "region_id": region["id"]}
    validate_error(api_client.create_household(payload, CASEWORKER), "ERR_VALIDATION", 400)


def test_household_default_dependents_zero():
    """PRD §3.2: "dependents_count (the number of dependents, defaulting to zero
    and never negative), elderly_or_disabled (a flag, defaulting to false ...)".

    Design: Corner/entities/household_default_dependents_zero
    """
    region = create_region(code="RDA")
    hh = validate_success(
        api_client.create_household(
            create_household_payload(
                region["id"], head_name="Def Fam", family_size=2,
                annual_income_cents=1000000,
            ),
            CASEWORKER,
        ),
        201,
    )
    assert hh["dependents_count"] == 0
    assert hh["elderly_or_disabled"] is False


def test_voucher_bedroom_size_computed_not_from_input():
    """PRD §3.3: "The voucher's bedroom_size is computed from the household's
    family size by the occupancy standard rather than supplied ... otherwise the
    bedroom count is the family size divided by two and rounded up to the next
    whole number". Family of 4 -> 2 bedrooms.

    Design: Corner/entities/voucher_bedroom_size_computed_input_ignored
    """
    region = create_region(code="RCA")
    household = make_eligible_household(region["id"], family_size=4, annual_income_cents=1800000)
    voucher = validate_success(
        api_client.create_voucher(create_voucher_payload(household["id"]), CASEWORKER), 201
    )
    assert voucher["bedroom_size"] == 2


def test_payment_standard_bad_bedroom_size_rejected():
    """PRD §3.1: "A payment standard is created against a region ... for a
    specific bedroom_size — a bedroom count from 0 (studio) through 6." PRD §2.8:
    structural enum/range violations surface as ERR_VALIDATION (HTTP 400).

    Design: Corner/entities/payment_standard_bad_bedroom_size_enum_range
    """
    region = create_region(code="RTA")
    payload = create_payment_standard_payload(
        region["id"], bedroom_size=7, amount_cents=90000, fmr_cents=100000
    )
    validate_error(
        api_client.create_payment_standard(payload, ADMIN), "ERR_VALIDATION", 400
    )


def test_rent_reasonableness_is_immutable_record():
    """PRD §3.1: "This determination is an immutable audit record carrying only
    its id and created_at." PRD §2.4: "It has no updated_at field and no version
    field."

    Design: Corner/entities/rent_reasonableness_immutable_no_version
    """
    region = create_region(code="RIA")
    landlord = create_landlord(name="LLi", payee_account="acct-i")
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=1,
        asking_rent_cents=80000, comparable_rent_cents=80000,
    )
    det = validate_success(
        api_client.create_rent_reasonableness(
            create_rent_reasonableness_payload(unit["id"], requested_rent_cents=70000),
            CASEWORKER,
        ),
        201,
    )
    assert det["outcome"] == "REASONABLE"
    assert "version" not in det


def test_list_payment_standards_pagination_envelope():
    """PRD §2.3: "Every list response includes the following fields in the meta
    object: limit, offset, total_count, and has_more." Filtering by region
    returns the one created standard.

    Design: Corner/entities/list_payment_standards_pagination_envelope
    """
    region = create_region(code="RLA")
    create_payment_standard(region["id"], bedroom_size=1, amount_cents=90000, fmr_cents=100000)
    resp = api_client.list_payment_standards(ADMIN, params={"region_id": region["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["total_count"] == 1
    assert len(body["data"]) == 1
