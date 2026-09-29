"""Supplement endpoints (PRD §3.8).

Two fiscal gates are evaluated at filing and the cumulative cap is checked BEFORE
auto-approval. Auto-approval is evaluated only on a round-one filing, never again.
"""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db, sorted_rows, touch
from errors import api_error, bad_request
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_supplement, get_vehicle
from services import calculations
from services import posture as posture_service
from services.constants import SUPPLEMENT_MAX_ROUNDS, SUPPLEMENT_REASON_CODES
from validation import (
    json_body,
    opt_int,
    opt_string,
    pagination,
    paginate,
    query_filter,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("supplements", __name__)

READ_ROLES = ("CatastropheDirector", "ShopEstimator", "InsurerAdjuster", "BillingCoordinator")

FILING_REPAIR_STATES = ("TRIAGED", "IN_REPAIR", "QC_PENDING", "QC_FAILED", "READY")


@bp.post("/hail-ops/supplements")
def create_supplement():
    authenticate(("ShopEstimator",))
    body = json_body()
    vehicle_id = req_string(body, "vehicle_id")
    reason_code = req_enum(body, "reason_code", SUPPLEMENT_REASON_CODES)
    requested_amount_cents = req_int(body, "requested_amount_cents", minimum=1)
    expected_vehicle_version = req_int(body, "expected_vehicle_version")
    supersedes_supplement_id = opt_string(body, "supersedes_supplement_id")

    vehicle = get_vehicle(vehicle_id)
    predecessor = (
        get_supplement(supersedes_supplement_id)
        if supersedes_supplement_id is not None
        else None
    )

    if expected_vehicle_version != vehicle["version"]:
        raise api_error(
            "ERR_STALE_VEHICLE_VERSION",
            "expected_vehicle_version does not match the vehicle's current version.",
        )
    if vehicle["repair_status"] not in FILING_REPAIR_STATES:
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "This vehicle has no supplement surface in its current repair state.",
        )
    if predecessor is not None and predecessor["status"] not in ("DENIED", "WITHDRAWN"):
        raise api_error(
            "ERR_INVALID_SUPPLEMENT_STATE",
            "A supplement may only supersede a DENIED or WITHDRAWN filing.",
        )
    agreement = db.rate_agreements.get(vehicle.get("pinned_rate_agreement_id"))
    if agreement is None:
        raise api_error(
            "ERR_NO_ACTIVE_RATE_AGREEMENT",
            "A supplement needs the vehicle's pinned rate agreement to price against.",
        )
    if calculations.supplement_cap_exceeded(vehicle, requested_amount_cents):
        raise api_error(
            "ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED",
            "The filing would push approved supplements past the cumulative cap.",
        )

    row = base_row()
    row.update({
        "vehicle_id": vehicle_id,
        "rate_agreement_id": agreement["id"],
        "supersedes_supplement_id": supersedes_supplement_id,
        "reason_code": reason_code,
        "requested_amount_cents": requested_amount_cents,
        "counter_amount_cents": None,
        "approved_amount_cents": 0,
        "round_index": 1,
        "status": "UNDER_REVIEW",
        "decided_at": None,
    })

    threshold = calculations.supplement_auto_approve_threshold_cents(vehicle, agreement)
    if requested_amount_cents <= threshold:
        row["status"] = "AUTO_APPROVED"
        row["approved_amount_cents"] = requested_amount_cents
        row["decided_at"] = clock.instant()

    db.supplements[row["id"]] = row
    if row["status"] == "AUTO_APPROVED":
        calculations.recompute_net_billable(vehicle)
    touch(vehicle)
    posture_service.recompute_for_vehicle(vehicle)
    return object_response(serializers.supplement(row), 201)


@bp.get("/hail-ops/supplements/<identifier>")
def read_supplement(identifier):
    authenticate(READ_ROLES)
    supplement = get_supplement(identifier)
    return object_response(serializers.supplement(supplement))


