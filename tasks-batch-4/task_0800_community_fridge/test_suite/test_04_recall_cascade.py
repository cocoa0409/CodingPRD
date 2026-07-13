"""Recall -> quarantine -> hold/suspend cascade and the HELD<->STOCKED revert cycle."""
from test_helpers import (
    validate_success, ApiErrorId,
    setup_two_stocked_batches, setup_quarantined_fridge,
    recall_batch, discard_batch,
    make_admin_headers,
)


def _fridge(api, fridge_id):
    return validate_success(api.get_fridge(fridge_id, make_admin_headers()), 200)


def _batch(api, batch_id):
    return validate_success(api.get_batch(batch_id, make_admin_headers()), 200)


def _need(api, need_id):
    return validate_success(api.get_need(need_id, make_admin_headers()), 200)


def test_recall_sets_batch_recalled_and_fridge_quarantined(api):
    """PRD §3.7: "A `Steward` or `NetworkAdmin` recalls a batch that is currently
    `STOCKED` or `HELD`, moving it to `RECALLED`. ... it raises the fridge's
    `active_recall_count`, which forces the fridge's `safety_posture` to
    `QUARANTINED`."

    Design: Difficulty/transitive_cascade/recall_quarantine_hold_suspend_chain
    """
    fridge, steward, recalled, batch_b, need = setup_quarantined_fridge(
        api, capacity_slots=10
    )
    assert recalled["status"] == "RECALLED"
    assert _fridge(api, fridge["id"])["safety_posture"] == "QUARANTINED"


def test_quarantine_cascade_holds_sibling_batch_and_suspends_need(api):
    """PRD §2.7: "When a fridge becomes `QUARANTINED`, every other batch at that fridge
    that was in `STOCKED` status is moved to `HELD`, and every `NeedPosting` at that
    fridge that was in `OPEN` status is moved to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/recall_quarantine_hold_suspend_chain
    """
    fridge, steward, recalled, batch_b, need = setup_quarantined_fridge(
        api, capacity_slots=10
    )
    assert _batch(api, batch_b["id"])["status"] == "HELD"
    assert _need(api, need["id"])["status"] == "SUSPENDED"


def test_sibling_batch_moves_to_held_on_quarantine(api):
    """PRD §2.7: "When a fridge becomes `QUARANTINED`, every other batch at that fridge
    that was in `STOCKED` status is moved to `HELD`, and every `NeedPosting` at that
    fridge that was in `OPEN` status is moved to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/batch_stocked_held_stocked_revert
    """
    fridge, steward, batch_a, batch_b = setup_two_stocked_batches(api, capacity_slots=10)
    recall_batch(api, batch_a["id"], steward["id"])
    assert _batch(api, batch_b["id"])["status"] == "HELD"


def test_discarding_recall_reverts_held_sibling_back_to_stocked(api):
    """PRD §3.7: "Discarding recomputes the fridge's `active_recall_count`; if it
    reaches zero and no other blocker remains, the fridge leaves `QUARANTINED`, and the
    reversal cascade returns each `HELD` batch to `STOCKED` and each `SUSPENDED` need
    to `OPEN`."

    Design: Difficulty/non_linear_state_machine/batch_stocked_held_stocked_revert
    """
    fridge, steward, batch_a, batch_b = setup_two_stocked_batches(api, capacity_slots=10)
    recall_batch(api, batch_a["id"], steward["id"])
    discard_batch(api, batch_a["id"], steward["id"])
    assert _batch(api, batch_b["id"])["status"] == "STOCKED"
    assert _fridge(api, fridge["id"])["safety_posture"] == "OPERATIONAL"
