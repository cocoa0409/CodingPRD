"""Domain model: registries, derived fields, serializers, posture engine,
ledger and the cascades of PRD §2.10 / §2.11 / §3.
"""

from decimal import Decimal

import calc
import store
from store import db

# --------------------------------------------------------------- registries
ROLES = (
    "FacilityRegistrant",
    "ResponsiblePersonAgent",
    "RegulatoryReviewer",
    "EnforcementOfficer",
    "SystemOperator",
)

FACILITY_TYPES = ("MANUFACTURER", "PROCESSOR", "BOTH")
REGISTRATION_STATUSES = ("DRAFT", "PENDING_REVIEW", "REGISTERED", "RENEWAL_DUE", "LAPSED", "REJECTED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
POSTURE_SEVERITY = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}

PERIOD_KINDS = ("INITIAL", "RENEWAL", "LATE_RENEWAL")
PERIOD_STATUSES = ("ACTIVE", "EXPIRED")

OWNERSHIP_STATUSES = ("FILED", "ACCEPTED", "REJECTED", "SUPERSEDED")

LISTING_STATUSES = ("DRAFT", "SUBMITTED", "LISTED", "RETURNED", "SUSPENDED", "DELISTED")
SAFETY_STATUSES = (
    "UNSUBSTANTIATED",
    "UNDER_SUBSTANTIATION",
    "SUBSTANTIATED",
    "SUBSTANTIATION_FAILED",
    "REVALIDATION_REQUIRED",
)
SUSPENSION_REASONS = ("FACILITY_LAPSED", "RECALL_ESCALATION")
PRODUCT_FORMS = ("LEAVE_ON", "RINSE_OFF")
LABEL_CONTACT_TYPES = ("DOMESTIC_ADDRESS", "DOMESTIC_PHONE", "ELECTRONIC_CONTACT")
CONSUMER_LABEL_CONTACT_TYPES = ("DOMESTIC_ADDRESS", "ELECTRONIC_CONTACT")

# PRD §3.3 cosmetic category registry — exact, case-sensitive.
CATEGORY_CODES = ("01A", "02C", "03B", "05G", "07A", "08D", "11E", "12A")
PROFESSIONAL_USE_PERMITTED_CATEGORIES = ("03B", "05G", "08D", "11E")

FUNCTION_CODES = ("FRAGRANCE", "PRESERVATIVE", "COLORANT", "SURFACTANT", "ACTIVE", "OTHER")

SUBSTANTIATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "ADEQUATE",
    "DEFICIENT",
    "REVALIDATION_REQUIRED",
    "SUPERSEDED",
)
ASSESSMENT_BASES = ("PRODUCT_SPECIFIC", "INGREDIENT_READ_ACROSS", "PANEL_MONOGRAPH")
REVIEW_MODES = ("SCREENING", "FULL")
EVIDENCE_TYPES = (
    "CLINICAL_SAFETY_STUDY",
    "IN_VITRO_TOXICOLOGY",
    "READ_ACROSS_ANALOG",
    "HISTORICAL_USE_DOSSIER",
    "LITERATURE_REVIEW",
)
REVIEWER_CREDENTIALS = (
    "BOARD_CERTIFIED_TOXICOLOGIST",
    "ERT",
    "QUALIFIED_SAFETY_ASSESSOR",
    "OTHER",
)

SERIOUSNESS_VALUES = ("SERIOUS", "NON_SERIOUS")
OUTCOME_CODES = (
    "DEATH",
    "HOSPITALIZATION",
    "DISFIGUREMENT",
    "SERIOUS_PERSISTENT",
    "INFECTION",
    "NONE",
)
REPORT_STATUSES = (
    "RECORDED",
    "RETAINED",
    "REPORT_DUE",
    "REPORTED_TIMELY",
    "REPORTED_LATE",
    "REPORT_OVERDUE",
)
OPEN_SERIOUS_STATUSES = ("REPORT_DUE", "REPORT_OVERDUE")

INSPECTION_TYPES = ("GMP_ROUTINE", "FOR_CAUSE", "PREANNOUNCED_FOLLOWUP")
INSPECTION_STATUSES = (
    "SCHEDULED",
    "OBSERVATIONS_ISSUED",
    "RESPONSE_SUBMITTED",
    "CLOSED_NAI",
    "CLOSED_VAI",
    "ESCALATED_OAI",
)
INSPECTION_TERMINAL_STATUSES = ("CLOSED_NAI", "CLOSED_VAI", "ESCALATED_OAI")
INSPECTION_OBSERVED_STATUSES = (
    "OBSERVATIONS_ISSUED",
    "RESPONSE_SUBMITTED",
    "CLOSED_NAI",
    "CLOSED_VAI",
    "ESCALATED_OAI",
)

