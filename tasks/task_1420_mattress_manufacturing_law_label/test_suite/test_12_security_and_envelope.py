"""Auth headers, path existence ordering, and domain 404s (PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_error,
)

PM = TEST_USERS["plant_manager_headers"]


def test_request_without_role_header_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing, or if the role value is not
    one of the declared role names, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    # X-User-ID present, X-User-Role absent.
    resp = api.list_models({"X-User-ID": "pm-1", "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_unknown_ids_return_resource_specific_404(api):
    """PRD §2.8: "Unknown ids produce the resource's dedicated 404:
    `ERR_MODEL_NOT_FOUND`, `ERR_BOM_LINE_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`,
    `ERR_RETAILER_NOT_FOUND`, `ERR_FOAM_BATCH_NOT_FOUND`,
    `ERR_QUILT_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    or `ERR_INTAKE_NOT_FOUND`."

    Design: Corner/errors/not_found_errors_across_resources
    """
    retailer = api.get_retailer(NON_EXISTENT_UUID, PM)
    validate_error(retailer, ApiErrorId.ERR_RETAILER_NOT_FOUND)

    batch = api.get_foam_batch(NON_EXISTENT_UUID, PM)
    validate_error(batch, ApiErrorId.ERR_FOAM_BATCH_NOT_FOUND)

    claim = api.get_warranty_claim(NON_EXISTENT_UUID, PM)
    validate_error(claim, ApiErrorId.ERR_CLAIM_NOT_FOUND)


def test_nested_path_resolves_parent_before_child(api):
    """PRD §2.8: "3. Path resource existence, resolved left-to-right — on
    nested paths the parent `modelId` is resolved before any `lineId`,
    `certId`, or `labelId` beneath it, and `retailerId` before any ledger
    scope beneath it."

    Design: Corner/validations/path_existence_checked_left_to_right
    """
    resp = api.list_bom_lines(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_MODEL_NOT_FOUND)
