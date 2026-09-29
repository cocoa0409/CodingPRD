"""Mirror refreshes and the two long cascades of PRD section 2.8."""
from datetime import timedelta

from common import (D, db, new_record, now, touch, by_created, pack_modules,
                    vehicle_consents, campaign_consents, vehicle_claims)
import calc

ACCRUING_STATUSES = ("APPROVED_MODULE", "APPROVED_PACK", "APPROVED_SOFTWARE",
                     "FULFILLED", "CLOSED")
RELEASED_STATUSES = ("LIMITED_RELEASE", "FIELD_RELEASE")
OPEN_CONSENT_STATUSES = ("PENDING", "GRANTED")


# --------------------------------------------------------- program mirrors
def refresh_reman_stock():
    count = 0
    for pack in db.packs.values():
        if pack["pack_type"] == "REMANUFACTURED" and pack["status"] == "STOCK":
            count += 1
    state = "DEPLETED" if count == 0 else "AVAILABLE"
    for program in db.programs.values():
        if program["reman_available_count"] != count or program["reman_stock_state"] != state:
            program["reman_available_count"] = count
            program["reman_stock_state"] = state
            touch(program)


def refresh_accrual(program):
    total = 0
    for claim in db.claims.values():
        vehicle = db.vehicles.get(claim["vehicle_id"])
        if vehicle is None or vehicle["warranty_program_id"] != program["id"]:
            continue
        if claim["adjudication_status"] not in ACCRUING_STATUSES:
            continue
        total += int(claim["oem_total_cents"] or 0)
    if program["accrued_liability_cents"] != total:
        program["accrued_liability_cents"] = total
        touch(program)


def refresh_all_accruals():
    for program in list(db.programs.values()):
        refresh_accrual(program)


# ------------------------------------------------------------ pack counters
def refresh_pack_counters(pack):
    # module_replacements_to_date is a lifetime counter and never falls; the
    # faulted counter is a live re-derivation of the module rows.
    replaced = max(calc.replaced_module_count(pack["id"]),
                   pack["module_replacements_to_date"])
    faulted = calc.faulted_module_count(pack["id"])
    if pack["module_replacements_to_date"] != replaced or pack["faulted_module_count"] != faulted:
        pack["module_replacements_to_date"] = replaced
        pack["faulted_module_count"] = faulted
        touch(pack)


# -------------------------------------------------------- campaign counters
def refresh_campaign(campaign):
    consents = campaign_consents(campaign["id"])
    solicited = len(consents)
    open_count = len([c for c in consents if c["consent_status"] in OPEN_CONSENT_STATUSES])
    applied = len([c for c in consents if c["consent_status"] == "APPLIED"])
    changed = False
    if campaign["solicited_consent_count"] != solicited:
        campaign["solicited_consent_count"] = solicited
        changed = True
    if campaign["open_consent_count"] != open_count:
        campaign["open_consent_count"] = open_count
        changed = True
    if campaign["applied_count"] != applied:
        campaign["applied_count"] = applied
        changed = True
    if (campaign["status"] in RELEASED_STATUSES and solicited >= 1 and open_count == 0):
        campaign["status"] = "CLOSED"
        changed = True
    if changed:
        touch(campaign)


# --------------------------------------------------------- center standing
def block_claims(center, statuses):
    for claim in db.claims.values():
        if claim["service_center_id"] != center["id"]:
            continue
        if claim["adjudication_status"] not in statuses:
            continue
        if not claim["fulfilment_blocked"]:
            claim["fulfilment_blocked"] = True
            touch(claim)


def clear_blocked_claims(center):
    for claim in db.claims.values():
        if claim["service_center_id"] != center["id"]:
            continue
        if claim["fulfilment_blocked"]:
            claim["fulfilment_blocked"] = False
            touch(claim)


def decertify(center):
    if center["status"] == "DECERTIFIED":
        return
    center["status"] = "DECERTIFIED"
    touch(center)
    blocked = tuple(s for s in ("SUBMITTED", "INFO_REQUESTED", "APPROVED_MODULE",
                               "APPROVED_PACK", "APPROVED_SOFTWARE", "FULFILLED"))
    block_claims(center, blocked)


def recompute_compliance(center):
    score = calc.compliance_score_for(center)
    if center["compliance_score"] != score:
        center["compliance_score"] = score
        touch(center)
    if score <= 20:
        decertify(center)


def raise_hazmat_hold(center):
    center["open_hazmat_holds"] = center["open_hazmat_holds"] + 1
    touch(center)
    if center["open_hazmat_holds"] >= 2 and center["status"] == "ACTIVE":
        center["status"] = "SHIPPING_SUSPENDED"
        touch(center)
        block_claims(center, ("APPROVED_MODULE", "APPROVED_PACK"))


