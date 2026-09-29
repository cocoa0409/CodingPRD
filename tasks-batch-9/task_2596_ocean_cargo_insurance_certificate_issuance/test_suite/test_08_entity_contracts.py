"""
Entity contracts: created rows, declared defaults, reads, listings and the
validation gates that guard every write.

Covers what a create echoes back and what it stamps itself, which optional
inputs fall back to a declared default, how a single-resource read and a
paginated listing present their rows, which error identifier an absent
identifier produces per collection, and the schema and reference-resolution
gates that reject or ignore what a client sends.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CERTIFICATE_CIF_SHIPMENT,
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    ERR_ACCUMULATION_ENTRY_NOT_FOUND,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_COMMODITY_CLASS_NOT_FOUND,
    ERR_DECLARATION_NOT_FOUND,
    ERR_GA_EVENT_NOT_FOUND,
    ERR_GA_POSTING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_POLICY_NOT_FOUND,
    ERR_PORT_NOT_FOUND,
    ERR_SURVEY_ORDER_NOT_FOUND,
    ERR_VESSEL_NOT_FOUND,
    EXPECTED_INSURED_VALUE_CIF,
    OPEN_POLICY_CANONICAL,
    PREMIUM_AUDITOR,
    SURVEYOR_ROTTERDAM,
    UNDERWRITER,
    VESSEL_KITE,
    ApiClient,
    assert_append_only_fields,
    assert_common_fields,
    assert_fields_present,
    assert_money,
    assert_rate,
    assert_total_count,
    collect_ids,
    create_commodity_class,
    create_vessel,
    make_assured_headers,
    open_claim_file,
    read_policy,
    read_vessel,
    set_clock,
)

# The instant the evidence log is written at, once the clock has been moved.
EVIDENCE_CLOCK = "2026-09-10T00:00:00Z"

# A port declared with nothing but its mandatory particulars, so every optional
# input has to fall back to the value the cover terms declare for it.
PORT_MINIMAL = {
    "unlocode": "SGSIN",
    "name": "Singapore",
    "country_code": "SG",
    "port_accumulation_limit_amount": 8000000,
}

# An open cover declared without its transit clause, its profit uplift or its
# excess, for the same reason.
OPEN_POLICY_MINIMAL = {
    "policy_number": "OP-2596-D",
    "assured_name": "Default Traders",
    "inception_at": "2026-01-01T00:00:00Z",
    "expiry_at": "2027-01-01T00:00:00Z",
    "freight_basis": "PREPAID",
    "per_certificate_limit_amount": 2000000,
    "conveyance_limit_amount": 3000000,
    "annual_aggregate_limit_amount": 10000000,
    "premium_rate_per_mille": 3.500,
    "war_rate_per_mille": 0.600,
    "strikes_rate_per_mille": 0.255,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the fractional-second suffix."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"
    return datetime.strptime(value.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")


def _certificate_body(env: dict, **overrides: object) -> dict:
    """
    The canonical CIF shipment body wired to one environment's references, with
    whatever the caller wants changed.
    """
    body = dict(CERTIFICATE_CIF_SHIPMENT)
    body.update({
        "open_policy_id": env["policy_id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
    })
    body.update(overrides)
    return body


def _build_three_commodity_classes(api: ApiClient) -> dict:
    """
    Three commodity classes registered in a fixed order: S3 consumer
    electronics, S1 hot rolled coil and S4 chilled produce.
    """
    electronics = create_commodity_class(api)
    steel = create_commodity_class(
        api, code="CC-STEEL", description="Hot rolled coil",
        susceptibility_rating="S1", required_packaging_code="STD",
        rate_loading_pct=0.00, max_conveyance_share_pct=1.00,
        survey_required_above_amount=1000000)
    reefer = create_commodity_class(
        api, code="CC-REEFER", description="Chilled produce",
        susceptibility_rating="S4", required_packaging_code="REEFER_SEALED",
        rate_loading_pct=0.60, max_conveyance_share_pct=0.50,
        survey_required_above_amount=250000)
    return {"electronics": electronics, "steel": steel, "reefer": reefer}


# ---------------------------------------------------------------------------
# Writing an open cover
# ---------------------------------------------------------------------------
def test_open_policy_creation_echoes_the_submitted_terms(api: ApiClient) -> None:
    """
    A written open cover comes back carrying every term the underwriter submitted.

    Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.

    Design: Corner/entities/open_policy_creation_returns_declared_fields_and_system_defaults
    """
    created = validate_success(
        api.create_open_policy(OPEN_POLICY_CANONICAL, UNDERWRITER), 201)

    assert is_valid_uuid(created["id"]), f"id is not a bare UUID: {created['id']!r}"
    assert created["policy_number"] == OPEN_POLICY_CANONICAL["policy_number"]
    assert created["assured_name"] == OPEN_POLICY_CANONICAL["assured_name"]
    assert _instant(created["inception_at"]) == _instant("2026-01-01T00:00:00Z")
    assert _instant(created["expiry_at"]) == _instant("2027-01-01T00:00:00Z")
    assert created["freight_basis"] == "PREPAID"
    assert created["warehouse_to_warehouse"] is True
    assert_rate(created["markup_pct"], 0.10, places=2, label="markup_pct")
    assert_money(created["deductible_amount"], 2500.00, "deductible_amount")
    assert_money(created["per_certificate_limit_amount"], 2000000.00,
                 "per_certificate_limit_amount")
    assert_money(created["conveyance_limit_amount"], 3000000.00,
                 "conveyance_limit_amount")
    assert_money(created["annual_aggregate_limit_amount"], 10000000.00,
                 "annual_aggregate_limit_amount")
    assert_rate(created["premium_rate_per_mille"], 3.500, places=3,
                label="premium_rate_per_mille")
    assert_rate(created["war_rate_per_mille"], 0.600, places=3,
                label="war_rate_per_mille")
    assert_rate(created["strikes_rate_per_mille"], 0.255, places=3,
                label="strikes_rate_per_mille")

    read_back = read_policy(api, created["id"])
    for field_name in ("policy_number", "assured_name", "freight_basis",
                       "warehouse_to_warehouse", "status", "war_cover_status"):
        assert read_back[field_name] == created[field_name], (
            f"{field_name} changed between the create and the read"
        )
    assert_money(read_back["per_certificate_limit_amount"], 2000000.00,
                 "read.per_certificate_limit_amount")
    assert_rate(read_back["premium_rate_per_mille"], 3.500, places=3,
                label="read.premium_rate_per_mille")


def test_new_open_policy_starts_at_draft_with_every_ledger_at_zero(
        api: ApiClient) -> None:
    """
    A written open cover stamps its own state, ledgers and war-termination block.

    A newly written policy lands in `status` `DRAFT` with `war_cover_status` `ATTACHED`, `version` 1, all five ledgers at zero, and `war_terminated_at`, `war_termination_port_unlocode` and `reinstatement_rate_per_mille` all null.

    Design: Corner/entities/open_policy_creation_returns_declared_fields_and_system_defaults
    """
    created = validate_success(
        api.create_open_policy(OPEN_POLICY_CANONICAL, UNDERWRITER), 201)

    assert created["status"] == "DRAFT", f"status: got {created['status']!r}"
    assert created["war_cover_status"] == "ATTACHED", (
        f"war_cover_status: got {created['war_cover_status']!r}"
    )
    assert_common_fields(created, expected_version=1, label="policy")
    assert_money(created["aggregate_insured_value_booked"], 0.00,
                 "aggregate_insured_value_booked")
    assert_money(created["aggregate_premium_booked"], 0.00,
                 "aggregate_premium_booked")
    assert_money(created["aggregate_return_premium"], 0.00,
                 "aggregate_return_premium")
    assert_money(created["security_deposit_held_amount"], 0.00,
                 "security_deposit_held_amount")
    assert created["certificates_issued_count"] == 0, (
        f"certificates_issued_count: got {created['certificates_issued_count']!r}"
    )
    assert created["war_terminated_at"] is None, "war_terminated_at must be null"
    assert created["war_termination_port_unlocode"] is None, (
        "war_termination_port_unlocode must be null"
    )
    assert created["reinstatement_rate_per_mille"] is None, (
        "reinstatement_rate_per_mille must be null"
    )


# ---------------------------------------------------------------------------
# Declared defaults on a port and on an open cover
# ---------------------------------------------------------------------------
def test_port_storage_window_defaults_to_sixty_free_days(api: ApiClient) -> None:
    """
    A port registered without a free-storage window gets the declared sixty days.

    Free storage after discharge is set by `storage_free_days`, defaulting to 60 and constrained to at least 1 and at most 60 days; this is the number of days warehouse-to-warehouse cover survives at that port before it lapses.

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(api.create_port(PORT_MINIMAL, UNDERWRITER), 201)

    assert created["storage_free_days"] == 60, (
        f"storage_free_days: expected 60, got {created['storage_free_days']!r}"
    )
    read_back = validate_success(api.get_port(created["id"], UNDERWRITER))
    assert read_back["storage_free_days"] == 60, (
        "the defaulted free-storage window must survive the read"
    )


