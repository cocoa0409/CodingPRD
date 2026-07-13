"""Capital projects, the percent-for-art budget, and the project budget ledger."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    make_project_payload, make_certify_payload, make_commission_payload,
    assert_budget_invariant,
    create_certified_project, create_commission,
    setup_open_call_with_submission,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_create_project_returns_provisional_budget(api):
    """PRD §3.1: "At creation the spendable art budget, `art_budget_cents`, is
    computed in its **provisional** variant: multiply `construction_budget_cents`
    by `percent_rate` and round the resulting cents product half-up to a whole
    number of cents."
    PRD §3.1: "Because no commissions exist yet, `committed_cents` is set to 0 and
    `uncommitted_cents` equals the full `art_budget_cents`."

    Design: Corner/entities/create_project_returns_all_fields_and_provisional_budget
    """
    data = validate_success(api.create_project(
        make_project_payload(name="Depot Park", construction_budget_cents=100000000,
                             percent_rate=0.01), ADMIN), 201)
    assert data["status"] == "DRAFT"
    assert data["committed_cents"] == 0
    assert data["art_budget_cents"] == 1000000


def test_default_percent_rate_applied_when_omitted(api):
    """PRD §3.1: "The percent-for-art rate, `percent_rate`, is optional; when
    omitted it defaults to 0.01 (one percent), and any supplied rate must lie
    between the minimum of 0.005 (half a percent) and the maximum of 0.05 (five
    percent), inclusive of both bounds."

    Design: Corner/entities/default_percent_rate_applied_when_omitted
    """
    payload = {"name": "Default Park", "construction_budget_cents": 100000000}
    data = validate_success(api.create_project(payload, ADMIN), 201)
    assert data["percent_rate"] == 0.01
    assert data["art_budget_cents"] == 1000000


def test_get_nonexistent_project_returns_not_found(api):
    """PRD §2.9: "A missing resource yields the corresponding not-found error
    (`ERR_PROJECT_NOT_FOUND`, `ERR_COMMISSION_NOT_FOUND`, `ERR_CALL_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`,
    `ERR_SCORE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`,
    `ERR_ARTWORK_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, or `ERR_LOAN_NOT_FOUND`), each
    returned with HTTP 404."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    resp = api.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)


def test_certify_recomputes_final_art_budget(api):
    """PRD §3.1: "Certification is permitted only while the project is in `DRAFT`;
    it advances the project `DRAFT → BUDGET_CERTIFIED` and recomputes
    `art_budget_cents` in its **final** variant — `certified_construction_budget_cents`
    multiplied by `percent_rate`, again rounded half-up to whole cents."
    PRD §3.1: "The final figure typically diverges from the provisional one."

    Design: Difficulty/dual_variant_calc/art_budget_provisional_vs_final_on_project
    """
    proj = get_success_data(api.create_project(
        make_project_payload(name="Riverfront Plaza", construction_budget_cents=200000000,
                             percent_rate=0.01), ADMIN))
    assert proj["art_budget_cents"] == 2000000, "provisional variant before certify"
    certified = validate_success(api.certify_project(
        proj["id"], make_certify_payload(150000000), ADMIN), 200)
    assert certified["status"] == "BUDGET_CERTIFIED"
    assert certified["art_budget_cents"] == 1500000


def test_provisional_and_final_variants_diverge(api):
    """PRD §3.1: "At creation the spendable art budget, `art_budget_cents`, is
    computed in its **provisional** variant: multiply `construction_budget_cents`
    by `percent_rate` and round the resulting cents product half-up to a whole
    number of cents."
    PRD §3.1: "The final figure typically diverges from the provisional one."

    Design: Difficulty/dual_variant_calc/art_budget_provisional_vs_final_on_project
    """
    proj = get_success_data(api.create_project(
        make_project_payload(name="Riverfront Plaza", construction_budget_cents=200000000,
                             percent_rate=0.01), ADMIN))
    provisional = proj["art_budget_cents"]
    certified = get_success_data(api.certify_project(
        proj["id"], make_certify_payload(150000000), ADMIN))
    assert provisional == 2000000
    assert certified["art_budget_cents"] == 1500000
    assert certified["art_budget_cents"] != provisional


def test_double_certify_returns_invalid_state(api):
    """PRD §3.1: "Certification is permitted only while the project is in `DRAFT`;
    it advances the project `DRAFT → BUDGET_CERTIFIED`"
    PRD §3.1: "`BUDGET_CERTIFIED` is terminal for the project lifecycle."

    Design: Corner/state_machines/double_certify_project_returns_invalid_state
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    resp = api.certify_project(proj["id"], make_certify_payload(190000000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_initial_commission_status_is_open(api):
    """PRD §3.2: "On success the commission is stored with its `project_id` and an
    initial status of `OPEN`, its `awarded_submission_id` is null, the project's
    `committed_cents` rises and `uncommitted_cents` falls by the allocation, and
    the project's `version` increments by one."

    Design: Corner/state_machines/initial_commission_status_is_open
    """
    proj = create_certified_project(api)
    comm = validate_success(api.create_commission(
        proj["id"], make_commission_payload(500000, proj["version"], title="Fresh"),
        ADMIN), 201)
    assert comm["status"] == "OPEN"


def test_committed_cents_reconciled_after_commission_create(api):
    """PRD §2.7: "The `committed_cents` figure is the sum of `allocation_cents`
    across every child commission of the project whose `status` is not `CANCELLED`,
    and `uncommitted_cents` is `art_budget_cents` minus `committed_cents`."

    Design: Corner/cross_cutting_complexity_layers/committed_cents_reconciled_after_commission_create
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    create_commission(api, proj["id"], allocation_cents=500000, expected_version=proj["version"])
    refreshed = get_success_data(api.get_project(proj["id"], ADMIN))
    assert refreshed["committed_cents"] == 500000
    assert refreshed["uncommitted_cents"] == 1500000


def test_stale_project_version_on_commission_create_rejected(api):
    """PRD §2.6: "If the project's current `version` has advanced beyond that
    value — because another writer already created a commission that consumed part
    of the art budget and bumped the project's `version` and `committed_cents` —
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_commission_create
    """
    proj = create_certified_project(api)
    stale_version = proj["version"]
    validate_success(api.create_commission(
        proj["id"], make_commission_payload(500000, stale_version, title="First"), ADMIN), 201)
    resp = api.create_commission(
        proj["id"], make_commission_payload(500000, stale_version, title="Stale"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_allocation_equal_to_budget_is_accepted(api):
    """PRD §3.2: "the project's `committed_cents` plus the requested
    `allocation_cents` must not exceed `art_budget_cents`. If it would, the request
    is rejected with `ERR_ALLOCATION_EXCEEDS_BUDGET` (HTTP 422); the boundary is
    inclusive, so an allocation that brings committed exactly up to the budget is
    allowed."

    Design: Difficulty/boundary_precision_check/allocation_equal_budget_ok_one_cent_over_fails
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    comm = validate_success(api.create_commission(
        proj["id"], make_commission_payload(2000000, proj["version"], title="Exact"),
        ADMIN), 201)
    assert comm["status"] == "OPEN"
    refreshed = get_success_data(api.get_project(proj["id"], ADMIN))
    assert refreshed["committed_cents"] == 2000000


def test_allocation_one_cent_over_budget_rejected(api):
    """PRD §3.2: "the project's `committed_cents` plus the requested
    `allocation_cents` must not exceed `art_budget_cents`. If it would, the request
    is rejected with `ERR_ALLOCATION_EXCEEDS_BUDGET` (HTTP 422); the boundary is
    inclusive, so an allocation that brings committed exactly up to the budget is
    allowed."

    Design: Difficulty/boundary_precision_check/allocation_equal_budget_ok_one_cent_over_fails
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    create_commission(api, proj["id"], allocation_cents=2000000, title="Exact",
                      expected_version=proj["version"])
    refreshed = get_success_data(api.get_project(proj["id"], ADMIN))
    assert refreshed["committed_cents"] == 2000000
    resp = api.create_commission(
        proj["id"], make_commission_payload(1, refreshed["version"], title="OneOver"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_BUDGET.value, 422)


def test_cancel_commission_restores_committed_and_uncommitted(api):
    """PRD §3.2: "Cancellation releases the budget: the commission is dropped from
    the committed sum, so the project's `committed_cents` decreases by
    `allocation_cents` and `uncommitted_cents` increases by the same amount,
    restoring the budget invariant."

    Design: Difficulty/compensating_invariant/budget_conserved_on_commission_cancel
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    comm = create_commission(api, proj["id"], allocation_cents=800000,
                             expected_version=proj["version"])
    validate_success(api.cancel_commission(comm["id"], ADMIN), 200)
    refreshed = get_success_data(api.get_project(proj["id"], ADMIN))
    assert refreshed["committed_cents"] == 0
    assert refreshed["uncommitted_cents"] == 2000000


def test_budget_invariant_holds_after_cancel(api):
    """PRD §2.7: "the art budget is conserved: `art_budget_cents` always equals
    `uncommitted_cents` plus `committed_cents`."

    Design: Difficulty/compensating_invariant/budget_conserved_on_commission_cancel
    """
    proj = create_certified_project(api, construction_budget_cents=200000000,
                                    certified_construction_budget_cents=200000000)
    comm = create_commission(api, proj["id"], allocation_cents=800000,
                             expected_version=proj["version"])
    validate_success(api.cancel_commission(comm["id"], ADMIN), 200)
    refreshed = get_success_data(api.get_project(proj["id"], ADMIN))
    assert refreshed["art_budget_cents"] == 2000000
    assert_budget_invariant(refreshed)
