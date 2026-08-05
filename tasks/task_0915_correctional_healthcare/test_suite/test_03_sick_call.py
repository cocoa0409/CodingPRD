"""Sick-call slips, triage and re-triage anchoring, the SLA clock and the encounter bill."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_sick_call_request,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSickCallListing:
    def test_sick_call_listing_filters_by_inmate_and_windows_the_result_set(
        self, api, nurse_headers
    ):
        """PRD §3.3: "Sick-call requests can be listed with optional `inmate_id`,
        `copay_charge_id`, `status` and `acuity` filters and read individually, and every
        such read evaluates `sla_breached` afresh."
        PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the size of the full filtered
        result set before the window is applied and `has_more` is true exactly when rows
        remain beyond the current window."

        Design: Corner/entities/sick_call_list_pagination_and_filter
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2020", full_name="Tam Uribe", booked_at="2026-05-01T00:00:00Z"
        )
        for complaint in ("headache", "back pain", "rash"):
            fx.submit_sick_call(inmate["id"], complaint_text=complaint)

        resp = api.list_sick_call_requests(
            nurse_headers,
            params={"inmate_id": inmate["id"], "status": "SUBMITTED", "limit": 2, "offset": 0},
        )
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(rows) == 2
        for row in rows:
            assert_sick_call_request(row)
            assert row["inmate_id"] == inmate["id"]

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["open_sick_call_count"] == 3


