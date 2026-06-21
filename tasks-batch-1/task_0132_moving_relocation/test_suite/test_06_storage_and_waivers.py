"""Storage-in-transit accrual, goodwill waivers (gross-charge conservation), and
optimistic-concurrency on estimate generation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_delivered_job, setup_released_storage_lot, open_storage_lot,
    setup_job_with_survey,
    generate_estimate, create_survey_with_items,
    create_estimate_payload,
    register_customer, create_job,
    make_estimator_headers, TEST_USERS,
    ITEMS_120CF,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


def test_sit_waive_conserves_gross_charges(api):
    """PRD §3.8: "A waive moves the lot `RELEASED → WAIVED`, adds the lot's
    `sit_charge_cents` to the job's `waived_cents` as a compensating credit,
    increments the job's `version` by one, and recomputes `balance_due_cents`. The
    conservation invariant holds: `gross_charges_cents` is unchanged and the balance
    drops by exactly the waived charge."

    Release accrues 51400 to gross; waive credits waived_cents by exactly 51400
    while gross_charges_cents is unchanged.

    Design: Difficulty/compensating_invariant/sit_waive_conserves_gross_charges
    """
    cust_id, job, lot = setup_released_storage_lot()
    assert lot["sit_charge_cents"] == 51400
    job_before = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    gross_before = job_before["gross_charges_cents"]

    waived = validate_success(api.waive_storage_lot(
        lot["id"], {"expected_move_job_version": job_before["version"]}, PLATFORM_ADMIN), 200)
    assert waived["status"] == "WAIVED"

    job_after = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    assert job_after["waived_cents"] == 51400
    assert job_after["gross_charges_cents"] == gross_before


def test_sit_waive_drops_balance_by_exactly_waived_charge(api):
    """PRD §3.8: "The conservation invariant holds: `gross_charges_cents` is
    unchanged and the balance drops by exactly the waived charge."

    Second assertion on the waive conservation instance: balance_due falls by
    exactly the 51400 SIT charge after the waive, with gross preserved.

    Design: Difficulty/compensating_invariant/sit_waive_conserves_gross_charges
    """
    cust_id, job, lot = setup_released_storage_lot()
    job_before = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    balance_before = job_before["balance_due_cents"]

    validate_success(api.waive_storage_lot(
        lot["id"], {"expected_move_job_version": job_before["version"]}, PLATFORM_ADMIN), 200)
    job_after = get_success_data(api.get_move_job(job["id"], PLATFORM_ADMIN))
    assert job_after["balance_due_cents"] == balance_before - 51400


def test_sit_accrual_billable_days_and_charge(api):
    """PRD §3.8: "The `billable_days` are those raw days less a three-day free
    allowance, floored at zero (the larger of zero and the raw days minus three).
    The `sit_charge_cents` is the `billable_days` multiplied by a daily storage rate
    of 4,200 cents (forty-two dollars) per day, plus twice a warehouse-handling fee
    of 11,000 cents (so 22,000 cents of handling in total), rounded half up."

    Intake 07-01, release 07-11 -> 10 raw days - 3 free = 7 billable; 7*4200 +
    22000 = 51400 cents.

    Design: Corner/calculations/sit_accrual_free_days_threshold_correct
    """
    cust_id, job, lot = setup_released_storage_lot(
        intake_date="2026-07-01T00:00:00Z", release_date="2026-07-11T00:00:00Z")
    assert lot["billable_days"] == 7
    assert lot["sit_charge_cents"] == 51400


def test_release_before_intake_rejected(api):
    """PRD §3.8: "A `Dispatcher` releases the lot by supplying a `release_date`,
    permitted while the lot is `IN_STORAGE`, while the job is `DELIVERED` or
    `IN_TRANSIT`, and only if the `release_date` is on or after the lot's
    `intake_date` — an earlier release date is rejected with
    `ERR_RELEASE_BEFORE_INTAKE`."

    A lot with intake 07-10 rejects a release_date of 07-05.

    Design: Corner/validations/release_before_intake_returns_422
    """
    cust_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LOCAL", items=ITEMS_120CF, binding_type="BINDING",
        valuation_coverage="RELEASED")
    lot = open_storage_lot(job["id"], intake_date="2026-07-10T00:00:00Z")
    res = api.release_storage_lot(lot["id"], {"release_date": "2026-07-05T00:00:00Z"}, DISPATCHER)
    validate_error(res, "ERR_RELEASE_BEFORE_INTAKE", 422)


def test_occ_stale_version_on_estimate_create_rejected(api):
    """PRD §2.6: "A request to author an estimate must carry
    `expected_move_job_version` matching the target `MoveJob`'s current `version`.
    If another writer has advanced the job's `version` since the client last read
    it — for instance because an earlier estimate was already generated and that
    estimate locked the survey, bumping the job — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    After a first estimate bumps the job version, a second create with the
    pre-bump version is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_estimate_create_returns_412
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    job_v0 = get_success_data(api.get_move_job(job["id"], ESTIMATOR))["version"]

    survey1 = create_survey_with_items(job["id"], ITEMS_120CF, survey_method="IN_HOME")
    generate_estimate(job["id"], survey1["id"], job_v0,
                      binding_type="BINDING", valuation_coverage="RELEASED")

    survey2 = create_survey_with_items(job["id"], ITEMS_120CF, survey_method="VIRTUAL")
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey2["id"], job_v0,
                                binding_type="NON_BINDING", valuation_coverage="RELEASED"),
        ESTIMATOR)
    validate_error(res, "ERR_STALE_VERSION", 412)


def test_occ_correct_version_bumps_job_version(api):
    """PRD §3.4: "Generating the estimate snapshots the author into
    `estimator_user_id`, locks the linked survey, computes every charge component
    below, and increments the job's `version` by one."

    A POST /estimates with the current version succeeds and bumps the job's version
    from 1 to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_increments_on_write
    """
    cust_id, job, survey = setup_job_with_survey(service_type="LOCAL", items=ITEMS_120CF)
    assert job["version"] == 1
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="RELEASED"),
        ESTIMATOR)
    validate_success(res, 201)
    job_after = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    assert job_after["version"] == 2
