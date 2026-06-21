"""Cancellation cascades, the SoD-beats-state priority pair on claim approval, the
close-blocked-by-open-storage cross-entity guard, and idempotent-cancel rejection.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_booked_job, setup_approved_claim, setup_claim_under_review,
    setup_delivered_job, open_storage_lot, schedule_dispatch,
    register_truck, register_crew,
    create_dispatch_payload,
    register_customer, create_job,
    make_customer_headers, make_claims_adjuster_headers, TEST_USERS,
    ITEMS_120CF,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


def test_cancel_job_cascades_dispatch_and_frees_resources(api):
    """PRD §3.9: "A permitted cancellation sets `job_status` to `CANCELLED` and
    cascades at least two levels deep: every `SCHEDULED` dispatch of the job is
    moved to `CANCELLED`, and each cancelled dispatch in turn frees the truck and
    crew occupation windows it held."

    Cancelling job A cancels its SCHEDULED dispatch; reusing the same truck+window
    for job B then succeeds, proving the window was freed.

    Design: Difficulty/transitive_cascade/cancel_job_cascades_dispatch_cancel_frees_resources
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=3)

    custA, jobA, surveyA, estA = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)
    dispA = schedule_dispatch(jobA["id"], truck_id=truck["id"], crew_id=crew["id"],
                              window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    custB, jobB, surveyB, estB = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)

    cancelled_job = validate_success(
        api.cancel_move_job(jobA["id"], make_customer_headers(custA)), 200)
    assert cancelled_job["job_status"] == "CANCELLED"

    dispA_after = get_success_data(api.get_dispatch(dispA["id"], DISPATCHER))
    assert dispA_after["status"] == "CANCELLED"

    # Reusing the freed truck+window for job B must succeed.
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T09:00:00Z",
                                window_end="2026-07-01T12:00:00Z", required_crew_size=3),
        DISPATCHER)
    dispB = validate_success(res, 201)
    assert dispB["status"] == "SCHEDULED"


