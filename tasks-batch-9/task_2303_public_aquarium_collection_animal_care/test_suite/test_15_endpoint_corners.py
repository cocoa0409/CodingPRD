"""Endpoint-surface corners for the routes published in PRD §4.

Each test drives one published route family and holds it to the envelope
contract of PRD §2.2, the pagination-and-filter contract of PRD §2.3 and the
resource-versioning contract of PRD §2.4.
"""
from datetime import datetime, timezone
from typing import Dict

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    PERMIT_OFFICER_HEADERS,
    VET_HEADERS,
    assertions,
    factories,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ERR_VALIDATION


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def same_instant(actual: str, expected: str) -> bool:
    """Two ISO 8601 UTC instants denote the same moment."""
    return parse_utc(actual) == parse_utc(expected)


def envelope(response) -> Dict:
    """The raw JSON envelope of a response."""
    return response.json()


def test_species_single_read_and_taxon_filtered_list_paginate_over_the_filtered_rows(api, build):
    """A species reads back singly and a filtered species list paginates over the filtered population.

    PRD §2.3: "Lists also accept optional filters, which narrow the result set without changing the pagination contract."

    Design: Corner/endpoints/endpoint_species_create_read_and_filtered_list_paginate_independently
    """
    first = build.create_species(
        scientific_name="Sebastes ruberrimus",
        common_name="yelloweye rockfish",
        taxon_group="TELEOST",
        protection_status="UNLISTED",
        sustainability_rating="GREEN",
        bioload_units_per_specimen=12.0,
        base_quarantine_days=30,
        wild_take_quota_annual=4,
    )
    build.advance(hours=1)
    second = build.create_species(
        scientific_name="Cheilinus undulatus",
        common_name="humphead wrasse",
        taxon_group="TELEOST",
        protection_status="CITES_APPENDIX_II",
        sustainability_rating="YELLOW",
        bioload_units_per_specimen=20.0,
        base_quarantine_days=30,
        wild_take_quota_annual=4,
    )
    build.advance(hours=1)
    third = build.create_species(
        scientific_name="Metridium senile",
        common_name="plumose anemone",
        taxon_group="INVERTEBRATE",
        protection_status="UNLISTED",
        sustainability_rating="GREEN",
        bioload_units_per_specimen=1.0,
        base_quarantine_days=14,
        wild_take_quota_annual=4,
    )

    # The single read answers with an object envelope and the derived permit flag
    # of PRD §3.3 (permit_required is true for anything other than UNLISTED).
    single_response = api.get_species(second["id"], CURATOR_HEADERS)
    single = validate_success(single_response)
    assert envelope(single_response)["response_type"] == "object"
    assert envelope(single_response)["meta"]["api_request_id"].startswith("req_")
    assertions.assert_species(single)
    assert single["id"] == second["id"]
    assert single["scientific_name"] == "Cheilinus undulatus"
    assert single["permit_required"] is True
    assert single["version"] == 1

    # The taxon_group filter narrows three rows to two, and limit 1 pages over
    # that filtered population — total_count describes the filtered set.
    page_one_response = api.list_species(CURATOR_HEADERS, {"taxon_group": "TELEOST", "limit": 1})
    page_one, page_one_meta = validate_paginated(page_one_response)
    assert envelope(page_one_response)["response_type"] == "array"
    assert [row["id"] for row in page_one] == [first["id"]]
    assert page_one_meta["total_count"] == 2
    assert page_one_meta["limit"] == 1
    assert page_one_meta["offset"] == 0
    assert page_one_meta["has_more"] is True

    page_two, page_two_meta = validate_paginated(
        api.list_species(CURATOR_HEADERS, {"taxon_group": "TELEOST", "limit": 1, "offset": 1})
    )
    assert [row["id"] for row in page_two] == [second["id"]]
    assert page_two_meta["total_count"] == 2
    assert page_two_meta["offset"] == 1
    assert page_two_meta["has_more"] is False

    protected, protected_meta = validate_paginated(
        api.list_species(CURATOR_HEADERS, {"protection_status": "CITES_APPENDIX_II"})
    )
    assert protected_meta["total_count"] == 1
    assert [row["id"] for row in protected] == [second["id"]]

    unfiltered, unfiltered_meta = validate_paginated(api.list_species(CURATOR_HEADERS))
    assert unfiltered_meta["total_count"] == 3
    assert [row["id"] for row in unfiltered] == [first["id"], second["id"], third["id"]]


