"""Operations and their inverses: the ledger and the quota pool must reconcile exactly.

Each test captures the pre-state, performs the operation, performs the compensating
operation and then asserts the same numbers again — and, where the reserved amount
was gating a second action, that the released allowance genuinely admits it.
"""
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    CLEARANCE_OFFICER_ID,
    Builder,
    factories,
    make_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ERR_BIOLOAD_CAPACITY_EXCEEDED, ERR_QUOTA_EXCEEDED


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def two_cleared_specimens_for_a_tight_exhibit(build: Builder) -> Dict[str, Any]:
    """Two cleared animals of 19.00 bioload units each for a 20-unit exhibit.

    The plan line admits two animals of the species, so the second placement is
    stopped by the ledger rather than by the plan.
    """
    world = build.approved_line(
        exhibit_overrides={"bioload_capacity_units": 20.0},
        species_overrides={
            "taxon_group": "TELEOST",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "bioload_units_per_specimen": 19.0,
            "base_quarantine_days": 30,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    request = build.create_acquisition(world["entry"], source_type="CAPTIVE_BRED", requested_count=2)
    request = build.submit_acquisition(request["id"])
    world["request"] = build.clear_acquisition(request["id"], world["species"]["id"])

    first = build.accession_specimen(world["species"], world["request"])
    second = build.accession_specimen(world["species"], world["request"])
    cases = [build.quarantine_case_of(first["id"]), build.quarantine_case_of(second["id"])]
    exams = build.record_clean_exams(first["id"], 2) + build.record_clean_exams(second["id"], 2)
    build.advance_to(cases[0]["projected_release_at"])
    build.close_clean_exams(exams)
    for case in cases:
        build.review_quarantine(case["id"], "CLEAR")
    world["first"] = build.get_specimen(first["id"])
    world["second"] = build.get_specimen(second["id"])
    return world


def two_wild_requests_against_a_four_unit_quota(build: Builder) -> Dict[str, Any]:
    """A species with an annual take of 4, one CLEARED request for 3 and a rival for 2.

    Both requests carry their own ISSUED import permit, so the only thing standing
    between the second one and clearance is the annual allowance.
    """
    world = build.approved_line(
        species_overrides={
            "taxon_group": "TELEOST",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "bioload_units_per_specimen": 8.0,
            "base_quarantine_days": 30,
            "wild_take_quota_annual": 4,
        },
        entry_overrides={"planned_count": 5, "sustainability_requirement": "GREEN_ONLY"},
    )
    world["institution"] = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=80.00
    )
    documents = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]

    first = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=3,
        source_institution_id=world["institution"]["id"],
    )
    first = build.submit_acquisition(first["id"])
    world["first_permit"] = build.issue_permit(first["id"], "IMPORT", documents)
    world["first_request"] = build.clear_acquisition(first["id"], world["species"]["id"])

    second = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=2,
        source_institution_id=world["institution"]["id"],
    )
    second = build.submit_acquisition(second["id"])
    world["second_permit"] = build.issue_permit(second["id"], "IMPORT", documents)
    world["second_request"] = build.get_acquisition(second["id"])
    return world


def attempt_clearance(api, build: Builder, request_id: str, species_id: str):
    """Clear a request through the raw client so a refusal can be asserted."""
    return api.clear_acquisition_request(
        request_id,
        factories.clearance_payload(build.species_version(species_id)),
        make_director_headers(CLEARANCE_OFFICER_ID),
    )


