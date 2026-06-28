"""Boundary precision, activity scheduling overlap, visiting-day window, and
canteen conservation/overdraft.

Difficulty queue: boundary_precision_check, resource_temporal_overlap,
compensating_invariant. Corner queue: canteen is_low threshold, adjacent booking,
activity full, swim test, visiting day handled here and in errors/endpoints files.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_guardian_headers, make_director_headers,
    ApiErrorId,
    setup_enrolling_session, setup_enrolling_session_with_staffed_cabin,
    setup_submitted_application, setup_bunked_application,
    setup_canteen_with_balance, make_camp,
    make_activity, book_activity, open_canteen_account, canteen_txn,
    register_guardian, make_camper, make_health_form, submit_health_form,
    api_client,
)


# ===========================================================================
# Difficulty / boundary_precision_check
# ===========================================================================
def test_cabin_staffable_exactly_at_ratio_boundary_enroll_succeeds():
    """PRD §3.2: "otherwise the cabin is staffable exactly when its `staff_weight_x10`
    is greater than or equal to that required weight. The boundary is inclusive: a
    cabin whose weight exactly equals the requirement is staffable."
    PRD §3.6: "On success the enrollment moves to `ENROLLED`".

    Design: Difficulty/boundary_precision_check/cabin_staffable_exactly_at_ratio_boundary_enroll_succeeds
    """
    # 1 camper + 1 counselor: required_weight_x10 = ceil(1/6)*10 = 10; weight 10 == required 10
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        session_overrides={"capacity": 20},
        cabin_overrides={"bunk_capacity": 8},
        num_counselors=1,
    )
    gc = setup_bunked_application(env, deposit_cents=25_000, email="bd1@x.com", clear_health=True)
    director = make_director_headers()
    enrolled = validate_success(api_client.enroll_application(gc["application"]["id"], director))
    assert enrolled["enroll_status"] == "ENROLLED", enrolled["enroll_status"]

    cabin = validate_success(api_client.get_cabin(env["cabin"]["id"], director))
    assert cabin["is_staffable"] is True, cabin["is_staffable"]  # weight 10 >= required 10
    assert cabin["staff_weight_x10"] == 10, cabin["staff_weight_x10"]


def test_cabin_staffable_one_short_of_ratio_boundary_blocks_enroll():
    """PRD §3.2: "otherwise the cabin is staffable exactly when its `staff_weight_x10`
    is greater than or equal to that required weight. The boundary is inclusive: a
    cabin whose weight exactly equals the requirement is staffable."
    PRD §3.6: "the target cabin must be `is_staffable` true after counting this camper
    (otherwise `ERR_CABIN_UNDERSTAFFED`)".

    Design: Difficulty/boundary_precision_check/cabin_staffable_exactly_at_ratio_boundary_enroll_succeeds
    """
    # weight 5 (single CIT, half) is one band below the required 10 for 1 camper -> understaffed
    env = setup_enrolling_session(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6,
                        "cit_counts_as_half": True},
    )
    director = make_director_headers()
    cit = get_success_data(api_client.create_staff(
        env["camp"]["id"], {"full_name": "CIT", "role_kind": "CIT",
                            "is_background_cleared": True}, director))
    get_success_data(api_client.create_cabin_assignment(
        {"cabin_id": env["cabin"]["id"], "staff_member_id": cit["id"]}, director))
    gc = setup_bunked_application(env, deposit_cents=25_000, email="bd2@x.com", clear_health=True)
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_CABIN_UNDERSTAFFED.value)


def test_canteen_purchase_exactly_at_balance_allowed_overdraft_rejected():
    """PRD §3.9: "Overdrafts are forbidden: a purchase whose `amount_cents` exceeds
    the account's current `balance_cents` is rejected with
    `ERR_CANTEEN_INSUFFICIENT_FUNDS`. A purchase whose amount exactly equals the
    current balance is allowed."

    Design: Difficulty/boundary_precision_check/canteen_purchase_exactly_at_balance_allowed_overdraft_rejected
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "canteen_low_balance_cents": 1_000})
    gc = setup_canteen_with_balance(env, 5_000, email="cb1@x.com")
    g_id = gc["guardian"]["id"]
    acct_id = gc["account"]["id"]
    # X+1 (5001 > 5000) -> rejected
    resp = api_client.create_canteen_transaction(
        acct_id, {"kind": "PURCHASE", "amount_cents": 5_001}, make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_CANTEEN_INSUFFICIENT_FUNDS.value)


