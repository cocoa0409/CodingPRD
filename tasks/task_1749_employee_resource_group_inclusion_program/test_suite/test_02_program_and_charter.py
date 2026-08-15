"""Program setup and group chartering: defaults, gates, uniqueness, sponsor
assignment, charter review loop, RBAC, and terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_sponsor_to_group,
    create_engagement,
    create_group_draft,
    create_group_payload,
    create_open_program,
    create_program,
    create_sponsor,
    create_survey,
    make_employee_headers,
    make_group_leader_headers,
    make_sponsor_headers,
    open_program,
    submit_charter,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS, add_members, sponsor_endorse_charter


class TestProgramLifecycle:
    def test_create_program_applies_defaults(self, api):
        """PRD §3.1: "A new program starts in `status` `SETUP` with `posture` `NORMAL`, and its `unallocated_pool_cents` is the full pool since no group has been allocated anything yet."

        Design: Corner/entities/create_program_applies_defaults
        """
        resp = api.create_program({"fiscal_year": 2027, "pool_total_cents": 250000}, DEI_HEADERS)
        data = validate_success(resp, 201)
        assert data["status"] == "SETUP"
        assert data["posture"] == "NORMAL"
        assert data["unallocated_pool_cents"] == 250000
        assert data["version"] == 1

    def test_group_create_requires_open_program(self, api):
        """PRD §3.1: "Chartering, membership, and funding activity all require the program to be `OPEN` (or `ALLOCATION_LOCKED` for some flows, noted where relevant), and operations that require one of those two statuses reject a `SETUP` program with `ERR_PROGRAM_NOT_OPEN`."

        Design: Corner/validations/group_create_requires_open_program
        """
        program = create_program(100000)  # stays SETUP
        resp = api.create_group(
            create_group_payload(program["id"], "Too Soon", "m", "AFFINITY"),
            make_group_leader_headers("emp_l57"),
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN.value, 409)

    def test_create_group_invalid_enum_returns_400(self, api):
        """PRD §2.6: "3. **Request schema** — required fields present, types and enum values valid, numeric ranges valid such as `capacity` greater than zero, `ends_at` strictly after `starts_at`, survey scores inside the 1-to-5 range (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/validations/create_group_invalid_enum_returns_400
        """
        program = create_open_program(100000)
        resp = api.create_group(
            create_group_payload(program["id"], "Bad Enum", "m", "NOT_A_CATEGORY"),
            make_group_leader_headers("emp_l37"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_initial_states_on_creation(self, api):
        """PRD §3.2: "The group starts in `CHARTER_DRAFT` with `allocated_cents`, `reserved_cents`, and `spent_cents` all zero, with `founding_member_count` and `certified_standing_score` null, and with `sponsor_id` null."
        PRD §3.9: "The survey starts in `DRAFT` with `response_count` zero and both indices null."
        PRD §3.10: "A new engagement starts in `PROPOSED`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp23", max_groups=3, max_mentees=2)

        group = create_group_draft(program["id"], "Init States", "AFFINITY", "emp_l30")
        assert group["status"] == "CHARTER_DRAFT"

        survey = create_survey(program["id"], title="S", min_responses=1)
        assert survey["status"] == "DRAFT"

        engagement = create_engagement(
            program["id"], sponsor["id"], "emp_m5",
            starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-15T00:00:00Z",
        )
        assert engagement["status"] == "PROPOSED"


