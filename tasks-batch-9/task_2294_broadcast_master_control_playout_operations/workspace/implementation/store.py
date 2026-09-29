"""In-memory data store. Every collection starts empty on every boot: no seeding."""
import copy
import itertools
import uuid

import timeutil
from constants import DEFAULT_CLOCK_UTC

transmitters = {}
multiplexes = {}
channels = {}
operators = {}
assets = {}
qc_reports = {}
playlists = {}
items = {}
spot_orders = {}
feed_windows = {}
overrides = {}
faults = {}
asrun = {}
notifications = {}

_seq = itertools.count(1)
_clock = {"value": DEFAULT_CLOCK_UTC}

COLLECTIONS = (transmitters, multiplexes, channels, operators, assets, qc_reports,
               playlists, items, spot_orders, feed_windows, overrides, faults,
               asrun, notifications)

_pending = {"snapshot": None}


def begin():
    """Open a request-scoped transaction (PRD 2.8: a refused request writes nothing)."""
    _pending["snapshot"] = ([copy.deepcopy(c) for c in COLLECTIONS], _clock["value"])


def rollback():
    """Undo every write the current request made, leaving no partial state behind."""
    snap = _pending["snapshot"]
    if snap is None:
        return
    saved, clock_value = snap
    for collection, restored in zip(COLLECTIONS, saved):
        collection.clear()
        collection.update(restored)
    _clock["value"] = clock_value
    _pending["snapshot"] = None


def commit():
    _pending["snapshot"] = None


def new_id():
    return str(uuid.uuid4())


def clock():
    return _clock["value"]


def set_clock(value):
    _clock["value"] = value


def base(versioned=True):
    stamp = timeutil.now_audit()
    rec = {"id": new_id(), "created_at": stamp}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next(_seq)
    return rec


def add(collection, rec):
    collection[rec["id"]] = rec
    return rec


def bump(rec):
    """Refresh updated_at and increment version (PRD 2.5)."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = timeutil.now_audit()
    return rec


def rows(collection):
    """All rows in creation order."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --- relationship helpers --------------------------------------------------

def multiplexes_of(transmitter_id):
    return [m for m in rows(multiplexes) if m["transmitter_id"] == transmitter_id]


def channels_of(multiplex_id):
    return [c for c in rows(channels) if c["multiplex_id"] == multiplex_id]


def channels_of_transmitter(transmitter_id):
    out = []
    for mux in multiplexes_of(transmitter_id):
        out.extend(channels_of(mux["id"]))
    return out


def playlists_of(channel_id):
    return [p for p in rows(playlists) if p["channel_id"] == channel_id]


def items_of(playlist_id):
    return sorted(
        [i for i in items.values() if i["playlist_id"] == playlist_id],
        key=lambda i: (i["sequence_number"], i["_seq"]),
    )


def items_for_asset(asset_id):
    return [i for i in rows(items) if i.get("asset_id") == asset_id]


def items_for_order(order_id):
    return [i for i in rows(items) if i.get("spot_order_id") == order_id]


def asrun_of(playlist_id):
    return sorted(
        [a for a in asrun.values() if a["playlist_id"] == playlist_id],
        key=lambda a: (a["event_utc"], a["_seq"]),
    )


def asrun_of_item(item_id):
    return sorted(
        [a for a in asrun.values() if a["playlist_item_id"] == item_id],
        key=lambda a: (a["event_utc"], a["_seq"]),
    )


def windows_of(channel_id):
    return [w for w in rows(feed_windows) if w["channel_id"] == channel_id]


def windows_of_multiplex(multiplex_id):
    out = []
    for ch in channels_of(multiplex_id):
        out.extend(windows_of(ch["id"]))
    return out


def overrides_of(channel_id):
    return [o for o in rows(overrides) if o["channel_id"] == channel_id]


def faults_of_channel(channel_id):
    return [f for f in rows(faults) if f.get("channel_id") == channel_id]


def faults_of_transmitter(transmitter_id):
    return [f for f in rows(faults) if f.get("transmitter_id") == transmitter_id]


def notifications_of(transmitter_id):
    return [n for n in rows(notifications) if n["transmitter_id"] == transmitter_id]


def channel_of_playlist(playlist):
    return channels.get(playlist["channel_id"])


def multiplex_of_channel(channel):
    return multiplexes.get(channel["multiplex_id"])


def transmitter_of_channel(channel):
    mux = multiplex_of_channel(channel)
    if mux is None:
        return None
    return transmitters.get(mux["transmitter_id"])


def on_air_playlist(channel_id):
    for p in playlists_of(channel_id):
        if p["status"] == "ON_AIR":
            return p
    return None
