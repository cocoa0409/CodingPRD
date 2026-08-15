"""DealerAgreement endpoints: create/list/get, activate (OCC + cert gate +
inclusive-overlap), terminate, expire."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_DUPLICATE_AGREEMENT_CODE,
    ERR_AGREEMENT_NOT_IN_DRAFT,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_DEALER_NOT_ACTIVE,
    ERR_CERTIFICATION_COMPLIANCE,
    ERR_AGREEMENT_OVERLAP,
    ERR_AGREEMENT_NOT_YET_EXPIRED,
)
from middleware import require_roles
from response import success_object, success_list
from services.cascades import terminate_agreement_cascade, expire_agreement_cascade
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_date,
    parse_pagination,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("agreements", __name__)

REQUIRED_ACTIVE_CERTS = 2


def get_agreement_or_404(agreement_id: str) -> dict:
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_FOUND, "Agreement id does not exist")
    return agreement


def _windows_overlap_inclusive(a_eff: str, a_exp: str, b_eff: str, b_exp: str) -> bool:
    """Inclusive [effective_date, expiry_date] overlap: touching counts."""
    return a_eff <= b_exp and b_eff <= a_exp


@bp.route("/dealer-agreements", methods=["POST"])
@require_roles("OemNetworkAdmin")
def create_agreement(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    agreement_code = require_string(body, "agreement_code")
    effective_date = require_date(body, "effective_date")
    expiry_date = require_date(body, "expiry_date")
    # Priority 3 input format: end strictly after start.
    if parse_date(expiry_date, "expiry_date") <= parse_date(effective_date, "effective_date"):
        raise_err(ERR_INVALID_DATE_RANGE, "expiry_date must be strictly after effective_date")

    # Priority 4 existence: body-referenced dealer.
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        from errors import ERR_DEALER_NOT_FOUND

        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 8: uniqueness of agreement_code.
    if any(a["agreement_code"] == agreement_code for a in db.agreements.values()):
        raise_err(ERR_DUPLICATE_AGREEMENT_CODE, "agreement_code already exists")

    agreement = {
        "dealer_id": dealer_id,
        "agreement_code": agreement_code,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "status": "DRAFT",
    }
    db.stamp_new(agreement)
    db.agreements[agreement["id"]] = agreement
    return success_object(serialize(agreement), 201)


@bp.route("/dealer-agreements", methods=["GET"])
@require_roles("Any")
def list_agreements(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.agreements.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/dealer-agreements/<agreement_id>", methods=["GET"])
@require_roles("Any")
def get_agreement(agreement_id: str, _user_id: str, _role: str):
    agreement = get_agreement_or_404(agreement_id)
    return success_object(serialize(agreement))


@bp.route("/dealer-agreements/<agreement_id>/activate", methods=["POST"])
@require_roles("OemNetworkAdmin")
def activate_agreement(agreement_id: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_dealer_version = require_int(body, "expected_dealer_version")
    supersede_existing = optional_field(body, "supersede_existing", False)
    if not isinstance(supersede_existing, bool):
        raise_err(ERR_INVALID_REQUEST, "supersede_existing must be a boolean")

    # Priority 4: path id.
    agreement = get_agreement_or_404(agreement_id)
    dealer = db.dealers.get(agreement["dealer_id"])
    if dealer is None:
        from errors import ERR_DEALER_NOT_FOUND

        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 6 state + OCC, in the scaffold's precondition order:
    # (1) agreement DRAFT, (2) OCC on Dealer.version, (3) dealer status.
    if agreement["status"] != "DRAFT":
        raise_err(ERR_AGREEMENT_NOT_IN_DRAFT, "Activation requires agreement in DRAFT")
    if expected_dealer_version != dealer["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_dealer_version != current Dealer.version",
        )
    if dealer["status"] not in ("ONBOARDING", "ACTIVE"):
        raise_err(
            ERR_DEALER_NOT_ACTIVE,
            "Activation requires Dealer.status in {ONBOARDING, ACTIVE}",
        )

    # Priority 7 safety gate: >= 2 ACTIVE certifications for the dealer.
    active_certs = sum(
        1
        for c in db.certifications.values()
        if c["dealer_id"] == dealer["id"] and c["status"] == "ACTIVE"
    )
    if active_certs < REQUIRED_ACTIVE_CERTS:
        raise_err(
            ERR_CERTIFICATION_COMPLIANCE,
            "Agreement activation requires >= 2 ACTIVE certifications",
        )

    # Priority 8: inclusive overlap with another ACTIVE agreement.
    overlapping = [
        a
        for a in db.agreements.values()
        if a["id"] != agreement["id"]
        and a["dealer_id"] == dealer["id"]
        and a["status"] == "ACTIVE"
        and _windows_overlap_inclusive(
            agreement["effective_date"], agreement["expiry_date"],
            a["effective_date"], a["expiry_date"],
        )
    ]
    if overlapping and not supersede_existing:
        raise_err(
            ERR_AGREEMENT_OVERLAP,
            "Overlapping ACTIVE agreement exists and supersede_existing is not set",
        )

    # --- commit ---
    agreement["status"] = "ACTIVE"
    db.touch(agreement)
    for other in overlapping:
        # Superseded agreements keep their ACTIVE territory assignments bound.
        other["status"] = "SUPERSEDED"
        db.touch(other)
    if dealer["status"] == "ONBOARDING":
        dealer["status"] = "ACTIVE"
    db.touch(dealer)  # exactly +1 version per activation
    return success_object(serialize(agreement))


@bp.route("/dealer-agreements/<agreement_id>/terminate", methods=["POST"])
@require_roles("OemNetworkAdmin")
def terminate_agreement(agreement_id: str, _user_id: str, _role: str):
    agreement = get_agreement_or_404(agreement_id)
    if agreement["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(
            ERR_AGREEMENT_NOT_ACTIVE,
            "Termination requires agreement in DRAFT or ACTIVE",
        )
    terminate_agreement_cascade(agreement)
    return success_object(serialize(agreement))


@bp.route("/dealer-agreements/<agreement_id>/expire", methods=["POST"])
@require_roles("OemNetworkAdmin")
def expire_agreement(agreement_id: str, _user_id: str, _role: str):
    agreement = get_agreement_or_404(agreement_id)
    # Priority 6 state.
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Expire requires agreement ACTIVE")
    # Priority 9 temporal: current logical date must be past expiry_date.
    if db.clock_date() <= parse_date(agreement["expiry_date"], "expiry_date"):
        raise_err(
            ERR_AGREEMENT_NOT_YET_EXPIRED,
            "Expire requires current logical date > expiry_date",
        )
    expire_agreement_cascade(agreement)
    return success_object(serialize(agreement))
