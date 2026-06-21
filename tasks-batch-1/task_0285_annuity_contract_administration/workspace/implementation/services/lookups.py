"""Resolution helpers for path resources (ERR_RESOURCE_NOT_FOUND) and FK body
references (ERR_REFERENCED_RESOURCE_NOT_FOUND) — PRD §2.8.
"""

import errors
from db import store


def _get_or_path_404(collection, rid):
    obj = collection.get(rid)
    if obj is None:
        raise errors.not_found()
    return obj


def path_product(rid):
    return _get_or_path_404(store.products, rid)


def path_contract(rid):
    return _get_or_path_404(store.contracts, rid)


def path_premium(rid):
    return _get_or_path_404(store.premiums, rid)


def path_allocation(rid):
    return _get_or_path_404(store.sub_account_allocations, rid)


def path_segment(rid):
    return _get_or_path_404(store.index_segments, rid)


def path_crediting_event(rid):
    return _get_or_path_404(store.crediting_events, rid)


def path_withdrawal(rid):
    return _get_or_path_404(store.withdrawals, rid)


def path_beneficiary(rid):
    return _get_or_path_404(store.beneficiaries, rid)


def path_annuitization(rid):
    return _get_or_path_404(store.annuitizations, rid)


def path_death_claim(rid):
    return _get_or_path_404(store.death_claims, rid)


def path_exchange(rid):
    return _get_or_path_404(store.exchanges, rid)


def ref_contract(rid):
    obj = store.contracts.get(rid)
    if obj is None:
        raise errors.referenced_not_found("Referenced contract does not exist.")
    return obj


def ref_product(rid):
    obj = store.products.get(rid)
    if obj is None:
        raise errors.referenced_not_found("Referenced product does not exist.")
    return obj


def ref_segment(rid):
    obj = store.index_segments.get(rid)
    if obj is None:
        raise errors.referenced_not_found("Referenced index segment does not exist.")
    return obj


def ref_allocation(rid):
    obj = store.sub_account_allocations.get(rid)
    if obj is None:
        raise errors.referenced_not_found("Referenced allocation does not exist.")
    return obj


def ref_exchange(rid):
    obj = store.exchanges.get(rid)
    if obj is None:
        raise errors.referenced_not_found("Referenced exchange does not exist.")
    return obj


def paginate(rows, limit, offset):
    """rows: list already sorted by (created_at, _seq) ASC. Returns
    (page_items, total_count)."""
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, total


def sorted_by_creation(items):
    """Sort a list of entities by created_at ASC, ties by insertion seq."""
    return sorted(items, key=lambda o: (o["created_at"], o.get("_seq", 0)))
