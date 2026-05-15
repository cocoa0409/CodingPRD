"""Compartment routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import compartments as svc
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/cabinets/<cabinet_id>/compartments")
    @require_auth("Operator")
    @with_lock
    def create_compartment(cabinet_id: str):
        return ok(svc.create_compartment(cabinet_id, get_json_body()), status=201)

    @app.get("/cabinets/<cabinet_id>/compartments/<compartment_id>")
    @require_auth("Operator", "Renter")
    @with_lock
    def get_compartment(cabinet_id: str, compartment_id: str):
        return ok(svc.get_compartment(cabinet_id, compartment_id))

    @app.get("/cabinets/<cabinet_id>/compartments")
    @require_auth("Operator", "Renter")
    @with_lock
    def list_compartments(cabinet_id: str):
        size_class = request.args.get("size_class")
        operational_status = request.args.get("operational_status")
        occupancy_status = request.args.get("occupancy_status")
        limit, offset = parse_limit_offset()
        items = svc.list_compartments(cabinet_id, size_class, operational_status, occupancy_status)
        return ok_list(items, limit, offset)

    @app.post("/compartments/<compartment_id>/claim-holding")
    @require_auth("Renter")
    @with_lock
    def claim_holding(compartment_id: str):
        return ok(svc.claim_holding(compartment_id))
