"""Delinquency remedies: the two payoff bases, the two independent member
dimensions, the aggregate restriction-day ceiling, and the precedence between
the safety check and the restriction minimum."""
from test_helpers import (
    ApiErrorId,
    create_delinquency_action_payload,
    make_clerk_headers,
    make_member_owner_headers,
    make_treasurer_headers,
    payment_payload,
    read_action,
    read_charge,
    read_member,
    read_segment,
    record_access_inspection,
    release_payload,
    set_clock,
    setup_annual_assessment,
    validate_error,
    validate_success,
)

SEGMENT_2400 = {
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}
COMPLIANT_MEASUREMENTS = {
    "measured_width_feet": 22,
    "measured_max_grade_pct": 9,
    "measured_turnout_count": 2,
    "turnaround_present": True,
}
SINGLE_PARCEL = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]

FIRST_TREASURER = make_treasurer_headers("bt-user-1")
SECOND_TREASURER = make_treasurer_headers("bt-user-2")


def _single_4m(inspect_compliant=True, association_overrides=None, deed_book_page="DB120-P41"):
    """One association, one segment, one 290-ft parcel, one verified member and
    an FY2027 roll for 4000000 whose lone charge clamps to the 1600000 cap."""
    set_clock("2026-10-01T00:00:00Z")
    overrides = {
        "name": "Pine Hollow Road Association",
        "reserve_target_cents": 1_000_000,
        "default_voting_basis": "PER_PARCEL",
        "delinquency_interest_basis": "STATUTORY",
        "quorum_bps": 5000,
    }
    overrides.update(association_overrides or {})
    scenario = setup_annual_assessment(
        parcel_specs=[dict(SINGLE_PARCEL[0], deed_book_page=deed_book_page)],
        fiscal_year=2027,
        fy_start_date="2026-10-01",
        fy_end_date="2027-09-30",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides=overrides,
        segment_overrides=dict(SEGMENT_2400, name="Pine Hollow Road"),
    )
    if inspect_compliant:
        record_access_inspection(
            scenario["segment"]["id"], "2026-10-01T00:00:00Z", **COMPLIANT_MEASUREMENTS
        )
    scenario["charge"] = scenario["charges"][0]
    scenario["member"] = scenario["members"][0]
    return scenario


def _initiate(api, charge_id, action_type, **payload_extras):
    payload = create_delinquency_action_payload(action_type, **payload_extras)
    return validate_success(
        api.create_delinquency_action(charge_id, payload, FIRST_TREASURER), 201
    )


