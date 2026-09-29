"""RateAgreement endpoints (PRD §3.4).

Drafting mutates nothing on the carrier, so Insurer.version is untouched by a draft.
Activation is the mutation that matters and it is guarded by OCC on Insurer.version.
"""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db, sorted_rows, touch
from errors import api_error
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_insurer, get_rate_agreement, get_storm_event
from validation import (
    json_body,
    pagination,
    paginate,
    query_filter,
    req_date_string,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("rate_agreements", __name__)

READ_ROLES = ("CatastropheDirector", "ShopEstimator", "InsurerAdjuster", "BillingCoordinator")


@bp.post("/hail-ops/rate-agreements")
def create_rate_agreement():
    authenticate(("CatastropheDirector",))
    body = json_body()
    insurer_id = req_string(body, "insurer_id")
    storm_event_id = req_string(body, "storm_event_id")
    effective_from = req_date_string(body, "effective_from")
    matrix_rate_dime_cents = req_int(body, "matrix_rate_dime_cents", minimum=1)
    matrix_rate_nickel_cents = req_int(body, "matrix_rate_nickel_cents", minimum=1)
    matrix_rate_quarter_cents = req_int(body, "matrix_rate_quarter_cents", minimum=1)
    matrix_rate_half_dollar_cents = req_int(body, "matrix_rate_half_dollar_cents", minimum=1)
    labor_rate_cents_per_hour = req_int(body, "labor_rate_cents_per_hour", minimum=1)
    panel_cap_cents = req_int(body, "panel_cap_cents", minimum=1)
    admin_fee_pct = req_number(body, "admin_fee_pct", minimum=0, maximum=1)
    admin_fee_cap_cents = req_int(body, "admin_fee_cap_cents", minimum=0)
    supplement_auto_approve_pct = req_number(
        body, "supplement_auto_approve_pct", minimum=0, maximum=1
    )
    rental_cap_days = req_int(body, "rental_cap_days", minimum=0)
    rental_daily_rate_cents = req_int(body, "rental_daily_rate_cents", minimum=0)

    get_insurer(insurer_id)
    get_storm_event(storm_event_id)

    row = base_row()
    row.update({
        "insurer_id": insurer_id,
        "storm_event_id": storm_event_id,
        "effective_from": effective_from,
        "matrix_rate_dime_cents": matrix_rate_dime_cents,
        "matrix_rate_nickel_cents": matrix_rate_nickel_cents,
        "matrix_rate_quarter_cents": matrix_rate_quarter_cents,
        "matrix_rate_half_dollar_cents": matrix_rate_half_dollar_cents,
        "labor_rate_cents_per_hour": labor_rate_cents_per_hour,
        "panel_cap_cents": panel_cap_cents,
        "admin_fee_pct": admin_fee_pct,
        "admin_fee_cap_cents": admin_fee_cap_cents,
        "supplement_auto_approve_pct": supplement_auto_approve_pct,
        "rental_cap_days": rental_cap_days,
        "rental_daily_rate_cents": rental_daily_rate_cents,
        "status": "DRAFT",
        "activated_at": None,
    })
    db.rate_agreements[row["id"]] = row
    return object_response(serializers.rate_agreement(row), 201)


@bp.get("/hail-ops/rate-agreements/<identifier>")
def read_rate_agreement(identifier):
    authenticate(READ_ROLES)
    agreement = get_rate_agreement(identifier)
    return object_response(serializers.rate_agreement(agreement))


@bp.get("/hail-ops/rate-agreements")
def list_rate_agreements():
    authenticate(READ_ROLES)
    limit, offset = pagination()

    rows = sorted_rows(list(db.rate_agreements.values()))
    insurer_id = query_filter("insurer_id")
    storm_event_id = query_filter("storm_event_id")
    status = query_filter("status")
    if insurer_id is not None:
        rows = [r for r in rows if r["insurer_id"] == insurer_id]
    if storm_event_id is not None:
        rows = [r for r in rows if r["storm_event_id"] == storm_event_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response(
        [serializers.rate_agreement(r) for r in page], limit, offset, len(rows)
    )


@bp.post("/hail-ops/rate-agreements/<identifier>/activate")
def activate_rate_agreement(identifier):
    authenticate(("CatastropheDirector",))
    body = json_body()
    expected_insurer_version = req_int(body, "expected_insurer_version")
    agreement = get_rate_agreement(identifier)

    insurer = db.insurers.get(agreement["insurer_id"])
    current_version = insurer["version"] if insurer is not None else None
    if expected_insurer_version != current_version:
        raise api_error(
            "ERR_STALE_INSURER_VERSION",
            "expected_insurer_version does not match the carrier's current version.",
        )

    if agreement["status"] != "DRAFT":
        raise api_error(
            "ERR_INVALID_LIFECYCLE_STATE", "Only a DRAFT agreement may be activated."
        )

    event = db.storm_events.get(agreement["storm_event_id"])
    if event is None or event["status"] not in ("TARGETED", "ACTIVE"):
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE",
            "Activation requires the parent event to be TARGETED or ACTIVE.",
        )

    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = clock.instant()
    touch(agreement)

    # hop 1: the carrier's previous sheet for this event loses its authority.
    for other in sorted_rows(list(db.rate_agreements.values())):
        if other["id"] == agreement["id"]:
            continue
        if other["insurer_id"] != agreement["insurer_id"]:
            continue
        if other["storm_event_id"] != agreement["storm_event_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)

    # hop 2: the carrier version bump is what makes a replayed activation stale.
    if insurer is not None:
        touch(insurer)

    return object_response(serializers.rate_agreement(agreement))
