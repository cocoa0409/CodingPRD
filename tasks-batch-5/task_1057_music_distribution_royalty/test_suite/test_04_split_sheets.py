"""Payees, split sheets, the path to a locked split, and the stale-track-version guard."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_split_sheet, assert_split_share,
    set_clock, create_plan, create_artist, create_active_subscription,
    create_release, add_track, create_collaborator, create_split_sheet, add_share,
    send_sheet, accept_share, lock_sheet, read_track, read_split_sheet, read_split_share,
    CLOCK_BASE, upc, isrc, make_artist_headers, make_collaborator_headers, make_admin_headers,
)


def _artist_with_track(email="artist@example.com", track_kwargs=None):
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist = create_artist(email=email)
    create_active_subscription(artist["id"], plan["id"])
    release = create_release(artist["id"], title="Record", upc=upc(1))
    track = add_track(release["id"], artist["id"], isrc=isrc(1), **(track_kwargs or {}))
    return artist, release, track


def test_split_share_junction_links_one_payee_across_two_sheets(api):
    """PRD §3.4: "Shares are added to a `DRAFT` sheet by naming the payee through
    `collaborator_id` and the entitlement through `share_bps`, a value between 1 and 10000
    inclusive."
    PRD §3.4: "Each addition recomputes the sheet's `total_share_bps` as the sum of `share_bps`
    across the sheet's shares and advances the sheet's `version` by 1."

    Design: Corner/entities/graph_topology_split_share_junction_links_sheet_and_collaborator
    """
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist = create_artist(email="aquila@example.com")
    create_active_subscription(artist["id"], plan["id"])
    release = create_release(artist["id"], title="Eagle", upc=upc(1))
    track_a = add_track(release["id"], artist["id"], title="Talon", track_number=1, isrc=isrc(1))
    track_b = add_track(release["id"], artist["id"], title="Wing", track_number=2, isrc=isrc(2))
    payee = create_collaborator(artist["id"], name="Shared", email="shared@example.com")

    sheet_a = create_split_sheet(track_a["id"], artist["id"],
                                 read_track(track_a["id"], artist["id"])["version"])
    sheet_b = create_split_sheet(track_b["id"], artist["id"],
                                 read_track(track_b["id"], artist["id"])["version"])

    share_a = validate_success(
        api.add_split_share(sheet_a["id"], {"collaborator_id": payee["id"], "share_bps": 10000},
                            make_artist_headers(artist["id"])),
        201,
    )
    share_b = validate_success(
        api.add_split_share(sheet_b["id"], {"collaborator_id": payee["id"], "share_bps": 10000},
                            make_artist_headers(artist["id"])),
        201,
    )
    assert_split_share(share_a)
    assert share_a["split_sheet_id"] == sheet_a["id"]
    assert share_a["accepted"] is False

    headers = make_artist_headers(artist["id"])
    _rows, meta = validate_paginated(
        api.list_split_shares(headers, params={"collaborator_id": payee["id"]})
    )
    assert meta["total_count"] == 2

    rows_a, meta_a = validate_paginated(
        api.list_split_shares(headers, params={"split_sheet_id": sheet_a["id"]})
    )
    assert meta_a["total_count"] == 1 and rows_a[0]["id"] == share_a["id"]

    rows_b, meta_b = validate_paginated(
        api.list_split_shares(headers, params={"split_sheet_id": sheet_b["id"]})
    )
    assert meta_b["total_count"] == 1 and rows_b[0]["id"] == share_b["id"]

    assert read_split_sheet(sheet_a["id"], artist["id"])["total_share_bps"] == 10000
    assert read_split_sheet(sheet_b["id"], artist["id"])["total_share_bps"] == 10000


def test_send_split_sheet_with_zero_shares_reports_empty_not_total_invalid(api):
    """PRD §3.4: "Two conditions guard that step: the sheet must hold at least one share,
    otherwise `ERR_SPLIT_SHEET_EMPTY` (HTTP 422), and `total_share_bps` must equal exactly 10000 —
    the whole of the recording, no more and no less — otherwise `ERR_SPLIT_TOTAL_INVALID`
    (HTTP 422)."
    PRD §3.4: "Both of these same two conditions are re-checked at lock time as well, in the same
    order and with the same codes; they guard those two operations and no others."

    Design: Difficulty/boundary_precision_check/send_split_sheet_with_zero_shares_hits_empty_collection_guard
    """
    artist, _release, track = _artist_with_track(email="corvus@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])

    resp = api.send_split_sheet(sheet["id"], make_artist_headers(artist["id"]))
    error = validate_error(resp, ApiErrorId.ERR_SPLIT_SHEET_EMPTY.value)

    assert error["error_id"] != ApiErrorId.ERR_SPLIT_TOTAL_INVALID.value, (
        "the empty-collection guard is evaluated before the total-bps guard"
    )
    stored = read_split_sheet(sheet["id"], artist["id"])
    assert stored["status"] == "DRAFT"
    assert stored["total_share_bps"] == 0


def test_zero_share_sheet_becomes_sendable_once_one_full_share_exists(api):
    """PRD §3.4: "Two conditions guard that step: the sheet must hold at least one share,
    otherwise `ERR_SPLIT_SHEET_EMPTY` (HTTP 422), and `total_share_bps` must equal exactly 10000 —
    the whole of the recording, no more and no less — otherwise `ERR_SPLIT_TOTAL_INVALID`
    (HTTP 422)."
    PRD §3.4: "Circulating the sheet for signature moves it `DRAFT → PENDING_ACCEPTANCE` and
    advances its `version` by 1."

    Design: Difficulty/boundary_precision_check/send_split_sheet_with_zero_shares_hits_empty_collection_guard
    """
    artist, _release, track = _artist_with_track(email="corvus2@example.com")
    payee = create_collaborator(artist["id"], name="Feather", email="feather@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])

    empty = api.send_split_sheet(sheet["id"], make_artist_headers(artist["id"]))
    validate_error(empty, ApiErrorId.ERR_SPLIT_SHEET_EMPTY.value)

    _rows, meta = validate_paginated(
        api.list_split_shares(make_artist_headers(artist["id"]),
                              params={"split_sheet_id": sheet["id"]})
    )
    assert meta["total_count"] == 0

    add_share(sheet["id"], artist["id"], payee["id"], 10000)
    sent = validate_success(api.send_split_sheet(sheet["id"], make_artist_headers(artist["id"])))
    assert sent["status"] == "PENDING_ACCEPTANCE"


def test_sending_a_sheet_that_does_not_total_ten_thousand_bps_rejected(api):
    """PRD §3.4: "Two conditions guard that step: the sheet must hold at least one share,
    otherwise `ERR_SPLIT_SHEET_EMPTY` (HTTP 422), and `total_share_bps` must equal exactly 10000 —
    the whole of the recording, no more and no less — otherwise `ERR_SPLIT_TOTAL_INVALID`
    (HTTP 422)."

    Design: Corner/validations/sending_a_sheet_whose_shares_do_not_total_10000_bps_rejected
    """
    artist, _release, track = _artist_with_track(email="volans@example.com")
    c1 = create_collaborator(artist["id"], name="V1", email="v1@example.com")
    c2 = create_collaborator(artist["id"], name="V2", email="v2@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])
    add_share(sheet["id"], artist["id"], c1["id"], 4000)
    add_share(sheet["id"], artist["id"], c2["id"], 5000)

    resp = api.send_split_sheet(sheet["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_SPLIT_TOTAL_INVALID.value)

    stored = read_split_sheet(sheet["id"], artist["id"])
    assert stored["status"] == "DRAFT"
    assert stored["total_share_bps"] == 9000


def test_one_rejection_returns_the_whole_sheet_to_draft(api):
    """PRD §3.4: "Rejection is far more destructive and is deliberately so: a single payee
    rejecting, with a `reason_code` recorded for the artist's benefit, returns the whole sheet
    from `PENDING_ACCEPTANCE` back to `DRAFT`, clears `accepted` to false and `accepted_at` to
    null on"
    PRD §3.4: "share of that sheet — not merely the rejecting one — resets `accepted_share_count`
    to 0, advances the sheet's `version` by 1, and advances the rejecting share's `version` by 1."

    Design: Corner/state_machines/split_share_reject_cycles_sheet_to_draft_and_clears_all_acceptances
    """
    artist, _release, track = _artist_with_track(email="columba@example.com")
    c1 = create_collaborator(artist["id"], name="Ada", email="ada@example.com")
    c2 = create_collaborator(artist["id"], name="Bo", email="bo@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])
    share_1 = add_share(sheet["id"], artist["id"], c1["id"], 5000)
    share_2 = add_share(sheet["id"], artist["id"], c2["id"], 5000)
    send_sheet(sheet["id"], artist["id"])
    accept_share(share_1["id"], c1["id"])

    validate_success(
        api.reject_split_share(share_2["id"], "SPLIT_TOO_LOW", make_collaborator_headers(c2["id"]))
    )

    stored = read_split_sheet(sheet["id"], artist["id"])
    assert stored["status"] == "DRAFT"
    assert stored["accepted_share_count"] == 0
    assert stored["total_share_bps"] == 10000, "the shares themselves survive the rejection"

    first = read_split_share(share_1["id"], artist["id"])
    assert first["accepted"] is False, "every share is cleared, not merely the rejecting one"
    assert first["accepted_at"] is None
    assert read_split_share(share_2["id"], artist["id"])["accepted"] is False


def test_locking_a_sheet_with_an_unaccepted_share_rejected(api):
    """PRD §3.4: "Locking is the artist's final step and requires unanimity: the sheet must be in
    `PENDING_ACCEPTANCE`, its `accepted_share_count` must equal the total number of its shares,
    and that count must be at least 1."
    PRD §3.4: "A lock attempted while any share is still unaccepted is refused with
    `ERR_SPLIT_NOT_ACCEPTED` (HTTP 409)."
    PRD §3.3: "A newly added track has `status` `PENDING` — the enumeration is `PENDING`,
    `ACTIVE`, `INACTIVE` — and a null `locked_split_sheet_id`, which is a computed pointer to
    whichever of the track's split sheets is currently locked rather than a field the client ever
    writes."

    Design: Corner/validations/locking_a_sheet_with_an_unaccepted_share_rejected
    """
    artist, _release, track = _artist_with_track(email="ara@example.com")
    c1 = create_collaborator(artist["id"], name="A1", email="a1@example.com")
    c2 = create_collaborator(artist["id"], name="A2", email="a2@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])
    share_1 = add_share(sheet["id"], artist["id"], c1["id"], 5000)
    add_share(sheet["id"], artist["id"], c2["id"], 5000)
    send_sheet(sheet["id"], artist["id"])
    accept_share(share_1["id"], c1["id"])

    resp = api.lock_split_sheet(sheet["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_SPLIT_NOT_ACCEPTED.value)

    stored = read_split_sheet(sheet["id"], artist["id"])
    assert stored["status"] == "PENDING_ACCEPTANCE"
    assert stored["accepted_share_count"] == 1
    assert read_track(track["id"], artist["id"])["locked_split_sheet_id"] is None


def test_locking_a_newer_sheet_supersedes_the_previous_locked_sheet(api):
    """PRD §3.4: "A successful lock moves the sheet `PENDING_ACCEPTANCE → LOCKED`, stamps
    `locked_at` with the current instant, writes the sheet's identifier into the parent track's
    `locked_split_sheet_id`, and — this is the cascade that makes re-splitting possible — moves
    any other sheet of the same track that was in `LOCKED` to `SUPERSEDED`, advancing that
    superseded sheet's `version` by 1 as well as the newly locked sheet's own `version`."
    PRD §3.4: "A track therefore has at most one locked sheet at any instant, and that sheet is
    the one every later allocation reads."

    Design: Corner/state_machines/locking_a_newer_sheet_supersedes_the_previous_locked_sheet
    """
    artist, _release, track = _artist_with_track(email="norma2@example.com")
    payee = create_collaborator(artist["id"], name="Solo", email="solo2@example.com")

    sheet_a = create_split_sheet(track["id"], artist["id"],
                                 read_track(track["id"], artist["id"])["version"])
    share_a = add_share(sheet_a["id"], artist["id"], payee["id"], 10000)
    send_sheet(sheet_a["id"], artist["id"])
    accept_share(share_a["id"], payee["id"])
    lock_sheet(sheet_a["id"], artist["id"])

    sheet_b = create_split_sheet(track["id"], artist["id"],
                                 read_track(track["id"], artist["id"])["version"],
                                 effective_from="2026-06-01T00:00:00Z")
    share_b = add_share(sheet_b["id"], artist["id"], payee["id"], 10000)
    send_sheet(sheet_b["id"], artist["id"])
    accept_share(share_b["id"], payee["id"])

    locked_b = validate_success(
        api.lock_split_sheet(sheet_b["id"], make_artist_headers(artist["id"]))
    )

    assert locked_b["status"] == "LOCKED"
    assert read_split_sheet(sheet_a["id"], artist["id"])["status"] == "SUPERSEDED"
    assert read_track(track["id"], artist["id"])["locked_split_sheet_id"] == sheet_b["id"]

    _rows, meta = validate_paginated(
        api.list_split_sheets(make_artist_headers(artist["id"]),
                              params={"track_id": track["id"]})
    )
    assert meta["total_count"] == 2


def test_collaborator_cannot_accept_another_payees_share(api):
    """PRD §2.1: "A `Collaborator` is a payee who accepts or rejects split shares and reads their
    own payouts and tax forms. When `X-User-Role` is `Collaborator`, `X-User-ID` is the `id` of
    the acting `Collaborator` record; ownership checks compare a share's or payout's
    `collaborator_id` to `X-User-ID`."
    PRD §2.1: "When an entity-backed role — `Artist` or `Collaborator` — addresses a resource that
    belongs to somebody else, the request is refused with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/collaborator_cannot_accept_another_payees_share
    """
    artist, _release, track = _artist_with_track(email="pyxis2@example.com")
    c_a = create_collaborator(artist["id"], name="PA", email="pa@example.com")
    c_b = create_collaborator(artist["id"], name="PB", email="pb@example.com")
    sheet = create_split_sheet(track["id"], artist["id"],
                               read_track(track["id"], artist["id"])["version"])
    share_a = add_share(sheet["id"], artist["id"], c_a["id"], 5000)
    add_share(sheet["id"], artist["id"], c_b["id"], 5000)
    send_sheet(sheet["id"], artist["id"])

    resp = api.accept_split_share(share_a["id"], make_collaborator_headers(c_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

    assert read_split_share(share_a["id"], artist["id"])["accepted"] is False
    assert read_split_sheet(sheet["id"], artist["id"])["accepted_share_count"] == 0


def test_split_sheet_create_with_stale_track_version_returns_stale_version(api):
    """PRD §2.7: "In both cases the caller must supply, as a required (never optional) field of
    the request body, the `version` value they last observed on that parent. If it does not equal
    the parent's current `version`, the write is refused with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is mutated."
    PRD §3.4: "Creating one names the recording through `track_id`, states the `effective_from`
    instant from which the sheet governs allocation, and — because the create is guarded against
    stale client state — must carry `expected_track_version` matching the track's current
    `version`, failing which the create is refused with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "A successful create yields a sheet in `DRAFT`, with `total_share_bps` and
    `accepted_share_count` at 0 and `locked_at` null, and advances the parent track's `version`
    by 1."

    Design: Corner/cross_cutting_layers/split_sheet_create_with_stale_track_version_returns_412
    """
    artist, _release, track = _artist_with_track(email="cepheus@example.com")
    headers = make_artist_headers(artist["id"])
    version_1 = track["version"]

    first = create_split_sheet(track["id"], artist["id"], version_1)
    assert_split_sheet(first)
    assert first["status"] == "DRAFT" and first["total_share_bps"] == 0

    stale = api.create_split_sheet(
        {"track_id": track["id"], "effective_from": "2026-02-01T00:00:00Z",
         "expected_track_version": version_1},
        headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    _rows, meta = validate_paginated(
        api.list_split_sheets(headers, params={"track_id": track["id"]})
    )
    assert meta["total_count"] == 1, "the stale create must mutate nothing"

    version_2 = read_track(track["id"], artist["id"])["version"]
    assert version_2 == version_1 + 1, "each successful create advances the track's version by 1"

    retried = validate_success(
        api.create_split_sheet(
            {"track_id": track["id"], "effective_from": "2026-02-01T00:00:00Z",
             "expected_track_version": version_2},
            headers,
        ),
        201,
    )
    assert retried["status"] == "DRAFT"

    _rows2, meta2 = validate_paginated(
        api.list_split_sheets(headers, params={"track_id": track["id"]})
    )
    assert meta2["total_count"] == 2
