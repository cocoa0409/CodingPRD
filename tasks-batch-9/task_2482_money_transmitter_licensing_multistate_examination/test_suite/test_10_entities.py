"""Entity-level PRD compliance: creation, defaults, identity and referential shape.

Every test drives a live server through the endpoints of PRD section 4 only. The
runner restarts the process before each test, so the database is empty and the
logical clock sits at its process-start instant of 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CONTROL_CHAIN_CYCLE,
    ERR_CROSS_LICENSEE_REFERENCE,
    ERR_DUPLICATE_EIN,
    ERR_DUPLICATE_STATE_CODE,
    ERR_INVALID_REQUEST,
    ERR_LICENSEE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_audit_stamps,
    assert_immutable_config_row,
)
from test_helpers.test_users import ADMIN_HEADERS, MANAGER_HEADERS, OFFICER_HEADERS


# ---------------------------------------------------------------------------
# Jurisdiction reference configuration
# ---------------------------------------------------------------------------


def test_create_jurisdiction_persists_every_declared_reference_value(
    api: MoneyTransmitterApiClient,
) -> None:
    """POST /jurisdictions returns 201 and echoes all eleven posted reference values.

    PRD 4: "Operations that create a new resource return `201 Created`."
    PRD 3.1: "Each `Jurisdiction` row is posted with a two-letter `state_code` in uppercase — exactly two characters, and unique across all jurisdictions, with a second row for the same code rejected as `ERR_DUPLICATE_STATE_CODE` — together with the regulator's display `name` and the statutory parameters that drive every downstream computation for that state: `min_net_worth_cents`, the minimum tangible net worth a licensee must report to hold a licence there; `base_bond_cents`, the statutory floor of the surety bond; `per_delegate_bond_cents`, the incremental bond amount charged for each active authorized delegate; `bond_cap_cents`, the statutory ceiling, which may never be below `base_bond_cents`; `response_window_days`, at least one, the number of days a licensee gets to answer an information request from that state; `renewal_fee_cents`, the base annual renewal fee for one licence; and `assessment_rate_bps`, the annual assessment rate in basis points applied to outstanding obligations."
    PRD 3.1: "Two further fields shape process rather than arithmetic: `participates_in_multistate`, a boolean defaulting to true that says whether the state may join a coordinated examination, and `call_report_frequency`, which is either `QUARTERLY` or `ANNUAL` and fixes the shape of the reporting calendar for every licence issued there."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/create_jurisdiction_persists_reference_config
    """
    response = api.create_jurisdiction(F.jurisdiction_payload(), ADMIN_HEADERS)
    data = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert data["state_code"] == "CA"
    assert data["name"] == "California DFPI"
    assert data["min_net_worth_cents"] == 50_000_000
    assert data["base_bond_cents"] == 5_000_000
    assert data["per_delegate_bond_cents"] == 100_000
    assert data["bond_cap_cents"] == 40_000_000
    assert data["response_window_days"] == 15
    assert data["renewal_fee_cents"] == 500_000
    assert data["assessment_rate_bps"] == 25
    assert data["call_report_frequency"] == "QUARTERLY"
    assert data["participates_in_multistate"] is True


def test_jurisdiction_omitted_participation_flag_defaults_to_true(
    api: MoneyTransmitterApiClient,
) -> None:
    """Omitting participates_in_multistate stores true, not false and not null.

    PRD 3.1: "Two further fields shape process rather than arithmetic: `participates_in_multistate`, a boolean defaulting to true that says whether the state may join a coordinated examination, and `call_report_frequency`, which is either `QUARTERLY` or `ANNUAL` and fixes the shape of the reporting calendar for every licence issued there."
    PRD 4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/jurisdiction_omitted_participation_flag_defaults_to_true
    """
    payload = F.jurisdiction_payload(
        **{**C.NV_CONFIG, "participates_in_multistate": ...}
    )
    assert "participates_in_multistate" not in payload

    data = validate_success(api.create_jurisdiction(payload, ADMIN_HEADERS), 201)

    assert data["state_code"] == "NV"
    assert data["participates_in_multistate"] is True
    assert data["call_report_frequency"] == "ANNUAL"


def test_jurisdiction_row_carries_no_version_or_updated_at(
    api: MoneyTransmitterApiClient,
) -> None:
    """A jurisdiction configuration row exposes only id and created_at.

    PRD 2.4: "Every resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at`, which is an ISO 8601 UTC timestamp with three fractional digits."
    PRD 2.4: "`Jurisdiction` is the single exception: a jurisdiction configuration row is immutable once posted, so it carries only `id` and `created_at` — it has no `updated_at`, no `version`, and no update endpoint."

    Design: Corner/entities/jurisdiction_response_carries_no_version_or_updated_at
    """
    data = validate_success(
        api.create_jurisdiction(F.jurisdiction_payload(**C.TX_CONFIG), ADMIN_HEADERS), 201
    )

    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert "updated_at" not in data
    assert "version" not in data
    assert_immutable_config_row(data)


def test_second_jurisdiction_with_same_state_code_rejects(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict
) -> None:
    """A second CA row is refused and the first configuration keeps driving the estate.

    PRD 3.1: "Each `Jurisdiction` row is posted with a two-letter `state_code` in uppercase — exactly two characters, and unique across all jurisdictions, with a second row for the same code rejected as `ERR_DUPLICATE_STATE_CODE` — together with the regulator's display `name` and the statutory parameters that drive every downstream computation for that state: `min_net_worth_cents`, the minimum tangible net worth a licensee must report to hold a licence there; `base_bond_cents`, the statutory floor of the surety bond; `per_delegate_bond_cents`, the incremental bond amount charged for each active authorized delegate; `bond_cap_cents`, the statutory ceiling, which may never be below `base_bond_cents`; `response_window_days`, at least one, the number of days a licensee gets to answer an information request from that state; `renewal_fee_cents`, the base annual renewal fee for one licence; and `assessment_rate_bps`, the annual assessment rate in basis points applied to outstanding obligations."
    PRD 2.4: "Every downstream calculation reads the jurisdiction configuration exactly as it was posted."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."

    Design: Corner/entities/second_jurisdiction_with_same_state_code_rejects
    """
    duplicate = F.jurisdiction_payload(
        name="California DFPI (duplicate)", min_net_worth_cents=60_000_000
    )
    validate_error(
        api.create_jurisdiction(duplicate, ADMIN_HEADERS), ERR_DUPLICATE_STATE_CODE, 409
    )

    # The surviving CA row still pins min_net_worth_cents 50_000_000, not the
    # rejected row's 60_000_000.
    licensee = fx.create_licensee(api)
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    submitted = fx.submit_application(api, application["id"])
    assert submitted["required_net_worth_cents"] == 50_000_000


# ---------------------------------------------------------------------------
# Licensee of record
# ---------------------------------------------------------------------------


def test_new_licensee_starts_with_vacuous_coverage_defaults(
    api: MoneyTransmitterApiClient,
) -> None:
    """A licensee registered with only legal_name and ein reads the vacuous defaults.

    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."
    PRD 3.1: "The financial position may be supplied at registration or later: `reported_tangible_net_worth_cents`, which defaults to zero and, unlike every other money field in the system, is explicitly permitted to be negative, and `net_worth_statement_date`, the as-of date of that figure."
    PRD 3.1: "A freshly created licensee starts with `version` at 1, `coverage_posture` at `COMPLIANT`, `coverage_ratio_bps` at 10000 — vacuously perfect, since there are no obligations yet — `control_chain_status` at `VERIFIED`, and every counter at zero: `aggregate_outstanding_obligations_cents`, `eligible_investment_value_cents`, `book_investment_value_cents`, `consecutive_failed_test_count` and `active_license_count`."

    Design: Corner/entities/new_licensee_starts_with_vacuous_coverage_defaults
    """
    payload = F.licensee_payload(
        reported_tangible_net_worth_cents=..., net_worth_statement_date=...
    )
    assert set(payload) == {"legal_name", "ein"}

    data = validate_success(api.create_licensee(payload, MANAGER_HEADERS), 201)

    assert_audit_stamps(data)
    assert data["version"] == 1
    assert data["reported_tangible_net_worth_cents"] == 0
    assert data["aggregate_outstanding_obligations_cents"] == 0
    assert data["eligible_investment_value_cents"] == 0
    assert data["book_investment_value_cents"] == 0
    assert data["coverage_ratio_bps"] == 10_000
    assert data["coverage_posture"] == "COMPLIANT"
    assert data["consecutive_failed_test_count"] == 0
    assert data["control_chain_status"] == "VERIFIED"
    assert data["active_license_count"] == 0


def test_licensee_without_ein_rejects_with_invalid_request(
    api: MoneyTransmitterApiClient,
) -> None:
    """A registration missing the required ein is a malformed request, not a 409.

    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."
    PRD 2.7: "**Request shape** — required fields present, enum values inside their declared sets, money and count fields integers no less than zero, ISO 8601 datetimes well formed, `limit` within 1 through 100 and `offset` no less than zero: `ERR_INVALID_REQUEST`."

    Design: Corner/entities/licensee_without_ein_rejects_with_invalid_request
    """
    payload = F.licensee_payload(ein=...)
    assert "ein" not in payload

    error = validate_error(
        api.create_licensee(payload, MANAGER_HEADERS), ERR_INVALID_REQUEST, 400
    )
    assert error["message"].strip()


def test_second_licensee_with_same_ein_rejects_with_duplicate_ein(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A second registration under an EIN already on file is refused as a duplicate.

    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."

    Design: Corner/entities/second_licensee_with_same_ein_rejects_with_duplicate_ein
    """
    validate_error(
        api.create_licensee(
            F.licensee_payload(legal_name="Meridian Payments Inc"), MANAGER_HEADERS
        ),
        ERR_DUPLICATE_EIN,
        409,
    )

    survivor = fx.get_licensee(api, licensee["id"])
    assert survivor["legal_name"] == C.SEED_LICENSEE_NAME
    assert survivor["ein"] == C.SEED_LICENSEE_EIN


