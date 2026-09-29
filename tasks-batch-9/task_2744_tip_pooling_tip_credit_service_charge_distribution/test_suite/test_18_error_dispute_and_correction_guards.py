"""Queue B — §1.6 error corners on the remedy path: the strict partial-award band, the
one-live-challenge-per-category key whose window is "not CLOSED", the claim ceiling that
binds only a dispute-backed correction, and both limbs of the supersede pointer."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_ALT,
    PREPARER,
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
    make_employee_headers,
    new_correction,
    new_dispute,
    new_shift,
    read_correction,
    read_dispute,
    read_pay_line,
    read_pay_period,
    setup_texas_wage_world,
    sole_pay_line_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


def _final_line_world() -> dict:
    """The Texas wage unit with one 480-minute CLOSED shift declaring 15000 cash tips,
    computed by op_prep_1 and approved by op_comp_1, so Ana's pay line is FINAL."""
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], world["employee"]["id"], 15000, 0)
    compute_period(world["pay_period"]["id"])
    approve_period(world["pay_period"]["id"])
    world["shift"] = shift
    world["pay_line"] = sole_pay_line_of(world["pay_period"]["id"])
    return world


def _corrections_of(api, pay_line_id: str):
    return validate_paginated(
        api.list_back_wage_corrections(COMPLIANCE, params={"pay_line_id": pay_line_id})
    )


