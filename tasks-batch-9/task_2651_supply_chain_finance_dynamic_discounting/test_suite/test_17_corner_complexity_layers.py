"""Corner-case coverage of the optimistic-concurrency layer of the contract.

Two write operations in this system are guarded against the ``version`` of a
parent row — naming a discount rate against the invoice's version, and reserving
an early payment against the offer's version — and the guard only earns its keep
because both guarded writes leave the parent row's *status* alone while still
advancing its ``version``. The third test walks a programme through
create / open / PAUSE / RESUME to pin the general rule the guards depend on:
every write to the addressed row advances its version by exactly one and
refreshes ``updated_at``, while a read advances nothing.

The harness restarts the API server before every test, so each test builds all
of its own state from an empty database using the shared builders in
``test_helpers.fixtures``.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_STALE_INVOICE_VERSION,
    ERR_STALE_OFFER_VERSION,
)
from test_helpers.assertions import (
    assert_buyer,
    assert_cash_breakdown,
    assert_invoice,
    assert_offer,
    assert_payment,
    assert_payment_axes,
    assert_program,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import make_buyer_admin_headers


def test_stale_expected_invoice_version_on_offer_create_is_rejected():
    """The first successful create takes the invoice's OFFERED -> OFFERED
    self-edge, so its status is unchanged while its version advances: status alone
    can never tell a second writer that its view has fallen behind. Replaying the
    version read before the first create therefore answers 412
    ERR_STALE_INVOICE_VERSION — not a 201 and not a state error — writes no offer
    row, and the identical payload carrying the refreshed version then succeeds
    and supersedes the first offer.

    PRD §2.6: "Naming a discount rate on an invoice — the create operation on the discount-offers collection, `POST /discount-offers` — requires `expected_invoice_version` in its body, carrying the client's last observed `version` of the invoice identified by `invoice_id`."
    PRD §2.6: "If that value does not equal the invoice's current `version`, the create is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412)."
    PRD §3.6: "Naming a fresh rate on an invoice that already carries a `NAMED` or `COUNTERED` offer takes the invoice's self-edge `OFFERED → OFFERED` instead: the prior offers on that invoice whose `status` is `NAMED` or `COUNTERED` become `SUPERSEDED`, in ascending `created_at` order, the new offer is created in `NAMED`, and the invoice's `status` stays `OFFERED` while its `version` still increments by one."
    Design: Corner/complexity_layers/stale_expected_invoice_version_on_offer_create_is_rejected
    """
    ctx = fx.build_eligible_invoice()
    invoice_id = ctx.invoice_id
    v_before = ctx.invoice_version
    assert ctx.invoice["status"] == "ELIGIBLE", (
        "the fixture invoice must open ELIGIBLE, got {!r}".format(ctx.invoice["status"])
    )

    def offer_body(apr_bps, expected_version):
        return f.offer_payload(
            invoice_id,
            ctx.session_id,
            expected_version,
            offered_apr_bps=apr_bps,
            requested_pay_date="2026-08-07T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        )

    offer_1 = validate_success(
        api_client.create_offer(offer_body(900, v_before), ctx.supplier_headers), 201
    )
    assert_offer(offer_1, status="NAMED", offered_apr_bps=900, version=1)

    after_first = validate_success(
        api_client.get_invoice(invoice_id, ctx.supplier_headers), 200
    )
    assert_invoice(after_first, id=invoice_id, status="OFFERED", version=v_before + 1)
    v_after_first = after_first["version"]

    # Replaying the pre-create version: the self-edge hid the write from status.
    validate_error(
        api_client.create_offer(offer_body(850, v_before), ctx.supplier_headers),
        ERR_STALE_INVOICE_VERSION,
        412,
    )

    # The refused create wrote nothing at all.
    offers, offers_meta = validate_paginated(
        api_client.list_offers(ctx.admin, invoice_id=invoice_id)
    )
    assert offers_meta["total_count"] == 1, (
        "the 412 must not have persisted an offer; expected total_count 1, got "
        "{}".format(offers_meta["total_count"])
    )
    assert [o["id"] for o in offers] == [offer_1["id"]]
    assert_invoice(
        validate_success(api_client.get_invoice(invoice_id, ctx.admin), 200),
        id=invoice_id,
        status="OFFERED",
        version=v_after_first,
    )

    # The identical payload with the refreshed version succeeds.
    offer_2 = validate_success(
        api_client.create_offer(offer_body(850, v_after_first), ctx.supplier_headers),
        201,
    )
    assert_offer(offer_2, status="NAMED", offered_apr_bps=850, version=1)
    assert offer_2["id"] != offer_1["id"], "the retry must create a new offer row"

    assert_offer(
        validate_success(api_client.get_offer(offer_1["id"], ctx.admin), 200),
        id=offer_1["id"],
        status="SUPERSEDED",
        version=2,
    )
    assert_invoice(
        validate_success(api_client.get_invoice(invoice_id, ctx.admin), 200),
        id=invoice_id,
        status="OFFERED",
        version=v_before + 2,
    )


def test_stale_expected_offer_version_on_payment_create_is_rejected():
    """A treasury client that read the offer's version at naming time and only
    reserves after the buyer accepts holds a version exactly one behind. The
    offer's source-state precondition passes — it really is ACCEPTED — so nothing
    but the version guard can stop the request, which is what proves
    ``expected_offer_version`` is compared against the live version rather than
    ignored once the state check is satisfied. The refusal encumbers no buyer
    credit, and the retry with the refreshed version bumps the offer again, so a
    second replay of the same value would be stale in its turn.

    PRD §2.6: "Reserving an early payment against an accepted offer — the create operation on the early-payments collection, `POST /early-payments` — requires `expected_offer_version` in its body, carrying the client's last observed `version` of the offer identified by `offer_id`."
    PRD §2.6: "If that value does not equal the offer's current `version`, the create is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412)."
    PRD §3.8: "It also increments the offer's `version` by one, which is what makes any further reservation carrying the old `expected_offer_version` stale."
    Design: Corner/complexity_layers/stale_expected_offer_version_on_payment_create_is_rejected
    """
    ctx = fx.build_named_offer(requested_pay_date="2026-08-07T00:00:00Z")
    v_named = ctx.offer["version"]
    assert v_named == 1, "a freshly named offer starts at version 1, got {}".format(
        v_named
    )
    face_cents = ctx.invoice["face_amount_cents"]
    assert face_cents == 100_000

    accepted = validate_success(api_client.accept_offer(ctx.offer_id, ctx.admin), 200)
    assert_offer(accepted, id=ctx.offer_id, status="ACCEPTED", accepted_apr_bps=900)
    v_accepted = accepted["version"]
    assert v_accepted == v_named + 1, (
        "acceptance increments the offer version by exactly one: expected {}, got "
        "{}".format(v_named + 1, v_accepted)
    )

    # The state precondition is satisfied, so only the OCC comparison can fail.
    validate_error(
        api_client.create_early_payment(
            f.early_payment_payload(ctx.offer_id, v_named), ctx.treasury
        ),
        ERR_STALE_OFFER_VERSION,
        412,
    )
    assert_buyer(
        validate_success(api_client.get_buyer(ctx.buyer_id, ctx.treasury), 200),
        id=ctx.buyer_id,
        credit_used_cents=0,
    )
    payments, payments_meta = validate_paginated(
        api_client.list_early_payments(ctx.treasury, offer_id=ctx.offer_id)
    )
    assert payments_meta["total_count"] == 0, (
        "the 412 must not have persisted a payment, got total_count {}".format(
            payments_meta["total_count"]
        )
    )
    assert payments == []
    assert_offer(
        validate_success(api_client.get_offer(ctx.offer_id, ctx.admin), 200),
        id=ctx.offer_id,
        status="ACCEPTED",
        version=v_accepted,
    )

    # days early on the pay-date basis: 2026-09-30 minus 2026-08-07 == 54.
    expected_days_early = 54
    expected_discount = f.expected_discount_cents(face_cents, 900, expected_days_early)
    assert expected_discount == 1_350, (
        "100000 * 900 * 54 / (10000 * 360) is exactly 1350, got {}".format(
            expected_discount
        )
    )
    expected_net = face_cents - expected_discount
    assert expected_net == 98_650

    payment = validate_success(
        api_client.create_early_payment(
            f.early_payment_payload(ctx.offer_id, v_accepted), ctx.treasury
        ),
        201,
    )
    assert_payment(
        payment,
        offer_id=ctx.offer_id,
        invoice_id=ctx.invoice_id,
        funding_source="BUYER_SELF",
        funder_id=None,
        accepted_apr_bps=900,
        version=1,
    )
    assert_payment_axes(payment, funding_status="RESERVED", settlement_status="UNSENT")
    assert_cash_breakdown(
        payment,
        days_early=expected_days_early,
        discount_amount_cents=expected_discount,
        funder_fee_cents=0,
        net_payment_cents=expected_net,
    )
    assert_buyer(
        validate_success(api_client.get_buyer(ctx.buyer_id, ctx.treasury), 200),
        id=ctx.buyer_id,
        credit_used_cents=expected_net,
    )
    assert_offer(
        validate_success(api_client.get_offer(ctx.offer_id, ctx.admin), 200),
        id=ctx.offer_id,
        status="ACCEPTED",
        version=v_accepted + 1,
    )


def test_version_increments_on_every_write_to_the_addressed_row():
    """Version is not a private counter of the two OCC-guarded creates: every
    state write on the addressed row advances it by exactly one and refreshes
    ``updated_at``, and a read advances neither. Walking a programme through
    create -> open -> PAUSE -> RESUME must therefore yield exactly 1, 2, 3, 4 with
    two interleaved GETs that change nothing, which rules out both a version that
    only tracks the guarded endpoints and a version that jumps by more than one
    per write. The logical clock is moved before each write so the refreshed
    ``updated_at`` is observably different.

    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current instant on every mutation of that row, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."
    PRD §3.1: "Opening also runs the adoption recomputation described in §3.10, which on a fresh programme leaves both counters at 0 and `adoption_rate_pct` at exactly 0.00, and bumps the programme's `version` by one."
    PRD §3.1: "Each of the three actions increments the programme's `version` by one."
    Design: Corner/complexity_layers/version_increments_on_every_write_to_the_addressed_row
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(
        legal_name="Version Walk Buyer", credit_limit_cents=100_000_000
    )
    admin = make_buyer_admin_headers(buyer["id"])

    created = validate_success(
        api_client.create_program(
            f.minimal_program_payload(buyer["id"], name="Version Walk Programme"),
            admin,
        ),
        201,
    )
    program_id = created["id"]
    assert_program(created, status="DRAFT", version=1)
    created_at = created["created_at"]
    ua_create = created["updated_at"]

    read_1 = validate_success(api_client.get_program(program_id, admin), 200)
    assert_program(read_1, id=program_id, status="DRAFT", version=1)
    assert read_1["updated_at"] == ua_create, (
        "a read must not refresh updated_at: {!r} -> {!r}".format(
            ua_create, read_1["updated_at"]
        )
    )

    fx.set_clock("2026-08-03T00:00:00Z")
    opened = validate_success(api_client.open_program(program_id, admin), 200)
    assert_program(
        opened,
        id=program_id,
        status="OPEN",
        version=2,
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert opened["version"] == read_1["version"] + 1, (
        "open advances the version by exactly one: expected {}, got {}".format(
            read_1["version"] + 1, opened["version"]
        )
    )
    assert opened["updated_at"] != ua_create, (
        "open must refresh updated_at, but it is still {!r}".format(ua_create)
    )
    assert opened["created_at"] == created_at, "created_at is written once and never moves"
    ua_open = opened["updated_at"]

    fx.set_clock("2026-08-04T00:00:00Z")
    paused = validate_success(
        api_client.set_program_status(
            program_id, f.program_status_payload("PAUSE"), admin
        ),
        200,
    )
    assert_program(paused, id=program_id, status="PAUSED", version=3)
    assert paused["version"] == opened["version"] + 1, (
        "PAUSE advances the version by exactly one: expected {}, got {}".format(
            opened["version"] + 1, paused["version"]
        )
    )
    assert paused["updated_at"] != ua_open, (
        "PAUSE must refresh updated_at, but it is still {!r}".format(ua_open)
    )
    ua_pause = paused["updated_at"]

    read_2 = validate_success(api_client.get_program(program_id, admin), 200)
    assert_program(read_2, id=program_id, status="PAUSED", version=3)
    assert read_2["updated_at"] == ua_pause, (
        "the second read must not refresh updated_at either: {!r} -> {!r}".format(
            ua_pause, read_2["updated_at"]
        )
    )

    fx.set_clock("2026-08-05T00:00:00Z")
    resumed = validate_success(
        api_client.set_program_status(
            program_id, f.program_status_payload("RESUME"), admin
        ),
        200,
    )
    assert_program(resumed, id=program_id, status="OPEN", version=4)
    assert resumed["version"] == paused["version"] + 1, (
        "RESUME advances the version by exactly one: expected {}, got {}".format(
            paused["version"] + 1, resumed["version"]
        )
    )
    assert resumed["updated_at"] != ua_pause, (
        "RESUME must refresh updated_at, but it is still {!r}".format(ua_pause)
    )
    assert resumed["created_at"] == created_at, "created_at is written once and never moves"

    walk = [
        created["version"],
        read_1["version"],
        opened["version"],
        paused["version"],
        read_2["version"],
        resumed["version"],
    ]
    assert walk == [1, 1, 2, 3, 3, 4], (
        "create / read / open / PAUSE / read / RESUME must walk 1, 1, 2, 3, 3, 4; "
        "got {}".format(walk)
    )
