"""Corner queue: committee charter/membership/dissolution and board seat appointment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    api_client,
    appoint_seat,
    appoint_seat_payload,
    assert_committee,
    charter_amendment_payload,
    create_and_open_motion,
    create_board_seat,
    create_committee,
    create_physician,
    create_policy,
    create_shareholder,
    dissolve_committee,
    get_board_seat,
    get_committee,
    table_motion,
    validate_error,
    validate_success,
    withdraw_motion,
)


class TestCommitteeCreateCharterInitialState:
    def test_new_committee_is_chartered(self, api):
        """PRD §3.3: "A new committee is `CHARTERED` with `charter_version` 1 and an
        empty `members` list."
        PRD §3.3: "Committee status is a compound, derived from `active_member_count`
        — the length of the members list — against `quorum_count`."

        Design: Corner/entities/committee_create_charter_initial_state
        """
        create_policy(total_shares_authorized=1000000)
        committee = create_committee(
            name="Finance Committee", committee_type="FINANCE",
            quorum_count=2, approval_threshold="SUPERMAJORITY",
        )
        assert_committee(committee)
        assert committee["status"] == "CHARTERED"
        assert committee["charter_version"] == 1
        assert committee["members"] == []
        assert committee["active_member_count"] == 0


class TestCommitteeDissolveBlockedWhileMotionOpen:
    def test_dissolve_blocked_then_unblocked_after_withdraw(self, api):
        """PRD §3.3: "Dissolution is available from `CHARTERED`, `ACTIVE`, or
        `IMPAIRED` — but only while no motion referencing the committee sits in `OPEN`
        or `TABLED` status, otherwise `ERR_INVALID_STATE` — and clears the members list
        as the committee becomes `DISSOLVED`."

        Design: Corner/state_machines/committee_dissolve_blocked_while_motion_open
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        committee = create_committee(name="Quality Committee", committee_type="QUALITY",
                                     quorum_count=1)
        add_member(committee["id"], a["id"], "MEMBER")
        motion = create_and_open_motion(
            "CHARTER_AMENDMENT", a, charter_amendment_payload(new_quorum_count=1),
            committee_id=committee["id"],
        )

        resp = api_client.dissolve_committee(committee["id"], TEST_USERS["board_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        table_motion(motion["id"], a)
        withdraw_motion(motion["id"], a)
        dissolved = dissolve_committee(committee["id"])
        assert dissolved["status"] == "DISSOLVED"
        assert dissolved["members"] == []


class TestCommitteeMembershipConstraints:
    def test_duplicate_chair_and_capacity_rejections(self, api):
        """PRD §3.3: "Adding a member is rejected when the committee already has
        `max_committee_members` members (`ERR_COMMITTEE_FULL`), when a `CHAIR` is added
        to a committee that already has one (`ERR_CHAIR_ALREADY_ASSIGNED`), or when the
        physician is already a member (`ERR_DUPLICATE_MEMBERSHIP`)."
        PRD §2.8: "`max_committee_members` (default 7)"

        Design: Corner/state_machines/committee_membership_constraints
        """
        create_policy(total_shares_authorized=1000000)
        physicians = [
            create_shareholder(f"Dr P{i}", 100, f"2010-01-0{i}T00:00:00Z")
            for i in range(1, 9)
        ]
        committee = create_committee(name="Comp", committee_type="COMPENSATION", quorum_count=1)
        add_member(committee["id"], physicians[0]["id"], "CHAIR")

        resp = api_client.add_committee_member(
            committee["id"], {"physician_id": physicians[0]["id"], "committee_role": "MEMBER"},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

        resp = api_client.add_committee_member(
            committee["id"], {"physician_id": physicians[1]["id"], "committee_role": "CHAIR"},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CHAIR_ALREADY_ASSIGNED)

        for p in physicians[1:7]:
            add_member(committee["id"], p["id"], "MEMBER")
        resp = api_client.add_committee_member(
            committee["id"], {"physician_id": physicians[7]["id"], "committee_role": "MEMBER"},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_FULL)
        assert get_committee(committee["id"])["active_member_count"] == 7


class TestSeatAppointNonShareholderRejected:
    def test_associate_cannot_hold_seat(self, api):
        """PRD §3.3: "Appointing into a `VACANT` seat requires the holder physician to
        be a `SHAREHOLDER` who is not `SUSPENDED` (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/seat_appoint_non_shareholder_rejected
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        seat = create_board_seat("SEAT-2", "EX_OFFICIO")
        resp = api_client.appoint_board_seat(
            seat["id"],
            appoint_seat_payload(p["id"], term_start="2026-08-01T00:00:00Z",
                                 term_end="2029-08-01T00:00:00Z"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_board_seat(seat["id"])["status"] == "VACANT"


class TestSeatTermWindowInvalid:
    def test_empty_term_window_rejected(self, api):
        """PRD §3.3: "the term window must be well-formed: `term_end` strictly after
        `term_start` (`ERR_TERM_WINDOW_INVALID`)"

        Design: Corner/validations/seat_term_window_invalid_rejected
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        seat = create_board_seat("SEAT-3", "CLINICAL")
        resp = api_client.appoint_board_seat(
            seat["id"],
            appoint_seat_payload(a["id"], term_start="2026-08-01T00:00:00Z",
                                 term_end="2026-08-01T00:00:00Z"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TERM_WINDOW_INVALID)
        assert get_board_seat(seat["id"])["status"] == "VACANT"
