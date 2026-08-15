"""CertificationAgreement endpoints (PRD §3.8), including the OCC guard on
creation (expected_client_version vs client.version, PRD §2.7)."""
import calendar
from datetime import date, timedelta

from flask import Blueprint

from db import new_common, store, touch
from errors import err
from middleware import get_or_404, require_roles
from response import Paginator, created, ok
from services.domain import scheme_covers
from services.fees import annual_certification_fee
from validation import body_json, req_date, req_enum, req_int, req_str

bp = Blueprint("agreements", __name__)

SCHEMES = ("KOSHER", "HALAL", "DUAL")
BILLING_CYCLES = ("ANNIVERSARY", "CALENDAR_YEAR")


def _add_months(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def compute_term_end(billing_cycle, term_start):
    """ANNIVERSARY: term_start + 12 months - 1 day; CALENDAR_YEAR: Dec 31 of
    the term-start year."""
    if billing_cycle == "ANNIVERSARY":
        return _add_months(term_start, 12) - timedelta(days=1)
    return date(term_start.year, 12, 31)


@bp.post("/agreements")
def create_agreement():
    data = body_json()
    client_id = req_str(data, "client_id")
    scheme = req_enum(data, "scheme", SCHEMES)
    billing_cycle = req_enum(data, "billing_cycle", BILLING_CYCLES)
    term_start_date = req_date(data, "term_start_date")
    per_product_fee_cents = req_int(data, "per_product_fee_cents")
    expected_client_version = req_int(data, "expected_client_version")
    require_roles("AccountManager")
    client = get_or_404(store.clients, client_id, "Client")
    # OCC before any business logic (validation priority 3.5).
    if expected_client_version != client["version"]:
        err("ERR_STALE_CLIENT_VERSION",
            "expected_client_version %s does not match the client's current "
            "version %s" % (expected_client_version, client["version"]))
    if not scheme_covers(client["certification_scheme"], scheme):
        err("ERR_SCHEME_MISMATCH",
            "Agreement scheme %s is not covered by the client's scheme %s"
            % (scheme, client["certification_scheme"]))
    # Create-with-supersede: the client's previous ACTIVE agreement is replaced.
    for existing in store.agreements.values():
        if existing["client_id"] == client_id and existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    # The create advances the client record — the reason the OCC guard exists.
    touch(client)
    agreement = new_common({
        "client_id": client_id,
        "scheme": scheme,
        "billing_cycle": billing_cycle,
        "term_start_date": term_start_date,
        "term_end_date": compute_term_end(billing_cycle, term_start_date),
        "per_product_fee_cents": per_product_fee_cents,
        "annual_fee_snapshot_cents": None,
        "status": "DRAFT",
    })
    store.agreements[agreement["id"]] = agreement
    return created(agreement)


@bp.get("/agreements")
def list_agreements():
    p = Paginator()
    rows = list(store.agreements.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "status")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/agreements/<agreement_id>")
def get_agreement(agreement_id):
    return ok(get_or_404(store.agreements, agreement_id, "Agreement"))


@bp.post("/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    require_roles("AccountManager")
    agreement = get_or_404(store.agreements, agreement_id, "Agreement")
    client = store.clients.get(agreement["client_id"])
    if client is None or client["status"] not in ("APPLICANT", "CERTIFIED"):
        err("ERR_CLIENT_INVALID_STATE",
            "activate requires the client to be APPLICANT or CERTIFIED")
    if agreement["status"] != "DRAFT":
        err("ERR_AGREEMENT_INVALID_STATE",
            "activate requires agreement status DRAFT")
    if any(a for a in store.agreements.values()
           if a["client_id"] == agreement["client_id"] and a["status"] == "ACTIVE"
           and a["id"] != agreement_id):
        err("ERR_ACTIVE_AGREEMENT_EXISTS",
            "The client already has an ACTIVE agreement")
    # Activation-snapshot variant: the fee freezes here; later facility or
    # risk-tier changes never mutate the snapshot.
    agreement["annual_fee_snapshot_cents"] = annual_certification_fee(
        client, agreement["scheme"])
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return ok(agreement)
