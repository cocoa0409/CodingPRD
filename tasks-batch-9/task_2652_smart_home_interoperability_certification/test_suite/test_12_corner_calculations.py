"""The service's derived arithmetic, driven to the boundaries that expose it.

Four computations are exercised here: the test plan's feature-set closure and its
three case counts, a plugfest's distinct-vendor quorum, the marginally-tiered
noncompliance penalty across both of its breakpoints, and the two input-set
questions behind the credit ledger and the readiness score.
"""

from test_helpers import (
    CASE_OPEN,
    CASE_REMEDIATED,
    COMPLIANCE_UNDER_INVESTIGATION,
    ERR_INSUFFICIENT_DISTINCT_VENDORS,
    PLAN_DRAFT,
    PLUGFEST_LOCKED,
    PLUGFEST_REGISTRATION_OPEN,
    PUB_UNPUBLISHED,
    advance_case,
    append_results,
    assert_cents,
    assert_credit_ledger_invariant,
    assert_penalty,
    assert_reserved_bench_minutes,
    assert_score,
    assert_states,
    build_laboratory,
    build_member,
    build_program,
    build_specification,
    cancel_session,
    feature,
    new_case,
    new_listing,
    new_participation,
    new_plugfest,
    new_session,
    new_submission,
    read_laboratory,
    read_ledger,
    read_listing,
    read_member,
    read_readiness,
    read_submission,
    read_test_plan,
    result_line,
    same_instant,
    set_clock,
    start_session,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import ADMIN_HEADERS

#: One optional declaration seeds a two-round chain: B_OPT activates the
#: CONDITIONAL C_COND, whose own activation then reaches D_COND. E_OPT is never
#: declared and the THERMOSTAT rows — one of which reuses the code B_OPT — belong
#: to another device class.
CLOSURE_FEATURES = [
    feature("A_CORE", "MANDATORY", 20),
    feature("B_OPT", "OPTIONAL", 8),
    feature("C_COND", "CONDITIONAL", 6, depends_on="B_OPT"),
    feature("D_COND", "CONDITIONAL", 5, depends_on="C_COND"),
    feature("E_OPT", "OPTIONAL", 12),
    feature("T_CORE", "MANDATORY", 10, device_type="THERMOSTAT"),
    feature("B_OPT", "OPTIONAL", 9, device_type="THERMOSTAT"),
]

#: One mandatory and one optional lighting feature set, so a submission declaring
#: both pins a different fee from one declaring only the mandatory code.
LEDGER_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "OPTIONAL", 10),
]

#: The single mandatory feature set the penalty scenario tests against.
ONE_MANDATORY_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]


def _closure_program():
    """An IN_REVIEW lighting submission declaring A_CORE and B_OPT, with its plan
    resolved."""
    return build_program(
        stage="plan",
        features=CLOSURE_FEATURES,
        declared_codes=["A_CORE", "B_OPT"],
        device_type="LIGHTING",
    )


def _two_vendor_plugfest_program():
    """One member holding two lighting devices, a second member holding one, and a
    plugfest whose quorum is two distinct vendors."""
    set_clock()
    ctx = build_specification(ONE_MANDATORY_FEATURE)
    ctx.update(build_laboratory())
    ctx.update(build_member(scope_specification_id=ctx.specification_id))
    ctx.submission_1 = new_submission(
        ctx.member_id, ctx.specification_id, ["CORE_ONOFF"], device_model="AL-100"
    )
    ctx.submission_2 = new_submission(
        ctx.member_id, ctx.specification_id, ["CORE_ONOFF"], device_model="AL-200"
    )
    co_vendor = build_member(scope_specification_id=ctx.specification_id)
    ctx.member_2_id = co_vendor.member_id
    ctx.submission_3 = new_submission(
        co_vendor.member_id, ctx.specification_id, ["CORE_ONOFF"], device_model="BL-300"
    )
    ctx.plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start="2026-10-05T09:00:00Z",
        window_end="2026-10-05T17:00:00Z",
        registration_deadline="2026-10-01T00:00:00Z",
        min_distinct_vendors=2,
    )
    ctx.plugfest_id = ctx.plugfest["id"]
    return ctx


