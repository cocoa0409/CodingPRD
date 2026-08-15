"""Billing gate, OS&D capped-liability waterfall, claim holds, and the
on-time service-standard report."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_service_standard_report,
    create_service_standard_report_payload,
    get_success_data,
    make_delivered_shipment,
    make_osd_case,
    make_rated_shipment,
    make_shipment,
    make_terminal,
    make_terminal_pair,
    set_clock,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["rating_clerk_headers"]
OSD = TEST_USERS["osd_clerk_headers"]
ADMIN = TEST_USERS["terminal_admin_headers"]
DOCK = TEST_USERS["dock_supervisor_headers"]


class TestOsdLiabilityWaterfall:
    def _delivered_class70_with_case(self, api):
        """Deliver a CLASS_70 450-lb shipment rated GROSS at 24725 (LIFTGATE +
        NOTIFY), then open and review a DAMAGE case claiming 200000 with line
        items [100000, 90000]. The trailer caps are sized so the 450-lb
        shipment alone clears the 60.0 readiness floor."""
        ctx = make_delivered_shipment(
            shipment_overrides={
                "nmfc_class": "CLASS_70", "actual_weight_lbs": 450,
                "length_in": 48, "width_in": 40, "height_in": 48,
                "service_standard": "STANDARD",
                "accessorial_codes": ["LIFTGATE", "NOTIFY"],
            },
            trailer_max_weight_lbs=700,   # 450/700 = 64.3% >= 60.0 floor
            trailer_max_cube_cuft=3500,
            door_number=22,
        )
        shipment = ctx["shipment"]
        assert shipment["handling_status"] == "DELIVERED"
        assert shipment["rated_amount_cents"] == 24725
        case = make_osd_case(shipment["id"], case_kind="DAMAGE",
                             claimed_amount_cents=200000,
                             item_amounts_cents=[100000, 90000])
        validate_success(api.review_osd_case(case["id"], headers=OSD))
        return shipment, case

    def test_osd_resolution_awards_min_of_four_caps(self, api):
        """PRD §3.8: "The `awarded_amount_cents` is the minimum of those four
        values; when ceilings tie, the same value results, so tie order is
        immaterial."
        PRD §3.8: "3. The per-pound class cap: the shipment's current
        `actual_weight_lbs` multiplied by the per-pound liability for its
        current `nmfc_class`, rounded half-up to whole cents. The per-pound
        rates are: `CLASS_50` 150, `CLASS_55` 200, `CLASS_60` 250, `CLASS_65`
        300, `CLASS_70` 350, `CLASS_85` 450, `CLASS_100` 600, `CLASS_125` 800
        cents per pound."

        Design: Difficulty/combinatorial_formula/osd_liability_min_of_four_caps
        """
        _, case = self._delivered_class70_with_case(api)
        resolved = validate_success(api.resolve_osd_case(case["id"], headers=OSD))
        # min(claimed 200000, gross 190000, class cap 450*350=157500,
        #     freight cap 24725*10=247250) = 157500 — the class cap binds.
        assert resolved["awarded_amount_cents"] == 157500
        assert resolved["status"] == "RESOLVED"

    def test_resolution_clears_osd_hold(self, api):
        """PRD §3.8: "Both resolution and denial clear the hold when the shipment
        has no other case still `OPEN` or `UNDER_REVIEW` — the `osd_hold` flips
        back to `false` and the freight (if still on dock) becomes loadable
        again."

        Design: Difficulty/combinatorial_formula/osd_liability_min_of_four_caps
        """
        shipment, case = self._delivered_class70_with_case(api)
        validate_success(api.resolve_osd_case(case["id"], headers=OSD))
        after = get_success_data(api.get_shipment(shipment["id"], headers=OSD))
        assert after["osd_hold"] is False, (
            "no remaining OPEN/UNDER_REVIEW case -> hold released"
        )


class TestBillingGate:
    def test_bill_before_delivery_rejected(self, api):
        """PRD §3.7: "A `RatingClerk` may bill a shipment whose `rating_status`
        is `RATED` or `RERATED` only when two conditions hold: its
        `handling_status` is `DELIVERED`, and no OS&D case linked to the
        shipment is `OPEN` or `UNDER_REVIEW`. Billing against either violation
        is rejected with `ERR_SHIPMENT_NOT_BILLABLE` (HTTP 409)."

        Design: Corner/validations/error_shipment_not_billable_before_delivery
        """
        origin, dest = make_terminal_pair()
        shipment = make_rated_shipment(origin["id"], dest["id"],
                                       nmfc_class="CLASS_70",
                                       actual_weight_lbs=450)
        resp = api.bill_shipment(shipment["id"], headers=CLERK)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_BILLABLE)


class TestOsdHoldSideEffect:
    def test_osd_case_creation_sets_hold_immediately(self, api):
        """PRD §3.8: "The case is created `OPEN`, and opening it sets the
        shipment's `osd_hold` to `true` immediately: freight under an open claim
        may not be manifested (§3.5), and the hold is the physical interlock for
        that rule."

        Design: Corner/endpoints/osd_case_create_side_effect_sets_hold
        """
        origin, dest = make_terminal_pair()
        shipment = make_rated_shipment(origin["id"], dest["id"],
                                       nmfc_class="CLASS_70",
                                       actual_weight_lbs=450)
        assert shipment["osd_hold"] is False
        case = make_osd_case(shipment["id"], case_kind="OVERAGE",
                             claimed_amount_cents=100,
                             item_amounts_cents=[100])
        assert case["status"] == "OPEN"
        after = get_success_data(api.get_shipment(shipment["id"], headers=OSD))
        assert after["osd_hold"] is True, (
            "the hold is visible on an immediate read (no lag)"
        )

    def test_dock_supervisor_cannot_resolve_case(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /ltl/osd-cases/{caseId}/resolve is authorized for OsdClerk
        only.

        Design: Corner/rbac/dock_supervisor_cannot_resolve_osd_case
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                 actual_weight_lbs=500)
        case = make_osd_case(shipment["id"], case_kind="DAMAGE",
                             claimed_amount_cents=1000,
                             item_amounts_cents=[1000])
        validate_success(api.review_osd_case(case["id"], headers=OSD))
        resp = api.resolve_osd_case(case["id"], headers=DOCK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_osd_case(case["id"], headers=OSD))
        assert after["status"] == "UNDER_REVIEW"


class TestServiceStandardReport:
    def test_on_time_report_counts_delivery_at_commitment(self, api):
        """PRD §3.7: "Of those, `shipments_on_time` counts the shipments that are
        `DELIVERED` with `delivered_at_utc` at or before
        `committed_delivery_utc` — arrival exactly at the commitment instant
        counts as on time."
        PRD §3.7: "The report counts `shipments_due`: shipments whose
        `destination_terminal_id` is this terminal, whose
        `committed_delivery_utc` falls inside the window, and whose
        `handling_status` is `IN_LINEHAUL` or `DELIVERED`"
        PRD §3.7: "`service_level_met` is true when the on-time percentage is at
        least 95.0 — the service target — and 95.0 exactly meets the standard."

        Design: Corner/calculations/on_time_report_threshold_and_half_open_window
        """
        set_clock("2026-08-01T10:00:00Z")
        origin = make_terminal(code="CHI", name="Chicago", dock_doors=12)
        dest = make_terminal(code="ATL", name="Atlanta", dock_doors=10,
                             timezone="UTC")
        # GUARANTEED: tendered 2026-08-01T10:00:00Z -> commit +1 day. The leg is
        # arrived with the logical clock at the commitment instant, so the
        # delivery lands exactly at the commitment (<= semantics: on time).
        ctx = make_delivered_shipment(
            t_origin=origin, t_dest=dest,
            shipment_overrides={"nmfc_class": "CLASS_60",
                                "actual_weight_lbs": 26000, "length_in": 96,
                                "width_in": 96, "height_in": 96,
                                "service_standard": "GUARANTEED"},
            door_number=39,
            leg_dep="2026-08-01T20:00:00Z", leg_arr="2026-08-02T08:00:00Z",
            arrive_clock="2026-08-02T10:00:00Z",
        )
        shipment = ctx["shipment"]
        assert shipment["committed_delivery_utc"] == "2026-08-02T10:00:00Z"
        assert shipment["delivered_at_utc"] == "2026-08-02T10:00:00Z", (
            "delivered exactly at the commitment instant"
        )

        resp = api.create_service_standard_report(
            dest["id"], create_service_standard_report_payload("2026-08-02"),
            headers=ADMIN)
        report = validate_success(resp, expected_status=201)
        assert_service_standard_report(report)
        assert report["shipments_due"] == 1, (
            "commitment 2026-08-02T10:00:00Z falls inside "
            "[2026-08-02T00:00:00Z, 2026-08-03T00:00:00Z)"
        )
        assert report["shipments_on_time"] == 1, (
            "delivered exactly at commitment counts as on time"
        )
        assert report["on_time_pct"] == 100.0
        assert report["service_level_met"] is True

    def test_report_excludes_tendered_and_cancelled(self, api):
        """PRD §3.7: "The report counts `shipments_due`: shipments whose
        `destination_terminal_id` is this terminal, whose
        `committed_delivery_utc` falls inside the window, and whose
        `handling_status` is `IN_LINEHAUL` or `DELIVERED` — freight still
        `TENDERED`, `ON_DOCK`, or `MANIFESTED`, and cancelled freight, is
        excluded from both numerator and denominator."
        PRD §3.7: "when no shipments are due, the percentage is 0.0 by
        definition."

        Design: Corner/calculations/input_set_filtering_excludes_cancelled_and_tendered
        """
        set_clock("2026-08-01T10:00:00Z")
        origin = make_terminal(code="CHI", name="Chicago", dock_doors=12)
        dest = make_terminal(code="ATL", name="Atlanta", dock_doors=10,
                             timezone="UTC")
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                 actual_weight_lbs=500,
                                 service_standard="GUARANTEED")
        assert shipment["committed_delivery_utc"] == "2026-08-02T10:00:00Z"
        # The shipment stays TENDERED: excluded from the report's input set.
        resp = api.create_service_standard_report(
            dest["id"], create_service_standard_report_payload("2026-08-02"),
            headers=ADMIN)
        report = validate_success(resp, expected_status=201)
        assert report["shipments_due"] == 0
        assert report["shipments_on_time"] == 0
        assert report["on_time_pct"] == 0.0
        assert report["service_level_met"] is False
