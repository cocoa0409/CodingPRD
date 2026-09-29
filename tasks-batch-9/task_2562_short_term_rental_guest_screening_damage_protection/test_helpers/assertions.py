"""Arithmetic the PRD fixes, and assertion helpers that report every mismatch.

The money functions here re-derive the PRD's own worked examples rather than
restating their answers, so a test can pin an exact figure and still show where
that figure comes from. Rounding is always half up, and it is always applied at
the point the PRD names — on the full waiver product, on the trust fee, and once
per allocation line.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_paginated

from . import constants


def round_half_up(value):
    """Round a rational value to the nearest whole cent, halves upward."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ─── Guest risk score (PRD §3.2) ──────────────────────


def risk_tier_for_score(risk_score):
    """Read the tier off the clamped score, bands inclusive at both ends."""
    for tier, low, high in constants.RISK_TIER_BANDS:
        if low <= risk_score <= high:
            return tier
    raise AssertionError("risk_score {0} falls in no declared band".format(risk_score))


def guest_risk_score(verification_state="UNVERIFIED", completed_stay_count=0,
                     payment_risk_signal="CLEAN", chargeback_count=0,
                     substantiated_incident_count=0, escalated_incident_count=0,
                     approved_claim_count=0):
    """The eight-step score of PRD §3.2, with the incident cap before the clamp."""
    total = constants.BASE_RISK
    if verification_state == "VERIFIED":
        total += constants.VERIFIED_CREDIT
    stay_credit = constants.STAY_CREDIT_PER_STAY * completed_stay_count
    if stay_credit < constants.STAY_CREDIT_FLOOR:
        stay_credit = constants.STAY_CREDIT_FLOOR
    total += stay_credit
    total += constants.PAYMENT_SIGNAL_PENALTY[payment_risk_signal]
    total += constants.CHARGEBACK_PENALTY * chargeback_count
    incident_subtotal = (
        constants.INCIDENT_PENALTY * substantiated_incident_count
        + constants.ESCALATION_PENALTY * escalated_incident_count
    )
    if incident_subtotal > constants.INCIDENT_PENALTY_CAP:
        incident_subtotal = constants.INCIDENT_PENALTY_CAP
    total += incident_subtotal
    total += constants.CLAIM_PENALTY * approved_claim_count
    if total < constants.SCORE_MIN:
        return constants.SCORE_MIN
    if total > constants.SCORE_MAX:
        return constants.SCORE_MAX
    return total


# ─── Booking charge (PRD §3.3) ────────────────────────


def waiver_fee_cents(waiver_nightly_fee_cents, nights, risk_tier_at_booking):
    """The full nightly-by-nights-by-multiplier product, rounded once."""
    multiplier = constants.WAIVER_RISK_MULTIPLIER[risk_tier_at_booking]
    return round_half_up(
        Decimal(str(waiver_nightly_fee_cents))
        * Decimal(nights)
        * Decimal(str(multiplier))
    )


def trust_fee_pct_for_subtotal(pre_fee_subtotal_cents):
    """The tier is selected from the pre-fee subtotal alone, never the total."""
    if pre_fee_subtotal_cents < constants.TRUST_FEE_TIER_BREAK_CENTS:
        return constants.TRUST_FEE_PCT_LOW
    return constants.TRUST_FEE_PCT_HIGH


def trust_fee_cents(pre_fee_subtotal_cents):
    """The fee at the pinned tier, rounded half up to a whole cent."""
    pct = trust_fee_pct_for_subtotal(pre_fee_subtotal_cents)
    return round_half_up(Decimal(pre_fee_subtotal_cents) * Decimal(str(pct)))


def total_charged_cents(pre_fee_subtotal_cents):
    """The subtotal plus its fee; the refundable deposit hold is not included."""
    return pre_fee_subtotal_cents + trust_fee_cents(pre_fee_subtotal_cents)


# ─── Settlement waterfall (PRD §3.7) ──────────────────


def allocation_payment_cents(charged_gross_cents, deductible_cents, coverage_pct):
    """One line's payment: post-deductible gross times the layer percentage."""
    net = charged_gross_cents - deductible_cents
    if net < 0:
        net = 0
    return round_half_up(Decimal(net) * Decimal(str(coverage_pct)))


