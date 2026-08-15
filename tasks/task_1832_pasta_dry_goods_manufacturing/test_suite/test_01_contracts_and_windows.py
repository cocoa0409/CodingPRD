"""Ingredient contracts: creation defaults, activation windows, terminal
lockout, delivery-window edges, and index-reading uniqueness."""
from test_helpers import (
    ApiErrorId,
    assert_contract,
    create_active_contract,
    create_contract_draft,
    create_contract_payload,
    create_lot_payload,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]


def test_contract_creation_applies_system_defaults(api):
    """PRD: "The contract is born in `DRAFT` with `cumulative_delivered_kg` at
    zero and the creating user's identity captured in `created_by_user_id`."
    PRD: "a `version` integer that starts at 1 and increments by exactly 1 on
    every mutation of that entity"
    PRD: "Before any client interaction the clock reads exactly
    2026-08-01T00:00:00Z."

    Design: Corner/entities/contract_creation_applies_system_defaults
    """
    resp = api.create_contract(create_contract_payload(contract_code="C-DEF"), PROC)
    data = validate_success(resp, 201)
    assert_contract(data)
    assert data["status"] == "DRAFT"
    assert data["cumulative_delivered_kg"] == 0
    assert data["version"] == 1
    assert data["created_by_user_id"] == "proc-1"
    assert data["created_at"].startswith("2026-08-01T00:00:00"), (
        f"server fields stamp from the logical clock default, got {data['created_at']!r}"
    )


def test_contract_terminal_lockout(api):
    """PRD: "a `ProcurementManager` may later close it, moving `ACTIVE` to
    `CLOSED` (terminal)"
    PRD: "then transition legality on the target resource as
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/contract_terminal_lockout
    """
    contract = create_active_contract(contract_code="C-TL")
    closed = validate_success(api.close_contract(contract["id"], PROC))
    assert closed["status"] == "CLOSED"

    resp_activate = api.activate_contract(contract["id"], PM)
    validate_error(resp_activate, ApiErrorId.ERR_INVALID_STATE)
    resp_close = api.close_contract(contract["id"], PROC)
    validate_error(resp_close, ApiErrorId.ERR_INVALID_STATE)


def test_receipt_window_and_contract_status_edges(api):
    """PRD: "a receipt against a contract that is not `ACTIVE` is rejected with
    `ERR_CONTRACT_NOT_ACTIVE`"
    PRD: "Activation refuses a window that has already lapsed —
    `effective_end` earlier than the current clock date is `ERR_INVALID_REQUEST`"
    PRD: "The delivery date must fall inside the contract's window, both
    endpoints inclusive; a date outside it is rejected with
    `ERR_CONTRACT_WINDOW_INVALID`."

    Design: Corner/validations/receipt_window_and_contract_status_edges
    """
    draft = create_contract_draft(contract_code="C-RW1")
    lapsed = create_contract_draft(contract_code="C-RW2", ingredient_type="DURUM_SEMOLINA",
                                   effective_end="2026-06-30")
    active = create_active_contract(contract_code="C-RW3", ingredient_type="RICE_FLOUR",
                                    effective_end="2026-08-31")

    resp1 = api.create_semolina_lot(create_lot_payload(draft["id"], 100.0), PROC)
    validate_error(resp1, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    resp2 = api.activate_contract(lapsed["id"], PM)
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    ok = validate_success(
        api.create_semolina_lot(create_lot_payload(active["id"], 100.0,
                                                   delivery_date="2026-08-31"), PROC), 201)
    assert ok["delivery_date"] == "2026-08-31", "delivery on effective_end is inclusive"

    resp3 = api.create_semolina_lot(create_lot_payload(active["id"], 100.0,
                                                       delivery_date="2026-09-01"), PROC)
    validate_error(resp3, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID)


def test_price_index_reading_append_only_unique_per_date(api):
    """PRD: "One reading per contract per date: a second reading for the same
    (`contract_id`, `effective_date`) pair is rejected with
    `ERR_DUPLICATE_INDEX_READING`."
    PRD: "a `PriceIndexReading` is an append-only event log entry and carries
    only `id` and `created_at` (no `updated_at`, no `version`)"

    Design: Corner/entities/price_index_reading_append_only_unique_per_date
    """
    contract = create_active_contract(contract_code="C-IMM")

    first = validate_success(
        api.create_index_reading(contract["id"],
                                 {"effective_date": "2026-08-01", "index_value": 110.0},
                                 PROC), 201)
    assert "id" in first and "created_at" in first
    assert "version" not in first, "append-only reading must not carry version"
    assert "updated_at" not in first, "append-only reading must not carry updated_at"

    dup = api.create_index_reading(contract["id"],
                                   {"effective_date": "2026-08-01", "index_value": 111.0},
                                   PROC)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_INDEX_READING)

    rows = validate_success(api.list_index_readings(contract["id"], PROC))
    assert len(rows) == 1
    assert rows[0]["effective_date"] == "2026-08-01"
    assert rows[0]["index_value"] == 110.0


class TestContractWindowClosedIntervalOverlap:
    def _setup_three_contracts(self, api):
        contract_a = create_active_contract(contract_code="C-WA", effective_end="2026-08-31")
        contract_b = create_contract_draft(contract_code="C-WB", base_price_cents_per_kg=520,
                                           effective_start="2026-08-31")
        contract_c = create_contract_draft(contract_code="C-WC", base_price_cents_per_kg=520,
                                           effective_start="2026-09-01")
        return contract_a, contract_b, contract_c

    def test_shared_endpoint_date_conflicts(self, api):
        """PRD: "Both endpoints are inclusive in that comparison, so a candidate
        whose `effective_start` equals another active contract's `effective_end`
        does conflict and is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_overlap
        """
        _, contract_b, _ = self._setup_three_contracts(api)

        resp = api.activate_contract(contract_b["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

        after = validate_success(api.get_contract(contract_b["id"], PM))
        assert after["status"] == "DRAFT", "rejected activation leaves the contract DRAFT"

    def test_first_non_overlapping_day_activates(self, api):
        """PRD: "no other `ACTIVE` contract of the same `ingredient_type` may
        have a closed delivery window intersecting this one."
        PRD: "Both endpoints are inclusive in that comparison, so a candidate
        whose `effective_start` equals another active contract's `effective_end`
        does conflict and is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_overlap
        """
        _, _, contract_c = self._setup_three_contracts(api)

        resp = api.activate_contract(contract_c["id"], PM)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE", (
            "2026-09-01 is strictly after the active window's 2026-08-31 end"
        )
