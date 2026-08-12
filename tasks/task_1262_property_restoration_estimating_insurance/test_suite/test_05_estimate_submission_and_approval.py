"""Estimate submission gates, approval preconditions, and claim aggregates.

Covers the completed-inspection gate, the constraint-vs-temporal gate order at
submit, the price-window temporal gate, approval only from SUBMITTED, the
estimate-creation state gate, the one-INITIAL-estimate cap, and the claim-level
aggregate recomputation over the approved estimate set.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_claim_ctx, claim_to_assessing, claim_to_estimating, schedule_inspection,
    add_evidence_photos, add_reading, complete_inspection, make_estimate, add_line,
    read_estimate, read_claim, submit_estimate,
    setup_estimating_claim, setup_draft_estimate, setup_submitted_estimate,
    create_estimate_payload, create_estimate_line_payload, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

_WATER_POLICY = {"coverage_a_limit_cents": 100000000, "flat_deductible_cents": 100000}
_ACME_CARRIER = {"name": "Acme Mutual", "tax_rate": 0.07}


class TestCompletedInspectionGate:
    def test_estimate_submit_gated_by_completed_inspection(self, api):
        """PRD §3.5: "Next, the claim must carry at least one inspection in
        `COMPLETED` status (`ERR_INSPECTION_INCOMPLETE`, HTTP 422, priority 8)."
        PRD §3.5: "Submission cascades to the claim only for `INITIAL` estimates:
        while the claim is `ESTIMATING`, the claim moves `ESTIMATING → NEGOTIATING`
        with its `version` incremented."

        Design: Difficulty/cross_entity_state_dependency/estimate_submit_gated_by_completed_inspection
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides=_ACME_CARRIER,
                             policy_overrides=_WATER_POLICY)
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        insp = schedule_inspection(claim_id, assignee_id="tech-9")
        claim_to_estimating(ctx)
        estimate = make_estimate(claim_id)
        add_line(estimate["id"], ctx["entries"][0]["id"], 100)
        # a SCHEDULED inspection does not satisfy the gate
        validate_error(api.submit_estimate(estimate["id"], ESTIMATOR),
                       ApiErrorId.ERR_INSPECTION_INCOMPLETE)
        add_evidence_photos(claim_id, insp["id"], tags=("AREA", "AREA", "MOISTURE_PROOF"))
        add_reading(insp["id"], reading_value=18, dry_standard=12)
        complete_inspection(insp["id"])
        submitted = validate_success(api.submit_estimate(estimate["id"], ESTIMATOR), 200)
        assert submitted["status"] == "SUBMITTED"
        assert read_claim(claim_id)["status"] == "NEGOTIATING", \
            "INITIAL submit bubbles the claim up"

    def test_submit_with_no_inspection_at_all_fails_same_gate(self, api):
        """PRD §3.5: "Next, the claim must carry at least one inspection in
        `COMPLETED` status (`ERR_INSPECTION_INCOMPLETE`, HTTP 422, priority 8)."

        Design: Difficulty/cross_entity_state_dependency/estimate_submit_gated_by_completed_inspection
        """
        ctx = setup_draft_estimate(cause_of_loss="WATER",
                                   with_completed_inspection=False,
                                   carrier_overrides=_ACME_CARRIER,
                                   policy_overrides=_WATER_POLICY,
                                   line_specs=[(0, 100)])
        validate_error(api.submit_estimate(ctx["estimate"]["id"], ESTIMATOR),
                       ApiErrorId.ERR_INSPECTION_INCOMPLETE)


