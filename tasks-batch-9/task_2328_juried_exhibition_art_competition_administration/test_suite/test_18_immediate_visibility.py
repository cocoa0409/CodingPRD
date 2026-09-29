"""Writes are visible the instant they return: the mutating response carries the
updated record itself, the cascade it triggered is readable on the very next
request, and a different role reading the same record sees the same version."""

from test_helpers import (
    CALL_MANAGER,
    JURY_CHAIR_A,
    fixtures,
    make_artist_headers,
    validate_paginated,
    validate_success,
)

TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]
MEMBER_TWO_WORK_FEE_CENTS = 3713


def test_the_fee_payment_response_already_shows_its_own_cascade(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    PRD §3.3: "A successful payment records `fee_paid_cents`, advances the entry
    `PENDING_FEE → SUBMITTED`, and cascades: every work of the entry whose
    `status` is `DRAFT` advances to `SUBMITTED`, each such work's own `version`
    incrementing by 1 alongside the entry's."

    PRD §3.3: "The base line is the exhibition's `entry_fee_base_cents`
    multiplied by one minus that discount fraction, rounded half up to whole
    cents."

    PRD §2.4: "**`version` (integer)** — a counter that begins at 1 on creation
    and increments by exactly 1 on every mutation of that record."

    Design: Corner/consistency_model/immediate_visibility_of_cascade_within_the_same_response
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, TWO_WORKS
    )
    artist_headers = make_artist_headers(artist["id"])

    submitted = fixtures.submit_entry(entry["id"], artist)
    assert submitted["status"] == "PENDING_FEE"
    assert submitted["entry_fee_cents"] == MEMBER_TWO_WORK_FEE_CENTS
    assert submitted["fee_paid_cents"] == 0

    # The write's own response body is the observation point — no second read.
    paid = validate_success(
        api.pay_entry_fee(
            entry["id"], {"amount_cents": MEMBER_TWO_WORK_FEE_CENTS},
            artist_headers,
        )
    )
    assert paid["status"] == "SUBMITTED"
    assert paid["entry_fee_cents"] == MEMBER_TWO_WORK_FEE_CENTS
    assert paid["fee_paid_cents"] == MEMBER_TWO_WORK_FEE_CENTS
    assert paid["works_count"] == len(TWO_WORKS)
    assert paid["version"] == submitted["version"] + 1

    # The cascade the same call performed is readable on the next request.
    cascaded, meta = validate_paginated(
        api.list_artworks(artist_headers, params={"entry_id": entry["id"]})
    )
    assert meta["total_count"] == len(TWO_WORKS)
    assert [work["status"] for work in cascaded] == ["SUBMITTED"] * len(TWO_WORKS)
    assert [work["id"] for work in cascaded] == [
        created["id"] for created in artworks
    ]

    # Visibility is not per-actor: two other roles read the same figures.
    by_manager = validate_success(api.get_entry(entry["id"], CALL_MANAGER))
    assert by_manager["status"] == "SUBMITTED"
    assert by_manager["version"] == paid["version"]
    assert by_manager["works_count"] == len(TWO_WORKS)
    assert by_manager["fee_paid_cents"] == MEMBER_TWO_WORK_FEE_CENTS

    by_chair = validate_success(api.get_entry(entry["id"], JURY_CHAIR_A))
    assert by_chair["version"] == paid["version"]
    assert by_chair["submitted_at"] == submitted["submitted_at"]
