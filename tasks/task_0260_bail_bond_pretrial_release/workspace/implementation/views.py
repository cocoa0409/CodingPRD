"""Serialization: strip internal-only fields before returning records.

Internal fields (never exposed in the API payload):
  - activated_by_user_id on Bond (segregation-of-duties bookkeeping)
  - passed_recovery_open on ForfeitureProceeding (judgment-credit bookkeeping)
"""

_INTERNAL = {
    "activated_by_user_id",
    "passed_recovery_open",
}


def view(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def view_list(records):
    return [view(r) for r in records]
