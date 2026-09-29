"""The decision instrument and its signature: the two obligation readings, the
pinned fiscal pass that produces them, the objection window the signature opens,
and the gates — state, document, commitment, ceiling, role and identity — that a
signature must clear.
"""
from test_helpers import (
    DECIDING_OFFICIAL_HEADERS,
    DECIDING_OFFICIAL_USER_ID,
    DEFAULT_MAX_BINDING_OBLIGATION_CENTS,
    DEFAULT_OBJECTION_WINDOW_DAYS,
    NEPA_COORDINATOR_HEADERS,
    NEPA_COORDINATOR_USER_ID,
    POLICY_ADMIN_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    approx_score,
    assert_decision,
    assert_instant_equals,
    assert_mitigation,
    assert_office_ledger_equals,
    assert_scores_differ,
    entries_with_code,
    fixtures,
    make_deciding_official_headers,
    mitigation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A single commitment whose one-time cost alone approaches the office ceiling,
#: used to put the fiscal band in conflict with the state band.
CAP_BREACHING_COMMITMENT = {
    "measure_text": "Full acquisition of the winter range parcel",
    "cost_estimate_cents": 950000000,
    "monitoring_years": 0,
    "annual_monitoring_cost_cents": 0,
    "reduction_points": 4.0,
}

#: A commitment that sits under the ceiling on its own cost but is pushed past
#: it by the contingency fee.
FEE_BREACHING_COMMITMENT = {
    "measure_text": "Acquire and endow the Ridgeline conservation easement",
    "cost_estimate_cents": 890000000,
    "monitoring_years": 0,
    "annual_monitoring_cost_cents": 0,
    "reduction_points": 4.0,
}

#: Two identical monitoring streams, each landing exactly on a half cent.
TWIN_HALF_CENT_COMMITMENTS = [
    {"measure_text": "Seasonal closure of the winter range unit",
     "cost_estimate_cents": 1200000, "monitoring_years": 3,
     "annual_monitoring_cost_cents": 4500, "reduction_points": 9.0},
    {"measure_text": "Second-season closure of the calving unit",
     "cost_estimate_cents": 1200000, "monitoring_years": 3,
     "annual_monitoring_cost_cents": 4500, "reduction_points": 9.0},
]


def _sign(client, decision_id, headers=DECIDING_OFFICIAL_HEADERS):
    return client.sign_decision(decision_id, headers)


class TestObligationReadings:
    """Two readings of the same commitment set: the narrow committed cost and the
    full lifecycle exposure."""

    def test_the_two_readings_diverge_by_the_escalated_stream_and_the_fee(
        self, client
    ):
        """The same two commitments report 3300000 cents committed and 3487823
        cents binding, a divergence of 187823 cents.

        PRD 3.9: "First, `committed_obligation_cents` is the sum of
        `cost_estimate_cents` over the decision's commitments whose `status` is
        `BINDING`, with no monitoring escalation and no contingency fee; it is the
        narrower of the two obligation readings and is always at or below
        `binding_obligation_cents` on identical commitment rows."
        PRD 3.9: "Second, `base_obligation_cents` is the sum of
        `lifecycle_obligation_cents` over those same binding commitments;
        commitments still `PROPOSED` and commitments already `RELEASED` are
        excluded from both sums."

        Design: Difficulty/dual_variant_calc/decision_obligation_commitment_only_vs_lifecycle_divergence
        """
        ctx = fixtures.setup_signed_mitigated_fonsi()
        decision = ctx["decision"]
        first, second = ctx["mitigations"]

        assert decision["status"] == "SIGNED"
        assert_decision(decision)
        assert decision["committed_obligation_cents"] == 3300000, (
            "the committed reading is the plain sum of the two one-time costs"
        )
        assert fixtures.read_mitigation(first["id"])[
            "lifecycle_obligation_cents"] == 1213973
        assert fixtures.read_mitigation(second["id"])[
            "lifecycle_obligation_cents"] == 2107763
        assert decision["base_obligation_cents"] == 3321736, (
            "the lifecycle reading adds each commitment's escalated monitoring "
            "stream"
        )
        assert decision["contingency_fee_cents"] == 166087
        assert decision["binding_obligation_cents"] == 3487823
        assert (decision["binding_obligation_cents"]
                - decision["committed_obligation_cents"]) == 187823, (
            "the escalated streams and the contingency fee account for the whole "
            "divergence between the two readings"
        )
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]),
                                   3487823)

    def test_neither_reading_is_populated_before_the_signature_pins_them(
        self, client
    ):
        """Both readings stay at zero on the draft that already carries the two
        commitments, and the signature is what separates them.

        PRD 3.9: "The commitment begins with `status` `PROPOSED` and
        `monitoring_status` `NOT_REQUIRED`, and attaching it increments the
        decision's `version` by one."
        PRD 3.9: "Second, `base_obligation_cents` is the sum of
        `lifecycle_obligation_cents` over those same binding commitments;
        commitments still `PROPOSED` and commitments already `RELEASED` are
        excluded from both sums."

        Design: Difficulty/dual_variant_calc/decision_obligation_commitment_only_vs_lifecycle_divergence
        """
        ctx = fixtures.setup_drafted_decision(
            decision_type="MITIGATED_FONSI",
            mitigations=fixtures.CANONICAL_MITIGATIONS,
        )
        drafted = ctx["decision"]
        assert drafted["status"] == "DRAFT"
        assert drafted["committed_obligation_cents"] == 0, (
            "a proposed commitment contributes to neither reading"
        )
        assert drafted["base_obligation_cents"] == 0
        assert drafted["binding_obligation_cents"] == 0
        for commitment in ctx["mitigations"]:
            assert commitment["status"] == "PROPOSED"
            assert_mitigation(commitment)
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        signed = validate_success(_sign(client, drafted["id"]))
        assert signed["status"] == "SIGNED"
        assert signed["committed_obligation_cents"] == 3300000
        assert signed["binding_obligation_cents"] == 3487823
        assert signed["committed_obligation_cents"] < signed[
            "binding_obligation_cents"], (
            "the narrower reading sits below the lifecycle reading on the same "
            "commitment rows"
        )
        for commitment in ctx["mitigations"]:
            moved = fixtures.read_mitigation(commitment["id"])
            assert moved["status"] == "BINDING"
            assert moved["monitoring_status"] == "SCHEDULED", (
                "each commitment carries three monitoring years"
            )


