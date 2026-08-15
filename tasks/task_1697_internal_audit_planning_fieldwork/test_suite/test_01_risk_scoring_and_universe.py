"""Risk scoring variants, entity universe lifecycle, and OCC on entity version.

Covers PRD §3.1 (audit universe + risk assessment cycle) and §2.6 (OCC).
"""
from test_helpers import (
    ApiErrorId,
    assert_auditable_entity,
    assert_risk_assessment,
    create_auditable_entity_payload,
    create_auditor,
    create_engagement_payload,
    create_entity,
    create_plan,
    create_risk_assessment_payload,
    get_plan,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_manager_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRiskScoreVariants:
    """Dual-variant scoring selected by the entity's scrutiny flag (PRD §3.1)."""

    def test_weighted_variant_scores_72_for_l3_i4(self, api, admin_headers):
        """PRD §3.1: "Under `WEIGHTED`, the `inherent_risk_score` is eight times
        the `likelihood` plus twelve times the `impact` — so a likelihood of 3
        and an impact of 4 produce a score of 72."
        PRD §3.1: "the entity's `current_inherent_risk_score` is set to this
        assessment's score and its `current_risk_tier` is recomputed from that
        score — `CRITICAL` when the score is at least 85, `HIGH` for 70 through
        84, `MODERATE` for 40 through 69, and `LOW` below 40, with each lower
        boundary inclusive."

        Design: Difficulty/dual_variant_calc/risk_score_weighted_vs_conservative_variants
        """
        set_clock()
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        ent = create_entity(name="Entity A", regulatory_scrutiny=False)
        mgr_h = make_manager_headers(mgr["id"])

        ra = get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], likelihood=3, impact=4,
            ),
            mgr_h,
        ))
        assert ra["scoring_variant"] == "WEIGHTED"
        assert ra["inherent_risk_score"] == 72

        finalized = get_success_data(api.finalize_risk_assessment(ra["id"], mgr_h))
        assert finalized["status"] == "FINALIZED"
        assert finalized["inherent_risk_score"] == 72

        entity_after = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))
        assert entity_after["current_inherent_risk_score"] == 72
        assert entity_after["current_risk_tier"] == "HIGH"

    def test_conservative_variant_scores_80_for_identical_inputs(self, api):
        """PRD §3.1: "Under `CONSERVATIVE`, the score is twenty times the larger
        of `likelihood` and `impact`, a worst-axis-dominance rule under which
        the same inputs produce 80 rather than 72."
        PRD §3.1: "The server selects the `scoring_variant` by reading the
        entity's `regulatory_scrutiny` flag at that moment: `true` selects
        `CONSERVATIVE`; `false` selects `WEIGHTED`."

        Design: Difficulty/dual_variant_calc/risk_score_weighted_vs_conservative_variants
        """
        set_clock()
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        ent = create_entity(name="Entity B", regulatory_scrutiny=True)
        mgr_h = make_manager_headers(mgr["id"])

        ra = get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], likelihood=3, impact=4,
            ),
            mgr_h,
        ))
        assert ra["scoring_variant"] == "CONSERVATIVE"
        assert ra["inherent_risk_score"] == 80
        assert ra["inherent_risk_score"] != 72, (
            "Identical (L=3, I=4) inputs must diverge across the two variants"
        )

        get_success_data(api.finalize_risk_assessment(ra["id"], mgr_h))
        entity_after = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))
        assert entity_after["current_inherent_risk_score"] == 80
        assert entity_after["current_risk_tier"] == "HIGH"


