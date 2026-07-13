"""Validation-precedence, boundary-precision, and cross-entity state-dependency tests."""
import pytest

from test_helpers import (
    validate_error, get_success_data,
    make_researcher_headers, TEST_USERS,
    create_active_project, create_draft_project, provision_client, provision_researcher,
    create_completed_search, create_person, add_citation, setup_person_under_review,
    log_time, log_time_data, api_client,
)
from test_helpers.factories import (
    create_record_search_payload, create_citation_payload, create_dna_payload,
    create_appointment_payload, create_time_entry_payload,
)

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# priority_pair_validation_conflict / time_entry_state_beats_fiscal_returns_project_not_active
# ==========================================================================
class TestTimeEntryStateBeatsFiscal:
    """PRD §3.2 pins the project-active check ahead of the budget check, so a
    not-ACTIVE project pre-empts a cap breach with ERR_PROJECT_NOT_ACTIVE."""

    def test_closed_project_cap_breach_returns_not_active(self):
        """PRD §3.2: "Logging time is admissible only when the owning project is
        `ACTIVE`; otherwise the attempt fails with `ERR_PROJECT_NOT_ACTIVE` (this
        project-active check is evaluated before the budget check)."

        Design: Difficulty/priority_pair_validation_conflict/time_entry_state_beats_fiscal_returns_project_not_active
        """
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=2)
        get_success_data(api_client.close_project(project["id"], PM))
        # 10 hours would blow the 1.5x=3.0 cap, but the closed-state check fires first.
        resp = log_time(project["id"], researcher["id"], hours=10, billable=True)
        validate_error(resp, "ERR_PROJECT_NOT_ACTIVE")

    def test_draft_project_cap_breach_returns_not_active(self):
        """PRD §3.2: "Logging time is admissible only when the owning project is
        `ACTIVE`; otherwise the attempt fails with `ERR_PROJECT_NOT_ACTIVE` (this
        project-active check is evaluated before the budget check)."

        Design: Difficulty/priority_pair_validation_conflict/time_entry_state_beats_fiscal_returns_project_not_active
        """
        client = provision_client()
        researcher = provision_researcher()
        project = create_draft_project(client["id"], researcher["id"],
                                       package_type="BASIC_PACKAGE",
                                       package_price_cents=100000, budget_hours=2)
        # Never activated: project is DRAFT (not ACTIVE); 10h would also breach the cap.
        resp = log_time(project["id"], researcher["id"], hours=10, billable=True)
        validate_error(resp, "ERR_PROJECT_NOT_ACTIVE")


# ==========================================================================
# priority_pair_validation_conflict / citation_referential_beats_constraint_returns_cross_project
# ==========================================================================
class TestCitationReferentialBeatsConstraint:
    def _two_projects(self):
        client = provision_client()
        researcher = provision_researcher()
        proj_a = create_draft_project(client["id"], researcher["id"], title="PA")
        proj_a = get_success_data(api_client.activate_project(proj_a["id"], PM))
        proj_b = create_draft_project(client["id"], researcher["id"], title="PB")
        proj_b = get_success_data(api_client.activate_project(proj_b["id"], PM))
        return researcher, proj_a, proj_b

    def test_cross_project_wins_over_incomplete_search(self):
        """PRD §3.4: "Two guards protect citation creation and are evaluated in this
        order after the referenced search and person are confirmed to exist: the
        search and the person must belong to the same project, or the request fails
        with `ERR_CROSS_PROJECT_REFERENCE`; and the referenced record search must be
        in `COMPLETED`, since a search that has not produced results cannot be cited,
        or the request fails with `ERR_SEARCH_NOT_COMPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/citation_referential_beats_constraint_returns_cross_project
        """
        researcher, proj_a, proj_b = self._two_projects()
        rh = make_researcher_headers(researcher["id"])
        # PENDING search in project A (so search-not-completed would also fire).
        search_a = get_success_data(api_client.create_record_search(
            create_record_search_payload(project_id=proj_a["id"], search_terms="x"), rh))
        person_b = create_person(proj_b["id"], researcher["id"], full_name="Cross Person")
        resp = api_client.create_citation(
            create_citation_payload(record_search_id=search_a["id"], person_id=person_b["id"],
                                   citation_text="x", source_type="CENSUS", quality="PRIMARY"), rh)
        validate_error(resp, "ERR_CROSS_PROJECT_REFERENCE")

    def test_cross_project_detected_with_completed_search(self):
        """PRD §3.4: "the search and the person must belong to the same project, or
        the request fails with `ERR_CROSS_PROJECT_REFERENCE`".

        Design: Difficulty/priority_pair_validation_conflict/citation_referential_beats_constraint_returns_cross_project
        """
        researcher, proj_a, proj_b = self._two_projects()
        # COMPLETED search in project A -> only the cross-project violation remains.
        search_a = create_completed_search(proj_a["id"], researcher["id"], search_terms="y")
        person_b = create_person(proj_b["id"], researcher["id"], full_name="Cross Person 2")
        rh = make_researcher_headers(researcher["id"])
        resp = api_client.create_citation(
            create_citation_payload(record_search_id=search_a["id"], person_id=person_b["id"],
                                   citation_text="y", source_type="CENSUS", quality="PRIMARY"), rh)
        validate_error(resp, "ERR_CROSS_PROJECT_REFERENCE")


