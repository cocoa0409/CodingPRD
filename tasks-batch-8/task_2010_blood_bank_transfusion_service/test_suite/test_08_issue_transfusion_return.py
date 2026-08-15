"""Issuing, bedside transfusion windows, the thirty-minute return rule, and
emergency-release obligations."""
from test_helpers import (
    ApiErrorId,
    get_issue,
    get_order,
    get_success_data,
    get_unit,
    issue_all,
    list_wastage,
    make_compatible_crossmatch,
    make_emergency_issue,
    make_issue,
    make_stock,
    make_typed_patient,
    make_verified_order,
    receive_unit_descriptor,
    return_issue_payload,
    set_clock,
    setup_emergency_order_untyped,
    setup_order_with_reserved_units,
    validate_error,
    validate_paginated,
    validate_success,
    expire_patient_typing,
    TECH_A,
    TECH_B,
    DOC_1,
    DOC_2,
    api_client,
)


class TestThirtyMinuteBoundary:
    def _setup_two_issued_units(self, api):
        ctx = setup_order_with_reserved_units(
            num_units=2, units_requested=2, mrn="M-9020",
            unit_numbers=["U-501", "U-502"])
        issue_all(ctx)
        return ctx

    def test_return_at_exactly_thirty_minutes_restocks(self, api):
        """PRD §3.5: "when the return arrives at or before thirty minutes after
        `issued_at` with the seal intact and no temperature excursion, the
        disposition is `RESTOCKED` — the boundary is inclusive, so exactly thirty
        minutes and zero seconds restocks while thirty minutes and one second
        discards."

        Design: Difficulty/boundary_precision_check/return_thirty_minute_boundary
        """
        ctx = self._setup_two_issued_units(api)
        set_clock("2026-08-10T09:30:00Z")
        returned = validate_success(api.return_issue(
            ctx["issues"]["U-501"]["id"], return_issue_payload(True, False), TECH_A))
        assert returned["return_disposition"] == "RESTOCKED", (
            "exactly 30m00s is inside the inclusive boundary"
        )
        assert get_unit(ctx["units"]["U-501"]["id"])["status"] == "AVAILABLE"

    def test_return_at_thirty_minutes_one_second_discards(self, api):
        """PRD §3.5: "the boundary is inclusive, so exactly thirty minutes and zero
        seconds restocks while thirty minutes and one second discards."
        PRD §3.5: "Either discard disposition moves the unit to `DISCARDED` and
        writes a wastage record with reason `RETURNED_OVER_30MIN` or
        `RETURNED_COMPROMISED` as applicable, recomputing posture and the rolling
        wastage rate."

        Design: Difficulty/boundary_precision_check/return_thirty_minute_boundary
        """
        ctx = self._setup_two_issued_units(api)
        set_clock("2026-08-10T09:30:01Z")
        returned = validate_success(api.return_issue(
            ctx["issues"]["U-502"]["id"], return_issue_payload(True, False), TECH_A))
        assert returned["return_disposition"] == "DISCARDED_OVER_30MIN", (
            "one second past the boundary flips the outcome"
        )
        assert get_unit(ctx["units"]["U-502"]["id"])["status"] == "DISCARDED"
        records = list_wastage({"unit_id": ctx["units"]["U-502"]["id"]})
        assert len(records) == 1
        assert records[0]["reason"] == "RETURNED_OVER_30MIN"


