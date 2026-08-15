"""Core business engine: cross-aggregate recomputation, posture, time sweep, scan pipeline."""

import hashlib
from datetime import timedelta

from db import store, touch, base_resource, iso_fmt, parse_iso, new_id
from services.policy import (
    classify_license,
    effective_classification,
    determine_obligation,
    obligation_type_for,
    compute_bom_posture,
    round2,
)

SEVERITY_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 90, "LOW": 180}

OPEN_FINDING_STATUSES = {"OPEN", "CONFIRMED", "MITIGATED"}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def entries_of_bom(bom_id):
    return [e for e in store.bom_entries.values() if e["bom_id"] == bom_id]


def boms_of_product(product_id):
    return [b for b in store.boms.values() if b["product_id"] == product_id]


def findings_of_product(product_id):
    return [f for f in store.findings.values() if f["product_id"] == product_id]


def tickets_of_product(product_id):
    return [t for t in store.tickets.values() if t["product_id"] == product_id]


def tickets_of_entry(bom_entry_id):
    return [t for t in store.tickets.values() if t["bom_entry_id"] == bom_entry_id]


def tickets_of_bom(bom_id):
    entry_ids = {e["id"] for e in entries_of_bom(bom_id)}
    return [t for t in store.tickets.values() if t["bom_entry_id"] in entry_ids]


def active_bom(product):
    """The product's current active BOM: newest FINALIZED BOM, else newest DRAFT."""
    boms = [b for b in store.boms.values()
            if b["product_id"] == product["id"] and b["status"] == "FINALIZED"]
    if boms:
        boms.sort(key=lambda b: (b["created_at"], b["id"]))
        return boms[-1]
    drafts = [b for b in store.boms.values()
              if b["product_id"] == product["id"] and b["status"] == "DRAFT"]
    if drafts:
        drafts.sort(key=lambda b: (b["created_at"], b["id"]))
        return drafts[-1]
    return None


def approved_component_ids(product_id):
    """Component ids with a non-expired APPROVED LicenseApprovalRequest for the product."""
    now = store.now()
    ids = set()
    for a in store.approvals.values():
        if a["product_id"] != product_id:
            continue
        if a["status"] != "APPROVED":
            continue
        exp = a.get("expiry_at")
        if exp and parse_iso(exp) < now:
            continue
        ids.add(a["component_id"])
    return ids


def _attach_eff(entries):
    for e in entries:
        comp = store.components.get(e["component_id"])
        e["_effective_classification"] = effective_classification(comp) if comp else None
    return entries


# ---------------------------------------------------------------------------
# Posture + counts recomputation
# ---------------------------------------------------------------------------

def recompute_bom_derived(bom):
    """Recompute BOM tallies + posture. Mutates and touches the BOM."""
    entries = _attach_eff(entries_of_bom(bom["id"]))
    product = store.products.get(bom["product_id"])
    approved = approved_component_ids(bom["product_id"])

    total = len(entries)
    copyleft = sum(1 for e in entries if e.get("_effective_classification") in ("WEAK_COPYLEFT", "STRONG_COPYLEFT"))
    restricted = sum(1 for e in entries if e.get("_effective_classification") == "RESTRICTED")
    prohibited = sum(1 for e in entries if e.get("_effective_classification") == "PROHIBITED")

    changed = (
        bom.get("total_components") != total
        or bom.get("copyleft_components") != copyleft
        or bom.get("restricted_components") != restricted
        or bom.get("prohibited_components") != prohibited
    )
    bom["total_components"] = total
    bom["copyleft_components"] = copyleft
    bom["restricted_components"] = restricted
    bom["prohibited_components"] = prohibited

    if bom["status"] in ("FINALIZED",):
        posture = compute_bom_posture(entries, product or {}, approved)
        if bom.get("bom_posture") != posture:
            bom["bom_posture"] = posture
            changed = True
    elif bom.get("bom_posture") is None:
        bom["bom_posture"] = None

    if changed:
        touch(bom)
    return bom


def recompute_entry_vuln_max(entry):
    """Recompute vulnerability_severity_max from open findings on this entry."""
    worst = "NONE"
    for f in store.findings.values():
        if f["bom_entry_id"] != entry["id"]:
            continue
        if f["status"] not in OPEN_FINDING_STATUSES:
            continue
        vuln = store.vulnerabilities.get(f["vulnerability_id"])
        sev = vuln["severity"] if vuln else "LOW"
        if SEVERITY_ORDER[sev] > SEVERITY_ORDER[worst]:
            worst = sev
    if entry.get("vulnerability_severity_max") != worst:
        entry["vulnerability_severity_max"] = worst
        touch(entry)


