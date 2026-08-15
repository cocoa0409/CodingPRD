"""Statement approval chain: finalize gating, cash ledger, void compensation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_dispute,
    assert_cents,
    create_active_plan,
    create_agreement,
    create_dispute_under_review,
    create_effective_agreement,
    create_under_review_statement,
    create_validated_capture,
    file_capture_dispute,
    get_success_data,
    make_committee_headers,
    make_physician_headers,
    register_physician,
    reject_dispute,
    set_clock,
    setup_active_plan_with_effective_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANALYST_2 = TEST_USERS["analyst_2_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
COMMITTEE_9 = TEST_USERS["committee_9_headers"]


def _statement_with_open_dispute(api):
    """EFFECTIVE agreement + validated 9.70-wRVU capture + UNDER_REVIEW statement
    + a FILED dispute on the capture (PRD §3.7 finalize gate)."""
    scenario = setup_active_plan_with_effective_agreement(
        npi="1000000081", plan_name="Blk Plan"
    )
    agr_id = scenario["agreement"]["id"]
    capture = create_validated_capture(agr_id, units=10)
    stmt = create_under_review_statement(agr_id, 2026, 2)
    dispute = file_capture_dispute(scenario["physician"]["id"], capture["id"],
                                   "questioning units")
    return {**scenario, "capture": capture, "stmt": stmt, "dispute": dispute}


def _cash_scenario(api):
    """EFFECTIVE agreement (draw 1000000) + one validated 5000.00-wRVU capture +
    UNDER_REVIEW 2026-02 statement on a single-tier plan (PRD §3.7)."""
    scenario = setup_active_plan_with_effective_agreement(
        npi="1000000101", plan_name="Cash Plan",
        rates=[{"cpt_code": "99285", "wrvu_value": 5.0}],
    )
    agr_id = scenario["agreement"]["id"]
    capture = create_validated_capture(agr_id, cpt_code="99285", units=1000,
                                       service_date="2026-02-05",
                                       posting_date="2026-02-05")
    stmt = create_under_review_statement(agr_id, 2026, 2)
    return {**scenario, "capture": capture, "stmt": stmt}


class TestFinalizeGating:
    def test_finalize_blocked_by_open_dispute(self, api):
        """PRD §3.7: "The committee finalizes an `UNDER_REVIEW` statement — but only when no dispute on the same agreement sits in `FILED`, `UNDER_REVIEW`, or `DATA_CORRECTION` (`ERR_OPEN_DISPUTES`)"

        Design: Difficulty/cross_entity_state_dependency/statement_finalize_blocked_by_open_dispute
        """
        scenario = _statement_with_open_dispute(api)
        assert scenario["dispute"]["status"] == "FILED"
        resp = api.finalize_statement(scenario["stmt"]["id"], COMMITTEE_9)
        validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTES)
        stmt = get_success_data(api.get_statement(scenario["stmt"]["id"], ANALYST))
        assert stmt["status"] == "UNDER_REVIEW", "a blocked finalize changes nothing"

    def test_finalize_succeeds_after_dispute_terminal(self, api):
        """PRD §3.8: "Resolution belongs to the committee and takes a `resolution` of `ACCEPTED` or `REJECTED` from either `UNDER_REVIEW` or `DATA_CORRECTION`, moving the dispute to its terminal state `RESOLVED_ACCEPTED` or `RESOLVED_REJECTED` respectively. Rejection simply records `resolution` `REJECTED` and the resolver's `X-User-ID` as `resolver_user_id` — no compensation side effects"
        PRD §3.7: "Finalization moves the statement to `FINALIZED`, locks every included capture from `VALIDATED` to `LOCKED` (documentation frozen while `credit_status` stays `CREDITED` — the two axes evolve independently)"

        Design: Difficulty/cross_entity_state_dependency/statement_finalize_blocked_by_open_dispute
        """
        scenario = _statement_with_open_dispute(api)
        validate_error(api.finalize_statement(scenario["stmt"]["id"], COMMITTEE_9),
                       ApiErrorId.ERR_OPEN_DISPUTES)
        get_success_data(api.start_dispute_review(scenario["dispute"]["id"], ANALYST))
        reject_dispute(scenario["dispute"]["id"])
        finalized = validate_success(
            api.finalize_statement(scenario["stmt"]["id"], COMMITTEE_9), 200
        )
        assert finalized["status"] == "FINALIZED"
        capture = get_success_data(api.get_capture(scenario["capture"]["id"], ANALYST))
        assert capture["capture_status"] == "LOCKED", "finalize locks included captures"
        assert capture["credit_status"] == "CREDITED", "a REJECTED dispute fires no compensation"

    def test_finalizer_must_differ_from_statement_creator(self, api):
        """PRD §3.7: "only when the finalizer's `X-User-ID` differs from the statement's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); on the finalize call the state guard fires first, then segregation of duties, then the open-disputes check."
        PRD §2.8: "the `CompCommittee` member finalizing a compensation statement must not be the analyst recorded as that statement's `created_by_user_id`."

        Design: Corner/validations/statement_finalize_segregation_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000243", plan_name="Fin Plan"
        )
        stmt = create_under_review_statement(scenario["agreement"]["id"], 2026, 2)
        resp_same_user = api.finalize_statement(
            stmt["id"], make_committee_headers("an_1")  # same id as the generating analyst
        )
        validate_error(resp_same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        finalized = validate_success(
            api.finalize_statement(stmt["id"], COMMITTEE_9), 200
        )
        assert finalized["status"] == "FINALIZED"

    def test_analyst_role_cannot_finalize(self, api):
        """PRD §4: POST /comp/comp-statements/{id}/finalize is authorized for CompCommittee only.
        PRD §2.1: "A `CompAnalyst` is the compensation-office analyst: it drafts plans, rate rows, and agreements; posts and validates production; runs statements and true-ups; triages disputes; and drafts plan changes. It never approves compliance artifacts and never finalizes payments."
        PRD §2.1: "A request whose role is not listed among the roles authorized for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_finalize_statement
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000271", plan_name="Fin2 Plan"
        )
        stmt = create_under_review_statement(scenario["agreement"]["id"], 2026, 2)
        resp = api.finalize_statement(stmt["id"], ANALYST_2)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestCashLedger:
    def test_finalize_pays_into_lifetime_paid(self, api):
        """PRD §3.7: "Finalization moves the statement to `FINALIZED`, locks every included capture from `VALIDATED` to `LOCKED` (documentation frozen while `credit_status` stays `CREDITED` — the two axes evolve independently), and recomputes the agreement's `lifetime_paid_cents` to include this statement's `net_payment_cents`"

        Design: Difficulty/compensating_invariant/statement_void_cash_conservation
        """
        scenario = _cash_scenario(api)
        stmt = scenario["stmt"]
        # 5000.00 wRVU x 4500c = 22500000 earned; net = 22500000 + 0 + 0 + 0 - 1000000.
        assert_cents(stmt["net_payment_cents"], 21500000)
        finalized = validate_success(api.finalize_statement(stmt["id"], COMMITTEE_9), 200)
        assert finalized["status"] == "FINALIZED"
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert_cents(agreement["lifetime_paid_cents"], 21500000)

    def test_void_rolls_cash_back_and_unlocks_captures(self, api):
        """PRD §3.7: "The committee may void a `FINALIZED` statement, supplying a `reason`; the statement moves to `VOIDED`, each included capture still `CREDITED` is unlocked from `LOCKED` back to `VALIDATED`, and the agreement's `lifetime_paid_cents` is recomputed to exclude the statement — a cash rollback to its pre-finalize value."
        PRD §3.7: "The statement listing accepts an optional `status` filter"

        Design: Difficulty/compensating_invariant/statement_void_cash_conservation
        """
        scenario = _cash_scenario(api)
        stmt_id = scenario["stmt"]["id"]
        get_success_data(api.finalize_statement(stmt_id, COMMITTEE_9))
        voided = validate_success(
            api.void_statement(stmt_id, {"reason": "posted to wrong period"}, COMMITTEE_9),
            200,
        )
        assert voided["status"] == "VOIDED"
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert agreement["lifetime_paid_cents"] == 0, (
            "finalize (+21500000) paired with its compensating void returns the cash "
            "ledger to exactly its pre-finalize value"
        )
        capture = get_success_data(api.get_capture(scenario["capture"]["id"], ANALYST))
        assert capture["capture_status"] == "VALIDATED", "the void unlocks the capture"
        assert capture["credit_status"] == "CREDITED"
        rows, _ = validate_paginated(
            api.list_statements(scenario["agreement"]["id"], ANALYST)
        )
        voided_rows = [s for s in rows if s["id"] == stmt_id]
        assert voided_rows and voided_rows[0]["status"] == "VOIDED", (
            "the VOIDED statement remains queryable"
        )


class TestParallelCaptureAxes:
    def test_finalize_locks_documentation_axis_only(self, api):
        """PRD §3.7: "Finalization moves the statement to `FINALIZED`, locks every included capture from `VALIDATED` to `LOCKED` (documentation frozen while `credit_status` stays `CREDITED` — the two axes evolve independently)"

        Design: Difficulty/non_linear_state_machine/capture_parallel_state_dimensions
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000030", plan_name="Par Plan"
        )
        agr_id = scenario["agreement"]["id"]
        capture = create_validated_capture(agr_id, units=10)
        stmt = create_under_review_statement(agr_id, 2026, 2)
        get_success_data(api.finalize_statement(stmt["id"], COMMITTEE_9))
        locked = get_success_data(api.get_capture(capture["id"], ANALYST))
        assert locked["capture_status"] == "LOCKED"
        assert locked["credit_status"] == "CREDITED", (
            "the documentation axis moved; the credit axis did not"
        )

    def test_reversal_moves_credit_axis_only(self, api):
        """PRD §3.8: "Acceptance flips the subject capture `CREDITED → REVERSED`, records a `reversed_reason` drawn from the resolving dispute, recomputes the owning agreement's `ytd_wrvu_credited`"
        PRD §3.7: "each included capture still `CREDITED` is unlocked from `LOCKED` back to `VALIDATED`"
        PRD §3.8: "moving the dispute to its terminal state `RESOLVED_ACCEPTED` or `RESOLVED_REJECTED` respectively"

        Design: Difficulty/non_linear_state_machine/capture_parallel_state_dimensions
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000030", plan_name="Par Plan"
        )
        agr_id = scenario["agreement"]["id"]
        capture = create_validated_capture(agr_id, units=10)
        stmt = create_under_review_statement(agr_id, 2026, 2)
        get_success_data(api.finalize_statement(stmt["id"], COMMITTEE_9))
        dispute = create_dispute_under_review(scenario["physician"]["id"], capture["id"],
                                              "units keyed incorrectly")
        resolved = accept_dispute(dispute["id"])
        assert resolved["status"] == "RESOLVED_ACCEPTED"
        assert resolved["resolution"] == "ACCEPTED"
        after = get_success_data(api.get_capture(capture["id"], ANALYST))
        assert after["credit_status"] == "REVERSED"
        assert after["capture_status"] == "LOCKED", (
            "unlock happens only on statement void, and only for captures still CREDITED"
        )
        agreement = get_success_data(api.get_agreement(agr_id, ANALYST))
        assert agreement["ytd_wrvu_credited"] == 0.00


class TestPhysicianOwnership:
    def test_physician_reads_only_own_agreement(self, api):
        """PRD §2.1: "A `Physician`-role caller may read only its own physician record, its own agreements, statements, and captures, list only its own disputes, file disputes only on subjects belonging to its own agreement, and acknowledge plan changes only for plans it is enrolled in; any other access is refused with `ERR_NOT_OWN_RESOURCE`."

        Design: Corner/rbac/physician_ownership_scope_enforced
        """
        set_clock()
        pa = register_physician(npi="1000000273", full_name="Dr PA")
        pb = register_physician(npi="1000000274", full_name="Dr PB")
        plan, _ = create_active_plan(name="Own Plan")
        agr_a = create_effective_agreement(pa["id"], plan["id"])
        agr_b = create_agreement(pb["id"], plan["id"])
        own = validate_success(
            api.get_agreement(agr_a["id"], make_physician_headers(pa["id"])), 200
        )
        assert own["id"] == agr_a["id"]
        resp = api.get_agreement(agr_b["id"], make_physician_headers(pa["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE)
        assert resp.status_code == 403, "the resource exists but is out of scope (not 404)"
