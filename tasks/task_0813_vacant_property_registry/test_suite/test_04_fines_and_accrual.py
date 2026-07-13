"""Fine assessment, accrual, dispute/settlement, and the assess->suspend cascade.

Covers difficulty instances 1a (provisional vs finalized), 6a (day-30/31
boundary), 9a (ledger net-zero), 5a (state beats fiscal on record-lien), 4a
(assess -> ledger -> suspend cascade) plus corner record-lien-below-min.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_registrant, create_property, create_standard, create_inspection,
    complete_inspection, violations_for_inspection, transition_violation,
    assess_fine, set_clock, dispute_fine, pay_fine, get_property,
    setup_assessed_fine, setup_escalated_violation,
)

OFFICER = TEST_USERS["code_officer_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


def _two_assessed_fines(api):
    """Two ASSESSED fines (base 20000 each, cure 10) on one property, assessed at
    2026-03-11. Returns (registrant, property, fine_a, fine_b)."""
    s1 = create_standard(api, category="SECURING", severity_weight=8,
                         cure_period_days=10, base_fine_cents=20000)
    s2 = create_standard(api, category="SECURING", severity_weight=8,
                         cure_period_days=10, base_fine_cents=20000)
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    insp = create_inspection(api, prop["id"])
    complete_inspection(api, insp["id"], "FAIL", [s1["code"], s2["code"]])
    viols = violations_for_inspection(api, insp["id"])
    set_clock(api, "2026-03-11T00:00:00Z")
    transition_violation(api, viols[0]["id"], "ESCALATE")
    transition_violation(api, viols[1]["id"], "ESCALATE")
    fine_a = assess_fine(api, viols[0]["id"])
    fine_b = assess_fine(api, viols[1]["id"])
    return registrant, prop, fine_a, fine_b


# --- Difficulty 1a: provisional vs finalized accrual -----------------------
def test_finalized_accrual_frozen_at_payment_instant(api):
    """PRD §3.5: "the raw amount is `base_amount_cents`, plus 500 cents for each of
    the first up-to-30 overdue days, plus 1000 cents for each overdue day beyond
    the 30th."
    PRD §3.5: "The **finalized** form evaluates at the settlement instant, is
    frozen into `finalized_amount_cents` (which is null until the fine settles),
    and is reconciled into the ledger."

    Design: Difficulty/dual_variant_calc/fine_provisional_vs_finalized_accrual
    """
    registrant, prop, fine_a, _ = _two_assessed_fines(api)
    set_clock(api, "2026-04-20T00:00:00Z")  # 40 days after 2026-03-11
    pay_fine(api, fine_a["id"], registrant["id"])
    settled = validate_success(api.get_fine(fine_a["id"], ADMIN))
    assert settled["status"] == "PAID"
    assert settled["finalized_amount_cents"] == 45000


def test_provisional_accrual_tracks_clock_and_caps_at_triple(api):
    """PRD §3.5: "The accrued figure is this raw amount capped so that it never
    exceeds three times `base_amount_cents`".
    PRD §3.5: "The **provisional** form evaluates at the current clock, so the
    value grows as the clock advances; it is exposed as `accrued_amount_cents`".

    Design: Difficulty/dual_variant_calc/fine_provisional_vs_finalized_accrual
    """
    _, _, _, fine_b = _two_assessed_fines(api)
    set_clock(api, "2026-05-10T00:00:00Z")  # 60 days after 2026-03-11 -> raw 65000, capped 60000
    read = validate_success(api.get_fine(fine_b["id"], ADMIN))
    assert read["status"] == "ASSESSED"
    assert read["accrued_amount_cents"] == 60000


# --- Difficulty 6a: day-30 vs day-31 boundary ------------------------------
def test_fine_accrual_at_day_30_is_base_rate(api):
    """PRD §3.5: "The first 30 of those overdue days each add one
    `daily_penalty_cents` (500 cents) to the base; every overdue day on or after
    the 30th day adds twice `daily_penalty_cents` (1000 cents) per day."

    Design: Difficulty/boundary_precision_check/fine_accrual_day30_vs_day31
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-11T00:00:00Z",
                              base_fine_cents=20000, cure_period_days=5,
                              category="SECURING")
    set_clock(api, "2026-04-10T00:00:00Z")  # exactly 30 days overdue
    read = validate_success(api.get_fine(ctx["fine"]["id"], ADMIN))
    assert read["accrued_amount_cents"] == 35000


def test_fine_accrual_at_day_31_charges_doubled_tier(api):
    """PRD §3.5: "every overdue day on or after the 30th day adds twice
    `daily_penalty_cents` (1000 cents) per day."

    Design: Difficulty/boundary_precision_check/fine_accrual_day30_vs_day31
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-11T00:00:00Z",
                              base_fine_cents=20000, cure_period_days=5,
                              category="SECURING")
    set_clock(api, "2026-04-11T00:00:00Z")  # 31 days overdue
    read = validate_success(api.get_fine(ctx["fine"]["id"], ADMIN))
    assert read["accrued_amount_cents"] == 36000


# --- Difficulty 9a: fine ledger net-zero conservation ----------------------
def test_paid_fine_freezes_finalized_amount(api):
    """PRD §3.5: "Paying settles the fine: the system freezes
    `finalized_amount_cents` to the finalized accrual at the current clock".

    Design: Difficulty/compensating_invariant/fine_ledger_net_zero
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-11T00:00:00Z",
                              base_fine_cents=20000, cure_period_days=5,
                              category="SECURING")
    set_clock(api, "2026-04-20T00:00:00Z")  # 40 days overdue -> finalized 45000
    pay_fine(api, ctx["fine"]["id"], ctx["registrant"]["id"])
    settled = validate_success(api.get_fine(ctx["fine"]["id"], ADMIN))
    assert settled["status"] == "PAID"
    assert settled["finalized_amount_cents"] == 45000


