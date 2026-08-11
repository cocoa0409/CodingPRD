"""Clock-dependent latches (PRD 2.4) and the serializers.

PRD 2.4: "Every derived, time-sensitive posture in the system ... is evaluated
against this logical clock on the next read or write that touches the affected
row."
"""

import clock
from store import DB, ordered
from validation import LIVE_OUTCOME_TYPES

COMMON = ("id", "created_at", "updated_at", "version")


# =====================================================================
#  Clock-dependent latches
# =====================================================================

def latch_hold(record):
    """IntakeRecord.hold_status -- the MONOTONE latch of PRD 3.2.

    "Any read or write that touches the episode while the logical clock has
    reached or passed `hold_expires_at` latches it to `HOLD_EXPIRED` -- the
    boundary is inclusive ... Once latched it is permanent."
    """
    if record is None:
        return None
    if record["hold_status"] == "HOLD_EXPIRED":
        return record
    if clock.now() >= clock.parse(record["hold_expires_at"]):
        record["hold_status"] = "HOLD_EXPIRED"
    return record


def lapse_home_check(app):
    """FosterApplication.home_check_status -- NOT monotone (PRD 3.4).

    "any read or write touching the application while the logical clock stands
    strictly later than `home_check_expires_at` moves it PASSED -> LAPSED.  The
    comparison is strict."
    """
    if app is None:
        return None
    if app["home_check_status"] == "PASSED" and app.get("home_check_expires_at"):
        if clock.now() > clock.parse(app["home_check_expires_at"]):
            app["home_check_status"] = "LAPSED"
    return app


def expire_certificate(cert):
    """HealthCertificate.status.

    # Adjudication of friction 4: Reading A -- ANY read or write that observes
    # the clock past `expires_at` latches the certificate to EXPIRED.  Reading B
    # (only a departure check latches) strands two declared behaviours: the
    # `status` filter on GET /rescue/health-certificates could never return an
    # EXPIRED row unless a departure had first been attempted, and a plain
    # certificate read could never report EXPIRED at all.  Reading A also
    # matches the general rule of PRD 2.4, which lists "the expiry of a health
    # certificate" among the postures "evaluated against this logical clock on
    # the next read or write that touches the affected row".  The expiry
    # comparison is strict (PRD 3.5: "the certificate is still valid at an
    # instant exactly equal to `expires_at`").
    """
    if cert is None:
        return None
    if cert["status"] == "VALID" and clock.now() > clock.parse(cert["expires_at"]):
        cert["status"] = "EXPIRED"
    return cert


def open_episode(animal):
    """The animal's currently open custody episode, or None."""
    for rec in ordered(DB.where("IntakeRecord", animal_id=animal["id"], status="OPEN")):
        return latch_hold(rec)
    return None


def current_episode(animal):
    """The episode Animal.current_intake_record_id points at, latched."""
    rid = animal.get("current_intake_record_id")
    if not rid:
        return None
    return latch_hold(DB.get("IntakeRecord", rid))


# =====================================================================
#  Animal derivations (PRD 2.8 -- calendar-free arithmetic)
# =====================================================================

def elapsed_days_since(raw_instant):
    return clock.elapsed_days(clock.now(), clock.parse(raw_instant))


def age_weeks(animal):
    return elapsed_days_since(animal["date_of_birth"]) // 7


def age_months(animal):
    return elapsed_days_since(animal["date_of_birth"]) // 30


def length_of_stay_days(animal):
    rid = animal.get("current_intake_record_id")
    if not rid:
        return 0
    rec = DB.get("IntakeRecord", rid)
    if rec is None:
        return 0
    return elapsed_days_since(rec["intake_datetime"])


def active_holds(animal_id, hold_type):
    return [h for h in DB.where("HoldRecord", animal_id=animal_id, status="ACTIVE")
            if h["hold_type"] == hold_type]


# =====================================================================
#  Organization roll-ups -- derived, never stored independently (PRD 3.9)
# =====================================================================

def unrestricted_balance_cents():
    total = 0
    for c in DB.all("Contribution"):
        if c["restriction_category"] == "UNRESTRICTED" and c["status"] in ("RECEIVED", "PARTIALLY_APPLIED"):
            total += available_cents(c)
        total += c["released_cents"]
    for m in DB.all("MedicalRecord"):
        if m["status"] == "COMPLETED":
            total -= m["admin_overhead_cents"]
            if not m["funding_required"]:
                total -= m["cost_cents"]
    return total


