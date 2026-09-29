"""Layers that cut across the whole model: optimistic concurrency and the frozen rung.

Two write operations in this API are guarded by an optimistic-concurrency token
(PRD 2.6): creating a permissible-investment test carries
``expected_licensee_version`` and filing a surrender request carries
``expected_state_license_version``. Both guards sit above every state and
business check in the ladder of PRD 2.7, so a stale writer is told it is stale
and the guarded row does not move. The third layer here is the cumulative
counter behind ``coverage_posture``: ``FROZEN`` is the first rung of the ordered
posture test of PRD 3.7, reached only by two consecutive certified shortfalls,
and once reached it outranks even a perfect ratio.
"""

from typing import Dict

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
    ERR_POSTURE_FROZEN,
    ERR_STALE_LICENSE_VERSION,
    ERR_STALE_LICENSEE_VERSION,
)
from test_helpers.test_users import (
    CHIEF_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    SECOND_CHIEF_HEADERS,
)

# The two closed coverage periods the shortfall tests file on. Both certify well
# inside the forty-five day window that PRD 3.7 measures from
# coverage_period_end: 2026-06-30 + 45 days is 2026-08-14 and 2026-07-31 + 45
# days is 2026-09-14, while the logical clock stays at its 2026-08-01 start.
FIRST_PERIOD_START = "2026-06-01T00:00:00Z"
FIRST_PERIOD_END = "2026-06-30T00:00:00Z"
SECOND_PERIOD_START = "2026-07-01T00:00:00Z"
SECOND_PERIOD_END = "2026-07-31T00:00:00Z"

# The derived licence fields a rejected write must leave exactly where they were.
LICENSE_HELD_FIELDS = (
    "license_status",
    "reporting_status",
    "expansion_gate",
    "bond_status",
    "outstanding_obligations_cents",
    "version",
    "updated_at",
)


def _license_snapshot(license_row: Dict[str, object]) -> Dict[str, object]:
    """The subset of a licence row that a version-guarded reject must not touch."""
    return {field: license_row[field] for field in LICENSE_HELD_FIELDS}


