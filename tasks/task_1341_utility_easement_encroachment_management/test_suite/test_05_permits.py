"""Third-party permits: fee tiers, parallel state dimensions, overlap windows,
and approval gates."""
from test_helpers import (
    ROW_AGENT,
    VEGETATION_INSPECTOR,
    ApiErrorId,
    add_encroachment,
    add_offer,
    add_permit,
    api_client,
    approve_permit,
    assert_third_party_permit,
    create_active_case,
    create_approved_permit,
    create_encroachment_negotiating,
    create_permit_payload,
    get_case,
    get_case_version,
    get_encroachment,
    get_permit,
    notify_encroachment,
    pass_permit_inspection,
    validate_error,
    validate_success,
)


class TestPermitFee:

    def test_permit_fee_mode_b_nested_rounding_order(self):
        """PRD section 3.4: "Each permit type carries a base annual rate in
        cents: 25,000 for `DRIVEWAY`, 10,000 for `LANDSCAPING`, 15,000 for
        `FENCE_RETENTION`, 50,000 for `STRUCTURE_RETENTION`, and 75,000 for
        `UTILITY_CROSSING`."
        PRD section 3.4: "The first 500 square feet are charged at 12 cents
        per square foot, rounded half-up to whole cents. Square footage beyond
        500 up to 2,000 is charged at 8 cents per square foot on the excess
        over 500, with the bracket total rounded half-up. Square footage beyond
        2,000 is charged at 5 cents per square foot on the excess over 2,000,
        again with the bracket total rounded half-up."

        STRUCTURE_RETENTION at 2001 sqft: 50000 + (500*12) + (1500*8) + (1*5)
        = 50000 + 6000 + 12000 + 5 = 68005.

        Design: Difficulty/combinatorial_formula/permit_fee_mode_b_nested_rounding_order
        """
        case, doc = create_active_case(case_code="ESM-004", parcel_id="P-004")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=2001,
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        approved = approve_permit(case["id"], permit["id"])
        assert approved["annual_fee_cents"] == 68005, (
            f"per-bracket rounding must yield 68005, got {approved['annual_fee_cents']}"
        )

    def test_permit_approval_succeeds_and_legalizes_encroachment(self):
        """PRD section 3.4: "When the permit names an `encroachment_id`, that
        encroachment must be in `NEGOTIATING` or `COUNTERED` (else
        `ERR_ENCROACHMENT_NOT_NEGOTIATING`), and on approval the encroachment
        automatically becomes `PERMITTED_RETROACTIVELY`, decrementing
        `open_encroachment_count` and recomputing the pressure score."
        PRD section 3.4: "Approval also computes the permit's
        `annual_fee_cents` and recomputes the case's `active_permit_count`."

        Design: Difficulty/combinatorial_formula/permit_fee_mode_b_nested_rounding_order
        """
        case, doc = create_active_case(case_code="ESM-004b", parcel_id="P-004b")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=2001,
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        approved = approve_permit(case["id"], permit["id"])
        assert_third_party_permit(approved)
        assert approved["approval_status"] == "APPROVED"
        assert approved["annual_fee_cents"] == 68005

        enc_after = get_encroachment(case["id"], enc["id"])
        assert enc_after["status"] == "PERMITTED_RETROACTIVELY"
        assert get_case(case["id"])["open_encroachment_count"] == 0

    def test_permit_fee_tiered_boundaries(self):
        """PRD section 3.4: "Each permit type carries a base annual rate in
        cents: 25,000 for `DRIVEWAY`, 10,000 for `LANDSCAPING`, 15,000 for
        `FENCE_RETENTION`, 50,000 for `STRUCTURE_RETENTION`, and 75,000 for
        `UTILITY_CROSSING`."
        PRD section 3.4: "The first 500 square feet are charged at 12 cents
        per square foot, rounded half-up to whole cents."

        LANDSCAPING at exactly 500 sqft: 10000 + 500*12 = 16000.

        Design: Corner/calculations/permit_fee_tiered_boundaries
        """
        case, doc = create_active_case(case_code="ESM-CAL5", parcel_id="P-CAL5")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="VEGETATION",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="LANDSCAPING", requested_area_sqft=500,
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        approved = approve_permit(case["id"], permit["id"])
        assert approved["annual_fee_cents"] == 16000, (
            f"LANDSCAPING at 500 sqft must cost 16000, got {approved['annual_fee_cents']}"
        )


