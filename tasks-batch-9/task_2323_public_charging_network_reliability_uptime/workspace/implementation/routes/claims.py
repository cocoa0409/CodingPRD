"""Reimbursement claims, withhold tiers and remediation (PRD §2.7, §3.8)."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id
from response import object_response

bp = Blueprint("claims", __name__)

LINE_ITEM_CATEGORIES = ("OANDM", "NETWORK_FEES", "PARTS")
DECISIONS = ("APPROVE", "WITHHOLD", "DENY")
TERMINAL_CLAIM_STATES = ("APPROVED", "DENIED", "SUPERSEDED")


def _snapshot(claim, report):
    effective = calc.effective_uptime_pct(report["uptime_pct"], claim["remediation_credit_pp"])
    claim["effective_uptime_pct"] = effective
    claim["withhold_rate"] = calc.withhold_rate_for(effective)


def _line_items(body):
    raw = body.get("line_items")
    if not isinstance(raw, list):
        raise err("ERR_INVALID_REQUEST", "Field 'line_items' must be an array of objects.")
    if len(raw) == 0:
        raise err("ERR_CLAIM_LINE_ITEMS_EMPTY", "line_items must hold at least one entry.")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "Each line item must be an object.")
        port_id = validation.as_string(entry, "port_id")
        category = validation.as_enum(entry, "category", LINE_ITEM_CATEGORIES)
        amount_cents = validation.as_int(entry, "amount_cents", minimum=0)
        items.append({"port_id": port_id, "category": category,
                      "amount_cents": amount_cents})
    return items


@bp.post("/reimbursement-claims")
@endpoint("NetworkOperator")
def file_claim():
    body = validation.json_body()

    raw_report_id = validation.fk(body, "uptime_report_id")
    report = lookup.uptime_report(raw_report_id) if raw_report_id is not None else None

    raw_items = body.get("line_items")
    if isinstance(raw_items, list):
        for entry in raw_items:
            if isinstance(entry, dict):
                raw_port_id = validation.fk(entry, "port_id")
                if raw_port_id is not None:
                    lookup.port(raw_port_id)

    validation.as_string(body, "uptime_report_id")
    items = _line_items(body)
    expected_version = validation.as_int(body, "expected_uptime_report_version")

    if expected_version != report["version"]:
        raise err("ERR_STALE_PARENT_VERSION",
                  "expected_uptime_report_version does not match the report's version.")

    for item in items:
        port = db.ports.get(item["port_id"])
        if port is None or port["station_id"] != report["station_id"]:
            raise err("ERR_CLAIM_LINE_PORT_MISMATCH",
                      "Every line item port_id must belong to the report's station.")

    row = db.base_record()
    row.update({
        "uptime_report_id": report["id"],
        "line_items": items,
        "requested_amount_cents": sum(item["amount_cents"] for item in items),
        "remediation_credit_pp": Decimal("0.00"),
        "effective_uptime_pct": None,
        "withhold_rate": None,
        "withheld_amount_cents": None,
        "approved_amount_cents": None,
        "state": "PENDING",
        "decided_by_user_id": None,
    })
    db.claims[row["id"]] = row
    db.mark_fresh(row)

    for existing in db.claims_of_report(report["id"]):
        if existing["id"] == row["id"]:
            continue
        if existing["state"] == "PENDING":
            existing["state"] = "SUPERSEDED"
            db.touch(existing)

    report["claim_count"] = report["claim_count"] + 1
    db.touch(report)

    return object_response(serialize.reimbursement_claim(row), 201)


@bp.get("/reimbursement-claims/<claim_id>")
@endpoint()
def get_claim(claim_id):
    return object_response(serialize.reimbursement_claim(lookup.claim(claim_id)))


@bp.post("/reimbursement-claims/<claim_id>/review")
@endpoint("ProgramAdministrator")
def review_claim(claim_id):
    claim = lookup.claim(claim_id)

    if claim["state"] in TERMINAL_CLAIM_STATES:
        raise err("ERR_ALREADY_TERMINAL", "The claim is already in a terminal state.")
    if claim["state"] not in ("PENDING", "WITHHELD"):
        raise err("ERR_INVALID_STATE",
                  "Only a PENDING or WITHHELD claim may be opened for adjudication.")

    report = db.reports.get(claim["uptime_report_id"])
    if report is None or report["state"] != "ACCEPTED":
        raise err("ERR_UPTIME_REPORT_NOT_ACCEPTED",
                  "The claim's uptime report is not ACCEPTED.")

    _snapshot(claim, report)
    claim["state"] = "REVIEW"
    db.touch(claim)
    return object_response(serialize.reimbursement_claim(claim))


@bp.post("/reimbursement-claims/<claim_id>/decision")
@endpoint("ProgramAdministrator")
def decide_claim(claim_id):
    claim = lookup.claim(claim_id)
    body = validation.json_body()
    decision = validation.as_enum(body, "decision", DECISIONS)

    if claim["state"] != "REVIEW":
        raise err("ERR_INVALID_STATE", "Only a claim in REVIEW may be decided.")

    report = db.reports.get(claim["uptime_report_id"])
    if (report is not None and report["finalized_by_user_id"] is not None
            and report["finalized_by_user_id"] == current_user_id()):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The auditor who finalized the report may not decide claims against it.")

    rate = claim["withhold_rate"] if claim["withhold_rate"] is not None else Decimal("0.00")

    if decision == "APPROVE":
        if rate != Decimal("0.00"):
            raise err("ERR_UPTIME_BELOW_APPROVAL_THRESHOLD",
                      "Approval requires a withhold rate of 0.00.")
        claim["withheld_amount_cents"] = 0
        claim["approved_amount_cents"] = claim["requested_amount_cents"]
        claim["state"] = "APPROVED"
    elif decision == "WITHHOLD":
        if not (Decimal("0.00") < rate < Decimal("1.00")):
            raise err("ERR_WITHHOLD_RATE_MISMATCH",
                      "A withhold requires a withhold rate strictly between 0.00 and 1.00.")
        withheld = calc.withheld_amount_cents(claim["line_items"], rate)
        claim["withheld_amount_cents"] = withheld
        claim["approved_amount_cents"] = claim["requested_amount_cents"] - withheld
        claim["state"] = "WITHHELD"
    else:  # DENY
        if rate != Decimal("1.00"):
            raise err("ERR_WITHHOLD_RATE_MISMATCH",
                      "A denial requires a withhold rate of 1.00.")
        claim["withheld_amount_cents"] = claim["requested_amount_cents"]
        claim["approved_amount_cents"] = 0
        claim["state"] = "DENIED"

    claim["decided_by_user_id"] = current_user_id()
    db.touch(claim)
    return object_response(serialize.reimbursement_claim(claim))


@bp.post("/reimbursement-claims/<claim_id>/remediation")
@endpoint("NetworkOperator")
def file_remediation(claim_id):
    claim = lookup.claim(claim_id)
    body = validation.json_body()
    credit = validation.as_number(body, "remediation_credit_pp", places=2)

    if claim["state"] != "WITHHELD":
        raise err("ERR_INVALID_STATE",
                  "Only a WITHHELD claim may receive a remediation credit.")

    claim["remediation_credit_pp"] = credit
    report = db.reports.get(claim["uptime_report_id"])
    if report is not None:
        _snapshot(claim, report)
    claim["state"] = "REVIEW"
    db.touch(claim)
    return object_response(serialize.reimbursement_claim(claim))
