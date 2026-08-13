"""Submittal lifecycle, deferrals, long-lead items, and expediting scores (PRD §3.1, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_spec_section,
    activate_spec_section,
    create_active_project,
    create_lli_advance_payload,
    create_revision_payload,
    get_reviewer,
    get_submittal,
    lli_of_submittal,
    make_subcontractor_rep_headers,
    return_revision,
    route_revision,
    set_clock,
    setup_long_lead_world,
    setup_long_lead_world_at_clock,
    setup_register_world,
    submit_revision,
    submittals_of_section,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestSubmittalVoidCascade:
    def test_void_submittal_terminal_lockdown_and_compensation(self, api):
        """PRD §3.3: "Voiding cascades: every revision still `SUBMITTED` or
        `UNDER_REVIEW` becomes `SUPERSEDED`, with the holding reviewer's
        `open_review_count` decremented for each `UNDER_REVIEW` revision voided; the
        linked LongLeadItem, if any exists and is not yet terminal, becomes `CANCELLED`;
        the submittal's `expediting_status` falls back to `NOT_REQUIRED`; and the
        submittal's `version` bumps."
        PRD §3.2: "attempts against a `VOID` or `CLOSED` submittal fail with
        `ERR_SUBMITTAL_TERMINAL`."

        Design: Corner/state_machines/void_submittal_terminal_lockdown_and_compensation
        """
        world = setup_register_world(lead_time_days=35)
        submittal = world["submittals"][0]
        reviewer = world["reviewers"][0]
        revision = submit_revision(
            submittal["id"], world["subcontractor"]["id"], "doc://r0"
        )
        route_revision(revision["id"], reviewer["id"])
        assert get_reviewer(reviewer["id"])["open_review_count"] == 1
        lli = lli_of_submittal(submittal["id"])
        assert lli is not None

        voided = validate_success(
            api.void_submittal(submittal["id"], {"reason": "scope cut"}, PM), 200
        )
        assert voided["review_status"] == "VOID"
        assert voided["expediting_status"] == "NOT_REQUIRED"

        revision_after = validate_success(api.get_revision(revision["id"], PE), 200)
        assert revision_after["status"] == "SUPERSEDED"
        assert get_reviewer(reviewer["id"])["open_review_count"] == 0, (
            "the void compensated the held review"
        )
        lli_after = validate_success(api.get_long_lead_item(lli["id"], PE), 200)
        assert lli_after["status"] == "CANCELLED"

        resp = api.create_revision(
            submittal["id"],
            create_revision_payload("doc://r1", voided["version"]),
            make_subcontractor_rep_headers(world["subcontractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBMITTAL_TERMINAL, 409)


class TestSubmittalDates:
    def test_submittal_required_dates_backward_business_pass(self, api):
        """PRD §3.1: "Its required dates derive from a backward business-day pass with a
        pinned evaluation order: first `required_approval_date` steps back the section's
        `lead_time_days` business days from the `required_on_site_date` (the on-site date
        itself is not counted), then `required_submission_date` steps back the section's
        `review_days` business days from the `required_approval_date` — submission always
        derives from approval, never the reverse."
        Need 2026-08-15, lead 35, review 10, no holidays: approval 2026-06-29,
        submission 2026-06-15.

        Design: Corner/calculations/submittal_required_dates_backward_business_pass
        """
        project = create_active_project("P")
        section = add_spec_section(
            project["id"],
            "051200",
            lead_time_days=35,
            review_days=10,
            default_need_date="2026-08-15",
        )
        activate_spec_section(section["id"])
        submittal = submittals_of_section(project["id"], "051200")[0]
        assert submittal["required_on_site_date"] == "2026-08-15"
        assert submittal["required_approval_date"] == "2026-06-29"
        assert submittal["required_submission_date"] == "2026-06-15"

    def test_submittal_patch_recomputes_dates_and_lli_mirror(self, api):
        """PRD §3.3: "while a submittal's `review_status` is anything other than `CLOSED`
        or `VOID`, a `ProjectEngineer` may patch its `required_on_site_date`. Doing so
        recomputes `required_approval_date` and `required_submission_date` through the
        same pinned backward pass, mirrors the new date onto the linked LongLeadItem —
        whose `days_late`, `escalation_level`, and `priority_score` recompute in turn —
        and bumps the submittal's `version`."
        Patching 2026-08-15 -> 2026-08-22 yields approval 2026-07-06, submission
        2026-06-22, and the item mirrors 2026-08-22 in the same request.

        Design: Corner/endpoints/submittal_patch_recomputes_dates_and_lli_mirror
        """
        world = setup_long_lead_world(
            section_number="051200",
            lead_time_days=35,
            review_days=10,
            default_need_date="2026-08-15",
        )
        submittal = world["submittals"][0]
        lli = world["lli"]

        patched = validate_success(
            api.patch_submittal(
                submittal["id"], {"required_on_site_date": "2026-08-22"}, PE
            ),
            200,
        )
        assert patched["required_on_site_date"] == "2026-08-22"
        assert patched["required_approval_date"] == "2026-07-06"
        assert patched["required_submission_date"] == "2026-06-22"

        lli_after = validate_success(api.get_long_lead_item(lli["id"], PE), 200)
        assert lli_after["required_on_site_date"] == "2026-08-22", (
            "the mirror is updated atomically with the patch"
        )


class TestDeferralStateMachine:
    def test_decide_deferral_without_request_rejected(self, api):
        """PRD §3.4: "A `ProjectManager` then decides: a `decision` of `APPROVE` moves
        the submittal to `DEFERRED_APPROVED`, while `REJECT` returns it to `NONE`;
        deciding without a pending request fails with `ERR_DEFERRAL_NOT_PENDING`."

        Design: Corner/state_machines/decide_deferral_without_request_rejected
        """
        world = setup_register_world(lead_time_days=5)
        submittal = world["submittals"][0]
        assert submittal["deferral_status"] == "NONE"
        resp = api.decide_deferral(submittal["id"], {"decision": "APPROVE"}, PM)
        validate_error(resp, ApiErrorId.ERR_DEFERRAL_NOT_PENDING, 409)


class TestLongLeadAdvanceChain:
    def test_lli_advance_must_not_skip_steps(self, api):
        """PRD §3.4: "Procurement advances along a fixed single-file chain —
        `IDENTIFIED` → `QUOTED` → `PO_ISSUED` → `IN_PRODUCTION` → `SHIPPED` →
        `DELIVERED` — one step at a time. Each advance names its target as `to_status`
        and records an `actual_date`; any target that is not exactly the next step is
        rejected with `ERR_LLI_INVALID_ADVANCE`."
        PRD §3.4: "Advancing to `QUOTED` stamps `quoted_date`, to `PO_ISSUED` stamps
        `po_issued_date`, and to `SHIPPED` stamps `shipped_date`, each from the supplied
        `actual_date`"

        Design: Corner/state_machines/lli_advance_must_not_skip_steps
        """
        world = setup_long_lead_world(lead_time_days=35)
        lli = world["lli"]
        assert lli["status"] == "IDENTIFIED"

        resp = api.advance_long_lead_item(
            lli["id"], create_lli_advance_payload("PO_ISSUED", "2026-08-02"), PE
        )
        validate_error(resp, ApiErrorId.ERR_LLI_INVALID_ADVANCE, 409)

        advanced = validate_success(
            api.advance_long_lead_item(
                lli["id"], create_lli_advance_payload("QUOTED", "2026-08-02"), PE
            ),
            200,
        )
        assert advanced["status"] == "QUOTED"
        assert advanced["quoted_date"] == "2026-08-02"


class TestPriorityScore:
    def _score_world(self, api):
        """Long-lead register generated at clock 2026-08-25 with need 2026-08-15:
        the item stands 10 calendar days late (escalation level 2)."""
        return setup_long_lead_world_at_clock(
            "2026-08-25T00:00:00Z",
            section_number="055000",
            lead_time_days=30,
            default_need_date="2026-08-15",
            required_submittal_kinds=("SHOP_DRAWINGS",),
        )

    def test_priority_score_weighted_sum_with_lateness_and_criticality(self, api):
        """PRD §3.4: "The `priority_score` itself is a weighted sum: three points per
        calendar day of lateness, counting at most twenty days of lateness; plus
        criticality points — forty for `CRITICAL`, twenty for `HIGH`, zero for
        `STANDARD`; plus two points for every calendar day by which the clock date has
        passed the item's `required_on_site_date`, with no contribution while that date
        still lies in the future."
        PRD §3.4: "It carries a free-text `description` (default empty) and a
        `criticality` of `CRITICAL`, `HIGH`, or `STANDARD` (default `STANDARD`), both
        patchable by a `ProjectEngineer` with an immediate `priority_score` recompute."
        Ten days late with HIGH criticality: 3*10 + 20 + 2*10 = 70.

        Design: Difficulty/combinatorial_formula/expediting_priority_score_nonlinear_clamps
        """
        world = self._score_world(api)
        lli = world["lli"]
        assert lli["days_late"] == 10
        assert lli["escalation_level"] == 2, "seven to thirteen days late is level 2"

        patched = validate_success(
            api.patch_long_lead_item(lli["id"], {"criticality": "HIGH"}, PE), 200
        )
        assert patched["priority_score"] == 70, (
            "3*min(10,20)=30 lateness + 20 HIGH criticality + 2*10=20 float"
        )
        assert patched["escalation_level"] == 2

    def test_deferral_approval_halves_priority_score_on_recompute(self, api):
        """PRD §3.4: "the linked long-lead item's `priority_score` is halved — floor
        division — on every recompute for as long as the deferral stands approved"
        PRD §3.4: "a `criticality` of `CRITICAL`, `HIGH`, or `STANDARD` (default
        `STANDARD`), both patchable by a `ProjectEngineer` with an immediate
        `priority_score` recompute."
        With the score at 70 and the deferral approved, a subsequent patch recomputes
        the score to floor(70/2) = 35.

        Design: Difficulty/combinatorial_formula/expediting_priority_score_nonlinear_clamps
        """
        world = self._score_world(api)
        submittal = world["submittal"]
        lli = world["lli"]
        patched = validate_success(
            api.patch_long_lead_item(lli["id"], {"criticality": "HIGH"}, PE), 200
        )
        assert patched["priority_score"] == 70

        validate_success(
            api.request_deferral(
                submittal["id"], {"reason": "owner decision pending"}, PE
            ),
            200,
        )
        decided = validate_success(
            api.decide_deferral(submittal["id"], {"decision": "APPROVE"}, PM), 200
        )
        assert decided["deferral_status"] == "DEFERRED_APPROVED"

        # Force a recompute while the deferral stands approved (a criticality /
        # description patch recomputes the score immediately, PRD §3.4).
        repatched = validate_success(
            api.patch_long_lead_item(lli["id"], {"description": "recheck"}, PE), 200
        )
        assert repatched["priority_score"] == 35, "floor(70 / 2) under the approved deferral"


class TestEscalationTierBoundaries:
    def _tier_world(self, api):
        """Long-lead register generated at the default clock with need 2026-08-15;
        lead_time_days 30 sits exactly on the default threshold 30."""
        return setup_long_lead_world(
            section_number="055000",
            lead_time_days=30,
            default_need_date="2026-08-15",
            required_submittal_kinds=("SHOP_DRAWINGS",),
        )

    def _level_at(self, api, project_id, lli_id, clock):
        set_clock(clock)
        validate_success(api.run_daily_scan(project_id, PM), 200)
        return validate_success(api.get_long_lead_item(lli_id, PE), 200)["escalation_level"]

    def test_long_lead_threshold_and_first_tier_boundary(self, api):
        """PRD §3.1: "A generated submittal whose section `lead_time_days` is at least
        the project's `long_lead_threshold_days` is flagged `is_long_lead`"
        PRD §3.4: "`escalation_level` tiers on `days_late` with lower-inclusive
        boundaries: level 0 when nothing is late, level 1 for one to six days late,
        level 2 for seven to thirteen, and level 3 at fourteen or more — exactly seven
        days late is level 2, exactly fourteen is level 3."
        Need 2026-08-15: at clock 2026-08-21 the item is 6 days late (level 1); at
        2026-08-22 exactly 7 days late (level 2).

        Design: Difficulty/boundary_precision_check/escalation_tier_exact_day_boundaries
        """
        world = self._tier_world(api)
        submittal = world["submittals"][0]
        assert submittal["is_long_lead"] is True, (
            "lead_time_days 30 meets the default threshold 30: at-least is long-lead"
        )
        lli = world["lli"]
        assert self._level_at(api, world["project"]["id"], lli["id"], "2026-08-21T00:00:00Z") == 1
        assert self._level_at(api, world["project"]["id"], lli["id"], "2026-08-22T00:00:00Z") == 2

    def test_second_and_third_tier_day_boundaries(self, api):
        """PRD §3.4: "`escalation_level` tiers on `days_late` with lower-inclusive
        boundaries: level 0 when nothing is late, level 1 for one to six days late,
        level 2 for seven to thirteen, and level 3 at fourteen or more — exactly seven
        days late is level 2, exactly fourteen is level 3."
        Need 2026-08-15: at clock 2026-08-28 the item is 13 days late (still level 2);
        at 2026-08-29 exactly 14 days late (level 3).

        Design: Difficulty/boundary_precision_check/escalation_tier_exact_day_boundaries
        """
        world = self._tier_world(api)
        lli = world["lli"]
        assert self._level_at(api, world["project"]["id"], lli["id"], "2026-08-28T00:00:00Z") == 2
        assert self._level_at(api, world["project"]["id"], lli["id"], "2026-08-29T00:00:00Z") == 3
