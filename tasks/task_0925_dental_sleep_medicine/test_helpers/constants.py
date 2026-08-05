"""Domain thresholds and fee constants stated in the PRD."""

# --- Sleep study quality gates and severity bands (PRD 3.2) ---
THRESHOLDS = {
    "MIN_HSAT_RECORDING_MINUTES": 240,
    "MAX_HSAT_ARTIFACT_PCT": 20,
    "MIN_PSG_TST_MINUTES": 180,
    "AHI_MILD_MIN": 5.0,
    "AHI_MODERATE_MIN": 15.0,
    "AHI_SEVERE_MIN": 30.0,
    # --- Diagnosis currency (PRD 3.3) ---
    "HSAT_VALIDITY_DAYS": 365,
    "PSG_VALIDITY_DAYS": 1095,
    # --- Medical necessity fork (PRD 3.3) ---
    "MIN_CPAP_TRIAL_NIGHTS": 30,
    "CPAP_LOOKBACK_DAYS": 730,
    "MIN_SYMPTOM_SCORE": 10,
    # --- Device geometry (PRD 3.5 / 3.6) ---
    "START_ADVANCEMENT_PCT": 0.60,
    "PREFAB_START_MM": 4.00,
    "PREFAB_START_PCT": 0.50,
    "MM_INCREMENT": 0.25,
    "MAX_INCREMENT_PER_VISIT_MM": 1.00,
    "SEVERE_SIDE_EFFECT_REDUCTION_MM": 0.50,
    "MIN_TITRATION_INTERVAL_DAYS": 14,
    "PLATEAU_MIN_VISITS": 3,
    # --- Adherence (PRD 3.7) ---
    "ADHERENCE_WINDOW_DAYS": 30,
    "ADHERENCE_MIN_HOURS": 4.0,
    "ADHERENCE_MIN_NIGHTS_PCT": 0.70,
    # --- Efficacy (PRD 3.7) ---
    "PARTIAL_AHI_CEILING": 10.0,
    "EFFICACY_REPORT_DUE_DAYS": 30,
    # --- Recall cadence (PRD 3.7) ---
    "FIRST_RECALL_DAYS": 90,
    "SUBSEQUENT_RECALL_DAYS": 365,
    "RECALL_GRACE_DAYS": 30,
    # --- Documentation and money (PRD 3.4 / 3.8 / 3.9) ---
    "F2F_LOOKBACK_DAYS": 180,
    "PA_VALIDITY_DAYS": 90,
    "WARRANTY_MONTHS": 36,
    "FEE_SCHEDULE_E0486_CENTS": 185000,
    "FEE_SCHEDULE_A9270_CENTS": 0,
    "LABOR_RATE_CENTS_PER_15MIN": 2500,
    "REPAIR_CAP_PCT": 0.50,
    "REPAIR_CAP_CENTS": 92500,
}

# --- Payer policy defaults (PRD 3.1) ---
PAYER_DEFAULTS = {
    "prior_auth_required": True,
    "useful_lifetime_months": 60,
    "coinsurance_pct": 0.20,
    "appeal_limit": 2,
    "residual_ahi_target": 5.0,
    "pct_reduction_target": 0.50,
}

# --- Pagination contract (PRD 2.3) ---
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# --- The logical clock's pre-set reading (PRD 2.4) ---
CLOCK_EPOCH = "2026-05-01T00:00:00Z"

# --- Dates the canonical clinical timeline runs on ---
TIMELINE = {
    "intake": "2026-05-01T00:00:00Z",
    "study_performed_on": "2026-04-10",
    "cpap_documented_on": "2026-03-01",
    "order_date": "2026-05-10",
    "f2f_encounter_date": "2026-04-20",
    "signed_on": "2026-05-11",
    "shipped_on": "2026-05-15",
    "delivery": "2026-06-01T00:00:00Z",
    "delivered_on": "2026-06-01",
    "visit_1": "2026-06-01",
    "visit_2": "2026-06-15",
    "visit_3": "2026-06-29",
    "efficacy_performed_on": "2026-07-05",
    "efficacy_draft": "2026-07-06T00:00:00Z",
    "physician_response": "2026-07-07T00:00:00Z",
}

TEST_DEFAULTS = {
    "max_protrusive_mm": 8.00,
    "promised_turnaround_days": 14,
    "billed_cents_device": 250000,
    "epworth_score": 14,
}
