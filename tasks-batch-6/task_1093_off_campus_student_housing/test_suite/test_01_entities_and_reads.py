"""Entity creation, defaults, uniqueness, typed not-found, and reads.

Corner coverage index, entities section (queue B).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId,
    create_university_payload, create_property_payload, create_unit_payload,
    create_student_payload,
    TEST_USERS, make_student_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]
MGR2 = TEST_USERS["manager2_headers"]


def test_university_create_returns_full_declared_shape(api):
    """PRD §3.1: "From the tier the system computes partner_discount_bps: 500
    basis points when the tier is PREFERRED". PRD §3.1: "A newly created
    university reports verified_student_count of 0". PRD §2.4: "version is an
    integer that begins at 1 on creation".

    Design: Corner/entities/university_create_returns_full_declared_shape
    """
    resp = api.create_university(create_university_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert data["code"] == "SU"
    assert data["partner_tier"] == "PREFERRED"
    assert data["partner_discount_bps"] == 500
    assert data["verified_student_count"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a bare UUID"


def test_university_id_is_bare_uuid_and_timestamps_present(api):
    """PRD §2.4: "id is a server-minted UUID with no type prefix". PRD §2.4:
    "created_at is the ISO 8601 UTC instant of creation with three fractional
    digits."

    Design: Corner/entities/university_create_returns_full_declared_shape
    """
    resp = api.create_university(create_university_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]) and len(data["id"]) == 36 and data["id"].count("-") == 4
    assert data["created_at"].endswith("Z")


def test_university_partner_discount_bps_is_computed_from_tier(api):
    """PRD §3.1: "From the tier the system computes partner_discount_bps: 500
    basis points when the tier is PREFERRED, and 0 when it is STANDARD".

    Design: Corner/entities/university_partner_discount_bps_is_computed_from_tier
    """
    pref = validate_success(api.create_university(
        create_university_payload(code="SU", partner_tier="PREFERRED"), ADMIN), 201)
    std = validate_success(api.create_university(
        create_university_payload(name="City College", code="CC", partner_tier="STANDARD",
                                  verification_required=False, partner_admin_user_id="uni-admin-cc"),
        ADMIN), 201)
    assert pref["partner_discount_bps"] == 500
    assert std["partner_discount_bps"] == 0
    assert std["verification_required"] is False


def test_university_tier_and_verification_defaults_applied(api):
    """PRD §3.1: "The institution's partner_tier is optional and defaults to
    STANDARD". PRD §3.1: "sets verification_required, which defaults to true".

    Design: Corner/entities/university_tier_and_verification_defaults_applied
    """
    payload = {"name": "Anchor U", "code": "ANC",
               "academic_year_start_date": "2026-08-15",
               "academic_year_end_date": "2027-05-15",
               "partner_admin_user_id": "uni-admin-anc"}
    created = validate_success(api.create_university(payload, ADMIN), 201)
    data = validate_success(api.get_university(created["id"], ADMIN), 200)
    assert data["partner_tier"] == "STANDARD"
    assert data["verification_required"] is True
    assert data["partner_discount_bps"] == 0


def test_university_duplicate_code_rejected(api):
    """PRD §3.1: "a short institution code of 2-8 uppercase alphanumeric
    characters that must be unique across all universities. A second
    PlatformAdmin attempting to reuse a code is refused with
    ERR_UNIVERSITY_CODE_TAKEN."

    Design: Corner/entities/university_duplicate_code_rejected
    """
    fx.create_university(api, code="SU")
    resp = api.create_university(create_university_payload(
        name="Second State", code="SU", partner_tier="STANDARD",
        verification_required=True, partner_admin_user_id="uni-admin-2",
        academic_year_start_date="2026-09-01", academic_year_end_date="2027-06-01"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNIVERSITY_CODE_TAKEN.value)


def test_property_create_starts_in_draft_with_zero_rollups(api):
    """PRD §3.2: "The creating manager's X-User-ID is recorded as
    manager_user_id, the posture is DRAFT, and all rollup counters -
    unit_count, total_bed_count, available_bed_count, escrow_balance_cents,
    maintenance_reserve_cents - start at 0 with payout_eligible false."

    Design: Corner/entities/property_create_starts_in_draft_with_zero_rollups
    """
    uni = fx.create_university(api)
    resp = api.create_property(create_property_payload(uni["id"]), MGR)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["manager_user_id"] == "mgr-1"
    assert data["unit_count"] == 0 and data["total_bed_count"] == 0 and data["available_bed_count"] == 0
    assert data["escrow_balance_cents"] == 0 and data["maintenance_reserve_cents"] == 0
    assert data["payout_eligible"] is False
    assert data["version"] == 1


def test_property_list_pagination_reports_total_count_and_has_more(api):
    """PRD §2.3: "Each list response reports limit, offset, total_count (the
    number of matching rows before the page window) and has_more (true when
    rows remain beyond the current window) inside meta." PRD §2.3: "List
    results are ordered by created_at ascending".

    Design: Corner/entities/property_list_pagination_reports_total_count_and_has_more
    """
    uni = fx.create_university(api)
    p1 = fx.create_property(api, uni["id"], name="Maple Commons")
    p2 = fx.create_property(api, uni["id"], name="Oak Lofts")
    p3 = fx.create_property(api, uni["id"], name="Birch House")
    r1 = api.list_properties(ADMIN, params={"university_id": uni["id"], "limit": 2, "offset": 0})
    data1, meta1 = validate_paginated(r1)
    assert len(data1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    assert data1[0]["id"] == p1["id"] and data1[1]["id"] == p2["id"]
    r2 = api.list_properties(ADMIN, params={"university_id": uni["id"], "limit": 2, "offset": 2})
    data2, meta2 = validate_paginated(r2)
    assert len(data2) == 1 and data2[0]["id"] == p3["id"]
    assert meta2["total_count"] == 3 and meta2["has_more"] is False


def test_unit_missing_required_bed_labels_rejected(api):
    """PRD §3.2: "an ordered bed_labels array of distinct slot labels". PRD
    §2.9: "request schema - required fields present ... else ERR_VALIDATION".

    Design: Corner/entities/unit_missing_required_bed_labels_rejected
    """
    uni = fx.create_university(api)
    prop = fx.create_property(api, uni["id"])
    payload = {"property_id": prop["id"], "unit_number": "101", "floorplan_code": "4x2",
               "bedroom_count": 4, "bathroom_count": 2, "base_rent_cents_per_bed_monthly": 90000}
    validate_error(api.create_unit(payload, MGR), ApiErrorId.ERR_VALIDATION.value)
    data, meta = validate_paginated(api.list_units(ADMIN, params={"property_id": prop["id"]}))
    assert meta["total_count"] == 0


def test_unit_bed_labels_length_must_match_bedroom_count(api):
    """PRD §3.2: "The length of bed_labels must equal bedroom_count, or the
    request is ERR_BED_LABELS_MISMATCH."

    Design: Corner/entities/unit_bed_labels_length_must_match_bedroom_count
    """
    uni = fx.create_university(api)
    prop = fx.create_property(api, uni["id"])
    payload = create_unit_payload(prop["id"], bedroom_count=4, bed_labels=["A", "B", "C"])
    validate_error(api.create_unit(payload, MGR), ApiErrorId.ERR_BED_LABELS_MISMATCH.value)


def test_unit_number_unique_within_property_but_free_across_properties(api):
    """PRD §3.2: "a unit_number unique within the owning property (a duplicate
    is ERR_DUPLICATE_UNIT_NUMBER)".

    Design: Corner/entities/unit_number_unique_within_property_but_free_across_properties
    """
    uni = fx.create_university(api)
    prop1 = fx.create_property(api, uni["id"], name="Maple Commons")
    prop2 = fx.create_property(api, uni["id"], name="Birch House")
    fx.create_unit(api, prop1["id"], unit_number="101", bedroom_count=4,
                   bed_labels=["A", "B", "C", "D"])
    dup = api.create_unit(create_unit_payload(prop1["id"], unit_number="101", bedroom_count=2,
                                              bathroom_count=1, bed_labels=["A", "B"],
                                              base_rent_cents_per_bed_monthly=70000), MGR)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value)
    ok = api.create_unit(create_unit_payload(prop2["id"], unit_number="101", bedroom_count=2,
                                             bathroom_count=1, bed_labels=["A", "B"],
                                             base_rent_cents_per_bed_monthly=70000), MGR)
    other = validate_success(ok, 201)
    assert other["unit_number"] == "101"
    p1 = fx.get_property(api, prop1["id"])
    p2 = fx.get_property(api, prop2["id"])
    assert p1["unit_count"] == 1 and p1["total_bed_count"] == 4
    assert p2["unit_count"] == 1 and p2["total_bed_count"] == 2


def test_student_defaults_credit_band_and_smoker_flag(api):
    """PRD §3.1: "The optional credit_score_band defaults to FAIR ... the
    optional smoker flag defaults to false. Every student is born UNVERIFIED,
    with verification_submitted_at, verification_expires_at, and
    verification_decided_at all null."

    Design: Corner/entities/student_defaults_credit_band_and_smoker_flag
    """
    uni = fx.create_university(api)
    payload = {"university_id": uni["id"], "full_name": "Plain Jane", "email": "jane@su.edu",
               "cleanliness_level": 3, "noise_tolerance": 3, "sleep_schedule": "EARLY"}
    data = validate_success(api.create_student(payload, ADMIN), 201)
    assert data["credit_score_band"] == "FAIR"
    assert data["smoker"] is False
    assert data["verification_status"] == "UNVERIFIED"
    assert data["verification_submitted_at"] is None
    assert data["verification_expires_at"] is None
    assert data["verification_decided_at"] is None


def test_student_invalid_enum_and_out_of_range_rejected(api):
    """PRD §2.9: "enum members legal, integers in range ... else
    ERR_VALIDATION" with "cleanliness_level and noise_tolerance 1-5".

    Design: Corner/entities/student_invalid_enum_and_out_of_range_rejected
    """
    uni = fx.create_university(api)
    bad_enum = api.create_student({"university_id": uni["id"], "full_name": "Bad Enum",
                                   "email": "bad@su.edu", "cleanliness_level": 3,
                                   "noise_tolerance": 3, "sleep_schedule": "MIDDAY"}, ADMIN)
    validate_error(bad_enum, ApiErrorId.ERR_VALIDATION.value)
    bad_range = api.create_student({"university_id": uni["id"], "full_name": "Bad Range",
                                    "email": "range@su.edu", "cleanliness_level": 9,
                                    "noise_tolerance": 3, "sleep_schedule": "EARLY"}, ADMIN)
    validate_error(bad_range, ApiErrorId.ERR_VALIDATION.value)
    _, meta = validate_paginated(api.list_students(ADMIN, params={"university_id": uni["id"]}))
    assert meta["total_count"] == 0


def test_student_email_uniqueness_enforced(api):
    """PRD §3.1: "an email unique across all students (a collision is
    ERR_EMAIL_TAKEN)".

    Design: Corner/entities/student_email_uniqueness_enforced
    """
    uni = fx.create_university(api)
    fx.create_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    dup = api.create_student(create_student_payload(uni["id"], "ava@su.edu",
                                                    full_name="Ava Clone", credit_score_band="THIN",
                                                    cleanliness_level=1, noise_tolerance=5,
                                                    sleep_schedule="LATE", smoker=True), ADMIN)
    validate_error(dup, ApiErrorId.ERR_EMAIL_TAKEN.value)
    _, meta = validate_paginated(api.list_students(ADMIN, params={"university_id": uni["id"]}))
    assert meta["total_count"] == 1


def test_student_create_with_unknown_university_returns_not_found(api):
    """PRD §2.10: "a missing university is ERR_UNIVERSITY_NOT_FOUND ... returned
    (HTTP 404) both when a path segment names a missing row and when a foreign
    key in a request body references one that does not exist".

    Design: Corner/entities/student_create_with_unknown_university_returns_not_found
    """
    fx.create_university(api)
    resp = api.create_student({"university_id": "00000000-0000-4000-8000-000000000000",
                               "full_name": "Ghost Student", "email": "ghost@nowhere.edu",
                               "cleanliness_level": 3, "noise_tolerance": 3,
                               "sleep_schedule": "EARLY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNIVERSITY_NOT_FOUND.value)


def test_lease_rent_snapshot_and_system_fields_are_server_minted(api):
    """PRD §3.4: "monthly_rent_cents is snapshotted from the unit's
    base_rent_cents_per_bed_monthly - any client-supplied rent is ignored." PRD
    §3.4: "The lease is born with lease_status DRAFT and funding_status
    UNFUNDED".

    Design: Corner/entities/lease_rent_snapshot_and_system_fields_are_server_minted
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead",
                                  cleanliness_level=4, noise_tolerance=3, sleep_schedule="EARLY")
    resp = api.create_lease({"student_id": student["id"], "unit_id": base["unit"]["id"],
                             "bed_label": "A", "term_start_date": "2026-08-15",
                             "term_end_date": "2027-08-01", "installment_count": 10},
                            make_student_headers(student["id"]))
    data = validate_success(resp, 201)
    assert data["monthly_rent_cents"] == 90000
    assert data["property_id"] == base["prop"]["id"]
    assert data["roommate_group_id"] is None and data["replaces_lease_id"] is None
    assert data["guarantor_required"] is False
    assert data["lease_status"] == "DRAFT" and data["funding_status"] == "UNFUNDED"
    assert data["total_contract_cents"] is None
    assert data["version"] == 1 and is_valid_uuid(data["id"])


