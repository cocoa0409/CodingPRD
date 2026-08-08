"""Fee assessment at issuance, and the guards that stand in front of it."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    ApiErrorId,
    advance_permit_to_under_review,
    apply_for_permit,
    assert_posture,
    clear_open_finding,
    fee_balance,
    pay_operator_balance,
    post_drain_certification,
    read_facility,
    read_permit,
    set_clock,
    setup_facility_with_permit_under_review,
    setup_finalized_inspection,
    setup_operator_and_pool,
    submit_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_annual_fee_sums_base_volume_and_feature_surcharges_in_full(api):
    """PRD 3.3: For an `ANNUAL` permit, `fee_variant` is `FULL_TERM` and the
    subtotal is simply the base plus the volume surcharge plus the feature
    surcharges, all charged in full for the 365-day term.
    PRD 3.3: Step three sums the feature surcharges over the facility's
    `features` — 5000 cents for `SLIDE`, 7500 for `DIVING_BOARD`, 12000 for
    `WAVE_GENERATOR`, 4000 for `SPA_JETS` and 3000 for `SPLASH_PAD` — and these
    are never prorated.
    PRD 3.3: Step one takes the base fee from the facility's class **as it stands
    at the instant of issuance** — 45000 cents for `CLASS_A_COMPETITION`, 30000
    cents for `CLASS_B_PUBLIC`, 18000 cents for `CLASS_C_SEMI_PUBLIC` and 12000
    cents for `SPA` — and simultaneously snapshots that class into
    `classification_at_issue`, pinning the tier against any later
    reclassification.

    Design: Corner/calculations/annual_permit_fee_full_term_with_feature_surcharges
    """
    ctx = setup_facility_with_permit_under_review(
        operator_overrides={
            "legal_name": "Metro Aquatics",
            "contact_email": "metro@aquatics.example",
        },
        name="Metro Competition Pool",
        facility_class="CLASS_A_COMPETITION",
        surface_area_sqft=2000,
        water_volume_gallons=100000,
        max_depth_feet=13,
        drain_count=4,
        features=["SLIDE", "DIVING_BOARD"],
    )

    issued = validate_success(
        api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN)
    )

    assert issued["assessed_fee_cents"] == 77500
    assert issued["fee_variant"] == "FULL_TERM"
    assert issued["classification_at_issue"] == "CLASS_A_COMPETITION"

    facility = read_facility(ctx["facility_id"])
    assert facility["max_bather_load"] == 100
    assert facility["lifeguard_required"] is True
    assert fee_balance(ctx["operator_id"]) == 77500


def test_volume_surcharge_is_zero_at_exactly_the_free_allowance(api):
    """PRD 3.3: Step two computes the volume surcharge on the gallons above a
    free allowance: subtract 25000 gallons from the facility's
    `water_volume_gallons` and treat a negative result as zero, divide the
    remainder by 10000 and round that quotient **up** to a whole number of
    surcharge units, then multiply by 2500 cents per unit. A venue holding 25000
    gallons or fewer therefore pays no volume surcharge, while one holding 45001
    gallons pays for three units.
    PRD 3.1: `lifeguard_required` is true exactly when the class is either
    `CLASS_A_COMPETITION` or `CLASS_B_PUBLIC` **and** the computed
    `max_bather_load` is at least 50; semi-public pools and spas never require a
    lifeguard, regardless of size.

    Design: Corner/calculations/volume_surcharge_is_zero_at_exactly_the_free_allowance
    """
    ctx = setup_facility_with_permit_under_review(
        operator_overrides={
            "legal_name": "Court Yard Homes",
            "contact_email": "hoa@courtyard.example",
        },
        name="HOA Pool",
        facility_class="CLASS_C_SEMI_PUBLIC",
        surface_area_sqft=600,
        water_volume_gallons=25000,
        max_depth_feet=6,
    )

    issued = validate_success(
        api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN)
    )

    assert issued["assessed_fee_cents"] == 18000, (
        "One gallon more would have added a whole 2500-cent surcharge unit"
    )

    facility = read_facility(ctx["facility_id"])
    assert facility["max_bather_load"] == 30
    assert facility["lifeguard_required"] is False


def test_outstanding_fees_block_issuance_until_the_operator_pays(api):
    """PRD 3.3: and the operator's `fee_balance_cents` must be exactly 0 at that
    instant, or `ERR_OUTSTANDING_FEES` with HTTP 402.
    PRD 3.3: That last rule is the reason plan-review fees matter: an operator
    who has not settled the 25000-cent review charge cannot be issued the permit
    that review unlocked.

    Design: Corner/validations/outstanding_fees_block_permit_issuance
    """
    ctx = setup_operator_and_pool()
    submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], project_type="EQUIPMENT_REPLACEMENT",
        drawing_reference="DR-EQ-9",
    )
    permit = apply_for_permit(ctx["facility_id"], ctx["op_headers"])
    advance_permit_to_under_review(permit["id"], ctx["op_headers"])

    validate_error(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN),
        ApiErrorId.ERR_OUTSTANDING_FEES.value, 402,
    )
    assert read_permit(permit["id"])["status"] == "UNDER_REVIEW"

    pay_operator_balance(
        ctx["operator_id"], ctx["op_headers"], 25000, "Plan review fee"
    )
    assert fee_balance(ctx["operator_id"]) == 0

    issued = validate_success(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN)
    )
    assert issued["status"] == "ISSUED"
    assert issued["assessed_fee_cents"] == 40000
    assert fee_balance(ctx["operator_id"]) == 40000


def test_drain_safety_gate_blocks_issuance_on_and_after_the_enforcement_date(api):
    """PRD 3.8: Enforcement of drain safety has a start date, and that date is
    `2026-06-01`.
    PRD 3.8: Until the logical-clock date reaches 1 June 2026 a non-compliant
    venue is neither restricted nor blocked from permitting; from that date
    onward, a `vgb_compliance_status` other than `COMPLIANT` restricts the venue
    under clause 5 of the posture gate and blocks permit issuance with
    `ERR_VGB_NONCOMPLIANT`.
    PRD 3.8: Otherwise, if the venue has fewer than 2 submerged suction outlets
    and the governing certification's `sva_system_type` is `NONE` — a single
    unprotected drain, the exact configuration the federal rule was written to
    eliminate — the status is `NONCOMPLIANT`. In every other case it is
    `COMPLIANT`.

    Design: Corner/errors/vgb_noncompliance_blocks_issuance_after_the_enforcement_date
    """
    set_clock("2026-06-15T00:00:00Z")
    ctx = setup_facility_with_permit_under_review(
        operator_overrides={
            "legal_name": "Harbour Club",
            "contact_email": "club@harbour.example",
        },
        permit_overrides={"term_start_date": "2026-07-01"},
        name="Harbour Club Pool",
        water_volume_gallons=20000,
        max_depth_feet=9,
        drain_count=1,
    )

    validate_error(
        api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN),
        ApiErrorId.ERR_VGB_NONCOMPLIANT.value, 409,
    )
    assert (
        read_facility(ctx["facility_id"])["vgb_compliance_status"] == "NONCOMPLIANT"
    )

    post_drain_certification(
        ctx["facility_id"], ctx["op_headers"], sva_system_type="SVRS",
        effective_on="2026-06-15",
    )
    assert read_facility(ctx["facility_id"])["vgb_compliance_status"] == "COMPLIANT"

    issued = validate_success(
        api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN)
    )
    assert issued["status"] == "ISSUED"
    assert issued["assessed_fee_cents"] == 30000
    assert issued["is_late_application"] is False


def test_open_critical_finding_blocks_issuance_until_it_is_verified(api):
    """PRD 3.3: the facility must carry no violation whose own status is `OPEN`
    and whose severity is `CRITICAL` or `IMMINENT_HEALTH_HAZARD` on a `FINALIZED`
    inspection, or `ERR_OPEN_CRITICAL_VIOLATIONS`
    PRD 2.10: A facility's `open_demerit_points` is the sum of `points_assessed`
    over every violation whose own status is `OPEN` and whose parent inspection
    belongs to that facility and is currently in `FINALIZED`.

    Design: Corner/errors/open_critical_violation_blocks_permit_issuance
    """
    ctx = setup_operator_and_pool()
    _, violations = setup_finalized_inspection(
        ctx["facility_id"],
        findings=[
            {
                "code": "WQ-101",
                "severity": "CRITICAL",
                "description": "Free chlorine below minimum",
                "corrected_on_site": False,
            }
        ],
        inspection_type="PREOPERATIONAL",
    )
    permit = apply_for_permit(ctx["facility_id"], ctx["op_headers"])
    advance_permit_to_under_review(permit["id"], ctx["op_headers"])

    validate_error(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN),
        ApiErrorId.ERR_OPEN_CRITICAL_VIOLATIONS.value, 409,
    )
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 10

    clear_open_finding(violations[0]["id"], ctx["op_headers"], INSPECTOR)
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 0

    issued = validate_success(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN)
    )
    assert issued["status"] == "ISSUED"
    assert fee_balance(ctx["operator_id"]) == 40000


class TestSeasonalProrationRoundsPerComponent:
    """Proration is rounded per component and only then summed."""

    @staticmethod
    def _setup():
        return setup_facility_with_permit_under_review(
            operator_overrides={
                "legal_name": "Lakeside Recreation District",
                "contact_email": "permits@lakeside.example",
            },
            permit_overrides={
                "permit_type": "SEASONAL",
                "term_start_date": "2026-06-01",
            },
            name="Lakeside Seasonal Pool",
            is_seasonal=True,
            season_start_date="2026-06-01",
            season_end_date="2026-08-31",
        )

    def test_seasonal_term_is_taken_from_the_declared_season_window(self, api):
        """PRD 3.3: `term_end_date` is, for an annual permit, the day 364 days
        after `term_start_date`, giving a 365-day term counted inclusively; for a
        seasonal permit it is simply the facility's `season_end_date` as it
        stands at application time.
        PRD 3.3: `term_days` is the inclusive day count of the resulting term —
        the number of days from `term_start_date` to `term_end_date` counting
        both endpoints.
        PRD 3.3: For a `SEASONAL` permit, `fee_variant` is `SEASONAL_PRORATED`
        and a proration factor is formed by dividing the permit's `term_days` by
        365; the base is multiplied by that factor and rounded half up to whole
        cents, the volume surcharge is multiplied by the same factor and
        **separately** rounded half up to whole cents, and those two rounded
        components are then added to the un-prorated feature surcharges.

        Design: Difficulty/combinatorial_formula/seasonal_permit_fee_round_per_component_then_sum
        """
        ctx = self._setup()

        issued = validate_success(
            api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN)
        )

        assert issued["term_end_date"] == "2026-08-31"
        assert issued["term_days"] == 92
        assert issued["is_late_application"] is False
        assert issued["fee_variant"] == "SEASONAL_PRORATED"

    def test_prorated_components_are_rounded_before_they_are_summed(self, api):
        """PRD 3.3: Rounding each prorated component before summing is normative
        and is not interchangeable with rounding the sum: a 30000-cent base plus
        a 10000-cent volume surcharge over a 92-day season yields 7562 plus 2521,
        or 10083 cents, where rounding after summing would yield 10082.
        PRD 3.3: Issuance then writes `issued_at` from the logical clock and
        `issued_by_user_id` from the acting `X-User-ID`, posts a ledger entry of
        `entry_type` `PERMIT_FEE` against this permit for the positive subtotal

        Design: Difficulty/combinatorial_formula/seasonal_permit_fee_round_per_component_then_sum
        """
        ctx = self._setup()

        issued = validate_success(
            api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN)
        )

        assert issued["assessed_fee_cents"] == 10083, (
            "7562 + 2521 per component; rounding the sum would give 10082"
        )
        assert fee_balance(ctx["operator_id"]) == 10083

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "PERMIT_FEE"
        assert rows[0]["amount_cents"] == 10083
