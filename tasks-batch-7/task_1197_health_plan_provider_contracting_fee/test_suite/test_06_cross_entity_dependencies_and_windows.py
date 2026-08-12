"""Cross-entity state dependencies and resource temporal overlap."""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    add_continuity_case,
    create_carve_out_payload, create_contract_version_payload,
    create_fee_schedule_entry_payload, create_termination_notice_payload,
    create_draft_contract, create_network, create_provider,
    make_contract_legal_headers, make_contract_manager_headers,
    setup_contract_active, setup_issued_notice, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CL = TEST_USERS["contract_legal_headers"]
CM = TEST_USERS["contract_manager_headers"]


class TestBeginTestingRequiresValidatedVersion:
    def _setup_loaded_only(self, api):
        """Contract in IN_CONFIGURATION with version 1 LOADED (entry mapped)."""
        from test_helpers import create_published_benchmark
        net = create_network()
        create_published_benchmark()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        entry = get_success_data(api.create_fee_schedule_entry(
            version["id"], create_fee_schedule_entry_payload(), CA))
        get_success_data(api.map_benchmark(entry["id"], CA))
        get_success_data(api.load_version(version["id"], CA))
        return contract["id"], version["id"]

    def test_begin_testing_rejected_while_version_only_loaded(self, api):
        """PRD §3.6: "beginning testing requires the contract to be in
        `IN_CONFIGURATION` (`ERR_CONTRACT_INVALID_STATE` otherwise) and at least
        one of its versions to have reached `VALIDATED`, failing with
        `ERR_NO_VALIDATED_VERSION` (HTTP 422) when none has."

        Design: Difficulty/cross_entity_state_dependency/begin_testing_requires_validated_version
        """
        contract_id, _ = self._setup_loaded_only(api)
        resp = api.begin_testing(contract_id, CA)
        validate_error(resp, ApiErrorId.ERR_NO_VALIDATED_VERSION)

    def test_begin_testing_succeeds_after_version_validated(self, api):
        """PRD §3.6: "Success moves the contract to `IN_TESTING`, increments the
        `version`, and appends `CONTRACT_TESTING_STARTED`."

        Design: Difficulty/cross_entity_state_dependency/begin_testing_requires_validated_version
        """
        contract_id, version_id = self._setup_loaded_only(api)
        get_success_data(api.validate_version(version_id, CA))
        contract = get_success_data(api.begin_testing(contract_id, CA))
        assert contract["contract_status"] == "IN_TESTING"


class TestCocActivateRequiresNoticeEffective:
    def _setup_notified_case(self, api):
        artefacts = setup_issued_notice()
        notice = artefacts["notice"]
        case = add_continuity_case(
            notice["id"], member_ref="M1", condition_category="PREGNANCY",
            treatment_end_date="2026-12-01")
        get_success_data(api.notify_case(case["id"], CM))
        return artefacts, notice, case

    def test_activate_coverage_rejected_while_notice_issued(self, api):
        """PRD §3.9: "Coverage activation moves a case from `NOTIFIED` to
        `ACTIVE_COVERAGE` once the parent notice has become `EFFECTIVE`"

        Design: Difficulty/cross_entity_state_dependency/coc_activate_requires_notice_effective
        """
        _, _, case = self._setup_notified_case(api)
        resp = api.activate_coverage(case["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)

    def test_finalize_cascade_activates_notified_case(self, api):
        """PRD §3.9: "every continuity-of-care case of the notice standing
        `NOTIFIED` moves to `ACTIVE_COVERAGE`"

        Design: Difficulty/cross_entity_state_dependency/coc_activate_requires_notice_effective
        """
        _, notice, case = self._setup_notified_case(api)
        set_clock("2026-08-15T00:00:00Z")
        get_success_data(api.finalize_notice(notice["id"], ADMIN))
        case_after = get_success_data(api.get_continuity_case(case["id"], ADMIN))
        assert case_after["case_status"] == "ACTIVE_COVERAGE"


class TestVersionWindowCollision:
    def _setup_in_configuration(self, api):
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        return contract

    def test_equal_effective_dates_collide(self, api):
        """PRD §2.6: "two versions of the same contract may never share an
        `effective_date` — equal starts collide"
        PRD §3.4: "the `effective_date` must differ from every other version's
        `effective_date` on the same contract, because half-open windows with
        equal starts overlap, failing with `ERR_VERSION_WINDOW_OVERLAP` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/version_window_collision
        """
        contract = self._setup_in_configuration(api)
        get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        current = get_success_data(api.get_contract(contract["id"], ADMIN))
        resp = api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=2, effective_date="2026-07-01",
                expected_contract_version=current["version"]),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_WINDOW_OVERLAP)

    def test_distinct_effective_dates_never_conflict(self, api):
        """PRD §2.6: "any two distinct effective dates, however close, never
        conflict."

        Design: Difficulty/resource_temporal_overlap/version_window_collision
        """
        contract = self._setup_in_configuration(api)
        get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        current = get_success_data(api.get_contract(contract["id"], ADMIN))
        v2 = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=2, effective_date="2026-09-01",
                expected_contract_version=current["version"]),
            CM,
        ))
        assert v2["version_status"] == "DRAFT"


