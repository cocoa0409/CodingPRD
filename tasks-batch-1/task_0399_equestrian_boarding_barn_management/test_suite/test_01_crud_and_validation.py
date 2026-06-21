"""CRUD, input-shape validation, list reads, and RBAC denials.

Covers owner/horse/stall creation and lookup, field-shape and fiscal
validations, reverse-reachability list reads, and the role/ownership access
controls of PRD §2.1 / §2.6 / §2.7.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_owner, assert_stall, assert_boarding_agreement,
    create_owner_payload, create_stall_payload, create_horse_payload,
    create_lesson_payload, create_invoice_payload,
    create_owner, create_stall, create_horse, create_draft_agreement,
    setup_finalized_invoice_for_ended_boarding, adjust_deposit,
    create_active_boarding, set_clock,
    make_owner_headers, TEST_USERS,
    NON_EXISTENT_UUID,
)

BM = TEST_USERS["barn_manager_headers"]


# ===========================================================================
# entities
# ===========================================================================
def test_create_owner_returns_201_with_system_fields(api):
    """PRD §3.1: "A freshly created owner begins life in `ACTIVE` status with
    `deposit_held_cents`, `account_balance_cents`, `standing_score`, and
    `provisional_standing_score` all at zero and `version` at 1."

    Design: Corner/entities/create_owner_returns_201_with_system_fields
    """
    res = api.create_owner(create_owner_payload(full_name="Zoe Rider", email="zoe@x.com"), BM)
    owner = validate_success(res, 201)
    assert_owner(owner)
    assert owner["version"] == 1
    assert owner["status"] == "ACTIVE"
    assert owner["deposit_held_cents"] == 0
    assert owner["account_balance_cents"] == 0
    assert owner["standing_score"] == 0


def test_create_horse_missing_required_field_returns_invalid_request(api):
    """PRD §2.7: "A request that violates any of these shape rules — or that omits
    a required field or supplies a malformed enum value — is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_horse_missing_required_field_returns_invalid_request
    """
    owner = create_owner()
    res = api.create_horse({"owner_id": owner["id"]}, BM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_horse_unknown_owner_returns_not_found(api):
    """PRD §2.5: "the body's references — `owner_id`, `horse_id`, `stall_id`, and
    `pasture_id` — must each resolve to an existing entity before any state-machine
    or business rule is evaluated; an unresolved body reference fails with the
    corresponding not-found error (`ERR_OWNER_NOT_FOUND`, `ERR_HORSE_NOT_FOUND`, or
    `ERR_STALL_NOT_FOUND`, the last covering both `stall_id` and `pasture_id` since
    a pasture is a kind of stall)."

    Design: Corner/entities/create_horse_unknown_owner_returns_not_found
    """
    res = api.create_horse(create_horse_payload(NON_EXISTENT_UUID, name="Ghost"), BM)
    validate_error(res, "ERR_OWNER_NOT_FOUND", expected_status=404)


def test_get_owner_not_found_returns_404(api):
    """PRD §2.5: "Path identifiers and their dedicated errors are: an owner id
    (`ERR_OWNER_NOT_FOUND`)".

    Design: Corner/entities/get_owner_not_found_returns_404
    """
    res = api.get_owner(NON_EXISTENT_UUID, BM)
    validate_error(res, "ERR_OWNER_NOT_FOUND", expected_status=404)


def test_create_stall_pasture_capacity_two_succeeds(api):
    """PRD §2.7: "a stall whose `kind` is `STALL` must have `capacity` equal to 1,
    while a pasture whose `kind` is `PASTURE` must have `capacity` of at least 1."
    PRD §3.2: "A new stall starts with `occupied_count` at zero."

    Design: Corner/entities/create_stall_pasture_capacity_two_succeeds
    """
    res = api.create_stall(
        create_stall_payload(label="PX", kind="PASTURE", capacity=2, daily_rate_cents=1000), BM
    )
    stall = validate_success(res, 201)
    assert_stall(stall)
    assert stall["occupied_count"] == 0
    assert stall["capacity"] == 2


def test_stall_kind_capacity_two_rejected(api):
    """PRD §2.7: "a stall whose `kind` is `STALL` must have `capacity` equal to 1".

    Design: Corner/entities/stall_kind_capacity_two_rejected
    """
    res = api.create_stall(
        create_stall_payload(label="SX", kind="STALL", capacity=2, daily_rate_cents=4500), BM
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_computed_charge_fields_default_zero_on_draft(api):
    """PRD §3.5: "it is created in `DRAFT` with `end_date`, `suspended_at` null,
    `suspended_days` at zero, and both `provisional_charge_cents` and
    `final_charge_cents` at zero."

    Design: Corner/entities/computed_charge_fields_default_zero_on_draft
    """
    owner = create_owner()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    assert agreement["status"] == "DRAFT"
    assert agreement["provisional_charge_cents"] == 0
    assert agreement["final_charge_cents"] == 0


# ===========================================================================
# validations (field-shape / fiscal)
# ===========================================================================
def test_ends_before_starts_lesson_rejected(api):
    """PRD §2.7: "A lesson's `ends_at` must be strictly after its `starts_at`."

    Design: Corner/validations/ends_before_starts_lesson_rejected
    """
    owner = create_owner()
    horse = create_horse(owner["id"])
    res = api.create_lesson(
        create_lesson_payload(
            horse["id"],
            starts_at="2026-06-10T11:00:00.000Z",
            ends_at="2026-06-10T10:00:00.000Z",
        ),
        BM,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_turnout_pasture_id_not_pasture_rejected(api):
    """PRD §2.7: "A `pasture_id` supplied for a turnout must reference a stall whose
    `kind` is `PASTURE`."

    Design: Corner/validations/turnout_pasture_id_not_pasture_rejected
    """
    ctx = create_active_boarding()
    # ctx["stall"] is a STALL-kind stall; using it as pasture_id is invalid.
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": ctx["stall"]["id"],
            "window_start": "2026-07-01T08:00:00.000Z",
            "window_end": "2026-07-01T12:00:00.000Z",
        },
        BM,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_overpayment_rejected(api):
    """PRD §3.8: "the payment must not overpay: `paid_amount_cents` already recorded
    plus the new `amount_cents` must not exceed `amount_due_cents`, or the request
    is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_finalized_invoice_for_ended_boarding(daily_rate_cents=4500)
    inv_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["amount_due_cents"] == 45000
    res = api.transition_invoice(inv_id, {"target_status": "PAID", "amount_cents": 45001}, BM)
    validate_error(res, "ERR_OVERPAYMENT", expected_status=422)
    # Invoice remains FINALIZED.
    invoices, _ = validate_paginated(api.list_owner_invoices(ctx["owner"]["id"], BM))
    target = [i for i in invoices if i["id"] == inv_id][0]
    assert target["status"] == "FINALIZED"