class TestIssueRestockCycle:
    def test_restock_reverts_order_and_keeps_crossmatch_consumed(self, api):
        """PRD §3.5: "A `RESTOCKED` return moves the unit from `ISSUED` back to
        `AVAILABLE` and recomputes posture — pointedly, the consumed crossmatch is
        not revived, remaining `CONSUMED`."
        PRD §3.3: "a return or stop that drops fulfillment below the requested
        count reverts `PARTIALLY_ISSUED` to `AWAITING_CROSSMATCH`"

        Design: Difficulty/non_linear_state_machine/blood_unit_issue_return_restock_cycle
        """
        ctx = setup_order_with_reserved_units(mrn="M-9010", unit_numbers=["U-100"])
        issue_all(ctx)
        set_clock("2026-08-10T09:20:00Z")
        returned = validate_success(api.return_issue(
            ctx["issues"]["U-100"]["id"], return_issue_payload(True, False), TECH_A))
        assert returned["return_disposition"] == "RESTOCKED", "20 minutes <= 30"
        assert get_unit(ctx["units"]["U-100"]["id"])["status"] == "AVAILABLE"
        assert get_success_data(
            api.get_crossmatch(ctx["crossmatches"]["U-100"]["id"], TECH_A)
        )["status"] == "CONSUMED", "the restock never revives the crossmatch"
        assert get_order(ctx["order"]["id"])["status"] == "AWAITING_CROSSMATCH", (
            "the order bubbles backward once its consumed slot is lost"
        )

    def test_unit_cycles_twice_with_version_increment_per_hop(self, api):
        """PRD §2.5: "**`version` (integer):** a system-managed integer that
        increments by one on every mutation, available for optimistic concurrency
        control where §2.8 declares it."
        PRD §2.11: "Each such automatic reconciliation mutates the affected
        resource normally, refreshing its `updated_at` and incrementing its
        `version`."

        Design: Difficulty/non_linear_state_machine/blood_unit_issue_return_restock_cycle
        """
        ctx = setup_order_with_reserved_units(mrn="M-9010", unit_numbers=["U-100"])
        unit_id = ctx["units"]["U-100"]["id"]
        v_after_release = ctx["units"]["U-100"]["version"]

        issue_all(ctx)  # reserve (xm COMPATIBLE) happened in setup, then issue
        assert get_unit(unit_id)["version"] == v_after_release + 2, (
            "reserve then issue: two more mutations"
        )
        set_clock("2026-08-10T09:20:00Z")
        validate_success(api.return_issue(ctx["issues"]["U-100"]["id"],
                                          return_issue_payload(True, False), TECH_A))
        assert get_unit(unit_id)["version"] == v_after_release + 3, "the restock"

        # Second lap: a fresh order takes the same physical unit around the loop.
        order2 = make_verified_order(ctx["patient"]["id"], product_type="RBC",
                                     units_requested=1)
        xm2 = make_compatible_crossmatch(order2["id"], unit_id)
        assert get_unit(unit_id)["version"] == v_after_release + 4, "re-reserve"
        assert xm2["status"] == "COMPATIBLE"
        issue2 = make_issue(order2["id"], unit_id)
        assert issue2["status"] == "ISSUED"
        final = get_unit(unit_id)
        assert final["status"] == "ISSUED", "the same unit completes the loop twice"
        assert final["version"] == v_after_release + 5


