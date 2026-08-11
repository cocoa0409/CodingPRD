"""Job outcomes: cancellations, no-shows, and warranty callbacks."""
from test_helpers import (
    ApiErrorId,
    arrive_stop,
    get_route_stop,
    make_customer_headers,
    make_mechanic_headers,
    set_clock,
    setup_completed_job,
    setup_dispatched_request,
    setup_quoted_request,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCancellation:
    def test_cancel_quoted_is_free_no_invoice(self, api, dispatcher_headers):
        """PRD §3.4: "Cancelling from `QUOTED` — available to the owning `Customer`
        or a `Dispatcher`, with an optional `cancel_reason` — is free: no invoice
        is created, and if the request was covered, its allowance reservation is
        released."

        Design: Corner/calculations/cancel_quoted_is_free_no_invoice
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        data = validate_success(api.service_request_event(
            ctx["request"]["id"], {"event_type": "CANCEL"}, dispatcher_headers), 200)
        assert data["work_status"] == "CANCELLED"
        invoices, _ = validate_paginated(api.list_request_invoices(ctx["request"]["id"], dispatcher_headers))
        assert invoices == [], f"free cancel from QUOTED must create no invoice, got {invoices}"

    def test_cancel_dispatched_creates_callout_fee_invoice(self, api, dispatcher_headers):
        """PRD §3.7: "Cancelling from `DISPATCHED` or `ON_SITE` — by the owning
        customer or a dispatcher — marks the linked stop `SKIPPED`, recomputes the
        route day's count with a version bump, clears `scheduled_mechanic_id`,
        releases any allowance reservation, and auto-creates a cancellation-fee
        invoice in `DRAFT` carrying the zone's `base_callout_fee_cents` as its
        callout, zero labor and parts, no surcharge, and tax on the callout alone."

        Design: Corner/calculations/cancel_dispatched_creates_callout_fee_invoice
        """
        ctx = setup_dispatched_request(
            window=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        data = validate_success(api.service_request_event(
            ctx["request"]["id"], {"event_type": "CANCEL", "cancel_reason": "not home"},
            make_customer_headers(ctx["customer"]["id"])), 200)
        assert data["work_status"] == "CANCELLED"
        assert data["scheduled_mechanic_id"] is None
        assert get_route_stop(ctx["stop"]["id"])["status"] == "SKIPPED"

        invoices, _ = validate_paginated(api.list_request_invoices(ctx["request"]["id"], dispatcher_headers))
        assert len(invoices) == 1, f"exactly one fee invoice must be auto-created, got {len(invoices)}"
        fee = invoices[0]
        assert fee["status"] == "DRAFT"
        assert fee["callout_cents"] == 2500
        assert fee["labor_cents"] == 0 and fee["parts_gross_cents"] == 0
        assert fee["surcharge_cents"] == 0
        assert fee["tax_cents"] == 200, f"tax on 2500 callout must be 200, got {fee['tax_cents']}"
        assert fee["total_cents"] == 2700, f"fee invoice total must be 2700, got {fee['total_cents']}"

    def test_cancel_from_terminal_cancelled_rejected(self, api, dispatcher_headers):
        """PRD §3.7: "any event fired from a state that does not support it draws
        `ERR_INVALID_STATE`."
        PRD §3.4: "Cancelling from `QUOTED` — available to the owning `Customer`
        or a `Dispatcher`, with an optional `cancel_reason` — is free"

        Design: Corner/state_machines/cancel_from_terminal_cancelled_rejected
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        first = validate_success(api.service_request_event(
            ctx["request"]["id"], {"event_type": "CANCEL", "cancel_reason": "changed mind"},
            dispatcher_headers), 200)
        assert first["work_status"] == "CANCELLED"

        second = api.service_request_event(ctx["request"]["id"], {"event_type": "CANCEL"}, dispatcher_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)


class TestNoShow:
    def test_no_show_invoice_is_callout_plus_tax_only(self, api, dispatcher_headers):
        """PRD §3.7: "Marking a no-show from `ON_SITE` — mechanic only — performs
        the same stop and day bookkeeping and releases the reservation without
        consuming allowance, then auto-creates a `DRAFT` invoice flagged
        `is_no_show_fee` true containing the callout plus its tax and nothing
        else."

        Design: Corner/calculations/no_show_invoice_is_callout_plus_tax_only
        """
        ctx = setup_dispatched_request(
            window=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        arrive_stop(ctx["stop"]["id"], ctx["mechanic"]["id"])
        data = validate_success(api.service_request_event(
            ctx["request"]["id"], {"event_type": "MARK_NO_SHOW"},
            make_mechanic_headers(ctx["mechanic"]["id"])), 200)
        assert data["work_status"] == "NO_SHOW"

        invoices, _ = validate_paginated(api.list_request_invoices(ctx["request"]["id"], dispatcher_headers))
        assert len(invoices) == 1, f"exactly one no-show fee invoice must exist, got {len(invoices)}"
        fee = invoices[0]
        assert fee["status"] == "DRAFT"
        assert fee["is_no_show_fee"] is True
        assert fee["callout_cents"] == 2500
        assert fee["labor_cents"] == 0 and fee["parts_gross_cents"] == 0
        assert fee["surcharge_cents"] == 0
        assert fee["tax_cents"] == 200
        assert fee["total_cents"] == 2700, f"no-show fee must total 2700, got {fee['total_cents']}"


class TestWarrantyCallbacks:
    def _completed_basic_job(self):
        """Job COMPLETED at the startup logical clock (BASIC tier, 30 warranty
        days, no parts consumed)."""
        return setup_completed_job(labor_minutes=40)

    def test_warranty_deadline_inclusive_allows_callback(self, api, dispatcher_headers):
        """PRD §3.8: "the deadline is the original's `completed_at` plus that many
        days, and the comparison against the logical clock is inclusive — a
        callback opened at the exact deadline second is eligible, and any instant
        after it is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409)."
        PRD §3.7: "Completing records `actual_labor_minutes` and stamps
        `completed_at` from the logical clock"
        PRD §2.6: "At startup, before any operator intervention, the logical clock
        reads exactly 2026-05-01T00:00:00Z"

        Design: Corner/calculations/warranty_deadline_inclusive_allows_callback
        """
        ctx = self._completed_basic_job()
        completed_at = ctx["request"]["completed_at"]
        assert completed_at.startswith("2026-05-01T00:00:00"), (
            f"completed_at must be stamped from the startup logical clock, got {completed_at}")

        # Deadline: 2026-05-01 + 30 days = 2026-05-31T00:00:00Z (inclusive).
        set_clock("2026-05-31T00:00:00Z")
        resp = api.create_callback(ctx["request"]["id"], {
            "window_start": "2026-05-31T10:00:00Z", "window_end": "2026-05-31T11:00:00Z",
            "issue_note": "brake rubs again",
        }, dispatcher_headers)
        cb = validate_success(resp, 201)
        assert cb["request_kind"] == "CALLBACK"
        assert cb["callback_of_id"] == ctx["request"]["id"]

    def test_warranty_deadline_plus_one_second_rejected(self, api, dispatcher_headers):
        """PRD §3.8: "the comparison against the logical clock is inclusive — a
        callback opened at the exact deadline second is eligible, and any instant
        after it is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409)."

        Design: Corner/calculations/warranty_deadline_plus_one_second_rejected
        """
        ctx = self._completed_basic_job()
        set_clock("2026-05-31T00:00:01Z")
        resp = api.create_callback(ctx["request"]["id"], {
            "window_start": "2026-05-31T10:00:00Z", "window_end": "2026-05-31T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

    def test_duplicate_callback_rejected(self, api, dispatcher_headers):
        """PRD §3.8: "only then is the duplicate guard evaluated, refusing with
        `ERR_CALLBACK_EXISTS` (HTTP 409) when an earlier callback for the same
        original is still open — that is, its `work_status` is anything other than
        `CLOSED`, `CANCELLED`, or `NO_SHOW`."

        Design: Corner/validations/duplicate_callback_rejected
        """
        ctx = self._completed_basic_job()
        first = validate_success(api.create_callback(ctx["request"]["id"], {
            "window_start": "2026-05-03T10:00:00Z", "window_end": "2026-05-03T11:00:00Z",
        }, dispatcher_headers), 201)
        assert first["request_kind"] == "CALLBACK"

        resp = api.create_callback(ctx["request"]["id"], {
            "window_start": "2026-05-04T10:00:00Z", "window_end": "2026-05-04T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CALLBACK_EXISTS)
