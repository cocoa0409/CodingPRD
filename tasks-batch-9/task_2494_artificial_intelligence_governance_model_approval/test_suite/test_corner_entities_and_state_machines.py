"""Entity shape, listing and lifecycle-transition compliance tests.

Every test builds its own preconditions from scratch through the PRD's own
endpoints, because the harness restarts the API with an empty database before
each individual test.
"""

from test_helpers import (
    DEFAULT_CLOCK,
    FIRST_PARTY_ASSET,
    FORCED_PROHIBITED_USE_CASE,
    LIMITED_EU_USE_CASE,
    LIMITED_USE_CASE,
    MINIMAL_USE_CASE,
    NON_EXISTENT_UUID,
    THIRD_PARTY_ASSET_CARTWRIGHT,
    THIRD_PARTY_ASSET_NORTHWIND,
    BUSINESS_REVIEWER,
    OFFICER,
    REQUESTER,
    USER_BUSINESS_1,
    USER_REQUESTER_1,
    ApiErrorId,
    assert_classification_snapshot,
    assert_common_fields,
    assert_created_at_ascending,
    assert_debt_equals,
    assert_disclosure_notice,
    assert_gate_order,
    assert_ledger_entry,
    assert_model_asset,
    assert_review_gate,
    classified_use_case,
    classify_payload,
    current_version,
    expected_base_score,
    file_use_case,
    gates_by_type,
    is_iso8601_timestamp,
    issue_conditions,
    list_gates,
    list_ledger,
    list_snapshots,
    minimal_use_case_under_review,
    move_clock,
    pin_clock,
    prohibited_rejected_use_case,
    publish_notice,
    read_use_case,
    register_asset,
    take_up_and_clear,
    take_up_gate,
    use_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The intake fields a client declares and the server must echo back verbatim.
DECLARED_INTAKE_FIELDS = (
    "title",
    "business_unit",
    "description",
    "affects_individuals",
    "decision_autonomy",
    "data_sensitivity",
    "individual_impact",
    "jurisdictions",
    "deployed_headcount_reach",
)


def assert_instant(actual, expected):
    """Assert a stamped instant, comparing exactly to the second in UTC."""
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 instant: {actual!r}"
    assert actual.startswith(expected.rstrip("Z")), (
        f"expected the instant {expected}, got {actual}"
    )


class TestUseCaseIntakeEntity:
    """Intake creation and the defaults a use case carries before classification."""

    def test_intake_creation_persists_every_declared_field(self, api):
        """PRD §3.2: "The filing declares a `title` of 1 to 160 characters, the owning `business_unit` code of 1 to 40 characters, a `description` of 1 to 2000 characters narrating what the system does and how its outputs are used, the boolean `affects_individuals` (true when outputs are applied to identifiable natural persons), the `decision_autonomy` level, the `data_sensitivity` class, the `individual_impact` severity, a `jurisdictions` array, a non-negative `deployed_headcount_reach` giving the number of individuals the deployment can touch per year, and optionally a `predecessor_use_case_id` naming the prior-generation use case this intake supersedes. A first-generation intake omits `predecessor_use_case_id`, which then holds null."

        PRD §3.2: "A newly filed intake lands in status `DRAFT` with `version` 1 and `requester_user_id` set to the filer's `X-User-ID`."

        PRD §4: "Every endpoint that mints a new record responds with HTTP 201 on success"

        Design: Corner/entities/use_case_intake_creation_persists_declared_fields
        """
        pin_clock(api)
        payload = use_case_payload()

        response = api.create_use_case(payload, headers=REQUESTER)
        use_case = validate_success(response, expected_status=201)

        assert response.json()["response_type"] == "object"
        assert_common_fields(use_case)
        assert use_case["version"] == 1
        assert use_case["status"] == "DRAFT"
        assert use_case["requester_user_id"] == USER_REQUESTER_1
        assert use_case["predecessor_use_case_id"] is None
        for field in DECLARED_INTAKE_FIELDS:
            assert use_case[field] == payload[field], (
                f"{field} was not echoed verbatim: "
                f"expected {payload[field]!r}, got {use_case[field]!r}"
            )

    def test_computed_risk_fields_hold_their_defaults_before_classification(self, api):
        """PRD §3.2: "It starts with `classification_stale` false, `classification_cycle_index` 0, `risk_score` null, `risk_tier` null, `required_gate_types` empty, `final_risk_score` null, `final_risk_tier` null, `control_credit` null, `vendor_penalty` null, `open_conditions_count` 0, `cleared_gate_count` 0, `monitoring_posture` `HEALTHY`, `safety_flag` false, `approved_at` null, `approved_by_user_id` null, `approval_expires_at` null, `reassessment_interval_days` null, `reassessment_due_at` null, `reassessment_cycle_index` 0, `reassessment_status` `NOT_SCHEDULED`, `rejection_reason` null, `revoked_at` null and `revocation_reason` null."

        Design: Corner/entities/use_case_computed_risk_fields_default_before_classify
        """
        pin_clock(api)
        created = file_use_case(api, LIMITED_USE_CASE)

        use_case = validate_success(api.get_use_case(created["id"], headers=OFFICER))

        assert use_case["classification_stale"] is False
        assert use_case["classification_cycle_index"] == 0
        assert use_case["risk_score"] is None
        assert use_case["risk_tier"] is None
        assert use_case["required_gate_types"] == []
        assert use_case["final_risk_score"] is None
        assert use_case["final_risk_tier"] is None
        assert use_case["control_credit"] is None
        assert use_case["vendor_penalty"] is None
        assert use_case["open_conditions_count"] == 0
        assert use_case["cleared_gate_count"] == 0
        assert use_case["monitoring_posture"] == "HEALTHY"
        assert use_case["safety_flag"] is False
        assert use_case["approved_at"] is None
        assert use_case["approved_by_user_id"] is None
        assert use_case["approval_expires_at"] is None
        assert use_case["reassessment_interval_days"] is None
        assert use_case["reassessment_due_at"] is None
        assert use_case["reassessment_cycle_index"] == 0
        assert use_case["reassessment_status"] == "NOT_SCHEDULED"
        assert use_case["rejection_reason"] is None
        assert use_case["revoked_at"] is None
        assert use_case["revocation_reason"] is None


class TestModelAssetListing:
    """Pagination, ordering and filtering of the model asset registry."""

    def _three_assets(self, api):
        """Register three assets at three distinct instants, oldest first."""
        pin_clock(api)
        first = register_asset(api, FIRST_PARTY_ASSET)
        move_clock(api, "2026-08-01T01:00:00Z")
        second = register_asset(api, THIRD_PARTY_ASSET_NORTHWIND)
        move_clock(api, "2026-08-01T02:00:00Z")
        third = register_asset(api, THIRD_PARTY_ASSET_CARTWRIGHT)
        return first, second, third

    def test_three_assets_page_as_two_then_one_in_created_at_order(self, api):
        """PRD §2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may be no smaller than 0."

        PRD §2.3: "List results are sorted by `created_at` ascending unless a specific endpoint's description in §4 says otherwise."

        PRD §2.3: "For list responses the `meta` object carries `limit` and `offset` as applied, `total_count` as the number of records matching the filter before pagination, and `has_more`, which is true when records remain beyond the current page."

        Design: Corner/entities/model_asset_listing_pagination_and_created_at_ordering
        """
        first, second, third = self._three_assets(api)

        page_one = api.list_model_assets(headers=OFFICER, limit=2, offset=0)
        rows, meta = validate_paginated(page_one)

        assert page_one.json()["response_type"] == "array"
        assert [row["id"] for row in rows] == [first["id"], second["id"]]
        assert_created_at_ascending(rows)
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True

        rows_two, meta_two = validate_paginated(
            api.list_model_assets(headers=OFFICER, limit=2, offset=2)
        )

        assert [row["id"] for row in rows_two] == [third["id"]]
        assert meta_two["total_count"] == 3
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

    def test_third_party_filter_narrows_the_listing_to_registered_defaults(self, api):
        """PRD §3.1: "A freshly registered asset lands in status `REGISTERED` with `version` 1, `active_binding_count` 0, `enforced_shadow_count` 0 and `vendor_terms_grade` null. Assets may be listed with optional `status`, `provider` and `is_third_party` filters, and read individually"

        Design: Corner/entities/model_asset_listing_pagination_and_created_at_ordering
        """
        _, second, third = self._three_assets(api)

        rows, meta = validate_paginated(
            api.list_model_assets(headers=OFFICER, is_third_party="true")
        )

        assert [row["id"] for row in rows] == [second["id"], third["id"]]
        assert meta["total_count"] == 2
        for row in rows:
            assert_model_asset(
                row,
                status="REGISTERED",
                version=1,
                vendor_terms_grade=None,
                active_binding_count=0,
                enforced_shadow_count=0,
                is_third_party=True,
            )


class TestUseCaseRequestRejections:
    """Reference resolution and request-shape rejections on the intake endpoint."""

    def test_unknown_use_case_id_yields_the_not_found_error_envelope(self, api):
        """PRD §2.8: "On any path of the shape `/use-cases/{id}/...`, an `{id}` that resolves to no `UseCase` row yields `ERR_USE_CASE_NOT_FOUND` (HTTP 404)."

        PRD §2.9: "The `{id}` of a `/use-cases/{id}...` path resolves — `ERR_USE_CASE_NOT_FOUND` (404), on every such path."

        Design: Corner/entities/use_case_unknown_id_not_found
        """
        pin_clock(api)

        response = api.get_use_case(NON_EXISTENT_UUID, headers=OFFICER)
        error = validate_error(response, ApiErrorId.USE_CASE_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""
        assert response.json()["meta"]["api_request_id"].startswith("req_")

    def test_intake_omitting_jurisdictions_is_rejected_as_malformed(self, api):
        """PRD §3.2: "`jurisdictions` is an array whose members are drawn from `EU`, `UK`, `US_CA`, `US_CO` and `US_FED`; the array may be empty but may not contain the same jurisdiction twice."

        PRD §2.9: "Request-body shape — `ERR_INVALID_REQUEST` (400), on every endpoint that accepts a body. This covers a missing required field"

        Design: Corner/entities/use_case_create_missing_jurisdictions_rejected
        """
        pin_clock(api)
        payload = use_case_payload()
        del payload["jurisdictions"]

        validate_error(
            api.create_use_case(payload, headers=REQUESTER),
            ApiErrorId.INVALID_REQUEST,
        )

        rows, meta = validate_paginated(api.list_use_cases(headers=OFFICER))
        assert rows == []
        assert meta["total_count"] == 0

    def test_intake_with_an_undeclared_autonomy_value_is_rejected(self, api):
        """PRD §3.2: "`decision_autonomy` is one of `ADVISORY`, `HUMAN_IN_LOOP`, `HUMAN_ON_LOOP` or `FULLY_AUTOMATED`."

        PRD §2.9: "Request-body shape — `ERR_INVALID_REQUEST` (400), on every endpoint that accepts a body. This covers a missing required field, a wrong type, an enum value outside its declared set"

        Design: Corner/entities/use_case_create_invalid_enum_autonomy_rejected
        """
        pin_clock(api)

        validate_error(
            api.create_use_case(
                use_case_payload(decision_autonomy="SEMI_AUTOMATED"),
                headers=REQUESTER,
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        rows, meta = validate_paginated(api.list_use_cases(headers=OFFICER))
        assert rows == []
        assert meta["total_count"] == 0


class TestClassificationSnapshotEntity:
    """The append-only snapshot each classification leaves behind."""

    def test_snapshot_records_every_point_contribution(self, api):
        """PRD §3.2: "Individual impact contributes nothing for `NONE`, 10 points for `LOW`, 25 points for `MATERIAL` and 40 points for `CONSEQUENTIAL`; these land on the snapshot as `impact_points`. Decision autonomy contributes nothing for `ADVISORY`, 8 points for `HUMAN_IN_LOOP`, 18 points for `HUMAN_ON_LOOP` and 30 points for `FULLY_AUTOMATED`, recorded as `autonomy_points`. Data sensitivity contributes nothing for `PUBLIC`, 6 points for `INTERNAL`, 14 points for `CONFIDENTIAL` and 24 points for `SPECIAL_CATEGORY`, recorded as `sensitivity_points`. Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`. Finally, `jurisdiction_points` is 3 points for each declared jurisdiction that is one of the three high-scrutiny jurisdictions `EU`, `UK` and `US_CO` — a use case declaring all three of those plus `US_FED` therefore earns 9 points, not 12. The five contributions add up to `base_score`."

        PRD §3.2: "At classification time both adjustments are nil by definition — the provisional pass scores the *declaration*, not the controls, so `vendor_penalty` is 0 and `control_credit` is 0, and the snapshot records `cleared_gate_count` and `passed_eval_count` as 0 even in the unusual case where such rows already exist. Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        PRD §3.2: "The `variant` is `INTAKE_PROVISIONAL` for a classification run and `DEPLOYMENT_FINAL` for the one the approval writes."

        PRD §2.4: "a `ClassificationSnapshot` and a `GovernanceLedgerEntry` carry only `id` and `created_at`. Neither has an `updated_at` and neither has a `version`, because neither is ever mutated after it is appended."

        Design: Corner/entities/classification_snapshot_records_every_point_contribution
        """
        pin_clock(api)
        use_case = classified_use_case(api, MINIMAL_USE_CASE)

        snapshots = list_snapshots(api, use_case["id"])

        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert_classification_snapshot(
            snapshot,
            use_case_id=use_case["id"],
            variant="INTAKE_PROVISIONAL",
            cycle_index=1,
            impact_points=10,
            autonomy_points=0,
            sensitivity_points=0,
            reach_points=0,
            jurisdiction_points=0,
            base_score=10,
            vendor_penalty=0,
            control_credit=0,
            cleared_gate_count=0,
            passed_eval_count=0,
            risk_score=10,
            risk_tier="MINIMAL",
            forced_prohibited=False,
        )
        assert snapshot["base_score"] == expected_base_score(MINIMAL_USE_CASE)
        assert_instant(snapshot["computed_at"], DEFAULT_CLOCK)


class TestReviewGateEntity:
    """Gate rows and their scoping to the use case that opened them."""

    def test_gate_listing_is_scoped_to_its_parent_use_case(self, api):
        """PRD §3.2: "Every pre-existing gate on the use case that is not already `VOIDED` is moved to `VOIDED` with `control_debt_index` zeroed to 0.00, and then one fresh `ReviewGate` is created per entry of `required_gate_types`, in that canonical creation order, each starting in status `PENDING`, each with `pinned_risk_tier` frozen to the tier just computed and `pinned_classification_index` frozen to the new `classification_cycle_index`."

        PRD §3.3: "A use case's gates can be listed with optional `status` and `gate_type` filters, and because the creation order is canonical, that listing is index-stable."

        Design: Corner/entities/review_gates_listing_is_scoped_to_its_parent_use_case
        """
        pin_clock(api)
        minimal = classified_use_case(api, MINIMAL_USE_CASE)
        limited = classified_use_case(api, LIMITED_USE_CASE)

        rows, meta = validate_paginated(
            api.list_review_gates(minimal["id"], headers=OFFICER)
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert_review_gate(
            rows[0],
            use_case_id=minimal["id"],
            gate_type="BUSINESS",
            status="PENDING",
            pinned_risk_tier="MINIMAL",
            pinned_classification_index=1,
            open_condition_count=0,
            conditions=[],
            assigned_reviewer_user_id=None,
            cleared_by_user_id=None,
        )
        assert_debt_equals(rows[0]["control_debt_index"], 0.00)

        other_rows, other_meta = validate_paginated(
            api.list_review_gates(limited["id"], headers=OFFICER)
        )

        assert other_meta["total_count"] == 2
        assert_gate_order(other_rows, ["PRIVACY", "BUSINESS"])
        assert all(gate["pinned_risk_tier"] == "LIMITED" for gate in other_rows)
        assert all(gate["use_case_id"] == limited["id"] for gate in other_rows)
        assert rows[0]["id"] not in [gate["id"] for gate in other_rows]


class TestUseCaseLifecycle:
    """The use case state machine: the initial state and the classify transitions."""

    def test_a_new_use_case_is_draft_and_owns_no_children(self, api):
        """PRD §3.2: "A newly filed intake lands in status `DRAFT` with `version` 1 and `requester_user_id` set to the filer's `X-User-ID`."

        PRD §3.2: "one fresh `ReviewGate` is created per entry of `required_gate_types`, in that canonical creation order, each starting in status `PENDING`"

        PRD §3.2: "Every classification leaves behind an immutable **Classification Snapshot** recording, for that `cycle_index` and `variant`, the `use_case_id`, all five contributions"

        Design: Corner/state_machines/use_case_initial_state_is_draft_with_no_children
        """
        pin_clock(api)
        created = file_use_case(api, LIMITED_USE_CASE)

        use_case = read_use_case(api, created["id"])
        assert use_case["status"] == "DRAFT"

        gates, gate_meta = validate_paginated(
            api.list_review_gates(created["id"], headers=OFFICER)
        )
        assert gates == []
        assert gate_meta["total_count"] == 0

        snapshots, snapshot_meta = validate_paginated(
            api.list_classification_snapshots(created["id"], headers=OFFICER)
        )
        assert snapshots == []
        assert snapshot_meta["total_count"] == 0

    def test_classify_moves_draft_to_under_review_with_the_provisional_pair(self, api):
        """PRD §3.2: "Both branches increment `classification_cycle_index` by 1, append a `ClassificationSnapshot` for that cycle, write `risk_score` and `risk_tier` onto the use case, clear `classification_stale` to false, and increment the use case's `version`."

        PRD §3.2: "**On the ordinary branch**, where the prohibited combination does not hold, the use case moves `DRAFT → UNDER_REVIEW`. `required_gate_types` is set from the provisional tier in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`: a `MINIMAL` tier demands only the `BUSINESS` gate, a `LIMITED` tier demands `PRIVACY` and `BUSINESS`, a `HIGH` tier demands all four, and a `PROHIBITED` tier demands none."

        PRD §3.2: "Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        Design: Corner/state_machines/classify_moves_draft_to_under_review_and_opens_tier_gates
        """
        pin_clock(api)
        created = file_use_case(api, LIMITED_USE_CASE)

        use_case = validate_success(
            api.classify_use_case(
                created["id"],
                classify_payload(created["version"]),
                headers=OFFICER,
            )
        )

        assert use_case["status"] == "UNDER_REVIEW"
        assert use_case["risk_score"] == 49
        assert use_case["risk_tier"] == "LIMITED"
        assert use_case["required_gate_types"] == ["PRIVACY", "BUSINESS"]
        assert use_case["classification_cycle_index"] == 1
        assert use_case["classification_stale"] is False
        assert use_case["version"] == 2

    def test_classify_opens_one_pending_gate_per_required_type(self, api):
        """PRD §3.2: "one fresh `ReviewGate` is created per entry of `required_gate_types`, in that canonical creation order, each starting in status `PENDING`, each with `pinned_risk_tier` frozen to the tier just computed and `pinned_classification_index` frozen to the new `classification_cycle_index`. Both `open_conditions_count` and `cleared_gate_count` are recomputed to 0."

        PRD §2.3: "because the review gates a classification creates are created in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`, listing a use case's gates by `created_at` ascending yields that same canonical order and is therefore index-stable across runs."

        Design: Corner/state_machines/classify_moves_draft_to_under_review_and_opens_tier_gates
        """
        pin_clock(api)
        use_case = classified_use_case(api, LIMITED_USE_CASE)

        gates = list_gates(api, use_case["id"])

        assert_gate_order(gates, ["PRIVACY", "BUSINESS"])
        for gate in gates:
            assert_review_gate(
                gate,
                use_case_id=use_case["id"],
                status="PENDING",
                pinned_risk_tier="LIMITED",
                pinned_classification_index=1,
            )
        assert use_case["open_conditions_count"] == 0
        assert use_case["cleared_gate_count"] == 0

    def test_reclassification_voids_the_previous_cycle_and_opens_a_new_set(self, api):
        """PRD §3.2: "Either way the consequences are the same and they are severe by design: `classification_stale` is set to true, every `ReviewGate` on the use case whose status is `PENDING`, `IN_REVIEW`, `CONDITIONS_ISSUED` or `CLEARED` is moved to `VOIDED` with its `control_debt_index` zeroed to 0.00 and its `open_condition_count` zeroed, both `open_conditions_count` and `cleared_gate_count` on the use case are recomputed and therefore become 0, and the use case's `version` increments."

        PRD §3.2: "Every pre-existing gate on the use case that is not already `VOIDED` is moved to `VOIDED` with `control_debt_index` zeroed to 0.00, and then one fresh `ReviewGate` is created per entry of `required_gate_types`, in that canonical creation order, each starting in status `PENDING`, each with `pinned_risk_tier` frozen to the tier just computed and `pinned_classification_index` frozen to the new `classification_cycle_index`."

        PRD §3.2: "Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`."

        Design: Corner/state_machines/reclassification_voids_the_previous_cycle_gates_and_opens_a_new_set
        """
        pin_clock(api)
        use_case = classified_use_case(api, LIMITED_USE_CASE)
        use_case_id = use_case["id"]
        cycle_one_gates = gates_by_type(api, use_case_id)
        cycle_one_ids = {gate["id"] for gate in cycle_one_gates.values()}
        assert len(cycle_one_ids) == 2

        # PRD §3.2 makes intake editable "only from `DRAFT` or from
        # `CHANGES_REQUESTED`", so the revision below has to be issued from one of
        # those two. Classification left the use case in `UNDER_REVIEW`, so a gate
        # issues conditions first: PRD §3.3 says that "the use case bubbles
        # `UNDER_REVIEW → CHANGES_REQUESTED`".
        privacy = cycle_one_gates["PRIVACY"]
        take_up_gate(api, privacy["id"], "PRIVACY")
        issue_conditions(api, privacy["id"], "PRIVACY", 2)
        assert read_use_case(api, use_case_id)["status"] == "CHANGES_REQUESTED"

        revised = validate_success(
            api.update_use_case(
                use_case_id, {"deployed_headcount_reach": 12000}, headers=REQUESTER
            )
        )
        assert revised["status"] == "DRAFT"
        assert revised["classification_stale"] is True
        assert all(gate["status"] == "VOIDED" for gate in list_gates(api, use_case_id))

        reclassified = validate_success(
            api.classify_use_case(
                use_case_id, classify_payload(revised["version"]), headers=OFFICER
            )
        )

        assert reclassified["status"] == "UNDER_REVIEW"
        assert reclassified["classification_cycle_index"] == 2
        assert reclassified["classification_stale"] is False
        assert reclassified["risk_score"] == 51
        assert reclassified["risk_tier"] == "LIMITED"
        assert reclassified["cleared_gate_count"] == 0
        assert reclassified["open_conditions_count"] == 0

        gates = list_gates(api, use_case_id)
        assert len(gates) == 4
        old_gates = [gate for gate in gates if gate["id"] in cycle_one_ids]
        new_gates = [gate for gate in gates if gate["id"] not in cycle_one_ids]
        assert len(old_gates) == 2, "the cycle-1 gates were voided in place, not deleted"
        assert len(new_gates) == 2
        for gate in old_gates:
            assert_review_gate(
                gate, status="VOIDED", pinned_classification_index=1
            )
            assert_debt_equals(gate["control_debt_index"], 0.00)
        for gate in new_gates:
            assert_review_gate(
                gate,
                status="PENDING",
                pinned_risk_tier="LIMITED",
                pinned_classification_index=2,
            )
        assert sorted(gate["gate_type"] for gate in new_gates) == [
            "BUSINESS",
            "PRIVACY",
        ]

        snapshots = list_snapshots(api, use_case_id)
        assert len(snapshots) == 2
        assert [snapshot["cycle_index"] for snapshot in snapshots] == [1, 2]
        assert [snapshot["variant"] for snapshot in snapshots] == [
            "INTAKE_PROVISIONAL",
            "INTAKE_PROVISIONAL",
        ]
        assert [snapshot["risk_score"] for snapshot in snapshots] == [49, 51]
        assert [snapshot["reach_points"] for snapshot in snapshots] == [2, 4]

    def test_classifying_an_under_review_use_case_is_refused(self, api):
        """PRD §3.2: "Classification is a `GovernanceOfficer` action, is permitted only from `DRAFT` — any other status is rejected with `ERR_USE_CASE_NOT_IN_DRAFT` — and requires `expected_use_case_version` to match the use case's current `version`."

        PRD §2.9: "The use case is in `DRAFT` — `ERR_USE_CASE_NOT_IN_DRAFT` (409), on classification."

        Design: Corner/state_machines/classify_twice_invalid_not_in_draft
        """
        pin_clock(api)
        use_case = classified_use_case(api, LIMITED_USE_CASE)
        use_case_id = use_case["id"]
        pinned_version = current_version(api, use_case_id)
        assert pinned_version == 2

        validate_error(
            api.classify_use_case(
                use_case_id, classify_payload(pinned_version), headers=OFFICER
            ),
            ApiErrorId.USE_CASE_NOT_IN_DRAFT,
        )

        after = read_use_case(api, use_case_id)
        assert after["classification_cycle_index"] == 1
        assert after["version"] == 2
        assert len(list_gates(api, use_case_id)) == 2

    def test_forced_prohibited_classification_lands_in_terminal_rejected(self, api):
        """PRD §3.2: "When `affects_individuals` is true **and** `individual_impact` is `CONSEQUENTIAL` **and** `decision_autonomy` is `FULLY_AUTOMATED` **and** `data_sensitivity` is `SPECIAL_CATEGORY`, the combination is prohibited outright: `forced_prohibited` on the snapshot is set to true and `risk_tier` becomes `PROHIBITED` regardless of what the score came to."

        PRD §3.2: "**On the prohibited branch**, where the combination holds, the use case moves `DRAFT → REJECTED`, which is terminal. The snapshot records `forced_prohibited` true and `risk_tier` `PROHIBITED`; `required_gate_types` is set to empty and **no gate rows are created at all**; `rejection_reason` is recorded as the literal string `PROHIBITED_COMBINATION`; and a `GovernanceLedgerEntry` of type `CLASSIFICATION_REJECTED` is appended with `reach_delta` 0 and `debt_delta` 0.00."

        Design: Corner/state_machines/rejected_use_case_is_terminal_and_locked
        """
        chain = prohibited_rejected_use_case(api)

        use_case = read_use_case(api, chain.use_case_id)
        assert use_case["status"] == "REJECTED"
        assert use_case["risk_tier"] == "PROHIBITED"
        assert use_case["risk_score"] == 94
        assert use_case["rejection_reason"] == "PROHIBITED_COMBINATION"
        assert use_case["required_gate_types"] == []
        assert list_gates(api, chain.use_case_id) == []

        snapshots = list_snapshots(api, chain.use_case_id)
        assert len(snapshots) == 1
        assert_classification_snapshot(
            snapshots[0],
            forced_prohibited=True,
            risk_tier="PROHIBITED",
            variant="INTAKE_PROVISIONAL",
        )

        entries = list_ledger(api, chain.use_case_id)
        assert len(entries) == 1
        assert_ledger_entry(
            entries[0],
            entry_type="CLASSIFICATION_REJECTED",
            reach_delta=0,
            use_case_id=chain.use_case_id,
        )
        assert_debt_equals(entries[0]["debt_delta"], 0.00)

    def test_revising_a_rejected_use_case_is_refused_as_terminal(self, api):
        """PRD §2.8: "A record whose parent use case has reached a terminal status is frozen. If the addressed use case — or the parent use case of the addressed child record — is `REJECTED` or `REVOKED`, every mutating request against it is rejected with `ERR_USE_CASE_TERMINAL` (HTTP 409). Reads are unaffected."

        PRD §3.2: "Its lifecycle statuses are `DRAFT`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `READY_FOR_APPROVAL`, `APPROVED`, `UNDER_REASSESSMENT`, `SUSPENDED`, `REJECTED` and `REVOKED`; `REJECTED` and `REVOKED` are terminal."

        Design: Corner/state_machines/rejected_use_case_is_terminal_and_locked
        """
        chain = prohibited_rejected_use_case(api)
        before = read_use_case(api, chain.use_case_id)
        assert before["status"] == "REJECTED"

        validate_error(
            api.update_use_case(
                chain.use_case_id,
                {"decision_autonomy": "HUMAN_IN_LOOP"},
                headers=REQUESTER,
            ),
            ApiErrorId.USE_CASE_TERMINAL,
        )

        after = read_use_case(api, chain.use_case_id)
        assert after["decision_autonomy"] == FORCED_PROHIBITED_USE_CASE[
            "decision_autonomy"
        ]
        assert after["version"] == before["version"]
        assert after["status"] == "REJECTED"


class TestReviewGateLifecycle:
    """Gate transitions and the states each gate action has a transition out of."""

    def test_start_review_on_a_cleared_gate_is_refused(self, api):
        """PRD §3.3: "Taking up a gate moves it `PENDING → IN_REVIEW` or `CONDITIONS_ISSUED → IN_REVIEW`, sets `assigned_reviewer_user_id` to the acting `X-User-ID`, and is permitted only while the parent use case is in `UNDER_REVIEW` or `CHANGES_REQUESTED`."

        PRD §2.9: "The addressed gate is in a status the requested action has a transition out of: take-up needs `PENDING` or `CONDITIONS_ISSUED`, issuing conditions needs `IN_REVIEW`, clearing needs `IN_REVIEW` or `CONDITIONS_ISSUED`, reopening needs `CLEARED` — `ERR_GATE_NOT_IN_REVIEWABLE_STATE` (409), on all four gate actions."

        PRD §3.3: "When, after this clearance, every non-`VOIDED` gate on the use case is `CLEARED` and `cleared_gate_count` equals the number of entries in `required_gate_types`, the use case bubbles `UNDER_REVIEW → READY_FOR_APPROVAL`."

        Design: Corner/state_machines/start_review_on_cleared_gate_invalid
        """
        chain = minimal_use_case_under_review(api)
        gate_id = chain.gate_id("BUSINESS")

        cleared = take_up_and_clear(api, gate_id, "BUSINESS")
        assert_review_gate(
            cleared,
            status="CLEARED",
            gate_type="BUSINESS",
            cleared_by_user_id=USER_BUSINESS_1,
            open_condition_count=0,
        )
        assert_debt_equals(cleared["debt_before_clear"], 0.00)
        assert_instant(cleared["cleared_at"], DEFAULT_CLOCK)
        parent = read_use_case(api, chain.use_case_id)
        assert parent["status"] == "READY_FOR_APPROVAL"
        assert parent["cleared_gate_count"] == 1

        validate_error(
            api.start_gate_review(gate_id, headers=BUSINESS_REVIEWER),
            ApiErrorId.GATE_NOT_IN_REVIEWABLE_STATE,
        )

        after = gates_by_type(api, chain.use_case_id)["BUSINESS"]
        assert after["status"] == "CLEARED"
        assert after["assigned_reviewer_user_id"] == cleared["assigned_reviewer_user_id"]
        assert read_use_case(api, chain.use_case_id)["status"] == "READY_FOR_APPROVAL"


class TestDisclosureNoticeLifecycle:
    """Notice withdrawal and its refusal on an already withdrawn row."""

    def test_withdrawing_a_notice_twice_is_refused(self, api):
        """PRD §3.6: "A published notice lands in status `PUBLISHED`; its only other status is the terminal `WITHDRAWN`."

        PRD §3.6: "Withdrawal moves a notice `PUBLISHED → WITHDRAWN` and stamps `withdrawn_at` with the current logical instant, releasing the jurisdiction slot for a fresh publication. Either a `GovernanceOfficer` or the use case's own `Requester` may withdraw a notice; when the actor is a `Requester`, their `X-User-ID` must match the use case's `requester_user_id`. Withdrawal also happens without any client request as part of the revocation cascade. A notice already `WITHDRAWN` cannot be withdrawn again and the attempt is rejected with `ERR_NOTICE_ALREADY_WITHDRAWN`."

        Design: Corner/state_machines/withdraw_notice_twice_already_withdrawn
        """
        pin_clock(api)
        use_case = file_use_case(api, LIMITED_EU_USE_CASE)
        notice = publish_notice(api, use_case["id"], "EU")
        assert_disclosure_notice(
            notice,
            status="PUBLISHED",
            jurisdiction="EU",
            notice_type="AUTOMATED_DECISION_NOTICE",
        )
        assert notice["withdrawn_at"] is None

        move_clock(api, "2026-08-02T00:00:00Z")
        withdrawn = validate_success(
            api.withdraw_disclosure_notice(notice["id"], headers=REQUESTER)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_instant(withdrawn["withdrawn_at"], "2026-08-02T00:00:00Z")

        validate_error(
            api.withdraw_disclosure_notice(notice["id"], headers=OFFICER),
            ApiErrorId.NOTICE_ALREADY_WITHDRAWN,
        )

        rows, _ = validate_paginated(
            api.list_disclosure_notices(use_case["id"], headers=OFFICER)
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "WITHDRAWN"
        assert rows[0]["withdrawn_at"] == withdrawn["withdrawn_at"]
        assert rows[0]["version"] == withdrawn["version"]
