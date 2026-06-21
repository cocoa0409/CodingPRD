"""Dispatch windows, overlap/buffer/double-booking guards, OCC booking, and visits."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS,
    create_category, create_customer, create_pro, create_cleared_pro, create_window,
    create_job, accepted_instant_job,
    create_dispatch_window_payload, book_window_payload, create_visit_payload,
    accept_quote_payload,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# =====================================================================
# Difficulty: resource_temporal_overlap / dispatch_window_overlap_half_open_adjacency_allowed
# =====================================================================

class TestDispatchWindowOverlapHalfOpen:
    """A pro's windows use half-open intervals: boundary-touch allowed, true overlap rejected."""

    def test_overlapping_window_rejected(self, api):
        """PRD §3.4: "A professional may not publish a window that overlaps any of their own
        existing windows that are not `RELEASED`; overlap is judged on half-open intervals, so two
        windows that merely touch at a boundary do not overlap, but any true overlap is rejected
        with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_overlap_half_open_adjacency_allowed
        """
        pro = create_pro(email="p15@x.com", full_name="P Fifteen", home_zip_code="30301", skill_tags=["hvac"])
        pro_h = make_pro_headers(pro["id"])
        get_success_data(api.create_dispatch_window(
            create_dispatch_window_payload(pro["id"], "2026-06-10T10:00:00.000Z",
                                           "2026-06-10T12:00:00.000Z", "30301"), pro_h))
        res = api.create_dispatch_window(
            create_dispatch_window_payload(pro["id"], "2026-06-10T11:00:00.000Z",
                                           "2026-06-10T13:00:00.000Z", "30301"), pro_h)
        validate_error(res, "ERR_WINDOW_OVERLAP", expected_status=409)

    def test_boundary_touching_window_allowed(self, api):
        """PRD §3.4: "overlap is judged on half-open intervals, so two windows that merely touch at
        a boundary do not overlap, but any true overlap is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_overlap_half_open_adjacency_allowed
        """
        pro = create_pro(email="p15b@x.com", full_name="P 15b", home_zip_code="30301", skill_tags=["hvac"])
        pro_h = make_pro_headers(pro["id"])
        get_success_data(api.create_dispatch_window(
            create_dispatch_window_payload(pro["id"], "2026-06-10T10:00:00.000Z",
                                           "2026-06-10T12:00:00.000Z", "30301"), pro_h))
        res = api.create_dispatch_window(
            create_dispatch_window_payload(pro["id"], "2026-06-10T12:00:00.000Z",
                                           "2026-06-10T14:00:00.000Z", "30301"), pro_h)
        win2 = validate_success(res, 201)
        assert win2["hold_state"] == "FREE"


# =====================================================================
# Difficulty: resource_temporal_overlap / customer_double_book_closed_interval_adjacency_rejected
# =====================================================================

class TestCustomerDoubleBookClosedInterval:
    """A customer's booked windows use CLOSED intervals: even adjacency is rejected."""

    def _setup(self):
        cat = create_category(code="DBL_BK", name="Double Book", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["hvac"])
        cust = create_customer(email="c16@x.com", full_name="C Sixteen", zip_code="30301")
        pro_a = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                                   email="p16a@x.com", full_name="P 16a")
        pro_b = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                                   email="p16b@x.com", full_name="P 16b")
        win_a = create_window(pro_a["id"], "2026-06-11T10:00:00.000Z", "2026-06-11T12:00:00.000Z", "30301")
        win_b = create_window(pro_b["id"], "2026-06-11T12:00:00.000Z", "2026-06-11T14:00:00.000Z", "30301")
        cust_h = make_customer_headers(cust["id"])
        # first job booked into win_a
        job1, q1 = accepted_instant_job(cust["id"], cat["id"], "30301")
        get_success_data(api_client.book_window(
            win_a["id"], book_window_payload(job1["id"], win_a["version"]), cust_h))
        # second accepted job
        job2, q2 = accepted_instant_job(cust["id"], cat["id"], "30301")
        return cust, win_b, job2

    def test_adjacent_second_booking_rejected(self, api):
        """PRD §3.4: "the booking customer must not already hold another `SCHEDULED` job whose
        booked window's interval touches or overlaps the interval of the window now being booked.
        This second check treats the intervals as closed, so even adjacent, back-to-back windows
        are rejected — a customer cannot be at two sites at once — with `ERR_CUSTOMER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/customer_double_book_closed_interval_adjacency_rejected
        """
        cust, win_b, job2 = self._setup()
        res = api.book_window(win_b["id"], book_window_payload(job2["id"], win_b["version"]),
                              make_customer_headers(cust["id"]))
        validate_error(res, "ERR_CUSTOMER_DOUBLE_BOOKED", expected_status=409)

    def test_second_window_stays_free_after_rejected_double_book(self, api):
        """PRD §3.4: "the booking customer must not already hold another `SCHEDULED` job whose
        booked window's interval touches or overlaps the interval of the window now being booked.
        This second check treats the intervals as closed, so even adjacent, back-to-back windows
        are rejected — a customer cannot be at two sites at once — with `ERR_CUSTOMER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/customer_double_book_closed_interval_adjacency_rejected
        """
        cust, win_b, job2 = self._setup()
        api.book_window(win_b["id"], book_window_payload(job2["id"], win_b["version"]),
                        make_customer_headers(cust["id"]))
        refreshed = validate_success(api.get_dispatch_window(win_b["id"], ADMIN), 200)
        assert refreshed["hold_state"] == "FREE"


