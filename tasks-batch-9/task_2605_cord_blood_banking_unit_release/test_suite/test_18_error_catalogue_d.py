"""Late gates: a thin post-thaw dose, a doubly refused listing, an unpaid family and a lapsed panel."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_bank_scenario,
    confirm_reservation,
    expected_post_thaw_dose,
    issue_invoice,
    make_medical_director_headers,
    make_registry_operator_headers,
    make_transplant_center_headers,
    nightly_run,
    place_reservation,
    read_account,
    read_listing,
    read_reservation,
    read_screening,
    read_unit,
    record_confirmatory_test,
    set_clock,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _confirmed_hold_on_an_unbilled_private_unit():
    """A frozen private unit with no storage account and one confirmed hold."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-thin-v1",
        kit_lot_code="LOT-2026-T",
        courier_tracking_code="TRK-0840",
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
    return scenario


def _a_passing_but_thin_confirmatory_test(scenario):
    """Seventy percent recovery at seventy-five percent viability: a pass worth 1.50."""
    return record_confirmatory_test(
        scenario["unit"]["id"],
        scenario["reservation"]["id"],
        tnc_millions=700,
        cd34_thousands=1800,
        viability_pct=75.0,
        volume_ml=24.0,
        sterility_result="NEGATIVE",
    )


class TestAPassingTestThatIsStillTooThin:
    def test_the_release_is_refused_on_the_dose_floor_and_not_on_the_missing_test(self):
        """The linkage gate is satisfied by the passing test, so the dose gate answers.

        "The hold's `post_thaw_dose_x1e7_per_kg` must be at least 2.50, inclusive at the boundary,
        and a shortfall is `ERR_DOSE_BELOW_MINIMUM`."

        Design: Corner/errors/corner_confirmatory_test_that_passes_can_still_be_too_thin_to_release
        """
        scenario = _confirmed_hold_on_an_unbilled_private_unit()
        confirmatory = _a_passing_but_thin_confirmatory_test(scenario)
        assert confirmatory["outcome"] == "PASS"
        assert confirmatory["failure_reason_codes"] == []

        linked = read_reservation(scenario["reservation"]["id"])
        assert linked["confirmatory_test_id"] == confirmatory["id"]

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt on a thin post-thaw dose"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_DOSE_BELOW_MINIMUM.value, 422)

    def test_the_pre_flight_summary_names_the_same_gate_without_shipping_anything(self):
        """Reading the summary must mutate nothing while predicting the exact refusal.

        "It reports `reservation_id`, `unit_id`, both `pre_cryo_dose_x1e7_per_kg` and
        `post_thaw_dose_x1e7_per_kg`, the `confirmatory_recovery_pct` behind the post-thaw figure, a
        boolean `dose_gate_passed`, a boolean `confirmatory_test_present`, the governing
        `maternal_result`, the holding `tank_status`, the `account_balance_cents`, the
        `projected_settlement_total_cents` the release would post, and a `blocking_error_id` naming
        the first gate that would refuse the release under the §2.9 order — null when no gate would
        refuse it."

        Design: Corner/errors/corner_confirmatory_test_that_passes_can_still_be_too_thin_to_release
        """
        scenario = _confirmed_hold_on_an_unbilled_private_unit()
        _a_passing_but_thin_confirmatory_test(scenario)

        summary = validate_success(
            api_client.get_release_summary(
                scenario["reservation"]["id"], make_medical_director_headers("md-002")
            )
        )

        assert summary["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.86, abs=0.01)
        assert summary["confirmatory_recovery_pct"] == pytest.approx(70.00, abs=0.01)
        assert summary["post_thaw_dose_x1e7_per_kg"] == pytest.approx(1.50, abs=0.01)
        assert summary["post_thaw_dose_x1e7_per_kg"] == pytest.approx(
            expected_post_thaw_dose(1000, 700, 75.0, 35.0), abs=0.01
        )
        assert summary["dose_gate_passed"] is False
        assert summary["confirmatory_test_present"] is True
        assert summary["blocking_error_id"] == ApiErrorId.ERR_DOSE_BELOW_MINIMUM.value

        api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt on a thin post-thaw dose"},
            make_medical_director_headers("md-002"),
        )

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["status"] == "CONFIRMED"
        assert hold["released_at"] is None
        assert hold["settlement_total_cents"] is None

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "RESERVED"
        assert unit["disposition_reason"] is None
        assert unit["disposed_at"] is None


def _public_unit_whose_listing_has_been_pulled():
    """A listed public unit taken off the market by the registry desk."""
    scenario = build_bank_scenario(
        stage="listed",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PUBLIC_DONATION",
        hla_typing_consent=True,
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-02",
        consent_document_hash="hash-susp-v1",
        kit_lot_code="LOT-2026-L",
        courier_tracking_code="TRK-0850",
        slot_code="A-01",
    )
    scenario["listing"] = validate_success(
        api_client.suspend_registry_listing(
            scenario["listing"]["id"],
            {"suspension_note": "registry audit in progress"},
            make_registry_operator_headers("ro-001"),
        )
    )
    scenario["unit"] = read_unit(scenario["unit"]["id"])
    return scenario