def recompute_product_counts(product):
    """Recompute product aggregate counts from the active BOM + findings."""
    bom = active_bom(product)
    entries = _attach_eff(entries_of_bom(bom["id"])) if bom else []
    approved = approved_component_ids(product["id"])

    total = len(entries)
    copyleft = sum(1 for e in entries if e.get("_effective_classification") in ("WEAK_COPYLEFT", "STRONG_COPYLEFT"))
    restricted = sum(
        1 for e in entries
        if e.get("_effective_classification") == "RESTRICTED" and e["component_id"] not in approved
    )
    high_vulns = 0
    for f in store.findings.values():
        if f["product_id"] != product["id"]:
            continue
        if f["status"] not in OPEN_FINDING_STATUSES:
            continue
        vuln = store.vulnerabilities.get(f["vulnerability_id"])
        if vuln and vuln["severity"] in ("HIGH", "CRITICAL"):
            high_vulns += 1

    changed = False
    for k, v in (("total_dependency_count", total),
                 ("copyleft_dependency_count", copyleft),
                 ("restricted_dependency_count", restricted),
                 ("high_severity_vulnerability_count", high_vulns)):
        if product.get(k) != v:
            product[k] = v
            changed = True
    if changed:
        touch(product)
    return product


def set_posture(product, new_posture):
    """Apply a posture transition with cascaded side effects."""
    old = product.get("compliance_posture")
    if old == new_posture:
        return
    now = store.now()
    product["compliance_posture"] = new_posture
    product["posture_version"] = int(product.get("posture_version", 1)) + 1
    touch(product)

    if new_posture == "BLOCKED":
        # All open ReleaseGates -> FAILED
        for g in store.gates.values():
            if g["product_id"] == product["id"] and g["gate_status"] in ("OPEN", "EVALUATING"):
                g["gate_status"] = "FAILED"
                g["evaluation_result"] = "FAIL"
                touch(g)
        # All PENDING approval requests -> EXPIRED
        for a in store.approvals.values():
            if a["product_id"] == product["id"] and a["status"] == "PENDING":
                a["status"] = "EXPIRED"
                a["final_decision"] = "EXPIRED"
                touch(a)
        # All OPEN/IN_PROGRESS obligation tickets past due -> OVERDUE
        for t in store.tickets.values():
            if t["product_id"] != product["id"]:
                continue
            if t["status"] in ("OPEN", "IN_PROGRESS"):
                due = t.get("due_at")
                if due and parse_iso(due) < now:
                    t["status"] = "OVERDUE"
                    touch(t)


def reevaluate_product_posture(product):
    """Derive posture from active BOM + findings (automatic transitions only).

    Escalation is automatic; de-escalation from BLOCKED is NOT (requires CISO unblock).
    """
    if product["compliance_posture"] == "BLOCKED":
        return  # manual recovery only

    bom = active_bom(product)
    if bom and bom["status"] == "FINALIZED":
        recompute_bom_derived(bom)
        entries = _attach_eff(entries_of_bom(bom["id"]))
        approved = approved_component_ids(product["id"])
        if any(e.get("_effective_classification") == "PROHIBITED" for e in entries):
            set_posture(product, "BLOCKED")
            return
        has_restricted = any(
            e.get("_effective_classification") == "RESTRICTED" and e["component_id"] not in approved
            for e in entries
        )
        has_high_vuln = any(e.get("vulnerability_severity_max") in ("HIGH", "CRITICAL") for e in entries)
        strict_weak = product.get("distribution_model") == "EMBEDDED" and any(
            e.get("_effective_classification") == "WEAK_COPYLEFT" for e in entries
        )
        if has_restricted or has_high_vuln or strict_weak:
            _escalate_to_at_risk(product)
            return
        # Clean board
        set_posture(product, "COMPLIANT")
        return

    # No finalized BOM: derive from findings only
    has_high = any(
        f["status"] in OPEN_FINDING_STATUSES
        and store.vulnerabilities.get(f["vulnerability_id"])
        and store.vulnerabilities[f["vulnerability_id"]]["severity"] in ("HIGH", "CRITICAL")
        for f in store.findings.values()
        if f["product_id"] == product["id"]
    )
    if has_high:
        _escalate_to_at_risk(product)
    else:
        set_posture(product, "COMPLIANT")


