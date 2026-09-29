"""Queue B — §1.2 state machines on the payroll side: the period's two precondition
guards, the dispute fork's join, correction idempotency, the DRAFT-line lock and the
service-charge void that drags a computed period back to OPEN."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_ALT,
    PREPARER,
    PREPARER_ALT,
    ApiErrorId,
    adjudicate_dispute,
    apply_correction,
    approve_period,
    assert_instant_equals,
    close_shift,
    compute_period,
    create_back_wage_correction_payload,
    create_dispute_payload,
    declare_shift_tips,
    list_corrections_of,
    list_pay_lines_of,
    make_employee_headers,
    new_correction,
    new_dispute,
    new_service_charge,
    new_shift,
    read_correction,
    read_dispute,
    read_pay_line,
    read_pay_period,
    read_service_charge,
    read_shift,
    reopen_period,
    setup_texas_wage_world,
    sole_pay_line_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


def _single_shift_world(**location_overrides) -> dict:
    """The Texas wage week with exactly one CLOSED shift on 2026-08-04 declaring
    5000 cents of cash tips and no card sales."""
    world = setup_texas_wage_world(**location_overrides)
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], world["employee"]["id"], 5000, 0)
    world["shift"] = shift
    return world


def _final_line_world() -> dict:
    """That same week computed by op_prep_1 and approved by op_comp_1, leaving one
    FINAL pay line at version 2 with total_gross_cents 1704."""
    world = _single_shift_world()
    compute_period(world["pay_period"]["id"], headers=PREPARER)
    approve_period(world["pay_period"]["id"], headers=COMPLIANCE)
    world["pay_line"] = sole_pay_line_of(world["pay_period"]["id"])
    return world


# ---------------------------------------------------------------------------
# precondition_enforcement — approve and reopen from OPEN
# ---------------------------------------------------------------------------
def test_one_error_id_guards_two_missing_preconditions_on_an_open_period(api):
    """Approve wants COMPUTED and reopen wants COMPUTED or APPROVED; OPEN satisfies neither.

    PRD §2.10 rung 13: "The target pay period's `status` is `COMPUTED` —
    `ERR_PAY_PERIOD_NOT_COMPUTED`, 409, on
    `POST /pay-periods/{pay_period_id}/approve`."
    PRD §2.10 rung 14: "The target pay period's `status` is either `COMPUTED` or
    `APPROVED` — `ERR_PAY_PERIOD_NOT_COMPUTED`, 409, on
    `POST /pay-periods/{pay_period_id}/reopen`."
    PRD §3.8: "The guards, in order: the period's `status` must be `COMPUTED` or
    `APPROVED`, so reopening a period that is already `OPEN` yields
    `ERR_PAY_PERIOD_NOT_COMPUTED`; and no back-wage correction whose `status` is
    `PENDING` may exist on any pay line of the period, failing which
    `ERR_PENDING_CORRECTION_EXISTS` — an unresolved correction must be applied or
    superseded before the numbers underneath it are torn down."

    Design: Corner/state_machines/approve_and_reopen_an_open_pay_period_return_pay_period_not_computed
    """
    world = setup_texas_wage_world()
    period_id = world["pay_period"]["id"]

    validate_error(
        api.approve_pay_period(period_id, COMPLIANCE),
        ApiErrorId.ERR_PAY_PERIOD_NOT_COMPUTED.value,
    )
    validate_error(
        api.reopen_pay_period(period_id, COMPLIANCE, {"reason": "premature"}),
        ApiErrorId.ERR_PAY_PERIOD_NOT_COMPUTED.value,
    )

    period = read_pay_period(period_id)
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None
    assert period["computed_by_user_id"] is None
    assert period["approved_by_user_id"] is None
    assert period["version"] == 1, "neither refusal left a fingerprint"

    _rows, meta = validate_paginated(
        api.list_pay_lines(COMPLIANCE, params={"pay_period_id": period_id})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# precondition_enforcement — the unfinished-money lock on reopen
# ---------------------------------------------------------------------------
def test_a_pending_correction_locks_the_reopen_until_the_money_is_posted(api):
    """The identical reopen call fails, then succeeds the moment the 500 is applied.

    PRD §2.10 rung 15: "No back-wage correction with `status` `PENDING` exists on any
    pay line of the target period — `ERR_PENDING_CORRECTION_EXISTS`, 409, on
    `POST /pay-periods/{pay_period_id}/reopen`."
    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's
    `total_gross_cents`; the line's `version` is incremented by 1; and `applied_at` is
    stamped with the current logical instant while `applied_by_user_id` records the
    acting `X-User-ID`."
    PRD §3.8: "From either `DRAFT` or `FINAL` a line goes to the terminal
    `SUPERSEDED` when the owning period re-enters `OPEN` or when a fresh compute
    replaces the pay-line set; in both cases the line's `version` is incremented by 1,
    which invalidates any `expected_pay_line_version` a client was holding."

    Design: Corner/state_machines/reopen_with_a_pending_correction_returns_pending_correction_exists
    """
    world = _final_line_world()
    line_id = world["pay_line"]["id"]
    correction = new_correction(
        line_id,
        world["pay_line"]["version"],
        headers=COMPLIANCE_ALT,
        amount_cents=500,
        reason_code="POOL_SHARE_SHORTFALL",
    )

    validate_error(
        api.reopen_pay_period(
            world["pay_period"]["id"], COMPLIANCE, {"reason": "audit finding"}
        ),
        ApiErrorId.ERR_PENDING_CORRECTION_EXISTS.value,
    )

    assert read_pay_period(world["pay_period"]["id"])["status"] == "APPROVED"
    assert read_correction(correction["id"])["status"] == "PENDING"
    locked = read_pay_line(line_id)
    assert locked["status"] == "FINAL"
    assert locked["pending_correction_cents"] == 500
    assert locked["correction_applied_cents"] == 0
    assert locked["version"] == 3, "compute 1, approve 2, correction issue 3"

    applied = apply_correction(correction["id"], headers=PREPARER_ALT)
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_user_id"] == PREPARER_ALT["X-User-ID"]
    assert_instant_equals(applied["applied_at"], CLOCK, "applied_at")

    paid = read_pay_line(line_id)
    assert paid["pending_correction_cents"] == 0
    assert paid["correction_applied_cents"] == 500
    assert paid["total_gross_cents"] == 2204, "1704 of straight cash plus the 500 posted"
    assert paid["version"] == 4

    reopened = reopen_period(
        world["pay_period"]["id"], reason="audit finding", headers=COMPLIANCE
    )
    assert reopened["status"] == "OPEN"
    assert reopened["compute_variant"] is None
    assert reopened["total_correction_cents"] == 500, (
        "an APPLIED correction stays inside the rollup across the supersession"
    )

    torn_down = read_pay_line(line_id)
    assert torn_down["status"] == "SUPERSEDED"
    assert torn_down["version"] == 5


# ---------------------------------------------------------------------------
# invalid_transition — adjudicating a closed dispute
# ---------------------------------------------------------------------------
def test_a_denied_and_closed_dispute_cannot_be_adjudicated_a_second_time(api):
    """The whole DENIED arm moves no money, and CLOSED refuses the replay.

    PRD §2.10 rung 19: "The target dispute's `status` is `OPEN` —
    `ERR_DISPUTE_NOT_OPEN`, 409, on `POST /disputes/{dispute_id}/adjudicate`."
    PRD §3.9: "The `OPEN → DENIED` branch grants nothing, and it is the divergent arm
    of the fork. `awarded_cents` must be absent from the payload, and
    `adjudicated_amount_cents` is set to 0. Because the award is zero, **no** back-wage
    correction is created, the line's `pending_correction_cents` is left exactly as it
    was, no pre-existing `PENDING` correction is voided, the line's `version` is left
    untouched, and the period's `total_correction_cents` is unchanged."
    PRD §3.9: "Closing stamps `closed_at` with the current logical instant and
    decrements the line's `open_dispute_count`, again without incrementing the line's
    `version`, because no money moves."

    Design: Corner/state_machines/adjudicate_a_closed_dispute_returns_dispute_not_open
    """
    world = _final_line_world()
    dispute = new_dispute(
        world["pay_line"]["id"],
        world["employee"]["id"],
        category="CC_FEE",
        claimed_amount_cents=2000,
        narrative="card fee looks wrong",
    )
    adjudicate_dispute(dispute["id"], "DENIED", headers=COMPLIANCE)
    validate_success(api.close_dispute(dispute["id"], COMPLIANCE))

    validate_error(
        api.adjudicate_dispute(dispute["id"], {"resolution": "UPHELD"}, COMPLIANCE),
        ApiErrorId.ERR_DISPUTE_NOT_OPEN.value,
    )

    closed = read_dispute(dispute["id"])
    assert closed["status"] == "CLOSED"
    assert closed["adjudicated_amount_cents"] == 0
    assert closed["adjudicated_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert_instant_equals(closed["closed_at"], CLOCK, "closed_at")

    _rows, meta = validate_paginated(
        api.list_back_wage_corrections(
            COMPLIANCE, params={"pay_line_id": world["pay_line"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "a DENIED dispute creates no correction and the rejected replay creates none"
    )

    line = read_pay_line(world["pay_line"]["id"])
    assert line["open_dispute_count"] == 0
    assert line["pending_correction_cents"] == 0
    assert line["total_gross_cents"] == 1704
    assert line["version"] == 2, "the entire dispute lifecycle moved no money"


# ---------------------------------------------------------------------------
# precondition_enforcement — the two limbs of the close guard
# ---------------------------------------------------------------------------
def test_closing_a_dispute_is_refused_while_open_and_again_while_the_award_is_unpaid(api):
    """The same call is refused twice for two different reasons before it succeeds.

    PRD §2.10 rung 20: "The target dispute's `status` is one of `UPHELD`,
    `PARTIALLY_UPHELD` or `DENIED`, and for the two award-bearing outcomes the
    dispute's back-wage correction has `status` `APPLIED` —
    `ERR_DISPUTE_NOT_ADJUDICATED`, 409, on `POST /disputes/{dispute_id}/close`."
    PRD §3.9: "From `UPHELD` the dispute may be closed only once the dispute's
    back-wage correction carries `status` `APPLIED`; the same requirement attaches
    from `PARTIALLY_UPHELD`, since that arm too produced an award that must actually be
    paid."
    PRD §3.9: "One reason code alone has a further effect: where `reason_code` is
    `TIP_CREDIT_INVALID`, the correction is by definition a minimum-wage top-up, so
    the period's `total_topup_cents` is additionally raised by `amount_cents`. Under
    every other reason code the period's `total_topup_cents` is left alone."

    Design: Corner/state_machines/close_an_open_or_unpaid_dispute_returns_dispute_not_adjudicated
    """
    world = _final_line_world()
    dispute = new_dispute(
        world["pay_line"]["id"],
        world["employee"]["id"],
        category="CC_FEE",
        claimed_amount_cents=2000,
        narrative="card fee looks wrong",
    )

    validate_error(
        api.close_dispute(dispute["id"], COMPLIANCE),
        ApiErrorId.ERR_DISPUTE_NOT_ADJUDICATED.value,
    )
    assert read_dispute(dispute["id"])["status"] == "OPEN"

    adjudicated = adjudicate_dispute(
        dispute["id"],
        "PARTIALLY_UPHELD",
        headers=COMPLIANCE,
        awarded_cents=800,
        reason_code="CC_FEE_OVERDEDUCTION",
    )
    assert adjudicated["adjudicated_amount_cents"] == 800
    awards = list_corrections_of(dispute_id=dispute["id"])
    assert len(awards) == 1
    assert awards[0]["status"] == "PENDING"
    assert awards[0]["amount_cents"] == 800

    validate_error(
        api.close_dispute(dispute["id"], COMPLIANCE),
        ApiErrorId.ERR_DISPUTE_NOT_ADJUDICATED.value,
    )

    apply_correction(awards[0]["id"], headers=PREPARER_ALT)
    paid = read_pay_line(world["pay_line"]["id"])
    assert paid["correction_applied_cents"] == 800
    assert paid["pending_correction_cents"] == 0
    assert paid["total_gross_cents"] == 2504
    assert paid["version"] == 4

    closed = validate_success(api.close_dispute(dispute["id"], COMPLIANCE))
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], CLOCK, "closed_at")

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_correction_cents"] == 800
    assert period["total_topup_cents"] == 0, (
        "CC_FEE_OVERDEDUCTION is not a minimum-wage top-up"
    )
    assert read_pay_line(world["pay_line"]["id"])["open_dispute_count"] == 0


# ---------------------------------------------------------------------------
# idempotency — applying a correction twice
# ---------------------------------------------------------------------------
def test_replaying_an_apply_posts_the_money_exactly_once(api):
    """APPLIED is terminal, so the second post is a 409 and the gross stays at 2204.

    PRD §3.9: "**Applying a correction.** Posting a `PENDING` correction to its line
    drives it `PENDING → APPLIED` and may be done by either a `ComplianceOfficer` or a
    `PayrollPreparer` — but never by the same person who issued it."
    PRD §2.10 rung 21: "The target correction's `status` is `PENDING` —
    `ERR_CORRECTION_NOT_PENDING`, 409, on
    `POST /back-wage-corrections/{correction_id}/apply`."
    PRD §3.4: "`total_correction_cents` is the sum of `amount_cents` over back-wage
    corrections whose `status` is either `PENDING` or `APPLIED` and whose
    `pay_line_id` names a pay line of this period; a correction that has been `VOIDED`
    drops out of the sum entirely."

    Design: Corner/state_machines/apply_an_already_applied_correction_returns_correction_not_pending
    """
    world = _final_line_world()
    correction = new_correction(
        world["pay_line"]["id"],
        world["pay_line"]["version"],
        headers=COMPLIANCE_ALT,
        amount_cents=500,
        reason_code="POOL_SHARE_SHORTFALL",
    )
    apply_correction(correction["id"], headers=PREPARER_ALT)

    validate_error(
        api.apply_back_wage_correction(correction["id"], PREPARER_ALT),
        ApiErrorId.ERR_CORRECTION_NOT_PENDING.value,
    )

    stored = read_correction(correction["id"])
    assert stored["status"] == "APPLIED"
    assert stored["applied_by_user_id"] == PREPARER_ALT["X-User-ID"]
    assert_instant_equals(stored["applied_at"], CLOCK, "applied_at")

    line = read_pay_line(world["pay_line"]["id"])
    assert line["correction_applied_cents"] == 500, "not 1000"
    assert line["pending_correction_cents"] == 0
    assert line["total_gross_cents"] == 2204, "not 2704"
    assert line["version"] == 4

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_correction_cents"] == 500
    assert period["total_topup_cents"] == 0


# ---------------------------------------------------------------------------
# precondition_enforcement — the DRAFT line lock
# ---------------------------------------------------------------------------
def test_a_draft_line_admits_neither_a_dispute_nor_a_correction(api):
    """The FINAL check fires ahead of the version check even on a correct version.

    PRD §2.10 rung 22: "The pay line named by `pay_line_id` has `status` `FINAL` —
    `ERR_PAY_LINE_NOT_FINAL`, 409, on `POST /disputes`,
    `POST /back-wage-corrections` and
    `POST /back-wage-corrections/{correction_id}/apply`."
    PRD §3.9: "Then the line's `status` must be `FINAL` — a `DRAFT` line has not been
    approved and a `SUPERSEDED` line no longer represents anything — failing which
    `ERR_PAY_LINE_NOT_FINAL`."
    PRD §3.9: "Four checks guard the issue, in this order: the target line's `status`
    must be `FINAL`, failing which `ERR_PAY_LINE_NOT_FINAL`;
    `expected_pay_line_version` must equal that line's stored `version`, failing which
    `ERR_STALE_PAY_LINE_VERSION`; `supersedes_correction_id`, when supplied, must name
    a correction whose `status` is `PENDING` on the very same `pay_line_id`, and it is
    **required** whenever such a correction already exists on that line, so both a
    wrong target and a missing one yield `ERR_SUPERSEDE_TARGET_MISMATCH`; and where
    `dispute_id` is supplied, `amount_cents` may not exceed that dispute's
    `adjudicated_amount_cents`, failing which `ERR_CORRECTION_EXCEEDS_CLAIM`, which is
    also the code for a non-positive amount."

    Design: Corner/state_machines/dispute_or_correct_a_draft_pay_line_returns_pay_line_not_final
    """
    world = _single_shift_world()
    compute_period(world["pay_period"]["id"], headers=PREPARER)
    line = sole_pay_line_of(world["pay_period"]["id"])
    assert line["status"] == "DRAFT" and line["version"] == 1

    validate_error(
        api.create_dispute(
            create_dispute_payload(
                line["id"],
                world["employee"]["id"],
                claimed_amount_cents=1000,
                narrative="too early",
            ),
            make_employee_headers(world["employee"]["id"]),
        ),
        ApiErrorId.ERR_PAY_LINE_NOT_FINAL.value,
    )
    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line["id"],
                line["version"],
                amount_cents=400,
                reason_code="TIP_CREDIT_INVALID",
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_PAY_LINE_NOT_FINAL.value,
    )

    after = read_pay_line(line["id"])
    assert after["status"] == "DRAFT"
    assert after["variant"] == "WEEKLY_AGGREGATE"
    assert after["open_dispute_count"] == 0
    assert after["pending_correction_cents"] == 0
    assert after["version"] == 1, "the presented version was current all along"

    _dr, dispute_meta = validate_paginated(
        api.list_disputes(COMPLIANCE, params={"pay_line_id": line["id"]})
    )
    _cr, correction_meta = validate_paginated(
        api.list_back_wage_corrections(COMPLIANCE, params={"pay_line_id": line["id"]})
    )
    assert dispute_meta["total_count"] == 0
    assert correction_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# side_effect_execution — voiding an allocated service charge
# ---------------------------------------------------------------------------
def test_voiding_an_allocated_wages_charge_reopens_the_period_and_uncrowds_the_credit(api):
    """6000 of wages crowds the credit to 0; voiding it restores a 4096-cent credit.

    PRD §3.6: "Voiding a charge that was `ALLOCATED` unwinds whichever absorption
    occurred: if `allocated_pool_id` was set, `amount_cents` is subtracted from that
    pool's `service_charge_tips_cents` and from its `net_pool_cents`, and the unit's
    `pending_pool_cents` is then recomputed; if `allocated_pay_period_id` was set,
    that period is driven back to `OPEN` by the server, which marks every pay line of
    the period `SUPERSEDED`."
    PRD §3.8: "`regular_rate_cents_per_hour` is `straight_cash_cents` plus
    `service_charge_wages_cents`, divided by the number of hours worked — that is, by
    `total_minutes` divided by sixty — rounded half up."
    PRD §3.8: "`tip_credit_cents` is then the smallest of those three figures — the
    per-hour ceiling, the tips actually available, and the residual — floored at 0 so
    it can never be negative."
    PRD §3.6: "In the `WAGES` case the absorption requires that at least one `CLOSED`
    shift exist at that unit on that `business_date`, stamps
    `allocated_pay_period_id` with the computing period's identifier, and contributes
    to the affected employees' `service_charge_wages_cents`."

    Design: Corner/state_machines/voiding_an_allocated_service_charge_drives_the_computed_period_back_to_open
    """
    world = _single_shift_world()
    charge = new_service_charge(
        world["location"]["id"], amount_cents=6000, description="Banquet 14 gratuity"
    )
    compute_period(world["pay_period"]["id"], headers=PREPARER)

    absorbed = read_service_charge(charge["id"])
    assert absorbed["treatment"] == "WAGES"
    assert absorbed["status"] == "ALLOCATED"
    assert absorbed["allocated_pay_period_id"] == world["pay_period"]["id"]
    assert absorbed["allocated_pool_id"] is None

    crowded = sole_pay_line_of(world["pay_period"]["id"])
    assert crowded["service_charge_wages_cents"] == 6000
    assert crowded["straight_cash_cents"] == 1704
    assert crowded["regular_rate_cents_per_hour"] == 963, "7704 cents over eight hours"
    assert crowded["minimum_wage_obligation_cents"] == 5800
    assert crowded["tip_credit_cents"] == 0, (
        "the residual is already negative, so the floored credit is 0"
    )
    assert crowded["topup_cents"] == 0
    assert crowded["total_gross_cents"] == 7704

    voided = validate_success(
        api.void_service_charge(
            charge["id"], PREPARER, {"reason": "billed to the wrong unit"}
        )
    )
    assert voided["status"] == "VOIDED"

    reopened = read_pay_period(world["pay_period"]["id"])
    assert reopened["status"] == "OPEN"
    assert reopened["compute_variant"] is None
    assert read_pay_line(crowded["id"])["status"] == "SUPERSEDED"

    compute_period(world["pay_period"]["id"], headers=PREPARER)
    live = [
        row
        for row in list_pay_lines_of(world["pay_period"]["id"])
        if row["status"] != "SUPERSEDED"
    ]
    assert len(live) == 1
    rebuilt = live[0]
    assert rebuilt["service_charge_wages_cents"] == 0
    assert rebuilt["straight_cash_cents"] == 1704
    assert rebuilt["regular_rate_cents_per_hour"] == 213
    assert rebuilt["minimum_wage_obligation_cents"] == 5800
    assert rebuilt["tips_available_cents"] == 5000
    assert rebuilt["tip_credit_cents"] == 4096
    assert rebuilt["topup_cents"] == 0
    assert rebuilt["total_gross_cents"] == 1704

    survivor = read_shift(world["shift"]["id"])
    assert survivor["time_status"] == "CLOSED"
    assert survivor["declaration_status"] == "DECLARED"
    assert survivor["retained_tips_cents"] == 5000, (
        "the cascade touched the period and the line, not the shift"
    )
