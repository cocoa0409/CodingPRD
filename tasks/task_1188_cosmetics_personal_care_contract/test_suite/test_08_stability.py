"""Stability studies: chamber aggregate capacity and required-interval sequencing."""
from test_helpers import (
    ApiErrorId,
    assert_chamber,
    assert_study,
    create_active_formula,
    create_approved_formula,
    create_chamber,
    create_component,
    create_customer,
    create_study,
    record_reading,
    validate_error,
    validate_success,
)


class TestChamberCapacity:
    def test_chamber_aggregate_capacity(self, api, qa_manager_headers):
        """PRD §3.7: "The chamber must have free capacity — its count of
        in-progress studies below `capacity_studies` — failing with
        `ERR_CHAMBER_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §3.7: "a `FAIL` reading at any point ends the study as
        `COMPLETED_FAIL`, freeing one unit of chamber capacity and blocking all
        future batch releases for the formula per §3.6".

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        chamber = create_chamber(chamber_code="CH1", capacity_studies=2)
        study1 = create_study(formula["id"], chamber["id"], "PRESERVATIVE_EFFICACY")
        create_study(formula["id"], chamber["id"], "PRESERVATIVE_EFFICACY")

        resp = api.create_study(
            formula["id"], {"chamber_id": chamber["id"], "study_type": "ACCELERATED"},
            qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED, 409)

        record_reading(study1["id"], 28, "FAIL")  # completes and frees a slot

        study3 = validate_success(api.create_study(
            formula["id"], {"chamber_id": chamber["id"], "study_type": "ACCELERATED"},
            qa_manager_headers), 201)
        assert_study(study3)
        assert study3["status"] == "IN_PROGRESS"

        fetched_chamber = validate_success(api.get_chamber(chamber["id"], qa_manager_headers), 200)
        assert_chamber(fetched_chamber)
        assert fetched_chamber["active_study_count"] == 2

    def test_study_allowed_on_approved_formula(self, api, qa_manager_headers):
        """PRD §3.7: "A study is started for a formula standing `APPROVED` or
        `ACTIVE` by naming a `chamber_id` and a `study_type`."
        PRD §3.7: "A started study begins `IN_PROGRESS` with
        `recorded_interval_count` at zero, and the chamber's count rises by one."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity
        """
        customer = create_customer()
        component = create_component()
        formula = create_approved_formula(customer["id"], component_id=component["id"])
        assert formula["status"] == "APPROVED"
        chamber = create_chamber(chamber_code="CH1", capacity_studies=1)

        study = validate_success(api.create_study(
            formula["id"], {"chamber_id": chamber["id"], "study_type": "ACCELERATED"},
            qa_manager_headers), 201)
        assert_study(study)
        assert study["status"] == "IN_PROGRESS"
        assert study["recorded_interval_count"] == 0
        assert study["required_intervals"] == [30, 60, 90]


class TestReadingSequence:
    def test_reading_interval_out_of_order(self, api, qa_manager_headers):
        """PRD §3.7: "Readings must follow the required sequence exactly: the
        recorded `interval_index` must equal the next required day-index — the
        entry at position `recorded_interval_count` of the study's
        `required_intervals` — failing with `ERR_READING_INTERVAL_OUT_OF_ORDER`
        (HTTP 422)."
        PRD §3.7: "`ACCELERATED` requires days 30, 60, and 90".

        Design: Corner/validations/reading_interval_out_of_order
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        chamber = create_chamber(chamber_code="CH1", capacity_studies=4)
        study = create_study(formula["id"], chamber["id"], "ACCELERATED")

        resp = api.record_reading(study["id"], {"interval_index": 60, "result": "PASS"},
                                  qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_READING_INTERVAL_OUT_OF_ORDER, 422)

        reading = validate_success(api.record_reading(
            study["id"], {"interval_index": 30, "result": "PASS"}, qa_manager_headers), 201)
        assert reading["interval_index"] == 30

        fetched = validate_success(api.get_study(study["id"], qa_manager_headers), 200)
        assert_study(fetched)
        assert fetched["recorded_interval_count"] == 1
        assert fetched["status"] == "IN_PROGRESS"
