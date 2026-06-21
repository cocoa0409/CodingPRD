"""Creation defaults, not-found / invalid-request shapes, RBAC denials, optimistic
concurrency on the case version, and reverse-reachability listing.

PRD coverage: §2.1 (auth/forbidden), §2.7 (OCC on case version), §2.8 (reference and
not-found), §3.1/§3.2 (owner/property/case creation defaults), §3.5 (live owner
fields), §3.10 (payment bumps version).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
)
from test_helpers import assert_owner, assert_case
from test_helpers import fixtures as F
from test_helpers.test_users import make_registrant_headers, make_anonymous_headers


ADMIN = F.ADMIN
OFFICER = F.OFFICER
CLERK = F.CLERK


# ==========================================================================
# Corner: entities / create_owner_returns_201_with_defaults
# ==========================================================================
def test_create_owner_returns_201_with_first_tier_defaults(api):
    """PRD §3.1: "A freshly registered owner starts at `repeat_tier` of `FIRST` with
    a `prior_violation_count` of zero."

    Design: Corner/entities/create_owner_returns_201_with_defaults
    """
    F.set_clock("2026-01-01T00:00:00Z")
    resp = api.create_owner({"full_name": "Anna A", "mailing_email": "anna@x.com"}, ADMIN)
    owner = validate_success(resp, expected_status=201)
    assert_owner(owner)
    assert owner["repeat_tier"] == "FIRST", f"expected FIRST, got {owner['repeat_tier']}"
    assert owner["prior_violation_count"] == 0, (
        f"expected prior_violation_count 0, got {owner['prior_violation_count']}"
    )


# ==========================================================================
# Corner: entities / get_case_not_found_returns_404
# ==========================================================================
def test_get_case_unknown_id_returns_not_found(api):
    """PRD §2.8: "A single missing identifier always yields `ERR_NOT_FOUND` as well."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    F.set_clock("2026-01-01T00:00:00Z")
    resp = api.get_case(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ==========================================================================
# Corner: entities / create_property_missing_required_field_returns_invalid_request
# ==========================================================================
def test_create_property_missing_parcel_number_invalid_request(api):
    """PRD §2.8: "any request body missing a required field, or supplying an enum
    value outside its permitted set, is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "Properties are likewise registered ... each naming the `owner_id` of
    record, a `parcel_number`, a `street_address`, and an `occupancy`"

    Design: Corner/entities/create_property_missing_required_field_returns_invalid_request
    """
    F.set_clock("2026-01-01T00:00:00Z")
    owner = F.create_owner()
    resp = api.create_property(
        {"owner_id": owner["id"], "street_address": "1 X St", "occupancy": "OCCUPIED"}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner: entities / create_property_invalid_occupancy_enum_returns_invalid_request
# ==========================================================================
def test_create_property_invalid_occupancy_enum_invalid_request(api):
    """PRD §2.8: "any request body missing a required field, or supplying an enum
    value outside its permitted set, is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "an `occupancy` of either `OCCUPIED` or `VACANT`"

    Design: Corner/entities/create_property_invalid_occupancy_enum_returns_invalid_request
    """
    F.set_clock("2026-01-01T00:00:00Z")
    owner = F.create_owner()
    resp = api.create_property(
        {
            "owner_id": owner["id"],
            "parcel_number": "APN-X",
            "street_address": "2 X St",
            "occupancy": "MAYBE",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner: entities / case_computed_outstanding_balance_input_ignored
# ==========================================================================
def test_new_case_has_zero_balance_and_intake_posture(api):
    """PRD §3.2: "The new case starts with `posture` of `INTAKE`, an
    `outstanding_balance_cents` of zero, `payments_applied_cents` of zero, and a null
    `closed_at`"

    Design: Corner/entities/case_computed_outstanding_balance_input_ignored
    """
    F.set_clock("2026-01-01T00:00:00Z")
    owner = F.create_owner()
    prop = F.create_property(owner["id"])
    resp = api.create_case({"property_id": prop["id"]}, OFFICER)
    case = validate_success(resp, expected_status=201)
    assert_case(case)
    assert case["outstanding_balance_cents"] == 0, (
        f"expected balance 0, got {case['outstanding_balance_cents']}"
    )
    assert case["posture"] == "INTAKE", f"expected INTAKE, got {case['posture']}"


# ==========================================================================
# Corner: validations / missing_auth_header_returns_unauthenticated
# ==========================================================================
def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role` or presents a value that is not
    one of the recognized roles is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    headers = make_anonymous_headers()  # X-User-Role is an unrecognized value
    resp = api.create_owner({"full_name": "No Auth", "mailing_email": "noauth@x.com"}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ==========================================================================
# Corner: rbac / registrant_cannot_issue_notice
# ==========================================================================
def test_registrant_cannot_issue_notice(api):
    """PRD §2.1: "When the header is well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.4: "A `CodeOfficer` issues a `ViolationNotice` by naming the `case_id`,
    the `source_inspection_id` that substantiates it, and the `violation_class` of
    `MINOR`, `MAJOR`, or `HAZARD` that selects the pricing row."

    Design: Corner/rbac/registrant_cannot_issue_notice
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner, _prop, case, insp = F.setup_case_with_substantiation()
    headers = make_registrant_headers(owner["id"])
    resp = api.create_notice(
        {"case_id": case["id"], "source_inspection_id": insp["id"], "violation_class": "MAJOR"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ==========================================================================
# Corner: rbac / code_officer_cannot_record_lien
# ==========================================================================
def test_code_officer_cannot_record_lien(api):
    """PRD §2.1: "When the header is well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.12: "When penalties go unpaid, a `FinanceClerk` records a `Lien` against
    the case to encumber the parcel."

    Design: Corner/rbac/code_officer_cannot_record_lien
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    version = F.case_version(ctx["case"]["id"])
    resp = api.create_lien(
        {"case_id": ctx["case"]["id"], "expected_case_version": version}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ==========================================================================
# Corner: cross_cutting_complexity_layers / case_version_increments_on_payment
# ==========================================================================
def test_payment_increments_case_version_by_one(api):
    """PRD §3.10: "The payment recomputes the case's `outstanding_balance_cents` and
    posture and increments the case's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/case_version_increments_on_payment
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    v_before = F.case_version(ctx["case"]["id"])
    paid = F.post_payment(ctx["case"]["id"], 5000, expected_version=v_before)
    assert paid["version"] == v_before + 1, (
        f"expected version {v_before + 1}, got {paid['version']}"
    )


# ==========================================================================
# Corner: cross_cutting_complexity_layers / lien_stale_case_version_returns_412
# ==========================================================================
def test_lien_with_stale_case_version_returns_stale_version(api):
    """PRD §2.7: "If `expected_case_version` does not equal the case's current
    `version` at the moment of recording, the request is rejected with
    `ERR_STALE_VERSION` and HTTP status 412. This means that if any other writer has
    advanced the case's version since the client last read it — for instance by
    posting a payment or waiving a contested fine, each of which bumps `Case.version`
    and shifts the balance — the clerk's view is stale and the lien they would freeze
    could carry a wrong principal, so the record is refused."

    Design: Corner/cross_cutting_complexity_layers/lien_stale_case_version_returns_412
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    case_id = ctx["case"]["id"]
    stale_v = F.case_version(case_id)
    # Post a payment with the observed version -> bumps Case.version, making stale_v stale.
    F.post_payment(case_id, 10000, expected_version=stale_v)
    resp = api.create_lien({"case_id": case_id, "expected_case_version": stale_v}, CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ==========================================================================
# Corner: endpoints / list_notices_filtered_by_case_id_reverse_reachability
# ==========================================================================
def test_list_notices_filtered_by_case_id(api):
    """PRD §3.4: "a notice list can be filtered by `case_id`, `owner_id`, or
    `source_inspection_id`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_notices_filtered_by_case_id_reverse_reachability
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    data, meta = validate_paginated(
        api.list_notices(CLERK, params={"case_id": ctx["case"]["id"]})
    )
    assert len(data) == 1, f"expected exactly one notice, got {len(data)}"
    assert data[0]["id"] == ctx["notice"]["id"], "listed notice id mismatch"
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


# ==========================================================================
# Corner: endpoints / list_case_complaints_subresource_reverse_reachability
# ==========================================================================
def test_list_case_complaints_subresource(api):
    """PRD §3.3: "A case's complaints can be listed as a sub-resource of the case."

    Design: Corner/endpoints/list_case_complaints_subresource_reverse_reachability
    """
    F.set_clock("2026-01-01T00:00:00Z")
    _owner, _prop, case = F.setup_owner_property_case()
    comp = get_success_data(
        api.create_complaint(
            {"case_id": case["id"], "reporter_kind": "ANONYMOUS", "narrative": "trash"}, OFFICER
        )
    )
    data, _meta = validate_paginated(api.list_case_complaints(case["id"], OFFICER))
    assert len(data) == 1, f"expected exactly one complaint, got {len(data)}"
    assert data[0]["id"] == comp["id"], "listed complaint id mismatch"
