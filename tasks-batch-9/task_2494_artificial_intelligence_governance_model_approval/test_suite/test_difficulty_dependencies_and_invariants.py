"""Cross-entity state dependencies, exclusive-window temporal overlap, and the two
compensating conservation invariants the governance ledger exists to make checkable.

Every test drives the API through the PRD's own endpoints from an empty database.
"""

import pytest

from test_helpers import (
    ASSET_NOT_APPROVED_STATUS_ON_BINDING_CREATION,
    DEFAULT_CLOCK,
    EVAL_WINDOWS,
    LEGAL_REVIEWER,
    LIMITED_USE_CASE,
    OFFICER,
    REQUESTER,
    SECURITY_REVIEWER,
    ApiErrorId,
    approve_use_case,
    approve_asset,
    approved_design,
    assert_debt_equals,
    assert_debt_total_matches_gates,
    assert_iso_instant,
    assert_ledger_debt_balance,
    assert_ledger_reach_balance,
    assert_metric_value,
    assert_reach_conserved,
    clear_all_gates,
    classified_use_case,
    create_binding,
    disclosure_notice_payload,
    entry_types,
    exactly_seventy_high_use_case,
    expected_gate_debt,
    gates_by_type,
    high_tier_with_legal_conditions,
    limited_use_case_with_binding,
    list_bindings,
    list_evaluations,
    list_gates,
    list_ledger,
    list_notices,
    model_binding_payload,
    pin_clock,
    read_asset,
    read_summary,
    read_use_case,
    register_asset,
    report_incident,
    revoke_use_case,
    shared_asset_two_bound_use_cases,
    take_up_gate,
    test_evaluation_payload as evaluation_schedule_payload,
    use_case_with_september_eu_notice_window,
    validate_error,
    validate_success,
)


# PRD §3.4 requires the completion body to carry the metric that the frozen profile's
# `required_metric_name` designates — `adversarial_pass_rate` for a red-team run and
# `worst_group_parity_ratio` for a bias run — so these calls name that field directly.


def _schedule_evaluation(api, use_case_id, binding_id, eval_type, start, end):
    """Reserve one exclusive test window on the bound asset, naming its use case."""
    return validate_success(
        api.create_test_evaluation(
            evaluation_schedule_payload(
                binding_id, eval_type, start, end, use_case_id=use_case_id
            ),
            headers=SECURITY_REVIEWER,
        ),
        expected_status=201,
    )


def _limited_approval(api):
    """A LIMITED-tier use case (reach 5000) carried to APPROVED on one passed bias run."""
    chain = limited_use_case_with_binding(api)
    start, end = EVAL_WINDOWS["BIAS"]
    scheduled = _schedule_evaluation(
        api, chain.use_case_id, chain.binding_id, "BIAS", start, end
    )
    chain.evaluations["BIAS"] = validate_success(
        api.complete_test_evaluation(
            scheduled["id"],
            {"worst_group_parity_ratio": 0.7500, "sample_size": 400},
            headers=SECURITY_REVIEWER,
        )
    )
    assert chain.evaluations["BIAS"]["status"] == "PASSED"
    chain.design = approved_design(api, chain.use_case_id)
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = approve_use_case(api, chain.use_case_id)
    return chain


