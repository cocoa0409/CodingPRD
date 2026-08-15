"""Authentication, role authorization, ownership scope, and typed 404s."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_agreement_payload,
    create_co_manufacturer_payload,
    create_product_payload,
    create_promo_window_payload,
    get_success_data,
    make_coman_headers,
    set_clock,
    validate_error,
)

PM = TEST_USERS["plant_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
QT = TEST_USERS["quality_tech_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        name outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.9: "Authentication: `X-User-Role` and `X-User-ID` are present
        and the role is declared (else `ERR_UNAUTHENTICATED`)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.get_product(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_route_planner_cannot_create_product(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized
        for the targeted endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /snack-mfg/products is authorized for PlantManager only.

        Design: Corner/validations/route_planner_cannot_create_product
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_product(create_product_payload(name="Nope"), RP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_quality_tech_cannot_create_promo_window(self, api):
        """PRD §2.1: "A `QualityTechnician` is the quality gatekeeper: swab
        recording, changeover validation, weight checks, hold release, and
        quality disposition."
        PRD §4: POST /snack-mfg/promo-windows is authorized for PlantManager
        only.

        Design: Corner/rbac/quality_tech_cannot_create_promo_window
        """
        product = get_success_data(
            api.create_product(create_product_payload(), PM)
        )
        resp = api.create_promo_window(
            create_promo_window_payload(product["id"]), QT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestCoManufacturerOwnershipScope:
    def test_coman_cannot_read_other_agreement(self, api):
        """PRD §2.1: "When `X-User-Role` is `CoManufacturer`, `X-User-ID` is
        the `id` of the acting `CoManufacturer` entity; ownership checks on any
        agreement or slot compare the agreement's `co_manufacturer_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/validations/coman_cannot_read_other_agreement
        """
        cm_a = get_success_data(
            api.create_co_manufacturer(create_co_manufacturer_payload(name="TollCo A"), PM)
        )
        cm_b = get_success_data(
            api.create_co_manufacturer(create_co_manufacturer_payload(name="TollCo B"), PM)
        )
        agreement = get_success_data(api.create_agreement(
            create_agreement_payload(cm_a["id"]), PM,
        ))
        resp = api.get_agreement(agreement["id"], make_coman_headers(cm_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestTypedNotFound:
    def test_not_found_sweep_returns_typed_404s(self, api):
        """PRD §2.9: "The first missing resource produces its specific 404:
        `ERR_PRODUCT_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_CHANGEOVER_NOT_FOUND`, `ERR_OIL_NOT_FOUND`,
        `ERR_MOVEMENT_NOT_FOUND`, `ERR_WEIGHT_CHECK_NOT_FOUND`,
        `ERR_SHIPMENT_NOT_FOUND`, `ERR_PROMO_WINDOW_NOT_FOUND`,
        `ERR_DISPLAY_CASE_NOT_FOUND`, `ERR_COMAN_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, or `ERR_SLOT_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_returns_typed_404s
        """
        set_clock("2026-08-01T00:00:00Z")
        base = "00000000-0000-0000-0000-0000000000{:02d}"
        cases = [
            (api.get_product, base.format(1), ApiErrorId.ERR_PRODUCT_NOT_FOUND),
            (api.get_line, base.format(2), ApiErrorId.ERR_LINE_NOT_FOUND),
            (api.get_run, base.format(3), ApiErrorId.ERR_RUN_NOT_FOUND),
            (api.get_changeover, base.format(4), ApiErrorId.ERR_CHANGEOVER_NOT_FOUND),
            (api.get_fryer_oil, base.format(5), ApiErrorId.ERR_OIL_NOT_FOUND),
            (api.get_oil_movement, base.format(6), ApiErrorId.ERR_MOVEMENT_NOT_FOUND),
            (api.get_weight_check, base.format(7), ApiErrorId.ERR_WEIGHT_CHECK_NOT_FOUND),
            (api.get_shipment, base.format(8), ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
            (api.get_promo_window, base.format(9), ApiErrorId.ERR_PROMO_WINDOW_NOT_FOUND),
            (api.get_display_case, base.format(10), ApiErrorId.ERR_DISPLAY_CASE_NOT_FOUND),
            (api.get_co_manufacturer, base.format(11), ApiErrorId.ERR_COMAN_NOT_FOUND),
            (api.get_agreement, base.format(12), ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api.get_slot, base.format(13), ApiErrorId.ERR_SLOT_NOT_FOUND),
        ]
        for getter, missing_id, error_id in cases:
            resp = getter(missing_id, PM)
            validate_error(resp, error_id, 404)