class TestCharterSubmissionGates:
    def test_charter_submit_without_sponsor_rejected(self, api):
        """PRD §3.2: "Submission requires three conditions — the group has an assigned sponsor (`ERR_CHARTER_NO_SPONSOR` if `sponsor_id` is still null), the group has at least 10 active members (`ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS` when `active_member_count` is below 10), and the group is in `CHARTER_DRAFT` or `CHANGES_REQUESTED` — and moves the group to `SUBMITTED`, incrementing `version` by 1."

        Design: Corner/validations/charter_submit_without_sponsor_rejected
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Sponsorless", "AFFINITY", "emp_l40")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        resp = api.submit_charter(group["id"], make_group_leader_headers("emp_l40"))
        validate_error(resp, ApiErrorId.ERR_CHARTER_NO_SPONSOR.value, 409)

    def test_charter_submit_nine_members_boundary(self, api):
        """PRD §3.2: "Submission requires three conditions — the group has an assigned sponsor (`ERR_CHARTER_NO_SPONSOR` if `sponsor_id` is still null), the group has at least 10 active members (`ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS` when `active_member_count` is below 10), and the group is in `CHARTER_DRAFT` or `CHANGES_REQUESTED` — and moves the group to `SUBMITTED`, incrementing `version` by 1."

        Design: Corner/validations/charter_submit_nine_members_boundary
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp27", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "Nine Only", "AFFINITY", "emp_l39")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 10)])  # 9 members
        group = assign_sponsor_to_group(group, sponsor["id"])

        # 9 active members is below the founding minimum of 10.
        resp = api.submit_charter(group["id"], make_group_leader_headers("emp_l39"))
        validate_error(resp, ApiErrorId.ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS.value, 409)

        # The 10th member tips the boundary; the identical call now succeeds.
        add_members(group["id"], ["emp_f10"])
        resp = api.submit_charter(group["id"], make_group_leader_headers("emp_l39"))
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED"

    def test_group_name_not_unique_rejected(self, api):
        """PRD §3.2: "A `GroupLeader` (or a `DeiAdmin` acting on someone's behalf) drafts a charter by creating an `ErgGroup` inside a program: the payload carries the `program_id`, a `name` that must be unique within the program case-sensitively across non-terminal groups (violations surface as `ERR_GROUP_NAME_NOT_UNIQUE`), a `mission_statement`, and a `category` of `AFFINITY`, `PROFESSIONAL`, or `COMMUNITY_OUTREACH`."

        Design: Corner/validations/group_name_not_unique_rejected
        """
        program = create_open_program(100000)
        create_group_draft(program["id"], "Unique Name", "AFFINITY", "emp_l41")
        resp = api.create_group(
            create_group_payload(program["id"], "Unique Name", "m2", "PROFESSIONAL"),
            make_group_leader_headers("emp_l42"),
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NAME_NOT_UNIQUE.value, 409)


