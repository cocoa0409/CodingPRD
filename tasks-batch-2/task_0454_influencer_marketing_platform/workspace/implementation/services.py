"""Cross-entity helpers, cascades, and shared lookups."""
from db import db, bump
from errors import err
import derive


# ----- existence lookups (ERR_NOT_FOUND) -----

def get_brand(brand_id):
    b = db.brands.get(brand_id)
    if not b:
        raise err("ERR_NOT_FOUND", "Brand not found")
    return b


def get_creator(creator_id):
    c = db.creators.get(creator_id)
    if not c:
        raise err("ERR_NOT_FOUND", "Creator not found")
    return c


def get_campaign(campaign_id):
    c = db.campaigns.get(campaign_id)
    if not c:
        raise err("ERR_NOT_FOUND", "Campaign not found")
    return c


def get_deliverable(deliverable_id):
    d = db.deliverables.get(deliverable_id)
    if not d:
        raise err("ERR_NOT_FOUND", "Deliverable not found")
    return d


def get_offer(offer_id):
    o = db.offers.get(offer_id)
    if not o:
        raise err("ERR_NOT_FOUND", "Offer not found")
    return o


def get_contract(contract_id):
    c = db.contracts.get(contract_id)
    if not c:
        raise err("ERR_NOT_FOUND", "Contract not found")
    return c


def get_content_submission(sub_id):
    s = db.content_submissions.get(sub_id)
    if not s:
        raise err("ERR_NOT_FOUND", "Content submission not found")
    return s


def get_attribution_asset(asset_id):
    a = db.attribution_assets.get(asset_id)
    if not a:
        raise err("ERR_NOT_FOUND", "Attribution asset not found")
    return a


def get_payout(payout_id):
    p = db.payouts.get(payout_id)
    if not p:
        raise err("ERR_NOT_FOUND", "Payout not found")
    return p


def get_tax_form(form_id):
    t = db.tax_forms.get(form_id)
    if not t:
        raise err("ERR_NOT_FOUND", "Tax form not found")
    return t


def get_brand_safety_flag(flag_id):
    f = db.brand_safety_flags.get(flag_id)
    if not f:
        raise err("ERR_NOT_FOUND", "Brand-safety flag not found")
    return f


# ----- contract brand lookup -----

def contract_brand(contract):
    camp = db.campaigns.get(contract["campaign_id"])
    if not camp:
        return None
    return db.brands.get(camp["brand_id"])


# ----- bubble-up: contract fulfillment after content approval -----

def maybe_fulfill_contract(contract):
    """If every Deliverable of the contract's campaign now has an APPROVED
    submission tied to this contract, transition ACTIVE -> FULFILLED."""
    if contract["status"] != "ACTIVE":
        return
    campaign_id = contract["campaign_id"]
    deliverables = [d for d in db.deliverables.values() if d["campaign_id"] == campaign_id]
    if not deliverables:
        return
    for d in deliverables:
        approved = any(
            s for s in db.content_submissions.values()
            if s["deliverable_id"] == d["id"]
            and s["contract_id"] == contract["id"]
            and s["status"] == "APPROVED"
        )
        if not approved:
            return
    contract["status"] = "FULFILLED"
    bump(contract)