class TestEntityCreationDefaults:
    def test_entity_creation_defaults_and_system_fields(self, api, admin_headers):
        """PRD §3.1: "A new entity starts with `status` equal to `ACTIVE`,
        `retired_at` null, and — until a risk assessment is finalized for it —
        a null `current_inherent_risk_score` and null `current_risk_tier`."
        PRD §3.1: "`regulatory_scrutiny`, a boolean defaulting to `false`"

        Design: Corner/entities/entity_creation_defaults_and_system_fields
        """
        resp = api.create_auditable_entity(
            create_auditable_entity_payload(name="Core Payments", business_owner="CFO"),
            admin_headers,
        )
        created = validate_success(resp, expected_status=201)
        assert_auditable_entity(created)
        assert created["status"] == "ACTIVE"
        assert created["regulatory_scrutiny"] is False
        assert created["version"] == 1
        assert created["retired_at"] is None
        assert created["current_inherent_risk_score"] is None
        assert created["current_risk_tier"] is None
        assert is_valid_uuid(created["id"])

        fetched = validate_success(api.get_auditable_entity(created["id"], admin_headers))
        assert fetched["id"] == created["id"]
        assert fetched["status"] == "ACTIVE"

    def test_entity_create_missing_required_name_returns_invalid_request(self, api, admin_headers):
        """PRD §2.7 stage 5: "required fields are present, types are valid, enum
        values are in range, and no unknown or read-only fields were supplied;
        violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "An `AuditAdmin` registers an **AuditableEntity** — a business
        unit, process, or site — by supplying its `name` and the accountable
        executive as `business_owner`."

        Design: Corner/entities/entity_create_missing_required_name_returns_invalid_request
        """
        resp = api.create_auditable_entity({"business_owner": "CFO"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_entity_create_with_system_field_rejected(self, api, admin_headers):
        """PRD §2.7 stage 5: "required fields are present, types are valid, enum
        values are in range, and no unknown or read-only fields were supplied;
        violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.4: "`version` (integer): a system-managed integer that starts at
        1 when the resource is created and increments by one on every mutation."

        Design: Corner/entities/entity_create_with_system_field_rejected
        """
        resp = api.create_auditable_entity(
            {"name": "X", "business_owner": "Y", "status": "RETIRED"}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestRiskAssessmentGuards:
    def test_risk_assessment_score_out_of_range_rejected(self, api):
        """PRD §3.1: "supplying the entity reference `auditable_entity_id`
        together with `likelihood` and `impact`, each an integer from 1 to 5
        inclusive; a value outside that range is rejected with
        `ERR_SCORE_OUT_OF_RANGE`."

        Design: Corner/entities/risk_assessment_score_out_of_range_rejected
        """
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        resp = api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], likelihood=6, impact=3,
            ),
            make_manager_headers(mgr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE, expected_status=422)

    def test_risk_assessment_uniqueness_and_finalize_state(self, api):
        """PRD §3.1: "if a `DRAFT` assessment already exists for the same
        `auditable_entity_id` and `fiscal_year`, creation fails with
        `ERR_RISK_ASSESSMENT_DRAFT_EXISTS`; if a `FINALIZED` assessment already
        exists for that pair, creation fails with
        `ERR_RISK_ASSESSMENT_ALREADY_FINALIZED`."
        PRD §3.1: "Finalizing it — an `AuditManager` action — requires the
        assessment to be in `DRAFT` (else `ERR_RISK_ASSESSMENT_INVALID_STATE`)"

        Design: Corner/state_machines/risk_assessment_uniqueness_and_finalize_state
        """
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])

        ra1 = get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(ent["id"], ent["version"], likelihood=3, impact=3),
            mgr_h,
        ))

        # Duplicate DRAFT for the same (entity, fiscal_year) is rejected.
        ent_v2 = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))["version"]
        dup = api.create_risk_assessment(
            create_risk_assessment_payload(ent["id"], ent_v2, likelihood=4, impact=4),
            mgr_h,
        )
        validate_error(dup, ApiErrorId.ERR_RISK_ASSESSMENT_DRAFT_EXISTS, expected_status=409)

        # Re-finalize after finalization is an invalid-state error.
        finalized = get_success_data(api.finalize_risk_assessment(ra1["id"], mgr_h))
        assert finalized["status"] == "FINALIZED"
        assert is_iso8601_timestamp(finalized["finalized_at"])
        refinalize = api.finalize_risk_assessment(ra1["id"], mgr_h)
        validate_error(refinalize, ApiErrorId.ERR_RISK_ASSESSMENT_INVALID_STATE, expected_status=409)

        # A same-year create after finalization hits the FINALIZED guard.
        ent_v3 = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))["version"]
        after = api.create_risk_assessment(
            create_risk_assessment_payload(ent["id"], ent_v3, likelihood=5, impact=5),
            mgr_h,
        )
        validate_error(after, ApiErrorId.ERR_RISK_ASSESSMENT_ALREADY_FINALIZED, expected_status=409)

        entity_after = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))
        assert entity_after["current_inherent_risk_score"] == 60
        assert entity_after["current_risk_tier"] == "MODERATE"