class TestRetriage:
    def test_third_retriage_is_refused_once_the_counter_reaches_its_cap(self, api, nurse_headers):
        """PRD §3.3: "A re-triage is accepted only while `retriage_count` is strictly less
        than 2; a third attempt is rejected at rung 14 with `ERR_MAX_RETRIAGE_EXCEEDED`
        (409)."

        Design: Corner/state_machines/sick_call_retriage_cap_rejected_on_third_retriage
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2100", full_name="Bea Dowd", booked_at="2026-05-01T00:00:00Z"
        )
        request = fx.setup_triaged_sick_call(
            inmate["id"], "ROUTINE", complaint_text="chest tightness"
        )
        fx.triage(request["id"], "URGENT")
        fx.triage(request["id"], "EMERGENT")

        resp = api.triage_sick_call_request(request["id"], {"acuity": "ROUTINE"}, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_MAX_RETRIAGE_EXCEEDED.value, 409)

        unchanged = fx.read_sick_call(request["id"])
        assert unchanged["retriage_count"] == 2
        assert unchanged["acuity"] == "EMERGENT"

    def test_retriage_to_the_stored_acuity_is_a_payload_failure(self, api, nurse_headers):
        """PRD §3.3: "The submitted `acuity` must differ from the one the request already
        carries; re-triaging to the identical acuity is a payload failure reported as
        `ERR_VALIDATION` (400) at rung 9."

        Design: Corner/state_machines/sick_call_retriage_same_acuity_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2110", full_name="Cy Eaton", booked_at="2026-05-01T00:00:00Z"
        )
        request = fx.setup_triaged_sick_call(inmate["id"], "URGENT", complaint_text="ear ache")

        resp = api.triage_sick_call_request(request["id"], {"acuity": "URGENT"}, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
        assert fx.read_sick_call(request["id"])["retriage_count"] == 0


class TestResponseDeadlineAnchoring:
    def test_upgrade_re_pins_the_anchor_to_the_original_submission(self, api, nurse_headers):
        """PRD §3.3: "- **An upgrade** — a move to a strictly more urgent acuity — re-pins
        `deadline_anchor_at` to the **original** `submitted_at`. Time already elapsed since
        the slip was written is not forgiven, so the recomputed `response_deadline_at` can
        and often does land in the past: a request submitted eight hours ago and upgraded
        from `ROUTINE` to `EMERGENT` acquires a deadline one hour after submission, which is
        seven hours overdue the moment it is written."
        PRD §3.3: "In both cases `response_deadline_at` is the newly-pinned anchor plus the
        new acuity's allowance from the same one/twenty-four/seventy-two-hour table."

        Design: Corner/calculations/sick_call_upgrade_anchors_on_original_submission
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2220", full_name="Nia Prasad", booked_at="2026-05-01T00:00:00Z"
        )
        request = fx.setup_triaged_sick_call(
            inmate["id"], "ROUTINE", complaint_text="abdominal pain"
        )
        assert_same_instant(
            request["response_deadline_at"], "2026-05-04T00:00:00Z", "initial deadline"
        )

        fx.set_clock("2026-05-02T00:00:00Z")
        resp = api.triage_sick_call_request(request["id"], {"acuity": "URGENT"}, nurse_headers)
        data = validate_success(resp, 200)
        assert data["acuity"] == "URGENT"
        assert data["retriage_count"] == 1
        assert_same_instant(
            data["deadline_anchor_at"], "2026-05-01T00:00:00Z", "deadline_anchor_at"
        )
        assert_same_instant(
            data["response_deadline_at"], "2026-05-02T00:00:00Z", "response_deadline_at"
        )

    def test_downgrade_re_pins_the_anchor_to_the_retriage_instant(self, api, nurse_headers):
        """PRD §3.3: "- **A downgrade** — a move to a strictly less urgent acuity — re-pins
        `deadline_anchor_at` to the **re-triage instant**, that is, the current clock.
        Elapsed time is forgiven, and the clock starts again from now."
        PRD §3.3: "In both cases `response_deadline_at` is the newly-pinned anchor plus the
        new acuity's allowance from the same one/twenty-four/seventy-two-hour table."

        Design: Corner/calculations/sick_call_downgrade_anchors_on_retriage_instant
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2230", full_name="Oz Ramirez", booked_at="2026-05-01T00:00:00Z"
        )
        request = fx.setup_triaged_sick_call(
            inmate["id"], "URGENT", complaint_text="sore throat"
        )
        assert_same_instant(
            request["response_deadline_at"], "2026-05-02T00:00:00Z", "initial deadline"
        )

        fx.set_clock("2026-05-02T00:00:00Z")
        resp = api.triage_sick_call_request(request["id"], {"acuity": "ROUTINE"}, nurse_headers)
        data = validate_success(resp, 200)
        assert_same_instant(
            data["deadline_anchor_at"], "2026-05-02T00:00:00Z", "deadline_anchor_at"
        )
        assert_same_instant(
            data["response_deadline_at"], "2026-05-05T00:00:00Z", "response_deadline_at"
        )

    def test_sla_is_not_breached_at_the_deadline_and_is_breached_one_second_later(self, api):
        """PRD §3.3: "The first triage moves the request from `SUBMITTED` to `TRIAGED`,
        stamps `triaged_at` with the current clock instant, pins `deadline_anchor_at` to the
        request's own `submitted_at`, and leaves `retriage_count` at 0. The
        `response_deadline_at` is then the anchor plus the acuity's service-level allowance:
        one hour for `EMERGENT`, twenty-four hours for `URGENT`, and seventy-two hours for
        `ROUTINE`."
        PRD §3.3: "Otherwise the resolution instant is the request's `seen_at` when the
        patient has been seen, and the current clock instant when they have not, and the
        request is breached exactly when that resolution instant falls strictly after
        `response_deadline_at`. Equality is not a breach."

        Design: Corner/calculations/sick_call_sla_breach_strict_after_deadline
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2240", full_name="Pia Sadiq", booked_at="2026-05-01T00:00:00Z"
        )
        request = fx.setup_triaged_sick_call(
            inmate["id"], "EMERGENT", complaint_text="shortness of breath"
        )
        assert_same_instant(
            request["response_deadline_at"], "2026-05-01T01:00:00Z", "response_deadline_at"
        )

        fx.set_clock("2026-05-01T01:00:00Z")
        assert fx.read_sick_call(request["id"])["sla_breached"] is False

        fx.set_clock("2026-05-01T01:00:01Z")
        assert fx.read_sick_call(request["id"])["sla_breached"] is True


class TestEncounterBilling:
    def test_see_response_already_carries_the_posted_charge_identifier(self, api, provider_headers):
        """PRD §3.3: "When a `Provider` records that the patient was seen, the request moves
        from `SCHEDULED` to `SEEN`, `seen_at` is stamped from the clock — freezing the SLA
        resolution instant — and the encounter bills. Exactly one co-pay charge is created,
        with its `encounter_type` copied from the sick-call request, its `source_sick_call_id`
        pointing back at this request, its `amount_cents`, `scheduled_amount_cents` and
        `charge_variant` produced by the co-pay engine of §3.7, and its `indigency_snapshot`
        taken from the indigency determination as it stood **immediately before** this charge
        posted. The new charge's identifier is written back onto the request as
        `copay_charge_id`."

        Design: Corner/consistency_model/immediate_consistency_charge_visible_in_see_response
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2410", full_name="Ida Lemos", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 1000)
        request = fx.setup_scheduled_sick_call(
            inmate["id"], "ROUTINE", complaint_text="wrist swelling"
        )

        resp = api.see_sick_call_request(request["id"], provider_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "SEEN"
        assert data["copay_charge_id"] is not None
        assert_same_instant(data["seen_at"], "2026-05-01T00:00:00Z", "seen_at")

        charge = fx.read_charge(data["copay_charge_id"])
        assert charge["amount_cents"] == 500
        assert fx.read_inmate(inmate["id"])["account_balance_cents"] == 500

    def test_charge_listing_filtered_by_source_sick_call_returns_only_that_encounter(
        self, api, admin_headers
    ):
        """PRD §3.7: "Charges can be listed with optional `inmate_id`, `source_sick_call_id`,
        `reversal_grievance_id`, `status` and `charge_variant` filters, and read individually
        with their computed `amount_cents`, `charge_variant` and `indigency_snapshot`."
        PRD §3.7: "**The funded variant** applies when `indigency_snapshot` is false:
        `amount_cents` equals `scheduled_amount_cents` in full, `charge_variant` is `FUNDED`,
        the charge's `status` is `POSTED`, and one ledger entry of type `CHARGE` is appended
        whose `amount_cents` is the negation of the charge amount."

        Design: Corner/endpoints/copay_charges_filtered_by_source_sick_call_id
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2340", full_name="Ana Duarte", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 1000)
        seen = fx.setup_seen_sick_call(inmate["id"], "ROUTINE", complaint_text="knee pain")
        charge_id = seen["copay_charge_id"]

        resp = api.list_copay_charges(admin_headers, params={"source_sick_call_id": seen["id"]})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert rows[0]["id"] == charge_id
        assert rows[0]["charge_variant"] == "FUNDED"
        assert rows[0]["amount_cents"] == 500
        assert rows[0]["status"] == "POSTED"
        assert_same_instant(seen["seen_at"], "2026-05-01T00:00:00Z", "seen_at")
