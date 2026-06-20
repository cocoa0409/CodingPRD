"""Genetic & Molecular Testing Lab API — Flask entry point.

In-memory only; no seeding at startup. The store is created fresh on every
process boot (db.store), so start.sh re-invocation wipes all state.
"""
import os

from flask import Flask, request

import serializers as S
from calculations import (
    counselor_slots_conflict,
    incidental_admitted,
    patient_age_years,
    patient_responsibility_estimate,
    patient_responsibility_final,
    pathogenicity_risk_index,
    qns_sufficient,
    sequencer_runs_conflict,
)
from common import (
    ALL_ROLES,
    get_json_body,
    paginate,
    parse_iso,
    require_bool,
    require_enum,
    require_fields,
    require_iso,
    require_non_negative_int,
    require_number,
    require_role,
    require_string,
    require_user_context,
)
from db import new_id, store
from errors import ApiError, err
from response import error_response, success

app = Flask(__name__)

# Enums used in validation
INSURANCE_PAYERS = {"MEDICARE", "COMMERCIAL", "SELF_PAY"}
SPECIMEN_TYPES = {"BLOOD", "SALIVA", "TISSUE"}
ACMG_TIERS = {"BENIGN", "LIKELY_BENIGN", "VUS", "LIKELY_PATHOGENIC", "PATHOGENIC"}
REFERRAL_REASONS = {"PATHOGENIC_RESULT", "VUS_FOLLOWUP", "INCIDENTAL_FINDING", "PATIENT_REQUEST"}
AUTH_DECISIONS = {"APPROVED", "DENIED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found."), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed."), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", str(e)), 422


# ---------------------------------------------------------------------------
# Lookup helpers (raise resource-specific not-found errors)
# ---------------------------------------------------------------------------
def get_order(order_id):
    o = store.test_orders.get(order_id)
    if o is None:
        raise err("ERR_ORDER_NOT_FOUND", "Test order not found.")
    return o


def get_panel(panel_id):
    p = store.panels.get(panel_id)
    if p is None:
        raise err("ERR_PANEL_NOT_FOUND", "Panel not found.")
    return p


def get_gene(gene_id):
    g = store.genes.get(gene_id)
    if g is None:
        raise err("ERR_GENE_NOT_FOUND", "Gene not found.")
    return g


def get_provider(provider_id):
    p = store.providers.get(provider_id)
    if p is None:
        raise err("ERR_PROVIDER_NOT_FOUND", "Provider not found.")
    return p


def get_panel_gene(pg_id):
    pg = store.panel_genes.get(pg_id)
    if pg is None:
        raise err("ERR_PANEL_GENE_NOT_FOUND", "Panel-gene membership not found.")
    return pg


def get_consent(consent_id):
    c = store.consents.get(consent_id)
    if c is None:
        raise err("ERR_CONSENT_NOT_FOUND", "Consent not found.")
    return c


def get_specimen(specimen_id):
    s = store.specimens.get(specimen_id)
    if s is None:
        raise err("ERR_SPECIMEN_NOT_FOUND", "Specimen not found.")
    return s


def get_variant(variant_id):
    v = store.variants.get(variant_id)
    if v is None:
        raise err("ERR_VARIANT_NOT_FOUND", "Variant not found.")
    return v


def get_report(report_id):
    r = store.reports.get(report_id)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", "Report not found.")
    return r


def get_requisition(requisition_id):
    r = store.requisitions.get(requisition_id)
    if r is None:
        raise err("ERR_REQUISITION_NOT_FOUND", "Requisition not found.")
    return r


def get_billing_by_id(billing_id):
    b = store.billings.get(billing_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "Billing record not found.")
    return b


def get_sequencer(sequencer_id):
    s = store.sequencers.get(sequencer_id)
    if s is None:
        raise err("ERR_SEQUENCER_NOT_FOUND", "Sequencer not found.")
    return s


def get_run(run_id):
    r = store.sequencer_runs.get(run_id)
    if r is None:
        raise err("ERR_RUN_NOT_FOUND", "Sequencer run not found.")
    return r


def get_counselor(counselor_id):
    c = store.counselors.get(counselor_id)
    if c is None:
        raise err("ERR_COUNSELOR_NOT_FOUND", "Counselor profile not found.")
    return c


def get_referral(referral_id):
    r = store.referrals.get(referral_id)
    if r is None:
        raise err("ERR_REFERRAL_NOT_FOUND", "Referral not found.")
    return r


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def billing_for_order(order_id):
    for b in store.billings.values():
        if b["test_order_id"] == order_id:
            return b
    return None


def requisition_for_order(order_id):
    for r in store.requisitions.values():
        if r["test_order_id"] == order_id:
            return r
    return None


def order_variants(order_id):
    return [v for v in store.variants.values() if v["test_order_id"] == order_id]


