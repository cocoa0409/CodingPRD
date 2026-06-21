"""The custom design queue: quote / revision / approve / decline negotiation.

Covers the cyclic QUOTED -> REVISION_REQUESTED -> QUOTED negotiation loop, the
quote-validation rule, and the compensating-action invariant that declining a
custom request leaves an artist's flash catalogue untouched.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_artist_headers, make_client_headers,
    create_pending_custom_request, create_artist, create_client,
    create_flash_design,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]


def test_quote_revision_quote_cycle_returns_to_quoted(api):
    """PRD §3.4: "From `QUOTED`, the `Client` may bounce the quote back for
    rework, moving the request from `QUOTED` to `REVISION_REQUESTED`; this then
    re-opens it for a fresh quote, closing the `QUOTED` → `REVISION_REQUESTED` →
    `QUOTED` negotiation cycle."

    Design: Difficulty/non_linear_state_machine/custom_request_quote_revision_cycle
    """
    artist, client, request = create_pending_custom_request()
    ah = make_artist_headers(artist["id"])
    ch = make_client_headers(client["id"])
    get_success_data(
        api.quote_custom_request(request["id"],
                                 factories.quote_payload(quoted_price_cents=60000, estimated_minutes=240), ah)
    )
    get_success_data(api.request_revision_custom_request(request["id"], ch))
    re_quoted = get_success_data(
        api.quote_custom_request(request["id"],
                                 factories.quote_payload(quoted_price_cents=50000, estimated_minutes=200), ah)
    )
    assert re_quoted["status"] == "QUOTED", f"cycle must return to QUOTED, got {re_quoted['status']}"


def test_quote_revision_quote_cycle_overwrites_quote_fields(api):
    """PRD §3.4: "On a valid quote the request's `quoted_price_cents`,
    `quoted_hourly_rate_cents`, and `estimated_minutes` are set from the request;
    when the source state was `REVISION_REQUESTED`, these fields are overwritten
    with the new values, supporting repeated negotiation rounds."

    Design: Difficulty/non_linear_state_machine/custom_request_quote_revision_cycle
    """
    artist, client, request = create_pending_custom_request()
    ah = make_artist_headers(artist["id"])
    ch = make_client_headers(client["id"])
    get_success_data(
        api.quote_custom_request(request["id"],
                                 factories.quote_payload(quoted_price_cents=60000, estimated_minutes=240), ah)
    )
    get_success_data(api.request_revision_custom_request(request["id"], ch))
    re_quoted = get_success_data(
        api.quote_custom_request(request["id"],
                                 factories.quote_payload(quoted_price_cents=50000, estimated_minutes=200), ah)
    )
    assert re_quoted["quoted_price_cents"] == 50000, \
        f"re-quote must overwrite price, got {re_quoted['quoted_price_cents']}"
    assert re_quoted["estimated_minutes"] == 200, \
        f"re-quote must overwrite estimated_minutes, got {re_quoted['estimated_minutes']}"


def test_quote_missing_both_price_fields_rejected(api):
    """PRD §3.4: "A quote that supplies neither a price nor an hourly rate is
    rejected with `ERR_VALIDATION`."

    Design: Corner/validations/quote_missing_both_price_fields_rejected
    """
    artist, client, request = create_pending_custom_request()
    resp = api.quote_custom_request(
        request["id"], {"estimated_minutes": 180}, make_artist_headers(artist["id"])
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_decline_request_sets_declined(api):
    """PRD §3.4: "An `Artist` may decline a request that is in either `PENDING`
    or `REVISION_REQUESTED`, moving it to the terminal `DECLINED`."

    Design: Difficulty/compensating_invariant/custom_request_decline_conserves_queue_slot_count
    """
    artist = create_artist(hourly_rate_cents=16000)
    create_flash_design(artist["id"], title="Koi", piece_price_cents=40000, estimated_minutes=90)
    client = create_client()
    request = get_success_data(
        api.create_custom_request(
            factories.create_custom_request_payload(artist["id"], client["id"], brief="Phoenix back piece"),
            make_client_headers(client["id"]),
        )
    )
    declined = get_success_data(
        api.decline_custom_request(request["id"], make_artist_headers(artist["id"]))
    )
    assert declined["status"] == "DECLINED", f"expected DECLINED, got {declined['status']}"


def test_decline_request_conserves_flash_catalogue(api):
    """PRD §3.4: "An `Artist` may decline a request that is in either `PENDING`
    or `REVISION_REQUESTED`, moving it to the terminal `DECLINED`."
    PRD §3.3: "A flash design's `status` follows the availability lifecycle
    `AVAILABLE`, `RESERVED`, and `RETIRED`, beginning at `AVAILABLE`."

    Declining a custom request touches the request queue only; the artist's one
    AVAILABLE flash design must remain AVAILABLE (conserved quantity).

    Design: Difficulty/compensating_invariant/custom_request_decline_conserves_queue_slot_count
    """
    artist = create_artist(hourly_rate_cents=16000)
    flash = create_flash_design(artist["id"], title="Koi", piece_price_cents=40000, estimated_minutes=90)
    client = create_client()
    request = get_success_data(
        api.create_custom_request(
            factories.create_custom_request_payload(artist["id"], client["id"], brief="Phoenix back piece"),
            make_client_headers(client["id"]),
        )
    )
    get_success_data(api.decline_custom_request(request["id"], make_artist_headers(artist["id"])))
    after = get_success_data(api.get_flash_design(flash["id"], MANAGER))
    assert after["status"] == "AVAILABLE", \
        f"flash catalogue must be conserved (AVAILABLE), got {after['status']}"
