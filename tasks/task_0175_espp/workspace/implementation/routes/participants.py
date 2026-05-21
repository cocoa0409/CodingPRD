"""Per-participant routes: purchases, form-3922 list, accrual-summary, dispositions."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_response
from core.errors import APIError
from core.pagination import paginate, parse_pagination
from core.serializers import (
    disposition_view,
    form_3922_view,
    purchase_view,
)
from services.disposition_service import list_dispositions_for_participant
from services.form_service import list_forms_for_participant
from services.participant_service import accrual_summary
from services.purchase_service import list_purchases_for_participant


bp = Blueprint("participants", __name__)


def _parse_calendar_year() -> int:
    raw = request.args.get("calendar_year")
    if raw is None:
        raise APIError(
            "ERR_PAGINATION_INVALID",
            "calendar_year is required.",
            422,
        )
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise APIError(
            "ERR_PAGINATION_INVALID",
            "calendar_year must be an integer.",
            422,
        )


@bp.route("/participants/<participant_id>/purchases", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def list_purchases(participant_id: str):
    limit, offset = parse_pagination()
    hps = request.args.get("holding_period_status")
    ds = request.args.get("disposition_status")
    items = list_purchases_for_participant(
        participant_id,
        holding_period_status=hps,
        disposition_status=ds,
    )
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [purchase_view(p) for p in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )


@bp.route("/participants/<participant_id>/form-3922", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def list_forms(participant_id: str):
    limit, offset = parse_pagination()
    year = _parse_calendar_year()
    items = list_forms_for_participant(participant_id, calendar_year=year)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [form_3922_view(f) for f in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )


@bp.route("/participants/<participant_id>/accrual-summary", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def get_accrual_summary(participant_id: str):
    year = _parse_calendar_year()
    include_raw = request.args.get("include_projection")
    if include_raw is None:
        include_projection = True
    else:
        lowered = include_raw.lower()
        if lowered in ("true", "1", "yes"):
            include_projection = True
        elif lowered in ("false", "0", "no"):
            include_projection = False
        else:
            raise APIError(
                "ERR_PAGINATION_INVALID",
                "include_projection must be boolean.",
                422,
            )
    result = accrual_summary(
        participant_id=participant_id,
        calendar_year=year,
        include_projection=include_projection,
    )
    return success_response(result)


@bp.route("/participants/<participant_id>/dispositions", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def list_dispositions(participant_id: str):
    limit, offset = parse_pagination()
    classification = request.args.get("classification")
    status_filter = request.args.get("status")
    items = list_dispositions_for_participant(
        participant_id,
        classification=classification,
        status=status_filter,
    )
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [disposition_view(d) for d in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )
