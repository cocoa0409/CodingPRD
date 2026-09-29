"""Two lifecycles in this service are not simple straight lines.

A qualification can re-enter `SUBMITTED` after a change request, so one status is
occupied twice in a single lifetime and it is `revision_round` rather than the
status that records how many laps were run.  A pallet carries two independent
state dimensions at once, and three release transitions can go by while custody
never moves.
"""

from test_helpers import (
    QM_CAROL,
    assert_instant_equals,
    append_acceptable_runs,
    append_validation_run,
    decide_qualification,
    list_validation_runs,
    open_qualification,
    read_cold_room,
    read_lot,
    read_qualification,
    record_release_decision,
    setup_dispositioned_clean_cycle,
    setup_facility,
    ship_pallet,
    submit_qualification,
)
from test_helpers.fixtures import QUALITY, QUALITY_SECOND


# --------------------------------------------------------------------------- #
# the qualification revision loop
# --------------------------------------------------------------------------- #
def _qualification_at_changes_requested() -> dict:
    """Open, submit, fail one run and request changes, leaving one round closed."""
    world = setup_facility()
    qualification = open_qualification(world["customer"]["id"], world["family"]["id"])
    submit_qualification(qualification["id"], world["customer"]["id"])
    append_validation_run(
        qualification["id"],
        achieved_log_reduction=4.1,
        package_integrity_result="FAIL",
        leaker_count=4,
    )
    decide_qualification(
        qualification["id"], "REQUEST_CHANGES", decision_note="seal integrity"
    )
    world["qualification"] = read_qualification(qualification["id"])
    return world


def test_a_change_request_closes_a_round_without_leaving_the_lifecycle():
    """`REQUEST_CHANGES` parks the recipe at `CHANGES_REQUESTED` and counts the lap
    on `revision_round`, and the failed run is not counted as acceptable.

    PRD 3.2: "A `REQUEST_CHANGES` outcome instead advances `UNDER_VALIDATION →
    CHANGES_REQUESTED` and increments `revision_round` by one; it has no gates of
    its own beyond the state check."
    PRD 3.2: "After the append, `validation_run_acceptable_count` is recomputed as
    the number of the qualification's runs whose verdict is `ACCEPTABLE`."

    Design: Difficulty/non_linear_state_machine/qualification_revision_round_cycles_back_to_submitted
    """
    world = _qualification_at_changes_requested()
    qualification = world["qualification"]

    assert qualification["status"] == "CHANGES_REQUESTED"
    assert qualification["revision_round"] == 1
    assert qualification["validation_run_acceptable_count"] == 0
    assert qualification["qualified_at"] is None


def test_the_second_lap_re_enters_submitted_and_reaches_qualified():
    """Submitting from `CHANGES_REQUESTED` occupies `SUBMITTED` for the second time
    in one lifetime, and two acceptable runs then carry the recipe to `QUALIFIED`.

    PRD 3.2: "The same operation also closes the revision loop: a qualification
    sitting at `CHANGES_REQUESTED` advances `CHANGES_REQUESTED → SUBMITTED`, but
    only while `revision_round` has not exceeded three completed rounds — a fourth
    attempt is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 422)."
    PRD 3.2: "A qualification that clears all four gates advances
    `UNDER_VALIDATION → QUALIFIED`, stamps `qualified_at` with the logical clock
    instant of the decision, and sets `expires_at` to exactly 365 days after
    `qualified_at`."

    Design: Difficulty/non_linear_state_machine/qualification_revision_round_cycles_back_to_submitted
    """
    world = _qualification_at_changes_requested()
    qualification_id = world["qualification"]["id"]

    submit_qualification(qualification_id, world["customer"]["id"])
    append_acceptable_runs(qualification_id, how_many=2)
    decide_qualification(qualification_id, "QUALIFY")
    qualification = read_qualification(qualification_id)

    assert qualification["status"] == "QUALIFIED"
    assert qualification["package_suitability_score"] == 100.00
    assert_instant_equals(qualification["qualified_at"], "2026-08-03T08:00:00Z")
    assert_instant_equals(qualification["expires_at"], "2027-08-03T08:00:00Z")


def test_the_revision_round_survives_qualification_and_the_failed_run_is_kept():
    """The lap counter still reads 1 on the qualified recipe, and all three runs are
    retained with exactly one of them `UNACCEPTABLE`.

    PRD 3.2: "First, `validation_run_acceptable_count` must be at least two — the
    facility will not qualify a recipe on a single acceptable run — and a shortfall
    is refused with `ERR_INSUFFICIENT_VALIDATION_RUNS`."
    PRD 3.2: "it is `ACCEPTABLE` when the `package_integrity_result` is `PASS`
    **and** the measured pressure is at least the qualification's `pressure_mpa`
    **and** the measured hold time is at least the qualification's
    `hold_time_seconds` **and** the achieved log reduction is at least the
    qualification's `target_log_reduction`; if any one of those four fails, the
    verdict is `UNACCEPTABLE`."

    Design: Difficulty/non_linear_state_machine/qualification_revision_round_cycles_back_to_submitted
    """
    world = _qualification_at_changes_requested()
    qualification_id = world["qualification"]["id"]

    submit_qualification(qualification_id, world["customer"]["id"])
    append_acceptable_runs(qualification_id, how_many=2)
    decide_qualification(qualification_id, "QUALIFY")
    qualification = read_qualification(qualification_id)
    runs = list_validation_runs(qualification_id)

    assert qualification["revision_round"] == 1
    assert qualification["validation_run_acceptable_count"] == 2
    assert len(runs) == 3
    assert [r["run_verdict"] for r in runs].count("UNACCEPTABLE") == 1