def test_cancel_job_moves_scheduled_dispatch_to_cancelled(api):
    """PRD §3.9: "every `SCHEDULED` dispatch of the job is moved to `CANCELLED`, and
    each cancelled dispatch in turn frees the truck and crew occupation windows it
    held."

    Second assertion on the cancel cascade instance: cancelling the job directly
    drives its SCHEDULED dispatch to CANCELLED.

    Design: Difficulty/transitive_cascade/cancel_job_cascades_dispatch_cancel_frees_resources
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=3)
    custA, jobA, surveyA, estA = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)
    dispA = schedule_dispatch(jobA["id"], truck_id=truck["id"], crew_id=crew["id"])

    cancelled_job = validate_success(
        api.cancel_move_job(jobA["id"], make_customer_headers(custA)), 200)
    assert cancelled_job["job_status"] == "CANCELLED"
    dispA_after = get_success_data(api.get_dispatch(dispA["id"], DISPATCHER))
    assert dispA_after["status"] == "CANCELLED"


def test_claim_sod_beats_invalid_state(api):
    """PRD §3.12: "then segregation of duties on claim adjudication
    (`ERR_SEGREGATION_OF_DUTIES`), then whether the requested state transition is
    defined from the current state (`ERR_INVALID_STATE`)."
    PRD §3.10: "on approve, deny, and reopen, the acting `X-User-ID` must not equal
    the claim's `filed_by_user_id` — the adjuster who intook a claim may not
    adjudicate it — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    On an already-APPROVED claim, a re-approve by the original filer is BOTH a SoD
    violation (p5) and a state violation (p6); SoD (the higher priority) wins.

    Design: Difficulty/priority_pair_validation_conflict/claim_sod_beats_invalid_state
    """
    _, _, _, claim = setup_approved_claim(
        valuation_coverage="RELEASED", filer_user_id="adj-filer", approver_user_id="adj-approver")
    assert claim["status"] == "APPROVED"
    # The filer re-approves: SoD violation AND approve-from-APPROVED is undefined.
    res = api.approve_damage_claim(claim["id"], make_claims_adjuster_headers("adj-filer"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_claim_filer_cannot_approve_own_claim(api):
    """PRD §3.10: "on approve, deny, and reopen, the acting `X-User-ID` must not
    equal the claim's `filed_by_user_id` — the adjuster who intook a claim may not
    adjudicate it — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Second assertion on the SoD-beats-state instance, isolating the segregation
    rule itself: on a fresh UNDER_REVIEW claim (where approve IS a defined
    transition), the filer approving their own claim is still rejected with
    ERR_SEGREGATION_OF_DUTIES.

    Design: Difficulty/priority_pair_validation_conflict/claim_sod_beats_invalid_state
    """
    _, _, _, claim = setup_claim_under_review(
        valuation_coverage="RELEASED", filer_user_id="adj-filer", with_item=True)
    res = api.approve_damage_claim(claim["id"], make_claims_adjuster_headers("adj-filer"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_close_blocked_by_open_storage_lot(api):
    """PRD §3.11: "Closure is permitted only when the job is fully settled and
    clean: the `payment_status` must be `PAID_IN_FULL`, no `DamageClaim` of the job
    may be `UNDER_REVIEW`, and no `StorageLot` of the job may be `IN_STORAGE`. If a
    claim is still under review or a lot is still in storage, closure is blocked with
    `ERR_DEPENDENT_STATE_BLOCK`."

    A DELIVERED, PAID_IN_FULL job that still has an IN_STORAGE lot cannot close.

    Design: Difficulty/cross_entity_state_dependency/close_blocked_by_open_storage_lot
    """
    cust_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LOCAL", items=ITEMS_120CF, binding_type="BINDING",
        valuation_coverage="RELEASED")
    # Open a lot (IN_STORAGE) on the delivered job.
    open_storage_lot(job["id"], intake_date="2026-07-01T00:00:00Z")
    # Pay the exact balance to reach PAID_IN_FULL.
    job_now = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    validate_success(api.create_payment(
        job["id"], {"kind": "BALANCE", "amount_cents": job_now["balance_due_cents"]},
        make_customer_headers(cust_id)), 201)

    res = api.close_move_job(job["id"], PLATFORM_ADMIN)
    validate_error(res, "ERR_DEPENDENT_STATE_BLOCK", 409)
    job_after = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    assert job_after["job_status"] == "DELIVERED"


def test_close_blocked_preserves_delivered_state(api):
    """PRD §3.11: "If a claim is still under review or a lot is still in storage,
    closure is blocked with `ERR_DEPENDENT_STATE_BLOCK`."

    Second assertion on the close-blocked instance: the rejected close leaves the
    job in DELIVERED (no state change side effect fires).

    Design: Difficulty/cross_entity_state_dependency/close_blocked_by_open_storage_lot
    """
    cust_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LOCAL", items=ITEMS_120CF, binding_type="BINDING",
        valuation_coverage="RELEASED")
    open_storage_lot(job["id"], intake_date="2026-07-01T00:00:00Z")
    job_now = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    validate_success(api.create_payment(
        job["id"], {"kind": "BALANCE", "amount_cents": job_now["balance_due_cents"]},
        make_customer_headers(cust_id)), 201)
    res = api.close_move_job(job["id"], PLATFORM_ADMIN)
    validate_error(res, "ERR_DEPENDENT_STATE_BLOCK", 409)
    job_after = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    assert job_after["job_status"] == "DELIVERED"


def test_cancel_already_cancelled_job_rejected(api):
    """PRD §3.9: "Before goods are in motion, the booking `Customer` may cancel a
    job that is `QUOTING` or `BOOKED`."
    PRD §3.12: "then whether the requested state transition is defined from the
    current state (`ERR_INVALID_STATE`)."

    Cancelling a job already CANCELLED returns ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_job_returns_invalid_state
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    validate_success(api.cancel_move_job(job["id"], make_customer_headers(cust_id)), 200)
    res = api.cancel_move_job(job["id"], make_customer_headers(cust_id))
    validate_error(res, "ERR_INVALID_STATE", 409)
