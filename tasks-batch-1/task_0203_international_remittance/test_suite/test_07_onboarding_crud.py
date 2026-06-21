"""Resource creation, defaults, system-field initialization, listing, and the
recipient-KYC revision cycle.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_corridor_payload, create_sender_payload, create_recipient_payload,
    submit_kyc_payload, decide_kyc_payload, create_transfer_payload,
    setup_corridor, setup_sender, setup_recipient,
    create_locked_quote, create_transfer_from_quote,
    assert_corridor, assert_sender, assert_recipient,
    NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── corridor creation (corner: entities) ───────────────────────────────────

def test_create_corridor_returns_201_active_zero_reserved(api):
    """PRD §3.1: "On creation a corridor's `status` is `ACTIVE` and its
    `reserved_minor` is 0."
    PRD §2.4: "The `version` begins at 1 on creation."

    Design: Corner/entities/create_corridor_returns_201_with_all_fields
    """
    api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN)
    res = api.create_corridor(create_corridor_payload(
        enabled_payout_methods=["BANK", "CASH_PICKUP", "WALLET"],
        rolling_window_cap_minor=400000), ADMIN)
    corridor = validate_success(res, 201)
    assert_corridor(corridor)
    assert corridor["status"] == "ACTIVE", corridor["status"]
    assert corridor["reserved_minor"] == 0, corridor["reserved_minor"]
    assert corridor["version"] == 1, corridor["version"]


# ─── sender not found (corner: entities) ────────────────────────────────────

def test_get_sender_nonexistent_returns_404(api):
    """PRD §2.6: "Every identifier a request supplies — both path identifiers and
    foreign keys embedded in the body — must resolve to an existing resource ... and
    rejects the first unresolved reference with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_sender_not_found_returns_404
    """
    res = api.get_sender(NON_EXISTENT_UUID, AGENT)
    validate_error(res, "ERR_NOT_FOUND")


# ─── recipient required field (corner: entities) ────────────────────────────

def test_create_recipient_missing_payout_method_rejected(api):
    """PRD §3.2: "An agent creates a recipient under a sender by supplying that
    sender's `sender_id`, the beneficiary's legal `full_name` and receiving `country`,
    the `payout_method` (`BANK`, `CASH_PICKUP`, or `WALLET`), and a `payout_account_ref`."
    PRD §3.9: "then that the body is well-formed — required fields present, enum values
    valid, and all amounts strictly greater than zero (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_recipient_missing_required_payout_method_returns_invalid_request
    """
    sender = setup_sender()
    payload = create_recipient_payload(sender["id"], full_name="No Method")
    del payload["payout_method"]
    res = api.create_recipient(payload, AGENT)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── corridor defaults (corner: entities) ───────────────────────────────────

def test_corridor_window_and_ttl_defaults_applied(api):
    """PRD §3.1: "`rolling_window_cap_minor` caps cumulative funded send per sender
    within `rolling_window_hours` (which defaults to 24 hours when omitted), and
    `rate_lock_ttl_seconds` sets how long a locked rate stays valid (defaulting to
    1800 seconds when omitted)."

    Design: Corner/entities/corridor_rolling_window_hours_default_applied_when_omitted
    """
    api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN)
    payload = create_corridor_payload(
        name="US->MX", receive_country="MX", receive_currency="MXN",
        enabled_payout_methods=["CASH_PICKUP"], fx_margin_bps=100,
        per_transfer_max_minor=500000, rolling_window_cap_minor=400000)
    payload.pop("rolling_window_hours", None)
    payload.pop("rate_lock_ttl_seconds", None)
    corridor = validate_success(api.create_corridor(payload, ADMIN), 201)
    assert corridor["rolling_window_hours"] == 24, corridor["rolling_window_hours"]
    assert corridor["rate_lock_ttl_seconds"] == 1800, corridor["rate_lock_ttl_seconds"]


# ─── sender system fields (corner: entities) ────────────────────────────────

def test_sender_system_fields_initialized_regardless_of_input(api):
    """PRD §3.2: "A freshly registered sender starts at `kyc_tier` of `TIER0` and
    `status` of `ACTIVE`."

    Design: Corner/entities/sender_kyc_tier_system_field_ignores_input
    """
    res = api.create_sender(create_sender_payload(full_name="Sys Field Sender"), AGENT)
    sender = validate_success(res, 201)
    assert_sender(sender)
    assert sender["kyc_tier"] == "TIER0", sender["kyc_tier"]
    assert sender["status"] == "ACTIVE", sender["status"]


# ─── transfer listing pagination (corner: entities) ─────────────────────────

def test_list_transfers_paginated_total_count_and_has_more(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_transfers_paginated_with_total_count_and_has_more
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    for principal in (50000, 60000):
        quote = create_locked_quote(corridor["id"], sender["id"], principal)
        create_transfer_from_quote(quote, recipient["id"])
    data, meta = validate_paginated(
        api.list_transfers(AGENT, params={"sender_id": sender["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)


# ─── recipient KYC revision cycle (corner: state_machines) ──────────────────

def test_rejected_recipient_resubmit_increments_review_count(api):
    """PRD §3.2: "A `REJECTED` beneficiary is not a dead end — the agent may resubmit
    documents, which again requires `kyc_doc_ref`, records the new reference, and
    returns the recipient to `PENDING_REVIEW`; this resubmission path additionally
    increments `kyc_review_count` by one."

    Design: Corner/state_machines/recipient_kyc_revision_cycle_increments_review_count
    """
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    api.submit_recipient_kyc(recipient["id"], submit_kyc_payload(kyc_doc_ref="DOC-A"), AGENT)
    api.decide_recipient_kyc(recipient["id"], decide_kyc_payload("REJECT"), OFFICER)
    resubmitted = validate_success(api.submit_recipient_kyc(
        recipient["id"], submit_kyc_payload(kyc_doc_ref="DOC-B"), AGENT), 200)
    assert resubmitted["kyc_status"] == "PENDING_REVIEW", resubmitted["kyc_status"]
    assert resubmitted["kyc_review_count"] == 1, resubmitted["kyc_review_count"]


# ─── submit-kyc without doc (corner: errors) ────────────────────────────────

def test_submit_kyc_without_doc_ref_rejected(api):
    """PRD §3.2: "The agent submits documents, which requires a `kyc_doc_ref` in the
    body — omitting it is rejected with `ERR_KYC_DOC_REQUIRED`."

    Design: Corner/errors/submit_kyc_missing_doc_returns_doc_required
    """
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    res = api.submit_recipient_kyc(recipient["id"], {}, AGENT)
    validate_error(res, "ERR_KYC_DOC_REQUIRED")
    after = validate_success(api.get_recipient(recipient["id"], AGENT), 200)
    assert after["kyc_status"] == "UNVERIFIED", after["kyc_status"]


# ─── OCC stale quote version on transfer create (corner: cross-cutting) ─────

def test_create_transfer_with_stale_quote_version_rejected(api):
    """PRD §2.10: "If the quote's current `version` differs from
    `expected_quote_version` — for instance because the same quote was re-locked,
    advancing its `version`, after the agent last read it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_quote_version_on_transfer_create_returns_412
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    locked = create_locked_quote(corridor["id"], sender["id"], 50000)
    # Deliberately pass a stale (current - 1) expected_quote_version.
    res = api.create_transfer(create_transfer_payload(
        locked["id"], recipient["id"], locked["version"] - 1), AGENT)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_quote(locked["id"], AGENT), 200)
    assert after["status"] == "LOCKED", after["status"]
