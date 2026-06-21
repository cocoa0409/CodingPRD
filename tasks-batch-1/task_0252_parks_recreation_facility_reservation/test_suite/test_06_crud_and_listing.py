"""CRUD, defaults, computed fields, listing/pagination, and reverse-reachability.

Covers corner instances under sections entities and endpoints.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    set_clock, create_facility, create_patron, apply_permit, capture_payment,
    facility_version, grant_permit, setup_granted_permit,
    setup_lottery_round_with_entries,
    assert_facility, assert_patron, assert_permit,
    create_facility_payload, create_patron_payload,
    make_patron_headers, NON_EXISTENT_UUID, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_create_facility_returns_defaults_and_system_fields(api):
    """PRD §3.2: "A facility opens in status OPEN, with granted_permit_count at 0
    and version at 1."
    PRD §3.2: "The buffer_minutes value is a mandatory gap enforced between two
    granted permits on the facility for turnover and cleaning, defaulting to 0. The
    deposit_cents value is the refundable security deposit required to grant a
    permit on the facility, defaulting to 0. The requires_coi flag, defaulting to
    false, marks a facility where a valid certificate of insurance must be on file
    at grant time; when it is set, min_coi_coverage_cents (defaulting to 0) is the
    minimum coverage that certificate must carry."

    Design: Corner/entities/facility_create_returns_defaults_and_system_fields
    """
    res = api.create_facility(create_facility_payload(
        name="Main Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.40, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22), COORD)
    fac = validate_success(res, 201)
    assert_facility(fac)
    assert fac["status"] == "OPEN"
    assert fac["granted_permit_count"] == 0
    assert fac["version"] == 1
    assert fac["buffer_minutes"] == 0
    assert fac["deposit_cents"] == 0
    assert fac["requires_coi"] is False


def test_get_facility_returns_stored_data(api):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD §3.2: "The hourly_rate_cents is the base non-resident hourly rate in cents.
    ... The prime_multiplier is applied to the portion of a booking that falls
    inside the facility's prime window."

    Design: Corner/entities/facility_get_returns_stored_data
    """
    fac = create_facility(
        name="Get Court", facility_type="COURT", hourly_rate_cents=8000,
        resident_discount_pct=0.25, prime_multiplier=2.0,
        prime_start_hour=17, prime_end_hour=21)
    got = validate_success(api.get_facility(fac["id"], COORD), 200)
    assert got["name"] == "Get Court"
    assert got["hourly_rate_cents"] == 8000
    assert got["prime_multiplier"] == 2.0


def test_get_nonexistent_facility_returns_not_found(api):
    """PRD §2.8: "the system validates their existence left-to-right along the path,
    and rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier
    that does not resolve."

    Design: Corner/entities/facility_get_nonexistent_returns_not_found
    """
    res = api.get_facility(NON_EXISTENT_UUID, COORD)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_facility_missing_required_field_returns_validation(api):
    """PRD §2.8: "A request whose body is malformed, omits a required field, or
    supplies an enum or range value outside its allowed set ... is rejected with
    ERR_VALIDATION (HTTP 422)."

    facility_type has no default; omitting it -> ERR_VALIDATION.

    Design: Corner/entities/facility_create_missing_required_field_returns_validation
    """
    res = api.create_facility(
        {"name": "Bad Fac", "hourly_rate_cents": 10000, "resident_discount_pct": 0.40,
         "prime_multiplier": 1.5, "prime_start_hour": 18, "prime_end_hour": 22}, COORD)
    validate_error(res, "ERR_VALIDATION")


def test_create_facility_invalid_enum_returns_validation(api):
    """PRD §3.2: "a facility_type that is one of FIELD, COURT, POOL, or PAVILION."
    PRD §2.8: "supplies an enum or range value outside its allowed set ... is
    rejected with ERR_VALIDATION (HTTP 422)."

    facility_type='STADIUM' is not allowed -> ERR_VALIDATION.

    Design: Corner/entities/facility_create_invalid_enum_returns_validation
    """
    res = api.create_facility(create_facility_payload(
        name="Stadium", facility_type="STADIUM"), COORD)
    validate_error(res, "ERR_VALIDATION")


def test_create_patron_defaults(api):
    """PRD §3.1: "On registration the patron starts in GOOD standing with
    no_show_strikes set to 0, wallet_credit_cents set to 0, and residency_verified
    set to false."

    Design: Corner/entities/patron_create_defaults_standing_good
    """
    res = api.create_patron(create_patron_payload(
        full_name="New P", residency="RESIDENT"), TEST_USERS["patron_headers"])
    patron = validate_success(res, 201)
    assert_patron(patron)
    assert patron["standing"] == "GOOD"
    assert patron["residency_verified"] is False
    assert patron["no_show_strikes"] == 0
    assert patron["wallet_credit_cents"] == 0


