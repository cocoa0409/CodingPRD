"""Benefit applications (PRD §2.3, §3.5): the appeal re-file cycle,
member-scope and work-eligibility rules, and filtered pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    date_part,
    make_case, add_member,
    setup_arrived_case, set_clock,
    make_benefit_application, transition_application,
)
from test_helpers.fixtures import CM


_ADULT = {"full_name": "Adult", "date_of_birth": "1990-01-01",
          "relationship": "PRINCIPAL", "work_eligible": True}


def _arrived_case_with_member(case_number, members=(_ADULT,), household_size=1):
    return setup_arrived_case(case_number=case_number,
                              household_size=household_size, members=list(members))


class TestBenefitApplicationRefileCycle:
    def test_appeal_cycle_refiles_same_application(self, api):
        """PRD §3.5: "A `DENIED` application may be appealed, moving to
        `APPEALED` with no date stamping, and an `APPEALED` application may
        be re-filed back to `FILED` — the re-file stamps `filed_on` anew and
        clears `decided_on` to null, since the prior decision no longer
        stands. This `DRAFT → FILED → DENIED → APPEALED → FILED` loop is the
        appeal cycle."

        Design: Difficulty/non_linear_state_machine/benefit_application_refile_cycle
        """
        ctx = _arrived_case_with_member("CASE-NL1")
        app = make_benefit_application(ctx["case"]["id"], ctx["members"][0]["id"])
        assert app["status"] == "DRAFT"
        set_clock("2026-08-15T09:00:00Z")
        filed = transition_application(app["id"], "FILED")
        denied = transition_application(app["id"], "DENIED")
        appealed = transition_application(app["id"], "APPEALED")
        set_clock("2026-08-25T09:00:00Z")
        refiled = transition_application(app["id"], "FILED")
        assert (filed["status"], denied["status"], appealed["status"],
                refiled["status"]) == ("FILED", "DENIED", "APPEALED", "FILED")
        assert refiled["id"] == app["id"]

    def test_cycle_restamps_filed_on_and_clears_decided_on(self, api):
        """PRD §3.5: "From `FILED` it is decided: `APPROVED` or `DENIED`,
        either way stamping `decided_on` from the clock." and "the re-file
        stamps `filed_on` anew and clears `decided_on` to null, since the
        prior decision no longer stands."

        Design: Difficulty/non_linear_state_machine/benefit_application_refile_cycle
        """
        ctx = _arrived_case_with_member("CASE-NL1B")
        app = make_benefit_application(ctx["case"]["id"], ctx["members"][0]["id"])
        set_clock("2026-08-15T09:00:00Z")
        filed = transition_application(app["id"], "FILED")
        assert date_part(filed["filed_on"]) == "2026-08-15"
        denied = transition_application(app["id"], "DENIED")
        assert date_part(denied["decided_on"]) == "2026-08-15"
        transition_application(app["id"], "APPEALED")
        set_clock("2026-08-25T09:00:00Z")
        refiled = transition_application(app["id"], "FILED")
        assert date_part(refiled["filed_on"]) == "2026-08-25"
        assert refiled["decided_on"] is None


class TestApplicationMemberScope:
    def test_member_of_another_case_is_not_found(self, api):
        """PRD §3.5: "A `CaseManager` opens a benefit application with the
        `case_id`, the `member_id` of the member the application is for —
        that member must belong to the case, else `ERR_NOT_FOUND`".

        Design: Corner/validations/application_member_wrong_case_returns_not_found
        """
        case_a = make_case(case_number="CASE-V6A", household_size=2,
                           scheduled_arrival_date="2026-08-20")
        member_a = add_member(case_a["id"], full_name="Member Of A",
                              date_of_birth="1990-01-01",
                              relationship="PRINCIPAL", work_eligible=True)
        ctx_b = setup_arrived_case(case_number="CASE-V6B", household_size=1)
        resp = api.create_benefit_application(
            {"case_id": ctx_b["case"]["id"], "member_id": member_a["id"],
             "benefit_type": "SSN"}, CM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCashAssistanceEligibility:
    def _child_only_case(self):
        return setup_arrived_case(
            case_number="CASE-V7", household_size=2,
            members=[{"full_name": "Child V", "date_of_birth": "2016-05-20",
                      "relationship": "CHILD", "work_eligible": False}])

    def test_cash_assistance_for_non_work_eligible_member_rejected(self, api):
        """PRD §3.5: "Cash assistance carries an eligibility rule: the member
        must be `work_eligible`, else the create is rejected with
        `ERR_MEMBER_NOT_ELIGIBLE`."

        Design: Corner/validations/cash_assistance_ineligible_member_returns_not_eligible
        """
        ctx = self._child_only_case()
        resp = api.create_benefit_application(
            {"case_id": ctx["case"]["id"], "member_id": ctx["members"][0]["id"],
             "benefit_type": "CASH_ASSISTANCE"}, CM)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE)

    def test_other_benefit_types_allowed_for_same_member(self, api):
        """PRD §3.5: "Cash assistance carries an eligibility rule: the member
        must be `work_eligible`, else the create is rejected with
        `ERR_MEMBER_NOT_ELIGIBLE`." and "Applications start in `DRAFT`".

        Design: Corner/validations/cash_assistance_ineligible_member_returns_not_eligible
        """
        ctx = self._child_only_case()
        app = validate_success(api.create_benefit_application(
            {"case_id": ctx["case"]["id"], "member_id": ctx["members"][0]["id"],
             "benefit_type": "SSN"}, CM), 201)
        assert app["status"] == "DRAFT"


class TestBenefitApplicationsPagination:
    def _three_filed_applications(self):
        ctx = _arrived_case_with_member("CASE-EP1")
        member_id = ctx["members"][0]["id"]
        apps = [make_benefit_application(ctx["case"]["id"], member_id, bt)
                for bt in ("SSN", "STATE_ID", "MEDICAL")]
        for app in apps:
            transition_application(app["id"], "FILED")
        return ctx

    def test_first_page_with_limit_two(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, must be at least 1, and must not
        exceed 100. `offset` defaults to 0." PRD §3.5: "Applications can be
        listed with `case_id`, `member_id`, and `status` filters plus
        pagination."

        Design: Corner/endpoints/benefit_applications_pagination_limit_offset
        """
        ctx = self._three_filed_applications()
        resp = api.list_benefit_applications(
            CM, params={"case_id": ctx["case"]["id"], "status": "FILED",
                        "limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert all(a["status"] == "FILED" for a in data)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_second_page_with_offset_two(self, api):
        """PRD §2.3: "List responses sort by `created_at` ascending unless a
        more specific ordering is stated for the endpoint, and the `meta`
        object of a list response carries the four pagination fields
        `limit`, `offset`, `total_count`, and `has_more`." PRD §3.5:
        "Applications can be listed with `case_id`, `member_id`, and `status`
        filters plus pagination."

        Design: Corner/endpoints/benefit_applications_pagination_limit_offset
        """
        ctx = self._three_filed_applications()
        resp = api.list_benefit_applications(
            CM, params={"case_id": ctx["case"]["id"], "status": "FILED",
                        "limit": 2, "offset": 2})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
