"""Locker provisioning, storage fees, occupancy counts and capacity boundaries."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    onboard_member, create_locker, assign_locker,
    setup_active_member_with_locker, store_bottle,
    create_locker_payload, create_bottle_payload, make_cellar_member_headers,
)

MGR = TEST_USERS["cellar_manager_headers"]


# --------------------------------------------------------------------------- #
# Queue A — combinatorial_formula / storage_fee_tier_climate_occupancy_clamp
# --------------------------------------------------------------------------- #
def test_storage_fee_large_sparkling_full_surcharge(api):
    """PRD §3.2: "The raw fee is the base rate multiplied by the climate multiplier,
    multiplied by one plus the surcharge fraction (so by 1.10 when full, by 1.00
    otherwise). That raw value is rounded half-up to two decimal places and taken as
    integer cents, then clamped so that it is never below a floor of 2,500 cents and
    never above a cap of 9,000 cents."

    Design: Difficulty/combinatorial_formula/storage_fee_tier_climate_occupancy_clamp
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="SPARKLING", capacity=1, tier="RESERVE"
    )
    store_bottle(api, locker["id"], member["id"], wine_name="Krug", format_ml=750)
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["occupancy_status"] == "FULL", f"expected FULL, got {lk['occupancy_status']}"
    assert lk["monthly_fee_cents"] == 8580, (
        f"LARGE*SPARKLING*FULL fee should be 8580, got {lk['monthly_fee_cents']}"
    )


def test_storage_fee_surcharge_only_applies_when_full(api):
    """PRD §3.2: "A full-occupancy surcharge of ten percent applies only while the
    locker's `occupancy_status` is `FULL`; otherwise no surcharge applies."

    Design: Difficulty/combinatorial_formula/storage_fee_tier_climate_occupancy_clamp
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="SPARKLING", capacity=1, tier="RESERVE"
    )
    # VACANT: no surcharge -> 6000 * 1.30 * 1.00 = 7800
    before = validate_success(api.get_locker(locker["id"], MGR))
    assert before["occupancy_status"] == "VACANT"
    assert before["monthly_fee_cents"] == 7800, (
        f"vacant fee should be 7800 (no surcharge), got {before['monthly_fee_cents']}"
    )
    # FULL: 10% surcharge -> 7800 * 1.10 = 8580
    store_bottle(api, locker["id"], member["id"], wine_name="Krug", format_ml=750)
    after = validate_success(api.get_locker(locker["id"], MGR))
    assert after["monthly_fee_cents"] == 8580, (
        f"full fee should be 8580 (surcharge applied), got {after['monthly_fee_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — boundary_precision_check / locker_capacity_exact_boundary
# --------------------------------------------------------------------------- #
def test_deposit_into_full_locker_rejected(api):
    """PRD §3.3: "A deposit consumes one free unit of the locker, so it is refused with
    `ERR_LOCKER_CAPACITY_EXCEEDED` when the locker has no free capacity — that is, when
    `free_bottles` would be driven below zero; a locker whose `free_bottles` is already
    zero blocks the deposit at that boundary."

    Design: Difficulty/boundary_precision_check/locker_capacity_exact_boundary
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=1, tier="STANDARD"
    )
    store_bottle(api, locker["id"], member["id"], wine_name="First Fill")
    overflow = create_bottle_payload(locker_id=locker["id"], wine_name="Overflow")
    validate_error(
        api.create_bottle(overflow, make_cellar_member_headers(member["id"])),
        ApiErrorId.ERR_LOCKER_CAPACITY_EXCEEDED.value,
    )


def test_capacity_free_bottles_zero_at_exact_boundary(api):
    """PRD §3.2: "it is `FULL` when `occupied_bottles` is greater than or equal to
    `capacity_bottles`; otherwise it is `PARTIAL`. Note the boundary: a locker whose
    stored count reaches capacity is `FULL`, not merely partial."

    Design: Difficulty/boundary_precision_check/locker_capacity_exact_boundary
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=1, tier="STANDARD"
    )
    store_bottle(api, locker["id"], member["id"], wine_name="First Fill")
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["occupied_bottles"] == 1, f"occupied should equal capacity 1, got {lk['occupied_bottles']}"
    assert lk["free_bottles"] == 0, f"free should be exactly 0 at boundary, got {lk['free_bottles']}"
    assert lk["occupancy_status"] == "FULL", f"reaching capacity is FULL, got {lk['occupancy_status']}"


# --------------------------------------------------------------------------- #
# Queue A — cross_entity_state_dependency / assign_requires_member_active
# --------------------------------------------------------------------------- #
def test_assign_locker_to_pending_member_rejected(api):
    """PRD §3.2: "The request names the target `member_id`; that member must be `ACTIVE`,
    and a locker assignment to a member who is not active is refused with
    `ERR_MEMBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_member_active
    """
    member = onboard_member(api, tier="STANDARD", activate=False)  # PENDING
    locker = create_locker(api, size_tier="SMALL", climate_zone="RED", capacity=2)
    validate_error(
        api.assign_locker(locker["id"], {"member_id": member["id"]}, MGR),
        ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value,
    )


def test_assign_to_pending_member_leaves_locker_available(api):
    """PRD §3.2: "Assigning a locker moves it from `AVAILABLE` to `ASSIGNED`." — a
    refused assignment to a non-active member (`ERR_MEMBER_NOT_ACTIVE`) must not perform
    the transition.

    Design: Difficulty/cross_entity_state_dependency/assign_requires_member_active
    """
    member = onboard_member(api, tier="STANDARD", activate=False)  # PENDING
    locker = create_locker(api, size_tier="SMALL", climate_zone="RED", capacity=2)
    validate_error(
        api.assign_locker(locker["id"], {"member_id": member["id"]}, MGR),
        ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value,
    )
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["status"] == "AVAILABLE", f"locker must stay AVAILABLE, got {lk['status']}"


# --------------------------------------------------------------------------- #
# Queue B — calculations / storage_fee_minimum_floor_applied
# --------------------------------------------------------------------------- #
def test_storage_fee_minimum_floor_applied(api):
    """PRD §3.2: "then clamped so that it is never below a floor of 2,500 cents and
    never above a cap of 9,000 cents."

    Design: Corner/calculations/storage_fee_minimum_floor_applied
    """
    payload = create_locker_payload(size_tier="SMALL", climate_zone="RED", capacity_bottles=3)
    # SMALL*RED = 2000*1.00 = 2000, clamps up to the 2500 floor.
    data = validate_success(api.create_locker(payload, MGR), expected_status=201)
    assert data["monthly_fee_cents"] == 2500, (
        f"fee should clamp up to floor 2500, got {data['monthly_fee_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — state_machines / release_non_empty_locker_returns_not_empty
# --------------------------------------------------------------------------- #
def test_release_non_empty_locker_returns_not_empty(api):
    """PRD §3.2: "Releasing a locker moves it from `ASSIGNED` back to `AVAILABLE`, but
    only if it is completely unencumbered: both `occupied_bottles` and `reserved_bottles`
    must be zero, and a release attempted while either count is non-zero is refused with
    `ERR_LOCKER_NOT_EMPTY`."

    Design: Corner/state_machines/release_non_empty_locker_returns_not_empty
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=2, tier="STANDARD"
    )
    store_bottle(api, locker["id"], member["id"], wine_name="Stay Put")
    validate_error(api.release_locker(locker["id"], MGR), ApiErrorId.ERR_LOCKER_NOT_EMPTY.value)
