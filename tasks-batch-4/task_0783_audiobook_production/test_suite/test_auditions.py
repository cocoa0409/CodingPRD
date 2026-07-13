"""Audition submission, casting decisions, and audition-gated contract offers."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers, make_author_headers, make_narrator_headers,
    create_title_payload, create_audition_payload, create_contract_payload,
    onboard_author, onboard_narrator, new_title, open_title, submit_audition,
    setup_accepted_audition,
)


def test_admin_cannot_submit_audition(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/admin_cannot_submit_audition_returns_unauthorized
    """
    author = onboard_author(api)
    title = new_title(api, author["id"])
    open_title(api, title["id"], author["id"])
    resp = api.create_audition(create_audition_payload(title["id"]), admin_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_author_cannot_open_others_title(api):
    """PRD §2.1: "When an entity-backed caller invokes an operation that mutates
    a resource it does not own, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403), the same code used for a disallowed role."

    Design: Corner/rbac/author_cannot_open_others_title_returns_unauthorized
    """
    author_a = onboard_author(api)
    author_b = onboard_author(api)
    title = new_title(api, author_b["id"])  # owned by B
    resp = api.open_title(title["id"], make_author_headers(author_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_open_already_open_title_returns_invalid_state(api):
    """PRD §3.1: "Attempting to open a title that is not in `DRAFT` has no matching
    transition and is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/open_non_draft_title_returns_invalid_state
    """
    author = onboard_author(api)
    title = new_title(api, author["id"])
    open_title(api, title["id"], author["id"])  # now OPEN_FOR_AUDITION
    resp = api.open_title(title["id"], make_author_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_auditions_by_title_returns_children(api):
    """PRD §3.2: "Auditions can be listed and filtered by `title_id`, by
    `narrator_id`, and by `status`."

    Design: Corner/endpoints/list_auditions_by_title_returns_children
    """
    author = onboard_author(api)
    narrator = onboard_narrator(api)
    title = new_title(api, author["id"])
    open_title(api, title["id"], author["id"])
    audition = submit_audition(api, title["id"], narrator["id"])
    resp = api.list_auditions(make_author_headers(author["id"]), params={"title_id": title["id"]})
    data = validate_success(resp, 200)
    ids = [a["id"] for a in data]
    assert audition["id"] in ids
    for a in data:
        assert a["title_id"] == title["id"]


def test_offer_contract_without_accepted_audition_rejected(api):
    """PRD §3.3: "Offering also requires that an `ACCEPTED` audition exists for
    this exact title-and-narrator pairing; without it the offer is refused with
    `ERR_AUDITION_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/contract_offer_requires_accepted_audition
    """
    author = onboard_author(api)
    narrator = onboard_narrator(api)
    title = new_title(api, author["id"])
    opened = open_title(api, title["id"], author["id"])
    submit_audition(api, title["id"], narrator["id"])  # stays SUBMITTED
    payload = create_contract_payload(title["id"], narrator["id"], opened["version"])
    resp = api.create_contract(payload, make_author_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_AUDITION_NOT_ACCEPTED.value)


def test_offer_contract_after_declined_audition_rejected(api):
    """PRD §3.3: "Offering also requires that an `ACCEPTED` audition exists for
    this exact title-and-narrator pairing; without it the offer is refused with
    `ERR_AUDITION_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/contract_offer_requires_accepted_audition
    """
    author = onboard_author(api)
    narrator = onboard_narrator(api)
    title = new_title(api, author["id"])
    opened = open_title(api, title["id"], author["id"])
    audition = submit_audition(api, title["id"], narrator["id"])
    validate_success(
        api.decide_audition(audition["id"], {"decision": "DECLINE"}, make_author_headers(author["id"])), 200
    )
    payload = create_contract_payload(title["id"], narrator["id"], opened["version"])
    resp = api.create_contract(payload, make_author_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_AUDITION_NOT_ACCEPTED.value)
