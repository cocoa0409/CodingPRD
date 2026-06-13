"""Late-cancel / no-show fee assessment, tiered surcharges, strike accrual and
member standing. Translates difficulty-design dual_variant_calc (fee base),
combinatorial_formula (tiered surcharge), transitive_cascade (no-show chain),
compensating_invariant (strike conservation) plus corner instances for the intro
and freeze conditional validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_network, setup_member_with_membership, create_member,
    create_active_membership, create_published_session, reserve, get_member,
    get_membership, drive_member_to_strikes, set_clock, api_client,
    make_member_headers, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]


def _fees_for_reservation(api, reservation_id):
    fees = get_success_data(api.list_fees(ADMIN, params={"reservation_id": reservation_id}))
    return fees if isinstance(fees, list) else fees.get("data", fees)


def test_first_late_cancel_fee_base_1500(api):
    """PRD §3.8: "The base is 1500 cents for a `LATE_CANCEL` and 2500 cents for a
    `NO_SHOW`."
    PRD §3.8: "A surcharge is then added according to the strike count observed before
    incrementing for this event: when the prior strike count is at most 1, the surcharge
    is 0 cents".

    Design: Difficulty/dual_variant_calc/fee_late_cancel_base_vs_no_show_base
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-02T10:00:00Z", seat_capacity=1)
    r1 = reserve(session["id"], member["id"], membership["id"])

    set_clock("2026-06-02T03:00:00Z")  # inside the 12h late-cancel window
    cancelled = validate_success(api.cancel_reservation(r1["id"], make_member_headers(member["id"])), 200)
    assert cancelled["attendance_status"] == "LATE_CANCELLED"

    fees = _fees_for_reservation(api, r1["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "LATE_CANCEL"
    assert fees[0]["amount_cents"] == 1500, f"first late-cancel base 1500, got {fees[0]['amount_cents']}"


def test_first_no_show_fee_base_2500(api):
    """PRD §3.8: "The base is 1500 cents for a `LATE_CANCEL` and 2500 cents for a
    `NO_SHOW`."
    PRD §3.7: "For each new no-show a `NO_SHOW` `FeeCharge` is assessed (see below), the
    seat credit is *not* refunded, the member's strike count is incremented, and their
    `standing` is recomputed."

    Design: Difficulty/dual_variant_calc/fee_late_cancel_base_vs_no_show_base
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-02T10:00:00Z", seat_capacity=1)
    r2 = reserve(session["id"], member["id"], membership["id"])

    set_clock("2026-06-02T11:30:00Z")  # past ends_at; never checked in
    validate_success(api.run_completion(ADMIN), 200)

    res = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert res["attendance_status"] == "NO_SHOW"
    fees = _fees_for_reservation(api, r2["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "NO_SHOW"
    assert fees[0]["amount_cents"] == 2500, f"first no-show base 2500, got {fees[0]['amount_cents']}"


def test_late_cancel_tier2_surcharge_at_prior_strikes_two(api):
    """PRD §3.8: "when the prior strike count is 2 or 3, the surcharge is 1000 cents".
    PRD §3.8: "The `amount_cents` is the base plus the surcharge."
    PRD §3.8: "At the boundaries, a prior count of exactly 1 lands in the zero-surcharge
    tier, and a prior count of exactly 2 lands in the 1000-cent tier."

    Design: Difficulty/combinatorial_formula/late_fee_tiered_surcharge_three_inputs
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "30 Pack", "price_cents": 9000,
                                        "grant_credits": 30, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # Build prior strikes == 2 via two NO_SHOWs.
    drive_member_to_strikes(net, member, membership, 2, base_clock="2026-06-01T00:00:00Z")
    assert get_member(member["id"])["no_show_strikes"] == 2

    # Session under test: late-cancel with prior_strikes == 2 -> 1500 + 1000.
    set_clock("2026-06-05T00:00:00Z")
    s3 = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-05T10:00:00Z", seat_capacity=1)
    r3 = reserve(s3["id"], member["id"], membership["id"])
    cancelled = validate_success(api.cancel_reservation(r3["id"], make_member_headers(member["id"])), 200)
    assert cancelled["attendance_status"] == "LATE_CANCELLED"

    fees = _fees_for_reservation(api, r3["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "LATE_CANCEL"
    assert fees[0]["amount_cents"] == 2500, (
        f"base 1500 + tier2 surcharge 1000 = 2500, got {fees[0]['amount_cents']}")


def test_late_cancel_zero_surcharge_at_prior_strikes_one(api):
    """PRD §3.8: "A surcharge is then added according to the strike count observed before
    incrementing for this event: when the prior strike count is at most 1, the surcharge
    is 0 cents".
    PRD §3.8: "At the boundaries, a prior count of exactly 1 lands in the zero-surcharge
    tier, and a prior count of exactly 2 lands in the 1000-cent tier."

    Design: Difficulty/combinatorial_formula/late_fee_tiered_surcharge_three_inputs
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "30 Pack", "price_cents": 9000,
                                        "grant_credits": 30, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # Build prior strikes == 1 via one NO_SHOW.
    drive_member_to_strikes(net, member, membership, 1, base_clock="2026-06-01T00:00:00Z")
    assert get_member(member["id"])["no_show_strikes"] == 1

    set_clock("2026-06-05T00:00:00Z")
    s = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-05T10:00:00Z", seat_capacity=1)
    r = reserve(s["id"], member["id"], membership["id"])
    cancelled = validate_success(api.cancel_reservation(r["id"], make_member_headers(member["id"])), 200)
    assert cancelled["attendance_status"] == "LATE_CANCELLED"

    fees = _fees_for_reservation(api, r["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "LATE_CANCEL"
    # prior_strikes == 1 -> surcharge 0 -> base 1500 only.
    assert fees[0]["amount_cents"] == 1500, (
        f"prior_strikes 1 lands in the zero-surcharge tier -> 1500, got {fees[0]['amount_cents']}")


def test_no_show_chain_fee_strike_then_restricted_standing(api):
    """PRD §3.7: "For each new no-show a `NO_SHOW` `FeeCharge` is assessed (see below),
    the seat credit is *not* refunded, the member's strike count is incremented, and
    their `standing` is recomputed."
    PRD §3.7: "The member's `standing` is `RESTRICTED` when `no_show_strikes` is at least
    3, and `GOOD` otherwise; thus 2 strikes still leaves a member `GOOD` while 3 makes
    them `RESTRICTED`, and a `RESTRICTED` member cannot create reservations."

    Design: Difficulty/transitive_cascade/no_show_fee_strike_standing_chain
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "30 Pack", "price_cents": 9000,
                                        "grant_credits": 30, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    drive_member_to_strikes(net, member, membership, 2, base_clock="2026-06-01T00:00:00Z")
    assert get_member(member["id"])["no_show_strikes"] == 2

    # Third no-show drives strikes 2 -> 3 and flips standing to RESTRICTED.
    set_clock("2026-06-05T00:00:00Z")
    s3 = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-05T10:00:00Z", seat_capacity=1)
    r3 = reserve(s3["id"], member["id"], membership["id"])
    set_clock("2026-06-05T11:30:00Z")
    validate_success(api.run_completion(ADMIN), 200)

    res = validate_success(api.get_reservation(r3["id"], ADMIN), 200)
    assert res["attendance_status"] == "NO_SHOW"
    fees = _fees_for_reservation(api, r3["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "NO_SHOW" and fees[0]["status"] == "ASSESSED"
    after = get_member(member["id"])
    assert after["no_show_strikes"] == 3, f"expected 3 strikes, got {after['no_show_strikes']}"
    assert after["standing"] == "RESTRICTED"


def test_no_show_keeps_seat_credit_and_flags_not_refunded(api):
    """PRD §3.7: "For each new no-show a `NO_SHOW` `FeeCharge` is assessed (see below),
    the seat credit is *not* refunded, the member's strike count is incremented, and
    their `standing` is recomputed."
    PRD §3.8: "The `credit_refunded` flag is true exactly when the seat credit was
    refunded as part of the event that produced the fee — true for a late cancel (the
    credit is returned), false for a no-show (the credit is kept)."

    Design: Difficulty/transitive_cascade/no_show_fee_strike_standing_chain
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=1)
    r = reserve(session["id"], member["id"], membership["id"])  # debits 5 -> balance 15
    set_clock("2026-06-10T11:30:00Z")
    validate_success(api.run_completion(ADMIN), 200)

    res = validate_success(api.get_reservation(r["id"], ADMIN), 200)
    assert res["attendance_status"] == "NO_SHOW"
    # Seat credit is kept: balance stays at 15 (the booking debit is not reversed).
    assert get_membership(membership["id"], member["id"])["credit_balance"] == 15
    fees = _fees_for_reservation(api, r["id"])
    assert len(fees) == 1 and fees[0]["kind"] == "NO_SHOW"
    assert fees[0]["credit_refunded"] is False, "a no-show fee must flag credit_refunded false"


def test_strike_conservation_no_show_then_waive(api):
    """PRD §3.8: "A `StudioManager` (or the `NetworkAdmin`) may waive an `ASSESSED` fee,
    moving it `ASSESSED → WAIVED`. Waiving zeroes the member's effective liability for
    that fee and reverses the strike the originating event added: the member's
    `no_show_strikes` is decremented by one, floored at zero, and their `standing` is
    recomputed."

    Design: Difficulty/compensating_invariant/strike_conservation_no_show_then_fee_waive
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=1)
    r1 = reserve(session["id"], member["id"], membership["id"])
    set_clock("2026-06-10T11:30:00Z")
    validate_success(api.run_completion(ADMIN), 200)

    assert get_member(member["id"])["no_show_strikes"] == 1
    fees = _fees_for_reservation(api, r1["id"])
    assert len(fees) == 1
    fee_id = fees[0]["id"]

    waived = validate_success(api.waive_fee(fee_id, TEST_USERS["studio_manager_headers"]), 200)
    assert waived["status"] == "WAIVED"
    after = get_member(member["id"])
    assert after["no_show_strikes"] == 0, f"waive must restore to 0, got {after['no_show_strikes']}"
    assert after["standing"] == "GOOD"


def test_strike_conservation_forward_no_show_increments_strike(api):
    """PRD §3.7: "For each new no-show a `NO_SHOW` `FeeCharge` is assessed (see below),
    the seat credit is *not* refunded, the member's strike count is incremented, and
    their `standing` is recomputed."
    PRD §3.7: "A member's `no_show_strikes` is the count of that member's `FeeCharge`
    rows whose `status` is `ASSESSED` and whose `created_at` falls within the trailing 30
    days".

    Design: Difficulty/compensating_invariant/strike_conservation_no_show_then_fee_waive
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=1)
    reserve(session["id"], member["id"], membership["id"])
    set_clock("2026-06-10T11:30:00Z")
    validate_success(api.run_completion(ADMIN), 200)

    # Forward half of the conservation: the single NO_SHOW raised strikes to exactly 1,
    # standing stays GOOD (1 < 3), and the fee is ASSESSED.
    after = get_member(member["id"])
    assert after["no_show_strikes"] == 1, f"forward NO_SHOW must raise strikes to 1, got {after['no_show_strikes']}"
    assert after["standing"] == "GOOD"


def test_intro_already_used_second_purchase_rejected(api):
    """PRD §3.2: "If the chosen plan is an `INTRO` plan whose `intro_once_per_member` is
    true and the member's `has_used_intro` is already true, the purchase is refused with
    `ERR_INTRO_ALREADY_USED`."
    PRD §3.2: "If the activated plan is an `INTRO` plan, the member's `has_used_intro` is
    set to true at activation."

    Design: Corner/validations/error_intro_already_used_second_intro
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="INTRO", plan_overrides={
        "name": "Intro", "price_cents": 2000, "grant_credits": 3, "validity_days": 14,
        "intro_once_per_member": True,
    })
    member, _ = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    assert get_member(member["id"])["has_used_intro"] is True

    res = api.create_membership(member["id"], {"plan_id": net["plan"]["id"]}, make_member_headers(member["id"]))
    validate_error(res, "ERR_INTRO_ALREADY_USED")


def test_freeze_not_allowed_on_credit_pack(api):
    """PRD §3.3: "A freeze is permitted only when the membership is `ACTIVE`, the
    underlying plan's `kind` is `MEMBERSHIP`, the plan's `freeze_max_days` is greater
    than 0, and the membership's `freeze_days_used` is still strictly below
    `freeze_max_days`; a request that violates any of these is refused with
    `ERR_FREEZE_NOT_ALLOWED`."

    Design: Corner/validations/error_freeze_not_allowed_on_credit_pack
    """
    net = setup_network(plan_kind="CREDIT_PACK", plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 60,
    })
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    res = api.freeze_membership(
        membership["id"], {"expected_membership_version": membership["version"]},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_FREEZE_NOT_ALLOWED")
