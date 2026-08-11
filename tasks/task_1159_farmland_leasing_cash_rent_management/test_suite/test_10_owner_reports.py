"""Owner reporting: closed-window aggregation, empty-window zeros, the
closed-interval overlap guard, the inverted-period guard, and absentee-owner
acknowledgment escalation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_iso_instant_equal,
    assert_owner_report,
    create_report_payload,
    get_report,
    make_landlord_headers,
    setup_landlord,
    setup_paid_installment_scenario,
    setup_report_scenario,
    set_clock,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestAggregation:
    def test_report_aggregation_inclusive_window_sums(self, api):
        """PRD §3.10: "The `rent_collected_cents` is the sum of `paid_cents` over the installments of this landlord's leases whose `last_payment_at` falls inside the window: an installment contributes its full current `paid_cents` to whichever window contains its most recent payment, and an installment never paid contributes zero."
        PRD §3.10: "A window with no matching rows yields zeros — never nulls, never an error."

        Design: Corner/calculations/report_aggregation_inclusive_window_sums
        """
        ctx = setup_paid_installment_scenario()  # I1 paid 1250000 at 2027-03-01
        landlord_id = ctx["landlord"]["id"]

        q1 = validate_success(
            api.create_report(
                create_report_payload(
                    landlord_id,
                    period_start="2027-01-01T00:00:00Z",
                    period_end="2027-03-31T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        assert_owner_report(q1)
        assert q1["rent_collected_cents"] == 1250000, (
            "last_payment_at 2027-03-01 falls inside the closed window"
        )

        q2 = validate_success(
            api.create_report(
                create_report_payload(
                    landlord_id,
                    period_start="2027-04-01T00:00:00Z",
                    period_end="2027-06-30T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        assert q2["rent_collected_cents"] == 0
        assert q2["expenses_approved_cents"] == 0
        assert q2["noncompliant_count"] == 0

    def test_empty_report_window_yields_zero_aggregates(self, api):
        """PRD §3.10: "A window with no matching rows yields zeros — never nulls, never an error."
        PRD §3.10: "The `rent_collected_cents` is the sum of `paid_cents` over the installments of this landlord's leases whose `last_payment_at` falls inside the window"

        Design: Difficulty/boundary_precision_check/empty_report_window_yields_zero_aggregates
        """
        landlord = setup_landlord(name="L Empty", contact_email="le@x.com")
        report = validate_success(
            api.create_report(create_report_payload(landlord["id"]), MGR), 201
        )
        assert_owner_report(report)
        assert report["rent_collected_cents"] == 0
        assert report["expenses_approved_cents"] == 0
        assert report["noncompliant_count"] == 0
        assert report["status"] == "DRAFT"

    def test_new_report_starts_draft_with_null_schedule_fields(self, api):
        """PRD §3.10: "A new report starts in `DRAFT` status with `sent_at`, `ack_due_date`, and `acknowledged_at` all null and `escalation_required` false."

        Design: Difficulty/boundary_precision_check/empty_report_window_yields_zero_aggregates
        """
        landlord = setup_landlord(name="L Empty2", contact_email="le2@x.com")
        report = validate_success(
            api.create_report(create_report_payload(landlord["id"]), MGR), 201
        )
        assert report["status"] == "DRAFT"
        assert report["sent_at"] is None
        assert report["ack_due_date"] is None
        assert report["acknowledged_at"] is None
        assert report["escalation_required"] is False


class TestPeriodGuards:
    def test_report_inverted_period_rejected(self, api):
        """PRD §3.10: "A `period_start` later than the `period_end` is rejected with `ERR_INVALID_PERIOD`"

        Design: Corner/validations/report_inverted_period_rejected
        """
        landlord = setup_landlord(name="L IP", contact_email="lip@x.com")
        resp = api.create_report(
            create_report_payload(
                landlord["id"],
                report_type="ANNUAL",
                period_start="2026-06-30T00:00:00Z",
                period_end="2026-01-01T00:00:00Z",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)

    def test_touching_report_window_overlaps_closed_interval(self, api):
        """PRD §2.9: "Owner-report windows follow the opposite convention: the period is the closed interval `[period_start, period_end]` with both ends inclusive, and two reports for the same landlord whose windows share even a single endpoint overlap."
        PRD §3.10: "a window that overlaps any existing report for the same landlord — touching endpoints already count as overlap under the closed-interval semantics of §2.9 — is rejected with `ERR_REPORT_PERIOD_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/landlord_report_closed_interval_touching_overlap
        """
        landlord = setup_landlord(name="L Rpt", contact_email="lrr@x.com")
        validate_success(
            api.create_report(create_report_payload(landlord["id"]), MGR), 201
        )
        # [2026-03-31, 2026-06-30] shares the endpoint 2026-03-31 with the
        # existing [2026-01-01, 2026-03-31] report: closed intervals overlap.
        touching = api.create_report(
            create_report_payload(
                landlord["id"],
                period_start="2026-03-31T00:00:00Z",
                period_end="2026-06-30T00:00:00Z",
            ),
            MGR,
        )
        validate_error(touching, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_disjoint_report_window_accepted(self, api):
        """PRD §2.9: "the period is the closed interval `[period_start, period_end]` with both ends inclusive, and two reports for the same landlord whose windows share even a single endpoint overlap."

        Design: Difficulty/resource_temporal_overlap/landlord_report_closed_interval_touching_overlap
        """
        landlord = setup_landlord(name="L Rpt2", contact_email="lrr2@x.com")
        validate_success(
            api.create_report(create_report_payload(landlord["id"]), MGR), 201
        )
        disjoint = validate_success(
            api.create_report(
                create_report_payload(
                    landlord["id"],
                    period_start="2026-04-01T00:00:00Z",
                    period_end="2026-06-30T00:00:00Z",
                ),
                MGR,
            ),
            201,
        )
        assert disjoint["status"] == "DRAFT", (
            "2026-04-01 shares no endpoint with [2026-01-01, 2026-03-31]"
        )


class TestAbsenteeEscalation:
    def test_absentee_report_ack_deadline_escalates_then_ack_clears(self, api):
        """PRD §3.10: "Sending moves a report from `DRAFT` to `SENT`, stamps `sent_at` from the clock, and sets the `ack_due_date` to `sent_at` plus the landlord's `ack_required_days`"
        PRD §3.10: "The escalation flag is a computed signal rather than a status: the clock sweep sets `escalation_required` true whenever the landlord is `absentee`, the report is `SENT`, and the clock has passed the `ack_due_date`."
        PRD §3.10: "a successful acknowledgment moves the report to the terminal `ACKNOWLEDGED` state, stamps `acknowledged_at`, and clears `escalation_required`."

        Design: Corner/cross_cutting_layers/absentee_report_ack_deadline_escalates_then_ack_clears
        """
        ctx = setup_report_scenario(
            landlord_overrides={
                "name": "L AE",
                "contact_email": "lae@x.com",
                "absentee": True,
                "ack_required_days": 14,
            },
            send=True,  # sent at the default clock 2026-05-01
        )
        report = ctx["report"]
        assert report["status"] == "SENT"
        assert_iso_instant_equal(report["sent_at"], "2026-05-01T00:00:00Z")
        assert_iso_instant_equal(report["ack_due_date"], "2026-05-15T00:00:00Z")
        assert report["escalation_required"] is False

        set_clock("2026-05-16T00:00:00Z")  # one day past ack_due_date
        escalated = get_report(report["id"])
        assert escalated["status"] == "SENT"
        assert escalated["escalation_required"] is True, (
            "absentee owner, SENT, clock past ack_due_date"
        )

        acknowledged = validate_success(
            api.acknowledge_report(
                report["id"], make_landlord_headers(ctx["landlord"]["id"])
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["escalation_required"] is False
        assert_iso_instant_equal(
            acknowledged["acknowledged_at"], "2026-05-16T00:00:00Z"
        )
