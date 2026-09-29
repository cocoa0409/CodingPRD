"""Amending a settled season, and the money that has to move backwards.

Covers the depth-four revert cascade, the credit direction and its reversal,
the payment boundary against the live balance, and the permit-version token an
unrelated write invalidates.
"""
from test_helpers import (
    ApiErrorId,
    accept_use_report,
    amend_report_payload,
    authorize_guide,
    create_qualified_guide,
    current_permit_version,
    file_insurance_certificate,
    finalize_fee_assessment,
    list_use_reports,
    pay_fee_assessment,
    payment_payload,
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

ADMIN = TEST_USERS["program_administrator_headers"]


def _reporting_permit(clock="2027-09-01T00:00:00Z"):
    """An ISSUED 200-day GRADUATED permit with one authorized guide and
    general-liability coverage across the whole term."""
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200}, clock=clock
    )
    guide = create_qualified_guide(context["outfitter"]["id"])
    authorize_guide(context["permit"]["id"], guide["id"], context["outfitter"]["id"])
    file_insurance_certificate(context["permit"]["id"], context["outfitter"]["id"])
    permit = read_permit(context["permit"]["id"])
    assert permit["authorized_client_capacity_total"] == 8
    assert permit["insurance_current"] is True
    assert permit["compliance_status"] == "COMPLIANT"
    return context