class TestOccOnEntityVersion:
    def test_occ_stale_entity_version_rejected(self, api, admin_headers):
        """PRD §2.6: "Creating a risk assessment requires the request to carry
        `expected_auditable_entity_version` holding the client last-observed
        `version` of the target auditable entity; if that value does not equal
        the entity's current `version` — because, for instance, another
        assessment was created or finalized against the entity after the client
        read it — the request is rejected with `ERR_STALE_ENTITY_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_entity_version_rejected
        """
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])

        # First creation succeeds against version 1 and bumps the entity to 2.
        get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], fiscal_year=2026, likelihood=3, impact=3,
            ),
            mgr_h,
        ))
        entity_now = get_success_data(api.get_auditable_entity(ent["id"], mgr_h))
        assert entity_now["version"] == 2

        # A second create carrying the stale observed version is rejected.
        stale = api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], fiscal_year=2027, likelihood=4, impact=4,
            ),
            mgr_h,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_ENTITY_VERSION, expected_status=412)

        data, meta = validate_paginated(
            api.list_risk_assessments(mgr_h, params={"auditable_entity_id": ent["id"]})
        )
        assert meta["total_count"] == 1, "No second assessment may be persisted"

    def test_priority_occ_beats_uniqueness(self, api):
        """PRD §2.7: "Every request passes through a fixed validation pipeline,
        and the ordering between stages is contractual: when several violations
        are present, the error surfaced is the one belonging to the earliest
        stage."
        PRD §2.7 stage 6: "**Optimistic concurrency** — the OCC comparisons of
        §2.6, yielding `ERR_STALE_ENTITY_VERSION` or `ERR_STALE_PLAN_VERSION`."

        Design: Corner/validations/priority_occ_beats_uniqueness
        """
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])

        # Draft for FY2026 created against version 1; entity advances to 2.
        get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(ent["id"], ent["version"], likelihood=3, impact=3),
            mgr_h,
        ))

        # This request is BOTH stale-versioned and a same-year duplicate; the
        # OCC stage (earlier in the pipeline) must surface first.
        resp = api.create_risk_assessment(
            create_risk_assessment_payload(
                ent["id"], ent["version"], fiscal_year=2026, likelihood=4, impact=4,
            ),
            mgr_h,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ENTITY_VERSION, expected_status=412)


class TestRetiredEntityArchival:
    def test_retired_entity_archival_semantics(self, api, admin_headers):
        """PRD §3.1: "A `RETIRED` entity remains fully readable but rejects new
        risk assessments and new engagements with `ERR_AUDITABLE_ENTITY_RETIRED`."
        PRD §3.1: "the transition from `ACTIVE` to `RETIRED` requires the entity
        to currently be `ACTIVE` — otherwise `ERR_AUDITABLE_ENTITY_INVALID_STATE`
        — and requires that no engagement of the entity is in `PLANNED`,
        `SCOPED`, `FIELDWORK`, or `REPORTING` status; open work blocks
        retirement with `ERR_ENTITY_HAS_OPEN_ENGAGEMENTS`."

        Design: Corner/state_machines/retired_entity_archival_semantics
        """
        set_clock()
        ent_a = create_entity(name="EA")
        ent_b = create_entity(name="EB")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        # Entity B holds a PLANNED engagement, blocking its retirement.
        eng_b = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent_b["id"], plan["version"], title="G"),
            mgr_h,
        ))

        retired = get_success_data(api.retire_auditable_entity(ent_a["id"], admin_headers))
        assert retired["status"] == "RETIRED"
        assert is_iso8601_timestamp(retired["retired_at"])

        # Archival read: the retired entity remains GET-readable.
        fetched = get_success_data(api.get_auditable_entity(ent_a["id"], admin_headers))
        assert fetched["status"] == "RETIRED"
        assert_auditable_entity(fetched)

        # Re-retire is an invalid-state error.
        rere = api.retire_auditable_entity(ent_a["id"], admin_headers)
        validate_error(rere, ApiErrorId.ERR_AUDITABLE_ENTITY_INVALID_STATE, expected_status=409)

        # New risk assessment against a RETIRED entity is rejected.
        ra = api.create_risk_assessment(
            create_risk_assessment_payload(
                ent_a["id"], retired["version"], likelihood=3, impact=3,
            ),
            mgr_h,
        )
        validate_error(ra, ApiErrorId.ERR_AUDITABLE_ENTITY_RETIRED, expected_status=409)

        # New engagement against a RETIRED entity is rejected (fresh plan
        # version supplied so OCC passes and the referential gate fires).
        plan_v2 = get_plan(plan["id"])["version"]
        eng = api.create_engagement(
            create_engagement_payload(
                plan["id"], ent_a["id"], plan_v2, title="G2",
                start_date="2026-06-01T00:00:00Z", end_date="2026-06-30T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(eng, ApiErrorId.ERR_AUDITABLE_ENTITY_RETIRED, expected_status=409)

        # Entity B cannot be retired while it has an open engagement.
        blocked = api.retire_auditable_entity(ent_b["id"], admin_headers)
        validate_error(blocked, ApiErrorId.ERR_ENTITY_HAS_OPEN_ENGAGEMENTS, expected_status=409)
