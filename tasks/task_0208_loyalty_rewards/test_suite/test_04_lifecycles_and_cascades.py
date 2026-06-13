"""State machine lifecycles and transitive cascades.

Covers referral branching (complete / revoke / expire), the depth-3 purchase ->
referral-complete -> dual mint cascade, birthday grants, expiration sweeps,
promotion lifecycle, partner pause/resume, and member creation defaults.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_error,
    validate_paginated,
    set_clock,
    setup_program,
    register_member,
    post_purchase,
    get_member,
    add_partner,
    create_referral,
    setup_pending_referral,
    setup_referral_with_registered_referee,
    create_promotion_payload,
    ApiErrorId,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Transitive cascade depth-3: purchase completes referral, mints two lots
# ---------------------------------------------------------------------------
def test_purchase_completes_referral_mints_both_members(api):
    """PRD 3.6: "On completion the platform mints a `REFERRAL` `PointsLot` of the program's `referral_referrer_points` to the referrer and appends a `REFERRAL` `PointsTransaction` for them; mints a `REFERRAL` `PointsLot` of the program's `referral_referee_points` to the referee and appends a `REFERRAL` `PointsTransaction` for them; sets the referral's `completed_at` to the current clock time; recomputes balances for both members; and moves the referral to the terminal `COMPLETED` status."

    The referee's qualifying purchase of 10000c (== referral_min_qualifying_cents)
    completes the referral: referrer gains 500, referee gains 250 referral points
    plus 100 earned = 350.

    Design: Difficulty/transitive_cascade/purchase_completes_referral_mints_two_lots_recomputes_balances_depth3
    """
    s = setup_referral_with_registered_referee()
    referrer, referee, referral = s["referrer"], s["referee"], s["referral"]
    post_purchase(referee["id"], 10000)

    ref_after = get_success_data(api.get_referral(referral["id"], ADMIN))
    assert ref_after["status"] == "COMPLETED", f"Expected COMPLETED, got {ref_after['status']}"
    referrer = get_member(referrer["id"])
    referee = get_member(referee["id"])
    assert referrer["available_points"] == 500, \
        f"Expected referrer 500, got {referrer['available_points']}"
    assert referee["available_points"] == 350, \
        f"Expected referee 350 (250 referral + 100 earned), got {referee['available_points']}"


def test_referral_completion_sets_completed_at(api):
    """PRD 3.6: "sets the referral's `completed_at` to the current clock time; recomputes balances for both members; and moves the referral to the terminal `COMPLETED` status."

    On completion the referral's completed_at is populated (no longer null).

    Design: Difficulty/transitive_cascade/purchase_completes_referral_mints_two_lots_recomputes_balances_depth3
    """
    s = setup_referral_with_registered_referee()
    referee, referral = s["referee"], s["referral"]
    post_purchase(referee["id"], 10000)
    ref_after = get_success_data(api.get_referral(referral["id"], ADMIN))
    assert ref_after["status"] == "COMPLETED"
    assert ref_after.get("completed_at"), "completed_at must be set on completion"


# ---------------------------------------------------------------------------
# Referral branching: PENDING -> REVOKED grants nothing
# ---------------------------------------------------------------------------
def test_referral_revoke_grants_nothing(api):
    """PRD 3.6: "A `ProgramAdmin` may revoke a still-`PENDING` referral, moving it to `REVOKED`, again with no points granted and no ledger change."

    Revoking a PENDING referral moves it to REVOKED and the referrer's
    available_points remains 0.

    Design: Difficulty/non_linear_state_machine/referral_branches_pending_to_completed_or_revoked
    """
    s = setup_pending_referral()
    referrer, referral = s["referrer"], s["referral"]
    revoked = get_success_data(api.revoke_referral(referral["id"], ADMIN))
    assert revoked["status"] == "REVOKED", f"Expected REVOKED, got {revoked['status']}"
    referrer = get_member(referrer["id"])
    assert referrer["available_points"] == 0, \
        f"Expected 0, got {referrer['available_points']}"


def test_referral_expires_via_sweep_grants_nothing(api):
    """PRD 3.6: "A pending referral that has aged beyond the program's `lot_expiration_months` since its creation is moved to `EXPIRED` during an expiration sweep once the clock has reached or passed that point — no points are granted and no ledger entry is written."

    A referral created 2026-01-15 is EXPIRED by a sweep at 2027-02-01 (> 12 months)
    with the referrer's available_points still 0.

    Design: Difficulty/non_linear_state_machine/referral_branches_pending_to_completed_or_revoked
    """
    s = setup_pending_referral(clock="2026-01-15T00:00:00Z")
    prog, referrer, referral = s["program"], s["referrer"], s["referral"]
    set_clock("2027-02-01T00:00:00Z")
    get_success_data(api.sweep_expirations(prog["id"], ADMIN))
    ref_after = get_success_data(api.get_referral(referral["id"], ADMIN))
    assert ref_after["status"] == "EXPIRED", f"Expected EXPIRED, got {ref_after['status']}"
    referrer = get_member(referrer["id"])
    assert referrer["available_points"] == 0, \
        f"Expected 0, got {referrer['available_points']}"


def test_pending_referral_expired_by_sweep(api):
    """PRD 3.6: "A pending referral that has aged beyond the program's `lot_expiration_months` since its creation is moved to `EXPIRED` during an expiration sweep once the clock has reached or passed that point — no points are granted and no ledger entry is written."

    A referral created 2026-01-15 is moved to EXPIRED by sweep-expirations at
    2027-02-01 (more than the 12-month lot_expiration_months later).

    Design: Corner/state_machines/referral_expires_after_window_via_sweep
    """
    s = setup_pending_referral(clock="2026-01-15T00:00:00Z")
    prog, referrer, referral = s["program"], s["referrer"], s["referral"]
    set_clock("2027-02-01T00:00:00Z")
    get_success_data(api.sweep_expirations(prog["id"], ADMIN))
    ref_after = get_success_data(api.get_referral(referral["id"], ADMIN))
    assert ref_after["status"] == "EXPIRED", f"Expected EXPIRED, got {ref_after['status']}"
    referrer = get_member(referrer["id"])
    assert referrer["available_points"] == 0, \
        f"Expected 0 (no grant), got {referrer['available_points']}"


# ---------------------------------------------------------------------------
# Birthday grants
# ---------------------------------------------------------------------------
def test_birthday_grant_mints_lot_and_marks_year(api):
    """PRD 3.5: "A `ProgramAdmin` may grant a member their birthday reward, which mints a `BIRTHDAY` `PointsLot` of exactly the program's `birthday_reward_points`, appends a `BIRTHDAY` `PointsTransaction`, records the calendar year of the grant on the member's `last_birthday_grant_year`, recomputes the member's balances, and advances the member's `version` by one."

    On the member's birthday a grant mints a 200-point BIRTHDAY lot, sets
    last_birthday_grant_year to 2026, and available_points becomes 200.

    Design: Corner/state_machines/birthday_grant_mints_lot_and_marks_year
    """
    base = setup_program(clock="2026-03-10T00:00:00Z")
    member = register_member(base["program"]["id"], birth_month_day="03-10")
    resp = api.birthday_grant(member["id"], ADMIN)
    lot = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert lot["original_points"] == 200, f"Expected 200, got {lot['original_points']}"
    assert lot["source_type"] == "BIRTHDAY", f"Expected BIRTHDAY, got {lot['source_type']}"
    member = get_member(member["id"])
    assert member["available_points"] == 200, \
        f"Expected 200, got {member['available_points']}"
    assert member["last_birthday_grant_year"] == 2026, \
        f"Expected 2026, got {member['last_birthday_grant_year']}"


def test_birthday_grant_twice_same_year_rejected(api):
    """PRD 3.5: "it is allowed at most once per calendar year: a second grant in a year for which `last_birthday_grant_year` already records a grant is rejected with `ERR_BIRTHDAY_ALREADY_GRANTED` (HTTP 409)."

    Design: Corner/state_machines/birthday_grant_twice_same_year_returns_409
    """
    base = setup_program(clock="2026-03-10T00:00:00Z")
    member = register_member(base["program"]["id"], birth_month_day="03-10")
    get_success_data(api.birthday_grant(member["id"], ADMIN))
    resp = api.birthday_grant(member["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BIRTHDAY_ALREADY_GRANTED.value)


def test_birthday_grant_off_date_rejected(api):
    """PRD 3.5: "it is allowed only on the member's actual birthday: the month-day of the current clock time must equal the member's `birth_month_day`, and a grant requested on any other day is rejected with `ERR_NOT_BIRTHDAY` (HTTP 409)."

    Design: Corner/state_machines/birthday_grant_off_date_returns_409
    """
    base = setup_program(clock="2026-07-01T00:00:00Z")
    member = register_member(base["program"]["id"], birth_month_day="03-10")
    resp = api.birthday_grant(member["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_BIRTHDAY.value)


# ---------------------------------------------------------------------------
# Expiration sweep
# ---------------------------------------------------------------------------
def test_sweep_expires_past_lot_and_zeroes_balance(api):
    """PRD 3.9: "For each such lot it appends an `EXPIRE` `PointsTransaction` whose `points_delta` is the negative of the lot's `remaining_points`, sets that lot's `remaining_points` to 0, and moves the lot to the terminal `EXPIRED` status; after processing it recomputes the affected members' balances."

    A 600-point lot created 2026-01-15 is swept at 2027-02-01: it becomes EXPIRED
    with remaining_points 0, an EXPIRE transaction with delta -600 is written, and
    available_points drops to 0.

    Design: Corner/state_machines/expiration_sweep_expires_past_lot_zeroes_balance
    """
    base = setup_program(clock="2026-01-15T00:00:00Z")
    prog = base["program"]
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)
    set_clock("2027-02-01T00:00:00Z")
    get_success_data(api.sweep_expirations(prog["id"], ADMIN))

    member = get_member(member["id"])
    assert member["available_points"] == 0, \
        f"Expected 0 after sweep, got {member['available_points']}"
    lots, _ = validate_paginated(api.list_member_lots(member["id"], ADMIN))
    expired = [lot for lot in lots if lot["original_points"] == 600]
    assert expired and expired[0]["status"] == "EXPIRED", \
        f"Expected EXPIRED lot, got {expired[0]['status'] if expired else 'missing'}"
    assert expired[0]["remaining_points"] == 0
    txns, _ = validate_paginated(api.list_transactions(ADMIN, params={"member_id": member["id"]}))
    expire_rows = [t for t in txns if t["type"] == "EXPIRE"]
    assert any(t["points_delta"] == -600 for t in expire_rows), \
        "Expected an EXPIRE transaction with points_delta -600"


# ---------------------------------------------------------------------------
# Promotion lifecycle
# ---------------------------------------------------------------------------
def test_promotion_refresh_scheduled_active_then_ended(api):
    """PRD 3.10: "A refresh capability, run by a `ProgramAdmin`, moves a `SCHEDULED` promotion to `ACTIVE` once the clock is within its window (at or after `starts_at` and strictly before `ends_at`) and moves an `ACTIVE` promotion to the terminal `ENDED` status once the clock has reached or passed its `ends_at`."

    A promotion [2026-06-01, 2026-07-01) refreshed at 2026-06-10 becomes ACTIVE,
    then refreshed at 2026-07-02 becomes ENDED.

    Design: Corner/state_machines/promotion_refresh_scheduled_to_active_to_ended
    """
    base = setup_program()  # active program; promotions are program config
    prog = base["program"]
    promo = get_success_data(api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="DBL", bonus_multiplier=2.0,
                                 starts_at="2026-06-01T00:00:00Z",
                                 ends_at="2026-07-01T00:00:00Z", min_eligible_cents=0),
        ADMIN))
    set_clock("2026-06-10T00:00:00Z")
    get_success_data(api.refresh_promotions(prog["id"], ADMIN))
    set_clock("2026-07-02T00:00:00Z")
    get_success_data(api.refresh_promotions(prog["id"], ADMIN))

    promos, _ = validate_paginated(api.list_promotions(prog["id"], ADMIN))
    found = [p for p in promos if p["id"] == promo["id"]]
    assert found and found[0]["status"] == "ENDED", \
        f"Expected ENDED, got {found[0]['status'] if found else 'missing'}"


# ---------------------------------------------------------------------------
# Partner pause/resume round trip
# ---------------------------------------------------------------------------
def test_partner_pause_then_resume(api):
    """PRD 3.8: "An administrator may pause an `ACTIVE` partner (moving it to `PAUSED`, after which new transfers are refused with `ERR_PARTNER_PAUSED`) and resume a `PAUSED` partner back to `ACTIVE`."

    A partner paused then resumed reports the final ACTIVE status.

    Design: Corner/state_machines/partner_pause_then_resume_round_trip
    """
    base = setup_program()
    partner = add_partner(base["program"]["id"])
    get_success_data(api.pause_partner(partner["id"], ADMIN))
    resumed = get_success_data(api.resume_partner(partner["id"], ADMIN))
    assert resumed["status"] == "ACTIVE", f"Expected ACTIVE, got {resumed['status']}"


# ---------------------------------------------------------------------------
# Member creation defaults
# ---------------------------------------------------------------------------
def test_create_member_defaults(api):
    """PRD 3.2: "A new member starts in `ACTIVE` status, with `current_tier_code` resolved to `STANDARD`, a `last_birthday_grant_year` of null until the first birthday grant, and a `referred_by_member_id` of null when the registrant is organic."

    Creation returns 201 with a server-minted id, version 1, status ACTIVE, and
    current_tier_code STANDARD.

    Design: Corner/entities/create_member_returns_201_with_system_fields
    """
    base = setup_program()
    resp = api.create_member(
        {"program_id": base["program"]["id"], "email": "m@x.com",
         "full_name": "M", "birth_month_day": "03-10"}, ADMIN)
    member = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert member["status"] == "ACTIVE", f"Expected ACTIVE, got {member['status']}"
    assert member["current_tier_code"] == "STANDARD", \
        f"Expected STANDARD, got {member['current_tier_code']}"
    assert member["version"] == 1, f"Expected version 1, got {member['version']}"
