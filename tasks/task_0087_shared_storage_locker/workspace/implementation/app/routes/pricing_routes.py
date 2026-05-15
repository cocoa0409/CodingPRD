"""Pricing profile routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import pricing_profiles as svc
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/pricing-profiles")
    @require_auth("Operator")
    @with_lock
    def create_pricing_profile():
        return ok(svc.create_pricing_profile(get_json_body()), status=201)

    @app.get("/pricing-profiles")
    @require_auth("Operator", "Renter")
    @with_lock
    def list_pricing_profiles():
        size_class = request.args.get("size_class")
        rental_mode = request.args.get("rental_mode")
        limit, offset = parse_limit_offset()
        items = svc.list_pricing_profiles(size_class, rental_mode)
        return ok_list(items, limit, offset)
