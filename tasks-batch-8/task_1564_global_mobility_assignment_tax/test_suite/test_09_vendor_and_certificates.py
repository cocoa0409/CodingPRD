"""Vendor engagements and certificates of coverage: the cyclic review loop,
the one-open-slot rules, and the clock-driven expiry cascade (PRD §2.5, §3.4,
§3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_engagement_to_under_review,
    create_and_post_record,
    create_certificate_payload,
    create_draft_assignment,
    create_draft_record,
    create_employee,
    create_engagement,
    create_engagement_payload,
    create_policy,
    create_program,
    mark_filed_payload,
    mark_issued_payload,
    set_clock_payload,
    setup_active_assignment,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["vendor_coordinator_headers"]
VENDOR = TEST_USERS["tax_vendor_headers"]
ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


def _draft_assignment(totalization=True):
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    return create_draft_assignment(
        program["id"], employee["id"], policy["id"], totalization_applies=totalization)


def test_vendor_engagement_revision_cycle_increments_count(api, vendor_coordinator_headers):
    """PRD §3.4: "The coordinator begins internal review (`DRAFT_RETURNED` →
    `UNDER_REVIEW`) and then either sends the draft back for revision (`UNDER_REVIEW` →
    `REVISION_REQUESTED`, incrementing `revision_count` by one — the loop may repeat as
    many times as needed) or accepts the draft (`UNDER_REVIEW` → `ACCEPTED`)."
    PRD §3.4: "The `TaxVendor` returns a draft return, moving the engagement to
    `DRAFT_RETURNED` from either `DATA_SENT` or — after a revision round —
    `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/vendor_engagement_revision_cycle
    """
    assignment = _draft_assignment()
    engagement = create_engagement(assignment["id"], tax_year=2026)
    advance_engagement_to_under_review(engagement["id"])

    # One revision lap: UNDER_REVIEW -> REVISION_REQUESTED -> DRAFT_RETURNED.
    revision = validate_success(api.request_revision(engagement["id"], vendor_coordinator_headers), 200)
    assert revision["status"] == "REVISION_REQUESTED"
    assert revision["revision_count"] == 1

    returned = validate_success(api.return_draft(engagement["id"], VENDOR), 200)
    assert returned["status"] == "DRAFT_RETURNED", (
        "the cyclic loop returns to DRAFT_RETURNED after a revision round"
    )
    assert returned["revision_count"] == 1


def test_vendor_engagement_reaches_filed_after_review_loop(api, vendor_coordinator_headers):
    """PRD §3.4: "Marking the return filed moves `ACCEPTED` → `FILED` and records two
    figures from the filed return, `filed_total_gross_cents` and
    `filed_home_tax_cents`; the filing is what unlocks settlement creation for that
    assignment and tax year (§3.8)."

    Design: Difficulty/non_linear_state_machine/vendor_engagement_revision_cycle
    """
    assignment = _draft_assignment()
    engagement = create_engagement(assignment["id"], tax_year=2026)
    advance_engagement_to_under_review(engagement["id"])
    validate_success(api.request_revision(engagement["id"], vendor_coordinator_headers), 200)
    validate_success(api.return_draft(engagement["id"], VENDOR), 200)
    validate_success(api.start_review(engagement["id"], vendor_coordinator_headers), 200)
    validate_success(api.accept_engagement(engagement["id"], vendor_coordinator_headers), 200)

    filed = validate_success(api.mark_filed(
        engagement["id"], mark_filed_payload(3600000, 320000),
        vendor_coordinator_headers), 200)
    assert filed["status"] == "FILED"
    assert filed["filed_total_gross_cents"] == 3600000


def test_engagement_close_frees_duplicate_slot(api, vendor_coordinator_headers):
    """PRD §3.4: "At most one engagement per assignment and tax year may be
    non-`CLOSED` — a second attempt while any earlier engagement for the year is still
    open, including one already `FILED`, is rejected with `ERR_DUPLICATE_ENGAGEMENT`."
    PRD §3.4: "A filed engagement is finally closed (`FILED` → `CLOSED`), the terminal
    state that also frees the one-open-engagement slot for the year."

    Design: Corner/state_machines/engagement_close_frees_duplicate_slot
    """
    assignment = _draft_assignment()
    engagement = create_engagement(assignment["id"], tax_year=2026)
    advance_engagement_to_under_review(engagement["id"])
    validate_success(api.accept_engagement(engagement["id"], vendor_coordinator_headers), 200)
    validate_success(api.mark_filed(
        engagement["id"], mark_filed_payload(3600000, 320000), vendor_coordinator_headers), 200)

    res = api.create_engagement(
        create_engagement_payload(assignment["id"], tax_year=2026, scope="HOME_ONLY",
                                  vendor_name="OtherTax", fee_cents=200000),
        vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ENGAGEMENT)

    validate_success(api.close_engagement(engagement["id"], vendor_coordinator_headers), 200)
    successor = validate_success(api.create_engagement(
        create_engagement_payload(assignment["id"], tax_year=2026, scope="HOME_ONLY",
                                  vendor_name="OtherTax", fee_cents=200000),
        vendor_coordinator_headers), 201)
    assert successor["status"] == "ENGAGED"


def test_coc_one_open_slot_and_rejected_frees_slot(api, vendor_coordinator_headers):
    """PRD §3.5: "A `VendorCoordinator` applies with the `assignment_id` and an
    external `application_ref`; at most one certificate per assignment may be open
    across `REQUESTED`, `SUBMITTED`, and `ISSUED`, else `ERR_COC_ALREADY_OPEN`."
    PRD §3.5: "Rejection (`SUBMITTED` → `REJECTED`) records the authority's decision
    and frees the one-open-certificate slot, allowing a fresh application."

    Design: Corner/validations/coc_one_open_slot_and_rejected_frees_slot
    """
    assignment = _draft_assignment()
    first = validate_success(api.create_certificate(
        create_certificate_payload(assignment["id"], application_ref="COC-1"),
        vendor_coordinator_headers), 201)

    res = api.create_certificate(
        create_certificate_payload(assignment["id"], application_ref="COC-2"),
        vendor_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_COC_ALREADY_OPEN)

    validate_success(api.submit_certificate(first["id"], vendor_coordinator_headers), 200)
    rejected = validate_success(api.mark_rejected(first["id"], vendor_coordinator_headers), 200)
    assert rejected["status"] == "REJECTED"

    fresh = validate_success(api.create_certificate(
        create_certificate_payload(assignment["id"], application_ref="COC-3"),
        vendor_coordinator_headers), 201)
    assert fresh["status"] == "REQUESTED"


def test_clock_expiry_cascade_recomputes_draft_socsec(api, admin_headers, payroll_headers):
    """PRD §3.5: "When the logical clock is advanced past an `ISSUED` certificate's
    `valid_until` — coverage end being inclusive, expiry triggers only once the clock
    date is strictly after it — the certificate transitions `ISSUED` → `EXPIRED`."
    PRD §3.5: "The first cascade hop flips the assignment's split `coc_exempt` back to
    false; the second hop recomputes `employer_socsec_cents` under the non-exempt rule
    on every `DRAFT` shadow payroll record of the assignment, while `POSTED` records
    keep their frozen figures."
    PRD §2.5: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time."

    Design: Corner/complexity_layers/clock_expiry_cascade_recomputes_draft_socsec
    """
    ctx = setup_active_assignment(
        totalization=True, coc_valid_from="2026-09-01", coc_valid_until="2026-09-15")
    asg_id = ctx["assignment"]["id"]
    cert_id = ctx["certificate"]["id"]
    split_id = ctx["split"]["id"]

    september = create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=0, housing_receipts_cents=0)
    october = create_draft_record(
        asg_id, tax_year=2026, period_month=10, total_gross_cents=900000,
        per_diem_days=0, housing_receipts_cents=0)
    assert october["employer_socsec_cents"] == 0, "exempt at creation"
    assert september["employer_socsec_cents"] == 0

    validate_success(api.set_clock(set_clock_payload("2026-09-16T00:00:00Z"), admin_headers), 200)

    cert = validate_success(api.get_certificate(cert_id, admin_headers), 200)
    assert cert["status"] == "EXPIRED", "the clock swept the lapsed certificate"

    split = validate_success(api.get_split(split_id, admin_headers), 200)
    assert split["coc_exempt"] is False

    october_after = validate_success(api.get_record(october["id"], admin_headers), 200)
    assert october_after["employer_socsec_cents"] == 27540, (
        "DRAFT recompute: round_half_up(360000 x 0.0765) = 27540"
    )

    september_after = validate_success(api.get_record(september["id"], admin_headers), 200)
    assert september_after["employer_socsec_cents"] == 0, (
        "POSTED records keep their frozen figures"
    )
