"""Entity-specific not-found codes, reachable rejection codes on writes and list
reads, and the program's immediate-consistency guarantees on cascading writes."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error, validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_fee_schedule_read_with_an_unknown_id_is_not_found(api):
    """A well-formed identifier matching no FeeSchedule answers the schedule's own 404 code in the error envelope.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Exactly one schedule exists and it is ACTIVE; the queried identifier is a
    different, well-formed UUID, so only the existence check can fire.

    Design: Corner/errors/fee_schedule_read_with_an_unknown_id_is_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api)

    response = api.get_fee_schedule(NON_EXISTENT_UUID, U.BILLING_CLERK)
    error_data = validate_error(response, E.ERR_FEE_SCHEDULE_NOT_FOUND, expected_status=404)
    assert response.json()["response_type"] == "error"
    assert error_data["message"].strip()

    real = A.data_of(api.get_fee_schedule(schedule_id, U.BILLING_CLERK))
    A.assert_status(real, "ACTIVE")


def test_alarm_company_read_with_an_unknown_id_is_not_found(api):
    """The companyId segment resolves against AlarmCompany alone, so both an unknown UUID and a real premises id in that position answer the company 404.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.5: "Path parameters are resolved strictly left to right, so the leftmost unresolvable segment determines the error."

    A premises identifier is a well-formed UUID that names no AlarmCompany, so
    the code names the entity the segment addresses, not the shape of the value.

    Design: Corner/errors/alarm_company_read_with_an_unknown_id_is_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)

    validate_error(
        api.get_alarm_company(NON_EXISTENT_UUID, U.PERMIT_CLERK),
        E.ERR_ALARM_COMPANY_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_alarm_company(site_id, U.PERMIT_CLERK),
        E.ERR_ALARM_COMPANY_NOT_FOUND,
        expected_status=404,
    )

    real = A.data_of(api.get_alarm_company(company_id, U.PERMIT_CLERK))
    A.assert_status(real, "ACTIVE")


def test_alarm_system_read_with_an_unknown_id_is_not_found(api):
    """An unknown systemId read by an entity-backed permit holder answers the system 404 rather than the ownership refusal.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."
    PRD §2.10: "The service therefore evaluates its checks in one fixed sequence and returns the **first** failure it finds; later checks are never reached."

    Existence sits at positions 6 and 7 and ownership at position 8, so the 404
    wins: ownership could not be evaluated for a row that does not exist.

    Design: Corner/errors/alarm_system_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    holder = bundle.holder_headers

    validate_error(
        api.get_alarm_system(NON_EXISTENT_UUID, holder),
        E.ERR_ALARM_SYSTEM_NOT_FOUND,
        expected_status=404,
    )

    own = A.data_of(api.get_alarm_system(bundle.system_id, holder))
    A.assert_status(own, "PERMITTED")


def test_site_contact_read_with_an_unknown_id_is_not_found(api):
    """An unknown contactId answers the roster entry's own 404 and leaves the live roster and its premises counter untouched.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §3.9: "Fourth, the three derived counts are recomputed: `ecv_callable_contact_count` as the number of contacts that are `ACTIVE` with `is_ecv_callable` true, `unpermitted_system_count` as the number of systems in `UNPERMITTED`, and `lifted_suspension_count` as the number of suspension orders in `LIFTED`."

    Two callable contacts were added and none removed, so the filtered listing
    reports 2 rows and the premises counter still reads 2 after the failed read.

    Design: Corner/errors/site_contact_read_with_an_unknown_id_is_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(api)
    X.create_contacts(api, site_id, 2)

    validate_error(
        api.get_site_contact(NON_EXISTENT_UUID, U.PERMIT_CLERK),
        E.ERR_SITE_CONTACT_NOT_FOUND,
        expected_status=404,
    )

    listing = api.list_site_contacts(U.PERMIT_CLERK, {"alarm_site_id": site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 2)
    assert X.get_site(api, site_id)["ecv_callable_contact_count"] == 2


def test_dispatch_request_read_with_an_unknown_id_is_not_found(api):
    """An unknown requestId answers the dispatch request's own 404 on the read and on the validate action, leaving the real request untouched.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared."

    Path existence sits at positions 6 and 7 and the declared transition at
    position 17, so validate on an unknown id answers the same 404. The real
    request was created and never acted on, so it is still SUBMITTED at version 1.

    Design: Corner/errors/dispatch_request_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api)
    request_id = X.submit_dispatch_request(
        api, bundle, bundle.system_id, "2026-09-15T03:09:00Z"
    )

    validate_error(
        api.get_dispatch_request(NON_EXISTENT_UUID, U.DISPATCH_SUPERVISOR),
        E.ERR_DISPATCH_REQUEST_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.validate_dispatch_request(NON_EXISTENT_UUID, U.DISPATCH_SUPERVISOR),
        E.ERR_DISPATCH_REQUEST_NOT_FOUND,
        expected_status=404,
    )

    real = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(real, "SUBMITTED")
    assert real["version"] == 1