# --------------------------------------------------------------------------
# Placement and removal are exact inverses on the exhibit ledger
# --------------------------------------------------------------------------
def test_removing_the_specimen_just_placed_restores_the_ledger_to_its_exact_pre_values(build):
    """The ledger returns to 0.00 / 0.00 and a re-placement reproduces 19.00 / 95.00.

    PRD §3.2: "Placement and removal are exact inverses: removing the specimen that was just placed restores both `occupied_bioload_units` and `bioload_utilization_pct` to precisely their pre-placement values."

    Design: Difficulty/compensating_invariant/compensating_exhibit_bioload_ledger_restores_exactly_after_removal
    """
    world = two_cleared_specimens_for_a_tight_exhibit(build)

    before = build.get_exhibit(world["exhibit"]["id"])
    assert before["occupied_bioload_units"] == 0.00, before
    assert before["bioload_utilization_pct"] == 0.00, before
    assert before["posture"] == "OPEN", before
    baseline_version = before["version"]

    placed = build.place(world["first"]["id"], world["exhibit"]["id"])
    assert placed["disposition_status"] == "ON_EXHIBIT", placed
    assert placed["holding_area"] is None, placed
    assert placed["bioload_units"] == 19.00, placed

    loaded = build.get_exhibit(world["exhibit"]["id"])
    assert loaded["occupied_bioload_units"] == 19.00, loaded
    assert loaded["bioload_utilization_pct"] == 95.00, loaded
    # Exactly 95.00 is not strictly greater than 95.00, so the exhibit stays OPEN.
    assert loaded["posture"] == "OPEN", loaded
    assert loaded["last_posture_reason"] is None, loaded
    assert loaded["version"] == baseline_version + 1, loaded

    removed = build.remove(world["first"]["id"], world["exhibit"]["id"], holding_area="QT-BAY-2")
    assert removed["disposition_status"] == "CLEARED", removed
    assert removed["exhibit_id"] is None, removed
    assert removed["holding_area"] == "QT-BAY-2", removed
    assert removed["bioload_units"] == 19.00, removed

    restored = build.get_exhibit(world["exhibit"]["id"])
    assert restored["occupied_bioload_units"] == before["occupied_bioload_units"], restored
    assert restored["bioload_utilization_pct"] == before["bioload_utilization_pct"], restored
    assert restored["occupied_bioload_units"] == 0.00, restored
    assert restored["bioload_utilization_pct"] == 0.00, restored
    assert restored["posture"] == "OPEN", restored
    assert restored["version"] == baseline_version + 2, restored

    build.place(world["first"]["id"], world["exhibit"]["id"])
    again = build.get_exhibit(world["exhibit"]["id"])
    assert again["occupied_bioload_units"] == loaded["occupied_bioload_units"], again
    assert again["bioload_utilization_pct"] == loaded["bioload_utilization_pct"], again
    assert again["occupied_bioload_units"] == 19.00, again
    assert again["bioload_utilization_pct"] == 95.00, again
    assert again["version"] == baseline_version + 3, again


def test_capacity_released_by_a_removal_admits_the_placement_it_had_refused(api, build):
    """The second animal is refused on capacity, then admitted once the first leaves.

    PRD §2.8: "The exhibit's `occupied_bioload_units` plus the candidate specimen's `bioload_units` does not exceed `bioload_capacity_units` — `ERR_BIOLOAD_CAPACITY_EXCEEDED` (409). Applies to exhibit placement."

    Design: Difficulty/compensating_invariant/compensating_exhibit_bioload_ledger_restores_exactly_after_removal
    """
    world = two_cleared_specimens_for_a_tight_exhibit(build)
    build.place(world["first"]["id"], world["exhibit"]["id"])

    occupied = build.get_exhibit(world["exhibit"]["id"])
    assert occupied["occupied_bioload_units"] == 19.00, occupied

    refused = api.place_specimen(
        world["second"]["id"],
        factories.placement_payload(world["exhibit"]["id"], occupied["version"]),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_BIOLOAD_CAPACITY_EXCEEDED, 409)
    assert build.get_specimen(world["second"]["id"])["disposition_status"] == "CLEARED"
    # A refused placement changes nothing about the ledger.
    unchanged = build.get_exhibit(world["exhibit"]["id"])
    assert unchanged["occupied_bioload_units"] == 19.00, unchanged
    assert unchanged["bioload_utilization_pct"] == 95.00, unchanged

    build.remove(world["first"]["id"], world["exhibit"]["id"], holding_area="QT-BAY-2")
    emptied = build.get_exhibit(world["exhibit"]["id"])
    assert emptied["occupied_bioload_units"] == 0.00, emptied
    assert emptied["bioload_utilization_pct"] == 0.00, emptied

    admitted = validate_success(
        api.place_specimen(
            world["second"]["id"],
            factories.placement_payload(world["exhibit"]["id"], emptied["version"]),
            AQUARIST_HEADERS,
        ),
        200,
    )
    assert admitted["disposition_status"] == "ON_EXHIBIT", admitted

    final = build.get_exhibit(world["exhibit"]["id"])
    assert final["occupied_bioload_units"] == 19.00, final
    assert final["bioload_utilization_pct"] == 95.00, final
    assert final["posture"] == "OPEN", final


