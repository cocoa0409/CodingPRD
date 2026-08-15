"""Recall action lifecycle: effectiveness gates and clean close (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_recall_action,
    get_brand,
    get_formula,
    get_recall,
    initiate_recall,
    setup_batch_in_state,
    validate_error,
    validate_success,
)


def test_recall_effectiveness_check_requires_affected_lots(api, qa_approver_headers):
    """PRD §3.8: "Beginning the check moves the recall from `INITIATED` to
    `EFFECTIVENESS_CHECK` and requires the lot cascade to have actually executed —
    `affected_lot_count` greater than zero, else `ERR_RECALL_NO_LOTS` (HTTP 422)."
    PRD §3.8: "The recall starts in `INITIATED`."

    Design: Corner/state_machines/recall_effectiveness_check_requires_affected_lots
    """
    # COMPLETED batch with NO lots: initiation succeeds (a batch is in scope),
    # but no lots move, so affected_lot_count stays 0.
    ctx = setup_batch_in_state("COMPLETED", planned_kg=250.0, line_id="LINE-N1", with_lot=False)
    recall = initiate_recall(
        ctx["formula"]["id"], [ctx["batch"]["id"]], recall_class="CLASS_III",
        reason="Precautionary",
    )
    assert_recall_action(recall)
    assert recall["status"] == "INITIATED"
    assert recall["affected_lot_count"] == 0

    resp = api.begin_effectiveness_check(recall["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_RECALL_NO_LOTS.value)
    assert get_recall(recall["id"])["status"] == "INITIATED"


def test_recall_effectiveness_range_and_clean_close(api, qa_approver_headers):
    """PRD §3.8: "Recording effectiveness moves the recall to `COMPLETED` and
    stores the recovery figure supplied as `effectiveness_pct` — a field that sits
    at zero until recorded — which must lie between 0 and 100 inclusive, else
    `ERR_EFFECTIVENESS_RANGE` (HTTP 422)."
    PRD §3.8: "Closing a `COMPLETED` recall moves it to `CLOSED` and recomputes
    both the formula's `open_recall_flag` — false again once no other open recall
    remains — and the brand's `open_recall_count`."

    Design: Corner/state_machines/recall_effectiveness_range_and_clean_close
    """
    ctx = setup_batch_in_state("COMPLETED", planned_kg=300.0, line_id="LINE-C1", with_lot=True)
    recall = initiate_recall(
        ctx["formula"]["id"], [ctx["batch"]["id"]], recall_class="CLASS_II",
        reason="Potency drift",
    )
    assert recall["affected_lot_count"] == 1
    validate_success(api.begin_effectiveness_check(recall["id"], qa_approver_headers))

    bad = api.record_effectiveness(recall["id"], {"effectiveness_pct": 101.0}, qa_approver_headers)
    validate_error(bad, ApiErrorId.ERR_EFFECTIVENESS_RANGE.value)

    completed = validate_success(
        api.record_effectiveness(recall["id"], {"effectiveness_pct": 95.5}, qa_approver_headers)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["effectiveness_pct"] == pytest.approx(95.5, abs=0.005)

    closed = validate_success(api.close_recall(recall["id"], qa_approver_headers))
    assert closed["status"] == "CLOSED"
    assert get_formula(ctx["formula"]["id"])["open_recall_flag"] is False
    assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 0