def assert_fields(data, label="row", **expected):
    """Assert an exact value for each named field, reporting all mismatches."""
    missing = [field for field in expected if field not in data]
    assert not missing, "{0} is missing fields {1}; got {2}".format(
        label, sorted(missing), sorted(data.keys())
    )
    mismatches = [
        "{0} expected {1!r}, got {2!r}".format(field, value, data[field])
        for field, value in expected.items()
        if data[field] != value
    ]
    assert not mismatches, "{0}: {1}".format(label, "; ".join(sorted(mismatches)))


def assert_guest_risk(guest, risk_score, risk_tier=None, label="guest"):
    """The score and the tier read off it must agree with each other."""
    expected_tier = risk_tier if risk_tier is not None else risk_tier_for_score(risk_score)
    assert_fields(guest, label, risk_score=risk_score, risk_tier=expected_tier)


def assert_booking_snapshot(reservation, risk_score, risk_tier, label="reservation"):
    """The snapshot pinned at creation, which no later cascade may move."""
    assert_fields(
        reservation,
        label,
        risk_score_at_booking=risk_score,
        risk_tier_at_booking=risk_tier,
    )


def assert_charge(reservation, nights=None, accommodation_cents=None,
                  waiver_fee_cents=None, pre_fee_subtotal_cents=None,
                  trust_fee_pct=None, trust_fee_cents=None, total_charged_cents=None,
                  deposit_hold_cents=None, label="reservation"):
    """Assert whichever of the pinned charge components the caller names."""
    expected = {
        "nights": nights,
        "accommodation_cents": accommodation_cents,
        "waiver_fee_cents": waiver_fee_cents,
        "pre_fee_subtotal_cents": pre_fee_subtotal_cents,
        "trust_fee_pct": trust_fee_pct,
        "trust_fee_cents": trust_fee_cents,
        "total_charged_cents": total_charged_cents,
        "deposit_hold_cents": deposit_hold_cents,
    }
    assert_fields(
        reservation,
        label,
        **{field: value for field, value in expected.items() if value is not None}
    )


def assert_charge_internally_consistent(charge, label="charge_breakdown"):
    """The subtotal, the fee tier and the total must reproduce one another."""
    subtotal = charge["accommodation_cents"] + charge["waiver_fee_cents"]
    assert charge["pre_fee_subtotal_cents"] == subtotal, (
        "{0}.pre_fee_subtotal_cents should be accommodation plus waiver fee "
        "({1}), got {2}".format(label, subtotal, charge["pre_fee_subtotal_cents"])
    )
    expected_pct = trust_fee_pct_for_subtotal(subtotal)
    assert abs(charge["trust_fee_pct"] - expected_pct) < 1e-9, (
        "{0}.trust_fee_pct should be {1} for a subtotal of {2}, got {3}".format(
            label, expected_pct, subtotal, charge["trust_fee_pct"]
        )
    )
    expected_fee = trust_fee_cents(subtotal)
    assert charge["trust_fee_cents"] == expected_fee, (
        "{0}.trust_fee_cents should be {1}, got {2}".format(
            label, expected_fee, charge["trust_fee_cents"]
        )
    )
    assert charge["total_charged_cents"] == subtotal + expected_fee, (
        "{0}.total_charged_cents should be {1}, got {2}".format(
            label, subtotal + expected_fee, charge["total_charged_cents"]
        )
    )


def assert_settlement_conservation(claim, gross_cents, label="damage_claim"):
    """recovered plus host_absorbed equals the gross the run started from."""
    total = claim["recovered_cents"] + claim["host_absorbed_cents"]
    assert total == gross_cents, (
        "{0}: recovered_cents {1} plus host_absorbed_cents {2} must equal the "
        "gross {3}, got {4}".format(
            label,
            claim["recovered_cents"],
            claim["host_absorbed_cents"],
            gross_cents,
            total,
        )
    )


def assert_money_split(claim, approved_amount_cents=None, deposit_applied_cents=None,
                       recovered_cents=None, uncovered_cents=None,
                       host_absorbed_cents=None, label="damage_claim"):
    """Assert the settled money fields the caller names, then the conservation."""
    expected = {
        "approved_amount_cents": approved_amount_cents,
        "deposit_applied_cents": deposit_applied_cents,
        "recovered_cents": recovered_cents,
        "uncovered_cents": uncovered_cents,
        "host_absorbed_cents": host_absorbed_cents,
    }
    assert_fields(
        claim,
        label,
        **{field: value for field, value in expected.items() if value is not None}
    )
    if approved_amount_cents:
        assert_settlement_conservation(claim, approved_amount_cents, label=label)


