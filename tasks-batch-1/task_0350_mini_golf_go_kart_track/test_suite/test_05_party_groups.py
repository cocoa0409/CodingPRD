"""Party-group lifecycle: deposit refund vs forfeit on cancel, and the
empty-member-set confirm guard.

Covers Difficulty queue rule non_linear_state_machine (party-group branching)
and boundary_precision_check (empty member set).
"""
from test_helpers import (
    validate_success, validate_error,
    make_ops_manager_headers,
    create_venue, create_attraction, create_pricing_plan, create_heat, open_heat,
    create_guest, sign_waiver, get_wallet_for_guest, top_up,
    create_party_group, create_heat_hold_booking,
    get_party_group, get_wallet, get_venue,
)

OPS = make_ops_manager_headers()


def test_party_group_draft_cancel_refunds_confirmed_cancel_forfeits(api):
    """PRD §3.10: "The deposit's fate turns entirely on when the cancellation
    happens — if the group is cancelled while still DRAFT, the deposit is refunded
    by crediting deposit_cents back to the host wallet's arcade_card_balance_cents;
    if the group is cancelled while CONFIRMED, the deposit is forfeited and no
    refund is made."

    Design: Difficulty/non_linear_state_machine/party_group_branching_refund_vs_forfeit
    """
    venue = create_venue(name="Track D", set_clock=None)
    host = create_guest(full_name="Host", height_cm=175)
    wallet = get_wallet_for_guest(host["id"])
    top_up(wallet["id"], 4000)  # below 5000, no loyalty bonus

    grp1 = create_party_group(venue["id"], host["id"], deposit_cents=2000,
                              included_unit_count=10, package_name="P1")
    grp2 = create_party_group(venue["id"], host["id"], deposit_cents=2000,
                              included_unit_count=10, package_name="P2")
    # Balance now 4000 - 2000 - 2000 = 0.

    # Give grp2 a member booking so it can be confirmed.
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=10)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])
    open_heat(heat["id"])
    sign_waiver(host["id"])
    create_heat_hold_booking(venue["id"], host["id"], heat["id"], plan["id"],
                             party_size=1, group_id=grp2["id"])
    grp2_v = get_party_group(grp2["id"])["version"]
    validate_success(api.confirm_party_group(grp2["id"], {"expected_group_version": grp2_v}, OPS), 200)

    # grp1 cancelled while DRAFT -> deposit refunded (+2000).
    validate_success(api.cancel_party_group(grp1["id"], OPS), 200)
    # grp2 cancelled while CONFIRMED -> deposit forfeited (no refund).
    validate_success(api.cancel_party_group(grp2["id"], OPS), 200)

    assert get_party_group(grp1["id"])["status"] == "CANCELLED"
    assert get_party_group(grp2["id"])["status"] == "CANCELLED"
    bal = get_wallet(wallet["id"])["arcade_card_balance_cents"]
    # 4000 - 2000 - 2000 + 2000 (P1 DRAFT refund) = 2000; P2 forfeited.
    assert bal == 2000, f"expected 2000 (P1 refunded, P2 forfeited), got {bal}"


def test_party_group_draft_create_debits_deposit_cancel_refunds(api):
    """PRD §3.10: "Creation opens the group in DRAFT status with units_consumed at
    zero and debits deposit_cents from the host's wallet arcade_card_balance_cents".
    PRD §3.10: "if the group is cancelled while still DRAFT, the deposit is refunded
    by crediting deposit_cents back to the host wallet's arcade_card_balance_cents".

    Design: Difficulty/non_linear_state_machine/party_group_branching_refund_vs_forfeit
    """
    # Isolated DRAFT branch: create debits, DRAFT-cancel restores full balance.
    venue = create_venue(name="Track D2", set_clock=None)
    host = create_guest(full_name="Host2", height_cm=175)
    wallet = get_wallet_for_guest(host["id"])
    top_up(wallet["id"], 3000)
    grp = create_party_group(venue["id"], host["id"], deposit_cents=2000,
                             included_unit_count=5, package_name="Solo")
    assert get_wallet(wallet["id"])["arcade_card_balance_cents"] == 1000, "deposit debited at create"
    assert get_party_group(grp["id"])["status"] == "DRAFT"

    validate_success(api.cancel_party_group(grp["id"], OPS), 200)
    assert get_party_group(grp["id"])["status"] == "CANCELLED"
    assert get_wallet(wallet["id"])["arcade_card_balance_cents"] == 3000, (
        "DRAFT cancel refunds the deposit to the host wallet"
    )


def test_party_confirm_empty_member_set_rejected(api):
    """PRD §3.10: "Confirmation requires the venue to be OPEN and requires the group
    to hold at least one member booking in HOLD or CONFIRMED; a group with no such
    member cannot be confirmed and is rejected with ERR_PARTY_GROUP_EMPTY."

    Design: Difficulty/boundary_precision_check/party_confirm_empty_member_set_rejected
    """
    venue = create_venue(name="Track J", set_clock=None)
    host = create_guest(full_name="Host", height_cm=175)
    grp = create_party_group(venue["id"], host["id"], deposit_cents=0,
                             included_unit_count=5, package_name="Empty")
    grp_v = get_party_group(grp["id"])["version"]
    res = api.confirm_party_group(grp["id"], {"expected_group_version": grp_v}, OPS)
    validate_error(res, "ERR_PARTY_GROUP_EMPTY")
    assert get_party_group(grp["id"])["status"] == "DRAFT", "group unchanged"


def test_party_confirm_with_one_hold_member_succeeds(api):
    """PRD §3.10: "Confirmation requires the venue to be OPEN and requires the group
    to hold at least one member booking in HOLD or CONFIRMED; a group with no such
    member cannot be confirmed and is rejected with ERR_PARTY_GROUP_EMPTY."

    Design: Difficulty/boundary_precision_check/party_confirm_empty_member_set_rejected
    """
    # The boundary's other side: exactly one HOLD member clears the empty-set guard.
    venue = create_venue(name="Track J2", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])
    open_heat(heat["id"])
    host = create_guest(full_name="Host", height_cm=175)
    sign_waiver(host["id"])
    grp = create_party_group(venue["id"], host["id"], deposit_cents=0,
                             included_unit_count=5, package_name="OneMember")
    create_heat_hold_booking(venue["id"], host["id"], heat["id"], plan["id"],
                             party_size=1, group_id=grp["id"])  # one HOLD member

    grp_v = get_party_group(grp["id"])["version"]
    confirmed = validate_success(
        api.confirm_party_group(grp["id"], {"expected_group_version": grp_v}, OPS), 200)
    assert confirmed["status"] == "CONFIRMED", "group with a HOLD member confirms"
