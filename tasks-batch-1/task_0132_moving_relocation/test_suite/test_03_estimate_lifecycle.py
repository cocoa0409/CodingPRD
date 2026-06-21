"""Estimate lifecycle: the DRAFT<->REVISED revision loop, acceptance booking,
sibling supersede, and the immediately-visible ledger after acceptance.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_job_with_survey, setup_job_with_estimate, setup_booked_job,
    accept_estimate, generate_estimate,
    create_estimate_payload,
    register_customer, create_job, create_survey_with_items,
    make_customer_headers, make_estimator_headers, TEST_USERS,
    ITEMS_120CF, ITEMS_370CF,
)

ESTIMATOR = TEST_USERS["estimator_headers"]


def test_estimate_revision_cycle_draft_revised_revised(api):
    """PRD §3.4: "While the job is still `QUOTING`, an `Estimator` may revise a
    `DRAFT` estimate, which moves it `DRAFT → REVISED`; a `REVISED` estimate may be
    revised again and stays `REVISED → REVISED`, so the revision loop is
    repeatable."
    PRD §3.4: "on each revision the full pricing engine re-runs, every charge
    component and the `estimate_total_cents` are recomputed, and the estimate's own
    `version` increments by one."

    Two revises on a DRAFT estimate: DRAFT->REVISED->REVISED, version 1->2->3.

    Design: Difficulty/non_linear_state_machine/estimate_revision_cycle_draft_revised_revised
    """
    cust_id, job, survey, est = setup_job_with_estimate(
        service_type="LONG_HAUL", items=ITEMS_120CF,
        binding_type="BINDING", valuation_coverage="RELEASED",
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900})
    assert est["status"] == "DRAFT"

    r1 = validate_success(api.revise_estimate(est["id"], {"binding_type": "NON_BINDING"}, ESTIMATOR), 200)
    assert r1["status"] == "REVISED"
    assert r1["version"] == 2

    r2 = validate_success(api.revise_estimate(est["id"], {"valuation_coverage": "RELEASED"}, ESTIMATOR), 200)
    assert r2["status"] == "REVISED"
    assert r2["version"] == 3


def test_estimate_stays_revised_on_repeat_revision(api):
    """PRD §3.4: "a `REVISED` estimate may be revised again and stays
    `REVISED → REVISED`, so the revision loop is repeatable."

    Second assertion on the revision-cycle instance: after the first revise the
    estimate is REVISED, and a further revise keeps it REVISED (the self-loop) while
    bumping version each time.

    Design: Difficulty/non_linear_state_machine/estimate_revision_cycle_draft_revised_revised
    """
    cust_id, job, survey, est = setup_job_with_estimate(
        service_type="LONG_HAUL", items=ITEMS_120CF,
        binding_type="BINDING", valuation_coverage="RELEASED",
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900})
    r1 = validate_success(api.revise_estimate(est["id"], {"binding_type": "NON_BINDING"}, ESTIMATOR), 200)
    assert r1["status"] == "REVISED"
    r2 = validate_success(api.revise_estimate(est["id"], {"binding_type": "BINDING"}, ESTIMATOR), 200)
    assert r2["status"] == "REVISED"
    assert r2["version"] == 3


def test_revise_accepted_estimate_rejected(api):
    """PRD §3.4: "Revising an estimate that is not in `DRAFT` or `REVISED`, or
    revising while the job has left `QUOTING`, is rejected as an invalid state
    transition with `ERR_INVALID_STATE`."

    An ACCEPTED estimate cannot be revised.

    Design: Corner/state_machines/revise_accepted_estimate_returns_invalid_state
    """
    cust_id, job, survey, est = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)
    res = api.revise_estimate(est["id"], {"binding_type": "BINDING"}, ESTIMATOR)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_accept_supersedes_sibling_estimate(api):
    """PRD §3.5: "Acceptance sets the estimate's `status` to `ACCEPTED`, records the
    estimate's `id` on the job as `accepted_estimate_id`, moves the job's
    `job_status` from `QUOTING` to `BOOKED`, and adds the accepted estimate's
    `estimate_total_cents` to the job's `gross_charges_cents` before recomputing
    `balance_due_cents`. As a sibling-superseding side effect, every other estimate
    of the same job whose `status` is `DRAFT` or `REVISED` is set to `SUPERSEDED`."

    Accepting one of two DRAFT estimates books the job and supersedes the sibling.

    Design: Corner/state_machines/accept_supersedes_sibling_estimates
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")

    survey1 = create_survey_with_items(job["id"], ITEMS_120CF, survey_method="IN_HOME")
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est1 = generate_estimate(job["id"], survey1["id"], job["version"],
                             binding_type="BINDING", valuation_coverage="RELEASED",
                             estimator_user_id="est-su")

    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    survey2 = create_survey_with_items(job["id"], ITEMS_120CF, survey_method="VIRTUAL")
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est2 = generate_estimate(job["id"], survey2["id"], job["version"],
                             binding_type="NON_BINDING", valuation_coverage="RELEASED",
                             estimator_user_id="est-su")

    accepted = validate_success(api.accept_estimate(est2["id"], make_customer_headers(cust_id)), 200)
    assert accepted["status"] == "ACCEPTED"

    superseded = get_success_data(api.get_estimate(est1["id"], ESTIMATOR))
    assert superseded["status"] == "SUPERSEDED"

    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["job_status"] == "BOOKED"


def test_ledger_visible_immediately_after_accept(api):
    """PRD §3.5: "Acceptance ... moves the job's `job_status` from `QUOTING` to
    `BOOKED`, and adds the accepted estimate's `estimate_total_cents` to the job's
    `gross_charges_cents` before recomputing `balance_due_cents`."

    Immediately after accept, the booked job shows job_status BOOKED and
    gross_charges_cents == the accepted estimate total (70200 for this LOCAL job).

    Design: Corner/consistency_model/ledger_fields_visible_immediately_after_accept
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL", origin_zip="90001", destination_zip="90002",
                     distance_miles=0)
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    get_success_data(api.create_packing_order(
        {"move_job_id": job["id"], "crate_count": 0,
         "packing_lines": [{"material_code": "dish_pack", "quantity": 2, "unit_price_cents": 1850}]},
        ESTIMATOR))
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est = generate_estimate(job["id"], survey["id"], job["version"],
                            binding_type="NON_BINDING", valuation_coverage="RELEASED",
                            estimator_user_id="est-im")
    assert est["estimate_total_cents"] == 70200

    booked = validate_success(api.accept_estimate(est["id"], make_customer_headers(cust_id)), 200)
    assert booked["status"] == "ACCEPTED"

    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["job_status"] == "BOOKED"
    assert job_after["gross_charges_cents"] == 70200