class TestMonitoringStreamRounding:
    """The monitoring stream is rounded once per commitment, before any
    summation."""

    def test_each_stream_is_rounded_before_the_base_is_summed(self, client):
        """Two streams landing on a half cent round up individually, so the base
        is 3321736 rather than the 3321735 a single late rounding would give.

        PRD 3.9: "The undiscounted monitoring stream is `monitoring_years`
        multiplied by `annual_monitoring_cost_cents` and then by the office's
        `monitoring_escalation_factor`; that product is rounded half up to whole
        cents on its own, and `lifecycle_obligation_cents` is
        `cost_estimate_cents` plus the rounded stream."
        PRD 3.9: "Rounding once per commitment before any summation is the pinned
        order described in §2.8."

        Design: Difficulty/combinatorial_formula/mode_b_monitoring_stream_rounded_per_commitment_then_summed
        """
        ctx = fixtures.setup_signed_mitigated_fonsi()
        first, second = ctx["mitigations"]

        assert fixtures.read_mitigation(first["id"])[
            "lifecycle_obligation_cents"] == 1213973, (
            "a raw stream of 13972.5 cents rounds half up to 13973"
        )
        assert fixtures.read_mitigation(second["id"])[
            "lifecycle_obligation_cents"] == 2107763, (
            "a raw stream of 7762.5 cents rounds half up to 7763"
        )
        assert ctx["decision"]["base_obligation_cents"] == 3321736
        assert ctx["decision"]["base_obligation_cents"] != 3321735, (
            "summing the two raw streams and rounding once would lose a cent"
        )

    def test_two_identical_half_cent_streams_each_round_up(self, client):
        """Two commitments with the same 13972.5-cent stream contribute 13973
        cents each, so the base is 2427946 rather than 2427945.

        PRD 3.9: "Rounding once per commitment before any summation is the pinned
        order described in §2.8."
        PRD 3.9: "Second, `base_obligation_cents` is the sum of
        `lifecycle_obligation_cents` over those same binding commitments;
        commitments still `PROPOSED` and commitments already `RELEASED` are
        excluded from both sums."

        Design: Difficulty/combinatorial_formula/mode_b_monitoring_stream_rounded_per_commitment_then_summed
        """
        ctx = fixtures.setup_signed_decision(
            decision_type="MITIGATED_FONSI",
            mitigations=TWIN_HALF_CENT_COMMITMENTS,
        )
        for commitment in ctx["mitigations"]:
            assert fixtures.read_mitigation(commitment["id"])[
                "lifecycle_obligation_cents"] == 1213973

        assert ctx["decision"]["committed_obligation_cents"] == 2400000
        assert ctx["decision"]["base_obligation_cents"] == 2427946, (
            "each rounded stream is added to the base separately"
        )
        assert ctx["decision"]["base_obligation_cents"] != 2427945, (
            "rounding the summed raw streams once would give one cent less"
        )


