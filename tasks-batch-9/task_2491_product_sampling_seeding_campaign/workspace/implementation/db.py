"""In-memory data store.

Every collection is a plain dict keyed by the row's UUID id.  The store starts
completely empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import uuid

import clock

COLLECTIONS = (
    "campaigns",
    "kit_lines",
    "fulfillment_centers",
    "fulfillment_waves",
    "panelists",
    "enrollments",
    "sample_shipments",
    "review_submissions",
    "retailers",
    "syndication_records",
    "diversion_cases",
    "purchase_matches",
    "lift_analyses",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._counter = 0

    def next_seq(self):
        self._counter += 1
        return self._counter


db = Store()


def new_row(versioned=True):
    stamp = clock.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


def ordered(rows):
    """Default ordering: created_at ascending, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------- lookups

def campaign_of_enrollment(enrollment):
    return db.campaigns.get(enrollment["campaign_id"])


def panelist_of_enrollment(enrollment):
    return db.panelists.get(enrollment["panelist_id"])


def enrollment_of_shipment(shipment):
    return db.enrollments.get(shipment["enrollment_id"])


def campaign_of_shipment(shipment):
    return campaign_of_enrollment(db.enrollments[shipment["enrollment_id"]])


def wave_of_shipment(shipment):
    return db.fulfillment_waves[shipment["fulfillment_wave_id"]]


def center_of_wave(wave):
    return db.fulfillment_centers[wave["fulfillment_center_id"]]


def freight_of_shipment(shipment):
    return center_of_wave(wave_of_shipment(shipment))["freight_cents_per_kit"]


def enrollment_of_review(review):
    return db.enrollments.get(review["enrollment_id"])


def campaign_of_review(review):
    return campaign_of_enrollment(db.enrollments[review["enrollment_id"]])


def panelist_of_review(review):
    return db.panelists.get(db.enrollments[review["enrollment_id"]]["panelist_id"])


def review_of_syndication(record):
    return db.review_submissions.get(record["review_submission_id"])


def retailer_of_syndication(record):
    return db.retailers.get(record["retailer_id"])


def campaign_shipments(campaign_id):
    out = []
    for s in db.sample_shipments.values():
        enr = db.enrollments.get(s["enrollment_id"])
        if enr is not None and enr["campaign_id"] == campaign_id:
            out.append(s)
    return ordered(out)


def campaign_enrollments(campaign_id):
    return ordered([e for e in db.enrollments.values() if e["campaign_id"] == campaign_id])


def campaign_reviews(campaign_id):
    out = []
    for r in db.review_submissions.values():
        enr = db.enrollments.get(r["enrollment_id"])
        if enr is not None and enr["campaign_id"] == campaign_id:
            out.append(r)
    return ordered(out)


def campaign_kit_lines(campaign_id):
    return ordered([k for k in db.kit_lines.values() if k["campaign_id"] == campaign_id])


def enrollment_shipments(enrollment_id):
    return ordered([s for s in db.sample_shipments.values()
                    if s["enrollment_id"] == enrollment_id])


def enrollment_reviews(enrollment_id):
    return ordered([r for r in db.review_submissions.values()
                    if r["enrollment_id"] == enrollment_id])


def panelist_enrollments(panelist_id):
    return ordered([e for e in db.enrollments.values() if e["panelist_id"] == panelist_id])


def panelist_diversion_cases(panelist_id):
    return ordered([c for c in db.diversion_cases.values()
                    if c["panelist_id"] == panelist_id])


def review_syndication_records(review_id):
    return ordered([r for r in db.syndication_records.values()
                    if r["review_submission_id"] == review_id])


def wave_shipments(wave_id):
    return ordered([s for s in db.sample_shipments.values()
                    if s["fulfillment_wave_id"] == wave_id])
