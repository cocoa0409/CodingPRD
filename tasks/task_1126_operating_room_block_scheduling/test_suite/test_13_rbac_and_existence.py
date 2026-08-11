"""RBAC role boundaries, ownership enforcement, and resource-specific 404s."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_block_payload,
    create_case_payload,
    create_service_line_payload,
    create_surgeon_payload,
    create_vote_payload,
    make_case,
    make_line,
    make_surgeon,
    make_surgeon_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
NURSE = TEST_USERS["nurse_headers"]

MISSING_UUID = "11111111-2222-3333-4444-555555555555"


class TestRoleDenials:
    def test_surgeon_cannot_create_service_line(self, api):
        """PRD §2.1: "A request whose role may not perform the operation is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` — for example, a `SchedulingAdmin`
        attempting to cast a committee vote, a `CommitteeMember` attempting to
        reopen a review, or a `Surgeon` attempting to create a block."

        Design: Corner/validations/surgeon_cannot_create_service_line
        """
        surgeon = build_user_headers(MISSING_UUID, "Surgeon")
        res = api.create_service_line(
            create_service_line_payload(name="HACK", target_utilization_pct=75), surgeon
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert res.status_code == 403
        _, meta = validate_paginated(api.list_service_lines(ADMIN))
        assert meta["total_count"] == 0

    def test_committee_member_cannot_create_block(self, api):
        """PRD §2.1: "A `CommitteeMember` is a block-committee voting member: may
        cast and re-cast votes, but cannot reopen reviews and cannot allocate
        blocks."
        PRD §2.7: "2. **Role authorization** — the role is permitted for this
        endpoint, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to all
        endpoints" — evaluated before resource existence (rule 4).

        Design: Corner/rbac/committee_member_cannot_create_block
        """
        member = build_user_headers("cm_1", "CommitteeMember")
        res = api.create_block(
            create_block_payload(MISSING_UUID, MISSING_UUID,
                                 date="2026-05-04", start_minute=420, end_minute=720),
            member,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert res.status_code == 403

    def test_governance_segregation_of_duties(self, api):
        """PRD §2.1: "A request whose role may not perform the operation is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` — for example, a `SchedulingAdmin`
        attempting to cast a committee vote, a `CommitteeMember` attempting to
        reopen a review, or a `Surgeon` attempting to create a block."
        PRD §2.1: "A `BlockCommitteeChair` facilitates reviews: may reopen reviews
        decided as MAINTAIN, but cannot vote."

        Design: Corner/rbac/governance_segregation_of_duties
        """
        line = make_line()
        missing_review = "55555555-6666-7777-8888-999999999999"
        vote_payload = create_vote_payload("REDUCE", line["version"])

        admin_vote = api.cast_committee_vote(missing_review, vote_payload, ADMIN)
        validate_error(admin_vote, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert admin_vote.status_code == 403

        chair_vote = api.cast_committee_vote(
            missing_review, vote_payload, TEST_USERS["chair_headers"]
        )
        validate_error(chair_vote, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert chair_vote.status_code == 403

        member_reopen = api.reopen_committee_review(
            missing_review, build_user_headers("cm_1", "CommitteeMember")
        )
        validate_error(member_reopen, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert member_reopen.status_code == 403

    def test_case_lifecycle_role_boundaries(self, api):
        """PRD §2.1: "A `Surgeon` is an attending surgeon: posts and manages their
        own cases, requests open-time reallocation, and may release their own
        surgeon-specific blocks early." and "A `CirculatorNurse` is the OR
        circulator: records actual case start and completion times."

        Design: Corner/rbac/case_lifecycle_role_boundaries
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        case = make_case(surgeon["id"])

        nurse_posts = api.create_case(
            create_case_payload(surgeon["id"], procedure_class="MINOR"), NURSE
        )
        validate_error(nurse_posts, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert nurse_posts.status_code == 403

        surgeon_starts = api.start_case(
            case["id"], {"actual_start_minute": 420},
            make_surgeon_headers(surgeon["id"]),
        )
        validate_error(surgeon_starts, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert surgeon_starts.status_code == 403

        assert validate_success(api.get_case(case["id"], ADMIN), 200)["status"] == "POSTED"


class TestOwnership:
    def test_surgeon_cannot_cancel_another_surgeons_case(self, api):
        """PRD §2.7: "3. **Ownership** — a `Surgeon` may act only on their own
        cases, blocks, and requests: posting a case requires its `surgeon_id` to
        equal `X-User-ID`; scheduling, rescheduling, and cancelling a case require
        the caller to own it; ... Violations yield `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."

        Design: Corner/validations/surgeon_cannot_cancel_another_surgeons_case
        """
        line = make_line()
        surgeon_a = make_surgeon(line["id"], full_name="Dr. A")
        surgeon_b = make_surgeon(line["id"], full_name="Dr. B")
        case = make_case(surgeon_a["id"])

        res = api.cancel_case(case["id"], make_surgeon_headers(surgeon_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert res.status_code == 403
        assert validate_success(api.get_case(case["id"], ADMIN), 200)["status"] == "POSTED"


class TestExistenceErrors:
    def test_not_found_errors_on_reads(self, api, admin_headers):
        """PRD §2.7: "4. **Resource existence** — path identifiers are validated
        left to right, then body-referenced foreign keys in their declared order.
        Each missing resource yields its own 404: `ERR_SERVICE_LINE_NOT_FOUND`,
        `ERR_SURGEON_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
        `ERR_REQUEST_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

        Design: Corner/errors/not_found_errors_on_reads
        """
        case_res = api.get_case(MISSING_UUID, admin_headers)
        validate_error(case_res, ApiErrorId.ERR_CASE_NOT_FOUND)
        assert case_res.status_code == 404

        slot_res = api.get_open_time_slot(MISSING_UUID, admin_headers)
        validate_error(slot_res, ApiErrorId.ERR_SLOT_NOT_FOUND)
        assert slot_res.status_code == 404

    def test_not_found_errors_on_writes(self, api):
        """PRD §2.7: "4. **Resource existence** — path identifiers are validated
        left to right, then body-referenced foreign keys in their declared order.
        Each missing resource yields its own 404: `ERR_SERVICE_LINE_NOT_FOUND`,
        `ERR_SURGEON_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
        `ERR_REQUEST_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`. A request for a vote
        collection under a non-existent review, for example, fails on the review
        identifier before anything else is examined."

        Design: Corner/errors/not_found_errors_on_writes
        """
        line = make_line()

        res_line = api.create_surgeon(
            create_surgeon_payload(MISSING_UUID, full_name="Dr. X"), ADMIN
        )
        validate_error(res_line, ApiErrorId.ERR_SERVICE_LINE_NOT_FOUND)
        assert res_line.status_code == 404

        res_room = api.create_block(
            create_block_payload(line["id"], MISSING_UUID,
                                 date="2026-05-04", start_minute=420, end_minute=720),
            ADMIN,
        )
        validate_error(res_room, ApiErrorId.ERR_ROOM_NOT_FOUND)

        missing_surgeon = "22222222-3333-4444-5555-666666666666"
        res_surgeon = api.create_case(
            create_case_payload(missing_surgeon),
            make_surgeon_headers(missing_surgeon),
        )
        validate_error(res_surgeon, ApiErrorId.ERR_SURGEON_NOT_FOUND)

        res_cov = api.withdraw_anesthesia_coverage(
            "33333333-4444-5555-6666-777777777777", TEST_USERS["coordinator_headers"]
        )
        validate_error(res_cov, ApiErrorId.ERR_COVERAGE_NOT_FOUND)

        res_req = api.withdraw_reallocation_request(
            "44444444-5555-6666-7777-888888888888",
            make_surgeon_headers(missing_surgeon),
        )
        validate_error(res_req, ApiErrorId.ERR_REQUEST_NOT_FOUND)

        res_review = api.cast_committee_vote(
            "55555555-6666-7777-8888-999999999999",
            create_vote_payload("REDUCE", line["version"]),
            build_user_headers("cm_1", "CommitteeMember"),
        )
        validate_error(res_review, ApiErrorId.ERR_REVIEW_NOT_FOUND)