# --------------------------------------------------------------------------- #
# the pallet's two independent state dimensions
# --------------------------------------------------------------------------- #
def test_a_hold_moves_the_release_dimension_and_leaves_custody_at_treated():
    """An operator-driven `HOLD_FOR_TEST` records its reason on the release
    dimension while the pallet stays in custody at `TREATED`.

    PRD 3.9: "A `HOLD_FOR_TEST` advances the pallet `NOT_RELEASED →
    ON_HOLD_FOR_TEST` and records the supplied `hold_reason`; this is the
    operator-driven counterpart of the automatic hold that a deviated chamber run
    applies."
    PRD 3.9: "The pallet's custody must be `TREATED` in every case — a pallet that
    has not been through a chamber, or has already shipped, is refused with
    `ERR_INVALID_LOT_CUSTODY_STATE`."

    Design: Difficulty/non_linear_state_machine/lot_custody_and_release_dimensions_advance_independently
    """
    world = setup_dispositioned_clean_cycle()
    lot_id = world["lot"]["id"]
    assert world["lot"]["release_state"] == "NOT_RELEASED"

    record_release_decision(
        lot_id, "HOLD_FOR_TEST", headers=QUALITY, hold_reason="micro pending"
    )
    lot = read_lot(lot_id)

    assert lot["release_state"] == "ON_HOLD_FOR_TEST"
    assert lot["custody_state"] == "TREATED"
    assert lot["hold_reason"] == "micro pending"


def test_release_from_hold_clears_the_reason_and_still_does_not_move_custody():
    """A second quality manager lifts the hold: the release dimension reaches
    `RELEASED` and is stamped with her identifier, and custody has not budged.

    PRD 3.9: "A `RELEASE` advances the pallet `NOT_RELEASED → RELEASED`, or
    `ON_HOLD_FOR_TEST → RELEASED` when it was on hold, in which case `hold_reason`
    is cleared to null. Either way `released_by_user_id` is stamped with the acting
    `X-User-ID`."
    PRD 2.1: "it lands in `recorded_by_user_id` on a lab validation run, in
    `adjudicated_by_user_id` on a deviation, and in `released_by_user_id` on a
    pallet that has been released."

    Design: Difficulty/non_linear_state_machine/lot_custody_and_release_dimensions_advance_independently
    """
    world = setup_dispositioned_clean_cycle()
    lot_id = world["lot"]["id"]
    record_release_decision(
        lot_id, "HOLD_FOR_TEST", headers=QUALITY, hold_reason="micro pending"
    )

    record_release_decision(lot_id, "RELEASE", headers=QUALITY_SECOND)
    lot = read_lot(lot_id)

    assert lot["release_state"] == "RELEASED"
    assert lot["custody_state"] == "TREATED"
    assert lot["released_by_user_id"] == QM_CAROL
    assert lot["hold_reason"] is None


def test_shipping_moves_custody_alone_and_frees_the_cold_room_position():
    """Only the ship call advances custody to `SHIPPED`; the release dimension stays
    at `RELEASED`, the room's occupancy falls back to zero and the unit ledger is
    untouched throughout.

    PRD 3.9: "A successful shipment advances the pallet `TREATED → SHIPPED`, lowers
    the cold room's `occupied_pallets` by one and recomputes the room's
    `capacity_state`, freeing a position for the next inbound pallet, and increments
    the pallet's `version`."
    PRD 3.1: "`occupied_pallets` is not a free-running counter: it is the number of
    pallets assigned to this room whose `custody_state` is `IN_COLD_STORAGE`,
    `IN_VESSEL` or `TREATED`."
    PRD 3.4: "Pallets are read back with both state dimensions and the full unit
    ledger visible, and can be listed and filtered by `customer_id`,
    `qualification_id`, `cold_room_id`, `custody_state` and `release_state` — the
    two state dimensions being independently filterable precisely because they
    evolve independently."

    Design: Difficulty/non_linear_state_machine/lot_custody_and_release_dimensions_advance_independently
    """
    world = setup_dispositioned_clean_cycle()
    lot_id = world["lot"]["id"]
    record_release_decision(
        lot_id, "HOLD_FOR_TEST", headers=QUALITY, hold_reason="micro pending"
    )
    record_release_decision(lot_id, "RELEASE", headers=QUALITY_SECOND)

    ship_pallet(lot_id)
    lot = read_lot(lot_id)
    room = read_cold_room(world["room"]["id"])

    assert lot["custody_state"] == "SHIPPED"
    assert lot["release_state"] == "RELEASED"
    assert lot["units_treated"] == 1000
    assert room["occupied_pallets"] == 0
    assert room["capacity_state"] == "NORMAL"
