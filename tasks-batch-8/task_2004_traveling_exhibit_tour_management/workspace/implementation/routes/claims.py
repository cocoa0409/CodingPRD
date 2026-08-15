"""DamageClaim endpoints (PRD §3.7)."""

from flask import Blueprint

import calc
import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import claim_out
from validate import (json_body, req_int, get_tour, get_shipment, get_claim,
                      paginate, apply_filters, sorted_created)

bp = Blueprint("claims", __name__)


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/claims", methods=["POST"])
def create_claim(tour_id, shipment_id):
    require_roles("Registrar", "TourManager")
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    data = json_body()
    report_id = data.get("condition_report_id")
    if not isinstance(report_id, str) or not report_id:
        fail("ERR_INVALID_REQUEST",
             "Missing or invalid required field: condition_report_id")
    claimed = req_int(data, "claimed_amount_cents")
    line_items = data.get("line_items")
    if not isinstance(line_items, list):
        fail("ERR_INVALID_REQUEST", "line_items must be an array")
    for li in line_items:
        if not isinstance(li, dict) \
                or not isinstance(li.get("description"), str) \
                or not isinstance(li.get("amount_cents"), int) \
                or isinstance(li.get("amount_cents"), bool):
            fail("ERR_INVALID_REQUEST",
                 "Each line item needs a description and an amount_cents")
    report = db.reports.get(report_id)
    if report is None or report["shipment_id"] != shipment["id"]:
        fail("ERR_INVALID_REQUEST",
             "condition_report_id does not reference a report on this shipment")
    # Itemization must be non-empty and sum to the claimed total (422).
    if not line_items \
            or sum(li["amount_cents"] for li in line_items) != claimed:
        fail("ERR_CLAIM_AMOUNT_MISMATCH",
             "claimed_amount_cents must equal the sum of line item amounts")
    claim = db.stamp_new({
        "id": db.new_id(),
        "shipment_id": shipment["id"],
        "condition_report_id": report_id,
        "claimed_amount_cents": claimed,
        "line_items": [{"description": li["description"],
                        "amount_cents": li["amount_cents"]}
                       for li in line_items],
        "status": "FILED",
        "assessed_payout_cents": None,
    })
    db.claims[claim["id"]] = claim
    return ok_object(claim_out(claim), status=201)


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/claims", methods=["GET"])
def list_claims(tour_id, shipment_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    items = system.claims_of_shipment(shipment["id"])
    items = apply_filters(items, [("status", "status")])
    return paginate([claim_out(c) for c in sorted_created(items)])


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/claims/<claim_id>/transition",
          methods=["POST"])
def claim_transition(tour_id, shipment_id, claim_id):
    require_roles("TourManager", "Insurer")
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    claim = get_claim(shipment, claim_id)
    data = json_body()
    action = data.get("action")
    if action not in ("REVIEW", "APPROVE", "DENY", "PAY"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)
    # Action-level authorization: REVIEW is the TourManager's; APPROVE, DENY,
    # and PAY belong to the Insurer.
    if action == "REVIEW":
        require_roles("TourManager")
    else:
        require_roles("Insurer")

    if action == "REVIEW":
        if claim["status"] != "FILED":
            fail("ERR_INVALID_STATE", "REVIEW is only permitted from FILED")
        report = db.reports.get(claim["condition_report_id"])
        if report is None or report["status"] not in ("SUBMITTED", "ACCEPTED"):
            fail("ERR_INVALID_STATE",
                 "The evidencing report must be SUBMITTED or ACCEPTED")
        claim["status"] = "UNDER_REVIEW"
        db.touch(claim)
        return ok_object(claim_out(claim))

    if action == "APPROVE":
        if claim["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE",
                 "APPROVE is only permitted from UNDER_REVIEW")
        dest = db.stops.get(shipment["destination_stop_id"])
        certs = [c for c in system.certs_of_tour(tour["id"])
                 if dest is not None and c["tour_stop_id"] == dest["id"]
                 and c["status"] in ("ISSUED", "ACTIVE")]
        if not any(claim["claimed_amount_cents"] <= c["coverage_cents"]
                   for c in certs):
            fail("ERR_CLAIM_EXCEEDS_COVERAGE",
                 "claimed_amount_cents exceeds the covering certificate's "
                 "coverage")
        claim["assessed_payout_cents"] = calc.damage_payout(
            claim["line_items"], claim["claimed_amount_cents"])
        claim["status"] = "APPROVED"
        db.touch(claim)
        return ok_object(claim_out(claim))

    if action == "DENY":
        if claim["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE", "DENY is only permitted from UNDER_REVIEW")
        claim["assessed_payout_cents"] = 0
        claim["status"] = "DENIED"
        db.touch(claim)
        system.maybe_release_damage_hold(shipment)
        return ok_object(claim_out(claim))

    # PAY
    if claim["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "PAY is only permitted from APPROVED")
    claim["status"] = "PAID"
    db.touch(claim)
    system.maybe_release_damage_hold(shipment)
    return ok_object(claim_out(claim))
