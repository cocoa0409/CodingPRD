"""The tier-one ceiling, the finalization gate, and the money identity.

Covers the inclusive 2500000-cent bracket line probed from both variants, the
set-shaped dependency that blocks a premature finalization, and the ratcheted
conservation identity across an amendment and its reversal.
"""
from test_helpers import (
    ApiErrorId,
    accept_use_report,
    amend_report_payload,
    authorize_guide,
    create_qualified_guide,
    current_permit_version,
    finalize_fee_assessment,
    list_use_reports,
    pay_fee_assessment,
    read_permit,
    read_use_report,
    setup_issued_permit,
    sole_fee_assessment,
    trip_use_report_payload,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]


def _reporting_permit(clock="2027-09-20T00:00:00Z", area_overrides=None,
                      outfitter_overrides=None):
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        area_overrides=area_overrides,
        outfitter_overrides=outfitter_overrides,
        clock=clock,
    )
    guide = create_qualified_guide(context["outfitter"]["id"])
    authorize_guide(context["permit"]["id"], guide["id"], context["outfitter"]["id"])
    assert read_permit(context["permit"]["id"])["authorized_client_capacity_total"] == 8
    return context


def _file(context, start, end, days, gross, deductions=0):
    return validate_success(
        api_client.create_trip_use_report(
            context["permit"]["id"],
            trip_use_report_payload(
                period_start_date=start,
                period_end_date=end,
                service_days_used=days,
                client_count=8,
                gross_revenue_cents=gross,
                allowable_deductions_cents=deductions,
            ),
            context["holder_headers"],
        ),
        201,
    )


def _file_and_accept(context, start, end, days, gross, deductions=0):
    return accept_use_report(_file(context, start, end, days, gross, deductions)["id"])


def _amend(context, report_id, **overrides):
    return api_client.amend_trip_use_report(
        report_id,
        amend_report_payload(
            current_permit_version(context["permit"]["id"]), **overrides
        ),
        context["holder_headers"],
    )


def _identity_holds(assessment):
    return (
        assessment["assessed_fee_cents"] + assessment["credit_balance_cents"]
        == assessment["paid_to_date_cents"] + assessment["balance_due_cents"]
    )