@pytest.mark.parametrize("path,err", [
    ("/universities/00000000-0000-4000-8000-000000000001", ApiErrorId.ERR_UNIVERSITY_NOT_FOUND),
    ("/properties/00000000-0000-4000-8000-000000000002", ApiErrorId.ERR_PROPERTY_NOT_FOUND),
    ("/units/00000000-0000-4000-8000-000000000003", ApiErrorId.ERR_UNIT_NOT_FOUND),
    ("/students/00000000-0000-4000-8000-000000000004", ApiErrorId.ERR_STUDENT_NOT_FOUND),
    ("/roommate-groups/00000000-0000-4000-8000-000000000005", ApiErrorId.ERR_GROUP_NOT_FOUND),
    ("/group-memberships/00000000-0000-4000-8000-000000000006", ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND),
])
def test_read_endpoints_return_typed_not_found_for_unknown_ids(api, path, err):
    """PRD §2.10: "a missing university is ERR_UNIVERSITY_NOT_FOUND, a missing
    property ERR_PROPERTY_NOT_FOUND, a missing unit ERR_UNIT_NOT_FOUND, a
    missing student ERR_STUDENT_NOT_FOUND, a missing roommate group
    ERR_GROUP_NOT_FOUND, a missing membership ERR_MEMBERSHIP_NOT_FOUND".

    Design: Corner/entities/read_endpoints_return_typed_not_found_for_unknown_ids
    """
    validate_error(api.raw("GET", path, headers=ADMIN), err.value)


