"""Serialize internal entity dicts to public JSON.

Strips internal-only keys (those prefixed with '_') so they never leak into
responses. Every other field is emitted verbatim.
"""


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
