"""The zero point of a computed read, and a uniqueness key scoped to live rows.

A bundle that has just been declared is the one moment when every timeliness
figure is absent rather than zero: the two scores are null, the cumulative
activation-anchored deadlines already exist for all four steps, and the advisory
sequence-anchored deadline exists only for the step that has no predecessor to
wait for. The bed label is the mirror image on the write side: the same creation
body is a duplicate while the first bed is alive and a fresh row once it has
been retired, and the retired row itself never comes back.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_bundle_activation,
    assert_checklist_item,
    assert_instant_equals,
    assert_instant_is_null,
    assert_obstetric_unit,
    activate_hemorrhage_bundle,
    bootstrap_unit,
    BOOTSTRAP_OFFICER_HEADERS,
    create_encounter,
    get_success_data,
    reload_activation,
    set_clock,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
CHARGE_HEADERS = TEST_USERS["charge_nurse_headers"]
HEMORRHAGE_ITEM_COUNT = 4
ACTIVATION_ANCHORED = {
    1: "2026-08-01T06:10:00Z",
    2: "2026-08-01T06:25:00Z",
    3: "2026-08-01T06:45:00Z",
    4: "2026-08-01T06:55:00Z",
}

ZERO_POINT_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Priya Raman MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


def _scalar_values(payload):
    """Every scalar anywhere in a response body, so a projection can be checked
    without assuming the names it chose for its own keys."""
    found = []
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        else:
            found.append(item)
    return found


@pytest.fixture
def a_hemorrhage_bundle_read_before_anything_was_done():
    """One activation at the pinned instant, no completion, no escalation, no sweep."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=ZERO_POINT_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-TIMELINESS-001",
        parity=1,
        gestational_age_weeks=39,
    )
    activation = activate_hemorrhage_bundle(
        world,
        encounter,
        activation_trigger="QBL_THRESHOLD",
        quantitative_blood_loss_ml=1200,
    )
    items = api_client.list_checklist_items(
        activation["id"], world.charge_headers, params={"limit": 10, "offset": 0}
    ).json()
    report = api_client.get_timeliness_report(
        activation["id"], BOOTSTRAP_OFFICER_HEADERS
    )
    return {
        "world": world,
        "encounter": encounter,
        "activation": activation,
        "items": items,
        "report": report,
    }


def test_the_activation_opens_with_no_stage_and_no_scores(
    a_hemorrhage_bundle_read_before_anything_was_done,
):
    """"The activation opens in `ACTIVATED` with `activated_at` at the current
    instant, `unit_id` denormalised from the encounter, `highest_stage_reached` at 0,
    `on_time_step_count`, `late_step_count` and `missed_step_count` at 0, both scores
    null and `rescind_reason` null."

    Design: Corner/endpoints/timeliness_report_returns_null_scores_and_a_null_sequence_due_date_before_any_step_is_completed
    """
    setup = a_hemorrhage_bundle_read_before_anything_was_done
    activation = reload_activation(setup["world"], setup["activation"]["id"])
    assert_bundle_activation(activation)
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0
    assert activation["on_time_step_count"] == 0
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["timeliness_score"] is None
    assert activation["sequence_adjusted_score"] is None
    assert_instant_equals(activation["activated_at"], CLOCK_START, "activated_at")


def test_the_report_shows_the_two_variants_with_neither_score_computed(
    a_hemorrhage_bundle_read_before_anything_was_done,
):
    """"Both scores stay null until the activation reaches `CONTROLLED`, and a
    timeliness report read exposes the two variants side by side with the per-item
    on-time and late classification under each anchoring."

    Design: Corner/endpoints/timeliness_report_returns_null_scores_and_a_null_sequence_due_date_before_any_step_is_completed
    """
    setup = a_hemorrhage_bundle_read_before_anything_was_done
    assert setup["report"].status_code == 200
    reported = _scalar_values(setup["report"].json())
    assert setup["activation"]["id"] in reported
    assert "OBSTETRIC_HEMORRHAGE" in reported
    assert "ACTIVATED" in reported
    scores_that_were_computed_anyway = [
        value for value in reported if isinstance(value, float) and value == 0.0
    ]
    assert scores_that_were_computed_anyway == []


def test_the_report_carries_every_step_of_the_minted_checklist(
    a_hemorrhage_bundle_read_before_anything_was_done,
):
    """"Take the applicable items: every item of the activation whose `status` is not
    `NOT_APPLICABLE`." Nothing has been voided, so all four minted steps are
    applicable and each one's authoritative deadline is already in the projection.

    Design: Corner/endpoints/timeliness_report_returns_null_scores_and_a_null_sequence_due_date_before_any_step_is_completed
    """
    setup = a_hemorrhage_bundle_read_before_anything_was_done
    assert setup["items"]["meta"]["total_count"] == HEMORRHAGE_ITEM_COUNT
    reported = _scalar_values(setup["report"].json())
    for sequence in (1, 2, 3, 4):
        assert any(
            isinstance(value, str) and value.startswith(ACTIVATION_ANCHORED[sequence][:16])
            for value in reported
        ), f"step {sequence} deadline missing from the report"


