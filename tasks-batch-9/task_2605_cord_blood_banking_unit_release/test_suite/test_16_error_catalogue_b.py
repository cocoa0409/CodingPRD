"""Intake refusals: the temperature bound, standing consent, a contaminated culture and replays."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_bank_scenario,
    make_medical_director_headers,
    make_technologist_headers,
    open_consent_amendment,
    read_collection,
    read_tank,
    read_unit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _collection_waiting_for_a_shipper_that_arrives_too_warm():
    """A perfect collection drawn 19 hours before the receipt clock."""
    scenario = build_bank_scenario(
        stage="collected",
        tank_code=None,
        collected_at="2026-08-10T05:00:00Z",
        collection_clock="2026-08-10T06:00:00Z",
        collection_volume_ml=130.0,
        anticoagulant_volume_ml=25.0,
    )
    set_clock("2026-08-11T00:00:00Z")
    return scenario


class TestTheTransportTemperatureCeiling:
    def test_a_shipper_five_degrees_above_the_maximum_is_refused(self):
        """Every other receipt precondition is satisfied, so only the bound can refuse.

        "Receipt also demands that the kit be `USED`, that the kit's `expires_at` not have passed,
        and that `transport_temp_c` lie within the closed range from 2.0 to 30.0 degrees Celsius —
        a shipper at exactly 2.0 or exactly 30.0 is acceptable, anything outside is
        `ERR_TRANSPORT_TEMP_OUT_OF_RANGE`."

        Design: Corner/errors/corner_transport_temperature_above_the_range_is_refused
        """
        scenario = _collection_waiting_for_a_shipper_that_arrives_too_warm()

        response = api_client.receive_collection(
            scenario["collection"]["id"],
            {"transport_temp_c": 35.0},
            make_technologist_headers("tech-001"),
        )

        validate_error(response, ApiErrorId.ERR_TRANSPORT_TEMP_OUT_OF_RANGE.value, 422)

    def test_the_refused_receipt_persists_nothing_and_mints_no_unit(self):
        """The rejected temperature must not be written and no unit may appear.

        "A successful receipt advances the collection `COLLECTED → RECEIVED`, stamps `received_at`
        from the logical clock, and **mints the CordBloodUnit** — the one and only way a unit ever
        comes into existence, exactly one per collection."

        Design: Corner/errors/corner_transport_temperature_above_the_range_is_refused
        """
        scenario = _collection_waiting_for_a_shipper_that_arrives_too_warm()
        api_client.receive_collection(
            scenario["collection"]["id"],
            {"transport_temp_c": 35.0},
            make_technologist_headers("tech-001"),
        )

        collection = read_collection(scenario["collection"]["id"])
        assert collection["status"] == "COLLECTED"
        assert collection["received_at"] is None
        assert collection["hours_to_receipt"] is None
        assert collection["transport_temp_c"] is None
        assert collection["net_volume_ml"] == pytest.approx(105.0, abs=0.01)

        rows, meta = validate_paginated(
            api_client.list_collection_units(
                scenario["collection"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


def _determined_unit_whose_family_has_reopened_its_consent():
    """A unit that clears every freeze gate except the standing consent."""
    scenario = build_bank_scenario(
        stage="determined",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-cnc-v1",
        kit_lot_code="LOT-2026-N",
        courier_tracking_code="TRK-0800",
    )
    scenario["amendment"] = open_consent_amendment(scenario["enrollment"]["id"])
    return scenario


class TestConsentAsAStandingFreezeGate:
    def test_an_open_amendment_refuses_the_freeze_on_the_consent_rung(self):
        """The unit's own state admits the freeze, so the refusal is not a state error.

        "An in-flight amendment leaves the enrollment in `AMENDMENT_PENDING` and therefore blocks
        all four, and a revoked consent blocks them permanently."

        Design: Corner/errors/corner_cryopreserving_under_an_open_consent_amendment_is_refused
        """
        scenario = _determined_unit_whose_family_has_reopened_its_consent()
        assert scenario["amendment"]["consent_status"] == "AMENDMENT_PENDING"
        assert scenario["amendment"]["consent_amendment_count"] == 1
        assert scenario["unit"]["processing_status"] == "VOLUME_REDUCED"
        assert scenario["unit"]["eligibility_status"] == "ELIGIBLE"
        assert scenario["unit"]["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)

        response = api_client.cryopreserve_unit(
            scenario["unit"]["id"],
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-01",
                "freeze_at": "2026-08-11T02:00:00Z",
            },
            make_technologist_headers("tech-001"),
        )

        validate_error(response, ApiErrorId.ERR_CONSENT_NOT_CURRENT.value, 409)

    def test_the_refused_freeze_consumed_neither_a_slot_nor_an_axis(self):
        """A refusal at rung eleven must leave the tank exactly as it was found.

        "`consent_status` is a cyclic axis independent of the enrollment's operational
        `lifecycle_status`, and four downstream operations require it to be currently `CONSENTED`:
        dispatching a collection kit, recording a collection, publishing a registry listing and
        cryopreserving a unit."

        Design: Corner/errors/corner_cryopreserving_under_an_open_consent_amendment_is_refused
        """
        scenario = _determined_unit_whose_family_has_reopened_its_consent()
        api_client.cryopreserve_unit(
            scenario["unit"]["id"],
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-01",
                "freeze_at": "2026-08-11T02:00:00Z",
            },
            make_technologist_headers("tech-001"),
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "VOLUME_REDUCED"
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["tank_id"] is None
        assert unit["slot_code"] is None
        assert unit["cryopreserved_at"] is None

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 0
        assert tank["status"] == "ONLINE"


def _characterised_unit_with_a_positive_culture():
    """A private unit whose one acceptance test came back contaminated."""
    return build_bank_scenario(
        stage="tested",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        sterility_result="POSITIVE",
        consent_document_hash="hash-ster-v1",
        kit_lot_code="LOT-2026-P",
        courier_tracking_code="TRK-0810",
    )


class TestAPositiveSterilityCulture:
    def test_the_determination_is_refused_although_the_acceptance_test_exists(self):
        """The existence rung is satisfied, so the sterility rung is the one that answers.

        "It is admissible only when the unit's `processing_status` is `VOLUME_REDUCED` or
        `CRYOPRESERVED`, and it requires a governing completed panel, exactly one `POST_PROCESSING`
        quality test on the unit, and a `sterility_result` of `NEGATIVE` on that test."

        Design: Corner/errors/corner_positive_sterility_blocks_the_eligibility_determination
        """
        scenario = _characterised_unit_with_a_positive_culture()
        assert scenario["quality_test"]["outcome"] == "FAIL"
        assert scenario["quality_test"]["failure_reason_codes"] == ["STERILITY"]

        rows, meta = validate_paginated(
            api_client.list_unit_quality_tests(
                scenario["unit"]["id"], make_medical_director_headers("md-002")
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["test_kind"] == "POST_PROCESSING"

        response = api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "culture came back positive"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_STERILITY_POSITIVE.value, 422)

    def test_the_gate_zeroes_the_score_yet_the_counts_are_still_republished(self):
        """A multiplicative gate of zero cannot be confused with a missing measurement.

        "A sterility gate takes the value 0.0 when the `POST_PROCESSING` test's `sterility_result`
        is anything other than `NEGATIVE`, and 1.0 when it is `NEGATIVE`."

        Design: Corner/errors/corner_positive_sterility_blocks_the_eligibility_determination
        """
        scenario = _characterised_unit_with_a_positive_culture()
        api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "culture came back positive"},
            make_medical_director_headers("md-002"),
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["quality_acceptance_score"] == pytest.approx(0.00, abs=0.01)
        assert unit["eligibility_status"] == "PENDING"
        assert unit["eligibility_reason_code"] is None
        assert unit["post_processing_tnc_millions"] == 1000
        assert unit["post_processing_cd34_thousands"] == 2400
        assert unit["post_processing_viability_pct"] == pytest.approx(88.0, abs=0.01)


def _received_collection_with_one_completed_run():
    """Both rows sit one step past the only edge that admits the action being replayed."""
    return build_bank_scenario(
        stage="reduced",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-rep-v1",
        kit_lot_code="LOT-2026-R",
        courier_tracking_code="TRK-0820",
        pre_tnc_millions=1100,
        post_tnc_millions=1000,
        post_volume_ml=25.0,
    )


class TestReplayingAnActionThatAlreadySucceeded:
    def test_receiving_an_already_received_collection_names_the_collection(self):
        """Each row answers with the state code that belongs to its own entity.

        "The error is the one belonging to the entity whose state was wrong —
        `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_UNIT_STATE`, `ERR_INVALID_RESERVATION_STATE`,
        `ERR_INVALID_KIT_STATE`, `ERR_INVALID_COLLECTION_STATE`, `ERR_INVALID_EXCURSION_STATE`,
        `ERR_INVALID_RUN_STATE`, `ERR_INVALID_INVOICE_STATE` or `ERR_INVALID_LISTING_STATE` — each
        at HTTP 409."

        Design: Corner/errors/corner_repeating_receipt_and_run_completion_is_refused_on_both_rows
        """
        scenario = _received_collection_with_one_completed_run()

        replayed = api_client.receive_collection(
            scenario["collection"]["id"],
            {"transport_temp_c": 20.0},
            make_technologist_headers("tech-001"),
        )

        validate_error(replayed, ApiErrorId.ERR_INVALID_COLLECTION_STATE.value, 409)

        rows, meta = validate_paginated(
            api_client.list_collection_units(
                scenario["collection"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["unit"]["id"]

    def test_completing_an_already_completed_run_leaves_its_metrics_alone(self):
        """A refused replay may not recompute the recovery figures it would have written.

        "**Both** outcomes stamp `completed_at` from the logical clock and compute both recovery
        metrics — this symmetry matters, because a failed run is still a measured run."

        Design: Corner/errors/corner_repeating_receipt_and_run_completion_is_refused_on_both_rows
        """
        scenario = _received_collection_with_one_completed_run()
        assert scenario["run"]["status"] == "COMPLETED"

        replayed = api_client.complete_processing_run(
            scenario["run"]["id"],
            {"outcome": "COMPLETED", "post_volume_ml": 30.0, "post_tnc_millions": 900},
            make_technologist_headers("tech-001"),
        )

        validate_error(replayed, ApiErrorId.ERR_INVALID_RUN_STATE.value, 409)

        run = validate_success(
            api_client.get_processing_run(
                scenario["run"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert run["post_volume_ml"] == pytest.approx(25.0, abs=0.01)
        assert run["post_tnc_millions"] == 1000
        assert run["tnc_recovery_pct"] == pytest.approx(90.91, abs=0.01)
        assert run["volume_reduction_pct"] == pytest.approx(76.19, abs=0.01)
