"""Credit ledger entries: append-only read model (PRD 2.4, 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_credit_ledger_entry_immutability(api):
    """PRD 2.4: "The single exception is the credit ledger: a `CreditLedgerEntry` is an append-only record that carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries; they are never modified after insertion."
    PRD 3.8: "a polymorphic `reference_id` pointing at the Referral, SatisfactionClaim, or Invoice that motivated the entry, null for `ADJUSTMENT` entries which instead carry an optional operator `note`."

    Design: Corner/entities/credit_ledger_entry_immutability
    """
    customer = th.register_customer(email="c4@x.com", full_name="C Four")
    entry = th.add_credit(customer["id"], 250, note="promo")

    fetched = th.validate_success(api.get_ledger_entry(entry["id"], ADMIN))
    th.assert_ledger_entry(fetched)
    assert fetched["entry_type"] == "ADJUSTMENT"
    assert fetched["amount_cents"] == 250
    assert fetched["reference_id"] is None
    assert fetched["customer_id"] == customer["id"]
