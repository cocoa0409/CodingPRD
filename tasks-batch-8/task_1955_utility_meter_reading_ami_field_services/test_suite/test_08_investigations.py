"""Tamper and theft investigations: workflow loop, back-bill, closure gates.

Covers PRD section 3.6 plus the account-lifecycle interaction of section 3.1.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_investigation_to_pending_disposition,
    capture_read_payload,
    confirm_theft_payload,
    create_billing_period_payload,
    create_field_technician_payload,
    create_meter,
    create_replacement_campaign_payload,
    create_route_payload,
    dispatch_order_to,
    enroll_payload,
    get_account,
    get_campaign,
    get_enrollment,
    get_investigation,
    get_meter,
    get_route_stops,
    get_stop,
    get_work_order,
    make_field_technician_headers,
    make_investigator_headers,
    open_investigation,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_in_progress_route,
    start_order_as,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]


def _investigation_at_pending_disposition(
    api, account_number, cycle_code, indication_type="THEFT_REPORT", opened_by="inv-001"
):
    """Account + installed meter + investigation driven to
    PENDING_DISPOSITION. Returns (account, meter, investigation)."""
    set_logical_clock("2026-08-01T00:00:00Z")
    account, meter = setup_account_with_installed_meter(
        account_number, cycle_code, service_address=f"{account_number} Rd"
    )
    inv = open_investigation(
        account["id"], meter["id"], indication_type=indication_type, opened_by=opened_by
    )
    advance_investigation_to_pending_disposition(inv["id"], opened_by)
    return account, meter, get_investigation(inv["id"])


class TestInvestigationWorkflowLoop:
    def _looped_investigation(self, api):
        account, meter = setup_account_with_installed_meter(
            "A-5002", "C11", service_address="7 Cedar Ave"
        )
        inv = open_investigation(
            account["id"], meter["id"], indication_type="USAGE_ANOMALY", opened_by="inv-101"
        )
        return account, meter, inv

    def test_investigation_revision_loop_revisits_evidence_gathering(self, api):
        """PRD section 3.6: "The investigation workflow is a supervised loop.
        From `OPEN`, the investigator begins evidence gathering
        (`EVIDENCE_GATHERING`); from there they submit a disposition
        (`PENDING_DISPOSITION`); a disposition can bounce back to
        `EVIDENCE_GATHERING` when more evidence is requested, and this
        revision loop may repeat indefinitely."

        Design: Difficulty/non_linear_state_machine/investigation_evidence_disposition_revision_loop
        """
        _account, _meter, inv = self._looped_investigation(api)
        headers = make_investigator_headers("inv-101")

        assert inv["investigation_status"] == "OPEN"
        beg = validate_success(api.begin_evidence(inv["id"], headers), 200)
        assert beg["investigation_status"] == "EVIDENCE_GATHERING"
        sub = validate_success(api.submit_disposition(inv["id"], headers), 200)
        assert sub["investigation_status"] == "PENDING_DISPOSITION"
        looped = validate_success(api.request_more_evidence(inv["id"], headers), 200)
        # the loop revisits EVIDENCE_GATHERING
        assert looped["investigation_status"] == "EVIDENCE_GATHERING"
        resub = validate_success(api.submit_disposition(inv["id"], headers), 200)
        assert resub["investigation_status"] == "PENDING_DISPOSITION"
        cleared = validate_success(api.clear_investigation(inv["id"], headers), 200)
        assert cleared["investigation_status"] == "CLEARED"

    def test_investigation_revision_loop_version_and_clear_cascade(self, api):
        """PRD section 2.5: "No resource type is exempt: all thirteen carry
        the full quartet, and any mutation — client-driven or cascaded —
        refreshes `updated_at` and increments `version` on each resource it
        touches."
        PRD section 3.6: "Clearing the investigation moves it from
        `PENDING_DISPOSITION` to `CLEARED` and returns the meter's
        `tamper_status` from `SUSPECTED` to `NONE`, lifting the
        evidence-preservation hold."

        Design: Difficulty/non_linear_state_machine/investigation_evidence_disposition_revision_loop
        """
        account, meter, inv = self._looped_investigation(api)
        headers = make_investigator_headers("inv-101")
        # opening the investigation flipped the meter to SUSPECTED
        assert get_meter(meter["id"])["tamper_status"] == "SUSPECTED"

        validate_success(api.begin_evidence(inv["id"], headers), 200)
        validate_success(api.submit_disposition(inv["id"], headers), 200)
        validate_success(api.request_more_evidence(inv["id"], headers), 200)
        validate_success(api.submit_disposition(inv["id"], headers), 200)
        cleared = validate_success(api.clear_investigation(inv["id"], headers), 200)
        # create v1 + begin v2 + submit v3 + more-evidence v4 + submit v5 + clear v6
        assert cleared["version"] == 6
        assert get_meter(meter["id"])["tamper_status"] == "NONE"


class TestConfirmTheft:
    def test_backbill_per_month_rounding_pinned(self, api):
        """PRD section 3.6: "The back-bill is then computed with a pinned
        rounding order: each month's charge is that month's estimated kWh
        multiplied by eleven and a quarter cents, rounded half-up to a whole
        cent — per-month rounding happens before any summation, and summing
        first and rounding once produces a different result and is rejected;
        the subtotal is the sum of those per-month charges; the penalty is one
        quarter of the subtotal, rounded half-up to a whole cent; and the
        total back-bill, stored on `backbill_cents`, is the subtotal plus the
        penalty."

        Design: Difficulty/combinatorial_formula/backbill_per_month_rounding_order_pinned
        """
        _account, _meter, inv = _investigation_at_pending_disposition(
            api, "A-4001", "C10", opened_by="inv-001"
        )
        confirmed = validate_success(
            api.confirm_theft(
                inv["id"],
                confirm_theft_payload(3, [333, 333, 333]),
                make_investigator_headers("inv-001"),
            ),
            200,
        )
        # per-month: round_half_up(333 * 11.25) = 3746; subtotal 11238;
        # penalty round_half_up(11238 * 0.25) = 2810; total 14048.
        assert confirmed["backbill_cents"] == 14048
        assert confirmed["backbill_cents"] != 14049  # sum-then-round would give 14049
        assert confirmed["investigation_status"] == "CONFIRMED_THEFT"

    def test_confirm_theft_cascade_effects(self, api):
        """PRD section 3.6: "Confirmation then cascades: an `EXCHANGE` work
        order is auto-created in `OPEN` for the account and meter with
        `exchange_work_order_id` recording it; the meter's `tamper_status`
        moves from `SUSPECTED` to `CONFIRMED`; and the account moves from
        `ACTIVE` to `SUSPENDED` with the full pending-stop cancellation
        cascade of §3.1."

        Design: Difficulty/combinatorial_formula/backbill_per_month_rounding_order_pinned
        """
        account, meter, inv = _investigation_at_pending_disposition(
            api, "A-4001", "C10", opened_by="inv-001"
        )
        confirmed = validate_success(
            api.confirm_theft(
                inv["id"],
                confirm_theft_payload(3, [333, 333, 333]),
                make_investigator_headers("inv-001"),
            ),
            200,
        )
        exchange_wo_id = confirmed["exchange_work_order_id"]
        assert exchange_wo_id is not None
        exchange_wo = get_work_order(exchange_wo_id)
        assert exchange_wo["work_order_type"] == "EXCHANGE"
        assert exchange_wo["work_order_status"] == "OPEN"
        assert exchange_wo["meter_id"] == meter["id"]

        assert get_meter(meter["id"])["tamper_status"] == "CONFIRMED"
        assert get_account(account["id"])["account_status"] == "SUSPENDED"


class TestInvestigationGates:
    def test_investigation_duplicate_per_meter_rejected(self, api, investigator_headers):
        """PRD section 3.6: "Only one non-terminal investigation may exist per
        meter — a manual open while another investigation for the meter sits
        in any state short of `CLOSED` fails with
        `ERR_INVESTIGATION_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/investigation_duplicate_per_meter_rejected
        """
        account, meter = setup_account_with_installed_meter(
            "C-0078", "C78", service_address="78 Dup Rd"
        )
        open_investigation(
            account["id"], meter["id"], indication_type="THEFT_REPORT", opened_by="inv-401"
        )
        res = api.create_investigation(
            {
                "service_account_id": account["id"],
                "meter_id": meter["id"],
                "indication_type": "USAGE_ANOMALY",
            },
            make_investigator_headers("inv-401"),
        )
        validate_error(res, ApiErrorId.ERR_INVESTIGATION_ALREADY_OPEN.value, 409)

    def test_backbill_array_length_mismatch_rejected(self, api):
        """PRD section 3.6: "The caller supplies `theft_window_months` — the
        number of months of unbilled usage claimed — and
        `monthly_estimated_kwh`, an array of per-month estimated kWh whose
        length must equal `theft_window_months` exactly, failing which the
        request is rejected with `ERR_BACKBILL_INPUT_MISMATCH` (HTTP 422) at
        body-validation time."

        Design: Corner/validations/backbill_array_length_mismatch_rejected
        """
        _account, _meter, inv = _investigation_at_pending_disposition(
            api, "C-0079", "C79", opened_by="inv-501"
        )
        res = api.confirm_theft(
            inv["id"],
            confirm_theft_payload(2, [100, 200, 300]),
            make_investigator_headers("inv-501"),
        )
        validate_error(res, ApiErrorId.ERR_BACKBILL_INPUT_MISMATCH.value, 422)
        after = get_investigation(inv["id"])
        assert after["investigation_status"] == "PENDING_DISPOSITION"
        assert after["backbill_cents"] is None


class TestInvestigationClosure:
    def test_investigation_close_requires_verified_exchange(self, api):
        """PRD section 3.6: "Closing from `CONFIRMED_THEFT` carries a second
        gate: the auto-created exchange work order recorded on
        `exchange_work_order_id` must have reached `VERIFIED`, failing which
        the close is rejected with `ERR_EXCHANGE_NOT_VERIFIED` (HTTP 409). A
        successful close stamps `closed_by_user_id` and lands the
        investigation in the terminal `CLOSED` state."

        Design: Corner/validations/investigation_close_requires_verified_exchange
        """
        account, meter, inv = _investigation_at_pending_disposition(
            api, "C-0101", "CB2", opened_by="inv-801"
        )
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Close Tech"), ADMIN
            ),
            201,
        )
        m2 = create_meter("SN-CX-2", "HANDHELD")
        confirmed = validate_success(
            api.confirm_theft(
                inv["id"],
                confirm_theft_payload(1, [500]),
                make_investigator_headers("inv-801"),
            ),
            200,
        )
        # charge round(500*11.25)=5625; penalty round(5625*0.25)=1406
        assert confirmed["backbill_cents"] == 7031
        xwo_id = confirmed["exchange_work_order_id"]

        dispatch_order_to(xwo_id, tech["id"])
        start_order_as(xwo_id, tech["id"])
        validate_success(
            api.complete_work_order(
                xwo_id,
                {
                    "new_meter_id": m2["id"],
                    "old_final_read_value": 8000,
                    "new_initial_read_value": 0,
                },
                make_field_technician_headers(tech["id"]),
            ),
            200,
        )

        # COMPLETED but not VERIFIED: the closure gate holds.
        res = api.close_investigation(inv["id"], make_investigator_headers("inv-802"))
        validate_error(res, ApiErrorId.ERR_EXCHANGE_NOT_VERIFIED.value, 409)

        validate_success(api.verify_work_order(xwo_id, ADMIN), 200)
        closed = validate_success(
            api.close_investigation(inv["id"], make_investigator_headers("inv-802")), 200
        )
        assert closed["investigation_status"] == "CLOSED"
        assert closed["closed_by_user_id"] == "inv-802"

    def test_investigation_close_segregation_of_duties(self, api):
        """PRD section 3.6: "From either `CONFIRMED_THEFT` or `CLEARED`, an
        investigator may close the investigation, but the closer's `X-User-ID`
        must differ from the `opened_by_user_id` — the same operator cannot
        close what they opened, and an attempt fails with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/investigation_close_segregation_of_duties
        """
        _account, _meter, inv = _investigation_at_pending_disposition(
            api, "C-0102", "CB3", indication_type="USAGE_ANOMALY", opened_by="inv-901"
        )
        validate_success(
            api.clear_investigation(inv["id"], make_investigator_headers("inv-901")), 200
        )

        res = api.close_investigation(inv["id"], make_investigator_headers("inv-901"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        closed = validate_success(
            api.close_investigation(inv["id"], make_investigator_headers("inv-902")), 200
        )
        assert closed["investigation_status"] == "CLOSED"

    def test_investigation_closed_terminal_lockdown(self, api):
        """PRD section 3.6: "A successful close stamps `closed_by_user_id` and
        lands the investigation in the terminal `CLOSED` state."
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/investigation_closed_terminal_lockdown
        """
        _account, _meter, inv = _investigation_at_pending_disposition(
            api, "C-0036", "C36", indication_type="USAGE_ANOMALY", opened_by="inv-201"
        )
        validate_success(
            api.clear_investigation(inv["id"], make_investigator_headers("inv-201")), 200
        )
        closed = validate_success(
            api.close_investigation(inv["id"], make_investigator_headers("inv-202")), 200
        )
        assert closed["investigation_status"] == "CLOSED"

        res = api.request_more_evidence(inv["id"], make_investigator_headers("inv-201"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert get_investigation(inv["id"])["investigation_status"] == "CLOSED"


class TestAccountInvestigationInteraction:
    def test_reactivate_blocked_by_open_investigation(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Reactivation from `SUSPENDED` back to `ACTIVE` is
        refused while any investigation for the account sits in `OPEN`,
        `EVIDENCE_GATHERING`, `PENDING_DISPOSITION`, or `CONFIRMED_THEFT`
        (`ERR_ACCOUNT_HAS_OPEN_INVESTIGATION`, HTTP 409); a `CLEARED`
        investigation does not block."

        Design: Corner/validations/reactivate_blocked_by_open_investigation
        """
        account, meter = setup_account_with_installed_meter(
            "C-0091", "C91", service_address="91 React Rd"
        )
        inv = open_investigation(
            account["id"], meter["id"], indication_type="USAGE_ANOMALY", opened_by="inv-601"
        )
        validate_success(api.suspend_service_account(account["id"], meter_ops_admin_headers), 200)

        res = api.reactivate_service_account(account["id"], meter_ops_admin_headers)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_INVESTIGATION.value, 409)

        advance_investigation_to_pending_disposition(inv["id"], "inv-601")
        validate_success(
            api.clear_investigation(inv["id"], make_investigator_headers("inv-601")), 200
        )
        validate_success(
            api.close_investigation(inv["id"], make_investigator_headers("inv-602")), 200
        )

        reactivated = validate_success(
            api.reactivate_service_account(account["id"], meter_ops_admin_headers), 200
        )
        assert reactivated["account_status"] == "ACTIVE"


class TestTamperReadCascade:
    def _tamper_capture_scenario(self, api):
        """Two FAILED AMI meters enrolled in one OPEN campaign; a tamper-
        flagged field capture against the first meter's stop.
        Returns (account_1, m1, m2, campaign, enrollments, read)."""
        set_logical_clock("2026-07-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Tech Five"), ADMIN
            ),
            201,
        )
        account_1, m1 = setup_account_with_installed_meter(
            "A-6101", "C13", meter_type="AMI", service_address="21 Maple Dr"
        )
        account_2, m2 = setup_account_with_installed_meter(
            "A-6102", "C13", meter_type="AMI", service_address="22 Maple Dr"
        )
        for at in [
            "2026-07-02T00:00:00Z",
            "2026-07-03T00:00:00Z",
            "2026-07-04T00:00:00Z",
            "2026-07-18T00:00:00Z",
        ]:
            run_ops_snapshot(at)
        assert get_meter(m1["id"])["endpoint_comms_status"] == "FAILED"
        assert get_meter(m2["id"])["endpoint_comms_status"] == "FAILED"

        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="FY26 Theft Corridor", quota=2),
                ADMIN,
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)
        enrollments = validate_success(
            api.enroll_meters(campaign["id"], enroll_payload([m1["id"], m2["id"]]), ADMIN),
            201,
        )
        assert len(enrollments) == 2

        period, route, stops, tech2 = setup_in_progress_route(
            "C13",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            route_shift="FULL",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Tech Five",
        )
        assert len(stops) == 2
        stop_1 = next(s for s in stops if s["service_account_id"] == account_1["id"])

        read = validate_success(
            api.capture_read(
                stop_1["id"],
                capture_read_payload(
                    m1["id"],
                    1234,
                    "2026-08-03T10:00:00Z",
                    stop_1["version"],
                    tamper_indication=True,
                ),
                make_field_technician_headers(tech2["id"]),
            ),
            201,
        )
        return account_1, m1, m2, campaign, enrollments, read

    def test_tamper_read_auto_creates_investigation(self, api):
        """PRD section 3.6: "Investigations also open themselves: when a field
        capture arrives with `tamper_indication` true and no non-terminal
        investigation exists for that account and meter, the system creates an
        `OPEN` investigation whose `triggering_read_id` points at the
        tamper-flagged read and whose `opened_by_user_id` is recorded as
        `system`."
        PRD section 3.6: "Either path flips the meter's `tamper_status` from
        `NONE` to `SUSPECTED`, and suspicion has teeth."

        Design: Difficulty/transitive_cascade/tamper_read_cascades_through_enrollment_withdrawal_keeps_campaign_open
        """
        _account_1, m1, _m2, _campaign, _enrollments, read = self._tamper_capture_scenario(api)
        assert read["read_status"] == "PROVISIONAL"
        assert read["tamper_indication"] is True

        investigations, meta = validate_paginated(
            api.list_investigations(ADMIN, params={"meter_id": m1["id"]})
        )
        assert meta["total_count"] == 1
        inv = investigations[0]
        assert inv["investigation_status"] == "OPEN"
        assert inv["triggering_read_id"] == read["id"]
        assert inv["opened_by_user_id"] == "system"

        assert get_meter(m1["id"])["tamper_status"] == "SUSPECTED"

    def test_tamper_read_withdraws_enrollment_keeps_campaign_open(self, api):
        """PRD section 3.6: "Suspicion also withdraws the meter from any
        replacement program already in flight: a CampaignEnrollment for the
        meter in `ENROLLED` or `WORK_ORDER_CREATED` transitions to
        `WITHDRAWN`, its `OPEN` or `DISPATCHED` work order transitions to
        `CANCELLED`, and the owning campaign recomputes its counts,
        auto-completing when every enrollment has reached a terminal state
        (§3.8)."

        Design: Difficulty/transitive_cascade/tamper_read_cascades_through_enrollment_withdrawal_keeps_campaign_open
        """
        _account_1, m1, m2, campaign, enrollments, _read = self._tamper_capture_scenario(api)
        enr_by_meter = {e["meter_id"]: e for e in enrollments}
        enr_1 = enr_by_meter[m1["id"]]
        enr_2 = enr_by_meter[m2["id"]]

        enr_1_after = get_enrollment(enr_1["id"])
        assert enr_1_after["enrollment_status"] == "WITHDRAWN"
        assert get_work_order(enr_1["work_order_id"])["work_order_status"] == "CANCELLED"

        # the second enrollment remains non-terminal, so the campaign stays OPEN
        enr_2_after = get_enrollment(enr_2["id"])
        assert enr_2_after["enrollment_status"] == "WORK_ORDER_CREATED"
        assert get_work_order(enr_2["work_order_id"])["work_order_status"] == "OPEN"

        campaign_after = get_campaign(campaign["id"])
        assert campaign_after["campaign_status"] == "OPEN"
        assert campaign_after["enrolled_count"] == 1
        assert campaign_after["withdrawn_count"] == 1
