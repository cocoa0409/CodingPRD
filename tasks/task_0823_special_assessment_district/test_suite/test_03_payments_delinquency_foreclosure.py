"""Payments and reversal, the payoff cascade, delinquency charges, and foreclosure forks.

Covers difficulty instances payment_payoff_paidoff_lien_release_depth3,
principal_conservation_under_payment_then_reversal, delinquency_marks_exactly_at_due_plus_grace,
parcel_active_foreclosure_active_cycle, foreclosure_judgment_fork_to_sale,
state_beats_fiscal_on_cancelled_installment_payment, and corner instances for delinquency
values, the foreclosure threshold, payment-amount mismatch, and paying a scheduled installment.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_issued_bond, setup_foreclosure_at_judgment, set_clock,
    get_parcel_installment, refresh_parcel, refresh_installment,
    list_parcel_liens, get_bond, get_foreclosure, parcel_version,
    pay_installment, create_payoff_quote, advance_foreclosure_payload,
    get_success_data,
)

ADMIN = TEST_USERS["admin_headers"]
TREAS = TEST_USERS["treasurer_headers"]


# --- depth-3 cascade: payment -> installment PAID -> parcel PAID_OFF -> lien RELEASED ---

def _setup_single_due_term1(api, cost, clock="2027-07-01T00:00:00Z"):
    _, parcels, _, bond = setup_issued_bond(
        api, parcels=[{"apn": "C-1", "owner_name": "OC", "benefit_units": 100}],
        total_project_cost_cents=cost, roll_method="BENEFIT_UNITS", bond={"term_years": 1},
    )
    if clock:
        set_clock(api, clock)
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    return parcels[0], bond, inst


def test_final_payment_pays_installment_and_zeroes_principal(api):
    """PRD §3.5: "A successful payment advances the installment from `DUE` to `PAID` (or from
    `DELINQUENT` to `PAID` when redeeming a delinquent charge) and debits the parcel's
    `remaining_principal_cents` by the installment's `principal_cents`." PRD §3.5: "When the
    debit drives the parcel's `remaining_principal_cents` to 0, the parcel's payoff cascade fires".

    Design: Difficulty/transitive_cascade/payment_payoff_paidoff_lien_release_depth3
    """
    parcel, _, inst = _setup_single_due_term1(api, cost=1_000_000)
    pay_installment(api, inst["id"], amount_cents=1050000, payment_date="2027-07-01T00:00:00Z", paid_by="OC")
    assert refresh_installment(api, inst["id"])["status"] == "PAID"
    assert refresh_parcel(api, parcel["id"])["remaining_principal_cents"] == 0


def test_final_payment_pays_off_parcel_and_releases_liens(api):
    """PRD §3.5: "Reaching a `remaining_principal_cents` of 0 transitions the parcel from
    `ACTIVE` to `PAID_OFF`. That cascade releases every unreleased `Lien` on the parcel
    (moving each `RECORDED` lien to `RELEASED`)".

    Design: Difficulty/transitive_cascade/payment_payoff_paidoff_lien_release_depth3
    """
    parcel, _, inst = _setup_single_due_term1(api, cost=1_000_000)
    pay_installment(api, inst["id"], amount_cents=1050000, payment_date="2027-07-01T00:00:00Z", paid_by="OC")
    assert refresh_parcel(api, parcel["id"])["status"] == "PAID_OFF"
    liens = list_parcel_liens(api, parcel["id"])
    assert liens, "expected at least one lien on the assessed parcel"
    assert all(lien["status"] == "RELEASED" for lien in liens)


# --- principal conservation across payment then reversal ---

def _setup_two_parcels_due(api):
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[
            {"apn": "CP-1", "owner_name": "O1", "benefit_units": 60},
            {"apn": "CP-2", "owner_name": "O2", "benefit_units": 40},
        ],
        total_project_cost_cents=10_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 10},
    )
    set_clock(api, "2027-07-01T00:00:00Z")
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    payment = pay_installment(api, inst["id"], amount_cents=777027,
                              payment_date="2027-07-01T00:00:00Z", paid_by="O1")
    return parcels, payment


def test_payment_reversal_restores_parcel_principal(api):
    """PRD §3.5: "A CountyTreasurer may reverse a prior payment as a compensating action.
    Reversal marks the payment's reversed flag true ... and credits the parcel's
    remaining_principal_cents back by the installment's principal_cents."

    Design: Difficulty/compensating_invariant/principal_conservation_under_payment_then_reversal
    """
    parcels, payment = _setup_two_parcels_due(api)
    get_success_data(api.reverse_payment(payment["id"], TREAS))
    assert refresh_parcel(api, parcels[0]["id"])["remaining_principal_cents"] == 6000000
    assert refresh_parcel(api, parcels[1]["id"])["remaining_principal_cents"] == 4000000


def test_payment_reversal_conserves_total_principal(api):
    """PRD §2.9: "every principal payment debits the parcel ledger by exactly the
    installment's principal component — no cent is ever created or lost." PRD §3.5:
    "credits the parcel's remaining_principal_cents back by the installment's principal_cents."

    Design: Difficulty/compensating_invariant/principal_conservation_under_payment_then_reversal
    """
    parcels, payment = _setup_two_parcels_due(api)
    get_success_data(api.reverse_payment(payment["id"], TREAS))
    total = (refresh_parcel(api, parcels[0]["id"])["remaining_principal_cents"]
             + refresh_parcel(api, parcels[1]["id"])["remaining_principal_cents"])
    assert total == 10000000


# --- delinquency grace boundary (>= due_date + 30 days) ---

def test_mark_delinquent_at_exact_grace_boundary_succeeds(api):
    """PRD §3.6: "a grace period of 30 days must have elapsed, meaning the logical clock
    must be at or past the installment's due_date plus 30 days". PRD §3.6: "The one-time
    penalty_cents is that base multiplied by ten percent (0.10), rounded half up."

    Design: Difficulty/boundary_precision_check/delinquency_marks_exactly_at_due_plus_grace
    """
    _, _, inst = _setup_single_due_term1(api, cost=1_000_000, clock="2027-07-31T00:00:00Z")
    result = get_success_data(api.mark_delinquent(inst["id"], TREAS))
    assert result["status"] == "DELINQUENT"
    assert result["penalty_cents"] > 0


def test_mark_delinquent_one_day_before_grace_rejected(api):
    """PRD §3.6: "a grace period of 30 days must have elapsed, meaning the logical clock
    must be at or past the installment's due_date plus 30 days, or the request is rejected
    with ERR_GRACE_NOT_ELAPSED (HTTP 409)."

    Design: Difficulty/boundary_precision_check/delinquency_marks_exactly_at_due_plus_grace
    """
    _, _, inst = _setup_single_due_term1(api, cost=1_000_000, clock="2027-07-30T00:00:00Z")
    validate_error(api.mark_delinquent(inst["id"], TREAS), ApiErrorId.ERR_GRACE_NOT_ELAPSED.value)


# --- foreclosure fork: JUDGMENT -> REDEEMED (parcel cycles back to ACTIVE) ---

def test_foreclosure_redeem_reaches_redeemed_status(api):
    """PRD §3.8: "From JUDGMENT to REDEEMED: permitted only when the foreclosure is JUDGMENT.
    This is the divergent recovery branch by which the owner redeems."

    Design: Difficulty/non_linear_state_machine/parcel_active_foreclosure_active_cycle
    """
    _, parcel, _, foreclosure, _ = setup_foreclosure_at_judgment(api)
    result = get_success_data(api.advance_foreclosure(foreclosure["id"],
                                                      advance_foreclosure_payload("REDEEMED"), TREAS))
    assert result["status"] == "REDEEMED"


def test_foreclosure_redeem_returns_parcel_to_active(api):
    """PRD §3.8: "every `DELINQUENT` installment of the parcel transitions to `PAID` —
    redemption settles them — and the parcel's `remaining_principal_cents` is debited by each
    such installment's `principal_cents`; ... and the parcel cascades from `IN_FORECLOSURE`
    back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/parcel_active_foreclosure_active_cycle
    """
    _, parcel, _, foreclosure, _ = setup_foreclosure_at_judgment(api)
    get_success_data(api.advance_foreclosure(foreclosure["id"],
                                             advance_foreclosure_payload("REDEEMED"), TREAS))
    assert refresh_parcel(api, parcel["id"])["status"] == "ACTIVE"


# --- foreclosure fork: JUDGMENT -> SALE (defaults installments, liens, bond) ---

def test_foreclosure_sale_defaults_bond(api):
    """PRD §3.8: "every `RECORDED` `Lien` of the parcel transitions to `FORECLOSED`; and the
    parent `ImprovementBond` transitions from `ISSUED` to `DEFAULTED`."

    Design: Difficulty/non_linear_state_machine/foreclosure_judgment_fork_to_sale
    """
    district, parcel, bond, foreclosure, _ = setup_foreclosure_at_judgment(api)
    result = get_success_data(api.advance_foreclosure(foreclosure["id"],
                                                      advance_foreclosure_payload("SALE"), TREAS))
    assert result["status"] == "SALE"
    assert get_bond(api, district["id"], bond["id"])["status"] == "DEFAULTED"


def test_foreclosure_sale_keeps_parcel_in_foreclosure(api):
    """PRD §3.8: "From JUDGMENT to SALE ... The parcel remains IN_FORECLOSURE; every
    DELINQUENT installment of the parcel transitions to the terminal DEFAULTED".

    Design: Difficulty/non_linear_state_machine/foreclosure_judgment_fork_to_sale
    """
    _, parcel, _, foreclosure, _ = setup_foreclosure_at_judgment(api)
    get_success_data(api.advance_foreclosure(foreclosure["id"],
                                             advance_foreclosure_payload("SALE"), TREAS))
    assert refresh_parcel(api, parcel["id"])["status"] == "IN_FORECLOSURE"


# --- validation precedence: state check beats fiscal amount check ---

def _setup_paidoff_with_cancelled_installment(api):
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[{"apn": "P-1", "owner_name": "OP", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 2},
    )
    parcel = parcels[0]
    quote = validate_success(
        create_payoff_quote(api, parcel["id"], "IMMEDIATE", "2026-08-01T00:00:00Z",
                            parcel_version(api, parcel["id"]), headers=TREAS), 201)
    get_success_data(api.honor_payoff_quote(quote["id"], TREAS))
    inst = get_parcel_installment(api, parcel["id"], 1)
    return parcel, inst


def test_payment_on_cancelled_installment_reports_state_error(api):
    """PRD §3.5: "a CANCELLED, PAID, or DEFAULTED installment can never be paid, so any of
    these yields ERR_INSTALLMENT_NOT_PAYABLE (HTTP 409)." PRD §2.10: "an illegal state
    before ... the fiscal exact-amount check on payments".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_installment_payment
    """
    _, inst = _setup_paidoff_with_cancelled_installment(api)
    assert inst["status"] == "CANCELLED"
    payload = {"amount_cents": 999, "payment_date": "2026-08-02T00:00:00Z", "paid_by": "OP"}
    validate_error(api.create_payment(inst["id"], payload, TREAS),
                   ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value)


def test_payment_on_cancelled_installment_not_reported_as_amount_mismatch(api):
    """PRD §2.10: "checks are evaluated in a fixed priority order and the first failure is
    the one reported. The order is: ... then resource-state legality of the requested
    transition (the family of 409 invalid-state errors) ... and finally ... the fiscal
    exact-amount check on payments (ERR_PAYMENT_AMOUNT_MISMATCH, HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_installment_payment
    """
    _, inst = _setup_paidoff_with_cancelled_installment(api)
    payload = {"amount_cents": 999, "payment_date": "2026-08-02T00:00:00Z", "paid_by": "OP"}
    err = validate_error(api.create_payment(inst["id"], payload, TREAS),
                         ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value)
    assert err["error_id"] != ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value


# --- corner: delinquency penalty + redemption interest values ---

def test_delinquency_charges_penalty_and_redemption_interest(api):
    """PRD §3.6: "The one-time penalty_cents is that base multiplied by ten percent (0.10),
    rounded half up. ... the redemption interest is the base multiplied by one and one-half
    percent (0.015) per whole month late ... rounded half up. The installment's
    amount_due_cents is then recomputed as the base plus penalty_cents plus
    redemption_interest_cents."

    Design: Corner/calculations/delinquency_penalty_and_redemption_interest_values
    """
    _, _, inst = _setup_single_due_term1(api, cost=1_000_000, clock="2027-08-01T00:00:00Z")
    result = get_success_data(api.mark_delinquent(inst["id"], TREAS))
    assert result["penalty_cents"] == 105000
    assert result["redemption_interest_cents"] == 15750
    assert result["amount_due_cents"] == 1170750


# --- corner: foreclosure below the delinquency threshold ---

def test_foreclosure_below_threshold_rejected(api):
    """PRD §3.8: "it requires the count of DELINQUENT installments on the parcel to be at
    least 3; a parcel with fewer than three delinquent installments cannot be foreclosed and
    yields ERR_FORECLOSURE_THRESHOLD_NOT_MET (HTTP 409)."

    Design: Corner/errors/foreclosure_initiate_below_threshold_rejected
    """
    parcel, _, inst = _setup_single_due_term1(api, cost=1_000_000, clock="2027-08-01T00:00:00Z")
    get_success_data(api.mark_delinquent(inst["id"], TREAS))
    validate_error(api.create_foreclosure(parcel["id"], ADMIN),
                   ApiErrorId.ERR_FORECLOSURE_THRESHOLD_NOT_MET.value)
    assert refresh_parcel(api, parcel["id"])["status"] == "ACTIVE"


# --- corner: payment amount mismatch on a DUE installment ---

def test_payment_amount_mismatch_rejected(api):
    """PRD §3.5: "The amount_cents must equal the installment's current amount_due_cents
    exactly — no partial or overpayment — or the request is rejected with
    ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

    Design: Corner/errors/payment_amount_mismatch_on_due_installment
    """
    parcel, _, inst = _setup_single_due_term1(api, cost=500_000, clock="2027-07-01T00:00:00Z")
    payload = {"amount_cents": 500000, "payment_date": "2027-07-01T00:00:00Z", "paid_by": "O"}
    validate_error(api.create_payment(inst["id"], payload, TREAS),
                   ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    assert refresh_installment(api, inst["id"])["status"] == "DUE"


# --- corner: paying a SCHEDULED installment ---

def test_pay_scheduled_installment_not_yet_payable(api):
    """PRD §3.5: "Payment is accepted only when the installment is currently DUE or
    DELINQUENT; a SCHEDULED installment is not yet payable ... so any of these yields
    ERR_INSTALLMENT_NOT_PAYABLE (HTTP 409)."

    Design: Corner/state_machines/pay_scheduled_installment_not_yet_payable
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[{"apn": "S4-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS", bond={"term_years": 1},
    )
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    assert inst["status"] == "SCHEDULED"
    payload = {"amount_cents": 525000, "payment_date": "2026-03-01T00:00:00Z", "paid_by": "O"}
    validate_error(api.create_payment(inst["id"], payload, TREAS),
                   ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value)