def _certify_a_shortfall(
    api: MoneyTransmitterApiClient,
    licensee_id: str,
    coverage_period_start: str,
    coverage_period_end: str,
) -> Dict[str, object]:
    """Open, prepare and certify one ELIGIBLE_MARKET test on the current figures.

    The chief compliance officer prepares and a second, distinct chief
    compliance officer certifies, so the segregation of duties of PRD 2.10 is
    satisfied and the only thing the certification can express is the verdict.
    """
    test = fx.open_investment_test(
        api,
        licensee_id,
        "ELIGIBLE_MARKET",
        coverage_period_start=coverage_period_start,
        coverage_period_end=coverage_period_end,
    )
    prepared = fx.prepare_investment_test(api, test["id"], CHIEF_HEADERS)
    assert prepared["status"] == "PREPARED"
    assert prepared["result"] == "SHORTFALL"
    certified = validate_success(
        api.certify_investment_test(test["id"], SECOND_CHIEF_HEADERS, F.certify_payload())
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["result"] == "SHORTFALL"
    return certified


def _licensee_with_two_certified_shortfalls(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> Dict[str, object]:
    """Drive coverage to 5000 bps and certify two consecutive shortfalls on it."""
    fx.record_holding(
        api, scenario.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    fx.adjust_obligations(api, scenario.license_id, 10_000_000)
    _certify_a_shortfall(api, scenario.licensee_id, FIRST_PERIOD_START, FIRST_PERIOD_END)
    _certify_a_shortfall(api, scenario.licensee_id, SECOND_PERIOD_START, SECOND_PERIOD_END)
    frozen = fx.get_licensee(api, scenario.licensee_id)
    assert frozen["consecutive_failed_test_count"] == 2
    assert frozen["coverage_posture"] == "FROZEN"
    return frozen


# ---------------------------------------------------------------------------
# The licensee-version guard on creating a permissible-investment test
# ---------------------------------------------------------------------------


def test_a_licensee_version_stale_by_one_financials_patch_cannot_open_a_coverage_test(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The pre-patch version is refused; refetching and retrying succeeds.

    PRD 2.6: "Creating a permissible-investment test requires the request body to carry `expected_licensee_version`, a non-optional field holding the client's last observed `version` of the parent `Licensee`."
    PRD 2.6: "If that value does not equal the licensee's current `version`, the create is rejected with `ERR_STALE_LICENSEE_VERSION` (HTTP 412)."
    PRD 2.6: "Many other operations bump `Licensee.version` too — a financials update, a holding creation or disposal, an obligations adjustment, a test certification — and each of them therefore invalidates a client's cached version."
    PRD 3.1: "That version bump matters far beyond the financial statement itself, because it invalidates any `expected_licensee_version` a client was holding for a coverage test it had not yet created."
    PRD 2.7: "Both sit above every state and business check, so a stale writer learns that it is stale rather than learning about a business condition it may no longer be seeing correctly."
    PRD 3.7: "The row starts in `DRAFT`; the other statuses are `PREPARED`, and the terminal `CERTIFIED` and `SUPERSEDED`."

    Design: Corner/cross_cutting_complexity_layers/stale_licensee_version_blocks_a_new_permissible_investment_test
    """
    fx.record_holding(
        api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )
    observed = fx.get_licensee(api, licensee["id"])
    stale_version = observed["version"]

    patched = fx.update_financials(
        api,
        licensee["id"],
        reported_tangible_net_worth_cents=480_000_000,
        net_worth_statement_date="2026-07-31T00:00:00Z",
    )
    fresh_version = patched["version"]
    # A financials patch is one mutation of the licensee row, so its version
    # advances by exactly one even though no holding changed.
    assert fresh_version == stale_version + 1

    rejected = api.create_investment_test(
        F.investment_test_payload(licensee["id"], "ELIGIBLE_MARKET", stale_version),
        OFFICER_HEADERS,
    )
    validate_error(rejected, ERR_STALE_LICENSEE_VERSION)

    # Nothing moved: no test row was created and the licensee version held.
    rows, meta = validate_paginated(
        api.list_investment_tests(OFFICER_HEADERS, params={"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    held = fx.get_licensee(api, licensee["id"])
    assert held["version"] == fresh_version
    assert held["reported_tangible_net_worth_cents"] == 480_000_000

    # The success side: the same call with the refreshed token is accepted.
    created = validate_success(
        api.create_investment_test(
            F.investment_test_payload(licensee["id"], "ELIGIBLE_MARKET", fresh_version),
            OFFICER_HEADERS,
        ),
        201,
    )
    assert created["status"] == "DRAFT"
    assert created["method"] == "ELIGIBLE_MARKET"
    assert created["licensee_id"] == licensee["id"]
    assert created["result"] is None
    # The accepted create is itself a mutation of the licensee, so the token it
    # consumed is now one behind again.
    assert fx.get_licensee(api, licensee["id"])["version"] == fresh_version + 1


def test_replaying_a_consumed_licensee_version_opens_no_second_coverage_test(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The token a successful create consumed is refused on replay.

    PRD 2.6: "A successful create bumps `Licensee.version`, so replaying the same `expected_licensee_version` a second time is rejected."
    PRD 2.6: "If that value does not equal the licensee's current `version`, the create is rejected with `ERR_STALE_LICENSEE_VERSION` (HTTP 412)."
    PRD 3.7: "Creating a new test supersedes the old work: any existing test of the same licensee whose status is `DRAFT` or `PREPARED` moves to the terminal `SUPERSEDED`, and the create bumps `Licensee.version`."

    Design: Corner/cross_cutting_complexity_layers/stale_licensee_version_blocks_a_new_permissible_investment_test
    """
    consumed_version = fx.get_licensee(api, licensee["id"])["version"]

    first = validate_success(
        api.create_investment_test(
            F.investment_test_payload(licensee["id"], "ELIGIBLE_MARKET", consumed_version),
            OFFICER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "DRAFT"
    # The create bumped the licensee, so the token it carried is now stale.
    assert fx.get_licensee(api, licensee["id"])["version"] == consumed_version + 1

    replayed = api.create_investment_test(
        F.investment_test_payload(licensee["id"], "ELIGIBLE_MARKET", consumed_version),
        OFFICER_HEADERS,
    )
    validate_error(replayed, ERR_STALE_LICENSEE_VERSION)

    # Nothing moved: still exactly one test row, still DRAFT rather than
    # superseded, and the licensee version did not advance a second time.
    rows, meta = validate_paginated(
        api.list_investment_tests(OFFICER_HEADERS, params={"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["version"] == first["version"]
    assert fx.get_licensee(api, licensee["id"])["version"] == consumed_version + 1


# ---------------------------------------------------------------------------
# The licence-version guard on filing a surrender request
# ---------------------------------------------------------------------------


def test_a_license_version_stale_by_two_netting_obligation_writes_cannot_file_surrender(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The post-bond version is refused although the business state is unchanged.

    PRD 2.6: "Filing a surrender request requires the request body to carry `expected_state_license_version`, a non-optional field holding the client's last observed `version` of the parent `StateLicense`."
    PRD 2.6: "If it does not equal the licence's current `version`, the request is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412)."
    PRD 2.6: "Obligation adjustments, bond events, delegate activations, renewals and surrender decisions all bump the licence version, and every one of them changes whether surrender is admissible at all, so a client working from a stale view must not be allowed to move a licence into `SURRENDER_REQUESTED`."
    PRD 3.4: "Both the licence's `version` and the licensee's `version` are bumped."
    PRD 3.4: "Two substantive conditions apply: the licence's `outstanding_obligations_cents` must be exactly zero, or the request is rejected with `ERR_OUTSTANDING_OBLIGATIONS_REMAIN`; and no `DelegateAuthorization` of the licence may still be `ACTIVE`, or the request is rejected with `ERR_ACTIVE_DELEGATES_REMAIN`."
    PRD 3.4: "On success the licence moves to `SURRENDER_REQUESTED`, `expansion_gate` is set to `BLOCKED`, `version` is bumped, and `active_license_count` is reduced by one — but only when the prior status was `ACTIVE`; surrendering an already-suspended licence moves no counter, because the suspension already decremented it."

    Design: Corner/cross_cutting_complexity_layers/stale_license_version_blocks_a_surrender_request
    """
    stale_version = active_license.extra["license"]["version"]

    fx.adjust_obligations(api, active_license.license_id, 250_000, memo="Intraday float")
    settled = fx.adjust_obligations(
        api, active_license.license_id, -250_000, memo="Float settled"
    )
    fresh_version = settled["version"]
    # Two obligation adjustments are two mutations, so the version advanced
    # twice even though +250000 then -250000 nets the balance back to zero.
    assert settled["outstanding_obligations_cents"] == 0
    assert fresh_version == stale_version + 2

    # Both substantive surrender conditions hold, so the version guard is the
    # only reason the stale call can fail: the balance is zero and the licence
    # carries no delegate authorization at all.
    before = fx.get_license(api, active_license.license_id)
    assert before["license_status"] == "ACTIVE"
    assert before["outstanding_obligations_cents"] == 0
    authorizations, auth_meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"state_license_id": active_license.license_id}
        )
    )
    assert auth_meta["total_count"] == 0
    assert authorizations == []
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1

    rejected = api.request_surrender(
        active_license.license_id,
        F.surrender_request_payload(stale_version),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_STALE_LICENSE_VERSION)

    # Nothing moved: the guarded row is byte-for-byte where it was, no
    # SURRENDER_REQUESTED transition happened and the counter did not drop.
    held = fx.get_license(api, active_license.license_id)
    assert _license_snapshot(held) == _license_snapshot(before)
    assert held["license_status"] == "ACTIVE"
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1

    # The success side: the same call with the refreshed token is accepted.
    filed = validate_success(
        api.request_surrender(
            active_license.license_id,
            F.surrender_request_payload(fresh_version),
            MANAGER_HEADERS,
        )
    )
    assert filed["license_status"] == "SURRENDER_REQUESTED"
    assert filed["expansion_gate"] == "BLOCKED"
    assert filed["version"] == fresh_version + 1
    # The prior status was ACTIVE, so the one authorised licence is decremented.
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


def test_replaying_a_consumed_license_version_leaves_the_surrender_request_alone(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The token the accepted surrender consumed is refused on replay.

    PRD 2.6: "A successful surrender request bumps `StateLicense.version`, so a replayed request with the same expected version is rejected."
    PRD 2.6: "If it does not equal the licence's current `version`, the request is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412)."
    PRD 2.7: "6. **Version guards** — `expected_licensee_version` (`ERR_STALE_LICENSEE_VERSION`), then `expected_state_license_version` (`ERR_STALE_LICENSE_VERSION`)."
    PRD 3.4: "The request carries an `effective_date`, a `wind_down_narrative` and the `expected_state_license_version` guard of §2.6, and is admissible from either `ACTIVE` or `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/stale_license_version_blocks_a_surrender_request
    """
    consumed_version = active_license.extra["license"]["version"]

    filed = validate_success(
        api.request_surrender(
            active_license.license_id,
            F.surrender_request_payload(consumed_version),
            MANAGER_HEADERS,
        )
    )
    assert filed["license_status"] == "SURRENDER_REQUESTED"
    # The accepted request bumped the licence, so the token is now one behind.
    assert filed["version"] == consumed_version + 1

    before = fx.get_license(api, active_license.license_id)
    replayed = api.request_surrender(
        active_license.license_id,
        F.surrender_request_payload(consumed_version),
        MANAGER_HEADERS,
    )
    validate_error(replayed, ERR_STALE_LICENSE_VERSION)

    # Nothing moved: the licence is still the single SURRENDER_REQUESTED row at
    # the same version, and the counter was not decremented a second time.
    held = fx.get_license(api, active_license.license_id)
    assert _license_snapshot(held) == _license_snapshot(before)
    assert held["license_status"] == "SURRENDER_REQUESTED"
    assert held["version"] == consumed_version + 1
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


# ---------------------------------------------------------------------------
# The cumulative counter behind a FROZEN posture
# ---------------------------------------------------------------------------


def test_only_the_second_consecutive_certified_shortfall_freezes_the_posture(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One certified shortfall reads DEFICIENT; the second reads FROZEN.

    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "First, the test moves `PREPARED → CERTIFIED`, `certified_at` is stamped from the logical clock, `certified_by_user_id` records the acting identity, and the licensee's `consecutive_failed_test_count` either increases by one — when the test's `result` is `SHORTFALL` — or resets to zero when it is `PASS`; `coverage_posture` is then recomputed, and because two consecutive certified shortfalls set the count to 2, the second one alone forces the posture to `FROZEN` no matter how good the ratio looks."

    Design: Corner/cross_cutting_complexity_layers/two_consecutive_certified_shortfalls_freeze_the_posture
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    fx.adjust_obligations(api, active_license.license_id, 10_000_000)

    # Cash carries no haircut, so the eligible value is the full 5000000 against
    # 10000000 of obligations: floor(5000000 * 10000 / 10000000) == 5000 bps.
    opening = fx.get_licensee(api, active_license.licensee_id)
    assert opening["eligible_investment_value_cents"] == 5_000_000
    assert opening["aggregate_outstanding_obligations_cents"] == 10_000_000
    assert opening["coverage_ratio_bps"] == 5000
    assert opening["consecutive_failed_test_count"] == 0

    first = _certify_a_shortfall(
        api, active_license.licensee_id, FIRST_PERIOD_START, FIRST_PERIOD_END
    )
    # The shortfall is 10000000 of obligations less 5000000 of eligible value.
    assert first["obligations_cents"] == 10_000_000
    assert first["investment_value_cents"] == 5_000_000
    assert first["coverage_ratio_bps"] == 5000
    assert first["shortfall_cents"] == 5_000_000

    after_one = fx.get_licensee(api, active_license.licensee_id)
    # One certified shortfall is a count of 1, below the FROZEN rung of 2, so the
    # ratio decides and 5000 bps is below the 9500 WATCH floor.
    assert after_one["consecutive_failed_test_count"] == 1
    assert after_one["coverage_ratio_bps"] == 5000
    assert after_one["coverage_posture"] == "DEFICIENT"

    second = _certify_a_shortfall(
        api, active_license.licensee_id, SECOND_PERIOD_START, SECOND_PERIOD_END
    )
    assert second["shortfall_cents"] == 5_000_000

    after_two = fx.get_licensee(api, active_license.licensee_id)
    # The second consecutive certified shortfall sets the count to 2, which is
    # the first rung of the ordered posture test.
    assert after_two["consecutive_failed_test_count"] == C.FROZEN_FAILED_TEST_COUNT == 2
    assert after_two["coverage_ratio_bps"] == 5000
    assert after_two["coverage_posture"] == "FROZEN"

    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    assert summary["obligations_cents"] == 10_000_000
    assert summary["coverage_ratio_bps"] == 5000
    assert summary["consecutive_failed_test_count"] == 2
    assert summary["coverage_posture"] == "FROZEN"


def test_a_frozen_posture_refuses_a_new_delegate_authorization(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """With the posture FROZEN, appointing an agent to the licence is refused.

    PRD 3.6: "The licensee's `coverage_posture` must not be `FROZEN`, or creation is rejected with `ERR_POSTURE_FROZEN`."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.7: "A `FROZEN` posture then blocks application submission, application approval and new delegate authorizations with `ERR_POSTURE_FROZEN`."

    Design: Corner/cross_cutting_complexity_layers/two_consecutive_certified_shortfalls_freeze_the_posture
    """
    delegate = fx.create_delegate(api, active_license.licensee_id)
    scored = fx.review_delegate(
        api, delegate["id"], training_score=90, aml_test_score=90, recordkeeping_score=70
    )
    # 90 * 4000 + 90 * 3500 + 70 * 2500 == 850000, and 850000 / 10000 floored is
    # 85, comfortably above the activation floor of 70, so the oversight rule
    # cannot be what refuses the appointment.
    assert scored["oversight_score"] == 85

    _licensee_with_two_certified_shortfalls(api, active_license)

    # The licence itself is still authorised, so ERR_LICENSE_NOT_ACTIVE is not
    # in play either.
    assert fx.get_license(api, active_license.license_id)["license_status"] == "ACTIVE"

    rejected = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            active_license.license_id,
            "2026-09-01T00:00:00Z",
            "2027-08-31T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(rejected, ERR_POSTURE_FROZEN)

    # Nothing moved: no authorization row exists and the delegate is untouched.
    rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
    held = fx.get_licensee(api, active_license.licensee_id)
    assert held["coverage_posture"] == "FROZEN"
    delegate_row = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_row["authorized_state_count"] == 0
    assert delegate_row["oversight_score"] == 85
    # No authorization was created, so nothing counts against the bond either.
    assert fx.get_license(api, active_license.license_id)["active_delegate_count"] == 0


def test_a_frozen_posture_survives_a_cash_injection_that_restores_full_coverage(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The FROZEN rung is tested first, so a 10000 bps ratio does not clear it.

    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "Both recording a holding and disposing of one recompute the licensee's coverage figures and posture and bump `Licensee.version`."
    PRD 2.8: "If any one of the five fails, the gate is `BLOCKED`."

    Design: Corner/cross_cutting_complexity_layers/two_consecutive_certified_shortfalls_freeze_the_posture
    """
    frozen = _licensee_with_two_certified_shortfalls(api, active_license)
    assert frozen["coverage_ratio_bps"] == 5000

    # A second 5000000 of cash brings the eligible value to the full 10000000 of
    # obligations: floor(10000000 * 10000 / 10000000) == 10000 bps, which is the
    # COMPLIANT band on ratio alone.
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "Pacific Custody Bank", 5_000_000, 5_000_000
    )

    recovered = fx.get_licensee(api, active_license.licensee_id)
    assert recovered["eligible_investment_value_cents"] == 10_000_000
    assert recovered["aggregate_outstanding_obligations_cents"] == 10_000_000
    assert recovered["coverage_ratio_bps"] == 10_000
    # The counter still stands at 2, and that rung is tested before the ratio.
    assert recovered["consecutive_failed_test_count"] == 2
    assert recovered["coverage_posture"] == "FROZEN"

    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    assert summary["coverage_ratio_bps"] == 10_000
    assert summary["coverage_posture"] == "FROZEN"

    # A FROZEN posture fails the fifth gate condition, so the licence's
    # expansion gate stays BLOCKED even at full coverage.
    assert fx.get_license(api, active_license.license_id)["expansion_gate"] == "BLOCKED"
