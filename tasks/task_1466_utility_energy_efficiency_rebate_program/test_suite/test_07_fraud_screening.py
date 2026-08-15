"""Fraud screening at submission: the half-open same-address window, the
closed ally-burst window with its count threshold, persisted fraud flags, and
the SUSPECT hold at approval."""
from test_helpers import (
    ApiErrorId,
    build_submitted_application,
    create_active_ally,
    create_open_program,
    get_application,
    validate_error,
    validate_paginated,
    verify_application,
)


class TestSameServiceAddressHalfOpenWindow:
    def test_same_day_invoice_excluded_from_window(self, api, admin_headers):
        """PRD §3.4: "Rule one, `SAME_SERVICE_ADDRESS` (weight 40): consider the
        trailing thirty-day window anchored on this application's own
        `invoice_date` — a window that includes the date thirty days before the
        invoice date and excludes the invoice date itself, so the current
        application's invoice date is not inside its own window."
        PRD §3.4: "If any *other* application exists in the same program year
        with the identical `service_address`, in any of `SUBMITTED`,
        `PRE_INSPECTION`, `POST_INSPECTION`, `VERIFIED`, `APPROVED`, or `PAID`,
        and with an `invoice_date` inside that window, forty points are
        assessed."

        Design: Difficulty/resource_temporal_overlap/same_service_address_half_open_window
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-06-01",
        )
        # Same service_address, identical invoice_date: the prior application's
        # invoice date equals this one's own, which the half-open window
        # excludes -> no SAME_SERVICE_ADDRESS assessment.
        app2, _ = build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-06-01",
        )
        # 2026-06-01 is 73 days before the 2026-08-13 clock: no INVOICE_GAP_SMALL.
        assert app2["risk_score"] == 0
        assert app2["auto_flag_status"] == "CLEAR"

        data, meta = validate_paginated(
            api.list_fraud_flags(admin_headers, params={"application_id": app2["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []

    def test_prior_invoice_inside_window_assesses_40(self, api, admin_headers):
        """PRD §3.4: "If any *other* application exists in the same program year
        with the identical `service_address`, in any of `SUBMITTED`,
        `PRE_INSPECTION`, `POST_INSPECTION`, `VERIFIED`, `APPROVED`, or `PAID`,
        and with an `invoice_date` inside that window, forty points are
        assessed."
        PRD §3.4: "When the accumulated `risk_score` reaches fifty, the
        application's `auto_flag_status` becomes `SUSPECT`; otherwise it remains
        `CLEAR`."

        Design: Difficulty/resource_temporal_overlap/same_service_address_half_open_window
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-06-01",
        )
        build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-06-01",
        )
        # Window for 2026-06-15 is [2026-05-16, 2026-06-15): 2026-06-01 is
        # inside -> +40. Gap to the 2026-08-13 clock is 59 days: no other rule.
        app3, _ = build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-06-15",
        )
        assert app3["risk_score"] == 40
        assert app3["auto_flag_status"] == "CLEAR"

        data, meta = validate_paginated(
            api.list_fraud_flags(admin_headers, params={"application_id": app3["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["flag_kind"] == "SAME_SERVICE_ADDRESS"
        assert data[0]["weight"] == 40


class TestAllyBurstClosedWindow:
    def test_fourth_submission_below_burst_threshold(self, api, admin_headers):
        """PRD §3.4: "Rule two, `ALLY_BURST` (weight 25): count the applications
        that share this application's `trade_ally_id` and `program_year_id`, sit
        in one of those same six statuses, and have a `submitted_at` date inside
        the trailing seven-day window ending on the current logical-clock date —
        both endpoints inclusive, and including the application now being
        submitted. A count of five or more adds twenty-five points."

        Design: Difficulty/resource_temporal_overlap/ally_burst_closed_window_count_threshold
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        apps = [
            build_submitted_application(py, ally, measures[0])[0]
            for _ in range(4)
        ]
        # Fourth submission: count is 4 < 5 -> no ALLY_BURST. Invoice
        # 2026-08-01 is 12 days before the clock: no INVOICE_GAP_SMALL.
        assert apps[3]["risk_score"] == 0
        assert apps[3]["auto_flag_status"] == "CLEAR"

    def test_fifth_submission_triggers_burst(self, api, admin_headers):
        """PRD §3.4: "A count of five or more adds twenty-five points."
        PRD §3.4: "When the accumulated `risk_score` reaches fifty, the
        application's `auto_flag_status` becomes `SUSPECT`; otherwise it remains
        `CLEAR`."
        PRD §3.4: "The screen accumulates a `risk_score` from up to three rules
        and persists one immutable fraud flag per triggered rule, each recording
        its `application_id`, a `flag_kind`, the rule's `weight`, and a
        human-readable `detail`."

        Design: Difficulty/resource_temporal_overlap/ally_burst_closed_window_count_threshold
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        apps = [
            build_submitted_application(py, ally, measures[0])[0]
            for _ in range(5)
        ]
        app5 = apps[4]
        # Fifth submission on the same logical day: burst count 5 -> +25 only.
        assert app5["risk_score"] == 25
        assert app5["auto_flag_status"] == "CLEAR"

        data, meta = validate_paginated(
            api.list_fraud_flags(admin_headers, params={"application_id": app5["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["flag_kind"] == "ALLY_BURST"
        assert data[0]["weight"] == 25


class TestFraudFlagListing:
    def test_fraud_flag_list_returns_created_flags(self, api, admin_headers):
        """PRD §3.4: "The screen accumulates a `risk_score` from up to three
        rules and persists one immutable fraud flag per triggered rule, each
        recording its `application_id`, a `flag_kind`, the rule's `weight`, and
        a human-readable `detail`."
        PRD §3.4: "Fraud-flag listings filter by `application_id` and
        `flag_kind`."

        Design: Corner/entities/fraud_flag_list_returns_created_flags
        """
        py, measures = create_open_program(budget_cap_cents=100_000_000)
        ally = create_active_ally()
        apps = [
            build_submitted_application(py, ally, measures[0])[0]
            for _ in range(5)
        ]
        app5 = apps[4]

        data, meta = validate_paginated(
            api.list_fraud_flags(admin_headers, params={"application_id": app5["id"]})
        )
        assert meta["total_count"] == 1
        flag = data[0]
        assert flag["application_id"] == app5["id"]
        assert flag["flag_kind"] == "ALLY_BURST"
        assert flag["weight"] == 25
        assert isinstance(flag["detail"], str) and flag["detail"]
        # Append-only shape: no version / updated_at.
        assert "version" not in flag
        assert "updated_at" not in flag


class TestSuspectHoldAtApproval:
    def test_approve_on_suspect_application_returns_fraud_hold(self, api, admin_headers):
        """PRD §3.6: "Approval's checks run in order — the program-open gate,
        the `VERIFIED` state check, then the fraud hold, then segregation of
        duties — so a `SUSPECT` application is refused with
        `ERR_FRAUD_SUSPECT_HOLD` (HTTP 409) even when the approver would also
        trip the segregation rule."
        PRD §3.4: "When the accumulated `risk_score` reaches fifty, the
        application's `auto_flag_status` becomes `SUSPECT`; otherwise it remains
        `CLEAR`."

        Design: Corner/validations/approve_on_suspect_application_returns_fraud_hold
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-08-10",
        )
        # app2: same address, invoice 2026-08-12 -> SAME_SERVICE_ADDRESS (40)
        # because 2026-08-10 lies in [2026-07-13, 2026-08-12); plus
        # INVOICE_GAP_SMALL (15) because the invoice is one day before the
        # 2026-08-13 clock. 40 + 15 = 55 >= 50 -> SUSPECT.
        app2, line2 = build_submitted_application(
            py, ally, measures[0], service_address="1 Main St",
            invoice_date="2026-08-12", claim="DEEMED",
        )
        assert app2["auto_flag_status"] == "SUSPECT"

        # Verification does not consult the fraud screen; a SUSPECT
        # application still reaches VERIFIED.
        app2 = verify_application(app2)
        assert app2["status"] == "VERIFIED"

        res = api.approve_application(app2["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_FRAUD_SUSPECT_HOLD, expected_status=409)
        assert get_application(app2["id"])["status"] == "VERIFIED"
