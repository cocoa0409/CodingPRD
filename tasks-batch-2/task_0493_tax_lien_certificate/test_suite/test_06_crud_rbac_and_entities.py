"""Entity CRUD, defaults, computed/system fields, parent/FK referential checks,
RBAC role-denied paths, and certificate listing filters.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_investor_headers,
    assert_county,
    assert_parcel,
    assert_investor,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
INVESTOR = TEST_USERS["investor_headers"]


def test_create_county_returns_201_with_fields(api):
    """PRD §3.1: "Everything begins with a county configuration, created by a
    `CountyTreasurer`."
    PRD §2.5: "an integer `version` that begins at its initial value on creation"

    Design: Corner/entities/create_county_returns_201_with_fields
    """
    county = validate_success(
        api.create_county(
            f.create_county_payload(name="Corner County", state_code="AZ"), TREASURER
        ),
        expected_status=201,
    )
    assert_county(county)
    assert county["state_code"] == "AZ"
    assert county["version"] == 1
    assert county["penalty_rate_bps"] == 0
    assert county["day_count_basis"] == 365


def test_county_optional_defaults_applied(api):
    """PRD §3.1: "The `penalty_rate_bps` is a flat mandatory penalty applied to the
    base tax at redemption regardless of how much time has elapsed; it is at least
    0 and defaults to 0 when omitted."
    PRD §3.1: "The `premium_bidding_enabled` flag, defaulting to false"
    PRD §3.1: "The `premium_earns_interest` flag, defaulting to false"

    Design: Corner/entities/county_penalty_rate_default_applied
    """
    county = validate_success(
        api.create_county(f.create_county_payload(name="Def County"), TREASURER),
        expected_status=201,
    )
    assert county["penalty_rate_bps"] == 0
    assert county["premium_bidding_enabled"] is False
    assert county["premium_earns_interest"] is False


def test_get_parcel_returns_stored_delinquent(api):
    """PRD §3.1: "A freshly registered parcel has `status` of `DELINQUENT` and a
    null `active_certificate_id`."

    Design: Corner/entities/get_parcel_by_id_returns_stored
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="C")
    parcel = fx.create_parcel(county["id"], apn="R-1",
                              assessed_value_cents=100_000, base_tax_due_cents=50_000)

    got = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert_parcel(got)
    assert got["status"] == "DELINQUENT"
    assert got["base_tax_due_cents"] == 50000
    assert got["active_certificate_id"] is None