def _register_both_devices_of_the_first_member(ctx):
    """Two participations, one vendor."""
    ctx.participation_1 = new_participation(
        ctx.plugfest_id, ctx.member_id, ctx.submission_1["id"]
    )
    ctx.participation_2 = new_participation(
        ctx.plugfest_id, ctx.member_id, ctx.submission_2["id"]
    )
    return ctx


def _walk_case_to_remediated(case_id):
    """ESCALATE, order thirty days of remediation, then confirm it."""
    advance_case(case_id, "ESCALATE")
    advance_case(case_id, "ORDER_REMEDIATION", remediation_days=30)
    advance_case(case_id, "CONFIRM_REMEDIATION")


def _three_priced_cases_program():
    """One UNPUBLISHED listing carrying three cases priced at 100, 101 and 1200
    impact units, the first two walked back to REMEDIATED so the next may open."""
    ctx = build_program(stage="review_complete", features=ONE_MANDATORY_FEATURE)
    listing = new_listing(ctx.submission_id)
    ctx.listing_id = listing["id"]
    ctx.case_1 = new_case(
        ctx.listing_id,
        category="INTEROP_DEFECT",
        evidence_summary="Pairing failures reported by three ecosystems",
        claimed_impact_units=100,
    )
    _walk_case_to_remediated(ctx.case_1["id"])
    ctx.case_2 = new_case(
        ctx.listing_id,
        category="INTEROP_DEFECT",
        evidence_summary="One more affected unit than the first case",
        claimed_impact_units=101,
    )
    _walk_case_to_remediated(ctx.case_2["id"])
    ctx.case_3 = new_case(
        ctx.listing_id,
        category="SECURITY_DEFECT",
        evidence_summary="Attestation bypass across the fleet",
        claimed_impact_units=1200,
    )
    return ctx


def _escrowed_plus_draft_program():
    """A funded member with one SUBMITTED submission and one left in DRAFT."""
    set_clock()
    ctx = build_specification(LEDGER_FEATURES)
    ctx.update(build_member(scope_specification_id=ctx.specification_id, credit_cents=1000000))
    ctx.submission_a = new_submission(
        ctx.member_id,
        ctx.specification_id,
        ["CORE_ONOFF", "CORE_DIM"],
        device_model="AL-100",
    )
    ctx.submission_b = new_submission(
        ctx.member_id, ctx.specification_id, ["CORE_ONOFF"], device_model="AL-200"
    )
    submit_submission(ctx.submission_a["id"], ctx.member_id)
    return ctx


def _two_bench_readiness_program():
    """Two INTEROP sessions on the same window and different benches, the first one
    already carrying a PASS on each of the two mandatory feature sets."""
    ctx = build_program(stage="issued")
    ctx.session_1 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    ctx.session_2 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    set_clock("2026-09-02T09:00:00Z")
    start_session(ctx.session_1["id"], ctx.laboratory_id)
    append_results(
        ctx.session_1["id"],
        ctx.laboratory_id,
        [
            result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "h1"),
            result_line(ctx.feature_set_ids["CORE_DIM"], "PASS", "h2"),
        ],
    )
    return ctx


def _record_the_overriding_fail(ctx):
    """A later FAIL on CORE_DIM, recorded an hour on in the second session."""
    set_clock("2026-09-02T10:00:00Z")
    start_session(ctx.session_2["id"], ctx.laboratory_id)
    append_results(
        ctx.session_2["id"],
        ctx.laboratory_id,
        [result_line(ctx.feature_set_ids["CORE_DIM"], "FAIL", "h3")],
    )
    return ctx


