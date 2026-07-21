"""State-eligibility precedence and cross-entity state preconditions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_booking_deposit_paid, setup_published_retreat,
    new_retreat, new_room, new_guest,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import create_booking_payload
from test_helpers.test_users import make_guest_headers

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_pay_balance
# ---------------------------------------------------------------------------
def test_pay_balance_wrong_amount_on_cancelled_booking_is_invalid_state(api):
    """PRD §2.9: "Fifth is state eligibility: the target must be in a state from which the requested transition is allowed"
    PRD §2.9: "violations yield `ERR_INVALID_STATE` (409)."
    PRD §2.9: "Tenth is payment-amount matching, yielding `ERR_PAYMENT_AMOUNT_MISMATCH` (422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay_balance
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    validate_success(api.cancel_booking(ctx["booking"]["id"], gh), 200)
    resp = api.pay_balance(ctx["booking"]["id"], 1, gh)  # wrong amount AND wrong state
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_balance_correct_amount_on_cancelled_booking_is_invalid_state(api):
    """PRD §2.9: "Fifth is state eligibility: the target must be in a state from which the requested transition is allowed"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay_balance
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    validate_success(api.cancel_booking(ctx["booking"]["id"], gh), 200)
    # Even the correct balance amount must be rejected on state grounds first.
    resp = api.pay_balance(ctx["booking"]["id"], ctx["booking"]["balance_due_cents"], gh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / booking_requires_published_retreat
# ---------------------------------------------------------------------------
def test_booking_against_draft_retreat_rejected(api):
    """PRD §3.2: "Several preconditions gate the create: the retreat must be `PUBLISHED` (otherwise `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_published_retreat
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)  # stays DRAFT, version 1
    room = new_room(api, retreat["id"], bed_count=4)
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    payload = create_booking_payload(retreat["id"], guest["id"], room["id"], 2, retreat["version"])
    resp = api.create_booking(payload, gh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_booking_against_published_retreat_succeeds(api):
    """PRD §3.2: "A successful create places the booking in `PENDING_DEPOSIT`, adds `party_size` to both the room's `reserved_beds` and the retreat's `reserved_count`"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_published_retreat
    """
    base = setup_published_retreat(api, room_overrides={"bed_count": 4})
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    payload = create_booking_payload(base["retreat"]["id"], guest["id"], base["room"]["id"], 2, base["version"])
    data = validate_success(api.create_booking(payload, gh), 201)
    assert data["status"] == "PENDING_DEPOSIT"


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_publish_already_published_retreat_invalid
# ---------------------------------------------------------------------------
def test_publish_already_published_retreat_rejected(api):
    """PRD §3.1: "an attempt to publish a retreat with no lodging room, or a retreat not currently in `DRAFT`, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_publish_already_published_retreat_invalid
    """
    base = setup_published_retreat(api, room_overrides={"bed_count": 4})
    resp = api.publish_retreat(base["retreat"]["id"], _OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_complete_before_end_date_invalid
# ---------------------------------------------------------------------------
def test_complete_retreat_before_end_date_rejected(api):
    """PRD §3.1: "attempting completion before `end_date`, or on a retreat in the wrong state, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_complete_before_end_date_invalid
    """
    base = setup_published_retreat(api, room_overrides={"bed_count": 4})
    # Clock is at default 2026-07-01, well before end_date 2026-09-08.
    resp = api.complete_retreat(base["retreat"]["id"], _OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
