"""Entity contracts of the executive compensation and say-on-pay API.

This module covers the shape of the rows themselves: what a company registration
accepts and echoes, what a read-back returns, the defaults a registration applies
when a field is omitted, the server-managed `id`, `created_at`, `updated_at` and
`version` properties every entity carries, the computed size ratios of a peer
membership, the many-to-many membership junction between a peer group and a
company, left-to-right path-identifier resolution, and request well-formedness on
the creating endpoints.
"""

from test_helpers import (
    CHAIR,
    CONSULTANT,
    COUNSEL,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_member_payload,
    api_client,
    assert_common_fields,
    assert_company,
    assert_money,
    assert_peer_group,
    assert_peer_group_member,
    assert_ratio,
    create_company,
    create_company_payload,
    create_executive_payload,
    create_peer_group,
    create_peer_group_payload,
    create_restatement_event_payload,
    is_valid_uuid,
    read_peer_group,
    read_peer_group_members,
    read_restatement_events,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Company registration, defaults and read-back
# ---------------------------------------------------------------------------
def test_company_registration_returns_201_with_every_declared_field():
    """Registering the issuer echoes all eight declared inputs and returns 201.

    PRD: "A `CompConsultant` registers a company with its `legal_name` (one to one hundred and twenty characters, not blank), its `ticker` (one to five uppercase letters), the `is_issuer` flag, a `gics_sector` drawn from `TECH`, `INDUSTRIALS`, `HEALTHCARE`, `FINANCIALS`, `CONSUMER` or `ENERGY`, and four market data points: trailing-twelve-month `revenue_usd` and `market_cap_usd` (both strictly positive), the current `share_price_usd` (strictly positive), and `ceo_tdc_usd`, the last disclosed chief-executive total direct compensation, which may be zero but not negative."
    PRD: "Creating a new row returns `201 Created`."

    Design: Corner/entities/company_creation_returns_201_with_every_declared_field
    """
    set_clock()

    response = api_client.create_company(create_company_payload("ACME"), CONSULTANT)

    company = validate_success(response, 201)
    assert_company(company)
    assert company["legal_name"] == "Acme Industries Inc"
    assert company["ticker"] == "ACME"
    # is_issuer is honoured as sent rather than defaulted back to false.
    assert company["is_issuer"] is True
    assert company["gics_sector"] == "TECH"
    assert_money(company["revenue_usd"], 10000000000, "revenue_usd")
    assert_money(company["market_cap_usd"], 20000000000, "market_cap_usd")
    assert_money(company["share_price_usd"], 50.00, "share_price_usd")
    assert_money(company["ceo_tdc_usd"], 15000000, "ceo_tdc_usd")

    body = response.json()
    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present"


def test_company_read_back_returns_the_stored_row_with_version_still_one():
    """A pure read of the issuer neither recomputes nor re-defaults anything.

    PRD: "**`version`** (integer): a counter that starts at 1 on creation and increments by exactly one on every mutation of that row."

    Design: Corner/entities/company_retrieval_returns_the_stored_row_unchanged
    """
    set_clock()
    issuer = create_company("ACME")

    response = api_client.get_company(issuer["id"], CHAIR)

    company = validate_success(response, 200)
    assert_company(company)
    assert company["id"] == issuer["id"]
    assert company["ticker"] == "ACME"
    assert_money(company["revenue_usd"], 10000000000, "revenue_usd")
    assert company["listing_status"] == "ACTIVE"
    assert company["version"] == 1, "a read is not a mutation, so version stays at 1"


def test_company_registration_defaults_listing_status_to_active():
    """Omitting listing_status yields ACTIVE and omitting is_issuer yields false.

    PRD: "`is_issuer` defaults to false when the field is omitted, and a `listing_status` may be supplied at registration but defaults to `ACTIVE`."

    Design: Corner/entities/company_creation_omitting_listing_status_defaults_to_active
    """
    set_clock()
    payload = create_company_payload("BRVO")
    payload.pop("is_issuer")
    assert "listing_status" not in payload, "the default is only observable when the field is omitted"

    response = api_client.create_company(payload, CONSULTANT)

    company = validate_success(response, 201)
    assert_company(company)
    assert company["listing_status"] == "ACTIVE"
    assert company["is_issuer"] is False


def test_company_registration_without_ticker_is_malformed():
    """A registration missing the required ticker is rejected as malformed.

    PRD: "This covers missing required fields, enum values outside their declared sets, numbers that are negative where the field's semantics forbid it, a reallocation whose `from_component` equals its `to_component`, `points` that is not strictly positive, non-integer vote tallies or tallies whose `votes_for` and `votes_against` sum to zero, `window_end` at or before `window_start`, `lookback_end` at or before `lookback_start`, and any instant that is not parseable ISO 8601."

    Design: Corner/entities/company_creation_without_ticker_returns_invalid_request
    """
    set_clock()
    payload = create_company_payload("ACME")
    payload.pop("ticker")

    response = api_client.create_company(payload, CONSULTANT)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    # No row was written: registering the issuer afterwards is still the first
    # company carrying is_issuer true, so it is accepted.
    issuer = validate_success(
        api_client.create_company(create_company_payload("ACME"), CONSULTANT), 201
    )
    assert issuer["is_issuer"] is True


def test_company_registration_with_undeclared_gics_sector_is_malformed():
    """A gics_sector outside the declared set is rejected instead of stored.

    PRD: "This covers missing required fields, enum values outside their declared sets, numbers that are negative where the field's semantics forbid it, a reallocation whose `from_component` equals its `to_component`, `points` that is not strictly positive, non-integer vote tallies or tallies whose `votes_for` and `votes_against` sum to zero, `window_end` at or before `window_start`, `lookback_end` at or before `lookback_start`, and any instant that is not parseable ISO 8601."

    Design: Corner/entities/company_creation_with_an_undeclared_gics_sector_returns_invalid_request
    """
    set_clock()
    payload = create_company_payload("HOTL", gics_sector="MATERIALS")

    response = api_client.create_company(payload, CONSULTANT)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    # The ticker was never taken, because no row with an out-of-set sector was stored.
    accepted = validate_success(
        api_client.create_company(create_company_payload("HOTL"), CONSULTANT), 201
    )
    assert accepted["ticker"] == "HOTL"
    assert accepted["gics_sector"] == "TECH"


def test_company_read_with_unknown_id_returns_company_not_found():
    """A syntactically valid but never-minted company id resolves to a 404.

    PRD: "A request naming a non-existent company therefore fails with `ERR_COMPANY_NOT_FOUND` before any question about the sub-resource is asked; the same discipline yields `ERR_PEER_GROUP_NOT_FOUND`, `ERR_PEER_GROUP_MEMBER_NOT_FOUND`, `ERR_EXECUTIVE_NOT_FOUND`, `ERR_PAY_PROGRAM_NOT_FOUND`, `ERR_INCENTIVE_METRIC_NOT_FOUND`, `ERR_PAYOUT_AWARD_NOT_FOUND`, `ERR_CDA_DRAFT_NOT_FOUND`, `ERR_SCREEN_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_RESTATEMENT_EVENT_NOT_FOUND` and `ERR_DETERMINATION_NOT_FOUND` for their respective row types."

    Design: Corner/entities/company_get_with_an_unknown_id_returns_company_not_found
    """
    set_clock()

    response = api_client.get_company(NON_EXISTENT_UUID, CONSULTANT)

    validate_error(response, ApiErrorId.ERR_COMPANY_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


# ---------------------------------------------------------------------------
# Parent resolution on nested creates
# ---------------------------------------------------------------------------
def test_executive_registration_under_unknown_company_returns_company_not_found():
    """An officer registration under an unknown company id never persists a row.

    PRD: "A request naming a non-existent company therefore fails with `ERR_COMPANY_NOT_FOUND` before any question about the sub-resource is asked; the same discipline yields `ERR_PEER_GROUP_NOT_FOUND`, `ERR_PEER_GROUP_MEMBER_NOT_FOUND`, `ERR_EXECUTIVE_NOT_FOUND`, `ERR_PAY_PROGRAM_NOT_FOUND`, `ERR_INCENTIVE_METRIC_NOT_FOUND`, `ERR_PAYOUT_AWARD_NOT_FOUND`, `ERR_CDA_DRAFT_NOT_FOUND`, `ERR_SCREEN_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_RESTATEMENT_EVENT_NOT_FOUND` and `ERR_DETERMINATION_NOT_FOUND` for their respective row types."

    Design: Corner/entities/executive_creation_under_an_unknown_company_returns_company_not_found
    """
    set_clock()
    issuer = create_company("ACME")

    response = api_client.create_executive(
        NON_EXISTENT_UUID, create_executive_payload("CEO"), CONSULTANT
    )

    validate_error(response, ApiErrorId.ERR_COMPANY_NOT_FOUND, 404)
    rows, meta = validate_paginated(
        api_client.list_company_executives(issuer["id"], CONSULTANT, {"limit": 100})
    )
    assert meta["total_count"] == 0, "the well-formed body must not have been persisted"
    assert rows == []


def test_restatement_declaration_with_inverted_lookback_window_is_malformed():
    """A lookback window whose end precedes its start is a malformed request.

    PRD: "The lookback end must be strictly after the lookback start, and the restatement date must fall at or after the lookback end."

    Design: Corner/entities/restatement_event_with_lookback_end_before_start_returns_invalid_request
    """
    set_clock()
    issuer = create_company("ACME")
    payload = create_restatement_event_payload(
        restatement_date="2027-03-01T00:00:00Z",
        lookback_start="2026-12-31T23:59:59Z",
        lookback_end="2026-01-01T00:00:00Z",
        accounting_reason="Inverted window supplied on purpose.",
    )

    response = api_client.create_restatement_event(issuer["id"], payload, COUNSEL)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert read_restatement_events(issuer["id"]) == [], "no event row may be written"


# ---------------------------------------------------------------------------
# Peer group and membership contracts
# ---------------------------------------------------------------------------
def test_new_peer_group_starts_at_version_one_with_zero_members_and_null_medians():
    """A freshly opened group carries server-minted system fields and no benchmark.

    PRD: "A freshly opened group has `accepted_member_count` of 0 and null medians."

    Design: Corner/entities/system_fields_are_server_generated_and_version_starts_at_one
    """
    set_clock()
    issuer = create_company("ACME")

    response = api_client.create_peer_group(
        create_peer_group_payload(issuer["id"], "RAW_MEDIAN"), CONSULTANT
    )

    peer_group = validate_success(response, 201)
    assert_peer_group(peer_group)
    assert_common_fields(peer_group, "PeerGroup")
    assert is_valid_uuid(peer_group["id"]), "the id is a server-minted UUID"
    assert peer_group["version"] == 1
    assert peer_group["created_at"] == peer_group["updated_at"], (
        "nothing has mutated the row since it was written"
    )
    assert peer_group["status"] == "DRAFT"
    assert peer_group["accepted_member_count"] == 0
    assert peer_group["median_revenue_usd"] is None
    assert peer_group["median_market_cap_usd"] is None
    assert peer_group["benchmark_target_tdc_usd"] is None
    assert peer_group["approved_by_user_id"] is None


def test_peer_membership_size_ratios_derive_from_issuer_and_peer():
    """The membership's two ratios and band verdict are computed, never supplied.

    PRD: "The peer's revenue divided by the issuer's revenue, rounded half-up to four decimal places, is stored as `revenue_ratio`; the peer's market capitalisation divided by the issuer's market capitalisation, rounded the same way, is stored as `market_cap_ratio`."

    Design: Corner/entities/peer_group_member_ratios_are_derived_from_both_companies
    """
    set_clock()
    issuer = create_company("ACME")
    peer = create_company("BRVO")
    peer_group = create_peer_group(issuer["id"])

    response = api_client.add_peer_group_member(
        peer_group["id"],
        add_member_payload(peer["id"], peer_group["version"], "SIZE_MATCH"),
        CONSULTANT,
    )

    member = validate_success(response, 201)
    assert_peer_group_member(member)
    # 8,000,000,000 / 10,000,000,000 and 16,000,000,000 / 20,000,000,000.
    assert_ratio(member["revenue_ratio"], 0.8000, "revenue_ratio")
    assert_ratio(member["market_cap_ratio"], 0.8000, "market_cap_ratio")
    assert member["in_size_band"] is True
    assert member["status"] == "ACCEPTED"
    assert member["exclusion_reason"] is None


def test_peer_group_member_listing_windows_on_limit_and_offset():
    """A limit/offset window returns the second membership in creation order.

    PRD: "The response `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before the window is applied."
    PRD: "Unless a specific endpoint says otherwise, list results are ordered by the row's creation timestamp, ascending."

    Design: Corner/entities/peer_group_member_listing_paginates_with_limit_and_offset
    """
    set_clock()
    issuer = create_company("ACME")
    first_peer = create_company("BRVO")
    second_peer = create_company("CHRL")
    peer_group = create_peer_group(issuer["id"])
    api_client.add_peer_group_member(
        peer_group["id"],
        add_member_payload(first_peer["id"], peer_group["version"], "SIZE_MATCH"),
        CONSULTANT,
    )
    refreshed = read_peer_group(peer_group["id"])
    api_client.add_peer_group_member(
        peer_group["id"],
        add_member_payload(second_peer["id"], refreshed["version"], "SIZE_MATCH"),
        CONSULTANT,
    )

    rows, meta = validate_paginated(
        api_client.list_peer_group_members(peer_group["id"], CONSULTANT, {"limit": 1, "offset": 1})
    )

    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["total_count"] == 2, "total_count precedes the window"
    assert meta["has_more"] is False, "the window reaches the end of the set"
    assert len(rows) == 1
    assert rows[0]["peer_company_id"] == second_peer["id"], "CHRL was created second"
    # 12,000,000,000 / 10,000,000,000 and 30,000,000,000 / 20,000,000,000.
    assert_ratio(rows[0]["revenue_ratio"], 1.2000, "revenue_ratio")
    assert_ratio(rows[0]["market_cap_ratio"], 1.5000, "market_cap_ratio")


def test_one_peer_company_holds_memberships_in_two_peer_groups():
    """One peer sits in two groups at once, with a distinct membership row each.

    PRD: "A company may not appear twice in the same group even if its earlier membership has since been excluded — the second attempt is `ERR_PEER_ALREADY_IN_GROUP` — and a group's own issuer may never be added as a peer of itself, which is `ERR_PEER_IS_ISSUER`."

    Design: Corner/entities/one_peer_company_joins_two_peer_groups_through_the_junction_entity
    """
    set_clock()
    issuer = create_company("ACME")
    peer = create_company("BRVO")
    group_2026 = create_peer_group(issuer["id"], "RAW_MEDIAN", fiscal_year=2026)
    membership_2026 = validate_success(
        api_client.add_peer_group_member(
            group_2026["id"],
            add_member_payload(peer["id"], group_2026["version"], "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )
    group_2027 = create_peer_group(issuer["id"], "SIZE_ADJUSTED", fiscal_year=2027)
    membership_2027 = validate_success(
        api_client.add_peer_group_member(
            group_2027["id"],
            add_member_payload(peer["id"], group_2027["version"], "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api_client.list_company_peer_memberships(peer["id"], CONSULTANT, {"limit": 10, "offset": 0})
    )

    assert meta["total_count"] == 2, "the peer is reachable from the company side twice"
    assert {row["peer_group_id"] for row in rows} == {group_2026["id"], group_2027["id"]}
    assert all(row["peer_company_id"] == peer["id"] for row in rows)
    assert membership_2026["id"] != membership_2027["id"], "each membership is its own row"
    # One row from each group side.
    assert [row["id"] for row in read_peer_group_members(group_2026["id"])] == [
        membership_2026["id"]
    ]
    assert [row["id"] for row in read_peer_group_members(group_2027["id"])] == [
        membership_2027["id"]
    ]


def test_peer_group_rejects_its_own_issuer_as_a_peer():
    """A group may not benchmark itself, even though the issuer sits in both bands.

    PRD: "A company may not appear twice in the same group even if its earlier membership has since been excluded — the second attempt is `ERR_PEER_ALREADY_IN_GROUP` — and a group's own issuer may never be added as a peer of itself, which is `ERR_PEER_IS_ISSUER`."

    Design: Corner/entities/a_peer_group_cannot_contain_its_own_issuer
    """
    set_clock()
    issuer = create_company("ACME")
    peer_group = create_peer_group(issuer["id"])

    response = api_client.add_peer_group_member(
        peer_group["id"],
        add_member_payload(issuer["id"], peer_group["version"], "SIZE_MATCH"),
        CONSULTANT,
    )

    validate_error(response, ApiErrorId.ERR_PEER_IS_ISSUER, 422)
    after = read_peer_group(peer_group["id"])
    assert after["accepted_member_count"] == 0
    assert after["version"] == 1, "a rejected add does not bump the group's version"
