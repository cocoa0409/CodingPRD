"""Tenancy lifecycle mechanics: proration variants, subsidy tiers, occupancy
boundaries, notice/rescission, and termination invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_tenancy,
    create_tenancy,
    get_tenancy,
    get_unit,
    setup_active_tenancy,
    setup_certified_site,
    setup_eligible_household,
    setup_pending_tenancy,
    setup_site_with_units,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestProrationVariants:
    """Difficulty instance: calendar_day vs weekly_slot divergence on an
    identical move-in date (2026-08-11)."""

    def _setup_two_tenancies(self, api):
        ctx = setup_site_with_units(site_name="Site P", unit_specs=[
            {"unit_code": "F1", "unit_type": "FAMILY_UNIT",
             "max_occupancy": 4, "monthly_rent_cents": 90000},
            {"unit_code": "D1", "unit_type": "SEASONAL_DORM",
             "max_occupancy": 8, "monthly_rent_cents": 62000},
        ])
        uf, ud = ctx["units"]
        hf = setup_eligible_household(
            name="Fam A", members=(("A One", "1980-01-01", "HEAD"),
                                   ("A Two", "1985-05-05", "SPOUSE")))["household"]
        hd = setup_eligible_household(
            name="Fam B", members=(("B One", "1979-03-03", "HEAD"),
                                   ("B Two", "1988-07-07", "SPOUSE")))["household"]
        tf = create_tenancy(hf["id"], uf["id"], move_in_date="2026-08-11")
        td = create_tenancy(hd["id"], ud["id"], move_in_date="2026-08-11")
        activate_tenancy(tf["id"])
        activate_tenancy(td["id"])
        return tf, td

    def test_family_unit_calendar_day_proration(self, api,
                                                intake_coordinator_headers):
        """PRD §3.4: "For a `FAMILY_UNIT`, the charge is the unit's full
        `monthly_rent_cents` times the days remaining in the move-in month —
        counted inclusively, from the `move_in_date` through the last day of
        that month — divided by the number of days in that calendar month,
        rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/proration_calendar_vs_weekly_slot_divergence
        """
        tf, _ = self._setup_two_tenancies(api)
        statement = validate_success(api.get_tenancy_statement(
            tf["id"], intake_coordinator_headers))
        # round_half_up(90000 * 21 / 31) = 60968; burden 90000/500000 = 0.18
        # earns no subsidy.
        assert statement["balance_cents"] == 60968
        assert statement["subsidy_tier_percent"] == 0

    def test_seasonal_dorm_weekly_slot_proration(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.4: "For a `SEASONAL_DORM`, the monthly rent is first
        converted to a weekly slot rate — twelve months per year over
        fifty-two weeks per year, rounded half up to whole cents — and the
        charge is that weekly rate times the number of weeks the remaining
        days span, computed as the days remaining divided by seven and rounded
        up to a whole number: a partially used week bills the whole slot."

        Design: Difficulty/dual_variant_calc/proration_calendar_vs_weekly_slot_divergence
        """
        _, td = self._setup_two_tenancies(api)
        statement = validate_success(api.get_tenancy_statement(
            td["id"], intake_coordinator_headers))
        # weekly rate: round_half_up(62000 * 12 / 52) = 14308; 21 remaining
        # days span ceil(21/7) = 3 weekly slots -> 42924.
        assert statement["balance_cents"] == 42924
        assert statement["balance_cents"] != 42000, (
            "The calendar-day counterfactual on identical dorm inputs; "
            "variant selection is pinned by unit_type")
        assert statement["subsidy_tier_percent"] == 0


