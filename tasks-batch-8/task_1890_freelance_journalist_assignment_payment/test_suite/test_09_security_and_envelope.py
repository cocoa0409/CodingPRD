"""Security and envelope: role exclusivity, ownership denial,
authentication, path existence, pagination defaults, and the DeskConfig
singleton."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    bootstrap_desk,
    create_assignment,
    create_contributor,
    get_assignment,
    get_invoice,
    make_contributor_headers,
    make_finance_headers,
    setup_accepted_assignment,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    submit_invoice,
    validate_error,
    validate_paginated,
    walk_assignment,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def test_contributor_cannot_kill_own_assignment(api):
    """PRD section 4: "| POST | /freelance-desk/assignments/{id}/kill |
    Editor kills the assignment; kill fee per tier and lateness | Editor |"
    PRD section 2.1: "A request whose role is not listed among the
    authorized roles for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/contributor_cannot_kill_own_assignment
    """
    contributor, _agr, assignment = setup_assignment_in_state(
        "IN_PROGRESS", legal_name="Kill Ken", email="ken@x.com")
    resp = api.kill_assignment(
        assignment["id"], make_contributor_headers(contributor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert (get_assignment(assignment["id"])["editorial_status"]
            == "IN_PROGRESS")


def test_editor_cannot_verify_invoice(api):
    """PRD section 4: "| POST | /freelance-desk/invoices/{id}/verify |
    Finance verifies claim amounts; computes gross/withholding/net; or
    rejects | FinanceUser |"
    PRD section 2.1: "A request whose role is not listed among the
    authorized roles for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/editor_cannot_verify_invoice
    """
    contributor, _agr, accepted = setup_accepted_assignment(
        legal_name="Role Rita", email="rita@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000)
    invoice = submit_invoice(accepted["id"], contributor["id"], 50000, 0)

    resp = _api.verify_invoice(invoice["id"], {"decision": "VERIFY"},
                               EDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert get_invoice(invoice["id"])["status"] == "SUBMITTED"


def test_contributor_cannot_accept_others_assignment(api):
    """PRD section 3.3: "From `OFFERED`, the contributor themselves accepts
    (moving to `ACCEPTED`) — ownership is enforced by comparing `X-User-ID`
    to the assignment's `contributor_id`, with a mismatch rejected as
    `ERR_NOT_OWNER`."

    Design: Corner/rbac/contributor_cannot_touch_others_assignment
    """
    contributor_a, _agr = setup_contributor_with_agreement(
        legal_name="Owner A", email="a@x.com")
    contributor_b = create_contributor(legal_name="Owner B", email="b@x.com")
    assignment = create_assignment(contributor_a["id"], title="OA")
    walk_assignment(assignment["id"], contributor_a["id"], "OFFERED")

    resp = _api.accept_assignment(
        assignment["id"], make_contributor_headers(contributor_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER, 403)
    assert (get_assignment(assignment["id"])["editorial_status"]
            == "OFFERED")


def test_verification_editor_cannot_create_assignment(api):
    """PRD section 4: "| POST | /freelance-desk/assignments | Create an
    assignment brief in DRAFT | Editor |"
    PRD section 2.1: "A request whose `X-User-Role` is absent or does not
    match one of these spellings, or whose `X-User-ID` is absent, is rejected
    with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the
    authorized roles for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/verification_editor_cannot_create_assignment
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Ref Rex", email="rex@x.com")
    payload = {"contributor_id": contributor["id"], "title": "X",
               "brief": "b", "commissioned_word_count": 100,
               "deadline_utc": "2026-08-10T00:00:00Z"}

    resp = _api.create_assignment(
        payload, TEST_USERS["verification_editor_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    # Missing X-User-Role is an authentication failure, checked before roles.
    no_role_headers = {"X-User-ID": "someone",
                       "Content-Type": "application/json"}
    resp_no_role = _api.create_assignment(payload, no_role_headers)
    validate_error(resp_no_role, ApiErrorId.ERR_UNAUTHENTICATED, 401)


@pytest.mark.parametrize("kind", ["assignment", "invoice", "batch", "report"])
def test_get_unknown_id_returns_not_found(api, kind):
    """PRD section 2.7: "Nested paths are validated left-to-right: each
    path-templated resource must exist before any child resource is
    resolved, and a missing id at any level yields `ERR_NOT_FOUND`."

    Design: Corner/errors/not_found_on_unknown_ids
    """
    bootstrap_desk()
    fin = make_finance_headers("fin-1")
    getters = {
        "assignment": (EDITOR, f"/freelance-desk/assignments/{NON_EXISTENT_UUID}"),
        "invoice": (fin, f"/freelance-desk/invoices/{NON_EXISTENT_UUID}"),
        "batch": (fin, f"/freelance-desk/payment-batches/{NON_EXISTENT_UUID}"),
        "report": (TEST_USERS["verification_editor_headers"],
                   f"/freelance-desk/verification-reports/{NON_EXISTENT_UUID}"),
    }
    headers, path = getters[kind]
    resp = _api.get(path, headers=headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_contributors_pagination_defaults_and_envelope(api):
    """PRD section 2.3: "`limit` controls page size: it defaults to 10, has
    a minimum of 1, and a maximum of 100. `offset` controls how many records
    to skip and defaults to 0. Responses include the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more` inside `meta`."
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources." and "The `api_request_id`
    is a server-generated unique identifier for the request that starts with
    `req_`."

    Design: Corner/endpoints/pagination_defaults_and_envelope
    """
    bootstrap_desk()
    for i in range(1, 13):
        create_contributor(legal_name=f"P{i:02d}", email=f"p{i:02d}@x.com")

    resp = api.list_contributors(ADMIN)
    body = resp.json()
    rows, meta = validate_paginated(resp)
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert len(rows) == 10, "default page size is 10"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    resp2 = api.list_contributors(ADMIN, params={"limit": 10, "offset": 10})
    rows2, meta2 = validate_paginated(resp2)
    assert len(rows2) == 2, "second page holds the remaining two"
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12


def test_desk_config_second_bootstrap_rejected(api):
    """PRD section 3.10: "The desk's policy constants live on a singleton
    `DeskConfig` initialized once by a `DeskAdmin`; a second initialization
    attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/desk_config_double_bootstrap_rejected
    """
    bootstrap_desk()
    resp = api.bootstrap_desk_config({}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
