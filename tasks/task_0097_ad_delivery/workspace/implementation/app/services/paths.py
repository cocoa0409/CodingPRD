"""Hierarchical path resolution — left-to-right with the first failing segment
producing the matching not-found error.
"""
from .. import store
from ..auth import ENTITY_BACKED_ROLES, current_role, current_user_id
from ..errors import ApiError


def _enforce_entity_backed_scope(advertiser_id: str) -> None:
    """PRD §2.1: ownership checks compare the resource's owning
    advertiser_id to the advertiser referenced by the AccountUser the
    caller's X-User-ID resolves to. If the calling X-User-ID is not an
    AccountUser of this advertiser, reject as forbidden.
    """
    role = current_role()
    if role not in ENTITY_BACKED_ROLES:
        return
    uid = current_user_id()
    # Find an AccountUser with matching external_user_id under THIS advertiser.
    for u in store.list_all("AccountUser"):
        if (
            u.get("advertiser_id") == advertiser_id
            and u.get("external_user_id") == uid
        ):
            return
    raise ApiError("ERR_FORBIDDEN_ROLE")


def resolve_advertiser(advertiser_id: str) -> dict:
    rec = store.get("Advertiser", advertiser_id)
    if not rec:
        raise ApiError("ERR_ADVERTISER_NOT_FOUND")
    _enforce_entity_backed_scope(advertiser_id)
    return rec


def resolve_campaign(advertiser_id: str, campaign_id: str) -> tuple[dict, dict]:
    adv = resolve_advertiser(advertiser_id)
    camp = store.get("Campaign", campaign_id)
    if not camp or camp.get("advertiser_id") != advertiser_id:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND")
    return adv, camp


def resolve_ad_group(advertiser_id: str, campaign_id: str, ad_group_id: str) -> tuple[dict, dict, dict]:
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    ag = store.get("AdGroup", ad_group_id)
    if not ag or ag.get("campaign_id") != campaign_id:
        raise ApiError("ERR_AD_GROUP_NOT_FOUND")
    return adv, camp, ag


def resolve_creative(advertiser_id: str, campaign_id: str, ad_group_id: str, creative_id: str) -> tuple[dict, dict, dict, dict]:
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    cr = store.get("Creative", creative_id)
    if not cr or cr.get("ad_group_id") != ad_group_id:
        raise ApiError("ERR_CREATIVE_NOT_FOUND")
    return adv, camp, ag, cr


def resolve_creative_flat(creative_id: str) -> dict:
    cr = store.get("Creative", creative_id)
    if not cr:
        raise ApiError("ERR_CREATIVE_NOT_FOUND")
    return cr


def resolve_qualification(advertiser_id: str, doc_id: str) -> tuple[dict, dict]:
    adv = resolve_advertiser(advertiser_id)
    doc = store.get("QualificationDoc", doc_id)
    if not doc or doc.get("advertiser_id") != advertiser_id:
        raise ApiError("ERR_QUALIFICATION_DOC_NOT_FOUND")
    return adv, doc


def resolve_account_user(advertiser_id: str, user_id: str) -> tuple[dict, dict]:
    adv = resolve_advertiser(advertiser_id)
    u = store.get("AccountUser", user_id)
    if not u or u.get("advertiser_id") != advertiser_id:
        raise ApiError("ERR_INVALID_REQUEST", "AccountUser not found under advertiser.")
    return adv, u


def resolve_wallet_tx(advertiser_id: str, tx_id: str) -> tuple[dict, dict]:
    adv = resolve_advertiser(advertiser_id)
    tx = store.get("WalletTransaction", tx_id)
    if not tx or tx.get("advertiser_id") != advertiser_id:
        raise ApiError("ERR_WALLET_TX_NOT_FOUND")
    return adv, tx


def resolve_billing_event(event_id: str) -> dict:
    rec = store.get("BillingEvent", event_id)
    if not rec:
        raise ApiError("ERR_BILLING_EVENT_NOT_FOUND")
    return rec


def resolve_conversion(conversion_id: str) -> dict:
    rec = store.get("ConversionEvent", conversion_id)
    if not rec:
        raise ApiError("ERR_CONVERSION_NOT_FOUND")
    return rec


def resolve_auction(auction_id: str) -> dict:
    rec = store.get("AuctionEvent", auction_id)
    if not rec:
        raise ApiError("ERR_INVALID_REQUEST", "Auction not found.")
    return rec
