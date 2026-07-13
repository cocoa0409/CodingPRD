"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"setup failed" errors rather than confusing assertion failures.

Identity threading: FacilityOperator is entity-backed on Facility, so every
operator-owned write in these helpers uses make_facility_operator_headers(
facility_id) with the real facility id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload, create_source_payload, create_permit_payload,
    create_public_notice_payload, create_inventory_payload, create_line_item_payload,
    create_stack_test_payload, create_exceedance_payload, create_inspection_payload,
    create_enforcement_action_payload,
)
from .test_users import TEST_USERS, make_facility_operator_headers

REVIEWER = TEST_USERS["permit_reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
ENFORCER = TEST_USERS["enforcement_officer_headers"]


# ─── Primitive builders ───────────────────────────────

def set_clock(to_iso8601, headers=None):
    """Advance the server logical clock (any authenticated role may do this)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or REVIEWER))


def register_facility(name="Test Facility", **overrides) -> dict:
    """Register a facility. Returns the facility resource (includes version)."""
    res = api_client.create_facility(
        create_facility_payload(name=name, **overrides),
        make_facility_operator_headers("bootstrap"),
    )
    return get_success_data(res)


def current_facility_version(facility_id) -> int:
    """Read the facility's current version fresh (for the OCC guard)."""
    fac = get_success_data(
        api_client.get_facility(facility_id, make_facility_operator_headers(facility_id)))
    return fac["version"]


def register_source(facility_id, expected_facility_version=None, **overrides) -> dict:
    """Register an emission source. Auto-reads the current facility version for
    the concurrency guard unless one is supplied explicitly."""
    op = make_facility_operator_headers(facility_id)
    if expected_facility_version is None:
        expected_facility_version = current_facility_version(facility_id)
    res = api_client.create_source(
        create_source_payload(facility_id, expected_facility_version, **overrides), op)
    return get_success_data(res)


def setup_facility_with_source(facility_name="Test Facility", **source_overrides):
    """Register a facility and one source. Returns (facility, source)."""
    facility = register_facility(name=facility_name)
    source = register_source(facility["id"], **source_overrides)
    return facility, source


def register_operating_source(facility_name="Op Facility", **source_overrides):
    """Register facility + source, mark it PERMITTED, then OPERATING.
    Returns (facility, source)."""
    facility, source = setup_facility_with_source(facility_name, **source_overrides)
    op = make_facility_operator_headers(facility["id"])
    get_success_data(api_client.permit_source(source["id"], REVIEWER))
    get_success_data(api_client.start_operating_source(source["id"], op))
    return facility, source


# ─── Inventory helpers ────────────────────────────────

def create_inventory(facility_id, reporting_year=2025, due_at="2026-12-31T00:00:00Z") -> dict:
    op = make_facility_operator_headers(facility_id)
    res = api_client.create_inventory(
        create_inventory_payload(facility_id, reporting_year=reporting_year, due_at=due_at), op)
    return get_success_data(res)


def add_line_item(facility_id, inventory_id, source_id, reported_tons, method="ESTIMATED") -> dict:
    op = make_facility_operator_headers(facility_id)
    res = api_client.create_line_item(
        create_line_item_payload(inventory_id, source_id, reported_tons, method=method), op)
    return get_success_data(res)


def setup_submitted_inventory(facility_id, source_id, line_tons, reporting_year=2025,
                              due_at="2026-12-31T00:00:00Z"):
    """Create a DRAFT inventory, add one line item per value in `line_tons`, and
    submit it. Returns the submitted inventory resource."""
    op = make_facility_operator_headers(facility_id)
    inv = create_inventory(facility_id, reporting_year=reporting_year, due_at=due_at)
    for tons in line_tons:
        add_line_item(facility_id, inv["id"], source_id, tons)
    return get_success_data(api_client.submit_inventory(inv["id"], op))


def certify_inventory(facility_id, inventory_id, expected_facility_version=None):
    """Certify a SUBMITTED inventory. Reads the fresh facility version unless one
    is supplied. Returns the certified inventory resource."""
    if expected_facility_version is None:
        expected_facility_version = current_facility_version(facility_id)
    res = api_client.certify_inventory(
        inventory_id, {"expected_facility_version": expected_facility_version}, REVIEWER)
    return get_success_data(res)


# ─── Permit helpers ───────────────────────────────────

def create_permit(facility_id, permit_type="PERMIT_BY_RULE") -> dict:
    op = make_facility_operator_headers(facility_id)
    return get_success_data(api_client.create_permit(
        create_permit_payload(facility_id, permit_type), op))


def setup_permit_in_public_notice(facility_id, permit_type="PERMIT_BY_RULE",
                                  comment_open_at="2026-03-01T00:00:00Z",
                                  comment_close_at="2026-03-05T00:00:00Z"):
    """Drive a permit to PUBLIC_NOTICE with an OPEN linked notice.
    Returns (permit, notice)."""
    op = make_facility_operator_headers(facility_id)
    permit = create_permit(facility_id, permit_type)
    get_success_data(api_client.submit_permit(permit["id"], op))
    get_success_data(api_client.begin_review_permit(permit["id"], REVIEWER))
    notice = get_success_data(api_client.create_public_notice(
        create_public_notice_payload(permit["id"], comment_open_at, comment_close_at), REVIEWER))
    permit = get_success_data(api_client.open_public_notice_permit(permit["id"], REVIEWER))
    return permit, notice


def setup_issued_permit(facility_id, permit_type="PERMIT_BY_RULE"):
    """Full permit workflow through ISSUED: submit -> begin-review -> notice ->
    open -> advance clock past close -> close -> issue. Returns the issued permit.
    Leaves the logical clock at 2026-03-06T00:00:00Z."""
    permit, notice = setup_permit_in_public_notice(
        facility_id, permit_type,
        comment_open_at="2026-03-01T00:00:00Z", comment_close_at="2026-03-05T00:00:00Z")
    set_clock("2026-03-06T00:00:00Z", REVIEWER)
    get_success_data(api_client.close_public_notice(notice["id"], REVIEWER))
    permit = get_success_data(api_client.issue_permit(permit["id"], REVIEWER))
    return permit, notice


# ─── Exceedance / stack test / enforcement helpers ────

def create_exceedance(source_id, detected_at="2026-03-01T00:00:00Z",
                      event_type="EXCEEDANCE", magnitude_pct=0) -> dict:
    return get_success_data(api_client.create_exceedance(
        create_exceedance_payload(source_id, detected_at, event_type, magnitude_pct), INSPECTOR))


def create_stack_test(source_id, scheduled_start, scheduled_end) -> dict:
    return get_success_data(api_client.create_stack_test(
        create_stack_test_payload(source_id, scheduled_start, scheduled_end), INSPECTOR))


def create_enforcement_action(facility_id, action_type="PENALTY", origin="MANUAL", **overrides) -> dict:
    return get_success_data(api_client.create_enforcement_action(
        create_enforcement_action_payload(facility_id, action_type, origin, **overrides), ENFORCER))


def create_inspection(facility_id, scheduled_start, scheduled_end, complaint_id=None) -> dict:
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(facility_id, scheduled_start, scheduled_end, complaint_id), INSPECTOR))


def setup_suspended_facility(facility_name="Suspended Facility", **source_overrides):
    """Register facility + operating source, open an INITIATED PENALTY and assess
    it so the facility (and its operating source) are SUSPENDED.
    Returns (facility, source, enforcement_action)."""
    facility, source = register_operating_source(facility_name, **source_overrides)
    action = create_enforcement_action(facility["id"], action_type="PENALTY", origin="MANUAL")
    action = get_success_data(api_client.assess_penalty(action["id"], ENFORCER))
    return facility, source, action
