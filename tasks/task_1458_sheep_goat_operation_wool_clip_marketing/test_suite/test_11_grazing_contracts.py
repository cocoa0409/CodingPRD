"""Grazing contracts: negotiation cycle, window gates, OCC counter-offers,
activation head range, contract-move state gates."""
from test_helpers import (
    ApiErrorId,
    create_contract,
    create_flock,
    create_move,
    set_clock,
    setup_active_contract,
    transition_contract,
    transition_move,
    validate_error,
    validate_success,
)


class TestNegotiationCycle:

    def test_grazing_contract_negotiation_cycle(self, api, ranch_manager_headers, grazing_client_headers):
        """PRD §3.8: "The client counters (`PROPOSED -> COUNTERED`) through the
        system's second optimistic-concurrency point: the request must carry
        `expected_grazing_contract_version` matching the contract's current
        `version`, else `ERR_STALE_CONTRACT_VERSION` (HTTP 412) per §2.6. Any
        term fields supplied with the counter — `rate_per_head_day_cents`,
        `min_head`, `max_head`, `service_window_start`, or
        `service_window_end` — overwrite the standing terms, and
        `terms_version` increments by 1 on every counter. The ranch may then
        adopt the countered terms as the standing proposal (`COUNTERED ->
        PROPOSED`), or accept the client's counter outright (`COUNTERED ->
        ACCEPTED`)".

        Design: Difficulty/non_linear_state_machine/grazing_contract_negotiation_cycle
        """
        flock = create_flock(flock_name="Contract Ranch", species="SHEEP", baseline_headcount=800)
        contract = create_contract(
            flock["id"], client_org_name="City Weed Board", parcel_name="North 40",
            service_window_start="2026-09-01T00:00:00Z",
            service_window_end="2026-09-30T00:00:00Z",
            rate_per_head_day_cents=100, min_head=50, max_head=600,
            target_cover_reduction_pct=70.0)
        assert contract["contract_status"] == "DRAFT"
        assert contract["terms_version"] == 1

        contract = transition_contract(contract["id"], "PROPOSED")
        v2 = contract["version"]
        contract = validate_success(api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": v2, "rate_per_head_day_cents": 120,
        }, grazing_client_headers))
        assert contract["contract_status"] == "COUNTERED"
        assert contract["terms_version"] == 2
        assert contract["rate_per_head_day_cents"] == 120

        contract = transition_contract(contract["id"], "PROPOSED")
        v4 = contract["version"]
        contract = validate_success(api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": v4, "rate_per_head_day_cents": 110,
        }, grazing_client_headers))
        assert contract["terms_version"] == 3
        assert contract["rate_per_head_day_cents"] == 110

        # Ranch accepts the client's counter outright from COUNTERED.
        contract = transition_contract(contract["id"], "ACCEPTED")
        assert contract["contract_status"] == "ACCEPTED"

    def test_negotiation_cycle_terms_version_increments_per_counter(self, api, ranch_manager_headers, grazing_client_headers):
        """PRD §3.8: "The contract starts in `DRAFT` `contract_status` with
        `terms_version` at 1" and "`terms_version` increments by 1 on every
        counter."

        Design: Difficulty/non_linear_state_machine/grazing_contract_negotiation_cycle
        """
        flock = create_flock(flock_name="Contract2 Ranch", species="SHEEP", baseline_headcount=800)
        contract = create_contract(flock["id"], client_org_name="City Weed Board",
                                   parcel_name="North 41")
        assert contract["terms_version"] == 1
        contract = transition_contract(contract["id"], "PROPOSED")
        for round_no in range(2):
            contract = validate_success(api.counter_grazing_contract(contract["id"], {
                "expected_grazing_contract_version": contract["version"],
                "rate_per_head_day_cents": 95 + round_no,
            }, grazing_client_headers))
            assert contract["terms_version"] == 2 + round_no
            if round_no == 0:
                contract = transition_contract(contract["id"], "PROPOSED")
        assert contract["contract_status"] == "COUNTERED"
        assert contract["rate_per_head_day_cents"] == 96


