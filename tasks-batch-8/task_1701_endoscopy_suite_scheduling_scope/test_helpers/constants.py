"""Domain thresholds and shared values — numeric constants from the PRD."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Booking window arithmetic (PRD §3.2)
    "AGE_THRESHOLD_YEARS": 65,
    "AGE_ADDON_MIN": 5,
    "ANESTHESIA_ADDON_NONE": 0,
    "ANESTHESIA_ADDON_MAC": 10,
    "ANESTHESIA_ADDON_GENERAL": 15,
    "TURNOVER_STANDARD_MIN": 15,
    "TURNOVER_ERCP_CAPABLE_MIN": 25,
    "ROOM_DAY_CAPACITY_MINUTES": 480,
    # Bowel-prep adequacy (PRD §3.5)
    "BBPS_TOTAL_MIN": 6,
    "BBPS_SEGMENT_MIN": 2,
    "BBPS_SEGMENT_MAX": 3,
    # Reprocessing step windows (PRD §3.6)
    "PRECLEAN_DEADLINE_MIN": 60,
    "MANUAL_CLEAN_MIN": 5,
    "EXTENDED_MANUAL_CLEAN_MIN": 20,
    "HLD_MIN_CONTACT_SECONDS": 600,
    "HLD_MIN_CONCENTRATION_PPM": 300,
    "DRY_MIN_MINUTES": 10,
    # Storage hang time (PRD §3.6)
    "HANG_TIME_HOURS": 72,
    # Quality metrics (PRD §3.9)
    "ADR_MIN_AGE": 45,
    "ROOM_OPEN_MINUTES_PER_DAY": 480,
    # Day-of-procedure windows (PRD §3.4)
    "CHECKIN_EARLY_MIN": 60,
    "CHECKIN_LATE_MIN": 30,
    "NO_SHOW_GRACE_MIN": 30,
    # Specimen custody windows (PRD §3.8)
    "LABEL_WINDOW_MIN": 15,
    "TRANSPORT_WINDOW_MIN": 120,
}

TEST_DEFAULTS = {
    "PATIENT_DOB_YOUNG": "1990-05-05",   # 36 at the 2026-08 procedures
    "PATIENT_DOB_MID": "1976-03-10",     # 50 at the 2026-08 procedures
    "PATIENT_DOB_SENIOR": "1966-05-20",  # 60 at the 2026-08 procedures
    "COLONO_BASE_MINUTES": 40,
    "EGD_BASE_MINUTES": 25,
    "HLD_LOT": "LOT-1",
    "HLD_PPM_OK": 350,
    "TECHNICIAN_ID": "tech-1",
    "NURSE_ID": "nurse-1",
}
