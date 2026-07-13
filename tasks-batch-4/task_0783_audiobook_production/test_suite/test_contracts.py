"""Contract offering, deal-type coherence, responses, and OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_author_headers, make_narrator_headers,
    onboard_narrator,
    setup_accepted_audition, setup_offered_contract, setup_accepted_contract,
    accept_contract,
)


def test_contract_missing_deal_type_returns_validation(api):
    """PRD §2.6: "A malformed body, a missing required field, or a bad type or
    enum value is rejected earlier with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_contract_missing_deal_type_returns_validation
    """
    ctx = setup_accepted_audition(api)
    payload = {
        "title_id": ctx["title"]["id"],
        "narrator_id": ctx["narrator"]["id"],
        "royalty_share_pct": 0.30,
        "expected_title_version": ctx["title_version"],
    }
    resp = api.create_contract(payload, make_author_headers(ctx["author"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_royalty_share_missing_pct_returns_deal_type_fields(api):
    """PRD §3.3: "Supplying the wrong field for the deal type, or omitting the
    required one, is a deal-coherence failure rejected with `ERR_DEAL_TYPE_FIELDS`."

    Design: Corner/validations/contract_royalty_share_missing_pct_returns_deal_type_fields
    """
    ctx = setup_accepted_audition(api)
    payload = {
        "title_id": ctx["title"]["id"],
        "narrator_id": ctx["narrator"]["id"],
        "deal_type": "ROYALTY_SHARE",
        "expected_title_version": ctx["title_version"],
    }
    resp = api.create_contract(payload, make_author_headers(ctx["author"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DEAL_TYPE_FIELDS.value)


def test_respond_on_accepted_contract_returns_not_offered(api):
    """PRD §3.3: "Both responses require that the caller is the contract's narrator
    and that the contract is still `OFFERED`; a response to a contract that is not
    `OFFERED` is refused with `ERR_CONTRACT_NOT_OFFERED`."

    Design: Corner/state_machines/respond_on_non_offered_contract_returns_invalid_state
    """
    ctx = setup_accepted_contract(api)  # contract ACCEPTED
    resp = api.respond_contract(
        ctx["contract"]["id"], {"decision": "DECLINE"}, make_narrator_headers(ctx["narrator"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_OFFERED.value)
    reread = validate_success(api.get_contract(ctx["contract"]["id"], make_narrator_headers(ctx["narrator"]["id"])), 200)
    assert reread["status"] == "ACCEPTED"


def test_respond_missing_contract_returns_not_found(api):
    """PRD §2.6: "a missing `contract_id` yields `ERR_CONTRACT_NOT_FOUND`".

    Design: Corner/errors/error_contract_not_found_on_respond
    """
    narrator = onboard_narrator(api)
    resp = api.respond_contract(
        "00000000-0000-4000-8000-000000000001", {"decision": "ACCEPT"},
        make_narrator_headers(narrator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)


def test_contract_accept_moves_title_to_production(api):
    """PRD §3.3: "Accepting a contract moves it `OFFERED → ACCEPTED` and drives
    the title `CASTING → IN_PRODUCTION`, opening the door to production delivery;
    the contract's version is bumped."

    Design: Corner/consistency_model/contract_accept_immediately_moves_title_to_production
    """
    ctx = setup_offered_contract(api)
    contract = accept_contract(api, ctx["contract"]["id"], ctx["narrator"]["id"])
    assert contract["status"] == "ACCEPTED"
    title = validate_success(api.get_title(ctx["title"]["id"], make_author_headers(ctx["author"]["id"])), 200)
    assert title["status"] == "IN_PRODUCTION"


def test_decline_contract_sets_declined(api):
    """PRD §3.3: "Declining moves the contract `OFFERED → DECLINED` and returns
    the title `CASTING → OPEN_FOR_AUDITION` so the author can cast someone else."

    Design: Difficulty/non_linear_state_machine/contract_offered_branches_to_declined
    """
    ctx = setup_offered_contract(api)
    resp = api.respond_contract(
        ctx["contract"]["id"], {"decision": "DECLINE"}, make_narrator_headers(ctx["narrator"]["id"])
    )
    contract = validate_success(resp, 200)
    assert contract["status"] == "DECLINED"


def test_decline_contract_returns_title_to_open(api):
    """PRD §3.3: "Declining moves the contract `OFFERED → DECLINED` and returns
    the title `CASTING → OPEN_FOR_AUDITION` so the author can cast someone else."

    Design: Difficulty/non_linear_state_machine/contract_offered_branches_to_declined
    """
    ctx = setup_offered_contract(api)
    validate_success(
        api.respond_contract(ctx["contract"]["id"], {"decision": "DECLINE"}, make_narrator_headers(ctx["narrator"]["id"])), 200
    )
    title = validate_success(api.get_title(ctx["title"]["id"], make_author_headers(ctx["author"]["id"])), 200)
    assert title["status"] == "OPEN_FOR_AUDITION"


def test_stale_title_version_offer_rejected(api):
    """PRD §2.5: "The server compares `expected_title_version` against the title's
    current `version`; if they do not match, the offer is rejected with
    `ERR_STALE_TITLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/contract_offer_stale_title_version_returns_412
    """
    ctx = setup_offered_contract(api)  # first offer landed, title.version advanced
    # Second offer still carries the pre-offer expected_title_version (stale).
    payload = {
        "title_id": ctx["title"]["id"],
        "narrator_id": ctx["narrator"]["id"],
        "deal_type": "ROYALTY_SHARE",
        "royalty_share_pct": 0.35,
        "expected_title_version": ctx["title_version"],
    }
    resp = api.create_contract(payload, make_author_headers(ctx["author"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_TITLE_VERSION.value)
