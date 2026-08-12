"""Board tally quorum, and optimistic concurrency on member withdrawal
(PRD §2.5, §2.8, §3.7, §3.9)."""
from test_helpers import (
    validate_success, validate_error, api_client,
    create_district, create_member, create_fiscal_year, seat_delegate,
    set_clock, get_member, make_member_headers,
    resolution_payload, TEST_USERS,
)

SECRETARY = TEST_USERS["secretary_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_tally_rejected_when_quorum_not_met(api):
    """PRD §3.9: "When the voting window closes — or when every seated
    delegate has voted — the tally is taken. If the total votes cast fall
    short of `quorum_required`, tallying is rejected with
    `ERR_QUORUM_NOT_MET` (HTTP 422). With quorum met, the resolution passes
    only if `votes_for` exceeds `votes_against`, moving it to `PASSED`; a tie
    or majority against moves it to `REJECTED`."

    Design: Corner/errors/err_quorum_not_met_on_premature_tally
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(max_delegates=3)
    member = create_member(district["id"])
    delegate = seat_delegate(district["id"], member["id"])
    fy = create_fiscal_year()
    # Voting window already closed (year 2000), so the first recorded vote
    # triggers the tally with only 1 vote cast against a quorum of 3.
    res_created = api_client.create_board_resolution(
        resolution_payload(
            "AMEND_ALLOCATION", fy["id"], quorum_required=3,
        ),
        SECRETARY,
    )
    resolution = validate_success(res_created, 201)
    validate_success(api_client.open_voting(resolution["id"], SECRETARY))
    res = api_client.record_vote(
        resolution["id"], {"delegate_id": delegate["id"], "vote": "FOR"},
        SECRETARY,
    )
    validate_error(res, "ERR_QUORUM_NOT_MET", expected_status=422)
    after = validate_success(
        api_client.get_board_resolution(resolution["id"], SECRETARY),
    )
    assert after["status"] != "PASSED", (
        "A tally short of quorum must not pass the resolution"
    )


def test_withdraw_stale_member_version_returns_412(api):
    """PRD §2.8: "A member withdrawal must carry `expected_member_version`,
    the withdrawing client’s last observed `version` of the member record.
    If the member's current `version` has advanced since that observation —
    for instance because a certificate redemption cascaded an equity-balance
    update onto the member in the interim — the withdrawal is rejected with
    `ERR_STALE_MEMBER_VERSION` (HTTP 412), forcing the client to re-read the
    member and re-issue the request against the fresh version."

    Design: Corner/cross_cutting_layers/occ_member_withdraw_stale_version_returns_412
    """
    district = create_district()
    member = create_member(district["id"])
    stale_version = member["version"]
    # Two mutations advance the member's version beyond the observed value.
    validate_success(api.deactivate_member(member["id"], REGISTRAR))
    validate_success(api.reactivate_member(member["id"], REGISTRAR))
    res = api.withdraw_member(
        member["id"],
        {"expected_member_version": stale_version},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_STALE_MEMBER_VERSION", expected_status=412)
    after = get_member(member["id"])
    assert after["status"] == "ACTIVE", (
        "Rejected withdrawal must leave the member ACTIVE; got "
        f"{after['status']}"
    )


def test_withdraw_correct_version_succeeds(api):
    """PRD §3.7: "A member may also withdraw — an OCC-guarded write requiring
    `expected_member_version` — permitted only while the member is `ACTIVE`
    with no open redemption request and no open estate claim referencing
    them; withdrawal moves the member to `WITHDRAWN` and freezes all of the
    member's `ISSUED` and `ACTIVE` certificates pending a board resolution."
    PRD §2.5: "**`version`** (integer): starts at its initial value on
    creation and increments by one on every mutation of the resource,
    including mutations caused by cascading side effects from operations on
    other resources."

    Design: Corner/cross_cutting_layers/occ_member_withdraw_correct_version_succeeds
    """
    district = create_district()
    member = create_member(district["id"])
    version_before = member["version"]
    withdrawn = validate_success(
        api.withdraw_member(
            member["id"],
            {"expected_member_version": version_before},
            make_member_headers(member["id"]),
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == version_before + 1, (
        f"version must increment by one on mutation; got "
        f"{withdrawn['version']} (was {version_before})"
    )
