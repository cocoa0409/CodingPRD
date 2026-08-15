"""Entity creation contracts, common fields, defaults, uniqueness, pagination,
and applicability threshold boundaries (PRD §2.3, §2.4, §3.1, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    DS,
    NON_EXISTENT_UUID,
    PA,
    assert_applicability_evaluation,
    assert_notice,
    assert_retention_policy,
    create_activity_payload,
    create_consumer,
    create_data_element_payload,
    create_data_system_payload,
    create_notice_payload,
    create_purpose_payload,
    create_retention_policy_payload,
    create_state_law_rule,
    get_success_data,
    is_valid_uuid,
    list_evaluations_for_rule,
    run_applicability,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestApplicabilityCountBoundary:
    def test_applicability_count_at_threshold(self, api):
        """PRD §3.8: "applies is true when the resident consumer count reaches at
        least the rule's resident_records_threshold or the revenue share
        percentage reaches at least the rule's revenue_share_threshold_pct.
        margin_to_threshold is the resident consumer count minus the rule's
        resident_records_threshold, and is negative when the count falls below
        the threshold."
        PRD §3.8: "The run iterates over every StateLawRule in created_at
        ascending order, breaking ties by state_code ascending, and produces one
        ApplicabilityEvaluation row per rule."

        Design: Difficulty/boundary_precision_check/applicability_count_at_threshold
        """
        rule_or = create_state_law_rule(
            state_code="OR", law_name="OCPA", resident_records_threshold=2,
            revenue_share_threshold_pct=100.0, request_deadline_days=45,
            extension_days=30)
        rule_wa = create_state_law_rule(
            state_code="WA", law_name="MyHealth", resident_records_threshold=3,
            revenue_share_threshold_pct=100.0, request_deadline_days=45,
            extension_days=30)
        create_consumer(email="or1@x.com", full_name="OR One", state_code="OR")
        create_consumer(email="or2@x.com", full_name="OR Two", state_code="OR")
        create_consumer(email="wa1@x.com", full_name="WA One", state_code="WA")
        create_consumer(email="wa2@x.com", full_name="WA Two", state_code="WA")

        run = run_applicability({"OR": 0, "WA": 0}, total_revenue_cents=1000)
        assert run["evaluation_count"] == 2, "one evaluation row per rule"

        or_evals, _ = list_evaluations_for_rule(rule_or["id"])
        assert len(or_evals) == 1
        or_ev = or_evals[0]
        assert_applicability_evaluation(or_ev)
        assert or_ev["resident_consumer_count"] == 2
        assert or_ev["applies"] is True, "count 2 == threshold 2 applies (inclusive >=)"
        assert or_ev["margin_to_threshold"] == 0

        wa_evals, _ = list_evaluations_for_rule(rule_wa["id"])
        assert len(wa_evals) == 1
        wa_ev = wa_evals[0]
        assert wa_ev["resident_consumer_count"] == 2
        assert wa_ev["applies"] is False, "count 2 == threshold 3 - 1 does not apply"
        assert wa_ev["margin_to_threshold"] == -1

    def test_applicability_below_threshold_with_revenue_shortfall(self, api):
        """PRD §3.8: "applies is true when the resident consumer count reaches at
        least the rule's resident_records_threshold or the revenue share
        percentage reaches at least the rule's revenue_share_threshold_pct."
        PRD §3.8: "margin_to_threshold is the resident consumer count minus the
        rule's resident_records_threshold, and is negative when the count falls
        below the threshold."

        Design: Difficulty/boundary_precision_check/applicability_count_at_threshold
        """
        rule_az = create_state_law_rule(
            state_code="AZ", law_name="AZPA", resident_records_threshold=3,
            revenue_share_threshold_pct=99.0, request_deadline_days=45,
            extension_days=30)
        create_consumer(email="az1@x.com", full_name="AZ One", state_code="AZ")
        create_consumer(email="az2@x.com", full_name="AZ Two", state_code="AZ")

        # 2 < 3 residents AND revenue share 50.0 < 99.0: neither arm applies
        run = run_applicability({"AZ": 500}, total_revenue_cents=1000)
        assert run["evaluation_count"] == 1

        evals, _ = list_evaluations_for_rule(rule_az["id"])
        ev = evals[0]
        assert ev["resident_consumer_count"] == 2
        assert ev["revenue_share_pct"] == pytest.approx(50.0, abs=0.0001)
        assert ev["applies"] is False
        assert ev["margin_to_threshold"] == -1


class TestApplicabilityEvaluationShape:
    def test_applicability_evaluation_immutability(self, api):
        """PRD §2.4: "ApplicabilityEvaluation is the exception: it carries id and
        created_at but no updated_at and no version, because evaluation rows are
        immutable records of a threshold-monitoring run."
        PRD §3.8: "The resulting rows are immutable audit records; per §2.4 they
        carry no updated_at and no version."

        Design: Corner/entities/applicability_evaluation_immutability
        """
        rule = create_state_law_rule(
            state_code="CA", law_name="CCPA", resident_records_threshold=1,
            revenue_share_threshold_pct=100.0, request_deadline_days=45,
            extension_days=45)
        run_applicability({"CA": 0}, total_revenue_cents=1000)

        evals, _ = list_evaluations_for_rule(rule["id"])
        assert len(evals) == 1
        ev = evals[0]
        assert is_valid_uuid(ev["id"])
        assert "created_at" in ev
        assert "version" not in ev, "evaluation rows carry no version"
        assert "updated_at" not in ev, "evaluation rows carry no updated_at"
        assert ev["state_law_rule_id"] == rule["id"]
        assert_applicability_evaluation(ev)


class TestEntityCreationContracts:
    def test_retention_policy_creation_echoes_fields(self, api):
        """PRD §3.1: "A PrivacyAdmin creates retention policies by supplying a
        policy_code, a duration_days count that must be greater than zero, and a
        disposal_action that is one of ANONYMIZE, DELETE, or ARCHIVE."
        PRD §2.4: "Every persisted entity carries a server-minted id that is a
        UUID with no type prefix, a created_at timestamp, and — for all entities
        except ApplicabilityEvaluation — an updated_at timestamp and a
        monotonically increasing integer version."

        Design: Corner/entities/retention_policy_creation_echoes_fields
        """
        policy = validate_success(api.create_retention_policy(
            create_retention_policy_payload(policy_code="RP-2YR", duration_days=730,
                                            disposal_action="ANONYMIZE"), PA),
            expected_status=201)
        assert_retention_policy(policy)
        assert policy["policy_code"] == "RP-2YR"
        assert policy["duration_days"] == 730
        assert policy["disposal_action"] == "ANONYMIZE"
        assert policy["version"] == 1

    def test_system_fields_input_ignored(self, api):
        """PRD §2.4: "Every persisted entity carries a server-minted id that is a
        UUID with no type prefix"
        PRD §2.4: "version starts at its initial value on creation and increments
        by exactly 1 on every mutation"

        Design: Corner/entities/system_fields_input_ignored
        """
        payload = create_data_element_payload(element_key="email")
        payload["id"] = "00000000-0000-0000-0000-000000000000"
        payload["version"] = 99
        element = validate_success(api.create_data_element(payload, DS), expected_status=201)
        assert element["id"] != "00000000-0000-0000-0000-000000000000", (
            "the server mints its own id and ignores the injected one"
        )
        assert is_valid_uuid(element["id"])
        assert element["version"] == 1, "an injected version of 99 is ignored"

    def test_notice_defaults_applied(self, api):
        """PRD §3.2: "A PrivacyAdmin creates a notice by supplying a scope — one
        of WEBSITE, MOBILE_APP, EMPLOYEE, or LOYALTY_PROGRAM — a title, a body,
        an effective_from instant, an optional effective_to instant whose absence
        leaves the window open-ended, and an optional supersedes_notice_id
        declaring which currently published notice this one is intended to
        replace. A new notice is created in DRAFT status, with published_at and
        superseded_by_notice_id both null."

        Design: Corner/entities/notice_defaults_applied
        """
        payload = create_notice_payload(scope="MOBILE_APP", title="app v1")
        del payload["effective_to"]
        notice = validate_success(api.create_notice(payload, PA), expected_status=201)
        assert_notice(notice)
        assert notice["effective_to"] is None, "omitted effective_to leaves the window open-ended"
        assert notice["supersedes_notice_id"] is None
        assert notice["status"] == "DRAFT"
        assert notice["published_at"] is None

    def test_data_element_invalid_enum_rejected(self, api):
        """PRD §3.1: "a category drawn from BASIC_CONTACT, IDENTIFIER, FINANCIAL,
        HEALTH, BIOMETRIC, PRECISE_LOCATION, or MINOR_DATA, and a classification
        drawn from PUBLIC, INTERNAL, CONFIDENTIAL, or RESTRICTED"
        PRD §5: "ERR_INVALID_REQUEST | 400"

        Design: Corner/entities/data_element_invalid_enum_rejected
        """
        resp = api.create_data_element(
            create_data_element_payload(element_key="mystery", category="TOPSECRET",
                                        classification="INTERNAL"), DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_activity_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.4: "A DataSteward documents a processing activity by supplying
        an activity_name, a business_unit, a notice_scope drawn from the same
        four-value enum as notices, a data_element_ids list whose members must
        each resolve to a data element in ACTIVE status, and an optional
        vendor_id referencing the processing vendor."
        PRD §5: "ERR_INVALID_REQUEST | 400"

        Design: Corner/entities/activity_missing_required_field_returns_invalid_request
        """
        resp = api.create_activity(
            {"business_unit": "Finance", "notice_scope": "WEBSITE", "data_element_ids": []},
            DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_element_key_rejected(self, api):
        """PRD §3.1: "Each element carries an element_key that is unique across
        all data elements"
        PRD §2.8: "then uniqueness, buffer, pool, and open-assessment constraints
        (ERR_DUPLICATE_KEY, ERR_TRANSFER_WINDOW_CONFLICT,
        ERR_OPEN_ASSESSMENT_EXISTS, ERR_NO_SYSTEMS_IN_SCOPE,
        ERR_NO_DOCUMENTED_PURPOSE)"

        Design: Corner/validations/duplicate_element_key_rejected
        """
        get_success_data(api.create_data_element(
            create_data_element_payload(element_key="email", category="BASIC_CONTACT",
                                        classification="INTERNAL"), DS))
        resp = api.create_data_element(
            create_data_element_payload(element_key="email", category="FINANCIAL",
                                        classification="CONFIDENTIAL"), DS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


class TestNotFoundAndForeignKeys:
    def test_get_missing_entity_returns_not_found(self, api):
        """PRD §2.8: "Path-id and body-supplied foreign-key existence
        (ERR_NOT_FOUND) comes next, with path identifiers validated
        left-to-right."
        PRD §5: "ERR_NOT_FOUND | 404"

        Design: Corner/entities/get_missing_entity_returns_not_found
        """
        resp = api.get_activity(NON_EXISTENT_UUID, DS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_purpose_bad_retention_fk_not_found(self, api):
        """PRD §2.8: "Path-id and body-supplied foreign-key existence
        (ERR_NOT_FOUND) comes next, with path identifiers validated
        left-to-right."
        PRD §3.4: "a retention_policy_id referencing an existing retention
        policy"

        Design: Corner/entities/purpose_bad_retention_fk_not_found
        """
        element = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="email"), DS))
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        resp = api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="CONTRACT",
                                   retention_policy_id=NON_EXISTENT_UUID), DS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListingPagination:
    def test_data_systems_listing_pagination(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, limit and
        offset. The default limit is 10, with a minimum of 1 and a maximum of
        100; the default offset is 0. Results are returned sorted by created_at
        ascending. The response meta carries the pagination fields limit, offset,
        total_count, and has_more."

        Design: Corner/entities/data_systems_listing_pagination
        """
        for key, region, cats in (("sys-1", "US", ["FINANCIAL"]),
                                  ("sys-2", "EU", ["HEALTH"]),
                                  ("sys-3", "UK", ["BIOMETRIC"])):
            get_success_data(api.create_data_system(
                create_data_system_payload(system_key=key, hosting_region=region,
                                           stores_categories=cats), PA))

        page1, meta1 = validate_paginated(
            api.list_data_systems(DS, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_data_systems(DS, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2
