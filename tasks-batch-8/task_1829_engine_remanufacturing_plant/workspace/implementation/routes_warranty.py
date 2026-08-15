"""Warranty claims: filing, teardown, and adjudication (PRD 3.11)."""

from flask import Blueprint, request

import calcs
import clock as clockmod
import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import (
    ERR_ADJUDICATOR_IS_TEARDOWN_TECH,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_STATE,
    ERR_NO_ELIGIBLE_ENGINE,
    ERR_WARRANTY_EXPIRED,
    raise_error,
)
from services import create_deposit, get_or_404, select_sealed_engine
from store import db, stamp_new, sorted_rows, touch
from validate import (
    check_allowed_fields,
    filter_enum,
    get_body,
    pagination,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("warranty", __name__)

CLAIM_STATUSES = {
    "OPEN",
    "TEARDOWN_COMPLETE",
    "APPROVED_CREDIT",
    "APPROVED_REPLACEMENT",
    "DENIED",
}
OUTCOMES = {"APPROVED_CREDIT", "APPROVED_REPLACEMENT", "DENIED"}


@bp.route("/warranty-claims", methods=["POST"])
def create_warranty_claim():
    caller = authorized(["Distributor"])
    body = get_body()
    check_allowed_fields(body, ["reman_engine_id", "distributor_id", "failure_description"])
    reman_engine_id = req_str(body, "reman_engine_id")
    distributor_id = req_str(body, "distributor_id")
    failure_description = req_str(body, "failure_description")

    # Existence of body-referenced ids (priority 4), canonical order.
    engine = get_or_404("engines", reman_engine_id)
    get_or_404("distributors", distributor_id)

    # Ownership (priority 5): a distributor files claims only for itself.
    if distributor_id != caller.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "a distributor may file warranty claims only for itself",
        )
    # The engine must be SOLD to the filing distributor: an engine in any
    # other status fails the state check; one sold to someone else fails the
    # ownership check.
    if engine["status"] == "SOLD" and engine["distributor_id"] != caller.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "the engine was sold to a different distributor",
        )
    if engine["status"] != "SOLD":
        raise_error(
            ERR_INVALID_STATE,
            "a warranty claim requires the engine to be SOLD",
        )

    now = clockmod.now()
    # Warranty window: filing is permitted only while the whole-day age of the
    # sale is strictly less than 360 days (12 months x 30 days).
    days = clockmod.age_in_days(engine["sold_at"], now)
    if days >= calcs.WARRANTY_DAYS:
        raise_error(ERR_WARRANTY_EXPIRED, "the 360-day warranty window has closed")

    record = {
        "reman_engine_id": engine["id"],
        "distributor_id": distributor_id,
        "failure_description": failure_description,
        "status": "OPEN",
        "filed_at": now,
        "months_in_service": days // calcs.DAYS_PER_MONTH,
        "teardown_findings": None,
        "teardown_by": None,
        "settled_credit_cents": None,
    }
    stamp_new(record)
    db.warranty_claims[record["id"]] = record
    return envelope.created(serializers.warranty_claim(record))


@bp.route("/warranty-claims", methods=["GET"])
def list_warranty_claims():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_distributor = request.args.get("distributor_id")
    f_engine = request.args.get("reman_engine_id")
    f_status = filter_enum("status", CLAIM_STATUSES)
    rows = list(db.warranty_claims.values())
    if f_distributor is not None:
        rows = [r for r in rows if r["distributor_id"] == f_distributor]
    if f_engine is not None:
        rows = [r for r in rows if r["reman_engine_id"] == f_engine]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.warranty_claim(r) for r in page], limit, offset, total)


@bp.route("/warranty-claims/<rid>", methods=["GET"])
def get_warranty_claim(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("warranty_claims", rid)
    return envelope.ok(serializers.warranty_claim(record))


@bp.route("/warranty-claims/<rid>/teardown", methods=["POST"])
def teardown_warranty_claim(rid):
    caller = authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["teardown_findings"])
    teardown_findings = req_str(body, "teardown_findings")
    claim = get_or_404("warranty_claims", rid)
    if claim["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "only an OPEN claim can be torn down")

    claim["teardown_findings"] = teardown_findings
    claim["teardown_by"] = caller.user_id
    claim["status"] = "TEARDOWN_COMPLETE"
    touch(claim)

    # CROSS-ENTITY: the referenced engine leaves sellable inventory.
    engine = db.engines[claim["reman_engine_id"]]
    if engine["status"] == "SOLD":
        engine["status"] = "RETURNED"
        touch(engine)

    return envelope.ok(serializers.warranty_claim(claim))


@bp.route("/warranty-claims/<rid>/adjudicate", methods=["POST"])
def adjudicate_warranty_claim(rid):
    caller = authorized(["WarrantyAdjuster"])
    body = get_body()
    check_allowed_fields(body, ["outcome", "teardown_fee_cents"])
    outcome = req_enum(body, "outcome", OUTCOMES)
    teardown_fee_cents = req_int(body, "teardown_fee_cents")
    claim = get_or_404("warranty_claims", rid)

    if claim["status"] != "TEARDOWN_COMPLETE":
        raise_error(
            ERR_INVALID_STATE, "only a TEARDOWN_COMPLETE claim can be adjudicated"
        )

    # Segregation of duties: the adjudicator must differ from the teardown
    # technician.
    if claim["teardown_by"] == caller.user_id:
        raise_error(
            ERR_ADJUDICATOR_IS_TEARDOWN_TECH,
            "the adjudicator must differ from the teardown technician",
        )

    engine = db.engines[claim["reman_engine_id"]]
    spec = db.build_specs[engine["build_spec_id"]]
    distributor = db.distributors[claim["distributor_id"]]
    now = clockmod.now()

    if outcome == "APPROVED_CREDIT":
        # Credit variant, pinned evaluation order (calcs.warranty_credit_cents).
        claim["settled_credit_cents"] = calcs.warranty_credit_cents(
            engine["sale_price_cents"], claim["months_in_service"], teardown_fee_cents
        )
        distributor["credit_balance_cents"] += claim["settled_credit_cents"]
        touch(distributor)
    elif outcome == "APPROVED_REPLACEMENT":
        # Replacement variant: zero cash credit; the same server-side selector
        # as a sale allocates a SEALED engine of the failed engine's spec.
        replacement = select_sealed_engine(engine["build_spec_id"])
        if replacement is None:
            raise_error(
                ERR_NO_ELIGIBLE_ENGINE,
                "no SEALED engine of the claim's build spec is available",
            )
        claim["settled_credit_cents"] = 0
        # REPLACEMENT CHAIN: the selected engine sells to the claimant at
        # sale_price_cents = 0 (warranty replacements bypass sale pricing);
        # a new HELD deposit is created and the claimant's ledger moves.
        replacement["status"] = "SOLD"
        replacement["distributor_id"] = claim["distributor_id"]
        replacement["sold_at"] = now
        replacement["sale_price_cents"] = 0
        touch(replacement)
        create_deposit(claim["distributor_id"], replacement["id"], spec, now)
        touch(distributor)
    else:  # DENIED
        claim["settled_credit_cents"] = 0

    # The torn-down unit is scrapped under every outcome; it never returns
    # to stock.
    if engine["status"] == "RETURNED":
        engine["status"] = "SCRAPPED"
        touch(engine)

    claim["status"] = outcome
    touch(claim)
    return envelope.ok(serializers.warranty_claim(claim))
