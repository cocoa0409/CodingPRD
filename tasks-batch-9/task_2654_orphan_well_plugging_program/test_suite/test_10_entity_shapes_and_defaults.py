"""Row shape on creation and retrieval: computed fields, defaults and rejections."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_immutable_row,
    assert_null_fields,
    assert_page,
    assert_score,
)
from test_helpers.constants import ZERO_UUID


def test_a_fresh_operator_has_zero_exposure_and_version_one(api: ApiClient):
    """An operator with no wells owes nothing and starts its version counter at one.

    The assurance calculation over an empty well set answers 0 rather than null, and an
    operator that has posted nothing at all is still in good standing because the
    deficiency comparison is a strict one.

    PRD: "A freshly registered operator has no wells, so its computed
    `required_bond_cents` is 0, its `active_well_count` and `orphan_candidate_count` are
    both 0, and its `status` begins at `ACTIVE`."

    Design: Corner/entities/operator_creation_returns_zero_exposure_and_version_one
    """
    row = validate_success(
        api.create_operator(
            {
                "name": "Cottonwood Energy LLC",
                "region_code": "WY",
                "financial_assurance_tier": "BLANKET",
                "bond_amount_cents": 0,
            },
            users.ADMIN,
        ),
        201,
    )

    assert_fields(
        row,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        status="ACTIVE",
        active_well_count=0,
        orphan_candidate_count=0,
        version=1,
        created_at="2026-08-01T00:00:00.000Z",
    )
    assert_cents(row["bond_amount_cents"], 0, "bond_amount_cents")
    assert_cents(row["required_bond_cents"], 0, "required_bond_cents")
    assert_null_fields(
        row, "successor_operator_id", "insolvency_declared_at", "bond_forfeited_at"
    )


def test_well_creation_computes_its_own_scores_and_lifecycle_fields(api: ApiClient):
    """Values offered for the derived fields are replaced by the computed ones.

    The payload names a screening score, a remediation score, a lifecycle status, an
    access status, an idle count and a version, and every one of them is answered with
    the figure the rules produce instead.

    PRD: "Creating a well is not a passive insert. Both priority scores are computed
    immediately, writing `screening_score` and `remediation_score`; the idle-well and
    de-minimis figures are computed, writing `idle_months` and `cumulative_boe_60mo`"

    Design: Corner/entities/well_creation_computed_and_system_fields_input_ignored
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")

    row = validate_success(
        api.create_well(
            {
                "api_well_number": "49-001-92001",
                "operator_id": operator["id"],
                "spud_year": 1974,
                "total_depth_ft": 2500,
                "casing_strings": 2,
                "methane_scfd": 250,
                "groundwater_depth_ft": 40,
                "population_within_1000ft": 8,
                "surface_disturbance_acres": 2.0,
                "screening_score": 99.99,
                "remediation_score": 0.01,
                "status": "ORPHAN_CONFIRMED",
                "access_status": "ENTRY_ORDERED",
                "idle_months": 1,
                "version": 77,
            },
            users.INSPECTOR,
        ),
        201,
    )

    assert_score(row["screening_score"], 59.90, "screening_score")
    assert_score(row["remediation_score"], 81.00, "remediation_score")
    assert_score(row["cumulative_boe_60mo"], 0.00, "cumulative_boe_60mo")
    assert_fields(
        row,
        status="PRODUCING",
        access_status="NO_ACCESS_REQUESTED",
        idle_months=999,
        version=1,
    )
    assert_null_fields(row, "orphan_confirmed_at", "last_production_month")


