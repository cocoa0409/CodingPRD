"""When several guards fail at once, the earliest guard in the fixed order answers."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_billed_private_scenario,
    build_listed_public_scenario,
    confirm_reservation,
    make_medical_director_headers,
    make_transplant_center_headers,
    nightly_run,
    place_reservation,
    read_account,
    read_reservation,
    read_listing,
    read_screening,
    read_unit,
    set_clock,
    unit_version,
    validate_error,
    validate_success,
)


def _delinquent_private_unit():
    """A stored private unit whose account has been driven to delinquency."""
    scenario = build_billed_private_scenario(
        plan_term_years=1,
        tank_code="TANK-G",
        capacity_slots=5,
        primary_parent_name="Priority Parent",
        collection_site_code="SITE-07",
        consent_document_hash="hash-pri-v1",
        slot_code="G-01",
        invoice_clock="2026-09-01T00:00:00Z",
        billing_period_start="2026-09-01",
        billing_period_end="2027-08-31",
        prorated_days=365,
    )
    set_clock("2026-11-01T00:00:00Z")
    nightly_run()
    set_clock("2027-01-01T00:00:00Z")
    nightly_run()
    return scenario


class TestUnitStateOutranksAccountStanding:
    def test_both_grounds_for_refusal_are_genuinely_present(self):
        """The unit is flagged for abandonment and the account is delinquent at once.

        "from `DELINQUENT` and from `ABANDONMENT_NOTICE` the cure additionally returns every
        unit of that account whose `availability_status` is `PENDING_ABANDONMENT` to
        `PRIVATE_STORED`."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_409_outranks_account_delinquent_402_on_reservation
        """
        scenario = _delinquent_private_unit()

        assert read_unit(scenario["unit"]["id"])["availability_status"] == "PENDING_ABANDONMENT"
        assert read_account(scenario["account"]["id"])["status"] == "DELINQUENT"

    def test_the_state_rung_answers_before_the_fiscal_rung(self):
        """State admissibility sits at rung 9 and account standing at rung 33.

        "the **first** check that fails determines both the error identifier and the HTTP
        status; no later check may mask an earlier one, and no earlier check may be skipped
        because a later one would also fail."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_409_outranks_account_delinquent_402_on_reservation
        """
        scenario = _delinquent_private_unit()
        headers = make_transplant_center_headers("tc-004")
        version = unit_version(scenario["unit"]["id"], headers)

        response = api_client.create_reservation(
            {
                "unit_id": scenario["unit"]["id"],
                "requesting_center_name": "Center Priority",
                "patient_weight_kg": 20.0,
                "patient_hla_match_count": 6,
                "hold_from": "2027-03-01T00:00:00Z",
                "hold_until": "2027-03-05T00:00:00Z",
                "expected_unit_version": version,
            },
            headers,
        )

        assert response.status_code == 409
        body = validate_error(response, ApiErrorId.ERR_INVALID_UNIT_STATE.value, 409)
        assert body["error_id"] != ApiErrorId.ERR_ACCOUNT_DELINQUENT.value

    def test_the_refused_hold_is_never_written(self):
        """A refused placement leaves no hold behind on the unit.

        "Holds are browsable by `unit_id`, by `superseded_by_reservation_id`, by
        `confirmatory_test_id` and by `status`."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_409_outranks_account_delinquent_402_on_reservation
        """
        scenario = _delinquent_private_unit()
        headers = make_transplant_center_headers("tc-004")
        version = unit_version(scenario["unit"]["id"], headers)

        api_client.create_reservation(
            {
                "unit_id": scenario["unit"]["id"],
                "requesting_center_name": "Center Priority",
                "patient_weight_kg": 20.0,
                "patient_hla_match_count": 6,
                "hold_from": "2027-03-01T00:00:00Z",
                "hold_until": "2027-03-05T00:00:00Z",
                "expected_unit_version": version,
            },
            headers,
        )

        rows = validate_success(
            api_client.list_reservations(headers, {"unit_id": scenario["unit"]["id"]})
        )
        assert rows == []


def _reactive_panel_after_confirmation():
    """A confirmed hold whose governing maternal panel is then amended to reactive."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-H",
        capacity_slots=5,
        primary_parent_name="Reactive Parent",
        collection_site_code="SITE-08",
        hla_typing_consent=True,
        consent_document_hash="hash-rea-v1",
        slot_code="H-01",
    )
    reservation = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Reactive",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    scenario["reservation"] = confirm_reservation(
        reservation["id"], intended_transplant_date="2026-09-03", center_user_id="tc-001"
    )
    set_clock("2026-08-12T00:00:00Z")
    validate_success(
        api_client.amend_maternal_screening(
            scenario["screening"]["id"],
            {"hiv_result": "REACTIVE", "nat_confirmed": True},
            make_medical_director_headers("md-001"),
        )
    )
    return scenario


class TestMaternalReactiveOutranksConfirmatoryRequirement:
    def test_the_amended_panel_governs_as_reactive(self):
        """An amendment to a reactive marker turns the whole panel reactive.

        "`overall_result` is derived by precedence: `REACTIVE` if any governing marker is
        `REACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/maternal_reactive_422_outranks_confirmatory_required_409_on_release
        """
        scenario = _reactive_panel_after_confirmation()

        screening = read_screening(scenario["screening"]["id"])
        assert screening["overall_result"] == "REACTIVE"
        assert screening["status"] == "COMPLETED"

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "INELIGIBLE"
        assert unit["eligibility_reason_code"] == "MATERNAL_REACTIVE"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "SUSPENDED"
        assert (
            read_listing(scenario["listing"]["id"])["suspension_reason_code"]
            == "MATERNAL_REACTIVE"
        )

    def test_the_maternal_rung_answers_before_the_confirmatory_rung(self):
        """Rung 14 refuses the release although no confirmatory test exists either.

        "The enrollment's governing panel — the latest `COMPLETED` maternal screening — must
        have an `overall_result` of exactly `NON_REACTIVE`, so that both `REACTIVE` and
        `INDETERMINATE` block the release."

        Design: Difficulty/priority_pair_validation_conflict/maternal_reactive_422_outranks_confirmatory_required_409_on_release
        """
        scenario = _reactive_panel_after_confirmation()
        assert read_reservation(scenario["reservation"]["id"])["confirmatory_test_id"] is None

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "priority ladder probe"},
            make_medical_director_headers("md-002"),
        )

        assert response.status_code == 422
        body = validate_error(response, ApiErrorId.ERR_MATERNAL_SCREENING_REACTIVE.value, 422)
        assert body["error_id"] != ApiErrorId.ERR_CONFIRMATORY_TEST_REQUIRED.value
        assert body["error_id"] != ApiErrorId.ERR_UNIT_NOT_ELIGIBLE.value

    def test_the_refused_release_changes_nothing(self):
        """A release refused at the maternal rung leaves the hold and the unit untouched.

        "**Release for transplant** is the irreversible act, performed by a `MedicalDirector`
        with an optional `release_note`, and it is gated on eight conditions, all of which
        must hold."

        Design: Difficulty/priority_pair_validation_conflict/maternal_reactive_422_outranks_confirmatory_required_409_on_release
        """
        scenario = _reactive_panel_after_confirmation()

        api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "priority ladder probe"},
            make_medical_director_headers("md-002"),
        )

        reservation = read_reservation(scenario["reservation"]["id"])
        assert reservation["status"] == "CONFIRMED"
        assert reservation["released_at"] is None
        assert reservation["settlement_total_cents"] is None

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "RESERVED"
        assert unit["eligibility_determined_by_user_id"] == "md-001"