RECALL_STATUSES = (
    "PLAN_REQUIRED",
    "PLAN_SUBMITTED",
    "PLAN_ACCEPTED",
    "PLAN_REJECTED",
    "EXECUTING",
    "EXTENDED",
    "CLOSED_EFFECTIVE",
    "ESCALATED_MANDATORY",
)
RECALL_OPEN_STATUSES = (
    "PLAN_REQUIRED",
    "PLAN_SUBMITTED",
    "PLAN_ACCEPTED",
    "PLAN_REJECTED",
    "EXECUTING",
    "EXTENDED",
)
INITIATION_BASES = ("MANDATORY_ORDER", "VOLUNTARY_NOTICE")
HAZARD_CLASSES = ("CLASS_I", "CLASS_II", "CLASS_III")
DISTRIBUTION_DEPTHS = ("WHOLESALE", "RETAIL", "CONSUMER")
MAX_PLAN_ROUNDS = 3

WITHDRAWAL_STATUSES = (
    "OPEN",
    "RECORDS_PRODUCED",
    "INTERIM_REVIEWED",
    "CLOSED_EFFECTIVE",
    "EXTENDED_INEFFECTIVE",
    "SUPERSEDED",
)
WITHDRAWAL_SUPERSEDABLE = ("OPEN", "RECORDS_PRODUCED", "INTERIM_REVIEWED", "EXTENDED_INEFFECTIVE")
EFFECTIVENESS_BASES = ("REPORTED_BASIS", "VERIFIED_BASIS")

CONSIGNEE_CLASSES = ("WHOLESALE", "RETAIL", "CONSUMER")

RECOVERY_BUCKETS = {
    "REPORTED_RETURN": "units_reported_returned",
    "REPORTED_DESTRUCTION": "units_reported_destroyed",
    "IN_TRANSIT_RETURN": "units_in_transit_returns",
    "VERIFIED_RETURN": "units_verified_returned",
    "VERIFIED_DESTRUCTION": "units_verified_destroyed",
}
RECOVERY_ENTRY_KINDS = tuple(list(RECOVERY_BUCKETS.keys()) + ["CORRECTION_REVERSAL"])
VERIFIED_BUCKETS = ("units_verified_returned", "units_verified_destroyed")
BUCKET_FIELDS = tuple(RECOVERY_BUCKETS.values())
RECOVERY_BUCKET_KINDS = tuple(RECOVERY_BUCKETS.keys())


def resolve_bucket_field(value):
    """A reversal names its target bucket either by movement kind (REPORTED_RETURN)
    or by the record's own field name (units_reported_returned)."""
    if value in RECOVERY_BUCKETS:
        return RECOVERY_BUCKETS[value]
    if value in BUCKET_FIELDS:
        return value
    return None

LEDGER_ENTRY_TYPES = (
    "POSTURE_CHANGE",
    "UNIT_MOVEMENT",
    "STATE_TRANSITION",
    "DEADLINE_BREACH",
    "ADVERSE_EVENT_REPORT",
    "INSPECTION_OUTCOME",
    "RECALL_DECISION",
    "WITHDRAWAL_CLOSURE",
    "OWNERSHIP_CHANGE",
)
SUBJECT_ENTITIES = (
    "Facility",
    "ProductListing",
    "AdverseEvent",
    "InspectionEngagement",
    "RecallAction",
    "MarketWithdrawal",
    "DistributionRecord",
    "OwnershipChangeUpdate",
)

ADMISSIBLE_REGISTERED = ("REGISTERED", "RENEWAL_DUE")

DESIGNATION_CAP_DEFAULT = 25
GMP_NAI_THRESHOLD = Decimal("85.00")
GMP_VAI_THRESHOLD = Decimal("70.00")
RESPONSE_WINDOW_DAYS = 15
SERIOUS_REPORT_DEADLINE_DAYS = 15
OWNERSHIP_FILING_DEADLINE_DAYS = 60
RENEWAL_WINDOW_DAYS = 90
GRACE_PERIOD_DAYS = 60
RETENTION_YEARS_CONSUMER = 3
RETENTION_YEARS_SERIOUS_OR_PROFESSIONAL = 6
POSTURE_FROZEN_POINTS = Decimal("25.00")
POSTURE_RESTRICTED_POINTS = Decimal("10.00")


# ------------------------------------------------------------------- lookups
def listings_of_facility(facility_id):
    return [l for l in db["listings"].values() if l["facility_id"] == facility_id]


def ingredients_of_listing(listing_id):
    return [i for i in db["ingredients"].values() if i["listing_id"] == listing_id]


def substantiations_of_listing(listing_id):
    return [s for s in db["substantiations"].values() if s["listing_id"] == listing_id]


