"""Immediate consistency of the money ladder.

Nothing about an assessment is deferred: the response that mints a chargeback
already carries every computed figure, and the reads issued straight afterwards
already show the derived state on the finding and on the supplier.
"""
from datetime import datetime, timezone

from test_helpers import (
    REQ_LBL_01,
    file_violation,
    setup_program,
    validate_success,
)

RECEIPT_DAY = "2026-08-10T00:00:00Z"


def _instant(value: str) -> datetime:
    """Compare two ISO 8601 UTC instants without depending on their spelling."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_assessment_response_already_carries_every_derived_value(
    api, officer_headers
):
    """PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."
    PRD §3.5: "It opens with `reversal_cents` 0, `recovered_cents` 0,
    `outstanding_cents` equal to `gross_assessed_cents`, `deduction_posted` false,
    `dispute_status` `NONE` and `settlement_status` `ASSESSED`."
    PRD §3.5: "The first link moves the violation to `CHARGED` and lowers both the
    shipment's `open_violation_count` and the supplier's `open_violation_count` by
    one, restoring them to their pre-filing values just as a void would."
    PRD §2.7: "When `min_evidence_count` is 0 the violation was born
    `EVIDENCE_COMPLETE` and this rung passes on an empty evidence set."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "Finally `exposure_alert_flag` is true exactly when
    `open_chargeback_cents` has reached 500,000 cents or more."

    Design: Corner/consistency_model/corner_assessment_response_already_carries_every_derived_value
    """
    world = setup_program(
        REQ_LBL_01,
        vendor_overrides={
            "vendor_code": "V2072",
            "legal_name": "Immediate Imports",
            "payment_terms_days": 30,
        },
        requirement_overrides={"min_evidence_count": 0},
    )
    violation = file_violation(
        world["shipment"]["id"],
        world["requirement"]["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels on four cartons.",
    )

    chargeback = validate_success(
        api.assess_violation(
            violation["id"],
            {"assessment_note": "Label scan failures confirmed."},
            officer_headers,
        ),
        201,
    )

    # The minting response itself already carries the whole computation.
    assert chargeback["gross_assessed_cents"] == 38000, (
        f"expected 38000 cents assessed, got {chargeback['gross_assessed_cents']}"
    )
    assert chargeback["outstanding_cents"] == 38000, (
        f"outstanding opens equal to the assessed figure, "
        f"got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "ASSESSED", (
        f"the settlement dimension opens at ASSESSED, "
        f"got {chargeback['settlement_status']}"
    )
    assert chargeback["dispute_status"] == "NONE", (
        f"the dispute dimension opens at NONE, got {chargeback['dispute_status']}"
    )
    assert chargeback["evidence_at_assessment_count"] == 0, (
        f"an empty evidence set snapshots as 0, "
        f"got {chargeback['evidence_at_assessment_count']}"
    )
    assert _instant(chargeback["assessed_at"]) == _instant(RECEIPT_DAY), (
        f"assessed_at reads the logical clock {RECEIPT_DAY}, "
        f"got {chargeback['assessed_at']}"
    )

    # The read issued straight afterwards, with no intervening write, already
    # shows the finding charged.
    charged = validate_success(api.get_violation(violation["id"], officer_headers), 200)
    assert charged["status"] == "CHARGED", (
        f"the finding reads CHARGED immediately, got {charged['status']}"
    )

    # And the supplier's exposure figures are already reconciled.
    supplier = validate_success(
        api.get_vendor(world["vendor"]["id"], officer_headers), 200
    )
    assert supplier["open_chargeback_cents"] == 38000, (
        f"exposure should already read 38000 cents, "
        f"got {supplier['open_chargeback_cents']}"
    )
    assert supplier["exposure_alert_flag"] is False, (
        f"38000 cents is far below the 500000-cent alert threshold, "
        f"got {supplier['exposure_alert_flag']}"
    )
