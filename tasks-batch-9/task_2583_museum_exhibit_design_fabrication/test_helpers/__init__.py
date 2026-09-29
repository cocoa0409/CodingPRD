"""Shared test infrastructure for the exhibit design and fabrication API.

Tests import everything through this package: the framework's envelope
validators and race helpers, the endpoint client, the error catalogue, the
domain vocabularies, the payload factories, the caller identities, the domain
assertions and the composite setup builders.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import factories, fixtures  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_common_fields,
    assert_counters,
    assert_empty_envelope,
    assert_envelope,
    assert_error_envelope_shape,
    assert_geometry,
    assert_ids_in_order,
    assert_index,
    assert_ledger,
    assert_money_identity,
    assert_only_keys,
    assert_unchanged,
    assert_zone_slot_identity,
    assert_zone_slots,
    round_half_up,
)
from .constants import *  # noqa: F401,F403
from .factories import OMIT, OBJECTIVE_PRIMARY, OBJECTIVE_SECONDARY  # noqa: F401
from .fixtures import FAR_DEADLINE, LATE_CLOCK, project_in_phase  # noqa: F401
from .test_users import (  # noqa: F401
    ACCESSIBILITY,
    ALL_ROLES,
    ALL_ROLE_HEADERS,
    BLANK_USER_ID_HEADER,
    CONSERVATOR,
    CURATOR,
    FABRICATION,
    HEADERS_BY_ROLE,
    NO_ROLE_HEADER,
    NO_USER_ID_HEADER,
    OPERATIONS,
    PANEL_ELIGIBLE_ROLES,
    PM,
    PM_SECOND,
    ROLE_ACCESSIBILITY,
    ROLE_CONSERVATOR,
    ROLE_CURATOR,
    ROLE_FABRICATION_LEAD,
    ROLE_MUSEUM_OPERATIONS,
    ROLE_PROJECT_MANAGER,
    UNKNOWN_ROLE_HEADER,
    USER_ACCESSIBILITY,
    USER_CONSERVATOR,
    USER_CURATOR,
    USER_FABRICATION,
    USER_ID_BY_ROLE,
    USER_OPERATIONS,
    USER_PM,
    USER_PM_SECOND,
    headers_for,
)
from .types import (  # noqa: F401
    CaseDecision,
    CaseStatus,
    ComplexityTier,
    ConditionStatus,
    DrawingDecision,
    DrawingStatus,
    FinishGrade,
    InteractiveKind,
    InteractiveStatus,
    MaintenanceTier,
    MaterialClass,
    MaterialDecision,
    MaterialStatus,
    MountStatus,
    OccupancyState,
    OddyResult,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    PrototypeDecision,
    PunchStatus,
    RoundStatus,
    SecurityTier,
    Severity,
    UsedIn,
    Verdict,
    VoteDecision,
    WindowDecision,
    WindowStatus,
    WorkClass,
)
