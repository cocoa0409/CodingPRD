"""Role lists, engagement ownership and the separation the firm's opinion rests on."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ASSESSOR_NOT_ACTIVE,
    ERR_NOT_ENGAGEMENT_LEAD,
    ERR_NOT_ENGAGEMENT_QA_REVIEWER,
    ERR_QA_NOT_QUALIFIED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
    ERR_VENDOR_SCOPE_FORBIDDEN,
)
from test_helpers.assertions import (
    assert_finding_ledger_identity,
    assert_money,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_segment_state,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    APPROVED_BUDGET,
    CLOCK_DEFAULT,
    LEAD_CERT_EXPIRES,
    SECOND_LEAD_EMAIL,
    SECOND_LEAD_NAME,
)
from test_helpers.factories import (
    change_log_payload,
    conclusion_payload,
    dispute_decision_payload,
    dispute_payload,
    document_evidence,
    engagement_payload,
    network_segment_payload,
    qa_review_payload,
    scan_finding_payload,
)
from test_helpers.fixtures import (
    Scenario,
    build_registry,
    complete_cycle,
    open_engagement,
    open_requirement,
    publish_finding,
    read_engagement,
    register_assessor,
    register_vendor,
    schedule_scan_cycle,
    start_testing,
    validated_segment,
)
from test_helpers.test_users import (
    admin_headers,
    client_rep_headers,
    make_assessor_headers,
    make_asv_vendor_headers,
    make_lead_headers,
    make_qa_reviewer_headers,
)

LENA_NAME = "Lena Ortiz"
LENA_EMAIL = "lena.ortiz@qsa.example"
SECOND_CLIENT = "Harbor Fuel Stops LLC"
SECOND_ACQUIRER = "Second Harbor Bank"
SECOND_FIELDWORK_START = "2026-11-02"
SECOND_FIELDWORK_END = "2026-11-20"


def _requirement_in_testing(api, scenario: Scenario, requirement_ref: str = "1.2.1"):
    """Open one requirement on the engagement and move it into active testing."""
    requirement = open_requirement(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        requirement_ref=requirement_ref,
    )
    return start_testing(api, requirement["id"], scenario["lead_id"])


class TestClientRepresentativeSurface:
    """The client's own staff narrate their environment but never evidence it."""

    def test_client_representative_cannot_record_evidence_but_can_log_a_change(
        self, api, scoping_engagement
    ):
        """The same actor is refused on the evidence file and admitted on the change log.

        PRD: Client representatives may raise false-positive disputes and record
        in-year changes, and may read anything, but may never record evidence,
        conclude a requirement or touch a report.

        Design: Corner/rbac/rbac_client_representative_may_narrate_changes_but_not_collect_evidence
        """
        scenario = scoping_engagement
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        requirement = _requirement_in_testing(api, scenario)

        refused = api.create_evidence_item(
            requirement["id"],
            document_evidence("1.2.1.a"),
            client_rep_headers(),
        )
        validate_error(refused, ERR_UNAUTHORIZED, 403)
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert held["evidence_item_count"] == 0
        assert_requirement_dimensions(held, test_status="IN_TESTING")

        # The very same actor is a first-class author of the in-year change log.
        entry = validate_success(
            api.create_change_log_entry(
                scenario["engagement_id"],
                change_log_payload(
                    change_type="APPLICATION_UPDATED",
                    description="Payment application patched to 4.2.1.",
                    affects_scope=False,
                ),
                client_rep_headers(),
            ),
            201,
        )
        assert entry["triggers_reassessment"] is False

        # A staff assessor's identical payload is accepted and stamped with them.
        item = validate_success(
            api.create_evidence_item(
                requirement["id"],
                document_evidence("1.2.1.a"),
                make_assessor_headers(lead_id),
            ),
            201,
        )
        assert item["collector_assessor_id"] == lead_id
        after = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert after["evidence_item_count"] == 1

        rows = assert_total_count(
            api.list_evidence_items(
                lead_headers, {"requirement_assessment_id": requirement["id"]}
            ),
            1,
        )
        assert rows[0]["collector_assessor_id"] == lead_id


