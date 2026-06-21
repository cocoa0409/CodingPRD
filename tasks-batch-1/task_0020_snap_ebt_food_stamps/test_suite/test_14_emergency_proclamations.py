"""Reference-data uniqueness: emergency proclamation per-month uniqueness
and household case_number uniqueness.
"""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    set_clock, create_household,
)

PA = TEST_USERS["policy_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


# ─── Corner / validations / duplicate_case_number_rejected ──

def test_duplicate_case_number_rejected(api):
    """Two /households calls with the same case_number must be rejected on
    the second with ERR_DUPLICATE_CASE_NUMBER (the state_code/address can
    differ; PRD §3.1 says case_number alone is the uniqueness key).

    PRD §3.1: "The caseworker supplies a `case_number` — a string of the
    form two uppercase letters, a hyphen, and six digits, which must be
    unique across all households (a duplicate is rejected with
    `ERR_DUPLICATE_CASE_NUMBER`) — together with the issuing `state_code`
    (one of `CA`, `TX`, `NY`, `FL`, `IL`, `PA`, `OH`, `GA`, `NC`, `MI`),
    a free-text `address_line`, and an optional `heap_recipient` boolean."

    Design: Corner/validations/duplicate_case_number_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_household(case_number="CA-140001", state_code="CA",
                     address_line="X")
    resp = api.create_household(
        {"case_number": "CA-140001", "state_code": "TX",
         "address_line": "Y"},
        CW,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER.value)


# ─── Corner / validations / duplicate_proclamation_rejected ──

def test_duplicate_proclamation_for_state_and_month_rejected(api):
    """A second EmergencyAllotmentProclamation for the same (state_code,
    benefit_month) pair must be rejected with ERR_DUPLICATE_PROCLAMATION.

    PRD §3.10: "The pair `(state_code, benefit_month)` is unique across
    all proclamations; a duplicate is rejected with
    `ERR_DUPLICATE_PROCLAMATION`."

    Design: Corner/validations/duplicate_proclamation_rejected
    """
    set_clock("2026-08-15T00:00:00Z")
    validate_first = api.create_emergency_allotment(
        {"state_code": "CA", "benefit_month": "2026-09"}, PA,
    )
    assert validate_first.status_code == 201, (
        f"first proclamation create must succeed, got {validate_first.status_code}: "
        f"{validate_first.text}"
    )
    resp = api.create_emergency_allotment(
        {"state_code": "CA", "benefit_month": "2026-09",
         "min_supplement_cents": 10000},
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROCLAMATION.value)