def review_items_of(substantiation_id):
    return [r for r in db["review_items"].values() if r["substantiation_id"] == substantiation_id]


def events_of_listing(listing_id):
    return [e for e in db["adverse_events"].values() if e["listing_id"] == listing_id]


def inspections_of_facility(facility_id):
    return [i for i in db["inspections"].values() if i["facility_id"] == facility_id]


def periods_of_facility(facility_id):
    return [p for p in db["periods"].values() if p["facility_id"] == facility_id]


def ownership_changes_of_facility(facility_id):
    return [o for o in db["ownership_changes"].values() if o["facility_id"] == facility_id]


def recalls_of_listing(listing_id):
    return [r for r in db["recalls"].values() if r["listing_id"] == listing_id]


def withdrawals_of_recall(recall_id):
    return [w for w in db["withdrawals"].values() if w["recall_action_id"] == recall_id]


def records_of_listing(listing_id):
    return [r for r in db["distribution_records"].values() if r["listing_id"] == listing_id]


def records_of_withdrawal(withdrawal_id):
    return [r for r in db["distribution_records"].values() if r["withdrawal_id"] == withdrawal_id]


def ledger_of_facility(facility_id):
    return [e for e in db["ledger"].values() if e["facility_id"] == facility_id]


def listings_of_responsible_person(rp_id):
    return [l for l in db["listings"].values() if l["responsible_person_id"] == rp_id]


def facility_of_listing(listing):
    return store.get("facilities", listing["facility_id"])


def listing_of_substantiation(sub):
    return store.get("listings", sub["listing_id"])


def listing_of_recall(recall):
    return store.get("listings", recall["listing_id"])


def recall_of_withdrawal(withdrawal):
    return store.get("recalls", withdrawal["recall_action_id"])


def listing_of_withdrawal(withdrawal):
    recall = recall_of_withdrawal(withdrawal)
    return listing_of_recall(recall) if recall else None


def facility_events(facility_id):
    events = []
    for listing in listings_of_facility(facility_id):
        events.extend(events_of_listing(listing["id"]))
    return events


def facility_recalls(facility_id):
    recalls = []
    for listing in listings_of_facility(facility_id):
        recalls.extend(recalls_of_listing(listing["id"]))
    return recalls


# ------------------------------------------------------------ derived fields
def ingredient_disclosure_required(ingredient, listing=None):
    listing = listing or store.get("listings", ingredient["listing_id"])
    if listing is None:
        return False
    return calc.disclosure_required(ingredient, listing)


def undisclosed_allergen_count(listing):
    """PRD §3.3 — ingredients that require disclosure but are not label_disclosed."""
    count = 0
    for ingredient in ingredients_of_listing(listing["id"]):
        if ingredient_disclosure_required(ingredient, listing) and not ingredient["label_disclosed"]:
            count += 1
    return count


def allergen_disclosure_complete(listing):
    return undisclosed_allergen_count(listing) == 0


def listing_data_gap(listing_id):
    return any(i["is_data_gap_flag"] for i in ingredients_of_listing(listing_id))


def distributed_units_total(listing):
    return sum(r["units_shipped"] for r in records_of_listing(listing["id"]))


def open_recall_count(listing):
    return len([r for r in recalls_of_listing(listing["id"]) if r["status"] in RECALL_OPEN_STATUSES])


def listing_open_serious_event_count(listing):
    return len([
        e for e in events_of_listing(listing["id"])
        if e["seriousness"] == "SERIOUS" and e["report_status"] in OPEN_SERIOUS_STATUSES
    ])


def facility_open_serious_event_count(facility):
    return len([
        e for e in facility_events(facility["id"])
        if e["seriousness"] == "SERIOUS" and e["report_status"] in OPEN_SERIOUS_STATUSES
    ])


def event_points_of(event):
    listing = store.get("listings", event["listing_id"])
    professional = bool(listing and listing.get("professional_use_only"))
    return calc.event_points(event["report_status"], event.get("lateness_days") or 0, professional)


def retention_until_of(event):
    listing = store.get("listings", event["listing_id"])
    professional = bool(listing and listing.get("professional_use_only"))
    years = (
        RETENTION_YEARS_SERIOUS_OR_PROFESSIONAL
        if (event["seriousness"] == "SERIOUS" or professional)
        else RETENTION_YEARS_CONSUMER
    )
    return store.add_years(event["received_at"].date(), years)


def serious_event_points(facility):
    values = [event_points_of(e) for e in facility_events(facility["id"])
              if e["report_status"] in calc.POINT_BEARING_STATUSES]
    return calc.facility_points(values)


