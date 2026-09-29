"""Numeric constants, timestamps and endpoint paths published by the PRD.

Nothing here is inferred. Every number is a literal the contract names, and
every path string is a row of the contract's endpoint table.
"""


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

# The service boots with its logical clock parked at exactly this instant.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

CLOCK_SET_PATH = "/_clock/set_current_utc"


# --------------------------------------------------------------------------
# Standard campaign envelope used across the suite
# --------------------------------------------------------------------------

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-12-31T00:00:00Z"


# --------------------------------------------------------------------------
# Pagination (PRD "Listing and pagination")
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


# --------------------------------------------------------------------------
# Identifier used for "this row does not exist" probes
# --------------------------------------------------------------------------

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


# --------------------------------------------------------------------------
# Supporter engagement scoring
# --------------------------------------------------------------------------

ACQUISITION_BONUS = {
    "PETITION": 1.0,
    "EVENT": 2.0,
    "DIGITAL_AD": 0.5,
    "REFERRAL": 1.5,
}

CHANNEL_PRESSURE_WEIGHT = {
    "EMAIL": 1.0,
    "SMS": 1.5,
    "PHONE": 3.0,
}

# Recency decay applied to each logged action, keyed by whole elapsed days.
DECAY_RECENT = 1.00       # elapsed days <= 7
DECAY_MID = 0.75          # elapsed days > 7 and <= 30
DECAY_OLD = 0.50          # elapsed days > 30

SECONDS_PER_DAY = 86400

ENGAGEMENT_SCORE_CEILING = 50.0
RETENTION_SCORE_CEILING = 80.0

# Spokesperson story bonus folded into the engagement score.
STORY_BONUS = {
    None: 0.0,
    "UNTRAINED": 0.0,
    "TRAINED": 1.0,
    "CERTIFIED": 3.0,
}

RETENTION_PER_THANKED_ACTION = 2.0
RETENTION_PER_HELD_MEETING_LED = 5.0

# A supporter counts as retained once retention_score reaches this floor.
RETAINED_SUPPORTER_THRESHOLD = 10.00


# --------------------------------------------------------------------------
# Milestone pressure multipliers
# --------------------------------------------------------------------------

MILESTONE_MULTIPLIER = {
    "COMMITTEE_HEARING": 1.5,
    "FLOOR_VOTE": 2.0,
    "RECESS": 0.5,
    "SIGNING": 1.0,
}

# An action logged outside every milestone window carries the neutral weight.
MILESTONE_MULTIPLIER_DEFAULT = 1.0

# Only a RECESS milestone marks a blackout period.
BLACKOUT_MILESTONE_KIND = "RECESS"


# --------------------------------------------------------------------------
# District pressure index
# --------------------------------------------------------------------------

PRESSURE_CONTACT_FACTOR = 2.0
PRESSURE_CONTACT_CAP = 60.0

PRESSURE_PER_HELD_MEETING = 12.0
PRESSURE_MEETING_CAP = 24.0

STANCE_BONUS = {
    "SUPPORT": 0.0,
    "LEAN_SUPPORT": 10.0,
    "UNDECIDED": 10.0,
    "LEAN_OPPOSE": 4.0,
    "OPPOSE": 0.0,
}

PRESSURE_INDEX_CAP = 100.0

TIER_PRIMARY_THRESHOLD = 60.00
TIER_SECONDARY_THRESHOLD = 30.00

# Credit a single held meeting contributes to its legislator.
MEETING_PRESSURE_CREDIT = 12.00


# --------------------------------------------------------------------------
# Coalition funding
# --------------------------------------------------------------------------

PARTNER_SHARE_WEIGHT = {
    "ANCHOR": 5,
    "CORE": 3,
    "ALLY": 1,
}

ENDORSEMENT_QUORUM_FRACTION = 0.5
ENDORSEMENT_QUORUM_FLOOR = 1


# --------------------------------------------------------------------------
# Message variant review
# --------------------------------------------------------------------------

REVISION_LIMIT = 3


# --------------------------------------------------------------------------
# Touch budget
# --------------------------------------------------------------------------

BASE_TOUCH_ALLOWANCE = 3
SURGE_TOUCH_CAP = 5
SURGE_GRANT_OPEN = 2
SURGE_GRANT_RESTRICTED = 1


# --------------------------------------------------------------------------
# Sending economics
# --------------------------------------------------------------------------

UNIT_SEND_COST_CENTS = {
    "EMAIL": 2,
    "SMS": 15,
    "PHONE": 60,
}

# Stand-in reported for cost per action when nothing has been attributed yet.
COST_PER_ACTION_SENTINEL = 999999

MIN_TEST_REACH = 3

BPS_SCALE = 10000


# --------------------------------------------------------------------------
# Wave saturation and meeting geometry
# --------------------------------------------------------------------------

MAX_OVERLAPPING_WAVES_PER_CHANNEL = 2

MEETING_TRAVEL_BUFFER_MINUTES = 30


# --------------------------------------------------------------------------
# Posture derivation thresholds
# --------------------------------------------------------------------------

FROZEN_BLOCKED_ACTIVATION_THRESHOLD = 2
RESTRICTED_BLOCKED_ACTIVATION_THRESHOLD = 1
RESTRICTED_OPPOSED_PRIORITY_THRESHOLD = 1

# Postures that narrow sending: SMS and PHONE are refused, EMAIL proceeds.
RESTRICTED_BLOCKED_CHANNELS = ["SMS", "PHONE"]


