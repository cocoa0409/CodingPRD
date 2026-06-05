"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in the Moving & Relocation domain require the system to
be walked through several states — register a customer, create a job, survey it,
price an estimate, accept it, pay a deposit, dispatch a truck+crew, depart, and
complete to reach DELIVERED — before the behavior under test can even be
triggered. These helpers encapsulate those preambles.

All setup calls use get_success_data() (the lenient validator) so a broken
precondition surfaces as a clear "Setup step failed" error rather than a
confusing assertion mismatch in the test body. Because the runner restarts the
server (empty DB) before every test, every helper builds its world from scratch.

Identity threading: a Customer is entity_backed, so every ownership-gated call
(accept / cancel / payments) uses make_customer_headers(customer_id) with the
real Customer.id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_move_job_payload, create_survey_payload,
    create_survey_item_payload, create_packing_order_payload, create_estimate_payload,
    create_truck_payload, create_crew_payload, create_dispatch_payload,
    create_storage_lot_payload, create_damage_claim_payload, create_claim_item_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_estimator_headers,
    make_dispatcher_headers, make_claims_adjuster_headers, make_platform_admin_headers,
)

# Item bundles whose totals are pinned by the design indices.
# sofa 2@35 + bed 3@60 + box 40@3 = 70 + 180 + 120 = 370 cf, weight 2590 lb.
ITEMS_370CF = [
    {"label": "sofa", "quantity": 2, "cubic_feet_each": 35},
    {"label": "bed", "quantity": 3, "cubic_feet_each": 60},
    {"label": "box", "quantity": 40, "cubic_feet_each": 3},
]
# box 40@3 = 120 cf, weight 840 lb (the small single-item survey).
ITEMS_120CF = [{"label": "box", "quantity": 40, "cubic_feet_each": 3}]

# Packing lines used by the 666864 long-haul estimate: dish 4@1850 + mirror 2@1200
# + 3 crates = 7400 + 2400 + 28500 = 38300 cents.
PACKING_LINES_38300 = [
    {"material_code": "dish_pack", "quantity": 4, "unit_price_cents": 1850},
    {"material_code": "mirror", "quantity": 2, "unit_price_cents": 1200},
]

DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: atomic primitives ────────────────────────────────────────────────
def register_customer(**overrides) -> dict:
    """Create one Customer. Returns the Customer dict."""
    return get_success_data(api_client.create_customer(
        create_customer_payload(**overrides), PLATFORM_ADMIN))


def register_truck(**overrides) -> dict:
    return get_success_data(api_client.create_truck(
        create_truck_payload(**overrides), DISPATCHER))


def register_crew(**overrides) -> dict:
    return get_success_data(api_client.create_crew(
        create_crew_payload(**overrides), DISPATCHER))


def create_job(customer_id, service_type="LOCAL", **overrides) -> dict:
    """Create a QUOTING/UNPAID MoveJob owned by customer_id."""
    return get_success_data(api_client.create_move_job(
        create_move_job_payload(customer_id, service_type, **overrides),
        make_customer_headers(customer_id)))


def create_survey_with_items(move_job_id, items, survey_method="IN_HOME") -> dict:
    """Open a survey and append each item; returns the survey after rollup."""
    survey = get_success_data(api_client.create_survey(
        create_survey_payload(move_job_id, survey_method), ESTIMATOR))
    for it in items:
        api_client.add_survey_item(
            survey["id"], create_survey_item_payload(**it), ESTIMATOR)
    return get_success_data(api_client.get_survey(survey["id"], ESTIMATOR))


# ─── Tier 1: survey + (optional packing) + estimate ───────────────────────────
def setup_job_with_survey(customer_id=None, service_type="LOCAL", items=None,
                          survey_method="IN_HOME", job_overrides=None):
    """Customer + QUOTING job + survey populated with `items`.

    Returns (customer, job, survey). Re-fetches the job so its current version
    is exact for any subsequent OCC-gated estimate create.
    """
    if customer_id is None:
        customer_id = register_customer()["id"]
    job = create_job(customer_id, service_type, **(job_overrides or {}))
    survey = create_survey_with_items(
        job["id"], items if items is not None else ITEMS_120CF, survey_method)
    job = get_success_data(api_client.get_move_job(job["id"], PLATFORM_ADMIN))
    return customer_id, job, survey


def add_packing_order(move_job_id, packing_lines, crate_count=0) -> dict:
    return get_success_data(api_client.create_packing_order(
        create_packing_order_payload(move_job_id, packing_lines, crate_count=crate_count),
        ESTIMATOR))


def generate_estimate(move_job_id, survey_id, expected_version,
                      binding_type="NON_BINDING", valuation_coverage="RELEASED",
                      estimator_user_id="test-estimator-1", **overrides) -> dict:
    """Generate (POST) one estimate. Locks the survey, bumps the job version."""
    return get_success_data(api_client.create_estimate(
        create_estimate_payload(move_job_id, survey_id, expected_version,
                                binding_type, valuation_coverage, **overrides),
        make_estimator_headers(estimator_user_id)))


