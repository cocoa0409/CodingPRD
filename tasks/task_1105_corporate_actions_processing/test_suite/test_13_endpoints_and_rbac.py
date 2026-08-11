"""Endpoint-side claims (PRD §3.4, §3.6): cancel cascade, amendment listing,
booking-line pinning; error reachability; RBAC exclusivity; segregation of
duties.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_merger_event_confirmed,
    make_missed_entitlement_context, file_claim,
    make_account_holder_headers, make_analyst_headers, make_examiner_headers,
    split_terms, create_security_payload, get_event_version,
    get_entitlement_for,
)
from test_helpers.fixtures import (
    ADMIN, VENDOR, ANALYST_1, ANALYST_2, OPS, EXAMINER, CUSTODIAN,
)
from test_helpers import api_client


class TestCancelEventCascade:
    def test_cancel_voids_elections_and_supersedes_entitlements(self, api):
        """PRD §3.4: "From `CONFIRMED` or `AMENDED`, cancellation supersedes every `PROJECTED` or `FIRM` entitlement (`PROJECTED` → `SUPERSEDED`, `FIRM` → `SUPERSEDED`) and voids every live election (`SUBMITTED` → `VOID`, `WITHDRAWN` → `VOID`), then recomputes each affected account's pending count."

        Design: Corner/endpoints/cancel_event_voids_elections_supersedes_entitlements
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        event, acct = ctx["event"], ctx["account"]
        election = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"])), 201)
        ent = get_entitlement_for(event["id"], acct["id"])
        cancelled = validate_success(api.cancel_event(event["id"], ANALYST_1))
        assert cancelled["status"] == "CANCELLED"
        el_after = get_success_data(api.get_election(election["id"], OPS))
        assert el_after["status"] == "VOID"
        ent_after = get_success_data(api.get_entitlement(ent["id"], OPS))
        assert ent_after["status"] == "SUPERSEDED"


class TestAmendmentsListedUnderEvent:
    def test_amendments_subresource_lists_applied_amendment(self, api):
        """PRD §3.4: "The amendments applied to an event remain listable as a
        permanent audit trail." and "An immutable `EventAmendment` audit record is created pointing back to the event via `event_id`, stamped with `applied_by_user_id` and an `amendment_seq` equal to one plus the count of the event's prior amendments."

        Design: Corner/endpoints/amendments_listed_under_event_subresource
        """
        sec = make_security(ticker="ACME", cusip="CUSPE00003")
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        amendment = validate_success(api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=3),
             "reason": "ratio revised",
             "expected_event_version": event["version"]},
            ANALYST_1), 201)
        data, meta = validate_paginated(api.list_amendments(event["id"], OPS))
        assert meta["total_count"] == 1
        assert data[0]["id"] == amendment["id"]
        assert data[0]["amendment_seq"] == 1
        assert data[0]["event_id"] == event["id"]


