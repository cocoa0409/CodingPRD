"""Two-variant calculations: the SLA deadline, the hygiene score, plan
proration rounding order, and the loyalty tier pinned to the pre-discount
total."""
from test_helpers import (
    validate_success, assert_same_instant, assert_cycle_money_arithmetic,
    fixtures as fx,
)


# ==========================================================================
# The removal SLA deadline: BASE versus ESCALATED_RESUBMISSION
# ==========================================================================

def _postal_us_ca_world():
    """A POSTAL / US_CA broker with a 30-day self-declared window, one FOUND
    exposure at it, and a DRAFTED removal request, all at 2026-05-11."""
    household = fx.open_household()
    broker = fx.create_broker(name="PeopleFinderCo", opt_out_method="POSTAL",
                              jurisdiction="US_CA", response_window_days=30,
                              requires_identity_verification=False)
    profile = fx.setup_active_profile(household)
    fx.set_clock("2026-05-11T00:00:00Z")
    scan, exposures = fx.run_scan(profile["id"], [broker["id"]], kind="INITIAL")
    request = fx.draft_removal(exposures[0]["id"])
    return household, broker, request


def test_sla_deadline_base_variant_takes_the_jurisdiction_floor(api):
    """PRD §3.5: "Under the **`BASE`** variant, used on the `DRAFTED → SUBMITTED` edge,
    the server first takes the broker's method buffer in days — 0 for `WEB_FORM`, 2 for
    `EMAIL`, 7 for `POSTAL`, 3 for `PHONE` — and adds it to the broker's
    `response_window_days`; it then takes the larger of that sum and the broker's
    jurisdiction floor, which is 45 days for `US_CA`, 45 days for `US_VA`, 30 days for
    `EU` and 21 days for `OTHER`."
    PRD §3.5: "The result is stored as `effective_window_days`, `deadline_variant` is set
    to `BASE`, and `sla_deadline_at` is `submitted_at` advanced by that many whole days
    (each day being 86400 seconds), preserving the millisecond precision of `submitted_at`."

    Design: Difficulty/dual_variant_calc/sla_deadline_base_vs_escalated_resubmission
    """
    _, _, request = _postal_us_ca_world()

    data = validate_success(api.submit_removal_request(request["id"], fx.AGENT))

    assert data["deadline_variant"] == "BASE"
    # 30 declared window + 7 POSTAL buffer = 37; max(37, 45 US_CA floor) = 45.
    assert data["effective_window_days"] == 45
    # submitted_at 2026-05-11 + 45 whole days: 20 days to 2026-05-31, 25 more to 2026-06-25.
    assert_same_instant(data["sla_deadline_at"], "2026-06-25T00:00:00Z", "sla_deadline_at")
    assert_same_instant(data["submitted_at"], "2026-05-11T00:00:00Z", "submitted_at")
    assert data["status"] == "SUBMITTED"


def test_sla_deadline_escalated_resubmission_variant_uses_a_flat_window(api):
    """PRD §3.5: "Under the **`ESCALATED_RESUBMISSION`** variant, used on the
    `ESCALATED → SUBMITTED` edge, `effective_window_days` is a flat 15 days — the method
    buffer and the jurisdiction floor are both ignored entirely, so the same broker yields
    a strictly shorter deadline on the second pass — and `deadline_variant` records
    `ESCALATED_RESUBMISSION`."

    Design: Difficulty/dual_variant_calc/sla_deadline_base_vs_escalated_resubmission
    """
    _, _, request = _postal_us_ca_world()
    fx.submit_removal(request["id"])

    # The BASE deadline is 2026-06-25; expiry is admitted at exactly that instant.
    fx.set_clock("2026-06-25T00:00:00Z")
    validate_success(api.expire_removal_request(request["id"], fx.AGENT))
    validate_success(api.escalate_removal_request(request["id"], fx.AGENT))

    data = validate_success(api.submit_removal_request(request["id"], fx.AGENT))

    assert data["deadline_variant"] == "ESCALATED_RESUBMISSION"
    assert data["effective_window_days"] == 15
    # 2026-06-25 + 15 whole days = 2026-07-10 (5 days to month end, 10 into July).
    assert_same_instant(data["sla_deadline_at"], "2026-07-10T00:00:00Z", "sla_deadline_at")
    assert data["escalation_count"] == 1
    assert data["status"] == "SUBMITTED"


# ==========================================================================
# The hygiene score: NO_TWO_FACTOR versus TWO_FACTOR_ATTESTED
# ==========================================================================

