"""The notarial journal: in-person entries, fee-cap enforcement, amend/void
lifecycle, and the lifetime-fee ledger invariant.

Covers the journal fee-cap boundary, the invalid-request-beats-fee-cap priority
pair, the void-conserves-ledger compensating invariant, and the amend idempotency
corner.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_notary_headers,
    create_journal_entry_payload,
    amend_journal_entry_payload,
    TEST_USERS,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]


def _active_notary_with_caps(email, caps):
    ctx = th.setup_active_notary(
        jurisdiction_overrides={"state_code": "TX"},
        notary_overrides={"email": email},
        fee_schedules=caps,
    )
    return ctx["notary"]


# ===========================================================================
# boundary_precision_check: journal fee at cap passes, over cap fails
# ===========================================================================
def test_journal_fee_at_cap_is_accepted(api):
    """PRD §3.7: "The fee on a direct entry is policed against the statutory cap at
    creation: if `fee_charged_cents` exceeds the `max_act_fee_cents` from the fee
    schedule matching the notary's jurisdiction and that act type, the entry is
    rejected with `ERR_FEE_EXCEEDS_CAP`."
    PRD §3.7: "A directly-created entry begins in `POSTED` status."

    Design: Difficulty/boundary_precision_check/journal_fee_at_cap_passes_over_cap_fails
    """
    notary = _active_notary_with_caps("nb1@x.com", {"ACKNOWLEDGMENT": 1000})
    hdr = make_notary_headers(notary["id"])
    payload = create_journal_entry_payload(
        notary["id"], "ACKNOWLEDGMENT", "Exact Cap", "ID_CREDENTIAL", 1000
    )
    data = validate_success(api.create_journal_entry(payload, hdr), expected_status=201)
    assert data["status"] == "POSTED"
    assert data["fee_charged_cents"] == 1000


def test_journal_fee_over_cap_returns_fee_exceeds_cap(api):
    """PRD §3.7: "if `fee_charged_cents` exceeds the `max_act_fee_cents` from the
    fee schedule matching the notary's jurisdiction and that act type, the entry is
    rejected with `ERR_FEE_EXCEEDS_CAP`."

    Design: Difficulty/boundary_precision_check/journal_fee_at_cap_passes_over_cap_fails
    """
    notary = _active_notary_with_caps("nb1b@x.com", {"ACKNOWLEDGMENT": 1000})
    hdr = make_notary_headers(notary["id"])
    payload = create_journal_entry_payload(
        notary["id"], "ACKNOWLEDGMENT", "Over Cap", "ID_CREDENTIAL", 1001
    )
    resp = api.create_journal_entry(payload, hdr)
    validate_error(resp, ApiErrorId.ERR_FEE_EXCEEDS_CAP.value, expected_status=409)


# ===========================================================================
# priority_pair_validation_conflict: invalid-request beats fee-cap
# ===========================================================================
def test_journal_create_missing_field_and_over_cap_returns_invalid_request(api):
    """PRD §2.9: "Request well-formedness is checked fourth: a missing required
    field, a wrongly typed value, or an enum value outside its declared set yields
    `ERR_INVALID_REQUEST` (400) ... Only once all of these pass does the system
    evaluate the domain-specific business rules — ... fee caps"

    Design: Difficulty/priority_pair_validation_conflict/invalid_request_beats_fee_cap_on_journal_create
    """
    notary = _active_notary_with_caps("npp2@x.com", {"ACKNOWLEDGMENT": 1000})
    hdr = make_notary_headers(notary["id"])
    # omit required signer_name AND set fee above cap — well-formedness wins
    payload = {
        "notary_id": notary["id"],
        "act_type": "ACKNOWLEDGMENT",
        "id_method": "ID_CREDENTIAL",
        "fee_charged_cents": 5000,
    }
    resp = api.create_journal_entry(payload, hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_journal_create_over_cap_alone_returns_fee_exceeds_cap(api):
    """PRD §2.9: "Only once all of these pass does the system evaluate the
    domain-specific business rules — ... fee caps"
    PRD §3.7: "if `fee_charged_cents` exceeds the `max_act_fee_cents` from the fee
    schedule matching the notary's jurisdiction and that act type, the entry is
    rejected with `ERR_FEE_EXCEEDS_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_request_beats_fee_cap_on_journal_create
    """
    notary = _active_notary_with_caps("npp2b@x.com", {"ACKNOWLEDGMENT": 1000})
    hdr = make_notary_headers(notary["id"])
    # well-formed payload but over the cap — only the fee-cap rule can fault
    payload = create_journal_entry_payload(
        notary["id"], "ACKNOWLEDGMENT", "Present Name", "ID_CREDENTIAL", 5000
    )
    resp = api.create_journal_entry(payload, hdr)
    validate_error(resp, ApiErrorId.ERR_FEE_EXCEEDS_CAP.value, expected_status=409)


# ===========================================================================
# Corner: amend already-amended entry
# ===========================================================================
def test_amend_already_amended_entry_returns_entry_not_posted(api):
    """PRD §3.7: "Amending moves the original entry from `POSTED` to the terminal
    `AMENDED` status ... Amendment requires the original entry to be `POSTED`,
    failing otherwise with `ERR_ENTRY_NOT_POSTED`"

    Design: Corner/state_machines/amend_already_amended_entry_returns_entry_not_posted
    """
    notary = _active_notary_with_caps("amd@x.com", {"OATH": 1000})
    hdr = make_notary_headers(notary["id"])
    entry = validate_success(
        api.create_journal_entry(
            create_journal_entry_payload(notary["id"], "OATH", "Orig", "PERSONAL_KNOWLEDGE", 500), hdr
        ),
        201,
    )
    validate_success(api.amend_journal_entry(entry["id"], amend_journal_entry_payload("Corrected", 500), hdr))
    resp = api.amend_journal_entry(entry["id"], amend_journal_entry_payload("Again", 500), hdr)
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_POSTED.value, expected_status=409)


# ===========================================================================
# compensating_invariant: void conserves the lifetime fee ledger
# ===========================================================================
def test_void_entry_drops_lifetime_fees_to_zero(api):
    """PRD §2.6: "A notary's `lifetime_fees_collected_cents` is a running ledger of
    fee revenue, and it is always defined as the sum of `fee_charged_cents` across
    that notary's journal entries that are currently in `POSTED` status. Entries
    that have been amended or voided are excluded."
    PRD §3.7: "Voiding recomputes the notary's `lifetime_fees_collected_cents` with
    the voided entry excluded and writes an audit record."

    Design: Difficulty/compensating_invariant/void_journal_entry_conserves_lifetime_fee_ledger
    """
    notary = _active_notary_with_caps("nci1@x.com", {"OATH": 1000})
    hdr = make_notary_headers(notary["id"])
    entry = validate_success(
        api.create_journal_entry(
            create_journal_entry_payload(notary["id"], "OATH", "Oath Taker", "PERSONAL_KNOWLEDGE", 700), hdr
        ),
        201,
    )
    after_post = validate_success(api.get_notary(notary["id"], CA))
    assert after_post["lifetime_fees_collected_cents"] == 700
    voided = validate_success(api.void_journal_entry(entry["id"], CA))
    assert voided["status"] == "VOID"
    after_void = validate_success(api.get_notary(notary["id"], CA))
    assert after_void["lifetime_fees_collected_cents"] == 0


def test_posted_entry_raises_lifetime_fees(api):
    """PRD §2.6: "A notary's `lifetime_fees_collected_cents` is a running ledger of
    fee revenue, and it is always defined as the sum of `fee_charged_cents` across
    that notary's journal entries that are currently in `POSTED` status."
    PRD §3.7: "Posting an entry recomputes the notary's
    `lifetime_fees_collected_cents` and writes an audit record."

    Design: Difficulty/compensating_invariant/void_journal_entry_conserves_lifetime_fee_ledger
    """
    notary = _active_notary_with_caps("nci1b@x.com", {"OATH": 1000})
    hdr = make_notary_headers(notary["id"])
    before = validate_success(api.get_notary(notary["id"], CA))
    assert before["lifetime_fees_collected_cents"] == 0
    validate_success(
        api.create_journal_entry(
            create_journal_entry_payload(notary["id"], "OATH", "Oath Taker", "PERSONAL_KNOWLEDGE", 700), hdr
        ),
        201,
    )
    after = validate_success(api.get_notary(notary["id"], CA))
    assert after["lifetime_fees_collected_cents"] == 700
