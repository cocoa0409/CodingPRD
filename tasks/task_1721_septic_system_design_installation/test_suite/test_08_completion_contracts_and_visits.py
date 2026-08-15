"""Final-inspection completion cascade, homeowner education, maintenance
contracts (proration, lapse, renewal OCC), and service visits."""
from test_helpers import (
    ApiErrorId,
    add_maintenance_contract,
    advance_clock,
    api_client,
    deliver_education_payload,
    get_contract,
    get_design,
    get_installation,
    get_permit,
    pass_inspection,
    record_visit_payload,
    renew_contract_payload,
    schedule_inspection,
    setup_completed_installation,
    setup_contract,
    setup_installation,
    validate_error,
    validate_success,
    walk_installation_to_field_installed,
    walk_installation_to_ready_for_final,
    walk_installation_to_rough_in,
    walk_installation_to_tank_set,
)


def _walk_to_ready_for_final(ctx):
    walk_installation_to_rough_in(ctx)
    walk_installation_to_tank_set(ctx)
    walk_installation_to_field_installed(ctx)
    walk_installation_to_ready_for_final(ctx)


class TestFinalInspectionCascade:
    def test_final_pass_completes_installation_and_finalizes_permit(self, api):
        """PRD section 3.6: "A passed `FINAL` inspection moves a `READY_FOR_FINAL`
        installation to `COMPLETED`, stamps the `completed_period`, copies the
        pinned design's `required_absorption_area_sqft` into the installation's
        `final_absorption_area_sqft` as the as-built record, transitions the
        authorizing permit to `FINALIZED`, and arms homeowner education for the
        customer".

        Design: Difficulty/transitive_cascade/final_inspection_pass_cascades_completion_finalization_education
        """
        ctx = setup_installation(bedroom_count=4, inspector=True)
        _walk_to_ready_for_final(ctx)
        final_insp = schedule_inspection(ctx, hold_point="FINAL", scheduled_period=0)
        pass_inspection(ctx, ctx.i0, final_insp["id"])

        installation = get_installation(ctx)
        assert installation["status"] == "COMPLETED", "hop 1"
        assert installation["final_absorption_area_sqft"] == 750, (
            "as-built copied from the pinned 4-bed LOAM design: 600/0.80")
        assert get_permit(ctx)["status"] == "FINALIZED", "hop 2"

    def test_education_delivery_gated_until_final_pass(self, api):
        """PRD section 3.8: "delivery requires at least one `COMPLETED`
        installation on the referenced site and otherwise fails with
        `ERR_INVALID_STATE`."
        PRD section 3.8: "Delivery stamps the customer's `education_completed_at`
        with a logical timestamp derived from the site's `current_period_index`,
        closing the loop that installation completion armed."

        Design: Difficulty/transitive_cascade/final_inspection_pass_cascades_completion_finalization_education
        """
        ctx = setup_installation(bedroom_count=4, inspector=True)
        _walk_to_ready_for_final(ctx)
        final_insp = schedule_inspection(ctx, hold_point="FINAL", scheduled_period=0)

        early = api_client.deliver_education_record(
            ctx.cid, ctx.cu, deliver_education_payload(ctx.s, 0), ctx.manager)
        validate_error(early, ApiErrorId.ERR_INVALID_STATE)

        pass_inspection(ctx, ctx.i0, final_insp["id"])
        customer = validate_success(api_client.deliver_education_record(
            ctx.cid, ctx.cu, deliver_education_payload(ctx.s, 0), ctx.manager), 201)
        assert customer["education_completed_at"] is not None, (
            "hop 3: the education gate opened once the cascade armed it")


