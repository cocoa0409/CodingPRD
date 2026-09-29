"""A set job's two status dimensions advance on disjoint triggers (PRD §3.7).

The scope dimension walks `SCOPE_PENDING -> SCOPE_SPLIT -> SCOPE_DELIVERED`
without ever touching the progress dimension, and closing the marriage line
advances the progress dimension without touching the scope dimension, so the
observable state of a set job is the cross-product of the two.
"""

import pytest

from test_helpers import (
    api_client,
    assert_version_incremented,
    book_set_job,
    close_marriage_line,
    make_set_crew_lead_headers,
    open_order,
    read_set_job,
    record_scope_split,
    register_plant,
    register_set_crew,
    scope_split_payload,
    set_logical_clock,
    setup_dispatched_set_job,
    utility_crossover_payload,
    validate_success,
)


def _scheduled_set_job():
    """A single-section AZ order with one booked, never dispatched set job."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(license_expiry_date="2027-06-30")
    order = open_order(
        plant["id"], section_count=1, destination_state="AZ", wind_zone="I"
    )
    set_job = book_set_job(order["id"], set_crew["id"], labor_base_cents=480000)
    return {"plant": plant, "set_crew": set_crew, "order": order, "set_job": set_job}


def test_scope_split_advances_scope_dimension_while_progress_stays_scheduled():
    """PRD §3.7: "Dispatching, closing the marriage line and the final inspection
    move `progress_status` only and leave `scope_status` untouched; recording the
    scope split and recording the utility crossover move `scope_status` only and
    leave `progress_status` untouched."
    PRD §3.7: "The split may be recorded while `progress_status` is `SCHEDULED`,
    `DISPATCHED` or `SET_COMPLETE` — it does not wait for dispatch."
    PRD §3.7: "Pricing follows directly: `skirting_fee_cents` is zero when
    `skirting_owner` is `DEALER`, and otherwise the skirting run length multiplied
    by eighteen dollars fifty per linear foot (1,850 cents per foot), rounded half
    up to whole cents; `steps_fee_cents` is zero when `steps_owner` is `DEALER`,
    and otherwise the step count multiplied by four hundred and twenty dollars per
    unit (42,000 cents), which needs no rounding."
    PRD §3.7: "Recording the split raises the job's `version` and leaves
    `progress_status` unchanged."

    Design: Difficulty/non_linear_state_machine/set_job_parallel_dimensions_advance_independently
    """
    scenario = _scheduled_set_job()
    booked = scenario["set_job"]

    assert booked["progress_status"] == "SCHEDULED", (
        f"a fresh booking opens at SCHEDULED, got {booked['progress_status']}"
    )
    assert booked["scope_status"] == "SCOPE_PENDING", (
        f"a fresh booking opens at SCOPE_PENDING, got {booked['scope_status']}"
    )

    split = validate_success(
        api_client.record_scope_split(
            booked["id"],
            scope_split_payload(
                skirting_owner="INSTALLER",
                steps_owner="INSTALLER",
                skirting_linear_ft=52,
                steps_count=1,
            ),
            make_set_crew_lead_headers(scenario["set_crew"]["id"]),
        )
    )

    assert split["scope_status"] == "SCOPE_SPLIT", (
        f"SCOPE_PENDING -> SCOPE_SPLIT expected, got {split['scope_status']}"
    )
    assert split["progress_status"] == "SCHEDULED", (
        "the scope split must leave the progress dimension exactly where it was, "
        f"expected SCHEDULED, got {split['progress_status']}"
    )
    assert split["skirting_fee_cents"] == 96200, (
        "52 linear feet at 1,850 cents per foot must price the skirting at 96200, "
        f"got {split['skirting_fee_cents']}"
    )
    assert split["steps_fee_cents"] == 42000, (
        "one step unit at 42,000 cents must price the steps at 42000, got "
        f"{split['steps_fee_cents']}"
    )
    assert_version_incremented(split["version"], booked["version"])


def test_utility_crossover_after_dispatch_leaves_progress_dimension_untouched():
    """PRD §3.7: "Once the scope is split, the same `SetCrewLead` records the
    under-floor utility crossovers, moving `scope_status` `SCOPE_SPLIT →
    SCOPE_DELIVERED`. This step does wait for dispatch: `progress_status` must be
    `DISPATCHED` or `SET_COMPLETE`."
    PRD §3.7: "The submission supplies `crossover_count`, the number of crossovers
    made between sections, and pricing is a flat six hundred dollars (60,000 cents)
    for mobilising the crossover work plus one hundred and eighty dollars (18,000
    cents) for each crossover made, stored as `crossover_fee_cents`."
    PRD §3.7: "Recording the crossover raises the job's `version` and leaves
    `progress_status` unchanged."
    PRD §3.7: "Before any closure attempt the job reads `closure_status`
    `NOT_ASSESSED` with `closure_score` null."

    Design: Difficulty/non_linear_state_machine/set_job_parallel_dimensions_advance_independently
    """
    scenario = setup_dispatched_set_job(
        section_count=1, job_overrides={"labor_base_cents": 480000}
    )
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]

    split = record_scope_split(
        job_id,
        crew_id,
        skirting_owner="INSTALLER",
        steps_owner="INSTALLER",
        skirting_linear_ft=52,
        steps_count=1,
    )
    assert split["progress_status"] == "DISPATCHED", (
        "the split must not disturb a dispatched job's progress dimension, got "
        f"{split['progress_status']}"
    )

    delivered = validate_success(
        api_client.record_utility_crossover(
            job_id,
            utility_crossover_payload(crossover_count=3),
            make_set_crew_lead_headers(crew_id),
        )
    )

    assert delivered["scope_status"] == "SCOPE_DELIVERED", (
        f"SCOPE_SPLIT -> SCOPE_DELIVERED expected, got {delivered['scope_status']}"
    )
    assert delivered["progress_status"] == "DISPATCHED", (
        "recording the crossover leaves the progress dimension at DISPATCHED, got "
        f"{delivered['progress_status']}"
    )
    assert delivered["crossover_fee_cents"] == 114000, (
        "60,000 cents of mobilisation plus three crossovers at 18,000 cents each "
        f"must price the crossover at 114000, got {delivered['crossover_fee_cents']}"
    )
    assert delivered["crossover_recorded"] is True, (
        "the crossover step sets crossover_recorded to true"
    )
    assert delivered["closure_status"] == "NOT_ASSESSED", (
        "no closure has been attempted, so closure_status must still read "
        f"NOT_ASSESSED, got {delivered['closure_status']}"
    )
    assert delivered.get("closure_score") is None, (
        f"closure_score stays null before any closure, got {delivered.get('closure_score')}"
    )
    assert delivered.get("invoice_total_cents") is None, (
        "no invoice is assembled before a clean final inspection, got "
        f"{delivered.get('invoice_total_cents')}"
    )
    assert_version_incremented(delivered["version"], split["version"])


def test_closing_marriage_line_advances_progress_and_leaves_scope_status_alone():
    """PRD §3.7: "The job's `SetCrewLead` closes the marriage line, which moves
    `progress_status` `DISPATCHED → SET_COMPLETE`."
    PRD §3.7: "A single-section order therefore records no joints, closes with a
    `closure_score` of 0.00 and a `closure_status` of `NOT_APPLICABLE`, and passes
    the later gate vacuously."
    PRD §3.7: "Closing raises the job's `version`, re-derives the order's posture,
    and leaves `scope_status` unchanged."

    Design: Difficulty/non_linear_state_machine/set_job_parallel_dimensions_advance_independently
    """
    scenario = setup_dispatched_set_job(
        section_count=1, job_overrides={"labor_base_cents": 480000}
    )
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]

    split = record_scope_split(
        job_id,
        crew_id,
        skirting_owner="INSTALLER",
        steps_owner="INSTALLER",
        skirting_linear_ft=52,
        steps_count=1,
    )
    assert split["scope_status"] == "SCOPE_SPLIT", (
        f"the scope dimension must sit at SCOPE_SPLIT, got {split['scope_status']}"
    )

    closed = close_marriage_line(job_id, crew_id)

    assert closed["progress_status"] == "SET_COMPLETE", (
        f"DISPATCHED -> SET_COMPLETE expected on closure, got {closed['progress_status']}"
    )
    assert closed["scope_status"] == "SCOPE_SPLIT", (
        "closing the marriage line must leave the scope dimension untouched, "
        f"expected SCOPE_SPLIT, got {closed['scope_status']}"
    )
    assert closed["closure_status"] == "NOT_APPLICABLE", (
        "a single-section order records no joints and closes NOT_APPLICABLE, got "
        f"{closed['closure_status']}"
    )
    assert closed["closure_score"] == pytest.approx(0.00, abs=0.01), (
        f"a jointless closure scores 0.00, got {closed['closure_score']}"
    )
    assert closed["skirting_fee_cents"] == 96200, (
        "the scope pricing recorded earlier survives the closure, expected 96200, "
        f"got {closed['skirting_fee_cents']}"
    )
    assert_version_incremented(closed["version"], split["version"])

    reread = read_set_job(job_id)
    assert reread["scope_status"] == "SCOPE_SPLIT", (
        "a re-read confirms the scope dimension never moved, got "
        f"{reread['scope_status']}"
    )
