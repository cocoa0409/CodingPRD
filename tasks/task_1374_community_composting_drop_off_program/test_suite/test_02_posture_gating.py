"""Site posture: derived gate, boundary precision, OCC-vs-safety priority,
material season windows, drop computed fields."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contamination_report_payload,
    create_drop_payload,
    create_material_payload,
    get_site_version,
    get_success_data,
    make_participant_headers,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / posture_capacity_gte_boundary (2 tests)
# ---------------------------------------------------------------------------

def _setup_capacity_boundary(api):
    """Program ACTIVE; site capacity 100; participant with grant.

    Returns (prog_id, site_id, mat_id, part_id, grant_id, part_headers).
    """
    ids = setup_program_with_operational_site(
        site_overrides={"capacity_kg": 100})
    part = setup_verified_participant_with_grant(
        ids["prog_id"], ids["site_id"],
        grant_overrides={"bucket_quota": 50})
    return ids, part


def test_posture_watch_at_99_then_suspended_at_capacity(api):
    """PRD §2.7: "Otherwise, if the site's available on-site mass — `stored_kg`
    minus `pending_pickup_kg` — is greater than or equal to `capacity_kg`,
    posture is `SUSPENDED`."
    PRD §2.7: "The boundary itself triggers: available mass exactly equal to
    capacity is full."
    PRD §2.7: "Otherwise, posture is `WATCH` if any one of three conditions
    holds: available on-site mass is at least 80 percent of `capacity_kg`"

    Design: Difficulty/boundary_precision_check/posture_capacity_gte_boundary
    """
    ids, part = _setup_capacity_boundary(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    ph = part["part_headers"]

    # 99.00 kg -> WATCH (99 >= ceil(0.8*100)=80 but < 100)
    sv0 = get_site_version(prog_id, site_id)
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv0,
                            gross_weight_kg=99.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        ph), expected_status=201)
    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "WATCH", (
        f"99.00/100 kg must be WATCH, got {site['posture']}")

    # +1.00 kg (<= 5 kg, allowed at WATCH) -> exactly 100.00 -> SUSPENDED
    sv1 = site["version"]
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv1,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T11:00:00Z"),
        ph), expected_status=201)
    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "SUSPENDED", (
        f"100.00/100 kg must be SUSPENDED (>= boundary), got {site['posture']}")


def test_suspended_site_at_capacity_rejects_next_drop(api):
    """PRD §2.7: "a site at `SUSPENDED` or `CLOSED` rejects every drop with
    `ERR_SITE_POSTURE_BLOCKS_DROP` (HTTP 409)."
    PRD §2.7: "Otherwise, if the site's available on-site mass — `stored_kg`
    minus `pending_pickup_kg` — is greater than or equal to `capacity_kg`,
    posture is `SUSPENDED`."
    PRD §2.7: "The boundary itself triggers: available mass exactly equal to
    capacity is full."

    Design: Difficulty/boundary_precision_check/posture_capacity_gte_boundary
    """
    ids, part = _setup_capacity_boundary(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    ph = part["part_headers"]

    sv0 = get_site_version(prog_id, site_id)
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv0,
                            gross_weight_kg=99.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        ph), expected_status=201)
    sv1 = get_site_version(prog_id, site_id)
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv1,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T11:00:00Z"),
        ph), expected_status=201)

    # Site now at exactly 100.00 -> SUSPENDED; next drop rejected.
    sv2 = get_site_version(prog_id, site_id)
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv2,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T12:00:00Z"),
        ph)
    validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKS_DROP)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             occ_state_vs_business_safety_priority (2 tests)
# ---------------------------------------------------------------------------

def _setup_suspended_site_with_stale_version(api):
    """Program with posture_contam_threshold=1; two MAJOR site-wide reports
    push the site to SUSPENDED (2 >= 2*1). Returns stale and fresh site
    versions plus context."""
    ids = setup_program_with_operational_site(
        program_overrides={"posture_contam_threshold": 1})
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    sv_stale = get_site_version(prog_id, site_id)
    for i in (1, 2):
        validate_success(api.create_contamination_report(
            prog_id, site_id,
            create_contamination_report_payload(
                severity="MAJOR", finding_note=f"site-wide plastic {i}"),
            AUDITOR), expected_status=201)

    part = setup_verified_participant_with_grant(prog_id, site_id)
    sv_fresh = get_site_version(prog_id, site_id)
    return ids, part, sv_stale, sv_fresh


def test_stale_site_version_wins_over_posture_block(api):
    """PRD §2.9: "the server evaluates them in a fixed priority order, and the
    first failure determines the error returned" — stale-version check (4)
    precedes the posture gate (6).
    PRD §2.5: "If the site's current `version` has advanced since that read —
    because another writer recorded a drop, a pickup completed, or a
    posture-affecting report or complaint landed — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Difficulty/priority_pair_validation_conflict/occ_state_vs_business_safety_priority
    """
    ids, part, sv_stale, _sv_fresh = _setup_suspended_site_with_stale_version(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv_stale,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        part["part_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_fresh_version_at_suspended_site_reaches_posture_gate(api):
    """PRD §2.9: "Posture gate on drop creation: site posture must be `OPEN`
    (or `WATCH` with a drop of at most 5 kg gross) — otherwise
    `ERR_SITE_POSTURE_BLOCKS_DROP` (HTTP 409)."
    PRD §2.9: "the first failure determines the error returned" — with a fresh
    version, the stale-version check passes and the posture gate fires.

    Design: Difficulty/priority_pair_validation_conflict/occ_state_vs_business_safety_priority
    """
    ids, part, _sv_stale, sv_fresh = _setup_suspended_site_with_stale_version(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv_fresh,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        part["part_headers"])
    validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKS_DROP)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / site_posture_capacity_vs_complaint_domains
# (2 tests)
# ---------------------------------------------------------------------------

def _setup_complaint_window_site(api):
    """Site capacity 1000 holding 100.00 kg; clock 2026-08-13; two complaints
    reported 2026-08-10 (inside the rolling 14-day window)."""
    ids = setup_program_with_operational_site(
        program_overrides={"posture_complaint_threshold": 2},
        site_overrides={"capacity_kg": 1000})
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    sv = get_site_version(prog_id, site_id)
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=100.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        part["part_headers"]), expected_status=201)

    get_success_data(api.set_clock("2026-08-13T00:00:00Z", ADMIN))
    c1 = validate_success(api.create_complaint(
        prog_id, site_id,
        {"reporter_contact": "n1", "kind": "ODOR", "description": "smell",
         "reported_at": "2026-08-10T09:00:00Z"},
        ANON), expected_status=201)
    c2 = validate_success(api.create_complaint(
        prog_id, site_id,
        {"reporter_contact": "n2", "kind": "VECTOR", "description": "flies",
         "reported_at": "2026-08-10T10:00:00Z"},
        ANON), expected_status=201)
    return ids, c1["id"], c2["id"]


def test_complaints_within_window_force_watch_posture(api):
    """PRD §2.7: "Otherwise, posture is `WATCH` if any one of three conditions
    holds: available on-site mass is at least 80 percent of `capacity_kg` (the
    capacity figure is rounded up to a whole kilogram before comparison, so
    the threshold is the ceiling of 0.8 times `capacity_kg`); the count of
    open contamination reports at the site is at least the program's
    `posture_contam_threshold`; or the number of unresolved complaints filed
    within the rolling 14-day window ending at the current logical clock is at
    least the program's `posture_complaint_threshold`."

    Design: Difficulty/dual_variant_calc/site_posture_capacity_vs_complaint_domains
    """
    ids, _c1, _c2 = _setup_complaint_window_site(api)
    site = validate_success(api.get_site(ids["prog_id"], ids["site_id"], ADMIN))
    assert site["posture"] == "WATCH", (
        f"two unresolved complaints inside the window (threshold 2) must give "
        f"WATCH, got {site['posture']}")
    assert site["stored_kg"] == pytest.approx(100.0)


def test_resolving_complaints_returns_posture_to_open(api):
    """PRD §2.7: "Otherwise, posture is `OPEN`."
    PRD §3.7: "Resolution is reachable from `OPEN`, `ACKNOWLEDGED`, or
    `REOPENED`; it moves the ticket to `RESOLVED`, stamps `resolved_at`, and
    recomputes the site's posture."

    Design: Difficulty/dual_variant_calc/site_posture_capacity_vs_complaint_domains
    """
    ids, c1, c2 = _setup_complaint_window_site(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    get_success_data(api.resolve_complaint(prog_id, site_id, c1, ADMIN))
    get_success_data(api.resolve_complaint(prog_id, site_id, c2, ADMIN))

    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "OPEN", (
        f"with both complaints resolved and 100/1000 kg stored, posture must "
        f"be OPEN, got {site['posture']}")
    assert site["stored_kg"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Corner: calculations/material_season_wrap_around_window (1 test)
# ---------------------------------------------------------------------------

def test_material_season_window_wraps_year_boundary(api):
    """PRD §3.4: "the window may wrap the year boundary: when the start
    month-day is not after the end month-day, the current date's month-day must
    fall between them inclusive; when the start is after the end (a window
    wrapping December into January), the current month-day must be at or after
    the start **or** at or before the end."
    PRD §3.4: "An inactive category or an out-of-season date fails with
    `ERR_MATERIAL_NOT_ACCEPTED`."

    Design: Corner/calculations/material_season_wrap_around_window
    """
    ids = setup_program_with_operational_site(
        material_overrides={"code": "YARD", "description": "yard waste",
                            "accepted_start_month_day": "11-01",
                            "accepted_end_month_day": "03-31"})
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)
    ph = part["part_headers"]

    # August (clock default 2026-08-01): outside 11-01..03-31 wrap window
    sv_aug = get_site_version(prog_id, site_id)
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv_aug,
                            gross_weight_kg=5.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        ph)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_ACCEPTED)

    # December: inside the wrapped window
    get_success_data(api.set_clock("2026-12-15T00:00:00Z", ADMIN))
    sv_dec = get_site_version(prog_id, site_id)
    drop = validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv_dec,
                            gross_weight_kg=5.00,
                            occurred_at="2026-12-14T10:00:00Z"),
        ph), expected_status=201)
    assert drop["verification_state"] == "PENDING_AUDIT"


# ---------------------------------------------------------------------------
# Corner: entities/drop_event_computed_provisional_net (1 test)
# ---------------------------------------------------------------------------

def test_drop_computes_provisional_net_and_initial_states(api):
    """PRD §3.4: "the drop's `provisional_net_kg` is computed as
    `gross_weight_kg` minus `contamination_kg`, rounded half-up to two decimal
    places. The drop starts with `verification_state` `PENDING_AUDIT` and
    `credit_state` `UNCREDITED`"

    Design: Corner/entities/drop_event_computed_provisional_net
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    sv = get_site_version(prog_id, site_id)
    drop = validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=7.50, contamination_kg=2.25,
                            occurred_at="2026-07-01T10:00:00Z"),
        part["part_headers"]), expected_status=201)

    assert drop["provisional_net_kg"] == pytest.approx(5.25)
    assert drop["verification_state"] == "PENDING_AUDIT"
    assert drop["credit_state"] == "UNCREDITED"
