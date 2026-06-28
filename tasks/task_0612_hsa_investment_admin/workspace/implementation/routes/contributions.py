"""Contribution: create (PENDING), list, post (PRD §3.4).

Posting runs the IRS guardrail in pinned order: contributions_ytd -> limit ->
catch-up sub-limit guard (BEFORE general excess) -> excess -> posture.
"""
from flask import Blueprint

import serializers
from clock import clock
from db import db, stamp_create, touch
from errors import err
from helpers import get_json_body, paginate, qarg, require_enum, require_positive_int
from lookups import get_account, get_contribution
from middleware import caller, require_role
from response import success
from services.account_calc import (catch_up_component, catch_up_eligible,
                                    recompute_derived)

bp = Blueprint("contributions", __name__)


@bp.route("/hsa/accounts/<account_id>/contributions", methods=["POST"])
def create_contribution(account_id):
    user_id, role = caller()
    require_role(role, {"AccountAdmin", "Employer"})
    account = get_account(account_id)

    # Employer ownership (PRD §2.1): an employer may only create payroll
    # contributions on accounts it sponsors (account.employer_id == X-User-ID).
    if role == "Employer":
        if account["employer_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Employer does not sponsor this account")

    body = get_json_body()
    channel = require_enum(body, "channel", {"PAYROLL", "INDIVIDUAL"})
    amount = require_positive_int(body, "amount_cents")
    kind = require_enum(body, "contribution_kind", {"REGULAR", "CATCH_UP"},
                        required=False, default="REGULAR")

    o = {
        "account_id": account_id,
        "channel": channel,
        "amount_cents": amount,
        "contribution_kind": kind,
        "status": "PENDING",
        "posted_at": None,
    }
    stamp_create(o)
    db.contributions[o["id"]] = o
    return success(serializers.contribution(o), status=201)


@bp.route("/hsa/accounts/<account_id>/contributions", methods=["GET"])
def list_contributions(account_id):
    user_id, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder", "Employer"})
    account = get_account(account_id)
    if role == "Employer" and account["employer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Employer does not sponsor this account")
    status_filter = qarg("status")
    channel_filter = qarg("channel")
    items = [
        c for c in db.contributions.values()
        if c["account_id"] == account_id
        and (status_filter is None or c["status"] == status_filter)
        and (channel_filter is None or c["channel"] == channel_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.contribution(c) for c in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/contributions/<contribution_id>/post", methods=["POST"])
def post_contribution(account_id, contribution_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    contribution = get_contribution(account_id, contribution_id)

    # State: only from PENDING.
    if contribution["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Contribution is not PENDING")

    # lifecycle must be ACTIVE (ERR_INVALID_STATE).
    if account["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")

    # posture must be OPEN (ERR_POSTURE_LOCKED).
    if account["contribution_posture"] != "OPEN":
        raise err("ERR_POSTURE_LOCKED", "Account contribution_posture is LOCKED")

    # PAYROLL channel requires employer with payroll enabled.
    if contribution["channel"] == "PAYROLL":
        employer = db.employers.get(account["employer_id"])
        if employer is None or not employer.get("payroll_contributions_enabled", False):
            raise err("ERR_PAYROLL_DISABLED", "Payroll contributions are disabled")

    # CATCH_UP requires holder 55+ in plan_year.
    if contribution["contribution_kind"] == "CATCH_UP":
        if not catch_up_eligible(account):
            raise err("ERR_CATCHUP_INELIGIBLE", "Accountholder is not catch-up eligible")

    # Catch-up sub-limit guard (STEP 4), evaluated BEFORE general excess (STEP 3).
    # Sum of POSTED CATCH_UP amounts must not exceed catch_up component. We test
    # the prospective sum (existing POSTED catch-up + this amount).
    if contribution["contribution_kind"] == "CATCH_UP":
        posted_catchup = sum(
            c["amount_cents"] for c in db.contributions.values()
            if c["account_id"] == account_id and c["status"] == "POSTED"
            and c["contribution_kind"] == "CATCH_UP"
        )
        if posted_catchup + contribution["amount_cents"] > catch_up_component(account):
            raise err("ERR_CATCHUP_LIMIT_EXCEEDED", "Catch-up sub-limit exceeded")

    # Commit: POSTED, posted_at stamped, cash credited, derived recomputed.
    contribution["status"] = "POSTED"
    contribution["posted_at"] = clock.now_iso()
    touch(contribution)
    account["cash_balance_cents"] += contribution["amount_cents"]
    recompute_derived(account)  # ytd / limit / excess / posture; bump version
    return success(serializers.contribution(contribution), status=200)