def test_port_war_exposure_defaults_to_the_green_tier(api: ApiClient) -> None:
    """
    A port registered without a war-risk tier is treated as green.

    War exposure is set by `war_risk_tier`, defaulting to `GREEN` and otherwise `AMBER` or `LISTED_AREA`.

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(api.create_port(PORT_MINIMAL, UNDERWRITER), 201)

    assert created["war_risk_tier"] == "GREEN", (
        f"war_risk_tier: expected GREEN, got {created['war_risk_tier']!r}"
    )


def test_green_tier_carries_a_unit_war_rate_multiplier(api: ApiClient) -> None:
    """
    The green tier's derived multiplier is exactly one, so war rating is unloaded.

    Each tier fixes a derived `war_rate_multiplier`: `GREEN` gives 1.0, `AMBER` gives 1.5, and `LISTED_AREA` gives 0.0, meaning no war cover is obtainable there at any price.

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(api.create_port(PORT_MINIMAL, UNDERWRITER), 201)

    assert_rate(created["war_rate_multiplier"], 1.0, places=4,
                label="war_rate_multiplier")


def test_open_policy_transit_clause_defaults_to_warehouse_to_warehouse(
        api: ApiClient) -> None:
    """
    An open cover written without a transit clause is warehouse to warehouse.

    The transit clause is chosen by `warehouse_to_warehouse`, which defaults to true and means cover survives discharge for the storage window rather than ending overside.

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(
        api.create_open_policy(OPEN_POLICY_MINIMAL, UNDERWRITER), 201)

    assert created["warehouse_to_warehouse"] is True, (
        f"warehouse_to_warehouse: expected true, "
        f"got {created['warehouse_to_warehouse']!r}"
    )
    assert created["status"] == "DRAFT", f"status: got {created['status']!r}"


def test_open_policy_advance_profit_uplift_defaults_to_ten_percent(
        api: ApiClient) -> None:
    """
    An open cover written without a markup carries the declared 0.10 uplift.

    Whether declared ocean freight forms part of the insured-value base is fixed by `freight_basis`, which is either `PREPAID` or `COLLECT`, and the advance-profit uplift is fixed by `markup_pct`, which defaults to 0.10, is carried to 2 decimals and must be at least 0 and at most 0.30 — a thirty percent ceiling on imaginary profit.

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(
        api.create_open_policy(OPEN_POLICY_MINIMAL, UNDERWRITER), 201)

    assert_rate(created["markup_pct"], 0.10, places=2, label="markup_pct")


