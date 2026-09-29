"""Two interval geometries that must not share one comparison helper."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assessment_payload,
    coverage_payload,
    create_certificate,
    create_coverage,
    create_moderate_certificate,
    create_site,
    device_payload,
    read_assessment,
    read_certificate,
    read_coverage,
    read_operator,
    read_site,
    run_oversight,
    set_clock,
    setup_competent_operator,
    setup_covered_site,
    validate_error,
    validate_success,
)

# ─── coverage_window_touching_endpoint_collides_then_next_day ─────────


def _site_covered_to_the_end_of_august():
    return setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243022"},
        site_overrides={
            "name": "Coverage Geometry POCT",
            "department_code": "DEPT-300",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-08-31"},
    )


def _attach_coverage(site_id, certificate_id, coverage_start):
    return api_client.create_coverage(
        coverage_payload(
            site_id, certificate_id,
            coverage_start=coverage_start, coverage_end="2027-12-31",
        ),
        ADMIN,
    )


def test_a_window_starting_on_the_existing_end_date_collides():
    """Closed-closed geometry means the shared single day is an overlap.

    PRD 3.1: "A site may hold at most one coverage window over any given date, and
    the collision test is **closed-closed**: two windows collide when the new
    `coverage_start` is on or before an existing `coverage_end` **and** that existing
    `coverage_start` is on or before the new `coverage_end`. Touching endpoints
    therefore collide — an existing window ending 2027-12-31 and a new window starting
    2027-12-31 overlap on that single day, and the new row is rejected with
    `ERR_COVERAGE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/coverage_window_touching_endpoint_collides_then_next_day_is_accepted
    """
    certificate, site, _coverage = _site_covered_to_the_end_of_august()

    response = _attach_coverage(site["id"], certificate["id"], "2026-08-31")

    validate_error(response, "ERR_COVERAGE_WINDOW_OVERLAP", 409)


def test_a_window_starting_the_day_after_is_accepted():
    """2026-09-01 shares no day with a window ending 2026-08-31.

    PRD 3.1: "There is no buffer between windows."

    Design: Difficulty/resource_temporal_overlap/coverage_window_touching_endpoint_collides_then_next_day_is_accepted
    """
    certificate, site, coverage = _site_covered_to_the_end_of_august()
    _attach_coverage(site["id"], certificate["id"], "2026-08-31")

    accepted = validate_success(
        _attach_coverage(site["id"], certificate["id"], "2026-09-01"), 201
    )

    assert accepted["coverage_start"] == "2026-09-01"
    assert accepted["permitted_complexity_snapshot"] == "WAIVED"
    assert read_coverage(coverage["id"])["coverage_end"] == "2026-08-31"


def test_only_the_accepted_window_raises_the_covered_site_count():
    """The rejected attempt leaves the certificate's coverage tally alone.

    PRD 3.1: "On success the row pins a `permitted_complexity_snapshot` copied from
    the certificate's `permitted_complexity` at that moment — a later amendment to the
    certificate never retroactively widens or narrows a coverage already granted — the
    certificate's `covered_site_count` rises by one, and the site's posture and
    `scope_creep_flag` are re-evaluated."

    Design: Difficulty/resource_temporal_overlap/coverage_window_touching_endpoint_collides_then_next_day_is_accepted
    """
    certificate, site, _coverage = _site_covered_to_the_end_of_august()

    _attach_coverage(site["id"], certificate["id"], "2026-08-31")
    _attach_coverage(site["id"], certificate["id"], "2026-09-01")

    assert read_certificate(certificate["id"])["covered_site_count"] == 2
    assert read_site(site["id"])["oversight_posture"] == "OPEN"


# ─── competency_window_touching_endpoint_allowed_then_earlier ─────────


def _operator_with_an_approved_window_to_mid_september():
    """op_a holds an APPROVED GlucoMeter-X window over [2026-08-01, 2026-09-15)."""
    env = setup_competent_operator(
        certificate_overrides={"certificate_number": "45D2243023"},
        site_overrides={
            "name": "Competency Geometry POCT",
            "department_code": "DEPT-310",
            "complexity_scope": "WAIVED",
        },
        assessment_overrides={
            "effective_date": "2026-08-01", "expires_at": "2026-09-15",
        },
    )
    env["version_after_approval"] = read_operator(env["subject"]["id"])["version"]
    return env


def _submit(env, effective_date, expires_at, expected_version):
    return api_client.create_assessment(
        assessment_payload(
            env["subject"]["id"], env["assessor"]["id"], expected_version,
            assessment_type="ANNUAL",
            effective_date=effective_date, expires_at=expires_at,
        ),
        COORDINATOR,
    )


def test_a_window_effective_on_the_existing_expiry_is_adjacent_and_allowed():
    """Half-open geometry lets 2026-09-15 abut a window expiring 2026-09-15.

    PRD 3.3: "Competency windows for one operator and one device model may not
    overlap, and the geometry here is **half-open** on `[effective_date, expires_at)`
    — deliberately different from the closed-closed geometry of coverage windows. Two
    windows collide when the new `effective_date` falls strictly before an existing
    `expires_at` **and** that existing `effective_date` falls strictly before the new
    `expires_at`. Touching endpoints therefore do **not** collide: an existing window
    expiring 2027-03-14 and a new window effective 2027-03-14 are adjacent and both
    allowed."

    Design: Difficulty/resource_temporal_overlap/competency_window_touching_endpoint_allowed_then_one_day_earlier_collides
    """
    env = _operator_with_an_approved_window_to_mid_september()
    assert env["assessment"]["status"] == "APPROVED"

    adjacent = validate_success(
        _submit(env, "2026-09-15", "2027-09-15", env["version_after_approval"]), 201
    )

    assert adjacent["status"] == "SUBMITTED"
    assert adjacent["effective_date"] == "2026-09-15"
    assert read_operator(env["subject"]["id"])["version"] == (
        env["version_after_approval"] + 1
    )


def test_a_window_effective_one_day_earlier_collides_with_the_approved_row():
    """2026-09-14 falls strictly inside the approved window, so it is refused.

    PRD 2.7: "**Rank 68 — competency window collision.** On competency-assessment
    submission, no colliding approved competency window may exist for the same
    operator and device model. Otherwise `ERR_ASSESSMENT_WINDOW_OVERLAP` (409).
    Geometry in §3.3."

    Design: Difficulty/resource_temporal_overlap/competency_window_touching_endpoint_allowed_then_one_day_earlier_collides
    """
    env = _operator_with_an_approved_window_to_mid_september()
    _submit(env, "2026-09-15", "2027-09-15", env["version_after_approval"])
    version_now = read_operator(env["subject"]["id"])["version"]

    response = _submit(env, "2026-09-14", "2027-09-14", version_now)

    validate_error(response, "ERR_ASSESSMENT_WINDOW_OVERLAP", 409)
    assert read_operator(env["subject"]["id"])["version"] == version_now


def test_the_intervening_submitted_row_is_not_what_blocked_the_collision():
    """Only APPROVED rows are candidates, and the operator keeps its approved window.

    PRD 3.3: "Only assessments whose `status` is `APPROVED` are candidates for the
    test; rows in `SUBMITTED`, `REJECTED` or `VOIDED` never block a new submission."

    Design: Difficulty/resource_temporal_overlap/competency_window_touching_endpoint_allowed_then_one_day_earlier_collides
    """
    env = _operator_with_an_approved_window_to_mid_september()
    adjacent = validate_success(
        _submit(env, "2026-09-15", "2027-09-15", env["version_after_approval"]), 201
    )
    version_now = read_operator(env["subject"]["id"])["version"]
    _submit(env, "2026-09-14", "2027-09-14", version_now)

    assert read_assessment(adjacent["id"])["status"] == "SUBMITTED"
    operator = read_operator(env["subject"]["id"])
    assert operator["competency_status"] == "COMPETENT"
    assert operator["competency_expires_at"] == "2026-09-15"


# ─── expired_certificate_excluded_from_overlap_candidates ─────────────


def _moderate_site_whose_waiver_has_expired():
    """A MODERATE site whose only coverage sits under an EXPIRED waiver."""
    set_clock("2026-08-01T00:00:00Z")
    waiver = create_certificate(
        certificate_number="45D2243024",
        effective_date="2026-01-01", expiration_date="2026-08-31",
    )
    site = create_site(
        name="Scope Upgrade POCT", department_code="DEPT-320",
        complexity_scope="MODERATE",
    )
    old_coverage = create_coverage(
        site["id"], waiver["id"],
        coverage_start="2026-01-01", coverage_end="2026-08-31",
    )
    compliance = create_moderate_certificate(
        certificate_number="45D2243025",
        effective_date="2026-01-01", expiration_date="2027-12-31",
    )
    set_clock("2026-09-05T00:00:00Z")
    summary = run_oversight(note="September epoch")
    return waiver, site, old_coverage, compliance, summary


def test_a_replacement_window_may_fully_contain_an_expired_certificates_window():
    """The older row is retained but excluded from the collision candidate set.

    PRD 3.1: "The candidate set for this test is the site's existing coverage rows
    whose certificate has `status` of `ACTIVE` or `SUSPENDED`; rows whose certificate
    has already `EXPIRED` are excluded, so a lapsed certificate never blocks the
    replacement window that succeeds it."

    Design: Difficulty/resource_temporal_overlap/expired_certificate_excluded_from_overlap_candidates_unlocks_moderate_scope
    """
    waiver, site, old_coverage, compliance, summary = (
        _moderate_site_whose_waiver_has_expired()
    )

    assert summary["certificates_expired"] == 1
    assert summary["sites_posture_changed"] == 1
    assert read_certificate(waiver["id"])["status"] == "EXPIRED"
    assert read_coverage(old_coverage["id"])[
        "permitted_complexity_snapshot"
    ] == "WAIVED"

    replacement = validate_success(
        api_client.create_coverage(
            coverage_payload(
                site["id"], compliance["id"],
                coverage_start="2026-01-01", coverage_end="2027-12-31",
            ),
            ADMIN,
        ),
        201,
    )

    assert replacement["permitted_complexity_snapshot"] == "MODERATE"
    assert read_coverage(old_coverage["id"])["coverage_end"] == "2026-08-31"


def test_the_wider_snapshot_lets_a_moderate_instrument_be_installed():
    """The new in-window snapshot is what makes the MODERATE install legal.

    PRD 3.4: "A `WAIVED` instrument then installs freely, but a `MODERATE` one
    requires that in-window coverage to carry a `permitted_complexity_snapshot` of
    `MODERATE`; otherwise the installation is refused with
    `ERR_COMPLEXITY_SCOPE_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/expired_certificate_excluded_from_overlap_candidates_unlocks_moderate_scope
    """
    _waiver, site, _old, compliance, _summary = (
        _moderate_site_whose_waiver_has_expired()
    )
    create_coverage(
        site["id"], compliance["id"],
        coverage_start="2026-01-01", coverage_end="2027-12-31",
    )

    installed = validate_success(
        api_client.create_device(
            device_payload(
                site["id"],
                device_model="ChemAnalyzer-M", serial_number="SN-1101",
                analyte="CHEMISTRY_PANEL", complexity_class="MODERATE",
                connectivity_mode="INTERFACED", qc_frequency_days=7,
            ),
            ADMIN,
        ),
        201,
    )

    assert installed["status"] == "ACTIVE"
    assert installed["qc_next_due_at"] == "2026-09-05"


def test_the_recovered_site_reads_open_with_no_scope_creep():
    """Regaining in-window coverage clears both the posture and the creep flag.

    PRD 3.9: "Scope creep is detected: every instrument whose `status` is `ACTIVE` and
    whose `complexity_class` is `MODERATE`, sitting at a site whose in-window active
    coverage carries a `permitted_complexity_snapshot` of `WAIVED`, moves to
    `QC_LOCKED` with `qc_lock_reason` of `CERTIFICATE_SCOPE`, and the site's
    `scope_creep_flag` is set true."

    Design: Difficulty/resource_temporal_overlap/expired_certificate_excluded_from_overlap_candidates_unlocks_moderate_scope
    """
    _waiver, site, _old, compliance, _summary = (
        _moderate_site_whose_waiver_has_expired()
    )
    create_coverage(
        site["id"], compliance["id"],
        coverage_start="2026-01-01", coverage_end="2027-12-31",
    )
    api_client.create_device(
        device_payload(
            site["id"],
            device_model="ChemAnalyzer-M", serial_number="SN-1101",
            analyte="CHEMISTRY_PANEL", complexity_class="MODERATE",
            connectivity_mode="INTERFACED", qc_frequency_days=7,
        ),
        ADMIN,
    )

    read_back = read_site(site["id"])
    assert read_back["scope_creep_flag"] is False
    assert read_back["oversight_posture"] == "OPEN"
    assert read_back["manual_entry_blocked"] is False
    assert read_certificate(compliance["id"])["covered_site_count"] == 1
