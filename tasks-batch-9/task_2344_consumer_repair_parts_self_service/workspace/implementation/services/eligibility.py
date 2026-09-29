"""self_repair_eligibility_decision, warranty_impact_classification, self_repair_risk_index."""
from fractions import Fraction

import db
from services.compliance import published_revision, select_compat
from util import round_half_up

TIER_WEIGHT = {
    "TIER_A_SELF_SERVICE": Fraction(10, 100),
    "TIER_B_GUIDED": Fraction(40, 100),
    "TIER_C_AUTHORIZED_ONLY": Fraction(80, 100),
    "TIER_D_NON_SERVICEABLE": Fraction(1),
}

SAFETY_WEIGHT = {
    "UNRESTRICTED": Fraction(10, 100),
    "SAFETY_RESTRICTED_BATTERY": Fraction(60, 100),
    "SAFETY_RESTRICTED_HIGH_VOLTAGE": Fraction(90, 100),
    "PAIRED_SECURITY": Fraction(70, 100),
}


def effective_safety_class(part, profile):
    """Pairing restrictions collapse to UNRESTRICTED where the region forbids them."""
    if part["safety_class"] == "PAIRED_SECURITY" and not profile.get("allows_pairing_restriction"):
        return "UNRESTRICTED"
    return part["safety_class"]


def decide(model, part, profile, requester_class):
    """Return (decision, tool_rental_part_id) — first matching branch wins."""
    at = db.now()
    compat = select_compat(part["id"], model["id"], at)
    is_consumer = requester_class == "SELF_REPAIR_CONSUMER"

    if compat is None:
        return "BLOCKED_NO_COMPATIBILITY", None
    if part["status"] != "PUBLISHED":
        return "BLOCKED_PART_UNAVAILABLE", None
    if model["repairability_tier"] == "TIER_D_NON_SERVICEABLE":
        return "BLOCKED_TIER", None

    effective = effective_safety_class(part, profile)

    if is_consumer and effective in ("SAFETY_RESTRICTED_HIGH_VOLTAGE", "PAIRED_SECURITY"):
        return "BLOCKED_SAFETY", None
    if (
        is_consumer
        and effective == "SAFETY_RESTRICTED_BATTERY"
        and model.get("published_safety_sheet_revision_number") is None
    ):
        return "BLOCKED_NO_MANUAL", None
    if model.get("published_disassembly_revision_number") is None:
        return "BLOCKED_NO_MANUAL", None
    if is_consumer and not compat.get("self_service_eligible"):
        return "BLOCKED_TIER", None
    if compat.get("required_tool_part_id") is not None or (
        is_consumer and effective == "SAFETY_RESTRICTED_BATTERY"
    ):
        return "ELIGIBLE_WITH_TOOL_RENTAL", compat.get("required_tool_part_id")
    return "ELIGIBLE", None


def classify_warranty(model, part, provider, requester_class):
    """Reads the part's *stored* safety_class, never the region-adjusted one."""
    if requester_class == "AUTHORIZED_PROVIDER" and provider is not None \
            and provider.get("authorization_status") == "AUTHORIZED":
        return "WARRANTY_PRESERVED"
    if part["safety_class"] == "UNRESTRICTED" and model["repairability_tier"] == "TIER_A_SELF_SERVICE":
        return "WARRANTY_PRESERVED_WITH_LOG"
    if part["safety_class"] == "SAFETY_RESTRICTED_BATTERY":
        return "WARRANTY_LIMITED_COMPONENT_EXCLUSION"
    return "WARRANTY_VOID_AFFECTED_SUBSYSTEM"


def risk_index(model, part):
    at = db.now()
    compat = select_compat(part["id"], model["id"], at)
    tier_w = TIER_WEIGHT.get(model["repairability_tier"], Fraction(0))
    safety_w = SAFETY_WEIGHT.get(part["safety_class"], Fraction(0))
    if compat is None:
        install_w = Fraction(0)
    else:
        install_w = min(Fraction(1), Fraction(compat["install_minutes"], 120))
    raw = (
        Fraction(40, 100) * tier_w
        + Fraction(35, 100) * safety_w
        + Fraction(25, 100) * install_w
    )
    return round_half_up(100 * min(Fraction(1), raw))


def side_outputs(model):
    """pinned_manual_revision_id and liability_warning_version, always emitted."""
    guide = published_revision(model["id"], "DISASSEMBLY_GUIDE")
    if guide is None:
        return None, None
    warning = "LW-%s-R%d" % (model["model_code"], guide["revision_number"])
    return guide["id"], warning
