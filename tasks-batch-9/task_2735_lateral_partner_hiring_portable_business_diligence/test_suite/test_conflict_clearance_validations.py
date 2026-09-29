"""Conflicts validations: the direct-adverse gate on both cure routes, the waiver route
that does work, and the matter-type subset rule on the check itself."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    create_conflict_check_payload,
    create_conflict_waiver_payload,
    clear_conflict_check_payload,
    grant_waiver_payload,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_conflict_check,
    setup_assessed_candidate,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]


def test_a_directly_adverse_check_resists_both_a_direct_clear_and_an_ethical_wall():
    """But a check whose `severity` is `DIRECT_ADVERSE` may **not** be cleared this way — a
    directly adverse conflict cannot be waved through without a client waiver — and the
    attempt is refused with `ERR_DIRECT_ADVERSE_REQUIRES_WAIVER`.
    One strategy is barred by severity: an `ETHICAL_WALL` may not be used to cure a
    `DIRECT_ADVERSE` check, because a screen cannot fix direct adversity, and that
    combination is refused with `ERR_DIRECT_ADVERSE_REQUIRES_WAIVER`.

    Design: Corner/validations/direct_adverse_check_cannot_be_cleared_directly
    """
    ctx = _setup_direct_adverse_check()
    check_id = ctx["direct_adverse_check"]["id"]

    direct = api_client.clear_conflict_check(
        check_id, clear_conflict_check_payload(), COUNSEL
    )
    validate_error(direct, ApiErrorId.ERR_DIRECT_ADVERSE_REQUIRES_WAIVER.value)

    screen = api_client.create_conflict_waiver(
        check_id,
        create_conflict_waiver_payload(
            waiver_strategy="ETHICAL_WALL",
            requested_from_client="Vertex Capital Partners",
        ),
        COUNSEL,
    )
    validate_error(screen, ApiErrorId.ERR_DIRECT_ADVERSE_REQUIRES_WAIVER.value)

    check = read_conflict_check(check_id)
    assert check["status"] == "PENDING"
    assert check["resolution_note"] is None
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "IN_PROGRESS"

    entry = read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])
    assert entry["portable_status"] == "VALIDATED"
    assert_money_equals(
        entry["validated_portable_amount_usd"], 1269000.00, "validated_portable_amount_usd"
    )


def test_an_advance_consent_waiver_is_the_route_that_clears_direct_adversity():
    """The waiver lands with `status` `REQUESTED` and `decided_at` null, and the parent
    check moves `PENDING → WAIVER_PENDING`.
    **Granted**: the counsel records the client's consent with a `resolution_note`,
    provided the waiver's `status` is still `REQUESTED` and the current logical clock is at
    or before the `response_deadline_date`; `decided_at` is set to the current clock
    instant, the waiver becomes `REQUESTED → GRANTED`, the parent check moves
    `WAIVER_PENDING → CLEAR`, and the candidate's `clearance_status` is recomputed and may
    become `CLEARED`.

    Design: Corner/validations/direct_adverse_cleared_through_a_granted_advance_consent_waiver
    """
    ctx = _setup_direct_adverse_check()
    check_id = ctx["direct_adverse_check"]["id"]

    waiver = validate_success(
        api_client.create_conflict_waiver(
            check_id,
            create_conflict_waiver_payload(
                waiver_strategy="ADVANCE_CONSENT",
                requested_from_client="Northwind Holdings",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )
    assert waiver["status"] == "REQUESTED"
    assert waiver["decided_at"] is None
    assert read_conflict_check(check_id)["status"] == "WAIVER_PENDING"

    granted = validate_success(
        api_client.grant_conflict_waiver(
            waiver["id"],
            grant_waiver_payload(
                resolution_note=(
                    "Client signed an advance-consent letter covering the M&A matters."
                )
            ),
            COUNSEL,
        )
    )
    assert granted["status"] == "GRANTED"
    assert_instant_equals(granted["decided_at"], "2026-08-01T00:00:00.000Z", "decided_at")

    assert read_conflict_check(check_id)["status"] == "CLEAR"

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "CLEARED"
    assert candidate["pipeline_status"] == "DILIGENCE"

    assert (
        read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])[
            "portable_status"
        ]
        == "VALIDATED"
    )
    assert read_assessment(ctx["assessment"]["id"])["status"] == "CURRENT"


def test_a_check_may_only_name_matter_types_the_entry_itself_discloses():
    """The entry's `status` must be `ACTIVE`, its questionnaire's `status` must be
    `UNDER_REVIEW`, `REVISION_REQUESTED`, or `ACCEPTED`, and **every element of
    `affected_matter_types` must appear in that entry's own `matter_types`** — a matter type
    absent from the entry is refused with `ERR_MATTER_TYPE_NOT_ON_ENTRY`.
    The candidate's very first check moves `clearance_status`
    `NOT_STARTED → IN_PROGRESS`.

    Design: Corner/validations/conflict_check_matter_types_are_constrained_to_the_entry_book
    """
    ctx = setup_assessed_candidate("SLIM")
    entry = ctx["entries"]["Northwind Holdings"]
    assert entry["matter_types"] == ["M_AND_A", "SECURITIES"]
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "NOT_STARTED"

    off_book = api_client.create_conflict_check(
        entry["id"],
        create_conflict_check_payload(
            adverse_party_name="Helios Antitrust Group",
            affected_matter_types=["ANTITRUST"],
            severity="POSITIONAL",
        ),
        COUNSEL,
    )
    validate_error(off_book, ApiErrorId.ERR_MATTER_TYPE_NOT_ON_ENTRY.value)
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "NOT_STARTED"

    check = validate_success(
        api_client.create_conflict_check(
            entry["id"],
            create_conflict_check_payload(
                adverse_party_name="Helios Antitrust Group",
                affected_matter_types=["M_AND_A", "SECURITIES"],
                severity="POSITIONAL",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )
    assert check["status"] == "PENDING"
    assert check["severity"] == "POSITIONAL"

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "IN_PROGRESS"
    assert candidate["pipeline_status"] == "DILIGENCE"


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_direct_adverse_check():
    """SLIM BOOK assessed, with one PENDING DIRECT_ADVERSE check on the entry."""
    ctx = setup_assessed_candidate("SLIM")
    ctx["direct_adverse_check"] = validate_success(
        api_client.create_conflict_check(
            ctx["entries"]["Northwind Holdings"]["id"],
            create_conflict_check_payload(
                adverse_party_name="Vertex Capital Partners",
                affected_matter_types=["M_AND_A"],
                severity="DIRECT_ADVERSE",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )
    return ctx