class TestIssueStateGate:
    def _setup_held_order(self, api):
        stock = make_stock([
            receive_unit_descriptor("U-401", donor_id="D-800", lot_number="LOT-8"),
            receive_unit_descriptor("U-402", abo_type="B", donor_id="D-801",
                                    lot_number="LOT-8"),
        ])
        patient, ts = make_typed_patient(mrn="M-9016", full_name="Pat Sixteen",
                                         date_of_birth="1978-06-30")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = make_compatible_crossmatch(order["id"], stock["units"]["U-401"]["id"])
        ctx = {"supplier": stock["supplier"], "units": stock["units"],
               "patient": patient, "ts": ts, "order": order,
               "crossmatches": {"U-401": xm}}
        expire_patient_typing(ctx)  # sweep past the T&S expiry -> ON_HOLD
        assert ctx["order"]["status"] == "ON_HOLD"
        return ctx

    def test_issue_on_held_order_state_error_wins(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline, and
        when several rules are violated at once the earliest stage in this order
        wins."
        PRD §3.5: "The order must be `READY` or `PARTIALLY_ISSUED` — or
        `AWAITING_CROSSMATCH` when the issue is an emergency release — else
        `ERR_ORDER_NOT_ISSUABLE` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_held_order_issue
        """
        ctx = self._setup_held_order(api)
        # U-402 (B NEG) is ABO-incompatible for the A POS patient AND the order is
        # ON_HOLD: the from-state check (stage seven) precedes unit compatibility.
        resp = api.create_issue_record(
            {"order_id": ctx["order"]["id"],
             "unit_id": ctx["units"]["U-402"]["id"],
             "verified_by_user_id": "tech-b"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ISSUABLE)
        assert get_unit(ctx["units"]["U-402"]["id"])["status"] == "AVAILABLE", (
            "no side effects fire when the state gate rejects"
        )

    def test_issue_on_held_order_with_compatible_unit(self, api):
        """PRD §3.5: "The order must be `READY` or `PARTIALLY_ISSUED` — or
        `AWAITING_CROSSMATCH` when the issue is an emergency release — else
        `ERR_ORDER_NOT_ISSUABLE` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_held_order_issue
        """
        ctx = self._setup_held_order(api)
        # U-401 (O NEG) is compatible and back on the shelf after the sweep; only
        # the order-state rule fails — the same 409 in isolation.
        resp = api.create_issue_record(
            {"order_id": ctx["order"]["id"],
             "unit_id": ctx["units"]["U-401"]["id"],
             "verified_by_user_id": "tech-b"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ISSUABLE)


class TestBedsideWindow:
    def test_issue_start_after_4h_window_lapsed(self, api):
        """PRD §3.5: "Starting a transfusion requires the issue to be in `ISSUED`
        (`ERR_ISSUE_NOT_STARTABLE`) and the current time to be no later than four
        hours after `issued_at` — exactly four hours is allowed, anything later is
        rejected with `ERR_TRANSFUSION_START_WINDOW_LAPSED` (HTTP 409)."

        Design: Corner/state_machines/issue_start_after_4h_window_lapsed
        """
        ctx = setup_order_with_reserved_units(mrn="M-2003", unit_numbers=["U-100"])
        issue_all(ctx)
        issue = ctx["issues"]["U-100"]
        set_clock("2026-08-10T13:00:01Z")  # issued 09:00 + 4h = 13:00:00
        resp = api.start_transfusion(issue["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_TRANSFUSION_START_WINDOW_LAPSED)
        assert get_issue(issue["id"])["status"] == "ISSUED"


class TestEmergencyReleaseRules:
    def test_error_emergency_justification_required(self, api):
        """PRD §3.5: "every emergency release demands an `emergency_justification`
        of at least twenty characters, else `ERR_EMERGENCY_JUSTIFICATION_REQUIRED`
        (HTTP 422)."

        Design: Corner/errors/error_emergency_justification_required
        """
        ctx = setup_emergency_order_untyped(mrn="M-4001")
        unit = ctx["units"]["U-100"]
        resp = api.create_issue_record(
            {"order_id": ctx["order"]["id"], "unit_id": unit["id"],
             "verified_by_user_id": "tech-b", "is_emergency_release": True,
             "emergency_justification": "short"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_JUSTIFICATION_REQUIRED)
        assert get_unit(unit["id"])["status"] == "AVAILABLE"
        _data, meta = validate_paginated(api.list_issue_records(
            TECH_A, params={"order_id": ctx["order"]["id"]}))
        assert meta["total_count"] == 0, "no issue record was created"

    def test_error_emergency_release_not_allowed(self, api):
        """PRD §3.5: "The **emergency-release rule** admits the
        `is_emergency_release` flag only when the order's `urgency` is `EMERGENCY`
        or the patient has an `ACTIVATED` massive transfusion protocol, else
        `ERR_EMERGENCY_RELEASE_NOT_ALLOWED` (HTTP 409)"

        Design: Corner/errors/error_emergency_release_not_allowed
        """
        stock = make_stock([receive_unit_descriptor("U-100")])
        patient, _ts = make_typed_patient(mrn="M-4002", full_name="Omar Doe",
                                          date_of_birth="1978-01-01")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1, urgency="ROUTINE")
        unit = stock["units"]["U-100"]
        resp = api.create_issue_record(
            {"order_id": order["id"], "unit_id": unit["id"],
             "verified_by_user_id": "tech-b", "is_emergency_release": True,
             "emergency_justification":
                 "emergency release requested by trauma team lead"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_RELEASE_NOT_ALLOWED)
        assert get_unit(unit["id"])["status"] == "AVAILABLE"

    def test_error_second_specimen_required(self, api):
        """PRD §3.5: "The **two-specimen rule** forbids issuing a red-cell-class
        unit whose ABO group is anything other than `O` to a patient whose
        `abo_confirmed` latch is still false — unless the issue is an emergency
        release — under `ERR_SECOND_SPECIMEN_REQUIRED` (HTTP 409)."

        Design: Corner/errors/error_second_specimen_required
        """
        stock = make_stock([
            receive_unit_descriptor("U-A1", abo_type="A", donor_id="D-520",
                                    lot_number="LOT-3"),
            receive_unit_descriptor("U-O1", abo_type="O", donor_id="D-521",
                                    lot_number="LOT-3"),
        ])
        patient, _ts = make_typed_patient(mrn="M-4003", full_name="Pia Doe",
                                          date_of_birth="1986-04-04", abo="A",
                                          rh="POS")
        assert patient["abo_confirmed"] is False, "one specimen only"
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=2)
        make_compatible_crossmatch(order["id"], stock["units"]["U-A1"]["id"])
        make_compatible_crossmatch(order["id"], stock["units"]["U-O1"]["id"])

        resp = api.create_issue_record(
            {"order_id": order["id"], "unit_id": stock["units"]["U-A1"]["id"],
             "verified_by_user_id": "tech-b"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_SECOND_SPECIMEN_REQUIRED)
        assert get_unit(stock["units"]["U-A1"]["id"])["status"] == "RESERVED"

        issue = make_issue(order["id"], stock["units"]["U-O1"]["id"])
        assert issue["status"] == "ISSUED", "group O units are exempt from the rule"


class TestEmergencyAcknowledgement:
    def _setup_emergency_release(self, api):
        ctx = setup_emergency_order_untyped(mrn="M-4004")
        issue = make_emergency_issue(ctx["order"]["id"], ctx["units"]["U-100"]["id"])
        ctx["issue"] = issue
        return ctx

    def test_error_emergency_ack_window_lapsed(self, api):
        """PRD §3.5: "The acknowledgement requires the issue to be an
        as-yet-unacknowledged emergency release (`ERR_ISSUE_NOT_ACKNOWLEDGABLE`),
        requires the caller to be the very physician recorded as the order's
        `ordering_physician_id` (`ERR_NOT_ORDERING_PHYSICIAN`, HTTP 403), and is
        refused after the window with `ERR_EMERGENCY_ACK_WINDOW_LAPSED` (HTTP 409)"
        PRD §3.5: "An issue whose `is_emergency_release` is true, whose
        `physician_acknowledged_at` remains null, and whose twenty-four-hour mark
        has passed reads `ack_overdue` as true."

        Design: Corner/errors/error_emergency_ack_window_lapsed
        """
        ctx = self._setup_emergency_release(api)
        set_clock("2026-08-11T10:00:00Z")  # issued 09:00 + 25h
        resp = api.acknowledge_emergency(ctx["issue"]["id"], DOC_1)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_ACK_WINDOW_LAPSED)
        issue = get_issue(ctx["issue"]["id"])
        assert issue["ack_overdue"] is True
        assert issue["physician_acknowledged_at"] is None

    def test_ack_by_non_ordering_physician_rejected(self, api):
        """PRD §3.5: "requires the caller to be the very physician recorded as the
        order's `ordering_physician_id` (`ERR_NOT_ORDERING_PHYSICIAN`, HTTP 403),
        and is refused after the window with `ERR_EMERGENCY_ACK_WINDOW_LAPSED`
        (HTTP 409); success stamps `physician_acknowledged_at`."

        Design: Corner/rbac/ack_by_non_ordering_physician_rejected
        """
        ctx = self._setup_emergency_release(api)
        resp = api.acknowledge_emergency(ctx["issue"]["id"], DOC_2)
        validate_error(resp, ApiErrorId.ERR_NOT_ORDERING_PHYSICIAN)

        acked = validate_success(
            api.acknowledge_emergency(ctx["issue"]["id"], DOC_1))
        assert acked["physician_acknowledged_at"] == ctx["issue"]["issued_at"], (
            "no clock movement intervened, so the stamp equals issued_at"
        )


class TestIssueSegregation:
    def test_sod_issue_verifier_equals_issuer_rejected(self, api):
        """PRD §3.5: "A `BloodBankTechnologist` creates one with an `order_id` and
        a `verified_by_user_id` naming a second technologist who performs an
        independent verification — that identifier must differ from the caller's
        `X-User-ID`, the segregation rule on issuing, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_issue_verifier_equals_issuer_rejected
        """
        ctx = setup_order_with_reserved_units(mrn="M-5003", unit_numbers=["U-100"])
        unit = ctx["units"]["U-100"]
        resp = api.create_issue_record(
            {"order_id": ctx["order"]["id"], "unit_id": unit["id"],
             "verified_by_user_id": "tech-a"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_unit(unit["id"])["status"] == "RESERVED"
        _data, meta = validate_paginated(api.list_issue_records(
            TECH_A, params={"order_id": ctx["order"]["id"]}))
        assert meta["total_count"] == 0