# ---------------------------------------------------------------------------
# errors / dispute_award_amount_and_duplicate_category_guards_rejected
# ---------------------------------------------------------------------------
def test_the_partial_award_band_is_strict_at_both_ends_and_empty_elsewhere(api):
    """Zero, the whole claim, and any award at all under UPHELD share one error id.

    PRD §3.9: "The `OPEN → PARTIALLY_UPHELD` branch grants part of the claim. Here
    `awarded_cents` is required and must be strictly greater than 0 and strictly less than
    `claimed_amount_cents` — the bound is strict at both ends — and
    `adjudicated_amount_cents` is set equal to `awarded_cents`."
    PRD §3.9: "The reason `DENIED` exists as its own branch rather than as a partial award
    of zero is precisely the strict lower bound above: an `awarded_cents` of 0 under
    `PARTIALLY_UPHELD` is rejected with `ERR_PARTIAL_AMOUNT_INVALID`, so denial is the only
    way to award nothing. Symmetrically, an `awarded_cents` equal to `claimed_amount_cents`
    under `PARTIALLY_UPHELD` is also rejected — full grant is `UPHELD`'s job — and supplying
    `awarded_cents` at all under `UPHELD` or `DENIED` is rejected the same way."
    PRD §3.9: "A newly raised dispute has `status` `OPEN`, `adjudicated_amount_cents` 0,
    `adjudicated_by_user_id` null and `closed_at` null."
    PRD §3.9: "Raising it increments the line's `open_dispute_count` but deliberately does
    not increment the line's `version`, because no money has moved."

    Design: Corner/errors/dispute_award_amount_and_duplicate_category_guards_rejected
    """
    world = _final_line_world()
    line = world["pay_line"]
    assert line["status"] == "FINAL"
    assert line["version"] == 2
    assert line["straight_cash_cents"] == 1704
    assert line["minimum_wage_obligation_cents"] == 5800
    assert line["tips_available_cents"] == 15000
    assert line["tip_credit_cents"] == 4096
    assert line["topup_cents"] == 0
    assert line["total_gross_cents"] == 1704

    dispute = new_dispute(
        line["id"],
        world["employee"]["id"],
        category="CC_FEE",
        claimed_amount_cents=1000,
        narrative="card fee taken from my tips",
    )
    assert dispute["status"] == "OPEN"
    assert dispute["adjudicated_amount_cents"] == 0, "no award has been decided yet"
    assert dispute["adjudicated_by_user_id"] is None
    assert dispute["closed_at"] is None
    raised = read_pay_line(line["id"])
    assert raised["open_dispute_count"] == 1
    assert raised["version"] == 2, "raising a dispute moves no money"

    for payload in (
        {"resolution": "PARTIALLY_UPHELD", "awarded_cents": 0,
         "reason_code": "CC_FEE_OVERDEDUCTION"},
        {"resolution": "PARTIALLY_UPHELD", "awarded_cents": 1000,
         "reason_code": "CC_FEE_OVERDEDUCTION"},
        {"resolution": "UPHELD", "awarded_cents": 500,
         "reason_code": "CC_FEE_OVERDEDUCTION"},
    ):
        validate_error(
            api.adjudicate_dispute(dispute["id"], payload, COMPLIANCE),
            ApiErrorId.ERR_PARTIAL_AMOUNT_INVALID.value,
        )

    untouched = read_dispute(dispute["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["adjudicated_amount_cents"] == 0
    _rows, meta = _corrections_of(api, line["id"])
    assert meta["total_count"] == 0, "a refused adjudication writes no correction"


def test_the_category_is_freed_by_closing_and_not_by_deciding(api):
    """A DENIED CC_FEE dispute still blocks a second one; a CLOSED one does not.

    PRD §3.9: "Then the employee must have no other dispute on the same `pay_line_id` with
    the same `category` whose `status` is anything other than `CLOSED`, failing which
    `ERR_DUPLICATE_DISPUTE_CATEGORY`; one open challenge per computation per line is the
    limit."
    PRD §3.9: "From `DENIED` there is no such requirement, because that arm produced no
    correction — the join is deliberately asymmetric."
    PRD §3.9: "Closing stamps `closed_at` with the current logical instant and decrements
    the line's `open_dispute_count`, again without incrementing the line's `version`,
    because no money moves."

    Design: Corner/errors/dispute_award_amount_and_duplicate_category_guards_rejected
    """
    world = _final_line_world()
    line_id = world["pay_line"]["id"]
    employee_id = world["employee"]["id"]
    employee_headers = make_employee_headers(employee_id)

    first = new_dispute(
        line_id, employee_id, category="CC_FEE", claimed_amount_cents=1000
    )
    validate_error(
        api.create_dispute(
            create_dispute_payload(
                line_id, employee_id, category="CC_FEE", claimed_amount_cents=400
            ),
            employee_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_DISPUTE_CATEGORY.value,
    )
    other_category = validate_success(
        api.create_dispute(
            create_dispute_payload(
                line_id, employee_id, category="TIP_CREDIT", claimed_amount_cents=600
            ),
            employee_headers,
        ),
        expected_status=201,
    )
    assert other_category["category"] == "TIP_CREDIT", (
        "the key is (pay_line_id, category), not the pay line alone"
    )

    adjudicate_dispute(
        first["id"], "DENIED", reason_code="CC_FEE_OVERDEDUCTION"
    )
    validate_error(
        api.create_dispute(
            create_dispute_payload(
                line_id, employee_id, category="CC_FEE", claimed_amount_cents=400
            ),
            employee_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_DISPUTE_CATEGORY.value,
    )

    closed = validate_success(api.close_dispute(first["id"], COMPLIANCE))
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], CLOCK, "closed_at")

    freed = validate_success(
        api.create_dispute(
            create_dispute_payload(
                line_id, employee_id, category="CC_FEE", claimed_amount_cents=400
            ),
            employee_headers,
        ),
        expected_status=201,
    )
    assert freed["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_disputes(COMPLIANCE, params={"pay_line_id": line_id})
    )
    assert meta["total_count"] == 3


def test_the_denied_arm_writes_nothing_where_the_partial_arm_writes_a_correction(api):
    """One line, two decisions: the fork shows up as one correction and one version bump.

    PRD §3.9: "The `OPEN → DENIED` branch grants nothing, and it is the divergent arm of
    the fork. `awarded_cents` must be absent from the payload, and
    `adjudicated_amount_cents` is set to 0. Because the award is zero, **no** back-wage
    correction is created, the line's `pending_correction_cents` is left exactly as it was,
    no pre-existing `PENDING` correction is voided, the line's `version` is left untouched,
    and the period's `total_correction_cents` is unchanged."
    PRD §3.9: "Because this award is also positive, the branch then runs exactly the same
    four-hop cascade as the full-grant branch: one `PENDING` back-wage correction created
    with `dispute_id` set and `amount_cents` equal to `adjudicated_amount_cents`, any
    pre-existing `PENDING` correction on the line driven `PENDING → VOIDED` and named by the
    new correction's `supersedes_correction_id`, the line's `pending_correction_cents` set
    to the new amount with its `version` incremented by 1, and the period's
    `total_correction_cents` recomputed."
    PRD §3.9: "All three branches stamp `adjudicated_by_user_id` with the acting
    `X-User-ID`."

    Design: Corner/errors/dispute_award_amount_and_duplicate_category_guards_rejected
    """
    world = _final_line_world()
    line_id = world["pay_line"]["id"]
    employee_id = world["employee"]["id"]

    fee_claim = new_dispute(
        line_id, employee_id, category="CC_FEE", claimed_amount_cents=1000
    )
    credit_claim = new_dispute(
        line_id, employee_id, category="TIP_CREDIT", claimed_amount_cents=600
    )

    denied = adjudicate_dispute(
        fee_claim["id"], "DENIED", reason_code="CC_FEE_OVERDEDUCTION"
    )
    assert denied["status"] == "DENIED"
    assert denied["adjudicated_amount_cents"] == 0
    _rows, meta = _corrections_of(api, line_id)
    assert meta["total_count"] == 0
    assert read_pay_line(line_id)["version"] == 2, "the denial moved no money"

    partial = adjudicate_dispute(
        credit_claim["id"],
        "PARTIALLY_UPHELD",
        awarded_cents=599,
        reason_code="TIP_CREDIT_INVALID",
    )
    assert partial["status"] == "PARTIALLY_UPHELD"
    assert partial["adjudicated_amount_cents"] == 599

    rows, meta = _corrections_of(api, line_id)
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["amount_cents"] == 599
    assert rows[0]["dispute_id"] == credit_claim["id"]
    assert rows[0]["supersedes_correction_id"] is None, "nothing to displace"

    line = read_pay_line(line_id)
    assert line["version"] == 3
    assert line["pending_correction_cents"] == 599
    assert line["correction_applied_cents"] == 0
    assert line["open_dispute_count"] == 2, "deciding a dispute does not close it"
    assert read_pay_period(world["pay_period"]["id"])["total_correction_cents"] == 599


# ---------------------------------------------------------------------------
# errors / correction_claim_ceiling_and_supersede_target_guards_rejected
# ---------------------------------------------------------------------------
def _awarded_world() -> dict:
    """The FINAL pay line plus a CC_FEE dispute claiming 1000 that op_comp_1 partially
    upheld at 800, so one PENDING correction C1 sits on the line at version 3."""
    world = _final_line_world()
    world["dispute"] = new_dispute(
        world["pay_line"]["id"],
        world["employee"]["id"],
        category="CC_FEE",
        claimed_amount_cents=1000,
    )
    adjudicate_dispute(
        world["dispute"]["id"],
        "PARTIALLY_UPHELD",
        awarded_cents=800,
        reason_code="CC_FEE_OVERDEDUCTION",
    )
    world["line_v3"] = read_pay_line(world["pay_line"]["id"])
    world["c1"] = list_corrections_of(pay_line_id=world["pay_line"]["id"])[0]
    return world


def test_the_award_is_the_ceiling_wherever_the_correction_names_its_dispute(api):
    """900 cannot be paid out on an 800 award, and the refusal leaves the version usable.

    PRD §3.9: "Four checks guard the issue, in this order: the target line's `status` must
    be `FINAL`, failing which `ERR_PAY_LINE_NOT_FINAL`; `expected_pay_line_version` must
    equal that line's stored `version`, failing which `ERR_STALE_PAY_LINE_VERSION`;
    `supersedes_correction_id`, when supplied, must name a correction whose `status` is
    `PENDING` on the very same `pay_line_id`, and it is **required** whenever such a
    correction already exists on that line, so both a wrong target and a missing one yield
    `ERR_SUPERSEDE_TARGET_MISMATCH`; and where `dispute_id` is supplied, `amount_cents` may
    not exceed that dispute's `adjudicated_amount_cents`, failing which
    `ERR_CORRECTION_EXCEEDS_CLAIM`, which is also the code for a non-positive amount."
    PRD §3.9: "Issuing it voids the superseded `PENDING` correction it displaced — that
    transition stamps the displaced row's `voided_at` with the current logical instant and
    removes its amount from the line's `pending_correction_cents` — raises the line's
    `pending_correction_cents` by the new amount, increments the line's `version` by exactly
    1, and recomputes the owning period's `total_correction_cents`."
    PRD §2.7: "The server compares it to that line's stored `version` and rejects a mismatch
    with `ERR_STALE_PAY_LINE_VERSION` (HTTP 412). On success the line's `version` increases
    by exactly 1."

    Design: Corner/errors/correction_claim_ceiling_and_supersede_target_guards_rejected
    """
    world = _awarded_world()
    line_id = world["pay_line"]["id"]
    assert world["line_v3"]["version"] == 3, "the adjudication bumped the line from 2"
    assert world["line_v3"]["pending_correction_cents"] == 800

    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id,
                3,
                dispute_id=world["dispute"]["id"],
                supersedes_correction_id=world["c1"]["id"],
                amount_cents=900,
                reason_code="CC_FEE_OVERDEDUCTION",
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_CORRECTION_EXCEEDS_CLAIM.value,
    )
    unchanged = read_pay_line(line_id)
    assert unchanged["version"] == 3, "the refused issue is not a write"
    assert unchanged["pending_correction_cents"] == 800

    replacement = validate_success(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id,
                3,
                dispute_id=world["dispute"]["id"],
                supersedes_correction_id=world["c1"]["id"],
                amount_cents=800,
                reason_code="CC_FEE_OVERDEDUCTION",
            ),
            COMPLIANCE_ALT,
        ),
        expected_status=201,
    )
    assert replacement["status"] == "PENDING"
    assert replacement["amount_cents"] == 800
    assert replacement["supersedes_correction_id"] == world["c1"]["id"]

    displaced = read_correction(world["c1"]["id"])
    assert displaced["status"] == "VOIDED"
    assert_instant_equals(displaced["voided_at"], CLOCK, "voided_at")

    line = read_pay_line(line_id)
    assert line["version"] == 4
    assert line["pending_correction_cents"] == 800, "the VOIDED predecessor drops out"