def test_suspension_order_read_with_an_unknown_id_is_not_found(api):
    """With no suspension order in existence the read of an unknown orderId still answers the order's own 404, while the filtered listing answers 200 with no rows.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."

    Serving takes the same path segment, so it answers the same 404 before any
    state or basis precondition of the order can be evaluated.

    Design: Corner/errors/suspension_order_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)

    validate_error(
        api.get_suspension_order(NON_EXISTENT_UUID, U.BILLING_CLERK),
        E.ERR_SUSPENSION_ORDER_NOT_FOUND,
        expected_status=404,
    )

    listing = api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)

    validate_error(
        api.serve_suspension_order(NON_EXISTENT_UUID, U.PROGRAM_ADMIN),
        E.ERR_SUSPENSION_ORDER_NOT_FOUND,
        expected_status=404,
    )


def test_penalty_invoice_read_with_an_unknown_id_is_not_found(api):
    """An unknown invoiceId answers the invoice's own 404 on the read and on the adjustment endpoint, before any revision or amount check runs.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."
    PRD §2.10: "Every one of these is checked before any state precondition, so a caller working from a stale read learns that fact rather than receiving a state complaint."

    Existence at positions 6 and 7 precedes the revision guards at positions 11
    to 16, so a fully formed adjustment against an unknown invoice is a 404. The
    premises' issue-fee invoice is 5000 plus a 500-cent administrative floor, so
    the untouched invoice still owes 5500 cents.

    Design: Corner/errors/penalty_invoice_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]

    validate_error(
        api.get_penalty_invoice(NON_EXISTENT_UUID, bundle.holder_headers),
        E.ERR_PENALTY_INVOICE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.adjust_invoice(
            NON_EXISTENT_UUID,
            {
                "adjustment_kind": "REDUCE",
                "amount_cents": 100,
                "reason": "Reduction against an invoice that does not exist.",
                "expected_penalty_invoice_version": 1,
            },
            U.PROGRAM_ADMIN,
        ),
        E.ERR_PENALTY_INVOICE_NOT_FOUND,
        expected_status=404,
    )

    A.assert_invoice_totals(
        X.get_invoice(api, invoice["id"]),
        assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        outstanding_cents=5500,
    )