def test_open_policy_deductible_defaults_to_zero(api: ApiClient) -> None:
    """
    An open cover written without a per-claim excess carries none at all.

    Alongside the tower sits `deductible_amount`, the per-claim excess, defaulting to 0, and the three rates the pricing engine reads: `premium_rate_per_mille` for the marine risk (greater than zero, 3 decimals), `war_rate_per_mille` for war risk (at least zero, 3 decimals) and `strikes_rate_per_mille` for strikes, riots and civil commotions (at least zero, 3 decimals).

    Design: Corner/entities/port_and_policy_optional_inputs_fall_back_to_declared_defaults
    """
    created = validate_success(
        api.create_open_policy(OPEN_POLICY_MINIMAL, UNDERWRITER), 201)

    assert_money(created["deductible_amount"], 0.00, "deductible_amount")
    assert_rate(created["premium_rate_per_mille"], 3.500, places=3,
                label="premium_rate_per_mille")


# ---------------------------------------------------------------------------
# Reading one conveyance
# ---------------------------------------------------------------------------
def test_vessel_read_returns_the_registered_particulars(api: ApiClient) -> None:
    """
    A hull reads back with exactly the particulars it was registered with.

    A vessel is registered by an `Underwriter` with its `name`, its `imo_number` (unique across all vessels and exactly seven digits), its `year_built` (a whole year no earlier than 1900 and no later than 2100), its `classification_society` and its two-letter ISO country `flag_code`.

    Design: Corner/entities/vessel_get_by_id_returns_stored_and_computed_fields
    """
    created = create_vessel(api, review=False)

    hull = read_vessel(api, created["id"])
    assert hull["id"] == created["id"]
    assert hull["name"] == VESSEL_KITE["name"], f"name: got {hull['name']!r}"
    assert hull["imo_number"] == VESSEL_KITE["imo_number"], (
        f"imo_number: got {hull['imo_number']!r}"
    )
    assert hull["year_built"] == VESSEL_KITE["year_built"], (
        f"year_built: got {hull['year_built']!r}"
    )
    assert hull["classification_society"] == VESSEL_KITE["classification_society"]
    assert hull["flag_code"] == VESSEL_KITE["flag_code"]
    assert_money(hull["vessel_accumulation_limit_amount"],
                 VESSEL_KITE["vessel_accumulation_limit_amount"],
                 "vessel_accumulation_limit_amount")


