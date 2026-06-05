"""Serialize internal records into their public JSON representation.

Internal records carry a private `_seq` ordering key that must never appear in
output. Every other field is emitted as stored. ResidualEvent is the only entity
with no updated_at / version (PRD section 2.4)."""


def public(record):
    """Strip private bookkeeping keys for the API response."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
