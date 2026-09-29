"""Domain constants: clock instants, scoring weights, thresholds, payload values.

Every numeric value here is stated by the PRD; nothing is invented.
"""

# ----------------------------------------------------------------------
# Logical season clock (PRD §2.7)
# ----------------------------------------------------------------------
#: The instant the server's logical clock holds at process startup.
CLOCK_PROCESS_START = "2026-08-01T00:00:00Z"
#: Canonical season opening used by the test fixtures.
CLOCK_SEASON_START = "2026-09-01T00:00:00Z"
#: The instant invitation waves are released in the canonical walk.
CLOCK_WAVE_RELEASE = "2026-10-01T12:00:00Z"
#: A moment after the canonical interview slot has ended.
CLOCK_AFTER_INTERVIEW = "2026-10-05T16:30:00Z"
#: The instant the canonical walk closes the wave, ranks and certifies.
CLOCK_RANKING_DAY = "2026-10-20T09:00:00Z"
#: Exactly four hours after CLOCK_RANKING_DAY — a SOAP offer expiry instant.
CLOCK_SOAP_EXPIRY = "2026-10-20T13:00:00Z"
#: The last instant at which a rank list may be certified (PRD §2.7, inclusive).
RANK_LIST_CERTIFICATION_DEADLINE = "2027-02-25T21:00:00Z"
#: One instant family strictly after the certification deadline.
CLOCK_AFTER_CERTIFICATION_DEADLINE = "2027-02-26T00:00:00Z"

# ----------------------------------------------------------------------
# Screening composite (PRD §3.2)
# ----------------------------------------------------------------------
ACADEMIC_WEIGHT = 0.45
EXPERIENCE_WEIGHT = 0.30
HOLISTIC_WEIGHT = 0.25
#: Upper bound the final screening composite is clamped to.
SCORE_CEILING = 40.0
#: Reviews an application must hold before it may be screened.
MIN_REVIEWS_TO_SCREEN = 2
#: Bonus added when the applicant is a pipeline program alum.
PIPELINE_ALUM_BONUS = 3.0
#: Step 2 score band thresholds mapped to their bonus.
STEP2_BANDS = ((250, 6.0), (235, 4.0), (220, 2.0))

# ----------------------------------------------------------------------
# Interviewer load (PRD §3.4)
# ----------------------------------------------------------------------
LEAD_LOAD_FACTOR = 1.5
MEMBER_LOAD_FACTOR = 1.0

# ----------------------------------------------------------------------
# Committee deliberation (PRD §3.6)
# ----------------------------------------------------------------------
#: Fraction of the committee electorate that must approve, ceiling-rounded.
COMMITTEE_QUORUM_PCT = 0.60

# ----------------------------------------------------------------------
# Windows and expiry durations (PRD §3.3, §3.5, §3.8)
# ----------------------------------------------------------------------
#: Hours of separation two invitation wave windows must keep, both directions.
WAVE_BUFFER_HOURS = 48
#: Hours an issued invitation stays answerable.
INVITATION_TTL_HOURS = 120
#: Hours a SOAP offer stays answerable.
SOAP_OFFER_TTL_HOURS = 4

# ----------------------------------------------------------------------
# Pagination (PRD §2.3)
# ----------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ----------------------------------------------------------------------
# Canonical program payload values
# ----------------------------------------------------------------------
PROGRAM_NAME = "Metro Internal Medicine"
PROGRAM_CODE = "1140140M0"
PROGRAM_SPECIALTY = "IM"
PATHOLOGY_PROGRAM_NAME = "County Pathology"
PATHOLOGY_PROGRAM_CODE = "1140300P0"
PATHOLOGY_SPECIALTY = "PATH"

# ----------------------------------------------------------------------
# Canonical faculty payload values
# ----------------------------------------------------------------------
DIRECTOR_NAME = "Iris Kwon"
SECOND_DIRECTOR_NAME = "Hal Ndiaye"
LEAD_INTERVIEWER_NAME = "Alan Reyes"
MEMBER_INTERVIEWER_NAME = "Bea Osei"

# ----------------------------------------------------------------------
# Canonical interview window values
# ----------------------------------------------------------------------
WAVE_INVITE_RELEASE_AT = "2026-10-01T12:00:00Z"
WAVE_RESPONSE_DEADLINE_AT = "2026-10-08T12:00:00Z"
SLOT_START_AT = "2026-10-05T13:00:00Z"
SLOT_END_AT = "2026-10-05T16:00:00Z"
SLOT_ROOM_LABEL = "A-1"

# ----------------------------------------------------------------------
# Prohibited pre-match phrases scanned for by PRD §3.9
# ----------------------------------------------------------------------
PROHIBITED_RANKING_PHRASES = (
    "how will you rank",
    "rank us",
    "commit to us",
    "where will we be on your list",
    "ranking intent",
)

# ----------------------------------------------------------------------
# Misc canonical payload values
# ----------------------------------------------------------------------
DEFAULT_SALARY_CENTS = 6500000
UNREPORTED_GROUP_LABEL = "UNREPORTED"
