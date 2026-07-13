"""Access control: authentication, endpoint authorization across the six peer roles,
and the Customer role's entity-backed ownership rule."""

from test_helpers import (
    NO_AUTH_HEADERS,
    ApiErrorId,
    create_frame_payload,
    drive_lab_order_to_shipped,
    make_customer_headers,
    new_customer,
    new_prescription,
    read_lab_order,
    read_prescription,
    setup_confirmed_order,
    setup_order_scenario,
    validate_error,
)
from test_helpers.fixtures import BENEFITS, LAB, LOW_POWER_RX


def test_a_request_with_no_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API carries two mandatory headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the capacity in which that
    principal acts."
    PRD §2.1: "A request that omits either header, or that presents an `X-User-Role` value
    outside those six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "The system evaluates checks in the following fixed priority order and reports the
    **first** failure it encounters; later checks are never reached."

    Authentication sits above path existence, so an unknown order id still yields 401, not 404.

    Design: Corner/rbac/get_order_missing_auth_headers_returns_unauthenticated
    """
    resp = api.get_order("33333333-3333-4333-8333-333333333333", NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_a_customer_cannot_verify_their_own_prescription(api):
    """PRD §2.1: "A request that is well-authenticated but whose role does not appear in the
    authorized-role list for the endpoint it targets is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §3.2: "An `OpticianVerifier` then rules on a `SUBMITTED` prescription by supplying a
    `decision`."

    Verification is the optician's alone — owning the prescription does not confer it.

    Design: Corner/rbac/customer_cannot_verify_a_prescription
    """
    customer = new_customer(full_name="Self Verify", email="self@example.com")
    rx = new_prescription(customer["id"], **LOW_POWER_RX)

    resp = api.verify_prescription(
        rx["id"], {"decision": "VERIFIED"}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_prescription(rx["id"])["status"] == "SUBMITTED"


def test_a_lab_technician_cannot_hand_over_the_lab_order_they_shipped(api):
    """PRD §2.1: "A request that is well-authenticated but whose role does not appear in the
    authorized-role list for the endpoint it targets is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §3.7: "Handover is a `StoreAssociate`'s act — the BOPIS counter or the courier
    confirmation — and it advances a `SHIPPED` lab order to `DELIVERED`."

    Peer-role separation: the technician who shipped the very same lab order may not deliver it.

    Design: Corner/rbac/lab_technician_cannot_deliver_a_lab_order
    """
    scenario = setup_confirmed_order(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
    )
    shipped = drive_lab_order_to_shipped(scenario["lab_order"]["id"])

    resp = api.deliver_lab_order(shipped["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = read_lab_order(shipped["id"])
    assert after["status"] == "SHIPPED"
    assert after["delivered_at"] is None


def test_a_customer_cannot_read_another_customers_order(api):
    """PRD §2.1: "Concretely, a `Customer` may only read or mutate prescriptions, home try-on
    kits, orders, warranty claims and exam appointments whose `customer_id` equals their own
    `X-User-ID`. A violation of that ownership rule is also reported as `ERR_UNAUTHORIZED`
    (HTTP 403) — the API does not distinguish "not yours" from "not allowed", to avoid leaking
    the existence of other customers' records."

    The snooping customer gets a 403, never a 404.

    Design: Corner/rbac/customer_cannot_read_another_customers_order
    """
    owner_scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
    )
    snooper = new_customer(full_name="Snoop Er", email="snoop@example.com")

    resp = api.get_order(
        owner_scenario["order"]["id"], make_customer_headers(snooper["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_a_benefits_admin_cannot_add_a_frame_to_the_catalog(api):
    """PRD §2.1: "A request that is well-authenticated but whose role does not appear in the
    authorized-role list for the endpoint it targets is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §3.1: "Before anything can be sold, a `PlatformAdmin` populates four catalogs."

    Being an operator role is not enough — catalog writes belong to the PlatformAdmin alone.

    Design: Corner/rbac/benefits_admin_cannot_create_a_frame
    """
    resp = api.create_frame(
        create_frame_payload(sku="FRM-NO", name="Nope", price_cents=9500), BENEFITS
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