def _cancel_the_second_session(ctx):
    """Cancel the session carrying the FAIL and record one more line on the first,
    which is what forces the persisted provisional score to be rewritten."""
    cancel_session(ctx.session_2["id"], ctx.laboratory_headers)
    append_results(
        ctx.session_1["id"],
        ctx.laboratory_id,
        [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "h4")],
    )
    return ctx


class TestTestPlanClosureReachesItsFixedPoint:
    """The closure over a lighting feature graph whose conditional chain is two
    rounds deep."""

    def test_01_the_conditional_chain_is_followed_for_two_rounds(self):
        """One declared optional code activates a conditional feature set, and that
        activation activates a second conditional one, so the closure holds four
        feature sets ordered by feature_code.

        PRD (§3.5): "It then propagates to a fixed point, applying two rules on
        every round and repeating until the working set stops growing, with eight
        rounds sufficing for any graph this service accepts."

        Design: Corner/calculations/plan_closure_needs_two_propagation_rounds_to_reach_its_fixed_point
        """
        ctx = _closure_program()

        plan = read_test_plan(ctx.plan_id)

        expected = [
            ctx.feature_set_ids["LIGHTING:A_CORE"],
            ctx.feature_set_ids["LIGHTING:B_OPT"],
            ctx.feature_set_ids["LIGHTING:C_COND"],
            ctx.feature_set_ids["LIGHTING:D_COND"],
        ]
        assert plan["included_feature_set_ids"] == expected, (
            "the closure must hold A_CORE, B_OPT, C_COND and D_COND in feature_code "
            "order, expected {}, got {}".format(expected, plan["included_feature_set_ids"])
        )
        assert len(plan["included_feature_set_ids"]) == 4, (
            "a single-pass resolution stops at three feature sets; the fixed point "
            "holds 4, got {}".format(len(plan["included_feature_set_ids"]))
        )

    def test_02_the_three_case_counts_split_the_closure_by_obligation(self):
        """The closure's 39 required cases split into 31 mandatory ones — the
        conditional sets counting as mandatory work — and 8 optional ones.

        PRD (§3.5): "`mandatory_case_count` is that sum restricted to members whose
        `obligation` is `MANDATORY` or `CONDITIONAL` — conditional sets, once in
        scope, are counted as mandatory work."

        Design: Corner/calculations/plan_closure_needs_two_propagation_rounds_to_reach_its_fixed_point
        """
        ctx = _closure_program()

        plan = read_test_plan(ctx.plan_id)

        assert plan["required_case_count"] == 39, (
            "A_CORE 20 plus B_OPT 8 plus C_COND 6 plus D_COND 5, expected "
            "required_case_count 39, got {}".format(plan["required_case_count"])
        )
        assert plan["mandatory_case_count"] == 31, (
            "A_CORE 20 plus the two conditional sets 6 and 5, expected "
            "mandatory_case_count 31, got {}".format(plan["mandatory_case_count"])
        )
        assert plan["optional_case_count"] == 8, (
            "only the declared B_OPT is optional work, expected optional_case_count "
            "8, got {}".format(plan["optional_case_count"])
        )
        assert (
            plan["required_case_count"]
            == plan["mandatory_case_count"] + plan["optional_case_count"]
        ), (
            "required_case_count must equal mandatory plus optional, expected {}, "
            "got {}".format(
                plan["mandatory_case_count"] + plan["optional_case_count"],
                plan["required_case_count"],
            )
        )

    def test_03_undeclared_optional_and_other_device_class_candidates_stay_out(self):
        """The undeclared optional set never enters the closure, and neither do the
        thermostat feature sets — one of which reuses the declared code B_OPT.

        PRD (§3.5): "The candidate pool is every feature set whose
        `specification_id` equals the submission's pinned specification and whose
        `device_type` equals the submission's device class; feature sets of other
        device classes are never included, even when their `feature_code` happens to
        appear in `declared_feature_codes`, and a declared code with no matching
        candidate is simply ignored here because submission creation already refused
        unknown codes."

        Design: Corner/calculations/plan_closure_needs_two_propagation_rounds_to_reach_its_fixed_point
        """
        ctx = _closure_program()

        plan = read_test_plan(ctx.plan_id)

        included = plan["included_feature_set_ids"]
        for excluded_key, why in (
            ("LIGHTING:E_OPT", "an undeclared OPTIONAL set never enters the closure"),
            ("THERMOSTAT:T_CORE", "a THERMOSTAT mandatory set is another device class"),
            ("THERMOSTAT:B_OPT", "the THERMOSTAT set reusing the declared code B_OPT"),
        ):
            assert ctx.feature_set_ids[excluded_key] not in included, (
                "{} — {} must be absent from included_feature_set_ids, got {}".format(
                    excluded_key, why, included
                )
            )
        assert_states(
            plan,
            specification_id=ctx.specification_id,
            device_type="LIGHTING",
            state=PLAN_DRAFT,
            voided_reason=None,
        )
        submission = read_submission(ctx.submission_id)
        assert_cents(
            submission["certification_fee_cents"], 150000, "certification_fee_cents"
        )


