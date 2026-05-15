"""Confirmation endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..services.confirmations import (
    create_confirmation,
    fail_confirmation,
    issue_confirmation,
    seal_confirmation,
)
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def _enrich_confirmation(confirmation: dict) -> dict:
    """Decorate the confirmation response with sibling Payment reference.

    PRD §3.9: issuing a confirmation creates a Payment row keyed by
    confirmation_id. Expose that id on the confirmation so callers can
    navigate without a separate /payments lookup.
    """
    store = get_store()
    enriched = dict(confirmation)
    payment = None
    for p in store.payments.values():
        if p.get("confirmation_id") == confirmation["id"]:
            payment = p
            break
    enriched["payment_id"] = payment["id"] if payment else None
    return enriched


def register(app: Flask) -> None:
    @app.route("/confirmations", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _create_confirmation():
        body = get_json_body()
        return ok(_enrich_confirmation(create_confirmation(body)), 201)

    @app.route("/confirmations/<string:confirmation_id>/issue", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _issue(confirmation_id: str):
        store = get_store()
        if confirmation_id not in store.confirmations:
            raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
        body = get_json_body()
        check_version(store.confirmations[confirmation_id], body)
        return ok(_enrich_confirmation(issue_confirmation(confirmation_id)))

    @app.route("/confirmations/<string:confirmation_id>/fail", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _fail(confirmation_id: str):
        store = get_store()
        if confirmation_id not in store.confirmations:
            raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
        body = get_json_body()
        check_version(store.confirmations[confirmation_id], body)
        return ok(_enrich_confirmation(fail_confirmation(confirmation_id, body)))

    @app.route("/confirmations/<string:confirmation_id>/seal", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _seal(confirmation_id: str):
        store = get_store()
        if confirmation_id not in store.confirmations:
            raise ApiError("ERR_NOT_FOUND", f"Confirmation {confirmation_id} not found.")
        body = get_json_body()
        check_version(store.confirmations[confirmation_id], body)
        return ok(_enrich_confirmation(seal_confirmation(confirmation_id)))