def test_reading_a_well_returns_the_state_that_was_stored_at_creation(api: ApiClient):
    """The fetch echoes the persisted figures rather than deriving fresh ones.

    Nothing about the well has changed between the create and the read, so the same two
    scores, the same idle count and the same version come back.

    PRD: "Neither score is ever computed lazily at read time - a well fetched from the
    API always exposes the two values that were current at its last write."

    Design: Corner/entities/well_retrieval_returns_the_stored_and_computed_state
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    created = fx.make_well(api, operator["id"], api_well_number="49-001-92002")

    row = validate_success(api.get_well(created["id"], users.ADMIN), 200)

    assert_fields(
        row,
        id=created["id"],
        api_well_number="49-001-92002",
        operator_id=operator["id"],
        total_depth_ft=2500,
        methane_scfd=250,
        status="PRODUCING",
        access_status="NO_ACCESS_REQUESTED",
        idle_months=999,
        version=1,
    )
    assert_score(row["screening_score"], 59.90, "screening_score")
    assert_score(row["remediation_score"], 81.00, "remediation_score")


def test_each_entity_answers_an_absent_path_id_with_its_own_not_found(api: ApiClient):
    """Fourteen reads of the same absent identifier give fourteen different error ids.

    A single shared not-found identifier would collapse these answers into one; the
    catalogue insists on one error per entity.

    PRD: "The full set of not-found errors is one per entity: `ERR_OPERATOR_NOT_FOUND`,
    `ERR_WELL_NOT_FOUND`, `ERR_ORPHAN_DETERMINATION_NOT_FOUND`,
    `ERR_SITE_ACCESS_NOT_FOUND`, `ERR_WELL_TRANSFER_NOT_FOUND`,
    `ERR_CONTRACTOR_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
    `ERR_UNIT_COST_CONTRACT_NOT_FOUND`, `ERR_PLUGGING_JOB_NOT_FOUND`,
    `ERR_RECLAMATION_TASK_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_FUNDING_ALLOCATION_NOT_FOUND` and `ERR_GRANT_REPORT_NOT_FOUND` - each with HTTP
    404."

    Design: Corner/entities/nonexistent_path_ids_return_the_owning_entitys_not_found_error
    """
    reads = [
        (api.get_operator(ZERO_UUID, users.ADMIN), e.ERR_OPERATOR_NOT_FOUND),
        (api.get_well(ZERO_UUID, users.ADMIN), e.ERR_WELL_NOT_FOUND),
        (
            api.get_orphan_determination(ZERO_UUID, users.ADMIN),
            e.ERR_ORPHAN_DETERMINATION_NOT_FOUND,
        ),
        (api.get_site_access(ZERO_UUID, users.ADMIN), e.ERR_SITE_ACCESS_NOT_FOUND),
        (api.get_well_transfer(ZERO_UUID, users.ADMIN), e.ERR_WELL_TRANSFER_NOT_FOUND),
        (api.get_contractor(ZERO_UUID, users.ADMIN), e.ERR_CONTRACTOR_NOT_FOUND),
        (
            api.get_solicitation(ZERO_UUID, users.PROCUREMENT),
            e.ERR_SOLICITATION_NOT_FOUND,
        ),
        (api.get_bid(ZERO_UUID, users.PROCUREMENT), e.ERR_BID_NOT_FOUND),
        (
            api.get_unit_cost_contract(ZERO_UUID, users.PROCUREMENT),
            e.ERR_UNIT_COST_CONTRACT_NOT_FOUND,
        ),
        (api.get_plugging_job(ZERO_UUID, users.ADMIN), e.ERR_PLUGGING_JOB_NOT_FOUND),
        (
            api.get_reclamation_task(ZERO_UUID, users.ADMIN),
            e.ERR_RECLAMATION_TASK_NOT_FOUND,
        ),
        (
            api.get_funding_source(ZERO_UUID, users.FUNDING),
            e.ERR_FUNDING_SOURCE_NOT_FOUND,
        ),
        (
            api.get_funding_allocation(ZERO_UUID, users.FUNDING),
            e.ERR_FUNDING_ALLOCATION_NOT_FOUND,
        ),
        (api.get_grant_report(ZERO_UUID, users.FUNDING), e.ERR_GRANT_REPORT_NOT_FOUND),
    ]
    for response, expected_error in reads:
        validate_error(response, expected_error, 404)


def test_every_create_rejects_a_missing_required_input_and_stores_nothing(api: ApiClient):
    """Four creates each drop one mandatory field and each is refused outright.

    A missing bond amount, a missing methane rate, a missing gas volume and a missing
    minimum technical score all land on the same schema error, and the inventory is
    unchanged afterwards.

    PRD: "Missing required inputs, wrong types, enum values outside their declared sets,
    numeric bound violations, malformed date strings and duplicate well numbers fail with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/missing_required_inputs_return_invalid_request_on_every_create
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"], api_well_number="49-001-92003")

    validate_error(
        api.create_operator(
            {
                "name": "No Bond Co",
                "region_code": "WY",
                "financial_assurance_tier": "BLANKET",
            },
            users.ADMIN,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_well(
            {
                "api_well_number": "49-001-92004",
                "operator_id": operator["id"],
                "spud_year": 1974,
                "total_depth_ft": 2500,
                "casing_strings": 2,
                "groundwater_depth_ft": 40,
                "population_within_1000ft": 8,
                "surface_disturbance_acres": 2.0,
            },
            users.INSPECTOR,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_production_record(
            well["id"], {"month": "2026-07", "oil_bbl": 10.0}, users.INSPECTOR
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_solicitation(
            {
                "region_code": "WY",
                "scope_description": "plugging services",
                "bid_due_at": "2026-08-20T00:00:00Z",
                "ceiling_cents": 20000000,
            },
            users.PROCUREMENT,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )

    assert_page(api.list_operators(users.ADMIN), 1, expected_total=1)
    assert_page(api.list_wells(users.ADMIN), 1, expected_total=1)
    assert_page(
        api.list_production_records(well["id"], users.INSPECTOR), 0, expected_total=0
    )


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(api: ApiClient):
    """The notice period default depends on the access mode, and money defaults to zero.

    A negotiated request gets no waiting period at all, so its window closes the instant
    it opens; a compelled one gets thirty days; and a state appropriation carries neither
    a match percentage nor a bond owner.

    PRD: "`waiting_period_days` is the statutory notice period, an integer from 0 through
    180; when it is omitted it defaults to 30 for `STATUTORY_ENTRY` mode and to 0 for
    `AGREEMENT` mode. `compensation_cents` is the surface damage compensation offered to
    the owner; it may not be negative and defaults to 0 when omitted."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    negotiated_well = fx.make_well(api, operator["id"], api_well_number="49-001-92005")
    compelled_well = fx.make_well(
        api, operator["id"], api_well_number="49-001-92006", spud_year=1976
    )

    negotiated = fx.open_site_access(api, negotiated_well["id"], mode="AGREEMENT")
    compelled = fx.open_site_access(api, compelled_well["id"], mode="STATUTORY_ENTRY")
    source = validate_success(
        api.create_funding_source(
            {
                "kind": "STATE_FUND",
                "name": "Wyoming orphan well account",
                "authorized_cents": 10000000,
                "expires_at": "2027-12-31T00:00:00Z",
                "allowable_cost_categories": ["PLUGGING"],
            },
            users.FUNDING,
        ),
        201,
    )

    assert_fields(
        negotiated,
        waiting_period_days=0,
        status="REQUESTED",
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-01T00:00:00Z",
    )
    assert_cents(negotiated["compensation_cents"], 0, "compensation_cents")
    assert_fields(
        compelled,
        waiting_period_days=30,
        status="REQUESTED",
        window_end_at="2026-08-31T00:00:00Z",
    )
    assert_null_fields(negotiated, "legal_authority_citation", "resolved_at")
    assert_null_fields(compelled, "legal_authority_citation", "resolved_at")

    assert_fields(source, status="ACTIVE", reporting_required=False)
    assert_null_fields(source, "federal_match_required_pct", "bond_operator_id")
    assert_cents(source["committed_cents"], 0, "committed_cents")
    assert_cents(source["disbursed_cents"], 0, "disbursed_cents")

    assert_fields(fx.read_well(api, negotiated_well["id"]), idle_months=999)


def test_a_production_record_carries_no_version_and_no_updated_timestamp(api: ApiClient):
    """The ledger line is append only, so two of the four common fields are absent.

    Its barrel-of-oil-equivalent figure and its filer are still server derived, and
    filing it moves the well's own idle and de-minimis figures forward.

    PRD: "a production record is an append-only ledger line, so it carries only `id` and
    `created_at` - it has neither `updated_at` nor `version`, and both fields are absent
    from its representation entirely."

    Design: Corner/entities/production_record_is_immutable_with_no_version_or_updated_at
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(
        api,
        operator["id"],
        api_well_number="49-001-92007",
        last_production_month="2026-06",
    )

    row = validate_success(
        api.create_production_record(
            well["id"],
            {"month": "2026-07", "oil_bbl": 150.0, "gas_mcf": 180.0},
            users.INSPECTOR,
        ),
        201,
    )

    assert_immutable_row(row)
    assert_score(row["boe"], 180.00, "boe")
    assert_fields(row, reported_by_user_id="u_insp", well_id=well["id"], month="2026-07")

    refreshed = fx.read_well(api, well["id"])
    assert_fields(refreshed, last_production_month="2026-07", idle_months=1)
    assert_score(refreshed["cumulative_boe_60mo"], 180.00, "cumulative_boe_60mo")


def test_bad_enums_bad_numbers_and_a_duplicate_well_number_all_fail_the_same_gate(
    api: ApiClient,
):
    """Five malformed requests are refused by schema validation before any rule runs.

    An assurance tier outside its set, a negative emission rate, a well number already in
    the inventory, an access mode outside its set and a page size of zero all answer with
    the one schema error.

    PRD: "A `limit` outside the range 1 through 100 is a schema violation and is rejected
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected_invalid_request
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"], api_well_number="49-001-92008")

    validate_error(
        api.create_operator(
            {
                "name": "Bad Tier Co",
                "region_code": "WY",
                "financial_assurance_tier": "PARTIAL",
                "bond_amount_cents": 100000,
            },
            users.ADMIN,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_well(
            {
                "api_well_number": "49-001-92009",
                "operator_id": operator["id"],
                "spud_year": 1974,
                "total_depth_ft": 2500,
                "casing_strings": 2,
                "methane_scfd": -1,
                "groundwater_depth_ft": 40,
                "population_within_1000ft": 8,
                "surface_disturbance_acres": 2.0,
            },
            users.INSPECTOR,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_well(
            {
                "api_well_number": "49-001-92008",
                "operator_id": operator["id"],
                "spud_year": 1980,
                "total_depth_ft": 2500,
                "casing_strings": 2,
                "methane_scfd": 10,
                "groundwater_depth_ft": 40,
                "population_within_1000ft": 8,
                "surface_disturbance_acres": 2.0,
            },
            users.INSPECTOR,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_site_access(
            well["id"],
            {"surface_owner_name": "Halvorsen Ranch", "mode": "COURT_ORDER"},
            users.ADMIN,
        ),
        e.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.list_wells(users.ADMIN, {"limit": 0}), e.ERR_INVALID_REQUEST, 422
    )

    assert_page(api.list_wells(users.ADMIN), 1, expected_total=1)


def test_foreign_keys_in_the_request_body_must_name_rows_that_exist(api: ApiClient):
    """An absent identifier inside the payload reports the referenced entity's own 404.

    Referential integrity is not confined to path parameters: an operator named on a well
    create, on a transfer proposal, a contractor named on a bid and a contract named on a
    job order each answer with the missing entity's error.

    PRD: "The same catalogue also serves foreign keys supplied in a request body rather
    than in the path: the `operator_id` on well creation, the `successor_operator_id` on
    an enforcement action, the `to_operator_id` on a transfer proposal, the
    contract-ceiling context on solicitation creation, the `contractor_id` on bid
    submission, the `well_id` and `contract_id` on plugging-job creation, and the
    `override_source_id` on a funding commitment all return the corresponding not-found
    error when they name no existing row."

    Design: Corner/entities/body_foreign_keys_must_name_existing_rows_not_found
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"], api_well_number="49-001-92010")
    solicitation = fx.make_open_solicitation(api)

    validate_error(
        api.create_well(
            {
                "api_well_number": "49-001-92011",
                "operator_id": ZERO_UUID,
                "spud_year": 1974,
                "total_depth_ft": 2500,
                "casing_strings": 2,
                "methane_scfd": 250,
                "groundwater_depth_ft": 40,
                "population_within_1000ft": 8,
                "surface_disturbance_acres": 2.0,
            },
            users.INSPECTOR,
        ),
        e.ERR_OPERATOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_well_transfer(
            well["id"], {"to_operator_id": ZERO_UUID}, users.ADMIN
        ),
        e.ERR_OPERATOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_bid(
            solicitation["id"],
            {
                "contractor_id": ZERO_UUID,
                "cement_per_sack_cents": 4137,
                "rig_day_rate_cents": 849999,
                "casing_per_ft_cents": 1213,
                "mobilization_fee_cents": 2499999,
                "technical_score": 92,
            },
            users.PROCUREMENT,
        ),
        e.ERR_CONTRACTOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_plugging_job(
            {
                "well_id": well["id"],
                "contract_id": ZERO_UUID,
                "scheduled_start": "2026-09-01T00:00:00Z",
                "planned_cement_sacks": 100,
                "planned_rig_days": 3,
                "planned_casing_ft": 500,
            },
            users.ADMIN,
        ),
        e.ERR_UNIT_COST_CONTRACT_NOT_FOUND,
        404,
    )

    assert_page(api.list_wells(users.ADMIN), 1, expected_total=1)
    assert_page(api.list_bids(users.PROCUREMENT), 0, expected_total=0)
    assert_page(api.list_plugging_jobs(users.ADMIN), 0, expected_total=0)