class TestSubsidyTierEvaluationOrder:
    """Difficulty instance: the tier keys on GROSS rent (circular order
    pinned). Income 2400000 -> monthly 200000; ratio 90000/200000 = 0.45 ->
    tier 0.15."""

    def _setup(self, api):
        return setup_active_tenancy(
            site_name="Site S", household_name="Fam S", income_cents=2400000,
            members=(("S One", "1980-01-01", "HEAD"),
                     ("S Two", "2015-06-01", "CHILD")))

    def test_subsidy_tier_keyed_on_gross_rent(self, api,
                                              intake_coordinator_headers):
        """PRD §3.4: "Subsidy relief follows immediately, keyed on gross rent
        rather than net to break the apparent circle. ... Otherwise the
        rent-burden ratio is the unit's full `monthly_rent_cents` divided by
        monthly income: a ratio of at least 0.50 earns the 0.30 tier, a ratio
        of at least 0.30 earns the 0.15 tier, and anything below earns nothing
        — boundaries inclusive."

        Design: Difficulty/combinatorial_formula/subsidy_tier_circular_order_pinned
        """
        ctx = self._setup(api)
        statement = validate_success(api.get_tenancy_statement(
            ctx["tenancy"]["id"], intake_coordinator_headers))
        assert statement["subsidy_tier_percent"] == pytest.approx(0.15)
        # credit = round_half_up(0.15 * 60968) = 9145; 60968 - 9145 = 51823.
        assert statement["balance_cents"] == 51823
        assert statement["rent_bucket_balance_cents"] == 51823, (
            "The SUBSIDY_CREDIT posts into the rent bucket")

    def test_subsidy_credit_entry_posted_after_rent_and_minor_count(
            self, api, intake_coordinator_headers,
            operator_admin_headers):
        """PRD §3.4: "The credit is the tier times the prorated rent charge,
        rounded half up to whole cents, posted as a `SUBSIDY_CREDIT` entry
        after the `RENT` entry and skipped entirely when the tier is zero."
        PRD §3.3: "The system derives `is_minor` — true when the member is
        under eighteen years of age on the clock date"

        Design: Difficulty/combinatorial_formula/subsidy_tier_circular_order_pinned
        """
        ctx = self._setup(api)
        entries, _ = validate_paginated(api.list_charge_ledger_entries(
            operator_admin_headers,
            params={"tenancy_id": ctx["tenancy"]["id"]}))
        # PRD §3.4 posts RENT then SUBSIDY_CREDIT in the same activation; both
        # can share a millisecond created_at, and §2.3 specifies no tiebreak
        # for list ordering, so the relative list order of the pair is not
        # uniquely derivable. Assert the posted set and exact amounts instead.
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type == {"RENT": 60968, "SUBSIDY_CREDIT": 9145}, (
            "round_half_up(0.15 * 60968) = 9145")

        household = validate_success(api.get_household(
            ctx["household"]["id"], intake_coordinator_headers))
        assert household["minor_count"] == 1, (
            "The member born 2015-06-01 is 11 at the 2026-08-01 clock")


