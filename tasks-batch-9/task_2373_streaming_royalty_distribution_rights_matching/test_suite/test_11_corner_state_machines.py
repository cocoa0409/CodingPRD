"""State-machine conformance: legal transitions, refused transitions and the
status bubble-ups of the usage batch, rights registration, royalty pool,
accounting period, rate schedule, royalty statement and audit engagement.
"""

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    DEFAULT_CLOCK_UTC,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    append_line,
    audit_engagement_payload,
    calculate_pool,
    create_batch,
    create_effective_schedule,
    create_engagement,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    create_schedule,
    create_statement,
    data_production_payload,
    dispute_payload,
    file_and_approve_registration,
    file_registration,
    finalize_pool,
    issue_statement,
    make_rights_holder_user_headers,
    match_batch,
    produce_audit_data,
    rejection_payload,
    review_registration,
    seal_batch,
    set_clock,
    settlement_payload,
    statement_lines,
    usage_line_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["royalty_admin_headers"]
ANALYST = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR = TEST_USERS["regulatory_officer_headers"]
MATCHER = TEST_USERS["fuzzy_matcher_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
SETTLING_ADMIN = TEST_USERS["settling_admin_headers"]


# ─────────────────────────────────────────────────────
# Composite preambles this module needs and fixtures.py
# does not carry, all built from the fixtures.py atoms.
# ─────────────────────────────────────────────────────

def _setup_single_line_matched_batch(api, *, play_count=450000):
    """One EFFECTIVE GB/INDIVIDUAL schedule, the 2026-06 period and one sealed
    batch carrying a single line resolved by exact ISRC."""
    fixture = {"schedule": create_effective_schedule(api)}
    fixture["period"] = create_period(api)
    fixture["recording"] = create_recording(api)
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    fixture["usage_line"] = append_line(
        api,
        fixture["batch"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=play_count,
    )
    seal_batch(api, fixture["batch"]["id"])
    fixture["batch_after_match"] = match_batch(api, fixture["batch"]["id"])
    return fixture


def _setup_single_line_finalized_pool(api):
    """The single-line matched batch with the label's MASTER claim approved and
    the GB/INDIVIDUAL pool calculated and frozen."""
    fixture = _setup_single_line_matched_batch(api)
    fixture["label"] = create_label(api)
    fixture["master_registration"] = file_and_approve_registration(
        api,
        fixture["recording"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    pool = create_pool(api, fixture["period"]["id"])
    calculate_pool(api, pool["id"])
    fixture["pool"] = finalize_pool(api, pool["id"])
    return fixture


def _setup_single_line_issued_statement(api):
    """The single-line finalized pool carried through to the label's ISSUED
    statement, which carries exactly one MASTER usage line."""
    fixture = _setup_single_line_finalized_pool(api)
    fixture["draft_statement"] = create_statement(
        api, fixture["label"]["id"], fixture["period"]["id"]
    )
    fixture["statement"] = issue_statement(api, fixture["draft_statement"]["id"])
    fixture["statement_lines"] = statement_lines(api, fixture["statement"]["id"])
    return fixture


def _setup_two_batch_period_with_calculated_pool(api):
    """The 2026-06 period owning one fully matched batch and one partially
    matched batch, plus its GB/INDIVIDUAL pool calculated but not yet frozen.

    Both batches are opened while the period is still OPEN, because a batch may
    only be opened inside an OPEN period; they are then sealed and matched in
    turn, which is what bubbles the period to USAGE_SEALED.
    """
    fixture = {"schedule": create_effective_schedule(api)}
    fixture["period"] = create_period(api)
    fixture["recording"] = create_recording(api)

    fixture["batch_a"] = create_batch(api, fixture["period"]["id"])
    fixture["batch_b"] = create_batch(
        api, fixture["period"]["id"], source_label="Partner feed"
    )
    append_line(
        api,
        fixture["batch_a"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=300000,
    )
    append_line(
        api,
        fixture["batch_b"]["id"],
        reported_title="Unknown Signal",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    seal_batch(api, fixture["batch_a"]["id"])
    fixture["batch_a_after_match"] = match_batch(api, fixture["batch_a"]["id"])
    seal_batch(api, fixture["batch_b"]["id"])
    fixture["batch_b_after_match"] = match_batch(api, fixture["batch_b"]["id"])

    pool = create_pool(api, fixture["period"]["id"])
    fixture["pool"] = calculate_pool(api, pool["id"])
    return fixture


# ─────────────────────────────────────────────────────
# UsageBatch
# ─────────────────────────────────────────────────────

class TestUsageBatchTransitions:
    def test_a_second_seal_is_refused_and_the_batch_stays_sealed(self, api):
        """Sealing moves an OPEN batch to SEALED and a second seal of the same batch is refused with ERR_INVALID_USAGE_BATCH_STATE.

        PRD: "A `RightsOpsAnalyst` seals an `OPEN` batch whose `line_count` is at least 1 while its parent period is still `OPEN`, moving the batch `OPEN → SEALED`; after that no further line may be appended."

        Design: Corner/state_machines/usage_batch_seal_and_match_are_not_repeatable
        """
        period = create_period(api)
        create_recording(api)
        batch = create_batch(api, period["id"])
        append_line(
            api,
            batch["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=300000,
        )

        first = validate_success(api.seal_usage_batch(batch["id"], ANALYST), 200)
        assert first["status"] == "SEALED"

        validate_error(
            api.seal_usage_batch(batch["id"], ANALYST),
            ApiErrorId.ERR_INVALID_USAGE_BATCH_STATE.value,
            409,
        )

        after = validate_success(api.get_usage_batch(batch["id"], ANALYST), 200)
        assert after["status"] == "SEALED"

    def test_appending_a_line_after_sealing_is_refused(self, api):
        """A line appended to a batch that has already been sealed is refused and leaves the batch's line and play counters untouched.

        PRD: "Appending to a batch that is no longer `OPEN` is refused with `ERR_INVALID_USAGE_BATCH_STATE`."

        Design: Corner/state_machines/usage_batch_seal_and_match_are_not_repeatable
        """
        period = create_period(api)
        create_recording(api)
        batch = create_batch(api, period["id"])
        append_line(
            api,
            batch["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=300000,
        )
        seal_batch(api, batch["id"])

        validate_error(
            api.append_usage_line(
                batch["id"],
                usage_line_payload(
                    reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
                    reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
                    territory_code="GB",
                    subscription_tier="INDIVIDUAL",
                    play_count=1,
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_USAGE_BATCH_STATE.value,
            409,
        )

        after = validate_success(api.get_usage_batch(batch["id"], ANALYST), 200)
        assert after["status"] == "SEALED"
        assert after["line_count"] == 1
        assert after["total_play_count"] == 300000

    def test_a_second_match_is_refused_and_the_counters_do_not_move(self, api):
        """Matching a SEALED batch moves it to MATCHED, and a second match of the now-MATCHED batch is refused without re-running the matcher.

        PRD: "A `RoyaltyAdmin` or a `RightsOpsAnalyst` runs it over a batch whose `status` is `SEALED`; a batch in any other state is refused with `ERR_INVALID_USAGE_BATCH_STATE`."

        Design: Corner/state_machines/usage_batch_seal_and_match_are_not_repeatable
        """
        period = create_period(api)
        create_recording(api)
        batch = create_batch(api, period["id"])
        append_line(
            api,
            batch["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=300000,
        )
        seal_batch(api, batch["id"])

        matched = validate_success(api.match_usage_batch(batch["id"], MATCHER), 200)
        assert matched["status"] == "MATCHED"
        assert matched["matched_play_count"] == 300000
        assert matched["unmatched_play_count"] == 0

        validate_error(
            api.match_usage_batch(batch["id"], MATCHER),
            ApiErrorId.ERR_INVALID_USAGE_BATCH_STATE.value,
            409,
        )

        after = validate_success(api.get_usage_batch(batch["id"], ANALYST), 200)
        assert after["status"] == "MATCHED"
        assert after["line_count"] == 1
        assert after["total_play_count"] == 300000
        assert after["matched_play_count"] == 300000


# ─────────────────────────────────────────────────────
# RightsRegistration
# ─────────────────────────────────────────────────────

class TestRightsRegistrationTransitions:
    def test_new_registration_lands_in_submitted_with_evidence_round_zero(self, api):
        """A newly filed claim lands in SUBMITTED with evidence_round 0, no reviewer, no disputing holder and supersede_overlapping false.

        PRD: "A successful filing lands the registration at `status` `SUBMITTED` with `evidence_round` at 0."

        Design: Corner/state_machines/registration_is_created_in_submitted_with_derived_payee
        """
        label = create_label(api)
        recording = create_recording(api)

        registration = file_registration(
            api,
            recording["id"],
            label["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        )

        assert registration["status"] == "SUBMITTED"
        assert registration["evidence_round"] == 0
        assert registration["reviewed_by_user_id"] is None
        assert registration["disputing_holder_id"] is None
        assert registration["supersede_overlapping"] is False
        assert registration["collective_id"] is None

    def test_payee_holder_id_is_derived_from_direct_routing(self, api):
        """A DIRECT-routed claim has its payee_holder_id computed by the service as the claimant rather than supplied by the caller.

        PRD: "The service computes `payee_holder_id` from the routing — it equals `collective_id` when `routing` is `COLLECTIVE` and `claimant_id` when `routing` is `DIRECT` — re-derives the work's `rights_state`, which becomes `PROVISIONAL` if no stronger state applies, and increments the work's `version`."

        Design: Corner/state_machines/registration_is_created_in_submitted_with_derived_payee
        """
        label = create_label(api)
        recording = create_recording(api)

        registration = file_registration(
            api,
            recording["id"],
            label["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        )

        assert registration["routing"] == "DIRECT"
        assert registration["payee_holder_id"] == label["id"]
        assert registration["payee_holder_id"] == registration["claimant_id"]

    def test_approve_straight_from_submitted_is_refused(self, api):
        """UNDER_REVIEW is a mandatory waypoint, so approving a SUBMITTED claim is refused and the claim stays SUBMITTED until review moves it.

        PRD: "`REJECTED` and `SUPERSEDED` accept no transition whatsoever, and any transition requested against a registration that is not in the state the transition requires is refused with `ERR_INVALID_REGISTRATION_STATE`."

        Design: Corner/state_machines/registration_is_created_in_submitted_with_derived_payee
        """
        label = create_label(api)
        recording = create_recording(api)
        registration = file_registration(
            api,
            recording["id"],
            label["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        )

        validate_error(
            api.approve_rights_registration(registration["id"], REVIEWER),
            ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value,
            409,
        )

        unchanged = validate_success(
            api.get_rights_registration(registration["id"], ANALYST), 200
        )
        assert unchanged["status"] == "SUBMITTED"

        reviewed = validate_success(
            api.review_rights_registration(registration["id"], REVIEWER), 200
        )
        assert reviewed["status"] == "UNDER_REVIEW"

    def test_reject_stores_the_reason_and_reviewer_and_registers_nothing(self, api):
        """Rejecting a claim under review stores the reason and the rejecting analyst's identifier and leaves the work with no registered ownership.

        PRD: "Rejection is the terminal alternative: a `RightsOpsAnalyst` may move a claim `UNDER_REVIEW → REJECTED` by supplying a `rejection_reason`, which is stored alongside `reviewed_by_user_id` — the analyst's own `X-User-ID` — after which the work's `rights_state` is re-derived."

        Design: Corner/state_machines/registration_rejected_is_terminal_for_every_trigger
        """
        label = create_label(api)
        recording = create_recording(api)
        registration = file_registration(
            api,
            recording["id"],
            label["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        )
        review_registration(api, registration["id"])

        rejected = validate_success(
            api.reject_rights_registration(
                registration["id"],
                rejection_payload(
                    rejection_reason="claimant is not the master owner of record"
                ),
                REVIEWER,
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "claimant is not the master owner of record"
        assert rejected["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID

        work = validate_success(api.get_work(recording["id"], ANALYST), 200)
        assert work["rights_state"] == "UNMATCHED"
        assert work["approved_master_share_bps"] == 0

    def test_rejected_registration_accepts_no_transition(self, api):
        """A REJECTED claim refuses review, request-evidence, evidence, approve and dispute alike and stays REJECTED with evidence_round 0.

        PRD: "`REJECTED` and `SUPERSEDED` accept no transition whatsoever, and any transition requested against a registration that is not in the state the transition requires is refused with `ERR_INVALID_REGISTRATION_STATE`."

        Design: Corner/state_machines/registration_rejected_is_terminal_for_every_trigger
        """
        label = create_label(api)
        rival = create_label(api, legal_name="Kestrel Tapes", territory="GB", rate_bps=800)
        recording = create_recording(api)
        registration = file_registration(
            api,
            recording["id"],
            label["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        )
        review_registration(api, registration["id"])
        validate_success(
            api.reject_rights_registration(
                registration["id"],
                rejection_payload(
                    rejection_reason="claimant is not the master owner of record"
                ),
                REVIEWER,
            ),
            200,
        )

        registration_id = registration["id"]
        refused = [
            api.review_rights_registration(registration_id, REVIEWER),
            api.request_registration_evidence(registration_id, REVIEWER),
            api.submit_registration_evidence(
                registration_id, make_rights_holder_user_headers(label["id"])
            ),
            api.approve_rights_registration(registration_id, REVIEWER),
            api.dispute_rights_registration(
                registration_id,
                dispute_payload(rival["id"]),
                make_rights_holder_user_headers(rival["id"]),
            ),
        ]
        for response in refused:
            validate_error(
                response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value, 409
            )

        work = validate_success(api.get_work(recording["id"], ANALYST), 200)
        assert work["rights_state"] == "UNMATCHED"
        assert work["approved_master_share_bps"] == 0

        final = validate_success(
            api.get_rights_registration(registration_id, ANALYST), 200
        )
        assert final["status"] == "REJECTED"
        assert final["evidence_round"] == 0


# ─────────────────────────────────────────────────────
# RoyaltyPool
# ─────────────────────────────────────────────────────

class TestRoyaltyPoolTransitions:
    def test_finalize_from_draft_returns_invalid_pool_state(self, api):
        """Finalize is legal only from CALCULATED, so finalizing a DRAFT pool is refused with the pool-state error and performs no partial freeze.

        PRD: "A pool that is `FINALIZED` cannot be calculated, and a pool in any state the requested transition does not allow is refused with `ERR_INVALID_POOL_STATE`, while a wrongly-stated parent period yields `ERR_INVALID_PERIOD_STATE`."

        Design: Corner/state_machines/pool_finalize_from_draft_returns_invalid_state
        """
        period = create_period(api)
        pool = create_pool(api, period["id"])
        assert pool["status"] == "DRAFT"

        validate_error(
            api.finalize_pool(pool["id"], ADMIN),
            ApiErrorId.ERR_INVALID_POOL_STATE.value,
            409,
        )

        after = validate_success(api.get_pool(pool["id"], ADMIN), 200)
        assert after["status"] == "DRAFT"
        assert after["distributable_cents"] == 0
        assert after["allocation_basis"] is None
        assert after["applied_rate_schedule_id"] is None
        assert after["residual_payee_holder_id"] is None


# ─────────────────────────────────────────────────────
# AccountingPeriod
# ─────────────────────────────────────────────────────

class TestAccountingPeriodTransitions:
    def test_close_from_open_returns_invalid_period_state(self, api):
        """An OPEN period whose claim window has already closed still refuses the close with the period-state error and stays OPEN.

        PRD: "A `RoyaltyAdmin` may close a period whose `status` is `DISTRIBUTED` — any other state is refused with `ERR_INVALID_PERIOD_STATE` — and only when three further conditions hold."

        Design: Corner/state_machines/period_close_from_open_returns_invalid_state
        """
        period = create_period(api)
        assert (
            period["claim_window_closes_at"]
            == TEST_DEFAULTS["PERIOD_CLAIM_WINDOW_CLOSES_AT"]
        )
        set_clock(api, "2026-08-30T00:00:00Z")

        validate_error(
            api.close_period(period["id"], ADMIN),
            ApiErrorId.ERR_INVALID_PERIOD_STATE.value,
            409,
        )

        after = validate_success(api.get_period(period["id"], ADMIN), 200)
        assert after["status"] == "OPEN"
        assert after["total_holding_cents"] == 0

    def test_finalizing_the_last_pool_reconciles_both_batch_shapes(self, api):
        """Finalizing the period's only pool bubbles the period to DISTRIBUTED and drags the fully matched and the partially matched batch alike to RECONCILED.

        PRD: "On the `USAGE_SEALED → DISTRIBUTED` transition every usage batch of the period is reconciled, by way of `MATCHED → RECONCILED` for a fully matched batch and `PARTIALLY_MATCHED → RECONCILED` for one that still carries unmatched plays."

        Design: Corner/state_machines/batches_move_to_reconciled_when_the_period_distributes
        """
        fixture = _setup_two_batch_period_with_calculated_pool(api)

        assert fixture["batch_a_after_match"]["status"] == "MATCHED"
        assert fixture["batch_b_after_match"]["status"] == "PARTIALLY_MATCHED"
        assert fixture["batch_b_after_match"]["unmatched_play_count"] == 50000

        before = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN), 200
        )
        assert before["status"] == "USAGE_SEALED"

        pool = fixture["pool"]
        assert pool["total_play_count"] == 350000
        assert pool["distributable_cents"] == 999999
        assert pool["denominator_basis"] == "ALL_USAGE"
        assert pool["denominator_play_count"] == 350000
        assert pool["matched_attributed_cents"] == 857142
        assert pool["holding_cents"] == 142857
        assert pool["rounding_residual_cents"] == 0

        finalized = validate_success(api.finalize_pool(pool["id"], ADMIN), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["residual_payee_holder_id"] is None
        assert finalized["rounding_residual_cents"] == 0

        after = validate_success(api.get_period(fixture["period"]["id"], ADMIN), 200)
        assert after["status"] == "DISTRIBUTED"

        reconciled, _meta = validate_paginated(
            api.list_usage_batches(
                ANALYST,
                params={
                    "period_id": fixture["period"]["id"],
                    "status": "RECONCILED",
                },
            )
        )
        assert {batch["id"] for batch in reconciled} == {
            fixture["batch_a"]["id"],
            fixture["batch_b"]["id"],
        }

    def test_a_reconciled_batch_cannot_be_matched_again(self, api):
        """RECONCILED is terminal, so re-matching a reconciled batch is refused and its unmatched plays stay frozen out of the distribution.

        PRD: "A `RoyaltyAdmin` or a `RightsOpsAnalyst` runs it over a batch whose `status` is `SEALED`; a batch in any other state is refused with `ERR_INVALID_USAGE_BATCH_STATE`."

        Design: Corner/state_machines/batches_move_to_reconciled_when_the_period_distributes
        """
        fixture = _setup_two_batch_period_with_calculated_pool(api)
        finalize_pool(api, fixture["pool"]["id"])

        validate_error(
            api.match_usage_batch(fixture["batch_b"]["id"], MATCHER),
            ApiErrorId.ERR_INVALID_USAGE_BATCH_STATE.value,
            409,
        )

        after = validate_success(
            api.get_usage_batch(fixture["batch_b"]["id"], ANALYST), 200
        )
        assert after["status"] == "RECONCILED"
        assert after["unmatched_play_count"] == 50000


# ─────────────────────────────────────────────────────
# RateSchedule
# ─────────────────────────────────────────────────────

class TestRateScheduleTransitions:
    def test_promulgating_twice_returns_invalid_rate_schedule_state(self, api):
        """Promulgation is legal only from PROPOSED, so a second promulgate of the same schedule is refused and does not re-stamp promulgated_at.

        PRD: "Only a `RegulatoryOfficer` may do it, only against a schedule whose `status` is `PROPOSED` — otherwise `ERR_INVALID_RATE_SCHEDULE_STATE` — and it accepts a single optional input, `supersede_incumbent`."

        Design: Corner/state_machines/rate_schedule_promulgate_twice_returns_invalid_state
        """
        schedule = create_schedule(api)
        assert schedule["status"] == "PROPOSED"
        assert schedule["promulgated_at"] is None

        effective = validate_success(
            api.promulgate_rate_schedule(schedule["id"], REGULATOR, {}), 200
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["promulgated_at"].replace(".000Z", "Z") == DEFAULT_CLOCK_UTC

        validate_error(
            api.promulgate_rate_schedule(schedule["id"], REGULATOR, {}),
            ApiErrorId.ERR_INVALID_RATE_SCHEDULE_STATE.value,
            409,
        )

        after = validate_success(api.get_rate_schedule(schedule["id"], REGULATOR), 200)
        assert after["status"] == "EFFECTIVE"
        assert after["promulgated_at"].replace(".000Z", "Z") == DEFAULT_CLOCK_UTC


# ─────────────────────────────────────────────────────
# RoyaltyStatement
# ─────────────────────────────────────────────────────

class TestRoyaltyStatementTransitions:
    def test_first_issue_moves_the_statement_and_credits_the_payee(self, api):
        """Issuing a DRAFT statement stamps issued_at from the logical clock and raises the payee's receivable balance by exactly its net payable.

        PRD: "Issuing moves the statement `DRAFT → ISSUED`, stamps `issued_at` from the logical clock, raises the payee's `receivable_balance_cents` by exactly `net_payable_cents`, increments the payee's `issued_statement_count` by 1, and increments the statement's `version`."

        Design: Corner/state_machines/statement_issue_twice_and_engagement_against_draft_are_refused
        """
        fixture = _setup_single_line_finalized_pool(api)
        assert fixture["pool"]["distributable_cents"] == 999999

        draft = create_statement(api, fixture["label"]["id"], fixture["period"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["line_count"] == 1
        assert draft["gross_cents"] == 749999
        assert draft["admin_fee_cents"] == 60000
        assert draft["net_payable_cents"] == 689999

        issued = validate_success(api.issue_statement(draft["id"], ADMIN), 200)
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"].replace(".000Z", "Z") == DEFAULT_CLOCK_UTC

        holder = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN), 200
        )
        assert holder["receivable_balance_cents"] == 689999
        assert holder["issued_statement_count"] == 1

    def test_second_issue_is_refused_with_no_double_credit(self, api):
        """A second issue of an already-ISSUED statement is refused and the payee's balance and issued-statement count stay exactly where the first issue left them.

        PRD: "A statement that assembled to no lines at all cannot be issued and is refused with `ERR_NO_STATEMENT_LINES`; a statement that is not `DRAFT` is refused with `ERR_INVALID_STATEMENT_STATE`."

        Design: Corner/state_machines/statement_issue_twice_and_engagement_against_draft_are_refused
        """
        fixture = _setup_single_line_issued_statement(api)
        assert fixture["statement"]["net_payable_cents"] == 689999

        before = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN), 200
        )
        assert before["receivable_balance_cents"] == 689999
        assert before["issued_statement_count"] == 1

        validate_error(
            api.issue_statement(fixture["statement"]["id"], ADMIN),
            ApiErrorId.ERR_INVALID_STATEMENT_STATE.value,
            409,
        )

        after = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN), 200
        )
        assert after["receivable_balance_cents"] == 689999
        assert after["issued_statement_count"] == 1

    def test_engagement_against_a_draft_statement_is_refused(self, api):
        """An audit engagement opened against a DRAFT statement is refused with the statement-state error, which fires before the audit window is even consulted.

        PRD: "The audited statement's `status` must be `ISSUED`; an engagement opened against a `DRAFT` or `SUPERSEDED` statement is refused with `ERR_INVALID_STATEMENT_STATE`."

        Design: Corner/state_machines/statement_issue_twice_and_engagement_against_draft_are_refused
        """
        fixture = _setup_single_line_issued_statement(api)
        publisher = create_publisher(
            api, legal_name="Tidewater Songs", territory="GB", rate_bps=800
        )

        draft = create_statement(api, publisher["id"], fixture["period"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["line_count"] == 0
        assert draft["issued_at"] is None

        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(publisher["id"], draft["id"]),
                make_rights_holder_user_headers(publisher["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATEMENT_STATE.value,
            409,
        )


# ─────────────────────────────────────────────────────
# AuditEngagement
# ─────────────────────────────────────────────────────

class TestAuditEngagementTransitions:
    def test_engagement_is_created_with_frozen_counters_and_deadline(self, api):
        """A new engagement freezes required_line_count from the audited statement's line count, sets its production deadline 30 days out, and starts at PENDING/NONE.

        PRD: "On creation the service freezes `required_line_count` from the number of statement lines the audited statement carries at that moment — frozen thereafter, so lines added later do not move the target — computes `production_deadline_at` as `created_at` advanced by 30 days, and sets `produced_line_count` to 0, `production_status` to `PENDING` and `finding_status` to `NONE`."

        Design: Corner/state_machines/engagement_settle_before_findings_returns_invalid_state
        """
        fixture = _setup_single_line_issued_statement(api)
        assert len(fixture["statement_lines"]) == 1

        engagement = create_engagement(
            api, fixture["label"]["id"], fixture["statement"]["id"]
        )

        assert engagement["required_line_count"] == 1
        assert engagement["produced_line_count"] == 0
        assert engagement["production_status"] == "PENDING"
        assert engagement["finding_status"] == "NONE"
        assert (
            engagement["production_deadline_at"].replace(".000Z", "Z")
            == "2026-08-31T00:00:00Z"
        )

    def test_one_full_production_reaches_complete_in_a_single_call(self, api):
        """Producing every required line in one call takes production_status straight from PENDING to COMPLETE, skipping PARTIAL and leaving finding_status untouched.

        PRD: "When the recomputed count is still strictly below `required_line_count`, the engagement moves `PENDING → PARTIAL`; when it equals `required_line_count`, the engagement moves `PENDING → COMPLETE` if the whole set arrived in one call, or `PARTIAL → COMPLETE` if it accumulated over several."

        Design: Corner/state_machines/engagement_settle_before_findings_returns_invalid_state
        """
        fixture = _setup_single_line_issued_statement(api)
        engagement = create_engagement(
            api, fixture["label"]["id"], fixture["statement"]["id"]
        )

        produced = validate_success(
            api.produce_audit_data(
                engagement["id"],
                data_production_payload([fixture["statement_lines"][0]["id"]]),
                ADMIN,
            ),
            200,
        )

        assert produced["produced_line_count"] == 1
        assert produced["required_line_count"] == 1
        assert produced["production_status"] == "COMPLETE"
        assert produced["finding_status"] == "NONE"

    def test_settle_before_a_finding_is_asserted_is_refused(self, api):
        """Settling an engagement whose finding_status is still NONE is refused, and the refusal moves neither status dimension nor the holder's balance.

        PRD: "A `RoyaltyAdmin` settles an engagement whose `finding_status` is `ASSERTED` and whose `production_status` is `COMPLETE`, supplying a `resolution` and, on the upholding branch, a `settled_amount_cents`."

        Design: Corner/state_machines/engagement_settle_before_findings_returns_invalid_state
        """
        fixture = _setup_single_line_issued_statement(api)
        engagement = create_engagement(
            api, fixture["label"]["id"], fixture["statement"]["id"]
        )
        produced = produce_audit_data(
            api, engagement["id"], [fixture["statement_lines"][0]["id"]]
        )
        assert produced["production_status"] == "COMPLETE"
        assert produced["finding_status"] == "NONE"

        validate_error(
            api.settle_audit_engagement(
                engagement["id"],
                settlement_payload("UPHOLD", settled_amount_cents=5000),
                SETTLING_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value,
            409,
        )

        after = validate_success(
            api.get_audit_engagement(engagement["id"], ADMIN), 200
        )
        assert after["production_status"] == "COMPLETE"
        assert after["finding_status"] == "NONE"
        assert after["settled_amount_cents"] == 0
        assert after["interest_cents"] == 0

        holder = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN), 200
        )
        assert holder["receivable_balance_cents"] == 689999
