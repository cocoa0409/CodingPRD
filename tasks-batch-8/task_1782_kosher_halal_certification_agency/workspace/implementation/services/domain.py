"""Derived-field recomputation, bubble-ups, and the multi-hop cascades.

Every cascade is atomic within its triggering request (consistency_model:
immediate). Each mutated record gets its own updated_at refresh and version
bump via db.touch.
"""
from db import store, touch

# --- open_nc_score / risk_tier (SCAFFOLD §1.3 open_nc_score_and_risk_tier) ---
NC_WEIGHTS = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 8}
NC_COUNTED_STATUSES = ("OPEN", "REOPENED", "ESCALATED")

# Holiday scheme coverage: PASSOVER/ROSH_HASHANAH need KOSHER or DUAL;
# RAMADAN/EID_AL_FITR need HALAL or DUAL.
HOLIDAY_SCHEME_COVERAGE = {
    "PASSOVER": ("KOSHER", "DUAL"),
    "ROSH_HASHANAH": ("KOSHER", "DUAL"),
    "RAMADAN": ("HALAL", "DUAL"),
    "EID_AL_FITR": ("HALAL", "DUAL"),
}


def scheme_covers(owning_scheme, requested_scheme):
    """KOSHER covers KOSHER only; HALAL covers HALAL only; DUAL covers all."""
    if owning_scheme == "DUAL":
        return requested_scheme in ("KOSHER", "HALAL", "DUAL")
    return requested_scheme == owning_scheme


def find_active_agreement(client_id):
    for a in store.agreements.values():
        if a["client_id"] == client_id and a["status"] == "ACTIVE":
            return a
    return None


def recompute_client_nc(client):
    """open_nc_score sums severity weights over findings at ALL of the client's
    facilities (any facility status) in OPEN/REOPENED/ESCALATED; risk_tier is
    LOW <= 2, MEDIUM 3..7, HIGH >= 8."""
    score = 0
    for f in store.findings.values():
        if f["status"] not in NC_COUNTED_STATUSES:
            continue
        fac = store.facilities.get(f["facility_id"])
        if fac is not None and fac["client_id"] == client["id"]:
            score += NC_WEIGHTS[f["severity"]]
    tier = "HIGH" if score >= 8 else ("MEDIUM" if score >= 3 else "LOW")
    if client["open_nc_score"] != score or client["risk_tier"] != tier:
        client["open_nc_score"] = score
        client["risk_tier"] = tier
        touch(client)


def recompute_client_billed(client):
    """total_billed_cents sums total_cents over invoices in ISSUED/OVERDUE/PAID
    (VOID excluded)."""
    total = sum(i["total_cents"] for i in store.invoices.values()
                if i["client_id"] == client["id"]
                and i["status"] in ("ISSUED", "OVERDUE", "PAID"))
    if client["total_billed_cents"] != total:
        client["total_billed_cents"] = total
        touch(client)


def certificate_entries(certificate_id):
    return [e for e in store.certificate_products.values()
            if e["certificate_id"] == certificate_id]


def recompute_certificate(cert):
    """scope_status is PARTIAL_FROZEN iff any entry is FROZEN;
    active_product_count counts INCLUDED entries."""
    entries = certificate_entries(cert["id"])
    scope = "PARTIAL_FROZEN" if any(e["status"] == "FROZEN" for e in entries) else "FULL"
    count = sum(1 for e in entries if e["status"] == "INCLUDED")
    if cert["scope_status"] != scope or cert["active_product_count"] != count:
        cert["scope_status"] = scope
        cert["active_product_count"] = count
        touch(cert)


def client_active_certificates(client_id):
    return [c for c in store.certificates.values()
            if c["client_id"] == client_id and c["status"] == "ACTIVE"]


def bubble_client_on_cert_loss(client):
    """A CERTIFIED client left with zero ACTIVE certificates drops to
    SUSPENDED."""
    if client["status"] == "CERTIFIED" and not client_active_certificates(client["id"]):
        client["status"] = "SUSPENDED"
        touch(client)


def suspend_certificate_system(cert):
    """System-path ACTIVE -> SUSPENDED (unconditional on the cascade trigger)."""
    if cert["status"] == "ACTIVE":
        cert["status"] = "SUSPENDED"
        touch(cert)
        return True
    return False


def suspend_facility_cascade(facility):
    """Facility APPROVED -> SUSPENDED, then HOP-1: in-scope ACTIVE certificates
    -> SUSPENDED; HOP-2: each affected client recomputes (CERTIFIED with zero
    ACTIVE certificates -> SUSPENDED)."""
    if facility["status"] != "APPROVED":
        return
    facility["status"] = "SUSPENDED"
    touch(facility)
    affected_clients = set()
    for cert in store.certificates.values():
        if facility["id"] in cert["facility_ids"] and cert["status"] == "ACTIVE":
            cert["status"] = "SUSPENDED"
            touch(cert)
            affected_clients.add(cert["client_id"])
    for cid in affected_clients:
        client = store.clients.get(cid)
        if client is not None:
            bubble_client_on_cert_loss(client)


