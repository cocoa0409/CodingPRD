"""Certificate and CertificateProduct endpoints (PRD §3.7): issuance under the
full gate chain, suspension/reinstatement, renewal, and the product list."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import logical_now, new_common, store, touch
from errors import err
from middleware import get_or_404, require_roles
from response import Paginator, created, ok
from routes.invoices import create_invoice
from services.domain import (bubble_client_on_cert_loss, certificate_entries,
                             find_active_agreement, recompute_certificate,
                             recompute_client_billed, scheme_covers)
from services.fees import (annual_certification_fee, cycle_end_for,
                           prorata_line_cents, volume_discount_cents)
from validation import body_json, opt_str, req_enum, req_str, req_str_list

bp = Blueprint("certificates", __name__)

SCHEMES = ("KOSHER", "HALAL", "DUAL")
TERM_TYPES = ("ANNUAL", "SEASONAL")
ANNUAL_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 60


def _create_entry(certificate_id, product_id):
    entry = new_common({
        "certificate_id": certificate_id,
        "product_id": product_id,
        "status": "INCLUDED",
    })
    store.certificate_products[entry["id"]] = entry
    return entry


@bp.post("/certificates")
def create_certificate():
    data = body_json()
    client_id = req_str(data, "client_id")
    scheme = req_enum(data, "scheme", SCHEMES)
    term_type = req_enum(data, "term_type", TERM_TYPES)
    facility_ids = req_str_list(data, "facility_ids")
    product_ids = req_str_list(data, "product_ids")
    if term_type == "SEASONAL":
        holiday_window_id = req_str(data, "holiday_window_id")
    else:
        opt_str(data, "holiday_window_id")  # type-check if present; stays null
        holiday_window_id = None
    require_roles("CertificateOfficer")
    client = get_or_404(store.clients, client_id, "Client")
    facilities = [get_or_404(store.facilities, fid, "Facility")
                  for fid in facility_ids]
    products = [get_or_404(store.products, pid, "Product")
                for pid in product_ids]
    window = None
    if holiday_window_id is not None:
        window = get_or_404(store.holiday_windows, holiday_window_id,
                            "HolidayProductionWindow")
    for f in facilities:
        if f["client_id"] != client_id:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "Facility %s belongs to a different client" % f["id"])
    for prod in products:
        if prod["client_id"] != client_id:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "Product %s belongs to a different client" % prod["id"])
    if window is not None:
        window_facility = store.facilities.get(window["facility_id"])
        if window_facility is None or window_facility["client_id"] != client_id:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "The holiday window belongs to a different client")
        if window["facility_id"] not in facility_ids:
            err("ERR_INVALID_REQUEST",
                "The holiday window's facility must be inside the certificate scope")
    if not scheme_covers(client["certification_scheme"], scheme):
        err("ERR_SCHEME_MISMATCH",
            "Certificate scheme %s is not covered by the client's scheme %s"
            % (scheme, client["certification_scheme"]))
    if len(set(product_ids)) != len(product_ids):
        err("ERR_PRODUCT_ALREADY_CERTIFIED",
            "product_ids contains a duplicate")
    included_count = len(product_ids)
    cert = new_common({
        "client_id": client_id,
        "scheme": scheme,
        "term_type": term_type,
        "holiday_window_id": holiday_window_id,
        "facility_ids": list(facility_ids),
        "renews_certificate_id": None,
        "status": "DRAFT",
        "scope_status": "FULL",
        "active_product_count": included_count,
        "issued_at": None,
        "valid_until": None,
    })
    store.certificates[cert["id"]] = cert
    for pid in product_ids:
        _create_entry(cert["id"], pid)
    return created(cert)


@bp.get("/certificates")
def list_certificates():
    p = Paginator()
    rows = list(store.certificates.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "scheme")
    rows = p.filter(rows, "holiday_window_id")
    rows = p.filter(rows, "renews_certificate_id")
    facility_filter = request.args.get("facility_ids")
    if facility_filter is not None:
        rows = [c for c in rows if facility_filter in c["facility_ids"]]
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/certificates/<certificate_id>")
def get_certificate(certificate_id):
    return ok(get_or_404(store.certificates, certificate_id, "Certificate"))


@bp.get("/certificates/<certificate_id>/products")
def list_certificate_products(certificate_id):
    get_or_404(store.certificates, certificate_id, "Certificate")
    p = Paginator()
    rows = certificate_entries(certificate_id)
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/certificates/<certificate_id>/issue")
def issue_certificate(certificate_id):
    """DRAFT -> ACTIVE. Gates evaluate in the PRD §3.7 order."""
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] != "DRAFT":
        err("ERR_CERTIFICATE_INVALID_STATE", "issue requires certificate status DRAFT")
    client = store.clients.get(cert["client_id"])
    if client is None or client["status"] not in ("APPLICANT", "CERTIFIED"):
        err("ERR_CLIENT_INVALID_STATE",
            "issue requires the client to be APPLICANT or CERTIFIED")
    window = None
    if cert["term_type"] == "SEASONAL":
        window = store.holiday_windows.get(cert["holiday_window_id"] or "")
        if window is None or window["status"] != "CONFIRMED":
            err("ERR_WINDOW_INVALID_STATE",
                "SEASONAL issuance requires the holiday window CONFIRMED")
    for fid in cert["facility_ids"]:
        facility = store.facilities.get(fid)
        if facility is None or facility["status"] != "APPROVED":
            err("ERR_FACILITY_NOT_APPROVED",
                "Every in-scope facility must be APPROVED")
    if not cert["facility_ids"]:
        err("ERR_CERTIFICATE_SCOPE_EMPTY",
            "issue requires a non-empty facility scope")
    live_entries = [e for e in certificate_entries(certificate_id)
                    if e["status"] != "REMOVED"]
    for e in live_entries:
        if e["status"] != "INCLUDED":
            err("ERR_PRODUCT_NOT_CERTIFIABLE",
                "Every certificate entry must be INCLUDED at issuance")
        product = store.products.get(e["product_id"])
        if product is None or product["status"] != "CERTIFIABLE":
            err("ERR_PRODUCT_NOT_CERTIFIABLE",
                "Every listed product must be CERTIFIABLE at issuance")
    agreement = find_active_agreement(cert["client_id"])
    if agreement is None:
        err("ERR_NO_ACTIVE_AGREEMENT",
            "issue requires an ACTIVE agreement for the client")
    if not scheme_covers(agreement["scheme"], cert["scheme"]):
        err("ERR_SCHEME_MISMATCH",
            "The ACTIVE agreement's scheme %s does not cover certificate scheme %s"
            % (agreement["scheme"], cert["scheme"]))
    # Fiscal gate (priority 9): locate the qualifying PAID fee invoice.
    if cert["renews_certificate_id"]:
        paid_invoice = next((i for i in store.invoices.values()
                             if i["invoice_type"] == "RENEWAL"
                             and i.get("related_certificate_id") == certificate_id
                             and i["status"] == "PAID"), None)
    else:
        paid_invoice = next((i for i in store.invoices.values()
                             if i["invoice_type"] == "ANNUAL_CERTIFICATION"
                             and i.get("agreement_id") == agreement["id"]
                             and i["status"] == "PAID"), None)
    if paid_invoice is None:
        err("ERR_CERTIFICATION_FEE_UNPAID",
            "issue requires the qualifying fee invoice to be PAID")
    # Issuance segregation wall (priority 9.5, evaluated only once a qualifying
    # PAID invoice exists).
    if paid_invoice["paid_recorded_by"] == g.user_id:
        err("ERR_SEGREGATION_OF_DUTIES_ISSUANCE",
            "The issuer may not be the operator who recorded the fee payment")
    now = logical_now()
    cert["issued_at"] = now
    parent = None
    if cert["renews_certificate_id"]:
        parent = store.certificates.get(cert["renews_certificate_id"])
    if parent is not None and parent.get("valid_until") is not None:
        # Renewal-child variant: parent's valid_until + 365 days.
        cert["valid_until"] = parent["valid_until"] + timedelta(days=ANNUAL_TERM_DAYS)
    elif cert["term_type"] == "ANNUAL":
        cert["valid_until"] = now + timedelta(days=ANNUAL_TERM_DAYS)
    else:
        cert["valid_until"] = window["window_end"]
    cert["status"] = "ACTIVE"
    cert["scope_status"] = "FULL"
    cert["active_product_count"] = sum(1 for e in certificate_entries(certificate_id)
                                       if e["status"] == "INCLUDED")
    touch(cert)
    if parent is not None and parent["status"] == "ACTIVE":
        parent["status"] = "SUPERSEDED"
        touch(parent)
    # Bubble-up: first issuance promotes the client.
    if client["status"] == "APPLICANT":
        client["status"] = "CERTIFIED"
        touch(client)
    return ok(cert)


@bp.post("/certificates/<certificate_id>/products")
def add_certificate_products(certificate_id):
    """Atomic add of one or more CERTIFIABLE products to an ACTIVE certificate;
    auto-creates exactly one PRODUCT_ADDITION invoice (per-line rounding, then
    sum, then the once-only volume discount)."""
    data = body_json()
    product_ids = req_str_list(data, "product_ids", allow_empty=False)
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] != "ACTIVE":
        err("ERR_CERTIFICATE_INVALID_STATE",
            "add-products requires certificate status ACTIVE")
    products = [get_or_404(store.products, pid, "Product") for pid in product_ids]
    for prod in products:
        if prod["client_id"] != cert["client_id"]:
            err("ERR_CROSS_CLIENT_REFERENCE",
                "Product %s belongs to a different client" % prod["id"])
    for prod in products:
        if prod["status"] != "CERTIFIABLE":
            err("ERR_PRODUCT_NOT_CERTIFIABLE",
                "Product %s is not CERTIFIABLE" % prod["id"])
    listed = {e["product_id"] for e in certificate_entries(certificate_id)
              if e["status"] in ("INCLUDED", "FROZEN")}
    seen = set()
    for pid in product_ids:
        if pid in listed or pid in seen:
            err("ERR_PRODUCT_ALREADY_CERTIFIED",
                "Product %s is already listed on this certificate" % pid)
        seen.add(pid)
    agreement = find_active_agreement(cert["client_id"])
    if agreement is None:
        err("ERR_NO_ACTIVE_AGREEMENT",
            "add-products requires an ACTIVE agreement for the client")
    created_entries = [_create_entry(certificate_id, pid) for pid in product_ids]
    recompute_certificate(cert)
    addition_date = logical_now().date()
    cycle_end = cycle_end_for(agreement, addition_date)
    lines = [prorata_line_cents(agreement["per_product_fee_cents"],
                                addition_date, cycle_end)
             for _ in product_ids]
    subtotal = sum(lines)
    discount = volume_discount_cents(subtotal)
    create_invoice(cert["client_id"], agreement["id"], certificate_id,
                   "PRODUCT_ADDITION", subtotal, discount)
    client = store.clients.get(cert["client_id"])
    if client is not None:
        recompute_client_billed(client)
    return created(created_entries, rtype="array")


@bp.delete("/certificate-products/<entry_id>")
def remove_certificate_product(entry_id):
    require_roles("CertificateOfficer")
    entry = get_or_404(store.certificate_products, entry_id, "CertificateProduct")
    if entry["status"] == "REMOVED":
        err("ERR_CERTIFICATE_PRODUCT_INVALID_STATE",
            "Entry is already REMOVED")
    entry["status"] = "REMOVED"
    touch(entry)
    # The addition fee is never refunded; the certificate recomputes.
    cert = store.certificates.get(entry["certificate_id"])
    if cert is not None:
        recompute_certificate(cert)
    return ok(entry)


@bp.post("/certificates/<certificate_id>/suspend")
def suspend_certificate(certificate_id):
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] != "ACTIVE":
        err("ERR_CERTIFICATE_INVALID_STATE",
            "suspend requires certificate status ACTIVE")
    cert["status"] = "SUSPENDED"
    touch(cert)
    client = store.clients.get(cert["client_id"])
    if client is not None:
        bubble_client_on_cert_loss(client)
    return ok(cert)


@bp.post("/certificates/<certificate_id>/reinstate")
def reinstate_certificate(certificate_id):
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] != "SUSPENDED":
        err("ERR_CERTIFICATE_INVALID_STATE",
            "reinstate requires certificate status SUSPENDED")
    for fid in cert["facility_ids"]:
        facility = store.facilities.get(fid)
        if facility is None or facility["status"] != "APPROVED":
            err("ERR_FACILITY_NOT_APPROVED",
                "Every in-scope facility must be APPROVED")
    for finding in store.findings.values():
        if (finding["facility_id"] in cert["facility_ids"]
                and finding["severity"] in ("MAJOR", "CRITICAL")
                and finding["status"] in ("OPEN", "REOPENED", "ESCALATED")):
            err("ERR_OPEN_MAJOR_FINDINGS",
                "An in-scope facility has MAJOR/CRITICAL findings in an open status")
    client = store.clients.get(cert["client_id"])
    if any(i for i in store.invoices.values()
           if i["client_id"] == cert["client_id"] and i["status"] == "OVERDUE"):
        err("ERR_CERTIFICATION_FEE_UNPAID",
            "reinstate requires zero OVERDUE invoices for the client")
    cert["status"] = "ACTIVE"
    touch(cert)  # valid_until is unchanged: downtime is never compensated.
    if client is not None and client["status"] == "SUSPENDED":
        client["status"] = "CERTIFIED"
        touch(client)
    return ok(cert)


@bp.post("/certificates/<certificate_id>/revoke")
def revoke_certificate(certificate_id):
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_CERTIFICATE_INVALID_STATE",
            "revoke requires certificate status ACTIVE or SUSPENDED")
    cert["status"] = "REVOKED"
    touch(cert)
    client = store.clients.get(cert["client_id"])
    if client is not None:
        bubble_client_on_cert_loss(client)
    return ok(cert)


@bp.post("/certificates/<certificate_id>/renew")
def renew_certificate(certificate_id):
    """ACTIVE ANNUAL certificate -> renewal-child DRAFT + RENEWAL invoice."""
    require_roles("CertificateOfficer")
    cert = get_or_404(store.certificates, certificate_id, "Certificate")
    if cert["status"] != "ACTIVE":
        err("ERR_CERTIFICATE_INVALID_STATE", "renew requires certificate status ACTIVE")
    if cert["term_type"] == "SEASONAL":
        err("ERR_CERTIFICATE_NOT_RENEWABLE",
            "SEASONAL certificates are not renewable")
    client = store.clients.get(cert["client_id"])
    if client is not None and client["risk_tier"] == "HIGH":
        err("ERR_CLIENT_HIGH_RISK",
            "Renewal is blocked while the client's risk tier is HIGH")
    live_entries = [e for e in certificate_entries(certificate_id)
                    if e["status"] != "REMOVED"]
    if any(e["status"] == "FROZEN" for e in live_entries):
        err("ERR_PRODUCT_NOT_CERTIFIABLE",
            "Renewal is blocked while any certificate entry is FROZEN")
    now = logical_now()
    window_start = cert["valid_until"] - timedelta(days=RENEWAL_WINDOW_DAYS)
    if not (window_start <= now <= cert["valid_until"]):
        err("ERR_RENEWAL_WINDOW_CLOSED",
            "Renewal is allowed only within [valid_until - 60d, valid_until]")
    if any(c for c in store.certificates.values()
           if c.get("renews_certificate_id") == certificate_id
           and c["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")):
        err("ERR_RENEWAL_ALREADY_EXISTS",
            "A live renewal child already exists for this certificate")
    # The RENEWAL invoice's agreement is system-set: the client's ACTIVE
    # agreement when one exists, otherwise the latest-created agreement (the
    # certificate may legitimately outlive its term). Renewal itself is not
    # gated on an ACTIVE agreement (PRD §3.7).
    agreement = find_active_agreement(cert["client_id"])
    if agreement is None:
        candidates = [a for a in store.agreements.values()
                      if a["client_id"] == cert["client_id"]]
        candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
        agreement = candidates[-1] if candidates else None
    copied_product_ids = [e["product_id"] for e in live_entries
                          if e["status"] == "INCLUDED"]
    child = new_common({
        "client_id": cert["client_id"],
        "scheme": cert["scheme"],
        "term_type": "ANNUAL",
        "holiday_window_id": None,
        "facility_ids": list(cert["facility_ids"]),
        "renews_certificate_id": certificate_id,
        "status": "DRAFT",
        "scope_status": "FULL",
        "active_product_count": len(copied_product_ids),
        "issued_at": None,
        "valid_until": None,
    })
    store.certificates[child["id"]] = child
    for pid in copied_product_ids:
        _create_entry(child["id"], pid)
    # Renewal-recompute variant: the annual fee runs against the current
    # facility set and current risk tier (it may diverge from the snapshot).
    fee_scheme = agreement["scheme"] if agreement is not None else cert["scheme"]
    fee = annual_certification_fee(client, fee_scheme) if client else 0
    create_invoice(cert["client_id"],
                   agreement["id"] if agreement is not None else None,
                   child["id"], "RENEWAL", fee)
    if client is not None:
        recompute_client_billed(client)
    return created(child)
