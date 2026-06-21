"""Barrel export: framework generics + Greek-recruitment-specific test helpers."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# Domain types
from .types import (  # noqa: F401
    ChapterRiskStatus,
    GreekType,
    PNMStatus,
    RoundPhase,
    PartyStatus,
    RsvpStatus,
    PreferenceSide,
    BidMatchStatus,
    PriorityKind,
    DuesEntryKind,
    RiskIncidentStatus,
    UserRole,
    Chapter,
    PNM,
    RecruitmentRound,
    Party,
    PartyInvitation,
    Preference,
    BidMatch,
    DuesLedgerEntry,
    RiskIncident,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_common_fields_full,
    assert_common_fields_append_only,
    assert_chapter,
    assert_pnm,
    assert_round,
    assert_party,
    assert_party_invitation,
    assert_preference,
    assert_bid_match,
    assert_dues_ledger_entry,
    assert_risk_incident,
)

# Payload factories
from .factories import (
    create_chapter_payload,
    update_chapter_payload,
    register_pnm_payload,
    create_round_payload,
    create_party_payload,
    create_invitation_payload,
    create_preference_payload,
    create_bid_match_payload,
    rescind_bid_match_payload,
    create_risk_incident_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    PROBATION_THRESHOLD,
    SUSPEND_THRESHOLD,
    MIN_GPA,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DEFAULT_CLOCK_ISO,
    DEFAULT_BID_DAY_AT,
    DEFAULT_PARTY_START,
    DEFAULT_PARTY_DURATION_MINUTES,
    DEFAULT_PARTY_CAPACITY,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_panhellenic_admin_headers,
    make_recruitment_chair_headers,
    make_risk_officer_headers,
    make_chapter_officer_headers,
    make_pnm_headers,
    make_anonymous_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    create_chapter,
    create_round,
    register_pnm,
    activate_pnm,
    register_and_activate_pnm,
    create_party,
    open_party,
    complete_party,
    cancel_party,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    decline_invitation,
    file_pnm_preference,
    file_chapter_preference,
    advance_round,
    file_risk_incident,
    dismiss_risk_incident,
    attend_and_complete_party_for_pnm,
    setup_round_with_proposed_bid_via_mutual_selection,
    setup_round_with_accepted_bid,
    raise_chapter_to_risk_points,
    get_chapter,
    get_pnm,
    get_party,
    get_invitation,
    get_round,
    get_bid_match,
    get_risk_incident,
    list_dues_ledger,
    list_bid_match_dues_ledger,
    list_pnm_bid_matches,
)
