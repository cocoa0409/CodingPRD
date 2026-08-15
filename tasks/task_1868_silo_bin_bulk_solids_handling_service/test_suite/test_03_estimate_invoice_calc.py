"""Estimate and invoice calculation tests: tiered rates, per-line rounding."""
import pytest

from test_helpers import (
    make_plant_operator_headers,
    make_technician_headers,
    validate_success,
)
from test_helpers.fixtures import (
    create_approved_ticket,
    create_draft_ticket,
    create_in_progress_ticket,
    create_site,
    create_site_vessel_technician,
    create_technician,
    create_vessel,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]


class TestEstimateCombinatorial:
    def test_estimate_tiered_rate_crew_posture_discount(self, api):
        """PRD §3.6: "At creation the system computes a provisional `estimate_cents`
        in integer cents. The base is the per-crew-hour rate for the `job_type` —
        9500 cents for `DIAGNOSIS`, 14500 cents for `CLEANOUT`, 11000 cents for
        `INSPECTION`, 22000 cents for `RETROFIT_AERATION`, and 18000 cents for
        `RETROFIT_VIBRATOR` — multiplied by `est_hours` and by `crew_size`. When the
        vessel's `flow_posture` at creation is `FLOW_IMPAIRED`, the base is further
        multiplied by an emergency multiplier of 1.5; otherwise the multiplier is
        1.0. The multiplied result is rounded half up to integer cents, then a
        contract discount equal to that subtotal multiplied by the site's
        `contract_discount_pct` and divided by 100, again rounded half up to
        integer cents, is subtracted to yield `estimate_cents`."

        Design: Difficulty/combinatorial_formula/estimate_tiered_rate_crew_posture_discount
        """
        site = create_site(
            name="Site Three",
            state_code="IL",
            contract_discount_pct=10,
            capital_threshold_cents=500000,
        )
        vessel = create_vessel(
            site["id"],
            name="BIN-E",
            vessel_kind="BIN",
            capacity_tons=100,
            material_name="pellets",
            reorder_point_pct=30,
        )
        ticket = create_draft_ticket(
            site["id"],
            vessel["id"],
            job_type="CLEANOUT",
            requires_entry=False,
            est_hours=8,
            crew_size=2,
        )
        # 14500 x 8 x 2 = 232000; x 1.0 NORMAL; discount round(232000 x 0.10) = 23200
        assert ticket["estimate_cents"] == 208800

    def test_commercial_track_below_threshold_is_contract_service(self, api):
        """PRD §3.6: "This transition resolves the ticket's `commercial_track`: the
        ticket is routed to `CAPITAL_PROJECT` when `estimate_cents` is greater than
        or equal to the site's `capital_threshold_cents`, and to `CONTRACT_SERVICE`
        otherwise."

        Design: Difficulty/combinatorial_formula/estimate_tiered_rate_crew_posture_discount
        """
        site = create_site(
            name="Site Three",
            state_code="IL",
            contract_discount_pct=10,
            capital_threshold_cents=500000,
        )
        vessel = create_vessel(
            site["id"],
            name="BIN-E",
            vessel_kind="BIN",
            capacity_tons=100,
            material_name="pellets",
            reorder_point_pct=30,
        )
        ticket = create_draft_ticket(
            site["id"],
            vessel["id"],
            job_type="CLEANOUT",
            requires_entry=False,
            est_hours=8,
            crew_size=2,
        )
        quoted = validate_success(
            api.quote_service_ticket(ticket["id"], SM), 200
        )
        # 208800 < 500000 -> CONTRACT_SERVICE
        assert quoted["commercial_track"] == "CONTRACT_SERVICE"
        assert quoted["estimate_cents"] == 208800


