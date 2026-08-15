"""Soil science records: freshness age boundary, supersession cascade, void ownership."""
from test_helpers import (
    ApiErrorId,
    add_design,
    add_percolation_test,
    add_science,
    add_soil_evaluation,
    add_staff,
    advance_clock,
    api_client,
    get_design,
    make_soil_scientist_headers,
    setup_company,
    setup_site_with_science,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
    add_customer,
    add_site,
)


class TestScienceAgeBoundary:
    def test_submit_at_science_age_exactly_24_succeeds(self, api):
        """PRD section 3.4: "Finally, the science must still be fresh: the site's
        `current_period_index` minus the evaluation's `evaluation_date_period`,
        and minus the test's `test_date_period`, must each be at most 24 periods.
        An age of exactly 24 periods is still valid — only an age strictly greater
        than 24 is stale — and a violation surfaces as `ERR_SCIENCE_EXPIRED`."

        Design: Difficulty/boundary_precision_check/science_age_exactly_24_passes_25_fails
        """
        ctx = setup_site_with_science()
        advance_clock(ctx, 2)  # re-stamp science at period 2 via fresh records
        add_science(ctx, eval_attr="e2", perc_attr="pt2")
        design = add_design(ctx, bedroom_count=3, eval_attr="e2", perc_attr="pt2")
        advance_clock(ctx, 24)  # period 26: science age exactly 24
        submitted = submit_design(ctx, design["id"])
        assert submitted["status"] == "SUBMITTED", (
            "age exactly 24 is still valid (strictly-greater triggers staleness)")

    def test_submit_at_science_age_25_fails(self, api):
        """PRD section 3.4: "An age of exactly 24 periods is still valid — only an
        age strictly greater than 24 is stale — and a violation surfaces as
        `ERR_SCIENCE_EXPIRED`."

        Design: Difficulty/boundary_precision_check/science_age_exactly_24_passes_25_fails
        """
        ctx = setup_site_with_science()
        advance_clock(ctx, 2)
        add_science(ctx, eval_attr="e2", perc_attr="pt2")
        design = add_design(ctx, bedroom_count=3, eval_attr="e2", perc_attr="pt2")
        advance_clock(ctx, 25)  # period 27: science age 25
        resp = api_client.submit_design(ctx.cid, ctx.cu, ctx.s, design["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_SCIENCE_EXPIRED)


class TestSupersessionCascade:
    def test_superseded_perc_test_supersedes_record_and_withdraws_design(self, api):
        """PRD section 3.2: "Recording a new evaluation for a site automatically
        transitions whichever evaluation was previously `RECORDED` to `SUPERSEDED`,
        writing the new record's id into the old record's `superseded_by_id`; the
        same rule governs percolation tests. Supersession then cascades into
        design work: every `DRAFT` design still pinning the superseded record is
        automatically moved to `WITHDRAWN`."

        Design: Difficulty/cross_entity_state_dependency/design_submit_depends_on_science_record_states
        """
        ctx = setup_site_with_science()
        design = add_design(ctx, bedroom_count=3)
        pt2 = add_percolation_test(ctx, minutes_per_inch=15.5, test_pit_count=3,
                                   attr="pt2")
        pt1 = validate_success(api_client.get_percolation_test(
            ctx.cid, ctx.cu, ctx.s, ctx.pt1, ctx.manager))
        assert pt1["status"] == "SUPERSEDED"
        assert pt1["superseded_by_id"] == pt2
        assert get_design(ctx, design["id"])["status"] == "WITHDRAWN", (
            "the DRAFT design pinning the superseded test is auto-withdrawn")

    def test_submit_after_science_supersession_fails_state_check(self, api):
        """PRD section 3.4: "the design must actually be in `DRAFT`, else
        `ERR_INVALID_STATE`".
        PRD section 2.9: "When a single request violates more than one rule, the
        applicable checks are evaluated in a fixed precedence order and only the
        first failure is reported."

        Design: Difficulty/cross_entity_state_dependency/design_submit_depends_on_science_record_states
        """
        ctx = setup_site_with_science()
        design = add_design(ctx, bedroom_count=3)
        add_percolation_test(ctx, minutes_per_inch=15.5, test_pit_count=3, attr="pt2")
        assert get_design(ctx, design["id"])["status"] == "WITHDRAWN"
        resp = api_client.submit_design(ctx.cid, ctx.cu, ctx.s, design["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSingleRecordedAnchor:
    def test_recording_new_evaluation_preserves_single_recorded_anchor(self, api):
        """PRD section 3.2: "Science is single-generational per site. Recording a
        new evaluation for a site automatically transitions whichever evaluation
        was previously `RECORDED` to `SUPERSEDED`, writing the new record's id
        into the old record's `superseded_by_id`; the same rule governs
        percolation tests."

        Design: Difficulty/compensating_invariant/science_supersession_preserves_single_recorded_anchor
        """
        ctx = setup_site_with_science()
        add_design(ctx, bedroom_count=3, attr="da")
        add_design(ctx, bedroom_count=5, system_type="PRESSURE_DISTRIBUTION", attr="db")
        e2 = add_soil_evaluation(ctx, soil_class="CLAY_LOAM", limiting_layer_inches=40,
                                 attr="e2")
        recorded, meta = validate_paginated(api_client.list_soil_evaluations(
            ctx.cid, ctx.cu, ctx.s, ctx.manager, params={"status": "RECORDED"}))
        assert len(recorded) == 1 and recorded[0]["id"] == e2, (
            "exactly one RECORDED evaluation remains after the forward+supersede pair")
        e1 = validate_success(api_client.get_soil_evaluation(
            ctx.cid, ctx.cu, ctx.s, ctx.e1, ctx.manager))
        assert e1["status"] == "SUPERSEDED"
        assert e1["superseded_by_id"] == e2

    def test_supersession_withdraws_all_draft_designs_pinning_old_science(self, api):
        """PRD section 3.2: "Supersession then cascades into design work: every
        `DRAFT` design still pinning the superseded record is automatically moved
        to `WITHDRAWN`."

        Design: Difficulty/compensating_invariant/science_supersession_preserves_single_recorded_anchor
        """
        ctx = setup_site_with_science()
        add_design(ctx, bedroom_count=3, attr="da")
        add_design(ctx, bedroom_count=5, system_type="PRESSURE_DISTRIBUTION", attr="db")
        add_soil_evaluation(ctx, soil_class="CLAY_LOAM", limiting_layer_inches=40, attr="e2")
        assert get_design(ctx, ctx.da)["status"] == "WITHDRAWN"
        assert get_design(ctx, ctx.db)["status"] == "WITHDRAWN", (
            "the compensating cascade leaves zero DRAFT designs pinning stale science")


class TestVoidOwnership:
    def test_scientist_void_ownership_enforced(self, api):
        """PRD section 3.2: "A scientist may also void a record outright, but only
        the recording scientist may do so: the acting scientist's id must equal
        the record's `evaluator_id`, otherwise the call is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD section 3.2: "A successful void leaves the record in `VOIDED`, one of
        the two terminal states alongside `SUPERSEDED`."

        Design: Corner/rbac/scientist_void_ownership_enforced
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, second_scientist=True)
        add_customer(ctx)
        add_site(ctx)
        e1 = add_soil_evaluation(ctx)
        resp = api_client.void_soil_evaluation(
            ctx.cid, ctx.cu, ctx.s, e1, make_soil_scientist_headers(ctx.ss2))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        voided = validate_success(api_client.void_soil_evaluation(
            ctx.cid, ctx.cu, ctx.s, e1, ctx.scientist))
        assert voided["status"] == "VOIDED"
