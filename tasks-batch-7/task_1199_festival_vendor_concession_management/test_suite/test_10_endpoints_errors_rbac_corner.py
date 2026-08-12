"""Corner: endpoint behaviors (idempotency, clock), error envelope, RBAC denials."""
from datetime import datetime, timezone

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    confirm_assignment,
    create_assignment,
    create_booth,
    create_festival,
    create_slot,
    create_vendor,
    create_zone,
    make_vendor_headers,
    report_sale,
    setup_active_assignment,
    setup_confirmed_assignment,
    setup_open_festival,
    start_review,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
HI = TEST_USERS["health_inspector_headers"]
FIN1 = TEST_USERS["finance_headers"]


def _instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestPosIdempotency:
    def test_pos_idempotent_replay_returns_existing(self, api):
        """PRD §3.6: "Reporting is idempotent on the pair of assignment and key: a
        duplicate submission carrying an already-used `idempotency_key` for the
        same `assignment_id` returns HTTP 200 with the existing transaction and
        creates nothing."

        Design: Corner/endpoints/pos_idempotent_replay_returns_existing
        """
        scen = setup_active_assignment(name="Idem Fest")
        asg_id = scen["assignment"]["id"]
        payload = {"assignment_id": asg_id, "amount_cents": 4200,
                   "occurred_at": "2026-07-10T14:00:00Z", "idempotency_key": "dup-1"}
        headers = make_vendor_headers(scen["vendor"]["id"])
        first = validate_success(api.create_transaction(payload, headers), expected_status=201)
        replay_resp = api.create_transaction(payload, headers)
        replay = validate_success(replay_resp, expected_status=200)
        assert replay_resp.status_code == 200, "replay returns 200, not 201"
        assert replay["id"] == first["id"], "same row returned, no duplicate created"
        data, meta = validate_paginated(api.list_transactions(FIN1, params={"assignment_id": asg_id}))
        assert meta["total_count"] == 1


class TestLogicalClock:
    def test_clock_default_pins_server_start_time(self, api):
        """PRD §2.5: "At server startup the logical clock is exactly
        `2026-05-01T00:00:00Z` and it must not fall back to wall-clock time under
        any circumstance. A director-only test-driving capability advances the
        logical clock to a supplied `to_iso8601` instant and returns the resulting
        `current_utc`."
        PRD §3.5: "once the logical clock reaches the instant 120 minutes before
        `window_start`, creating a reservation in that slot or cancelling an
        existing one is rejected with `ERR_SLOT_LOCKED`."

        Design: Corner/endpoints/clock_default_pins_server_start_time
        """
        # NOTE: built from granular calls only — no clock-set call is made before
        # the trigger, so the pinned startup default proves itself.
        festival = create_festival(name="Clock Fest")
        zone = create_zone(festival["id"])
        advance_festival(festival["id"], "APPLICATIONS_OPEN")
        vendor = create_vendor(legal_name="Clock LLC")
        app = submit_application(vendor, festival["id"])
        start_review(app["id"])
        accept_application(app["id"], "FLAT_FEE", flat_fee_cents=50000)
        advance_festival(festival["id"], "CURATED")
        booth = create_booth(zone["id"])
        asg = create_assignment(app["id"], booth["id"], power_draw_amps=20)
        confirm_assignment(asg["id"])
        slot = create_slot(festival["id"], window_start="2026-05-01T02:00:00Z",
                           window_end="2026-05-01T04:00:00Z")
        resp = api.create_reservation(
            {"assignment_id": asg["id"], "slot_id": slot["id"], "vehicle_count": 1},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_LOCKED)

        echo = validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, DIRECTOR))
        assert _instant(echo["current_utc"]) == _instant("2026-06-01T00:00:00Z")