def setup_job_with_estimate(customer_id=None, service_type="LOCAL", items=None,
                            binding_type="NON_BINDING", valuation_coverage="RELEASED",
                            packing_lines=None, crate_count=0, job_overrides=None,
                            **estimate_overrides):
    """Customer + QUOTING job + survey + (optional packing) + DRAFT estimate.

    Returns (customer_id, job, survey, estimate). The estimate is created against
    the job's current version (read after any packing order, which does not bump
    the job, but we re-fetch defensively).
    """
    customer_id, job, survey = setup_job_with_survey(
        customer_id, service_type, items, job_overrides=job_overrides)
    if packing_lines is not None or crate_count:
        add_packing_order(job["id"], packing_lines or [], crate_count)
        job = get_success_data(api_client.get_move_job(job["id"], PLATFORM_ADMIN))
    estimate = generate_estimate(
        job["id"], survey["id"], job["version"],
        binding_type, valuation_coverage, **estimate_overrides)
    return customer_id, job, survey, estimate


# ─── Tier 2: booked job (estimate accepted) ───────────────────────────────────
def accept_estimate(estimate_id, customer_id) -> dict:
    return get_success_data(api_client.accept_estimate(
        estimate_id, make_customer_headers(customer_id)))


def setup_booked_job(customer_id=None, service_type="LOCAL", items=None,
                     binding_type="NON_BINDING", valuation_coverage="RELEASED",
                     packing_lines=None, crate_count=0, job_overrides=None,
                     **estimate_overrides):
    """A BOOKED job: estimate accepted. Returns (customer_id, job, survey, estimate)."""
    customer_id, job, survey, estimate = setup_job_with_estimate(
        customer_id, service_type, items, binding_type, valuation_coverage,
        packing_lines, crate_count, job_overrides, **estimate_overrides)
    accept_estimate(estimate["id"], customer_id)
    job = get_success_data(api_client.get_move_job(job["id"], make_customer_headers(customer_id)))
    return customer_id, job, survey, estimate


def pay_deposit(move_job_id, customer_id, amount_cents=10000) -> dict:
    return get_success_data(api_client.create_payment(
        move_job_id, {"kind": "DEPOSIT", "amount_cents": amount_cents},
        make_customer_headers(customer_id)))


def setup_deposit_paid_job(customer_id=None, service_type="LOCAL", items=None,
                           binding_type="NON_BINDING", valuation_coverage="RELEASED",
                           packing_lines=None, crate_count=0, deposit_cents=10000,
                           job_overrides=None, **estimate_overrides):
    """A BOOKED + DEPOSIT_PAID job. Returns (customer_id, job, survey, estimate)."""
    customer_id, job, survey, estimate = setup_booked_job(
        customer_id, service_type, items, binding_type, valuation_coverage,
        packing_lines, crate_count, job_overrides, **estimate_overrides)
    pay_deposit(job["id"], customer_id, deposit_cents)
    job = get_success_data(api_client.get_move_job(job["id"], make_customer_headers(customer_id)))
    return customer_id, job, survey, estimate


# ─── Tier 3: scheduled / en-route dispatch ────────────────────────────────────
def schedule_dispatch(move_job_id, truck_id=None, crew_id=None,
                      window_start="2026-07-01T09:00:00Z",
                      window_end="2026-07-01T12:00:00Z",
                      required_crew_size=3, truck_capacity=2000, crew_head_count=3) -> dict:
    """Create a SCHEDULED dispatch, registering a truck/crew if not supplied."""
    if truck_id is None:
        truck_id = register_truck(capacity_cubic_feet=truck_capacity)["id"]
    if crew_id is None:
        crew_id = register_crew(head_count=crew_head_count)["id"]
    return get_success_data(api_client.create_dispatch(
        create_dispatch_payload(move_job_id, truck_id, crew_id,
                                window_start, window_end, required_crew_size),
        DISPATCHER))


def setup_scheduled_dispatch(customer_id=None, service_type="LOCAL", items=None,
                             binding_type="NON_BINDING", valuation_coverage="RELEASED",
                             packing_lines=None, crate_count=0, deposit_cents=10000,
                             job_overrides=None, **estimate_overrides):
    """Deposit-paid job + a SCHEDULED dispatch.

    Returns (customer_id, job, estimate, dispatch).
    """
    customer_id, job, survey, estimate = setup_deposit_paid_job(
        customer_id, service_type, items, binding_type, valuation_coverage,
        packing_lines, crate_count, deposit_cents, job_overrides, **estimate_overrides)
    dispatch = schedule_dispatch(job["id"])
    return customer_id, job, estimate, dispatch


def setup_en_route_dispatch(customer_id=None, service_type="LOCAL", items=None,
                            binding_type="NON_BINDING", valuation_coverage="RELEASED",
                            packing_lines=None, crate_count=0, deposit_cents=10000,
                            job_overrides=None, **estimate_overrides):
    """Job departed: dispatch EN_ROUTE, job IN_TRANSIT.

    Returns (customer_id, job, estimate, dispatch).
    """
    customer_id, job, estimate, dispatch = setup_scheduled_dispatch(
        customer_id, service_type, items, binding_type, valuation_coverage,
        packing_lines, crate_count, deposit_cents, job_overrides, **estimate_overrides)
    get_success_data(api_client.depart_dispatch(dispatch["id"], DISPATCHER))
    return customer_id, job, estimate, dispatch


