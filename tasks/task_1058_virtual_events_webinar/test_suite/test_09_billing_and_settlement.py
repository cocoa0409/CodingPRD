"""Billing: the sponsorship invoice's pinned rounding order, the organizer
invoice's subtotal-keyed discount, the concurrency guard and segregation of
duties."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_settlement,
    assert_line_item,
    make_finance_admin_headers,
    make_sponsor_headers,
    shift_iso,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    add_speaker,
    invite_speaker,
    accept_invitation,
    schedule_session,
    add_broadcast,
    publish_event,
    start_event,
    end_event,
    add_registration,
    pay_registration,
    add_sponsor,
    sign_contract,
    add_booth,
    capture_lead,
    set_clock,
    reset_clock,
    read_event,
    read_registration,
    read_settlement,
    read_booth,
    current_event_version,
    create_event_settlement,
    setup_published_event,
    setup_ended_event,
    setup_event_settlement,
    setup_issued_event_settlement,
    api_client,
)

ORG = TEST_USERS["organizer_headers"]
FIN = TEST_USERS["finance_admin_headers"]
FIN2 = TEST_USERS["second_finance_admin_headers"]


# ==========================================================================
# The sponsorship invoice rounds each line before summing
# ==========================================================================

def _expo_c_sponsor_invoice():
    """GOLD sponsor, lead_quota 2 with five captured leads (3 overage units) and
    7 reported booth stream minutes."""
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Expo C", "capacity": 100},
        ticket_overrides={"quota": 10},
    )
    sponsor = add_sponsor(
        event["id"], name="Globex", package_tier="GOLD",
        contact_email="sales@globex.example",
    )
    sign_contract(sponsor["id"], "Globex Legal")
    booth = add_booth(sponsor["id"], headline="Globex Booth", lead_quota=2)
    validate_success(
        api_client.report_booth_stream_usage(
            booth["id"], 7, make_sponsor_headers(sponsor["id"])
        ),
        200,
    )
    for index in range(1, 6):
        registration = add_registration(
            event["id"], ticket_type["id"], f"l{index}@example.com"
        )
        capture_lead(booth["id"], registration["id"], True)
    return event, sponsor, booth


def test_sponsor_invoice_rounds_each_line_before_summing(api):
    """PRD 3.11: "**Each line's `line_total_cents` is computed as its units
    multiplied by its unit rate and rounded half up to a whole cent first**, and
    only then are the three rounded line totals added to give `subtotal_cents`.
    Summing the unrounded line values and rounding once at the end produces a
    different subtotal and is wrong."
    PRD 3.11: "The `PACKAGE` line always bills one unit at the package rate for
    the sponsor's `package_tier`: 250,000 cents for `BRONZE`, 500,000 cents for
    `SILVER`, and 900,000 cents for `GOLD`. The `LEAD_OVERAGE` line bills the
    excess of the booth's `captured_lead_count` over its `lead_quota` — or zero
    units when the booth stayed within quota, never a negative figure — at 137.5
    cents per lead. The `BOOTH_STREAM` line bills the booth's
    `stream_minutes_total` at 4.25 cents per minute."

    Design: Difficulty/combinatorial_formula/sponsor_invoice_rounds_each_line_before_summing
    """
    event, sponsor, booth = _expo_c_sponsor_invoice()
    refreshed_booth = read_booth(booth["id"])
    assert refreshed_booth["captured_lead_count"] == 5
    assert refreshed_booth["stream_minutes_total"] == 7

    settlement = validate_success(
        api.create_sponsor_settlement(sponsor["id"], FIN), 201
    )
    assert_settlement(settlement)
    assert settlement["subject_type"] == "SPONSOR"
    assert len(settlement["line_items"]) == 3

    assert_line_item(settlement["line_items"][0], "PACKAGE", 1, 900000, 900000)
    assert_line_item(settlement["line_items"][1], "LEAD_OVERAGE", 3, 137.5, 413)
    assert_line_item(settlement["line_items"][2], "BOOTH_STREAM", 7, 4.25, 30)
    assert settlement["subtotal_cents"] == 900443, (
        "Per-line rounding gives 900000 + 413 + 30 = 900443; summing unrounded "
        f"values and rounding once would give 900442. Got "
        f"{settlement['subtotal_cents']}"
    )


def test_sponsor_invoice_taxes_the_already_rounded_subtotal(api):
    """PRD 3.11: "Tax is then taken as 8.25 percent of that already-rounded
    `subtotal_cents`, rounded half up exactly once, and written to `tax_cents`;
    `total_cents` is `subtotal_cents` plus `tax_cents`. Sponsorship invoices
    carry `platform_fee_cents` of zero and `organizer_payout_cents` of zero."

    Design: Difficulty/combinatorial_formula/sponsor_invoice_rounds_each_line_before_summing
    """
    event, sponsor, booth = _expo_c_sponsor_invoice()
    settlement = validate_success(
        api.create_sponsor_settlement(sponsor["id"], FIN), 201
    )

    assert settlement["tax_cents"] == 74287, (
        "8.25% of 900443 is 74286.5475, which rounds half up to 74287; got "
        f"{settlement['tax_cents']}"
    )
    assert settlement["total_cents"] == 974730, (
        f"Expected 900443 + 74287 = 974730, got {settlement['total_cents']}"
    )
    assert settlement["platform_fee_cents"] == 0
    assert settlement["organizer_payout_cents"] == 0
    assert settlement["sponsor_id"] == sponsor["id"]


# ==========================================================================
# The organizer invoice keys its discount on the subtotal
# ==========================================================================

def _summit_d_settled():
    """A 200000-cent seat (fee clamped at the 2500 ceiling, so 202500) plus 30
    streamed minutes, giving subtotal 202620 and tier-1 volume discount."""
    reset_clock()
    event = new_event(
        name="Summit D", capacity=100,
        starts_at="2026-09-13T09:00:00Z", ends_at="2026-09-13T18:00:00Z",
    )
    ticket_type = add_ticket_type(
        event["id"], name="Corporate", price_cents=200000, quota=5
    )
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Opening", capacity=500,
        starts_at="2026-09-13T10:00:00Z", ends_at="2026-09-13T11:00:00Z",
    )
    speaker = add_speaker(event["id"], full_name="Dana Reed", email="dana@example.com")
    junction = invite_speaker(session["id"], speaker["id"], speaking_role="HOST")
    accept_invitation(junction["id"], speaker["id"])
    schedule_session(session["id"])
    broadcast = add_broadcast(session["id"])
    publish_event(event["id"])
    registration = add_registration(
        event["id"], ticket_type["id"], "corp@example.com"
    )
    pay_registration(registration["id"], 202500)
    start_event(event["id"])
    validate_success(api_client.preview_broadcast(broadcast["id"], ORG), 200)
    live = validate_success(api_client.go_live_broadcast(broadcast["id"], ORG), 200)
    set_clock(shift_iso(live["started_at"], minutes=30))
    validate_success(api_client.end_broadcast(broadcast["id"], ORG), 200)
    end_event(event["id"])
    settlement = create_event_settlement(event["id"])
    return event, registration, settlement


def test_event_settlement_discount_is_keyed_on_the_subtotal(api):
    """PRD 3.11: "**Step five** picks the volume discount from the subtotal: a
    `subtotal_cents` of at least 250,000 earns fifteen percent, otherwise a
    `subtotal_cents` of at least 100,000 earns ten percent, and anything below
    that earns none — both thresholds are inclusive."
    PRD 3.11: "**Step six** takes the raw platform fee as eight percent of
    `subtotal_cents` rounded half up, multiplies it by one minus the volume
    discount fraction and rounds half up again, then applies a floor so that
    `platform_fee_cents` is never less than 500 cents."

    Design: Difficulty/combinatorial_formula/event_settlement_fee_discount_tier_keyed_on_subtotal_not_total
    """
    event, registration, settlement = _summit_d_settled()

    assert read_event(event["id"])["streamed_minutes_total"] == 30
    assert settlement["subtotal_cents"] == 202620, (
        "202500 of ticket revenue plus 30 minutes at 4 cents = 202620; got "
        f"{settlement['subtotal_cents']}"
    )
    assert settlement["platform_fee_cents"] == 14589, (
        "The 10% tier keyed on the subtotal turns a raw 16210 into 14589, not the "
        f"undiscounted 16210; got {settlement['platform_fee_cents']}"
    )
    assert settlement["total_cents"] == 14709, (
        f"Expected 14589 + 120 streaming = 14709, got {settlement['total_cents']}"
    )


def test_event_settlement_reprices_paid_seats_and_pays_out_the_remainder(api):
    """PRD 3.11: "**Step seven** sets `total_cents` to `platform_fee_cents` plus
    the streaming charge, and `organizer_payout_cents` to the gross ticket
    revenue less `total_cents` — a figure that may legitimately be negative."
    PRD 3.4: "**Sixth**, a processing fee is taken as three percent of that
    discounted amount, rounded half up to a whole cent, and then clamped so that
    it is never below 100 cents and never above 2,500 cents — this is the second
    and last rounding."

    Design: Difficulty/combinatorial_formula/event_settlement_fee_discount_tier_keyed_on_subtotal_not_total
    """
    event, registration, settlement = _summit_d_settled()

    priced = read_registration(registration["id"])
    assert priced["amount_due_cents"] == 202500, (
        "200000 plus a fee clamped at the 2500 ceiling; got "
        f"{priced['amount_due_cents']}"
    )
    assert priced["final_amount_due_cents"] == 202500, (
        "The final run reaches the same figure, so nothing needs correcting"
    )
    assert settlement["organizer_payout_cents"] == 187791, (
        f"Expected 202500 - 14709 = 187791, got "
        f"{settlement['organizer_payout_cents']}"
    )
    assert read_event(event["id"])["settlement_adjustment_cents"] == 0


# ==========================================================================
# Corner instances
# ==========================================================================

def test_event_settlement_with_no_paid_registrations_applies_fee_floor(api):
    """PRD 3.11: "When no registration of the event has been paid, gross ticket
    revenue and `settlement_adjustment_cents` are both zero, the 500-cent floor
    still applies, and so `total_cents` equals 500 cents against zero revenue and
    `organizer_payout_cents` comes out negative."
    PRD 3.4: "The result is written to `final_amount_due_cents`, which is null
    until settlement runs."

    Design: Corner/calculations/corner_event_settlement_with_no_paid_registrations_applies_fee_floor
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Empty Books"})
    registration = add_registration(
        event["id"], ticket_type["id"], "unpaid@example.com"
    )
    start_event(event["id"])
    end_event(event["id"])

    settlement = validate_success(
        api.create_event_settlement(
            event["id"], current_event_version(event["id"]), FIN
        ),
        201,
    )
    assert_settlement(settlement)
    assert settlement["subtotal_cents"] == 0
    assert settlement["platform_fee_cents"] == 500, (
        f"The 500-cent floor still applies, got {settlement['platform_fee_cents']}"
    )
    assert settlement["total_cents"] == 500
    assert settlement["organizer_payout_cents"] == -500, (
        f"Expected 0 - 500 = -500, got {settlement['organizer_payout_cents']}"
    )
    assert read_registration(registration["id"])["final_amount_due_cents"] is None, (
        "An UNPAID row never participates, so its final price stays null"
    )
    assert read_event(event["id"])["settlement_adjustment_cents"] == 0


