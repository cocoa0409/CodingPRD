"""Certificate-of-analysis review: findings, deviation scores, close guards."""

from test_helpers import (
    QM_1,
    QM_2,
    SQE_1,
    ApiErrorId,
    assert_finding,
    assert_qty,
    close_coa_review_response,
    create_coa_payload,
    disposition_finding,
    register_coa,
    setup_source_with_contract,
    start_coa_review,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_PARAM_SPEC = [
    {"parameter_name": "moisture", "criticality": "MAJOR", "uom": "percent",
     "target_value": 4, "min_value": 0, "max_value": 8},
    {"parameter_name": "purity", "criticality": "CRITICAL", "uom": "percent",
     "target_value": 97, "min_value": 95, "max_value": 100},
]


def _setup_two_finding_coa():
    """CoA lot with moisture 9.2 (MAJOR, band [0, 8]) and purity 93.5 (CRITICAL,
    band [95, 100]) — two out-of-spec findings — under review."""
    ctx = setup_source_with_contract(
        "ENZ-1", supplier_code="SUP-1", parameters=TWO_PARAM_SPEC,
        contract_kwargs={
            "annual_committed_volume_kg": 60000,
            "index_base_value": 200,
            "index_pass_through_pct": 0.6,
        },
    )
    coa = register_coa(
        ctx["source"]["id"], ctx["contract"]["id"],
        lot_number="L1", shipped_qty_kg=1000, received_at="2026-08-01T00:00:00Z",
        measured_values=[
            {"parameter_name": "moisture", "observed_value": 9.2},
            {"parameter_name": "purity", "observed_value": 93.5},
        ],
        registrar_id=SQE_1,
    )
    under_review, findings = start_coa_review(ctx["source"]["id"], coa["id"], qm_id=QM_1)
    ctx["coa"] = coa
    ctx["under_review"] = under_review
    ctx["findings"] = findings
    return ctx


def _find_by_param(findings, name):
    return [f for f in findings if f["parameter_name"] == name][0]


class TestDeviationScoreDualVariant:
    def test_provisional_and_final_scores_diverge_on_downgrade(self, api):
        """PRD §3.7: "The **provisional** variant, computed when the CoA enters
        `UNDER_REVIEW`, weights every finding at its snapshot `criticality_at_finding`
        regardless of disposition. The **final** variant, computed when the review
        closes, weights any finding dispositioned `DOWNGRADED_TO_MINOR` as `MINOR`
        (weight 1) regardless of its snapshot criticality; findings dispositioned
        `REJECT_LOT` still count at full weight. Provisional and final diverge
        whenever any finding is downgraded." — moisture 0.1500 x 2 plus purity
        0.3000 x 3 gives provisional 120.00; downgrading moisture to weight 1 gives
        final 105.00 for identical measured values.

        Design: Difficulty/dual_variant_calc/coa_deviation_score_provisional_vs_final_diverge
        """
        ctx = _setup_two_finding_coa()
        source_id, coa_id = ctx["source"]["id"], ctx["coa"]["id"]
        assert_qty(ctx["under_review"]["provisional_deviation_score"], 120.0, places=2)

        moisture = _find_by_param(ctx["findings"], "moisture")
        purity = _find_by_param(ctx["findings"], "purity")
        disposition_finding(source_id, coa_id, moisture["id"], "DOWNGRADED_TO_MINOR", note="minor practical impact")
        disposition_finding(source_id, coa_id, purity["id"], "ACCEPT_AS_IS", note="customer waiver on file")

        closed = validate_success(close_coa_review_response(source_id, coa_id, "ACCEPT", closer_id=QM_2))
        assert_qty(closed["final_deviation_score"], 105.0, places=2)
        assert abs(float(closed["final_deviation_score"]) - float(ctx["under_review"]["provisional_deviation_score"])) > 0.001, (
            "the two variants must diverge when a finding is downgraded"
        )

    def test_conditional_acceptance_and_finding_snapshots(self, api):
        """PRD §3.6: "the finding snapshots `parameter_name`, `observed_value`, the
        `violated_bound` (the min or max bound that was exceeded), and
        `criticality_at_finding` copied from the spec parameter. Findings are
        persisted in the spec's parameter creation order, and the findings list
        endpoint returns them in that same order — deterministic, with no id-based
        ordering." and "lands the CoA in `ACCEPTED` status — or in
        `CONDITIONALLY_ACCEPTED` if at least one finding carries disposition
        `ACCEPT_AS_IS`."

        Design: Difficulty/dual_variant_calc/coa_deviation_score_provisional_vs_final_diverge
        """
        ctx = _setup_two_finding_coa()
        source_id, coa_id = ctx["source"]["id"], ctx["coa"]["id"]
        findings = ctx["findings"]
        assert len(findings) == 2
        # Parameter creation order: moisture first, purity second.
        assert findings[0]["parameter_name"] == "moisture"
        assert findings[1]["parameter_name"] == "purity"
        for row in findings:
            assert_finding(row)
        moisture, purity = findings[0], findings[1]
        assert_qty(moisture["violated_bound"], 8, places=4)
        assert_qty(moisture["excess_ratio"], 0.15, places=4)
        assert moisture["criticality_at_finding"] == "MAJOR"
        assert_qty(purity["violated_bound"], 95, places=4)
        assert_qty(purity["excess_ratio"], 0.3, places=4)
        assert purity["criticality_at_finding"] == "CRITICAL"

        disposition_finding(source_id, coa_id, moisture["id"], "DOWNGRADED_TO_MINOR", note="minor practical impact")
        disposition_finding(source_id, coa_id, purity["id"], "ACCEPT_AS_IS", note="customer waiver on file")
        closed = validate_success(close_coa_review_response(source_id, coa_id, "ACCEPT", closer_id=QM_2))
        assert closed["status"] == "CONDITIONALLY_ACCEPTED", (
            "one ACCEPT_AS_IS finding lands the CoA in CONDITIONALLY_ACCEPTED"
        )


class TestDeviationScoreBoundary:
    def _setup_ash_coa(self, observed):
        ctx = setup_source_with_contract(
            "MIN-1", supplier_code="SUP-M",
            parameters=[{
                "parameter_name": "ash", "criticality": "MAJOR", "uom": "percent",
                "target_value": 1, "min_value": 0, "max_value": 2,
            }],
            contract_kwargs={
                "annual_committed_volume_kg": 10000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
        )
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="ASH-1", shipped_qty_kg=100, received_at="2026-08-01T00:00:00Z",
            measured_values=[{"parameter_name": "ash", "observed_value": observed}],
        )
        under_review, findings = start_coa_review(ctx["source"]["id"], coa["id"])
        ctx["coa"] = coa
        ctx["under_review"] = under_review
        ctx["findings"] = findings
        return ctx

    def test_deviation_score_exactly_150_blocks_accept(self, api):
        """PRD §3.6: "the deviation score must be strictly below 150 (exactly 150
        blocks the accept; `ERR_DEVIATION_SCORE_TOO_HIGH`)" and "The score check is
        satisfied either by a `provisional_deviation_score` strictly below 150, or,
        when the provisional score is at or above 150, by all findings being
        dispositioned `ACCEPT_AS_IS` with the recomputed final score strictly below
        150." — ash 3.5 on MAJOR [0, 2]: excess 0.7500 x 2 x 100 = 150.00, which is
        NOT strictly below 150 on either variant.

        Design: Difficulty/boundary_precision_check/deviation_score_exactly_150_blocks_accept
        """
        ctx = self._setup_ash_coa(3.5)
        assert_qty(ctx["under_review"]["provisional_deviation_score"], 150.0, places=2)
        disposition_finding(
            ctx["source"]["id"], ctx["coa"]["id"], ctx["findings"][0]["id"],
            "ACCEPT_AS_IS", note="process capability waiver",
        )
        resp = close_coa_review_response(ctx["source"]["id"], ctx["coa"]["id"], "ACCEPT", closer_id=QM_2)
        validate_error(resp, ApiErrorId.ERR_DEVIATION_SCORE_TOO_HIGH)

    def test_deviation_score_just_below_150_accepts(self, api):
        """PRD §3.6: "the deviation score must be strictly below 150 (exactly 150
        blocks the accept; `ERR_DEVIATION_SCORE_TOO_HIGH`)" — ash 3.4998 on MAJOR
        [0, 2]: excess 0.7499 x 2 x 100 = 149.98 is strictly below the ceiling, so
        the accept proceeds and lands in `CONDITIONALLY_ACCEPTED` (one
        `ACCEPT_AS_IS` finding).

        Design: Difficulty/boundary_precision_check/deviation_score_exactly_150_blocks_accept
        """
        ctx = self._setup_ash_coa(3.4998)
        assert_qty(ctx["under_review"]["provisional_deviation_score"], 149.98, places=2)
        disposition_finding(
            ctx["source"]["id"], ctx["coa"]["id"], ctx["findings"][0]["id"],
            "ACCEPT_AS_IS", note="process capability waiver",
        )
        closed = validate_success(
            close_coa_review_response(ctx["source"]["id"], ctx["coa"]["id"], "ACCEPT", closer_id=QM_2)
        )
        assert closed["status"] == "CONDITIONALLY_ACCEPTED"


class TestCoARegistrationAndCloseGuards:
    def test_measured_values_incomplete_rejected(self, api, sqe_headers):
        """PRD §3.6: "an array of `(parameter_name, observed_value)` pairs that must
        cover every spec parameter of the source's pinned spec exactly once, with
        each `observed_value` numeric. Registration is rejected with
        `ERR_MEASURED_VALUES_INCOMPLETE` if the coverage is wrong, with
        `ERR_SOURCE_NOT_ACTIVE` if the source is not `ACTIVE`, and with
        `ERR_INVALID_REQUEST` if `shipped_qty_kg` is not positive."

        Design: Corner/validations/measured_values_incomplete_rejected
        """
        ctx = setup_source_with_contract(
            "ENZ-MVC", supplier_code="SUP-MVC", parameters=TWO_PARAM_SPEC,
            contract_kwargs={
                "annual_committed_volume_kg": 5000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
        )
        resp = api.register_coa(
            ctx["source"]["id"],
            create_coa_payload(
                ctx["contract"]["id"],
                [{"parameter_name": "moisture", "observed_value": 5}],  # purity missing
                lot_number="MVC-1",
            ),
            sqe_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEASURED_VALUES_INCOMPLETE)

    def test_findings_undispositioned_blocks_close(self, api):
        """PRD §3.6: "Every finding must have a disposition other than `REPORTED`
        (otherwise `ERR_FINDINGS_UNDISPOSITIONED`)."

        Design: Corner/validations/findings_undispositioned_blocks_close
        """
        ctx = setup_source_with_contract(
            "ENZ-UND", supplier_code="SUP-UND",
            parameters=[{
                "parameter_name": "purity", "criticality": "CRITICAL", "uom": "percent",
                "target_value": 97, "min_value": 95, "max_value": 100,
            }],
            contract_kwargs={
                "annual_committed_volume_kg": 5000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
        )
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="UND-1", measured_values=[{"parameter_name": "purity", "observed_value": 93.5}],
        )
        start_coa_review(ctx["source"]["id"], coa["id"])
        # Finding left in REPORTED; close attempted by a QualityManager who is not
        # the registrar so only the undisposed-findings guard can fire.
        resp = close_coa_review_response(ctx["source"]["id"], coa["id"], "REJECT", closer_id=QM_2)
        validate_error(resp, ApiErrorId.ERR_FINDINGS_UNDISPOSITIONED)

    def test_accept_with_reject_lot_finding_blocked(self, api):
        """PRD §3.6: "For `outcome=ACCEPT`, two further guards apply: no finding may
        have disposition `REJECT_LOT` (otherwise `ERR_FINDINGS_REQUIRE_REJECTION`),
        and the deviation score must be strictly below 150 (exactly 150 blocks the
        accept; `ERR_DEVIATION_SCORE_TOO_HIGH`)." — moisture 10.5 on MINOR [0, 10]
        scores 5.00, well under the ceiling, yet the REJECT_LOT finding blocks the
        accept.

        Design: Corner/validations/accept_with_reject_lot_finding_blocked
        """
        ctx = setup_source_with_contract("ENZ-RL", supplier_code="SUP-RL")
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="RL-1", measured_values=[{"parameter_name": "moisture", "observed_value": 10.5}],
        )
        _under_review, findings = start_coa_review(ctx["source"]["id"], coa["id"])
        assert len(findings) == 1
        disposition_finding(
            ctx["source"]["id"], coa["id"], findings[0]["id"],
            "REJECT_LOT", note="customer spec violation",
        )
        resp = close_coa_review_response(ctx["source"]["id"], coa["id"], "ACCEPT", closer_id=QM_2)
        validate_error(resp, ApiErrorId.ERR_FINDINGS_REQUIRE_REJECTION)

    def test_coa_provisional_score_zero_when_no_findings(self, api, quality_manager_headers):
        """PRD §3.6: "On entry the system creates one `CoAOutOfSpecFinding` per
        measured parameter whose `observed_value` falls outside the pinned spec's
        inclusive `[min_value, max_value]` range." and "The provisional deviation
        score is then computed (see below) and stored on
        `provisional_deviation_score`." — an in-spec lot produces zero findings and
        an empty sum, i.e. score 0.

        Design: Corner/calculations/coa_provisional_score_zero_when_no_findings
        """
        ctx = setup_source_with_contract("ENZ-ZERO", supplier_code="SUP-Z")
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="Z1", measured_values=[{"parameter_name": "moisture", "observed_value": 5}],
        )
        under_review, findings = start_coa_review(ctx["source"]["id"], coa["id"])
        assert_qty(under_review["provisional_deviation_score"], 0, places=2)
        assert findings == []
        _rows, meta = validate_paginated(
            api.list_coa_findings(ctx["source"]["id"], coa["id"], quality_manager_headers)
        )
        assert meta["total_count"] == 0


