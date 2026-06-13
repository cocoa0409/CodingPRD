"""Partner transfers: conversion, compensation, blackouts, and the member OCC guard.

Covers tier-ratio conversion (pinned tier-first order), the submit/reverse
conservation invariant, optimistic concurrency on the member version, blackout
temporal overlap with buffer, and the transfer-block / partner-paused gates.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_error,
    set_clock,
    setup_program,
    register_member,
    post_purchase,
    get_member,
    member_version,
    add_partner,
    submit_transfer,
    setup_member_and_partner,
    setup_submitted_transfer,
    schedule_blackout,
    create_partner_transfer_payload,
    ApiErrorId,
    STANDARD_GOLD,
    STANDARD_ONLY,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Conversion MODE (c): partner_points = floor(loyalty_points * tier ratio)
# ---------------------------------------------------------------------------
def test_partner_transfer_floor_with_gold_ratio(api):
    """PRD 3.8: "First the member's `current_tier_code` is resolved through the trailing-window tier evaluation of Section 3.4; then the conversion ratio is taken as the `transfer_ratio` of that tier; then the `partner_points` is the `loyalty_points` multiplied by that ratio, with the floor taken once."

    GOLD member (transfer_ratio 0.8) transferring 1000 yields
    floor(1000 * 0.8) = 800 partner points.

    Design: Difficulty/combinatorial_formula/partner_transfer_ratio_from_tier_mode_c
    """
    base = setup_program(tiers=STANDARD_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    member = register_member(prog["id"])
    post_purchase(member["id"], 500000)   # GOLD (qualifying 5000)
    member = get_member(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 1000, member["version"])
    xfer = get_success_data(api.create_partner_transfer(payload, ADMIN))
    assert xfer["partner_points"] == 800, \
        f"Expected partner_points 800, got {xfer['partner_points']}"


def test_partner_transfer_standard_ratio_floor(api):
    """PRD 3.8: "then the `partner_points` is the `loyalty_points` multiplied by that ratio, with the floor taken once."

    STANDARD member (transfer_ratio 0.5) transferring 300 yields
    floor(300 * 0.5) = 150 partner points.

    Design: Difficulty/combinatorial_formula/partner_transfer_ratio_from_tier_mode_c
    """
    s = setup_member_and_partner(purchase_cents=90000, tiers=STANDARD_ONLY,
                                 transfer_block_size=100, min_transfer_points=100)
    member, partner = s["member"], s["partner"]
    payload = create_partner_transfer_payload(member["id"], partner["id"], 300, member["version"])
    xfer = get_success_data(api.create_partner_transfer(payload, ADMIN))
    assert xfer["partner_points"] == 150, \
        f"Expected partner_points 150, got {xfer['partner_points']}"


# ---------------------------------------------------------------------------
# Compensating invariant: submit + reverse conserves available_points
# ---------------------------------------------------------------------------
def test_transfer_reverse_conserves_available_points(api):
    """PRD 3.8: "reversal is legal only from `SUBMITTED` and is a compensating action that mints a `TRANSFER_IN_REVERSAL` `PointsLot` of the original `loyalty_points` back to the member, appends a `TRANSFER_IN_REVERSAL` `PointsTransaction` (referencing the transfer through `ref_transfer_id`), recomputes the member's balances, and moves the transfer to the terminal `REVERSED` status — restoring the member's net minted-minus-burned loyalty points to their pre-transfer value."

    Member with 900 available points submits a 500-point transfer (available drops
    to 400) then reverses it; available_points returns to exactly 900.

    Design: Difficulty/compensating_invariant/transfer_submit_reverse_conserves_member_available_points
    """
    s = setup_submitted_transfer(loyalty_points=500, purchase_cents=90000, tiers=STANDARD_ONLY)
    member, transfer = s["member"], s["transfer"]
    reversed_xfer = get_success_data(api.reverse_transfer(transfer["id"], ADMIN))
    assert reversed_xfer["status"] == "REVERSED", \
        f"Expected REVERSED, got {reversed_xfer['status']}"
    member = get_member(member["id"])
    assert member["available_points"] == 900, \
        f"Expected 900 conserved, got {member['available_points']}"


def test_transfer_submit_burns_available_points(api):
    """PRD 3.8: "A submitted transfer burns `loyalty_points` from the member's lots in FIFO order (recording `TRANSFER_OUT` ledger rows referencing the transfer through `ref_transfer_id`), recomputes the member's balances, advances the member's `version` by one, and enters `SUBMITTED` status."

    A member with 900 available points who submits a 500-point transfer is left
    with available_points 400 immediately after submit.

    Design: Difficulty/compensating_invariant/transfer_submit_reverse_conserves_member_available_points
    """
    s = setup_submitted_transfer(loyalty_points=500, purchase_cents=90000, tiers=STANDARD_ONLY)
    member = get_member(s["member"]["id"])
    assert member["available_points"] == 400, \
        f"Expected 400 after submit, got {member['available_points']}"


# ---------------------------------------------------------------------------
# OCC on member version at transfer submit
# ---------------------------------------------------------------------------
def test_transfer_submit_stale_member_version_rejected(api):
    """PRD 2.9: "Submitting a partner transfer likewise requires `expected_member_version` to match the member's current `version`. Because the transfer's `partner_points` depend on the member's current tier and the burn depends on `available_points`, an advance of the member's `version` since the client's last read means another posted ledger mutation has occurred and the client's basis is stale; the submission is then rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), again checked last, just before the write."

    A version captured before a later posted purchase bumped it is stale: the
    transfer submission is rejected with ERR_STALE_MEMBER_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_transfer_submit
    """
    s = setup_member_and_partner(purchase_cents=100000, tiers=STANDARD_ONLY)
    member, partner = s["member"], s["partner"]
    stale_v = member_version(member["id"])
    post_purchase(member["id"], 50000)   # bumps member version
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, stale_v)
    resp = api.create_partner_transfer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)


def test_transfer_submit_correct_version_succeeds(api):
    """PRD 2.9: "When a member confirms a quoted redemption, the request must carry `expected_member_version` holding the `version` of the `Member` the client last observed. The server compares it to the member's current `version` just before the burn is written."

    A transfer carrying the live member version succeeds (201, SUBMITTED) and
    leaves available_points at 900 (1000 minted, 100 transferred).

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_transfer_submit_succeeds
    """
    s = setup_member_and_partner(purchase_cents=100000, tiers=STANDARD_ONLY)
    member, partner = s["member"], s["partner"]
    v = member_version(member["id"])
    payload = create_partner_transfer_payload(member["id"], partner["id"], 100, v)
    resp = api.create_partner_transfer(payload, ADMIN)
    xfer = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert xfer["status"] == "SUBMITTED", f"Expected SUBMITTED, got {xfer['status']}"
    member = get_member(member["id"])
    assert member["available_points"] == 900, \
        f"Expected 900, got {member['available_points']}"


# ---------------------------------------------------------------------------
# Transfer-block constraint
# ---------------------------------------------------------------------------
def test_transfer_not_multiple_of_block_rejected(api):
    """PRD 3.8: "The `loyalty_points` must be a positive whole multiple of the partner's `transfer_block_size` and must be at least the partner's `min_transfer_points`; a value violating either constraint is rejected with `ERR_INVALID_TRANSFER_BLOCK` (HTTP 422)."

    A transfer of 150 against block_size 100 is not a whole multiple and is
    rejected.

    Design: Corner/calculations/transfer_not_multiple_of_block_returns_422
    """
    s = setup_member_and_partner(purchase_cents=100000, tiers=STANDARD_ONLY,
                                 transfer_block_size=100, min_transfer_points=100)
    member, partner = s["member"], s["partner"]
    payload = create_partner_transfer_payload(member["id"], partner["id"], 150, member["version"])
    resp = api.create_partner_transfer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSFER_BLOCK.value)


# ---------------------------------------------------------------------------
# Blackout temporal overlap with 60-minute buffer
# ---------------------------------------------------------------------------
def test_blackout_within_buffer_rejected(api):
    """PRD 3.8: "A new blackout must keep clear of every existing `SCHEDULED` blackout on the same partner by a sixty-minute buffer on each side: the new interval conflicts when its `starts_at` is at or before an existing blackout's `ends_at` extended forward by sixty minutes, and at the same time the existing blackout's `starts_at` pulled back by sixty minutes is at or before the new interval's `ends_at`."

    Existing blackout [00:00, 01:00]; a new one starting 01:30 (30 minutes after,
    inside the 60-minute buffer) is rejected with ERR_BLACKOUT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/blackout_window_overlap_closed_with_buffer
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    schedule_blackout(partner["id"], "2026-06-14T00:00:00Z", "2026-06-14T01:00:00Z")
    resp = api.create_blackout(
        partner["id"],
        {"partner_account_id": partner["id"], "starts_at": "2026-06-14T01:30:00Z",
         "ends_at": "2026-06-14T02:30:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP.value)


def test_blackout_outside_buffer_accepted(api):
    """PRD 3.8: "A new blackout must keep clear of every existing `SCHEDULED` blackout on the same partner by a sixty-minute buffer on each side: the new interval conflicts when its `starts_at` is at or before an existing blackout's `ends_at` extended forward by sixty minutes, and at the same time the existing blackout's `starts_at` pulled back by sixty minutes is at or before the new interval's `ends_at`."

    A new blackout starting well past the 60-minute buffer of the existing one
    (existing [00:00, 01:00], new [03:00, 04:00]) is accepted (201, SCHEDULED).

    Design: Difficulty/resource_temporal_overlap/blackout_window_overlap_closed_with_buffer
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    schedule_blackout(partner["id"], "2026-06-14T00:00:00Z", "2026-06-14T01:00:00Z")
    resp = api.create_blackout(
        partner["id"],
        {"partner_account_id": partner["id"], "starts_at": "2026-06-14T03:00:00Z",
         "ends_at": "2026-06-14T04:00:00Z"}, ADMIN)
    bo = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert bo["status"] == "SCHEDULED", f"Expected SCHEDULED, got {bo['status']}"