class TestLienPayoffBases:
    """Identical arrears, identical clock, two association policies."""

    def _lien_scenario(self, api, basis, association_name, deed):
        set_clock("2026-10-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[
                {
                    "deed_book_page": deed,
                    "frontage_feet": 290,
                    "usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "trips_per_day": 6,
                }
            ],
            fiscal_year=2027,
            fy_start_date="2026-10-01",
            fy_end_date="2027-09-30",
            budget_requirement_cents=3_972_604,
            method_variant="FRONTAGE_WEIGHTED",
            association_overrides={
                "name": association_name,
                "reserve_target_cents": 1_000_000,
                "default_voting_basis": "PER_PARCEL",
                "delinquency_interest_basis": basis,
                "quorum_bps": 5000,
            },
            segment_overrides=dict(SEGMENT_2400, name=association_name.split(" Road")[0]),
        )
        charge = scenario["charges"][0]
        set_clock("2026-12-15T00:00:00Z")
        action = _initiate(api, charge["id"], "LIEN_FILING")
        scenario["charge"] = charge
        scenario["action"] = action
        scenario["member"] = scenario["members"][0]
        return scenario

    def test_statutory_payoff_prorates_simple_interest_over_exact_days(self, api):
        """PRD §3.6: "Under `STATUTORY`, the payoff is the principal plus simple
        interest at a twelve-percent annual rate prorated by exact days over three
        hundred and sixty-five: multiply the principal by twelve hundredths,
        multiply by the days delinquent, divide by three hundred and sixty-five,
        round that interest half up to whole cents, and add it to the principal.
        Filing costs are never added on this branch."
        PRD §3.6: "Its principal is the charge's `balance_cents` frozen at that
        instant, and the days delinquent are the whole days from the charge's
        `due_date` to the current clock date."

        Design: Difficulty/dual_variant_calc/lien_payoff_statutory_vs_association_policy_divergence
        """
        scenario = self._lien_scenario(
            api, "STATUTORY", "Statutory Ridge Road Association", "DB200-P11"
        )
        assert scenario["charge"]["amount_cents"] == 1_589_041
        assert scenario["roll"]["unallocated_residual_cents"] == 2_383_563

        effective = validate_success(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER)
        )

        assert effective["status"] == "EFFECTIVE"
        assert effective["lien_amount_cents"] == 1_589_041
        assert effective["payoff_amount_cents"] == 1_604_714
        assert effective["payoff_amount_cents"] - effective["lien_amount_cents"] == 15_673, (
            "the statutory branch never adds the 12500-cent filing cost"
        )

    def test_association_policy_payoff_compounds_whole_thirty_day_months(self, api):
        """PRD §3.6: "Under `ASSOCIATION_POLICY`, the twelve-thousand-five-hundred-cent
        lien filing cost is added to the principal first, and the sum is then
        compounded by whole thirty-day months at one and a quarter percent per
        month: take the number of whole thirty-day months in the days delinquent,
        discarding any partial month, raise one plus one and a quarter hundredths
        to that power, multiply the principal-plus-filing-cost by the result, and
        round half up to whole cents once at the end."

        Design: Difficulty/dual_variant_calc/lien_payoff_statutory_vs_association_policy_divergence
        """
        scenario = self._lien_scenario(
            api, "ASSOCIATION_POLICY", "Bluff Lane Road Association", "DB300-P11"
        )
        assert scenario["charge"]["amount_cents"] == 1_589_041

        effective = validate_success(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER)
        )

        assert effective["status"] == "EFFECTIVE"
        assert effective["lien_amount_cents"] == 1_589_041
        assert effective["payoff_amount_cents"] == 1_621_560

    def test_the_basis_is_the_only_thing_that_moves_the_quote(self, api):
        """PRD §3.6: "Which branch applies is a property of the association, chosen
        by its `delinquency_interest_basis`."
        PRD §3.6: "Because the filing cost is inside the base and the growth steps
        rather than accrues, this branch quotes a higher payoff than the statutory
        one for the same arrears."

        Design: Difficulty/dual_variant_calc/lien_payoff_statutory_vs_association_policy_divergence
        """
        statutory = self._lien_scenario(
            api, "STATUTORY", "Statutory Ridge Road Association", "DB200-P11"
        )
        policy = self._lien_scenario(
            api, "ASSOCIATION_POLICY", "Bluff Lane Road Association", "DB300-P11"
        )

        a = validate_success(
            api.effectuate_delinquency_action(statutory["action"]["id"], SECOND_TREASURER)
        )
        b = validate_success(
            api.effectuate_delinquency_action(policy["action"]["id"], SECOND_TREASURER)
        )

        assert a["lien_amount_cents"] == b["lien_amount_cents"] == 1_589_041
        assert b["payoff_amount_cents"] - a["payoff_amount_cents"] == 16_846

        for scenario in (statutory, policy):
            member = read_member(scenario["member"]["id"])
            assert member["standing_status"] == "LIEN_FILED"
            assert member["encumbered_principal_cents"] == 1_589_041
            assert member["access_status"] == "UNRESTRICTED", (
                "a lien with no gate closed leaves access untouched"
            )


