"""License period overlap, kennel capacity, kennel-state gating, and the
safety-vs-temporal precedence at tag issuance (PRD §3.4, §3.2, §2.6).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_owner_headers,
    set_clock,
    create_owner,
    create_pet,
    create_kennel,
    create_draft_license,
    setup_active_individual_license,
    setup_approved_individual_license,
    setup_kennel_with_active_licenses,
    setup_designated_case,
    drive_license_to_approved,
)
from test_helpers import api_client

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_pet_license_period_half_open_overlap_rejected(api):
    """PRD §3.4: "there must be no other license of the same pet in ACTIVE or
    GRACE whose validity interval, running from its issued_on up to but not
    including its expires_on, overlaps the interval this issuance would create,
    which runs from the current time up to but not including the current time plus
    term_years ... a genuine overlap is rejected with ERR_LICENSE_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/pet_license_period_half_open_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    # First ACTIVE license for the pet: [2026-01-01, 2027-01-01).
    owner, pet, vr, ll1 = setup_active_individual_license(
        owner_overrides={"full_name": "Owner L", "email": "ol@x.com"},
        pet_overrides={"is_altered": True, "name": "Rover"},
    )
    # Second license for SAME pet, driven to APPROVED.
    ll2 = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_approved(owner["id"], ll2["id"], vr["id"])

    # Issue at 2026-06-01 → [2026-06-01, 2027-06-01) overlaps ll1.
    set_clock("2026-06-01T00:00:00Z")
    res = api.issue_tag(ll2["id"], CLERK)
    validate_error(res, "ERR_LICENSE_PERIOD_OVERLAP")

    ll1_after = validate_success(api.get_license(ll1["id"], CLERK), 200)
    assert ll1_after["status"] == "ACTIVE"