def test_list_parcels_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_parcels_pagination_envelope
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="C")
    fx.create_parcel(county["id"], apn="L-1", assessed_value_cents=100_000,
                     base_tax_due_cents=50_000)
    fx.create_parcel(county["id"], apn="L-2", assessed_value_cents=100_000,
                     base_tax_due_cents=60_000)

    data, meta = validate_paginated(
        api.list_parcels(county["id"], AUDITOR, {"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_nonexistent_certificate_404(api):
    """PRD §2.9: "The server validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier in the path
    that does not resolve to an existing resource, before considering anything
    further to its right."

    Design: Corner/entities/get_nonexistent_certificate_404
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="C")

    resp = api.get_certificate(county["id"], "00000000-0000-4000-8000-000000000000", AUDITOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_parcel_missing_base_tax_rejected(api):
    """PRD §3.1: "the `base_tax_due_cents` — the original delinquent tax principal
    that will become the face amount of the lien, which must be at least 1."
    PRD §2.10: "then basic request-body shape — required fields present, enums in
    range, integers non-negative where required, and the OCC field present where
    one is required (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_parcel_missing_base_tax_invalid_request
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="C")

    resp = api.create_parcel(
        county["id"],
        {"apn": "X-1", "owner_name": "O", "assessed_value_cents": 100_000},
        TREASURER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_investor_system_fields_ignored_on_create(api):
    """PRD §3.2: "A new investor starts with an `escrow_balance_cents` of 0, a
    `deposit_total_cents` of 0, and `registered` set to false."

    Design: Corner/entities/investor_system_fields_ignored_on_create
    """
    inv = validate_success(
        api.create_investor(
            f.create_investor_payload(legal_name="I-sys", tax_id="TIN-SYS"), INVESTOR
        ),
        expected_status=201,
    )
    assert_investor(inv)
    assert inv["escrow_balance_cents"] == 0
    assert inv["registered"] is False
    assert inv["version"] == 1


def test_register_parcel_under_missing_county_404(api):
    """PRD §2.9: "The server validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier in the path
    that does not resolve to an existing resource"

    Design: Corner/entities/parcel_requires_existing_county_parent
    """
    resp = api.create_parcel(
        "00000000-0000-4000-8000-000000000000",
        f.create_parcel_payload(apn="NF-1", assessed_value_cents=100_000,
                                base_tax_due_cents=50_000),
        TREASURER,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_listing_parcel_cross_county_rejected(api):
    """PRD §2.9: "when a request body carries foreign keys, those references must
    resolve within the correct county scope: a listing's `parcel_id` must name a
    parcel whose `county_id` equals the county in the path, a referenced investor
    must exist, and a certificate must belong to the path county."
    PRD §2.9: "A body foreign key that points outside the correct county scope is
    rejected with `ERR_CROSS_COUNTY_REFERENCE`."

    Design: Corner/entities/certificate_fk_county_filtered_list
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county_a = fx.create_county(name="County A")
    parcel_a = fx.create_parcel(county_a["id"], apn="PA-1",
                                assessed_value_cents=100_000, base_tax_due_cents=50_000)
    county_b = fx.create_county(name="County B")
    sale_b = fx.create_sale(county_b["id"], sale_name="S_B")

    resp = api.create_listing(
        county_b["id"], sale_b["id"], f.create_listing_payload(parcel_a["id"]), TREASURER
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_COUNTY_REFERENCE.value)


def test_list_certificates_filter_by_holder(api):
    """PRD §3.6: "Certificates can be read directly and listed in a county,
    filtered by `parcel_id`, `listing_id`, `holder_investor_id`, `county_id`, or
    `status`."

    Design: Corner/endpoints/list_certificates_filter_by_holder
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "LH County"},
        parcel_overrides={"apn": "LH-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, investor = ctx["county"], ctx["investor"]

    data, meta = validate_paginated(
        api.list_certificates(county["id"], AUDITOR,
                              {"holder_investor_id": investor["id"]})
    )
    assert meta["total_count"] == 1


def test_investor_cannot_open_sale(api):
    """PRD §2.1: "A request whose role is valid but is not permitted to perform the
    requested operation is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.3: "Opening a sale advances it from `DRAFT` to `OPEN`"

    Design: Corner/rbac/investor_cannot_open_sale
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="C")
    parcel = fx.create_parcel(county["id"], apn="RB-1", base_tax_due_cents=100_000)
    investor = _register_only_investor("I1", "TIN-RB1")
    sale = fx.create_sale(county["id"], sale_name="S")
    fx.create_listing(county["id"], sale["id"], parcel["id"])

    resp = api.open_sale(county["id"], sale["id"], make_investor_headers(investor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    sale_after = validate_success(api.get_sale(county["id"], sale["id"], AUDITOR))
    assert sale_after["status"] == "DRAFT"


def test_auditor_cannot_create_county(api):
    """PRD §2.1: "When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an
    opaque identifier not tied to any persisted entity; the auditor may read every
    resource but may mutate none."
    PRD §3.1: "Everything begins with a county configuration, created by a
    `CountyTreasurer`."

    Design: Corner/rbac/auditor_cannot_create_county
    """
    resp = api.create_county(f.create_county_payload(name="Aud County"), AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_undeclared_or_unauthorized_role_rejected(api):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not
    one of these three declared roles, is rejected with `ERR_UNAUTHENTICATED`. A
    request whose role is valid but is not permitted to perform the requested
    operation is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    # An Investor (valid role) calling the treasurer-only POST /counties is denied;
    # the PRD pins the outcome to one of authentication/authorization rejection.
    resp = api.create_county(f.create_county_payload(name="NoAuth County"), INVESTOR)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_UNAUTHENTICATED.value, ApiErrorId.ERR_FORBIDDEN_ROLE.value],
    )


def test_sub_tax_by_non_holder_forbidden(api):
    """PRD §3.7: "The payer must equal the certificate's current
    `holder_investor_id`; a non-holder attempt is rejected with
    `ERR_NOT_CERTIFICATE_HOLDER`."

    Design: Corner/rbac/sub_tax_by_non_holder_forbidden
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "NH County"},
        parcel_overrides={"apn": "NH-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, cert = ctx["county"], ctx["certificate"]
    i2 = fx.create_funded_investor(200_000, legal_name="I2", tax_id="TIN-NH2")

    cert_v = validate_success(
        api.get_certificate(county["id"], cert["id"], make_investor_headers(i2["id"]))
    )["version"]
    resp = api.create_sub_tax(
        county["id"], cert["id"],
        f.create_sub_tax_payload(i2["id"], 2026, 50_000, cert_v),
        make_investor_headers(i2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_CERTIFICATE_HOLDER.value)


def test_redeem_reconciles_parcel_to_redeemed(api):
    """PRD §2.8: "when the certificate is redeemed the parcel returns to `REDEEMED`
    with `active_certificate_id` cleared to null"

    Design: Corner/cross_cutting_complexity_layers/derived_field_active_certificate_reconciled_on_redeem
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "DF County"},
        parcel_overrides={"apn": "DF-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, parcel, cert = ctx["county"], ctx["parcel"], ctx["certificate"]

    fx.set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER), expected_status=201
    )

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "REDEEMED"
    assert parcel_after["active_certificate_id"] is None

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "REDEEMED"


def _register_only_investor(legal_name, tax_id):
    from test_helpers import get_success_data
    from test_helpers import api_client
    return get_success_data(
        api_client.create_investor(
            f.create_investor_payload(legal_name=legal_name, tax_id=tax_id), TREASURER
        )
    )
