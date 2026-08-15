"""Vendor onboarding, contract terms, standing, and rep credentialing."""
from test_helpers import (
    CLOCK_DEFAULT,
    COORD_1,
    ApiErrorId,
    assert_same_instant,
    assert_vendor,
    assert_vendor_rep,
    coordinator,
    create_case,
    create_credentialed_rep,
    create_rep,
    create_request,
    create_room,
    create_vendor,
    get_success_data,
    is_valid_uuid,
    make_nurse_headers,
    make_scheduler_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    approve_credential_payload,
    create_request_payload,
    create_tray_payload,
    create_vendor_payload,
)


class TestVendorOnboarding:
    def test_vendor_create_applies_contract_defaults(self, api):
        """PRD: "The creation payload also fixes the vendor's late-delivery
        contract: `late_grace_minutes`, the number of grace minutes subtracted
        from any lateness before billing, which defaults to 15 when omitted and
        may never be negative; `late_rate_per_hour_cents`, the penalty rate per
        billable hour, which must be greater than zero; `late_penalty_cap_cents`,
        the per-assessment cap applied separately to the time charge and to the
        delay surcharge, which must be greater than zero; and
        `delay_surcharge_per_minute_cents`, the surcharge rate per minute of
        vendor-attributable case delay, which defaults to 0 and may never be
        negative."
        PRD: "New vendors begin `ACTIVE` with both rollups,
        `outstanding_penalty_cents` and `outstanding_liability_cents`,
        initialized to zero."
        PRD: "Before any clock call has been made, the current time is exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/vendor_create_applies_contract_defaults
        """
        payload = {
            "vendor_name": "Acme Surgical",
            "vendor_code": "ACME",
            "late_rate_per_hour_cents": 5000,
            "late_penalty_cap_cents": 20000,
        }
        resp = api.create_vendor(payload, coordinator())
        vendor = validate_success(resp, 201)
        assert_vendor(vendor)
        assert vendor["late_grace_minutes"] == 15, \
            "late_grace_minutes defaults to 15 when omitted"
        assert vendor["delay_surcharge_per_minute_cents"] == 0, \
            "delay_surcharge_per_minute_cents defaults to 0 when omitted"
        assert vendor["status"] == "ACTIVE"
        assert vendor["outstanding_penalty_cents"] == 0
        assert vendor["outstanding_liability_cents"] == 0
        assert is_valid_uuid(vendor["id"])
        # Created before any clock call: stamped from the logical clock default.
        assert_same_instant(vendor["created_at"], CLOCK_DEFAULT,
                            "vendor.created_at")

        fetched = validate_success(
            api.get_vendor(vendor["id"], make_scheduler_headers()))
        assert fetched["late_grace_minutes"] == 15
        assert fetched["delay_surcharge_per_minute_cents"] == 0
        assert fetched["status"] == "ACTIVE"

    def test_get_single_vendor_returns_persisted_contract(self, api):
        """PRD: "The creation payload also fixes the vendor's late-delivery
        contract: `late_grace_minutes`, the number of grace minutes subtracted
        from any lateness before billing, which defaults to 15 when omitted and
        may never be negative; `late_rate_per_hour_cents`, the penalty rate per
        billable hour, which must be greater than zero; `late_penalty_cap_cents`,
        the per-assessment cap applied separately to the time charge and to the
        delay surcharge, which must be greater than zero; and
        `delay_surcharge_per_minute_cents`, the surcharge rate per minute of
        vendor-attributable case delay, which defaults to 0 and may never be
        negative."
        PRD: "A `VendorCoordinator` onboards each instrument vendor by
        registering its legal `vendor_name` together with a unique
        `vendor_code`"

        Design: Corner/endpoints/get_single_vendor_returns_persisted_contract
        """
        vendor = create_vendor(
            vendor_name="Acme Surgical", vendor_code="ACME",
            late_grace_minutes=20, late_rate_per_hour_cents=7500,
            late_penalty_cap_cents=15000,
            delay_surcharge_per_minute_cents=100)
        fetched = validate_success(
            api.get_vendor(vendor["id"], make_nurse_headers()))
        assert_vendor(fetched)
        assert fetched["vendor_name"] == "Acme Surgical"
        assert fetched["vendor_code"] == "ACME"
        assert fetched["late_grace_minutes"] == 20
        assert fetched["late_rate_per_hour_cents"] == 7500
        assert fetched["late_penalty_cap_cents"] == 15000
        assert fetched["delay_surcharge_per_minute_cents"] == 100

    def test_duplicate_vendor_code_rejected(self, api):
        """PRD: "A `VendorCoordinator` onboards each instrument vendor by
        registering its legal `vendor_name` together with a unique
        `vendor_code`; a code already present on any other vendor is rejected
        with `ERR_DUPLICATE_VENDOR_CODE` (409)."

        Design: Corner/validations/duplicate_vendor_code_rejected
        """
        create_vendor()
        resp = api.create_vendor(
            create_vendor_payload(vendor_name="Acme Clone", vendor_code="ACME",
                                  late_rate_per_hour_cents=100,
                                  late_penalty_cap_cents=100),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_CODE)
        _rows, meta = validate_paginated(api.list_vendors(coordinator()))
        assert meta["total_count"] == 1, "no second vendor may be persisted"