def test_permit_quoted_fee_is_computed_from_window_and_rate(api):
    """PRD §3.3: "The provisional usage fee, stored in quoted_fee_cents, is then
    computed forward-looking from that snapshot. ... The non-prime component is the
    non-prime hours multiplied by the effective rate, rounded half up to whole
    cents."
    PRD §3.3: "It resolves to RESIDENT only when the patron's residency is RESIDENT
    and their residency_verified is true at application time; in every other case
    it resolves to NON_RESIDENT."

    NON_RESIDENT, hourly 10000, window 10:00-12:00 (non-prime 2h) -> quoted 20000,
    is_prime_requested false, pricing_residency NON_RESIDENT.

    Design: Corner/entities/permit_quoted_fee_input_ignored_computed
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="QF Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22)
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z")
    assert_permit(permit)
    assert permit["quoted_fee_cents"] == 20000
    assert permit["is_prime_requested"] is False
    assert permit["pricing_residency"] == "NON_RESIDENT"


def test_patron_permits_listing_pagination(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Patron with 2 applied permits; limit=1 -> total_count 2, has_more true, 1 item.

    Design: Corner/entities/patrons_permits_listing_pagination
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="List Field", facility_type="FIELD")
    patron = create_patron(residency="NON_RESIDENT")
    apply_permit(facility["id"], patron["id"], "2026-08-21T10:00:00Z", "2026-08-21T12:00:00Z")
    apply_permit(facility["id"], patron["id"], "2026-08-22T10:00:00Z", "2026-08-22T12:00:00Z")

    res = api.list_patron_permits(
        patron["id"], make_patron_headers(patron["id"]), params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_over_max_returns_validation(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. ... A limit or offset outside
    its allowed bound is rejected with ERR_PAGINATION_INVALID (HTTP 422)."

    limit=500 (> max 100) -> ERR_PAGINATION_INVALID.

    Design: Corner/entities/pagination_limit_over_max_returns_validation
    """
    patron = create_patron(residency="RESIDENT")
    res = api.list_patron_permits(
        patron["id"], make_patron_headers(patron["id"]), params={"limit": 500, "offset": 0})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_refunds_listed_for_permit_after_cancel(api):
    """PRD §3.4: "the ledger is readable per permit and per payment."
    PRD §3.7: "The total_refund_cents is the sum of the fee refund and the deposit
    refund, and a Refund is created with these amounts and the supplied
    refund_destination; the permit's refunded_cents is set accordingly."
    PRD §3.7: "If the lead is at least 168 hours — a full seven days — the entire
    usage fee is refunded."

    Granted permit final 24000 + deposit 5000, cancel at lead 200h → the per-permit
    refund list contains the Refund with total 29000.

    Design: Corner/endpoints/refunds_listed_for_permit_after_cancel
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "RefList Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]
    set_clock("2026-07-24T09:00:00Z")
    validate_success(api.cancel_permit(
        facility["id"], permit["id"], {"refund_destination": "ORIGINAL"},
        make_patron_headers(patron["id"])), 200)

    data, meta = validate_paginated(api.list_permit_refunds(permit["id"], FINANCE))
    assert len(data) == 1
    refund = data[0]
    assert refund["total_refund_cents"] == 29000
    assert refund["fee_refund_cents"] == 24000
    assert refund["deposit_refund_cents"] == 5000


def test_lottery_entries_filtered_by_patron(api):
    """PRD §4 (endpoint): "List lottery entries, filterable by patron/round".
    PRD §2.1: "Ownership checks compare the targeted resource's owning-patron foreign
    key to X-User-ID: for a permit, the patron_id; for an insurance certificate, its
    patron_id; for a lottery entry, its patron_id; for a league series, its
    patron_id."

    Two patrons enter the same round; filtering by one patron returns only that
    patron's entry.

    Design: Corner/endpoints/lottery_entries_filtered_by_patron_reverse_reachability
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Filt Lot", "facility_type": "FIELD"},
        entrants=[
            {"verified": True, "residency": "RESIDENT"},
            {"verified": False, "residency": "NON_RESIDENT"},
        ],
    )
    patrons, entries = ctx["patrons"], ctx["entries"]
    p1, e1 = patrons[0], entries[0]

    data, meta = validate_paginated(api.list_lottery_entries(
        make_patron_headers(p1["id"]), params={"patron_id": p1["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == e1["id"]
