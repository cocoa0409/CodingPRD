"""Compensating operations: invalid-traffic retraction and refund-claim reversal.

Both compensations are round trips. The forward operation is applied, the
figures are snapshotted, the compensation is applied, and every figure must land
back on exactly its pre-operation value with no residual drift - while the two
deliberate exceptions on a claim reversal (the retained money triple and the
untouched open-claim counter) survive the unwind.
"""
import pytest

from test_helpers import (
    OPERATOR_USER_ID,
    assert_credit_double_entry,
    assert_impression_conservation,
    assert_ivt_finding,
    assert_measurement_batch,
    assert_money_triple,
    assert_refund_claim,
    ensure_page_classified,
    factories,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    read_advertiser,
    read_batch,
    read_campaign,
    read_claim,
    read_finding,
    read_publisher,
    setup_approved_claim,
    setup_base_world,
    setup_confirmed_finding,
    setup_ingested_batch,
    validate_success,
)

OPERATOR = make_operator_headers(OPERATOR_USER_ID)
ADMIN = make_admin_headers()


# ---------------------------------------------------------------------------
# local composition over the shared helpers
# ---------------------------------------------------------------------------
def _scored_batch_world(api):
    """A SCORED DISPLAY batch of 10000 measured / 8000 measurable / 7000 in view
    with no finding confirmed yet, so ivt_impressions is 0 and
    net_billable_impressions is the whole delivery."""
    world = setup_base_world(api)
    ensure_page_classified(api, world)
    batch = setup_ingested_batch(
        api,
        world,
        measurable_impressions=8000,
        in_view_impressions=7000,
        avg_in_view_seconds=1.2,
        avg_in_view_pixel_pct=0.6,
    )
    scored = get_success_data(api.score_measurement_batch(batch["id"], OPERATOR))
    assert scored["scoring_status"] == "SCORED", (
        f"expected SCORED, got {scored['scoring_status']} after score"
    )
    return world, scored


def _confirm(api, batch_id, ivt_class, flagged_impressions, confidence):
    """Confirm one detector finding against the batch, which is the act that
    folds it into the deduplicated invalid-traffic figures."""
    return setup_confirmed_finding(
        api,
        batch_id,
        ivt_class=ivt_class,
        flagged_impressions=flagged_impressions,
        confidence=confidence,
    )


def _retract(api, finding_id, reason):
    response = api.retract_ivt_finding(
        finding_id, factories.retract_finding_payload(retract_reason=reason), OPERATOR
    )
    return validate_success(response, expected_status=200)


def _assert_ivt_figures(batch, ivt, rate, net_billable, sophistication, where):
    """The four invalid-traffic figures plus the conservation invariant."""
    assert batch["ivt_impressions"] == ivt, (
        f"expected ivt_impressions {ivt}, got {batch['ivt_impressions']} {where}"
    )
    assert batch["ivt_rate"] == pytest.approx(rate, abs=0.0001), (
        f"expected ivt_rate {rate}, got {batch['ivt_rate']} {where}"
    )
    assert batch["net_billable_impressions"] == net_billable, (
        f"expected net_billable_impressions {net_billable}, "
        f"got {batch['net_billable_impressions']} {where}"
    )
    assert batch["sophistication_flag"] is sophistication, (
        f"expected sophistication_flag {sophistication}, "
        f"got {batch['sophistication_flag']} {where}"
    )
    assert_impression_conservation(batch)


def _settled_claim_world(api):
    """One QUARANTINED batch with a confirmed DATACENTER finding of 400, cited by
    a claim that has been reviewed and approved, so both halves of the credit
    ledger carry the frozen net credit."""
    world = setup_base_world(api)
    ensure_page_classified(api, world)
    batch = setup_ingested_batch(
        api,
        world,
        measurable_impressions=6000,
        in_view_impressions=5000,
        avg_in_view_seconds=0.8,
        avg_in_view_pixel_pct=0.6,
    )
    _confirm(api, batch["id"], "DATACENTER", 400, 0.90)
    get_success_data(api.score_measurement_batch(batch["id"], OPERATOR))
    adjudicated = get_success_data(api.certify_measurement_batch(batch["id"], OPERATOR))
    assert adjudicated["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {adjudicated['scoring_status']} after certify"
    )
    claim = setup_approved_claim(api, world, batch_ids=[batch["id"]])
    assert claim["claim_state"] == "APPROVED", (
        f"expected APPROVED, got {claim['claim_state']} after approve"
    )
    return world, adjudicated, claim


