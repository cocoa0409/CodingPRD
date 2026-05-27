"""Maintenance fee lifecycle: on-time vs late base+surcharge calculation,
the three-window ordering constraint, the window-closed temporal validation,
and the lapse-cascade-to-EXPIRED cross-entity invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, run_sweep,
    setup_application_in_issued, setup_utility_with_maintenance_fees,
    setup_utility_at_w1_due_date,
    list_maintenance_fees, pay_maintenance,
    create_applicant, create_application,
    pay_filing_fee, docket_application, issue_office_action, pay_issue_fee,
    create_fee_payment_payload,
    maintenance_base_fee_cents, maintenance_late_surcharge_cents,
)


# =============================================================================
# Difficulty / dual_variant_calc / maintenance_fee_on_time_vs_late_diverges
# =============================================================================

def test_maintenance_w1_small_on_time_payment_exact_base_only(api):
    """For a SMALL-entity issued UTILITY whose W1 due_date is 2024-01-01,
    paying on the due date exactly with amount_cents=base only (100000 cents
    SMALL W1) is ACCEPTED. No surcharge applies.

    PRD §3.8: "if the server's `current_utc` is on or before `window_due_date`,
    no surcharge applies and the expected payment is simply the base..."

    Design: Difficulty/dual_variant_calc/maintenance_fee_on_time_vs_late_diverges
    """
    applicant, application, fees = setup_utility_at_w1_due_date(
        entity_size="SMALL",
        issue_clock="2020-01-01T00:00:00.000Z",
        w1_due_clock="2024-01-01T00:00:00.000Z",
    )
    w1 = fees[0]
    expected = maintenance_base_fee_cents(1, "SMALL")
    assert expected == 100000

    payment_res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W1",
            amount_cents=expected,
            maintenance_fee_id=w1["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(payment_res, 201)
    assert fee_payment["payment_status"] == "POSTED"
    assert fee_payment["amount_cents"] == 100000

    w1_after = validate_success(
        api.get_maintenance_fee(w1["id"], make_applicant_headers(applicant["id"])),
        200,
    )
    assert w1_after["fee_status"] == "PAID"


def test_maintenance_w1_small_late_payment_requires_base_plus_surcharge(api):
    """For the same SMALL UTILITY, paying after the due date (within grace)
    must equal base + surcharge: 100000 + (16000 * 0.5) = 108000 cents.

    PRD §3.8: "if `current_utc` is strictly after `window_due_date` but on
    or before `window_grace_date`, a surcharge applies, computed by
    multiplying `LATE_SURCHARGE_BASE_CENTS` of 16,000 cents by the entity
    multiplier and rounding the result to the nearest cent with round-half-up,
    then added to the base."

    Design: Difficulty/dual_variant_calc/maintenance_fee_on_time_vs_late_diverges
    """
    applicant, application, fees = setup_utility_at_w1_due_date(
        entity_size="SMALL",
        issue_clock="2020-01-01T00:00:00.000Z",
        # Set clock 30 days past W1 due → within grace (grace = due + 6mo).
        w1_due_clock="2024-01-31T00:00:00.000Z",
    )
    w1 = fees[0]
    base = maintenance_base_fee_cents(1, "SMALL")
    surcharge = maintenance_late_surcharge_cents("SMALL")
    expected = base + surcharge
    assert expected == 108000

    payment_res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W1",
            amount_cents=expected,
            maintenance_fee_id=w1["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(payment_res, 201)
    assert fee_payment["payment_status"] == "POSTED"
    assert fee_payment["amount_cents"] == 108000


# =============================================================================
# Difficulty / combinatorial_formula / maintenance_fee_three_input_nonlinear
# =============================================================================

def test_maintenance_w2_micro_on_time_base_amount_posts(api):
    """MICRO-entity UTILITY issued 2018-01-01: W1 (base MICRO = 40000) paid
    on time at 2022-01-01; then clock to 2026-01-01 (W2 due) and W2 paid at
    base MICRO 75200 (376000*0.2 round-half-up) — base-only, no surcharge.

    PRD §3.7: "Each row's `base_fee_cents` is computed at the moment of
    issuance: the base in cents is 200,000 for window 1, 376,000 for
    window 2, and 772,000 for window 3; that base is multiplied by the
    entity multiplier at issuance time and rounded with round-half-up."

    Design: Difficulty/combinatorial_formula/maintenance_fee_three_input_nonlinear
    """
    # Walk fully to ISSUED with custom clock (W1 due = issue + 4y = 2022-01-01).
    set_clock("2018-01-01T00:00:00.000Z")
    applicant = create_applicant(
        legal_name="Micro M", entity_size="MICRO",
        micro_qualifying_year=2017, gross_income_prior_year_cents=5000000,
        prior_applications_filed=0,
    )
    application = create_application(applicant, application_type="UTILITY",
                                     title="MUtility", claim_count=10,
                                     independent_claim_count=2)
    pay_filing_fee(applicant, application)  # 6400 MICRO UTILITY
    docket_application(application["id"])
    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")
    issued = pay_issue_fee(applicant, application)
    fees = list_maintenance_fees(issued["id"], applicant)
    fees_sorted = sorted(fees, key=lambda f: f["window_number"])
    w1, w2 = fees_sorted[0], fees_sorted[1]

    # Pay W1 on time
    set_clock("2022-01-01T00:00:00.000Z")
    base_w1_micro = maintenance_base_fee_cents(1, "MICRO")
    assert base_w1_micro == 40000
    pay_maintenance(applicant, application["id"], w1["id"],
                    "MAINTENANCE_W1", base_w1_micro)

    # Pay W2 on time at base MICRO
    set_clock("2026-01-01T00:00:00.000Z")
    expected_w2 = maintenance_base_fee_cents(2, "MICRO")
    assert expected_w2 == 75200

    pay_res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W2",
            amount_cents=expected_w2,
            maintenance_fee_id=w2["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(pay_res, 201)
    assert fee_payment["payment_status"] == "POSTED"
    assert fee_payment["amount_cents"] == 75200

    w2_after = validate_success(
        api.get_maintenance_fee(w2["id"], make_applicant_headers(applicant["id"])),
        200,
    )
    assert w2_after["fee_status"] == "PAID"


def test_maintenance_w2_micro_late_payment_requires_base_plus_micro_surcharge(api):
    """The late surcharge is independently discounted at MICRO 0.20 — for W2
    MICRO that means base 75200 + surcharge round_half_up(16000*0.2)=3200,
    expected total 78400 cents.

    PRD §3.8: "The two rounds happen independently — the base is rounded
    once at issuance, the surcharge is rounded once at payment time, and the
    two integer cents are summed."

    Design: Difficulty/combinatorial_formula/maintenance_fee_three_input_nonlinear
    """
    set_clock("2018-01-01T00:00:00.000Z")
    applicant = create_applicant(
        legal_name="Micro Late", entity_size="MICRO",
        micro_qualifying_year=2017, gross_income_prior_year_cents=5000000,
        prior_applications_filed=0,
    )
    application = create_application(applicant, application_type="UTILITY",
                                     title="MUtilityLate", claim_count=10,
                                     independent_claim_count=2)
    pay_filing_fee(applicant, application)
    docket_application(application["id"])
    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")
    issued = pay_issue_fee(applicant, application)
    fees_sorted = sorted(list_maintenance_fees(issued["id"], applicant),
                         key=lambda f: f["window_number"])
    w1, w2 = fees_sorted[0], fees_sorted[1]

    set_clock("2022-01-01T00:00:00.000Z")
    pay_maintenance(applicant, application["id"], w1["id"],
                    "MAINTENANCE_W1", maintenance_base_fee_cents(1, "MICRO"))

    # W2 due 2026-01-01; advance 30 days past due → within grace.
    set_clock("2026-01-31T00:00:00.000Z")
    base = maintenance_base_fee_cents(2, "MICRO")
    surcharge = maintenance_late_surcharge_cents("MICRO")
    expected = base + surcharge
    assert expected == 78400

    pay_res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W2",
            amount_cents=expected,
            maintenance_fee_id=w2["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(pay_res, 201)
    assert fee_payment["payment_status"] == "POSTED"
    assert fee_payment["amount_cents"] == 78400


# =============================================================================
# Corner / state_machines / pay_maintenance_w2_before_w1_paid_out_of_order
# =============================================================================

def test_pay_maintenance_w2_while_w1_still_pending_rejected(api):
    """Paying W2 while W1 is still PENDING is rejected with
    ERR_MAINTENANCE_OUT_OF_ORDER.

    PRD §3.8: "Fourth, the windows must be paid in order: a payment for
    window N is permitted only when every earlier window on the same
    application is already `PAID`; an attempt to pay window 2 while window
    1 is still `PENDING`, or window 3 while window 1 or 2 is still
    `PENDING`, is rejected with `ERR_MAINTENANCE_OUT_OF_ORDER`."

    Design: Corner/state_machines/pay_maintenance_w2_before_w1_paid_out_of_order
    """
    set_clock("2020-01-01T00:00:00.000Z")
    applicant, application, fees = setup_utility_with_maintenance_fees(
        entity_size="LARGE")
    w2 = sorted(fees, key=lambda f: f["window_number"])[1]

    # Advance to within W2 window
    set_clock("2028-01-01T00:00:00.000Z")
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W2",
            amount_cents=376000,  # LARGE W2 base
            maintenance_fee_id=w2["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MAINTENANCE_OUT_OF_ORDER.value)
