"""Buyer registration, the onsale queue, admission windows, and admission overlap."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_buyer_payload, create_queue_token_payload, create_hold_payload,
    make_buyer_headers,
    register_buyer, setup_onsale_event, admit_buyer, event_version, set_clock,
)

BOX = TEST_USERS["box_office_headers"]


# ─── Corner: buyer creation ───────────────────────────────────────────────
def test_buyer_create_returns_201_with_fields(api):
    """PRD §3.2: "Buyers themselves are registered by the box office with a `name` and a
    unique `email`, starting with a `credit_balance_cents` of 0."
    PRD §2.4: "The `version` starts at 1 when the resource is created and increases by
    exactly 1 on every mutation of that resource."

    Design: Corner/entities/buyer_create_returns_201_with_fields
    """
    res = api.create_buyer(create_buyer_payload(name="Ada"), BOX)
    buyer = validate_success(res, 201)
    assert buyer["credit_balance_cents"] == 0
    assert buyer["version"] == 1


def test_buyer_create_missing_required_email_returns_validation(api):
    """PRD §3.2: "Buyers themselves are registered by the box office with a `name` and a
    unique `email`, starting with a `credit_balance_cents` of 0." (email is a required
    registration field.) PRD §3.5 establishes `ERR_VALIDATION` as the malformed-input error:
    "A malformed transfer — a resale without a positive `list_price_cents`, or a gift that
    nevertheless carries a `list_price_cents` — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/buyer_create_missing_required_email_returns_validation
    """
    res = api.create_buyer({"name": "NoEmail"}, BOX)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


# ─── Corner: RBAC on admission ────────────────────────────────────────────
def test_buyer_cannot_admit_queue_token(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation — or a buyer attempts to act on a resource it does not
    own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." (admission is a
    BoxOffice capability per §4.)

    Design: Corner/rbac/buyer_cannot_admit_queue_token
    """
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1)
    token = validate_success(
        api.create_queue_token(
            env["event"]["id"], create_queue_token_payload(buyer["id"]),
            make_buyer_headers(buyer["id"]),
        ),
        201,
    )
    res = api.admit_queue_token(token["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


# ─── Corner: admission gating on hold create ──────────────────────────────
def test_hold_onsale_without_admission_returns_not_admitted(api):
    """PRD §3.2: "When the event is `ONSALE`, a buyer may create a hold only if they hold an
    `ADMITTED` token for that event whose window is still open; a hold attempt during
    `ONSALE` without such a token is rejected with `ERR_NOT_ADMITTED`".

    Design: Corner/validations/hold_onsale_without_admission_returns_not_admitted
    """
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1)
    ev_id = env["event"]["id"]
    seat_id = env["seats"][0]["id"]

    res = api.create_hold(
        ev_id,
        create_hold_payload([seat_id], buyer["id"], event_version(ev_id)),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_ADMITTED.value, expected_status=409)


def test_hold_after_admission_window_lapsed_returns_window_expired(api):
    """PRD §3.2: "if the buyer had a token but its `purchase_deadline` has already passed
    (the clock is strictly beyond it), the attempt is rejected with
    `ERR_ADMISSION_WINDOW_EXPIRED`."

    Design: Corner/validations/hold_after_admission_window_lapsed_returns_window_expired
    """
    set_clock("2026-06-01T10:00:00Z")
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1, purchase_window_minutes=30)
    ev_id = env["event"]["id"]
    admit_buyer(ev_id, buyer["id"])  # admitted at 10:00, deadline 10:30

    set_clock("2026-06-01T10:31:00Z")  # strictly past the deadline
    res = api.create_hold(
        ev_id,
        create_hold_payload([env["seats"][0]["id"]], buyer["id"], event_version(ev_id)),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ADMISSION_WINDOW_EXPIRED.value, expected_status=409)


# ─── Difficulty: inclusive admission-window overlap ───────────────────────
def _two_waiting_tokens(api, ev_id, buyer_id):
    hb = make_buyer_headers(buyer_id)
    tk1 = validate_success(
        api.create_queue_token(ev_id, create_queue_token_payload(buyer_id), hb), 201
    )
    tk2 = validate_success(
        api.create_queue_token(ev_id, create_queue_token_payload(buyer_id), hb), 201
    )
    return tk1, tk2


def test_admit_second_token_blocked_at_deadline_instant(api):
    """PRD §3.2: "if the buyer already holds an `ADMITTED` token for this event whose
    `purchase_deadline` is at or after the current clock, the admit is rejected with
    `ERR_ALREADY_ADMITTED`." (clock == purchase_deadline is inclusive, so it still blocks.)

    Design: Difficulty/resource_temporal_overlap/queue_admission_window_inclusive_overlap
    """
    set_clock("2026-06-01T10:00:00Z")
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1, purchase_window_minutes=30)
    ev_id = env["event"]["id"]
    tk1, tk2 = _two_waiting_tokens(api, ev_id, buyer["id"])

    validate_success(api.admit_queue_token(tk1["id"], BOX), 200)  # deadline 10:30
    set_clock("2026-06-01T10:30:00Z")  # clock == purchase_deadline
    res = api.admit_queue_token(tk2["id"], BOX)
    validate_error(res, ApiErrorId.ERR_ALREADY_ADMITTED.value, expected_status=409)


def test_admit_second_token_blocked_inside_open_window(api):
    """PRD §3.2: "if the buyer already holds an `ADMITTED` token for this event whose
    `purchase_deadline` is at or after the current clock, the admit is rejected with
    `ERR_ALREADY_ADMITTED`." (a strictly-open window blocks a second admission too.)

    Design: Difficulty/resource_temporal_overlap/queue_admission_window_inclusive_overlap
    """
    set_clock("2026-06-01T10:00:00Z")
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1, purchase_window_minutes=30)
    ev_id = env["event"]["id"]
    tk1, tk2 = _two_waiting_tokens(api, ev_id, buyer["id"])

    validate_success(api.admit_queue_token(tk1["id"], BOX), 200)  # deadline 10:30
    set_clock("2026-06-01T10:15:00Z")  # clock strictly before deadline (window open)
    res = api.admit_queue_token(tk2["id"], BOX)
    validate_error(res, ApiErrorId.ERR_ALREADY_ADMITTED.value, expected_status=409)