class TestASuspendedListingRefusesBothWays:
    def test_suspending_a_listing_that_is_already_suspended_is_refused(self):
        """Only an active listing may be pulled, so the replay has no admissible edge.

        "The registry desk suspends an `ACTIVE` listing — optionally recording a `suspension_note` —
        when HLA re-typing or a registry audit requires the unit off the market."

        "The error is the one belonging to the entity whose state was wrong —
        `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_UNIT_STATE`, `ERR_INVALID_RESERVATION_STATE`,
        `ERR_INVALID_KIT_STATE`, `ERR_INVALID_COLLECTION_STATE`, `ERR_INVALID_EXCURSION_STATE`,
        `ERR_INVALID_RUN_STATE`, `ERR_INVALID_INVOICE_STATE` or `ERR_INVALID_LISTING_STATE` — each
        at HTTP 409."

        Design: Corner/errors/corner_suspended_listing_cannot_be_suspended_again_nor_republished
        """
        scenario = _public_unit_whose_listing_has_been_pulled()
        assert scenario["listing"]["listing_status"] == "SUSPENDED"
        assert scenario["listing"]["suspension_reason_code"] == "REGISTRY_HOLD"
        assert scenario["unit"]["availability_status"] == "UNAVAILABLE"

        response = api_client.suspend_registry_listing(
            scenario["listing"]["id"],
            {"suspension_note": "a second pull"},
            make_registry_operator_headers("ro-001"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_LISTING_STATE.value, 409)

    def test_a_fresh_publication_is_refused_by_the_live_listing_rung(self):
        """The version is re-read, so a stale-version refusal cannot be mistaken for this one.

        "The unit must have no existing listing whose `listing_status` is `ACTIVE` or `SUSPENDED`,
        and a second attempt while such a listing lives is `ERR_DUPLICATE_ACTIVE_LISTING`."

        Design: Corner/errors/corner_suspended_listing_cannot_be_suspended_again_nor_republished
        """
        scenario = _public_unit_whose_listing_has_been_pulled()
        operator = make_registry_operator_headers("ro-001")
        current = unit_version(scenario["unit"]["id"], operator)

        response = api_client.create_registry_listing(
            {
                "unit_id": scenario["unit"]["id"],
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": current,
            },
            operator,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_LISTING.value, 409)

        listing = read_listing(scenario["listing"]["id"])
        assert listing["listing_status"] == "SUSPENDED"
        assert listing["suspension_reason_code"] == "REGISTRY_HOLD"
        assert listing["potency_grade"] == "A"

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["version"] == current


def _confirmed_hold_on_a_unit_whose_family_owes_a_year():
    """A billed private unit, one wholly unpaid invoice and a passing confirmatory test."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        plan_term_years=1,
        prepaid_through_date="2027-08-01",
        billing_contact_email="avery@example.test",
        consent_document_hash="hash-owed-v1",
        kit_lot_code="LOT-2026-B",
        courier_tracking_code="TRK-0860",
        slot_code="A-01",
    )
    scenario["invoice"] = issue_invoice(
        scenario["account"]["id"],
        billing_period_start="2026-08-11",
        billing_period_end="2027-08-11",
        prorated_days=365,
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


class TestAnUnpaidFamilyBlocksTheShipment:
    def test_every_clinical_gate_passes_and_the_fiscal_one_refuses(self):
        """The account never entered a delinquency stage, so this is not the delinquency rung.

        "And where the unit has a `storage_account_id`, that account's `status` must not be
        `DELINQUENT`, `ABANDONMENT_NOTICE` or `ABANDONED`, and its `balance_cents` must be exactly
        0; because an account only reaches those three statuses while it carries a positive
        residual, a release refused on either ground reports `ERR_OUTSTANDING_BALANCE`, which is the
        fiscal rung scoped to release."

        Design: Corner/errors/corner_release_is_blocked_by_an_unpaid_invoice_on_the_family_account
        """
        scenario = _confirmed_hold_on_a_unit_whose_family_owes_a_year()
        assert scenario["invoice"]["amount_due_cents"] == 18225
        assert scenario["confirmatory"]["outcome"] == "PASS"

        ledger = read_account(scenario["account"]["id"])
        assert ledger["balance_cents"] == 18225
        assert ledger["status"] == "ACTIVE"

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt against an unpaid account"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_OUTSTANDING_BALANCE.value, 402)

    def test_the_summary_predicts_the_fiscal_refusal_and_the_unit_stays_in_its_slot(self):
        """Both dose gates are green, which isolates the balance as the sole blocker.

        "A successful release moves the hold `CONFIRMED → RELEASED`, stamps `released_at` from the
        logical clock, sets `dose_variant_applied` to `POST_THAW`, and computes and persists
        `settlement_total_cents` on the hold while mirroring the same figure to the account's
        `last_settlement_total_cents`."

        Design: Corner/errors/corner_release_is_blocked_by_an_unpaid_invoice_on_the_family_account
        """
        scenario = _confirmed_hold_on_a_unit_whose_family_owes_a_year()

        summary = validate_success(
            api_client.get_release_summary(
                scenario["reservation"]["id"], make_medical_director_headers("md-002")
            )
        )
        assert summary["post_thaw_dose_x1e7_per_kg"] == pytest.approx(2.71, abs=0.01)
        assert summary["post_thaw_dose_x1e7_per_kg"] == pytest.approx(
            expected_post_thaw_dose(1000, 1000, 95.0, 35.0), abs=0.01
        )
        assert summary["confirmatory_recovery_pct"] == pytest.approx(100.00, abs=0.01)
        assert summary["dose_gate_passed"] is True
        assert summary["confirmatory_test_present"] is True
        assert summary["maternal_result"] == "NON_REACTIVE"
        assert summary["tank_status"] == "ONLINE"
        assert summary["account_balance_cents"] == 18225
        assert summary["blocking_error_id"] == ApiErrorId.ERR_OUTSTANDING_BALANCE.value

        api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt against an unpaid account"},
            make_medical_director_headers("md-002"),
        )

        ledger = read_account(scenario["account"]["id"])
        assert ledger["status"] == "ACTIVE"
        assert ledger["balance_cents"] == 18225
        assert ledger["last_settlement_total_cents"] is None

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "RESERVED"
        assert unit["disposition_reason"] is None
        assert unit["tank_id"] == scenario["tank"]["id"]
        assert unit["slot_code"] == "A-01"


def _stored_unit_whose_panel_lapsed_overnight():
    """A frozen private unit whose only panel expired one day before the sweep."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        screening_collected_at="2026-08-10T05:00:00Z",
        consent_document_hash="hash-lapse-v1",
        kit_lot_code="LOT-2026-E",
        courier_tracking_code="TRK-0870",
        slot_code="A-01",
    )
    set_clock("2027-02-07T00:00:00Z")
    scenario["counters"] = nightly_run()
    return scenario


