"""Household-intake corner tests: required fields, defaults, parent FK
resolution, type/format constraints. Sources: PRD §3.1, §2.6, §2.10.
"""
from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID, ApiErrorId,
    TEST_USERS,
    create_household_payload, create_household_member_payload,
    set_clock, create_household,
)

CW = TEST_USERS["caseworker_headers"]


def test_create_household_missing_case_number_returns_invalid_request(api):
    """A POST /snap/households body without case_number is a missing-required-field
    body-parse failure and must be rejected with ERR_INVALID_REQUEST per PRD §2.10.

    PRD §2.10: "Generic body-parse failures (missing required field, type or
    enum violation, malformed JSON) yield `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "The caseworker supplies a `case_number` — a string of the form
    two uppercase letters, a hyphen, and six digits, which must be unique
    across all households (a duplicate is rejected with `ERR_DUPLICATE_CASE_NUMBER`)
    — together with the issuing `state_code`"

    Design: Corner/entities/create_household_missing_case_number_returns_invalid_request
    """
    resp = api.create_household(
        {"state_code": "CA", "address_line": "X"}, CW,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_household_not_found_returns_404(api):
    """GET /snap/households/{nonexistent-uuid} returns ERR_NOT_FOUND because
    the path id does not resolve.

    PRD §2.6: "Every `{id}` segment that appears in a URL path must resolve,
    left to right, to a row in the corresponding entity table; the first
    segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_household_not_found_returns_404
    """
    resp = api.get_household(NON_EXISTENT_UUID, CW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_household_default_heap_recipient_is_false(api):
    """Omitting heap_recipient applies the documented default of false; the
    household is born in PENDING with size 0.

    PRD §3.1: "The household is born with `status` set to `PENDING`, `size`
    set to 0, and `heap_recipient` defaulting to false when not supplied."

    Design: Corner/entities/create_household_default_heap_recipient_is_false
    """
    resp = api.create_household(
        create_household_payload(case_number="CA-100100", state_code="CA",
                                 address_line="1 X"),
        CW,
    )
    hh = validate_success(resp, 201)
    assert hh["heap_recipient"] is False, \
        f"heap_recipient must default to false, got {hh['heap_recipient']!r}"
    assert hh["status"] == "PENDING", \
        f"new household must start in PENDING, got {hh['status']!r}"
    assert hh["size"] == 0, f"new household size must be 0, got {hh['size']!r}"


def test_create_member_with_default_earned_zero(api):
    """A new HouseholdMember created without earned/unearned income fields gets
    them defaulted to 0.

    PRD §3.1: "Income is captured as two integer-cent fields,
    `monthly_earned_income_cents` (wage income) and `monthly_unearned_income_cents`
    (Social Security, child support, and similar), each defaulting to 0 and
    required to be non-negative."

    Design: Corner/entities/create_member_with_default_earned_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-100101", state_code="CA",
                          address_line="1 X")
    resp = api.create_household_member(
        create_household_member_payload(
            hh["id"], full_name="M", date_of_birth="1970-01-01",
            relationship="HEAD",
        ),
        CW,
    )
    m = validate_success(resp, 201)
    assert m["monthly_earned_income_cents"] == 0, \
        f"earned default must be 0, got {m['monthly_earned_income_cents']!r}"
    assert m["monthly_unearned_income_cents"] == 0, \
        f"unearned default must be 0, got {m['monthly_unearned_income_cents']!r}"


def test_parent_not_found_on_create_member(api):
    """POST /snap/household-members with a household_id that does not resolve
    must return ERR_PARENT_NOT_FOUND, not ERR_INVALID_REQUEST.

    PRD §2.6: "Similarly, every foreign-key field in a POST body — `household_id`
    on a member, application, EBT card, allotment, or fraud flag;
    `household_member_id` on an ABAWD waiver; `ebt_card_id` on a purchase
    transaction — must reference an existing parent row, or the request is
    rejected with `ERR_PARENT_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/parent_not_found_on_create_member
    """
    resp = api.create_household_member(
        create_household_member_payload(
            NON_EXISTENT_UUID, full_name="X",
            date_of_birth="1970-01-01", relationship="HEAD"),
        CW,
    )
    validate_error(resp, ApiErrorId.ERR_PARENT_NOT_FOUND.value)


def test_monthly_allotment_benefit_month_format_invalid(api):
    """benefit_month must be in YYYY-MM form. '2026-13' is an invalid format
    (month out of range) and is rejected as a body-parse failure with
    ERR_INVALID_REQUEST.

    PRD §3.5: "A `MonthlyAllotment` is created in `DRAFT` by a `BenefitIssuer`
    (or a `Caseworker` acting jointly) with a body containing `household_id`
    and a `benefit_month` string in `YYYY-MM` form."
    PRD §2.10: "Generic body-parse failures (missing required field, type or
    enum violation, malformed JSON) yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/monthly_allotment_benefit_month_format_invalid
    """
    from test_helpers import setup_household_certified_active
    set_clock("2026-09-01T00:00:00Z")
    hh, _app = setup_household_certified_active(
        case_number="CA-100102", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    resp = api.create_monthly_allotment(
        {"household_id": hh["id"], "benefit_month": "2026-13"},
        TEST_USERS["benefit_issuer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
