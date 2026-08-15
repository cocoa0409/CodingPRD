"""Service substitutions (OCC, supersede chains, eligibility) and appeals
(windows, terminal lockdown, the grant recommit cascade) (PRD §2.7, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    appeal_begin_review,
    appeal_decide,
    approve_substitution,
    budget_summary,
    begin_review,
    certify_request,
    create_service_substitution_payload,
    decide_request,
    get_line,
    get_request,
    get_substitution,
    make_appeal_officer_headers,
    new_appeal,
    new_cycle,
    new_line,
    new_request,
    new_service,
    new_substitution,
    set_clock,
    setup_certified_contract,
    setup_committed_scenario,
    validate_error,
)


def _committed_c2_with_spare_service():
    """Committed C2 line (2,000,000 pre-discount) on 'Wireless Access Points',
    with 'Ethernet Switches' also in the same cycle inventory."""
    return setup_committed_scenario(
        category="CATEGORY_TWO", bid_price=2000000, contract_total=2000000,
        line_amounts=(2000000,),
        extra_services=[("Ethernet Switches", "CATEGORY_TWO", "INTERNAL_CONNECTIONS")],
    )


class TestSubstitutionSupersedeChain:
    def test_substitution_supersede_chain(self, api):
        """PRD §3.7: "At creation, the substitution snapshots the line's current
        `eligible_service_id` into its own `from_eligible_service_id`, starts in
        `REQUESTED` status".
        PRD §3.7: "Approval moves the substitution from `REQUESTED` to `APPROVED`
        and rewrites the line: its `eligible_service_id` becomes the
        substitution's `to_eligible_service_id`, while all committed amounts on
        the line stay unchanged. If the substitution named a predecessor in
        `supersedes_substitution_id`, that predecessor flips from `APPROVED` to
        `SUPERSEDED` in the same request."

        Design: Corner/endpoints/substitution_supersede_chain
        """
        ctx = _committed_c2_with_spare_service()
        es_c2, es_c2b = ctx["services"]["primary"], ctx["services"]["extra"][0]
        line = get_line(ctx["lines"][0]["id"])

        # S1: APs -> Switches.
        s1 = new_substitution(ctx, line, es_c2b, line["version"],
                              reason="APs discontinued by manufacturer")
        assert s1["status"] == "REQUESTED"
        assert s1["from_eligible_service_id"] == es_c2["id"], (
            "from-service must be snapshotted from the line at creation"
        )

        s1 = approve_substitution(s1)
        assert s1["status"] == "APPROVED"
        line = get_line(line["id"])
        assert line["eligible_service_id"] == es_c2b["id"], (
            "approval must rewrite the line's eligible service"
        )
        assert line["committed_pre_discount_cents"] == 2000000, (
            "committed amounts stay unchanged across the rewrite"
        )

        # S2: Switches -> APs, superseding S1.
        s2 = new_substitution(ctx, line, es_c2, line["version"],
                              supersedes_substitution_id=s1["id"],
                              reason="Equivalent AP model re-certified eligible")
        approve_substitution(s2)
        assert get_substitution(s1["id"])["status"] == "SUPERSEDED"
        assert get_line(line["id"])["eligible_service_id"] == es_c2["id"]

    def test_occ_substitution_supersede_stale_line_version(self, api):
        """PRD §2.7: "A `POST /erate/service-substitutions` request must carry
        `expected_line_version`, holding the coordinator's last-observed `version`
        of the funding request line. If the line's current `version` has advanced
        — for instance because a prior substitution on the same line was just
        approved, rewriting the line's eligible service and bumping its `version`
        — the new substitution's from-service premise is stale and the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_substitution_supersede_stale_line_version
        """
        ctx = _committed_c2_with_spare_service()
        es_c2, es_c2b = ctx["services"]["primary"], ctx["services"]["extra"][0]
        line = get_line(ctx["lines"][0]["id"])
        stale_version = line["version"]

        s1 = new_substitution(ctx, line, es_c2b, stale_version,
                              reason="APs discontinued")
        approve_substitution(s1)  # create + approval each advanced the line version
        current_version = get_line(line["id"])["version"]
        assert current_version > stale_version

        # A create predicated on the pre-approval line version is stale.
        resp = api.create_service_substitution(
            create_service_substitution_payload(
                frn_line_id=line["id"], to_eligible_service_id=es_c2["id"],
                expected_line_version=stale_version,
                supersedes_substitution_id=s1["id"],
                reason="Stale attempt predicated on pre-approval line"),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # The same create against the observed current version succeeds.
        s2 = new_substitution(ctx, get_line(line["id"]), es_c2, current_version,
                              supersedes_substitution_id=s1["id"],
                              reason="Fresh attempt on current line version")
        assert s2["status"] == "REQUESTED"

    def test_substitution_target_ineligible_or_wrong_category_rejected(self, api):
        """PRD §3.7: "The target service must sit in the same funding cycle's
        eligible services inventory (otherwise `ERR_SERVICE_NOT_ELIGIBLE`) and
        must carry the same category as the service being replaced (otherwise
        `ERR_SUBSTITUTION_CATEGORY_MISMATCH`)."

        Design: Corner/validations/substitution_target_ineligible_or_wrong_category_rejected
        """
        old_cycle = new_cycle(label="FY2026", window_open_date="2025-10-01",
                              window_close_date="2026-03-31",
                              service_delivery_deadline="2026-06-30")
        es_old = new_service(old_cycle["id"], "Legacy Switches (FY2026)",
                             "CATEGORY_TWO", "INTERNAL_CONNECTIONS")
        ctx = setup_committed_scenario(
            category="CATEGORY_TWO", bid_price=2000000, contract_total=2000000,
            line_amounts=(2000000,),
            extra_services=[("Dedicated Internet Access 1Gbps",
                             "CATEGORY_ONE", "INTERNET_ACCESS")],
        )
        es_c1 = ctx["services"]["extra"][0]
        line = get_line(ctx["lines"][0]["id"])  # CATEGORY_TWO line

        # Wrong-category target (CATEGORY_ONE service on a CATEGORY_TWO line).
        resp = api.create_service_substitution(
            create_service_substitution_payload(
                frn_line_id=line["id"], to_eligible_service_id=es_c1["id"],
                expected_line_version=line["version"],
                reason="Wrong category target"),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_CATEGORY_MISMATCH)

        # Wrong-cycle target (FY2026 inventory entry; category matches).
        resp = api.create_service_substitution(
            create_service_substitution_payload(
                frn_line_id=line["id"], to_eligible_service_id=es_old["id"],
                expected_line_version=line["version"],
                reason="Wrong cycle target"),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_ELIGIBLE)


def _denied_c2_request():
    """C2 request with a single 8,000,000 line, DENIED with decision_date
    2027-04-15; no budget consumed."""
    return setup_committed_scenario(
        category="CATEGORY_TWO", bid_price=8000000, contract_total=8000000,
        line_amounts=(8000000,), outcome="DENIED",
        decide_clock="2027-04-15T00:00:00Z",
    )


class TestAppealGrantRecommitCascade:
    """Queue A: transitive_cascade/appeal_grant_recommit_cascade."""

    def test_grant_flips_request_and_recommits_lines(self, api):
        """PRD §3.8: "A grant is where the cascade fires, in three links within
        the same atomic request. First, the funding request flips from `DENIED`
        back to `COMMITTED`, its `version` incrementing. Second, each of the
        request's `DENIED` lines re-runs the commitment machinery of §3.5 against
        the budget as it stands now: the request's Category Two lines are walked
        again in `created_at` ascending order, each line's allocation recomputed
        as the smaller of its `requested_pre_discount_cents` and the currently
        remaining budget, with the remainder decrementing before the next line's
        turn. A line whose recomputed allocation exceeds zero moves back to
        `COMMITTED` with its commitment fields — `committed_pre_discount_cents`,
        `committed_share_cents`, `remaining_reimbursable_cents`,
        `invoice_deadline_date` — recomputed against the current budget".

        Design: Difficulty/transitive_cascade/appeal_grant_recommit_cascade
        """
        ctx = _denied_c2_request()
        assert ctx["request"]["status"] == "DENIED"
        assert get_line(ctx["lines"][0]["id"])["status"] == "DENIED"

        set_clock("2027-04-20T00:00:00Z")
        appeal = appeal_begin_review(
            new_appeal(ctx, ctx["request"], "Documentation was on file")
        )
        granted = appeal_decide(appeal, "GRANTED", rationale="Record substantiated")
        assert granted["status"] == "GRANTED"

        request = get_request(ctx["request"]["id"])
        assert request["status"] == "COMMITTED", (
            "LINK1: the grant must reverse DENIED back to COMMITTED"
        )
        line = get_line(ctx["lines"][0]["id"])
        assert line["status"] == "COMMITTED"
        # Recommitted against full availability: min(8,000,000, 16,700,000).
        assert line["committed_pre_discount_cents"] == 8000000
        assert line["committed_share_cents"] == 4000000  # 50% pinned rate
        assert line["remaining_reimbursable_cents"] == 4000000

    def test_grant_recomputes_budget_ledger_and_request_total(self, api):
        """PRD §3.8: "Third, the applicant's Category Two committed ledger
        increases by each recommitted line's `committed_pre_discount_cents`, and
        the request's `committed_total_share_cents` is recomputed as the sum of
        the per-line committed shares. A denial of the appeal, by contrast,
        changes nothing on the funding request — the request remains `DENIED`."

        Design: Difficulty/transitive_cascade/appeal_grant_recommit_cascade
        """
        ctx = _denied_c2_request()
        summary = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert summary["c2_committed_cents"] == 0, "DENIED lines never consume budget"

        set_clock("2027-04-20T00:00:00Z")
        appeal = appeal_begin_review(
            new_appeal(ctx, ctx["request"], "Documentation was on file")
        )
        appeal_decide(appeal, "GRANTED", rationale="Record substantiated")

        summary = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert summary["c2_committed_cents"] == 8000000, (
            "LINK3: the ledger increases by the recommitted pre-discount amount"
        )
        assert summary["c2_available_cents"] == 8700000
        assert summary["c2_cap_cents"] == 16700000
        request = get_request(ctx["request"]["id"])
        assert request["committed_total_share_cents"] == 4000000


class TestAppealLifecycle:
    def test_appeal_terminal_lockdown(self, api):
        """PRD §3.8: "Both outcomes set `outcome_date` to the clock's date, create
        an `APPEAL_DECISION` retained document, and increment the appeal's
        `version`; `GRANTED` and `DENIED` are both terminal for the appeal."
        PRD §2.10: "**State gates** — the target resource must be in a from-state
        of the invoked transition, or satisfy the state gate of a state-gated
        create" and "Violations yield `ERR_INVALID_STATE_TRANSITION`, or the more
        specific `ERR_CONTRACT_NOT_CERTIFIED`, `ERR_LINE_NOT_COMMITTED`, or
        `ERR_SERVICES_NOT_STARTED` where those named gates apply."

        Design: Corner/state_machines/appeal_terminal_lockdown
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), outcome="DENIED",
                                       decide_clock="2027-04-15T00:00:00Z")
        set_clock("2027-05-10T00:00:00Z")
        appeal = appeal_begin_review(
            new_appeal(ctx, ctx["request"], "Procedural error")
        )
        denied = appeal_decide(appeal, "DENIED")
        assert denied["status"] == "DENIED"

        resp = api.decide_appeal(
            appeal["id"], {"outcome": "GRANTED"},
            make_appeal_officer_headers("usac-app-3"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_request(ctx["request"]["id"])["status"] == "DENIED", (
            "the failed re-decision must leave the funding request untouched"
        )

    def test_second_appeal_while_active_rejected(self, api):
        """PRD §3.8: "only one appeal per request may be non-terminal at a time:
        if an appeal in `FILED` or `UNDER_REVIEW` already exists for the request,
        the filing is rejected with `ERR_APPEAL_ALREADY_ACTIVE`."

        Design: Corner/validations/second_appeal_while_active_rejected
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), outcome="DENIED",
                                       decide_clock="2027-04-15T00:00:00Z")
        set_clock("2027-04-20T00:00:00Z")
        first = new_appeal(ctx, ctx["request"], "First appeal")
        assert first["status"] == "FILED"

        resp = api.create_appeal(
            {"funding_request_id": ctx["request"]["id"],
             "grounds": "Second appeal while first active"},
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_ACTIVE)

    def test_appeal_window_day60_allowed_day61_rejected(self, api):
        """PRD §3.8: "The filing date, stored as `filed_date`, is taken from the
        logical clock and must fall within the closed window from the request's
        `decision_date` through 60 days after it; filing on day 60 itself is
        allowed, while day 61 or later is `ERR_APPEAL_WINDOW_PASSED`."
        PRD §2.4: "The **appeal window** is the closed interval from a request's
        `decision_date` through 60 days after it. Filing on day 60 is allowed;
        filing on day 61 or later is `ERR_APPEAL_WINDOW_PASSED`."

        Design: Corner/cross_cutting_complexity_layers/appeal_window_day60_allowed_day61_rejected
        """
        ctx = setup_certified_contract()  # C1 contract, capacity 50000
        # Two requests, one 25000 line each, both DENIED on 2027-04-15.
        set_clock("2026-10-15T00:00:00Z")
        r1 = new_request(ctx)
        new_line(ctx, r1, ctx["contract"], ctx["services"]["primary"], 25000)
        r1 = certify_request(ctx, r1)
        begin_review(ctx, r1)
        r2 = new_request(ctx)
        new_line(ctx, r2, ctx["contract"], ctx["services"]["primary"], 25000)
        r2 = certify_request(ctx, r2)
        begin_review(ctx, r2)
        set_clock("2027-04-15T00:00:00Z")
        decide_request(ctx, r1, outcome="DENIED")
        decide_request(ctx, r2, outcome="DENIED")

        # decision_date 2027-04-15: day 60 = 2027-06-14, day 61 = 2027-06-15.
        set_clock("2027-06-14T00:00:00Z")
        ap1 = new_appeal(ctx, r1, "Day-60 filing")
        assert ap1["status"] == "FILED"
        assert ap1["filed_date"] == "2027-06-14", (
            "filing on day 60 of the closed window must be allowed"
        )

        set_clock("2027-06-15T00:00:00Z")
        resp = api.create_appeal(
            {"funding_request_id": r2["id"], "grounds": "Day-61 filing"},
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_PASSED)
