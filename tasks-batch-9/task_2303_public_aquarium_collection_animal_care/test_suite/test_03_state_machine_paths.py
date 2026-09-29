"""Non-linear state machine paths: bounded revision cycles and orthogonal dimensions.

Every world in this module is assembled through the published endpoints, so each
test starts from the empty database and the logical clock parked at the epoch.
"""
from typing import Any, Dict

from test_helpers import (
    PERMIT_OFFICER_HEADERS,
    VET_HEADERS,
    assertions,
    get_success_data,
    validate_error,
)
from test_helpers.api_errors import (
    ERR_INVALID_ACTION,
    ERR_ROUND_LIMIT_EXCEEDED,
)

IMPORT_DOCUMENTS = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]

SPECIES_OVERRIDES = {
    "taxon_group": "TELEOST",
    "protection_status": "UNLISTED",
    "sustainability_rating": "GREEN",
    "bioload_units_per_specimen": 12.0,
    "base_quarantine_days": 30,
    "wild_take_quota_annual": 4,
}
ENTRY_OVERRIDES = {"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"}
PLANT_OVERRIDES = {"redundancy_test_interval_days": 90}


def _instant_seconds(value: str) -> str:
    """An ISO-8601 UTC instant reduced to whole seconds for comparison.

    PRD §2.4 fixes the fractional precision of `created_at` only; the precision
    used to render domain instants such as `started_at` or
    `projected_release_at` is left open, so comparisons here pin the instant and
    not its rendering.
    """
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return text + "Z"


# --------------------------------------------------------------------------
# World builders (setup only; every call here must succeed)
# --------------------------------------------------------------------------
def _wild_collection_request_with_submitted_permit(build) -> Dict[str, Any]:
    """A WILD_COLLECTION request in PENDING_PERMIT with a once-submitted IMPORT permit."""
    world = build.approved_line(
        plant_overrides=dict(PLANT_OVERRIDES),
        species_overrides=dict(SPECIES_OVERRIDES),
        entry_overrides=dict(ENTRY_OVERRIDES),
    )
    institution = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=80.0
    )
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request = build.submit_acquisition(request["id"])
    permit = build.draft_permit(request["id"], "IMPORT", IMPORT_DOCUMENTS)
    permit = build.submit_permit(permit["id"])
    world["institution"] = institution
    world["request"] = request
    world["permit"] = permit
    return world


def _quarantined_teleost(build) -> Dict[str, Any]:
    """A freshly accessioned TELEOST specimen with a 30-day ACTIVE quarantine case."""
    return build.quarantined_specimen(
        plant_overrides=dict(PLANT_OVERRIDES),
        species_overrides=dict(SPECIES_OVERRIDES),
        entry_overrides=dict(ENTRY_OVERRIDES),
    )


def _specimen_on_exhibit_under_no_treatment(build) -> Dict[str, Any]:
    """A cleared specimen of 12.00 bioload units placed on a 100-unit exhibit."""
    world = build.cleared_specimen(
        plant_overrides=dict(PLANT_OVERRIDES),
        species_overrides=dict(SPECIES_OVERRIDES),
        entry_overrides=dict(ENTRY_OVERRIDES),
    )
    specimen_id = world["specimen"]["id"]
    build.place(specimen_id, world["exhibit"]["id"])
    world["specimen"] = build.get_specimen(specimen_id)
    build.advance_to("2026-09-01T00:00:00Z")
    return world


def _open_treatment(build, specimen_id: str) -> Dict[str, Any]:
    return build.open_vet_case(
        specimen_id,
        "TREATMENT",
        opened_at="2026-09-01T00:00:00Z",
        treatment_start_at="2026-09-01T00:00:00Z",
        withdrawal_days=10,
        diagnosis_code="DERM-014",
    )


def _extension_days(days: int, reason: str) -> Dict[str, Any]:
    return {"outcome": "EXTEND", "extension_days": days, "reason": reason}


def _read_veterinary_case(build, case_id: str) -> Dict[str, Any]:
    """Read one veterinary case back through its own endpoint."""
    return get_success_data(build.api.get_veterinary_case(case_id, VET_HEADERS))