def _four_finding_profile():
    """One DRAFT profile with two_factor_attested false carrying four OPEN
    findings whose weights sum to 25 + 18 + 12 + 7 = 62, below the 70 cap."""
    household = fx.open_household()
    profile = fx.draft_profile(household, two_factor_attested=False)
    for finding_type, detail in (("BREACHED_PASSWORD", "corp mail vault"),
                                 ("WEAK_PASSWORD", "retail login"),
                                 ("REUSED_PASSWORD", "forum login"),
                                 ("STALE_PASSWORD", "old router admin")):
        fx.add_credential_finding(profile["id"], finding_type, detail=detail)
    return household, profile


def test_hygiene_score_no_two_factor_variant_subtracts_the_full_penalty(api):
    """PRD §3.7: "The **multiplier** is selected from the profile's attestation: 0.60 when
    `two_factor_attested` is true, and 1.00 when it is false."
    PRD §3.7: "The **hygiene score** is 100 minus the adjusted penalty, rounded half-up to
    2 decimal places."
    PRD §3.7: "The **hygiene band** is `STRONG` when the score is at least 80, otherwise
    `MODERATE` when it is at least 60, otherwise `WEAK` when it is at least 40, and
    `CRITICAL` in every remaining case."

    Design: Difficulty/dual_variant_calc/hygiene_score_two_factor_vs_no_two_factor
    """
    household, profile = _four_finding_profile()

    data = validate_success(api.get_hygiene_score(profile["id"], household["owner"]))

    assert data["open_finding_count"] == 4
    # raw = 25 + 18 + 12 + 7 = 62; cap min(62, 70) = 62; multiplier 1.00.
    assert data["raw_penalty"] == 62
    assert data["capped_penalty"] == 62
    assert float(data["adjusted_penalty"]) == 62.00
    # 100 - 62.00 = 38.00, which is below 40 and therefore CRITICAL.
    assert float(data["hygiene_score"]) == 38.00
    assert data["hygiene_band"] == "CRITICAL"
    assert data["variant"] == "NO_TWO_FACTOR"


def test_hygiene_score_two_factor_variant_scales_the_capped_penalty(api):
    """PRD §3.7: "The **adjusted penalty** is the capped penalty multiplied by that
    multiplier, rounded half-up to 2 decimal places."
    PRD §3.3: "toggling the attestation re-derives `hygiene_score` and `hygiene_band`
    immediately under the newly selected variant, and the edit bumps the profile's `version`."

    Design: Difficulty/dual_variant_calc/hygiene_score_two_factor_vs_no_two_factor
    """
    household, profile = _four_finding_profile()

    validate_success(api.patch_monitored_profile(profile["id"],
                                                 {"two_factor_attested": True},
                                                 household["owner"]))
    data = validate_success(api.get_hygiene_score(profile["id"], household["owner"]))

    assert data["raw_penalty"] == 62
    assert data["capped_penalty"] == 62
    # 62 * 0.60 = 37.20 exactly.
    assert float(data["adjusted_penalty"]) == 37.20
    # 100 - 37.20 = 62.80, at or above 60 and therefore MODERATE — two bands above
    # the CRITICAL the identical finding set scores without the attestation.
    assert float(data["hygiene_score"]) == 62.80
    assert data["hygiene_band"] == "MODERATE"
    assert data["variant"] == "TWO_FACTOR_ATTESTED"

    row = validate_success(api.get_monitored_profile(profile["id"], household["owner"]))
    assert float(row["hygiene_score"]) == 62.80
    assert row["hygiene_band"] == "MODERATE"


# ==========================================================================
# Plan proration: the rounding order forks between upgrade and downgrade
# ==========================================================================

def _solo_account_ten_days_in():
    """A SOLO (1200) account opened at the startup instant, a FAMILY (2200) plan
    to move to, and the clock at 2026-05-11 so 20 whole days remain in the cycle."""
    solo = fx.create_solo_plan()
    family = fx.create_family_plan()
    household = fx.open_household(plan=solo)
    fx.set_clock("2026-05-11T00:00:00Z")
    return household, solo, family


def test_plan_upgrade_rounds_the_daily_rate_before_multiplying(api):
    """PRD §3.9: "Under the **`UPGRADE`** variant, in force when `change_kind` is
    `UPGRADE` and the new fee is strictly greater than the old, the server first divides
    the fee delta by 30 and rounds half-up to a whole cent to get a daily rate, and *then*
    multiplies that rounded rate by the remaining days."

    Design: Difficulty/combinatorial_formula/plan_proration_rounding_order_upgrade_vs_downgrade
    """
    household, solo, family = _solo_account_ten_days_in()

    data = validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": family["id"], "change_kind": "UPGRADE",
         "expected_account_version": fx.account_version(household)},
        household["owner"]))

    assert data["plan_id"] == family["id"]
    cycle = fx.first_cycle(household)
    # remaining_days: cycle ends 2026-05-31, now 2026-05-11 -> 20 whole days.
    # fee delta = 2200 - 1200 = 1000; daily rate = round_half_up(1000/30) = 33;
    # charge = 33 * 20 = 660.
    assert cycle["proration_charge_cents"] == 660
    assert cycle["base_charge_cents"] == 1200


