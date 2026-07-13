"""Not-found error catalogue coverage and top-level RBAC/authentication gates."""
from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_hazard_plan_payload,
)


def test_not_found_ids_across_core_entities(api, admin_headers, clinical_headers, logistics_headers):
    """PRD §2.6: "...every resource identifier that appears in the URL path is
    confirmed to exist — the corresponding not-found error
    (`ERR_HAZARD_PLAN_NOT_FOUND`, `ERR_POD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`,
    `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`, `ERR_COUNTERMEASURE_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`,
    `ERR_DISPENSING_EVENT_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`, or
    `ERR_SITUATION_REPORT_NOT_FOUND`) is returned for the first path identifier
    that fails to resolve."
    PRD §2.6: "Fifth, every foreign key referenced in the request body —
    `hazard_plan_id`, `pod_id`, `staff_member_id`, `countermeasure_id`,
    `partner_pod_id` — is confirmed to reference an existing resource, using
    the same not-found error family."

    Design: Corner/errors/not_found_ids_across_core_entities
    """
    validate_error(
        api.get_hazard_plan(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_HAZARD_PLAN_NOT_FOUND
    )
    validate_error(api.get_pod(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_POD_NOT_FOUND)
    validate_error(
        api.verify_staff_credential(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND,
    )
    validate_error(
        api.confirm_shift_assignment(NON_EXISTENT_UUID, clinical_headers),
        ApiErrorId.ERR_SHIFT_ASSIGNMENT_NOT_FOUND,
    )
    validate_error(
        api.create_inventory_lot(
            {
                "countermeasure_id": NON_EXISTENT_UUID, "lot_number": "LOT-NF1",
                "on_hand_quantity": 10, "expiration_date": "2027-01-01T00:00:00Z",
            },
            logistics_headers,
        ),
        ApiErrorId.ERR_COUNTERMEASURE_NOT_FOUND,
    )
    validate_error(
        api.get_inventory_lot(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND
    )
    validate_error(
        api.get_allocation_request(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_ALLOCATION_REQUEST_NOT_FOUND,
    )
    validate_error(
        api.get_dispensing_event(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_DISPENSING_EVENT_NOT_FOUND,
    )
    validate_error(api.get_drill(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_DRILL_NOT_FOUND)
    validate_error(
        api.get_situation_report(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_SITUATION_REPORT_NOT_FOUND,
    )


def test_forbidden_role_cannot_create_hazard_plan(api, logistics_headers):
    """PRD §4 endpoint table: "POST | `/hazard-plans` | Create a
    hazard/scenario plan | PublicHealthAdmin".
    PRD §2.1: "A request from a recognized role attempting an operation
    outside that role's authorized surface is rejected with `ERR_FORBIDDEN`
    (403)."

    Design: Corner/rbac/forbidden_role_cannot_create_hazard_plan
    """
    payload = create_hazard_plan_payload(
        hazard_type="OUTBREAK_OTHER", title="Forbidden Plan",
        jurisdiction_code="CTY38", target_population=400,
    )
    res = api.create_hazard_plan(payload, logistics_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_unauthenticated_missing_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value outside this set of five, is rejected with
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/unauthenticated_missing_headers_rejected
    """
    res = api.list_hazard_plans(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