class TestCreditPointsAndFee:
    """The credit is pinned from the base alone and frozen before the fee is
    charged."""

    def test_the_credit_is_capped_by_the_capacity_the_base_alone_affords(
        self, client
    ):
        """Fourteen declared reduction points are cut to 13.29 by a capacity of
        13.286944, and not raised to the 13.95 the post-fee total would afford.

        PRD 3.9: "Third, `credit_points` is computed from that base alone: the
        declared total is the sum of `reduction_points` over the same binding
        commitments, the capacity total is `base_obligation_cents` divided by the
        office's `cost_per_reduction_point_cents`, and `credit_points` is the
        smallest of the declared total, the capacity total and the office's
        `max_mitigated_reduction_points`, rounded half up to two decimal places."
        PRD 3.9: "At that point `credit_points` is frozen: recomputing the
        capacity total from the larger `binding_obligation_cents` would raise the
        credit and is not permitted, and the value persisted on the decision is
        the one computed in the third step."

        Design: Difficulty/combinatorial_formula/mode_c_credit_points_pinned_before_contingency_fee
        """
        ctx = fixtures.setup_signed_mitigated_fonsi()
        decision = ctx["decision"]

        assert decision["base_obligation_cents"] == 3321736
        assert decision["credit_points"] == approx_score(13.29), (
            "the capacity total is the binding constraint, below both the "
            "declared 14.0 and the office maximum of 18.0"
        )
        assert_scores_differ(decision["credit_points"], 13.95, "credit_points")
        assert decision["contingency_fee_cents"] == 166087, (
            "a credit at or above 10.00 selects the five-hundredths fee rate"
        )
        assert decision["binding_obligation_cents"] == 3487823

    def test_the_fee_is_charged_on_the_base_and_the_frozen_credit_sets_the_ceiling(
        self, client
    ):
        """The fee is 166087 cents rather than the 174391 the binding total would
        yield, and the mitigated ceiling is 70.21 less the frozen 13.29.

        PRD 3.9: "Fifth, `contingency_fee_cents` is `base_obligation_cents`
        multiplied by that fee rate, rounded half up to whole cents — the fee is
        charged on the base, not on the binding total."
        PRD 3.9: "Seventh and last, `mitigated_max_score` is the action's
        `max_unmitigated_score` reduced by the frozen `credit_points`, floored at
        0.00 and rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/mode_c_credit_points_pinned_before_contingency_fee
        """
        ctx = fixtures.setup_signed_mitigated_fonsi()
        decision = ctx["decision"]

        assert decision["contingency_fee_cents"] == 166087
        assert decision["contingency_fee_cents"] != 174391, (
            "five hundredths of the binding total would be a larger fee"
        )
        assert decision["binding_obligation_cents"] == (
            decision["base_obligation_cents"] + decision["contingency_fee_cents"]
        )
        assert ctx["action"]["max_unmitigated_score"] == approx_score(70.21)
        assert decision["mitigated_max_score"] == approx_score(56.92), (
            "the action's worst unmitigated score is reduced by the frozen credit"
        )
        assert_scores_differ(decision["mitigated_max_score"], 56.26,
                             "mitigated_max_score")


