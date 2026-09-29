"""The role model from both sides: each desk on its own work, and neither hat worn twice."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_bank_scenario,
    confirm_reservation,
    issue_invoice,
    make_billing_admin_headers,
    make_collection_site_headers,
    make_medical_director_headers,
    make_parent_guardian_headers,
    make_platform_admin_headers,
    make_registry_operator_headers,
    make_technologist_headers,
    make_transplant_center_headers,
    nightly_run,
    place_reservation,
    post_temperature_reading,
    read_enrollment,
    read_invoice,
    read_reservation,
    read_tank,
    read_unit,
    record_confirmatory_test,
    record_quality_test,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _bank_that_used_every_desk_it_needed():
    """One private unit carried from registration to its slot by eight different desks."""
    return build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        plan_term_years=1,
        prepaid_through_date="2027-08-01",
        billing_contact_email="avery@example.test",
        consent_document_hash="hash-rbac-v1",
        kit_lot_code="LOT-2026-X",
        courier_tracking_code="TRK-0900",
        slot_code="A-01",
    )


class TestEachDeskOnItsOwnWork:
    def test_the_laboratory_and_the_freezer_carry_the_unit_to_its_slot(self):
        """Intake, delivery suite, laboratory, director and engineer each act unrefused.

        "`ProcessingTechnologist` — laboratory staff who receive or reject collections, run volume
        reduction, record quality tests and cryopreserve units; they never determine eligibility and
        never release."

        "`FacilitiesEngineer` — the cryogenic facilities engineer, who commissions tanks, posts
        temperature readings and acknowledges alarms; resolving an excursion is a shared authority
        with the medical director."

        Design: Corner/rbac/corner_every_role_performs_its_own_exclusive_operations
        """
        scenario = _bank_that_used_every_desk_it_needed()

        assert scenario["unit"]["processing_status"] == "CRYOPRESERVED"
        assert scenario["unit"]["availability_status"] == "PRIVATE_STORED"
        assert scenario["unit"]["eligibility_status"] == "ELIGIBLE"
        assert scenario["unit"]["slot_code"] == "A-01"
        assert scenario["tank"]["occupied_slots"] == 1

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-190.0, reading_at="2026-08-11T01:00:00Z"
        )

        tank = read_tank(scenario["tank"]["id"])
        assert tank["status"] == "ONLINE"
        assert tank["last_temperature_c"] == pytest.approx(-190.0, abs=0.01)
        assert tank["occupied_slots"] == 1

        rows, meta = validate_paginated(
            api_client.list_tank_excursions(
                scenario["tank"]["id"], make_platform_admin_headers()
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_billing_desk_the_family_the_centre_and_the_operator_all_act(self):
        """Four more desks, each on an endpoint its own role owns, all of them accepted.

        "`BillingAdministrator` — the private-storage billing desk, which opens accounts, issues
        invoices and posts payments."

        "`TransplantCenter` — an external transplant centre that searches inventory and places,
        confirms, declines or cancels holds for its own patients."

        Design: Corner/rbac/corner_every_role_performs_its_own_exclusive_operations
        """
        scenario = _bank_that_used_every_desk_it_needed()

        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-08-11",
            billing_period_end="2027-08-11",
            prorated_days=365,
        )
        assert invoice["amount_due_cents"] == 18225

        validate_success(
            api_client.pay_storage_invoice(
                invoice["id"],
                {"amount_cents": 18225, "payment_reference": "WIRE-2026-FAMILY"},
                make_parent_guardian_headers(scenario["enrollment"]["id"]),
            )
        )
        assert read_invoice(invoice["id"])["status"] == "PAID"

        hold = place_reservation(
            scenario["unit"]["id"],
            center_user_id="tc-001",
            requesting_center_name="Center One",
            patient_weight_kg=35.0,
            patient_hla_match_count=6,
            hold_from="2026-09-01T00:00:00Z",
            hold_until="2026-09-05T00:00:00Z",
        )
        assert hold["status"] == "PENDING_CONFIRMATORY"
        assert hold["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.86, abs=0.01)

        confirmed = confirm_reservation(hold["id"], intended_transplant_date="2026-09-03")
        assert confirmed["status"] == "CONFIRMED"

        counters = nightly_run()
        assert counters["kits_expired"] == 0
        assert counters["screenings_expired"] == 0
        assert counters["reservations_expired"] == 0
        assert counters["invoices_advanced_past_due"] == 0
        assert counters["invoices_advanced_delinquent"] == 0
        assert counters["accounts_advanced"] == 0
        assert counters["units_flagged_pending_abandonment"] == 0


class TestNoDeskReachesIntoAnother:
    def test_four_crossings_in_the_four_directions_that_matter_are_all_refused(self):
        """Registry into medicine, centre into publication, billing into the freezer, suite into ops.

        "If the headers are well formed but the declared role does not appear in the addressed
        endpoint's authorized-role set, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
        403)."

        Design: Corner/rbac/corner_roles_cannot_reach_across_into_another_roles_exclusive_operations
        """
        scenario = _bank_that_used_every_desk_it_needed()
        unit_id = scenario["unit"]["id"]
        current = unit_version(unit_id, make_technologist_headers("tech-001"))

        registry_into_medicine = api_client.determine_eligibility(
            unit_id, {"decision_note": "not my judgement to make"}, make_registry_operator_headers("ro-001")
        )
        validate_error(registry_into_medicine, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        centre_into_publication = api_client.create_registry_listing(
            {
                "unit_id": unit_id,
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": current,
            },
            make_transplant_center_headers("tc-001"),
        )
        validate_error(centre_into_publication, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        billing_into_the_freezer = api_client.cryopreserve_unit(
            unit_id,
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-02",
                "freeze_at": "2026-08-11T03:00:00Z",
            },
            make_billing_admin_headers("ba-001"),
        )
        validate_error(billing_into_the_freezer, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        suite_into_the_batch = api_client.run_nightly_batch({}, make_collection_site_headers("cs-001"))
        validate_error(suite_into_the_batch, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    def test_the_role_rung_answers_before_the_program_type_and_state_rungs(self):
        """A private unit and a frozen unit would both fail later checks that never run.

        "Role membership is checked before any body parsing, any path lookup and any business rule."

        Design: Corner/rbac/corner_roles_cannot_reach_across_into_another_roles_exclusive_operations
        """
        scenario = _bank_that_used_every_desk_it_needed()
        unit_id = scenario["unit"]["id"]
        technologist = make_technologist_headers("tech-001")
        current = unit_version(unit_id, technologist)

        publication = api_client.create_registry_listing(
            {
                "unit_id": unit_id,
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": current,
            },
            make_transplant_center_headers("tc-001"),
        )
        assert publication.status_code == 403, publication.text
        assert publication.json()["data"]["error_id"] == ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        refreeze = api_client.cryopreserve_unit(
            unit_id,
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-02",
                "freeze_at": "2026-08-11T03:00:00Z",
            },
            make_billing_admin_headers("ba-001"),
        )
        assert refreeze.status_code == 403, refreeze.text
        assert refreeze.json()["data"]["error_id"] == ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        unit = read_unit(unit_id, technologist)
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["availability_status"] == "PRIVATE_STORED"
        assert unit["slot_code"] == "A-01"
        assert unit["version"] == current


def _unit_measured_by_a_technologist_who_also_wears_a_directors_hat():
    """One reduced unit whose acceptance test was posted by the principal `dual-001`."""
    scenario = build_bank_scenario(
        stage="reduced",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-sod-v1",
        kit_lot_code="LOT-2026-S",
        courier_tracking_code="TRK-0910",
        pre_tnc_millions=1100,
        post_tnc_millions=1000,
        post_volume_ml=25.0,
    )
    scenario["quality_test"] = record_quality_test(
        scenario["unit"]["id"],
        technologist_user_id="dual-001",
        test_kind="POST_PROCESSING",
        tnc_millions=1000,
        cd34_thousands=2400,
        viability_pct=88.0,
        volume_ml=25.0,
        sterility_result="NEGATIVE",
    )
    return scenario


class TestTheMeasurerMayNotJudge:
    def test_the_same_principal_wearing_the_directors_hat_is_refused(self):
        """The role is correct on the endpoint, so only the identity comparison can refuse.

        "First, the `MedicalDirector` who determines a unit's eligibility must not be the user
        recorded in `performed_by_user_id` on that unit's `POST_PROCESSING` quality test — the
        technologist who measured the unit may not also judge it."

        Design: Corner/rbac/corner_the_technologist_who_ran_the_test_cannot_also_determine_eligibility
        """
        scenario = _unit_measured_by_a_technologist_who_also_wears_a_directors_hat()
        assert scenario["quality_test"]["performed_by_user_id"] == "dual-001"

        response = api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "self-review"},
            make_medical_director_headers("dual-001"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "PENDING"
        assert unit["eligibility_reason_code"] is None
        assert unit["eligibility_determined_by_user_id"] is None
        assert unit["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)

    def test_a_colleague_succeeds_on_the_identical_payload(self):
        """Nothing about the request changes except the acting identifier.

        "Both comparisons are on `X-User-ID`, both are absolute (there is no override flag, no
        supervisory bypass, and `PlatformAdmin` is not exempt), and both fail with
        `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

        Design: Corner/rbac/corner_the_technologist_who_ran_the_test_cannot_also_determine_eligibility
        """
        scenario = _unit_measured_by_a_technologist_who_also_wears_a_directors_hat()
        api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "self-review"},
            make_medical_director_headers("dual-001"),
        )

        judged = validate_success(
            api_client.determine_eligibility(
                scenario["unit"]["id"],
                {"decision_note": "self-review"},
                make_medical_director_headers("md-002"),
            )
        )
        assert judged["eligibility_status"] == "ELIGIBLE"
        assert judged["eligibility_determined_by_user_id"] == "md-002"

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "ELIGIBLE"
        assert unit["eligibility_reason_code"] == "ACCEPTED"
        assert unit["processing_status"] == "VOLUME_REDUCED"


def _release_ready_hold_judged_by_the_first_director():
    """Every release gate green, on a unit md-001 personally judged eligible."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        director_user_id="md-001",
        consent_document_hash="hash-sod2-v1",
        kit_lot_code="LOT-2026-D",
        courier_tracking_code="TRK-0920",
        slot_code="A-01",
    )
    reservation = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center One",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    scenario["reservation"] = confirm_reservation(
        reservation["id"], intended_transplant_date="2026-09-03", center_user_id="tc-001"
    )
    scenario["confirmatory"] = record_confirmatory_test(
        scenario["unit"]["id"],
        scenario["reservation"]["id"],
        tnc_millions=1000,
        cd34_thousands=2400,
        viability_pct=95.0,
        volume_ml=24.0,
        sterility_result="NEGATIVE",
    )
    return scenario


class TestTheJudgeMayNotShip:
    def test_the_determining_director_is_refused_although_every_other_gate_is_green(self):
        """The dose clears the floor and the test passes, so no later rung could answer.

        "Second, the `MedicalDirector` who authorizes a release must not be the user recorded in
        `eligibility_determined_by_user_id` on the unit — the director who judged the unit may not
        also ship it."

        Design: Corner/rbac/corner_the_determining_director_cannot_authorise_that_units_release
        """
        scenario = _release_ready_hold_judged_by_the_first_director()
        assert scenario["unit"]["eligibility_determined_by_user_id"] == "md-001"
        assert scenario["confirmatory"]["outcome"] == "PASS"

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["post_thaw_dose_x1e7_per_kg"] == pytest.approx(2.71, abs=0.01)

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "shipping the unit I judged"},
            make_medical_director_headers("md-001"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        after = read_reservation(scenario["reservation"]["id"])
        assert after["status"] == "CONFIRMED"
        assert after["released_at"] is None

    def test_the_colleagues_release_ships_the_unit_and_empties_the_slot(self):
        """The identical call from a second director fires the whole release cascade.

        "The unit moves `RESERVED → RELEASED` with `disposition_reason` set to
        `TRANSPLANT_RELEASED` and `disposed_at` stamped from the logical clock; its
        `processing_status` is deliberately left unchanged, because the unit ships still frozen."

        Design: Corner/rbac/corner_the_determining_director_cannot_authorise_that_units_release
        """
        scenario = _release_ready_hold_judged_by_the_first_director()
        api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "shipping the unit I judged"},
            make_medical_director_headers("md-001"),
        )

        released = validate_success(
            api_client.release_reservation(
                scenario["reservation"]["id"],
                {"release_note": "authorised by a second director"},
                make_medical_director_headers("md-002"),
            )
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"].startswith("2026-08-11T00:00:00")
        assert released["dose_variant_applied"] == "POST_THAW"
        assert released["settlement_total_cents"] is None

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "RELEASED"
        assert unit["disposition_reason"] == "TRANSPLANT_RELEASED"
        assert unit["disposed_at"].startswith("2026-08-11T00:00:00")
        assert unit["processing_status"] == "CRYOPRESERVED"

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 0

        enrollment = read_enrollment(scenario["enrollment"]["id"])
        assert enrollment["lifecycle_status"] == "CLOSED"
