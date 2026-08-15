"""Mentoring engagements: buffered-window conflicts, sponsor capacity, the
single-engagement rule for mentees, and the self-pairing prohibition."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_engagement,
    create_mentoring_engagement_payload,
    create_open_program,
    create_sponsor,
    make_employee_headers,
    make_sponsor_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestBufferedWindow:
    def test_start_inside_buffer_rejected(self, api):
        """PRD §3.10: "Finally, a buffered-window conflict check runs per sponsor over their `PROPOSED` and `ACTIVE` engagements: a new engagement conflicts when it starts before the existing engagement's `ends_at` plus 14 days and the existing engagement starts before the new one's `ends_at` plus 14 days — a start exactly 14 days after an existing engagement's end is allowed. A conflict is rejected with `ERR_MENTORING_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/mentoring_buffered_window
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_spm", max_groups=3, max_mentees=3)
        create_engagement(program["id"], sponsor["id"], "emp_m1",
                          "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")

        # 2026-09-28 is one day inside the 14-day post-buffer of the
        # 2026-09-15-ending engagement (buffer runs to 2026-09-29).
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor["id"],
                "2026-09-28T00:00:00Z", "2026-10-12T00:00:00Z",
            ),
            make_employee_headers("emp_m2"),
        )
        validate_error(resp, ApiErrorId.ERR_MENTORING_WINDOW_CONFLICT.value, 409)

    def test_start_exactly_at_buffer_end_allowed(self, api):
        """PRD §3.10: "Finally, a buffered-window conflict check runs per sponsor over their `PROPOSED` and `ACTIVE` engagements: a new engagement conflicts when it starts before the existing engagement's `ends_at` plus 14 days and the existing engagement starts before the new one's `ends_at` plus 14 days — a start exactly 14 days after an existing engagement's end is allowed. A conflict is rejected with `ERR_MENTORING_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/mentoring_buffered_window
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_spm", max_groups=3, max_mentees=3)
        create_engagement(program["id"], sponsor["id"], "emp_m1",
                          "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")

        # 2026-09-29 is exactly ends_at + 14 days: allowed.
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor["id"],
                "2026-09-29T00:00:00Z", "2026-10-13T00:00:00Z",
            ),
            make_employee_headers("emp_m2"),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PROPOSED"


class TestCapacityGates:
    def test_sponsor_at_max_mentees_rejected_and_decline_frees_slot(self, api):
        """PRD §3.10: "Two capacity gates follow: the sponsor's count of engagements in `PROPOSED` or `ACTIVE` status must be strictly below their `max_mentees` (`ERR_SPONSOR_CAPACITY_EXCEEDED`), and the mentee must have no engagement in `PROPOSED` or `ACTIVE` status at all (`ERR_MENTEE_ALREADY_ENGAGED`)."
        PRD §3.10: "The named sponsor decides: a `decision` of `ACCEPT` moves `PROPOSED` → `ACTIVE`, and a `decision` of `DECLINE` moves `PROPOSED` → `DECLINED`."

        Design: Corner/validations/mentoring_capacity_and_mentee_single_engagement
        """
        program = create_open_program(100000)
        sponsor_a = create_sponsor("emp_sa", max_groups=3, max_mentees=1)
        e1 = create_engagement(program["id"], sponsor_a["id"], "emp_m1",
                               "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")

        # spA is already at max_mentees 1 with the PROPOSED engagement.
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor_a["id"],
                "2026-10-01T00:00:00Z", "2026-10-15T00:00:00Z",
            ),
            make_employee_headers("emp_m2"),
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_CAPACITY_EXCEEDED.value, 409)

        # DECLINE moves the engagement out of the counted statuses.
        data = validate_success(
            api.mentoring_sponsor_decision(
                e1["id"], {"decision": "DECLINE"}, make_sponsor_headers(sponsor_a["id"])
            ),
            200,
        )
        assert data["status"] == "DECLINED"

        # The freed slot accepts the previously rejected proposal.
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor_a["id"],
                "2026-10-01T00:00:00Z", "2026-10-15T00:00:00Z",
            ),
            make_employee_headers("emp_m2"),
        )
        validate_success(resp, 201)

    def test_mentee_with_live_engagement_cannot_be_proposed_again(self, api):
        """PRD §3.10: "Two capacity gates follow: the sponsor's count of engagements in `PROPOSED` or `ACTIVE` status must be strictly below their `max_mentees` (`ERR_SPONSOR_CAPACITY_EXCEEDED`), and the mentee must have no engagement in `PROPOSED` or `ACTIVE` status at all (`ERR_MENTEE_ALREADY_ENGAGED`)."

        Design: Corner/validations/mentoring_capacity_and_mentee_single_engagement
        """
        program = create_open_program(100000)
        sponsor_a = create_sponsor("emp_sa", max_groups=3, max_mentees=1)
        sponsor_b = create_sponsor("emp_sb", max_groups=3, max_mentees=2)
        create_engagement(program["id"], sponsor_a["id"], "emp_m1",
                          "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")

        # emp_m1 already has a PROPOSED engagement; a different sponsor's
        # proposal for the same mentee is still rejected.
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor_b["id"],
                "2026-11-01T00:00:00Z", "2026-11-15T00:00:00Z",
            ),
            make_employee_headers("emp_m1"),
        )
        validate_error(resp, ApiErrorId.ERR_MENTEE_ALREADY_ENGAGED.value, 409)


class TestSelfPairing:
    def test_mentoring_self_pairing_rejected(self, api):
        """PRD §3.10: "Self-pairing is forbidden: a sponsor whose `employee_id` equals the mentee's is rejected with `ERR_MENTORING_SELF_PAIRING` (HTTP 400)."

        Design: Corner/validations/mentoring_self_pairing_rejected
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_self", max_groups=3, max_mentees=2)
        resp = api.create_mentoring_engagement(
            create_mentoring_engagement_payload(
                program["id"], sponsor["id"],
                "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z",
                mentee_employee_id="emp_self",
            ),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_MENTORING_SELF_PAIRING.value, 400)
