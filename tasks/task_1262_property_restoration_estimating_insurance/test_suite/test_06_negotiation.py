"""Adjuster negotiation rounds: counter-offers, dispositions, expiry, OCC.

Covers the cyclic estimate machine (SUBMITTED -> COUNTERED -> REVISED ->
SUBMITTED), disposition accept/reject semantics, the deemed-acceptance expiry
sweep, line-membership validation, the resolved-round gate, and the disposition
append OCC rule.
"""
from datetime import datetime
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_submitted_estimate, make_countered_estimate, read_estimate, read_claim,
    create_append_dispositions_payload, create_respond_payload,
    create_negotiation_round_payload, set_logical_clock, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestNegotiationCycle:
    def test_estimate_negotiation_revision_cycle(self, api):
        """PRD §3.5: "A `REJECT` moves the disposition to `REJECTED`, leaves the
        line `DISPUTED` and the estimate `COUNTERED`, awaiting revision or
        concession; the round still auto-resolves when nothing remains `PENDING`."
        PRD §3.5: "Alternatively the `Estimator` may revise the `COUNTERED`
        estimate, moving it to `REVISED` and reverting all `DISPUTED` lines to
        `PENDING` for re-editing under §3.4."
        PRD §3.5: "The round's `disputed_amount_cents` is recomputed as
        dispositions are added or answered: for each `PENDING` disposition,
        multiply the proposed quantity by the proposed unit price — each falling
        back to the line's current value when that proposal is null — round the
        product half up to integer cents, take the absolute difference against the
        line's current `extended_cents`, and sum those differences."

        Design: Difficulty/non_linear_state_machine/estimate_negotiation_revision_cycle
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 1000)])
        line_id = ctx["lines"][0]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line_id,
                                       "proposed_qty": 900}])
        assert ctx["round"]["disputed_amount_cents"] == 20000, \
            "|200,000 - round(900*200)|"
        disp_id = ctx["dispositions"][0]["id"]
        rejected = validate_success(api.respond_to_disposition(
            disp_id, create_respond_payload("REJECT"), ESTIMATOR), 200)
        assert rejected["status"] == "REJECTED"
        round_after = validate_success(
            api.get_negotiation_round(ctx["round"]["id"], ADJUSTER), 200)
        assert round_after["status"] == "RESOLVED", \
            "auto-resolved when its last PENDING disposition was answered"
        assert read_estimate(ctx["estimate"]["id"])["status"] == "COUNTERED", \
            "REJECT leaves the estimate COUNTERED; a revise edge is required"

        revised = validate_success(api.revise_estimate(ctx["estimate"]["id"],
                                                       ESTIMATOR), 200)
        assert revised["status"] == "REVISED"
        patched = validate_success(api.patch_estimate_line(
            ctx["estimate"]["id"], line_id,
            {"expected_estimate_version": revised["version"], "qty": 950},
            ESTIMATOR), 200)
        assert patched["negotiation_status"] == "PENDING", \
            "revise reverted the disputed line to PENDING"
        resubmitted = validate_success(api.submit_estimate(ctx["estimate"]["id"],
                                                           ESTIMATOR), 200)
        assert resubmitted["status"] == "SUBMITTED", \
            "cycle SUBMITTED->COUNTERED->REVISED->SUBMITTED traversed"
        validate_success(api.approve_estimate(ctx["estimate"]["id"], ADJUSTER), 200)
        claim = read_claim(ctx["claim"]["id"])
        assert claim["rcv_total_cents"] == 190000, "revised qty 950 x 200c"
        assert claim["status"] == "APPROVED"

    def test_concede_applies_pending_dispositions_and_approves(self, api):
        """PRD §3.5: "Instead of answering line by line, the `Estimator` holding a
        `COUNTERED` estimate with an `OPEN` round may concede: every `PENDING`
        disposition is applied at its proposed values under the same rules as
        `ACCEPT`, the round moves to `RESOLVED`, totals are recomputed, and the
        estimate moves `COUNTERED → APPROVED` with the same claim-side effects as
        an approval."

        Design: Difficulty/non_linear_state_machine/estimate_negotiation_revision_cycle
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 1000)])
        line_id = ctx["lines"][0]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line_id,
                                       "proposed_qty": 900}])
        conceded = validate_success(api.concede_estimate(ctx["estimate"]["id"],
                                                         ESTIMATOR), 200)
        assert conceded["status"] == "APPROVED"
        round_after = validate_success(
            api.get_negotiation_round(ctx["round"]["id"], ADJUSTER), 200)
        assert round_after["status"] == "RESOLVED"
        claim = read_claim(ctx["claim"]["id"])
        assert claim["rcv_total_cents"] == 180000, "proposed qty 900 applied"
        assert claim["status"] == "APPROVED"


