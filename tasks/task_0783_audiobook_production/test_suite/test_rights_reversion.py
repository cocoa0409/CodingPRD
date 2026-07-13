"""Rights reversion and its consistency cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers, make_author_headers, make_narrator_headers,
    create_audition_payload,
    setup_published_title, setup_provisional_statement,
)

_ONE_SALE = [
    {"units_sold": 10, "units_returned": 0, "unit_price_cents": 1500, "occurred_at": "2026-03-15T00:00:00Z"},
]


def test_revert_terminates_contract_and_withdraws_listing(api):
    """PRD §3.8: "It sets the title's `rights_status` to `REVERTED`. The title's
    `ACCEPTED` contract is terminated, moving it `ACCEPTED → TERMINATED`. Every
    `ACTIVE` distribution listing for the title is withdrawn, moving each
    `ACTIVE → WITHDRAWN`."

    Design: Difficulty/transitive_cascade/rights_reversion_four_hop_chain
    """
    ctx = setup_provisional_statement(api, sales=_ONE_SALE)
    author_id = ctx["author"]["id"]
    validate_success(api.revert_rights(ctx["title"]["id"], make_author_headers(author_id)), 200)

    title = validate_success(api.get_title(ctx["title"]["id"], make_author_headers(author_id)), 200)
    assert title["status"] == "REVERTED"
    assert title["rights_status"] == "REVERTED"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], admin_headers()), 200)
    assert contract["status"] == "TERMINATED"
    listing = validate_success(api.get_listing(ctx["listing"]["id"], admin_headers()), 200)
    assert listing["status"] == "WITHDRAWN"


def test_revert_freezes_open_statement(api):
    """PRD §3.8: "And every royalty statement for the title that is still open —
    in `PROVISIONAL` or `FINALIZED` status — is frozen, moving `PROVISIONAL →
    FROZEN` or `FINALIZED → FROZEN` respectively, so that no further money moves
    on a title whose rights have been surrendered."

    Design: Difficulty/transitive_cascade/rights_reversion_four_hop_chain
    """
    ctx = setup_provisional_statement(api, sales=_ONE_SALE)
    author_id = ctx["author"]["id"]
    validate_success(api.revert_rights(ctx["title"]["id"], make_author_headers(author_id)), 200)
    statement = validate_success(api.get_statement(ctx["statement"]["id"], admin_headers()), 200)
    assert statement["status"] == "FROZEN"


def test_revert_already_reverted_title_rejected(api):
    """PRD §3.8: "Reverting requires that the caller owns the title, that the title
    is currently `PUBLISHED` — a revert on a non-published title is refused with
    `ERR_TITLE_NOT_REVERTABLE` — and that its `rights_status` is still `ACTIVE`."

    Design: Corner/state_machines/revert_rights_on_reverted_title_terminal_lockdown
    """
    ctx = setup_published_title(api)
    author_id = ctx["author"]["id"]
    validate_success(api.revert_rights(ctx["title"]["id"], make_author_headers(author_id)), 200)
    resp = api.revert_rights(ctx["title"]["id"], make_author_headers(author_id))
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_REVERTABLE.value)


def test_audition_on_reverted_title_rejected(api):
    """PRD §2.8: "Any production or distribution mutation on a title whose
    `rights_status` is `REVERTED` is refused with `ERR_RIGHTS_REVERTED` (HTTP 409)."

    Design: Corner/validations/audition_on_reverted_title_returns_rights_reverted
    """
    ctx = setup_published_title(api)
    author_id = ctx["author"]["id"]
    validate_success(api.revert_rights(ctx["title"]["id"], make_author_headers(author_id)), 200)
    resp = api.create_audition(
        create_audition_payload(ctx["title"]["id"], sample_url="http://sample/after-revert"),
        make_narrator_headers(ctx["narrator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RIGHTS_REVERTED.value)
