"""Validation-priority conflicts, cross-entity state dependencies, temporal overlap,
and compensating invariants."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_bound_account, setup_plate_violation, create_account, create_vehicle,
    create_transponder, create_plaza, credit_account, bind_transponder,
    record_transponder_read, record_plate_read, price,
    create_transponder_binding_payload, create_hov_window_payload, create_reprice_payload,
    api_client, TEST_USERS, make_account_holder_headers, NON_EXISTENT_UUID,
)

OP = TEST_USERS["toll_operator_headers"]


class TestValidationPriorityConflicts:
    def test_account_not_active_beats_binding_overlap(self, api):
        """PRD §2.9: "The business-rule band (priorities 6 through 16) ... is: binding
        ownership match (`ERR_OWNERSHIP_MISMATCH`), owning-account-active on bind
        (`ERR_ACCOUNT_NOT_ACTIVE`), plate-registration eligibility
        (`ERR_PLATE_UNREGISTERED`), binding-interval overlap (`ERR_BINDING_OVERLAP`)".

        Design: Difficulty/priority_pair_validation_conflict/account_not_active_beats_binding_overlap
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="PP1V")
        tp_a = create_transponder(account["id"], "TP-PP1A")
        bind_transponder(account["id"], tp_a["id"], vehicle["id"], vehicle["version"],
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-12-31T00:00:00Z")
        veh2 = validate_success(api.get_vehicle(vehicle["id"],
                                make_account_holder_headers(account["id"])), 200)
        tp_b = create_transponder(account["id"], "TP-PP1B")
        api.suspend_account(account["id"], OP)
        # Bind targets a SUSPENDED account (P7) AND overlaps an active binding interval (P9).
        payload = create_transponder_binding_payload(
            tp_b["id"], vehicle["id"], "2026-06-01T00:00:00Z", veh2["version"],
            effective_to="2026-08-01T00:00:00Z")
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE", expected_status=409)

    def test_not_found_beats_insufficient_balance_on_pay(self, api):
        """PRD §2.7: "Identifiers are validated left to right in the order they appear,
        and the first one that does not resolve causes immediate rejection with
        `ERR_NOT_FOUND` (HTTP 404). This ordering applies uniformly: existence is
        established before any state, ownership, or business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_insufficient_balance_on_pay
        """
        account = create_account()  # zero balance, no violation
        res = api.pay_violation("00000000-0000-4000-8000-000000000000",
                                make_account_holder_headers(account["id"]))
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_pay_nonexistent_violation_returns_404_status(self, api):
        """PRD §2.7: "existence is established before any state, ownership, or business
        rule is evaluated." PRD §2.9: "(3) existence — every path and body foreign-key id
        resolves, validated left to right, else `ERR_NOT_FOUND` (404)".

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_insufficient_balance_on_pay
        """
        # Underfunded account (zero balance) paying a missing violation id: existence is
        # checked first, so the result is the 404 existence error, never the 402 fiscal one.
        account = create_account()
        res = api.pay_violation("00000000-0000-4000-8000-000000000000",
                                make_account_holder_headers(account["id"]))
        assert res.status_code == 404, f"expected 404, got {res.status_code}"
        validate_error(res, "ERR_NOT_FOUND")

    def test_account_not_active_returns_409_status(self, api):
        """PRD §2.9: "(2) role authorization ... (5) state validity ... (6) through (16)
        the domain-specific business rules described throughout §3, in the order listed
        below". PRD §3.4: "binding under a `DELINQUENT`, `SUSPENDED`, or `CLOSED` account
        is rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/account_not_active_beats_binding_overlap
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="PP1X")
        tp_a = create_transponder(account["id"], "TP-PP1XA")
        bind_transponder(account["id"], tp_a["id"], vehicle["id"], vehicle["version"],
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-12-31T00:00:00Z")
        veh2 = validate_success(api.get_vehicle(vehicle["id"],
                                make_account_holder_headers(account["id"])), 200)
        tp_b = create_transponder(account["id"], "TP-PP1XB")
        api.suspend_account(account["id"], OP)
        payload = create_transponder_binding_payload(
            tp_b["id"], vehicle["id"], "2026-06-01T00:00:00Z", veh2["version"],
            effective_to="2026-08-01T00:00:00Z")
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        # ERR_ACCOUNT_NOT_ACTIVE carries HTTP 409 (not the would-be overlap's status).
        assert res.status_code == 409, f"expected 409, got {res.status_code}"
        validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")


class TestCrossEntityStateDependency:
    def test_binding_requires_account_active(self, api):
        """PRD §3.4: "The owning account must be `ACTIVE`; binding under a `DELINQUENT`,
        `SUSPENDED`, or `CLOSED` account is rejected with `ERR_ACCOUNT_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/binding_requires_account_active
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="CE1V")
        tp = create_transponder(account["id"], "TP-CE1")
        api.suspend_account(account["id"], OP)
        payload = create_transponder_binding_payload(
            tp["id"], vehicle["id"], "2026-01-01T00:00:00Z", vehicle["version"])
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")

    def test_binding_under_delinquent_account_rejected(self, api):
        """PRD §3.4: "The owning account must be `ACTIVE`; binding under a `DELINQUENT`,
        `SUSPENDED`, or `CLOSED` account is rejected with `ERR_ACCOUNT_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/binding_requires_account_active
        """
        # Drive the account to DELINQUENT via an unpaid plate violation, then attempt a
        # bind of a fresh transponder onto a fresh REGISTERED vehicle of the same account.
        account, _, _, _, _ = setup_plate_violation(plate_number="CE1D")
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["status"] == "DELINQUENT"
        vehicle = create_vehicle(account["id"], plate_number="CE1DV")
        tp = create_transponder(account["id"], "TP-CE1D")
        payload = create_transponder_binding_payload(
            tp["id"], vehicle["id"], "2026-01-01T00:00:00Z", vehicle["version"])
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")

    def test_transponder_price_requires_vehicle_registered(self, api):
        """PRD §3.6: "a `PLATE`-read transaction may price at the transponder rate only
        if its matched vehicle's `registration_status` is `REGISTERED`. A `LAPSED`
        vehicle cannot price at transponder rate and is rejected with
        `ERR_PLATE_UNREGISTERED` (HTTP 409), forcing the plate-rate / violation path."

        Design: Difficulty/cross_entity_state_dependency/transponder_price_requires_vehicle_registered
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="CE2V")
        api.lapse_vehicle_registration(vehicle["id"], OP)
        plaza = create_plaza(base_rate_cents=400)
        txn = record_plate_read(plaza["id"], "CE2V", "NY", "2026-02-10T08:00:00Z",
                                is_peak=False, declared_axles=2)
        res = api.price_toll_transaction(txn["id"], OP)
        validate_error(res, "ERR_PLATE_UNREGISTERED")

    def test_registered_vehicle_plate_read_prices_successfully(self, api):
        """PRD §3.6: "a `PLATE`-read transaction may price at the transponder rate only
        if its matched vehicle's `registration_status` is `REGISTERED`."

        Design: Difficulty/cross_entity_state_dependency/transponder_price_requires_vehicle_registered
        """
        # A REGISTERED vehicle's plate read prices (the inclusive side of the rule):
        # the plate rate applies and pricing succeeds rather than being rejected.
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="CE2R")
        plaza = create_plaza(base_rate_cents=400, plate_surcharge_bps=5000)
        txn = record_plate_read(plaza["id"], "CE2R", "NY", "2026-02-10T08:00:00Z",
                                is_peak=False, declared_axles=2)
        priced = validate_success(api.price_toll_transaction(txn["id"], OP), 200)
        assert priced["pricing_status"] == "PRICED"