class TestMemberDimensionsMoveIndependently:
    """Fiscal standing and access standing are separate projections."""

    def test_effectuating_a_notice_warns_access_and_leaves_standing_alone(self, api):
        """PRD §3.6: "while for a `NOTICE` the member's `access_status` moves to
        `WARNED` and `standing_status` is left entirely alone."
        PRD §3.6: "As a side effect of the first action against a charge, the
        charge moves `OPEN → DELINQUENT` and `delinquent_since` is stamped with the
        current clock date, and the member's `standing_status` is reconciled to
        `DELINQUENT`."

        Design: Difficulty/non_linear_state_machine/member_standing_and_access_dimensions_advance_independently
        """
        scenario = _single_4m()
        set_clock("2026-12-15T00:00:00Z")

        notice = _initiate(api, scenario["charge"]["id"], "NOTICE")
        after_initiation = read_member(scenario["member"]["id"])
        assert after_initiation["standing_status"] == "DELINQUENT"
        assert after_initiation["access_status"] == "UNRESTRICTED"
        charge = read_charge(scenario["charge"]["id"])
        assert charge["status"] == "DELINQUENT"
        assert charge["delinquent_since"] == "2026-12-15"

        effective = validate_success(
            api.effectuate_delinquency_action(notice["id"], SECOND_TREASURER)
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["lien_amount_cents"] == 0

        member = read_member(scenario["member"]["id"])
        assert member["standing_status"] == "DELINQUENT", "a notice never encumbers"
        assert member["access_status"] == "WARNED"
        assert read_charge(scenario["charge"]["id"])["status"] == "DELINQUENT"

    def test_effectuating_a_lien_moves_standing_and_leaves_access_warned(self, api):
        """PRD §2.8: "Because a member row carries both dimensions independently,
        combinations that look contradictory are legitimate: a member may be
        `LIEN_FILED` and `UNRESTRICTED` at once when a lien was filed but no gate
        was closed, and `GOOD_STANDING` and `WARNED` at once when a notice was
        served and the charge was subsequently paid."
        PRD §2.8: "The companion counter `restricted_days_used` is the sum of
        `restriction_days` over that member's `ACCESS_RESTRICTION` actions whose
        `status` is `EFFECTIVE` or `RELEASED`"

        Design: Difficulty/non_linear_state_machine/member_standing_and_access_dimensions_advance_independently
        """
        scenario = _single_4m()
        set_clock("2026-12-15T00:00:00Z")
        notice = _initiate(api, scenario["charge"]["id"], "NOTICE")
        validate_success(api.effectuate_delinquency_action(notice["id"], SECOND_TREASURER))

        lien = _initiate(api, scenario["charge"]["id"], "LIEN_FILING")
        effective = validate_success(
            api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER)
        )

        assert effective["lien_amount_cents"] == 1_600_000
        assert effective["payoff_amount_cents"] == 1_615_781

        member = read_member(scenario["member"]["id"])
        assert member["standing_status"] == "LIEN_FILED"
        assert member["access_status"] == "WARNED", (
            "a lien filing is not an access escalation"
        )
        assert member["restricted_days_used"] == 0
        assert member["encumbered_principal_cents"] == 1_600_000

        assert read_charge(scenario["charge"]["id"])["status"] == "LIEN_ENCUMBERED"
        assert read_action(notice["id"])["status"] == "EFFECTIVE"
        assert read_action(notice["id"])["lien_amount_cents"] == 0

    def test_paying_in_full_releases_both_remedies_and_restores_the_member(self, api):
        """PRD §3.6: "Because the charge reached `PAID`, every delinquency action on
        that charge whose `status` is `EFFECTIVE` moves `EFFECTIVE → RELEASED` with
        `released_at` stamped and its `lien_amount_cents` reset to zero; because
        those actions closed, the member's `standing_status` and `access_status` are
        re-reconciled and `encumbered_principal_cents` falls by the released lien
        principal."
        PRD §3.6: "`restricted_days_used` is not decremented by any of this."

        Design: Difficulty/non_linear_state_machine/member_standing_and_access_dimensions_advance_independently
        """
        scenario = _single_4m()
        set_clock("2026-12-15T00:00:00Z")
        notice = _initiate(api, scenario["charge"]["id"], "NOTICE")
        validate_success(api.effectuate_delinquency_action(notice["id"], SECOND_TREASURER))
        lien = _initiate(api, scenario["charge"]["id"], "LIEN_FILING")
        validate_success(api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER))

        paid = validate_success(
            api.create_payment(
                scenario["charge"]["id"],
                payment_payload(1_600_000),
                make_member_owner_headers(scenario["member"]["id"]),
            )
        )
        assert paid["status"] == "PAID"
        assert paid["balance_cents"] == 0

        assert read_action(notice["id"])["status"] == "RELEASED"
        assert read_action(lien["id"])["status"] == "RELEASED"

        member = read_member(scenario["member"]["id"])
        assert member["standing_status"] == "GOOD_STANDING"
        assert member["access_status"] == "UNRESTRICTED"
        assert member["encumbered_principal_cents"] == 0
        assert member["restricted_days_used"] == 0


