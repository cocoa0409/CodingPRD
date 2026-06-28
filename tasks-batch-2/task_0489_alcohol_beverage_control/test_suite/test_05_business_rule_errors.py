"""Business-rule rejections: training, protest timing, issuance fee, hearing
window validity, renewal timing, transfer-type integrity, demerit threshold, and
the quota-reserve optimistic-concurrency check.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    make_examiner_headers,
    ApiErrorId,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    advance_to_protest_period,
    setup_application_in_protest_period_with_filed_protest,
    create_server_permit,
    file_violation,
    sustain_violation,
)

DIRECTOR = TEST_USERS["director_headers"]
EXAMINER = TEST_USERS["examiner_headers"]
ZONING = TEST_USERS["zoning_officer_headers"]
ADJUDICATOR = TEST_USERS["adjudication_officer_headers"]


# ─── Queue B: validations ─────────────────────────────────────────────────
def test_activate_permit_without_training_rejected(api):
    """PRD §3.7: "Activating a permit advances it from `PENDING` to `ACTIVE` and
    is gated three ways: the holder's `training_completed` must be true (otherwise
    `ERR_TRAINING_INCOMPLETE`, 422)"

    Design: Corner/validations/training_incomplete_blocks_server_activation
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    owner_id = bundle["ref"]["owner_id"]
    permit = create_server_permit(lic["id"], owner_id, training_completed=False, holder_name="Untrained")
    resp = api.activate_server_permit(
        permit["id"], {"expected_license_version": lic["version"]}, make_applicant_headers(owner_id))
    validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE.value)
    after = get_success_data(api.get_server_permit(permit["id"], DIRECTOR))
    assert after["status"] == "PENDING"


def test_protest_after_window_closed_rejected(api):
    """PRD §3.4: "Filing is allowed only while the application is in
    `PROTEST_PERIOD` and the current clock instant is strictly before
    `protest_period_ends_at`; a protest filed after the window has closed, or
    against an application not in `PROTEST_PERIOD`, is rejected with
    `ERR_PROTEST_WINDOW_CLOSED` (422)."

    Submitted 2026-01-01 (window ends 2026-01-31); at clock 2026-02-15 a protest
    is rejected ERR_PROTEST_WINDOW_CLOSED.

    Design: Corner/validations/protest_after_window_closed_rejected
    """
    ref, app = create_submitted_application()
    advance_to_protest_period(ref, app)
    get_success_data(api.set_clock("2026-02-15T00:00:00Z", DIRECTOR))
    resp = api.create_protest(
        {"application_id": app["id"], "protester_name": "Late Filer", "grounds": "ZONING"},
        TEST_USERS["anonymous_headers"])
    validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value)


