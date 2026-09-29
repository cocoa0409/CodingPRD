"""Rung 3 (path existence) and rung 4 (body reference) resolution helpers."""

import db
from errors import ApiError


def _find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "No such resource: %s." % row_id)
    return row


# ------------------------------------------------------- rung 3: path existence
def move_or_404(move_id):
    return _find(db.db.moves, move_id, "ERR_MOVE_NOT_FOUND")


def resident_or_404(resident_id):
    return _find(db.db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")


def order_or_404(order_id):
    return _find(db.db.orders, order_id, "ERR_UTILITY_ORDER_NOT_FOUND")


def handoff_or_404(handoff_id):
    return _find(db.db.handoffs, handoff_id, "ERR_HANDOFF_NOT_FOUND")


def filing_or_404(filing_id):
    return _find(db.db.filings, filing_id, "ERR_FILING_NOT_FOUND")


def placement_or_404(placement_id):
    return _find(db.db.placements, placement_id, "ERR_PLACEMENT_NOT_FOUND")


def consent_or_404(consent_id):
    return _find(db.db.consents, consent_id, "ERR_CONSENT_NOT_FOUND")


def verification_or_404(verification_id):
    return _find(db.db.verifications, verification_id, "ERR_VERIFICATION_NOT_FOUND")


def feed_source_or_404(feed_id):
    return _find(db.db.feed_sources, feed_id, "ERR_REFERENCE_NOT_FOUND")


def address_or_404(address_id):
    return _find(db.db.service_addresses, address_id, "ERR_REFERENCE_NOT_FOUND")


def provider_or_404(provider_id):
    return _find(db.db.utility_providers, provider_id, "ERR_REFERENCE_NOT_FOUND")


def territory_or_404(territory_id):
    return _find(db.db.territories, territory_id, "ERR_REFERENCE_NOT_FOUND")


def partner_or_404(partner_id):
    return _find(db.db.partners, partner_id, "ERR_REFERENCE_NOT_FOUND")


def ledger_entry_or_404(entry_id):
    return _find(db.db.ledger, entry_id, "ERR_REFERENCE_NOT_FOUND")


# ----------------------------------------------------- rung 4: body references
def ref(collection, value):
    """Resolve a body reference, raising ERR_REFERENCE_NOT_FOUND on a miss."""
    if value is None:
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "Referenced resource %s does not exist." % value)
    return row


def ref_move(value):
    return ref(db.db.moves, value)


def ref_resident(value):
    return ref(db.db.residents, value)


def ref_feed_source(value):
    return ref(db.db.feed_sources, value)


def ref_address(value):
    return ref(db.db.service_addresses, value)


def ref_provider(value):
    return ref(db.db.utility_providers, value)


def ref_partner(value):
    return ref(db.db.partners, value)


# -------------------------------------------------------------- child listings
def orders_of_move(move_id):
    return sorted(
        [o for o in db.db.orders.values() if o["move_id"] == move_id],
        key=db.order_key,
    )


def verifications_of_move(move_id):
    return sorted(
        [v for v in db.db.verifications.values() if v["move_id"] == move_id],
        key=db.order_key,
    )


def filings_of_move(move_id):
    return sorted(
        [f for f in db.db.filings.values() if f["move_id"] == move_id],
        key=db.order_key,
    )


def placements_of_move(move_id):
    return sorted(
        [p for p in db.db.placements.values() if p["move_id"] == move_id],
        key=db.order_key,
    )


def handoffs_of_order(order_id):
    return sorted(
        [h for h in db.db.handoffs.values() if h["utility_order_id"] == order_id],
        key=db.order_key,
    )


def consents_of_resident(resident_id):
    return sorted(
        [c for c in db.db.consents.values() if c["resident_id"] == resident_id],
        key=db.order_key,
    )


def moves_of_resident(resident_id):
    return sorted(
        [m for m in db.db.moves.values() if m["resident_id"] == resident_id],
        key=db.order_key,
    )


def placements_of_partner(partner_id):
    return sorted(
        [p for p in db.db.placements.values() if p["partner_id"] == partner_id],
        key=db.order_key,
    )