class TestRoleDenialPrecedesEveryBusinessGate:
    """A role the endpoint never admits is turned away before any rule is read."""

    def test_role_refusal_surfaces_ahead_of_the_conclusion_and_lock_rules(
        self, api, scoping_engagement
    ):
        """The operator's refusals never mention the missing evidence or zone.

        PRD: When more than one rule could refuse a request, the refusal that
        surfaces is the one from the lowest rung of the following ladder.

        Design: Corner/rbac/rbac_role_denial_is_decided_before_any_business_gate
        """
        scenario = scoping_engagement
        lead_id = scenario["lead_id"]
        qa_id = scenario["qa_id"]
        lead_headers = make_lead_headers(lead_id)
        requirement = _requirement_in_testing(api, scenario)

        # No evidence at all and no sampling plan, so a conclusion would breach
        # two separate constraints if the operator's role were ever admitted.
        refused_conclusion = api.conclude_requirement(
            requirement["id"],
            conclusion_payload(
                conclusion="IN_PLACE",
                conclusion_rationale="Operator asserts the control is fine.",
            ),
            admin_headers(),
        )
        validate_error(refused_conclusion, ERR_UNAUTHORIZED, 403)
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert_requirement_dimensions(held, test_status="IN_TESTING")
        assert_version_unchanged(requirement["version"], held["version"])

        # The registry belongs to the operator, so an assessor is refused there
        # even though the amendment payload is perfectly well formed.
        refused_patch = api.update_assessor(
            qa_id, {"qa_qualified": False}, make_assessor_headers(lead_id)
        )
        validate_error(refused_patch, ERR_UNAUTHORIZED, 403)
        reviewer = validate_success(api.get_assessor(qa_id, lead_headers))
        assert reviewer["qa_qualified"] is True

        # The operator opens engagements but never runs them, and the engagement
        # holds no validated cardholder zone the refusal could have complained of.
        refused_lock = api.lock_scope(scenario["engagement_id"], admin_headers())
        validate_error(refused_lock, ERR_UNAUTHORIZED, 403)
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["status"] == "SCOPING"
        assert engagement["scope_locked"] is False


def _two_led_engagements(api) -> Scenario:
    """Two engagements led by two different Qualified Security Assessors.

    The first is Northwind Retail, led by Dana Reyes and holding a validated
    cardholder zone; the second is Harbor Fuel Stops, led by Owen Marsh, who
    therefore holds the lead role without leading Northwind.
    """
    scenario = build_registry(api)
    outsider = register_assessor(
        api,
        SECOND_LEAD_NAME,
        SECOND_LEAD_EMAIL,
        LEAD_CERT_EXPIRES,
        qa_qualified=False,
    )
    first = open_engagement(api, scenario["lead_id"], qa_reviewer_id=scenario["qa_id"])
    validated_segment(api, first["id"], scenario["lead_id"], name="CDE-CORE")
    second = open_engagement(
        api,
        outsider["id"],
        qa_reviewer_id=scenario["qa_id"],
        client_legal_name=SECOND_CLIENT,
        acquirer_name=SECOND_ACQUIRER,
        fieldwork_start_date=SECOND_FIELDWORK_START,
        fieldwork_end_date=SECOND_FIELDWORK_END,
    )
    scenario["outsider"] = outsider
    scenario["outsider_id"] = outsider["id"]
    scenario["engagement_id"] = first["id"]
    scenario["other_engagement"] = second
    scenario["other_engagement_id"] = second["id"]
    return scenario


