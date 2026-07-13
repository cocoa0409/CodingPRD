"""The depth-4 learn-to-skate cancel cascade and two validation-priority pairs
where a higher-priority check pre-empts a lower-priority one."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_skater_headers,
    create_rink, create_published_slot, create_class, create_skater,
    create_funded_skater, assign_locker, setup_active_subscription,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/cascade_slot_cancel_class_enrollment_subscription_refund
# ---------------------------------------------------------------------------
def test_slot_cancel_cascades_through_class_enrollment_subscription(api):
    """PRD §3.1: "for a `LEARN_TO_SKATE` slot, every non-terminal class on the slot
    becomes `CANCELLED`, which withdraws its enrollments and in turn cancels their
    tuition subscriptions with proration refunds".
    PRD §3.3: "When a parent ice slot is cancelled, each non-terminal class on it
    becomes `CANCELLED` and its `ENROLLED` enrollments become `WITHDRAWN`".

    Design: Difficulty/transitive_cascade/cascade_slot_cancel_class_enrollment_subscription_refund
    """
    setup = setup_active_subscription(api, clock="2026-06-16T00:00:00Z",
                                      proration_mode="CALENDAR", sessions_attended=5,
                                      email="cascade@x.com")
    slot = validate_success(api.cancel_ice_slot(setup["slot"]["id"], RM))
    assert slot["status"] == "CANCELLED", f"slot expected CANCELLED, got {slot['status']}"
    cls = validate_success(api.get_class(setup["class_id"], RM))
    assert cls["status"] == "CANCELLED", f"class expected CANCELLED, got {cls['status']}"
    enr = validate_success(api.get_enrollment(setup["enrollment"]["id"], RM))
    assert enr["status"] == "WITHDRAWN", f"enrollment expected WITHDRAWN, got {enr['status']}"
    sub = validate_success(api.get_tuition_subscription(setup["subscription"]["id"], RM))
    assert sub["status"] == "CANCELLED", f"subscription expected CANCELLED, got {sub['status']}"


def test_slot_cancel_cascade_refunds_prorated_tuition(api):
    """PRD §3.4: "Cancelling an `ACTIVE` subscription ... computes a proration
    refund, credits it to the wallet, sets `status` to `CANCELLED`".
    PRD §3.4: "The refund is the `monthly_fee_cents` multiplied by days remaining,
    divided by total days, rounded half-up to whole cents."

    Design: Difficulty/transitive_cascade/cascade_slot_cancel_class_enrollment_subscription_refund
    """
    # fee 12000, cycle 30 days, clock 2026-06-16 -> 15 days remaining -> refund 6000.
    # Wallet 100000 - 12000 (sub create) + 6000 (cascade refund) = 94000.
    setup = setup_active_subscription(api, clock="2026-06-16T00:00:00Z",
                                      proration_mode="CALENDAR", sessions_attended=5,
                                      email="cascaderef@x.com")
    validate_success(api.cancel_ice_slot(setup["slot"]["id"], RM))
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 94000, (
        f"expected prorated refund to 94000, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/conflict_existence_beats_state_returns_not_found
# ---------------------------------------------------------------------------
def _cancelled_class(api):
    rink = create_rink(api)
    slot = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    cls = create_class(api, slot["id"])
    validate_success(api.cancel_ice_slot(slot["id"], RM))  # -> class CANCELLED
    return cls


def test_nonexistent_skater_into_cancelled_class_returns_not_found(api):
    """PRD §2.9: "Existence — every resource referenced by a path identifier or a
    foreign-key body field ... must exist. Path identifiers are checked
    left-to-right, and the first identifier that does not resolve yields
    `ERR_NOT_FOUND` (404) before any identifier to its right is examined."
    PRD §2.9: "a mid-flight state problem surfaces as `ERR_INVALID_STATE` before any
    capacity or fiscal check runs".

    Design: Difficulty/priority_pair_validation_conflict/conflict_existence_beats_state_returns_not_found
    """
    cls = _cancelled_class(api)
    # Enroll a non-existent skater into the CANCELLED class: existence (priority 3)
    # is checked before state (priority 4), so ERR_NOT_FOUND wins.
    validate_error(
        api.create_enrollment(cls["id"], {"skater_id": NON_EXISTENT_UUID}, RM),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_existing_skater_into_cancelled_class_returns_invalid_state(api):
    """PRD §3.3: "The class must be `OPEN` — enrolling on a `FULL`, `CANCELLED`, or
    `COMPLETED` class yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_existence_beats_state_returns_not_found
    """
    cls = _cancelled_class(api)
    # With a real skater the existence check passes, so the state check fires.
    sk = create_skater(api, "stateonly@x.com")
    validate_error(
        api.create_enrollment(cls["id"], {"skater_id": sk["id"]}, RM),
        ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/conflict_locker_overlap_beats_insufficient_funds
# ---------------------------------------------------------------------------
def test_locker_overlap_beats_insufficient_funds(api):
    """PRD §2.9: "6. Temporal overlap — the ice-slot resurface-buffer collision
    (`ERR_SLOT_OVERLAP`, 409) or the locker season-range collision
    (`ERR_LOCKER_OCCUPIED`, 409)."
    PRD §2.9: "8. Fiscal — sufficient wallet credit for the charge, else
    `ERR_INSUFFICIENT_FUNDS` (402)."

    Design: Difficulty/priority_pair_validation_conflict/conflict_locker_overlap_beats_insufficient_funds
    """
    rink = create_rink(api, locker_fee_cents=2000)
    sk_a = create_funded_skater(api, "lka@x.com", 100000)
    assign_locker(api, rink["id"], sk_a["id"], 1, "2026-06-01", "2026-09-01",
                  as_skater_id=sk_a["id"])
    sk_b = create_skater(api, "lkb@x.com")  # wallet 0
    # B overlaps locker 1 AND cannot pay: temporal (priority 6) pre-empts fiscal (8).
    resp = api.create_locker_assignment(
        rink["id"],
        {"skater_id": sk_b["id"], "locker_number": 1,
         "season_start_date": "2026-08-01", "season_end_date": "2026-10-01"},
        make_skater_headers(sk_b["id"]))
    validate_error(resp, ApiErrorId.ERR_LOCKER_OCCUPIED.value)


def test_insufficient_funds_when_locker_not_occupied(api):
    """PRD §2.7: "Whenever an operation would charge more than the wallet holds —
    an admission fee, a locker fee, a tuition monthly fee, or a slot-booking quote
    — the request is rejected with `ERR_INSUFFICIENT_FUNDS` and no money moves."

    Design: Difficulty/priority_pair_validation_conflict/conflict_locker_overlap_beats_insufficient_funds
    """
    rink = create_rink(api, locker_fee_cents=2000)
    sk_a = create_funded_skater(api, "lkc@x.com", 100000)
    assign_locker(api, rink["id"], sk_a["id"], 1, "2026-06-01", "2026-09-01",
                  as_skater_id=sk_a["id"])
    sk_b = create_skater(api, "lkd@x.com")  # wallet 0
    # B requests a DIFFERENT, free locker: no overlap, so the fiscal check fires.
    resp = api.create_locker_assignment(
        rink["id"],
        {"skater_id": sk_b["id"], "locker_number": 2,
         "season_start_date": "2026-08-01", "season_end_date": "2026-10-01"},
        make_skater_headers(sk_b["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
