"""License windowing: same-cell half-open exclusivity, cross-window buffered
holdback, window containment, and validation priority between them."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    assert_license_agreement,
    assert_same_instant,
    create_direct_license,
    create_license_payload,
    list_all_licenses,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


class TestSameCellHalfOpenOverlap:
    def _existing_exclusive(self, api, workspace):
        slot = add_slot(workspace)
        create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        return slot

    def test_adjacent_window_at_existing_end_succeeds(self, api):
        """PRD §2.8: "Adjacent windows — where the candidate's start equals the existing license's end — do not conflict."

        Design: Difficulty/resource_temporal_overlap/same_window_exclusive_half_open_overlap
        """
        workspace = setup_catalog()
        slot = self._existing_exclusive(api, workspace)

        resp = api.create_license_agreement(
            create_license_payload(
                slot["id"], workspace["platform"]["id"],
                license_start="2026-12-01T00:00:00Z",
                license_end="2027-03-01T00:00:00Z",
                exclusive=False, flat_fee_cents=50000,
            ),
            RM,
        )
        adjacent = validate_success(resp, 201)
        assert_license_agreement(adjacent)
        assert adjacent["license_status"] == "EXECUTED", (
            "half-open [start, end) semantics: [09-01,12-01) and [12-01,03-01) "
            "share no instant"
        )

    def test_one_day_overlap_with_exclusive_rejected(self, api):
        """PRD §2.8: "**Same-cell exclusivity overlap** uses half-open semantics: two licenses on the same title, territory, language, and window type conflict when the existing license's `license_start` is strictly before the candidate's `license_end`, and the candidate's `license_start` is strictly before the existing license's `license_end`, and at least one of the two is exclusive."
        PRD §3.4: "it fires `ERR_EXCLUSIVITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/same_window_exclusive_half_open_overlap
        """
        workspace = setup_catalog()
        slot = self._existing_exclusive(api, workspace)

        resp = api.create_license_agreement(
            create_license_payload(
                slot["id"], workspace["platform"]["id"],
                license_start="2026-11-30T00:00:00Z",
                license_end="2027-02-01T00:00:00Z",
                exclusive=False, flat_fee_cents=50000,
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT, 409)


class TestCrossWindowHoldback:
    def _exclusive_svod_license(self, api, workspace):
        slot_sv = add_slot(
            workspace, window_type="SVOD", sellable_to="2028-01-01T00:00:00Z",
        )
        license_agreement = create_direct_license(
            slot_sv["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=300000,
        )
        return slot_sv, license_agreement

    def test_holdback_until_and_closed_end_conflict(self, api):
        """PRD §3.4: "an exclusive `SVOD` license blocks `AVOD` and `FREE_TV` for 30 days"
        PRD §3.4: "When the row is empty the license's `holdback_until` is null; otherwise `holdback_until` is the license's `license_end` plus the row's buffer in days, and any candidate on a blocked window whose interval intersects the closed interval from the upstream `license_start` through `holdback_until` is rejected with `ERR_HOLDBACK_CONFLICT`."
        PRD §2.8: "The holdback rule applies regardless of whether the candidate itself is exclusive."

        Design: Difficulty/resource_temporal_overlap/cross_window_holdback_buffered_closed_interval
        """
        workspace = setup_catalog()
        _slot_sv, upstream = self._exclusive_svod_license(api, workspace)
        assert_same_instant(
            upstream["holdback_until"], "2026-12-31T00:00:00Z", "holdback_until"
        )
        slot_av = add_slot(
            workspace, window_type="AVOD", sellable_to="2028-01-01T00:00:00Z",
        )

        resp = api.create_license_agreement(
            create_license_payload(
                slot_av["id"], workspace["platform"]["id"],
                license_start="2026-12-31T00:00:00Z",
                license_end="2027-03-01T00:00:00Z",
                exclusive=False, flat_fee_cents=40000,
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_HOLDBACK_CONFLICT, 409)

    def test_candidate_after_holdback_until_succeeds(self, api):
        """PRD §2.8: "**Cross-window holdback blocking** uses a closed, buffered interval: an exclusive license on a window with a non-empty holdback row blocks a candidate license on a blocked downstream window whenever the candidate's `license_start` is on or before the upstream license's `holdback_until` and the candidate's `license_end` is on or after the upstream license's `license_start`."

        Design: Difficulty/resource_temporal_overlap/cross_window_holdback_buffered_closed_interval
        """
        workspace = setup_catalog()
        self._exclusive_svod_license(api, workspace)
        slot_av = add_slot(
            workspace, window_type="AVOD", sellable_to="2028-01-01T00:00:00Z",
        )

        resp = api.create_license_agreement(
            create_license_payload(
                slot_av["id"], workspace["platform"]["id"],
                license_start="2027-01-01T00:00:00Z",
                license_end="2027-04-01T00:00:00Z",
                exclusive=False, flat_fee_cents=40000,
            ),
            RM,
        )
        successor = validate_success(resp, 201)
        assert successor["license_status"] == "EXECUTED", (
            "a start after holdback_until (2026-12-31) falls outside the closed "
            "blocked interval"
        )

    def test_holdback_until_derived_with_buffer_constant(self, api):
        """PRD §3.4: "an exclusive `SVOD` license blocks `AVOD` and `FREE_TV` for 30 days; exclusive `AVOD` and `FREE_TV` licenses block nothing cross-window. When the row is empty the license's `holdback_until` is null; otherwise `holdback_until` is the license's `license_end` plus the row's buffer in days"

        Design: Corner/calculations/holdback_until_derived_with_buffer_constant
        """
        workspace = setup_catalog()
        slot_sv = add_slot(
            workspace, window_type="SVOD", sellable_to="2028-01-01T00:00:00Z",
        )
        slot_av = add_slot(
            workspace, window_type="AVOD", sellable_to="2028-01-01T00:00:00Z",
        )

        svod_license = create_direct_license(
            slot_sv["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=300000,
        )
        assert_same_instant(
            svod_license["holdback_until"], "2026-12-31T00:00:00Z",
            "SVOD holdback_until",
        )

        avod_license = create_direct_license(
            slot_av["id"], workspace["platform"]["id"],
            license_start="2027-01-01T00:00:00Z",
            license_end="2027-06-01T00:00:00Z",
            exclusive=True, flat_fee_cents=90000,
        )
        assert avod_license["holdback_until"] is None, (
            "the AVOD matrix row is empty, so the license blocks nothing "
            "cross-window"
        )


class TestWindowContainment:
    def test_license_window_outside_rights_rejected(self, api):
        """PRD §3.3: "Every line's window must be contained in its slot's rights period — `license_start` at or after `sellable_from` and `license_end` at or before `sellable_to` — otherwise `ERR_WINDOW_OUTSIDE_RIGHTS` (422)."
        PRD §3.6: "Window containment, exclusivity, and holdback rules apply exactly as at package offer."

        Design: Corner/validations/license_window_outside_rights_rejected
        """
        workspace = setup_catalog()
        slot = add_slot(workspace, sellable_to="2027-01-01T00:00:00Z")

        resp = api.create_license_agreement(
            create_license_payload(
                slot["id"], workspace["platform"]["id"],
                license_start="2026-09-01T00:00:00Z",
                license_end="2027-06-01T00:00:00Z",
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_RIGHTS, 422)

    def test_temporal_violation_reported_over_conflict(self, api):
        """PRD §2.9: "When multiple validations could reject the same request, the server evaluates them in a fixed priority order. Authentication (headers present, role known) runs first, then authorization and platform ownership, then request-body schema validation (required fields present, types correct, enum values known — including the rule that any window or period end is strictly after its start), then existence of every referenced resource, then state checks, then business-safety rules (embargo, segregation of duties), then business-referential rules (line membership, duplicate line slots), then business-temporal rules (window containment, clock monotonicity), then business-constraint rules (duplicate slot tuples, exclusivity and holdback conflicts, blocked lines, empty acceptance, statement period overlap, delivery completeness), and finally business-fiscal rules (positive revenue, fee-structure consistency)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_license_create
        """
        workspace = setup_catalog()
        slot = add_slot(workspace, sellable_to="2027-01-01T00:00:00Z")
        create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-11-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )

        resp = api.create_license_agreement(
            create_license_payload(
                slot["id"], workspace["platform"]["id"],
                license_start="2026-10-01T00:00:00Z",
                license_end="2027-02-01T00:00:00Z",
                exclusive=True, flat_fee_cents=50000,
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_RIGHTS, 422)

    def test_rejected_candidate_creates_no_license(self, api):
        """PRD §3.3: "Every line's window must be contained in its slot's rights period — `license_start` at or after `sellable_from` and `license_end` at or before `sellable_to` — otherwise `ERR_WINDOW_OUTSIDE_RIGHTS` (422)."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_license_create
        """
        workspace = setup_catalog()
        slot = add_slot(workspace, sellable_to="2027-01-01T00:00:00Z")
        existing = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-11-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )

        resp = api.create_license_agreement(
            create_license_payload(
                slot["id"], workspace["platform"]["id"],
                license_start="2026-10-01T00:00:00Z",
                license_end="2027-02-01T00:00:00Z",
                exclusive=True, flat_fee_cents=50000,
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_RIGHTS, 422)

        licenses = list_all_licenses()
        assert len(licenses) == 1 and licenses[0]["id"] == existing["id"], (
            "the rejected candidate must not create a second license"
        )


class TestFeeStructureValidation:
    def test_flat_fee_license_without_positive_fee_returns_422(self, api):
        """PRD §3.3: "A `FLAT_FEE` line requires `flat_fee_cents` greater than 0 and forbids `revenue_share_pct` or `minimum_guarantee_cents` above 0. A `REVENUE_SHARE` line requires `revenue_share_pct` greater than 0 and at most 100. A `MINIMUM_GUARANTEE` line requires `minimum_guarantee_cents` greater than 0 and `revenue_share_pct` greater than 0 and at most 100. Any inconsistency is rejected with `ERR_FEE_STRUCTURE_INVALID`."

        Design: Corner/validations/flat_fee_license_missing_fee_returns_422
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        payload = create_license_payload(
            slot["id"], workspace["platform"]["id"], flat_fee_cents=0,
        )

        resp = api.create_license_agreement(payload, RM)
        validate_error(resp, ApiErrorId.ERR_FEE_STRUCTURE_INVALID, 422)

    def test_mg_license_without_share_returns_422(self, api):
        """PRD §3.3: "A `MINIMUM_GUARANTEE` line requires `minimum_guarantee_cents` greater than 0 and `revenue_share_pct` greater than 0 and at most 100. Any inconsistency is rejected with `ERR_FEE_STRUCTURE_INVALID`."

        Design: Corner/validations/mg_license_without_share_returns_422
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        payload = create_license_payload(
            slot["id"], workspace["platform"]["id"],
            fee_model="MINIMUM_GUARANTEE",
            minimum_guarantee_cents=50000,
            revenue_share_pct=0,
        )
        payload.pop("flat_fee_cents")  # not a MINIMUM_GUARANTEE field; default 0

        resp = api.create_license_agreement(payload, RM)
        validate_error(resp, ApiErrorId.ERR_FEE_STRUCTURE_INVALID, 422)


class TestDirectDealComputedFields:
    def test_create_license_response_includes_computed_fields(self, api):
        """PRD §3.6: "For a direct deal `package_id` is null and `allocated_fee_cents` equals the input guaranteed fee — `flat_fee_cents` for `FLAT_FEE`, `minimum_guarantee_cents` for `MINIMUM_GUARANTEE`, and 0 for `REVENUE_SHARE`."
        PRD §3.6: "the recoupment ledger fields — `recouped_cents`, `royalty_payable_cents` — start at 0, with `outstanding_recoupment_cents` equal to the outstanding guarantee for a `MINIMUM_GUarantee` license and 0 otherwise. The license's `license_status` begins at `EXECUTED`, with `activated_at` null and `termination_credit_cents` null."
        PRD §3.4: "otherwise `holdback_until` is the license's `license_end` plus the row's buffer in days"

        Design: Corner/consistency_model/create_license_response_includes_computed_fields
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)

        payload = create_license_payload(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True,
            fee_model="MINIMUM_GUARANTEE",
            minimum_guarantee_cents=80000,
            revenue_share_pct=50,
        )
        payload.pop("flat_fee_cents")  # not a FLAT_FEE field; leave it to its default
        resp = api.create_license_agreement(payload, RM)
        license_agreement = validate_success(resp, 201)
        assert_license_agreement(license_agreement)
        assert license_agreement["license_status"] == "EXECUTED"
        assert license_agreement["recouped_cents"] == 0
        assert license_agreement["outstanding_recoupment_cents"] == 80000
        assert license_agreement["allocated_fee_cents"] == 80000, (
            "direct deal: allocated fee equals the input guaranteed fee"
        )
        assert_same_instant(
            license_agreement["holdback_until"], "2026-12-31T00:00:00Z",
            "holdback_until",
        )
        assert license_agreement["package_id"] is None
