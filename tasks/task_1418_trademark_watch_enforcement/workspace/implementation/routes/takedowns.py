"""TakedownFiling endpoints (PRD 3.7)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_APPEAL_CAP_REACHED,
    ERR_BUDGET_EXCEEDED,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_takedown_filing, referral_threshold_cascade, client_budget_spent,
)
from util import get_payload, reject_unknown_fields, require_enum, touch
from routes.common import do_list

bp = Blueprint("takedown_filings", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
OUTCOMES = ("REMOVED", "REJECTED", "REINSTATED")
# Filing requires the alert to be past intake and not terminal (PRD 3.7).
FILABLE_ALERT_STATES = ("TRIAGED", "UNDER_ASSESSMENT", "MONITORING", "ESCALATED")
APPEAL_CAP = 2


def _get_filing(filing_id):
    filing = db.takedown_filings.get(filing_id)
    if filing is None:
        raise_error(ERR_NOT_FOUND, "TakedownFiling not found")
    return filing


@bp.route("/brand/takedown-filings", methods=["GET"])
def list_filings():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.takedown_filings.values(), ser_takedown_filing,
                   [("watch_alert_id", "watch_alert_id", None),
                    ("status", "status", None),
                    ("basis", "basis", None)],
                   user_id, role, "takedown_filing")


@bp.route("/brand/takedown-filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    user_id, role = require_roles(*READ_ROLES)
    filing = _get_filing(filing_id)
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("takedown_filing", filing))
    return success(ser_takedown_filing(filing), 200)


@bp.route("/brand/takedown-filings/<filing_id>/file", methods=["POST"])
def file_filing(filing_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, set())
    filing = _get_filing(filing_id)
    if filing["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "file is declared only from DRAFT")
    alert = db.watch_alerts.get(filing["watch_alert_id"])
    if alert["status"] not in FILABLE_ALERT_STATES:
        raise_error(ERR_INVALID_STATE,
                    "The alert must be TRIAGED / UNDER_ASSESSMENT / MONITORING / ESCALATED")
    record = db.trademark_records.get(alert["trademark_record_id"])
    if record["status"] == "CANCELLED":
        raise_error(ERR_INVALID_STATE, "The alert's record is CANCELLED")
    # Fiscal: the client's remaining budget must cover the platform fee.
    client = db.clients[record["client_id"]]
    if client["enforcement_budget_cents"] - client_budget_spent(client["id"]) < filing["fee_cents"]:
        raise_error(ERR_BUDGET_EXCEEDED, "budget_remaining_cents does not cover the filing fee")
    filing["status"] = "FILED"
    touch(filing)
    return success(ser_takedown_filing(filing), 200)


@bp.route("/brand/takedown-filings/<filing_id>/platform-response", methods=["POST"])
def platform_response(filing_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"outcome"})
    outcome = require_enum(body, "outcome", OUTCOMES)
    filing = _get_filing(filing_id)
    if outcome == "REMOVED":
        if filing["status"] not in ("FILED", "APPEALED"):
            raise_error(ERR_INVALID_STATE,
                        "REMOVED is declared only from FILED / APPEALED")
        filing["status"] = "REMOVED"
        touch(filing)
        if filing["basis"] == "COUNTERFEIT":
            # confirmed_counterfeit_count is derived; the threshold cascade may
            # auto-create a DRAFT LAW_ENFORCEMENT referral exactly once.
            alert = db.watch_alerts.get(filing["watch_alert_id"])
            referral_threshold_cascade(alert)
    elif outcome == "REJECTED":
        if filing["status"] not in ("FILED", "APPEALED"):
            raise_error(ERR_INVALID_STATE,
                        "REJECTED is declared only from FILED / APPEALED")
        filing["status"] = "REJECTED"
        touch(filing)
    else:  # REINSTATED
        if filing["status"] != "REMOVED":
            raise_error(ERR_INVALID_STATE, "REINSTATED is declared only from REMOVED")
        filing["status"] = "REINSTATED"
        touch(filing)
        # For COUNTERFEIT filings the derived confirmed count drops by one
        # (floor 0) automatically on the next read.
    return success(ser_takedown_filing(filing), 200)


@bp.route("/brand/takedown-filings/<filing_id>/appeal", methods=["POST"])
def appeal_filing(filing_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, set())
    filing = _get_filing(filing_id)
    if filing["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE, "appeal is declared only from REJECTED")
    if filing["appeal_count"] >= APPEAL_CAP:
        raise_error(ERR_APPEAL_CAP_REACHED, "appeal cap of 2 reached")
    filing["appeal_count"] += 1
    filing["status"] = "APPEALED"
    touch(filing)
    return success(ser_takedown_filing(filing), 200)
