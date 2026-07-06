"""Composite setup helpers for the Survey & Market-Research Panel API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the database is reset before each test). Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear error.

Identity threading: the Panelist role is entity-backed. Any ownership-gated call
(participation start/submit/abandon, payout create/cancel, booking create/cancel)
uses make_panelist_headers(panelist["id"]) — never the shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_study_payload, create_quota_cell_payload, create_panelist_payload,
    create_consent_payload, create_participation_payload, create_attention_check_payload,
    submit_payload, create_facility_payload, create_focus_group_payload,
    create_focus_group_booking_payload, create_data_delivery_payload,
)
from .test_users import (
    TEST_USERS, make_panelist_headers,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


# ==========================================================================
# Tier 1: Single-entity creation shortcuts
# ==========================================================================
def create_study(**overrides) -> dict:
    """Create a DRAFT study. Returns the study resource."""
    resp = api_client.create_study(create_study_payload(**overrides), RM)
    return get_success_data(resp)


def create_quota_cell(study_id, **overrides) -> dict:
    resp = api_client.create_quota_cell(study_id, create_quota_cell_payload(**overrides), RM)
    return get_success_data(resp)


def create_panelist(**overrides) -> dict:
    resp = api_client.create_panelist(create_panelist_payload(**overrides), OPS)
    return get_success_data(resp)


def create_consent(panelist_id, study_id, **overrides) -> dict:
    resp = api_client.create_consent(
        create_consent_payload(panelist_id, study_id, **overrides), OPS)
    return get_success_data(resp)


def create_facility(**overrides) -> dict:
    resp = api_client.create_facility(create_facility_payload(**overrides), FC)
    return get_success_data(resp)


def get_panelist_version(panelist_id) -> int:
    """Read a panelist's current version (recomputes balance/health first)."""
    data = get_success_data(api_client.get_panelist(panelist_id, OPS))
    return data["version"]


# ==========================================================================
# Tier 2: Launched-study scaffolds (the most common preamble)
# ==========================================================================
def create_fielding_study_with_cell(target_n=2, study_overrides=None, segment_key="SEG_A"):
    """Create a study, add one quota cell, launch to FIELDING.
    Returns (study, cell). study reflects the launch response."""
    study_overrides = study_overrides or {}
    study = create_study(**study_overrides)
    cell = create_quota_cell(study["id"], segment_key=segment_key, target_n=target_n)
    study = get_success_data(api_client.launch_study(study["id"], RM))
    return study, cell


def setup_panelist_with_consent(study_id, panelist_overrides=None,
                                consent_version=1, segment_key="SEG_A"):
    """Register a panelist and record an ACCEPTED consent for (panelist, study)."""
    panelist_overrides = panelist_overrides or {}
    panelist_overrides.setdefault("segment_key", segment_key)
    panelist = create_panelist(**panelist_overrides)
    create_consent(panelist["id"], study_id, consent_version=consent_version)
    return panelist


def create_screening_participation(study_id, panelist_id, quota_cell_id):
    """Create a participation (SCREENING / NOT_STARTED). Returns the participation."""
    resp = api_client.create_participation(
        create_participation_payload(study_id, panelist_id, quota_cell_id), FC)
    return get_success_data(resp)


def setup_screened_in_participation(target_n=2, study_overrides=None,
                                    segment_key="SEG_A", panelist_overrides=None):
    """Active study + cell + consented panelist + a participation screened IN.
    Returns (study, cell, panelist, participation) where participation is
    SCREENED_IN with a HELD provisional accrual.
    """
    study, cell = create_fielding_study_with_cell(
        target_n=target_n, study_overrides=study_overrides, segment_key=segment_key)
    panelist = setup_panelist_with_consent(
        study["id"], panelist_overrides=panelist_overrides, segment_key=segment_key)
    participation = create_screening_participation(study["id"], panelist["id"], cell["id"])
    participation = get_success_data(
        api_client.screen_participation(participation["id"], "IN", FC))
    return study, cell, panelist, participation


def setup_started_participation(target_n=2, study_overrides=None,
                                segment_key="SEG_A", panelist_overrides=None):
    """As setup_screened_in_participation, but also start the survey (IN_PROGRESS).
    Returns (study, cell, panelist, participation)."""
    study, cell, panelist, participation = setup_screened_in_participation(
        target_n=target_n, study_overrides=study_overrides,
        segment_key=segment_key, panelist_overrides=panelist_overrides)
    participation = get_success_data(
        api_client.start_participation(participation["id"], make_panelist_headers(panelist["id"])))
    return study, cell, panelist, participation


# ==========================================================================
# Tier 3: Full lifecycle shortcuts (through QUALIFIED / credited points)
# ==========================================================================
def setup_qualified_participation(target_n=2, study_overrides=None,
                                  segment_key="SEG_A", completion_seconds=600,
                                  straightline_run=0, panelist_overrides=None):
    """Drive a participation through screen-in -> start -> submit at top quality,
    producing a QUALIFIED participation and a CREDITED finalized accrual.
    Returns (study, cell, panelist, participation) where participation is the
    submit response (screening_status QUALIFIED).
    """
    study, cell, panelist, participation = setup_started_participation(
        target_n=target_n, study_overrides=study_overrides,
        segment_key=segment_key, panelist_overrides=panelist_overrides)
    participation = get_success_data(api_client.submit_participation(
        participation["id"],
        submit_payload(completion_seconds=completion_seconds, straightline_run=straightline_run),
        make_panelist_headers(panelist["id"])))
    return study, cell, panelist, participation


