"""Role-based access control and entity-backed ownership scope."""
from test_helpers import (
    ApiErrorId,
    create_buyer,
    create_buyer_payload,
    create_contract,
    create_grower,
    create_lot,
    create_lot_payload,
    make_buyer_headers,
    make_grower_headers,
    make_intake_headers,
    make_lab_headers,
    make_admin_headers,
    build_user_headers,
    validate_error,
    validate_success,
)


class TestRoleExclusiveDeny:
    def test_grower_cannot_create_lots_forbidden(self, api):
        """PRD (User and Role-Based Access Control): "A request whose role is
        not permitted for the targeted endpoint ... is rejected with
        ERR_FORBIDDEN (HTTP 403)." PRD (Endpoint Definitions): POST /lots is
        authorized for IntakeOperator only.

        Design: Corner/rbac/grower_cannot_create_lots_forbidden
        """
        grower = create_grower()
        resp = api.create_lot(
            create_lot_payload(grower_id=grower["id"], gross_weight_lbs=1000),
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_lab_technician_cannot_create_settlement_forbidden(self, api):
        """PRD (User and Role-Based Access Control): "A request whose role is
        not permitted for the targeted endpoint ... is rejected with
        ERR_FORBIDDEN (HTTP 403)." PRD (Endpoint Definitions): POST /settlements
        is authorized for PlantAdmin only.

        Design: Corner/rbac/lab_technician_cannot_create_settlement_forbidden
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=1000)
        resp = api.create_settlement({"lot_id": lot["id"]}, make_lab_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestOwnershipScope:
    def test_grower_ownership_scope_on_lot_read(self, api):
        """PRD (User and Role-Based Access Control): "When X-User-Role is
        Grower, X-User-ID is the id of the acting Grower; ownership checks on
        any resource that references a grower compare the resource's grower_id
        field to X-User-ID, so a grower sees only their own lots and
        settlements." — and a grower asking after another grower's lot hears
        ERR_FORBIDDEN.

        Design: Corner/rbac/grower_ownership_scope_on_lot_read
        """
        g1 = create_grower(name="Riverbend Orchards", ranch_code="RB-01")
        g2 = create_grower(name="Delta Farms", ranch_code="DF-02",
                           base_price_cents_per_lb=247)
        lot1 = create_lot(g1["id"], gross_weight_lbs=1000)
        lot2 = create_lot(g2["id"], variety="Butte", gross_weight_lbs=2000)

        own = validate_success(
            api.get_lot(lot1["id"], make_grower_headers(g1["id"]))
        )
        assert own["id"] == lot1["id"]

        other = api.get_lot(lot2["id"], make_grower_headers(g1["id"]))
        validate_error(other, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_buyer_ownership_scope_on_contract_read(self, api):
        """PRD (User and Role-Based Access Control): "When X-User-Role is Buyer,
        X-User-ID is the id of the acting Buyer; ownership checks compare the
        contract's buyer_id ... to X-User-ID, so a buyer sees only their own
        contracts and shipments."

        Design: Corner/rbac/buyer_ownership_scope_on_contract_read
        """
        b1 = create_buyer(name="Acme Snacks", buyer_code="AC-1")
        b2 = create_buyer(name="NutWorld", buyer_code="NW-2")
        c1 = create_contract(
            b1["id"], product_form="IN_SHELL", size_spec="UNSIZED",
            price_cents_per_lb=150, required_qty_lbs=500,
        )
        c2 = create_contract(
            b2["id"], product_form="KERNEL", size_spec="UNSIZED",
            price_cents_per_lb=300, required_qty_lbs=1000,
        )

        own = validate_success(
            api.get_contract(c1["id"], make_buyer_headers(b1["id"]))
        )
        assert own["id"] == c1["id"]

        other = api.get_contract(c2["id"], make_buyer_headers(b1["id"]))
        validate_error(other, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestUnauthenticated:
    def test_unauthenticated_unknown_role_rejected(self, api):
        """PRD (User and Role-Based Access Control): "A request missing either
        header, or presenting an X-User-Role value outside that declared set, is
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/unauthenticated_unknown_role_rejected
        """
        resp = api.create_grower(
            {"name": "X", "ranch_code": "X-1", "base_price_cents_per_lb": 100},
            build_user_headers("someone", "Nobody"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
