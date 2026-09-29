"""One event, many rows: the alarm cascade and the delinquency cascade."""

import pytest

from test_helpers import (
    build_billed_private_scenario,
    build_listed_public_scenario,
    latest_excursion,
    nightly_run,
    place_reservation,
    post_temperature_reading,
    read_account,
    read_invoice,
    read_listing,
    read_reservation,
    read_tank,
    read_unit,
    set_clock,
)


def _alarmed_tank_scenario():
    """A listed public unit under one pending hold, then a warm reading on its tank."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-E",
        capacity_slots=5,
        primary_parent_name="Alarm Parent",
        collection_site_code="SITE-05",
        hla_typing_consent=True,
        consent_document_hash="hash-al-v1",
        courier_tracking_code="TRK-0500",
        slot_code="E-01",
    )
    scenario["reservation"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Alarm",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    set_clock("2026-08-12T00:00:00Z")
    return scenario


class TestTemperatureAlarmCascade:
    def test_a_warm_reading_alarms_the_tank_and_opens_one_excursion(self):
        """The reading refreshes the tank's telemetry and opens the excursion.

        "A reading strictly warmer than −150.0 degrees Celsius is an alarm condition: the tank
        moves `ONLINE → ALARM`"

        Design: Difficulty/transitive_cascade/temperature_alarm_quarantine_cascade_depth4
        """
        scenario = _alarmed_tank_scenario()

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-12T00:00:00Z"
        )

        tank = read_tank(scenario["tank"]["id"])
        assert tank["status"] == "ALARM"
        assert tank["last_temperature_c"] == pytest.approx(-140.0, abs=0.01)
        assert tank["last_reading_at"].startswith("2026-08-12T00:00:00")

        excursion = latest_excursion(scenario["tank"]["id"])
        assert excursion["status"] == "OPEN"
        assert excursion["detected_at"].startswith("2026-08-12T00:00:00")
        assert excursion["peak_temperature_c"] == pytest.approx(-140.0, abs=0.01)

    def test_the_quarantine_moves_only_the_availability_axis_of_the_unit(self):
        """Level two of the cascade quarantines the tank's stored units.

        "Every unit in the alarmed tank whose `availability_status` is `PRIVATE_STORED` or
        `LISTED` moves to `QUARANTINED` with a `quarantine_reason_code` of `EXCURSION_OPEN`"

        Design: Difficulty/transitive_cascade/temperature_alarm_quarantine_cascade_depth4
        """
        scenario = _alarmed_tank_scenario()

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-12T00:00:00Z"
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "QUARANTINED"
        assert unit["quarantine_reason_code"] == "EXCURSION_OPEN"
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["eligibility_status"] == "ELIGIBLE"

    def test_the_listing_suspends_and_its_pending_hold_is_cancelled(self):
        """Levels three and four reach the listing and then the holds standing on it.

        "And for each listing thereby suspended, every hold on that unit in
        `PENDING_CONFIRMATORY` is cancelled with a `cancellation_reason_code` of
        `LISTING_SUSPENDED`"

        Design: Difficulty/transitive_cascade/temperature_alarm_quarantine_cascade_depth4
        """
        scenario = _alarmed_tank_scenario()

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-12T00:00:00Z"
        )

        listing = read_listing(scenario["listing"]["id"])
        assert listing["listing_status"] == "SUSPENDED"
        assert listing["suspension_reason_code"] == "UNIT_QUARANTINED"

        reservation = read_reservation(scenario["reservation"]["id"], center_user_id="tc-001")
        assert reservation["status"] == "CANCELLED"
        assert reservation["cancellation_reason_code"] == "LISTING_SUSPENDED"

    def test_a_quarantined_unit_keeps_occupying_its_slot(self):
        """The cascade never frees cryogenic capacity.

        "Quarantined units keep occupying their slots throughout, so the tank's
        `occupied_slots` does not change."

        Design: Difficulty/transitive_cascade/temperature_alarm_quarantine_cascade_depth4
        """
        scenario = _alarmed_tank_scenario()
        before = read_tank(scenario["tank"]["id"])["occupied_slots"]

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-12T00:00:00Z"
        )

        assert before == 1
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1


def _delinquency_scenario():
    """A stored private unit whose one-year account carries a full-year invoice."""
    return build_billed_private_scenario(
        plan_term_years=1,
        tank_code="TANK-F",
        capacity_slots=5,
        primary_parent_name="Delinquent Parent",
        collection_site_code="SITE-06",
        consent_document_hash="hash-del-v1",
        slot_code="F-01",
        invoice_clock="2026-09-01T00:00:00Z",
        billing_period_start="2026-09-01",
        billing_period_end="2027-08-31",
        prorated_days=365,
    )


class TestNightlyDelinquencyCascade:
    def test_the_first_run_advances_the_invoice_to_past_due_with_a_late_fee(self):
        """The first stage advance adds a fee computed on the residual at that moment.

        "Every advance adds a late fee to `late_fee_line_cents` equal to the invoice's
        residual at that moment multiplied by 0.015 and rounded half up"

        Design: Difficulty/transitive_cascade/nightly_delinquency_abandonment_cascade_depth3
        """
        scenario = _delinquency_scenario()
        assert scenario["invoice"]["amount_due_cents"] == 18225
        assert scenario["invoice"]["late_fee_line_cents"] == 0
        assert scenario["account"]["balance_cents"] == 18225
        assert scenario["account"]["status"] == "ACTIVE"

        set_clock("2026-11-01T00:00:00Z")
        counters = nightly_run()

        assert counters["invoices_advanced_past_due"] == 1
        assert counters["invoices_advanced_delinquent"] == 0
        assert counters["accounts_advanced"] == 1
        assert counters["units_flagged_pending_abandonment"] == 0

        invoice = read_invoice(scenario["invoice"]["id"])
        assert invoice["status"] == "PAST_DUE"
        assert invoice["late_fee_line_cents"] == 273
        assert invoice["amount_due_cents"] == 18498

        account = read_account(scenario["account"]["id"])
        assert account["status"] == "PAST_DUE"
        assert account["balance_cents"] == 18498
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "PRIVATE_STORED"

    def test_each_run_advances_an_invoice_by_at_most_one_stage(self):
        """Even a badly overdue invoice takes two runs to reach delinquency.

        "An `ISSUED` invoice advances to `PAST_DUE` once that count reaches 30; a `PAST_DUE`
        invoice advances to `DELINQUENT` once it reaches 90."

        Design: Difficulty/transitive_cascade/nightly_delinquency_abandonment_cascade_depth3
        """
        scenario = _delinquency_scenario()

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        set_clock("2027-01-01T00:00:00Z")
        second = nightly_run()

        assert second["invoices_advanced_past_due"] == 0
        assert second["invoices_advanced_delinquent"] == 1
        assert second["accounts_advanced"] == 1

        invoice = read_invoice(scenario["invoice"]["id"])
        assert invoice["status"] == "DELINQUENT"
        assert invoice["late_fee_line_cents"] == 550
        assert invoice["amount_due_cents"] == 18775

    def test_delinquency_flags_the_stored_unit_for_abandonment(self):
        """Level two of the fiscal cascade reaches the family's inventory.

        "every unit of the account whose `availability_status` is `PRIVATE_STORED` moves to
        `PENDING_ABANDONMENT`"

        Design: Difficulty/transitive_cascade/nightly_delinquency_abandonment_cascade_depth3
        """
        scenario = _delinquency_scenario()

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        set_clock("2027-01-01T00:00:00Z")
        counters = nightly_run()

        assert counters["units_flagged_pending_abandonment"] == 1
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "PENDING_ABANDONMENT"
        assert read_account(scenario["account"]["id"])["status"] == "DELINQUENT"
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1

    def test_the_pending_hold_on_that_unit_is_declined_by_the_cascade(self):
        """Level three declines the holds standing against the abandoned inventory.

        "every hold on such a unit in `PENDING_CONFIRMATORY` is declined with a
        `cancellation_reason_code` of `ACCOUNT_DELINQUENT`."

        Design: Difficulty/transitive_cascade/nightly_delinquency_abandonment_cascade_depth3
        """
        scenario = _delinquency_scenario()

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()

        set_clock("2027-01-01T00:00:00Z")
        reservation = place_reservation(
            scenario["unit"]["id"],
            center_user_id="tc-003",
            requesting_center_name="Center Delinquent",
            patient_weight_kg=20.0,
            patient_hla_match_count=6,
            hold_from="2027-02-01T00:00:00Z",
            hold_until="2027-02-05T00:00:00Z",
        )
        nightly_run()

        declined = read_reservation(reservation["id"], center_user_id="tc-003")
        assert declined["status"] == "DECLINED"
        assert declined["cancellation_reason_code"] == "ACCOUNT_DELINQUENT"