@pytest.mark.parametrize("method,path,payload,err", [
    ("GET", "/leases/00000000-0000-4000-8000-000000000011", None, ApiErrorId.ERR_LEASE_NOT_FOUND),
    ("GET", "/guarantor-applications/00000000-0000-4000-8000-000000000012", None,
     ApiErrorId.ERR_GUARANTOR_APPLICATION_NOT_FOUND),
    ("GET", "/sublets/00000000-0000-4000-8000-000000000014", None, ApiErrorId.ERR_SUBLET_NOT_FOUND),
    ("GET", "/amenities/00000000-0000-4000-8000-000000000015", None, ApiErrorId.ERR_AMENITY_NOT_FOUND),
    ("GET", "/amenity-assignments/00000000-0000-4000-8000-000000000016", None,
     ApiErrorId.ERR_AMENITY_ASSIGNMENT_NOT_FOUND),
    ("GET", "/payouts/00000000-0000-4000-8000-000000000017", None, ApiErrorId.ERR_PAYOUT_NOT_FOUND),
])
def test_child_read_endpoints_return_typed_not_found_for_unknown_ids(api, method, path, payload, err):
    """PRD §2.10: "a missing lease ERR_LEASE_NOT_FOUND, a missing guarantor
    application ERR_GUARANTOR_APPLICATION_NOT_FOUND, a missing installment
    ERR_INSTALLMENT_NOT_FOUND, a missing sublet ERR_SUBLET_NOT_FOUND, a missing
    amenity ERR_AMENITY_NOT_FOUND, a missing amenity assignment
    ERR_AMENITY_ASSIGNMENT_NOT_FOUND, and a missing payout ERR_PAYOUT_NOT_FOUND."

    Design: Corner/entities/child_read_endpoints_return_typed_not_found_for_unknown_ids
    """
    validate_error(api.raw(method, path, payload=payload, headers=ADMIN), err.value)


def test_pay_unknown_installment_returns_installment_not_found(api):
    """PRD §2.10: "a missing installment ERR_INSTALLMENT_NOT_FOUND ... returned
    (HTTP 404) both when a path segment names a missing row".

    Design: Corner/entities/child_read_endpoints_return_typed_not_found_for_unknown_ids
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava")
    resp = api.pay_installment("00000000-0000-4000-8000-000000000013", {"amount_cents": 100},
                               make_student_headers(student["id"]))
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_NOT_FOUND.value)