class TestConstraintBeatsTemporal:
    def test_inspection_constraint_beats_price_window_temporal(self, api):
        """PRD §3.5: "Next, the claim must carry at least one inspection in
        `COMPLETED` status (`ERR_INSPECTION_INCOMPLETE`, HTTP 422, priority 8)."
        PRD §3.5: "Last, the temporal gate (priority 9): every non-removed line's
        price list entry must cover the claim's `date_of_loss` within its half-open
        window — `effective_from` on or before the loss date and the loss date
        strictly before `effective_to` — else `ERR_PRICE_WINDOW_VIOLATION`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/inspection_constraint_beats_price_window_temporal
        """
        # No inspection at all; the single line's window starts after the loss.
        ctx = setup_draft_estimate(
            cause_of_loss="WATER", with_completed_inspection=False,
            carrier_overrides=_ACME_CARRIER, policy_overrides=_WATER_POLICY,
            entry_specs=({"category_code": "LATE-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 500,
                          "effective_from": "2026-06-01T00:00:00Z",
                          "effective_to": "2026-12-01T00:00:00Z"},),
            line_specs=[(0, 10)])
        # both gates fail; the priority-8 constraint must surface first
        validate_error(api.submit_estimate(ctx["estimate"]["id"], ESTIMATOR),
                       ApiErrorId.ERR_INSPECTION_INCOMPLETE)

    def test_canceled_inspection_still_fails_gate_before_temporal(self, api):
        """PRD §3.5: "Next, the claim must carry at least one inspection in
        `COMPLETED` status (`ERR_INSPECTION_INCOMPLETE`, HTTP 422, priority 8)."
        PRD §3.5: "Last, the temporal gate (priority 9): every non-removed line's
        price list entry must cover the claim's `date_of_loss` within its half-open
        window"

        Design: Difficulty/priority_pair_validation_conflict/inspection_constraint_beats_price_window_temporal
        """
        # A CANCELED inspection is not COMPLETED; the line's window also misses.
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides=_ACME_CARRIER,
                             policy_overrides=_WATER_POLICY,
                             entry_specs=({"category_code": "LATE-1",
                                           "trade": "GENERAL", "kind": "LABOR",
                                           "unit": "EA", "unit_price_cents": 500,
                                           "effective_from": "2026-06-01T00:00:00Z",
                                           "effective_to": "2026-12-01T00:00:00Z"},))
        claim_to_assessing(ctx)
        insp = schedule_inspection(ctx["claim"]["id"])
        get_cancel = validate_success(api.cancel_inspection(insp["id"],
                                                            TEST_USERS["field_technician_headers"]), 200)
        assert get_cancel["status"] == "CANCELED"
        claim_to_estimating(ctx)
        estimate = make_estimate(ctx["claim"]["id"])
        add_line(estimate["id"], ctx["entries"][0]["id"], 10)
        validate_error(api.submit_estimate(estimate["id"], ESTIMATOR),
                       ApiErrorId.ERR_INSPECTION_INCOMPLETE)


class TestPriceWindowGate:
    def test_price_window_violation_at_submit_returns_422(self, api):
        """PRD §3.5: "Last, the temporal gate (priority 9): every non-removed
        line's price list entry must cover the claim's `date_of_loss` within its
        half-open window — `effective_from` on or before the loss date and the loss
        date strictly before `effective_to` — else `ERR_PRICE_WINDOW_VIOLATION`
        (HTTP 422)."

        Design: Corner/validations/price_window_violation_at_submit_returns_422
        """
        # Inspection gate satisfied; only the temporal gate can fail.
        ctx = setup_draft_estimate(
            cause_of_loss="WATER", carrier_overrides=_ACME_CARRIER,
            policy_overrides=_WATER_POLICY, readings=[{"reading_value": 18}],
            entry_specs=({"category_code": "LATE-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 500,
                          "effective_from": "2026-06-01T00:00:00Z",
                          "effective_to": "2026-12-01T00:00:00Z"},),
            line_specs=[(0, 10)])
        validate_error(api.submit_estimate(ctx["estimate"]["id"], ESTIMATOR),
                       ApiErrorId.ERR_PRICE_WINDOW_VIOLATION)
        assert read_estimate(ctx["estimate"]["id"])["status"] == "DRAFT"


