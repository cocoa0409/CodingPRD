"""Determination recording, claim withdrawal/closure gates, and the reserve
ledger invariant across an appeal REVERSE decision."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_witness,
    appeal_determination,
    assert_line_item,
    create_claim,
    create_employer,
    create_model,
    create_separation,
    create_state_rule,
    create_statement,
    finalize_model,
    get_appeal,
    get_claim,
    get_determination,
    get_employer,
    get_line_item,
    get_model,
    get_statement,
    post_line,
    prep_witness_to_ready,
    schedule_hearing,
    set_clock,
    setup_determined_claim,
    setup_heard_appeal,
    submit_complete_response,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["claims_analyst_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]


class TestClaimClosureGates:
    def test_close_blocked_while_determination_not_final(self, api):
        """PRD §3.5: "A `ClaimsAnalyst` may close a claim only when it is
        `DETERMINED` (otherwise `ERR_CLAIM_NOT_CLOSABLE`), its determination is
        `FINAL` (otherwise `ERR_DETERMINATION_NOT_FINAL`), and no appeal
        remains in `FILED`, `DOCKETED`, or `HEARD` (otherwise
        `ERR_APPEAL_IN_FLIGHT`)."

        Design: Difficulty/cross_entity_state_dependency/claim_close_requires_determination_final
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_determined_claim()
        # Determination is ISSUED, no appeal exists: only the FINAL gate fails.
        assert ctx["determination"]["status"] == "ISSUED"

        err = api.close_claim(ctx["claim"]["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_DETERMINATION_NOT_FINAL, 409)
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"

    def test_close_succeeds_after_determination_final_via_affirm(self, api):
        """PRD §3.5: "**Affirm.** The appeal becomes `DECIDED_AFFIRMED`, the
        determination becomes `FINAL`, and the claim returns from
        `HEARING_PENDING` to `DETERMINED`."
        PRD §3.5: "The claim becomes `CLOSED` — terminal, like `WITHDRAWN` —
        and the employer's `compliance_posture` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/claim_close_requires_determination_final
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_heard_appeal(referee_id="ref-close-1")
        decided = validate_success(
            api.decide_appeal(ctx["appeal"]["id"], "AFFIRM", LIAISON), 200)
        assert decided["status"] == "DECIDED_AFFIRMED"
        assert get_determination(ctx["determination"]["id"])["status"] == "FINAL"
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"

        closed = validate_success(api.close_claim(ctx["claim"]["id"], ANALYST), 200)
        assert closed["status"] == "CLOSED"

    def test_close_from_notice_received_rejected(self, api):
        """PRD §3.5: "A `ClaimsAnalyst` may close a claim only when it is
        `DETERMINED` (otherwise `ERR_CLAIM_NOT_CLOSABLE`)"

        Design: Corner/state_machines/claim_close_from_notice_received_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="InvT")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])

        err = api.close_claim(claim["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_CLOSABLE, 409)
        assert get_claim(claim["id"])["status"] == "NOTICE_RECEIVED"

    def test_withdraw_after_determination_rejected(self, api):
        """PRD §3.3: "An `AgencyLiaison` may withdraw a claim only while it is
        in `NOTICE_RECEIVED` or `RESPONSE_IN_PROGRESS` (otherwise
        `ERR_CLAIM_NOT_WITHDRAWABLE`)"

        Design: Corner/state_machines/claim_withdraw_after_determination_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_determined_claim()

        err = api.withdraw_claim(ctx["claim"]["id"], LIAISON)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE, 409)
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"

    def test_determination_before_adjudication_rejected(self, api):
        """PRD §3.5: "Adjudication concludes its first pass when an
        `AgencyLiaison` records the agency's determination on a claim that is
        `UNDER_ADJUDICATION` (otherwise `ERR_CLAIM_NOT_UNDER_ADJUDICATION`)."

        Design: Corner/errors/error_determination_before_adjudication_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="AdjCo")
        separation = create_separation(employer["id"])
        claim, _resp = submit_complete_response(employer["id"], separation["id"],
                                                response_type="NO_PROTEST")
        assert claim["status"] == "RESPONSE_SUBMITTED"  # no agency ack yet

        err = api.create_determination(
            claim["id"], {"outcome": "ALLOWED", "mailed_at": "2026-08-05T09:00:00Z"},
            LIAISON)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_UNDER_ADJUDICATION, 409)


