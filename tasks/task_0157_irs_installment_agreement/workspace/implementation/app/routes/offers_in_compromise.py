"""Offer in Compromise endpoints (§3.8)."""
from __future__ import annotations

import math

from flask import Blueprint, request

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success, success_list
from app.errors import (
    ERR_DEPOSIT_INSUFFICIENT,
    ERR_INVALID_STATE,
    ERR_LIABILITY_LOCKED,
    ERR_LIABILITY_NOT_OWNED,
    ERR_NOT_FOUND,
    ERR_OIC_BELOW_RCP,
    ERR_OVERLAPPING_TOLLING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
    raise_error,
)
from app.services.calculations import rcp_cents
from app.services.common import bump_version, check_version, init_common_fields
from app.services.csed import close_events_of_kind, open_event, _open_event_of_kind
from app.services.liabilities import set_status
from app.services.liens import release_check
from app.services.payment_allocation import allocate, settle_to_paid_if_zero
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import now_iso
from app.util import (
    get_json_body,
    get_pagination,
    optional_version,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_list,
    require_str,
)


bp = Blueprint("offers", __name__, url_prefix="/collections/offers-in-compromise")


OIC_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN")


def _serialize(o: dict) -> dict:
    return {
        "id": o["id"],
        "taxpayer_id": o["taxpayer_id"],
        "liability_ids": list(o["liability_ids"]),
        "offer_amount_cents": o["offer_amount_cents"],
        "schedule_months": o["schedule_months"],
        "deposit_paid_cents": o.get("deposit_paid_cents", 0),
        "rcp_cents": o["rcp_cents"],
        "status": o["status"],
        "decision_officer_id": o.get("decision_officer_id"),
        "claiming_officer_id": o.get("claiming_officer_id"),
        "submitted_at": o.get("submitted_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("Taxpayer", "IRSOfficer")
def create_oic(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "liability_ids", "offer_amount_cents", "schedule_months"])
    taxpayer_id = require_str(body, "taxpayer_id")
    liab_ids = require_list(body, "liability_ids", min_len=1)
    if any(not isinstance(x, str) for x in liab_ids):
        raise_error(ERR_VALIDATION, "liability_ids must be an array of strings.")
    offer_amount = require_int(body, "offer_amount_cents", minimum=1)
    schedule_months = require_int(body, "schedule_months", minimum=1, maximum=24)

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")
        enforce_taxpayer_ownership(identity, taxpayer_id)

        liabs = []
        for lid in liab_ids:
            l = STORE.tax_liabilities.get(lid)
            if l is None or l["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_LIABILITY_NOT_OWNED, f"Liability {lid!r} not owned by taxpayer.")
            liabs.append(l)

        for l in liabs:
            if l["status"] not in ("OPEN", "IN_AGREEMENT", "CNC"):
                raise_error(ERR_INVALID_STATE,
                            f"Liability {l['id']!r} in status {l['status']} cannot be part of an OIC.")

        oic = {
            "id": new_id(),
            "taxpayer_id": taxpayer_id,
            "liability_ids": list(liab_ids),
            "offer_amount_cents": offer_amount,
            "schedule_months": schedule_months,
            "deposit_paid_cents": 0,
            "rcp_cents": rcp_cents(tp["monthly_disposable_income_cents"], schedule_months),
            "status": "DRAFT",
            "decision_officer_id": None,
            "claiming_officer_id": None,
            "submitted_at": None,
        }
        init_common_fields(oic)
        STORE.offers[oic["id"]] = oic

    return success(_serialize(oic), status=201)


@bp.route("/<oic_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_oic(identity, oic_id):
    with STORE.lock:
        oic = STORE.offers.get(oic_id)
        if oic is None:
            raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
        enforce_taxpayer_ownership(identity, oic["taxpayer_id"])
        return success(_serialize(oic))


@bp.route("", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer")
def list_oics(identity):
    limit, offset = get_pagination()
    taxpayer_filter = request.args.get("taxpayer_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in OIC_STATUSES:
        raise_error(ERR_VALIDATION, "Invalid status filter.")
    with STORE.lock:
        items = list(STORE.offers.values())
        if taxpayer_filter:
            items = [o for o in items if o["taxpayer_id"] == taxpayer_filter]
        if status_filter:
            items = [o for o in items if o["status"] == status_filter]
        items.sort(key=lambda o: o["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([_serialize(o) for o in page], limit, offset, total)


@bp.route("/<oic_id>/submit", methods=["POST"])
@require_roles("Taxpayer")
def submit_oic(identity, oic_id):
    body = get_json_body()
    with STORE.lock:
        oic = STORE.offers.get(oic_id)
        if oic is None:
            raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
        enforce_taxpayer_ownership(identity, oic["taxpayer_id"])
        if oic["status"] != "DRAFT":
            raise_error(ERR_INVALID_STATE, f"OIC is in status {oic['status']}, cannot submit.")
        check_version(oic, optional_version(body))

        # Check covered liabilities still eligible
        for lid in oic["liability_ids"]:
            liab = STORE.tax_liabilities[lid]
            if liab["status"] not in ("OPEN", "IN_AGREEMENT", "CNC"):
                raise_error(ERR_INVALID_STATE, f"Liability {lid!r} not in submittable state.")

        # Cross-workflow lock: liability in ACTIVE IA + OIC overlap (priority 12)
        for ia in STORE.installment_agreements.values():
            if ia["status"] == "ACTIVE" and any(lid in oic["liability_ids"] for lid in ia["liability_ids"]):
                # In real IRS this is OK (OIC supersedes IA on accept), but per scaffold lock check:
                # The check is for IA activation vs OIC UNDER_REVIEW. Since submitting OIC does NOT
                # immediately lock, we DON'T raise here. The lock is enforced at IA activation against
                # UNDER_REVIEW OICs.
                pass

        # Tolling-overlap pre-check (priority 11): cannot submit a second
        # OIC while an OIC_PENDING tolling is still open on a covered
        # liability.
        for lid in oic["liability_ids"]:
            if _open_event_of_kind(lid, "OIC_PENDING") is not None:
                raise_error(
                    ERR_OVERLAPPING_TOLLING,
                    f"An OIC_PENDING tolling event is already open on liability {lid!r}.",
                )

        # Deposit sufficiency check (priority 17)
        deposit_required = math.ceil(oic["offer_amount_cents"] * 0.20)
        deposit_paid = oic.get("deposit_paid_cents", 0)
        if deposit_paid < deposit_required:
            raise_error(ERR_DEPOSIT_INSUFFICIENT,
                        f"OIC deposit {deposit_paid} cents is less than required {deposit_required}.")

        # Recompute rcp
        tp = STORE.taxpayers[oic["taxpayer_id"]]
        oic["rcp_cents"] = rcp_cents(tp["monthly_disposable_income_cents"], oic["schedule_months"])

        oic["status"] = "SUBMITTED"
        oic["submitted_at"] = now_iso()
        bump_version(oic)

        # Open OIC_PENDING tolling event on each covered liability.
        # PRD §3.3: two simultaneously-open events of the same event_kind
        # on the same liability are forbidden — must surface
        # ERR_OVERLAPPING_TOLLING. Do not suppress.
        for lid in oic["liability_ids"]:
            open_event(lid, "OIC_PENDING", source_ref=oic_id)

        refresh_taxpayer_aggregates(oic["taxpayer_id"])
        return success(_serialize(oic))


@bp.route("/<oic_id>/take-up", methods=["POST"])
@require_roles("OICOfficer")
def take_up_oic(identity, oic_id):
    body = get_json_body()
    with STORE.lock:
        oic = STORE.offers.get(oic_id)
        if oic is None:
            raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
        if oic["status"] != "SUBMITTED":
            raise_error(ERR_INVALID_STATE, f"OIC is in status {oic['status']}, cannot take up.")
        check_version(oic, optional_version(body))

        oic["status"] = "UNDER_REVIEW"
        oic["claiming_officer_id"] = identity.user_id
        bump_version(oic)
        return success(_serialize(oic))


@bp.route("/<oic_id>/decide", methods=["POST"])
@require_roles("OICOfficer")
def decide_oic(identity, oic_id):
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", ("ACCEPT", "REJECT"))

    with STORE.lock:
        oic = STORE.offers.get(oic_id)
        if oic is None:
            raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
        if oic["status"] != "UNDER_REVIEW":
            raise_error(ERR_INVALID_STATE, f"OIC is in status {oic['status']}, cannot decide.")
        check_version(oic, optional_version(body))

        # Segregation of duties (priority 8)
        if oic.get("claiming_officer_id") and identity.user_id == oic["claiming_officer_id"]:
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "OICOfficer who took up the case cannot decide it.")

        liabs = [STORE.tax_liabilities[lid] for lid in oic["liability_ids"]]

        if decision == "ACCEPT":
            # Check if any covered liability has already been PAID via concurrent process
            for l in liabs:
                if l["status"] == "PAID":
                    raise_error(ERR_INVALID_STATE,
                                f"Liability {l['id']!r} is already PAID; cannot accept OIC.")

            # RCP check (priority 18)
            if oic["offer_amount_cents"] < oic["rcp_cents"]:
                raise_error(ERR_OIC_BELOW_RCP,
                            f"Offer {oic['offer_amount_cents']} < RCP {oic['rcp_cents']}.")

            oic["status"] = "ACCEPTED"
            oic["decision_officer_id"] = identity.user_id
            bump_version(oic)

            # Transition each covered liability to IN_COMPROMISE
            for l in liabs:
                if l["status"] != "PAID":
                    set_status(l, "IN_COMPROMISE")
                close_events_of_kind(l["id"], "OIC_PENDING")

            # Cascade: terminate any ACTIVE IA covering any of the OIC liabilities
            for ia in list(STORE.installment_agreements.values()):
                if ia["status"] != "ACTIVE":
                    continue
                if not any(lid in oic["liability_ids"] for lid in ia["liability_ids"]):
                    continue
                ia["status"] = "TERMINATED"
                bump_version(ia)
                for lid in ia["liability_ids"]:
                    liab = STORE.tax_liabilities[lid]
                    if lid in oic["liability_ids"]:
                        set_status(liab, "IN_COMPROMISE")
                    else:
                        # Revert to OPEN unless paid
                        if liab["current_balance_cents"] == 0:
                            set_status(liab, "PAID")
                        else:
                            set_status(liab, "OPEN")

            # Lien release cascade — only if all covered liability_ids on a lien are in IN_COMPROMISE or PAID
            for lien in STORE.liens.values():
                if lien["status"] != "FILED":
                    continue
                covered = [STORE.tax_liabilities[lid] for lid in lien["liability_ids"]]
                if all(c["status"] in ("IN_COMPROMISE", "PAID") for c in covered):
                    lien["status"] = "RELEASED"
                    lien["released_at"] = now_iso()
                    lien["release_reason"] = "OIC_ACCEPTED"
                    bump_version(lien)

        else:  # REJECT
            oic["status"] = "REJECTED"
            oic["decision_officer_id"] = identity.user_id
            bump_version(oic)

            for l in liabs:
                close_events_of_kind(l["id"], "OIC_PENDING")

            _allocate_deposit_lump_sum(oic)

        refresh_taxpayer_aggregates(oic["taxpayer_id"])
        return success(_serialize(oic))


@bp.route("/<oic_id>/withdraw", methods=["POST"])
@require_roles("Taxpayer")
def withdraw_oic(identity, oic_id):
    body = get_json_body()
    with STORE.lock:
        oic = STORE.offers.get(oic_id)
        if oic is None:
            raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
        enforce_taxpayer_ownership(identity, oic["taxpayer_id"])
        if oic["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            raise_error(ERR_INVALID_STATE, f"OIC is in status {oic['status']}, cannot withdraw.")
        check_version(oic, optional_version(body))

        oic["status"] = "WITHDRAWN"
        bump_version(oic)

        for lid in oic["liability_ids"]:
            close_events_of_kind(lid, "OIC_PENDING")

        _allocate_deposit_lump_sum(oic)
        refresh_taxpayer_aggregates(oic["taxpayer_id"])
        return success(_serialize(oic))


def _allocate_deposit_lump_sum(oic: dict) -> None:
    """On REJECT/WITHDRAWN, deposit is non-refundable and allocated as LUMP_SUM."""
    deposit = oic.get("deposit_paid_cents", 0)
    if deposit <= 0:
        return
    # Allocate against the OIC's covered liabilities in the pinned order; surplus rejected over total
    total = sum(STORE.tax_liabilities[lid]["current_balance_cents"] for lid in oic["liability_ids"])
    apply_amount = min(deposit, total)
    if apply_amount > 0:
        allocate(apply_amount, oic["liability_ids"])
        settle_to_paid_if_zero(oic["liability_ids"])
        release_check(dominant_cause="PAID_IN_FULL")