class TestApprovalPreconditions:
    def test_estimate_approve_from_draft_returns_invalid_state(self, api):
        """PRD §3.5: "An `Adjuster` may then approve the `SUBMITTED` estimate
        outright, deny it, or counter it."
        PRD §2.7: "**State-machine legality** — the requested transition or action
        exists from the resource's current state, and child-creation state gates
        are satisfied (`ERR_INVALID_STATE_TRANSITION`, `ERR_CLAIM_NOT_PAYABLE`,
        `ERR_SUPPLEMENT_NOT_PERMITTED`, `ERR_ESTIMATE_NOT_EDITABLE`,
        `ERR_INVOICE_NOT_ISSUABLE`, `ERR_ROUND_NOT_OPEN`)."

        Design: Corner/state_machines/estimate_approve_from_draft_returns_invalid_state
        """
        ctx = setup_draft_estimate(cause_of_loss="WATER",
                                   carrier_overrides=_ACME_CARRIER,
                                   policy_overrides=_WATER_POLICY,
                                   line_specs=[(0, 100)])
        res = api.approve_estimate(ctx["estimate"]["id"], ADJUSTER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert read_estimate(ctx["estimate"]["id"])["status"] == "DRAFT"

    def test_estimate_create_before_assessment_rejected(self, api):
        """PRD §3.4: "Creation requires the claim to be in `ASSESSING`,
        `ESTIMATING`, or `NEGOTIATING` (otherwise `ERR_INVALID_STATE_TRANSITION`)"

        Design: Corner/validations/estimate_create_before_assessment_rejected
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides=_ACME_CARRIER,
                             policy_overrides=_WATER_POLICY)
        # claim still INTAKE
        res = api.create_estimate(ctx["claim"]["id"],
                                  create_estimate_payload(ctx["claim"]["version"]),
                                  ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_second_initial_estimate_rejected(self, api):
        """PRD §3.4: "is capped at one `INITIAL` estimate per claim — a second
        attempt is rejected with `ERR_DUPLICATE_INITIAL_ESTIMATE` (HTTP 409)."

        Design: Corner/validations/second_initial_estimate_rejected
        """
        ctx = setup_draft_estimate(cause_of_loss="WATER",
                                   carrier_overrides=_ACME_CARRIER,
                                   policy_overrides=_WATER_POLICY,
                                   line_specs=[(0, 100)])
        claim = read_claim(ctx["claim"]["id"])
        # fresh claim version: the OCC check passes; uniqueness fires instead
        res = api.create_estimate(claim["id"],
                                  create_estimate_payload(claim["version"]),
                                  ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_INITIAL_ESTIMATE)


class TestClaimAggregates:
    def test_claim_aggregates_follow_estimate_approval(self, api):
        """PRD §3.4: "At the claim level, `rcv_total_cents`, `acv_total_cents`,
        and `recoverable_depreciation_cents` are recomputed whenever the approved
        estimate set changes: each is the sum of the same-named estimate figure
        over the claim's estimates in `APPROVED` or `LOCKED` status."
        PRD §3.4: "Estimates in `DRAFT`, `SUBMITTED`, `COUNTERED`, `REVISED`, or
        `DENIED` contribute nothing to claim aggregates."

        Design: Corner/cross_cutting_layers/claim_aggregates_follow_estimate_approval
        """
        ctx = setup_draft_estimate(
            cause_of_loss="FIRE",
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0},),
            line_specs=[(0, 100)])
        claim_id = ctx["claim"]["id"]
        assert read_claim(claim_id)["rcv_total_cents"] == 0, "DRAFT contributes nothing"
        submit_estimate(ctx["estimate"]["id"])
        assert read_claim(claim_id)["rcv_total_cents"] == 0, \
            "SUBMITTED still not counted"
        approved = validate_success(api.approve_estimate(ctx["estimate"]["id"],
                                                         ADJUSTER), 200)
        assert approved["status"] == "APPROVED"
        claim = read_claim(claim_id)
        assert claim["rcv_total_cents"] == 20000
        assert claim["acv_total_cents"] == 20000, "depreciation 0 -> acv == rcv"
