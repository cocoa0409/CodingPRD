"""Validation basics: auth context, required fields, ownership (PRD 2.1, 2.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]

MISSING = "11111111-1111-1111-1111-111111111111"


def test_missing_auth_header_returns_400(api):
    """PRD 2.1: "Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    # No identity headers at all: authentication precedes existence, so even a
    # non-existent lawn id must surface the 400 auth error, not a 404.
    resp = api.get_lawn(MISSING, headers={})
    th.validate_error(
        resp, th.ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    )


def test_lawn_missing_required_field_returns_invalid_request(api):
    """PRD 2.8: "Before the ordered checks below, every request is screened for basic well-formedness: a missing required field, a type mismatch, an invalid enum member, or a `next_ship_date` left absent while `auto_ship` is true is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD 3.3: "A customer onboards a property by creating a lawn profile with a `customer_id` that must equal the caller's `X-User-ID`, a human `label` such as "Front yard", the `lawn_size_sqm` area in square meters — which must be greater than zero and which determines the pricing tier used later for shipments — a `grass_type` of `COOL_SEASON`, `WARM_SEASON`, or `MIXED`, and a `region` key that the weather gate will match against advisories."

    Design: Corner/validations/lawn_missing_required_field_returns_invalid_request
    """
    customer = th.register_customer(email="v2@x.com", full_name="V Two")
    payload = th.lawn_payload(customer["id"])
    del payload["lawn_size_sqm"]
    th.validate_error(
        api.create_lawn(payload, th.make_customer_headers(customer["id"])),
        th.ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_ownership_mismatch_on_foreign_lawn_patch(api):
    """PRD 2.1: "A failed ownership comparison is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD 3.3: "Archiving a lawn is the customer's own action: patching the lawn with `status` set to `ARCHIVED`. The same patch endpoint also updates `label` and `region`. Archiving requires ownership and requires that no application task of the lawn sits in `SCHEDULED`, `FROZEN`, or `AWAITING_DELIVERY`; open applications block the archive with `ERR_LAWN_HAS_OPEN_APPLICATIONS` (HTTP 409)."

    Design: Corner/validations/ownership_mismatch_on_foreign_lawn_patch
    """
    owner = th.register_customer(email="v3a@x.com", full_name="A")
    stranger = th.register_customer(email="v3b@x.com", full_name="B",
                                    climate_zone="WARM")
    lawn = th.create_lawn(owner)

    th.validate_error(
        api.patch_lawn(lawn["id"], {"label": "Hijacked"},
                       th.make_customer_headers(stranger["id"])),
        th.ApiErrorId.ERR_OWNERSHIP_MISMATCH,
    )
    fetched = th.validate_success(api.get_lawn(lawn["id"], ADMIN))
    assert fetched["label"] == "Front", "a rejected patch changes nothing"
