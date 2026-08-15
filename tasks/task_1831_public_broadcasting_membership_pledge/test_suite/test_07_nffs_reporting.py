"""NFFS reporting: dual variants, rounding order, segregation of duties, reconcile."""
from test_helpers import (
    ApiErrorId,
    assert_nffs_report,
    capture_pledge,
    close_drive,
    create_nffs_report_payload,
    create_premium,
    get_drive,
    get_pledge,
    make_coordinator_headers,
    make_station_admin_headers,
    pay_in_full,
    post_payment_ok,
    receive_lot,
    setup_nffs_mixed_pledges,
    setup_station,
    validate_error,
    validate_success,
)


class TestNffsDualVariant:
    def test_nffs_provisional_vs_final_revenue(self, api):
        """PRD §3.11: "Under the **PROVISIONAL** variant (the variant on `DRAFT`
        and `AMENDED` reports), the total is the sum over all pledges in the
        fiscal year of: the pledge's `amount_cents` minus its FMV deduction
        when `payment_status` is `PLEDGED`; the pledge's `net_collected_cents`
        when `payment_status` is `PAID` or `PARTIAL`; and zero when
        `payment_status` is `DECLINED` or `WRITTEN_OFF`. Under the **FINAL**
        variant (the variant on `FINALIZED` reports), only actually-collected
        revenue counts: the sum includes a pledge's `net_collected_cents` only
        when `payment_status` is `PAID` or `PARTIAL`, and `PLEDGED` pledges
        contribute zero."
        PRD §3.11: "Finalization moves the report `DRAFT` → `FINALIZED`, flips
        the variant to `FINAL`, recomputes `membership_revenue_cents` under the
        FINAL variant, and stamps `finalized_by_user_id` from the requesting
        `X-User-ID`."

        Design: Difficulty/dual_variant_calc/nffs_provisional_vs_final_revenue
        """
        drafter = make_coordinator_headers("coord-1001")
        station = setup_nffs_mixed_pledges(drafter)
        report = station["report"]

        assert report["status"] == "DRAFT"
        assert report["variant"] == "PROVISIONAL"
        assert report["drafted_by_user_id"] == "coord-1001"
        # P1: PLEDGED 12000 with MUG FMV 2500 RESERVED -> 9500 provisional.
        # P2: PAID 20000, no premium -> net 20000 under both variants.
        assert report["membership_revenue_cents"] == 29500, (
            "PROVISIONAL counts the uncollected pledge at face minus FMV")

        resp = api.finalize_nffs_report(
            report["id"], make_station_admin_headers("admin-9001"))
        finalized = validate_success(resp, 200)
        assert_nffs_report(finalized)
        assert finalized["status"] == "FINALIZED"
        assert finalized["variant"] == "FINAL"
        assert finalized["finalized_by_user_id"] == "admin-9001"
        assert finalized["membership_revenue_cents"] == 20000, (
            "FINAL counts only collected revenue; the PLEDGED pledge is zero")
        assert report["membership_revenue_cents"] > finalized[
            "membership_revenue_cents"], (
            "the same drive totals yield a strictly smaller-or-equal FINAL")

    def test_nffs_amend_returns_to_provisional_and_refinalize_recomputes(
            self, api):
        """PRD §3.11: "Amendment re-opens a `FINALIZED` report to `AMENDED`
        status, returning the variant to `PROVISIONAL`. Re-finalizing from
        `AMENDED` is allowed and follows the same rule: the variant flips back
        to `FINAL`, totals are recomputed, and the segregation-of-duties check
        still applies against the original `drafted_by_user_id`."

        Design: Difficulty/dual_variant_calc/nffs_provisional_vs_final_revenue
        """
        drafter = make_coordinator_headers("coord-1001")
        station = setup_nffs_mixed_pledges(drafter)
        report = station["report"]
        admin = make_station_admin_headers("admin-9001")

        finalized = validate_success(
            api.finalize_nffs_report(report["id"], admin), 200)
        assert finalized["membership_revenue_cents"] == 20000

        resp = api.amend_nffs_report(report["id"], admin)
        amended = validate_success(resp, 200)
        assert amended["status"] == "AMENDED"
        assert amended["variant"] == "PROVISIONAL", (
            "amendment returns the report to the PROVISIONAL variant")

        resp = api.finalize_nffs_report(report["id"], admin)
        refinalized = validate_success(resp, 200)
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["variant"] == "FINAL"
        assert refinalized["membership_revenue_cents"] == 20000, (
            "re-finalizing from AMENDED recomputes totals under FINAL")