def _reverse(api, claim_id, reason):
    response = api.reverse_refund_claim(
        claim_id, factories.reverse_claim_payload(reversal_reason=reason), ADMIN
    )
    return validate_success(response, expected_status=200)


# ---------------------------------------------------------------------------
# Retracting a confirmed invalid-traffic finding
# ---------------------------------------------------------------------------
def test_retracting_confirmed_sivt_finding_restores_every_ivt_figure(api):
    """Retracting the confirmed sophisticated finding puts the batch's invalid-traffic figures back on their pre-confirmation values with no drift.

    PRD: "A confirmed finding moves `CONFIRMED → RETRACTED`, and the batch's `ivt_impressions`, `ivt_rate`, `sophistication_flag` and `net_billable_impressions` are recomputed over the findings that remain confirmed, which restores the figures to exactly the values they held before that confirmation with no residual drift — the impression-conservation invariant of §2.11 holds before the confirmation, after it, and again after the matching retraction."

    Design: Difficulty/compensating_invariant/ivt_retract_restores_impression_conservation_with_no_drift
    """
    world, scored = _scored_batch_world(api)
    batch_id = scored["id"]

    # Nothing confirmed yet: the whole measured delivery is billable.
    _assert_ivt_figures(scored, 0, 0.0, 10000, False, "after score")
    assert scored["coverage_rate"] == pytest.approx(0.8, abs=0.0001), (
        f"expected coverage_rate 0.8, got {scored['coverage_rate']} after score"
    )

    datacenter = _confirm(api, batch_id, "DATACENTER", 400, 0.90)
    after_datacenter = read_batch(api, batch_id)
    _assert_ivt_figures(after_datacenter, 400, 0.04, 9600, False, "after confirming DATACENTER")

    general_bot = _confirm(api, batch_id, "GENERAL_BOT", 300, 0.85)
    after_bot = read_batch(api, batch_id)
    _assert_ivt_figures(
        after_bot, 400, 0.04, 9600, False,
        "after confirming GENERAL_BOT (the GIVT family contributes max(400, 300))",
    )

    ad_farm = _confirm(api, batch_id, "SIVT_AD_FARM", 250, 0.95)
    assert_ivt_finding(ad_farm)
    assert ad_farm["ivt_family"] == "SIVT", (
        f"expected ivt_family SIVT, got {ad_farm['ivt_family']} for SIVT_AD_FARM"
    )
    after_farm = read_batch(api, batch_id)
    _assert_ivt_figures(after_farm, 650, 0.065, 9350, True, "after confirming SIVT_AD_FARM")

    retracted = _retract(api, ad_farm["id"], "Fingerprint traced to a whitelisted QA harness")
    assert retracted["status"] == "RETRACTED", (
        f"expected RETRACTED, got {retracted['status']} after retract"
    )

    compensated = read_batch(api, batch_id)
    assert_measurement_batch(compensated)
    _assert_ivt_figures(compensated, 400, 0.04, 9600, False, "after retracting SIVT_AD_FARM")
    for field in (
        "ivt_impressions", "ivt_rate", "net_billable_impressions", "sophistication_flag",
    ):
        assert compensated[field] == after_datacenter[field], (
            f"{field} must return to its pre-confirmation value "
            f"{after_datacenter[field]}, got {compensated[field]} after retract"
        )

    # The surviving confirmed findings are untouched by the compensation.
    for surviving, label in ((datacenter, "DATACENTER"), (general_bot, "GENERAL_BOT")):
        current = read_finding(api, surviving["id"])
        assert current["status"] == "CONFIRMED", (
            f"{label} must stay CONFIRMED, got {current['status']} after retract"
        )
        assert current["flagged_impressions"] == surviving["flagged_impressions"], (
            f"{label} flagged_impressions must stay {surviving['flagged_impressions']}, "
            f"got {current['flagged_impressions']} after retract"
        )

    # The compensation touched only the invalid-traffic terms.
    assert compensated["coverage_rate"] == pytest.approx(0.8, abs=0.0001), (
        f"expected coverage_rate still 0.8, got {compensated['coverage_rate']} after retract"
    )
    assert compensated["scoring_status"] == "SCORED", (
        f"expected scoring_status still SCORED, got {compensated['scoring_status']} after retract"
    )
    assert compensated["qualified_in_view_impressions"] == 7000, (
        "the viewability figures must survive the retraction, got "
        f"{compensated['qualified_in_view_impressions']} qualified in view"
    )