def test_payment_record_read_with_an_unknown_id_is_not_found(api):
    """An unknown paymentId answers the receipt's own 404 on the read and on the void endpoint, never the void-window refusal.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."
    PRD §3.9: "Only an administrator voids, supplying a `void_reason`, and only inside the window: the logical clock must be at or before `tendered_on` plus 2 whole days, the boundary inclusive, and none of the payment's allocations may target an invoice whose `collections_stage` has since become `WRITTEN_OFF`, else `ERR_PAYMENT_VOID_WINDOW_CLOSED`."

    Existence at positions 6 and 7 precedes the temporal windows at positions 30
    to 35, so a probe can never learn from the window code whether a receipt
    exists. The real tender of 5500 cents settles the 5500-cent issue-fee
    invoice exactly, so it is APPLIED with the whole amount allocated.

    Design: Corner/errors/payment_record_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    payment_id = X.post_payment(
        api, bundle, 5500, C.CLOCK_STARTUP_UTC, method="CARD"
    )

    validate_error(
        api.get_payment_record(NON_EXISTENT_UUID, U.BILLING_CLERK),
        E.ERR_PAYMENT_RECORD_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.void_payment_record(
            NON_EXISTENT_UUID,
            {"void_reason": "Void of a receipt that does not exist."},
            U.PROGRAM_ADMIN,
        ),
        E.ERR_PAYMENT_RECORD_NOT_FOUND,
        expected_status=404,
    )

    payment = X.get_payment(api, payment_id)
    A.assert_status(payment, "APPLIED")
    A.assert_money_cents(payment["allocated_cents"], 5500, "allocated_cents")


def test_payment_allocation_read_with_an_unknown_id_is_not_found(api):
    """An unknown allocationId answers the ledger line's own 404 and never falls back to the parent payment's code.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §3.9: "Every non-zero application creates a `PaymentAllocation` — which carries only an `id` and a `created_at` beyond its own fields, having no revision counter of its own — recording the `payment_record_id`, the `penalty_invoice_id`, the `amount_cents` applied, a 1-based `sequence_index` giving its position in the order that produced it, and `status` of `APPLIED`."

    The 5500-cent tender exhausts the single 5500-cent issue-fee invoice, so the
    waterfall produces exactly one allocation line of 5500 cents against it.

    Design: Corner/errors/payment_allocation_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    payment_id = X.post_payment(api, bundle, 5500, C.CLOCK_STARTUP_UTC, method="CARD")

    validate_error(
        api.get_payment_allocation(NON_EXISTENT_UUID, U.PROGRAM_ADMIN),
        E.ERR_PAYMENT_ALLOCATION_NOT_FOUND,
        expected_status=404,
    )

    listing = api.list_payment_allocations(
        U.PROGRAM_ADMIN, {"payment_record_id": payment_id}
    )
    validate_success(listing, 200)
    rows = A.assert_total_count(listing, 1)
    A.assert_money_cents(rows[0]["amount_cents"], 5500, "allocation amount_cents")
    assert rows[0]["penalty_invoice_id"] == invoice["id"]


def test_compliance_report_read_with_an_unknown_id_is_not_found(api):
    """An unknown reportId answers the report's own 404 on the read and on the correction endpoint, never the correction-limit code.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`, `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`, `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`, `allocationId` and `reportId`, and each unresolvable identifier produces its own code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`, `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`, `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`, `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`, `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`, `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "All fifteen entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."
    PRD §3.10: "Only the company itself may correct, else `ERR_NOT_RESOURCE_OWNER`; at least one of the resupplied metrics must differ from the stored value, else `ERR_NO_REPORTABLE_VARIANCE`; and `correction_count` must be strictly below 2 as evaluated **before** the increment, else `ERR_CORRECTION_LIMIT_REACHED` — so a report may be corrected twice and no more."
    PRD §3.10: "Acceptance moves the report to the terminal `ACCEPTED`, stamping `reviewed_at` and `reviewed_by_user_id`, admitting the `period_score` into the company's score set, and resetting `consecutive_flagged_report_count`."
    PRD §3.10: "The report is created in `SUBMITTED` with `correction_count` 0 and `reviewed_at`, `reviewed_by_user_id` and `variance_notes` null."

    Path existence at positions 6 and 7 precedes the program constraints at
    positions 36 to 53, so the correction-limit aggregate is never reached and
    the accepted report keeps its correction count of 0.

    Design: Corner/errors/compliance_report_read_with_an_unknown_id_is_not_found
    """
    bundle = X.setup_program_baseline(api)
    X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-30T00:00:00Z")
    report_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(api, report_id, "ACCEPT", variance_notes="Counts reconcile exactly.")

    validate_error(
        api.get_compliance_report(NON_EXISTENT_UUID, U.REVIEW_OFFICER),
        E.ERR_COMPLIANCE_REPORT_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.correct_compliance_report(
            NON_EXISTENT_UUID,
            {
                "reported_dispatch_count": 2,
                "reported_cancellation_count": 0,
                "ecv_attempt_count": 2,
            },
            bundle.operator_headers,
        ),
        E.ERR_COMPLIANCE_REPORT_NOT_FOUND,
        expected_status=404,
    )

    report = X.get_report(api, report_id)
    A.assert_status(report, "ACCEPTED")
    assert report["correction_count"] == 0


