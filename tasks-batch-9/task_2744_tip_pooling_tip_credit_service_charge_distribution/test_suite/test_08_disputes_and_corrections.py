"""Queue A — the dispute fork: a partial award that forks and rejoins at CLOSED,
and an adjudication whose cascade displaces a correction issued by audit."""
from test_helpers import (
    COMPLIANCE,
    PREPARER_ALT,
    adjudicate_dispute,
    apply_correction,
    assert_instant_equals,
    list_corrections_of,
    new_correction,
    new_dispute,
    read_correction,
    read_dispute,
    read_pay_line,
    read_pay_period,
    setup_texas_final_pay_line_world,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


def _sole_correction_of_dispute(dispute_id: str) -> dict:
    rows = list_corrections_of(dispute_id=dispute_id)
    assert len(rows) == 1, (
        f"the award cascade creates exactly one correction, got {len(rows)}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# non_linear_state_machine / dispute_fork_partially_upheld_then_join_closed
# ---------------------------------------------------------------------------
def _setup_partially_upheld_dispute() -> dict:
    """The FINAL Texas pay line at version 2 with one OPEN TIP_CREDIT dispute
    claiming 2000 cents, adjudicated down to an award of 800."""
    world = setup_texas_final_pay_line_world()
    line = world["pay_line"]
    dispute = new_dispute(line["id"], world["employee"]["id"], claimed_amount_cents=2000)
    world["dispute"] = adjudicate_dispute(
        dispute["id"],
        "PARTIALLY_UPHELD",
        headers=COMPLIANCE,
        awarded_cents=800,
        reason_code="TIP_CREDIT_INVALID",
    )
    return world


def test_partial_award_takes_the_middle_branch_and_creates_a_pending_correction(api):
    """800 of a 2000 claim: the strict bound is satisfied and the cascade fires.

    PRD §3.9: "Here `awarded_cents` is required and must be strictly greater than 0
    and strictly less than `claimed_amount_cents` — the bound is strict at both ends
    — and `adjudicated_amount_cents` is set equal to `awarded_cents`."
    PRD §3.9: "Because this award is also positive, the branch then runs exactly the
    same four-hop cascade as the full-grant branch: one `PENDING` back-wage
    correction created with `dispute_id` set and `amount_cents` equal to
    `adjudicated_amount_cents`, any pre-existing `PENDING` correction on the line
    driven `PENDING → VOIDED` and named by the new correction's
    `supersedes_correction_id`, the line's `pending_correction_cents` set to the new
    amount with its `version` incremented by 1, and the period's
    `total_correction_cents` recomputed."
    PRD §3.9: "All three branches stamp `adjudicated_by_user_id` with the acting
    `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/dispute_fork_partially_upheld_then_join_closed
    """
    world = _setup_partially_upheld_dispute()
    dispute = world["dispute"]

    assert dispute["status"] == "PARTIALLY_UPHELD"
    assert dispute["adjudicated_amount_cents"] == 800
    assert dispute["adjudicated_by_user_id"] == COMPLIANCE["X-User-ID"]

    correction = _sole_correction_of_dispute(dispute["id"])
    assert correction["status"] == "PENDING"
    assert correction["amount_cents"] == 800
    assert correction["reason_code"] == "TIP_CREDIT_INVALID"
    assert correction["dispute_id"] == dispute["id"]
    assert correction["issued_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert correction["supersedes_correction_id"] is None, (
        "no correction existed on this line, so nothing was displaced"
    )

    line = read_pay_line(world["pay_line"]["id"])
    assert line["pending_correction_cents"] == 800
    assert line["correction_applied_cents"] == 0
    assert line["total_gross_cents"] == 7004, (
        "an award that is only pending has not yet moved the gross"
    )
    assert line["version"] == 3


def test_applying_then_closing_pays_the_award_and_rejoins_the_three_arms(api):
    """The join at CLOSED is reached only once the money has actually been paid.

    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's
    `total_gross_cents`; the line's `version` is incremented by 1; and `applied_at`
    is stamped with the current logical instant while `applied_by_user_id` records
    the acting `X-User-ID`."
    PRD §3.9: "One reason code alone has a further effect: where `reason_code` is
    `TIP_CREDIT_INVALID`, the correction is by definition a minimum-wage top-up, so
    the period's `total_topup_cents` is additionally raised by `amount_cents`."
    PRD §3.9: "Closing stamps `closed_at` with the current logical instant and
    decrements the line's `open_dispute_count`, again without incrementing the
    line's `version`, because no money moves."

    Design: Difficulty/non_linear_state_machine/dispute_fork_partially_upheld_then_join_closed
    """
    world = _setup_partially_upheld_dispute()
    dispute_id = world["dispute"]["id"]
    correction = _sole_correction_of_dispute(dispute_id)

    applied = apply_correction(correction["id"], headers=PREPARER_ALT)
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_user_id"] == PREPARER_ALT["X-User-ID"]
    assert_instant_equals(applied["applied_at"], CLOCK, "applied_at")

    line = read_pay_line(world["pay_line"]["id"])
    assert line["pending_correction_cents"] == 0
    assert line["correction_applied_cents"] == 800
    assert line["total_gross_cents"] == 7804
    assert line["version"] == 4

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_correction_cents"] == 800
    assert period["total_topup_cents"] == 4396, (
        "3596 of computed top-up plus the 800 TIP_CREDIT_INVALID award"
    )

    closed = validate_success(api.close_dispute(dispute_id, COMPLIANCE))
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], CLOCK, "closed_at")

    after = read_pay_line(world["pay_line"]["id"])
    assert after["open_dispute_count"] == 0
    assert after["version"] == 4, "closing a dispute moves no money and no version"