def test_retracting_the_largest_givt_finding_recomputes_from_survivors(api):
    """Retracting the largest confirmed general-invalid-traffic finding falls back to the next surviving detector of that family instead of subtracting the retracted amount.

    PRD: "When a confirmed invalid-traffic finding is retracted, however, the batch's invalid-traffic figures are recomputed from the remaining confirmed findings and land exactly on their pre-confirmation values, with no residual drift."

    Design: Difficulty/compensating_invariant/ivt_retract_restores_impression_conservation_with_no_drift
    """
    world, scored = _scored_batch_world(api)
    batch_id = scored["id"]
    _assert_ivt_figures(scored, 0, 0.0, 10000, False, "after score")

    _confirm(api, batch_id, "GENERAL_BOT", 300, 0.85)
    _confirm(api, batch_id, "SIVT_AD_FARM", 250, 0.95)
    before = read_batch(api, batch_id)
    _assert_ivt_figures(before, 550, 0.055, 9450, True, "with GENERAL_BOT 300 and SIVT 250 confirmed")

    datacenter = _confirm(api, batch_id, "DATACENTER", 400, 0.90)
    after_confirm = read_batch(api, batch_id)
    _assert_ivt_figures(
        after_confirm, 650, 0.065, 9350, True,
        "after confirming DATACENTER 400, which displaces GENERAL_BOT 300 as the GIVT maximum",
    )

    _retract(api, datacenter["id"], "Cloud ASN range reassigned to a residential carrier")

    compensated = read_batch(api, batch_id)
    assert_measurement_batch(compensated)
    # Recomputing over the survivors yields max(300) + 250 = 550. Decrementing the
    # retracted 400 from the running total would leave 250 instead.
    _assert_ivt_figures(compensated, 550, 0.055, 9450, True, "after retracting DATACENTER")
    for field in (
        "ivt_impressions", "ivt_rate", "net_billable_impressions", "sophistication_flag",
    ):
        assert compensated[field] == before[field], (
            f"{field} must return to its pre-confirmation value {before[field]}, "
            f"got {compensated[field]} after retracting the largest GIVT finding"
        )


def test_retracting_a_non_maximal_givt_finding_moves_no_figure_at_all(api):
    """A confirmed general-invalid-traffic finding that never raised the family maximum also leaves every figure exactly where it was when it is retracted.

    PRD: "Only `CONFIRMED` findings enter this computation; `PROPOSED` and `RETRACTED` findings are excluded entirely."

    Design: Difficulty/compensating_invariant/ivt_retract_restores_impression_conservation_with_no_drift
    """
    world, scored = _scored_batch_world(api)
    batch_id = scored["id"]

    datacenter = _confirm(api, batch_id, "DATACENTER", 400, 0.90)
    ad_farm = _confirm(api, batch_id, "SIVT_AD_FARM", 250, 0.95)
    before = read_batch(api, batch_id)
    _assert_ivt_figures(before, 650, 0.065, 9350, True, "with DATACENTER 400 and SIVT 250 confirmed")

    general_bot = _confirm(api, batch_id, "GENERAL_BOT", 300, 0.85)
    after_confirm = read_batch(api, batch_id)
    _assert_ivt_figures(
        after_confirm, 650, 0.065, 9350, True,
        "after confirming GENERAL_BOT 300 behind the larger DATACENTER 400",
    )

    retracted = _retract(api, general_bot["id"], "Declared crawler agents belong to a partner audit")
    assert retracted["status"] == "RETRACTED", (
        f"expected RETRACTED, got {retracted['status']} after retract"
    )

    compensated = read_batch(api, batch_id)
    # Dropping the 300 from the confirmed set leaves the GIVT maximum at 400, so
    # subtracting 300 from the running total would corrupt the figures.
    _assert_ivt_figures(compensated, 650, 0.065, 9350, True, "after retracting GENERAL_BOT")
    for field in (
        "ivt_impressions", "ivt_rate", "net_billable_impressions", "sophistication_flag",
    ):
        assert compensated[field] == before[field], (
            f"{field} must be unchanged at {before[field]}, got {compensated[field]} "
            "after retracting a non-maximal GIVT finding"
        )

    for surviving, label in ((datacenter, "DATACENTER"), (ad_farm, "SIVT_AD_FARM")):
        current = read_finding(api, surviving["id"])
        assert current["status"] == "CONFIRMED", (
            f"{label} must stay CONFIRMED, got {current['status']} after retract"
        )