def test_the_authoritative_dates_are_the_cumulative_sums_from_activation(
    a_hemorrhage_bundle_read_before_anything_was_done,
):
    """"`due_at_activation_anchored`, the authoritative date, is `activated_at` plus
    the sum of `required_within_minutes` across every item whose `step_sequence` is
    less than or equal to this item's. For a hemorrhage bundle that yields offsets of
    10, 25, 45 and 55 minutes from activation."

    Design: Corner/endpoints/timeliness_report_returns_null_scores_and_a_null_sequence_due_date_before_any_step_is_completed
    """
    setup = a_hemorrhage_bundle_read_before_anything_was_done
    by_sequence = {row["step_sequence"]: row for row in setup["items"]["data"]}
    assert sorted(by_sequence) == [1, 2, 3, 4]
    for sequence, step_code, stage_gate, allowance in (
        (1, "QBL_MEASURE", 1, 10),
        (2, "UTEROTONIC_GIVEN", 1, 15),
        (3, "TYPE_AND_SCREEN", 2, 20),
        (4, "MTP_ACTIVATED", 3, 10),
    ):
        row = by_sequence[sequence]
        assert_checklist_item(row)
        assert row["step_code"] == step_code
        assert row["stage_gate"] == stage_gate
        assert row["required_within_minutes"] == allowance
        assert_instant_equals(
            row["due_at_activation_anchored"],
            ACTIVATION_ANCHORED[sequence],
            f"due_at_activation_anchored of step {sequence}",
        )


def test_only_the_first_step_has_an_advisory_date_at_all(
    a_hemorrhage_bundle_read_before_anything_was_done,
):
    """"`due_at_sequence_anchored`, the advisory date, is instead the predecessor
    item's `completed_at` plus this item's own `required_within_minutes`; for the first
    item it is `activated_at` plus that item's own allowance, and for any item whose
    predecessor has not been completed it is null. At activation only the first item's
    sequence-anchored date can be computed."

    Design: Corner/endpoints/timeliness_report_returns_null_scores_and_a_null_sequence_due_date_before_any_step_is_completed
    """
    setup = a_hemorrhage_bundle_read_before_anything_was_done
    by_sequence = {row["step_sequence"]: row for row in setup["items"]["data"]}
    assert_instant_equals(
        by_sequence[1]["due_at_sequence_anchored"],
        ACTIVATION_ANCHORED[1],
        "due_at_sequence_anchored of step 1",
    )
    for sequence in (2, 3, 4):
        assert_instant_is_null(
            by_sequence[sequence]["due_at_sequence_anchored"],
            f"due_at_sequence_anchored of step {sequence}",
        )
    for row in by_sequence.values():
        assert row["status"] == "PENDING"
        assert_instant_is_null(row["completed_at"], "completed_at")
        assert row["minutes_from_activation"] is None


