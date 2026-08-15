"""Authentication, authorization, and ownership rules (PRD §2.1, §2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line,
    create_catalog_series_payload,
    create_dealer,
    create_draft_order,
    create_wave,
    create_wave_payload,
    get_success_data,
    make_dealer_rep_headers,
    setup_claim_under_review,
    setup_mn_catalog,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["plant_engineer_headers"]
PL = TEST_USERS["production_lead_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "All interactions with the API must be authenticated through
    two mandatory HTTP headers: `X-User-ID` identifies the acting user, and
    `X-User-Role` specifies their operational capacity. The system recognizes
    six roles, spelled exactly as follows: `DealerRep`, `PlantEngineer`,
    `ProductionLead`, `ShippingCoordinator`, `WarrantyAdjuster`, and
    `PlantManager`. A request with missing headers or an unrecognized role is
    rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.10: "When several violations are present at once, the error returned
    is the one from the earliest stage in this order — later checks never mask
    earlier ones" (authentication is stage 1, before the existence check).

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_order(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_dealer_cannot_release_wave_returns_forbidden(api):
    """PRD §2.1: "Once authenticated, each operation is restricted to designated
    roles; an attempt to perform an action outside the caller's role is rejected
    with `ERR_FORBIDDEN_ROLE`."
    PRD §2.10: "When several violations are present at once, the error returned
    is the one from the earliest stage in this order — later checks never mask
    earlier ones" (authorization is stage 2, before state preconditions).

    Design: Corner/rbac/dealer_cannot_release_wave_returns_forbidden
    """
    dealer = create_dealer()
    wave = create_wave()  # PLANNED — would also fail the release state check
    res = api.release_wave(wave["id"], make_dealer_rep_headers(dealer["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_engineer_cannot_approve_claim_returns_forbidden(api):
    """PRD §2.1: "Once authenticated, each operation is restricted to designated
    roles; an attempt to perform an action outside the caller's role is rejected
    with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/engineer_cannot_approve_claim_returns_forbidden
    """
    env = setup_claim_under_review(component="HARDWARE", coverage_variant="COMPONENT")
    res = api.approve_claim(env["claim"]["id"], {"remedy": "REFUND"}, PE)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    claim = validate_success(api.get_warranty_claim(env["claim"]["id"], PM), 200)
    assert claim["status"] == "UNDER_REVIEW"


def test_dealer_ownership_mismatch_on_confirm(api):
    """PRD §2.1: "When `X-User-Role` is `DealerRep`, `X-User-ID` is the `id` of
    the acting `Dealer`; ownership checks on any resource that references a
    `Dealer` compare the resource's dealer chain to `X-User-ID`, and a mismatch
    is rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/dealer_ownership_mismatch_on_confirm
    """
    cat = setup_mn_catalog()
    dealer_a = cat["dealer"]
    dealer_b = create_dealer(name="B", state="MN")

    rep_a = make_dealer_rep_headers(dealer_a["id"])
    order = get_success_data(api.create_order(
        {"dealer_id": dealer_a["id"], "order_date": "2026-08-02T00:00:00Z"}, rep_a
    ))
    get_success_data(api.add_order_line(
        order["id"],
        {"series_id": cat["series"]["id"], "glass_package_id": cat["glass"]["id"],
         "shape": "RECTANGLE", "width_in": 40, "height_in": 60, "quantity": 1,
         "grid_style": "NONE", "hardware_finish": "STANDARD"},
        rep_a,
    ))

    mismatched = api.confirm_order(order["id"], make_dealer_rep_headers(dealer_b["id"]))
    validate_error(mismatched, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)
    fetched = validate_success(api.get_order(order["id"], PM), 200)
    assert fetched["production_status"] == "DRAFT"

    confirmed = validate_success(api.confirm_order(order["id"], rep_a), 200)
    assert confirmed["production_status"] == "CONFIRMED"


def test_plant_manager_superset_runs_wave_and_catalog_ops(api):
    """PRD §2.1: "The `PlantManager` is the plant administrator: its permission
    set is a superset of every operational role, and it alone controls dealer
    credit, the dealer registry, and the test-driving clock."

    Design: Corner/rbac/plant_manager_superset_runs_wave_and_catalog_ops
    """
    series = validate_success(
        api.create_catalog_series(create_catalog_series_payload(), PM), 201
    )
    assert series["status"] == "ACTIVE"

    wave = validate_success(api.create_wave(create_wave_payload(), PM), 201)
    opened = validate_success(api.open_wave(wave["id"], PM), 200)
    assert opened["status"] == "OPEN"
