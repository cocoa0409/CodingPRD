"""Financial freezes: the estimated vs substantiated exposure dual variant, the
case-state gate on freezing, the 24h cool-down geometry, money conservation
across freeze/lift, and the freeze/lift state and RBAC guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_freeze_payload,
)
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _two_account_financial_case():
    fx.set_clock("2026-06-01T00:00:00Z")
    client = fx.new_client()
    acc1 = fx.new_account(client["id"], total_balance_cents=3_000_000)
    acc2 = fx.new_account(client["id"], total_balance_cents=2_500_000)
    report = fx.new_report(client["id"], allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    case_id = fx.screen_in(report["id"])["case_id"]
    fx.open_investigation(case_id)
    return client, acc1, acc2, case_id


# ---------------- exposure dual variant ----------------

def test_estimated_exposure_sums_full_account_balances(api):
    """PRD §3.5: "The `estimated_exposure_cents` is the projected worst-case
    exposure: the sum of the full `total_balance_cents` of every account that
    currently holds an active freeze in the case."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_substantiated_diverge
    """
    client, acc1, acc2, case_id = _two_account_financial_case()
    fx.create_active_freeze(case_id, acc1["id"], 1_200_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.create_active_freeze(case_id, acc2["id"], 800_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    case = fx.get_case(case_id)
    assert case["estimated_exposure_cents"] == 5_500_000, (
        f"estimated should sum full balances 3,000,000+2,500,000; got {case['estimated_exposure_cents']}"
    )


def test_substantiated_exposure_sums_flagged_amounts(api):
    """PRD §3.5: "The `substantiated_exposure_cents` is the verified figure: the
    sum of the `flagged_amount_cents` of every active freeze in the case, and it
    is typically strictly smaller than the estimated figure for the same
    accounts."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_substantiated_diverge
    """
    client, acc1, acc2, case_id = _two_account_financial_case()
    fx.create_active_freeze(case_id, acc1["id"], 1_200_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.create_active_freeze(case_id, acc2["id"], 800_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    case = fx.get_case(case_id)
    assert case["substantiated_exposure_cents"] == 2_000_000, (
        f"substantiated should sum flagged 1,200,000+800,000; got {case['substantiated_exposure_cents']}"
    )
    assert case["substantiated_exposure_cents"] != case["estimated_exposure_cents"]


# ---------------- freeze gated by case state ----------------

def test_freeze_on_open_case_rejected(api):
    """PRD §3.5: "the case must actually concern financial exploitation and be
    under investigation: its `allegation_types` must include
    `FINANCIAL_EXPLOITATION` and its `status` must be `UNDER_INVESTIGATION`, or
    the freeze is refused with `ERR_NOT_FINANCIAL_EXPLOITATION` (422)."

    Design: Difficulty/cross_entity_state_dependency/freeze_requires_case_under_investigation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    client = fx.new_client()
    acc = fx.new_account(client["id"], total_balance_cents=400_000)
    report = fx.new_report(client["id"], allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    case_id = fx.screen_in(report["id"])["case_id"]  # OPEN, no investigation opened
    resp = api.create_freeze(
        create_freeze_payload(case_id, acc["id"], 100_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z"),
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FINANCIAL_EXPLOITATION.value)


def test_freeze_rejection_leaves_case_open(api):
    """PRD §3.5: "its `status` must be `UNDER_INVESTIGATION`, or the freeze is
    refused with `ERR_NOT_FINANCIAL_EXPLOITATION` (422)." A rejected freeze must
    not advance the still-OPEN case.

    Design: Difficulty/cross_entity_state_dependency/freeze_requires_case_under_investigation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    client = fx.new_client()
    acc = fx.new_account(client["id"], total_balance_cents=400_000)
    report = fx.new_report(client["id"], allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    case_id = fx.screen_in(report["id"])["case_id"]
    api.create_freeze(
        create_freeze_payload(case_id, acc["id"], 100_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z"),
        CASEWORKER,
    )
    case = fx.get_case(case_id)
    assert case["status"] == "OPEN", f"case should remain OPEN after a rejected freeze; got {case['status']}"


# ---------------- 24h cool-down geometry ----------------

def test_freeze_within_cooldown_window_rejected(api):
    """PRD §3.5: "a mandatory cool-down separates successive freezes on the same
    account: the new `freeze_start` must be at least 24 hours after the
    `freeze_end` of the most recent prior freeze on that account. Because the
    cool-down uses closed-interval semantics, a `freeze_start` that falls within
    the 24-hour window after that prior `freeze_end` is rejected with
    `ERR_FREEZE_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/freeze_account_buffer_cooldown_overlap
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=900_000)
    fz1 = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 200_000,
                                  "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z")
    fx.lift_freeze(fz1["id"])
    resp = api.create_freeze(
        create_freeze_payload(ctx["case_id"], ctx["account"]["id"], 150_000,
                              "2026-06-05T12:00:00Z", "2026-06-10T00:00:00Z"),  # only 12h after prior end
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_FREEZE_WINDOW_OVERLAP.value)


def test_freeze_after_full_cooldown_accepted(api):
    """PRD §3.5: "the new `freeze_start` must be at least 24 hours after the
    `freeze_end` of the most recent prior freeze on that account." A start
    exactly 24 hours after the prior freeze_end satisfies the cool-down.

    Design: Difficulty/resource_temporal_overlap/freeze_account_buffer_cooldown_overlap
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=900_000)
    fz1 = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 200_000,
                                  "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z")
    fx.lift_freeze(fz1["id"])
    resp = api.create_freeze(
        create_freeze_payload(ctx["case_id"], ctx["account"]["id"], 150_000,
                              "2026-06-06T00:00:00Z", "2026-06-10T00:00:00Z"),  # exactly prior end + 24h
        CASEWORKER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


# ---------------- money conservation across freeze/lift ----------------

def test_lift_restores_available_balance(api):
    """PRD §3.5: "Lifting a freeze ... toggles the account back from `FROZEN` to
    `ACTIVE` by resetting `frozen_amount_cents` to zero, `available_balance_cents`
    back to `total_balance_cents`, and `flagged_amount_cents` to zero."

    Design: Difficulty/compensating_invariant/money_conservation_freeze_then_lift
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=1_000_000)
    fz = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 600_000,
                                 "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    resp = api.lift_freeze(fz["id"], SUPERVISOR)
    data = validate_success(resp)
    assert data["status"] == "LIFTED"
    account = fx.get_account(ctx["account"]["id"])
    assert account["available_balance_cents"] == 1_000_000


def test_lift_conserves_account_total(api):
    """PRD §3.5: "with the standing invariant that available plus frozen always
    equals the total". After freeze-then-lift on a 1,000,000-cent account,
    frozen returns to zero and the total is conserved.

    Design: Difficulty/compensating_invariant/money_conservation_freeze_then_lift
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=1_000_000)
    fz = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 600_000,
                                 "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    api.lift_freeze(fz["id"], SUPERVISOR)
    account = fx.get_account(ctx["account"]["id"])
    assert account["frozen_amount_cents"] == 0
    assert account["available_balance_cents"] + account["frozen_amount_cents"] == account["total_balance_cents"] == 1_000_000


# ---------------- freeze state / RBAC guards (queue B) ----------------

def test_account_already_frozen_returns_409(api):
    """PRD §3.5: "the target account must currently be `ACTIVE`; freezing an
    already-frozen account yields `ERR_ACCOUNT_ALREADY_FROZEN` (409)."

    Design: Corner/validations/account_already_frozen_returns_409
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=500_000)
    fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 100_000,
                            "2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_freeze(
        create_freeze_payload(ctx["case_id"], ctx["account"]["id"], 50_000,
                              "2026-06-02T00:00:00Z", "2026-06-11T00:00:00Z"),
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ALREADY_FROZEN.value)


def test_lift_non_active_freeze_returns_invalid_state(api):
    """PRD §3.5: "Lifting a freeze is a `Supervisor` action: it requires the
    freeze to be `ACTIVE` (otherwise `ERR_FREEZE_INVALID_STATE`, 409)".

    Design: Corner/state_machines/lift_non_active_freeze_returns_invalid_state
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=300_000)
    fz = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 100_000,
                                 "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.lift_freeze(fz["id"])
    resp = api.lift_freeze(fz["id"], SUPERVISOR)  # already LIFTED
    validate_error(resp, ApiErrorId.ERR_FREEZE_INVALID_STATE.value)


def test_caseworker_cannot_lift_freeze_returns_403(api):
    """PRD §4: "POST `/freezes/{id}/lift` — Lift an active freeze — Supervisor".
    PRD §2.1: "If the headers are valid but the acting role is not permitted to
    perform the requested operation according to the authorization matrix in
    Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/caseworker_cannot_lift_freeze_returns_403
    """
    ctx = fx.create_financial_case_with_account(total_balance_cents=200_000)
    fz = fx.create_active_freeze(ctx["case_id"], ctx["account"]["id"], 50_000,
                                 "2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.lift_freeze(fz["id"], CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
