"""Payroll handoff lifecycle, OCC, supersede/withdraw, proration, and benefits window."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_in_progress,
    setup_handoff_ready,
    create_handoff_for_case,
    get_case_handoffs,
    get_summary,
    make_hr_admin_headers,
)

HR = TEST_USERS["hr_admin_headers"]
PAYROLL = TEST_USERS["payroll_ops_headers"]


def test_first_period_gross_per_component_rounding_order(api):
    """PRD §2.10: "The first-period proration rounds **per component first, then
    sums**: each of the three compensation components is multiplied by the
    employment ratio and rounded half-up to whole cents independently, and the
    gross is the sum of those three rounded figures. The alternative order —
    summing unrounded components and rounding once — is forbidden because it
    yields different cents for identical inputs; for example, components of
    90000, 10000, and 2500 cents across 11 employed days of a 14-day period
    produce 80535 under the mandated per-component order but 80536 under
    sum-then-round."

    Design: Difficulty/combinatorial_formula/first_period_gross_per_component_rounding_order
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]
    # start_date 2026-05-04; period 2026-05-01..2026-05-14 -> 11 of 14 days employed.
    handoff = create_handoff_for_case(
        case_id, ctx["case_version"],
        first_period_start_date="2026-05-01",
        first_period_end_date="2026-05-14",
    )
    # per-component: round_half_up(90000*11/14)=70714, (10000*11/14)=7857, (2500*11/14)=1964
    # sum = 80535; forbidden sum-then-round would be 80536.
    assert handoff["first_period_gross_cents"] == 80535
    assert handoff["first_period_gross_cents"] != 80536


def test_first_period_gross_components_individually_rounded(api):
    """PRD §2.10: "components of 90000, 10000, and 2500 cents across 11 employed
    days of a 14-day period produce 80535 under the mandated per-component order
    but 80536 under sum-then-round."

    Re-deriving the expected value from the rule: each component rounds half-up
    before summation.

    Design: Difficulty/combinatorial_formula/first_period_gross_per_component_rounding_order
    """
    ctx = setup_handoff_ready()
    handoff = create_handoff_for_case(
        ctx["case"]["id"], ctx["case_version"],
        first_period_start_date="2026-05-01",
        first_period_end_date="2026-05-14",
    )
    assert handoff["base_salary_cents"] == 90000
    assert handoff["signing_bonus_cents"] == 10000
    assert handoff["relocation_stipend_cents"] == 2500
    assert handoff["first_period_gross_cents"] == 80535


def test_occ_stale_version_returns_412_and_success_increments(api):
    """PRD §2.8: "That request must carry `expected_case_version`, a non-optional
    field holding the case `version` the client last observed. If
    `expected_case_version` does not match the case's current `version` —
    because another writer has advanced the case since the client last read it,
    for instance by creating a handoff that legitimately superseded the prior
    non-terminal one — the create is rejected with `ERR_STALE_VERSION` (HTTP
    412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_returns_412_and_success_increments
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]
    stale_version = ctx["case_version"] - 1

    resp = api.create_payroll_handoff(case_id, {
        "expected_case_version": stale_version,
        "first_period_start_date": "2026-05-01",
        "first_period_end_date": "2026-05-14",
    }, HR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # Correct version succeeds; case.version increments by exactly 1.
    resp2 = api.create_payroll_handoff(case_id, {
        "expected_case_version": ctx["case_version"],
        "first_period_start_date": "2026-05-01",
        "first_period_end_date": "2026-05-14",
    }, HR)
    data = validate_success(resp2, expected_status=201)
    assert data["status"] == "DRAFT"
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["version"] == ctx["case_version"] + 1


def test_open_handoff_count_conserved_under_create_withdraw_supersede(api):
    """PRD §3.9: "supersedes any existing handoffs of the case in `DRAFT` or
    `TRANSMITTED` (moving them to `SUPERSEDED`)"
    PRD §3.7: "the case summary ... `open_handoff_count` — the number of the
    case's payroll handoffs still in a non-terminal state."

    Design: Difficulty/compensating_invariant/open_handoff_count_conserved_under_create_withdraw_supersede
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]

    # Baseline: zero handoffs.
    s0 = get_summary(case_id)
    assert s0["open_handoff_count"] == 0

    # h1 create + withdraw -> count returns to 0.
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h1 = create_handoff_for_case(case_id, case["version"])
    get_success_data(api.withdraw_payroll_handoff(h1["id"], HR))
    s1 = get_summary(case_id)
    assert s1["open_handoff_count"] == 0

    # h2 then h3: h3 creation supersedes h2; count stays at 1.
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h2 = create_handoff_for_case(case_id, case["version"])
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h3 = create_handoff_for_case(case_id, case["version"])

    handoffs = get_case_handoffs(case_id)
    by_id = {h["id"]: h for h in handoffs}
    assert by_id[h1["id"]]["status"] == "WITHDRAWN"
    assert by_id[h2["id"]]["status"] == "SUPERSEDED"
    assert by_id[h3["id"]]["status"] == "DRAFT"

    s2 = get_summary(case_id)
    assert s2["open_handoff_count"] == 1

    # Withdraw h3 -> count returns to 0.
    get_success_data(api.withdraw_payroll_handoff(h3["id"], HR))
    s3 = get_summary(case_id)
    assert s3["open_handoff_count"] == 0


