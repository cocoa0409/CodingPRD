"""Qualification document logic + advertiser qualification status recomputation."""
from .. import store
from ..errors import ApiError


REQUIRED_DOC_BY_INDUSTRY = {
    "MEDICAL": "MEDICAL_PERMIT",
    "FINANCIAL": "FINANCIAL_LICENSE",
    "EDUCATION": "EDUCATION_PERMIT",
}


def docs_for_advertiser(advertiser_id: str) -> list[dict]:
    return [d for d in store.list_all("QualificationDoc") if d.get("advertiser_id") == advertiser_id]


def recompute_qualification_status(advertiser: dict) -> str:
    """Recompute Advertiser.qualification_status from its QualificationDocs."""
    docs = docs_for_advertiser(advertiser["id"])
    industry = advertiser.get("industry_category")

    if not docs:
        new = "UNVERIFIED"
    elif any(d["review_status"] == "REJECTED" for d in docs):
        new = "REJECTED"
    elif any(d["review_status"] == "PENDING" for d in docs):
        new = "UNDER_REVIEW"
    else:
        # All approved at this point — check industry requirement.
        if industry == "GENERAL":
            new = "VERIFIED"
        else:
            req = REQUIRED_DOC_BY_INDUSTRY.get(industry)
            has_req = any(d["doc_type"] == req and d["review_status"] == "APPROVED" for d in docs)
            new = "VERIFIED" if has_req else "UNDER_REVIEW"

    advertiser["qualification_status"] = new
    return new


def maybe_activate_advertiser(advertiser: dict):
    """Move PENDING → ACTIVE on first qualification_status=VERIFIED with funded balance."""
    if advertiser.get("status") != "PENDING":
        return
    if advertiser.get("qualification_status") != "VERIFIED":
        return
    if int(advertiser.get("balance_cents", 0)) + int(advertiser.get("credit_line_cents", 0)) > 0:
        advertiser["status"] = "ACTIVE"
        store.touch(advertiser)


def cascade_reject_creatives_on_qual_rejected(advertiser: dict):
    """When qualification flips back to REJECTED from prior VERIFIED, reject all APPROVED creatives."""
    from .. import store as _store

    for cr in _store.list_all("Creative"):
        if cr.get("advertiser_id") != advertiser["id"]:
            continue
        if cr.get("review_status") == "APPROVED":
            cr["review_status"] = "REJECTED"
            _store.touch(cr)
            ag = _store.get("AdGroup", cr["ad_group_id"])
            if ag:
                ag["approved_creative_count"] = max(0, int(ag.get("approved_creative_count", 0)) - 1)
                _store.touch(ag)
                # Re-evaluate AdGroup status
                if ag.get("status") in ("READY", "RUNNING") and ag["approved_creative_count"] == 0:
                    ag["status"] = "DISAPPROVED"
                    _store.touch(ag)