class TestSignatureBandOrder:
    """State admissibility is settled before the office ceiling is tested."""

    def test_an_inadmissible_review_stage_outranks_the_breached_ceiling(
        self, client
    ):
        """A signature attempted while the document is only published is refused
        as an invalid state, never as a breached obligation ceiling.

        PRD 2.5: "8. State admissibility of the target row and of every row named
        in the transition's preconditions — `ERR_INVALID_STATE`."
        PRD 2.5: "14. The office obligation ceiling at signature —
        `ERR_OBLIGATION_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/sign_state_precondition_outranks_obligation_cap
        """
        ctx = fixtures.setup_published_document()
        action_id = ctx["action"]["id"]
        assert ctx["action"]["review_stage"] == "DRAFT_PUBLISHED"
        assert ctx["document"]["publication_status"] == "PUBLISHED"
        assert ctx["document"]["comment_status"] == "OPEN"

        decision = fixtures.draft_decision(action_id, ctx["alt_b"]["id"],
                                          "MITIGATED_FONSI")
        commitment = fixtures.attach_mitigation(decision["id"],
                                               ctx["analysis"]["id"],
                                               **CAP_BREACHING_COMMITMENT)
        assert commitment["lifecycle_obligation_cents"] == 950000000, (
            "with no monitoring the lifecycle obligation is the one-time cost, "
            "already above the office ceiling of 900000000"
        )

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        refused = _sign(client, decision["id"])
        validate_error(refused, ApiErrorId.INVALID_STATE.value,
                       expected_status=409)

        untouched = fixtures.read_decision(decision["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["signed_at"] is None
        assert untouched["binding_obligation_cents"] == 0, (
            "the fiscal quantities are pinned only by a permitted signature"
        )
        assert fixtures.read_mitigation(commitment["id"])["status"] == "PROPOSED"
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

    def test_the_ceiling_surfaces_once_the_stage_and_the_document_are_admissible(
        self, client
    ):
        """The same commitment on the same office is refused on the ceiling once
        the document is final and the action has reached the closed comment stage.

        PRD 2.5: "14. The office obligation ceiling at signature —
        `ERR_OBLIGATION_CAP_EXCEEDED`."
        PRD 3.9: "Only once those figures exist is the office ceiling tested,
        under the ledger rule of §2.12, and a signature that would breach it is
        rejected with `ERR_OBLIGATION_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/sign_state_precondition_outranks_obligation_cap
        """
        ctx = fixtures.setup_drafted_decision(
            decision_type="MITIGATED_FONSI",
            mitigations=[CAP_BREACHING_COMMITMENT],
        )
        assert ctx["action"]["review_stage"] == "COMMENT_CLOSED"
        assert ctx["document"]["publication_status"] == "FINAL"

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        refused = _sign(client, ctx["decision"]["id"])
        validate_error(refused, ApiErrorId.OBLIGATION_CAP_EXCEEDED.value,
                       expected_status=409)

        untouched = fixtures.read_decision(ctx["decision"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["signed_at"] is None
        assert fixtures.read_mitigation(ctx["mitigations"][0]["id"])["status"] == (
            "PROPOSED"
        ), "a refused signature moves no commitment to binding"
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)


class TestSignatureEffectsAndReads:
    """What the signature writes, and what the draft exposes before it."""

    def test_the_objection_window_is_taken_from_the_office_parameter(self, client):
        """Signing at midday opens the window at the signature instant and closes
        it forty-five whole days later, keeping the time of day.

        PRD 3.9: "A permitted signature sets `signed_by_user_id` to the signer's
        `X-User-ID` and `signed_at` to the current logical time, moves the
        decision `DRAFT → SIGNED`, adds the decision's `binding_obligation_cents`
        to the office's own `binding_obligation_cents`, sets
        `objection_window_opens_at` equal to `signed_at` and
        `objection_window_closes_at` to `signed_at` advanced by the office's
        `objection_window_days` whole days, advances the action `COMMENT_CLOSED →
        DECIDED`, and appends a `DECISION_SIGNED` entry with the corresponding
        `record_entry_count` increment."
        PRD 3.9: "First, `committed_obligation_cents` is the sum of
        `cost_estimate_cents` over the decision's commitments whose `status` is
        `BINDING`, with no monitoring escalation and no contingency fee; it is the
        narrower of the two obligation readings and is always at or below
        `binding_obligation_cents` on identical commitment rows."

        Design: Corner/calculations/corner_objection_window_derived_from_office_objection_window_days
        """
        ctx = fixtures.setup_drafted_decision(decision_type="FONSI")
        assert ctx["office"]["objection_window_days"] == (
            DEFAULT_OBJECTION_WINDOW_DAYS
        )

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        signed = validate_success(_sign(client, ctx["decision"]["id"]))

        assert signed["status"] == "SIGNED"
        assert_instant_equals(signed["signed_at"], "2026-11-01T12:00:00Z",
                              "signed_at is the current logical time")
        assert_instant_equals(signed["objection_window_opens_at"],
                              "2026-11-01T12:00:00Z",
                              "the window opens at the signature instant")
        assert_instant_equals(signed["objection_window_closes_at"],
                              "2026-12-16T12:00:00Z",
                              "forty-five whole days later at the same time of day")
        assert signed["committed_obligation_cents"] == 0, (
            "a plain finding of no significant impact carries no commitment"
        )
        assert signed["base_obligation_cents"] == 0
        assert signed["binding_obligation_cents"] == 0
        assert signed["objection_count"] == 0
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

    def test_a_draft_decision_reads_back_its_derived_fields_as_zeros_and_nulls(
        self, client
    ):
        """The obligation fields are present and zero, and the signature fields
        are present and null, on a decision that has not been signed.

        PRD 3.9: "The server records `prepared_by_user_id` from the caller's
        `X-User-ID` and sets `status` to `DRAFT`, with `signed_by_user_id`,
        `signed_at`, `objection_window_opens_at` and `objection_window_closes_at`
        all null, `credit_points` and `mitigated_max_score` at 0.0,
        `objection_count` at 0, and `committed_obligation_cents`,
        `base_obligation_cents`, `contingency_fee_cents` and
        `binding_obligation_cents` all at 0."
        PRD 3.9: "Signature is reserved to a `DecidingOfficial` and is the moment
        every fiscal quantity is fixed."

        Design: Corner/endpoints/corner_get_decision_exposes_derived_obligation_fields_while_draft
        """
        ctx = fixtures.setup_drafted_decision(decision_type="FONSI")

        read_back = validate_success(
            client.get_decision(ctx["decision"]["id"], DECIDING_OFFICIAL_HEADERS)
        )
        assert read_back["status"] == "DRAFT"
        assert read_back["prepared_by_user_id"] == NEPA_COORDINATOR_USER_ID
        assert read_back["selected_alternative_id"] == ctx["alt_b"]["id"]
        assert read_back["committed_obligation_cents"] == 0
        assert read_back["base_obligation_cents"] == 0
        assert read_back["contingency_fee_cents"] == 0
        assert read_back["binding_obligation_cents"] == 0
        assert read_back["credit_points"] == approx_score(0.0)
        assert read_back["mitigated_max_score"] == approx_score(0.0)
        assert read_back["objection_count"] == 0
        for field in ("signed_at", "signed_by_user_id",
                      "objection_window_opens_at", "objection_window_closes_at"):
            assert read_back[field] is None, (
                f"{field} is only set by the signature transition"
            )
        assert_decision(read_back)


class TestSignatureGates:
    """The document gate, the commitment gate and the ceiling gate."""

    def test_a_published_document_short_of_final_blocks_the_signature(self, client):
        """The stage gate and the document gate are separate: the closed comment
        period is not enough while the assessment is still only published.

        PRD 3.9: "The decision's `status` must be `DRAFT`; the signer's
        `X-User-ID` must differ from `prepared_by_user_id` per §2.11; the action's
        `review_stage` must be `COMMENT_CLOSED`; and unless the `decision_type`
        is `CE_DETERMINATION`, the action must have a `NepaDocument` whose
        `publication_status` is `FINAL`, with a missing final document rejected as
        `ERR_FINAL_DOCUMENT_REQUIRED`."
        PRD 3.8: "Finalising the document is the last publication-axis step
        before a decision may be signed."

        Design: Corner/errors/corner_error_final_document_required_rejects_sign
        """
        ctx = fixtures.setup_comment_closed_document(comments=[])
        assert ctx["action"]["review_stage"] == "COMMENT_CLOSED"
        assert ctx["document"]["publication_status"] == "PUBLISHED"
        assert ctx["document"]["comment_status"] == "CLOSED"

        decision = fixtures.draft_decision(ctx["action"]["id"],
                                          ctx["alt_b"]["id"], "FONSI")
        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        refused = _sign(client, decision["id"])
        validate_error(refused, ApiErrorId.FINAL_DOCUMENT_REQUIRED.value,
                       expected_status=409)

        untouched = fixtures.read_decision(decision["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["signed_at"] is None
        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "PUBLISHED", (
            "the refused signature left both document axes alone"
        )
        assert document["comment_status"] == "CLOSED"
        assert fixtures.read_action(ctx["action"]["id"])["review_stage"] == (
            "COMMENT_CLOSED"
        )
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

    def test_a_mitigated_finding_with_no_commitment_behind_it_is_refused(
        self, client
    ):
        """The commitment requirement is specific to the mitigated finding, and
        an empty commitment set is refused at signature.

        PRD 3.9: "A `MITIGATED_FONSI` must then carry at least one commitment
        whose `status` is `BINDING`; a mitigated finding of no significant impact
        with no commitment behind it is rejected with
        `ERR_MITIGATED_FONSI_WITHOUT_COMMITMENT`."
        PRD 3.9: "The signature first moves every `MitigationCommitment` of the
        decision whose `status` is `PROPOSED` to `BINDING`, setting each one's
        `monitoring_status` to `SCHEDULED` when its `monitoring_years` is greater
        than zero and to `NOT_REQUIRED` otherwise."

        Design: Corner/validations/corner_mitigated_fonsi_without_commitment_is_rejected_at_sign
        """
        ctx = fixtures.setup_drafted_decision(decision_type="MITIGATED_FONSI")
        assert ctx["decision"]["decision_type"] == "MITIGATED_FONSI"
        _, meta = validate_paginated(
            client.list_mitigations(NEPA_COORDINATOR_HEADERS,
                                    params={"decision_id": ctx["decision"]["id"]})
        )
        assert meta["total_count"] == 0, "the draft carries no commitment at all"

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        refused = _sign(client, ctx["decision"]["id"])
        validate_error(refused,
                       ApiErrorId.MITIGATED_FONSI_WITHOUT_COMMITMENT.value,
                       expected_status=409)

        untouched = fixtures.read_decision(ctx["decision"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["signed_at"] is None
        assert untouched["signed_by_user_id"] is None
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)
        assert fixtures.read_action(ctx["action"]["id"])["review_stage"] == (
            "COMMENT_CLOSED"
        ), "the action stays where it was"

    def test_the_ceiling_is_tested_against_the_lifecycle_total_including_the_fee(
        self, client
    ):
        """A commitment costing 890000000 cents sits under the ceiling until the
        17800000-cent fee is added, and the signature is then refused.

        PRD 2.12: "Before a signature is allowed, the office total after the
        addition must not exceed `max_binding_obligation_cents`; that is, the sum
        of the office's current `binding_obligation_cents` and the decision's own
        `binding_obligation_cents` must be less than or equal to the ceiling."
        PRD 3.9: "Fifth, `contingency_fee_cents` is `base_obligation_cents`
        multiplied by that fee rate, rounded half up to whole cents — the fee is
        charged on the base, not on the binding total."

        Design: Corner/errors/corner_error_obligation_cap_exceeded_rejects_sign
        """
        ctx = fixtures.setup_drafted_decision(
            decision_type="FONSI", mitigations=[FEE_BREACHING_COMMITMENT],
        )
        assert ctx["office"]["max_binding_obligation_cents"] == (
            DEFAULT_MAX_BINDING_OBLIGATION_CENTS
        )
        assert_office_ledger_equals(ctx["office"], 0)
        commitment = ctx["mitigations"][0]
        assert commitment["lifecycle_obligation_cents"] == 890000000, (
            "with no monitoring years the lifecycle total is the one-time cost, "
            "still under the ceiling on its own"
        )
        assert commitment["monitoring_status"] == "NOT_REQUIRED"

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        refused = _sign(client, ctx["decision"]["id"])
        validate_error(refused, ApiErrorId.OBLIGATION_CAP_EXCEEDED.value,
                       expected_status=409)

        untouched = fixtures.read_decision(ctx["decision"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["binding_obligation_cents"] == 0
        assert untouched["credit_points"] == approx_score(0.0)
        assert fixtures.read_mitigation(commitment["id"])["status"] == "PROPOSED"
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)


class TestSignatureAuthority:
    """Who may sign, and who may not sign what they prepared."""

    def test_a_policy_admin_may_not_sign_even_a_perfectly_signable_decision(
        self, client
    ):
        """The configuring role is refused on the signature endpoint, and the
        deciding official's identical call succeeds.

        PRD 2.5: "2. Role authorisation for the target endpoint, on every
        endpoint — `ERR_ROLE_NOT_PERMITTED`."
        PRD 3.9: "Signature is reserved to a `DecidingOfficial` and is the moment
        every fiscal quantity is fixed."

        Design: Corner/rbac/corner_policy_admin_cannot_sign_a_decision
        """
        ctx = fixtures.setup_drafted_decision(decision_type="FONSI")
        action_id = ctx["action"]["id"]
        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)

        refused = _sign(client, ctx["decision"]["id"], POLICY_ADMIN_HEADERS)
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED.value,
                       expected_status=403)

        untouched = fixtures.read_decision(ctx["decision"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["signed_by_user_id"] is None
        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert entries_with_code(entries, "DECISION_SIGNED") == [], (
            "the refused call appended nothing to the administrative record"
        )

        signed = validate_success(_sign(client, ctx["decision"]["id"]))
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == DECIDING_OFFICIAL_USER_ID
        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert len(entries_with_code(entries, "DECISION_SIGNED")) == 1

    def test_the_preparer_may_not_sign_the_decision_they_prepared(self, client):
        """Separation is enforced on identity: the coordinator's own identifier
        under the deciding role is refused, and a different official succeeds.

        PRD 2.11: "At decision signature, the signing `DecidingOfficial`'s
        `X-User-ID` must differ from the decision's `prepared_by_user_id`."
        PRD 2.11: "These checks are evaluated before any state or business check
        on the same request, so an official attempting to sign their own draft
        learns that fact even if the draft is not otherwise signable."

        Design: Corner/rbac/corner_preparer_cannot_sign_the_decision_they_prepared
        """
        ctx = fixtures.setup_drafted_decision(decision_type="FONSI")
        assert ctx["decision"]["prepared_by_user_id"] == NEPA_COORDINATOR_USER_ID
        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)

        refused = _sign(client, ctx["decision"]["id"],
                        make_deciding_official_headers(NEPA_COORDINATOR_USER_ID))
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value,
                       expected_status=403)
        assert fixtures.read_decision(ctx["decision"]["id"])["status"] == "DRAFT", (
            "the refused signature leaves the draft where it was"
        )

        signed = validate_success(_sign(client, ctx["decision"]["id"]))
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == DECIDING_OFFICIAL_USER_ID
        assert signed["prepared_by_user_id"] == NEPA_COORDINATOR_USER_ID, (
            "the preparer is unchanged by the signature"
        )


class TestMitigationConcurrency:
    """The decision's own version guards its commitment set."""

    def test_a_replayed_decision_version_is_refused_on_the_second_commitment(
        self, client
    ):
        """The version read before the first commitment is stale for the second,
        and the refused attempt creates no row.

        PRD 2.9: "Attaching a mitigation commitment to a decision requires
        `expected_decision_version` to equal the current `version` of the target
        `DecisionDocument`."
        PRD 2.9: "A mismatch is rejected with `ERR_STALE_DECISION_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/corner_add_mitigation_with_stale_expected_decision_version_is_rejected
        """
        ctx = fixtures.setup_drafted_decision(decision_type="FONSI")
        decision_id = ctx["decision"]["id"]
        observed_version = ctx["decision"]["version"]

        first = fixtures.attach_mitigation(
            decision_id, ctx["analysis"]["id"],
            expected_decision_version=observed_version,
            measure_text="Seasonal timing restriction on the treatment unit",
            reduction_points=5.0,
        )
        assert first["status"] == "PROPOSED"
        assert first["lifecycle_obligation_cents"] == 2597250, (
            "three years of 450000 cents escalated by 1.035 add 1397250 cents"
        )

        refused = client.add_mitigation(
            decision_id,
            mitigation_payload(ctx["analysis"]["id"], observed_version,
                               measure_text="Weed-free equipment washing station",
                               cost_estimate_cents=300000, monitoring_years=0,
                               annual_monitoring_cost_cents=0,
                               reduction_points=1.0),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.STALE_DECISION_VERSION.value,
                       expected_status=412)

        rows, meta = validate_paginated(
            client.list_mitigations(NEPA_COORDINATOR_HEADERS,
                                    params={"decision_id": decision_id})
        )
        assert meta["total_count"] == 1, "the refused attempt created no row"
        assert [row["id"] for row in rows] == [first["id"]]
        assert fixtures.read_mitigation(first["id"])["status"] == "PROPOSED"

        decision = fixtures.read_decision(decision_id)
        assert decision["status"] == "DRAFT"
        assert decision["base_obligation_cents"] == 0, (
            "obligations are pinned only at signature"
        )
        assert decision["version"] == observed_version + 1, (
            "only the accepted commitment moved the decision version"
        )