@pytest.fixture
def a_bed_label_claimed_retired_and_claimed_again():
    """LDR-01 refused as a duplicate, retired, minted again, then retired twice."""
    set_clock(CLOCK_START)
    unit = get_success_data(
        api_client.create_unit(
            {
                "unit_name": "Thistledown Perinatal Center LDR",
                "licensed_ldr_beds": 4,
                "licensed_or_rooms": 1,
            },
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )

    def _open_bed(bed_label):
        return api_client.create_bed(
            unit["id"], {"bed_label": bed_label, "bed_type": "LDR"},
            BOOTSTRAP_OFFICER_HEADERS,
        )

    original = get_success_data(_open_bed("LDR-01"))
    keeper = get_success_data(_open_bed("LDR-02"))
    while_it_was_alive = _open_bed("LDR-01")
    retired = api_client.delete_bed(original["id"], BOOTSTRAP_OFFICER_HEADERS)
    after_the_retirement = _open_bed("LDR-01")
    retired_again = api_client.delete_bed(original["id"], BOOTSTRAP_OFFICER_HEADERS)
    listing = api_client.list_unit_beds(
        unit["id"], CHARGE_HEADERS, params={"limit": 10, "offset": 0}
    )
    return {
        "unit": unit,
        "original": original,
        "keeper": keeper,
        "while_it_was_alive": while_it_was_alive,
        "retired": retired,
        "after_the_retirement": after_the_retirement,
        "retired_again": retired_again,
        "listing": listing,
    }


def test_the_label_is_taken_while_the_first_bed_still_lives(
    a_bed_label_claimed_retired_and_claimed_again,
):
    """"`bed_label` is a string of 1 to 40 characters, unique within the unit among
    beds whose `status` is not `CLOSED`; a collision is refused with
    `ERR_DUPLICATE_BED_LABEL`."

    Design: Corner/endpoints/closing_a_bed_frees_its_label_for_reuse_while_a_live_bed_still_owns_it
    """
    setup = a_bed_label_claimed_retired_and_claimed_again
    validate_error(
        setup["while_it_was_alive"], ApiErrorId.ERR_DUPLICATE_BED_LABEL.value, 409
    )
    assert setup["original"]["status"] == "AVAILABLE"


def test_retirement_hands_back_the_closed_row_rather_than_erasing_it(
    a_bed_label_claimed_retired_and_claimed_again,
):
    """"Retirement is a `PerinatalSafetyOfficer` act and moves a bed from `AVAILABLE`
    or `BLOCKED` to `CLOSED`; it is refused with `ERR_BED_HAS_FUTURE_HOLDS` while any
    booking in `CAPACITY_HELD` or `CONFIRMED` still points at the bed."

    Design: Corner/endpoints/closing_a_bed_frees_its_label_for_reuse_while_a_live_bed_still_owns_it
    """
    setup = a_bed_label_claimed_retired_and_claimed_again
    assert setup["retired"].status_code == 200
    retired = get_success_data(setup["retired"])
    assert_bed(retired)
    assert retired["id"] == setup["original"]["id"]
    assert retired["bed_label"] == "LDR-01"
    assert retired["status"] == "CLOSED"


def test_the_freed_label_mints_a_brand_new_bed(
    a_bed_label_claimed_retired_and_claimed_again,
):
    """"A bed opens at `AVAILABLE` and moves through `HELD`, `OCCUPIED`, `TURNOVER`,
    `BLOCKED` and finally `CLOSED`, carrying `current_encounter_id` while a patient is
    in it, `held_booking_id` while a booking reserves it, and `turnover_clear_at` while
    it is being cleaned."

    Design: Corner/endpoints/closing_a_bed_frees_its_label_for_reuse_while_a_live_bed_still_owns_it
    """
    setup = a_bed_label_claimed_retired_and_claimed_again
    assert setup["after_the_retirement"].status_code == 201
    replacement = get_success_data(setup["after_the_retirement"])
    assert_bed(replacement)
    assert replacement["id"] != setup["original"]["id"]
    assert replacement["bed_label"] == "LDR-01"
    assert replacement["bed_type"] == "LDR"
    assert replacement["status"] == "AVAILABLE"
    assert replacement["version"] == 1
    assert replacement["current_encounter_id"] is None
    assert replacement["held_booking_id"] is None
    assert_instant_is_null(replacement["turnover_clear_at"], "turnover_clear_at")


def test_the_retired_row_is_never_resurrected_or_retired_twice(
    a_bed_label_claimed_retired_and_claimed_again,
):
    """"**Priority 8** — the declared-transition guard, on every action operation: an
    attempt to move a record from a state for which the requested edge is not declared
    yields `ERR_INVALID_STATE_TRANSITION` at HTTP 409."

    Design: Corner/endpoints/closing_a_bed_frees_its_label_for_reuse_while_a_live_bed_still_owns_it
    """
    setup = a_bed_label_claimed_retired_and_claimed_again
    validate_error(
        setup["retired_again"], ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409
    )
    original = get_success_data(
        api_client.get_bed(setup["original"]["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert_bed(original)
    assert original["status"] == "CLOSED"


def test_the_unit_ends_with_three_rows_and_two_live_labour_beds(
    a_bed_label_claimed_retired_and_claimed_again,
):
    """"Beds may be listed within a unit ordered by `bed_label` ascending — the same
    lexicographic order the capacity sweep uses when it chooses among candidate beds —
    or across units through a flat collection filtered by `unit_id`, `bed_type`,
    `status`, `current_encounter_id` and `held_booking_id`, which is the only way to
    discover the bed a cascade attached to a particular encounter or booking."

    Design: Corner/endpoints/closing_a_bed_frees_its_label_for_reuse_while_a_live_bed_still_owns_it
    """
    setup = a_bed_label_claimed_retired_and_claimed_again
    body = setup["listing"].json()
    assert setup["listing"].status_code == 200
    assert body["meta"]["total_count"] == 3
    assert len(body["data"]) == 3
    labels = [row["bed_label"] for row in body["data"]]
    assert sorted(labels) == ["LDR-01", "LDR-01", "LDR-02"]
    first_label = [row for row in body["data"] if row["bed_label"] == "LDR-01"]
    assert sorted(row["status"] for row in first_label) == ["AVAILABLE", "CLOSED"]
    keeper = get_success_data(
        api_client.get_bed(setup["keeper"]["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert_bed(keeper)
    assert keeper["status"] == "AVAILABLE"
    unit = get_success_data(
        api_client.get_unit(setup["unit"]["id"], BOOTSTRAP_OFFICER_HEADERS)
    )
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
