"""Writes refused because a *different* row is in the wrong state.

Each case replays the identical request once the other entity has moved, which
proves the refusal was a function of the neighbour's state and nothing else.
"""

from test_helpers import (
    DIRECTOR_HEADERS,
    SPONSORSHIP_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_inventory_conservation,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

UNSIGNED_OUTING = {
    "name": "Unsigned Course Open",
    "format": "BEST_BALL",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
UNSIGNED_CONTRACT = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 4,
    "fnb_minimum_cents": 0,
    "fnb_per_player_cents": 4500,
}


def _draft_contract_outing(api):
    """An outing that is complete in itself but whose contract is still DRAFT."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    outing = fx.new_outing(api, **UNSIGNED_OUTING)
    contract = fx.new_contract(api, outing["id"], **UNSIGNED_CONTRACT)
    tier = fx.new_tier(api, outing["id"])
    return {
        "outing_id": outing["id"],
        "contract_id": contract["id"],
        "tier_id": tier["id"],
    }


class TestOpenRegistrationWaitsOnTheContract:
    """The gate on DRAFT to OPEN reads the contract row, not the outing's own fields."""

    def test_open_registration_is_refused_while_the_contract_is_still_draft(self, api):
        """A complete, tiered outing cannot open over an unsigned contract.

        The PRD gates the move on the neighbour row: "the outing must have a
        contract whose status is `SIGNED` or `AMENDED`, and an outing with no
        contract at all fails the same check with `ERR_CONTRACT_NOT_SIGNED`".
        A package tier exists, so the only unmet precondition is the signature,
        and neither row may be disturbed by the refusal.

        Design: Difficulty/cross_entity_state_dependency/outing_cannot_open_registration_while_contract_is_draft
        """
        ctx = _draft_contract_outing(api)

        response = api.play_transition(
            ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"), DIRECTOR_HEADERS
        )
        validate_error(response, ApiErrorId.CONTRACT_NOT_SIGNED.value, 409)

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "DRAFT"
        assert outing["reopen_count"] == 0

        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["status"] == "DRAFT"
        assert contract["signed_at"] is None

    def test_the_identical_request_opens_the_field_once_the_course_signs(self, api):
        """Signing the contract, and nothing else, unblocks the replayed transition.

        The PRD says "Signing moves the contract from `DRAFT` to `SIGNED` and
        stamps `signed_at` from the logical clock." Because the outing was never
        touched by the earlier refusal, the same body now satisfies the same gate.

        Design: Difficulty/cross_entity_state_dependency/outing_cannot_open_registration_while_contract_is_draft
        """
        ctx = _draft_contract_outing(api)
        refused = api.play_transition(
            ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"), DIRECTOR_HEADERS
        )
        validate_error(refused, ApiErrorId.CONTRACT_NOT_SIGNED.value, 409)

        signed = fx.sign_contract(api, ctx["contract_id"])
        assert signed["status"] == "SIGNED"
        assert signed["signed_at"] is not None

        replay = api.play_transition(
            ctx["outing_id"], f.play_transition_payload("OPEN_REGISTRATION"), DIRECTOR_HEADERS
        )
        validate_success(replay, 200)
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"


UNPAID_OUTING = {"name": "Unpaid Sponsor Open", "field_capacity_teams": 1, "prize_pool_cents": 0}
SPONSOR_TIER_ONE_SIGN = {
    "code": "GOLD",
    "price_cents": 250000,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 1,
}


def _unpaid_sponsor_with_reserved_upsell(api):
    """A RESERVED upsell hold sitting under a registration that never paid."""
    ctx = fx.open_outing(api, tier=SPONSOR_TIER_ONE_SIGN, sponsor_tier=True, outing=UNPAID_OUTING)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Slow Pay Motors", player_count=0
    )
    asset = fx.new_asset(api, ctx["outing_id"])
    allocation = fx.new_allocation(api, registration["id"], asset["id"], source="UPSELL")
    ctx["registration_id"] = registration["id"]
    ctx["asset_id"] = asset["id"]
    ctx["allocation_id"] = allocation["id"]
    return ctx


