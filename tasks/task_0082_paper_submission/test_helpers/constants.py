"""Domain thresholds and constants from the PRD.

Numeric values used in PRD calculations and timing rules, plus test
defaults that exercise them. PRD section refs are inline.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Plagiarism threshold (PRD §3.3)
# "when similarity_percent is at least 25.0, the result is FAIL; when it
#  is strictly less than 25.0, the result is PASS."
# ---------------------------------------------------------------------------
PLAGIARISM_THRESHOLD = 25.0

# ---------------------------------------------------------------------------
# Reviewer-Invitation timing (PRD §3.5)
# "response_deadline_at to seven days after the server clock"
# "review_deadline_at set to twenty-one days after the server clock"
# ---------------------------------------------------------------------------
INVITATION_RESPONSE_DAYS = 7
REVIEW_DEADLINE_DAYS = 21

# ---------------------------------------------------------------------------
# Conflict-of-interest weights and cap (PRD §3.5)
# coauthor signal contributes 60; institution signal contributes 30;
# excluded signal contributes 100; coi_score = min(raw, 100); rejection at >= 50.
# ---------------------------------------------------------------------------
W_COAUTHOR = 60
W_INSTITUTION = 30
W_EXCLUDED = 100
COI_CAP = 100
COI_REJECT_THRESHOLD = 50

# ---------------------------------------------------------------------------
# Reviewer-match weights and clamp range (PRD §3.5)
# match_score raw = 60*tag_match + 30*suggested - 10*load; clamp to [0, 100].
# ---------------------------------------------------------------------------
W_TAG = 60
W_SUGGESTED = 30
W_LOAD = 10
MATCH_SCORE_MIN = 0
MATCH_SCORE_MAX = 100

# ---------------------------------------------------------------------------
# Reviewer capacity (PRD §3.5)
# "accepting one more invitation must leave that count at most three"
# ---------------------------------------------------------------------------
REVIEWER_MAX_CONCURRENT = 3

# ---------------------------------------------------------------------------
# Editor assignment window (PRD §3.4)
# "the five-day interval starting at associate_assigned_at and ending at
#  associate_window_end_at"
# ---------------------------------------------------------------------------
EDITOR_ASSIGNMENT_WINDOW_DAYS = 5

# ---------------------------------------------------------------------------
# Revision deadlines (PRD §3.8)
# "thirty days for MINOR_REVISION and sixty days for MAJOR_REVISION"
# ---------------------------------------------------------------------------
MINOR_REVISION_DAYS = 30
MAJOR_REVISION_DAYS = 60

# ---------------------------------------------------------------------------
# Editor decision aggregation weights (PRD §3.7)
# "1.215 for ACCEPT, 1.005 for MINOR_REVISION, 0.835 for MAJOR_REVISION,
#  and 0.605 for REJECT"
# ---------------------------------------------------------------------------
WEIGHT_ACCEPT = 1.215
WEIGHT_MINOR_REVISION = 1.005
WEIGHT_MAJOR_REVISION = 0.835
WEIGHT_REJECT = 0.605

# ---------------------------------------------------------------------------
# Editor decision insufficient-reviews threshold (PRD §3.7)
# "at least two reviews are in SUBMITTED at the current revision_round"
# ---------------------------------------------------------------------------
MIN_SUBMITTED_REVIEWS_FOR_RECOMMEND = 2

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3_600

# ---------------------------------------------------------------------------
# Indexing targets enumeration (PRD §3.9 — "from the set {PUBMED, WEB_OF_SCIENCE, SCOPUS}")
# ---------------------------------------------------------------------------
INDEXING_TARGET_VALUES = ("PUBMED", "WEB_OF_SCIENCE", "SCOPUS")

# ---------------------------------------------------------------------------
# Common test defaults — used by factories so individual tests can vary
# only the value(s) they care about.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "TOPIC_TAG": "ml",
    "OTHER_TOPIC_TAG": "robotics",
    "REVIEW_MODE": "SINGLE_BLIND",
    "MANUSCRIPT_TITLE": "A Study of Useful Things",
    "MANUSCRIPT_FILE_URI": "https://files.example.com/manuscript.pdf",
    "COPY_EDIT_URI": "https://files.example.com/copy-edit.pdf",
    "PROOF_URI": "https://files.example.com/proof.pdf",
    "REPORT_URI": "https://reports.example.com/plagiarism.pdf",
    "REVISED_FILE_URI": "https://files.example.com/revised.pdf",
    "DECLARATION_COI": "No conflicts of interest declared.",
    "DECLARATION_FUNDING": "Funded by Example Foundation.",
    "DECLARATION_ETHICS": "Approved by Example Ethics Board #12345.",
    "DECISION_LETTER_BODY": "We have considered your manuscript carefully...",
    "RESPONSE_LETTER": "Thank you for your thoughtful comments...",
    "AUTHOR_INSTITUTION": "Example University",
    "OTHER_INSTITUTION": "Other University",
    "REVIEWER_INSTITUTION": "Reviewer Institute",
    "EDITOR_INSTITUTION": "Editor College",
    "DEFAULT_DOI": "10.1234/example.001",
    "DEFAULT_ISSUE_LABEL": "Vol 1, Issue 1",
    "VALID_ORCID": "0000-0001-2345-6789",
    "ALTERNATE_ORCID": "0000-0002-3456-789X",
}


__all__ = [
    "PLAGIARISM_THRESHOLD",
    "INVITATION_RESPONSE_DAYS",
    "REVIEW_DEADLINE_DAYS",
    "W_COAUTHOR",
    "W_INSTITUTION",
    "W_EXCLUDED",
    "COI_CAP",
    "COI_REJECT_THRESHOLD",
    "W_TAG",
    "W_SUGGESTED",
    "W_LOAD",
    "MATCH_SCORE_MIN",
    "MATCH_SCORE_MAX",
    "REVIEWER_MAX_CONCURRENT",
    "EDITOR_ASSIGNMENT_WINDOW_DAYS",
    "MINOR_REVISION_DAYS",
    "MAJOR_REVISION_DAYS",
    "WEIGHT_ACCEPT",
    "WEIGHT_MINOR_REVISION",
    "WEIGHT_MAJOR_REVISION",
    "WEIGHT_REJECT",
    "MIN_SUBMITTED_REVIEWS_FOR_RECOMMEND",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "INDEXING_TARGET_VALUES",
    "TEST_DEFAULTS",
]