def test_hold_session_on_a_docket_with_no_scheduled_appeals_is_rejected(api):
    """Holding a session at exactly its start instant with no appeal seated is refused for emptiness, not for a session that has not started.

    PRD §3.6: "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`, the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket must seat at least one appeal, else `ERR_DOCKET_EMPTY`."
    PRD §3.6: "The docket is created in `OPEN` with `scheduled_appeal_count` at 0 and `held_at` null."
    PRD §5: "Every failure response carries one of the identifiers below in `data.error_id`, with the HTTP status shown."

    The clock is parked at exactly 2026-10-05T14:00:00Z, the session start, so
    the inclusive start boundary is satisfied and the acting officer is the
    docket's own ho-03; only the emptiness precondition can reject the call, and
    the catalogue lists ERR_DOCKET_EMPTY at HTTP 409. Nothing moves on the
    docket, so it stays OPEN at version 1 with no seats taken.

    Design: Corner/errors/hold_session_on_a_docket_with_no_scheduled_appeals_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    X.set_clock(api, "2026-10-05T14:00:00Z")

    validate_error(
        api.hold_session(docket_id, {}, U.HEARING_OFFICER),
        E.ERR_DOCKET_EMPTY,
        expected_status=409,
    )

    docket = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    A.assert_status(docket, "OPEN")
    assert docket["held_at"] is None
    assert docket["scheduled_appeal_count"] == 0
    assert docket["version"] == 1


def test_dispatch_requests_list_with_per_page_above_one_hundred_is_rejected(api):
    """A per_page of 101 is rejected outright rather than silently clamped to the declared maximum of 100.

    PRD §2.3: "Every list endpoint is paginated with two optional query inputs. `page` is an integer that must be at or above 1 and defaults to 1. `per_page` is an integer that must lie between 1 and 100 inclusive and defaults to 10. A `page` below 1, a `per_page` outside the range 1 to 100, or a sort key that does not name a declared field of the entity being listed is rejected with `ERR_INVALID_PAGINATION`."
    PRD §2.10: "**Position 59 — paging.** Last of all, on list reads, `page` and `per_page` are range-checked and any sort key is checked against the listed entity's declared fields, failing with `ERR_INVALID_PAGINATION`."
    PRD §5: "Every failure response carries one of the identifiers below in `data.error_id`, with the HTTP status shown."

    The ceiling of 100 is inclusive, so 101 is the first rejected value on the
    upper edge; the catalogue lists ERR_INVALID_PAGINATION at HTTP 422. The same
    call at the boundary value 100 succeeds and sees the one existing request,
    which proves the rejection was not a clamp.

    Design: Corner/errors/dispatch_requests_list_with_per_page_above_one_hundred_is_rejected
    """
    bundle = X.setup_program_baseline(api)
    request_id = X.submit_dispatch_request(
        api, bundle, bundle.system_id, "2026-09-15T03:09:00Z"
    )

    validate_error(
        api.list_dispatch_requests(
            U.DISPATCH_SUPERVISOR,
            {"alarm_site_id": bundle.site_id, "page": 1, "per_page": 101},
        ),
        E.ERR_INVALID_PAGINATION,
        expected_status=422,
    )

    allowed = api.list_dispatch_requests(
        U.DISPATCH_SUPERVISOR,
        {"alarm_site_id": bundle.site_id, "page": 1, "per_page": 100},
    )
    validate_success(allowed, 200)
    rows, meta = validate_paginated(allowed)
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [request_id]
    A.assert_status(A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR)), "SUBMITTED")


def test_suspension_orders_list_with_page_below_one_is_rejected(api):
    """A page of 0 is rejected even when the filtered collection holds no rows, so paging is range-checked before retrieval.

    PRD §2.3: "Every list endpoint is paginated with two optional query inputs. `page` is an integer that must be at or above 1 and defaults to 1. `per_page` is an integer that must lie between 1 and 100 inclusive and defaults to 10. A `page` below 1, a `per_page` outside the range 1 to 100, or a sort key that does not name a declared field of the entity being listed is rejected with `ERR_INVALID_PAGINATION`."
    PRD §2.10: "**Position 59 — paging.** Last of all, on list reads, `page` and `per_page` are range-checked and any sort key is checked against the listed entity's declared fields, failing with `ERR_INVALID_PAGINATION`."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    No suspension order has ever been created, so a caller cannot use the zero
    page to probe emptiness: the 422 arrives regardless, while page 1 answers 200
    with a total_count of 0 and no further rows.

    Design: Corner/errors/suspension_orders_list_with_page_below_one_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)

    validate_error(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN,
            {"alarm_site_id": bundle.site_id, "page": 0, "per_page": 25},
        ),
        E.ERR_INVALID_PAGINATION,
        expected_status=422,
    )

    allowed = api.list_suspension_orders(
        U.PROGRAM_ADMIN,
        {"alarm_site_id": bundle.site_id, "page": 1, "per_page": 25},
    )
    validate_success(allowed, 200)
    rows, meta = validate_paginated(allowed)
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_immediate_every_cascade_hop_is_visible_in_the_writing_response(api):
    """A chargeable determination returns the fully priced row, and the premises roll-up and the new invoice are already settled when read straight afterwards with no clock movement between.

    PRD §3.5: "It then sets `determination` to `COUNTED`, stamps `determined_at` with the logical clock and `determined_by_user_id` with the acting `X-User-ID`, assigns the occurrence numbering, prices the incident, and bills it."
    PRD §3.5: "Every input to that computation is preserved on the incident as `fee_basis`, holding `tier_base_cents`, `occupancy_multiplier`, `non_ecv_surcharge_applied` and `unpermitted_multiplier_applied` as booleans recording whether each factor differed from 1, `cap_applied`, and `aggravation_cents`."
    PRD §3.5: "When the assessed fee is above zero a `FALSE_ALARM_FEE` invoice is issued; when the tier base is zero under the free allowance and no aggravation applies, no invoice row is created at all and no administrative fee is charged. The premises' `chargeable_count_rolling_365`, `chargeable_count_permit_year`, `chargeable_count_window`, `lifetime_assessed_cents`, `outstanding_balance_cents`, `renewal_block_active` and `response_status` are then all recomputed."
    PRD §3.9: "Every request that creates, adjusts, voids or pays an invoice, changes a contact, changes a system's status, or changes a suspension order's status ends by recomputing the premises in a pinned seven-step order, because each step reads the one before it. First, per invoice, `outstanding_cents` is `assessed_cents` minus `paid_cents` minus `adjusted_cents`, floored at zero. Second, `outstanding_balance_cents` is the sum of `outstanding_cents` over the premises' invoices whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose `collections_stage` is not `WRITTEN_OFF`."
    PRD §3.8: "`issued_on` is the logical clock and `due_on` is `issued_on` plus `invoice_due_days` whole days."

    The first two occurrences sit at indexes 1 and 2, inside the free allowance
    of 2, so their tier base is zero and neither issues an invoice. The third is
    the first chargeable one: the marginal tier for index 3 is 10000 cents, the
    COMMERCIAL occupancy multiplier is 1.50, the request used TWO_CALL_ECV so no
    surcharge applies, the system was permitted at occurrence so no unpermitted
    factor applies, and 10000 x 1.50 = 15000 which is under the 100000-cent cap,
    giving assessed_fee_cents 15000 with no aggravation. Its invoice carries a
    subtotal of 15000, an administrative fee of 0.05 x 15000 = 750 inside the
    500-to-5000 clamp, and an assessment of 15750; issued at the determination
    clock of 2026-09-20T01:00:00Z it falls due 30 whole days later. The premises
    then owes three 5500-cent issue fees for its three systems plus that 15750,
    which is 32250 cents, none of it paid.

    Design: Corner/consistency_model/immediate_every_cascade_hop_is_visible_in_the_writing_response
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=3,
    )
    X.create_counted_incident(
        api, bundle, bundle.system_ids[0], "2026-09-15T03:09:00Z", cause_code="OPERATOR_ERROR"
    )
    X.create_counted_incident(
        api, bundle, bundle.system_ids[1], "2026-09-16T04:00:00Z", cause_code="OPEN_DOOR_WINDOW"
    )
    third = X.create_reported_incident(
        api, bundle, bundle.system_ids[2], "2026-09-17T04:00:00Z", cause_code="EQUIPMENT_MALFUNCTION"
    )

    written = api.determine_incident(
        third.incident_id,
        F.determination_payload("COUNTED", review_notes="Third occurrence: first chargeable tier."),
        U.REVIEW_OFFICER,
    )
    validate_success(written, 200)
    incident = get_success_data(written)
    A.assert_status(incident, "COUNTED", field="determination")
    assert incident["occurrence_index"] == 3
    A.assert_money_cents(incident["assessed_fee_cents"], 15000, "assessed_fee_cents")
    A.assert_fee_basis(
        incident["fee_basis"],
        tier_base_cents=10000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=False,
    )

    site = A.data_of(api.get_alarm_site(bundle.site_id, U.REVIEW_OFFICER))
    assert site["chargeable_count_window"] == 3
    A.assert_money_cents(site["outstanding_balance_cents"], 32250, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 32250, "lifetime_assessed_cents")

    listing = api.list_penalty_invoices(
        U.BILLING_CLERK,
        {"false_alarm_incident_id": third.incident_id, "page": 1, "per_page": 25},
    )
    validate_success(listing, 200)
    invoice = A.assert_total_count(listing, 1)[0]
    A.assert_invoice_totals(
        invoice, subtotal_cents=15000, admin_fee_cents=750, assessed_cents=15750,
        outstanding_cents=15750, paid_cents=0, adjusted_cents=0, payment_status="UNPAID",
    )
    assert invoice["due_on"].startswith("2026-10-20T01:00:00")


def test_immediate_no_denormalised_counter_lags_behind_its_source_row(api):
    """Three denormalised counters on two different parents — the premises' callable-contact count and outstanding balance and the company's monitored-system count — are each already correct in the very first read after the write that moved them.

    PRD §3.2: "Both adding and removing a contact recompute `ecv_callable_contact_count` on the premises and bump that premises' `version` by 1 — which is why a client holding an `expected_alarm_site_version` from before a roster edit will be turned away on its next guarded write."
    PRD §3.2: "A contact's `status` is `ACTIVE` or `REMOVED`; removal is soft, setting `status` to `REMOVED` and stamping `removed_at` (null while active) rather than deleting the row."
    PRD §3.9: "Every request that creates, adjusts, voids or pays an invoice, changes a contact, changes a system's status, or changes a suspension order's status ends by recomputing the premises in a pinned seven-step order, because each step reads the one before it."
    PRD §3.9: "Fourth, the three derived counts are recomputed: `ecv_callable_contact_count` as the number of contacts that are `ACTIVE` with `is_ecv_callable` true, `unpermitted_system_count` as the number of systems in `UNPERMITTED`, and `lifted_suspension_count` as the number of suspension orders in `LIFTED`. Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."
    PRD §3.8: "Settlement — `UNPAID → PAID` or `PARTIALLY_PAID → PAID` — occurs exactly when `paid_cents` plus `adjusted_cents` equals `assessed_cents` after the write, whether that is reached by an allocation covering the remainder or by a `WAIVE` adjustment; `outstanding_cents` becomes 0, the stage resettles to `CURRENT` on the next nightly run, and when every invoice for the premises is `PAID` a `REINSTATEMENT_PENDING` suspension order becomes liftable."
    PRD §3.3: "The premises' balances, lifetime assessment and renewal block flag are recomputed, the premises' `version` is bumped by 1, and the monitoring company's `monitored_system_count` is incremented."
    PRD §3.10: "`monitored_system_count` as the number of systems it monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`"

    Three ACTIVE callable contacts minus one leaves 2, still at the ECV minimum.
    The single approval billed 5000 plus a 500-cent administrative fee floor, so
    the premises owes 5500 before the tender and 0 immediately after it, and 5500
    never reaches the 50000-cent delinquency block in either direction. One
    system is monitored, so the company's count is 1. Every read below is a first
    read: no nightly run and no retry stands between it and the write it reflects.

    Design: Corner/consistency_model/immediate_no_denormalised_counter_lags_behind_its_source_row
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, contact_count=3, system_count=1
    )

    removed = api.delete_site_contact(bundle.contact_ids[2], U.PERMIT_CLERK)
    validate_success(removed, 200)

    after_removal = A.data_of(api.get_alarm_site(bundle.site_id, U.PERMIT_CLERK))
    assert after_removal["ecv_callable_contact_count"] == 2
    A.assert_money_cents(
        after_removal["outstanding_balance_cents"], 5500, "outstanding_balance_cents"
    )
    assert after_removal["renewal_block_active"] is False

    X.post_payment(api, bundle, 5500, C.CLOCK_STARTUP_UTC, method="CARD")

    after_payment = A.data_of(api.get_alarm_site(bundle.site_id, U.BILLING_CLERK))
    A.assert_money_cents(
        after_payment["outstanding_balance_cents"], 0, "outstanding_balance_cents"
    )
    assert after_payment["renewal_block_active"] is False

    company = A.data_of(api.get_alarm_company(bundle.company_id, U.PERMIT_CLERK))
    assert company["monitored_system_count"] == 1
