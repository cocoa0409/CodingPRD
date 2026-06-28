"""Existence + ownership lookups (PRD §2.5, §2.1).

Path resource ids are validated strictly left to right; the first missing one
yields its own not-found error (PRD §2.5).
"""
import errors
from db import db


def get_creator(creator_id):
    rec = db.creators.get(creator_id)
    if rec is None:
        errors.fail(errors.ERR_CREATOR_NOT_FOUND, "Creator not found")
    return rec


def get_tier(tier_id):
    rec = db.tiers.get(tier_id)
    if rec is None:
        errors.fail(errors.ERR_TIER_NOT_FOUND, "Tier not found")
    return rec


def get_patron(patron_id):
    rec = db.patrons.get(patron_id)
    if rec is None:
        errors.fail(errors.ERR_PATRON_NOT_FOUND, "Patron not found")
    return rec


def get_pledge(pledge_id):
    rec = db.pledges.get(pledge_id)
    if rec is None:
        errors.fail(errors.ERR_PLEDGE_NOT_FOUND, "Pledge not found")
    return rec


def get_charge(charge_id):
    rec = db.charges.get(charge_id)
    if rec is None:
        errors.fail(errors.ERR_CHARGE_NOT_FOUND, "Charge not found")
    return rec


def get_post(post_id):
    rec = db.posts.get(post_id)
    if rec is None:
        errors.fail(errors.ERR_POST_NOT_FOUND, "Post not found")
    return rec


def get_conversation(conversation_id):
    rec = db.conversations.get(conversation_id)
    if rec is None:
        errors.fail(errors.ERR_CONVERSATION_NOT_FOUND, "Conversation not found")
    return rec


def get_payout(payout_id):
    rec = db.payouts.get(payout_id)
    if rec is None:
        errors.fail(errors.ERR_PAYOUT_NOT_FOUND, "Payout not found")
    return rec


def get_offer(offer_id):
    rec = db.win_back_offers.get(offer_id)
    if rec is None:
        errors.fail(errors.ERR_OFFER_NOT_FOUND, "Win-back offer not found")
    return rec


def get_message(message_id):
    rec = db.messages.get(message_id)
    if rec is None:
        errors.fail(errors.ERR_MESSAGE_NOT_FOUND, "Message not found")
    return rec


def get_post_access(access_id):
    rec = db.post_accesses.get(access_id)
    if rec is None:
        errors.fail(errors.ERR_ACCESS_NOT_FOUND, "PostAccess not found")
    return rec


def require_creator_owner(ctx, creator_id):
    """Entity-backed Creator acting on owned resource (PRD §2.1 priority 3)."""
    if ctx.is_creator and ctx.user_id != creator_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Creator does not own this resource")


def require_patron_owner(ctx, patron_id):
    """Entity-backed Patron acting on owned resource (PRD §2.1 priority 3)."""
    if ctx.is_patron and ctx.user_id != patron_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Patron does not own this resource")