class TestFilteredList:
    def test_filtered_list_combines_status_and_festival(self, api):
        """PRD §3.2: "The application list filters by `festival_id`, `vendor_id`,
        `status`, `category`, and `supersedes_application_id`."

        Design: Corner/endpoints/filtered_list_combines_status_and_festival
        """
        f1 = setup_open_festival(name="Filter F1")
        va = create_vendor(legal_name="Filter A", contact_email="a@filter.com")
        vb = create_vendor(legal_name="Filter B", contact_email="b@filter.com")
        app_a = submit_application(va, f1["festival"]["id"], category="FOOD_HOT")
        submit_application(vb, f1["festival"]["id"], category="FOOD_COLD",
                           proposed_flat_fee_cents=40000, power_needed_amps=10)  # stays SUBMITTED
        start_review(app_a["id"])
        accept_application(app_a["id"], "FLAT_FEE", flat_fee_cents=50000)

        f2 = create_festival(name="Filter F2", event_start="2026-08-01T12:00:00Z",
                             event_end="2026-08-02T23:00:00Z")
        create_zone(f2["id"], name="South")
        advance_festival(f2["id"], "APPLICATIONS_OPEN")
        app_c = submit_application(vb, f2["id"], category="DESSERT",
                                   proposed_flat_fee_cents=30000, power_needed_amps=10)
        start_review(app_c["id"])
        accept_application(app_c["id"], "FLAT_FEE", flat_fee_cents=30000)

        data, meta = validate_paginated(
            api.list_applications(VM, params={"festival_id": f1["festival"]["id"], "status": "ACCEPTED"})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [app_a["id"]], (
            "F1's SUBMITTED app and F2's ACCEPTED app are both excluded"
        )


class TestErrorEnvelope:
    def test_error_envelope_contains_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_contains_error_id_and_message
        """
        resp = api.get_festival(NON_EXISTENT_UUID, DIRECTOR)
        err = validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip(), "message non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"].get("api_request_id"), "error envelope carries meta.api_request_id"


class TestRbacDenials:
    def test_vendor_cannot_decide_application(self, api):
        """PRD §4: POST /vendor-applications/{applicationId}/decide — "Accept,
        reject, or waitlist with curated terms | VendorManager".
        PRD §2.10: "Second, role authorization for the endpoint (2)."

        Design: Corner/rbac/vendor_cannot_decide_application
        """
        resp = api.decide_application(
            NON_EXISTENT_UUID,
            {"decision": "ACCEPTED", "curated_fee_model": "FLAT_FEE", "curated_flat_fee_cents": 50000},
            make_vendor_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_health_inspector_cannot_issue_fine(self, api):
        """PRD §4: POST /compliance-fines — "Issue a compliance fine against an
        assignment | SustainabilityOfficer, FestivalDirector".

        Design: Corner/rbac/health_inspector_cannot_issue_fine
        """
        resp = api.create_fine(
            {"assignment_id": NON_EXISTENT_UUID, "type": "WASTE_SORTING", "amount_cents": 5000},
            HI,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_finance_lead_cannot_record_inspection(self, api):
        """PRD §4: POST /inspection-records — "Record a completed walk-up
        inspection | HealthInspector".

        Design: Corner/rbac/finance_lead_cannot_record_inspection
        """
        resp = api.create_inspection(
            {"assignment_id": NON_EXISTENT_UUID, "type": "HEALTH_SPOT", "result": "PASS"},
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_operations_lead_cannot_create_settlement(self, api):
        """PRD §4: POST /settlements — "Create the single settlement for an
        assignment | FinanceLead".

        Design: Corner/rbac/operations_lead_cannot_create_settlement
        """
        resp = api.create_settlement({"assignment_id": NON_EXISTENT_UUID}, OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestVendorOwnerAllowed:
    def test_vendor_owner_reports_own_pos(self, api):
        """PRD §3.6: "A sale is reported by the owning `Vendor` or a `FinanceLead`
        with the `assignment_id`, the gross `amount_cents` (at least 1, otherwise
        `ERR_INVALID_AMOUNT`, HTTP 400), the sale instant `occurred_at`, and a
        client-supplied `idempotency_key`."
        PRD §3.6: "A new transaction enters `REPORTED` status".

        Design: Corner/rbac/vendor_owner_reports_own_pos
        """
        scen = setup_active_assignment(name="Owner Pos Fest")
        data = report_sale(scen["assignment"]["id"], scen["vendor"], 2500, "own1")
        assert data["status"] == "REPORTED"