# ---------------------------------------------------------------------------
# Reversing a settled refund claim
# ---------------------------------------------------------------------------
def test_reversal_unwinds_both_credit_ledgers_back_to_zero(api):
    """Reversing the settled claim subtracts the net credit from the advertiser and the charged publisher alike, returning both halves of the ledger to their pre-approval values.

    PRD: "It moves the claim `APPROVED → REVERSED`, subtracts `net_credit_cents` from both the advertiser's `credit_received_cents_total` and the publisher's `credit_issued_cents_total`, restoring both to exactly their pre-approval values with no drift; decrements the advertiser's `settled_claim_count` by 1; moves every cited batch `settlement_status` `CREDITED → UNBILLED`, which makes those batches citable again by a future claim; and leaves the campaign's `open_claim_count` unchanged, because it was already decremented at approval."

    Design: Difficulty/compensating_invariant/claim_reversal_unwinds_both_credit_ledgers_symmetrically
    """
    world, batch, claim = _settled_claim_world(api)

    # Both legs moved together at approval.
    advertiser = read_advertiser(api, world["advertiser"]["id"])
    publisher = read_publisher(api, world["publisher"]["id"])
    assert_credit_double_entry(advertiser, publisher, 4760)
    assert advertiser["settled_claim_count"] == 1, (
        f"expected settled_claim_count 1, got {advertiser['settled_claim_count']} after approve"
    )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0, got {campaign['open_claim_count']} after approve"
    )
    credited_batch = read_batch(api, batch["id"])
    assert credited_batch["settlement_status"] == "CREDITED", (
        f"expected CREDITED, got {credited_batch['settlement_status']} after approve"
    )

    reversed_claim = _reverse(
        api, claim["id"], "Publisher produced reconciling server logs after settlement"
    )
    assert_refund_claim(reversed_claim)
    assert reversed_claim["claim_state"] == "REVERSED", (
        f"expected REVERSED, got {reversed_claim['claim_state']} after reverse"
    )

    # Both legs unwound, so the difference between them is still zero.
    advertiser_after = read_advertiser(api, world["advertiser"]["id"])
    publisher_after = read_publisher(api, world["publisher"]["id"])
    assert_credit_double_entry(advertiser_after, publisher_after, 0)
    assert (
        advertiser_after["credit_received_cents_total"]
        == publisher_after["credit_issued_cents_total"]
    ), (
        "the two ledger legs must move symmetrically: advertiser "
        f"{advertiser_after['credit_received_cents_total']} vs publisher "
        f"{publisher_after['credit_issued_cents_total']} after reverse"
    )
    assert advertiser_after["settled_claim_count"] == 0, (
        f"expected settled_claim_count 0, got {advertiser_after['settled_claim_count']} "
        "after reverse"
    )

    # The open-claim counter is deliberately left alone: approval already spent it.
    campaign_after = read_campaign(api, world["campaign"]["id"])
    assert campaign_after["open_claim_count"] == 0, (
        f"expected open_claim_count still 0, got {campaign_after['open_claim_count']} "
        "after reverse"
    )

    # The measurement dimension is untouched by the money compensation.
    unbilled = read_batch(api, batch["id"])
    assert_measurement_batch(unbilled)
    assert unbilled["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {unbilled['settlement_status']} after reverse"
    )
    assert unbilled["scoring_status"] == "QUARANTINED", (
        f"expected scoring_status still QUARANTINED, got {unbilled['scoring_status']} "
        "after reverse"
    )
    assert unbilled["ivt_impressions"] == 400, (
        f"expected ivt_impressions still 400, got {unbilled['ivt_impressions']} after reverse"
    )
    assert unbilled["net_billable_impressions"] == 9600, (
        f"expected net_billable_impressions still 9600, "
        f"got {unbilled['net_billable_impressions']} after reverse"
    )
    assert_impression_conservation(unbilled)