def test_unscreened_vessel_reads_back_its_initial_computed_block(
        api: ApiClient) -> None:
    """
    A hull that has not been screened yet carries a zeroed computed block.

    A newly registered vessel lands in `status` `PENDING_REVIEW` with `overage_surcharge_pct`, `accumulated_insured_value` and `open_ga_event_count` all at zero, and no certificate may be issued on it in that state.

    Design: Corner/entities/vessel_get_by_id_returns_stored_and_computed_fields
    """
    created = create_vessel(api, review=False)

    hull = read_vessel(api, created["id"])
    assert hull["status"] == "PENDING_REVIEW", f"status: got {hull['status']!r}"
    assert_rate(hull["overage_surcharge_pct"], 0.00, places=2,
                label="overage_surcharge_pct")
    assert_money(hull["accumulated_insured_value"], 0.00,
                 "accumulated_insured_value")
    assert hull["open_ga_event_count"] == 0, (
        f"open_ga_event_count: got {hull['open_ga_event_count']!r}"
    )
    assert_common_fields(hull, expected_version=1, label="vessel")


# ---------------------------------------------------------------------------
# Listing commodity classes
# ---------------------------------------------------------------------------
def test_commodity_class_listing_paginates_with_counters_over_the_whole_set(
        api: ApiClient) -> None:
    """
    Two pages of a three-row register report the same total and opposite has_more.

    `total_count` is the number of rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the returned page.

    Design: Corner/entities/commodity_class_listing_paginates_and_filters_by_susceptibility
    """
    classes = _build_three_commodity_classes(api)

    first_rows, first_meta = validate_paginated(
        api.list_commodity_classes(UNDERWRITER, {"limit": 2, "offset": 0}))
    assert len(first_rows) == 2, f"first page holds {len(first_rows)} rows"
    assert first_meta["total_count"] == 3, (
        f"total_count: expected 3, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "rows remain beyond the first page"
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_commodity_classes(UNDERWRITER, {"limit": 2, "offset": 2}))
    assert len(second_rows) == 1, f"second page holds {len(second_rows)} rows"
    assert second_meta["total_count"] == 3, (
        f"total_count: expected 3, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "nothing remains beyond the last page"
    assert second_meta["offset"] == 2

    paged_ids = collect_ids(first_rows) + collect_ids(second_rows)
    assert sorted(paged_ids) == sorted(
        [classes["electronics"]["id"], classes["steel"]["id"],
         classes["reefer"]["id"]]), (
        "the two pages together must cover the register exactly once"
    )


def test_commodity_class_listing_narrows_by_susceptibility_rating(
        api: ApiClient) -> None:
    """
    Filtering the register by susceptibility returns only the matching class.

    Classes can be listed by every role, optionally narrowed by `susceptibility_rating`.

    Design: Corner/entities/commodity_class_listing_paginates_and_filters_by_susceptibility
    """
    classes = _build_three_commodity_classes(api)

    rows, meta = validate_paginated(
        api.list_commodity_classes(UNDERWRITER, {"susceptibility_rating": "S1"}))
    assert meta["total_count"] == 1, (
        f"total_count over the filtered set: expected 1, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "a single matching row leaves nothing behind"
    assert len(rows) == 1, f"the filtered page holds {len(rows)} rows"
    assert rows[0]["id"] == classes["steel"]["id"], (
        "the S1 filter must return the hot rolled coil class"
    )
    assert rows[0]["susceptibility_rating"] == "S1"
    assert_rate(rows[0]["rate_loading_pct"], 0.00, places=2,
                label="rate_loading_pct")
    assert_rate(rows[0]["max_conveyance_share_pct"], 1.00, places=2,
                label="max_conveyance_share_pct")
    assert_money(rows[0]["survey_required_above_amount"], 1000000.00,
                 "survey_required_above_amount")


# ---------------------------------------------------------------------------
# Path identifier resolution
# ---------------------------------------------------------------------------
def test_unknown_path_ids_return_entity_specific_not_found(api: ApiClient) -> None:
    """
    Each collection answers an absent path identifier with its own 404 identifier.

    The resolution errors are `ERR_POLICY_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SURVEY_ORDER_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_GA_EVENT_NOT_FOUND`, `ERR_GA_POSTING_NOT_FOUND` and `ERR_ACCUMULATION_ENTRY_NOT_FOUND`, each carrying HTTP 404.

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found
    """
    probes = [
        ("open policy",
         api.get_open_policy(NON_EXISTENT_UUID, UNDERWRITER),
         ERR_POLICY_NOT_FOUND),
        ("certificate",
         api.get_certificate(NON_EXISTENT_UUID, UNDERWRITER),
         ERR_CERTIFICATE_NOT_FOUND),
        ("vessel",
         api.get_vessel(NON_EXISTENT_UUID, UNDERWRITER),
         ERR_VESSEL_NOT_FOUND),
        ("port",
         api.get_port(NON_EXISTENT_UUID, UNDERWRITER),
         ERR_PORT_NOT_FOUND),
        ("claim file",
         api.get_claim_file(NON_EXISTENT_UUID, CLAIMS_ADJUSTER),
         ERR_CLAIM_NOT_FOUND),
        ("survey order",
         api.get_survey_order(NON_EXISTENT_UUID, CLAIMS_ADJUSTER),
         ERR_SURVEY_ORDER_NOT_FOUND),
        ("premium declaration",
         api.get_premium_declaration(NON_EXISTENT_UUID, PREMIUM_AUDITOR),
         ERR_DECLARATION_NOT_FOUND),
        ("general average event",
         api.get_ga_event(NON_EXISTENT_UUID, CLAIMS_ADJUSTER),
         ERR_GA_EVENT_NOT_FOUND),
        ("security posting",
         api.get_ga_security_posting(NON_EXISTENT_UUID, CLAIMS_ADJUSTER),
         ERR_GA_POSTING_NOT_FOUND),
        ("accumulation entry",
         api.get_accumulation_entry(NON_EXISTENT_UUID, UNDERWRITER),
         ERR_ACCUMULATION_ENTRY_NOT_FOUND),
    ]

    for label, response, expected_error in probes:
        assert response.status_code == 404, (
            f"{label}: expected HTTP 404, got {response.status_code}"
        )
        validate_error(response, expected_error)
        meta = response.json()["meta"]
        assert isinstance(meta.get("api_request_id"), str), (
            f"{label}: the error envelope must carry meta.api_request_id"
        )


# ---------------------------------------------------------------------------
# Schema validation on a shipment declaration
# ---------------------------------------------------------------------------
def test_certificate_declaration_without_a_vessel_is_rejected(
        api: ApiClient, canonical_env: dict) -> None:
    """
    Dropping the carrying conveyance fails the schema gate before any lookup.

    Schema validation itself precedes all of this and reports `ERR_INVALID_REQUEST` (HTTP 400): every non-optional input field of the endpoint must be present, enum-typed fields must hold one of their declared values, money fields must be non-negative where declared so, datetimes must parse as ISO 8601 UTC, and pagination bounds must hold.

    Design: Corner/entities/certificate_creation_missing_required_fields_returns_invalid_request
    """
    body = _certificate_body(canonical_env, certificate_number="CERT-NOVSL")
    body.pop("vessel_id")

    response = api.create_certificate(
        body, make_assured_headers(canonical_env["policy_id"]))
    validate_error(response, ERR_INVALID_REQUEST)

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"open_policy_id": canonical_env["policy_id"]}),
        0, "certificates of the cover")
    policy = read_policy(api, canonical_env["policy_id"])
    assert policy["certificates_issued_count"] == 0, (
        "a rejected declaration must not touch the issued-certificate counter"
    )
    assert policy["version"] == 2, (
        "the cover has only been written and activated, so its version is 2"
    )


