"""10b5-1 plans: lifecycle loops, cooling-off variants, OCC, supersede, matching."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    as_officer,
    assert_same_instant,
    create_approved_plan,
    create_current_person,
    create_draft_plan,
    create_officer,
    create_quarterly_window,
    create_submitted_plan,
    create_tenb5_plan_payload,
    get_person,
    get_success_data,
    ingest_confirmation,
    run_sweep,
    set_logical_clock,
    validate_error,
    validate_success,
    validate_paginated,
)


class TestPlanLifecycle:
    def test_owner_terminates_draft_plan(self, api):
        """PRD §3.6: "`TERMINATE` moves a plan in `DRAFT`, `ACTIVE`, or `SUSPENDED` to
        the terminal `TERMINATED` — available to the owning insider or an officer
        alike."

        Design: Corner/state_machines/plan_terminate_draft_by_owner
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        owner = create_current_person("Plan Owner", "planowner@x.com")
        plan = create_draft_plan(owner, total_quantity=100)
        data = validate_success(
            api.act_on_tenb5_plan(plan["id"], {"action": "TERMINATE"}, as_insider(owner))
        )
        assert data["status"] == "TERMINATED"

    def test_returned_plan_resubmits_in_revision_loop(self, api):
        """PRD §3.6: "A `RETURN` decision instead records the officer's `return_note`
        on the plan, and the owner may revise and submit again — `RETURNED` plans
        submit back to `SUBMITTED` in a revision loop that can repeat indefinitely."

        Design: Difficulty/non_linear_state_machine/tenb5_plan_revision_and_suspend_resume_cycles
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer5@x.com")
        owner = create_current_person("Insider D", "insider_d@x.com")
        plan = create_submitted_plan(owner, total_quantity=300)

        returned = get_success_data(
            api.decide_tenb5_plan(
                plan["id"], {"outcome": "RETURN", "return_note": "fix trade dates"},
                as_officer(officer),
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_note"] == "fix trade dates"

        resubmitted = get_success_data(
            api.submit_tenb5_plan(plan["id"], as_insider(owner))
        )
        assert resubmitted["status"] == "SUBMITTED"

        approved = get_success_data(
            api.decide_tenb5_plan(plan["id"], {"outcome": "APPROVE"}, as_officer(officer))
        )
        assert approved["status"] == "APPROVED"
        assert_same_instant(
            approved["cooling_off_end"], "2026-08-31T00:00:00Z", "cooling_off_end"
        )

    def test_active_plan_suspend_resume_cycle(self, api):
        """PRD §3.6: "The sweep moves an `APPROVED` plan to `ACTIVE` only once now is
        at or past its `cooling_off_end`." PRD §3.6: "`SUSPEND` moves an `ACTIVE` plan
        to `SUSPENDED` (officers only), `RESUME` returns a `SUSPENDED` plan to
        `ACTIVE` (officers only)".

        Design: Difficulty/non_linear_state_machine/tenb5_plan_revision_and_suspend_resume_cycles
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer5b@x.com")
        owner = create_current_person("Insider D2", "insider_d2@x.com")
        plan = create_approved_plan(owner, officer, total_quantity=300)
        assert_same_instant(plan["cooling_off_end"], "2026-08-31T00:00:00Z",
                            "cooling_off_end")

        set_logical_clock("2026-08-31T00:00:00Z")
        run_sweep(officer)
        active = get_success_data(api.get_tenb5_plan(plan["id"], as_officer(officer)))
        assert active["status"] == "ACTIVE"

        suspended = get_success_data(
            api.act_on_tenb5_plan(plan["id"], {"action": "SUSPEND"}, as_officer(officer))
        )
        assert suspended["status"] == "SUSPENDED"
        resumed = get_success_data(
            api.act_on_tenb5_plan(plan["id"], {"action": "RESUME"}, as_officer(officer))
        )
        assert resumed["status"] == "ACTIVE"


class TestCoolingOffVariants:
    def test_executive_cooling_off_uses_window_end_plus_buffer(self, api):
        """PRD §3.6: "Under the `EXECUTIVE` variant — owners designated
        `SECTION_16_OFFICER` or `DIRECTOR` — cooling-off ends at the later of two
        instants: ninety days after `approved_at`, or two days after the `end_at` of
        the `QUARTERLY` blackout window whose half-open interval contains
        `approved_at`, considering quarterly windows in any status other than
        `MERGED`; when no quarterly window contains the approval instant, the
        executive rule reduces to ninety days after `approved_at`."

        Design: Difficulty/dual_variant_calc/cooling_off_end_executive_vs_standard
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer2@x.com")
        exec_person = create_current_person(
            "Exec E", "exec_e@x.com", designation="SECTION_16_OFFICER",
            department="Executive",
        )
        create_quarterly_window(officer, "2026-07-15T00:00:00Z", "2026-11-15T00:00:00Z")
        plan = create_approved_plan(
            exec_person, officer, total_quantity=500,
            first_trade_date="2026-12-01T00:00:00Z",
        )
        assert_same_instant(plan["approved_at"], "2026-08-01T00:00:00Z", "approved_at")
        # max(approved + 90d = 2026-10-30, window end + 2d = 2026-11-17)
        assert_same_instant(
            plan["cooling_off_end"], "2026-11-17T00:00:00Z", "cooling_off_end"
        )

    def test_standard_cooling_off_is_thirty_days(self, api):
        """PRD §3.6: "Under the `STANDARD` variant — owners designated `EMPLOYEE` or
        `CONSULTANT` — cooling-off ends thirty days after `approved_at`." PRD §3.6:
        "Identical approval instants therefore yield a later `cooling_off_end` for
        executives than for staff."

        Design: Difficulty/dual_variant_calc/cooling_off_end_executive_vs_standard
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer2b@x.com")
        std_person = create_current_person("Std S", "std_s@x.com",
                                           designation="EMPLOYEE", department="Sales")
        plan = create_approved_plan(
            std_person, officer, total_quantity=500,
            first_trade_date="2026-12-01T00:00:00Z",
        )
        assert_same_instant(plan["approved_at"], "2026-08-01T00:00:00Z", "approved_at")
        assert_same_instant(
            plan["cooling_off_end"], "2026-08-31T00:00:00Z", "cooling_off_end"
        )


