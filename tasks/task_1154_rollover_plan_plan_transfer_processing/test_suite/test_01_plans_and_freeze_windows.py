"""Plan configuration defaults, plan lifecycle guards, and the freeze cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_approved_indirect_case,
    get_account,
    get_case,
    is_valid_uuid,
    make_admin_headers,
    make_plan,
    make_processor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plan_creation_applies_defaults(api):
    """PRD §3.1: "A plan's behavior is shaped by seven capability flags, each
    defaulting to `true` when omitted at creation: `accepts_incoming_rollovers`
    (whether the plan credits inbound rollovers), `accepts_incoming_transfers`
    (whether it accepts plan-to-plan transfers in), `accepts_loan_transfers`
    (whether it accepts loan notes moved with a transfer),
    `accepts_after_tax_basis` (whether it accepts after-tax, non-Roth basis on
    inbound money), `allows_in_plan_roth_conversion` (whether participants may
    convert in-plan balances to Roth), `requires_spousal_consent` (whether
    married participants need spousal consent for money leaving the plan), and
    `spousal_consent_threshold_cents` (the balance above which consent is
    required, defaulting to 500000 cents — the statutory five-thousand-dollar
    line)."
    PRD §3.1: "A plan is created in `ACTIVE` status and may move
    `ACTIVE → FROZEN`, `FROZEN → ACTIVE`, or `ACTIVE → TERMINATED`, all at the
    hands of a `PlanSponsorAdmin`."
    PRD §2.5: "`version` (integer): a system-managed integer starting at 1 on
    creation and incrementing by exactly 1 on every mutation."

    Design: Corner/entities/plan_creation_applies_defaults
    """
    resp = api.create_plan(
        {"plan_name": "Defaults Plan", "plan_type": "PLAN_403B"}, make_admin_headers()
    )
    plan = validate_success(resp, expected_status=201)
    assert plan["status"] == "ACTIVE", f"plan must start ACTIVE, got {plan['status']}"
    assert plan["version"] == 1, f"plan version must start at 1, got {plan['version']}"
    for flag in (
        "accepts_incoming_rollovers",
        "accepts_incoming_transfers",
        "accepts_loan_transfers",
        "accepts_after_tax_basis",
        "allows_in_plan_roth_conversion",
        "requires_spousal_consent",
    ):
        assert plan[flag] is True, f"default for {flag} must be true, got {plan.get(flag)}"
    assert plan["spousal_consent_threshold_cents"] == 500000


def test_plan_create_system_fields_input_ignored(api):
    """PRD §2.5: "`id` (string): a unique, server-generated identifier formatted
    as a UUID, with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer starting at 1 on
    creation and incrementing by exactly 1 on every mutation."

    Design: Corner/entities/plan_create_system_fields_input_ignored
    """
    client_id = "11111111-2222-4333-8444-555555555555"
    resp = api.create_plan(
        {
            "plan_name": "SysFields",
            "plan_type": "IRA",
            "id": client_id,
            "version": 99,
            "created_at": "2001-01-01T00:00:00.000Z",
        },
        make_admin_headers(),
    )
    plan = validate_success(resp, expected_status=201)
    assert is_valid_uuid(plan["id"])
    assert plan["id"] != client_id, "server must mint its own id, not honor the client's"
    assert plan["version"] == 1, f"server-managed version must start at 1, got {plan['version']}"


def test_plan_state_guards(api):
    """PRD §3.1: "Freezing a plan that is already `FROZEN` is rejected with
    `ERR_PLAN_FROZEN`; freezing a `TERMINATED` plan is rejected with
    `ERR_PLAN_TERMINATED`. Unfreezing a plan that is not `FROZEN` is rejected
    with `ERR_PLAN_NOT_FROZEN`. Terminating a plan that is already `TERMINATED`
    is likewise rejected with `ERR_PLAN_TERMINATED`."

    Design: Corner/validations/plan_state_guards
    """
    admin = make_admin_headers()
    plan_a = make_plan(name="Plan A")
    plan_b = make_plan(name="Plan B", plan_type="PLAN_403B")

    validate_success(api.freeze_plan(plan_a["id"], admin))
    resp = api.freeze_plan(plan_a["id"], admin)
    validate_error(resp, ApiErrorId.ERR_PLAN_FROZEN)

    resp = api.unfreeze_plan(plan_b["id"], admin)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FROZEN)

    validate_success(api.terminate_plan(plan_b["id"], admin))
    resp = api.terminate_plan(plan_b["id"], admin)
    validate_error(resp, ApiErrorId.ERR_PLAN_TERMINATED)


def test_plan_freeze_cascade_suspends_case_and_cancels_disbursement(api):
    """PRD §3.1: "**Link 1:** every rollover case whose source or receiving
    account sits at this plan and whose status is non-terminal — that is, in
    `DRAFT`, `DOCS_PENDING`, `ELIGIBILITY_REVIEW`, `ELIGIBLE`, `DISBURSED`,
    `AWAITING_REDEPOSIT`, or `ACCEPTANCE_PENDING` — records its current status
    into `prior_status` and transitions to `SUSPENDED`. **Link 2:** every
    disbursement pointing at a case that just became `SUSPENDED` and still in
    `PENDING` transitions to `CANCELLED`."

    Design: Difficulty/transitive_cascade/plan_freeze_cascade
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    case = bundle["case"]
    # Assemble only (PENDING disbursement, balances debited, not yet issued).
    resp = api.assemble_disbursement(
        case["id"], {"method": "ACH"}, make_processor_headers("proc-2")
    )
    disb = validate_success(resp)

    resp = api.freeze_plan(bundle["plan"]["id"], make_admin_headers())
    plan = validate_success(resp)
    assert plan["status"] == "FROZEN", f"plan must be FROZEN, got {plan['status']}"

    frozen_case = get_case(case["id"])
    assert frozen_case["status"] == "SUSPENDED", (
        f"link 1: case must be SUSPENDED, got {frozen_case['status']}"
    )
    assert frozen_case["prior_status"] == "ELIGIBLE", (
        f"link 1: prior_status must record ELIGIBLE, got {frozen_case['prior_status']}"
    )

    resp = api.list_case_disbursements(case["id"], make_processor_headers("proc-1"))
    disbs, _ = validate_paginated(resp)
    assert len(disbs) == 1
    assert disbs[0]["id"] == disb["id"]
    assert disbs[0]["status"] == "CANCELLED", (
        f"link 2: PENDING disbursement of a suspended case must be CANCELLED, "
        f"got {disbs[0]['status']}"
    )


