"""Corner coverage: domain validation rejections, recurring-cadence fixed-drift
behavior, warranty expiry on refresh, RBAC forbidden/missing-header gates, and
the two optimistic-concurrency stale-version checks.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_inspector, create_property, get_property, set_clock, pay,
    create_inspector_payload, create_property_payload,
    create_radon_test_payload, retrieve_short_term_payload, schedule_payload,
    create_mitigation_job_payload, cancel_warranty_payload,
    create_permit_payload,
    setup_actionable_property, setup_designed_job, setup_quoted_job,
    setup_scheduled_job, setup_cleared_job_with_warranty, create_crew,
    make_inspector_headers, make_client_contact_headers,
    TEST_USERS, DESIGNER, COMPLIANCE, ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLIENT = TEST_USERS["client_contact_headers"]


# ── validations ────────────────────────────────────────────────────────────

def test_quote_without_actionable_result_rejected(api):
    """PRD §3.4: "Quoting is only permitted when the property posture is
    `MITIGATION_REQUIRED` and the `triggering_test_id` resolves to a test whose
    `action_outcome` is `ACTION_RECOMMENDED`; otherwise the quote is rejected
    with `ERR_NO_ACTIONABLE_RESULT`."

    Design: Corner/validations/val_quote_without_actionable_result_rejected
    """
    # NO_ACTION initial result (2.0 < 4.0) → posture never reaches MITIGATION_REQUIRED.
    _, _, _, job = setup_designed_job(
        foundation_type="SLAB", floor_area_sqft=1400, lab_result=2.0,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    res = api.quote_job(job["id"], DESIGNER)
    validate_error(res, ApiErrorId.ERR_NO_ACTIONABLE_RESULT.value)


def test_place_test_with_unknown_inspector_rejected(api):
    """PRD §2.5: "foreign-key fields supplied in the request body — `inspector_id`,
    `crew_id`, `triggering_test_id`, and `mitigation_job_id` — must reference
    existing resources, otherwise `ERR_REFERENCED_RESOURCE_NOT_FOUND`."

    Design: Corner/validations/val_referenced_inspector_not_found
    """
    prop = create_property()
    bogus = "00000000-0000-0000-0000-000000000777"
    res = api.create_radon_test(
        create_radon_test_payload(prop["id"], bogus,
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        make_inspector_headers(bogus))
    validate_error(res, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)


def test_retrieve_before_window_rejected(api):
    """PRD §3.2: "the difference between the current logical-clock instant and
    `placement_start_utc` must be at least `placement_window_hours` hours,
    otherwise the request is rejected with `ERR_PLACEMENT_WINDOW_NOT_ELAPSED`."

    Design: Corner/validations/val_retrieve_before_window_rejected
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    set_clock("2026-04-02T23:00:00Z")  # 47h < 48h
    res = api.retrieve_radon_test(test["id"], retrieve_short_term_payload(3.0), insp)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_WINDOW_NOT_ELAPSED.value)


def test_duplicate_active_inspector_license_rejected(api):
    """PRD §2.9: "An `nrpp_license_id` must be unique among `ACTIVE` inspectors;
    a registration that would duplicate the license of another active inspector
    is rejected with `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/validations/val_duplicate_inspector_license_rejected
    """
    validate_success(api.create_inspector(
        create_inspector_payload(full_name="Dup A", nrpp_license_id="NRPP-DUP"),
        ADMIN), 201)
    res = api.create_inspector(
        create_inspector_payload(full_name="Dup B", nrpp_license_id="NRPP-DUP"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)


def test_schedule_with_insufficient_deposit_rejected(api):
    """PRD §3.5: "The deposit must be satisfied: `deposit_paid_cents` must be at
    least `deposit_required_cents`, else `ERR_DEPOSIT_NOT_SATISFIED`."

    Design: Corner/validations/val_deposit_not_satisfied_on_schedule
    """
    crew = create_crew()
    _, prop, _, job = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    # deposit_required is 45000; only 40000 paid.
    assert job["deposit_required_cents"] == 45000
    pay(job["id"], "DEPOSIT", 40000)
    prop_now = get_property(prop["id"])
    res = api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-03T08:00:00Z",
                         "2026-04-03T12:00:00Z", prop_now["version"]),
        DESIGNER)
    validate_error(res, ApiErrorId.ERR_DEPOSIT_NOT_SATISFIED.value)


def test_schedule_window_start_not_before_end_rejected(api):
    """PRD §3.5: "The window must be well formed, with `install_start_utc`
    strictly earlier than `install_end_utc`, else `ERR_INVALID_WINDOW`."

    Design: Corner/validations/val_invalid_window_start_not_before_end
    """
    crew = create_crew()
    _, prop, _, job = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    pay(job["id"], "DEPOSIT", job["deposit_required_cents"])
    prop_now = get_property(prop["id"])
    res = api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-05T08:00:00Z",
                         "2026-04-05T08:00:00Z", prop_now["version"]),
        DESIGNER)
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW.value)


# ── calculations / endpoints ────────────────────────────────────────────────

def test_fire_due_advances_cadence_from_prior_due_not_clock(api):
    """PRD §3.7: "Crucially the cadence advances from the prior scheduled due
    date, not from the actual fire timestamp, so a late fire does not drift the
    schedule."
    PRD §3.7: "A fire creates a fresh `RECURRING` radon test on the property in
    the `PLACED` state, increments `fired_count`, sets `last_fired_utc` to the
    current logical-clock instant, and advances `next_due_utc` by `interval_days`
    days."

    Design: Corner/calculations/calc_next_retest_fixed_cadence_no_drift
    """
    _, prop, _, _, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False, "retest_interval_days": 730})
    # next_due was 2028-04-02; fire late at 2028-12-01.
    assert schedule["next_due_utc"].startswith("2028-04-02T00:00:00")
    set_clock("2028-12-01T00:00:00Z")
    fired = validate_success(api.fire_due(schedule["id"], COMPLIANCE), 200)
    # 2028-04-02 + 730 days = 2030-04-02 (NOT clock-based).
    assert fired["next_due_utc"].startswith("2030-04-02T00:00:00")
    assert fired["fired_count"] == 1


