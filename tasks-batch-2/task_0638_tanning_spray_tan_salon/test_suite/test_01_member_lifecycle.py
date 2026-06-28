"""Member registration, lifecycle transitions, and the parallel billing dimension.

Covers queue-B entity/state-machine corner instances for Member plus the
non_linear_state_machine difficulty instance for Member's parallel dimensions.
"""
from test_helpers import (
    api_client,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    assert_member,
    create_member_payload,
    TEST_USERS,
    make_member_headers,
)
from test_helpers import fixtures as fx

SALON_MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_system_headers"]


def test_register_member_returns_201_pending_current(api):
    """PRD §3.1: "On registration the member begins with lifecycle `status` of
    `PENDING`, a `billing_status` of `CURRENT`, an `account_credit_cents` of 0,
    and a `completed_uv_session_count` of 0."

    Design: Corner/entities/create_member_returns_201_pending
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    resp = api.create_member(
        create_member_payload(full_name="New Member", plan_id=plan["id"]), FRONT_DESK
    )
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["status"] == "PENDING"
    assert data["billing_status"] == "CURRENT"
    assert data["account_credit_cents"] == 0
    assert data["completed_uv_session_count"] == 0


def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that does not resolve produces the
    corresponding not-found error — `ERR_MEMBER_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND` — before any deeper
    validation runs."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, expected_status=404)


def test_member_id_system_minted_version_starts_at_one(api):
    """PRD §2.4: "an `id` that is a server-minted UUID with no type prefix and
    serves as identity only ... and a `version` integer that starts at its initial
    value and increments by one on each mutation."

    Design: Corner/entities/member_id_input_ignored_system_minted
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    resp = api.create_member(
        create_member_payload(full_name="Sys Member", plan_id=plan["id"]), FRONT_DESK
    )
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_list_members_returns_paginated_array(api):
    """PRD §2.3: "List responses surface `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/list_members_pagination_envelope
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.register_member(plan["id"], full_name="List Member")
    resp = api.list_members(FRONT_DESK)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] >= 1, f"expected total_count >= 1, got {meta['total_count']}"


def test_activate_without_dues_rejected_member_stays_pending(api):
    """PRD §3.2: "Activation requires that a `SUCCEEDED` `EFT_DUES` payment already
    exists for this member's first cycle — absent it, the activation is rejected
    with `ERR_DUES_NOT_PAID`."

    Design: Corner/state_machines/activate_without_dues_returns_dues_not_paid
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.register_member(plan["id"], full_name="Unpaid Member")
    resp = api.activate_member(member["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_DUES_NOT_PAID.value, expected_status=409)
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["status"] == "PENDING"


def test_unfreeze_non_frozen_member_rejected(api):
    """PRD §3.3: "Unfreeze requires the member to currently be `FROZEN` (otherwise
    `ERR_MEMBER_NOT_FROZEN`) and carries the same `expected_member_version` OCC
    check."

    Design: Corner/state_machines/unfreeze_non_frozen_member_returns_error
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.create_active_member(plan["id"], full_name="NotFrozen Member")
    resp = api.unfreeze_member(
        member["id"], {"expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FROZEN.value, expected_status=409)


def test_cancel_already_cancelled_member_rejected(api):
    """PRD §3.3: "Cancellation requires the member to be in one of those three
    states (otherwise `ERR_MEMBER_ALREADY_CANCELLED`), requires no session in
    `RESERVED` or `IN_PROGRESS` status (otherwise `ERR_OPEN_SESSION_EXISTS`), and
    carries the `expected_member_version` OCC check."

    Design: Corner/state_machines/cancel_already_cancelled_member_returns_invalid_state
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.create_active_member(plan["id"], full_name="Cancel Member")
    cancelled = fx.cancel_member(member["id"], member["version"])
    assert cancelled["status"] == "CANCELLED"
    resp = api.cancel_member(
        member["id"], {"expected_member_version": cancelled["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_CANCELLED.value, expected_status=409)


def test_freeze_blocked_by_open_reserved_session(api):
    """PRD §3.3: "Freezing requires the member to currently be `ACTIVE` (otherwise
    `ERR_MEMBER_NOT_ACTIVE`) and requires that the member has no session in
    `RESERVED` or `IN_PROGRESS` status (otherwise `ERR_OPEN_SESSION_EXISTS`)."

    Design: Corner/state_machines/freeze_blocked_by_open_session
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0},
        clock="2026-06-01T10:00:00Z",
    )
    fx.reserve_uv_session(member["id"], equipment["id"], "2026-06-01T10:00:00Z", 120)
    resp = api.freeze_member(
        member["id"], {"expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_SESSION_EXISTS.value, expected_status=409)
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["account_credit_cents"] == 0, "no credit should be minted on a blocked freeze"


def test_declined_eft_moves_billing_to_past_due_status_stays_active(api):
    """PRD §2.6: "A `Member` carries two independent state dimensions that evolve
    in parallel: a lifecycle `status` (one of `PENDING`, `ACTIVE`, `FROZEN`,
    `CANCELLED`) and a `billing_status` (one of `CURRENT`, `PAST_DUE`,
    `SUSPENDED`, defaulting to `CURRENT`). The two never collapse into one another;
    a member can be `ACTIVE` while `PAST_DUE`, for instance."
    PRD §3.2: "On a `DECLINED` charge while `CURRENT` and past due, the member
    moves from `CURRENT` to `PAST_DUE`: a `DECLINED` `EFT_DUES` payment is created
    and `cycle_anchor_at` is not advanced."

    Design: Difficulty/non_linear_state_machine/member_parallel_lifecycle_and_billing_dimensions
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Billing Member")
    fx.set_clock("2026-07-02T00:00:00Z")
    resp = api.run_eft({"member_id": member["id"], "outcome": "DECLINED"}, BILLING)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE", f"lifecycle status must stay ACTIVE, got {data['status']}"
    assert data["billing_status"] == "PAST_DUE", (
        f"billing_status must move to PAST_DUE, got {data['billing_status']}"
    )


def test_declined_eft_billing_independent_of_lifecycle_verified_on_read(api):
    """PRD §2.6: "A `Member` carries two independent state dimensions that evolve
    in parallel: a lifecycle `status` (one of `PENDING`, `ACTIVE`, `FROZEN`,
    `CANCELLED`) and a `billing_status` (one of `CURRENT`, `PAST_DUE`,
    `SUSPENDED`, defaulting to `CURRENT`). The two never collapse into one another;
    a member can be `ACTIVE` while `PAST_DUE`, for instance."

    Design: Difficulty/non_linear_state_machine/member_parallel_lifecycle_and_billing_dimensions
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Billing Member 2")
    fx.set_clock("2026-07-02T00:00:00Z")
    api.run_eft({"member_id": member["id"], "outcome": "DECLINED"}, BILLING)
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["status"] == "ACTIVE"
    assert after["billing_status"] == "PAST_DUE"