class TestAppealReverseReserveInvariant:
    def _setup_heard_with_charges(self, api, referee_id):
        """Employer (reserve 30,000,000) -> claim determined ALLOWED ->
        statement + 200,000-cent line (reserve debited) -> appeal heard."""
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_determined_claim(
            employer_kwargs={"legal_name": "Res2Co",
                             "reserve_balance_cents": 30_000_000},
            separation_reason="DISCHARGE_MISCONDUCT", outcome="ALLOWED")
        statement = create_statement(ctx["employer"]["id"],
                                     issued_at="2026-08-06T09:00:00Z")
        line = post_line(statement["id"], ctx["claim"]["id"], 200_000,
                         benefit_weeks=2)
        reserve_mid = get_employer(ctx["employer"]["id"])["reserve_balance_cents"]
        assert reserve_mid == 29_800_000, "reserve debited when the charge posts"

        appeal = appeal_determination(ctx["determination"]["id"])
        hearing = schedule_hearing(appeal["id"], ctx["claim"]["id"],
                                   referee_id=referee_id)
        witness = add_witness(hearing["id"])
        prep_witness_to_ready(hearing["id"], witness["id"])
        validate_success(api.hold_hearing(hearing["id"], LIAISON), 200)
        ctx.update({"statement": get_statement(statement["id"]),
                    "line": line, "appeal": get_appeal(appeal["id"])})
        return ctx

    def test_reverse_restores_reserve_and_reverses_line(self, api):
        """PRD §3.5: "**Reverse.** The appeal becomes `DECIDED_REVERSED` and
        the determination becomes `REVERSED`. When the reversed determination's
        outcome was `ALLOWED`, every charge line on that claim still in
        `PENDING` or `SUSTAINED` automatically transitions to `REVERSED`; each
        such reversal decrements its statement's `total_charged_cents` and the
        claim's `charged_amount_cents` by the line's amount, and the employer's
        `reserve_balance_cents` is credited by the sum of all auto-reversed
        amounts — exactly one credit per reversed line, restoring the
        pre-charge ledger."
        PRD §3.6: "the employer's `reserve_balance_cents` decreases by the
        amount — the reserve is debited when the charge posts."

        Design: Difficulty/compensating_invariant/appeal_reverse_credits_reserve_invariant
        """
        ctx = self._setup_heard_with_charges(api, "ref-rev-1")

        decided = validate_success(
            api.decide_appeal(ctx["appeal"]["id"], "REVERSE", LIAISON), 200)
        assert decided["status"] == "DECIDED_REVERSED"
        assert get_determination(ctx["determination"]["id"])["status"] == "REVERSED"
        line_after = get_line_item(ctx["line"]["id"])
        assert_line_item(line_after)
        assert line_after["status"] == "REVERSED"
        assert get_statement(ctx["statement"]["id"])["total_charged_cents"] == 0
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 0
        # Reserve conserved across the charge-then-reversal cycle.
        assert get_employer(ctx["employer"]["id"])["reserve_balance_cents"] == 30_000_000

    def test_reverse_supersedes_rating_models(self, api):
        """PRD §3.5: "All experience-rating models for the employer move to
        `SUPERSEDED`, because their inputs have been invalidated."

        Design: Difficulty/compensating_invariant/appeal_reverse_credits_reserve_invariant
        """
        ctx = self._setup_heard_with_charges(api, "ref-rev-2")
        # Model created and finalized against the post-charge inputs.
        model = create_model(ctx["employer"]["id"], model_year=2027,
                             variant="RESERVE_RATIO", kind="OFFICIAL")
        finalize_model(ctx["employer"]["id"], model["id"])
        assert get_model(model["id"])["status"] == "FINALIZED"

        validate_success(api.decide_appeal(ctx["appeal"]["id"], "REVERSE", LIAISON), 200)
        assert get_model(model["id"])["status"] == "SUPERSEDED"
        assert get_employer(ctx["employer"]["id"])["reserve_balance_cents"] == 30_000_000
        assert get_claim(ctx["claim"]["id"])["charged_amount_cents"] == 0
