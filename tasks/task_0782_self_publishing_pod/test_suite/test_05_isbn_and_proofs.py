"""ISBN pool assignment/release (conserved invariant), assignment availability,
publish ISBN precondition, and the proof revision cycle.

Translates difficulty instances
`compensating_invariant/isbn_pool_count_conserved_on_assign_then_release` and
`non_linear_state_machine/format_revision_cycle_locked_back_to_draft`, plus
corner instances from section `validations`.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, make_publisher_headers,
    create_publisher, create_title, create_print_format,
    add_isbn, assign_isbn,
    setup_locked_print_format, order_proof, approve_proof,
)


# --- compensating_invariant: ISBN pool count ---------------------------------

def test_assign_isbn_sets_assigned_and_points_at_format(api):
    """PRD 3.4: "A successful assignment transitions the ISBN FREE -> ASSIGNED,
    sets its assigned_format_id to the format, sets the format's denormalized
    isbn_id, and increments Format.version by 1."

    Design: Difficulty/compensating_invariant/isbn_pool_count_conserved_on_assign_then_release
    """
    pub = create_publisher(api)
    isbn = add_isbn(api, pub["id"])
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    assign_isbn(api, pub["id"], fmt["id"], isbn["id"])
    got = get_success_data(api.get_isbn(isbn["id"], make_publisher_headers(pub["id"])))
    assert got["status"] == "ASSIGNED"
    assert got["assigned_format_id"] == fmt["id"]


def test_release_isbn_restores_free_and_clears_links(api):
    """PRD 3.4: "A publisher may reverse this as a compensation, releasing the
    assigned ISBN back to ASSIGNED -> FREE, clearing both assigned_format_id and
    the format's isbn_id, and again incrementing Format.version by 1."

    Design: Difficulty/compensating_invariant/isbn_pool_count_conserved_on_assign_then_release
    """
    pub = create_publisher(api)
    isbn = add_isbn(api, pub["id"])
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    headers = make_publisher_headers(pub["id"])
    assign_isbn(api, pub["id"], fmt["id"], isbn["id"])
    get_success_data(api.release_isbn(fmt["id"], headers))
    got_isbn = get_success_data(api.get_isbn(isbn["id"], headers))
    assert got_isbn["status"] == "FREE"
    assert got_isbn["assigned_format_id"] is None
    got_fmt = get_success_data(api.get_format(fmt["id"], headers))
    assert got_fmt["isbn_id"] is None


def test_assign_isbn_already_assigned_returns_not_available(api):
    """PRD 3.4: "the target Isbn must be FREE and must belong to the same
    publisher that owns the format, otherwise the assignment is rejected with
    ERR_ISBN_NOT_AVAILABLE (HTTP 409)."

    Design: Corner/validations/assign_isbn_already_assigned_returns_not_available
    """
    pub = create_publisher(api)
    isbn = add_isbn(api, pub["id"])
    title = create_title(api, pub["id"])
    fmt1 = create_print_format(api, pub["id"], title["id"], page_count=200)
    fmt2 = create_print_format(api, pub["id"], title["id"], page_count=180)
    assign_isbn(api, pub["id"], fmt1["id"], isbn["id"])
    validate_error(
        api.assign_isbn(fmt2["id"], {"isbn_id": isbn["id"]}, make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_ISBN_NOT_AVAILABLE,
    )


def test_publish_without_isbn_returns_isbn_not_assigned(api):
    """PRD 3.7: "The format must also carry an assigned ISBN: if isbn_id is null,
    publication is refused with ERR_ISBN_NOT_ASSIGNED (HTTP 409)."

    Design: Corner/validations/publish_without_isbn_returns_isbn_not_assigned
    """
    base = setup_locked_print_format(api, assign_isbn_too=False)
    pub, fmt = base["publisher"], base["format"]
    proof = order_proof(api, pub["id"], fmt["id"])
    approve_proof(api, pub["id"], proof["id"])
    validate_error(
        api.publish_format(fmt["id"], make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_ISBN_NOT_ASSIGNED,
    )


# --- non_linear_state_machine: revision cycle CONTENT_LOCKED -> DRAFT ---------

def test_request_revision_sets_proof_revision_requested(api):
    """PRD 3.4: "or requests a revision, moving it ORDERED -> REVISION_REQUESTED
    and capturing the optional revision_notes."

    Design: Difficulty/non_linear_state_machine/format_revision_cycle_locked_back_to_draft
    """
    base = setup_locked_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    proof = order_proof(api, pub["id"], fmt["id"])
    updated = get_success_data(api.request_revision(
        proof["id"], {"revision_notes": "fix chapter 3"}, make_publisher_headers(pub["id"])
    ))
    assert updated["status"] == "REVISION_REQUESTED"


def test_request_revision_unlocks_format_to_draft(api):
    """PRD 3.4: "if the parent format is currently CONTENT_LOCKED, the revision
    request transitions it back CONTENT_LOCKED -> DRAFT, unlocking the content so
    the interior or cover can be re-uploaded, and increments Format.version by 1."

    Design: Difficulty/non_linear_state_machine/format_revision_cycle_locked_back_to_draft
    """
    base = setup_locked_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    headers = make_publisher_headers(pub["id"])
    proof = order_proof(api, pub["id"], fmt["id"])
    api.request_revision(proof["id"], {"revision_notes": "fix chapter 3"}, headers)
    refetched = get_success_data(api.get_format(fmt["id"], headers))
    assert refetched["status"] == "DRAFT", "revision on a locked format must reopen it to DRAFT"