def _escalate_to_at_risk(product):
    old = product.get("compliance_posture")
    if old == "AT_RISK":
        # side effects of COMPLIANT->AT_RISK apply per detection event? Keep idempotent.
        return
    if old == "COMPLIANT":
        product["compliance_posture"] = "AT_RISK"
        product["posture_version"] = int(product.get("posture_version", 1)) + 1
        touch(product)
        # open gates: evaluation_result recomputed, warning_findings_count incremented
        for g in store.gates.values():
            if g["product_id"] == product["id"] and g["gate_status"] in ("OPEN", "EVALUATING"):
                g["warning_findings_count"] = int(g.get("warning_findings_count", 0)) + 1
                touch(g)


# ---------------------------------------------------------------------------
# BOM finalization cascade (scan completion)
# ---------------------------------------------------------------------------

def finalize_bom(bom, scan):
    """BOM DRAFT -> FINALIZED with the full cascade."""
    product = store.products[bom["product_id"]]

    # Supersede older FINALIZED BOMs for the same product
    for other in store.boms.values():
        if other["id"] != bom["id"] and other["product_id"] == bom["product_id"] and other["status"] == "FINALIZED":
            other["status"] = "SUPERSEDED"
            touch(other)
            # open gates referencing superseded BOM -> EXPIRED
            for g in store.gates.values():
                if g["bom_id"] == other["id"] and g["gate_status"] in ("OPEN", "EVALUATING"):
                    g["gate_status"] = "EXPIRED"
                    touch(g)
            # open obligation tickets tied to its entries -> OVERDUE if not fulfilled
            for e in entries_of_bom(other["id"]):
                for t in tickets_of_entry(e["id"]):
                    if t["status"] in ("OPEN", "IN_PROGRESS"):
                        t["status"] = "OVERDUE"
                        touch(t)

    bom["status"] = "FINALIZED"
    bom["notice_file_generated"] = False
    recompute_bom_derived(bom)
    touch(bom)

    entries = _attach_eff(entries_of_bom(bom["id"]))
    approved = approved_component_ids(product["id"])

    # Spawn approval requests for RESTRICTED entries lacking approval
    for e in entries:
        if e.get("_effective_classification") == "RESTRICTED" and e["component_id"] not in approved:
            existing = [a for a in store.approvals.values()
                        if a["bom_entry_id"] == e["id"] and a["status"] in ("PENDING", "LEGAL_REVIEW", "ENGINEERING_REVIEW", "APPROVED")]
            if not existing:
                req = base_resource()
                req.update({
                    "product_id": product["id"],
                    "component_id": e["component_id"],
                    "bom_entry_id": e["id"],
                    "request_reason": None,
                    "risk_acknowledgment": False,
                    "status": "PENDING",
                    "legal_reviewer_id": None,
                    "engineering_reviewer_id": None,
                    "legal_decision": "PENDING",
                    "legal_conditions": None,
                    "engineering_decision": "PENDING",
                    "final_decision": None,
                    "decision_effective_at": None,
                    "expiry_at": None,
                    "requested_by": None,
                })
                store.approvals[req["id"]] = req

    # Obligation tickets for entries with determination != NONE
    for e in entries:
        det = e.get("obligation_determination")
        if det and det != "NONE":
            existing = [t for t in tickets_of_entry(e["id"])]
            if not existing:
                t = base_resource()
                t.update({
                    "product_id": product["id"],
                    "bom_entry_id": e["id"],
                    "obligation_type": obligation_type_for(det),
                    "due_at": iso_fmt(store.now() + timedelta(days=30)),
                    "status": "OPEN",
                    "fulfillment_evidence_uri": None,
                    "waiver_reason": None,
                    "waived_by": None,
                })
                store.tickets[t["id"]] = t

    recompute_product_counts(product)
    reevaluate_product_posture(product)


def update_entry_obligation_fulfilled(entry):
    """Entry obligation_fulfilled = true when every linked ticket is FULFILLED or WAIVED."""
    tickets = tickets_of_entry(entry["id"])
    if tickets and all(t["status"] in ("FULFILLED", "WAIVED") for t in tickets):
        if not entry.get("obligation_fulfilled"):
            entry["obligation_fulfilled"] = True
            touch(entry)
    else:
        if entry.get("obligation_fulfilled"):
            entry["obligation_fulfilled"] = False
            touch(entry)


# ---------------------------------------------------------------------------
# Scan pipeline (synchronous worker)
# ---------------------------------------------------------------------------

