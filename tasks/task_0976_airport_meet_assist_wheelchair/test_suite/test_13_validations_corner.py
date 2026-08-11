"""Corner queue B — validations section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, submit_request, set_clock,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


class TestMissingXUserRole:
    def test_missing_x_user_role_returns_401(self, api):
        """PRD §2.1: "A request missing either header, presenting a malformed
        identifier, or carrying a role outside the enumerated set is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_x_user_role_returns_401
        """
        resp = api_client._request(
            "GET", f"/maa/airports/{NON_EXISTENT_UUID}",
            headers={},  # no X-User-Role, no X-User-ID
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRequesterCannotSetPosture:
    def test_requester_cannot_set_posture_returns_403(self, api):
        """PRD §2.1: "A request whose role is well-formed but not on the
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: posture endpoint is `OpsManager`-only.

        Design: Corner/validations/requester_cannot_set_posture_returns_403
        """
        airport = create_airport(iata_code="CVG", meet_buffer_minutes=15)
        resp = api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, REQ,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestStaleVersionOcc:
    def test_stale_version_occ_conflict_returns_412(self, api):
        """PRD §2.7: "Posting a `SUBMIT` or `CANCEL` against an assist request
        requires the request body to carry `expected_assist_request_version`
        holding the value of the request's `version` field the client last
        observed. If the version on the server has since advanced... the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_occ_conflict_returns_412
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="IND", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="IND1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P IND", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="IND1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        create_leg(request["id"], segment["id"],
                   leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        # Capture the version the client last observed, then SUBMIT — PRD §2.7:
        # "posting an assist-request lifecycle event increments the request's
        # `version` by 1", so the captured value is stale afterwards.
        cur = get_success_data(api_client.get_assist_request(request["id"], REQ))
        stale_v = cur["version"]
        submit_request(request["id"], expected_version=stale_v)
        # CANCEL with the pre-SUBMIT version — OCC must reject with 412
        resp = api_client.post_assist_request_event(
            request["id"],
            {"event_type": "CANCEL", "expected_assist_request_version": stale_v},
            REQ,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSubmitWithZeroLegs:
    def test_submit_with_zero_legs_rejected(self, api):
        """PRD §3.3: "the request must carry at least one service leg; a submit
        with zero legs is rejected with `ERR_NO_LEGS` (HTTP 409)."

        Design: Corner/validations/submit_with_zero_legs_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        passenger = create_passenger(
            full_name="P NoLegs", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="NL1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        resp = api_client.post_assist_request_event(
            request["id"],
            {"event_type": "SUBMIT",
             "expected_assist_request_version": request["version"]},
            REQ,
        )
        validate_error(resp, ApiErrorId.ERR_NO_LEGS)


class TestSubmitPrivateWithoutCardToken:
    def test_submit_private_billing_without_card_token_rejected(self, api):
        """PRD §3.3: "when `bill_to` is `PRIVATE`, the passenger's
        `private_card_token` must be non-empty, and when `bill_to` is `AIRLINE`,
        the passenger's `airline_pnr` must be non-empty — violations are rejected
        with `ERR_PAYMENT_METHOD_REQUIRED` (HTTP 402)."

        Design: Corner/validations/submit_private_billing_without_card_token_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="JAX", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="JAX1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P JAX", dob="1990-01-01", mobility_code="WCHR",
            # no private_card_token, no airline_pnr
        )
        request = create_assist_request(
            passenger["id"], bill_to="PRIVATE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        cur = get_success_data(api_client.get_assist_request(request["id"], REQ))
        resp = api_client.post_assist_request_event(
            request["id"],
            {"event_type": "SUBMIT",
             "expected_assist_request_version": cur["version"]},
            REQ,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_METHOD_REQUIRED)


class TestMarkPaidOnProvisionalInvoice:
    def test_mark_paid_on_provisional_invoice_rejected(self, api):
        """PRD §3.6: "`MARK_PAID` is valid only on a `FINAL` invoice — a
        provisional invoice is never directly payable."
        PRD §3.6: "Settlement-state violations — marking a provisional invoice
        paid, disputing an invoice not `OPEN`, resolving or writing off an
        invoice not `DISPUTED` — are rejected with `ERR_INVOICE_STATE` (HTTP 409)."

        Design: Corner/validations/mark_paid_on_provisional_invoice_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="SDF", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="SDF1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P SDF", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="SDF1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        request = submit_request(request["id"])
        invoices = get_success_data(api_client.list_request_invoices(request["id"], CLERK))
        prov = next(i for i in invoices if i["invoice_kind"] == "PROVISIONAL")
        # MARK_PAID on PROVISIONAL — rejected
        from test_helpers import make_billing_clerk_headers
        resp = api_client.post_invoice_event(
            prov["id"],
            {"event_type": "MARK_PAID",
             "expected_invoice_version": prov["version"]},
            make_billing_clerk_headers("clerk_x"),
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_STATE)
        # Status remains OPEN
        inv_after = get_success_data(api_client.get_invoice(prov["id"], CLERK))
        assert inv_after["status"] == "OPEN"
