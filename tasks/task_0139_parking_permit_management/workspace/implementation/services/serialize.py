"""Entity serialization — strip internal bookkeeping keys before responding."""
from __future__ import annotations

from typing import Any, Dict

# Internal keys that must never appear in API output.
_INTERNAL = {"_seq"}


def public(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in obj.items() if k not in _INTERNAL}


def public_list(objs) -> list:
    return [public(o) for o in objs]