class TestCarveOutClosedIntervalAdjacency:
    def _setup_version_with_existing_carve_out(self, api):
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        get_success_data(api.create_carve_out(
            version["id"],
            create_carve_out_payload(
                service_category="TRANSPLANT", override_type="FLAT_RATE",
                override_flat_cents=5000000, start_date="2026-07-01",
                end_date="2026-12-31", priority_rank=1),
            CL,
        ))
        return version["id"]

    def test_adjacent_window_conflicts(self, api):
        """PRD §3.5: "a new window conflicts — and is rejected with
        `ERR_CARVE_OUT_WINDOW_CONFLICT` (HTTP 409) — when the new window's
        `start_date` falls on or before the day after the existing window's
        `end_date` and the existing window's `start_date` falls on or before the
        day after the new window's `end_date`."
        PRD §3.5: "True overlaps and back-to-back adjacency (one window ending
        the day before the other begins) are therefore both rejected"

        Design: Difficulty/resource_temporal_overlap/carve_out_closed_interval_adjacency
        """
        version_id = self._setup_version_with_existing_carve_out(api)
        resp = api.create_carve_out(
            version_id,
            create_carve_out_payload(
                service_category="TRANSPLANT", override_type="FLAT_RATE",
                override_flat_cents=5200000, start_date="2027-01-01",
                end_date="2027-06-30", priority_rank=2),
            CL,
        )
        validate_error(resp, ApiErrorId.ERR_CARVE_OUT_WINDOW_CONFLICT)

    def test_one_day_gap_and_different_category_do_not_conflict(self, api):
        """PRD §3.5: "window-conflict checks compare the literal value only, so a
        `"*"` carve-out and an OFFICE_VISIT carve-out never conflict on category
        grounds"
        PRD §3.5: adjacency rule conflicts only when `start_date` <= existing
        `end_date` + 1 day.

        Design: Difficulty/resource_temporal_overlap/carve_out_closed_interval_adjacency
        """
        version_id = self._setup_version_with_existing_carve_out(api)
        # 2027-01-02 leaves a 1-day gap after 2026-12-31: no conflict.
        ok1 = get_success_data(api.create_carve_out(
            version_id,
            create_carve_out_payload(
                service_category="TRANSPLANT", override_type="FLAT_RATE",
                override_flat_cents=5200000, start_date="2027-01-02",
                end_date="2027-06-30", priority_rank=2),
            CL,
        ))
        assert ok1["id"]
        # Same window on a DIFFERENT service_category: no conflict.
        ok2 = get_success_data(api.create_carve_out(
            version_id,
            create_carve_out_payload(
                service_category="DIALYSIS", override_type="EXCLUDE",
                start_date="2026-07-01", end_date="2026-12-31", priority_rank=1),
            CL,
        ))
        assert ok2["id"]