def compromise_facility_lines(facility):
    """All of the facility's lines -> COMPROMISED, kosherized_valid_until null
    (critical-finding / no-access side effect only)."""
    for line in store.equipment_lines.values():
        if line["facility_id"] == facility["id"] and line["kosherization_state"] != "COMPROMISED":
            line["kosherization_state"] = "COMPROMISED"
            line["kosherized_valid_until"] = None
            touch(line)


def product_junctions(product_id):
    return [j for j in store.product_ingredients.values()
            if j["product_id"] == product_id]


def product_has_pending_or_blocked(product_id):
    return any(j["status"] in ("PENDING_REAPPROVAL", "BLOCKED")
               for j in product_junctions(product_id))


def ingredient_freeze_cascade(ingredient):
    """Change-notice cascade (PRD §3.3), four hops, atomic:
    HOP-1 junctions ACTIVE -> PENDING_REAPPROVAL;
    HOP-2 owning CERTIFIABLE products -> REVIEW_HOLD;
    HOP-3 INCLUDED entries of those products -> FROZEN;
    HOP-4 owning certificates recompute scope_status / active_product_count."""
    flipped_products = set()
    for j in store.product_ingredients.values():
        if j["ingredient_id"] == ingredient["id"] and j["status"] == "ACTIVE":
            j["status"] = "PENDING_REAPPROVAL"
            touch(j)
            flipped_products.add(j["product_id"])
    held_products = set()
    for pid in flipped_products:
        product = store.products.get(pid)
        if product is not None and product["status"] == "CERTIFIABLE":
            product["status"] = "REVIEW_HOLD"
            touch(product)
            held_products.add(pid)
    affected_certs = set()
    for e in store.certificate_products.values():
        if e["product_id"] in held_products and e["status"] == "INCLUDED":
            e["status"] = "FROZEN"
            touch(e)
            affected_certs.add(e["certificate_id"])
    for cid in affected_certs:
        recompute_certificate(store.certificates[cid])


def ingredient_compensation_cascade(ingredient):
    """Re-approval compensation (PRD §3.3): PENDING_REAPPROVAL junctions ->
    ACTIVE; REVIEW_HOLD products with no remaining PENDING_REAPPROVAL/BLOCKED
    junctions -> CERTIFIABLE; their FROZEN entries -> INCLUDED; certificates
    recompute."""
    restored_products = set()
    for j in store.product_ingredients.values():
        if j["ingredient_id"] == ingredient["id"] and j["status"] == "PENDING_REAPPROVAL":
            j["status"] = "ACTIVE"
            touch(j)
            restored_products.add(j["product_id"])
    released_products = set()
    for pid in restored_products:
        product = store.products.get(pid)
        if (product is not None and product["status"] == "REVIEW_HOLD"
                and not product_has_pending_or_blocked(pid)):
            product["status"] = "CERTIFIABLE"
            touch(product)
            released_products.add(pid)
    affected_certs = set()
    for e in store.certificate_products.values():
        if e["product_id"] in released_products and e["status"] == "FROZEN":
            e["status"] = "INCLUDED"
            touch(e)
            affected_certs.add(e["certificate_id"])
    for cid in affected_certs:
        recompute_certificate(store.certificates[cid])


def release_review_hold_if_clear(product):
    """Manual release valve (PRD §3.4): a REVIEW_HOLD product with zero
    PENDING_REAPPROVAL/BLOCKED junctions returns to CERTIFIABLE, its FROZEN
    certificate entries return to INCLUDED, certificates recompute."""
    if product["status"] != "REVIEW_HOLD":
        return
    if product_has_pending_or_blocked(product["id"]):
        return
    product["status"] = "CERTIFIABLE"
    touch(product)
    affected_certs = set()
    for e in store.certificate_products.values():
        if e["product_id"] == product["id"] and e["status"] == "FROZEN":
            e["status"] = "INCLUDED"
            touch(e)
            affected_certs.add(e["certificate_id"])
    for cid in affected_certs:
        recompute_certificate(store.certificates[cid])


def revoke_client_certificates(client):
    """Withdraw/terminate cascade: the client's DRAFT/ACTIVE/SUSPENDED
    certificates -> REVOKED; already-terminal certificates untouched."""
    for cert in store.certificates.values():
        if cert["client_id"] == client["id"] and cert["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
            cert["status"] = "REVOKED"
            touch(cert)


def covering_certificate_exists(facility_id, holiday_code):
    """Some ACTIVE certificate whose facility_ids contains the facility and
    whose scheme covers the holiday code."""
    allowed = HOLIDAY_SCHEME_COVERAGE[holiday_code]
    for c in store.certificates.values():
        if (c["status"] == "ACTIVE" and facility_id in c["facility_ids"]
                and c["scheme"] in allowed):
            return True
    return False