def test_reversal_retains_the_frozen_money_figures_as_the_audit_record(api):
    """The reversal is not a full rollback: the money figures frozen at approval survive on the reversed claim as the record of what was unwound.

    PRD: "The frozen money triple — `credited_impressions`, `gross_credit_cents`, `admin_fee_rate`, `admin_fee_cents` and `net_credit_cents` — is deliberately retained as the audit record of what was reversed rather than nulled out, and the claim's `version` increments by 1."

    Design: Difficulty/compensating_invariant/claim_reversal_unwinds_both_credit_ledgers_symmetrically
    """
    world, batch, claim = _settled_claim_world(api)
    assert claim["credited_impressions"] == 6400, (
        f"expected credited_impressions 6400, got {claim['credited_impressions']} after approve"
    )
    assert_money_triple(claim, 5600, 0.15, 840, 4760)

    reversed_claim = _reverse(
        api, claim["id"], "Publisher produced reconciling server logs after settlement"
    )
    assert reversed_claim["claim_state"] == "REVERSED", (
        f"expected REVERSED, got {reversed_claim['claim_state']} after reverse"
    )
    assert reversed_claim["version"] == claim["version"] + 1, (
        f"expected claim version {claim['version'] + 1}, "
        f"got {reversed_claim['version']} after reverse"
    )

    stored = read_claim(api, claim["id"])
    assert stored["credited_impressions"] == 6400, (
        "credited_impressions must be retained as the audit record, got "
        f"{stored['credited_impressions']} after reverse"
    )
    assert_money_triple(stored, 5600, 0.15, 840, 4760)

    # The retained figures did not leak back into the ledgers.
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        0,
    )


def test_reversed_batch_is_citable_again_and_a_second_cycle_stays_symmetric(api):
    """The batch returned to unbilled can be claimed and settled a second time, and both ledger totals track the single approved claim through every cycle.

    PRD: "The sum of `net_credit_cents` over all claims currently in `APPROVED` therefore always equals the total across advertisers' `credit_received_cents_total` and equally the total across publishers' `credit_issued_cents_total`."

    Design: Difficulty/compensating_invariant/claim_reversal_unwinds_both_credit_ledgers_symmetrically
    """
    world, batch, first_claim = _settled_claim_world(api)
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        4760,
    )

    _reverse(api, first_claim["id"], "Publisher produced reconciling server logs after settlement")
    # No claim is in APPROVED any more, so both totals are back at zero.
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        0,
    )

    second_claim = setup_approved_claim(api, world, batch_ids=[batch["id"]])
    assert second_claim["claim_state"] == "APPROVED", (
        f"expected APPROVED, got {second_claim['claim_state']} on the second claim"
    )
    assert second_claim["id"] != first_claim["id"], "the second claim must be a new record"
    assert second_claim["credited_impressions"] == 6400, (
        f"expected credited_impressions 6400, got {second_claim['credited_impressions']} "
        "on the second approval"
    )
    assert_money_triple(second_claim, 5600, 0.15, 840, 4760)

    advertiser = read_advertiser(api, world["advertiser"]["id"])
    publisher = read_publisher(api, world["publisher"]["id"])
    assert_credit_double_entry(advertiser, publisher, 4760)
    assert advertiser["settled_claim_count"] == 1, (
        f"expected settled_claim_count 1, got {advertiser['settled_claim_count']} "
        "after the second approval"
    )
    recredited = read_batch(api, batch["id"])
    assert recredited["settlement_status"] == "CREDITED", (
        f"expected CREDITED, got {recredited['settlement_status']} after the second approval"
    )

    _reverse(api, second_claim["id"], "Second settlement withdrawn pending arbitration")
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        0,
    )
    final_batch = read_batch(api, batch["id"])
    assert final_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {final_batch['settlement_status']} after the second reverse"
    )
    assert read_campaign(api, world["campaign"]["id"])["open_claim_count"] == 0, (
        "open_claim_count must be back at 0 with no live claim"
    )
