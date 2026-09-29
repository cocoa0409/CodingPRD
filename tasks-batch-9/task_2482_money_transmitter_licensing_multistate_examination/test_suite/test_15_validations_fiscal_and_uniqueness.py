"""Fiscal sufficiency, uniqueness and window validations at their exact boundaries.

Every rule exercised here is a threshold rule, and the interesting cases are the
two integers either side of the threshold: a bond one cent short of the
requirement against the exact requirement, a renewal payment one cent under the
computed total against the total itself, an obligation reversal one cent past
zero against the reversal that lands exactly on zero, a certification one day
past its forty-five day window against one arriving on the last admissible
instant, and a response two items short of the demand against one that meets it
exactly. Two further cases prove that a uniqueness rule keys on what the
specification says it keys on — the (licensee, jurisdiction) pair for a live
application, the (licence, period_label) pair for a call report — and one proves
that when a surrender breaches both of its substantive conditions at once the
ladder of PRD 2.7 returns the structural error rather than the fiscal one.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVE_DELEGATES_REMAIN,
    ERR_BOND_INSUFFICIENT,
    ERR_CERTIFICATION_WINDOW_CLOSED,
    ERR_DUPLICATE_CALL_REPORT,
    ERR_DUPLICATE_LICENSE_APPLICATION,
    ERR_NEGATIVE_OBLIGATIONS,
    ERR_NET_WORTH_INSUFFICIENT,
    ERR_OUTSTANDING_OBLIGATIONS_REMAIN,
    ERR_RENEWAL_FEE_MISMATCH,
    ERR_RESPONSE_INCOMPLETE,
)
from test_helpers.test_users import (
    CHIEF_HEADERS,
    MANAGER_HEADERS,
    USER_CHIEF_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER,
    make_state_regulator_headers,
)

# A projected annual volume of at most one billion cents sits in bond tier one,
# so every application below pins the same tier bond of 2,500,000 cents.
TIER_ONE_VOLUME_CENTS = 90_000_000

# A coverage period whose certification window has already run out at the
# process-start clock of 2026-08-01: 2026-06-15 plus forty-five days is
# 2026-07-30, so the window closed two days before the clock reads.
CLOSED_PERIOD_START = "2026-05-16T00:00:00Z"
CLOSED_PERIOD_END = "2026-06-15T00:00:00Z"

# A coverage period whose window closes exactly on the process-start clock:
# 2026-06-17 plus forty-five days is 2026-08-01T00:00:00Z.
OPEN_PERIOD_START = "2026-05-18T00:00:00Z"
OPEN_PERIOD_END = "2026-06-17T00:00:00Z"


# ---------------------------------------------------------------------------
# Net worth at approval
# ---------------------------------------------------------------------------


def test_approval_with_net_worth_below_the_state_minimum_rejects(
    api: MoneyTransmitterApiClient,
) -> None:
    """A 50,000,000 net worth fails Texas's 100,000,000 floor at APPROVE.

    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."
    PRD 3.3: "The action `APPROVE` carries three substantive preconditions on top of the state and scope checks: the licensee's `reported_tangible_net_worth_cents` must be at least the application's pinned `required_net_worth_cents`, or the approval is rejected with `ERR_NET_WORTH_INSUFFICIENT`; every non-`REMOVED` control person of the licensee whose `control_determination` is `CONTROL` must have `background_check_status` of `CLEARED`, or the approval is rejected with `ERR_BACKGROUND_CHECK_INCOMPLETE`, which is the per-holder statement of the licensee-level condition that `control_chain_status` be `VERIFIED`; and the licensee's `coverage_posture` must not be `FROZEN`."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 2.3: "The licence register filters on `licensee_id`, `jurisdiction_id`, `application_id`, `license_status` and `reporting_status` — and the `application_id` filter is the only way to discover the licence that an approval minted, since approval returns the application rather than the new licence."

    Design: Corner/validations/net_worth_below_the_state_minimum_blocks_approval
    """
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    licensee = fx.create_licensee(api, reported_tangible_net_worth_cents=50_000_000)
    application = fx.create_application(
        api,
        licensee["id"],
        texas["id"],
        projected_annual_volume_cents=TIER_ONE_VOLUME_CENTS,
    )
    submitted = fx.submit_application(api, application["id"])
    # Texas pins min_net_worth_cents 100,000,000 onto the application at submit.
    assert submitted["required_net_worth_cents"] == 100_000_000
    fx.review_application(api, application["id"], texas["id"], "START_REVIEW")

    rejected = api.review_application(
        application["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(texas["id"]),
    )
    validate_error(rejected, ERR_NET_WORTH_INSUFFICIENT)

    # Nothing moved: the application is still open for review and no licence was
    # minted, so the register has no row carrying this application_id.
    row = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert row["status"] == "UNDER_REVIEW"
    assert row.get("decision_at") is None
    assert row["required_net_worth_cents"] == 100_000_000
    licenses, _ = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": application["id"]})
    )
    assert licenses == []


def test_approval_with_net_worth_exactly_at_the_state_minimum_is_accepted(
    api: MoneyTransmitterApiClient,
) -> None:
    """The same 50,000,000 net worth clears California's 50,000,000 floor.

    PRD 3.3: "The action `APPROVE` carries three substantive preconditions on top of the state and scope checks: the licensee's `reported_tangible_net_worth_cents` must be at least the application's pinned `required_net_worth_cents`, or the approval is rejected with `ERR_NET_WORTH_INSUFFICIENT`; every non-`REMOVED` control person of the licensee whose `control_determination` is `CONTROL` must have `background_check_status` of `CLEARED`, or the approval is rejected with `ERR_BACKGROUND_CHECK_INCOMPLETE`, which is the per-holder statement of the licensee-level condition that `control_chain_status` be `VERIFIED`; and the licensee's `coverage_posture` must not be `FROZEN`."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 3.3: "It starts with `license_status` `PENDING_BOND`, `reporting_status` `CURRENT`, `expansion_gate` `BLOCKED`, `bond_status` `NONE`, `outstanding_obligations_cents` zero, and `bond_requirement_cents` copied from the application's `required_bond_cents`."

    Design: Corner/validations/net_worth_below_the_state_minimum_blocks_approval
    """
    california = fx.create_jurisdiction(api, C.CA_CONFIG)
    licensee = fx.create_licensee(api, reported_tangible_net_worth_cents=50_000_000)
    application = fx.create_application(
        api,
        licensee["id"],
        california["id"],
        projected_annual_volume_cents=TIER_ONE_VOLUME_CENTS,
    )
    submitted = fx.submit_application(api, application["id"])
    # California's floor is 50,000,000, exactly what the licensee reports, and
    # "at least" makes that boundary admissible.
    assert submitted["required_net_worth_cents"] == 50_000_000
    fx.review_application(api, application["id"], california["id"], "START_REVIEW")

    approved = fx.review_application(
        api, application["id"], california["id"], "APPROVE"
    )
    assert approved["status"] == "APPROVED"
    assert approved["decision_at"] is not None

    licenses, meta = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": application["id"]})
    )
    assert meta["total_count"] == 1
    minted = licenses[0]
    assert minted["license_status"] == "PENDING_BOND"
    assert minted["bond_status"] == "NONE"
    # max(base_bond 5,000,000, tier one 2,500,000 + 0 delegates * 100,000) = 5,000,000,
    # times the 10000 bps MONEY_TRANSMISSION multiplier, capped at 40,000,000.
    assert minted["bond_requirement_cents"] == 5_000_000


# ---------------------------------------------------------------------------
# The certification window
# ---------------------------------------------------------------------------


def test_certification_after_the_forty_five_day_window_rejects(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A window that closed on 2026-07-30 refuses a certification at 2026-08-01.

    PRD 3.7: "Certification is the `ChiefComplianceOfficer`'s alone and carries an optional `attestation_note`."
    PRD 3.7: "It is admissible only from `PREPARED`; the certifying `X-User-ID` must differ from `prepared_by_user_id` per §2.10; and it must arrive on or before forty-five days after `coverage_period_end` — the boundary is inclusive, and a late certification is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED`."
    PRD 2.10: "The certifying identity must differ from the preparing identity; a certification attempt whose `X-User-ID` equals the recorded `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."
    PRD 3.7: "First, the test moves `PREPARED → CERTIFIED`, `certified_at` is stamped from the logical clock, `certified_by_user_id` records the acting identity, and the licensee's `consecutive_failed_test_count` either increases by one — when the test's `result` is `SHORTFALL` — or resets to zero when it is `PASS`; `coverage_posture` is then recomputed, and because two consecutive certified shortfalls set the count to 2, the second one alone forces the posture to `FROZEN` no matter how good the ratio looks."

    Design: Corner/validations/certification_after_the_forty_five_day_window_rejects
    """
    fx.record_holding(api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000)
    test = fx.open_investment_test(
        api,
        licensee["id"],
        "ELIGIBLE_MARKET",
        coverage_period_start=CLOSED_PERIOD_START,
        coverage_period_end=CLOSED_PERIOD_END,
    )
    prepared = fx.prepare_investment_test(api, test["id"])
    # The preparer is the compliance officer, so the certifying chief officer is
    # a different identity and the segregation rule of PRD 2.10 is satisfied.
    assert prepared["prepared_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert prepared["result"] == "PASS"

    rejected = api.certify_investment_test(
        test["id"],
        CHIEF_HEADERS,
        F.certify_payload(attestation_note="Late certification attempt."),
    )
    validate_error(rejected, ERR_CERTIFICATION_WINDOW_CLOSED)

    # Nothing moved: the row is still PREPARED, uncertified, and the licensee's
    # failed-test counter did not take a step in either direction.
    row = validate_success(api.get_investment_test(test["id"], CHIEF_HEADERS))
    assert row["status"] == "PREPARED"
    assert row.get("certified_at") is None
    assert row["result"] == "PASS"
    assert fx.get_licensee(api, licensee["id"])["consecutive_failed_test_count"] == 0


def test_certification_on_the_last_day_of_the_window_is_accepted(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A window closing exactly at the clock's instant still admits certification.

    PRD 3.7: "It is admissible only from `PREPARED`; the certifying `X-User-ID` must differ from `prepared_by_user_id` per §2.10; and it must arrive on or before forty-five days after `coverage_period_end` — the boundary is inclusive, and a late certification is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED`."
    PRD 3.7: "First, the test moves `PREPARED → CERTIFIED`, `certified_at` is stamped from the logical clock, `certified_by_user_id` records the acting identity, and the licensee's `consecutive_failed_test_count` either increases by one — when the test's `result` is `SHORTFALL` — or resets to zero when it is `PASS`; `coverage_posture` is then recomputed, and because two consecutive certified shortfalls set the count to 2, the second one alone forces the posture to `FROZEN` no matter how good the ratio looks."
    PRD 2.4: "The server holds a **logical clock** that starts at `2026-08-01T00:00:00Z` when the process starts and never advances on its own."

    Design: Corner/validations/certification_after_the_forty_five_day_window_rejects
    """
    fx.record_holding(api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000)
    test = fx.open_investment_test(
        api,
        licensee["id"],
        "ELIGIBLE_MARKET",
        coverage_period_start=OPEN_PERIOD_START,
        coverage_period_end=OPEN_PERIOD_END,
    )
    prepared = fx.prepare_investment_test(api, test["id"])
    assert prepared["prepared_by_user_id"] == USER_COMPLIANCE_OFFICER

    # 2026-06-17 plus forty-five twenty-four hour periods is 2026-08-01T00:00:00Z,
    # which is exactly where the clock stands, and the boundary is inclusive.
    certified = validate_success(
        api.certify_investment_test(
            test["id"], CHIEF_HEADERS, F.certify_payload(attestation_note="On the deadline.")
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_at"] is not None
    assert certified["certified_by_user_id"] == USER_CHIEF_COMPLIANCE_OFFICER
    # A PASS resets the counter rather than raising it.
    assert fx.get_licensee(api, licensee["id"])["consecutive_failed_test_count"] == 0


# ---------------------------------------------------------------------------
# The surety bond amount
# ---------------------------------------------------------------------------


def test_bond_one_cent_short_rejects_then_the_exact_amount_activates(
    api: MoneyTransmitterApiClient, pending_bond_license: fx.Scenario
) -> None:
    """4,999,999 is refused against a 5,000,000 requirement; 5,000,000 activates.

    PRD 3.4: "The posted amount must be at least the licence's current `bond_requirement_cents`; a smaller bond is rejected with `ERR_BOND_INSUFFICIENT` (HTTP 422)."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "On success the licence moves `PENDING_BOND → ACTIVE`: `bond_posted_cents` records the face amount, `bond_status` becomes `POSTED`, the `bond_issuer` is stored, `authorized_at` is stamped from the logical clock, the licensee's `active_license_count` is increased by one, and — because the licence has just joined the obligation aggregate set — the licensee's `aggregate_outstanding_obligations_cents` is recomputed."
    PRD 3.4: "`bond_status` has four values in all — `NONE`, `POSTED`, `CANCELLATION_NOTICED` and `CANCELLED` — with `NONE` as the default."

    Design: Corner/validations/bond_one_cent_short_of_the_requirement_rejects_then_the_exact_amount_passes
    """
    license_id = pending_bond_license.license_id
    before = fx.get_license(api, license_id)
    # max(base_bond 5,000,000, tier one 2,500,000 + 0 * 100,000) = 5,000,000, left
    # unchanged by the 10000 bps MONEY_TRANSMISSION multiplier and under the cap.
    assert before["bond_requirement_cents"] == 5_000_000

    rejected = api.post_bond(license_id, F.bond_payload(4_999_999), MANAGER_HEADERS)
    validate_error(rejected, ERR_BOND_INSUFFICIENT)

    # Nothing moved: the licence is still unbonded and unauthorised.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["license_status"] == "PENDING_BOND"
    assert unchanged["bond_status"] == "NONE"
    assert unchanged["bond_posted_cents"] == before["bond_posted_cents"]
    assert unchanged["version"] == before["version"]
    assert fx.get_licensee(api, pending_bond_license.licensee_id)["active_license_count"] == 0

    accepted = validate_success(
        api.post_bond(license_id, F.bond_payload(5_000_000), MANAGER_HEADERS)
    )
    assert accepted["license_status"] == "ACTIVE"
    assert accepted["bond_status"] == "POSTED"
    assert accepted["bond_posted_cents"] == 5_000_000
    assert accepted["bond_issuer"] == C.SEED_BOND_ISSUER
    assert accepted["authorized_at"] is not None
    assert fx.get_licensee(api, pending_bond_license.licensee_id)["active_license_count"] == 1


# ---------------------------------------------------------------------------
# The renewal fee
# ---------------------------------------------------------------------------


def test_renewal_payment_off_by_one_cent_rejects_then_the_exact_total_renews(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """509,999 is refused against a computed total of 510,000, which then renews.

    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "The supplied `payment_amount_cents` must equal that total exactly; any other figure is rejected with `ERR_RENEWAL_FEE_MISMATCH` (HTTP 422)."
    PRD 3.5: "On a match, `renewal_status` moves from `NOT_RENEWED` to `RENEWED`, `renewal_year` records the year renewed, `renewal_total_fee_cents` records the computed total, and the licence's `version` is bumped."

    Design: Corner/validations/renewal_payment_off_by_one_cent_rejects_with_fee_mismatch
    """
    license_id = active_license.license_id
    before = fx.get_license(api, license_id)
    assert before["active_delegate_count"] == 0
    assert before["reporting_status"] == "CURRENT"
    assert before["renewal_status"] == "NOT_RENEWED"

    # Subtotal 500,000 + 0 * 25,000 = 500,000; that exceeds 250,000 so the tier is
    # 200 bps; assessment = round-half-up(500,000 * 200 / 10000) = 10,000; total 510,000.
    rejected = api.renew_license(
        license_id, F.renewal_payload(2027, 509_999), MANAGER_HEADERS
    )
    validate_error(rejected, ERR_RENEWAL_FEE_MISMATCH)

    # Nothing moved: no renewal was recorded and the licence version held.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["renewal_status"] == "NOT_RENEWED"
    assert unchanged["version"] == before["version"]

    accepted = validate_success(
        api.renew_license(license_id, F.renewal_payload(2027, 510_000), MANAGER_HEADERS)
    )
    assert accepted["renewal_status"] == "RENEWED"
    assert accepted["renewal_year"] == 2027
    assert accepted["renewal_total_fee_cents"] == 510_000
    assert accepted["version"] == before["version"] + 1


# ---------------------------------------------------------------------------
# Obligation adjustments
# ---------------------------------------------------------------------------


def test_obligation_delta_below_zero_rejects_with_negative_obligations(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A -3,000,001 reversal against a 3,000,000 balance is refused outright.

    PRD 3.4: "The delta is added to the licence's `outstanding_obligations_cents`, and the resulting balance may never go below zero — an adjustment that would drive it negative is rejected with `ERR_NEGATIVE_OBLIGATIONS` (HTTP 422)."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."

    Design: Corner/validations/obligation_delta_below_zero_rejects_with_negative_obligations
    """
    license_id = active_license.license_id
    funded = fx.adjust_obligations(api, license_id, 3_000_000, memo="Settlement float")
    assert funded["outstanding_obligations_cents"] == 3_000_000

    rejected = api.adjust_obligations(
        license_id,
        F.obligations_payload(-3_000_001, memo="Over-reversal"),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_NEGATIVE_OBLIGATIONS)

    # Nothing moved: 3,000,000 + (-3,000,001) = -1 would be negative, so the
    # balance and the licensee-level aggregate both hold at 3,000,000.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["outstanding_obligations_cents"] == 3_000_000
    assert unchanged["version"] == funded["version"]
    owner = fx.get_licensee(api, active_license.licensee_id)
    assert owner["aggregate_outstanding_obligations_cents"] == 3_000_000


def test_obligation_delta_landing_exactly_on_zero_is_accepted(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A -3,000,000 reversal against the same balance lands on zero and is kept.

    PRD 3.4: "The delta is added to the licence's `outstanding_obligations_cents`, and the resulting balance may never go below zero — an adjustment that would drive it negative is rejected with `ERR_NEGATIVE_OBLIGATIONS` (HTTP 422)."
    PRD 3.4: "The adjustment then re-derives, in order: the licensee's `aggregate_outstanding_obligations_cents`, both permissible-investment values, `coverage_ratio_bps` and `coverage_posture`."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."

    Design: Corner/validations/obligation_delta_below_zero_rejects_with_negative_obligations
    """
    license_id = active_license.license_id
    fx.adjust_obligations(api, license_id, 3_000_000, memo="Settlement float")

    # 3,000,000 + (-3,000,000) = 0, and zero is admissible: the rule guards the
    # resulting balance, not the sign of the delta.
    cleared = fx.adjust_obligations(api, license_id, -3_000_000, memo="Full reversal")
    assert cleared["outstanding_obligations_cents"] == 0

    owner = fx.get_licensee(api, active_license.licensee_id)
    assert owner["aggregate_outstanding_obligations_cents"] == 0
    # With no obligations the ratio is vacuously perfect at 10000 bps.
    assert owner["coverage_ratio_bps"] == 10_000
    assert owner["coverage_posture"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Surrender: the outstanding-obligation condition
# ---------------------------------------------------------------------------


def test_surrender_request_with_one_cent_outstanding_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One outstanding cent blocks the surrender request and moves nothing.

    PRD 3.4: "Two substantive conditions apply: the licence's `outstanding_obligations_cents` must be exactly zero, or the request is rejected with `ERR_OUTSTANDING_OBLIGATIONS_REMAIN`; and no `DelegateAuthorization` of the licence may still be `ACTIVE`, or the request is rejected with `ERR_ACTIVE_DELEGATES_REMAIN`."
    PRD 2.6: "Filing a surrender request requires the request body to carry `expected_state_license_version`, a non-optional field holding the client's last observed `version` of the parent `StateLicense`."
    PRD 2.6: "A successful surrender request bumps `StateLicense.version`, so a replayed request with the same expected version is rejected."

    Design: Corner/validations/surrender_request_with_one_cent_outstanding_rejects
    """
    license_id = active_license.license_id
    # Cash cover keeps the posture COMPLIANT, so the expansion gate stays OPEN
    # and only the residual cent stands between the licence and its wind-down.
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    with_residual = fx.adjust_obligations(api, license_id, 1, memo="Residual cent")
    assert with_residual["outstanding_obligations_cents"] == 1

    rejected = api.request_surrender(
        license_id,
        F.surrender_request_payload(with_residual["version"]),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_OUTSTANDING_OBLIGATIONS_REMAIN)

    # Nothing moved: the licence never entered SURRENDER_REQUESTED and, because
    # the write never landed, its version is still the one the client held.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["license_status"] == "ACTIVE"
    assert unchanged["expansion_gate"] == "OPEN"
    assert unchanged["outstanding_obligations_cents"] == 1
    assert unchanged["version"] == with_residual["version"]
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


def test_surrender_request_with_exactly_zero_outstanding_is_accepted(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Clearing that last cent to exactly zero admits the surrender request.

    PRD 3.4: "Two substantive conditions apply: the licence's `outstanding_obligations_cents` must be exactly zero, or the request is rejected with `ERR_OUTSTANDING_OBLIGATIONS_REMAIN`; and no `DelegateAuthorization` of the licence may still be `ACTIVE`, or the request is rejected with `ERR_ACTIVE_DELEGATES_REMAIN`."
    PRD 3.4: "On success the licence moves to `SURRENDER_REQUESTED`, `expansion_gate` is set to `BLOCKED`, `version` is bumped, and `active_license_count` is reduced by one — but only when the prior status was `ACTIVE`; surrendering an already-suspended licence moves no counter, because the suspension already decremented it."

    Design: Corner/validations/surrender_request_with_one_cent_outstanding_rejects
    """
    license_id = active_license.license_id
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    fx.adjust_obligations(api, license_id, 1, memo="Residual cent")
    # 1 + (-1) = 0, which is the exact balance the wind-down guard demands.
    cleared = fx.adjust_obligations(api, license_id, -1, memo="Residual cent settled")
    assert cleared["outstanding_obligations_cents"] == 0

    accepted = validate_success(
        api.request_surrender(
            license_id, F.surrender_request_payload(cleared["version"]), MANAGER_HEADERS
        )
    )
    assert accepted["license_status"] == "SURRENDER_REQUESTED"
    assert accepted["expansion_gate"] == "BLOCKED"
    assert accepted["version"] == cleared["version"] + 1
    # The licence was ACTIVE immediately before, so the counter steps 1 -> 0.
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


# ---------------------------------------------------------------------------
# Surrender: which of the two conditions reports first
# ---------------------------------------------------------------------------


def test_active_delegate_check_outranks_the_outstanding_obligation_check(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Both surrender conditions fail at once and the structural error wins.

    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 2.7: "11. **Uniqueness and structural constraints**, in this order: duplicate live application (`ERR_DUPLICATE_LICENSE_APPLICATION`), duplicate `ein` (`ERR_DUPLICATE_EIN`), duplicate `state_code` (`ERR_DUPLICATE_STATE_CODE`), duplicate or mis-formed `period_label` (`ERR_DUPLICATE_CALL_REPORT`), incomplete information-request response (`ERR_RESPONSE_INCOMPLETE`), active delegates remaining at surrender (`ERR_ACTIVE_DELEGATES_REMAIN`), control-chain cycle or excessive depth (`ERR_CONTROL_CHAIN_CYCLE`), reporting status not current at renewal (`ERR_REPORTING_NOT_CURRENT`)."
    PRD 2.7: "12. **Fiscal sufficiency**, last, in this order: net worth (`ERR_NET_WORTH_INSUFFICIENT`), bond amount (`ERR_BOND_INSUFFICIENT`), outstanding obligations at surrender (`ERR_OUTSTANDING_OBLIGATIONS_REMAIN`), renewal fee match (`ERR_RENEWAL_FEE_MISMATCH`), non-negative obligations (`ERR_NEGATIVE_OBLIGATIONS`)."
    PRD 3.4: "Two substantive conditions apply: the licence's `outstanding_obligations_cents` must be exactly zero, or the request is rejected with `ERR_OUTSTANDING_OBLIGATIONS_REMAIN`; and no `DelegateAuthorization` of the licence may still be `ACTIVE`, or the request is rejected with `ERR_ACTIVE_DELEGATES_REMAIN`."

    Design: Corner/validations/active_delegate_check_outranks_the_outstanding_obligation_check
    """
    license_id = active_license.license_id
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    # 90 * 4000 + 90 * 3500 + 70 * 2500 = 850,000, divided by 10000 and rounded
    # down is 85, which clears the activation floor of 70.
    appointed = fx.setup_active_authorization(
        api,
        active_license,
        scores={"training_score": 90, "aml_test_score": 90, "recordkeeping_score": 70},
    )
    assert appointed["authorization"]["status"] == "ACTIVE"
    scored = validate_success(
        api.get_delegate(active_license.delegate_id, MANAGER_HEADERS)
    )
    assert scored["oversight_score"] == 85

    with_residual = fx.adjust_obligations(api, license_id, 1, memo="Residual cent")
    # Both conditions now fail: one ACTIVE authorization remains and one cent is
    # still outstanding.
    assert with_residual["outstanding_obligations_cents"] == 1
    assert with_residual["active_delegate_count"] == 1

    rejected = api.request_surrender(
        license_id,
        F.surrender_request_payload(with_residual["version"]),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_ACTIVE_DELEGATES_REMAIN)

    # Nothing moved, and the losing condition is on the record: the fiscal
    # shortfall of one cent was live and still did not decide the response.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["license_status"] == "ACTIVE"
    assert unchanged["active_delegate_count"] == 1
    assert unchanged["outstanding_obligations_cents"] == 1
    assert unchanged["version"] == with_residual["version"]


# ---------------------------------------------------------------------------
# Duplicate live application
# ---------------------------------------------------------------------------


def test_second_application_for_the_same_state_rejects_at_submit(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """Two California drafts are free; the second submit is the one refused.

    PRD 3.3: "Nothing is checked for duplication at this point — a licensee may keep several drafts for the same state."
    PRD 3.3: "There must be no other application for the same licensee and the same jurisdiction whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT` or `APPROVED`; a second live filing is rejected with `ERR_DUPLICATE_LICENSE_APPLICATION`."
    PRD 3.3: "The row starts in `DRAFT`; the remaining statuses are `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`, `APPROVED`, `DENIED` and `WITHDRAWN`, of which the last three are terminal."

    Design: Corner/validations/second_application_for_the_same_state_rejects_at_submit
    """
    first = fx.create_application(
        api,
        licensee["id"],
        ca_jurisdiction["id"],
        license_class="MONEY_TRANSMISSION",
        projected_annual_volume_cents=TIER_ONE_VOLUME_CENTS,
    )
    second = fx.create_application(
        api,
        licensee["id"],
        ca_jurisdiction["id"],
        license_class="PAYMENT_INSTRUMENTS",
        projected_annual_volume_cents=TIER_ONE_VOLUME_CENTS,
        new_product_narrative="Money orders sold through retail agents.",
    )
    # Both drafts were created: duplication is not tested at creation.
    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"

    submitted = fx.submit_application(api, first["id"])
    assert submitted["status"] == "SUBMITTED"

    rejected = api.submit_application(second["id"], MANAGER_HEADERS)
    validate_error(rejected, ERR_DUPLICATE_LICENSE_APPLICATION)

    # Nothing moved: the refused draft is untouched, and the sibling that owns
    # the (licensee, jurisdiction) pair is still the live filing even though the
    # two applications declare different licence classes.
    still_draft = validate_success(api.get_application(second["id"], MANAGER_HEADERS))
    assert still_draft["status"] == "DRAFT"
    assert still_draft.get("submitted_at") is None
    assert still_draft["version"] == second["version"]
    assert (
        validate_success(api.get_application(first["id"], MANAGER_HEADERS))["status"]
        == "SUBMITTED"
    )


# ---------------------------------------------------------------------------
# Duplicate call-report label
# ---------------------------------------------------------------------------


def test_second_call_report_for_the_same_period_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Refiling 2026Q2 is refused and does not add its volume a second time.

    PRD 3.5: "The label is a reporting-period key: for a jurisdiction whose `call_report_frequency` is `QUARTERLY` it is a four-digit year followed by the letter Q and a digit from 1 to 4; for an `ANNUAL` jurisdiction it is a four-digit year followed by the letters FY."
    PRD 3.5: "The label must be unique for the licence, and its form must match the jurisdiction's cadence — a repeat label, or a quarterly label filed against an annual state, is rejected with `ERR_DUPLICATE_CALL_REPORT` (HTTP 409)."
    PRD 3.5: "The report's `status` follows a strictly ordered two-test rule: the report is `LATE` if the logical clock is strictly past `due_at`; otherwise it is `FILED_DEFICIENT` if `transaction_count` is exactly zero while `transmission_volume_cents` is greater than zero; otherwise it is `FILED`."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."

    Design: Corner/validations/second_call_report_for_the_same_period_rejects
    """
    license_id = active_license.license_id
    unfiled = fx.get_license(api, license_id)
    filed = fx.file_call_report(api, license_id, "2026Q2", 40_000_000, 700)
    # Q2 ends 2026-06-30 and due_at is that plus forty-five days, 2026-08-14, so a
    # filing at the 2026-08-01 clock is neither late nor internally inconsistent.
    assert filed["status"] == "FILED"
    before = fx.get_license(api, license_id)
    # The one accepted filing added its whole 40,000,000 to the rolling volume.
    assert before["annual_volume_cents"] == unfiled["annual_volume_cents"] + 40_000_000

    rejected = api.file_call_report(
        F.call_report_payload(license_id, "2026Q2", 5_000_000, 90), MANAGER_HEADERS
    )
    validate_error(rejected, ERR_DUPLICATE_CALL_REPORT)

    # Nothing moved: the rolling volume did not take the second filing's
    # 5,000,000, the reporting dimension held, and only one report exists.
    unchanged = fx.get_license(api, license_id)
    assert unchanged["annual_volume_cents"] == before["annual_volume_cents"]
    assert unchanged["reporting_status"] == "CURRENT"
    assert unchanged["version"] == before["version"]
    reports, meta = validate_paginated(
        api.list_license_call_reports(license_id, MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert reports[0]["period_label"] == "2026Q2"


# ---------------------------------------------------------------------------
# Information-request completeness
# ---------------------------------------------------------------------------


def test_short_information_response_rejects_as_incomplete(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Two of three demanded items is not a response at all.

    PRD 3.8: "A `StateRegulator` opens one against an `exam_id` with its own `jurisdiction_id`, a `subject` describing the records wanted, and a `requested_item_count` of at least one."
    PRD 3.8: "The exam must be in `FIELDWORK`, or the response is rejected with `ERR_EXAM_INVALID_STATE`; the request must be in `OPEN` or `OVERDUE`, or the response is rejected with `ERR_INFO_REQUEST_INVALID_STATE`; the logical clock must be on or before `due_at`, the boundary being inclusive, or the response is rejected with `ERR_RESPONSE_WINDOW_CLOSED`; and `submitted_item_count` must be at least `requested_item_count`, or the response is rejected with `ERR_RESPONSE_INCOMPLETE` (HTTP 422)."
    PRD 3.8: "A partial delivery is not a response."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."

    Design: Corner/validations/short_information_response_rejects_as_incomplete
    """
    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=3,
    )
    assert request["status"] == "OPEN"
    # California allows fifteen days, so due_at is 2026-08-16 and the clock at
    # 2026-08-01 is comfortably inside the window: only completeness can fail.
    assert request["due_at"].startswith("2026-08-16T00:00:00")

    rejected = api.respond_to_information_request(
        request["id"],
        F.information_response_payload(2, narrative="Two of three ledgers attached."),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_RESPONSE_INCOMPLETE)

    # Nothing moved: the demand is still open, nothing was banked against it,
    # and the exam's open-matter count is untouched.
    unchanged = validate_success(api.get_information_request(request["id"], regulator))
    assert unchanged["status"] == "OPEN"
    assert unchanged["submitted_item_count"] == 0
    assert unchanged.get("responded_at") is None
    assert unchanged["version"] == request["version"]
    assert validate_success(api.get_exam(exam["id"], regulator))["open_request_count"] == 1


def test_information_response_meeting_the_requested_count_exactly_is_accepted(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Three of three items satisfies the at-least test and lands as RESPONDED.

    PRD 3.8: "The exam must be in `FIELDWORK`, or the response is rejected with `ERR_EXAM_INVALID_STATE`; the request must be in `OPEN` or `OVERDUE`, or the response is rejected with `ERR_INFO_REQUEST_INVALID_STATE`; the logical clock must be on or before `due_at`, the boundary being inclusive, or the response is rejected with `ERR_RESPONSE_WINDOW_CLOSED`; and `submitted_item_count` must be at least `requested_item_count`, or the response is rejected with `ERR_RESPONSE_INCOMPLETE` (HTTP 422)."
    PRD 3.8: "On success the request moves to `RESPONDED`, `submitted_item_count` is stored and `responded_at` is stamped."
    PRD 3.8: "`open_request_count` does not move: a `RESPONDED` request is still an open matter as far as the exam is concerned, which is exactly why responding to every request is not enough to let the lead draft its report — each one must also be accepted."

    Design: Corner/validations/short_information_response_rejects_as_incomplete
    """
    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=3,
    )

    # Exactly the demanded count: 3 is at least 3.
    answered = fx.respond_to_information_request(api, request["id"], 3)
    assert answered["status"] == "RESPONDED"
    assert answered["submitted_item_count"] == 3
    assert answered["responded_at"] is not None
    # A RESPONDED request has not left the open set.
    assert validate_success(api.get_exam(exam["id"], regulator))["open_request_count"] == 1
