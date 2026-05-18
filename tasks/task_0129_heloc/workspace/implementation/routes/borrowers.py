"""Borrower endpoints + bankruptcy event."""
from __future__ import annotations

import re

from flask import Blueprint

from db import store
from errors import err_already_bankrupt, err_validation_failed
from middleware import require_auth
from response import success
from services.engine import (
    cascade_default_for_borrower,
    stamp_create,
    stamp_ledger,
    stamp_update,
)
from services.serializers import bankruptcy_event_view, borrower_view

from routes._helpers import (
    enforce_borrower_self,
    get_borrower_or_404,
    get_json,
    get_string,
)

bp = Blueprint("borrowers", __name__)


# Relaxed RFC-5322-shaped email check. Tests do not need full RFC
# compliance; a sensible shape predicate prevents nonsense input
# from being accepted while accepting reasonable test fixtures.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.post("/borrowers")
@require_auth(["Originator", "PlatformAdmin"], endpoint_key="POST /borrowers")
def create_borrower():
    body = get_json()
    full_name = get_string(body, "full_name", required=True)
    email = get_string(body, "email", required=True)
    if not (1 <= len(full_name) <= 200):
        raise err_validation_failed("full_name must be 1..200 chars.")
    if not _EMAIL_RE.match(email):
        raise err_validation_failed("email is not RFC-5322 shaped.")

    with store.lock:
        # Uniqueness check on email.
        for existing in store.borrowers.values():
            if existing["email"] == email:
                raise err_validation_failed("email already registered.")
        b = {
            "full_name": full_name,
            "email": email,
            "bankruptcy_flag": False,
            "bankruptcy_filed_at": None,
        }
        stamp_create(b)
        store.borrowers[b["id"]] = b
    return success(borrower_view(b), 201)


@bp.get("/borrowers/<bid>")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /borrowers/{id}",
)
def get_borrower(bid: str):
    b = get_borrower_or_404(bid)
    enforce_borrower_self(b["id"])
    return success(borrower_view(b), 200)


@bp.post("/borrowers/<bid>/bankruptcy-events")
@require_auth(
    ["Servicer", "PlatformAdmin"],
    endpoint_key="POST /borrowers/{id}/bankruptcy-events",
)
def create_bankruptcy_event(bid: str):
    with store.lock:
        b = get_borrower_or_404(bid)
        # Validation priority 17: borrower not already bankrupt.
        if b["bankruptcy_flag"]:
            raise err_already_bankrupt()
        # Persist the event first so we can use its id as source_event_id.
        evt = {
            "borrower_id": bid,
            "recorded_at": store.now(),
        }
        stamp_ledger(evt)
        store.bankruptcy_events[evt["id"]] = evt
        # Update the borrower.
        b["bankruptcy_flag"] = True
        b["bankruptcy_filed_at"] = store.now()
        stamp_update(b)
        # Cascade default to every DRAW/REPAY HELOC owned by this borrower.
        cascade_default_for_borrower(bid, source_event_id=evt["id"])
    return success(bankruptcy_event_view(evt), 201)
