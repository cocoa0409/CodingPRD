"""Tournaments: provisional-vs-final prize pool, capacity boundary, check-in
gated on the tournament's OPEN state, cancellation refunds, and registration guards."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    create_tournament, create_open_tournament, create_membership, register, check_in,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


def _open_with_registrations(api, n, *, entry_fee_cents=1000, capacity=8, checked_in=0, prefix="p"):
    trn = create_open_tournament(api, entry_fee_cents=entry_fee_cents, capacity=capacity)
    regs = []
    for i in range(n):
        m = create_membership(api, email=f"{prefix}{i}@x.com", full_name=f"{prefix}{i}")
        regs.append(register(api, trn["id"], m["id"]))
    for i in range(checked_in):
        check_in(api, regs[i]["id"])
    return trn, regs


# ─── Difficulty/dual_variant_calc/tournament_prize_provisional_vs_final ────
def test_provisional_prize_counts_registered_and_checked_in(api):
    """PRD §3.6: "While the tournament is `OPEN`, reading it returns a live
    `provisional_prize_pool_cents` in which the eligible registrations are those that are
    `REGISTERED` or `CHECKED_IN`."
    PRD §3.6: "The gross is the number of eligible registrations multiplied by the
    tournament's `entry_fee_cents`; the `house_cut_cents` is 20 percent of that gross
    rounded half up; and the pool is the gross minus the house cut."

    Design: Difficulty/dual_variant_calc/tournament_prize_provisional_vs_final
    """
    trn, _ = _open_with_registrations(api, 3, entry_fee_cents=1000, checked_in=2, prefix="pa")
    data = validate_success(api.get_tournament(trn["id"], STAFF))
    # gross 3*1000=3000, house round(600)=600, pool 2400
    assert data["provisional_prize_pool_cents"] == 2400, \
        f"expected provisional 2400, got {data['provisional_prize_pool_cents']}"


def test_final_prize_freezes_checked_in_only(api):
    """PRD §3.6: "Starting the tournament moves it from `OPEN` to `RUNNING` and freezes the
    final figures: the eligible registrations are now only those that are `CHECKED_IN`, and
    from them `prize_pool_cents` and `house_cut_cents` are computed and frozen."

    Design: Difficulty/dual_variant_calc/tournament_prize_provisional_vs_final
    """
    trn, _ = _open_with_registrations(api, 3, entry_fee_cents=1000, checked_in=2, prefix="pb")
    started = validate_success(api.start_tournament(trn["id"], MGR))
    # gross 2*1000=2000, house 400, pool 1600
    assert started["prize_pool_cents"] == 1600, \
        f"expected final pool 1600, got {started['prize_pool_cents']}"
    assert started["house_cut_cents"] == 400


# ─── Difficulty/boundary_precision_check/tournament_capacity_exact_full_rejects_next ─
def test_registration_at_capacity_rejects_next(api):
    """PRD §3.6: "the count of registrations that are `REGISTERED` or `CHECKED_IN` must be
    strictly below the tournament's `capacity`, or the request is rejected with
    `ERR_TOURNAMENT_FULL`"

    Design: Difficulty/boundary_precision_check/tournament_capacity_exact_full_rejects_next
    """
    trn, _ = _open_with_registrations(api, 2, entry_fee_cents=0, capacity=2, prefix="fa")
    m3 = create_membership(api, email="f3@x.com", full_name="F3")
    res = api.create_registration({"tournament_id": trn["id"], "membership_id": m3["id"]}, STAFF)
    validate_error(res, "ERR_TOURNAMENT_FULL")


def test_registration_up_to_capacity_accepted(api):
    """PRD §3.6: "the count of registrations that are `REGISTERED` or `CHECKED_IN` must be
    strictly below the tournament's `capacity`, or the request is rejected with
    `ERR_TOURNAMENT_FULL`"

    Design: Difficulty/boundary_precision_check/tournament_capacity_exact_full_rejects_next
    """
    trn = create_open_tournament(api, entry_fee_cents=0, capacity=2)
    m1 = create_membership(api, email="fb1@x.com", full_name="FB1")
    m2 = create_membership(api, email="fb2@x.com", full_name="FB2")
    register(api, trn["id"], m1["id"])
    # second registration brings count to exactly capacity (2) and is still accepted
    second = validate_success(
        api.create_registration({"tournament_id": trn["id"], "membership_id": m2["id"]}, STAFF),
        expected_status=201)
    assert second["status"] == "REGISTERED"


# ─── Difficulty/cross_entity_state_dependency/checkin_depends_on_tournament_open_state ─
def test_checkin_while_open_succeeds(api):
    """PRD §3.6: "Checking a registrant in moves the registration from `REGISTERED` to
    `CHECKED_IN`; this requires the referenced tournament to still be `OPEN` (check-in
    happens before the tournament starts and freezes its pool), and a check-in attempted
    when the tournament is not `OPEN` is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/checkin_depends_on_tournament_open_state
    """
    trn, regs = _open_with_registrations(api, 2, entry_fee_cents=0, prefix="ga")
    checked = validate_success(api.check_in_registration(regs[0]["id"], STAFF))
    assert checked["status"] == "CHECKED_IN"


def test_checkin_after_start_rejected(api):
    """PRD §3.6: "a check-in attempted when the tournament is not `OPEN` is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/checkin_depends_on_tournament_open_state
    """
    trn, regs = _open_with_registrations(api, 2, entry_fee_cents=0, prefix="gb")
    check_in(api, regs[0]["id"])
    validate_success(api.start_tournament(trn["id"], MGR))  # -> RUNNING
    res = api.check_in_registration(regs[1]["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner/state_machines/cancel_open_tournament_refunds_all_registrations ─
def test_cancel_open_tournament_refunds_registration(api):
    """PRD §3.6: "If it was `OPEN` with registrations, every registration that is
    `REGISTERED` or `CHECKED_IN` is moved to the terminal `REFUNDED` state with
    `refunded_cents` set to its `fee_paid_cents`"

    Design: Corner/state_machines/cancel_open_tournament_refunds_all_registrations
    """
    trn, regs = _open_with_registrations(api, 1, entry_fee_cents=1000, prefix="rc")
    validate_success(api.cancel_tournament(trn["id"], MGR))
    reg = validate_success(api.get_registration(regs[0]["id"], STAFF))
    assert reg["status"] == "REFUNDED" and reg["refunded_cents"] == 1000


# ─── Corner/validations/duplicate_registration_returns_duplicate ───────────
def test_duplicate_registration_rejected(api):
    """PRD §3.6: "the member must not already hold a non-terminal registration (one that is
    `REGISTERED` or `CHECKED_IN`) for that tournament, or the request is rejected with
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_registration_returns_duplicate
    """
    trn = create_open_tournament(api, entry_fee_cents=0)
    m = create_membership(api, email="dupreg@x.com", full_name="DupReg")
    register(api, trn["id"], m["id"])
    res = api.create_registration({"tournament_id": trn["id"], "membership_id": m["id"]}, STAFF)
    validate_error(res, "ERR_DUPLICATE_REGISTRATION")


# ─── Corner/validations/register_scheduled_tournament_returns_not_open ─────
def test_register_scheduled_tournament_rejected(api):
    """PRD §3.6: "the tournament must be `OPEN`, or the request is rejected with
    `ERR_TOURNAMENT_NOT_OPEN`"

    Design: Corner/validations/register_scheduled_tournament_returns_not_open
    """
    trn = create_tournament(api, entry_fee_cents=0)  # SCHEDULED, never opened
    m = create_membership(api, email="no@x.com", full_name="No")
    res = api.create_registration({"tournament_id": trn["id"], "membership_id": m["id"]}, STAFF)
    validate_error(res, "ERR_TOURNAMENT_NOT_OPEN")
