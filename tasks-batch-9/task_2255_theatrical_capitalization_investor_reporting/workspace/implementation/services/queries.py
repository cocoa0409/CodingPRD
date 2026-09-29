"""Row selection helpers.  Every list is ordered by created_at ascending."""

import db


def _ordered(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def docs_of(production_id):
    return _ordered(d for d in db.store["offering_documents"].values()
                    if d["production_id"] == production_id)


def subs_of_doc(document_id):
    return _ordered(s for s in db.store["subscriptions"].values()
                    if s["offering_document_id"] == document_id)


def subs_of_production(production_id):
    doc_ids = {d["id"] for d in docs_of(production_id)}
    return _ordered(s for s in db.store["subscriptions"].values()
                    if s["offering_document_id"] in doc_ids)


def accounts_of(production_id):
    return _ordered(a for a in db.store["investor_accounts"].values()
                    if a["production_id"] == production_id)


def account_for(production_id, investor_id):
    for a in accounts_of(production_id):
        if a["investor_id"] == investor_id:
            return a
    return None


def participants_of(production_id):
    return _ordered(p for p in db.store["royalty_participants"].values()
                    if p["production_id"] == production_id)


def budget_lines_of(production_id):
    return _ordered(b for b in db.store["budget_lines"].values()
                    if b["production_id"] == production_id)


def operating_budgets_of(production_id):
    return _ordered(o for o in db.store["operating_budgets"].values()
                    if o["production_id"] == production_id)


def active_operating_budgets(production_id):
    return [o for o in operating_budgets_of(production_id)
            if o["status"] == "ACTIVE"]


def wraps_of(production_id):
    return _ordered(w for w in db.store["weekly_wraps"].values()
                    if w["production_id"] == production_id)


def allocations_of_wrap(wrap_id):
    return _ordered(a for a in db.store["royalty_allocations"].values()
                    if a["wrap_id"] == wrap_id)


def allocations_of_participant(participant_id):
    return _ordered(a for a in db.store["royalty_allocations"].values()
                    if a["royalty_participant_id"] == participant_id)


def income_of(production_id):
    return _ordered(s for s in db.store["subsidiary_rights_income"].values()
                    if s["production_id"] == production_id)


def distributions_of(production_id):
    return _ordered(d for d in db.store["investor_distributions"].values()
                    if d["production_id"] == production_id)


def notices_of(production_id):
    return _ordered(c for c in db.store["closing_notices"].values()
                    if c["production_id"] == production_id)


def engagements_of_theatre(theatre_id):
    return _ordered(e for e in db.store["theatre_engagements"].values()
                    if e["theatre_id"] == theatre_id)


def eligible_participants(production_id):
    """SCAFFOLD wrap_settlement input_set / PRD 3.7: ACTIVE participations
    holding at least one pool point, ordered by pool_points DESC then
    created_at ASC."""
    rows = [p for p in participants_of(production_id)
            if p["status"] == "ACTIVE" and p["pool_points"] > 0]
    return sorted(rows, key=lambda p: (-p["pool_points"], p["_seq"]))
