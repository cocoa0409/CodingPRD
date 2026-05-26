"""BeneficiaryChange routes: create, approve, reject, get, list."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create, stamp_update, iso_ms
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_BENEFICIARY_NOT_FAMILY_MEMBER,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_FORBIDDEN,
)
from middleware import require_roles, current_user_id
from response import success_object, success_array, parse_pagination, paginate
from validators import must_exist, require_dict, require_int, require_str


_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "account_id", "from_beneficiary_id", "to_beneficiary_id",
    "from_relationship_class", "to_relationship_class",
    "status", "decided_at_utc",
)
_FAMILY_OK = {"SELF", "CHILD", "SIBLING", "FIRST_COUSIN"}


def _view(c: dict) -> dict:
    return {k: c.get(k) for k in _VIEW_KEYS}


def _ensure_owner_via_account(account_id: str) -> dict:
    account = must_exist(store.accounts, account_id, path=False)
    if request.headers.get("X-User-Role") == "AccountOwner":
        if current_user_id() != account["donor_id"]:
            raise err(ERR_FORBIDDEN, "AccountOwner does not own this account")
    return account


def register(app: Flask) -> None:

    @app.post("/beneficiary-changes")
    @require_roles("AccountOwner")
    def create_change():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        to_id = require_str(body, "to_beneficiary_id")
        account = _ensure_owner_via_account(account_id)
        to_ben = must_exist(store.beneficiaries, to_id, path=False)
        from_id = account["beneficiary_id"]
        from_ben = store.beneficiaries[from_id]
        # PRD §3.7: the family-member rule also rejects creation when to is OTHER.
        if to_ben["relationship_class"] == "OTHER":
            raise err(ERR_BENEFICIARY_NOT_FAMILY_MEMBER, "to_relationship_class is OTHER")
        change = stamp_create({
            "account_id": account_id,
            "from_beneficiary_id": from_id,
            "to_beneficiary_id": to_id,
            "from_relationship_class": from_ben["relationship_class"],
            "to_relationship_class": to_ben["relationship_class"],
            "status": "PENDING",
            "decided_at_utc": None,
        }, store.clock_utc)
        store.beneficiary_changes[change["id"]] = change
        store.bchange_creator[change["id"]] = current_user_id()
        return success_object(_view(change), status=201)

    @app.post("/beneficiary-changes/<cid>/approve")
    @require_roles("ComplianceOfficer")
    def approve_change(cid: str):
        change = must_exist(store.beneficiary_changes, cid, path=True)
        body = require_dict(request.get_json(silent=True))
        # Segregation-of-duties: PRD §2.8 places SoD ABOVE OCC + state. Test
        # test_segregation_surfaces_before_occ_when_same_user_approves_own_change
        # demands SoD fires when the change is still PENDING and OCC is fresh —
        # so SoD must run before state too in PRACTICE we check SoD before OCC.
        # Test test_auth_segregation_beats_state_occ_on_beneficiary_change_approve
        # also confirms SoD fires before OCC.
        creator = store.bchange_creator.get(cid)
        if creator is not None and creator == current_user_id():
            raise err(ERR_SEGREGATION_OF_DUTIES, "approver must differ from creator")
        # State precondition.
        if change["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "change must be PENDING to approve")
        account = store.accounts[change["account_id"]]
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to approve change")
        # OCC.
        if "expected_account_version" not in body:
            raise err(ERR_INVALID_REQUEST, "expected_account_version required")
        expected = require_int(body, "expected_account_version")
        if expected != account["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "expected_account_version mismatch")
        # Family rule.
        if change["to_relationship_class"] not in _FAMILY_OK:
            raise err(ERR_BENEFICIARY_NOT_FAMILY_MEMBER, "to_relationship_class not family")
        # Apply.
        now = store.clock_utc
        change["status"] = "APPROVED"
        change["decided_at_utc"] = iso_ms(now)
        stamp_update(change, now)
        account["beneficiary_id"] = change["to_beneficiary_id"]
        stamp_update(account, now)
        return success_object(_view(change))

    @app.post("/beneficiary-changes/<cid>/reject")
    @require_roles("ComplianceOfficer")
    def reject_change(cid: str):
        change = must_exist(store.beneficiary_changes, cid, path=True)
        if change["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "change must be PENDING to reject")
        now = store.clock_utc
        change["status"] = "REJECTED"
        change["decided_at_utc"] = iso_ms(now)
        stamp_update(change, now)
        return success_object(_view(change))

    @app.get("/beneficiary-changes/<cid>")
    @require_roles("AccountOwner", "ComplianceOfficer")
    def get_change(cid: str):
        change = must_exist(store.beneficiary_changes, cid, path=True)
        if request.headers.get("X-User-Role") == "AccountOwner":
            account = store.accounts.get(change["account_id"])
            if not account or current_user_id() != account["donor_id"]:
                raise err(ERR_FORBIDDEN, "AccountOwner does not own this change")
        return success_object(_view(change))

    @app.get("/beneficiary-changes")
    @require_roles("AccountOwner", "ComplianceOfficer")
    def list_changes():
        limit, offset = parse_pagination(request.args)
        rows = list(store.beneficiary_changes.values())
        account_filter = request.args.get("account_id")
        to_filter = request.args.get("to_beneficiary_id")
        from_filter = request.args.get("from_beneficiary_id")
        if account_filter:
            rows = [c for c in rows if c["account_id"] == account_filter]
        if to_filter:
            rows = [c for c in rows if c["to_beneficiary_id"] == to_filter]
        if from_filter:
            rows = [c for c in rows if c["from_beneficiary_id"] == from_filter]
        if request.headers.get("X-User-Role") == "AccountOwner":
            owned = {a["id"] for a in store.accounts.values()
                     if a["donor_id"] == current_user_id()}
            rows = [c for c in rows if c["account_id"] in owned]
        rows.sort(key=lambda c: c["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(c) for c in page],
            limit=limit, offset=offset, total_count=total,
        )
