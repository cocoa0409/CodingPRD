"""Cost recovery, contribution claims and de minimis settlements."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("actions", __name__)

ZERO = Decimal("0.00")


@bp.post("/sites/<site_id>/cost-recovery-actions")
def create_action(site_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    respondent_id = shape.str_field(body, "respondent_prp_id")
    action_type = shape.enum_field(body, "action_type", K.ACTION_TYPES)
    demanded = shape.money_field(body, "demanded_cents", strictly_positive=True)
    expected = shape.int_field(body, "expected_prp_version", lo=0)
    claimant_id = shape.str_field(body, "claimant_prp_id", required=False)
    site = common.get_site(site_id)
    respondent = common.get_prp(respondent_id)
    claimant = common.get_prp(claimant_id) if claimant_id else None
    if expected != respondent["version"]:
        raise ApiError("ERR_STALE_PRP_VERSION")
    # This stream is refused only when the site is frozen, never when it is
    # merely restricted.
    common.deny_frozen(site)
    common.deny_deleted(site)
    round_ = derive.adopted_round(site)
    if round_ is None:
        raise ApiError("ERR_NO_ADOPTED_ALLOCATION")
    share = derive.share_for(round_["id"], respondent["id"])
    if (
        respondent["site_id"] != site["id"]
        or share is None
        or share["disposition"] != "ALLOCATED"
    ):
        raise ApiError("ERR_RESPONDENT_NOT_ALLOCATED")

    share_pct = share["final_pct"] if share["final_pct"] is not None else ZERO
    floor = None
    if action_type == "DE_MINIMIS_SETTLEMENT":
        if not respondent["de_minimis_eligible"]:
            raise ApiError("ERR_NOT_DE_MINIMIS_ELIGIBLE")
        floor = calc.de_minimis_premium_floor(
            site["total_response_cost_cents"], share_pct
        )
        if demanded < floor:
            raise ApiError("ERR_DE_MINIMIS_PREMIUM_INSUFFICIENT")

    action = common.new_record(
        {
            "site_id": site["id"],
            "respondent_prp_id": respondent["id"],
            # The government is the claimant on a demand and on a buyout.
            "claimant_prp_id": claimant["id"]
            if claimant is not None and action_type == "CONTRIBUTION_CLAIM"
            else None,
            "action_type": action_type,
            "demanded_cents": demanded,
            "premium_floor_cents": floor,
            "respondent_share_pct_at_offer": share_pct,
            "status": "OFFERED",
            "received_cents": 0,
            "received_at": None,
            "void_reason": None,
        }
    )
    store.cost_recovery_actions[action["id"]] = action
    # The respondent is never left holding two live offers of the same kind.
    for other in derive.site_actions(site["id"]):
        if (
            other["id"] != action["id"]
            and other["respondent_prp_id"] == respondent["id"]
            and other["action_type"] == action_type
            and other["status"] == "OFFERED"
        ):
            txn.watch(other)
            other["status"] = "SUPERSEDED"
    # Opening any action increments the respondent's version by one.
    txn.force(respondent)
    return common.respond(action, serialize.cost_recovery_action, 201)


def _settle_de_minimis(site, action, respondent):
    txn.watch(respondent)
    respondent["status"] = "DE_MINIMIS_SETTLED"
    respondent["contribution_protection"] = True
    round_ = derive.adopted_round(site)
    if round_ is None:
        return
    share = derive.share_for(round_["id"], respondent["id"])
    if share is None or share["disposition"] != "ALLOCATED":
        return
    txn.watch(share)
    share["pre_settlement_final_pct"] = share["final_pct"] or ZERO
    share["final_pct"] = ZERO
    share["disposition"] = "SETTLED"
    derive.recompute_share_totals(round_)


@bp.post("/cost-recovery-actions/<action_id>/response")
def respond_action(action_id):
    actor = require(K.ROLE_PRP)
    body = shape.get_body()
    decision = shape.enum_field(body, "decision", K.RESPONSE_DECISIONS)
    shape.str_field(body, "response_note", required=False)
    action = common.get_action(action_id)
    common.identity(actor, action["respondent_prp_id"])
    respondent = store.prps[action["respondent_prp_id"]]
    site = store.sites[action["site_id"]]
    common.state(action["status"] == "OFFERED")
    common.deny_deleted(site)

    if decision == "ACCEPT" and action["action_type"] == "DE_MINIMIS_SETTLEMENT":
        # Eligibility is re-checked at acceptance against current site totals.
        if not respondent["de_minimis_eligible"]:
            raise ApiError("ERR_NOT_DE_MINIMIS_ELIGIBLE")
        if action["demanded_cents"] < (action["premium_floor_cents"] or 0):
            raise ApiError("ERR_DE_MINIMIS_PREMIUM_INSUFFICIENT")

    txn.watch(action)
    if decision == "REJECT":
        action["status"] = "REJECTED"
        if action["action_type"] == "COST_RECOVERY_DEMAND":
            txn.watch(respondent)
            respondent["status"] = "RECALCITRANT"
    else:
        # Acceptance is a promise to pay, not a payment.
        action["status"] = "ACCEPTED"
        if action["action_type"] == "DE_MINIMIS_SETTLEMENT":
            _settle_de_minimis(site, action, respondent)
    derive.recompute_site_derived(site)
    return common.respond(action, serialize.cost_recovery_action)


@bp.post("/cost-recovery-actions/<action_id>/collection")
def collect_action(action_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    received = shape.money_field(body, "received_cents", minimum=0)
    shape.str_field(body, "receipt_reference", required=False)
    action = common.get_action(action_id)
    site = store.sites[action["site_id"]]
    common.state(action["status"] == "ACCEPTED")
    common.deny_deleted(site)
    outstanding = action["demanded_cents"] - action["received_cents"]
    # Overpayment is refused, never clamped, with nothing recorded.
    if received > outstanding:
        raise ApiError("ERR_OVERPAYMENT_NOT_ALLOWED")

    txn.watch(action)
    action["received_cents"] += received
    action["received_at"] = logical_clock.now()
    if action["received_cents"] == action["demanded_cents"]:
        action["status"] = "COLLECTED"
        if action["action_type"] == "COST_RECOVERY_DEMAND":
            respondent = store.prps[action["respondent_prp_id"]]
            if respondent["status"] in ("PARTICIPATING", "RECALCITRANT"):
                txn.watch(respondent)
                respondent["status"] = "SETTLED"
                respondent["contribution_protection"] = True
    derive.recompute_site_derived(site)
    return common.respond(action, serialize.cost_recovery_action)


@bp.post("/cost-recovery-actions/<action_id>/voiding")
def void_action(action_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    reason = shape.str_field(body, "void_reason")
    action = common.get_action(action_id)
    site = store.sites[action["site_id"]]
    respondent = store.prps[action["respondent_prp_id"]]
    common.state(action["status"] in ("ACCEPTED", "COLLECTED"))
    common.deny_deleted(site)

    txn.watch(action)
    action["status"] = "VOIDED"
    action["void_reason"] = reason
    # A full compensating reversal: the receipts leave the ledger with the
    # action's own received_cents zeroed.
    action["received_cents"] = 0

    if action["action_type"] == "DE_MINIMIS_SETTLEMENT":
        if respondent["status"] == "DE_MINIMIS_SETTLED":
            txn.watch(respondent)
            respondent["status"] = "PARTICIPATING"
            respondent["contribution_protection"] = False
            derive.recompute_prp_eligibility(site, respondent)
        round_ = derive.adopted_round(site)
        share = (
            derive.share_for(round_["id"], respondent["id"]) if round_ else None
        )
        if share is not None and share["disposition"] == "SETTLED":
            txn.watch(share)
            share["final_pct"] = share["pre_settlement_final_pct"] or ZERO
            share["pre_settlement_final_pct"] = None
            share["disposition"] = "ALLOCATED"
            derive.recompute_share_totals(round_)
    elif action["action_type"] == "COST_RECOVERY_DEMAND":
        # A demand settlement never zeroed the final_pct, so the share is left
        # entirely alone.
        if respondent["status"] == "SETTLED":
            txn.watch(respondent)
            respondent["status"] = "PARTICIPATING"
            respondent["contribution_protection"] = False

    derive.recompute_site_derived(site)
    return common.respond(action, serialize.cost_recovery_action)