class TestSponsorAssignment:
    def test_sponsor_group_capacity_boundary(self, api):
        """PRD §3.2: "Three gates apply, in addition to the version check: the sponsor must exist and be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`); the sponsor's current load — the count of groups assigned to that sponsor in any of `CHARTER_DRAFT`, `SUBMITTED`, `SPONSOR_ENDORSED`, `CHANGES_REQUESTED`, `ACTIVE`, or `SUSPENDED` status — must be strictly below the sponsor's `max_groups` (`ERR_SPONSOR_CAPACITY_EXCEEDED`); and the group must currently be in `CHARTER_DRAFT`, `CHANGES_REQUESTED`, or `ACTIVE` (from any other state the assignment is rejected with `ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/validations/sponsor_group_capacity_boundary
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp31", max_groups=1, max_mentees=2)
        g1 = create_group_draft(program["id"], "Cap One", "AFFINITY", "emp_l46")
        g2 = create_group_draft(program["id"], "Cap Two", "AFFINITY", "emp_l47")

        # max_groups 1: the first assignment succeeds.
        resp = api.assign_sponsor(
            g1["id"],
            {"sponsor_id": sponsor["id"], "expected_group_version": g1["version"]},
            DEI_HEADERS,
        )
        data = validate_success(resp, 200)
        assert data["sponsor_id"] == sponsor["id"]

        # The second assignment would push the load to the cap.
        resp = api.assign_sponsor(
            g2["id"],
            {"sponsor_id": sponsor["id"], "expected_group_version": g2["version"]},
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_CAPACITY_EXCEEDED.value, 409)

    def test_occ_stale_group_version_on_assign_sponsor(self, api):
        """PRD §2.7: "Sponsor assignment on a group requires a non-optional `expected_group_version` carrying the client's last observed `version` of that `ErgGroup`. If the group's version has advanced since the client last read it, the assignment is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412)."
        PRD §2.7: "Reassignment legitimately supersedes the prior assignment while the group is in `CHARTER_DRAFT`, `CHANGES_REQUESTED`, or `ACTIVE`, so the stale-write guard is expressed purely as a version check: a second assignment carrying the previously observed version must fail."

        Design: Corner/cross_cutting_layers/occ_stale_group_version_on_assign_sponsor
        """
        program = create_open_program(100000)
        spa = create_sponsor("emp_sa3", max_groups=3, max_mentees=2)
        spb = create_sponsor("emp_sb3", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "OCC Group", "AFFINITY", "emp_l61")
        observed_version = group["version"]

        resp = api.assign_sponsor(
            group["id"],
            {"sponsor_id": spa["id"], "expected_group_version": observed_version},
            DEI_HEADERS,
        )
        data = validate_success(resp, 200)
        assert data["version"] == observed_version + 1

        # The second assignment carries the now-stale pre-write version.
        resp = api.assign_sponsor(
            group["id"],
            {"sponsor_id": spb["id"], "expected_group_version": observed_version},
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_GROUP_VERSION.value, 412)


class TestCharterReview:
    def test_wrong_sponsor_cannot_endorse_charter(self, api):
        """PRD §3.2: "The sponsor's `X-User-ID` must match the group's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`)."

        Design: Corner/validations/wrong_sponsor_cannot_endorse_charter
        """
        program = create_open_program(100000)
        spa = create_sponsor("emp_sa2", max_groups=3, max_mentees=2)
        spb = create_sponsor("emp_sb2", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "Assigned Only", "AFFINITY", "emp_l56")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, spa["id"])
        submit_charter(group["id"], "emp_l56")

        resp = api.group_sponsor_decision(
            group["id"], {"decision": "ENDORSE"}, make_sponsor_headers(spb["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ASSIGNED.value, 409)

    def test_charter_rejected_is_terminal(self, api):
        """PRD §3.2: "On an endorsed charter, a `DeiAdmin` `decision` of `APPROVE` moves the group `SPONSOR_ENDORSED` → `ACTIVE` and snapshots `founding_member_count` to the group's `active_member_count` at that moment; a `decision` of `REJECT` moves it `SPONSOR_ENDORSED` → `CHARTER_REJECTED`, a terminal state."
        PRD §2.6: "6. **Lifecycle state gates** — the target resource's current state permits the transition, including terminal-state lockdown (state-category errors such as `ERR_INVALID_STATE_TRANSITION`, `ERR_GROUP_NOT_ACTIVE`, `ERR_PROGRAM_NOT_OPEN`, `ERR_PROGRAM_IN_CLIMATE_REVIEW`, `ERR_ALLOCATION_NOT_LOCKED`, `ERR_SURVEY_NOT_OPEN`, `ERR_EVENT_NOT_PUBLISHED`, `ERR_SPONSOR_NOT_ACTIVE`, `ERR_LEADERSHIP_GAP`, 409)."

        Design: Corner/state_machines/charter_rejected_is_terminal
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp19", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "Terminal Group", "AFFINITY", "emp_l25")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, sponsor["id"])
        submit_charter(group["id"], "emp_l25")
        sponsor_endorse_charter(group["id"], sponsor["id"])
        resp = api.group_dei_decision(group["id"], {"decision": "REJECT"}, DEI_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CHARTER_REJECTED"

        resp = api.submit_charter(group["id"], make_group_leader_headers("emp_l25"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    def test_charter_revision_loop_statuses(self, api):
        """PRD §3.2: "A `decision` of `ENDORSE` moves the group `SUBMITTED` → `SPONSOR_ENDORSED`; a `decision` of `REQUEST_CHANGES`, optionally annotated with a `change_note`, moves it `SUBMITTED` → `CHANGES_REQUESTED`."
        PRD §3.2: "The revision loop `SUBMITTED` → `CHANGES_REQUESTED` → `SUBMITTED` may repeat without bound while the owner refines the charter."

        Design: Difficulty/non_linear_state_machine/charter_changes_requested_cycle
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp6", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "Cycle Group", "AFFINITY", "emp_l6")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, sponsor["id"])

        data = validate_success(
            api.submit_charter(group["id"], make_group_leader_headers("emp_l6")), 200
        )
        assert data["status"] == "SUBMITTED"

        data = validate_success(
            api.group_sponsor_decision(
                group["id"],
                {"decision": "REQUEST_CHANGES", "change_note": "Clarify membership criteria"},
                make_sponsor_headers(sponsor["id"]),
            ),
            200,
        )
        assert data["status"] == "CHANGES_REQUESTED"

        # Second pass through the revision loop.
        data = validate_success(
            api.submit_charter(group["id"], make_group_leader_headers("emp_l6")), 200
        )
        assert data["status"] == "SUBMITTED"

        data = validate_success(
            api.group_sponsor_decision(
                group["id"], {"decision": "ENDORSE"}, make_sponsor_headers(sponsor["id"])
            ),
            200,
        )
        assert data["status"] == "SPONSOR_ENDORSED"

        data = validate_success(
            api.group_dei_decision(group["id"], {"decision": "APPROVE"}, DEI_HEADERS), 200
        )
        assert data["status"] == "ACTIVE"

    def test_charter_approval_snapshots_founding_members(self, api):
        """PRD §3.2: "On an endorsed charter, a `DeiAdmin` `decision` of `APPROVE` moves the group `SPONSOR_ENDORSED` → `ACTIVE` and snapshots `founding_member_count` to the group's `active_member_count` at that moment; a `decision` of `REJECT` moves it `SPONSOR_ENDORSED` → `CHARTER_REJECTED`, a terminal state."

        Design: Difficulty/non_linear_state_machine/charter_changes_requested_cycle
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp6", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "Cycle Group", "AFFINITY", "emp_l6")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, sponsor["id"])
        submit_charter(group["id"], "emp_l6")
        api.group_sponsor_decision(
            group["id"],
            {"decision": "REQUEST_CHANGES", "change_note": "Clarify membership criteria"},
            make_sponsor_headers(sponsor["id"]),
        )
        submit_charter(group["id"], "emp_l6")
        sponsor_endorse_charter(group["id"], sponsor["id"])
        data = validate_success(
            api.group_dei_decision(group["id"], {"decision": "APPROVE"}, DEI_HEADERS), 200
        )
        assert data["status"] == "ACTIVE"
        assert data["founding_member_count"] == 10


class TestRbac:
    def test_employee_cannot_decide_charter(self, api):
        """PRD §2.1: "A caller whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/employee_cannot_decide_charter
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp38", max_groups=3, max_mentees=2)
        group = create_group_draft(program["id"], "RBAC Group", "AFFINITY", "emp_l59")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, sponsor["id"])
        submit_charter(group["id"], "emp_l59")

        # dei-decision is DeiAdmin-exclusive; an Employee caller is rejected.
        resp = api.group_dei_decision(
            group["id"], {"decision": "APPROVE"}, make_employee_headers("emp_f01")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_sponsor_cannot_create_program(self, api):
        """PRD §2.1: "A caller whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/sponsor_cannot_create_program
        """
        sponsor = create_sponsor("emp_sp39", max_groups=3, max_mentees=2)
        # Program creation is DeiAdmin-exclusive.
        resp = api.create_program(
            {"fiscal_year": 2028, "pool_total_cents": 100000},
            make_sponsor_headers(sponsor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