# --------------------------------------------------------------------------
# Permit revision cycle: SUBMITTED -> INFO_REQUESTED -> SUBMITTED
# --------------------------------------------------------------------------
def test_permit_resubmission_after_an_information_request_counts_a_fresh_round(build):
    """Each INFO_REQUESTED to SUBMITTED lap increments submission_round up to the ceiling of 3.

    PRD §3.5: "A successful submission moves the permit to `SUBMITTED`, increments
    `submission_round` by 1, empties `missing_document_codes` and clears
    `decision_reason` to null so that a revision round does not carry the previous
    round's complaint."

    Design: Difficulty/non_linear_state_machine/nonlinear_permit_info_requested_revision_cycle_hits_round_ceiling
    """
    world = _wild_collection_request_with_submitted_permit(build)
    permit_id = world["permit"]["id"]

    assertions.assert_permit(world["permit"])
    assert world["permit"]["status"] == "SUBMITTED"
    assert world["permit"]["submission_round"] == 1
    assert world["permit"]["missing_document_codes"] == []

    # First lap back to the authority: the decision parks the dossier without
    # touching the round counter, and only the resubmission advances it.
    first_query = build.decide_permit(
        permit_id, "REQUEST_INFO", reason="origin declaration illegible"
    )
    assert first_query["status"] == "INFO_REQUESTED"
    assert first_query["submission_round"] == 1
    assert first_query["decision_reason"] == "origin declaration illegible"

    second_round = build.submit_permit(permit_id)
    assert second_round["status"] == "SUBMITTED"
    assert second_round["submission_round"] == 2
    assert second_round["decision_reason"] is None
    assert second_round["missing_document_codes"] == []

    # Second lap: SUBMITTED is re-entered a third time, and 3 is the ceiling
    # itself, which the specification allows.
    second_query = build.decide_permit(
        permit_id, "REQUEST_INFO", reason="health certificate stale"
    )
    assert second_query["status"] == "INFO_REQUESTED"
    assert second_query["submission_round"] == 2

    third_round = build.submit_permit(permit_id)
    assert third_round["status"] == "SUBMITTED"
    assert third_round["submission_round"] == 3

    stored = build.get_permit(permit_id)
    assert stored["status"] == "SUBMITTED"
    assert stored["submission_round"] == 3


def test_fourth_permit_submission_is_refused_and_leaves_the_permit_in_info_requested(
    build, api
):
    """A fourth submission breaks the ceiling of 3 and performs no transition at all.

    PRD §2.8: "A round counter would not exceed its ceiling —
    `ERR_ROUND_LIMIT_EXCEEDED` (409). Applies to permit submission (at most 3
    submission rounds), transfer decisions (at most 2 counters) and quarantine
    reviews (at most 2 extensions). Reaching the ceiling is allowed; the attempt
    that would pass it fails."

    Design: Difficulty/non_linear_state_machine/nonlinear_permit_info_requested_revision_cycle_hits_round_ceiling
    """
    world = _wild_collection_request_with_submitted_permit(build)
    permit_id = world["permit"]["id"]

    build.decide_permit(permit_id, "REQUEST_INFO", reason="origin declaration illegible")
    build.submit_permit(permit_id)
    build.decide_permit(permit_id, "REQUEST_INFO", reason="health certificate stale")
    build.submit_permit(permit_id)
    at_ceiling = build.decide_permit(
        permit_id, "REQUEST_INFO", reason="third clarification"
    )
    assert at_ceiling["status"] == "INFO_REQUESTED"
    assert at_ceiling["submission_round"] == 3

    refused = api.submit_permit(permit_id, {}, PERMIT_OFFICER_HEADERS)
    validate_error(refused, ERR_ROUND_LIMIT_EXCEEDED, 409)

    # The counter, not the state, decided the refusal — so the permit must not
    # have been flipped to SUBMITTED on the way to the check.
    stored = build.get_permit(permit_id)
    assert stored["status"] == "INFO_REQUESTED"
    assert stored["submission_round"] == 3

    # The dossier's parent is untouched by the whole revision cycle: neither a
    # REQUEST_INFO decision nor a refused submission moves the request.
    parent = build.get_acquisition(world["request"]["id"])
    assert parent["status"] == "PENDING_PERMIT"
    assert parent["sustainability_score_variant"] == "PROVISIONAL"
    assert parent["cleared_at"] is None


