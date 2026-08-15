"""Work letter negotiation: the PROPOSED-COUNTERED cycle, execution, OCC."""
from test_helpers import (
    TEST_DEFAULTS,
    ApiErrorId,
    counter_work_letter_payload,
    create_lease_record,
    create_lease_space_record,
    create_project_record,
    create_property_record,
    create_tenant_record,
    create_work_letter_record,
    get_success_data,
    make_tenant_rep_headers,
    setup_project_negotiated,
    setup_property_space_tenant_lease,
    validate_error,
    validate_success,
)

class TestNegotiationCycle:
    def test_negotiation_volley_round_numbers_and_execution(
        self, api, landlord_pm_headers
    ):
        """PRD 3.2: "each counter increments `round_number` by exactly 1 and,
        because the counter is written against a specific draft, the request
        must carry `expected_work_letter_version` equal to the letter's current
        `version`". PRD 3.2: "The landlord may re-propose from `COUNTERED` back
        to `PROPOSED`, again stamping `proposed_by` as `LANDLORD` without
        touching `round_number`, and this `PROPOSED` → `COUNTERED` → `PROPOSED`
        volley may repeat without bound." PRD 3.2: "Execution is the moment the
        allowance pool is born: the project's `allowance_total_cents` is set
        from the letter's `allowance_offer_cents`, `allowance_remaining_cents`
        is recomputed, and both records' versions increment."

        Design: Difficulty/non_linear_state_machine/work_letter_negotiation_cycle
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        tenant_headers = make_tenant_rep_headers(base["tenant"]["id"])

        wl = create_work_letter_record(
            project["id"], allowance_offer_cents=45_000_000, work_delineation="LANDLORD"
        )
        assert wl["round_number"] == 0
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        assert wl["status"] == "PROPOSED" and wl["proposed_by"] == "LANDLORD"

        # Tenant counter #1 (round 1).
        observed = get_success_data(api.get_work_letter(wl["id"], landlord_pm_headers))["version"]
        wl = get_success_data(
            api.counter_work_letter(
                wl["id"],
                counter_work_letter_payload(observed, allowance_offer_cents=52_000_000),
                tenant_headers,
            )
        )
        assert wl["status"] == "COUNTERED" and wl["round_number"] == 1

        # Landlord re-proposes; tenant counter #2 (round 2).
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        assert wl["status"] == "PROPOSED" and wl["round_number"] == 1
        observed = wl["version"]
        wl = get_success_data(
            api.counter_work_letter(
                wl["id"],
                counter_work_letter_payload(observed, allowance_offer_cents=50_000_000),
                tenant_headers,
            )
        )
        assert wl["status"] == "COUNTERED" and wl["round_number"] == 2

        # Landlord re-proposes, tenant accepts, landlord executes.
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        wl = get_success_data(api.accept_work_letter(wl["id"], tenant_headers))
        wl = get_success_data(api.execute_work_letter(wl["id"], landlord_pm_headers))

        assert wl["status"] == "EXECUTED"
        assert wl["round_number"] == 2, f"two tenant counters must yield round 2, got {wl['round_number']}"
        assert wl["allowance_offer_cents"] == 50_000_000, (
            "the latest countered offer rides on the letter into execution"
        )
        project = get_success_data(api.get_project(project["id"], landlord_pm_headers))
        assert project["allowance_total_cents"] == 50_000_000
        assert project["allowance_remaining_cents"] == 50_000_000

    def test_single_counter_increments_round_and_repropose_preserves_it(
        self, api, landlord_pm_headers
    ):
        """PRD 3.2: "The tenant's representative — and only the `TenantRep`
        whose identity matches the lease — may counter, moving `PROPOSED` →
        `COUNTERED` with a revised `scope_description`, `allowance_offer_cents`,
        and `work_delineation`; each counter increments `round_number` by
        exactly 1". PRD 3.2: "The landlord may re-propose from `COUNTERED` back
        to `PROPOSED`, again stamping `proposed_by` as `LANDLORD` without
        touching `round_number`".

        Design: Difficulty/non_linear_state_machine/work_letter_negotiation_cycle
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        tenant_headers = make_tenant_rep_headers(base["tenant"]["id"])

        wl = create_work_letter_record(project["id"])
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        wl = get_success_data(
            api.counter_work_letter(
                wl["id"], counter_work_letter_payload(wl["version"]), tenant_headers
            )
        )
        assert wl["status"] == "COUNTERED"
        assert wl["round_number"] == 1, f"one counter must yield round 1, got {wl['round_number']}"

        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        assert wl["status"] == "PROPOSED"
        assert wl["proposed_by"] == "LANDLORD"
        assert wl["round_number"] == 1, "re-proposing must not touch round_number"


