"""Existence + ownership lookups (PRD §2.8, §2.1).

Existence is checked left-to-right, each missing id yielding its specific
ERR_{RESOURCE}_NOT_FOUND code. Ownership checks compare a resource's owning
member to the acting Member's X-User-ID.
"""
import db
import errors


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise errors.err(errors.ERR_MEMBER_NOT_FOUND)
    return m


def get_plan(plan_id):
    p = db.plans.get(plan_id)
    if p is None:
        raise errors.err(errors.ERR_PLAN_NOT_FOUND)
    return p


def get_zone(zone_id):
    z = db.shipping_zones.get(zone_id)
    if z is None:
        raise errors.err(errors.ERR_SHIPPING_ZONE_NOT_FOUND)
    return z


def get_recipe(recipe_id):
    r = db.recipes.get(recipe_id)
    if r is None:
        raise errors.err(errors.ERR_RECIPE_NOT_FOUND)
    return r


def get_subscription(sub_id):
    s = db.subscriptions.get(sub_id)
    if s is None:
        raise errors.err(errors.ERR_SUBSCRIPTION_NOT_FOUND)
    return s


def get_weekly_box(box_id):
    b = db.weekly_boxes.get(box_id)
    if b is None:
        raise errors.err(errors.ERR_WEEKLY_BOX_NOT_FOUND)
    return b


def get_box_recipe(box_recipe_id, box_id=None):
    br = db.box_recipes.get(box_recipe_id)
    if br is None or (box_id is not None and br["box_id"] != box_id):
        raise errors.err(errors.ERR_BOX_RECIPE_NOT_FOUND)
    return br


def get_referral(ref_id):
    r = db.referrals.get(ref_id)
    if r is None:
        raise errors.err(errors.ERR_REFERRAL_NOT_FOUND)
    return r


def member_of_subscription(sub):
    return sub["member_id"]


def member_of_box(box):
    sub = db.subscriptions.get(box["subscription_id"])
    if sub is None:
        return None
    return sub["member_id"]


def assert_member_owns_subscription(ctx, sub):
    """Member ownership: subscription.member_id must equal X-User-ID."""
    if ctx.role == "Member" and sub["member_id"] != ctx.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED)


def assert_member_owns_box(ctx, box):
    """Member ownership: the box's subscription's member must equal X-User-ID."""
    if ctx.role == "Member":
        owner = member_of_box(box)
        if owner != ctx.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED)


def assert_member_self(ctx, member_id):
    """Member ownership for member-scoped reads: target must be the actor."""
    if ctx.role == "Member" and member_id != ctx.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED)
