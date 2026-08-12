"""Photography: the booking geometry, the session entitlement and MLS delivery."""

from test_helpers import (
    CLERK,
    COORD,
    ApiErrorId,
    assert_money,
    assert_photo_shoot,
    assert_same_instant,
    make_listing_agent_headers,
    occupied_authorize_and_collect,
    set_clock,
    setup_occupied_agent_draft,
    setup_occupied_pay_at_closing_authorized,
    setup_occupied_pay_at_closing_deferred,
    setup_vacant_project_staged,
    setup_vacant_pull_committed,
    start_pickup_in_progress,
    validate_error,
    validate_success,
)


def test_delivering_a_shoot_that_was_never_completed_is_refused(api):
    """PRD §2.7: "Rung 30: the photo shoot's `state` is a legal origin for the requested
    transition; otherwise `ERR_SHOOT_INVALID_STATE`, HTTP 409."
    PRD §3.8: "Delivering the images moves the shoot `COMPLETED → DELIVERED` and stamps
    `delivered_at` from the logical clock."
    PRD §3.8: "**`mls_delivery_gated` is true exactly when the project's `payer_type` is
    `PAY_AT_CLOSING`, and false for `AGENT`, `SELLER`, `SPLIT` and `BROKERAGE`.**"

    Design: Corner/state_machines/photo_shoot_deliver_before_completion_rejected_as_shoot_invalid_state
    """
    ctx = setup_vacant_project_staged()
    shoot = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False},
        COORD), 201)

    resp = api.deliver_photo_shoot(shoot["id"], COORD)

    validate_error(resp, ApiErrorId.ERR_SHOOT_INVALID_STATE.value, 409)
    stored = validate_success(api.get_photo_shoot(shoot["id"], COORD))
    assert_photo_shoot(stored)
    assert stored["state"] == "SCHEDULED"
    assert stored["delivered_at"] is None
    assert stored["mls_delivery_gated"] is False


