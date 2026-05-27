"""Monthly allotment lifecycle: per-month uniqueness, past-month rejection,
issuance temporal gate, and the OCC stale-version check on /issue.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_member, current_household_version,
    setup_household_with_active_card,
    setup_household_certified_active,
    create_monthly_allotment,
)

CW = TEST_USERS["caseworker_headers"]
BI = TEST_USERS["benefit_issuer_headers"]


# ─── Difficulty / resource_temporal_overlap / monthly_allotment_per_month_uniqueness ──

def test_duplicate_household_benefit_month_pair_rejected(api):
    """The pair (household_id, benefit_month) is unique. A second create for
    the same pair must be rejected with ERR_DUPLICATE_ALLOTMENT_MONTH.

    PRD §3.5: "The pair `(household_id, benefit_month)` is unique across
    all allotments; a duplicate is rejected with
    `ERR_DUPLICATE_ALLOTMENT_MONTH`."

    Design: Difficulty/resource_temporal_overlap/monthly_allotment_per_month_uniqueness
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="NC-170001", state_code="NC",
        clock_iso="2026-10-01T00:00:00Z",
    )
    ma1 = create_monthly_allotment(hh["id"], "2026-10")
    assert ma1["status"] == "DRAFT"
    resp = api.create_monthly_allotment(
        {"household_id": hh["id"], "benefit_month": "2026-10"}, BI,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ALLOTMENT_MONTH.value)


def test_adjacent_calendar_month_is_independent_slot(api):
    """Per-month uniqueness applies to discrete calendar-month slots only —
    there is no rolling window. After failing for 2026-10, the same
    household can create an allotment for 2026-11 successfully.

    PRD §3.5: "The pair `(household_id, benefit_month)` is unique across
    all allotments; a duplicate is rejected with
    `ERR_DUPLICATE_ALLOTMENT_MONTH`."
    PRD §3.5: "The `benefit_month` must be the current month (as `YYYY-MM`
    of `SystemClock.current_utc`) or any future month; a month that has
    already started in the past yields `ERR_BENEFIT_MONTH_IN_PAST`."

    Design: Difficulty/resource_temporal_overlap/monthly_allotment_per_month_uniqueness
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="NC-170002", state_code="NC",
        clock_iso="2026-10-01T00:00:00Z",
    )
    create_monthly_allotment(hh["id"], "2026-10")
    resp = api.create_monthly_allotment(
        {"household_id": hh["id"], "benefit_month": "2026-11"}, BI,
    )
    ma2 = validate_success(resp, 201)
    assert ma2["benefit_month"] == "2026-11"
    assert ma2["status"] == "DRAFT"


# ─── Corner / validations / benefit_month_in_past_rejected ──

def test_benefit_month_in_past_rejected(api):
    """With clock at 2026-09 and benefit_month=2026-07 (past), create is
    rejected with ERR_BENEFIT_MONTH_IN_PAST.

    PRD §3.5: "The `benefit_month` must be the current month (as `YYYY-MM`
    of `SystemClock.current_utc`) or any future month; a month that has
    already started in the past yields `ERR_BENEFIT_MONTH_IN_PAST`."

    Design: Corner/validations/benefit_month_in_past_rejected
    """
    hh, _app = setup_household_certified_active(
        case_number="CA-700001", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    resp = api.create_monthly_allotment(
        {"household_id": hh["id"], "benefit_month": "2026-07"}, BI,
    )
    validate_error(resp, ApiErrorId.ERR_BENEFIT_MONTH_IN_PAST.value)


# ─── Corner / validations / issuance_too_early_rejected ──

def test_issuance_before_first_day_of_benefit_month_rejected(api):
    """Issuing a 2026-09 allotment while the clock is at 2026-08-15 must
    return ERR_ISSUANCE_TOO_EARLY — PRD §3.5 prohibits issue before the
    first day of the benefit_month.

    PRD §3.5: "On success, the allotment's `standard_allotment_cents` and
    `emergency_supplement_cents` are recomputed one last time from the
    live §3.4 inputs and frozen, `issued_total_cents` is recomputed to
    the frozen sum, `issued_at` is stamped to `SystemClock.current_utc`,
    and the household's `version` increments by 1."
    PRD §3.5: "Issuance transitions the allotment from `DRAFT` to
    `ISSUED` and is exclusive to the `BenefitIssuer` role. The request
    body carries `expected_household_version` to satisfy the
    optimistic-concurrency rule described in §2.5. The transition
    requires that the allotment is in `DRAFT`, that the household is
    `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`), that the household
    has at least one EBT card in `ACTIVE` status, and that
    `SystemClock.current_utc` is on or after the first UTC day of
    `benefit_month` (otherwise `ERR_ISSUANCE_TOO_EARLY`)."

    Design: Corner/validations/issuance_too_early_rejected
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-700002", state_code="CA",
        clock_iso="2026-08-15T00:00:00Z",
    )
    # Create a DRAFT allotment for next month (2026-09 is current/future).
    ma = create_monthly_allotment(hh["id"], "2026-09")
    hh_v = current_household_version(hh["id"])
    resp = api.issue_monthly_allotment(
        ma["id"], {"expected_household_version": hh_v}, BI,
    )
    validate_error(resp, ApiErrorId.ERR_ISSUANCE_TOO_EARLY.value)


# ─── Corner / cross_cutting_complexity_layers / occ_stale_household_version_on_issue ──

def test_occ_stale_household_version_on_issue(api):
    """An issuer reads Household.version=V; before /issue, a member is
    added (which bumps Household.version to V+1 per PRD §3.1). The
    subsequent /issue with expected_household_version=V is rejected with
    ERR_STALE_HOUSEHOLD_VERSION.

    PRD §2.5: "Issuing a monthly allotment requires `expected_household_version`
    in the request body. The value must match the target household's
    current `version`. If another writer — adding a household member,
    flipping `heap_recipient`, approving an application — has advanced
    the household's `version` since the issuer last read it, the issue
    request is rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412).
    This prevents the issuer from freezing an allotment amount computed
    against household inputs that have since changed (for example, the
    household just grew, so `gross_income_cents` and `net_income_cents`
    are different from what the issuer saw)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_household_version_on_issue
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-700003", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    ma = create_monthly_allotment(hh["id"], "2026-09")
    pre_v = current_household_version(hh["id"])
    # Intervening member-add advances Household.version.
    add_member(hh["id"], full_name="M2", date_of_birth="1972-01-01",
               relationship="SPOUSE", disabled=True)
    resp = api.issue_monthly_allotment(
        ma["id"], {"expected_household_version": pre_v}, BI,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION.value)
