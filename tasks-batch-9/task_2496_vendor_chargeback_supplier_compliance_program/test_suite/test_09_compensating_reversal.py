"""Compensating actions and what they deliberately leave behind.

Reversing a posted deduction must return every money figure to exactly its
pre-posting value while the reversed allocation survives as an audit row rather
than disappearing.  Voiding a violation must return the open counts to exactly
their pre-filing values while the evidence ledger, which is monotonic, keeps
every item it ever accepted.
"""
from test_helpers import (
    REQ_LBL_01,
    add_evidence,
    file_violation,
    read_allocation,
    read_chargeback,
    read_deduction,
    read_shipment,
    read_vendor,
    read_violation,
    reversal_payload,
    setup_posted_deduction,
    setup_program,
    validate_paginated,
    validate_success,
    void_payload,
)


def _reversal_world():
    """A fully recovered chargeback of 425000 netted by a single posted deduction."""
    return setup_posted_deduction(
        425_000,
        invoice_reference="INV-95",
        schedule=None,
        vendor_overrides={
            "vendor_code": "V1501",
            "legal_name": "Unwind Utensils",
            "payment_terms_days": 60,
        },
        guide_overrides={
            "guide_code": "RG-2026-A",
            "title": "Domestic Routing Guide 2026-A",
        },
    )


def _void_world():
    """One evidence-complete labelling finding on a received shipment."""
    world = setup_program(
        REQ_LBL_01,
        vendor_overrides={
            "vendor_code": "V1502",
            "legal_name": "Ledgerkeep Labels",
            "payment_terms_days": 45,
        },
        guide_overrides={
            "guide_code": "RG-2026-A",
            "title": "Domestic Routing Guide 2026-A",
        },
    )
    violation = file_violation(
        world["shipment"]["id"],
        world["requirement"]["id"],
        affected_units=500,
        affected_cartons=20,
        narrative="Carton labels unreadable at the induction scanner.",
    )
    first = add_evidence(violation["id"], kind="PHOTO")
    second = add_evidence(violation["id"], kind="SCAN")
    world["violation"] = read_violation(violation["id"])
    world["evidence"] = [first, second]
    return world


# ---------------------------------------------------------------------------
# Reversing a posted deduction
# ---------------------------------------------------------------------------
def test_deduction_reversal_restores_the_supplier_and_chargeback_money_exactly(
    api, accountant_headers
):
    """PRD §3.9: "Reversal unwinds a posting completely. It requires the deduction
    to be `POSTED`, refused otherwise with `ERR_DEDUCTION_NOT_POSTED`, and takes a
    `reversal_reason`. The deduction moves `POSTED → REVERSED`, stamping
    `reversed_at` and recording the reason; every child allocation flips
    `EFFECTIVE → REVERSED`; the deduction's `over_allocated_cents` is reset to 0."
    PRD §3.9: "Each affected chargeback then recomputes `recovered_cents` with the
    reversed allocations no longer counted, sets `deduction_posted` back to false
    when no effective deduction-sourced allocation remains on it, re-derives
    `outstanding_cents`, and re-derives `settlement_status` — which takes a
    chargeback `PARTIALLY_RECOVERED → ASSESSED` or `RECOVERED → ASSESSED` once its
    `recovered_cents` returns to 0, restoring `outstanding_cents` to
    `gross_assessed_cents` less `reversal_cents`."
    PRD §3.9: "The supplier's `open_chargeback_cents` and
    `recovered_lifetime_cents` return to exactly their pre-posting values, with no
    drift, because both are recomputed from source rows rather than adjusted by a
    delta."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "`refund_due_cents` is the sum, over every one of the supplier's
    chargebacks with no settlement filter at all, of the excess of
    `recovered_cents` over `gross_assessed_cents` less `reversal_cents`, counting
    zero where there is no excess — so a written-off chargeback that still holds
    the supplier's cash contributes its whole recovered amount to the refund owed."
    PRD §3.9: "Finally `exposure_alert_flag` is true exactly when
    `open_chargeback_cents` has reached 500,000 cents or more."

    Design: Difficulty/compensating_invariant/deduction_reversal_restores_vendor_open_exposure_exactly
    """
    world = _reversal_world()
    assert world["chargeback"]["settlement_status"] == "RECOVERED", (
        "posting the full amount must have recovered the chargeback, got "
        f"{world['chargeback']['settlement_status']}"
    )

    reversed_deduction = validate_success(
        api.reverse_deduction(
            world["deduction"]["id"],
            reversal_payload(
                reversal_reason="AP applied the netting to the wrong remittance advice."
            ),
            accountant_headers,
        ),
        200,
    )
    assert reversed_deduction["status"] == "REVERSED", (
        f"expected REVERSED, got {reversed_deduction['status']}"
    )

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["gross_assessed_cents"] == 425000, (
        f"expected gross_assessed_cents 425000, got {chargeback['gross_assessed_cents']}"
    )
    assert chargeback["reversal_cents"] == 0, (
        f"a deduction reversal is not a dispute reversal, expected 0, got "
        f"{chargeback['reversal_cents']}"
    )
    assert chargeback["recovered_cents"] == 0, (
        f"expected recovered_cents 0, got {chargeback['recovered_cents']}"
    )
    assert chargeback["outstanding_cents"] == 425000, (
        f"expected outstanding_cents 425000, got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "ASSESSED", (
        f"expected ASSESSED, got {chargeback['settlement_status']}"
    )
    assert chargeback["deduction_posted"] is False, (
        f"expected deduction_posted false, got {chargeback['deduction_posted']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 425000, (
        f"expected open_chargeback_cents 425000, got {vendor['open_chargeback_cents']}"
    )
    assert vendor["recovered_lifetime_cents"] == 0, (
        f"expected recovered_lifetime_cents 0, got {vendor['recovered_lifetime_cents']}"
    )
    assert vendor["refund_due_cents"] == 0, (
        f"expected refund_due_cents 0, got {vendor['refund_due_cents']}"
    )
    assert vendor["exposure_alert_flag"] is False, (
        "425000 has not reached 500000, expected false, got "
        f"{vendor['exposure_alert_flag']}"
    )


