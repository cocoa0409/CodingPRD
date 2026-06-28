"""Corner queue — endpoints (listing/pagination envelope, FK reverse-reachability),
errors (reference-not-found, coverage-overlap, appeal-window-closed), rbac
(unauthorized ops, peer ownership, unauthenticated), the two OCC cases, and the
immediate-consistency read.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_counselor_headers,
    make_student_headers,
    make_unknown_role_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ==========================================================================
# endpoints section
# ==========================================================================
def test_list_applications_pagination_envelope(api):
    """PRD §2.3: "List responses report pagination state through four fields in
    the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/list_applications_pagination_envelope
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.list_applications(ch, params={"student_id": student["id"]})
    data_list, meta = validate_paginated(resp)
    body = resp.json()
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    assert meta["total_count"] == 1, f"one application => total_count 1; got {meta['total_count']}"
    assert meta["has_more"] is False


def test_fk_reverse_billing_entries_listed(api):
    """PRD §2.6: "child resources are discovered through filtered list reads
    rather than nested paths"
    PRD §3.3: "if `retainer_deposit_cents` is greater than 0 the system appends a
    `BillingEntry` that is a `CREDIT` with `source_kind` of `MANUAL` and
    `amount_cents` equal to the deposit"

    Design: Corner/endpoints/fk_reverse_billing_entries_listed
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 20000, "retainer_deposit_cents": 100000},
    )
    ch = make_counselor_headers(counselor["id"])
    data_list, meta = validate_paginated(
        api.list_billing_entries(ch, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 1, f"activation should post exactly one CREDIT; got {meta['total_count']}"
    assert data_list[0]["entry_type"] == "CREDIT"


# ==========================================================================
# errors section
# ==========================================================================
def test_create_application_with_nonexistent_school_reference_not_found(api):
    """PRD §2.6: "Each such field must reference a row that actually exists; if it
    does not, the request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/reference_not_found_application_bad_school
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.create_application(
        {"student_id": student["id"], "school_list_item_id": NON_EXISTENT_UUID,
         "round": "RD", "deadline_utc": "2027-01-01T00:00:00Z"},
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_contract_coverage_interior_overlap_rejected(api):
    """PRD §3.3: "The new window conflicts when the new start is strictly before
    an existing window's end and that existing window's start is strictly before
    the new end. Windows that merely share a single endpoint instant are adjacent
    and permitted; only a strict interior overlap is rejected, with
    `ERR_CONTRACT_COVERAGE_OVERLAP`."

    Design: Corner/errors/contract_coverage_overlap_rejected
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_contract(
            f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                      coverage_start_utc="2026-04-01T00:00:00Z",
                                      coverage_end_utc="2026-12-31T00:00:00Z"),
            ch,
        )
    )
    # Interior overlap 2026-10-01..2026-12-31.
    resp = api.create_contract(
        f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                  coverage_start_utc="2026-10-01T00:00:00Z",
                                  coverage_end_utc="2027-03-01T00:00:00Z"),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_COVERAGE_OVERLAP.value)


def test_appeal_after_window_closed(api):
    """PRD §3.9: "The appeal is allowed only while the logical clock now is
    strictly before the application's `deadline_utc` plus a 30-day appeal window;
    once that window has closed the appeal is rejected with
    `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/errors/appeal_window_closed_after_30_days
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-20T00:00:00Z",
        student_overrides={"gpa": 3.5, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(api_client.record_decision(app["id"], {"decision": "DENIED"}, ch))
    # Advance clock to >30 days after the deadline.
    fx.set_clock("2027-02-15T00:00:00Z")
    resp = api.appeal_application(app["id"], ch)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)


# ==========================================================================
# rbac section
# ==========================================================================
def test_student_cannot_create_application(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation — or is permitted in general but is acting on
    a resource it does not own — the request is rejected with `ERR_FORBIDDEN`."
    PRD §4: "| POST | `/applications` | Create an Application against a SELECTED
    school-list item | Counselor |"

    Design: Corner/rbac/student_cannot_create_application
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    sh = make_student_headers(student["id"])
    item, _v = fx.select_school(counselor["id"], student, {"school_name": "Sec U",
                                                           "admit_rate": 0.50, "median_sat": 1250,
                                                           "round": "RD"})
    # Student attempts a Counselor-exclusive op on their own tree.
    resp = api.create_application(
        f.create_application_payload(student["id"], item["id"], "RD"), sh
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_counselor_cannot_read_other_counselors_student(api):
    """PRD §2.1: "A counselor may act only on students they own — that is,
    students whose `counselor_id` equals the caller's `X-User-ID`"
    PRD §2.1: "or is permitted in general but is acting on a resource it does not
    own — the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/counselor_cannot_act_on_other_counselors_student
    """
    counselor_a = fx.create_counselor(full_name="CCA", email="cca@x.com", hourly_rate_cents=18000)
    counselor_b = fx.create_counselor(full_name="CCB", email="ccb@x.com", hourly_rate_cents=18000)
    student = fx.create_student(counselor_a["id"], full_name="STU", email="stu@x.com",
                                grad_year=2027, gpa=3.5, sat_total=1300)
    ch_b = make_counselor_headers(counselor_b["id"])
    resp = api.get_student(student["id"], ch_b)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    these three values, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    counselor = fx.create_counselor(full_name="CC30", email="cc30@x.com", hourly_rate_cents=18000)
    resp = api.get_counselor(counselor["id"], make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ==========================================================================
# cross_cutting_complexity_layers section
# ==========================================================================
def test_occ_stale_student_version_on_contract_activate(api):
    """PRD §2.7: "The server compares `expected_student_version` to the student's
    current `version`. If they differ — meaning another writer advanced the
    student's `version` after the client last read it — the write is rejected with
    `ERR_STALE_STUDENT_VERSION` (HTTP 412)"
    PRD §2.7: "School selection is guarded because it recomputes the student's
    `list_locked` flag; if two selections each computed `list_locked` against an
    out-of-date list snapshot the result would be wrong, so the second one is
    rejected as stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_student_version_on_contract_activate
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    v_onb = student["version"]
    # DRAFT contract awaiting activation.
    contract = get_success_data(
        api_client.create_contract(
            f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                      retainer_deposit_cents=100000),
            ch,
        )
    )
    # A school selection bumps the student's version, making v_onb stale.
    item = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="OCC U",
                                              admit_rate=0.50, median_sat=1250, round="RD"),
            ch,
        )
    )
    get_success_data(api_client.select_school_list_item(item["id"], {"expected_student_version": v_onb}, ch))
    # Activate with the now-stale version.
    resp = api.activate_contract(contract["id"], {"expected_student_version": v_onb}, ch)
    validate_error(resp, ApiErrorId.ERR_STALE_STUDENT_VERSION.value)


def test_occ_correct_version_on_school_select_succeeds(api):
    """PRD §2.7: "Each of these write operations requires the request body to
    carry `expected_student_version`, holding the `version` of the `Student` the
    client last observed."
    PRD §3.2: "Selecting an item recomputes the student's `list_locked` flag and
    is guarded by optimistic concurrency on the student as described in Section
    2.7, requiring `expected_student_version` and rejecting a stale value with
    `ERR_STALE_STUDENT_VERSION`; selection also increments the student's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_school_select_succeeds_and_bumps
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    item = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="Good U",
                                              admit_rate=0.50, median_sat=1250, round="RD"),
            ch,
        )
    )
    selected = validate_success(
        api.select_school_list_item(item["id"], {"expected_student_version": student["version"]}, ch)
    )
    assert selected["status"] == "SELECTED"


# ==========================================================================
# consistency_model section
# ==========================================================================
def test_profile_strength_immediately_visible_after_activity(api):
    """PRD §3.1: "Adding an activity recomputes the student's `profile_strength`."
    PRD §3.1: "The GPA component is the student's `gpa` divided by 4.0 and then
    multiplied by 40, yielding 0 to 40."

    Design: Corner/consistency_model/immediate_profile_strength_visible_on_activity_add
    """
    # gpa 3.5 => gpa_c 35.0; sat 1200 => sat_c 20.0; academics 55.0; tier3 2x20 => resume 0.16 => 55.16.
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.5, "sat_total": 1200}
    )
    ch = make_counselor_headers(counselor["id"])
    fx.add_activity(counselor["id"], student["id"], hours_per_week=2, weeks_per_year=20,
                    tier=3, category="ARTS", title="A")
    fetched = validate_success(api.get_student(student["id"], ch))
    assert fetched["profile_strength"] == 55.16, (
        f"profile_strength should immediately reflect the added activity (55.16); "
        f"got {fetched['profile_strength']}"
    )
