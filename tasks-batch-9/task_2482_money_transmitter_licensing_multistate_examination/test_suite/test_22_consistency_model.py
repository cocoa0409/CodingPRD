"""Read-your-writes: every derived figure is already correct in the write response.

An obligations adjustment is the widest-reaching ordinary write in the model: it
moves one licence's balance and then re-derives the licensee's obligation
aggregate, both permissible-investment values, the coverage ratio, the posture
and the expansion gate of every affected licence. PRD 2.2 says a write returns
the updated resource, so the response body of the adjustment must already carry
the recomputed licence state, and the first read that follows must already carry
the recomputed licensee state. Nothing here converges on a second call.
"""

from typing import Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import MANAGER_HEADERS

# The derived licence fields the write response and the immediate read must agree
# on character for character.
LICENSE_DERIVED_FIELDS = (
    "outstanding_obligations_cents",
    "license_status",
    "reporting_status",
    "expansion_gate",
    "bond_status",
    "bond_requirement_cents",
    "version",
    "updated_at",
)

# The derived licensee fields that must be correct on the very first read.
LICENSEE_DERIVED_FIELDS = (
    "aggregate_outstanding_obligations_cents",
    "eligible_investment_value_cents",
    "book_investment_value_cents",
    "coverage_ratio_bps",
    "coverage_posture",
    "consecutive_failed_test_count",
    "version",
    "updated_at",
)


def _license_derived(license_row: Dict[str, object]) -> Dict[str, object]:
    return {field: license_row[field] for field in LICENSE_DERIVED_FIELDS}


def _licensee_derived(licensee_row: Dict[str, object]) -> Dict[str, object]:
    return {field: licensee_row[field] for field in LICENSEE_DERIVED_FIELDS}


def test_the_obligations_write_response_already_carries_every_recomputed_figure(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One adjustment; the write body and the first read are already converged.

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD 3.4: "The delta is added to the licence's `outstanding_obligations_cents`, and the resulting balance may never go below zero — an adjustment that would drive it negative is rejected with `ERR_NEGATIVE_OBLIGATIONS` (HTTP 422)."
    PRD 3.4: "The adjustment then re-derives, in order: the licensee's `aggregate_outstanding_obligations_cents`, both permissible-investment values, `coverage_ratio_bps` and `coverage_posture`."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "A licensee-level coverage read exposes both variants side by side over identical holdings — `obligations_cents`, `book_investment_value_cents`, `book_coverage_ratio_bps`, `eligible_investment_value_cents`, `coverage_ratio_bps`, `concentration_cap_cents`, `coverage_posture` and `consecutive_failed_test_count` — so that the divergence is observable in a single response."

    Design: Corner/consistency_model/derived_licensee_state_is_visible_in_the_same_request
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    opening = fx.get_license(api, active_license.license_id)
    assert opening["outstanding_obligations_cents"] == 0
    assert opening["expansion_gate"] == "OPEN"

    written = validate_success(
        api.adjust_obligations(
            active_license.license_id,
            F.obligations_payload(5_263_157, memo="Same-request visibility probe"),
            MANAGER_HEADERS,
        )
    )

    # The write response itself already carries the new balance and the
    # re-derived gate: a WATCH posture still satisfies the fifth gate condition.
    assert written["outstanding_obligations_cents"] == 5_263_157
    assert written["expansion_gate"] == "OPEN"
    assert written["version"] == opening["version"] + 1

    # The immediately following read of the same licence is byte-identical.
    reread = fx.get_license(api, active_license.license_id)
    assert _license_derived(reread) == _license_derived(written)

    # The first read of the licensee after the write is already correct: cash
    # carries no haircut so both variants stand at 5000000, and
    # floor(5000000 * 10000 / 5263157) == 9500 bps, which is the WATCH floor.
    licensee_row = fx.get_licensee(api, active_license.licensee_id)
    assert licensee_row["aggregate_outstanding_obligations_cents"] == 5_263_157
    assert licensee_row["eligible_investment_value_cents"] == 5_000_000
    assert licensee_row["book_investment_value_cents"] == 5_000_000
    assert licensee_row["coverage_ratio_bps"] == 9500
    assert licensee_row["coverage_posture"] == "WATCH"

    # The computed coverage read agrees with it on the same first call, including
    # the cap: floor(5263157 * 1000 / 10000) == 526315 cents.
    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    assert summary["obligations_cents"] == 5_263_157
    assert summary["eligible_investment_value_cents"] == 5_000_000
    assert summary["book_investment_value_cents"] == 5_000_000
    assert summary["coverage_ratio_bps"] == 9500
    assert summary["book_coverage_ratio_bps"] == 9500
    assert summary["concentration_cap_cents"] == 526_315
    assert summary["coverage_posture"] == "WATCH"
    assert summary["consecutive_failed_test_count"] == 0

    # No second call is needed to converge: repeating both reads returns exactly
    # the same derived values, and the rows were not touched by reading them.
    assert _licensee_derived(fx.get_licensee(api, active_license.licensee_id)) == (
        _licensee_derived(licensee_row)
    )
    assert fx.get_coverage_summary(api, active_license.licensee_id) == summary
    assert _license_derived(fx.get_license(api, active_license.license_id)) == (
        _license_derived(written)
    )


def test_a_posture_drop_is_visible_in_the_same_response_as_the_write_that_causes_it(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The adjustment that drops the posture returns the already-blocked gate.

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 2.9: "The **posture cascade** begins whenever a licensee's `coverage_posture` becomes `DEFICIENT` or `FROZEN`."
    PRD 2.9: "Every `StateLicense` of that licensee whose `license_status` is `ACTIVE` has `expansion_gate` set to `BLOCKED`."
    PRD 3.4: "If the posture drops to `DEFICIENT` or `FROZEN`, the posture cascade of §2.9 runs."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."

    Design: Corner/consistency_model/derived_licensee_state_is_visible_in_the_same_request
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    assert fx.get_license(api, active_license.license_id)["expansion_gate"] == "OPEN"
    assert fx.get_licensee(api, active_license.licensee_id)["coverage_posture"] == "COMPLIANT"

    written = validate_success(
        api.adjust_obligations(
            active_license.license_id,
            F.obligations_payload(5_300_000, memo="Single write below the WATCH floor"),
            MANAGER_HEADERS,
        )
    )

    # floor(5000000 * 10000 / 5300000) == 9433 bps, below the 9500 WATCH floor,
    # so the posture drops to DEFICIENT and the cascade blocks this very licence
    # inside the response that reports the write.
    assert written["outstanding_obligations_cents"] == 5_300_000
    assert written["license_status"] == "ACTIVE"
    assert written["expansion_gate"] == "BLOCKED"

    reread = fx.get_license(api, active_license.license_id)
    assert _license_derived(reread) == _license_derived(written)

    licensee_row = fx.get_licensee(api, active_license.licensee_id)
    assert licensee_row["aggregate_outstanding_obligations_cents"] == 5_300_000
    assert licensee_row["coverage_ratio_bps"] == 9433
    assert licensee_row["coverage_posture"] == "DEFICIENT"

    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    assert summary["obligations_cents"] == 5_300_000
    assert summary["coverage_ratio_bps"] == 9433
    assert summary["coverage_posture"] == "DEFICIENT"

    # The first read after the write was already the settled one.
    assert _licensee_derived(fx.get_licensee(api, active_license.licensee_id)) == (
        _licensee_derived(licensee_row)
    )
    assert fx.get_coverage_summary(api, active_license.licensee_id) == summary