class TestSecurityGateClearDependsOnEvaluationRowStatus:
    """The SECURITY gate's clearance turns on the status of a TestEvaluation row."""

    def test_clear_is_refused_while_no_redteam_evaluation_exists(self, api):
        """PRD §3.3: "A `SECURITY` gate requires a `TestEvaluation` on the use case whose `eval_type` is `SECURITY_REDTEAM` and whose status is `PASSED`; without one the clearance fails with `ERR_REQUIRED_EVALUATION_MISSING`. Note carefully that the gate does **not** consult the tier's required-evaluation list — only the red-team run."

        Design: Difficulty/cross_entity_state_dependency/security_gate_clear_depends_on_evaluation_row_status
        """
        chain = exactly_seventy_high_use_case(api)
        assert chain.use_case["risk_tier"] == "HIGH"
        gate = chain.gates["SECURITY"]
        # The take-up is itself a write, so the "nothing was written" check below
        # is anchored on the row as it stood immediately before the refused clear.
        in_review = take_up_gate(api, gate["id"], "SECURITY")
        assert in_review["status"] == "IN_REVIEW"
        assert list_evaluations(api, use_case_id=chain.use_case_id) == []

        response = api.clear_gate(
            gate["id"],
            {"decision_note": "attempting to clear with no red-team evidence"},
            headers=SECURITY_REVIEWER,
        )
        validate_error(response, ApiErrorId.REQUIRED_EVALUATION_MISSING)

        gates = gates_by_type(api, chain.use_case_id)
        assert gates["SECURITY"]["status"] == "IN_REVIEW"
        assert gates["SECURITY"]["cleared_by_user_id"] is None
        assert gates["SECURITY"]["version"] == in_review["version"]
        for gate_type in ("LEGAL", "PRIVACY", "BUSINESS"):
            assert gates[gate_type]["status"] == "PENDING"
        assert read_use_case(api, chain.use_case_id)["cleared_gate_count"] == 0

    def test_clear_is_refused_when_the_redteam_run_exists_but_failed(self, api):
        """PRD §2.9: "On gate clearance the tier's evaluation list is not consulted at all; the only rule is that clearing a gate whose `gate_type` is `SECURITY` requires a `PASSED` `SECURITY_REDTEAM` evaluation on the use case, while clearing a `PRIVACY` or `BUSINESS` gate requires no evaluation evidence whatsoever." PRD §3.4: "`required_metric_threshold` is drawn from the tier: at `HIGH` the thresholds are 0.80 for `BIAS`, 0.90 for `ROBUSTNESS`, 0.95 for `HALLUCINATION` and 0.95 for `SECURITY_REDTEAM`; at `LIMITED` they are 0.70, 0.80, 0.85 and 0.85 respectively; at `MINIMAL` they are 0.60, 0.70, 0.75 and 0.75; and at `PROHIBITED` every threshold is 1.00." PRD §3.4: "The run lands in `PASSED` when `observed_metric_value` is at least `required_metric_threshold` **and** `sample_size` is at least `required_sample_size`; a value exactly equal to the threshold passes, because both comparisons are inclusive. If either comparison fails, the run lands in `FAILED`." PRD §3.4: "A `FAILED` run also sets `observed_metric_value` and `completed_at`, but if its `eval_type` is `BIAS` it raises the use case's `safety_flag` to true, and — whatever its type — if the use case is currently in `UNDER_REVIEW` or `READY_FOR_APPROVAL` it pushes the use case to `CHANGES_REQUESTED`."

        Design: Difficulty/cross_entity_state_dependency/security_gate_clear_depends_on_evaluation_row_status
        """
        chain = exactly_seventy_high_use_case(api)
        gate = chain.gates["SECURITY"]
        take_up_gate(api, gate["id"], "SECURITY")

        scheduled = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "SECURITY_REDTEAM",
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
        )
        assert scheduled["required_metric_name"] == "adversarial_pass_rate"
        assert scheduled["required_metric_threshold"] == pytest.approx(0.95, abs=0.01)
        assert scheduled["required_sample_size"] == 1000

        completed = validate_success(
            api.complete_test_evaluation(
                scheduled["id"],
                {"adversarial_pass_rate": 0.9000, "sample_size": 1000},
                headers=SECURITY_REVIEWER,
            )
        )
        assert completed["status"] == "FAILED"
        assert_metric_value(completed["observed_metric_value"], 0.9000)

        use_case = read_use_case(api, chain.use_case_id)
        assert use_case["status"] == "CHANGES_REQUESTED"
        assert use_case["safety_flag"] is False

        response = api.clear_gate(
            gate["id"],
            {"decision_note": "attempting to clear on a failed red-team"},
            headers=SECURITY_REVIEWER,
        )
        validate_error(response, ApiErrorId.REQUIRED_EVALUATION_MISSING)

        gates = gates_by_type(api, chain.use_case_id)
        assert gates["SECURITY"]["status"] == "IN_REVIEW"
        assert gates["SECURITY"]["cleared_at"] is None
        assert read_use_case(api, chain.use_case_id)["cleared_gate_count"] == 0

    def test_clear_succeeds_once_a_passed_redteam_row_exists(self, api):
        """PRD §3.3: "A `SECURITY` gate requires a `TestEvaluation` on the use case whose `eval_type` is `SECURITY_REDTEAM` and whose status is `PASSED`; without one the clearance fails with `ERR_REQUIRED_EVALUATION_MISSING`." PRD §3.3: "Once those pass, the clearance captures `debt_before_clear` from the gate's current `control_debt_index` (this is what makes the compensating reopen exact), zeroes `control_debt_index` to 0.00 and `open_condition_count` to 0, records `cleared_by_user_id` and `cleared_at`, and appends a `GovernanceLedgerEntry` of type `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the captured `debt_before_clear`."

        Design: Difficulty/cross_entity_state_dependency/security_gate_clear_depends_on_evaluation_row_status
        """
        chain = exactly_seventy_high_use_case(api)
        gate = chain.gates["SECURITY"]
        take_up_gate(api, gate["id"], "SECURITY")

        failing = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "SECURITY_REDTEAM",
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
        )
        validate_success(
            api.complete_test_evaluation(
                failing["id"],
                {"adversarial_pass_rate": 0.9000, "sample_size": 1000},
                headers=SECURITY_REVIEWER,
            )
        )
        blocked = api.clear_gate(
            gate["id"], {"decision_note": "still no passing run"}, headers=SECURITY_REVIEWER
        )
        validate_error(blocked, ApiErrorId.REQUIRED_EVALUATION_MISSING)
        gate_before = gates_by_type(api, chain.use_case_id)["SECURITY"]

        passing = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "SECURITY_REDTEAM",
            "2026-08-03T00:00:00Z",
            "2026-08-04T00:00:00Z",
        )
        completed = validate_success(
            api.complete_test_evaluation(
                passing["id"],
                {"adversarial_pass_rate": 0.9600, "sample_size": 1000},
                headers=SECURITY_REVIEWER,
            )
        )
        assert completed["status"] == "PASSED"
        assert_metric_value(completed["observed_metric_value"], 0.9600)

        # Nothing about the gate moved between the refused clear and this one.
        assert gate_before["status"] == "IN_REVIEW"
        cleared = validate_success(
            api.clear_gate(
                gate["id"],
                {"decision_note": "red-team passed at 0.96"},
                headers=SECURITY_REVIEWER,
            )
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_user_id"] == "usr_sec_1"
        assert_debt_equals(cleared["debt_before_clear"], 0.00)
        assert_debt_equals(cleared["control_debt_index"], 0.00)
        assert read_use_case(api, chain.use_case_id)["cleared_gate_count"] == 1


class TestBindingCreationDependsOnModelAssetStatus:
    """The create is refused for the state of the asset row its body names."""

    def test_create_is_refused_while_the_named_asset_is_still_registered(self, api):
        """PRD §3.4: "The referenced asset must be `APPROVED_FOR_USE`, otherwise the creation is rejected with `ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE`, and the use case's `risk_tier` must not be `PROHIBITED`, otherwise it is rejected with `ERR_PROHIBITED_USE_CASE`." PRD §2.9: "The referenced asset has status `APPROVED_FOR_USE` — `ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE` (422), on binding creation."

        Design: Difficulty/cross_entity_state_dependency/binding_creation_depends_on_model_asset_status
        """
        pin_clock(api)
        asset = register_asset(api)
        assert asset["status"] == "REGISTERED"
        assert asset["version"] == 1
        use_case = classified_use_case(api, LIMITED_USE_CASE)
        assert use_case["risk_tier"] == "LIMITED"

        response = api.create_model_binding(
            use_case["id"],
            model_binding_payload(asset["id"], use_case["version"]),
            headers=OFFICER,
        )
        validate_error(
            response,
            ApiErrorId.MODEL_ASSET_NOT_APPROVED_FOR_USE,
            expected_status=ASSET_NOT_APPROVED_STATUS_ON_BINDING_CREATION,
        )
        # The asset id resolved on both sides of the check, so this is a business
        # referential refusal rather than an existence failure.
        assert response.json()["data"]["error_id"] != ApiErrorId.MODEL_ASSET_NOT_FOUND.value

    def test_refused_create_leaves_no_binding_and_no_version_movement(self, api):
        """PRD §2.4: "Most records additionally carry `updated_at`, refreshed to the logical clock's current reading on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations a cascade performs on the row rather than mutations a client requested directly." PRD §3.4: "Every prior binding of the use case whose status is `PINNED` or `STALE` is moved to `RETIRED` with `superseded_reason` set to `SUPERSEDED_BY_NEW_BINDING`; for each such retirement the corresponding asset's `active_binding_count` is decremented by 1; every `TestEvaluation` still in `PLANNED` on a retired binding is moved to `VOIDED`; the newly bound asset's `active_binding_count` is incremented by 1; and the use case's `version` increments." PRD §2.10: "`active_binding_count` on a `ModelAsset` is the number of bindings on that asset whose status is `PINNED` or `STALE`."

        Design: Difficulty/cross_entity_state_dependency/binding_creation_depends_on_model_asset_status
        """
        pin_clock(api)
        asset = register_asset(api)
        use_case = classified_use_case(api, LIMITED_USE_CASE)
        version_before = use_case["version"]

        response = api.create_model_binding(
            use_case["id"],
            model_binding_payload(asset["id"], version_before),
            headers=OFFICER,
        )
        validate_error(
            response,
            ApiErrorId.MODEL_ASSET_NOT_APPROVED_FOR_USE,
            expected_status=ASSET_NOT_APPROVED_STATUS_ON_BINDING_CREATION,
        )

        assert list_bindings(api, use_case["id"]) == []
        asset_after = read_asset(api, asset["id"])
        assert asset_after["active_binding_count"] == 0
        assert asset_after["version"] == 1
        assert asset_after["status"] == "REGISTERED"
        assert read_use_case(api, use_case["id"])["version"] == version_before

    def test_identical_create_succeeds_once_the_asset_is_approved_for_use(self, api):
        """PRD §3.1: "Clearing an asset for use moves it from `REGISTERED` to `APPROVED_FOR_USE`, and this is the gate at which third-party supply is tested: if `is_third_party` is true, the asset must already carry a `VendorModelAssessment` with status `ACCEPTED` whose `terms_grade` is `A`, `B` or `C`, and without one the attempt is rejected with `ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED`." PRD §3.1: "In both directions, clearing increments the asset's `version`, and that increment is exactly what makes previously pinned bindings stale — every binding on the asset whose status is `PINNED` and whose `pinned_model_version` is below the new asset version is moved to `STALE` with `superseded_reason` set to `ASSET_REAPPROVED`." PRD §3.4: "The new binding lands in status `PINNED` with `pinned_model_version` set to the asset's `version` at that instant and `pinned_at` set to the current logical instant."

        Design: Difficulty/cross_entity_state_dependency/binding_creation_depends_on_model_asset_status
        """
        pin_clock(api)
        asset = register_asset(api)
        assert asset["is_third_party"] is False
        use_case = classified_use_case(api, LIMITED_USE_CASE)
        payload = model_binding_payload(asset["id"], use_case["version"])

        refused = api.create_model_binding(use_case["id"], payload, headers=OFFICER)
        validate_error(
            refused,
            ApiErrorId.MODEL_ASSET_NOT_APPROVED_FOR_USE,
            expected_status=ASSET_NOT_APPROVED_STATUS_ON_BINDING_CREATION,
        )

        approved_asset = approve_asset(api, asset["id"])
        assert approved_asset["status"] == "APPROVED_FOR_USE"
        assert approved_asset["version"] == 2

        # The identical body, including the same expected_use_case_version.
        binding = validate_success(
            api.create_model_binding(use_case["id"], payload, headers=OFFICER),
            expected_status=201,
        )
        assert binding["status"] == "PINNED"
        assert binding["pinned_model_version"] == 2
        assert binding["superseded_reason"] is None
        assert_iso_instant(binding["pinned_at"], DEFAULT_CLOCK)
        assert read_asset(api, asset["id"])["active_binding_count"] == 1


class TestEvaluationWindowsHalfOpenOnSharedModelAsset:
    """Test capacity is reserved on the asset, and the interval is half-open."""

    def test_touching_windows_are_accepted_in_both_directions(self, api):
        """PRD §3.4: "Test capacity on an asset is exclusive, and the window semantics are **half-open**: a window covers its `window_start_at` inclusively and stops short of its `window_end_at`." PRD §3.4: "Two windows conflict when the new window starts strictly before the existing one ends and the existing one starts strictly before the new one ends. Because both comparisons are strict, windows that merely touch do not conflict: an existing window ending at some instant and a new window beginning at that exact same instant are both accepted."

        Design: Difficulty/resource_temporal_overlap/evaluation_windows_half_open_on_shared_model_asset
        """
        chain = shared_asset_two_bound_use_cases(api)
        first = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "BIAS",
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
        )
        assert first["status"] == "PLANNED"

        after = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "ROBUSTNESS",
            "2026-08-03T00:00:00Z",
            "2026-08-04T00:00:00Z",
        )
        assert_iso_instant(after["window_start_at"], "2026-08-03T00:00:00Z")

        before = _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "HALLUCINATION",
            "2026-08-01T12:00:00Z",
            "2026-08-02T00:00:00Z",
        )
        assert_iso_instant(before["window_end_at"], "2026-08-02T00:00:00Z")

        assert len(list_evaluations(api, model_binding_id=chain.binding_id)) == 3

    def test_containment_counts_as_overlap_and_the_refusal_reserves_nothing(self, api):
        """PRD §3.4: "Two windows conflict when the new window starts strictly before the existing one ends and the existing one starts strictly before the new one ends." PRD §3.4: "A genuine overlap is rejected with `ERR_EVALUATION_WINDOW_CONFLICT`. Evaluations in `VOIDED` are excluded from the candidate set and therefore free the window they had reserved."

        Design: Difficulty/resource_temporal_overlap/evaluation_windows_half_open_on_shared_model_asset
        """
        chain = shared_asset_two_bound_use_cases(api)
        _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "BIAS",
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
        )

        response = api.create_test_evaluation(
            evaluation_schedule_payload(
                chain.binding_id,
                "HALLUCINATION",
                "2026-08-02T12:00:00Z",
                "2026-08-02T18:00:00Z",
                use_case_id=chain.use_case_id,
            ),
            headers=SECURITY_REVIEWER,
        )
        validate_error(response, ApiErrorId.EVALUATION_WINDOW_CONFLICT)

        # The refused create left no PLANNED row behind to poison later checks.
        rows = list_evaluations(api, model_binding_id=chain.binding_id)
        assert len(rows) == 1
        assert rows[0]["eval_type"] == "BIAS"
        assert list_evaluations(api, eval_type="HALLUCINATION") == []

    def test_the_candidate_set_spans_every_binding_of_the_same_asset(self, api):
        """PRD §3.4: "The candidate set for a conflict is every evaluation whose `model_binding_id` points at *any* binding of the same asset — not merely the same binding — whose status is `PLANNED`, `PASSED` or `FAILED`."

        Design: Difficulty/resource_temporal_overlap/evaluation_windows_half_open_on_shared_model_asset
        """
        chain = shared_asset_two_bound_use_cases(api)
        second_use_case_id = chain.extra["second_use_case"]["id"]
        binding_b = chain.extra["binding_b"]["id"]
        assert chain.extra["binding_b"]["model_asset_id"] == chain.asset_id
        assert list_evaluations(api, model_binding_id=binding_b) == []

        _schedule_evaluation(
            api,
            chain.use_case_id,
            chain.binding_id,
            "ROBUSTNESS",
            "2026-08-03T00:00:00Z",
            "2026-08-04T00:00:00Z",
        )

        response = api.create_test_evaluation(
            evaluation_schedule_payload(
                binding_b,
                "BIAS",
                "2026-08-03T06:00:00Z",
                "2026-08-03T12:00:00Z",
                use_case_id=second_use_case_id,
            ),
            headers=SECURITY_REVIEWER,
        )
        validate_error(response, ApiErrorId.EVALUATION_WINDOW_CONFLICT)

        # B is not blocked wholesale: a free window on the same asset is accepted.
        accepted = _schedule_evaluation(
            api,
            second_use_case_id,
            binding_b,
            "BIAS",
            "2026-08-04T00:00:00Z",
            "2026-08-05T00:00:00Z",
        )
        assert accepted["status"] == "PLANNED"
        assert len(list_evaluations(api, model_binding_id=binding_b)) == 1
        assert len(list_evaluations(api, model_binding_id=chain.binding_id)) == 1


