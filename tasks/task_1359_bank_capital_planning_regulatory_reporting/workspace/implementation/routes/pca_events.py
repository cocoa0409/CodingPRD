"""PCAThresholdEvent endpoints (PRD 3.8)."""

from __future__ import annotations

from flask import Blueprint

from db import pca_threshold_events
from middleware import require_roles
from response import success_object, success_list
from services.core import ser_pca_event, get_bank, get_pca_event
from util import apply_filters, sorted_page

bp = Blueprint("pca_events", __name__)


@bp.route("/banks/<bankId>/pca-threshold-events", methods=["GET"])
@require_roles("Any")
def list_pca_events(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [e for e in pca_threshold_events.values() if e["bank_id"] == bank["id"]]
    items = apply_filters(items, {"metric": "metric", "breached": "breached"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_pca_event(e) for e in page], limit, offset, total)


@bp.route("/banks/<bankId>/pca-threshold-events/<eventId>", methods=["GET"])
@require_roles("Any")
def get_one_pca_event(bankId: str, eventId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_pca_event(get_pca_event(bank, eventId)))