def listed_product_count(facility):
    return len([l for l in listings_of_facility(facility["id"]) if l["listing_status"] == "LISTED"])


def abbreviated_renewal_eligible(facility):
    """PRD §3.2 — posture OPEN and no accepted ownership change inside the window."""
    if facility["compliance_posture"] != "OPEN":
        return False
    start = facility.get("current_period_start")
    end = facility.get("current_period_end")
    if start is None or end is None:
        return True
    for filing in ownership_changes_of_facility(facility["id"]):
        if filing["status"] != "ACCEPTED":
            continue
        effective = filing["change_effective_date"]
        if start <= effective <= end:
            return False
    return True


def listing_marketable(listing):
    facility = facility_of_listing(listing)
    if facility is None:
        return False
    return (
        listing["listing_status"] == "LISTED"
        and listing["safety_status"] == "SUBSTANTIATED"
        and allergen_disclosure_complete(listing)
        and facility["compliance_posture"] != "FROZEN"
    )


def active_designation_count(rp):
    return len([
        l for l in listings_of_responsible_person(rp["id"])
        if l["listing_status"] in ("SUBMITTED", "LISTED")
    ])


def responsible_person_status(rp):
    return "ACTIVE" if active_designation_count(rp) >= 1 else "DORMANT"


def record_units_outstanding(record):
    return (
        record["units_shipped"]
        - record["units_verified_returned"]
        - record["units_verified_destroyed"]
    )


def withdrawal_records_count(withdrawal):
    return len(records_of_withdrawal(withdrawal["id"]))


def withdrawal_shipped_units(withdrawal):
    return sum(r["units_shipped"] for r in records_of_withdrawal(withdrawal["id"]))


def withdrawal_reported_units(withdrawal):
    return sum(
        r["units_reported_returned"] + r["units_reported_destroyed"] + r["units_in_transit_returns"]
        for r in records_of_withdrawal(withdrawal["id"])
    )


def withdrawal_verified_units(withdrawal):
    return sum(
        r["units_verified_returned"] + r["units_verified_destroyed"]
        for r in records_of_withdrawal(withdrawal["id"])
    )


def withdrawal_outstanding_units(withdrawal):
    return sum(record_units_outstanding(r) for r in records_of_withdrawal(withdrawal["id"]))


# ----------------------------------------------------------- posture engine
def points_reading(points):
    if points >= POSTURE_FROZEN_POINTS:
        return "FROZEN"
    if points >= POSTURE_RESTRICTED_POINTS:
        return "RESTRICTED"
    return "OPEN"


def override_reading(facility):
    if facility["registration_status"] == "LAPSED":
        return "FROZEN"
    for recall in facility_recalls(facility["id"]):
        if recall["status"] == "ESCALATED_MANDATORY":
            return "FROZEN"
    for engagement in inspections_of_facility(facility["id"]):
        if engagement["status"] == "ESCALATED_OAI":
            return "RESTRICTED"
    return "OPEN"


def compute_posture(facility):
    from_points = points_reading(serious_event_points(facility))
    from_override = override_reading(facility)
    if POSTURE_SEVERITY[from_override] > POSTURE_SEVERITY[from_points]:
        return from_override
    return from_points


def recompute_posture(facility):
    """Returns (changed, before, after, escalated_out_of_open)."""
    before = facility["compliance_posture"]
    after = compute_posture(facility)
    facility["compliance_posture"] = after
    changed = after != before
    escalated = before == "OPEN" and after != "OPEN"
    return changed, before, after, escalated


# ------------------------------------------------------------------- ledger
def ledger_append(facility_id, entry_type, subject_entity, subject_id, detail,
                  signed_units_delta=0, posture_before=None, posture_after=None):
    """PRD §2.11 — append-only, 1-based sequence_no per facility."""
    sequence_no = len(ledger_of_facility(facility_id)) + 1
    return store.insert(
        "ledger",
        {
            "facility_id": facility_id,
            "entry_type": entry_type,
            "subject_entity": subject_entity,
            "subject_id": subject_id,
            "signed_units_delta": signed_units_delta if entry_type == "UNIT_MOVEMENT" else 0,
            "posture_before": posture_before if entry_type == "POSTURE_CHANGE" else None,
            "posture_after": posture_after if entry_type == "POSTURE_CHANGE" else None,
            "detail": detail,
            "occurred_at": store.now_iso(),
            "sequence_no": sequence_no,
        },
        common=False,
    )


