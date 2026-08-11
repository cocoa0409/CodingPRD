"""Disputes: the filing window, the provisional-credit cap, and the exact
round trip a denial performs on the cleared balance."""

from test_helpers import (
    ApiErrorId,
    api_client,
    apply_provisional_credit,
    approve_payment,
    assert_dispute,
    assert_ledger_identity,
    create_dispute_payload,
    file_dispute,
    list_ledger_entries,
    read_account,
    read_dispute,
    read_payment,
    release_payment,
    resolve_dispute,
    schedule_payment,
    set_clock,
    settle_payment,
    setup_billpay_world,
    TEST_USERS,
    validate_error,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _settled_payment_world(amount_cents=80000, settle_on="2026-06-01T09:00:00Z", **kwargs):
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", **kwargs)
    payment = schedule_payment(world, amount_cents=amount_cents, channel="ACH")
    if payment["approval_status"] == "PENDING_SECOND_APPROVAL":
        approve_payment(payment["id"], note="Invoice verified against the care plan.")
    release_payment(payment["id"])
    if settle_on != "2026-06-01T09:00:00Z":
        set_clock(settle_on)
    settled = settle_payment(payment["id"])
    world["payment"] = settled
    return world


def test_a_dispute_filed_on_the_sixtieth_day_still_goes_through():
    """PRD §3.6: "The filing window is 60 days from settlement, inclusive: a
    dispute filed on exactly the sixtieth day still goes through, and one filed
    on the sixty-first is refused with `ERR_DISPUTE_WINDOW_EXPIRED` at rung 22."
    PRD §3.6: "Filing writes the current logical date to `filed_on` and records
    `days_since_settlement` as the whole number of days from the payment's
    `settled_on` to `filed_on`."

    Design: Difficulty/boundary_precision_check/dispute_filing_window_is_inclusive_on_day_sixty
    """
    world = _settled_payment_world(settle_on="2026-06-10T09:00:00Z")

    set_clock("2026-08-09T09:00:00Z")
    response = api_client.create_dispute(
        create_dispute_payload(world["payment"]["id"], 50000, reason_code="SCAM_INDUCED"),
        COMPLIANCE,
    )

    dispute = validate_success(response, 201)
    assert_dispute(dispute)
    assert dispute["status"] == "FILED"
    assert dispute["days_since_settlement"] == 60
    assert dispute["filed_on"] == "2026-08-09"
    assert dispute["provisional_credit_cents"] == 0
    assert read_payment(world["payment"]["id"])["settled_on"] == "2026-06-10"


def test_a_dispute_filed_on_the_sixty_first_day_is_refused():
    """PRD §2.9 rung 22: "**Dispute filing window.** The current logical date
    is at most 60 days after the payment's `settled_on`; exactly 60 days later
    still files. Otherwise `ERR_DISPUTE_WINDOW_EXPIRED` (409). Applies to
    filing a dispute."

    Design: Difficulty/boundary_precision_check/dispute_filing_window_is_inclusive_on_day_sixty
    """
    world = _settled_payment_world(settle_on="2026-06-10T09:00:00Z")

    set_clock("2026-08-10T09:00:00Z")
    response = api_client.create_dispute(
        create_dispute_payload(world["payment"]["id"], 50000, reason_code="SCAM_INDUCED"),
        COMPLIANCE,
    )

    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value, 409)


def test_a_provisional_credit_above_the_cap_is_refused():
    """PRD §3.6: "The credit is capped: `disputed_amount_cents` must be at or
    below 500000 cents, with exactly 500000 still crediting and anything above
    refused with `ERR_CREDIT_CAP_EXCEEDED` at rung 39."

    Design: Corner/validations/corner_provisional_credit_above_the_cap_is_rejected
    """
    world = _settled_payment_world(
        amount_cents=600000,
        allocation_cents=700000,
        budget_overrides={"category_name": "CARE"},
        payee_type="ESSENTIAL",
        payee_overrides={
            "payee_name": "Meadow Rehab Center",
            "remittance_reference": "MRC-2",
        },
    )
    filing = api_client.create_dispute(
        create_dispute_payload(world["payment"]["id"], 500001, reason_code="WRONG_AMOUNT"),
        COMPLIANCE,
    )
    dispute = validate_success(filing, 201)

    response = api_client.apply_provisional_credit(dispute["id"], COMPLIANCE)

    validate_error(response, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED.value, 409)
    after = read_dispute(dispute["id"])
    assert after["status"] == "FILED"
    assert after["provisional_credit_cents"] == 0
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 4399100


def test_the_provisional_credit_raises_the_cleared_balance():
    """PRD §3.6: "On success `provisional_credit_cents` is set to
    `disputed_amount_cents`, a `DISPUTE_PROVISIONAL_CREDIT` ledger entry of
    positive `provisional_credit_cents` dated the current logical date is
    appended, the account's `cleared_balance_cents` and
    `available_balance_cents` both rise by that amount, and the receiving
    period's `unreconciled_entry_count` rises by one."

    Design: Difficulty/compensating_invariant/dispute_credit_then_denial_conserves_cleared_balance_and_ledger_identity
    """
    world = _settled_payment_world()
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 4919500
    dispute = file_dispute(world["payment"]["id"], 50000, reason_code="UNAUTHORIZED")

    credited = apply_provisional_credit(dispute["id"])

    assert credited["status"] == "PROVISIONAL_CREDITED"
    assert credited["provisional_credit_cents"] == 50000
    account = read_account(world["account"]["id"])
    assert account["cleared_balance_cents"] == 4969500
    assert account["available_balance_cents"] == 4969500


def test_denying_a_credited_dispute_restores_the_cleared_balance_exactly():
    """PRD §3.6: "**Credited and denied** (`PROVISIONAL_CREDITED` → `DENIED`):
    a `DISPUTE_CREDIT_REVERSAL` ledger entry of negative
    `provisional_credit_cents` dated the current logical date is appended, and
    the account's `cleared_balance_cents` and `available_balance_cents` fall
    back to exactly their pre-credit values."
    PRD §2.12: "**The ledger identity.** An account's `cleared_balance_cents`
    minus its `opening_balance_cents` equals the signed sum of `amount_cents`
    over every `LedgerEntry` belonging to that account, frozen entries
    included."

    Design: Difficulty/compensating_invariant/dispute_credit_then_denial_conserves_cleared_balance_and_ledger_identity
    """
    world = _settled_payment_world()
    dispute = file_dispute(world["payment"]["id"], 50000, reason_code="UNAUTHORIZED")
    apply_provisional_credit(dispute["id"])

    denied = resolve_dispute(
        dispute["id"],
        "DENIED",
        resolution_note="Carrier evidence shows the client authorised the debit.",
    )

    assert denied["status"] == "DENIED"
    assert denied["provisional_credit_cents"] == 50000
    account = read_account(world["account"]["id"])
    assert account["cleared_balance_cents"] == 4919500
    assert account["available_balance_cents"] == 4919500

    entries = list_ledger_entries(world["account"]["id"])
    assert len(entries) == 4, f"Expected four ledger entries, got {entries}"
    assert sorted(entry["entry_type"] for entry in entries) == [
        "DISBURSEMENT",
        "DISPUTE_CREDIT_REVERSAL",
        "DISPUTE_PROVISIONAL_CREDIT",
        "SERVICE_FEE",
    ]
    assert sum(entry["amount_cents"] for entry in entries) == -80500
    assert_ledger_identity(account, entries)
