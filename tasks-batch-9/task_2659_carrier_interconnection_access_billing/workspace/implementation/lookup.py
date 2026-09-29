"""Existence resolution: path parameters (PRD 2.7 step 3, left to right) and
body references (step 5, in payload field order)."""
from errors import ApiError
from store import db

_RESOLVERS = (
    ("carrier", "carriers", "ERR_CARRIER_NOT_FOUND"),
    ("agreement", "agreements", "ERR_AGREEMENT_NOT_FOUND"),
    ("offer", "offers", "ERR_OFFER_NOT_FOUND"),
    ("trunk_group", "trunk_groups", "ERR_TRUNK_GROUP_NOT_FOUND"),
    ("measurement", "measurements", "ERR_MEASUREMENT_NOT_FOUND"),
    ("cdr", "cdrs", "ERR_CDR_NOT_FOUND"),
    ("augment_order", "augment_orders", "ERR_AUGMENT_ORDER_NOT_FOUND"),
    ("tariff_filing", "tariff_filings", "ERR_TARIFF_FILING_NOT_FOUND"),
    ("factor_filing", "factor_filings", "ERR_FACTOR_FILING_NOT_FOUND"),
    ("usage_batch", "usage_batches", "ERR_USAGE_BATCH_NOT_FOUND"),
    ("invoice", "invoices", "ERR_INVOICE_NOT_FOUND"),
    ("dispute", "disputes", "ERR_DISPUTE_NOT_FOUND"),
    ("recon_case", "recon_cases", "ERR_RECONCILIATION_CASE_NOT_FOUND"),
    ("ledger_entry", "ledger_entries", "ERR_INVALID_REQUEST"),
)


def _make(name, collection, error_id):
    def resolver(identifier):
        if not isinstance(identifier, str) or identifier == "":
            raise ApiError(error_id, "%s not found" % name)
        row = getattr(db, collection).get(identifier)
        if row is None:
            raise ApiError(error_id, "%s not found" % name)
        return row
    return resolver


get_carrier = _make(*_RESOLVERS[0])
get_agreement = _make(*_RESOLVERS[1])
get_offer = _make(*_RESOLVERS[2])
get_trunk_group = _make(*_RESOLVERS[3])
get_measurement = _make(*_RESOLVERS[4])
get_cdr = _make(*_RESOLVERS[5])
get_augment_order = _make(*_RESOLVERS[6])
get_tariff_filing = _make(*_RESOLVERS[7])
get_factor_filing = _make(*_RESOLVERS[8])
get_usage_batch = _make(*_RESOLVERS[9])
get_invoice = _make(*_RESOLVERS[10])
get_dispute = _make(*_RESOLVERS[11])
get_recon_case = _make(*_RESOLVERS[12])


def get_ledger_entry(identifier):
    # PRD 2.7 lists no dedicated not-found code for entry_id; a missing entry
    # is still an existence failure and answers 404.
    row = db.ledger_entries.get(identifier)
    if row is None:
        raise ApiError("ERR_RESERVE_LEDGER_ENTRY_NOT_FOUND",
                       "reserve ledger entry not found", 404)
    return row


def invoice_for_batch(batch_id):
    for invoice in db.invoices.values():
        if invoice["usage_batch_id"] == batch_id:
            return invoice
    return None