def test_kennel_slot_aggregate_capacity_overlap_rejected(api):
    """PRD §3.2: "there must be a free slot, meaning the kennel's occupied_slots is
    strictly below its slot_capacity; a full kennel (occupied slots at or above
    capacity) yields ERR_KENNEL_FULL."

    Design: Difficulty/resource_temporal_overlap/kennel_slot_aggregate_capacity_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    # Capacity 2, occupied 2.
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=2, occupied=2)

    pet3 = create_pet(owner["id"], name="M3", is_altered=True, species="DOG")
    lic3 = create_draft_license(
        owner["id"], pet3["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    res = api.submit_license(lic3["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_KENNEL_FULL")

    kennel_after = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_after["occupied_slots"] == 2


def test_kennel_full_boundary_occupied_equals_capacity(api):
    """PRD §3.2: "there must be a free slot, meaning the kennel's occupied_slots is
    strictly below its slot_capacity; a full kennel (occupied slots at or above
    capacity) yields ERR_KENNEL_FULL."

    Design: Difficulty/boundary_precision_check/kennel_full_boundary_occupied_equals_capacity
    """
    set_clock("2026-01-01T00:00:00Z")
    # Capacity 1, occupied 1 → occupied(1) is NOT < capacity(1).
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=1, occupied=1)

    pet2 = create_pet(owner["id"], name="P2", is_altered=True, species="DOG")
    lic2 = create_draft_license(
        owner["id"], pet2["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    res = api.submit_license(lic2["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_KENNEL_FULL")

    kennel_after = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_after["occupied_slots"] == 1


def test_submit_kennel_license_blocked_when_kennel_suspended(api):
    """PRD §3.2: "A kind/kennel mismatch - an INDIVIDUAL carrying a kennel_id, or a
    KENNEL whose kennel is missing or not OPEN - is rejected with
    ERR_LICENSE_KIND_MISMATCH."

    Design: Difficulty/cross_entity_state_dependency/submit_depends_on_kennel_open_state
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner K", email="ok@x.com", address_zip="12001")
    kennel = create_kennel(owner["id"], slot_capacity=4, facility_name="K Kennels")
    pet = create_pet(owner["id"], name="Spot", is_altered=True, species="DOG")
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    # Suspend the kennel, then attempt submit.
    validate_success(api.suspend_kennel(kennel["id"], OFFICER), 200)

    res = api.submit_license(lic["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_LICENSE_KIND_MISMATCH")

    kennel_after = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_after["status"] == "SUSPENDED"


def test_dangerous_hold_beats_period_overlap_on_issue_tag(api):
    """PRD §3.4: "Two safety gates apply. First, the pet must not be under a live
    dangerous-dog hold ... a pet carrying an open DESIGNATED case cannot have a tag
    issued, and the attempt fails with ERR_DANGEROUS_DOG_HOLD. Second, the new
    license period must not collide with another live license for the same pet ...
    a genuine overlap is rejected with ERR_LICENSE_PERIOD_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/dangerous_hold_safety_beats_period_overlap_on_issue_tag
    """
    set_clock("2026-01-01T00:00:00Z")
    # LG1 ACTIVE first → provides the overlapping period.
    owner, pet, vr, lg1 = setup_active_individual_license(
        owner_overrides={"full_name": "Owner G", "email": "og@x.com"},
        pet_overrides={"is_altered": False, "name": "Bruno"},
    )
    # LG2 second license for the same pet, driven to APPROVED.
    lg2 = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_approved(owner["id"], lg2["id"], vr["id"])
    # Now designate the pet dangerous (after LG1 already ACTIVE).
    setup_designated_case(owner["id"], pet["id"], severity="ATTACK")

    # Issuing LG2's tag at clock 2026-01-01 both overlaps LG1 AND is dangerous-held;
    # the safety gate (First) wins.
    res = api.issue_tag(lg2["id"], CLERK)
    validate_error(res, "ERR_DANGEROUS_DOG_HOLD")


def test_adjacent_license_period_at_boundary_does_not_overlap(api):
    """PRD §3.4: "The intervals are half-open, so a prior license whose expires_on
    lands exactly at the current instant is adjacent rather than overlapping and
    does not block issuance".

    Companion (the permissive boundary of the half-open rule): a second license
    issued exactly when the first's expires_on lands is adjacent, not overlapping,
    so issuance succeeds.

    Design: Difficulty/resource_temporal_overlap/pet_license_period_half_open_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    # First license: [2026-01-01, 2027-01-01).
    owner, pet, vr, ll1 = setup_active_individual_license(
        owner_overrides={"full_name": "Owner L2", "email": "ol2@x.com"},
        pet_overrides={"is_altered": True, "name": "Rover2"},
    )
    ll2 = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_approved(owner["id"], ll2["id"], vr["id"])

    # Issue exactly at 2027-01-01 (== ll1.expires_on) → adjacent, not overlapping.
    set_clock("2027-01-01T00:00:00Z")
    issued = validate_success(api.issue_tag(ll2["id"], CLERK), 200)
    assert issued["status"] == "ACTIVE"


def test_kennel_below_capacity_submit_succeeds(api):
    """PRD §3.2: "there must be a free slot, meaning the kennel's occupied_slots is
    strictly below its slot_capacity".

    Companion (the X-1 / free-slot side of the kennel-full boundary): with
    occupied_slots(1) strictly below capacity(2), a new kennel submit succeeds and
    stamps a fee.

    Design: Difficulty/resource_temporal_overlap/kennel_slot_aggregate_capacity_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    # Capacity 2, occupied 1 → one free slot remains.
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=2, occupied=1)

    pet2 = create_pet(owner["id"], name="Free", is_altered=False, species="DOG")
    lic2 = create_draft_license(
        owner["id"], pet2["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    submitted = validate_success(
        api.submit_license(lic2["id"], make_owner_headers(owner["id"])), 200
    )
    assert submitted["status"] == "SUBMITTED"


def test_kennel_full_boundary_at_capacity_minus_one_succeeds(api):
    """PRD §3.2: "there must be a free slot, meaning the kennel's occupied_slots is
    strictly below its slot_capacity".

    Companion (the just-below-boundary case for the capacity==1 fixture): a kennel
    of capacity 1 with occupied_slots 0 admits its first kennel submit.

    Design: Difficulty/boundary_precision_check/kennel_full_boundary_occupied_equals_capacity
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner I2", email="oi2@x.com", address_zip="90002")
    kennel = create_kennel(owner["id"], slot_capacity=1, facility_name="I2 Kennels")
    pet = create_pet(owner["id"], name="P1", is_altered=True, species="DOG")
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    # occupied_slots(0) < capacity(1) → submit allowed.
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    assert submitted["status"] == "SUBMITTED"


def test_submit_open_kennel_license_succeeds(api):
    """PRD §3.2: "If the kind is KENNEL, a kennel_id must be present, the named
    kennel's status must be OPEN, and there must be a free slot".

    Companion (the OPEN-state permissive branch of the same cross-entity gate): a
    KENNEL license whose kennel is OPEN submits successfully.

    Design: Difficulty/cross_entity_state_dependency/submit_depends_on_kennel_open_state
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner K2", email="ok2@x.com", address_zip="12002")
    kennel = create_kennel(owner["id"], slot_capacity=4, facility_name="K2 Kennels")
    pet = create_pet(owner["id"], name="Spot2", is_altered=True, species="DOG")
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="KENNEL", term_years=1, kennel_id=kennel["id"]
    )
    # Kennel left OPEN → submit allowed.
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    assert submitted["status"] == "SUBMITTED"


def test_period_overlap_fires_alone_without_dangerous_hold(api):
    """PRD §3.4: "the new license period must not collide with another live license
    for the same pet ... a genuine overlap is rejected with
    ERR_LICENSE_PERIOD_OVERLAP."

    Companion to the safety-vs-temporal pair: with NO dangerous-dog hold present,
    the overlap rule fires on its own (ERR_LICENSE_PERIOD_OVERLAP), confirming the
    two gates are independent and the temporal one is what the safety gate
    pre-empts in the paired test.

    Design: Difficulty/priority_pair_validation_conflict/dangerous_hold_safety_beats_period_overlap_on_issue_tag
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lg1 = setup_active_individual_license(
        owner_overrides={"full_name": "Owner G2", "email": "og2@x.com"},
        pet_overrides={"is_altered": False, "name": "Bruno2"},
    )
    lg2 = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_approved(owner["id"], lg2["id"], vr["id"])

    # No designation → only the overlap gate can fire.
    set_clock("2026-06-01T00:00:00Z")
    res = api.issue_tag(lg2["id"], CLERK)
    validate_error(res, "ERR_LICENSE_PERIOD_OVERLAP")