def test_paid_fine_returns_balance_to_registration_fee(api):
    """PRD §2.6: "a fine's full life contributes a net of zero to the outstanding
    balance once it settles by payment: the `FINE_ASSESSED` credit plus the
    `FINE_ACCRUAL` credit is exactly offset by the `FINE_PAYMENT` debit."

    Design: Difficulty/compensating_invariant/fine_ledger_net_zero
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-11T00:00:00Z",
                              base_fine_cents=20000, cure_period_days=5,
                              category="SECURING")
    set_clock(api, "2026-04-20T00:00:00Z")
    pay_fine(api, ctx["fine"]["id"], ctx["registrant"]["id"])
    prop = get_property(api, ctx["property"]["id"])
    assert prop["outstanding_balance_cents"] == 10000


# --- Difficulty 4a: assess -> ledger -> auto-suspend cascade ---------------
def test_assessing_fine_pushes_balance_over_suspend_threshold(api):
    """PRD §3.5: "The system posts a `FINE_ASSESSED` `LedgerEntry` whose
    `amount_cents` is the positive `base_amount_cents` and recomputes the
    property's `outstanding_balance_cents`."

    Design: Difficulty/transitive_cascade/assess_fine_ledger_balance_suspends_registration
    """
    ctx = setup_escalated_violation(api, escalate_clock="2026-03-06T00:00:00Z",
                                    base_fine_cents=95000, cure_period_days=5,
                                    category="SANITATION", severity_weight=6)
    fine = assess_fine(api, ctx["violation"]["id"])
    prop = get_property(api, ctx["property"]["id"])
    assert prop["outstanding_balance_cents"] == 105000
    assert fine["status"] == "ASSESSED"


def test_balance_at_threshold_auto_suspends_registration(api):
    """PRD §3.1: "Whenever a ledger insert leaves the recomputed
    `outstanding_balance_cents` at or above 100000 cents, an `ACTIVE` property is
    transitioned to `SUSPENDED` (the boundary is inclusive — a balance of exactly
    100000 cents suspends)."

    Design: Difficulty/transitive_cascade/assess_fine_ledger_balance_suspends_registration
    """
    ctx = setup_escalated_violation(api, escalate_clock="2026-03-06T00:00:00Z",
                                    base_fine_cents=95000, cure_period_days=5,
                                    category="SANITATION", severity_weight=6)
    assess_fine(api, ctx["violation"]["id"])
    prop = get_property(api, ctx["property"]["id"])
    assert prop["registration_status"] == "SUSPENDED"


# --- Difficulty 5a: state check beats fiscal check on record-lien ----------
def test_record_lien_on_disputed_low_fine_reports_invalid_state(api):
    """PRD §3.5: "Conversion requires the fine to be `ASSESSED`; an attempt against
    any other state is rejected with `ERR_INVALID_STATE`. It further requires that
    the fine's finalized accrual to the current clock be worth at least 25000 cents
    ... and this fiscal-floor check is evaluated only after the state check passes."

    Design: Difficulty/priority_pair_validation_conflict/record_lien_state_beats_fiscal
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=10000, cure_period_days=5,
                              category="SECURING")
    dispute_fine(api, ctx["fine"]["id"], ctx["registrant"]["id"], "not my property")
    resp = api.record_lien(ctx["fine"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_record_lien_on_disputed_sufficient_fine_still_invalid_state(api):
    """PRD §3.5: "Conversion requires the fine to be `ASSESSED`; an attempt against
    any other state is rejected with `ERR_INVALID_STATE` ... this fiscal-floor
    check is evaluated only after the state check passes." A DISPUTED fine whose
    accrual clears the 25000 floor still fails on the state check first.

    Design: Difficulty/priority_pair_validation_conflict/record_lien_state_beats_fiscal
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=30000, cure_period_days=5,
                              category="STRUCTURAL")
    dispute_fine(api, ctx["fine"]["id"], ctx["registrant"]["id"], "disputed")
    resp = api.record_lien(ctx["fine"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: record-lien below the minimum amount --------------------------
def test_record_lien_below_min_amount_returns_error(api):
    """PRD §3.5: "It further requires that the fine's finalized accrual to the
    current clock be worth at least 25000 cents — a fine whose finalized accrual
    falls below this floor is rejected with `ERR_LIEN_AMOUNT_TOO_LOW`".

    Design: Corner/validations/record_lien_below_min_amount_returns_error
    """
    ctx = setup_assessed_fine(api, escalate_clock="2026-03-06T00:00:00Z",
                              base_fine_cents=10000, cure_period_days=5,
                              category="STRUCTURAL")
    # Fine is ASSESSED, 0 days overdue -> finalized would be 10000 (< 25000).
    resp = api.record_lien(ctx["fine"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_LIEN_AMOUNT_TOO_LOW.value)