def _file_and_accept(context, start, end, days, gross, deductions=0):
    report = validate_success(
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
    return accept_use_report(report["id"])


def _amend(context, report_id, expected_permit_version, **overrides):
    return api_client.amend_trip_use_report(
        report_id,
        amend_report_payload(expected_permit_version, **overrides),
        context["holder_headers"],
    )


def _pay(context, assessment_id, amount_cents):
    return api_client.create_fee_payment(
        assessment_id, payment_payload(amount_cents), context["holder_headers"]
    )


def _settled_season():
    """Three accepted reports, the season finalized at 131002 and paid off."""
    context = _reporting_permit()
    permit_id = context["permit"]["id"]
    first = _file_and_accept(context, "2027-05-15", "2027-06-15", 60, 1_800_050, 200_000)
    second = _file_and_accept(context, "2027-06-15", "2027-07-15", 60, 1_500_000, 100_000)
    third = _file_and_accept(context, "2027-07-15", "2027-08-15", 40, 900_000, 0)
    assert first["adjusted_gross_revenue_cents"] == 1_600_050
    assert second["adjusted_gross_revenue_cents"] == 1_400_000
    assert third["adjusted_gross_revenue_cents"] == 900_000

    provisional = sole_fee_assessment(permit_id)
    assert provisional["assessed_fee_cents"] == 126_002, (
        "48002 + 42000 + 36000: the third report opens above the tier-1 ceiling"
    )
    final = finalize_fee_assessment(provisional["id"])
    assert final["status"] == "FINAL"
    assert final["reported_agr_cents"] == 3_900_050
    assert final["assessed_fee_cents"] == 131_002
    paid = pay_fee_assessment(final["id"], context["outfitter"]["id"], 131_002)
    assert paid["status"] == "PAID"
    assert paid["paid_to_date_cents"] == 131_002
    assert paid["balance_due_cents"] == 0
    assert paid["credit_balance_cents"] == 0
    return context, first, second, third, paid


def test_an_amendment_drags_a_paid_season_back_through_four_links():
    """PRD §3.7: "The original row is never edited: it moves `ACCEPTED → SUPERSEDED`, which is
    terminal, and a **new** report row is created directly in `ACCEPTED` carrying
    `supersedes_report_id` pointing at the original, the same `period_start_date` and
    `period_end_date`, and the amended figures — so both the original and the corrected numbers
    survive in the audit trail."
    PRD §3.7: "Because the accepted set changed, the season's assessment reverts: a `FINAL` or
    `PAID` assessment returns to `PROVISIONAL`, `finalized_at` is cleared, `variant_applied` is
    set back to `PROVISIONAL_PER_REPORT`, and every money field is recomputed over the new
    accepted set with `paid_to_date_cents` preserved."
    PRD §3.7: "If the recomputed balance is positive, `fee_delinquent` becomes true, and because
    it became true the permit's `compliance_status` is re-derived from `COMPLIANT` to `PROBATION`
    — four links from one request."
    PRD §3.7: "assigns `applied_rate_bp` from the bracket that the cumulative total of *strictly
    earlier* reports falls into"
    PRD §3.7: "`expected_permit_version` must equal the permit's current `version`, else
    `ERR_STALE_PERMIT_VERSION` at HTTP 412"

    Design: Difficulty/transitive_cascade/amend_report_revert_assessment_delinquency_depth_four
    """
    context, first, second, third, paid = _settled_season()
    permit_id = context["permit"]["id"]

    before = read_permit(permit_id)
    assert before["fee_delinquent"] is False
    assert before["compliance_status"] == "COMPLIANT"
    permit_version = before["version"]

    replacement = validate_success(
        _amend(
            context, third["id"], permit_version,
            service_days_used=40, client_count=8,
            gross_revenue_cents=1_400_000, allowable_deductions_cents=0,
        ),
        201,
    )

    assert read_use_report(third["id"])["status"] == "SUPERSEDED"
    assert replacement["status"] == "ACCEPTED"
    assert replacement["supersedes_report_id"] == third["id"]
    assert replacement["period_start_date"].startswith("2027-07-15")
    assert replacement["period_end_date"].startswith("2027-08-15")
    assert replacement["adjusted_gross_revenue_cents"] == 1_400_000

    reverted = sole_fee_assessment(permit_id)
    assert reverted["status"] == "PROVISIONAL", "a PAID assessment goes backwards"
    assert reverted["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert reverted["finalized_at"] is None
    assert reverted["reported_agr_cents"] == 4_400_050
    assert reverted["assessed_fee_cents"] == 146_002, "48002 + 42000 + 56000"

    priced = read_use_report(replacement["id"])
    assert priced["applied_rate_bp"] == 400, (
        "its opening cumulative of 3000050 already sits above the 2500000 tier-1 ceiling"
    )
    assert priced["fee_component_cents"] == 56_000

    assert reverted["paid_to_date_cents"] == 131_002, "money already paid is never rewound"
    assert reverted["balance_due_cents"] == 15_000
    assert reverted["credit_balance_cents"] == 0
    assert (
        reverted["assessed_fee_cents"] + reverted["credit_balance_cents"]
        == reverted["paid_to_date_cents"] + reverted["balance_due_cents"]
    )

    after = read_permit(permit_id)
    assert after["fee_delinquent"] is True
    assert after["compliance_status"] == "PROBATION"
    assert after["service_days_used_ytd"] == 160
    assert after["version"] == permit_version + 1

    validate_error(
        _amend(
            context, replacement["id"], permit_version,
            service_days_used=40, client_count=8,
            gross_revenue_cents=1_400_000, allowable_deductions_cents=0,
        ),
        ApiErrorId.ERR_STALE_PERMIT_VERSION,
        412,
    )

    for report, component in ((first, 48_002), (second, 42_000)):
        untouched = read_use_report(report["id"])
        assert untouched["status"] == "ACCEPTED"
        assert untouched["fee_component_cents"] == component
    assert paid["assessed_fee_cents"] == 131_002, "the settled figure the holder had computed from"


def test_a_downward_amendment_pays_out_in_credit_and_its_reversal_lands_back_home():
    """PRD §3.7: "Because `paid_to_date_cents` never decreases, an amendment that lowers the fee
    below what was already paid surfaces the difference as a credit rather than by rewinding the
    payment, and a forward amendment paired with its reversing amendment must land back on the
    original `assessed_fee_cents` with the identity intact and no drift."
    PRD §3.7: "`balance_due_cents` is `assessed_fee_cents` less `paid_to_date_cents` floored at
    zero, and `credit_balance_cents` is `paid_to_date_cents` less `assessed_fee_cents` floored at
    zero."
    PRD §3.7: "Those four money fields satisfy an identity that must hold after every acceptance,
    finalization, payment and amendment: `assessed_fee_cents` plus `credit_balance_cents` equals
    `paid_to_date_cents` plus `balance_due_cents`."
    PRD §3.7: "The permit's `service_days_used_ytd` is recomputed from the accepted set rather
    than adjusted"
    PRD §3.7: "`SUPERSEDED` rows are ignored, which is what lets an amendment chain reuse a
    period"

    Design: Difficulty/transitive_cascade/amend_report_revert_assessment_delinquency_depth_four
    """
    context, _first, _second, third, _paid = _settled_season()
    permit_id = context["permit"]["id"]

    lowered = validate_success(
        _amend(
            context, third["id"], current_permit_version(permit_id),
            service_days_used=40, client_count=8,
            gross_revenue_cents=400_000, allowable_deductions_cents=0,
        ),
        201,
    )
    assert lowered["adjusted_gross_revenue_cents"] == 400_000

    credited = sole_fee_assessment(permit_id)
    assert credited["status"] == "PROVISIONAL"
    assert credited["reported_agr_cents"] == 3_400_050
    assert credited["assessed_fee_cents"] == 106_002, "48002 + 42000 + 16000"
    assert credited["paid_to_date_cents"] == 131_002
    assert credited["balance_due_cents"] == 0
    assert credited["credit_balance_cents"] == 25_000, (
        "the overpayment surfaces as credit rather than as a refunded payment"
    )
    assert (
        credited["assessed_fee_cents"] + credited["credit_balance_cents"]
        == credited["paid_to_date_cents"] + credited["balance_due_cents"]
    )

    mid_flight = read_permit(permit_id)
    assert mid_flight["fee_delinquent"] is False, "a credit is not a debt"
    assert mid_flight["compliance_status"] == "COMPLIANT"
    assert mid_flight["service_days_used_ytd"] == 160

    restored = validate_success(
        _amend(
            context, lowered["id"], current_permit_version(permit_id),
            service_days_used=40, client_count=8,
            gross_revenue_cents=900_000, allowable_deductions_cents=0,
        ),
        201,
    )
    assert restored["supersedes_report_id"] == lowered["id"]
    assert restored["period_start_date"].startswith("2027-07-15")
    assert read_use_report(lowered["id"])["status"] == "SUPERSEDED"
    assert read_use_report(third["id"])["status"] == "SUPERSEDED"

    home = sole_fee_assessment(permit_id)
    assert home["reported_agr_cents"] == 3_900_050
    assert home["assessed_fee_cents"] == 126_002, (
        "back on the provisional figure the season started from, with no drift"
    )
    assert home["paid_to_date_cents"] == 131_002
    assert home["balance_due_cents"] == 0
    assert home["credit_balance_cents"] == 5_000, (
        "131002 was paid against the aggregate figure, so the provisional basis leaves 5000 over"
    )
    assert (
        home["assessed_fee_cents"] + home["credit_balance_cents"]
        == home["paid_to_date_cents"] + home["balance_due_cents"]
    )

    accepted, meta = list_use_reports(
        params={"permit_id": permit_id, "status": "ACCEPTED"}
    )
    assert meta["total_count"] == 3, "three live rows across a two-link amendment chain"
    assert [row["adjusted_gross_revenue_cents"] for row in accepted] == [
        1_600_050, 1_400_000, 900_000,
    ]
    superseded, superseded_meta = list_use_reports(
        params={"permit_id": permit_id, "status": "SUPERSEDED"}
    )
    assert superseded_meta["total_count"] == 2
    assert {row["id"] for row in superseded} == {third["id"], lowered["id"]}
    assert read_permit(permit_id)["service_days_used_ytd"] == 160


def test_a_payment_is_measured_against_the_live_balance_not_the_assessed_figure():
    """PRD §3.7: "The holder pays by recording an `amount_cents` against the assessment. Payments
    are accepted while the assessment is `PROVISIONAL` or `FINAL`. The amount must be strictly
    positive and must not exceed the current `balance_due_cents`, else
    `ERR_PAYMENT_EXCEEDS_BALANCE`. The payment adds to `paid_to_date_cents`, which only ever
    increases, and recomputes `balance_due_cents` and `credit_balance_cents`; the assessment moves
    to `PAID` only when `balance_due_cents` reaches zero, and a partial payment leaves the status
    untouched."
    PRD §3.7: "Only a `PAID` assessment with `balance_due_cents` at zero is closable; a
    `PROVISIONAL`, `FINAL` or already-`CLOSED` assessment is refused with
    `ERR_FEE_ASSESSMENT_CLOSED` — the same error that a later payment, finalization or
    amendment-driven revert against a closed assessment receives."
    PRD §2.5: "**State preconditions** — the target record is in a status from which the requested
    transition is declared."
    PRD §2.5: "**Fiscal, quota and capacity limits** — service-day caps, area availability,
    coverage sufficiency, bond sufficiency, outstanding balances, payment amounts and deduction
    caps."
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`."

    Design: Corner/validations/payment_boundary_passes_at_exactly_the_balance_and_fails_one_cent_over
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        clock="2027-10-01T00:00:00Z",
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    guide = create_qualified_guide(outfitter_id)
    authorize_guide(permit_id, guide["id"], outfitter_id)
    _file_and_accept(context, "2027-06-01", "2027-06-16", 10, 2_000_000, 0)

    provisional = sole_fee_assessment(permit_id)
    assert provisional["assessed_fee_cents"] == 60_000
    assessment_id = provisional["id"]

    validate_error(
        api_client.close_fee_assessment(assessment_id, ADMIN),
        ApiErrorId.ERR_FEE_ASSESSMENT_CLOSED,
        409,
    )
    finalized = finalize_fee_assessment(assessment_id)
    assert finalized["status"] == "FINAL"
    assert finalized["assessed_fee_cents"] == 60_000, (
        "the same 60000 both ways: 2000000 sits wholly inside the first bracket"
    )
    validate_error(
        api_client.close_fee_assessment(assessment_id, ADMIN),
        ApiErrorId.ERR_FEE_ASSESSMENT_CLOSED,
        409,
    )

    validate_error(
        _pay(context, assessment_id, 60_001),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )
    validate_error(
        _pay(context, assessment_id, 0),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )

    part = validate_success(_pay(context, assessment_id, 20_000))
    assert part["status"] == "FINAL", "a partial payment leaves the status untouched"
    assert part["paid_to_date_cents"] == 20_000
    assert part["balance_due_cents"] == 40_000
    assert part["credit_balance_cents"] == 0
    assert (
        part["assessed_fee_cents"] + part["credit_balance_cents"]
        == part["paid_to_date_cents"] + part["balance_due_cents"]
    )

    validate_error(
        _pay(context, assessment_id, 40_001),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )

    settled = validate_success(_pay(context, assessment_id, 40_000))
    assert settled["status"] == "PAID", "exactly the remaining balance is admitted"
    assert settled["paid_to_date_cents"] == 60_000
    assert settled["balance_due_cents"] == 0
    assert settled["credit_balance_cents"] == 0

    permit = read_permit(permit_id)
    assert permit["fee_delinquent"] is False
    assert permit["insurance_current"] is False
    assert permit["compliance_status"] == "PROBATION", (
        "the balance is gone but the missing certificate keeps the permit on probation"
    )
    assert permit["administrative_status"] == "ISSUED"

    validate_error(
        _pay(context, assessment_id, 1),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )
    closed = validate_success(api_client.close_fee_assessment(assessment_id, ADMIN))
    assert closed["status"] == "CLOSED"

    validate_error(
        _pay(context, assessment_id, 1),
        ApiErrorId.ERR_FEE_ASSESSMENT_CLOSED,
        409,
    )


def test_an_unrelated_certificate_filing_invalidates_the_amendment_token():
    """PRD §2.6: "Amending an accepted trip use report must carry `expected_permit_version`, a
    non-optional field holding the client's last observed `version` of the parent `Permit`. If it
    does not equal the permit's current `version`, the amendment is rejected with
    `ERR_STALE_PERMIT_VERSION` (HTTP 412), because the fee basis the holder computed its amendment
    against is no longer the basis the server holds."
    PRD §2.6: "No other endpoint accepts a version field, and a rejected version check leaves the
    parent's `version` untouched."
    PRD §3.6: "Filing recomputes the permit's `insurance_current` and re-derives its
    `compliance_status`, and advances the permit's `version`."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Corner/complexity_layers/amendment_rejects_a_stale_permit_token_after_an_unrelated_permit_write
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        clock="2027-06-15T00:00:00Z",
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    guide = create_qualified_guide(outfitter_id)
    authorize_guide(permit_id, guide["id"], outfitter_id)
    original = _file_and_accept(context, "2027-05-15", "2027-06-01", 20, 2_000_000, 0)
    assert sole_fee_assessment(permit_id)["assessed_fee_cents"] == 60_000

    stale_version = current_permit_version(permit_id)
    file_insurance_certificate(permit_id, outfitter_id)
    after_certificate = read_permit(permit_id)
    assert after_certificate["insurance_current"] is True
    assert after_certificate["version"] > stale_version, (
        "a certificate filing touches the permit, which is exactly the unrelated write the rule "
        "is about"
    )

    validate_error(
        _amend(
            context, original["id"], stale_version,
            service_days_used=20, client_count=8,
            gross_revenue_cents=3_000_000, allowable_deductions_cents=0,
        ),
        ApiErrorId.ERR_STALE_PERMIT_VERSION,
        412,
    )

    untouched = read_use_report(original["id"])
    assert untouched["status"] == "ACCEPTED"
    assert untouched["adjusted_gross_revenue_cents"] == 2_000_000
    rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 1, "the refused amendment created no replacement row"
    assert rows[0]["id"] == original["id"]
    assert sole_fee_assessment(permit_id)["assessed_fee_cents"] == 60_000
    held_version = read_permit(permit_id)["version"]
    assert held_version == after_certificate["version"]

    replacement = validate_success(
        _amend(
            context, original["id"], held_version,
            service_days_used=20, client_count=8,
            gross_revenue_cents=3_000_000, allowable_deductions_cents=0,
        ),
        201,
    )
    assert read_use_report(original["id"])["status"] == "SUPERSEDED"
    assert replacement["status"] == "ACCEPTED"
    assert replacement["supersedes_report_id"] == original["id"]
    assert read_permit(permit_id)["version"] == held_version + 1

    repriced = sole_fee_assessment(permit_id)
    assert repriced["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert repriced["reported_agr_cents"] == 3_000_000
    assert repriced["assessed_fee_cents"] == 90_000, "3000000 at 300 bp, one report opening at zero"
