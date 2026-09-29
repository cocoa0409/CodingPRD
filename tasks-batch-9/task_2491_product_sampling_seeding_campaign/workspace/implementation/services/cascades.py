"""Multi-hop cascades (PRD 2.7): shipment cancellation and diversion substantiation."""

import clock
import db as store
from db import db, touch
from services import calculations as calc


def cancel_shipment(shipment):
    """Depth-3 cascade: shipment -> kit lines -> wave -> campaign."""
    shipment["status"] = "CANCELLED"

    # hop 1 — release the reserved units on every line named in the snapshot
    for line_id, units in list(shipment["reserved_line_units"].items()):
        line = db.kit_lines.get(line_id)
        if line is None:
            continue
        line["units_reserved"] -= units
        line["units_available"] += units
        touch(line)

    # hop 2 — return the planned units to the wave, auto-unlocking when it empties
    wave = store.wave_of_shipment(shipment)
    wave["planned_unit_count"] -= shipment["kit_unit_total"]
    if wave["status"] == "LOCKED" and wave["planned_unit_count"] == 0:
        wave["status"] = "PLANNED"
    touch(wave)

    # hop 3 — release the budget snapshot and refresh the provisional unit cost
    campaign = store.campaign_of_shipment(shipment)
    campaign["allocated_sample_count"] -= 1
    campaign["budget_committed_cents"] -= shipment["committed_cost_cents"]
    campaign["budget_available_cents"] += shipment["committed_cost_cents"]
    calc.refresh_provisional_cost(campaign)
    touch(campaign)

    touch(shipment)


def substantiate_diversion(case):
    """Direct campaign effect plus the depth-4 integrity cascade."""
    now = clock.now_iso()
    case["status"] = "SUBSTANTIATED"
    case["substantiated_at"] = now
    touch(case)

    shipment = db.sample_shipments[case["sample_shipment_id"]]
    case_campaign = store.campaign_of_shipment(shipment)
    case_campaign["substantiated_diversion_count"] += 1
    calc.refresh_posture(case_campaign)
    touch(case_campaign)

    # hop 1 — the panelist earns a strike and is banned outright
    panelist = db.panelists[case["panelist_id"]]
    panelist["diversion_strikes"] += 1
    panelist["integrity_status"] = "BANNED"
    touch(panelist)

    # hop 2 — every live enrollment of that panelist is revoked
    revoked = []
    for enrollment in store.panelist_enrollments(panelist["id"]):
        if enrollment["screening_status"] not in ("PENDING_SCREEN", "SCREEN_PASSED"):
            continue
        enrollment["screening_status"] = "SCREEN_REVOKED"
        if enrollment["obligation_status"] != "REVIEW_FULFILLED":
            enrollment["obligation_status"] = "FORFEITED"
        touch(enrollment)
        revoked.append(enrollment)

    # hop 3 — live reviews on those enrollments are retracted
    retracted = []
    for enrollment in revoked:
        for review in store.enrollment_reviews(enrollment["id"]):
            if review["status"] not in ("SUBMITTED", "APPROVED"):
                continue
            was_approved = review["status"] == "APPROVED"
            review["status"] = "RETRACTED"
            touch(review)
            if was_approved:
                review_campaign = store.campaign_of_review(review)
                review_campaign["approved_review_count"] -= 1
                touch(review_campaign)
            retracted.append(review)

    # hop 4 — syndicated copies of those reviews are pulled back
    for review in retracted:
        for record in store.review_syndication_records(review["id"]):
            if record["status"] != "SYNDICATED":
                continue
            record["status"] = "TAKEDOWN_REQUESTED"
            record["takedown_requested_at"] = now
            touch(record)
            review_campaign = store.campaign_of_review(review)
            review_campaign["syndicated_review_count"] -= 1
            touch(review_campaign)
