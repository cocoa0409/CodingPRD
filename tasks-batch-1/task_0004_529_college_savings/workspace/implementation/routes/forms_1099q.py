"""Form 1099-Q routes."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask, request

from db import store, stamp_create, stamp_update, iso_ms
from errors import (
    err,
    ERR_FORM_ALREADY_EXISTS,
    ERR_FORM_PREMATURE_ISSUANCE,
    ERR_FORM_CORRECTION_WINDOW_CLOSED,
    ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success_object, success_array, parse_pagination, paginate
from services import refresh_form_1099q_aggregates
from validators import must_exist, require_dict, require_int, require_str


_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "account_id", "tax_year",
    "gross_distribution_cents", "earnings_cents", "basis_cents", "penalty_cents",
    "recipient_kind", "recipient_tax_id_last4", "status",
    "issued_at_utc", "supersedes_form_id",
)


def _view(f: dict) -> dict:
    return {k: f.get(k) for k in _VIEW_KEYS}


def register(app: Flask) -> None:

    @app.post("/forms-1099q")
    @require_roles("SystemTaxAuthority")
    def create_form():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        must_exist(store.accounts, account_id, path=False)
        tax_year = require_int(body, "tax_year")
        supersedes_id = body.get("supersedes_form_id")
        if supersedes_id is not None:
            must_exist(store.forms_1099q, supersedes_id, path=False)
        # Uniqueness: a DRAFT/ISSUED/REISSUED form for (account_id, tax_year).
        for f in store.forms_1099q.values():
            if (
                f["account_id"] == account_id
                and f["tax_year"] == tax_year
                and f["status"] in {"DRAFT", "ISSUED", "REISSUED"}
            ):
                raise err(ERR_FORM_ALREADY_EXISTS, "form already exists for (account, year)")
        form = stamp_create({
            "account_id": account_id,
            "tax_year": tax_year,
            "gross_distribution_cents": 0,
            "earnings_cents": 0,
            "basis_cents": 0,
            "penalty_cents": 0,
            "recipient_kind": "BENEFICIARY",
            "recipient_tax_id_last4": None,
            "status": "DRAFT",
            "issued_at_utc": None,
            "supersedes_form_id": supersedes_id,
        }, store.clock_utc)
        refresh_form_1099q_aggregates(form)
        store.forms_1099q[form["id"]] = form
        return success_object(_view(form), status=201)

    @app.post("/forms-1099q/<fid>/issue")
    @require_roles("SystemTaxAuthority")
    def issue_form(fid: str):
        form = must_exist(store.forms_1099q, fid, path=True)
        # State precondition (priority 6) before business safety (priority 9).
        if form["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "form must be DRAFT to issue")
        # Premature issuance: current clock must be >= Jan 1 of (tax_year + 1).
        boundary = datetime(form["tax_year"] + 1, 1, 1, tzinfo=timezone.utc)
        if store.clock_utc < boundary:
            raise err(ERR_FORM_PREMATURE_ISSUANCE, "before Jan 1 of tax_year + 1")
        # Re-snapshot aggregates one last time then pin recipient_tax_id_last4.
        refresh_form_1099q_aggregates(form)
        account = store.accounts[form["account_id"]]
        if form["recipient_kind"] == "ACCOUNT_OWNER":
            donor = store.donors[account["donor_id"]]
            form["recipient_tax_id_last4"] = donor["federal_tax_id_last4"]
        else:
            ben = store.beneficiaries[account["beneficiary_id"]]
            form["recipient_tax_id_last4"] = ben["federal_tax_id_last4"]
        form["status"] = "ISSUED"
        form["issued_at_utc"] = iso_ms(store.clock_utc)
        stamp_update(form, store.clock_utc)
        return success_object(_view(form))

    @app.post("/forms-1099q/<fid>/correct")
    @require_roles("SystemTaxAuthority")
    def correct_form(fid: str):
        form = must_exist(store.forms_1099q, fid, path=True)
        if form["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "form must be ISSUED to correct")
        # Correction window: tax_year >= current_year - 3.
        if form["tax_year"] < store.clock_utc.year - 3:
            raise err(ERR_FORM_CORRECTION_WINDOW_CLOSED, "correction window closed")
        now = store.clock_utc
        form["status"] = "CORRECTED"
        stamp_update(form, now)
        # Spawn successor in REISSUED state.
        successor = stamp_create({
            "account_id": form["account_id"],
            "tax_year": form["tax_year"],
            "gross_distribution_cents": 0,
            "earnings_cents": 0,
            "basis_cents": 0,
            "penalty_cents": 0,
            "recipient_kind": "BENEFICIARY",
            "recipient_tax_id_last4": None,
            "status": "DRAFT",  # transitional; immediately moved to REISSUED.
            "issued_at_utc": None,
            "supersedes_form_id": form["id"],
        }, now)
        refresh_form_1099q_aggregates(successor)
        # Pin recipient_tax_id_last4 for the successor as well (REISSUED is frozen).
        account = store.accounts[form["account_id"]]
        if successor["recipient_kind"] == "ACCOUNT_OWNER":
            successor["recipient_tax_id_last4"] = store.donors[account["donor_id"]][
                "federal_tax_id_last4"
            ]
        else:
            successor["recipient_tax_id_last4"] = store.beneficiaries[
                account["beneficiary_id"]
            ]["federal_tax_id_last4"]
        successor["status"] = "REISSUED"
        successor["issued_at_utc"] = iso_ms(now)
        store.forms_1099q[successor["id"]] = successor
        return success_object(_view(form))

    @app.get("/forms-1099q/<fid>")
    @require_roles("SystemTaxAuthority", "AccountOwner", "ComplianceOfficer")
    def get_form(fid: str):
        form = must_exist(store.forms_1099q, fid, path=True)
        return success_object(_view(form))

    @app.get("/forms-1099q")
    @require_roles("SystemTaxAuthority", "ComplianceOfficer")
    def list_forms():
        limit, offset = parse_pagination(request.args)
        rows = list(store.forms_1099q.values())
        account_filter = request.args.get("account_id")
        ty_filter = request.args.get("tax_year")
        supersedes_filter = request.args.get("supersedes_form_id")
        if account_filter:
            rows = [f for f in rows if f["account_id"] == account_filter]
        if ty_filter:
            try:
                ty_int = int(ty_filter)
                rows = [f for f in rows if f["tax_year"] == ty_int]
            except ValueError:
                rows = []
        if supersedes_filter:
            rows = [f for f in rows if f.get("supersedes_form_id") == supersedes_filter]
        rows.sort(key=lambda f: f["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(f) for f in page],
            limit=limit, offset=offset, total_count=total,
        )
