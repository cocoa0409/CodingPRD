"""Serialization overlays for derived/computed fields (PRD §1.1)."""

from core import serialize, STORE
from services import applicant_active_count, lease_occupancy_count

REQUIRED_SIGNER_ROLES = ["LANDLORD", "LEASEHOLDER", "APPLICANT"]


def present_applicant(a):
    d = serialize(a)
    d["active_application_count"] = applicant_active_count(a["id"])
    return d


def present_lease(l):
    d = serialize(l)
    d["active_occupancy_count"] = lease_occupancy_count(l["id"])
    return d


def collected_roles_for(agreement_id):
    roles = []
    for s in STORE["signatures"].values():
        if s["agreement_id"] == agreement_id and s["signer_role"] not in roles:
            roles.append(s["signer_role"])
    return roles


def present_agreement(ag):
    d = serialize(ag)
    collected = collected_roles_for(ag["id"])
    d["required_signer_roles"] = list(REQUIRED_SIGNER_ROLES)
    d["collected_signer_roles"] = collected
    d["is_fully_signed"] = set(REQUIRED_SIGNER_ROLES).issubset(set(collected))
    return d