# -------------------------------------------------------------- serializers
def facility_json(facility):
    return {
        "id": facility["id"],
        "facility_name": facility["facility_name"],
        "owner_operator_name": facility["owner_operator_name"],
        "facility_type": facility["facility_type"],
        "country_code": facility["country_code"],
        "state_or_province": facility["state_or_province"],
        "facility_fei": facility["facility_fei"],
        "registration_status": facility["registration_status"],
        "compliance_posture": facility["compliance_posture"],
        "serious_event_points": calc.num(serious_event_points(facility)),
        "registration_cycle_count": facility["registration_cycle_count"],
        "current_period_start": store.iso_date(facility["current_period_start"]),
        "current_period_end": store.iso_date(facility["current_period_end"]),
        "renewal_window_open_date": store.iso_date(facility["renewal_window_open_date"]),
        "grace_end_date": store.iso_date(facility["grace_end_date"]),
        "listed_product_count": listed_product_count(facility),
        "open_serious_event_count": facility_open_serious_event_count(facility),
        "gmp_readiness_score": calc.num(facility["gmp_readiness_score"]),
        "last_inspection_outcome": facility["last_inspection_outcome"],
        "abbreviated_renewal_eligible": abbreviated_renewal_eligible(facility),
        "created_at": facility["created_at"],
        "updated_at": facility["updated_at"],
        "version": facility["version"],
    }


def period_json(period):
    return {
        "id": period["id"],
        "facility_id": period["facility_id"],
        "period_kind": period["period_kind"],
        "period_start": store.iso_date(period["period_start"]),
        "period_end": store.iso_date(period["period_end"]),
        "renewal_window_open_date": store.iso_date(period["renewal_window_open_date"]),
        "grace_end_date": store.iso_date(period["grace_end_date"]),
        "sequence_index": period["sequence_index"],
        "status": period["status"],
        "created_at": period["created_at"],
        "updated_at": period["updated_at"],
        "version": period["version"],
    }


def ownership_change_json(filing):
    return {
        "id": filing["id"],
        "facility_id": filing["facility_id"],
        "new_owner_operator_name": filing["new_owner_operator_name"],
        "change_effective_date": store.iso_date(filing["change_effective_date"]),
        "filed_at": store.iso(filing["filed_at"]),
        "filing_deadline_at": store.iso(filing["filing_deadline_at"]),
        "is_late_filing": filing["is_late_filing"],
        "status": filing["status"],
        "decision_note": filing["decision_note"],
        "decided_by_user_id": filing["decided_by_user_id"],
        "created_at": filing["created_at"],
        "updated_at": filing["updated_at"],
        "version": filing["version"],
    }


def responsible_person_json(rp):
    return {
        "id": rp["id"],
        "legal_name": rp["legal_name"],
        "us_address_line": rp["us_address_line"],
        "contact_phone": rp["contact_phone"],
        "contact_email": rp["contact_email"],
        "designation_cap": rp["designation_cap"],
        "active_designation_count": active_designation_count(rp),
        "status": responsible_person_status(rp),
        "created_at": rp["created_at"],
        "updated_at": rp["updated_at"],
        "version": rp["version"],
    }


def listing_json(listing):
    return {
        "id": listing["id"],
        "facility_id": listing["facility_id"],
        "responsible_person_id": listing["responsible_person_id"],
        "product_name": listing["product_name"],
        "category_code": listing["category_code"],
        "product_form": listing["product_form"],
        "professional_use_only": listing["professional_use_only"],
        "professional_use_statement_present": listing["professional_use_statement_present"],
        "label_contact_type": listing["label_contact_type"],
        "label_contact_value": listing["label_contact_value"],
        "lot_authorized_units": listing["lot_authorized_units"],
        "listing_number": listing["listing_number"],
        "listing_status": listing["listing_status"],
        "safety_status": listing["safety_status"],
        "suspension_reason": listing["suspension_reason"],
        "allergen_disclosure_complete": allergen_disclosure_complete(listing),
        "undisclosed_allergen_count": undisclosed_allergen_count(listing),
        "distributed_units_total": distributed_units_total(listing),
        "open_recall_count": open_recall_count(listing),
        "open_serious_event_count": listing_open_serious_event_count(listing),
        "marketable": listing_marketable(listing),
        "created_at": listing["created_at"],
        "updated_at": listing["updated_at"],
        "version": listing["version"],
    }


def ingredient_json(ingredient):
    return {
        "id": ingredient["id"],
        "listing_id": ingredient["listing_id"],
        "inci_name": ingredient["inci_name"],
        "cas_number": ingredient["cas_number"],
        "function_code": ingredient["function_code"],
        "concentration_pct": calc.num(ingredient["concentration_pct"]),
        "is_fragrance_allergen": ingredient["is_fragrance_allergen"],
        "label_disclosed": ingredient["label_disclosed"],
        "is_data_gap_flag": ingredient["is_data_gap_flag"],
        "disclosure_required": ingredient_disclosure_required(ingredient),
        "created_at": ingredient["created_at"],
        "updated_at": ingredient["updated_at"],
        "version": ingredient["version"],
    }


