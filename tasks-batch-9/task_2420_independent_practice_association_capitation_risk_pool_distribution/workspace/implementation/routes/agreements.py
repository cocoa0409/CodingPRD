"""Delegation agreements (PRD 3.1)."""

from flask import Blueprint

import calc
import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("agreements", __name__)

AGREEMENT_STATES = ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
LIVE_POOL_STATES = ("ACCUMULATING", "CLOSED_FOR_INCURRAL", "RESERVED",
                    "SETTLEMENT_PROPOSED")

READ_ROLES = ("IpaAdmin", "NetworkManager", "ClaimsExaminer",
              "ReinsuranceUnderwriter", "PayerRepresentative")


@bp.post("/ipa/delegation-agreements")
def create_agreement():
    middleware.require("IpaAdmin")
    body = validate.body()

    payer_name = validate.req_str(body, "payer_name")
    payer_tax_id = validate.req_str(body, "payer_tax_id")
    delegation_scope = validate.req_enum(body, "delegation_scope", calc.DELEGATION_SCOPES)
    base_pmpm_cents = validate.req_int(body, "base_pmpm_cents", minimum=1)
    reconciliation_method = validate.req_enum(body, "reconciliation_method",
                                              calc.RECONCILIATION_METHODS)
    ibnr_method = validate.req_enum(body, "ibnr_method", calc.IBNR_METHODS)
    ibnr_completion_factor_bps = validate.req_int(body, "ibnr_completion_factor_bps",
                                                 minimum=1, maximum=10000)
    target_claims_pmpm_cents = validate.req_int(body, "target_claims_pmpm_cents",
                                               minimum=0)
    professional_pool_share_bps = validate.req_int(body, "professional_pool_share_bps",
                                                  minimum=0, maximum=10000)
    institutional_pool_share_bps = validate.req_int(body, "institutional_pool_share_bps",
                                                   minimum=0, maximum=10000)
    quality_withhold_bps = validate.req_int(body, "quality_withhold_bps", minimum=0,
                                            maximum=3000)
    stop_loss_attachment_cents = validate.req_int(body, "stop_loss_attachment_cents",
                                                 minimum=0)
    reinsurance_recovery_bps = validate.req_int(body, "reinsurance_recovery_bps",
                                               minimum=0, maximum=10000)
    max_panel_size = validate.req_int(body, "max_panel_size", minimum=1)
    continuity_of_care_days = validate.opt_int(body, "continuity_of_care_days",
                                              minimum=0, default=90)

    # check 20 — uniqueness
    for existing in db.agreements.values():
        if existing["payer_tax_id"] == payer_tax_id:
            fail("ERR_DUPLICATE_TAX_ID")
    # check 21 — pool shares sum to par
    if professional_pool_share_bps + institutional_pool_share_bps != 10000:
        fail("ERR_POOL_SHARE_SUM_INVALID")

    agreement = db.create(
        db.agreements,
        payer_name=payer_name,
        payer_tax_id=payer_tax_id,
        delegation_scope=delegation_scope,
        base_pmpm_cents=base_pmpm_cents,
        reconciliation_method=reconciliation_method,
        ibnr_method=ibnr_method,
        ibnr_completion_factor_bps=ibnr_completion_factor_bps,
        target_claims_pmpm_cents=target_claims_pmpm_cents,
        professional_pool_share_bps=professional_pool_share_bps,
        institutional_pool_share_bps=institutional_pool_share_bps,
        quality_withhold_bps=quality_withhold_bps,
        stop_loss_attachment_cents=stop_loss_attachment_cents,
        reinsurance_recovery_bps=reinsurance_recovery_bps,
        continuity_of_care_days=continuity_of_care_days,
        max_panel_size=max_panel_size,
        status="DRAFT",
        capitation_posture="CURRENT",
        accrued_capitation_cents=0,
        withheld_balance_cents=0,
        forfeited_withhold_cents=0,
        total_assigned_members=0,
    )
    return response.ok(serialize.agreement(agreement), 201)


@bp.get("/ipa/delegation-agreements")
def list_agreements():
    middleware.require(*READ_ROLES)
    status = validate.query_enum("status", AGREEMENT_STATES)
    limit, offset = validate.pagination()
    items = db.ordered(db.agreements.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.agreement(a) for a in window], limit, offset,
                            len(items))


@bp.get("/ipa/delegation-agreements/<agreement_id>")
def read_agreement(agreement_id):
    user_id, role = middleware.require(*READ_ROLES)
    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)
    return response.ok(serialize.agreement(agreement))


@bp.post("/ipa/delegation-agreements/<agreement_id>/state")
def agreement_state(agreement_id):
    middleware.require("IpaAdmin")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", AGREEMENT_STATES)
    agreement = resolve.agreement(agreement_id)
    current = agreement["status"]

    if to_state == "ACTIVE":
        if current not in ("DRAFT", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        if current == "DRAFT":
            # check 21 is re-evaluated at activation
            if (agreement["professional_pool_share_bps"]
                    + agreement["institutional_pool_share_bps"]) != 10000:
                fail("ERR_POOL_SHARE_SUM_INVALID")
            agreement["status"] = "ACTIVE"
            agreement["capitation_posture"] = "CURRENT"
            db.touch(agreement)
            for enrollee in db.enrollees_of_agreement(agreement["id"]):
                derive.derive_enrollee_components(agreement, enrollee)
        else:
            agreement["status"] = "ACTIVE"
            db.touch(agreement)
    elif to_state == "SUSPENDED":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        agreement["status"] = "SUSPENDED"
        db.touch(agreement)
        derive.close_open_panels(agreement)
    elif to_state == "TERMINATED":
        if current not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        for pool in db.pools_of_agreement(agreement["id"]):
            if pool["status"] in LIVE_POOL_STATES:
                fail("ERR_INVALID_STATE_TRANSITION")
        agreement["status"] = "TERMINATED"
        db.touch(agreement)
    else:
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.agreement(agreement))