class TestPermitParallelDimensions:

    def test_failed_inspection_after_approval_auto_revokes(self):
        """PRD section 3.4: "A failed inspection is immediately consequential:
        if the permit's `approval_status` is `APPROVED` at that moment, the
        approval is automatically torn down to `REVOKED`."
        PRD section 3.4: "A new permit starts with `approval_status` `PENDING`
        and `field_inspection_status` `NOT_SCHEDULED` — two parallel dimensions
        that then evolve semi-independently."

        Design: Difficulty/non_linear_state_machine/third_party_permit_parallel_dimensions
        """
        case, doc = create_active_case(case_code="ESM-006", parcel_id="P-006")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="DRIVEWAY", requested_area_sqft=400,
            requested_start_date="2026-09-01T00:00:00Z",
            requested_end_date="2027-09-01T00:00:00Z",
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        approve_permit(case["id"], permit["id"])

        fail_resp = api_client.record_permit_inspection(
            case["id"], permit["id"], {"result": "FAILED"}, VEGETATION_INSPECTOR
        )
        validate_success(fail_resp)
        after = get_permit(case["id"], permit["id"])
        assert after["field_inspection_status"] == "FAILED"
        assert after["approval_status"] == "REVOKED", (
            f"failed inspection on an APPROVED permit must auto-revoke, "
            f"got {after['approval_status']}"
        )

    def test_passed_inspection_does_not_approve_permit(self):
        """PRD section 3.4: "A new permit starts with `approval_status`
        `PENDING` and `field_inspection_status` `NOT_SCHEDULED` — two parallel
        dimensions that then evolve semi-independently."
        PRD section 3.4: "Approval is the gated act, moving `approval_status`
        `PENDING → APPROVED`, and it is the second case-sensitive write of
        §2.7: the request must carry `expected_case_version`, rejected with
        `ERR_STALE_CASE_VERSION` (412) when the case has moved on, and success
        increments the case's `version` by 1."

        The inspection dimension reaching PASSED leaves the approval dimension
        at PENDING; only the explicit approve call moves it.

        Design: Difficulty/non_linear_state_machine/third_party_permit_parallel_dimensions
        """
        case, doc = create_active_case(case_code="ESM-006b", parcel_id="P-006b")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="DRIVEWAY", requested_area_sqft=400,
            requested_start_date="2026-09-01T00:00:00Z",
            requested_end_date="2027-09-01T00:00:00Z",
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        mid = get_permit(case["id"], permit["id"])
        assert mid["field_inspection_status"] == "PASSED"
        assert mid["approval_status"] == "PENDING", (
            "a passed inspection must not itself approve the permit"
        )
        approve_permit(case["id"], permit["id"])
        after = get_permit(case["id"], permit["id"])
        assert after["approval_status"] == "APPROVED"
        assert after["field_inspection_status"] == "PASSED"


