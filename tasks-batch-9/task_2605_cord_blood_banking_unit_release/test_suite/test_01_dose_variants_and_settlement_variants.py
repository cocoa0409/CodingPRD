"""Two figures derived twice from identical inputs: the cell dose and the storage settlement."""

import pytest

from test_helpers import (
    build_listed_public_scenario,
    build_private_scenario,
    confirm_reservation,
    dispose_unit,
    expected_confirmatory_recovery_pct,
    expected_post_thaw_dose,
    expected_pre_cryo_dose,
    place_reservation,
    read_account,
    read_reservation,
    read_tank,
    read_unit,
    record_confirmatory_test,
    set_clock,
    validate_success,
    api_client,
    make_medical_director_headers,
)


def _public_unit_with_confirmed_hold():
    """A listed public unit under a confirmed 35.0 kg hold, at clock 2026-08-11T03:00:00Z."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-A",
        capacity_slots=10,
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-01",
        research_use_authorized=True,
        hla_typing_consent=True,
        consent_document_hash="hash-pub-v1",
        screening_markers={"cmv_result": "NON_REACTIVE"},
        slot_code="A-01",
        hla_a="A*01:01",
        hla_b="B*07:02",
        hla_drb1="DRB1*15:01",
    )
    set_clock("2026-08-11T03:00:00Z")
    reservation = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Northside BMT",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    reservation = confirm_reservation(
        reservation["id"], intended_transplant_date="2026-09-03", center_user_id="tc-001"
    )
    scenario["reservation"] = reservation
    return scenario


class TestDoseVariantDivergence:
    def test_confirmatory_test_passes_and_links_itself_to_its_hold(self):
        """A passing confirmatory test attaches to the hold it names.

        "When a confirmatory test names a reservation and its own outcome is `PASS`,
        it links itself to that reservation as the reservation's `confirmatory_test_id`
        and the reservation's post-thaw dose is computed and persisted."

        Design: Difficulty/dual_variant_calc/dose_variant_divergence_pre_cryo_vs_post_thaw
        """
        scenario = _public_unit_with_confirmed_hold()
        test = record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=1200,
            cd34_thousands=2600,
            viability_pct=82.0,
            volume_ml=25.0,
            technologist_user_id="tech-002",
        )

        assert test["outcome"] == "PASS"
        assert test["failure_reason_codes"] == []

        reservation = read_reservation(scenario["reservation"]["id"])
        assert reservation["confirmatory_test_id"] == test["id"]

        unit = read_unit(scenario["unit"]["id"])
        assert unit["post_processing_tnc_millions"] == 1500

    def test_pre_cryo_and_post_thaw_doses_diverge_on_the_same_unit_and_patient(self):
        """The pre-freeze and post-thaw variants legitimately produce different numbers.

        "The `PRE_CRYO` variant is `post_processing_tnc_millions` divided by ten times
        `patient_weight_kg`, rounded half up to two decimals."

        Design: Difficulty/dual_variant_calc/dose_variant_divergence_pre_cryo_vs_post_thaw
        """
        scenario = _public_unit_with_confirmed_hold()
        record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=1200,
            cd34_thousands=2600,
            viability_pct=82.0,
            volume_ml=25.0,
            technologist_user_id="tech-002",
        )

        reservation = read_reservation(scenario["reservation"]["id"])
        assert reservation["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(4.29, abs=0.01)
        assert reservation["post_thaw_dose_x1e7_per_kg"] == pytest.approx(2.81, abs=0.01)
        assert reservation["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1500, 35.0), abs=0.01
        )
        assert reservation["post_thaw_dose_x1e7_per_kg"] == pytest.approx(
            expected_post_thaw_dose(1500, 1200, 82.0, 35.0), abs=0.01
        )
        delta = (
            reservation["pre_cryo_dose_x1e7_per_kg"] - reservation["post_thaw_dose_x1e7_per_kg"]
        )
        assert delta == pytest.approx(1.48, abs=0.01)

    def test_applied_variant_stays_pre_cryo_until_the_release_itself(self):
        """The applied variant does not follow the freshly computed post-thaw figure.

        "search ranking and reservation creation use `PRE_CRYO` only; the release gate
        uses `POST_THAW` only."

        Design: Difficulty/dual_variant_calc/dose_variant_divergence_pre_cryo_vs_post_thaw
        """
        scenario = _public_unit_with_confirmed_hold()
        record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=1200,
            cd34_thousands=2600,
            viability_pct=82.0,
            volume_ml=25.0,
            technologist_user_id="tech-002",
        )

        reservation = read_reservation(scenario["reservation"]["id"])
        assert reservation["dose_variant_applied"] == "PRE_CRYO"
        assert reservation["status"] == "CONFIRMED"

    def test_release_summary_reports_the_recovery_behind_the_post_thaw_figure(self):
        """The pre-flight summary exposes the recovery percentage and the dose gate.

        "It reports `reservation_id`, `unit_id`, both `pre_cryo_dose_x1e7_per_kg` and
        `post_thaw_dose_x1e7_per_kg`, the `confirmatory_recovery_pct` behind the
        post-thaw figure, a boolean `dose_gate_passed`"

        Design: Difficulty/dual_variant_calc/dose_variant_divergence_pre_cryo_vs_post_thaw
        """
        scenario = _public_unit_with_confirmed_hold()
        record_confirmatory_test(
            scenario["unit"]["id"],
            scenario["reservation"]["id"],
            tnc_millions=1200,
            cd34_thousands=2600,
            viability_pct=82.0,
            volume_ml=25.0,
            technologist_user_id="tech-002",
        )

        summary = validate_success(
            api_client.get_release_summary(
                scenario["reservation"]["id"], make_medical_director_headers("md-002")
            )
        )
        assert summary["confirmatory_recovery_pct"] == pytest.approx(80.00, abs=0.01)
        assert summary["confirmatory_recovery_pct"] == pytest.approx(
            expected_confirmatory_recovery_pct(1200, 1500), abs=0.01
        )
        assert summary["dose_gate_passed"] is True
        assert summary["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(4.29, abs=0.01)
        assert summary["post_thaw_dose_x1e7_per_kg"] == pytest.approx(2.81, abs=0.01)


def _stored_private_unit(*, plan_term_years, parent_name, tank, slot_code, kit_lot_code,
                         courier_tracking_code, consent_hash, delivery_mode, email):
    return build_private_scenario(
        tank=tank,
        primary_parent_name=parent_name,
        collection_site_code="SITE-01",
        consent_document_hash=consent_hash,
        plan_term_years=plan_term_years,
        prepaid_through_date="2027-06-30",
        billing_contact_email=email,
        kit_lot_code=kit_lot_code,
        courier_tracking_code=courier_tracking_code,
        delivery_mode=delivery_mode,
        slot_code=slot_code,
    )


class TestStorageFeeSettlementVariants:
    def test_five_year_plan_refunds_the_unused_days_as_prorated_termination(self):
        """A five-year plan refunds the unused prepaid days when the unit leaves.

        "prorated termination (`PRORATED_TERMINATION`), when `plan_term_years` is 5 or 18,
        refunds 18000 cents multiplied by those unused days divided by 365, rounded half
        up to whole cents."

        Design: Difficulty/dual_variant_calc/storage_fee_variant_prorated_termination_vs_anniversary_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        from test_helpers import commission_tank

        tank = commission_tank(tank_code="TANK-B", tank_class="STANDARD", capacity_slots=20)
        five_year = _stored_private_unit(
            plan_term_years=5,
            parent_name="Five Year Parent",
            tank=tank,
            slot_code="B-01",
            kit_lot_code="LOT-2026-B",
            courier_tracking_code="TRK-0002",
            consent_hash="hash-f5-v1",
            delivery_mode="VAGINAL",
            email="f5@example.com",
        )

        set_clock("2026-12-08T00:00:00Z")
        dispose_unit(
            five_year["unit"]["id"],
            reason="QUALITY_FAILURE",
            director_user_id="md-002",
            note="late audit finding",
        )

        account = read_account(five_year["account"]["id"])
        assert account["last_settlement_total_cents"] == -7560
        assert account["balance_cents"] == 0
        assert read_unit(five_year["unit"]["id"])["availability_status"] == "DISPOSED"

    def test_one_year_plan_refunds_nothing_at_all_as_anniversary_accrual(self):
        """A one-year plan refunds nothing, however early the unit leaves inventory.

        "anniversary accrual (`ANNIVERSARY_ACCRUAL`), when `plan_term_years` is 1, refunds
        nothing at all, however early in the period the unit leaves inventory"

        Design: Difficulty/dual_variant_calc/storage_fee_variant_prorated_termination_vs_anniversary_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        from test_helpers import commission_tank

        tank = commission_tank(tank_code="TANK-B", tank_class="STANDARD", capacity_slots=20)
        one_year = _stored_private_unit(
            plan_term_years=1,
            parent_name="One Year Parent",
            tank=tank,
            slot_code="B-02",
            kit_lot_code="LOT-2026-C",
            courier_tracking_code="TRK-0003",
            consent_hash="hash-f1-v1",
            delivery_mode="CESAREAN",
            email="f1@example.com",
        )

        set_clock("2026-12-08T00:00:00Z")
        dispose_unit(
            one_year["unit"]["id"],
            reason="QUALITY_FAILURE",
            director_user_id="md-002",
            note="late audit finding",
        )

        account = read_account(one_year["account"]["id"])
        assert account["last_settlement_total_cents"] == 2500
        assert account["balance_cents"] == 0
        assert read_unit(one_year["unit"]["id"])["availability_status"] == "DISPOSED"

    def test_two_identical_accounts_settle_ten_thousand_and_sixty_cents_apart(self):
        """Identical prepaid dates settle differently because the plan term selects the variant.

        "Then the variant is selected by the account's `plan_term_years`"

        Design: Difficulty/dual_variant_calc/storage_fee_variant_prorated_termination_vs_anniversary_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        from test_helpers import commission_tank

        tank = commission_tank(tank_code="TANK-B", tank_class="STANDARD", capacity_slots=20)
        five_year = _stored_private_unit(
            plan_term_years=5,
            parent_name="Five Year Parent",
            tank=tank,
            slot_code="B-01",
            kit_lot_code="LOT-2026-B",
            courier_tracking_code="TRK-0002",
            consent_hash="hash-f5-v1",
            delivery_mode="VAGINAL",
            email="f5@example.com",
        )
        one_year = _stored_private_unit(
            plan_term_years=1,
            parent_name="One Year Parent",
            tank=tank,
            slot_code="B-02",
            kit_lot_code="LOT-2026-C",
            courier_tracking_code="TRK-0003",
            consent_hash="hash-f1-v1",
            delivery_mode="CESAREAN",
            email="f1@example.com",
        )

        set_clock("2026-12-08T00:00:00Z")
        for scenario in (five_year, one_year):
            dispose_unit(
                scenario["unit"]["id"],
                reason="QUALITY_FAILURE",
                director_user_id="md-002",
                note="late audit finding",
            )

        settlement_five = read_account(five_year["account"]["id"])["last_settlement_total_cents"]
        settlement_one = read_account(one_year["account"]["id"])["last_settlement_total_cents"]
        assert settlement_five == -7560
        assert settlement_one == 2500
        assert settlement_one - settlement_five == 10060

        tank_after = read_tank(tank["id"])
        assert tank_after["occupied_slots"] == 0
