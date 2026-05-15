"""Rental routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import rentals as svc
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/cabinets/<cabinet_id>/compartments/<compartment_id>/rentals")
    @require_auth("Renter")
    @with_lock
    def create_rental(cabinet_id: str, compartment_id: str):
        return ok(svc.create_rental(cabinet_id, compartment_id, get_json_body()), status=201)

    @app.get("/rentals/<rental_id>")
    @require_auth("Renter", "Operator")
    @with_lock
    def get_rental(rental_id: str):
        return ok(svc.get_rental(rental_id))

    @app.get("/rentals")
    @require_auth("Renter", "Operator")
    @with_lock
    def list_rentals():
        renter_id = request.args.get("renter_id")
        cabinet_id = request.args.get("cabinet_id")
        status = request.args.get("status")
        limit, offset = parse_limit_offset()
        items = svc.list_rentals(renter_id, cabinet_id, status)
        return ok_list(items, limit, offset)

    @app.post("/rentals/<rental_id>/renew")
    @require_auth("Renter")
    @with_lock
    def renew_rental(rental_id: str):
        return ok(svc.renew_rental(rental_id, get_json_body()))

    @app.post("/rentals/<rental_id>/return")
    @require_auth("Renter")
    @with_lock
    def return_rental(rental_id: str):
        return ok(svc.return_rental(rental_id, get_json_body()))

    @app.post("/rentals/<rental_id>/refund")
    @require_auth("Operator")
    @with_lock
    def refund_rental(rental_id: str):
        return ok(svc.refund_rental(rental_id, get_json_body()))