def test_certificate_declaration_without_a_sailing_date_is_rejected(
        api: ApiClient, canonical_env: dict) -> None:
    """
    Dropping the sailing instant fails the schema gate, so no draft is written.

    Schema validation itself precedes all of this and reports `ERR_INVALID_REQUEST` (HTTP 400): every non-optional input field of the endpoint must be present, enum-typed fields must hold one of their declared values, money fields must be non-negative where declared so, datetimes must parse as ISO 8601 UTC, and pagination bounds must hold.

    Design: Corner/entities/certificate_creation_missing_required_fields_returns_invalid_request
    """
    body = _certificate_body(canonical_env, certificate_number="CERT-NODATE")
    body.pop("sailing_date")

    response = api.create_certificate(
        body, make_assured_headers(canonical_env["policy_id"]))
    validate_error(response, ERR_INVALID_REQUEST)

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"open_policy_id": canonical_env["policy_id"]}),
        0, "certificates of the cover")


def test_certificate_declaration_ignores_computed_and_system_fields(
        api: ApiClient, canonical_env: dict) -> None:
    """
    A body smuggling an insured value, a status and a premium total has no effect.

    Fields that the system computes or manages itself are ignored rather than rejected when a client sends them — a client that helpfully includes `insured_value` or `status` in a body does not get an error, it simply gets no effect.

    Design: Corner/entities/certificate_computed_and_system_fields_input_ignored
    """
    body = _certificate_body(
        canonical_env, certificate_number="CERT-SMUG",
        insured_value=9.99, status="ISSUED", total_premium_amount=1.00)

    created = validate_success(
        api.create_certificate(
            body, make_assured_headers(canonical_env["policy_id"])), 201)

    assert_money(created["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "insured_value")
    assert created["status"] == "DRAFT", (
        f"status: expected DRAFT, got {created['status']!r}"
    )
    assert created["war_cover_status"] == "PENDING", (
        f"war_cover_status: expected PENDING, got {created['war_cover_status']!r}"
    )
    assert created["total_premium_amount"] is None, (
        f"total_premium_amount must be null on a draft, "
        f"got {created['total_premium_amount']!r}"
    )
    assert_money(created["deductible_amount"], 2500.00, "deductible_amount")
    assert created["issued_by_user_id"] is None, "issued_by_user_id must be null"
    assert created["issued_at"] is None, "issued_at must be null"


# ---------------------------------------------------------------------------
# Type and range constraints on the register
# ---------------------------------------------------------------------------
def test_vessel_registration_rejects_an_unlisted_classification_society(
        api: ApiClient) -> None:
    """
    A society outside the declared vocabulary is a payload fault, not a hull.

    Schema validation itself precedes all of this and reports `ERR_INVALID_REQUEST` (HTTP 400): every non-optional input field of the endpoint must be present, enum-typed fields must hold one of their declared values, money fields must be non-negative where declared so, datetimes must parse as ISO 8601 UTC, and pagination bounds must hold.

    Design: Corner/entities/vessel_port_and_policy_type_constraint_violations_rejected
    """
    baseline = create_vessel(api, review=False)

    payload = dict(VESSEL_KITE)
    payload.update({"name": "MV Enum", "imo_number": "9100002",
                    "classification_society": "RINA"})
    validate_error(api.create_vessel(payload, UNDERWRITER), ERR_INVALID_REQUEST)

    assert read_vessel(api, baseline["id"])["version"] == 1, (
        "a rejected registration must leave every existing hull untouched"
    )


def test_vessel_registration_rejects_a_malformed_imo_number(
        api: ApiClient) -> None:
    """
    An IMO number that is not seven digits long is refused before any row exists.

    A vessel is registered by an `Underwriter` with its `name`, its `imo_number` (unique across all vessels and exactly seven digits), its `year_built` (a whole year no earlier than 1900 and no later than 2100), its `classification_society` and its two-letter ISO country `flag_code`.

    Design: Corner/entities/vessel_port_and_policy_type_constraint_violations_rejected
    """
    baseline = create_vessel(api, review=False)

    payload = dict(VESSEL_KITE)
    payload.update({"name": "MV Imo", "imo_number": "91"})
    validate_error(api.create_vessel(payload, UNDERWRITER), ERR_INVALID_REQUEST)

    assert read_vessel(api, baseline["id"])["version"] == 1, (
        "a rejected registration must leave every existing hull untouched"
    )


def test_port_registration_rejects_a_storage_window_above_sixty_days(
        api: ApiClient) -> None:
    """
    Ninety free storage days is outside the declared range and is refused.

    Free storage after discharge is set by `storage_free_days`, defaulting to 60 and constrained to at least 1 and at most 60 days; this is the number of days warehouse-to-warehouse cover survives at that port before it lapses.

    Design: Corner/entities/vessel_port_and_policy_type_constraint_violations_rejected
    """
    payload = dict(PORT_MINIMAL)
    payload["storage_free_days"] = 90

    validate_error(api.create_port(payload, UNDERWRITER), ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# The append-only evidence log
# ---------------------------------------------------------------------------
def _open_claim_after_moving_the_clock(api: ApiClient, env: dict) -> str:
    """
    Move the logical clock past the loss and open a claim on the environment's
    issued certificate. Returns the claim identifier.
    """
    set_clock(api, EVIDENCE_CLOCK)
    claim = open_claim_file(api, env["certificate_id"], peril="SEA_PERIL",
                            loss_date="2026-09-02T00:00:00Z",
                            damage_percentage=12.5)
    return claim["id"]


def test_damage_document_carries_no_version_and_no_updated_at(
        api: ApiClient, issued_certificate_env: dict) -> None:
    """
    An appended document exposes only the append-only common properties.

    Documents are immutable once written — this is an append-only log, so a document row has no `updated_at` and no `version`, and there is no way to amend or remove one.

    Design: Corner/entities/damage_document_is_append_only_with_no_version_field
    """
    claim_id = _open_claim_after_moving_the_clock(api, issued_certificate_env)

    document = validate_success(api.add_claim_document(
        claim_id, {"doc_type": "BILL_OF_LADING", "reference": "BL-SGNL-778"},
        CLAIMS_ADJUSTER), 201)

    assert_append_only_fields(document, label="damage document")
    assert_fields_present(
        document,
        ["claim_file_id", "doc_type", "reference", "received_at", "origin"],
        label="damage document")
    assert document["claim_file_id"] == claim_id
    assert document["doc_type"] == "BILL_OF_LADING"
    assert document["reference"] == "BL-SGNL-778"


def test_damage_document_origin_is_stamped_from_the_acting_role(
        api: ApiClient, issued_certificate_env: dict) -> None:
    """
    A document posted by an adjuster records an adjuster origin.

    Each row also records an `origin` of `ADJUSTER` or `SURVEYOR` according to the role that posted it.

    Design: Corner/entities/damage_document_is_append_only_with_no_version_field
    """
    claim_id = _open_claim_after_moving_the_clock(api, issued_certificate_env)

    document = validate_success(api.add_claim_document(
        claim_id, {"doc_type": "BILL_OF_LADING", "reference": "BL-SGNL-778"},
        CLAIMS_ADJUSTER), 201)

    assert document["origin"] == "ADJUSTER", (
        f"origin: expected ADJUSTER, got {document['origin']!r}"
    )


def test_damage_document_received_at_falls_back_to_the_logical_clock(
        api: ApiClient, issued_certificate_env: dict) -> None:
    """
    A document appended without a received instant takes the logical clock's.

    Documents are appended to the claim by a `ClaimsAdjuster` or a `Surveyor`, each carrying a `doc_type` drawn from `SURVEY_REPORT`, `PACKING_LIST`, `BILL_OF_LADING`, `COMMERCIAL_INVOICE`, `CARRIER_CLAIM_LETTER` and `PHOTO_SET`, a free-text `reference` locating the document, and an optional `received_at` instant which otherwise takes the logical clock.

    Design: Corner/entities/damage_document_is_append_only_with_no_version_field
    """
    claim_id = _open_claim_after_moving_the_clock(api, issued_certificate_env)

    document = validate_success(api.add_claim_document(
        claim_id, {"doc_type": "BILL_OF_LADING", "reference": "BL-SGNL-778"},
        CLAIMS_ADJUSTER), 201)

    assert _instant(document["received_at"]) == _instant(EVIDENCE_CLOCK), (
        f"received_at: expected the logical clock at {EVIDENCE_CLOCK}, "
        f"got {document['received_at']!r}"
    )


def test_one_bill_of_lading_leaves_the_claim_documentation_incomplete(
        api: ApiClient, issued_certificate_env: dict) -> None:
    """
    A log holding one of the three mandatory types is not yet complete.

    Appending a document re-derives the claim's `documentation_complete`, which becomes true once the log holds at least one document of each of the three mandatory types `SURVEY_REPORT`, `BILL_OF_LADING` and `CARRIER_CLAIM_LETTER`; `COMMERCIAL_INVOICE`, `PACKING_LIST` and `PHOTO_SET` are useful but optional evidence.

    Design: Corner/entities/damage_document_is_append_only_with_no_version_field
    """
    claim_id = _open_claim_after_moving_the_clock(api, issued_certificate_env)

    document = validate_success(api.add_claim_document(
        claim_id, {"doc_type": "BILL_OF_LADING", "reference": "BL-SGNL-778"},
        CLAIMS_ADJUSTER), 201)

    rows = assert_total_count(
        api.list_claim_documents(claim_id, CLAIMS_ADJUSTER), 1, "evidence log")
    assert collect_ids(rows) == [document["id"]], (
        "the log must hold exactly the one appended document"
    )
    claim = validate_success(api.get_claim_file(claim_id, CLAIMS_ADJUSTER))
    assert claim["documentation_complete"] is False, (
        "one mandatory document of three cannot complete the file"
    )


# ---------------------------------------------------------------------------
# Body reference resolution
# ---------------------------------------------------------------------------
def test_certificate_body_references_each_yield_their_own_not_found(
        api: ApiClient, canonical_env: dict) -> None:
    """
    One fabricated reference at a time decides which 404 the declaration returns.

    An unresolvable body reference yields the 404 error of the entity it points at — `ERR_POLICY_NOT_FOUND`, `ERR_COMMODITY_CLASS_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`, `ERR_PORT_NOT_FOUND` (which also covers an unresolvable `base_port_id`), `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SURVEYOR_NOT_FOUND` or `ERR_GA_EVENT_NOT_FOUND`.

    Design: Corner/entities/body_foreign_keys_are_validated_before_ownership_returns_not_found
    """
    assured = make_assured_headers(canonical_env["policy_id"])

    probes = [
        ("commodity_class_id", "CERT-FK1", ERR_COMMODITY_CLASS_NOT_FOUND),
        ("vessel_id", "CERT-FK2", ERR_VESSEL_NOT_FOUND),
        ("discharge_port_id", "CERT-FK3", ERR_PORT_NOT_FOUND),
    ]
    for field_name, certificate_number, expected_error in probes:
        body = _certificate_body(canonical_env,
                                 certificate_number=certificate_number)
        body[field_name] = NON_EXISTENT_UUID
        response = api.create_certificate(body, assured)
        validate_error(response, expected_error)

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"open_policy_id": canonical_env["policy_id"]}),
        0, "certificates of the cover")


