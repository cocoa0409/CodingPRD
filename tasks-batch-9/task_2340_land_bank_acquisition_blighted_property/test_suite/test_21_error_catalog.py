"""
The rejections that name a resource or a missing credential.

Two families are exercised here: the 404 family, where every resource names
itself when the identifier that should have found it matches nothing, and the
401 family, where a request that never established who is calling is turned away
before anything else about it is considered.
"""

from test_helpers import (
    CLERK_1,
    DISP_1,
    INTAKE_1,
    INV_1,
    ROLE_INTAKE_OFFICER,
    TREAS_1,
    ApiErrorId,
    NON_EXISTENT_UUID,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


# ── the 404 family names the resource that was not found ───────────────────
def test_unknown_path_ids_on_reads_name_their_own_resource(api):
    """
    Reading a packet, an order, an application, an agreement, an applicant or a
    funding source by an identifier that was never minted answers with the 404
    that names that resource.

    Identifiers in a request path are resolved strictly left to right, and the first one that matches no record ends the request with a 404 naming that resource: an unknown parcel yields `ERR_PROPERTY_NOT_FOUND`, an unknown acquisition packet `ERR_PACKET_NOT_FOUND`, an unknown title action `ERR_TITLE_ACTION_NOT_FOUND`, an unknown maintenance order `ERR_ORDER_NOT_FOUND`, an unknown demolition run `ERR_RUN_NOT_FOUND`, an unknown disposition application `ERR_APPLICATION_NOT_FOUND`, an unknown development agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown applicant `ERR_APPLICANT_NOT_FOUND` and an unknown funding source `ERR_FUNDING_SOURCE_NOT_FOUND`.

    Design: Corner/errors/unknown_path_resource_not_found_family_returns_resource_specific_ids
    """
    validate_error(
        api.get_acquisition_packet(NON_EXISTENT_UUID, CLERK_1),
        ApiErrorId.PACKET_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_maintenance_order(NON_EXISTENT_UUID, INV_1),
        ApiErrorId.ORDER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_disposition_application(NON_EXISTENT_UUID, DISP_1),
        ApiErrorId.APPLICATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_development_agreement(NON_EXISTENT_UUID, CLERK_1),
        ApiErrorId.AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_applicant(NON_EXISTENT_UUID, DISP_1),
        ApiErrorId.APPLICANT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_funding_source(NON_EXISTENT_UUID, TREAS_1),
        ApiErrorId.FUNDING_SOURCE_NOT_FOUND.value,
        404,
    )


def test_unknown_path_ids_on_action_endpoints_are_resolved_before_anything_else(api):
    """
    Adjudicating a title action and executing a demolition run that do not exist
    answer with the 404 that names the title action and the run, rather than
    looking at the body or the state first.

    Identifiers in a request path are resolved strictly left to right, and the first one that matches no record ends the request with a 404 naming that resource: an unknown parcel yields `ERR_PROPERTY_NOT_FOUND`, an unknown acquisition packet `ERR_PACKET_NOT_FOUND`, an unknown title action `ERR_TITLE_ACTION_NOT_FOUND`, an unknown maintenance order `ERR_ORDER_NOT_FOUND`, an unknown demolition run `ERR_RUN_NOT_FOUND`, an unknown disposition application `ERR_APPLICATION_NOT_FOUND`, an unknown development agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown applicant `ERR_APPLICANT_NOT_FOUND` and an unknown funding source `ERR_FUNDING_SOURCE_NOT_FOUND`.

    Design: Corner/errors/unknown_path_resource_not_found_family_returns_resource_specific_ids
    """
    validate_error(
        api.adjudicate_title_action(
            NON_EXISTENT_UUID, {"outcome": "CLEARED"}, INTAKE_1
        ),
        ApiErrorId.TITLE_ACTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.execute_demolition_run(NON_EXISTENT_UUID, INV_1),
        ApiErrorId.RUN_NOT_FOUND.value,
        404,
    )

    # Nothing was written by either refusal.
    parcels, parcel_meta = validate_paginated(api.list_properties(INTAKE_1))
    assert parcel_meta["total_count"] == 0
    assert parcels == []
    orders, order_meta = validate_paginated(api.list_maintenance_orders(INV_1))
    assert order_meta["total_count"] == 0
    assert orders == []


# ── the path identifier is resolved before the body reference ──────────────
def _acquired_parcel_and_an_unrestricted_budget(api):
    """
    One acquired parcel and one unrestricted budget, with no contractor
    registered at all, so a mowing order can carry a dangling contractor.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="FK Order Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    parcel = fixtures.create_property(
        api,
        address="3260 Basswood Ln",
        situs_ward=5,
        lot_area_sqft=10000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )
    fixtures.acquire_property(
        api, parcel["id"], funding_source["id"], donor_name="Basswood Trust"
    )
    return funding_source, fixtures.read_property(api, parcel["id"])


def _mow_order_payload(funding_source_id, contractor_id, expected_property_version):
    """A well-formed mowing order over a one-day window in early August."""
    return factories.maintenance_order_payload(
        contractor_id,
        funding_source_id,
        expected_property_version,
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )


def test_the_unknown_parcel_in_the_path_answers_before_the_unknown_contractor(api):
    """
    A mowing order whose path parcel and whose body contractor are both unknown
    is refused for the parcel, because the path is resolved first.

    Existence of path identifiers, then existence of body references (the 404 family of §2.5).

    Design: Corner/errors/unknown_path_resource_outranks_unknown_body_foreign_key_rejected
    """
    funding_source, parcel = _acquired_parcel_and_an_unrestricted_budget(api)

    response = api.create_maintenance_order(
        NON_EXISTENT_UUID,
        _mow_order_payload(funding_source["id"], NON_EXISTENT_UUID, parcel["version"]),
        INV_1,
    )

    validate_error(response, ApiErrorId.PROPERTY_NOT_FOUND.value, 404)


def test_repairing_the_path_then_surfaces_the_unknown_contractor(api):
    """
    With the parcel in the path repaired, the same order is refused for the
    contractor the body could not resolve, and no money is committed.

    Existence of path identifiers, then existence of body references (the 404 family of §2.5).

    Design: Corner/errors/unknown_path_resource_outranks_unknown_body_foreign_key_rejected
    """
    funding_source, parcel = _acquired_parcel_and_an_unrestricted_budget(api)

    response = api.create_maintenance_order(
        parcel["id"],
        _mow_order_payload(funding_source["id"], NON_EXISTENT_UUID, parcel["version"]),
        INV_1,
    )

    validate_error(response, ApiErrorId.CONTRACTOR_NOT_FOUND.value, 404)

    orders, meta = validate_paginated(api.list_maintenance_orders(INV_1))
    assert meta["total_count"] == 0
    assert orders == []
    ledger = fixtures.read_funding_source(api, funding_source["id"])
    assert ledger["committed_cents"] == 0
    assert ledger["available_cents"] == 900000


# ── authentication is the very first rung of the ladder ────────────────────
def _valid_registration_payload():
    """A parcel registration that is correct in every respect but its headers."""
    return factories.property_payload(
        parcel_id="APN-203270",
        address="3270 Catalpa Ln",
        situs_ward=5,
        lot_area_sqft=6000,
        assessed_value_cents=250000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=3,
    )


def _assert_no_parcel_was_registered(api):
    parcels, meta = validate_paginated(api.list_properties(INTAKE_1))
    assert meta["total_count"] == 0
    assert parcels == []


def test_a_request_without_the_user_id_header_is_unauthenticated(api):
    """
    A parcel registration that declares a role but no acting user is refused as
    unauthenticated.

    If either header is absent, or if `X-User-Role` is not one of the six roles the authority recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401).

    Design: Corner/errors/missing_auth_headers_and_unknown_role_rejected
    """
    headers = {
        "X-User-Role": ROLE_INTAKE_OFFICER,
        "Content-Type": "application/json",
    }

    response = api.post(
        f"{constants.API_PREFIX}/properties",
        json=_valid_registration_payload(),
        headers=headers,
    )

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
    _assert_no_parcel_was_registered(api)


def test_a_request_without_the_user_role_header_is_unauthenticated(api):
    """
    A parcel registration that names an acting user but declares no role is
    refused as unauthenticated.

    If either header is absent, or if `X-User-Role` is not one of the six roles the authority recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401).

    Design: Corner/errors/missing_auth_headers_and_unknown_role_rejected
    """
    headers = {
        "X-User-ID": "intake-1",
        "Content-Type": "application/json",
    }

    response = api.post(
        f"{constants.API_PREFIX}/properties",
        json=_valid_registration_payload(),
        headers=headers,
    )

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
    _assert_no_parcel_was_registered(api)


def test_a_role_the_authority_does_not_recognize_is_unauthenticated(api):
    """
    A parcel registration declaring a role outside the six the authority
    recognizes is refused as unauthenticated rather than as a forbidden role.

    If either header is absent, or if `X-User-Role` is not one of the six roles the authority recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401).

    Design: Corner/errors/missing_auth_headers_and_unknown_role_rejected
    """
    headers = {
        "X-User-ID": "auditor-1",
        "X-User-Role": "CountyAuditor",
        "Content-Type": "application/json",
    }

    response = api.post(
        f"{constants.API_PREFIX}/properties",
        json=_valid_registration_payload(),
        headers=headers,
    )

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
    _assert_no_parcel_was_registered(api)
