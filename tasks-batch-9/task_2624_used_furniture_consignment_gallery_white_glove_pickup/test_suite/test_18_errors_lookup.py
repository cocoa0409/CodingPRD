"""Who is asking, and does the thing they name exist at all."""

from test_helpers import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    LOGISTICS_COORDINATOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    total_count,
    validate_error,
)

ROLE_ONLY_HEADERS = {
    "X-User-Role": "GalleryManager",
    "Content-Type": "application/json",
}

def test_a_request_with_a_missing_x_user_id_header_returns_unauthenticated():
    """No principal at all is answered before any question of permission.

    PRD 2.1: "Both are mandatory on every endpoint, including read endpoints. If either
    header is absent, or if `X-User-Role` is not exactly one of the seven role names below,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.9: "Both headers present and `X-User-Role` one of the seven declared roles, on
    every endpoint — otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/a_request_with_a_missing_x_user_id_header_returns_unauthenticated
    """
    anonymous = api_client.list_consignors(ROLE_ONLY_HEADERS)
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    identified = api_client.list_consignors(GALLERY_MANAGER)
    assert identified.status_code == 200, (
        f"Expected the same call with a principal to be served, "
        f"got {identified.status_code}: {identified.text}"
    )
    assert total_count(identified) == 0, (
        f"Expected an empty register, got {total_count(identified)}"
    )


def test_reading_an_unknown_consignor_id_returns_consignor_not_found():
    """A well-formed id naming no account is a 404, not a validation complaint.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "The reported code is selected by which segment failed:
    `ERR_CONSIGNOR_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PICKUP_JOB_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
    `ERR_AUDIT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/reading_an_unknown_consignor_id_returns_consignor_not_found
    """
    response = api_client.get_consignor(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_CONSIGNOR_NOT_FOUND, 404)


def test_reading_an_unknown_buyer_id_returns_buyer_not_found():
    """The register's customers have their own not-found rather than the consignors'.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "The reported code is selected by which segment failed:
    `ERR_CONSIGNOR_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PICKUP_JOB_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
    `ERR_AUDIT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/reading_an_unknown_buyer_id_returns_buyer_not_found
    """
    response = api_client.get_buyer(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_BUYER_NOT_FOUND, 404)


def test_reading_an_unknown_truck_id_returns_truck_not_found():
    """The truck's not-found is reachable from a plain read of the fleet.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "The reported code is selected by which segment failed:
    `ERR_CONSIGNOR_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PICKUP_JOB_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
    `ERR_AUDIT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/reading_an_unknown_truck_id_returns_truck_not_found
    """
    response = api_client.get_truck(NON_EXISTENT_UUID, LOGISTICS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_TRUCK_NOT_FOUND, 404)


def test_reading_an_unknown_crew_id_returns_crew_not_found():
    """Both scheduling resources are finite, and each has its own not-found.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "The reported code is selected by which segment failed:
    `ERR_CONSIGNOR_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PICKUP_JOB_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
    `ERR_AUDIT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/reading_an_unknown_crew_id_returns_crew_not_found
    """
    response = api_client.get_crew(NON_EXISTENT_UUID, LOGISTICS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_CREW_NOT_FOUND, 404)


def test_reading_an_unknown_zone_id_returns_zone_not_found():
    """The zone's not-found serves the path form as well as the body form.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "Because the path is checked first, a path id and a body foreign key are
    never both reported."

    PRD 2.9: "The reported code is selected by which segment failed:
    `ERR_CONSIGNOR_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PICKUP_JOB_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
    `ERR_AUDIT_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/reading_an_unknown_zone_id_returns_zone_not_found
    """
    response = api_client.get_zone(NON_EXISTENT_UUID, FLOOR_OPERATOR)
    validate_error(response, ApiErrorId.ERR_ZONE_NOT_FOUND, 404)


def test_reading_an_unknown_pickup_job_id_returns_pickup_job_not_found():
    """The job must exist before anyone can complain about the state it is in.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "they simply run after positions 1 through 6 on their own endpoints"

    PRD 2.9: "the pickup job is in `SCHEDULED` when item attachment, completion or
    cancellation is requested, otherwise `ERR_PICKUP_JOB_STATE_INVALID` (409)"

    Design: Corner/errors/reading_an_unknown_pickup_job_id_returns_pickup_job_not_found
    """
    response = api_client.get_pickup_job(NON_EXISTENT_UUID, LOGISTICS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_PICKUP_JOB_NOT_FOUND, 404)


def test_reading_an_unknown_sale_id_returns_sale_not_found():
    """The sale's not-found is the same code a delivery order's body key would draw.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "an unresolvable `sale_id` answers `ERR_SALE_NOT_FOUND`, and an unresolvable
    `delivery_order_id` answers `ERR_DELIVERY_ORDER_NOT_FOUND`"

    Design: Corner/errors/reading_an_unknown_sale_id_returns_sale_not_found
    """
    response = api_client.get_sale(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_SALE_NOT_FOUND, 404)


def test_reading_an_unknown_delivery_order_id_returns_delivery_order_not_found():
    """A delivery order hangs off a sale but keeps a not-found of its own.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "an unresolvable `sale_id` answers `ERR_SALE_NOT_FOUND`, and an unresolvable
    `delivery_order_id` answers `ERR_DELIVERY_ORDER_NOT_FOUND`"

    Design: Corner/errors/reading_an_unknown_delivery_order_id_returns_delivery_order_not_found
    """
    response = api_client.get_delivery_order(NON_EXISTENT_UUID, LOGISTICS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_DELIVERY_ORDER_NOT_FOUND, 404)


def test_reading_an_unknown_claim_id_returns_claim_not_found():
    """The claim must exist before its from-state can be judged.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "The claim's `status` is the from-state the requested action needs —
    `SUBMITTED` for an information request and for adjudication, `INFO_REQUESTED` for a
    resubmission — on all three of those endpoints. Otherwise `ERR_CLAIM_STATE_INVALID`
    (409)."

    Design: Corner/errors/reading_an_unknown_claim_id_returns_claim_not_found
    """
    response = api_client.get_damage_claim(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)


def test_approving_an_unknown_audit_id_returns_audit_not_found():
    """The count has no single read, so its not-found surfaces through the approval.

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    PRD 2.9: "they simply run after positions 1 through 6 on their own endpoints"

    PRD 2.9: "the shrinkage audit is in `COUNTED` when write-off approval is requested,
    otherwise `ERR_AUDIT_STATE_INVALID` (409)"

    Design: Corner/errors/approving_an_unknown_audit_id_returns_audit_not_found
    """
    response = api_client.approve_write_off(NON_EXISTENT_UUID, GALLERY_MANAGER)
    validate_error(response, ApiErrorId.ERR_AUDIT_NOT_FOUND, 404)