def test_a_vacant_shoot_before_any_completed_install_is_refused(api):
    """PRD §2.7: "Rung 48: on a `VACANT_STAGING` project the shoot instant is on or after the
    project's `COMPLETE` install's `completed_at`; otherwise `ERR_SHOOT_BEFORE_INSTALL`,
    HTTP 409."
    PRD §3.8: "Temporally, on a vacant-arm project the shoot instant must be on or after the
    project's completed install's `completed_at` — earlier is `ERR_SHOOT_BEFORE_INSTALL` —
    and on either arm the shoot instant must be **strictly** before the project's de-stage
    start, meaning the instant the pickup entered `IN_PROGRESS`; on or after that is
    `ERR_SHOOT_AFTER_DESTAGE`."

    Design: Corner/validations/shoot_scheduled_before_install_completion_rejected
    """
    ctx = setup_vacant_pull_committed()

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-20T10:00:00Z", "is_reshoot": False}, COORD)

    validate_error(resp, ApiErrorId.ERR_SHOOT_BEFORE_INSTALL.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["photo_sessions_consumed"] == 0


def test_a_second_reshoot_request_exhausts_the_single_package_credit(api):
    """PRD §2.7: "Rung 51: the project's `reshoot_credits_remaining` is at least 1 before a
    reshoot may be requested; otherwise `ERR_RESHOOT_ENTITLEMENT_EXHAUSTED`, HTTP 409."
    PRD §3.8: "The listing agent or the seller may request a reshoot against a shoot in
    state `COMPLETED` or `DELIVERED`, supplying the new `scheduled_at`; the source shoot
    moves to `RESHOOT_REQUESTED`, a fresh shoot is created with `is_reshoot` true in state
    `SCHEDULED`, and `reshoot_credits_remaining` decreases by one."
    PRD §3.8: "With no credit left the request is refused with
    `ERR_RESHOOT_ENTITLEMENT_EXHAUSTED`."

    Design: Corner/validations/second_reshoot_request_exhausts_the_entitlement
    """
    ctx = setup_vacant_project_staged()
    agent = make_listing_agent_headers(ctx["agent_id"])
    first = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False},
        COORD), 201)
    other = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T15:00:00Z", "is_reshoot": False},
        COORD), 201)
    set_clock("2026-06-11T15:00:00Z")
    validate_success(api.complete_photo_shoot(first["id"], COORD))
    validate_success(api.complete_photo_shoot(other["id"], COORD))
    reshoot = validate_success(api.request_reshoot(
        first["id"], "2026-06-12T10:00:00Z", agent), 201)

    resp = api.request_reshoot(other["id"], "2026-06-13T10:00:00Z", agent)

    validate_error(resp, ApiErrorId.ERR_RESHOOT_ENTITLEMENT_EXHAUSTED.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["reshoot_credits_remaining"] == 0
    stored = validate_success(api.get_photo_shoot(reshoot["id"], COORD))
    assert stored["is_reshoot"] is True
    assert stored["state"] == "SCHEDULED"


def test_the_third_session_on_a_two_session_package_carries_the_overage(api):
    """PRD §3.8: "Non-reshoot shoots receive a `session_index`, the 1-based creation order of
    non-reshoot shoots on that project; the shoot is created in state `SCHEDULED` with
    `overage_fee` 0, a null `delivered_at`, and `mls_delivery_gated` derived immediately."
    PRD §3.8: "Completion moves the shoot `SCHEDULED → COMPLETED`, increments the project's
    `photo_sessions_consumed` when `is_reshoot` is false, and derives the `overage_fee`: a
    reshoot is always 0.00 because it consumes a credit rather than a session; a non-reshoot
    whose `session_index` is strictly greater than the project's current tier's
    `included_photo_sessions` costs 285.00; and anything else costs 0.00."

    Design: Corner/calculations/photo_overage_fee_charged_on_the_third_included_two_session_package
    """
    ctx = setup_vacant_project_staged()
    shoots = []
    for instant in ("2026-06-11T08:00:00Z", "2026-06-11T12:00:00Z", "2026-06-11T16:00:00Z"):
        shoots.append(validate_success(api.schedule_photo_shoot(
            ctx["proj_id"], {"scheduled_at": instant, "is_reshoot": False}, COORD), 201))
    set_clock("2026-06-11T16:00:00Z")

    for shoot in shoots:
        validate_success(api.complete_photo_shoot(shoot["id"], COORD))

    rows = [validate_success(api.get_photo_shoot(s["id"], COORD)) for s in shoots]
    assert rows[0]["session_index"] == 1
    assert_money(rows[0]["overage_fee"], 0.00, "shoot 1.overage_fee")
    assert rows[1]["session_index"] == 2
    assert_money(rows[1]["overage_fee"], 0.00, "shoot 2.overage_fee")
    assert rows[2]["session_index"] == 3
    assert_money(rows[2]["overage_fee"], 285.00, "shoot 3.overage_fee")
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["photo_sessions_consumed"] == 3


def test_an_agent_payer_shoot_delivers_without_any_payment_gate(api):
    """PRD §3.8: "**`mls_delivery_gated` is true exactly when the project's `payer_type` is
    `PAY_AT_CLOSING`, and false for `AGENT`, `SELLER`, `SPLIT` and `BROKERAGE`.**"
    PRD §3.8: "It is permitted when `mls_delivery_gated` is false, or when the project's
    invoice is in state `PAID`; a gated shoot whose invoice is unpaid is refused with
    `ERR_MLS_DELIVERY_PAYMENT_GATE` (HTTP 402)."

    Design: Corner/calculations/mls_delivery_is_ungated_for_an_agent_payer_project
    """
    ctx = setup_occupied_agent_draft()
    occupied_authorize_and_collect(ctx, actor="agent")
    visit = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD), 201)
    shoot = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-03T10:00:00Z", "is_reshoot": False},
        COORD), 201)
    set_clock("2026-06-02T09:00:00Z")
    validate_success(api.complete_visit(visit["id"], 2.0, COORD))
    set_clock("2026-06-03T10:00:00Z")
    validate_success(api.complete_photo_shoot(shoot["id"], COORD))

    validate_success(api.deliver_photo_shoot(shoot["id"], COORD))

    stored = validate_success(api.get_photo_shoot(shoot["id"], COORD))
    assert stored["mls_delivery_gated"] is False
    assert stored["state"] == "DELIVERED"
    assert_same_instant(stored["delivered_at"], "2026-06-03T10:00:00Z",
                        "shoot.delivered_at")
    assert_money(stored["overage_fee"], 0.00, "shoot.overage_fee")


