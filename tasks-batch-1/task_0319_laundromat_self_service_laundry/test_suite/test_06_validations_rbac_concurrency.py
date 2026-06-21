"""Validation errors, validation-priority pairs, RBAC, OCC, member entity
defaults, plan activation cascade, and pagination bounds."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    build_user_headers,
    make_member_headers,
    make_attendant_headers,
    create_member_payload,
    create_machine_payload,
    create_vend_payload,
    create_reload_payload,
    pay_wdf_order_payload,
    create_plan,
    create_machine,
    create_member,
    reload_wallet,
    set_clock,
    setup_active_plan_and_washer,
    setup_active_plan_and_dryer,
    setup_funded_member,
    setup_submitted_wallet_claim,
    setup_ready_wdf_order,
    capture_coin_vend,
    get_machine_version,
    get_machine,
    get_member,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


# ---------------------------------------------------------------------------
# Validation-priority pairs (difficulty)
# ---------------------------------------------------------------------------
def test_machine_unavailable_beats_insufficient_wallet(api):
    """PRD §3.3: "The capture is allowed only against an `IDLE` machine; if the
    machine is `RUNNING`, `DONE`, `FAULT`, or `OUT_OF_SERVICE` the vend is
    rejected with `ERR_MACHINE_UNAVAILABLE` (HTTP 409)."
    PRD §2.10: "State validity is sixth ... Only after all of these do the
    domain-specific business rules in the remainder of this document apply".

    Design: Difficulty/priority_pair_validation_conflict/machine_unavailable_beats_insufficient_wallet
    """
    plan, washer = setup_active_plan_and_washer(clock="2026-06-01T10:00:00Z")
    member = create_member()  # wallet 0, ACTIVE
    capture_coin_vend(washer["id"])  # machine now RUNNING
    version = get_machine_version(washer["id"])
    # APP_WALLET vend by an empty-wallet member on a RUNNING machine.
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET", member_id=member["id"]),
        make_member_headers(member["id"]))
    # Machine-availability (state, priority 6/9) is checked before the wallet
    # balance business rule.
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)


def test_not_found_beats_disposal_hold_on_dispose(api):
    """PRD §2.9: "any referenced ... item that does not exist halts the request
    at that point before any business rule is evaluated."
    PRD §2.10: "Existence is third: every referenced resource must exist, or
    `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_dispose
    """
    resp = api.dispose_lost_found(NON_EXISTENT_UUID, ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Plan activation cascade (difficulty transitive_cascade)
# ---------------------------------------------------------------------------
def test_plan_activation_retires_prior_active(api):
    """PRD §3.1: "Activation carries a cascade: any other plan currently in
    `ACTIVE` is moved to `RETIRED` at the same moment, since only one plan may be
    active".

    Design: Difficulty/transitive_cascade/plan_activate_cascade_depth2_retires_prior
    """
    from test_helpers import create_pricing_plan_payload
    p1 = validate_success(api.create_pricing_plan(create_pricing_plan_payload(label="P1"), MANAGER), 201)
    activated_p1 = validate_success(api.activate_pricing_plan(p1["id"], MANAGER), 200)
    assert activated_p1["status"] == "ACTIVE"
    p2 = validate_success(
        api.create_pricing_plan(
            create_pricing_plan_payload(label="P2", wash_base_cents=350,
                                        dry_base_cents_per_block=80, wdf_rate_cents_per_lb=200),
            MANAGER), 201)
    activated_p2 = validate_success(api.activate_pricing_plan(p2["id"], MANAGER), 200)
    assert activated_p2["status"] == "ACTIVE"
    # Prior ACTIVE plan P1 is now RETIRED.
    p1_now = validate_success(api.get_pricing_plan(p1["id"], MANAGER), 200)
    assert p1_now["status"] == "RETIRED"


# ---------------------------------------------------------------------------
# Validation → error (corner)
# ---------------------------------------------------------------------------
def test_dryer_vend_without_blocks_rejected(api):
    """PRD §3.3: "A dryer vend must request at least one block — a `DRYER`
    capture with `dry_blocks` less than 1 is rejected with
    `ERR_DRY_BLOCKS_REQUIRED` (HTTP 422)."

    Design: Corner/validations/dryer_vend_without_blocks_returns_422
    """
    plan, dryer = setup_active_plan_and_dryer(clock="2026-06-01T10:00:00Z")
    version = dryer["version"]
    resp = api.create_vend(
        dryer["id"], create_vend_payload(version, payment_method="COIN", dry_blocks=0),
        ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_DRY_BLOCKS_REQUIRED.value)


def test_vend_without_active_plan_rejected(api):
    """PRD §3.1: "Whenever a vend, reload, or wash-dry-fold intake needs to price
    something and no plan is `ACTIVE`, that request is rejected with
    `ERR_NO_ACTIVE_PLAN` (HTTP 409)."

    Design: Corner/validations/vend_without_active_plan_returns_409
    """
    set_clock("2026-06-01T10:00:00Z")
    create_plan(activate=False)  # DRAFT plan only; nothing ACTIVE
    washer = create_machine(label="W1")
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLAN.value)
    assert get_machine(washer["id"])["status"] == "IDLE"


def test_insufficient_wallet_app_vend_rejected(api):
    """PRD §3.3: "`wallet_cents` must be at least the charged amount (otherwise
    `ERR_INSUFFICIENT_WALLET`, HTTP 409)."

    Design: Corner/validations/insufficient_wallet_app_vend_returns_409
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", plan_overrides={"wash_base_cents": 300})
    member = create_member()  # wallet 0
    version = washer["version"]
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET", member_id=member["id"]),
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)
    assert get_machine(washer["id"])["status"] == "IDLE"


def test_redeem_below_threshold_rejected(api):
    """PRD §3.4: "this requires the member's `loyalty_points` to be at least the
    active plan's `loyalty_redeem_threshold_points`, otherwise the redemption is
    rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 409)."

    Design: Corner/validations/redeem_below_threshold_returns_409
    """
    create_plan(loyalty_redeem_threshold_points=50)
    member = create_member()  # loyalty_points 0
    resp = api.redeem(member["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_suspended_member_reload_rejected(api):
    """PRD §3.4: "the member must be `ACTIVE` or the reload is rejected with
    `ERR_MEMBER_NOT_ACTIVE`."

    Design: Corner/validations/suspended_member_reload_returns_409
    """
    create_plan()
    member = create_member()
    validate_success(api.update_member(member["id"], {"status": "SUSPENDED"}, MANAGER), 200)
    resp = api.create_reload(
        member["id"], create_reload_payload(tender="APP", principal_cents=2000),
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


def test_duplicate_phone_member_rejected(api):
    """PRD §3.4: "The `phone` must be unique among members that are not `CLOSED`;
    registering a member whose phone collides with an existing non-closed member
    is rejected with `ERR_DUPLICATE_PHONE` (HTTP 409)."

    Design: Corner/validations/duplicate_phone_member_returns_409
    """
    create_member(full_name="M One", phone="555-0001", card_token="tok-m1")
    resp = api.create_member(
        create_member_payload(full_name="M Two", phone="555-0001", card_token="tok-m2"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PHONE.value)


def test_free_credit_use_without_credit_rejected(api):
    """PRD §3.3: "If `used_free_credit` was requested but the conditions for it
    do not hold — the member has no `free_wash_credits`, or the tender is not
    `APP_WALLET`, or the machine is not a `WASHER` — the vend is rejected with
    `ERR_NO_FREE_CREDIT` (HTTP 409)."

    Design: Corner/validations/no_free_credit_use_returns_409
    """
    plan, washer, member = setup_funded_member(
        principal_cents=5000, tender="APP", clock="2026-06-01T10:00:00Z")
    assert member["free_wash_credits"] == 0
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET",
                            member_id=member["id"], used_free_credit=True),
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_FREE_CREDIT.value)


def test_pagination_limit_below_min_rejected(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is
    rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_out_of_range_returns_422
    """
    resp = api.list_machines(MANAGER, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Member entity creation (corner)
# ---------------------------------------------------------------------------
def test_member_create_defaults(api):
    """PRD §3.4: "A member starts `ACTIVE` with `wallet_cents`, `loyalty_points`,
    `free_wash_credits`, and `lifetime_spend_cents` all at zero, and a `status`
    of `ACTIVE`, `SUSPENDED`, or `CLOSED`."

    Design: Corner/entities/member_defaults_active_zero_balances_on_create
    """
    resp = api.create_member(create_member_payload(), MANAGER)
    member = validate_success(resp, 201)
    assert member["status"] == "ACTIVE"
    assert member["wallet_cents"] == 0
    assert member["loyalty_points"] == 0
    assert member["free_wash_credits"] == 0
    assert member["lifetime_spend_cents"] == 0


def test_member_missing_required_field_rejected(api):
    """PRD §3.4: "A **Member** is registered with a `full_name`, a `phone`, and a
    `card_token` used to authenticate vends and reloads".
    PRD §2.10: "Request well-formedness is fourth: required fields present ... or
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_member_missing_required_field_returns_422
    """
    resp = api.create_member({"full_name": "M One", "phone": "555-0001"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_computed_member_balance_reflects_credited_reload(api):
    """PRD §3.4: "The `credited_cents` is `principal_cents` plus `bonus_cents`,
    and that full credited amount is added to the member's `wallet_cents`."

    Design: Corner/endpoints/computed_read_member_balances_match
    """
    create_plan(reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    reload_wallet(member["id"], 5000, tender="APP")  # tier2 10% -> 5500
    resp = api.get_member(member["id"], make_member_headers(member["id"]))
    fetched = validate_success(resp, 200)
    assert fetched["wallet_cents"] == 5500


def test_loyalty_ledger_no_write_endpoint(api):
    """PRD §2.4: "each `LoyaltyLedgerEntry` carries only `id` and `created_at`. It
    has no `updated_at` and no `version`, because once written it is never
    modified."
    PRD §2.9: "any referenced ... member ... that does not exist halts the
    request ... with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/loyalty_ledger_is_immutable_no_update_endpoint
    """
    resp = api.list_member_loyalty_ledger(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# RBAC (corner)
# ---------------------------------------------------------------------------
def test_member_cannot_approve_refund(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_approve_refund
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="MACHINE_FAULT", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    resp = api.approve_refund_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_register_machine(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_register_machine
    """
    member = create_member()
    resp = api.create_machine(create_machine_payload(label="W1"), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_pay_other_members_order(api):
    """PRD §2.1: "Ownership checks on any resource that references a member
    compare that resource's `member_id` to `X-User-ID` — a member may reload,
    redeem, pay, and cancel only against their own records."
    PRD §2.1: "A member acting on a resource that is not their own ... is
    rejected with `ERR_FORBIDDEN`".

    Design: Corner/rbac/member_cannot_pay_other_members_order
    """
    plan, attendant_id, owner, order = setup_ready_wdf_order(weight_lb=20, member_principal_cents=5000)
    other = create_member(full_name="M Two", phone="555-0002", card_token="tok-m2")
    resp = api.pay_wdf_order(
        order["id"], pay_wdf_order_payload("APP_WALLET"), make_member_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    order_now = validate_success(api.get_wdf_order(order["id"], MANAGER), 200)
    assert order_now["status"] == "READY"


def test_missing_role_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role`
    value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_401
    """
    # An unknown / ghost role is not one of Manager, Attendant, Member.
    ghost = build_user_headers("ghost-1", "Ghost")
    resp = api.list_machines(ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Optimistic concurrency (corner)
# ---------------------------------------------------------------------------
def test_stale_machine_version_on_vend_rejected(api):
    """PRD §2.8: "Capturing a vend against a machine requires the request to
    carry `expected_machine_version` ... If that value does not match the
    machine's current `version` ... the capture is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_machine_version_on_vend_returns_412
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    stale_version = washer["version"]  # observed before any vend
    # First vend bumps the machine version; complete + clear so it is IDLE again.
    capture_coin_vend(washer["id"])
    validate_success(api.complete_cycle(washer["id"], ATTENDANT), 200)
    validate_success(api.clear_machine(washer["id"], ATTENDANT), 200)
    # Second vend carries the pre-first-vend (stale) version.
    resp = api.create_vend(
        washer["id"], create_vend_payload(stale_version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_claim_version_on_approve_rejected(api):
    """PRD §2.8: "Approving a refund claim requires the request to carry
    `expected_claim_version` ... If that value does not match the claim's current
    `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_approve_returns_412
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="MACHINE_FAULT", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    stale = claim["version"] - 1  # one below the claim's current version
    resp = api.approve_refund_claim(
        claim["id"], {"expected_claim_version": stale}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Cross-cutting cascade (corner)
# ---------------------------------------------------------------------------
def test_redeem_then_free_credit_vend_chain(api):
    """PRD §3.4: "On redemption the member's `loyalty_points` is reduced by the
    redemption threshold, `free_wash_credits` increases by one".
    PRD §3.3: "if `used_free_credit` is set and the tender is `APP_WALLET` and the
    machine is a `WASHER` and the member holds at least one `free_wash_credits`,
    the charged amount is forced to zero and one free-wash credit is consumed."

    Design: Corner/cross_cutting_complexity_layers/loyalty_redeem_grants_free_credit_then_zeroes_vend
    """
    from test_helpers import setup_member_with_free_credit
    # loyalty_cents_per_point 1 -> 300-cent vend accrues 300 points; redeem 50
    # leaves 250 and grants 1 credit; washer cleared back to IDLE in the fixture.
    plan, washer, member = setup_member_with_free_credit(
        loyalty_cents_per_point=1, redeem_threshold=50, principal_cents=5000)
    assert member["free_wash_credits"] == 1
    assert member["loyalty_points"] == 250
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET",
                            member_id=member["id"], used_free_credit=True),
        make_member_headers(member["id"]))
    vend2 = validate_success(resp, 201)
    assert vend2["charged_amount_cents"] == 0
    after = get_member(member["id"])
    assert after["free_wash_credits"] == 0, "the free credit was consumed"
    assert after["loyalty_points"] == 250, "a zero-charge free-credit vend accrues no points"
