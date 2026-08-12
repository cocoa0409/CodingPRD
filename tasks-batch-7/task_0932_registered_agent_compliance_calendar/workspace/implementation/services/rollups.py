"""Delinquency ranking and portfolio rollups (PRD 2.11).

None of these recomputations bumps a version or refreshes updated_at: PRD 3.13
requires that an ops-run which finds nothing to do "mutates nothing at all --
no version bumps, no updated_at refreshes", and every one of these rollups runs
on every ops-run.  Only the declared state transitions bump versions.
"""

import lookup
from constants import (
    OBLIGATION_RANK,
    OPEN_OBLIGATION_STATUSES,
    RANK_ADMIN_DISSOLVED,
    RANK_CURRENT,
    RANK_TO_STATUS,
    SOP_RISK_FLAG_THRESHOLD,
)
from store import DB


def registration_rank(registration):
    if registration["status"] in ("ADMIN_DISSOLVED", "CLOSED_PERMANENT"):
        return RANK_ADMIN_DISSOLVED
    open_obligations = [
        o
        for o in lookup.obligations_of_registration(registration["id"])
        if o["status"] in OPEN_OBLIGATION_STATUSES
    ]
    if not open_obligations:
        return RANK_CURRENT
    return max(OBLIGATION_RANK[o["status"]] for o in open_obligations)


def recompute_registration_rank(registration):
    registration["delinquency_rank"] = registration_rank(registration)
    return registration["delinquency_rank"]


def entity_posture(entity):
    registrations = lookup.registrations_of_entity(entity["id"])
    if not registrations:
        return RANK_TO_STATUS[RANK_CURRENT]
    return RANK_TO_STATUS[max(r["delinquency_rank"] for r in registrations)]


def recompute_entity(entity):
    entity["compliance_posture"] = entity_posture(entity)


def sop_open_escalation_count(client_id):
    total = 0
    registration_ids = {r["id"] for r in lookup.registrations_of_client(client_id)}
    open_documents = {
        d["id"]
        for d in DB.sop_documents.values()
        if d["registration_id"] in registration_ids and d["status"] in ("FORWARDED", "ESCALATED")
    }
    for event in DB.sop_events.values():
        if event["sop_document_id"] in open_documents:
            total += 1
    return total


def recompute_client(client):
    client_id = client["id"]
    entities = lookup.entities_of_client(client_id)
    client["portfolio_entity_count"] = sum(
        1 for e in entities if e["lifecycle_status"] != "DISSOLVED"
    )
    open_rows = [
        o for o in lookup.obligations_of_client(client_id) if o["status"] in OPEN_OBLIGATION_STATUSES
    ]
    client["portfolio_open_obligation_count"] = len(open_rows)
    client["portfolio_outstanding_cents"] = sum(o["total_due_cents"] for o in open_rows)
    registrations = lookup.registrations_of_client(client_id)
    if registrations:
        client["portfolio_delinquency_status"] = RANK_TO_STATUS[
            max(r["delinquency_rank"] for r in registrations)
        ]
    else:
        client["portfolio_delinquency_status"] = RANK_TO_STATUS[RANK_CURRENT]
    client["sop_open_escalation_count"] = sop_open_escalation_count(client_id)
    client["portfolio_risk_flag"] = client["sop_open_escalation_count"] >= SOP_RISK_FLAG_THRESHOLD
    client["credit_balance_cents"] = sum(
        p["refunded_amount_cents"] for p in DB.payments.values() if p["client_id"] == client_id
    )


def cascade_from_registration(registration):
    """Registration rank -> entity posture -> client rollup (PRD 2.11)."""
    if registration is None:
        return
    recompute_registration_rank(registration)
    entity = lookup.entity_of_registration(registration)
    if entity is None:
        return
    recompute_entity(entity)
    client = DB.clients.get(entity["client_id"])
    if client is not None:
        recompute_client(client)


def cascade_from_entity(entity):
    if entity is None:
        return
    for registration in lookup.registrations_of_entity(entity["id"]):
        recompute_registration_rank(registration)
    recompute_entity(entity)
    client = DB.clients.get(entity["client_id"])
    if client is not None:
        recompute_client(client)


def cascade_from_obligation(obligation):
    registration = DB.registrations.get(obligation["registration_id"])
    cascade_from_registration(registration)


def cascade_from_client(client):
    if client is None:
        return
    for entity in lookup.entities_of_client(client["id"]):
        for registration in lookup.registrations_of_entity(entity["id"]):
            recompute_registration_rank(registration)
        recompute_entity(entity)
    recompute_client(client)


def recompute_everything():
    for registration in DB.registrations.values():
        recompute_registration_rank(registration)
    for entity in DB.legal_entities.values():
        recompute_entity(entity)
    for client in DB.clients.values():
        recompute_client(client)
