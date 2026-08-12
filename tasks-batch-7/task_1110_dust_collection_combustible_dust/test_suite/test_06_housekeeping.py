"""Housekeeping programs and audits: schedule posture, threshold snapshotting,
clock-driven OVERDUE cascades, and audit due-ness."""
from test_helpers import (
    ApiErrorId,
    assert_housekeeping_audit,
    assert_housekeeping_program,
    create_audit,
    create_housekeeping_program,
    create_site,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import make_housekeeping_auditor_headers

ENGINEER = TEST_USERS["compliance_engineer_headers"]


def test_never_audited_program_is_overdue(api):
    """PRD §3.5: "If `last_audit_at` is null — the program has never been
    audited — `current_posture` is `OVERDUE` (a never-audited program is
    non-compliant by definition) and `next_due_at` remains null."

    Design: Corner/calculations/housekeeping_schedule_no_audits_is_overdue
    """
    site = create_site(insurer_id="FM-1")
    program = create_housekeeping_program(
        site["id"], name="P", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    assert_housekeeping_program(program)

    after = validate_success(
        api.get_housekeeping_program(site["id"], program["id"], ENGINEER), 200)
    assert after["current_posture"] == "OVERDUE"
    assert after["next_due_at"] is None


def test_audit_pass_uses_snapshotted_threshold(api):
    """PRD §3.5: "At creation the system snapshots the program's current
    `target_accumulation_g_per_m2` into the audit's
    `pass_threshold_g_per_m2` field — so a later change to the program target
    does not retroactively alter the pass criterion for an audit already on
    the books."
    PRD §3.5: "computes `pass` as true exactly when
    `measured_accumulation_g_per_m2` is less than or equal to
    `pass_threshold_g_per_m2`".

    Measured 1.5 against a snapshotted threshold of 1.0 fails.

    Design: Corner/calculations/housekeeping_audit_pass_threshold_uses_snapshot
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site(insurer_id="FM-1")
    program = create_housekeeping_program(
        site["id"], name="P", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    audit = create_audit(site["id"], program["id"], "2026-05-01T00:00:00Z",
                         auditor_id="aud-1", measured_accumulation_g_per_m2=1.5)

    res = api.record_housekeeping_audit(
        site["id"], program["id"], audit["id"],
        make_housekeeping_auditor_headers("aud-1"))
    recorded = validate_success(res, 200)
    assert_housekeeping_audit(recorded)
    assert recorded["pass_threshold_g_per_m2"] == 1.0
    assert recorded["pass"] is False
    assert recorded["status"] == "RECORDED"


def test_overdue_audit_increments_site_counter(api):
    """PRD §3.5: "When the current clock advances past `scheduled_for +
    frequency_hours` hours and the audit is still in `SCHEDULED`, the system
    auto-transitions the audit to `OVERDUE`. This transition increments the
    Site's `open_overdue_housekeeping` counter by 1 and recomputes the site
    posture."
    PRD §2.11: "Advancing the clock triggers any system-initiated transitions
    whose preconditions have become true: HousekeepingAudits that should flip
    to `OVERDUE`".

    Audit scheduled 2026-05-02T00:00 under a 24-hour program goes overdue once
    the clock reaches 2026-05-04T00:00.

    Design: Difficulty/transitive_cascade/overdue_housekeeping_audit_cascades_to_posture_change
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    program = create_housekeeping_program(
        site["id"], name="HKP", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    audit = create_audit(site["id"], program["id"], "2026-05-02T00:00:00Z",
                         auditor_id="aud-1", measured_accumulation_g_per_m2=0.5)

    set_clock("2026-05-04T00:00:00Z")

    audit_after = validate_success(
        api.get_housekeeping_audit(site["id"], program["id"], audit["id"],
                                   ENGINEER), 200)
    assert audit_after["status"] == "OVERDUE"

    site_after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert site_after["open_overdue_housekeeping"] == 1


def test_overdue_audit_recomputes_posture_score(api):
    """PRD §2.4: "10 points for each overdue housekeeping audit at the site,
    counting at most 3 such audits,".
    PRD §2.4: "a `posture_score` of at least 85 yields `COMPLIANT`".
    PRD §3.1: "An administrative `recompute_posture` action (restricted to
    `PlatformAdmin` and `ComplianceManager`) forces the site-posture derivation
    to run against the current counters".

    One overdue audit drops the score to 90, which is still the COMPLIANT band.

    Design: Difficulty/transitive_cascade/overdue_housekeeping_audit_cascades_to_posture_change
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    program = create_housekeeping_program(
        site["id"], name="HKP", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    create_audit(site["id"], program["id"], "2026-05-02T00:00:00Z",
                 auditor_id="aud-1", measured_accumulation_g_per_m2=0.5)

    set_clock("2026-05-04T00:00:00Z")
    admin = TEST_USERS["platform_admin_headers"]
    validate_success(api.recompute_posture(site["id"], admin), 200)

    site_after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert site_after["open_overdue_housekeeping"] == 1
    assert site_after["posture_score"] == 90
    assert site_after["posture"] == "COMPLIANT"


def test_record_future_audit_rejected_not_due(api):
    """PRD §3.5: "The transition from `SCHEDULED` to `RECORDED` requires that
    `scheduled_for` is not in the future relative to the current clock; an
    audit whose scheduled time has not yet arrived is rejected with
    `ERR_AUDIT_NOT_DUE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/housekeeping_audit_scheduling_aggregate_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    program = create_housekeeping_program(
        site["id"], name="P", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    audit = create_audit(site["id"], program["id"], "2026-05-03T00:00:00Z",
                         auditor_id="aud-1", measured_accumulation_g_per_m2=0.5)

    res = api.record_housekeeping_audit(
        site["id"], program["id"], audit["id"],
        make_housekeeping_auditor_headers("aud-1"))
    validate_error(res, ApiErrorId.ERR_AUDIT_NOT_DUE)

    after = validate_success(
        api.get_housekeeping_audit(site["id"], program["id"], audit["id"],
                                   ENGINEER), 200)
    assert after["status"] == "SCHEDULED"


def test_record_audit_at_exact_scheduled_time_succeeds(api):
    """PRD §3.5: "The transition from `SCHEDULED` to `RECORDED` requires that
    `scheduled_for` is not in the future relative to the current clock; an
    audit whose scheduled time has not yet arrived is rejected with
    `ERR_AUDIT_NOT_DUE` (HTTP 422)."
    PRD §3.5: "computes `pass` as true exactly when
    `measured_accumulation_g_per_m2` is less than or equal to
    `pass_threshold_g_per_m2`".

    At the exact scheduled instant the audit is no longer in the future, so
    recording succeeds; 0.5 <= 1.0 passes.

    Design: Difficulty/resource_temporal_overlap/housekeeping_audit_scheduling_aggregate_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    program = create_housekeeping_program(
        site["id"], name="P", target_accumulation_g_per_m2=1.0,
        frequency_hours=24)
    audit = create_audit(site["id"], program["id"], "2026-05-01T00:00:00Z",
                         auditor_id="aud-1", measured_accumulation_g_per_m2=0.5)

    res = api.record_housekeeping_audit(
        site["id"], program["id"], audit["id"],
        make_housekeeping_auditor_headers("aud-1"))
    recorded = validate_success(res, 200)
    assert recorded["status"] == "RECORDED"
    assert recorded["pass"] is True
