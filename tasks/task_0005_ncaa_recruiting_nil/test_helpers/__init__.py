"""Barrel export: framework generics + PRD-specific code.

Tests import everything from `test_helpers` so they have one consistent
source for both the runner's generic utilities and this domain's specifics.
"""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
    GenericApiClient,
)

# PRD-specific types
from .types import (
    UserRole,
    SportCode, PeriodType, ContactChannel,
    EligibilityStatus, EligibilityCertificationStatus, DenialReason,
    ScholarshipOfferStatus,
    NILDealStatus, NILDealTier, NILRejectionReason,
    TransferPortalEntryStatus, BoosterIncidentStatus, PenaltyTier,
    Program, Period, StudentAthlete, EligibilityCertification,
    RecruitingContact, ScholarshipOffer, NILDeal,
    TransferPortalEntry, BoosterIncident,
)

# API client + endpoint surface
from .api_client import api_client, ApiClient

# Error catalogue (importing this module registers the HTTP-status map).
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_program,
    assert_program_invariants,
    assert_period,
    assert_student_athlete,
    assert_eligibility_certification,
    assert_recruiting_contact,
    assert_scholarship_offer,
    assert_nil_deal,
    assert_transfer_portal_entry,
    assert_booster_incident,
)

# Factories
from .factories import (
    create_program_payload,
    create_period_payload,
    create_student_athlete_payload,
    create_eligibility_certification_payload,
    deny_certification_payload,
    create_recruiting_contact_payload,
    create_scholarship_offer_payload,
    send_scholarship_offer_payload,
    create_nil_deal_payload,
    reject_nil_deal_payload,
    create_transfer_portal_entry_payload,
    match_transfer_portal_entry_payload,
    create_booster_incident_payload,
    sustain_booster_incident_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    DE_MINIMIS_CUTOFF_CENTS,
    STANDARD_CUTOFF_CENTS,
    SEVERITY_TIER_1_CUTOFF_CENTS,
    SEVERITY_TIER_2_CUTOFF_CENTS,
    SEVERITY_TIER_3_CUTOFF_CENTS,
    SEVERITY_WEIGHTS,
    PENALTY_TIER_LEVEL_II_FLOOR,
    PENALTY_TIER_BAN_FLOOR,
    SLOT_CAP_MIN, SLOT_CAP_MAX,
    GPA_MIN, GPA_MAX, GPA_NCAA_FLOOR,
    PORTAL_WINDOW_DAYS,
    NIL_REVISION_ROUND_CAP,
    PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT, PAGINATION_DEFAULT_OFFSET,
)

# User identities
from .test_users import (
    TEST_USERS,
    make_student_athlete_headers,
    make_coach_headers,
    make_nil_reviewer_headers,
    make_compliance_officer_headers,
    make_eligibility_center_headers,
)

# Composite fixtures
from .fixtures import (
    # Clock + sweep
    set_clock,
    sweep_portal_expirations,
    # Primitives
    create_program,
    create_period,
    create_student_athlete,
    submit_certification,
    approve_certification,
    deny_certification,
    certify_athlete,
    create_draft_offer,
    send_offer,
    create_and_send_offer,
    create_nil_deal,
    submit_nil_deal,
    request_nil_deal_revision,
    enter_portal,
    report_incident,
    open_investigation,
    sustain_incident,
    report_and_sustain_incident,
    # Composite
    setup_certified_athlete,
    setup_program_with_certified_athlete,
    setup_program_with_sent_offer,
    setup_nil_deal_under_review,
    setup_program_at_postseason_ban,
    setup_program_at_level_one,
    setup_athlete_in_portal_window,
)
