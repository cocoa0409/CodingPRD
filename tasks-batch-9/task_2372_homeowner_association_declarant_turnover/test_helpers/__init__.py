"""Test infrastructure for the HOA Declarant Turnover API.

Re-exports everything the test suite needs — the framework's generic
validators and assertions alongside this API's client, error catalogue,
constants, payload factories, domain assertions and seeding helpers — so every
test module imports from a single place.
"""

# ─── Framework re-exports ─────────────────────────────

from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# ─── This API's client ────────────────────────────────

from .api_client import ApiClient  # noqa: F401

# ─── Error catalogue ──────────────────────────────────

from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_ENTITY  # noqa: F401

# ─── Business constants ───────────────────────────────

from .constants import *  # noqa: F401,F403

# ─── Domain assertions ────────────────────────────────

from .assertions import (  # noqa: F401
    assert_all_cents_integers,
    assert_cancellation_window,
    assert_cents_integer,
    assert_claim_pool_conserved,
    assert_claim_reserve_breakdown,
    assert_common_fields,
    assert_created_at_ascending,
    assert_created_fresh,
    assert_dimensions,
    assert_envelope_meta,
    assert_error_envelope_shape,
    assert_instant,
    assert_pagination_meta,
    assert_pct,
    assert_posture,
    assert_schedule_waterfall,
    assert_seat_ledger,
    assert_study_evaluation,
    assert_two_decimal_places,
    assert_unevaluated_study,
)

# ─── Payload factories ────────────────────────────────

from .factories import (  # noqa: F401
    advance_payload,
    assessment_schedule_payload,
    association_payload,
    audit_engagement_payload,
    certify_trigger_payload,
    claim_action_payload,
    close_sale_payload,
    component_payload,
    contract_action_payload,
    defect_claim_payload,
    director_payload,
    lot_payload,
    milestone_payload,
    records_item_payload,
    records_transition_payload,
    reserve_study_payload,
    reversal_payload,
    study_action_payload,
    subsidy_entry_payload,
    turnover_case_payload,
    vendor_contract_payload,
)

# ─── Identities and headers ───────────────────────────

from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    DECLARANT_HEADERS,
    DECLARANT_USER_ID,
    ELECTION_INSPECTOR_USER_ID,
    HEADERS_NO_AUTH,
    HEADERS_UNKNOWN_ROLE,
    HEADERS_WITHOUT_ROLE,
    HEADERS_WITHOUT_USER_ID,
    INSPECTOR_HEADERS,
    OUTSIDE_WINDOW_OPERATOR_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    SHARED_OPERATOR_USER_ID,
    UNKNOWN_ROLE_NAME,
    make_admin_headers,
    make_auditor_headers,
    make_declarant_headers,
    make_headers,
    make_inspector_headers,
    make_transition_committee_headers,
)

# ─── Fixtures and seeding helpers ─────────────────────

from .fixtures import (  # noqa: F401
    admin_headers,
    api,
    association,
    association_with_case,
    auditor_headers,
    build_adopted_reserve_study,
    build_case_in_audit_in_progress,
    build_closed_lots,
    build_completed_component,
    build_conveyed_component,
    build_owner_controlled_board,
    committee_headers,
    conveyed_component,
    create_schedule_with_fresh_version,
    declarant_headers,
    do_accept_item,
    do_adopt_schedule,
    do_adopt_study,
    do_advance_financial,
    do_advance_governance,
    do_build_complete,
    do_cancel_contract,
    do_certify_trigger,
    do_claim_accept,
    do_claim_developer_reject,
    do_claim_notice,
    do_claim_reinvestigate,
    do_claim_reserve,
    do_claim_withdraw,
    do_close_sale,
    do_consent,
    do_conveyance_accepted,
    do_deed_tendered,
    do_deliver_item,
    do_issue_engagement,
    do_recompute_study,
    do_refuse_consent,
    do_reject_item,
    do_repose_sweep,
    do_request_assignment,
    do_rescind_director,
    do_reverse_entry,
    fresh_association_version,
    inspector_headers,
    read_association,
    read_turnover_case,
    seed_assessment_schedule,
    seed_association,
    seed_audit_engagement,
    seed_component,
    seed_declarant_appointed_director,
    seed_defect_claim,
    seed_director,
    seed_lot,
    seed_owner_elected_director,
    seed_records_item,
    seed_reserve_study,
    seed_subsidy_entry,
    seed_turnover_case,
    seed_vendor_contract,
    set_clock,
)

# ─── Type shapes ──────────────────────────────────────

from .types import (  # noqa: F401
    AssessmentSchedule,
    Association,
    AuditEngagement,
    ClockState,
    CommonAreaComponent,
    CommonFields,
    DefectClaim,
    Director,
    Headers,
    Lot,
    Payload,
    RecordsTransferItem,
    ReposeSweepResult,
    ReserveStudy,
    SubsidyEntry,
    TurnoverCase,
    VendorContract,
)
