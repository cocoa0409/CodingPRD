"""Business-rule validations on quoting, booking, payment, refund, and warranty, plus the
state-over-safety priority conflict."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS,
    create_category, create_customer, create_cleared_pro, create_pro, create_window,
    create_job, estimate_requested_job, accepted_instant_job,
    in_progress_job, issued_invoice_for_in_progress_job, completed_paid_job,
    dispute_under_review, set_clock,
    submit_quote_payload, book_window_payload, create_visit_payload, pay_invoice_payload,
    create_dispute_payload, resolve_dispute_payload, accept_quote_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# =====================================================================
# Difficulty: priority_pair_validation_conflict / state_beats_pro_not_cleared_on_quote
# =====================================================================

class TestStateBeatsProNotClearedOnQuote:
    """A REQUESTED job quoted by a PENDING pro fails the state check (priority 7) before the
    pro-cleared check (priority 8)."""

    def _setup(self):
        cat = create_category(code="PRIO_A", name="Prio A", pricing_model="HOURLY",
                              hourly_rate_cents=9000, skill_tags=["hvac"])
        cust = create_customer(email="c9@x.com", full_name="C Nine", zip_code="30301")
        pro = create_pro(email="p9@x.com", full_name="P Nine", home_zip_code="30301", skill_tags=["hvac"])
        # job left in REQUESTED (no request-estimate) -> quotes endpoint not defined from REQUESTED
        job = create_job(cust["id"], cat["id"], "30301")
        return cust, pro, job

    def test_state_error_wins_over_pro_not_cleared(self, api):
        """PRD §2.9: "the order is: ... (7) state legality for the requested transition, surfacing
        `ERR_INVALID_STATE`; and then (8) onward, the domain-specific business rules described
        throughout §3 ... a state-machine conflict before any of the safety, scheduling, or fiscal
        checks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_pro_not_cleared_on_quote
        """
        cust, pro, job = self._setup()
        res = api.submit_quote(job["id"], submit_quote_payload(estimated_labor_hours=2.0),
                               make_pro_headers(pro["id"]))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_job_unchanged_after_state_conflict(self, api):
        """PRD §2.9: "the order is: ... (7) state legality for the requested transition, surfacing
        `ERR_INVALID_STATE`; and then (8) onward, the domain-specific business rules described
        throughout §3 ... a state-machine conflict before any of the safety, scheduling, or fiscal
        checks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_pro_not_cleared_on_quote
        """
        cust, pro, job = self._setup()
        api.submit_quote(job["id"], submit_quote_payload(estimated_labor_hours=2.0),
                         make_pro_headers(pro["id"]))
        after = get_success_data(api.get_job(job["id"], make_customer_headers(cust["id"])))
        assert after["status"] == "REQUESTED"


# NOTE: difficulty instance priority_pair_validation_conflict/zip_mismatch_beats_stale_version_on_book
# is SKIPPED. The PRD states ERR_ZIP_MISMATCH (§3.4) and ERR_STALE_VERSION (§2.8) independently but
# never commits to which is evaluated first on /dispatch-windows/{id}/book; a faithful PRD-only
# implementer could surface either. The outcome is not uniquely derivable -> gap left as a gap.


# =====================================================================
# Corner: validations
# =====================================================================

def test_skill_tag_mismatch_on_quote_rejected(api):
    """PRD §3.5: "The third gate is the **skill gate**: the professional's `skill_tags` must be a
    superset of the category's `skill_tags`, meaning the professional carries every tag the
    category demands; a shortfall is rejected with `ERR_SKILL_TAG_MISMATCH`."

    Design: Corner/validations/skill_tag_mismatch_on_quote_returns_422
    """
    cat = create_category(code="VAL_SKILL", name="Val Skill", pricing_model="HOURLY",
                          hourly_rate_cents=9000, skill_tags=["hvac"])
    cust = create_customer(email="cval1@x.com", full_name="C Val1", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pval1@x.com", full_name="P Val1")
    job = estimate_requested_job(cust["id"], cat["id"], "30301")
    res = api.submit_quote(job["id"], submit_quote_payload(estimated_labor_hours=2.0),
                           make_pro_headers(pro["id"]))
    validate_error(res, "ERR_SKILL_TAG_MISMATCH", expected_status=422)


def test_license_required_pro_without_license_rejected(api):
    """PRD §3.5: "The second gate is the **license gate**: only when the job's category
    `requires_license`, the professional's `license_status` must be `VERIFIED` and their
    `license_expires_on` must be in the future; a missing, unverified, or expired license is
    rejected with `ERR_LICENSE_REQUIRED`."

    Design: Corner/validations/license_required_pro_without_license_rejected
    """
    cat = create_category(code="VAL_LIC", name="Val License", pricing_model="HOURLY",
                          hourly_rate_cents=9000, requires_license=True, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["electric"])
    cust = create_customer(email="cval2@x.com", full_name="C Val2", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["electric"], home_zip_code="30301",
                             email="pval2@x.com", full_name="P Val2")  # license_status NONE
    window = create_window(pro["id"], "2026-06-15T10:00:00.000Z", "2026-06-15T12:00:00.000Z", "30301")
    job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
    res = api.book_window(window["id"], book_window_payload(job["id"], window["version"]),
                          make_customer_headers(cust["id"]))
    validate_error(res, "ERR_LICENSE_REQUIRED", expected_status=422)


def test_instant_quote_on_ineligible_category_rejected(api):
    """PRD §3.3: "Requesting an instant quote on a category that is not instant-eligible, or on a
    warranty-callback job, is rejected with `ERR_INSTANT_QUOTE_INELIGIBLE`."

    Design: Corner/validations/instant_quote_on_ineligible_category_rejected
    """
    cat = create_category(code="VAL_INELIG", name="Val Inelig", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=False)
    cust = create_customer(email="cval3@x.com", full_name="C Val3", zip_code="30301")
    job = create_job(cust["id"], cat["id"], "30301")
    res = api.instant_quote(job["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INSTANT_QUOTE_INELIGIBLE", expected_status=422)


def test_partial_payment_rejected_full_only(api):
    """PRD §3.7: "Payment must be exact: the supplied `amount_cents` must equal the invoice's
    current `balance_due_cents`, because only full payment is accepted; any other amount is
    rejected with `ERR_PARTIAL_PAYMENT`."

    Design: Corner/validations/partial_payment_rejected_full_only
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code="VAL_PAY", name="Val Pay", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["plumb"])
    cust = create_customer(email="cval4@x.com", full_name="C Val4", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pval4@x.com", full_name="P Val4")
    job, window, invoice = issued_invoice_for_in_progress_job(
        cust["id"], cat["id"], pro,
        "2026-06-16T10:00:00.000Z", "2026-06-16T12:00:00.000Z", "2026-06-16T10:30:00.000Z")
    res = api.pay_invoice(invoice["id"], pay_invoice_payload(10000), make_customer_headers(cust["id"]))
    validate_error(res, "ERR_PARTIAL_PAYMENT", expected_status=422)


def test_refund_exceeds_paid_rejected(api):
    """PRD §3.10: "A `decision` of `APPROVE` requires an `approved_refund_cents` that is strictly
    greater than zero and no greater than the invoice's `amount_paid_cents` minus its
    already-`refunded_cents`; a value outside that range is rejected with `ERR_REFUND_EXCEEDS_PAID`."

    Design: Corner/validations/refund_exceeds_paid_rejected
    """
    cat = create_category(code="VAL_REF", name="Val Refund", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["plumb"])
    set_clock("2026-06-01T08:00:00.000Z")
    cust = create_customer(email="cval5@x.com", full_name="C Val5", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pval5@x.com", full_name="P Val5")
    job, window, invoice = completed_paid_job(
        cust["id"], cat["id"], pro,
        "2026-06-17T10:00:00.000Z", "2026-06-17T12:00:00.000Z", "2026-06-17T10:30:00.000Z",
        pay_amount=14500)
    disp = dispute_under_review(cust["id"], invoice["id"], job["id"], "OVERCHARGED", 20000)
    res = api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=20000), ADMIN)
    validate_error(res, "ERR_REFUND_EXCEEDS_PAID", expected_status=422)


