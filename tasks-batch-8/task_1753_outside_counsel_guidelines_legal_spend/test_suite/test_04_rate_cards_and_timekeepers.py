"""Rate-card lifecycle, annual increase caps, and timekeeper qualification (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_rate_row,
    approve_rate_card,
    assert_rate_card,
    create_approved_rate_card,
    create_draft_rate_card,
    create_rate_card_payload,
    firm_headers,
    get_firm,
    get_line_item,
    list_line_items,
    ops_headers,
    qualify_timekeeper,
    rate_not_on_card_line,
    register_and_qualify_timekeeper,
    register_timekeeper,
    setup_billing_ready,
    setup_department_with_firm,
    submit_invoice,
    submit_rate_card,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRateCardRevisionLoop:
    """DRAFT → SUBMITTED → REJECTED → DRAFT → SUBMITTED is a functional cycle."""

    def _rejected_card(self, api):
        dept, firm = setup_department_with_firm()
        tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
        card = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card["id"], tk["id"], 100_000)
        submit_rate_card(dept["id"], firm["id"], card["id"])
        rejected = validate_success(
            api.reject_rate_card(dept["id"], firm["id"], card["id"], ops_headers())
        )
        assert rejected["status"] == "REJECTED"
        return dept, firm, card

    def test_revise_returns_card_to_draft(self, api):
        """PRD §3.4: "Rejection sends a card `SUBMITTED → REJECTED`, and the firm may loop a rejected card back `REJECTED → DRAFT` through revision — the acting user's firm must own the card (`ERR_FIRM_MISMATCH`) — edit its rows, and submit again."

        Design: Difficulty/non_linear_state_machine/rate_card_revision_loop
        """
        dept, firm, card = self._rejected_card(api)
        revised = validate_success(
            api.revise_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"]))
        )
        assert_rate_card(revised)
        assert revised["status"] == "DRAFT", (
            f"revise must return the card to DRAFT, got {revised['status']}"
        )

    def test_revised_card_can_be_resubmitted(self, api):
        """PRD §3.4: "Rejection sends a card `SUBMITTED → REJECTED`, and the firm may loop a rejected card back `REJECTED → DRAFT` through revision — the acting user's firm must own the card (`ERR_FIRM_MISMATCH`) — edit its rows, and submit again."

        Design: Difficulty/non_linear_state_machine/rate_card_revision_loop
        """
        dept, firm, card = self._rejected_card(api)
        validate_success(api.revise_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"])))
        resubmitted = validate_success(
            api.submit_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"]))
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"a revised card must be submittable again, got {resubmitted['status']}"
        )
        assert resubmitted["submitted_at"] is not None


class TestRateCardYearUniqueness:
    """Effective-year is a point-uniqueness constraint on SUBMITTED/APPROVED cards."""

    def test_same_year_second_submit_conflicts(self, api):
        """PRD §3.4: "Submission (`DRAFT → SUBMITTED`) stamps `submitted_at` with the logical clock, increments the card's `version`, and is guarded by four checks: the acting user's firm must own the card (`ERR_FIRM_MISMATCH`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); every timekeeper referenced by a rate row on the card must be `QUALIFIED` (`ERR_TIMEKEEPER_NOT_QUALIFIED`); and no other card of the same firm may already cover the same `effective_year` in `SUBMITTED` or `APPROVED` status (`ERR_RATE_CARD_YEAR_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/rate_card_year_uniqueness_point_semantics
        """
        dept, firm = setup_department_with_firm()
        tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
        card1 = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card1["id"], tk["id"], 100_000)
        submit_rate_card(dept["id"], firm["id"], card1["id"])

        card2 = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card2["id"], tk["id"], 100_000)
        resp = api.submit_rate_card(dept["id"], firm["id"], card2["id"], firm_headers(firm["id"]))
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_YEAR_CONFLICT)
        card2_after = validate_success(api.get_rate_card(dept["id"], firm["id"], card2["id"], ops_headers()))
        assert card2_after["status"] == "DRAFT", (
            f"conflicting submit must leave the card DRAFT, got {card2_after['status']}"
        )

    def test_adjacent_year_no_conflict(self, api):
        """PRD §3.4: "Submission (`DRAFT → SUBMITTED`) stamps `submitted_at` with the logical clock, increments the card's `version`, and is guarded by four checks: the acting user's firm must own the card (`ERR_FIRM_MISMATCH`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); every timekeeper referenced by a rate row on the card must be `QUALIFIED` (`ERR_TIMEKEEPER_NOT_QUALIFIED`); and no other card of the same firm may already cover the same `effective_year` in `SUBMITTED` or `APPROVED` status (`ERR_RATE_CARD_YEAR_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/rate_card_year_uniqueness_point_semantics
        """
        dept, firm = setup_department_with_firm()
        tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
        card1 = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card1["id"], tk["id"], 100_000)
        submit_rate_card(dept["id"], firm["id"], card1["id"])

        # The constraint covers only the SAME effective_year; an adjacent year submits cleanly.
        card2 = create_draft_rate_card(dept["id"], firm["id"], 2027)
        add_rate_row(dept["id"], firm["id"], card2["id"], tk["id"], 102_000)
        submitted = validate_success(
            api.submit_rate_card(dept["id"], firm["id"], card2["id"], firm_headers(firm["id"]))
        )
        assert submitted["status"] == "SUBMITTED", (
            f"a different effective_year must not conflict, got {submitted['status']}"
        )


class TestSubmitGatedByTimekeeperQualification:
    """DRAFT → SUBMITTED requires every referenced timekeeper to be QUALIFIED."""

    def test_submit_blocked_by_pending_timekeeper(self, api):
        """PRD §3.4: "Submission (`DRAFT → SUBMITTED`) stamps `submitted_at` with the logical clock, increments the card's `version`, and is guarded by four checks: the acting user's firm must own the card (`ERR_FIRM_MISMATCH`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); every timekeeper referenced by a rate row on the card must be `QUALIFIED` (`ERR_TIMEKEEPER_NOT_QUALIFIED`); and no other card of the same firm may already cover the same `effective_year` in `SUBMITTED` or `APPROVED` status (`ERR_RATE_CARD_YEAR_CONFLICT`)."

        Design: Difficulty/cross_entity_state_dependency/rate_card_submit_gated_by_timekeeper_qualification
        """
        dept, firm = setup_department_with_firm()
        tk = register_timekeeper(dept["id"], firm["id"], "NotYet", "ASSOCIATE")
        assert tk["qualification_status"] == "PENDING"
        card = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card["id"], tk["id"], 50_000)

        resp = api.submit_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"]))
        validate_error(resp, ApiErrorId.ERR_TIMEKEEPER_NOT_QUALIFIED)
        card_after = validate_success(api.get_rate_card(dept["id"], firm["id"], card["id"], ops_headers()))
        assert card_after["status"] == "DRAFT", (
            f"blocked submit must leave the card DRAFT, got {card_after['status']}"
        )

    def test_submit_succeeds_after_qualification(self, api):
        """PRD §3.4: "Submission (`DRAFT → SUBMITTED`) stamps `submitted_at` with the logical clock, increments the card's `version`, and is guarded by four checks: the acting user's firm must own the card (`ERR_FIRM_MISMATCH`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); every timekeeper referenced by a rate row on the card must be `QUALIFIED` (`ERR_TIMEKEEPER_NOT_QUALIFIED`); and no other card of the same firm may already cover the same `effective_year` in `SUBMITTED` or `APPROVED` status (`ERR_RATE_CARD_YEAR_CONFLICT`)."
        PRD §3.4: "A new timekeeper's `qualification_status` is `PENDING` until a `LegalOpsReviewer` qualifies them (`PENDING → QUALIFIED`), which requires the employing firm to be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/rate_card_submit_gated_by_timekeeper_qualification
        """
        dept, firm = setup_department_with_firm()
        tk = register_timekeeper(dept["id"], firm["id"], "NotYet", "ASSOCIATE")
        card = create_draft_rate_card(dept["id"], firm["id"], 2026)
        add_rate_row(dept["id"], firm["id"], card["id"], tk["id"], 50_000)
        qualify_timekeeper(dept["id"], firm["id"], tk["id"])

        submitted = validate_success(
            api.submit_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"]))
        )
        assert submitted["status"] == "SUBMITTED", (
            f"submit must succeed once every referenced timekeeper is QUALIFIED, got {submitted['status']}"
        )


class TestAnnualRateCapClamping:
    """Approval clamps each row to min(proposed, floored class-keyed ceiling)."""

    def _two_year_setup(self, api, p26, a26):
        dept, firm = setup_department_with_firm(annual_rate_increase_cap_pct=5.00)
        tk_p = register_and_qualify_timekeeper(dept["id"], firm["id"], "P1", "PARTNER")
        tk_a = register_and_qualify_timekeeper(dept["id"], firm["id"], "A1", "ASSOCIATE")
        create_approved_rate_card(
            dept["id"], firm["id"],
            [(tk_p["id"], p26), (tk_a["id"], a26)],
            effective_year=2026,
        )
        return dept, firm, tk_p, tk_a

    def _propose_and_approve(self, api, dept, firm, tk_p, p27, tk_a, a27):
        card = create_draft_rate_card(dept["id"], firm["id"], 2027)
        row_p = add_rate_row(dept["id"], firm["id"], card["id"], tk_p["id"], p27)
        row_a = add_rate_row(dept["id"], firm["id"], card["id"], tk_a["id"], a27)
        submit_rate_card(dept["id"], firm["id"], card["id"])
        approve_rate_card(dept["id"], firm["id"], card["id"])
        p = validate_success(api.get_rate_row(dept["id"], firm["id"], card["id"], row_p["id"], ops_headers()))
        a = validate_success(api.get_rate_row(dept["id"], firm["id"], card["id"], row_a["id"], ops_headers()))
        return p, a

    def test_partner_rate_clamped_by_full_cap(self, api):
        """PRD §3.4: "The cap applicable to a row depends on the timekeeper's class: the full `annual_rate_increase_cap_pct` for a `PARTNER`, eighty percent of that cap for an `ASSOCIATE`, and sixty percent of it for a `PARALEGAL`."
        PRD §3.4: "Otherwise, for each row, the ceiling is the prior card's approved rate for the same timekeeper multiplied by one plus the applicable sub-cap percentage divided by one hundred, truncated down to a whole cent; the row's `approved_rate_cents` is then the smaller of its proposed `hourly_rate_cents` and that ceiling."

        Design: Difficulty/combinatorial_formula/rate_cap_nested_min_max
        """
        dept, firm, tk_p, tk_a = self._two_year_setup(api, 100_000, 50_000)
        # Partner proposes 106000 (+6.00% > 5.00% cap) → ceiling floor(100000 * 1.05) = 105000.
        p, _ = self._propose_and_approve(api, dept, firm, tk_p, 106_000, tk_a, 50_000)
        assert p["approved_rate_cents"] == 105_000, (
            f"partner row must clamp to floor(100000*1.05)=105000, got {p['approved_rate_cents']}"
        )
        assert p["approved_rate_cents"] != 106_000, "proposed rate above the cap must not survive"

    def test_associate_rate_clamped_by_sub_cap(self, api):
        """PRD §3.4: "The cap applicable to a row depends on the timekeeper's class: the full `annual_rate_increase_cap_pct` for a `PARTNER`, eighty percent of that cap for an `ASSOCIATE`, and sixty percent of it for a `PARALEGAL`."
        PRD §3.4: "Otherwise, for each row, the ceiling is the prior card's approved rate for the same timekeeper multiplied by one plus the applicable sub-cap percentage divided by one hundred, truncated down to a whole cent; the row's `approved_rate_cents` is then the smaller of its proposed `hourly_rate_cents` and that ceiling."
        PRD §3.4: "Violators are clamped rather than blocked — approval itself is never refused over the cap."

        Design: Difficulty/combinatorial_formula/rate_cap_nested_min_max
        """
        dept, firm, tk_p, tk_a = self._two_year_setup(api, 100_000, 50_000)
        # Associate proposes 53000 (+6.00% > 5.00*0.80 = 4.00% sub-cap) → ceiling floor(50000 * 1.04) = 52000.
        _, a = self._propose_and_approve(api, dept, firm, tk_p, 100_000, tk_a, 53_000)
        assert a["approved_rate_cents"] == 52_000, (
            f"associate row must clamp to floor(50000*1.04)=52000, got {a['approved_rate_cents']}"
        )
        assert a["approved_rate_cents"] != 53_000, "proposed rate above the sub-cap must not survive"

    def test_partner_rate_at_exact_cap_not_clamped(self, api):
        """PRD §3.4: "Otherwise, for each row, the ceiling is the prior card's approved rate for the same timekeeper multiplied by one plus the applicable sub-cap percentage divided by one hundred, truncated down to a whole cent; the row's `approved_rate_cents` is then the smaller of its proposed `hourly_rate_cents` and that ceiling."

        Design: Difficulty/boundary_precision_check/rate_cap_exact_boundary_compliant
        """
        dept, firm, tk_p, tk_a = self._two_year_setup(api, 100_000, 50_000)
        # Exactly +5.00%: min(105000, floor(100000*1.05)=105000) — the inclusive boundary passes through.
        p, _ = self._propose_and_approve(api, dept, firm, tk_p, 105_000, tk_a, 50_000)
        assert p["approved_rate_cents"] == 105_000, (
            f"a proposal exactly at the 5.00% cap is compliant and must not be reduced, got {p['approved_rate_cents']}"
        )

    def test_associate_rate_at_exact_sub_cap_not_clamped(self, api):
        """PRD §3.4: "The cap applicable to a row depends on the timekeeper's class: the full `annual_rate_increase_cap_pct` for a `PARTNER`, eighty percent of that cap for an `ASSOCIATE`, and sixty percent of it for a `PARALEGAL`."
        PRD §3.4: "Otherwise, for each row, the ceiling is the prior card's approved rate for the same timekeeper multiplied by one plus the applicable sub-cap percentage divided by one hundred, truncated down to a whole cent; the row's `approved_rate_cents` is then the smaller of its proposed `hourly_rate_cents` and that ceiling."

        Design: Difficulty/boundary_precision_check/rate_cap_exact_boundary_compliant
        """
        dept, firm, tk_p, tk_a = self._two_year_setup(api, 100_000, 50_000)
        # Exactly +4.00% (= 5.00 * 0.80 sub-cap): min(52000, floor(50000*1.04)=52000) — boundary passes through.
        _, a = self._propose_and_approve(api, dept, firm, tk_p, 100_000, tk_a, 52_000)
        assert a["approved_rate_cents"] == 52_000, (
            f"a proposal exactly at the 4.00% sub-cap is compliant and must not be reduced, got {a['approved_rate_cents']}"
        )


class TestApprovedCardCountInvariant:
    """Exactly one APPROVED card per firm survives every approval."""

    def _setup_two_cards(self, api):
        dept, firm = setup_department_with_firm(annual_rate_increase_cap_pct=5.00)
        tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
        card26 = create_approved_rate_card(dept["id"], firm["id"], [(tk["id"], 100_000)], 2026)
        card27 = create_draft_rate_card(dept["id"], firm["id"], 2027)
        add_rate_row(dept["id"], firm["id"], card27["id"], tk["id"], 105_000)
        submit_rate_card(dept["id"], firm["id"], card27["id"])
        return dept, firm, card26, card27

    def test_approve_supersedes_prior_approved_card(self, api):
        """PRD §3.4: "Approval also supersedes: any other card of the firm in `APPROVED` status transitions to `SUPERSEDED`, and the approved card's `version` increments."

        Design: Difficulty/compensating_invariant/approved_rate_card_count_invariant_under_supersession
        """
        dept, firm, card26, card27 = self._setup_two_cards(api)
        approve_rate_card(dept["id"], firm["id"], card27["id"])

        c26 = validate_success(api.get_rate_card(dept["id"], firm["id"], card26["id"], ops_headers()))
        c27 = validate_success(api.get_rate_card(dept["id"], firm["id"], card27["id"], ops_headers()))
        assert c26["status"] == "SUPERSEDED", (
            f"prior APPROVED card must be SUPERSEDED, got {c26['status']}"
        )
        assert c27["status"] == "APPROVED", (
            f"newly approved card must be APPROVED, got {c27['status']}"
        )

    def test_approved_card_count_remains_one(self, api, legal_ops_headers):
        """PRD §3.4: "Approval also supersedes: any other card of the firm in `APPROVED` status transitions to `SUPERSEDED`, and the approved card's `version` increments."
        PRD §2.3: "Several listings accept optional filter parameters in addition to `limit` and `offset`: panel firms and guideline versions filter by `status`; matters filter by `engagement_status` and `panel_firm_id`; acknowledgments filter by `status` and `guideline_version_id`; rate cards filter by `status` and `effective_year`; timekeepers filter by `qualification_status` and `tk_class`; invoices filter by `status`; line items filter by `review_status`; appeals filter by `status`; and accruals and scorecard snapshots filter by `period_year` and `period_month`."

        Design: Difficulty/compensating_invariant/approved_rate_card_count_invariant_under_supersession
        """
        dept, firm, card26, card27 = self._setup_two_cards(api)
        approve_rate_card(dept["id"], firm["id"], card27["id"])

        resp = api.list_rate_cards(dept["id"], firm["id"], legal_ops_headers, params={"status": "APPROVED"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            f"exactly one APPROVED card per firm must survive supersession, got {meta['total_count']}"
        )
        assert len(data) == 1 and data[0]["id"] == card27["id"]


def test_disqualify_timekeeper_with_pending_lines_blocked(api, legal_ops_headers):
    """PRD §3.4: "A qualified timekeeper may later be disqualified (`QUALIFIED → DISQUALIFIED`, terminal), but only while no line item in `PENDING` review status still references them — otherwise the transition is refused with `ERR_TIMEKEEPER_HAS_PENDING_LINES`."
    PRD §3.5: "Otherwise, if the asserted rate matches no approved rate on the firm's card for that year yet sits below the approved rate, the line is left `PENDING` for manual review — the rate-not-on-card case."

    Design: Corner/state_machines/disqualify_timekeeper_with_pending_lines_blocked
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    tk_id = ctx["timekeeper"]["id"]
    submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [rate_not_on_card_line(tk_id, "L110", 1.00, 90_000)],
        invoice_number="INV-DQ",
    )

    resp = api.disqualify_timekeeper(dept_id, firm_id, tk_id, legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_TIMEKEEPER_HAS_PENDING_LINES)
    tk_after = validate_success(api.get_timekeeper(dept_id, firm_id, tk_id, legal_ops_headers))
    assert tk_after["qualification_status"] == "QUALIFIED", (
        f"blocked disqualify must leave the timekeeper QUALIFIED, got {tk_after['qualification_status']}"
    )


