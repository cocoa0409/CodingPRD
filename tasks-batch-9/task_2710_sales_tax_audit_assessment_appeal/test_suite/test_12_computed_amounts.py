"""Untaxed-purchase arithmetic, the double-counting guard, the clock and the caps."""
from test_helpers import (
    TEST_USERS,
    abate_penalty,
    api_client,
    create_use_tax_purchase_payload,
    draw_sample_unit,
    file_certificate,
    list_adjustments,
    load_information_return,
    read_assessment,
    read_audit,
    read_certificate,
    read_sample_unit,
    read_taxpayer,
    record_purchase,
    register_taxpayer,
    rescore_screening,
    review_certificate,
    set_clock_date,
    setup_agreed_methodology,
    setup_issued_assessment,
    setup_scoped_audit,
    validate_paginated,
    validate_success,
)

AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]


def test_a_used_capital_asset_steps_down_to_its_entry_value_before_the_credit():
    """The stepdown, the apportionment and the credit clamp compose in that order.

    PRD 3.5: "A `CAPITAL_ASSET` purchase first chooses its pre-apportionment base:
    when `first_use_outside_state` is true **and** `months_used_outside_state` is at
    least 6, the asset entered the state already used and the base steps down to
    `fair_market_value_at_entry_cents`, which is mandatory in exactly that branch and
    whose omission is refused with `ERR_CAPITAL_ASSET_FMV_REQUIRED`; otherwise the
    base is `purchase_price_cents`. That base is then apportioned:
    `taxable_basis_cents` is the base multiplied by `in_state_usage_pct_bp`, divided
    by 10,000 and rounded half up. From the basis, `gross_use_tax_cents` is
    `taxable_basis_cents` multiplied by 625 basis points, divided by 10,000 and
    rounded half up; `credit_applied_cents` is the smaller of
    `tax_paid_other_state_cents` and `gross_use_tax_cents`, so the credit is clamped
    at the gross tax and a purchase never produces a refund; and `use_tax_due_cents`
    is `gross_use_tax_cents` less `credit_applied_cents`."

    Design: Corner/calculations/capital_asset_fmv_stepdown_then_clamps_the_other_state_credit
    """
    ctx = setup_agreed_methodology()

    purchase = validate_success(
        api_client.create_use_tax_purchase(
            create_use_tax_purchase_payload(
                ctx["audit"]["id"],
                "2026-02-10",
                10_000_000,
                asset_class="CAPITAL_ASSET",
                in_state_usage_pct_bp=7_500,
                first_use_outside_state=True,
                months_used_outside_state=8,
                fair_market_value_at_entry_cents=6_000_000,
                tax_paid_other_state_cents=200_000,
                vendor_name="Cascade Machine Works",
            ),
            AUDITOR,
        ),
        201,
    )

    # 6,000,000 * 7,500 / 10,000, not 10,000,000 * 7,500 / 10,000.
    assert purchase["taxable_basis_cents"] == 4_500_000
    assert purchase["gross_use_tax_cents"] == 281_250
    assert purchase["credit_applied_cents"] == 200_000
    assert purchase["use_tax_due_cents"] == 81_250
    assert purchase["reclassification_count"] == 0

    audit = read_audit(ctx["audit"]["id"])
    assert audit["use_tax_deficiency_cents"] == 81_250
    assert audit["projection_status"] == "STALE"


def _two_rejected_certificates_one_of_them_sampled():
    """One sampled invoice, one certificate attached to it and one standing alone."""
    ctx = setup_agreed_methodology(minimum_sample_size=1)
    audit_id = ctx["audit"]["id"]
    ctx["unit"] = draw_sample_unit(
        ctx["agreement"]["id"],
        invoice_reference="RT-100",
        invoice_amount_cents=1_000_000,
        exempt_sale_amount_cents=800_000,
        error_class="NO_ERROR",
    )
    ctx["linked"] = file_certificate(
        audit_id,
        purchaser_name="Delta Resale Co",
        claimed_exemption_type="RESALE",
        covered_sale_amount_cents=800_000,
        received_before_sale=False,
        sample_unit_id=ctx["unit"]["id"],
    )
    ctx["unlinked"] = file_certificate(
        audit_id,
        purchaser_name="Orchard Farms LLC",
        claimed_exemption_type="AGRICULTURAL",
        covered_sale_amount_cents=2_000_000,
        form_complete=False,
    )
    review_certificate(
        ctx["linked"]["id"], "REJECTED", review_note="Certificate taken after the sale"
    )
    review_certificate(ctx["unlinked"]["id"], "REJECTED", review_note="Form incomplete")
    return ctx


