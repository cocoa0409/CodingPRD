"""Validation ordering and individual business guards.

Covers the two priority-conflict pairs that the PRD pins explicitly in §2.10,
plus the individual safety/business validations (guardian, height, pass daily
limit, pass validity, waiver-missing).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_guest_patron_headers,
    create_ticket_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/invalid_state_beats_park_closed_on_confirm
# ===========================================================================

def test_invalid_state_reported_before_park_closed_on_reconfirm(api):
    """PRD §2.10: "an illegal state before a stale version, and a stale version
    before a closed-park rejection."
    PRD §2.10: "(5) state — the target is in a state from which the requested transition is defined,
    else `ERR_INVALID_STATE".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_park_closed_on_confirm
    """
    # Confirm a ticket, then weather-close the park (cascade expires the ticket).
    state = fx.setup_confirmed_ticket(
        clock="2026-03-10T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-10T10:00:00Z", block_ends="2026-03-10T12:00:00Z",
        park_overrides={"min_snow_depth_cm": 15},
    )
    park_id, block_id, ticket_id, patron = (
        state["park"]["id"], state["block"]["id"], state["ticket"]["id"], state["patron"]
    )
    fx.create_weather_log(park_id, observed_at="2026-03-10T10:35:00Z", snow_depth_cm=5, wind_kph=10)
    # Ticket is now EXPIRED and park CLOSED. Re-confirm -> state check fires first.
    v = fx.block_version(block_id, patron["id"])
    resp = api.confirm_ticket(ticket_id, v, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_expired_ticket_reconfirm_not_park_closed(api):
    """PRD §2.10: "(7) closed-park gating — a `CLOSED` posture blocks the gated operations, else
    `ERR_PARK_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_park_closed_on_confirm
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-10T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-10T10:00:00Z", block_ends="2026-03-10T12:00:00Z",
        park_overrides={"min_snow_depth_cm": 15},
    )
    park_id, block_id, ticket_id, patron = (
        state["park"]["id"], state["block"]["id"], state["ticket"]["id"], state["patron"]
    )
    fx.create_weather_log(park_id, observed_at="2026-03-10T10:35:00Z", snow_depth_cm=5, wind_kph=10)
    v = fx.block_version(block_id, patron["id"])
    resp = api.confirm_ticket(ticket_id, v, make_guest_patron_headers(patron["id"]))
    # The pinned order requires state over closed-park; must NOT be ERR_PARK_CLOSED.
    body = resp.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, \
        f"state check must pre-empt closed-park, got {body['error_id']}"


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/waiver_missing_beats_capacity_on_confirm
# ===========================================================================

