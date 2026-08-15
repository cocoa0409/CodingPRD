"""Listings, response envelopes, vendor assessment lifecycle, and immediate
consistency (PRD §2.2, §2.3, §2.4, §2.5, §3.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_metric,
    assert_instant_equal,
    complete_engagement,
    create_approved_model_with_metric,
    create_change_request,
    create_draft_report,
    create_model,
    create_vendor_assessment,
    get_model,
    open_engagement,
    parse_instant,
    set_clock,
    create_finding,
    create_model_with_approved_doc,
    submit_documentation,
    decide_documentation,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


class TestListings:
    def test_model_list_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
        defaulting to 0. The `meta` block of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/model_list_pagination_envelope
        """
        for name in ("Page M1", "Page M2", "Page M3"):
            create_model(name=name, declared_complexity="LOW", usage_scope="SINGLE_DESK",
                         exposure_amount=100)
        page1, meta1 = validate_paginated(api.list_models(OFFICER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_models(OFFICER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

    def test_models_list_filters_by_risk_tier(self, api):
        """PRD §3.1: "The model list endpoint supports optional filtering by `status`,
        `risk_tier`, `owner_user_id`, and `replaced_by_model_id`."

        Design: Corner/endpoints/models_list_filters_by_risk_tier
        """
        create_model(name="FiltT1 M", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        create_model(name="FiltT3 M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        rows, _ = validate_paginated(api.list_models(OFFICER, params={"risk_tier": "TIER_1"}))
        assert len(rows) == 1 and rows[0]["name"] == "FiltT1 M"
        all_rows, _ = validate_paginated(api.list_models(OFFICER))
        assert len(all_rows) == 2

    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.1: "Every child record later created under the model — documentation,
        change requests, engagements, findings, metrics, vendor assessments — carries a
        system-assigned `model_id` pointing back to it."
        PRD §4: GET /mrm/models/{id}/documentations, .../change-requests,
        .../validation-engagements, .../monitoring-metrics, and
        .../vendor-assessments each list the model's child records.

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        model, doc = create_model_with_approved_doc(name="FKReach M", business_unit="Trading",
                                                    declared_complexity="LOW",
                                                    usage_scope="SINGLE_DESK", exposure_amount=100,
                                                    is_vendor_model=True)
        create_change_request(model["id"], "MINOR", model["version"], description="fk reach")
        eng = open_engagement(model["id"])
        complete_engagement(eng["id"], outcome="EFFECTIVE", assessed_complexity="LOW")
        create_vendor_assessment(model["id"], completeness_score=80, valid_months=12)
        approved = validate_success(api.approve_model(model["id"], OFFICER))
        assert approved["status"] == "APPROVED_FOR_USE"
        add_metric(model["id"], "psi", "ABOVE_IS_BREACH", 0.25)

        docs, _ = validate_paginated(api.list_documentations(model["id"], OFFICER))
        assert len(docs) == 1 and docs[0]["status"] == "APPROVED"
        crs, _ = validate_paginated(api.list_change_requests(model["id"], OFFICER))
        assert len(crs) == 1 and crs[0]["status"] == "SUBMITTED"
        engs, _ = validate_paginated(api.list_engagements(model["id"], OFFICER))
        assert len(engs) == 1 and engs[0]["status"] == "COMPLETED"
        metrics, _ = validate_paginated(api.list_metrics(model["id"], OFFICER))
        assert len(metrics) == 1 and metrics[0]["status"] == "ACTIVE"
        assessments, _ = validate_paginated(api.list_vendor_assessments(model["id"], OFFICER))
        assert len(assessments) == 1 and assessments[0]["status"] == "CURRENT"


class TestExistenceAndEnvelope:
    def test_model_get_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "Any unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/model_get_unknown_id_returns_not_found
        """
        create_model(name="Exists M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        err = validate_error(api.get_model(NON_EXISTENT_UUID, OFFICER), ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_nested_child_creation_under_wrong_parent_returns_not_found(self, api):
        """PRD §2.8: "Path parameters — the model `id` first, then any nested child
        identifier such as `docId`, `crId`, or `fid` — are resolved strictly left to
        right; identifiers referenced in the request body, such as
        `replacement_model_id` or `metric_id`, are resolved at their own existence
        step. Any unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/nested_child_creation_under_wrong_parent_returns_not_found
        """
        err = validate_error(
            api.create_finding(NON_EXISTENT_UUID, {"severity": "LOW", "title": "orphan"}, OFFICER),
            ApiErrorId.ERR_NOT_FOUND,
        )
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_error_response_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_model(NON_EXISTENT_UUID, OFFICER)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"
        body = resp.json()
        assert body["meta"].get("api_request_id"), "meta.api_request_id present"
        assert body["meta"].get("api_request_timestamp"), "meta.api_request_timestamp present"
        assert body["response_type"] == "error"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


class TestVendorAssessmentLifecycle:
    def test_vendor_assessment_valid_until_computed(self, api):
        """PRD §3.5: "At recording, `assessed_at` is stamped with the logical-clock
        now, `valid_until` is computed as `assessed_at` plus `valid_months` months, and
        the assessment starts in `CURRENT`."

        Recorded at the 2026-08-01 default clock with valid_months 6 -> valid_until
        2027-02-01.

        Design: Corner/entities/vendor_assessment_valid_until_computed
        """
        model = create_model(name="Vendor V", business_unit="Trading", declared_complexity="LOW",
                             usage_scope="SINGLE_DESK", exposure_amount=100, is_vendor_model=True)
        assessment = validate_success(
            api.create_vendor_assessment(model["id"], {"completeness_score": 75, "valid_months": 6},
                                         OFFICER),
            expected_status=201,
        )
        assert assessment["status"] == "CURRENT"
        assert_instant_equal(assessment["assessed_at"], "2026-08-01T00:00:00Z", "assessed_at")
        assert_instant_equal(assessment["valid_until"], "2027-02-01T00:00:00Z", "valid_until")

    def test_assessment_on_non_vendor_model_rejected(self, api):
        """PRD §3.5: "Assessments exist only for models registered with
        `is_vendor_model` true; recording one for any other model fails with
        `ERR_NOT_A_VENDOR_MODEL`."

        Design: Corner/validations/assessment_on_non_vendor_model_rejected
        """
        model = create_model(name="NotVend M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100, is_vendor_model=False)
        err = validate_error(
            api.create_vendor_assessment(model["id"], {"completeness_score": 90, "valid_months": 12},
                                         OFFICER),
            ApiErrorId.ERR_NOT_A_VENDOR_MODEL,
        )
        assert err["error_id"] == "ERR_NOT_A_VENDOR_MODEL"
        assessments, _ = validate_paginated(api.list_vendor_assessments(model["id"], OFFICER))
        assert assessments == []

    def test_vendor_assessment_expiry_boundary(self, api):
        """PRD §3.5: "The clock sweep flips an assessment to the terminal `EXPIRED`
        once the logical clock reads strictly after `valid_until`; at exactly
        `valid_until` the assessment is still current."

        valid_months 1 from 2026-08-01 -> valid_until 2026-09-01.

        Design: Corner/cross_cutting_complexity_layers/vendor_assessment_expiry_boundary
        """
        model = create_model(name="VExp V", business_unit="Trading", declared_complexity="LOW",
                             usage_scope="SINGLE_DESK", exposure_amount=100, is_vendor_model=True)
        create_vendor_assessment(model["id"], completeness_score=90, valid_months=1)

        def status_now():
            rows, _ = validate_paginated(api.list_vendor_assessments(model["id"], OFFICER))
            return rows[0]["status"]

        set_clock("2026-09-01T00:00:00Z")
        assert status_now() == "CURRENT", "equality remains CURRENT"
        set_clock("2026-09-01T00:00:01Z")
        assert status_now() == "EXPIRED", "one second past valid_until"


class TestImmediateConsistency:
    def test_immediate_consistency_visible_in_same_response(self, api):
        """PRD §3.6: "Every finding receives its `remediation_due_at` once, at
        creation."
        PRD §3.6: "Raising a finding increments the model's `open_findings_count` —
        defined as the number of findings on the model whose status is `OPEN`,
        `OVERDUE`, or `ESCALATED` — by one and recomputes the model's `risk_score` and
        `risk_tier`, since the findings penalty of §3.1 has grown."

        The create response itself carries the computed deadline (HIGH on TIER_3:
        round(30 * 2.0) = 60 days -> 2026-09-30), and the immediately-following read
        shows the bumped count and recomputed score (30 + 5 = 35).

        Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
        """
        model = create_model(name="ImmCon M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = validate_success(
            api.create_finding(model["id"], {"severity": "HIGH", "title": "immediate"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(finding["remediation_due_at"], "2026-09-30T00:00:00Z",
                             "computed inline in the create response")
        assert finding["status"] == "OPEN"
        data = validate_success(api.get_model(model["id"], OFFICER))
        assert data["open_findings_count"] == 1
        assert data["risk_score"] == 35
        assert data["risk_tier"] == "TIER_3"

    def test_updated_at_refreshed_on_mutation(self, api):
        """PRD §2.4: "Resources are stamped with `created_at` at creation and
        `updated_at` on every mutation, both ISO 8601 UTC timestamps with three
        fractional digits."
        PRD §3.6: "Closure stamps `closed_at`, decrements `open_findings_count` by one,
        recomputes `risk_score` and `risk_tier` with the penalty reduced, and refreshes
        `validation_due_at` if the tier changed."

        Design: Corner/consistency_model/updated_at_refreshed_on_mutation
        """
        model = create_model(name="UpdAt M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="LOW", title="bump")
        validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        after = validate_success(api.get_model(model["id"], OFFICER))
        assert parse_instant(after["updated_at"]) >= parse_instant(model["updated_at"]), (
            "updated_at refreshed by the cascaded recompute on finding close"
        )
        assert after["open_findings_count"] == 0