class TestVisitWindow:
    def test_visit_at_end_period_accepted(self, api):
        """PRD section 3.8: "The visit is only valid while the contract is
        `ACTIVE` and the `visit_period` lies inside the coverage window from
        `start_period` through `end_period` inclusive; either violation fails with
        `ERR_VISIT_OUTSIDE_CONTRACT`."

        Design: Difficulty/resource_temporal_overlap/visit_inside_contract_window_inclusive_bounds
        """
        ctx = setup_contract(start_period=2, end_period=8, annual_fee_cents=120000)
        visit = validate_success(api_client.record_visit(
            ctx.cid, ctx.cu, ctx.s, ctx.mc,
            record_visit_payload(visit_period=8,
                                 findings="Boundary visit at end_period"),
            ctx.manager), 201)
        assert visit["visit_period"] == 8, "the closed-interval upper bound is inside"

    def test_visit_beyond_end_period_rejected(self, api):
        """PRD section 3.8: "The visit is only valid while the contract is
        `ACTIVE` and the `visit_period` lies inside the coverage window from
        `start_period` through `end_period` inclusive; either violation fails with
        `ERR_VISIT_OUTSIDE_CONTRACT`."

        Design: Difficulty/resource_temporal_overlap/visit_inside_contract_window_inclusive_bounds
        """
        ctx = setup_contract(start_period=2, end_period=8, annual_fee_cents=120000)
        resp = api_client.record_visit(
            ctx.cid, ctx.cu, ctx.s, ctx.mc,
            record_visit_payload(visit_period=9, findings="One period past end"),
            ctx.manager)
        validate_error(resp, ApiErrorId.ERR_VISIT_OUTSIDE_CONTRACT)


class TestMaintenanceProration:
    def test_proration_partial_window_round_once(self, api):
        """PRD section 3.8: "Its `prorated_fee_cents` — the fee actually charged
        for the coverage window — is the annual fee multiplied by the number of
        periods covered, counted inclusively as `end_period` minus `start_period`
        plus one, divided by the 12 periods in a year, with the result rounded
        half-up to whole cents. The rounding happens exactly once on the
        contract-level product; rounding per period and summing produces a
        different number and is incorrect."

        Design: Difficulty/combinatorial_formula/maintenance_proration_round_once_at_contract_level
        """
        ctx = setup_completed_installation()
        contract = add_maintenance_contract(
            ctx, start_period=2, end_period=8, annual_fee_cents=100000)
        assert contract["prorated_fee_cents"] == 58333, (
            "round_half_up(100000 * 7 / 12) once at contract level; "
            "per-period rounding would give 58331")
        assert contract["status"] == "ACTIVE"

    def test_proration_value_persists_on_reread(self, api):
        """PRD section 3.8: "Its `prorated_fee_cents` — the fee actually charged
        for the coverage window — is the annual fee multiplied by the number of
        periods covered, counted inclusively as `end_period` minus `start_period`
        plus one, divided by the 12 periods in a year, with the result rounded
        half-up to whole cents."

        Design: Difficulty/combinatorial_formula/maintenance_proration_round_once_at_contract_level
        """
        ctx = setup_completed_installation()
        contract = add_maintenance_contract(
            ctx, start_period=2, end_period=8, annual_fee_cents=100000)
        reread = get_contract(ctx, contract["id"])
        assert reread["prorated_fee_cents"] == 58333
        assert reread["start_period"] == 2 and reread["end_period"] == 8

    def test_proration_constants_applied_full_year(self, api):
        """PRD section 3.8: "Its `prorated_fee_cents` — the fee actually charged
        for the coverage window — is the annual fee multiplied by the number of
        periods covered, counted inclusively as `end_period` minus `start_period`
        plus one, divided by the 12 periods in a year, with the result rounded
        half-up to whole cents."

        Design: Corner/calculations/proration_constants_applied_full_year
        """
        ctx = setup_completed_installation()
        contract = add_maintenance_contract(
            ctx, start_period=3, end_period=14, annual_fee_cents=120000)
        assert contract["prorated_fee_cents"] == 120000, (
            "coverage 14-3+1 == 12 periods: no drift at the full-year boundary")


