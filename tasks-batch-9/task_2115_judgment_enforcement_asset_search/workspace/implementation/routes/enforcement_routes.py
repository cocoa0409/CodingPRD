"""Enforcement actions: drafting, writ request, service and release (PRD 3.5)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    LEVY_TERM_DAYS,
    SHERIFF_FEE_CENTS,
    add_days,
    bank_levy_hold,
    by_seq,
    certified_score,
    debtor_of_judgment,
    get_action,
    get_finding,
    get_judgment,
    guard_judgment_alive,
    guard_not_stayed,
    invalid_state,
    recompute_balances,
    recount_judgment,
    return_levy_hold,
    step_back_posture,
    to_date,
    wage_garnishment_withholding,
)
from errors import ApiError
from store import bump, new_row, store, touch
from validators import (
    ENUM_ACTION_TYPE,
    check_enum,
    json_body,
    pagination,
    present,
    require_date,
    require_int,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ("CaseManager", "EnforcementOfficer", "ComplianceOfficer", "Creditor")


def register(app):
    # ---- POST /enforcement-actions ---------------------------------------
    @endpoint(app, "/enforcement-actions", "POST", ("CaseManager",), 201)
    def create_action(ctx):
        body = json_body()
        judgment = get_judgment(body.get("judgment_id")) if present(body, "judgment_id") else None
        finding = get_finding(body.get("asset_finding_id")) if present(body, "asset_finding_id") else None
        judgment_id = require_string(body, "judgment_id")
        asset_finding_id = require_string(body, "asset_finding_id")
        require_string(body, "action_type")
        expected_version = require_int(body, "expected_judgment_version")
        action_type = check_enum(body, "action_type", ENUM_ACTION_TYPE)
        # rung 12 - optimistic concurrency against the judgment row
        if expected_version != judgment["version"]:
            raise ApiError("ERR_STALE_JUDGMENT_VERSION",
                           "expected_judgment_version does not match the judgment's current version.")
        guard_judgment_alive(judgment)
        guard_not_stayed(judgment)
        # rung 28 - the finding must be VERIFIED at drafting
        if finding["status"] != "VERIFIED":
            raise ApiError("ERR_FINDING_NOT_VERIFIED", "The referenced asset finding is not VERIFIED.")
        # rung 32 - the instrument must match the asset class
        if action_type == "WAGE_GARNISHMENT" and finding["asset_type"] != "EMPLOYMENT":
            raise ApiError("ERR_ACTION_ASSET_TYPE_MISMATCH",
                           "A wage garnishment requires an EMPLOYMENT finding.")
        if action_type == "BANK_LEVY" and finding["asset_type"] != "BANK_ACCOUNT":
            raise ApiError("ERR_ACTION_ASSET_TYPE_MISMATCH",
                           "A bank levy requires a BANK_ACCOUNT finding.")

        row = new_row({
            "judgment_id": judgment_id,
            "asset_finding_id": asset_finding_id,
            "action_type": action_type,
            "status": "DRAFT",
            "writ_requested_on": None,
            "writ_requested_by_user_id": None,
            "served_on": None,
            "expires_on": None,
            "levy_hold_cents": 0,
            "weekly_withholding_cents": 0,
            "collected_cents": 0,
            "sheriff_fee_cents": 0,
        })
        store.enforcement_actions[row["id"]] = row
        bump(judgment)
        return serialize(row)

    # ---- GET /enforcement-actions ----------------------------------------
    @endpoint(app, "/enforcement-actions", "GET", READ_ROLES, 200)
    def list_actions(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.enforcement_actions.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "asset_finding_id")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, lambda r: store.judgments.get(r["judgment_id"]))
        return make_list(rows, limit, offset, serialize)

    # ---- GET /enforcement-actions/{enforcement_action_id} ----------------
    @endpoint(app, "/enforcement-actions/<enforcement_action_id>", "GET", READ_ROLES, 200)
    def read_action(ctx, enforcement_action_id):
        action = get_action(enforcement_action_id)
        check_judgment_ownership(ctx, store.judgments.get(action["judgment_id"]))
        return serialize(action)

    # ---- POST /enforcement-actions/{id}/request-writ ---------------------
    @endpoint(app, "/enforcement-actions/<enforcement_action_id>/request-writ", "POST",
              ("EnforcementOfficer",), 200)
    def request_writ(ctx, enforcement_action_id):
        action = get_action(enforcement_action_id)
        if action["status"] != "DRAFT":
            invalid_state("Only a DRAFT enforcement action may have its writ requested.")
        judgment = store.judgments.get(action["judgment_id"])
        guard_judgment_alive(judgment)
        finding = store.asset_findings.get(action["asset_finding_id"])
        # rung 17 - segregation of duties, keyed on X-User-ID
        verifier = finding.get("verified_by_user_id") if finding else None
        if verifier and ctx.user_id and verifier == ctx.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The officer who verified the finding may not request the writ.")
        # rung 19 then rung 27 - posture gates
        guard_not_stayed(judgment)
        if judgment["enforcement_posture"] not in ("LIEN_PERFECTED", "ENFORCING"):
            raise ApiError("ERR_NO_PERFECTED_LIEN", "No perfected lien supports this writ.")
        # rung 29 - the finding must not have been staled since drafting
        if finding is not None and finding["status"] == "STALE":
            raise ApiError("ERR_FINDING_STALE", "A superseding skip trace staled the linked finding.")

        withholding = 0
        if action["action_type"] == "WAGE_GARNISHMENT":
            withholding = wage_garnishment_withholding(action)
            if withholding <= 0:
                raise ApiError("ERR_GARNISHMENT_BELOW_FLOOR",
                               "The computed weekly withholding is zero.")
        else:
            if bank_levy_hold(action) <= 0:
                raise ApiError("ERR_NO_LEVIABLE_FUNDS", "The computed bank levy hold is zero.")

        action["status"] = "WRIT_REQUESTED"
        action["writ_requested_on"] = store.clock_date().isoformat()
        action["writ_requested_by_user_id"] = ctx.user_id
        if action["action_type"] == "WAGE_GARNISHMENT":
            action["weekly_withholding_cents"] = withholding
        bump(action)

        debtor = debtor_of_judgment(judgment)
        if debtor is not None:
            debtor["certified_recoverability_score"] = certified_score(debtor)
            touch(debtor)
        recount_judgment(judgment)
        touch(judgment)
        return serialize(action)

    # ---- POST /enforcement-actions/{id}/serve ----------------------------
    @endpoint(app, "/enforcement-actions/<enforcement_action_id>/serve", "POST",
              ("EnforcementOfficer",), 200)
    def serve_writ(ctx, enforcement_action_id):
        action = get_action(enforcement_action_id)
        body = json_body()
        served_on = require_date(body, "served_on")
        if action["status"] != "WRIT_REQUESTED":
            invalid_state("Only a WRIT_REQUESTED enforcement action may be served.")
        judgment = store.judgments.get(action["judgment_id"])
        guard_judgment_alive(judgment)
        guard_not_stayed(judgment)
        requested_on = to_date(action["writ_requested_on"])
        clock_date = store.clock_date()
        if served_on < requested_on or served_on > clock_date:
            raise ApiError("ERR_INVALID_REQUEST",
                           "served_on must fall between writ_requested_on and the current clock date.")
        expires_on = add_days(served_on, LEVY_TERM_DAYS)
        # rung 24 - half-open occupation windows may not overlap
        for other in store.enforcement_actions.values():
            if other["id"] == action["id"]:
                continue
            if other["asset_finding_id"] != action["asset_finding_id"]:
                continue
            if other["status"] not in ("SERVED", "SUSPENDED"):
                continue
            other_start = to_date(other["served_on"])
            other_end = to_date(other["expires_on"])
            if other_start is None or other_end is None:
                continue
            if served_on < other_end and other_start < expires_on:
                raise ApiError("ERR_LEVY_WINDOW_CONFLICT",
                               "The occupation window overlaps a live writ on the same asset.")

        finding = store.asset_findings.get(action["asset_finding_id"])
        hold = 0
        if action["action_type"] == "BANK_LEVY":
            hold = bank_levy_hold(action)
            if hold <= 0:
                raise ApiError("ERR_NO_LEVIABLE_FUNDS", "The computed bank levy hold is zero.")

        action["served_on"] = served_on.isoformat()
        action["expires_on"] = expires_on.isoformat()
        if action["action_type"] == "BANK_LEVY":
            action["levy_hold_cents"] = hold
            finding["available_cents"] -= hold
            finding["frozen_cents"] += hold
            bump(finding)
        # the sheriff fee lands only after the hold has been sized
        action["sheriff_fee_cents"] = SHERIFF_FEE_CENTS
        action["status"] = "SERVED"
        bump(action)

        judgment["_sheriff_fees"] += SHERIFF_FEE_CENTS
        recompute_balances(judgment)
        if judgment["enforcement_posture"] == "LIEN_PERFECTED":
            judgment["enforcement_posture"] = "ENFORCING"
        recount_judgment(judgment)
        bump(judgment)
        return serialize(action)

    # ---- POST /enforcement-actions/{id}/release --------------------------
    @endpoint(app, "/enforcement-actions/<enforcement_action_id>/release", "POST",
              ("EnforcementOfficer", "ComplianceOfficer"), 200)
    def release_writ(ctx, enforcement_action_id):
        action = get_action(enforcement_action_id)
        if action["status"] not in ("WRIT_REQUESTED", "SERVED", "SUSPENDED"):
            invalid_state("Only a live writ may be released.")
        judgment = store.judgments.get(action["judgment_id"])
        guard_judgment_alive(judgment)
        return_levy_hold(action)
        action["status"] = "RELEASED"
        bump(action)
        step_back_posture(judgment)
        return serialize(action)