def test_canteen_purchase_exactly_at_balance_drives_to_zero():
    """PRD §3.9: "A purchase whose amount exactly equals the current balance is
    allowed."
    PRD §3.9: "The account's balance is derived: it is the sum of the `amount_cents`
    of all `APPLIED` canteen transactions of kind `DEPOSIT` minus the sum of the
    `amount_cents` of all `APPLIED` canteen transactions of kind `PURCHASE`."

    Design: Difficulty/boundary_precision_check/canteen_purchase_exactly_at_balance_allowed_overdraft_rejected
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "canteen_low_balance_cents": 1_000})
    gc = setup_canteen_with_balance(env, 5_000, email="cb2@x.com")
    g_id = gc["guardian"]["id"]
    acct_id = gc["account"]["id"]
    # X (5000 == 5000) -> allowed, balance -> 0
    get_success_data(api_client.create_canteen_transaction(
        acct_id, {"kind": "PURCHASE", "amount_cents": 5_000}, make_guardian_headers(g_id)))
    acct = validate_success(api_client.get_canteen_account(acct_id, make_guardian_headers(g_id)))
    assert acct["balance_cents"] == 0, acct["balance_cents"]


# ===========================================================================
# Difficulty / resource_temporal_overlap
# ===========================================================================
def test_activity_buffer_window_collision_rejected():
    """PRD §3.8: "the new offering's `starts_minute` must be at least the existing
    booking's `ends_minute` plus that existing offering's `setup_buffer_minutes`".
    PRD §3.8: "A booking is rejected if either the raw intervals overlap or the buffer
    window is violated on that slot day."

    Design: Difficulty/resource_temporal_overlap/activity_buffer_window_collision_on_offering_slot
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    archery = make_activity(env["session"]["id"], name="Archery", slot_day=1,
                            starts_minute=540, ends_minute=600, seat_capacity=10,
                            setup_buffer_minutes=15)
    swim = make_activity(env["session"]["id"], name="Swim", slot_day=1,
                         starts_minute=600, ends_minute=660, seat_capacity=10,
                         setup_buffer_minutes=0)
    gc = setup_submitted_application(env, email="tc1@x.com")
    g_id = gc["guardian"]["id"]
    book_activity(g_id, archery["id"], gc["application"]["id"])
    # Swim starts at 600 but Archery ends at 600 with 15-min buffer -> needs start >= 615 -> conflict
    resp = api_client.create_activity_enrollment(
        {"offering_id": swim["id"], "application_id": gc["application"]["id"]},
        make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT.value)


