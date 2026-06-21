"""Dispute adjudication side effects, reminders, and access control.

Translates queue-B corner instances for the disputes section (reject unfreezes),
endpoints (acknowledge), and rbac (forbidden role, self-adjudication, unauth).
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    make_mediator_headers,
    make_operator_headers,
    build_household_with_members,
    post_expense,
    issue_rent_bill,
    freeze_household_via_dispute,
    file_dispute_on_expense,
    set_clock,
    create_profile,
)

api = api_client


def test_reject_dispute_unfreezes_household_to_active():
    """PRD §3.9: "Rejecting sets the dispute to `REJECTED` and leaves the target
    unchanged. Each of reopen, resolve, and reject ends the freeze: the household
    returns to `ACTIVE`, provided no other dispute is still `UNDER_REVIEW`."

    Design: Corner/state_machines/dispute_reject_unfreezes_household_back_to_active
    """
    env = build_household_with_members(
        api, [{"full_name": "UnfM1"}, {"full_name": "UnfM2"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    dispute = freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-c1")

    rejected = validate_success(api.reject_dispute(dispute["id"], make_mediator_headers("med-c1")))
    assert rejected["status"] == "REJECTED"
    household = validate_success(api.get_household(env["household"]["id"], lh))
    assert household["status"] == "ACTIVE"


def test_acknowledge_sent_reminder_moves_to_acknowledged():
    """PRD §3.8: "A member who receives a reminder may acknowledge it, moving the
    reminder from `SENT` to `ACKNOWLEDGED`."

    Design: Corner/endpoints/acknowledge_sent_reminder
    """
    env = build_household_with_members(
        api, [{"full_name": "AckM1"}], clock="2026-06-01T00:00:00.000Z",
        listing_overrides={"capacity": 3},
    )
    m1 = env["members"][0]
    lh = make_roommate_headers(env["lister"]["id"])
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)
    reminder = validate_success(
        api.create_payment_reminder(
            {"household_id": env["household"]["id"], "bill_id": bill["id"],
             "due_date": "2026-06-10T00:00:00.000Z"},
            lh,
        ),
        201,
    )
    set_clock(api, "2026-06-10T00:00:00.000Z")
    validate_success(api.dispatch_reminders(make_operator_headers()))

    acked = validate_success(api.acknowledge_reminder(reminder["id"], make_roommate_headers(m1["id"])))
    assert acked["status"] == "ACKNOWLEDGED"


def test_reminder_target_ambiguous_rejected():
    """PRD §3.8: "The reminder names the `household_id`, a `due_date`, and exactly one of
    `bill_id` or `settlement_id` — the other must be null. A reminder that names neither
    or both is rejected with `ERR_REMINDER_TARGET_AMBIGUOUS`."

    Design: Corner/validations/reminder_target_ambiguous_rejected
    """
    env = build_household_with_members(api, [{"full_name": "RtM1"}], listing_overrides={"capacity": 3})
    lh = make_roommate_headers(env["lister"]["id"])
    resp = api.create_payment_reminder(
        {"household_id": env["household"]["id"], "due_date": "2026-06-10T00:00:00.000Z"},
        lh,
    )
    validate_error(resp, ApiErrorId.ERR_REMINDER_TARGET_AMBIGUOUS.value)


def test_roommate_cannot_dispatch_reminders():
    """PRD §2.1: "When an authenticated caller holds a role that is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /_reminders/dispatch is authorized for PlatformOperator only.

    Design: Corner/rbac/roommate_cannot_dispatch_reminders
    """
    actor = create_profile(api, full_name="Rb1")
    resp = api.dispatch_reminders(make_roommate_headers(actor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_roommate_cannot_resolve_dispute():
    """PRD §2.1: "When an authenticated caller holds a role that is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /disputes/{id}/resolve is authorized for DisputeMediator only.

    Design: Corner/rbac/roommate_cannot_resolve_dispute
    """
    env = build_household_with_members(
        api, [{"full_name": "Rb2M1"}, {"full_name": "Rb2M2"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    dispute = freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-rb2")
    resp = api.resolve_dispute(
        dispute["id"], {"adjusted_amount_cents": 6000}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_mediator_cannot_self_adjudicate():
    """PRD §2.1: "A further segregation-of-duties rule binds the mediator role: the
    `DisputeMediator` acting to claim, resolve, or reject a dispute must not be the
    dispute's `filed_by_id`. A violation is rejected with `ERR_SELF_ADJUDICATION`."

    Design: Corner/rbac/mediator_self_adjudication_denied
    """
    env = build_household_with_members(
        api, [{"full_name": "SaM1"}, {"full_name": "SaM2"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    dispute = file_dispute_on_expense(api, env, filer=m1, expense=expense)
    # A mediator whose operator id equals the filer's id attempts to claim.
    resp = api.claim_dispute(dispute["id"], make_mediator_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_ADJUDICATION.value)


def test_unauthenticated_request_rejected():
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a known
    role, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    create_profile(api, full_name="Unauth")
    resp = api.list_households(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