# --------------------------------------------------------------------------
# Cancellation returns the wild-take reservation to the species pool
# --------------------------------------------------------------------------
def test_second_wild_request_is_refused_while_the_first_holds_three_of_four_units(api, build):
    """Three reserved plus two requested exceeds the annual take of four.

    PRD §2.8: "The species' `wild_take_quota_reserved` plus the request's `requested_count` does not exceed `wild_take_quota_annual` — `ERR_QUOTA_EXCEEDED` (409). Applies to acquisition clearance, and only for a `WILD_COLLECTION` source."

    Design: Difficulty/compensating_invariant/compensating_wild_quota_release_by_cancellation_unblocks_second_request
    """
    world = two_wild_requests_against_a_four_unit_quota(build)

    first = build.get_acquisition(world["first_request"]["id"])
    assert first["status"] == "CLEARED", first
    assert first["quota_units_reserved"] == 3, first
    # 40 (GREEN) + 10 (WILD_COLLECTION) + 0.25 * 80.00 + 5 (permit) - 20 * (3 / 4).
    assert first["sustainability_score"] == 60.00, first
    assert first["sustainability_score_variant"] == "FINAL", first
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 3

    response = attempt_clearance(
        api, build, world["second_request"]["id"], world["species"]["id"]
    )
    validate_error(response, ERR_QUOTA_EXCEEDED, 409)

    second = build.get_acquisition(world["second_request"]["id"])
    assert second["status"] == "PENDING_PERMIT", second
    assert second["quota_units_reserved"] == 0, second
    assert second["sustainability_score"] == 70.00, second
    assert second["sustainability_score_variant"] == "PROVISIONAL", second
    assert second["cleared_by_user_id"] is None, second
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 3


def test_cancelling_the_first_request_returns_its_three_units_to_the_species_pool(build):
    """The reservation goes back to exactly 0 on the request and on the species.

    PRD §3.5: "the cancellation sets `closure_reason` to `CURATOR_CANCELLED`, releases `quota_units_reserved` back into the species' pool and sets it to 0, and revokes every non-terminal permit of the request with `decision_reason` set to `ACQUISITION_CANCELLED`."

    Design: Difficulty/compensating_invariant/compensating_wild_quota_release_by_cancellation_unblocks_second_request
    """
    world = two_wild_requests_against_a_four_unit_quota(build)
    species_before = build.get_species(world["species"]["id"])
    assert species_before["wild_take_quota_reserved"] == 3, species_before
    assert species_before["wild_take_quota_annual"] == 4, species_before

    cancelled = build.cancel_acquisition(world["first_request"]["id"], reason="Season closed early")
    assert cancelled["status"] == "CANCELLED", cancelled
    assert cancelled["closure_reason"] == "CURATOR_CANCELLED", cancelled
    assert cancelled["quota_units_reserved"] == 0, cancelled

    stored = build.get_acquisition(world["first_request"]["id"])
    assert stored["status"] == "CANCELLED", stored
    assert stored["quota_units_reserved"] == 0, stored

    species_after = build.get_species(world["species"]["id"])
    assert species_after["wild_take_quota_reserved"] == 0, species_after
    assert species_after["wild_take_quota_annual"] == 4, species_after

    permit = build.get_permit(world["first_permit"]["id"])
    assert permit["status"] == "REVOKED", permit
    assert permit["decision_reason"] == "ACQUISITION_CANCELLED", permit


def test_released_quota_admits_the_second_wild_request_that_was_refused_before(api, build):
    """The same clearance that failed on quota succeeds after the release, reserving 2.

    PRD §2.8: "Because the reservation is released again by cancellation, plan suspension and permit expiry, the pool must reconcile exactly."

    Design: Difficulty/compensating_invariant/compensating_wild_quota_release_by_cancellation_unblocks_second_request
    """
    world = two_wild_requests_against_a_four_unit_quota(build)

    refused = attempt_clearance(api, build, world["second_request"]["id"], world["species"]["id"])
    validate_error(refused, ERR_QUOTA_EXCEEDED, 409)

    build.cancel_acquisition(world["first_request"]["id"])
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0

    admitted = validate_success(
        attempt_clearance(api, build, world["second_request"]["id"], world["species"]["id"]), 200
    )
    assert admitted["status"] == "CLEARED", admitted
    assert admitted["quota_units_reserved"] == 2, admitted
    # 40 + 10 + 0.25 * 80.00 + 5 (permit) - 20 * (2 / 4), the pool now standing at 0.
    assert admitted["sustainability_score"] == 65.00, admitted
    assert admitted["sustainability_score_variant"] == "FINAL", admitted
    assert admitted["cleared_by_user_id"] == CLEARANCE_OFFICER_ID, admitted

    stored = build.get_acquisition(world["second_request"]["id"])
    assert stored["status"] == "CLEARED", stored
    assert stored["quota_units_reserved"] == 2, stored
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 2
