"""Derived-counter recomputation and the multi-hop cascades of PRD 3."""
from datetime import timedelta

import calc
from db import cfg, db, new_id
from helpers import clock_date, new_common, touch

CERT_SLOT_STATUSES = ("SUBMITTED", "ACTIVE", "UNDER_AUDIT")
OPEN_INSPECTION_STATUSES = ("DRAFT", "IN_PROGRESS", "RECONDITIONING_REQUIRED")
LIVE_COMPLAINT_STATUSES = ("OPEN", "REINSPECTION_ORDERED")
WITHDRAWABLE = ("DRAFT", "SYNDICATED")


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #
def dealer_certifications(dealer_id):
    return [c for c in db.certifications.values() if c["dealer_id"] == dealer_id]


def certification_listings(certification_id):
    return [l for l in db.listings.values() if l["certification_id"] == certification_id]


def dealer_listings(dealer_id):
    ids = set(c["id"] for c in db.certifications.values() if c["dealer_id"] == dealer_id)
    return [l for l in db.listings.values() if l["certification_id"] in ids]


def certification_complaints(certification_id):
    return [c for c in db.complaints.values() if c["certification_id"] == certification_id]


def certification_claims(certification_id):
    return [c for c in db.claims.values() if c["certification_id"] == certification_id]


def dealer_claims(dealer_id):
    ids = set(c["id"] for c in db.certifications.values() if c["dealer_id"] == dealer_id)
    return [c for c in db.claims.values() if c["certification_id"] in ids]


def dealer_audit_samples(dealer_id):
    ids = set(c["id"] for c in db.certifications.values() if c["dealer_id"] == dealer_id)
    return [s for s in db.audit_samples.values() if s["certification_id"] in ids]


def inspection_recon_items(inspection_id):
    return [r for r in db.recon_items.values() if r["inspection_id"] == inspection_id]


def template_items_of(template_id):
    return [i for i in db.checklist_items.values() if i["template_id"] == template_id]


def template_item(template_id, item_code):
    for item in db.checklist_items.values():
        if item["template_id"] == template_id and item["item_code"] == item_code:
            return item
    return None


def attempt_results(inspection_id, attempt_index):
    return [
        r
        for r in db.inspection_results.values()
        if r["inspection_id"] == inspection_id and r["attempt_index"] == attempt_index
    ]


# --------------------------------------------------------------------------- #
# dealer counter recomputation
# --------------------------------------------------------------------------- #
def recompute_dealer_cert_counts(dealer):
    config = cfg()
    certs = dealer_certifications(dealer["id"])
    low, high = calc.window_bounds(config, clock_date())
    dealer["lifetime_submitted_count"] = len(certs)
    dealer["lifetime_activated_count"] = sum(
        1 for c in certs if c["activated_at"] is not None
    )
    dealer["window_activated_count"] = sum(
        1
        for c in certs
        if c["activated_at"] is not None and low <= c["activated_at"].date() <= high
    )
    dealer["active_certification_count"] = sum(
        1 for c in certs if c["status"] in CERT_SLOT_STATUSES
    )


def recompute_dealer_fee_ledger(dealer):
    certs = dealer_certifications(dealer["id"])
    billed = sum(c["fee_charged_cents"] for c in certs if c["activated_at"] is not None)
    credited = sum(c["fee_credited_cents"] for c in certs)
    dealer["fee_billed_cents_total"] = billed
    dealer["fee_credited_cents_total"] = credited
    dealer["fee_balance_cents"] = billed - credited


def recompute_dealer_claim_counts(dealer):
    config = cfg()
    low, high = calc.window_bounds(config, clock_date())
    approved = [c for c in dealer_claims(dealer["id"]) if c["status"] == "APPROVED"]
    dealer["approved_claim_count_lifetime"] = len(approved)
    dealer["approved_claim_count_window"] = sum(
        1 for c in approved if low <= c["repair_date"] <= high
    )


def recompute_dealer_ratio(dealer):
    config = cfg()
    if dealer["lifetime_activated_count"] >= config["claim_variant_volume_floor"]:
        dealer["claim_ratio_variant"] = "TRAILING_WINDOW"
        dealer["claim_ratio_effective"] = calc.ratio_2dp(
            dealer["approved_claim_count_window"], dealer["window_activated_count"]
        )
    else:
        dealer["claim_ratio_variant"] = "LIFETIME_CUMULATIVE"
        dealer["claim_ratio_effective"] = calc.ratio_2dp(
            dealer["approved_claim_count_lifetime"], dealer["lifetime_activated_count"]
        )
    recompute_dealer_risk(dealer)


def recompute_dealer_audit(dealer):
    samples = dealer_audit_samples(dealer["id"])
    dealer["audit_sample_count"] = len(samples)
    dealer["audit_fail_count"] = sum(1 for s in samples if s["status"] == "FAILED")
    dealer["audit_fail_rate"] = calc.ratio_2dp(
        dealer["audit_fail_count"], dealer["audit_sample_count"]
    )
    recompute_dealer_risk(dealer)


def recompute_dealer_risk(dealer):
    dealer["risk_score"] = calc.risk_score(
        dealer["claim_ratio_effective"], dealer["audit_fail_rate"]
    )


