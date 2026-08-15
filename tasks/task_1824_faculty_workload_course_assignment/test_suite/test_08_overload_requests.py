"""Overload requests: snapshot, budget gate, segregation of duties, negotiation loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_assignment,
    create_overload_request_payload,
    make_chair_headers,
    make_dean_headers,
    setup_faculty_with_load,
    setup_overload_request,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]


def test_overload_comp_cents_computed(api):
    """PRD §3.9: "A successful submission snapshots two computed values onto the
    request: `overload_credits`, copied from the load sheet at submission time, and
    `comp_cents`, the product of that overload and the term's
    `overload_comp_rate_cents`, rounded half-up to whole cents. The request is born
    `SUBMITTED`."

    Design: Corner/calculations/c_overload_comp_cents_computed
    """
    # 3 ONLINE (3.5 each) + 1 IN_PERSON (3.0) -> teaching 13.5, overload 1.5.
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        3, modality="ONLINE"
    )
    from test_helpers import make_section
    s4 = make_section(term["id"], course["id"], section_number="04",
                      modality="IN_PERSON", meeting_day="THU")
    add_assignment(s4["id"], faculty["id"])

    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    request = validate_success(resp, 201)
    assert request["overload_credits"] == pytest.approx(1.5), "13.5 - 12"
    assert request["comp_cents"] == 225_000, "1.5 x 150000"
    assert request["status"] == "SUBMITTED"


def test_no_overload_request_rejected(api):
    """PRD §3.9: "Submission requires a live overload: the pair's load sheet must
    exist with `overload_credits` greater than 0, else the submission is rejected
    with `ERR_NO_OVERLOAD`."

    Design: Corner/validations/c_no_overload_request_rejected
    """
    # 4 IN_PERSON x 3.0 = 12.0 teaching -> overload exactly 0.0 at base load.
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        4, modality="IN_PERSON"
    )
    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_NO_OVERLOAD, 422)


def test_overload_request_exists_rejected(api):
    """PRD §3.9: "Only one non-terminal request may exist per term-and-faculty pair; a
    second submission while one is still in flight is rejected with
    `ERR_OVERLOAD_REQUEST_EXISTS`."

    Design: Corner/validations/c_overload_request_exists_rejected
    """
    # 5 IN_PERSON x 3.0 = 15.0 -> overload 3.0.
    term, course, faculty, sections, assignments, request = setup_overload_request(
        5, modality="IN_PERSON"
    )
    assert request["status"] == "SUBMITTED"

    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_OVERLOAD_REQUEST_EXISTS, 409)


def test_overload_withdrawn_terminal(api):
    """PRD §3.9: "Any transition not described here — acting on a terminal
    `DEAN_APPROVED`, `DENIED`, or `WITHDRAWN` request, or reaching for a target the
    from-state does not support — is rejected with `ERR_INVALID_OVERLOAD_TRANSITION`."

    Design: Corner/state_machines/c_overload_withdrawn_terminal
    """
    term, course, faculty, sections, assignments, request = setup_overload_request(
        5, modality="IN_PERSON"
    )
    resp = api.transition_overload_request(
        request["id"], {"to_state": "WITHDRAWN"}, CHAIR
    )
    withdrawn = validate_success(resp)
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.transition_overload_request(
        request["id"], {"to_state": "CHAIR_ENDORSED"}, CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_OVERLOAD_TRANSITION, 409)

    after = validate_success(api.get_overload_request(request["id"], CHAIR))
    assert after["status"] == "WITHDRAWN"


def test_comp_budget_exceeded_on_approve(api):
    """PRD §3.9: "Approval runs two preconditions in order: the approver's `X-User-ID`
    must differ from `endorsed_by_user_id` — a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` — and the term's `comp_budget_spent_cents` plus the
    request's `comp_cents` must not exceed `comp_budget_cents`, else the approval is
    rejected with `ERR_COMP_BUDGET_EXCEEDED`."

    Design: Corner/validations/c_comp_budget_exceeded_on_approve
    """
    # Budget 200000 < comp 225000 (overload 1.5 x 150000).
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        3, modality="ONLINE", term_overrides={"comp_budget_cents": 200_000}
    )
    from test_helpers import make_section
    s4 = make_section(term["id"], course["id"], section_number="04",
                      modality="IN_PERSON", meeting_day="THU")
    add_assignment(s4["id"], faculty["id"])

    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    request = validate_success(resp, 201)
    resp = api.transition_overload_request(
        request["id"], {"to_state": "CHAIR_ENDORSED"}, make_chair_headers("chair-1")
    )
    validate_success(resp)

    resp = api.transition_overload_request(
        request["id"], {"to_state": "DEAN_APPROVED"}, make_dean_headers("dean-1")
    )
    validate_error(resp, ApiErrorId.ERR_COMP_BUDGET_EXCEEDED, 402)

    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 0, "no partial debit"
    after = validate_success(api.get_overload_request(request["id"], CHAIR))
    assert after["status"] == "CHAIR_ENDORSED"


def test_chair_cannot_approve_overload(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint — including per-`to_state` role gates on the shared transition endpoints
    — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §3.9: "From `CHAIR_ENDORSED`, a `DeanOffice` operator may approve or deny."

    Design: Corner/rbac/c_chair_cannot_approve_overload
    """
    term, course, faculty, sections, assignments, request = setup_overload_request(
        5, modality="IN_PERSON", endorse=True, endorser_user_id="chair-1"
    )
    # A chair (even a different chair user id) may not perform DEAN_APPROVED.
    resp = api.transition_overload_request(
        request["id"], {"to_state": "DEAN_APPROVED"}, make_chair_headers("chair-2")
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_dean_who_endorsed_cannot_approve(api):
    """PRD §2.1: "Segregation of duties governs overload compensation. When a
    `DeanOffice` operator attempts to move an overload request to `DEAN_APPROVED`,
    the approver's `X-User-ID` must differ from the request's recorded
    `endorsed_by_user_id`; a chair may never approve the same request they endorsed,
    and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/c_dean_who_endorsed_cannot_approve
    """
    # 5 IN_PERSON x 3.0 = 15.0 -> overload 3.0, comp 450000; budget ample.
    term, course, faculty, sections, assignments, request = setup_overload_request(
        5, modality="IN_PERSON", endorse=True, endorser_user_id="user-x"
    )
    assert request["endorsed_by_user_id"] == "user-x"

    # Same human (dual-hatted) acting as DeanOffice with the same X-User-ID.
    resp = api.transition_overload_request(
        request["id"], {"to_state": "DEAN_APPROVED"}, make_dean_headers("user-x")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    # A different dean user id passes the segregation gate.
    resp = api.transition_overload_request(
        request["id"], {"to_state": "DEAN_APPROVED"}, make_dean_headers("dean-9")
    )
    approved = validate_success(resp)
    assert approved["status"] == "DEAN_APPROVED"

    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 450_000
