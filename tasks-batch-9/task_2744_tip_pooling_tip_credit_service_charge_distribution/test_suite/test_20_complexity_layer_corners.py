"""Queue B — §1.7 complexity-layer corners: the two optimistic-concurrency windows, each
proven to sit below an earlier state rung on the precedence ladder, and the eight-percent
reporting threshold probed three times on one period through reopen."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_ALT,
    PREPARER,
    ApiErrorId,
    activate_policy,
    approve_period,
    assert_instant_equals,
    close_shift,
    compute_period,
    create_back_wage_correction_payload,
    declare_shift_tips,
    list_pay_lines_of,
    new_correction,
    new_draft_policy,
    new_location,
    new_shift,
    read_location,
    read_correction,
    read_pay_line,
    read_pay_period,
    read_policy,
    read_shift,
    reopen_period,
    set_logical_clock,
    setup_texas_wage_world,
    sole_pay_line_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


# ---------------------------------------------------------------------------
# complexity_layers / location_version_occ_on_policy_activation
# ---------------------------------------------------------------------------
def test_the_only_writer_of_a_units_version_makes_its_own_replay_stale(api):
    """One successful activation is the whole width of the window, and the replay of that
    activation is answered by the earlier state rung rather than by the OCC comparison.

    PRD §2.7: "The server compares it to the stored `version` of that `Location`. If the
    two differ, the request is rejected with `ERR_STALE_LOCATION_VERSION` (HTTP 412). On
    success the server increments that unit's `version` by exactly 1 — activation is in
    fact the only writer of a unit's `version` — so replaying the same activation with the
    same `expected_location_version` is reliably rejected."
    PRD §3.3: "The policy's `status` must be `DRAFT` — activating one already `ACTIVE` or
    already `SUPERSEDED` yields `ERR_POLICY_NOT_DRAFT`. Then the supplied
    `expected_location_version` must equal the unit's stored `version`, failing which the
    activation is refused with `ERR_STALE_LOCATION_VERSION`."
    PRD §2.10: "Every rule in the system occupies a fixed rung on a single precedence
    ladder, and the rule on the lowest-numbered rung that the request violates is the rule
    that produces the response; every rule below it on the ladder is never reached."
    PRD §2.10: "11. The target policy's `status` is `DRAFT` — `ERR_POLICY_NOT_DRAFT`, 409,
    on `POST /tip-pool-policies/{policy_id}/activate`."
    PRD §2.10: "23. `expected_location_version` equals the stored `version` of the policy's
    unit — `ERR_STALE_LOCATION_VERSION`, 412, on
    `POST /tip-pool-policies/{policy_id}/activate`."
    PRD §3.3: "Second, if another policy at the same `location_id` currently holds `status`
    `ACTIVE`, that incumbent is driven from `ACTIVE` to `SUPERSEDED` — a system-driven
    transition with no client request of its own."
    PRD §3.3: "Fifth, the unit's `version` is incremented by exactly 1, so any second
    activation replayed with the same `expected_location_version` fails."
    PRD §3.3: "A drafted policy has `status` `DRAFT` and `activated_at` null."

    Design: Corner/complexity_layers/location_version_occ_on_policy_activation
    """
    set_logical_clock()
    location = new_location()
    assert location["version"] == 1, "registration leaves the unit at version 1"
    policy_a = new_draft_policy(
        location["id"], share_basis="POINTS_ONLY", cc_fee_pass_through=False
    )
    policy_b = new_draft_policy(
        location["id"],
        contribution_basis="GROSS_SALES_PCT",
        cc_fee_pass_through=False,
    )

    first = activate_policy(policy_a["id"], 1)
    assert first["status"] == "ACTIVE"
    assert_instant_equals(first["activated_at"], CLOCK, "activated_at")
    assert read_location(location["id"])["version"] == 2, "activation bumped the parent by 1"

    validate_error(
        api.activate_tip_pool_policy(
            policy_b["id"], {"expected_location_version": 1}, COMPLIANCE
        ),
        ApiErrorId.ERR_STALE_LOCATION_VERSION.value,
        expected_status=412,
    )
    refused = read_policy(policy_b["id"])
    assert refused["status"] == "DRAFT", "a 412 is not a write"
    assert refused["activated_at"] is None
    assert read_location(location["id"])["version"] == 2, (
        "the refusal did not move the parent version either"
    )

    second = activate_policy(policy_b["id"], 2)
    assert second["status"] == "ACTIVE"
    assert read_policy(policy_a["id"])["status"] == "SUPERSEDED", (
        "the incumbent is retired without any client request of its own"
    )
    assert read_location(location["id"])["version"] == 3

    validate_error(
        api.activate_tip_pool_policy(
            policy_a["id"], {"expected_location_version": 3}, COMPLIANCE
        ),
        ApiErrorId.ERR_POLICY_NOT_DRAFT.value,
        expected_status=409,
    )
    validate_error(
        api.activate_tip_pool_policy(
            policy_a["id"], {"expected_location_version": 1}, COMPLIANCE
        ),
        ApiErrorId.ERR_POLICY_NOT_DRAFT.value,
        expected_status=409,
    )

    assert read_location(location["id"])["version"] == 3, "neither refusal wrote anything"
    _rows, meta = validate_paginated(
        api.list_tip_pool_policies(
            COMPLIANCE, params={"location_id": location["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1, "only one policy per unit may hold ACTIVE at a time"


# ---------------------------------------------------------------------------
# complexity_layers / pay_line_version_occ_on_correction_issue
# ---------------------------------------------------------------------------
def _final_line_world() -> dict:
    """The Texas wage unit with one 480-minute CLOSED shift on 2026-08-04 declaring 15000
    cash tips, computed by op_prep_1 and approved by op_comp_1."""
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


def test_the_pay_line_version_has_four_writers_and_the_occ_rung_answers_first(api):
    """A request that is both stale and unpointed answers 412, and every 412 leaves the
    version exactly where the caller's next read will find it.

    PRD §2.7: "The server compares it to that line's stored `version` and rejects a mismatch
    with `ERR_STALE_PAY_LINE_VERSION` (HTTP 412). On success the line's `version` increases
    by exactly 1. Because computing a period, approving it, reopening it, adjudicating a
    dispute on the line, and applying an earlier correction to the line all bump that line's
    `version`, a client that read the line before any of those operations is reliably
    rejected rather than being allowed to overwrite `pending_correction_cents` it never
    observed."
    PRD §2.10: "24. `expected_pay_line_version` equals the stored `version` of the
    correction's target line — `ERR_STALE_PAY_LINE_VERSION`, 412, on
    `POST /back-wage-corrections`."
    PRD §2.10: "37. `supersedes_correction_id`, when supplied, names a correction whose
    `status` is `PENDING` on the same `pay_line_id`; and it is required whenever such a
    correction already exists on that line — `ERR_SUPERSEDE_TARGET_MISMATCH`, 422, on
    `POST /back-wage-corrections`."
    PRD §2.10: "Every rule in the system occupies a fixed rung on a single precedence
    ladder, and the rule on the lowest-numbered rung that the request violates is the rule
    that produces the response; every rule below it on the ladder is never reached."
    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's `total_gross_cents`;
    the line's `version` is incremented by 1; and `applied_at` is stamped with the current
    logical instant while `applied_by_user_id` records the acting `X-User-ID`."

    Design: Corner/complexity_layers/pay_line_version_occ_on_correction_issue
    """
    world = _final_line_world()
    line_id = world["pay_line"]["id"]
    assert world["pay_line"]["status"] == "FINAL"
    assert world["pay_line"]["version"] == 2, "compute bumped the line to 1 and approve to 2"
    assert world["pay_line"]["total_gross_cents"] == 1704

    first = new_correction(
        line_id, 2, headers=COMPLIANCE_ALT, amount_cents=400,
        reason_code="SIDE_WORK_OVERAGE",
    )
    assert first["status"] == "PENDING"
    assert first["amount_cents"] == 400
    at_v3 = read_pay_line(line_id)
    assert at_v3["version"] == 3
    assert at_v3["pending_correction_cents"] == 400

    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id, 2, amount_cents=800, reason_code="POOL_SHARE_SHORTFALL"
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_STALE_PAY_LINE_VERSION.value,
        expected_status=412,
    )
    unmoved = read_pay_line(line_id)
    assert unmoved["version"] == 3, "the refusal is not a write, so the re-read converges"
    assert unmoved["pending_correction_cents"] == 400
    _rows, meta = validate_paginated(
        api.list_back_wage_corrections(COMPLIANCE, params={"pay_line_id": line_id})
    )
    assert meta["total_count"] == 1, "the stale request stored nothing"

    second = new_correction(
        line_id, 3, headers=COMPLIANCE_ALT,
        supersedes_correction_id=first["id"],
        amount_cents=800,
        reason_code="POOL_SHARE_SHORTFALL",
    )
    assert second["supersedes_correction_id"] == first["id"]
    assert read_correction(first["id"])["status"] == "VOIDED"
    at_v4 = read_pay_line(line_id)
    assert at_v4["version"] == 4
    assert at_v4["pending_correction_cents"] == 800

    applied = validate_success(
        api.apply_back_wage_correction(second["id"], PREPARER)
    )
    assert applied["status"] == "APPLIED"
    at_v5 = read_pay_line(line_id)
    assert at_v5["version"] == 5
    assert at_v5["correction_applied_cents"] == 800
    assert at_v5["pending_correction_cents"] == 0
    assert at_v5["total_gross_cents"] == 2504, "1704 of wages plus the 800 now paid"

    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line_id, 3, amount_cents=200, reason_code="TIP_CREDIT_INVALID"
            ),
            COMPLIANCE_ALT,
        ),
        ApiErrorId.ERR_STALE_PAY_LINE_VERSION.value,
        expected_status=412,
    )

    third = new_correction(
        line_id, 5, headers=COMPLIANCE_ALT, amount_cents=200,
        reason_code="TIP_CREDIT_INVALID",
    )
    assert third["status"] == "PENDING"
    assert third["dispute_id"] is None
    assert third["supersedes_correction_id"] is None, "the VOIDED and APPLIED rows are past"
    at_v6 = read_pay_line(line_id)
    assert at_v6["version"] == 6
    assert at_v6["pending_correction_cents"] == 200
    assert at_v6["total_gross_cents"] == 2504, "a PENDING correction pays nothing yet"


# ---------------------------------------------------------------------------
# complexity_layers / eight_percent_allocated_tips_threshold_boundary
# ---------------------------------------------------------------------------
def _reporting_world() -> dict:
    """The Texas wage unit with one 480-minute CLOSED shift on 2026-08-04 carrying 100000
    of gross sales and no card sales, so the reporting threshold is exactly 8000."""
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        gross_sales_cents=100000,
        charged_sales_cents=0,
    )
    close_shift(shift["id"])
    world["shift"] = shift
    return world


def _settle(world: dict, declared: int) -> dict:
    """Declare that much cash on the one shift, then compute and approve, returning the
    single FINAL pay line the round produced."""
    declare_shift_tips(world["shift"]["id"], world["employee"]["id"], declared, 0)
    compute_period(world["pay_period"]["id"])
    approve_period(world["pay_period"]["id"])
    live = list_pay_lines_of(world["pay_period"]["id"], status="FINAL")
    assert len(live) == 1, "one employee, so one live line per round"
    return live[0]


def test_the_eight_percent_comparison_is_strict_and_the_allocation_is_inert(api):
    """One cent below the threshold allocates one cent, exactly at it allocates nothing, and
    the tip credit is 4096 in all three rounds.

    PRD §3.8: "The threshold is eight percent of the period's `gross_receipts_cents`,
    rounded half up. The period's `reported_tips_cents` is the sum of `reported_tips_cents`
    over the period's non-`SUPERSEDED` pay lines. The comparison is **strictly less than**:
    if reported tips are strictly below the threshold, `allocation_shortfall_cents` is the
    threshold less the reported tips; if reported tips equal or exceed the threshold,
    `allocation_shortfall_cents` is 0 and every line's `allocated_tips_cents` is 0."
    PRD §3.8: "Allocated tips are a reporting figure and nothing more: they are written to
    `allocated_tips_cents`, are never added to `total_gross_cents`, and never enlarge
    `tips_available_cents` for the purpose of the tip credit."
    PRD §3.8: "Where a shortfall exists it is split across the **directly tipped** lines
    only — those whose employee worked at least one `CLOSED` shift on a job role whose
    `tip_status` is `TIPPED` and whose `is_management` is false — pro rata by each
    employee's summed `gross_sales_cents` across their shifts."
    PRD §3.8: "Reopening marks every pay line of the period whose `status` is `DRAFT` or
    `FINAL` as `SUPERSEDED`; sets `compute_variant`, `computed_by_user_id` and
    `approved_by_user_id` all back to null and `allocation_shortfall_cents` back to 0;
    zeroes `total_tip_credit_cents`, `total_topup_cents` and `reported_tips_cents`; and
    releases every service charge whose `allocated_pay_period_id` names this period from
    `ALLOCATED` back to `RECORDED`, clearing `allocated_pay_period_id` to null so the charge
    is available to be absorbed again by the next compute."
    PRD §3.8: "`reported_tips_cents` is `retained_tips_cents` plus `pool_tips_cents`, and is
    the figure the reporting test measures."
    PRD §3.5: "The declaration dimension moves `UNDECLARED → DECLARED` on the first
    declaration, `DECLARED → AMENDED` on the second, and thereafter cycles
    `AMENDED → AMENDED` without bound for as long as the period stays `OPEN` and the shift
    stays unpooled."

    Design: Corner/complexity_layers/eight_percent_allocated_tips_threshold_boundary
    """
    world = _reporting_world()
    period_id = world["pay_period"]["id"]

    line_a = _settle(world, 7000)
    below = read_pay_period(period_id)
    assert below["gross_receipts_cents"] == 100000
    assert below["reported_tips_cents"] == 7000
    assert below["allocation_shortfall_cents"] == 1000, "the threshold is 8000"
    assert line_a["reported_tips_cents"] == 7000
    assert line_a["allocated_tips_cents"] == 1000, "the sole directly tipped line takes it all"
    assert line_a["tips_available_cents"] == 7000
    assert line_a["tip_credit_cents"] == 4096
    assert line_a["topup_cents"] == 0
    assert line_a["total_gross_cents"] == 1704, "allocated tips are not compensation"

    reopened = reopen_period(period_id, "tip declaration amended")
    assert reopened["status"] == "OPEN"
    assert reopened["allocation_shortfall_cents"] == 0
    assert reopened["reported_tips_cents"] == 0
    assert read_pay_line(line_a["id"])["status"] == "SUPERSEDED"

    line_b = _settle(world, 8000)
    at_threshold = read_pay_period(period_id)
    assert at_threshold["reported_tips_cents"] == 8000
    assert at_threshold["allocation_shortfall_cents"] == 0, (
        "the comparison is strictly less than, and 8000 is not below 8000"
    )
    assert line_b["allocated_tips_cents"] == 0
    assert line_b["tip_credit_cents"] == 4096
    assert line_b["total_gross_cents"] == 1704
    assert line_b["id"] != line_a["id"], "each compute inserts a fresh line set"

    reopen_period(period_id, "tip declaration amended again")
    line_c = _settle(world, 7999)
    one_below = read_pay_period(period_id)
    assert one_below["reported_tips_cents"] == 7999
    assert one_below["allocation_shortfall_cents"] == 1, (
        "one cent below the threshold produces exactly one cent of allocated tips"
    )
    assert line_c["allocated_tips_cents"] == 1
    assert line_c["reported_tips_cents"] == 7999
    assert line_c["tip_credit_cents"] == 4096
    assert line_c["total_gross_cents"] == 1704

    amended = read_shift(world["shift"]["id"])
    assert amended["declaration_status"] == "AMENDED"
    assert amended["declaration_count"] == 3
    assert amended["gross_sales_cents"] == 100000, "the receipts never moved"

    rows, meta = validate_paginated(
        api.list_pay_lines(PREPARER, params={"pay_period_id": period_id})
    )
    assert meta["total_count"] == 3
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["FINAL", "SUPERSEDED", "SUPERSEDED"]
