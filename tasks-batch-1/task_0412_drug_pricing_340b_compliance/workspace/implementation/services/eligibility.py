"""Eligibility cascade for a dispense. PRD §3.5, scaffold §1.3
eligibility_determination. Five prongs in fixed order; first failing prong
determines (classification_status, eligibility_reason)."""

ELIGIBLE_PRESCRIBER_TYPES = {"EMPLOYED", "CONTRACTED"}


def determine(patient, prescriber, child_site, covered_entity):
    """Return (classification_status, eligibility_reason).

    child_site is None when the dispense names no child site.
    """
    # 1. Relationship prong
    if patient["has_ce_care_record"] is False:
        return "CLASSIFIED_WAC", "INELIGIBLE_NO_RELATIONSHIP"
    # 2. Responsibility prong
    if patient["ce_retains_responsibility"] is False:
        return "CLASSIFIED_WAC", "INELIGIBLE_NO_RESPONSIBILITY"
    # 3. Prescriber prong
    if prescriber["relationship_type"] not in ELIGIBLE_PRESCRIBER_TYPES:
        return "CLASSIFIED_WAC", "INELIGIBLE_PRESCRIBER"
    # 4. Site prong (only when dispense is at a child site)
    if child_site is not None and child_site["registered"] is False:
        return "CLASSIFIED_WAC", "INELIGIBLE_UNREGISTERED_SITE"
    # 5. Medicaid carve-out prong
    if patient["medicaid_ffs_enrolled"] is True and covered_entity["medicaid_billing_mode"] == "CARVE_OUT":
        return "CLASSIFIED_WAC", "CARVED_OUT_MEDICAID"
    return "CLASSIFIED_340B", "ELIGIBLE_340B"