class TestWorkLetterTerminalStates:
    def test_work_letter_withdraw_from_executed_rejected(self, api, landlord_pm_headers):
        """PRD 3.2: "At any point before acceptance the landlord may withdraw a
        letter from `DRAFT`, `PROPOSED`, or `COUNTERED` into `WITHDRAWN`;
        `EXECUTED` and `WITHDRAWN` are terminal." PRD 2.7: "The targeted entity
        must be in a state from which the requested transition exists —
        including the parent-phase gates named throughout §3 — and terminal
        states reject every transition, else `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/work_letter_withdraw_from_executed_rejected
        """
        sc = setup_project_negotiated()
        wl = sc["work_letter"]
        assert wl["status"] == "EXECUTED"
        resp = api.withdraw_work_letter(wl["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        wl_after = get_success_data(api.get_work_letter(wl["id"], landlord_pm_headers))
        assert wl_after["status"] == "EXECUTED"

    def test_second_work_letter_execute_rejected_already_executed(
        self, api, landlord_pm_headers
    ):
        """PRD 3.2: "execution is refused with
        `ERR_WORK_LETTER_ALREADY_EXECUTED` (HTTP 409) when another letter of the
        same project is already `EXECUTED`, because exactly one letter may ever
        reach that state per project."

        Design: Corner/state_machines/second_work_letter_execute_rejected_already_executed
        """
        sc = setup_project_negotiated(
            allowance_offer_cents=TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"]
        )
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])
        wl2 = create_work_letter_record(sc["project"]["id"], allowance_offer_cents=51_000_000)
        wl2 = get_success_data(api.propose_work_letter(wl2["id"], landlord_pm_headers))
        wl2 = get_success_data(api.accept_work_letter(wl2["id"], tenant_headers))
        resp = api.execute_work_letter(wl2["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_WORK_LETTER_ALREADY_EXECUTED)
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_total_cents"] == TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"], (
            "the first letter's executed offer must stand unchanged"
        )


class TestWorkLetterBodyValidation:
    def test_work_letter_invalid_enum_returns_invalid_request(self, api, landlord_pm_headers):
        """PRD 3.2: "the `work_delineation` declaring who performs base-building
        versus suite work: `LANDLORD`, `TENANT`, or `SPLIT`." PRD 2.7:
        "Required fields are present, types are correct, enum members are
        valid, and monetary amounts are integer cents, else
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/work_letter_invalid_enum_returns_invalid_request
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        resp = api.create_work_letter(
            project["id"],
            {
                "scope_description": "bad enum",
                "allowance_offer_cents": 100,
                "work_delineation": "SHARED",
            },
            landlord_pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExecutionConsistency:
    def test_immediate_visibility_of_execute_side_effect(self, api, landlord_pm_headers):
        """PRD 2.9: "The project aggregate is kept internally consistent by
        cascades that run as part of the mutation that triggers them, never
        asynchronously." PRD 3.2: "Execution is the moment the allowance pool
        is born: the project's `allowance_total_cents` is set from the letter's
        `allowance_offer_cents`, `allowance_remaining_cents` is recomputed, and
        both records' versions increment."

        Design: Corner/consistency_model/immediate_visibility_of_execute_side_effect
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        tenant_headers = make_tenant_rep_headers(base["tenant"]["id"])
        wl = create_work_letter_record(project["id"], allowance_offer_cents=50_000_000)
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        wl = get_success_data(api.accept_work_letter(wl["id"], tenant_headers))

        executed = validate_success(api.execute_work_letter(wl["id"], landlord_pm_headers), 200)
        assert executed["status"] == "EXECUTED", (
            "the mutation response itself must report EXECUTED"
        )
        project = validate_success(api.get_project(project["id"], landlord_pm_headers), 200)
        assert project["allowance_total_cents"] == 50_000_000, (
            "an immediate read must already reflect the stamped allowance pool"
        )
        assert project["allowance_remaining_cents"] == 50_000_000


class TestWorkLetterOcc:
    def test_occ_work_letter_counter_stale_version_rejected(self, api, landlord_pm_headers):
        """PRD 2.8: "Counter-proposing a work letter (`POST
        /api/work-letters/{id}/counter`) requires `expected_work_letter_version`
        carrying the `version` of the work letter the client last observed. If
        the letter's current `version` has since advanced — for example because
        the landlord just re-proposed, advancing both `round_number` context and
        `version` — the counter is rejected with `ERR_STALE_VERSION` (HTTP
        412), because it was drafted against a draft of the letter the tenant
        has not seen."

        Design: Corner/cross_cutting_layers/occ_work_letter_counter_stale_version_rejected
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        tenant_headers = make_tenant_rep_headers(base["tenant"]["id"])
        wl = create_work_letter_record(project["id"], allowance_offer_cents=45_000_000)
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))

        observed = get_success_data(api.get_work_letter(wl["id"], tenant_headers))["version"]
        # Tenant counters successfully (round 1), landlord re-proposes: version advanced.
        wl = get_success_data(
            api.counter_work_letter(
                wl["id"],
                counter_work_letter_payload(observed, allowance_offer_cents=48_000_000),
                tenant_headers,
            )
        )
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))

        # The stale counter drafted against the pre-counter version is rejected.
        resp = api.counter_work_letter(
            wl["id"],
            counter_work_letter_payload(observed, allowance_offer_cents=49_000_000),
            tenant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Re-reading and retrying with the fresh version succeeds.
        fresh = get_success_data(api.get_work_letter(wl["id"], landlord_pm_headers))["version"]
        wl = validate_success(
            api.counter_work_letter(
                wl["id"],
                counter_work_letter_payload(fresh, allowance_offer_cents=49_000_000),
                tenant_headers,
            ),
            200,
        )
        assert wl["status"] == "COUNTERED"
        assert wl["round_number"] == 2


class TestTenantScope:
    def test_tenant_scope_violation_other_tenants_project_forbidden(
        self, api, landlord_pm_headers
    ):
        """PRD 2.1: "When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id`
        of the acting `Tenant`; ownership checks on any resource reached
        through a lease compare the lease's `tenant_id` field to `X-User-ID`,
        and a mismatch is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."
        PRD 3.2: "Acceptance is likewise scoped to the owning representative:
        the tenant accepts a tabled letter (`PROPOSED` → `ACCEPTED`)".

        Design: Corner/roles/tenant_scope_violation_other_tenants_project_forbidden
        """
        prop = create_property_record()
        space_a = create_lease_space_record(prop["id"])
        space_b = create_lease_space_record(prop["id"])
        tenant_a = create_tenant_record()
        tenant_b = create_tenant_record()
        create_lease_record(space_a["id"], tenant_a["id"])
        lease_b = create_lease_record(space_b["id"], tenant_b["id"])
        lease_b = get_success_data(api.activate_lease(lease_b["id"], landlord_pm_headers))
        project_b = create_project_record(lease_b["id"], project_name="TI-B")
        wl_b = create_work_letter_record(project_b["id"])
        wl_b = get_success_data(api.propose_work_letter(wl_b["id"], landlord_pm_headers))

        # Tenant A's representative attempts to accept tenant B's letter.
        resp = api.accept_work_letter(wl_b["id"], make_tenant_rep_headers(tenant_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)
        wl_after = get_success_data(api.get_work_letter(wl_b["id"], landlord_pm_headers))
        assert wl_after["status"] == "PROPOSED", "a foreign tenant's accept must not move the letter"