class TestAHoldOnAUnitWhosePanelLapsed:
    def test_the_sweep_revokes_eligibility_without_anybody_asking(self):
        """The batch alone moves the unit off `ELIGIBLE`; no human decision is involved.

        "Beyond the `ELIGIBLE → INELIGIBLE` move driven by a newly reactive panel, an `ELIGIBLE`
        unit moves `ELIGIBLE → INDETERMINATE` with an `eligibility_reason_code` of
        `SCREENING_EXPIRED` when the nightly batch expires the enrollment's governing panel — that
        is, when the logical clock passes the panel's `valid_until` and the panel moves `COMPLETED →
        EXPIRED`."

        Design: Corner/errors/corner_reservation_on_a_unit_whose_screening_lapsed_overnight_is_refused
        """
        scenario = _stored_unit_whose_panel_lapsed_overnight()

        assert scenario["counters"]["screenings_expired"] == 1
        assert scenario["counters"]["kits_expired"] == 0
        assert scenario["counters"]["reservations_expired"] == 0
        assert scenario["counters"]["accounts_advanced"] == 0
        assert scenario["counters"]["units_flagged_pending_abandonment"] == 0

        panel = read_screening(scenario["screening"]["id"])
        assert panel["status"] == "EXPIRED"
        assert panel["valid_until"].startswith("2027-02-06T05:00:00")
        assert panel["overall_result"] == "NON_REACTIVE"

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "INDETERMINATE"
        assert unit["eligibility_reason_code"] == "SCREENING_EXPIRED"
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["availability_status"] == "PRIVATE_STORED"

    def test_the_hold_is_refused_on_eligibility_rather_than_on_the_panel_itself(self):
        """Hold placement is not one of the operations the maternal-panel rung guards.

        "**Unit eligibility** — on reservation creation, registry publication and release, the
        unit's `eligibility_status` is `ELIGIBLE`."

        "Finally, `valid_until` is set to `collected_at` plus 180 days — the panel's shelf life,
        roughly six months of clinical currency."

        Design: Corner/errors/corner_reservation_on_a_unit_whose_screening_lapsed_overnight_is_refused
        """
        scenario = _stored_unit_whose_panel_lapsed_overnight()
        centre = make_transplant_center_headers("tc-001")

        response = api_client.create_reservation(
            {
                "unit_id": scenario["unit"]["id"],
                "requesting_center_name": "Center One",
                "patient_weight_kg": 35.0,
                "patient_hla_match_count": 6,
                "hold_from": "2027-03-01T00:00:00Z",
                "hold_until": "2027-03-05T00:00:00Z",
                "expected_unit_version": unit_version(scenario["unit"]["id"], centre),
            },
            centre,
        )

        validate_error(response, ApiErrorId.ERR_UNIT_NOT_ELIGIBLE.value, 409)

        rows, meta = validate_paginated(
            api_client.list_reservations(centre, {"unit_id": scenario["unit"]["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