def restricted_balance_cents():
    total = 0
    for c in DB.all("Contribution"):
        if c["restriction_category"] != "UNRESTRICTED" and c["status"] in ("RECEIVED", "PARTIALLY_APPLIED"):
            total += available_cents(c)
    return total


def open_commitment_slots_total(org_id):
    total = 0
    for pc in DB.where("PartnerCommitment", organization_id=org_id):
        if pc["status"] in ("OPEN", "PARTIALLY_DRAWN"):
            total += pc["slots_open"]
    return total


def available_cents(contribution):
    """Conservation identity 2: amount == applied + released + available."""
    return contribution["amount_cents"] - contribution["applied_cents"] - contribution["released_cents"]


def reclaim_history_count(person_id):
    """PRD 3.2: "the number of unreversed RETURN_TO_OWNER outcomes already
    naming them as counterparty"."""
    n = 0
    for o in DB.all("OutcomeRecord"):
        if (o["outcome_type"] == "RETURN_TO_OWNER"
                and o["counterparty_person_id"] == person_id
                and o["reversed_at"] is None):
            n += 1
    return n


def litter_member_count(litter_id):
    return len(DB.where("Animal", litter_id=litter_id))


# =====================================================================
#  Serializers
# =====================================================================

def _base(row):
    return {k: row[k] for k in COMMON}


def _pick(row, names):
    out = _base(row)
    for n in names:
        out[n] = row.get(n)
    return out


def organization(row):
    out = _pick(row, ("name", "org_type", "state_code", "default_methodology",
                      "records_freeze_active", "records_freeze_reason", "freeze_status"))
    out["unrestricted_balance_cents"] = unrestricted_balance_cents()
    out["restricted_balance_cents"] = restricted_balance_cents()
    out["open_commitment_slots_total"] = open_commitment_slots_total(row["id"])
    return out


def person(row):
    out = _pick(row, ("full_name", "email", "youngest_child_age_years",
                      "resident_cat_count", "resident_dog_count", "housing_type",
                      "has_fenced_yard", "hardship_certified", "driver_license_number"))
    out["reclaim_history_count"] = reclaim_history_count(row["id"])
    return out


def animal(row):
    out = _pick(row, ("name", "species", "size_class", "weight_lb", "date_of_birth",
                      "temperament", "microchip_id", "identifiable", "litter_id",
                      "current_organization_id", "current_foster_home_id",
                      "current_intake_record_id", "lifecycle_status", "alteration_status",
                      "rabies_vaccinated_at", "restriction_no_children_under_years",
                      "restriction_no_cats", "restriction_no_dogs",
                      "restriction_requires_fenced_yard",
                      "restriction_housing_types_excluded", "current_hub_code"))
    # A read of an animal touches its custody episode, so the monotone hold
    # latch is re-derived here (PRD 2.4).
    current_episode(row)
    out["age_weeks"] = age_weeks(row)
    out["age_months"] = age_months(row)
    out["length_of_stay_days"] = length_of_stay_days(row)
    return out


def litter(row):
    out = _pick(row, ("label", "dam_animal_id", "transport_basis", "split_approved_at"))
    out["member_count"] = litter_member_count(row["id"])
    return out


def intake_record(row):
    latch_hold(row)
    return _pick(row, ("animal_id", "source_person_id", "intake_type", "intake_datetime",
                       "impound_billing_basis", "identifiable_at_intake", "hold_days",
                       "hold_expires_at", "hold_status", "status", "reclaim_base_fee_cents",
                       "impound_billable_days", "impound_subtotal_cents",
                       "repeat_offense_multiplier", "hardship_waiver_cents",
                       "reclaim_total_cents"))


def hold_record(row):
    return _pick(row, ("animal_id", "hold_type", "reason", "status", "released_at",
                       "released_by_user_id"))


def foster_home(row):
    return _pick(row, ("person_id", "label", "dog_slot_capacity", "cat_slot_capacity",
                       "max_headcount", "accepts_cats", "min_child_age_years",
                       "has_fenced_yard", "consumed_dog_slots", "consumed_cat_slots",
                       "consumed_headcount", "capacity_status"))


