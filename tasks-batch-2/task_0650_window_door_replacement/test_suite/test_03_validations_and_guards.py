"""Validation guards and rejections: state guards, cross-entity preconditions,
crew scheduling constraints, OCC, expiry, RBAC, and request-body validation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as FX,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    NON_EXISTENT_UUID,
)

SALES = TEST_USERS["sales_consultant_headers"]
OPS = TEST_USERS["operations_coordinator_headers"]
TECH = TEST_USERS["service_tech_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Determined rejection when two guards could apply
# ---------------------------------------------------------------------------

def test_accept_stale_version_alone_returns_stale_version(api):
    """PRD §2.8: "If the supplied `expected_quote_version` does not equal the
    quote's current `version` at the moment of acceptance, the client is acting
    on a stale view of the quote, and the acceptance is rejected with
    `ERR_STALE_QUOTE_VERSION` (HTTP 412)."

    Isolates the OCC stale-version check with the clock left before expiry so
    only the version mismatch can fail.

    Design: Difficulty/priority_pair_validation_conflict/quote_accept_expired_beats_stale_version_temporal_vs_state
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    resp = api.accept_quote(pid, qid, F.accept_quote_payload(base["quote_version"] - 1), make_homeowner_headers(ho_id))
    validate_error(resp, ApiErrorId.ERR_STALE_QUOTE_VERSION.value, 412)


def test_install_complete_without_approved_permit_returns_permit_not_approved(api):
    """PRD §3.7: "The coordinator completes an `EN_ROUTE` job, moving it to
    `COMPLETED`, which requires the job to be `EN_ROUTE` and the project to hold
    an `APPROVED` (or later) permit; completing without an approved permit is
    rejected with `ERR_PERMIT_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/install_complete_permit_beats_goods_safety_vs_constraint
    """
    # EN_ROUTE job (goods READY, departed) but permit only FILED (not approved).
    base = FX.setup_en_route_install(api, approve_permit=False)
    pid, job_id = base["project"]["id"], base["install_job"]["id"]
    resp = api.complete_install_job(pid, job_id, OPS)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value, 409)


def test_install_complete_with_approved_permit_succeeds(api):
    """PRD §3.7: "The coordinator completes an `EN_ROUTE` job, moving it to
    `COMPLETED`, which requires the job to be `EN_ROUTE` and the project to hold
    an `APPROVED` (or later) permit."
    PRD §3.7: "Completion advances the project to `INSPECTION`."

    Complement to the rejection case: with an APPROVED permit the same complete
    call succeeds, confirming the permit guard is the only thing the rejection
    case trips.

    Design: Difficulty/priority_pair_validation_conflict/install_complete_permit_beats_goods_safety_vs_constraint
    """
    base = FX.setup_en_route_install(api, approve_permit=True)
    pid, job_id = base["project"]["id"], base["install_job"]["id"]
    completed = validate_success(api.complete_install_job(pid, job_id, OPS), 200)
    assert completed["status"] == "COMPLETED", completed["status"]
    proj = validate_success(api.get_project(pid, OPS), 200)
    assert proj["status"] == "INSPECTION", proj["status"]


# ---------------------------------------------------------------------------
# Cross-entity transition preconditions
# ---------------------------------------------------------------------------

def test_install_depart_requires_manufacture_ready(api):
    """PRD §3.7: "Departure requires the job to be `SCHEDULED`, the linked
    manufacture order to be in `READY` (a crew cannot leave before the goods are
    built), and the current logical clock to have reached or passed
    `window_start`; departing before the goods are ready is rejected with
    `ERR_GOODS_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/install_depart_requires_manufacture_ready_job_to_order
    """
    # SCHEDULED job, order still IN_BUILD (NOT READY); window has started.
    base = FX.setup_scheduled_install(api, ready=False)
    pid, job_id = base["project"]["id"], base["install_job"]["id"]
    get_success_data(api.set_clock(F.set_clock_payload("2026-05-10T09:00:00Z"), ADMIN))
    resp = api.depart_install_job(pid, job_id, OPS)
    validate_error(resp, ApiErrorId.ERR_GOODS_NOT_READY.value, 409)
    job_after = validate_success(api.get_install_job(job_id, OPS), 200)
    assert job_after["status"] == "SCHEDULED", job_after["status"]