class TestDisclosureNoticeWindowsClosedWithQuietBuffer:
    """A notice slot is keyed by (use case, notice_type, jurisdiction) and closed."""

    @pytest.mark.parametrize(
        "effective_from, effective_to",
        [
            ("2026-09-30T00:00:00Z", "2026-10-05T00:00:00Z"),
            ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"),
            ("2026-10-07T00:00:00Z", "2026-10-31T00:00:00Z"),
        ],
    )
    def test_touching_and_in_buffer_successors_are_refused(
        self, api, effective_from, effective_to
    ):
        """PRD §3.6: "A notice window is **closed** at both ends — it includes both `effective_from` and `effective_to` — and it additionally reserves a quiet buffer of 7 days after it ends." PRD §3.6: "A new notice conflicts with an existing one when the new window's `effective_from` falls at or before 7 days after the existing window's `effective_to` **and** the existing window's `effective_from` falls at or before 7 days after the new window's `effective_to`. Because the comparisons are inclusive, touching windows do conflict, and so does a new window that begins anywhere inside the 7-day buffer following an existing one — for an existing window ending at `2026-09-30T00:00:00Z`, the earliest start the system will accept for a successor is `2026-10-08T00:00:00Z`. A conflict is rejected with `ERR_DISCLOSURE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/disclosure_notice_windows_closed_with_quiet_buffer_per_jurisdiction
        """
        chain = use_case_with_september_eu_notice_window(api)
        assert_iso_instant(chain.notices["EU"]["effective_to"], "2026-09-30T00:00:00Z")

        response = api.create_disclosure_notice(
            chain.use_case_id,
            disclosure_notice_payload(
                "AUTOMATED_DECISION_NOTICE",
                "EU",
                effective_from,
                effective_to,
                locale_count=3,
            ),
            headers=REQUESTER,
        )
        validate_error(response, ApiErrorId.DISCLOSURE_WINDOW_CONFLICT)

        published = list_notices(api, chain.use_case_id, status="PUBLISHED")
        assert len(published) == 1
        assert published[0]["id"] == chain.notices["EU"]["id"]

    def test_the_earliest_legal_successor_start_is_the_eighth_of_october(self, api):
        """PRD §3.6: "Because the comparisons are inclusive, touching windows do conflict, and so does a new window that begins anywhere inside the 7-day buffer following an existing one — for an existing window ending at `2026-09-30T00:00:00Z`, the earliest start the system will accept for a successor is `2026-10-08T00:00:00Z`."

        Design: Difficulty/resource_temporal_overlap/disclosure_notice_windows_closed_with_quiet_buffer_per_jurisdiction
        """
        chain = use_case_with_september_eu_notice_window(api)

        notice = validate_success(
            api.create_disclosure_notice(
                chain.use_case_id,
                disclosure_notice_payload(
                    "AUTOMATED_DECISION_NOTICE",
                    "EU",
                    "2026-10-08T00:00:00Z",
                    "2026-10-31T00:00:00Z",
                    locale_count=3,
                ),
                headers=REQUESTER,
            ),
            expected_status=201,
        )
        assert notice["status"] == "PUBLISHED"
        assert_iso_instant(notice["effective_from"], "2026-10-08T00:00:00Z")
        assert len(list_notices(api, chain.use_case_id, status="PUBLISHED")) == 2

    @pytest.mark.parametrize(
        "notice_type, jurisdiction",
        [
            ("AUTOMATED_DECISION_NOTICE", "UK"),
            ("USER_FACING_AI_DISCLOSURE", "EU"),
        ],
    )
    def test_an_identical_window_on_a_different_slot_key_is_accepted(
        self, api, notice_type, jurisdiction
    ):
        """PRD §3.6: "Uniqueness is scoped to the triple of use case, `notice_type` and `jurisdiction`, and only `PUBLISHED` rows on that triple are candidates."

        Design: Difficulty/resource_temporal_overlap/disclosure_notice_windows_closed_with_quiet_buffer_per_jurisdiction
        """
        chain = use_case_with_september_eu_notice_window(api)
        existing = chain.notices["EU"]
        assert existing["notice_type"] == "AUTOMATED_DECISION_NOTICE"
        assert existing["jurisdiction"] == "EU"

        notice = validate_success(
            api.create_disclosure_notice(
                chain.use_case_id,
                disclosure_notice_payload(
                    notice_type,
                    jurisdiction,
                    existing["effective_from"],
                    existing["effective_to"],
                    locale_count=3,
                ),
                headers=REQUESTER,
            ),
            expected_status=201,
        )
        assert notice["status"] == "PUBLISHED"
        assert notice["notice_type"] == notice_type
        assert notice["jurisdiction"] == jurisdiction
        assert notice["effective_from"] == existing["effective_from"]
        assert notice["effective_to"] == existing["effective_to"]
        assert len(list_notices(api, chain.use_case_id, status="PUBLISHED")) == 2

    def test_withdrawing_the_incumbent_frees_the_slot_immediately(self, api):
        """PRD §3.6: "A `WITHDRAWN` notice is excluded from the candidate set and therefore frees its slot immediately." PRD §3.6: "Withdrawal moves a notice `PUBLISHED → WITHDRAWN` and stamps `withdrawn_at` with the current logical instant, releasing the jurisdiction slot for a fresh publication."

        Design: Difficulty/resource_temporal_overlap/disclosure_notice_windows_closed_with_quiet_buffer_per_jurisdiction
        """
        chain = use_case_with_september_eu_notice_window(api)
        successor = disclosure_notice_payload(
            "AUTOMATED_DECISION_NOTICE",
            "EU",
            "2026-10-01T00:00:00Z",
            "2026-10-31T00:00:00Z",
            locale_count=3,
        )

        refused = api.create_disclosure_notice(
            chain.use_case_id, successor, headers=REQUESTER
        )
        validate_error(refused, ApiErrorId.DISCLOSURE_WINDOW_CONFLICT)

        withdrawn = validate_success(
            api.withdraw_disclosure_notice(
                chain.notices["EU"]["id"], headers=REQUESTER
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_iso_instant(withdrawn["withdrawn_at"], DEFAULT_CLOCK)

        republished = validate_success(
            api.create_disclosure_notice(
                chain.use_case_id, successor, headers=REQUESTER
            ),
            expected_status=201,
        )
        assert republished["status"] == "PUBLISHED"
        assert_iso_instant(republished["effective_from"], "2026-10-01T00:00:00Z")
        assert len(list_notices(api, chain.use_case_id, status="PUBLISHED")) == 1
        assert len(list_notices(api, chain.use_case_id, status="WITHDRAWN")) == 1


class TestApproveAndRevokeConservePortfolioHeadcountReach:
    """Invariant R: the ledger's reach balance equals the live portfolio reach."""

    def test_approval_books_the_reach_and_the_balance_matches_the_portfolio(self, api):
        """PRD §2.11: "**Conserved quantity 1 — inventory headcount reach.** The three statuses `APPROVED`, `UNDER_REASSESSMENT` and `SUSPENDED` constitute the *inventory statuses*: a use case in any of them is live in the governance inventory. `portfolio_approved_reach` is the sum of `deployed_headcount_reach` over every use case in an inventory status, and `portfolio_approved_reach_high_tier` is that same sum restricted to use cases whose `final_risk_tier` is `HIGH`. The sum of `reach_delta` over all ledger entries — `ledger_reach_balance` — must equal `portfolio_approved_reach` at all times." PRD §3.7: "`control_credit`, `vendor_penalty`, `final_risk_score` and `final_risk_tier` are written onto the use case, `approved_by_user_id` records the signing `X-User-ID`, `monitoring_posture` is set to `HEALTHY`, and a `GovernanceLedgerEntry` of type `APPROVAL_GRANTED` is appended with a `reach_delta` of plus the use case's `deployed_headcount_reach` and a `debt_delta` of 0.00."

        Design: Difficulty/compensating_invariant/approve_and_revoke_conserve_portfolio_headcount_reach
        """
        chain = _limited_approval(api)
        assert chain.use_case["status"] == "APPROVED"
        assert chain.use_case["deployed_headcount_reach"] == 5000
        assert chain.use_case["final_risk_tier"] == "LIMITED"

        granted = list_ledger(api, chain.use_case_id, entry_type="APPROVAL_GRANTED")
        assert len(granted) == 1
        assert granted[0]["reach_delta"] == 5000
        assert_debt_equals(granted[0]["debt_delta"], 0.00)

        summary = read_summary(api)
        assert summary["inventory_count"] == 1
        assert summary["portfolio_approved_reach"] == 5000
        assert summary["ledger_reach_balance"] == 5000
        assert summary["portfolio_approved_reach_high_tier"] == 0
        assert_reach_conserved(summary)

    def test_the_suspend_and_reinstate_excursion_moves_no_reach(self, api):
        """PRD §3.8: "When posture re-derivation leaves a use case that is in `APPROVED` or `UNDER_REASSESSMENT` at `IMPAIRED`, that use case moves to `SUSPENDED`, every `ModelBinding` of the use case in `PINNED` drops to `STALE` with `superseded_reason` `APPROVAL_SUSPENDED`, every `TestEvaluation` in `PLANNED` on a binding that just went stale is `VOIDED`, and a `GovernanceLedgerEntry` of type `APPROVAL_SUSPENDED` is appended with `reach_delta` 0 and `debt_delta` 0.00. The reach delta is zero precisely because `SUSPENDED` remains an inventory status — a suspension does not take reach out of the portfolio." PRD §3.8: "If the posture now comes out `HEALTHY`, the use case is currently `SUSPENDED`, and the current logical instant is strictly before `approval_expires_at`, then the use case is reinstated `SUSPENDED → APPROVED`; every `ModelBinding` of the use case whose status is `STALE`, whose `superseded_reason` is `APPROVAL_SUSPENDED` and whose `pinned_model_version` still equals its asset's current `version` returns to `PINNED` with `superseded_reason` cleared to null; and a `GovernanceLedgerEntry` of type `APPROVAL_REINSTATED` is appended with `reach_delta` 0 and `debt_delta` 0.00, keeping the reach total conserved across the whole suspend-and-reinstate round trip."

        Design: Difficulty/compensating_invariant/approve_and_revoke_conserve_portfolio_headcount_reach
        """
        chain = _limited_approval(api)
        incident = report_incident(
            api, chain.use_case_id, "SEV1", reported_to_regulator=True
        )
        suspended = read_use_case(api, chain.use_case_id)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["monitoring_posture"] == "IMPAIRED"

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 5000
        assert summary["ledger_reach_balance"] == 5000
        assert summary["inventory_count"] == 1
        assert_reach_conserved(summary)

        validate_success(
            api.contain_incident(
                incident["id"], {"reported_to_regulator": True}, headers=OFFICER
            )
        )
        resolved = validate_success(
            api.resolve_incident(
                incident["id"], {"reported_to_regulator": True}, headers=OFFICER
            )
        )
        assert resolved["status"] == "RESOLVED"

        reinstated = read_use_case(api, chain.use_case_id)
        assert reinstated["status"] == "APPROVED"
        assert reinstated["monitoring_posture"] == "HEALTHY"
        binding = list_bindings(api, chain.use_case_id)[0]
        assert binding["status"] == "PINNED"
        assert binding["superseded_reason"] is None

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 5000
        assert summary["ledger_reach_balance"] == 5000
        assert summary["portfolio_approved_reach_high_tier"] == 0
        assert_reach_conserved(summary)

        for entry_type in ("APPROVAL_SUSPENDED", "APPROVAL_REINSTATED"):
            entries = list_ledger(api, chain.use_case_id, entry_type=entry_type)
            assert len(entries) == 1
            assert entries[0]["reach_delta"] == 0
            assert_debt_equals(entries[0]["debt_delta"], 0.00)

    def test_revocation_compensates_the_approval_to_exactly_zero(self, api):
        """PRD §3.8: "Its `reach_delta` is minus the use case's `deployed_headcount_reach` when the use case was in an inventory status — `APPROVED`, `UNDER_REASSESSMENT` or `SUSPENDED` — and 0 when it was merely `READY_FOR_APPROVAL` and therefore never counted toward the portfolio." PRD §3.8: "Because hop 1's negative reach delta exactly offsets the positive one the approval booked, the sum of `reach_delta` for that use case returns to 0 and the portfolio reach returns to its pre-approval value." PRD §2.11: "This holds because an approval books plus the use case's `deployed_headcount_reach` and its compensating revocation books minus the same figure, while suspension and reinstatement book 0 on both sides: `SUSPENDED` is itself an inventory status, so posture churn cannot drift the reach total."

        Design: Difficulty/compensating_invariant/approve_and_revoke_conserve_portfolio_headcount_reach
        """
        chain = _limited_approval(api)
        incident = report_incident(
            api, chain.use_case_id, "SEV1", reported_to_regulator=True
        )
        validate_success(
            api.contain_incident(
                incident["id"], {"reported_to_regulator": True}, headers=OFFICER
            )
        )
        validate_success(
            api.resolve_incident(
                incident["id"], {"reported_to_regulator": True}, headers=OFFICER
            )
        )

        revoked = revoke_use_case(api, chain.use_case_id)
        assert revoked["status"] == "REVOKED"

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 0
        assert summary["ledger_reach_balance"] == 0
        assert summary["portfolio_approved_reach_high_tier"] == 0
        assert summary["inventory_count"] == 0
        assert_reach_conserved(summary)

        entries = list_ledger(api, chain.use_case_id)
        assert_ledger_reach_balance(entries, 0)
        booked = entry_types(entries)
        for entry_type in (
            "APPROVAL_GRANTED",
            "APPROVAL_SUSPENDED",
            "APPROVAL_REINSTATED",
            "APPROVAL_REVOKED",
            "BINDING_RETIRED",
        ):
            assert booked.count(entry_type) == 1
        assert list_ledger(api, chain.use_case_id, entry_type="APPROVAL_REVOKED")[0][
            "reach_delta"
        ] == -5000
        assert list_ledger(api, chain.use_case_id, entry_type="BINDING_RETIRED")[0][
            "reach_delta"
        ] == 0

        # The reach invariant closes without any asset-side hop: a first-party asset
        # is never restricted by the revocation cascade.
        asset = read_asset(api, chain.asset_id)
        assert asset["is_third_party"] is False
        assert asset["status"] == "APPROVED_FOR_USE"
        assert asset["active_binding_count"] == 0


class TestGateClearAndReopenConserveControlDebt:
    """Invariant D: clear and reopen close at 0.00, while voiding does not."""

    def test_clearance_books_minus_the_debt_the_gate_carried(self, api):
        """PRD §3.3: "A gate's `control_debt_index` is its gate-type weight, multiplied by its `open_condition_count` divided by 3, multiplied by the tier multiplier of its own `pinned_risk_tier`, with the product rounded half up to two decimal places. The gate-type weights are 1.35 for `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`. The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for `HIGH` and 2.0 for `PROHIBITED`." PRD §3.3: "Once those pass, the clearance captures `debt_before_clear` from the gate's current `control_debt_index` (this is what makes the compensating reopen exact), zeroes `control_debt_index` to 0.00 and `open_condition_count` to 0, records `cleared_by_user_id` and `cleared_at`, and appends a `GovernanceLedgerEntry` of type `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the captured `debt_before_clear`."

        Design: Difficulty/compensating_invariant/gate_clear_and_reopen_conserve_control_debt_to_the_cent
        """
        chain = high_tier_with_legal_conditions(api, 2)
        create_binding(api, chain.use_case_id, chain.asset_id)
        gate = chain.gates["LEGAL"]
        assert gate["status"] == "CONDITIONS_ISSUED"
        assert gate["open_condition_count"] == 2
        assert gate["pinned_risk_tier"] == "HIGH"
        assert_debt_equals(gate["control_debt_index"], 1.35)
        assert_debt_equals(
            gate["control_debt_index"], expected_gate_debt("LEGAL", 2, "HIGH")
        )

        before = read_summary(api)
        assert_debt_equals(before["control_debt_index_total"], 1.35)
        assert_debt_equals(before["ledger_debt_balance"], 0.00)
        assert list_ledger(api, chain.use_case_id) == []

        cleared = validate_success(
            api.clear_gate(
                gate["id"],
                {"decision_note": "assignment letter received, notice text added"},
                headers=LEGAL_REVIEWER,
            )
        )
        assert cleared["status"] == "CLEARED"
        assert_debt_equals(cleared["control_debt_index"], 0.00)
        assert_debt_equals(cleared["debt_before_clear"], 1.35)

        after = read_summary(api)
        assert_debt_equals(after["control_debt_index_total"], 0.00)
        assert_debt_equals(after["ledger_debt_balance"], -1.35)
        assert_debt_total_matches_gates(after, list_gates(api, chain.use_case_id))

        entries = list_ledger(api, chain.use_case_id, entry_type="GATE_CLEARED")
        assert len(entries) == 1
        assert_debt_equals(entries[0]["debt_delta"], -1.35)
        assert entries[0]["reach_delta"] == 0
        assert read_use_case(api, chain.use_case_id)["cleared_gate_count"] == 1

    def test_reopening_restores_the_exact_cent_and_closes_the_ledger(self, api):
        """PRD §2.11: "For any gate, clearing and then reopening is debt-neutral by construction: clearance books a `debt_delta` of minus the debt the gate carried and reopening books plus exactly that same figure, so `control_debt_index_total` returns to its exact pre-clearance cent value and the ledger debt balance for that use case returns to 0.00." PRD §3.3: "It restores `control_debt_index` verbatim from `debt_before_clear`, sets `open_condition_count` to 0, nulls both `cleared_by_user_id` and `cleared_at`, optionally records a `decision_note`, and appends a `GovernanceLedgerEntry` of type `GATE_REOPENED` with `reach_delta` 0 and a `debt_delta` of plus that same `debt_before_clear`."

        Design: Difficulty/compensating_invariant/gate_clear_and_reopen_conserve_control_debt_to_the_cent
        """
        chain = high_tier_with_legal_conditions(api, 2)
        create_binding(api, chain.use_case_id, chain.asset_id)
        gate = chain.gates["LEGAL"]
        assert_debt_equals(gate["control_debt_index"], 1.35)

        validate_success(
            api.clear_gate(
                gate["id"], {"decision_note": "conditions satisfied"}, headers=LEGAL_REVIEWER
            )
        )
        reopened = validate_success(
            api.reopen_gate(
                gate["id"],
                {"decision_note": "the assignment letter was unsigned"},
                headers=OFFICER,
            )
        )
        assert reopened["status"] == "IN_REVIEW"
        assert_debt_equals(reopened["control_debt_index"], 1.35)
        assert_debt_equals(reopened["debt_before_clear"], 1.35)
        assert reopened["open_condition_count"] == 0
        assert reopened["cleared_by_user_id"] is None
        assert reopened["cleared_at"] is None

        summary = read_summary(api)
        assert_debt_equals(summary["control_debt_index_total"], 1.35)
        assert_debt_equals(summary["ledger_debt_balance"], 0.00)

        entries = list_ledger(api, chain.use_case_id)
        assert entry_types(entries) == ["GATE_CLEARED", "GATE_REOPENED"]
        assert_debt_equals(entries[1]["debt_delta"], 1.35)
        assert_debt_equals(entries[0]["debt_delta"] + entries[1]["debt_delta"], 0.00)
        assert_ledger_debt_balance(entries, 0.00)
        assert entries[1]["reach_delta"] == 0
        assert read_use_case(api, chain.use_case_id)["cleared_gate_count"] == 0

    def test_voiding_gates_removes_debt_without_any_compensating_entry(self, api):
        """PRD §2.11: "Voiding a gate is deliberately **not** compensating — it removes that gate's contribution permanently and appends no ledger entry at all." PRD §3.3: "Voiding a gate out of `CONDITIONS_ISSUED` permanently removes its contribution from the portfolio debt total, and — unlike clearance and reopening — it appends no ledger entry, so voiding is deliberately not a compensating event." PRD §3.2: "A revision from `CHANGES_REQUESTED` lands the use case back in `DRAFT`; a revision from `DRAFT` leaves it in `DRAFT`. Either way the consequences are the same and they are severe by design: `classification_stale` is set to true, every `ReviewGate` on the use case whose status is `PENDING`, `IN_REVIEW`, `CONDITIONS_ISSUED` or `CLEARED` is moved to `VOIDED` with its `control_debt_index` zeroed to 0.00 and its `open_condition_count` zeroed, both `open_conditions_count` and `cleared_gate_count` on the use case are recomputed and therefore become 0, and the use case's `version` increments."

        Design: Difficulty/compensating_invariant/gate_clear_and_reopen_conserve_control_debt_to_the_cent
        """
        chain = high_tier_with_legal_conditions(api, 2)
        create_binding(api, chain.use_case_id, chain.asset_id)
        gate = chain.gates["LEGAL"]

        validate_success(
            api.clear_gate(
                gate["id"], {"decision_note": "conditions satisfied"}, headers=LEGAL_REVIEWER
            )
        )
        validate_success(
            api.reopen_gate(
                gate["id"], {"decision_note": "reopened for re-review"}, headers=OFFICER
            )
        )
        closed_pair = read_summary(api)
        assert_debt_equals(closed_pair["control_debt_index_total"], 1.35)
        assert_debt_equals(closed_pair["ledger_debt_balance"], 0.00)

        revised = validate_success(
            api.update_use_case(
                chain.use_case_id, {"deployed_headcount_reach": 9000}, headers=REQUESTER
            )
        )
        assert revised["status"] == "DRAFT"
        assert revised["classification_stale"] is True
        assert revised["cleared_gate_count"] == 0
        assert revised["open_conditions_count"] == 0

        gates = list_gates(api, chain.use_case_id)
        assert len(gates) == 4
        for voided in gates:
            assert voided["status"] == "VOIDED"
            assert_debt_equals(voided["control_debt_index"], 0.00)
            assert voided["open_condition_count"] == 0

        summary = read_summary(api)
        assert_debt_equals(summary["control_debt_index_total"], 0.00)
        assert_debt_equals(summary["ledger_debt_balance"], 0.00)
        # The debt left the portfolio uncompensated: no third entry was appended.
        assert entry_types(list_ledger(api, chain.use_case_id)) == [
            "GATE_CLEARED",
            "GATE_REOPENED",
        ]
