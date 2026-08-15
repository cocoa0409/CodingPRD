"""License classification, obligation determination, posture calculations."""

from decimal import Decimal, ROUND_HALF_UP

# --- License classification catalogue (18 recognized identifiers) ---
PERMISSIVE_LICENSES = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Apache-2.0", "Zlib", "Unlicense"}
WEAK_COPYLEFT_LICENSES = {"LGPL-2.1", "LGPL-3.0", "MPL-2.0", "EPL-2.0", "CDDL-1.0"}
STRONG_COPYLEFT_LICENSES = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "SSPL-1.0"}
RESTRICTED_LICENSES = {"CC-BY-NC-4.0", "CC-BY-SA-4.0", "proprietary-source-available"}
PROHIBITED_LICENSES = {"WTFPL", "unlicensed", "proprietary-no-grant"}

VALID_CLASSIFICATIONS = {"PERMISSIVE", "WEAK_COPYLEFT", "STRONG_COPYLEFT", "RESTRICTED", "PROHIBITED"}


def classify_license(discovered_spdx, distribution_model=None):
    """Compute license_policy_classification from discovered SPDX id.

    Conservative default: null/unrecognized -> RESTRICTED.
    Context adjustment: AGPL-3.0 inside a SaaS product -> PROHIBITED.
    SSPL-1.0 in a SaaS context -> PROHIBITED.
    """
    spdx = discovered_spdx
    if spdx is None or spdx == "":
        return "RESTRICTED"

    if spdx in PERMISSIVE_LICENSES:
        base = "PERMISSIVE"
    elif spdx in WEAK_COPYLEFT_LICENSES:
        base = "WEAK_COPYLEFT"
    elif spdx in STRONG_COPYLEFT_LICENSES:
        base = "STRONG_COPYLEFT"
    elif spdx in RESTRICTED_LICENSES:
        base = "RESTRICTED"
    elif spdx in PROHIBITED_LICENSES:
        base = "PROHIBITED"
    else:
        # Unrecognized -> conservative RESTRICTED
        return "RESTRICTED"

    # Context adjustments
    if distribution_model == "SaaS":
        if spdx == "AGPL-3.0":
            return "PROHIBITED"
        if spdx == "SSPL-1.0":
            return "PROHIBITED"
    return base


def effective_classification(component):
    """policy_override_classification if set, else license_policy_classification.

    PRD §3.2: a freshly registered component has "no policy classification
    computed yet" — classification is computed from the *discovered* license
    when a scan completes, so before that point there is no effective
    classification to report (None).
    """
    if component is None:
        return None
    override = component.get("policy_override_classification")
    if override:
        return override
    return component.get("license_policy_classification")


def determine_obligation(eff_classification, distribution_model, dependency_scope, license_spdx=None):
    """Compute obligation_determination for a BOM entry.

    Fixed order per PRD section 3.4:
    1. PROHIBITED -> PROHIBITED_USE
    2. scope in {TEST, DEV} -> NONE
    3. PERMISSIVE -> ATTRIBUTION_ONLY
    4. WEAK_COPYLEFT -> SaaS: ATTRIBUTION_ONLY; else SOURCE_OFFER
    5. STRONG_COPYLEFT -> AGPL-3.0+SaaS: FULL_SOURCE_DISCLOSURE;
       ON_PREMISE/EMBEDDED: SOURCE_DISCLOSURE; MOBILE_APP: FULL_SOURCE_DISCLOSURE
    6. RESTRICTED -> SOURCE_DISCLOSURE (approval tracked separately)
    """
    if eff_classification == "PROHIBITED":
        return "PROHIBITED_USE"
    if dependency_scope in ("TEST", "DEV"):
        return "NONE"
    if eff_classification == "PERMISSIVE":
        return "ATTRIBUTION_ONLY"
    if eff_classification == "WEAK_COPYLEFT":
        if distribution_model == "SaaS":
            return "ATTRIBUTION_ONLY"
        return "SOURCE_OFFER"
    if eff_classification == "STRONG_COPYLEFT":
        if distribution_model == "SaaS" and license_spdx == "AGPL-3.0":
            return "FULL_SOURCE_DISCLOSURE"
        if distribution_model in ("ON_PREMISE", "EMBEDDED"):
            return "SOURCE_DISCLOSURE"
        if distribution_model == "MOBILE_APP":
            return "FULL_SOURCE_DISCLOSURE"
        if distribution_model == "SaaS":
            # Strong copyleft non-AGPL in SaaS: conservative source disclosure
            return "SOURCE_DISCLOSURE"
        return "SOURCE_DISCLOSURE"
    if eff_classification == "RESTRICTED":
        return "SOURCE_DISCLOSURE"
    return "NONE"


def obligation_type_for(determination):
    """Map obligation_determination to a ticket obligation_type."""
    return {
        "ATTRIBUTION_ONLY": "ATTRIBUTION",
        "SOURCE_OFFER": "SOURCE_OFFER",
        "SOURCE_DISCLOSURE": "SOURCE_DELIVERY",
        "FULL_SOURCE_DISCLOSURE": "COPYLEFT_COMPLIANCE",
        "PROHIBITED_USE": "LICENSE_TEXT",
    }.get(determination, "LICENSE_TEXT")


def compute_bom_posture(entries, product, approved_component_ids):
    """Compute bom_posture (GREEN/YELLOW/RED) from entries.

    entries: list of BomEntry dicts (with component data accessible via resolver)
    approved_component_ids: set of component ids with an APPROVED LicenseApprovalRequest
    """
    prohibited_count = 0
    restricted_count = 0
    copyleft_count = 0
    high_vuln_count = 0
    for e in entries:
        eff = e.get("_effective_classification")
        if eff == "PROHIBITED":
            prohibited_count += 1
        elif eff == "RESTRICTED":
            if e.get("component_id") not in approved_component_ids:
                restricted_count += 1
        elif eff in ("WEAK_COPYLEFT", "STRONG_COPYLEFT"):
            copyleft_count += 1
        if e.get("vulnerability_severity_max") in ("HIGH", "CRITICAL"):
            high_vuln_count += 1

    if prohibited_count > 0:
        return "RED"
    if restricted_count > 0 or high_vuln_count > 0:
        return "YELLOW"
    # strict_mode: EMBEDDED — any WEAK_COPYLEFT also triggers YELLOW
    if product.get("distribution_model") == "EMBEDDED":
        for e in entries:
            if e.get("_effective_classification") == "WEAK_COPYLEFT":
                return "YELLOW"
    return "GREEN"


def round2(value):
    """Round to 2 decimal places, ROUND_HALF_UP. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)