# ==========================================================================
# boundary_precision_check / hours_cap_boundary_at_exact_1_5x_budget
# ==========================================================================
class TestHoursCapBoundary:
    """PRD §3.2: cap is 1.5 * budget_hours; budget_hours 2 -> cap 3.0. The boundary
    is strict (> cap rejects), so exactly 3.0 is accepted and 3.5 is rejected."""

    def test_at_exact_cap_accepted(self):
        """PRD §3.2: "when the entry is billable, the project's current
        `consumed_hours` plus the new entry's billable `hours` must not exceed 1.5
        times `budget_hours`; a log that would push the running billable total past
        that hard cap is rejected with `ERR_HOURS_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/hours_cap_boundary_at_exact_1_5x_budget
        """
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=2)
        entry = log_time_data(project["id"], researcher["id"], hours=3, billable=True)
        assert entry["status"] == "ACTIVE"
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["consumed_hours"] == pytest.approx(3.0, abs=0.001), (
            f"consumed_hours must sit exactly at the cap 3.0, got {proj['consumed_hours']}")

    def test_over_cap_rejected(self):
        """PRD §3.2: "a log that would push the running billable total past that hard
        cap is rejected with `ERR_HOURS_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/hours_cap_boundary_at_exact_1_5x_budget
        """
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=2)
        log_time_data(project["id"], researcher["id"], hours=3, billable=True)  # at cap 3.0
        resp = log_time(project["id"], researcher["id"], hours=0.5, billable=True)  # -> 3.5 > 3.0
        validate_error(resp, "ERR_HOURS_CAP_EXCEEDED")
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["consumed_hours"] == pytest.approx(3.0, abs=0.001), (
            f"a rejected over-cap log must not change consumed_hours, got {proj['consumed_hours']}")


# ==========================================================================
# boundary_precision_check / person_verify_insufficient_citations_count_boundary
# ==========================================================================
class TestPersonVerifyCitationCountBoundary:
    """PRD §3.4: verifying a Person requires at least 2 VERIFIED citations; below
    the floor of 2 fails with ERR_INSUFFICIENT_CITATIONS."""

    def test_one_verified_citation_rejected(self):
        """PRD §3.4: "must have at least 2 `VERIFIED` citations (else
        `ERR_INSUFFICIENT_CITATIONS`)".

        Design: Difficulty/boundary_precision_check/person_verify_insufficient_citations_count_boundary
        """
        client, researcher, project = create_active_project()
        person = setup_person_under_review(project["id"], researcher["id"], full_name="Solo Cite")
        search = create_completed_search(project["id"], researcher["id"], search_terms="solo")
        add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                     source_type="VITAL_RECORD", citation_text="Birth", verify=True)
        rh = make_researcher_headers(researcher["id"])
        resp = api_client.verify_person(person["id"], rh)
        validate_error(resp, "ERR_INSUFFICIENT_CITATIONS")

    def test_zero_verified_citations_rejected(self):
        """PRD §3.4: "must have at least 2 `VERIFIED` citations (else
        `ERR_INSUFFICIENT_CITATIONS`)".

        Design: Difficulty/boundary_precision_check/person_verify_insufficient_citations_count_boundary
        """
        client, researcher, project = create_active_project()
        person = setup_person_under_review(project["id"], researcher["id"], full_name="No Cite")
        rh = make_researcher_headers(researcher["id"])
        resp = api_client.verify_person(person["id"], rh)
        validate_error(resp, "ERR_INSUFFICIENT_CITATIONS")