class TestNffsRoundingOrder:
    def _setup_floor_scenario(self, api):
        """One PAID pledge whose premium FMV exceeds its amount (floored at 0)
        plus one plain PAID pledge of 5000, in an FY2026 drive."""
        station = setup_station(level_overrides={
            "code": "BASIC", "min_annual_cents": 1000,
            "min_monthly_sustainer_cents": 100})
        premium = create_premium(sku="BOOK-0001", title="Signed Book",
                                 fair_market_value_cents=1500,
                                 membership_level_code="BASIC")
        receive_lot(premium["id"], received_at="2026-07-15T00:00:00Z",
                    unit_cost_cents=700, total_qty=10)
        small = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=1000, premium_id=premium["id"])
        assert small["fulfillment_status"] == "RESERVED"
        small_paid = post_payment_ok(small, 1000)
        big = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="ONE_TIME",
            amount_cents=5000)
        big_paid = pay_in_full(big)
        station.update({"premium": premium, "small_paid": small_paid,
                        "big_paid": big_paid})
        return station

    def test_nffs_per_pledge_rounding_order(self, api):
        """PRD §3.8: "The result is the pledge's `collected_cents` minus the
        deduction, floored at 0."
        PRD §2.6: "Aggregate roll-ups (drive totals, NFFS revenue, challenge
        progress) are per-pledge integers first, then summed — never
        averaged-then-rounded."
        PRD §3.11: "the pledge's `net_collected_cents` when `payment_status`
        is `PAID` or `PARTIAL`"

        Design: Difficulty/combinatorial_formula/nffs_per_pledge_rounding_order
        """
        station = self._setup_floor_scenario(api)
        # The small pledge floors at max(0, 1000 - 1500) = 0 per-pledge.
        assert station["small_paid"]["net_collected_cents"] == 0
        assert station["small_paid"]["collected_cents"] == 1000
        assert station["big_paid"]["net_collected_cents"] == 5000

        report = validate_success(api.create_nffs_report(
            create_nffs_report_payload(2026),
            make_coordinator_headers("coord-2001")), 201)
        assert report["membership_revenue_cents"] == 5000, (
            "per-pledge floor then sum: 0 + 5000; sum-then-floor would "
            "wrongly give (1000 + 5000) - 1500 = 4500")

    def test_nffs_per_pledge_floor_feeds_drive_and_donor_totals(self, api):
        """PRD §2.6: "Aggregate roll-ups (drive totals, NFFS revenue, challenge
        progress) are per-pledge integers first, then summed — never
        averaged-then-rounded."
        PRD §3.8: "The result is the pledge's `collected_cents` minus the
        deduction, floored at 0."

        Design: Difficulty/combinatorial_formula/nffs_per_pledge_rounding_order
        """
        station = self._setup_floor_scenario(api)
        drive = get_drive(station["drive"]["id"])
        assert drive["collected_cents"] == 5000, (
            "the drive roll-up sums the floored per-pledge nets 0 + 5000")

        donor = validate_success(
            api.get_donor(station["donor"]["id"],
                          make_coordinator_headers("coord-2002")), 200)
        assert donor["lifetime_given_cents"] == 5000
        assert get_pledge(station["small_paid"]["id"])[
            "net_collected_cents"] == 0


class TestNffsSegregationOfDuties:
    def test_segregation_of_duties_finalize_by_drafter_rejected(self, api):
        """PRD §3.11: "The finalizer must differ from the drafter: if the same
        `X-User-ID` attempts to finalize a report it drafted, the request is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."
        PRD §3.11: "The draft is created in `DRAFT` status with `variant`
        `PROVISIONAL`, the `drafted_by_user_id` set to the requesting
        `X-User-ID`"

        Design: Corner/validations/segregation_of_duties_finalize_by_drafter_rejected
        """
        report = validate_success(api.create_nffs_report(
            create_nffs_report_payload(2026),
            make_coordinator_headers("coord-7001")), 201)
        assert report["drafted_by_user_id"] == "coord-7001"

        # A StationAdmin may finalize, but not with the drafter's X-User-ID.
        resp = api.finalize_nffs_report(
            report["id"], make_station_admin_headers("coord-7001"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        reread = validate_success(
            api.get_nffs_report(report["id"],
                                make_station_admin_headers("admin-1")), 200)
        assert reread["status"] == "DRAFT"
        assert reread["variant"] == "PROVISIONAL"

    def test_membership_coordinator_cannot_finalize_nffs(self, api):
        """PRD §2.1: "A recognized role attempting an operation outside its
        grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The full
        role-to-endpoint grant appears in §4."
        PRD §2.1: "`StationAdmin` — the station general manager / development
        director. Owns membership level and premium configuration, the pledge
        drive lifecycle (create/schedule/unschedule/go-live/close), on-air
        break scheduling, matching challenge and underwriting credit creation,
        NFFS report finalization and amendment, and the logical clock."

        Design: Corner/rbac/membership_coordinator_cannot_finalize_nffs
        """
        report = validate_success(api.create_nffs_report(
            create_nffs_report_payload(2026),
            make_coordinator_headers("coord-8001")), 201)

        resp = api.finalize_nffs_report(
            report["id"], make_coordinator_headers("coord-8002"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestDriveReconcile:
    def test_reconcile_rejected_while_pledges_unresolved(
            self, api, coordinator_headers):
        """PRD §3.3: "Finally, once every pledge of the drive has reached a
        terminal payment state (`PAID`, `DECLINED`, or `WRITTEN_OFF` — no
        `PLEDGED` or `PARTIAL` remaining), a `MembershipCoordinator` reconciles
        the drive: `CLOSED` → `RECONCILED`, freezing totals for NFFS reporting.
        A reconcile attempt while any pledge is unresolved is rejected with
        `ERR_UNRESOLVED_PLEDGES` (422)."

        Design: Corner/state_machines/reconcile_rejected_while_pledges_unresolved
        """
        station = setup_station()
        capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        close_drive(station["drive"]["id"])

        resp = api.reconcile_drive(station["drive"]["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_PLEDGES)
        assert get_drive(station["drive"]["id"])["status"] == "CLOSED", (
            "the rejected reconcile leaves the drive CLOSED")