class TestPlanCreateOccAndSupersede:
    def test_plan_create_with_stale_person_version_rejected(self, api):
        """PRD §2.7: "Creating a plan supersedes any existing draft-stage plan for
        the same person and ticker and increments the person's `version`, so a
        creation carrying a previously observed version is stale and is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/plan_create_stale_person_version_returns_412
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        owner = create_current_person("Owner X2", "owner_x2@x.com")
        stale_version = owner["version"] - 1
        resp = api.create_tenb5_plan(
            create_tenb5_plan_payload(
                covered_person_id=owner["id"],
                security_ticker="ACME",
                total_quantity=100,
                first_trade_date="2026-09-01T00:00:00Z",
                expected_covered_person_version=stale_version,
            ),
            as_insider(owner),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        _, meta = validate_paginated(
            api.list_tenb5_plans(admin_headers(),
                                 params={"covered_person_id": owner["id"]})
        )
        assert meta["total_count"] == 0

    def test_new_plan_supersedes_existing_draft(self, api):
        """PRD §3.6: "Creation **supersedes**: any existing plan of the same owner
        for the same ticker sitting in `DRAFT`, `SUBMITTED`, or `RETURNED` is
        automatically moved to `CANCELLED`, and the owner's `CoveredPerson` record
        increments its `version`."

        Design: Corner/cross_cutting_layers/plan_create_supersedes_existing_draft
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        owner = create_current_person("Owner X6", "owner_x6@x.com")
        version_before = owner["version"]
        plan1 = create_draft_plan(owner, total_quantity=100)
        plan2 = create_draft_plan(owner, total_quantity=200,
                                  first_trade_date="2026-10-01T00:00:00Z")

        old = get_success_data(api.get_tenb5_plan(plan1["id"], as_insider(owner)))
        assert old["status"] == "CANCELLED"
        assert plan2["status"] == "DRAFT"
        assert get_person(owner["id"])["version"] == version_before + 2


class TestPlanMatchingGate:
    def test_confirmation_flagged_while_plan_not_active(self, api):
        """PRD §3.7: "Failing the preclearance lane, the matcher tries the plan lane:
        a qualifying plan shares the confirmation's `covered_person_id` and
        `security_ticker`, is `ACTIVE`, and has a `trade_date` no earlier than its
        `cooling_off_end` and no earlier than its `first_trade_date`."

        Design: Difficulty/cross_entity_state_dependency/confirmation_plan_match_requires_active_plan
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer13@x.com")
        owner = create_current_person("Insider M", "insider_m@x.com")
        plan = create_approved_plan(owner, officer, total_quantity=300,
                                    first_trade_date="2026-09-01T00:00:00Z")
        assert plan["status"] == "APPROVED"

        conf = ingest_confirmation(
            officer, owner, ticker="ACME", side="SELL", quantity=10, price=25.00,
            trade_date="2026-09-02T00:00:00Z", broker_ref="BR-D14-1",
        )
        assert conf["status"] == "FLAGGED"

    def test_confirmation_matches_plan_after_cooling_off_sweep(self, api):
        """PRD §3.6: "The sweep moves an `APPROVED` plan to `ACTIVE` only once now is
        at or past its `cooling_off_end`." PRD §3.7: "Among qualifying plans the
        matcher selects the one with the earliest `approved_at`, breaking ties by
        ascending `created_at`, and the confirmation records it in `match_plan_id`."

        Design: Difficulty/cross_entity_state_dependency/confirmation_plan_match_requires_active_plan
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer13b@x.com")
        owner = create_current_person("Insider M2", "insider_m2@x.com")
        plan = create_approved_plan(owner, officer, total_quantity=300,
                                    first_trade_date="2026-09-01T00:00:00Z")
        set_logical_clock("2026-09-01T00:00:00Z")
        run_sweep(officer)
        active = get_success_data(api.get_tenb5_plan(plan["id"], as_officer(officer)))
        assert active["status"] == "ACTIVE"

        conf = ingest_confirmation(
            officer, owner, ticker="ACME", side="SELL", quantity=10, price=25.00,
            trade_date="2026-09-02T00:00:00Z", broker_ref="BR-D14-2",
        )
        assert conf["status"] == "MATCHED_PLAN"
        assert conf["match_plan_id"] == plan["id"]