def test_install_depart_succeeds_when_manufacture_ready(api):
    """PRD §3.7: "Departure requires the job to be `SCHEDULED`, the linked
    manufacture order to be in `READY` (a crew cannot leave before the goods are
    built), and the current logical clock to have reached or passed
    `window_start`."
    PRD §3.7: "Departure advances the project to `INSTALLING`."

    Complement: with the linked order READY (and window started) the same depart
    succeeds, confirming the READY-goods precondition is what the rejection case
    trips.

    Design: Difficulty/cross_entity_state_dependency/install_depart_requires_manufacture_ready_job_to_order
    """
    base = FX.setup_scheduled_install(api, ready=True)
    pid, job_id = base["project"]["id"], base["install_job"]["id"]
    get_success_data(api.set_clock(F.set_clock_payload("2026-05-10T09:00:00Z"), ADMIN))
    departed = validate_success(api.depart_install_job(pid, job_id, OPS), 200)
    assert departed["status"] == "EN_ROUTE", departed["status"]


def test_permit_inspection_requires_completed_install_job(api):
    """PRD §3.8: "The coordinator records an inspection result against an
    `APPROVED` permit by supplying a `result`, and recording requires that the
    project has a `COMPLETED` install job, since inspection only follows
    installation."
    PRD §3.11: "the target resource must be in the correct state for its
    transition (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/permit_inspection_requires_completed_install_permit_to_job
    """
    # APPROVED permit, install job still EN_ROUTE (not COMPLETED).
    base = FX.setup_en_route_install(api, approve_permit=True)
    pid, permit_id = base["project"]["id"], base["permit"]["id"]
    resp = api.record_inspection(pid, permit_id, F.record_inspection_payload("PASS"), OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    permit_after = validate_success(api.get_permit(permit_id, OPS), 200)
    assert permit_after["status"] == "APPROVED", permit_after["status"]


def test_permit_inspection_passes_when_install_completed(api):
    """PRD §3.8: "The coordinator records an inspection result against an
    `APPROVED` permit by supplying a `result`, and recording requires that the
    project has a `COMPLETED` install job, since inspection only follows
    installation."
    PRD §3.8: "A passing result moves the permit to `INSPECTION_PASSED`."

    Complement: once the install job is COMPLETED, recording PASS on the same
    APPROVED permit succeeds, confirming the COMPLETED-install precondition is
    what the rejection case trips.

    Design: Difficulty/cross_entity_state_dependency/permit_inspection_requires_completed_install_permit_to_job
    """
    base = FX.setup_install_completed_permit_approved(api)
    pid, permit_id = base["project"]["id"], base["permit"]["id"]
    passed = validate_success(api.record_inspection(pid, permit_id, F.record_inspection_payload("PASS"), OPS), 200)
    assert passed["status"] == "INSPECTION_PASSED", passed["status"]


# ---------------------------------------------------------------------------
# Crew window overlap and daily-capacity geometry
# ---------------------------------------------------------------------------

def test_crew_window_strict_overlap_rejected(api):
    """PRD §3.7: "The new window must not overlap any other non-terminal install
    job window on the same crew; because windows are half-open, abutment where
    one window's end equals another's start is allowed, but any true overlap is
    rejected with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_half_open_strict_overlap
    """
    crew = FX.create_crew(api, daily_capacity_openings=50)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]
    # [10:00, 14:00) strictly overlaps [08:00, 12:00).
    resp = api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T10:00:00Z", "2026-05-10T14:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value, 409)


def test_crew_window_abutment_allowed(api):
    """PRD §3.7: "because windows are half-open, abutment where one window's end
    equals another's start is allowed, but any true overlap is rejected with
    `ERR_CREW_WINDOW_CONFLICT`."

    Half-open complement: a window starting exactly at the prior window's end
    abuts (does not overlap) and is allowed.

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_half_open_strict_overlap
    """
    crew = FX.create_crew(api, daily_capacity_openings=50)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]
    # [12:00, 14:00) starts exactly where the first ended -> abutment, allowed.
    job2 = validate_success(api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T12:00:00Z", "2026-05-10T14:00:00Z"), OPS), 201)
    assert job2["status"] == "SCHEDULED", job2["status"]


def test_crew_daily_capacity_aggregate_exceeded_rejected(api):
    """PRD §3.7: "across all non-terminal install jobs on that crew that share
    any calendar day with the new window, the sum of their `opening_count` plus
    the new job's must not exceed the crew's `daily_capacity_openings`; equality
    with the capacity is allowed, but exceeding it is rejected with
    `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate_same_day_exceeded
    """
    crew = FX.create_crew(api, daily_capacity_openings=1)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]
    # Abutting window [12:00, 16:00) same day; opening_count 1 + 1 = 2 > capacity 1.
    resp = api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T12:00:00Z", "2026-05-10T16:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value, 409)


