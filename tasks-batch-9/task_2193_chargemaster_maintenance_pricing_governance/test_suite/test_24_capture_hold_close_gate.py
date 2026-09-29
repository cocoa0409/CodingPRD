"""Closing a batch is gated on the owning department's derived capture_hold flag."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_capture_hold_scenario,
    disposition_finding, read_batch, read_department, read_item, list_findings,
    batch_lifecycle,
    ANALYST,
)


def test_confirming_the_finding_derives_a_capture_hold_that_refuses_the_close():
    """PRD §3.9: "When no companion is present and no finding with that
    `trigger_captured_charge_id` already sits in `OPEN`, `CONFIRMED` or `RESOLVED`, a new
    `MissingChargeFinding` is created in `OPEN` with `batch_id` and `department_id` copied from
    the batch, `trigger_captured_charge_id` naming the unpaired line,
    `expected_charge_item_id` naming the companion item that should have been captured, and
    `estimated_lost_charge_cents` computed as the companion item's `gross_charge_cents`
    multiplied by the trigger line's `quantity`."
    PRD §3.9: "it records the payload's `disposition_note`, then adds the finding's
    `estimated_lost_charge_cents` to the department's `unresolved_finding_amount_cents` with
    `Department.version` advancing by 1, and — the second cascade link — sets the department's
    `capture_hold` to true once `unresolved_finding_amount_cents` reaches 500000 cents or more,
    which blocks that department from ingesting any further capture batch."
    PRD §3.9: "Also from `RECONCILED`, the analyst may close — `RECONCILED → CLOSED` — which
    requires that `open_finding_count` be 0, meaning every finding of the batch is `CONFIRMED`,
    `DISMISSED` or `RESOLVED` (otherwise `ERR_FINDINGS_OPEN`, 409), and that the department's
    `capture_hold` be false (otherwise `ERR_DEPARTMENT_CAPTURE_HOLD`, 409)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__batch_close_gated_by_derived_department_capture_hold
    """
    s = setup_capture_hold_scenario()
    assert read_item(s["trigger_item"]["id"])["gross_charge_cents"] == 300000
    assert read_item(s["companion_item"]["id"])["gross_charge_cents"] == 300000
    assert s["batch"]["status"] == "RECONCILED"
    assert s["batch"]["matched_line_count"] == 2
    assert len(s["findings"]) == 1, (
        "the companion line is 72 hours after the trigger, outside the 24-hour window, so "
        f"exactly one finding opens: got {len(s['findings'])}"
    )
    finding = s["finding"]
    assert finding["status"] == "OPEN"
    assert finding["estimated_lost_charge_cents"] == 600000, (
        "the companion's 300000 cents times the trigger line's quantity of 2"
    )
    assert finding["expected_charge_item_id"] == s["companion_item"]["id"]
    assert finding["trigger_captured_charge_id"] == s["trigger_line"]["id"]

    confirmed = disposition_finding(
        finding["id"], "CONFIRM",
        disposition_note="companion interpretation was genuinely never posted",
    )
    assert confirmed["status"] == "CONFIRMED"

    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 600000
    assert department["capture_hold"] is True, (
        "600000 cents reaches the 500000-cent threshold, so the flag derives to true"
    )

    assert read_batch(s["batch"]["id"])["open_finding_count"] == 0, (
        "a CONFIRMED finding is no longer open, so the findings gate is satisfied and the "
        "capture-hold gate is the one that has to fire"
    )
    validate_error(
        api_client.batch_lifecycle(s["batch"]["id"], {"action": "CLOSE"}, ANALYST),
        ApiErrorId.ERR_DEPARTMENT_CAPTURE_HOLD.value,
        409,
    )
    assert read_batch(s["batch"]["id"])["status"] == "RECONCILED"


def test_resolving_the_finding_clears_the_hold_and_the_identical_close_succeeds():
    """PRD §3.9: "It requires that the supplied `recovery_captured_charge_id` resolve to a
    `CapturedCharge` in the **same** batch whose `charge_item_id` equals the finding's
    `expected_charge_item_id`, otherwise `ERR_RECOVERY_LINE_INVALID` (422), and that the
    batch's `status` not be `CLOSED`, otherwise `ERR_INVALID_BATCH_STATE`."
    PRD §3.9: "On success `recovery_captured_charge_id` is stored, and the *same literal
    amount* — the finding's frozen `estimated_lost_charge_cents` — is subtracted from the
    department's `unresolved_finding_amount_cents` and added to its `recovered_charge_cents`,
    so that the department's total identified leakage is conserved"
    PRD §3.9: "The department's `capture_hold` is then recomputed — which is how a department
    digs itself out of a hold — and `Department.version` advances by 1."
    PRD §3.9: "Closing recomputes the department's aggregates but deliberately does not touch
    `open_request_count`, which tracks change requests rather than batches. `CLOSED` is the
    batch's terminal state, and the three lifecycle actions are named `FINALIZE`, `DISPUTE` and
    `CLOSE`, each accepting an optional `note`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__batch_close_gated_by_derived_department_capture_hold
    """
    s = setup_capture_hold_scenario()
    disposition_finding(s["finding"]["id"], "CONFIRM",
                        disposition_note="companion interpretation was never posted")
    validate_error(
        api_client.batch_lifecycle(s["batch"]["id"], {"action": "CLOSE"}, ANALYST),
        ApiErrorId.ERR_DEPARTMENT_CAPTURE_HOLD.value,
        409,
    )

    resolved = disposition_finding(
        s["finding"]["id"], "RESOLVE",
        disposition_note="late-posted companion line accepted",
        recovery_captured_charge_id=s["recovery_line"]["id"],
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["estimated_lost_charge_cents"] == 600000, (
        "the amount is frozen at creation and is never recomputed"
    )
    assert resolved["recovery_captured_charge_id"] == s["recovery_line"]["id"]

    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 0
    assert department["recovered_charge_cents"] == 600000
    assert (
        department["unresolved_finding_amount_cents"]
        + department["recovered_charge_cents"] == 600000
    ), "the identified leakage is conserved across the confirm-then-resolve pair"
    assert department["capture_hold"] is False

    closed = batch_lifecycle(s["batch"]["id"], "CLOSE")
    assert closed["status"] == "CLOSED", (
        "the identical call now succeeds; only the department's derived flag moved"
    )
    assert closed["open_finding_count"] == 0
    assert closed["reconcile_pass_count"] == 1
    assert closed["line_count"] == 2
    assert closed["exception_line_count"] == 0
    assert closed["mean_line_variance_bp"] == 0
    assert closed["total_expected_charge_cents"] == 1200000
    assert closed["total_posted_charge_cents"] == 1200000
    assert [f["status"] for f in list_findings(batch_id=s["batch"]["id"])] == ["RESOLVED"]
