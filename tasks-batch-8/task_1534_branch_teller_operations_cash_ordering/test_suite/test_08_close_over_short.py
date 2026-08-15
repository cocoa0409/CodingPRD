"""Closing ceremony: dual control, variance, over/short cases, OCC on close."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, setup_out_of_balance, deposit, teller_h,
)

MGR = TEST_USERS["manager_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_attest_severe_variance_opens_case(api):
    """PRD §3.8: "A variance whose absolute value reaches or exceeds the
    branch's `over_short_investigation_threshold_cents` automatically opens an
    `OverShortCase` — `OPEN`, stamped with the `business_date`, linked to the
    `drawer_id`, and carrying a copy of the signed `variance_cents`."

    Design: Difficulty/transitive_cascade/attest_severe_variance_cascades_to_case_and_suspension
    """
    ctx, case = setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=45_000)
    assert ctx["drawer"]["status"] == "OUT_OF_BALANCE"
    assert ctx["drawer"]["variance_cents"] == -5_000
    assert case is not None
    assert case["status"] == "OPEN"
    assert case["variance_cents"] == -5_000
    assert case["drawer_id"] == ctx["drawer"]["id"]


def test_attest_severe_variance_suspends_teller(api):
    """PRD §3.8: "a case whose absolute variance reaches or exceeds twice the
    threshold automatically suspends the drawer's teller, moving them from
    `ACTIVE` to `SUSPENDED` without any human call."

    Design: Difficulty/transitive_cascade/attest_severe_variance_cascades_to_case_and_suspension
    """
    ctx, case = setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=45_000)
    assert case is not None and abs(case["variance_cents"]) >= 2_000
    teller = validate_success(api.get_teller(ctx["teller"]["id"], MGR))
    assert teller["status"] == "SUSPENDED"


def test_over_short_case_lifecycle_gates_drawer_close(api):
    """PRD §3.8: "An `OUT_OF_BALANCE` drawer closes only once its over/short
    case — if one was created — has reached `RESOLVED` or `WAIVED`; closing
    earlier is refused with `ERR_OVER_SHORT_UNRESOLVED`."

    Design: Corner/state_machines/over_short_case_lifecycle_gates_drawer_close
    """
    # variance -1000: at the 1000 threshold (case opens) but below 2x (teller stays)
    ctx, case = setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=49_000)
    assert case is not None and case["status"] == "OPEN"
    teller = validate_success(api.get_teller(ctx["teller"]["id"], MGR))
    assert teller["status"] == "ACTIVE"
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    resp = api.close_drawer(drawer["id"], drawer["version"], MGR)
    validate_error(resp, "ERR_OVER_SHORT_UNRESOLVED", 409)
    investigated = validate_success(api.investigate_case(case["id"], MGR))
    assert investigated["status"] == "UNDER_INVESTIGATION"
    resolved = validate_success(api.resolve_case(case["id"], MGR))
    assert resolved["status"] == "RESOLVED"
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    closed = validate_success(api.close_drawer(drawer["id"], drawer["version"], MGR))
    assert closed["status"] == "CLOSED"


def test_severe_over_short_waiver_rejected(api):
    """PRD §3.8: "a case at or beyond twice the threshold is too serious to
    waive and refuses with `ERR_WAIVER_NOT_ALLOWED`."

    Design: Corner/errors/severe_over_short_waiver_rejected
    """
    # severe case: variance -5000 >= 2 * 1000
    ctx, case = setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=45_000)
    resp = api.waive_case(case["id"], MGR)
    validate_error(resp, "ERR_WAIVER_NOT_ALLOWED", 422)
    # non-severe case (variance -1500 < 2000) waives and records the decision
    ctx2, case2 = setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=48_500)
    waived = validate_success(api.waive_case(case2["id"], MGR))
    assert waived["status"] == "WAIVED"
    approvals = get_success_data(api.list_approvals(MGR, {"branch_id": ctx2["branch"]["id"]}))
    assert approvals[0]["action_type"] == "OVER_SHORT_WAIVER"
    assert approvals[0]["subject_id"] == case2["id"]


def test_dual_control_attest_by_counting_teller_rejected(api):
    """PRD §3.8: "If the attestor's `X-User-ID` equals the drawer's
    `teller_id`, the attempt fails with `ERR_DUAL_CONTROL_VIOLATION` and the
    drawer stays `COUNTING`."

    Design: Corner/validations/dual_control_attest_by_counting_teller_rejected
    """
    ctx = basic_setup(api)
    validate_success(api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"]))
    # BranchManager role but the counting teller's id -> dual-control violation
    resp = api.attest_drawer(ctx["drawer"]["id"],
                             {"X-User-ID": ctx["teller"]["id"], "X-User-Role": "BranchManager"})
    validate_error(resp, "ERR_DUAL_CONTROL_VIOLATION", 409)
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    assert drawer["status"] == "COUNTING"


def test_close_closed_drawer_rejected(api):
    """PRD §3.8: "Close is not idempotent: a `CLOSED` drawer rejects a second
    close with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_closed_drawer_rejected
    """
    ctx = basic_setup(api)
    validate_success(api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"]))
    attested = validate_success(api.attest_drawer(ctx["drawer"]["id"], MGR))
    closed = validate_success(api.close_drawer(ctx["drawer"]["id"], attested["version"], MGR))
    assert closed["status"] == "CLOSED"
    resp = api.close_drawer(ctx["drawer"]["id"], closed["version"], MGR)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_close_with_stale_drawer_version_rejected(api):
    """PRD §2.6: "Closing a teller drawer requires `expected_drawer_version`,
    the drawer's `version` as last observed. A mismatch with the drawer's
    current `version` — for example because a recount or an audit adjustment
    advanced it — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/close_with_stale_drawer_version_rejected
    """
    ctx = basic_setup(api)
    stale_version = ctx["drawer"]["version"]  # 1, from creation
    validate_success(api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"]))
    attested = validate_success(api.attest_drawer(ctx["drawer"]["id"], MGR))
    resp = api.close_drawer(ctx["drawer"]["id"], stale_version, MGR)
    validate_error(resp, "ERR_STALE_VERSION", 412)
    closed = validate_success(api.close_drawer(ctx["drawer"]["id"], attested["version"], MGR))
    assert closed["status"] == "CLOSED"