def test_a_gated_shoot_cannot_deliver_while_the_invoice_is_still_deferred(api):
    """PRD §2.7: "Rung 72: when a shoot's `mls_delivery_gated` is true, the project's invoice
    is in state `PAID` before delivery; otherwise `ERR_MLS_DELIVERY_PAYMENT_GATE`, HTTP 402."
    PRD §3.8: "It is permitted when `mls_delivery_gated` is false, or when the project's
    invoice is in state `PAID`; a gated shoot whose invoice is unpaid is refused with
    `ERR_MLS_DELIVERY_PAYMENT_GATE` (HTTP 402)."
    PRD §3.9: "Deferring it is the `PAY_AT_CLOSING`-only alternative: it moves `DRAFT →
    DEFERRED_CLOSING`, stamps `issued_at`, leaves `due_date` null, and drives the project's
    `payment_state` to `DEFERRED`; the listing must still be in `ACTIVE`, `UNDER_CONTRACT`
    or `BACK_ON_MARKET`."

    Design: Corner/errors/mls_delivery_blocked_while_a_pay_at_closing_invoice_is_unpaid
    """
    ctx = setup_occupied_pay_at_closing_deferred()

    resp = api.deliver_photo_shoot(ctx["shoot_id"], COORD)

    validate_error(resp, ApiErrorId.ERR_MLS_DELIVERY_PAYMENT_GATE.value, 402)
    shoot = validate_success(api.get_photo_shoot(ctx["shoot_id"], COORD))
    assert shoot["mls_delivery_gated"] is True
    assert shoot["state"] == "COMPLETED"
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert invoice["state"] == "DEFERRED_CLOSING"
    assert invoice["due_date"] is None
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 2072.50, "deposit.amount")


def test_a_project_on_fiscal_hold_cannot_request_a_reshoot(api):
    """PRD §2.7: "Rung 71: the project's `fiscal_hold` is false before any new commitment may
    be made; otherwise `ERR_FISCAL_HOLD`, HTTP 402."
    PRD §3.9: "A project's `fiscal_hold` is true exactly while its `payment_state` is
    `ESCALATED`, and while it is true no new commitment may be made — no pull, no install,
    no visit, no photo shoot, no reshoot request, no lease extension and no package upgrade
    — each refused with `ERR_FISCAL_HOLD` (HTTP 402)."

    Design: Corner/errors/fiscal_hold_blocks_a_reshoot_request
    """
    ctx = setup_occupied_pay_at_closing_deferred()
    validate_success(api.escalate_invoice(ctx["inv_id"], CLERK))

    resp = api.request_reshoot(
        ctx["shoot_id"], "2026-06-04T10:00:00Z",
        make_listing_agent_headers(ctx["agent_id"]))

    validate_error(resp, ApiErrorId.ERR_FISCAL_HOLD.value, 402)
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert invoice["state"] == "ESCALATED"
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["fiscal_hold"] is True
    assert project["payment_state"] == "ESCALATED"
    assert project["reshoot_credits_remaining"] == 1


def test_a_shoot_starting_239_minutes_after_another_collides(api):
    """PRD §2.7: "Rung 62: the proposed shoot's half-open 180-minute block does not overlap
    any existing shoot's block plus that shoot's trailing 60-minute buffer on the same
    property; otherwise `ERR_SHOOT_TIME_CONFLICT`, HTTP 409."
    PRD §3.8: "A new shoot starting exactly 240 minutes after an existing one is therefore
    legal, and 239 minutes is not."

    Design: Difficulty/resource_temporal_overlap/shoot_block_buffer_rejects_a_start_239_minutes_later
    """
    ctx = setup_vacant_project_staged()
    first = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False},
        COORD), 201)

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T13:59:00Z", "is_reshoot": False}, COORD)

    validate_error(resp, ApiErrorId.ERR_SHOOT_TIME_CONFLICT.value, 409)
    stored = validate_success(api.get_photo_shoot(first["id"], COORD))
    assert stored["state"] == "SCHEDULED"
    assert stored["session_index"] == 1
    assert_money(stored["overage_fee"], 0.00, "shoot.overage_fee")


def test_a_shoot_starting_exactly_240_minutes_later_is_legal(api):
    """PRD §3.8: "Geometrically, the shoot occupies a **half-open 180-minute block**
    beginning at its `scheduled_at`, and it must not overlap any existing shoot on the
    **same property** in state `SCHEDULED` or `COMPLETED`, where each existing shoot is
    treated as occupying its own 180-minute block **plus a trailing 60-minute buffer**."
    PRD §3.8: "A new shoot starting exactly 240 minutes after an existing one is therefore
    legal, and 239 minutes is not."

    Design: Difficulty/resource_temporal_overlap/shoot_block_buffer_rejects_a_start_239_minutes_later
    """
    ctx = setup_vacant_project_staged()
    validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False},
        COORD), 201)

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T14:00:00Z", "is_reshoot": False}, COORD)

    second = validate_success(resp, 201)
    assert second["state"] == "SCHEDULED"
    assert second["session_index"] == 2


