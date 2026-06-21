"""Resource lookup and ownership-chain resolution (PRD §2.1, §2.5).

Three roles are entity-backed: Publisher, Advertiser, Listener. X-User-ID is the
id of that actor and is compared along the ownership chain. PlatformAdmin is
opaque and is never subject to ownership checks.
"""

import db
import errors


# ---------------------------------------------------------------------------
# Existence lookups — raise ERR_NOT_FOUND (PRD §2.5).
# ---------------------------------------------------------------------------

def _get_or_404(collection, _id):
    if _id is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Missing reference")
    obj = collection.get(_id)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return obj


def get_publisher(_id):
    return _get_or_404(db.db.publishers, _id)


def get_advertiser(_id):
    return _get_or_404(db.db.advertisers, _id)


def get_listener(_id):
    return _get_or_404(db.db.listeners, _id)


def get_show(_id):
    return _get_or_404(db.db.shows, _id)


def get_episode(_id):
    return _get_or_404(db.db.episodes, _id)


def get_media_asset(_id):
    return _get_or_404(db.db.media_assets, _id)


def get_feed(_id):
    return _get_or_404(db.db.feeds, _id)


def get_subscription(_id):
    return _get_or_404(db.db.subscriptions, _id)


def get_distribution(_id):
    return _get_or_404(db.db.distributions, _id)


def get_campaign(_id):
    return _get_or_404(db.db.ad_campaigns, _id)


def get_placement(_id):
    return _get_or_404(db.db.ad_placements, _id)


def get_download_event(_id):
    return _get_or_404(db.db.download_events, _id)


def get_payout(_id):
    return _get_or_404(db.db.payout_statements, _id)


# ---------------------------------------------------------------------------
# Ownership checks — raise ERR_NOT_RESOURCE_OWNER (PRD §2.1, §2.5).
# PlatformAdmin is never subject to ownership.
# ---------------------------------------------------------------------------

def _fail_owner():
    raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Caller does not own the target resource")


def assert_publisher_owns_show(caller, show):
    if caller.role == "PlatformAdmin":
        return
    if caller.role != "Publisher" or show["publisher_id"] != caller.user_id:
        _fail_owner()


def assert_publisher_owns_episode(caller, episode):
    if caller.role == "PlatformAdmin":
        return
    show = db.db.shows.get(episode["show_id"])
    if show is None or caller.role != "Publisher" or show["publisher_id"] != caller.user_id:
        _fail_owner()


def assert_publisher_owns_feed(caller, feed):
    if caller.role == "PlatformAdmin":
        return
    show = db.db.shows.get(feed["show_id"])
    if show is None or caller.role != "Publisher" or show["publisher_id"] != caller.user_id:
        _fail_owner()


def assert_publisher_owns_media(caller, media):
    if caller.role == "PlatformAdmin":
        return
    episode = db.db.episodes.get(media["episode_id"])
    if episode is None:
        _fail_owner()
    show = db.db.shows.get(episode["show_id"])
    if show is None or caller.role != "Publisher" or show["publisher_id"] != caller.user_id:
        _fail_owner()


def assert_publisher_owns_distribution(caller, dist):
    if caller.role == "PlatformAdmin":
        return
    show = db.db.shows.get(dist["show_id"])
    if show is None or caller.role != "Publisher" or show["publisher_id"] != caller.user_id:
        _fail_owner()


def assert_advertiser_owns_campaign(caller, campaign):
    if caller.role == "PlatformAdmin":
        return
    if caller.role != "Advertiser" or campaign["advertiser_id"] != caller.user_id:
        _fail_owner()


def assert_advertiser_owns_placement(caller, placement):
    if caller.role == "PlatformAdmin":
        return
    campaign = db.db.ad_campaigns.get(placement["campaign_id"])
    if campaign is None or caller.role != "Advertiser" or campaign["advertiser_id"] != caller.user_id:
        _fail_owner()


def assert_listener_owns_subscription(caller, sub):
    if caller.role == "PlatformAdmin":
        return
    if caller.role != "Listener" or sub["listener_id"] != caller.user_id:
        _fail_owner()
