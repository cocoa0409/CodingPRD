"""Economic impact reporting, settlement accounting, and optimistic concurrency."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_event, create_bid, create_bid_payload, create_verified_bid,
    award_event_bid, create_contracted_venue, create_hotel_block,
    create_booking, reconcile_block, set_clock, get_event,
    setup_completed_event, setup_accepted_impact_report, setup_approved_settlement,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
CVB = TEST_USERS["cvb_headers"]
ANY = TEST_USERS["any_headers"]


def _get_settlement(api, settlement_id):
    return get_success_data(api.get_settlement(settlement_id, ANY))


def _get_block(api, block_id):
    return get_success_data(api.get_hotel_block(block_id, ANY))


# ===========================================================================
# Queue A: dual_variant_calc / impact_spend_projected_vs_audited
# ===========================================================================

def _setup_completed_event_with_bookings():
    """COMPLETED event after a played final; B1 (18 rooms x 4 nights = 72)
    CHECKED_OUT and B2 (1 room x 4 nights = 4) still CONFIRMED at submit time.

    The block is NOT reconciled here (reconcile is not needed for the report).
    Returns (ctx, report_id)."""
    from test_helpers import api_client as _api
    from test_helpers import (
        setup_event_in_registration_open, make_team_eligible,
        list_division_matches, advance_posture,
    )
    ctx = setup_event_in_registration_open()
    ev_id = ctx["event"]["id"]
    block_id = ctx["block"]["id"]
    b1 = create_booking(block_id, rooms_count=18, guest_name="Block A")
    b2 = create_booking(block_id, rooms_count=1, guest_name="Block B")
    validate_success(_api.transition_booking(b1["id"], {"action": "CONFIRM"}, ADMIN))
    validate_success(_api.transition_booking(b2["id"], {"action": "CONFIRM"}, ADMIN))
    set_clock("2026-10-09T00:00:00Z")
    validate_success(_api.transition_booking(b1["id"], {"action": "CHECK_IN"}, ADMIN))
    validate_success(_api.transition_booking(b1["id"], {"action": "CHECK_OUT"}, ADMIN))
    # Play the division final so the posture can complete.
    from test_helpers import make_team_eligible as _mk
    _mk(ctx["division"]["id"], name="Tigers", contact_email="t@x.com", strength_rating=90)
    _mk(ctx["division"]["id"], name="Sharks", contact_email="s@x.com", strength_rating=70)
    validate_success(_api.lock_seeding(ctx["division"]["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    validate_success(_api.publish_bracket(ctx["division"]["id"], ADMIN))
    final = list_division_matches(ctx["division"]["id"])[0]
    advance_posture(ev_id, "LIVE")
    validate_success(_api.schedule_match(final["id"], {"field_id": ctx["field"]["id"],
                                                       "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(_api.start_match(final["id"], ADMIN))
    validate_success(_api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    advance_posture(ev_id, "COMPLETED")
    report = get_success_data(_api.create_impact_report(
        ev_id, {"projected_attendance": 400},
        {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    submitted = validate_success(_api.submit_impact_report(report["id"], ADMIN))
    return ctx, submitted


def test_impact_spend_projected_vs_audited(api):
    """PRD §3.9: "Submitting the report snapshots the projected variant of the
    direct-spend calculation. `projected_room_nights` becomes the sum of
    `room_nights` over the event's bookings in `RESERVED`, `CONFIRMED`,
    `CHECKED_IN`, `CHECKED_OUT`, or `NO_SHOW` status, and
    `projected_direct_spend_cents` becomes the sum of those bookings'
    `total_charge_cents` plus 14,500 cents — that is, $145.00 of per-capita
    spending — for every projected attendee. No intermediate rounding applies;
    everything is integer cents."
    PRD §3.9: "`actual_room_nights` sums `room_nights` over only the event's
    `CHECKED_OUT` and `NO_SHOW` bookings, and `audited_direct_spend_cents` (also
    null until audit) sums those bookings' `total_charge_cents` plus the same
    14,500 cents per actual attendee. Identical event data therefore produces a
    different audited total than the projected one, because the booking set and
    the attendance figure both change."

    Design: Difficulty/dual_variant_calc/impact_spend_projected_vs_audited
    """
    ctx, submitted = _setup_completed_event_with_bookings()
    # Projected variant: 72 (CHECKED_OUT) + 4 (CONFIRMED) = 76 room-nights;
    # charges 1080000 + 60000 = 1140000; plus 400 x 14500 = 5800000.
    assert submitted["projected_room_nights"] == 76
    assert submitted["projected_direct_spend_cents"] == 6940000
    audited = validate_success(api.audit_impact_report(
        submitted["id"], {"actual_attendance": 350}, CVB))
    # Audited variant: only CHECKED_OUT/NO_SHOW -> 72 nights, 1080000 charges;
    # plus 350 x 14500 = 5075000.
    assert audited["actual_room_nights"] == 72
    assert audited["audited_direct_spend_cents"] == 6155000
    assert submitted["projected_direct_spend_cents"] != audited["audited_direct_spend_cents"]


def test_impact_report_projected_snapshot_uses_submitter_attendance(api):
    """PRD §3.9: "`projected_direct_spend_cents` becomes the sum of those
    bookings' `total_charge_cents` plus 14,500 cents — that is, $145.00 of
    per-capita spending — for every projected attendee."

    Design: Difficulty/dual_variant_calc/impact_spend_projected_vs_audited
    """
    ctx, submitted = _setup_completed_event_with_bookings()
    # The projected snapshot is frozen at submit: 76 nights and 6940000 cents.
    reread = get_success_data(api.get_impact_report(submitted["id"], ANY))
    assert reread["projected_room_nights"] == 76
    assert reread["projected_direct_spend_cents"] == 6940000
    assert reread["status"] == "SUBMITTED"


# ===========================================================================
# Queue A: combinatorial_formula / official_stipend_per_assignment_rounding
# ===========================================================================

def _setup_completed_event_with_worked_trainees():
    """COMPLETED event; two TRAINEE officials hold WORKED ASSISTANT assignments
    on the played final; block reconciled; settlement created. Returns ctx."""
    from test_helpers import api_client as _api
    from test_helpers import (
        setup_published_bracket, create_active_official,
        propose_and_accept_assignment, reconcile_block, advance_posture,
    )
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    final = ctx["matches"][-1]
    validate_success(_api.schedule_match(
        final["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    o1 = create_active_official(ctx["event"]["id"], name="Ora One",
                                certification_level="TRAINEE")
    o2 = create_active_official(ctx["event"]["id"], name="Otto Two",
                                certification_level="TRAINEE")
    a1 = propose_and_accept_assignment(final["id"], o1["id"], slot_role="ASSISTANT")
    a2 = propose_and_accept_assignment(final["id"], o2["id"], slot_role="ASSISTANT")
    validate_success(_api.start_match(final["id"], ADMIN))
    validate_success(_api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    validate_success(_api.complete_assignment(a1["id"], ADMIN))
    validate_success(_api.complete_assignment(a2["id"], ADMIN))
    advance_posture(ctx["event"]["id"], "COMPLETED")
    ctx["event"] = get_event(ctx["event"]["id"])
    ctx["block"] = reconcile_block(ctx["block"]["id"])
    settlement = get_success_data(_api.create_settlement(
        ctx["event"]["id"], {"sponsor_contributions_cents": 0}, ADMIN))
    ctx["settlement"] = settlement
    return ctx


def test_official_stipend_per_assignment_rounding(api):
    """PRD §3.9: "`officials_stipend_total_cents`: the sum over the event's
    `WORKED` assignments of a per-assignment stipend — 9,999 cents ($99.99)
    multiplied by the official's certification multiplier, 0.6 for `TRAINEE`,
    1.0 for `REGIONAL`, and 1.5 for `NATIONAL` — with each assignment's stipend
    rounded half up to whole cents before summation. Summing the raw products
    and rounding once yields a different total and is non-conformant."

    Design: Difficulty/combinatorial_formula/official_stipend_per_assignment_rounding
    """
    from test_helpers import api_client as _api
    ctx = _setup_completed_event_with_worked_trainees()
    certified = validate_success(_api.certify_settlement(
        ctx["settlement"]["id"],
        {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    # round_half_up(9999 * 0.6) = 5999 per assignment; 2 x 5999 = 11998.
    # Sum-then-round would yield 11999 and is non-conformant.
    assert certified["officials_stipend_total_cents"] == 11998


def test_official_stipend_levels_scale_per_assignment(api):
    """PRD §3.9: "`officials_stipend_total_cents`: the sum over the event's
    `WORKED` assignments of a per-assignment stipend — 9,999 cents ($99.99)
    multiplied by the official's certification multiplier, 0.6 for `TRAINEE`,
    1.0 for `REGIONAL`, and 1.5 for `NATIONAL` — with each assignment's stipend
    rounded half up to whole cents before summation. Summing the raw products
    and rounding once yields a different total and is non-conformant."

    Design: Difficulty/combinatorial_formula/official_stipend_per_assignment_rounding
    """
    from test_helpers import api_client as _api
    from test_helpers import (
        setup_published_bracket, create_active_official,
        propose_and_accept_assignment, reconcile_block, advance_posture,
    )
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    final = ctx["matches"][-1]
    validate_success(_api.schedule_match(
        final["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    # One NATIONAL CREW_CHIEF (final round requires NATIONAL) and one REGIONAL
    # ASSISTANT, both WORKED.
    o1 = create_active_official(ctx["event"]["id"], name="Nat Ref",
                                certification_level="NATIONAL")
    o2 = create_active_official(ctx["event"]["id"], name="Reg Ref",
                                certification_level="REGIONAL")
    a1 = propose_and_accept_assignment(final["id"], o1["id"], slot_role="CREW_CHIEF")
    a2 = propose_and_accept_assignment(final["id"], o2["id"], slot_role="ASSISTANT")
    validate_success(_api.start_match(final["id"], ADMIN))
    validate_success(_api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    validate_success(_api.complete_assignment(a1["id"], ADMIN))
    validate_success(_api.complete_assignment(a2["id"], ADMIN))
    advance_posture(ctx["event"]["id"], "COMPLETED")
    ctx["event"] = get_event(ctx["event"]["id"])
    ctx["block"] = reconcile_block(ctx["block"]["id"])
    settlement = get_success_data(_api.create_settlement(
        ctx["event"]["id"], {"sponsor_contributions_cents": 0}, ADMIN))
    certified = validate_success(_api.certify_settlement(
        settlement["id"], {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    # round(9999*1.5) + round(9999*1.0) = 14999 + 9999 = 24998 (14998.5 halves up).
    assert certified["officials_stipend_total_cents"] == 24998


# ===========================================================================
# Queue A: transitive_cascade / settlement_pay_event_block_cascade
# ===========================================================================

def test_settlement_pay_event_block_cascade(api):
    """PRD §3.9: "Payment then moves `APPROVED` → `PAID` and fires the closing
    cascade of §2.5: the event moves `COMPLETED` → `SETTLED`, and every hotel
    block still `RECONCILED` becomes `SETTLED` with its `final_rebate_cents` and
    `attrition_penalty_cents` frozen."
    PRD §2.5: "`COMPLETED` → `SETTLED` is not manual: it happens automatically
    when the event's settlement is paid (see §3.9), and it requires an impact
    report of the event to be `ACCEPTED`. Its cascade moves every hotel block in
    `RECONCILED` to `SETTLED` (each block's `version` increments by one, with
    `final_rebate_cents` and `attrition_penalty_cents` frozen)."

    Design: Difficulty/transitive_cascade/settlement_pay_event_block_cascade
    """
    from test_helpers import api_client as _api
    ctx = _setup_approved_settlement_with_rebate()
    paid = validate_success(_api.pay_settlement(ctx["settlement"]["id"], ADMIN))
    assert paid["status"] == "PAID"
    # hop 1: pay -> event posture
    assert get_event(ctx["event"]["id"])["posture"] == "SETTLED"
    # hop 2: event SETTLED -> reconciled blocks become SETTLED, figures frozen.
    block = _get_block(api, ctx["block"]["id"])
    assert block["status"] == "SETTLED"
    assert block["final_rebate_cents"] == 108000


def test_settlement_pay_freezes_block_rebate(api):
    """PRD §2.5: "`COMPLETED` → `SETTLED` is not manual: it happens
    automatically when the event's settlement is paid (see §3.9), and it
    requires an impact report of the event to be `ACCEPTED`. Its cascade moves
    every hotel block in `RECONCILED` to `SETTLED` (each block's `version`
    increments by one, with `final_rebate_cents` and `attrition_penalty_cents`
    frozen)."

    Design: Difficulty/transitive_cascade/settlement_pay_event_block_cascade
    """
    from test_helpers import api_client as _api
    ctx = _setup_approved_settlement_with_rebate()
    before = _get_block(api, ctx["block"]["id"])
    assert before["status"] == "RECONCILED"
    paid = validate_success(_api.pay_settlement(ctx["settlement"]["id"], ADMIN))
    assert paid["status"] == "PAID"
    after = _get_block(api, ctx["block"]["id"])
    assert after["status"] == "SETTLED"
    assert after["final_rebate_cents"] == before["final_rebate_cents"] == 108000
    assert after["attrition_penalty_cents"] == before["attrition_penalty_cents"] == 0
    assert after["version"] == before["version"] + 1


def _setup_approved_settlement_with_rebate():
    """COMPLETED event; a block with a 72-night CHECKED_OUT booking reconciled
    (final rebate 108000); ACCEPTED impact report; settlement certified by
    ops-admin-1 and approved by ops-admin-2."""
    from test_helpers import api_client as _api
    from test_helpers import (
        setup_event_in_registration_open, list_division_matches,
        advance_posture, create_booking,
    )
    ctx = setup_event_in_registration_open()
    ev_id = ctx["event"]["id"]
    block_id = ctx["block"]["id"]
    create_booking(block_id, rooms_count=18, guest_name="Block A", check_in_out=True)
    # Play the final.
    from test_helpers import make_team_eligible as _mk
    _mk(ctx["division"]["id"], name="Tigers", contact_email="t@x.com", strength_rating=90)
    _mk(ctx["division"]["id"], name="Sharks", contact_email="s@x.com", strength_rating=70)
    validate_success(_api.lock_seeding(ctx["division"]["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    validate_success(_api.publish_bracket(ctx["division"]["id"], ADMIN))
    final = list_division_matches(ctx["division"]["id"])[0]
    advance_posture(ev_id, "LIVE")
    validate_success(_api.schedule_match(final["id"], {"field_id": ctx["field"]["id"],
                                                       "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(_api.start_match(final["id"], ADMIN))
    validate_success(_api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    advance_posture(ev_id, "COMPLETED")
    ctx["event"] = get_event(ev_id)
    ctx["block"] = reconcile_block(block_id)
    assert ctx["block"]["final_rebate_cents"] == 108000
    # ACCEPTED impact report and an SoD-clean certified+approved settlement.
    report = setup_accepted_impact_report(ctx)
    settlement = get_success_data(_api.create_settlement(
        ev_id, {"sponsor_contributions_cents": 500000}, ADMIN))
    certified = validate_success(_api.certify_settlement(
        settlement["id"], {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    approved = validate_success(_api.approve_settlement(
        certified["id"], {"X-User-ID": "ops-admin-2", "X-User-Role": "CommissionAdmin"}))
    ctx["settlement"] = approved
    ctx["report"] = report
    return ctx


# ===========================================================================
# Corner / calculations (sanction fee tier boundary + fee-paid filter)
# ===========================================================================

def test_sanction_fee_tier1_boundary_and_fee_paid_filter(api):
    """PRD §3.9: "`registration_revenue_cents`: the sum, over every team of the
    event in a fee-paid status — `ROSTER_SUBMITTED`, `ELIGIBLE`, `CHECKED_IN`,
    `ELIMINATED`, `FINISHED`, `CHAMPION`, or `DISQUALIFIED` — of that team's
    division's `registration_fee_cents`. `ENTERED`, `WAITLISTED`, and
    `WITHDRAWN` teams are excluded, their fee not yet due or refunded."
    PRD §3.9: "`sanction_fee_cents`: the sanctioning body's marginal tiered fee
    on `registration_revenue_cents` — the first 5,000,000 cents ($50,000) at 8%,
    the next 5,000,000 cents (the portion from 5,000,001 through 10,000,000
    cents) at 10%, and any remainder above 10,000,000 cents ($100,000) at 12%.
    Each tier's slice is rounded half up to whole cents first and the rounded
    slices are then summed; rounding once on the total is non-conformant."
    PRD §3.9: "`venue_rental_total_cents`: the sum of `rental_fee_cents` over
    the event's `CONTRACTED` and `RELEASED` venues."
    PRD §3.9: "`net_to_commission_cents`: the waterfall remainder. Deductions
    apply in a strict bucket order — the sanction fee first, then venue rental,
    then officials' stipends, then the expense total — each bucket fully
    satisfied before the next, and the remainder after all four deductions is
    the net. The net may be negative, in which case it represents a receivable:
    the commission owes the difference."

    Design: Corner/calculations/sanction_fee_tier1_boundary_and_fee_paid_filter
    """
    from test_helpers import api_client as _api
    from test_helpers import (
        setup_event_in_registration_open, create_division,
        make_team_eligible, list_division_matches, advance_posture,
    )
    ctx = setup_event_in_registration_open(
        division_overrides={"name": "U16", "team_cap": 4, "min_teams": 2,
                            "registration_fee_cents": 2500000})
    ev_id = ctx["event"]["id"]
    d1 = ctx["division"]
    # D2 below min_teams (only 1 eligible): auto-cancelled at COMPETITION_SETUP
    # and its team withdrawn, so its 999999-cent fee leaves the revenue base.
    d2 = create_division(ev_id, name="U18", team_cap=4, min_teams=2,
                         registration_fee_cents=999999)
    make_team_eligible(d1["id"], name="Tigers", contact_email="t@x.com", strength_rating=90)
    make_team_eligible(d1["id"], name="Sharks", contact_email="s@x.com", strength_rating=70)
    make_team_eligible(d2["id"], name="Wolves", contact_email="w@x.com", strength_rating=85)
    validate_success(_api.lock_seeding(d1["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    validate_success(_api.publish_bracket(d1["id"], ADMIN))
    final = list_division_matches(d1["id"])[0]
    advance_posture(ev_id, "LIVE")
    validate_success(_api.schedule_match(final["id"], {"field_id": ctx["field"]["id"],
                                                       "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(_api.start_match(final["id"], ADMIN))
    validate_success(_api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    advance_posture(ev_id, "COMPLETED")
    ctx["event"] = get_event(ev_id)
    ctx["block"] = reconcile_block(ctx["block"]["id"])
    settlement = get_success_data(_api.create_settlement(
        ev_id, {"sponsor_contributions_cents": 0}, ADMIN))
    certified = validate_success(_api.certify_settlement(
        settlement["id"], {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    # Two fee-paid teams (CHAMPION + FINISHED) x 2500000 = exactly TIER1_CAP.
    assert certified["registration_revenue_cents"] == 5000000
    # Exactly at the cap: tier1 slice 5000000 x 0.08 = 400000; tier2 slice 0.
    assert certified["sanction_fee_cents"] == 400000
    assert certified["venue_rental_total_cents"] == 200000
    # Waterfall: 5000000 - 400000 - 200000 - 0 stipends - 0 expenses.
    assert certified["net_to_commission_cents"] == 4400000


# ===========================================================================
# Corner / validations (settlement SoD + uniqueness)
# ===========================================================================

def test_settlement_sod_and_uniqueness_rejected(api):
    """PRD §2.11: "And the administrator approving a settlement must not be the
    administrator who certified it: the approver's `X-User-ID` must differ from
    the settlement's `certified_by_user_id`."
    PRD §3.9: "Settlement is the final accounting, and an event has at most one:
    creating a second settlement for the same event is rejected with
    `ERR_SETTLEMENT_EXISTS` (HTTP 409), and creating the first requires
    `COMPLETED` posture."

    Design: Corner/validations/settlement_sod_and_uniqueness_rejected
    """
    from test_helpers import api_client as _api
    ctx = setup_completed_event(with_settlement=True)
    setup_accepted_impact_report(ctx, projected_attendance=100, actual_attendance=90)
    certifier = {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}
    settlement = validate_success(_api.certify_settlement(ctx["settlement"]["id"], certifier))
    # Approve by the certifier breaches SoD.
    resp = api.approve_settlement(settlement["id"], certifier)
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    # A second settlement for the same event is rejected.
    resp = api.create_settlement(ctx["event"]["id"], {"sponsor_contributions_cents": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXISTS)
    assert _get_settlement(api, settlement["id"])["status"] == "EXPENSES_CERTIFIED"


# ===========================================================================
# Corner / cross_cutting_layers (OCC on the four guarded write paths)
# ===========================================================================

def test_occ_bid_create_stale_version_rejected(api):
    """PRD §2.8: "`POST /api/v1/events/{id}/bids` — creating a bid on an event
    requires `expected_event_version` matching the event's current `version`.
    Bid creation legitimately supersedes an existing draft bid and can revive a
    lost or settled event, so a writer holding a stale event view must restart
    from a fresh read."
    PRD §2.8: "In each case, if the supplied value does not equal the parent
    entity's current `version` — because another write has advanced that version
    since the client last read the entity — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no change is applied."

    Design: Corner/cross_cutting_layers/occ_bid_create_stale_version_rejected
    """
    ev = create_event()
    b1 = create_bid(ev["id"])  # event version now 2
    # Replaying the originally observed version (1) is stale.
    resp = api.create_bid(ev["id"], create_bid_payload(ev["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    ev_after = get_event(ev["id"])
    assert ev_after["version"] == 2
    assert get_success_data(api.get_bid(b1["id"], ANY))["status"] == "DRAFT"


def test_occ_bid_patch_stale_version_rejected(api):
    """PRD §2.8: "`PATCH /api/v1/bids/{id}` — editing a bid's notes requires
    `expected_bid_version` matching the bid's current `version`, because
    requirement verifications and reviewer actions mutate the bid's review
    surface between reads."
    PRD §2.8: "In each case, if the supplied value does not equal the parent
    entity's current `version` — because another write has advanced that version
    since the client last read the entity — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no change is applied."

    Design: Corner/cross_cutting_layers/occ_bid_patch_stale_version_rejected
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    assert bid["version"] == 1
    patched = validate_success(api.patch_bid(
        bid["id"], {"expected_bid_version": bid["version"], "notes": "v2 notes"}, ADMIN))
    assert patched["version"] == 2
    # Replaying the same observed version is stale.
    resp = api.patch_bid(bid["id"], {"expected_bid_version": bid["version"],
                                     "notes": "stale replay"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_success_data(api.get_bid(bid["id"], ANY))["notes"] == "v2 notes"


def test_occ_hotel_block_patch_stale_rejected(api):
    """PRD §2.8: "`PATCH /api/v1/hotel-blocks/{id}` — editing a negotiating
    hotel block's terms requires `expected_hotel_block_version` matching the
    block's current `version`; bookings pin their rate from the block, so
    repricing from a stale view would corrupt already-quoted offers."
    PRD §2.8: "In each case, if the supplied value does not equal the parent
    entity's current `version` — because another write has advanced that version
    since the client last read the entity — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no change is applied."

    Design: Corner/cross_cutting_layers/occ_hotel_block_patch_stale_rejected
    """
    ev = create_event()
    block = create_hotel_block(ev["id"], contracted=False)  # NEGOTIATING, v1
    assert block["version"] == 1
    patched = validate_success(api.patch_hotel_block(
        block["id"], {"expected_hotel_block_version": block["version"],
                      "room_rate_cents": 16000}, ADMIN))
    assert patched["room_rate_cents"] == 16000
    assert patched["version"] == 2
    resp = api.patch_hotel_block(
        block["id"], {"expected_hotel_block_version": block["version"],
                      "room_rate_cents": 17000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert _get_block(api, block["id"])["room_rate_cents"] == 16000


def test_occ_posture_advance_stale_rejected(api):
    """PRD §2.8: "`POST /api/v1/events/{id}/posture` — advancing an event's
    posture requires `expected_event_version` matching the event's current
    `version`, because posture transitions fire multi-entity cascades whose
    preconditions were evaluated against the version the client observed."
    PRD §2.8: "In each case, if the supplied value does not equal the parent
    entity's current `version` — because another write has advanced that version
    since the client last read the entity — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no change is applied."

    Design: Corner/cross_cutting_layers/occ_posture_advance_stale_rejected
    """
    ev = create_event()
    award_event_bid(ev["id"])
    create_contracted_venue(ev["id"])
    create_hotel_block(ev["id"], contracted=True)
    observed = get_event(ev["id"])["version"]
    advanced = validate_success(api.advance_posture(
        ev["id"], {"to_posture": "PLANNING", "expected_event_version": observed}, ADMIN))
    assert advanced["posture"] == "PLANNING"
    assert advanced["version"] == observed + 1
    # Replaying the stale observed version fails before any posture logic runs.
    resp = api.advance_posture(
        ev["id"], {"to_posture": "REGISTRATION_OPEN", "expected_event_version": observed}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_event(ev["id"])["posture"] == "PLANNING"
