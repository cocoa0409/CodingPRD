"""Agreement, assignment, policy, and schedule lifecycle (PRD §3.2, §3.3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_draft_agreement, setup_executed_agreement, setup_funded_agreement,
    add_draft_schedule, activate_schedule, get_agreement, get_schedule,
    create_qualified_assignment_payload, create_annuity_policy_payload,
    create_scheduled_payment_payload,
    api_client, TEST_USERS,
)

CASE_MGR = TEST_USERS["case_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _setup_assigned_with_pending_policy():
    """Agreement EXECUTED -> ASSIGNED with a policy still PENDING_ISSUE."""
    ctx = setup_executed_agreement()
    assignment = get_success_data(api_client.create_qualified_assignment(
        create_qualified_assignment_payload(ctx["agreement"]["id"]), CASE_MGR))
    ctx["assignment"] = assignment
    ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
    ctx["policy"] = get_success_data(api_client.create_annuity_policy(
        create_annuity_policy_payload(ctx["agreement"]["id"], assignment["id"]), CASE_MGR))
    return ctx


def test_agreement_execute_twice_returns_invalid_state(api):
    """PRD §3.2: "Execution by a case manager moves the agreement `DRAFT` → `EXECUTED`
    and bumps its `version`; attempting execution from any other state fails with
    `ERR_AGREEMENT_INVALID_STATE`."

    Design: Corner/state_machines/agreement_execute_twice_returns_invalid_state
    """
    ctx = setup_executed_agreement()
    resp = api.execute_settlement_agreement(ctx["agreement"]["id"], CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)
    assert get_agreement(ctx["agreement"]["id"])["status"] == "EXECUTED"


def test_duplicate_case_number_returns_409(api):
    """PRD §3.2: "A structured settlement engagement begins when a `CaseManager` creates
    a `SettlementAgreement` with a unique `case_number` — a duplicate fails with
    `ERR_DUPLICATE_CASE_NUMBER`".

    Design: Corner/errors/duplicate_case_number_returns_409
    """
    ctx = setup_draft_agreement(agreement_overrides={"case_number": "DUP-001"})
    payload = {
        "case_number": "DUP-001", "court_state_code": "CA",
        "obligor_name": "Other Insurer", "injury_type": "NON_PHYSICAL",
        "primary_payee_id": ctx["payee"]["id"], "agreement_date": "2026-02-01",
    }
    resp = api.create_settlement_agreement(payload, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)


def test_release_twice_returns_assignment_invalid_state(api):
    """PRD §3.2: "Once a policy linked to an assignment stands `IN_FORCE` or
    `PARTIALLY_COMMUTED`, a `ComplianceOfficer` may release the obligor's novation,
    moving the assignment `EXECUTED` → `RELEASED`; releasing without such a policy fails
    with `ERR_POLICY_INVALID_STATE`, and releasing an assignment no longer `EXECUTED`
    fails with `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/errors/release_twice_returns_assignment_invalid_state
    """
    ctx = setup_funded_agreement()
    released = validate_success(
        api.release_qualified_assignment(ctx["assignment"]["id"], COMPLIANCE))
    assert released["status"] == "RELEASED"
    resp = api.release_qualified_assignment(ctx["assignment"]["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)


def test_mark_in_force_twice_returns_policy_invalid_state(api):
    """PRD §3.2: "Marking the policy in force — a case manager supplying `in_force_date`
    — moves it `PENDING_ISSUE` → `IN_FORCE` (`ERR_POLICY_INVALID_STATE` from any other
    state)".

    Design: Corner/errors/mark_in_force_twice_returns_policy_invalid_state
    """
    ctx = setup_funded_agreement()
    assert ctx["policy"]["status"] == "IN_FORCE"
    resp = api.mark_policy_in_force(ctx["policy"]["id"], {"in_force_date": "2026-01-26"}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_POLICY_INVALID_STATE)


def test_schedule_activation_blocked_until_policy_in_force(api):
    """PRD §3.3: "the agreement must be `FUNDED` or `ACTIVE` (`ERR_AGREEMENT_INVALID_STATE`)".
    PRD §3.2: "Marking the policy in force — a case manager supplying `in_force_date`
    — moves it `PENDING_ISSUE` → `IN_FORCE` (`ERR_POLICY_INVALID_STATE` from any other
    state), requires the linked agreement still `ASSIGNED` (`ERR_AGREEMENT_INVALID_STATE`),
    stamps `in_force_date`, bumps the policy's `version`, and cascades the agreement
    `ASSIGNED` → `FUNDED` with its own version increment."

    Design: Difficulty/cross_entity_state_dependency/funding_requires_policy_in_force
    """
    ctx = _setup_assigned_with_pending_policy()
    add_draft_schedule(ctx, [{"due_date": "2027-03-01", "base_amount_cents": 80000}])

    # Agreement is ASSIGNED (policy still PENDING_ISSUE): activation is blocked.
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "ASSIGNED"
    resp = api.activate_payment_schedule(
        ctx["schedule"]["id"],
        {"expected_settlement_agreement_version": agreement["version"]}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)


def test_mark_in_force_cascade_opens_schedule_activation(api):
    """PRD §3.2: "Marking the policy in force — a case manager supplying `in_force_date`
    — moves it `PENDING_ISSUE` → `IN_FORCE` (`ERR_POLICY_INVALID_STATE` from any other
    state), requires the linked agreement still `ASSIGNED` (`ERR_AGREEMENT_INVALID_STATE`),
    stamps `in_force_date`, bumps the policy's `version`, and cascades the agreement
    `ASSIGNED` → `FUNDED` with its own version increment."
    PRD §3.3: "On success the schedule moves `DRAFT` → `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/funding_requires_policy_in_force
    """
    ctx = _setup_assigned_with_pending_policy()
    add_draft_schedule(ctx, [{"due_date": "2027-03-01", "base_amount_cents": 80000}])

    policy = validate_success(api.mark_policy_in_force(
        ctx["policy"]["id"], {"in_force_date": "2026-01-25"}, CASE_MGR))
    assert policy["status"] == "IN_FORCE"
    assert get_agreement(ctx["agreement"]["id"])["status"] == "FUNDED", (
        "mark-in-force cascades the linked agreement ASSIGNED -> FUNDED"
    )

    schedule = activate_schedule(ctx)
    assert schedule["status"] == "ACTIVE", "activation succeeds once the cross-entity gate opens"


def test_payment_create_with_client_amount_returns_invalid_request(api):
    """PRD §2.10: "and no unknown payload fields — all rejected as `ERR_INVALID_REQUEST`
    (HTTP 400)".
    PRD §3.3: "Escalation computes two amounts at creation." — `amount_cents` is
    server-computed, so a client-supplied value is an unknown field.

    Design: Corner/entities/payment_create_with_client_amount_returns_invalid_request
    """
    ctx = setup_executed_agreement(agreement_overrides={"case_number": "EN-001"})
    add_draft_schedule(ctx, [])
    payload = create_scheduled_payment_payload(ctx["schedule"]["id"], ctx["payee"]["id"],
                                               1, "2027-01-01", 50000)
    payload["amount_cents"] = 1
    resp = api.create_scheduled_payment(payload, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_add_payment_to_active_schedule_returns_invalid_state(api):
    """PRD §3.3: "Rows are added one at a time by a case manager: `payment_schedule_id`,
    which must reference a `DRAFT` schedule (`ERR_SCHEDULE_INVALID_STATE` otherwise)".

    Design: Corner/errors/add_payment_to_active_schedule_returns_invalid_state
    """
    ctx = setup_funded_agreement()
    add_draft_schedule(ctx, [{"due_date": "2027-01-01", "base_amount_cents": 30000}])
    activate_schedule(ctx)

    resp = api.create_scheduled_payment(
        create_scheduled_payment_payload(ctx["schedule"]["id"], ctx["payee"]["id"], 2,
                                         "2027-02-01", 31000), CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_INVALID_STATE)


def test_activate_empty_schedule_returns_has_payments_error(api):
    """PRD §3.3: "The schedule must then be `DRAFT` (`ERR_SCHEDULE_INVALID_STATE`), must
    contain at least one payment row (`ERR_SCHEDULE_HAS_PAYMENTS`), and the agreement
    must be `FUNDED` or `ACTIVE`".

    Design: Corner/errors/activate_empty_schedule_returns_has_payments_error
    """
    ctx = setup_funded_agreement()
    add_draft_schedule(ctx, [])
    agreement = get_agreement(ctx["agreement"]["id"])
    resp = api.activate_payment_schedule(
        ctx["schedule"]["id"],
        {"expected_settlement_agreement_version": agreement["version"]}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_HAS_PAYMENTS)


def test_schedule_supersede_cancels_pending_payments(api):
    """PRD §3.3: "On success the schedule moves `DRAFT` → `ACTIVE`; whichever schedule
    was previously `ACTIVE` for the same agreement, if any, becomes `SUPERSEDED`, and
    the new schedule's `supersedes_schedule_id` records its id."
    PRD §3.3: "Supersession cancels the old schedule's pending work: its payments in
    `SCHEDULED` or `PAYABLE` move to `CANCELLED` with `cancel_reason` = `SUPERSEDED`".

    Design: Corner/state_machines/schedule_supersede_cancels_pending_payments
    """
    ctx = setup_funded_agreement()
    add_draft_schedule(ctx, [{"due_date": "2027-01-01", "base_amount_cents": 30000},
                             {"due_date": "2027-02-01", "base_amount_cents": 31000}])
    schedule1 = activate_schedule(ctx)
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["total_scheduled_cents"] == 61000, (
        "total_scheduled_cents is the sum of amount_cents over the ACTIVE schedule"
    )

    ctx2 = {"agreement": agreement, "payee": ctx["payee"]}
    add_draft_schedule(ctx2, [{"due_date": "2027-03-01", "base_amount_cents": 50000},
                              {"due_date": "2027-04-01", "base_amount_cents": 52000}],
                       schedule_overrides={"effective_from_date": "2026-03-01",
                                           "escalation_anchor_date": "2026-03-01"})
    schedule2 = activate_schedule(ctx2)
    assert schedule2["status"] == "ACTIVE"
    assert schedule2["supersedes_schedule_id"] == schedule1["id"]

    old_schedule = get_schedule(schedule1["id"])
    assert old_schedule["status"] == "SUPERSEDED"
    for old_payment in ctx["payments"]:
        row = get_success_data(api.get_scheduled_payment(old_payment["id"], TEST_USERS["reader_headers"]))
        assert row["status"] == "CANCELLED"
        assert row["cancel_reason"] == "SUPERSEDED"

    agreement_after = get_agreement(ctx["agreement"]["id"])
    assert agreement_after["total_scheduled_cents"] == 102000
    assert agreement_after["outstanding_liability_cents"] == 102000, (
        "outstanding_liability_cents is recomputed over the new payment set"
    )