# ---------------------------------------------------------------------------
# transitive_cascade / dispute_adjudication_cascade_supersedes_prior_correction
# ---------------------------------------------------------------------------
def _setup_audit_correction_then_upheld_dispute() -> dict:
    """The FINAL Texas pay line carrying one PENDING audit correction of 1000
    cents, then an UPHELD dispute claiming 1500."""
    world = setup_texas_final_pay_line_world()
    line = world["pay_line"]
    world["audit_correction"] = new_correction(
        line["id"],
        line["version"],
        headers=COMPLIANCE,
        amount_cents=1000,
        reason_code="SIDE_WORK_OVERAGE",
    )
    dispute = new_dispute(line["id"], world["employee"]["id"], claimed_amount_cents=1500)
    world["dispute"] = adjudicate_dispute(
        dispute["id"], "UPHELD", headers=COMPLIANCE, reason_code="TIP_CREDIT_INVALID"
    )
    return world


def test_upheld_award_displaces_the_audit_correction_rather_than_stacking_on_it(api):
    """Two rows exist on the line but only the 1500 one is live, naming its predecessor.

    PRD §3.9: "`awarded_cents` must be absent from the payload, and
    `adjudicated_amount_cents` is set equal to `claimed_amount_cents`."
    PRD §3.9: "Because the award is positive, the branch then runs a four-hop
    cascade: it creates exactly one back-wage correction with `status` `PENDING`,
    its `dispute_id` naming this dispute and its `amount_cents` equal to
    `adjudicated_amount_cents`; it drives any pre-existing `PENDING` correction on
    the same pay line from `PENDING` to `VOIDED`, with the new correction's
    `supersedes_correction_id` naming the one it displaced; it sets the pay line's
    `pending_correction_cents` to the new correction's amount and increments that
    line's `version` by 1; and it recomputes the owning period's
    `total_correction_cents` from the `PENDING` and `APPLIED` corrections across all
    of that period's pay lines."

    Design: Difficulty/transitive_cascade/dispute_adjudication_cascade_supersedes_prior_correction
    """
    world = _setup_audit_correction_then_upheld_dispute()
    audit_id = world["audit_correction"]["id"]

    assert world["dispute"]["status"] == "UPHELD"
    assert world["dispute"]["adjudicated_amount_cents"] == 1500

    rows = list_corrections_of(pay_line_id=world["pay_line"]["id"])
    assert len(rows) == 2, (
        f"the displaced audit row survives beside the new one, got {len(rows)}"
    )

    new_row = _sole_correction_of_dispute(world["dispute"]["id"])
    assert new_row["status"] == "PENDING"
    assert new_row["amount_cents"] == 1500
    assert new_row["reason_code"] == "TIP_CREDIT_INVALID"
    assert new_row["supersedes_correction_id"] == audit_id


def test_displaced_correction_is_voided_and_drops_out_of_both_rollups(api):
    """The line owes 1500, not 2500, and the voided 1000 keeps its own amount.

    PRD §3.9: "Issuing it voids the superseded `PENDING` correction it displaced —
    that transition stamps the displaced row's `voided_at` with the current logical
    instant and removes its amount from the line's `pending_correction_cents` —
    raises the line's `pending_correction_cents` by the new amount, increments the
    line's `version` by exactly 1, and recomputes the owning period's
    `total_correction_cents`."
    PRD §3.4: "`total_correction_cents` is the sum of `amount_cents` over back-wage
    corrections whose `status` is either `PENDING` or `APPLIED` and whose
    `pay_line_id` names a pay line of this period; a correction that has been
    `VOIDED` drops out of the sum entirely."
    PRD §3.8: "`pending_correction_cents` and `correction_applied_cents` are the
    sums of `amount_cents` over the line's corrections whose `status` is `PENDING`
    and whose `status` is `APPLIED` respectively."

    Design: Difficulty/transitive_cascade/dispute_adjudication_cascade_supersedes_prior_correction
    """
    world = _setup_audit_correction_then_upheld_dispute()

    voided = read_correction(world["audit_correction"]["id"])
    assert voided["status"] == "VOIDED"
    assert_instant_equals(voided["voided_at"], CLOCK, "voided_at")
    assert voided["amount_cents"] == 1000, (
        "the displaced row is not rewritten, it is only taken out of the sums"
    )

    line = read_pay_line(world["pay_line"]["id"])
    assert line["pending_correction_cents"] == 1500, (
        "the new award replaces the displaced 1000 rather than stacking to 2500"
    )
    assert line["correction_applied_cents"] == 0
    assert line["total_gross_cents"] == 7004
    assert line["version"] == 4, (
        "version 1 at compute, 2 at approval, 3 at the audit issue, 4 at the "
        "adjudication cascade"
    )

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_correction_cents"] == 1500

    assert read_dispute(world["dispute"]["id"])["status"] == "UPHELD"
