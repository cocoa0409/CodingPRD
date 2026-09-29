"""Cyclic and non-linear transitions of the royalty state machines.

Three areas are exercised here: the bounded UNDER_REVIEW / NEEDS_EVIDENCE
evidence cycle of a rights registration, the royalty pool's CALCULATED
self-loop together with the FINALIZED -> REOPENED_FOR_ADJUSTMENT -> CALCULATED
-> FINALIZED cycle its parent period rides in lockstep, and the two
independently advancing status dimensions of an audit engagement through to an
upheld settlement with interest.
"""

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    audit_engagement_payload,
    calculate_pool,
    close_period,
    create_and_issue_statement,
    create_composition,
    create_effective_schedule,
    create_engagement,
    create_pool,
    create_publisher,
    data_production_payload,
    file_and_approve_registration,
    file_registration,
    finalize_pool,
    findings_payload,
    make_rights_holder_user_headers,
    record_findings,
    request_evidence,
    review_registration,
    set_clock,
    settle_engagement,
    setup_all_matched_batch,
    setup_audit_engagement,
    setup_canonical_statement_issued,
    submit_evidence,
    validate_error,
    validate_success,
)

# The remand schedule of the retroactive proceeding: the same GB/INDIVIDUAL cell
# and the same window as the canonical schedule, but a richer revenue share.
_REMAND_SCHEDULE = dict(
    proceeding_ref=TEST_DEFAULTS["SCHEDULE_REMAND_REF"],
    territory_code="GB",
    subscription_tier="INDIVIDUAL",
    revenue_share_bps=8000,
    per_subscriber_minimum_cents=500,
    mechanical_share_bps=4000,
    performance_share_bps=6000,
    statutory_floor_per_play_millicents=100,
    effective_from=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
    effective_to=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
    retroactive=True,
)

_CLOSING_CLOCK = "2026-08-30T00:00:00Z"
_SETTLEMENT_CLOCK = "2026-10-01T00:00:00Z"


# ─────────────────────────────────────────────────────
# Composite preambles built from the helper atoms
# ─────────────────────────────────────────────────────

def _setup_composition_claim_under_review(api):
    """A MECHANICAL claim over a composition that carries no usage anywhere,
    taken into review — the entry state of the evidence cycle.

    The publisher carries a direct deal rate so that DIRECT routing is viable,
    and no usage line exists anywhere, so no claim window can interfere.
    """
    publisher = create_publisher(api, rate_bps=1000)
    composition = create_composition(api)
    filed = file_registration(
        api,
        composition["id"],
        publisher["id"],
        right_type="MECHANICAL",
        routing="DIRECT",
        share_bps=6000,
        territory_set=["GB"],
    )
    return {
        "publisher": publisher,
        "composition": composition,
        "filed": filed,
        "under_review": review_registration(api, filed["id"]),
    }


def _setup_claim_with_both_evidence_rounds_spent(api):
    """The same claim after two full request-evidence / evidence passes, so it
    sits in UNDER_REVIEW with evidence_round at 2."""
    state = _setup_composition_claim_under_review(api)
    registration_id = state["filed"]["id"]
    holder_id = state["publisher"]["id"]
    for _ in range(2):
        request_evidence(api, registration_id)
        state["under_review"] = submit_evidence(api, registration_id, holder_id)
    return state