def test_hourly_invoice_without_labor_lines_rejected(api):
    """PRD §3.6: "Recording labor hours on a `FLAT` category, or failing to record any labor hours
    before issuing an `HOURLY` invoice, is a pricing-model violation rejected with
    `ERR_PRICING_MODEL_MISMATCH`."

    Design: Corner/validations/hourly_invoice_without_labor_lines_rejected
    """
    cat = create_category(code="VAL_HRNO", name="Val HR NoLabor", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["electric"])
    cust = create_customer(email="cval6@x.com", full_name="C Val6", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["electric"], home_zip_code="30301",
                             email="pval6@x.com", full_name="P Val6")
    job, window = in_progress_job(cust["id"], cat["id"], pro,
                                  "2026-06-18T10:00:00.000Z", "2026-06-18T12:00:00.000Z",
                                  "2026-06-18T10:30:00.000Z")
    pro_h = make_pro_headers(pro["id"])
    invoice = get_success_data(api.create_invoice(job["id"], pro_h))  # DRAFT, no labor lines
    res = api.issue_invoice(invoice["id"], pro_h)
    validate_error(res, "ERR_PRICING_MODEL_MISMATCH", expected_status=422)


def test_warranty_expired_callback_rejected(api):
    """PRD §3.8: "A callback may be opened only while the current moment is strictly before the
    original job's completion instant plus the category's `callback_warranty_days`; past that point
    the request is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Corner/validations/warranty_expired_callback_rejected
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code="VAL_WARR", name="Val Warranty", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=14500, callback_warranty_days=30, skill_tags=["plumb"])
    cust = create_customer(email="cval7@x.com", full_name="C Val7", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pval7@x.com", full_name="P Val7")
    job, window, invoice = completed_paid_job(
        cust["id"], cat["id"], pro,
        "2026-06-01T10:00:00.000Z", "2026-06-01T12:00:00.000Z", "2026-06-01T10:30:00.000Z",
        pay_amount=14500)
    # advance clock well past 30-day warranty
    set_clock("2026-07-15T08:00:00.000Z")
    res = api.open_callback(job["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_WARRANTY_EXPIRED", expected_status=422)


def test_travel_buffer_conflict_rejected(api):
    """PRD §3.4: "the window being booked must leave a gap of at least sixty minutes before and
    after any other already-`BOOKED` window of the same professional whenever the two windows serve
    *different* ZIP codes ... A violation is rejected with `ERR_TRAVEL_BUFFER_CONFLICT`."

    Design: Corner/validations/travel_buffer_conflict_excluded
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code="VAL_TBUF", name="Val Travel", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["hvac"])
    cust = create_customer(email="cval8@x.com", full_name="C Val8", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                             email="pval8@x.com", full_name="P Val8")
    cust_h = make_customer_headers(cust["id"])
    # BOOKED window [10:00,12:00) ZIP 30301; FREE window [12:30,14:00) ZIP 99999 -> 30-min gap < 60.
    win_a = create_window(pro["id"], "2026-06-20T10:00:00.000Z", "2026-06-20T12:00:00.000Z", "30301")
    win_b = create_window(pro["id"], "2026-06-20T12:30:00.000Z", "2026-06-20T14:00:00.000Z", "99999")
    job1, q1 = accepted_instant_job(cust["id"], cat["id"], "30301")
    get_success_data(api.book_window(win_a["id"], book_window_payload(job1["id"], win_a["version"]), cust_h))
    job2, q2 = accepted_instant_job(cust["id"], cat["id"], "99999")
    res = api.book_window(win_b["id"], book_window_payload(job2["id"], win_b["version"]), cust_h)
    validate_error(res, "ERR_TRAVEL_BUFFER_CONFLICT", expected_status=409)