# --------------------------------------------------------------------------- #
# inspection money aggregates
# --------------------------------------------------------------------------- #
def recompute_inspection_money(inspection):
    config = cfg()
    items = [
        r for r in inspection_recon_items(inspection["id"]) if r["status"] == "COMPLETED"
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total_cost = 0
    total_reimbursable = 0
    for item in items:
        cost = item["actual_cost_cents"] or 0
        total_cost += cost
        point = template_item(inspection["template_id"], item["item_code"])
        ceiling = point["max_reconditioning_cost_cents"] if point else cost
        share = calc.half_up_mul(cost, config["recon_reimbursement_share"])
        total_reimbursable += min(share, ceiling)
    inspection["total_recon_cost_cents"] = total_cost
    inspection["total_reimbursable_cents"] = min(
        total_reimbursable, config["recon_reimbursement_cap_cents"]
    )


# --------------------------------------------------------------------------- #
# listing withdrawal
# --------------------------------------------------------------------------- #
def withdraw_listing(listing, reason):
    config = cfg()
    listing["status"] = "WITHDRAWN"
    listing["withdrawn_at"] = db.clock
    listing["withdrawal_reason"] = reason
    listing["removal_due_at"] = db.clock + timedelta(
        hours=config["listing_removal_sla_hours"]
    )
    touch(listing)


def withdraw_certification_listings(certification, reason, statuses=WITHDRAWABLE):
    for listing in certification_listings(certification["id"]):
        if listing["status"] in statuses:
            withdraw_listing(listing, reason)


# --------------------------------------------------------------------------- #
# complaint dismissal (and the inspections it voids)
# --------------------------------------------------------------------------- #
def void_complaint_inspections(complaint):
    for inspection in db.inspections.values():
        if (
            inspection["complaint_id"] == complaint["id"]
            and inspection["status"] in OPEN_INSPECTION_STATUSES
        ):
            inspection["status"] = "VOIDED"
            inspection["failure_reason"] = "COMPLAINT_DISMISSED"
            touch(inspection)


def dismiss_certification_complaints(certification, skip_complaint_id=None):
    for complaint in certification_complaints(certification["id"]):
        if complaint["id"] == skip_complaint_id:
            continue
        if complaint["status"] not in LIVE_COMPLAINT_STATUSES:
            continue
        complaint["status"] = "DISMISSED"
        complaint["resolved_at"] = db.clock
        touch(complaint)
        void_complaint_inspections(complaint)


# --------------------------------------------------------------------------- #
# certification decertification / rejection
# --------------------------------------------------------------------------- #
def decertify_certification(certification, reason, skip_complaint_id=None):
    certification["status"] = "DECERTIFIED"
    certification["decertification_reason"] = reason
    certification["decertified_at"] = db.clock
    if reason == "POST_AUDIT_FAIL":
        certification["fee_credited_cents"] = certification["fee_charged_cents"]
    touch(certification)

    vehicle = db.vehicles.get(certification["vehicle_id"])
    if vehicle is not None:
        if vehicle["cpo_state"] in ("CERTIFIED", "CERTIFICATION_PENDING"):
            vehicle["cpo_state"] = "DECERTIFIED"
        vehicle["decertified_at"] = db.clock
        touch(vehicle)

    withdraw_certification_listings(certification, "CERTIFICATION_DECERTIFIED")
    dismiss_certification_complaints(certification, skip_complaint_id)

    dealer = db.dealers.get(certification["dealer_id"])
    if dealer is not None:
        recompute_dealer_cert_counts(dealer)
        recompute_dealer_fee_ledger(dealer)
        recompute_dealer_claim_counts(dealer)
        recompute_dealer_ratio(dealer)
        touch(dealer)


def reject_submitted_certification(certification, reason):
    certification["status"] = "REJECTED"
    certification["rejection_reason"] = reason
    touch(certification)
    vehicle = db.vehicles.get(certification["vehicle_id"])
    if vehicle is not None:
        if vehicle["cpo_state"] == "CERTIFICATION_PENDING":
            vehicle["cpo_state"] = "NOT_CERTIFIED"
        touch(vehicle)


# --------------------------------------------------------------------------- #
# dealer suspension
# --------------------------------------------------------------------------- #
def suspend_dealer(dealer, reason, listing_statuses):
    dealer["privilege_status"] = "SUSPENDED"
    dealer["privilege_reason"] = reason
    touch(dealer)
    for certification in dealer_certifications(dealer["id"]):
        if certification["status"] == "SUBMITTED":
            reject_submitted_certification(certification, "DEALER_SUSPENDED")
    for listing in dealer_listings(dealer["id"]):
        if listing["status"] in listing_statuses:
            withdraw_listing(listing, "DEALER_SUSPENDED")
    recompute_dealer_cert_counts(dealer)
    touch(dealer)


def evaluate_privilege_thresholds(dealer):
    config = cfg()
    ratio = dealer["claim_ratio_effective"]
    if ratio >= config["claim_ratio_suspension_threshold"]:
        suspend_dealer(dealer, "CLAIM_RATIO_SUSPENSION", ("SYNDICATED",))
    elif ratio >= config["claim_ratio_probation_threshold"]:
        dealer["privilege_status"] = "PROBATION"
        dealer["privilege_reason"] = "CLAIM_RATIO_PROBATION"
        touch(dealer)


# --------------------------------------------------------------------------- #
# reconditioning item generation
# --------------------------------------------------------------------------- #
def generate_reconditioning_items(inspection, failed_points):
    existing = set(r["item_code"] for r in inspection_recon_items(inspection["id"]))
    for point in failed_points:
        if point["item_code"] in existing:
            continue
        existing.add(point["item_code"])
        row = new_common(
            {
                "id": new_id(),
                "inspection_id": inspection["id"],
                "item_code": point["item_code"],
                "severity": point["severity"],
                "status": "REQUIRED",
                "actual_cost_cents": None,
                "reimbursable_cents": 0,
                "waiver_reason": None,
                "completed_at": None,
                "closed_by_user_id": None,
            }
        )
        db.recon_items[row["id"]] = row