def test_deduction_reversal_keeps_the_allocation_row_as_a_reversed_audit_entry(
    api, accountant_headers, officer_headers
):
    """PRD §3.9: "Reversal unwinds a posting completely. It requires the deduction
    to be `POSTED`, refused otherwise with `ERR_DEDUCTION_NOT_POSTED`, and takes a
    `reversal_reason`. The deduction moves `POSTED → REVERSED`, stamping
    `reversed_at` and recording the reason; every child allocation flips
    `EFFECTIVE → REVERSED`; the deduction's `over_allocated_cents` is reset to 0."
    PRD §3.9: "The deduction document maintains three derived figures of its own.
    Its `amount_cents` is the sum of `allocated_cents` over its allocations whose
    `effective_status` is anything other than `REVERSED`. Its `allocation_count`
    is simply the number of allocations it holds, reversed ones included."
    PRD §2.12: "In every case the compensating action is a forward transition to a
    new state rather than an erasure of history: the original row remains
    readable, with the state that records what happened to it."

    Design: Difficulty/compensating_invariant/deduction_reversal_restores_vendor_open_exposure_exactly
    """
    world = _reversal_world()
    assert world["allocation"]["effective_status"] == "EFFECTIVE", (
        "posting must have made the earmark EFFECTIVE, got "
        f"{world['allocation']['effective_status']}"
    )

    validate_success(
        api.reverse_deduction(
            world["deduction"]["id"],
            reversal_payload(
                reversal_reason="AP applied the netting to the wrong remittance advice."
            ),
            accountant_headers,
        ),
        200,
    )

    deduction = read_deduction(world["deduction"]["id"])
    assert deduction["status"] == "REVERSED", (
        f"expected REVERSED, got {deduction['status']}"
    )
    assert deduction["amount_cents"] == 0, (
        "a reversed allocation stops counting towards the netted amount, expected 0, "
        f"got {deduction['amount_cents']}"
    )
    assert deduction["allocation_count"] == 1, (
        "the audit count keeps the reversed allocation, expected 1, got "
        f"{deduction['allocation_count']}"
    )
    assert deduction["over_allocated_cents"] == 0, (
        f"expected over_allocated_cents 0, got {deduction['over_allocated_cents']}"
    )

    allocation = read_allocation(world["allocation"]["id"])
    assert allocation["effective_status"] == "REVERSED", (
        f"expected the allocation REVERSED, got {allocation['effective_status']}"
    )
    assert allocation["allocated_cents"] == 425000, (
        "the reversed row keeps the amount it once applied, expected 425000, got "
        f"{allocation['allocated_cents']}"
    )

    _, meta = validate_paginated(
        api.list_allocations(
            officer_headers, params={"chargeback_id": world["chargeback"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the reversed allocation is still listed, expected 1, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Voiding a violation
# ---------------------------------------------------------------------------
def test_violation_void_restores_the_open_counts_to_their_pre_filing_values(
    api, officer_headers
):
    """PRD §3.4: "The void takes the violation `DETECTED → VOIDED` or
    `EVIDENCE_COMPLETE → VOIDED` with an identical side-effect set from either
    origin: the recorded `void_reason` is stored, the shipment's
    `open_violation_count` and the supplier's `open_violation_count` each fall by
    one to exactly their pre-filing values, and the violation's `version`
    increments."
    PRD §3.4: "Voiding mints no chargeback and touches no money field on the
    supplier; that asymmetry with the other terminal branch is the whole point of
    the fork."

    Design: Difficulty/compensating_invariant/violation_void_restores_open_counts_but_not_the_evidence_ledger
    """
    world = _void_world()
    before = read_shipment(world["shipment"]["id"])
    assert before["open_violation_count"] == 1, (
        f"expected one open finding before the void, got {before['open_violation_count']}"
    )
    assert before["evidence_capture_count"] == 2, (
        f"expected evidence_capture_count 2 before the void, got "
        f"{before['evidence_capture_count']}"
    )

    voided = validate_success(
        api.void_violation(
            world["violation"]["id"],
            void_payload(
                void_reason="Detection was in error; overlabels were present."
            ),
            officer_headers,
        ),
        200,
    )
    assert voided["status"] == "VOIDED", (
        f"expected VOIDED, got {voided['status']}"
    )

    shipment = read_shipment(world["shipment"]["id"])
    assert shipment["open_violation_count"] == 0, (
        f"expected the shipment's open_violation_count back to 0, got "
        f"{shipment['open_violation_count']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_violation_count"] == 0, (
        f"expected the supplier's open_violation_count back to 0, got "
        f"{vendor['open_violation_count']}"
    )
    assert vendor["open_chargeback_cents"] == 0, (
        f"a void mints no money, expected 0, got {vendor['open_chargeback_cents']}"
    )

    _, meta = validate_paginated(
        api.list_chargebacks(
            officer_headers, params={"violation_id": world["violation"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a void mints no chargeback, expected 0, got {meta['total_count']}"
    )


def test_violation_void_leaves_the_evidence_ledger_undisturbed(api, officer_headers):
    """PRD §3.4: "The shipment's `evidence_capture_count` is pointedly not
    decremented — the evidence remains, and so does the count of it."
    PRD §2.12: "A shipment's `evidence_capture_count` counts every evidence item
    ever captured against any violation on that shipment, and it is deliberately
    not decremented when a violation is voided — the photographs were taken, the
    inspection happened, and the audit record of that work survives the withdrawal
    of the finding."
    PRD §3.4: "The stored item records `captured_by_user_id` from the acting
    `X-User-ID` and `captured_at` from the current logical clock, carries
    `subject_type` `VIOLATION` with the owning `violation_id` set and `dispute_id`
    null, and is never modified thereafter."
    PRD §3.4: "Each capture raises the violation's `evidence_count` by one and the
    shipment's `evidence_capture_count` by one."

    Design: Difficulty/compensating_invariant/violation_void_restores_open_counts_but_not_the_evidence_ledger
    """
    world = _void_world()
    validate_success(
        api.void_violation(
            world["violation"]["id"],
            void_payload(
                void_reason="Detection was in error; overlabels were present."
            ),
            officer_headers,
        ),
        200,
    )

    shipment = read_shipment(world["shipment"]["id"])
    assert shipment["evidence_capture_count"] == 2, (
        "the capture ledger is monotonic and survives the void, expected 2, got "
        f"{shipment['evidence_capture_count']}"
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "VOIDED", (
        f"expected VOIDED, got {violation['status']}"
    )
    assert violation["evidence_count"] == 2, (
        "the finding keeps the evidence it accumulated, expected 2, got "
        f"{violation['evidence_count']}"
    )

    items, meta = validate_paginated(
        api.list_violation_evidence(world["violation"]["id"], officer_headers)
    )
    assert meta["total_count"] == 2, (
        f"both evidence items survive the void, expected 2, got {meta['total_count']}"
    )
    for item in items:
        assert item["subject_type"] == "VIOLATION", (
            f"evidence filed against a finding is subject_type VIOLATION, got "
            f"{item['subject_type']}"
        )
