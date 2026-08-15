"""Contract termination cascades, C2 budget conservation, document retention
and purge geometry, and header/ownership access gates (PRD §2.1, §2.4, §2.9,
§3.2, §3.4, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_c2_budget_invariants,
    begin_review,
    budget_summary,
    decide_request,
    get_line,
    get_request,
    list_documents,
    make_auditor_headers,
    new_applicant,
    new_applicant_user_with_headers,
    new_cycle,
    place_hold,
    set_clock,
    setup_certified_contract,
    setup_committed_scenario,
    setup_request_with_lines,
    terminate_contract,
    validate_error,
    validate_success,
)


def _committed_single_c2_line():
    """COMMITTED request with exactly one C2 line (2,000,000 pre-discount,
    share 1,000,000); C2 budget committed stands at 2,000,000."""
    return setup_committed_scenario(
        category="CATEGORY_TWO", bid_price=2000000, contract_total=2000000,
        line_amounts=(2000000,),
    )


class TestContractTerminationCascade:
    """Queue A: transitive_cascade/contract_termination_cascade."""

    def test_termination_cancels_lines_and_zeroes_remaining(self, api):
        """PRD §3.4: "First, every funding request line whose `contract_id` is
        this contract and whose status is `PENDING` or `COMMITTED` moves to
        `CANCELLED` with `denial_reason` `CONTRACT_TERMINATED`; on a cancelled
        `COMMITTED` line, `remaining_reimbursable_cents` is forced to 0 while
        `reimbursed_cents` is preserved as historical record."

        Design: Difficulty/transitive_cascade/contract_termination_cascade
        """
        ctx = _committed_single_c2_line()
        line = get_line(ctx["lines"][0]["id"])
        assert line["status"] == "COMMITTED"
        assert line["remaining_reimbursable_cents"] == 1000000

        terminated = terminate_contract(ctx, ctx["contract"],
                                        reason="Vendor exited the market")
        assert terminated["status"] == "TERMINATED"

        line = get_line(line["id"])
        assert line["status"] == "CANCELLED", f"got {line['status']}"
        assert line["denial_reason"] == "CONTRACT_TERMINATED"
        assert line["remaining_reimbursable_cents"] == 0
        assert line["reimbursed_cents"] == 0, "historical (zero) ledger preserved"

    def test_termination_releases_budget_and_closes_empty_request(self, api):
        """PRD §3.4: "Second, for each cancelled `CATEGORY_TWO` line, the
        applicant's Category Two committed ledger is released by that line's
        `committed_pre_discount_cents`, and every affected funding request's
        `committed_total_share_cents` is recomputed over its remaining
        `COMMITTED` lines. Third, any `COMMITTED` funding request left with zero
        `COMMITTED` lines moves to `CLOSED`."

        Design: Difficulty/transitive_cascade/contract_termination_cascade
        """
        ctx = _committed_single_c2_line()
        before = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert before["c2_committed_cents"] == 2000000

        terminate_contract(ctx, ctx["contract"], reason="Vendor exited the market")

        after = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert after["c2_committed_cents"] == 0, (
            "LINK2: the cancelled line's 2,000,000 must be released"
        )
        assert after["c2_available_cents"] == 16700000
        assert_c2_budget_invariants(after)

        request = get_request(ctx["request"]["id"])
        assert request["status"] == "CLOSED", (
            f"LINK3: zero remaining COMMITTED lines must close the request, "
            f"got {request['status']}"
        )
        assert request["committed_total_share_cents"] == 0


class TestC2BudgetConservation:
    """Queue A: compensating_invariant/c2_budget_conserved_across_commit_and_terminate."""

    def test_forward_commit_conserves_pool(self, api):
        """PRD §3.2: "The **committed** side of the pool is the sum of
        `committed_pre_discount_cents` over the applicant's `CATEGORY_TWO`
        funding lines currently in `COMMITTED` status — `PENDING` and `DENIED`
        lines never consume budget, and `CANCELLED` lines have released whatever
        they held. The **available** budget is the cap minus the committed
        amount, and the server maintains the invariant that the cap always equals
        committed plus available."

        Design: Difficulty/compensating_invariant/c2_budget_conserved_across_commit_and_terminate
        """
        ctx = setup_certified_contract(category="CATEGORY_TWO", bid_price=4000000,
                                       contract_total=4000000)
        setup_request_with_lines(ctx, line_amounts=(4000000,))
        begin_review(ctx, ctx["request"])

        before = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert before["c2_cap_cents"] == 16700000
        assert before["c2_committed_cents"] == 0, "PENDING lines never consume budget"
        assert before["c2_available_cents"] == 16700000
        assert_c2_budget_invariants(before)

        decide_request(ctx, ctx["request"], outcome="COMMITTED")
        after = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert after["c2_cap_cents"] == 16700000
        assert after["c2_committed_cents"] == 4000000
        assert after["c2_available_cents"] == 12700000
        assert_c2_budget_invariants(after)

    def test_compensating_termination_restores_pool_exactly(self, api):
        """PRD §3.2: "the server maintains the invariant that the cap always
        equals committed plus available."
        PRD §3.4: "for each cancelled `CATEGORY_TWO` line, the applicant's
        Category Two committed ledger is released by that line's
        `committed_pre_discount_cents`".

        Design: Difficulty/compensating_invariant/c2_budget_conserved_across_commit_and_terminate
        """
        ctx = setup_committed_scenario(category="CATEGORY_TWO", bid_price=4000000,
                                       contract_total=4000000,
                                       line_amounts=(4000000,))
        mid = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert mid["c2_committed_cents"] == 4000000
        assert mid["c2_available_cents"] == 12700000

        terminate_contract(ctx, ctx["contract"], reason="Vendor default")
        after = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert after["c2_cap_cents"] == 16700000
        assert after["c2_committed_cents"] == 0, (
            "the compensating termination must restore the pool exactly"
        )
        assert after["c2_available_cents"] == 16700000
        assert_c2_budget_invariants(after)


def _commitment_document():
    """A committed request (decision on 2027-04-15) yields retained documents
    anchored to the cycle's retention horizon."""
    ctx = setup_committed_scenario(line_amounts=(50000,),
                                   decide_clock="2027-04-15T00:00:00Z")
    docs = list_documents({"subject_type": "FUNDING_REQUEST",
                           "subject_id": ctx["request"]["id"]})
    assert docs, "Setup failed: certification/decision must create retained documents"
    assert any(d["document_kind"] == "COMMITMENT_DECISION" for d in docs)
    return ctx, docs[0]


