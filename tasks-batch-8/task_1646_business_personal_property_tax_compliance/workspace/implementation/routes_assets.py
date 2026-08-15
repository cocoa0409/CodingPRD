"""Routes: assets, classification, disposals (PRD §3.2, §3.3)."""

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_str, req_int, req_enum, lookup, stamp_new, touch,
    parse_date_field, append_audit,
)
from services import (
    find_class_rule, rule_proposal, reclassify_line_refresh,
    recompute_rendition_total, generate_rendition_lines,
    lien_date, flag_forecasts_force, latest_recorded_disposal, CATEGORIES,
)
from serializers import asset_view, disposal_view

bp = Blueprint("assets", __name__)

CLASSIFICATION_VALUES = {"TAXABLE", "NON_TAXABLE", "EXEMPT_FLAGGED"}


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/assets
    # ------------------------------------------------------------------
    @app.post("/bpp/assets")
    def create_asset():
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        body = get_body()
        client_id = req_str(body, "client_id")
        jurisdiction_id = req_str(body, "jurisdiction_id")
        asset_tag = req_str(body, "asset_tag")
        category = req_enum(body, "category", CATEGORIES)
        cost = req_int(body, "acquisition_cost_cents", min_v=1)
        acq = parse_date_field(body, "acquisition_date")
        in_service = parse_date_field(body, "in_service_date")
        # referenced entities must exist
        lookup(store.clients, client_id, "ClientAccount")
        lookup(store.jurisdictions, jurisdiction_id, "Jurisdiction")
        # asset_tag unique per client
        for a in store.assets.values():
            if a["client_id"] == client_id and a["asset_tag"] == asset_tag:
                E.raise_err(E.ERR_INVALID_REQUEST, "asset_tag must be unique per client")
        a = {
            "client_id": client_id,
            "jurisdiction_id": jurisdiction_id,
            "asset_tag": asset_tag,
            "category": category,
            "acquisition_cost_cents": cost,
            "acquisition_date": acq,
            "in_service_date": in_service,
            "lifecycle_status": "ACTIVE",
            "classification_status": "UNCLASSIFIED",
            "taxable_classification": None,
            "disposed_date": None,
            "disposal_proceeds_cents": None,
        }
        stamp_new(store, a)
        store.assets[a["id"]] = a
        return created(asset_view(a))

    # ------------------------------------------------------------------
    # GET /bpp/assets/<asset_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/assets/<asset_id>")
    def get_asset(asset_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        a = lookup(store.assets, asset_id, "Asset")
        return ok(asset_view(a))

    # ------------------------------------------------------------------
    # GET /bpp/assets
    # ------------------------------------------------------------------
    @app.get("/bpp/assets")
    def list_assets():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        limit, offset = parse_pagination()
        items = list(store.assets.values())
        cid = request.args.get("client_id")
        if cid is not None:
            items = [a for a in items if a["client_id"] == cid]
        jid = request.args.get("jurisdiction_id")
        if jid is not None:
            items = [a for a in items if a["jurisdiction_id"] == jid]
        ls = request.args.get("lifecycle_status")
        if ls is not None:
            items = [a for a in items if a["lifecycle_status"] == ls]
        cs = request.args.get("classification_status")
        if cs is not None:
            items = [a for a in items if a["classification_status"] == cs]
        include_disposed = request.args.get("include_disposed")
        if include_disposed is None or include_disposed.lower() not in ("true", "1", "yes"):
            items = [a for a in items if a["lifecycle_status"] != "DISPOSED"]
        items.sort(key=lambda a: a["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([asset_view(a) for a in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/assets/<asset_id>/classify
    # ------------------------------------------------------------------
    @app.post("/bpp/assets/<asset_id>/classify")
    def classify_asset(asset_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        a = lookup(store.assets, asset_id, "Asset")
        body = get_body()
        classification = req_enum(body, "taxable_classification", CLASSIFICATION_VALUES)
        # state gate (priority 5)
        if a["lifecycle_status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Cannot classify a DISPOSED asset")
        # class rule coverage (priority 13)
        rule = find_class_rule(store, a["jurisdiction_id"], a["category"])
        if rule is None:
            E.raise_err(E.ERR_CLASS_RULE_MISSING, "No class rule for this jurisdiction/category")
        proposal = rule_proposal(rule)
        a["classification_status"] = "CLASSIFIED" if classification == proposal else "OVERRIDDEN"
        a["taxable_classification"] = classification
        touch(a)
        # downstream effect: recompute lines on DRAFT/AMENDMENT_OPEN renditions
        reclassify_line_refresh(store, a)
        return ok(asset_view(a))

    # ------------------------------------------------------------------
    # POST /bpp/assets/<asset_id>/disposals
    # ------------------------------------------------------------------
    @app.post("/bpp/assets/<asset_id>/disposals")
    def record_disposal(asset_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        a = lookup(store.assets, asset_id, "Asset")
        body = get_body()
        disposal_date = parse_date_field(body, "disposal_date")
        proceeds = req_int(body, "disposal_proceeds_cents", min_v=0)
        # state gate (priority 5): lifecycle must be ACTIVE
        if a["lifecycle_status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Asset is not ACTIVE")
        # disposal date sanity (priority 17)
        if disposal_date < a["acquisition_date"] or disposal_date > store.clock_date():
            E.raise_err(E.ERR_INVALID_DISPOSAL_DATE, "disposal_date outside the allowed window")

        rec = {
            "asset_id": a["id"],
            "disposal_date": disposal_date,
            "disposal_proceeds_cents": proceeds,
            "disposal_status": "RECORDED",
        }
        stamp_new(store, rec)
        store.disposals[rec["id"]] = rec

        # Link 1: asset -> DISPOSED
        a["lifecycle_status"] = "DISPOSED"
        a["disposed_date"] = disposal_date
        a["disposal_proceeds_cents"] = proceeds
        touch(a)

        # Link 2: exclude lines on DRAFT/AMENDMENT_OPEN renditions whose lien
        # date is strictly after the disposal date
        touched_renditions = set()
        for r in store.renditions.values():
            if r["rendition_status"] not in ("DRAFT", "AMENDMENT_OPEN"):
                continue
            if r["client_id"] != a["client_id"] or r["jurisdiction_id"] != a["jurisdiction_id"]:
                continue
            if lien_date(r["tax_year"]) <= disposal_date:
                continue
            for line in r["lines"]:
                if line["asset_id"] == a["id"] and line["included"]:
                    line["included"] = False
                    line["exclusion_reason"] = "DISPOSED"
                    touched_renditions.add(r["id"])
        # Link 3: recompute touched rendition totals + version bump
        for rid in touched_renditions:
            r = store.renditions[rid]
            recompute_rendition_total(r)
            touch(r)

        # Link 4: flag published forecasts whose tax year's lien date is
        # strictly after the disposal date
        fy_years = {
            f["tax_year"]
            for f in store.forecasts.values()
            if f["client_id"] == a["client_id"]
            and f["forecast_status"] == "PUBLISHED"
            and lien_date(f["tax_year"]) > disposal_date
        }
        flag_forecasts_force(store, a["client_id"], fy_years, caller.user_id)

        append_audit(store, a["client_id"], "DISPOSAL_RECORDED",
                     f"Disposal {rec['id']} recorded for asset {a['id']}", caller.user_id)
        return created(disposal_view(rec))

    # ------------------------------------------------------------------
    # GET /bpp/assets/<asset_id>/disposals
    # ------------------------------------------------------------------
    @app.get("/bpp/assets/<asset_id>/disposals")
    def list_disposals(asset_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        lookup(store.assets, asset_id, "Asset")
        limit, offset = parse_pagination()
        items = [d for d in store.disposals.values() if d["asset_id"] == asset_id]
        ds = request.args.get("disposal_status")
        if ds is not None:
            items = [d for d in items if d["disposal_status"] == ds]
        items.sort(key=lambda d: d["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([disposal_view(d) for d in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/disposals/<disposal_id>/reverse
    # ------------------------------------------------------------------
    @app.post("/bpp/disposals/<disposal_id>/reverse")
    def reverse_disposal(disposal_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        rec = lookup(store.disposals, disposal_id, "DisposalRecord")
        # state gate (priority 5)
        if rec["disposal_status"] != "RECORDED":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Only a RECORDED disposal may be reversed")
        a = store.assets.get(rec["asset_id"])
        if a is None:
            E.raise_err(E.ERR_NOT_FOUND, f"Asset not found: {rec['asset_id']}")

        rec["disposal_status"] = "REVERSED"
        touch(rec)

        # Asset DISPOSED -> ACTIVE
        a["lifecycle_status"] = "ACTIVE"
        a["disposed_date"] = None
        a["disposal_proceeds_cents"] = None
        touch(a)

        # Reinstate lines excluded for DISPOSED on DRAFT/AMENDMENT_OPEN renditions
        touched = set()
        for r in store.renditions.values():
            if r["rendition_status"] not in ("DRAFT", "AMENDMENT_OPEN"):
                continue
            if r["client_id"] != a["client_id"] or r["jurisdiction_id"] != a["jurisdiction_id"]:
                continue
            hit = False
            for line in r["lines"]:
                if (
                    line["asset_id"] == a["id"]
                    and not line["included"]
                    and line["exclusion_reason"] == "DISPOSED"
                ):
                    hit = True
            if hit:
                # full regeneration recomputes values and inclusion cleanly
                generate_rendition_lines(store, r)  # touches rendition too
                touched.add(r["id"])

        # Forecasts flagged by the original disposal keep needs_regeneration;
        # reversal never clears the flag — nothing to do here.

        append_audit(store, a["client_id"], "DISPOSAL_REVERSED",
                     f"Disposal {rec['id']} reversed for asset {a['id']}", caller.user_id)
        return ok(disposal_view(rec))