def test_second_event_settlement_after_issue_returns_settlement_exists(api):
    """PRD 3.11: "**The organizer invoice** has `subject_type` of `EVENT`, is
    created against an event under the concurrency guard of Section 2.9, and is
    refused with `ERR_SETTLEMENT_EXISTS` (HTTP 409) when an EVENT settlement for
    the same event already sits in `ISSUED` or `PAID`."
    PRD 3.11: "When the settlement's `subject_type` is `EVENT`, issuance is also
    what closes the event: the owning event transitions `ENDED → SETTLED` and its
    `version` advances."

    Design: Corner/errors/corner_second_event_settlement_after_issue_returns_settlement_exists
    """
    event, ticket_type, settlement = setup_issued_event_settlement(
        event_overrides={"name": "One Invoice"}
    )
    assert settlement["state"] == "ISSUED"

    validate_error(
        api.create_event_settlement(
            event["id"], current_event_version(event["id"]), FIN
        ),
        ApiErrorId.ERR_SETTLEMENT_EXISTS,
    )
    assert read_settlement(settlement["id"])["state"] == "ISSUED"
    assert read_event(event["id"])["state"] == "SETTLED"


def test_settlement_create_with_stale_event_version_returns_412(api):
    """PRD 2.9: "If that value does not equal the event's current `version`, the
    request is rejected with `ERR_STALE_EVENT_VERSION` and HTTP 412, and nothing
    is written — no settlement row, no re-derived registration amounts, no
    supersede."

    Design: Corner/cross_cutting_layers/corner_settlement_create_with_stale_event_version_returns_412
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Stale"})
    start_event(event["id"])
    stale_version = current_event_version(event["id"])
    fresh = end_event(event["id"])
    assert fresh["version"] == stale_version + 1, (
        "Ending the event must advance the version so the earlier read is stale"
    )

    validate_error(
        api.create_event_settlement(event["id"], stale_version, FIN),
        ApiErrorId.ERR_STALE_EVENT_VERSION,
    )
    assert read_event(event["id"])["state"] == "ENDED", (
        "The refused create must not settle the event"
    )
    rows, meta = validate_paginated(
        api.list_settlements(FIN, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 0, (
        f"Nothing is written on a stale-version rejection, got {meta['total_count']} "
        "settlement rows"
    )


def test_new_event_settlement_voids_prior_draft(api):
    """PRD 2.9: "Creating an EVENT settlement is the one write on this platform
    that is guarded by optimistic concurrency control, and it is guarded because
    that write is destructive: a new EVENT settlement supersedes any prior
    `DRAFT` EVENT settlement on the same event by voiding it."
    PRD 3.11: "A prior EVENT settlement still in `DRAFT` is not an obstacle: it
    is superseded, moving to `VOID` as the new one is created. Creation advances
    the event's `version`."

    Design: Corner/cross_cutting_layers/corner_new_event_settlement_voids_prior_draft
    """
    event, ticket_type = setup_ended_event(event_overrides={"name": "Supersede"})
    version_after_end = event["version"]
    first = validate_success(
        api.create_event_settlement(event["id"], version_after_end, FIN), 201
    )
    version_after_create = current_event_version(event["id"])
    assert version_after_create == version_after_end + 1, (
        "Creating an EVENT settlement advances the event's version"
    )

    second = validate_success(
        api.create_event_settlement(event["id"], version_after_create, FIN), 201
    )
    assert read_settlement(first["id"])["state"] == "VOID", (
        "The prior DRAFT is superseded and voided"
    )
    assert read_settlement(second["id"])["state"] == "DRAFT"
    assert second["total_cents"] == 500


def test_finance_admin_cannot_pay_settlement_they_issued(api):
    """PRD 3.11: "And **segregation of duties** applies: the finance operator
    marking the settlement paid must not be the same operator recorded in
    `issued_by_user_id`, or the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.11: "Issuing a settlement moves it `DRAFT → ISSUED` and stamps
    `issued_by_user_id` with the acting `X-User-ID`."

    Design: Corner/cross_cutting_layers/corner_finance_admin_cannot_pay_settlement_they_issued
    """
    event, ticket_type, settlement = setup_issued_event_settlement(
        issuer_user_id="fin-1", event_overrides={"name": "SoD"}
    )
    assert settlement["issued_by_user_id"] == "fin-1"
    assert settlement["total_cents"] == 500

    validate_error(
        api.pay_settlement(settlement["id"], 500, FIN),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    refreshed = read_settlement(settlement["id"])
    assert refreshed["state"] == "ISSUED", (
        "A refused payment leaves the settlement ISSUED"
    )
    assert refreshed["paid_by_user_id"] is None


def test_second_finance_admin_can_pay_issued_settlement(api):
    """PRD 3.11: "Payment moves the settlement `ISSUED → PAID`, stamps
    `paid_by_user_id` with the acting `X-User-ID`, and enforces two conditions.
    The submitted `paid_amount_cents` must equal `total_cents` exactly, failing
    otherwise with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD 3.11: "When the settlement's `subject_type` is `EVENT`, issuance is also
    what closes the event: the owning event transitions `ENDED → SETTLED` and its
    `version` advances."

    Design: Corner/cross_cutting_layers/corner_second_finance_admin_can_pay_issued_settlement
    """
    event, ticket_type, settlement = setup_issued_event_settlement(
        issuer_user_id="fin-1", event_overrides={"name": "SoD OK"}
    )

    paid = validate_success(api.pay_settlement(settlement["id"], 500, FIN2), 200)
    assert paid["state"] == "PAID", f"Expected PAID, got {paid['state']}"
    assert paid["paid_by_user_id"] == "fin-2", (
        f"Expected paid_by_user_id fin-2, got {paid['paid_by_user_id']}"
    )
    assert read_event(event["id"])["state"] == "SETTLED"
