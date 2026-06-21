"""Application and sales-report state machines: review/reject/resubmit cycle,
dispute/resubmit cycle, initial states, terminal lockdown, and vendor bubble-up.

Covers Difficulty rule non_linear_state_machine and the corner state_machines
instances that exercise the Application and SalesReport pipelines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_vendor_headers, TEST_USERS,
    create_market, create_vendor, create_active_vendor,
    create_submitted_application, create_under_review_application,
    create_rejected_application, setup_present_check_in,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine
# ---------------------------------------------------------------------------
def test_application_reject_resubmit_returns_to_submitted(api):
    """PRD 3.2: "the owning vendor ... may resubmit it, which is legal only from
    REJECTED, returns it to SUBMITTED, clears review_note back to null, and
    increments version, opening a fresh review pass."

    Design: Difficulty/non_linear_state_machine/application_reject_resubmit_cycle
    """
    market = create_market()
    vendor, app = create_rejected_application(market["id"], "CRAFTS", "V1", "v1@x.com")
    vh = make_vendor_headers(vendor["id"])

    resubmitted = validate_success(api.resubmit_application(app["id"], vh), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["review_note"] is None


def test_application_cycle_allows_second_review_pass(api):
    """PRD 3.2: "A MarketAdmin moves a submitted application into review, advancing
    it from SUBMITTED to UNDER_REVIEW; this is legal only while the application is
    SUBMITTED" — so a resubmitted (SUBMITTED) application can be reviewed again,
    demonstrating the REJECTED -> SUBMITTED -> UNDER_REVIEW cycle.

    Design: Difficulty/non_linear_state_machine/application_reject_resubmit_cycle
    """
    market = create_market()
    vendor, app = create_rejected_application(market["id"], "CRAFTS", "V1", "v1@x.com")
    vh = make_vendor_headers(vendor["id"])

    validate_success(api.resubmit_application(app["id"], vh), 200)
    reviewed_again = validate_success(api.start_review_application(app["id"], ADMIN), 200)
    assert reviewed_again["status"] == "UNDER_REVIEW"


def test_sales_report_dispute_resubmit_recomputes_provisional(api):
    """PRD 3.8: "A disputed report is returned to the manager's queue when the
    owning vendor resubmits it with corrected figures, advancing it from DISPUTED
    back to SUBMITTED, recomputing the provisional commission_cents". Corrected
    gross 20000 gives 20000*700/10000 = 1400.

    Design: Difficulty/non_linear_state_machine/sales_report_dispute_resubmit_cycle
    """
    base = setup_present_check_in(product_category="CRAFTS")
    vh = make_vendor_headers(base["vendor"]["id"])
    sr = get_success_data(api.create_sales_report(
        {"market_id": base["market"]["id"], "check_in_id": base["check_in"]["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 0}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))
    assert sr["commission_cents"] == 2100
    get_success_data(api.dispute_sales_report(sr["id"], MANAGER))

    corrected = validate_success(
        api.submit_sales_report(sr["id"], {"gross_sales_cents": 20000, "tokens_accepted": 0}, vh),
        200)
    assert corrected["status"] == "SUBMITTED"
    assert corrected["commission_cents"] == 1400


def test_sales_report_dispute_transitions_from_submitted(api):
    """PRD 3.8: "A MarketManager may dispute a submitted report, advancing it from
    SUBMITTED to DISPUTED; a dispute is legal only from SUBMITTED, flags the report
    without changing commission_cents".

    Design: Difficulty/non_linear_state_machine/sales_report_dispute_resubmit_cycle
    """
    base = setup_present_check_in(product_category="CRAFTS")
    vh = make_vendor_headers(base["vendor"]["id"])
    sr = get_success_data(api.create_sales_report(
        {"market_id": base["market"]["id"], "check_in_id": base["check_in"]["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 0}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))

    disputed = validate_success(api.dispute_sales_report(sr["id"], MANAGER), 200)
    assert disputed["status"] == "DISPUTED"
    assert disputed["commission_cents"] == 2100, "commission unchanged on dispute"


# ---------------------------------------------------------------------------
# Corner: state_machines (Application pipeline)
# ---------------------------------------------------------------------------
def test_application_initial_state_is_submitted(api):
    """PRD 3.2: "The application is born SUBMITTED with a null review_note."

    Design: Corner/state_machines/application_initial_state_is_submitted
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    app = validate_success(api.create_application(
        {"vendor_id": vendor["id"], "product_category": "CRAFTS"}, vh), 201)
    assert app["status"] == "SUBMITTED"


def test_approve_from_submitted_without_review_is_invalid_state(api):
    """PRD 3.2: "Approval requires the application to be UNDER_REVIEW" and PRD 3.3
    closes with "Any attempt to drive an assignment through a transition illegal
    from its current state is rejected with ERR_INVALID_STATE." Approving a
    SUBMITTED application is illegal.

    Design: Corner/state_machines/approve_from_submitted_without_review_is_invalid_state
    """
    market = create_market()
    vendor, app = create_submitted_application(market["id"], "CRAFTS", "V1", "v1@x.com")

    res = api.approve_application(app["id"], {"review_note": "x"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_application(app["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_reject_approved_application_is_invalid_state(api):
    """PRD 3.2: "Rejection, legal only from UNDER_REVIEW, moves the application to
    REJECTED" — so rejecting an APPROVED application is an illegal transition,
    rejected with ERR_INVALID_STATE (PRD 3.3).

    Design: Corner/state_machines/approved_application_is_terminal_no_reject
    """
    market = create_market()
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    # The vendor's first application is APPROVED; find it via the filtered list.
    apps, _ = validate_paginated(
        api.list_applications(ADMIN, params={"vendor_id": vendor["id"]}))
    approved_id = next(a["id"] for a in apps if a["status"] == "APPROVED")

    res = api.reject_application(approved_id, {"review_note": "no"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_approve_bubbles_vendor_prospect_to_active(api):
    """PRD 3.2: "A successful approval ... promotes the owning vendor from PROSPECT
    to ACTIVE if it was still PROSPECT, and increments both the application's and
    the vendor's version by 1."

    Design: Corner/state_machines/approve_bubbles_vendor_to_active
    """
    market = create_market()
    vendor, app = create_under_review_application(market["id"], "CRAFTS", "V1", "v1@x.com")
    assert vendor["status"] == "PROSPECT"

    approved = validate_success(api.approve_application(app["id"], {"review_note": "ok"}, ADMIN), 200)
    assert approved["status"] == "APPROVED"
    vendor_after = get_success_data(api.get_vendor(vendor["id"], ADMIN))
    assert vendor_after["status"] == "ACTIVE"