def test_plan_downgrade_rounds_once_after_multiplying(api):
    """PRD §3.9: "Under the **`DOWNGRADE`** variant, in force when `change_kind` is
    `DOWNGRADE` and the new fee is strictly less than the old, the server multiplies the
    fee delta by the remaining days *first*, divides by 30, and rounds half-up exactly
    once at the end."

    Design: Difficulty/combinatorial_formula/plan_proration_rounding_order_upgrade_vs_downgrade
    """
    household, solo, family = _solo_account_ten_days_in()
    validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": family["id"], "change_kind": "UPGRADE",
         "expected_account_version": fx.account_version(household)},
        household["owner"]))

    data = validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": solo["id"], "change_kind": "DOWNGRADE",
         "expected_account_version": fx.account_version(household)},
        household["owner"]))

    assert data["plan_id"] == solo["id"]
    cycle = fx.first_cycle(household)
    # Identical inputs to the upgrade leg: fee delta 1000 over 20 remaining days.
    # credit = round_half_up(1000 * 20 / 30) = round_half_up(666.66..) = 667,
    # exactly 7 cents more than the 660 the round-then-multiply order produced.
    assert cycle["proration_credit_cents"] == 667
    assert cycle["proration_charge_cents"] == 660
    assert cycle["proration_credit_cents"] - cycle["proration_charge_cents"] == 7


# ==========================================================================
# The loyalty tier is chosen from the pre-discount total, once
# ==========================================================================

def _solo_account_with_vpn_addon(seats_total, per_seat_fee_cents):
    solo = fx.create_solo_plan()
    household = fx.open_household(plan=solo)
    fx.set_clock("2026-05-11T00:00:00Z")
    addon = fx.buy_addon(household, addon_type="VPN", seats_total=seats_total,
                         per_seat_fee_cents=per_seat_fee_cents)
    return household, addon


def test_addon_purchase_stamps_its_ceiled_prorated_charge_on_the_cycle(api):
    """PRD §3.8: "Under the **`SEAT_ADDED`** variant — used when the add-on is created —
    the charge is the product of `per_seat_fee_cents`, `seats_total` and that inclusive
    day count, divided by 30 and rounded **up** to the next whole cent; the figure is
    stamped on the add-on as `prorated_charge_cents` and added to the open cycle's
    `addon_charge_cents`."

    Design: Difficulty/combinatorial_formula/cycle_total_discount_tier_pinned_to_pre_discount_total
    """
    household, addon = _solo_account_with_vpn_addon(3, 152)

    # remaining days exclusive = floor((2026-05-31 - 2026-05-11)/86400) = 20; +1 = 21.
    # 152 * 3 * 21 = 9576; 9576 / 30 = 319.2; ceil -> 320.
    assert addon["prorated_charge_cents"] == 320
    cycle = fx.first_cycle(household)
    assert cycle["addon_charge_cents"] == 320


def test_loyalty_tier_is_never_reselected_from_the_post_discount_total(api):
    """PRD §3.9: "Second, a loyalty rate is selected **from that pre-discount figure**:
    8 per cent when it is at least 5000 cents, otherwise 5 per cent when it is at least
    3000 cents, otherwise 2 per cent when it is at least 1500 cents, and otherwise nothing
    at all."
    PRD §3.9: "The tier is chosen once, from the pre-discount total, and is **never**
    re-chosen from the post-discount total even when the discount pushes the total back
    under the threshold that selected it."

    Design: Difficulty/combinatorial_formula/cycle_total_discount_tier_pinned_to_pre_discount_total
    """
    household, addon = _solo_account_with_vpn_addon(3, 152)

    cycle = fx.first_cycle(household)

    # pre-discount = 1200 base + 320 add-on charge = 1520, which is at or above the
    # 1500 tier-1 threshold, so the rate is 2 per cent.
    assert cycle["pre_discount_total_cents"] == 1520
    # round_half_up(1520 * 0.02) = round_half_up(30.4) = 30.
    assert cycle["loyalty_discount_cents"] == 30
    # 1520 - 30 = 1490, which is below 1500: a re-selecting implementation would
    # report a discount of 0 and a total of 1520 here.
    assert cycle["total_charged_cents"] == 1490
    assert cycle["total_charged_cents"] < 1500
    assert_cycle_money_arithmetic(cycle)