def lower_hazmat_hold(center):
    center["open_hazmat_holds"] = max(0, center["open_hazmat_holds"] - 1)
    touch(center)
    if center["open_hazmat_holds"] <= 1 and center["status"] == "SHIPPING_SUSPENDED":
        center["status"] = "ACTIVE"
        touch(center)
        clear_blocked_claims(center)


# ----------------------------------------------------------- consent expiry
def expire_vehicle_consents(vehicle):
    affected = []
    for consent in vehicle_consents(vehicle["id"]):
        if consent["consent_status"] in OPEN_CONSENT_STATUSES:
            consent["consent_status"] = "EXPIRED"
            touch(consent)
            if consent["campaign_id"] not in affected:
                affected.append(consent["campaign_id"])
    for campaign_id in affected:
        campaign = db.campaigns.get(campaign_id)
        if campaign is not None:
            refresh_campaign(campaign)


# ------------------------------------------------------------ thermal event
SETTLED_NOTIFICATION = ("NOT_REQUIRED", "FILED", "LATE_FILED")


def derive_event_status(event):
    if (event["containment_status"] == "CONTAINMENT_CLOSED"
            and event["notification_status"] in SETTLED_NOTIFICATION):
        event["event_status"] = "COMPLETE"
    else:
        event["event_status"] = "OPEN"


def thermal_cascade(event, vehicle, pack):
    if event["severity"] not in ("S3", "S4"):
        return
    pack["damaged_defective"] = True
    pack["hazmat_classification"] = "UN3536"
    if pack["status"] == "IN_SERVICE":
        pack["status"] = "QUARANTINED"
    touch(pack)
    positions = set(event["affected_module_positions"])
    for module in pack_modules(pack["id"]):
        if module["position_index"] in positions:
            module["thermal_runaway_flag"] = True
            module["status"] = "FAULTED"
            touch(module)
    refresh_pack_counters(pack)
    vehicle["warranty_hold"] = True
    if vehicle["status"] == "ACTIVE":
        vehicle["status"] = "IMMOBILIZED"
    touch(vehicle)
    # For S4 only, campaign suspension runs BEFORE the consent-expiry step so
    # that a suspended campaign is never silently auto-closed afterwards.
    if event["severity"] == "S4":
        for campaign in by_created(list(db.campaigns.values())):
            if campaign["target_defect"] != "THERMAL_MANAGEMENT":
                continue
            if campaign["applies_to_model_code"] != vehicle["model_code"]:
                continue
            if campaign["status"] not in RELEASED_STATUSES:
                continue
            campaign["status"] = "SUSPENDED"
            touch(campaign)
            for consent in campaign_consents(campaign["id"]):
                if consent["consent_status"] == "PENDING":
                    consent["consent_status"] = "EXPIRED"
                    touch(consent)
            refresh_campaign(campaign)
    expire_vehicle_consents(vehicle)


# -------------------------------------------------------- shipment rejection
def shipment_rejection_cascade(pack, center):
    pack["status"] = "QUARANTINED"
    pack["damaged_defective"] = True
    pack["hazmat_classification"] = "UN3536"
    touch(pack)
    raise_hazmat_hold(center)
    center["rejected_shipment_count"] = center["rejected_shipment_count"] + 1
    touch(center)
    recompute_compliance(center)


# ------------------------------------------------------- claim money helpers
def zero_settlement(claim, fields):
    for field in fields:
        claim[field] = 0


# ------------------------------------------------------------ consent factory
CONSENT_WINDOW = timedelta(days=14)


def create_consent(campaign, vehicle, superseded=None):
    """A PENDING consent expiring fourteen days after its own created_at."""
    record = new_record()
    record.update({
        "campaign_id": campaign["id"],
        "vehicle_id": vehicle["id"],
        "superseded_consent_id": superseded["id"] if superseded else None,
        "solicitation_round": (superseded["solicitation_round"] + 1) if superseded else 1,
        "consent_status": "PENDING",
        "expires_at": record["created_at"] + CONSENT_WINDOW,
        "decision_at": None,
        "applied_at": None,
        "applied_software_version": None,
    })
    db.consents[record["id"]] = record
    return record


def existing_open_consent(campaign_id, vehicle_id):
    for consent in by_created(list(db.consents.values())):
        if consent["campaign_id"] != campaign_id or consent["vehicle_id"] != vehicle_id:
            continue
        if consent["consent_status"] in OPEN_CONSENT_STATUSES:
            return consent
    return None


def any_consent(campaign_id, vehicle_id):
    for consent in by_created(list(db.consents.values())):
        if consent["campaign_id"] == campaign_id and consent["vehicle_id"] == vehicle_id:
            return consent
    return None
