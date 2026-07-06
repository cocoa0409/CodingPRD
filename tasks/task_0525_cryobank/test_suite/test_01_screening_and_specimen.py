"""Donor screening branch divergence, specimen quarantine release guards.

Queue-A (Difficulty) translations for non_linear_state_machine (screening
branch), cross_entity_state_dependency (release requires donor APPROVED), and
priority_pair_validation_conflict (retest vs quarantine on release).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS,
    create_under_review_application,
)

CM = TEST_USERS["catalog_manager_headers"]

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_screening_approve_branch_sets_donor_approved_and_fda_eligible(api):
    """PRD §3.1: "On approval the donor's status becomes APPROVED, its
    fda_eligible flag is set to true, and its genetic_panel_clear flag is set to
    true exactly when the application's genetic_carrier_count equals 0 (and false
    otherwise)."

    Design: Difficulty/non_linear_state_machine/screening_branch_approve_vs_defer_divergent_effects
    """
    donor_id, app_id = create_under_review_application(display_code="D-5a")
    data = validate_success(api.approve_application(app_id, SO))
    assert data["status"] == "APPROVED"
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["status"] == "APPROVED"
    assert donor["fda_eligible"] is True


def test_screening_defer_branch_sets_donor_deferred(api):
    """PRD §3.1: "Deferral advances the application UNDER_REVIEW -> DEFERRED, a
    terminal outcome, requiring only that the application currently be UNDER_REVIEW."
    PRD §3.4: "Deferring a donor's screening application ... sets the donor's status
    to DEFERRED and cascades across all of the donor's material".

    Design: Difficulty/non_linear_state_machine/screening_branch_approve_vs_defer_divergent_effects
    """
    donor_id, app_id = create_under_review_application(display_code="D-5b")
    data = validate_success(api.defer_application(app_id, SO))
    assert data["status"] == "DEFERRED"
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["status"] == "DEFERRED"


def test_release_quarantine_with_donor_approved_succeeds_and_activates_donor(api):
    """PRD §3.2: "Releasing quarantine is a ComplianceOfficer action that advances
    the specimen QUARANTINE -> RELEASED. It is permitted only when the specimen is
    in QUARANTINE, its retest_negative is true, the current logical time has reached
    the specimen's quarantine_release_date ..., and the donor is APPROVED."
    PRD §3.2: "On the donor's first ever released specimen, the donor's status
    advances to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/specimen_release_requires_donor_approved
    """
    donor_id, app_id = create_under_review_application(display_code="D-13")
    validate_success(api.approve_application(app_id, SO))
    specimen = validate_success(api.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }, LT), expected_status=201)
    validate_success(api.begin_quarantine(specimen["id"], "T-13", LT))
    validate_success(api.set_clock("2026-06-01T00:00:00Z", CO))
    data = validate_success(api.release_quarantine(specimen["id"], CO))
    assert data["status"] == "RELEASED"
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["status"] == "ACTIVE", "first-release side effect: donor -> ACTIVE"


def test_release_quarantine_lists_inventory(api):
    """PRD §3.2: "Release also recomputes the listability of that specimen's
    inventory lot." PRD §3.2: "An inventory lot's readiness for catalog listing is
    captured by its computed is_listed flag. A lot is listed exactly when its
    specimen is RELEASED, its donor is ACTIVE, the donor has not reached its family
    limit ..., its hold_status is OPEN, and its available_vials is greater than 0."

    Design: Difficulty/cross_entity_state_dependency/specimen_release_requires_donor_approved
    """
    donor_id, app_id = create_under_review_application(display_code="D-13b")
    validate_success(api.approve_application(app_id, SO))
    specimen = validate_success(api.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }, LT), expected_status=201)
    validate_success(api.begin_quarantine(specimen["id"], "T-13b", LT))
    inv_list = validate_success(api.list_donor_inventories(
        CO, params={"specimen_id": specimen["id"]}))
    inv_id = inv_list[0]["id"]
    before = validate_success(api.get_donor_inventory(inv_id, CO))
    assert before["is_listed"] is False, "not listed while specimen still QUARANTINE"
    validate_success(api.set_clock("2026-06-01T00:00:00Z", CO))
    validate_success(api.release_quarantine(specimen["id"], CO))
    after = validate_success(api.get_donor_inventory(inv_id, CO))
    assert after["is_listed"] is True, "release + donor ACTIVE + vials -> listed"


def test_release_quarantine_retest_false_and_before_date_rejected(api):
    """PRD §3.2: "A release attempt where retest_negative is still false is
    rejected with ERR_RETEST_NOT_NEGATIVE; a release attempt before the quarantine
    window has elapsed — the current UTC instant still earlier than
    quarantine_release_date — is rejected with ERR_QUARANTINE_NOT_ELAPSED."

    PRD does not state which of these two release-time checks pre-empts the other,
    so the rejection error is accepted as either (error-precedence silence pattern);
    the specimen must remain QUARANTINE.

    Design: Difficulty/priority_pair_validation_conflict/retest_vs_quarantine_temporal_release
    """
    donor_id, app_id = create_under_review_application(display_code="D-9")
    validate_success(api.approve_application(app_id, SO))
    specimen = validate_success(api.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": False,
    }, LT), expected_status=201)
    validate_success(api.begin_quarantine(specimen["id"], "T-9", LT))
    # clock still at default 2026-05-01 (before release date); retest false too.
    resp = api.release_quarantine(specimen["id"], CO)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_RETEST_NOT_NEGATIVE.value,
        ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED.value,
    ])
    spec = validate_success(api.get_specimen(specimen["id"], CO))
    assert spec["status"] == "QUARANTINE", "specimen unchanged after rejected release"


def test_release_quarantine_retest_false_after_date_returns_retest_error(api):
    """PRD §3.2: "A release attempt where retest_negative is still false is rejected
    with ERR_RETEST_NOT_NEGATIVE".

    Clock advanced past quarantine_release_date so only the retest check can fail,
    isolating ERR_RETEST_NOT_NEGATIVE deterministically.

    Design: Difficulty/priority_pair_validation_conflict/retest_vs_quarantine_temporal_release
    """
    donor_id, app_id = create_under_review_application(display_code="D-9b")
    validate_success(api.approve_application(app_id, SO))
    specimen = validate_success(api.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": False,
    }, LT), expected_status=201)
    validate_success(api.begin_quarantine(specimen["id"], "T-9b", LT))
    validate_success(api.set_clock("2026-06-02T00:00:00Z", CO))
    resp = api.release_quarantine(specimen["id"], CO)
    validate_error(resp, ApiErrorId.ERR_RETEST_NOT_NEGATIVE.value)
    spec = validate_success(api.get_specimen(specimen["id"], CO))
    assert spec["status"] == "QUARANTINE"