def test_activity_raw_interval_overlap_rejected():
    """PRD §3.8: "treating each offering's interval as half-open from its
    `starts_minute` up to but not including its `ends_minute`, a conflict exists if the
    new offering's interval and an existing booking's interval overlap."
    PRD §3.8: "A booking is rejected if either the raw intervals overlap or the buffer
    window is violated on that slot day."

    Design: Difficulty/resource_temporal_overlap/activity_buffer_window_collision_on_offering_slot
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    first = make_activity(env["session"]["id"], name="Archery", slot_day=1,
                          starts_minute=540, ends_minute=600, seat_capacity=10)
    # overlapping raw interval [570, 630) on the same slot_day
    second = make_activity(env["session"]["id"], name="Riding", slot_day=1,
                           starts_minute=570, ends_minute=630, seat_capacity=10)
    gc = setup_submitted_application(env, email="tc2@x.com")
    g_id = gc["guardian"]["id"]
    book_activity(g_id, first["id"], gc["application"]["id"])
    resp = api_client.create_activity_enrollment(
        {"offering_id": second["id"], "application_id": gc["application"]["id"]},
        make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT.value)


def test_visiting_day_outside_session_window_rejected():
    """PRD §3.1: "a visiting-day instant `visiting_day_on` that must fall within the
    inclusive window from `starts_on` to `ends_on`".
    PRD §3.1: "A start instant not strictly before the end, or a visiting day outside
    the session window, is rejected — the former as `ERR_INVALID_REQUEST` and the
    latter as `ERR_VISITING_DAY_OUT_OF_RANGE`."

    Design: Difficulty/resource_temporal_overlap/visiting_day_outside_session_window_closed_interval
    """
    camp = make_camp()  # sets clock + creates camp
    director = make_director_headers()
    resp = api_client.create_session(
        camp["id"],
        {"name": "Bad Session", "starts_on": "2026-07-01T00:00:00Z",
         "ends_on": "2026-07-14T00:00:00Z", "visiting_day_on": "2026-07-20T00:00:00Z",
         "capacity": 10},
        director)
    validate_error(resp, ApiErrorId.ERR_VISITING_DAY_OUT_OF_RANGE.value)


def test_visiting_day_before_starts_on_rejected():
    """PRD §3.1: "a visiting-day instant `visiting_day_on` that must fall within the
    inclusive window from `starts_on` to `ends_on`".
    PRD §3.1: "A start instant not strictly before the end, or a visiting day outside
    the session window, is rejected — the former as `ERR_INVALID_REQUEST` and the
    latter as `ERR_VISITING_DAY_OUT_OF_RANGE`."

    Design: Difficulty/resource_temporal_overlap/visiting_day_outside_session_window_closed_interval
    """
    camp = make_camp()
    director = make_director_headers()
    # visiting_day 2026-06-25 is before starts_on 2026-07-01 -> out of range
    resp = api_client.create_session(
        camp["id"],
        {"name": "Bad Session 2", "starts_on": "2026-07-01T00:00:00Z",
         "ends_on": "2026-07-14T00:00:00Z", "visiting_day_on": "2026-06-25T00:00:00Z",
         "capacity": 10},
        director)
    validate_error(resp, ApiErrorId.ERR_VISITING_DAY_OUT_OF_RANGE.value)


# ===========================================================================
# Difficulty / compensating_invariant
# ===========================================================================
def test_activity_book_then_drop_conserves_seats_taken():
    """PRD §3.8: "On success the enrollment is `BOOKED` and the offering's
    `seats_taken` is incremented. Dropping a booking moves it from `BOOKED` to
    `DROPPED` and decrements the offering's `seats_taken`."
    PRD §3.8: "tracks `seats_taken`, the count of its activity enrollments in
    `BOOKED` status."

    Design: Difficulty/compensating_invariant/activity_book_then_drop_conserves_seats_taken
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000},
                                  cabin_overrides={"gender_band": "GIRLS"})
    crafts = make_activity(env["session"]["id"], name="Crafts", slot_day=1,
                           starts_minute=60, ends_minute=120, seat_capacity=5)
    gc = setup_submitted_application(env, email="ci1@x.com", camper_overrides={"gender": "GIRL"})
    g_id = gc["guardian"]["id"]
    ae = book_activity(g_id, crafts["id"], gc["application"]["id"])
    after_book = validate_success(api_client.get_activity(crafts["id"], make_guardian_headers(g_id)))
    assert after_book["seats_taken"] == 1, after_book["seats_taken"]

    dropped = validate_success(api_client.drop_activity_enrollment(ae["id"], make_guardian_headers(g_id)))
    assert dropped["status"] == "DROPPED", dropped["status"]
    after_drop = validate_success(api_client.get_activity(crafts["id"], make_guardian_headers(g_id)))
    assert after_drop["seats_taken"] == 0, after_drop["seats_taken"]  # conserved: back to pre-book value


def test_seats_taken_conserved_with_two_bookers_after_one_drops():
    """PRD §3.8: "On success the enrollment is `BOOKED` and the offering's
    `seats_taken` is incremented. Dropping a booking moves it from `BOOKED` to
    `DROPPED` and decrements the offering's `seats_taken`."

    Design: Difficulty/compensating_invariant/activity_book_then_drop_conserves_seats_taken
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    offering = make_activity(env["session"]["id"], name="Hiking", slot_day=2,
                             starts_minute=300, ends_minute=360, seat_capacity=5)
    gc_a = setup_submitted_application(env, email="ci2a@x.com")
    gc_b = setup_submitted_application(env, email="ci2b@x.com")
    ae_a = book_activity(gc_a["guardian"]["id"], offering["id"], gc_a["application"]["id"])
    book_activity(gc_b["guardian"]["id"], offering["id"], gc_b["application"]["id"])
    two = validate_success(api_client.get_activity(offering["id"], make_director_headers()))
    assert two["seats_taken"] == 2, two["seats_taken"]

    # A drops -> seats_taken returns to exactly the remaining BOOKED count (1)
    get_success_data(api_client.drop_activity_enrollment(
        ae_a["id"], make_guardian_headers(gc_a["guardian"]["id"])))
    one = validate_success(api_client.get_activity(offering["id"], make_director_headers()))
    assert one["seats_taken"] == 1, one["seats_taken"]


def test_canteen_deposit_then_equal_purchase_conserves_balance():
    """PRD §3.9: "The account's balance is derived: it is the sum of the
    `amount_cents` of all `APPLIED` canteen transactions of kind `DEPOSIT` minus the
    sum of the `amount_cents` of all `APPLIED` canteen transactions of kind
    `PURCHASE`."
    PRD §3.9: "The account's `is_low` flag is true exactly when `balance_cents` is at
    or below the camp's `canteen_low_balance_cents`."

    Design: Difficulty/compensating_invariant/canteen_deposit_then_equal_purchase_conserves_balance
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "canteen_low_balance_cents": 1_000})
    gc = setup_submitted_application(env, email="cv1@x.com")
    g_id = gc["guardian"]["id"]
    acct = open_canteen_account(g_id, gc["application"]["id"])
    # DEPOSIT 3000 (forward) then PURCHASE 3000 (compensating) -> balance back to 0
    canteen_txn(g_id, acct["id"], "DEPOSIT", 3_000)
    canteen_txn(g_id, acct["id"], "PURCHASE", 3_000)
    final = validate_success(api_client.get_canteen_account(acct["id"], make_guardian_headers(g_id)))
    assert final["balance_cents"] == 0, final["balance_cents"]
    assert final["is_low"] is True, final["is_low"]  # 0 <= 1000


