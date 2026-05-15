"""Insurance-claim routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import insurance_claims as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/insurance-claims")
    @require_auth("Renter")
    @with_lock
    def create_claim():
        return ok(svc.create_claim(get_json_body()), status=201)

    @app.get("/insurance-claims/<claim_id>")
    @require_auth("Renter", "InsuranceAgent", "Operator")
    @with_lock
    def get_claim(claim_id: str):
        return ok(svc.get_claim(claim_id))

    @app.post("/insurance-claims/<claim_id>/request-evidence")
    @require_auth("InsuranceAgent")
    @with_lock
    def request_evidence(claim_id: str):
        return ok(svc.request_evidence(claim_id, get_json_body()))

    @app.post("/insurance-claims/<claim_id>/evidence")
    @require_auth("Renter")
    @with_lock
    def submit_evidence(claim_id: str):
        return ok(svc.submit_evidence(claim_id, get_json_body()))

    @app.post("/insurance-claims/<claim_id>/reject-evidence")
    @require_auth("InsuranceAgent")
    @with_lock
    def reject_evidence(claim_id: str):
        return ok(svc.reject_evidence(claim_id, get_json_body()))

    @app.post("/insurance-claims/<claim_id>/approve")
    @require_auth("InsuranceAgent")
    @with_lock
    def approve_claim(claim_id: str):
        return ok(svc.approve_claim(claim_id, get_json_body()))

    @app.post("/insurance-claims/<claim_id>/deny")
    @require_auth("InsuranceAgent")
    @with_lock
    def deny_claim(claim_id: str):
        return ok(svc.deny_claim(claim_id, get_json_body()))

    @app.post("/insurance-claims/<claim_id>/pay")
    @require_auth("InsuranceAgent")
    @with_lock
    def pay_claim(claim_id: str):
        return ok(svc.pay_claim(claim_id, get_json_body()))
