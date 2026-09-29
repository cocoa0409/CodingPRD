"""Refusals: the ladder's lower rungs, the 404 family and the state guards."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ASSESSOR_NOT_FOUND,
    ERR_ASV_NOT_APPROVED,
    ERR_CCW_MONITORING_INTERVAL_TOO_LONG,
    ERR_CCW_SECTION_INCOMPLETE,
    ERR_COMPONENT_NOT_FOUND,
    ERR_DUPLICATE_ASSESSOR_EMAIL,
    ERR_DUPLICATE_QUARTER_LABEL,
    ERR_DUPLICATE_VENDOR_NAME,
    ERR_ENGAGEMENT_FROZEN,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_FINDING_NOT_HIGH_SEVERITY,
    ERR_INVALID_CCW_STATE,
    ERR_INVALID_FINDING_DISPUTE_STATE,
    ERR_INVALID_REMEDIATION_STATE,
    ERR_INVALID_ROC_STATE,
    ERR_INVALID_SCAN_CYCLE_STATE,
    ERR_NO_APPLICABLE_REQUIREMENTS,
    ERR_QA_REVIEWER_NOT_ASSIGNED,
    ERR_REQUIREMENT_TESTING_INCOMPLETE,
    ERR_ROC_ALREADY_EXISTS,
    ERR_SEGMENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    NOT_FOUND_ERROR_IDS,
)
from test_helpers.assertions import (
    assert_finding_ledger_identity,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_total_count,
    assert_version_bumped_by,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    LEAD_EMAIL,
    LEAD_NAME,
    QA_EMAIL,
    ROLE_LEAD_ASSESSOR,
)
from test_helpers.factories import (
    assessor_payload,
    assign_payload,
    asv_vendor_payload,
    attest_payload,
    ccw_decision_payload,
    ccw_payload,
    change_log_payload,
    dispute_decision_payload,
    dispute_payload,
    engagement_payload,
    network_segment_payload,
    qa_review_payload,
    requirement_payload,
    retest_payload,
    revise_payload,
    roc_payload,
    scan_cycle_payload,
    scan_finding_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_component,
    build_engagement_with_gap,
    build_registry,
    build_scoping_engagement,
    complete_cycle,
    create_roc,
    declare_segment,
    draft_ccw,
    draw_plan,
    lock_scope,
    open_engagement,
    open_requirement,
    publish_finding,
    read_engagement,
    register_vendor,
    requirement_concluded,
    schedule_scan_cycle,
    submit_ccw,
    validated_segment,
)
from test_helpers.test_users import (
    UNKNOWN_ACTOR_ID,
    admin_headers,
    client_rep_headers,
    headers_with_unknown_user,
    headers_without_user_id,
    make_asv_vendor_headers,
    make_lead_headers,
)


class TestActorResolutionRunsFirst:
    """An unresolvable caller is refused before anything else is looked at."""

    def test_a_request_with_no_actor_header_is_refused_before_its_body_is_read(
        self, api, registry
    ):
        """The 401 wins over a missing field and an unknown lead in the same body.

        PRD: Authentication is always evaluated before authorization, and both are
        evaluated before the request body is inspected at all.

        Design: Corner/errors/error_unresolvable_actor_returns_unauthenticated_before_any_other_rule
        """
        payload = engagement_payload(lead_assessor_id=UNKNOWN_ACTOR_ID)
        del payload["assessment_year"]

        refused = api.create_engagement(
            payload, headers_without_user_id(ROLE_LEAD_ASSESSOR)
        )

        validate_error(refused, ERR_UNAUTHENTICATED, 401)
        assert_total_count(
            api.list_engagements(make_lead_headers(registry["lead_id"])), 0
        )

    def test_an_unknown_actor_identifier_is_refused_on_a_read_open_to_every_role(
        self, api, registry
    ):
        """A header that names nobody fails even where every role is admitted.

        PRD: If either header is absent, or if `X-User-ID` cannot be resolved to a
        known assessor record, a known scanning-vendor record, or a recognised
        opaque operator, the request is refused with `ERR_UNAUTHENTICATED` (HTTP
        401).

        Design: Corner/errors/error_unresolvable_actor_returns_unauthenticated_before_any_other_rule
        """
        refused = api.list_engagements(headers_with_unknown_user(ROLE_LEAD_ASSESSOR))

        validate_error(refused, ERR_UNAUTHENTICATED, 401)
        # The very same read answers once the caller is a registered assessor.
        assert_total_count(
            api.list_engagements(make_lead_headers(registry["lead_id"])), 0
        )


class TestEveryCollectionOwnsItsNotFoundCode:
    """One fabricated identifier draws fourteen different 404 identifiers."""

    def test_each_addressable_collection_answers_with_its_own_not_found_code(
        self, api, registry
    ):
        """The same unknown identifier is named differently by each collection.

        PRD: Each identifier in the URL path is resolved left to right, and the
        first unresolved one answers with that entity's own 404 code:
        `ERR_ASSESSOR_NOT_FOUND`, `ERR_ASV_VENDOR_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_COMPONENT_NOT_FOUND`, `ERR_SAMPLING_PLAN_NOT_FOUND`,
        `ERR_REQUIREMENT_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, `ERR_CCW_NOT_FOUND`,
        `ERR_REMEDIATION_ITEM_NOT_FOUND`, `ERR_ROC_NOT_FOUND`,
        `ERR_SCAN_CYCLE_NOT_FOUND`, `ERR_SCAN_FINDING_NOT_FOUND` or
        `ERR_CHANGE_LOG_ENTRY_NOT_FOUND`.

        Design: Corner/errors/error_every_path_identifier_answers_its_own_not_found_code
        """
        lead_headers = make_lead_headers(registry["lead_id"])
        paths = api.not_found_probe_paths(UNKNOWN_ACTOR_ID)
        assert len(paths) == len(NOT_FOUND_ERROR_IDS)

        seen = []
        for path, expected_error_id in zip(paths, NOT_FOUND_ERROR_IDS):
            refused = api.get_by_path(path, lead_headers)
            payload = validate_error(refused, expected_error_id, 404)
            seen.append(payload["error_id"])

        assert len(set(seen)) == len(NOT_FOUND_ERROR_IDS), (
            "the fourteen collections must not share one generic identifier: %s" % seen
        )
        # None of the probes brought a row into existence.
        assert_total_count(api.list_engagements(lead_headers), 0)
        assert_total_count(api.list_network_segments(lead_headers), 0)
        assert_total_count(api.list_change_log_entries(lead_headers), 0)


class TestBodyReferencesResolveAfterThePath:
    """The URL is resolved to the last identifier before the body is read."""

    def test_the_unknown_engagement_answers_before_the_unknown_component(
        self, api, scoping_engagement
    ):
        """One request names two unknown rows; the path one is reported first.

        PRD: Identifiers supplied in the request body are resolved only after every
        path identifier has resolved.

        Design: Corner/errors/error_body_reference_existence_is_resolved_after_the_path_identifier
        """
        payload = change_log_payload(
            change_type="APPLICATION_UPDATED",
            description="The payment application was patched to a new release.",
            affects_scope=False,
            component_id=UNKNOWN_ACTOR_ID,
        )

        on_unknown_engagement = api.create_change_log_entry(
            UNKNOWN_ACTOR_ID, payload, client_rep_headers()
        )
        validate_error(on_unknown_engagement, ERR_ENGAGEMENT_NOT_FOUND, 404)

        on_real_engagement = api.create_change_log_entry(
            scoping_engagement["engagement_id"], payload, client_rep_headers()
        )
        validate_error(on_real_engagement, ERR_COMPONENT_NOT_FOUND, 404)

        assert_total_count(
            api.list_change_log_entries(scoping_engagement["lead_headers"]), 0
        )

    def test_each_body_reference_answers_with_the_code_of_what_it_names(
        self, api, scoping_engagement
    ):
        """A dangling lead names the roster; a dangling parent names the zones.

        PRD: A `lead_assessor_id` or `qa_reviewer_id` that names no assessor answers
        `ERR_ASSESSOR_NOT_FOUND`; an `asv_vendor_id` that names no vendor answers
        `ERR_ASV_VENDOR_NOT_FOUND`; a `parent_segment_id` or `segment_id` that names
        no zone answers `ERR_SEGMENT_NOT_FOUND`; a `component_id` that names no
        component answers `ERR_COMPONENT_NOT_FOUND`.

        Design: Corner/errors/error_body_reference_existence_is_resolved_after_the_path_identifier
        """
        lead_headers = scoping_engagement["lead_headers"]

        dangling_lead = api.create_engagement(
            engagement_payload(
                lead_assessor_id=UNKNOWN_ACTOR_ID,
                client_legal_name="Harbor Fuel Stops LLC",
                fieldwork_start_date="2026-11-02",
                fieldwork_end_date="2026-11-20",
            ),
            lead_headers,
        )
        validate_error(dangling_lead, ERR_ASSESSOR_NOT_FOUND, 404)

        dangling_parent = api.create_network_segment(
            scoping_engagement["engagement_id"],
            network_segment_payload(
                name="CDE-CHILD",
                segment_class="CDE",
                parent_segment_id=UNKNOWN_ACTOR_ID,
            ),
            lead_headers,
        )
        validate_error(dangling_parent, ERR_SEGMENT_NOT_FOUND, 404)

        assert_total_count(api.list_engagements(lead_headers), 1)
        assert_total_count(api.list_network_segments(lead_headers), 0)


class TestNaturalKeysAreGuardedOnCreateAndOnAmend:
    """A registry key collides the same way whichever verb reaches it."""

    def test_an_assessor_email_collides_on_registration_and_on_amendment(
        self, api, registry
    ):
        """The roster refuses the duplicate address twice over, and changes nothing.

        PRD: Attempting to register a second assessor under an email already in the
        registry is refused with `ERR_DUPLICATE_ASSESSOR_EMAIL`, and the same
        refusal guards an amendment that would collide with another assessor's
        address.

        Design: Corner/errors/error_natural_key_uniqueness_on_both_create_and_amend
        """
        admin = admin_headers()

        on_registration = api.create_assessor(
            assessor_payload(full_name="Owen Marsh", email=LEAD_EMAIL), admin
        )
        validate_error(on_registration, ERR_DUPLICATE_ASSESSOR_EMAIL, 422)
        assert_total_count(api.list_assessors(registry["lead_headers"]), 2)

        on_amendment = api.update_assessor(
            registry["qa_id"], {"email": LEAD_EMAIL}, admin
        )
        validate_error(on_amendment, ERR_DUPLICATE_ASSESSOR_EMAIL, 422)

        reviewer = validate_success(
            api.get_assessor(registry["qa_id"], registry["lead_headers"])
        )
        assert reviewer["email"] == QA_EMAIL
        assert reviewer["version"] == registry["qa"]["version"]

    def test_a_vendor_name_collides_with_another_row_but_never_with_its_own(
        self, api, registry
    ):
        """Resending a vendor's own trading name is an amendment, not a collision.

        PRD: Approved Scanning Vendors are registered in parallel, with a trading
        `name` that must be unique across the vendor registry — a collision is
        refused with `ERR_DUPLICATE_VENDOR_NAME` on both registration and amendment
        — and an `approval_expires_at` instant at which the vendor's approval
        lapses.

        Design: Corner/errors/error_natural_key_uniqueness_on_both_create_and_amend
        """
        admin = admin_headers()
        lead_headers = registry["lead_headers"]
        northstar = register_vendor(api, name="Northstar ASV")
        bluewater = register_vendor(
            api, name="Bluewater ASV", approval_expires_at="2027-06-30T00:00:00Z"
        )

        on_registration = api.create_asv_vendor(
            asv_vendor_payload(name="Northstar ASV"), admin
        )
        validate_error(on_registration, ERR_DUPLICATE_VENDOR_NAME, 422)
        assert_total_count(api.list_asv_vendors(lead_headers), 2)

        on_amendment = api.update_asv_vendor(
            bluewater["id"], {"name": "Northstar ASV"}, admin
        )
        validate_error(on_amendment, ERR_DUPLICATE_VENDOR_NAME, 422)
        held = validate_success(api.get_asv_vendor(bluewater["id"], lead_headers))
        assert held["name"] == "Bluewater ASV"
        assert held["version"] == bluewater["version"]

        amended = validate_success(
            api.update_asv_vendor(
                bluewater["id"],
                {
                    "name": "Bluewater ASV",
                    "approval_expires_at": "2028-06-30T00:00:00Z",
                },
                admin,
            )
        )
        assert amended["name"] == "Bluewater ASV"
        assert_version_bumped_by(bluewater["version"], amended["version"], 1)
        untouched = validate_success(api.get_asv_vendor(northstar["id"], lead_headers))
        assert untouched["version"] == northstar["version"]


def _engagement_holding_a_third_quarter_cycle(api) -> Scenario:
    """A commissioned engagement with one 2026-Q3 scan booked and two vendors.

    One vendor's approval runs to the end of 2027; the other's lapsed a month
    before the current clock, so only the first can be handed new work.
    """
    scenario = build_scoping_engagement(api)
    approved = register_vendor(
        api, name="Northstar ASV", approval_expires_at="2027-12-31T00:00:00Z"
    )
    lapsed = register_vendor(
        api, name="Lapsed Scan Co", approval_expires_at="2026-07-01T00:00:00Z"
    )
    scenario["approved_vendor"] = approved
    scenario["lapsed_vendor"] = lapsed
    scenario["cycle"] = schedule_scan_cycle(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        approved["id"],
        quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z",
    )
    return scenario


class TestSchedulingChecksTheVendorBeforeTheCalendar:
    """A lapsed vendor and a repeated label in one request: the vendor answers."""

    def test_a_lapsed_vendor_is_reported_even_when_the_label_also_repeats(self, api):
        """The vendor's standing is settled before the quarter label is looked at.

        PRD: Two checks guard scheduling, and their order is fixed by the ladder:
        the named vendor's `effective_approval` must be `APPROVED` at the logical
        clock, or the request is refused with `ERR_ASV_NOT_APPROVED`, and only then
        is the calendar consulted.

        Design: Corner/errors/error_unapproved_vendor_outranks_the_duplicate_quarter_label
        """
        scenario = _engagement_holding_a_third_quarter_cycle(api)
        lead_headers = scenario["lead_headers"]

        lapsed = validate_success(
            api.get_asv_vendor(scenario["lapsed_vendor"]["id"], lead_headers)
        )
        assert lapsed["approval_status"] == "APPROVED"
        assert lapsed["effective_approval"] == "EXPIRED"

        refused = api.create_scan_cycle(
            scenario["engagement_id"],
            scan_cycle_payload(
                asv_vendor_id=scenario["lapsed_vendor"]["id"],
                quarter_label="2026-Q3",
                window_start="2026-10-01T00:00:00Z",
            ),
            lead_headers,
        )

        validate_error(refused, ERR_ASV_NOT_APPROVED, 422)
        assert_total_count(
            api.list_scan_cycles(
                lead_headers, {"engagement_id": scenario["engagement_id"]}
            ),
            1,
        )

    def test_the_repeated_quarter_label_surfaces_once_the_vendor_is_approved(
        self, api
    ):
        """The label is the engagement's own key, so only a new quarter is booked.

        PRD: Scheduling one is lead-only and carries a `quarter_label` such as
        `2026-Q3` — client-facing, and unique within the engagement, a repeat being
        refused with `ERR_DUPLICATE_QUARTER_LABEL` — the `asv_vendor_id` of the
        vendor that will run the scan, and a `window_start` instant opening the scan
        window.

        Design: Corner/errors/error_unapproved_vendor_outranks_the_duplicate_quarter_label
        """
        scenario = _engagement_holding_a_third_quarter_cycle(api)
        lead_headers = scenario["lead_headers"]
        vendor_id = scenario["approved_vendor"]["id"]

        repeated = api.create_scan_cycle(
            scenario["engagement_id"],
            scan_cycle_payload(
                asv_vendor_id=vendor_id,
                quarter_label="2026-Q3",
                window_start="2026-10-01T00:00:00Z",
            ),
            lead_headers,
        )
        validate_error(repeated, ERR_DUPLICATE_QUARTER_LABEL, 422)

        fourth_quarter = validate_success(
            api.create_scan_cycle(
                scenario["engagement_id"],
                scan_cycle_payload(
                    asv_vendor_id=vendor_id,
                    quarter_label="2026-Q4",
                    window_start="2026-10-01T00:00:00Z",
                ),
                lead_headers,
            ),
            201,
        )
        assert fourth_quarter["quarter_label"] == "2026-Q4"
        assert fourth_quarter["status"] == "SCHEDULED"
        assert_same_instant(fourth_quarter["window_end"], "2026-12-30T00:00:00Z")

        assert_total_count(
            api.list_scan_cycles(
                lead_headers, {"engagement_id": scenario["engagement_id"]}
            ),
            2,
        )
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["quarterly_scan_compliant"] is False


class TestReportCreationWalksItsPreconditions:
    """Authoring the report is refused until the programme is truly finished."""

    def test_a_report_needs_at_least_one_applicable_requirement(
        self, api, fieldwork_engagement
    ):
        """With nothing in the programme there is no denominator to divide by.

        PRD: Its `applicable_requirement_count` must be at least 1, so that the
        compliance denominator is non-zero, or the request answers
        `ERR_NO_APPLICABLE_REQUIREMENTS`.

        Design: Corner/errors/error_report_creation_gates_and_the_single_report_row_rule
        """
        lead_headers = fieldwork_engagement["lead_headers"]
        engagement = read_engagement(
            api,
            fieldwork_engagement["engagement_id"],
            fieldwork_engagement["lead_id"],
        )
        assert engagement["status"] == "FIELDWORK"
        assert engagement["posture"] == "OPEN"
        assert engagement["applicable_requirement_count"] == 0

        refused = api.create_roc(
            fieldwork_engagement["engagement_id"], roc_payload(), lead_headers
        )

        validate_error(refused, ERR_NO_APPLICABLE_REQUIREMENTS, 422)
        assert_total_count(
            api.list_rocs(
                lead_headers,
                {"engagement_id": fieldwork_engagement["engagement_id"]},
            ),
            0,
        )

    def test_a_report_needs_every_requirement_to_have_reached_a_conclusion(
        self, api, fieldwork_engagement
    ):
        """One untouched requirement is enough to hold the report back.

        PRD: No requirement of the engagement may still be at `NOT_STARTED` or
        `IN_TESTING` — every requirement must have reached a conclusion — or the
        request answers `ERR_REQUIREMENT_TESTING_INCOMPLETE`.

        Design: Corner/errors/error_report_creation_gates_and_the_single_report_row_rule
        """
        lead_headers = fieldwork_engagement["lead_headers"]
        requirement = open_requirement(
            api,
            fieldwork_engagement["engagement_id"],
            fieldwork_engagement["lead_id"],
            requirement_ref="1.2.1",
            requirement_family="R1",
        )
        assert requirement["test_status"] == "NOT_STARTED"

        refused = api.create_roc(
            fieldwork_engagement["engagement_id"], roc_payload(), lead_headers
        )

        validate_error(refused, ERR_REQUIREMENT_TESTING_INCOMPLETE, 422)
        assert_total_count(
            api.list_rocs(
                lead_headers,
                {"engagement_id": fieldwork_engagement["engagement_id"]},
            ),
            0,
        )

    def test_a_revision_reuses_the_one_report_row_instead_of_minting_another(
        self, api, roc_in_qa
    ):
        """Back at fieldwork after a rejection, a fresh report is still refused.

        PRD: And at most one report may ever exist per engagement, so a second
        attempt answers `ERR_ROC_ALREADY_EXISTS`; revisions reuse the existing row
        rather than creating another.

        Design: Corner/errors/error_report_creation_gates_and_the_single_report_row_rule
        """
        lead_headers = roc_in_qa["lead_headers"]
        engagement_id = roc_in_qa["engagement_id"]

        # While the report is in review the engagement is frozen to child writes.
        blocked = api.create_requirement_assessment(
            engagement_id,
            requirement_payload(requirement_ref="1.2.2", requirement_family="R1"),
            lead_headers,
        )
        validate_error(blocked, ERR_ENGAGEMENT_FROZEN, 409)
        assert_total_count(
            api.list_requirement_assessments(
                lead_headers, {"engagement_id": engagement_id}
            ),
            1,
        )

        rejected = validate_success(
            api.qa_review_roc(
                roc_in_qa["roc_id"],
                qa_review_payload(
                    decision="REJECT",
                    qa_decision_note="The sampling rationale needs to be expanded.",
                ),
                roc_in_qa["qa_headers"],
            )
        )
        assert rejected["status"] == "QA_REJECTED"

        revised = validate_success(
            api.revise_roc(roc_in_qa["roc_id"], revise_payload(), lead_headers)
        )
        assert revised["status"] == "DRAFTING"
        assert revised["revision_count"] == 1
        engagement = read_engagement(api, engagement_id, roc_in_qa["lead_id"])
        assert engagement["status"] == "FIELDWORK"
        assert engagement["posture"] == "OPEN"

        second_report = api.create_roc(
            engagement_id, roc_payload("v1.1"), lead_headers
        )
        validate_error(second_report, ERR_ROC_ALREADY_EXISTS, 422)

        rows = assert_total_count(
            api.list_rocs(lead_headers, {"engagement_id": engagement_id}), 1
        )
        assert rows[0]["roc_version_label"] == "v1.0"


def _report_on_an_engagement_with_no_reviewer(api) -> Scenario:
    """A report sitting at DRAFTING on an engagement that nominated no reviewer.

    The engagement is commissioned without a `qa_reviewer_id`, then carried all
    the way to a single IN_PLACE requirement so the report may be authored.
    """
    scenario = build_registry(api)
    lead_id = scenario["lead_id"]
    engagement = open_engagement(api, lead_id)
    engagement_id = engagement["id"]
    segment = validated_segment(api, engagement_id, lead_id, name="CDE-CORE")
    hosts = {}
    for hostname, component_type, function_class, stores_chd in (
        ("app-01", "SERVER", "SECURITY_SERVICE", False),
        ("pay-01", "APPLICATION", "PAYMENT_APPLICATION", True),
        ("pay-02", "APPLICATION", "PAYMENT_APPLICATION", True),
    ):
        hosts[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            segment["id"],
            hostname,
            component_type=component_type,
            function_class=function_class,
            stores_chd=stores_chd,
        )
    draw_plan(api, engagement_id, lead_id, plan_variant="FINAL")
    lock_scope(api, engagement_id, lead_id)
    requirement_concluded(
        api,
        engagement_id,
        lead_id,
        "1.2.1",
        "R1",
        hosts["pay-01"]["id"],
        conclusion="IN_PLACE",
    )
    roc = create_roc(api, engagement_id, lead_id)
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement_id
    scenario["roc"] = roc
    scenario["roc_id"] = roc["id"]
    return scenario


class TestReportHandoverNeedsAReviewerAndTheRightState:
    """Quality assurance cannot begin without a reviewer or from the wrong state."""

    def test_handing_over_a_report_with_nobody_nominated_is_refused(self, api):
        """Nominating the reviewer unblocks the handover on a frozen engagement.

        PRD: It requires the engagement's `qa_reviewer_id` to be set, and a report
        handed over on an engagement with no nominated reviewer is refused with
        `ERR_QA_REVIEWER_NOT_ASSIGNED`.

        Design: Corner/errors/error_qa_submission_requires_a_nominated_reviewer_and_a_drafting_report
        """
        scenario = _report_on_an_engagement_with_no_reviewer(api)
        lead_headers = scenario["lead_headers"]

        refused = api.qa_submit_roc(scenario["roc_id"], lead_headers)
        validate_error(refused, ERR_QA_REVIEWER_NOT_ASSIGNED, 422)

        held = validate_success(api.get_roc(scenario["roc_id"], lead_headers))
        assert held["status"] == "DRAFTING"
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["qa_reviewer_id"] is None
        assert engagement["status"] == "REPORTING"
        assert engagement["posture"] == "FROZEN"

        # Nominating the reviewer stays available even under a frozen posture.
        nominated = validate_success(
            api.assign_qa_reviewer(
                scenario["engagement_id"], scenario["qa_id"], lead_headers
            )
        )
        assert nominated["qa_reviewer_id"] == scenario["qa_id"]
        assert nominated["posture"] == "FROZEN"

        handed_over = validate_success(
            api.qa_submit_roc(scenario["roc_id"], lead_headers)
        )
        assert handed_over["status"] == "IN_QA"

    def test_a_drafting_report_cannot_be_attested(self, api, roc_in_drafting):
        """Attestation waits for the reviewer's approval, not the author's wish.

        PRD: It is lead-only, available only from `QA_APPROVED`, and carries
        `attestation_signature_name` — the typed signature.

        Design: Corner/errors/error_qa_submission_requires_a_nominated_reviewer_and_a_drafting_report
        """
        lead_headers = roc_in_drafting["lead_headers"]

        refused = api.attest_roc(
            roc_in_drafting["roc_id"],
            attest_payload(attestation_signature_name=LEAD_NAME),
            lead_headers,
        )

        validate_error(refused, ERR_INVALID_ROC_STATE, 409)
        held = validate_success(api.get_roc(roc_in_drafting["roc_id"], lead_headers))
        assert held["status"] == "DRAFTING"
        assert held["attested_at"] is None
        assert held["attestation_signature_name"] is None

    def test_a_report_already_in_review_cannot_be_handed_over_again(
        self, api, roc_in_qa
    ):
        """The handover exists once, from DRAFTING, and not from review itself.

        PRD: Handing the report to quality assurance is lead-only and available only
        from `DRAFTING`; any other report status answers `ERR_INVALID_ROC_STATE`.

        Design: Corner/errors/error_qa_submission_requires_a_nominated_reviewer_and_a_drafting_report
        """
        lead_headers = roc_in_qa["lead_headers"]

        refused = api.qa_submit_roc(roc_in_qa["roc_id"], lead_headers)

        validate_error(refused, ERR_INVALID_ROC_STATE, 409)
        held = validate_success(api.get_roc(roc_in_qa["roc_id"], lead_headers))
        assert held["status"] == "IN_QA"
        assert held["version"] == roc_in_qa["roc"]["version"]

    def test_a_report_in_review_cannot_be_taken_back_into_fieldwork(
        self, api, roc_in_qa
    ):
        """Only the reviewer's rejection opens the road back to fieldwork.

        PRD: Taking a rejected report back into fieldwork is lead-only, available
        only from `QA_REJECTED`, and carries a `revision_note`.

        Design: Corner/errors/error_qa_submission_requires_a_nominated_reviewer_and_a_drafting_report
        """
        lead_headers = roc_in_qa["lead_headers"]

        refused = api.revise_roc(
            roc_in_qa["roc_id"], revise_payload(), lead_headers
        )

        validate_error(refused, ERR_INVALID_ROC_STATE, 409)
        held = validate_success(api.get_roc(roc_in_qa["roc_id"], lead_headers))
        assert held["status"] == "IN_QA"
        assert held["revision_count"] == 0
        engagement = read_engagement(api, roc_in_qa["engagement_id"], roc_in_qa["lead_id"])
        assert engagement["status"] == "REPORTING"
        assert engagement["posture"] == "FROZEN"


def _gapped_requirement_on_r1(api) -> Scenario:
    """A FIELDWORK engagement whose requirement 1.2.1 was found NOT_IN_PLACE."""
    return build_engagement_with_gap(
        api, requirement_ref="1.2.1", requirement_family="R1"
    )


class TestWorksheetSubmissionAndDecisionGates:
    """A worksheet is checked twice: once on submission, once on the decision."""

    def test_a_worksheet_missing_a_narrative_section_cannot_be_submitted(self, api):
        """The blank validation narrative is tolerated in draft, never on submission.

        PRD: Submission re-validates the paperwork: all five narrative sections
        `constraint_text`, `objective_text`, `identified_risk_text`,
        `validation_text` and `maintenance_text` must be non-empty and `control_refs`
        must hold at least one entry, or the submission is refused with
        `ERR_CCW_SECTION_INCOMPLETE`.

        Design: Corner/errors/error_worksheet_submission_and_decision_gates_in_ladder_order
        """
        scenario = _gapped_requirement_on_r1(api)
        lead_headers = scenario["lead_headers"]

        worksheet = validate_success(
            api.create_ccw(
                scenario["requirement_id"],
                ccw_payload(
                    expected_requirement_assessment_version=scenario["requirement"][
                        "version"
                    ],
                    validation_text="",
                ),
                lead_headers,
            ),
            201,
        )
        assert worksheet["status"] == "DRAFT"
        assert worksheet["control_depth_points"] == 80
        assert worksheet["monitoring_factor"] == 80
        assert worksheet["risk_offset_points"] == 55
        assert worksheet["thin_control_capped"] is False
        assert float(worksheet["rigor_score"]) == 73.75

        refused = api.submit_ccw(worksheet["id"], lead_headers)

        validate_error(refused, ERR_CCW_SECTION_INCOMPLETE, 422)
        held = validate_success(api.get_ccw(worksheet["id"], lead_headers))
        assert held["status"] == "DRAFT"
        assert held["version"] == worksheet["version"]

    def test_a_monthly_monitoring_interval_blocks_acceptance(self, api):
        """A control verified every 45 days is not monitoring anything in time.

        PRD: Acceptance additionally demands two things of the worksheet itself:
        `monitoring_interval_days` must not exceed 30, or the acceptance is refused
        with `ERR_CCW_MONITORING_INTERVAL_TOO_LONG`, and `rigor_score` must have
        reached 70.00 — the threshold is inclusive, so a score of exactly 70.00
        passes and 69.99 does not — or the acceptance is refused with
        `ERR_CCW_RIGOR_INSUFFICIENT`.

        Design: Corner/errors/error_worksheet_submission_and_decision_gates_in_ladder_order
        """
        scenario = _gapped_requirement_on_r1(api)
        lead_headers = scenario["lead_headers"]
        worksheet = draft_ccw(
            api,
            scenario["requirement_id"],
            scenario["lead_id"],
            scenario["requirement"]["version"],
            monitoring_interval_days=45,
        )
        assert worksheet["monitoring_factor"] == 25
        assert float(worksheet["rigor_score"]) == 54.50
        submitted = submit_ccw(api, worksheet["id"], scenario["lead_id"])
        assert submitted["status"] == "SUBMITTED"

        refused = api.decide_ccw(
            worksheet["id"],
            ccw_decision_payload(decision="ACCEPT"),
            scenario["qa_headers"],
        )

        validate_error(refused, ERR_CCW_MONITORING_INTERVAL_TOO_LONG, 422)
        held = validate_success(api.get_ccw(worksheet["id"], lead_headers))
        assert held["status"] == "SUBMITTED"
        assert held["decided_at"] is None
        requirement = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )
        assert_requirement_dimensions(
            requirement, test_status="NOT_IN_PLACE", remediation_status="GAP_OPEN"
        )
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["accepted_ccw_count"] == 0

    def test_a_rejected_worksheet_cannot_be_submitted_a_second_time(self, api):
        """Rejection is final for that worksheet; a fresh argument needs a fresh one.

        PRD: Submitting a worksheet for decision is lead-only, requires a posture
        other than `FROZEN`, is available only from `DRAFT` — any other state answers
        `ERR_INVALID_CCW_STATE` — and requires the parent requirement to still be
        `NOT_IN_PLACE`.

        Design: Corner/errors/error_worksheet_submission_and_decision_gates_in_ladder_order
        """
        scenario = _gapped_requirement_on_r1(api)
        lead_headers = scenario["lead_headers"]
        requirement_id = scenario["requirement_id"]
        first = draft_ccw(
            api,
            requirement_id,
            scenario["lead_id"],
            scenario["requirement"]["version"],
        )
        current = validate_success(
            api.get_requirement_assessment(requirement_id, lead_headers)
        )
        second = draft_ccw(
            api,
            requirement_id,
            scenario["lead_id"],
            current["version"],
            monitoring_interval_days=45,
        )
        superseded = validate_success(api.get_ccw(first["id"], lead_headers))
        assert superseded["status"] == "SUPERSEDED"
        submit_ccw(api, second["id"], scenario["lead_id"])

        rejected = validate_success(
            api.decide_ccw(
                second["id"],
                ccw_decision_payload(
                    decision="REJECT",
                    reviewer_note="The named controls do not meet the objective.",
                ),
                scenario["qa_headers"],
            )
        )
        assert rejected["status"] == "REJECTED"
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["open_gap_count"] == 1

        refused = api.submit_ccw(second["id"], lead_headers)

        validate_error(refused, ERR_INVALID_CCW_STATE, 409)
        assert_total_count(
            api.list_ccws(lead_headers, {"requirement_assessment_id": requirement_id}),
            2,
        )
        assert_total_count(
            api.list_ccws(
                lead_headers,
                {"engagement_id": scenario["engagement_id"], "status": "REJECTED"},
            ),
            1,
        )


def _cycle_with_a_low_and_a_high_finding(api) -> Scenario:
    """A scheduled 2026-Q3 scan holding one 3.9 and one 7.5 finding."""
    scenario = build_scoping_engagement(api)
    engagement_id = scenario["engagement_id"]
    lead_id = scenario["lead_id"]
    segment = declare_segment(
        api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
    )
    host = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pay-01",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
    )
    vendor = register_vendor(api)
    cycle = schedule_scan_cycle(
        api,
        engagement_id,
        lead_id,
        vendor["id"],
        quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z",
    )
    scenario["host"] = host
    scenario["vendor"] = vendor
    scenario["vendor_id"] = vendor["id"]
    scenario["cycle"] = cycle
    scenario["cycle_id"] = cycle["id"]
    scenario["low_finding"] = publish_finding(
        api,
        cycle["id"],
        vendor["id"],
        host["id"],
        plugin_reference="ASV-11022",
        cvss_score=3.9,
    )
    scenario["high_finding"] = publish_finding(
        api,
        cycle["id"],
        vendor["id"],
        host["id"],
        plugin_reference="CVE-2026-31881",
        cvss_score=7.5,
    )
    return scenario


class TestScanCycleAndDisputeStatesAreCheckedSeparately:
    """The cycle's status and the finding's dispute status are different gates."""

    def test_a_low_finding_cannot_be_disputed_and_a_high_one_only_once(self, api):
        """There is nothing to gain by disputing a finding that blocks nothing.

        PRD: Three conditions apply: the finding's `severity_class` must be
        `HIGH_OR_ABOVE`, since a low finding does not block anything and there is
        nothing to gain by disputing it — a low finding answers
        `ERR_FINDING_NOT_HIGH_SEVERITY`; the finding's `dispute_status` must be
        `NONE`, and a second dispute on the same finding answers
        `ERR_INVALID_FINDING_DISPUTE_STATE`; and the parent cycle's `status` must be
        `FAILING` or `DISPUTE_OPEN`.

        Design: Corner/errors/error_scan_cycle_and_dispute_states_are_checked_separately
        """
        scenario = _cycle_with_a_low_and_a_high_finding(api)
        lead_headers = scenario["lead_headers"]
        closed = complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])
        assert closed["status"] == "FAILING"
        assert closed["raw_high_finding_count"] == 1
        assert closed["effective_high_finding_count"] == 1
        assert_finding_ledger_identity(closed)

        on_low = api.dispute_scan_finding(
            scenario["low_finding"]["id"], dispute_payload(), client_rep_headers()
        )
        validate_error(on_low, ERR_FINDING_NOT_HIGH_SEVERITY, 422)
        untouched = validate_success(
            api.get_scan_finding(scenario["low_finding"]["id"], lead_headers)
        )
        assert untouched["severity_class"] == "LOW"
        assert untouched["dispute_status"] == "NONE"

        disputed = validate_success(
            api.dispute_scan_finding(
                scenario["high_finding"]["id"],
                dispute_payload(
                    dispute_rationale="The host does not serve the banner the plugin keys on."
                ),
                client_rep_headers(),
            )
        )
        assert disputed["dispute_status"] == "DISPUTED"
        cycle = validate_success(api.get_scan_cycle(scenario["cycle_id"], lead_headers))
        assert cycle["status"] == "DISPUTE_OPEN"
        assert cycle["open_dispute_count"] == 1

        repeated = api.dispute_scan_finding(
            scenario["high_finding"]["id"],
            dispute_payload(dispute_rationale="Raising the same objection again."),
            client_rep_headers(),
        )
        validate_error(repeated, ERR_INVALID_FINDING_DISPUTE_STATE, 409)
        held = validate_success(
            api.get_scan_finding(scenario["high_finding"]["id"], lead_headers)
        )
        assert (
            held["dispute_rationale"]
            == "The host does not serve the banner the plugin keys on."
        )
        assert held["dispute_status"] == "DISPUTED"

    def test_a_completed_cycle_takes_no_further_findings(self, api):
        """The vendor's own scan is closed, so its ledger stops moving.

        PRD: Only the cycle's own vendor may publish findings against it, and only
        while the cycle is still `SCHEDULED`; a finding pushed at a completed cycle
        answers `ERR_INVALID_SCAN_CYCLE_STATE`.

        Design: Corner/errors/error_scan_cycle_and_dispute_states_are_checked_separately
        """
        scenario = _cycle_with_a_low_and_a_high_finding(api)
        lead_headers = scenario["lead_headers"]
        complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])

        refused = api.create_scan_finding(
            scenario["cycle_id"],
            scan_finding_payload(
                component_id=scenario["host"]["id"],
                plugin_reference="ASV-77401",
                cvss_score=9.1,
            ),
            make_asv_vendor_headers(scenario["vendor_id"]),
        )

        validate_error(refused, ERR_INVALID_SCAN_CYCLE_STATE, 409)
        assert_total_count(
            api.list_scan_findings(
                lead_headers, {"scan_cycle_id": scenario["cycle_id"]}
            ),
            2,
        )
        cycle = validate_success(api.get_scan_cycle(scenario["cycle_id"], lead_headers))
        assert cycle["raw_high_finding_count"] == 1
        assert_finding_ledger_identity(cycle)

    def test_a_cycle_can_only_be_closed_from_scheduled(self, api):
        """Closing the scan a second time changes nothing about the first close.

        PRD: Closing the scan belongs to the cycle's vendor, takes no payload, is
        available only from `SCHEDULED`, and branches on the ledger rather than on
        anything the caller supplies.

        Design: Corner/errors/error_scan_cycle_and_dispute_states_are_checked_separately
        """
        scenario = _cycle_with_a_low_and_a_high_finding(api)
        lead_headers = scenario["lead_headers"]
        closed = complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])
        assert_same_instant(closed["scan_completed_at"], CLOCK_DEFAULT)
        assert closed["attestation_of_scan_compliance"] is False

        refused = api.complete_scan_cycle(
            scenario["cycle_id"], make_asv_vendor_headers(scenario["vendor_id"])
        )

        validate_error(refused, ERR_INVALID_SCAN_CYCLE_STATE, 409)
        held = validate_success(api.get_scan_cycle(scenario["cycle_id"], lead_headers))
        assert held["status"] == "FAILING"
        assert held["version"] == closed["version"]
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["quarterly_scan_compliant"] is False

    def test_a_finding_nobody_disputed_cannot_be_decided(self, api):
        """A decision needs a claim on the table first.

        PRD: Deciding carries a `decision` of `ACCEPT` or `REJECT` and a
        `decision_note`, and is available only from `DISPUTED`.

        Design: Corner/errors/error_scan_cycle_and_dispute_states_are_checked_separately
        """
        scenario = _cycle_with_a_low_and_a_high_finding(api)
        lead_headers = scenario["lead_headers"]
        complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])

        refused = api.decide_scan_finding_dispute(
            scenario["low_finding"]["id"],
            dispute_decision_payload(decision="ACCEPT"),
            make_asv_vendor_headers(scenario["vendor_id"]),
        )

        validate_error(refused, ERR_INVALID_FINDING_DISPUTE_STATE, 409)
        held = validate_success(
            api.get_scan_finding(scenario["low_finding"]["id"], lead_headers)
        )
        assert held["dispute_status"] == "NONE"
        assert held["decided_at"] is None
        cycle = validate_success(api.get_scan_cycle(scenario["cycle_id"], lead_headers))
        assert cycle["accepted_false_positive_count"] == 0
        assert_finding_ledger_identity(cycle)


def _sole_remediation_item(api, scenario) -> dict:
    """Find the one item the NOT_IN_PLACE conclusion minted for the requirement."""
    rows = assert_total_count(
        api.list_remediation_items(
            scenario["lead_headers"],
            {"requirement_assessment_id": scenario["requirement_id"]},
        ),
        1,
    )
    return rows[0]


class TestRemediationTransitionsRequireTheRightLedgerState:
    """An item is assigned from two states and retested from exactly one."""

    def test_an_unassigned_item_cannot_be_retested(self, api):
        """Nobody has committed to the fix yet, so there is nothing to retest.

        PRD: Recording the retest is open to the lead or a staff assessor, requires a
        posture other than `FROZEN`, is available only from `IN_PROGRESS`, and carries
        an `outcome` of `PASS` or `FAIL` plus an optional `note`.

        Design: Corner/errors/error_remediation_transitions_require_the_right_ledger_state
        """
        scenario = _gapped_requirement_on_r1(api)
        lead_headers = scenario["lead_headers"]
        item = _sole_remediation_item(api, scenario)
        assert item["status"] == "OPEN"
        assert item["source"] == "REQUIREMENT_CONCLUSION"
        assert item["severity"] == "MEDIUM"
        assert item["retest_count"] == 0

        refused = api.retest_remediation_item(
            item["id"], retest_payload(outcome="PASS"), lead_headers
        )

        validate_error(refused, ERR_INVALID_REMEDIATION_STATE, 409)
        held = validate_success(api.get_remediation_item(item["id"], lead_headers))
        assert held["status"] == "OPEN"
        assert held["retest_count"] == 0
        assert held["version"] == item["version"]

    def test_assignment_is_refused_in_progress_and_allowed_again_after_a_failure(
        self, api
    ):
        """The owner and date are rewritten only from the failed-retest state.

        PRD: Assignment is available from `OPEN` and from `RETEST_FAILED`, and any
        other state answers `ERR_INVALID_REMEDIATION_STATE`; from `RETEST_FAILED` it
        overwrites the previous owner and date.

        Design: Corner/errors/error_remediation_transitions_require_the_right_ledger_state
        """
        scenario = _gapped_requirement_on_r1(api)
        lead_headers = scenario["lead_headers"]
        engagement_id = scenario["engagement_id"]
        item = _sole_remediation_item(api, scenario)

        assigned = validate_success(
            api.assign_remediation_item(
                item["id"],
                assign_payload(
                    owner_reference="Client Network Team", due_date="2026-08-20"
                ),
                lead_headers,
            )
        )
        assert assigned["status"] == "IN_PROGRESS"
        assert assigned["owner_reference"] == "Client Network Team"
        assert assigned["due_date"] == "2026-08-20"
        assert (
            read_engagement(api, engagement_id, scenario["lead_id"])["open_gap_count"]
            == 1
        )

        refused = api.assign_remediation_item(
            item["id"],
            assign_payload(owner_reference="Client Platform Team", due_date="2026-08-24"),
            lead_headers,
        )
        validate_error(refused, ERR_INVALID_REMEDIATION_STATE, 409)
        held = validate_success(api.get_remediation_item(item["id"], lead_headers))
        assert held["owner_reference"] == "Client Network Team"
        assert held["due_date"] == "2026-08-20"

        failed = validate_success(
            api.retest_remediation_item(
                item["id"],
                retest_payload(
                    outcome="FAIL", note="The ruleset still permits the traffic."
                ),
                lead_headers,
            )
        )
        assert failed["status"] == "RETEST_FAILED"
        assert failed["retest_count"] == 1
        assert (
            read_engagement(api, engagement_id, scenario["lead_id"])["posture"]
            == "RESTRICTED"
        )

        reassigned = validate_success(
            api.assign_remediation_item(
                item["id"],
                assign_payload(
                    owner_reference="Client Platform Team", due_date="2026-08-24"
                ),
                lead_headers,
            )
        )
        assert reassigned["status"] == "IN_PROGRESS"
        assert reassigned["owner_reference"] == "Client Platform Team"
        assert reassigned["due_date"] == "2026-08-24"

        passed = validate_success(
            api.retest_remediation_item(
                item["id"],
                retest_payload(
                    outcome="PASS", note="The ruleset now blocks the traffic."
                ),
                lead_headers,
            )
        )
        assert passed["status"] == "RETEST_PASSED"
        assert passed["retest_count"] == 2
        assert_same_instant(passed["closed_at"], CLOCK_DEFAULT)

        requirement = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )
        assert_requirement_dimensions(requirement, remediation_status="GAP_REMEDIATED")
        engagement = read_engagement(api, engagement_id, scenario["lead_id"])
        assert engagement["open_gap_count"] == 0
        assert engagement["posture"] == "OPEN"
        assert_total_count(
            api.list_remediation_items(
                lead_headers,
                {"engagement_id": engagement_id, "status": "RETEST_PASSED"},
            ),
            1,
        )
