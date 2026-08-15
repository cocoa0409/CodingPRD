"""Distribution information cycle, approve/decline fork, disburse cascade to
annual statements, error precedence pairs, and reserve/release conservation
(PRD §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_beneficiary_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    OPS,
    add_beneficiary,
    cast_votes,
    create_approved_document,
    create_approved_request,
    create_request_in_review,
    create_request_in_voting,
    create_trust,
    get_trust,
    post_adjustment,
    setup_funded_trust,
)


def _hems_ctx(api, income=5000000, principal=10000000, members=5):
    return setup_funded_trust(
        income_cents=income,
        principal_cents=principal,
        committee_size=members,
        all_beneficiaries=[{"full_name": "Ivy Inc", "beneficiary_class": "INCOME",
                            "share_bps": 10000, "date_of_birth": "1955-01-01"}],
        distribution_standard="HEMS",
    )


class TestInformationCycleAndFork:
    def test_information_cycle_runs_twice_then_approves(self, api):
        """PRD §3.3: "Only the requesting beneficiary answers: the transition
        INFORMATION_REQUESTED → UNDER_REVIEW requires `X-User-ID` to equal the
        request's `beneficiary_id` (`ERR_NOT_OWN_RESOURCE`) and carries the
        beneficiary's `info_response_note`. This UNDER_REVIEW →
        INFORMATION_REQUESTED → UNDER_REVIEW loop is unbounded."
        PRD §3.3: "if `approve_count` has reached at least three, the request
        becomes APPROVED — exactly three approvals approves — and the
        reservation remains in place."

        Design: Difficulty/non_linear_state_machine/distribution_request_info_cycle_and_fork
        """
        ctx = _hems_ctx(api)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]
        req = create_request_in_review(trust["id"], ben["id"], amount_cents=3000000,
                                       purpose_category="HEALTH", as_beneficiary=True)
        for note_req, note_resp in (("need invoice", "invoice attached"),
                                    ("need second quote", "second quote attached")):
            assert api.request_information(req["id"], {"info_request_note": note_req},
                                           OFFICER).status_code == 200
            assert api.provide_information(
                req["id"], {"info_response_note": note_resp},
                make_beneficiary_headers(ben["id"]),
            ).status_code == 200

        assert api.open_voting(req["id"], OFFICER).status_code == 200
        cast_votes(req["id"], ids[:3], "APPROVE")
        current = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert current["status"] == "APPROVED"
        assert current["income_portion_cents"] == 3000000
        assert current["principal_portion_cents"] == 0

    def test_sibling_decline_releases_reservation(self, api):
        """PRD §3.3: "otherwise, if `decline_count` has reached at least
        three, the request becomes DECLINED" and "a decline additionally
        releases the reservation — the trust's reserved balances are reduced
        by this request's portions, the available balances recomputed — and
        decrements `pending_distribution_count`."

        Design: Difficulty/non_linear_state_machine/distribution_request_info_cycle_and_fork
        """
        ctx = _hems_ctx(api)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]

        req1 = create_request_in_voting(trust["id"], ben["id"], amount_cents=3000000,
                                        purpose_category="HEALTH", as_beneficiary=True)
        cast_votes(req1["id"], ids[:3], "APPROVE")

        req2 = create_request_in_voting(trust["id"], ben["id"], amount_cents=1000000,
                                        purpose_category="EDUCATION", as_beneficiary=True)
        cast_votes(req2["id"], [ids[0], ids[1], ids[3]], "DECLINE")

        req2_after = validate_success(api.get_distribution_request(req2["id"], OFFICER))
        assert req2_after["status"] == "DECLINED"
        trust_after = get_trust(trust["id"])
        # req1's reservation kept; req2's released on decline
        assert trust_after["reserved_income_cents"] == 3000000
        assert trust_after["available_income_cents"] == 2000000


class TestDisburseStatementCascade:
    def test_disburse_posts_distribution_ledger_row(self, api):
        """PRD §3.3: "First, the ledger is appended: one DISTRIBUTION row in
        the INCOME bucket for the negative of `income_portion_cents` when that
        portion is greater than zero, and one DISTRIBUTION row in the
        PRINCIPAL bucket for the negative of `principal_portion_cents` when
        that is greater than zero, each with `value_date` set to the current
        clock date and `source_entity_type` of DISTRIBUTION_REQUEST pointing
        back at the request via `source_entity_id`."

        Design: Difficulty/transitive_cascade/disburse_to_statement_supersede
        """
        ctx = _hems_ctx(api)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]
        req = create_approved_request(trust["id"], ben["id"], ids, amount_cents=1000000,
                                      purpose_category="HEALTH")
        disbursed = validate_success(api.disburse_request(req["id"], OPS))
        assert disbursed["status"] == "DISBURSED"

        rows, meta = validate_paginated(
            api.list_ledger_entries(OPS, params={"trust_id": trust["id"],
                                                 "entry_kind": "DISTRIBUTION"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == -1000000
        assert rows[0]["bucket"] == "INCOME"

    def test_disburse_recomputes_balances_and_supersedes_statement(self, api):
        """PRD §3.3: "Second, the trust's balances are recomputed from the
        ledger, this request's reservation is released,
        `pending_distribution_count` decrements, and the trust's `version`
        increments. Third, every AnnualStatement of the trust still in DRAFT
        or FINALIZED whose `fiscal_year` contains the disbursement's
        `value_date` is automatically SUPERSEDED, since its totals are now
        stale."

        Design: Difficulty/transitive_cascade/disburse_to_statement_supersede
        """
        ctx = _hems_ctx(api)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]

        resp = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        stmt = get_success_data(resp)
        assert api.finalize_statement(stmt["id"], OFFICER).status_code == 200

        req = create_approved_request(trust["id"], ben["id"], ids, amount_cents=1000000,
                                      purpose_category="HEALTH")
        assert api.disburse_request(req["id"], OPS).status_code == 200

        trust_after = get_trust(trust["id"])
        assert trust_after["income_balance_cents"] == 4000000
        assert trust_after["reserved_income_cents"] == 0
        assert trust_after["available_income_cents"] == 4000000

        stmt_after = validate_success(api.get_annual_statement(stmt["id"], OFFICER))
        assert stmt_after["status"] == "SUPERSEDED"


class TestErrorPrecedenceStateBeatsFiscal:
    def _declined_then_underfunded(self, api):
        """Request DECLINED 3-0, then available income cut below the released
        portions by an ADJUSTMENT."""
        ctx = _hems_ctx(api, members=3)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        ids = [m["id"] for m in ctx["members"]]
        req = create_request_in_voting(trust["id"], ben["id"], amount_cents=4500000,
                                       purpose_category="HEALTH")
        cast_votes(req["id"], ids[:3], "DECLINE")
        post_adjustment(trust["id"], "INCOME", -2000000, value_date="2026-08-20",
                        description="correction of misposted interest")
        return trust, req

    def test_state_error_wins_over_fiscal_error(self, api):
        """PRD §2.8: "6. **State validity** — the target entity is in a valid
        from-state for the requested transition, including terminal-state
        lockdown (`ERR_INVALID_STATE`)" and "11. **Funds checks last** —
        reservation waterfalls, termination reserves, and fee portions are
        validated against available balances only after every check above has
        passed (`ERR_INSUFFICIENT_AVAILABLE_BALANCE`,
        `ERR_FEE_EXCEEDS_AVAILABLE_BALANCE`)."
        PRD §2.8: "The practical consequence is that a request failing, say,
        both authentication and a funds check always surfaces
        `ERR_UNAUTHENTICATED`, and a stale version always surfaces before an
        insufficient-balance rejection."
        PRD §3.3: "Disbursement by a `TrustOperationsOfficer` requires the
        request to be APPROVED (`ERR_REQUEST_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
        """
        trust, req = self._declined_then_underfunded(api)
        resp = api.disburse_request(req["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_APPROVED)

    def test_failed_disburse_posts_nothing_and_keeps_balance(self, api):
        """PRD §3.3: "Only an APPROVED request can be paid out. Disbursement
        by a `TrustOperationsOfficer` requires the request to be APPROVED
        (`ERR_REQUEST_NOT_APPROVED`) and the trust ACTIVE
        (`ERR_TRUST_NOT_ACTIVE`)."
        PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
        """
        trust, req = self._declined_then_underfunded(api)
        api.disburse_request(req["id"], OPS)
        trust_after = get_trust(trust["id"])
        assert trust_after["income_balance_cents"] == 3000000
        _, meta = validate_paginated(
            api.list_ledger_entries(OPS, params={"trust_id": trust["id"],
                                                 "entry_kind": "DISTRIBUTION"})
        )
        assert meta["total_count"] == 0


class TestErrorPrecedenceSafetyBeatsReferential:
    def _two_hems_trusts(self, api):
        ta = create_trust(trust_name="Safety Trust A", distribution_standard="HEMS")
        create_approved_document(ta["id"])
        ben_a = add_beneficiary(ta["id"], full_name="Ivy A",
                                beneficiary_class="INCOME", share_bps=10000,
                                date_of_birth="1955-01-01")
        assert api.submit_for_acceptance(ta["id"], OFFICER).status_code == 200
        assert api.accept_trust(ta["id"], EXEC).status_code == 200
        tb = create_trust(trust_name="Safety Trust B", distribution_standard="HEMS")
        create_approved_document(tb["id"])
        assert api.submit_for_acceptance(tb["id"], OFFICER).status_code == 200
        assert api.accept_trust(tb["id"], EXEC).status_code == 200
        return ta, ben_a, tb

    # NOTE: the priority pair "purpose gate (§2.8.7) beats cross-trust
    # reference (§2.8.9)" cannot be exercised at request-create time per the
    # PRD: §3.3 assigns the purpose-standard check to open-voting ("Opening
    # the vote is the fiduciary hinge, and its preconditions are evaluated in
    # the order given here"), while the create paragraph enumerates only
    # ERR_NOT_OWN_RESOURCE / ERR_CROSS_TRUST_REFERENCE / ERR_TRUST_NOT_ACTIVE
    # / ERR_STALE_VERSION. A PRD-faithful create therefore surfaces
    # ERR_CROSS_TRUST_REFERENCE whenever the beneficiary is foreign, so no
    # create-time purpose-vs-reference race exists to assert.

    def test_referential_error_fires_when_purpose_is_valid(self, api):
        """PRD §2.8: "7. **Fiduciary and compliance gates** — the purpose
        standard permits the requested `purpose_category`
        (`ERR_PURPOSE_OUTSIDE_STANDARD`)" precedes "9. **Cross-entity
        references** — body references belong to the same trust
        (`ERR_CROSS_TRUST_REFERENCE`), the beneficiary is ACTIVE
        (`ERR_BENEFICIARY_NOT_ACTIVE`), and acceptance requires an APPROVED
        instrument (`ERR_DOCUMENT_NOT_APPROVED`)."
        PRD §3.3: "The `purpose_category` must be permitted by the trust's
        `distribution_standard`: HEMS permits HEALTH, EDUCATION, MAINTENANCE,
        and SUPPORT; SUPPORT permits HEALTH, MAINTENANCE, and SUPPORT;
        DISCRETIONARY permits every category; any other pairing is rejected
        with `ERR_PURPOSE_OUTSIDE_STANDARD`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_request_create
        """
        _, ben_a, tb = self._two_hems_trusts(api)
        resp = api.create_distribution_request(
            {
                "trust_id": tb["id"],
                "beneficiary_id": ben_a["id"],
                "amount_cents": 100000,
                "allocation_source": "INCOME_ONLY",
                "purpose_category": "HEALTH",
                "expected_trust_account_version": get_trust(tb["id"])["version"],
            },
            OFFICER,
        )
        # Purpose HEALTH is permitted by HEMS, so the safety gate passes and
        # the cross-trust reference is the surfaced rejection.
        validate_error(resp, ApiErrorId.ERR_CROSS_TRUST_REFERENCE)

    def test_cross_trust_reference_with_valid_purpose(self, api):
        """PRD §3.3: "The beneficiary named must belong to the same trust as
        the request; a cross-trust reference is rejected with
        `ERR_CROSS_TRUST_REFERENCE`."

        Design: Corner/errors/cross_trust_reference_rejected_with_valid_purpose
        """
        ta = create_trust(trust_name="Ref A", distribution_standard="DISCRETIONARY")
        create_approved_document(ta["id"])
        ben_a = add_beneficiary(ta["id"], full_name="Ivy A",
                                beneficiary_class="INCOME", share_bps=10000,
                                date_of_birth="1955-01-01")
        assert api.submit_for_acceptance(ta["id"], OFFICER).status_code == 200
        assert api.accept_trust(ta["id"], EXEC).status_code == 200
        tb = create_trust(trust_name="Ref B", trust_type="REVOCABLE",
                          distribution_standard="DISCRETIONARY")
        create_approved_document(tb["id"])
        assert api.submit_for_acceptance(tb["id"], OFFICER).status_code == 200
        assert api.accept_trust(tb["id"], EXEC).status_code == 200

        resp = api.create_distribution_request(
            {
                "trust_id": tb["id"],
                "beneficiary_id": ben_a["id"],
                "amount_cents": 100000,
                "allocation_source": "INCOME_ONLY",
                "purpose_category": "OTHER",
                "expected_trust_account_version": get_trust(tb["id"])["version"],
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_TRUST_REFERENCE)


class TestReserveReleaseConservation:
    def test_open_voting_applies_exact_reservation(self, api):
        """PRD §3.3: "A successful opening sets `income_portion_cents` and
        `principal_portion_cents` per the waterfall, adds them to the trust's
        `reserved_income_cents` and `reserved_principal_cents`, recomputes the
        available balances, increments the trust's `version`."
        PRD §2.6: "`available_income_cents` and `available_principal_cents`
        are each the corresponding balance minus the corresponding
        reservation."

        Design: Difficulty/compensating_invariant/reserve_release_conserves_cents
        """
        ctx = _hems_ctx(api, members=3)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(trust["id"], ben["id"], amount_cents=3000000,
                                       allocation_source="INCOME_FIRST",
                                       purpose_category="EDUCATION")
        assert api.open_voting(req["id"], OFFICER).status_code == 200
        mid = get_trust(trust["id"])
        assert mid["reserved_income_cents"] == 3000000
        assert mid["income_balance_cents"] == 5000000
        assert mid["available_income_cents"] == 2000000

    def test_cancel_releases_exactly_and_ledger_stays_untouched(self, api):
        """PRD §3.3: "An officer's cancellation, carrying a
        `cancelled_reason`, moves any non-terminal state — SUBMITTED,
        UNDER_REVIEW, INFORMATION_REQUESTED, VOTING, or APPROVED — to
        CANCELLED, releasing the reservation if one exists (as described
        below), decrementing `pending_distribution_count`, and incrementing
        the trust's `version`."
        PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket."

        Design: Difficulty/compensating_invariant/reserve_release_conserves_cents
        """
        ctx = _hems_ctx(api, members=3)
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(trust["id"], ben["id"], amount_cents=3000000,
                                       allocation_source="INCOME_FIRST",
                                       purpose_category="EDUCATION")
        assert api.open_voting(req["id"], OFFICER).status_code == 200
        assert api.cancel_request(req["id"], {"cancelled_reason": "beneficiary request"},
                                  OFFICER).status_code == 200

        end = get_trust(trust["id"])
        assert end["reserved_income_cents"] == 0
        assert end["available_income_cents"] == 5000000
        assert end["income_balance_cents"] == 5000000, (
            "reserve/release never touches the ledger"
        )
        rows, _ = validate_paginated(
            api.list_ledger_entries(OPS, params={"trust_id": trust["id"], "bucket": "INCOME"})
        )
        assert sum(r["amount_cents"] for r in rows) == 5000000
