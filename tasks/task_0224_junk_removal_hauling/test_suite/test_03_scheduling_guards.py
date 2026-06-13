"""Dispatch / scheduling guard tests: validation ordering, cross-entity state guards,
hazmat safety, temporal window conflicts, the fiscal credit-limit guard, and optimistic
concurrency on crew and job versions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_estimated_job_with_crew_truck, setup_estimated_job, setup_scheduled_job,
    create_policy, create_customer, create_crew, create_truck, create_job,
    submit_estimate, accept_estimate, add_item, get_crew_version,
    create_dispatch_payload,
    make_customer_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── priority_pair_validation_conflict ────────────────

def test_complete_nonloaded_overlimit_returns_job_not_loaded(api):
    """PRD §2.7: "fifth, target-state correctness for the requested transition (the
    various "not in expected state" conflicts) ... ninth, the fiscal credit-limit guard
    (`ERR_CREDIT_LIMIT_EXCEEDED`)".
    PRD §3.8: "A dispatcher completes a `LOADED` job (otherwise `ERR_JOB_NOT_LOADED`)."

    A complete on an ESTIMATED (not LOADED) job for a low-credit customer fails the
    state check (tier 5) before the fiscal check (tier 9), so the error is
    ERR_JOB_NOT_LOADED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_complete_nonloaded_overlimit
    """
    create_policy()
    cust = create_customer(credit_limit_cents=5000)
    job = create_job(cust["id"])
    est = submit_estimate(job["id"], cust["id"], raw_fraction=0.30)
    accept_estimate(job["id"], est["id"], cust["id"])  # job ESTIMATED, not LOADED
    resp = api.complete_haul_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_LOADED.value)


def test_complete_draft_job_overlimit_still_returns_job_not_loaded(api):
    """PRD §2.7: "fifth, target-state correctness for the requested transition ... ninth,
    the fiscal credit-limit guard (`ERR_CREDIT_LIMIT_EXCEEDED`)".
    PRD §3.8: "A dispatcher completes a `LOADED` job (otherwise `ERR_JOB_NOT_LOADED`)."

    A complete on a DRAFT (never-loaded) job for a low-credit customer still fails the
    state check (tier 5) ahead of the fiscal check (tier 9).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_complete_nonloaded_overlimit
    """
    create_policy()
    cust = create_customer(credit_limit_cents=1)
    job = create_job(cust["id"])  # DRAFT
    resp = api.complete_haul_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_LOADED.value)


def test_dispatch_freon_offshift_nonhazmat_returns_crew_not_hazmat(api):
    """PRD §2.7: "seventh, the hazmat safety guard (`ERR_CREW_NOT_HAZMAT`); eighth, the
    temporal scheduling guards (shift containment and window conflicts)".
    PRD §3.4: "If the job contains any `FREON_APPLIANCE` job item, the assigned crew must
    have `hazmat_certified` true (otherwise `ERR_CREW_NOT_HAZMAT`, HTTP 422)."

    A FREON job dispatched to a non-hazmat crew with a window also outside the shift fails
    the safety guard (tier 7) before the temporal guard (tier 8): ERR_CREW_NOT_HAZMAT.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_dispatch_freon_offshift
    """
    ctx = setup_estimated_job_with_crew_truck(
        raw_fraction=0.30,
        items=[("FREON_APPLIANCE", 1)],
        crew_overrides={"hazmat_certified": False},
    )
    crew_v = get_crew_version(ctx["crew"]["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v,
            window_start_utc="2026-06-10T19:00:00.000Z",
            window_end_utc="2026-06-10T20:00:00.000Z",
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_HAZMAT.value)


def test_dispatch_freon_with_window_conflict_nonhazmat_returns_crew_not_hazmat(api):
    """PRD §2.7: "seventh, the hazmat safety guard (`ERR_CREW_NOT_HAZMAT`); eighth, the
    temporal scheduling guards (shift containment and window conflicts)".
    PRD §3.4: "If the job contains any `FREON_APPLIANCE` job item, the assigned crew must
    have `hazmat_certified` true (otherwise `ERR_CREW_NOT_HAZMAT`, HTTP 422)."

    A FREON job dispatched to a non-hazmat crew with a window that ALSO collides with an
    existing window on that crew still fails the safety guard (tier 7) before the temporal
    conflict guard (tier 8): ERR_CREW_NOT_HAZMAT.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_dispatch_freon_offshift
    """
    policy = create_policy()
    cust = create_customer()
    crew = create_crew(hazmat_certified=False, buffer_minutes=30)
    truck_a = create_truck()
    truck_b = create_truck()
    # First plain job dispatched 09:00-10:00 to occupy the crew window.
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    crew_v0 = get_crew_version(crew["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew["id"], truck_a["id"], crew_v0,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    # Freon job whose window 10:05-11:00 (gap 5 < 30) would conflict; safety fires first.
    job_b = create_job(cust["id"])
    add_item(job_b["id"], cust["id"], "FREON_APPLIANCE", 1)
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew_v1 = get_crew_version(crew["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew["id"], truck_b["id"], crew_v1,
            window_start_utc="2026-06-10T10:05:00.000Z", window_end_utc="2026-06-10T11:00:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_HAZMAT.value)


# ─── cross_entity_state_dependency: crew off duty ─────

def test_dispatch_blocked_when_crew_off_duty(api):
    """PRD §3.4: "The crew must be `ON_DUTY` (otherwise `ERR_CREW_OFF_DUTY`) and the truck
    must be `IN_SERVICE` (otherwise `ERR_TRUCK_OUT_OF_SERVICE`)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_crew_off_duty
    """
    ctx = setup_estimated_job_with_crew_truck(raw_fraction=0.30)
    validate_success(api.set_crew_status(ctx["crew"]["id"], {"status": "OFF_DUTY"}, ADMIN))
    crew_v = get_crew_version(ctx["crew"]["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_OFF_DUTY.value)


def test_activate_blocked_when_crew_off_duty(api):
    """PRD §3.6: "Activation requires the dispatch to be `RESERVED` (otherwise
    `ERR_DISPATCH_NOT_RESERVED`) and the crew to be `ON_DUTY` (otherwise
    `ERR_CREW_OFF_DUTY`)".

    Reserve a dispatch, then set the crew OFF_DUTY before activating.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_crew_off_duty
    """
    ctx = setup_scheduled_job(raw_fraction=0.10)
    validate_success(api.set_crew_status(ctx["crew"]["id"], {"status": "OFF_DUTY"}, ADMIN))
    resp = api.activate_dispatch(ctx["dispatch"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CREW_OFF_DUTY.value)


# ─── resource_temporal_overlap ────────────────────────

def test_crew_buffer_gap_violation_rejected(api):
    """PRD §3.4: "The window must keep a gap of at least the crew's `buffer_minutes` from
    every other window currently held by that crew — that is, from every dispatch on the
    crew that is `RESERVED` or `ACTIVE` (otherwise `ERR_CREW_WINDOW_CONFLICT`)."

    First window 09:00-10:00 on the crew; a second window 10:15-11:00 leaves only a 15-min
    gap, less than the crew's 30-min buffer, so it is rejected even though the raw
    intervals do not intersect. (Distinct trucks so the truck guard cannot fire first.)

    Design: Difficulty/resource_temporal_overlap/crew_buffer_gap_overlap_rejected
    """
    policy = create_policy()
    cust = create_customer()
    crew = create_crew(buffer_minutes=30)
    truck_a = create_truck()
    truck_b = create_truck()
    # Job A scheduled 09:00-10:00.
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    crew_v0 = get_crew_version(crew["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew["id"], truck_a["id"], crew_v0,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    # Job B estimated, awaiting dispatch 10:15-11:00 (gap 15 < 30).
    job_b = create_job(cust["id"])
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew_v1 = get_crew_version(crew["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew["id"], truck_b["id"], crew_v1,
            window_start_utc="2026-06-10T10:15:00.000Z", window_end_utc="2026-06-10T11:00:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value)


def test_crew_buffer_gap_exactly_met_is_allowed(api):
    """PRD §3.4: "The window must keep a gap of at least the crew's `buffer_minutes` from
    every other window currently held by that crew — that is, from every dispatch on the
    crew that is `RESERVED` or `ACTIVE` (otherwise `ERR_CREW_WINDOW_CONFLICT`)."

    First window 09:00-10:00; a second window starting 10:30 leaves a gap of exactly the
    crew's 30-minute buffer, which satisfies the "at least buffer_minutes" rule, so the
    reservation is allowed. (Distinct trucks so the truck guard cannot interfere.)

    Design: Difficulty/resource_temporal_overlap/crew_buffer_gap_overlap_rejected
    """
    create_policy()
    cust = create_customer()
    crew = create_crew(buffer_minutes=30)
    truck_a = create_truck()
    truck_b = create_truck()
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    crew_v0 = get_crew_version(crew["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew["id"], truck_a["id"], crew_v0,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    job_b = create_job(cust["id"])
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew_v1 = get_crew_version(crew["id"])
    disp_b = validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew["id"], truck_b["id"], crew_v1,
            window_start_utc="2026-06-10T10:30:00.000Z", window_end_utc="2026-06-10T11:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    assert disp_b["dispatch_status"] == "RESERVED", f"dispatch_status={disp_b['dispatch_status']}"


def test_truck_halfopen_overlap_rejected(api):
    """PRD §3.4: "And the window must not intersect, under half-open interval semantics,
    any window currently held by that truck — any dispatch on the truck that is
    `RESERVED` or `ACTIVE` (otherwise `ERR_TRUCK_WINDOW_CONFLICT`)."

    Same truck, two crews (so the crew buffer is irrelevant): first window 09:00-10:00,
    second 09:30-10:30 intersects, so it is rejected with ERR_TRUCK_WINDOW_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/truck_halfopen_adjacency_allowed_but_overlap_rejected
    """
    create_policy()
    cust = create_customer()
    crew1 = create_crew()
    crew2 = create_crew()
    truck = create_truck()
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    crew1_v = get_crew_version(crew1["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew1["id"], truck["id"], crew1_v,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    job_b = create_job(cust["id"])
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew2_v = get_crew_version(crew2["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew2["id"], truck["id"], crew2_v,
            window_start_utc="2026-06-10T09:30:00.000Z", window_end_utc="2026-06-10T10:30:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value)


def test_truck_halfopen_adjacent_window_allowed(api):
    """PRD §3.4: "the window must not intersect, under half-open interval semantics, any
    window currently held by that truck".

    Under half-open [start,end) semantics a second window on the same truck that starts
    exactly when the first ends (10:00) does NOT intersect, so it is allowed.

    Design: Difficulty/resource_temporal_overlap/truck_halfopen_adjacency_allowed_but_overlap_rejected
    """
    create_policy()
    cust = create_customer()
    crew1 = create_crew()
    crew2 = create_crew()
    truck = create_truck()
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    crew1_v = get_crew_version(crew1["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew1["id"], truck["id"], crew1_v,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    job_b = create_job(cust["id"])
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew2_v = get_crew_version(crew2["id"])
    disp_b = validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew2["id"], truck["id"], crew2_v,
            window_start_utc="2026-06-10T10:00:00.000Z", window_end_utc="2026-06-10T11:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    assert disp_b["dispatch_status"] == "RESERVED", f"dispatch_status={disp_b['dispatch_status']}"


# ─── corner: validations ──────────────────────────────

def test_load_fraction_above_one_returns_invalid_fraction(api):
    """PRD §2.7: "The one structural rule that carries its own distinct code is the
    on-site load fraction: a `measured_truck_fraction` that is not greater than 0 and at
    most 1.0 is rejected with `ERR_INVALID_FRACTION`."

    Design: Corner/validations/load_fraction_above_one_returns_invalid_fraction
    """
    from test_helpers import setup_on_site_job, make_crew_lead_headers
    ctx = setup_on_site_job(raw_fraction=0.10)
    resp = api.load_haul_job(
        ctx["job"]["id"], {"measured_truck_fraction": 1.5}, make_crew_lead_headers(ctx["crew"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FRACTION.value)


def test_dispatch_window_end_before_start_returns_invalid_request(api):
    """PRD §2.7: "a dispatch's `window_end_utc` is strictly later than its
    `window_start_utc`; ... Any violation of these structural rules is
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/dispatch_window_end_before_start_returns_invalid_request
    """
    ctx = setup_estimated_job_with_crew_truck(raw_fraction=0.10)
    crew_v = get_crew_version(ctx["crew"]["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v,
            window_start_utc="2026-06-10T10:00:00.000Z", window_end_utc="2026-06-10T09:00:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_dispatch_truck_out_of_service_returns_truck_out_of_service(api):
    """PRD §3.4: "the truck must be `IN_SERVICE` (otherwise `ERR_TRUCK_OUT_OF_SERVICE`)."

    Design: Corner/validations/dispatch_truck_out_of_service_returns_truck_out_of_service
    """
    ctx = setup_estimated_job_with_crew_truck(raw_fraction=0.10)
    validate_success(api.set_truck_status(ctx["truck"]["id"], {"status": "OUT_OF_SERVICE"}, ADMIN))
    crew_v = get_crew_version(ctx["crew"]["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v),
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRUCK_OUT_OF_SERVICE.value)


def test_dispatch_exceeding_credit_limit_returns_payment_required(api):
    """PRD §2.9: "When a dispatch is created or a job is completed, the platform checks
    that the customer's current outstanding balance plus the new exposure would not
    exceed the credit limit; if it would, the operation is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    estimated_total for raw 0.30 (billed 0.375, no items) = 21750 exceeds a 10000 credit
    limit on a customer with 0 balance.

    Design: Corner/validations/dispatch_credit_limit_exceeded_returns_402
    """
    create_policy()
    cust = create_customer(credit_limit_cents=10000)
    crew = create_crew()
    truck = create_truck()
    job = create_job(cust["id"])
    est = submit_estimate(job["id"], cust["id"], raw_fraction=0.30)
    accept_estimate(job["id"], est["id"], cust["id"])
    crew_v = get_crew_version(crew["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(job["id"], crew["id"], truck["id"], crew_v), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


def test_dispatch_window_outside_shift_returns_outside_shift(api):
    """PRD §3.4: "The pickup window must lie entirely within the crew's shift — its start
    at or after `shift_start_utc` and its end at or before `shift_end_utc` (otherwise
    `ERR_WINDOW_OUTSIDE_SHIFT`)."

    Crew shift 08:00-18:00; window 19:00-20:00 lies outside, and the job carries no freon
    item so the safety guard cannot pre-empt the temporal guard.

    Design: Corner/validations/window_outside_shift_returns_outside_shift
    """
    ctx = setup_estimated_job_with_crew_truck(raw_fraction=0.10, crew_overrides={"hazmat_certified": True})
    crew_v = get_crew_version(ctx["crew"]["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(
            ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v,
            window_start_utc="2026-06-10T19:00:00.000Z", window_end_utc="2026-06-10T20:00:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_SHIFT.value)


# ─── corner: optimistic concurrency ───────────────────

def test_dispatch_with_stale_crew_version_rejected(api):
    """PRD §2.10: "When a dispatch is created, the request must carry
    `expected_crew_version` holding the client's last observed `version` of the target
    `Crew`. If that value does not match the crew's current `version` ... the create is
    rejected with `ERR_STALE_CREW_VERSION` (HTTP 412)."

    A first dispatch bumps the crew's version; a second create still carrying the pre-bump
    version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_stale_crew_version_rejected
    """
    create_policy()
    cust = create_customer()
    crew = create_crew()
    truck_a = create_truck()
    truck_b = create_truck()
    job_a = create_job(cust["id"])
    est_a = submit_estimate(job_a["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_a["id"], est_a["id"], cust["id"])
    job_b = create_job(cust["id"])
    est_b = submit_estimate(job_b["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job_b["id"], est_b["id"], cust["id"])
    crew_v0 = get_crew_version(crew["id"])
    validate_success(api.create_dispatch(
        create_dispatch_payload(
            job_a["id"], crew["id"], truck_a["id"], crew_v0,
            window_start_utc="2026-06-10T09:00:00.000Z", window_end_utc="2026-06-10T10:00:00.000Z",
        ), DISPATCHER), expected_status=201)
    resp = api.create_dispatch(
        create_dispatch_payload(
            job_b["id"], crew["id"], truck_b["id"], crew_v0,
            window_start_utc="2026-06-10T11:00:00.000Z", window_end_utc="2026-06-10T12:00:00.000Z",
        ), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_CREW_VERSION.value)


def test_revise_with_stale_job_version_rejected(api):
    """PRD §2.10: "When a scheduled job is revised, the request must carry
    `expected_job_version` holding the client's last observed `version` of the target
    `HaulJob`. If that value does not match the job's current `version` ... the revise is
    rejected with `ERR_STALE_JOB_VERSION` (HTTP 412)."

    Carry a deliberately stale version (current - 1).

    Design: Corner/cross_cutting_complexity_layers/occ_revise_stale_job_version_rejected
    """
    ctx = setup_scheduled_job(raw_fraction=0.10)
    job_v = validate_success(
        api.get_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    )["version"]
    resp = api.revise_haul_job(
        ctx["job"]["id"], {"expected_job_version": job_v - 1}, make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_JOB_VERSION.value)