def test_a_sampled_certificate_is_kept_out_of_the_audit_level_roll_up():
    """The linked defect reaches the notice through the projection, and only once.

    PRD 3.5: "The audit's `certificate_deficiency_cents` is the sum of
    `missing_certificate_tax_cents` over the certificates of that audit whose status
    is `REJECTED` **and** whose `sample_unit_id` is null. Rejected certificates that
    are linked to a sample unit are deliberately excluded: their tax has already
    entered the population through the linked unit's `CERTIFICATE_DEFECT`
    `error_amount_cents`, and therefore through the projection. Adding them to the
    roll-up as well would assess the same exempt sale twice."
    PRD 3.5: "First, the certificate records the `review_note`, takes status
    `REJECTED`, and computes `missing_certificate_tax_cents` as
    `covered_sale_amount_cents` multiplied by 625 basis points, divided by 10,000 and
    rounded half up."
    PRD 3.4: "`sample_error_rate_bp` is the error sum multiplied by 10,000, divided by
    the base sum and rounded half up to a whole basis point"

    Design: Corner/calculations/certificate_deficiency_excludes_the_certificate_linked_to_a_sample_unit
    """
    ctx = _two_rejected_certificates_one_of_them_sampled()

    linked = read_certificate(ctx["linked"]["id"])
    assert linked["status"] == "REJECTED"
    assert linked["good_faith_accepted"] is False
    assert linked["missing_certificate_tax_cents"] == 50_000

    unlinked = read_certificate(ctx["unlinked"]["id"])
    assert unlinked["status"] == "REJECTED"
    assert unlinked["missing_certificate_tax_cents"] == 125_000

    unit = read_sample_unit(ctx["unit"]["id"])
    assert unit["error_class"] == "CERTIFICATE_DEFECT"
    assert unit["error_amount_cents"] == 50_000

    audit = validate_success(api_client.project_sample(ctx["audit"]["id"], AUDITOR), 200)
    # 125,000 only: the sampled certificate's tax is already inside the projection.
    assert audit["certificate_deficiency_cents"] == 125_000
    assert audit["sample_error_rate_bp"] == 500
    assert audit["projected_deficiency_cents"] == 500_000
    assert audit["examined_unit_count"] == 1
    assert audit["projection_status"] == "CURRENT"
    assert audit["projection_method"] == "RATIO_ESTIMATION"


def test_the_limitation_warning_turns_on_at_exactly_ninety_days_out():
    """One day of clock movement flips a derived status the row never stored.

    PRD 3.2: "The status is `EXPIRED` when the logical clock date is strictly after
    `statute_expiry_date`. It is `EXPIRING_SOON` when the audit has not expired and the
    whole number of days from the logical clock date to `statute_expiry_date` is 90 or
    fewer — a full calendar quarter of warning. Otherwise it is `PROTECTED`."
    PRD 3.2: "From that date the system derives `statute_status` against the current
    logical clock, on every read and at every validation that consults it, and never
    serves a stored stale value."

    Design: Corner/calculations/statute_status_flips_to_expiring_soon_at_exactly_ninety_days_out
    """
    ctx = setup_scoped_audit(
        scope_period_start="2023-01-01", scope_period_end="2024-12-31", audit_type="FIELD"
    )
    audit_id = ctx["audit"]["id"]
    assert ctx["audit"]["base_statute_expiry_date"] == "2027-12-31"
    assert ctx["audit"]["statute_expiry_date"] == "2027-12-31"
    assert ctx["audit"]["waiver_days_added"] == 0
    assert ctx["audit"]["tolled_days"] == 0
    version_at_scoping = ctx["audit"]["version"]

    set_clock_date("2027-10-01")
    ninety_one_days_out = read_audit(audit_id)
    assert ninety_one_days_out["statute_status"] == "PROTECTED"

    set_clock_date("2027-10-02")
    ninety_days_out = read_audit(audit_id)
    assert ninety_days_out["statute_status"] == "EXPIRING_SOON"

    assert ninety_days_out["statute_expiry_date"] == "2027-12-31"
    assert ninety_days_out["version"] == version_at_scoping


