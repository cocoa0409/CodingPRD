"""Role-based access control: exclusive operations and entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    get_contract,
    get_order,
    make_application,
    make_contract,
    make_faire_day,
    make_performer,
    make_season,
    make_shift,
    make_vendor,
    setup_paid_day_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, DIRECTOR, OPERATOR, VENDOR_CO
from test_helpers.test_users import (
    make_guest_headers,
    make_performer_headers,
    make_vendor_headers,
    make_volunteer_headers,
)


def test_performer_cannot_offer_contract(api):
    """PRD §2.1: "An attempt to perform an operation outside the caller's permitted
    set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)"
    PRD §4: `POST /cast-contracts/{id}/offer` is authorized for CastDirector only.

    Design: Corner/rbac/performer_cannot_offer_contract
    """
    season = make_season(name="RBAC Revel A")
    performer = make_performer(stage_name="Quinn", act_type="ROVING",
                               base_day_rate_cents=8000)
    contract = make_contract(season["id"], performer["id"],
                             offered_day_rate_cents=8000, guaranteed_days=1,
                             required_rehearsal_hours=0)

    res = api.offer_contract(
        contract["id"], {}, make_performer_headers(performer["id"])
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_contract(contract["id"])["status"] == "DRAFT"


def test_vendor_cannot_decide_own_application(api):
    """PRD §2.1: "An attempt to perform an operation outside the caller's permitted
    set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)"
    PRD §4: `POST /vendor-applications/{id}/decide` is authorized for
    VendorCoordinator only.

    Design: Corner/rbac/vendor_cannot_decide_own_application
    """
    season = make_season(name="RBAC Revel B")
    vendor = make_vendor(business_name="Rope Makers", category="ARTISAN")
    application = make_application(season["id"], vendor["id"], 64, "MEADOW")

    res = api.decide_application(
        application["id"],
        {"craft_score": 10, "authenticity_score": 10, "safety_score": 10,
         "outcome": "JURIED_IN"},
        make_vendor_headers(vendor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    current = validate_success(api.get_vendor_application(application["id"], ANY), 200)
    assert current["status"] == "JURY_REVIEW"


def test_guest_cannot_refund_order(api):
    """PRD §2.1: "An attempt to perform an operation outside the caller's permitted
    set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)"
    PRD §4: `POST /ticket-orders/{id}/refund` is authorized for GateAgent only.

    Design: Corner/rbac/guest_cannot_refund_order
    """
    season, day, order = setup_paid_day_order(
        quantity=1, buyer_email="g-rbac@example.com"
    )
    res = api.refund_order(
        order["id"], {"refund_cents": 500}, make_guest_headers("g-rbac@example.com")
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_order(order["id"])["refunded_cents"] == 0


def test_performer_cannot_accept_others_contract(api):
    """PRD §2.1: "When `X-User-Role` is `Performer`, `X-User-ID` is the `id` of the
    acting Performer; ownership checks on any resource that references a Performer
    compare the resource's foreign-key field to `X-User-ID` — concretely, a
    performer may counter or accept only the cast contract whose `performer_id`
    equals their `X-User-ID`."
    PRD §2.1: "where a workflow declares resource ownership, a caller whose identity
    does not match the owner is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/performer_cannot_accept_others_contract
    """
    season = make_season(name="RBAC Revel D")
    performer_a = make_performer(stage_name="Rosa", base_day_rate_cents=8000)
    performer_b = make_performer(stage_name="Stefan", act_type="COMBAT",
                                 base_day_rate_cents=8500)
    contract = make_contract(season["id"], performer_a["id"],
                             offered_day_rate_cents=8000, guaranteed_days=1,
                             required_rehearsal_hours=0)
    validate_success(api.offer_contract(contract["id"], {}, DIRECTOR), 200)

    res = api.accept_contract(contract["id"], make_performer_headers(performer_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    assert get_contract(contract["id"])["status"] == "OFFERED"


def test_volunteer_shift_cancel_ownership(api, volunteer_coordinator_headers):
    """PRD §3.8: "Cancellation is shared between the volunteer and the coordinator:
    the caller must either own the shift — `X-User-ID` equal to the shift's
    `volunteer_handle` — or act as a `VolunteerCoordinator`, else
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/volunteer_shift_cancel_ownership
    """
    season = make_season(name="RBAC Revel E")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    shift_m = make_shift(season["id"], day["id"], "vol-m", "GATE",
                         "2026-06-06T08:00:00Z", "2026-06-06T12:00:00Z")
    shift_n = make_shift(season["id"], day["id"], "vol-n", "INFO",
                         "2026-06-06T12:00:00Z", "2026-06-06T16:00:00Z")

    # A different volunteer's handle does not own the shift.
    res = api.cancel_shift(shift_m["id"], make_volunteer_headers("vol-n"))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    # The owner cancels their own shift.
    cancelled_own = validate_success(
        api.cancel_shift(shift_m["id"], make_volunteer_headers("vol-m")), 200
    )
    assert cancelled_own["status"] == "CANCELLED"

    # The coordinator shares the operation without an ownership check.
    cancelled_co = validate_success(
        api.cancel_shift(shift_n["id"], volunteer_coordinator_headers), 200
    )
    assert cancelled_co["status"] == "CANCELLED"