def test_warranty_refresh_expires_after_term(api):
    """PRD §3.6: "when the current logical-clock instant is at or after
    `started_at_utc` plus `term_days` days, coverage moves from `ACTIVE` to
    `EXPIRED`, which cascades the associated retest schedule to `ENDED`."

    Design: Corner/endpoints/ep_warranty_refresh_expires_after_term
    """
    _, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False, "warranty_term_days": 30})
    # started_at 2026-04-03 + 30 days; advance to 2026-05-04 (past term).
    set_clock("2026-05-04T00:00:00Z")
    refreshed = validate_success(api.refresh_warranty(warranty["id"], COMPLIANCE), 200)
    assert refreshed["coverage_status"] == "EXPIRED"
    sched_after = validate_success(
        api.get_retest_schedule(schedule["id"], COMPLIANCE), 200)
    assert sched_after["status"] == "ENDED"


def test_fire_due_before_due_date_rejected(api):
    """PRD §3.7: "Firing ... requires the schedule to be `ARMED`, the current
    logical-clock instant to be at or after `next_due_utc` (else
    `ERR_RETEST_NOT_DUE`)."

    Design: Corner/endpoints/ep_retest_not_due_rejected
    """
    _, prop, _, _, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    # Clock left at 2026-04-03; next_due is 2028-04-02.
    res = api.fire_due(schedule["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_RETEST_NOT_DUE.value)


# ── errors ───────────────────────────────────────────────────────────────────

def test_open_claim_without_qualifying_retest_rejected(api):
    """PRD §3.6: "the property's `latest_result_pci_l` must be at least the
    warranty's `guarantee_ceiling_pci_l`, else `ERR_NO_QUALIFYING_RETEST`."

    Design: Corner/errors/err_no_qualifying_retest_on_open_claim
    """
    # latest_result_pci_l stays 1.5 (the passing post-mit retest) < ceiling 2.0.
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    client = make_client_contact_headers(prop["id"])
    res = api.open_claim(warranty["id"], client)
    validate_error(res, ApiErrorId.ERR_NO_QUALIFYING_RETEST.value)


def test_post_mitigation_test_against_non_installed_job_rejected(api):
    """PRD §3.2: "A `POST_MITIGATION` test placed against a job that is not
    `INSTALLED`, or a `mitigation_job_id` supplied on a test whose purpose is not
    `POST_MITIGATION`, is rejected with `ERR_RETEST_NOT_ALLOWED`."

    Design: Corner/errors/err_retest_not_allowed_post_mit_without_installed_job
    """
    inspector, prop, _, job = setup_designed_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    insp = make_inspector_headers(inspector["id"])
    res = api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR",
                                  purpose="POST_MITIGATION",
                                  mitigation_job_id=job["id"],
                                  placement_window_hours=48),
        insp)
    validate_error(res, ApiErrorId.ERR_RETEST_NOT_ALLOWED.value)


# ── rbac ─────────────────────────────────────────────────────────────────────

def test_client_contact_cannot_place_test(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/rbac_clientcontact_cannot_place_test
    """
    inspector = create_inspector()
    prop = create_property()
    client = make_client_contact_headers(prop["id"])
    res = api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        client)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_missing_user_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/rbac_missing_user_headers_rejected
    """
    res = api.list_properties(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_inspector_cannot_issue_permit(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/rbac_inspector_cannot_issue_permit
    """
    inspector, _, _, job, _ = setup_scheduled_job(
        foundation_type="SLAB", floor_area_sqft=1400, pay_balance=False,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    insp = make_inspector_headers(inspector["id"])
    res = api.create_permit(
        create_permit_payload(job["id"], "CTY-1", "P-C610"), insp)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ── optimistic concurrency ───────────────────────────────────────────────────

def test_schedule_with_stale_property_version_rejected(api):
    """PRD §2.7: "A competing job for the same property that reaches its scheduled
    state flips the property posture to `MITIGATING` and advances
    `Property.version`; a scheduler still holding the pre-mutation version is
    therefore working from a stale view, and the schedule is rejected with
    `ERR_STALE_PROPERTY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_stale_property_version_rejected
    """
    crew = create_crew()
    _, prop, _, job = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    pay(job["id"], "DEPOSIT", job["deposit_required_cents"])
    prop_now = get_property(prop["id"])
    stale = prop_now["version"] - 1
    res = api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-03T08:00:00Z",
                         "2026-04-03T12:00:00Z", stale),
        DESIGNER)
    validate_error(res, ApiErrorId.ERR_STALE_PROPERTY_VERSION.value)


def test_cancel_warranty_with_stale_version_rejected(api):
    """PRD §2.7: "a cancel still carrying the pre-mutation version is rejected
    with `ERR_STALE_WARRANTY_VERSION` (HTTP 412), because the prorated refund
    would otherwise be computed against a coverage or claim state the caller
    never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_cancel_warranty_stale_version_rejected
    """
    _, prop, _, warranty, _, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    stale = fresh["version"] - 1
    res = api.cancel_warranty(warranty["id"], cancel_warranty_payload(stale), client)
    validate_error(res, ApiErrorId.ERR_STALE_WARRANTY_VERSION.value)
