"""Roadside inspection intake/review, violation recording, and the
cross-entity finalize gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_violation,
    create_accident_payload,
    create_challenge_payload,
    create_inspection_payload,
    create_violation_payload,
    get_inspection,
    get_violation,
    make_carrier,
    make_category,
    make_challenge,
    make_driver,
    make_inspection,
    make_inspection_with_violation,
    make_violation,
    run_cycle,
    setup_finalize_blocked_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestViolationIntake:
    def test_violation_driver_defaults_to_inspection_driver(
        self, api, manager_headers
    ):
        """PRD §3.3: "The cited `driver_id` is optional on input and defaults to
        the inspection's driver; the cited driver must be `ACTIVE`
        (`ERR_DRIVER_NOT_ACTIVE`)."

        Design: Corner/entities/violation_driver_defaults_to_inspection_driver
        """
        carrier = make_carrier(dot_number="DOT-2008")
        category = make_category(category_code="HAZMAT", display_name="Hazmat")
        driver = make_driver(carrier["id"], cdl_number="CDL-2008", full_name="Dan Oka")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2008",
            inspection_level=2, state_code="OR",
        )
        resp = api.create_violation(
            create_violation_payload(
                inspection["id"], category["id"],
                violation_code="397.1", severity_weight=3,
            ),
            manager_headers,
        )
        data = validate_success(resp, 201)
        assert_violation(data)
        assert data["driver_id"] == driver["id"], "driver_id defaults to the inspection's driver"

    def test_immediate_visibility_after_mutation(self, api, manager_headers):
        """PRD §3.3: "Every violation carries a computed
        `time_weight_multiplier`, evaluated against the logical clock at
        creation and refreshed by every measurement cycle." and "The violation's
        `weighted_points` are its `severity_weight` multiplied by that
        multiplier, recomputed whenever the multiplier is refreshed. Recording a
        violation also recomputes the parent inspection's
        `total_weighted_points` — the sum of `weighted_points` over its
        violations in `ACTIVE` or `CHALLENGED` status, with `REMOVED` always
        excluded — and the cited driver's `risk_score`".

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        carrier = make_carrier(dot_number="DOT-2604")
        category = make_category(category_code="UNSAFE_DRIVING", display_name="UD")
        driver = make_driver(carrier["id"], cdl_number="CDL-2604", full_name="Max Uli")
        inspection = make_inspection(carrier["id"], driver["id"], state_code="FL")

        created = validate_success(
            api.create_violation(
                create_violation_payload(
                    inspection["id"], category["id"],
                    violation_code="392.2", severity_weight=8,
                ),
                manager_headers,
            ),
            201,
        )
        assert created["time_weight_multiplier"] == 3
        assert created["weighted_points"] == 24

        fetched = get_violation(created["id"])
        assert fetched["time_weight_multiplier"] == 3
        assert fetched["weighted_points"] == 24
        assert get_inspection(inspection["id"])["total_weighted_points"] == 24

    def test_violation_create_fk_existence_order_returns_404(
        self, api, manager_headers
    ):
        """PRD §2.6: "Path identifiers are resolved first, from left to right;
        then body foreign-key identifiers are resolved in their declared input
        order. Each missing resource yields its own 404:
        `ERR_CARRIER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
        `ERR_CATEGORY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`" — and likewise for
        every other resource.

        Design: Corner/validations/violation_create_fk_existence_order_returns_404
        """
        carrier = make_carrier(dot_number="DOT-2303")
        category = make_category()
        driver = make_driver(carrier["id"], cdl_number="CDL-2303")
        inspection = make_inspection(carrier["id"], driver["id"], state_code="ND")

        bad_inspection = api.create_violation(
            create_violation_payload(NON_EXISTENT_UUID, category["id"], violation_code="X"),
            manager_headers,
        )
        validate_error(bad_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND)

        bad_category = api.create_violation(
            create_violation_payload(inspection["id"], NON_EXISTENT_UUID, violation_code="X"),
            manager_headers,
        )
        validate_error(bad_category, ApiErrorId.ERR_CATEGORY_NOT_FOUND)

    def test_invalid_enum_range_and_duplicate_category_rejected(
        self, api, admin_headers, manager_headers
    ):
        """PRD §3.1: "an `intervention_threshold` (the percentile, from 1 to
        100, at or above which the category is alerted)" and "with reuse of a
        code rejected as `ERR_DUPLICATE_CATEGORY_CODE`".
        PRD §3.3: "a `severity_weight` from 1 to 10 (anything outside that range
        is rejected with `ERR_INVALID_SEVERITY_WEIGHT`)".
        PRD §2.6: shape violations "surface as `ERR_INVALID_REQUEST`, ... (all
        HTTP 400)."

        Design: Corner/validations/invalid_enum_range_and_duplicate_category_rejected
        """
        carrier = make_carrier(dot_number="DOT-2304")
        category = make_category(
            category_code="VEHICLE_MAINTENANCE", display_name="VM",
            intervention_threshold=65, benchmark_measure=10.0,
        )
        driver = make_driver(carrier["id"], cdl_number="CDL-2304")
        inspection = make_inspection(carrier["id"], driver["id"], state_code="ND")

        bad_threshold = api.create_category(
            {
                "category_code": "HAZMAT",
                "display_name": "HM",
                "intervention_threshold": 0,
                "benchmark_measure": 10.0,
            },
            admin_headers,
        )
        validate_error(bad_threshold, ApiErrorId.ERR_INVALID_REQUEST)

        bad_weight = api.create_violation(
            create_violation_payload(
                inspection["id"], category["id"], violation_code="X", severity_weight=11
            ),
            manager_headers,
        )
        validate_error(bad_weight, ApiErrorId.ERR_INVALID_SEVERITY_WEIGHT)

        dup_code = api.create_category(
            {
                "category_code": "VEHICLE_MAINTENANCE",
                "display_name": "VM again",
                "intervention_threshold": 70,
                "benchmark_measure": 8.0,
            },
            admin_headers,
        )
        validate_error(dup_code, ApiErrorId.ERR_DUPLICATE_CATEGORY_CODE)

    def test_future_occurrence_rejected(self, api, manager_headers):
        """PRD §3.3: "the `occurred_at` timestamp, which may not be later than
        the logical clock (`ERR_FUTURE_OCCURRENCE`)".
        PRD §3.7: "the `occurred_at` timestamp (not in the future of the logical
        clock, otherwise `ERR_FUTURE_OCCURRENCE`)".

        Design: Corner/validations/future_occurrence_rejected
        """
        carrier = make_carrier(dot_number="DOT-2305")
        category = make_category(category_code="UNSAFE_DRIVING", display_name="UD")
        driver = make_driver(carrier["id"], cdl_number="CDL-2305")
        inspection = make_inspection(carrier["id"], driver["id"], state_code="WI")

        future_violation = api.create_violation(
            create_violation_payload(
                inspection["id"], category["id"], violation_code="X",
                severity_weight=5, occurred_at="2027-01-01T00:00:00Z",
            ),
            manager_headers,
        )
        validate_error(future_violation, ApiErrorId.ERR_FUTURE_OCCURRENCE)

        future_accident = api.create_accident(
            create_accident_payload(
                carrier["id"], driver["id"], occurred_at="2026-09-01T00:00:00Z"
            ),
            manager_headers,
        )
        validate_error(future_accident, ApiErrorId.ERR_FUTURE_OCCURRENCE)

    def test_driver_carrier_mismatch_rejected(self, api, manager_headers):
        """PRD §3.3: "The named driver must belong to the named carrier,
        otherwise the import is rejected with `ERR_DRIVER_CARRIER_MISMATCH`."

        Design: Corner/validations/driver_carrier_mismatch_rejected
        """
        carrier_a = make_carrier(dot_number="DOT-2311A", legal_name="Mismatch A")
        carrier_b = make_carrier(dot_number="DOT-2311B", legal_name="Mismatch B")
        driver = make_driver(carrier_a["id"], cdl_number="CDL-2311")

        resp = api.create_inspection(
            create_inspection_payload(
                carrier_b["id"], driver["id"], report_number="R-2311", state_code="MI"
            ),
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_CARRIER_MISMATCH)

    def test_duplicate_report_number_scoped_per_carrier(self, api, manager_headers):
        """PRD §3.3: "The `report_number` is unique per carrier
        (`ERR_DUPLICATE_REPORT_NUMBER`)" — the same number under a different
        carrier is a distinct inspection."

        Design: Corner/validations/duplicate_report_number_scoped_per_carrier
        """
        carrier_a = make_carrier(dot_number="DOT-2313A", legal_name="Dup A")
        carrier_b = make_carrier(dot_number="DOT-2313B", legal_name="Dup B")
        driver_a = make_driver(carrier_a["id"], cdl_number="CDL-2313A")
        driver_b = make_driver(carrier_b["id"], cdl_number="CDL-2313B")
        make_inspection(
            carrier_a["id"], driver_a["id"], report_number="R-SHARED", state_code="MO"
        )

        dup = api.create_inspection(
            create_inspection_payload(
                carrier_a["id"], driver_a["id"], report_number="R-SHARED",
                inspection_date="2026-06-01T00:00:00Z", inspection_level=2,
                state_code="MO",
            ),
            manager_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT_NUMBER)

        other_carrier = api.create_inspection(
            create_inspection_payload(
                carrier_b["id"], driver_b["id"], report_number="R-SHARED", state_code="KS"
            ),
            manager_headers,
        )
        validate_success(other_carrier, 201)


