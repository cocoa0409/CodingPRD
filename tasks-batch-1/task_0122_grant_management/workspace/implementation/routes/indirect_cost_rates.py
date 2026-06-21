"""IndirectCostRate endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("indirect_cost_rates", __name__)

RATE_TYPES = {"NEGOTIATED", "DE_MINIMIS"}
BASE_TYPES = {"MTDC", "TDC"}


def _serialize(rate):
    return c.serialize(rate)


@bp.route("/indirect-cost-rates", methods=["POST"])
@require_roles("FinanceOfficer")
def create_rate(user_id, role):
    body = c.get_body()

    # priority 3: existence of the award FK (when provided as a valid-shaped id).
    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        award = db.awards.get(award_id)
        if award is None:
            raise errors.not_found("Award not found.")

        # priority 5: OCC on Award.version (PRD §2.6).
        expected = body.get("expected_award_version")
        if expected is None:
            raise errors.invalid_request("expected_award_version is required.")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_award_version must be an integer.")
        if expected != award["version"]:
            raise errors.stale_version()

        # priority 14: field validity / contextual requireds.
        rate_type = c.require_enum(body, "rate_type", RATE_TYPES)
        base_type = c.optional_enum(body, "base_type", BASE_TYPES, "MTDC")
        negotiated_rate = body.get("negotiated_rate")
        if rate_type == "NEGOTIATED":
            if negotiated_rate is None:
                raise errors.invalid_request("negotiated_rate is required when rate_type is NEGOTIATED.")
            if isinstance(negotiated_rate, bool) or not isinstance(negotiated_rate, (int, float)):
                raise errors.invalid_request("negotiated_rate must be a number.")
            if not (0 < negotiated_rate <= 1):
                raise errors.invalid_request("negotiated_rate must be in (0, 1].")
        else:
            # DE_MINIMIS: negotiated_rate is ignored even if present (PRD §3.3).
            negotiated_rate = None

        # Supersede any prior ACTIVE rate for this award (PRD §3.3).
        for existing in db.indirect_cost_rates.values():
            if existing["award_id"] == award_id and existing["status"] == "ACTIVE":
                existing["status"] = "SUPERSEDED"
                db.touch(existing)

        record = {
            "award_id": award_id,
            "rate_type": rate_type,
            "negotiated_rate": negotiated_rate,
            "base_type": base_type,
            "status": "ACTIVE",
        }
        db.stamp_create(record)
        db.indirect_cost_rates[record["id"]] = record

        # Mutating the award advances its version (PRD §2.6, §3.3).
        db.touch(award)

        return success(_serialize(record), status=201)


@bp.route("/indirect-cost-rates", methods=["GET"])
@require_roles("FinanceOfficer", "AgencyOfficer", "Auditor")
def list_rates(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.indirect_cost_rates.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/indirect-cost-rates/<rate_id>", methods=["GET"])
@require_roles("FinanceOfficer", "AgencyOfficer", "Auditor")
def get_rate(rate_id, user_id, role):
    with db.LOCK:
        rate = db.indirect_cost_rates.get(rate_id)
        if rate is None:
            raise errors.not_found("Indirect cost rate not found.")
        return success(_serialize(rate), status=200)


def active_rate_for_award(award_id):
    """Return the award's single ACTIVE IndirectCostRate, or None. Caller holds
    db.LOCK."""
    for rate in db.indirect_cost_rates.values():
        if rate["award_id"] == award_id and rate["status"] == "ACTIVE":
            return rate
    return None
