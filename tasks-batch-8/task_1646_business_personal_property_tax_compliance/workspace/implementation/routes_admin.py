"""Routes: clients, operators, jurisdictions, class rules, clock."""

import re

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_str, req_int, req_number, req_enum, lookup, stamp_new, touch,
    parse_date_field, parse_iso_datetime, append_audit,
)
from services import (
    compute_forecast, flag_forecasts, run_clock_sweeps,
)
from serializers import (
    client_view, operator_view, jurisdiction_view, class_rule_view,
    forecast_view, audit_event_view,
)

bp = Blueprint("admin", __name__)

MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
EXEMPTION_TYPE_VALUES = {"FREEPORT", "POLLUTION_CONTROL", "HISTORIC"}
PENALTY_BASE_VALUES = {"VALUE_BASE", "TAX_BASE"}
OPERATOR_ROLE_VALUES = {"TAX_ANALYST", "SENIOR_MANAGER"}
FORECAST_VARIANT_VALUES = {"NOTICE_BASED", "RENDERED_CONSERVATIVE"}


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/clients
    # ------------------------------------------------------------------
    @app.post("/bpp/clients")
    def create_client():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin")
        body = get_body()
        legal_name = req_str(body, "legal_name")
        contact_email = req_str(body, "contact_email")
        c = {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "forecast_sequence": 0,
        }
        stamp_new(store, c)
        store.clients[c["id"]] = c
        return created(client_view(c))

    # ------------------------------------------------------------------
    # GET /bpp/clients/<client_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/clients/<client_id>")
    def get_client(client_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        c = lookup(store.clients, client_id, "ClientAccount")
        return ok(client_view(c))

    # ------------------------------------------------------------------
    # GET /bpp/clients/<client_id>/accrual-forecasts
    # ------------------------------------------------------------------
    @app.get("/bpp/clients/<client_id>/accrual-forecasts")
    def list_client_forecasts(client_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        lookup(store.clients, client_id, "ClientAccount")
        limit, offset = parse_pagination()
        items = [f for f in store.forecasts.values() if f["client_id"] == client_id]
        tax_year = request.args.get("tax_year")
        if tax_year is not None:
            try:
                ty = int(tax_year)
            except ValueError:
                E.raise_err(E.ERR_INVALID_REQUEST, "tax_year must be an integer")
            items = [f for f in items if f["tax_year"] == ty]
        variant = request.args.get("variant")
        if variant is not None:
            items = [f for f in items if f["variant"] == variant]
        fstatus = request.args.get("forecast_status")
        if fstatus is not None:
            items = [f for f in items if f["forecast_status"] == fstatus]
        items.sort(key=lambda f: f["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([forecast_view(f) for f in page], total, limit, offset)

    # ------------------------------------------------------------------
    # GET /bpp/clients/<client_id>/audit-events
    # ------------------------------------------------------------------
    @app.get("/bpp/clients/<client_id>/audit-events")
    def list_audit_events(client_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        lookup(store.clients, client_id, "ClientAccount")
        limit, offset = parse_pagination()
        items = [e for e in store.audit_events.values() if e["client_id"] == client_id]
        et = request.args.get("event_type")
        if et is not None:
            items = [e for e in items if e["event_type"] == et]
        items.sort(key=lambda e: e["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([audit_event_view(e) for e in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/clients/<client_id>/accrual-forecasts
    # ------------------------------------------------------------------
    @app.post("/bpp/clients/<client_id>/accrual-forecasts")
    def publish_forecast(client_id):
        caller = get_caller(store)
        require_role(caller, "SeniorManager")
        client = lookup(store.clients, client_id, "ClientAccount")
        body = get_body()
        tax_year = req_int(body, "tax_year")
        variant = req_enum(body, "variant", FORECAST_VARIANT_VALUES)
        as_of = parse_date_field(body, "as_of_date")
        if "expected_client_version" not in body or body["expected_client_version"] is None:
            E.raise_err(E.ERR_INVALID_REQUEST, "expected_client_version is required")
        expected = body["expected_client_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            E.raise_err(E.ERR_INVALID_REQUEST, "expected_client_version must be an integer")
        # OCC (priority 12) before business rules (priority 26)
        if expected != client["version"]:
            E.raise_err(E.ERR_STALE_VERSION, "Stale client version")
        from datetime import date as _date
        if as_of < _date(tax_year, 1, 1):
            E.raise_err(E.ERR_FORECAST_INPUT_INVALID, "as_of_date before Jan 1 of tax_year")

        liability, component_count, covered_ids = compute_forecast(store, client_id, tax_year, variant)

        # Supersede prior PUBLISHED forecast for (client, tax_year)
        for f in store.forecasts.values():
            if (
                f["client_id"] == client_id
                and f["tax_year"] == tax_year
                and f["forecast_status"] == "PUBLISHED"
            ):
                f["forecast_status"] = "SUPERSEDED"
                touch(f)

        fc = {
            "client_id": client_id,
            "tax_year": tax_year,
            "variant": variant,
            "as_of_date": as_of,
            "forecasted_liability_cents": liability,
            "component_count": component_count,
            "forecast_status": "PUBLISHED",
            "needs_regeneration": False,
            "published_by_operator_id": caller.user_id,
            # publish-time input set, used by the DRAFT->FILED
            # "not already covering this rendition" flagging rule
            "_covered_rendition_ids": covered_ids,
        }
        stamp_new(store, fc)
        store.forecasts[fc["id"]] = fc

        client["version"] += 1
        client["updated_at"] = store.now_iso()
        client["forecast_sequence"] += 1

        append_audit(store, client_id, "FORECAST_PUBLISHED",
                     f"Accrual forecast {fc['id']} published", caller.user_id)
        return created(forecast_view(fc))

    # ------------------------------------------------------------------
    # POST /bpp/operators
    # ------------------------------------------------------------------
    @app.post("/bpp/operators")
    def create_operator():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin")
        body = get_body()
        display_name = req_str(body, "display_name")
        op_role = req_enum(body, "operator_role", OPERATOR_ROLE_VALUES)
        o = {"display_name": display_name, "operator_role": op_role}
        stamp_new(store, o)
        store.operators[o["id"]] = o
        return created(operator_view(o))

    # ------------------------------------------------------------------
    # POST /bpp/jurisdictions
    # ------------------------------------------------------------------
    @app.post("/bpp/jurisdictions")
    def create_jurisdiction():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin")
        body = get_body()
        county_name = req_str(body, "county_name")
        state_code = req_str(body, "state_code")
        mmdd = req_str(body, "base_deadline_mmdd")
        if not MMDD_RE.match(mmdd):
            E.raise_err(E.ERR_INVALID_REQUEST, "base_deadline_mmdd must match MM-DD")
        max_extension_days = req_int(body, "max_extension_days", min_v=0)
        late_pct = req_int(body, "late_penalty_pct_per_month", min_v=0)
        max_late_pct = req_int(body, "max_late_penalty_pct", min_v=0)
        penalty_base = req_enum(body, "penalty_base", PENALTY_BASE_VALUES)
        tax_rate = req_number(body, "tax_rate")
        offered = body.get("offered_exemption_types")
        if offered is None or not isinstance(offered, list):
            E.raise_err(E.ERR_INVALID_REQUEST, "offered_exemption_types must be an array")
        for t in offered:
            if t not in EXEMPTION_TYPE_VALUES:
                E.raise_err(E.ERR_INVALID_REQUEST, f"Invalid exemption type: {t}")
        max_exemption_pct = req_int(body, "max_exemption_pct", min_v=0, max_v=100)
        j = {
            "county_name": county_name,
            "state_code": state_code,
            "base_deadline_mmdd": mmdd,
            "max_extension_days": max_extension_days,
            "late_penalty_pct_per_month": late_pct,
            "max_late_penalty_pct": max_late_pct,
            "penalty_base": penalty_base,
            "tax_rate": tax_rate,
            "offered_exemption_types": offered,
            "max_exemption_pct": max_exemption_pct,
        }
        stamp_new(store, j)
        store.jurisdictions[j["id"]] = j
        return created(jurisdiction_view(j))

    # ------------------------------------------------------------------
    # GET /bpp/jurisdictions/<jurisdiction_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/jurisdictions/<jurisdiction_id>")
    def get_jurisdiction(jurisdiction_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        j = lookup(store.jurisdictions, jurisdiction_id, "Jurisdiction")
        return ok(jurisdiction_view(j))

    # ------------------------------------------------------------------
    # POST /bpp/class-rules
    # ------------------------------------------------------------------
    @app.post("/bpp/class-rules")
    def create_class_rule():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin")
        body = get_body()
        jurisdiction_id = req_str(body, "jurisdiction_id")
        category = req_enum(body, "category", {
            "MACHINERY", "FURNITURE", "COMPUTER", "VEHICLE", "INVENTORY",
            "LEASEHOLD_IMPROVEMENT",
        })
        is_taxable = body.get("is_taxable")
        if is_taxable is None or not isinstance(is_taxable, bool):
            E.raise_err(E.ERR_INVALID_REQUEST, "is_taxable must be a boolean")
        convention = req_enum(body, "depreciation_convention", {"FULL_YEAR", "HALF_YEAR"})
        vector = body.get("percent_good_vector")
        if vector is None or not isinstance(vector, list) or not vector:
            E.raise_err(E.ERR_INVALID_REQUEST, "percent_good_vector must be a non-empty array")
        for v in vector:
            if isinstance(v, bool) or not isinstance(v, int):
                E.raise_err(E.ERR_INVALID_REQUEST, "percent_good_vector entries must be integers")
        floor_pct = req_int(body, "percent_good_floor_pct", min_v=0)
        de_minimis = req_int(body, "de_minimis_line_cents", min_v=0)
        # existence of the referenced jurisdiction
        lookup(store.jurisdictions, jurisdiction_id, "Jurisdiction")
        # duplicate check (priority 19)
        for r in store.class_rules.values():
            if r["jurisdiction_id"] == jurisdiction_id and r["category"] == category:
                E.raise_err(E.ERR_DUPLICATE_CLASS_RULE,
                            "A class rule already exists for this jurisdiction and category")
        rule = {
            "jurisdiction_id": jurisdiction_id,
            "category": category,
            "is_taxable": is_taxable,
            "depreciation_convention": convention,
            "percent_good_vector": vector,
            "percent_good_floor_pct": floor_pct,
            "de_minimis_line_cents": de_minimis,
        }
        stamp_new(store, rule)
        store.class_rules[rule["id"]] = rule
        return created(class_rule_view(rule))

    # ------------------------------------------------------------------
    # GET /bpp/jurisdictions/<jurisdiction_id>/class-rules
    # ------------------------------------------------------------------
    @app.get("/bpp/jurisdictions/<jurisdiction_id>/class-rules")
    def list_class_rules(jurisdiction_id):
        caller = get_caller(store)
        require_role(caller, "FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")
        lookup(store.jurisdictions, jurisdiction_id, "Jurisdiction")
        limit, offset = parse_pagination()
        items = [r for r in store.class_rules.values() if r["jurisdiction_id"] == jurisdiction_id]
        cat = request.args.get("category")
        if cat is not None:
            items = [r for r in items if r["category"] == cat]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([class_rule_view(r) for r in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/_clock/set-current-utc
    # ------------------------------------------------------------------
    @app.post("/bpp/_clock/set-current-utc")
    def set_clock():
        caller = get_caller(store)
        require_role(caller, "FirmAdmin")
        body = get_body()
        raw = body.get("to_iso8601")
        if raw is None:
            E.raise_err(E.ERR_INVALID_REQUEST, "to_iso8601 is required")
        target = parse_iso_datetime(raw)
        if target <= store.clock:
            E.raise_err(E.ERR_CLOCK_MONOTONIC, "Clock target must be strictly after the current value")
        store.clock = target
        run_clock_sweeps(store)
        return ok({})