def test_unknown_licensee_id_returns_licensee_not_found(
    api: MoneyTransmitterApiClient,
) -> None:
    """A well-formed but unknown licensee UUID resolves to a 404, not a 400 or an empty 200.

    PRD 2.7: "**Reference resolution**, left to right along the path and then through the body, in this exact sequence: licensee references (`ERR_LICENSEE_NOT_FOUND`), then jurisdiction references (`ERR_JURISDICTION_NOT_FOUND`), then control-person references including `parent_control_person_id` (`ERR_CONTROL_PERSON_NOT_FOUND`), then application references (`ERR_APPLICATION_NOT_FOUND`), then state-licence references whether in the path or in a body field (`ERR_LICENSE_NOT_FOUND`), then delegate references (`ERR_DELEGATE_NOT_FOUND`), then delegate-authorization references (`ERR_AUTHORIZATION_NOT_FOUND`), then investment-holding references (`ERR_HOLDING_NOT_FOUND`), then coverage-test references (`ERR_TEST_NOT_FOUND`), then examination references including `exam_id` and `originating_exam_id` (`ERR_EXAM_NOT_FOUND`), then information-request references (`ERR_INFO_REQUEST_NOT_FOUND`), then enforcement-action references (`ERR_ENFORCEMENT_NOT_FOUND`)."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/unknown_licensee_id_returns_not_found
    """
    response = api.get_licensee(NON_EXISTENT_UUID, MANAGER_HEADERS)

    error = validate_error(response, ERR_LICENSEE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip()


# ---------------------------------------------------------------------------
# Investment holdings
# ---------------------------------------------------------------------------


def test_new_investment_holding_is_server_marked_held(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A recorded holding starts HELD with age_days defaulted to zero.

    PRD 3.7: "A `ComplianceOfficer` or `ChiefComplianceOfficer` records each asset as an `InvestmentHolding` under a `licensee_id`, with an `asset_class` drawn from `CASH`, `US_TREASURY`, `AGENCY_BOND`, `MONEY_MARKET_FUND`, `RECEIVABLE_FROM_DELEGATE` and `CORPORATE_DEBT`; a `counterparty_name` naming the obligor or custodian, which is the grouping key for the concentration cap; a `book_value_cents` and a `market_value_cents`, both zero or greater; and, for a receivable, an `age_days` in days, defaulting to zero and ignored entirely for every non-receivable class."
    PRD 3.7: "The row starts with `status` `HELD`; disposing of it moves it to `DISPOSED`, and only `HELD` rows enter any coverage computation."
    PRD 4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/new_investment_holding_is_server_marked_held
    """
    payload = F.investment_holding_payload(
        licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )
    assert "age_days" not in payload

    data = validate_success(api.create_investment_holding(payload, OFFICER_HEADERS), 201)

    assert_audit_stamps(data)
    assert data["licensee_id"] == licensee["id"]
    assert data["asset_class"] == "CASH"
    assert data["counterparty_name"] == "First Republic Trust"
    assert data["status"] == "HELD"
    assert data["age_days"] == 0


def test_recording_a_holding_recomputes_both_licensee_investment_values(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A single 4,000,000-cent CASH holding lifts both variants and bumps the version.

    PRD 3.7: "Both recording a holding and disposing of one recompute the licensee's coverage figures and posture and bump `Licensee.version`."
    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "Holdings in the uncapped classes — `CASH` and `US_TREASURY` — accumulate into a single uncapped total."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."

    Design: Corner/entities/new_investment_holding_is_server_marked_held
    """
    assert licensee["version"] == 1

    fx.record_holding(
        api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )

    after = fx.get_licensee(api, licensee["id"])
    # CASH carries no haircut and sits in the uncapped bucket: 4_000_000 both ways.
    assert after["book_investment_value_cents"] == 4_000_000
    assert after["eligible_investment_value_cents"] == 4_000_000
    # Obligations are zero, so the ratio is the vacuous 10000.
    assert after["aggregate_outstanding_obligations_cents"] == 0
    assert after["coverage_ratio_bps"] == 10_000
    assert after["coverage_posture"] == "COMPLIANT"
    # 1 -> 2: recording a holding bumps Licensee.version.
    assert after["version"] == 2


def test_investment_holding_with_negative_book_value_rejects(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A negative book_value_cents is a malformed request and stores nothing.

    PRD 3.7: "A `ComplianceOfficer` or `ChiefComplianceOfficer` records each asset as an `InvestmentHolding` under a `licensee_id`, with an `asset_class` drawn from `CASH`, `US_TREASURY`, `AGENCY_BOND`, `MONEY_MARKET_FUND`, `RECEIVABLE_FROM_DELEGATE` and `CORPORATE_DEBT`; a `counterparty_name` naming the obligor or custodian, which is the grouping key for the concentration cap; a `book_value_cents` and a `market_value_cents`, both zero or greater; and, for a receivable, an `age_days` in days, defaulting to zero and ignored entirely for every non-receivable class."
    PRD 2.7: "**Request shape** — required fields present, enum values inside their declared sets, money and count fields integers no less than zero, ISO 8601 datetimes well formed, `limit` within 1 through 100 and `offset` no less than zero: `ERR_INVALID_REQUEST`."

    Design: Corner/entities/investment_holding_with_negative_book_value_rejects
    """
    validate_error(
        api.create_investment_holding(
            F.investment_holding_payload(
                licensee["id"], "CASH", "First Republic Trust", -1, 4_000_000
            ),
            OFFICER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_licensee_investment_holdings(licensee["id"], OFFICER_HEADERS)
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = fx.get_licensee(api, licensee["id"])
    assert after["book_investment_value_cents"] == 0
    assert after["eligible_investment_value_cents"] == 0


def test_investment_holdings_list_paginates_with_total_count_and_has_more(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Three holdings paginate two-then-one with the pagination meta of the envelope.

    PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100."
    PRD 2.3: "`offset` is the number of rows to skip; it defaults to 0 and its minimum is 0."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope."
    PRD 2.3: "A licensee's holdings listing filters on `status` and `asset_class`."

    Design: Corner/entities/investment_holdings_list_paginates_with_total_count_and_has_more
    """
    holdings = fx.record_holdings(
        api,
        licensee["id"],
        [
            {
                "asset_class": "CASH",
                "counterparty_name": "First Republic Trust",
                "book_value_cents": 1_000_000,
                "market_value_cents": 1_000_000,
            },
            {
                "asset_class": "US_TREASURY",
                "counterparty_name": "US Treasury",
                "book_value_cents": 2_000_000,
                "market_value_cents": 2_000_000,
            },
            {
                "asset_class": "MONEY_MARKET_FUND",
                "counterparty_name": "Vantage MMF",
                "book_value_cents": 3_000_000,
                "market_value_cents": 3_000_000,
            },
        ],
    )
    expected_ids = {holding["id"] for holding in holdings}

    first_response = api.list_licensee_investment_holdings(
        licensee["id"], OFFICER_HEADERS, params={"limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    # 0 + 2 < 3, so a third row is still waiting.
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_licensee_investment_holdings(
            licensee["id"], OFFICER_HEADERS, params={"limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    # 2 + 1 == 3, so the page exhausts the collection.
    assert second_meta["has_more"] is False

    paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(paged_ids) == 3
    assert set(paged_ids) == expected_ids


# ---------------------------------------------------------------------------
# Control chain structure
# ---------------------------------------------------------------------------


def test_control_person_parent_from_another_licensee_rejects(
    api: MoneyTransmitterApiClient,
) -> None:
    """A parent pointer into another licensee's roster is a cross-licensee reference.

    PRD 3.2: "A parent holder belonging to a different licensee than the row being created is rejected with `ERR_CROSS_LICENSEE_REFERENCE` (HTTP 422)."
    PRD 3.2: "Above the individual holders sits the licensee's `control_chain_status`, an aggregate over the non-`REMOVED` holders whose `control_determination` is `CONTROL`, with values `VERIFIED`, `PENDING_CHECKS` and `BLOCKED` and a default of `VERIFIED`."

    Design: Corner/entities/control_person_parent_from_another_licensee_rejects
    """
    licensee_a = fx.create_licensee(api)
    licensee_b = fx.create_licensee(
        api, legal_name="Halcyon Remit Corp", ein="741100002"
    )
    holder_a = fx.create_control_person(
        api,
        licensee_a["id"],
        full_name="Northgate HoldCo",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=6000,
    )

    validate_error(
        api.create_control_person(
            F.control_person_payload(
                licensee_b["id"],
                full_name="Priya Raman",
                role_title="ENTITY_HOLDER",
                direct_ownership_bps=4000,
                parent_control_person_id=holder_a["id"],
            ),
            MANAGER_HEADERS,
        ),
        ERR_CROSS_LICENSEE_REFERENCE,
        422,
    )

    rows, meta = validate_paginated(
        api.list_control_persons(MANAGER_HEADERS, params={"licensee_id": licensee_b["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fx.get_licensee(api, licensee_b["id"])["control_chain_status"] == "VERIFIED"


def test_control_person_chain_deeper_than_five_links_rejects(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A five-row parent chain is accepted and the sixth link is refused as a cycle.

    PRD 3.2: "The chain must be sane: a parent pointer that names the row itself, that reaches back into the row's own descendants, or that would make the chain more than five links deep is rejected with `ERR_CONTROL_CHAIN_CYCLE` (HTTP 422)."
    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."

    Design: Corner/entities/control_person_chain_deeper_than_five_links_rejects
    """
    parent_id = None
    chain = []
    for tier in range(1, 6):
        row = fx.create_control_person(
            api,
            licensee["id"],
            full_name=f"Tier {tier} HoldCo",
            role_title="ENTITY_HOLDER",
            direct_ownership_bps=10_000,
            **({} if parent_id is None else {"parent_control_person_id": parent_id}),
        )
        chain.append(row)
        parent_id = row["id"]

    deepest = chain[-1]
    # Every hop is 10000 * 10000 / 10000 = 10000, and every parent's direct stake
    # of 10000 bps is above the 2500 bps control threshold, so nothing dilutes.
    assert deepest["effective_ownership_bps"] == 10_000
    assert deepest["attributed_ownership_bps"] == 10_000

    validate_error(
        api.create_control_person(
            F.control_person_payload(
                licensee["id"],
                full_name="Tier 6 HoldCo",
                role_title="ENTITY_HOLDER",
                direct_ownership_bps=10_000,
                parent_control_person_id=deepest["id"],
            ),
            MANAGER_HEADERS,
        ),
        ERR_CONTROL_CHAIN_CYCLE,
        422,
    )

    rows, meta = validate_paginated(
        api.list_control_persons(MANAGER_HEADERS, params={"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 5
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# Delegate authorizations as the delegate x licence junction
# ---------------------------------------------------------------------------


def test_authorization_with_expiry_before_effective_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """An inverted authorization window is malformed and no row is created.

    PRD 3.6: "The appointment is made concrete per state by a `DelegateAuthorization`, which pairs a `delegate_id` with a `state_license_id` and defines a period and a limit: `effective_date` is the first day of the authorization period, `expiry_date` is the last day and may not precede the effective date, and `monthly_volume_cap_cents` is the contractual monthly transmission cap, which must be strictly greater than zero."
    PRD 2.7: "**Request shape** — required fields present, enum values inside their declared sets, money and count fields integers no less than zero, ISO 8601 datetimes well formed, `limit` within 1 through 100 and `offset` no less than zero: `ERR_INVALID_REQUEST`."
    PRD 3.6: "The row starts in `ONBOARDING`, the other statuses being `ACTIVE`, `SUSPENDED` and the terminal `TERMINATED`."
    PRD 3.6: "`authorized_state_count` starts at zero and `oversight_hold`, the flag that records that every one of the delegate's authorizations has been suspended by a posture or licence cascade, starts false."

    Design: Corner/entities/authorization_with_expiry_before_effective_rejects
    """
    delegate = fx.create_delegate(api, active_license.licensee_id)

    validate_error(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                active_license.license_id,
                "2026-10-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert after["status"] == "ONBOARDING"
    assert after["authorized_state_count"] == 0
    assert after["oversight_hold"] is False


def test_authorization_joining_delegate_and_license_of_two_licensees_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Both ends of the authorization edge must sit under one licensee.

    PRD 3.6: "The delegate and the licence must belong to the same licensee — a delegate authorized under another licensee's licence is rejected with `ERR_CROSS_LICENSEE_REFERENCE`."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."

    Design: Corner/entities/authorization_joining_delegate_and_license_of_two_licensees_rejects
    """
    other_licensee = fx.create_licensee(
        api, legal_name="Halcyon Remit Corp", ein="741100002"
    )
    foreign_delegate = fx.create_delegate(
        api, other_licensee["id"], legal_name="Foreign Agent LLC", delegate_type="AGENT"
    )

    validate_error(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                foreign_delegate["id"],
                active_license.license_id,
                "2026-09-01T00:00:00Z",
                "2027-08-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        ERR_CROSS_LICENSEE_REFERENCE,
        422,
    )

    rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"state_license_id": active_license.license_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    license_row = fx.get_license(api, active_license.license_id)
    assert license_row["active_delegate_count"] == 0