def test_issue_before_fee_paid_rejected(api):
    """PRD §3.5: "the fee must be fully paid — `fee_paid_cents` must be greater
    than or equal to `fee_quoted_cents`, otherwise `ERR_FEE_UNPAID` (422)"

    An APPROVED application with fee_paid_cents 0 < fee_quoted_cents 110000 ->
    ERR_FEE_UNPAID, no License created, status stays APPROVED.

    Design: Corner/validations/issue_before_fee_paid_rejected
    """
    ref, app = create_submitted_application()
    advance_to_protest_period(ref, app)
    get_success_data(api.set_clock("2026-02-01T00:00:00Z", DIRECTOR))
    get_success_data(api.approve_application(app["id"], DIRECTOR))
    resp = api.issue_application(app["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FEE_UNPAID.value)
    after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert after["status"] == "APPROVED"


def test_schedule_hearing_ends_before_starts_rejected(api):
    """PRD §3.5: "The hearing is booked into a non-empty `room_code` over a window
    from `starts_at` (inclusive lower bound) to `ends_at` (exclusive upper bound),
    where `ends_at` must be strictly after `starts_at`."

    schedule-hearing with ends_at <= starts_at -> ERR_INVALID_REQUEST (400);
    protest stays FILED.

    Design: Corner/validations/hearing_ends_before_starts_rejected
    """
    ref, app, protest = setup_application_in_protest_period_with_filed_protest(grounds="ZONING")
    resp = api.schedule_hearing(
        protest["id"], {"room_code": "RM-9", "starts_at": "2026-01-10T11:00:00Z",
                        "ends_at": "2026-01-10T09:00:00Z"}, ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    after = get_success_data(api.get_protest(protest["id"], DIRECTOR))
    assert after["status"] == "FILED"


def test_renew_before_window_open_rejected(api):
    """PRD §3.8: "Renewal is permitted only when the clock has reached
    `renewal_window_opens_at` and the license is in `RENEWAL_DUE` (otherwise
    `ERR_RENEWAL_WINDOW_NOT_OPEN`, 422)"

    An ACTIVE license (clock before renewal_window_opens_at, status not
    RENEWAL_DUE) renewed -> ERR_RENEWAL_WINDOW_NOT_OPEN, stays ACTIVE.

    Design: Corner/validations/renew_outside_window_rejected
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    resp = api.renew_license(lic["id"], {"renewal_fee_paid_cents": 100000}, owner)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value)
    after = get_success_data(api.get_license(lic["id"], DIRECTOR))
    assert after["status"] == "ACTIVE"


def test_transfer_ownership_with_premise_field_rejected(api):
    """PRD §3.12: "An ownership transfer hands the license to a new applicant and
    requires `new_applicant_id` (and forbids `new_premise_id`) ... A request that
    supplies the wrong field for its type — or a location transfer whose target
    premise sits in a different region than the license — is rejected with
    `ERR_TRANSFER_TYPE_INVALID` (422)."

    transfer_type OWNERSHIP supplying new_premise_id (and no new_applicant_id) ->
    ERR_TRANSFER_TYPE_INVALID.

    Design: Corner/validations/transfer_type_ownership_with_premise_rejected
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    ref = bundle["ref"]
    owner = make_applicant_headers(ref["owner_id"])
    spare = get_success_data(api.create_premise(
        {"applicant_id": ref["owner_id"], "region_code": ref["region"]["region_code"],
         "street_address": "2 Spare St", "distance_to_school_m": 200,
         "zoning_district": "COMMERCIAL"}, owner))
    resp = api.create_transfer_request(
        {"license_id": lic["id"], "transfer_type": "OWNERSHIP", "new_premise_id": spare["id"]}, owner)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_TYPE_INVALID.value)


# ─── Queue B: errors ──────────────────────────────────────────────────────
def test_reinstate_with_demerit_threshold_rejected(api):
    """PRD §3.10: "A `Director` may later reinstate a `SUSPENDED` license back to
    `ACTIVE`, provided `outstanding_fine_cents` is zero (otherwise
    `ERR_OUTSTANDING_FINE`) and `demerit_points` is strictly below ten (otherwise
    `ERR_DEMERIT_THRESHOLD`)."

    A SUSPENDED license with demerit_points 10 and fines fully paid -> reinstate
    rejected ERR_DEMERIT_THRESHOLD, stays SUSPENDED.

    Design: Corner/errors/error_demerit_threshold_blocks_reinstate
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    # EGREGIOUS (fine 200000, demerit 6) + SERIOUS (fine 112500 at recidivism 1.5, demerit 4 -> 10).
    v1 = file_violation(lic_id, severity="EGREGIOUS")
    s1 = sustain_violation(v1["id"], action_type="FINE")
    v2 = file_violation(lic_id, severity="SERIOUS")
    s2 = sustain_violation(v2["id"], action_type="FINE")
    # Pay all fines so the fiscal check passes and the demerit check binds.
    get_success_data(api.pay_fine(lic_id, {"action_id": s1["action_id"], "amount_cents": 200000}, owner))
    get_success_data(api.pay_fine(lic_id, {"action_id": s2["action_id"], "amount_cents": 112500}, owner))
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["status"] == "SUSPENDED" and lic["outstanding_fine_cents"] == 0 and lic["demerit_points"] == 10
    resp = api.reinstate_license(lic_id, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DEMERIT_THRESHOLD.value)
    after = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert after["status"] == "SUSPENDED"


# ─── Queue B: cross_cutting_complexity_layers (OCC) ───────────────────────
def test_stale_region_version_on_submit_rejected(api):
    """PRD §2.7: "A submit of a quota-managed application must carry
    `expected_region_version` holding the client's last observed `version` of the
    target `QuotaRegion`. If that value does not equal the region's current
    `version` ... the submit is rejected with `ERR_STALE_REGION_VERSION` (HTTP
    412)."

    After a first submit bumps the region version, a second submit carrying a
    version one less than current is stale -> ERR_STALE_REGION_VERSION, stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_region_version_on_submit_rejected
    """
    get_success_data(api.set_clock("2026-01-01T00:00:00Z", DIRECTOR))
    get_success_data(api.create_license_class(
        {"code": "ON_47", "premise_type": "ON_PREMISE", "quota_managed": True,
         "base_fee_cents": 100000, "renewal_cycle_months": 12, "requires_zoning": True,
         "max_servers_per_license": 5}, DIRECTOR))
    region = get_success_data(api.create_quota_region(
        {"region_code": "CTY_LA", "population": 50000, "persons_per_license": 25000}, DIRECTOR))
    o1 = get_success_data(api.create_applicant({"legal_name": "Bar One"}, DIRECTOR))
    p1 = get_success_data(api.create_premise(
        {"applicant_id": o1["id"], "region_code": "CTY_LA", "street_address": "1 A St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(o1["id"])))
    a1 = get_success_data(api.create_application(
        {"applicant_id": o1["id"], "premise_id": p1["id"], "license_class_code": "ON_47"},
        make_applicant_headers(o1["id"])))
    get_success_data(api.submit_application(
        a1["id"], {"expected_region_version": region["version"]}, make_applicant_headers(o1["id"])))
    # Second application; the first submit already advanced the region version.
    o2 = get_success_data(api.create_applicant({"legal_name": "Bar Two"}, DIRECTOR))
    p2 = get_success_data(api.create_premise(
        {"applicant_id": o2["id"], "region_code": "CTY_LA", "street_address": "2 B St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(o2["id"])))
    a2 = get_success_data(api.create_application(
        {"applicant_id": o2["id"], "premise_id": p2["id"], "license_class_code": "ON_47"},
        make_applicant_headers(o2["id"])))
    reg_now = get_success_data(api.get_quota_region(region["id"], DIRECTOR))
    stale_version = reg_now["version"] - 1
    resp = api.submit_application(
        a2["id"], {"expected_region_version": stale_version}, make_applicant_headers(o2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_REGION_VERSION.value)
    after = get_success_data(api.get_application(a2["id"], DIRECTOR))
    assert after["status"] == "DRAFT"
