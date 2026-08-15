"""Utilization reporting: the reserve accrual variants, the dispute-revise
cycle, void compensation, terminal lockdown, duplicate periods, and monthly
charge."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_lease,
    create_lease_with_accepted_report,
    make_lessee_rep_headers,
    submit_and_accept_report,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestAccrualVariants:
    def test_actual_vs_minimum_guarantee_diverge_below_minimum(self, api):
        """PRD §3.3: "The billable hours depend on the lease's
        `accrual_basis`: under `ACTUAL` the billable hours are exactly the
        reported `flight_hours`; under `MINIMUM_GUARANTEE` they are the
        greater of the reported `flight_hours` and the lease's
        `minimum_monthly_hours`, diverging from the actual basis exactly when
        the reported hours fall short of the minimum."
        PRD §3.3: "The posted accrual equals the flight-hour term — billable
        hours multiplied by `reserve_rate_per_fh_cents`, rounded half up to
        whole cents — plus the cycle term — `flight_cycles` multiplied by
        `reserve_rate_per_fc_cents`, exact integer arithmetic with no
        rounding."

        Design: Difficulty/dual_variant_calc/reserve_accrual_actual_vs_minimum_guarantee
        """
        # Lease A: ACTUAL basis.
        lease_a, _ac_a, lessee_a = create_active_lease(
            monthly_rent_cents=1000000, reserve_rate_per_fh_cents=4000,
            reserve_rate_per_fc_cents=8000, monthly_hour_cap=300,
            accrual_basis="ACTUAL")
        submit_and_accept_report(lease_a["id"], lessee_a["id"],
                                 period_month="2026-08", flight_hours=100.0,
                                 flight_cycles=20)
        # Lease B: MINIMUM_GUARANTEE with a 150-hour minimum.
        lease_b, _ac_b, lessee_b = create_active_lease(
            monthly_rent_cents=1000000, reserve_rate_per_fh_cents=4000,
            reserve_rate_per_fc_cents=8000, monthly_hour_cap=300,
            accrual_basis="MINIMUM_GUARANTEE", minimum_monthly_hours=150)
        submit_and_accept_report(lease_b["id"], lessee_b["id"],
                                 period_month="2026-08", flight_hours=100.0,
                                 flight_cycles=20)

        acc_a = validate_success(api.get_lease(lease_a["id"], ADMIN))["reserve_accrued_cents"]
        acc_b = validate_success(api.get_lease(lease_b["id"], ADMIN))["reserve_accrued_cents"]
        assert acc_a == 560000, f"ACTUAL: 100.0x4000 + 20x8000 = 560000, got {acc_a}"
        assert acc_b == 760000, f"MINIMUM_GUARANTEE: max(100,150)x4000 + 20x8000 = 760000, got {acc_b}"
        assert acc_a != acc_b, "identical utilization must accrue differently across variants"

    def test_variant_selection_is_by_lease_terms_not_report(self, api):
        """PRD §3.2: "The `accrual_basis` selects the reserve-accrual variant
        — `ACTUAL`, the default, or `MINIMUM_GUARANTEE` — and
        `minimum_monthly_hours`, defaulting to zero, sets the minimum
        billable hours per month that apply only when the basis is
        `MINIMUM_GUARANTEE`."
        PRD §3.3: "The billable hours depend on the lease's
        `accrual_basis`: under `ACTUAL` the billable hours are exactly the
        reported `flight_hours`; under `MINIMUM_GUARANTEE` they are the
        greater of the reported `flight_hours` and the lease's
        `minimum_monthly_hours`, diverging from the actual basis exactly when
        the reported hours fall short of the minimum."

        Design: Difficulty/dual_variant_calc/reserve_accrual_actual_vs_minimum_guarantee
        """
        # Identical report payloads on two leases differing only in basis:
        # the report's own fields cannot select the variant.
        lease_a, _ac_a, lessee_a = create_active_lease(accrual_basis="ACTUAL")
        rep_a = submit_and_accept_report(lease_a["id"], lessee_a["id"],
                                         period_month="2026-08",
                                         flight_hours=100.0, flight_cycles=20)
        lease_b, _ac_b, lessee_b = create_active_lease(
            accrual_basis="MINIMUM_GUARANTEE", minimum_monthly_hours=150)
        rep_b = submit_and_accept_report(lease_b["id"], lessee_b["id"],
                                         period_month="2026-08",
                                         flight_hours=100.0, flight_cycles=20)
        assert rep_a["posted_accrual_cents"] == 560000
        assert rep_b["posted_accrual_cents"] == 760000

    def test_minimum_guarantee_above_minimum_uses_actual_hours(self, api):
        """PRD §3.3: "under `MINIMUM_GUARANTEE` they are the greater of the
        reported `flight_hours` and the lease's `minimum_monthly_hours`,
        diverging from the actual basis exactly when the reported hours fall
        short of the minimum."

        Design: Corner/calculations/accrual_minimum_guarantee_above_minimum_uses_actual
        """
        lease, _ac, lessee = create_active_lease(
            monthly_rent_cents=1000000, reserve_rate_per_fh_cents=4000,
            reserve_rate_per_fc_cents=8000, monthly_hour_cap=300,
            accrual_basis="MINIMUM_GUARANTEE", minimum_monthly_hours=150)
        report = submit_and_accept_report(lease["id"], lessee["id"],
                                          period_month="2026-08",
                                          flight_hours=200.0, flight_cycles=25)
        # max(200.0, 150) x 4000 + 25 x 8000 = 800000 + 200000
        assert report["posted_accrual_cents"] == 1000000, (
            f"reported hours above the minimum are used as-is; "
            f"expected 1000000, got {report['posted_accrual_cents']}")


class TestDisputeReviseCycle:
    def test_revise_recomputes_accrual_from_revised_figures(self, api):
        """PRD §3.3: "the owning `LesseeRep` may revise a `DISPUTED` report,
        which replaces its `flight_hours` and `flight_cycles`, clears
        `dispute_reason` to null, and returns it to `SUBMITTED` for another
        review."
        PRD §3.3: "That amount is stamped on the report as
        `posted_accrual_cents`, added into the lease's
        `reserve_accrued_cents` with the balance recomputed per §2.9, and the
        aircraft's `total_flight_hours` and `total_flight_cycles` are
        increased by the reported `flight_hours` and `flight_cycles` in the
        same mutation."

        Design: Difficulty/non_linear_state_machine/utilization_report_dispute_revise_cycle
        """
        lease, aircraft, lessee = create_active_lease(
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        report = submit_report(lease["id"], lessee["id"],
                               period_month="2026-08", flight_hours=100.0,
                               flight_cycles=20)
        created_version = report["version"]
        disputed = validate_success(
            api.review_utilization_report(
                report["id"], {"decision": "DISPUTE", "reason": "hours mismatch vs ACARS"},
                ADMIN))
        assert disputed["status"] == "DISPUTED"

        revised = validate_success(
            api.revise_utilization_report(
                report["id"], {"flight_hours": 120.0, "flight_cycles": 22},
                make_lessee_rep_headers(lessee["id"])))
        assert revised["status"] == "SUBMITTED", (
            f"revise returns the report to SUBMITTED, got {revised['status']!r}")
        assert revised["version"] >= created_version + 2, (
            f"version must have advanced through dispute and revise; "
            f"created at {created_version}, now {revised['version']}")

        accepted = validate_success(
            api.review_utilization_report(report["id"], {"decision": "ACCEPT"}, ADMIN))
        # Accrual computed from the REVISED figures: 120.0 x 4000 + 22 x 8000.
        assert accepted["posted_accrual_cents"] == 656000, (
            f"expected 656000 from revised 120.0h/22 cycles, got "
            f"{accepted['posted_accrual_cents']}")

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_accrued_cents"] == 656000
        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["total_flight_hours"] == pytest.approx(120.0)
        assert aircraft_now["total_flight_cycles"] == 22

    def test_dispute_records_reason(self, api):
        """PRD §3.3: "Disputing a report records the supplied `reason` on the
        report's `dispute_reason` and moves it `SUBMITTED → DISPUTED`."

        Design: Difficulty/non_linear_state_machine/utilization_report_dispute_revise_cycle
        """
        lease, _aircraft, lessee = create_active_lease()
        report = submit_report(lease["id"], lessee["id"], period_month="2026-08")
        disputed = validate_success(
            api.review_utilization_report(
                report["id"], {"decision": "DISPUTE", "reason": "hours mismatch vs ACARS"},
                ADMIN))
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "hours mismatch vs ACARS"


class TestVoidCompensation:
    def test_accept_then_void_restores_totals(self, api):
        """PRD §3.3: "a `LessorAdmin` may void an `ACCEPTED` report while the
        lease is `ACTIVE`, `DEFAULTED`, or `RETURN_INITIATED`, which
        subtracts exactly `posted_accrual_cents` from
        `reserve_accrued_cents`, subtracts the report's hours and cycles from
        the aircraft totals, recomputes the reserve balance, and leaves the
        report terminally `VOIDED`. Accept followed by void is a net no-op on
        both ledgers."

        Design: Difficulty/compensating_invariant/utilization_accept_void_restores_totals
        """
        lease, aircraft, lessee = create_active_lease(
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        report = submit_report(lease["id"], lessee["id"],
                               period_month="2026-08", flight_hours=100.0,
                               flight_cycles=20)

        accepted = validate_success(
            api.review_utilization_report(report["id"], {"decision": "ACCEPT"}, ADMIN))
        assert accepted["posted_accrual_cents"] == 560000
        aircraft_mid = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_mid["total_flight_hours"] == pytest.approx(100.0)
        assert aircraft_mid["total_flight_cycles"] == 20

        voided = validate_success(api.void_utilization_report(report["id"], ADMIN))
        assert voided["status"] == "VOIDED"

        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["total_flight_hours"] == 0
        assert aircraft_now["total_flight_cycles"] == 0
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_accrued_cents"] == 0

    def test_totals_defined_over_accepted_reports_only(self, api):
        """PRD §3.3: "The aircraft totals are defined over `ACCEPTED` reports
        across every lease of the airframe — hours carried to one decimal
        place, cycles as integers — so each accept increments them and each
        void decrements them."

        Design: Difficulty/compensating_invariant/utilization_accept_void_restores_totals
        """
        lease, aircraft, lessee = create_active_lease()
        # A merely SUBMITTED report contributes nothing to the totals.
        submit_report(lease["id"], lessee["id"], period_month="2026-08",
                      flight_hours=55.0, flight_cycles=9)
        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["total_flight_hours"] == 0
        assert aircraft_now["total_flight_cycles"] == 0

        # After accept the totals reflect exactly the accepted report.
        reports, _meta = validate_paginated(api.list_utilization_reports(lease["id"], ADMIN))
        validate_success(
            api.review_utilization_report(reports[0]["id"], {"decision": "ACCEPT"}, ADMIN))
        aircraft_acc = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_acc["total_flight_hours"] == pytest.approx(55.0)
        assert aircraft_acc["total_flight_cycles"] == 9

    def test_voided_report_terminal_lockdown(self, api):
        """PRD §3.3: "leaves the report terminally `VOIDED`."
        PRD §2.8 (5): "State preconditions — the target resource is in a
        from-state the transition allows, including terminal-state lockdown
        and the one-open-child rules (else `ERR_INVALID_STATE`, HTTP 409; ...)"

        Design: Corner/state_machines/voided_report_terminal_lockdown
        """
        lease, _aircraft, lessee, report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20})
        validate_success(api.void_utilization_report(report["id"], ADMIN))

        resp = api.review_utilization_report(report["id"], {"decision": "ACCEPT"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_accrued_cents"] == 0, (
            "the rejected review must not produce any ledger side effect")


class TestDuplicatePeriod:
    def test_duplicate_report_period_rejected(self, api):
        """PRD §3.3: "At most one non-`VOIDED` report may exist per lease per
        `period_month` — a duplicate is `ERR_DUPLICATE_REPORT_PERIOD` — while
        a voided report frees its month for re-submission."

        Design: Corner/validations/duplicate_report_period_rejected
        """
        lease, _aircraft, lessee = create_active_lease()
        submit_report(lease["id"], lessee["id"], period_month="2026-08",
                      flight_hours=100.0, flight_cycles=20)
        resp = api.create_utilization_report(
            lease["id"],
            {"period_month": "2026-08", "flight_hours": 50.0, "flight_cycles": 10},
            make_lessee_rep_headers(lessee["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD, expected_status=409)


class TestMonthlyCharge:
    def test_tiered_overage_and_cycle_surcharge(self, api):
        """PRD §3.3: "The first fifty overage hours bill at 5,000 cents per
        hour and any overage beyond fifty hours bills at 7,500 cents per
        hour, with each tier rounded half up to whole cents before the two
        are summed. A cycle surcharge of 25,000 cents applies when the
        month's cycles multiplied by two exceed the month's hours, and is
        zero otherwise."

        Design: Difficulty/combinatorial_formula/monthly_charge_tiered_overage
        """
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 340.0, "flight_cycles": 400},
            monthly_rent_cents=1000000, monthly_hour_cap=300,
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        data = validate_success(api.get_monthly_charge(lease["id"], "2026-08", ADMIN))
        # Overage 40h, all inside tier 1: 40 x 5000.
        assert data["overage_cents"] == 200000
        # 400 cycles x 2 = 800 > 340 hours -> surcharge fires.
        assert data["cycle_surcharge_cents"] == 25000
        assert data["total_cents"] == 1225000, (
            f"1000000 + 200000 + 25000 = 1225000, got {data['total_cents']}")

    def test_tier2_rate_applies_beyond_fifty_overage_hours(self, api):
        """PRD §3.3: "The first fifty overage hours bill at 5,000 cents per
        hour and any overage beyond fifty hours bills at 7,500 cents per
        hour, with each tier rounded half up to whole cents before the two
        are summed."
        PRD §3.3: "The response carries `month`, `hours`, `cycles`,
        `base_rent_cents` (the lease's `monthly_rent_cents`),
        `overage_cents`, `cycle_surcharge_cents`, and their sum
        `total_cents`."

        Design: Difficulty/combinatorial_formula/monthly_charge_tiered_overage
        """
        # 400.0 hours vs cap 300 -> overage 100 = 50 x 5000 + 50 x 7500.
        # 120 cycles x 2 = 240 <= 400 -> no surcharge.
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 400.0, "flight_cycles": 120},
            monthly_rent_cents=1000000, monthly_hour_cap=300)
        data = validate_success(api.get_monthly_charge(lease["id"], "2026-08", ADMIN))
        assert data["hours"] == pytest.approx(400.0)
        assert data["cycles"] == 120
        assert data["base_rent_cents"] == 1000000
        assert data["overage_cents"] == 625000, (
            f"50x5000 + 50x7500 = 625000, got {data['overage_cents']}")
        assert data["cycle_surcharge_cents"] == 0
        assert data["total_cents"] == 1625000

    def test_cap_inclusive_and_surcharge_strict_greater(self, api):
        """PRD §3.3: "Overage hours are the hours in excess of
        `monthly_hour_cap`, floored at zero."
        PRD §3.3: "A cycle surcharge of 25,000 cents applies when the month's
        cycles multiplied by two exceed the month's hours, and is zero
        otherwise."

        Design: Corner/cross_cutting_layers/cycle_surcharge_threshold_exact_boundary
        """
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 300.0, "flight_cycles": 150},
            monthly_rent_cents=1000000, monthly_hour_cap=300)
        data = validate_success(api.get_monthly_charge(lease["id"], "2026-08", ADMIN))
        # Hours exactly at the cap: overage is zero (cap is inclusive).
        assert data["overage_cents"] == 0
        # 150 cycles x 2 == 300 hours exactly: strict > does not fire.
        assert data["cycle_surcharge_cents"] == 0
        assert data["total_cents"] == 1000000

    def test_charge_excludes_non_accepted_reports(self, api):
        """PRD §3.3: "Given a `month` in `YYYY-MM` form, the charge uses only
        the `ACCEPTED` utilization report for that period — `SUBMITTED`,
        `DISPUTED`, and `VOIDED` reports are excluded, and when no accepted
        report exists the month's hours and cycles are both zero."

        Design: Corner/calculations/monthly_charge_excludes_non_accepted_reports
        """
        lease, _aircraft, lessee = create_active_lease(
            monthly_rent_cents=1000000, monthly_hour_cap=300)
        submit_report(lease["id"], lessee["id"], period_month="2026-08",
                      flight_hours=400.0, flight_cycles=500)
        data = validate_success(api.get_monthly_charge(lease["id"], "2026-08", ADMIN))
        assert data["hours"] == 0
        assert data["cycles"] == 0
        assert data["overage_cents"] == 0
        assert data["cycle_surcharge_cents"] == 0
        assert data["total_cents"] == 1000000, (
            f"base rent only when no ACCEPTED report exists, got {data['total_cents']}")


class TestReportListing:
    def test_reports_sorted_by_period_month(self, api):
        """PRD §2.3: "a lease's utilization reports are ordered by
        `period_month` ascending."
        PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/fk_reverse_reachability_utilization_reports_sorted
        """
        lease, _aircraft, lessee = create_active_lease()
        # Created out of month order on purpose.
        submit_report(lease["id"], lessee["id"], period_month="2026-08",
                      flight_hours=10.0, flight_cycles=2)
        submit_report(lease["id"], lessee["id"], period_month="2026-07",
                      flight_hours=20.0, flight_cycles=4)
        data, meta = validate_paginated(api.list_utilization_reports(lease["id"], ADMIN))
        assert meta["total_count"] == 2
        assert data[0]["period_month"] == "2026-07", (
            f"reports must come back sorted period_month ASC, got {data[0]['period_month']!r}")
        assert data[1]["period_month"] == "2026-08"
