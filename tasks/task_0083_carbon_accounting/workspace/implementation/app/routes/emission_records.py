"""EmissionRecord listing endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..response import list_envelope
from ..services.calculations import derive_scope
from ..store import store
from ..utils import page_slice, parse_pagination
from ._helpers import get_org_or_404, get_period_or_404


emission_records_bp = Blueprint("emission_records", __name__)


@emission_records_bp.route(
    "/organizations/<org_id>/reporting-periods/<period_id>/emission-records", methods=["GET"]
)
@require_auth(["DataSteward", "Verifier", "Discloser"])
def list_emission_records(org_id, period_id):
    get_org_or_404(org_id)
    get_period_or_404(org_id, period_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    scope_f = request.args.get("scope")

    items = []
    for er in store.emission_records.values():
        if er.get("reporting_period_id") != period_id:
            continue
        if status_f is not None and er.get("status") != status_f:
            continue
        if scope_f is not None:
            ad = store.activity_data.get(er.get("activity_data_id"))
            if not ad:
                continue
            src = store.emission_sources.get(ad.get("emission_source_id"))
            if not src or derive_scope(src.get("category", "")) != scope_f:
                continue
        items.append(er)
    items.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