class TestRetentionAndPurge:
    """Queue A: resource_temporal_overlap/retention_purge_half_open_hold."""

    def test_purge_inside_hold_blocked_allowed_at_hold_end(self, api):
        """PRD §3.9: "When the document is under a hold, the clock's date must
        additionally not fall inside the hold's half-open interval; a purge
        attempted on a covered date fails with `ERR_AUDIT_HOLD_ACTIVE`, while a
        purge on `hold_end_date` itself is allowed because the interval excludes
        its end."
        PRD §2.4: "The **retention horizon** of a document is its
        `retained_until_date`, computed as the cycle's `service_delivery_deadline`
        plus ten years, keeping the same month and day in a leap-safe manner."

        Design: Difficulty/resource_temporal_overlap/retention_purge_half_open_hold
        """
        _, doc = _commitment_document()
        # 2027-06-30 + 10 years, same month-day.
        assert doc["retained_until_date"] == "2037-06-30", (
            f"retained_until_date must be 2037-06-30, got {doc['retained_until_date']}"
        )

        set_clock("2037-07-01T00:00:00Z")  # retention lapsed...
        place_hold(doc, "2037-06-01", "2037-08-01")  # ...but clock inside the hold
        resp = api.purge_document(doc["id"], make_auditor_headers("usac-aud-1"))
        validate_error(resp, ApiErrorId.ERR_AUDIT_HOLD_ACTIVE)

        set_clock("2037-08-01T00:00:00Z")  # hold_end_date itself: exclusive end
        purged = validate_success(
            api.purge_document(doc["id"], make_auditor_headers("usac-aud-1")), 200
        )
        assert purged["status"] == "PURGED"

    def test_purge_requires_clock_strictly_past_retention(self, api):
        """PRD §3.9: "From either `RETAINED` or `HELD`, an `Auditor` may purge a
        document only when the clock's date is strictly greater than
        `retained_until_date` — purging on the retention date itself is forbidden
        and draws `ERR_DOCUMENT_NOT_PURGEABLE`."
        PRD §2.4: "Purging requires the clock's date to be strictly greater than
        `retained_until_date` — purging on that date itself is forbidden
        (`ERR_DOCUMENT_NOT_PURGEABLE`)."

        Design: Difficulty/resource_temporal_overlap/retention_purge_half_open_hold
        """
        _, doc = _commitment_document()
        assert doc["retained_until_date"] == "2037-06-30"

        set_clock("2037-06-30T00:00:00Z")  # ON the retention date: not purgeable
        resp = api.purge_document(doc["id"], make_auditor_headers("usac-aud-1"))
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_PURGEABLE)

        set_clock("2037-07-01T00:00:00Z")  # strictly past: purgeable
        purged = validate_success(
            api.purge_document(doc["id"], make_auditor_headers("usac-aud-1")), 200
        )
        assert purged["status"] == "PURGED"


class TestAccessGates:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, naming their operational
        capacity." PRD §2.1: "A request that omits either header, or presents a
        malformed one, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_applicant(
            {"name": "No Auth USD", "entity_type": "SCHOOL", "urban_rural": "URBAN",
             "student_count": 100},
            headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_coordinator_of_other_applicant_denied(self, api):
        """PRD §2.1: "When `X-User-Role` is `ApplicantCoordinator` or
        `ApplicantCertifier`, `X-User-ID` is the `id` of the acting
        `ApplicantUser`; ownership checks on any resource that traces back to an
        applicant — a posting, contract, funding request, funding request line,
        invoice, or appeal — compare that user's `applicant_id` against the
        resource's applicant chain, and a mismatch is rejected with
        `ERR_APPLICANT_ACCESS_DENIED` (HTTP 403)."

        Design: Corner/rbac/coordinator_of_other_applicant_denied
        """
        cycle = new_cycle()
        app_a = new_applicant(name="District A", entity_type="SCHOOL",
                              urban_rural="URBAN", student_count=1000)
        app_b = new_applicant(name="District B", entity_type="SCHOOL",
                              urban_rural="RURAL", student_count=500)
        _, coord_b = new_applicant_user_with_headers(app_b["id"], "Coord B",
                                                     "COORDINATOR")
        resp = api.create_procurement_posting(
            {"applicant_id": app_a["id"], "funding_cycle_id": cycle["id"],
             "category": "CATEGORY_ONE", "description": "Intruder posting",
             "price_weight_pct": 100, "other_factor_weights": []},
            coord_b,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICANT_ACCESS_DENIED)
