"""Security: authentication, role authorization, ownership, segregation of duties."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    build_user_headers, TEST_USERS, ApiErrorId,
    create_waive_payload, create_association, register_owner, register_property,
    create_complete_draft, create_under_review_application, set_logical_clock,
    setup_review_ready, setup_approved_with_permit, setup_violation_with_fine,
    get_violation_fine, read_application,
    make_homeowner_headers, make_committee_member_headers,
)

MANAGER = TEST_USERS["manager_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def test_missing_or_unknown_auth_headers_unauthenticated(api):
    """Missing headers or an undeclared role are rejected before any other check.

    PRD §2.1: "A request whose headers are missing, or whose `X-User-Role` is not
    one of these declared roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    assoc = create_association(name="Auth HOA")
    res = api.get_association(assoc["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    res2 = api.get_association(assoc["id"],
                               headers=build_user_headers("whoever", "Wizard"))
    validate_error(res2, ApiErrorId.ERR_UNAUTHENTICATED)


def test_homeowner_cannot_decide_returns_unauthorized(api):
    """The committee decision is Manager-exclusive, even for the owning Homeowner.

    PRD §2.1: "A request whose role is not on the target operation's authorized list
    is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: the decide operation's authorized role is "Manager".

    Design: Corner/validations/homeowner_cannot_decide_returns_unauthorized
    """
    bundle = setup_review_ready()
    app_id = bundle["application"]["id"]
    res = api.decide_application(
        app_id, {"conditions": []},
        make_homeowner_headers(bundle["applicant"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert read_application(app_id)["status"] == "UNDER_REVIEW"


def test_applicant_cannot_vote_on_own_application(api):
    """The applicant acting as CommitteeMember on their own application is barred.

    PRD §3.4: "A committee member who is the applicant is barred from acting on that
    application under §2.9's segregation-of-duties rule, surfacing as
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/applicant_cannot_vote_on_own_application
    """
    bundle = setup_review_ready(ballots=None, num_committee=1)
    app_id = bundle["application"]["id"]
    res = api.cast_vote(app_id, {"ballot": "APPROVE"},
                        make_committee_member_headers(bundle["applicant"]["id"]))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    other = bundle["committee"][0]
    ok = validate_success(api.cast_vote(
        app_id, {"ballot": "APPROVE"},
        make_committee_member_headers(other["id"])), 201)
    assert ok["ballot"] == "APPROVE"


def test_homeowner_cannot_submit_others_application(api):
    """A Homeowner must own the application they submit.

    PRD §2.9: "Context authorization: a `Homeowner` must own the acted-on resource
    (the application's `owner_id` or the property's `primary_owner_id` equals
    `X-User-ID`) ... Ownership failures yield `ERR_UNAUTHORIZED` (403)"

    Design: Corner/validations/homeowner_cannot_submit_others_application
    """
    assoc = create_association(name="Own HOA")
    owner_a = register_owner(assoc["id"], full_name="Ann A", email="ann.a@x.com")
    owner_b = register_owner(assoc["id"], full_name="Cid B", email="cid.b@x.com")
    prop = register_property(assoc["id"], owner_a["id"], lot_number="O-7",
                             address="7 Owner Ct")
    app = create_complete_draft(prop["id"], owner_a)

    res = api.submit_application(app["id"], make_homeowner_headers(owner_b["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert read_application(app["id"])["status"] == "DRAFT"


def test_manager_cannot_cast_vote(api):
    """Ballot casting is CommitteeMember-exclusive.

    PRD §2.1: "A request whose role is not on the target operation's authorized list
    is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.4: "Any `CommitteeMember` may cast a `ballot` of `APPROVE`, `DENY`, or
    `ABSTAIN` while the application is `UNDER_REVIEW`"

    Design: Corner/rbac/manager_cannot_cast_vote
    """
    bundle = setup_review_ready(ballots=None)
    app_id = bundle["application"]["id"]
    res = api.cast_vote(app_id, {"ballot": "APPROVE"}, MANAGER)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    votes = validate_paginated(api.list_votes(app_id, MANAGER))[0]
    assert votes == [], "no ballot may be recorded by a rejected call"


def test_committee_member_cannot_record_inspection(api):
    """Recording an inspection result is Inspector-exclusive.

    PRD §2.1: "A request whose role is not on the target operation's authorized list
    is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.7: "An `Inspector` records the outcome of a `SCHEDULED` inspection by
    supplying a `result` of `PASS` or `FAIL`"

    Design: Corner/rbac/committee_member_cannot_record_inspection
    """
    bundle = setup_approved_with_permit()
    set_logical_clock("2026-06-10T09:00:00Z")
    inspection = validate_success(api.request_inspection(
        bundle["permit"]["id"],
        make_homeowner_headers(bundle["applicant"]["id"])), 201)
    member = bundle["committee"][0]
    res = api.record_inspection(inspection["id"], {"result": "PASS"},
                                make_committee_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    after = validate_success(api.get_inspection(inspection["id"], MANAGER), 200)
    assert after["status"] == "SCHEDULED"


def test_inspector_cannot_waive_fine(api):
    """Waiver is the manager's compensating action, not the inspector's.

    PRD §2.1: "A request whose role is not on the target operation's authorized list
    is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.8: "Waiver is the manager's compensating action and may be partial: a
    `Manager` waives by supplying `amount_cents` and a `reason`"

    Design: Corner/rbac/inspector_cannot_waive_fine
    """
    bundle = setup_violation_with_fine()
    fine_id = bundle["fine"]["id"]
    res = api.waive_fine(fine_id, create_waive_payload(1000, "inspector goodwill"),
                         INSPECTOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    fine = get_violation_fine(bundle["violation"]["id"])
    assert fine["waived_cents"] == 0
