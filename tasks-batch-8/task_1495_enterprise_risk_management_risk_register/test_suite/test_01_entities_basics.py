"""Corner: entities — creation defaults, FK integrity, required fields,
system-field handling, not-found, listing, immutability shape (§1.9 entities)."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_category, assert_risk, assert_control, assert_assessment,
    create_category, create_risk,
    create_active_control,
    create_category_payload, create_risk_payload, create_control_payload,
    make_risk_manager_headers, make_risk_owner_headers,
    make_control_owner_headers, make_internal_auditor_headers,
    USER_RISK_MANAGER, USER_RISK_OWNER, USER_CONTROL_OWNER, USER_INTERNAL_AUDITOR,
    NON_EXISTENT_UUID,
)


class TestCategoryCreationDefaults:
    def test_weight_factor_defaults_to_one(self):
        """PRD §3.1: "Each category also carries a `weight_factor`, defaulting to 1.0,
        that scales its contribution to board-report heat (§3.8)."

        Design: Corner/entities/category_creation_with_defaults
        """
        res = api_client.create_category(
            {"name": "RootCat"}, make_risk_manager_headers(USER_RISK_MANAGER),
        )
        data = validate_success(res, 201)
        assert data["weight_factor"] == pytest.approx(1.0)

    def test_root_has_null_parent_and_fresh_common_fields(self):
        """PRD §3.1: "the optional `parent_category_id` places the category under an
        existing parent, and omitting it creates a root node."
        PRD §2.5: "Every resource carries an `id` — a unique, server-minted identifier
        formatted as a UUID with no type prefix — and a `created_at` timestamp".
        PRD §3.1: "`current_tolerance_score`... null when no such statement exists".

        Design: Corner/entities/category_creation_with_defaults
        """
        res = api_client.create_category(
            {"name": "RootCat"}, make_risk_manager_headers(USER_RISK_MANAGER),
        )
        created = validate_success(res, 201)
        assert_category(created)
        assert created["parent_category_id"] is None
        assert created["version"] == 1
        assert created["current_tolerance_score"] is None
        # GET re-read yields the same shape
        got = validate_success(
            api_client.get_category(
                created["id"], make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
            ), 200,
        )
        assert got["id"] == created["id"]
        assert got["parent_category_id"] is None
        assert got["version"] == 1


class TestCategoryParentNotFound:
    def test_unknown_parent_category_rejected(self):
        """PRD §2.9: "Foreign-key references supplied in request bodies —
        `category_id`, `control_id`, and `parent_category_id` — must likewise
        reference existing resources, or the request fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/category_parent_not_found_rejected
        """
        res = api_client.create_category(
            {"name": "Orphan", "parent_category_id": NON_EXISTENT_UUID},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestRiskCreationRequiredFields:
    def test_missing_title_rejected(self):
        """PRD §3.2: "A `RiskOwner` opens a register entry by supplying the
        `category_id` that classifies it, a short `title`, the `owner_user_id`
        of the accountable owner".
        PRD §2.8 #3: "required fields present... (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/risk_creation_missing_required_field_rejected
        """
        cat = create_category(name="RC")
        res = api_client.create_risk(
            {"category_id": cat["id"], "owner_user_id": USER_RISK_OWNER},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestRiskSystemFields:
    def test_server_sets_status_draft_version_one(self):
        """PRD §3.2: "A new risk begins in `DRAFT` with `kri_alert` false,
        `reserved_treatment_cents` at 0, and every score field null."

        Design: Corner/entities/risk_system_fields_input_ignored
        """
        cat = create_category(name="SF")
        res = api_client.create_risk(
            create_risk_payload(cat["id"], title="T"),
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        risk = validate_success(res, 201)
        assert risk["status"] == "DRAFT"
        assert risk["version"] == 1

    def test_residual_null_and_zero_budget_reserved(self):
        """PRD §3.2: "A new risk begins in `DRAFT` with `kri_alert` false,
        `reserved_treatment_cents` at 0, and every score field null."
        PRD §3.5: "`available_treatment_cents` is `treatment_budget_cents` minus
        that reservation."

        Design: Corner/entities/risk_system_fields_input_ignored
        """
        cat = create_category(name="SF")
        res = api_client.create_risk(
            create_risk_payload(cat["id"], title="T"),
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        risk = validate_success(res, 201)
        assert risk["residual_score"] is None
        assert risk["residual_band"] is None
        assert risk["reserved_treatment_cents"] == 0
        # treatment_budget_cents defaults to 0 → available == 0
        assert risk["available_treatment_cents"] == 0


class TestControlCreationDefaults:
    def test_max_mapped_risks_defaults_to_10(self):
        """PRD §3.3: "an optional `max_mapped_risks` capacity, an integer of at
        least 1 defaulting to 10. A new control is `PROPOSED` with its
        `mapped_active_count` at 0."

        Design: Corner/entities/control_creation_defaults_max_mapped
        """
        res = api_client.create_control(
            create_control_payload(name="C-default", effectiveness_pct=0.5),
            make_control_owner_headers(USER_CONTROL_OWNER),
        )
        ctl = validate_success(res, 201)
        assert_control(ctl)
        assert ctl["max_mapped_risks"] == 10
        assert ctl["mapped_active_count"] == 0
        assert ctl["status"] == "PROPOSED"


class TestGetRiskNotFound:
    def test_get_unknown_risk_returns_404(self):
        """PRD §2.9: "the first identifier that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/get_risk_not_found_returns_404
        """
        res = api_client.get_risk(
            NON_EXISTENT_UUID, make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestRiskListPaginationEnvelope:
    def test_limit_one_returns_page_meta(self):
        """PRD §2.3: "Paginated list responses carry the fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/risk_list_pagination_envelope
        """
        cat = create_category(name="PG")
        create_risk(cat["id"], title="P1")
        create_risk(cat["id"], title="P2")
        res = api_client.list_risks(
            make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
            params={"category_id": cat["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestAssessmentImmutabilityShape:
    def test_assessment_has_no_version_or_updated_at(self):
        """PRD §2.5: "The two exceptions are the RiskAssessment and the
        KRIObservation. Both are immutable event records: they carry only `id`
        and `created_at`, and both `updated_at` and `version` are absent".

        Design: Corner/entities/assessment_event_immutability_shape
        """
        cat = create_category(name="IM")
        risk = create_risk(cat["id"], title="IR")
        api_client.submit_risk(risk["id"], make_risk_owner_headers(USER_RISK_OWNER))
        v = validate_success(
            api_client.get_risk(
                risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )["version"]
        res = api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 2, "impact": 3,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        assessment = validate_success(res, 201)
        assert_assessment(assessment)

    def test_assessment_list_contains_one_inherent_with_score(self):
        """PRD §3.2: "`inherent_score` is captured for both kinds".
        PRD §3.2: "A risk's assessment history is listed in chronological order."

        Design: Corner/entities/assessment_event_immutability_shape
        """
        cat = create_category(name="IM")
        risk = create_risk(cat["id"], title="IR")
        api_client.submit_risk(risk["id"], make_risk_owner_headers(USER_RISK_OWNER))
        v = validate_success(
            api_client.get_risk(
                risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )["version"]
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 2, "impact": 3,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        res = api_client.list_assessments(
            risk["id"], make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
        )
        data = validate_success(res, 200)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["kind"] == "INHERENT"
        assert data[0]["inherent_score"] == 6