class TestInvoicePerLineRounding:
    def _setup_in_progress_cleanout(self):
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={
                "name": "Site Four",
                "state_code": "IL",
                "contract_discount_pct": 10,
                "capital_threshold_cents": 500000,
            },
            vessel_overrides={
                "name": "BIN-F",
                "vessel_kind": "BIN",
                "capacity_tons": 100,
                "material_name": "pellets",
                "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech One", "weekly_capacity_hours": 40},
        )
        ticket = create_in_progress_ticket(
            site["id"],
            vessel["id"],
            tech["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T17:00:00Z",
            job_type="CLEANOUT",
            requires_entry=False,
            est_hours=8,
            crew_size=2,
        )
        return site, vessel, tech, ticket

    def test_invoice_per_line_rounding_then_sum(self, api):
        """PRD §3.9: "The ticket transitions from `IN_PROGRESS` to `COMPLETED`, the
        technician's `remaining_capacity_hours` is recomputed (the ticket's
        `est_hours` is released), and the invoice is computed with a pinned rounding
        order — per line first, then sum, then discount, then tax"
        PRD §3.9: "Summing raw fractional lines and rounding once at the end is
        non-conformant and produces different cents; the per-line rounding order is
        part of the contract."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        site, vessel, tech, ticket = self._setup_in_progress_cleanout()
        completed = validate_success(
            api.complete_service_ticket(
                ticket["id"],
                {"actual_hours": 7.5, "mileage_miles": 12, "disposal_tons": 1.25},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        # labor: 7.5 x 14500 x 2 = 217500
        assert completed["invoice_labor_cents"] == 217500
        # mobilization: 12 x 331.7 = 3980.4 -> per-line round_half_up -> 3980
        assert completed["invoice_mobilization_cents"] == 3980
        # disposal: 1.25 x 3653.92 = 4567.40 -> 4567
        assert completed["invoice_disposal_cents"] == 4567
        # per-line rounded sum (raw sum 226047.8 would round to 226048)
        assert completed["invoice_subtotal_cents"] == 226047
        # discount: round_half_up(226047 x 0.10) = round_half_up(22604.7) = 22605
        assert completed["invoice_discount_cents"] == 22605
        # tax: round_half_up((226047 - 22605) x 0.06) = round_half_up(12206.52) = 12207
        assert completed["invoice_tax_cents"] == 12207
        # total: 203442 + 12207 = 215649 (not 215650, the sum-then-round result)
        assert completed["invoice_total_cents"] == 215649

    def test_invoice_total_differs_from_sum_then_round_variant(self, api):
        """PRD §3.9: "Summing raw fractional lines and rounding once at the end is
        non-conformant and produces different cents; the per-line rounding order is
        part of the contract."
        PRD §3.9: "`invoice_total_cents` is the taxable amount plus
        `invoice_tax_cents`."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        site, vessel, tech, ticket = self._setup_in_progress_cleanout()
        completed = validate_success(
            api.complete_service_ticket(
                ticket["id"],
                {"actual_hours": 7.5, "mileage_miles": 12, "disposal_tons": 1.25},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        subtotal = completed["invoice_subtotal_cents"]
        discount = completed["invoice_discount_cents"]
        tax = completed["invoice_tax_cents"]
        total = completed["invoice_total_cents"]
        # internal consistency of the pinned pipeline
        assert subtotal == (
            completed["invoice_labor_cents"]
            + completed["invoice_mobilization_cents"]
            + completed["invoice_disposal_cents"]
        )
        assert total == (subtotal - discount) + tax
        # the non-conformant sum-then-round pipeline would produce 215650
        assert total == 215649
        assert total != 215650


class TestCapitalThresholdBoundary:
    def test_estimate_at_threshold_routes_capital_and_service_manager_approves(
        self, api
    ):
        """PRD §3.6: "This transition resolves the ticket's `commercial_track`: the
        ticket is routed to `CAPITAL_PROJECT` when `estimate_cents` is greater than
        or equal to the site's `capital_threshold_cents`, and to `CONTRACT_SERVICE`
        otherwise."
        PRD §3.6: "On the `CAPITAL_PROJECT` track, a `ServiceManager` approves,
        representing internal capital review. An approval attempted by a role that
        does not match the ticket's `commercial_track` is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/errors/capital_threshold_inclusive_boundary_routes_capital
        """
        from test_helpers.fixtures import post_quality_report

        site = create_site(
            name="CAP Site",
            state_code="IA",
            contract_discount_pct=0,
            capital_threshold_cents=285000,
        )
        vessel = create_vessel(
            site["id"],
            name="SILO-CAP",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="flour",
            reorder_point_pct=30,
            moisture_limit_pct=12.0,
        )
        tech = create_technician(name="Tech CAP", weekly_capacity_hours=40)
        # Breach the moisture limit so the vessel becomes FLOW_IMPAIRED (1.5x mult)
        post_quality_report(
            vessel["id"], tech["id"],
            sampled_at="2026-08-02T00:00:00Z",
            moisture_pct=15.0, caking_index=1,
        )
        ticket = create_draft_ticket(
            site["id"],
            vessel["id"],
            job_type="DIAGNOSIS",
            requires_entry=False,
            est_hours=10,
            crew_size=2,
        )
        # 9500 x 10 x 2 = 190000 x 1.5 = 285000; discount 0
        assert ticket["estimate_cents"] == 285000
        quoted = validate_success(api.quote_service_ticket(ticket["id"], SM), 200)
        # 285000 >= 285000 -> inclusive boundary routes CAPITAL_PROJECT
        assert quoted["commercial_track"] == "CAPITAL_PROJECT"

        # PlantOperator approval rejected on the capital track
        from test_helpers import ApiErrorId, validate_error

        res = api.approve_service_ticket(
            ticket["id"], make_plant_operator_headers(site["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        # ServiceManager approval succeeds
        approved = validate_success(
            api.approve_service_ticket(ticket["id"], SM), 200
        )
        assert approved["status"] == "APPROVED"