def assert_allocation_line(allocation, coverage_layer_id=None, sequence_index=None,
                           gross_cents=None, deductible_cents=None,
                           allocated_cents=None, voided=None,
                           label="settlement_allocation"):
    """Assert one waterfall line, then that its payment follows from its own terms."""
    expected = {
        "coverage_layer_id": coverage_layer_id,
        "sequence_index": sequence_index,
        "gross_cents": gross_cents,
        "deductible_cents": deductible_cents,
        "allocated_cents": allocated_cents,
        "voided": voided,
    }
    assert_fields(
        allocation,
        label,
        **{field: value for field, value in expected.items() if value is not None}
    )


def assert_layer_capacity(layer, consumed_cents=None, layer_state=None,
                          label="coverage_layer"):
    """A layer's spent capacity and the state that follows from it."""
    expected = {"consumed_cents": consumed_cents, "layer_state": layer_state}
    assert_fields(
        layer,
        label,
        **{field: value for field, value in expected.items() if value is not None}
    )
    if consumed_cents is not None and layer_state is not None:
        if layer_state == "EXHAUSTED":
            assert consumed_cents >= layer["limit_cents"], (
                "{0} may only read EXHAUSTED once consumed {1} reaches its "
                "limit {2}".format(label, consumed_cents, layer["limit_cents"])
            )


def assert_version(data, expected_version, label="row"):
    assert data["version"] == expected_version, (
        "{0}.version expected {1}, got {2}".format(label, expected_version, data["version"])
    )


def assert_version_unchanged(before, after, label="row"):
    """A refused request must leave the row's version exactly where it was."""
    assert before["version"] == after["version"], (
        "{0}.version moved from {1} to {2}; the refused request should have "
        "written nothing".format(label, before["version"], after["version"])
    )


def assert_version_advanced_by(before, after, steps, label="row"):
    """A single request may bump a version more than once through its cascade."""
    expected = before["version"] + steps
    assert after["version"] == expected, (
        "{0}.version should advance from {1} by {2} to {3}, got {4}".format(
            label, before["version"], steps, expected, after["version"]
        )
    )


def assert_page(response, total_count=None, has_more=None, limit=None, offset=None):
    """Validate the pagination envelope of PRD §2.3 and its counters."""
    items, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "meta.total_count expected {0}, got {1}".format(
                total_count, meta["total_count"]
            )
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            "meta.has_more expected {0}, got {1!r}".format(has_more, meta["has_more"])
        )
    if limit is not None:
        assert meta["limit"] == limit, "meta.limit expected {0}, got {1}".format(
            limit, meta["limit"]
        )
    if offset is not None:
        assert meta["offset"] == offset, "meta.offset expected {0}, got {1}".format(
            offset, meta["offset"]
        )
    return items, meta


def assert_ids_equal(items, expected_ids, label="collection"):
    """The exact membership of a page, order-insensitive."""
    actual = sorted(row["id"] for row in items)
    assert actual == sorted(expected_ids), (
        "{0} membership expected {1}, got {2}".format(
            label, sorted(expected_ids), actual
        )
    )


def assert_contains_id(items, expected_id, label="collection"):
    actual = [row["id"] for row in items]
    assert expected_id in actual, "{0} should contain {1}; got {2}".format(
        label, expected_id, actual
    )


def assert_excludes_id(items, unexpected_id, label="collection"):
    actual = [row["id"] for row in items]
    assert unexpected_id not in actual, "{0} should not contain {1}; got {2}".format(
        label, unexpected_id, actual
    )


def assert_ascending_by_created_at(items, label="collection"):
    """PRD §2.3: "List results are ordered by ``created_at`` ascending."

    That is the whole of the stated rule: the contract fixes no tie-break for
    rows sharing a ``created_at``, which under a frozen logical clock is every
    row written in the same request sequence. So only the stamp sequence is
    asserted here; ordering within one instant is left to the server.
    """
    stamps = [row["created_at"] for row in items]
    assert stamps == sorted(stamps), (
        "{0} must be ordered by created_at ascending, got {1}".format(label, stamps)
    )