class TestInspectionReviewWorkflow:
    def test_inspection_begin_review_twice_rejected(self, api, analyst_headers):
        """PRD §3.3: "beginning review moves `IMPORTED` → `UNDER_REVIEW`, and
        finalizing moves `UNDER_REVIEW` → `FINALIZED`; either action attempted
        from the wrong state is rejected with `ERR_INSPECTION_NOT_REVIEWABLE`."

        Design: Corner/state_machines/inspection_begin_review_twice_rejected
        """
        carrier = make_carrier(dot_number="DOT-2103")
        driver = make_driver(carrier["id"], cdl_number="CDL-2103")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2103", state_code="WY"
        )
        assert inspection["review_status"] == "IMPORTED"

        first = api.begin_review_inspection(inspection["id"], analyst_headers)
        assert validate_success(first, 200)["review_status"] == "UNDER_REVIEW"

        second = api.begin_review_inspection(inspection["id"], analyst_headers)
        validate_error(second, ApiErrorId.ERR_INSPECTION_NOT_REVIEWABLE)

    def test_challenge_on_finalized_inspection_rejected(
        self, api, analyst_headers, manager_headers
    ):
        """PRD §3.3: "`FINALIZED` is terminal: recording a new violation on a
        finalized inspection, or filing a challenge against one of its
        violations, is rejected with `ERR_INSPECTION_FINALIZED`."

        Design: Corner/validations/challenge_on_finalized_inspection_rejected
        """
        carrier, category, driver, inspection, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2321"},
            inspection_overrides={"state_code": "AR"},
        )
        validate_success(api.begin_review_inspection(inspection["id"], analyst_headers), 200)
        validate_success(api.finalize_inspection(inspection["id"], analyst_headers), 200)

        late_violation = api.create_violation(
            create_violation_payload(
                inspection["id"], category["id"], violation_code="396.5", severity_weight=2
            ),
            manager_headers,
        )
        validate_error(late_violation, ApiErrorId.ERR_INSPECTION_FINALIZED)

        late_challenge = api.create_challenge(
            create_challenge_payload(violation["id"], evidence_note="late evidence"),
            analyst_headers,
        )
        validate_error(late_challenge, ApiErrorId.ERR_INSPECTION_FINALIZED)

    def test_challenge_on_removed_violation_rejected(self, api, analyst_headers, admin_headers):
        """PRD §3.4: "Filing requires the violation to be `ACTIVE`
        (`ERR_VIOLATION_NOT_ACTIVE` otherwise)" and "`OVERTURNED` closes the
        challenge and moves the violation `CHALLENGED` → `REMOVED`, which is
        terminal."

        Design: Corner/validations/challenge_on_removed_violation_rejected
        """
        carrier, category, driver, inspection, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2322"},
            inspection_overrides={"state_code": "MS"},
        )
        challenge = make_challenge(
            violation["id"], reason_code="DUPLICATE_REPORT", evidence_note="dup of R-2321"
        )
        validate_success(api.start_review_challenge(challenge["id"], admin_headers), 200)
        validate_success(
            api.decide_challenge(challenge["id"], {"outcome": "OVERTURNED"}, admin_headers),
            200,
        )
        assert get_violation(violation["id"])["status"] == "REMOVED"

        resp = api.create_challenge(
            create_challenge_payload(violation["id"], evidence_note="again"),
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VIOLATION_NOT_ACTIVE)