# =====================================================================
# Difficulty: cross_entity_state_dependency / job_book_requires_pro_cleared_job_to_pro
# =====================================================================

class TestBookingRequiresClearedPro:
    """Booking is gated by the window-owning Pro's background_check_status == CLEARED."""

    def _setup_pending_pro(self):
        cat = create_category(code="XENT_A", name="Xent A", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["hvac"])
        cust = create_customer(email="c13@x.com", full_name="C Thirteen", zip_code="30301")
        pro = create_pro(email="p13@x.com", full_name="P Thirteen", home_zip_code="30301", skill_tags=["hvac"])
        window = create_window(pro["id"], "2026-06-08T10:00:00.000Z", "2026-06-08T12:00:00.000Z", "30301")
        job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
        return cust, window, job

    def test_book_window_owned_by_pending_pro_rejected(self, api):
        """PRD §3.5: "The first gate is the **background gate**: the acting or owning
        professional's `background_check_status` must be `CLEARED`; otherwise the operation is
        rejected with `ERR_PRO_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/job_book_requires_pro_cleared_job_to_pro
        """
        cust, window, job = self._setup_pending_pro()
        res = api.book_window(window["id"], book_window_payload(job["id"], window["version"]),
                              make_customer_headers(cust["id"]))
        validate_error(res, "ERR_PRO_NOT_CLEARED", expected_status=422)

    def test_window_unbooked_after_pro_not_cleared_rejection(self, api):
        """PRD §3.5: "The first gate is the **background gate**: the acting or owning
        professional's `background_check_status` must be `CLEARED`; otherwise the operation is
        rejected with `ERR_PRO_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/job_book_requires_pro_cleared_job_to_pro
        """
        cust, window, job = self._setup_pending_pro()
        api.book_window(window["id"], book_window_payload(job["id"], window["version"]),
                        make_customer_headers(cust["id"]))
        refreshed = validate_success(api.get_dispatch_window(window["id"], ADMIN), 200)
        assert refreshed["hold_state"] == "FREE"


# =====================================================================
# Difficulty: boundary_precision_check / visit_arrival_at_window_end_rejected_half_open
# =====================================================================

