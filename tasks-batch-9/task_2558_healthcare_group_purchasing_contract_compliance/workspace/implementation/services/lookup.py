"""Path and body foreign-key resolution (PRD section 2.8)."""

from db import db
from errors import ApiError

_NOT_FOUND = {
    "contract": "ERR_CONTRACT_NOT_FOUND",
    "contract_item": "ERR_CONTRACT_ITEM_NOT_FOUND",
    "member": "ERR_MEMBER_NOT_FOUND",
    "commitment": "ERR_COMMITMENT_NOT_FOUND",
    "xref": "ERR_XREF_NOT_FOUND",
    "activation": "ERR_ACTIVATION_NOT_FOUND",
    "file": "ERR_FILE_NOT_FOUND",
    "measurement": "ERR_MEASUREMENT_NOT_FOUND",
    "distribution": "ERR_DISTRIBUTION_NOT_FOUND",
    "review": "ERR_REVIEW_NOT_FOUND",
    "purchase_line": "ERR_PURCHASE_LINE_NOT_FOUND",
}

_COLLECTIONS = {
    "contract": "contracts",
    "contract_item": "contract_items",
    "member": "members",
    "commitment": "commitments",
    "xref": "xrefs",
    "activation": "activations",
    "file": "files",
    "measurement": "measurements",
    "distribution": "distributions",
    "review": "reviews",
    "purchase_line": "purchase_lines",
}


def fetch(kind, identifier):
    """Resolve one identifier or raise that entity's not-found error."""
    collection = getattr(db, _COLLECTIONS[kind])
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[kind])
    return row


def get_contract(identifier):
    return fetch("contract", identifier)


def get_contract_item(identifier):
    return fetch("contract_item", identifier)


def get_member(identifier):
    return fetch("member", identifier)


def get_commitment(identifier):
    return fetch("commitment", identifier)


def get_xref(identifier):
    return fetch("xref", identifier)


def get_activation(identifier):
    return fetch("activation", identifier)


def get_file(identifier):
    return fetch("file", identifier)


def get_measurement(identifier):
    return fetch("measurement", identifier)


def get_distribution(identifier):
    return fetch("distribution", identifier)


def get_review(identifier):
    return fetch("review", identifier)


def get_purchase_line(identifier):
    return fetch("purchase_line", identifier)


# Foreign keys named in a request body are resolved after the path identifiers,
# in this order: contract_id, member_id, contract_item_id, commitment_id.
BODY_FK_ORDER = (
    ("contract_id", "contract"),
    ("member_id", "member"),
    ("contract_item_id", "contract_item"),
    ("commitment_id", "commitment"),
)


def resolve_body_fks(body, keys):
    """Resolve the requested body foreign keys in the canonical order.

    Values that are absent or not strings are left to rung 6 (request shape).
    """
    resolved = {}
    wanted = set(keys)
    for key, kind in BODY_FK_ORDER:
        if key not in wanted:
            continue
        value = body.get(key) if isinstance(body, dict) else None
        if not isinstance(value, str) or value == "":
            resolved[key] = None
            continue
        resolved[key] = fetch(kind, value)
    return resolved