def process_scan(scan):
    """Drive a QUEUED scan synchronously through the full pipeline to COMPLETED."""
    scan["status"] = "PARSING"
    touch(scan)

    manifest_components = scan.get("_manifest_components", [])
    scan["status"] = "RESOLVING"
    scan["components_discovered"] = len(manifest_components)
    touch(scan)

    # Resolve components: match by package_url or create new catalogue entries
    resolved = []
    for spec in manifest_components:
        purl = spec.get("package_url") or ""
        comp = None
        for c in store.components.values():
            if c["package_url"] == purl:
                comp = c
                break
        if comp is None:
            comp = base_resource()
            comp.update({
                "package_url": purl,
                "component_name": spec.get("component_name") or (purl.split("/")[-1].split("@")[0] if purl else "unknown"),
                "version": spec.get("version") or (purl.split("@")[-1] if "@" in purl else "0.0.0"),
                "_rev": 1,
                "declared_license_spdx": spec.get("declared_license_spdx") or spec.get("license") or "",
                "discovered_license_spdx": None,
                "license_policy_classification": None,
                "policy_override_classification": None,
                "effective_classification": None,
                "source_download_url": spec.get("source_download_url"),
                "copyright_notice": spec.get("copyright_notice"),
            })
            store.components[comp["id"]] = comp
        resolved.append((comp, spec))

    scan["components_resolved"] = len(resolved)
    scan["status"] = "SCANNING_LICENSES"
    touch(scan)

    product = store.products[scan["product_id"]]

    # Create BOM (DRAFT) + entries
    bom = base_resource()
    bom.update({
        "product_id": product["id"],
        "scan_id": scan["id"],
        "version_label": scan.get("_version_label") or "scan-" + scan["id"][:8],
        "status": "DRAFT",
        "bom_posture": None,
        "total_components": 0,
        "copyleft_components": 0,
        "restricted_components": 0,
        "prohibited_components": 0,
        "notice_file_generated": False,
        "notice_file_hash": None,
    })
    store.boms[bom["id"]] = bom

    entry_by_index = []
    for idx, (comp, spec) in enumerate(resolved):
        e = base_resource()
        is_direct = bool(spec.get("is_direct", True))
        e.update({
            "bom_id": bom["id"],
            "component_id": comp["id"],
            "dependency_scope": spec.get("dependency_scope") or "RUNTIME",
            "is_direct": is_direct,
            "dependency_depth": 0 if is_direct else int(spec.get("dependency_depth", 1)),
            "parent_entry_id": None,
            "obligation_determination": None,
            "obligation_fulfilled": False,
            "vulnerability_severity_max": "NONE",
        })
        store.bom_entries[e["id"]] = e
        entry_by_index.append(e)

    # Wire parent_entry_id for transitive entries (round-robin under direct entries)
    direct_entries = [e for e in entry_by_index if e["is_direct"]]
    transitive = [e for e in entry_by_index if not e["is_direct"]]
    if transitive and direct_entries:
        for i, e in enumerate(transitive):
            parent = direct_entries[i % len(direct_entries)]
            e["parent_entry_id"] = parent["id"]

    # License scanning: populate discovered_license_spdx + classification
    for comp, spec in resolved:
        discovered = spec.get("discovered_license_spdx") or spec.get("license") or comp.get("declared_license_spdx")
        comp["discovered_license_spdx"] = discovered
        comp["license_policy_classification"] = classify_license(discovered, product.get("distribution_model"))
        comp["effective_classification"] = effective_classification(comp)
        touch(comp)

    # Obligation determination per entry
    for (comp, spec), e in zip(resolved, entry_by_index):
        eff = effective_classification(comp)
        lic = comp.get("discovered_license_spdx") or comp.get("declared_license_spdx")
        e["obligation_determination"] = determine_obligation(
            eff, product.get("distribution_model"), e["dependency_scope"], lic
        )
        touch(e)

    # Coverage
    with_license = sum(1 for comp, _ in resolved if comp.get("discovered_license_spdx"))
    if scan["components_resolved"] == 0:
        coverage = 0.00
    else:
        coverage = round2(with_license * 100.0 / scan["components_resolved"])
    scan["license_scan_coverage_pct"] = coverage
    scan["status"] = "SCORING"
    touch(scan)

    # Scoring completion -> COMPLETED + cascade
    scan["status"] = "COMPLETED"
    touch(scan)
    finalize_bom(bom, scan)
    return scan


# ---------------------------------------------------------------------------
# Time sweep (logical clock advancement)
# ---------------------------------------------------------------------------

