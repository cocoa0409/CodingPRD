"""The transparency projection, a partial update, and two refused writes."""

from test_helpers import (
    CONTROLLER_APPROVER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    advance_to_in_execution,
    create_program,
    create_supplier,
    create_transport_segment,
    make_controller_headers,
    manifest_guest,
    mark_ready,
    read_program,
    set_clock,
    setup_invoiced_program,
    setup_program_with_contracted_element,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]
CTRL = make_controller_headers(CONTROLLER_APPROVER_USER_ID)

SUMMARY_FIELDS = (
    "final_subtotal_cents",
    "disclosed_markup_cents",
    "management_fee_cents",
    "final_client_total_cents",
    "supplier_gross_payable_cents",
    "supplier_settled_cents",
    "supplier_open_payable_cents",
)


class TestCostSummaryProjection:
    def _invoiced_forty_guest_programme(self):
        """One 40-guest element at 5,000 cents a head, marked up a fifth."""
        return setup_invoiced_program(
            actual_headcount=40,
            program_overrides={
                "client_name": "Summary Client",
                "group_name": "Summary Group",
                "guaranteed_count": 40,
                "markup_pct": 0.20,
            },
            element_overrides={"title": "Summary Element"},
            venue_overrides={"name": "Summary Venue"},
            supplier_overrides={"legal_name": "Summary Supplier"},
            contract_overrides={"deposit_pct": 0},
        )

    def test_the_summary_reports_the_selected_fee_rate_and_the_whole_ladder(self, api):
        """PRD §3.9: "The markup-transparency read the client is entitled to see exposes,
        for one programme, its `program_id`, the frozen `estimated_client_total_cents`, and
        then the final picture: `final_subtotal_cents`, `disclosed_markup_cents`,
        `management_fee_cents`, the `fee_pct_applied` rate actually selected by the tier test,
        `final_client_total_cents`, and the three supplier-side figures
        `supplier_gross_payable_cents`, `supplier_settled_cents` and
        `supplier_open_payable_cents`."

        Design: Corner/endpoints/cost_summary_computed_read_matches_program_money_fields
        """
        ctx = self._invoiced_forty_guest_programme()

        summary = validate_success(
            api.get_program_cost_summary(ctx["program"]["id"], CTRL)
        )

        assert summary["program_id"] == ctx["program"]["id"]
        assert summary["final_subtotal_cents"] == 200_000
        assert summary["disclosed_markup_cents"] == 40_000
        # A 240,000-cent base sits below the 500,000-cent ceiling.
        assert summary["fee_pct_applied"] == 0.12
        assert summary["management_fee_cents"] == 28_800
        assert summary["final_client_total_cents"] == 268_800
        assert summary["supplier_gross_payable_cents"] == 200_000
        assert summary["supplier_settled_cents"] == 0
        assert summary["supplier_open_payable_cents"] == 200_000

    def test_the_projection_never_diverges_from_the_stored_programme(self, api):
        """PRD §3.9: "Step four selects the fee rate from the base and from the base alone,
        never from the grand total: a base below 500,000 cents — that is, below 5,000.00 in the
        billing currency — attracts a fee of 12 hundredths; a base below 2,000,000 cents
        (20,000.00) attracts 9 hundredths; and any larger base attracts 7 hundredths."

        Design: Corner/endpoints/cost_summary_computed_read_matches_program_money_fields
        """
        ctx = self._invoiced_forty_guest_programme()

        summary = validate_success(
            api.get_program_cost_summary(ctx["program"]["id"], CTRL)
        )

        program = read_program(ctx["program"]["id"])
        for field in SUMMARY_FIELDS:
            assert summary[field] == program[field], field
        assert summary["estimated_client_total_cents"] == program[
            "estimated_client_total_cents"
        ]