class TestFinalizeCrossEntityGate:
    def test_finalize_blocked_by_open_challenge(self, api, analyst_headers):
        """PRD §3.3: "Finalization is additionally blocked while any violation
        of the inspection carries an open challenge — one in `SUBMITTED`,
        `UNDER_REVIEW`, or `REMANDED` status — surfacing as
        `ERR_OPEN_CHALLENGES_BLOCK_FINALIZE`."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_challenge
        """
        env = setup_finalize_blocked_case()
        resp = api.finalize_inspection(env["inspection"]["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_CHALLENGES_BLOCK_FINALIZE)
        assert get_inspection(env["inspection"]["id"])["review_status"] == "UNDER_REVIEW"

    def test_finalize_succeeds_once_challenge_upheld(self, api, analyst_headers, admin_headers):
        """PRD §3.3: "Finalization is additionally blocked while any violation
        of the inspection carries an open challenge — one in `SUBMITTED`,
        `UNDER_REVIEW`, or `REMANDED` status — surfacing as
        `ERR_OPEN_CHALLENGES_BLOCK_FINALIZE`."
        PRD §3.4: "`UPHELD` closes the challenge and returns the violation
        `CHALLENGED` → `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_challenge
        """
        env = setup_finalize_blocked_case()
        validate_success(
            api.start_review_challenge(env["challenge"]["id"], admin_headers), 200
        )
        validate_success(
            api.decide_challenge(
                env["challenge"]["id"], {"outcome": "UPHELD"}, admin_headers
            ),
            200,
        )
        finalized = validate_success(
            api.finalize_inspection(env["inspection"]["id"], analyst_headers), 200
        )
        assert finalized["review_status"] == "FINALIZED"
        assert get_violation(env["violation"]["id"])["status"] == "ACTIVE"


class TestReverseFilteredLists:
    def test_fk_reverse_filtered_lists(self, api, analyst_headers):
        """PRD §3.3: "The violation list can be filtered by `inspection_id`,
        `category_id`, `driver_id`, and `status`."
        PRD §3.4: "The challenge list can be filtered by `violation_id` and
        `status`."
        PRD §3.10: "Snapshots are immutable once written and can be listed with
        filters on `carrier_id`, `category_id`, and `cycle_date`."

        Design: Corner/entities/fk_reverse_filtered_lists
        """
        carrier = make_carrier(dot_number="DOT-2009")
        category = make_category(
            category_code="CONTROLLED_SUBSTANCES_ALCOHOL", display_name="CSA"
        )
        driver = make_driver(carrier["id"], cdl_number="CDL-2009")
        i1 = make_inspection(carrier["id"], driver["id"], report_number="R-2009A", state_code="ID")
        i2 = make_inspection(
            carrier["id"], driver["id"], report_number="R-2009B",
            inspection_date="2026-06-01T00:00:00Z", state_code="ID",
        )
        v1 = make_violation(i1["id"], category["id"], violation_code="392.4", severity_weight=3)
        v2 = make_violation(
            i2["id"], category["id"], violation_code="392.5", severity_weight=2,
            occurred_at="2026-06-01T00:00:00Z",
        )
        ch1 = make_challenge(v1["id"], reason_code="OTHER", evidence_note="docs")
        run_cycle(carrier["id"])

        data, _ = validate_paginated(
            api.list_violations(analyst_headers, params={"inspection_id": i1["id"]})
        )
        assert [v["id"] for v in data] == [v1["id"]]
        data, _ = validate_paginated(
            api.list_violations(analyst_headers, params={"inspection_id": i2["id"]})
        )
        assert [v["id"] for v in data] == [v2["id"]]

        data, meta = validate_paginated(
            api.list_challenges(analyst_headers, params={"violation_id": v1["id"]})
        )
        assert [c["id"] for c in data] == [ch1["id"]]
        data, meta = validate_paginated(
            api.list_challenges(analyst_headers, params={"violation_id": v2["id"]})
        )
        assert data == [] and meta["total_count"] == 0

        data, meta = validate_paginated(
            api.list_snapshots(
                analyst_headers,
                params={"carrier_id": carrier["id"], "category_id": category["id"]},
            )
        )
        assert len(data) == 1 and meta["total_count"] == 1