class TestBookingLinesFilterableByBooking:
    def test_split_booking_emits_single_lot_mutation_line(self, api):
        """PRD §3.6: "the booking-lines listing can be filtered by `booking_id`, `position_lot_id`, and `entitlement_id`, and the entitlements listing by `event_id`, `account_id`, `status`, and `supersedes_entitlement_id`." PRD §3.6: "Each `BookingLine` records its `booking_id`, the `entitlement_id` it settles, the `position_lot_id` it mutates or creates (null on pure-cash lines), a `line_kind` of `LOT_MUTATION`, `LOT_CREATION`, `CASH_CREDIT`, `CASH_DEBIT`, or `CASH_IN_LIEU`, and three signed deltas" and "Crucially, every lot line also stores `prior_quantity` and `prior_basis_cents` — the lot's values immediately before the line — which is what later makes an exact, recompute-free reversal possible."

        Design: Corner/endpoints/booking_lines_filterable_by_booking
        """
        sec = make_security(ticker="ACME", cusip="CUSPE00004")
        acct = make_account(account_number="A-1", holder_name="One")
        lot = make_lot(acct["id"], sec["id"], quantity=1000,
                       acquisition_date="2026-04-01",
                       cost_basis_total_cents=10000000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        booking = get_success_data(api_client.book_event(event["id"], OPS))
        data, meta = validate_paginated(
            api.list_booking_lines(OPS, params={"booking_id": booking["id"]}))
        # 1000 x 2 = 2000 exact: no fractional remainder, so no CIL line.
        assert meta["total_count"] == 1
        line = data[0]
        assert line["line_kind"] == "LOT_MUTATION"
        assert line["position_lot_id"] == lot["id"]
        assert line["quantity_delta"] == 1000
        assert line["prior_quantity"] == 1000
        assert line["basis_delta_cents"] == 0


class TestAccountNotFound:
    def test_get_nonexistent_account_returns_404(self, api):
        """PRD §2.10: "Each resource type has its own not-found error: `ERR_SECURITY_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_POSITION_LOT_NOT_FOUND`, `ERR_EVENT_SOURCE_NOT_FOUND`, `ERR_SOURCE_NOTIFICATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`" and the catalog ends "`ERR_RECON_BREAK_NOT_FOUND` — all HTTP 404".

        Design: Corner/errors/account_get_nonexistent_returns_404
        """
        resp = api.get_account("99999999-8888-7777-6666-555555555555", ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)


class TestRbacExclusiveDenied:
    def test_account_holder_cannot_create_security(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.1: "A `DeskAdministrator` registers each tradeable instrument".

        Design: Corner/rbac/account_holder_cannot_create_security
        """
        holder = make_account_holder_headers("some-account-id")
        resp = api.create_security(
            create_security_payload(ticker="ACME", cusip="CUSPF00001",
                                    name="Acme Corp"),
            holder)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_vendor_cannot_create_events(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.3: "an `EventAnalyst` assembles at least two raw notifications into a single golden `CorporateActionEvent".

        Design: Corner/rbac/vendor_cannot_create_events
        """
        resp = api.create_event(
            {"security_id": "11111111-2222-3333-4444-555555555555",
             "event_type": "SPLIT", "terms": split_terms(),
             "record_date": "2026-05-15", "payable_date": "2026-05-29",
             "source_notification_ids": [
                 "11111111-2222-3333-4444-555555555555",
                 "22222222-3333-4444-5555-666666666666"]},
            VENDOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_analyst_cannot_book_event(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.6: "Booking is the point of no return, performed by the `OperationsManager`."

        Design: Corner/rbac/analyst_cannot_book_event
        """
        resp = api.book_event("11111111-2222-3333-4444-555555555555", ANALYST_1)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_operations_manager_cannot_decide_claim(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.8: "Decision belongs to the `ClaimsExaminer".

        Design: Corner/rbac/operations_manager_cannot_decide_claim
        """
        resp = api.decide_claim(
            "11111111-2222-3333-4444-555555555555",
            {"decision": "APPROVED"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestSegregationOfDuties:
    def test_scrubber_cannot_confirm_own_event(self, api):
        """PRD §2.8: "The analyst who confirms an event must be a different individual from the analyst who scrubbed it: confirmation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the caller's `X-User-ID` equals the event's `scrubbed_by_user_id`."
        PRD §3.4: "Confirmation moves `DRAFT` → `CONFIRMED`, stamps `confirmed_by_user_id` with the confirmer's identity".

        Design: Corner/rbac/sod_scrubber_cannot_confirm_own_event
        """
        sec = make_security(ticker="ACME", cusip="CUSPF00002")
        event, _, _ = __import__("test_helpers").make_scrubbed_event(
            sec["id"], "SPLIT", split_terms())
        resp = api.confirm_event(event["id"], ANALYST_1)  # scrubber
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        confirmed = validate_success(api.confirm_event(event["id"], ANALYST_2))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by_user_id"] == "analyst-2"

    def test_filer_cannot_decide_own_claim(self, api):
        """PRD §2.8: "the examiner who decides a claim must not be the person who filed it: a claim decision is rejected with `ERR_SEGREGATION_OF_DUTIES` when the caller's `X-User-ID` equals the claim's `filed_by_user_id`."

        Design: Corner/rbac/sod_filer_cannot_decide_own_claim
        """
        ctx = make_missed_entitlement_context(price_per_share_cents=5000,
                                              compensation_pool_cents=100000)
        claim = file_claim(ctx["event"]["id"], ctx["entitlement"]["id"],
                           ctx["account"]["id"], claimed_amount_cents=50000)
        # The filer's X-User-ID is the account id; decide with the same id.
        resp = api.decide_claim(
            claim["id"], {"decision": "APPROVED"},
            make_examiner_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        decided = validate_success(api.decide_claim(
            claim["id"], {"decision": "APPROVED"},
            make_examiner_headers("examiner-9")))
        assert decided["review_status"] == "APPROVED"
