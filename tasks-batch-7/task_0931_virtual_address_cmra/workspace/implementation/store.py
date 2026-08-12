"""
In-memory data store.  Plain Python dicts, nothing else: no sqlite, no file,
no cache directory, no serialisation to disk.  Every collection starts EMPTY on
every boot -- nothing here is seeded, preloaded or hardcoded; each row is minted
only by the declared API surface.
"""

from util import CLOCK, IDS, new_id

COLLECTIONS = (
    "plan_tiers",
    "carrier_rules",
    "boxes",
    "recipients",
    "form1583s",
    "id_documents",
    "mail_items",
    "scan_jobs",
    "dispositions",
    "forward_shipments",
    "check_deposits",
    "deposit_batches",
    "registered_agents",
    "compliance_reviews",
    "billing_cycles",
    "usage_entries",
    "cancellations",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        CLOCK.reset()
        IDS.reset()


DB = Store()


def insert(collection, row, common=True):
    row["id"] = new_id()
    row["created_at"] = CLOCK.now
    if common:
        row["updated_at"] = CLOCK.now
        row["version"] = 1
    collection[row["id"]] = row
    return row


def rows(collection):
    """All rows in the canonical list order: created_at ASC, id ASC."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["id"]))


# -------------------------------------------------------------- lookups
def box(box_id):
    return DB.boxes.get(box_id)


def recipient(rid):
    return DB.recipients.get(rid)


def mail_item(mid):
    return DB.mail_items.get(mid)


def plan_tier(tid):
    return DB.plan_tiers.get(tid)


def tier_of_box(b):
    return DB.plan_tiers.get(b["plan_tier_id"])


def recipients_of_box(box_id):
    return [r for r in rows(DB.recipients) if r["box_id"] == box_id]


def mail_items_of_box(box_id):
    return [m for m in rows(DB.mail_items) if m["box_id"] == box_id]


def forms_of_recipient(rid):
    return [f for f in rows(DB.form1583s) if f["recipient_id"] == rid]


def docs_of_recipient(rid):
    return [d for d in rows(DB.id_documents) if d["recipient_id"] == rid]


def scan_jobs_of_item(mid):
    return [j for j in rows(DB.scan_jobs) if j["mail_item_id"] == mid]


def dispositions_of_item(mid):
    return [d for d in rows(DB.dispositions) if d["mail_item_id"] == mid]


def pending_dispositions(mid):
    return [d for d in dispositions_of_item(mid) if d["status"] == "PENDING"]


def checks_of_batch(bid):
    return [c for c in rows(DB.check_deposits) if c["deposit_batch_id"] == bid]


def batches_of_box(box_id):
    return [b for b in rows(DB.deposit_batches) if b["box_id"] == box_id]


def ra_services_of_box(box_id):
    return [r for r in rows(DB.registered_agents) if r["box_id"] == box_id]


def active_ra(box_id):
    """
    Adjudication of friction 5 (reading B, several add-ons may be active): the
    governing add-on is the most recently created active one.
    """
    actives = [r for r in ra_services_of_box(box_id) if r["active"]]
    return actives[-1] if actives else None


def reviews_of_box(box_id):
    return [r for r in rows(DB.compliance_reviews) if r["box_id"] == box_id]


def cycles_of_box(box_id):
    return [c for c in rows(DB.billing_cycles) if c["box_id"] == box_id]


def open_cycle(box_id):
    for c in cycles_of_box(box_id):
        if c["status"] == "OPEN":
            return c
    return None


def cancellations_of_box(box_id):
    return [c for c in rows(DB.cancellations) if c["box_id"] == box_id]


def live_cancellation(box_id):
    live = [c for c in cancellations_of_box(box_id)
            if c["status"] in ("REQUESTED", "FINAL_FORWARD")]
    return live[-1] if live else None


def entries_of_cycle(cid):
    return [e for e in rows(DB.usage_entries) if e["billing_cycle_id"] == cid]


def entries_of_item(mid):
    return [e for e in rows(DB.usage_entries) if e.get("mail_item_id") == mid]


def box_of_recipient(r):
    return DB.boxes.get(r["box_id"]) if r else None


def box_of_item(m):
    return DB.boxes.get(m["box_id"]) if m else None


def box_of_form(f):
    r = recipient(f["recipient_id"])
    return box_of_recipient(r)


def box_of_doc(d):
    r = recipient(d["recipient_id"])
    return box_of_recipient(r)


def box_of_scan_job(j):
    return box_of_item(mail_item(j["mail_item_id"]))


def box_of_disposition(d):
    return box_of_item(mail_item(d["mail_item_id"]))


def box_of_check(c):
    b = DB.deposit_batches.get(c["deposit_batch_id"])
    return DB.boxes.get(b["box_id"]) if b else None