class TestResourceTemporalOverlap:
    def test_binding_overlap_rejected_on_vehicle(self, api):
        """PRD §3.4: "The proposed binding interval, the half-open span from
        `effective_from` up to but not including `effective_to`, must not overlap any
        `ACTIVE` binding interval already on the same vehicle ... but any true overlap is
        rejected with `ERR_BINDING_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/binding_half_open_overlap_on_vehicle
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="OV1V")
        tp_a = create_transponder(account["id"], "TP-OV1A")
        bind_transponder(account["id"], tp_a["id"], vehicle["id"], vehicle["version"],
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-06-01T00:00:00Z")
        veh2 = validate_success(api.get_vehicle(vehicle["id"],
                                make_account_holder_headers(account["id"])), 200)
        tp_b = create_transponder(account["id"], "TP-OV1B")
        payload = create_transponder_binding_payload(
            tp_b["id"], vehicle["id"], "2026-03-01T00:00:00Z", veh2["version"],
            effective_to="2026-09-01T00:00:00Z")
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        validate_error(res, "ERR_BINDING_OVERLAP")

    def test_binding_abutting_at_endpoint_is_allowed(self, api):
        """PRD §3.4: "because the intervals are half-open, two bindings that merely touch
        at a shared endpoint (one's `effective_to` equal to the next's `effective_from`)
        are allowed, but any true overlap is rejected with `ERR_BINDING_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/binding_half_open_overlap_on_vehicle
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="OV1A")
        tp_a = create_transponder(account["id"], "TP-OV1AA")
        bind_transponder(account["id"], tp_a["id"], vehicle["id"], vehicle["version"],
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-06-01T00:00:00Z")
        veh2 = validate_success(api.get_vehicle(vehicle["id"],
                                make_account_holder_headers(account["id"])), 200)
        tp_b = create_transponder(account["id"], "TP-OV1AB")
        # New binding begins exactly at the prior interval's effective_to (abutting).
        payload = create_transponder_binding_payload(
            tp_b["id"], vehicle["id"], "2026-06-01T00:00:00Z", veh2["version"],
            effective_to="2026-09-01T00:00:00Z")
        res = api.create_transponder_binding(payload, make_account_holder_headers(account["id"]))
        binding = validate_success(res, 201)
        assert binding["status"] == "ACTIVE"

    def test_hov_window_buffered_overlap_rejected(self, api):
        """PRD §3.5: "must not even abut one within a 15-minute buffer: if the gap
        between the new window and any existing declared window on that vehicle is less
        than 15 minutes, the declaration is rejected with `ERR_HOV_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hov_window_buffered_overlap_on_vehicle
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="OV2V", hov_capable=True)
        holder = make_account_holder_headers(account["id"])
        api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T07:00:00Z", "2026-02-09T10:00:00Z", 3), holder)
        # New window starts only 10 minutes after the prior window ends.
        res = api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T10:10:00Z", "2026-02-09T12:00:00Z", 3), holder)
        validate_error(res, "ERR_HOV_WINDOW_OVERLAP")

    def test_hov_window_beyond_buffer_is_allowed(self, api):
        """PRD §3.5: "if the gap between the new window and any existing declared window
        on that vehicle is less than 15 minutes, the declaration is rejected with
        `ERR_HOV_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hov_window_buffered_overlap_on_vehicle
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="OV2A", hov_capable=True)
        holder = make_account_holder_headers(account["id"])
        api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T07:00:00Z", "2026-02-09T10:00:00Z", 3), holder)
        # New window starts 20 minutes after the prior ends (gap >= 15 min) -> allowed.
        res = api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T10:20:00Z", "2026-02-09T12:00:00Z", 3), holder)
        window = validate_success(res, 201)
        assert window["status"] == "DECLARED"


class TestCompensatingInvariants:
    def test_reprice_balance_conservation(self, api):
        """PRD §3.7: "Repricing recomputes `toll_cents` via the same pricing formula,
        adjusts `balance_cents` by the difference between the new and the old
        `toll_cents`, appends a `TOLL_DEBIT` ledger entry for that delta, moves
        `pricing_status` from `PRICED` to `REPRICED`, and increments the transaction's
        `version` by 1."

        Design: Difficulty/compensating_invariant/reprice_balance_conservation
        """
        account, vehicle, transponder, plaza, txn = None, None, None, None, None
        account = create_account()
        credit_account(account["id"], 100000)
        vehicle = create_vehicle(account["id"], plate_number="IV1V", axle_count=3)
        transponder = create_transponder(account["id"], "TP-IV1")
        bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
        plaza = create_plaza(base_rate_cents=400, axle_surcharge_cents=150,
                            peak_multiplier_bps=2500)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-11T08:00:00Z",
                                      is_peak=True, declared_axles=2)
        priced = price(txn["id"])  # gross/toll 500
        reprice = create_reprice_payload(3, True, priced["version"])
        repriced = validate_success(api.reprice_toll_transaction(txn["id"], reprice, OP), 200)
        # 3 axles peak: (400 + 150)*1.25 = 687.5 -> 688
        assert repriced["toll_cents"] == 688, f"expected 688, got {repriced['toll_cents']}"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["balance_cents"] == 99312, f"expected 99312, got {acct['balance_cents']}"

    def test_reprice_ledger_debits_sum_to_final_toll(self, api):
        """PRD §3.7: "adjusts `balance_cents` by the difference between the new and the
        old `toll_cents`, appends a `TOLL_DEBIT` ledger entry for that delta".
        PRD §2.8: "a signed `amount_cents` (negative for debits, positive for credits)".

        Design: Difficulty/compensating_invariant/reprice_balance_conservation
        """
        account = create_account()
        credit_account(account["id"], 100000)
        vehicle = create_vehicle(account["id"], plate_number="IV1W", axle_count=3)
        transponder = create_transponder(account["id"], "TP-IV1W")
        bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
        plaza = create_plaza(base_rate_cents=400, axle_surcharge_cents=150,
                            peak_multiplier_bps=2500)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-11T08:00:00Z",
                                      is_peak=True, declared_axles=2)
        priced = price(txn["id"])
        api.reprice_toll_transaction(txn["id"], create_reprice_payload(3, True, priced["version"]), OP)
        entries = validate_success(
            api.list_ledger_entries(OP, params={"ref_transaction_id": txn["id"]}), 200)
        toll_debit_sum = sum(e["amount_cents"] for e in entries if e["entry_type"] == "TOLL_DEBIT")
        assert toll_debit_sum == -688, f"expected TOLL_DEBIT sum -688, got {toll_debit_sum}"

    def test_violation_outstanding_fines_conservation(self, api):
        """PRD §3.8: "Payment debits `balance_cents` by `fine_total_cents`, appends a
        `VIOLATION_SETTLE` ledger entry, moves the violation to the terminal `SETTLED`,
        and cascades: the linked transaction moves from `IN_VIOLATION` to `SETTLED`,
        `outstanding_fines_cents` is recomputed, and if it is now 0 and the account is
        `DELINQUENT`, the account returns to `ACTIVE`."

        Design: Difficulty/compensating_invariant/violation_outstanding_fines_conservation
        """
        account, vehicle, plaza, txn, viol = setup_plate_violation(
            account_overrides={}, plate_number="IV2V")
        credit_account(account["id"], 10000)
        # fine_total = toll 750 + penalty 2500 = 3250
        paid = validate_success(api.pay_violation(viol["id"],
                                make_account_holder_headers(account["id"])), 200)
        assert paid["settlement_status"] == "SETTLED"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["outstanding_fines_cents"] == 0
        assert acct["balance_cents"] == 6750, f"expected 6750, got {acct['balance_cents']}"

    def test_violation_outstanding_rises_on_issue(self, api):
        """PRD §3.1: "A read-only `outstanding_fines_cents` on the account is the sum of
        `fine_total_cents` over every `Violation` of that account whose settlement status
        is `ASSESSED` or `CONTESTED`". PRD §3.8: "carries the underlying toll into
        `toll_due_cents` (taken from the transaction's `toll_cents` at issuance)".

        Design: Difficulty/compensating_invariant/violation_outstanding_fines_conservation
        """
        account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="IV2W")
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # fine_total = 750 + 2500 = 3250
        assert acct["outstanding_fines_cents"] == 3250, \
            f"expected 3250, got {acct['outstanding_fines_cents']}"
