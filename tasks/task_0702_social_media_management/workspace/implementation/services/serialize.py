"""Serialize internal entity dicts into API output (strips private fields)."""

# Field order matters little for tests, but we explicitly expose each entity's
# public field set so internal bookkeeping keys (prefixed with "_") never leak.

PRIVATE_PREFIX = "_"


def _public(obj):
    return {k: v for k, v in obj.items() if not k.startswith(PRIVATE_PREFIX)}


def client_out(c):
    return _public(c)


def package_out(p):
    return _public(p)


def channel_out(ch):
    return _public(ch)


def content_item_out(ci):
    return _public(ci)


def content_target_out(t):
    return _public(t)


def schedule_slot_out(s):
    return _public(s)


def boost_out(b):
    return _public(b)


def conversation_out(c):
    return _public(c)


def message_out(m):
    return _public(m)


def collab_out(c):
    return _public(c)


def ugc_out(a):
    return _public(a)


def snapshot_out(s):
    return _public(s)


def ledger_out(l):
    return _public(l)