def test_waiver_missing_reported_before_capacity_on_confirm(api):
    """PRD §2.10: "After these come the domain-specific business checks described
    throughout §3 — waiver presence, guardian requirement, height minimum, lane-turn
    overlap, block window, lane availability, pass daily limit, pass validity, and
    the capacity guard".

    Design: Difficulty/priority_pair_validation_conflict/waiver_missing_beats_capacity_on_confirm
    """
    # cap-1 lane filled by a waivered patron; a no-waiver patron confirms into the full block.
    base = fx.setup_park_with_lane_and_block(
        clock="2026-03-11T10:30:00Z", lane_capacity=1, num_lanes=1,
        block_starts="2026-03-11T10:00:00Z", block_ends="2026-03-11T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    pw, _ = fx.setup_waivered_patron(park_id)
    pn = fx.create_patron()  # NO waiver
    tw = fx.create_ticket(park_id, block_id, pw["id"])
    tn = fx.create_ticket(park_id, block_id, pn["id"])
    fx.confirm_ticket(tw["id"], pw["id"], block_id)  # fills capacity (committed 1 == cap 1)
    v = fx.block_version(block_id, pn["id"])
    resp = api.confirm_ticket(tn["id"], v, make_guest_patron_headers(pn["id"]))
    validate_error(resp, ApiErrorId.ERR_WAIVER_MISSING.value)


def test_no_waiver_confirm_into_full_block_not_capacity_error(api):
    """PRD §3.2: "confirming a ticket and boarding a rider both require an `ACTIVE` waiver to exist
    for the holder at the park, and the absence of one is rejected with
    `ERR_WAIVER_MISSING` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/waiver_missing_beats_capacity_on_confirm
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-03-11T10:30:00Z", lane_capacity=1, num_lanes=1,
        block_starts="2026-03-11T10:00:00Z", block_ends="2026-03-11T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    pw, _ = fx.setup_waivered_patron(park_id)
    pn = fx.create_patron()
    tw = fx.create_ticket(park_id, block_id, pw["id"])
    tn = fx.create_ticket(park_id, block_id, pn["id"])
    fx.confirm_ticket(tw["id"], pw["id"], block_id)
    v = fx.block_version(block_id, pn["id"])
    resp = api.confirm_ticket(tn["id"], v, make_guest_patron_headers(pn["id"]))
    body = resp.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_WAIVER_MISSING.value, \
        f"waiver presence must pre-empt capacity guard, got {body['error_id']}"


# ===========================================================================
# Corner/validations/guardian_required_for_minor_confirm
# ===========================================================================

def test_minor_confirm_without_guardian_rejected(api):
    """PRD §3.2: "a minor rider — one whose `rider_age_years` is less than 18 — requires that the
    holder's `ACTIVE` waiver carry a non-null `guardian_name`; confirming a ticket for a
    minor without a guardian signatory is rejected with `ERR_GUARDIAN_REQUIRED` (HTTP
    422)."

    Design: Corner/validations/guardian_required_for_minor_confirm
    """
    # Waiver without guardian_name, minor rider (age 12).
    state = fx.setup_reserved_ticket(
        clock="2026-03-30T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-30T10:00:00Z", block_ends="2026-03-30T12:00:00Z",
        rider_height_cm=130, rider_age_years=12, guardian_name=None,
    )
    block_id, ticket_id, patron = state["block"]["id"], state["ticket"]["id"], state["patron"]
    v = fx.block_version(block_id, patron["id"])
    resp = api.confirm_ticket(ticket_id, v, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_REQUIRED.value)
    ticket = validate_success(api.get_ticket(ticket_id, fx.OPERATOR), 200)
    assert ticket["lifecycle_state"] == "RESERVED"


# ===========================================================================
# Corner/validations/pass_daily_limit_blocks_fifth_gold_redemption
# ===========================================================================

def test_fifth_gold_redemption_blocked_by_daily_limit(api):
    """PRD §3.3: "a `GOLD` pass permits 4 per day". "A creation that would carry
    redemptions_today_count past the tier's allowance is rejected with
    ERR_PASS_DAILY_LIMIT (HTTP 409)."

    Design: Corner/validations/pass_daily_limit_blocks_fifth_gold_redemption
    """
    state = fx.setup_pass_holder(
        clock="2026-04-01T09:00:00Z", tier="GOLD",
        valid_from="2026-04-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z",
        block_starts="2026-04-01T10:00:00Z", block_ends="2026-04-01T12:00:00Z",
        patron_zip="90012",
    )
    park_id, block_id, patron, pass_id = (
        state["park"]["id"], state["block"]["id"], state["patron"], state["season_pass"]["id"]
    )
    # Four redemptions today.
    for _ in range(4):
        fx.create_ticket(park_id, block_id, patron["id"], season_pass_id=pass_id)
    # Fifth -> rejected.
    payload = create_ticket_payload(park_id=park_id, time_block_id=block_id,
                                    holder_patron_id=patron["id"], season_pass_id=pass_id)
    resp = api.create_ticket(payload, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PASS_DAILY_LIMIT.value)
    pass_after = validate_success(api.get_season_pass(pass_id, fx.OPERATOR), 200)
    assert pass_after["redemptions_today_count"] == 4


# ===========================================================================
# Corner/validations/pass_not_valid_when_suspended
# ===========================================================================

def test_ticket_against_suspended_pass_rejected(api):
    """PRD §3.3: "A `ParkOperator` may suspend an active pass — `ACTIVE → SUSPENDED` — which requires
    it to be `ACTIVE`; thereafter any ticket creation against that pass is refused as
    not valid."
    PRD §3.3: "its `status` must be `ACTIVE` and the logical clock must fall within the pass window
    — at or after `valid_from` and strictly before `valid_until`; otherwise the creation
    is rejected with `ERR_PASS_NOT_VALID` (HTTP 409)."

    Design: Corner/validations/pass_not_valid_when_suspended
    """
    state = fx.setup_pass_holder(
        clock="2026-04-02T09:00:00Z", tier="SILVER",
        valid_from="2026-04-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z",
        block_starts="2026-04-02T10:00:00Z", block_ends="2026-04-02T12:00:00Z",
        patron_zip="90013",
    )
    park_id, block_id, patron, pass_id = (
        state["park"]["id"], state["block"]["id"], state["patron"], state["season_pass"]["id"]
    )
    validate_success(api.suspend_season_pass(pass_id, fx.OPERATOR), 200)
    payload = create_ticket_payload(park_id=park_id, time_block_id=block_id,
                                    holder_patron_id=patron["id"], season_pass_id=pass_id)
    resp = api.create_ticket(payload, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PASS_NOT_VALID.value)
    pass_after = validate_success(api.get_season_pass(pass_id, fx.OPERATOR), 200)
    assert pass_after["status"] == "SUSPENDED"


# ===========================================================================
# Corner/errors/waiver_revoke_then_confirm_triggers_waiver_missing
# ===========================================================================

def test_confirm_after_waiver_revoked_triggers_waiver_missing(api):
    """PRD §3.2: "Once a waiver is revoked, any subsequent confirm or board for that holder at that
    park fails for lack of an active waiver unless another `ACTIVE` waiver covers them."
    PRD §3.2: "the absence of one is rejected with `ERR_WAIVER_MISSING` (HTTP 409)."

    Design: Corner/errors/waiver_revoke_then_confirm_triggers_waiver_missing
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-04-06T10:30:00Z", lane_capacity=5, num_lanes=1,
        block_starts="2026-04-06T10:00:00Z", block_ends="2026-04-06T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    patron = fx.create_patron()
    waiver = fx.sign_waiver(patron["id"], park_id)
    validate_success(api.revoke_waiver(waiver["id"], fx.MARSHAL), 200)
    ticket = fx.create_ticket(park_id, block_id, patron["id"])
    v = fx.block_version(block_id, patron["id"])
    resp = api.confirm_ticket(ticket["id"], v, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_WAIVER_MISSING.value)
    waiver_after = validate_success(api.get_waiver(waiver["id"], fx.OPERATOR), 200)
    assert waiver_after["status"] == "REVOKED"