def test_crew_daily_capacity_aggregate_at_equality_allowed(api):
    """PRD §3.7: "the sum of their `opening_count` plus the new job's must not
    exceed the crew's `daily_capacity_openings`; equality with the capacity is
    allowed, but exceeding it is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

    Boundary complement: with capacity 2, two same-day jobs of opening_count 1
    sum to exactly 2 (== capacity), which is allowed.

    Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate_same_day_exceeded
    """
    crew = FX.create_crew(api, daily_capacity_openings=2)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]
    job2 = validate_success(api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T12:00:00Z", "2026-05-10T16:00:00Z"), OPS), 201)
    assert job2["status"] == "SCHEDULED", job2["status"]


# ---------------------------------------------------------------------------
# Guard rejections and request-body validation
# ---------------------------------------------------------------------------

def test_complete_measure_zero_openings_rejected(api):
    """PRD §3.2: "An attempt to complete a measure that has captured zero
    openings is rejected with `ERR_NO_OPENINGS`; an empty measure can never be
    marked measured."

    Design: Difficulty/boundary_precision_check/complete_measure_zero_openings_empty_set_rejected
    """
    # BOOKED consultation, zero openings.
    base = FX.setup_measured_consultation(api, openings=[])
    pid, cons_id = base["project"]["id"], base["consultation"]["id"]
    resp = api.complete_measure(pid, cons_id, SALES)
    validate_error(resp, ApiErrorId.ERR_NO_OPENINGS.value, 422)
    cons = validate_success(api.get_consultation_nested(pid, cons_id, SALES), 200)
    assert cons["status"] == "BOOKED", cons["status"]


def test_complete_measure_one_opening_succeeds(api):
    """PRD §3.2: "This transition requires that the consultation is currently
    `BOOKED` and that at least one opening has been added — that is,
    `total_opening_count` is one or more."

    Design: Difficulty/boundary_precision_check/complete_measure_zero_openings_empty_set_rejected
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    get_success_data(api.create_opening(project["id"], cons["id"], F.create_opening_payload(cons["id"]), SALES))
    measured = validate_success(api.complete_measure(project["id"], cons["id"], SALES), 200)
    assert measured["status"] == "MEASURED", measured["status"]


def test_cancel_already_cancelled_consultation_returns_invalid_state(api):
    """PRD §3.2: "A `SalesConsultant` may cancel a consultation only while it is
    `BOOKED`, which sets it to `CANCELLED` and prompts a recomputation of the
    parent project's status; cancelling anything not in `BOOKED` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_consultation_already_cancelled_returns_invalid_state
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    get_success_data(api.cancel_consultation(project["id"], cons["id"], SALES))
    resp = api.cancel_consultation(project["id"], cons["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    cons_after = validate_success(api.get_consultation_nested(project["id"], cons["id"], SALES), 200)
    assert cons_after["status"] == "CANCELLED", cons_after["status"]


def test_send_quote_before_measure_returns_consultation_not_measured(api):
    """PRD §3.3: "Sending a quote advances it from `DRAFT` to `SENT`, but only if
    the quote is currently `DRAFT` and its linked consultation has reached
    `MEASURED`; sending against a consultation that is not measured is rejected
    with `ERR_CONSULTATION_NOT_MEASURED`."

    Design: Corner/state_machines/send_quote_before_measure_returns_consultation_not_measured
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    get_success_data(api.create_opening(project["id"], cons["id"], F.create_opening_payload(cons["id"]), SALES))
    quote = get_success_data(api.create_quote(project["id"], F.create_quote_payload(project["id"], cons["id"]), SALES))
    resp = api.send_quote(project["id"], quote["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_NOT_MEASURED.value, 409)


def test_mark_ready_before_lead_time_returns_invalid_state(api):
    """PRD §3.6: "The coordinator later marks the order ready, moving it from
    `IN_BUILD` to `READY`, which requires the order to be `IN_BUILD` and the
    current logical clock to have reached or passed `ready_at` — that is, the
    lead time must have elapsed."
    PRD §3.11: "the target resource must be in the correct state for its
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/mark_ready_before_lead_time_returns_invalid_state
    """
    # IN_BUILD order; clock left at default 2026-04-01 (before ready_at 2026-05-06).
    base = FX.setup_manufacture_in_build(api)
    pid, mo_id = base["project"]["id"], base["manufacture"]["id"]
    resp = api.mark_ready(pid, mo_id, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    mo_after = validate_success(api.get_manufacture_order(mo_id, OPS), 200)
    assert mo_after["status"] == "IN_BUILD", mo_after["status"]


def test_terminal_rejected_quote_cannot_be_sent(api):
    """PRD §3.11: "the target resource must be in the correct state for its
    transition (`ERR_INVALID_STATE`)."
    PRD §3.3: "Sending a quote advances it from `DRAFT` to `SENT`, but only if
    the quote is currently `DRAFT`."

    Design: Corner/state_machines/terminal_rejected_quote_cannot_be_sent
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    get_success_data(api.reject_quote(pid, qid, make_homeowner_headers(ho_id)))
    resp = api.send_quote(pid, qid, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_quote_auto_expires_when_clock_passes_expires_at(api):
    """PRD §3.4: "A `SENT` quote whose `expires_at` has been reached or passed
    transitions to `EXPIRED`; this is evaluated lazily whenever the quote or its
    project is read and whenever the logical clock is set."

    Design: Corner/state_machines/quote_auto_expires_when_clock_passes_expires_at
    """
    # SENT at default 2026-04-01 -> expires 2026-05-01; clock to 2026-06-01.
    base = FX.setup_sent_quote(api)
    pid, qid = base["project"]["id"], base["quote"]["id"]
    get_success_data(api.set_clock(F.set_clock_payload("2026-06-01T00:00:00Z"), ADMIN))
    quote = validate_success(api.get_quote_nested(pid, qid, SALES), 200)
    assert quote["status"] == "EXPIRED", quote["status"]


def test_accept_second_quote_when_already_contracted(api):
    """PRD §3.4: "a second acceptance on an already-contracted project fails with
    `ERR_PROJECT_ALREADY_CONTRACTED`."

    Design: Corner/validations/accept_second_quote_when_already_contracted_returns_already_contracted
    """
    base = FX.setup_measured_consultation(api)
    pid, cons_id, ho_id = base["project"]["id"], base["consultation"]["id"], base["homeowner"]["id"]
    qa = get_success_data(api.create_quote(pid, F.create_quote_payload(pid, cons_id), SALES))
    qa = get_success_data(api.send_quote(pid, qa["id"], SALES))
    get_success_data(api.accept_quote(pid, qa["id"], F.accept_quote_payload(qa["version"]), make_homeowner_headers(ho_id)))
    # Second quote SENT after A's acceptance, so not auto-superseded.
    qb = get_success_data(api.create_quote(pid, F.create_quote_payload(pid, cons_id), SALES))
    qb = get_success_data(api.send_quote(pid, qb["id"], SALES))
    resp = api.accept_quote(pid, qb["id"], F.accept_quote_payload(qb["version"]), make_homeowner_headers(ho_id))
    validate_error(resp, ApiErrorId.ERR_PROJECT_ALREADY_CONTRACTED.value, 409)


def test_financing_over_quote_estimate_returns_financing_over_quote(api):
    """PRD §3.5: "A decision to approve requires that the application is
    `SUBMITTED` and that `requested_amount_cents` is no greater than the linked
    quote's `estimate_total_cents`; a request to finance more than the quote
    total is rejected with `ERR_FINANCING_OVER_QUOTE`."

    Design: Corner/validations/financing_over_quote_estimate_returns_financing_over_quote
    """
    # SENT quote estimate 84000; financing requesting 200000.
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    fin = get_success_data(api.create_financing(pid, qid, F.create_financing_payload(qid, requested_amount_cents=200_000, term_months=24), make_homeowner_headers(ho_id)))
    resp = api.decide_financing(pid, qid, fin["id"], F.decide_financing_payload("APPROVE"), OPS)
    validate_error(resp, ApiErrorId.ERR_FINANCING_OVER_QUOTE.value, 422)
    fin_after = validate_success(api.get_financing(fin["id"], SALES), 200)
    assert fin_after["status"] == "SUBMITTED", fin_after["status"]


def test_crew_jurisdiction_mismatch_on_install_create(api):
    """PRD §3.7: "The assigned crew's `home_jurisdiction` must equal the
    project's `jurisdiction_code`; a mismatch is rejected with
    `ERR_CREW_JURISDICTION_MISMATCH`."

    Design: Corner/validations/crew_jurisdiction_mismatch_on_install_create
    """
    # Project CENTRAL_LIGHT (zip 30301); crew WEST_STRICT.
    base = FX.setup_accepted_quote(api)
    pid = base["project"]["id"]
    crew = FX.create_crew(api, home_jurisdiction="WEST_STRICT")
    resp = api.create_install_job(
        pid, F.create_install_job_payload(pid, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T17:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_CREW_JURISDICTION_MISMATCH.value, 422)


def test_service_ticket_on_noncompleted_project_rejected(api):
    """PRD §3.9: "A ticket may be opened only on a `COMPLETED` project — opening
    one on any other project state is rejected with `ERR_PROJECT_NOT_COMPLETED`."

    Design: Corner/validations/service_ticket_on_noncompleted_project_returns_project_not_completed
    """
    base = FX.setup_measured_consultation(api)
    pid, ho_id = base["project"]["id"], base["homeowner"]["id"]
    open_id = base["opening_ids"][0]
    resp = api.create_service_ticket(pid, F.create_service_ticket_payload(pid, open_id, category="WARRANTY"), make_homeowner_headers(ho_id))
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_COMPLETED.value, 409)


def test_referral_from_noncompleted_referrer_rejected(api):
    """PRD §3.10: "Creation requires that the referrer project's status is
    `COMPLETED` and that the referrer and referred projects are different; a
    referrer that is not completed, or a referral that names the same project on
    both sides, is rejected with `ERR_REFERRER_NOT_COMPLETED`."

    Design: Corner/validations/referral_from_noncompleted_referrer_returns_referrer_not_completed
    """
    homeowner = FX.create_homeowner(api)
    pref = FX.create_project_for(api, homeowner["id"])   # LEAD, not COMPLETED
    pnew = FX.create_project_for(api, homeowner["id"])
    resp = api.create_referral(F.create_referral_payload(pref["id"], pnew["id"]), SALES)
    validate_error(resp, ApiErrorId.ERR_REFERRER_NOT_COMPLETED.value, 409)


def test_pagination_limit_out_of_range_returns_validation_limit(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a
    negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`."

    Design: Corner/validations/pagination_limit_out_of_range_returns_validation_limit
    """
    resp = api.list_projects(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value, 422)


def test_install_window_end_before_start_returns_invalid_request(api):
    """PRD §3.7: "a half-open install window defined by `window_start`
    (inclusive) and `window_end` (exclusive), where `window_end` must be
    strictly later than `window_start`."

    Design: Corner/errors/install_window_end_before_start_returns_invalid_request
    """
    base = FX.setup_accepted_quote(api)
    pid = base["project"]["id"]
    crew = FX.create_crew(api)
    resp = api.create_install_job(
        pid, F.create_install_job_payload(pid, crew["id"], "2026-05-10T17:00:00Z", "2026-05-10T08:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ---------------------------------------------------------------------------
# Role and ownership enforcement
# ---------------------------------------------------------------------------

def test_operations_coordinator_cannot_send_quote(api):
    """PRD §2.1: "the system checks whether the supplied `X-User-Role` is
    permitted to perform the requested operation; if it is not, the request is
    rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/operations_coordinator_cannot_send_quote_forbidden
    """
    base = FX.setup_draft_quote(api)
    pid, qid = base["project"]["id"], base["quote"]["id"]
    resp = api.send_quote(pid, qid, OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_homeowner_accept_quote_on_other_owners_project_returns_not_owner(api):
    """PRD §2.1: "when a homeowner accepts a quote, rejects a quote, or reopens a
    service ticket, the system verifies that the homeowner owns the underlying
    project; if they do not, the request is rejected with
    `ERR_NOT_PROJECT_OWNER`."

    Design: Corner/rbac/homeowner_accept_quote_on_other_owners_project_returns_not_owner
    """
    base = FX.setup_sent_quote(api)
    pid, qid = base["project"]["id"], base["quote"]["id"]
    other = FX.create_homeowner(api)  # homeowner B does not own the project
    resp = api.accept_quote(pid, qid, F.accept_quote_payload(base["quote_version"]), make_homeowner_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header — or carrying an empty value
    for either — is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request("GET", "/projects", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
