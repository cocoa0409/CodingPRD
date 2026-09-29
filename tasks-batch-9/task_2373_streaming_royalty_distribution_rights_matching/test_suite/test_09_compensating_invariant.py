"""Conserved quantities under a cascade and its compensating reversal.

Three identities are checked here: the royalty pool's value identity, the usage
batch's play-count identity, and a rights holder's receivable balance. Each is
observed before a forward mutation, after it, after an operation that is refused,
and after the compensating mutation that unwinds the forward one.
"""

from test_helpers import (
    ADMIN_SETTLE_USER_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    assert_audit_engagement,
    assert_play_count_conservation,
    assert_pool_value_conservation,
    assert_rights_holder,
    assert_royalty_pool,
    assert_royalty_statement,
    assert_usage_batch,
    assert_usage_line,
    create_engagement,
    create_schedule,
    dispute_payload,
    dispute_registration,
    approve_registration,
    issue_statement,
    make_rights_holder_user_headers,
    produce_audit_data,
    promulgate_schedule,
    record_findings,
    settle_engagement,
    settlement_payload,
    setup_all_matched_statement_drafted,
    setup_registration_under_review_for_recording_b,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
SETTLING_ADMIN_HEADERS = TEST_USERS["settling_admin_headers"]


# ─────────────────────────────────────────────────────
# Composite state this file needs and fixtures.py lacks
# ─────────────────────────────────────────────────────

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


def _setup_drafted_statement_with_proposed_remand(api):
    """The all-matched GB/INDIVIDUAL fixture carried to a DRAFT statement for the
    label, plus a PROPOSED retroactive replacement schedule for the same cell at
    a higher revenue share and the same statutory floor.

    Promulgating that proposal later is what reopens the pool and supersedes the
    statement the label has by then been issued.
    """
    fixture = setup_all_matched_statement_drafted(api)
    fixture["remand_schedule"] = create_schedule(api, **_REMAND_SCHEDULE)
    return fixture


# ─────────────────────────────────────────────────────
# royalty_pool_value_conservation
# ─────────────────────────────────────────────────────

class TestRoyaltyPoolValueConservation:

    def test_approve_moves_holding_cents_into_matched_attributed_only(self, api):
        """Approving the claim over the unresolved recording moves exactly 99999 cents from holding_cents into matched_attributed_cents, leaving distributable_cents 999999 and rounding_residual_cents 2 untouched.

        PRD: "Within a `RoyaltyPool`, `matched_attributed_cents` plus `holding_cents` plus `rounding_residual_cents` equals `distributable_cents` at all times."

        Design: Difficulty/compensating_invariant/royalty_pool_value_conservation
        """
        fixture = setup_registration_under_review_for_recording_b(api, second_label=True)
        pool_id = fixture["pool"]["id"]

        # Observation 0 — before the forward action.
        before = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert_royalty_pool(before)
        assert before["matched_attributed_cents"] == 899998
        assert before["holding_cents"] == 99999
        assert before["rounding_residual_cents"] == 2
        assert before["distributable_cents"] == 999999
        assert_pool_value_conservation(before)

        approve_registration(api, fixture["claim_registration"]["id"])

        # Observation 1 — after the forward action.
        after = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert_royalty_pool(after)
        assert after["matched_attributed_cents"] == 999997
        assert after["holding_cents"] == 0
        assert after["rounding_residual_cents"] == 2
        assert after["distributable_cents"] == 999999
        assert_pool_value_conservation(after)

        # Exactly the cents that left holding arrived in matched_attributed.
        assert after["matched_attributed_cents"] - before["matched_attributed_cents"] == 99999
        assert before["holding_cents"] - after["holding_cents"] == 99999

    def test_dispute_returns_exactly_the_same_cents_to_holding(self, api):
        """Disputing the approved claim returns exactly 99999 cents from matched_attributed_cents to holding_cents, a refused self-dispute leaves every figure bit-identical, and the pool lands back on observation zero.

        PRD: "Approving a claim moves cents out of `holding_cents` and into `matched_attributed_cents`; disputing that same claim moves exactly those cents back."

        Design: Difficulty/compensating_invariant/royalty_pool_value_conservation
        """
        fixture = setup_registration_under_review_for_recording_b(api, second_label=True)
        pool_id = fixture["pool"]["id"]
        registration_id = fixture["claim_registration"]["id"]
        claimant_id = fixture["label"]["id"]
        rival_id = fixture["rival_label"]["id"]
        unresolved_line_id = fixture["usage_lines"][2]["id"]

        # Observation 0 — before the forward action.
        before = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert before["matched_attributed_cents"] == 899998
        assert before["holding_cents"] == 99999
        assert before["rounding_residual_cents"] == 2
        assert before["distributable_cents"] == 999999
        assert_pool_value_conservation(before)

        approve_registration(api, registration_id)

        # Observation 1 — after the forward action.
        approved = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert approved["matched_attributed_cents"] == 999997
        assert approved["holding_cents"] == 0
        assert approved["rounding_residual_cents"] == 2
        assert approved["distributable_cents"] == 999999
        assert_pool_value_conservation(approved)

        # A dispute raised by the claimant itself has no standing.
        refused = api.dispute_rights_registration(
            registration_id,
            dispute_payload(claimant_id),
            make_rights_holder_user_headers(claimant_id),
        )
        validate_error(refused, ApiErrorId.ERR_DISPUTE_BY_CLAIMANT.value, 422)

        # The refused call moved nothing: bit-identical to observation 1.
        unchanged = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert unchanged["matched_attributed_cents"] == 999997
        assert unchanged["holding_cents"] == 0
        assert unchanged["rounding_residual_cents"] == 2
        assert unchanged["distributable_cents"] == 999999
        assert_pool_value_conservation(unchanged)

        disputed_registration = dispute_registration(api, registration_id, rival_id)
        assert disputed_registration["status"] == "DISPUTED"

        # Observation 2 — after the compensating action.
        reversed_pool = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
        assert_royalty_pool(reversed_pool)
        assert reversed_pool["matched_attributed_cents"] == 899998
        assert reversed_pool["holding_cents"] == 99999
        assert reversed_pool["rounding_residual_cents"] == 2
        assert reversed_pool["distributable_cents"] == 999999
        assert_pool_value_conservation(reversed_pool)

        # The money is parked in holding, not deleted from the line.
        line = validate_success(api.get_usage_line(unresolved_line_id, ANALYST_HEADERS), 200)
        assert_usage_line(line)
        assert line["match_status"] == "DISPUTED"
        assert line["attributed_revenue_cents"] == 99999


# ─────────────────────────────────────────────────────
# usage_play_count_conservation
# ─────────────────────────────────────────────────────

class TestUsagePlayCountConservation:

    def test_approve_moves_unmatched_plays_into_matched(self, api):
        """Approving the claim over the unresolved recording moves all 50000 unmatched plays into matched_play_count, flipping the batch to MATCHED while total_play_count stays 500000.

        PRD: "Within a `UsageBatch`, `matched_play_count` plus `unmatched_play_count` plus `disputed_play_count` equals `total_play_count` at all times."

        Design: Difficulty/compensating_invariant/usage_play_count_conservation
        """
        fixture = setup_registration_under_review_for_recording_b(api, second_label=True)
        batch_id = fixture["batch"]["id"]

        # Observation 0 — before the forward action.
        before = validate_success(api.get_usage_batch(batch_id, ANALYST_HEADERS), 200)
        assert_usage_batch(before)
        assert before["total_play_count"] == 500000
        assert before["matched_play_count"] == 450000
        assert before["unmatched_play_count"] == 50000
        assert before["disputed_play_count"] == 0
        assert before["status"] == "PARTIALLY_MATCHED"
        assert_play_count_conservation(before)

        approve_registration(api, fixture["claim_registration"]["id"])

        # Observation 1 — after the forward action.
        after = validate_success(api.get_usage_batch(batch_id, ANALYST_HEADERS), 200)
        assert_usage_batch(after)
        assert after["total_play_count"] == 500000
        assert after["matched_play_count"] == 500000
        assert after["unmatched_play_count"] == 0
        assert after["disputed_play_count"] == 0
        assert after["status"] == "MATCHED"
        assert_play_count_conservation(after)

    def test_dispute_routes_the_plays_to_disputed_not_back_to_unmatched(self, api):
        """Disputing the approved claim moves the same 50000 plays out of matched_play_count into disputed_play_count rather than back into unmatched_play_count, with total_play_count fixed at 500000 throughout.

        PRD: "Approving a claim moves plays from `unmatched_play_count` into `matched_play_count`; disputing it moves exactly those plays from `matched_play_count` into `disputed_play_count`."

        Design: Difficulty/compensating_invariant/usage_play_count_conservation
        """
        fixture = setup_registration_under_review_for_recording_b(api, second_label=True)
        batch_id = fixture["batch"]["id"]

        # Observation 0 — before the forward action.
        before = validate_success(api.get_usage_batch(batch_id, ANALYST_HEADERS), 200)
        assert before["total_play_count"] == 500000
        assert before["matched_play_count"] == 450000
        assert before["unmatched_play_count"] == 50000
        assert before["disputed_play_count"] == 0
        assert before["status"] == "PARTIALLY_MATCHED"
        assert_play_count_conservation(before)

        approve_registration(api, fixture["claim_registration"]["id"])

        # Observation 1 — after the forward action.
        approved = validate_success(api.get_usage_batch(batch_id, ANALYST_HEADERS), 200)
        assert approved["total_play_count"] == 500000
        assert approved["matched_play_count"] == 500000
        assert approved["unmatched_play_count"] == 0
        assert approved["disputed_play_count"] == 0
        assert approved["status"] == "MATCHED"
        assert_play_count_conservation(approved)

        dispute_registration(api, fixture["claim_registration"]["id"], fixture["rival_label"]["id"])

        # Observation 2 — after the compensating action. The plays land in a
        # third bucket; unmatched_play_count is emphatically not restored.
        reversed_batch = validate_success(api.get_usage_batch(batch_id, ANALYST_HEADERS), 200)
        assert_usage_batch(reversed_batch)
        assert reversed_batch["total_play_count"] == 500000
        assert reversed_batch["matched_play_count"] == 450000
        assert reversed_batch["unmatched_play_count"] == 0
        assert reversed_batch["disputed_play_count"] == 50000
        assert_play_count_conservation(reversed_batch)


# ─────────────────────────────────────────────────────
# holder_receivable_conservation
# ─────────────────────────────────────────────────────

class TestHolderReceivableConservation:

    def test_issuing_raises_the_receivable_by_exactly_net_payable(self, api):
        """Issuing the label's single-line statement raises receivable_balance_cents from 0 to exactly the statement's net_payable_cents of 690000 and takes issued_statement_count to 1.

        PRD: "Issuing a statement raises the balance by exactly that statement's `net_payable_cents`; superseding it lowers the balance by exactly the same amount, returning it to its pre-issue value."

        Design: Difficulty/compensating_invariant/holder_receivable_conservation
        """
        fixture = _setup_drafted_statement_with_proposed_remand(api)
        holder_id = fixture["label"]["id"]
        statement_id = fixture["statement"]["id"]

        # Observation 0 — the statement is still DRAFT.
        drafted = validate_success(api.get_statement(statement_id, ADMIN_HEADERS), 200)
        assert_royalty_statement(drafted)
        assert drafted["status"] == "DRAFT"
        assert drafted["net_payable_cents"] == 690000

        before = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert_rights_holder(before)
        assert before["receivable_balance_cents"] == 0
        assert before["issued_statement_count"] == 0

        issue_statement(api, statement_id)

        # Observation 1 — after the forward action.
        after = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert_rights_holder(after)
        assert after["receivable_balance_cents"] == 690000
        assert after["issued_statement_count"] == 1
        assert after["receivable_balance_cents"] - before["receivable_balance_cents"] == 690000

    def test_asserted_then_withdrawn_finding_leaves_the_receivable_untouched(self, api):
        """Asserting an underpayment of 250000 cents and then settling it with WITHDRAW leaves receivable_balance_cents at 690000 at both steps, and a settlement above the assertion is refused without moving it.

        PRD: "Statements in `DRAFT` or `SUPERSEDED` contribute zero, with no time window; engagements in `NONE`, `ASSERTED` or `WITHDRAWN` contribute zero."

        Design: Difficulty/compensating_invariant/holder_receivable_conservation
        """
        fixture = _setup_drafted_statement_with_proposed_remand(api)
        holder_id = fixture["label"]["id"]
        statement_id = fixture["statement"]["id"]

        # Observation 0 — the statement is still DRAFT.
        drafted = validate_success(api.get_statement(statement_id, ADMIN_HEADERS), 200)
        assert drafted["net_payable_cents"] == 690000
        pre_issue = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert pre_issue["receivable_balance_cents"] == 0
        assert pre_issue["issued_statement_count"] == 0

        issue_statement(api, statement_id)

        # Observation 1 — after the forward action.
        issued = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert issued["receivable_balance_cents"] == 690000
        assert issued["issued_statement_count"] == 1

        lines, _meta = validate_paginated(
            api.list_statement_lines(ADMIN_HEADERS, params={"statement_id": statement_id})
        )
        assert len(lines) == 1

        engagement = create_engagement(api, holder_id, statement_id)
        assert_audit_engagement(engagement)
        assert engagement["required_line_count"] == 1
        assert engagement["production_status"] == "PENDING"

        produced = produce_audit_data(api, engagement["id"], [lines[0]["id"]])
        assert produced["produced_line_count"] == 1
        assert produced["production_status"] == "COMPLETE"

        asserted = record_findings(api, engagement["id"], holder_id, 250000)
        assert asserted["finding_status"] == "ASSERTED"
        assert asserted["asserted_underpayment_cents"] == 250000
        assert asserted["production_status"] == "COMPLETE"

        # Observation 2 — an assertion is not a credit.
        after_assertion = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert after_assertion["receivable_balance_cents"] == 690000
        assert after_assertion["issued_statement_count"] == 1

        # A settlement of one cent above the assertion is refused.
        refused = api.settle_audit_engagement(
            engagement["id"],
            settlement_payload("UPHOLD", settled_amount_cents=250001),
            SETTLING_ADMIN_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_ASSERTION.value, 422)

        # Bit-identical to observation 2.
        unchanged = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert unchanged["receivable_balance_cents"] == 690000
        assert unchanged["issued_statement_count"] == 1

        withdrawn = settle_engagement(api, engagement["id"], "WITHDRAW")
        assert_audit_engagement(withdrawn)
        assert withdrawn["finding_status"] == "WITHDRAWN"
        assert withdrawn["settled_amount_cents"] == 0
        assert withdrawn["interest_cents"] == 0
        assert withdrawn["findings_recorded_by_user_id"] == holder_id
        assert withdrawn["findings_recorded_by_user_id"] != ADMIN_SETTLE_USER_ID

        # Observation 3 — after the compensating action.
        after_withdrawal = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert_rights_holder(after_withdrawal)
        assert after_withdrawal["receivable_balance_cents"] == 690000
        assert after_withdrawal["issued_statement_count"] == 1

    def test_retroactive_supersession_returns_the_receivable_to_its_pre_issue_value(self, api):
        """Promulgating the retroactive replacement schedule supersedes the issued statement and drops receivable_balance_cents from 690000 back to exactly 0, with no residue from the withdrawn audit.

        PRD: "Issuing a statement raises the balance by exactly that statement's `net_payable_cents`; superseding it lowers the balance by exactly the same amount, returning it to its pre-issue value."

        Design: Difficulty/compensating_invariant/holder_receivable_conservation
        """
        fixture = _setup_drafted_statement_with_proposed_remand(api)
        holder_id = fixture["label"]["id"]
        statement_id = fixture["statement"]["id"]

        # Observation 0 — the statement is still DRAFT.
        drafted = validate_success(api.get_statement(statement_id, ADMIN_HEADERS), 200)
        assert drafted["net_payable_cents"] == 690000
        pre_issue = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert pre_issue["receivable_balance_cents"] == 0
        assert pre_issue["issued_statement_count"] == 0

        issue_statement(api, statement_id)

        # Observation 1 — after the forward action.
        issued = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert issued["receivable_balance_cents"] == 690000
        assert issued["issued_statement_count"] == 1

        lines, _meta = validate_paginated(
            api.list_statement_lines(ADMIN_HEADERS, params={"statement_id": statement_id})
        )
        assert len(lines) == 1

        engagement = create_engagement(api, holder_id, statement_id)
        assert engagement["required_line_count"] == 1
        produced = produce_audit_data(api, engagement["id"], [lines[0]["id"]])
        assert produced["production_status"] == "COMPLETE"
        asserted = record_findings(api, engagement["id"], holder_id, 250000)
        assert asserted["finding_status"] == "ASSERTED"

        # Observation 2 — an assertion is not a credit.
        after_assertion = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert after_assertion["receivable_balance_cents"] == 690000
        assert after_assertion["issued_statement_count"] == 1

        # A settlement of one cent above the assertion is refused.
        refused = api.settle_audit_engagement(
            engagement["id"],
            settlement_payload("UPHOLD", settled_amount_cents=250001),
            SETTLING_ADMIN_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_ASSERTION.value, 422)

        # Bit-identical to observation 2.
        unchanged = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert unchanged["receivable_balance_cents"] == 690000
        assert unchanged["issued_statement_count"] == 1

        withdrawn = settle_engagement(api, engagement["id"], "WITHDRAW")
        assert withdrawn["finding_status"] == "WITHDRAWN"
        assert withdrawn["settled_amount_cents"] == 0
        assert withdrawn["interest_cents"] == 0

        # Observation 3 — the withdrawal contributes nothing either way.
        after_withdrawal = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert after_withdrawal["receivable_balance_cents"] == 690000
        assert after_withdrawal["issued_statement_count"] == 1

        promulgate_schedule(api, fixture["remand_schedule"]["id"], supersede_incumbent=True)

        # Observation 4 — after the second compensating action.
        superseded = validate_success(api.get_statement(statement_id, ADMIN_HEADERS), 200)
        assert_royalty_statement(superseded)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["net_payable_cents"] == 690000

        final = validate_success(api.get_rights_holder(holder_id, ADMIN_HEADERS), 200)
        assert_rights_holder(final)
        assert final["receivable_balance_cents"] == 0
        assert final["issued_statement_count"] == 0
        assert final["receivable_balance_cents"] == pre_issue["receivable_balance_cents"]