class TestVisitArrivalWindowBoundary:
    """arrived_at must fall in [window_start, window_end); arrival AT window_end is rejected."""

    def _scheduled(self):
        cat = create_category(code="VISIT_B", name="Visit B", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["hvac"])
        cust = create_customer(email="c12@x.com", full_name="C Twelve", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                                 email="p12@x.com", full_name="P Twelve")
        window = create_window(pro["id"], "2026-06-07T10:00:00.000Z", "2026-06-07T12:00:00.000Z", "30301")
        job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
        cust_h = make_customer_headers(cust["id"])
        get_success_data(api_client.book_window(
            window["id"], book_window_payload(job["id"], window["version"]), cust_h))
        return job, pro, window

    def test_arrival_at_window_end_rejected(self, api):
        """PRD §3.6: "`arrived_at` must fall within the booked window's half-open interval from
        `window_start` inclusive to `window_end` exclusive; an arrival outside that interval is
        rejected with `ERR_VISIT_OUTSIDE_WINDOW`."

        Design: Difficulty/boundary_precision_check/visit_arrival_at_window_end_rejected_half_open
        """
        job, pro, window = self._scheduled()
        res = api.create_visit(
            job["id"], create_visit_payload(window["id"], "2026-06-07T12:00:00.000Z"),
            make_pro_headers(pro["id"]))
        validate_error(res, "ERR_VISIT_OUTSIDE_WINDOW", expected_status=422)

    def test_arrival_at_window_start_inclusive_accepted(self, api):
        """PRD §3.6: "`arrived_at` must fall within the booked window's half-open interval from
        `window_start` inclusive to `window_end` exclusive; an arrival outside that interval is
        rejected with `ERR_VISIT_OUTSIDE_WINDOW`."

        Design: Difficulty/boundary_precision_check/visit_arrival_at_window_end_rejected_half_open
        """
        job, pro, window = self._scheduled()
        res = api.create_visit(
            job["id"], create_visit_payload(window["id"], "2026-06-07T10:00:00.000Z"),
            make_pro_headers(pro["id"]))
        visit = validate_success(res, 201)
        assert visit["outcome"] == "OPEN"


# =====================================================================
# Corner: cross_cutting / occ_correct_version_book_succeeds_and_bumps_version
# =====================================================================

def test_book_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "If `expected_dispatchwindow_version` does not equal the window's current
    `version`, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.4: "On success
    the system ... flips the window's `hold_state` to `BOOKED`, records the window's
    `booked_job_id` as the job's id, and increments the window's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_book_succeeds_and_bumps_version
    """
    cat = create_category(code="CC_OCC", name="CC OCC", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["hvac"])
    cust = create_customer(email="ccc1@x.com", full_name="C CC1", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                             email="pcc1@x.com", full_name="P CC1")
    window = create_window(pro["id"], "2026-06-24T10:00:00.000Z", "2026-06-24T12:00:00.000Z", "30301")
    assert window["version"] == 1
    job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
    res = api.book_window(window["id"], book_window_payload(job["id"], window["version"]),
                          make_customer_headers(cust["id"]))
    booked = validate_success(res, 200)
    assert booked["hold_state"] == "BOOKED"
    assert booked["version"] == 2
    refreshed_job = validate_success(api.get_job(job["id"], make_customer_headers(cust["id"])), 200)
    assert refreshed_job["status"] == "SCHEDULED"


# Corner instance errors/stale_version_error_happy_then_stale_book is SKIPPED. In any sequential
# reproduction, the first happy book leaves the window genuinely BOOKED (hold_state != FREE), so a
# second book carrying the pre-book version simultaneously violates the §3.4 "window's hold_state
# must be FREE" precondition (ERR_INVALID_STATE) and the §2.8 version check (ERR_STALE_VERSION).
# PRD prose never commits to which check is evaluated first on the now-BOOKED window, so a faithful
# PRD-only implementer could surface either error. The winning error is not uniquely derivable ->
# gap left as a gap. (The successful-then-bumped-version path is already covered by the difficulty
# instance occ_correct_version_book_succeeds_and_bumps_version.)


# =====================================================================
# Corner: consistency_model / immediate_visibility_book_reflects_in_window_read
# =====================================================================

def test_book_immediately_visible_in_window_read(api):
    """PRD §3.4: "On success the system ... flips the window's `hold_state` to `BOOKED`, records
    the window's `booked_job_id` as the job's id".

    Design: Corner/consistency_model/immediate_visibility_book_reflects_in_window_read
    """
    cat = create_category(code="CM_IMM", name="CM Immediate", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["hvac"])
    cust = create_customer(email="ccm1@x.com", full_name="C CM1", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                             email="pcm1@x.com", full_name="P CM1")
    window = create_window(pro["id"], "2026-06-26T10:00:00.000Z", "2026-06-26T12:00:00.000Z", "30301")
    job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
    get_success_data(api.book_window(window["id"], book_window_payload(job["id"], window["version"]),
                                     make_customer_headers(cust["id"])))
    read = validate_success(api.get_dispatch_window(window["id"], DISPATCHER), 200)
    assert read["hold_state"] == "BOOKED"
    assert read["booked_job_id"] == job["id"]