def substantiation_json(sub):
    return {
        "id": sub["id"],
        "listing_id": sub["listing_id"],
        "assessor_name": sub["assessor_name"],
        "assessment_basis": sub["assessment_basis"],
        "status": sub["status"],
        "review_mode": sub["review_mode"],
        "adequacy_score": calc.num(sub["adequacy_score"]),
        "screening_reviewer_user_id": sub["screening_reviewer_user_id"],
        "full_reviewer_user_id": sub["full_reviewer_user_id"],
        "revision_round": sub["revision_round"],
        "data_gap_present": sub["data_gap_present"],
        "decided_at": store.iso(sub["decided_at"]),
        "created_at": sub["created_at"],
        "updated_at": sub["updated_at"],
        "version": sub["version"],
    }


def review_item_json(item):
    return {
        "id": item["id"],
        "substantiation_id": item["substantiation_id"],
        "evidence_type": item["evidence_type"],
        "reviewer_credential": item["reviewer_credential"],
        "citation": item["citation"],
        "screening_contribution": calc.num(item["screening_contribution"]),
        "full_contribution": calc.num(item["full_contribution"]),
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "version": item["version"],
    }


def adverse_event_json(event):
    return {
        "id": event["id"],
        "listing_id": event["listing_id"],
        "event_description": event["event_description"],
        "received_at": store.iso(event["received_at"]),
        "seriousness": event["seriousness"],
        "outcome_code": event["outcome_code"],
        "report_status": event["report_status"],
        "deadline_basis_at": store.iso(event["deadline_basis_at"]),
        "deadline_at": store.iso(event["deadline_at"]),
        "reclassified_at": store.iso(event["reclassified_at"]),
        "submitted_at": store.iso(event["submitted_at"]),
        "lateness_days": event["lateness_days"],
        "event_points": calc.num(event_points_of(event)),
        "retention_until": store.iso_date(retention_until_of(event)),
        "created_at": event["created_at"],
        "updated_at": event["updated_at"],
        "version": event["version"],
    }


def inspection_json(engagement):
    subscores = engagement["category_subscores"]
    return {
        "id": engagement["id"],
        "facility_id": engagement["facility_id"],
        "inspection_type": engagement["inspection_type"],
        "window_start": store.iso_date(engagement["window_start"]),
        "window_end": store.iso_date(engagement["window_end"]),
        "status": engagement["status"],
        "observation_count": engagement["observation_count"],
        "category_subscores": (
            None if subscores is None
            else {k: calc.num(v) for k, v in subscores.items()}
        ),
        "readiness_score": calc.num(engagement["readiness_score"]),
        "outcome_class": engagement["outcome_class"],
        "response_due_at": store.iso(engagement["response_due_at"]),
        "response_submitted_at": store.iso(engagement["response_submitted_at"]),
        "response_summary": engagement["response_summary"],
        "created_at": engagement["created_at"],
        "updated_at": engagement["updated_at"],
        "version": engagement["version"],
    }


def recall_json(recall):
    return {
        "id": recall["id"],
        "listing_id": recall["listing_id"],
        "initiation_basis": recall["initiation_basis"],
        "hazard_class": recall["hazard_class"],
        "status": recall["status"],
        "plan_round": recall["plan_round"],
        "corrective_summary": recall["corrective_summary"],
        "distribution_depth": recall["distribution_depth"],
        "plan_submitted_at": store.iso(recall["plan_submitted_at"]),
        "plan_decision_user_id": recall["plan_decision_user_id"],
        "plan_decision_at": store.iso(recall["plan_decision_at"]),
        "effectiveness_rate_final": calc.num(recall["effectiveness_rate_final"]),
        "created_at": recall["created_at"],
        "updated_at": recall["updated_at"],
        "version": recall["version"],
    }


def withdrawal_json(withdrawal):
    return {
        "id": withdrawal["id"],
        "recall_action_id": withdrawal["recall_action_id"],
        "scope_depth": withdrawal["scope_depth"],
        "status": withdrawal["status"],
        "records_produced_count": withdrawal_records_count(withdrawal),
        "shipped_units_total": withdrawal_shipped_units(withdrawal),
        "reported_recovered_units": withdrawal_reported_units(withdrawal),
        "verified_recovered_units": withdrawal_verified_units(withdrawal),
        "outstanding_units_total": withdrawal_outstanding_units(withdrawal),
        "reported_recovery_rate": calc.num(withdrawal["reported_recovery_rate"]),
        "provisional_verified_rate": calc.num(withdrawal["provisional_verified_rate"]),
        "unreachable_credit_pct": withdrawal["unreachable_credit_pct"],
        "adjusted_denominator_units": withdrawal["adjusted_denominator_units"],
        "verified_recovery_rate": calc.num(withdrawal["verified_recovery_rate"]),
        "effectiveness_verdict": withdrawal["effectiveness_verdict"],
        "effectiveness_reviewer_user_id": withdrawal["effectiveness_reviewer_user_id"],
        "created_at": withdrawal["created_at"],
        "updated_at": withdrawal["updated_at"],
        "version": withdrawal["version"],
    }


