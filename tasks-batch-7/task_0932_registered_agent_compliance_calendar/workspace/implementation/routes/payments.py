"""Client money: capture, allocation and refund (PRD 3.8)."""

import envelope
import listing
import lookup
import serializers
from dispatch import endpoint
from errors import ApiError
from services import filings as filing_service
from services import payments as payment_service
from services import rollups
from store import DB, touch


@endpoint("GET", "/payments/{id}", roles=["PlatformAdmin", "ClientContact"], success_code=200)
def read_payment(context):
    return envelope.object_response(serializers.payment(context.row))


@endpoint("POST", "/payments/{id}/capture", roles=["PlatformAdmin"], success_code=200)
def capture_payment(context):
    payment = context.row
    amount = context.body.integer("capture_amount_cents", required=True, minimum=0)  # rung 13
    target = context.refs.get("target_filing_id")

    # declared gate order (PRD 2.9.1): 16, then 35, then 36
    if payment["status"] != "AUTHORIZED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    if amount > payment["authorized_amount_cents"]:  # rung 35
        raise ApiError("ERR_CAPTURE_EXCEEDS_AUTHORIZATION")
    if target is not None and not payment_service.eligible_target(
        target, payment["client_id"]
    ):  # rung 36
        raise ApiError("ERR_ALLOCATION_TARGET_INVALID")

    payment["status"] = "CAPTURED"
    payment["captured_amount_cents"] = amount
    funded = payment_service.run_waterfall(payment, amount, target)
    touch(payment)

    for filing in funded:
        if (
            filing["filing_kind"] == "REINSTATEMENT"
            and filing["paid_amount_cents"] >= filing["total_fee_cents"]
        ):
            for case in filing_service.cases_in_status(filing, "FEES_ASSESSED"):
                case["status"] = "PAID"
                touch(case)

    client = DB.clients.get(payment["client_id"])
    if client is not None:
        rollups.recompute_client(client)
    return envelope.object_response(serializers.payment(payment))


@endpoint("POST", "/payments/{id}/void", roles=["PlatformAdmin"], success_code=200)
def void_payment(context):
    payment = context.row
    if payment["status"] != "AUTHORIZED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    payment["status"] = "VOIDED"
    touch(payment)
    return envelope.object_response(serializers.payment(payment))


@endpoint(
    "GET",
    "/payments/{id}/allocations",
    roles=["PlatformAdmin", "ClientContact"],
    success_code=200,
)
def list_payment_allocations(context):
    rows = lookup.allocations_of_payment(context.row["id"])
    return listing.respond(rows, serializers.allocation)