def panel_included_gene_ids(panel_id):
    return {
        pg["gene_id"]
        for pg in store.panel_genes.values()
        if pg["panel_id"] == panel_id and pg["status"] == "INCLUDED"
    }


def recompute_gene_count(panel):
    panel["gene_count"] = sum(
        1
        for pg in store.panel_genes.values()
        if pg["panel_id"] == panel["id"] and pg["status"] == "INCLUDED"
    )


def order_payer(order):
    req = requisition_for_order(order["id"])
    return req["insurance_payer"] if req else None


def recompute_estimate(order, billing):
    """Recompute estimated_patient_responsibility_cents (PRD 3.7 estimate).

    PRD 3.6 says the estimate is computed in either fork at requisition submit.
    For a non-self-pay order the payer-allowed amount is not yet known
    (allowed_amount_cents is None until the auth decision), so the base is taken
    as 0 — yielding a defined estimate of 0 cents that is recomputed once the
    auth is approved.
    """
    payer = order_payer(order)
    if payer is None:
        return
    base = billing.get("allowed_amount_cents")
    if base is None:
        base = 0
    order["estimated_patient_responsibility_cents"] = patient_responsibility_estimate(base, payer)


def classified_variants_sorted(order_id):
    """Variants with classification not in {UNCLASSIFIED, RECLASSIFIED}, ordered
    by created_at ASC then id (PRD 3.10 / 3.8)."""
    vs = [
        v for v in order_variants(order_id)
        if v.get("classification") not in ("UNCLASSIFIED", "RECLASSIFIED")
    ]
    vs.sort(key=lambda v: (v.get("created_at", ""), v.get("id", "")))
    return vs


def recompute_pathogenicity(order):
    """Recompute the order's pathogenicity risk index (PRD 3.10)."""
    panel = store.panels.get(order["panel_id"])
    gene_count = panel.get("gene_count", 0) if panel else 0
    vs = classified_variants_sorted(order["id"])
    order["_risk_index"] = pathogenicity_risk_index(vs, gene_count)


def reportability_selection(order):
    """PRD 3.8: select reportable variant ids and decide incidental disclosure.

    Returns (reportable_variant_ids, incidental_disclosed).
    """
    candidates = classified_variants_sorted(order["id"])
    primary = [
        v for v in candidates
        if not v.get("is_incidental")
        and v.get("classification") in ("VUS", "LIKELY_PATHOGENIC", "PATHOGENIC")
    ]
    # incidental policy inputs
    consent_opt_in = False
    signed_consent = None
    for c in store.consents.values():
        if c["test_order_id"] == order["id"] and c["status"] == "SIGNED":
            signed_consent = c
            break
    if signed_consent is not None:
        consent_opt_in = bool(signed_consent.get("incidental_findings_opt_in"))
    age = patient_age_years(order.get("patient_dob"), store.now())

    admitted_incidental = []
    for v in candidates:
        if not v.get("is_incidental"):
            continue
        gene = store.genes.get(v.get("gene_id"))
        gene_acmg = bool(gene.get("is_acmg_reportable")) if gene else False
        if incidental_admitted(v, consent_opt_in, gene_acmg, age):
            admitted_incidental.append(v)

    reportable_ids = [v["id"] for v in primary] + [v["id"] for v in admitted_incidental]
    incidental_disclosed = len(admitted_incidental) > 0
    return reportable_ids, incidental_disclosed