def test_institution_patch_carrying_only_the_audit_date_leaves_the_other_fields_alone(api, build):
    """A PATCH supplying only last_audit_at rewrites that field and nothing else.

    PRD §3.3: "The director may later update an institution's `accreditation_status`, `welfare_audit_score` or `last_audit_at`. The update recomputes `is_receiving_eligible` and increments the institution's `version`"

    Design: Corner/endpoints/endpoint_institution_patch_touches_only_the_supplied_fields
    """
    institution = build.create_institution(
        name="Northport Marine Institute",
        institution_code="NPM-0001",
        accreditation_status="ACCREDITED",
        welfare_audit_score=88.00,
        last_audit_at="2026-05-01T00:00:00Z",
    )
    assert institution["version"] == 1
    assert institution["is_receiving_eligible"] is True

    patched = validate_success(
        api.update_institution(
            institution["id"],
            factories.institution_patch_payload(last_audit_at="2026-07-15T00:00:00Z"),
            DIRECTOR_HEADERS,
        )
    )
    assertions.assert_institution(patched)
    assert same_instant(patched["last_audit_at"], "2026-07-15T00:00:00Z")
    assert patched["accreditation_status"] == "ACCREDITED"
    assertions.assert_scaled_equal(patched["welfare_audit_score"], 88.00)
    # Eligibility is recomputed on every edit (PRD §3.3) and lands on the same
    # value, so the receiver-ineligibility cascade of PRD §3.8 does not run.
    assert patched["is_receiving_eligible"] is True
    assert patched["version"] == 2

    reread = validate_success(api.get_institution(institution["id"], DIRECTOR_HEADERS))
    assert same_instant(reread["last_audit_at"], "2026-07-15T00:00:00Z")
    assert reread["accreditation_status"] == "ACCREDITED"
    assertions.assert_scaled_equal(reread["welfare_audit_score"], 88.00)
    assert reread["is_receiving_eligible"] is True
    assert reread["version"] == 2
    assert reread["name"] == "Northport Marine Institute"
    assert reread["institution_code"] == "NPM-0001"

    _, transfer_meta = validate_paginated(api.list_transfer_requests(DIRECTOR_HEADERS))
    assert transfer_meta["total_count"] == 0


