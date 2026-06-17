"""Roommate-group formation, the cyclic lock/reopen negotiation, membership
sizing constraints, and disband cascade."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_roommate_group, assert_membership,
    make_officer_headers, make_student_headers,
    create_student, create_cycle,
    create_roommate_group, invite_member, accept_member, setup_full_forming_group,
)

OFFICER = make_officer_headers()


# ─── Difficulty: cyclic lock -> reopen returns to FORMING ─────────────────────

def test_roommate_group_lock_then_reopen_returns_to_forming(api):
    """PRD §3.5: "When the group is exactly full — its `accepted_member_count`
    equals its `target_size` — the owner may lock it, moving its `status` from
    `FORMING` to `LOCKED` and freezing membership so no further invite, accept, or
    decline is honored." ... "The owner may reopen a locked group, moving it from
    `LOCKED` back to `FORMING` so membership becomes editable again, but only when
    no application referencing the group is in `SUBMITTED`, `OFFERED`, or
    `ACCEPTED` status".

    Design: Difficulty/non_linear_state_machine/roommate_group_cyclic_lock_reopen
    """
    grp = setup_full_forming_group(target_size=2, term_label="FALL_2026E")
    group, owner = grp["group"], grp["owner"]
    locked = validate_success(api.lock_group(group["id"], make_student_headers(owner["id"])), 200)
    assert locked["status"] == "LOCKED"
    reopened = validate_success(
        api.reopen_group(group["id"], make_student_headers(owner["id"])), 200)
    assert reopened["status"] == "FORMING"
    assert reopened["accepted_member_count"] == 2


def test_roommate_group_lock_freezes_at_target_size(api):
    """PRD §3.5: "Locking requires the count to equal the target exactly; a lock
    attempted when `accepted_member_count` does not equal `target_size` is rejected
    with `ERR_GROUP_SIZE_INVALID` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/roommate_group_cyclic_lock_reopen
    """
    grp = setup_full_forming_group(target_size=2, term_label="FALL_LOCK2")
    group, owner = grp["group"], grp["owner"]
    locked = validate_success(api.lock_group(group["id"], make_student_headers(owner["id"])), 200)
    assert_roommate_group(locked)
    assert locked["status"] == "LOCKED"
    assert locked["accepted_member_count"] == locked["target_size"] == 2


# ─── Corner: lock not full → ERR_GROUP_SIZE_INVALID ───────────────────────────

def test_lock_group_not_full_returns_group_size_invalid(api):
    """PRD §3.5: "Locking requires the count to equal the target exactly; a lock
    attempted when `accepted_member_count` does not equal `target_size` is rejected
    with `ERR_GROUP_SIZE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/lock_group_not_full_returns_group_size_invalid
    """
    owner = create_student(full_name="Lonely Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=220)
    cycle = create_cycle(term_label="LOCK_T")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=2)
    # Only the owner is ACCEPTED (count 1), below target 2.
    res = api.lock_group(group["id"], make_student_headers(owner["id"]))
    validate_error(res, "ERR_GROUP_SIZE_INVALID")
    after = validate_success(api.get_roommate_group(group["id"], OFFICER), 200)
    assert after["status"] == "FORMING"


# ─── Corner: duplicate membership invite rejected ─────────────────────────────

def test_duplicate_membership_invite_rejected(api):
    """PRD §3.5: "A student may not be invited to a group where they already hold
    a membership in `INVITED` or `ACCEPTED` status; such a duplicate invite is
    rejected with `ERR_DUPLICATE_MEMBERSHIP` (HTTP 409)."

    Design: Corner/errors/duplicate_membership_invite_rejected
    """
    owner = create_student(full_name="DupMem Owner", class_year="JUNIOR",
                           gender_identity="FEMALE", lottery_number=460)
    mate = create_student(full_name="DupMem Mate", class_year="JUNIOR",
                          gender_identity="FEMALE", lottery_number=461)
    cycle = create_cycle(term_label="DM_T")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=3)
    invite_member(group["id"], owner["id"], mate["id"])  # first invite -> INVITED
    res = api.create_membership(
        group["id"], {"student_id": mate["id"]}, make_student_headers(owner["id"]))
    validate_error(res, "ERR_DUPLICATE_MEMBERSHIP", expected_status=409)


# ─── Corner: disband cascades memberships to REMOVED ──────────────────────────

def test_disband_group_removes_memberships(api):
    """PRD §3.5: "The owner may disband the group from either `FORMING` or
    `LOCKED`, moving it to the terminal `DISBANDED`, provided no application
    referencing the group is in `OFFERED` or `ACCEPTED` status (otherwise
    `ERR_PRECONDITION_NOT_MET`, HTTP 409). Disbanding moves every membership still
    in `INVITED` or `ACCEPTED` to `REMOVED`, and any `SUBMITTED` application that
    referenced the group keeps competing solo with its `roommate_group_id`
    cleared to null."

    Design: Corner/cross_cutting_complexity_layers/cascade_disband_group_removes_memberships
    """
    grp = setup_full_forming_group(target_size=2, term_label="DIS_T")
    group, owner = grp["group"], grp["owner"]
    membership = grp["memberships"][0]
    disbanded = validate_success(
        api.disband_group(group["id"], make_student_headers(owner["id"])), 200)
    assert disbanded["status"] == "DISBANDED"
    mem_after = validate_success(api.get_membership(membership["id"], OFFICER), 200)
    assert mem_after["membership_status"] == "REMOVED"


# ─── Difficulty: state-vs-constraint precedence on membership accept ──────────

def test_accept_declined_membership_in_full_group_returns_invalid_state(api):
    """PRD §2.8: "Only after these gates do domain rules apply — date-range
    validity, state validity, cross-entity preconditions, gender compatibility,
    hold status, overlap and capacity ceilings, group sizing, settlement,
    duplicate prevention, and finally the optimistic-concurrency version check."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_constraint_on_membership_accept_declined_full_group
    """
    # A FORMING group at target_size 2 already full (owner + M1 ACCEPTED); a
    # second invitee M2 whose membership is DECLINED. Accepting M2's membership
    # violates both state (already DECLINED) and group sizing (already full);
    # state validity precedes group sizing, so ERR_INVALID_STATE wins.
    owner = create_student(full_name="Conf Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=80)
    m1 = create_student(full_name="Conf M1", class_year="JUNIOR",
                        gender_identity="MALE", lottery_number=81)
    m2 = create_student(full_name="Conf M2", class_year="JUNIOR",
                        gender_identity="MALE", lottery_number=82)
    cycle = create_cycle(term_label="FALL_2026J")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=2)
    mem1 = invite_member(group["id"], owner["id"], m1["id"])
    accept_member(group["id"], mem1["id"], m1["id"])  # group now full (count 2)
    mem2 = invite_member(group["id"], owner["id"], m2["id"])
    validate_success(
        api.decline_membership(group["id"], mem2["id"], make_student_headers(m2["id"])), 200)
    # Now accept the already-DECLINED membership.
    res = api.accept_membership(group["id"], mem2["id"], make_student_headers(m2["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    mem2_after = validate_success(api.get_membership(mem2["id"], OFFICER), 200)
    assert mem2_after["membership_status"] == "DECLINED"


def test_accept_membership_increments_accepted_count(api):
    """PRD §3.5: "The invited student accepts, moving their membership from
    `INVITED` to `ACCEPTED` and incrementing the group's `accepted_member_count`
    by 1; acceptance is permitted only while the group is `FORMING`, only by the
    invited student themselves, and only while `accepted_member_count` is still
    below `target_size`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_constraint_on_membership_accept_declined_full_group
    """
    owner = create_student(full_name="Count Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=83)
    mate = create_student(full_name="Count Mate", class_year="JUNIOR",
                          gender_identity="MALE", lottery_number=84)
    cycle = create_cycle(term_label="FALL_CNT")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=2)
    assert group["accepted_member_count"] == 1  # owner auto-accepted
    mem = invite_member(group["id"], owner["id"], mate["id"])
    accepted = validate_success(
        api.accept_membership(group["id"], mem["id"], make_student_headers(mate["id"])), 200)
    assert accepted["membership_status"] == "ACCEPTED"
    after = validate_success(api.get_roommate_group(group["id"], OFFICER), 200)
    assert after["accepted_member_count"] == 2
