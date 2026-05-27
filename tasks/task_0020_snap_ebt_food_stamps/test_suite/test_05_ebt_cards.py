"""EBT card lifecycle: activation cross-entity guard and replacement
rolling-window fraud trigger.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, add_member,
    create_and_submit_application, approve_application,
    setup_substantiated_fraud_flag,
    setup_household_with_active_card,
    get_first_card_for_household,
)

CW = TEST_USERS["caseworker_headers"]
INV = TEST_USERS["fraud_investigator_headers"]


def _approve_minted_pending_card_id(api, hh_id):
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh_id}), 200)
    assert len(cards) >= 1 and cards[0]["status"] == "PENDING_ISSUE"
    return cards[0]["id"]


# ─── Difficulty / cross_entity_state_dependency / card_activate_requires_household_active ──

def test_card_activate_rejected_when_household_suspended(api):
    """A PENDING_ISSUE card whose host household is SUSPENDED must not be
    activated — the cross-entity precondition test (PRD §2.8 priority 7)
    surfaces as ERR_HOUSEHOLD_NOT_ACTIVE.

    PRD §3.6: "Activation is performed by the `Cardholder` (or, jointly,
    a `Caseworker`). It transitions the card from `PENDING_ISSUE` to
    `ACTIVE`. The card must be in `PENDING_ISSUE`, the host household must
    be `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`), and — because the
    `Cardholder` is `Household`-backed — the caller's `X-User-ID` must
    equal the `id` of the host household."
    PRD §3.7: "The `ACTIVE` requirement re-appears in several cross-entity
    places: card activation, card reinstatement, and allotment issuance
    all reject with `ERR_HOUSEHOLD_NOT_ACTIVE` (HTTP 409) when the host
    household is not `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/card_activate_requires_household_active
    """
    set_clock("2026-09-15T00:00:00Z")
    hh = create_household(case_number="PA-140001", state_code="PA",
                          address_line="13 River Rd")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    card_id = _approve_minted_pending_card_id(api, hh["id"])

    # Substantiate a flag and suspend the household, but DO NOT activate
    # the card first (so the card remains PENDING_ISSUE and is not cascaded
    # by suspend per PRD §3.7).
    setup_substantiated_fraud_flag(hh["id"])
    validate_success(api.suspend_household(hh["id"], CW), 200)

    resp = api.activate_ebt_card(card_id, CW)
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_ACTIVE.value)


def test_card_activate_succeeds_when_household_is_active(api):
    """Complement: when the host household IS ACTIVE, the activate call on a
    PENDING_ISSUE card succeeds — confirming the gate is specifically the
    household-active precondition and not, say, a blanket ban on activation.

    PRD §3.6: "Activation is performed by the `Cardholder` (or, jointly,
    a `Caseworker`). It transitions the card from `PENDING_ISSUE` to
    `ACTIVE`. The card must be in `PENDING_ISSUE`, the host household must
    be `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`), and — because the
    `Cardholder` is `Household`-backed — the caller's `X-User-ID` must
    equal the `id` of the host household."

    Design: Difficulty/cross_entity_state_dependency/card_activate_requires_household_active
    """
    set_clock("2026-09-15T00:00:00Z")
    hh = create_household(case_number="PA-140002", state_code="PA",
                          address_line="14 River Rd")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    card_id = _approve_minted_pending_card_id(api, hh["id"])
    activated = validate_success(api.activate_ebt_card(card_id, CW), 200)
    assert activated["status"] == "ACTIVE"


# ─── Difficulty / resource_temporal_overlap / ebt_card_replace_abuse_rolling_90day_window ──

def test_third_replacement_within_90_days_raises_card_replace_abuse_flag(api):
    """The first and second replacements within the rolling 90-day window
    do not raise a CARD_REPLACE_ABUSE flag; the third one does (and is
    OPEN) — PRD §3.6 fixes the threshold at "third or later".

    PRD §3.6: "If this is the third or later replacement of any card for
    the same household within a rolling 90-day window — the window endpoint
    being `SystemClock.current_utc` inclusive, looking back exactly 90
    days — a `FraudFlag` with `trigger_rule` of `CARD_REPLACE_ABUSE` and
    `status` of `OPEN` is created (cascade link 3 of the replace cascade)."

    Design: Difficulty/resource_temporal_overlap/ebt_card_replace_abuse_rolling_90day_window
    """
    set_clock("2026-01-01T00:00:00Z")
    hh, _app, card1 = setup_household_with_active_card(
        case_number="CA-160001", state_code="CA",
        clock_iso="2026-01-01T00:00:00Z",
    )
    replaced_card1 = validate_success(api.replace_ebt_card(card1["id"], CW), 200)
    card2_id = replaced_card1["replaced_by_card_id"]
    assert card2_id, "first /replace must set replaced_by_card_id"

    set_clock("2026-01-15T00:00:00Z")
    replaced_card2 = validate_success(api.replace_ebt_card(card2_id, CW), 200)
    card3_id = replaced_card2["replaced_by_card_id"]
    assert card3_id

    # After 2 replacements, no CARD_REPLACE_ABUSE flag.
    set_clock("2026-02-01T00:00:00Z")
    pre = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "CARD_REPLACE_ABUSE"}), 200)
    assert len(pre) == 0, (
        f"after 2 replacements, no CARD_REPLACE_ABUSE flag must exist, got {len(pre)}"
    )

    # Third replacement within 90 days raises the flag.
    validate_success(api.replace_ebt_card(card3_id, CW), 200)
    post = validate_success(api.list_fraud_flags(
        INV, params={"household_id": hh["id"],
                     "trigger_rule": "CARD_REPLACE_ABUSE"}), 200)
    assert len(post) == 1, (
        f"third replacement within 90 days must create exactly one "
        f"CARD_REPLACE_ABUSE flag, got {len(post)}"
    )
    assert post[0]["status"] == "OPEN", \
        f"the raised flag must be OPEN, got {post[0]['status']!r}"
    assert post[0]["trigger_rule"] == "CARD_REPLACE_ABUSE"


def test_replace_sets_replaced_by_card_id_pointer_to_successor(api):
    """Each /replace mints a fresh ACTIVE successor card and writes its id
    onto the predecessor's `replaced_by_card_id`. This is a separate
    side-effect of the replace cascade from the fraud-trigger threshold,
    so it carries the same difficulty-design tag.

    PRD §3.6: "Replacement is performed by the `Cardholder` (or, jointly,
    a `Caseworker`) and moves the predecessor from `ACTIVE` to `REPLACED`.
    Both the card and its host household must be `ACTIVE`. On success, a
    fresh `EBTCard` is created with `status` of `ACTIVE` for the same
    `household_id`, and the predecessor's `replaced_by_card_id` is set to
    the new card's `id` (cascade link 2 of the replace cascade)."

    Design: Difficulty/resource_temporal_overlap/ebt_card_replace_abuse_rolling_90day_window
    """
    set_clock("2026-03-01T00:00:00Z")
    hh, _app, card = setup_household_with_active_card(
        case_number="CA-160003", state_code="CA",
        clock_iso="2026-03-01T00:00:00Z",
    )
    predecessor = validate_success(api.replace_ebt_card(card["id"], CW), 200)
    assert predecessor["status"] == "REPLACED", \
        f"predecessor must land in REPLACED, got {predecessor['status']!r}"
    succ_id = predecessor["replaced_by_card_id"]
    assert succ_id, "predecessor.replaced_by_card_id must point to successor"

    successor = validate_success(api.get_ebt_card(succ_id, CW), 200)
    assert successor["status"] == "ACTIVE", \
        f"successor must start in ACTIVE, got {successor['status']!r}"
    assert successor["household_id"] == hh["id"], (
        f"successor must serve the same household, got {successor['household_id']!r}"
    )