class TestSubsidyTierBoundaries:
    def test_subsidy_tier_boundary_030_inclusive(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.4: "a ratio of at least 0.50 earns the 0.30 tier, a ratio of
        at least 0.30 earns the 0.15 tier, and anything below earns nothing —
        boundaries inclusive."

        Design: Corner/calculations/subsidy_tier_boundary_030_inclusive
        """
        # Household A: 3600000/yr -> monthly 300000 -> ratio exactly 0.30.
        ctx_a = setup_active_tenancy(site_name="SA", household_name="Fam A30",
                                     income_cents=3600000)
        stmt_a = validate_success(api.get_tenancy_statement(
            ctx_a["tenancy"]["id"], intake_coordinator_headers))
        assert stmt_a["subsidy_tier_percent"] == pytest.approx(0.15)
        assert stmt_a["balance_cents"] == 51823

        # Household B: 3600100/yr -> monthly 300008 -> ratio 0.29999... below.
        ctx_b = setup_active_tenancy(site_name="SB", household_name="Fam B30",
                                     income_cents=3600100)
        stmt_b = validate_success(api.get_tenancy_statement(
            ctx_b["tenancy"]["id"], intake_coordinator_headers))
        assert stmt_b["subsidy_tier_percent"] == 0
        assert stmt_b["balance_cents"] == 60968

    def test_subsidy_tier_boundary_050_inclusive(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.4: "a ratio of at least 0.50 earns the 0.30 tier, a ratio of
        at least 0.30 earns the 0.15 tier, and anything below earns nothing —
        boundaries inclusive."

        Design: Corner/calculations/subsidy_tier_boundary_050_inclusive
        """
        # 2160000/yr -> monthly 180000 -> ratio exactly 0.50.
        ctx = setup_active_tenancy(site_name="S50", household_name="Fam 50",
                                   income_cents=2160000)
        stmt = validate_success(api.get_tenancy_statement(
            ctx["tenancy"]["id"], intake_coordinator_headers))
        assert stmt["subsidy_tier_percent"] == pytest.approx(0.30)
        # credit = round_half_up(0.30 * 60968) = 18290; 60968 - 18290 = 42678.
        assert stmt["balance_cents"] == 42678


class TestOccupancyBoundary:
    """Difficulty instance: projected == max_occupancy activates; +1 rejects
    with 422."""

    def _setup_two_households(self, api):
        ctx = setup_certified_site(site_name="Site OB")
        unit_id = ctx["unit"]["id"]
        h1 = setup_eligible_household(
            name="Fam Four",
            members=(("F1", "1980-01-01", "HEAD"),
                     ("F2", "1982-01-01", "SPOUSE"),
                     ("F3", "2010-01-01", "CHILD"),
                     ("F4", "2012-01-01", "CHILD")))["household"]
        h2 = setup_eligible_household(
            name="Fam One", members=(("O1", "1995-01-01", "HEAD"),))[
            "household"]
        return ctx, unit_id, h1, h2

    def test_occupancy_at_exact_capacity_allowed(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.4: "the projected occupancy — the unit's
        `current_occupancy`, defined as the sum of `member_count` across its
        `ACTIVE` and `NOTICE` tenancies, plus the incoming household's
        `member_count` — may equal the unit's `max_occupancy` but not exceed
        it"

        Design: Difficulty/boundary_precision_check/occupancy_boundary_exact_capacity
        """
        _, unit_id, h1, _ = self._setup_two_households(api)
        t1 = create_tenancy(h1["id"], unit_id)
        activated = activate_tenancy(t1["id"])
        assert activated["status"] == "ACTIVE", (
            "Projected 4 == max_occupancy 4 is the inclusive boundary")
        assert get_unit(unit_id)["current_occupancy"] == 4

    def test_occupancy_one_over_capacity_rejected(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "one person over the cap is rejected with
        `ERR_OCCUPANCY_LIMIT_EXCEEDED` (HTTP 422), counting all members
        regardless of `is_minor`."

        Design: Difficulty/boundary_precision_check/occupancy_boundary_exact_capacity
        """
        _, unit_id, h1, h2 = self._setup_two_households(api)
        t1 = create_tenancy(h1["id"], unit_id)
        activate_tenancy(t1["id"])
        assert get_unit(unit_id)["current_occupancy"] == 4, "Setup failed"

        t2 = create_tenancy(h2["id"], unit_id, move_in_date="2026-08-12")
        resp = api.update_tenancy(t2["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_LIMIT_EXCEEDED)


class TestOccupancyRoundtripInvariant:
    """Difficulty instance: activate -> terminate conserves headcount."""

    def _setup_three_member(self, api):
        return setup_pending_tenancy(
            site_name="Site OI", household_name="Fam OI",
            members=(("OI 1", "1980-01-01", "HEAD"),
                     ("OI 2", "1981-01-01", "SPOUSE"),
                     ("OI 3", "2011-01-01", "CHILD")))

    def test_activation_bumps_occupancy(self, api,
                                        intake_coordinator_headers):
        """PRD §3.4: "Activation posts money. The unit's `current_occupancy`
        grows by the household's `member_count`, and a `CERTIFIED` unit
        gaining its first `ACTIVE` tenancy becomes `OCCUPIED`."

        Design: Difficulty/compensating_invariant/occupancy_activate_terminate_roundtrip_invariant
        """
        ctx = self._setup_three_member(api)
        assert get_unit(ctx["unit"]["id"])["current_occupancy"] == 0

        activate_tenancy(ctx["tenancy"]["id"])
        unit = get_unit(ctx["unit"]["id"])
        assert unit["current_occupancy"] == 3
        assert unit["status"] == "OCCUPIED"

    def test_termination_releases_occupancy(self, api,
                                            intake_coordinator_headers):
        """PRD §3.4: "In both cases the date is recorded, the unit's
        `current_occupancy` drops by the household's `member_count`, an
        `OCCUPIED` unit whose occupancy thereby reaches zero returns to
        `CERTIFIED`, and the site posture recomputes."

        Design: Difficulty/compensating_invariant/occupancy_activate_terminate_roundtrip_invariant
        """
        ctx = self._setup_three_member(api)
        activate_tenancy(ctx["tenancy"]["id"])
        assert get_unit(ctx["unit"]["id"])["current_occupancy"] == 3, (
            "Setup failed")

        terminated = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"],
            {"status": "TERMINATED", "move_out_date": "2026-08-20"},
            intake_coordinator_headers))
        assert terminated["status"] == "TERMINATED"

        unit = get_unit(ctx["unit"]["id"])
        assert unit["current_occupancy"] == 0, (
            "The activate/terminate roundtrip conserves headcount")
        assert unit["status"] == "CERTIFIED"


class TestNoticeRescindAndInvalidTransitions:
    def test_tenancy_notice_rescind_revert(self, api,
                                           intake_coordinator_headers):
        """PRD §3.4: "An `IntakeCoordinator` moving an `ACTIVE` tenancy to
        `NOTICE` records an operator-initiated `notice_reason` of `OPERATOR`."
        PRD §3.4: "A successful rescission clears `notice_reason` back to
        null."

        Design: Corner/state_machines/tenancy_notice_rescind_revert
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam NR")
        notice = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "NOTICE"},
            intake_coordinator_headers))
        assert notice["status"] == "NOTICE"
        assert notice["notice_reason"] == "OPERATOR"

        rescinded = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "ACTIVE"},
            intake_coordinator_headers))
        assert rescinded["status"] == "ACTIVE"
        assert rescinded.get("notice_reason") is None

        statement = validate_success(api.get_tenancy_statement(
            ctx["tenancy"]["id"], intake_coordinator_headers))
        assert statement["balance_cents"] == 60968, (
            "Rescission posts no new charge; only the move-in proration "
            "remains")

    def test_tenancy_pending_to_terminated_invalid_transition(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "Termination is symmetric from `ACTIVE` or from
        `NOTICE`"
        PRD §2.8: "Seventh, state-machine validity: the requested target
        status must be a declared transition from the entity's current
        status"

        Design: Corner/state_machines/tenancy_pending_to_terminated_invalid_transition
        """
        ctx = setup_pending_tenancy(site_name="S", household_name="Fam T")
        resp = api.update_tenancy(
            ctx["tenancy"]["id"],
            {"status": "TERMINATED", "move_out_date": "2026-08-20"},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_tenancy(ctx["tenancy"]["id"])["status"] == "PENDING_MOVE_IN"

    def test_tenancy_cancelled_terminal_lockdown(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.4: "A tenancy that never begins may instead be cancelled
        outright — `PENDING_MOVE_IN → CANCELLED` — with no preconditions.
        `TERMINATED` and `CANCELLED` are terminal."

        Design: Corner/state_machines/tenancy_cancelled_terminal_lockdown
        """
        ctx = setup_pending_tenancy(site_name="S", household_name="Fam TL")
        cancelled = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "CANCELLED"},
            intake_coordinator_headers))
        assert cancelled["status"] == "CANCELLED"

        resp = api.update_tenancy(ctx["tenancy"]["id"], {"status": "NOTICE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_repeat_activation_rejected(self, api, intake_coordinator_headers,
                                        operator_admin_headers):
        """PRD §2.8: "Seventh, state-machine validity: the requested target
        status must be a declared transition from the entity's current
        status"
        PRD §3.4: "Activation — `PENDING_MOVE_IN → ACTIVE`, performed by an
        `IntakeCoordinator` — is the most heavily gated transition in the
        system"

        Design: Corner/state_machines/repeat_activation_rejected
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam RA")

        resp = api.update_tenancy(ctx["tenancy"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        entries, meta = validate_paginated(api.list_charge_ledger_entries(
            operator_admin_headers,
            params={"tenancy_id": ctx["tenancy"]["id"]}))
        assert len(entries) == 1, (
            "The prorated RENT charge is posted exactly once")
        assert entries[0]["entry_type"] == "RENT"
        assert entries[0]["amount_cents"] == 60968


class TestAvailabilityRead:
    def test_availability_computed_read_fields(self, api,
                                               operator_admin_headers):
        """PRD §3.2: "A computed availability read for a unit answers, in one
        place, everything an intake decision needs: `unit_status`,
        `current_occupancy`, `available_beds`, `under_pest_exclusion`,
        `pest_exclusion_end_date`, `has_valid_certification`,
        `habitability_score_cumulative`, and
        `habitability_score_worst_case`."

        Design: Corner/endpoints/availability_computed_read_fields
        """
        ctx = setup_active_tenancy(
            site_name="S", household_name="Fam AV",
            members=(("AV 1", "1990-01-01", "HEAD"),
                     ("AV 2", "1991-01-01", "SPOUSE")))
        read = validate_success(api.get_unit_availability(
            ctx["unit"]["id"], operator_admin_headers))
        assert read["current_occupancy"] == 2
        assert read["available_beds"] == 2, "4 - 2"
        assert read["under_pest_exclusion"] is False
        assert read["has_valid_certification"] is True
        assert read["unit_status"] == "OCCUPIED"
