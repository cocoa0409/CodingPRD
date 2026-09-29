"""Endpoint surfaces: the derived read, the partial update, the cross-aggregate write and the clock."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assertions,
    factories,
    fixtures,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_faculty_chair_headers,
    make_partner_account_lead_headers,
)


class TestRevenueSummaryRead:
    def test_the_summary_reconciles_every_ledger_after_a_remittance(self, api):
        """One remittance moves four of the eight totals, and the read shows all of them settled.

        PRD: "A consolidated position read is available for any role: it reports
        `collected_tuition_cents`, `recognized_revenue_cents`, `remitted_to_partner_cents`,
        `holdback_balance_cents`, `unrecouped_marketing_spend_cents`,
        `marketing_budget_remaining_cents`, an `open_statement_count` of the partnership's statements
        that have not reached `REMITTED` and are not absent from the settlement pipeline — that is,
        statements in `CALCULATED`, `UNIVERSITY_APPROVED`, `DISPUTED`, `RESOLVED_ADJUSTED` or
        `STALE` — and a `program_count` of the partnership's programs."
        PRD: "Remittance stamps `remitted_at` with the logical clock instant, adds
        `net_payable_cents` to the partnership's `remitted_to_partner_cents`, adds `holdback_cents`
        to the partnership's `holdback_balance_cents`, and subtracts `marketing_recoupment_cents`
        from the partnership's `unrecouped_marketing_spend_cents`."

        Design: Corner/endpoints/revenue_summary_reconciles_every_derived_total_after_remittance
        """
        context = fixtures.build_september_statement(api, credits_completed=None)
        statement = context["statement"]
        assert statement["net_payable_cents"] == 73919
        assert statement["holdback_cents"] == 3890
        assert statement["marketing_recoupment_cents"] == 13730

        fixtures.approve_statement(api, statement["id"])
        fixtures.remit_statement(api, statement["id"], remittance_reference="ACH-2026-09")

        summary = validate_success(
            api.get_revenue_summary(context["ps_id"], headers=make_compliance_auditor_headers())
        )

        assert summary["collected_tuition_cents"] == 562500
        assert summary["recognized_revenue_cents"] == 159198
        assert summary["remitted_to_partner_cents"] == 73919
        assert summary["holdback_balance_cents"] == 3890
        assert summary["unrecouped_marketing_spend_cents"] == 286270
        assert summary["marketing_budget_remaining_cents"] == 3700000
        assert summary["open_statement_count"] == 0
        assert summary["program_count"] == 1


class TestCourseAmendment:
    def test_a_partial_update_rewrites_only_the_supplied_design_metadata(self, api):
        """Three fields change; the title, the owner, the design state and the revision count do not.

        PRD: "Amendment is permitted only while the course's `design_status` is `NOT_STARTED`,
        `IN_DESIGN` or `DESIGN_SUSPENDED`, and refused with `ERR_COURSE_INVALID_DESIGN_STATE`
        otherwise; it may revise `title`, `credits`, `design_cost_cents`, `required_for_launch`,
        `ip_license_grant_back` and `prerequisite_course_id`."
        PRD: "The `FacultyChair` may send it back with `REQUEST_REVISION`, taking `FACULTY_REVIEW →
        IN_DESIGN` and adding one to the course's `revision_round`"

        Design: Corner/endpoints/course_amendment_rewrites_design_metadata_without_moving_the_design_state
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        course = fixtures.add_course(api, ps_id, program["id"])
        fixtures.start_course_design(api, ps_id, course["id"])

        amended = validate_success(
            api.amend_course(
                course["id"],
                {"credits": 4, "design_cost_cents": 1800000, "ip_license_grant_back": True},
                headers=make_faculty_chair_headers(),
            ),
            200,
        )

        assert amended["credits"] == 4
        assert amended["design_cost_cents"] == 1800000
        assert amended["ip_license_grant_back"] is True
        assert amended["title"] == "Foundations of Analytics"
        assert amended["content_owner"] == "UNIVERSITY"
        assert amended["design_status"] == "IN_DESIGN"
        assert amended["revision_round"] == 0


class TestLeadConversion:
    def test_conversion_returns_an_enrollment_that_links_back_and_snapshots_the_price(self, api):
        """One call spans lead, program and enrollment, pinning the per-credit price at conversion.

        PRD: "The lead moves `APPLIED → ENROLLED`, and an enrollment is created in `ENROLLED` that
        records its `program_id` and the `lead_id` it converted from. Two money fields are derived
        immediately: `tuition_per_credit_snapshot_cents` copies the program's
        `tuition_per_credit_cents` as it stands at conversion, so later list-price changes never
        restate revenue already booked, and `tuition_charged_cents` is `credits_enrolled` multiplied
        by that snapshot."
        PRD: "`total_enrollment_count` counts those in `ENROLLED`, `ACTIVE` or `COMPLETED` and is
        the figure compared against `enrollment_cap`"

        Design: Corner/endpoints/enroll_links_the_lead_to_a_new_enrollment_row_with_snapshotted_tuition
        """
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]
        lead = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)

        response = api.enroll_lead(lead["id"], factories.enroll_payload(), headers=make_bursar_headers())
        enrollment = validate_success(response, 201)

        assert enrollment["lead_id"] == lead["id"]
        assert enrollment["program_id"] == pg_id
        assert enrollment["tuition_per_credit_snapshot_cents"] == 62500
        assert enrollment["tuition_charged_cents"] == 562500
        assert enrollment["status"] == "ENROLLED"

        assert fixtures.read_lead(api, lead["id"])["status"] == "ENROLLED"
        assert fixtures.read_program(api, pg_id)["total_enrollment_count"] == 1


class TestLogicalClockEndpoint:
    def test_the_launch_timestamp_is_stamped_from_the_logical_clock(self, api):
        """The clock is authoritative, so `launched_at` carries the instant that was set.

        PRD: "All temporal reasoning in this system reads a **logical clock** rather than wall-clock
        time. Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`, and it never
        falls back to real time. A `PlatformAdmin`-only test-driving capability replaces the clock by
        supplying a `current_utc` instant, and the response reports both the new `current_utc` and
        the `previous_utc` it displaced; no entity is mutated by the call."
        PRD: "On a successful launch the program's `launched_at` is stamped with the logical clock
        instant."

        Design: Corner/endpoints/clock_endpoint_pins_the_logical_now_for_every_derived_timestamp
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        fixtures.create_approved_course(api, ps_id, pg_id)
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)
        fixtures.approve_program(api, pg_id)

        clock = fixtures.set_clock(api, fixtures.CLOCK_AUG_15)
        assertions.assert_logical_instant(clock["previous_utc"], fixtures.CLOCK_AUG_1)

        launched = validate_success(
            api.post_program_lifecycle_action(
                pg_id,
                factories.lifecycle_action_payload("LAUNCH"),
                headers=make_partner_account_lead_headers(ps_id),
            ),
            200,
        )

        assert launched["status"] == "LAUNCHED"
        assertions.assert_logical_instant(launched["launched_at"], fixtures.CLOCK_AUG_15)
