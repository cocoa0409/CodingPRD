"""Routes: renditions, filing, amendments, extensions (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_str, req_int, req_enum, lookup, stamp_new, touch,
    parse_date_field, append_audit,
)
from services import (
    base_deadline_date, lien_date, generate_rendition_lines,
    compute_lateness, flag_forecasts, flag_forecasts_force,
    flag_forecasts_uncovered, latest_recorded_disposal,
)
from serializers import rendition_view, extension_view

bp = Blueprint("renditions", __name__)


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/renditions
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions")
    def create_rendition():
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        body = get_body()
        client_id = req_str(body, "client_id")
        jurisdiction_id = req_str(body, "jurisdiction_id")
        tax_year = req_int(body, "tax_year")
        lookup(store.clients, client_id, "ClientAccount")
        jurisdiction = lookup(store.jurisdictions, jurisdiction_id, "Jurisdiction")
        # uniqueness (priority 18)
        for r in store.renditions.values():
            if (
                r["client_id"] == client_id
                and r["jurisdiction_id"] == jurisdiction_id
                and r["tax_year"] == tax_year
            ):
                E.raise_err(E.ERR_DUPLICATE_RENDITION,
                            "A rendition already exists for this client, jurisdiction, and tax year")
        r = {
            "client_id": client_id,
            "jurisdiction_id": jurisdiction_id,
            "tax_year": tax_year,
            "rendition_status": "DRAFT",
            "lines": [],
            "total_assessed_value_cents": 0,
            "deadline_date": base_deadline_date(jurisdiction, tax_year),
            "is_late_filing": False,
            "late_days": 0,
            "late_penalty_months": 0,
            "late_penalty_cents": 0,
            "filed_at": None,
            "filed_by_operator_id": None,
            "amendment_opened_by_operator_id": None,
            # filed snapshot for amendment withdraw
            "_filed_snapshot": None,
            "_lines_generated": False,
        }
        stamp_new(store, r)
        store.renditions[r["id"]] = r
        return created(rendition_view(r))

    # ------------------------------------------------------------------
    # GET /bpp/renditions/<rendition_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/renditions/<rendition_id>")
    def get_rendition(rendition_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        r = lookup(store.renditions, rendition_id, "Rendition")
        return ok(rendition_view(r))

    # ------------------------------------------------------------------
    # GET /bpp/renditions
    # ------------------------------------------------------------------
    @app.get("/bpp/renditions")
    def list_renditions():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        limit, offset = parse_pagination()
        items = list(store.renditions.values())
        cid = request.args.get("client_id")
        if cid is not None:
            items = [r for r in items if r["client_id"] == cid]
        jid = request.args.get("jurisdiction_id")
        if jid is not None:
            items = [r for r in items if r["jurisdiction_id"] == jid]
        ty = request.args.get("tax_year")
        if ty is not None:
            try:
                tyi = int(ty)
            except ValueError:
                E.raise_err(E.ERR_INVALID_REQUEST, "tax_year must be an integer")
            items = [r for r in items if r["tax_year"] == tyi]
        rs = request.args.get("rendition_status")
        if rs is not None:
            items = [r for r in items if r["rendition_status"] == rs]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([rendition_view(r) for r in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/renditions/<rendition_id>/generate-lines
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions/<rendition_id>/generate-lines")
    def generate_lines(rendition_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        r = lookup(store.renditions, rendition_id, "Rendition")
        # state gate (priority 7)
        if r["rendition_status"] not in ("DRAFT", "AMENDMENT_OPEN"):
            E.raise_err(E.ERR_AMENDMENT_STATE_MISMATCH,
                        "generate-lines requires DRAFT or AMENDMENT_OPEN")
        generate_rendition_lines(store, r)
        r["_lines_generated"] = True
        return ok(rendition_view(r))

    # ------------------------------------------------------------------
    # POST /bpp/renditions/<rendition_id>/file
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions/<rendition_id>/file")
    def file_rendition(rendition_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst", "SeniorManager")
        r = lookup(store.renditions, rendition_id, "Rendition")
        get_body()  # body optional; must be well-formed if present

        # state gates (priorities 6/7): FILED without open amendment -> error
        if r["rendition_status"] == "FILED":
            E.raise_err(E.ERR_RENDITION_ALREADY_FILED, "Rendition already filed")
        if r["rendition_status"] not in ("DRAFT", "AMENDMENT_OPEN"):
            # ACCEPTED or other states
            E.raise_err(E.ERR_RENDITION_ALREADY_FILED, "Rendition cannot be filed from its current state")
        was_amendment_refiling = r["rendition_status"] == "AMENDMENT_OPEN"

        # priority 20: filing completeness — in-scope ACTIVE assets classified
        lien = lien_date(r["tax_year"])
        for a in store.assets.values():
            if (
                a["client_id"] == r["client_id"]
                and a["jurisdiction_id"] == r["jurisdiction_id"]
                and a["lifecycle_status"] == "ACTIVE"
                and a["acquisition_date"] < lien
                and a["classification_status"] not in ("CLASSIFIED", "OVERRIDDEN")
            ):
                E.raise_err(E.ERR_UNCLASSIFIED_ASSETS,
                            f"Asset {a['id']} is not classified")

        # priority 21: at least one included line; lines must have been generated
        if not r["_lines_generated"] or not any(l["included"] for l in r["lines"]):
            E.raise_err(E.ERR_EMPTY_RENDITION, "Rendition has no included lines")

        filed_date = store.clock_date()
        compute_lateness(store, r, filed_date)
        r["rendition_status"] = "FILED"
        r["filed_at"] = store.clock_iso()
        r["filed_by_operator_id"] = caller.user_id
        r["amendment_opened_by_operator_id"] = None

        # Capture filed snapshot (for amendment withdraw)
        r["_filed_snapshot"] = {
            "lines": [dict(l) for l in r["lines"]],
            "total_assessed_value_cents": r["total_assessed_value_cents"],
            "is_late_filing": r["is_late_filing"],
            "late_days": r["late_days"],
            "late_penalty_months": r["late_penalty_months"],
            "late_penalty_cents": r["late_penalty_cents"],
        }

        # Mark RECORDED disposals of lien-excluded assets RECONCILED
        excluded_disposed_asset_ids = {
            l["asset_id"] for l in r["lines"]
            if not l["included"] and l["exclusion_reason"] == "DISPOSED"
        }
        for asset_id in excluded_disposed_asset_ids:
            d = latest_recorded_disposal(store, asset_id)
            if (
                d is not None
                and d["disposal_status"] == "RECORDED"
                and d["disposal_date"] < lien
            ):
                d["disposal_status"] = "RECONCILED"
                touch(d)
                append_audit(store, r["client_id"], "DISPOSAL_RECONCILED",
                             f"Disposal {d['id']} reconciled", "system")

        touch(r)

        # Flag published forecasts for (client, tax_year). A first filing only
        # flags forecasts that do not already cover this rendition; a re-file
        # of an open amendment flags all published forecasts for the pair.
        if was_amendment_refiling:
            flag_forecasts_force(store, r["client_id"], {r["tax_year"]}, caller.user_id)
        else:
            flag_forecasts_uncovered(store, r["client_id"], r["tax_year"], r["id"], caller.user_id)

        append_audit(store, r["client_id"], "RENDITION_FILED",
                     f"Rendition {r['id']} filed", caller.user_id)
        return ok(rendition_view(r))

    # ------------------------------------------------------------------
    # POST /bpp/renditions/<rendition_id>/amendments
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions/<rendition_id>/amendments")
    def amendment(rendition_id):
        caller = get_caller(store)
        require_role(caller, "SeniorManager")
        r = lookup(store.renditions, rendition_id, "Rendition")
        body = get_body()
        action = req_enum(body, "action", {"OPEN", "WITHDRAW"})

        # state gate (priority 7)
        if action == "OPEN" and r["rendition_status"] != "FILED":
            E.raise_err(E.ERR_AMENDMENT_STATE_MISMATCH, "OPEN requires FILED")
        if action == "WITHDRAW" and r["rendition_status"] != "AMENDMENT_OPEN":
            E.raise_err(E.ERR_AMENDMENT_STATE_MISMATCH, "WITHDRAW requires AMENDMENT_OPEN")

        # segregation of duties (priority 11)
        if caller.user_id == r["filed_by_operator_id"]:
            E.raise_err(E.ERR_SEGREGATION_OF_DUTIES,
                        "The operator who filed the rendition may not open or withdraw its amendment")

        if action == "OPEN":
            r["rendition_status"] = "AMENDMENT_OPEN"
            r["amendment_opened_by_operator_id"] = caller.user_id
            touch(r)
            append_audit(store, r["client_id"], "AMENDMENT_OPENED",
                         f"Amendment opened on rendition {r['id']}", caller.user_id)
        else:  # WITHDRAW
            snap = r["_filed_snapshot"]
            if snap is not None:
                r["lines"] = [dict(l) for l in snap["lines"]]
                r["total_assessed_value_cents"] = snap["total_assessed_value_cents"]
                r["is_late_filing"] = snap["is_late_filing"]
                r["late_days"] = snap["late_days"]
                r["late_penalty_months"] = snap["late_penalty_months"]
                r["late_penalty_cents"] = snap["late_penalty_cents"]
            r["rendition_status"] = "FILED"
            r["amendment_opened_by_operator_id"] = None
            touch(r)
            append_audit(store, r["client_id"], "AMENDMENT_WITHDRAWN",
                         f"Amendment withdrawn on rendition {r['id']}", caller.user_id)
        return ok(rendition_view(r))

    # ------------------------------------------------------------------
    # POST /bpp/renditions/<rendition_id>/extensions
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions/<rendition_id>/extensions")
    def request_extension(rendition_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        r = lookup(store.renditions, rendition_id, "Rendition")
        body = get_body()
        requested = parse_date_field(body, "requested_extend_to_date")
        if "expected_rendition_version" not in body or body["expected_rendition_version"] is None:
            E.raise_err(E.ERR_INVALID_REQUEST, "expected_rendition_version is required")
        expected = body["expected_rendition_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            E.raise_err(E.ERR_INVALID_REQUEST, "expected_rendition_version must be an integer")

        # state gate (priority 6): extension requires DRAFT
        if r["rendition_status"] != "DRAFT":
            E.raise_err(E.ERR_RENDITION_ALREADY_FILED,
                        "Extensions may only be requested on a DRAFT rendition")

        # OCC (priority 12) before window/ceiling checks
        if expected != r["version"]:
            E.raise_err(E.ERR_STALE_VERSION, "Stale rendition version")

        # extension window (priority 16)
        if store.clock_date() > r["deadline_date"]:
            E.raise_err(E.ERR_EXTENSION_WINDOW_CLOSED,
                        "The rendition's effective deadline has passed")

        # extension ceiling (priority 24)
        jurisdiction = store.jurisdictions[r["jurisdiction_id"]]
        base = base_deadline_date(jurisdiction, r["tax_year"])
        if requested > base + timedelta(days=jurisdiction["max_extension_days"]):
            E.raise_err(E.ERR_EXTENSION_EXCEEDS_MAX,
                        "Requested date exceeds the extension ceiling")

        # Grant immediately
        ext = {
            "rendition_id": r["id"],
            "requested_extend_to_date": requested,
            "granted_days": (requested - base).days,
            "extension_status": "GRANTED",
        }
        stamp_new(store, ext)
        store.extensions[ext["id"]] = ext

        # Supersede prior GRANTED extension
        for other in store.extensions.values():
            if (
                other["id"] != ext["id"]
                and other["rendition_id"] == r["id"]
                and other["extension_status"] == "GRANTED"
            ):
                other["extension_status"] = "SUPERSEDED"
                touch(other)
                append_audit(store, r["client_id"], "EXTENSION_SUPERSEDED",
                             f"Extension {other['id']} superseded", caller.user_id)

        r["deadline_date"] = requested
        r["version"] += 1
        r["updated_at"] = store.now_iso()

        append_audit(store, r["client_id"], "EXTENSION_GRANTED",
                     f"Extension {ext['id']} granted for rendition {r['id']}", caller.user_id)
        return created(extension_view(ext))

    # ------------------------------------------------------------------
    # GET /bpp/renditions/<rendition_id>/extensions
    # ------------------------------------------------------------------
    @app.get("/bpp/renditions/<rendition_id>/extensions")
    def list_extensions(rendition_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        lookup(store.renditions, rendition_id, "Rendition")
        limit, offset = parse_pagination()
        items = [e for e in store.extensions.values() if e["rendition_id"] == rendition_id]
        es = request.args.get("extension_status")
        if es is not None:
            items = [e for e in items if e["extension_status"] == es]
        items.sort(key=lambda e: e["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([extension_view(e) for e in page], total, limit, offset)
