"""Opportunity intake, investigator registry, subrecipient registry (PRD §3.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_funding_opportunity,
    assert_principal_investigator,
    assert_subrecipient_org,
    create_opportunity_payload,
    create_pi_payload,
    create_proposal_payload,
    create_subrecipient_org_payload,
    is_valid_uuid,
    make_opportunity,
    make_org,
    make_pi,
    make_pi_headers,
    reset_clock,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]


class TestOpportunityDeadline:
    def test_internal_deadline_default_lead(self, api, admin_headers):
        """PRD §3.1: "`internal_lead_days` (defaulting to 5) drives the computed
        `internal_deadline_at` described in §2.4". PRD §2.4: "Every funding
        opportunity derives its `internal_deadline_at` by subtracting
        `internal_lead_days` — five days unless the intake payload supplies a
        different count — from `sponsor_deadline_at`, using exact datetime
        arithmetic at second precision on ISO 8601 UTC values."

        Design: Corner/entities/funding_opportunity_computed_deadline_and_default
        """
        resp = api.create_funding_opportunity(
            {
                "sponsor_code": "NSF",
                "title": "DefaultLead",
                "activity_codes_allowed": ["RESEARCH_ON_CAMPUS"],
                "sponsor_deadline_at": "2026-09-05T17:00:00Z",
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_funding_opportunity(data)
        assert data["internal_lead_days"] == 5
        assert data["internal_deadline_at"] == "2026-08-31T17:00:00Z"
        assert data["status"] == "PUBLISHED"

    def test_internal_deadline_explicit_lead(self, api, admin_headers):
        """PRD §2.4: "Every funding opportunity derives its `internal_deadline_at`
        by subtracting `internal_lead_days` — five days unless the intake payload
        supplies a different count — from `sponsor_deadline_at`, using exact
        datetime arithmetic at second precision on ISO 8601 UTC values."

        Design: Corner/entities/funding_opportunity_computed_deadline_and_default
        """
        resp = api.create_funding_opportunity(
            create_opportunity_payload(
                title="Lead10",
                sponsor_code="NIH",
                sponsor_deadline_at="2026-09-05T17:00:00Z",
                internal_lead_days=10,
            ),
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["internal_deadline_at"] == "2026-08-26T17:00:00Z"


class TestInvestigatorEligibility:
    def test_delinquent_count_defaults_zero_and_eligible(self, api, admin_headers):
        """PRD §3.1: "recording `full_name`, `department_code`, academic `rank`
        ... and an optional `delinquent_report_count` that defaults to zero.
        `is_eligible` holds exactly when the investigator has no delinquent
        prior-award reports".

        Design: Corner/entities/principal_investigator_defaults_and_eligibility
        """
        resp = api.create_principal_investigator(
            {"full_name": "Clean", "department_code": "BIO", "rank": "FULL"},
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_principal_investigator(data)
        assert data["delinquent_report_count"] == 0
        assert data["is_eligible"] is True

    def test_delinquent_count_positive_ineligible(self, api, admin_headers):
        """PRD §3.1: "`is_eligible` holds exactly when the investigator has no
        delinquent prior-award reports, and it gates proposal creation".

        Design: Corner/entities/principal_investigator_defaults_and_eligibility
        """
        resp = api.create_principal_investigator(
            create_pi_payload(full_name="Late", delinquent_report_count=2),
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["is_eligible"] is False


class TestSubrecipientOrgRegistry:
    def test_risk_scoring_multi_input(self, api, sub_manager_headers):
        """PRD §3.7: "The base depends on `single_audit_status`: 10 points for
        `CURRENT`, 20 for `NOT_REQUIRED`, 45 for `MISSING`, 60 for `DELINQUENT`.
        The findings term adds five points per audit finding, capped at 25 points
        no matter how many findings exist. A foreign organization adds 10 points,
        and a first-time subrecipient adds another 10. The tiering is fixed: a
        score below 25 is `LOW`, from 25 through 49 is `MEDIUM`, and 50 or more
        is `HIGH`."

        Design: Difficulty/combinatorial_formula/subrecipient_risk_tiered_scoring
        """
        # DELINQUENT(60) + min(5*9, 25)=25 findings cap + 10 foreign = 95 HIGH
        a = validate_success(
            api.create_subrecipient_org(
                create_subrecipient_org_payload(
                    legal_name="Risky Foreign", uei="UEI-RF95",
                    single_audit_status="DELINQUENT", audit_finding_count=9,
                    is_foreign=True, first_time_subrecipient=False,
                ),
                sub_manager_headers,
            ),
            201,
        )
        assert_subrecipient_org(a)
        assert a["risk_score"] == 95
        assert a["risk_tier"] == "HIGH"
        # NOT_REQUIRED(20) + 4 findings(20) = 40 MEDIUM
        b = validate_success(
            api.create_subrecipient_org(
                create_subrecipient_org_payload(
                    legal_name="Borderline", uei="UEI-B040",
                    single_audit_status="NOT_REQUIRED", audit_finding_count=4,
                    is_foreign=False, first_time_subrecipient=False,
                ),
                sub_manager_headers,
            ),
            201,
        )
        assert b["risk_score"] == 40
        assert b["risk_tier"] == "MEDIUM"

    def test_risk_tier_boundaries(self, api, sub_manager_headers):
        """PRD §3.7: "The tiering is fixed: a score below 25 is `LOW`, from 25
        through 49 is `MEDIUM`, and 50 or more is `HIGH`."

        Design: Difficulty/combinatorial_formula/subrecipient_risk_tiered_scoring
        """
        # CURRENT(10) + 2 findings(10) = 20 -> LOW (below 25)
        low = validate_success(
            api.create_subrecipient_org(
                create_subrecipient_org_payload(
                    legal_name="Edge Low", uei="UEI-E024",
                    single_audit_status="CURRENT", audit_finding_count=2,
                ),
                sub_manager_headers,
            ),
            201,
        )
        assert low["risk_score"] == 20
        assert low["risk_tier"] == "LOW"
        # CURRENT(10) + 3 findings(15) = 25 -> MEDIUM (boundary enters MEDIUM)
        med = validate_success(
            api.create_subrecipient_org(
                create_subrecipient_org_payload(
                    legal_name="Edge Medium", uei="UEI-E025",
                    single_audit_status="CURRENT", audit_finding_count=3,
                ),
                sub_manager_headers,
            ),
            201,
        )
        assert med["risk_score"] == 25
        assert med["risk_tier"] == "MEDIUM"

    def test_duplicate_uei_rejected(self, api, sub_manager_headers):
        """PRD §3.7: "its `uei` — the Unique Entity Identifier, which must be
        globally unique across the registry, a duplicate being refused with
        `ERR_UEI_NOT_UNIQUE` (HTTP 409)".

        Design: Corner/entities/subrecipient_org_duplicate_uei_rejected
        """
        make_org(legal_name="First", uei="UEI-DUP1")
        resp = api.create_subrecipient_org(
            create_subrecipient_org_payload(legal_name="Second", uei="UEI-DUP1"),
            sub_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UEI_NOT_UNIQUE.value)


class TestProposalCreation:
    def test_missing_activity_code_invalid_request(self, api):
        """PRD §2.8: "structurally malformed payloads — a missing required field,
        a type mismatch, an unknown enum member, a non-positive `amount_cents`,
        an end date earlier than its start date, or a `SUBAWARD` line without its
        `subrecipient_commitment_id` — are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/proposal_missing_required_returns_invalid_request
        """
        opp = make_opportunity()
        pi = make_pi()
        payload = create_proposal_payload(opp["id"], pi["id"], title="NoCode")
        del payload["activity_code"]
        resp = api.create_proposal(payload, make_pi_headers(pi["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_unknown_activity_code_enum_invalid_request(self, api):
        """PRD §2.8: "structurally malformed payloads — a missing required field,
        a type mismatch, an unknown enum member ... are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/proposal_invalid_enum_returns_invalid_request
        """
        opp = make_opportunity(activity_codes_allowed=["RESEARCH_ON_CAMPUS", "INSTRUCTION"])
        pi = make_pi()
        payload = create_proposal_payload(
            opp["id"], pi["id"], title="BadEnum", activity_code="VENTURE_CAPITAL"
        )
        resp = api.create_proposal(payload, make_pi_headers(pi["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_proposal_not_found(self, api, director_headers):
        """PRD §2.9: "The same error answers a body-supplied reference that does
        not exist" and path identifiers "the server validates existence strictly
        left to right and answers `ERR_NOT_FOUND` (HTTP 404) for the first
        identifier that does not resolve".

        Design: Corner/entities/get_nonexistent_proposal_returns_not_found
        """
        resp = api.get_proposal(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", director_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_ineligible_pi_cannot_create(self, api):
        """PRD §3.1: "attempting to create a proposal for an investigator whose
        `delinquent_report_count` is greater than zero is refused with
        `ERR_PI_NOT_ELIGIBLE` (HTTP 403)."

        Design: Corner/validations/ineligible_pi_rejected
        """
        opp = make_opportunity()
        pi = make_pi(full_name="Late", delinquent_report_count=1)
        resp = api.create_proposal(
            create_proposal_payload(opp["id"], pi["id"], title="Nope"),
            make_pi_headers(pi["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PI_NOT_ELIGIBLE.value)

    def test_activity_code_not_allowed(self, api):
        """PRD §3.3: "the `activity_code` must appear in the opportunity's
        `activity_codes_allowed` (`ERR_ACTIVITY_CODE_NOT_ALLOWED`, 422)".

        Design: Corner/validations/activity_code_not_allowed_rejected
        """
        opp = make_opportunity(activity_codes_allowed=["RESEARCH_ON_CAMPUS"])
        pi = make_pi()
        resp = api.create_proposal(
            create_proposal_payload(
                opp["id"], pi["id"], title="WrongCode", activity_code="INSTRUCTION"
            ),
            make_pi_headers(pi["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVITY_CODE_NOT_ALLOWED.value)

    def test_per_pi_proposal_limit(self, api):
        """PRD §3.3: "when the opportunity sets `max_proposals_per_pi`, the
        investigator's count of proposals against this opportunity that have not
        reached a terminal state must leave room
        (`ERR_PI_PROPOSAL_LIMIT_EXCEEDED`, 409)."

        Design: Corner/errors/pi_proposal_limit_rejected
        """
        lim = make_opportunity(sponsor_code="NSF", title="LIM", max_proposals_per_pi=1)
        free = make_opportunity(sponsor_code="NIH", title="FREE")
        pi = make_pi()
        first = api.create_proposal(
            create_proposal_payload(lim["id"], pi["id"], title="First"),
            make_pi_headers(pi["id"]),
        )
        validate_success(first, 201)
        # Second non-terminal proposal on the capped opportunity is refused
        resp = api.create_proposal(
            create_proposal_payload(lim["id"], pi["id"], title="Second"),
            make_pi_headers(pi["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PI_PROPOSAL_LIMIT_EXCEEDED.value)
        # The cap is scoped to the opportunity: another opportunity is unaffected
        other = api.create_proposal(
            create_proposal_payload(free["id"], pi["id"], title="Elsewhere"),
            make_pi_headers(pi["id"]),
        )
        data = validate_success(other, 201)
        assert is_valid_uuid(data["id"])


class TestOpportunityClosureGate:
    def test_create_rejected_after_intake_closes(self, api):
        """PRD §3.3: "Creation enforces, beyond eligibility: the opportunity must
        still be `PUBLISHED` (`ERR_OPPORTUNITY_CLOSED`, 409)". PRD §3.1: "When
        the logical clock is set, the sweep transitions every still-`PUBLISHED`
        opportunity whose `sponsor_deadline_at` has passed into `INTAKE_CLOSED`,
        its terminal state."

        Design: Difficulty/cross_entity_state_dependency/create_proposal_requires_opportunity_published
        """
        reset_clock("2026-08-01T00:00:00Z")
        opp = make_opportunity(
            title="Early", sponsor_deadline_at="2026-08-10T17:00:00Z"
        )
        pi = make_pi()
        reset_clock("2026-08-11T00:00:00Z")
        o = validate_success(
            api.get_funding_opportunity(opp["id"], DIRECTOR)
        )
        assert o["status"] == "INTAKE_CLOSED"
        resp = api.create_proposal(
            create_proposal_payload(opp["id"], pi["id"], title="TooLate"),
            make_pi_headers(pi["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_CLOSED.value)

    def test_create_accepted_while_published(self, api):
        """PRD §3.1: "A newly intaken opportunity is `PUBLISHED`, its
        `internal_deadline_at` computed at creation." PRD §3.3: "Creation
        enforces, beyond eligibility: the opportunity must still be `PUBLISHED`
        (`ERR_OPPORTUNITY_CLOSED`, 409)".

        Design: Difficulty/cross_entity_state_dependency/create_proposal_requires_opportunity_published
        """
        reset_clock("2026-08-01T00:00:00Z")
        opp = make_opportunity(
            title="Early", sponsor_deadline_at="2026-08-10T17:00:00Z"
        )
        pi = make_pi()
        # Same payload accepted while the opportunity is still PUBLISHED
        ok = api.create_proposal(
            create_proposal_payload(opp["id"], pi["id"], title="InTime"),
            make_pi_headers(pi["id"]),
        )
        validate_success(ok, 201)
        reset_clock("2026-08-11T00:00:00Z")
        late = api.create_proposal(
            create_proposal_payload(opp["id"], pi["id"], title="TooLate"),
            make_pi_headers(pi["id"]),
        )
        validate_error(late, ApiErrorId.ERR_OPPORTUNITY_CLOSED.value)
