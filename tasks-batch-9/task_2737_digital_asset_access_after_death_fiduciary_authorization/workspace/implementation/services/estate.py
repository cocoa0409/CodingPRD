"""Estate counters, compound phase derivation and the closure guard
(PRD sections 2.10, 3.2, 3.10).
"""
from db import DB, bump, sorted_records
from errors import ApiError
from services import lookup

DISCLOSED_STATUSES = ("CATALOG_DISCLOSED", "CONTENT_DISCLOSED")
PENDING_DISPOSITION = ("PENDING", "ELECTED")
DISPOSED = ("EXECUTED", "PURGED")
OPEN_ORDER_STATUSES = ("PENDING", "REQUESTED")
OPEN_CLAIM_STATUSES = ("FILED", "PLATFORM_REVIEW", "ESCALATED")

DERIVED_KEYS = (
    "inventory_total_count",
    "disclosed_asset_count",
    "assets_pending_disposition_count",
    "assets_disposed_count",
    "open_cancellation_count",
    "cancelled_subscription_count",
    "refund_recovered_cents",
    "valuation_basis",
    "administration_phase",
)


def has_verified_death_certificate(estate_id):
    return any(
        d["doc_type"] == "DEATH_CERTIFICATE" and d["verification_status"] == "VERIFIED"
        for d in lookup.estate_documents(estate_id)
    )


def has_issued_letters(estate_id):
    return any(
        f["letters_status"] == "ISSUED" for f in lookup.estate_fiduciaries(estate_id)
    )


def derive_phase(estate):
    """First matching rule wins (PRD section 3.2 / calculation 8)."""
    if estate.get("closed_at") is not None:
        return "CLOSED"
    eid = estate["id"]
    if not has_verified_death_certificate(eid):
        return "INTAKE"
    if not has_issued_letters(eid):
        return "INTAKE"
    if estate["disclosed_asset_count"] == 0:
        return "AUTHORIZED"
    if estate["inventory_total_count"] == 0:
        return "DISCLOSURE"
    if estate["assets_disposed_count"] < estate["inventory_total_count"]:
        return "DISCLOSURE"
    return "WIND_DOWN"


def recompute(estate):
    """Recompute every derived counter and the phase; advance the estate's
    version only when a stored field actually changed."""
    before = {k: estate.get(k) for k in DERIVED_KEYS}
    eid = estate["id"]
    assets = lookup.estate_assets(eid)
    estate["inventory_total_count"] = len(assets)
    estate["disclosed_asset_count"] = sum(
        1 for a in assets if a["access_status"] in DISCLOSED_STATUSES)
    estate["assets_pending_disposition_count"] = sum(
        1 for a in assets if a["disposition_status"] in PENDING_DISPOSITION)
    estate["assets_disposed_count"] = sum(
        1 for a in assets if a["disposition_status"] in DISPOSED)
    orders = lookup.estate_orders(eid)
    estate["open_cancellation_count"] = sum(
        1 for o in orders if o["status"] in OPEN_ORDER_STATUSES)
    estate["cancelled_subscription_count"] = sum(
        1 for t in lookup.estate_terms(eid) if t["state"] == "CANCELLED")
    estate["refund_recovered_cents"] = sum(
        c["credited_cents"] for c in lookup.estate_claims(eid)
        if c["status"] == "CREDITED")
    runs = sorted_records([r for r in lookup.estate_runs(eid)
                           if r["status"] in ("COMPUTED", "FINALIZED")])
    estate["valuation_basis"] = runs[-1]["basis"] if runs else None
    estate["administration_phase"] = derive_phase(estate)
    if any(estate.get(k) != before.get(k) for k in DERIVED_KEYS):
        bump(estate)
    return estate


def require_open(estate):
    """Estate closure guard -- priority 28, applied to every estate-owned write."""
    if estate.get("closed_at") is not None:
        raise ApiError("ERR_ESTATE_CLOSED")
    return estate


def newest_non_superseded_run(estate_id):
    runs = sorted_records([r for r in lookup.estate_runs(estate_id)
                           if r["status"] != "SUPERSEDED"])
    return runs[-1] if runs else None


def has_computed_or_finalized_run(estate_id):
    return any(r["status"] in ("COMPUTED", "FINALIZED")
               for r in lookup.estate_runs(estate_id))


def finalized_run(estate_id):
    for r in lookup.estate_runs(estate_id):
        if r["status"] == "FINALIZED":
            return r
    return None