# --------------------------------------------------------------------------
# Two orthogonal dimensions on one specimen
# --------------------------------------------------------------------------
def test_opening_a_treatment_case_advances_only_the_clinical_dimension(build):
    """A treatment moves health_status alone and leaves the animal on exhibit.

    PRD §3.7: "Opening a `TREATMENT` case moves the clinical dimension to
    `UNDER_TREATMENT` — from `HEALTHY`, from `CRITICAL_CARE`, or from
    `UNDER_TREATMENT` itself for a second concurrent treatment — recomputes
    `treatment_withdrawal_until`, and recomputes the `ROLLING` welfare score,
    which drops because a new open-treatment penalty now applies."

    Design: Difficulty/non_linear_state_machine/nonlinear_specimen_two_dimensions_advance_independently
    """
    world = _specimen_on_exhibit_under_no_treatment(build)
    specimen_id = world["specimen"]["id"]
    exhibit_id = world["exhibit"]["id"]

    before = build.get_specimen(specimen_id)
    assert before["disposition_status"] == "ON_EXHIBIT"
    assert before["health_status"] == "HEALTHY"

    case = _open_treatment(build, specimen_id)
    assertions.assert_veterinary_case(case)
    assert case["status"] == "OPEN"
    assert case["case_type"] == "TREATMENT"

    specimen = build.get_specimen(specimen_id)
    assert specimen["health_status"] == "UNDER_TREATMENT"
    # The disposition dimension has not moved: the animal is still in the tank.
    assert specimen["disposition_status"] == "ON_EXHIBIT"
    assert specimen["exhibit_id"] == exhibit_id
    # The half-open window ends 10 days after the treatment start.
    assert _instant_seconds(specimen["treatment_withdrawal_until"]) == "2026-09-11T00:00:00Z"

    # A clinical event is not a ledger event: the specimen is still ON_EXHIBIT,
    # so it still consumes its 12.00 bioload units.
    exhibit = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(exhibit["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(exhibit["bioload_utilization_pct"], 12.00)
    assertions.assert_posture(exhibit, "OPEN", None)


def test_removing_a_specimen_under_treatment_advances_only_the_disposition_dimension(
    build,
):
    """Removal returns the disposition to CLEARED and leaves health_status UNDER_TREATMENT.

    PRD §3.6: "The specimen's `disposition_status` returns to `CLEARED`, its
    `exhibit_id` becomes null, its `holding_area` takes the supplied value, and
    the exhibit's `occupied_bioload_units` and `bioload_utilization_pct` are
    restored exactly before the posture is recomputed."

    Design: Difficulty/non_linear_state_machine/nonlinear_specimen_two_dimensions_advance_independently
    """
    world = _specimen_on_exhibit_under_no_treatment(build)
    specimen_id = world["specimen"]["id"]
    exhibit_id = world["exhibit"]["id"]
    case = _open_treatment(build, specimen_id)

    build.remove(specimen_id, exhibit_id, holding_area="HOLD-B")

    specimen = build.get_specimen(specimen_id)
    assert specimen["disposition_status"] == "CLEARED"
    assert specimen["exhibit_id"] is None
    assert specimen["holding_area"] == "HOLD-B"
    # The clinical dimension is untouched by the move to holding: the animal
    # ends in the (CLEARED, UNDER_TREATMENT) pair a single status field could
    # not represent.
    assert specimen["health_status"] == "UNDER_TREATMENT"
    assert _instant_seconds(specimen["treatment_withdrawal_until"]) == "2026-09-11T00:00:00Z"

    exhibit = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(exhibit["occupied_bioload_units"], 0.00)
    assertions.assert_scaled_equal(exhibit["bioload_utilization_pct"], 0.00)
    assertions.assert_posture(exhibit, "OPEN", None)

    # The removal is not a clinical event either: the treatment case stays open.
    reread_case = _read_veterinary_case(build, case["id"])
    assert reread_case["status"] == "OPEN"
    assert reread_case["case_type"] == "TREATMENT"
    assert reread_case["closed_at"] is None


# --------------------------------------------------------------------------
# Quarantine extend / resume cycle and the extension ceiling
# --------------------------------------------------------------------------
def test_quarantine_extend_and_resume_cycle_accumulates_the_release_date(build):
    """Each EXTEND pushes projected_release_at by the cumulative extension days.

    PRD §3.6: "It increments `extension_count`, adds `extension_days` into
    `total_extension_days` and recomputes `projected_release_at` from
    `started_at` plus (`protocol_days` plus `total_extension_days`) days."

    Design: Difficulty/non_linear_state_machine/nonlinear_quarantine_extend_resume_cycle_then_extension_ceiling
    """
    world = _quarantined_teleost(build)
    case_id = world["quarantine_case"]["id"]

    opened = build.get_quarantine_case(case_id)
    assertions.assert_quarantine_case(opened)
    assert opened["status"] == "ACTIVE"
    assert opened["protocol_days"] == 30
    assert opened["extension_count"] == 0
    assert opened["total_extension_days"] == 0
    assert _instant_seconds(opened["started_at"]) == "2026-08-01T00:00:00Z"
    assert _instant_seconds(opened["projected_release_at"]) == "2026-08-31T00:00:00Z"

    first = build.review_quarantine(
        case_id, "EXTEND", extension_days=10, reason="gill biopsy pending"
    )
    assert first["status"] == "EXTENDED"
    assert first["extension_count"] == 1
    assert first["total_extension_days"] == 10
    assert _instant_seconds(first["projected_release_at"]) == "2026-09-10T00:00:00Z"

    # ACTIVE is re-entered, and RESUME changes nothing else.
    resumed = build.review_quarantine(case_id, "RESUME")
    assert resumed["status"] == "ACTIVE"
    assert resumed["extension_count"] == 1
    assert resumed["total_extension_days"] == 10
    assert _instant_seconds(resumed["projected_release_at"]) == "2026-09-10T00:00:00Z"

    # The second extension is the ceiling itself, which is allowed, and the
    # release date moves by the cumulative 20 days rather than the last 10.
    second = build.review_quarantine(
        case_id, "EXTEND", extension_days=10, reason="second biopsy"
    )
    assert second["status"] == "EXTENDED"
    assert second["extension_count"] == 2
    assert second["total_extension_days"] == 20
    assert _instant_seconds(second["projected_release_at"]) == "2026-09-20T00:00:00Z"

    resumed_again = build.review_quarantine(case_id, "RESUME")
    assert resumed_again["status"] == "ACTIVE"
    assert resumed_again["extension_count"] == 2
    assert _instant_seconds(resumed_again["projected_release_at"]) == "2026-09-20T00:00:00Z"

    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "QUARANTINE"


def test_third_quarantine_extension_is_refused_once_two_extensions_are_recorded(
    build, api
):
    """From ACTIVE with two extensions already spent, EXTEND breaks the ceiling of 2.

    PRD §3.6: "`extension_count` plus 1 must be no greater than 2, else
    `ERR_ROUND_LIMIT_EXCEEDED`, and `extension_days` must be between 1 and 30."

    Design: Difficulty/non_linear_state_machine/nonlinear_quarantine_extend_resume_cycle_then_extension_ceiling
    """
    world = _quarantined_teleost(build)
    case_id = world["quarantine_case"]["id"]

    build.review_quarantine(case_id, "EXTEND", extension_days=10, reason="gill biopsy pending")
    build.review_quarantine(case_id, "RESUME")
    build.review_quarantine(case_id, "EXTEND", extension_days=10, reason="second biopsy")
    build.review_quarantine(case_id, "RESUME")

    # The case is ACTIVE again, exactly as it was before the first extension, so
    # only the counter can distinguish this attempt from a legal one.
    refused = api.create_quarantine_review(
        case_id, _extension_days(5, "third biopsy"), VET_HEADERS
    )
    validate_error(refused, ERR_ROUND_LIMIT_EXCEEDED, 409)

    stored = build.get_quarantine_case(case_id)
    assert stored["status"] == "ACTIVE"
    assert stored["extension_count"] == 2
    assert stored["total_extension_days"] == 20
    assert _instant_seconds(stored["projected_release_at"]) == "2026-09-20T00:00:00Z"
    assert stored["clearance_exam_count"] == 0

    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "QUARANTINE"


def test_clearing_an_extended_quarantine_case_is_an_invalid_action(build, api):
    """CLEAR is not a declared outcome from EXTENDED, whatever the clock says.

    PRD §3.6: "Clearing is legal **only** from `ACTIVE`: an `EXTENDED` case must
    be resumed first, and a `CLEAR` outcome against it is `ERR_INVALID_ACTION`."

    Design: Difficulty/non_linear_state_machine/nonlinear_quarantine_extend_resume_cycle_then_extension_ceiling
    """
    world = _quarantined_teleost(build)
    case_id = world["quarantine_case"]["id"]

    extended = build.review_quarantine(
        case_id, "EXTEND", extension_days=10, reason="gill biopsy pending"
    )
    assert extended["status"] == "EXTENDED"

    # The clock is still the arrival instant and no clean exams exist, so the
    # release-date and exam-count complaints both hold too; the invalid-action
    # rule outranks them.
    refused = api.create_quarantine_review(case_id, {"outcome": "CLEAR"}, VET_HEADERS)
    validate_error(refused, ERR_INVALID_ACTION, 422)

    stored = build.get_quarantine_case(case_id)
    assert stored["status"] == "EXTENDED"
    assert stored["extension_count"] == 1
    assert stored["total_extension_days"] == 10
    assert stored["cleared_at"] is None
    assert stored["cleared_by_user_id"] is None

    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "QUARANTINE"