class TestAggregateRestrictionDayCeiling:
    """Forty-five days per fiscal year, inclusive, and never refunded."""

    def _three_restrictions(self, api):
        scenario = _single_4m()
        set_clock("2026-12-15T00:00:00Z")
        scenario["r1"] = _initiate(
            api,
            scenario["charge"]["id"],
            "ACCESS_RESTRICTION",
            restriction_start_date="2026-12-16",
            restriction_end_date="2027-01-15",
        )
        scenario["r2"] = _initiate(
            api,
            scenario["charge"]["id"],
            "ACCESS_RESTRICTION",
            restriction_start_date="2027-01-15",
            restriction_end_date="2027-01-30",
        )
        scenario["r3"] = _initiate(
            api,
            scenario["charge"]["id"],
            "ACCESS_RESTRICTION",
            restriction_start_date="2027-01-30",
            restriction_end_date="2027-01-31",
        )
        return scenario

    def test_restriction_days_come_from_the_half_open_interval(self, api):
        """PRD §3.6: "Those two dates form a half-open interval — the start day is
        restricted, the end day is not — the start must fall strictly before the
        end, and the whole interval must lie inside the fiscal interval of the
        charge's roll"
        PRD §3.6: "The remedy's `restriction_days` is the whole number of days from
        the start date to the end date on that half-open reading, and it is zero for
        the other two action types."

        Design: Difficulty/resource_temporal_overlap/aggregate_restriction_days_ceiling_holds_across_the_fiscal_year_and_survives_release
        """
        scenario = self._three_restrictions(api)

        assert scenario["r1"]["restriction_days"] == 30
        assert scenario["r2"]["restriction_days"] == 15
        assert scenario["r3"]["restriction_days"] == 1
        for key in ("r1", "r2", "r3"):
            assert scenario[key]["status"] == "INITIATED"
            assert scenario[key]["lien_amount_cents"] == 0
        assert read_member(scenario["member"]["id"])["restricted_days_used"] == 0, (
            "initiation alone consumes no days"
        )

    def test_the_ceiling_is_inclusive_at_forty_five_and_refuses_one_more_day(self, api):
        """PRD §3.6: "the member's `restricted_days_used` plus this remedy's
        `restriction_days` must be no more than forty-five days for the fiscal year,
        an inclusive ceiling (otherwise `ERR_RESTRICTION_DAYS_EXCEEDED`)"
        PRD §3.6: "Two back-to-back restrictions that merely touch at a single date
        are each legal on their own and can still breach the aggregate ceiling."

        Design: Difficulty/resource_temporal_overlap/aggregate_restriction_days_ceiling_holds_across_the_fiscal_year_and_survives_release
        """
        scenario = self._three_restrictions(api)

        first = validate_success(
            api.effectuate_delinquency_action(scenario["r1"]["id"], SECOND_TREASURER)
        )
        assert first["status"] == "EFFECTIVE"
        assert first["lien_amount_cents"] == 1_600_000
        assert first["payoff_amount_cents"] == 1_615_781
        assert read_member(scenario["member"]["id"])["restricted_days_used"] == 30

        second = validate_success(
            api.effectuate_delinquency_action(scenario["r2"]["id"], SECOND_TREASURER)
        )
        assert second["status"] == "EFFECTIVE"
        member = read_member(scenario["member"]["id"])
        assert member["restricted_days_used"] == 45, "30 + 15 == 45 is allowed"
        assert member["access_status"] == "RESTRICTED"
        assert member["standing_status"] == "LIEN_FILED"
        assert read_charge(scenario["charge"]["id"])["status"] == "LIEN_ENCUMBERED"

        validate_error(
            api.effectuate_delinquency_action(scenario["r3"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_RESTRICTION_DAYS_EXCEEDED.value,
        )
        refused = read_action(scenario["r3"]["id"])
        assert refused["status"] == "INITIATED"
        assert refused["lien_amount_cents"] == 0

    def test_encumbered_principal_sums_the_effective_lien_amounts(self, api):
        """PRD §2.8: "In the same reconciliation, `encumbered_principal_cents` is
        set to the sum of `lien_amount_cents` over every delinquency action of that
        member whose `status` is `EFFECTIVE`."

        Design: Difficulty/resource_temporal_overlap/aggregate_restriction_days_ceiling_holds_across_the_fiscal_year_and_survives_release
        """
        scenario = self._three_restrictions(api)
        validate_success(
            api.effectuate_delinquency_action(scenario["r1"]["id"], SECOND_TREASURER)
        )
        validate_success(
            api.effectuate_delinquency_action(scenario["r2"]["id"], SECOND_TREASURER)
        )

        member = read_member(scenario["member"]["id"])
        assert member["encumbered_principal_cents"] == 3_200_000, (
            "two effective liens of 1600000 each, not the charge balance"
        )

    def test_releasing_a_restriction_does_not_hand_the_days_back(self, api):
        """PRD §2.8: "The counter is monotone. Releasing a restriction does not give
        the days back; consumed restriction days stay consumed for the fiscal year."
        PRD §3.6: "From `EFFECTIVE`, the remedy moves `EFFECTIVE → RELEASED`:
        `released_at` is stamped, `lien_amount_cents` resets to zero, and
        `payoff_amount_cents` is retained as the historical quote"

        Design: Difficulty/resource_temporal_overlap/aggregate_restriction_days_ceiling_holds_across_the_fiscal_year_and_survives_release
        """
        scenario = self._three_restrictions(api)
        validate_success(
            api.effectuate_delinquency_action(scenario["r1"]["id"], SECOND_TREASURER)
        )
        validate_success(
            api.effectuate_delinquency_action(scenario["r2"]["id"], SECOND_TREASURER)
        )
        validate_error(
            api.effectuate_delinquency_action(scenario["r3"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_RESTRICTION_DAYS_EXCEEDED.value,
        )

        released = validate_success(
            api.release_delinquency_action(
                scenario["r2"]["id"],
                release_payload("owner produced a payment plan"),
                SECOND_TREASURER,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["lien_amount_cents"] == 0

        member = read_member(scenario["member"]["id"])
        assert member["encumbered_principal_cents"] == 1_600_000
        assert member["restricted_days_used"] == 45, "released days keep counting"
        assert read_charge(scenario["charge"]["id"])["status"] == "LIEN_ENCUMBERED", (
            "R1 is still effective, so the charge stays encumbered"
        )

        validate_error(
            api.effectuate_delinquency_action(scenario["r3"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_RESTRICTION_DAYS_EXCEEDED.value,
        )
        assert read_member(scenario["member"]["id"])["access_status"] == "RESTRICTED"


class TestSafetyErrorOutranksBalanceMinimum:
    """Two effectuation rules fire at once; the earlier one must be reported."""

    def _both_violations(self, api):
        scenario = _single_4m()
        set_clock("2026-12-15T00:00:00Z")
        action = _initiate(
            api,
            scenario["charge"]["id"],
            "ACCESS_RESTRICTION",
            restriction_start_date="2027-01-05",
            restriction_end_date="2027-01-10",
        )
        validate_success(
            api.create_payment(
                scenario["charge"]["id"], payment_payload(1_560_000), make_clerk_headers()
            )
        )
        deficient = record_access_inspection(
            scenario["segment"]["id"],
            "2026-12-15T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=14,
            measured_turnout_count=2,
            turnaround_present=True,
        )
        assert deficient["emergency_access_grade"] == "DEFICIENT"
        scenario["action"] = action
        return scenario

    def test_the_safety_check_masks_the_restriction_minimum(self, api):
        """PRD §2.10: "More generally, every request walks the following checks in
        this exact order, and the first failure is the error returned. Where several
        checks could all fire, the earlier one masks the later ones."
        PRD §2.10 item 28: "The emergency-vehicle access standard, at the
        strictnesses given in §2.7 — otherwise `ERR_EMERGENCY_ACCESS_DEFICIENT`
        (409), on project award, remedy effectuation, and connection decision."

        Design: Difficulty/priority_pair_validation_conflict/access_safety_error_outranks_restriction_balance_minimum_error
        """
        scenario = self._both_violations(api)
        action = read_action(scenario["action"]["id"])
        assert action["action_type"] == "ACCESS_RESTRICTION"
        assert action["restriction_days"] == 5
        assert action["status"] == "INITIATED"
        charge = read_charge(scenario["charge"]["id"])
        assert charge["balance_cents"] == 40_000
        assert charge["status"] == "DELINQUENT"

        validate_error(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_EMERGENCY_ACCESS_DEFICIENT.value,
        )

    def test_clearing_the_grade_surfaces_the_restriction_minimum(self, api):
        """PRD §2.10 item 54: "The charge's `balance_cents` is at least fifty
        thousand cents before an `ACCESS_RESTRICTION` takes effect — otherwise
        `ERR_BALANCE_BELOW_RESTRICTION_MINIMUM` (409)."
        PRD §3.6: "the charge's `balance_cents` must be at least fifty thousand
        cents, so the association may not gate a road over a trivial arrears
        (otherwise `ERR_BALANCE_BELOW_RESTRICTION_MINIMUM`)"

        Design: Difficulty/priority_pair_validation_conflict/access_safety_error_outranks_restriction_balance_minimum_error
        """
        scenario = self._both_violations(api)
        validate_error(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_EMERGENCY_ACCESS_DEFICIENT.value,
        )

        regraded = record_access_inspection(
            scenario["segment"]["id"],
            "2026-12-16T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=11,
            measured_turnout_count=2,
            turnaround_present=True,
        )
        assert regraded["emergency_access_grade"] == "COMPLIANT"

        validate_error(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_BALANCE_BELOW_RESTRICTION_MINIMUM.value,
        )

    def test_neither_rejection_touches_the_action_the_charge_or_the_member(self, api):
        """PRD §3.6: "Effectuation is the second treasurer's act, and it is the
        point at which the remedy bites."
        PRD §3.6: "First, the remedy moves `INITIATED → EFFECTIVE`, with
        `effective_at` and `effectuated_by_user_id` stamped; for a `LIEN_FILING` or
        an `ACCESS_RESTRICTION`, `lien_amount_cents` is frozen at the charge's
        `balance_cents` and `payoff_amount_cents` is set to the quoted payoff."

        Design: Difficulty/priority_pair_validation_conflict/access_safety_error_outranks_restriction_balance_minimum_error
        """
        scenario = self._both_violations(api)
        validate_error(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_EMERGENCY_ACCESS_DEFICIENT.value,
        )
        record_access_inspection(
            scenario["segment"]["id"],
            "2026-12-16T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=11,
            measured_turnout_count=2,
            turnaround_present=True,
        )
        validate_error(
            api.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER),
            ApiErrorId.ERR_BALANCE_BELOW_RESTRICTION_MINIMUM.value,
        )

        action = read_action(scenario["action"]["id"])
        assert action["status"] == "INITIATED"
        assert action["lien_amount_cents"] == 0
        assert action["effectuated_by_user_id"] is None

        member = read_member(scenario["member"]["id"])
        assert member["access_status"] == "UNRESTRICTED"
        assert member["restricted_days_used"] == 0
        assert member["standing_status"] == "DELINQUENT"

        charge = read_charge(scenario["charge"]["id"])
        assert charge["status"] == "DELINQUENT"
        assert charge["balance_cents"] == 40_000
        assert read_segment(scenario["segment"]["id"])["emergency_access_grade"] == "COMPLIANT"
