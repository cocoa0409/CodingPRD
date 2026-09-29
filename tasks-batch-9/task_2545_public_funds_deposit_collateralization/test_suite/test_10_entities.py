"""Entity surface: creation echoes, declared defaults, computed fields, system fields, listing,
type constraints, parent resolution and the junction between assets and agreements."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assertions,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import (
    create_collateral_asset_payload,
    create_deposit_account_payload,
    create_depository_payload,
    create_pledge_agreement_payload,
    create_public_unit_payload,
    create_qualification_review_payload,
)
from test_helpers.fixtures import OFFICER, REGULATOR
from test_helpers.test_users import make_public_unit_treasurer_headers


def test_registering_a_custodian_echoes_every_declared_input(client):
    """A registration carrying all four inputs comes back with all four unchanged, unapproved,
    at version 1 and with a bare UUID identity.

    PRD: "Registering a **custodian** records the institution's `name` and its
    `custodian_type`, which is one of `FEDERAL_RESERVE`, `FHLB` or `TRUST_BANK`."
    PRD: "A freshly registered custodian's `approval_status` is `PENDING_APPROVAL` and its
    `approved_at` is null."
    PRD: "Every persisted resource carries a server-minted `id` that is a UUID string with no
    type prefix; clients never supply an `id`."
    PRD: "The `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."

    Design: Corner/entities/create_custodian_returns_all_declared_fields
    """
    fixtures.set_clock(client)

    response = client.create_custodian(
        {
            "name": "First Custody Bank",
            "custodian_type": "TRUST_BANK",
            "tri_party_capable": True,
            "concentration_limit_bps": 7500,
        },
        REGULATOR,
    )
    custodian = get_success_data(response, 201)

    assert response.json()["response_type"] == "object"
    assertions.assert_envelope_meta(response.json())
    assert custodian["name"] == "First Custody Bank"
    assert custodian["custodian_type"] == "TRUST_BANK"
    assert custodian["tri_party_capable"] is True
    assert custodian["concentration_limit_bps"] == 7500
    assert custodian["approval_status"] == "PENDING_APPROVAL"
    assert custodian["approved_at"] is None
    assert custodian["version"] == 1
    assertions.assert_custodian(custodian)


def test_reading_a_depository_returns_what_was_stored_plus_the_derived_tier(client):
    """A read of a thinly capitalised candidate bank reports its stored inputs, the tier derived
    from 850 basis points, every declared zero default, and a version still at 1.

    PRD: "From the capital ratio the service derives `capital_tier` immediately, with inclusive
    lower bounds: a ratio of at least 1000 basis points is `WELL_CAPITALIZED`, a ratio below that
    but at least 800 basis points is `ADEQUATELY_CAPITALIZED`, and anything below 800 basis
    points is `UNDERCAPITALIZED`."
    PRD: "A new depository starts at `approval_status` `DRAFT`, `collateral_posture`
    `COMPLIANT`, `risk_grade` `A` with `risk_score_bps` zero, `consecutive_deficiency_runs` zero,
    `open_margin_call_count` zero, `approved_pledge_capacity_cents` zero, a null `approved_at`,
    `mtm_run_index` zero, a null `last_mtm_window_end`, and `total_required_collateral_cents`,
    `total_pledged_collateral_value_cents` and `total_pledged_par_cents` all zero."
    PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation using the
    same format, and `version`, an integer that starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource."

    Design: Corner/entities/get_depository_returns_stored_data
    """
    fixtures.set_clock(client)
    created = fixtures.create_draft_depository(
        client,
        name="Thin Capital Bank",
        charter_type="NATIONAL",
        home_state="MI",
        capital_ratio_bps=850,
        insurance_determination_basis="PER_ACCOUNT",
    )

    depository = get_success_data(client.get_depository(created["id"], REGULATOR), 200)
    assert depository["name"] == "Thin Capital Bank"
    assert depository["charter_type"] == "NATIONAL"
    assert depository["home_state"] == "MI"
    assert depository["capital_ratio_bps"] == 850
    assert depository["insurance_determination_basis"] == "PER_ACCOUNT"
    assert depository["capital_tier"] == "ADEQUATELY_CAPITALIZED"
    assert depository["approval_status"] == "DRAFT"
    assert depository["approved_pledge_capacity_cents"] == 0
    assert depository["consecutive_deficiency_runs"] == 0
    assert depository["mtm_run_index"] == 0
    assert depository["last_mtm_window_end"] is None
    assert depository["collateral_posture"] == "COMPLIANT"
    assert depository["risk_grade"] == "A"
    assert depository["risk_score_bps"] == 0
    assert depository["version"] == 1
    assertions.assert_depository(depository)


def test_accounts_page_and_filter_conjunctively(client):
    """Two accounts of one unit at one bank page one at a time with a truthful total, a bank
    with no accounts answers an empty page rather than a 404, and an enum filter narrows to the
    single matching row.

    PRD: "The `meta` object of a list response carries `limit` (the effective page size),
    `offset` (the effective starting position), `total_count` (the number of records matching the
    filters before pagination is applied) and `has_more` (true when `offset` plus the number of
    returned records is strictly less than `total_count`)."
    PRD: "Unless a specific endpoint says otherwise, every collection is sorted by `created_at`
    ascending, and filters supplied as query parameters are combined conjunctively — a record
    must match all supplied filters to appear."
    PRD: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not
    be larger than 100."

    Design: Corner/entities/list_deposit_accounts_with_filter_and_pagination
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    bank = fixtures.create_approved_depository(client)
    empty_bank = fixtures.create_draft_depository(client, name="Empty Bank")

    first = fixtures.create_deposit_account(
        client, bank["id"], public_unit["id"], deposit_class="DEMAND"
    )
    second = fixtures.create_deposit_account(
        client, bank["id"], public_unit["id"], deposit_class="TIME_AND_SAVINGS"
    )

    page_one, meta_one = validate_paginated(
        client.list_deposit_accounts(
            REGULATOR, {"depository_id": bank["id"], "limit": 1, "offset": 0}
        )
    )
    assert [row["id"] for row in page_one] == [first["id"]]
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        client.list_deposit_accounts(
            REGULATOR, {"depository_id": bank["id"], "limit": 1, "offset": 1}
        )
    )
    assert [row["id"] for row in page_two] == [second["id"]]
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False

    empty, empty_meta = validate_paginated(
        client.list_deposit_accounts(REGULATOR, {"depository_id": empty_bank["id"]})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    narrowed, narrowed_meta = validate_paginated(
        client.list_deposit_accounts(
            REGULATOR,
            {"depository_id": bank["id"], "deposit_class": "TIME_AND_SAVINGS"},
        )
    )
    assert narrowed_meta["total_count"] == 1
    assert narrowed[0]["id"] == second["id"]
    assert narrowed[0]["deposit_class"] == "TIME_AND_SAVINGS"

    defaulted, default_meta = validate_paginated(
        client.list_deposit_accounts(REGULATOR, {"depository_id": bank["id"]})
    )
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert len(defaulted) == 2


def test_a_well_formed_but_unknown_agreement_id_is_a_not_found(client):
    """Reading an agreement that does not exist answers the error envelope with
    ERR_RESOURCE_NOT_FOUND rather than a 200 carrying nothing.

    PRD: "**Existence** — every identifier in the URL path is resolved left to right, then every
    foreign key in the request body is resolved; the first unresolved identifier yields
    `ERR_RESOURCE_NOT_FOUND`."
    PRD: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    Design: Corner/entities/get_unknown_pledge_agreement_returns_not_found
    """
    fixtures.set_clock(client)

    response = client.get_pledge_agreement(NON_EXISTENT_UUID, REGULATOR)
    error = validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    assert response.json()["response_type"] == "error"
    assert set(error.keys()) == {"error_id", "message"}
    assert error["message"].strip() != ""


def test_registering_an_asset_without_a_par_value_is_a_bad_request(client):
    """par_value_cents has no default, so an otherwise perfect registration that omits it is
    rejected on shape and leaves the bank's inventory empty.

    PRD: "**Request shape** — all required input fields present, every enum value inside its
    declared set, every integer amount strictly positive except `reported_par_cents` and
    `reported_asset_count` which may be zero, every timestamp a well-formed ISO 8601 UTC instant,
    and `projected_windows` non-empty; otherwise `ERR_INVALID_REQUEST`."
    PRD: "A `BankCollateralOfficer` registers each security the bank intends to pledge as a
    **collateral asset**, supplying the `depository_id` of the owning bank, the `custodian_id` of
    the institution holding it in safekeeping, its `cusip` security identifier, its `asset_type`,
    and its `par_value_cents`, which must be strictly positive."

    Design: Corner/entities/create_collateral_asset_missing_required_par_value_returns_invalid_request
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    depository = fixtures.create_approved_depository(client)

    response = client.create_collateral_asset(
        {
            "depository_id": depository["id"],
            "custodian_id": custodian["id"],
            "cusip": "912828LL1",
            "asset_type": "US_TREASURY",
        },
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _assets, meta = validate_paginated(
        client.list_collateral_assets(OFFICER, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 0


def test_a_custodian_registered_bare_takes_the_declared_defaults(client):
    """Omitting both optional inputs stores tri_party_capable false and a 6000-basis-point
    concentration limit, and a read back proves they were persisted rather than merely echoed.

    PRD: "`tri_party_capable` states whether the institution can hold collateral under a
    tri-party pledge arrangement and defaults to `false` when omitted, which means a newly
    registered custodian is presumed *not* tri-party capable until someone says otherwise."
    PRD: "`concentration_limit_bps` caps the share of any one depository's total pledged
    collateral value that this custodian may hold; it defaults to 6000 basis points — sixty
    percent — and a supplied value must be at least 1000 and at most 10000 basis points."

    Design: Corner/entities/create_custodian_omitting_optionals_applies_declared_defaults
    """
    fixtures.set_clock(client)

    created = get_success_data(
        client.create_custodian(
            {"name": "Minimal Custody", "custodian_type": "FHLB"}, REGULATOR
        ),
        201,
    )
    assert created["tri_party_capable"] is False
    assert created["concentration_limit_bps"] == 6000
    assert created["custodian_type"] == "FHLB"
    assert created["approval_status"] == "PENDING_APPROVAL"

    stored = get_success_data(client.get_custodian(created["id"], REGULATOR), 200)
    assert stored["tri_party_capable"] is False
    assert stored["concentration_limit_bps"] == 6000


def test_an_asset_computes_its_own_haircut_and_both_value_mirrors(client):
    """A general obligation bond priced at 9800 basis points carries the 1000-basis-point
    municipal haircut, a market value of 4,900,000 cents and a haircut value of 4,410,000, all
    computed by the service, with nothing pledged yet.

    PRD: "`haircut_bps` is derived at registration from the asset type and is never supplied by a
    client: a `US_TREASURY` carries 200 basis points, an `AGENCY_DEBENTURE` 300, an `AGENCY_MBS`
    800, a `MUNI_GO` 1000, a `MUNI_REVENUE` 1500, and a `LETTER_OF_CREDIT` none at all."
    PRD: "For the asset as a whole, `market_value_cents` is `par_value_cents` multiplied by
    `market_price_bps`, divided by 10000, rounded half up to whole cents; then
    `collateral_value_cents` is that market value multiplied by the quantity 10000 minus
    `haircut_bps`, divided by 10000, again rounded half up to whole cents."
    PRD: "A newly registered asset has `priced_at` stamped from the logical clock,
    `pledged_par_cents` at zero, `available_par_cents` equal to its full `par_value_cents`,
    `eligibility_status` `ELIGIBLE`, `pledge_status` `UNPLEDGED` and `ineligible_reason` null,
    with its two value mirrors computed as described below."

    Design: Corner/entities/collateral_asset_computed_haircut_market_and_collateral_values
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    depository = fixtures.create_approved_depository(client)

    asset = get_success_data(
        client.create_collateral_asset(
            create_collateral_asset_payload(
                depository["id"],
                custodian["id"],
                cusip="64966MGO1",
                asset_type="MUNI_GO",
                par_value_cents=5_000_000,
                market_price_bps=9800,
            ),
            OFFICER,
        ),
        201,
    )
    assert asset["haircut_bps"] == 1000
    assert asset["market_value_cents"] == 4_900_000
    assert asset["collateral_value_cents"] == 4_410_000
    assert asset["pledged_par_cents"] == 0
    assert asset["available_par_cents"] == 5_000_000
    assert asset["pledge_status"] == "UNPLEDGED"
    assert asset["eligibility_status"] == "ELIGIBLE"
    assert asset["ineligible_reason"] is None
    assert asset["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assertions.assert_haircut_matches_asset_type(asset)

    depository = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert depository["total_pledged_par_cents"] == 0


def test_the_insurance_group_sequence_restarts_for_a_different_deposit_class(client):
    """Two demand accounts of one county at one bank are sequenced 1 then 2, while the same
    county's time-and-savings account starts a fresh group at 1; all three open empty.

    PRD: "At creation the service assigns `group_sequence`, a monotone integer beginning at 1
    within the account's **insurance group**, which is the triple of `public_unit_id`,
    `depository_id` and `deposit_class`."
    PRD: "This sequence — never the account's `id` — pins the deterministic order in which
    insurance coverage is consumed, so the second `DEMAND` account a county opens at a given bank
    always sits behind the first."
    PRD: "A new unit begins with `total_deposit_balance_cents` and `total_uninsured_cents` at
    zero and `exposure_status` `NORMAL`."

    Design: Corner/entities/deposit_account_system_fields_group_sequence_and_zero_balances
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client)

    first = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"], deposit_class="DEMAND"
    )
    second = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"], deposit_class="DEMAND"
    )
    third = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"], deposit_class="TIME_AND_SAVINGS"
    )

    assert first["group_sequence"] == 1
    assert second["group_sequence"] == 2
    assert third["group_sequence"] == 1

    for account in (first, second, third):
        assert account["ledger_balance_cents"] == 0
        assert account["insured_amount_cents"] == 0
        assert account["uninsured_amount_cents"] == 0
        assert account["required_collateral_cents"] == 0
        assert account["coverage_ratio_bps"] == 10000
        assert account["collateral_status"] == "UNSECURED"
        assert account["funding_status"] == "PENDING_FUNDING"
        assert account["version"] == 1
        assertions.assert_deposit_account(account)

    _accounts, meta = validate_paginated(
        client.list_deposit_accounts(REGULATOR, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 3

    unit = get_success_data(client.get_public_unit(public_unit["id"], REGULATOR), 200)
    assert unit["total_deposit_balance_cents"] == 0
    assert unit["exposure_status"] == "NORMAL"


def test_undeclared_enum_values_and_a_negative_ratio_are_all_bad_requests(client):
    """A checking account, a township and a negative capital ratio are each outside the declared
    sets and ranges, so all three are refused on shape and none of them persists a row.

    PRD: "A `PublicUnitTreasurer` opens a **deposit account** by naming the `depository_id` of
    the bank, the `public_unit_id` of its own unit — which must equal its `X-User-ID` — the
    `deposit_class`, which is `DEMAND` or `TIME_AND_SAVINGS`, and the `pledging_mode`, which is
    `DEDICATED` or `POOLED`."
    PRD: "Registering one records its `name`, its `unit_type` — one of `SCHOOL_DISTRICT`,
    `COUNTY`, `MUNICIPALITY` or `STATE_AGENCY` — the two-letter `jurisdiction_state` code of the
    public-funds statute that governs it, and its `statutory_max_deposit_cents`, a strictly
    positive ceiling on the unit's aggregate ledger balance across every account it holds
    anywhere."
    PRD: "Registration supplies the bank's legal `name`, its `charter_type` (`STATE_CHARTERED` or
    `NATIONAL`) and the two-letter `home_state` code of its charter, and may optionally supply
    `capital_ratio_bps` (its total risk-based capital ratio in basis points, defaulting to 1200
    and constrained to the inclusive range 0 to 5000), `insurance_determination_basis`
    (`AGGREGATED_BY_UNIT` or `PER_ACCOUNT`, defaulting to `AGGREGATED_BY_UNIT`) and
    `pooled_program_id`, the pooled program the bank belongs to."

    Design: Corner/entities/create_deposit_account_invalid_enum_deposit_class_returns_invalid_request
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client)

    bad_class = client.create_deposit_account(
        create_deposit_account_payload(
            depository["id"], public_unit["id"], deposit_class="CHECKING"
        ),
        make_public_unit_treasurer_headers(public_unit["id"]),
    )
    validate_error(bad_class, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bad_unit_type = client.create_public_unit(
        create_public_unit_payload(name="Ridge Township", unit_type="TOWNSHIP"), REGULATOR
    )
    validate_error(bad_unit_type, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    negative_ratio = client.create_depository(
        create_depository_payload(name="Negative Capital Bank", capital_ratio_bps=-1),
        OFFICER,
    )
    validate_error(negative_ratio, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _accounts, meta = validate_paginated(
        client.list_deposit_accounts(REGULATOR, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 0

    banks, banks_meta = validate_paginated(client.list_depositories(REGULATOR))
    assert banks_meta["total_count"] == 1
    assert banks[0]["id"] == depository["id"]


def test_a_valuation_run_is_written_once_and_never_versioned(client):
    """A completed run reads back with an identity and a creation stamp but no updated_at and no
    version, carrying the window it valued, its totals and the three risk components that scored
    the bank a D.

    PRD: "`MarkToMarketRun` records are the sole exception: a mark-to-market run is an immutable
    historical record, so it carries only `id` and `created_at` — it has no `updated_at` field and
    no `version` field, and nothing in the service ever updates a run after it is written."
    PRD: "A run record is immutable once written: it carries `id` and `created_at` but no
    `updated_at` and no `version`, and nothing in the service ever amends one."
    PRD: "The **volatility component**, `volatility_component_bps`, is 10000 less the lesser of
    10000 and the depository's `consecutive_deficiency_runs` multiplied by 2500 — and here the
    counter is the value **after** step six, not the snapshot."
    PRD: "`risk_score_bps` is the coverage figure multiplied by 0.50, plus the volatility figure
    multiplied by 0.30, plus the documentation figure multiplied by 0.20, with the sum rounded
    half up to whole basis points."

    Design: Corner/entities/mtm_run_immutable_entity_has_no_version_and_no_update_endpoint
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client)
    fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    created = fixtures.create_mtm_run(
        client, depository["id"], "2026-07-31T00:00:00Z", DEFAULT_CLOCK_UTC
    )

    run = get_success_data(client.get_mtm_run(created["id"], REGULATOR), 200)
    assertions.assert_identity_stamps(run)
    assert "version" not in run
    assert "updated_at" not in run
    assert run["run_index"] == 1
    assert run["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert run["window_start"] == "2026-07-31T00:00:00Z"
    assert run["window_end"] == DEFAULT_CLOCK_UTC
    assert run["basis"] == "SUPERVISORY"
    assert run["total_required_collateral_cents"] == 78_750_000
    assert run["total_collateral_value_cents"] == 0
    assert run["deficiency_cents"] == 78_750_000
    assert run["deficiency_ratio_bps"] == 10000
    assert run["outcome"] == "DEFICIENT"
    assert run["coverage_component_bps"] == 0
    assert run["volatility_component_bps"] == 7500
    assert run["documentation_component_bps"] == 0
    assert run["risk_score_bps"] == 2250
    assert run["risk_grade_assigned"] == "D"
    assertions.assert_mtm_run(run)


def test_filing_a_package_under_an_unknown_bank_resolves_the_path_first(client):
    """A perfectly valid capacity request filed under a depository id that resolves to nothing is
    a 404, and the real bank's package list stays empty.

    PRD: "**Existence** — every identifier in the URL path is resolved left to right, then every
    foreign key in the request body is resolved; the first unresolved identifier yields
    `ERR_RESOURCE_NOT_FOUND`."
    PRD: "The filed review is `SUBMITTED`, its `depository_id` is taken from the path rather than
    the body, its `submitted_by_user_id` records the filing officer's `X-User-ID`, and its
    `round_count` is 1."

    Design: Corner/entities/create_qualification_review_under_unknown_depository_returns_not_found
    """
    fixtures.set_clock(client)
    real_bank = fixtures.create_draft_depository(client)

    response = client.create_qualification_review(
        NON_EXISTENT_UUID, create_qualification_review_payload(), OFFICER
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    _reviews, meta = validate_paginated(
        client.list_qualification_reviews(real_bank["id"], REGULATOR)
    )
    assert meta["total_count"] == 0


def test_an_unknown_custodian_foreign_key_stops_the_draft(client):
    """Drafting an agreement whose depository and beneficiary account both exist but whose
    custodian does not is a 404, and no agreement is left behind.

    PRD: "Body foreign keys are resolved in this declaration order: `depository_id`,
    `public_unit_id`, `custodian_id`, `pooled_program_id`, `deposit_account_id`,
    `pledge_agreement_id`, `collateral_asset_id`, `outgoing_allocation_id`, `incoming_asset_id`."
    PRD: "A `BankCollateralOfficer` drafts one by supplying the `depository_id` of its own bank,
    the `custodian_id` of the intended tri-party safekeeping agent, a `beneficiary_type` of either
    `DEPOSIT_ACCOUNT` or `POOLED_PROGRAM`, the bank's own document number as `agreement_number`,
    and the two-letter `governing_law_state` code named in the instrument."

    Design: Corner/entities/create_pledge_agreement_with_unknown_custodian_fk_returns_not_found
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"]
    )

    response = client.create_pledge_agreement(
        create_pledge_agreement_payload(
            depository["id"],
            NON_EXISTENT_UUID,
            beneficiary_type="DEPOSIT_ACCOUNT",
            deposit_account_id=account["id"],
            agreement_number="AG-0001",
        ),
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    _agreements, meta = validate_paginated(
        client.list_pledge_agreements(OFFICER, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 0


def test_one_asset_backs_two_agreements_without_either_seeing_the_other(client):
    """A 2,000,000-cent treasury split across two agreements of the same bank gives each of them
    980,000 of value and no more, fills the asset exactly, and is navigable from either side of
    the junction.

    PRD: "an agreement's `total_collateral_value_cents` is the sum of
    `allocated_collateral_value_cents` over its allocations that are `ACTIVE` and whose asset is
    `ELIGIBLE`; its `total_pledged_par_cents` is the sum of `allocated_par_cents` over all of its
    `ACTIVE` allocations, whether or not the underlying asset is still eligible; and its
    `active_allocation_count` is the number of its allocations in `ACTIVE` status."
    PRD: "A depository's `total_pledged_collateral_value_cents` is the sum of
    `total_collateral_value_cents` over its agreements in `EXECUTED` status."
    PRD: "Inventory is navigable from both directions: assets are listable by `depository_id`,
    `custodian_id`, `asset_type`, `eligibility_status` and `pledge_status`, and allocations by
    `pledge_agreement_id`, `collateral_asset_id`, `created_by_substitution_id` and `status`."

    Design: Corner/entities/allocation_junction_links_one_asset_to_two_agreements
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    second_account = fixtures.create_deposit_account(
        client,
        perimeter["depository_id"],
        perimeter["public_unit_id"],
        deposit_class="TIME_AND_SAVINGS",
    )
    second_agreement = fixtures.create_executed_dedicated_agreement(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        second_account["id"],
        perimeter["public_unit_id"],
    )
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=2_000_000,
        market_price_bps=10000,
    )

    first_leg = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 1_000_000
    )
    second_leg = fixtures.create_allocation(
        client, second_agreement["id"], asset["id"], 1_000_000
    )
    assert first_leg["allocated_collateral_value_cents"] == 980_000
    assert second_leg["allocated_collateral_value_cents"] == 980_000

    for agreement_id in (perimeter["agreement_id"], second_agreement["id"]):
        agreement = get_success_data(client.get_pledge_agreement(agreement_id, OFFICER), 200)
        assert agreement["total_collateral_value_cents"] == 980_000
        assert agreement["active_allocation_count"] == 1
        _rows, meta = validate_paginated(
            client.list_pledge_allocations(OFFICER, {"pledge_agreement_id": agreement_id})
        )
        assert meta["total_count"] == 1

    stored_asset = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert stored_asset["pledged_par_cents"] == 2_000_000
    assert stored_asset["available_par_cents"] == 0
    assert stored_asset["pledge_status"] == "FULLY_PLEDGED"

    _all_legs, legs_meta = validate_paginated(
        client.list_pledge_allocations(OFFICER, {"collateral_asset_id": asset["id"]})
    )
    assert legs_meta["total_count"] == 2

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 1_960_000
    assert depository["total_pledged_par_cents"] == 2_000_000
