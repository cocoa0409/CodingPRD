"""Authentication, role-based authorization, ownership, and read reachability."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Corner: rbac / submitter_cannot_record
# ===========================================================================
def test_submitter_cannot_record_package(api):
    """PRD Section 2.1: "When a recognized role attempts an operation it is not permitted
    to perform under the role matrix in Section 4, the request is rejected with
    ERR_FORBIDDEN."

    The Section 4 matrix authorizes only Recorder for POST /packages/{id}/record, so a
    Submitter calling it is denied with ERR_FORBIDDEN.

    Design: Corner/rbac/submitter_cannot_record
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, _assessment, _payment = fixtures.create_paid_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0, amount_cents=3500,
    )
    resp = api.record_package(pkg_after["id"], fixtures.make_submitter_headers(submitter["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Corner: rbac / examiner_cannot_create_office
# ===========================================================================
def test_examiner_cannot_create_office(api):
    """PRD Section 2.1: "When a recognized role attempts an operation it is not permitted
    to perform under the role matrix in Section 4, the request is rejected with
    ERR_FORBIDDEN."

    The Section 4 matrix authorizes only Clerk for POST /offices, so an Examiner calling
    it is denied with ERR_FORBIDDEN.

    Design: Corner/rbac/examiner_cannot_create_office
    """
    resp = api.create_office(
        {"county_name": "Rogue", "book_capacity": 3},
        fixtures.make_examiner_headers("ex-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Corner: rbac / missing_role_header_unauthenticated
# ===========================================================================
def test_missing_role_header_unauthenticated(api):
    """PRD Section 2.1: "If X-User-Role is missing or is not one of these four recognized
    roles, the request is rejected with ERR_UNAUTHENTICATED."

    A request with no X-User-Role header returns ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.list_submitters({"X-User-ID": "nobody", "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# Corner: rbac / re_record_not_owner
# ===========================================================================
def test_re_record_by_non_owner_forbidden(api):
    """PRD Section 2.10: "Sixth, for owner-scoped actions (re-record, withdraw, payments,
    continue, terminate) the acting submitter must own the resource, or the request is
    rejected with ERR_NOT_OWNER."
    PRD Section 2.1: "ownership checks on any resource that references a Submitter compare
    the resource's submitter_id foreign-key field to X-User-ID ... and a mismatch
    surfaces as ERR_NOT_OWNER."

    A submitter who is not the package owner calling re-record on a REJECTED package is
    denied with ERR_NOT_OWNER, and the package stays REJECTED.

    Design: Corner/rbac/re_record_not_owner
    """
    office, owner = fixtures.setup_office_and_submitter(submitter_name="Owner A",
                                                        submitter_type="TITLE_COMPANY")
    other = fixtures.create_submitter(name="Other B", submitter_type="ATTORNEY")
    pkg_id, _rn = fixtures.create_rejected_package(
        office["id"], owner["id"], reason_code="MARGIN",
        first_page_top_margin_inches=2.0,
    )
    resp = api.re_record(
        pkg_id, {"first_page_top_margin_inches": 3.0},
        fixtures.make_submitter_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
    data = validate_success(api.get_package(pkg_id, fixtures._clerk()))
    assert data["status"] == "REJECTED", f"package must stay REJECTED, got {data['status']}"


# ===========================================================================
# Corner: endpoints / party_entry_reverse_reachability_get
# ===========================================================================
def test_list_party_entries_returns_two(api):
    """PRD Section 2.3: "Every list-based response includes the fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."
    PRD Section 3.2: "A submitter adds a PartyEntry to a package by supplying a party_role
    (GRANTOR or GRANTEE) and a party_name. Each entry references its package_id."

    GET /packages/{id}/party-entries returns the package's two index entries as an array.

    Design: Corner/endpoints/party_entry_reverse_reachability_get
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_grantor_grantee(pkg["id"], submitter["id"])
    rows, meta = validate_paginated(api.list_party_entries(pkg["id"], fixtures._examiner()))
    assert meta["total_count"] == 2, f"two party entries expected, got {meta['total_count']}"