def test_panel_firm_user_cannot_approve_rate_card(api):
    """PRD §2.1: "Write operations are restricted per endpoint, and a caller whose role is not permitted on an endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "`LegalOpsReviewer` — in-house legal operations staff. This role administers departments, onboards and manages panel firms, publishes guideline versions, creates matters, approves and rejects rate cards, qualifies and disqualifies timekeepers, reviews invoice line items, decides appeals, pays invoices, maintains matter forecasts, recomputes scorecards, and drives the logical clock."

    Design: Corner/rbac/panel_firm_user_cannot_approve_rate_card
    """
    dept, firm = setup_department_with_firm()
    tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
    card = create_draft_rate_card(dept["id"], firm["id"], 2026)
    add_rate_row(dept["id"], firm["id"], card["id"], tk["id"], 100_000)
    submit_rate_card(dept["id"], firm["id"], card["id"])

    resp = api.approve_rate_card(dept["id"], firm["id"], card["id"], firm_headers(firm["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_stale_version_on_rate_card_create(api):
    """PRD §2.8: "Creating a rate card under a panel firm requires `expected_panel_firm_version`, matched against the firm's current `version` in the same way. Rate-card creation advances the firm's `version`, so a replayed creation intent is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_rate_card_create
    """
    dept, firm = setup_department_with_firm()
    firm_v = get_firm(dept["id"], firm["id"])["version"]
    first = validate_success(
        api.create_rate_card(
            dept["id"], firm["id"],
            create_rate_card_payload(effective_year=2026, expected_panel_firm_version=firm_v),
            firm_headers(firm["id"]),
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    # The first create advanced the firm's version; replaying the observed version is stale.
    resp = api.create_rate_card(
        dept["id"], firm["id"],
        create_rate_card_payload(effective_year=2027, expected_panel_firm_version=firm_v),
        firm_headers(firm["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_immediate_visibility_of_mutation_in_same_response(api, legal_ops_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.4: "When a `LegalOpsReviewer` approves a submitted card (`SUBMITTED → APPROVED`), each rate row's `approved_rate_cents` is set as follows."

    Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_response
    """
    dept, firm = setup_department_with_firm()
    tk = register_and_qualify_timekeeper(dept["id"], firm["id"])
    card = create_draft_rate_card(dept["id"], firm["id"], 2026)
    add_rate_row(dept["id"], firm["id"], card["id"], tk["id"], 100_000)
    submit_rate_card(dept["id"], firm["id"], card["id"])

    resp = api.approve_rate_card(dept["id"], firm["id"], card["id"], legal_ops_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED", (
        f"the approve response itself must reflect the post-mutation state, got {data['status']}"
    )
    assert data["id"] == card["id"]
