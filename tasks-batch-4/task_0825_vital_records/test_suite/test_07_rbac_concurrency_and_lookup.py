"""Access control (authentication, authorization, ownership), optimistic
concurrency on the vital event, and read/list envelope behavior."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_facility_filer_headers,
    create_facility,
    create_vital_event,
    create_amendment,
    submit_amendment,
    file_event,
    event_version,
    setup_registered_birth_event,
    setup_id_verified_copy,
    create_vital_event_payload,
    create_facility_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


# ---------------------------------------------------------------------------
# Corner: entities / vital_event_get_not_found_returns_404
# ---------------------------------------------------------------------------
def test_vital_event_get_not_found_returns_404(api):
    """PRD §2.7: "the system validates their existence left to right and rejects
    at the first one that does not resolve, returning the not-found error specific
    to that entity type: `ERR_FACILITY_NOT_FOUND`, `ERR_CERTIFIER_NOT_FOUND`,
    `ERR_VITAL_EVENT_NOT_FOUND`".

    Design: Corner/entities/vital_event_get_not_found_returns_404
    """
    resp = api.get_vital_event(NON_EXISTENT_UUID, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_VITAL_EVENT_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_vital_events_paginated_envelope
# ---------------------------------------------------------------------------
def test_list_vital_events_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_vital_events_paginated_envelope
    """
    fac = create_facility(jurisdiction_code="CTY-51")
    create_vital_event(fac["id"], jurisdiction_code="CTY-51")
    resp = api.list_vital_events(
        REGISTRAR, params={"jurisdiction_code": "CTY-51", "limit": 10, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Corner: rbac / facility_filer_cannot_register_returns_unauthorized
# ---------------------------------------------------------------------------
def test_facility_filer_cannot_register_returns_unauthorized(api):
    """PRD §2.1: "If the role is recognized but not permitted to call the
    requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."

    Design: Corner/rbac/facility_filer_cannot_register_returns_unauthorized
    """
    fac = create_facility(jurisdiction_code="CTY-53")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-53")
    file_event(ev["id"], fac["id"])
    resp = api.register_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner: rbac / filer_files_other_facility_event_returns_not_owner
# ---------------------------------------------------------------------------
def test_filer_files_other_facility_event_returns_not_owner(api):
    """PRD §2.1: "Ownership checks on any vital event compare the event's
    `facility_id` to `X-User-ID`; a filer may file only events belonging to its
    own facility."
    PRD §2.1: "An ownership violation on these entity-backed actions is rejected
    with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/filer_files_other_facility_event_returns_not_owner
    """
    fac_a = create_facility(jurisdiction_code="CTY-54", npi="NPI-054A")
    fac_b = create_facility(jurisdiction_code="CTY-54", npi="NPI-054B")
    ev = create_vital_event(fac_a["id"], jurisdiction_code="CTY-54")
    # facility B's filer tries to file facility A's event
    resp = api.file_vital_event(ev["id"], make_facility_filer_headers(fac_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


# ---------------------------------------------------------------------------
# Corner: rbac / applicant_cannot_create_vital_event_unauthorized
# ---------------------------------------------------------------------------
def test_applicant_cannot_create_vital_event_unauthorized(api):
    """PRD §2.1: "If the role is recognized but not permitted to call the
    requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."

    Design: Corner/rbac/applicant_cannot_create_vital_event_unauthorized
    """
    fac = create_facility(jurisdiction_code="CTY-55")
    resp = api.create_vital_event(
        create_vital_event_payload(fac["id"], jurisdiction_code="CTY-55"),
        APPLICANT,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner: rbac / missing_role_header_returns_unauthenticated
# ---------------------------------------------------------------------------
def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_facility(
        create_facility_payload(jurisdiction_code="CTY-56", npi="NPI-056"),
        {},  # no X-User-ID / X-User-Role headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / copy_issue_stale_event_version_returns_412
# ---------------------------------------------------------------------------
def test_copy_issue_stale_event_version_returns_412(api):
    """PRD §2.6: "Issuing a certified copy likewise requires
    `expected_vital_event_version` matching the referenced event's current
    `version`. If the record has advanced since the requester last observed it,
    the issuance is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), ensuring
    no copy is minted from an out-of-date view of the record."

    Design: Corner/cross_cutting/copy_issue_stale_event_version_returns_412
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-57",
                                           event_date="2026-02-25T00:00:00Z")
    c1 = setup_id_verified_copy(ev["id"], requester_relationship="SELF",
                                id_document_type="STATE_ID", copy_count=1)
    c2 = setup_id_verified_copy(ev["id"], requester_relationship="SELF",
                                id_document_type="STATE_ID", copy_count=1)
    v0 = event_version(ev["id"])
    validate_success(api.issue_copy_request(
        c1["id"], {"expected_vital_event_version": v0}, REGISTRAR
    ))  # bumps the event version
    resp = api.issue_copy_request(
        c2["id"], {"expected_vital_event_version": v0}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / amend_approve_stale_event_version_returns_412
# ---------------------------------------------------------------------------
def test_amend_approve_stale_event_version_returns_412(api):
    """PRD §2.6: "Approving an amendment requires the request to carry
    `expected_vital_event_version`, the `version` of the target vital event the
    registrar last observed. If that value does not match the event's current
    `version` — because another amendment approval or a copy issuance has advanced
    the record since it was read — the approval is rejected with
    `ERR_STALE_EVENT_VERSION` (HTTP 412), so that a correction is never written
    over a record the registrar has not seen."

    Design: Corner/cross_cutting/amend_approve_stale_event_version_returns_412
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-58",
                                           event_date="2026-02-25T00:00:00Z")
    am1 = create_amendment(ev["id"], field_name="subject_first_name", new_value="Ned")
    submit_amendment(am1["id"])
    am2 = create_amendment(ev["id"], field_name="subject_last_name", new_value="Amend")
    submit_amendment(am2["id"])
    v0 = event_version(ev["id"])
    validate_success(api.approve_amendment(
        am1["id"], {"expected_vital_event_version": v0}, REGISTRAR
    ))  # bumps the event version
    resp = api.approve_amendment(
        am2["id"], {"expected_vital_event_version": v0}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
