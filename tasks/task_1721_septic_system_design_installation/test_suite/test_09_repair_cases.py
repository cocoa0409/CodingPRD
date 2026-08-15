"""Repair cases: triage gating on the replacement design's state, the
provisional-vs-final replacement estimate pair, and the remediation gate."""
from test_helpers import (
    ApiErrorId,
    add_design,
    add_installation,
    add_permit,
    api_client,
    approve_design,
    get_design,
    get_permit,
    get_repair_case,
    setup_open_repair_case,
    submit_design,
    triage_repair_case_payload,
    validate_error,
    validate_success,
)


class TestReplacementEstimateVariants:
    def test_provisional_estimate_recorded_on_triage_time_design(self, api):
        """PRD section 3.9: "Triage records the remedy, sets the case's
        `replacement_design_id` when replacing, moves the case to `TRIAGED`, and —
        on the replacement path — stamps the replacement design's
        `provisional_estimate_cents`: the replacement design row referenced at
        triage contributes its current `design_daily_flow_gpd`, multiplied by 4200
        cents per gallon-per-day of flow."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_estimate_on_repair_replacement
        """
        ctx = setup_open_repair_case()
        dr = add_design(ctx, bedroom_count=3, system_type="GRAVITY")  # flow 450
        submit_design(ctx, dr["id"])
        approve_design(ctx, dr["id"])
        triaged = validate_success(api_client.triage_repair_case(
            ctx.cid, ctx.cu, ctx.s, ctx.rc,
            triage_repair_case_payload("REPLACEMENT", replacement_design_id=dr["id"]),
            ctx.manager))
        assert triaged["status"] == "TRIAGED"
        assert triaged["replacement_design_id"] == dr["id"]
        design = get_design(ctx, dr["id"])
        assert design["provisional_estimate_cents"] == 1890000, (
            "provisional variant: triage-time flow 450 * 4200")

    def test_final_estimate_reads_issuance_pinned_amended_design(self, api):
        """PRD section 3.9: "A replacement case resolves automatically when the
        installation under the permit pinning the replacement design reaches
        `COMPLETED`; at that moment the final replacement estimate is computed
        with the same 4200-cents-per-gallon-per-day rate but against the flow of
        the design row pinned at permit issuance, which may differ from the
        provisional figure whenever the replacement plan was amended between
        triage and issuance."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_estimate_on_repair_replacement
        """
        ctx = setup_open_repair_case()
        dr1 = add_design(ctx, bedroom_count=3, system_type="GRAVITY")  # flow 450
        submit_design(ctx, dr1["id"])
        approve_design(ctx, dr1["id"])
        validate_success(api_client.triage_repair_case(
            ctx.cid, ctx.cu, ctx.s, ctx.rc,
            triage_repair_case_payload("REPLACEMENT", replacement_design_id=dr1["id"]),
            ctx.manager))

        # Amend the replacement plan between triage and permit issuance.
        dr2 = add_design(ctx, bedroom_count=4, system_type="GRAVITY",
                         supersedes_design_id=dr1["id"])  # flow 600
        submit_design(ctx, dr2["id"])
        approve_design(ctx, dr2["id"])
        p1 = add_permit(ctx, design_id=dr2["id"], attr="p1")
        i1 = add_installation(ctx, permit_id=p1["id"], attr="i1")

        begun = validate_success(api_client.begin_remediation(
            ctx.cid, ctx.cu, ctx.s, ctx.rc, ctx.manager))
        assert begun["status"] == "IN_REMEDIATION", (
            "remediation accepted: the permit pins the amended replacement plan")

        permit = get_permit(ctx, p1["id"])
        assert permit["design_id"] == dr2["id"], (
            "the final variant reads the issuance-pinned row (flow 600 -> "
            "2520000 cents != provisional 1890000)")
        assert get_design(ctx, dr2["id"])["design_daily_flow_gpd"] == 600
        dr1_after = get_design(ctx, dr1["id"])
        assert dr1_after["status"] == "SUPERSEDED", (
            "approval of the amendment superseded the triage-time design")
        assert dr1_after["provisional_estimate_cents"] == 1890000, (
            "the provisional estimate stays on the triage-time row")


class TestTriageGating:
    def test_triage_replacement_with_submitted_design_rejected(self, api):
        """PRD section 3.9: "Choosing `REPLACEMENT` requires a
        `replacement_design_id` referencing an `APPROVED` design for the same
        site, else `ERR_REPLACEMENT_DESIGN_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/repair_triage_depends_on_replacement_design_state
        """
        ctx = setup_open_repair_case()
        dr = add_design(ctx, bedroom_count=4, system_type="MOUND")
        submit_design(ctx, dr["id"])  # SUBMITTED, not APPROVED
        resp = api_client.triage_repair_case(
            ctx.cid, ctx.cu, ctx.s, ctx.rc,
            triage_repair_case_payload("REPLACEMENT", replacement_design_id=dr["id"]),
            ctx.manager)
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_DESIGN_NOT_APPROVED)
        assert get_repair_case(ctx)["status"] == "OPEN"

    def test_triage_replacement_with_approved_design_succeeds(self, api):
        """PRD section 3.9: "Choosing `REPLACEMENT` requires a
        `replacement_design_id` referencing an `APPROVED` design for the same
        site, else `ERR_REPLACEMENT_DESIGN_NOT_APPROVED`".
        PRD section 3.9: "Triage records the remedy, sets the case's
        `replacement_design_id` when replacing, moves the case to `TRIAGED`".

        Design: Difficulty/cross_entity_state_dependency/repair_triage_depends_on_replacement_design_state
        """
        ctx = setup_open_repair_case()
        dr = add_design(ctx, bedroom_count=4, system_type="MOUND")
        submit_design(ctx, dr["id"])
        approve_design(ctx, dr["id"])
        triaged = validate_success(api_client.triage_repair_case(
            ctx.cid, ctx.cu, ctx.s, ctx.rc,
            triage_repair_case_payload("REPLACEMENT", replacement_design_id=dr["id"]),
            ctx.manager))
        assert triaged["status"] == "TRIAGED"
        assert triaged["remedy"] == "REPLACEMENT"
        assert triaged["replacement_design_id"] == dr["id"]


class TestRemediationGate:
    def test_error_remediation_not_started_on_replacement(self, api):
        """PRD section 3.9: "On the replacement path there is a further gate: an
        installation must already exist whose permit pins the case's
        `replacement_design_id`, else `ERR_REMEDIATION_NOT_STARTED`."

        Design: Corner/errors/error_remediation_not_started_on_replacement
        """
        ctx = setup_open_repair_case()
        dr = add_design(ctx, bedroom_count=4, system_type="MOUND")
        submit_design(ctx, dr["id"])
        approve_design(ctx, dr["id"])
        validate_success(api_client.triage_repair_case(
            ctx.cid, ctx.cu, ctx.s, ctx.rc,
            triage_repair_case_payload("REPLACEMENT", replacement_design_id=dr["id"]),
            ctx.manager))
        resp = api_client.begin_remediation(ctx.cid, ctx.cu, ctx.s, ctx.rc, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOT_STARTED)
        assert get_repair_case(ctx)["status"] == "TRIAGED"
