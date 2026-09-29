"""Cross-entity gates: a grandparent, an independent aggregate and a sibling."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── Two ownership hops up: the grandparent project ───────────────────────────

def _author_initial_appraisal(api, parcel_id):
    return api.create_appraisal(
        parcel_id,
        factories.create_appraisal_payload(
            parcel_id,
            appraiser_license_no="LIC-SA-1",
            effective_date="2026-07-01",
            indicated_value_cents=20_000_000,
        ),
        TEST_USERS["staff_appraiser_headers"],
    )


def test_authoring_an_appraisal_is_barred_while_the_grandparent_is_only_submitted(api):
    """The parcel and the body are both fine; only the project two hops up blocks it.

    "The project must be in `APPROVED`, otherwise `ERR_PROJECT_NOT_APPROVED`."

    "Creating an `INITIAL` appraisal also starts the parcel's acquisition
    dimension: if the parcel's `acquisition_status` is `NOT_STARTED` and its
    `participation_status` is `INTERESTED` or `VOLUNTARY_CONFIRMED`,
    `acquisition_status` moves to `APPRAISAL_IN_PROGRESS` and the parcel's
    `version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/appraisal_creation_depends_on_grandparent_project_reaching_approved
    """
    state = fixtures.create_validated_project(api)
    assert state["project"]["status"] == "SUBMITTED"

    validate_error(
        _author_initial_appraisal(api, state["parcel"]["id"]),
        ApiErrorId.ERR_PROJECT_NOT_APPROVED.value,
        409,
    )

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "NOT_STARTED"


def test_the_identical_authoring_call_succeeds_once_the_project_is_approved(api):
    """Nothing about the request changes; only the grandparent's status does.

    "On approval the project moves to `APPROVED`, the whole
    neighborhood-viability family (`participating_parcel_count`,
    `holdout_parcel_count`, `contiguous_open_space_parcel_count`,
    `largest_component_parcel_ids`, `neighborhood_viability_ratio`,
    `viability_status`) is recomputed, and the project's `version` advances by 1."

    "The server stamps `appraiser_user_id` with the acting `X-User-ID`, and the
    row opens in `status` `DRAFT` with `revision_count` 0, `validity_end_date`
    null and `version` 1."

    Design: Difficulty/cross_entity_state_dependency/appraisal_creation_depends_on_grandparent_project_reaching_approved
    """
    state = fixtures.create_validated_project(api)
    validate_error(
        _author_initial_appraisal(api, state["parcel"]["id"]),
        ApiErrorId.ERR_PROJECT_NOT_APPROVED.value,
        409,
    )

    project = validate_success(
        api.approve_mitigation_project(
            state["project"]["id"],
            factories.approve_project_payload(state["project"]["id"], "APPROVE"),
            TEST_USERS["project_approver_headers"],
        )
    )
    assert project["status"] == "APPROVED"

    appraisal = validate_success(
        _author_initial_appraisal(api, state["parcel"]["id"]), 201
    )
    assert appraisal["status"] == "DRAFT"
    assert appraisal["appraiser_user_id"] == "sa-1"
    assert appraisal["revision_count"] == 0
    assert appraisal["validity_end_date"] is None


# ─── An independent referenced root: the contractor ───────────────────────────

def _ready_work_order_under_a_suspended_contractor(api):
    """A fully READY work order whose contractor has since been suspended."""
    project = fixtures.create_draft_project(api)
    parcel = fixtures.create_parcel(api, project)
    contractor = fixtures.create_contractor(api, asbestos_certified=True)
    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"], asbestos_survey_status="CLEARED"
    )
    disconnections = fixtures.order_all_utility_disconnections(
        api, project, work_order["id"]
    )
    fixtures.confirm_all_utility_disconnections(api, project, disconnections)
    work_order = validate_success(
        api.get_demolition_work_order(
            work_order["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert work_order["status"] == "READY"
    contractor = validate_success(
        api.set_contractor_status(
            contractor["id"],
            factories.contractor_status_payload(contractor["id"], "SUSPENDED"),
            TEST_USERS["program_administrator_headers"],
        )
    )
    assert contractor["status"] == "SUSPENDED"
    return {
        "project": project,
        "parcel": parcel,
        "contractor": contractor,
        "work_order": work_order,
    }


def test_a_ready_work_order_cannot_mobilize_under_a_suspended_contractor(api):
    """The gate reads the contractor's current status, not the one at issue time.

    "Second, the contractor's `status` must be `ACTIVE`, otherwise
    `ERR_CONTRACTOR_SUSPENDED`."

    "Suspension is deliberately shallow: existing work orders are left exactly
    where they are and none of their fields change; the only effect is that no
    work order may thereafter be mobilized under that contractor."

    Design: Difficulty/cross_entity_state_dependency/demolition_start_depends_on_independent_contractor_aggregate_status
    """
    state = _ready_work_order_under_a_suspended_contractor(api)

    validate_error(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_CONTRACTOR_SUSPENDED.value,
        409,
    )

    work_order = validate_success(
        api.get_demolition_work_order(
            state["work_order"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert work_order["status"] == "READY"
    assert work_order["asbestos_survey_status"] == "CLEARED"


def test_reinstating_the_contractor_lifts_the_block_on_the_same_work_order(api):
    """The reverse edge on an entity outside the ownership chain unblocks the start.

    "Reinstatement is the reverse edge and lifts that block."

    "`active_work_order_count` is the count of that contractor's work orders whose
    `status` is `ISSUED`, `UTILITY_HOLD`, `READY`, `IN_PROGRESS` or
    `FAILED_INSPECTION`."

    Design: Difficulty/cross_entity_state_dependency/demolition_start_depends_on_independent_contractor_aggregate_status
    """
    state = _ready_work_order_under_a_suspended_contractor(api)
    validate_error(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_CONTRACTOR_SUSPENDED.value,
        409,
    )

    contractor = validate_success(
        api.set_contractor_status(
            state["contractor"]["id"],
            factories.contractor_status_payload(state["contractor"]["id"], "ACTIVE"),
            TEST_USERS["program_administrator_headers"],
        )
    )
    assert contractor["status"] == "ACTIVE"

    started = validate_success(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    assert started["status"] == "IN_PROGRESS"

    refreshed = validate_success(
        api.get_demolition_contractor(
            state["contractor"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert refreshed["active_work_order_count"] == 1


# ─── A lateral sibling: the relocation case on the same parcel ────────────────

def _scheduled_closing_beside_an_open_case(api):
    state = fixtures.parcel_with_scheduled_closing(api)
    state["case"] = fixtures.open_relocation_case(
        api,
        state["parcel"]["id"],
        displacee_type="OWNER_OCCUPANT",
        rhp_method="COMPARABLE_DWELLING",
        comparable_dwelling_price_cents=22_000_000,
        moving_expense_cents=175_000,
    )
    assert state["case"]["status"] == "OPENED"
    return state


def _fund(api, closing_id):
    return api.fund_closing_record(
        closing_id, TEST_USERS["program_administrator_headers"]
    )


def test_funding_is_barred_while_a_sibling_relocation_case_is_still_open(api):
    """The blocker is a sibling child of the same parcel, not an ancestor.

    "Every `RelocationCase` on the same parcel must have `status` of `CLAIM_PAID`
    or `CLAIM_DENIED_FINAL` - a case still sitting in `OPENED`,
    `ELIGIBILITY_DETERMINED`, `CLAIM_SUBMITTED`, `CLAIM_DENIED` or `APPEALED`
    blocks funding with `ERR_RELOCATION_NOT_SETTLED`, because the displacee's
    entitlement must be resolved before title passes."

    Design: Difficulty/cross_entity_state_dependency/closing_funding_depends_on_sibling_relocation_case_reaching_settlement
    """
    state = _scheduled_closing_beside_an_open_case(api)

    validate_error(
        _fund(api, state["closing"]["id"]),
        ApiErrorId.ERR_RELOCATION_NOT_SETTLED.value,
        409,
    )

    closing = validate_success(
        api.get_closing_record(
            state["closing"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert closing["status"] == "SCHEDULED"


def test_paying_the_sibling_claim_unblocks_funding_and_both_items_book(api):
    """Settling the sibling permits funding, and the ledger carries both shares.

    "`PAY` is admitted only from `CLAIM_SUBMITTED`, and requires the obligation
    cap to hold - the project's current `federal_obligated_cents` plus this case's
    `total_relocation_benefit_cents` multiplied by `cost_share_federal_pct` and
    rounded half up to whole cents must be at most `total_federal_share_cap_cents`,
    otherwise `ERR_FEDERAL_SHARE_CAP_EXCEEDED`."

    "Funding moves the closing to `FUNDED`, stamps `funded_at` from the logical
    clock and `funded_by_user_id` with the acting `X-User-ID`, moves the parcel's
    `acquisition_status` from `OFFER_ACCEPTED` to `CLOSED`, recomputes the
    project's `federal_obligated_cents` to include the settlement-cost item."

    "Note that `purchase_price_cents` is not what enters the ledger; only
    `settlement_cost_cents` does, because the purchase price was already obligated
    when the offer was presented."

    Design: Difficulty/cross_entity_state_dependency/closing_funding_depends_on_sibling_relocation_case_reaching_settlement
    """
    state = _scheduled_closing_beside_an_open_case(api)
    validate_error(
        _fund(api, state["closing"]["id"]),
        ApiErrorId.ERR_RELOCATION_NOT_SETTLED.value,
        409,
    )

    specialist = TEST_USERS["relocation_specialist_headers"]
    case = validate_success(
        api.determine_relocation_eligibility(state["case"]["id"], specialist)
    )
    assert case["replacement_housing_payment_cents"] == 600_000
    assert case["total_relocation_benefit_cents"] == 775_000

    validate_success(api.submit_relocation_claim(case["id"], specialist))
    case = validate_success(
        api.resolve_relocation_claim(
            case["id"],
            factories.resolve_claim_payload(case["id"], "PAY"),
            TEST_USERS["program_administrator_headers"],
        )
    )
    assert case["status"] == "CLAIM_PAID"

    closing = validate_success(_fund(api, state["closing"]["id"]))
    assert closing["status"] == "FUNDED"
    assert closing["funded_by_user_id"] == "pa-1"
    assert closing["purchase_price_cents"] == 21_400_000

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "CLOSED"

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 16_931_250