def time_sweep():
    """Re-evaluate every time-dependent rule after clock advancement."""
    now = store.now()

    # Obligation tickets past due_at -> OVERDUE
    for t in store.tickets.values():
        if t["status"] in ("OPEN", "IN_PROGRESS"):
            due = t.get("due_at")
            if due and parse_iso(due) < now:
                t["status"] = "OVERDUE"
                touch(t)

    # License approval requests: PENDING open >30 days -> EXPIRED; APPROVED past expiry -> EXPIRED
    for a in store.approvals.values():
        if a["status"] == "PENDING":
            created = parse_iso(a["created_at"])
            if created + timedelta(days=30) < now:
                a["status"] = "EXPIRED"
                a["final_decision"] = "EXPIRED"
                touch(a)
        elif a["status"] == "APPROVED":
            exp = a.get("expiry_at")
            if exp and parse_iso(exp) < now:
                a["status"] = "EXPIRED"
                a["final_decision"] = "EXPIRED"
                touch(a)

    # Release gates: OPEN > 14 days (or superseded BOM) -> EXPIRED; an
    # EVALUATING gate's evaluation is completed by the system per the verdict
    # recorded at evaluation time (PRD §3.7: "moves the gate from `EVALUATING`
    # to `FAILED`" / "to `PASSED`"); PASSED/BYPASSED past evaluation_expires_at
    # -> EXPIRED.
    for g in store.gates.values():
        if g["gate_status"] == "OPEN":
            created = parse_iso(g["created_at"])
            bom = store.boms.get(g["bom_id"])
            if (created + timedelta(days=14) < now) or (bom and bom["status"] == "SUPERSEDED"):
                g["gate_status"] = "EXPIRED"
                touch(g)
        elif g["gate_status"] == "EVALUATING":
            result = g.get("evaluation_result")
            if result == "FAIL":
                g["gate_status"] = "FAILED"
                touch(g)
            elif result in ("PASS", "CONDITIONAL_PASS"):
                g["gate_status"] = "PASSED"
                touch(g)
            if g["gate_status"] == "PASSED":
                exp = g.get("evaluation_expires_at")
                if exp and parse_iso(exp) < now:
                    g["gate_status"] = "EXPIRED"
                    touch(g)
        elif g["gate_status"] in ("PASSED", "BYPASSED"):
            exp = g.get("evaluation_expires_at")
            if exp and parse_iso(exp) < now:
                g["gate_status"] = "EXPIRED"
                touch(g)

    # Vulnerability findings past remediation_deadline are flagged (marker field)
    for f in store.findings.values():
        if f["status"] in OPEN_FINDING_STATUSES:
            dl = f.get("remediation_deadline")
            if dl and parse_iso(dl) < now:
                f["deadline_exceeded"] = True

    # Product posture re-evaluation
    for p in store.products.values():
        recompute_product_counts(p)
        reevaluate_product_posture(p)


# ---------------------------------------------------------------------------
# Vulnerability intake
# ---------------------------------------------------------------------------

def propagate_vulnerability(vuln):
    """Create findings for every BOM entry shipping a component matching the PURL."""
    pattern = vuln.get("affected_package_url") or ""
    matched_components = [c for c in store.components.values() if c["package_url"] == pattern]
    affected_products = set()
    for comp in matched_components:
        for e in store.bom_entries.values():
            if e["component_id"] != comp["id"]:
                continue
            bom = store.boms.get(e["bom_id"])
            if not bom:
                continue
            # Avoid duplicate findings for same vulnerability+entry
            existing = [f for f in store.findings.values()
                        if f["bom_entry_id"] == e["id"] and f["vulnerability_id"] == vuln["id"]]
            if existing:
                continue
            f = base_resource()
            f.update({
                "product_id": bom["product_id"],
                "bom_entry_id": e["id"],
                "vulnerability_id": vuln["id"],
                "detected_at": store.now_iso(),
                "status": "OPEN",
                "remediation_deadline": None,
                "remediation_component_id": None,
                "remediation_status": "NOT_STARTED",
                "verification_evidence_uri": None,
                "deadline_exceeded": False,
            })
            store.findings[f["id"]] = f
            recompute_entry_vuln_max(e)
            affected_products.add(bom["product_id"])
    for pid in affected_products:
        product = store.products.get(pid)
        if product:
            recompute_product_counts(product)
            reevaluate_product_posture(product)


def compute_remediation_deadline(finding, vuln, product):
    """SLA: detected_at + SLA_DAYS[severity]; compressed by license_change_flag / BLOCKED."""
    detected = parse_iso(finding["detected_at"])
    days = SLA_DAYS.get(vuln["severity"], 180)
    deadline = detected + timedelta(days=days)
    if vuln.get("license_change_flag"):
        deadline = min(deadline, detected + timedelta(days=14))
    if product.get("compliance_posture") == "BLOCKED":
        deadline = min(deadline, store.now() + timedelta(days=3))
    return deadline


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
