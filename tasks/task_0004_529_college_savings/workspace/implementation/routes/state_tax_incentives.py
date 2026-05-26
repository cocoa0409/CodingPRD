"""StateTaxIncentive routes."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create, stamp_update
from errors import err, ERR_INCENTIVE_ALREADY_EXISTS, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_array, parse_pagination, paginate
from calculations import state_tax_match_cents
from services import recompute_state_tax_incentives
from validators import must_exist, require_dict, require_int, require_str


_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "donor_id", "tax_year",
    "contributions_eligible_cents", "match_cents", "status",
)


def _view(s: dict) -> dict:
    return {k: s[k] for k in _VIEW_KEYS}


def register(app: Flask) -> None:

    @app.post("/state-tax-incentives")
    @require_roles("CustodianAgent")
    def create_incentive():
        body = require_dict(request.get_json(silent=True))
        donor_id = require_str(body, "donor_id")
        must_exist(store.donors, donor_id, path=False)
        tax_year = require_int(body, "tax_year")
        # Uniqueness (donor_id, tax_year).
        for sti in store.state_tax_incentives.values():
            if sti["donor_id"] == donor_id and sti["tax_year"] == tax_year:
                raise err(ERR_INCENTIVE_ALREADY_EXISTS, "incentive already exists")
        sti = stamp_create({
            "donor_id": donor_id,
            "tax_year": tax_year,
            "contributions_eligible_cents": 0,
            "match_cents": 0,
            "status": "DRAFT",
        }, store.clock_utc)
        store.state_tax_incentives[sti["id"]] = sti
        # Aggregate eligible contributions from existing POSTED data.
        recompute_state_tax_incentives(donor_id, tax_year)
        return success_object(_view(sti), status=201)

    @app.post("/state-tax-incentives/<sid>/calculate")
    @require_roles("CustodianAgent")
    def calculate_incentive(sid: str):
        sti = must_exist(store.state_tax_incentives, sid, path=True)
        if sti["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "incentive must be DRAFT to calculate")
        donor = store.donors[sti["donor_id"]]
        sti["match_cents"] = state_tax_match_cents(
            donor["state_code"], sti["contributions_eligible_cents"]
        )
        sti["status"] = "CALCULATED"
        stamp_update(sti, store.clock_utc)
        return success_object(_view(sti))

    @app.post("/state-tax-incentives/<sid>/finalize")
    @require_roles("CustodianAgent")
    def finalize_incentive(sid: str):
        sti = must_exist(store.state_tax_incentives, sid, path=True)
        if sti["status"] != "CALCULATED":
            raise err(ERR_INVALID_STATE, "incentive must be CALCULATED to finalize")
        sti["status"] = "FINALIZED"
        stamp_update(sti, store.clock_utc)
        return success_object(_view(sti))

    @app.get("/state-tax-incentives/<sid>")
    @require_roles("CustodianAgent", "AccountOwner")
    def get_incentive(sid: str):
        sti = must_exist(store.state_tax_incentives, sid, path=True)
        return success_object(_view(sti))

    @app.get("/state-tax-incentives")
    @require_roles("CustodianAgent", "ComplianceOfficer")
    def list_incentives():
        limit, offset = parse_pagination(request.args)
        rows = list(store.state_tax_incentives.values())
        donor_filter = request.args.get("donor_id")
        ty_filter = request.args.get("tax_year")
        if donor_filter:
            rows = [r for r in rows if r["donor_id"] == donor_filter]
        if ty_filter:
            try:
                ty_int = int(ty_filter)
                rows = [r for r in rows if r["tax_year"] == ty_int]
            except ValueError:
                rows = []
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(r) for r in page],
            limit=limit, offset=offset, total_count=total,
        )