# ==========================================================================
# cross_entity_state_dependency / record_search_requires_project_active
# ==========================================================================
class TestRecordSearchRequiresActiveProject:
    def test_search_on_draft_project_rejected(self):
        """PRD §3.3: "Research proceeds through `RecordSearch` records logged by a
        researcher (or a project manager) against an `ACTIVE` project; a search
        created against a project that is not `ACTIVE` is rejected with
        `ERR_PROJECT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/record_search_requires_project_active
        """
        client = provision_client()
        researcher = provision_researcher()
        project = create_draft_project(client["id"], researcher["id"])  # never activated
        rh = make_researcher_headers(researcher["id"])
        resp = api_client.create_record_search(
            create_record_search_payload(project_id=project["id"], search_terms="x"), rh)
        validate_error(resp, "ERR_PROJECT_NOT_ACTIVE")

    def test_search_on_closed_project_rejected(self):
        """PRD §3.3: "a search created against a project that is not `ACTIVE` is
        rejected with `ERR_PROJECT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/record_search_requires_project_active
        """
        client, researcher, project = create_active_project()
        get_success_data(api_client.close_project(project["id"], PM))
        rh = make_researcher_headers(researcher["id"])
        resp = api_client.create_record_search(
            create_record_search_payload(project_id=project["id"], search_terms="x"), rh)
        validate_error(resp, "ERR_PROJECT_NOT_ACTIVE")


# ==========================================================================
# cross_entity_state_dependency / dna_interpret_requires_subject_verified
# ==========================================================================
class TestDnaInterpretRequiresVerifiedSubject:
    def test_draft_subject_rejected(self):
        """PRD §3.5: "Interpretation is admissible only when the interpretation is
        `ORDERED` and the subject person is `VERIFIED`; if the subject is not
        verified the request fails with `ERR_SUBJECT_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/dna_interpret_requires_subject_verified
        """
        client, researcher, project = create_active_project()
        person = create_person(project["id"], researcher["id"], full_name="Unverified Subject")
        rh = make_researcher_headers(researcher["id"])
        dna = get_success_data(api_client.create_dna_interpretation(
            create_dna_payload(project_id=project["id"], subject_person_id=person["id"],
                              test_provider="AncestryDNA"), rh))
        resp = api_client.interpret_dna(dna["id"], {"cm_shared": 800}, rh)
        validate_error(resp, "ERR_SUBJECT_NOT_VERIFIED")

    def test_under_review_subject_rejected(self):
        """PRD §3.5: "Interpretation is admissible only when the interpretation is
        `ORDERED` and the subject person is `VERIFIED`; if the subject is not
        verified the request fails with `ERR_SUBJECT_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/dna_interpret_requires_subject_verified
        """
        client, researcher, project = create_active_project()
        person = setup_person_under_review(project["id"], researcher["id"],
                                           full_name="Pending Subject")
        rh = make_researcher_headers(researcher["id"])
        dna = get_success_data(api_client.create_dna_interpretation(
            create_dna_payload(project_id=project["id"], subject_person_id=person["id"],
                              test_provider="AncestryDNA"), rh))
        resp = api_client.interpret_dna(dna["id"], {"cm_shared": 800}, rh)
        validate_error(resp, "ERR_SUBJECT_NOT_VERIFIED")


# ==========================================================================
# Corner / validations
# ==========================================================================
def test_appointment_end_before_start_returns_invalid_interval():
    """PRD §3.6: "the interval itself must be well-formed: `end_utc` must be
    strictly after `start_utc`, or the request is rejected with
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/appointment_end_before_start_returns_invalid_interval_422
    """
    client, researcher, project = create_active_project()
    repo = get_success_data(api_client.create_repository(
        {"name": "Repo", "location": "NYC"}, PM))
    rh = make_researcher_headers(researcher["id"])
    resp = api_client.create_appointment(
        create_appointment_payload(repository_id=repo["id"], project_id=project["id"],
                                   researcher_id=researcher["id"],
                                   start_utc="2026-04-01T10:00:00Z",
                                   end_utc="2026-04-01T09:00:00Z"), rh)
    validate_error(resp, "ERR_INVALID_INTERVAL")


def test_citation_on_incomplete_search_returns_search_not_completed():
    """PRD §3.4: "the referenced record search must be in `COMPLETED`, since a
    search that has not produced results cannot be cited, or the request fails with
    `ERR_SEARCH_NOT_COMPLETED`."

    Design: Corner/validations/citation_on_incomplete_search_returns_search_not_completed
    """
    client, researcher, project = create_active_project()
    rh = make_researcher_headers(researcher["id"])
    # Same-project PENDING search (no referential violation) so only the constraint fires.
    search = get_success_data(api_client.create_record_search(
        create_record_search_payload(project_id=project["id"], search_terms="x"), rh))
    person = create_person(project["id"], researcher["id"], full_name="Same Project Person")
    resp = api_client.create_citation(
        create_citation_payload(record_search_id=search["id"], person_id=person["id"],
                               citation_text="x", source_type="CENSUS", quality="PRIMARY"), rh)
    validate_error(resp, "ERR_SEARCH_NOT_COMPLETED")
