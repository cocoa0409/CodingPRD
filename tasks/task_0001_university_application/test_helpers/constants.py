"""Domain thresholds and constants derived from PRD §3."""

# PRD §3.2: capacity boundary is inclusive at 5; sixth IN_PROGRESS rejected.
RECOMMENDER_INPROGRESS_CAP = 5

# PRD §3.5: essay word_count must be in [1..650] inclusive.
ESSAY_WORD_COUNT_MIN = 1
ESSAY_WORD_COUNT_MAX = 650

# PRD §3.2: letter body length minimum.
LETTER_BODY_MIN_CHARS = 200

# PRD §3.5: admission probability score caps.
SCORE_MAX = 100
GPA_COMPONENT_CAP = 40
SAT_COMPONENT_CAP = 30
LETTERS_FACTOR_CAP = 15
PLAN_BONUS_ED = 15
PLAN_BONUS_EA = 8
PLAN_BONUS_ROLLING = 5
PLAN_BONUS_REGULAR = 0

# PRD §3.3 / §3.7: default cooldown is 24h = 86,400,000 ms.
DEFAULT_COOLDOWN_MS = 86_400_000

# PRD §2.3: pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1
