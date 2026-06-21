"""Membership activation: capacity gate, single-occupancy overlap, derived count.

Translates queue-A cross_entity_state_dependency (capacity) and
resource_temporal_overlap (occupancy) instances, plus queue-B corner instances
for derived active_member_count and the non-manager ownership denial.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    create_match_request_payload,
    create_profile,
    create_listing,
    build_household_with_members,
)

api = api_client


def _activate_third_member_blocked_setup():
    """Capacity-2 listing, M1 & M2 ACTIVE, M3 PENDING. Returns (env, mem3_id, lister_headers)."""
    lister = create_profile(api, full_name="L13")
    listing = create_listing(api, lister, capacity=2, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    lh = make_roommate_headers(lister["id"])

    household_id = None
    members = []
    for name in ("M1", "M2", "M3"):
        member = create_profile(api, full_name=name)
        members.append(member)
        mr = get_success_data(
            api.create_match_request(
                create_match_request_payload(listing["id"], member["id"]),
                make_roommate_headers(member["id"]),
            )
        )
        get_success_data(api.accept_match_request(mr["id"], lh))
        if household_id is None:
            household_id = get_success_data(
                api.list_households(lh, params={"manager_id": lister["id"]})
            )[0]["id"]
        mem = get_success_data(
            api.list_memberships(lh, params={"profile_id": member["id"], "household_id": household_id})
        )[0]
        if name in ("M1", "M2"):
            get_success_data(api.activate_membership(mem["id"], lh))
        else:
            mem3_id = mem["id"]
    return mem3_id, lh


def test_activation_blocked_when_room_at_capacity():
    """PRD §3.3: "the household's `active_member_count` must be strictly below the
    listing's `capacity`; an activation that would push the count to or past capacity is
    rejected with `ERR_ROOM_AT_CAPACITY`."

    Design: Difficulty/cross_entity_state_dependency/membership_activate_blocked_by_room_capacity
    """
    mem3_id, lh = _activate_third_member_blocked_setup()
    resp = api.activate_membership(mem3_id, lh)
    validate_error(resp, ApiErrorId.ERR_ROOM_AT_CAPACITY.value)


def test_activation_blocked_at_capacity_three():
    """PRD §3.3: "the household's `active_member_count` must be strictly below the
    listing's `capacity`; an activation that would push the count to or past capacity is
    rejected with `ERR_ROOM_AT_CAPACITY`."

    A capacity-3 room with M1, M2, M3 already ACTIVE rejects activating a fourth member.

    Design: Difficulty/cross_entity_state_dependency/membership_activate_blocked_by_room_capacity
    """
    lister = create_profile(api, full_name="L13b")
    listing = create_listing(api, lister, capacity=3, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    lh = make_roommate_headers(lister["id"])
    household_id = None
    fourth_mem_id = None
    for name in ("A1", "A2", "A3", "A4"):
        member = create_profile(api, full_name=name)
        mr = get_success_data(
            api.create_match_request(
                create_match_request_payload(listing["id"], member["id"]),
                make_roommate_headers(member["id"]),
            )
        )
        get_success_data(api.accept_match_request(mr["id"], lh))
        if household_id is None:
            household_id = get_success_data(
                api.list_households(lh, params={"manager_id": lister["id"]})
            )[0]["id"]
        mem = get_success_data(
            api.list_memberships(lh, params={"profile_id": member["id"], "household_id": household_id})
        )[0]
        if name == "A4":
            fourth_mem_id = mem["id"]
        else:
            get_success_data(api.activate_membership(mem["id"], lh))

    resp = api.activate_membership(fourth_mem_id, lh)
    validate_error(resp, ApiErrorId.ERR_ROOM_AT_CAPACITY.value)


def test_active_member_count_recomputed_and_household_activates():
    """PRD §3.3: "When activation succeeds, the membership moves from `PENDING` to
    `ACTIVE` and the cascade runs. The household's `active_member_count` is recomputed
    from its `ACTIVE` memberships. If the household was `FORMING`, it advances to
    `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/derived_active_member_count_after_activation
    """
    lister = create_profile(api, full_name="AmcL")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    lh = make_roommate_headers(lister["id"])
    m1 = create_profile(api, full_name="AmcM1")
    mr = get_success_data(
        api.create_match_request(
            create_match_request_payload(listing["id"], m1["id"]),
            make_roommate_headers(m1["id"]),
        )
    )
    get_success_data(api.accept_match_request(mr["id"], lh))
    household_id = get_success_data(api.list_households(lh, params={"manager_id": lister["id"]}))[0]["id"]
    mem = get_success_data(
        api.list_memberships(lh, params={"profile_id": m1["id"], "household_id": household_id})
    )[0]

    validate_success(api.activate_membership(mem["id"], lh))
    household = validate_success(api.get_household(household_id, lh))
    assert household["active_member_count"] == 1
    assert household["status"] == "ACTIVE"


def test_non_manager_cannot_activate_membership():
    """PRD §3.3: "Activation is performed by the household's manager. The acting
    roommate must be the `manager_id` of the membership's household, and the household
    must be in `FORMING` or `ACTIVE` status."
    PRD §2.1: "When the caller holds the correct role but is not the specific owner,
    manager, or party that the operation requires, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/non_manager_cannot_activate_membership
    """
    lister = create_profile(api, full_name="OwnL")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    lh = make_roommate_headers(lister["id"])
    m1 = create_profile(api, full_name="OwnM1")
    stranger = create_profile(api, full_name="OwnZ")
    mr = get_success_data(
        api.create_match_request(
            create_match_request_payload(listing["id"], m1["id"]),
            make_roommate_headers(m1["id"]),
        )
    )
    get_success_data(api.accept_match_request(mr["id"], lh))
    household_id = get_success_data(api.list_households(lh, params={"manager_id": lister["id"]}))[0]["id"]
    mem = get_success_data(
        api.list_memberships(lh, params={"profile_id": m1["id"], "household_id": household_id})
    )[0]

    resp = api.activate_membership(mem["id"], make_roommate_headers(stranger["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_activate_unknown_membership_returns_not_found():
    """PRD §2.5: "the first identifier in the path that does not resolve to an existing
    resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before
    any deeper lookup or business rule is attempted."
    PRD §2.11: "Existence of every referenced resource (`ERR_NOT_FOUND`) is checked next,
    then whether the target is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."

    Design: Corner/validations/existence_before_state_on_unknown_membership
    """
    actor = create_profile(api, full_name="ExstL")
    resp = api.activate_membership(
        "00000000-0000-0000-0000-000000000000", make_roommate_headers(actor["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