def test_purchases_that_owe_nothing_are_still_recorded_and_summed():
    """An exempt input and a fully credited purchase both land at zero, not below it.

    PRD 3.5: "An `EXEMPT_MANUFACTURING` purchase takes `taxable_basis_cents` of 0 — it
    is recorded for completeness and contributes nothing."
    PRD 3.5: "`credit_applied_cents` is the smaller of `tax_paid_other_state_cents` and
    `gross_use_tax_cents`, so the credit is clamped at the gross tax and a purchase
    never produces a refund; and `use_tax_due_cents` is `gross_use_tax_cents` less
    `credit_applied_cents`."
    PRD 3.5: "The audit's `use_tax_deficiency_cents` is the sum of `use_tax_due_cents`
    over every untaxed purchase of that audit, including rows whose liability computes
    to 0."

    Design: Corner/calculations/zero_liability_purchases_still_join_the_use_tax_sum
    """
    ctx = setup_agreed_methodology()
    audit_id = ctx["audit"]["id"]

    exempt = record_purchase(
        audit_id,
        "2026-02-14",
        5_000_000,
        asset_class="EXEMPT_MANUFACTURING",
        vendor_name="Foundry Line Systems",
    )
    assert exempt["taxable_basis_cents"] == 0
    assert exempt["gross_use_tax_cents"] == 0
    assert exempt["credit_applied_cents"] == 0
    assert exempt["use_tax_due_cents"] == 0

    credited = record_purchase(
        audit_id, "2026-04-01", 76_208, tax_paid_other_state_cents=999_999
    )
    assert credited["taxable_basis_cents"] == 76_208
    assert credited["gross_use_tax_cents"] == 4_763
    assert credited["credit_applied_cents"] == 4_763
    assert credited["use_tax_due_cents"] == 0

    assert read_audit(audit_id)["use_tax_deficiency_cents"] == 0

    rows, meta = validate_paginated(
        api_client.list_audit_use_tax_purchases(
            audit_id, AUDITOR, params={"limit": 10, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_a_variance_of_exactly_two_and_a_half_basis_points_rounds_up():
    """Half-up rounding is visible on the component even when the score hides it.

    PRD 3.1: "otherwise it is the absolute difference between `reported_total_cents`
    and `matched_total_cents`, multiplied by 10,000, divided by `reported_total_cents`,
    rounded half up to a whole basis point, and then capped at 10,000."
    PRD 3.1: "A `SelectionAnalyst` may also ask for a recomputation of a single holder
    on demand, which refreshes the two totals, the four component fields and
    `screening_score` without touching anything else."

    Design: Corner/calculations/info_variance_bp_rounds_half_up_at_two_and_a_half_basis_points
    """
    taxpayer = register_taxpayer(
        legal_name="Halfpoint Hardware LLC",
        gross_receipts_annual_cents=100_000_000,
        delinquent_period_count=2,
    )
    information_return = load_information_return(
        taxpayer["id"],
        source_type="WHOLESALER_REPORT",
        period_start="2026-01-01",
        period_end="2026-03-31",
        reported_amount_cents=400_000,
        matched_return_amount_cents=399_900,
    )
    assert information_return["variance_cents"] == 100
    assert information_return["match_status"] == "UNDER_REPORTED"

    scored = rescore_screening(taxpayer["id"])
    assert scored["reported_total_cents"] == 400_000
    assert scored["matched_total_cents"] == 399_900
    # 100 * 10,000 / 400,000 is exactly 2.5 basis points, which rounds up to 3.
    assert scored["info_variance_bp"] == 3
    assert scored["delinquency_bp"] == 5_000
    assert scored["screening_score"] == 200

    # Recomputation is stable rather than cumulative.
    rescore_screening(taxpayer["id"])
    assert read_taxpayer(taxpayer["id"])["info_variance_bp"] == 3


def test_a_delinquent_taxpayer_is_capped_at_half_the_penalty():
    """Seventy-five earned points are capped to fifty before any money is computed.

    PRD 3.7: "`FIRST_TIME_COMPLIANT` contributes 40 points,
    `RELIANCE_ON_WRITTEN_ADVICE` 35, `RECORDS_LOST_IN_DISASTER` 25 and
    `SUBSTANTIAL_COOPERATION` 20; the points of every supplied factor are added
    together and the sum is capped at 100, so all four factors together give 120 points
    and yield an `abatement_pct` of 100."
    PRD 3.7: "Second, if the taxpayer's `compliance_status` is `DELINQUENT` the
    `abatement_pct` is capped at 50, so a delinquent taxpayer who earned 60 points
    receives 50 and one who earned 40 still receives 40; the cap lowers a percentage,
    it never raises one."
    PRD 3.7: "The abated amount is `penalty_cents` multiplied by `abatement_pct`,
    divided by 100 and rounded half up, and it is computed against the **original**
    `penalty_cents` stored on the assessment rather than against any penalty net of an
    earlier abatement."

    Design: Corner/calculations/abatement_points_cap_at_fifty_percent_for_a_delinquent_taxpayer
    """
    ctx = setup_issued_assessment(
        tax_deficiency_cents=4_763,
        taxpayer_overrides={"compliance_status": "DELINQUENT"},
    )
    assessment_id = ctx["assessment"]["id"]
    assert ctx["assessment"]["penalty_cents"] == 238
    assert ctx["assessment"]["total_due_cents"] == 5_001

    abate_penalty(
        assessment_id, ["FIRST_TIME_COMPLIANT", "RELIANCE_ON_WRITTEN_ADVICE"]
    )

    assessment = read_assessment(assessment_id)
    assert assessment["penalty_cents"] == 238
    assert assessment["total_due_cents"] == 5_001
    # 238 * 50 / 100 rounded half up, not 238 * 75 / 100.
    assert assessment["total_abated_cents"] == 119
    assert assessment["total_adjustments_cents"] == 119
    assert assessment["balance_due_cents"] == 4_882

    rows = list_adjustments(assessment_id=assessment_id, kind="PENALTY_ABATEMENT")
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 119
    assert rows[0]["abatement_pct"] == 50
    assert rows[0]["source"] == "SYSTEM"
    assert rows[0]["status"] == "POSTED"
