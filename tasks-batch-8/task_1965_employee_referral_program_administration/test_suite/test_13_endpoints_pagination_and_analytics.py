"""List pagination/filtering and analytics corner tests (PRD §2.3, §3.6, §3.8)."""
from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_hire_milestone,
    create_open_batch,
    add_milestone_to_batch,
    create_referral_payload,
    api_client,
)


class TestReferralsPagination:
    def test_referrals_list_pagination_and_status_filter(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and maximum of
        100. The `offset` parameter specifies the number of items to skip and defaults
        to 0." and "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §4: "List endpoints accept the filter query parameters discussed throughout
        §3 (for example `status`, `department`, `job_level`, `employment_status`,
        `global_status`, `hired_via_referral_id`, `filled_by_candidate_id`, `referrer_id`,
        `candidate_id`, `job_requisition_id`, `campaign_id`, `policy_version_id`, `kind`,
        `payroll_batch_id`, `employee_id`, `case_type`, and `referral_id`) in addition to
        the `limit` and `offset` pagination parameters of §2.3".

        3 referrals with limit=2: page 1 has 2 rows + has_more; offset 2 returns the
        last row; status filter intersects.

        Design: Corner/endpoints/referrals_list_pagination_and_status_filter
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(openings=5)
        for i in (1, 2, 3):
            submit_referral(emp["id"], req["id"], candidate_email=f"c{i}@x.com",
                            candidate_full_name=f"C {i}")

        ta = TEST_USERS["talent_admin_headers"]
        page1, meta1 = validate_paginated(api.list_referrals(ta, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_referrals(ta, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        rows_sub, meta_sub = validate_paginated(
            api.list_referrals(ta, params={"status": "SUBMITTED", "limit": 10, "offset": 0})
        )
        assert len(rows_sub) == 3

        rows_hired, meta_hired = validate_paginated(
            api.list_referrals(ta, params={"status": "HIRED", "limit": 10, "offset": 0})
        )
        assert rows_hired == []
        assert meta_hired["total_count"] == 0


class TestMilestonesFilteredByPayrollBatch:
    def test_milestones_filtered_by_payroll_batch(self, api):
        """PRD §3.5: "Milestones can be listed with `referral_id`, `payroll_batch_id`,
        `status`, and `kind` filters".
        PRD §3.6: "Attaching an approved milestone moves it from `APPROVED` to `BATCHED`
        and sets its `payroll_batch_id`".

        The payroll_batch_id filter returns exactly the attached milestone; the
        status=APPROVED filter afterwards returns zero rows.

        Design: Corner/endpoints/milestones_filtered_by_payroll_batch
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])
        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.approve_milestone(ms["id"], pp))
        batch = create_open_batch()
        add_milestone_to_batch(batch["id"], ms["id"], batch["version"])

        rows = get_success_data(api.list_milestones(pp, params={"payroll_batch_id": batch["id"]}))
        assert len(rows) == 1
        assert rows[0]["id"] == ms["id"]
        assert rows[0]["status"] == "BATCHED"

        rows_appr = get_success_data(
            api.list_milestones(pp, params={"payroll_batch_id": batch["id"], "status": "APPROVED"})
        )
        assert rows_appr == []


class TestAnalyticsWindow:
    def test_analytics_window_excludes_out_of_window_submissions(self, api):
        """PRD §3.8: "may bound the analysis with `window_start` and `window_end`, both
        inclusive; omitted, the window runs from the beginning of time up to the logical
        now. Only referrals whose `submitted_at` falls inside the window count." and
        "Groups with zero submissions are omitted from the output entirely."
        PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`".

        A referral submitted at the default clock is excluded by window_end 2026-07-31
        and included by window_end exactly 2026-08-01T00:00:00Z.

        Design: Corner/endpoints/analytics_window_excludes_out_of_window_submissions
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        submit_referral(emp["id"], req["id"], candidate_email="c1@x.com",
                        candidate_full_name="C One")

        ta = TEST_USERS["talent_admin_headers"]
        data_out = get_success_data(
            api.get_source_quality(
                ta, params={"group_by": "REQ_DEPARTMENT", "window_end": "2026-07-31T00:00:00Z"}
            )
        )
        assert data_out["groups"] == []

        data_in = get_success_data(
            api.get_source_quality(
                ta, params={"group_by": "REQ_DEPARTMENT", "window_end": "2026-08-01T00:00:00Z"}
            )
        )
        assert len(data_in["groups"]) == 1
        assert data_in["groups"][0]["submissions"] == 1