class TestAsBuiltReconciliation:
    def test_derived_field_reconciliation_installation_asbuilt(self, api):
        """PRD section 3.6: "A passed `FINAL` inspection moves a `READY_FOR_FINAL`
        installation to `COMPLETED`, stamps the `completed_period`, copies the
        pinned design's `required_absorption_area_sqft` into the installation's
        `final_absorption_area_sqft` as the as-built record".

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_installation_asbuilt
        """
        ctx = setup_installation(bedroom_count=4, inspector=True)
        assert get_design(ctx, ctx.d0)["required_absorption_area_sqft"] == 750
        _walk_to_ready_for_final(ctx)
        before = get_installation(ctx)
        assert before["status"] == "READY_FOR_FINAL"
        assert before.get("final_absorption_area_sqft") is None, (
            "the as-built field reconciles only at the COMPLETED transition")

        final_insp = schedule_inspection(ctx, hold_point="FINAL", scheduled_period=0)
        pass_inspection(ctx, ctx.i0, final_insp["id"])
        after = get_installation(ctx)
        assert after["status"] == "COMPLETED"
        assert after["final_absorption_area_sqft"] == 750


class TestContractLifecycleOnClock:
    def test_maintenance_contract_auto_lapse_on_clock(self, api):
        """PRD section 3.8: "When the `current_period_index` advances past the
        `end_period`, an `ACTIVE` contract moves to `LAPSED`".

        Design: Corner/state_machines/maintenance_contract_auto_lapse_and_expire_on_clock
        """
        ctx = setup_contract(start_period=0, end_period=3, annual_fee_cents=120000)
        advance_clock(ctx, 4)
        assert get_contract(ctx)["status"] == "LAPSED", "period 4 lies past end_period 3"

    def test_occ_stale_version_on_contract_renew(self, api):
        """PRD section 2.7: "Renewing a lapsed maintenance contract requires
        `expected_contract_version`, carrying the client's last observed `version`
        of that contract. A mismatch with the contract's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.8: "Renewal writes the new end period, recomputes
        `prorated_fee_cents` by the same once-rounded rule over the new window,
        returns the contract to `ACTIVE`, and bumps `version` by one."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_contract_renew
        """
        ctx = setup_contract(start_period=0, end_period=3, annual_fee_cents=120000)
        stale_version = ctx.contract["version"]
        advance_clock(ctx, 4)  # LAPSED; the cascade itself mutates the contract
        current = get_contract(ctx)
        assert current["status"] == "LAPSED"

        stale = api_client.renew_maintenance_contract(
            ctx.cid, ctx.cu, ctx.s, ctx.mc,
            renew_contract_payload(20, stale_version), ctx.manager)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        renewed = validate_success(api_client.renew_maintenance_contract(
            ctx.cid, ctx.cu, ctx.s, ctx.mc,
            renew_contract_payload(20, current["version"]), ctx.manager))
        assert renewed["status"] == "ACTIVE"
        assert renewed["end_period"] == 20
        assert renewed["version"] == current["version"] + 1
        assert renewed["prorated_fee_cents"] == 210000, (
            "round_half_up(120000 * 21 / 12) over the new window 0..20")

    def test_error_invalid_renewal_and_pinned_science_void(self, api):
        """PRD section 3.8: "renewal by a `ProjectManager` supplies a
        `new_end_period` that must lie strictly beyond the current `end_period`,
        else `ERR_INVALID_RENEWAL`".
        PRD section 3.2: "Voiding requires the record to be `RECORDED` (otherwise
        `ERR_INVALID_STATE`) and is refused with `ERR_PINNED_BY_LIVE_DESIGN` while
        any design in `SUBMITTED` or `APPROVED` status pins the record."

        Design: Corner/validations/error_invalid_renewal_and_pinned_science_void
        """
        ctx = setup_contract(start_period=0, end_period=3, annual_fee_cents=120000)
        advance_clock(ctx, 4)  # LAPSED
        current = get_contract(ctx)
        resp = api_client.renew_maintenance_contract(
            ctx.cid, ctx.cu, ctx.s, ctx.mc,
            renew_contract_payload(3, current["version"]), ctx.manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_RENEWAL)

        # The completed build's APPROVED design still pins the perc test.
        void_resp = api_client.void_percolation_test(
            ctx.cid, ctx.cu, ctx.s, ctx.pt1, ctx.scientist)
        validate_error(void_resp, ApiErrorId.ERR_PINNED_BY_LIVE_DESIGN)
