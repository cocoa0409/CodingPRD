"""Route-level shared helpers: reference resolution (priority 30/35), posture
gate (priority 44), listing filters."""
from core import (as_id, fail, store, opt_field)
import calc

# --------------------------------------------------------------------------- #
# Reference resolution
# --------------------------------------------------------------------------- #

BODY_REF_ORDER = (
    ("plan_id", "plans"),
    ("seat_id", "seats"),
    ("member_id", "members"),
    ("ips_id", "ips"),
    ("slot_id", "slots"),
    ("fund_id", "funds"),
    ("review_id", "reviews"),
    ("meeting_id", "meetings"),
    ("motion_id", "motions"),
    ("subject_id", None),
    ("outgoing_fund_id", "funds"),
    ("incoming_fund_id", "funds"),
    ("approving_motion_id", "motions"),
    ("successor_engagement_id", "engagements"),
    ("supersedes_scorecard_id", "scorecards"),
)


def get_row(collection, row_id, name="resource"):
    if not isinstance(row_id, str) or row_id.strip() == "":
        fail("ERR_RESOURCE_NOT_FOUND", "%s does not resolve" % name)
    row = getattr(store, collection).get(row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s does not resolve" % name)
    return row


def plan_id_of(collection, row):
    if row is None:
        return None
    if collection == "plans":
        return row["id"]
    if collection in ("seats", "slots", "funds", "reviews", "ips", "proposals",
                      "runs", "engagements", "meetings"):
        return row.get("plan_id")
    if collection == "members":
        seat = store.seats.get(row.get("seat_id"))
        return seat.get("plan_id") if seat else None
    if collection == "training":
        member = store.members.get(row.get("member_id"))
        return plan_id_of("members", member)
    if collection == "scorecards":
        review = store.reviews.get(row.get("review_id"))
        return review.get("plan_id") if review else None
    if collection == "motions":
        meeting = store.meetings.get(row.get("meeting_id"))
        return meeting.get("plan_id") if meeting else None
    return None


class Refs(object):
    """Resolved references plus their owning plan ids, in resolution order."""

    def __init__(self):
        self.rows = {}
        self.owners = []

    def add(self, name, collection, row):
        self.rows[name] = row
        self.owners.append((name, plan_id_of(collection, row)))

    def get(self, name):
        return self.rows.get(name)

    def cross_plan_check(self):
        seen = None
        for name, owner in self.owners:
            if owner is None:
                continue
            if seen is None:
                seen = owner
            elif owner != seen:
                fail("ERR_CROSS_PLAN_REFERENCE",
                     "%s belongs to a different plan" % name)
        return seen


def resolve_body_refs(payload, spec, extra_rows=None):
    """`spec` maps a body field name to its collection; a field prefixed by '!'
    is required. Resolution follows the declared global field order."""
    refs = Refs()
    if extra_rows:
        for name, (collection, row) in extra_rows.items():
            refs.add(name, collection, row)
    required = set()
    plain = {}
    for key, collection in spec.items():
        if key.startswith("!"):
            required.add(key[1:])
            plain[key[1:]] = collection
        else:
            plain[key] = collection
    for name, default_collection in BODY_REF_ORDER:
        if name not in plain:
            continue
        collection = plain[name] or default_collection
        value = payload.get(name)
        if value is None:
            if name in required:
                fail("ERR_INVALID_REQUEST", "%s is required" % name)
            continue
        refs.add(name, collection, get_row(collection, value, name))
    if "pool_fund_ids" in plain:
        values = payload.get("pool_fund_ids")
        if values is not None:
            if not isinstance(values, list):
                fail("ERR_INVALID_REQUEST", "pool_fund_ids must be an array")
            for value in values:
                refs.add("pool_fund_ids", "funds",
                         get_row("funds", value, "pool_fund_ids"))
        elif "pool_fund_ids" in required:
            fail("ERR_INVALID_REQUEST", "pool_fund_ids is required")
    if "attendee_member_ids" in plain:
        values = payload.get("attendee_member_ids")
        if values is not None:
            if not isinstance(values, list):
                fail("ERR_INVALID_REQUEST", "attendee_member_ids must be an array")
            for value in values:
                refs.add("attendee_member_ids", "members",
                         get_row("members", value, "attendee_member_ids"))
        elif "attendee_member_ids" in required:
            fail("ERR_INVALID_REQUEST", "attendee_member_ids is required")
    refs.cross_plan_check()
    return refs


def resolve_subject(subject_type, subject_id):
    collection = calc.SUBJECT_COLLECTION.get(subject_type)
    if collection is None:
        fail("ERR_INVALID_REQUEST", "subject_type is not recognised")
    if not isinstance(subject_id, str) or subject_id.strip() == "":
        fail("ERR_RESOURCE_NOT_FOUND", "subject_id does not resolve")
    row = getattr(store, collection).get(subject_id)
    if row is None:
        fail("ERR_MOTION_SUBJECT_MISMATCH",
             "subject_id does not resolve within subject_type %s" % subject_type)
    return collection, row


# --------------------------------------------------------------------------- #
# Posture gate (priority 44)
# --------------------------------------------------------------------------- #

def require_posture(plan, slot=None):
    posture = plan["menu_posture"]
    if posture == "FROZEN":
        fail("ERR_MENU_FROZEN", "the plan's menu posture is FROZEN")
    if posture == "RESTRICTED" and slot is not None and \
            slot["status"] in calc.AT_RISK_SLOT_STATES:
        fail("ERR_MENU_FROZEN",
             "the plan's menu posture is RESTRICTED and the slot is under surveillance")


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #

def filter_rows(rows, filters):
    """`filters` is a list of (value, key) pairs; a None value is skipped."""
    out = []
    for row in rows:
        keep = True
        for value, key in filters:
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out
