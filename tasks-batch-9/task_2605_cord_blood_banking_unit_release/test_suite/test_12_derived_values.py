"""Formulas, constants, weighted sums, aggregations and the pinned nightly ladder."""

import pytest

from test_helpers import (
    NIGHTLY_COUNTERS,
    ApiErrorId,
    api_client,
    build_bank_scenario,
    confirm_reservation,
    determine_eligibility,
    expected_confirmatory_recovery_pct,
    expected_late_fee,
    expected_pre_cryo_dose,
    expected_quality_acceptance_score,
    issue_invoice,
    make_medical_director_headers,
    make_technologist_headers,
    nightly_run,
    place_reservation,
    read_account,
    read_invoice,
    read_reservation,
    read_screening,
    read_unit,
    record_confirmatory_test,
    register_enrollment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCollectionArithmetic:
    def test_the_net_volume_is_the_gross_minus_the_anticoagulant(self):
        """Two hand-computable figures on the cheapest formula in the contract.

        "The system immediately derives `net_volume_ml` as the gross collection volume minus the
        anticoagulant volume, rounded half up to 1 decimal place — this net figure, not the gross
        one, is what the laboratory will later reduce."

        Design: Corner/calculations/corner_collection_volumes_and_transit_hours_match_the_formulas
        """
        scenario = build_bank_scenario(
            stage="collected",
            tank_code=None,
            collection_volume_ml=130.0,
            anticoagulant_volume_ml=25.0,
        )

        assert scenario["collection"]["net_volume_ml"] == pytest.approx(105.0, abs=0.01)
        assert scenario["collection"]["collection_volume_ml"] == pytest.approx(130.0, abs=0.01)
        assert scenario["collection"]["anticoagulant_volume_ml"] == pytest.approx(25.0, abs=0.01)
        assert scenario["collection"]["hours_to_receipt"] is None

    def test_nineteen_hours_of_transit_is_persisted_at_two_decimals(self):
        """The elapsed figure is rounded for storage but not for the decision.

        "The same elapsed figure, rounded half up to 2 decimal places, is persisted as
        `hours_to_receipt`; the acceptance decision never reads that rounded value."

        Design: Corner/calculations/corner_collection_volumes_and_transit_hours_match_the_formulas
        """
        scenario = build_bank_scenario(
            stage="received",
            tank_code=None,
            collected_at="2026-08-10T05:00:00Z",
            receipt_clock="2026-08-11T00:00:00Z",
            transport_temp_c=20.0,
        )

        collection = validate_success(
            api_client.get_collection(
                scenario["collection"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert collection["status"] == "RECEIVED"
        assert collection["received_at"].startswith("2026-08-11T00:00:00")
        assert collection["hours_to_receipt"] == pytest.approx(19.00, abs=0.01)
        assert collection["net_volume_ml"] == pytest.approx(105.0, abs=0.01)
        assert collection["transport_temp_c"] == pytest.approx(20.0, abs=0.01)


class TestMaternalPanelConstants:
    def test_a_draw_nine_days_early_is_recorded_but_never_governs(self):
        """The window constant decides the status and the validity constant the shelf life.

        "Otherwise, if `collected_at` falls outside the window running from 7 days before the
        enrollment's `expected_delivery_date` to 7 days after it — a window whose endpoints are
        both inclusive — the panel's `status` is `INVALID`, `overall_result` is null, and the
        record can never govern eligibility for the rest of its life."

        Design: Corner/calculations/corner_maternal_panel_drawn_outside_the_seven_day_window_lands_invalid
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(
            primary_parent_name="Avery Lin", expected_delivery_date="2026-08-10"
        )

        panel = validate_success(
            api_client.create_maternal_screening(
                {
                    "enrollment_id": enrollment["id"],
                    "collected_at": "2026-08-01T00:00:00Z",
                    "hiv_result": "NON_REACTIVE",
                    "hbv_result": "NON_REACTIVE",
                    "hcv_result": "NON_REACTIVE",
                    "htlv_result": "NON_REACTIVE",
                    "syphilis_result": "NON_REACTIVE",
                    "cmv_result": "REACTIVE",
                },
                make_medical_director_headers("md-001"),
            ),
            201,
        )

        assert panel["status"] == "INVALID"
        assert panel["overall_result"] is None
        assert panel["valid_until"].startswith("2027-01-28T00:00:00")
        assert panel["nat_confirmed"] is False

    def test_an_invalid_panel_can_never_govern_an_eligibility_determination(self):
        """A clean but out-of-window panel is worth exactly as much as no panel at all.

        "Panels in `PENDING`, `INVALID` or `EXPIRED` are excluded from that selection entirely,
        which means a newer `INVALID` panel never displaces an older `COMPLETED` one."

        Design: Corner/calculations/corner_maternal_panel_drawn_outside_the_seven_day_window_lands_invalid
        """
        scenario = build_bank_scenario(
            stage="tested",
            tank_code=None,
            program_type="PRIVATE_FAMILY",
            expected_delivery_date="2026-08-10",
            screening_collected_at="2026-08-01T00:00:00Z",
        )
        panel = read_screening(scenario["screening"]["id"])
        assert panel["status"] == "INVALID"
        assert panel["reactive_marker_codes"] == []

        response = api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "no governing panel exists"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_MATERNAL_SCREENING_INCOMPLETE.value, 409)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "PENDING"
        assert unit["eligibility_reason_code"] is None
        assert unit["eligibility_determined_by_user_id"] is None


class TestTheWeightedAcceptanceScore:
    def test_the_three_components_are_weighted_once_and_rounded_once(self):
        """Two saturated components and one fractional one land on exactly 90.40.

        "Rounding order here is not negotiable: the three components and the weighted sum are
        never rounded, and the single rounding happens once, at the very end."

        Design: Corner/calculations/corner_quality_acceptance_score_applies_the_weights_without_intermediate_rounding
        """
        scenario = build_bank_scenario(
            stage="tested",
            tank_code=None,
            program_type="PRIVATE_FAMILY",
            post_volume_ml=25.0,
            post_tnc_millions=1000,
            quality_tnc_millions=1000,
            quality_cd34_thousands=2400,
            quality_viability_pct=88.0,
            quality_volume_ml=25.0,
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)
        assert unit["quality_acceptance_score"] == pytest.approx(
            expected_quality_acceptance_score("PRIVATE_FAMILY", 1000, 2400, 88.0, 25.0), abs=0.01
        )

    def test_the_summary_counts_are_republished_from_the_single_test(self):
        """The unit's characterisation is copied off its one post-processing test.

        "Writing a `POST_PROCESSING` test also republishes the unit's summary counts —
        `post_processing_tnc_millions`, `post_processing_cd34_thousands` and
        `post_processing_viability_pct` are copied from that single test"

        Design: Corner/calculations/corner_quality_acceptance_score_applies_the_weights_without_intermediate_rounding
        """
        scenario = build_bank_scenario(
            stage="tested",
            tank_code=None,
            program_type="PRIVATE_FAMILY",
            post_volume_ml=25.0,
            post_tnc_millions=1000,
            quality_tnc_millions=1000,
            quality_cd34_thousands=2400,
            quality_viability_pct=88.0,
            quality_volume_ml=25.0,
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["post_processing_tnc_millions"] == 1000
        assert unit["post_processing_cd34_thousands"] == 2400
        assert unit["post_processing_viability_pct"] == pytest.approx(88.0, abs=0.01)
        assert unit["post_processing_volume_ml"] == pytest.approx(25.0, abs=0.01)

        determined = determine_eligibility(scenario["unit"]["id"], director_user_id="md-001")
        assert determined["eligibility_status"] == "ELIGIBLE"
        assert determined["eligibility_reason_code"] == "ACCEPTED"

        rows, meta = validate_paginated(
            api_client.list_unit_quality_tests(
                scenario["unit"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["test_kind"] == "POST_PROCESSING"
        assert rows[0]["outcome"] == "PASS"
        assert rows[0]["failure_reason_codes"] == []


def _confirmed_hold_awaiting_a_confirmatory_test():
    """A confirmed hold on an unbilled private unit of 1000 million cells."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-C",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Confirmatory Parent",
        collection_site_code="SITE-03",
        consent_document_hash="hash-cf-v1",
        kit_lot_code="LOT-2026-C",
        courier_tracking_code="TRK-0300",
        post_tnc_millions=1000,
        quality_tnc_millions=1000,
        slot_code="C-01",
    )
    set_clock("2026-08-12T00:00:00Z")
    reservation = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Confirmatory",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-08-20T00:00:00Z",
        hold_until="2026-08-25T00:00:00Z",
    )
    scenario["reservation"] = confirm_reservation(
        reservation["id"], intended_transplant_date="2026-08-21", center_user_id="tc-001"
    )
    return scenario


class TestConfirmatoryFloors:
    def test_a_viability_of_sixty_five_fails_on_exactly_one_code(self):
        """The recovery floor is cleared, so only the viability code may appear.

        "`VIABILITY` is recorded when the measured viability is below 70.0 percent, and
        `RECOVERY` when the derived recovery figure is below 60.0 percent."

        Design: Corner/calculations/corner_confirmatory_viability_below_the_floor_fails_and_blocks_release
        """
        scenario = _confirmed_hold_awaiting_a_confirmatory_test()
        assert scenario["reservation"]["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.86, abs=0.01)
        assert scenario["reservation"]["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1000, 35.0), abs=0.01
        )
        assert scenario["reservation"]["dose_variant_applied"] == "PRE_CRYO"

        confirmatory = record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=700,
            cd34_thousands=2400,
            viability_pct=65.0,
            volume_ml=24.0,
        )

        assert confirmatory["outcome"] == "FAIL"
        assert confirmatory["failure_reason_codes"] == ["VIABILITY"]

    def test_a_failing_test_never_links_itself_so_the_release_is_blocked(self):
        """The missing linkage answers before the dose floor is ever consulted.

        "When a confirmatory test names a reservation and its own outcome is `PASS`, it links
        itself to that reservation as the reservation's `confirmatory_test_id` and the
        reservation's post-thaw dose is computed and persisted."

        Design: Corner/calculations/corner_confirmatory_viability_below_the_floor_fails_and_blocks_release
        """
        scenario = _confirmed_hold_awaiting_a_confirmatory_test()
        record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=700,
            cd34_thousands=2400,
            viability_pct=65.0,
            volume_ml=24.0,
        )

        before = read_reservation(scenario["reservation"]["id"])
        assert before["confirmatory_test_id"] is None
        assert before["post_thaw_dose_x1e7_per_kg"] is None

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt on a failed confirmatory test"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_CONFIRMATORY_TEST_REQUIRED.value, 409)

        after = read_reservation(scenario["reservation"]["id"])
        assert after["status"] == "CONFIRMED"
        assert after["released_at"] is None
        assert after["settlement_total_cents"] is None
        assert after["dose_variant_applied"] == "PRE_CRYO"


class TestPanelAggregation:
    def test_one_indeterminate_marker_dominates_four_non_reactive_ones(self):
        """The worst governing marker wins; the four clean ones do not average it away.

        "Otherwise the panel's `status` is `COMPLETED` and `overall_result` is derived by
        precedence: `REACTIVE` if any governing marker is `REACTIVE`; failing that,
        `INDETERMINATE` if any governing marker is `INDETERMINATE`; failing that,
        `NON_REACTIVE`."

        Design: Corner/calculations/corner_one_indeterminate_marker_makes_the_whole_panel_indeterminate
        """
        scenario = build_bank_scenario(
            stage="tested",
            tank_code=None,
            program_type="PRIVATE_FAMILY",
            screening_markers={"hbv_result": "INDETERMINATE"},
            post_volume_ml=25.0,
            post_tnc_millions=1000,
            quality_tnc_millions=1000,
            quality_cd34_thousands=2400,
            quality_viability_pct=88.0,
            quality_volume_ml=25.0,
        )

        panel = read_screening(scenario["screening"]["id"])
        assert panel["status"] == "COMPLETED"
        assert panel["overall_result"] == "INDETERMINATE"
        assert panel["reactive_marker_codes"] == []

    def test_the_indeterminate_verdict_propagates_onto_the_eligibility_axis(self):
        """The panel branch is taken before the score branch is even considered.

        "If the governing panel's `overall_result` is `INDETERMINATE`, the unit moves `PENDING →
        INDETERMINATE` with an `eligibility_reason_code` of `MATERNAL_INDETERMINATE`."

        Design: Corner/calculations/corner_one_indeterminate_marker_makes_the_whole_panel_indeterminate
        """
        scenario = build_bank_scenario(
            stage="tested",
            tank_code=None,
            program_type="PRIVATE_FAMILY",
            screening_markers={"hbv_result": "INDETERMINATE"},
            post_volume_ml=25.0,
            post_tnc_millions=1000,
            quality_tnc_millions=1000,
            quality_cd34_thousands=2400,
            quality_viability_pct=88.0,
            quality_volume_ml=25.0,
        )

        determined = validate_success(
            api_client.determine_eligibility(
                scenario["unit"]["id"],
                {"decision_note": "panel is indeterminate"},
                make_medical_director_headers("md-001"),
            )
        )

        assert determined["eligibility_status"] == "INDETERMINATE"
        assert determined["eligibility_reason_code"] == "MATERNAL_INDETERMINATE"
        assert determined["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)
        assert determined["processing_status"] == "VOLUME_REDUCED"
        assert determined["availability_status"] == "UNAVAILABLE"
        assert determined["eligibility_determined_by_user_id"] == "md-001"


def _account_with_one_overdue_invoice():
    """A one-year private account carrying a full-year invoice due 31 August."""
    scenario = build_bank_scenario(
        stage="account",
        tank_code=None,
        plan_term_years=1,
        prepaid_through_date="2026-08-01",
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Ladder Parent",
        collection_site_code="SITE-04",
        consent_document_hash="hash-ld-v1",
        billing_contact_email="ladder@example.test",
    )
    scenario["invoice"] = issue_invoice(
        scenario["account"]["id"],
        billing_period_start="2026-08-01",
        billing_period_end="2027-07-31",
        prorated_days=365,
    )
    return scenario


class TestTheNightlyDelinquencyLadder:
    def test_an_invoice_one_hundred_and_twenty_three_days_late_advances_one_rung(self):
        """Both rungs are eligible in the same run and only one may be taken.

        "An `ISSUED` invoice advances to `PAST_DUE` once that count reaches 30; a `PAST_DUE`
        invoice advances to `DELINQUENT` once it reaches 90. Each boundary is inclusive, and **at
        most one stage advance per invoice per run**, so an invoice 95 days past due that is still
        `ISSUED` reaches `PAST_DUE` tonight and `DELINQUENT` only on the next run."

        Design: Corner/calculations/corner_nightly_run_advances_each_invoice_at_most_one_stage
        """
        scenario = _account_with_one_overdue_invoice()
        invoice = scenario["invoice"]
        assert invoice["status"] == "ISSUED"
        assert invoice["base_line_cents"] == 18000
        assert invoice["surcharge_line_cents"] == 0
        assert invoice["admin_line_cents"] == 225
        assert invoice["late_fee_line_cents"] == 0
        assert invoice["amount_due_cents"] == 18225
        assert invoice["due_date"].startswith("2026-08-31")

        set_clock("2027-01-01T00:00:00Z")
        counters = nightly_run()

        assert counters["invoices_advanced_past_due"] == 1
        assert counters["invoices_advanced_delinquent"] == 0

        after = read_invoice(invoice["id"])
        assert after["status"] == "PAST_DUE"
        assert after["late_fee_line_cents"] == 273
        assert after["late_fee_line_cents"] == expected_late_fee(18225)
        assert after["amount_due_cents"] == 18498
        assert after["amount_paid_cents"] == 0
        assert after["stage_advanced_at"].startswith("2027-01-01T00:00:00")

    def test_the_account_follows_its_invoice_by_exactly_one_rung(self):
        """Every other counter in the same run stays at zero.

        "An `ACTIVE` account moves to `PAST_DUE` when one of its invoices reached `PAST_DUE` in
        this run."

        Design: Corner/calculations/corner_nightly_run_advances_each_invoice_at_most_one_stage
        """
        scenario = _account_with_one_overdue_invoice()

        set_clock("2027-01-01T00:00:00Z")
        counters = nightly_run()

        assert counters["accounts_advanced"] == 1
        for name in NIGHTLY_COUNTERS:
            if name not in ("invoices_advanced_past_due", "accounts_advanced"):
                assert counters[name] == 0, name

        account = read_account(scenario["account"]["id"])
        assert account["status"] == "PAST_DUE"
        assert account["balance_cents"] == 18498
        assert account["lifetime_paid_cents"] == 0
        assert account["delinquency_stage_entered_at"].startswith("2027-01-01T00:00:00")