class TestDistinctVendorCountIsAMemberCount:
    """A plugfest's quorum counts vendors, not the devices they enter."""

    def test_04_two_devices_from_one_member_leave_the_count_at_one(self):
        """Two participations entered by the same member leave distinct_vendor_count
        at 1, so the lock is refused and the event stays open for registration.

        PRD (§3.7): "Two devices entered by the same member therefore count once,
        because it is a distinct-vendor count and not a participation count."

        Design: Corner/calculations/distinct_vendor_count_counts_members_not_participations
        """
        ctx = _register_both_devices_of_the_first_member(_two_vendor_plugfest_program())

        plugfest = validate_success(
            api_client.get_plugfest(ctx.plugfest_id, ADMIN_HEADERS)
        )
        assert plugfest["distinct_vendor_count"] == 1, (
            "one member entering two devices is one distinct vendor, expected "
            "distinct_vendor_count 1, got {}".format(plugfest["distinct_vendor_count"])
        )

        response = api_client.lock_plugfest(ctx.plugfest_id, headers=ADMIN_HEADERS)
        validate_error(response, ERR_INSUFFICIENT_DISTINCT_VENDORS)

        after = validate_success(api_client.get_plugfest(ctx.plugfest_id, ADMIN_HEADERS))
        assert_states(after, state=PLUGFEST_REGISTRATION_OPEN, locked_at=None)

    def test_05_a_second_member_lifts_the_count_to_exactly_the_minimum(self):
        """One registration by a second member takes distinct_vendor_count to 2, and
        the same lock that was refused now succeeds on exactly the minimum while the
        roster still holds three participations.

        PRD (§3.7): "A `ProgramAdmin` moves it `REGISTRATION_OPEN → LOCKED` only
        when `distinct_vendor_count` is at or above `min_distinct_vendors`; exactly
        the minimum is sufficient, and a shortfall is refused with
        `ERR_INSUFFICIENT_DISTINCT_VENDORS`."

        Design: Corner/calculations/distinct_vendor_count_counts_members_not_participations
        """
        ctx = _register_both_devices_of_the_first_member(_two_vendor_plugfest_program())
        validate_error(
            api_client.lock_plugfest(ctx.plugfest_id, headers=ADMIN_HEADERS),
            ERR_INSUFFICIENT_DISTINCT_VENDORS,
        )

        new_participation(ctx.plugfest_id, ctx.member_2_id, ctx.submission_3["id"])

        before_lock = validate_success(
            api_client.get_plugfest(ctx.plugfest_id, ADMIN_HEADERS)
        )
        assert before_lock["distinct_vendor_count"] == 2, (
            "two members are registered, expected distinct_vendor_count 2, got "
            "{}".format(before_lock["distinct_vendor_count"])
        )

        locked = validate_success(
            api_client.lock_plugfest(ctx.plugfest_id, headers=ADMIN_HEADERS)
        )
        assert locked["state"] == PLUGFEST_LOCKED, (
            "a count equal to min_distinct_vendors is sufficient, expected state "
            "LOCKED, got {}".format(locked["state"])
        )
        assert locked["locked_at"] is not None and same_instant(
            locked["locked_at"], "2026-09-01T00:00:00Z"
        ), (
            "locked_at must be stamped from the logical clock, expected "
            "2026-09-01T00:00:00Z, got {!r}".format(locked["locked_at"])
        )

        rows, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, plugfest_id=ctx.plugfest_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 3, (
            "three participations across two vendors, expected total_count 3, got "
            "{}".format(meta["total_count"])
        )
        assert rows[0]["id"] == ctx.participation_1["id"], (
            "participations list oldest first, expected data[0].id {}, got {}".format(
                ctx.participation_1["id"], rows[0]["id"]
            )
        )