# ===========================================================================
# Clock endpoints (PRD 2.4)
# ===========================================================================
@app.route("/lab/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_user_context()
    require_role(role, {"LabDirector"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    parse_iso(iso, "to_iso8601")
    store.clock["current_utc"] = iso
    return success(S.clock(store.clock), 200)


@app.route("/lab/_clock", methods=["GET"])
def get_clock():
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    return success(S.clock(store.clock), 200)


# ===========================================================================
# Gene catalog (PRD 3.1)
# ===========================================================================
@app.route("/lab/genes", methods=["POST"])
def create_gene():
    _, role = require_user_context()
    require_role(role, {"LabDirector"})
    body = get_json_body()
    require_fields(body, ["symbol"])
    symbol = require_string(body, "symbol")
    is_acmg = body.get("is_acmg_reportable", False)
    if not isinstance(is_acmg, bool):
        raise err("ERR_INVALID_REQUEST", "is_acmg_reportable must be a boolean.")
    # Unique symbol, case-sensitive (PRD 3.1).
    for g in store.genes.values():
        if g["symbol"] == symbol:
            raise err("ERR_INVALID_REQUEST", "Gene symbol must be unique.")
    g = {"symbol": symbol, "is_acmg_reportable": is_acmg, "status": "ACTIVE"}
    store.stamp_common(g)
    store.genes[g["id"]] = g
    return success(S.gene(g), 201)


@app.route("/lab/genes", methods=["GET"])
def list_genes():
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    items = list(store.genes.values())
    symbol = request.args.get("symbol")
    if symbol is not None:
        items = [g for g in items if g["symbol"] == symbol]
    page, pag = paginate(items)
    return success([S.gene(g) for g in page], 200, pagination=pag)


@app.route("/lab/genes/<gene_id>", methods=["GET"])
def get_gene_route(gene_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    return success(S.gene(get_gene(gene_id)), 200)


@app.route("/lab/genes/<gene_id>/panel-genes", methods=["GET"])
def list_gene_panel_genes(gene_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    get_gene(gene_id)
    items = [pg for pg in store.panel_genes.values() if pg["gene_id"] == gene_id]
    page, pag = paginate(items)
    return success([S.panel_gene(pg) for pg in page], 200, pagination=pag)


# ===========================================================================
# Panel catalog (PRD 3.1)
# ===========================================================================
@app.route("/lab/panels", methods=["POST"])
def create_panel():
    _, role = require_user_context()
    require_role(role, {"LabDirector"})
    body = get_json_body()
    require_fields(body, ["name", "list_price_cents"])
    name = require_string(body, "name")
    list_price = require_non_negative_int(body, "list_price_cents")
    requires_consent = body.get("requires_consent", True)
    if not isinstance(requires_consent, bool):
        raise err("ERR_INVALID_REQUEST", "requires_consent must be a boolean.")
    p = {
        "name": name,
        "list_price_cents": list_price,
        "requires_consent": requires_consent,
        "gene_count": 0,
        "status": "DRAFT",
    }
    store.stamp_common(p)
    store.panels[p["id"]] = p
    return success(S.panel(p), 201)


@app.route("/lab/panels", methods=["GET"])
def list_panels():
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    items = list(store.panels.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pag = paginate(items)
    return success([S.panel(p) for p in page], 200, pagination=pag)


@app.route("/lab/panels/<panel_id>", methods=["GET"])
def get_panel_route(panel_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    return success(S.panel(get_panel(panel_id)), 200)


@app.route("/lab/panels/<panel_id>/publish", methods=["POST"])
def publish_panel(panel_id):
    _, role = require_user_context()
    require_role(role, {"LabDirector"})
    p = get_panel(panel_id)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_REQUEST", "Panel is not in DRAFT status.")
    p["status"] = "PUBLISHED"
    store.touch(p)
    return success(S.panel(p), 200)


@app.route("/lab/panels/<panel_id>/panel-genes", methods=["POST"])
def add_panel_gene(panel_id):
    _, role = require_user_context()
    require_role(role, {"LabDirector"})
    p = get_panel(panel_id)
    body = get_json_body()
    require_fields(body, ["gene_id"])
    gene_id = require_string(body, "gene_id")
    get_gene(gene_id)
    pg = {
        "panel_id": panel_id,
        "gene_id": gene_id,
        "status": "INCLUDED",
    }
    store.stamp_common(pg)
    store.panel_genes[pg["id"]] = pg
    recompute_gene_count(p)
    store.touch(p)
    return success(S.panel_gene(pg), 201)


@app.route("/lab/panels/<panel_id>/panel-genes", methods=["GET"])
def list_panel_panel_genes(panel_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    get_panel(panel_id)
    items = [pg for pg in store.panel_genes.values() if pg["panel_id"] == panel_id]
    page, pag = paginate(items)
    return success([S.panel_gene(pg) for pg in page], 200, pagination=pag)


@app.route("/lab/panel-genes/<pg_id>", methods=["GET"])
def get_panel_gene_route(pg_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    return success(S.panel_gene(get_panel_gene(pg_id)), 200)


@app.route("/lab/panel-genes", methods=["GET"])
def list_panel_genes():
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    items = list(store.panel_genes.values())
    for key in ("panel_id", "gene_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [pg for pg in items if pg[key] == val]
    page, pag = paginate(items)
    return success([S.panel_gene(pg) for pg in page], 200, pagination=pag)


# ===========================================================================
# Provider (PRD 3.2)
# ===========================================================================
@app.route("/lab/providers", methods=["POST"])
def create_provider():
    _, role = require_user_context()
    require_role(role, {"LabIntake", "LabDirector"})
    body = get_json_body()
    require_fields(body, ["npi", "full_name"])
    npi = require_string(body, "npi")
    full_name = require_string(body, "full_name")
    for prov in store.providers.values():
        if prov["npi"] == npi:
            raise err("ERR_INVALID_REQUEST", "Provider NPI must be unique.")
    prov = {"npi": npi, "full_name": full_name}
    store.stamp_common(prov)
    store.providers[prov["id"]] = prov
    return success(S.provider(prov), 201)


@app.route("/lab/providers/<provider_id>", methods=["GET"])
def get_provider_route(provider_id):
    _, role = require_user_context()
    require_role(role, set(ALL_ROLES))
    return success(S.provider(get_provider(provider_id)), 200)


# Register the remaining workflow route groups. Imported after the helpers and
# `app` exist so the modules can reuse them.
import routes_workflow  # noqa: E402
routes_workflow.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