class TestEngagementOwnershipAfterTheRoleList:
    """Holding the lead role is not the same as leading this engagement."""

    def test_an_outside_lead_is_refused_ownership_yet_shares_the_data_entry(
        self, api
    ):
        """The outsider cannot lock or amend Northwind but can still declare a zone in it.

        PRD: Concretely, every lead-only operation additionally requires that
        `X-User-ID` equal the engagement's `lead_assessor_id`, and a mismatch is
        refused with `ERR_NOT_ENGAGEMENT_LEAD` (HTTP 403) — being certified and
        holding the `LeadAssessor` role is never sufficient on an engagement
        somebody else leads.

        Design: Corner/rbac/rbac_engagement_ownership_is_checked_after_the_role_list
        """
        scenario = _two_led_engagements(api)
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        outsider_id = scenario["outsider_id"]
        lead_headers = make_lead_headers(lead_id)
        outsider_lead_headers = make_lead_headers(outsider_id)

        refused_lock = api.lock_scope(engagement_id, outsider_lead_headers)
        validate_error(refused_lock, ERR_NOT_ENGAGEMENT_LEAD, 403)
        held = read_engagement(api, engagement_id, lead_id)
        assert held["status"] == "SCOPING"
        assert held["scope_locked"] is False

        # The ceiling is never re-read, because ownership is settled first.
        refused_patch = api.update_engagement(
            engagement_id, {"approved_budget_amount": 10000.00}, outsider_lead_headers
        )
        validate_error(refused_patch, ERR_NOT_ENGAGEMENT_LEAD, 403)
        held = read_engagement(api, engagement_id, lead_id)
        assert_money(held["approved_budget_amount"], APPROVED_BUDGET)

        # Zone declaration is shared with staff assessors, so the same individual
        # acting in that capacity is admitted - and moves the engagement's gate.
        segment = validate_success(
            api.create_network_segment(
                engagement_id,
                network_segment_payload(name="CONNECTED-OPS", segment_class="CONNECTED"),
                make_assessor_headers(outsider_id),
            ),
            201,
        )
        assert segment["engagement_id"] == engagement_id
        assert_segment_state(segment, segmentation_status="DECLARED")
        after = read_engagement(api, engagement_id, lead_id)
        assert after["unvalidated_segment_count"] == 1
        assert after["posture"] == "RESTRICTED"

        untouched = read_engagement(api, scenario["other_engagement_id"], outsider_id)
        assert untouched["version"] == scenario["other_engagement"]["version"]
        assert untouched["status"] == "SCOPING"
        outsider = validate_success(api.get_assessor(outsider_id, lead_headers))
        assert outsider["lead_engagement_count"] == 1


class TestOnlyTheNominatedReviewerDecidesTheReport:
    """The quality-assurance decision is bound to one named individual."""

    def test_an_unnominated_qualified_reviewer_cannot_decide_the_report(
        self, api, roc_in_qa
    ):
        """A second qualified reviewer is refused; the nominated one is obeyed.

        PRD: When `X-User-Role` is `QaReviewer`, `X-User-ID` is the `id` of the
        acting `Assessor` record; every quality-assurance operation additionally
        requires that `X-User-ID` equal the engagement's `qa_reviewer_id`, and a
        mismatch is refused with `ERR_NOT_ENGAGEMENT_QA_REVIEWER` (HTTP 403).

        Design: Corner/rbac/rbac_only_the_nominated_reviewer_can_decide_the_report
        """
        scenario = roc_in_qa
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        roc_id = scenario["roc_id"]
        outsider = register_assessor(
            api, LENA_NAME, LENA_EMAIL, LEAD_CERT_EXPIRES, qa_qualified=True
        )

        # She is qualified, active and collected nothing here, so the only thing
        # standing between her and the report is that nobody nominated her.
        assert outsider["qa_qualified"] is True
        assert outsider["certification_status"] == "ACTIVE"
        assert_total_count(
            api.list_evidence_items(
                lead_headers,
                {
                    "engagement_id": scenario["engagement_id"],
                    "collector_assessor_id": outsider["id"],
                },
            ),
            0,
        )

        refused_review = api.qa_review_roc(
            roc_id,
            qa_review_payload(
                decision="APPROVE", qa_decision_note="Looks fine from the outside."
            ),
            make_qa_reviewer_headers(outsider["id"]),
        )
        validate_error(refused_review, ERR_NOT_ENGAGEMENT_QA_REVIEWER, 403)
        held = validate_success(api.get_roc(roc_id, lead_headers))
        assert held["status"] == "IN_QA"
        assert held["qa_decision_note"] is None
        assert_version_unchanged(scenario["roc"]["version"], held["version"])

        # The lead-only hand-over refuses the same outsider under its own code.
        refused_submit = api.qa_submit_roc(roc_id, make_lead_headers(outsider["id"]))
        validate_error(refused_submit, ERR_NOT_ENGAGEMENT_LEAD, 403)

        approved = validate_success(
            api.qa_review_roc(
                roc_id,
                qa_review_payload(
                    decision="APPROVE",
                    qa_decision_note="Sampling, evidence and conclusions are consistent.",
                ),
                make_qa_reviewer_headers(scenario["qa_id"]),
            )
        )
        assert approved["status"] == "QA_APPROVED"
        assert (
            approved["qa_decision_note"]
            == "Sampling, evidence and conclusions are consistent."
        )
        assert_version_bumped_by(scenario["roc"]["version"], approved["version"])

        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["status"] == "REPORTING"
        assert engagement["posture"] == "FROZEN"