def test_session_transition_answers_with_the_mutated_session_on_every_action(api, build):
    """Each session transition returns HTTP 200 carrying the whole updated session.

    PRD §4: "every other successful operation returns HTTP 200, including state transitions, decisions, cascading actions and the clock control endpoint"

    Design: Corner/endpoints/endpoint_session_transition_action_returns_the_updated_session_not_an_empty_body
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=True)
    build.append_graded_reading(plant, "NORMAL")
    starts_at = shift(build.now, days=1, hours=10)
    ends_at = shift(build.now, days=1, hours=11)
    session = build.book_session(
        exhibit["id"],
        starts_at,
        ends_at,
        program_type="FEEDING_ENCOUNTER",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    assert session["status"] == "SCHEDULED"
    assert session["version"] == 1

    activate_response = api.transition_interaction_session(
        session["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
    )
    activated = validate_success(activate_response)
    assert envelope(activate_response)["response_type"] == "object"
    assertions.assert_interaction_session(activated)
    assert activated["id"] == session["id"]
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2
    assert activated["exhibit_id"] == exhibit["id"]
    assert activated["program_type"] == "FEEDING_ENCOUNTER"
    assert same_instant(activated["starts_at"], starts_at)
    assert same_instant(activated["ends_at"], ends_at)
    assert activated["max_guests"] == 6
    assert activated["guest_count"] == 4

    complete_response = api.transition_interaction_session(
        session["id"], factories.session_transition_payload("COMPLETE"), AQUARIST_HEADERS
    )
    completed = validate_success(complete_response)
    assert envelope(complete_response)["response_type"] == "object"
    assertions.assert_interaction_session(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["version"] == 3
    assert completed["exhibit_id"] == exhibit["id"]

    reread = validate_success(api.get_interaction_session(session["id"], AQUARIST_HEADERS))
    assert reread["status"] == "COMPLETED"
    assert reread["version"] == 3

    # Neither transition suspended anything, so the exhibit's lifetime
    # suspension counter of PRD §3.9 is untouched.
    assert build.get_exhibit(exhibit["id"])["suspended_session_count"] == 0


def test_the_permits_link_of_one_request_never_returns_a_sibling_requests_dossier(api, build):
    """The permits sub-resource is scoped to its parent acquisition request.

    PRD §3.5: "the permits of one request may be listed with the `status` and `permit_type` filters, and a permit read singly"

    Design: Corner/endpoints/endpoint_request_permits_link_returns_only_that_requests_permits
    """
    world = build.approved_line(
        species_overrides={"wild_take_quota_annual": 8},
        entry_overrides={"planned_count": 4, "sustainability_requirement": "GREEN_ONLY"},
    )
    institution = build.create_institution(welfare_audit_score=88.00)
    import_documents = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]

    request_a = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request_a = build.submit_acquisition(request_a["id"])
    assert request_a["permit_required"] is True
    assert request_a["status"] == "PENDING_PERMIT"
    permit_a = build.draft_permit(request_a["id"], "IMPORT", import_documents)
    permit_a = build.submit_permit(permit_a["id"])
    assert permit_a["status"] == "SUBMITTED"

    request_b = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request_b = build.submit_acquisition(request_b["id"])
    assert request_b["permit_required"] is True
    permit_b = build.draft_permit(request_b["id"], "IMPORT", import_documents)
    assert permit_b["status"] == "DRAFT"

    rows_a, meta_a = validate_paginated(
        api.list_acquisition_request_permits(request_a["id"], PERMIT_OFFICER_HEADERS)
    )
    assert meta_a["total_count"] == 1
    assert [row["id"] for row in rows_a] == [permit_a["id"]]
    assert rows_a[0]["status"] == "SUBMITTED"
    assert rows_a[0]["submission_round"] == 1
    assert rows_a[0]["acquisition_request_id"] == request_a["id"]

    rows_b, meta_b = validate_paginated(
        api.list_acquisition_request_permits(
            request_b["id"], PERMIT_OFFICER_HEADERS, {"status": "DRAFT"}
        )
    )
    assert meta_b["total_count"] == 1
    assert [row["id"] for row in rows_b] == [permit_b["id"]]

    # Request B's DRAFT dossier must not leak into request A's link.
    rows_a_draft, meta_a_draft = validate_paginated(
        api.list_acquisition_request_permits(
            request_a["id"], PERMIT_OFFICER_HEADERS, {"status": "DRAFT"}
        )
    )
    assert meta_a_draft["total_count"] == 0
    assert rows_a_draft == []
    assert meta_a_draft["has_more"] is False

    rows_a_transport, meta_a_transport = validate_paginated(
        api.list_acquisition_request_permits(
            request_a["id"], PERMIT_OFFICER_HEADERS, {"permit_type": "TRANSPORT"}
        )
    )
    assert meta_a_transport["total_count"] == 0
    assert rows_a_transport == []


def test_the_exhibit_list_filters_on_the_derived_posture_after_a_warning_reading(api, build):
    """posture is server-derived yet a first-class list filter on both exhibit lists.

    PRD §2.3: "Exhibits may be filtered by `life_support_system_id` and `posture`"

    Design: Corner/endpoints/endpoint_exhibit_list_filters_on_the_computed_posture_field
    """
    plant_one = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    plant_two = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit_a = build.create_exhibit(plant_one, name="Cold Water Reef")
    exhibit_b = build.create_exhibit(plant_one, name="Kelp Forest")
    exhibit_c = build.create_exhibit(plant_two, name="Rocky Shore")
    assert exhibit_a["posture"] == "OPEN"
    assert exhibit_a["version"] == 1

    reading = build.append_graded_reading(plant_one, "WARNING")
    assert reading["severity"] == "WARNING"
    assert build.get_plant(plant_one["id"])["alarm_state"] == "WARNING"
    assert build.get_plant(plant_two["id"])["alarm_state"] == "NORMAL"

    restricted, restricted_meta = validate_paginated(
        api.list_exhibits(CURATOR_HEADERS, {"posture": "RESTRICTED", "limit": 10})
    )
    assert restricted_meta["total_count"] == 2
    assert {row["id"] for row in restricted} == {exhibit_a["id"], exhibit_b["id"]}
    for row in restricted:
        assertions.assert_exhibit(row)
        assertions.assert_posture(row, "RESTRICTED", "LSS_WARNING")
        assertions.assert_scaled_equal(row["occupied_bioload_units"], 0.00)
        assertions.assert_scaled_equal(row["bioload_utilization_pct"], 0.00)
        assert row["version"] == 2

    open_rows, open_meta = validate_paginated(
        api.list_exhibits(CURATOR_HEADERS, {"posture": "OPEN", "limit": 10})
    )
    assert open_meta["total_count"] == 1
    assert [row["id"] for row in open_rows] == [exhibit_c["id"]]
    assertions.assert_posture(open_rows[0], "OPEN", None)
    assert open_rows[0]["version"] == 1

    served, served_meta = validate_paginated(
        api.list_system_exhibits(plant_one["id"], CURATOR_HEADERS, {"posture": "RESTRICTED", "limit": 10})
    )
    assert served_meta["total_count"] == 2
    assert {row["id"] for row in served} == {exhibit_a["id"], exhibit_b["id"]}

    by_plant, by_plant_meta = validate_paginated(
        api.list_exhibits(CURATOR_HEADERS, {"life_support_system_id": plant_two["id"]})
    )
    assert by_plant_meta["total_count"] == 1
    assert [row["id"] for row in by_plant] == [exhibit_c["id"]]


def test_quarantine_review_reads_extension_days_only_for_the_extend_outcome(api, build):
    """extension_days is range-checked and consumed by EXTEND alone; RESUME ignores it.

    PRD §3.6: "**`EXTEND`** moves an `ACTIVE` case to `EXTENDED`. `extension_count` plus 1 must be no greater than 2, else `ERR_ROUND_LIMIT_EXCEEDED`, and `extension_days` must be between 1 and 30."

    Design: Corner/endpoints/endpoint_quarantine_review_reads_extension_days_only_for_the_extend_outcome
    """
    world = build.quarantined_specimen()
    case = world["quarantine_case"]
    assertions.assert_quarantine_case(case)
    assert case["status"] == "ACTIVE"
    assert case["protocol_days"] == 30
    assert case["extension_count"] == 0
    assert case["total_extension_days"] == 0
    assert same_instant(case["projected_release_at"], "2026-08-31T00:00:00Z")

    build.advance_to("2026-08-10T00:00:00Z")

    # 31 days is outside the documented 1..30 range, so the review is a
    # validation failure and the case is left exactly as it was.
    rejected = api.create_quarantine_review(
        case["id"], factories.quarantine_review_payload("EXTEND", extension_days=31), VET_HEADERS
    )
    validate_error(rejected, ERR_VALIDATION, 422)
    untouched = build.get_quarantine_case(case["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["extension_count"] == 0
    assert untouched["total_extension_days"] == 0
    assert same_instant(untouched["projected_release_at"], "2026-08-31T00:00:00Z")

    extended = validate_success(
        api.create_quarantine_review(
            case["id"],
            factories.quarantine_review_payload(
                "EXTEND", extension_days=7, reason="mild ectoparasite load under treatment"
            ),
            VET_HEADERS,
        )
    )
    assert extended["status"] == "EXTENDED"
    assert extended["extension_count"] == 1
    assert extended["total_extension_days"] == 7
    assert same_instant(extended["projected_release_at"], "2026-09-07T00:00:00Z")

    # RESUME carries no extension_days at all and must not shift the date back.
    resumed = validate_success(
        api.create_quarantine_review(
            case["id"], factories.quarantine_review_payload("RESUME"), VET_HEADERS
        )
    )
    assert resumed["status"] == "ACTIVE"
    assert resumed["extension_count"] == 1
    assert resumed["total_extension_days"] == 7
    assert same_instant(resumed["projected_release_at"], "2026-09-07T00:00:00Z")

    reread = build.get_quarantine_case(case["id"])
    assert reread["status"] == "ACTIVE"
    assert same_instant(reread["projected_release_at"], "2026-09-07T00:00:00Z")
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "QUARANTINE"
