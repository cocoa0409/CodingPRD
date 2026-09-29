"""The bed-offer cycle runs repeatedly and is closed by a counter, not by a trigger.

An entry that is offered a bed and lets the offer lapse returns to the queue, so
the same entry can be offered again on the next nightly run. The loop is bounded
only by the number of offers the applicant has let go.
"""

from test_helpers import fixtures as fx


def _class_one_applicant_on_a_single_bed_unit(api):
    """One highly ranked applicant queued alone on a one-bed open unit."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=1, out_of_service_bed_count=0
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        service_days=900,
        discharge_character="HONORABLE",
        wartime_service=True,
        service_connected_disability_pct=80,
        nursing_care_for_service_connected=False,
        state_residency_years=6,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    return home, unit, applicant, entry


def _entry_row(api, unit_id, entry_id):
    rows = {row["id"]: row for row in fx.read_waitlist_entries_for_unit(api, unit_id)}
    return rows[entry_id]


def test_first_nightly_run_offers_the_bed_with_a_seven_day_window(api):
    """The checkpoint offers the free bed to the entry at the head of the queue.

    Per the PRD: "The transition stamps `offer_expires_at` at the current logical
    clock plus a seven-day offer window and increments the entry's `version`." The
    offer is issued by the checkpoint rather than by whatever freed the bed.

    Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_cycle_terminates_at_max_declines
    """
    home, unit, _applicant, entry = _class_one_applicant_on_a_single_bed_unit(api)

    fx.census_run(api, "2026-08-01", home["id"])

    row = _entry_row(api, unit["id"], entry["id"])
    assert row["status"] == "OFFERED"
    assert row["offer_expires_at"].startswith("2026-08-08T00:00:00"), (
        f"expected the offer window to close 2026-08-08, got {row['offer_expires_at']!r}"
    )


def test_lapsed_offer_returns_the_entry_to_the_queue(api):
    """An offer nobody takes up reverts the entry to ACTIVE with the window cleared.

    Per the PRD: "When the logical clock has moved strictly past an entry's
    `offer_expires_at`, that `OFFERED` entry reverts to `ACTIVE` with
    `offer_expires_at` cleared to null, the owning applicant's
    `declined_offer_count` increases by 1". The applicant keeps their place in
    line, which is what allows the cycle to run again.

    Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_cycle_terminates_at_max_declines
    """
    home, unit, applicant, entry = _class_one_applicant_on_a_single_bed_unit(api)
    fx.census_run(api, "2026-08-01", home["id"])

    fx.set_clock(api, "2026-08-09T00:00:00Z")
    fx.census_run(api, "2026-08-09", home["id"])

    row = _entry_row(api, unit["id"], entry["id"])
    assert row["status"] == "ACTIVE"
    assert row["offer_expires_at"] is None
    assert fx.read_applicant(api, applicant["id"])["declined_offer_count"] == 1


def test_third_decline_expires_the_entry_and_empties_the_queue(api):
    """Three laps of the offer cycle end with the entry expired and the unit's queue empty.

    Per the PRD: "Within the same checkpoint pass, after offers have been
    declined, any `ACTIVE` entry whose applicant has reached three declined offers
    moves to `EXPIRED` with `queue_position` set to 0, its unit's
    `waitlist_active_count` decremented by 1 and that unit's `version`
    incremented." The bed itself was never taken, so it is still free.

    Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_cycle_terminates_at_max_declines
    """
    home, unit, applicant, entry = _class_one_applicant_on_a_single_bed_unit(api)
    for through_date in ("2026-08-01", "2026-08-09", "2026-08-10", "2026-08-18", "2026-08-19", "2026-08-27"):
        fx.set_clock(api, f"{through_date}T00:00:00Z")
        fx.census_run(api, through_date, home["id"])

    row = _entry_row(api, unit["id"], entry["id"])
    assert row["status"] == "EXPIRED"
    assert row["queue_position"] == 0

    refreshed = fx.read_applicant(api, applicant["id"])
    assert refreshed["declined_offer_count"] == 3
    assert refreshed["status"] == "WAITLISTED"
    assert refreshed["priority_score"] == 1221

    care_unit = fx.read_unit(api, unit["id"])
    assert care_unit["waitlist_active_count"] == 0
    assert care_unit["occupied_bed_count"] == 0
    assert care_unit["available_bed_count"] == 1
