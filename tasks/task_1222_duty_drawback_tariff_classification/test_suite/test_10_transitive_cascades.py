"""Transitive cascades: the depth-3 entry-correction chain and the depth-2
payment cascade onto invoice, client aggregates, and compliance records."""
from test_helpers import get_invoice_for_claim, get_records_for_claim, record_payment, setup_approved_claim, setup_draft_claim_with_line, TEST_USERS, validate_success

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_entry_correction_cascades_entry_then_line_then_claim_estimate(api):
    """PRD 3.6: "A successful correction is itself a three-link cascade. The
    entry's own fields are updated and its eligible-duty figures —
    `non_drawbackable_cents`, `drawback_eligible_duty_cents`,
    `unclaimed_duty_cents` — are recomputed against the active measures. Then
    every `ACTIVE` claim line referencing the entry that belongs to a claim
    still in `DRAFT` has its `drawback_amount_cents` re-evaluated against the
    new entry figures. Finally, each affected draft claim's `estimate_cents` is
    recomputed."

    Design: Difficulty/transitive_cascade/entry_correction_cascade_depth3
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    validate_success(
        api.correct_import_entry(
            ctx["entry"]["id"],
            {"duty_paid_cents": 41250,
             "expected_import_entry_version": entry["version"]},
            ANALYST,
        )
    )

    # Link 1 — the entry itself.
    entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry_after["drawback_eligible_duty_cents"] == 41250
    assert entry_after["unclaimed_duty_cents"] == 24915

    # Link 2 — the ACTIVE line on the DRAFT claim re-rated by the entry mutation.
    line_after = validate_success(api.get_claim_line(ctx["line"]["id"], ANALYST))
    assert line_after["drawback_amount_cents"] == 16335, (
        f"line re-rated by the entry mutation: expected 16335, "
        f"got {line_after['drawback_amount_cents']}"
    )

    # Link 3 — the claim estimate recomputed by the line mutation.
    claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim_after["estimate_cents"] == 16335


def test_entry_correction_bumps_version_on_every_touched_entity(api):
    """PRD 3.6: "Every entity the cascade touches — entry, lines, claims — has
    its `version` incremented."
    PRD 2.5: "The `version` is an integer that starts at 1 on creation and
    increments by one on every mutation of the resource — including mutations
    driven by cross-entity cascades, so a single client-visible operation may
    advance the versions of several resources at once."

    Design: Difficulty/transitive_cascade/entry_correction_cascade_depth3
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    entry_v = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))["version"]
    line_v = validate_success(api.get_claim_line(ctx["line"]["id"], ANALYST))["version"]
    claim_v = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))["version"]

    validate_success(
        api.correct_import_entry(
            ctx["entry"]["id"],
            {"duty_paid_cents": 41250, "expected_import_entry_version": entry_v},
            ANALYST,
        )
    )

    entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    line_after = validate_success(api.get_claim_line(ctx["line"]["id"], ANALYST))
    claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert entry_after["version"] == entry_v + 1
    assert line_after["version"] == line_v + 1, "line version advances with the re-rate"
    assert claim_after["version"] == claim_v + 1, "claim version advances with the estimate"


def test_payment_creates_the_invoice_with_settled_tiered_fee(api):
    """PRD 3.5: "Second, an `Invoice` is auto-created in `ISSUED` status with
    its `claim_id` and `client_id` copied from the claim, `recovered_duty_cents`
    snapshotting `paid_duty_cents`, `fee_bps_snapshot` capturing the client's
    `contingency_fee_bps` at that instant — so a later fee renegotiation never
    reopens a settled invoice — and `fee_cents` computed per the settled tiered
    schedule of §3.7."

    Design: Difficulty/transitive_cascade/claim_payment_cascade_depth2
    """
    ctx = setup_approved_claim(approved_duty_cents=32670)

    record_payment(ctx["claim"]["id"], 32670)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    invoice = get_invoice_for_claim(ctx["claim"]["id"])
    assert claim["status"] == "PAID"
    assert invoice["status"] == "ISSUED"
    assert invoice["fee_cents"] == 8168, (
        f"settled fee on 32670 @ 2500 bps = round_half_up(8167.5) = 8168; "
        f"got {invoice['fee_cents']}"
    )
    assert invoice["recovered_duty_cents"] == 32670
    assert invoice["fee_bps_snapshot"] == 2500
    assert invoice["claim_id"] == ctx["claim"]["id"]
    assert invoice["client_id"] == ctx["client"]["id"]


def test_payment_moves_client_aggregates_and_starts_the_retention_clock(api):
    """PRD 3.5: "Third, the client's aggregates move: `lifetime_recovered_cents`
    grows by `paid_duty_cents`, `projected_fee_accrual_cents` is recomputed
    because the claim has left the `APPROVED` accrual set, and the client's
    `version` increments. In the same act, the claim's three compliance records
    each receive `retention_until` set to `paid_at` plus three years, with each
    record's `version` incremented — the statutory retention clock starts
    ticking at payment, not before."
    PRD 1: "Before any operator explicitly sets it, the logical clock reads
    exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock."

    Design: Difficulty/transitive_cascade/claim_payment_cascade_depth2
    """
    ctx = setup_approved_claim(approved_duty_cents=32670)

    paid = validate_success(
        api.record_payment(ctx["claim"]["id"], {"paid_duty_cents": 32670}, ADMIN)
    )
    assert paid["status"] == "PAID"
    assert paid["paid_at"] == "2026-05-01T00:00:00Z", (
        "paid_at is stamped from the untouched logical clock's default"
    )

    client = validate_success(api.get_client(ctx["client"]["id"], ADMIN))
    assert client["lifetime_recovered_cents"] == 32670
    assert client["projected_fee_accrual_cents"] == 0, (
        "the claim has left the APPROVED accrual set"
    )

    records = get_records_for_claim(ctx["claim"]["id"])
    assert len(records) == 3
    for rec in records:
        assert rec["retention_until"] == "2029-05-01T00:00:00Z", (
            f"paid_at + 3 years; got {rec['retention_until']}"
        )
        assert rec["status"] == "RETAINED"
