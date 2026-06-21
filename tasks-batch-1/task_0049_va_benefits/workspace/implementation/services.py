"""Business-logic services: cascading recomputation of the Veteran's derived
fields, dependent helpers, and combined-rating input-set selection.

These functions mutate records in place but do NOT touch updated_at / version —
the caller (route handler) owns the decision to `touch()` a record, per the
PRD's recomputation-as-mutation rule (§2.7).
"""

import calculations as calc
from db import db


def active_dependents(veteran_id):
    """Return the veteran's ACTIVE dependents (PRD §3.2 / §3.8)."""
    return [
        d for d in db.dependents.values()
        if d["veteran_id"] == veteran_id and d["status"] == "ACTIVE"
    ]


def active_dependent_count(veteran_id):
    return len(active_dependents(veteran_id))


def service_connected_conditions(veteran_id):
    """Input set for the finalized combined rating: conditions whose
    service_connection is SERVICE_CONNECTED and final_rating_pct > 0
    (PRD §3.6)."""
    return [
        c for c in db.conditions.values()
        if c["veteran_id"] == veteran_id
        and c["service_connection"] == "SERVICE_CONNECTED"
        and c["final_rating_pct"] > 0
    ]


def recompute_combined_rating(veteran):
    """Recompute Veteran.combined_rating_pct from the full service-connected set
    (PRD §3.6, cascade hop 1->2)."""
    vid = veteran["id"]
    sc = service_connected_conditions(vid)
    veteran["combined_rating_pct"] = calc.va_combined_rating(
        sc, get_rating=lambda c: c["final_rating_pct"]
    )


def recompute_monthly_compensation(veteran):
    """Recompute Veteran.monthly_compensation_cents from the current combined
    rating + ACTIVE dependents (PRD §3.8, cascade hop 2->3)."""
    veteran["monthly_compensation_cents"] = calc.monthly_compensation(
        veteran["combined_rating_pct"], active_dependents(veteran["id"])
    )


def recompute_provisional_rating(veteran, rated_claim_id=None):
    """Recompute Veteran.provisional_combined_rating_pct (PRD §3.6 provisional
    variant).

    The provisional figure is the combined rating over the finalized
    SERVICE_CONNECTED set PLUS, when a claim is being rated, that claim's still-
    PROPOSED conditions contributing their proposed_rating_pct. When called
    after a grant/deny with no in-flight rated claim, it reduces to the combined
    rating over the SERVICE_CONNECTED set together with any other claim's PROPOSED
    conditions that have already been folded in at their own RATED time.

    We compute it generally: include all SERVICE_CONNECTED conditions
    (final_rating_pct) and all conditions belonging to claims currently in RATED
    status (proposed_rating_pct). When rated_claim_id is supplied that claim is
    in RATED status and is therefore already captured by the RATED scan.
    """
    vid = veteran["id"]
    included = []
    rated_claim_ids = {
        cl["id"] for cl in db.claims.values()
        if cl["veteran_id"] == vid and cl["status"] == "RATED"
    }
    for c in db.conditions.values():
        if c["veteran_id"] != vid:
            continue
        if c["service_connection"] == "SERVICE_CONNECTED" and c["final_rating_pct"] > 0:
            included.append((c, c["final_rating_pct"]))
        elif c["service_connection"] == "PROPOSED" and c["claim_id"] in rated_claim_ids:
            included.append((c, c["proposed_rating_pct"]))

    # Build a lookup so the combined-rating function can read the chosen rating.
    rating_by_id = {c["id"]: r for (c, r) in included}
    conds = [c for (c, _r) in included]
    prov = calc.va_combined_rating(conds, get_rating=lambda c: rating_by_id[c["id"]])

    # provisional never falls below combined_rating_pct (SCAFFOLD entity note).
    veteran["provisional_combined_rating_pct"] = max(prov, veteran["combined_rating_pct"])


def conditions_for_claim(claim_id):
    return [c for c in db.conditions.values() if c["claim_id"] == claim_id]
