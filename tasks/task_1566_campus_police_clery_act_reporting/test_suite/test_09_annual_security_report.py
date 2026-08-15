"""Annual Security Report tests: compilation variants, cascades, OCC (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_classified_incident, create_under_classification_incident,
    create_offense_count_payload, create_classify_payload, create_asr, compile_asr,
    create_compiled_asr, create_published_asr, list_current_statistic_lines,
    classify_incident, get_log_entry_for_incident,
    ApiErrorId, assert_asr, assert_statistic_line, NON_EXISTENT_UUID, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _lines_by_cell(lines_payload):
    rows = lines_payload if isinstance(lines_payload, list) else lines_payload.get("items", lines_payload)
    return {(l["offense_type"], l["geography_column"]): l for l in rows}


def test_asr_compilation_provisional_vs_final(api):
    """PRD §3.5: "A `FINAL` compile includes only incidents in `CLASSIFIED`
    status and, on success, sets the report's `final_compile_done` true. A
    `PROVISIONAL` compile additionally includes incidents in
    `UNDER_RECLASSIFICATION`, counted at their last known offense rows."

    Design: Difficulty/dual_variant_calc/asr_compilation_provisional_vs_final
    """
    geography = create_geography(name="Main Quad", category="ON_CAMPUS")
    incident_a = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-03-10T09:00:00Z", occurred_at="2026-03-10T02:00:00Z",
    )
    # Incident B: classified with ROBBERY, then moved to UNDER_RECLASSIFICATION.
    incident_b = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        reported_at="2026-04-05T11:00:00Z", occurred_at="2026-04-05T01:00:00Z",
    )
    incident_b = validate_success(api.begin_reclassification(incident_b["id"], COORD), 200)
    assert incident_b["status"] == "UNDER_RECLASSIFICATION"

    asr = create_asr(report_year=2026)

    # PROVISIONAL compile: both incidents count.
    asr = compile_asr(asr, variant="PROVISIONAL")
    assert asr["statistics_version"] == 1
    prov_lines = get_success_data(api.list_statistic_lines(
        asr["id"], COORD,
        params={"compilation_variant": "PROVISIONAL", "statistics_version": 1},
    ))
    prov_map = _lines_by_cell(prov_lines)
    assert prov_map[("BURGLARY", "ON_CAMPUS")]["count"] == 1
    assert prov_map[("ROBBERY", "ON_CAMPUS")]["count"] == 1, (
        "PROVISIONAL includes UNDER_RECLASSIFICATION incidents at last known rows"
    )

    # FINAL compile: only the still-CLASSIFIED incident A counts.
    asr = compile_asr(asr, variant="FINAL")
    assert asr["statistics_version"] == 2
    assert asr["final_compile_done"] is True
    final_lines = get_success_data(api.list_statistic_lines(
        asr["id"], COORD,
        params={"compilation_variant": "FINAL", "statistics_version": 2},
    ))
    final_map = _lines_by_cell(final_lines)
    assert final_map[("BURGLARY", "ON_CAMPUS")]["count"] == 1
    assert all(l["offense_type"] != "ROBBERY" for l in final_map.values()), (
        "FINAL excludes UNDER_RECLASSIFICATION incidents entirely"
    )


def test_asr_provisional_excludes_draft_incidents(api):
    """PRD §3.5: "Incidents in `DRAFT`, `SUBMITTED`, `UNDER_CLASSIFICATION`,
    `UNFOUNDED`, or `WITHDRAWN` are excluded from both variants, always."

    Design: Difficulty/dual_variant_calc/asr_compilation_provisional_vs_final
    """
    geography = create_geography(name="Main Quad North", category="ON_CAMPUS")
    # One incident left UNDER_CLASSIFICATION — excluded from both variants.
    create_under_classification_incident(
        geography["id"],
        reported_at="2026-03-11T09:00:00Z", occurred_at="2026-03-11T02:00:00Z",
    )
    asr = create_asr(report_year=2026)

    asr = compile_asr(asr, variant="PROVISIONAL")
    lines = get_success_data(api.list_statistic_lines(
        asr["id"], COORD, params={"compilation_variant": "PROVISIONAL"}
    ))
    line_rows = lines if isinstance(lines, list) else lines.get("items", lines)
    assert len(line_rows) == 0, (
        "UNDER_CLASSIFICATION incidents are excluded from PROVISIONAL compiles"
    )


def test_unfound_cascade_depth3(api):
    """PRD §3.5: "When an incident is unfounded, three links fire in order: the
    incident's log entry is set to `disposition` `UNFOUNDED` with `is_public`
    false and `last_disposition_change_at` refreshed; because the log entry
    mutated, the ASR covering the incident's year, if its `statistics_version`
    is greater than 0, gets `statistics_stale` true; and because
    `statistics_stale` flipped true, all of that report's `CURRENT` statistic
    lines become `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/unfound_cascade_depth3
    """
    geography = create_geography(name="North Hall", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="AGGRAVATED_ASSAULT")],
        reported_at="2026-03-03T12:00:00Z", occurred_at="2026-03-03T11:00:00Z",
    )
    asr = create_asr(report_year=2026)
    asr = compile_asr(asr, variant="FINAL")
    assert asr["statistics_version"] == 1
    current_before = list_current_statistic_lines(asr["id"])
    assert len(current_before) == 1 and current_before[0]["status"] == "CURRENT"

    unfounded = validate_success(api.unfound_incident(
        incident["id"],
        {"justification": "Sworn investigation found the report was fabricated"},
        CHIEF,
    ), 200)
    assert unfounded["status"] == "UNFOUNDED"

    # Link 1: log entry disposition and public visibility.
    entry = get_log_entry_for_incident(incident["id"], headers=COORD)
    assert entry["disposition"] == "UNFOUNDED"
    assert entry["is_public"] is False

    # Link 2: ASR staleness flip caused by the log-entry mutation.
    asr_after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert asr_after["statistics_stale"] is True

    # Link 3: every statistic line superseded by the staleness flip.
    lines_after = get_success_data(api.list_statistic_lines(asr["id"], COORD))
    line_rows = lines_after if isinstance(lines_after, list) else lines_after.get("items", lines_after)
    assert len(line_rows) >= 1
    assert all(l["status"] == "SUPERSEDED" for l in line_rows), (
        "All CURRENT statistic lines must flip to SUPERSEDED on the unfound cascade"
    )


def test_unfound_cascade_excludes_offense_rows(api):
    """PRD §3.5: "All of the incident's offense rows become
    `EXCLUDED_UNFOUNDED`."

    Design: Difficulty/transitive_cascade/unfound_cascade_depth3
    """
    geography = create_geography(name="North Hall West", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="AGGRAVATED_ASSAULT")],
        reported_at="2026-03-04T12:00:00Z", occurred_at="2026-03-04T11:00:00Z",
    )
    validate_success(api.unfound_incident(
        incident["id"], {"justification": "Fabricated report confirmed"}, CHIEF
    ), 200)

    offenses = get_success_data(api.list_offense_counts(incident["id"], COORD))
    offense_rows = offenses if isinstance(offenses, list) else offenses.get("items", offenses)
    assert len(offense_rows) == 1
    assert offense_rows[0]["status"] == "EXCLUDED_UNFOUNDED"


def test_reclassification_count_conservation(api):
    """PRD §3.3: "Classification replaces the incident's entire prior offense
    row set with the submitted set."
    PRD §3.5: "on success increments `statistics_version` by one, sets
    `statistics_stale` false, stamps `compiled_at`, and increments the
    report's `version`."

    Design: Difficulty/compensating_invariant/reclassification_count_conservation
    """
    geography = create_geography(name="East Walk", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        reported_at="2026-03-22T10:00:00Z", occurred_at="2026-03-22T09:00:00Z",
    )
    asr = create_asr(report_year=2026)
    asr = compile_asr(asr, variant="FINAL")
    baseline = _lines_by_cell(list_current_statistic_lines(
        asr["id"], params={"compilation_variant": "FINAL"}
    ))
    assert sum(l["count"] for l in baseline.values()) == 1
    assert ("ROBBERY", "ON_CAMPUS") in baseline

    # Forward reclassification: ROBBERY -> BURGLARY, then recompile.
    incident = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    incident = classify_incident(
        incident, geography["id"],
        [create_offense_count_payload(offense_type="BURGLARY")],
    )
    asr = validate_success(api.get_asr(asr["id"], COORD), 200)
    asr = compile_asr(asr, variant="FINAL")
    forward = _lines_by_cell(list_current_statistic_lines(
        asr["id"], params={"compilation_variant": "FINAL"}
    ))
    assert sum(l["count"] for l in forward.values()) == 1
    assert forward[("BURGLARY", "ON_CAMPUS")]["count"] == 1
    assert all(l["offense_type"] != "ROBBERY" for l in forward.values())

    # Compensating reclassification: BURGLARY -> ROBBERY, then recompile.
    incident = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    incident = classify_incident(
        incident, geography["id"],
        [create_offense_count_payload(offense_type="ROBBERY")],
    )
    asr = validate_success(api.get_asr(asr["id"], COORD), 200)
    asr = compile_asr(asr, variant="FINAL")
    final_lines = _lines_by_cell(list_current_statistic_lines(
        asr["id"], params={"compilation_variant": "FINAL"}
    ))
    assert sum(l["count"] for l in final_lines.values()) == 1, (
        "The compensation round-trip must conserve the total offense count"
    )
    assert final_lines[("ROBBERY", "ON_CAMPUS")]["count"] == 1
    assert asr["statistics_version"] == 3
    assert asr["statistics_stale"] is False


def test_reclassification_marks_prior_lines_superseded(api):
    """PRD §3.3: "When a reclassification succeeds and an Annual Security
    Report for the calendar year of `occurred_at` exists in `COLLECTING` or
    `UNDER_AMENDMENT` status with a `statistics_version` greater than 0, that
    report's `statistics_stale` flag is set true and all of its `CURRENT`
    statistic lines are flipped to `SUPERSEDED`, signaling that the published
    pipeline has drifted from the underlying data."

    Design: Difficulty/compensating_invariant/reclassification_count_conservation
    """
    geography = create_geography(name="East Walk South", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        reported_at="2026-03-23T10:00:00Z", occurred_at="2026-03-23T09:00:00Z",
    )
    asr = create_asr(report_year=2026)
    asr = compile_asr(asr, variant="FINAL")

    incident = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    classify_incident(
        incident, geography["id"],
        [create_offense_count_payload(offense_type="BURGLARY")],
    )

    asr_after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert asr_after["statistics_stale"] is True, (
        "Reclassification of an incident whose year has a compiled ASR flips staleness"
    )
    lines = get_success_data(api.list_statistic_lines(asr["id"], COORD))
    line_rows = lines if isinstance(lines, list) else lines.get("items", lines)
    assert len(line_rows) >= 1
    assert all(l["status"] == "SUPERSEDED" for l in line_rows)


def test_occ_stale_version_on_compile_returns_412(api):
    """PRD §2.5: "Compiling an Annual Security Report requires
    `expected_report_version` equal to the report's current `version`; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a
    successful compile supersedes the prior statistics snapshot and a caller
    holding a stale version must not overwrite a snapshot it never saw."

    Design: Corner/complexity_layers/occ_stale_version_on_compile_returns_412
    """
    asr = create_asr(report_year=2026)
    stale_version = asr["version"]

    compiled = compile_asr(asr, variant="FINAL")
    assert compiled["version"] == stale_version + 1
    assert compiled["statistics_version"] == 1

    res = api.compile_asr(
        asr["id"],
        {"variant": "FINAL", "expected_report_version": stale_version},
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert after["statistics_version"] == 1, (
        "A stale compile must not advance statistics_version"
    )


def test_statistic_lines_filtered_by_column(api):
    """PRD §3.5: "Statistic lines are queryable with `compilation_variant`,
    `geography_column`, `offense_type`, and `statistics_version` filters,
    defaulting to the current snapshot."
    PRD §3.5: "an `ON_CAMPUS_RESIDENTIAL` incident increments both the
    `ON_CAMPUS` and the `ON_CAMPUS_RESIDENTIAL` columns (on-campus residential
    counts are a subset of on-campus counts)."

    Design: Corner/endpoints/statistic_lines_filtered_by_column
    """
    geography = create_geography(
        name="Hall F", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-02-10T09:00:00Z", occurred_at="2026-02-10T08:00:00Z",
    )
    asr = create_asr(report_year=2026)
    compile_asr(asr, variant="FINAL")

    residential = get_success_data(api.list_statistic_lines(
        asr["id"], COORD, params={"geography_column": "ON_CAMPUS_RESIDENTIAL"}
    ))
    residential_rows = residential if isinstance(residential, list) else residential.get("items", residential)
    assert len(residential_rows) == 1
    assert residential_rows[0]["offense_type"] == "BURGLARY"
    assert residential_rows[0]["count"] == 1

    non_campus = get_success_data(api.list_statistic_lines(
        asr["id"], COORD, params={"geography_column": "NON_CAMPUS"}
    ))
    non_campus_rows = non_campus if isinstance(non_campus, list) else non_campus.get("items", non_campus)
    assert len(non_campus_rows) == 0


def test_duplicate_asr_year_rejected(api):
    """PRD §3.5: "An `AnnualSecurityReport` shell is created by a `SystemAdmin`
    for a given `report_year`, which must be unique across all ASRs — a
    duplicate year is rejected with `ERR_DUPLICATE_REPORT_YEAR` (HTTP 409)."

    Design: Corner/validations/duplicate_asr_year_rejected
    """
    validate_success(api.create_asr({"report_year": 2026}, TEST_USERS["admin_headers"]), 201)
    res = api.create_asr({"report_year": 2026}, TEST_USERS["admin_headers"])
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REPORT_YEAR.value, expected_status=409)


def test_submit_review_before_final_compile_rejected(api):
    """PRD §3.5: "A coordinator submits the report for review — `COLLECTING →
    UNDER_REVIEW` — only after at least one successful `FINAL` compile;
    otherwise the call is rejected with `ERR_FINAL_COMPILE_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/submit_review_before_final_compile_rejected
    """
    asr = create_asr(report_year=2026)
    compile_asr(asr, variant="PROVISIONAL")

    res = api.submit_asr_review(asr["id"], COORD)
    validate_error(res, ApiErrorId.ERR_FINAL_COMPILE_REQUIRED.value, expected_status=422)

    after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert after["status"] == "COLLECTING"


def test_republish_without_recompile_returns_recompile_required(api):
    """PRD §3.5: "Republication by the chief requires a compile strictly newer
    than `amendment_started_at` — that is, `compiled_at` must be later than
    `amendment_started_at` — otherwise the call fails with
    `ERR_RECOMPILE_REQUIRED` (HTTP 422)."

    Design: Corner/state_machines/republish_without_recompile_returns_recompile_required
    """
    asr = create_published_asr(report_year=2026)
    amended = validate_success(api.begin_asr_amendment(asr["id"], COORD), 200)
    assert amended["status"] == "UNDER_AMENDMENT"

    res = api.republish_asr(asr["id"], CHIEF)
    validate_error(res, ApiErrorId.ERR_RECOMPILE_REQUIRED.value, expected_status=422)

    after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert after["status"] == "UNDER_AMENDMENT"


def test_coordinator_cannot_publish_asr(api):
    """PRD §2.1: "Segregation of duties is deliberate: the role that decides an
    alert (`CleryCoordinator`) may not authorize or disseminate it
    (`PoliceChief`), and the role that compiles a report (`CleryCoordinator`)
    may not publish it (`PoliceChief`)."

    Design: Corner/rbac/coordinator_cannot_publish_asr
    """
    asr = create_compiled_asr(report_year=2026, variant="FINAL")
    reviewed = validate_success(api.submit_asr_review(asr["id"], COORD), 200)
    assert reviewed["status"] == "UNDER_REVIEW"

    res = api.publish_asr(asr["id"], COORD)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    after = validate_success(api.get_asr(asr["id"], COORD), 200)
    assert after["status"] == "UNDER_REVIEW"
