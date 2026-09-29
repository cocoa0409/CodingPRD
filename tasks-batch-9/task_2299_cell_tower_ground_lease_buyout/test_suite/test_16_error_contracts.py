"""Refusal contracts on the lease-buyout surface: who is let in, and what a miss is called.

A caller who never declares a recognized capacity is turned away before any tower company,
lease stream or deal is touched, and a caller who asks for a portfolio, a facility, a
landowner, a tenancy, a valuation, a deal, an offer, a title report, a refusal notice, a
dispute, a pledge or an amendment event that was never recorded is told exactly which kind
of record is missing.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    Role,
    RofrDecision,
    OfferAction,
    TEST_USERS,
    TenancyStatus,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    assert_pairwise_distinct,
    create_portfolio,
    create_tower_company,
    make_acquisition_analyst_headers,
    make_headers_with_unknown_role,
    make_headers_without_role,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    make_title_officer_headers,
    make_tower_company_agent_headers,
    make_treasury_officer_headers,
    tower_site_payload,
    validate_error,
    validate_paginated,
)

# ---------------------------------------------------------------------------
# Probe helpers: one request per addressable entity type, all aimed at ids that
# no record in a freshly started server can own.
# ---------------------------------------------------------------------------


def _read_probes(api, entity_id=UNKNOWN_UUID):
    """Single-resource reads whose path segment names a record that does not exist."""
    return {
        "portfolio": api.get_portfolio(entity_id, headers=make_platform_admin_headers()),
        "facility": api.get_financing_facility(entity_id, headers=make_treasury_officer_headers()),
        "landowner": api.get_landowner(entity_id, headers=make_acquisition_analyst_headers()),
        "deal": api.get_deal(entity_id, headers=make_portfolio_manager_headers()),
        "title_report": api.get_title_report(entity_id, headers=make_title_officer_headers()),
        "dispute": api.get_dispute(entity_id, headers=make_servicing_agent_headers()),
        "pledge": api.get_collateral_pledge(entity_id, headers=make_treasury_officer_headers()),
    }


def _action_probes(api, entity_id=UNKNOWN_UUID):
    """Write surfaces addressed at a child record that does not exist.

    Every body below carries only legal values, so nothing here can be mistaken for a
    request-shape or enumeration violation.
    """
    return {
        "tenancy": api.set_tenancy_status(
            entity_id, {"status": TenancyStatus.TERMINATED.value}, headers=make_servicing_agent_headers()
        ),
        "valuation": api.approve_valuation(entity_id, headers=make_portfolio_manager_headers()),
        "offer": api.transition_offer(
            entity_id, {"action": OfferAction.SEND.value}, headers=make_acquisition_analyst_headers()
        ),
        "amendment": api.reverse_amendment_event(
            entity_id, {"reversal_reason": "keyed the wrong event"}, headers=make_servicing_agent_headers()
        ),
    }


def _refusal_notice_probe(api, tower_company_id, entity_id=UNKNOWN_UUID):
    """A real tower company agent responds to a refusal notice that does not exist."""
    return api.respond_to_rofr_notice(
        entity_id,
        {"decision": RofrDecision.WAIVE.value},
        headers=make_tower_company_agent_headers(tower_company_id),
    )


def _body_reference_probe(api, entity_id=UNKNOWN_UUID):
    """A tower site registration naming a tower company that does not exist."""
    return api.create_tower_site(
        tower_site_payload(entity_id, site_code="NE-9999"), headers=make_acquisition_analyst_headers()
    )


# ---------------------------------------------------------------------------
# Authentication: the gate that fires before anything else
# ---------------------------------------------------------------------------


def test_portfolio_listing_without_a_role_header_is_refused_as_unauthenticated(api):
    """A portfolio listing that declares no capacity is refused before any row is read, even
    though four different roles are allowed to list portfolios.

    PRD 2.1: If either header is absent, or if `X-Role` carries a value that is not one of the nine recognized roles, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401).

    Design: Corner/errors/unauthenticated_read_without_a_known_role_header_rejected
    """
    response = api.list_portfolios(headers=make_headers_without_role(TEST_USERS[Role.PLATFORM_ADMIN.value]))

    assert response.status_code == 401, (
        f"a read with no X-Role header must be 401, got {response.status_code}: {response.text}"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        "a missing X-Role header is an authentication failure, not an authorization failure"
    )


def test_portfolio_listing_with_an_unrecognised_role_value_is_refused_as_unauthenticated(api):
    """A portfolio listing declaring a capacity outside the nine recognized roles is refused
    as unauthenticated rather than as a forbidden role.

    PRD 2.1: The nine roles are `PlatformAdmin`, `AcquisitionAnalyst`, `PortfolioManager`, `TreasuryOfficer`, `TitleOfficer`, `Lender`, `ServicingAgent`, `Landowner`, and `TowerCompanyAgent`.

    PRD 2.8: 1. **Authentication** — `X-Role` is present and names a known role; otherwise `ERR_UNAUTHENTICATED` (401).

    Design: Corner/errors/unauthenticated_read_without_a_known_role_header_rejected
    """
    response = api.list_portfolios(headers=make_headers_with_unknown_role())

    assert response.status_code == 401, (
        f"an unrecognised X-Role value must be 401, got {response.status_code}: {response.text}"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        "an unknown role value never reaches the endpoint's role permission check"
    )


def test_unauthenticated_refusal_carries_the_two_field_error_envelope(api):
    """The refusal body is the standard error envelope: a meta carrying only the request id and
    timestamp, a request id prefixed `req_`, an error identifier and a message, and no success key.

    PRD 2.2: The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.

    PRD 2.2: The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.

    Design: Corner/errors/unauthenticated_read_without_a_known_role_header_rejected
    """
    response = api.list_portfolios(headers=make_headers_without_role())

    assert response.status_code == 401, (
        f"a read with no identity headers must be 401, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["response_type"] == "error", f"response_type must be 'error', got {body.get('response_type')!r}"
    assert "success" not in body, f"the envelope carries no success key, got keys {sorted(body.keys())}"

    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"an error meta carries only the request id and timestamp, got {sorted(meta.keys())}"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )

    data = body["data"]
    assert data["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value, (
        f"error_id must be ERR_UNAUTHENTICATED, got {data.get('error_id')!r}"
    )
    assert type(data["message"]) is str and data["message"].strip(), (
        f"the refusal must carry a human-readable message, got {data.get('message')!r}"
    )


# ---------------------------------------------------------------------------
# Not found: one code per addressable entity type
# ---------------------------------------------------------------------------


def test_single_resource_reads_of_unknown_ids_name_the_missing_entity_type(api):
    """Reading a portfolio, facility, landowner, deal, title report, dispute or pledge by an id
    no record owns returns that entity type's own 404 code, even while real records exist.

    PRD 2.9: The not-found vocabulary is per entity: `ERR_PORTFOLIO_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_TOWER_COMPANY_NOT_FOUND`, `ERR_TOWER_SITE_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_TITLE_REPORT_NOT_FOUND`, `ERR_ROFR_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, and `ERR_AMENDMENT_NOT_FOUND`.

    PRD 2.8: 3. **Path resource existence** — every identifier in the URL path resolves to a live resource, checked outermost segment first; otherwise the matching not-found error (404).

    Design: Corner/errors/not_found_each_addressable_entity_type_returns_its_own_distinct_404_code
    """
    create_portfolio(api)
    create_tower_company(api)

    expected = {
        "portfolio": ApiErrorId.ERR_PORTFOLIO_NOT_FOUND,
        "facility": ApiErrorId.ERR_FACILITY_NOT_FOUND,
        "landowner": ApiErrorId.ERR_LANDOWNER_NOT_FOUND,
        "deal": ApiErrorId.ERR_DEAL_NOT_FOUND,
        "title_report": ApiErrorId.ERR_TITLE_REPORT_NOT_FOUND,
        "dispute": ApiErrorId.ERR_DISPUTE_NOT_FOUND,
        "pledge": ApiErrorId.ERR_PLEDGE_NOT_FOUND,
    }
    probes = _read_probes(api)
    for label, response in probes.items():
        assert response.status_code == 404, (
            f"the {label} read of an unknown id must be 404, got {response.status_code}: {response.text}"
        )
        validate_error(response, expected[label].value, 404)

    # The code is keyed to the entity type, not to the particular unknown id.
    for other_id in (UNKNOWN_UUID_ALT, NON_EXISTENT_UUID):
        repeat = api.get_portfolio(other_id, headers=make_platform_admin_headers())
        validate_error(repeat, ApiErrorId.ERR_PORTFOLIO_NOT_FOUND.value, 404)


def test_write_surfaces_on_unknown_children_name_the_missing_entity_type(api):
    """Reclassifying a tenancy, approving a valuation, transitioning an offer or reversing an
    amendment event against an id no record owns each returns that entity type's own 404 code.

    PRD 2.9: The not-found vocabulary is per entity: `ERR_PORTFOLIO_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_TOWER_COMPANY_NOT_FOUND`, `ERR_TOWER_SITE_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_TITLE_REPORT_NOT_FOUND`, `ERR_ROFR_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, and `ERR_AMENDMENT_NOT_FOUND`.

    PRD 2.8: Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed.

    Design: Corner/errors/not_found_each_addressable_entity_type_returns_its_own_distinct_404_code
    """
    expected = {
        "tenancy": ApiErrorId.ERR_TENANCY_NOT_FOUND,
        "valuation": ApiErrorId.ERR_VALUATION_NOT_FOUND,
        "offer": ApiErrorId.ERR_OFFER_NOT_FOUND,
        "amendment": ApiErrorId.ERR_AMENDMENT_NOT_FOUND,
    }
    probes = _action_probes(api)
    for label, response in probes.items():
        assert response.status_code == 404, (
            f"the {label} write against an unknown id must be 404, got {response.status_code}: {response.text}"
        )
        validate_error(response, expected[label].value, 404)

    # Aiming the same surfaces at a second unknown id changes nothing about the code.
    alternates = _action_probes(api, UNKNOWN_UUID_ALT)
    for label, response in alternates.items():
        validate_error(response, expected[label].value, 404)


def test_refusal_notice_that_does_not_exist_outranks_the_refusal_holder_check(api):
    """A real tower company agent responding to a refusal notice that does not exist is told the
    notice is missing, not that it holds no right of first refusal.

    PRD 2.8: Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed.

    PRD 2.8: 3. **Path resource existence** — every identifier in the URL path resolves to a live resource, checked outermost segment first; otherwise the matching not-found error (404).

    PRD 2.8: 7. **Refusal-holder ownership** — a `TowerCompanyAgent` caller responding to a notice is the tower company of the notice's tower site; otherwise `ERR_NOT_ROFR_HOLDER` (403).

    Design: Corner/errors/not_found_each_addressable_entity_type_returns_its_own_distinct_404_code
    """
    company = create_tower_company(api, rofr_required=True, rofr_window_days=30)

    response = _refusal_notice_probe(api, company["id"])

    assert response.status_code == 404, (
        f"path existence precedes the refusal-holder check, expected 404, got {response.status_code}: {response.text}"
    )
    validate_error(response, ApiErrorId.ERR_ROFR_NOTICE_NOT_FOUND.value, 404)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_NOT_ROFR_HOLDER.value, (
        "existence is checked at position 3 and refusal-holder ownership only at position 7"
    )


def test_tower_site_naming_an_unknown_tower_company_reports_the_missing_company(api):
    """Registering a tower site against a tower company that does not exist is refused with the
    tower company's own 404 code, and no site is written.

    PRD 2.9: The same vocabulary serves references carried in request bodies, one step later in the order.

    PRD 2.9: A pledge creation naming a `lease_stream_id` that does not resolve yields `ERR_LEASE_STREAM_NOT_FOUND`; a deal creation naming an unresolvable `portfolio_id`, `lease_stream_id`, or `valuation_id` yields `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, or `ERR_VALUATION_NOT_FOUND` respectively; a facility creation naming an unresolvable `portfolio_id` yields `ERR_PORTFOLIO_NOT_FOUND`; a tower site naming an unresolvable `tower_company_id` yields `ERR_TOWER_COMPANY_NOT_FOUND`; and a lease stream naming an unresolvable `tower_site_id` or `landowner_id` yields `ERR_TOWER_SITE_NOT_FOUND` or `ERR_LANDOWNER_NOT_FOUND`.

    Design: Corner/errors/not_found_each_addressable_entity_type_returns_its_own_distinct_404_code
    """
    response = _body_reference_probe(api)

    assert response.status_code == 404, (
        f"an unresolvable tower_company_id must be 404, got {response.status_code}: {response.text}"
    )
    validate_error(response, ApiErrorId.ERR_TOWER_COMPANY_NOT_FOUND.value, 404)

    listing, meta = validate_paginated(api.list_tower_sites(headers=make_acquisition_analyst_headers()))
    assert meta["total_count"] == 0, (
        f"a refused registration writes nothing, expected total_count 0, got {meta['total_count']}"
    )
    assert listing == [], f"a refused registration writes nothing, got {listing}"


def test_every_addressable_entity_type_reports_a_different_missing_record_code(api):
    """Thirteen entity types addressed with the same unknown id return thirteen different 404
    codes, so no single generic not-found error stands in for all of them.

    PRD 2.9: The not-found vocabulary is per entity: `ERR_PORTFOLIO_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_TOWER_COMPANY_NOT_FOUND`, `ERR_TOWER_SITE_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_TITLE_REPORT_NOT_FOUND`, `ERR_ROFR_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, and `ERR_AMENDMENT_NOT_FOUND`.

    PRD 2.8: 4. **Body foreign-key existence** — every reference carried in the request body resolves; otherwise the matching not-found error (404).

    Design: Corner/errors/not_found_each_addressable_entity_type_returns_its_own_distinct_404_code
    """
    company = create_tower_company(api, rofr_required=True, rofr_window_days=30)

    probes = dict(_read_probes(api))
    probes.update(_action_probes(api))
    probes["rofr_notice"] = _refusal_notice_probe(api, company["id"])
    probes["tower_company"] = _body_reference_probe(api)

    assert len(probes) == 13, f"expected thirteen entity types probed, got {sorted(probes)}"

    codes = []
    for label, response in probes.items():
        assert response.status_code == 404, (
            f"the {label} probe must be 404, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["response_type"] == "error", f"the {label} probe must return an error envelope"
        codes.append(body["data"]["error_id"])

    assert_pairwise_distinct(codes, "not-found codes across the thirteen entity types")
    known = {member.value for member in ApiErrorId}
    unknown = [code for code in codes if code not in known]
    assert not unknown, f"codes outside the declared catalogue: {unknown}"
