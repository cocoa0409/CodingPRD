"""Consignment negotiation loop, proceeds waterfall, settlement cascade, and listing gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_member_locker_bottle, open_consignment,
    setup_offered_consignment, setup_accepted_consignment, setup_listed_consignment,
    make_cellar_member_headers,
)

MGR = TEST_USERS["cellar_manager_headers"]
BROKER = TEST_USERS["auction_broker_headers"]


# --------------------------------------------------------------------------- #
# Queue A — dual_variant_calc / consignment_provisional_vs_final_proceeds_diverge
# --------------------------------------------------------------------------- #
def test_consignment_provisional_estimate_on_accept(api):
    """PRD §3.7: "Acceptance moves the consignment to `ACCEPTED` and writes a provisional
    payout estimate into `estimated_proceeds_cents`, computed by the proceeds waterfall
    below over the accepted `offer_price_cents`; the provisional computation touches
    neither the ledger nor the bottle."

    Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_proceeds_diverge
    """
    member, locker, bottle, cn = setup_accepted_consignment(
        api, offer_price_cents=4_000_000, reserve_price_cents=3_000_000
    )
    # 0.20 tier: comm=800000, net=3200000, fee=96000 -> 3104000
    assert cn["estimated_proceeds_cents"] == 3_104_000, (
        f"provisional estimate should be 3104000, got {cn['estimated_proceeds_cents']}"
    )


def test_consignment_final_proceeds_on_settle(api):
    """PRD §3.7: "First, the `commission_pct` is selected by price tier: the fraction is
    0.20 when the price is at most 5,000,000 cents, 0.15 when the price is greater than
    that but at most 20,000,000 cents, and 0.10 when the price exceeds 20,000,000 cents."
    PRD §3.7: "the final run stores the selected fraction in `commission_pct` and the
    result in `net_proceeds_cents`."

    Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_proceeds_diverge
    """
    member, locker, bottle, cn = setup_accepted_consignment(
        api, offer_price_cents=4_000_000, reserve_price_cents=3_000_000
    )
    settled = validate_success(
        api.settle_consignment(cn["id"], {"hammer_price_cents": 6_000_000}, BROKER)
    )
    # 0.15 tier: comm=900000, net=5100000, fee=153000 -> 4947000
    assert settled["net_proceeds_cents"] == 4_947_000, (
        f"final net proceeds should be 4947000, got {settled['net_proceeds_cents']}"
    )
    assert settled["commission_pct"] == 0.15, (
        f"commission_pct should be 0.15, got {settled['commission_pct']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — non_linear_state_machine / consignment_offer_counter_offer_loop
# --------------------------------------------------------------------------- #
def test_consignment_counter_moves_to_countered(api):
    """PRD §3.7: "From `OFFERED`, the `CellarMember` may counter, supplying
    `counter_price_cents` and moving it to `COUNTERED`".

    Design: Difficulty/non_linear_state_machine/consignment_offer_counter_offer_loop
    """
    member, locker, bottle, cn = setup_offered_consignment(
        api, offer_price_cents=4_500_000, reserve_price_cents=4_000_000
    )
    countered = validate_success(
        api.counter_consignment(cn["id"], {"counter_price_cents": 5_500_000},
                                make_cellar_member_headers(member["id"]))
    )
    assert countered["status"] == "COUNTERED", f"expected COUNTERED, got {countered['status']}"


def test_consignment_reoffer_after_counter_loops_to_offered(api):
    """PRD §3.7: "the broker may then offer again, and the `OFFERED` and `COUNTERED`
    states can alternate any number of times."

    Design: Difficulty/non_linear_state_machine/consignment_offer_counter_offer_loop
    """
    member, locker, bottle, cn = setup_offered_consignment(
        api, offer_price_cents=4_500_000, reserve_price_cents=4_000_000
    )
    validate_success(
        api.counter_consignment(cn["id"], {"counter_price_cents": 5_500_000},
                                make_cellar_member_headers(member["id"]))
    )
    reoffered = validate_success(
        api.offer_consignment(cn["id"], {"offer_price_cents": 5_200_000}, BROKER)
    )
    assert reoffered["status"] == "OFFERED", f"expected OFFERED after re-offer, got {reoffered['status']}"
    assert reoffered["offer_price_cents"] == 5_200_000, (
        f"offer_price_cents should be updated to 5200000, got {reoffered['offer_price_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — transitive_cascade / consignment_settle_sell_bottle_recompute_locker
# --------------------------------------------------------------------------- #
def test_settle_marks_bottle_sold_and_detaches(api):
    """PRD §3.7: "the bottle transitions from `CONSIGNED` to the terminal `SOLD` with its
    `locker_id` cleared".

    Design: Difficulty/transitive_cascade/consignment_settle_sell_bottle_recompute_locker
    """
    member, locker, bottle, cn = setup_accepted_consignment(
        api, offer_price_cents=4_000_000, reserve_price_cents=3_000_000, capacity=3
    )
    validate_success(api.settle_consignment(cn["id"], {"hammer_price_cents": 6_000_000}, BROKER))
    b = validate_success(api.get_bottle(bottle["id"], MGR))
    assert b["status"] == "SOLD", f"bottle must be SOLD, got {b['status']}"
    assert b["locker_id"] is None, f"bottle locker_id must be cleared, got {b['locker_id']}"


def test_settle_recomputes_locker_and_credits_wallet(api):
    """PRD §3.7: "the source locker's `occupied_bottles`, `free_bottles`, and
    `occupancy_status` are recomputed, and a `CREDIT` ledger entry for the
    `net_proceeds_cents` is posted to the seller, raising their `wallet_balance_cents`."

    Design: Difficulty/transitive_cascade/consignment_settle_sell_bottle_recompute_locker
    """
    member, locker, bottle, cn = setup_accepted_consignment(
        api, offer_price_cents=4_000_000, reserve_price_cents=3_000_000, capacity=3
    )
    validate_success(api.settle_consignment(cn["id"], {"hammer_price_cents": 6_000_000}, BROKER))
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["occupied_bottles"] == 0, f"occupied should recompute to 0, got {lk['occupied_bottles']}"
    assert lk["free_bottles"] == 3, f"free should recompute to 3, got {lk['free_bottles']}"
    m = validate_success(api.get_member(member["id"], MGR))
    assert m["wallet_balance_cents"] == 4_947_000, (
        f"seller wallet must be credited net proceeds 4947000, got {m['wallet_balance_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — priority_pair_validation_conflict / list_referential_beats_temporal
# --------------------------------------------------------------------------- #
def test_list_provenance_error_beats_drink_window(api):
    """PRD §3.7: "the bottle must be `STORED` (otherwise `ERR_BOTTLE_NOT_STORED`), its
    `provenance_status` must be `DOCUMENTED` (otherwise `ERR_PROVENANCE_NOT_DOCUMENTED`),
    and its drink window must be open — a bottle whose `drink_window_status` is
    `TOO_YOUNG` is refused with `ERR_DRINK_WINDOW_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/list_referential_beats_temporal
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="SMALL", climate_zone="RED", capacity=3, tier="STANDARD",
        bottle_overrides={"provenance_status": "UNVERIFIED",
                          "drink_window_start_year": 2030, "drink_window_end_year": 2045},
    )
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=1_000_000)
    validate_error(
        api.list_consignment(cn["id"], BROKER), ApiErrorId.ERR_PROVENANCE_NOT_DOCUMENTED.value
    )


def test_list_referential_check_precedes_temporal_gate(api):
    """PRD §2.9: "the cross-entity member-active check; the cross-entity object-state
    checks on bottles; the temporal gates; the capacity and occupancy gates; the fiscal
    gates; and finally the optimistic-concurrency check on appraisal finalize."

    Design: Difficulty/priority_pair_validation_conflict/list_referential_beats_temporal
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="SMALL", climate_zone="RED", capacity=3, tier="STANDARD",
        bottle_overrides={"provenance_status": "UNVERIFIED",
                          "drink_window_start_year": 2030, "drink_window_end_year": 2045},
    )
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=1_000_000)
    validate_error(
        api.list_consignment(cn["id"], BROKER), ApiErrorId.ERR_PROVENANCE_NOT_DOCUMENTED.value
    )
    # rejected list performed no transition
    still = validate_success(api.get_consignment(cn["id"], BROKER))
    assert still["status"] == "DRAFT", f"rejected list must leave consignment DRAFT, got {still['status']}"


# --------------------------------------------------------------------------- #
# Queue A — priority_pair_validation_conflict / settle_state_beats_fiscal
# --------------------------------------------------------------------------- #
def test_settle_on_listed_returns_invalid_state(api):
    """PRD §2.9: "on state-transition endpoints, a resource that is not in a legal state
    for the requested transition yields `ERR_INVALID_STATE`."
    PRD §3.7: "Settlement is performed by the `AuctionBroker` and requires an `ACCEPTED`
    consignment."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_fiscal
    """
    member, locker, bottle, cn = setup_listed_consignment(api, reserve_price_cents=3_000_000)
    validate_error(
        api.settle_consignment(cn["id"], {"hammer_price_cents": 1}, BROKER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_settle_state_check_precedes_below_reserve(api):
    """PRD §2.9: "Every request is validated in a fixed priority order, and the first
    failing check determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_fiscal
    """
    member, locker, bottle, cn = setup_listed_consignment(api, reserve_price_cents=3_000_000)
    # hammer 1 is far below reserve, but state (not ACCEPTED) is checked first
    validate_error(
        api.settle_consignment(cn["id"], {"hammer_price_cents": 1}, BROKER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    still = validate_success(api.get_consignment(cn["id"], BROKER))
    assert still["status"] == "LISTED", f"consignment must remain LISTED, got {still['status']}"


# --------------------------------------------------------------------------- #
# Queue A — cross_entity_state_dependency / list_requires_bottle_stored
# --------------------------------------------------------------------------- #
def test_list_already_consigned_bottle_returns_not_stored(api):
    """PRD §3.7: "Listing is performed by an `AuctionBroker` and is gated on the bottle's
    condition: the consignment must be `DRAFT`, the bottle must be `STORED` (otherwise
    `ERR_BOTTLE_NOT_STORED`)".

    Design: Difficulty/cross_entity_state_dependency/list_requires_bottle_stored
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="PREMIUM",
        bottle_overrides={"provenance_status": "DOCUMENTED"},
    )
    cn1 = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_000_000)
    validate_success(api.list_consignment(cn1["id"], BROKER))  # bottle -> CONSIGNED
    cn2 = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_500_000)
    validate_error(api.list_consignment(cn2["id"], BROKER), ApiErrorId.ERR_BOTTLE_NOT_STORED.value)


def test_second_list_on_consigned_bottle_leaves_second_draft(api):
    """PRD §3.7: "Listing moves the consignment from `DRAFT` to `LISTED` and transitions
    the bottle from `STORED` to `CONSIGNED`."

    Design: Difficulty/cross_entity_state_dependency/list_requires_bottle_stored
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="PREMIUM",
        bottle_overrides={"provenance_status": "DOCUMENTED"},
    )
    cn1 = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_000_000)
    validate_success(api.list_consignment(cn1["id"], BROKER))
    cn2 = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_500_000)
    validate_error(api.list_consignment(cn2["id"], BROKER), ApiErrorId.ERR_BOTTLE_NOT_STORED.value)
    still = validate_success(api.get_consignment(cn2["id"], BROKER))
    assert still["status"] == "DRAFT", f"second consignment must stay DRAFT, got {still['status']}"


# --------------------------------------------------------------------------- #
# Queue B — errors / accept_below_reserve_returns_offer_below_reserve
# --------------------------------------------------------------------------- #
def test_accept_below_reserve_returns_offer_below_reserve(api):
    """PRD §3.7: "Acceptance requires the current `offer_price_cents` to be at least the
    `reserve_price_cents`; an offer below reserve is refused with
    `ERR_OFFER_BELOW_RESERVE`."

    Design: Corner/errors/accept_below_reserve_returns_offer_below_reserve
    """
    member, locker, bottle, cn = setup_offered_consignment(
        api, offer_price_cents=1_000_000, reserve_price_cents=3_000_000
    )
    validate_error(
        api.accept_consignment(cn["id"], make_cellar_member_headers(member["id"])),
        ApiErrorId.ERR_OFFER_BELOW_RESERVE.value,
    )


# --------------------------------------------------------------------------- #
# Queue B — errors / list_too_young_bottle_returns_drink_window_not_open
# --------------------------------------------------------------------------- #
def test_list_too_young_bottle_returns_drink_window_not_open(api):
    """PRD §3.7: "its drink window must be open — a bottle whose `drink_window_status` is
    `TOO_YOUNG` is refused with `ERR_DRINK_WINDOW_NOT_OPEN`."

    Design: Corner/errors/list_too_young_bottle_returns_drink_window_not_open
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="PREMIUM",
        bottle_overrides={"provenance_status": "DOCUMENTED",
                          "drink_window_start_year": 2030, "drink_window_end_year": 2050},
    )
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_000_000)
    validate_error(api.list_consignment(cn["id"], BROKER), ApiErrorId.ERR_DRINK_WINDOW_NOT_OPEN.value)
