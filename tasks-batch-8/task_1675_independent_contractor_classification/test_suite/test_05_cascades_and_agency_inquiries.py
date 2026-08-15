"""Suspension and conversion cascades, conversion lookback math, agency inquiries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_conversion,
    create_engagement,
    create_inquiry,
    extend_offer,
    get_contract,
    get_contractor,
    get_engagement,
    propose_amendment,
    run_determination,
    setup_engagement_at_state,
    setup_high_tier_engagement,
    submit_for_review,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_MANAGER = TEST_USERS["engagement_manager_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]
_LIAISON = TEST_USERS["agency_liaison_headers"]


class TestSuspensionCascade:
    """The four-link suspension cascade (PRD §3.6)."""

    def _setup_suspended_high_engagement(self):
        """ACTIVE HIGH-tier engagement with EXECUTED contract and one PROPOSED
        amendment referencing the ACTIVE exception grant."""
        setup = setup_high_tier_engagement("ACTIVE")
        contract = setup["contract"]
        amendment = propose_amendment(
            contract["id"],
            scope_change_summary="Add weekend route package under existing exception",
            new_rate_cents=9500,
            exception_grant_id=setup["exception"]["id"],
        )
        return setup, amendment

    def test_suspend_cascade_suspends_engagement_and_contract(self, api, compliance_officer_headers):
        """PRD §3.6: "Link 1: the engagement's `EXECUTED` contract transitions to
        `SUSPENDED`." — fired by a `ComplianceOfficer` moving the engagement
        `ACTIVE → SUSPENDED`.

        Design: Difficulty/transitive_cascade/tc_suspend_cascade_engagement_contract_amendment_exception
        """
        setup, _ = self._setup_suspended_high_engagement()
        engagement = setup["engagement"]
        contract = setup["contract"]

        res = api.suspend_engagement(engagement["id"], compliance_officer_headers)
        suspended = validate_success(res, 200)
        assert suspended["status"] == "SUSPENDED"
        assert get_contract(contract["id"])["status"] == "SUSPENDED"

    def test_suspend_cascade_voids_amendment_revokes_exception_watch(self, api, compliance_officer_headers):
        """PRD §3.6: "Link 2, caused by the contract mutation: every amendment of that
        contract in `PROPOSED` or `APPROVED` status transitions to `VOIDED`. Link 3,
        caused by each voiding: every ExceptionGrant referenced by a newly `VOIDED`
        amendment through its `exception_grant_id`, while still `ACTIVE`, transitions
        to `REVOKED`. Link 4, caused by the revocations: the contractor's standing is
        recomputed, and a contractor in `GOOD_STANDING` with a revoked grant moves to
        `WATCH`."

        Design: Difficulty/transitive_cascade/tc_suspend_cascade_engagement_contract_amendment_exception
        """
        setup, amendment = self._setup_suspended_high_engagement()
        engagement = setup["engagement"]
        contract = setup["contract"]

        validate_success(api.suspend_engagement(engagement["id"], compliance_officer_headers), 200)

        amendments, _ = validate_paginated(api.list_amendments(contract["id"], _ADMIN))
        voided = [a for a in amendments if a["id"] == amendment["id"]]
        assert len(voided) == 1 and voided[0]["status"] == "VOIDED"

        grants, _ = validate_paginated(api.list_exceptions(engagement["id"], _ADMIN))
        revoked = [g for g in grants if g["id"] == setup["exception"]["id"]]
        assert len(revoked) == 1 and revoked[0]["status"] == "REVOKED"

        assert get_contractor(setup["contractor"]["id"])["standing_status"] == "WATCH"


class TestConversionCascade:
    def _setup_two_engagements_with_offer(self):
        """eng_a ACTIVE (full STANDARD chain) + eng_b UNDER_REVIEW; conversion case on
        eng_a with the offer extended."""
        setup_a = setup_engagement_at_state("ACTIVE")
        contractor = setup_a["contractor"]
        jurisdiction = setup_a["jurisdiction"]

        eng_b = create_engagement(
            contractor["id"], jurisdiction["id"], title="Bystander engagement",
            agreed_rate_cents=8000, start_date="2026-03-01",
        )
        submit_questionnaire(eng_b["id"])
        run_determination(eng_b["id"])
        submit_for_review(eng_b["id"])

        conversion = create_conversion(setup_a["engagement"]["id"])
        extend_offer(conversion["id"], offer_salary_cents=12000000)
        return setup_a, eng_b, conversion

    def test_conversion_acceptance_converts_engagement(self, api, engagement_manager_headers):
        """PRD §3.9: "An `ACCEPTED` decision requires the engagement to be `ACTIVE`
        (otherwise `ERR_INVALID_STATE`) and completes the case as `COMPLETED`, firing
        the conversion cascade: the source engagement moves `ACTIVE → CONVERTED`".

        Design: Difficulty/transitive_cascade/tc_conversion_completion_cascade
        """
        setup_a, _, conversion = self._setup_two_engagements_with_offer()
        res = api.record_decision(conversion["id"], {"decision": "ACCEPTED"}, engagement_manager_headers)
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"
        assert get_engagement(setup_a["engagement"]["id"])["status"] == "CONVERTED"

    def test_conversion_acceptance_sweeps_sibling_engagements(self, api, engagement_manager_headers):
        """PRD §3.9: "that conversion moves the contractor's `standing_status` to
        `CONVERTED_TO_EMPLOYEE`; and that standing mutation rejects every other
        engagement of the same contractor still in a non-terminal status — `DRAFT`,
        `INTAKE_SUBMITTED`, `CLASSIFIED`, `UNDER_REVIEW`, `INFO_REQUESTED`,
        `APPROVAL_PENDING`, or `APPROVED` — moving each to `REJECTED`."

        Design: Difficulty/transitive_cascade/tc_conversion_completion_cascade
        """
        setup_a, eng_b, conversion = self._setup_two_engagements_with_offer()
        validate_success(
            api.record_decision(conversion["id"], {"decision": "ACCEPTED"}, engagement_manager_headers),
            200,
        )
        contractor = get_contractor(setup_a["contractor"]["id"])
        assert contractor["standing_status"] == "CONVERTED_TO_EMPLOYEE"
        assert get_engagement(eng_b["id"])["status"] == "REJECTED"

    def test_conversion_declined_leaves_engagement_active(self, api, engagement_manager_headers):
        """PRD §3.9: "A `DECLINED` decision moves the case to `DECLINED` and a
        `RESCINDED` decision to `RESCINDED`, both terminal and without further effect."

        Design: Corner/state_machines/sm_conversion_declined_leaves_engagement_active
        """
        setup = setup_engagement_at_state("ACTIVE")
        conversion = create_conversion(setup["engagement"]["id"])
        extend_offer(conversion["id"], offer_salary_cents=9000000)

        res = api.record_decision(conversion["id"], {"decision": "DECLINED"}, engagement_manager_headers)
        declined = validate_success(res, 200)
        assert declined["status"] == "DECLINED"
        assert get_engagement(setup["engagement"]["id"])["status"] == "ACTIVE"
        assert get_contractor(setup["contractor"]["id"])["standing_status"] == "GOOD_STANDING"

    def test_conversion_on_draft_engagement_rejected(self, api, compliance_officer_headers):
        """PRD §3.9: "A `ComplianceOfficer` opens a **ConversionCase** against an
        engagement in `ACTIVE` or `SUSPENDED` status — any other status is rejected
        with `ERR_CONVERSION_NOT_POSSIBLE` (HTTP 409)".

        Design: Corner/errors/err_conversion_on_draft_engagement_rejected
        """
        setup = setup_engagement_at_state("DRAFT")
        res = api.create_conversion(
            setup["engagement"]["id"],
            {"lookback_quarters": [
                {"quarter_label": "2025Q3", "service_fee_cents": 100000},
                {"quarter_label": "2025Q4", "service_fee_cents": 100000},
                {"quarter_label": "2026Q1", "service_fee_cents": 100000},
                {"quarter_label": "2026Q2", "service_fee_cents": 100000},
            ]},
            compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_CONVERSION_NOT_POSSIBLE.value)


class TestConversionLookbackRounding:
    LOOKBACK = [
        {"quarter_label": "2025Q3", "service_fee_cents": 1000300},
        {"quarter_label": "2025Q4", "service_fee_cents": 1000400},
        {"quarter_label": "2026Q1", "service_fee_cents": 1005200},
        {"quarter_label": "2026Q2", "service_fee_cents": 1003400},
    ]

    def test_lookback_per_quarter_rounding_pinned(self, api):
        """PRD §3.9: "Rounding per quarter and then summing is mandatory: summing the
        bases first and applying the factors once yields different cents and is not
        compliant. On a lookback of 1000300, 1000400, 1005200, and 1003400 cents, the
        pinned order yields a W-2 equivalent total of 5610815 cents, where the
        sum-then-round order would yield 5610814."

        Design: Difficulty/combinatorial_formula/cf_lookback_per_quarter_rounding_order
        """
        setup = setup_engagement_at_state("ACTIVE")
        conversion = create_conversion(setup["engagement"]["id"], self.LOOKBACK)
        assert conversion["w2_equivalent_total_cents"] == 5610815

    def test_lookback_delta_is_total_minus_service_fees(self, api):
        """PRD §3.9: "The `w2_equivalent_total_cents` is the sum of the four quarter
        equivalents, and `lookback_delta_cents` is that total minus the sum of the
        four `service_fee_cents` amounts."

        Design: Difficulty/combinatorial_formula/cf_lookback_per_quarter_rounding_order
        """
        setup = setup_engagement_at_state("ACTIVE")
        conversion = create_conversion(setup["engagement"]["id"], self.LOOKBACK)
        assert conversion["lookback_delta_cents"] == 5610815 - 4009300
        assert conversion["lookback_delta_cents"] == 1601515


class TestAgencyInquiries:
    def _setup_draft_engagement(self):
        setup = setup_engagement_at_state(
            "DRAFT",
            jurisdiction_overrides={
                "code": "US-CA", "test_type": "ABC_TEST", "state_filing_threshold_cents": 0,
            },
            engagement_overrides={"agreed_rate_cents": 9000},
        )
        return setup

    def test_exposure_estimate_pinned_evaluation_order(self, api, agency_liaison_headers):
        """PRD §3.9: "As a worked pin: a base of 5000000 cents with 2 quarters
        outstanding yields a penalty of 500000 cents, interest of 550000 cents, and a
        total exposure of 6050000 cents."
        PRD §3.9: "interest compounds on back payments plus penalty, never on itself".

        Design: Difficulty/combinatorial_formula/cf_exposure_pinned_evaluation_order
        """
        setup = self._setup_draft_engagement()
        res = api.create_inquiry(
            setup["engagement"]["id"],
            {
                "agency_type": "STATE_EDD",
                "received_at": "2026-07-15T00:00:00Z",
                "response_deadline": "2026-09-15T00:00:00Z",
                "back_payments_cents": 5000000,
                "quarters_outstanding": 2,
            },
            agency_liaison_headers,
        )
        inquiry = validate_success(res, 201)
        assert inquiry["exposure_estimate_cents"] == 6050000

    def test_exposure_penalty_tier_keyed_on_pre_penalty_base(self, api, agency_liaison_headers):
        """PRD §3.9: "ten percent when the base is below 10000000 cents, twenty percent
        when the base is at least 10000000 but below 100000000 cents, and forty percent
        when the base is 100000000 cents or more — the tier is keyed on the pre-penalty
        base, and the penalty is rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/cf_exposure_pinned_evaluation_order
        """
        setup = self._setup_draft_engagement()
        # One cent below the tier-2 limit: 10% of 9999999 = 999999.9 -> 1000000.
        below = validate_success(
            api.create_inquiry(
                setup["engagement"]["id"],
                {
                    "agency_type": "IRS",
                    "received_at": "2026-07-15T00:00:00Z",
                    "response_deadline": "2026-09-15T00:00:00Z",
                    "back_payments_cents": 9999999,
                    "quarters_outstanding": 0,
                },
                agency_liaison_headers,
            ),
            201,
        )
        assert below["exposure_estimate_cents"] == 9999999 + 1000000

        # Exactly at the tier-2 limit: 20% of 10000000 = 2000000.
        at = validate_success(
            api.create_inquiry(
                setup["engagement"]["id"],
                {
                    "agency_type": "DOL",
                    "received_at": "2026-07-15T00:00:00Z",
                    "response_deadline": "2026-09-15T00:00:00Z",
                    "back_payments_cents": 10000000,
                    "quarters_outstanding": 0,
                },
                agency_liaison_headers,
            ),
            201,
        )
        assert at["exposure_estimate_cents"] == 12000000

    def test_inquiry_escalation_creates_fieldwork_audit(self, api, agency_liaison_headers,
                                                        compliance_officer_headers):
        """PRD §3.9: "Recording an `outcome` of `ESCALATE_TO_AUDIT` requires a
        `new_response_deadline` in the future (its absence, or a deadline not later
        than the clock, is `ERR_INVALID_REQUEST`) and moves the inquiry
        `RESPONSE_SUBMITTED → AUDIT_OPENED` with two side effects: a new RiskAudit is
        created against the inquiry's contractor with `audit_type` `FIELDWORK`, status
        `OPEN`, and `engagement_id` set to the inquiry's engagement — its provisional
        score computed from declared data exactly as a directly created audit — and the
        inquiry's `response_deadline` is replaced by `new_response_deadline`."

        Design: Corner/state_machines/sm_inquiry_escalation_creates_fieldwork_audit
        """
        setup = self._setup_draft_engagement()
        inquiry = create_inquiry(setup["engagement"]["id"])
        validate_success(
            api.respond_inquiry(inquiry["id"], {"response_summary": "Initial position letter"},
                                agency_liaison_headers),
            200,
        )
        res = api.resolve_inquiry(
            inquiry["id"],
            {"outcome": "ESCALATE_TO_AUDIT", "new_response_deadline": "2026-12-01T00:00:00Z"},
            agency_liaison_headers,
        )
        resolved = validate_success(res, 200)
        assert resolved["status"] == "AUDIT_OPENED"
        assert str(resolved["response_deadline"]).startswith("2026-12-01")

        audits, meta = validate_paginated(
            api.list_audits(compliance_officer_headers,
                            params={"engagement_id": setup["engagement"]["id"]})
        )
        assert len(audits) == 1
        assert audits[0]["audit_type"] == "FIELDWORK"
        assert audits[0]["status"] == "OPEN"
        assert audits[0]["contractor_id"] == setup["contractor"]["id"]

    def test_inquiry_respond_after_deadline_rejected(self, api, agency_liaison_headers,
                                                     platform_admin_headers):
        """PRD §3.9: a response "is only permitted while the clock has not passed the
        `response_deadline`; a response after the deadline is rejected with
        `ERR_INQUIRY_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/val_inquiry_respond_after_deadline_rejected
        """
        setup = self._setup_draft_engagement()
        inquiry = create_inquiry(setup["engagement"]["id"], agency_type="IRS",
                                 back_payments_cents=1000000)
        api.set_clock("2026-09-02T00:00:00Z", platform_admin_headers)
        res = api.respond_inquiry(inquiry["id"], {"response_summary": "Too late"},
                                  agency_liaison_headers)
        validate_error(res, ApiErrorId.ERR_INQUIRY_DEADLINE_PASSED.value)