def foster_application(row):
    lapse_home_check(row)
    return _pick(row, ("person_id", "foster_home_id", "species_requested",
                       "application_status", "home_check_status", "home_check_passed_at",
                       "home_check_expires_at", "decided_by_user_id"))


def foster_placement(row):
    return _pick(row, ("animal_id", "foster_home_id", "foster_application_id", "litter_id",
                       "predecessor_placement_id", "count_basis", "slot_consumption",
                       "headcount_consumption", "status", "started_at", "ended_at",
                       "end_reason"))


def medical_record(row):
    return _pick(row, ("animal_id", "procedure_type", "expense_category", "cost_cents",
                       "funding_required", "scheduled_at", "completed_at", "status",
                       "funded_contribution_ids", "funded_amount_cents",
                       "admin_overhead_cents"))


def health_certificate(row):
    expire_certificate(row)
    return _pick(row, ("animal_id", "issued_at", "destination_state", "vet_license_number",
                       "window_days", "expires_at", "status"))


def transport_run(row):
    return _pick(row, ("origin_organization_id", "partner_commitment_id", "run_type",
                       "purpose", "origin_hub_code", "destination_hub_code", "status",
                       "slots_drawn", "started_at", "aborted_at"))


def transport_leg(row):
    return _pick(row, ("transport_run_id", "driver_person_id", "sequence_no",
                       "origin_hub_code", "destination_hub_code", "scheduled_depart_at",
                       "scheduled_arrive_at", "crate_capacity_units", "weight_capacity_lb",
                       "crosses_state_line", "destination_state_code", "species_policy",
                       "used_crate_units", "used_weight_lb", "status", "departed_at",
                       "arrived_at"))


def manifest_entry(row):
    return _pick(row, ("transport_leg_id", "animal_id", "crate_units", "is_litter_anchor",
                       "status", "stranded_at_hub_code"))


def adoption_application(row):
    return _pick(row, ("animal_id", "applicant_person_id", "attempt_count", "status",
                       "screened_by_user_id", "screened_at", "decline_reason"))


def adoption(row):
    return _pick(row, ("adoption_application_id", "animal_id", "adopter_person_id",
                       "credit_application_order", "refund_basis", "deposit_basis",
                       "base_fee_cents", "waiver_kind", "waiver_applied_cents",
                       "sponsorship_applied_cents", "adopter_charged_cents",
                       "residual_credit_cents", "alteration_deposit_cents",
                       "alteration_deposit_refunded_cents", "adopter_paid_cents",
                       "refund_issued_cents", "credit_restored_cents", "finalized_at",
                       "returned_at", "finalized_by_user_id", "status", "fee_status"))


def outcome_record(row):
    out = _pick(row, ("animal_id", "intake_record_id", "adoption_id",
                      "partner_commitment_id", "counterparty_person_id", "outcome_type",
                      "recorded_at", "reversed_at", "reversal_reason"))
    out["is_live_release"] = row["outcome_type"] in LIVE_OUTCOME_TYPES
    return out


def contribution(row):
    out = _pick(row, ("donor_person_id", "designated_animal_id", "designated_program",
                      "restriction_category", "donor_reference", "amount_cents",
                      "applied_cents", "released_cents", "status", "redesignation_count"))
    out["available_cents"] = available_cents(row)
    return out


def partner_commitment(row):
    return _pick(row, ("organization_id", "species", "slots_total", "expires_at",
                       "slots_drawn", "slots_released", "slots_open", "status"))


SERIALIZERS = {
    "Organization": organization,
    "Person": person,
    "Animal": animal,
    "Litter": litter,
    "IntakeRecord": intake_record,
    "HoldRecord": hold_record,
    "FosterHome": foster_home,
    "FosterApplication": foster_application,
    "FosterPlacement": foster_placement,
    "MedicalRecord": medical_record,
    "HealthCertificate": health_certificate,
    "TransportRun": transport_run,
    "TransportLeg": transport_leg,
    "ManifestEntry": manifest_entry,
    "AdoptionApplication": adoption_application,
    "Adoption": adoption,
    "OutcomeRecord": outcome_record,
    "Contribution": contribution,
    "PartnerCommitment": partner_commitment,
}


def render(row):
    return SERIALIZERS[row["_entity"]](row)