class TestCoASegregationAndRole:
    def test_segregation_registrar_cannot_close_own_coa(self, api):
        """PRD §2.11: "The `QualityManager` closing a CoA review must not be the
        CoA's registrar (the `SupplierQualityEngineer` whose `X-User-ID` matches
        `registered_by_user_id`)."

        Design: Corner/state_machines/segregation_registrar_cannot_close_own_coa
        """
        ctx = setup_source_with_contract("ENZ-SC", supplier_code="SUP-SC")
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="SOD-1", measured_values=[{"parameter_name": "moisture", "observed_value": 5}],
            registrar_id=SQE_1,
        )
        start_coa_review(ctx["source"]["id"], coa["id"], qm_id=QM_1)
        # QualityManager role, but the operator id equals registered_by_user_id.
        resp = close_coa_review_response(ctx["source"]["id"], coa["id"], "ACCEPT", closer_id=SQE_1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rbac_sqe_cannot_close_coa_review(self, api, sqe_headers):
        """PRD §2.1: "a role that is not permitted for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.12 orders the role check ahead of
        segregation-of-duties ("then forbidden role; ... then
        segregation-of-duties"). PRD §4 restricts close-review to QualityManager.

        Design: Corner/roles/rbac_sqe_cannot_close_coa_review
        """
        ctx = setup_source_with_contract("RBAC-5", supplier_code="RBAC-S5")
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="RBAC-L5", measured_values=[{"parameter_name": "moisture", "observed_value": 5}],
        )
        start_coa_review(ctx["source"]["id"], coa["id"])
        resp = api.close_coa_review(ctx["source"]["id"], coa["id"], {"outcome": "ACCEPT"}, sqe_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
