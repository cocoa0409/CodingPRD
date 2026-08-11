"""Membership lifecycle: join policies, approve/reject/leave/remove, roster
capacity, roster conservation invariant (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    approve_membership_as_admin,
    create_group,
    join_group,
    make_admin_headers,
    make_member_headers,
    make_moderator_headers,
    make_moderator,
    register_member,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_open_vs_approval_membership_initial_status(api):
    """PRD §3.1: "Under an `OPEN` join policy the request is auto-approved
    inline: the membership is created directly in `APPROVED` status,
    `member_count` increases by one, and `roster_status` is recomputed; should
    the roster already be full, the join is rejected with `ERR_GROUP_FULL`.
    Under `APPROVAL_REQUIRED` the membership is created in `REQUESTED` and
    awaits a decision."

    Design: Corner/state_machines/open_vs_approval_membership_initial_status
    """
    m = register_member("jp@x.com", "M")
    g1 = create_group("Open G", "98211", join_policy="OPEN")
    g2 = create_group("Approval G", "98212", join_policy="APPROVAL_REQUIRED")
    ms1 = validate_success(
        api.create_membership({"group_id": g1["id"]}, make_member_headers(m["id"])), 201
    )
    ms2 = validate_success(
        api.create_membership({"group_id": g2["id"]}, make_member_headers(m["id"])), 201
    )
    assert ms1["status"] == "APPROVED", "OPEN join policy must auto-approve inline"
    assert ms2["status"] == "REQUESTED", "APPROVAL_REQUIRED must leave the membership REQUESTED"
    g1_after = validate_success(api.get_group(g1["id"], make_member_headers(m["id"])), 200)
    g2_after = validate_success(api.get_group(g2["id"], make_admin_headers()), 200)
    assert g1_after["member_count"] == 1
    assert g2_after["member_count"] == 0


def test_membership_approve_after_reject_returns_not_requested(api, admin_headers):
    """PRD §3.1: "Approval by a moderator of that group (or a `PlatformAdmin`)
    requires the membership to still be `REQUESTED` — otherwise
    `ERR_MEMBERSHIP_NOT_REQUESTED`"

    Design: Corner/state_machines/membership_approve_after_reject_returns_not_requested
    """
    m = register_member("rjm@x.com", "M")
    group = create_group("Reject Group", "98206", join_policy="APPROVAL_REQUIRED")
    ms = join_group(m, group)
    assert ms["status"] == "REQUESTED"
    validate_success(api.reject_membership(ms["id"], admin_headers), 200)
    res = api.approve_membership(ms["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_REQUESTED, expected_status=409)
    after = validate_success(api.get_membership(ms["id"], admin_headers), 200)
    assert after["status"] == "REJECTED"


def test_membership_leave_after_reject_returns_not_approved(api):
    """PRD §3.1: "A member leaves their own `APPROVED` membership, moving it
    from `APPROVED` to `LEFT` — attempting to leave one not in `APPROVED` fails
    with `ERR_MEMBERSHIP_NOT_APPROVED`"

    Design: Corner/state_machines/membership_leave_after_reject_returns_not_approved
    """
    m = register_member("lv@x.com", "M")
    group = create_group("Leave Group", "98215", join_policy="APPROVAL_REQUIRED")
    ms = join_group(m, group)
    validate_success(api.reject_membership(ms["id"], make_admin_headers()), 200)
    res = api.leave_membership(ms["id"], make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_APPROVED, expected_status=409)


def test_group_full_boundary_rejects_third_approval(api, admin_headers):
    """PRD §3.1: "Approval by a moderator of that group (or a `PlatformAdmin`)
    requires the membership to still be `REQUESTED` — otherwise
    `ERR_MEMBERSHIP_NOT_REQUESTED` — and the roster to be `ACCEPTING`, since
    approving into a full roster fails with `ERR_GROUP_FULL`."
    PRD §3.1: "Group reads expose the computed roster fields — `member_count`
    (the number of memberships in `APPROVED` status) and `roster_status`, which
    reads `FULL` exactly when `member_count` has reached `capacity` and
    `ACCEPTING` otherwise"

    Design: Corner/validations/group_full_boundary_rejects_third_approval
    """
    m1 = register_member("gf1@x.com", "M1")
    m2 = register_member("gf2@x.com", "M2")
    m3 = register_member("gf3@x.com", "M3")
    group = create_group("Tiny Group", "98228", join_policy="APPROVAL_REQUIRED", capacity=2)
    ms1 = join_group(m1, group)
    ms2 = join_group(m2, group)
    ms3 = join_group(m3, group)
    validate_success(api.approve_membership(ms1["id"], admin_headers), 200)
    # Boundary: member_count 1 -> 2 with capacity 2 still succeeds.
    approved = validate_success(api.approve_membership(ms2["id"], admin_headers), 200)
    assert approved["status"] == "APPROVED"
    # member_count == capacity now; the third approve must be rejected.
    res = api.approve_membership(ms3["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_GROUP_FULL, expected_status=409)
    g_after = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert g_after["member_count"] == 2
    assert g_after["roster_status"] == "FULL"


def test_membership_approve_leave_conservation_counts(api, admin_headers):
    """PRD §3.1: "Group reads expose the computed roster fields — `member_count`
    (the number of memberships in `APPROVED` status) and `roster_status`, which
    reads `FULL` exactly when `member_count` has reached `capacity` and
    `ACCEPTING` otherwise"
    PRD §3.1: "Either way the group loses one approved member: `member_count`
    decreases by one, `roster_status` is recomputed, and the departing member's
    claims **in that group** that are still `QUEUED` or `OFFERED` move to
    `WITHDRAWN`, each withdrawal running the vacancy cascade of §3.3 on the
    affected post."

    Design: Difficulty/compensating_invariant/membership_approve_leave_conservation
    """
    set_clock("2026-05-10T09:00:00Z")
    m1 = register_member("im1@x.com", "M1")
    m2 = register_member("im2@x.com", "M2")
    m3 = register_member("im3@x.com", "M3")
    group = create_group("Invariant Group", "98116", join_policy="APPROVAL_REQUIRED")
    ms1 = join_group(m1, group)
    ms2 = join_group(m2, group)
    ms3 = join_group(m3, group)

    approve_membership_as_admin(ms1["id"])
    approve_membership_as_admin(ms2["id"])

    def approved_memberships():
        data, meta = validate_paginated(
            api.list_memberships(
                admin_headers, params={"group_id": group["id"], "status": "APPROVED"}
            )
        )
        return data, meta

    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    data, meta = approved_memberships()
    assert g["member_count"] == 2, f"after two approvals member_count must be 2, got {g['member_count']}"
    assert meta["total_count"] == 2
    assert len(data) == 2

    leave = validate_success(api.leave_membership(ms1["id"], make_member_headers(m1["id"])), 200)
    assert leave["status"] == "LEFT"
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    data, meta = approved_memberships()
    assert g["member_count"] == 1
    assert [x["id"] for x in data] == [ms2["id"]]

    approve_membership_as_admin(ms3["id"])
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    data, meta = approved_memberships()
    assert g["member_count"] == 2
    assert sorted(x["id"] for x in data) == sorted([ms2["id"], ms3["id"]])


def test_membership_approve_leave_conservation_leave_pair_reverses(api, admin_headers):
    """PRD §3.1: "Approval by a moderator of that group (or a `PlatformAdmin`)
    requires the membership to still be `REQUESTED` — otherwise
    `ERR_MEMBERSHIP_NOT_REQUESTED` — and the roster to be `ACCEPTING`, since
    approving into a full roster fails with `ERR_GROUP_FULL`."
    PRD §3.1: "Under an `OPEN` join policy the request is auto-approved inline:
    the membership is created directly in `APPROVED` status, `member_count`
    increases by one, and `roster_status` is recomputed"

    Second angle on the compensating pair: a single approve (+1) immediately
    followed by the same member's leave (-1) restores member_count to 0.

    Design: Difficulty/compensating_invariant/membership_approve_leave_conservation
    """
    set_clock("2026-05-10T09:00:00Z")
    m = register_member("im9@x.com", "M9")
    group = create_group("Invariant Group B", "98116", join_policy="APPROVAL_REQUIRED")
    ms = join_group(m, group)
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert g["member_count"] == 0

    approve_membership_as_admin(ms["id"])
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert g["member_count"] == 1, "approve must add exactly one approved member"

    validate_success(api.leave_membership(ms["id"], make_member_headers(m["id"])), 200)
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert g["member_count"] == 0, "the compensating leave must restore member_count to 0"
    data, meta = validate_paginated(
        api.list_memberships(admin_headers, params={"group_id": group["id"], "status": "APPROVED"})
    )
    assert meta["total_count"] == 0 and data == []


def test_immediate_consistency_on_membership_approve(api, admin_headers):
    """PRD §3.1: "Under an `OPEN` join policy the request is auto-approved
    inline: the membership is created directly in `APPROVED` status,
    `member_count` increases by one, and `roster_status` is recomputed"

    Design: Corner/consistency_model/immediate_consistency_on_membership_approve
    """
    m = register_member("icm@x.com", "M")
    group = create_group("Immediate Group", "98242", join_policy="APPROVAL_REQUIRED")
    ms = join_group(m, group)
    assert ms["status"] == "REQUESTED"
    approved = validate_success(api.approve_membership(ms["id"], admin_headers), 200)
    assert approved["status"] == "APPROVED", (
        "the approve response itself must carry APPROVED"
    )
    g = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert g["member_count"] == 1, (
        "the very next GET must already reflect member_count incremented"
    )


def test_groupmoderator_can_approve_membership(api):
    """PRD §2.1: "`GroupModerator` inherits member capabilities and additionally
    moderates memberships and reports within groups they moderate."
    PRD §3.1: "Approval may optionally assign a `role`; when omitted the member
    joins as `MEMBER`, and assigning `MODERATOR` at approval time is how the
    first moderators of a group come to be."

    Design: Corner/rbac/groupmoderator_can_approve_membership
    """
    mod = register_member("mod@x.com", "Mod")
    m2 = register_member("jm2@x.com", "M2")
    group = create_group("Mod Group", "98235", join_policy="APPROVAL_REQUIRED")
    ms_mod = join_group(mod, group)
    approve_membership_as_admin(ms_mod["id"], role="MODERATOR")
    ms2 = join_group(m2, group)
    res = api.approve_membership(ms2["id"], make_moderator_headers(mod["id"]))
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED", "moderator-authorized approve must succeed"
    g = validate_success(api.get_group(group["id"], make_admin_headers()), 200)
    assert g["member_count"] == 2
