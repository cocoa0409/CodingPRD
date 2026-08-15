"""Encroachment discovery, severity derivation, negotiation, and removal."""
import pytest

from test_helpers import (
    DEPARTMENT_DIRECTOR,
    ROW_AGENT,
    TITLE_EXAMINER,
    ApiErrorId,
    add_encroachment,
    api_client,
    assert_encroachment,
    create_active_case,
    create_encroachment_negotiating,
    create_encroachment_payload,
    create_encroachment_removed,
    create_encroachment_removal_agreed,
    get_case,
    get_encroachment,
    get_success_data,
    notify_encroachment,
    validate_error,
    validate_success,
)


class TestEncroachmentStateMachine:

    def test_invalid_transition_on_encroachment_from_discovered_to_negotiating(self):
        """PRD section 2.8: "**Target resource state** — the resource being
        transitioned must currently be in the state the transition starts from,
        else the entity-specific state error such as `ERR_OFFER_NOT_TENDERED`,
        `ERR_ENCROACHMENT_NOT_NEGOTIATING`, `ERR_PERMIT_NOT_PENDING`,
        `ERR_TASK_NOT_IN_PROGRESS`, `ERR_DOCUMENT_NOT_DRAFT`,
        `ERR_REFERRAL_NOT_ACCEPTED`, or `ERR_REFERRAL_NOT_FILED` (409), with
        `ERR_INVALID_STATE` (409) as the generic form."
        PRD section 3.3: "Beginning negotiation moves `NOTIFIED → NEGOTIATING`
        and sets `negotiation_round` to 1."

        Design: Corner/state_machines/invalid_transition_on_encroachment_from_discovered_to_negotiating
        """
        case, doc = create_active_case(case_code="ESM-S06", parcel_id="P-S06")
        enc = add_encroachment(case["id"], doc["id"], encroachment_type="FENCE",
                               encroachment_area_sqft=100, depth_into_easement_ft=1)
        assert enc["status"] == "DISCOVERED"
        resp = api_client.begin_encroachment_negotiation(case["id"], enc["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_waive_only_minor_encroachment(self):
        """PRD section 3.3: "One gentler exit exists for trivial cases: a
        `DepartmentDirector` may waive an encroachment, moving `NEGOTIATING →
        WAIVED`, but only when its `severity_tier` is `MINOR` — anything more
        serious is rejected with `ERR_ONLY_MINOR_WAIVABLE`."

        Design: Corner/state_machines/waive_only_minor_encroachment
        """
        case, doc = create_active_case(case_code="ESM-S07", parcel_id="P-S07")
        # STRUCTURE (base 3), area_ratio 2500/10000 = 0.25 -> multiplier 2.0,
        # depth_ratio 10/50 = 0.2 -> raw 3 * (1 + 0.2 * 2.0) = 4.2 -> SEVERE.
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=2500, depth_into_easement_ft=10,
        )
        assert enc["severity_tier"] == "SEVERE"
        resp = api_client.waive_encroachment(case["id"], enc["id"], DEPARTMENT_DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ONLY_MINOR_WAIVABLE, expected_status=409)

    def test_action_endpoint_confirm_removal_recomputes_count(self):
        """PRD section 3.3: "Confirming the physical removal then moves
        `REMOVAL_AGREED → REMOVED`, permitted only while the case is in
        `ACTIVE_MONITORING` or `RESOLUTION_PENDING`; it decrements
        `open_encroachment_count`, recomputes the pressure score, and when the
        count reaches zero the case automatically returns `RESOLUTION_PENDING →
        ACTIVE_MONITORING`."

        Design: Corner/endpoints/action_endpoint_confirm_removal_recomputes_count
        """
        case, doc = create_active_case(case_code="ESM-E01", parcel_id="P-E01")
        enc = create_encroachment_removal_agreed(case["id"], doc["id"])
        resp = api_client.confirm_encroachment_removal(case["id"], enc["id"], ROW_AGENT)
        data = validate_success(resp)
        assert data["status"] == "REMOVED"
        assert get_case(case["id"])["open_encroachment_count"] == 0


class TestSeverityTier:

    def test_severity_tier_at_area_tier_boundary(self):
        """PRD section 3.3: "The depth contribution is then amplified by an
        area-driven multiplier: when the area ratio is at least 0.25 the
        multiplier is 2.0; when it is at least 0.10 but below 0.25 the
        multiplier is 1.5; below 0.10 the multiplier is 1.0 — depth matters
        more when the footprint is large."
        PRD section 3.3: "The tier is pinned at exact thresholds with at-least
        semantics: a raw score of at least 6.0 is `CRITICAL`, at least 3.5 but
        below 6.0 is `SEVERE`, at least 1.8 but below 3.5 is `MODERATE`, and
        anything below 1.8 is `MINOR`."

        STRUCTURE base 3, area_ratio exactly 0.25 -> multiplier 2.0,
        depth_ratio 10/50 = 0.2 -> raw 3 * (1 + 0.2 * 2.0) = 4.2 -> SEVERE.

        Design: Difficulty/combinatorial_formula/severity_tier_mode_a_nonlinear_interaction
        """
        case, doc = create_active_case(case_code="ESM-003", parcel_id="P-003")
        enc = add_encroachment(
            case["id"], doc["id"], discovered_via="AERIAL_SURVEY",
            encroachment_type="STRUCTURE", encroachment_area_sqft=2500,
            depth_into_easement_ft=10,
        )
        assert_encroachment(enc)
        assert enc["severity_tier"] == "SEVERE", (
            f"raw score 4.2 must pin SEVERE, got {enc['severity_tier']}"
        )

    def test_severity_tier_just_below_area_tier_boundary(self):
        """PRD section 3.3: "The depth contribution is then amplified by an
        area-driven multiplier: when the area ratio is at least 0.25 the
        multiplier is 2.0; when it is at least 0.10 but below 0.25 the
        multiplier is 1.5; below 0.10 the multiplier is 1.0 — depth matters
        more when the footprint is large."
        PRD section 3.3: "The tier is pinned at exact thresholds with at-least
        semantics: a raw score of at least 6.0 is `CRITICAL`, at least 3.5 but
        below 6.0 is `SEVERE`, at least 1.8 but below 3.5 is `MODERATE`, and
        anything below 1.8 is `MINOR`."

        STRUCTURE base 3, area_ratio 2499/10000 = 0.2499 -> multiplier 1.5,
        depth_ratio 0.2 -> raw 3 * (1 + 0.2 * 1.5) = 3.9 -> SEVERE.

        Design: Difficulty/combinatorial_formula/severity_tier_mode_a_nonlinear_interaction
        """
        case, doc = create_active_case(case_code="ESM-003b", parcel_id="P-003b")
        enc = add_encroachment(
            case["id"], doc["id"], discovered_via="AERIAL_SURVEY",
            encroachment_type="STRUCTURE", encroachment_area_sqft=2499,
            depth_into_easement_ft=10,
        )
        assert enc["severity_tier"] == "SEVERE", (
            f"raw score 3.9 must pin SEVERE, got {enc['severity_tier']}"
        )

    def test_severity_provisional_at_creation(self):
        """PRD section 3.3: "The tier is computed provisionally at creation
        against the currently recorded document's width and re-derived whenever
        that document is superseded (§3.2)."

        STRUCTURE base 3 against width_ft 50: raw 3 * (1 + (10/50) * 2.0) = 4.2
        -> SEVERE.

        Design: Difficulty/dual_variant_calc/encroachment_severity_provisional_vs_rederived_on_supersede
        """
        case, doc = create_active_case(case_code="ESM-002", parcel_id="P-002")
        enc = add_encroachment(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=2500, depth_into_easement_ft=10,
        )
        assert enc["severity_tier"] == "SEVERE"

    def test_severity_rederived_when_encroached_document_superseded(self):
        """PRD section 3.2: "When the referenced document is later superseded,
        the encroachment is not deleted or re-pointed — it remains attached to
        the superseded document — but its `severity_tier` is recomputed against
        the superseding document's `width_ft`."
        PRD section 3.2: "Second, if the newly recorded document names a
        `supersedes_document_id`, that earlier document is automatically moved
        `RECORDED → SUPERSEDED` and its rank is freed; a superseded document
        keeps its last rank only until the supersession actually executes."

        Superseding width_ft 20: depth_ratio 10/20 = 0.5, multiplier 2.0 ->
        raw 3 * (1 + 0.5 * 2.0) = 6.0 -> CRITICAL (at-least semantics).

        Design: Difficulty/dual_variant_calc/encroachment_severity_provisional_vs_rederived_on_supersede
        """
        case, doc1 = create_active_case(case_code="ESM-002b", parcel_id="P-002b")
        enc = add_encroachment(
            case["id"], doc1["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=2500, depth_into_easement_ft=10,
        )
        assert enc["severity_tier"] == "SEVERE"

        doc2 = get_success_data(api_client.create_document(
            case["id"],
            {
                "doc_kind": "AMENDMENT",
                "instrument_number": "INST-002-super",
                "recording_date": "2026-08-01T00:00:00Z",
                "grantor_name": "Smith",
                "grantee_name": "CityUtil",
                "gis_polygon_wkt": "POLYGON((0 0, 2 0, 2 1, 0 1, 0 0))",
                "width_ft": 20,
                "supersedes_document_id": doc1["id"],
            },
            TITLE_EXAMINER,
        ))
        record_resp = api_client.record_document(case["id"], doc2["id"], TITLE_EXAMINER)
        validate_success(record_resp)

        enc_after = get_encroachment(case["id"], enc["id"])
        assert enc_after["severity_tier"] == "CRITICAL", (
            f"narrower superseding width must escalate SEVERE -> CRITICAL, "
            f"got {enc_after['severity_tier']}"
        )
        doc1_after = get_success_data(api_client.get_document(case["id"], doc1["id"], TITLE_EXAMINER))
        doc2_after = get_success_data(api_client.get_document(case["id"], doc2["id"], TITLE_EXAMINER))
        assert doc1_after["status"] == "SUPERSEDED"
        assert doc2_after["status"] == "RECORDED"


class TestPressureScore:

    def test_encroachment_pressure_score_accumulates_by_tier(self):
        """PRD section 3.3: "For each encroachment on the case whose status is
        not one of `REMOVED`, `PERMITTED_RETROACTIVELY`, `WAIVED`, or
        `ESCALATED_TO_LEGAL`, the system takes a tier weight — 1 for `MINOR`,
        3 for `MODERATE`, 7 for `SEVERE`, 15 for `CRITICAL` — and multiplies it
        by an age multiplier that compounds with neglect: the multiplier is 1
        plus one-hundredth per whole day of age, where whole days of age is the
        floor of the elapsed time since the encroachment's `created_at`, and
        the age used is capped at 90 days so the multiplier never exceeds 1.9."

        Two fresh VEGETATION encroachments (base 1, area_ratio 0.01 -> mult
        1.0, depth_ratio 0.02 -> raw 1.02 -> MINOR, weight 1, age 0 days ->
        multiplier 1) yield a pressure score of 2.00.

        Design: Corner/calculations/encroachment_pressure_score_accumulates_by_tier
        """
        case, doc = create_active_case(case_code="ESM-CAL3", parcel_id="P-CAL3")
        e1 = add_encroachment(case["id"], doc["id"], discovered_via="AERIAL_SURVEY",
                              encroachment_type="VEGETATION", encroachment_area_sqft=100,
                              depth_into_easement_ft=1)
        e2 = add_encroachment(case["id"], doc["id"], discovered_via="AERIAL_SURVEY",
                              encroachment_type="VEGETATION", encroachment_area_sqft=100,
                              depth_into_easement_ft=1)
        assert e1["severity_tier"] == "MINOR"
        assert e2["severity_tier"] == "MINOR"
        score = get_case(case["id"])["encroachment_pressure_score"]
        assert score == pytest.approx(2.00, abs=1e-9), (
            f"two fresh MINOR encroachments must score 2.00, got {score}"
        )


class TestEncroachmentCountInvariant:

    def test_count_returns_to_zero_after_report_and_remove(self):
        """PRD section 3.3: "A new encroachment starts in `DISCOVERED`, and its
        arrival reconciles the case: `open_encroachment_count` increments,
        `encroachment_pressure_score` is recomputed, and the first open
        encroachment automatically pulls the case `ACTIVE_MONITORING →
        RESOLUTION_PENDING`."
        PRD section 3.3: "Confirming the physical removal then moves
        `REMOVAL_AGREED → REMOVED`, permitted only while the case is in
        `ACTIVE_MONITORING` or `RESOLUTION_PENDING`; it decrements
        `open_encroachment_count`, recomputes the pressure score, and when the
        count reaches zero the case automatically returns `RESOLUTION_PENDING →
        ACTIVE_MONITORING`."

        Design: Difficulty/compensating_invariant/open_encroachment_count_invariant_across_report_and_remove
        """
        case, doc = create_active_case(case_code="ESM-018", parcel_id="P-018")
        assert get_case(case["id"])["open_encroachment_count"] == 0

        enc = add_encroachment(case["id"], doc["id"])
        after_report = get_case(case["id"])
        assert after_report["open_encroachment_count"] == 1
        assert after_report["status"] == "RESOLUTION_PENDING"

        notify_encroachment(case["id"], enc["id"])
        get_success_data(api_client.begin_encroachment_negotiation(case["id"], enc["id"], ROW_AGENT))
        get_success_data(api_client.agree_encroachment_removal(case["id"], enc["id"], ROW_AGENT))
        get_success_data(api_client.confirm_encroachment_removal(case["id"], enc["id"], ROW_AGENT))

        after_removal = get_case(case["id"])
        assert after_removal["open_encroachment_count"] == 0
        assert after_removal["status"] == "ACTIVE_MONITORING"

    def test_case_stays_in_resolution_until_last_encroachment_removed(self):
        """PRD section 3.3: "Confirming the physical removal then moves
        `REMOVAL_AGREED → REMOVED`, permitted only while the case is in
        `ACTIVE_MONITORING` or `RESOLUTION_PENDING`; it decrements
        `open_encroachment_count`, recomputes the pressure score, and when the
        count reaches zero the case automatically returns `RESOLUTION_PENDING →
        ACTIVE_MONITORING`."

        With two open encroachments, removing one leaves the count at one and
        the case in RESOLUTION_PENDING; only the last removal releases it.

        Design: Difficulty/compensating_invariant/open_encroachment_count_invariant_across_report_and_remove
        """
        case, doc = create_active_case(case_code="ESM-018b", parcel_id="P-018b")
        enc1 = add_encroachment(case["id"], doc["id"])
        add_encroachment(case["id"], doc["id"])
        assert get_case(case["id"])["open_encroachment_count"] == 2

        notify_encroachment(case["id"], enc1["id"])
        get_success_data(api_client.begin_encroachment_negotiation(case["id"], enc1["id"], ROW_AGENT))
        get_success_data(api_client.agree_encroachment_removal(case["id"], enc1["id"], ROW_AGENT))
        get_success_data(api_client.confirm_encroachment_removal(case["id"], enc1["id"], ROW_AGENT))

        mid = get_case(case["id"])
        assert mid["open_encroachment_count"] == 1
        assert mid["status"] == "RESOLUTION_PENDING", (
            "count above zero must hold the case in RESOLUTION_PENDING"
        )


class TestEncroachmentAccessControl:

    def test_title_examiner_cannot_create_encroachment(self):
        """PRD section 2.1: "A request whose role is valid but not permitted
        for the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403); the per-endpoint role assignments are listed in Section 4."
        PRD section 4: the "Report a discovered encroachment" endpoint lists
        only RightOfWayAgent as its authorized role.

        Design: Corner/roles/title_examiner_cannot_create_encroachment
        """
        case, doc = create_active_case(case_code="ESM-R02", parcel_id="P-R02")
        resp = api_client.create_encroachment(
            case["id"], create_encroachment_payload(doc["id"]), TITLE_EXAMINER
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_cross_case_reference_rejected(self):
        """PRD section 3.3: "The referenced document must exist, belong to the
        same case (else `ERR_CROSS_CASE_REFERENCE`), and be `RECORDED` (else
        `ERR_DOCUMENT_NOT_RECORDED`)."

        Design: Corner/validations/cross_case_reference_rejected
        """
        case_a, _doc_a = create_active_case(case_code="ESM-V01a", parcel_id="P-V01a")
        _case_b, doc_b = create_active_case(case_code="ESM-V01b", parcel_id="P-V01b")
        resp = api_client.create_encroachment(
            case_a["id"], create_encroachment_payload(doc_b["id"]), ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CASE_REFERENCE, expected_status=409)
