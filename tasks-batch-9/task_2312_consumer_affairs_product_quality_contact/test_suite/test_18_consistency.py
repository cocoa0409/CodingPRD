"""One write, everything settled: the triage response already carries its own
derived fields, and every follow-up read merely confirms what it said."""

from test_helpers import (
    ILLNESS_S1_COMPLAINT,
    add_complaint,
    add_contact,
    assert_lot_buckets,
    assert_severity,
    assert_two_decimal_value,
    seed_base_world,
    triage,
    validate_paginated,
    validate_success,
)


class TestSingleRequestSettlement:
    def test_a_triage_publishes_its_whole_cascade_in_the_same_response(self, api):
        """Band, lot hold, bucket move, report, sentiment and rate: no second pass.

        PRD: "A great deal of this system's state is derived, and derived state is
        reconciled inside the same request that triggers it — there is no
        deferred or eventual settlement."

        Design: Corner/consistency_model/corner_all_derived_values_are_visible_in_the_same_response
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1"))
        add_contact(
            api,
            world,
            "ct1",
            channel="PHONE",
            raw_message="Ill after eating, saw a doctor.",
        )
        complaint = add_complaint(api, world, "cp1", **ILLNESS_S1_COMPLAINT)
        complaint_id = complaint["id"]
        lot_id = world["lot"]["id"]
        plant_id = world["plant"]["id"]
        consumer_id = world["consumer"]["id"]
        supervisor = world.headers("sup1")
        officer = world.headers("ro1")
        assert_severity(complaint, provisional_score=87.00, provisional_band="S2")
        assert complaint["adjudicated_severity_score"] is None

        before_lot = validate_success(api.get_production_lot(lot_id, supervisor))
        assert before_lot["release_status"] == "RELEASED"
        assert_lot_buckets(before_lot, provisional=1, adjudicated=0)
        before_plant = validate_success(api.get_plant(plant_id, supervisor))
        assert before_plant["oversight_posture"] == "NORMAL"
        assert before_plant["open_investigation_count"] == 0

        # The write itself, read nowhere else.
        adjudicated = triage(api, world, complaint_id, reviewer_note="Severe illness.")
        assert adjudicated["handling_status"] == "TRIAGED"
        assert_severity(
            adjudicated,
            adjudicated_score=93.53,
            adjudicated_band="S1",
            effective_band="S1",
        )
        assert adjudicated["regulatory_status"] == "ESCALATED"
        assert adjudicated["triaged_by_ref"] == world.actor("sup1").id

        after_lot = validate_success(api.get_production_lot(lot_id, supervisor))
        assert after_lot["release_status"] == "HOLD"
        assert_lot_buckets(after_lot, provisional=0, adjudicated=1)

        # Posture reads trend signals only, so a lot hold does not move it.
        after_plant = validate_success(api.get_plant(plant_id, supervisor))
        assert after_plant["oversight_posture"] == "NORMAL"
        assert after_plant["open_investigation_count"] == 0

        reports, report_page = validate_paginated(
            api.list_regulatory_reports(officer)
        )
        assert report_page["total_count"] == 1
        assert reports[0]["complaint_id"] == complaint_id
        assert reports[0]["status"] == "OPEN"

        sentiment = validate_success(
            api.get_consumer_sentiment(consumer_id, supervisor)
        )
        assert_two_decimal_value(sentiment["penalty_total"], 20.00)
        assert_two_decimal_value(sentiment["sentiment_index"], 30.00)
        assert sentiment["complaint_count_in_window"] == 1

        rate = validate_success(
            api.get_lot_complaint_rate(lot_id, supervisor, {"variant": "adjudicated"})
        )
        assert rate["variant"] == "adjudicated"
        assert rate["numerator"] == 1
        assert_two_decimal_value(rate["rate_ppm"], 5.00)
        assert rate["rate_undefined"] is False