def test_unresolvable_policy_reference_precedes_the_ownership_check(
        api: ApiClient, canonical_env: dict) -> None:
    """
    A fabricated cover reference answers not-found even though the assured owns another.

    The global order is: authentication headers, then role authorisation, then payload schema, then path identifier resolution, then body reference resolution, then ownership and segregation of duties, then natural-key uniqueness, then state and transition preconditions, then optimistic-concurrency version checks, then the domain-specific bands.

    Design: Corner/entities/body_foreign_keys_are_validated_before_ownership_returns_not_found
    """
    body = _certificate_body(canonical_env, certificate_number="CERT-FK4",
                             open_policy_id=NON_EXISTENT_UUID)

    response = api.create_certificate(
        body, make_assured_headers(canonical_env["policy_id"]))
    validate_error(response, ERR_POLICY_NOT_FOUND)

    assert_total_count(
        api.list_certificates(UNDERWRITER,
                              {"open_policy_id": canonical_env["policy_id"]}),
        0, "certificates of the cover")


def test_claim_declaration_and_surveyor_bodies_resolve_their_references(
        api: ApiClient, canonical_env: dict) -> None:
    """
    Every create that carries a reference resolves it before doing anything else.

    Body-reference resolution applies wherever a body carries a reference: shipment declaration, claim opening, survey-order creation, declaration opening, general average declaration and surveyor appointment.

    Design: Corner/entities/body_foreign_keys_are_validated_before_ownership_returns_not_found
    """
    claim_body = {
        "certificate_id": NON_EXISTENT_UUID,
        "loss_type": "PARTICULAR_AVERAGE",
        "peril": "SEA_PERIL",
        "adjustment_basis": "DEPRECIATION_PCT",
        "claimed_amount": 1000.00,
        "loss_date": "2026-09-02T00:00:00Z",
        "damage_percentage": 1.0,
    }
    validate_error(api.create_claim_file(claim_body, CLAIMS_ADJUSTER),
                   ERR_CERTIFICATE_NOT_FOUND)

    declaration_body = {
        "open_policy_id": NON_EXISTENT_UUID,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    validate_error(
        api.create_premium_declaration(
            declaration_body, make_assured_headers(canonical_env["policy_id"])),
        ERR_POLICY_NOT_FOUND)

    surveyor_body = dict(SURVEYOR_ROTTERDAM)
    surveyor_body["base_port_id"] = NON_EXISTENT_UUID
    validate_error(api.create_surveyor(surveyor_body, COMPLIANCE_OFFICER),
                   ERR_PORT_NOT_FOUND)
