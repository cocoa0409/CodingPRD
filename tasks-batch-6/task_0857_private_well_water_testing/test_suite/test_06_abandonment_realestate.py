"""Abandonment/decommission permits and real-estate test requirements.

Covers the abandonment cross-entity well-active dependency, the real-estate
validity-window boundary, the OCC supersede race, and the related corner-queue
abandonment and requirement claims.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_applicant_headers,
    factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]


def _create_abandonment(api, ctx):
    payload = f.abandonment_permit_payload(ctx.well_id, ctx.applicant_id, ctx.driller_id)
    return get_success_data(api.create_abandonment_permit(payload, ctx.applicant_headers))


# --------------------------------------------------------------------------
# cross_entity_state_dependency / abandonment_approve_requires_well_active
# --------------------------------------------------------------------------
def test_abandonment_approve_on_proposed_well_rejected(api):
    """PRD §3.8: "the well must currently be ACTIVE (a well in any other registry
    status is rejected with ERR_WELL_NOT_ACTIVE, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/abandonment_approve_requires_well_active
    """
    ctx = fx.create_well_only(api)  # PROPOSED well
    driller = fx.create_driller(api)
    payload = f.abandonment_permit_payload(ctx.well_id, ctx.applicant_id, driller["id"])
    permit = get_success_data(api.create_abandonment_permit(payload, ctx.applicant_headers))
    resp = api.approve_abandonment(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WELL_NOT_ACTIVE)


def test_abandonment_approve_on_inactive_well_rejected(api):
    """PRD §3.8: "the well must currently be ACTIVE (a well in any other registry
    status is rejected with ERR_WELL_NOT_ACTIVE, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/abandonment_approve_requires_well_active
    """
    ctx = fx.setup_active_well(api)
    get_success_data(api.deactivate_well(ctx.well_id, OFFICER))  # ACTIVE -> INACTIVE
    permit = _create_abandonment(api, ctx)
    resp = api.approve_abandonment(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WELL_NOT_ACTIVE)


# --------------------------------------------------------------------------
# boundary_precision_check / real_estate_window_exactly_90_days_inclusive
# --------------------------------------------------------------------------
def test_link_sample_exactly_90_days_before_closing_accepted(api):
    """PRD §3.9: "the sample's collected_on must be at or before the
    closing_date, and the gap from collection to closing must be no greater than
    the real-estate validity span REAL_ESTATE_TEST_VALIDITY_DAYS (90 days)".

    Design: Difficulty/boundary_precision_check/real_estate_window_exactly_90_days_inclusive
    """
    ctx = fx.setup_requirement_with_safe_sample(
        api, collected_on="2026-05-01T00:00:00Z", closing_date="2026-07-30T00:00:00Z")
    resp = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"],
         "expected_requirement_version": ctx.requirement_version},
        ctx.applicant_headers)
    data = validate_success(resp, 200)
    assert data["linked_sample_id"] == ctx.sample["id"]


def test_link_sample_within_window_accepted(api):
    """PRD §3.9: "A successful attachment sets linked_sample_id to the chosen
    sample, superseding any previously attached candidate, and advances the
    requirement's version."

    Design: Difficulty/boundary_precision_check/real_estate_window_exactly_90_days_inclusive
    """
    ctx = fx.setup_requirement_with_safe_sample(
        api, collected_on="2026-05-02T00:00:00Z", closing_date="2026-07-30T00:00:00Z")
    resp = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"],
         "expected_requirement_version": ctx.requirement_version},
        ctx.applicant_headers)
    data = validate_success(resp, 200)
    assert data["linked_sample_id"] == ctx.sample["id"]
    assert data["version"] == ctx.requirement_version + 1


# --------------------------------------------------------------------------
# Corner: abandonment side effects and blocking
# --------------------------------------------------------------------------
def test_complete_abandonment_decommissions_well(api):
    """PRD §3.8: "On completion the permit's completed_on is stamped with the
    current instant, the permit moves from APPROVED to COMPLETED, and, as a
    cross-entity effect, the well's registry status advances from ACTIVE to the
    terminal DECOMMISSIONED."

    Design: Corner/state_machines/abandonment_complete_decommissions_well
    """
    ctx = fx.setup_active_well(api)
    permit = _create_abandonment(api, ctx)
    get_success_data(api.approve_abandonment(permit["id"], OFFICER))
    resp = api.complete_abandonment(permit["id"], ctx.driller_headers)
    completed = validate_success(resp, 200)
    assert completed["status"] == "COMPLETED"
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["registry_status"] == "DECOMMISSIONED"


def test_abandonment_blocked_by_nonterminal_permit(api):
    """PRD §3.8: "no construction permit on the same well may be in a non-terminal
    status of SUBMITTED, APPROVED, or ISSUED; if such a permit exists the approval
    is rejected with ERR_ABANDONMENT_BLOCKED (HTTP 409)."

    Design: Corner/validations/abandonment_blocked_by_nonterminal_permit
    """
    ctx = fx.setup_active_well(api)
    # A second, still-SUBMITTED construction permit on the same ACTIVE well.
    fx.create_submitted_permit(
        api, ctx.well_id, ctx.applicant_id, ctx.driller_id,
        proposed_depth_ft=260,
        scheduled_start="2026-06-10T08:00:00Z", scheduled_end="2026-06-11T17:00:00Z")
    permit = _create_abandonment(api, ctx)
    resp = api.approve_abandonment(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_ABANDONMENT_BLOCKED)


# --------------------------------------------------------------------------
# Corner: real-estate window / safety / state / OCC
# --------------------------------------------------------------------------
def test_link_sample_outside_window_rejected(api):
    """PRD §3.9: "the gap from collection to closing must be no greater than the
    real-estate validity span REAL_ESTATE_TEST_VALIDITY_DAYS (90 days); a
    violation is rejected with ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW (HTTP 422)."

    Design: Corner/validations/link_sample_outside_window_91_days_returns_error
    """
    ctx = fx.setup_requirement_with_safe_sample(
        api, collected_on="2026-04-30T00:00:00Z", closing_date="2026-07-30T00:00:00Z")
    resp = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"],
         "expected_requirement_version": ctx.requirement_version},
        ctx.applicant_headers)
    validate_error(resp, ApiErrorId.ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW)


def test_link_unsafe_sample_rejected(api):
    """PRD §3.9: "The safety check requires that the linked sample is RESULTED and
    that its result's advisory_level_confirmed is SAFE; otherwise the attachment
    is rejected with ERR_SAMPLE_NOT_SAFE (HTTP 422)."

    Design: Corner/validations/link_unsafe_sample_returns_sample_not_safe
    """
    ctx = fx.setup_requirement_with_safe_sample(
        api, collected_on="2026-05-01T00:00:00Z", closing_date="2026-07-30T00:00:00Z",
        transaction_type="REFINANCE",
        result_overrides={"bacteria_coliform": "PRESENT"})
    resp = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"],
         "expected_requirement_version": ctx.requirement_version},
        ctx.applicant_headers)
    validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_SAFE)


def test_certify_waived_requirement_rejected(api):
    """PRD §3.9: "Attachment is allowed only while the requirement is OPEN; an
    attempt against a requirement in any other status is rejected with
    ERR_REQUIREMENT_NOT_OPEN (HTTP 409)."
    PRD §3.9: "certification requires that the requirement is OPEN and that a
    candidate sample is currently attached (linked_sample_id is not null)."

    Design: Corner/validations/certify_waived_requirement_returns_requirement_not_open
    """
    ctx = fx.create_well_only(api)
    requirement = get_success_data(api.create_real_estate_requirement(
        f.real_estate_requirement_payload(ctx.well_id, ctx.applicant_id), ctx.applicant_headers))
    get_success_data(api.waive_requirement(requirement["id"], {"reason": "cash sale"}, OFFICER))
    resp = api.certify_requirement(requirement["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_OPEN)


def test_link_sample_with_stale_version_conflicts(api):
    """PRD §2.10: "If that value does not equal the requirement's current version
    — because an earlier attachment already advanced it since the client read the
    record — the request is rejected with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting/link_sample_stale_expected_version_conflicts
    """
    ctx = fx.setup_requirement_with_safe_sample(
        api, collected_on="2026-05-01T00:00:00Z", closing_date="2026-07-30T00:00:00Z")
    stale_version = ctx.requirement_version
    first = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"], "expected_requirement_version": stale_version},
        ctx.applicant_headers)
    validate_success(first, 200)  # version advances 1 -> 2
    second = api.link_sample(
        ctx.requirement_id,
        {"linked_sample_id": ctx.sample["id"], "expected_requirement_version": stale_version},
        ctx.applicant_headers)
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)
