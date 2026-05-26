"""Domain thresholds and constants from the PRD (§2.9, §2.10, §3.5, §3.6, §3.7)."""

# ─── NIL deal tier cutoffs (PRD §3.5) ───────────────────
DE_MINIMIS_CUTOFF_CENTS = 60_000      # net < 60,000 cents → DE_MINIMIS
STANDARD_CUTOFF_CENTS = 500_000       # net < 500,000 cents → STANDARD; otherwise HIGH_VALUE

# ─── Booster incident severity tiers (PRD §3.7) ─────────
SEVERITY_TIER_1_CUTOFF_CENTS = 50_000          # alleged < 50,000 → weight 1
SEVERITY_TIER_2_CUTOFF_CENTS = 500_000         # alleged < 500,000 → weight 3
SEVERITY_TIER_3_CUTOFF_CENTS = 2_500_000       # alleged < 2,500,000 → weight 7; otherwise 15
SEVERITY_WEIGHTS = (1, 3, 7, 15)

# ─── Program penalty tier thresholds (PRD §3.7) ─────────
PENALTY_TIER_LEVEL_II_FLOOR = 5     # total >= 5 → LEVEL_II
PENALTY_TIER_BAN_FLOOR = 15         # total >= 15 → POSTSEASON_BAN

# ─── Scholarship slot cap range (PRD §3.1, §2.9) ────────
SLOT_CAP_MIN = 1
SLOT_CAP_MAX = 130

# ─── Athlete GPA / eligibility (PRD §3.2) ───────────────
GPA_MIN = 0.000
GPA_MAX = 4.000
GPA_NCAA_FLOOR = 2.300   # certification approval requires gpa_at_review >= 2.300

# ─── Transfer portal window (PRD §3.6) ──────────────────
PORTAL_WINDOW_DAYS = 45

# ─── NIL deal revision cap (PRD §3.5) ───────────────────
NIL_REVISION_ROUND_CAP = 3

# ─── Pagination (PRD §2.3) ──────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