def test_canteen_balance_conserved_across_multiple_offsetting_txns():
    """PRD §3.9: "it is the sum of the `amount_cents` of all `APPLIED` canteen
    transactions of kind `DEPOSIT` minus the sum of the `amount_cents` of all
    `APPLIED` canteen transactions of kind `PURCHASE`."

    Design: Difficulty/compensating_invariant/canteen_deposit_then_equal_purchase_conserves_balance
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "canteen_low_balance_cents": 1_000})
    gc = setup_submitted_application(env, email="cv2@x.com")
    g_id = gc["guardian"]["id"]
    acct = open_canteen_account(g_id, gc["application"]["id"])
    # deposit 4000, purchase 1500, deposit 500, purchase 3000 -> net 0 (sum dep 4500 - sum pur 4500)
    canteen_txn(g_id, acct["id"], "DEPOSIT", 4_000)
    canteen_txn(g_id, acct["id"], "PURCHASE", 1_500)
    canteen_txn(g_id, acct["id"], "DEPOSIT", 500)
    canteen_txn(g_id, acct["id"], "PURCHASE", 3_000)
    final = validate_success(api_client.get_canteen_account(acct["id"], make_guardian_headers(g_id)))
    assert final["balance_cents"] == 0, final["balance_cents"]


# ===========================================================================
# Corner / calculations — canteen is_low threshold, adjacent booking
# ===========================================================================
def test_canteen_is_low_flips_at_low_balance_threshold():
    """PRD §3.9: "The account's `is_low` flag is true exactly when `balance_cents` is
    at or below the camp's `canteen_low_balance_cents`."

    Design: Corner/calculations/canteen_is_low_flag_at_low_balance_threshold
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "canteen_low_balance_cents": 1_000})
    gc = setup_canteen_with_balance(env, 1_000, email="il1@x.com")
    g_id = gc["guardian"]["id"]
    acct_id = gc["account"]["id"]
    at_threshold = validate_success(api_client.get_canteen_account(acct_id, make_guardian_headers(g_id)))
    assert at_threshold["balance_cents"] == 1_000
    assert at_threshold["is_low"] is True  # 1000 <= 1000

    # deposit 1 more -> 1001 -> is_low false
    get_success_data(api_client.create_canteen_transaction(
        acct_id, {"kind": "DEPOSIT", "amount_cents": 1}, make_guardian_headers(g_id)))
    above = validate_success(api_client.get_canteen_account(acct_id, make_guardian_headers(g_id)))
    assert above["balance_cents"] == 1_001, above["balance_cents"]
    assert above["is_low"] is False, above["is_low"]


def test_activity_adjacent_no_buffer_books_successfully():
    """PRD §3.8: "Because the intervals are half-open, exact adjacency — where one
    offering's `ends_minute` equals the other's `starts_minute` — is allowed and is
    not a conflict."

    Design: Corner/calculations/activity_adjacent_no_buffer_books_successfully
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    archery = make_activity(env["session"]["id"], name="Archery", slot_day=1,
                            starts_minute=540, ends_minute=600, seat_capacity=10)
    swim = make_activity(env["session"]["id"], name="Swim", slot_day=1,
                         starts_minute=600, ends_minute=660, seat_capacity=10)
    gc = setup_submitted_application(env, email="adj1@x.com")
    g_id = gc["guardian"]["id"]
    book_activity(g_id, archery["id"], gc["application"]["id"])
    # adjacency at 600 with no buffer -> allowed
    data = validate_success(api_client.create_activity_enrollment(
        {"offering_id": swim["id"], "application_id": gc["application"]["id"]},
        make_guardian_headers(g_id)), expected_status=201)
    assert data["status"] == "BOOKED", data["status"]
    after = validate_success(api_client.get_activity(swim["id"], make_guardian_headers(g_id)))
    assert after["seats_taken"] == 1, after["seats_taken"]
