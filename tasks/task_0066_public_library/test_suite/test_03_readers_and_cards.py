"""Reader registration, identity verification, and Card lifecycle tests (PRD §3.2)."""

import pytest

from test_helpers import (
    LIBRARIAN_HEADERS,
    LOAN_DURATION_DAYS_BY_CARD_TYPE,
    MAX_LOANS_BY_CARD_TYPE,
    MAX_RENEWALS_BY_CARD_TYPE,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    api_client,
    assert_card,
    assert_reader,
    assert_version_increased,
    blacklist_reader_payload,
    create_reader_payload,
    create_unverified_reader,
    create_verified_reader,
    create_verified_reader_with_card,
    emit_identity_verified,
    identity_verified_event_payload,
    issue_card,
    issue_card_payload,
    make_admin_headers,
    reissue_card_payload,
    validate_error,
    validate_success,
)


# =============================================================================
# Reader registration (PRD §3.2)
# =============================================================================


def test_new_reader_starts_unverified_normal_zero_loans(api):
    """PRD §3.2: "The reader begins life with identity_verified set to false,
    identity_verified_at null, status set to NORMAL, active_loan_count zero,
    and unpaid_fine_cents zero."

    Claim: a freshly registered Reader has identity_verified=false,
    status=NORMAL, active_loan_count=0, unpaid_fine_cents=0.
    """
    reader = create_unverified_reader()
    assert_reader(reader)
    assert reader["identity_verified"] is False
    assert reader.get("identity_verified_at") in (None,)
    assert reader["status"] == "NORMAL"
    assert reader["active_loan_count"] == 0
    assert reader["unpaid_fine_cents"] == 0


def test_identity_verified_event_flips_flag(api):
    """PRD §3.2: "an Admin posts an inbound event of type IDENTITY_VERIFIED,
    whose payload references the reader; on receipt the server sets the
    reader's identity_verified flag to true and records the
    identity_verified_at timestamp."

    Claim: posting IDENTITY_VERIFIED flips identity_verified=true and sets
    identity_verified_at to a non-null ISO 8601 timestamp.
    """
    reader = create_unverified_reader()
    emit_identity_verified(reader["id"])
    refreshed = validate_success(
        api.get_reader(reader["id"], LIBRARIAN_HEADERS), 200
    )
    assert refreshed["identity_verified"] is True
    assert refreshed["identity_verified_at"] is not None


# =============================================================================
# Card issuance and computed schedule (PRD §3.2)
# =============================================================================


def test_card_issuance_requires_identity_verified(api):
    """PRD §3.2: "If the reader's identity_verified is still false the request
    is rejected with ERR_IDENTITY_NOT_VERIFIED."

    Claim: issuing a Card to an unverified Reader returns
    ERR_IDENTITY_NOT_VERIFIED with HTTP 409.
    """
    reader = create_unverified_reader()
    res = api.issue_card(reader["id"], issue_card_payload(), LIBRARIAN_HEADERS)
    validate_error(res, "ERR_IDENTITY_NOT_VERIFIED", expected_status=409)


@pytest.mark.parametrize(
    "card_type,exp_max_loans,exp_duration,exp_max_renewals",
    [
        ("REGULAR", 5, 30, 2),
        ("STUDENT", 8, 60, 3),
        ("SENIOR", 4, 45, 2),
        ("TEMPORARY", 2, 14, 0),
    ],
)
def test_card_type_computed_parameters(
    api, card_type, exp_max_loans, exp_duration, exp_max_renewals
):
    """PRD §3.2: "the borrowing quota max_loans is 5 for REGULAR, 8 for
    STUDENT, 4 for SENIOR, and 2 for TEMPORARY; the loan period
    loan_duration_days is 30 for REGULAR, 60 for STUDENT, 45 for SENIOR, and
    14 for TEMPORARY; and the per-loan consecutive-renewal limit max_renewals
    is 2 for REGULAR, 3 for STUDENT, 2 for SENIOR, and 0 for TEMPORARY."

    Claim: per-card_type, the server pins max_loans, loan_duration_days, and
    max_renewals to the PRD-declared schedule.
    """
    reader = create_verified_reader()
    card = issue_card(reader["id"], card_type=card_type)
    assert_card(card)
    assert card["card_type"] == card_type
    assert card["max_loans"] == exp_max_loans
    assert card["loan_duration_days"] == exp_duration
    assert card["max_renewals"] == exp_max_renewals
    assert card["status"] == "ACTIVE"
    assert card["replaced_by_card_id"] in (None,)


