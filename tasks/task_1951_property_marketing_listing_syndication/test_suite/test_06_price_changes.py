"""Price changes: minimum-delta boundary, state gate precedence over business
rules, unchanged-price rejection, and the OCC stale-version guard (PRD §3.7, §2.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_price_change_payload,
    create_agent, owner_headers, create_draft_listing, create_active_listing,
    create_withdrawn_listing, get_listing,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]


class TestMinimumDeltaBoundary:
    def test_delta_exactly_50000_cents_passes(self, api):
        """PRD §3.7: "second, the movement must be material — either the absolute
        difference between the new and current price is at least 50000 cents, or the
        absolute percentage change, computed against the current price and rounded
        half up to two decimal places, is at least 1.0 percent — and a change failing
        both tests is rejected with `ERR_PRICE_CHANGE_TOO_SMALL`. A change meeting
        either threshold exactly passes."

        Design: Difficulty/boundary_precision_check/price_change_minimum_delta_boundary
        """
        agent, active = create_active_listing(list_price_cents=40000000)
        event = validate_success(api.create_price_change(
            active["id"],
            create_price_change_payload(40050000, active["version"]),
            owner_headers(agent)), 201)
        assert event["new_price_cents"] == 40050000
        assert get_listing(active["id"])["list_price_cents"] == 40050000

    def test_delta_49999_cents_below_both_thresholds_rejected(self, api):
        """PRD §3.7: "a change failing both tests is rejected with
        `ERR_PRICE_CHANGE_TOO_SMALL`."
        A 49999-cent delta on 40050000 is 0.12 percent when rounded half up to two
        decimals — below both the 50000-cent and the 1.0-percent thresholds.

        Design: Difficulty/boundary_precision_check/price_change_minimum_delta_boundary
        """
        agent, active = create_active_listing(list_price_cents=40000000)
        validate_success(api.create_price_change(
            active["id"],
            create_price_change_payload(40050000, active["version"]),
            owner_headers(agent)), 201)
        current = get_listing(active["id"])

        res = api.create_price_change(
            active["id"],
            create_price_change_payload(40000001, current["version"]),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_PRICE_CHANGE_TOO_SMALL, expected_status=422)
        assert get_listing(active["id"])["list_price_cents"] == 40050000


class TestStateGateBeatsBusinessRule:
    def test_price_change_on_withdrawn_listing_with_small_delta(self, api):
        """PRD §3.7: "Price movements on a live listing go through a dedicated
        price-change workflow, available while the listing is `ACTIVE` or
        `UNDER_CONTRACT` — any other lifecycle fails the state gate with
        `ERR_INVALID_STATE`"
        PRD §3.7: "The business checks run in a fixed order after the state, posture,
        and stale-version gates"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_price_change
        """
        agent, withdrawn = create_withdrawn_listing()
        res = api.create_price_change(
            withdrawn["id"],
            create_price_change_payload(50000100, withdrawn["version"]),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        listing = get_listing(withdrawn["id"])
        assert listing["list_price_cents"] == 50000000
        events = get_success_data(
            api.list_listing_events(withdrawn["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
        assert events == [], "no PRICE_CHANGE event may be appended by the rejected change"

    def test_price_change_on_draft_listing_with_small_delta(self, api):
        """PRD §3.7: "Price movements on a live listing go through a dedicated
        price-change workflow, available while the listing is `ACTIVE` or
        `UNDER_CONTRACT` — any other lifecycle fails the state gate with
        `ERR_INVALID_STATE`"
        PRD §2.9: "Endpoint-specific business rules — evaluated last, in the relative
        order stated for each workflow in §3."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_price_change
        """
        agent = create_agent()
        draft = create_draft_listing(agent)
        res = api.create_price_change(
            draft["id"],
            create_price_change_payload(50000100, draft["version"]),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_listing(draft["id"])["list_price_cents"] == 50000000


def test_unchanged_price_returns_price_unchanged(api):
    """PRD §3.7: "first, the new price must differ from the current
    `list_price_cents`, else `ERR_PRICE_UNCHANGED`"

    Design: Corner/validations/unchanged_price_returns_price_unchanged
    """
    agent, active = create_active_listing()
    res = api.create_price_change(
        active["id"],
        create_price_change_payload(50000000, active["version"]),
        owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_PRICE_UNCHANGED, expected_status=422)

    listing = get_listing(active["id"])
    assert listing["version"] == active["version"], "a rejected change must not bump version"
    events = get_success_data(
        api.list_listing_events(active["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
    assert events == []


def test_occ_stale_version_on_price_change(api):
    """PRD §2.8: "In both cases, if `expected_listing_version` does not match the
    listing's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412): another writer has advanced the listing since the client last read
    it, and the client's input is based on stale data."
    PRD §2.8: "Posting a price change likewise requires `expected_listing_version`
    in the request body, since the price-history head may have moved since the
    client last read the listing."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_price_change
    """
    agent, active = create_active_listing()
    stale_version = active["version"]
    validate_success(api.create_price_change(
        active["id"],
        create_price_change_payload(49000000, stale_version),
        owner_headers(agent)), 201)

    res = api.create_price_change(
        active["id"],
        create_price_change_payload(48000000, stale_version),
        owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    listing = get_listing(active["id"])
    assert listing["list_price_cents"] == 49000000
    events = get_success_data(
        api.list_listing_events(active["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
    assert len(events) == 1, "no PRICE_CHANGE event is appended for the rejected call"
