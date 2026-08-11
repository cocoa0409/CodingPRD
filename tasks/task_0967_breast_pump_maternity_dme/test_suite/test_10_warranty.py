"""Warranty claims: window gate, reopen budget, replacement cascade and budget."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_warranty_claim_payload,
    set_clock,
    setup_delivered_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _open_claim(api, order_id, headers, serial="SN-1", issue_type="MOTOR_FAILURE"):
    return validate_success(
        api.create_warranty_claim(
            create_warranty_claim_payload(order_id, serial_number=serial,
                                          issue_type=issue_type),
            headers,
        ), 201
    )


class TestWarrantyWindow:
    def test_claim_after_warranty_window_rejected(self, api, care_coordinator_headers):
        """PRD §3.7: "Two temporal-and-budget gates apply at creation: the current date
        must not be past the delivery date plus the warranty length
        (`ERR_WARRANTY_EXPIRED`)".

        Design: Corner/validations/warranty_expired_rejected
        """
        ctx = setup_delivered_order()  # delivered 2026-05-01, warranty_months 12
        set_clock("2027-05-02T00:00:00Z")
        res = api.create_warranty_claim(
            create_warranty_claim_payload(ctx["order"]["id"], serial_number="SN-X"),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_WARRANTY_EXPIRED, expected_status=422)


class TestReopenBudget:
    def test_reopen_loop_bounded_at_two(self, api, care_coordinator_headers,
                                        platform_admin_headers):
        """PRD §3.7: "A denied claim can be reopened by the patient or coordinator, moving
        `DENIED → OPENED` and incrementing `reopen_count` — but the reopen budget is 2, and
        a claim already reopened twice is rejected with `ERR_MAX_REOPENS_EXCEEDED`."

        Design: Corner/state_machines/warranty_reopen_cycle_and_cap
        """
        ctx = setup_delivered_order()
        claim = _open_claim(api, ctx["order"]["id"], care_coordinator_headers,
                            serial="SN-R", issue_type="SUCTION_LOSS")
        for round_no in (1, 2):
            denied = validate_success(
                api.decide_warranty_claim(
                    claim["id"],
                    {"decision": "DENIED", "resolution_notes": f"denial {round_no}"},
                    platform_admin_headers,
                ), 200
            )
            assert denied["status"] == "DENIED"
            reopened = validate_success(
                api.reopen_warranty_claim(claim["id"], care_coordinator_headers), 200
            )
            assert reopened["status"] == "OPENED"
            assert reopened["reopen_count"] == round_no

        validate_success(
            api.decide_warranty_claim(
                claim["id"], {"decision": "DENIED", "resolution_notes": "final denial"},
                platform_admin_headers,
            ), 200
        )
        res = api.reopen_warranty_claim(claim["id"], care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_MAX_REOPENS_EXCEEDED, expected_status=422)

        claim_after = validate_success(
            api.get_warranty_claim(claim["id"], care_coordinator_headers), 200
        )
        assert claim_after["reopen_count"] == 2
        assert claim_after["status"] == "DENIED"


class TestReplacementCascade:
    def test_approved_replace_resolve_creates_shipment_and_counts_replacements(
        self, api, care_coordinator_headers, platform_admin_headers,
        warehouse_operator_headers
    ):
        """PRD §3.7: "An `APPROVED_REPLACE` claim resolves with a cascade: the server
        creates a replacement `Shipment` for the claim's `pump_order_id` with
        `is_warranty_replacement` true, carrier `WARRANTY_REPLACEMENT`, a server-minted
        `tracking_number`, and status `LABEL_CREATED`; the claim's
        `replacement_shipment_id` points at it; and the order's `replacement_count`
        increments, flipping `warranty_blocked` to true once the count reaches 2 — the
        budget that gates future claims."

        Design: Difficulty/transitive_cascade/warranty_replace_cascade_to_shipment_and_order_posture
        """
        ctx = setup_delivered_order()  # no covered parts in catalog -> no schedules
        for serial in ("SN-1", "SN-2"):
            claim = _open_claim(api, ctx["order"]["id"], care_coordinator_headers,
                                serial=serial,
                                issue_type=("MOTOR_FAILURE" if serial == "SN-1"
                                            else "BATTERY_FAILURE"))
            validate_success(
                api.decide_warranty_claim(
                    claim["id"],
                    {"decision": "APPROVED_REPLACE", "resolution_notes": "replace unit"},
                    platform_admin_headers,
                ), 200
            )
            resolved = validate_success(
                api.resolve_warranty_claim(claim["id"], platform_admin_headers), 200
            )
            assert resolved["status"] == "RESOLVED"
            assert resolved["replacement_shipment_id"] is not None

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["replacement_count"] == 2
        assert order["warranty_blocked"] is True

        data, meta = validate_paginated(
            api.list_shipments(warehouse_operator_headers,
                               params={"pump_order_id": ctx["order"]["id"]})
        )
        assert meta["total_count"] == 3
        replacements = [s for s in data if s["is_warranty_replacement"]]
        assert len(replacements) == 2

    def test_third_claim_blocked_once_replacement_budget_exhausted(
        self, api, care_coordinator_headers, platform_admin_headers
    ):
        """PRD §3.7: "the order's `warranty_blocked` must be false — once an order's
        `replacement_count` has reached the replacement budget of 2, no further warranty
        claims open against it (`ERR_WARRANTY_REPLACEMENT_EXHAUSTED`)."

        Design: Difficulty/transitive_cascade/warranty_replace_cascade_to_shipment_and_order_posture
        """
        ctx = setup_delivered_order()
        for serial in ("SN-1", "SN-2"):
            claim = _open_claim(api, ctx["order"]["id"], care_coordinator_headers,
                                serial=serial)
            validate_success(
                api.decide_warranty_claim(
                    claim["id"],
                    {"decision": "APPROVED_REPLACE", "resolution_notes": "replace unit"},
                    platform_admin_headers,
                ), 200
            )
            validate_success(
                api.resolve_warranty_claim(claim["id"], platform_admin_headers), 200
            )

        res = api.create_warranty_claim(
            create_warranty_claim_payload(ctx["order"]["id"], serial_number="SN-3",
                                          issue_type="SUCTION_LOSS"),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_WARRANTY_REPLACEMENT_EXHAUSTED,
                       expected_status=422)
