"""Validation corners: the clinical, aggregate, sourcing and capacity gates.

Every test here drives one published rule of the ordered rejection ladder to the
exact identifier PRD §5 names for it, and re-reads the entities the rule claims to
leave alone so that a rejection is proved to have persisted nothing.
"""
from typing import Any, Dict, List

from test_helpers import (
    AQUARIST_HEADERS,
    CLEARANCE_OFFICER_ID,
    CURATOR_HEADERS,
    DIRECTOR_THIRD_ID,
    NON_EXISTENT_UUID,
    VET_SECOND_HEADERS,
    ApiClient,
    Builder,
    assertions,
    factories,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_BIOLOAD_CAPACITY_EXCEEDED,
    ERR_JUSTIFICATION_REQUIRED,
    ERR_PLANNED_COUNT_EXCEEDED,
    ERR_REQUESTED_COUNT_EXCEEDED,
    ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED,
    ERR_SPECIES_NOT_FOUND,
    ERR_SPECIMEN_NOT_HEALTHY,
    ERR_STALE_SPECIES_VERSION,
    ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION,
)

IMPORT_DOCUMENTS = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]


def _admit_cleared_specimens(build: Builder, world: Dict[str, Any], count: int) -> List[Dict[str, Any]]:
    """Accession `count` animals against the world's CLEARED request and clear each quarantine.

    Every animal is given the two closed preventive exams with no findings that
    quarantine clearance demands (PRD §3.6), and the clock is advanced to the
    latest `projected_release_at` before any `CLEAR` review is recorded.
    """
    specimens = [build.accession_specimen(world["species"], world["request"]) for _ in range(count)]
    cases = {s["id"]: build.quarantine_case_of(s["id"]) for s in specimens}
    exams = {s["id"]: build.record_clean_exams(s["id"], 2) for s in specimens}
    build.advance_to(max(case["projected_release_at"] for case in cases.values()))
    for specimen in specimens:
        build.close_clean_exams(exams[specimen["id"]])
        build.review_quarantine(cases[specimen["id"]]["id"], "CLEAR")
    return [build.get_specimen(s["id"]) for s in specimens]