class TestVendorStanding:
    def test_vendor_suspended_blocks_request_create(self, api):
        """PRD: "Suspending moves a vendor from `ACTIVE` to `SUSPENDED`; a
        suspended vendor blocks both the creation of new loaner requests and
        the approval of access passes, each failing with
        `ERR_VENDOR_NOT_ACTIVE` (409)."
        PRD: "Reinstating returns a `SUSPENDED` vendor to `ACTIVE`."

        Design: Corner/validations/vendor_suspended_blocks_request_create
        """
        vendor = create_vendor()
        room = create_room()
        case = create_case(room["id"], case_number="C-1",
                           scheduled_start_at="2026-08-10T09:00:00Z",
                           scheduled_end_at="2026-08-10T12:00:00Z")

        suspended = validate_success(api.suspend_vendor(vendor["id"],
                                                        coordinator()))
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_request(
            create_request_payload(case["id"], vendor["id"],
                                   priority_class="STANDARD"),
            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

        reinstated = validate_success(api.reinstate_vendor(vendor["id"],
                                                           coordinator()))
        assert reinstated["status"] == "ACTIVE"
        request = validate_success(
            api.create_request(
                create_request_payload(case["id"], vendor["id"],
                                       priority_class="STANDARD"),
                make_scheduler_headers()), 201)
        assert request["status"] == "DRAFT"

    def test_vendor_terminate_with_open_request_rejected(self, api):
        """PRD: "Termination is terminal in both directions — from `ACTIVE` or
        from `SUSPENDED` the vendor moves to `TERMINATED` — but only when the
        vendor has no open work: no loaner request of the vendor in `DRAFT`,
        `SUBMITTED`, or `APPROVED`, no penalty assessment in `ACCRUING` or
        `ASSESSED`, and no damage or loss claim in `FILED`, `APPORTIONED`, or
        `DISPUTED`. Any open item rejects the termination with
        `ERR_VENDOR_HAS_OPEN_WORK` (409)."

        Design: Corner/validations/vendor_terminate_with_open_request_rejected
        """
        vendor = create_vendor()
        room = create_room()
        case = create_case(room["id"], case_number="C-1",
                           scheduled_start_at="2026-08-10T09:00:00Z",
                           scheduled_end_at="2026-08-10T12:00:00Z")
        request = create_request(case["id"], vendor["id"], "STANDARD")
        tray = get_success_data(
            api.add_tray(request["id"], create_tray_payload(),
                         make_scheduler_headers()), 201)
        get_success_data(api.submit_request(request["id"],
                                            make_scheduler_headers()))
        get_success_data(api.decide_request(request["id"], {"decision": "APPROVE"},
                                            coordinator()))

        resp = api.terminate_vendor(vendor["id"], coordinator())
        validate_error(resp, ApiErrorId.ERR_VENDOR_HAS_OPEN_WORK)
        assert validate_success(api.get_vendor(vendor["id"],
                                               coordinator()))["status"] == "ACTIVE"

        # Cancelling the request clears the open work; terminate then succeeds.
        get_success_data(api.cancel_request(request["id"],
                                            make_scheduler_headers()))
        terminated = validate_success(api.terminate_vendor(vendor["id"],
                                                           coordinator()))
        assert terminated["status"] == "TERMINATED"
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "CANCELLED", \
            "request cancel cascade cancels its non-terminal trays"


class TestCredentialing:
    def test_credential_expiry_in_past_rejected(self, api):
        """PRD: "In every case the coordinator supplies a
        `credential_expires_at` that must lie strictly after the current clock
        time — an expiry at or before now is rejected with
        `ERR_CREDENTIAL_EXPIRY_PAST` (422)"

        Design: Corner/validations/credential_expiry_in_past_rejected
        """
        vendor = create_vendor()
        rep = create_rep(vendor["id"])
        assert rep["credential_status"] == "PENDING_VERIFICATION"

        resp = api.approve_credential(
            rep["id"],
            approve_credential_payload(
                credential_expires_at="2026-07-01T00:00:00Z"),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRY_PAST)
        assert validate_success(
            api.get_rep(rep["id"], coordinator()))["credential_status"] \
            == "PENDING_VERIFICATION"

        ok = validate_success(
            api.approve_credential(
                rep["id"],
                approve_credential_payload(
                    credential_expires_at="2026-08-10T00:00:00Z"),
                coordinator()))
        assert_vendor_rep(ok)
        assert ok["credential_status"] == "ACTIVE"

    def test_rep_credential_expiry_sweep_and_renewal(self, api):
        """PRD: "Independently of any manual action, the clock sweep expires
        credentials: a rep whose `credential_expires_at` has been reached or
        passed moves from `ACTIVE` to `EXPIRED` automatically."
        PRD: "Credential approval moves a rep from `PENDING_VERIFICATION` to
        `ACTIVE`, and the same approval action also serves as the credential
        cycle: from `EXPIRED` back to `ACTIVE` as a renewal, and from `ACTIVE`
        to `ACTIVE` as an extension."

        Design: Corner/state_machines/rep_credential_expiry_sweep_and_renewal
        """
        vendor = create_vendor()
        rep = create_credentialed_rep(vendor["id"],
                                      expires="2026-08-04T00:00:00Z")
        assert rep["credential_status"] == "ACTIVE"
        assert_same_instant(rep["credential_expires_at"],
                            "2026-08-04T00:00:00Z",
                            "rep.credential_expires_at")

        # Sweep at exactly the expiry instant: "reached or passed" is inclusive.
        get_success_data(api.set_clock("2026-08-04T00:00:00Z", coordinator()))
        swept = validate_success(api.get_rep(rep["id"], coordinator()))
        assert swept["credential_status"] == "EXPIRED"

        renewed = validate_success(
            api.approve_credential(
                rep["id"],
                approve_credential_payload(
                    credential_expires_at="2026-08-12T00:00:00Z",
                    or_access_level="SCRUB_ASSIST"),
                coordinator()))
        assert renewed["credential_status"] == "ACTIVE"
        assert_same_instant(renewed["credential_expires_at"],
                            "2026-08-12T00:00:00Z",
                            "rep.credential_expires_at")
        assert renewed["or_access_level"] == "SCRUB_ASSIST"