class TestPenaltyBandsAreMarginal:
    """Three cases on one listing, priced at 100, 101 and 1200 impact units."""

    def test_06_the_hundred_and_first_unit_is_priced_in_the_second_band_alone(self):
        """100 units assess 50000 cents and 101 units assess 50300, so the extra unit
        costs 300 rather than repricing the whole quantity.

        PRD (§3.9): "Because the tiering is marginal rather than cliff-edged, 100
        units assess 50000 cents and 101 units assess 50300 cents, not 30300."

        Design: Corner/calculations/penalty_bands_are_marginal_across_the_hundred_and_thousand_breakpoints
        """
        ctx = _three_priced_cases_program()

        assert_cents(
            ctx.case_1["assessment_subtotal_cents"],
            50000,
            "assessment_subtotal_cents at 100 units",
        )
        assert_cents(ctx.case_1["surcharge_cents"], 5000, "surcharge_cents at 100 units")
        assert_cents(
            ctx.case_1["penalty_total_cents"], 55000, "penalty_total_cents at 100 units"
        )

        assert_cents(
            ctx.case_2["assessment_subtotal_cents"],
            50300,
            "assessment_subtotal_cents at 101 units",
        )
        assert_cents(ctx.case_2["surcharge_cents"], 5030, "surcharge_cents at 101 units")
        assert_cents(
            ctx.case_2["penalty_total_cents"], 55330, "penalty_total_cents at 101 units"
        )

        marginal_step = (
            ctx.case_2["assessment_subtotal_cents"]
            - ctx.case_1["assessment_subtotal_cents"]
        )
        assert marginal_step == 300, (
            "the 101st unit alone is priced in the second band, expected a step of "
            "300 cents, got {}".format(marginal_step)
        )

    def test_07_twelve_hundred_units_are_split_across_all_three_bands(self):
        """1200 units assess 350000 cents — 100 at 500, 900 at 300 and 200 at 150 —
        and the security-defect rate takes the surcharge to 122500.

        PRD (§3.9): "The rates are 0.10 for `INTEROP_DEFECT`, 0.35 for
        `SECURITY_DEFECT`, 0.25 for `FALSE_FEATURE_DECLARATION` and 0.00 for
        `IP_WITHDRAWAL`, so an auto-opened intellectual-property case always assesses
        a surcharge of 0."

        Design: Corner/calculations/penalty_bands_are_marginal_across_the_hundred_and_thousand_breakpoints
        """
        ctx = _three_priced_cases_program()

        assert_cents(
            ctx.case_3["assessment_subtotal_cents"],
            350000,
            "assessment_subtotal_cents at 1200 units",
        )
        assert_cents(
            ctx.case_3["surcharge_cents"], 122500, "surcharge_cents at 1200 units"
        )
        assert_cents(
            ctx.case_3["penalty_total_cents"],
            472500,
            "penalty_total_cents at 1200 units",
        )
        assert_penalty(ctx.case_3, 1200, "SECURITY_DEFECT")
        assert (
            ctx.case_3["assessment_subtotal_cents"] + ctx.case_3["surcharge_cents"]
            == ctx.case_3["penalty_total_cents"]
        ), (
            "472500 sits well below the hard cap, so subtotal plus surcharge must "
            "equal the total, expected {}, got {}".format(
                ctx.case_3["assessment_subtotal_cents"] + ctx.case_3["surcharge_cents"],
                ctx.case_3["penalty_total_cents"],
            )
        )

    def test_08_each_case_records_its_filing_and_only_live_ones_are_counted(self):
        """Every case is operator-filed against the same listing, the enforcement
        axis moves without touching visibility, and the two remediated cases drop out
        of the member's open-case tally.

        PRD (§3.9): "Acceptance opens the case in `state` `OPEN`, records
        `opened_by_user_id` as the acting `X-User-ID`, leaves `auto_opened` false,
        `closed_by_user_id` and `remediation_deadline_at` null, prices the assessment,
        moves the listing's `compliance_status` to `UNDER_INVESTIGATION` while leaving
        `publication_status` untouched, and recomputes the member's
        `open_case_count`."

        Design: Corner/calculations/penalty_bands_are_marginal_across_the_hundred_and_thousand_breakpoints
        """
        ctx = _three_priced_cases_program()

        for label, case in (
            ("case 1", ctx.case_1),
            ("case 2", ctx.case_2),
            ("case 3", ctx.case_3),
        ):
            assert case["auto_opened"] is False, (
                "{} was filed by an operator, so auto_opened must be false, got "
                "{!r}".format(label, case["auto_opened"])
            )
            assert case["opened_by_user_id"] == "CO1", (
                "{} must record the acting officer, expected opened_by_user_id CO1, "
                "got {!r}".format(label, case["opened_by_user_id"])
            )

        assert_states(
            read_listing(ctx.listing_id),
            compliance_status=COMPLIANCE_UNDER_INVESTIGATION,
            publication_status=PUB_UNPUBLISHED,
        )

        rows, meta = validate_paginated(
            api_client.list_noncompliance_cases(
                ADMIN_HEADERS, listing_id=ctx.listing_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 3, (
            "three cases were filed against the listing, expected total_count 3, got "
            "{}".format(meta["total_count"])
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[ctx.case_1["id"]]["state"] == CASE_REMEDIATED, (
            "case 1 was walked to REMEDIATED, got {}".format(
                by_id[ctx.case_1["id"]]["state"]
            )
        )
        assert by_id[ctx.case_2["id"]]["state"] == CASE_REMEDIATED, (
            "case 2 was walked to REMEDIATED, got {}".format(
                by_id[ctx.case_2["id"]]["state"]
            )
        )
        assert by_id[ctx.case_3["id"]]["state"] == CASE_OPEN, (
            "case 3 was never advanced, expected OPEN, got {}".format(
                by_id[ctx.case_3["id"]]["state"]
            )
        )

        member = read_member(ctx.member_id)
        assert member["open_case_count"] == 1, (
            "only the OPEN case counts and REMEDIATED does not, expected "
            "open_case_count 1, got {}".format(member["open_case_count"])
        )


class TestCreditLedgerVariantsDifferByTheEscrow:
    """One escrowed submission and one DRAFT sibling, read both ways."""

    def test_09_the_default_read_is_the_available_variant_and_holds_the_invariant(self):
        """Omitting the variant returns AVAILABLE: 1000000 purchased, 150000 escrowed
        and 850000 spendable, which is also the figure persisted on the member.

        PRD (§3.2): "The `AVAILABLE` variant is the default when `variant` is
        omitted; it is the figure persisted on `credit_balance_cents`, and it is the
        figure the first submit compares against the pinned fee, because money
        committed to an in-flight submission is not spendable."

        Design: Corner/calculations/credit_ledger_variants_differ_by_exactly_the_escrowed_submission
        """
        ctx = _escrowed_plus_draft_program()

        assert_cents(
            ctx.submission_a["certification_fee_cents"],
            150000,
            "submission A certification_fee_cents",
        )
        assert_cents(
            ctx.submission_b["certification_fee_cents"],
            135000,
            "submission B certification_fee_cents",
        )

        default_read = read_ledger(ctx.member_id)

        assert default_read["variant"] == "AVAILABLE", (
            "the variant-less read evaluates AVAILABLE, got {!r}".format(
                default_read["variant"]
            )
        )
        assert_cents(default_read["credits_purchased_cents"], 1000000, "credits_purchased_cents")
        assert_cents(default_read["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_cents(default_read["escrowed_credit_cents"], 150000, "escrowed_credit_cents")
        assert_cents(default_read["balance_cents"], 850000, "AVAILABLE balance_cents")
        assert_credit_ledger_invariant(default_read)

        explicit = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert explicit == default_read, (
            "an explicit AVAILABLE read must equal the variant-less read, got {!r} "
            "versus {!r}".format(explicit, default_read)
        )
        assert_cents(
            read_member(ctx.member_id)["credit_balance_cents"],
            850000,
            "persisted credit_balance_cents",
        )

    def test_10_committed_keeps_the_escrow_in_the_balance_and_draft_escrows_nothing(self):
        """On identical stored rows COMMITTED reports 1000000 against AVAILABLE's
        850000 — a difference of exactly the escrowed submission's fee — while the
        DRAFT sibling's 135000 fee moves neither figure.

        PRD (§3.2): "The `COMMITTED` variant, requested explicitly, is the finance
        view of everything the member still owns including money held in escrow: it
        does *not* subtract `escrowed_credit_cents`, so its `balance_cents` is simply
        `credits_purchased_cents` reduced by `credits_consumed_cents`."

        Design: Corner/calculations/credit_ledger_variants_differ_by_exactly_the_escrowed_submission
        """
        ctx = _escrowed_plus_draft_program()

        available = read_ledger(ctx.member_id, variant="AVAILABLE")
        committed = read_ledger(ctx.member_id, variant="COMMITTED")

        assert committed["variant"] == "COMMITTED", (
            "the COMMITTED read must report its own variant, got {!r}".format(
                committed["variant"]
            )
        )
        assert_cents(committed["escrowed_credit_cents"], 150000, "escrowed_credit_cents")
        assert_cents(committed["balance_cents"], 1000000, "COMMITTED balance_cents")
        divergence = committed["balance_cents"] - available["balance_cents"]
        assert divergence == 150000, (
            "the two variants differ by exactly the escrowed submission's fee, "
            "expected 150000, got {}".format(divergence)
        )

        submission_b = read_submission(ctx.submission_b["id"])
        assert_cents(submission_b["fee_escrowed_cents"], 0, "DRAFT fee_escrowed_cents")
        assert_cents(
            available["escrowed_credit_cents"],
            ctx.submission_a["certification_fee_cents"],
            "escrowed_credit_cents against submission A's fee alone",
        )


class TestCancelledSessionsLeaveTheReadinessInputSet:
    """One PASS pair, a later overriding FAIL, and the cancel that voids it."""

    def test_11_a_later_fail_on_the_same_feature_set_overrides_the_earlier_pass(self):
        """Two PASS lines put PROVISIONAL at 85.00 on one counted session; the FAIL
        recorded an hour later on CORE_DIM in a second session becomes that feature
        set's effective outcome and drags the score to 68.34.

        PRD (§3.8): "Within the counted sessions, each feature set has one
        **effective outcome**, being the `outcome` of the latest result line naming
        it."

        Design: Corner/calculations/cancelled_sessions_leave_the_readiness_input_set
        """
        ctx = _two_bench_readiness_program()

        before = read_readiness(ctx.submission_id, variant="PROVISIONAL")

        assert_score(before["score"], "85.00", "PROVISIONAL score on the PASS pair")
        assert before["mandatory_passed_cases"] == 30, (
            "both mandatory feature sets pass, expected 30 mandatory cases, "
            "got {}".format(before["mandatory_passed_cases"])
        )
        assert before["counted_session_count"] == 1, (
            "only the started session counts so far, expected 1, got {}".format(
                before["counted_session_count"]
            )
        )

        _record_the_overriding_fail(ctx)
        after = read_readiness(ctx.submission_id, variant="PROVISIONAL")

        assert_score(after["score"], "68.34", "PROVISIONAL score after the later FAIL")
        assert after["mandatory_passed_cases"] == 20, (
            "CORE_DIM's 10 cases drop out when its effective outcome turns FAIL, "
            "expected 20, got {}".format(after["mandatory_passed_cases"])
        )
        assert after["counted_session_count"] == 2, (
            "both sessions are now IN_PROGRESS, expected 2 counted, got {}".format(
                after["counted_session_count"]
            )
        )

    def test_12_cancelling_the_failing_session_restores_the_earlier_pass(self):
        """Cancelling the session that carried the FAIL removes its lines from the
        input set, so CORE_DIM's 09:00 PASS is effective again, PROVISIONAL returns
        to 85.00, and the next result line rewrites the persisted figure.

        PRD (§3.8): "Sessions in `SCHEDULED` or `CANCELLED` never participate in
        either variant, which has a consequence worth naming: cancelling a session
        that carried failing lines raises both scores, because the failures leave the
        counted population entirely."

        Design: Corner/calculations/cancelled_sessions_leave_the_readiness_input_set
        """
        ctx = _two_bench_readiness_program()
        _record_the_overriding_fail(ctx)
        assert_score(
            read_readiness(ctx.submission_id, variant="PROVISIONAL")["score"],
            "68.34",
            "PROVISIONAL score while the FAIL is live",
        )

        _cancel_the_second_session(ctx)
        restored = read_readiness(ctx.submission_id, variant="PROVISIONAL")

        assert_score(restored["score"], "85.00", "PROVISIONAL score after the cancel")
        assert restored["mandatory_passed_cases"] == 30, (
            "the cancelled session's FAIL no longer suppresses CORE_DIM, expected 30 "
            "mandatory cases, got {}".format(restored["mandatory_passed_cases"])
        )
        assert restored["counted_session_count"] == 1, (
            "the CANCELLED session leaves the counted population, expected 1, "
            "got {}".format(restored["counted_session_count"])
        )
        assert_score(
            read_submission(ctx.submission_id)["provisional_readiness_score"],
            "85.00",
            "persisted provisional_readiness_score",
        )

    def test_13_final_sees_no_complete_session_and_the_bench_minutes_are_released(self):
        """At the same moment FINAL counts nothing, because neither session is
        COMPLETE, so it scores 35.00 from the vacuous optional and full timeliness
        components alone, and the cancelled session's 240 bench minutes are returned.

        PRD (§3.8): "Which sessions count is the first point of divergence: the
        `PROVISIONAL` variant counts sessions whose `state` is `IN_PROGRESS` or
        `COMPLETE`, while the `FINAL` variant counts only those whose `state` is
        `COMPLETE`."

        Design: Corner/calculations/cancelled_sessions_leave_the_readiness_input_set
        """
        ctx = _two_bench_readiness_program()
        _record_the_overriding_fail(ctx)
        _cancel_the_second_session(ctx)

        final = read_readiness(ctx.submission_id, variant="FINAL")

        assert_score(final["score"], "35.00", "FINAL readiness score")
        assert final["counted_session_count"] == 0, (
            "no session has reached COMPLETE, expected 0 counted under FINAL, "
            "got {}".format(final["counted_session_count"])
        )
        assert final["late_session_count"] == 0, (
            "nothing can be late when nothing is counted, expected 0, got {}".format(
                final["late_session_count"]
            )
        )
        assert final["mandatory_passed_cases"] == 0, (
            "FINAL reads no lines at all, expected 0 mandatory cases, got {}".format(
                final["mandatory_passed_cases"]
            )
        )
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 240)
