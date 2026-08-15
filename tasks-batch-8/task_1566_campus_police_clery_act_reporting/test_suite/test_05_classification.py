"""Classification & offense hierarchy tests (PRD §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_draft_incident, create_submitted_incident,
    create_under_classification_incident, create_classified_incident,
    create_unfounded_incident,
    create_classify_payload, create_offense_count_payload, create_asr, compile_asr,
    create_published_asr, list_current_statistic_lines, classify_incident,
    ApiErrorId, assert_offense_count, NON_EXISTENT_UUID, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _offenses_by_type(offense_rows):
    rows = offense_rows if isinstance(offense_rows, list) else offense_rows.get("items", offense_rows)
    return {row["offense_type"]: row for row in rows}


def test_offense_hierarchy_exemptions_and_double_count(api):
    """PRD §3.3: "Among the remaining non-exempt offenses, the primary offense
    is the one with the smallest `hierarchy_rank` ... The primary offense and
    every exempt offense are assigned `status` `COUNTED`; all other non-exempt
    offenses are `EXCLUDED_BY_HIERARCHY`."
    PRD §3.5: "an `ON_CAMPUS_RESIDENTIAL` incident increments both the
    `ON_CAMPUS` and the `ON_CAMPUS_RESIDENTIAL` columns (on-campus residential
    counts are a subset of on-campus counts)."
    PRD §3.5: "For the three referral offense types, each cell's
    `referred_persons_count` accumulates the offense rows' `referred_persons`
    values — persons referred for disciplinary action, not incidents."

    Design: Difficulty/combinatorial_formula/offense_hierarchy_with_exemptions_and_double_count
    """
    geography = create_geography(
        name="Residence Hall A", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-02-14T08:00:00Z",
        occurred_at="2026-02-14T03:00:00Z",
    )
    classified = validate_success(api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[
                {"offense_type": "SEX_OFFENSE", "victim_count": 1},
                {"offense_type": "ROBBERY", "victim_count": 1},
                {"offense_type": "DATING_VIOLENCE", "victim_count": 1},
                {"offense_type": "DRUG_LAW_REFERRAL", "referred_persons": 3},
            ],
        ),
        COORD,
    ), 200)
    assert classified["status"] == "CLASSIFIED"

    offenses = _offenses_by_type(get_success_data(
        api.list_offense_counts(incident["id"], COORD)
    ))
    assert offenses["SEX_OFFENSE"]["status"] == "COUNTED", (
        "SEX_OFFENSE (rank 20) beats ROBBERY (rank 30) as the primary non-exempt offense"
    )
    assert offenses["SEX_OFFENSE"]["hierarchy_rank"] == 20
    assert offenses["ROBBERY"]["status"] == "EXCLUDED_BY_HIERARCHY"
    assert offenses["ROBBERY"]["hierarchy_rank"] == 30
    assert offenses["DATING_VIOLENCE"]["status"] == "COUNTED", (
        "DATING_VIOLENCE is exempt from the hierarchy and must be COUNTED"
    )
    assert offenses["DATING_VIOLENCE"]["is_exempt_from_hierarchy"] is True
    assert offenses["DRUG_LAW_REFERRAL"]["status"] == "COUNTED", (
        "Referral offenses are exempt from the hierarchy and must be COUNTED"
    )
    assert offenses["DRUG_LAW_REFERRAL"]["is_exempt_from_hierarchy"] is True

    asr = create_asr(report_year=2026)
    compile_asr(asr, variant="FINAL")
    lines = list_current_statistic_lines(
        asr["id"], params={"compilation_variant": "FINAL"}
    )
    line_map = {(l["offense_type"], l["geography_column"]): l for l in lines}

    assert line_map[("SEX_OFFENSE", "ON_CAMPUS")]["count"] == 1
    assert line_map[("SEX_OFFENSE", "ON_CAMPUS_RESIDENTIAL")]["count"] == 1, (
        "ON_CAMPUS_RESIDENTIAL incidents double-count into both columns"
    )
    assert line_map[("DATING_VIOLENCE", "ON_CAMPUS")]["count"] == 1
    assert line_map[("DATING_VIOLENCE", "ON_CAMPUS_RESIDENTIAL")]["count"] == 1
    assert line_map[("DRUG_LAW_REFERRAL", "ON_CAMPUS")]["count"] == 1
    assert line_map[("DRUG_LAW_REFERRAL", "ON_CAMPUS")]["referred_persons_count"] == 3
    assert line_map[("DRUG_LAW_REFERRAL", "ON_CAMPUS_RESIDENTIAL")]["count"] == 1
    assert line_map[("DRUG_LAW_REFERRAL", "ON_CAMPUS_RESIDENTIAL")]["referred_persons_count"] == 3
    assert all(l["offense_type"] != "ROBBERY" for l in lines), (
        "An offense EXCLUDED_BY_HIERARCHY must produce no statistic line"
    )


def test_offense_hierarchy_primary_is_smallest_rank(api):
    """PRD §3.3: "Among the remaining non-exempt offenses, the primary offense
    is the one with the smallest `hierarchy_rank`, with ties broken by earliest
    submission order within the classify call's array — never by record id. The
    primary offense and every exempt offense are assigned `status` `COUNTED`;
    all other non-exempt offenses are `EXCLUDED_BY_HIERARCHY`."

    Design: Difficulty/combinatorial_formula/offense_hierarchy_with_exemptions_and_double_count
    """
    geography = create_geography(name="Residence Hall Annex", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-02-15T08:00:00Z",
        occurred_at="2026-02-15T03:00:00Z",
    )
    validate_success(api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[
                {"offense_type": "BURGLARY", "victim_count": 1},
                {"offense_type": "ROBBERY", "victim_count": 1},
            ],
        ),
        COORD,
    ), 200)

    offenses = _offenses_by_type(get_success_data(
        api.list_offense_counts(incident["id"], COORD)
    ))
    assert offenses["ROBBERY"]["status"] == "COUNTED", (
        "ROBBERY (rank 30) is the primary over BURGLARY (rank 50)"
    )
    assert offenses["BURGLARY"]["status"] == "EXCLUDED_BY_HIERARCHY"


def test_classify_with_unknown_geography_returns_reference_not_found(api):
    """PRD §2.6: "Foreign keys carried in a request body, namely `geography_id`
    and `referral_id`, resolve separately and produce `ERR_REFERENCE_NOT_FOUND`
    (HTTP 404) when the referenced entity does not exist."

    Design: Corner/validations/classify_with_unknown_geography_returns_reference_not_found
    """
    geography = create_geography(name="Z", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-07T09:00:00Z",
        occurred_at="2026-04-07T08:00:00Z",
    )
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            NON_EXISTENT_UUID,
            expected_incident_version=incident["version"],
            offense_counts=[create_offense_count_payload()],
        ),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, expected_status=404)


def test_classify_terminal_incident_with_retired_geography(api):
    """PRD §2.6: "When a request trips several rules at once, failures surface
    in a fixed priority order ... then state-machine legality (including
    terminal-incident guards, the anonymous-visibility guard, and OCC
    stale-version rejection), then business-safety rules ... and finally
    field-level value constraints" with referential business rules (retired
    geographies) ordered after the state guards."
    PRD §3.3: "Attempting any incident action from the terminal states
    `UNFOUNDED` or `WITHDRAWN` is rejected with `ERR_INCIDENT_TERMINAL`
    (HTTP 409) rather than the generic state error."

    Design: Difficulty/priority_pair_validation_conflict/classify_terminal_incident_with_retired_geography
    """
    geo_a = create_geography(name="East Quad", category="ON_CAMPUS")
    geo_b = create_geography(name="Old Annex", category="NON_CAMPUS")
    validate_success(api.update_geography(geo_b["id"], {"status": "RETIRED"},
                                          TEST_USERS["admin_headers"]), 200)

    incident = create_unfounded_incident(
        geo_a["id"],
        reported_at="2026-02-01T09:00:00Z", occurred_at="2026-02-01T08:00:00Z",
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        justification="Fabricated report confirmed",
    )
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geo_b["id"],
            expected_incident_version=incident["version"],
            offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        ),
        COORD,
    )
    # Terminal-state guard (state category) outranks the retired-geography
    # referential rule, so ERR_INCIDENT_TERMINAL — not ERR_GEOGRAPHY_RETIRED.
    validate_error(res, ApiErrorId.ERR_INCIDENT_TERMINAL.value, expected_status=409)


def test_classify_terminal_incident_surfaces_terminal_not_stale(api):
    """PRD §2.6: "then state-machine legality (including terminal-incident
    guards, the anonymous-visibility guard, and OCC stale-version rejection)".
    PRD §3.3: "Attempting any incident action from the terminal states
    `UNFOUNDED` or `WITHDRAWN` is rejected with `ERR_INCIDENT_TERMINAL`
    (HTTP 409) rather than the generic state error."

    A classify against a WITHDRAWN incident must surface ERR_INCIDENT_TERMINAL
    even though the classify endpoint is state-guarded.

    Design: Difficulty/priority_pair_validation_conflict/classify_terminal_incident_with_retired_geography
    """
    geography = create_geography(name="East Quad South", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-02-02T09:00:00Z",
        occurred_at="2026-02-02T08:00:00Z",
    )
    withdrawn = validate_success(api.withdraw_incident(incident["id"], COORD), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=withdrawn["version"],
            offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        ),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_INCIDENT_TERMINAL.value, expected_status=409)


def test_classify_empty_offenses_with_retired_geography(api):
    """PRD §3.3: "Two business-safety guards apply before any offense math: the
    array must be non-empty and contain at least one offense whose type is not
    `NON_CLERY`, otherwise the call is rejected with
    `ERR_CLASSIFICATION_INCOMPLETE` (HTTP 422)".
    PRD §2.6: "then business-safety rules (unfound justification, CSA
    certification, classification completeness, locked reports) ... then
    referential business rules (retired or in-use geographies, residential-
    facility requirements, referral linkage state)".

    Design: Difficulty/priority_pair_validation_conflict/classify_empty_offenses_with_retired_geography
    """
    geo_a = create_geography(name="South Field", category="ON_CAMPUS")
    geo_b = create_geography(name="Closed Lot", category="PUBLIC_PROPERTY")
    validate_success(api.update_geography(geo_b["id"], {"status": "RETIRED"},
                                          TEST_USERS["admin_headers"]), 200)

    incident = create_under_classification_incident(
        geo_a["id"], reported_at="2026-04-11T09:00:00Z",
        occurred_at="2026-04-11T08:00:00Z",
    )
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geo_b["id"],
            expected_incident_version=incident["version"],
            offense_counts=[],
        ),
        COORD,
    )
    # Classification completeness (business_safety) outranks the retired
    # geography referential rule.
    validate_error(res, ApiErrorId.ERR_CLASSIFICATION_INCOMPLETE.value, expected_status=422)


def test_classify_only_non_clery_offenses_rejected(api):
    """PRD §3.3: "the array must be non-empty and contain at least one offense
    whose type is not `NON_CLERY`, otherwise the call is rejected with
    `ERR_CLASSIFICATION_INCOMPLETE` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/classify_empty_offenses_with_retired_geography
    """
    geography = create_geography(name="South Field East", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-12T09:00:00Z",
        occurred_at="2026-04-12T08:00:00Z",
    )
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[{"offense_type": "NON_CLERY", "victim_count": 1}],
        ),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_CLASSIFICATION_INCOMPLETE.value, expected_status=422)


def test_reclassification_blocked_by_published_asr(api):
    """PRD §3.3: "begin-reclassification is forbidden outright with
    `ERR_REPORT_LOCKED` (HTTP 409) whenever the Annual Security Report covering
    the calendar year of the incident's `occurred_at` exists in `PUBLISHED` or
    `REPUBLISHED` status — published disclosures freeze their underlying
    classifications."

    Design: Difficulty/cross_entity_state_dependency/reclassification_blocked_by_published_asr
    """
    geography = create_geography(name="West Hall", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-01-20T10:00:00Z", occurred_at="2026-01-20T09:00:00Z",
    )
    asr = create_published_asr(report_year=2026)
    assert asr["status"] == "PUBLISHED"

    res = api.begin_reclassification(incident["id"], COORD)
    validate_error(res, ApiErrorId.ERR_REPORT_LOCKED.value, expected_status=409)

    after = validate_success(api.get_incident(incident["id"], COORD), 200)
    assert after["status"] == "CLASSIFIED", (
        "A locked report must leave the incident in CLASSIFIED"
    )


def test_reclassification_allowed_while_asr_collecting(api):
    """PRD §3.3: "begin-reclassification is forbidden outright with
    `ERR_REPORT_LOCKED` (HTTP 409) whenever the Annual Security Report covering
    the calendar year of the incident's `occurred_at` exists in `PUBLISHED` or
    `REPUBLISHED` status — published disclosures freeze their underlying
    classifications."

    While the year's ASR is still COLLECTING, reclassification is not locked.

    Design: Difficulty/cross_entity_state_dependency/reclassification_blocked_by_published_asr
    """
    geography = create_geography(name="West Hall Annex", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-01-21T10:00:00Z", occurred_at="2026-01-21T09:00:00Z",
    )
    asr = create_asr(report_year=2026)
    assert asr["status"] == "COLLECTING"

    reclass = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    assert reclass["status"] == "UNDER_RECLASSIFICATION"


def test_unfound_without_justification_rejected(api):
    """PRD §3.3: "the unfound call must carry a non-empty `justification` or be
    rejected with `ERR_UNFOUNDED_JUSTIFICATION_REQUIRED` (HTTP 422)."

    Design: Corner/validations/unfound_without_justification_rejected
    """
    geography = create_geography(name="V", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-11T09:00:00Z",
        occurred_at="2026-04-11T08:00:00Z",
    )
    res = api.unfound_incident(incident["id"], {"justification": ""}, CHIEF)
    validate_error(res, ApiErrorId.ERR_UNFOUNDED_JUSTIFICATION_REQUIRED.value,
                   expected_status=422)


def test_occ_stale_version_on_classify_returns_412(api):
    """PRD §2.5: "Classification of an incident requires the request to carry
    `expected_incident_version` equal to the incident's current `version`. If
    another writer has advanced the incident's version since the caller last
    read it ... the classify call is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the caller from silently overwriting a
    classification it never observed."

    Design: Corner/complexity_layers/occ_stale_version_on_classify_returns_412
    """
    geography = create_geography(name="I", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-14T09:00:00Z",
        occurred_at="2026-04-14T08:00:00Z",
    )
    assert incident["version"] == 3, "create(1) -> submit(2) -> begin-classification(3)"

    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"] - 1,
            offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        ),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    after = validate_success(api.get_incident(incident["id"], COORD), 200)
    assert after["status"] == "UNDER_CLASSIFICATION"
    assert after["version"] == incident["version"], (
        "A stale classify must not advance the incident version"
    )


def test_classify_response_immediately_consistent(api):
    """PRD §3.3: "After a successful classification the incident's
    `is_clery_reportable` becomes true as soon as at least one offense row is
    `COUNTED`, and `classified_at` records the timestamp of the most recent
    successful classify."
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/consistency_model/classify_response_immediately_consistent
    """
    geography = create_geography(name="H", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-15T09:00:00Z",
        occurred_at="2026-04-15T08:00:00Z",
    )
    classified = validate_success(api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[create_offense_count_payload(offense_type="SEX_OFFENSE")],
        ),
        COORD,
    ), 200)
    assert classified["status"] == "CLASSIFIED"
    assert classified["version"] == incident["version"] + 1
    assert classified["is_clery_reportable"] is True

    fetched = validate_success(api.get_incident(incident["id"], COORD), 200)
    assert fetched["status"] == classified["status"]
    assert fetched["version"] == classified["version"]
    assert fetched["is_clery_reportable"] is True
