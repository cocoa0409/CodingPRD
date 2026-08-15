"""Member enrollment, roster visibility, and member lifecycle rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    assert_member,
    create_member_payload,
    create_officer,
    get_success_data,
    make_officer_headers,
    setup_group_with_registered_block,
    setup_operational_group,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestRosterDefaults:
    def test_member_roster_visibility_defaults_to_group_only(self, api):
        """PRD §3.2: "optionally a `roster_visibility` that defaults to
        `GROUP_ONLY` when omitted."

        Design: Corner/entities/member_roster_visibility_default_group_only
        """
        group, block = setup_group_with_registered_block(
            "Vis Watch", "D03", "2-2 Test Ln", 3,
        )
        member = validate_success(
            api.create_member(
                create_member_payload(group["id"], block["id"],
                                      full_name="Vis M", contact_channel="EMAIL"),
                COORD,
            ),
            201,
        )
        assert_member(member)
        fetched = validate_success(api.get_member(member["id"], COORD))
        assert fetched["roster_visibility"] == "GROUP_ONLY"


class TestMemberSuspension:
    def test_double_suspend_returns_invalid_state(self, api):
        """PRD §2.6: "fourth, whether the target resource is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`)"
        PRD §3.2: "A member's lifecycle runs from `ACTIVE` to `SUSPENDED` or
        `WITHDRAWN` (terminal)."

        Design: Corner/state_machines/member_double_suspend_returns_invalid_state
        """
        ws = setup_operational_group("Idem Watch", "S03",
                                     member_channels=("SMS",),
                                     badge_number="BS03")
        member = ws["members"][0]
        first = validate_success(api.suspend_member(member["id"], COORD))
        assert first["membership_status"] == "SUSPENDED"

        resp = api.suspend_member(member["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_member(member["id"], COORD))
        assert after["membership_status"] == "SUSPENDED", (
            "The rejected second suspension leaves the member untouched"
        )


class TestPostureGateOnMemberWrites:
    def test_member_create_rejected_while_group_frozen(self, api):
        """PRD §3.2: "Enrollment, like every member write, is gated by posture:
        while the group's posture is `FROZEN`, member creation is rejected with
        `ERR_POSTURE_GATED`."
        PRD §3.8: "a coordinator may freeze a group whose `certification_status`
        is `SUSPENDED`, moving posture from `OPERATIONAL`, `DEGRADED`, or
        `FORMATION` to `FROZEN`."

        Design: Corner/validations/posture_gate_member_create_while_frozen
        """
        group, block = setup_group_with_registered_block(
            "Gate2 Watch", "V01", "1-1 Val St", 4,
        )
        suspended = validate_success(api.suspend_certification(group["id"], COORD))
        assert suspended["certification_status"] == "SUSPENDED"
        frozen = validate_success(api.freeze_watch_group(group["id"], COORD))
        assert frozen["posture"] == "FROZEN"

        resp = api.create_member(
            create_member_payload(group["id"], block["id"],
                                  full_name="Frozen M", contact_channel="SMS"),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_GATED)


class TestLiaisonRosterScoping:
    def test_liaison_officer_listing_sees_only_liaison_visible_members(self, api):
        """PRD §2.12: "A `LiaisonOfficer` listing members sees only those marked
        `LIAISON_VISIBLE` or `PROGRAM_WIDE`, unless the group holds an `ACTIVE`
        data-sharing agreement whose `scope` is `ROSTER_CONTACTS` or `FULL`, in
        which case the roster opens to the officer."

        Design: Corner/rbac/liaison_roster_visibility_scoping
        """
        group, block = setup_group_with_registered_block(
            "Scope Watch", "R04", "3-3 Scope St", 4,
        )
        visible = add_member(group["id"], block["id"], "Vis One", "SMS",
                             roster_visibility="LIAISON_VISIBLE")
        hidden = add_member(group["id"], block["id"], "Hid Two", "EMAIL")
        officer = create_officer("BR04", "Officer Sc", "R04")

        data, meta = validate_paginated(
            api.list_members(make_officer_headers(officer["id"]),
                             params={"watch_group_id": group["id"]})
        )
        ids = {m["id"] for m in data}
        assert meta["total_count"] == 1, (
            "Without an ACTIVE roster agreement the officer sees only "
            "LIAISON_VISIBLE/PROGRAM_WIDE members"
        )
        assert visible["id"] in ids and hidden["id"] not in ids

        _, meta_coord = validate_paginated(
            api.list_members(COORD, params={"watch_group_id": group["id"]})
        )
        assert meta_coord["total_count"] == 2, (
            "The coordinator's roster read is unscoped"
        )
