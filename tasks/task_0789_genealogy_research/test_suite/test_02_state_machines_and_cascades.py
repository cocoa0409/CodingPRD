"""State-machine and cascade tests: cyclic person reopen, independent document
dimensions, transitive verify/accept cascades, and corner transition guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_researcher_headers, make_client_headers, TEST_USERS,
    create_active_project, create_completed_search, create_person, add_citation,
    setup_person_under_review, create_submitted_deliverable, create_milestone,
    setup_ready_milestone, api_client,
)
from test_helpers.factories import (
    create_document_request_payload, create_deliverable_payload, create_heirloom_payload,
)

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# non_linear_state_machine / person_verified_reopen_cycle
# ==========================================================================
class TestPersonVerifiedReopenCycle:
    def _setup_and_dispute(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10,
            target_person_count=1)
        person = setup_person_under_review(project["id"], researcher["id"], full_name="Mary Jones")
        search = create_completed_search(project["id"], researcher["id"], search_terms="Jones")
        rh = make_researcher_headers(researcher["id"])
        cit1 = add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                            source_type="VITAL_RECORD", citation_text="Birth", verify=True)
        add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                     source_type="CHURCH", citation_text="Marriage", verify=True)
        # Person is now VERIFIED (2 verified PRIMARY citations). Dispute one.
        get_success_data(api_client.dispute_citation(
            cit1["id"], rh, {"reason": "Conflicting evidence found"}))
        return get_success_data(api_client.get_person(person["id"], PM)), project

    def test_dispute_reopens_verified_person(self):
        """PRD §3.4: "When a dispute drops a currently `VERIFIED` person below either
        gate — its `confidence_score` falls under 0.75, or its
        `verified_citation_count` falls under 2 — the system reopens the person
        `VERIFIED → UNDER_REVIEW`, decrements the owning project's
        `verified_person_count` by 1, and recomputes the project's `research_status`."

        Design: Difficulty/non_linear_state_machine/person_verified_reopen_cycle
        """
        person, _ = self._setup_and_dispute()
        assert person["verification_status"] == "UNDER_REVIEW", (
            f"disputing below the gate must reopen the person, got {person['verification_status']}")
        assert person["verified_citation_count"] == 1

    def test_reopen_decrements_project_verified_count(self):
        """PRD §3.4: "the system reopens the person `VERIFIED → UNDER_REVIEW`,
        decrements the owning project's `verified_person_count` by 1, and recomputes
        the project's `research_status`."

        Design: Difficulty/non_linear_state_machine/person_verified_reopen_cycle
        """
        _, project = self._setup_and_dispute()
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["verified_person_count"] == 0, (
            f"reopen must decrement verified_person_count back to 0, got {proj['verified_person_count']}")


# ==========================================================================
# non_linear_state_machine / document_request_parallel_dimensions_independent
# ==========================================================================
class TestDocumentRequestIndependentDimensions:
    def _setup_and_retrieve(self):
        client, researcher, project = create_active_project()
        repo = get_success_data(api_client.create_repository(
            {"name": "Bavaria Archive", "location": "Munich"}, PM))
        rh = make_researcher_headers(researcher["id"])
        doc = get_success_data(api_client.create_document_request(
            create_document_request_payload(project_id=project["id"], repository_id=repo["id"],
                                            document_type="Birth certificate",
                                            source_language="German",
                                            needs_translation=True), rh))
        return get_success_data(api_client.update_retrieval(doc["id"], {"outcome": "RETRIEVED"}, rh))

    def test_retrieval_dimension_advances(self):
        """PRD §3.6: "Advancing retrieval is a researcher action that supplies an
        `outcome` of `RETRIEVED` or `UNAVAILABLE` and is admissible only while
        `retrieval_status` is `REQUESTED`."

        Design: Difficulty/non_linear_state_machine/document_request_parallel_dimensions_independent
        """
        doc = self._setup_and_retrieve()
        assert doc["retrieval_status"] == "RETRIEVED", (
            f"retrieval must advance to RETRIEVED, got {doc['retrieval_status']}")

    def test_translation_dimension_unaffected_by_retrieval(self):
        """PRD §3.6: "The `translation_status` begins at `PENDING` when the request
        was created with `needs_translation` set to true".
        PRD §3.6: "Because the two dimensions are independent, advancing one never
        affects the other; each advance simply increments the request's `version`."

        Design: Difficulty/non_linear_state_machine/document_request_parallel_dimensions_independent
        """
        doc = self._setup_and_retrieve()
        assert doc["translation_status"] == "PENDING", (
            f"advancing retrieval must leave translation at PENDING, got {doc['translation_status']}")


# ==========================================================================
# transitive_cascade / citation_verify_cascades_to_research_complete_depth4
# ==========================================================================
class TestCitationVerifyCascade:
    def _setup_and_verify_second(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10,
            target_person_count=1)
        person = setup_person_under_review(project["id"], researcher["id"], full_name="Eli Ford")
        search = create_completed_search(project["id"], researcher["id"], search_terms="Ford")
        rh = make_researcher_headers(researcher["id"])
        add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                     source_type="VITAL_RECORD", citation_text="Birth", verify=True)
        cit2 = add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                            source_type="CHURCH", citation_text="Baptism", verify=False)
        # Verifying the 2nd citation fires the cascade.
        get_success_data(api_client.verify_citation(cit2["id"], rh))
        return person, project

    def test_second_citation_verify_auto_verifies_person(self):
        """PRD §3.4: "the person is auto-verified as a side effect of citation
        verification: when verifying a citation leaves its person `UNDER_REVIEW`
        with a `confidence_score` of at least 0.75 and a `verified_citation_count`
        of at least 2, the person is driven `UNDER_REVIEW → VERIFIED` automatically."

        Design: Difficulty/transitive_cascade/citation_verify_cascades_to_research_complete_depth4
        """
        person, _ = self._setup_and_verify_second()
        got = get_success_data(api_client.get_person(person["id"], PM))
        assert got["verification_status"] == "VERIFIED", (
            f"person must auto-verify on the 2nd citation verify, got {got['verification_status']}")

    def test_cascade_completes_project_research(self):
        """PRD §3.4: "Either path to `VERIFIED` increments the owning project's
        `verified_person_count` by 1 and then recomputes the project's
        `research_status`."
        PRD §3.2: "The `research_status` is derived and holds `IN_PROGRESS` until
        `verified_person_count` reaches or exceeds `target_person_count`, at which
        point it flips to `RESEARCH_COMPLETE`".

        Design: Difficulty/transitive_cascade/citation_verify_cascades_to_research_complete_depth4
        """
        _, project = self._setup_and_verify_second()
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["verified_person_count"] == 1
        assert proj["research_status"] == "RESEARCH_COMPLETE", (
            f"target_person_count 1 reached -> RESEARCH_COMPLETE, got {proj['research_status']}")


# ==========================================================================
# transitive_cascade / deliverable_accept_cascades_to_ready_amount_depth3
# ==========================================================================
class TestDeliverableAcceptCascade:
    def _setup_and_accept(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10)
        milestone = create_milestone(project["id"], amount_cents=40000, sequence_no=1)
        deliverable = create_submitted_deliverable(project["id"], researcher["id"],
                                                   deliverable_type="FAMILY_TREE",
                                                   milestone_id=milestone["id"])
        accepted = get_success_data(api_client.accept_deliverable(
            deliverable["id"], make_client_headers(client["id"])))
        return accepted, milestone, project

    def test_accept_readies_linked_milestone(self):
        """PRD §3.8: "Accepting a deliverable increments the owning project's
        `accepted_deliverable_count` by 1 and, when the deliverable names a
        `milestone_id`, drives that linked milestone from `PENDING` to `READY`".

        Design: Difficulty/transitive_cascade/deliverable_accept_cascades_to_ready_amount_depth3
        """
        accepted, milestone, _ = self._setup_and_accept()
        assert accepted["status"] == "ACCEPTED"
        m = get_success_data(api_client.get_milestone(milestone["id"], PM))
        assert m["status"] == "READY", (
            f"accepting the linked deliverable must ready the milestone, got {m['status']}")

    def test_ready_milestone_recomputes_ready_amount(self):
        """PRD §3.8: "that milestone's move to `READY` in turn recomputes the
        project's `ready_milestone_amount_cents`."

        Design: Difficulty/transitive_cascade/deliverable_accept_cascades_to_ready_amount_depth3
        """
        _, _, project = self._setup_and_accept()
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["ready_milestone_amount_cents"] == 40000, (
            f"ready_milestone_amount_cents must equal the milestone base 40000, "
            f"got {proj['ready_milestone_amount_cents']}")


# ==========================================================================
# Corner / state_machines
# ==========================================================================
def test_verify_person_from_draft_returns_invalid_state():
    """PRD §3.4: "the person must currently be `UNDER_REVIEW` (else
    `ERR_INVALID_STATE`), must have at least 2 `VERIFIED` citations (else
    `ERR_INSUFFICIENT_CITATIONS`), and must have a `confidence_score` of at least
    0.75 (else `ERR_CONFIDENCE_BELOW_THRESHOLD`); these three checks are evaluated
    in that order — state admissibility first, then the citation-count floor, then
    the confidence floor."

    Design: Corner/state_machines/verify_person_from_draft_returns_invalid_state
    """
    client, researcher, project = create_active_project()
    person = create_person(project["id"], researcher["id"], full_name="Still Draft")
    rh = make_researcher_headers(researcher["id"])
    resp = api_client.verify_person(person["id"], rh)
    validate_error(resp, "ERR_INVALID_STATE")


def test_accept_already_accepted_deliverable_returns_invalid_state():
    """PRD §3.8: "Both client decisions are admissible only from `SUBMITTED`, and
    both are restricted to the client who owns the deliverable's project (or a
    project manager)".

    Design: Corner/state_machines/accept_already_accepted_deliverable_returns_invalid_state
    """
    client, researcher, project = create_active_project()
    deliverable = create_submitted_deliverable(project["id"], researcher["id"],
                                               deliverable_type="RESEARCH_REPORT")
    ch = make_client_headers(client["id"])
    get_success_data(api_client.accept_deliverable(deliverable["id"], ch))
    resp = api_client.accept_deliverable(deliverable["id"], ch)
    validate_error(resp, "ERR_INVALID_STATE")


def test_activate_already_active_project_returns_invalid_state():
    """PRD §3.2: "Activating a project advances it `DRAFT → ACTIVE` and is permitted
    only when the project is currently `DRAFT`; attempting it from any other state
    fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_project_returns_invalid_state
    """
    client, researcher, project = create_active_project()  # already ACTIVE
    resp = api_client.activate_project(project["id"], PM)
    validate_error(resp, "ERR_INVALID_STATE")


def test_heirloom_advance_received_to_catalogued():
    """PRD §3.7: "it begins at `RECEIVED` and is advanced one step at a time by
    supplying the next `target_status` — from `RECEIVED` to `CATALOGUED`, then to
    `DIGITIZED`, and finally to the terminal `RETURNED`."

    Design: Corner/state_machines/heirloom_advance_received_to_catalogued
    """
    client, researcher, project = create_active_project()
    rh = make_researcher_headers(researcher["id"])
    heirloom = get_success_data(api_client.create_heirloom(
        create_heirloom_payload(project_id=project["id"], description="Family bible",
                               category="DOCUMENT"), rh))
    resp = api_client.advance_heirloom(heirloom["id"], {"target_status": "CATALOGUED"}, rh)
    data = validate_success(resp, expected_status=200)
    assert data["archive_status"] == "CATALOGUED", (
        f"advance must move RECEIVED -> CATALOGUED, got {data['archive_status']}")
