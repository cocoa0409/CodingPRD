"""Clients, the portfolio summary and client payments."""

import envelope
import listing
import lookup
import serializers
from constants import OPEN_OBLIGATION_STATUSES, RANK_TO_STATUS
from dispatch import endpoint
from services import rollups
from store import DB, new_row, ordered


@endpoint("POST", "/clients", roles=["PlatformAdmin"], success_code=201)
def create_client(context):
    legal_name = context.body.string("legal_name", required=True, max_len=200)
    billing_email = context.body.string("billing_email", required=True)
    row = new_row(
        DB.clients,
        {
            "legal_name": legal_name,
            "billing_email": billing_email,
            "credit_balance_cents": 0,
            "portfolio_entity_count": 0,
            "portfolio_open_obligation_count": 0,
            "portfolio_outstanding_cents": 0,
            "portfolio_delinquency_status": "CURRENT",
            "sop_open_escalation_count": 0,
            "portfolio_risk_flag": False,
        },
    )
    return envelope.object_response(serializers.client(row), 201)


@endpoint(
    "GET",
    "/clients/{id}",
    roles=["PlatformAdmin", "ComplianceOfficer", "ClientContact"],
    success_code=200,
)
def read_client(context):
    return envelope.object_response(serializers.client(context.row))


@endpoint(
    "GET",
    "/clients/{id}/portfolio-summary",
    roles=["PlatformAdmin", "ComplianceOfficer", "ClientContact"],
    success_code=200,
)
def portfolio_summary(context):
    client = context.row
    registrations = lookup.registrations_of_client(client["id"])
    open_rows = [
        o
        for o in lookup.obligations_of_client(client["id"])
        if o["status"] in OPEN_OBLIGATION_STATUSES
    ]
    # ADJUDICATION OF FRICTION 3 -- the portfolio summary.
    #  (a) registration_count: PRD 3.1 says "the number of registration rows
    #      the client holds across all of its entities, counted in EVERY
    #      status".  Reading: EVERY STATUS, terminal rows included.  This is
    #      also the reachability-maximising reading: worst_state_code is drawn
    #      from the same population and the per-state figures must sum to the
    #      client-level totals, both of which are taken over registrations "in
    #      any status" by PRD 2.11.
    #  (b) worst_state_code on a tie at the highest delinquency_rank: PRD 3.1
    #      names no tie-break, so the row is chosen by the document's own
    #      default list ordering (ascending created_at, then insertion order),
    #      i.e. the FIRST registration created among those at the maximum
    #      rank.  A deterministic pick keeps the field assertable; leaving it
    #      arbitrary would make it untestable.
    worst_state_code = None
    if registrations:
        best_rank = max(r["delinquency_rank"] for r in registrations)
        tied = ordered([r for r in registrations if r["delinquency_rank"] == best_rank])
        worst_state_code = tied[0]["state_code"]
        delinquency_status = RANK_TO_STATUS[best_rank]
    else:
        delinquency_status = RANK_TO_STATUS[0]
    data = {
        "client_id": client["id"],
        "entity_count": sum(
            1 for e in lookup.entities_of_client(client["id"]) if e["lifecycle_status"] != "DISSOLVED"
        ),
        "registration_count": len(registrations),
        "open_obligation_count": len(open_rows),
        "outstanding_cents": sum(o["total_due_cents"] for o in open_rows),
        "delinquency_status": delinquency_status,
        "worst_state_code": worst_state_code,
        "credit_balance_cents": client["credit_balance_cents"],
    }
    return envelope.object_response(data)


@endpoint(
    "GET",
    "/clients/{id}/legal-entities",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"],
    success_code=200,
)
def list_legal_entities(context):
    rows = lookup.entities_of_client(context.row["id"])
    rows = listing.apply_filters(rows, [("lifecycle_status", "lifecycle_status")])
    return listing.respond(rows, serializers.legal_entity)


@endpoint(
    "POST", "/clients/{id}/payments", roles=["PlatformAdmin", "ClientContact"], success_code=201
)
def authorize_payment(context):
    amount = context.body.integer("authorized_amount_cents", required=True, minimum=1)
    row = new_row(
        DB.payments,
        {
            "client_id": context.row["id"],
            "authorized_amount_cents": amount,
            "captured_amount_cents": 0,
            "allocated_amount_cents": 0,
            "unallocated_amount_cents": 0,
            "refunded_amount_cents": 0,
            "status": "AUTHORIZED",
        },
    )
    rollups.recompute_client(context.row)
    return envelope.object_response(serializers.payment(row), 201)


@endpoint(
    "GET", "/clients/{id}/payments", roles=["PlatformAdmin", "ClientContact"], success_code=200
)
def list_payments(context):
    rows = [p for p in DB.payments.values() if p["client_id"] == context.row["id"]]
    rows = listing.apply_filters(rows, [("status", "status")])
    return listing.respond(rows, serializers.payment)