def test_the_tier_one_ceiling_is_inclusive_and_one_cent_past_it_costs_a_thousand():
    """PRD §3.7: "Three graduated brackets apply when the permit's `fee_schedule_code` is
    `GRADUATED`: 300 basis points on the portion up to 2500000 cents, 400 basis points on the
    portion above that up to 10000000 cents, and 500 basis points above that."
    PRD §3.7: "for each report, assigns `applied_rate_bp` from the bracket that the cumulative
    total of *strictly earlier* reports falls into — so a report is charged entirely at one rate,
    the rate its opening cumulative earned, even if the report itself carries the total past a
    ceiling."
    PRD §3.7: "The rate fee is the sum of the per-report `fee_component_cents`."
    PRD §2.8: "There are no fractional cents anywhere: wherever a rate is applied to an amount,
    the product is rounded **half up** to a whole cent."
    PRD §3.7: "every money field is recomputed over the new accepted set with `paid_to_date_cents`
    preserved"

    Design: Difficulty/boundary_precision_check/fee_tier_one_ceiling_inclusivity_boundary
    """
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    first = _file_and_accept(context, "2027-05-15", "2027-06-14", 40, 2_500_000)
    second = _file_and_accept(context, "2027-06-15", "2027-07-15", 10, 100_000)

    at_ceiling = sole_fee_assessment(permit_id)
    assert read_use_report(first["id"])["applied_rate_bp"] == 300
    assert read_use_report(first["id"])["fee_component_cents"] == 75_000
    assert read_use_report(second["id"])["applied_rate_bp"] == 300, (
        "an opening cumulative of exactly 2500000 is still inside the first bracket"
    )
    assert read_use_report(second["id"])["fee_component_cents"] == 3_000
    assert at_ceiling["reported_agr_cents"] == 2_600_000
    assert at_ceiling["assessed_fee_cents"] == 78_000

    past = validate_success(
        _amend(
            context, first["id"],
            service_days_used=40, client_count=8,
            gross_revenue_cents=2_500_001, allowable_deductions_cents=0,
        ),
        201,
    )
    assert read_use_report(first["id"])["status"] == "SUPERSEDED"
    assert past["supersedes_report_id"] == first["id"]
    assert read_use_report(past["id"])["fee_component_cents"] == 75_000, (
        "75000.03 rounds back down to 75000, so the first report's own component never moves"
    )
    assert read_use_report(second["id"])["applied_rate_bp"] == 400, (
        "one cent past the ceiling pushes the following report into the second bracket"
    )
    assert read_use_report(second["id"])["fee_component_cents"] == 4_000
    one_past = sole_fee_assessment(permit_id)
    assert one_past["status"] == "PROVISIONAL"
    assert one_past["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert one_past["reported_agr_cents"] == 2_600_001
    assert one_past["assessed_fee_cents"] == 79_000
    assert one_past["assessed_fee_cents"] - at_ceiling["assessed_fee_cents"] == 1_000, (
        "the whole difference comes from the second report's bracket, never from rounding"
    )

    below = validate_success(
        _amend(
            context, past["id"],
            service_days_used=40, client_count=8,
            gross_revenue_cents=2_499_999, allowable_deductions_cents=0,
        ),
        201,
    )
    assert read_use_report(past["id"])["status"] == "SUPERSEDED"
    assert below["supersedes_report_id"] == past["id"]
    assert read_use_report(below["id"])["fee_component_cents"] == 75_000, (
        "74999.97 rounds up to 75000: the same component on either side of the line"
    )
    assert read_use_report(second["id"])["applied_rate_bp"] == 300
    assert read_use_report(second["id"])["fee_component_cents"] == 3_000
    one_below = sole_fee_assessment(permit_id)
    assert one_below["reported_agr_cents"] == 2_599_999
    assert one_below["assessed_fee_cents"] == 78_000, (
        "identical to the exact-ceiling figure, which is what makes the ceiling inclusive"
    )
    accepted, meta = list_use_reports(
        params={"permit_id": permit_id, "status": "ACCEPTED"}
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in accepted} == {below["id"], second["id"]}


def test_the_two_variants_agree_past_the_ceiling_and_differ_by_a_thousand_on_it():
    """PRD §3.7: "The **final** variant, `FINAL_AGGREGATE`, rounds once and brackets the season.
    It sums the untouched `adjusted_gross_revenue_cents` over the ordered set into a season total,
    splits that single total across the three brackets — the portion up to 2500000 cents, the
    portion between 2500000 and 10000000 cents, and the portion above 10000000 cents — multiplies
    each portion by its own rate, adds the three products, divides by 10000, and rounds half-up
    exactly once."
    PRD §3.7: "the provisional variant bills a report that straddles a bracket boundary entirely
    at the lower rate while the final variant splits the season total so that the straddling
    portion is billed partly at the higher rate"
    PRD §3.7: "Finalization recomputes `reported_agr_cents` and `assessed_fee_cents` under the
    aggregate variant, sets `variant_applied` to `FINAL_AGGREGATE`, stamps `finalized_at`,
    recomputes `balance_due_cents`, `credit_balance_cents`, `minimum_fee_applied`, then the
    permit's `fee_delinquent` and `compliance_status`; the delta against the provisional figure
    appears as either a new balance or a new credit, and the assessment moves `PROVISIONAL →
    FINAL`."

    Design: Difficulty/boundary_precision_check/fee_tier_one_ceiling_inclusivity_boundary
    """
    on_the_line = _reporting_permit()
    on_line_permit = on_the_line["permit"]["id"]
    _file_and_accept(on_the_line, "2027-05-15", "2027-06-14", 40, 2_500_000)
    _file_and_accept(on_the_line, "2027-06-15", "2027-07-15", 10, 100_000)
    provisional_on_line = sole_fee_assessment(on_line_permit)
    assert provisional_on_line["assessed_fee_cents"] == 78_000, (
        "both reports opened inside bracket one, the second at exactly the ceiling"
    )

    final_on_line = finalize_fee_assessment(provisional_on_line["id"])
    assert final_on_line["variant_applied"] == "FINAL_AGGREGATE"
    assert final_on_line["reported_agr_cents"] == 2_600_000
    assert final_on_line["assessed_fee_cents"] == 79_000, (
        "the aggregate splits at the same 2500000 line: 75000 plus 100000 at 400 bp"
    )
    assert final_on_line["assessed_fee_cents"] - provisional_on_line["assessed_fee_cents"] == 1_000
    assert final_on_line["balance_due_cents"] == 79_000
    assert final_on_line["minimum_fee_applied"] is False
    assert final_on_line["finalized_at"] is not None
    assert read_permit(on_line_permit)["fee_delinquent"] is True

    # A second permit in its own area, under its own holder: the area code and
    # the nine-digit EIN are both unique across their collections.
    one_past = _reporting_permit(
        area_overrides={"area_code": "BRW-17", "name": "Bear River Narrows"},
        outfitter_overrides={"ein": "410001700", "legal_name": "Narrows Outfitters LLC"},
    )
    past_permit = one_past["permit"]["id"]
    _file_and_accept(one_past, "2027-05-15", "2027-06-14", 40, 2_500_001)
    _file_and_accept(one_past, "2027-06-15", "2027-07-15", 10, 100_000)
    provisional_past = sole_fee_assessment(past_permit)
    assert provisional_past["reported_agr_cents"] == 2_600_001
    assert provisional_past["assessed_fee_cents"] == 79_000, (
        "one cent of revenue moves the second report to 400 bp and costs 1000 cents"
    )

    final_past = finalize_fee_assessment(provisional_past["id"])
    assert final_past["assessed_fee_cents"] == 79_000, (
        "790000400 over 10000 is 79000.04, which rounds back to 79000"
    )
    assert final_past["assessed_fee_cents"] == provisional_past["assessed_fee_cents"], (
        "past the ceiling the two variants agree; on the ceiling they differ by exactly 1000"
    )


def test_one_unreviewed_sibling_report_blocks_the_whole_season_from_closing():
    """PRD §3.7: "Finalization is available to a `PermitSpecialist` or `ProgramAdministrator`. The
    assessment must be `PROVISIONAL`, and no report for that permit and season may remain
    `SUBMITTED`, else `ERR_USE_REPORTS_PENDING` — the season cannot be closed out while an
    unreviewed report could still change the basis."
    PRD §3.7: "Both variants read only reports whose `status` is `ACCEPTED` and whose
    `season_year` matches the assessment; `SUBMITTED` and `SUPERSEDED` rows are excluded."
    PRD §3.7: "The report's `season_year` is derived as the calendar year of `period_start_date`
    and is what groups reports into a season's assessment"
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/cross_entity_state_dependency/fee_finalization_gated_by_sibling_report_states
    """
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    _file_and_accept(context, "2027-05-15", "2027-06-14", 40, 1_600_050)
    pending = _file(context, "2027-06-15", "2027-07-15", 30, 1_400_000)
    assert pending["status"] == "SUBMITTED"
    assert pending["season_year"] == 2027
    assert pending["applied_rate_bp"] is None

    before = sole_fee_assessment(permit_id)
    assert before["status"] == "PROVISIONAL"
    assert before["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert before["reported_agr_cents"] == 1_600_050, (
        "the submitted report is invisible to the money, which is what makes the premature "
        "finalization look safe"
    )
    assert before["assessed_fee_cents"] == 48_002
    assert read_permit(permit_id)["fee_delinquent"] is True

    validate_error(
        api_client.finalize_fee_assessment(before["id"], SPECIALIST),
        ApiErrorId.ERR_USE_REPORTS_PENDING,
        409,
    )

    untouched = sole_fee_assessment(permit_id)
    assert untouched["status"] == "PROVISIONAL"
    assert untouched["finalized_at"] is None
    assert untouched["assessed_fee_cents"] == 48_002
    assert untouched["version"] == before["version"], "a refused finalization writes nothing"
    assert read_permit(permit_id)["fee_delinquent"] is True

    accept_use_report(pending["id"])
    widened = sole_fee_assessment(permit_id)
    assert widened["reported_agr_cents"] == 3_000_050
    assert widened["assessed_fee_cents"] == 90_002, "48002 + 42000, both reports opening in tier 1"

    finalized = finalize_fee_assessment(widened["id"])
    assert finalized["status"] == "FINAL"
    assert finalized["variant_applied"] == "FINAL_AGGREGATE"
    assert finalized["reported_agr_cents"] == 3_000_050
    assert finalized["assessed_fee_cents"] == 95_002, (
        "2500000 at 300 bp plus 500050 at 400 bp, rounded once"
    )
    assert finalized["finalized_at"].startswith("2027-09-20")
    assert finalized["balance_due_cents"] == 95_002


def test_a_superseded_sibling_never_blocks_but_a_freshly_filed_one_does():
    """PRD §3.7: "no report for that permit and season may remain `SUBMITTED`, else
    `ERR_USE_REPORTS_PENDING`"
    PRD §3.7: "Both variants read only reports whose `status` is `ACCEPTED` and whose
    `season_year` matches the assessment; `SUBMITTED` and `SUPERSEDED` rows are excluded."
    PRD §3.7: "Because the accepted set changed, the season's assessment reverts: a `FINAL` or
    `PAID` assessment returns to `PROVISIONAL`, `finalized_at` is cleared, `variant_applied` is
    set back to `PROVISIONAL_PER_REPORT`, and every money field is recomputed over the new
    accepted set with `paid_to_date_cents` preserved."
    PRD §3.7: "The report must be `ACCEPTED`, else `ERR_USE_REPORT_STATE_INVALID`; the caller must
    own the permit; the deduction cap applies again"

    Design: Difficulty/cross_entity_state_dependency/fee_finalization_gated_by_sibling_report_states
    """
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    original = _file_and_accept(context, "2027-05-15", "2027-06-14", 40, 1_600_050)

    first_close = finalize_fee_assessment(sole_fee_assessment(permit_id)["id"])
    assert first_close["status"] == "FINAL"
    assert first_close["assessed_fee_cents"] == 48_002, (
        "1600050 sits wholly inside tier one, so both variants agree to the cent"
    )

    latecomer = _file(context, "2027-06-15", "2027-07-15", 30, 1_400_000)
    assert latecomer["status"] == "SUBMITTED"
    assert sole_fee_assessment(permit_id)["status"] == "FINAL", (
        "merely filing a report moves no money"
    )

    replacement = validate_success(
        _amend(
            context, original["id"],
            service_days_used=40, client_count=8,
            gross_revenue_cents=1_700_000, allowable_deductions_cents=0,
        ),
        201,
    )
    assert read_use_report(original["id"])["status"] == "SUPERSEDED"
    reverted = sole_fee_assessment(permit_id)
    assert reverted["status"] == "PROVISIONAL"
    assert reverted["finalized_at"] is None
    assert reverted["reported_agr_cents"] == 1_700_000
    assert reverted["assessed_fee_cents"] == 51_000

    validate_error(
        api_client.finalize_fee_assessment(reverted["id"], SPECIALIST),
        ApiErrorId.ERR_USE_REPORTS_PENDING,
        409,
    )

    validate_error(
        _amend(
            context, original["id"],
            service_days_used=40, client_count=8,
            gross_revenue_cents=1_800_000, allowable_deductions_cents=0,
        ),
        ApiErrorId.ERR_USE_REPORT_STATE_INVALID,
    )

    accept_use_report(latecomer["id"])
    ready = sole_fee_assessment(permit_id)
    assert ready["assessed_fee_cents"] == 93_000, "51000 + 42000"

    closed_out = finalize_fee_assessment(ready["id"])
    assert closed_out["status"] == "FINAL"
    assert closed_out["reported_agr_cents"] == 3_100_000
    assert closed_out["assessed_fee_cents"] == 99_000, (
        "2500000 at 300 bp plus 600000 at 400 bp: the superseded row was no obstacle"
    )
    assert read_use_report(replacement["id"])["status"] == "ACCEPTED"


def test_the_money_identity_survives_five_states_and_the_overpayment_becomes_credit():
    """PRD §3.7: "Those four money fields satisfy an identity that must hold after every
    acceptance, finalization, payment and amendment: `assessed_fee_cents` plus
    `credit_balance_cents` equals `paid_to_date_cents` plus `balance_due_cents`."
    PRD §3.7: "Because `paid_to_date_cents` never decreases, an amendment that lowers the fee
    below what was already paid surfaces the difference as a credit rather than by rewinding the
    payment, and a forward amendment paired with its reversing amendment must land back on the
    original `assessed_fee_cents` with the identity intact and no drift."
    PRD §3.7: "`reported_agr_cents` is the season total, `balance_due_cents` is
    `assessed_fee_cents` less `paid_to_date_cents` floored at zero, and `credit_balance_cents` is
    `paid_to_date_cents` less `assessed_fee_cents` floored at zero."
    PRD §3.7: "If the recomputed balance is positive, `fee_delinquent` becomes true, and because
    it became true the permit's `compliance_status` is re-derived from `COMPLIANT` to `PROBATION`
    — four links from one request."

    Design: Difficulty/compensating_invariant/fee_money_identity_across_amend_and_reversal
    """
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    _file_and_accept(context, "2027-05-15", "2027-06-14", 40, 1_600_050)
    _file_and_accept(context, "2027-06-15", "2027-07-15", 30, 1_400_000)
    third = _file_and_accept(context, "2027-07-16", "2027-08-15", 30, 900_000)

    state_zero = sole_fee_assessment(permit_id)
    assert state_zero["assessed_fee_cents"] == 126_002
    assert state_zero["reported_agr_cents"] == 3_900_050
    assert state_zero["paid_to_date_cents"] == 0
    assert state_zero["balance_due_cents"] == 126_002
    assert state_zero["credit_balance_cents"] == 0
    assert _identity_holds(state_zero)

    state_one = finalize_fee_assessment(state_zero["id"])
    assert state_one["variant_applied"] == "FINAL_AGGREGATE"
    assert state_one["assessed_fee_cents"] == 131_002
    assert state_one["balance_due_cents"] == 131_002
    assert state_one["credit_balance_cents"] == 0
    assert _identity_holds(state_one)
    assert read_permit(permit_id)["fee_delinquent"] is True

    state_two = pay_fee_assessment(state_one["id"], context["outfitter"]["id"], 131_002)
    assert state_two["status"] == "PAID"
    assert state_two["paid_to_date_cents"] == 131_002
    assert state_two["balance_due_cents"] == 0
    assert state_two["credit_balance_cents"] == 0
    assert _identity_holds(state_two)
    assert read_permit(permit_id)["fee_delinquent"] is False

    raised = validate_success(
        _amend(
            context, third["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=1_400_000, allowable_deductions_cents=0,
        ),
        201,
    )
    state_three = sole_fee_assessment(permit_id)
    assert state_three["status"] == "PROVISIONAL"
    assert state_three["finalized_at"] is None
    assert state_three["assessed_fee_cents"] == 146_002
    assert state_three["reported_agr_cents"] == 4_400_050
    assert state_three["paid_to_date_cents"] == 131_002
    assert state_three["balance_due_cents"] == 15_000
    assert state_three["credit_balance_cents"] == 0
    assert _identity_holds(state_three)
    assert read_permit(permit_id)["fee_delinquent"] is True

    reversed_again = validate_success(
        _amend(
            context, raised["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=900_000, allowable_deductions_cents=0,
        ),
        201,
    )
    state_four = sole_fee_assessment(permit_id)
    assert state_four["assessed_fee_cents"] == 126_002, (
        "exactly the state-zero figure: a rounding slip in the revert would read 126001 or 126003"
    )
    assert state_four["reported_agr_cents"] == 3_900_050
    assert state_four["paid_to_date_cents"] == 131_002, "the ratchet never turned back"
    assert state_four["balance_due_cents"] == 0
    assert state_four["credit_balance_cents"] == 5_000
    assert _identity_holds(state_four)
    assert read_permit(permit_id)["fee_delinquent"] is False

    assert read_use_report(third["id"])["status"] == "SUPERSEDED"
    assert read_use_report(raised["id"])["status"] == "SUPERSEDED"
    assert read_use_report(reversed_again["id"])["status"] == "ACCEPTED"
    _rows, meta = list_use_reports(params={"permit_id": permit_id, "status": "ACCEPTED"})
    assert meta["total_count"] == 3, "the fee was computed over exactly three reports throughout"


def test_a_partial_payment_ratchets_and_the_pair_of_amendments_leaves_no_drift():
    """PRD §3.7: "The payment adds to `paid_to_date_cents`, which only ever increases, and
    recomputes `balance_due_cents` and `credit_balance_cents`; the assessment moves to `PAID` only
    when `balance_due_cents` reaches zero, and a partial payment leaves the status untouched."
    PRD §3.7: "Those four money fields satisfy an identity that must hold after every acceptance,
    finalization, payment and amendment: `assessed_fee_cents` plus `credit_balance_cents` equals
    `paid_to_date_cents` plus `balance_due_cents`."
    PRD §3.7: "Because `paid_to_date_cents` never decreases, an amendment that lowers the fee below
    what was already paid surfaces the difference as a credit rather than by rewinding the payment,
    and a forward amendment paired with its reversing amendment must land back on the original
    `assessed_fee_cents` with the identity intact and no drift."

    Design: Difficulty/compensating_invariant/fee_money_identity_across_amend_and_reversal
    """
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    _file_and_accept(context, "2027-05-15", "2027-06-14", 40, 1_600_050)
    second = _file_and_accept(context, "2027-06-15", "2027-07-15", 30, 1_400_000)

    opening = sole_fee_assessment(permit_id)
    assert opening["assessed_fee_cents"] == 90_002
    assert opening["reported_agr_cents"] == 3_000_050
    assert opening["balance_due_cents"] == 90_002
    assert _identity_holds(opening)

    partial = pay_fee_assessment(opening["id"], context["outfitter"]["id"], 40_000)
    assert partial["status"] == "PROVISIONAL", "a partial payment leaves the status untouched"
    assert partial["paid_to_date_cents"] == 40_000
    assert partial["balance_due_cents"] == 50_002
    assert partial["credit_balance_cents"] == 0
    assert _identity_holds(partial)

    raised = validate_success(
        _amend(
            context, second["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=2_000_000, allowable_deductions_cents=0,
        ),
        201,
    )
    after_raise = sole_fee_assessment(permit_id)
    assert after_raise["assessed_fee_cents"] == 108_002
    assert after_raise["reported_agr_cents"] == 3_600_050
    assert after_raise["paid_to_date_cents"] == 40_000
    assert after_raise["balance_due_cents"] == 68_002
    assert after_raise["credit_balance_cents"] == 0
    assert _identity_holds(after_raise)

    restored = validate_success(
        _amend(
            context, raised["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=1_400_000, allowable_deductions_cents=0,
        ),
        201,
    )
    after_restore = sole_fee_assessment(permit_id)
    assert after_restore["assessed_fee_cents"] == 90_002, "no drift across the reversing pair"
    assert after_restore["reported_agr_cents"] == 3_000_050
    assert after_restore["paid_to_date_cents"] == 40_000, "the payment was never rewound"
    assert after_restore["balance_due_cents"] == 50_002
    assert after_restore["credit_balance_cents"] == 0
    assert _identity_holds(after_restore)

    settled = pay_fee_assessment(after_restore["id"], context["outfitter"]["id"], 50_002)
    assert settled["status"] == "PAID"
    assert settled["paid_to_date_cents"] == 90_002
    assert settled["balance_due_cents"] == 0
    assert settled["credit_balance_cents"] == 0
    assert _identity_holds(settled)
    assert read_permit(permit_id)["fee_delinquent"] is False

    lowered = validate_success(
        _amend(
            context, restored["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=400_000, allowable_deductions_cents=0,
        ),
        201,
    )
    after_lower = sole_fee_assessment(permit_id)
    assert after_lower["status"] == "PROVISIONAL", (
        "the amendment reverts the settled assessment even though nothing is owed"
    )
    assert after_lower["assessed_fee_cents"] == 60_002
    assert after_lower["reported_agr_cents"] == 2_000_050
    assert after_lower["paid_to_date_cents"] == 90_002, "the ratchet holds above the new fee"
    assert after_lower["balance_due_cents"] == 0
    assert after_lower["credit_balance_cents"] == 30_000, (
        "the overpayment surfaces as credit, not as a reduced paid_to_date_cents"
    )
    assert _identity_holds(after_lower)
    assert read_permit(permit_id)["fee_delinquent"] is False

    validate_success(
        _amend(
            context, lowered["id"],
            service_days_used=30, client_count=8,
            gross_revenue_cents=1_400_000, allowable_deductions_cents=0,
        ),
        201,
    )
    closing = sole_fee_assessment(permit_id)
    assert closing["assessed_fee_cents"] == 90_002
    assert closing["reported_agr_cents"] == 3_000_050
    assert closing["paid_to_date_cents"] == 90_002
    assert closing["balance_due_cents"] == 0
    assert closing["credit_balance_cents"] == 0, "the credit is consumed, not banked"
    assert _identity_holds(closing)
    assert read_permit(permit_id)["fee_delinquent"] is False
    assert read_use_report(second["id"])["status"] == "SUPERSEDED"
    _rows, meta = list_use_reports(params={"permit_id": permit_id, "status": "ACCEPTED"})
    assert meta["total_count"] == 2
