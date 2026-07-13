"""RBAC, ownership, optimistic concurrency, and pagination (Newborn Screening PRD)."""
from test_helpers import (
    validate_error,
    validate_paginated,
    create_screen_on_satisfactory,
    create_facility,
    create_infant,
    create_hospital_and_infant,
    create_specimen,
    create_specimen_payload,
    infant_version,
    point_of_care_hearing_payload,
    make_birth_facility_user_headers,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]


# ─── Corner: LabTechnician cannot report point-of-care ────────────────
def test_labtech_cannot_report_point_of_care(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.4: "A `BirthFacilityUser` reports a point-of-care dimension by supplying a
    `component` of either `HEARING` or `CCHD`."

    Design: Corner/rbac/labtech_cannot_report_point_of_care_returns_unauthorized
    """
    _facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    res = api.report_point_of_care(screen["id"], point_of_care_hearing_payload("PASS"), LAB)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


# ─── Corner: a different facility cannot collect the specimen ─────────
def test_other_facility_cannot_collect_specimen(api):
    """PRD §2.1: "a birth-facility user may register an infant only when the supplied
    `facility_id` equals `X-User-ID`, and may act on a specimen, consent record, or
    point-of-care screen only when the owning infant's registering facility equals
    `X-User-ID`. A mismatch is rejected with `ERR_NOT_OWNER`."

    Design: Corner/rbac/other_facility_cannot_collect_specimen_returns_not_owner
    """
    hosp_a = create_facility(name="Hosp A")
    hosp_b = create_facility(name="Hosp B")
    infant = create_infant(hosp_a)
    other_hdr = make_birth_facility_user_headers(hosp_b["id"])
    version = infant_version(infant["id"])
    res = api.create_specimen(
        create_specimen_payload(infant["id"], version), other_hdr
    )
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


# ─── Corner: stale infant version rejected (OCC) ──────────────────────
def test_specimen_create_stale_infant_version_rejected(api):
    """PRD §2.8: "A request to create a specimen must carry `expected_infant_version` as a
    mandatory field holding the `version` of the infant the client last observed."
    PRD §2.8: "If that value does not equal the infant's current `version`, the create is
    rejected with `ERR_STALE_INFANT_VERSION` (HTTP 412), because the client is acting on a
    stale view of the infant."

    Design: Corner/cross_cutting/specimen_create_stale_infant_version_returns_412
    """
    facility, infant = create_hospital_and_infant()
    stale_version = infant["version"]
    hdr = make_birth_facility_user_headers(facility["id"])
    create_specimen(facility, infant)  # advances Infant.version past `stale_version`
    res = api.create_specimen(
        create_specimen_payload(
            infant["id"], stale_version,
            specimen_type="REPEAT", collection_datetime="2026-02-28T18:00:00Z",
        ),
        hdr,
    )
    validate_error(res, "ERR_STALE_INFANT_VERSION", expected_status=412)


# ─── Corner: paginated specimen listing envelope ──────────────────────
def test_list_specimens_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if
    not provided it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/cross_cutting/list_specimens_pagination_envelope
    """
    facility, infant = create_hospital_and_infant()
    create_specimen(facility, infant)  # INITIAL
    create_specimen(
        facility, infant, specimen_type="REPEAT", collection_datetime="2026-02-28T18:00:00Z"
    )
    data, meta = validate_paginated(
        api.list_specimens(LAB, params={"infant_id": infant["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