class TestDispositionGuards:
    def test_disposition_double_respond_returns_invalid_state(self, api):
        """PRD §3.5: "Two state checks guard the answer, and within priority 6 they
        run in a fixed order: the disposition's own status is checked first —
        answering a non-`PENDING` disposition is `ERR_INVALID_STATE_TRANSITION` —
        and only then the round's status, a non-`OPEN` round yielding
        `ERR_ROUND_NOT_OPEN`."
        PRD §3.5: "When an answer leaves no `PENDING` dispositions, the round
        auto-resolves to `RESOLVED`, and if every disposition was `ACCEPTED` the
        estimate auto-approves with exactly the application, totals, and
        claim-side effects of an approval or concession."

        Design: Corner/state_machines/disposition_double_respond_returns_invalid_state
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 1000)])
        line_id = ctx["lines"][0]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line_id,
                                       "proposed_qty": 900}])
        disp_id = ctx["dispositions"][0]["id"]
        answered = validate_success(api.respond_to_disposition(
            disp_id, create_respond_payload("ACCEPT"), ESTIMATOR), 200)
        assert answered["status"] == "ACCEPTED"
        res = api.respond_to_disposition(disp_id, create_respond_payload("ACCEPT"),
                                         ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        est = read_estimate(ctx["estimate"]["id"])
        assert est["status"] == "APPROVED", "all-accept auto-approval"
        assert est["rcv_total_cents"] == 180000, "proposed qty 900 applied"

    def test_disposition_for_other_estimates_line_rejected(self, api):
        """PRD §3.5: "Every targeted line must belong to this estimate, else the
        whole counter-offer is rejected with `ERR_DISPOSITION_LINE_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/disposition_for_other_estimates_line_rejected
        """
        ctx_a = setup_submitted_estimate(line_specs=[(0, 100)])
        # a second claim with its own estimate + line: the line exists but does
        # not belong to the round's estimate
        ctx_b = setup_submitted_estimate(
            line_specs=[(0, 50)], policy_number="POL-OTHER")
        foreign_line_id = ctx_b["lines"][0]["id"]
        res = api.create_negotiation_round(
            ctx_a["estimate"]["id"],
            create_negotiation_round_payload(
                [{"estimate_line_id": foreign_line_id, "proposed_qty": 5}]),
            ADJUSTER)
        validate_error(res, ApiErrorId.ERR_DISPOSITION_LINE_MISMATCH)

    def test_disposition_add_to_resolved_round_returns_round_not_open(self, api):
        """PRD §3.5: "While the round is `OPEN` the `Adjuster` may append further
        dispositions through the OCC-guarded append of §2.9, which takes
        `expected_negotiation_round_version`, requires the round `OPEN`
        (`ERR_ROUND_NOT_OPEN`, HTTP 409)"

        Design: Corner/validations/disposition_add_to_resolved_round_returns_round_not_open
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 1000)])
        line_id = ctx["lines"][0]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line_id,
                                       "proposed_qty": 900}])
        disp_id = ctx["dispositions"][0]["id"]
        validate_success(api.respond_to_disposition(
            disp_id, create_respond_payload("ACCEPT"), ESTIMATOR), 200)
        round_after = validate_success(
            api.get_negotiation_round(ctx["round"]["id"], ADJUSTER), 200)
        assert round_after["status"] == "RESOLVED"
        # current OCC version does not save the append: the round gate fires
        res = api.append_dispositions(
            ctx["round"]["id"],
            create_append_dispositions_payload(
                round_after["version"],
                [{"estimate_line_id": line_id, "proposed_qty": 800}]),
            ADJUSTER)
        validate_error(res, ApiErrorId.ERR_ROUND_NOT_OPEN)

    def test_occ_disposition_add_stale_round_version(self, api):
        """PRD §2.9: "**Disposition append** — `POST
        /v1/negotiation-rounds/{id}/dispositions` requires
        `expected_negotiation_round_version` matching the round's current
        `version`."
        PRD §2.9: "A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_disposition_add_stale_round_version
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 100), (0, 50)])
        line1, line2 = ctx["lines"][0]["id"], ctx["lines"][1]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line1,
                                       "proposed_qty": 90}])
        round_id = ctx["round"]["id"]
        observed = ctx["round"]["version"]
        appended = validate_success(api.append_dispositions(
            round_id,
            create_append_dispositions_payload(
                observed, [{"estimate_line_id": line2, "proposed_qty": 45}]),
            ADJUSTER), 201)
        assert appended["version"] == observed + 1
        res = api.append_dispositions(
            round_id,
            create_append_dispositions_payload(
                observed, [{"estimate_line_id": line2, "proposed_qty": 40}]),
            ADJUSTER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


class TestDeemedAcceptance:
    def test_round_expiry_deemed_acceptance_approves_estimate(self, api):
        """PRD §3.5: "Finally, the deemed-acceptance sweep: when the logical clock
        is advanced past an `OPEN` round's `due_at` (§2.4), the round expires to
        `EXPIRED`, every `PENDING` disposition is auto-accepted at its proposed
        values, and the estimate auto-approves with the full claim-side effects —
        the carrier's silence is treated as acceptance."
        PRD §2.4: "At server startup the logical clock reads exactly
        2026-05-01T00:00:00Z."
        PRD §3.5: "The round is created `OPEN`, recording the countered estimate in
        its `estimate_id`, with a per-estimate `round_number` — one greater than
        the highest round number on the estimate — and a `due_at` of its creation
        time plus the carrier's `negotiation_response_days` days."

        Design: Corner/state_machines/round_expiry_deemed_acceptance_approves_estimate
        """
        ctx = setup_submitted_estimate(
            carrier_overrides={"name": "ZeroTax Mutual", "tax_rate": 0,
                               "negotiation_response_days": 7},
            line_specs=[(0, 1000)])
        line_id = ctx["lines"][0]["id"]
        make_countered_estimate(ctx, [{"estimate_line_id": line_id,
                                       "proposed_qty": 900}])
        round_id = ctx["round"]["id"]
        # created at the default clock 2026-05-01 + 7 days
        assert _parse(ctx["round"]["due_at"]) == _parse("2026-05-08T00:00:00Z")
        clock = set_logical_clock("2026-05-09T00:00:00Z")
        assert round_id in clock["expired_round_ids"]
        round_after = validate_success(api.get_negotiation_round(round_id, ADJUSTER), 200)
        assert round_after["status"] == "EXPIRED"
        est = read_estimate(ctx["estimate"]["id"])
        assert est["status"] == "APPROVED", "deemed acceptance applied proposed qty 900"
        assert est["rcv_total_cents"] == 180000
        assert read_claim(ctx["claim"]["id"])["status"] == "APPROVED"