class TestScanningVendorConfinedToItsOwnCycles:
    """Two vendors hold the same role, so only the cycle's own vendor may act."""

    def test_a_foreign_vendor_is_refused_on_every_write_of_another_vendors_cycle(
        self, api, validated_cde_engagement
    ):
        """Publication, completion and the dispute ruling all belong to the owner.

        PRD: When `X-User-Role` is `AsvVendor`, `X-User-ID` is the `id` of the
        acting `AsvVendor` record; ownership checks compare the target scan cycle's
        `asv_vendor_id` to `X-User-ID`, and a vendor acting on a cycle that is not
        its own is refused with `ERR_VENDOR_SCOPE_FORBIDDEN` (HTTP 403).

        Design: Corner/rbac/rbac_scanning_vendor_is_confined_to_its_own_cycles
        """
        scenario = validated_cde_engagement
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        component_id = scenario["component_ids"]["pay-01"]
        owner = register_vendor(api)
        stranger = register_vendor(api, name="Bluewater ASV")
        cycle = schedule_scan_cycle(api, engagement_id, lead_id, owner["id"])

        refused_publish = api.create_scan_finding(
            cycle["id"],
            scan_finding_payload(
                component_id=component_id, plugin_reference="BW-90001", cvss_score=6.4
            ),
            make_asv_vendor_headers(stranger["id"]),
        )
        validate_error(refused_publish, ERR_VENDOR_SCOPE_FORBIDDEN, 403)
        assert_total_count(
            api.list_scan_findings(lead_headers, {"scan_cycle_id": cycle["id"]}), 0
        )

        finding = publish_finding(
            api,
            cycle["id"],
            owner["id"],
            component_id,
            plugin_reference="ASV-30877",
            cvss_score=7.5,
        )
        assert finding["severity_class"] == "HIGH_OR_ABOVE"

        refused_complete = api.complete_scan_cycle(
            cycle["id"], make_asv_vendor_headers(stranger["id"])
        )
        validate_error(refused_complete, ERR_VENDOR_SCOPE_FORBIDDEN, 403)
        held = validate_success(api.get_scan_cycle(cycle["id"], lead_headers))
        assert held["status"] == "SCHEDULED"
        assert held["scan_completed_at"] is None

        failing = complete_cycle(api, cycle["id"], owner["id"])
        assert failing["status"] == "FAILING"

        # The assessor raises the false-positive claim but has no vote on it.
        disputed = validate_success(
            api.dispute_scan_finding(
                finding["id"],
                dispute_payload(
                    dispute_rationale="The scanner fingerprinted a backported patch level."
                ),
                lead_headers,
            )
        )
        assert disputed["dispute_status"] == "DISPUTED"
        refused_by_lead = api.decide_scan_finding_dispute(
            finding["id"],
            dispute_decision_payload(
                decision="ACCEPT", decision_note="I raised it, so I will close it."
            ),
            lead_headers,
        )
        validate_error(refused_by_lead, ERR_UNAUTHORIZED, 403)

        refused_decision = api.decide_scan_finding_dispute(
            finding["id"],
            dispute_decision_payload(
                decision="ACCEPT", decision_note="Not our scan, but we agree."
            ),
            make_asv_vendor_headers(stranger["id"]),
        )
        validate_error(refused_decision, ERR_VENDOR_SCOPE_FORBIDDEN, 403)
        still_disputed = validate_success(
            api.get_scan_finding(finding["id"], lead_headers)
        )
        assert still_disputed["dispute_status"] == "DISPUTED"

        decided = validate_success(
            api.decide_scan_finding_dispute(
                finding["id"],
                dispute_decision_payload(
                    decision="ACCEPT",
                    decision_note="Confirmed as a false positive after manual review.",
                ),
                make_asv_vendor_headers(owner["id"]),
            )
        )
        assert decided["dispute_status"] == "ACCEPTED_FALSE_POSITIVE"
        assert_same_instant(decided["decided_at"], CLOCK_DEFAULT)

        settled = validate_success(api.get_scan_cycle(cycle["id"], lead_headers))
        assert settled["raw_high_finding_count"] == 1
        assert settled["accepted_false_positive_count"] == 1
        assert settled["effective_high_finding_count"] == 0
        assert settled["open_dispute_count"] == 0
        assert_finding_ledger_identity(settled)
        assert settled["status"] == "PASSING"
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["quarterly_scan_compliant"] is True


