"""The two independent loan state axes and the multi-hop cascades driven by
clock sweeps and maturity events.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_originated_loc_base_loan,
    setup_loan_with_pending_cert,
    request_disbursement,
)

_SO = TEST_USERS["servicer_ops_headers"]
_CO = TEST_USERS["compliance_officer_headers"]
_SYS = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / loan_parallel_axes_servicing_vs_disposition_independent
# ---------------------------------------------------------------------------
def test_loan_axes_move_independently(api):
    """PRD §2.6: "A loan may be `DELINQUENT_OCCUPANCY` on the servicing axis while remaining
    `ACTIVE` on the disposition axis; conversely, a maturity event advances
    the disposition axis to `DUE_AND_PAYABLE` without disturbing the servicing
    axis."

    Design: Difficulty/non_linear_state_machine/loan_parallel_axes_servicing_vs_disposition_independent
    """
    lender, borrower, loan, cert = setup_loan_with_pending_cert()
    # Drive the cert delinquent: the year-1 cert's due_date is the origination
    # anniversary (2025-01-01). Per PRD §3.7 a certification only lapses once the
    # clock is strictly later than its due_date; advancing the clock past it runs
    # the §3.1 occupancy sweep, which moves the PENDING cert to DELINQUENT and
    # flips the loan's servicing axis to DELINQUENT_OCCUPANCY (disposition axis
    # stays ACTIVE).
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SO))
    after_delinquent = validate_success(api.get_loan(loan["id"], _SO))
    assert after_delinquent["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert after_delinquent["disposition_status"] == "ACTIVE"

    # A maturity event flips disposition; servicing axis is unchanged.
    validate_success(api.create_maturity_event(
        {"loan_id": loan["id"], "event_type": "PERMANENT_VACANCY", "event_date": "2025-02-15"},
        _CO), expected_status=201)
    after_maturity = validate_success(api.get_loan(loan["id"], _SO))
    assert after_maturity["disposition_status"] == "DUE_AND_PAYABLE"
    assert after_maturity["servicing_status"] == "DELINQUENT_OCCUPANCY"


def test_maturity_event_does_not_reset_servicing_axis(api):
    """PRD §2.6: "These axes move independently."
    PRD §3.9: "There is one further conditional cascade: when the `event_type` is
    `TAX_INSURANCE_DEFAULT` and the loan's set-aside has a `remaining_cents`
    of 0 (the pool is exhausted), the loan's `servicing_status` flips to
    `DELINQUENT_PROPERTY_CHARGE` on the independent servicing axis."

    Design: Difficulty/non_linear_state_machine/loan_parallel_axes_servicing_vs_disposition_independent
    """
    lender, borrower, loan, cert = setup_loan_with_pending_cert()
    # Drive the cert delinquent via the clock-advance sweep (year-1 due_date is
    # 2025-01-01; advancing past it lapses the cert per PRD §3.1/§3.7 and flips
    # the loan's servicing axis to DELINQUENT_OCCUPANCY).
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SO))
    validate_success(api.create_maturity_event(
        {"loan_id": loan["id"], "event_type": "PERMANENT_VACANCY", "event_date": "2025-02-15"},
        _CO), expected_status=201)
    reread = validate_success(api.get_loan(loan["id"], _SO))
    assert reread["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert reread["disposition_status"] == "DUE_AND_PAYABLE"


# ---------------------------------------------------------------------------
# transitive_cascade / cert_lapse_to_loan_servicing_delinquent_depth2
# ---------------------------------------------------------------------------
def test_clock_sweep_lapses_cert_and_flips_servicing(api):
    """PRD §3.7: "the clock-advance sweep of §3.1 moves any `PENDING` certification
    whose `due_date` is now earlier than the new clock date to `DELINQUENT`"
    PRD §3.7: "When a certification lapses to `DELINQUENT`, the system cascades onto the
    loan's servicing axis: a loan whose `servicing_status` is `CURRENT` flips
    to `DELINQUENT_OCCUPANCY`."

    Design: Difficulty/transitive_cascade/cert_lapse_to_loan_servicing_delinquent_depth2
    """
    lender, borrower, loan, cert = setup_loan_with_pending_cert(certification_year=1)
    # cert due_date is the year-1 anniversary (2025-01-01). Advance clock past it.
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SYS))
    cert_after = validate_success(api.get_occupancy_certification(cert["id"], _SO))
    assert cert_after["status"] == "DELINQUENT"
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert loan_after["disposition_status"] == "ACTIVE"


def test_clock_sweep_leaves_disposition_axis_unchanged(api):
    """PRD §3.7: "This cascade does not disturb the disposition axis."

    Design: Difficulty/transitive_cascade/cert_lapse_to_loan_servicing_delinquent_depth2
    """
    lender, borrower, loan, cert = setup_loan_with_pending_cert(certification_year=1)
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SYS))
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "ACTIVE"
    assert loan_after["servicing_status"] == "DELINQUENT_OCCUPANCY"


# ---------------------------------------------------------------------------
# cross_cutting / maturity_event_cascades_due_and_payable_voids_pending_draw_freezes_line
# ---------------------------------------------------------------------------
def test_maturity_event_cascade_voids_pending_draw_and_freezes_line(api):
    """PRD §3.9: "Every disbursement on the loan still in `REQUESTED` or `APPROVED` —
    that is, every draw not yet `DISBURSED` — is voided as part of this cascade,
    with its `approved_amount_cents` reset to 0; draws already `DISBURSED` are
    left untouched."
    PRD §3.9: "The loan's `available_line_of_credit_cents` is frozen to 0, because no
    further credit may be drawn once the loan is due and payable."

    Design: Corner/cross_cutting/maturity_event_cascades_due_and_payable_voids_pending_draw_freezes_line
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    disb = request_disbursement(loan["id"], requested_amount_cents=100000)
    validate_success(api.create_maturity_event(
        {"loan_id": loan["id"], "event_type": "SALE_OF_PROPERTY", "event_date": "2024-06-01"},
        _CO), expected_status=201)
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "DUE_AND_PAYABLE"
    assert loan_after["available_line_of_credit_cents"] == 0
    disb_after = validate_success(api.get_disbursement(disb["id"], _SO))
    assert disb_after["status"] == "VOIDED"
