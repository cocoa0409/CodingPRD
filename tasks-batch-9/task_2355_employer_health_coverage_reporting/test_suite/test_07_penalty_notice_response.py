"""Answering a proposed penalty assessment.

The recomputation prices section (a) against the thirty-employee exclusion,
prices section (b) only for employee-months whose month did not survive as an
(a) month, and then splits both the exclusion units and the recalculated cents
across the group's active members. Three further behaviours are covered: the
gate that a statement named by employee-level evidence must already have reached
the agency, the compliance control that outranks the response window, and the
allocation reset that conserves cents.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_allocation_conserved,
    assert_fields,
    assert_penalty_evidence,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CO_1 = TEST_USERS["compliance_officer"]
CO_2 = TEST_USERS["compliance_officer_2"]

# The recomputation of the two-member world below, worked from the season's
# statutory defaults: the surviving asserted (a) month prices at
# (41 - 30) * 24700, and two of the four asserted employee-months survive
# section (b) at 37000 each.
A_MONTH_PENALTY_CENTS = 271700
B_MONTH_PENALTY_CENTS = 74000
RECALCULATED_AMOUNT_CENTS = 345700
MEMBER_A_FT_MONTHS = 360
MEMBER_B_FT_MONTHS = 132
MEMBER_A_PENALTY_CENTS = 252952
MEMBER_B_PENALTY_CENTS = 92748
MEMBER_A_EXCLUSION_EMPLOYEES = 22
MEMBER_B_EXCLUSION_EMPLOYEES = 8

SINGLE_MEMBER_FT_MONTHS = 492


# ---------------------------------------------------------------------------
# Shared world builders — composed from test_helpers.fixtures only
# ---------------------------------------------------------------------------
def _determined_group_with_two_members(api, group_name, ein_a, ein_b):
    """Season → group → two ACTIVE members → twelve prior-year headcount months
    each (which aggregate over the fifty full-time-equivalent threshold) →
    twelve reporting-year months of 30 and 11 full-time employees → aggregated
    determination, which is what freezes each member's
    ``reporting_year_ft_months`` allocation weight.
    """
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"], name=group_name)
    member_a = fixtures.create_group_member(
        api, group["id"], ein=ein_a, legal_name="Ironwood Main", ownership_pct=70
    )
    member_b = fixtures.create_group_member(
        api, group["id"], ein=ein_b, legal_name="Ironwood Annex", ownership_pct=30
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        count_year="PRIOR_YEAR",
        full_time_employee_count=20,
        part_time_hours_total=0,
        total_employee_count=22,
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        count_year="REPORTING_YEAR",
        full_time_employee_count=30,
        part_time_hours_total=0,
        total_employee_count=34,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        count_year="REPORTING_YEAR",
        full_time_employee_count=11,
        part_time_hours_total=0,
        total_employee_count=12,
    )
    fixtures.run_ale_determination(api, group["id"])
    return {
        "season": season,
        "group": group,
        "member_a": member_a,
        "member_b": member_b,
    }


def _determined_group_with_single_member(api, group_name, ein, legal_name):
    """The same prelude for one ACTIVE member whose twelve reporting-year months
    each carry 41 full-time employees."""
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"], name=group_name)
    member = fixtures.create_group_member(
        api, group["id"], ein=ein, legal_name=legal_name, ownership_pct=100
    )
    fixtures.record_headcounts(
        api,
        member["id"],
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member["id"],
        count_year="REPORTING_YEAR",
        full_time_employee_count=41,
        part_time_hours_total=0,
        total_employee_count=45,
    )
    fixtures.run_ale_determination(api, group["id"])
    return {"season": season, "group": group, "member": member}


def _salaried_employee(api, group_member_id, full_name, ssn_last4):
    return fixtures.create_employee(
        api,
        group_member_id,
        full_name=full_name,
        ssn_last4=ssn_last4,
        is_hourly=False,
        monthly_salary_cents=400000,
        hourly_rate_cents=factories._UNSET,
    )


def _two_member_notice_ready_for_recompute(api, notice_number, group_name,
                                           ein_a, ein_b, receipt_id):
    """The two-member world plus employee E1 of member A whose statement has
    travelled to FILED_ACCEPTED through an accepted submission, a notice
    asserting (a) months 1 and 2 and four employee-months of E1, and two pieces
    of evidence filed in order: a minimum-essential-coverage proof for month 2,
    then a full-time dispute for E1's month 5.
    """
    ctx = _determined_group_with_two_members(api, group_name, ein_a, ein_b)
    employee = _salaried_employee(api, ctx["member_a"]["id"], "Owen Pratt", "3003")
    form = fixtures.generate_form(api, employee["id"])
    fixtures.accepted_transmittal_with_forms(
        api, ctx["member_a"]["id"], [form["id"]], receipt_id=receipt_id
    )
    notice = fixtures.create_penalty_notice(
        api,
        ctx["group"]["id"],
        notice_number,
        asserted_a_months=[1, 2],
        asserted_b_employee_months=[
            factories.asserted_b_pair(employee["id"], month)
            for month in (1, 5, 6, 7)
        ],
        proposed_amount_cents=1000000,
    )
    ctx["employee"] = employee
    ctx["form"] = form
    ctx["notice"] = notice
    ctx["mec_proof"] = fixtures.file_evidence(
        api, notice["id"], "MEC_OFFER_PROOF", 2, document_ref="DOC-MEC-M2"
    )
    ctx["ft_dispute"] = fixtures.file_evidence(
        api,
        notice["id"],
        "FT_STATUS_DISPUTE",
        5,
        document_ref="DOC-FT-M5",
        employee_id=employee["id"],
    )
    return ctx


def _recompute(api, notice_id, headers=CO_1):
    response = api.recompute_penalty_notice(notice_id, headers)
    return validate_success(response, 200)


# ---------------------------------------------------------------------------
# The recomputation formula
# ---------------------------------------------------------------------------
class TestPenaltyRecomputationFormula:
    def test_section_a_prices_surviving_month_against_the_exclusion_floor(self, api):
        """PRD §3.9: "The two monthly rates come first: the section (a) monthly
        amount is the season's `penalty_a_annual_cents` divided by 12 and truncated
        to whole cents, and the section (b) monthly amount is `penalty_b_annual_cents`
        divided by 12 and truncated the same way."
        PRD §3.9: "**Step 2 recomputes the group's monthly full-time counts, and only
        after step 1 has run.** For each month the count is the sum of
        `full_time_employee_count` over the reporting-year headcount rows of the
        group's `ACTIVE` members, less the full-time reductions step 1 recorded for
        that month."
        PRD §3.9: "**Step 3 prices section (a).** For each month still surviving in
        the asserted month set, the charge is the recomputed group full-time count for
        that month less the thirty-employee exclusion — floored at zero, so a month
        whose count is at or below thirty contributes nothing — multiplied by the
        section (a) monthly amount."
        PRD §3.9: "Their sum is `a_month_penalty_cents`."

        Design: Difficulty/combinatorial_formula/penalty_a_exclusion_floor_and_ab_month_mutual_exclusion
        """
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0007", "Ironwood Group", "666666661", "666666662",
            "AIR-2026-0001",
        )

        recomputed = _recompute(api, ctx["notice"]["id"])

        assert recomputed["status"] == "RECOMPUTED", (
            f"recompute must move the notice to RECOMPUTED, got {recomputed['status']}"
        )
        assert recomputed["a_month_penalty_cents"] == A_MONTH_PENALTY_CENTS, (
            "the one surviving asserted (a) month must price at "
            f"{A_MONTH_PENALTY_CENTS} cents, got {recomputed['a_month_penalty_cents']}"
        )

    def test_section_b_drops_employee_months_whose_month_survived_as_an_a_month(self, api):
        """PRD §3.9: "**Step 4 prices section (b).** The two sections are mutually
        exclusive per month, so any surviving employee-month pair whose month also
        survives in the asserted month set is dropped here."
        PRD §3.9: "The remaining pairs are counted and multiplied by the section (b)
        monthly amount to give `b_month_penalty_cents`, which charges per
        employee-month at the higher rate but only for the employees the agency
        actually named."
        PRD §3.9: "`recalculated_amount_cents` is the sum of the two components."

        Design: Difficulty/combinatorial_formula/penalty_a_exclusion_floor_and_ab_month_mutual_exclusion
        """
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0007", "Ironwood Group", "666666661", "666666662",
            "AIR-2026-0001",
        )

        recomputed = _recompute(api, ctx["notice"]["id"])

        assert recomputed["b_month_penalty_cents"] == B_MONTH_PENALTY_CENTS, (
            "only the two employee-months surviving the per-month mutual exclusion "
            f"may be charged, expected {B_MONTH_PENALTY_CENTS} cents, got "
            f"{recomputed['b_month_penalty_cents']}"
        )
        assert recomputed["recalculated_amount_cents"] == RECALCULATED_AMOUNT_CENTS, (
            f"expected recalculated_amount_cents {RECALCULATED_AMOUNT_CENTS}, got "
            f"{recomputed['recalculated_amount_cents']}"
        )

    def test_evidence_is_applied_in_created_at_order(self, api):
        """PRD §3.9: "**Step 1 applies the evidence in `created_at` ascending
        order**, walking two working sets that begin as the asserted month list and
        the asserted employee-month pairs."
        PRD §3.9: "A `MEC_OFFER_PROOF` whose month is still in the month set removes
        that month and is marked `applied` true."
        PRD §3.9: "An `FT_STATUS_DISPUTE` whose employee-month pair is still in the
        pair set removes that pair, is marked `applied` true, and additionally records
        one full-time reduction for its month."
        PRD §3.9: "`applied_evidence_count` and `recomputed_at` are written at the
        end."

        Design: Difficulty/combinatorial_formula/penalty_a_exclusion_floor_and_ab_month_mutual_exclusion
        """
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0007", "Ironwood Group", "666666661", "666666662",
            "AIR-2026-0001",
        )

        recomputed = _recompute(api, ctx["notice"]["id"])

        assert recomputed["applied_evidence_count"] == 2, (
            "both pieces of evidence still had their target in the working sets, so "
            f"applied_evidence_count must be 2, got {recomputed['applied_evidence_count']}"
        )
        mec_proof = validate_success(
            api.get_penalty_evidence(ctx["mec_proof"]["id"], CO_1)
        )
        assert_penalty_evidence(mec_proof, evidence_type="MEC_OFFER_PROOF",
                                month=2, applied=True)
        ft_dispute = validate_success(
            api.get_penalty_evidence(ctx["ft_dispute"]["id"], CO_1)
        )
        assert_penalty_evidence(ft_dispute, evidence_type="FT_STATUS_DISPUTE",
                                month=5, applied=True)

    def test_recalculated_cents_split_by_reporting_year_ft_months(self, api):
        """PRD §3.2: "A determination that lands on `DETERMINED_ALE` additionally
        recomputes `reporting_year_ft_months` for every `ACTIVE` member as the sum
        over months 1 through 12 of that member's reporting-year full-time employee
        counts — the weight both later allocations divide by."
        PRD §3.9: "**Step 6 allocates the recalculated cents** the same way, writing
        each member's `allocated_penalty_cents`, with the whole leftover remainder
        going to the member with the largest weight."
        PRD §3.9: "`allocated_total_cents` is the sum of those member allocations and
        equals `recalculated_amount_cents`, leaving `unallocated_amount_cents` at
        zero — that field is the conserved-quantity slack, and its being zero is what
        proves the allocation settled."
        PRD §2.9: "Cents are distributed the same way except that the entire leftover
        remainder goes to the single member with the largest weight, ties broken by
        the earlier member `created_at`, again never by id."

        Design: Difficulty/combinatorial_formula/penalty_a_exclusion_floor_and_ab_month_mutual_exclusion
        """
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0007", "Ironwood Group", "666666661", "666666662",
            "AIR-2026-0001",
        )

        recomputed = _recompute(api, ctx["notice"]["id"])

        member_a = fixtures.read_member(api, ctx["member_a"]["id"])
        member_b = fixtures.read_member(api, ctx["member_b"]["id"])
        assert_fields(member_a, reporting_year_ft_months=MEMBER_A_FT_MONTHS)
        assert_fields(member_b, reporting_year_ft_months=MEMBER_B_FT_MONTHS)
        assert member_a["allocated_penalty_cents"] == MEMBER_A_PENALTY_CENTS, (
            "the member with the largest weight takes the whole leftover remainder, "
            f"so expected {MEMBER_A_PENALTY_CENTS} cents, got "
            f"{member_a['allocated_penalty_cents']}"
        )
        assert member_b["allocated_penalty_cents"] == MEMBER_B_PENALTY_CENTS, (
            f"expected {MEMBER_B_PENALTY_CENTS} cents for the smaller member, got "
            f"{member_b['allocated_penalty_cents']}"
        )
        assert_fields(
            recomputed,
            allocated_total_cents=RECALCULATED_AMOUNT_CENTS,
            unallocated_amount_cents=0,
        )
        assert_allocation_conserved(recomputed, [member_a, member_b])

    def test_thirty_employee_exclusion_split_by_largest_remainder(self, api):
        """PRD §3.9: "**Step 5 allocates the thirty-employee exclusion** across the
        group's `ACTIVE` members using the largest-remainder rule of §2.9 with
        `reporting_year_ft_months` as the weight, writing each member's
        `allocated_exclusion_employees` so the units always total exactly thirty."
        PRD §2.9: "The thirty-employee exclusion is distributed by the
        largest-remainder rule: each member first receives the whole-employee floor
        of its weighted share, and the units still undistributed are handed out one
        at a time to the members with the largest fractional shares, ties broken by
        the larger weight and then by the earlier member `created_at` — never by id."

        Design: Difficulty/combinatorial_formula/penalty_a_exclusion_floor_and_ab_month_mutual_exclusion
        """
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0007", "Ironwood Group", "666666661", "666666662",
            "AIR-2026-0001",
        )

        _recompute(api, ctx["notice"]["id"])

        member_a = fixtures.read_member(api, ctx["member_a"]["id"])
        member_b = fixtures.read_member(api, ctx["member_b"]["id"])
        assert member_a["allocated_exclusion_employees"] == MEMBER_A_EXCLUSION_EMPLOYEES, (
            f"expected {MEMBER_A_EXCLUSION_EMPLOYEES} exclusion employees for the "
            f"heavier member, got {member_a['allocated_exclusion_employees']}"
        )
        assert member_b["allocated_exclusion_employees"] == MEMBER_B_EXCLUSION_EMPLOYEES, (
            f"expected {MEMBER_B_EXCLUSION_EMPLOYEES} exclusion employees for the "
            f"lighter member, got {member_b['allocated_exclusion_employees']}"
        )
        total = (
            member_a["allocated_exclusion_employees"]
            + member_b["allocated_exclusion_employees"]
        )
        assert total == 30, f"the exclusion units must total exactly thirty, got {total}"


# ---------------------------------------------------------------------------
# The gate on statements named by employee-level evidence
# ---------------------------------------------------------------------------
class TestRecomputeRequiresFiledStatements:
    @staticmethod
    def _notice_naming_an_unfiled_statement(api):
        ctx = _determined_group_with_single_member(
            api, "Evidence Gate Group", "212121212", "Evidence Gate Co"
        )
        employee = _salaried_employee(api, ctx["member"]["id"], "Elio Vance", "1717")
        form = fixtures.generate_form(api, employee["id"])
        notice = fixtures.create_penalty_notice(
            api,
            ctx["group"]["id"],
            "226J-2026-0012",
            asserted_a_months=[],
            asserted_b_employee_months=[factories.asserted_b_pair(employee["id"], 4)],
            proposed_amount_cents=37000,
        )
        ctx["employee"] = employee
        ctx["form"] = form
        ctx["notice"] = notice
        ctx["evidence"] = fixtures.file_evidence(
            api,
            notice["id"],
            "FT_STATUS_DISPUTE",
            4,
            document_ref="DOC-FT-M4",
            employee_id=employee["id"],
        )
        return ctx

    def test_recompute_rejected_while_the_named_statement_is_unfiled(self, api):
        """PRD §3.9: "Recomputation moves `EVIDENCE_GATHERING` → `RECOMPUTED`, needs
        at least one piece of evidence, and needs every statement named by an
        `FT_STATUS_DISPUTE` or `OFFER_PROOF` row to have reached the agency — a filing
        dimension of `FILED_ACCEPTED`, `FILED_WITH_ERRORS` or `CORRECTION_DRAFTED` —
        or it is refused with `ERR_EVIDENCE_FORM_NOT_FILED`."
        PRD §3.9: "The officer then files **PenaltyEvidence** against the notice,
        which moves it from `RECEIVED` to `EVIDENCE_GATHERING` (and is also accepted
        while already `EVIDENCE_GATHERING` or `RECOMPUTED`)."

        Design: Difficulty/cross_entity_state_dependency/penalty_recompute_requires_filed_form_for_named_evidence
        """
        ctx = self._notice_naming_an_unfiled_statement(api)

        response = api.recompute_penalty_notice(ctx["notice"]["id"], CO_2)

        validate_error(response, ApiErrorId.ERR_EVIDENCE_FORM_NOT_FILED, 409)
        notice = fixtures.read_notice(api, ctx["notice"]["id"])
        assert notice["status"] == "EVIDENCE_GATHERING", (
            "a refused recompute must leave the notice in EVIDENCE_GATHERING, got "
            f"{notice['status']}"
        )
        assert_fields(notice, recalculated_amount_cents=None, recomputed_at=None)

    def test_recompute_succeeds_once_the_named_statement_is_filed_accepted(self, api):
        """PRD §3.9: "Recomputation moves `EVIDENCE_GATHERING` → `RECOMPUTED`, needs
        at least one piece of evidence, and needs every statement named by an
        `FT_STATUS_DISPUTE` or `OFFER_PROOF` row to have reached the agency — a filing
        dimension of `FILED_ACCEPTED`, `FILED_WITH_ERRORS` or `CORRECTION_DRAFTED` —
        or it is refused with `ERR_EVIDENCE_FORM_NOT_FILED`."
        PRD §3.8: "A clean acceptance requires the `errors` array to be empty; it
        records the receipt identifier, moves every attached statement
        `PENDING_FILING` → `FILED_ACCEPTED`, and clears the member's
        `open_transmittal_id`."

        Design: Difficulty/cross_entity_state_dependency/penalty_recompute_requires_filed_form_for_named_evidence
        """
        ctx = self._notice_naming_an_unfiled_statement(api)
        validate_error(
            api.recompute_penalty_notice(ctx["notice"]["id"], CO_2),
            ApiErrorId.ERR_EVIDENCE_FORM_NOT_FILED,
            409,
        )

        fixtures.accepted_transmittal_with_forms(
            api, ctx["member"]["id"], [ctx["form"]["id"]], receipt_id="AIR-2026-0005"
        )

        form = fixtures.read_form(api, ctx["form"]["id"])
        assert form["filing_status"] == "FILED_ACCEPTED", (
            "a clean agency acceptance must move the attached statement to "
            f"FILED_ACCEPTED, got {form['filing_status']}"
        )
        recomputed = _recompute(api, ctx["notice"]["id"], CO_2)
        assert recomputed["status"] == "RECOMPUTED", (
            "the same recompute must succeed once the named statement has reached "
            f"the agency, got {recomputed['status']}"
        )

    def test_recompute_with_no_surviving_targets_prices_at_zero(self, api):
        """PRD §3.9: "An `FT_STATUS_DISPUTE` whose employee-month pair is still in the
        pair set removes that pair, is marked `applied` true, and additionally records
        one full-time reduction for its month."
        PRD §3.9: "**Step 4 prices section (b).** The two sections are mutually
        exclusive per month, so any surviving employee-month pair whose month also
        survives in the asserted month set is dropped here."
        PRD §3.9: "`recalculated_amount_cents` is the sum of the two components."
        PRD §3.9: "**Step 5 allocates the thirty-employee exclusion** across the
        group's `ACTIVE` members using the largest-remainder rule of §2.9 with
        `reporting_year_ft_months` as the weight, writing each member's
        `allocated_exclusion_employees` so the units always total exactly thirty."

        Design: Difficulty/cross_entity_state_dependency/penalty_recompute_requires_filed_form_for_named_evidence
        """
        ctx = self._notice_naming_an_unfiled_statement(api)
        fixtures.accepted_transmittal_with_forms(
            api, ctx["member"]["id"], [ctx["form"]["id"]], receipt_id="AIR-2026-0005"
        )

        recomputed = _recompute(api, ctx["notice"]["id"], CO_2)

        assert_fields(
            recomputed,
            a_month_penalty_cents=0,
            b_month_penalty_cents=0,
            recalculated_amount_cents=0,
            applied_evidence_count=1,
            unallocated_amount_cents=0,
        )
        evidence = validate_success(
            api.get_penalty_evidence(ctx["evidence"]["id"], CO_1)
        )
        assert_penalty_evidence(evidence, evidence_type="FT_STATUS_DISPUTE",
                                month=4, applied=True)
        member = fixtures.read_member(api, ctx["member"]["id"])
        assert_fields(
            member,
            reporting_year_ft_months=SINGLE_MEMBER_FT_MONTHS,
            allocated_penalty_cents=0,
            allocated_exclusion_employees=30,
        )


# ---------------------------------------------------------------------------
# Segregation of duties outranks the response window
# ---------------------------------------------------------------------------
class TestSubmitResponseSegregationOfDuties:
    @staticmethod
    def _recomputed_notice_past_its_due_date(api):
        """One member, a notice asserting (a) month 1 only, evidence filed and the
        recompute run by the same officer, and then the logical clock moved past
        the notice's ``response_due_date``."""
        ctx = _determined_group_with_single_member(
            api, "Priority Pair B Group", "131313131", "Priority Pair B Co"
        )
        notice = fixtures.create_penalty_notice(
            api,
            ctx["group"]["id"],
            "226J-2026-0011",
            asserted_a_months=[1],
            asserted_b_employee_months=[],
            proposed_amount_cents=271700,
        )
        fixtures.file_evidence(
            api, notice["id"], "MEC_OFFER_PROOF", 1, document_ref="DOC-MEC-M1",
            headers=CO_1,
        )
        ctx["notice"] = notice
        ctx["recomputed"] = fixtures.recompute_notice(api, notice["id"], headers=CO_1)
        fixtures.set_clock(api, "2027-07-15T00:00:00Z")
        return ctx

    def test_last_evidence_user_submitting_past_due_date_gets_segregation_of_duties(self, api):
        """PRD §2.7: "The user who most recently filed evidence on a penalty notice
        may not be the user who submits the response: on submission, `X-User-ID` must
        differ from that notice's `last_evidence_user_id`."
        PRD §2.7: "All three violations answer `ERR_SEGREGATION_OF_DUTIES` with HTTP
        403, and because they sit at rung 23 they are reported ahead of the furnishing
        window, the notice response window and every constraint below them."
        PRD §3.9: "Submitting the response moves `RECOMPUTED` → `RESPONSE_SUBMITTED`.
        It requires a non-null `recalculated_amount_cents`, an
        `unallocated_amount_cents` of exactly zero (otherwise
        `ERR_ALLOCATION_NOT_SETTLED`), a logical clock date no later than the
        `response_due_date` — the due date itself is still inside the window — and an
        acting user who is not the notice's `last_evidence_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_notice_window_rejected
        """
        ctx = self._recomputed_notice_past_its_due_date(api)

        response = api.submit_penalty_response(ctx["notice"]["id"], CO_1)

        error = validate_error(
            response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403
        )
        assert error["error_id"] != ApiErrorId.ERR_NOTICE_RESPONSE_WINDOW_CLOSED, (
            "segregation of duties must be reported ahead of the closed notice "
            "response window"
        )

    def test_refused_submission_leaves_the_notice_recomputed_and_unsubmitted(self, api):
        """PRD §2.7: "The user who most recently filed evidence on a penalty notice
        may not be the user who submits the response: on submission, `X-User-ID` must
        differ from that notice's `last_evidence_user_id`."
        PRD §3.9: "Each filing increments `evidence_count`, records
        `filed_by_user_id` on the row and `last_evidence_user_id` on the notice, and
        starts life with `applied` false."
        PRD §3.9: "Success stamps `response_submitted_at` and
        `response_submitted_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_notice_window_rejected
        """
        ctx = self._recomputed_notice_past_its_due_date(api)

        validate_error(
            api.submit_penalty_response(ctx["notice"]["id"], CO_1),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        notice = fixtures.read_notice(api, ctx["notice"]["id"])
        assert notice["status"] == "RECOMPUTED", (
            "a refused submission must leave the notice in RECOMPUTED, got "
            f"{notice['status']}"
        )
        assert_fields(
            notice,
            response_submitted_at=None,
            response_submitted_by_user_id=None,
            last_evidence_user_id="co-1",
            a_month_penalty_cents=0,
            b_month_penalty_cents=0,
            recalculated_amount_cents=0,
        )


# ---------------------------------------------------------------------------
# Resetting the allocation conserves cents
# ---------------------------------------------------------------------------
class TestAllocationReset:
    @staticmethod
    def _recomputed_two_member_notice(api):
        ctx = _two_member_notice_ready_for_recompute(
            api, "226J-2026-0013", "Reset Invariant Group", "252525251",
            "252525252", "AIR-2026-0006",
        )
        ctx["recomputed"] = fixtures.recompute_notice(api, ctx["notice"]["id"])
        return ctx

    def test_reset_moves_the_whole_recalculated_amount_to_unallocated(self, api):
        """PRD §3.9: "An officer who wants to redo the split can reset the allocation,
        a compensating action for step 6 alone: it requires the notice to be
        `RECOMPUTED` with `allocated_total_cents` above zero, zeroes every `ACTIVE`
        member's `allocated_penalty_cents`, sets `allocated_total_cents` to 0 and
        moves the whole `recalculated_amount_cents` into `unallocated_amount_cents`."
        PRD §3.9: "The notice stays `RECOMPUTED`; the conserved quantity is cents."

        Design: Difficulty/compensating_invariant/allocation_reset_conserves_recalculated_cents
        """
        ctx = self._recomputed_two_member_notice(api)
        assert ctx["recomputed"]["allocated_total_cents"] == RECALCULATED_AMOUNT_CENTS

        reset = validate_success(
            api.reset_penalty_allocation(ctx["notice"]["id"], CO_1), 200
        )

        assert_fields(
            reset,
            status="RECOMPUTED",
            recalculated_amount_cents=RECALCULATED_AMOUNT_CENTS,
            allocated_total_cents=0,
            unallocated_amount_cents=RECALCULATED_AMOUNT_CENTS,
        )

    def test_reset_zeroes_member_allocations_and_conserves_cents(self, api):
        """PRD §3.9: "An officer who wants to redo the split can reset the allocation,
        a compensating action for step 6 alone: it requires the notice to be
        `RECOMPUTED` with `allocated_total_cents` above zero, zeroes every `ACTIVE`
        member's `allocated_penalty_cents`, sets `allocated_total_cents` to 0 and
        moves the whole `recalculated_amount_cents` into `unallocated_amount_cents`."
        PRD §3.9: "`allocated_total_cents` is the sum of those member allocations and
        equals `recalculated_amount_cents`, leaving `unallocated_amount_cents` at
        zero — that field is the conserved-quantity slack, and its being zero is what
        proves the allocation settled."

        Design: Difficulty/compensating_invariant/allocation_reset_conserves_recalculated_cents
        """
        ctx = self._recomputed_two_member_notice(api)
        before_a = fixtures.read_member(api, ctx["member_a"]["id"])
        before_b = fixtures.read_member(api, ctx["member_b"]["id"])
        assert_allocation_conserved(ctx["recomputed"], [before_a, before_b])

        fixtures.reset_allocation(api, ctx["notice"]["id"])

        notice = fixtures.read_notice(api, ctx["notice"]["id"])
        member_a = fixtures.read_member(api, ctx["member_a"]["id"])
        member_b = fixtures.read_member(api, ctx["member_b"]["id"])
        assert member_a["allocated_penalty_cents"] == 0, (
            "the reset must zero every active member's allocated_penalty_cents, got "
            f"{member_a['allocated_penalty_cents']}"
        )
        assert member_b["allocated_penalty_cents"] == 0, (
            "the reset must zero every active member's allocated_penalty_cents, got "
            f"{member_b['allocated_penalty_cents']}"
        )
        conserved = (
            notice["unallocated_amount_cents"]
            + member_a["allocated_penalty_cents"]
            + member_b["allocated_penalty_cents"]
        )
        assert conserved == RECALCULATED_AMOUNT_CENTS, (
            "cents are conserved across the reset: unallocated plus the member "
            f"allocations must still be {RECALCULATED_AMOUNT_CENTS}, got {conserved}"
        )
        assert_allocation_conserved(notice, [member_a, member_b])

    def test_reset_leaves_the_exclusion_split_and_the_priced_components(self, api):
        """PRD §3.9: "An officer who wants to redo the split can reset the allocation,
        a compensating action for step 6 alone: it requires the notice to be
        `RECOMPUTED` with `allocated_total_cents` above zero, zeroes every `ACTIVE`
        member's `allocated_penalty_cents`, sets `allocated_total_cents` to 0 and
        moves the whole `recalculated_amount_cents` into `unallocated_amount_cents`."
        PRD §3.9: "**Step 5 allocates the thirty-employee exclusion** across the
        group's `ACTIVE` members using the largest-remainder rule of §2.9 with
        `reporting_year_ft_months` as the weight, writing each member's
        `allocated_exclusion_employees` so the units always total exactly thirty."

        Design: Difficulty/compensating_invariant/allocation_reset_conserves_recalculated_cents
        """
        ctx = self._recomputed_two_member_notice(api)

        fixtures.reset_allocation(api, ctx["notice"]["id"])

        member_a = fixtures.read_member(api, ctx["member_a"]["id"])
        member_b = fixtures.read_member(api, ctx["member_b"]["id"])
        assert_fields(
            member_a, allocated_exclusion_employees=MEMBER_A_EXCLUSION_EMPLOYEES
        )
        assert_fields(
            member_b, allocated_exclusion_employees=MEMBER_B_EXCLUSION_EMPLOYEES
        )
        notice = fixtures.read_notice(api, ctx["notice"]["id"])
        assert_fields(
            notice,
            a_month_penalty_cents=A_MONTH_PENALTY_CENTS,
            b_month_penalty_cents=B_MONTH_PENALTY_CENTS,
        )