def _setup_all_matched_pool_drafted(api):
    """The all-matched GB/INDIVIDUAL usage, the master claim approved, and the
    pool created but not yet calculated."""
    fixture = setup_all_matched_batch(api)
    fixture["master_registration"] = file_and_approve_registration(
        api,
        fixture["recording_a"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    fixture["pool"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=TEST_DEFAULTS["CANONICAL_SUBSCRIBER_COUNT"],
        gross_revenue_cents=TEST_DEFAULTS["CANONICAL_GROSS_REVENUE_CENTS"],
    )
    return fixture


def _setup_pool_calculated_twice(api):
    """The same pool run through calculate twice, so it reached CALCULATED once
    from DRAFT and once from CALCULATED itself."""
    fixture = _setup_all_matched_pool_drafted(api)
    calculate_pool(api, fixture["pool"]["id"])
    fixture["pool"] = calculate_pool(api, fixture["pool"]["id"])
    return fixture


def _setup_closed_period_after_distribution(api):
    """The recalculated pool frozen, the label's statement issued, the clock
    moved past the claim window and the period CLOSED."""
    fixture = _setup_pool_calculated_twice(api)
    fixture["pool"] = finalize_pool(api, fixture["pool"]["id"])
    fixture["statement"] = create_and_issue_statement(
        api, fixture["label"]["id"], fixture["period"]["id"]
    )
    set_clock(api, _CLOSING_CLOCK)
    fixture["period_closed"] = close_period(api, fixture["period"]["id"])
    return fixture


def _setup_retroactively_reopened_cycle(api):
    """The closed period after a retroactive remand schedule was promulgated
    over the same territory and tier, superseding the incumbent."""
    fixture = _setup_closed_period_after_distribution(api)
    fixture["remand_schedule"] = create_effective_schedule(
        api, supersede_incumbent=True, **_REMAND_SCHEDULE
    )
    return fixture


# ─────────────────────────────────────────────────────
# registration_evidence_loop_bounded_by_round_counter
# ─────────────────────────────────────────────────────

class TestRegistrationEvidenceLoop:

    def test_evidence_cycle_traverses_twice_and_the_counter_moves_on_the_return_leg(
        self, api, reviewer_headers
    ):
        """The UNDER_REVIEW / NEEDS_EVIDENCE cycle is traversed twice with the same two triggers and evidence_round advances only when the evidence comes back.

        PRD: "The claimant — a `RightsHolderUser` whose `X-User-ID` equals the registration's `claimant_id`, or a `RightsOpsAnalyst` acting for it — then supplies the evidence, which increments `evidence_round` by 1 and moves the claim `NEEDS_EVIDENCE → UNDER_REVIEW`; that step, too, requires `evidence_round` to be below 2 at the time it runs."

        Design: Difficulty/non_linear_state_machine/registration_evidence_loop_bounded_by_round_counter
        """
        state = _setup_composition_claim_under_review(api)
        registration_id = state["filed"]["id"]
        holder_headers = make_rights_holder_user_headers(state["publisher"]["id"])

        assert state["filed"]["status"] == "SUBMITTED"
        assert state["filed"]["evidence_round"] == 0
        assert state["under_review"]["status"] == "UNDER_REVIEW"
        assert state["under_review"]["evidence_round"] == 0

        bounced_once = validate_success(
            api.request_registration_evidence(registration_id, reviewer_headers), 200
        )
        assert bounced_once["status"] == "NEEDS_EVIDENCE"
        assert bounced_once["evidence_round"] == 0

        returned_once = validate_success(
            api.submit_registration_evidence(registration_id, holder_headers), 200
        )
        assert returned_once["status"] == "UNDER_REVIEW"
        assert returned_once["evidence_round"] == 1

        bounced_twice = validate_success(
            api.request_registration_evidence(registration_id, reviewer_headers), 200
        )
        assert bounced_twice["status"] == "NEEDS_EVIDENCE"
        assert bounced_twice["evidence_round"] == 1

        returned_twice = validate_success(
            api.submit_registration_evidence(registration_id, holder_headers), 200
        )
        assert returned_twice["status"] == "UNDER_REVIEW"
        assert returned_twice["evidence_round"] == 2

    def test_third_request_evidence_from_the_same_state_is_refused(
        self, api, reviewer_headers
    ):
        """A third request-evidence, issued from the very UNDER_REVIEW state that accepted the identical call twice, is refused and leaves the claim untouched.

        PRD: "From `UNDER_REVIEW` the analyst may bounce the claim back for documentary evidence, moving it `UNDER_REVIEW → NEEDS_EVIDENCE`, but only while `evidence_round` is strictly below 2; the third such attempt is refused with `ERR_EVIDENCE_ROUNDS_EXHAUSTED`, and that cap is what guarantees the loop terminates."

        Design: Difficulty/non_linear_state_machine/registration_evidence_loop_bounded_by_round_counter
        """
        state = _setup_claim_with_both_evidence_rounds_spent(api)
        registration_id = state["filed"]["id"]
        assert state["under_review"]["status"] == "UNDER_REVIEW"
        assert state["under_review"]["evidence_round"] == 2

        validate_error(
            api.request_registration_evidence(registration_id, reviewer_headers),
            ApiErrorId.ERR_EVIDENCE_ROUNDS_EXHAUSTED.value,
            422,
        )

        after = validate_success(
            api.get_rights_registration(registration_id, reviewer_headers), 200
        )
        assert after["status"] == "UNDER_REVIEW"
        assert after["evidence_round"] == 2

    def test_claim_remains_approvable_after_the_loop_is_exhausted(
        self, api, reviewer_headers
    ):
        """A claim whose evidence rounds are spent is still approvable from UNDER_REVIEW, and the round counter is not reset by the approval.

        PRD: "Its `status` becomes `APPROVED` and `reviewed_by_user_id` records the approving `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/registration_evidence_loop_bounded_by_round_counter
        """
        state = _setup_claim_with_both_evidence_rounds_spent(api)
        registration_id = state["filed"]["id"]

        approved = validate_success(
            api.approve_rights_registration(registration_id, reviewer_headers), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["evidence_round"] == 2


# ─────────────────────────────────────────────────────
# pool_reopen_recalculate_cycle_with_self_loop
# ─────────────────────────────────────────────────────

class TestPoolReopenRecalculateCycle:

    def test_calculate_self_loop_recomputes_a_calculated_pool_in_place(
        self, api, royalty_admin_headers
    ):
        """Calculate is accepted a second time from CALCULATED and leaves the pool in CALCULATED with the same distributable amount and denominator basis.

        PRD: "Calculation is what turns a `DRAFT` pool into a priced one, and it has three legal entry states: `DRAFT → CALCULATED` for a first run, `CALCULATED → CALCULATED` for a deliberate self-loop that recomputes in place, and `REOPENED_FOR_ADJUSTMENT → CALCULATED` for a run after a retroactive rate change."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_all_matched_pool_drafted(api)
        pool_id = fixture["pool"]["id"]
        assert fixture["pool"]["status"] == "DRAFT"

        first_run = validate_success(api.calculate_pool(pool_id, royalty_admin_headers), 200)
        assert first_run["status"] == "CALCULATED"
        assert first_run["distributable_cents"] == 999999
        assert first_run["denominator_basis"] == "ALL_USAGE"

        second_run = validate_success(api.calculate_pool(pool_id, royalty_admin_headers), 200)
        assert second_run["status"] == "CALCULATED"
        assert second_run["distributable_cents"] == 999999
        assert second_run["denominator_basis"] == "ALL_USAGE"

    def test_finalize_freezes_the_pool_and_bubbles_the_period_to_distributed(
        self, api, royalty_admin_headers
    ):
        """Finalizing the period's only pool moves it to FINALIZED and bubbles the period USAGE_SEALED -> DISTRIBUTED with nothing left in holding.

        PRD: "When the period owns at least one pool and every pool of the period has `status` `FINALIZED`, the period moves `USAGE_SEALED → DISTRIBUTED`, or `REOPENED → DISTRIBUTED` when it was reopened by a rate cascade; the second form closes the reopen cycle."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_pool_calculated_twice(api)

        finalized = validate_success(
            api.finalize_pool(fixture["pool"]["id"], royalty_admin_headers), 200
        )
        assert finalized["status"] == "FINALIZED"

        period = validate_success(
            api.get_period(fixture["period"]["id"], royalty_admin_headers), 200
        )
        assert period["status"] == "DISTRIBUTED"
        assert period["total_holding_cents"] == 0

    def test_calculate_is_refused_from_finalized(self, api, royalty_admin_headers):
        """Calculate is refused outright from FINALIZED — the one source state the transition does not allow — and the pool stays FINALIZED.

        PRD: "A pool that is `FINALIZED` cannot be calculated, and a pool in any state the requested transition does not allow is refused with `ERR_INVALID_POOL_STATE`, while a wrongly-stated parent period yields `ERR_INVALID_PERIOD_STATE`."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_closed_period_after_distribution(api)
        pool_id = fixture["pool"]["id"]
        assert fixture["pool"]["status"] == "FINALIZED"
        assert fixture["period_closed"]["status"] == "CLOSED"

        # The pool state check precedes the period state check, so the CLOSED
        # parent does not steal the error.
        validate_error(
            api.calculate_pool(pool_id, royalty_admin_headers),
            ApiErrorId.ERR_INVALID_POOL_STATE.value,
            409,
        )

        after = validate_success(api.get_pool(pool_id, royalty_admin_headers), 200)
        assert after["status"] == "FINALIZED"

    def test_retroactive_promulgation_reopens_the_finalized_pool(
        self, api, royalty_admin_headers
    ):
        """Promulgating a retroactive schedule over the pool's cell moves the frozen pool FINALIZED -> REOPENED_FOR_ADJUSTMENT.

        PRD: "**Link two** fires only when the newly effective schedule has `retroactive` set to true: every royalty pool whose `status` is `FINALIZED`, whose `subscription_tier` equals the schedule's, whose `territory_code` equals the schedule's or whose schedule is the literal `WORLD`, and whose parent period's `usage_end` falls inside the schedule's inclusive window, moves `FINALIZED → REOPENED_FOR_ADJUSTMENT`."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_retroactively_reopened_cycle(api)

        pool = validate_success(
            api.get_pool(fixture["pool"]["id"], royalty_admin_headers), 200
        )
        assert pool["status"] == "REOPENED_FOR_ADJUSTMENT"

    def test_retroactive_promulgation_reopens_the_closed_period(
        self, api, royalty_admin_headers
    ):
        """A period that had already reached the terminal-looking CLOSED state is moved back to REOPENED by the promulgation cascade.

        PRD: "**Link four** follows because those pools reopened and those statements were voided: every accounting period that owns a reopened pool moves to `REOPENED` — the `CLOSED → REOPENED` transition for a period that had already been closed, and the same move for a period still sitting in `DISTRIBUTED` when the cascade lands."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_retroactively_reopened_cycle(api)
        assert fixture["period_closed"]["status"] == "CLOSED"

        period = validate_success(
            api.get_period(fixture["period"]["id"], royalty_admin_headers), 200
        )
        assert period["status"] == "REOPENED"

    def test_recalculating_and_refinalizing_closes_the_reopen_cycle(
        self, api, royalty_admin_headers
    ):
        """Calculate is accepted from REOPENED_FOR_ADJUSTMENT under the newly effective schedule, and the second finalize bubbles the period REOPENED -> DISTRIBUTED.

        PRD: "Each `REOPENED_FOR_ADJUSTMENT` pool is recalculated, which now selects the newly `EFFECTIVE` schedule and moves the pool `REOPENED_FOR_ADJUSTMENT → CALCULATED`, and is then finalized again, which bubbles the period `REOPENED → DISTRIBUTED`."

        Design: Difficulty/non_linear_state_machine/pool_reopen_recalculate_cycle_with_self_loop
        """
        fixture = _setup_retroactively_reopened_cycle(api)
        pool_id = fixture["pool"]["id"]

        recalculated = validate_success(
            api.calculate_pool(pool_id, royalty_admin_headers), 200
        )
        assert recalculated["status"] == "CALCULATED"
        assert recalculated["applied_rate_schedule_id"] == fixture["remand_schedule"]["id"]
        assert recalculated["distributable_cents"] == 1142856

        refinalized = validate_success(
            api.finalize_pool(pool_id, royalty_admin_headers), 200
        )
        assert refinalized["status"] == "FINALIZED"

        period = validate_success(
            api.get_period(fixture["period"]["id"], royalty_admin_headers), 200
        )
        assert period["status"] == "DISTRIBUTED"


# ─────────────────────────────────────────────────────
# audit_parallel_dimensions_and_settlement_interest
# ─────────────────────────────────────────────────────

class TestAuditParallelDimensionsAndSettlement:

    def test_production_dimension_advances_from_pending_through_partial_to_complete(
        self, api, royalty_admin_headers
    ):
        """Producing the audited statement's two lines one at a time walks production_status PENDING -> PARTIAL -> COMPLETE while finding_status stays NONE.

        PRD: "When the recomputed count is still strictly below `required_line_count`, the engagement moves `PENDING → PARTIAL`; when it equals `required_line_count`, the engagement moves `PENDING → COMPLETE` if the whole set arrived in one call, or `PARTIAL → COMPLETE` if it accumulated over several."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_and_settlement_interest
        """
        fixture = setup_canonical_statement_issued(api)
        holder_id = fixture["label"]["id"]
        lines = fixture["statement_lines"]
        assert len(lines) == 2

        engagement = validate_success(
            api.create_audit_engagement(
                audit_engagement_payload(holder_id, fixture["statement"]["id"]),
                make_rights_holder_user_headers(holder_id),
            ),
            201,
        )
        assert engagement["required_line_count"] == 2
        assert engagement["produced_line_count"] == 0
        assert engagement["production_status"] == "PENDING"
        assert engagement["finding_status"] == "NONE"

        first = validate_success(
            api.produce_audit_data(
                engagement["id"],
                data_production_payload([lines[0]["id"]]),
                royalty_admin_headers,
            ),
            200,
        )
        assert first["produced_line_count"] == 1
        assert first["production_status"] == "PARTIAL"
        assert first["finding_status"] == "NONE"

        second = validate_success(
            api.produce_audit_data(
                engagement["id"],
                data_production_payload([lines[1]["id"]]),
                royalty_admin_headers,
            ),
            200,
        )
        assert second["produced_line_count"] == 2
        assert second["production_status"] == "COMPLETE"
        assert second["finding_status"] == "NONE"

    def test_finding_refused_while_production_is_still_pending(
        self, api, royalty_admin_headers
    ):
        """A finding asserted before any data has been produced is refused, and neither status dimension moves.

        PRD: "The engagement's `finding_status` must be `NONE`, or the request is refused with `ERR_INVALID_ENGAGEMENT_STATE`, and its `production_status` must be `COMPLETE` — a `PENDING` or `PARTIAL` production is not enough, and asserting against one is refused with `ERR_DATA_PRODUCTION_INCOMPLETE`."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_and_settlement_interest
        """
        fixture = setup_canonical_statement_issued(api)
        holder_id = fixture["label"]["id"]
        engagement = create_engagement(api, holder_id, fixture["statement"]["id"])
        assert engagement["production_status"] == "PENDING"

        validate_error(
            api.record_audit_findings(
                engagement["id"],
                findings_payload(100026),
                make_rights_holder_user_headers(holder_id),
            ),
            ApiErrorId.ERR_DATA_PRODUCTION_INCOMPLETE.value,
            422,
        )

        after = validate_success(
            api.get_audit_engagement(engagement["id"], royalty_admin_headers), 200
        )
        assert after["production_status"] == "PENDING"
        assert after["produced_line_count"] == 0
        assert after["finding_status"] == "NONE"

    def test_asserting_a_finding_leaves_the_production_dimension_at_complete(self, api):
        """Asserting the finding moves finding_status NONE -> ASSERTED and leaves production_status exactly at COMPLETE.

        PRD: "A successful assertion stores the amount and the note, stamps `findings_recorded_by_user_id` with the caller's `X-User-ID`, and moves `finding_status` `NONE → ASSERTED` while leaving `production_status` exactly where it was."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_and_settlement_interest
        """
        fixture = setup_audit_engagement(api)
        holder_id = fixture["label"]["id"]
        engagement = fixture["engagement"]
        assert engagement["production_status"] == "COMPLETE"
        assert engagement["finding_status"] == "NONE"

        asserted = validate_success(
            api.record_audit_findings(
                engagement["id"],
                findings_payload(100026, finding_note="Territory attribution understated"),
                make_rights_holder_user_headers(holder_id),
            ),
            200,
        )
        assert asserted["finding_status"] == "ASSERTED"
        assert asserted["asserted_underpayment_cents"] == 100026
        assert asserted["production_status"] == "COMPLETE"
        assert asserted["produced_line_count"] == 2

    def test_upheld_settlement_interest_is_rounded_once_over_the_whole_quotient(
        self, api
    ):
        """Upholding 100026 cents held 61 days settles the finding with interest of exactly 1505 cents, the value produced by rounding the fully assembled quotient once.

        PRD: "Then `interest_cents` is computed as `settled_amount_cents` multiplied by 900 basis points, multiplied by `days_elapsed`, divided by the product of 10,000 and 365 days, with the result rounded half up to a whole cent."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_and_settlement_interest
        """
        fixture = setup_audit_engagement(api)
        holder_id = fixture["label"]["id"]
        engagement = fixture["engagement"]
        record_findings(
            api,
            engagement["id"],
            holder_id,
            100026,
            finding_note="Territory attribution understated",
        )

        set_clock(api, _SETTLEMENT_CLOCK)
        settled = settle_engagement(
            api, engagement["id"], "UPHOLD", settled_amount_cents=100026
        )

        assert settled["finding_status"] == "SETTLED"
        assert settled["production_status"] == "COMPLETE"
        assert settled["settled_amount_cents"] == 100026
        assert settled["interest_cents"] == 1505
        # 1504 is what rounding the annual interest first and prorating it by
        # 61/365 afterwards produces.
        assert settled["interest_cents"] != 1504

    def test_upheld_settlement_moves_amount_and_interest_onto_the_receivable(
        self, api, royalty_admin_headers
    ):
        """The settlement raises the audited holder's receivable balance by exactly the settled amount plus the interest, on top of the issued statement's net payable.

        PRD: "The amount is stored, interest is computed, `finding_status` moves `ASSERTED → SETTLED`, and the audited holder's `receivable_balance_cents` rises by exactly `settled_amount_cents` plus `interest_cents`."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_and_settlement_interest
        """
        fixture = setup_audit_engagement(api)
        holder_id = fixture["label"]["id"]
        assert fixture["statement"]["net_payable_cents"] == 621000

        record_findings(
            api,
            fixture["engagement"]["id"],
            holder_id,
            100026,
            finding_note="Territory attribution understated",
        )
        set_clock(api, _SETTLEMENT_CLOCK)
        settled = settle_engagement(
            api, fixture["engagement"]["id"], "UPHOLD", settled_amount_cents=100026
        )
        assert settled["settled_amount_cents"] == 100026
        assert settled["interest_cents"] == 1505

        holder = validate_success(
            api.get_rights_holder(holder_id, royalty_admin_headers), 200
        )
        assert holder["receivable_balance_cents"] == 722531