def test_deposit_refund_below_zero_rejected(api):
    """PRD §3.1: "The held deposit may never be driven below zero — a refund larger
    than the deposit on hand is rejected with `ERR_INSUFFICIENT_DEPOSIT`".

    Design: Corner/validations/deposit_refund_below_zero_rejected
    """
    owner = create_owner()
    adjust_deposit(owner["id"], 5000)
    res = api.adjust_deposit(owner["id"], {"amount_cents": -6000}, BM)
    validate_error(res, "ERR_INSUFFICIENT_DEPOSIT", expected_status=422)
    after = validate_success(api.get_owner(owner["id"], BM), 200)
    assert after["deposit_held_cents"] == 5000


def test_void_finalized_invoice_with_payment_rejected(api):
    """PRD §3.8: "Voiding a `FINALIZED` invoice is permitted only when no payment
    has been recorded — `paid_amount_cents` must be zero, or the request is rejected
    with `ERR_INVOICE_HAS_PAYMENTS`".

    Design: Corner/validations/void_finalized_invoice_with_payment_rejected
    """
    ctx = setup_finalized_invoice_for_ended_boarding(daily_rate_cents=4500)
    inv_id = ctx["invoice"]["id"]
    validate_success(
        api.transition_invoice(inv_id, {"target_status": "PAID", "amount_cents": 10000}, BM), 200
    )
    res = api.transition_invoice(inv_id, {"target_status": "VOID"}, BM)
    validate_error(res, "ERR_INVOICE_HAS_PAYMENTS", expected_status=409)
    invoices, _ = validate_paginated(api.list_owner_invoices(ctx["owner"]["id"], BM))
    target = [i for i in invoices if i["id"] == inv_id][0]
    assert target["status"] == "FINALIZED"


