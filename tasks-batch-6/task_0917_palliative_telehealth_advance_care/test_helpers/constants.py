"""Domain thresholds and numeric constants stated in the PRD."""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_INSTANT = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_RENDERED = "2026-05-01T00:00:00.000Z"

# A convenient "programme is running" instant used by most fixtures.
BASE_CLOCK = "2026-06-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Referral triage (PRD 3.1)
# ---------------------------------------------------------------------------
REFERRAL = {
    "PROGNOSIS_HORIZON_MONTHS": 12,
    "SOURCE_WEIGHT_HOSPITAL_DISCHARGE": 30,
    "SOURCE_WEIGHT_PAYER": 20,
    "CRITERIA_POINTS": 12,
    "CLINICIAN_CRITERIA_MULTIPLIER": 2,
    "PAYER_PROGNOSIS_POINTS_PER_MONTH": 4,
    "CLINICIAN_PROGNOSIS_POINTS_PER_MONTH": 2,
    "TRIAGE_SCORE_CAP": 100,
    "ACCEPT_MIN_SCORE": 60,
    "MAX_REREFERRALS": 2,
}

# ---------------------------------------------------------------------------
# Surrogate hierarchy (PRD 3.2)
# ---------------------------------------------------------------------------
HIERARCHY_RANKS = {
    "HEALTHCARE_AGENT": 1,
    "SPOUSE": 2,
    "ADULT_CHILD": 3,
    "PARENT": 4,
    "SIBLING": 5,
}

# ---------------------------------------------------------------------------
# Advance care documents (PRD 3.3)
# ---------------------------------------------------------------------------
DOCUMENT = {
    "REQUIRED_WITNESSES": 2,
    "REQUIRED_NOTARIES": 1,
    "REQUIRED_POLST_PHYSICIAN_SIGNATURES": 1,
    "REQUIRED_POLST_PATIENT_SIGNATURES": 1,
    "REATTEST_DAYS": 365,
}

# ---------------------------------------------------------------------------
# Code status ladder (PRD 3.4)
# ---------------------------------------------------------------------------
CODE_STATUS_RANKS = {
    "FULL_CODE": 1,
    "DNR": 2,
    "DNR_DNI": 3,
    "COMFORT_MEASURES_ONLY": 4,
}
MAX_LADDER_STEP_PER_ORDER = 1
CODE_STATUS_ATTESTATIONS_REQUIRED = 2

# ---------------------------------------------------------------------------
# Symptom assessment scoring (PRD 3.5)
# ---------------------------------------------------------------------------
SYMPTOM = {
    "SELF_SCALE": 2.0,
    "PROXY_SUBJECTIVE_WEIGHT": 0.6,
    "PROXY_SCALE": 2.5,
    "DISTRESS_CAP": 100,
    "SEVERE_FLOOR": 70,
    "MODERATE_FLOOR": 40,
    "MILD_FLOOR": 15,
}
SEVERITY_SLA_MINUTES = {
    "SEVERE": 30,
    "MODERATE": 240,
    "MILD": 1440,
    "MINIMAL": 4320,
}

# ---------------------------------------------------------------------------
# After-hours escalation tiers (PRD 3.6)
# ---------------------------------------------------------------------------
ESCALATION_TIER_ACK_MINUTES = {1: 15, 2: 30, 3: 60}
ESCALATION_TIER_MAX = 3

# ---------------------------------------------------------------------------
# Conferences (PRD 3.7)
# ---------------------------------------------------------------------------
CONFERENCE = {
    "BUFFER_MINUTES": 15,
    "ATTESTATION_WINDOW_HOURS": 72,
    "IDT_CADENCE_MAX_DAYS": 15,
}
IDT_DISCIPLINES = ["PHYSICIAN", "NURSE", "SOCIAL_WORKER", "CHAPLAIN"]

# ---------------------------------------------------------------------------
# Analgesia (PRD 3.8)
# ---------------------------------------------------------------------------
MME_CONVERSION_FACTORS = {
    "MORPHINE_PO": 1.0,
    "OXYCODONE_PO": 1.5,
    "HYDROMORPHONE_PO": 5.0,
    "FENTANYL_TD": 2.4,
}
MEDICATION = {
    "OPIOID_NAIVE_SAFETY_FACTOR": 0.75,
    "MME_REVIEW_THRESHOLD": 90.0,
    "BREAKTHROUGH_FRACTION": 0.15,
    "EARLY_REFILL_WINDOW_DAYS": 2,
}

# ---------------------------------------------------------------------------
# Equipment (PRD 3.9)
# ---------------------------------------------------------------------------
DME_MAX_QUANTITY = 10
DME_MAX_TOTAL_UNITS = 500

# ---------------------------------------------------------------------------
# Hospice benefit periods (PRD 3.10)
# ---------------------------------------------------------------------------
HOSPICE = {
    "CERTIFICATIONS_REQUIRED": 2,
    "PERIOD_1_DAYS": 90,
    "PERIOD_2_DAYS": 90,
    "PERIOD_LATER_DAYS": 60,
    "FACE_TO_FACE_FROM_PERIOD": 3,
    "FACE_TO_FACE_WINDOW_DAYS": 30,
}

# ---------------------------------------------------------------------------
# Advance-care-planning billing (PRD 3.11)
# ---------------------------------------------------------------------------
CLAIM = {
    "FIRST_UNIT_MIN_MINUTES": 16,
    "ADDITIONAL_UNIT_MINUTES": 30,
    "MAX_UNITS": 4,
    "FIRST_UNIT_CENTS": 8600,
    "ADDITIONAL_UNIT_CENTS": 7500,
    "TELEHEALTH_RATE": 0.85,
    "IN_PERSON_RATE": 1.0,
    "TELEHEALTH_MODIFIER_CODE": "95",
    "ANNUAL_CAP_CENTS": 40000,
    "COINSURANCE_BOUNDARY_CENTS": 10000,
    "COINSURANCE_LOW": 0.1,
    "COINSURANCE_HIGH": 0.2,
    "MAX_DOCUMENTED_MINUTES": 240,
}

# ---------------------------------------------------------------------------
# Opaque operator identities (PRD 2.1)
#
# These are deliberately distinct from one another: several segregation-of-duty
# rules compare one recorded operator identifier against another, so sharing a
# single identifier across two parties would silently break those rules.
# ---------------------------------------------------------------------------
USER_IDS = {
    "INTAKE": "u_intake_1",
    "PHYSICIAN": "u_physician_1",
    "PHYSICIAN_2": "u_physician_2",
    "NURSE": "u_nurse_1",
    "SOCIAL_WORKER": "u_sw_1",
    "CHAPLAIN": "u_chaplain_1",
    "HOSPICE_DIRECTOR": "u_hospice_md_1",
    "ONCALL": "u_oncall_1",
    "BILLING": "u_billing_1",
    "ADMIN": "u_admin_1",
    # Attending clinician of record — never the same person as any witness or
    # surrogate, because a witness may not be the attending clinician.
    "ATTENDING": "u_attending_1",
    "ATTENDING_2": "u_attending_2",
    # Independent witnesses / notary: not the attending, not a surrogate, not a
    # beneficiary.
    "WITNESS_1": "u_witness_1",
    "WITNESS_2": "u_witness_2",
    "NOTARY": "u_notary_1",
    # People named on surrogate designations.
    "SPOUSE": "u_spouse_1",
    "AGENT": "u_agent_1",
    "ADULT_CHILD": "u_daughter_1",
    "SIBLING": "u_sibling_1",
    "PARENT": "u_parent_1",
    # A patient signing personally.
    "PATIENT_SIGNER": "u_patient_1",
}