class TestPermitOverlap:

    def _approved_driveway(self, case, start, end):
        return create_approved_permit(
            case["id"], permit_type="DRIVEWAY", requested_area_sqft=100,
            requested_start_date=start, requested_end_date=end,
            insurance_certificate_on_file=True,
        )

    def test_adjacent_half_open_windows_do_not_overlap(self):
        """PRD section 3.4: "And the requested window must not collide with any
        other `APPROVED` permit on the same case covering the same
        `permit_type` or an intersecting area, under a half-open overlap test
        in which touching intervals — one window's end exactly equal to
        another's start — do not overlap; a `STRUCTURE_RETENTION` permit
        additionally inflates both ends of its own window by a 30-day
        maintenance buffer before the comparison, while all other types compare
        their exact windows."

        [2026-09-01, 2026-10-01) and [2026-10-01, 2026-11-01) touch but do not
        overlap.

        Design: Difficulty/resource_temporal_overlap/permit_overlap_half_open_adjacency_vs_buffer
        """
        case, _doc = create_active_case(case_code="ESM-015", parcel_id="P-015")
        self._approved_driveway(case, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        permit2 = add_permit(
            case["id"], permit_type="DRIVEWAY", requested_area_sqft=100,
            requested_start_date="2026-10-01T00:00:00Z",
            requested_end_date="2026-11-01T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit2["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit2["id"], {"expected_case_version": version}, ROW_AGENT
        )
        data = validate_success(resp)
        assert data["approval_status"] == "APPROVED", (
            "half-open adjacency (end == start) must not count as overlap"
        )

    def test_structure_retention_buffer_creates_overlap(self):
        """PRD section 3.4: "And the requested window must not collide with any
        other `APPROVED` permit on the same case covering the same
        `permit_type` or an intersecting area, under a half-open overlap test
        in which touching intervals — one window's end exactly equal to
        another's start — do not overlap; a `STRUCTURE_RETENTION` permit
        additionally inflates both ends of its own window by a 30-day
        maintenance buffer before the comparison, while all other types compare
        their exact windows. A collision is rejected with `ERR_PERMIT_OVERLAP`."

        STRUCTURE_RETENTION [2026-10-15, 2026-11-15) inflates its own start
        back to 2026-09-15, which collides with the approved DRIVEWAY window
        [2026-09-01, 2026-10-01).

        Design: Difficulty/resource_temporal_overlap/permit_overlap_half_open_adjacency_vs_buffer
        """
        case, _doc = create_active_case(case_code="ESM-015b", parcel_id="P-015b")
        self._approved_driveway(case, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        permit3 = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=100,
            requested_start_date="2026-10-15T00:00:00Z",
            requested_end_date="2026-11-15T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit3["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit3["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_OVERLAP, expected_status=409)

    def test_same_type_overlapping_windows_rejected(self):
        """PRD section 3.4: "And the requested window must not collide with any
        other `APPROVED` permit on the same case covering the same
        `permit_type` or an intersecting area, under a half-open overlap test
        in which touching intervals — one window's end exactly equal to
        another's start — do not overlap; a `STRUCTURE_RETENTION` permit
        additionally inflates both ends of its own window by a 30-day
        maintenance buffer before the comparison, while all other types compare
        their exact windows. A collision is rejected with `ERR_PERMIT_OVERLAP`."

        Two FENCE_RETENTION permits whose windows intersect collide.

        Design: Difficulty/resource_temporal_overlap/permit_overlap_aggregate_capacity_different_semantics
        """
        case, _doc = create_active_case(case_code="ESM-016", parcel_id="P-016")
        create_approved_permit(
            case["id"], permit_type="FENCE_RETENTION", requested_area_sqft=100,
            requested_start_date="2026-09-01T00:00:00Z",
            requested_end_date="2026-12-01T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        permit2 = add_permit(
            case["id"], permit_type="FENCE_RETENTION", requested_area_sqft=100,
            requested_start_date="2026-10-01T00:00:00Z",
            requested_end_date="2026-11-01T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit2["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit2["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_OVERLAP, expected_status=409)

    def test_different_type_overlapping_windows_allowed(self):
        """PRD section 3.4: "And the requested window must not collide with any
        other `APPROVED` permit on the same case covering the same
        `permit_type` or an intersecting area, under a half-open overlap test
        in which touching intervals — one window's end exactly equal to
        another's start — do not overlap; a `STRUCTURE_RETENTION` permit
        additionally inflates both ends of its own window by a 30-day
        maintenance buffer before the comparison, while all other types compare
        their exact windows. A collision is rejected with `ERR_PERMIT_OVERLAP`."

        Permits carry no spatial footprint beyond an area figure, so the only
        computable collision between these two windows is the shared
        permit_type; a LANDSCAPING window overlapping a FENCE_RETENTION window
        does not collide.

        Design: Difficulty/resource_temporal_overlap/permit_overlap_aggregate_capacity_different_semantics
        """
        case, _doc = create_active_case(case_code="ESM-016b", parcel_id="P-016b")
        create_approved_permit(
            case["id"], permit_type="FENCE_RETENTION", requested_area_sqft=100,
            requested_start_date="2026-09-01T00:00:00Z",
            requested_end_date="2026-12-01T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        permit3 = add_permit(
            case["id"], permit_type="LANDSCAPING", requested_area_sqft=100,
            requested_start_date="2026-10-01T00:00:00Z",
            requested_end_date="2026-11-01T00:00:00Z",
            insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit3["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit3["id"], {"expected_case_version": version}, ROW_AGENT
        )
        data = validate_success(resp)
        assert data["approval_status"] == "APPROVED"


class TestPermitApprovalGates:

    def test_permit_invalid_date_range(self):
        """PRD section 3.4: "The window must be a valid half-open interval with
        the end strictly after the start, else `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/permit_invalid_date_range
        """
        case, _doc = create_active_case(case_code="ESM-V02", parcel_id="P-V02")
        payload = create_permit_payload(
            permit_type="DRIVEWAY", requested_area_sqft=100,
            requested_start_date="2026-12-01T00:00:00Z",
            requested_end_date="2026-09-01T00:00:00Z",
        )
        resp = api_client.create_permit(case["id"], payload, ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)

    def test_err_insurance_required_on_permit_approve(self):
        """PRD section 3.4: "Insurance must be on file (else
        `ERR_INSURANCE_REQUIRED`)."

        Design: Corner/errors/err_insurance_required_on_permit_approve
        """
        case, doc = create_active_case(case_code="ESM-ER2", parcel_id="P-ER2")
        enc = create_encroachment_negotiating(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        permit = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=100,
            encroachment_id=enc["id"], insurance_certificate_on_file=False,
        )
        pass_permit_inspection(case["id"], permit["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_REQUIRED, expected_status=409)

    def test_approve_rejected_when_encroachment_discovered(self):
        """PRD section 3.4: "When the permit names an `encroachment_id`, that
        encroachment must be in `NEGOTIATING` or `COUNTERED` (else
        `ERR_ENCROACHMENT_NOT_NEGOTIATING`), and on approval the encroachment
        automatically becomes `PERMITTED_RETROACTIVELY`, decrementing
        `open_encroachment_count` and recomputing the pressure score."

        The linked encroachment here is still DISCOVERED.

        Design: Difficulty/cross_entity_state_dependency/permit_approve_requires_encroachment_negotiating
        """
        case, doc = create_active_case(case_code="ESM-014", parcel_id="P-014")
        enc = add_encroachment(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        assert enc["status"] == "DISCOVERED"
        permit = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=100,
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_ENCROACHMENT_NOT_NEGOTIATING, expected_status=409)
        assert get_permit(case["id"], permit["id"])["approval_status"] == "PENDING"

    def test_approve_rejected_when_encroachment_only_notified(self):
        """PRD section 3.4: "When the permit names an `encroachment_id`, that
        encroachment must be in `NEGOTIATING` or `COUNTERED` (else
        `ERR_ENCROACHMENT_NOT_NEGOTIATING`), and on approval the encroachment
        automatically becomes `PERMITTED_RETROACTIVELY`, decrementing
        `open_encroachment_count` and recomputing the pressure score."

        The linked encroachment here has been NOTIFIED but negotiation has not
        begun, so it is likewise outside the NEGOTIATING/COUNTERED gate.

        Design: Difficulty/cross_entity_state_dependency/permit_approve_requires_encroachment_negotiating
        """
        case, doc = create_active_case(case_code="ESM-014b", parcel_id="P-014b")
        enc = add_encroachment(
            case["id"], doc["id"], encroachment_type="STRUCTURE",
            encroachment_area_sqft=100, depth_into_easement_ft=1,
        )
        notify_encroachment(case["id"], enc["id"])
        permit = add_permit(
            case["id"], permit_type="STRUCTURE_RETENTION", requested_area_sqft=100,
            encroachment_id=enc["id"], insurance_certificate_on_file=True,
        )
        pass_permit_inspection(case["id"], permit["id"])
        version = get_case_version(case["id"])
        resp = api_client.approve_permit(
            case["id"], permit["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_ENCROACHMENT_NOT_NEGOTIATING, expected_status=409)
        assert get_permit(case["id"], permit["id"])["approval_status"] == "PENDING"


class TestActivePermitCount:

    def test_derived_field_active_permit_count_reconciled(self):
        """PRD section 2.4: "Several of its fields are computed rather than
        written directly: `compensation_committed_cents` aggregates the
        acquisition offers that currently encumber the budget;
        `compensation_balance_cents` is always the `acquisition_budget_cents`
        minus `compensation_committed_cents`; `open_encroachment_count` counts
        the encroachments that have not reached a terminal state;
        `encroachment_pressure_score` aggregates the severity and age of
        unresolved encroachments; `title_cleared` reflects the latest title
        search together with the recorded-document inventory; and
        `active_permit_count` counts permits whose `approval_status` is
        `APPROVED` and whose `field_inspection_status` is anything other than
        `FAILED`."
        PRD section 3.4: "A failed inspection is immediately consequential: if
        the permit's `approval_status` is `APPROVED` at that moment, the
        approval is automatically torn down to `REVOKED`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_active_permit_count_reconciled
        """
        case, _doc = create_active_case(case_code="ESM-X05", parcel_id="P-X05")
        permit = create_approved_permit(
            case["id"], permit_type="DRIVEWAY", requested_area_sqft=100,
            insurance_certificate_on_file=True,
        )
        after_approve = get_case(case["id"])
        assert after_approve["active_permit_count"] == 1

        fail_resp = api_client.record_permit_inspection(
            case["id"], permit["id"], {"result": "FAILED"}, VEGETATION_INSPECTOR
        )
        validate_success(fail_resp)
        permit_after = get_permit(case["id"], permit["id"])
        assert permit_after["approval_status"] == "REVOKED"
        assert get_case(case["id"])["active_permit_count"] == 0
