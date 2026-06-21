"""RBAC isolation, authentication, foreign-key resolution, release-not-open, and
optimistic-concurrency stale-version rejection.

Translates the non-stub `rbac`, `errors`, and OCC corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_winery_payload, create_shipment_payload, create_release_payload,
    setup_active_product, setup_active_member, setup_active_membership,
    set_clock, create_winery, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── Corner: rbac (non-stub) ───────────────────────────

def test_club_manager_cannot_create_winery(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation per the authorization matrix in
    Section 4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | `/wineries` | Create a bonded winery/brewery premises |
    ComplianceOfficer".

    A ClubManager POST /wineries -> ERR_FORBIDDEN.

    Design: Corner/rbac/club_manager_cannot_create_winery
    """
    res = api.create_winery(create_winery_payload(name="Nope Co", ttb_permit_number="NP-1"), CLM)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_tasting_staff_cannot_open_release(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | `/releases/{releaseId}/transitions` | Open or close a release |
    CellarManager".

    A TastingRoomStaff OPEN_RELEASE -> ERR_FORBIDDEN.

    Design: Corner/rbac/tasting_staff_cannot_open_release
    """
    winery, batch, product = setup_active_product(bottled_bottles=10)
    release = get_success_data(api.create_release(
        create_release_payload(winery["id"], product["id"], pool_bottles=6, per_member_cap=6), CM))
    pv = get_success_data(api.get_product(product["id"], CM))["version"]
    res = api.transition_release(release["id"], {
        "action": "OPEN_RELEASE", "expected_release_version": release["version"],
        "expected_product_version": pv}, TRS)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated with two mandatory
    HTTP headers... If either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A request with no X-User-Role/X-User-ID -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_winery(
        create_winery_payload(name="Anon Co", ttb_permit_number="AN-1"),
        {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Corner: errors (non-stub) ─────────────────────────

def test_fk_not_found_on_shipment_bad_release(api):
    """PRD §2.6: "A body foreign key that does not resolve, or that resolves to a
    resource owned by a different winery, is rejected with `ERR_FK_NOT_FOUND`
    (HTTP 404)."

    POST /shipments with a non-existent release_id -> ERR_FK_NOT_FOUND.

    Design: Corner/errors/fk_not_found_on_shipment_bad_release
    """
    set_clock("2026-06-15T00:00:00Z")
    winery = create_winery(name="Fk Co", ttb_permit_number="FK-1")
    member = setup_active_member(winery["id"], ship_to_state_code="CA")
    membership = setup_active_membership(winery["id"], member["id"], tier="SILVER")
    res = api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"],
                                "00000000-0000-0000-0000-000000000000", 6), CLM)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_release_not_open_on_release_to_closed(api):
    """PRD §3.7: "A release also requires that the drawn release still be `OPEN`,
    failing which it is rejected with `ERR_RELEASE_NOT_OPEN`."

    A SCHEDULED shipment whose release is then CLOSED is rejected on RELEASE with
    ERR_RELEASE_NOT_OPEN.

    Design: Corner/errors/release_not_open_on_release_to_closed
    """
    from test_helpers import setup_open_release
    set_clock("2026-06-15T00:00:00Z")
    winery, product, release = setup_open_release(
        pool_bottles=6, per_member_cap=6, bottled_bottles=20,
        product_overrides={"list_price_cents": 5000})
    member = setup_active_member(winery["id"], ship_to_state_code="CA")
    membership = setup_active_membership(winery["id"], member["id"], tier="SILVER")
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 6), CLM))
    # Close the release after scheduling.
    rv = get_success_data(api.get_release(release["id"], CM))["version"]
    get_success_data(api.transition_release(
        release["id"], {"action": "CLOSE_RELEASE", "expected_release_version": rv}, CM))
    res = api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM)
    validate_error(res, "ERR_RELEASE_NOT_OPEN", expected_status=409)


# ─── Corner: cross_cutting_complexity_layers OCC (non-stub) ───

def test_occ_stale_winery_version_on_reinstate(api):
    """PRD §2.10: "a premises suspend or reinstate must carry `expected_winery_version`
    matching the target winery's current `version`. If an intervening suspension or
    reinstatement has already advanced the winery's version since the client last
    read it, the request is rejected with `ERR_STALE_WINERY_VERSION` (HTTP 412)".
    PRD §3.1: "Each successful transition increments the winery's `version` by one."

    SUSPEND advances version 1 -> 2; a REINSTATE still carrying expected version 1
    is stale -> ERR_STALE_WINERY_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_winery_version_on_reinstate
    """
    winery = create_winery(name="Occ Co", ttb_permit_number="OC-1")
    wv0 = winery["version"]
    get_success_data(api.transition_winery(
        winery["id"], {"action": "SUSPEND", "expected_winery_version": wv0}, CO))
    res = api.transition_winery(
        winery["id"], {"action": "REINSTATE", "expected_winery_version": wv0}, CO)
    validate_error(res, "ERR_STALE_WINERY_VERSION", expected_status=412)
