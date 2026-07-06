"""Subscription lifecycle: renewal cycle, cross-entity state dependencies,
cancellation crediting, and invalid transitions.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_patron_headers,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]


def _renewal_cycle_to_confirmed(api):
    """Build an ACTIVE sub on a RENEWAL_OPEN season, offer renewal, create &
    activate a successor, confirm. Returns (sub_id, succ_id, patron_id)."""
    th.set_clock("2026-04-01T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000)
    venue = th.create_venue()
    seat = th.create_seat(venue["id"], row_label="D", seat_number=1, price_tier="STANDARD")
    patron = th.create_patron(email="cycle@example.com")
    ph = make_patron_headers(patron["id"])
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    get_success_data(api.create_subscription_seat(
        th.create_subscription_seat_payload(sub["id"], seat["id"]), ph))
    get_success_data(api.activate_subscription(sub["id"], {"expected_season_version": season["version"]}, AGENT))

    th.set_clock("2026-05-02T00:00:00Z")
    get_success_data(api.open_renewal(season["id"], ADMIN))
    get_success_data(api.offer_renewal(sub["id"], AGENT))

    succ = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"], prior_subscription_id=sub["id"]), ph))
    get_success_data(api.create_subscription_seat(
        th.create_subscription_seat_payload(succ["id"], seat["id"]), ph))
    season_now = get_success_data(api.get_season(season["id"], ADMIN))
    get_success_data(api.activate_subscription(succ["id"], {"expected_season_version": season_now["version"]}, AGENT))
    return sub["id"], succ["id"], patron["id"]


# ==========================================================================
# Difficulty/non_linear_state_machine/subscription_renewal_cycle_loop
# ==========================================================================
def test_confirm_renewal_moves_original_to_renewed(api):
    """PRD §3.4: "The owning `Patron` then confirms the renewal, moving the
    subscription from `RENEWAL_PENDING` to `RENEWED`, which requires that a
    successor subscription — one whose `prior_subscription_id` equals this
    subscription's `id` — already exists in `ACTIVE` status."

    Design: Difficulty/non_linear_state_machine/subscription_renewal_cycle_loop
    """
    sub_id, succ_id, patron_id = _renewal_cycle_to_confirmed(api)
    data = validate_success(api.confirm_renewal(sub_id, make_patron_headers(patron_id)), 200)
    assert data["status"] == "RENEWED", f"original should be RENEWED, got {data['status']}"


def test_renewal_successor_is_active_and_flagged_renewal(api):
    """PRD §3.3: "when that reference is supplied the subscription's derived
    `is_renewal` flag is true".
    PRD §3.4: "Within the open window a `BoxOfficeAgent` offers renewal on an
    active subscription, moving it from `ACTIVE` to `RENEWAL_PENDING`".

    The successor carrying prior_subscription_id is ACTIVE with is_renewal=true,
    completing the loop into the next cycle.

    Design: Difficulty/non_linear_state_machine/subscription_renewal_cycle_loop
    """
    sub_id, succ_id, patron_id = _renewal_cycle_to_confirmed(api)
    get_success_data(api.confirm_renewal(sub_id, make_patron_headers(patron_id)))
    succ = get_success_data(api.get_subscription(succ_id, ADMIN))
    assert succ["status"] == "ACTIVE", f"successor should be ACTIVE, got {succ['status']}"
    assert succ["is_renewal"] is True


# ==========================================================================
# Difficulty/cross_entity_state_dependency/subscription_offer_renewal_requires_season_renewal_open
# ==========================================================================
def test_offer_renewal_rejected_when_season_planning(api):
    """PRD §3.4: "Within the open window a `BoxOfficeAgent` offers renewal on an
    active subscription, moving it from `ACTIVE` to `RENEWAL_PENDING`, which is
    permitted only while the bound season is in `RENEWAL_OPEN`".

    Offering renewal while the season is still PLANNING is rejected with
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/subscription_offer_renewal_requires_season_renewal_open
    """
    ctx = th.setup_active_subscription(seat_tiers=("STANDARD",), patron_email="planning@example.com")
    assert ctx["season"]["status"] == "PLANNING"
    validate_error(api.offer_renewal(ctx["subscription"]["id"], AGENT), ApiErrorId.ERR_INVALID_STATE.value)


def test_offer_renewal_succeeds_only_after_open_renewal(api):
    """PRD §3.4: "A `SeasonAdmin` opens renewal, advancing the season from
    `PLANNING` to `RENEWAL_OPEN`".
    PRD §3.4: "offers renewal on an active subscription, moving it from `ACTIVE`
    to `RENEWAL_PENDING`, which is permitted only while the bound season is in
    `RENEWAL_OPEN`".

    Same operation that was rejected in PLANNING succeeds once the season is
    RENEWAL_OPEN — pinning the Subscription->Season cross-entity dependency.

    Design: Difficulty/cross_entity_state_dependency/subscription_offer_renewal_requires_season_renewal_open
    """
    ctx = th.setup_active_subscription(seat_tiers=("STANDARD",), patron_email="opened@example.com")
    th.set_clock("2026-05-02T00:00:00Z")
    get_success_data(api.open_renewal(ctx["season"]["id"], ADMIN))
    data = validate_success(api.offer_renewal(ctx["subscription"]["id"], AGENT), 200)
    assert data["status"] == "RENEWAL_PENDING"


# ==========================================================================
# Corner/endpoints/subscription_cancel_credits_patron
# ==========================================================================
def test_subscription_cancel_releases_seat_and_credits_patron(api):
    """PRD §3.4: "Cancellation releases all of the subscription's `ASSIGNED` and
    `RENEWAL_OFFERED` subscription seats to `RELEASED` and credits the patron by
    adding the subscription's `total_price_cents` to their `account_credit_cents`."

    Design: Corner/endpoints/subscription_cancel_credits_patron
    """
    ctx = th.setup_active_subscription(seat_tiers=("STANDARD",), base_subscription_fee_cents=20000,
                                       patron_email="cancelsub@example.com")
    patron_id = ctx["patron"]["id"]
    sub_id = ctx["subscription"]["id"]
    ss_id = ctx["subscription_seats"][0]["id"]
    assert ctx["subscription"]["total_price_cents"] == 20000

    data = validate_success(api.cancel_subscription(sub_id, make_patron_headers(patron_id)), 200)
    assert data["status"] == "CANCELLED"
    ss = get_success_data(api.get_subscription_seat(ss_id, ADMIN))
    assert ss["status"] == "RELEASED"
    patron = get_success_data(api.get_patron(patron_id, ADMIN))
    assert patron["account_credit_cents"] == 20000, (
        f"expected credit 20000, got {patron['account_credit_cents']}")


# ==========================================================================
# Corner/state_machines/subscription_confirm_renewal_from_draft_invalid
# ==========================================================================
def test_confirm_renewal_from_draft_rejected(api):
    """PRD §3.4: "The owning `Patron` then confirms the renewal, moving the
    subscription from `RENEWAL_PENDING` to `RENEWED`".

    confirm-renewal on a DRAFT subscription (not RENEWAL_PENDING) is rejected with
    ERR_INVALID_STATE.

    Design: Corner/state_machines/subscription_confirm_renewal_from_draft_invalid
    """
    th.set_clock("2026-04-01T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000)
    patron = th.create_patron(email="draftconfirm@example.com")
    ph = make_patron_headers(patron["id"])
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    assert sub["status"] == "DRAFT"
    validate_error(api.confirm_renewal(sub["id"], ph), ApiErrorId.ERR_INVALID_STATE.value)
