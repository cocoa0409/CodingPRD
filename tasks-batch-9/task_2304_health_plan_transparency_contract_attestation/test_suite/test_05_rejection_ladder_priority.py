"""Requests that break several rules at once, where only one answer is correct.

Each case is built so that two or three independent checks would all fail. The
ladder is total, so exactly one error identifier is admissible, and in each pair
the two candidate answers differ — sometimes in HTTP status too — so the code
cannot be inferred from the status alone.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_SIGNER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    ATTESTATION_DRAFT,
    CYCLE_CERTIFIED,
    POSTURE_COMPLIANT,
    POSTURE_DEFICIENT,
    POSTURE_FROZEN,
    VENDOR_TYPE_PBM,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

TOOL_LAUNCH_CLOCK = "2027-01-05T09:00:00Z"
TOOL_APPEND_CLOCK = "2027-07-02T00:00:00Z"
EXISTING_WINDOW = {
    "window_start": "2027-06-10T00:00:00Z",
    "window_end": "2027-06-10T04:00:00Z",
    "cause": "Upstream pricing feed unavailable",
}


def _deficient_plan_year_with_fresh_draft(api: ApiClient) -> dict:
    """A DEFICIENT plan year whose only attestation draft postdates the flip."""
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    fx.gag_compliant_contract(api, setup["tpa_contract"]["id"])
    pbm = fx.add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    fx.gag_non_compliant_contract(api, pbm["contract"]["id"], prohibited_clause_count=2)
    setup["pbm_contract"] = fx.read_contract(api, pbm["contract"]["id"])
    setup["attestation"] = fx.attestation_draft(
        api, plan_year_id, contract_terms_doc_count=3
    )
    setup["plan_year"] = fx.read_plan_year(api, plan_year_id)
    return setup


def _live_tool_with_one_window(api: ApiClient) -> dict:
    """A LIVE tool already carrying one four-hour outage window."""
    fx.set_clock(api, TOOL_LAUNCH_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    tool = fx.live_price_comparison_tool(
        api,
        setup["plan_year"]["id"],
        covered_items_count=800,
        sla_target_uptime_pct=99.00,
    )
    fx.set_clock(api, TOOL_APPEND_CLOCK)
    fx.append_outage_windows(api, tool["id"], [EXISTING_WINDOW])
    setup["tool"] = validate_success(
        api.get_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
    )
    return setup


class TestPostureGateOutranksSegregationOfDuties:
    """A deficient plan year answers on posture, whoever is calling."""

    def test_deficient_posture_pre_empts_both_duties_and_gag_checks(
        self, api: ApiClient
    ) -> None:
        """Three checks fail at once and only the highest one answers.

        PRD 2.9: "Because this gate outranks segregation of duties, a deficient
        plan year returns `ERR_POSTURE_BLOCKS_ATTESTATION` (409) even when the
        submitter is also the preparer."

        Design: Difficulty/priority_pair_validation_conflict/attestation_submit_posture_gate_outranks_segregation_of_duties
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = _deficient_plan_year_with_fresh_draft(api)
        assert setup["plan_year"]["compliance_posture"] == POSTURE_DEFICIENT

        response = api.submit_attestation(
            setup["attestation"]["id"],
            f.submit_attestation_payload(),
            OFFICER_PREPARER_HEADERS,
        )
        body = validate_error(response, ApiErrorId.POSTURE_BLOCKS_ATTESTATION)
        assert body["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES
        assert body["error_id"] != ApiErrorId.GAG_CLAUSES_OUTSTANDING

        unchanged = validate_success(
            api.get_attestation(
                setup["attestation"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert unchanged["status"] == ATTESTATION_DRAFT
        assert unchanged["submitted_by_user_id"] is None

        plan_year = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert plan_year["attestation_status"] == ATTESTATION_DRAFT
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT

    def test_posture_gate_also_answers_a_properly_segregated_submitter(
        self, api: ApiClient
    ) -> None:
        """The gate is about the plan year, not about who signs.

        PRD 3.8: "The plan year's `compliance_posture` must be either
        `COMPLIANT` or `AT_RISK`; a `FROZEN` plan year has already been refused,
        and a `DEFICIENT` one is refused with
        `ERR_POSTURE_BLOCKS_ATTESTATION` — and because that posture gate
        outranks the duties check, a deficient plan year returns the posture
        error even when the submitter happens to be the preparer."

        Design: Difficulty/priority_pair_validation_conflict/attestation_submit_posture_gate_outranks_segregation_of_duties
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = _deficient_plan_year_with_fresh_draft(api)

        response = api.submit_attestation(
            setup["attestation"]["id"],
            f.submit_attestation_payload(),
            OFFICER_SIGNER_HEADERS,
        )
        validate_error(response, ApiErrorId.POSTURE_BLOCKS_ATTESTATION)

    def test_the_same_self_submission_reports_duties_on_a_healthy_plan_year(
        self, api: ApiClient
    ) -> None:
        """With the posture rung satisfied, the lower rung is what answers.

        PRD 2.9: "**Segregation of duties.** The submitting `X-User-ID` differs
        from `prepared_by_user_id`; the accepting or rejecting auditor differs
        from both `prepared_by_user_id` and `submitted_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/attestation_submit_posture_gate_outranks_segregation_of_duties
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = fx.submittable_attestation_setup(api, covered_lives=6000)
        healthy = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert healthy["compliance_posture"] == POSTURE_COMPLIANT

        response = api.submit_attestation(
            setup["attestation"]["id"],
            f.submit_attestation_payload(),
            OFFICER_PREPARER_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)


class TestIntervalShapeOutranksOverlap:
    """An inverted window reports its shape, never a collision."""

    def test_inverted_and_overlapping_window_reports_the_shape_error(
        self, api: ApiClient
    ) -> None:
        """06:00Z to 02:00Z is refused for being backwards, not for colliding.

        PRD 3.3: "The ordering matters — a window that is both inverted and
        overlapping reports the shape error, not the collision error."

        Design: Difficulty/priority_pair_validation_conflict/outage_window_interval_shape_outranks_overlap_constraint
        """
        setup = _live_tool_with_one_window(api)
        tool_id = setup["tool"]["id"]

        response = api.append_outage_window(
            tool_id,
            f.outage_window_payload(
                window_start="2027-06-10T06:00:00Z",
                window_end="2027-06-10T02:00:00Z",
                cause="Mis-keyed incident report",
            ),
            PLATFORM_OPERATOR_HEADERS,
        )
        body = validate_error(response, ApiErrorId.INVALID_INTERVAL)
        assert body["error_id"] != ApiErrorId.OUTAGE_WINDOW_OVERLAP

        unchanged = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        assert len(unchanged["outage_windows"]) == 1
        assert unchanged["outage_windows"][0]["window_end"] == "2027-06-10T04:00:00Z"

    def test_zero_length_window_inside_an_existing_one_reports_the_shape_error(
        self, api: ApiClient
    ) -> None:
        """Equal endpoints fail the shape rule before collision is considered.

        PRD 3.3: "First the window's own shape: `window_end` must be strictly
        after `window_start`, or the append is refused with
        `ERR_INVALID_INTERVAL`."

        Design: Difficulty/priority_pair_validation_conflict/outage_window_interval_shape_outranks_overlap_constraint
        """
        setup = _live_tool_with_one_window(api)
        tool_id = setup["tool"]["id"]

        response = api.append_outage_window(
            tool_id,
            f.outage_window_payload(
                window_start="2027-06-10T02:00:00Z",
                window_end="2027-06-10T02:00:00Z",
                cause="Zero-length incident record",
            ),
            PLATFORM_OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_INTERVAL)
        unchanged = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        assert len(unchanged["outage_windows"]) == 1

    def test_well_shaped_overlap_does_report_the_collision(
        self, api: ApiClient
    ) -> None:
        """The lower rung answers once the shape rule is satisfied.

        PRD 3.3: "Then collision: because windows are half-open, a window
        beginning at exactly the instant an existing window ends is accepted,
        while any genuine intersection with an existing window of the same tool
        is refused with `ERR_OUTAGE_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/outage_window_interval_shape_outranks_overlap_constraint
        """
        setup = _live_tool_with_one_window(api)
        tool_id = setup["tool"]["id"]

        response = api.append_outage_window(
            tool_id,
            f.outage_window_payload(
                window_start="2027-06-10T02:00:00Z",
                window_end="2027-06-10T06:00:00Z",
                cause="Overlapping incident record",
            ),
            PLATFORM_OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.OUTAGE_WINDOW_OVERLAP)
        unchanged = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        assert len(unchanged["outage_windows"]) == 1


class TestFrozenParentOutranksChildState:
    """The freeze on the parent answers before the child's own state is judged."""

    def test_recertifying_a_certified_cycle_under_a_freeze_reports_the_freeze(
        self, api: ApiClient
    ) -> None:
        """The parent's lockdown is consulted before the addressed row.

        PRD 2.9: "**Frozen plan year.** The owning plan year's
        `compliance_posture` is not `FROZEN`, on every mutating endpoint scoped
        to a plan year except the five exemptions named in §2.8 — otherwise
        `ERR_PLAN_YEAR_FROZEN` (409)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_plan_year_outranks_invalid_state_transition
        """
        fx.set_clock(api, "2027-07-01T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        certified = fx.certified_refresh_cycle(
            api, plan_year_id, "2027-06", "2027-06-01", "2027-06-30"
        )["cycle"]
        assert certified["status"] == CYCLE_CERTIFIED
        assert certified["on_time"] is True
        fx.frozen_plan_year(api, plan_year_id)

        response = api.certify_refresh_cycle(
            certified["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
        )
        body = validate_error(response, ApiErrorId.PLAN_YEAR_FROZEN)
        assert body["error_id"] != ApiErrorId.INVALID_STATE_TRANSITION

        unchanged = validate_success(
            api.get_refresh_cycle(certified["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == CYCLE_CERTIFIED
        assert unchanged["on_time"] is True

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["freeze_flag"] is True
        assert plan_year["compliance_posture"] == POSTURE_FROZEN
        assert plan_year["deficiency_points"] == 0

    def test_state_error_surfaces_once_the_freeze_is_lifted(
        self, api: ApiClient
    ) -> None:
        """Underneath the freeze sits an ordinary illegal transition.

        PRD 2.9: "**State legality.** The addressed resource is in a state from
        which the requested transition or state-requiring action is declared,
        including any parent `lifecycle_status` precondition — otherwise
        `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_plan_year_outranks_invalid_state_transition
        """
        fx.set_clock(api, "2027-07-01T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        certified = fx.certified_refresh_cycle(
            api, plan_year_id, "2027-06", "2027-06-01", "2027-06-30"
        )["cycle"]
        fx.frozen_plan_year(api, plan_year_id)
        thawed = fx.unfrozen_plan_year(api, plan_year_id)
        assert thawed["compliance_posture"] == POSTURE_COMPLIANT

        response = api.certify_refresh_cycle(
            certified["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
        )
        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION)

    def test_freeze_also_outranks_the_published_files_requirement(
        self, api: ApiClient
    ) -> None:
        """A pending cycle with no postings still answers on the freeze.

        PRD 2.9: "**Published files for the period.** On refresh cycle
        certification only: a machine-readable file in `status` `PUBLISHED`
        exists for the same `plan_year_id` with `posting_month` equal to the
        cycle's `period_month`, for each of the two `file_type` values
        `IN_NETWORK_RATES` and `ALLOWED_AMOUNTS` — otherwise
        `ERR_MRF_NOT_PUBLISHED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_plan_year_outranks_invalid_state_transition
        """
        fx.set_clock(api, "2027-07-01T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pending = fx.open_refresh_cycle(
            api,
            plan_year_id,
            period_month="2027-06",
            period_start="2027-06-01",
            period_end="2027-06-30",
        )
        fx.frozen_plan_year(api, plan_year_id)

        response = api.certify_refresh_cycle(
            pending["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
        )
        body = validate_error(response, ApiErrorId.PLAN_YEAR_FROZEN)
        assert body["error_id"] != ApiErrorId.MRF_NOT_PUBLISHED