class TestCommitWaitsOnTheRegistrationPayment:
    """A reservation is legal on an unpaid sponsor; recognizing its revenue is not."""

    def test_commit_is_refused_while_the_registration_is_pending_payment(self, api):
        """The hold stands, but the upsell cannot become revenue yet.

        Committing "requires the linked registration to be `CONFIRMED`,
        `AMENDED`, or `CHECKED_IN`, otherwise
        `ERR_REGISTRATION_NOT_REVENUE_RECOGNIZED`". The unit keeps the
        reservation it always legally held, and the outing recognizes nothing:
        "A registration still pending payment, waitlisted, cancelled, or refunded
        contributes nothing here, and neither does an allocation still merely
        reserved or already released."

        Design: Difficulty/cross_entity_state_dependency/allocation_cannot_commit_while_its_registration_is_unpaid
        """
        ctx = _unpaid_sponsor_with_reserved_upsell(api)
        assert fx.read_registration(api, ctx["registration_id"])["status"] == "PENDING_PAYMENT"

        response = api.allocation_fulfillment(
            ctx["allocation_id"], f.fulfillment_payload("COMMIT"), SPONSORSHIP_HEADERS
        )
        validate_error(response, ApiErrorId.REGISTRATION_NOT_REVENUE_RECOGNIZED.value, 409)

        allocation = fx.read_allocation(api, ctx["allocation_id"])
        assert allocation["status"] == "RESERVED"
        assert allocation["committed_at"] is None

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["reserved_count"] == 1
        assert asset["committed_count"] == 0
        assert asset["remaining_capacity"] == 0
        assert asset["status"] == "RESERVED"
        assert_inventory_conservation(asset)

        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 0

    def test_paying_the_registration_unblocks_the_identical_commit(self, api):
        """Payment alone turns the refused COMMIT into recognized revenue.

        On acceptance the PRD says that "when the source is an upsell it turns
        `upsell_price_cents` into recognized revenue", so gross revenue carries
        the 250000 sponsor package plus the 50000 hole sign.

        Design: Difficulty/cross_entity_state_dependency/allocation_cannot_commit_while_its_registration_is_unpaid
        """
        ctx = _unpaid_sponsor_with_reserved_upsell(api)
        refused = api.allocation_fulfillment(
            ctx["allocation_id"], f.fulfillment_payload("COMMIT"), SPONSORSHIP_HEADERS
        )
        validate_error(refused, ApiErrorId.REGISTRATION_NOT_REVENUE_RECOGNIZED.value, 409)

        paid = fx.pay_registration(api, ctx["registration_id"], 250000, TREASURER_HEADERS)
        assert paid["status"] == "CONFIRMED"

        replay = api.allocation_fulfillment(
            ctx["allocation_id"], f.fulfillment_payload("COMMIT"), SPONSORSHIP_HEADERS
        )
        validate_success(replay, 200)

        assert fx.read_allocation(api, ctx["allocation_id"])["status"] == "COMMITTED"
        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["committed_count"] == 1
        assert asset["reserved_count"] == 0
        assert_inventory_conservation(asset)
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 300000


WITHDRAWN_OUTING = {
    "name": "Withdrawn Sign Open",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
SPONSOR_TIER_TWO_SIGNS = {
    "code": "GOLD",
    "price_cents": 250000,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 2,
}
DOUBLE_SIGN = {
    "label": "Hole 9 double sign",
    "hole_number": 9,
    "capacity": 2,
    "exclusive": False,
    "list_price_cents": 50000,
}


def _confirmed_sponsor_with_withdrawn_sign(api):
    """A fully entitled sponsor facing a unit that has left the market unoccupied."""
    ctx = fx.open_outing(
        api, tier=SPONSOR_TIER_TWO_SIGNS, sponsor_tier=True, outing=WITHDRAWN_OUTING
    )
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Pulled Sign Partners", player_count=0
    )
    fx.pay_registration(api, registration["id"], 250000)
    asset = fx.new_asset(api, ctx["outing_id"], **DOUBLE_SIGN)
    fx.withdraw_asset(api, asset["id"])
    ctx["registration_id"] = registration["id"]
    ctx["asset_id"] = asset["id"]
    return ctx


class TestReservationWaitsOnTheAssetPosture:
    """A withdrawn unit reports its withdrawal, never a capacity shortfall."""

    def test_an_entitlement_allocation_against_a_withdrawn_unit_reports_the_withdrawal(self, api):
        """The unit was never occupied, so only its posture can explain the refusal.

        The declared order is explicit: "Fourth, a withdrawn unit is refused with
        `ERR_ASSET_WITHDRAWN`" and "this check deliberately precedes the capacity
        comparison, which a withdrawn unit would also fail, so a withdrawn unit
        never reports a capacity error." Withdrawal itself is what zeroed the
        headroom, since "The withdrawal forces `remaining_capacity` to 0 so the
        unit leaves the sellable pool."

        Design: Difficulty/cross_entity_state_dependency/allocation_cannot_be_reserved_against_a_withdrawn_asset
        """
        ctx = _confirmed_sponsor_with_withdrawn_sign(api)

        response = api.create_sponsor_allocation(
            f.sponsor_allocation_payload(
                ctx["registration_id"], ctx["asset_id"], "PACKAGE_ENTITLEMENT"
            ),
            SPONSORSHIP_HEADERS,
        )
        validate_error(response, ApiErrorId.ASSET_WITHDRAWN.value, 409)

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["status"] == "WITHDRAWN"
        assert asset["capacity"] == 2
        assert asset["remaining_capacity"] == 0
        assert asset["reserved_count"] == 0
        assert_inventory_conservation(asset)

        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 2
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 0

    def test_restoring_the_unit_lets_the_identical_reservation_through(self, api):
        """Restoring re-derives the headroom and the same body is accepted.

        The PRD states "Restoring reverses it, `WITHDRAWN → AVAILABLE`, and
        re-derives `remaining_capacity` back to the declared `capacity`", after
        which the entitlement allocation is born in `RESERVED`.

        Design: Difficulty/cross_entity_state_dependency/allocation_cannot_be_reserved_against_a_withdrawn_asset
        """
        ctx = _confirmed_sponsor_with_withdrawn_sign(api)
        payload = f.sponsor_allocation_payload(
            ctx["registration_id"], ctx["asset_id"], "PACKAGE_ENTITLEMENT"
        )
        validate_error(
            api.create_sponsor_allocation(payload, SPONSORSHIP_HEADERS),
            ApiErrorId.ASSET_WITHDRAWN.value,
            409,
        )

        restored = fx.restore_asset(api, ctx["asset_id"])
        assert restored["status"] == "AVAILABLE"
        assert restored["remaining_capacity"] == 2

        replay = api.create_sponsor_allocation(payload, SPONSORSHIP_HEADERS)
        allocation = validate_success(replay, 201)
        assert allocation["status"] == "RESERVED"
        assert fx.read_asset(api, ctx["asset_id"])["reserved_count"] == 1
