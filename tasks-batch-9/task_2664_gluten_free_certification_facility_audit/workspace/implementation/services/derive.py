"""Recomputation of computed fields plus the cascading side-effect helpers."""

import clock
import db
from constants import (
    AUDIT_CLOSED_STATUSES,
    NC_OPEN_STATUSES,
    REQUIRED_DOC_TYPES,
    ROLLING_WINDOW_DAYS,
    SEVERITY_POINTS,
)
from services import calc


class Counters(object):
    """Mutable tallies used by the surveillance sweep."""

    def __init__(self):
        self.data = {}

    def bump(self, name, amount=1):
        self.data[name] = self.data.get(name, 0) + amount


def _count(counters, name):
    if counters is not None:
        counters.bump(name)


# ------------------------------------------------------------------ lookups
def links_for_product(product_id):
    rows = [
        link
        for link in db.product_ingredients.values()
        if link["product_id"] == product_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def lines_for_product(product_id):
    """[(ingredient_row, link_row)] in formula-line creation order."""
    out = []
    for link in links_for_product(product_id):
        ingredient = db.ingredients.get(link["ingredient_id"])
        if ingredient is not None:
            out.append((ingredient, link))
    return out


def ingredients_for_product(product_id):
    return [ingredient for ingredient, _ in lines_for_product(product_id)]


def links_for_ingredient(ingredient_id):
    return [
        link
        for link in db.product_ingredients.values()
        if link["ingredient_id"] == ingredient_id
    ]


def documents_for_ingredient(ingredient_id):
    return [
        doc
        for doc in db.supplier_documents.values()
        if doc["ingredient_id"] == ingredient_id
    ]


def certificates_for_product(product_id):
    rows = [
        cert
        for cert in db.certificates.values()
        if cert["product_id"] == product_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def certificates_for_applicant(applicant_id):
    return [
        cert
        for cert in db.certificates.values()
        if cert["applicant_id"] == applicant_id
    ]


def active_certificate_for_product(product_id):
    for cert in certificates_for_product(product_id):
        if cert["status"] in ("ISSUED", "SUSPENDED"):
            return cert
    return None


def nonconformances_for_audit(audit_id):
    rows = [
        nc
        for nc in db.nonconformances.values()
        if nc.get("audit_id") == audit_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def nonconformances_for_certificate(certificate_id):
    return [
        nc
        for nc in db.nonconformances.values()
        if nc.get("certificate_id") == certificate_id
    ]


def nonconformances_for_applicant(applicant_id):
    return [
        nc
        for nc in db.nonconformances.values()
        if nc["applicant_id"] == applicant_id
    ]


def complaints_for_certificate(certificate_id):
    return [
        c
        for c in db.consumer_complaints.values()
        if c["certificate_id"] == certificate_id
    ]


def required_doc_types(ingredient):
    return list(REQUIRED_DOC_TYPES[ingredient["risk_class"]])


def has_open_critical(nonconformances):
    return any(
        nc["severity"] == "CRITICAL" and nc["status"] in NC_OPEN_STATUSES
        for nc in nonconformances
    )


# ------------------------------------------------------------- recomputation
def recompute_supplier(supplier):
    before = db.snapshot(supplier)
    supplier["verified_document_count"] = sum(
        1
        for doc in db.supplier_documents.values()
        if doc["supplier_id"] == supplier["id"] and doc["status"] == "VERIFIED"
    )
    return db.touch_if_changed(supplier, before)


def recompute_ingredient_docs(ingredient):
    before = db.snapshot(ingredient)
    ingredient["verified_doc_types"] = sorted(
        {
            doc["doc_type"]
            for doc in documents_for_ingredient(ingredient["id"])
            if doc["status"] == "VERIFIED"
        }
    )
    return db.touch_if_changed(ingredient, before)


def recompute_product_counts(product):
    lines = lines_for_product(product["id"])
    product["linked_ingredient_count"] = len(lines)
    product["blocked_ingredient_count"] = sum(
        1 for ingredient, _ in lines if ingredient["status"] == "BLOCKED"
    )
    scheduled = [
        lt
        for lt in db.lot_tests.values()
        if lt["product_id"] == product["id"] and lt["test_type"] == "SCHEDULED"
    ]
    if scheduled:
        product["last_scheduled_sample_on"] = max(
            lt["sample_collected_on"] for lt in scheduled
        )
    else:
        product["last_scheduled_sample_on"] = None


def recompute_facility_audit_outcome(facility):
    before = db.snapshot(facility)
    closed = [
        a
        for a in db.audits.values()
        if a["facility_id"] == facility["id"] and a["status"] in AUDIT_CLOSED_STATUSES
    ]
    if closed:
        closed.sort(key=lambda a: (a["closed_on"], -a["_seq"]))
        latest = closed[-1]
        facility["last_closed_audit_outcome"] = latest["status"]
        facility["last_closed_audit_closed_on"] = latest["closed_on"]
    else:
        facility["last_closed_audit_outcome"] = "NONE"
        facility["last_closed_audit_closed_on"] = None
    return db.touch_if_changed(facility, before)


def latest_closed_audit_for_facility(facility_id):
    closed = [
        a
        for a in db.audits.values()
        if a["facility_id"] == facility_id and a["status"] in AUDIT_CLOSED_STATUSES
    ]
    if not closed:
        return None
    closed.sort(key=lambda a: (a["closed_on"], -a["_seq"]))
    return closed[-1]


def recompute_audit_findings(audit):
    before = db.snapshot(audit)
    findings = nonconformances_for_audit(audit["id"])
    audit["finding_count"] = len(findings)
    audit["critical_finding_count"] = sum(
        1 for nc in findings if nc["severity"] == "CRITICAL"
    )
    # §3.7: the adjudicated figure is recomputed on every creation of, and every
    # status change of, any nonconformance naming this audit — the audit does not
    # have to be closed for that to happen.
    audit["final_score"] = calc.final_adjudicated_score(findings)
    return db.touch_if_changed(audit, before)


def recompute_audits_for_nonconformance(nc):
    audit_id = nc.get("audit_id")
    if not audit_id:
        return
    audit = db.audits.get(audit_id)
    if audit is not None:
        recompute_audit_findings(audit)


def recompute_applicant(applicant):
    before = db.snapshot(applicant)
    now = clock.now()
    certs = certificates_for_applicant(applicant["id"])

    cycle_certs = [c for c in certs if c["status"] in ("ISSUED", "SUSPENDED")]
    if cycle_certs:
        applicant["current_cycle_started_on"] = min(
            c["issued_on"] for c in cycle_certs
        )
    else:
        applicant["current_cycle_started_on"] = None

    applicant["active_certified_product_count"] = sum(
        1 for c in certs if c["status"] == "ISSUED"
    )
    suspended_count = sum(1 for c in certs if c["status"] == "SUSPENDED")
    applicant["suspended_certificate_count"] = suspended_count
    applicant["revoked_certificate_count"] = sum(
        1 for c in certs if c["status"] == "REVOKED"
    )

    ncs = nonconformances_for_applicant(applicant["id"])
    open_ncs = [nc for nc in ncs if nc["status"] in NC_OPEN_STATUSES]
    applicant["open_nc_penalty_points"] = sum(
        SEVERITY_POINTS[nc["severity"]] for nc in open_ncs
    )

    complaints = []
    for cert in certs:
        complaints.extend(complaints_for_certificate(cert["id"]))
    substantiated = [
        c
        for c in complaints
        if c["status"] in ("SUBSTANTIATED", "RECALL_COORDINATION", "CLOSED")
        and c["outcome_evidence"] not in (None, "NO_EVIDENCE")
    ]

    rolling_start = clock.add_days(now, -ROLLING_WINDOW_DAYS)
    cycle_start = applicant["current_cycle_started_on"] or applicant["created_at"]

    rolling_complaints = sum(
        1 for c in substantiated if rolling_start <= c["reported_on"] <= now
    )
    cycle_complaints = sum(
        1 for c in substantiated if cycle_start <= c["reported_on"] <= now
    )
    applicant["substantiated_complaint_count_rolling"] = rolling_complaints
    applicant["substantiated_complaint_count_cycle"] = cycle_complaints

    rolling_points = sum(
        SEVERITY_POINTS[nc["severity"]]
        for nc in open_ncs
        if rolling_start <= nc["created_at"] <= now
    )
    cycle_points = sum(
        SEVERITY_POINTS[nc["severity"]]
        for nc in open_ncs
        if cycle_start <= nc["created_at"] <= now
    )

    applicant["posture_score_rolling_12m"] = calc.posture_score(
        rolling_points, suspended_count, rolling_complaints
    )
    applicant["posture_score_cycle"] = calc.posture_score(
        cycle_points, suspended_count, cycle_complaints
    )

    posture = calc.posture_band(applicant["posture_score_cycle"])
    if any(
        c["status"] == "REVOKED"
        and c["revocation_reason"] in ("FRAUD", "REPEAT_FAILURE")
        for c in certs
    ):
        posture = "SUSPENDED"
    applicant["compliance_posture"] = posture

    applicant["fee_balance_cents"] = sum(
        c["total_fee_cents"]
        for c in certs
        if c["fee_charged"] and not c["fee_refunded"]
    )
    return db.touch_if_changed(applicant, before)


def recompute_applicant_by_id(applicant_id):
    applicant = db.applicants.get(applicant_id)
    if applicant is not None:
        recompute_applicant(applicant)


# ------------------------------------------------------------------ cascades
def suspend_certificate(cert, reason, counters=None):
    """ISSUED -> SUSPENDED with the full documented side-effect set."""
    if cert["status"] != "ISSUED":
        return False
    cert["status"] = "SUSPENDED"
    cert["suspended_on"] = clock.now()
    cert["suspension_reason"] = reason
    cert["suspension_count"] = cert["suspension_count"] + 1
    cert["mark_usage_locked"] = True
    db.touch(cert)
    _count(counters, "certificates_suspended")
    product = db.products.get(cert["product_id"])
    if product is not None and product["label_status"] == "APPROVED":
        product["label_status"] = "FROZEN"
        db.touch(product)
    recompute_applicant_by_id(cert["applicant_id"])
    return True


def suspend_certificates_for_product(product_id, reason, counters=None):
    suspended = []
    for cert in certificates_for_product(product_id):
        if suspend_certificate(cert, reason, counters):
            suspended.append(cert)
    return suspended


def block_ingredient_chain(ingredient, reason, counters=None):
    """Block an APPROVED ingredient, then every compound parent above it."""
    blocked = []
    if ingredient["status"] == "APPROVED":
        ingredient["status"] = "BLOCKED"
        ingredient["blocked_reason"] = reason
        db.touch(ingredient)
        _count(counters, "ingredients_blocked")
        blocked.append(ingredient)
    if not blocked:
        return blocked
    seen = {ingredient["id"]}
    cursor = ingredient
    while cursor.get("parent_ingredient_id"):
        parent = db.ingredients.get(cursor["parent_ingredient_id"])
        if parent is None or parent["id"] in seen:
            break
        seen.add(parent["id"])
        if parent["status"] == "APPROVED":
            parent["status"] = "BLOCKED"
            parent["blocked_reason"] = "SUB_COMPONENT_BLOCKED"
            db.touch(parent)
            _count(counters, "ingredients_blocked")
            blocked.append(parent)
        cursor = parent
    return blocked


def refresh_products_of_ingredients(ingredient_ids, counters=None,
                                    force_block=False):
    """Recompute formula-line aggregates and block cleared formulas."""
    ingredient_ids = set(ingredient_ids)
    if not ingredient_ids:
        return []
    product_ids = {
        link["product_id"]
        for link in db.product_ingredients.values()
        if link["ingredient_id"] in ingredient_ids
    }
    products = [db.products[pid] for pid in product_ids if pid in db.products]
    products.sort(key=lambda p: (p["created_at"], p["_seq"]))
    blocked_products = []
    for product in products:
        before = db.snapshot(product)
        recompute_product_counts(product)
        newly_blocked = False
        if product["formula_status"] == "CLEARED" and (
            force_block or product["blocked_ingredient_count"] >= 1
        ):
            product["formula_status"] = "BLOCKED"
            newly_blocked = True
        db.touch_if_changed(product, before)
        if newly_blocked:
            blocked_products.append(product)
            suspend_certificates_for_product(
                product["id"], "INGREDIENT_BLOCKED", counters
            )
    return blocked_products


def restore_products_of_ingredients(ingredient_ids):
    """A blocked formula returns to CLEARED once every line is approved again."""
    ingredient_ids = set(ingredient_ids)
    if not ingredient_ids:
        return []
    product_ids = {
        link["product_id"]
        for link in db.product_ingredients.values()
        if link["ingredient_id"] in ingredient_ids
    }
    products = [db.products[pid] for pid in product_ids if pid in db.products]
    products.sort(key=lambda p: (p["created_at"], p["_seq"]))
    cleared = []
    for product in products:
        before = db.snapshot(product)
        recompute_product_counts(product)
        lines = lines_for_product(product["id"])
        if (
            product["formula_status"] == "BLOCKED"
            and product["blocked_ingredient_count"] == 0
            and lines
            and all(ingredient["status"] == "APPROVED" for ingredient, _ in lines)
        ):
            product["formula_status"] = "CLEARED"
            cleared.append(product)
        db.touch_if_changed(product, before)
    return cleared


def block_ingredients_for_cause(ingredients, reason, counters=None):
    """Block a set of ingredients and cascade through parents, products, certs."""
    blocked = []
    for ingredient in ingredients:
        blocked.extend(block_ingredient_chain(ingredient, reason, counters))
    if blocked:
        refresh_products_of_ingredients([i["id"] for i in blocked], counters)
    return blocked


def recompute_product_plan(product):
    """Re-derive threshold and sampling plan from the current formula lines."""
    facility = db.facilities.get(product["facility_id"])
    lines = lines_for_product(product["id"])
    ingredients = [ingredient for ingredient, _ in lines]
    threshold = calc.threshold_standard(
        product["requested_mark_tier"], ingredients, facility
    )
    lots, exclusion_days = calc.sampling_plan(threshold, lines)
    product["threshold_ppm"] = threshold
    product["sampling_lots_per_year"] = lots
    product["sampling_exclusion_days"] = exclusion_days
    return threshold, lots, exclusion_days


def documents_expired_for_ingredient(ingredient, now):
    return [
        doc
        for doc in documents_for_ingredient(ingredient["id"])
        if doc["status"] == "VERIFIED" and doc["expires_on"] <= now
    ]