class TestContractOcc:

    def test_contract_counter_stale_version_rejected(self, api, ranch_manager_headers, grazing_client_headers):
        """PRD §2.6: "Counter-offering a grazing contract requires the request
        to carry `expected_grazing_contract_version`, holding the caller's last
        observed `version` of that contract. If the contract's current
        `version` no longer matches — for example because the ranch re-proposed
        terms after the client last read the contract — the counter is rejected
        with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), even if the contract has
        meanwhile returned to a state from which countering is otherwise
        allowed."

        Design: Corner/cross_cutting_layers/contract_counter_stale_version_rejected
        """
        flock = create_flock(flock_name="Occ2 Ranch", species="SHEEP", baseline_headcount=800)
        contract = create_contract(flock["id"], client_org_name="OCC Client",
                                   parcel_name="Parcel O")
        contract = transition_contract(contract["id"], "PROPOSED")
        stale_version = contract["version"]
        # Counter (v -> v+1), then the ranch re-proposes (v+1 -> v+2): PROPOSED again.
        validate_success(api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": stale_version,
            "rate_per_head_day_cents": 85,
        }, grazing_client_headers))
        contract = transition_contract(contract["id"], "PROPOSED")
        fresh_version = contract["version"]

        # Stale counter: contract is PROPOSED (state check would pass) but OCC fails.
        resp = api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": stale_version,
            "rate_per_head_day_cents": 80,
        }, grazing_client_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, expected_status=412)
        contract = validate_success(api.get_grazing_contract(contract["id"], grazing_client_headers))
        assert contract["terms_version"] == 2, "stale counter did not bump terms_version"

        # Fresh counter succeeds.
        contract = validate_success(api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": fresh_version,
            "rate_per_head_day_cents": 80,
        }, grazing_client_headers))
        assert contract["contract_status"] == "COUNTERED"
        assert contract["terms_version"] == 3
        assert contract["rate_per_head_day_cents"] == 80

    def test_contract_counter_as_ranch_manager_forbidden(self, api, ranch_manager_headers):
        """PRD §4: POST /api/grazing-contracts/{id}/counter is authorized for
        GrazingClient only.
        PRD §2.1: "A request whose role is not listed among the roles permitted
        on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/contract_counter_as_ranch_manager_forbidden
        """
        flock = create_flock(flock_name="Rbac3 Ranch", species="SHEEP", baseline_headcount=800)
        contract = create_contract(flock["id"], client_org_name="Client X", parcel_name="Parcel X")
        contract = transition_contract(contract["id"], "PROPOSED")
        resp = api.counter_grazing_contract(contract["id"], {
            "expected_grazing_contract_version": contract["version"],
            "rate_per_head_day_cents": 80,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
        contract = validate_success(api.get_grazing_contract(contract["id"], ranch_manager_headers))
        assert contract["contract_status"] == "PROPOSED"
        assert contract["terms_version"] == 1

    def test_grazing_contract_create_as_grazing_client_forbidden(self, api, grazing_client_headers):
        """PRD §4: POST /api/grazing-contracts is authorized for RanchManager
        only. PRD §2.1: "A request whose role is not listed among the roles
        permitted on the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)".

        Design: Corner/rbac/grazing_contract_create_as_grazing_client_forbidden
        """
        flock = create_flock(flock_name="Rbac4 Ranch", species="SHEEP", baseline_headcount=800)
        resp = api.create_grazing_contract({
            "flock_id": flock["id"], "client_org_name": "Self Serve",
            "parcel_name": "Parcel S",
            "service_window_start": "2026-09-01T00:00:00Z",
            "service_window_end": "2026-09-30T00:00:00Z",
            "rate_per_head_day_cents": 90, "min_head": 50, "max_head": 600,
            "target_cover_reduction_pct": 60.0,
        }, grazing_client_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


class TestContractWindowGates:

    def test_contract_window_closed_rejected(self, api, ranch_manager_headers, grazing_client_headers):
        """PRD §3.8: "Activation (`ACCEPTED -> ACTIVE`) is the manager's step
        and is window-gated: the logical clock must sit inside the service
        window — at or after `service_window_start` and strictly before
        `service_window_end` — else `ERR_CONTRACT_WINDOW_CLOSED` (HTTP 422)."
        PRD §3.8: "Completion (`ACTIVE -> COMPLETED`) is the manager's step
        once the logical clock has reached `service_window_end` — earlier
        completion is rejected with `ERR_CONTRACT_WINDOW_CLOSED`".

        Design: Corner/validations/contract_window_closed_rejected
        """
        flock = create_flock(flock_name="Window Ranch", species="SHEEP", baseline_headcount=800)
        window = dict(service_window_start="2026-09-01T00:00:00Z",
                      service_window_end="2026-09-30T00:00:00Z")
        # Contract A: ACCEPTED, never activated.
        contract_a = create_contract(flock["id"], client_org_name="Client A",
                                     parcel_name="Parcel A", **window)
        transition_contract(contract_a["id"], "PROPOSED")
        transition_contract(contract_a["id"], "ACCEPTED", headers=grazing_client_headers)
        # Contract B: walked to ACTIVE while the clock is in-window.
        contract_b = create_contract(flock["id"], client_org_name="Client B",
                                     parcel_name="Parcel B", **window)
        transition_contract(contract_b["id"], "PROPOSED")
        transition_contract(contract_b["id"], "ACCEPTED", headers=grazing_client_headers)
        set_clock("2026-09-02T00:00:00Z")
        transition_contract(contract_b["id"], "ACTIVE")

        # Activation before the window opens -> window closed.
        set_clock("2026-08-15T00:00:00Z")
        resp = api.transition_grazing_contract(
            contract_a["id"], {"to": "ACTIVE"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_CLOSED.value, expected_status=422)
        contract_a = validate_success(api.get_grazing_contract(contract_a["id"], ranch_manager_headers))
        assert contract_a["contract_status"] == "ACCEPTED"

        # Completion before the window ends -> window closed.
        set_clock("2026-09-15T00:00:00Z")
        resp = api.complete_grazing_contract(
            contract_b["id"], {"achieved_cover_reduction_pct": 65.0}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_CLOSED.value, expected_status=422)
        contract_b = validate_success(api.get_grazing_contract(contract_b["id"], ranch_manager_headers))
        assert contract_b["contract_status"] == "ACTIVE"


class TestContractMoves:

    def test_contract_move_requires_contract_active(self, api, range_hand_headers, grazing_client_headers, ranch_manager_headers):
        """PRD §3.2: "Planning a contract move against a contract that is not
        `ACTIVE` is likewise rejected with `ERR_CONTRACT_INVALID_STATE`."
        PRD §3.2: "for a contract move, the contract must currently be
        `ACTIVE`, otherwise `ERR_CONTRACT_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/contract_move_requires_contract_active
        """
        flock = create_flock(flock_name="Gate3 Ranch", species="SHEEP", baseline_headcount=800)
        contract = create_contract(
            flock["id"], client_org_name="Solar Farm LLC", parcel_name="Array Block 3",
            service_window_start="2026-09-01T00:00:00Z",
            service_window_end="2026-09-30T00:00:00Z",
            rate_per_head_day_cents=90, min_head=100, max_head=600,
            target_cover_reduction_pct=65.0)
        transition_contract(contract["id"], "PROPOSED")

        # Contract is PROPOSED (not ACTIVE) -> contract move creation rejected.
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "contract_id": contract["id"],
            "move_start": "2026-09-05T00:00:00Z", "move_end": "2026-09-20T00:00:00Z",
            "head_count": 300,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, expected_status=409)

        # Walk the contract to ACTIVE inside the window; the same move now books.
        transition_contract(contract["id"], "ACCEPTED", headers=grazing_client_headers)
        set_clock("2026-09-01T00:00:00Z")
        transition_contract(contract["id"], "ACTIVE")
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "contract_id": contract["id"],
            "move_start": "2026-09-05T00:00:00Z", "move_end": "2026-09-20T00:00:00Z",
            "head_count": 300,
        }, range_hand_headers)
        move = validate_success(resp, expected_status=201)
        assert move["move_status"] == "PLANNED"

    def test_contract_move_creation_gate_second_state(self, api, range_hand_headers):
        """PRD §3.2: "Planning a contract move against a contract that is not
        `ACTIVE` is likewise rejected with `ERR_CONTRACT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/contract_move_requires_contract_active
        """
        flock = create_flock(flock_name="Gate6 Ranch", species="SHEEP", baseline_headcount=800)
        # DRAFT contract (never proposed) also blocks contract moves.
        contract = create_contract(flock["id"], client_org_name="Solar Farm LLC",
                                   parcel_name="Array Block 4")
        resp = api.create_grazing_move({
            "flock_id": flock["id"], "contract_id": contract["id"],
            "move_start": "2026-09-05T00:00:00Z", "move_end": "2026-09-20T00:00:00Z",
            "head_count": 50,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, expected_status=409)

    def test_contract_move_head_range_at_activation_rejected(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "Activation (`PLANNED -> ACTIVE`) is allowed to both the
        manager and the range hand and is gated four ways: the logical clock
        must have reached `move_start` but not yet `move_end`; for a contract
        move, the contract must currently be `ACTIVE`, otherwise
        `ERR_CONTRACT_INVALID_STATE` (HTTP 409); for a contract move,
        `head_count` must lie within the contract's `min_head` to `max_head`
        inclusive, otherwise `ERR_HEAD_OUT_OF_CONTRACT_RANGE` (HTTP 422); and
        for any move, `head_count` must not exceed the flock's
        `current_headcount`, otherwise `ERR_INSUFFICIENT_HEAD` (HTTP 422)."

        Design: Corner/validations/contract_move_head_range_at_activation_rejected
        """
        flock = create_flock(flock_name="Range Ranch", species="SHEEP", baseline_headcount=800)
        contract = setup_active_contract(
            flock["id"], client_org_name="Utility ROW", parcel_name="Segment 4",
            rate_per_head_day_cents=90, min_head=50, max_head=600,
            target_cover_reduction_pct=60.0)
        # 40 head is below min_head 50; creation succeeds (gate is at activation).
        move = create_move(flock["id"], contract_id=contract["id"],
                           move_start="2026-09-05T00:00:00Z", move_end="2026-09-20T00:00:00Z",
                           head_count=40)
        set_clock("2026-09-05T00:00:00Z")
        resp = api.transition_grazing_move(move["id"], {"to": "ACTIVE"}, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_HEAD_OUT_OF_CONTRACT_RANGE.value, expected_status=422)
        move = validate_success(api.get_grazing_move(move["id"], range_hand_headers))
        assert move["move_status"] == "PLANNED"

