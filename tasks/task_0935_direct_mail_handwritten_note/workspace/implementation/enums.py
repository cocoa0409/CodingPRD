"""The closed enum sets of PRD 2.6 rung 7.

Every field listed here routes a non-member value to ERR_INVALID_ENUM.
No other field routes there; every other malformed value is ERR_VALIDATION
one rung earlier.  Query-string filters are deliberately excluded — a filter
value outside its set simply matches nothing and never errors.
"""
ACCOUNT_STATUS = ("ACTIVE", "SUSPENDED")
LIFECYCLE_STATUS = ("DRAFT", "ACTIVE", "PAUSED", "COMPLETED")
COMPLIANCE_STATUS = ("CLEAR", "HOLD")
BILLING_STATUS = ("OPEN", "CLOSED")
PEN_TYPES = ("GEL", "FOUNTAIN", "ROLLERBALL")
INK_TYPES = ("INK_BLUE_A", "INK_BLACK_B", "INK_NAVY_C")
ENVELOPE_STYLES = ("STANDARD", "WINDOW", "HAND_ADDRESSED")
DPV_CODES = ("Y", "D", "S", "N", "U")
JOB_KINDS = ("ADDRESSED", "EDDM")
MAIL_CLASSES = ("FIRST_CLASS", "MARKETING_MAIL", "EDDM")
EDDM_RATE_VARIANTS = ("SATURATION", "HIGH_DENSITY_PLUS")
DEDUPE_MODES = ("EXACT", "HOUSEHOLD")
CAPACITY_VARIANTS = ("SINGLE_PASS", "SPLIT_RUN")
ANCHOR_VARIANTS = ("ANCHOR_IN_HOME", "ANCHOR_MAIL_DATE")
MACHINE_STATUS = ("ONLINE", "OFFLINE")
RETURN_REASONS = ("MOVED_NO_FORWARD", "VACANT", "REFUSED", "INSUFFICIENT_ADDRESS")
