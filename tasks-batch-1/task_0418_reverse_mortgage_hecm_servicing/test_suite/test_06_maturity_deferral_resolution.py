"""Maturity events, the non-borrowing-spouse deferral chain, validation-priority
conflicts, and the payoff / short-sale / foreclosure resolution paths.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_borrower_headers,
    setup_lender_with_plf,
    create_borrower,
    create_loan,
    originate,
    setup_originated_loc_base_loan,
    setup_loan_with_qualified_nbs,
    setup_due_and_payable_loan,
    setup_deferred_loan,
    setup_settled_resolution,
    request_disbursement,
    record_maturity_event,
)

_SO = TEST_USERS["servicer_ops_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# transitive_cascade / death_to_due_and_payable_to_deferral_to_void_draw_depth3
# ---------------------------------------------------------------------------
def test_death_cascade_voids_draw_freezes_line_and_defers(api):
    """PRD §3.9: "Every disbursement on the loan still in `REQUESTED` or `APPROVED` —
    that is, every draw not yet `DISBURSED` — is voided as part of this cascade,
    with its `approved_amount_cents` reset to 0; draws already `DISBURSED` are
    left untouched."
    PRD §3.9: "The loan's `available_line_of_credit_cents` is frozen to 0, because no
    further credit may be drawn once the loan is due and payable."
    PRD §3.10: "The loan's `disposition_status` moves from `DUE_AND_PAYABLE` to `DEFERRED`,
    which freezes the disposition while the spouse remains."

    Design: Difficulty/transitive_cascade/death_to_due_and_payable_to_deferral_to_void_draw_depth3
    """
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(draw_type="LINE_OF_CREDIT")
    disb = request_disbursement(loan["id"], requested_amount_cents=2000000,
                                headers=make_borrower_headers(borrower["id"]))
    event = record_maturity_event(loan["id"], event_type="BORROWER_DEATH",
                                  event_date="2025-01-10")
    # Hop: maturity cascade voided the still-REQUESTED draw + froze the line.
    disb_after = validate_success(api.get_disbursement(disb["id"], _SO))
    assert disb_after["status"] == "VOIDED"
    loan_dap = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_dap["available_line_of_credit_cents"] == 0

    deferral = validate_success(api.create_nbs_deferral(
        {"loan_id": loan["id"], "borrower_id": nbs["id"], "maturity_event_id": event["id"]},
        _CO), expected_status=201)
    loan_def = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_def["disposition_status"] == "DEFERRED"
    assert deferral["status"] == "ACTIVE"


def test_death_deferral_period_start_is_event_date(api):
    """PRD §3.10: "When a deferral is opened, its `status` is `ACTIVE`, its `period_start` is set
    to the triggering maturity event's `event_date`, and its `period_end` is
    null while active."

    Design: Difficulty/transitive_cascade/death_to_due_and_payable_to_deferral_to_void_draw_depth3
    """
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(draw_type="LINE_OF_CREDIT")
    event = record_maturity_event(loan["id"], event_type="BORROWER_DEATH",
                                  event_date="2025-01-10")
    deferral = validate_success(api.create_nbs_deferral(
        {"loan_id": loan["id"], "borrower_id": nbs["id"], "maturity_event_id": event["id"]},
        _CO), expected_status=201)
    assert deferral["status"] == "ACTIVE"
    assert deferral["period_start"] == "2025-01-10"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_fiscal_on_disbursement_approve
# ---------------------------------------------------------------------------
def test_state_beats_fiscal_on_disbursement_approve(api):
    """PRD §3.5: "First, the loan must be drawable — `disposition_status` `ACTIVE` and
    `servicing_status` `CURRENT` at the same time — or the approval is
    rejected with `ERR_LOAN_NOT_DRAWABLE` (HTTP 409)."
    PRD §3.5: "Third, the `requested_amount_cents` must be less than or equal to the
    loan's `available_line_of_credit_cents` — drawing exactly the full available
    line is allowed, and only a request strictly greater than the line is
    rejected, with `ERR_INSUFFICIENT_LINE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement_approve
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    # Request a draw way over the line while the loan is still drawable (so it is
    # accepted at request time and stays REQUESTED).
    disb = request_disbursement(loan["id"], requested_amount_cents=99000000)
    # Make the loan not-drawable on the SERVICING axis without voiding the draw:
    # open a year-1 occupancy cert (due 2025-01-01) and advance the clock past it,
    # which lapses the cert via the §3.1 sweep and flips servicing_status to
    # DELINQUENT_OCCUPANCY while leaving disposition_status ACTIVE (so the still-
    # REQUESTED draw is not swept/voided — a maturity event WOULD void it, which
    # is why this test uses the servicing path instead).
    validate_success(api.create_occupancy_certification(
        {"loan_id": loan["id"], "certification_year": 1}, _SO), expected_status=201)
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2025-02-01T00:00:00.000Z"}, _SO))
    drawable = validate_success(api.get_loan(loan["id"], _SO))
    assert drawable["servicing_status"] == "DELINQUENT_OCCUPANCY"
    assert drawable["disposition_status"] == "ACTIVE"
    # Approve: the §3.5 "First, loan must be drawable" business check
    # (ERR_LOAN_NOT_DRAWABLE) fires before the §3.5 "Third, over-line" fiscal
    # check (ERR_INSUFFICIENT_LINE).
    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_LOAN_NOT_DRAWABLE.value)


def test_fiscal_check_fires_when_state_passes_on_approve(api):
    """PRD §3.5: "the `requested_amount_cents` must be less than or equal to the loan's
    `available_line_of_credit_cents` — drawing exactly the full available line
    is allowed, and only a request strictly greater than the line is rejected,
    with `ERR_INSUFFICIENT_LINE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement_approve
    """
    # On a drawable (ACTIVE/CURRENT) loan, the state check passes and the fiscal
    # over-line check fires — confirming p15 is reached only once p7 is satisfied.
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=99000000)
    validate_error(
        api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO),
        ApiErrorId.ERR_INSUFFICIENT_LINE.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / referential_beats_temporal_on_nbs_deferral
# ---------------------------------------------------------------------------
# NOTE: A test asserting that ERR_NBS_NOT_QUALIFIED wins over
# ERR_DEFERRAL_NOT_ELIGIBLE when BOTH an unqualified spouse and a non-death
# event apply was removed here. PRD §3.10 lists the three deferral gates in
# prose ("The triggering maturity event's `event_type` must be `BORROWER_DEATH`
# ... The named spouse must be a qualifying non-borrowing spouse ...") but never
# pins the relative precedence between the event-type check and the spouse-
# qualification check. A PRD-faithful implementer reading the prose top-to-bottom
# would check event-type first and return ERR_DEFERRAL_NOT_ELIGIBLE, while
# another could check qualification first and return ERR_NBS_NOT_QUALIFIED — the
# PRD does not uniquely determine the winner (ERROR-PRECEDENCE-SILENCE), so the
# assertion was not uniquely derivable and the test was deleted.
def test_temporal_check_fires_when_referential_passes_on_deferral(api):
    """PRD §3.10: "The triggering maturity event's `event_type` must be `BORROWER_DEATH`, because
    only a death opens deferral eligibility; any other event type is rejected
    with `ERR_DEFERRAL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_nbs_deferral
    """
    # Qualified spouse (referential p9 passes) + non-death event => only the temporal
    # p10 check can fail, isolating ERR_DEFERRAL_NOT_ELIGIBLE.
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(
        draw_type="LINE_OF_CREDIT", nbs_qualifies=True)
    event = record_maturity_event(loan["id"], event_type="PERMANENT_VACANCY",
                                  event_date="2025-02-15")
    validate_error(
        api.create_nbs_deferral(
            {"loan_id": loan["id"], "borrower_id": nbs["id"], "maturity_event_id": event["id"]},
            _CO),
        ApiErrorId.ERR_DEFERRAL_NOT_ELIGIBLE.value)


# ---------------------------------------------------------------------------
# validations / nbs_deferral_with_unqualified_spouse_returns_nbs_not_qualified
# ---------------------------------------------------------------------------
def test_nbs_deferral_unqualified_spouse_returns_not_qualified(api):
    """PRD §3.10: "The named spouse must be a qualifying non-borrowing spouse — both
    `is_non_borrowing_spouse` and `nbs_qualifies` true on that borrower — or
    the request is rejected with `ERR_NBS_NOT_QUALIFIED` (HTTP 422)."

    Design: Corner/validations/nbs_deferral_with_unqualified_spouse_returns_nbs_not_qualified
    """
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(
        draw_type="LUMP_SUM", nbs_qualifies=False)
    event = record_maturity_event(loan["id"], event_type="BORROWER_DEATH",
                                  event_date="2024-06-01")
    validate_error(
        api.create_nbs_deferral(
            {"loan_id": loan["id"], "borrower_id": nbs["id"], "maturity_event_id": event["id"]},
            _CO),
        ApiErrorId.ERR_NBS_NOT_QUALIFIED.value)
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "DUE_AND_PAYABLE"


# ---------------------------------------------------------------------------
# validations / nbs_deferral_on_non_death_event_returns_deferral_not_eligible
# ---------------------------------------------------------------------------
def test_nbs_deferral_on_non_death_event_returns_not_eligible(api):
    """PRD §3.10: "The triggering maturity event's `event_type` must be `BORROWER_DEATH`, because
    only a death opens deferral eligibility; any other event type is rejected
    with `ERR_DEFERRAL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/nbs_deferral_on_non_death_event_returns_deferral_not_eligible
    """
    # Qualified NBS but a PERMANENT_VACANCY event.
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(
        draw_type="LUMP_SUM", nbs_qualifies=True)
    event = record_maturity_event(loan["id"], event_type="PERMANENT_VACANCY",
                                  event_date="2024-06-01")
    validate_error(
        api.create_nbs_deferral(
            {"loan_id": loan["id"], "borrower_id": nbs["id"], "maturity_event_id": event["id"]},
            _CO),
        ApiErrorId.ERR_DEFERRAL_NOT_ELIGIBLE.value)
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "DUE_AND_PAYABLE"


# ---------------------------------------------------------------------------
# state_machines / open_resolution_with_active_deferral_returns_deferral_active
# ---------------------------------------------------------------------------
def test_open_resolution_with_active_deferral_rejected(api):
    """PRD §3.10: "Furthermore, a loan that already has an `ACTIVE` deferral cannot have another
    opened, and this same guard prevents starting a resolution while an active
    deferral stands: such an attempt is rejected with `ERR_DEFERRAL_ACTIVE`
    (HTTP 409)."

    Design: Corner/state_machines/open_resolution_with_active_deferral_returns_deferral_active
    """
    lender, borrower, nbs, loan, event, deferral = setup_deferred_loan()
    validate_error(
        api.create_resolution({"loan_id": loan["id"], "path": "FORECLOSURE"}, _CO),
        ApiErrorId.ERR_DEFERRAL_ACTIVE.value)
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "DEFERRED"


# ---------------------------------------------------------------------------
# state_machines / acknowledge_maturity_event_moves_recorded_to_acknowledged
# ---------------------------------------------------------------------------
def test_acknowledge_maturity_event_moves_to_acknowledged(api):
    """PRD §3.9: "Once a loan is due and payable, a `ComplianceOfficer` acknowledges the
    maturity event, moving it from `RECORDED` to `ACKNOWLEDGED`;
    acknowledgement records the due-and-payable notice issuance through the
    event's `updated_at`, and is permitted only while the loan's
    `disposition_status` is `DUE_AND_PAYABLE` or `DEFERRED`."

    Design: Corner/state_machines/acknowledge_maturity_event_moves_recorded_to_acknowledged
    """
    lender, borrower, loan, event = setup_due_and_payable_loan(
        draw_type="LUMP_SUM", event_type="SALE_OF_PROPERTY")
    out = validate_success(api.acknowledge_maturity_event(event["id"], _CO))
    assert out["status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# calculations / lesser_of_payoff_foreclosure_caps_at_95pct_appraised
# ---------------------------------------------------------------------------
def test_foreclosure_payoff_caps_at_95pct_appraised(api):
    """PRD §3.11: "On the `FORECLOSURE` branch the `payoff_amount_cents` is the smaller of the
    balance and 95% of the loan's original `appraised_value_cents` (that
    original value multiplied by 95, divided by 100, rounded half up to whole
    cents), and the `deficiency_cents` is the balance less that
    `payoff_amount_cents`."

    Design: Corner/calculations/lesser_of_payoff_foreclosure_caps_at_95pct_appraised
    """
    # PLF 1000000 makes gross == max_claim 30000000; LUMP_SUM advances net 29000000
    # so balance = 1000000 costs + 29000000 = 30000000 (above the 95% cap of 28500000).
    lender = setup_lender_with_plf(plf_overrides={"age": 75, "expected_rate_bps": 500,
                                                  "factor_micros": 1000000})
    borrower = create_borrower(lender["id"], full_name="Hank Borrower")
    loan = create_loan(lender["id"], borrower["id"], appraised_value_cents=30000000,
                       expected_rate_bps=500, draw_type="LUMP_SUM",
                       initial_financed_costs_cents=1000000)
    loan = originate(loan["id"])
    assert loan["principal_balance_cents"] == 30000000
    record_maturity_event(loan["id"], event_type="PERMANENT_VACANCY", event_date="2024-06-01")
    res = validate_success(api.create_resolution(
        {"loan_id": loan["id"], "path": "FORECLOSURE"}, _CO), expected_status=201)
    assert res["payoff_amount_cents"] == 28500000
    assert res["deficiency_cents"] == 1500000


# ---------------------------------------------------------------------------
# state_machines / settle_resolution_twice_second_returns_invalid_state
# ---------------------------------------------------------------------------
def test_settle_resolution_twice_second_returns_invalid_state(api):
    """PRD §3.11: "Settlement is terminal and is performed by a `ComplianceOfficer` on
    an `INITIATED` resolution while the loan is `IN_RESOLUTION`"
    PRD §2.10: "and fifth, that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/settle_resolution_twice_second_returns_invalid_state
    """
    lender, borrower, loan, res = setup_settled_resolution(path="PAYOFF", draw_type="LUMP_SUM")
    assert res["status"] == "SETTLED"
    validate_error(api.settle_resolution(res["id"], _CO), ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_resolution(res["id"], _CO))
    assert reread["status"] == "SETTLED"
