"""Aggregation and tiered-pricing calculations: per-line license markup with
round-per-line-then-sum, and retainer care-cycle tiered overage."""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    create_and_activate_project,
    setup_closed_care_cycle,
    create_license_payload,
)

SO = TEST_USERS["studio_ops_headers"]
BO = TEST_USERS["billing_ops_headers"]


def test_license_billable_rounds_per_line_then_sums(api):
    """PRD §2.5: "License markup is rounded **per line** — each license's billable amount is rounded to whole cents on its own before any project-level total sums those rounded line amounts together (round-per-line, then sum; never sum-then-round)."

    Design: Difficulty/combinatorial_formula/license_rollup_round_per_line_then_sum_order_pinned
    """
    studio, client, project, _ = create_and_activate_project(
        [50000], deposit_pct=0.20, service_type="WEB", license_markup_pct=0.0825
    )
    sid, pid = studio["id"], project["id"]
    lic1 = validate_success(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=100), SO
    ), expected_status=201)
    lic2 = validate_success(api.create_license(
        sid, create_license_payload(pid, "2026-03-11T00:00:00Z", "2026-03-20T00:00:00Z", kind="FONT", cost_cents=100), SO
    ), expected_status=201)

    assert lic1["billable_cents"] == 108, "round_half_up(100 * 1.0825)"
    assert lic2["billable_cents"] == 108
    assert lic1["billable_cents"] + lic2["billable_cents"] == 216, \
        "round-per-line-then-sum gives 216, not the sum-then-round 217"


def test_license_billable_each_line_independently_rounded(api):
    """PRD §3.7: "This per-line rounding is deliberate — each license's billable
    amount is rounded on its own, and any project-level license total is formed by
    summing the already-rounded per-line amounts rather than rounding a raw sum."

    Design: Difficulty/combinatorial_formula/license_rollup_round_per_line_then_sum_order_pinned
    """
    studio, client, project, _ = create_and_activate_project(
        [50000], deposit_pct=0.20, service_type="WEB", license_markup_pct=0.0825
    )
    sid, pid = studio["id"], project["id"]
    lic = validate_success(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=100), SO
    ), expected_status=201)
    # 100 * 1.0825 = 108.25 -> round_half_up -> 108
    assert lic["billable_cents"] == 108


def test_license_billable_computed_ignores_client_supplied_value(api):
    """PRD §3.7: "the system computes its billable_cents immediately: the cost
    multiplied by one plus the studio's license_markup_pct, rounded half up to
    whole cents."

    Design: Corner/entities/license_billable_computed_input_billable_ignored
    """
    studio, client, project, _ = create_and_activate_project(
        [50000], deposit_pct=0.20, service_type="WEB", license_markup_pct=0.10
    )
    sid, pid = studio["id"], project["id"]
    payload = create_license_payload(
        pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=2000,
    )
    payload["billable_cents"] = 999999  # client-supplied value must be ignored
    lic = validate_success(api.create_license(sid, payload, SO), expected_status=201)
    assert lic["billable_cents"] == 2200, "round_half_up(2000 * 1.10)"
    assert lic["status"] == "RESERVED"


def test_retainer_overage_nonlinear_two_tier_at_sixteen_hours(api):
    """PRD §3.10: "The first five of those overage hours are billed at the
    retainer's tier1_rate_cents; specifically the first-tier hours are the smaller
    of the raw overage hours and five. Any overage hours beyond the first five — the
    raw overage hours minus five, floored at zero — are billed at the retainer's
    tier2_rate_cents."

    Design: Difficulty/combinatorial_formula/retainer_overage_nonlinear_tier_min_max_branches
    """
    sid, retainer, cc = setup_closed_care_cycle(
        monthly_fee_cents=200000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
        hours_used=16,
    )
    # raw overage = 16 - 10 = 6 -> tier1 5h * 5000 + tier2 1h * 8000 = 33000
    assert cc["overage_cents"] == 33000
    assert cc["billed_cents"] == 233000, "monthly 200000 + overage 33000"
    assert cc["status"] == "CLOSED"


def test_retainer_billed_is_monthly_fee_plus_overage(api):
    """PRD §3.10: "The `billed_cents` is then the retainer's `monthly_fee_cents` plus the computed `overage_cents`."

    Design: Difficulty/combinatorial_formula/retainer_overage_nonlinear_tier_min_max_branches
    """
    sid, retainer, cc = setup_closed_care_cycle(
        monthly_fee_cents=200000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
        hours_used=16,
    )
    assert cc["billed_cents"] == cc["overage_cents"] + 200000


def test_retainer_overage_zero_when_within_included_hours(api):
    """PRD §3.10: "When usage is within the included hours the overage is zero."

    Design: Corner/calculations/retainer_overage_within_included_zero
    """
    sid, retainer, cc = setup_closed_care_cycle(
        monthly_fee_cents=100000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
        hours_used=8,
    )
    assert cc["overage_cents"] == 0
    assert cc["billed_cents"] == 100000


def test_retainer_overage_all_tier1_at_exactly_five_overage_hours(api):
    """PRD §3.10: "The boundary is exact: when overage is at or below five hours the
    whole of it stays in the first tier, and the second tier engages only beyond
    five overage hours."

    Design: Corner/calculations/retainer_overage_boundary_exactly_five_overage_hours_all_tier1
    """
    sid, retainer, cc = setup_closed_care_cycle(
        monthly_fee_cents=200000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
        hours_used=15,
    )
    # raw overage = 5 -> entirely tier-1: 5 * 5000 = 25000
    assert cc["overage_cents"] == 25000
    assert cc["billed_cents"] == 225000