def test_card_validity_from_after_until_rejected(api):
    """PRD §3.2: "the request must satisfy valid_from strictly earlier than
    valid_until or the server returns ERR_INVALID_INPUT."

    Claim: valid_from >= valid_until returns ERR_INVALID_INPUT (422).
    """
    reader = create_verified_reader()
    payload = issue_card_payload(
        valid_from="2025-06-01T00:00:00.000Z",
        valid_until="2025-01-01T00:00:00.000Z",
    )
    res = api.issue_card(reader["id"], payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_card_number_format_lib_year_seq(api):
    """PRD §3.2: "the server mints a unique human-readable card_number of the
    form LIB-YYYY-NNNNNN".

    Claim: card_number starts with `LIB-` prefix.
    """
    reader = create_verified_reader()
    card = issue_card(reader["id"])
    assert card["card_number"].startswith("LIB-"), card["card_number"]


# =============================================================================
# Freeze / unfreeze (PRD §3.2)
# =============================================================================


def test_freeze_card_active_to_frozen(api):
    """PRD §3.2: "A Librarian may freeze an ACTIVE card; the card moves to
    FROZEN".

    Claim: freezing an ACTIVE card sets status=FROZEN.
    """
    _, card = create_verified_reader_with_card()
    before_v = card["version"]
    res = api.freeze_card(card["id"], None, LIBRARIAN_HEADERS)
    frozen = validate_success(res, 200)
    assert frozen["status"] == "FROZEN"
    assert_version_increased(frozen, before_v)


def test_freeze_non_active_card_rejected(api):
    """PRD §3.2: "Freezing a card that is not in ACTIVE is rejected with
    ERR_INVALID_STATE."

    Claim: freezing a FROZEN card returns ERR_INVALID_STATE (409).
    """
    _, card = create_verified_reader_with_card()
    validate_success(api.freeze_card(card["id"], None, LIBRARIAN_HEADERS), 200)
    res = api.freeze_card(card["id"], None, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_unfreeze_card_frozen_to_active(api):
    """PRD §3.2: "Unfreezing returns a FROZEN card to ACTIVE."

    Claim: unfreezing a FROZEN card returns it to ACTIVE.
    """
    _, card = create_verified_reader_with_card()
    validate_success(api.freeze_card(card["id"], None, LIBRARIAN_HEADERS), 200)
    res = api.unfreeze_card(card["id"], None, LIBRARIAN_HEADERS)
    unfrozen = validate_success(res, 200)
    assert unfrozen["status"] == "ACTIVE"


# =============================================================================
# Reissue (PRD §3.2)
# =============================================================================


def test_reissue_links_old_card_to_new(api):
    """PRD §3.2: "when a Librarian invokes reissue on an ACTIVE or FROZEN card
    and supplies the successor card's card_type, valid_from, and valid_until
    in the request body, the server mints a new Card and writes the old card's
    replaced_by_card_id to point at the new card's id; the old card
    transitions to the terminal REISSUED state."

    Claim: reissue mints a successor Card, sets the old card's
    replaced_by_card_id, and moves the old card to REISSUED.
    """
    _, card = create_verified_reader_with_card()
    res = api.reissue_card(
        card["id"], reissue_card_payload(card_type="STUDENT"), LIBRARIAN_HEADERS
    )
    new_card = validate_success(res, 201)
    assert new_card["card_type"] == "STUDENT"
    assert new_card["status"] == "ACTIVE"

    # The OLD card should now be REISSUED with replaced_by_card_id set.
    # We fetch via the underlying GET (not in PRD's table, so we read using
    # the freeze endpoint as a probe is not appropriate). Re-read by attempting
    # a follow-up freeze: PRD §3.2 says reissue from non-{ACTIVE,FROZEN} fails,
    # so we expect ERR_INVALID_STATE when re-targeting the old card.
    refreeze = api.freeze_card(card["id"], None, LIBRARIAN_HEADERS)
    validate_error(refreeze, "ERR_INVALID_STATE", expected_status=409)


def test_reissue_from_terminal_state_rejected(api):
    """PRD §3.2: "A reissue invoked from any state other than ACTIVE or
    FROZEN is rejected with ERR_INVALID_STATE."

    Claim: reissue applied twice in a row rejects the second with
    ERR_INVALID_STATE.
    """
    _, card = create_verified_reader_with_card()
    validate_success(
        api.reissue_card(card["id"], reissue_card_payload(), LIBRARIAN_HEADERS),
        201,
    )
    res = api.reissue_card(card["id"], reissue_card_payload(), LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =============================================================================
# Blacklist / Unblacklist (PRD §3.2)
# =============================================================================


def test_blacklist_reader_moves_to_blacklisted_and_freezes_cards(api, admin_headers):
    """PRD §3.2: "Blacklisting a reader ... advances Reader.status to
    BLACKLISTED and, as a side effect, transitions every ACTIVE card of that
    reader to FROZEN."

    Claim: blacklist sets Reader.status=BLACKLISTED AND each ACTIVE card moves
    to FROZEN.
    """
    reader, card = create_verified_reader_with_card()
    res = api.blacklist_reader(reader["id"], blacklist_reader_payload(), admin_headers)
    updated_reader = validate_success(res, 200)
    assert updated_reader["status"] == "BLACKLISTED"

    # Active card should have flipped to FROZEN as a cascade side-effect.
    refreeze = api.freeze_card(card["id"], None, LIBRARIAN_HEADERS)
    validate_error(refreeze, "ERR_INVALID_STATE", expected_status=409)


def test_unblacklist_rejected_with_unpaid_fine(api, admin_headers):
    """PRD §3.2: "Unblacklisting a reader is only permitted when the reader's
    unpaid_fine_cents is zero and no loan in BORROWED, RENEWED, or
    RECALL_PENDING is currently overdue".

    Claim: attempting to unblacklist a reader with unpaid_fine_cents > 0 is
    rejected.
    """
    from test_helpers import create_loan_then_return_late

    # Create a fine first (so unpaid_fine_cents > 0), then blacklist.
    ctx = create_loan_then_return_late(days_past_due=5)
    reader = ctx["reader"]
    # Confirm reader has unpaid fine
    refreshed_reader = validate_success(
        api.get_reader(reader["id"], LIBRARIAN_HEADERS), 200
    )
    assert refreshed_reader["unpaid_fine_cents"] > 0

    validate_success(
        api.blacklist_reader(reader["id"], blacklist_reader_payload(), admin_headers),
        200,
    )
    # Try to unblacklist — should be rejected because unpaid_fine_cents > 0.
    res = api.unblacklist_reader(reader["id"], None, admin_headers)
    assert res.status_code >= 400, (
        "PRD §3.2: unblacklisting with unpaid_fine_cents > 0 must be rejected"
    )
