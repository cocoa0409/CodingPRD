"""Cross-entity cascades and shared lookup/pagination helpers."""
from flask import request

import errors
from store import db, touch, now_ts
from calc import (
    recompute_shares,
    recompute_committed,
    recompute_mod_tally,
    recompute_default_tally,
    facility_participants,
)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id):
    ent = db[collection].get(entity_id)
    if ent is None:
        raise errors.not_found(f"Resource {entity_id} not found")
    return ent


def paginate(items):
    """created_at ASC (stable on insertion sequence), limit/offset with
    defaults 10/0 and clamping to [1, 100] / [0, inf)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def apply_filters(items, filters):
    """filters: list of (query_param, entity_field)."""
    out = items
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            out = [e for e in out if str(e.get(field)) == val]
    return out


# ---------------------------------------------------------------------------
# cascade helpers
# ---------------------------------------------------------------------------

def void_participant_votes(participant):
    """On participant exit: CAST/RECAST votes on SOLICITING solicitations and
    on DECLARED default cases become VOIDED."""
    pid = participant["id"]
    for v in db["consent_votes"].values():
        if v["participant_id"] != pid or v["status"] not in ("CAST", "RECAST"):
            continue
        mod = db["modifications"].get(v["modification_id"])
        if mod is None or mod["status"] != "SOLICITING":
            continue
        v["status"] = "VOIDED"
        touch(v)
    for v in db["default_votes"].values():
        if v["participant_id"] != pid or v["status"] not in ("CAST", "RECAST"):
            continue
        case = db["default_cases"].get(v["default_case_id"])
        if case is None or case["status"] != "DECLARED":
            continue
        v["status"] = "VOIDED"
        touch(v)


def exit_participant(participant, facility, base_reduction):
    """Shared exit cascade (full transfer / buyback settle).

    base_reduction is how much commitment leaves the voting bases: the full
    commitment on buyback (agent retains the position), zero on transfer
    (the transferee absorbs it). Tallies of every live solicitation/default
    case on the facility recompute against the adjusted base.
    """
    from store import clock_dt

    participant["status"] = "EXITED"
    participant["_exit"] = {"at": clock_dt(), "reduction": base_reduction}
    touch(participant)
    void_participant_votes(participant)
    recompute_committed(facility)
    recompute_shares(facility)
    for mod in db["modifications"].values():
        if mod["facility_id"] == facility["id"] and mod["status"] == "SOLICITING":
            recompute_mod_tally(mod)
    for case in db["default_cases"].values():
        if case["facility_id"] == facility["id"] and case["status"] == "DECLARED":
            recompute_default_tally(case)


def restore_borrower_if_clear(borrower):
    """Borrower returns to ACTIVE exactly when no DECLARED default case
    remains on any of its facilities."""
    if borrower["status"] == "ACTIVE":
        return
    for case in db["default_cases"].values():
        if case["status"] != "DECLARED":
            continue
        fac = db["facilities"].get(case["facility_id"])
        if fac is not None and fac["borrower_id"] == borrower["id"]:
            return
    borrower["status"] = "ACTIVE"
    touch(borrower)


def has_remitted_payment(facility):
    return any(
        p["facility_id"] == facility["id"] and p["status"] == "REMITTED"
        for p in db["payments"].values()
    )


def facility_close_status(facility, fallback):
    """CLOSED when fully repaid with at least one remitted payment."""
    if (
        facility["outstanding_principal_cents"] == 0
        and facility["accrued_interest_cents"] == 0
        and has_remitted_payment(facility)
    ):
        return "CLOSED"
    return fallback


def maybe_close_facility(facility):
    if facility["status"] in ("ACTIVE", "ACCELERATED"):
        new_status = facility_close_status(facility, facility["status"])
        if new_status != facility["status"]:
            facility["status"] = new_status
            touch(facility)
