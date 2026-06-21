"""Cross-entity cascades and conserved-quantity invariants: office-action expiry
abandoning an application and conserving open_application_count, and the
cross-entity state guards on register / madrid-certify.

Sources: Difficulty/transitive_cascade, Difficulty/compensating_invariant,
Difficulty/cross_entity_state_dependency.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    setup_application_with_outstanding_oa,
    setup_published_application,
    setup_filed_application,
    institute_opposition,
    create_madrid,
    set_clock,
    examiner_headers,
)
from test_helpers.factories import create_ttab_proceeding_payload


class TestOfficeActionExpiryCascade:
    """expire sets OfficeAction.status=EXPIRED and Application.status=ABANDONED,
    and that abandonment decrements Applicant.open_application_count."""

    def test_expiry_abandons_application_and_expires_action(self, api):
        """PRD §3.3: "A system sweep against an OUTSTANDING action whose
        finality-adjusted grace tail has fully elapsed ... sets the action's status
        to EXPIRED, marks its docket deadline MISSED, moves the application from
        OFFICE_ACTION_ISSUED to the terminal ABANDONED state, and decrements the
        owning applicant's open_application_count by one."

        Design: Difficulty/transitive_cascade/office_action_expiry_cascades_abandon_then_open_count
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="LIKELIHOOD_OF_CONFUSION", is_final=True, mark_text="EXPIRY")
        set_clock("2026-04-02T00:00:00Z")  # past 2026-04-01 deadline, FINAL_GRACE=0
        oa = validate_success(api.expire_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        assert oa["status"] == "EXPIRED"
        app = validate_success(api.get_application(
            base["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "ABANDONED"

    def test_expiry_decrements_open_application_count(self, api):
        """PRD §3.3: "moves the application from OFFICE_ACTION_ISSUED to the terminal
        ABANDONED state, and decrements the owning applicant's open_application_count
        by one."

        Design: Difficulty/transitive_cascade/office_action_expiry_cascades_abandon_then_open_count
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="LIKELIHOOD_OF_CONFUSION", is_final=True, mark_text="EXPIRY2")
        set_clock("2026-04-02T00:00:00Z")
        validate_success(api.expire_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        applicant = validate_success(api.get_applicant(
            base["applicant"]["id"], examiner_headers()), 200)
        assert applicant["open_application_count"] == 0


class TestOpenApplicationCountConserved:
    """Filing increments open_application_count (+1); abandonment via office-action
    expiry decrements it (-1); after file-then-abandon the count returns to 0."""

    def test_file_then_abandon_conserves_open_count_to_zero(self, api):
        """PRD §3.1: "A new applicant's open_application_count, the running count of
        its applications not yet in a terminal REGISTERED or ABANDONED state, begins
        at 0."
        PRD §3.2: "increments the owning applicant's open_application_count by one."
        PRD §3.3: "moves the application from OFFICE_ACTION_ISSUED to the terminal
        ABANDONED state, and decrements the owning applicant's open_application_count
        by one."

        Design: Difficulty/compensating_invariant/open_application_count_conserved_file_then_abandon
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="LIKELIHOOD_OF_CONFUSION", is_final=True, mark_text="CONSERVE")
        applicant_filed = validate_success(api.get_applicant(
            base["applicant"]["id"], examiner_headers()), 200)
        assert applicant_filed["open_application_count"] == 1, (
            "filing should have incremented the count to 1")
        set_clock("2026-04-02T00:00:00Z")
        validate_success(api.expire_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        applicant_after = validate_success(api.get_applicant(
            base["applicant"]["id"], examiner_headers()), 200)
        assert applicant_after["open_application_count"] == 0, (
            "file-then-abandon must return the count to 0 with no drift")

    def test_abandoned_application_is_terminal(self, api):
        """PRD §3.3: "moves the application from OFFICE_ACTION_ISSUED to the terminal
        ABANDONED state, and decrements the owning applicant's open_application_count
        by one."

        Design: Difficulty/compensating_invariant/open_application_count_conserved_file_then_abandon
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="MERELY_DESCRIPTIVE", is_final=True, mark_text="CONSERVE2")
        set_clock("2026-04-02T00:00:00Z")
        validate_success(api.expire_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        app = validate_success(api.get_application(
            base["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "ABANDONED"


class TestRegisterBlockedByPendingOpposition:
    """A PUBLISHED USE application cannot transition to REGISTERED while a
    TTABProceeding targeting it has claim_status in {PLEADED, TRIAL}."""

    def test_register_rejected_while_opposition_pleaded(self, api):
        """PRD §3.4: "an examiner registers it, moving it from PUBLISHED to the
        terminal REGISTERED state, provided no board proceeding targeting this
        application is still live — that is, no TTABProceeding with this application
        as its target has a claim_status of PLEADED or TRIAL."

        Design: Difficulty/cross_entity_state_dependency/register_blocked_by_pending_opposition
        """
        base = setup_published_application(class_numbers=(9,), filing_basis="USE", mark_text="BLOCKED")
        att_headers = base["att_headers"]
        # A rival institutes an opposition (claim_status PLEADED).
        rival = validate_success(api.create_applicant(
            {"legal_name": "Rival Co", "entity_type": "CORPORATION", "country_code": "US"},
            att_headers), 201)
        institute_opposition(base["application"]["id"], rival["id"], att_headers)
        res = api.register_application(base["application"]["id"], examiner_headers())
        validate_error(res, "ERR_INVALID_STATE")
        app = validate_success(api.get_application(
            base["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "PUBLISHED"

    def test_application_stays_published_when_register_blocked(self, api):
        """PRD §3.4: "provided no board proceeding targeting this application is
        still live — that is, no TTABProceeding with this application as its target
        has a claim_status of PLEADED or TRIAL."

        Design: Difficulty/cross_entity_state_dependency/register_blocked_by_pending_opposition
        """
        base = setup_published_application(class_numbers=(9,), filing_basis="USE", mark_text="BLOCKED2")
        att_headers = base["att_headers"]
        rival = validate_success(api.create_applicant(
            {"legal_name": "Rival Co", "entity_type": "CORPORATION", "country_code": "US"},
            att_headers), 201)
        institute_opposition(base["application"]["id"], rival["id"], att_headers)
        validate_error(
            api.register_application(base["application"]["id"], examiner_headers()),
            "ERR_INVALID_STATE")
        app = validate_success(api.get_application(
            base["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "PUBLISHED"


class TestMadridCertifyBlockedByAbandonedBasic:
    """A Madrid application cannot be CERTIFIED when its basic application has been
    ABANDONED (status not in the certifiable set)."""

    def test_certify_rejected_when_basic_abandoned(self, api):
        """PRD §3.7: "An examiner certifies the international application, moving it
        from PENDING_CERTIFICATION to CERTIFIED, permitted only when the basic
        application is in any of FILED, UNDER_EXAMINATION, OFFICE_ACTION_ISSUED,
        PUBLISHED, ALLOWED, or REGISTERED."

        Design: Difficulty/cross_entity_state_dependency/madrid_certify_blocked_by_abandoned_basic
        """
        base = setup_filed_application(class_numbers=(9,), filing_basis="USE", mark_text="BASIC")
        att_headers = base["att_headers"]
        madrid = create_madrid(base["application"]["id"], ["FR"], att_headers)
        # Abandon the basic via a FINAL office action that expires.
        validate_success(api.assign_examination(
            base["application"]["id"], examiner_headers()), 200)
        oa = validate_success(api.create_office_action(
            {"application_id": base["application"]["id"], "ground": "MERELY_DESCRIPTIVE",
             "is_final": True}, examiner_headers()), 201)
        set_clock("2026-04-02T00:00:00Z")
        validate_success(api.expire_office_action(oa["id"], examiner_headers()), 200)
        res = api.certify_madrid_application(madrid["id"], examiner_headers())
        validate_error(res, "ERR_INVALID_STATE")
        madrid_after = validate_success(api.get_madrid_application(
            madrid["id"], examiner_headers()), 200)
        assert madrid_after["status"] == "PENDING_CERTIFICATION"

    def test_madrid_stays_pending_when_certify_blocked(self, api):
        """PRD §3.7: "permitted only when the basic application is in any of FILED,
        UNDER_EXAMINATION, OFFICE_ACTION_ISSUED, PUBLISHED, ALLOWED, or REGISTERED."

        Design: Difficulty/cross_entity_state_dependency/madrid_certify_blocked_by_abandoned_basic
        """
        base = setup_filed_application(class_numbers=(9,), filing_basis="USE", mark_text="BASIC2")
        att_headers = base["att_headers"]
        madrid = create_madrid(base["application"]["id"], ["FR"], att_headers)
        validate_success(api.assign_examination(
            base["application"]["id"], examiner_headers()), 200)
        oa = validate_success(api.create_office_action(
            {"application_id": base["application"]["id"], "ground": "SPECIMEN_DEFECT",
             "is_final": True}, examiner_headers()), 201)
        set_clock("2026-04-02T00:00:00Z")
        validate_success(api.expire_office_action(oa["id"], examiner_headers()), 200)
        validate_error(
            api.certify_madrid_application(madrid["id"], examiner_headers()),
            "ERR_INVALID_STATE")
        madrid_after = validate_success(api.get_madrid_application(
            madrid["id"], examiner_headers()), 200)
        assert madrid_after["status"] == "PENDING_CERTIFICATION"