class TestManifestMoveStaysInsideOneProgramme:
    FIRST_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "P1-SHTL",
        "origin": "Hotel Alpha",
        "destination": "Pier 9",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:30:00Z",
        "seat_capacity": 12,
    }
    SECOND_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "P2-SHTL",
        "origin": "Hotel Beta",
        "destination": "Pier 9",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:30:00Z",
        "seat_capacity": 12,
    }

    def test_a_target_vehicle_on_another_programme_is_refused(self, api):
        """PRD §3.5: "It requires the entry to be in `ASSIGNED`, both the source and the
        target segment to be in `SCHEDULED` (otherwise `ERR_INVALID_STATE_TRANSITION`), the
        `target_segment_id` to differ from the entry's current `segment_id` (otherwise
        `ERR_INVALID_REQUEST`), and the target segment to belong to the same programme as the
        source (otherwise `ERR_SEGMENT_PROGRAM_MISMATCH`)."

        Design: Corner/endpoints/manifest_move_across_programs_rejected
        """
        first_program = create_program(
            client_name="Program One Client",
            group_name="Program One Group",
            guaranteed_count=20,
        )
        second_program = create_program(
            client_name="Program Two Client",
            group_name="Program Two Group",
            guaranteed_count=20,
        )
        home_shuttle = create_transport_segment(
            first_program["id"], wheelchair_accessible=True, **self.FIRST_SHUTTLE
        )
        foreign_shuttle = create_transport_segment(
            second_program["id"], wheelchair_accessible=True, **self.SECOND_SHUTTLE
        )
        entry = manifest_guest(
            home_shuttle["id"], guest_ref="G-300", guest_name="Cyd Moreau", seat_count=3
        )

        response = api.move_manifest_entry(
            entry["id"], {"target_segment_id": foreign_shuttle["id"]}, OC
        )

        validate_error(response, ApiErrorId.ERR_SEGMENT_PROGRAM_MISMATCH.value, 422)
        # The target exists and has room; only its programme is wrong.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_SEGMENT_NOT_FOUND.value
        )
        assert (
            validate_success(api.get_manifest_entry(entry["id"], OC))["segment_id"]
            == home_shuttle["id"]
        )
        assert (
            validate_success(api.get_transport_segment(home_shuttle["id"], OC))[
                "booked_seat_count"
            ]
            == 3
        )
        assert (
            validate_success(api.get_transport_segment(foreign_shuttle["id"], OC))[
                "booked_seat_count"
            ]
            == 0
        )
        assert read_program(second_program["id"])["seated_guest_count"] == 0


class TestSupplierPartialUpdate:
    PATCHABLE = {
        "legal_name": "Patchable Catering",
        "supplier_type": "VENUE_SERVICES",
        "insurance_liability_limit_cents": 50_000_000,
    }

    def test_only_the_two_supplied_insurance_fields_are_rewritten(self, api):
        """PRD §3.3: "The same manager may later patch a supplier's `insurance_expires_on`,
        `insurance_liability_limit_cents`, `coi_verified` or `status`, which increments the
        supplier's `version`."

        Design: Corner/endpoints/patch_supplier_updates_insurance_and_bumps_version
        """
        supplier = create_supplier(**self.PATCHABLE)

        patched = validate_success(
            api.patch_supplier(
                supplier["id"],
                {
                    "insurance_liability_limit_cents": 250_000_000,
                    "insurance_expires_on": "2028-03-31",
                },
                SM,
            )
        )

        assert patched["insurance_liability_limit_cents"] == 250_000_000
        assert patched["insurance_expires_on"] == "2028-03-31"
        assert patched["coi_verified"] is True
        assert patched["status"] == "APPROVED"
        assert patched["legal_name"] == "Patchable Catering"
        assert patched["version"] == 2


class TestWeatherSwitchNeedsAStandIn:
    EXPOSED = {
        "element_type": "ACTIVITY",
        "title": "Exposed Lawn Games",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
        "is_weather_dependent": True,
    }

    def test_a_ready_weather_dependent_element_with_no_rain_plan_cannot_switch(self, api):
        """PRD §3.7: "A stand-in must exist: the server looks for elements whose
        `alternative_for_element_id` names this element and whose status is `PLANNED`."

        Design: Corner/endpoints/weather_switch_without_an_alternative_returns_409
        """
        ctx = setup_program_with_contracted_element(
            program_overrides={
                "client_name": "No Rain Plan Client",
                "group_name": "No Rain Plan Group",
                "guaranteed_count": 30,
            },
            element_overrides=self.EXPOSED,
            venue_overrides={"name": "No Rain Plan Lawn"},
            supplier_overrides={"legal_name": "No Rain Plan Events"},
            contract_overrides={"contract_value_cents": 120_000},
        )
        advance_to_in_execution(ctx["program"]["id"])
        mark_ready(ctx["element"]["id"])
        set_clock("2026-09-11T13:00:00Z")

        response = api.weather_switch_element(ctx["element"]["id"], OC)

        validate_error(response, ApiErrorId.ERR_NO_WEATHER_ALTERNATIVE.value, 409)
        assert (
            validate_success(api.get_program_element(ctx["element"]["id"], PD))["status"]
            == "READY"
        )
        assert read_program(ctx["program"]["id"])["open_element_count"] == 1
