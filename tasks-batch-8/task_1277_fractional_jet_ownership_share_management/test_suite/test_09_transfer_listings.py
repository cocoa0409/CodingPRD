"""Transfer listings: sale lifecycle, depreciation rebase, self-dealing, OCC on the
listing, wind-down cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_booking_ok,
    complete_booking_ok,
    create_activated_share,
    create_aircraft,
    create_booking_ok,
    create_confirmed_booking,
    create_owner,
    create_transfer_listing_ok,
    get_booking,
    get_share,
    make_owner_headers,
    setup_program_with_share,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _seller_with_listing(program_code="FJX-SM4", fly_hours=None):
    """Seller with an ACTIVE 1/8 MID share (optionally with flown hours) and a LISTED
    transfer listing; a second GOOD owner stands by as buyer."""
    sc = setup_program_with_share(program_code=program_code, class_code="MID")
    if fly_hours is not None:
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N910SM")
        create_completed = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-05T15:00:00Z", fly_hours,
        )
        assign_booking_ok(create_completed["id"], tail["id"])
        complete_booking_ok(create_completed["id"], fly_hours)
    buyer = create_owner(sc["program"]["id"], legal_name=f"{program_code} Buyer")
    listing = create_transfer_listing_ok(
        sc["share"]["id"], sc["owner"]["id"], asking_price_cents=10000000,
    )
    sc.update({"buyer": buyer, "listing": listing})
    return sc


class TestSaleRebasesDepreciation:
    def test_close_sale_reassigns_share_and_rebases_schedule(self, api):
        """PRD §3.8: "The listing becomes `SOLD`; the share's ownership is reassigned to
        the buyer; its `hours_remaining_cy` carries over untouched — the entitlement
        follows the share, not the owner; the depreciation schedule is rebased with a
        new basis equal to the final sale price and `accumulated_depreciation_cents`
        reset to zero for the buyer; and the share returns from `LISTED` to `ACTIVE`
        under its new owner, its `version` advancing once more."

        Design: Corner/state_machines/transfer_listing_sale_rebases_depreciation
        """
        sc = _seller_with_listing("FJX-SM4", fly_hours=4.00)
        listing = sc["listing"]
        accepted = validate_success(
            api.accept_listing(
                listing["id"],
                {"buyer_owner_id": sc["buyer"]["id"],
                 "expected_listing_version": listing["version"]},
                make_owner_headers(sc["buyer"]["id"]),
            ),
            200,
        )
        assert accepted["listing_status"] == "UNDER_OFFER"
        sold = validate_success(
            api.close_sale(listing["id"], {"final_sale_price_cents": 11000000}, FIN), 200
        )
        assert sold["listing_status"] == "SOLD"

        share = get_share(sc["share"]["id"])
        assert share["owner_id"] == sc["buyer"]["id"], "ownership follows the sale"
        assert share["share_status"] == "ACTIVE", "share returns to ACTIVE under the buyer"
        assert share["hours_remaining_cy"] == pytest.approx(96.00, abs=0.005), (
            "entitlement follows the share: 100.00 - 4.00 flown carries over"
        )
        scheds, _meta = validate_paginated(
            api.list_depreciation_schedules(FIN, params={"share_id": sc["share"]["id"]})
        )
        rebased = [s for s in scheds if s["basis_cents"] == 11000000]
        assert rebased, f"expected a schedule rebased to the sale price, got {scheds}"
        assert rebased[0]["accumulated_depreciation_cents"] == 0, (
            "the buyer's schedule starts with zero accumulated depreciation"
        )


class TestListingGates:
    def test_self_dealing_accept_rejected(self, api):
        """PRD §3.8: "Self-dealing is forbidden — a buyer identical to the share's
        current owner is rejected with `ERR_SELF_DEALING` (HTTP 422)"

        Design: Corner/validations/listing_accept_self_dealing_rejected
        """
        sc = _seller_with_listing("FJX-VA6")
        listing = sc["listing"]
        resp = api.accept_listing(
            listing["id"],
            {"buyer_owner_id": sc["owner"]["id"],
             "expected_listing_version": listing["version"]},
            make_owner_headers(sc["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_DEALING)
        assert resp.status_code == 422
        unchanged = validate_success(api.get_transfer_listing(listing["id"], FIN), 200)
        assert unchanged["listing_status"] == "LISTED"

    def test_stale_listing_version_rejected_on_accept(self, api):
        """PRD §2.7: "Accepting a transfer listing (`POST /transfer-listings/{id}/accept`)
        requires `expected_listing_version` matching the listing's current `version`; if
        the listing has advanced since the buyer last read it — for example because the
        seller amended the asking price — the acceptance is rejected with
        `ERR_STALE_LISTING_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_listing_version_covered
        """
        sc = _seller_with_listing("FJX-ER2")
        listing = sc["listing"]
        resp = api.accept_listing(
            listing["id"],
            {"buyer_owner_id": sc["buyer"]["id"],
             "expected_listing_version": listing["version"] - 1},
            make_owner_headers(sc["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LISTING_VERSION)
        assert resp.status_code == 412
        unchanged = validate_success(api.get_transfer_listing(listing["id"], FIN), 200)
        assert unchanged["listing_status"] == "LISTED"

    def test_duplicate_live_listing_rejected(self, api):
        """PRD §3.8: "the share must be `ACTIVE` with no other listing of it live — in
        `LISTED` or `UNDER_OFFER`; a duplicate live listing, or a listing attempted
        against a share in any other state, is rejected with `ERR_REFERENTIAL_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/exit_value_temporal_vs_referential_priority
        """
        sc = _seller_with_listing("FJX-PP2B")
        # The share is already covered by a LISTED listing; a second create must fail
        # on referential integrity regardless of a fresh OCC version.
        current_v = get_share(sc["share"]["id"])["version"]
        resp = api.create_transfer_listing(
            {
                "share_id": sc["share"]["id"],
                "asking_price_cents": 11000000,
                "program_repurchase_flag": False,
                "expected_share_version": current_v,
            },
            make_owner_headers(sc["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_CONFLICT)
        assert resp.status_code == 409


class TestWindDownCascade:
    def test_wind_down_expires_listings_and_requested_bookings_only(self, api):
        """PRD §2.9: "A `ProgramAdmin` may move a program from `ACTIVE` or `SUSPENDED`
        into `WINDING_DOWN`, after which the creation of new shares and new booking
        requests is rejected, every booking still in `REQUESTED` is expired, and every
        transfer listing still `LISTED` cascades to `EXPIRED`."

        Design: Corner/cross_cutting_layers/cascade_wind_down_expires_listings_and_bookings
        """
        sc = setup_program_with_share(program_code="FJX-CC2", class_code="MID")
        owner_b = create_owner(sc["program"]["id"], legal_name="CC2 OwnerB")
        share_b = create_activated_share(owner_b["id"], sc["cls"]["id"])
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N777CC")

        # One LISTED listing on the first owner's share
        listing = create_transfer_listing_ok(
            sc["share"]["id"], sc["owner"]["id"], asking_price_cents=10000000,
        )
        # One REQUESTED booking and one CONFIRMED+assigned booking on share B
        bk_req = create_booking_ok(
            share_b["id"], owner_b["id"], sc["cls"]["id"], "2026-09-10T15:00:00Z", 1.00,
        )
        bk_conf = create_confirmed_booking(
            share_b["id"], owner_b["id"], sc["cls"]["id"], "2026-09-12T15:00:00Z", 1.00,
        )
        assign_booking_ok(bk_conf["id"], tail["id"])

        resp = api.wind_down_program(sc["program"]["id"], ADMIN)
        program = validate_success(resp, 200)
        assert program["program_posture"] == "WINDING_DOWN"

        listed_after = validate_success(api.get_transfer_listing(listing["id"], ADMIN), 200)
        assert listed_after["listing_status"] == "EXPIRED", (
            "wind-down cascades live listings to EXPIRED"
        )
        req_after = get_booking(bk_req["id"])
        assert req_after["booking_status"] == "EXPIRED", (
            "wind-down expires bookings still in REQUESTED"
        )
        conf_after = get_booking(bk_conf["id"])
        assert conf_after["booking_status"] == "CONFIRMED", (
            "wind-down does not touch CONFIRMED bookings"
        )