def test_placement_of_an_under_treatment_specimen_is_refused_until_the_case_closes(api: ApiClient, build: Builder):
    """An open treatment blocks placement on the clinical dimension alone, and closing it admits the identical call.

    PRD §2.8: "The specimen's `health_status` is `HEALTHY` — `ERR_SPECIMEN_NOT_HEALTHY` (409). Applies to exhibit placement, transfer submission, transfer completion and quarantine reviews. This is a cross-dimension guard: the disposition dimension may be perfectly correct while the clinical dimension blocks the move."

    Design: Corner/validations/validation_placement_of_an_under_treatment_specimen_is_rejected
    """
    world = build.cleared_specimen(
        species_overrides={"bioload_units_per_specimen": 12.0},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    specimen = world["specimen"]
    exhibit = world["exhibit"]

    # Opening a TREATMENT case moves the clinical dimension to UNDER_TREATMENT (§3.7),
    # while the disposition dimension stays CLEARED and therefore placement-ready.
    treatment = build.open_vet_case(
        specimen["id"],
        "TREATMENT",
        treatment_start_at=build.now,
        withdrawal_days=10,
    )
    blocked = build.get_specimen(specimen["id"])
    assert blocked["health_status"] == "UNDER_TREATMENT", blocked["health_status"]
    assert blocked["disposition_status"] == "CLEARED", blocked["disposition_status"]

    refused = api.place_specimen(
        specimen["id"],
        factories.placement_payload(exhibit["id"], build.exhibit_version(exhibit["id"])),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_SPECIMEN_NOT_HEALTHY, 409)

    # Nothing was persisted: the animal is still in holding and the ledger is empty.
    unmoved = build.get_specimen(specimen["id"])
    assert unmoved["disposition_status"] == "CLEARED", unmoved["disposition_status"]
    assert unmoved["exhibit_id"] is None, unmoved["exhibit_id"]
    untouched_exhibit = build.get_exhibit(exhibit["id"])
    assertions.assert_scaled_equal(untouched_exhibit["occupied_bioload_units"], 0.00)

    # §3.7: RESOLVED with NONE on the specimen's only open case restores HEALTHY.
    closed = build.close_vet_case(treatment["id"], "RESOLVED", "NONE", headers=VET_SECOND_HEADERS)
    assert closed["status"] == "CLOSED", closed["status"]
    assert closed["outcome"] == "RESOLVED", closed["outcome"]
    assert closed["findings_severity"] == "NONE", closed["findings_severity"]
    healthy = build.get_specimen(specimen["id"])
    assert healthy["health_status"] == "HEALTHY", healthy["health_status"]

    admitted = validate_success(
        api.place_specimen(
            specimen["id"],
            factories.placement_payload(exhibit["id"], build.exhibit_version(exhibit["id"])),
            AQUARIST_HEADERS,
        )
    )
    assert admitted["disposition_status"] == "ON_EXHIBIT", admitted["disposition_status"]
    assert admitted["exhibit_id"] == exhibit["id"], admitted["exhibit_id"]
    on_exhibit = build.get_specimen(specimen["id"])
    assert on_exhibit["disposition_status"] == "ON_EXHIBIT", on_exhibit["disposition_status"]
    assert on_exhibit["exhibit_id"] == exhibit["id"], on_exhibit["exhibit_id"]

    # §3.2: the ledger now carries the one animal's snapshotted bioload of 12.
    loaded = build.get_exhibit(exhibit["id"])
    assertions.assert_scaled_equal(loaded["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(loaded["bioload_utilization_pct"], 12.00)
    assertions.assert_posture(loaded, "OPEN", None)


def test_third_placement_of_a_species_exceeds_the_plan_lines_planned_count(api: ApiClient, build: Builder):
    """Two placements fill a planned_count of 2 and the third is refused as an aggregate breach.

    PRD §2.8: "The number of specimens of this species already `ON_EXHIBIT` or `TRANSFER_PENDING` in the exhibit is below the plan line's `planned_count` — `ERR_PLANNED_COUNT_EXCEEDED` (409). Applies to exhibit placement. This is an aggregate rule: each placement is individually legal, and it is the collection that exceeds the plan."

    Design: Corner/validations/validation_third_placement_exceeds_the_plan_lines_planned_count
    """
    world = build.cleared_acquisition(
        requested_count=3,
        species_overrides={"bioload_units_per_specimen": 12.0},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    first, second, third = _admit_cleared_specimens(build, world, 3)
    exhibit_id = world["exhibit"]["id"]

    placed_first = build.place(first["id"], exhibit_id)
    assert placed_first["disposition_status"] == "ON_EXHIBIT", placed_first["disposition_status"]
    placed_second = build.place(second["id"], exhibit_id)
    assert placed_second["disposition_status"] == "ON_EXHIBIT", placed_second["disposition_status"]

    refused = api.place_specimen(
        third["id"],
        factories.placement_payload(exhibit_id, build.exhibit_version(exhibit_id)),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_PLANNED_COUNT_EXCEEDED, 409)

    rejected = build.get_specimen(third["id"])
    assert rejected["disposition_status"] == "CLEARED", rejected["disposition_status"]
    assert rejected["exhibit_id"] is None, rejected["exhibit_id"]

    # 24 of 100 units: the capacity rule of rank 45 had ample headroom, so the
    # aggregate plan rule is demonstrably what refused the third animal.
    exhibit = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(exhibit["occupied_bioload_units"], 24.00)
    assertions.assert_scaled_equal(exhibit["bioload_utilization_pct"], 24.00)
    assertions.assert_posture(exhibit, "OPEN", None)

    rows, meta = validate_paginated(api.list_specimens(CURATOR_HEADERS, {"exhibit_id": exhibit_id}))
    assert meta["total_count"] == 2, meta
    assert sorted(r["id"] for r in rows) == sorted([first["id"], second["id"]]), rows


def test_fourth_accession_against_a_fulfilled_request_exceeds_the_requested_count(api: ApiClient, build: Builder):
    """A request for three animals accepts three specimens and refuses the fourth.

    PRD §2.8: "The acquisition request's `fulfilled_count` is below its `requested_count` — `ERR_REQUESTED_COUNT_EXCEEDED` (409). Applies to specimen accession; a `FULFILLED` request accepts no further specimens."

    Design: Corner/validations/validation_fourth_accession_exceeds_the_requested_count
    """
    world = build.cleared_acquisition(
        requested_count=3,
        entry_overrides={"planned_count": 4, "sustainability_requirement": "GREEN_ONLY"},
    )
    request = world["request"]
    for _ in range(3):
        build.accession_specimen(world["species"], request)

    # §3.5: the third accession takes the count to requested_count, so the request
    # is already the terminal FULFILLED when the fourth animal is presented.
    filled = build.get_acquisition(request["id"])
    assert filled["status"] == "FULFILLED", filled["status"]
    assert filled["fulfilled_count"] == 3, filled["fulfilled_count"]

    refused = api.create_specimen(
        factories.specimen_payload(world["species"]["id"], request["id"], arrival_at=build.now),
        CURATOR_HEADERS,
    )
    validate_error(refused, ERR_REQUESTED_COUNT_EXCEEDED, 409)

    unchanged = build.get_acquisition(request["id"])
    assert unchanged["status"] == "FULFILLED", unchanged["status"]
    assert unchanged["fulfilled_count"] == 3, unchanged["fulfilled_count"]

    _, meta = validate_paginated(
        api.list_specimens(CURATOR_HEADERS, {"acquisition_request_id": request["id"]})
    )
    assert meta["total_count"] == 3, meta


def test_submission_under_an_any_with_justification_line_demands_written_reasoning(api: ApiClient, build: Builder):
    """The plan line's ANY_WITH_JUSTIFICATION requirement refuses a bare submission and accepts the justified retry.

    PRD §2.8: "`justification` is present when the parent plan line's `sustainability_requirement` is `ANY_WITH_JUSTIFICATION` — `ERR_JUSTIFICATION_REQUIRED` (422). Applies to acquisition submission. The rule is driven by the parent plan entry's configuration, not by the request's own fields."

    Design: Corner/validations/validation_justification_is_required_only_under_any_with_justification
    """
    world = build.approved_line(
        species_overrides={"sustainability_rating": "RED"},
        entry_overrides={"sustainability_requirement": "ANY_WITH_JUSTIFICATION"},
    )
    # §3.5: ANY_WITH_JUSTIFICATION admits any rating at creation, so the RED
    # species reaches submission and it is submission that demands the reasoning.
    request = build.create_acquisition(world["entry"], source_type="CAPTIVE_BRED", requested_count=1)

    refused = api.submit_acquisition_request(request["id"], {}, CURATOR_HEADERS)
    validate_error(refused, ERR_JUSTIFICATION_REQUIRED, 422)

    still_draft = build.get_acquisition(request["id"])
    assert still_draft["status"] == "DRAFT", still_draft["status"]
    assert still_draft["permit_deadline_at"] is None, still_draft["permit_deadline_at"]

    reasoning = "last remaining founder bloodline for the breeding programme"
    submitted = validate_success(
        api.submit_acquisition_request(request["id"], {"justification": reasoning}, CURATOR_HEADERS)
    )
    # §3.5: an UNLISTED species sourced CAPTIVE_BRED needs no permit, so the
    # request takes the READY_FOR_CLEARANCE road with a null deadline.
    assert submitted["status"] == "READY_FOR_CLEARANCE", submitted["status"]
    assert submitted["justification"] == reasoning, submitted["justification"]
    assert submitted["permit_required"] is False, submitted["permit_required"]
    assert submitted["permit_deadline_at"] is None, submitted["permit_deadline_at"]

    stored = build.get_acquisition(request["id"])
    assert stored["status"] == "READY_FOR_CLEARANCE", stored["status"]
    assert stored["justification"] == reasoning, stored["justification"]


def test_submission_under_a_green_or_yellow_line_needs_no_justification(api: ApiClient, build: Builder):
    """A plan line that does not demand reasoning submits a request carrying no justification at all.

    PRD §2.8: "`justification` is present when the parent plan line's `sustainability_requirement` is `ANY_WITH_JUSTIFICATION` — `ERR_JUSTIFICATION_REQUIRED` (422). Applies to acquisition submission. The rule is driven by the parent plan entry's configuration, not by the request's own fields."

    Design: Corner/validations/validation_justification_is_required_only_under_any_with_justification
    """
    world = build.approved_line(
        species_overrides={"sustainability_rating": "GREEN"},
        entry_overrides={"sustainability_requirement": "GREEN_OR_YELLOW"},
    )
    request = build.create_acquisition(world["entry"], source_type="CAPTIVE_BRED", requested_count=1)
    assert request["justification"] is None, request["justification"]

    submitted = validate_success(api.submit_acquisition_request(request["id"], {}, CURATOR_HEADERS))
    assert submitted["status"] == "READY_FOR_CLEARANCE", submitted["status"]
    assert submitted["justification"] is None, submitted["justification"]
    assert submitted["permit_deadline_at"] is None, submitted["permit_deadline_at"]

    stored = build.get_acquisition(request["id"])
    assert stored["status"] == "READY_FOR_CLEARANCE", stored["status"]


def test_green_only_plan_line_refuses_a_red_species_at_request_creation(api: ApiClient, build: Builder):
    """The sourcing standard is enforced when the request is opened, not deferred to clearance.

    PRD §3.5: "Creation checks the species' `sustainability_rating` against the plan line's `sustainability_requirement` — `GREEN_ONLY` admits only `GREEN`, `GREEN_OR_YELLOW` admits `GREEN` and `YELLOW`, and `ANY_WITH_JUSTIFICATION` admits any rating but demands written reasoning at submission — refusing a mismatch with `ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION`."

    Design: Corner/validations/validation_green_only_plan_line_rejects_a_red_species_at_request_creation
    """
    red_world = build.approved_line(
        species_overrides={"sustainability_rating": "RED"},
        entry_overrides={"sustainability_requirement": "GREEN_ONLY"},
    )
    green_species = build.create_species(sustainability_rating="GREEN")
    green_entry = build.create_approved_plan_entry(
        red_world["exhibit"], green_species, sustainability_requirement="GREEN_ONLY"
    )

    refused = api.create_acquisition_request(
        factories.acquisition_request_payload(
            red_world["entry"]["id"], source_type="CAPTIVE_BRED", requested_count=1
        ),
        CURATOR_HEADERS,
    )
    validate_error(refused, ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION, 409)

    _, red_meta = validate_paginated(
        api.list_acquisition_requests(
            CURATOR_HEADERS, {"collection_plan_entry_id": red_world["entry"]["id"]}
        )
    )
    assert red_meta["total_count"] == 0, red_meta

    # The identical call under the same GREEN_ONLY requirement is admitted once the
    # rating is inside the admitted set, and stamps the PROVISIONAL variant:
    # 40.0 GREEN + 35.0 CAPTIVE_BRED + 20.0 for a null source institution (§3.5).
    admitted = validate_success(
        api.create_acquisition_request(
            factories.acquisition_request_payload(
                green_entry["id"], source_type="CAPTIVE_BRED", requested_count=1
            ),
            CURATOR_HEADERS,
        ),
        201,
    )
    assertions.assert_scaled_equal(admitted["sustainability_score"], 95.00)
    assert admitted["sustainability_score_variant"] == "PROVISIONAL", admitted["sustainability_score_variant"]

    _, green_meta = validate_paginated(
        api.list_acquisition_requests(CURATOR_HEADERS, {"collection_plan_entry_id": green_entry["id"]})
    )
    assert green_meta["total_count"] == 1, green_meta


def test_stale_species_version_wins_over_the_already_cleared_state_complaint(api: ApiClient, build: Builder):
    """A replayed clearance breaches both the species guard and the state machine, and the guard answers first.

    PRD §2.6: "Where the guard does apply it is evaluated early — after the request has been shown to be well-formed and to reference existing rows, but before any state machine or business rule is consulted — so a stale version always wins over a state complaint, a posture complaint or a capacity complaint (§2.8)."

    Design: Corner/validations/validation_stale_species_version_masks_the_already_cleared_state_error
    """
    world = build.approved_line(species_overrides={"wild_take_quota_annual": 4})
    species_id = world["species"]["id"]
    request = build.create_acquisition(world["entry"], source_type="WILD_COLLECTION", requested_count=1)
    submitted = build.submit_acquisition(request["id"])
    assert submitted["status"] == "PENDING_PERMIT", submitted["status"]
    build.issue_permit(request["id"], "IMPORT", IMPORT_DOCUMENTS)

    # The director reads the quota pool, then clears against it. §3.5: a
    # WILD_COLLECTION clearance increments the species' version by 1, so the
    # token this reader still holds is now stale.
    stale_version = build.species_version(species_id)
    cleared = build.clear_acquisition(request["id"], species_id, user_id=CLEARANCE_OFFICER_ID)
    assert cleared["status"] == "CLEARED", cleared["status"]
    moved_species = build.get_species(species_id)
    assert moved_species["version"] == stale_version + 1, moved_species["version"]

    replay = api.clear_acquisition_request(
        request["id"],
        factories.clearance_payload(stale_version),
        make_director_headers(DIRECTOR_THIRD_ID),
    )
    validate_error(replay, ERR_STALE_SPECIES_VERSION, 412)

    # The first clearance stands untouched: rank 9 refused before the state
    # machine could report the request is no longer clearable.
    survivor = build.get_acquisition(request["id"])
    assert survivor["status"] == "CLEARED", survivor["status"]
    assert survivor["cleared_by_user_id"] == CLEARANCE_OFFICER_ID, survivor["cleared_by_user_id"]
    assert survivor["sustainability_score_variant"] == "FINAL", survivor["sustainability_score_variant"]
    assert survivor["quota_units_reserved"] == 1, survivor["quota_units_reserved"]

    # Nothing was persisted by the rejected call, so the pool did not move again.
    final_species = build.get_species(species_id)
    assert final_species["version"] == stale_version + 1, final_species["version"]
    assert final_species["wild_take_quota_reserved"] == 1, final_species["wild_take_quota_reserved"]


def test_unknown_species_id_in_the_plan_entry_body_returns_species_not_found(api: ApiClient, build: Builder):
    """A body foreign key is resolved before the concurrency guard, so an unknown species is a 404.

    PRD §2.8: "Every foreign key supplied in the request body resolves to an existing row, checked in the order the fields are declared for that endpoint — the entity-specific not-found code, at 404. Applies to the creation of exhibits, collection plan entries, acquisition requests, permits, specimens, veterinary cases, transfer requests and interaction sessions, and to exhibit placements."

    Design: Corner/validations/validation_unknown_species_id_in_the_body_returns_species_not_found
    """
    plant = build.create_plant()
    exhibit = build.create_exhibit(plant)
    assert exhibit["version"] == 1, exhibit["version"]

    refused = api.create_collection_plan_entry(
        factories.collection_plan_entry_payload(
            exhibit["id"], NON_EXISTENT_UUID, exhibit["version"], planned_count=2
        ),
        CURATOR_HEADERS,
    )
    validate_error(refused, ERR_SPECIES_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_collection_plan_entries(CURATOR_HEADERS))
    assert meta["total_count"] == 0, meta

    # The rejected create persisted nothing, so the exhibit's version — the very
    # token that was supplied and was perfectly current — is unchanged.
    reread = build.get_exhibit(exhibit["id"])
    assert reread["version"] == 1, reread["version"]


def test_placement_landing_exactly_on_bioload_capacity_is_admitted_and_flips_the_posture(api: ApiClient, build: Builder):
    """Filling an exhibit to precisely its capacity is allowed and takes the posture to RESTRICTED.

    PRD §2.8: "The exhibit's `occupied_bioload_units` plus the candidate specimen's `bioload_units` does not exceed `bioload_capacity_units` — `ERR_BIOLOAD_CAPACITY_EXCEEDED` (409). Applies to exhibit placement. Landing exactly on capacity is allowed, and may itself flip the posture to `RESTRICTED`."

    Design: Corner/validations/validation_placement_exactly_at_capacity_is_admitted_and_the_next_one_is_not
    """
    world = build.cleared_acquisition(
        requested_count=2,
        species_overrides={"bioload_units_per_specimen": 12.0},
        exhibit_overrides={"bioload_capacity_units": 24.0},
        entry_overrides={"planned_count": 3, "sustainability_requirement": "GREEN_ONLY"},
    )
    first, second = _admit_cleared_specimens(build, world, 2)
    exhibit_id = world["exhibit"]["id"]

    build.place(first["id"], exhibit_id)
    half_full = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(half_full["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(half_full["bioload_utilization_pct"], 50.00)
    assertions.assert_posture(half_full, "OPEN", None)

    # 12.00 + 12.00 is exactly 24 and the comparison is "does not exceed", so the
    # placement is admitted rather than refused.
    at_capacity = validate_success(
        api.place_specimen(
            second["id"],
            factories.placement_payload(exhibit_id, build.exhibit_version(exhibit_id)),
            AQUARIST_HEADERS,
        )
    )
    assert at_capacity["disposition_status"] == "ON_EXHIBIT", at_capacity["disposition_status"]
    squeezed_in = build.get_specimen(second["id"])
    assert squeezed_in["disposition_status"] == "ON_EXHIBIT", squeezed_in["disposition_status"]
    assert squeezed_in["exhibit_id"] == exhibit_id, squeezed_in["exhibit_id"]

    # §3.2: utilisation now reads 100.00, which is strictly greater than 95.00.
    full = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(full["occupied_bioload_units"], 24.00)
    assertions.assert_scaled_equal(full["bioload_utilization_pct"], 100.00)
    assertions.assert_posture(full, "RESTRICTED", "BIOLOAD_PRESSURE")


def test_placement_over_bioload_capacity_needs_the_override_only_to_reach_the_capacity_refusal(api: ApiClient, build: Builder):
    """On a full, RESTRICTED exhibit the override flag is demanded first and the capacity rule refuses next.

    PRD §2.8: "When the target exhibit's `posture` is `RESTRICTED`, `restricted_posture_override` is `true` — `ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED` (409). Applies to exhibit placement only, and is only evaluated when the posture actually is `RESTRICTED`; an `OPEN` exhibit ignores the flag entirely."

    Design: Corner/validations/validation_placement_exactly_at_capacity_is_admitted_and_the_next_one_is_not
    """
    world = build.cleared_acquisition(
        requested_count=3,
        species_overrides={"bioload_units_per_specimen": 12.0},
        exhibit_overrides={"bioload_capacity_units": 24.0},
        entry_overrides={"planned_count": 3, "sustainability_requirement": "GREEN_ONLY"},
    )
    first, second, third = _admit_cleared_specimens(build, world, 3)
    exhibit_id = world["exhibit"]["id"]

    build.place(first["id"], exhibit_id)
    build.place(second["id"], exhibit_id)
    full = build.get_exhibit(exhibit_id)
    assertions.assert_posture(full, "RESTRICTED", "BIOLOAD_PRESSURE")

    # The plan line allows a third animal (2 is below planned_count 3), so the
    # posture flag is the first thing standing in the way.
    without_override = api.place_specimen(
        third["id"],
        factories.placement_payload(exhibit_id, build.exhibit_version(exhibit_id)),
        AQUARIST_HEADERS,
    )
    validate_error(without_override, ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED, 409)

    # With the override the call reaches rank 45, where 24.00 + 12.00 exceeds 24.
    with_override = api.place_specimen(
        third["id"],
        factories.placement_payload(
            exhibit_id, build.exhibit_version(exhibit_id), restricted_posture_override=True
        ),
        AQUARIST_HEADERS,
    )
    validate_error(with_override, ERR_BIOLOAD_CAPACITY_EXCEEDED, 409)

    rejected = build.get_specimen(third["id"])
    assert rejected["disposition_status"] == "CLEARED", rejected["disposition_status"]
    assert rejected["exhibit_id"] is None, rejected["exhibit_id"]

    unchanged = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(unchanged["occupied_bioload_units"], 24.00)
    assertions.assert_scaled_equal(unchanged["bioload_utilization_pct"], 100.00)
    assertions.assert_posture(unchanged, "RESTRICTED", "BIOLOAD_PRESSURE")
