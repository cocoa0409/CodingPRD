"""Organization registration, computed eligibility, and input validation."""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_organization,
    create_organization_payload, create_license_payload,
    TEST_USERS, make_orgofficer_headers,
    set_clock, create_organization,
)

REGULATOR = TEST_USERS["regulator_headers"]


def test_organization_create_computes_eligible_501c3(api):
    """PRD §3.1: "The first, `months_active`, is the number of whole calendar months
    elapsed from `incorporation_date` to the current clock: compute twelve times the
    difference between the clock's year and the incorporation year, add the difference
    between the clock's month and the incorporation month, and then subtract one further
    month if the clock's day-of-month is earlier than the incorporation day-of-month."
    PRD §2.5: "On server startup the clock reads exactly `2026-05-01T00:00:00Z`; before
    any clock-setting call is made, the clock holds this default and never falls back to
    real time."

    Design: Corner/entities/organization_create_returns_computed_eligibility
    """
    res = api.create_organization(
        create_organization_payload(nonprofit_type="501C3",
                                    incorporation_date="2020-01-01T00:00:00Z",
                                    good_standing=True),
        REGULATOR,
    )
    org = validate_success(res, 201)
    assert_organization(org)
    fetched = validate_success(api.get_organization(org["id"], REGULATOR), 200)
    assert fetched["months_active"] == 76, f"expected 76, got {fetched['months_active']}"
    assert fetched["eligibility_status"] == "ELIGIBLE"


def test_organization_recent_incorporation_ineligible(api):
    """PRD §3.1: "The second, `eligibility_status`, is `ELIGIBLE` only when all three of
    the following hold, and is `INELIGIBLE` otherwise: the `nonprofit_type` is one of the
    qualifying types `501C3`, `501C4`, `501C8`, `501C10`, or `501C19` (i.e. any type other
    than `OTHER`); `months_active` is at least 36 (three full calendar years); and
    `good_standing` is `true`."

    Design: Corner/entities/organization_recent_incorporation_ineligible
    """
    org = validate_success(
        api.create_organization(
            create_organization_payload(nonprofit_type="501C3",
                                        incorporation_date="2025-01-01T00:00:00Z",
                                        good_standing=True),
            REGULATOR),
        201,
    )
    fetched = validate_success(api.get_organization(org["id"], REGULATOR), 200)
    assert fetched["months_active"] == 16, f"expected 16, got {fetched['months_active']}"
    assert fetched["eligibility_status"] == "INELIGIBLE"


def test_organization_default_good_standing_true(api):
    """PRD §3.1: "optionally whether it is in `good_standing` with the state registry —
    a boolean that defaults to `true` when omitted."

    Design: Corner/entities/organization_default_good_standing_applied
    """
    payload = create_organization_payload(nonprofit_type="501C3",
                                          incorporation_date="2020-01-01T00:00:00Z")
    payload.pop("good_standing", None)
    org = validate_success(api.create_organization(payload, REGULATOR), 201)
    fetched = validate_success(api.get_organization(org["id"], REGULATOR), 200)
    assert fetched["good_standing"] is True
    assert fetched["eligibility_status"] == "ELIGIBLE"


def test_months_active_recomputed_after_clock_advance(api):
    """PRD §2.5: "First, an organization's `months_active` and `eligibility_status` are
    always evaluated against the current clock, so the same organization can be ineligible
    at one clock value and eligible at a later one."
    PRD §3.1: "Both figures are recomputed whenever an organization is fetched and whenever
    eligibility is evaluated as a gate on license approval."

    Design: Corner/entities/months_active_recomputed_after_clock_advance
    """
    org = create_organization(incorporation_date="2020-01-01T00:00:00Z")
    set_clock("2027-01-01T00:00:00Z")
    fetched = validate_success(api.get_organization(org["id"], REGULATOR), 200)
    assert fetched["months_active"] == 84, f"expected 84, got {fetched['months_active']}"


def test_org_create_missing_ein_rejected(api):
    """PRD §2.10: "Body well-formedness — required fields present, enum values valid, and
    ordered time ranges correct; a malformed body yields `ERR_VALIDATION` (422), except for
    the three ordered-range checks which carry their own codes (see §3)."
    PRD §3.1: "A `Regulator` registers a nonprofit by supplying its `legal_name`, its `ein`
    (Employer Identification Number), its `nonprofit_type`, its `incorporation_date`, its
    `state_code` (a two-letter state code), and optionally whether it is in `good_standing`
    with the state registry — a boolean that defaults to `true` when omitted."

    Design: Corner/entities/org_create_missing_required_field_rejected
    """
    payload = create_organization_payload()
    payload.pop("ein")
    res = api.create_organization(payload, REGULATOR)
    validate_error(res, "ERR_VALIDATION")


def test_license_type_invalid_enum_rejected(api):
    """PRD §2.10: "Body well-formedness — required fields present, enum values valid, and
    ordered time ranges correct; a malformed body yields `ERR_VALIDATION` (422), except for
    the three ordered-range checks which carry their own codes (see §3)."
    PRD §3.2: "An `OrgOfficer` applies for a license on behalf of its organization by
    supplying the `organization_id`, the `license_type` (`BINGO`, `RAFFLE`, or `COMBINED`),
    a `contact_email`, and a `venue_name`."

    Design: Corner/entities/license_type_invalid_enum_rejected
    """
    org = create_organization()
    res = api.create_license(
        create_license_payload(org["id"], license_type="POKER"),
        make_orgofficer_headers(org["id"]),
    )
    validate_error(res, "ERR_VALIDATION")
