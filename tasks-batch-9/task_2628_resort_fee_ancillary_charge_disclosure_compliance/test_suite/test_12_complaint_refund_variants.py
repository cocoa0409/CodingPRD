"""Complaint entitlement variants and the refund-ceiling boundary."""
from test_helpers import (
    ApiErrorId,
    FOLIO_CHARGES_SUBTOTAL_CENTS,
    FOLIO_RESORT_AMOUNT_CENTS,
    FOLIO_TAX_TOTAL_CENTS,
    FOLIO_TOTAL_CENTS,
    FOLIO_WIFI_AMOUNT_CENTS,
    add_complaint,
    read_booking,
    read_folio,
    read_profile,
    read_property,
    setup_substantiated_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENT, COMPLIANCE, COMPLIANCE_2

MISSTATED_DISCLOSURE = {"disclosed_fee_amounts": {"RESORT": 6000}}


def _substantiate(api, complaint_id):
    validate_success(api.investigate_complaint(complaint_id, COMPLIANCE))
    return validate_success(api.substantiate_complaint(complaint_id, COMPLIANCE_2))


def test_full_fee_refund_entitlement_is_the_line_amount_plus_its_line_tax(api):
    """A never-disclosed exempt line is owed its whole 2600 cents.

    PRD 3.7: "Under `FULL_FEE_REFUND`, selected when `complaint_reason` is
    `NOT_DISCLOSED`, `TOTAL_NOT_SHOWN` or `MANDATORY_NOT_AVOIDABLE`, the guest
    was never told about the charge at all, so `refund_entitlement_cents` is the
    line's `amount_cents` plus the line's `tax_cents` — the tax already rounded
    on the line, so this variant introduces no rounding of its own — and
    `disclosed_fee_amounts` is ignored entirely." The canonical folio pins it:
    "A `FULL_FEE_REFUND` against the exempt per-person line, amount 2600 with
    `tax_cents` 0, yields an entitlement of 2600."

    Design: Difficulty/dual_variant_calc/complaint_refund_full_fee_versus_disclosure_gap_differential
    """
    env = setup_substantiated_complaint(
        fee_code="WIFI_PREMIUM",
        complaint_overrides={"complaint_reason": "NOT_DISCLOSED"},
        booking_overrides=MISSTATED_DISCLOSURE,
    )

    complaint = validate_success(api.get_guest_complaint(env["complaint"]["id"], AGENT))

    assert complaint["status"] == "SUBSTANTIATED"
    assert complaint["refund_variant"] == "FULL_FEE_REFUND"
    assert complaint["disputed_amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    # The map never mentioned this code, so nothing was disclosed for it.
    assert complaint["disclosed_amount_cents"] == 0
    assert complaint["refund_entitlement_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert complaint["refunded_amount_cents"] == 0
    assert complaint["dismissal_reason_code"] is None

    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED"


def test_disclosure_gap_differential_taxes_the_differential_afresh(api):
    """A misstated 8970 line disclosed at 6000 is owed 3367, not 10170 or 3368.

    PRD 3.7: "Under `DISCLOSURE_GAP_DIFFERENTIAL`, selected when
    `complaint_reason` is `MISSTATED_AMOUNT`, the guest was told a smaller
    number, so only the difference is owed. The differential is the line's
    `amount_cents` minus `disclosed_amount_cents`, floored at 0, and
    `refund_entitlement_cents` is that differential plus the differential times
    the line's own `tax_rate_bps` divided by 10000, **rounded half up
    independently** of the tax already carried on the line. Because that tax is
    rounded afresh, the differential refund is **not** a proportional slice of
    the full refund." The canonical folio pins it: "gives a differential of 2970
    and a tax of 397.386 rounded to 397, so `refund_entitlement_cents` is 3367 —
    not the 10170 that 8970 plus 1200 would give, and not the 3368 that a
    proportional slice of 10170 would give."

    Design: Difficulty/dual_variant_calc/complaint_refund_full_fee_versus_disclosure_gap_differential
    """
    env = setup_substantiated_complaint(
        fee_code="WIFI_PREMIUM",
        complaint_overrides={"complaint_reason": "NOT_DISCLOSED"},
        booking_overrides=MISSTATED_DISCLOSURE,
    )
    full_fee = env["complaint"]

    misstated = add_complaint(
        env,
        fee_code="RESORT",
        complaint_reason="MISSTATED_AMOUNT",
        narrative="The resort fee was quoted to me at sixty dollars for the stay.",
    )
    complaint = _substantiate(api, misstated["id"])

    assert complaint["status"] == "SUBSTANTIATED"
    assert complaint["refund_variant"] == "DISCLOSURE_GAP_DIFFERENTIAL"
    assert complaint["disputed_amount_cents"] == FOLIO_RESORT_AMOUNT_CENTS
    assert complaint["disclosed_amount_cents"] == 6000
    assert complaint["refund_entitlement_cents"] == 3367
    assert complaint["refund_entitlement_cents"] != 10170
    assert complaint["refund_entitlement_cents"] != 3368

    # The first complaint's own entitlement is untouched by the second variant.
    first = validate_success(api.get_guest_complaint(full_fee["id"], AGENT))
    assert first["refund_variant"] == "FULL_FEE_REFUND"
    assert first["refund_entitlement_cents"] == FOLIO_WIFI_AMOUNT_CENTS

    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED"
    profile = read_profile(env["profile"]["id"])
    assert profile["confirmed_undisclosed_count"] == 2
    assert profile["disclosure_score"] == 90
    assert profile["status"] == "DEPLOYED"
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 90
    assert prop["disclosure_posture"] == "COMPLIANT"


def test_refund_one_cent_above_entitlement_is_rejected_and_changes_nothing(api):
    """2601 against an entitlement of 2600 leaves the ledger byte-identical.

    PRD 3.7: "it requires `refund_amount_cents` to be at least 1 and at most
    `refund_entitlement_cents`, equality being permitted and one cent over being
    rejected with `ERR_REFUND_EXCEEDS_ENTITLEMENT` (HTTP 422)".

    Design: Difficulty/boundary_precision_check/refund_at_exactly_entitlement_passes_one_cent_over_is_rejected
    """
    env = setup_substantiated_complaint(fee_code="WIFI_PREMIUM")
    complaint_id = env["complaint"]["id"]
    folio_before = read_folio(env["folio"]["id"])
    assert folio_before["status"] == "POSTED"
    assert folio_before["line_count"] == 4
    assert folio_before["folio_total_cents"] == FOLIO_TOTAL_CENTS
    assert env["complaint"]["refund_entitlement_cents"] == FOLIO_WIFI_AMOUNT_CENTS

    validate_error(
        api.refund_complaint(complaint_id, FOLIO_WIFI_AMOUNT_CENTS + 1, AGENT),
        ApiErrorId.ERR_REFUND_EXCEEDS_ENTITLEMENT,
    )

    complaint = validate_success(api.get_guest_complaint(complaint_id, AGENT))
    assert complaint["status"] == "SUBSTANTIATED"
    assert complaint["refunded_amount_cents"] == 0

    folio_after = read_folio(env["folio"]["id"])
    assert folio_after == folio_before
    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED"
    assert booking["guest_out_of_pocket_cents"] == FOLIO_TOTAL_CENTS


def test_refund_at_exactly_the_entitlement_pays_and_cures_the_booking(api):
    """2600 exactly is paid, appended as line 5, and cures the booking.

    PRD 3.7: "It appends one `COMPLAINT_REFUND` line with `amount_cents` equal
    to `refund_amount_cents` carried **positive** under the credit sign
    convention, `tax_cents` of 0 and `taxability_determination` `EXEMPT` —
    because the entitlement already includes whatever tax was collected, taxing
    the refund line again would double-count. It records
    `refunded_amount_cents`, moves the folio `POSTED → ADJUSTED` or leaves it in
    `ADJUSTED`, re-derives the folio subtotals and the booking's
    `folio_total_cents` and `guest_out_of_pocket_cents`, moves the booking's
    `disclosure_status` from `UNDISCLOSED_CONFIRMED` to `CURED` ... Curing the
    booking removes its gap from the property's aggregate while **leaving the
    path's `confirmed_undisclosed_count` intact**".

    Design: Difficulty/boundary_precision_check/refund_at_exactly_entitlement_passes_one_cent_over_is_rejected
    """
    env = setup_substantiated_complaint(fee_code="WIFI_PREMIUM")
    complaint_id = env["complaint"]["id"]

    complaint = validate_success(
        api.refund_complaint(complaint_id, FOLIO_WIFI_AMOUNT_CENTS, AGENT)
    )

    assert complaint["status"] == "REFUNDED"
    assert complaint["refunded_amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS

    lines, _meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": env["folio"]["id"], "limit": 100})
    )
    refund_lines = [line for line in lines if line["line_type"] == "COMPLAINT_REFUND"]
    assert len(refund_lines) == 1
    refund_line = refund_lines[0]
    assert refund_line["amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert refund_line["tax_cents"] == 0
    assert refund_line["taxability_determination"] == "EXEMPT"
    assert refund_line["sequence_no"] == 5

    folio = read_folio(env["folio"]["id"])
    assert folio["status"] == "ADJUSTED"
    assert folio["line_count"] == 5
    assert folio["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert folio["credits_total_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert folio["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == 152552

    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "CURED"
    assert booking["folio_total_cents"] == 152552
    assert booking["guest_out_of_pocket_cents"] == 152552

    profile = read_profile(env["profile"]["id"])
    assert profile["confirmed_undisclosed_count"] == 1
    assert profile["disclosure_score"] == 95

    prop = read_property(env["property"]["id"])
    assert prop["aggregate_disclosure_gap_cents"] == 0
    assert prop["open_disclosure_obligation_count"] == 0

    # REFUNDED is terminal, so a second payment is an inadmissible transition.
    validate_error(
        api.refund_complaint(complaint_id, 1, AGENT), ApiErrorId.ERR_INVALID_STATE
    )