def distribution_record_json(record):
    return {
        "id": record["id"],
        "listing_id": record["listing_id"],
        "withdrawal_id": record["withdrawal_id"],
        "lot_code": record["lot_code"],
        "consignee_name": record["consignee_name"],
        "consignee_class": record["consignee_class"],
        "ship_date": store.iso_date(record["ship_date"]),
        "delivery_date": store.iso_date(record["delivery_date"]),
        "units_shipped": record["units_shipped"],
        "units_reported_returned": record["units_reported_returned"],
        "units_reported_destroyed": record["units_reported_destroyed"],
        "units_in_transit_returns": record["units_in_transit_returns"],
        "units_verified_returned": record["units_verified_returned"],
        "units_verified_destroyed": record["units_verified_destroyed"],
        "units_outstanding": record_units_outstanding(record),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def ledger_json(entry):
    return {
        "id": entry["id"],
        "facility_id": entry["facility_id"],
        "entry_type": entry["entry_type"],
        "subject_entity": entry["subject_entity"],
        "subject_id": entry["subject_id"],
        "signed_units_delta": entry["signed_units_delta"],
        "posture_before": entry["posture_before"],
        "posture_after": entry["posture_after"],
        "detail": entry["detail"],
        "occurred_at": entry["occurred_at"],
        "sequence_no": entry["sequence_no"],
        "created_at": entry["created_at"],
    }


# ---------------------------------------------------------------- cascades
def refresh_data_gap(listing):
    """Adding an ingredient refreshes data_gap_present on non-SUPERSEDED dossiers."""
    gap = listing_data_gap(listing["id"])
    for dossier in substantiations_of_listing(listing["id"]):
        if dossier["status"] != "SUPERSEDED":
            dossier["data_gap_present"] = gap


def fire_revalidation(facility):
    """PRD §2.10 revalidation cascade.  Returns [(listing, dossiers_moved), ...]
    visited in ascending owning-listing created_at, then dossier created_at."""
    affected = []
    for listing in store.by_created(listings_of_facility(facility["id"])):
        dossiers = [
            d for d in store.by_created(substantiations_of_listing(listing["id"]))
            if d["status"] == "ADEQUATE"
        ]
        if not dossiers:
            continue
        for dossier in dossiers:
            dossier["status"] = "REVALIDATION_REQUIRED"
            store.touch(dossier)
        listing["safety_status"] = "REVALIDATION_REQUIRED"
        store.touch(listing)
        affected.append((listing, len(dossiers)))
    return affected


def ledger_revalidation(facility, affected):
    for listing, _count in affected:
        ledger_append(
            facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
            "Safety substantiation revalidation required after posture escalation.",
        )


def revalidated_dossier_count(affected):
    return sum(count for _listing, count in affected)


def posture_refresh(facility):
    """Recompute posture, touch the facility, and run the revalidation cascade
    when the recomputation raises the posture out of OPEN."""
    changed, before, after, escalated = recompute_posture(facility)
    store.touch(facility)
    affected = fire_revalidation(facility) if escalated else []
    return changed, before, after, affected


def distinct_designees(listings):
    seen = []
    seen_ids = set()
    for listing in listings:
        rp_id = listing["responsible_person_id"]
        if rp_id in seen_ids:
            continue
        rp = store.get("responsible_persons", rp_id)
        if rp is not None:
            seen_ids.add(rp_id)
            seen.append(rp)
    return seen


def set_period_fields(facility, period):
    facility["current_period_start"] = period["period_start"]
    facility["current_period_end"] = period["period_end"]
    facility["renewal_window_open_date"] = period["renewal_window_open_date"]
    facility["grace_end_date"] = period["grace_end_date"]


def create_period(facility, period_kind, period_start, sequence_index):
    period_end, renewal_open, grace_end = calc.period_bounds(period_start)
    period = store.insert("periods", {
        "facility_id": facility["id"],
        "period_kind": period_kind,
        "period_start": period_start,
        "period_end": period_end,
        "renewal_window_open_date": renewal_open,
        "grace_end_date": grace_end,
        "sequence_index": sequence_index,
        "status": "ACTIVE",
    })
    set_period_fields(facility, period)
    return period


def active_period(facility):
    for period in periods_of_facility(facility["id"]):
        if period["status"] == "ACTIVE":
            return period
    return None


def latest_period(facility):
    periods = periods_of_facility(facility["id"])
    if not periods:
        return None
    return sorted(periods, key=lambda p: p["sequence_index"])[-1]


def expire_active_period(facility):
    period = active_period(facility)
    if period is not None:
        period["status"] = "EXPIRED"
        store.touch(period)
    return period


def lapse_facility(facility):
    """PRD §3.1 lapse cascade (sweep only).  Returns (suspended, affected)."""
    facility["registration_status"] = "LAPSED"
    expire_active_period(facility)
    changed, before, after, escalated = recompute_posture(facility)
    store.touch(facility)

    suspended = []
    for listing in store.by_created(listings_of_facility(facility["id"])):
        if listing["listing_status"] in ("SUBMITTED", "LISTED"):
            listing["listing_status"] = "SUSPENDED"
            listing["suspension_reason"] = "FACILITY_LAPSED"
            store.touch(listing)
            suspended.append(listing)
    for rp in distinct_designees(suspended):
        store.touch(rp)

    affected = fire_revalidation(facility) if escalated else []

    ledger_append(
        facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
        "Registration lapsed; compliance posture recomputed.",
        posture_before=before, posture_after=after,
    )
    for listing in suspended:
        ledger_append(
            facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
            "Listing suspended because the establishment registration lapsed.",
        )
    ledger_revalidation(facility, affected)
    return suspended, affected


def restore_after_late_renewal(facility):
    """PRD §3.1 late-renewal compensation.  RECALL_ESCALATION is never restored."""
    restored = []
    for listing in store.by_created(listings_of_facility(facility["id"])):
        if listing["listing_status"] == "SUSPENDED" and listing["suspension_reason"] == "FACILITY_LAPSED":
            listing["listing_status"] = "LISTED"
            listing["suspension_reason"] = None
            store.touch(listing)
            restored.append(listing)
    for rp in distinct_designees(restored):
        store.touch(rp)
    return restored


def escalate_recall(recall):
    """PRD §3.8 third-rejection escalation of a MANDATORY_ORDER recall."""
    recall["status"] = "ESCALATED_MANDATORY"
    store.touch(recall)
    listing = listing_of_recall(recall)
    facility = facility_of_listing(listing)
    suspended = None
    if listing["listing_status"] in ("SUBMITTED", "LISTED"):
        listing["listing_status"] = "SUSPENDED"
        listing["suspension_reason"] = "RECALL_ESCALATION"
        store.touch(listing)
        suspended = listing
        for rp in distinct_designees([listing]):
            store.touch(rp)
    changed, before, after, escalated = recompute_posture(facility)
    store.touch(facility)
    affected = fire_revalidation(facility) if escalated else []

    ledger_append(
        facility["id"], "RECALL_DECISION", "RecallAction", recall["id"],
        "Recall escalated to mandatory after the third plan rejection.",
    )
    ledger_append(
        facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
        "Compliance posture recomputed after mandatory recall escalation.",
        posture_before=before, posture_after=after,
    )
    if suspended is not None:
        ledger_append(
            facility["id"], "STATE_TRANSITION", "ProductListing", suspended["id"],
            "Listing suspended because the recall escalated to a mandatory order.",
        )
    ledger_revalidation(facility, affected)
    return affected


def close_inspection_vai(engagement, facility):
    engagement["status"] = "CLOSED_VAI"
    engagement["outcome_class"] = "VAI"
    store.touch(engagement)
    facility["last_inspection_outcome"] = "VAI"
    store.touch(facility)
    ledger_append(
        facility["id"], "INSPECTION_OUTCOME", "InspectionEngagement", engagement["id"],
        "Inspection engagement closed as VAI.",
    )


def escalate_inspection_oai(engagement, facility):
    engagement["status"] = "ESCALATED_OAI"
    engagement["outcome_class"] = "OAI"
    store.touch(engagement)
    facility["last_inspection_outcome"] = "OAI"
    changed, before, after, escalated = recompute_posture(facility)
    store.touch(facility)
    affected = fire_revalidation(facility) if escalated else []
    ledger_append(
        facility["id"], "INSPECTION_OUTCOME", "InspectionEngagement", engagement["id"],
        "Inspection engagement escalated to OAI.",
    )
    ledger_append(
        facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
        "Compliance posture recomputed after OAI escalation.",
        posture_before=before, posture_after=after,
    )
    ledger_revalidation(facility, affected)
    return affected


def refresh_inspection_mirror(engagement, facility):
    """The establishment mirrors the latest engagement to have issued observations."""
    facility["gmp_readiness_score"] = engagement["readiness_score"]