# --------------------------------------------------------------------------
# Endpoint paths
# --------------------------------------------------------------------------

CAMPAIGNS = "/advocacy/campaigns"
MILESTONES = "/advocacy/milestones"
LEGISLATORS = "/advocacy/legislators"
SUPPORTERS = "/advocacy/supporters"
CONSENT_EVENTS = "/advocacy/consent-events"
SEGMENTS = "/advocacy/segments"
MESSAGE_VARIANTS = "/advocacy/message-variants"
COALITION_PARTNERS = "/advocacy/coalition-partners"
PARTNER_ENDORSEMENTS = "/advocacy/partner-endorsements"
ACTIVATIONS = "/advocacy/activations"
ACTION_RECORDS = "/advocacy/action-records"
SPOKESPERSONS = "/advocacy/spokespersons"
DISTRICT_MEETINGS = "/advocacy/district-meetings"


def campaign_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}"


def campaign_launch_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/launch"


def campaign_close_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/close"


def campaign_posture_overrides_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/posture-overrides"


def campaign_message_test_resolutions_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/message-test-resolutions"


def campaign_outcome_report_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/outcome-report"


def campaign_milestones_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/milestones"


def campaign_partners_path(campaign_id: str) -> str:
    return f"{CAMPAIGNS}/{campaign_id}/coalition-partners"


def milestone_path(milestone_id: str) -> str:
    return f"{MILESTONES}/{milestone_id}"


def milestone_reschedule_path(milestone_id: str) -> str:
    return f"{MILESTONES}/{milestone_id}/reschedule"


def legislator_path(legislator_id: str) -> str:
    return f"{LEGISLATORS}/{legislator_id}"


def legislator_stance_updates_path(legislator_id: str) -> str:
    return f"{LEGISLATORS}/{legislator_id}/stance-updates"


def supporter_path(supporter_id: str) -> str:
    return f"{SUPPORTERS}/{supporter_id}"


def supporter_consent_events_path(supporter_id: str) -> str:
    return f"{SUPPORTERS}/{supporter_id}/consent-events"


def supporter_spokesperson_profiles_path(supporter_id: str) -> str:
    return f"{SUPPORTERS}/{supporter_id}/spokesperson-profiles"


def consent_event_path(consent_event_id: str) -> str:
    return f"{CONSENT_EVENTS}/{consent_event_id}"


def segment_path(segment_id: str) -> str:
    return f"{SEGMENTS}/{segment_id}"


def segment_refresh_path(segment_id: str) -> str:
    return f"{SEGMENTS}/{segment_id}/refresh"


def variant_path(variant_id: str) -> str:
    return f"{MESSAGE_VARIANTS}/{variant_id}"


def variant_submit_path(variant_id: str) -> str:
    return f"{MESSAGE_VARIANTS}/{variant_id}/submit"


def variant_review_decisions_path(variant_id: str) -> str:
    return f"{MESSAGE_VARIANTS}/{variant_id}/review-decisions"


def variant_lock_path(variant_id: str) -> str:
    return f"{MESSAGE_VARIANTS}/{variant_id}/lock"


def variant_reopen_path(variant_id: str) -> str:
    return f"{MESSAGE_VARIANTS}/{variant_id}/reopen"


def partner_path(partner_id: str) -> str:
    return f"{COALITION_PARTNERS}/{partner_id}"


def partner_withdraw_path(partner_id: str) -> str:
    return f"{COALITION_PARTNERS}/{partner_id}/withdraw"


def endorsement_path(endorsement_id: str) -> str:
    return f"{PARTNER_ENDORSEMENTS}/{endorsement_id}"


def endorsement_revoke_path(endorsement_id: str) -> str:
    return f"{PARTNER_ENDORSEMENTS}/{endorsement_id}/revoke"


def activation_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}"


def activation_clear_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}/clear"


def activation_block_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}/block"


def activation_start_send_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}/start-send"


def activation_complete_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}/complete"


def activation_abort_path(activation_id: str) -> str:
    return f"{ACTIVATIONS}/{activation_id}/abort"


def action_record_path(action_record_id: str) -> str:
    return f"{ACTION_RECORDS}/{action_record_id}"


def action_acknowledge_path(action_record_id: str) -> str:
    return f"{ACTION_RECORDS}/{action_record_id}/acknowledge"


def action_thank_path(action_record_id: str) -> str:
    return f"{ACTION_RECORDS}/{action_record_id}/thank"


def action_dispute_path(action_record_id: str) -> str:
    return f"{ACTION_RECORDS}/{action_record_id}/dispute"


def action_dispute_resolutions_path(action_record_id: str) -> str:
    return f"{ACTION_RECORDS}/{action_record_id}/dispute-resolutions"


def spokesperson_path(spokesperson_id: str) -> str:
    return f"{SPOKESPERSONS}/{spokesperson_id}"


def spokesperson_training_advancements_path(spokesperson_id: str) -> str:
    return f"{SPOKESPERSONS}/{spokesperson_id}/training-advancements"


def meeting_path(meeting_id: str) -> str:
    return f"{DISTRICT_MEETINGS}/{meeting_id}"


def meeting_response_path(meeting_id: str) -> str:
    return f"{DISTRICT_MEETINGS}/{meeting_id}/response"


def meeting_complete_path(meeting_id: str) -> str:
    return f"{DISTRICT_MEETINGS}/{meeting_id}/complete"