# ─── Tier 4: delivered job (dispatch completed) ───────────────────────────────
def setup_delivered_job(customer_id=None, service_type="LOCAL", items=None,
                        binding_type="NON_BINDING", valuation_coverage="RELEASED",
                        packing_lines=None, crate_count=0, deposit_cents=10000,
                        actual_weight_lbs=840, job_overrides=None, **estimate_overrides):
    """A DELIVERED job: dispatch completed with `actual_weight_lbs`.

    Returns (customer_id, job, estimate, dispatch) with the job re-fetched so
    final_charge_cents / balance_due_cents are current.
    """
    customer_id, job, estimate, dispatch = setup_en_route_dispatch(
        customer_id, service_type, items, binding_type, valuation_coverage,
        packing_lines, crate_count, deposit_cents, job_overrides, **estimate_overrides)
    get_success_data(api_client.complete_dispatch(
        dispatch["id"], {"actual_weight_lbs": actual_weight_lbs}, DISPATCHER))
    job = get_success_data(api_client.get_move_job(job["id"], PLATFORM_ADMIN))
    return customer_id, job, estimate, dispatch


# ─── Tier 5: storage lots & claims on delivered jobs ──────────────────────────
def open_storage_lot(move_job_id, intake_date="2026-07-01T00:00:00Z") -> dict:
    return get_success_data(api_client.create_storage_lot(
        create_storage_lot_payload(move_job_id, intake_date), DISPATCHER))


def setup_released_storage_lot(intake_date="2026-07-01T00:00:00Z",
                               release_date="2026-07-11T00:00:00Z"):
    """Delivered job + a RELEASED storage lot (SIT accrued to the job ledger).

    Default dates give 10 raw days -> 7 billable days -> 51400 cents.
    Returns (customer_id, job, lot). The job is re-fetched post-release.
    """
    customer_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LOCAL", items=ITEMS_120CF, binding_type="BINDING",
        valuation_coverage="RELEASED")
    # Open the lot before delivery is acceptable too, but opening it now keeps the
    # ledger ordering deterministic: gross already holds the estimate at acceptance.
    lot = open_storage_lot(job["id"], intake_date)
    lot = get_success_data(api_client.release_storage_lot(
        lot["id"], {"release_date": release_date}, DISPATCHER))
    job = get_success_data(api_client.get_move_job(job["id"], PLATFORM_ADMIN))
    return customer_id, job, lot


def file_claim(move_job_id, filer_user_id="adj-filer") -> dict:
    return get_success_data(api_client.create_damage_claim(
        create_damage_claim_payload(move_job_id),
        make_claims_adjuster_headers(filer_user_id)))


def add_claim_item(claim_id, filer_user_id="adj-filer", **item_overrides) -> dict:
    return get_success_data(api_client.add_claim_item(
        claim_id, create_claim_item_payload(**item_overrides),
        make_claims_adjuster_headers(filer_user_id)))


def setup_claim_under_review(valuation_coverage="RELEASED", deductible_cents=0,
                            declared_value_cents=None, item_overrides=None,
                            filer_user_id="adj-filer", with_item=True):
    """A DELIVERED job with an UNDER_REVIEW claim filed by `filer_user_id`.

    For FULL_VALUE coverage pass declared_value_cents and deductible_cents so the
    accepted estimate validates; the claim snapshots them at filing.
    Returns (customer_id, job, estimate, claim).
    """
    est_kwargs = {}
    if valuation_coverage == "FULL_VALUE":
        est_kwargs["declared_value_cents"] = (
            declared_value_cents if declared_value_cents is not None else 600000)
        est_kwargs["deductible_cents"] = deductible_cents
    customer_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LOCAL", items=ITEMS_120CF, binding_type="NON_BINDING",
        valuation_coverage=valuation_coverage, **est_kwargs)
    claim = file_claim(job["id"], filer_user_id)
    if with_item:
        add_claim_item(claim["id"], filer_user_id, **(item_overrides or {}))
    return customer_id, job, estimate, claim


def setup_approved_claim(valuation_coverage="RELEASED", deductible_cents=0,
                         declared_value_cents=None, item_overrides=None,
                         filer_user_id="adj-filer", approver_user_id="adj-approver"):
    """A DELIVERED job with an APPROVED claim (settlement computed and credited).

    Returns (customer_id, job, estimate, claim) with the claim re-fetched.
    """
    customer_id, job, estimate, claim = setup_claim_under_review(
        valuation_coverage, deductible_cents, declared_value_cents,
        item_overrides, filer_user_id, with_item=True)
    claim = get_success_data(api_client.approve_damage_claim(
        claim["id"], make_claims_adjuster_headers(approver_user_id)))
    return customer_id, job, estimate, claim
