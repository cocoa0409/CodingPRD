"""Carryover variants, the fifteen-percent ceiling, waivers, and the
close-out gates (PRD §3.10)."""

from test_helpers import (
    ApiErrorId,
    allow_expenditure,
    amendment_line,
    api_client,
    build_user_headers,
    charge_expenditure,
    disallow_expenditure,
    draft_amendment,
    get_grant,
    reclassify_expenditure,
    record_finding,
    setup_allocated,
    setup_certified_allocation,
    setup_visit_in_progress,
    validate_error,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")
MONITOR = build_user_headers("monitor-1", "SEAMonitor")


class TestCarryoverVariants:

    def test_carryover_provisional_vs_final_divergence(self):
        """PRD §3.10: "The **provisional** variant is forward-looking:
        `provisional_carryover_cents` is `net_allocable_cents` minus
        `liquidated_cents` minus `pending_cents` — pending charges count as
        encumbered at face value — and it is recomputed on every expenditure
        creation, review, and reclassification, and on every amendment
        approval or void."
        PRD §3.10: "The **final** variant is chronological:
        `final_carryover_cents` is `net_allocable_cents` minus
        `liquidated_cents` only, because no `PENDING_REVIEW` expenditure can
        exist at close-out, and both it and its percentage are stamped onto
        the grant at close-out rather than maintained live."

        Design: Difficulty/dual_variant_calc/carryover_provisional_vs_final_divergence
        """
        # Grant 20,000,000 (admin 0): school 60/100 is ELIGIBLE and served.
        ctx = setup_certified_allocation(2033, [(60, 100)],
                                         total_allocation_cents=20_000_000)
        grant = ctx["grant"]
        allocation_id = ctx["allocation"]["id"]
        e1 = charge_expenditure(grant, 3_000_000,
                                school_allocation_id=allocation_id,
                                incurred_date="2032-09-15",
                                description="tutor salaries")
        allow_expenditure(e1["id"])
        e2 = charge_expenditure(grant, 1_000_000,
                                school_allocation_id=allocation_id,
                                incurred_date="2032-10-01",
                                description="curriculum materials")
        mid = get_grant(grant["id"])
        # Provisional counts the pending charge as encumbered at face value.
        assert mid["liquidated_cents"] == 3_000_000
        assert mid["pending_cents"] == 1_000_000
        assert mid["provisional_carryover_cents"] == 16_000_000
        assert mid["provisional_carryover_pct_bp"] == 8000

        disallow_expenditure(e2["id"], disallow_reason="UNALLOWABLE_COST",
                             review_note="not allocable")
        reclassify_expenditure(e2["id"], "NON_TITLE_I_LOCAL")
        # Provisional now equals net - liquidated (pending drained): the 85%
        # carryover exceeds the ceiling, so request and win a waiver first.
        validate_success(api_client.request_carryover_waiver(
            grant["id"],
            {"justification": "unusual mid-year staffing vacancy delayed the "
                              "tutoring program launch significantly"},
            DIRECTOR))
        validate_success(api_client.decide_carryover_waiver(
            grant["id"], {"decision": "GRANT"}, MONITOR))
        closed = validate_success(api_client.close_out(grant["id"], DIRECTOR))
        assert closed["status"] == "CLOSED_OUT"
        assert closed["final_carryover_cents"] == 17_000_000, \
            "FINAL subtracts liquidated only: disallowed/reclassified excluded"
        assert closed["final_carryover_pct_bp"] == 8500
        assert closed["final_carryover_cents"] - \
            16_000_000 == 1_000_000, \
            "the variants differ by exactly the reclassified charge"

    def test_provisional_carryover_counts_pending_at_face_value(self):
        """PRD §3.10: "The **provisional** variant is forward-looking:
        `provisional_carryover_cents` is `net_allocable_cents` minus
        `liquidated_cents` minus `pending_cents` — pending charges count as
        encumbered at face value — and it is recomputed on every expenditure
        creation, review, and reclassification, and on every amendment
        approval or void."
        PRD §3.10: "Each variant's percentage — `provisional_carryover_pct_bp`
        and `final_carryover_pct_bp` — is its cents figure multiplied by
        10,000 and divided by the grant's `total_allocation_cents`, rounded
        half up to a whole basis point; note the denominator is the total
        allocation, not the net allocable amount."

        Design: Difficulty/dual_variant_calc/carryover_provisional_vs_final_divergence
        """
        ctx = setup_certified_allocation(2036, [(60, 100)],
                                         total_allocation_cents=20_000_000)
        grant = ctx["grant"]
        allocation_id = ctx["allocation"]["id"]
        e1 = charge_expenditure(grant, 3_000_000,
                                school_allocation_id=allocation_id,
                                incurred_date="2035-09-15",
                                description="tutor salaries")
        allow_expenditure(e1["id"])
        charge_expenditure(grant, 1_000_000,
                           school_allocation_id=allocation_id,
                           incurred_date="2035-10-01",
                           description="curriculum materials")
        mid = get_grant(grant["id"])
        assert mid["provisional_carryover_cents"] == 16_000_000
        assert mid["provisional_carryover_pct_bp"] == 8000, \
            "16,000,000 / 20,000,000 == 8000 bp on the TOTAL denominator"
        # Disallowing the pending charge drains pending_cents; the
        # provisional variant immediately reflects it.
        e2_rows = api_client.list_expenditures(
            DIRECTOR, params={"grant_id": grant["id"],
                              "status": "PENDING_REVIEW"})
        e2 = validate_success(e2_rows)[0]
        disallow_expenditure(e2["id"], disallow_reason="UNALLOWABLE_COST")
        after = get_grant(grant["id"])
        assert after["pending_cents"] == 0
        assert after["provisional_carryover_cents"] == 17_000_000
        assert after["provisional_carryover_pct_bp"] == 8500


class TestCarryoverLimitBoundary:

    def test_carryover_limit_exact_15pct(self):
        """PRD §3.10: "The statutory ceiling of fifteen percent is evaluated
        on the rounded basis-point value: a figure strictly greater than 1500
        basis points exceeds the limit."
        PRD §3.10: "And the final carryover percentage must be at most 1500
        basis points unless the grant holds a `GRANTED` waiver, else
        `ERR_CARRYOVER_LIMIT_EXCEEDED`. A successful close-out stamps
        `final_carryover_cents` and `final_carryover_pct_bp` onto the grant
        and advances its `version` by one, closing the fiscal year for good."

        Design: Difficulty/boundary_precision_check/carryover_limit_exact_15pct
        """
        # Carryover exactly 1,500,000 on a 10,000,000 grant == 1500 bp.
        ctx3 = setup_certified_allocation(2029, [(100, 100)])
        e3 = charge_expenditure(ctx3["grant"], 8_500_000,
                                school_allocation_id=ctx3["allocation"]["id"],
                                incurred_date="2028-09-01",
                                description="instructional salaries")
        allow_expenditure(e3["id"])
        closed = validate_success(api_client.close_out(ctx3["grant"]["id"],
                                                       DIRECTOR))
        assert closed["status"] == "CLOSED_OUT"
        assert closed["final_carryover_cents"] == 1_500_000
        assert closed["final_carryover_pct_bp"] == 1500, \
            "the boundary is inclusive: 1500 bp closes without a waiver"

        # One half-cent over the line: 1,500,500 rounds to 1501 bp.
        # The second grant reuses the first scenario's roster: nces_id is
        # unique and every certified snapshot must cover every active school
        # exactly once (PRD §3.2).
        ctx4 = setup_certified_allocation(2030, [(100, 100)],
                                          schools=ctx3["schools"])
        e4 = charge_expenditure(ctx4["grant"], 8_499_500,
                                school_allocation_id=ctx4["allocation"]["id"],
                                incurred_date="2029-09-01",
                                description="instructional salaries")
        allow_expenditure(e4["id"])
        resp = api_client.close_out(ctx4["grant"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_LIMIT_EXCEEDED)
        grant4 = get_grant(ctx4["grant"]["id"])
        assert grant4["status"] == "ALLOCATED", "close-out rejected"

    def test_carryover_rounding_just_below_the_line(self):
        """PRD §3.10: "Each variant's percentage —
        `provisional_carryover_pct_bp` and `final_carryover_pct_bp` — is its
        cents figure multiplied by 10,000 and divided by the grant's
        `total_allocation_cents`, rounded half up to a whole basis point; note
        the denominator is the total allocation, not the net allocable amount.
        The statutory ceiling of fifteen percent is evaluated on the rounded
        basis-point value: a figure strictly greater than 1500 basis points
        exceeds the limit."

        Design: Difficulty/boundary_precision_check/carryover_limit_exact_15pct
        """
        # 1,500,499 cents of carryover rounds DOWN to 1500 bp: closes.
        ctx5 = setup_certified_allocation(2031, [(100, 100)])
        e5 = charge_expenditure(ctx5["grant"], 8_499_501,
                                school_allocation_id=ctx5["allocation"]["id"],
                                incurred_date="2030-09-01",
                                description="instructional salaries")
        allow_expenditure(e5["id"])
        closed = validate_success(api_client.close_out(ctx5["grant"]["id"],
                                                       DIRECTOR))
        assert closed["final_carryover_cents"] == 1_500_499
        assert closed["final_carryover_pct_bp"] == 1500, \
            "round_half_up(1500.499) == 1500, within the limit"

        # 1,500,501 cents rounds UP to 1501 bp: rejected.
        # The second grant reuses the first scenario's roster (PRD §3.2
        # nces_id uniqueness + total snapshot coverage of active schools).
        ctx6 = setup_certified_allocation(2037, [(100, 100)],
                                          schools=ctx5["schools"])
        e6 = charge_expenditure(ctx6["grant"], 8_499_499,
                                school_allocation_id=ctx6["allocation"]["id"],
                                incurred_date="2036-09-01",
                                description="instructional salaries")
        allow_expenditure(e6["id"])
        resp = api_client.close_out(ctx6["grant"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_LIMIT_EXCEEDED)


class TestCloseOutGates:

    def test_closeout_blocked_by_open_findings(self):
        """PRD §3.10: "No finding of any visit of the grant may remain
        non-terminal — anything in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or
        `CAP_RETURNED` blocks close-out with
        `ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT`."
        PRD §2.8: "Seventh come the segregation-of-duties rules of §2.9, and
        eighth the supplement-not-supplant gate and the open-findings
        close-out block." and "Eleventh and last, the fiscal rules: set-aside
        floors, amendment net-zero and post-amendment floors, charge amounts
        against remaining balances, and the carryover and waiver conditions.
        Because the tiers run in this sequence, a request that fails several
        of them surfaces the earliest failure — a malformed body reports
        `ERR_INVALID_REQUEST`, never a masked state-machine error from a later
        tier."

        Design: Corner/errors/closeout_blocked_by_open_findings
        """
        ctx = setup_allocated(2080, [(100, 100)])
        visit = setup_visit_in_progress(ctx["grant"]["id"],
                                        scope="COMPREHENSIVE")
        record_finding(visit["id"], description="ranking not followed",
                       cap_due_date="2026-09-01")
        # The safety gate (tier 8) fires even though the 100% carryover would
        # also trip the fiscal gate (tier 11).
        resp = api_client.close_out(ctx["grant"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT)
        grant = get_grant(ctx["grant"]["id"])
        assert grant["status"] == "ALLOCATED"

    def test_closeout_blocked_by_pending_expenditure(self):
        """PRD §3.10: "No expenditure may remain in `PENDING_REVIEW`, else
        `ERR_UNRESOLVED_EXPENDITURES`."

        Design: Corner/errors/closeout_blocked_by_pending_expenditure
        """
        ctx = setup_certified_allocation(2081, [(100, 100)])
        grant = ctx["grant"]
        allocation_id = ctx["allocation"]["id"]
        # Liquidate enough that the final carryover would be within the
        # fifteen-percent ceiling (10,000,000 - 8,900,000 = 1,100,000 cents
        # == 1100 bp), so the pending-expenditure gate is the only one that
        # can fire.
        e1 = charge_expenditure(grant, 8_900_000,
                                school_allocation_id=allocation_id,
                                incurred_date="2080-09-01",
                                description="program salaries")
        allow_expenditure(e1["id"])
        charge_expenditure(grant, 1000,
                           school_allocation_id=allocation_id,
                           incurred_date="2080-09-02",
                           description="unreviewed charge")
        resp = api_client.close_out(grant["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_EXPENDITURES)
        assert get_grant(grant["id"])["status"] == "ALLOCATED"

    def test_closeout_blocked_by_draft_amendment(self):
        """PRD §3.10: "No amendment may remain in `DRAFT` or `SUBMITTED`, else
        `ERR_UNRESOLVED_AMENDMENTS`."

        Design: Corner/errors/closeout_blocked_by_draft_amendment
        """
        ctx = setup_certified_allocation(2082, [(100, 100)])
        grant = ctx["grant"]
        allocation = ctx["allocation"]
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        # Liquidate 8,500,000 so the final carryover (1,500,000 == 1500 bp)
        # sits exactly at the ceiling and the amendment gate is the only one
        # that can fire.
        e1 = charge_expenditure(grant, 8_500_000,
                                school_allocation_id=allocation["id"],
                                incurred_date="2081-09-01",
                                description="program salaries")
        allow_expenditure(e1["id"])
        # A DRAFT amendment (never submitted) still blocks close-out.
        draft_amendment(grant["id"],
                        [amendment_line("SCHOOL_ALLOCATION", allocation["id"],
                                        8_900_000),
                         amendment_line("SET_ASIDE", pd["id"], 600_000)])
        resp = api_client.close_out(grant["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_AMENDMENTS)
        assert get_grant(grant["id"])["status"] == "ALLOCATED"


class TestWaivers:

    def test_decide_waiver_without_request_rejected(self):
        """PRD §3.10: "The `SEAMonitor` decides a `REQUESTED` waiver — any
        other waiver status is rejected with `ERR_WAIVER_INVALID_STATE` — with
        a `decision` of `GRANT` or `DENY` and an optional `decision_note`."

        Design: Corner/errors/decide_waiver_without_request_rejected
        """
        ctx = setup_allocated(2078, [(100, 100)])
        resp = api_client.decide_carryover_waiver(
            ctx["grant"]["id"], {"decision": "GRANT"}, MONITOR)
        validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID_STATE)
        grant = get_grant(ctx["grant"]["id"])
        assert grant["carryover_waiver_status"] == "NONE"

    def test_waiver_lookback_three_years_rejected(self):
        """PRD §3.10: "requires the three-year lookback to be clear: no other
        grant may hold a `GRANTED` waiver in any of the three fiscal years
        immediately preceding this grant's `fiscal_year`, or the request is
        rejected with `ERR_CARRYOVER_WAIVER_WITHIN_3_YEARS`. A denied waiver
        never blocks a future request, and a granted waiver's own year is the
        anchor from which the three following years are counted."

        Design: Corner/errors/waiver_lookback_three_years_rejected
        """
        # FY2090 grant wins a GRANTED waiver (provisional carryover is 100%
        # with no expenditures, comfortably above the ceiling).
        ctx1 = setup_allocated(2090, [(50, 100)],
                               total_allocation_cents=5_000_000,
                               name_prefix="Lookback", nces_prefix="91")
        validate_success(api_client.request_carryover_waiver(
            ctx1["grant"]["id"],
            {"justification": "extraordinary circumstances delayed obligated "
                              "spending for the documented program year"},
            DIRECTOR))
        validate_success(api_client.decide_carryover_waiver(
            ctx1["grant"]["id"], {"decision": "GRANT"}, MONITOR))
        # FY2091 sits inside the three-year lookback anchored on FY2090.
        # The second grant reuses the first scenario's roster: nces_id is
        # unique and every certified snapshot must cover every active school
        # exactly once (PRD §3.2).
        ctx2 = setup_allocated(2091, [(50, 100)],
                               total_allocation_cents=5_000_000,
                               schools=ctx1["schools"])
        resp = api_client.request_carryover_waiver(
            ctx2["grant"]["id"],
            {"justification": "second consecutive year request that the "
                              "statute forbids within three years"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_WAIVER_WITHIN_3_YEARS)
        grant2 = get_grant(ctx2["grant"]["id"])
        assert grant2["carryover_waiver_status"] == "NONE"

    def test_waiver_within_limit_rejected(self):
        """PRD §3.10: "requires the provisional carryover percentage to be
        strictly greater than 1500 basis points, since a district already
        within the limit has nothing to waive (else
        `ERR_CARRYOVER_WITHIN_LIMIT`)".

        Design: Corner/errors/waiver_within_limit_rejected
        """
        ctx = setup_certified_allocation(2092, [(100, 100)])
        grant = ctx["grant"]
        e1 = charge_expenditure(grant, 9_000_000,
                                school_allocation_id=ctx["allocation"]["id"],
                                incurred_date="2091-09-01",
                                description="program salaries")
        allow_expenditure(e1["id"])
        # Provisional carryover is 1,000,000 of 10,000,000 == 1000 bp.
        assert get_grant(grant["id"])["provisional_carryover_pct_bp"] == 1000
        resp = api_client.request_carryover_waiver(
            grant["id"],
            {"justification": "request filed although the district is "
                              "comfortably within the fifteen percent limit"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_WITHIN_LIMIT)