def test_a_shoot_cannot_be_booked_once_the_de_stage_has_started(api):
    """PRD §2.7: "Rung 50: the shoot instant is strictly before the project's de-stage start,
    meaning the instant at which the pickup entered `IN_PROGRESS`; otherwise
    `ERR_SHOOT_AFTER_DESTAGE`, HTTP 409."
    PRD §3.8: "Temporally, on a vacant-arm project the shoot instant must be on or after the
    project's completed install's `completed_at` — earlier is `ERR_SHOOT_BEFORE_INSTALL` —
    and on either arm the shoot instant must be **strictly** before the project's de-stage
    start, meaning the instant the pickup entered `IN_PROGRESS`; on or after that is
    `ERR_SHOOT_AFTER_DESTAGE`."

    Design: Difficulty/cross_entity_state_dependency/photo_shoot_cannot_be_scheduled_after_destage_started
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-10-14T10:00:00Z", "is_reshoot": False}, COORD)

    validate_error(resp, ApiErrorId.ERR_SHOOT_AFTER_DESTAGE.value, 409)
    assert validate_success(api.get_pickup(pickup_id, COORD))["state"] == "IN_PROGRESS"
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["photo_sessions_consumed"] == 0


def test_a_shoot_instant_strictly_before_the_de_stage_start_is_still_bookable(api):
    """PRD §2.7: "Rung 50: the shoot instant is strictly before the project's de-stage start,
    meaning the instant at which the pickup entered `IN_PROGRESS`; otherwise
    `ERR_SHOOT_AFTER_DESTAGE`, HTTP 409."
    PRD §3.8: "Non-reshoot shoots receive a `session_index`, the 1-based creation order of
    non-reshoot shoots on that project; the shoot is created in state `SCHEDULED` with
    `overage_fee` 0, a null `delivered_at`, and `mls_delivery_gated` derived immediately."

    Design: Difficulty/cross_entity_state_dependency/photo_shoot_cannot_be_scheduled_after_destage_started
    """
    ctx = setup_vacant_project_staged()
    start_pickup_in_progress(ctx)

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-10-12T10:00:00Z", "is_reshoot": False}, COORD)

    shoot = validate_success(resp, 201)
    assert shoot["state"] == "SCHEDULED"
    assert shoot["session_index"] == 1
    assert shoot["mls_delivery_gated"] is False


def test_an_occupied_shoot_cannot_complete_before_any_visit_has(api):
    """PRD §2.7: "Rung 49: on an `OCCUPIED_PREP` project at least one visit is already in
    state `COMPLETED` before a shoot may be completed; otherwise `ERR_VISIT_NOT_COMPLETED`,
    HTTP 409."
    PRD §3.8: "on an occupied-arm project it requires at least one visit already in state
    `COMPLETED`, and a completion attempted before that is refused with
    `ERR_VISIT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/occupied_photo_shoot_cannot_complete_without_a_completed_visit
    """
    ctx = setup_occupied_pay_at_closing_authorized()
    shoot = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-05T10:00:00Z", "is_reshoot": False},
        COORD), 201)
    set_clock("2026-06-05T10:00:00Z")

    resp = api.complete_photo_shoot(shoot["id"], COORD)

    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_COMPLETED.value, 409)
    stored = validate_success(api.get_photo_shoot(shoot["id"], COORD))
    assert stored["state"] == "SCHEDULED"


def test_the_blocked_occupied_shoot_is_gated_and_consumed_nothing(api):
    """PRD §3.8: "**`mls_delivery_gated` is true exactly when the project's `payer_type` is
    `PAY_AT_CLOSING`, and false for `AGENT`, `SELLER`, `SPLIT` and `BROKERAGE`.**"
    PRD §3.8: "Completion moves the shoot `SCHEDULED → COMPLETED`, increments the project's
    `photo_sessions_consumed` when `is_reshoot` is false, and derives the `overage_fee`: a
    reshoot is always 0.00 because it consumes a credit rather than a session; a non-reshoot
    whose `session_index` is strictly greater than the project's current tier's
    `included_photo_sessions` costs 285.00; and anything else costs 0.00."

    Design: Difficulty/cross_entity_state_dependency/occupied_photo_shoot_cannot_complete_without_a_completed_visit
    """
    ctx = setup_occupied_pay_at_closing_authorized()
    shoot = validate_success(api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-05T10:00:00Z", "is_reshoot": False},
        COORD), 201)
    set_clock("2026-06-05T10:00:00Z")

    resp = api.complete_photo_shoot(shoot["id"], COORD)

    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_COMPLETED.value, 409)
    stored = validate_success(api.get_photo_shoot(shoot["id"], COORD))
    assert stored["mls_delivery_gated"] is True
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["photo_sessions_consumed"] == 0