def test_plan_freeze_cascade_restores_balances_and_unfreeze_resumes(api):
    """PRD §3.1: "**Link 3:** each disbursement cancelled this way restores the
    debited source balances exactly — every money-source row of the case's
    source account is credited back precisely the amount that source contributed
    at issuance, a full reversal of the issue-time debit, and the account's
    computed totals recompute."
    PRD §3.1: "Unfreezing reverses link 1 only: every `SUSPENDED` case with a
    `prior_status` recorded, resolving to this plan, returns to its
    `prior_status`, and `prior_status` is cleared."

    Design: Difficulty/transitive_cascade/plan_freeze_cascade
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    case = bundle["case"]
    account = bundle["account"]
    resp = api.assemble_disbursement(
        case["id"], {"method": "ACH"}, make_processor_headers("proc-2")
    )
    validate_success(resp)

    validate_success(api.freeze_plan(bundle["plan"]["id"], make_admin_headers()))

    acct = get_account(account["id"])
    assert acct["vested_balance_cents"] == 10800000, (
        f"link 3: vested balance must be restored to 10800000, got {acct['vested_balance_cents']}"
    )
    assert acct["total_balance_cents"] == 11600000, (
        f"link 3: total balance must be restored to 11600000, got {acct['total_balance_cents']}"
    )

    validate_success(api.unfreeze_plan(bundle["plan"]["id"], make_admin_headers()))
    resumed = get_case(case["id"])
    assert resumed["status"] == "ELIGIBLE", (
        f"unfreeze must resume the case to its prior_status ELIGIBLE, got {resumed['status']}"
    )
    assert resumed.get("prior_status") is None, (
        f"prior_status must be cleared on resume, got {resumed.get('prior_status')}"
    )