def test_supersede_leaves_terminal_handoffs_untouched(api):
    """PRD §3.9: "supersedes any existing handoffs of the case in `DRAFT` or
    `TRANSMITTED` (moving them to `SUPERSEDED`)"

    The rule names only DRAFT/TRANSMITTED; a WITHDRAWN handoff stays WITHDRAWN
    after a new handoff is created.

    Design: Difficulty/compensating_invariant/open_handoff_count_conserved_under_create_withdraw_supersede
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h1 = create_handoff_for_case(case_id, case["version"])
    get_success_data(api.withdraw_payroll_handoff(h1["id"], HR))

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h2 = create_handoff_for_case(case_id, case["version"])

    handoffs = {h["id"]: h for h in get_case_handoffs(case_id)}
    # WITHDRAWN is terminal — not touched by the create-with-supersede rule.
    assert handoffs[h1["id"]]["status"] == "WITHDRAWN"
    assert handoffs[h2["id"]]["status"] == "DRAFT"


def test_handoff_transmit_twice_and_withdraw_transmitted_rejected(api):
    """PRD §3.9: "From `DRAFT`, the handoff can be transmitted by an `HRAdmin`
    (any other handoff status draws `ERR_INVALID_HANDOFF_STATE`)"
    PRD §3.9: "An `HRAdmin` may instead withdraw a `DRAFT` handoff, moving it to
    `WITHDRAWN`."

    Design: Corner/state_machines/handoff_transmit_twice_and_withdraw_transmitted_rejected
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]
    handoff = create_handoff_for_case(case_id, ctx["case_version"])
    get_success_data(api.transmit_payroll_handoff(handoff["id"], HR))

    # Second transmit -> ERR_INVALID_HANDOFF_STATE.
    resp = api.transmit_payroll_handoff(handoff["id"], HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_HANDOFF_STATE)

    # Withdraw of TRANSMITTED -> ERR_INVALID_HANDOFF_STATE.
    resp2 = api.withdraw_payroll_handoff(handoff["id"], HR)
    validate_error(resp2, ApiErrorId.ERR_INVALID_HANDOFF_STATE)


def test_handoff_acknowledge_and_reject_paths(api):
    """PRD §3.9: "a `PayrollOps` operator acknowledges a `TRANSMITTED` handoff,
    moving it to `ACKNOWLEDGED` while stamping `acknowledged_at` and computing
    `benefits_window_breached`, or rejects it with a mandatory `reason` recorded
    as `rejection_reason`, moving it to `REJECTED_BY_PAYROLL`"
    PRD §3.9: "The benefits window itself closes at 23:59:59 UTC on the day
    thirty days after the case's `start_date`, recorded as
    `benefits_window_end`"

    Design: Corner/endpoints/handoff_acknowledge_and_reject_paths
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]

    h1 = create_handoff_for_case(case_id, ctx["case_version"])
    get_success_data(api.transmit_payroll_handoff(h1["id"], HR))
    r = api.acknowledge_payroll_handoff(h1["id"], PAYROLL)
    data = validate_success(r)
    assert data["status"] == "ACKNOWLEDGED"
    assert data["benefits_window_breached"] is False
    assert data["benefits_window_end"] == "2026-06-03T23:59:59Z"

    # Second handoff (after the first is terminal): transmit then reject.
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h2 = create_handoff_for_case(case_id, case["version"])
    get_success_data(api.transmit_payroll_handoff(h2["id"], HR))
    r2 = api.reject_payroll_handoff(h2["id"], {"reason": "bad bank account"}, PAYROLL)
    data2 = validate_success(r2)
    assert data2["status"] == "REJECTED_BY_PAYROLL"
    assert data2["rejection_reason"] == "bad bank account"

    # The ACKNOWLEDGED handoff was not superseded by the later create.
    h1_after = get_success_data(api.get_payroll_handoff(h1["id"], HR))
    assert h1_after["status"] == "ACKNOWLEDGED"


def test_benefits_window_boundary_exact(api):
    """PRD §3.9: "acknowledgment strictly later than that instant breaches the
    window, while acknowledgment exactly at it does not."

    h1 acknowledged exactly at benefits_window_end -> not breached;
    h2 acknowledged one second past -> breached.

    Design: Corner/calculations/benefits_window_boundary_exact
    """
    ctx = setup_handoff_ready()
    case_id = ctx["case"]["id"]
    h1 = create_handoff_for_case(case_id, ctx["case_version"])
    get_success_data(api.transmit_payroll_handoff(h1["id"], HR))

    # Acknowledge h1 at exactly benefits_window_end (2026-06-03T23:59:59Z).
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-03T23:59:59Z"}, HR))
    r1 = api.acknowledge_payroll_handoff(h1["id"], PAYROLL)
    assert validate_success(r1)["benefits_window_breached"] is False

    # Second handoff: acknowledge one second past the window.
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    h2 = create_handoff_for_case(case_id, case["version"])
    get_success_data(api.transmit_payroll_handoff(h2["id"], HR))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T00:00:00Z"}, HR))
    r2 = api.acknowledge_payroll_handoff(h2["id"], PAYROLL)
    assert validate_success(r2)["benefits_window_breached"] is True