@bp.get("/hail-ops/supplements")
def list_supplements():
    authenticate(READ_ROLES)
    limit, offset = pagination()

    rows = sorted_rows(list(db.supplements.values()))
    vehicle_id = query_filter("vehicle_id")
    rate_agreement_id = query_filter("rate_agreement_id")
    supersedes_supplement_id = query_filter("supersedes_supplement_id")
    status = query_filter("status")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if rate_agreement_id is not None:
        rows = [r for r in rows if r["rate_agreement_id"] == rate_agreement_id]
    if supersedes_supplement_id is not None:
        rows = [
            r for r in rows if r["supersedes_supplement_id"] == supersedes_supplement_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response([serializers.supplement(r) for r in page], limit, offset, len(rows))


@bp.post("/hail-ops/supplements/<identifier>/review")
def review_supplement(identifier):
    principal = authenticate(("InsurerAdjuster",))
    body = json_body()
    decision = req_enum(body, "decision", ("APPROVE", "COUNTER", "DENY"))
    counter_amount_cents = opt_int(body, "counter_amount_cents")
    supplement = get_supplement(identifier)
    vehicle = db.vehicles.get(supplement["vehicle_id"])

    if vehicle is None or principal.user_id != vehicle["insurer_id"]:
        raise api_error(
            "ERR_IDENTITY_MISMATCH",
            "Only the vehicle's own carrier may review this supplement.",
        )
    if supplement["status"] != "UNDER_REVIEW":
        raise api_error(
            "ERR_INVALID_SUPPLEMENT_STATE",
            "Only an UNDER_REVIEW supplement may be reviewed.",
        )

    if decision == "APPROVE":
        supplement["status"] = "APPROVED"
        supplement["approved_amount_cents"] = supplement["requested_amount_cents"]
        supplement["decided_at"] = clock.instant()
        touch(supplement)
        calculations.recompute_net_billable(vehicle)
    elif decision == "DENY":
        supplement["status"] = "DENIED"
        supplement["approved_amount_cents"] = 0
        supplement["decided_at"] = clock.instant()
        touch(supplement)
    else:
        if counter_amount_cents is None:
            raise bad_request("A COUNTER decision requires counter_amount_cents.")
        if not (0 < counter_amount_cents < supplement["requested_amount_cents"]):
            raise bad_request(
                "counter_amount_cents must be greater than 0 and less than the claim."
            )
        if supplement["round_index"] >= SUPPLEMENT_MAX_ROUNDS:
            raise api_error(
                "ERR_SUPPLEMENT_ROUND_LIMIT", "The negotiation ceiling has been reached."
            )
        supplement["status"] = "COUNTERED"
        supplement["counter_amount_cents"] = counter_amount_cents
        supplement["decided_at"] = clock.instant()
        touch(supplement)

    posture_service.recompute_for_vehicle(vehicle)
    return object_response(serializers.supplement(supplement))


@bp.post("/hail-ops/supplements/<identifier>/revise")
def revise_supplement(identifier):
    authenticate(("ShopEstimator",))
    body = json_body()
    action = req_enum(body, "action", ("REVISE", "WITHDRAW"))
    revised_amount_cents = opt_int(body, "revised_amount_cents")
    supplement = get_supplement(identifier)
    vehicle = db.vehicles.get(supplement["vehicle_id"])

    if action == "WITHDRAW":
        if supplement["status"] not in ("UNDER_REVIEW", "COUNTERED"):
            raise api_error(
                "ERR_INVALID_SUPPLEMENT_STATE",
                "Only an UNDER_REVIEW or COUNTERED supplement may be withdrawn.",
            )
        supplement["status"] = "WITHDRAWN"
        supplement["approved_amount_cents"] = 0
        touch(supplement)
        return object_response(serializers.supplement(supplement))

    if supplement["status"] != "COUNTERED":
        raise api_error(
            "ERR_INVALID_SUPPLEMENT_STATE", "Only a COUNTERED supplement may be revised."
        )
    if supplement["round_index"] >= SUPPLEMENT_MAX_ROUNDS:
        raise api_error(
            "ERR_SUPPLEMENT_ROUND_LIMIT", "Three rounds is the negotiation ceiling."
        )
    if revised_amount_cents is None:
        raise bad_request("A REVISE action requires revised_amount_cents.")
    counter = supplement["counter_amount_cents"]
    if counter is not None and revised_amount_cents < counter:
        raise bad_request("revised_amount_cents must be no less than counter_amount_cents.")
    if revised_amount_cents > supplement["requested_amount_cents"]:
        raise bad_request("revised_amount_cents must be no greater than the current claim.")
    if vehicle is not None and calculations.supplement_cap_exceeded(
        vehicle, revised_amount_cents
    ):
        raise api_error(
            "ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED",
            "The revised amount would push approved supplements past the cumulative cap.",
        )

    # Auto-approval is deliberately NOT re-evaluated on later rounds.
    supplement["requested_amount_cents"] = revised_amount_cents
    supplement["round_index"] = supplement["round_index"] + 1
    supplement["status"] = "UNDER_REVIEW"
    touch(supplement)
    return object_response(serializers.supplement(supplement))
