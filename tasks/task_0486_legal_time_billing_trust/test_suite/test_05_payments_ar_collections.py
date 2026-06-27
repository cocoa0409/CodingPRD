"""Operating payments, trust sweeps, A/R realization, write-off, collections,
the OCC stale-version guard, and the validation-priority conflicts on the sweep.

Queue A: dual_variant_calc (client A/R realization), transitive_cascade
(trust-sweep depth-3), priority_pair_validation_conflict, compensating_invariant
(payment reverse). Queue B: validations (overpayment, partial writeoff,
collections, ledger mismatch), errors (OCC stale).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    make_attorney_headers,
    validate_success, validate_error,
    ApiErrorId,
    create_payment_payload, write_off_payload, trust_sweep_payload, create_invoice_payload,
    create_open_matter, ensure_billing_codes, capture_time_entry,
    setup_issued_invoice, setup_issued_invoice_with_funded_trust, setup_funded_ledger,
    create_client, create_timekeeper, set_clock,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]
ATT9 = make_attorney_headers("att-9")


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / client_ar_provisional_vs_realization_final
# ---------------------------------------------------------------------------
def test_provisional_ar_counts_issued_invoice(api):
    """PRD §3.6: "The provisional `ar_balance_cents` is the sum, over the client's
    invoices whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`, of
    `total_cents` minus `amount_paid_cents` minus `written_off_cents`".

    Design: Difficulty/dual_variant_calc/client_ar_provisional_vs_realization_final
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    ar = validate_success(api.get_client_ar_summary(base["client_id"], CLERK))
    assert ar["ar_balance_cents"] == 50000


def test_write_off_drops_ar_and_zero_realization(api):
    """PRD §3.7: "A valid write-off adds the remaining balance into
    `written_off_cents`, moves `billing_status` to `WRITTEN_OFF`, cross-sets
    `collection_status` to `SETTLED`, drops the invoice out of A/R by recomputing
    the client's `ar_balance_cents`".
    PRD §3.6: "the `realization_pct` is the collected-final figure multiplied by
    ten thousand, divided by the billed-final figure, rounded half up, then
    divided by one hundred to yield a percentage carried to two decimal places —
    and it is reported as 0 when the billed-final figure is zero."

    Design: Difficulty/dual_variant_calc/client_ar_provisional_vs_realization_final
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    client_id = base["client_id"]
    validate_success(api.write_off_invoice(inv_id, write_off_payload(50000), ATT))
    ar = validate_success(api.get_client_ar_summary(client_id, CLERK))
    assert ar["ar_balance_cents"] == 0
    # billed_final 50000 (total) + 0; collected_final 0 -> realization 0.0.
    assert ar["realization_pct"] == 0.0


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / trust_sweep_depth3_paid_settled_chain
# ---------------------------------------------------------------------------
def test_trust_sweep_full_pays_invoice(api):
    """PRD §3.6: "adds the amount to the invoice's `amount_paid_cents`, advances
    the billing dimension exactly as a payment would (including the cross-set to
    `SETTLED` on reaching `PAID`)". PRD §3.6: "when the cumulative paid exactly
    equals the owed amount, the invoice becomes `PAID` (whether it was `ISSUED` or
    `PARTIALLY_PAID`), and reaching `PAID` also cross-sets the `collection_status`
    to `SETTLED`."

    Design: Difficulty/transitive_cascade/trust_sweep_depth3_paid_settled_chain
    """
    base = setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                                  deposit_cents=100000)
    inv = base["invoice"]
    payload = trust_sweep_payload(50000, base["ledger"]["id"], "clerk-1", inv["version"])
    validate_success(api.trust_sweep(inv["id"], payload, ATT9), expected_status=201)
    got = validate_success(api.get_invoice(inv["id"], CLERK))
    assert got["amount_paid_cents"] == 50000
    assert got["billing_status"] == "PAID"
    assert got["collection_status"] == "SETTLED"


def test_trust_sweep_paid_drops_client_ar_to_zero(api):
    """PRD §3.6: "recomputes the client's `ar_balance_cents`". PRD §3.6: "The
    provisional `ar_balance_cents` is the sum, over the client's invoices whose
    `billing_status` is `ISSUED` or `PARTIALLY_PAID`, of `total_cents` minus
    `amount_paid_cents` minus `written_off_cents`".

    Design: Difficulty/transitive_cascade/trust_sweep_depth3_paid_settled_chain
    """
    base = setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                                  deposit_cents=100000)
    inv = base["invoice"]
    payload = trust_sweep_payload(50000, base["ledger"]["id"], "clerk-1", inv["version"])
    validate_success(api.trust_sweep(inv["id"], payload, ATT9), expected_status=201)
    ar = validate_success(api.get_client_ar_summary(base["client_id"], CLERK))
    # PAID invoice drops out of the {ISSUED, PARTIALLY_PAID} A/R set.
    assert ar["ar_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / state_beats_overpayment_on_trust_sweep
# ---------------------------------------------------------------------------
def test_state_beats_overpayment_on_draft_sweep(api):
    """PRD §2.10: "Only after those gates does the system evaluate whether the
    target resource is in a legal state for the requested transition
    (`ERR_INVALID_STATE`) ... The remaining business constraints — invoice
    over-payment (`ERR_OVERPAYMENT`) ... are evaluated after the safety rules."
    PRD §3.6: "An `Attorney` sweeps an `ISSUED` or `PARTIALLY_PAID` invoice".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_overpayment_on_trust_sweep
    """
    # DRAFT invoice (not finalized) + funded ledger for the same client.
    ensure_billing_codes()
    client_id = create_client()["id"]
    tk_id = create_timekeeper()["id"]
    trust = setup_funded_ledger(client_id=client_id, deposit_cents=100000, confirm=False)
    matter, _, _ = create_open_matter(client_id=client_id, timekeeper_id=tk_id,
                                      matter_rate_cents=50000)
    capture_time_entry(matter["id"], tk_id, minutes=60)
    draft = validate_success(api.create_invoice(create_invoice_payload(matter["id"]), CLERK),
                             expected_status=201)
    payload = trust_sweep_payload(999999, trust["ledger"]["id"], "clerk-1", draft["version"])
    # Both state (DRAFT, not ISSUED) and overpayment are violated; state wins.
    validate_error(api.trust_sweep(draft["id"], payload, ATT9), ApiErrorId.ERR_INVALID_STATE)


def test_draft_sweep_leaves_invoice_in_draft(api):
    """PRD §2.10: "Only after those gates does the system evaluate whether the
    target resource is in a legal state for the requested transition
    (`ERR_INVALID_STATE`) ... The remaining business constraints — invoice
    over-payment (`ERR_OVERPAYMENT`) ... are evaluated after the safety rules."
    PRD §3.5: "First a `BillingClerk` creates a `DRAFT` `Invoice` for a matter".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_overpayment_on_trust_sweep
    """
    ensure_billing_codes()
    client_id = create_client()["id"]
    tk_id = create_timekeeper()["id"]
    trust = setup_funded_ledger(client_id=client_id, deposit_cents=100000, confirm=False)
    matter, _, _ = create_open_matter(client_id=client_id, timekeeper_id=tk_id,
                                      matter_rate_cents=50000)
    capture_time_entry(matter["id"], tk_id, minutes=60)
    draft = validate_success(api.create_invoice(create_invoice_payload(matter["id"]), CLERK),
                             expected_status=201)
    payload = trust_sweep_payload(999999, trust["ledger"]["id"], "clerk-1", draft["version"])
    validate_error(api.trust_sweep(draft["id"], payload, ATT9), ApiErrorId.ERR_INVALID_STATE)
    # The state check fires before overpayment; the DRAFT invoice is unchanged.
    inv = validate_success(api.get_invoice(draft["id"], CLERK))
    assert inv["billing_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / sod_beats_overpayment_on_trust_sweep
# ---------------------------------------------------------------------------
def test_sod_beats_overpayment_on_issued_sweep(api):
    """PRD §2.10: "Business-safety rules are evaluated next, in this order:
    segregation of duties (`ERR_SOD_SAME_ACTOR`) ... The remaining business
    constraints — invoice over-payment (`ERR_OVERPAYMENT`) ... are evaluated after
    the safety rules."
    PRD §3.6: "The approving attorney's own `X-User-ID` must differ from the
    supplied `initiated_by_user_id`; if they are the same actor, the sweep is
    rejected with `ERR_SOD_SAME_ACTOR` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_overpayment_on_trust_sweep
    """
    base = setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                                  deposit_cents=100000)
    inv = base["invoice"]
    # initiated_by == approver (att-9) -> SoD; amount 999999 -> overpayment. SoD wins.
    payload = trust_sweep_payload(999999, base["ledger"]["id"], "att-9", inv["version"])
    validate_error(api.trust_sweep(inv["id"], payload, ATT9), ApiErrorId.ERR_SOD_SAME_ACTOR)


def test_sod_same_actor_sweep_leaves_invoice_unpaid(api):
    """PRD §3.6: "The approving attorney's own `X-User-ID` must differ from the
    supplied `initiated_by_user_id`; if they are the same actor, the sweep is
    rejected with `ERR_SOD_SAME_ACTOR` (HTTP 403)." PRD §2.10: "Business-safety
    rules are evaluated next, in this order: segregation of duties
    (`ERR_SOD_SAME_ACTOR`) ... The remaining business constraints — invoice
    over-payment (`ERR_OVERPAYMENT`) ... are evaluated after the safety rules."

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_overpayment_on_trust_sweep
    """
    base = setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                                  deposit_cents=100000)
    inv = base["invoice"]
    payload = trust_sweep_payload(999999, base["ledger"]["id"], "att-9", inv["version"])
    validate_error(api.trust_sweep(inv["id"], payload, ATT9), ApiErrorId.ERR_SOD_SAME_ACTOR)
    # The SoD check fires before overpayment; the ISSUED invoice took no payment.
    got = validate_success(api.get_invoice(inv["id"], CLERK))
    assert got["amount_paid_cents"] == 0
    assert got["billing_status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / payment_reverse_preserves_ar_identity
# ---------------------------------------------------------------------------
def test_payment_reverse_restores_invoice_issued(api):
    """PRD §3.6: "reversal sets the payment's `status` to `REVERSED`, subtracts
    its `amount_cents` from the invoice's `amount_paid_cents`, recomputes the
    billing dimension (a previously `PAID` invoice falls back to `PARTIALLY_PAID`
    or `ISSUED`)".

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_ar_identity
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    pay = validate_success(
        api.create_payment(inv_id, create_payment_payload(50000, "CHECK"), CLERK),
        expected_status=201)
    validate_success(api.reverse_payment(pay["id"], CLERK))
    inv = validate_success(api.get_invoice(inv_id, CLERK))
    assert inv["amount_paid_cents"] == 0
    assert inv["billing_status"] == "ISSUED"


def test_payment_reverse_restores_ar_balance(api):
    """PRD §3.6: "recomputes the client's `ar_balance_cents`". PRD §3.6: "The
    provisional `ar_balance_cents` is the sum, over the client's invoices whose
    `billing_status` is `ISSUED` or `PARTIALLY_PAID`, of `total_cents` minus
    `amount_paid_cents` minus `written_off_cents`".

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_ar_identity
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    client_id = base["client_id"]
    pay = validate_success(
        api.create_payment(inv_id, create_payment_payload(50000, "CHECK"), CLERK),
        expected_status=201)
    validate_success(api.reverse_payment(pay["id"], CLERK))
    ar = validate_success(api.get_client_ar_summary(client_id, CLERK))
    assert ar["ar_balance_cents"] == 50000


# ---------------------------------------------------------------------------
# Section 4 — Validations (queue B)
# ---------------------------------------------------------------------------
def test_partial_writeoff_rejected(api):
    """PRD §3.7: "The supplied `amount_cents` must equal the full remaining
    balance — `total_cents` minus `amount_paid_cents` — because partial write-offs
    are not supported; a write-off amount that does not equal the full remaining
    balance is rejected with `ERR_PARTIAL_WRITEOFF` (HTTP 422)."

    Design: Corner/validations/partial_writeoff_rejected
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    validate_error(api.write_off_invoice(base["invoice"]["id"], write_off_payload(10000), ATT),
                   ApiErrorId.ERR_PARTIAL_WRITEOFF)


def test_overpayment_on_operating_payment_rejected(api):
    """PRD §3.6: "A payment or sweep whose amount would carry the invoice past its
    remaining balance — the remaining balance being `total_cents` minus
    `amount_paid_cents` minus `written_off_cents` — is rejected as an over-payment
    with `ERR_OVERPAYMENT` (HTTP 422)."

    Design: Corner/validations/overpayment_on_operating_payment_rejected
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    validate_error(
        api.create_payment(base["invoice"]["id"], create_payment_payload(60000, "CHECK"), CLERK),
        ApiErrorId.ERR_OVERPAYMENT)


def test_collections_too_early_rejected(api):
    """PRD §3.7: "Attempting to send to collections before the grace period has
    fully elapsed is rejected with `ERR_COLLECTIONS_TOO_EARLY` (HTTP 409)."

    Design: Corner/validations/collections_too_early_rejected
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    # due 2026-07-01; clock 2026-07-10 -> OVERDUE but within 15-day grace.
    set_clock("2026-07-10T00:00:00Z")
    validate_error(api.send_to_collections(inv_id, CLERK), ApiErrorId.ERR_COLLECTIONS_TOO_EARLY)


def test_send_to_collections_succeeds_past_grace(api):
    """PRD §3.7: "a `BillingClerk` sends an `OVERDUE` invoice to collections,
    permitted only once the clock is past the due date plus the fifteen-day grace
    and while the invoice's `billing_status` is still `ISSUED` or
    `PARTIALLY_PAID`; doing so sets `collection_status` to `IN_COLLECTIONS` and
    increments the invoice's `version`."

    Design: Corner/validations/send_to_collections_succeeds_past_grace
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    # due 2026-07-01 + 15-day grace = 2026-07-16; clock 2026-07-17 is past grace.
    set_clock("2026-07-17T00:00:00Z")
    inv = validate_success(api.send_to_collections(inv_id, CLERK))
    assert inv["collection_status"] == "IN_COLLECTIONS"


def test_ledger_account_mismatch_on_sweep(api):
    """PRD §3.6: "The chosen sub-ledger must belong to the same client as the
    invoice's `client_id` — a client's trust may only pay that client's invoices —
    and a mismatch is rejected with `ERR_LEDGER_ACCOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/ledger_account_mismatch_on_sweep
    """
    from test_helpers import setup_trust_account_and_ledger, post_deposit
    ensure_billing_codes()
    # Client A: ISSUED invoice. Client B: separate funded ledger.
    client_a = create_client(display_name="Acme Corp")["id"]
    client_b = create_client(display_name="Beta LLC")["id"]
    tk_id = create_timekeeper()["id"]
    base_b = setup_trust_account_and_ledger(client_id=client_b)
    post_deposit(base_b["ledger"]["id"], 100000)
    matter_a, _, _ = create_open_matter(client_id=client_a, timekeeper_id=tk_id,
                                        matter_rate_cents=50000)
    capture_time_entry(matter_a["id"], tk_id, minutes=60)
    draft = validate_success(api.create_invoice(create_invoice_payload(matter_a["id"]), CLERK),
                             expected_status=201)
    inv = validate_success(api.finalize_invoice(draft["id"], {}, CLERK))
    payload = trust_sweep_payload(50000, base_b["ledger"]["id"], "clerk-1", inv["version"])
    validate_error(api.trust_sweep(inv["id"], payload, ATT9),
                   ApiErrorId.ERR_LEDGER_ACCOUNT_MISMATCH)


# ---------------------------------------------------------------------------
# Section 6 — Errors (OCC stale) (queue B)
# ---------------------------------------------------------------------------
def test_occ_stale_invoice_version_on_sweep(api):
    """PRD §2.9: "When `expected_invoice_version` does not equal the invoice's
    current `version`, the sweep is rejected with `ERR_STALE_INVOICE_VERSION`
    (HTTP 412) and no ledger is touched."

    Design: Corner/errors/occ_stale_invoice_version_on_sweep
    """
    base = setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                                  deposit_cents=100000)
    inv = base["invoice"]
    stale_version = inv["version"]
    # An intervening operating payment advances the invoice version.
    validate_success(
        api.create_payment(inv["id"], create_payment_payload(10000, "ACH"), CLERK),
        expected_status=201)
    payload = trust_sweep_payload(20000, base["ledger"]["id"], "clerk-1", stale_version)
    validate_error(api.trust_sweep(inv["id"], payload, ATT9),
                   ApiErrorId.ERR_STALE_INVOICE_VERSION)