def test_both_limbs_of_the_supersede_pointer_on_one_line(api):
    """An APPLIED row is not a lawful target, and while a PENDING row exists the pointer
    is mandatory.

    PRD §3.9: "`supersedes_correction_id`, when supplied, must name a correction whose
    `status` is `PENDING` on the very same `pay_line_id`, and it is **required** whenever
    such a correction already exists on that line, so both a wrong target and a missing one
    yield `ERR_SUPERSEDE_TARGET_MISMATCH`."
    PRD §3.9: "Only a `PENDING` correction may be voided in this way; an `APPLIED`
    correction is terminal and can be undone only by issuing a new, opposite-signed
    correction."
    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's `total_gross_cents`;
    the line's `version` is incremented by 1; and `applied_at` is stamped with the current
    logical instant while `applied_by_user_id` records the acting `X-User-ID`."
    PRD §3.9: "The owning period's `total_correction_cents` is then recomputed as the sum of
    `amount_cents` over corrections whose `status` is `PENDING` or `APPLIED` on that
    period's pay lines."

    Design: Corner/errors/correction_claim_ceiling_and_supersede_target_guards_rejected
    """
    world = _awarded_world()
    line_id = world["pay_line"]["id"]

    dispute_backed = new_correction(
        line_id,
        3,
        headers=COMPLIANCE_ALT,
        dispute_id=world["dispute"]["id"],
        supersedes_correction_id=world["c1"]["id"],
        amount_cents=800,
        reason_code="CC_FEE_OVERDEDUCTION",
    )
    applied = apply_correction(dispute_backed["id"], PREPARER)
    assert applied["status"] == "APPLIED"

    settled = read_pay_line(line_id)
    assert settled["correction_applied_cents"] == 800
    assert settled["pending_correction_cents"] == 0
    assert settled["total_gross_cents"] == 2504, "1704 of wages plus the 800 paid"
    assert settled["version"] == 5

    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id,
                5,
                supersedes_correction_id=dispute_backed["id"],
                amount_cents=500,
                reason_code="POOL_SHARE_SHORTFALL",
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_SUPERSEDE_TARGET_MISMATCH.value,
    )

    discretionary = validate_success(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id, 5, amount_cents=500, reason_code="POOL_SHARE_SHORTFALL"
            ),
            COMPLIANCE_ALT,
        ),
        expected_status=201,
    )
    assert discretionary["status"] == "PENDING"
    assert discretionary["dispute_id"] is None, "an audit finding names no dispute"
    assert discretionary["supersedes_correction_id"] is None
    assert read_pay_line(line_id)["version"] == 6

    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id, 6, amount_cents=300, reason_code="TIP_CREDIT_INVALID"
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_SUPERSEDE_TARGET_MISMATCH.value,
    )
    last = validate_success(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id,
                6,
                supersedes_correction_id=discretionary["id"],
                amount_cents=300,
                reason_code="TIP_CREDIT_INVALID",
            ),
            COMPLIANCE_ALT,
        ),
        expected_status=201,
    )
    assert last["supersedes_correction_id"] == discretionary["id"]
    assert read_correction(discretionary["id"])["status"] == "VOIDED"

    final_line = read_pay_line(line_id)
    assert final_line["version"] == 7
    assert final_line["correction_applied_cents"] == 800
    assert final_line["pending_correction_cents"] == 300
    assert final_line["total_gross_cents"] == 2504, "a PENDING correction pays nothing"
    assert read_pay_period(world["pay_period"]["id"])["total_correction_cents"] == 1100, (
        "the APPLIED 800 plus the PENDING 300, both VOIDED rows excluded"
    )
