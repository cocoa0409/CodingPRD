"""Repair-ticket routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import repair_tickets as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/repair-tickets")
    @require_auth("Renter", "Operator")
    @with_lock
    def open_ticket():
        return ok(svc.open_ticket(get_json_body()), status=201)

    @app.get("/repair-tickets/<ticket_id>")
    @require_auth("Operator", "RepairTechnician")
    @with_lock
    def get_ticket(ticket_id: str):
        return ok(svc.get_ticket(ticket_id))

    @app.post("/repair-tickets/<ticket_id>/dispatch")
    @require_auth("Operator")
    @with_lock
    def dispatch_ticket(ticket_id: str):
        return ok(svc.dispatch_ticket(ticket_id, get_json_body()))

    @app.post("/repair-tickets/<ticket_id>/repair")
    @require_auth("RepairTechnician")
    @with_lock
    def repair_ticket(ticket_id: str):
        return ok(svc.repair_ticket(ticket_id, get_json_body()))

    @app.post("/repair-tickets/<ticket_id>/accept")
    @require_auth("Operator")
    @with_lock
    def accept_ticket(ticket_id: str):
        return ok(svc.accept_ticket(ticket_id, get_json_body()))

    @app.post("/repair-tickets/<ticket_id>/reject")
    @require_auth("Operator")
    @with_lock
    def reject_ticket(ticket_id: str):
        return ok(svc.reject_ticket(ticket_id, get_json_body()))