def test_turnout_in_past_rejected(api):
    """PRD §3.7: "the `window_start` must not be in the past relative to the current
    logical clock, or the request is rejected with `ERR_TURNOUT_IN_PAST`".

    Design: Corner/validations/turnout_in_past_rejected
    """
    ctx = create_active_boarding()
    pasture = create_stall(label="ZP-2", kind="PASTURE", capacity=3, daily_rate_cents=1000)
    set_clock("2026-06-10T00:00:00.000Z")
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": pasture["id"],
            "window_start": "2026-06-01T08:00:00.000Z",
            "window_end": "2026-06-01T12:00:00.000Z",
        },
        BM,
    )
    validate_error(res, "ERR_TURNOUT_IN_PAST", expected_status=409)


# ===========================================================================
# endpoints (reverse-reachability lists)
# ===========================================================================
def test_list_owner_horses_reverse_reach(api):
    """PRD §3.3: "an owner-scoped read lists all of an owner's horses."

    Design: Corner/endpoints/list_owner_horses_reverse_reach
    """
    owner = create_owner()
    create_horse(owner["id"], name="Vega")
    create_horse(owner["id"], name="Vela")
    res = api.list_owner_horses(owner["id"], make_owner_headers(owner["id"]))
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert meta["total_count"] == 2


def test_list_owner_invoices_reverse_reach(api):
    """PRD §3.8: "An owner-scoped read lists the owner's invoices and reflects their
    computed totals."

    Design: Corner/endpoints/list_invoice_payments_reverse_reach
    """
    owner = create_owner()
    validate_success(api.create_invoice(create_invoice_payload(owner["id"], "2026-06"), BM), 201)
    res = api.list_owner_invoices(owner["id"], BM)
    data, _ = validate_paginated(res)
    assert len(data) == 1


# ===========================================================================
# rbac
# ===========================================================================
def test_owner_cannot_create_stall(api):
    """PRD §2.1: "When a role is syntactically valid but not permitted to perform the
    requested operation ... the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: the `POST /stalls` row authorizes only `BarnManager`.

    Design: Corner/rbac/owner_cannot_create_stall
    """
    owner = create_owner()
    res = api.create_stall(
        create_stall_payload(label="Z-1", kind="STALL", capacity=1, daily_rate_cents=4500),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_barnmanager_cannot_complete_lesson(api):
    """PRD §2.1: "a role that is permitted for some target states of a transition
    endpoint but not the specific one requested ... is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.7: "Marking it `COMPLETED` is performed by an `Instructor`".

    Design: Corner/rbac/barnmanager_cannot_complete_lesson
    """
    ctx = create_active_boarding()
    lesson = validate_success(
        api.create_lesson(
            create_lesson_payload(
                ctx["horse"]["id"],
                starts_at="2026-06-02T10:00:00.000Z",
                ends_at="2026-06-02T11:00:00.000Z",
            ),
            BM,
        ),
        201,
    )
    res = api.transition_lesson(lesson["id"], {"target_status": "COMPLETED"}, BM)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_user_context_returns_401(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_returns_401
    """
    res = api.create_owner(create_owner_payload(full_name="No Context", email="noctx@x.com"), {})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=401)


def test_owner_cannot_act_on_other_owners_horse(api):
    """PRD §2.1: "When an `Owner` attempts an owner-scoped write (acting on its own
    horses, waivers, lessons, service/show/turnout requests, or withdrawals) against
    a resource that resolves to a different owner, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/owner_cannot_act_on_other_owners_horse
    """
    owner_a = create_owner()
    owner_b = create_owner()
    horse = create_horse(owner_a["id"], name="Atlas")
    res = api.create_lesson(
        create_lesson_payload(
            horse["id"],
            starts_at="2026-06-02T10:00:00.000Z",
            ends_at="2026-06-02T11:00:00.000Z",
        ),
        make_owner_headers(owner_b["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