def setup_panelist_with_points(points_target=150, segment_key="SEG_A"):
    """Produce a panelist whose points_balance == points_target via one QUALIFIED
    participation. With the default study (base=100, est=10) a top-quality submit
    finalizes to 150 points. Returns (study, cell, panelist, participation).
    Asserts nothing; caller reads the live balance via GET /panelists/{id}.
    """
    return setup_qualified_participation(
        target_n=2, segment_key=segment_key,
        study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})


# ==========================================================================
# Tier 4: Attention-check controlled quality submits
# ==========================================================================
def setup_started_participation_with_checks(checks, target_n=5, study_overrides=None,
                                            segment_key="SEG_A"):
    """Active study + consented panelist + participation screened IN, with the
    supplied attention checks recorded, then started (IN_PROGRESS).

    `checks` is a list of (check_kind, passed) tuples recorded before start.
    Returns (study, cell, panelist, participation) ready for a controlled submit.
    """
    study, cell, panelist, participation = setup_screened_in_participation(
        target_n=target_n, study_overrides=study_overrides, segment_key=segment_key)
    for check_kind, passed in checks:
        get_success_data(api_client.create_attention_check(
            participation["id"],
            create_attention_check_payload(check_kind=check_kind, passed=passed), FC))
    participation = get_success_data(
        api_client.start_participation(participation["id"], make_panelist_headers(panelist["id"])))
    return study, cell, panelist, participation


# ==========================================================================
# Tier 5: Health-window targeting (rolling vs lifetime, ACTIVE<->AT_RISK)
# ==========================================================================
def setup_panelist_health_window(completed_recent, extra_incomplete, target_n=10,
                                 segment_key="SEG_H", complete_first=False):
    """Build a panelist with a controlled completion pattern across participations.

    Creates `completed_recent` participations that are screened-in/started/submitted
    (so completion_status COMPLETED), then `extra_incomplete` participations left
    NOT_STARTED. Order of creation is COMPLETED first, then incomplete, so the
    most-recent RECENT_WINDOW (5) participations are the incomplete ones when
    extra_incomplete >= 5.

    With completed_recent completes among the 5 most recent, rolling health base
    = completed_in_window / 5 * 100.

    Returns (study, cell, panelist). Caller reads health via GET /panelists/{id}/health.
    """
    study, cell = create_fielding_study_with_cell(target_n=target_n, segment_key=segment_key)
    panelist = setup_panelist_with_consent(study["id"], segment_key=segment_key)
    ph = make_panelist_headers(panelist["id"])

    # Completed participations first (oldest by created_at).
    for _ in range(completed_recent):
        part = create_screening_participation(study["id"], panelist["id"], cell["id"])
        get_success_data(api_client.screen_participation(part["id"], "IN", FC))
        get_success_data(api_client.start_participation(part["id"], ph))
        get_success_data(api_client.submit_participation(
            part["id"], submit_payload(completion_seconds=600, straightline_run=0), ph))

    # Then incomplete participations (most recent by created_at).
    for _ in range(extra_incomplete):
        create_screening_participation(study["id"], panelist["id"], cell["id"])

    return study, cell, panelist


# ==========================================================================
# Tier 6: Payout-request scaffolds
# ==========================================================================
def setup_panelist_with_requested_payout(points_requested=100, segment_key="SEG_P"):
    """Panelist with points_balance 150 and one REQUESTED payout request.
    Returns (panelist, payout_request)."""
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, segment_key=segment_key,
        study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    version = get_panelist_version(panelist["id"])
    ph = make_panelist_headers(panelist["id"])
    payout = get_success_data(api_client.create_payout_request(
        {"panelist_id": panelist["id"], "payout_method": "CASH",
         "points_requested": points_requested, "expected_panelist_version": version}, ph))
    return panelist, payout


# ==========================================================================
# Tier 7: Focus-group scaffolds
# ==========================================================================
def setup_scheduled_focus_group(facility_overrides=None, focus_group_overrides=None,
                                segment_key="SEG_FG"):
    """Study + facility + one SCHEDULED focus group.
    Returns (study, facility, focus_group)."""
    facility_overrides = facility_overrides or {}
    focus_group_overrides = focus_group_overrides or {}
    study = create_study()
    facility = create_facility(**facility_overrides)
    fg = get_success_data(api_client.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"], **focus_group_overrides), FC))
    return study, facility, fg


def book_panelist_into_session(focus_group_id, panelist_id, expected_version):
    """Create a CONFIRMED focus-group booking. Returns the booking."""
    resp = api_client.create_focus_group_booking(
        create_focus_group_booking_payload(focus_group_id, panelist_id, expected_version), FC)
    return get_success_data(resp)


# ==========================================================================
# Tier 8: Data-delivery / study-closure scaffolds
# ==========================================================================
def setup_closed_study_with_building_delivery(report_format="CSV", segment_key="SEG_DL"):
    """A study launched and closed, with a BUILDING DataDelivery.
    Returns (study, cell, delivery)."""
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key=segment_key)
    delivery = get_success_data(api_client.create_data_delivery(
        create_data_delivery_payload(study["id"], report_format=report_format), RM))
    get_success_data(api_client.close_study(study["id"], RM))
    return study, cell, delivery