def _nomination_candidates(api) -> Scenario:
    """Four assessors and one engagement whose reviewer seat is still empty.

    Dana Reyes leads and is not authorised for review; Owen Marsh is active but
    unauthorised; Lena Ortiz is authorised and then suspended; Kim Vance is
    authorised and active.
    """
    scenario = build_registry(api)
    plain = register_assessor(
        api, SECOND_LEAD_NAME, SECOND_LEAD_EMAIL, LEAD_CERT_EXPIRES, qa_qualified=False
    )
    suspended = register_assessor(
        api, LENA_NAME, LENA_EMAIL, LEAD_CERT_EXPIRES, qa_qualified=True
    )
    validate_success(
        api.update_assessor(suspended["id"], {"status": "SUSPENDED"}, admin_headers())
    )
    engagement = open_engagement(api, scenario["lead_id"])
    scenario["plain_id"] = plain["id"]
    scenario["suspended_id"] = suspended["id"]
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement["id"]
    return scenario


class TestQaNominationSeparationQualificationAndStanding:
    """One endpoint, three refusals, and their order decides the answer."""

    def test_nominating_the_engagement_lead_breaches_separation_of_duties(self, api):
        """The lead cannot review his own engagement, however he is nominated.

        PRD: Nominating as quality-assurance reviewer the same individual who is
        the engagement's lead is refused with `ERR_SEGREGATION_OF_DUTIES`, and that
        refusal guards engagement creation, engagement amendment and the standalone
        nomination alike.

        Design: Corner/rbac/rbac_qa_nomination_enforces_separation_qualification_and_active_status_in_order
        """
        scenario = _nomination_candidates(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        # He is also unauthorised for review, yet separation is what answers.
        assert validate_success(api.get_assessor(lead_id, lead_headers))[
            "qa_qualified"
        ] is False
        refused = api.assign_qa_reviewer(engagement_id, lead_id, lead_headers)
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 422)
        held = read_engagement(api, engagement_id, lead_id)
        assert held["qa_reviewer_id"] is None
        assert_version_unchanged(scenario["engagement"]["version"], held["version"])

        # The same rule guards the commissioning payload itself.
        refused_creation = api.create_engagement(
            engagement_payload(
                lead_assessor_id=scenario["plain_id"],
                qa_reviewer_id=scenario["plain_id"],
                client_legal_name=SECOND_CLIENT,
                acquirer_name=SECOND_ACQUIRER,
                fieldwork_start_date=SECOND_FIELDWORK_START,
                fieldwork_end_date=SECOND_FIELDWORK_END,
            ),
            admin_headers(),
        )
        validate_error(refused_creation, ERR_SEGREGATION_OF_DUTIES, 422)
        assert_total_count(api.list_engagements(lead_headers), 1)

    def test_qualification_then_standing_decide_the_remaining_nominations(self, api):
        """An unauthorised outsider and a suspended one answer under their own codes.

        PRD: Nominating a reviewer whose `qa_qualified` flag is false is refused
        with `ERR_QA_NOT_QUALIFIED`, which guards engagement creation and the
        standalone nomination but not amendment.

        Design: Corner/rbac/rbac_qa_nomination_enforces_separation_qualification_and_active_status_in_order
        """
        scenario = _nomination_candidates(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        before = scenario["engagement"]["version"]

        refused_unqualified = api.assign_qa_reviewer(
            engagement_id, scenario["plain_id"], lead_headers
        )
        validate_error(refused_unqualified, ERR_QA_NOT_QUALIFIED, 422)

        # Lena clears separation and qualification, so her standing is what fails.
        suspended = validate_success(
            api.get_assessor(scenario["suspended_id"], lead_headers)
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["qa_qualified"] is True
        assert suspended["certification_status"] == "ACTIVE"
        refused_suspended = api.assign_qa_reviewer(
            engagement_id, scenario["suspended_id"], lead_headers
        )
        validate_error(refused_suspended, ERR_ASSESSOR_NOT_ACTIVE, 422)

        held = read_engagement(api, engagement_id, lead_id)
        assert held["qa_reviewer_id"] is None
        assert_version_unchanged(before, held["version"])

        nominated = validate_success(
            api.assign_qa_reviewer(engagement_id, scenario["qa_id"], lead_headers)
        )
        assert nominated["qa_reviewer_id"] == scenario["qa_id"]
        assert_version_bumped_by(before, nominated["version"])
        assert_total_count(
            api.list_engagements(lead_headers, {"qa_reviewer_id": scenario["qa_id"]}), 1
        )
