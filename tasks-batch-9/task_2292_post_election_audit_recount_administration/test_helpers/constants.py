"""Numeric constants and thresholds the PRD's calculations depend on."""

# --- audit sample sizing ---------------------------------------------------
ALPHA_FACTORS = {0.10: 2.303, 0.05: 2.996, 0.01: 4.605}
GAMMA = 1.2
MIN_SAMPLE_BATCHES = 2
ESCALATION_MULTIPLIER = 2.0

# --- deterministic batch selection ----------------------------------------
LCG_MULTIPLIER = 1103515245
LCG_INCREMENT = 12345
LCG_MODULUS = 2147483648
ROUND_STRIDE = 7919

# --- discrepancy measures --------------------------------------------------
NET_SHIFT_ESCALATION_THRESHOLD = 0.0050
MACRO_ESCALATION_THRESHOLD = 1.0000

# --- recount deposit assessment -------------------------------------------
FILING_FEE_CENTS = 50000
RATE_FULL_CENTS_PER_BALLOT = 25
RATE_PARTIAL_CENTS_PER_BALLOT = 40
DEPOSIT_FLOOR_CENTS = 100000
DEPOSIT_CAP_CENTS = 2000000

# --- recount cost and refund ----------------------------------------------
RECOUNT_RATE_CENTS_PER_BALLOT = 12.5
LABOR_RATE_CENTS_PER_HOUR = 4800
MATERIAL_MARGIN_CHANGE_VOTES = 100
WITHDRAWAL_RETENTION_PCT = 0.25

# --- certification timeline projection ------------------------------------
PER_ROUND_HOURS = 48
FULL_HAND_COUNT_HOURS_PER_1000 = 6
AT_RISK_HOURS = 72
EXTENSION_MAX_DAYS = 5
LEGAL_CONTEST_WINDOW_DAYS = 10

# --- board adjudication and tally governance ------------------------------
QUORUM_MIN_VOTES = 3
MAX_TALLY_REOPENS = 2
MAX_TEAM_MEMBERS = 6
RESEAL_BUFFER_MINUTES = 30
OBSERVER_ROOM_CAPACITY = 2

# --- recount eligibility ---------------------------------------------------
REQUEST_WINDOW_DAYS = 5
REQUEST_ELIGIBLE_MARGIN_PCT = 10.0000
AUTO_RECOUNT_THRESHOLD_CANDIDATE_PCT = 0.5000
AUTO_RECOUNT_THRESHOLD_MEASURE_PCT = 0.2500

# --- pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --- logical clock ---------------------------------------------------------
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"


# --- reusable scenario values ---------------------------------------------
TEST_DEFAULTS = {
    # Election E1 / contest C1: the six-batch risk-limiting scenario.
    "E1_JURISDICTION_CODE": "ST-01",
    "E1_ELECTION_NAME": "2026 General Election",
    "E1_ELECTION_DATE": "2026-11-03",
    "E1_CERTIFICATION_DEADLINE_AT": "2026-11-24T17:00:00Z",
    "CLOCK_CANVASS_DAY": "2026-11-05T09:00:00Z",
    "C1_LABEL": "C1",
    "C1_OFFICE_NAME": "State Auditor",
    "C1_CANDIDATES": ["ALVAREZ", "BRENNAN"],
    "C1_BALLOTS_CAST": 6000,
    "C1_REPORTED_VOTES": {"ALVAREZ": 3150, "BRENNAN": 2850},
    "C1_BATCH_BALLOT_COUNT": 1000,
    "C1_BATCH_MACHINE_VOTES": {"ALVAREZ": 525, "BRENNAN": 475},
    "C1_STORAGE_LOCATION_CODE": "VAULT-1",
    "AUDIT_SEED": "0459231087",
    "RISK_LIMIT_ALPHA": 0.05,
    "PRIOR_ERROR_RATE": 0.10,
    # Election E2 / contests C2 and C3: the recount money scenario.
    "E2_JURISDICTION_CODE": "ST-02",
    "C2_LABEL": "C2",
    "C2_OFFICE_NAME": "State Treasurer",
    "C2_CANDIDATES": ["CHEN", "DAVIS"],
    "C2_BALLOTS_CAST": 3000,
    "C2_REPORTED_VOTES": {"CHEN": 1575, "DAVIS": 1425},
    "C3_LABEL": "C3",
    "C3_OFFICE_NAME": "County Assessor",
    "C3_CANDIDATES": ["FORD", "GRANT"],
    "C3_BALLOTS_CAST": 2250,
    "C3_REPORTED_VOTES": {"FORD": 1180, "GRANT": 1070},
    # tally team roster
    "TEAM_DEM_USER_ID": "u-dem-1",
    "TEAM_REP_USER_ID": "u-rep-1",
    "BOARD_DEM_USER_ID": "u-board-1",
    "BOARD_REP_USER_ID": "u-board-2",
    "BOARD_DEM_2_USER_ID": "u-board-3",
}
