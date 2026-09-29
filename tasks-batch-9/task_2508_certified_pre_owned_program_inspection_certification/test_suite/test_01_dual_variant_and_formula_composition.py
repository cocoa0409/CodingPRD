"""Two lawful readings of one stored fact, and formulas whose step order is pinned.

Six behaviours live here, each one a place where the programme sanctions two
different answers computed from the same rows, or fixes the sequence in which a
multi-input formula must be evaluated:

* the warranty anchor, which begins coverage at the factory expiry date for a car
  still inside its factory term and at the activation date for one whose term has
  lapsed on either axis;
* the dealer's claim ratio under its lifetime-cumulative reading, where nothing
  ever ages out;
* the same dealer's claim ratio under its trailing-window reading, where the very
  same rows can score zero;
* the certification fee, whose volume discount is computed on the subtotal that
  already contains the *capped* surcharge;
* the reconditioning reimbursement, rounded per repair before the repairs are
  summed;
* the warranty claim payout, which pins a pre-claim ratio snapshot, trims to the
  certification's remaining headroom, and only then applies the share.
"""

from test_helpers import (
    active_certification,
    approve_claim,
    assert_dealer_ledger_conservation,
    assert_instant_equals,
    bootstrap_program,
    certification_documents,
    checklist_item_payload,
    claims_of,
    complete_reconditioning,
    create_vehicle,
    file_claim,
    item_p1_payload,
    open_inspection_for,
    read_certification,
    read_dealer,
    read_inspection,
    reconditioning_item_for,
    reconditioning_items,
    record_results,
    reimbursable_for,
    result_row,
    retune_config,
    set_clock,
    submit_inspection,
)

# The car whose factory term has already lapsed on the date axis: 36 months from
# 2022-02-01 expired on 2025-02-01, well before the epoch clock.
LAPSED_IN_SERVICE = "2022-02-01"
LAPSED_ODOMETER = 62000

# The car still inside its factory term on both axes at the epoch clock: 36
# months from 2024-03-15 run to 2027-03-15, and 20000 miles is below 36000.
LIVE_IN_SERVICE = "2024-03-15"
LIVE_ODOMETER = 20000


def _repairable_template_items(count: int) -> list:
    """One uncurable critical point plus `count` repairable MAJOR points.

    Every repairable point takes the default per-item ceiling of 100000 cents, so
    a 1001-cent repair is never trimmed by the point's own cap and the only
    arithmetic on show is the share and its rounding.
    """
    codes = [
        ("S1", "SAFETY", "all restraint systems nominal"),
        ("B1", "BRAKES", "pad friction material above the wear limit"),
        ("E1", "ELECTRICAL", "no stored electrical fault codes"),
    ][:count]
    items = [item_p1_payload()]
    items.extend(
        checklist_item_payload(
            item_code=code,
            category=category,
            severity="MAJOR",
            pass_criteria=criteria,
            reconditioning_allowed=True,
            max_reconditioning_cost_cents=100000,
        )
        for code, category, criteria in codes
    )
    return items


def _inspection_needing_repairs(api, repair_count: int):
    """Close a complete attempt that fails every repairable point of the template."""
    program = bootstrap_program(api, items=_repairable_template_items(repair_count))
    walk = open_inspection_for(api, program)
    rows = [result_row("P1", "PASS")]
    rows.extend(
        result_row(code, "FAIL") for code in ("S1", "B1", "E1")[:repair_count]
    )
    record_results(api, walk.inspection_id, program.technician_headers, rows)
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    return program, walk


def _two_activations_and_one_claim(api, program, adjudication_clock: str):
    """Two activations 13 months apart, with one claim against the earlier car.

    The claim's repair falls in June 2025, so by the epoch clock it sits outside
    any 365-day trailing window while remaining part of the dealer's lifetime
    record for ever.
    """
    retune_config(
        api,
        claim_ratio_probation_threshold=0.6,
        claim_ratio_suspension_threshold=0.9,
    )
    set_clock(api, "2025-06-01T00:00:00Z")
    early = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LAPSED_IN_SERVICE, odometer_miles=LAPSED_ODOMETER
        ),
        started_at="2025-05-30T09:00:00Z",
    )
    set_clock(api, "2025-06-20T00:00:00Z")
    claim = file_claim(
        api,
        program.dealer_headers,
        early.certification_id,
        repair_date="2025-06-15",
        repair_odometer_miles=62500,
        claimed_amount_cents=100000,
    )
    set_clock(api, "2026-07-01T00:00:00Z")
    late = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LAPSED_IN_SERVICE, odometer_miles=LAPSED_ODOMETER
        ),
        started_at="2026-06-28T09:00:00Z",
    )
    set_clock(api, adjudication_clock)
    return early, late, approve_claim(api, claim["id"])


# ─────────────────────────── the warranty anchor ────────────────────────────

def test_warranty_anchor_diverges_on_the_factory_term_still_being_live(api, program):
    """Two cars certified in the same breath anchor their coverage differently.

    PRD §3.7: "The factory basic warranty counts as still active when the
    activation date falls strictly before the factory expiry date **and** the
    inspection's `odometer_at_inspection` is strictly below the factory mileage
    limit."
    PRD §3.7: "When it is still active, `warranty_start_date` is the factory
    expiry date and `warranty_anchor_variant` is `IN_SERVICE_ANCHORED`"
    PRD §3.7: "When the factory warranty has lapsed on either axis,
    `warranty_start_date` is the activation date and `warranty_anchor_variant` is
    `CERTIFICATION_ANCHORED`"
    PRD §3.7: "the in-service-anchored answer always ends strictly later than the
    certification-anchored answer would for the same car"

    Design: Difficulty/dual_variant_calc/warranty_anchor_variant_divergence
    """
    lapsed = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LAPSED_IN_SERVICE, odometer_miles=LAPSED_ODOMETER
        ),
        odometer_at_inspection=LAPSED_ODOMETER,
    )
    live = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LIVE_IN_SERVICE, odometer_miles=LIVE_ODOMETER
        ),
        odometer_at_inspection=LIVE_ODOMETER,
    )

    lapsed_certification = lapsed.certification
    assert lapsed_certification["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert lapsed_certification["warranty_start_date"] == "2026-08-01"
    assert lapsed_certification["warranty_end_date"] == "2027-08-01"
    assert lapsed_certification["warranty_end_miles"] == 74000
    assert lapsed_certification["retention_expires_at"] == "2034-08-01"
    assert_instant_equals(
        lapsed_certification["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
    )
    assert lapsed_certification["fee_charged_cents"] == 120400

    live_certification = live.certification
    assert live_certification["warranty_anchor_variant"] == "IN_SERVICE_ANCHORED"
    assert live_certification["warranty_start_date"] == "2027-03-15"
    assert live_certification["warranty_end_date"] == "2028-03-15"
    assert live_certification["warranty_end_miles"] == 32000
    assert live_certification["retention_expires_at"] == "2035-03-15"
    assert_instant_equals(
        live_certification["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
    )
    assert live_certification["fee_charged_cents"] == 89900

    # Both cars were activated at the same instant, yet the in-service-anchored
    # car's coverage both begins and ends strictly later.
    assert (
        live_certification["warranty_start_date"]
        > lapsed_certification["warranty_start_date"]
    )
    assert (
        live_certification["warranty_end_date"]
        > lapsed_certification["warranty_end_date"]
    )


def test_retention_date_rides_the_anchored_end_date_onto_every_document(api, program):
    """The retention stamp follows the anchor variant onto every retained document.

    PRD §3.7: "`retention_expires_at` is `warranty_end_date` advanced by the
    documentation retention period in calendar years — seven years by default"
    PRD §3.7: "stamps `retained_until` equal to `retention_expires_at` onto
    **every** certification document row of this certification"
    PRD §2.4: "the approval of their parent certification stamps a
    `retained_until` value onto them, which is a completion of the row rather
    than a business mutation, and they still expose neither `updated_at` nor
    `version`"

    Design: Difficulty/dual_variant_calc/warranty_anchor_variant_divergence
    """
    live = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LIVE_IN_SERVICE, odometer_miles=LIVE_ODOMETER
        ),
        odometer_at_inspection=LIVE_ODOMETER,
    )
    certification = live.certification
    assert certification["warranty_end_date"] == "2028-03-15"
    assert certification["retention_expires_at"] == "2035-03-15"
    assert certification["document_count"] == 3

    documents = certification_documents(api, live.certification_id)
    assert len(documents) == 3
    assert sorted(row["doc_type"] for row in documents) == [
        "CUSTOMER_DISCLOSURE",
        "INSPECTION_WORKSHEET",
        "TITLE_HISTORY_REPORT",
    ]
    for row in documents:
        assert row["retained_until"] == "2035-03-15"
        assert "updated_at" not in row
        assert "version" not in row


# ──────────────────────── the two claim-ratio variants ───────────────────────

def test_lifetime_claim_ratio_counts_every_activation_and_every_claim(api, program):
    """Below the volume floor the ratio is the whole-life claim count over activations.

    PRD §3.9: "below that floor it is `LIFETIME_CUMULATIVE`"
    PRD §3.9: "Under `LIFETIME_CUMULATIVE`, `claim_ratio_effective` is
    `approved_claim_count_lifetime` divided by `lifetime_activated_count`, with 1
    substituted when that count is zero, rounded half up to 2 decimals"
    PRD §3.9: "a dealer with one approved claim over two lifetime activations
    scores `0.50`"
    PRD §3.9: "First, the claim pins `dealer_ratio_snapshot_before` to the
    certifying dealer's `claim_ratio_effective` as read *before* this claim is
    counted anywhere."

    Design: Difficulty/dual_variant_calc/dealer_claim_ratio_lifetime_cumulative_variant
    """
    early, late, claim = _two_activations_and_one_claim(
        api, program, "2026-07-01T00:00:00Z"
    )

    assert claim["status"] == "APPROVED"
    assert claim["dealer_ratio_snapshot_before"] == 0.00
    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["approved_claim_count_lifetime"] == 1
    assert dealer["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert dealer["claim_ratio_effective"] == 0.50
    assert dealer["risk_score"] == 30
    assert dealer["privilege_status"] == "ACTIVE"
    assert read_certification(api, early.certification_id)["status"] == "ACTIVE"
    assert read_certification(api, late.certification_id)["status"] == "ACTIVE"


def test_lifetime_claim_ratio_never_ages_a_claim_out(api, program):
    """Adjudicated years later, the lifetime reading still counts the old repair.

    PRD §3.9: "old claims never age out"
    PRD §3.9: "When the dealer's `lifetime_activated_count` is at or above the
    programme's volume floor — 20 activations by default — `claim_ratio_variant`
    is `TRAILING_WINDOW`; below that floor it is `LIFETIME_CUMULATIVE`."
    PRD §3.9: "take `claim_ratio_effective`, multiply by 100, and weight it at 60
    percent; take `audit_fail_rate`, multiply by 100, and weight it at 40
    percent; add the two weighted terms; round the sum half up to a whole number"

    Design: Difficulty/dual_variant_calc/dealer_claim_ratio_lifetime_cumulative_variant
    """
    _, _, claim = _two_activations_and_one_claim(api, program, "2028-01-01T00:00:00Z")

    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert dealer["claim_ratio_effective"] == 0.50
    # §3.9 recomputes `approved_claim_count_window` on this very approval, so it
    # is read against the 2028 clock and the June-2025 repair has aged out of the
    # trailing window. (`window_activated_count` is deliberately not asserted
    # here: §3.9's recomputation list for a claim approval omits it, so the PRD
    # does not fix what it reads once the clock has moved past the activations.)
    assert dealer["approved_claim_count_window"] == 0
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["approved_claim_count_lifetime"] == 1
    assert dealer["audit_fail_rate"] == 0.00
    assert dealer["risk_score"] == 30


def test_trailing_window_claim_ratio_reads_zero_on_the_same_rows(api, program):
    """At the volume floor the identical rows score 0.00 because both fall outside.

    PRD §3.9: "When the dealer's `lifetime_activated_count` is at or above the
    programme's volume floor — 20 activations by default — `claim_ratio_variant`
    is `TRAILING_WINDOW`"
    PRD §3.9: "Under `TRAILING_WINDOW`, `claim_ratio_effective` is
    `approved_claim_count_window` divided by `window_activated_count`, again with
    1 substituted for a zero denominator and rounded half up to 2 decimals"
    PRD §3.9: "the very same dealer with both its claim and its activation
    outside the window scores `0.00` on identical underlying rows"

    Design: Difficulty/dual_variant_calc/dealer_claim_ratio_trailing_window_variant
    """
    retune_config(api, claim_variant_volume_floor=1)
    _, _, claim = _two_activations_and_one_claim(api, program, "2026-08-01T00:00:00Z")

    assert claim["dealer_ratio_snapshot_before"] == 0.00
    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_variant"] == "TRAILING_WINDOW"
    assert dealer["window_activated_count"] == 1
    assert dealer["approved_claim_count_window"] == 0
    assert dealer["claim_ratio_effective"] == 0.00
    assert dealer["risk_score"] == 0
    # The lifetime counters still hold the very rows the window reading ignored.
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["approved_claim_count_lifetime"] == 1
    assert dealer["privilege_status"] == "ACTIVE"


def test_trailing_window_claim_ratio_ignores_the_out_of_window_activation(api, program):
    """A claim inside the window divides by the in-window activations alone.

    PRD §3.9: "numerator and denominator are both restricted to the trailing
    window"
    PRD §3.9: "Both window counters use the **inclusive** span running from the
    claim-window length before the current logical-clock date up to the current
    logical-clock date — 365 days by default"
    PRD §3.9: "When the post-claim `claim_ratio_effective` is at or above the
    programme's suspension threshold of 0.40, `privilege_status` becomes
    `SUSPENDED` with `privilege_reason` `CLAIM_RATIO_SUSPENSION`."

    Design: Difficulty/dual_variant_calc/dealer_claim_ratio_trailing_window_variant
    """
    retune_config(
        api,
        claim_variant_volume_floor=1,
        claim_ratio_probation_threshold=0.6,
        claim_ratio_suspension_threshold=0.9,
    )
    set_clock(api, "2025-06-01T00:00:00Z")
    active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LAPSED_IN_SERVICE, odometer_miles=LAPSED_ODOMETER
        ),
        started_at="2025-05-30T09:00:00Z",
    )
    set_clock(api, "2026-07-01T00:00:00Z")
    recent = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date=LAPSED_IN_SERVICE, odometer_miles=LAPSED_ODOMETER
        ),
        started_at="2026-06-28T09:00:00Z",
    )
    claim = file_claim(
        api,
        program.dealer_headers,
        recent.certification_id,
        repair_date="2026-07-15",
        repair_odometer_miles=62500,
        claimed_amount_cents=100000,
    )
    set_clock(api, "2026-08-01T00:00:00Z")
    claim = approve_claim(api, claim["id"])

    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_variant"] == "TRAILING_WINDOW"
    assert dealer["window_activated_count"] == 1
    assert dealer["approved_claim_count_window"] == 1
    assert dealer["claim_ratio_effective"] == 1.00
    # The lifetime reading of the same rows would have been 1 over 2, or 0.50.
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["approved_claim_count_lifetime"] == 1
    assert dealer["risk_score"] == 60
    assert dealer["privilege_status"] == "SUSPENDED"
    assert dealer["privilege_reason"] == "CLAIM_RATIO_SUSPENSION"


# ───────────────── the fee: cap first, then the volume discount ──────────────

def test_volume_discount_applies_to_the_capped_subtotal(api, program):
    """A six-year, 79000-mile car has its surcharge capped before any discount.

    PRD §3.7: "The surcharge cap is the programme's base fee multiplied by the
    surcharge cap fraction — 35 percent by default — rounded down to whole cents,
    and `fee_surcharge_cents` is the smaller of the raw surcharge and that cap."
    PRD §3.7: "Only then is the subtotal formed, as the base fee (89900 cents by
    default) plus the *capped* `fee_surcharge_cents`."
    PRD §3.7: "The discount is therefore always computed on the *capped*
    subtotal and never on the uncapped surcharge sum."

    Design: Difficulty/combinatorial_formula/certification_fee_cap_before_volume_discount
    """
    retune_config(api, volume_discount_tiers=[{"min_count": 0, "pct": 0.1}])
    walk = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date="2020-09-01", odometer_miles=79000
        ),
        odometer_at_inspection=79000,
    )

    certification = walk.certification
    # Five whole age years less the three free years gives 25000 cents, and
    # three whole 10000-mile blocks above the 40000-mile allowance give 27000:
    # a raw surcharge of 52000 that the 31465-cent cap cuts down.
    assert certification["fee_surcharge_cents"] == 31465
    assert certification["fee_discount_cents"] == 12136
    assert certification["fee_charged_cents"] == 109229

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == 109229
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == 109229
    assert_dealer_ledger_conservation(dealer)


def test_surcharge_cap_binds_even_with_no_discount_tier_in_play(api, program):
    """With the default 0-percent tier the capped subtotal is the whole charge.

    PRD §3.7: "The raw surcharge is the age component plus the mileage
    component."
    PRD §3.7: "`fee_discount_cents` is the subtotal multiplied by the selected
    tier's `pct`, rounded down to whole cents. `fee_charged_cents` is the
    subtotal minus `fee_discount_cents`."
    PRD §2.6: "`volume_discount_tiers` is the ordered list of `min_count`/`pct`
    pairs 0 at 0.0, 10 at 0.05, and 50 at 0.10"

    Design: Difficulty/combinatorial_formula/certification_fee_cap_before_volume_discount
    """
    walk = active_certification(
        api,
        program,
        vehicle=create_vehicle(
            api, in_service_date="2020-09-01", odometer_miles=79000
        ),
        odometer_at_inspection=79000,
    )

    certification = walk.certification
    assert certification["fee_surcharge_cents"] == 31465
    assert certification["fee_discount_cents"] == 0
    assert certification["fee_charged_cents"] == 121365
    # A dealer at zero prior activations lands on the `min_count` 0 tier, whose
    # `pct` of 0.0 leaves the capped subtotal untouched.
    assert read_dealer(api, program.dealer_id)["fee_billed_cents_total"] == 121365


# ───────────── reconditioning: round per repair, then sum, then cap ──────────

def test_reimbursement_rounds_each_repair_before_summing_three_of_them(api):
    """Three 1001-cent repairs owe 1803 cents, not the 1802 of one late rounding.

    PRD §3.5: "take `actual_cost_cents`, multiply by the programme's
    reimbursement share (60 percent by default), round that product half up to
    whole cents, and then take the smaller of that rounded figure and the point's
    `max_reconditioning_cost_cents`"
    PRD §3.5: "round each completed repair's share to whole cents *first*, then
    add the rounded per-item amounts together, iterating the completed repairs in
    `created_at` ascending order"
    PRD §3.5: "three repairs at 1001 cents each give 601 plus 601 plus 601, which
    is 1803 cents, not the 1802 cents a single rounding of the combined 3003
    cents would yield"

    Design: Difficulty/combinatorial_formula/reconditioning_reimbursement_round_per_item_then_sum
    """
    program, walk = _inspection_needing_repairs(api, 3)
    assert walk.inspection["status"] == "RECONDITIONING_REQUIRED"
    assert walk.inspection["failed_recon_count"] == 3

    items = reconditioning_items(api, walk.inspection_id)
    assert len(items) == 3
    for item in items:
        closed = complete_reconditioning(
            api, item["id"], 1001, program.other_technician_headers
        )
        assert closed["status"] == "COMPLETED"
        assert closed["actual_cost_cents"] == 1001
        assert closed["reimbursable_cents"] == 601
        assert closed["reimbursable_cents"] == reimbursable_for(1001, 100000)

    inspection = read_inspection(api, walk.inspection_id)
    assert inspection["total_recon_cost_cents"] == 3003
    assert inspection["total_reimbursable_cents"] == 1803
    assert inspection["status"] == "RECONDITIONING_REQUIRED"


def test_reimbursement_of_two_equal_repairs_also_rounds_before_summing(api):
    """Two 1001-cent repairs owe 1202 cents, where one late rounding gives 1201.

    PRD §2.9: "A per-item reconditioning reimbursement uses **round half up** to
    whole cents, applied to each item *individually before* the items are
    summed."
    PRD §3.5: "`total_recon_cost_cents` is the plain sum of `actual_cost_cents`
    over the inspection's repairs whose status is `COMPLETED`."
    PRD §3.5: "Summing the raw costs and rounding once at the end is wrong and
    produces a different total"

    Design: Difficulty/combinatorial_formula/reconditioning_reimbursement_round_per_item_then_sum
    """
    program, walk = _inspection_needing_repairs(api, 2)

    for code in ("S1", "B1"):
        item = reconditioning_item_for(api, walk.inspection_id, code)
        closed = complete_reconditioning(
            api, item["id"], 1001, program.other_technician_headers
        )
        assert closed["reimbursable_cents"] == 601

    inspection = read_inspection(api, walk.inspection_id)
    assert inspection["total_recon_cost_cents"] == 2002
    assert inspection["total_reimbursable_cents"] == 1202


# ───────────── the claim payout: snapshot, then trim, then share ─────────────

def test_claim_payout_trims_to_headroom_before_applying_the_probation_share(
    api, program
):
    """The second claim on one certification is trimmed first and shared second.

    PRD §3.9: "the remaining headroom on the certification is computed as the
    programme's per-claim ceiling minus the certification's
    `approved_claim_amount_cents` so far, with a negative result treated as zero,
    and the capped amount is the smaller of the claim's `claimed_amount_cents`
    and that headroom"
    PRD §3.9: "the trim happens before the probation share, never after"
    PRD §3.9: "when `dealer_ratio_snapshot_before` is at or above the
    programme's probation threshold of 0.25, the share is the programme's
    probation claim share of 0.80, and otherwise the share is 1.00"
    PRD §3.9: "`approved_amount_cents` is the capped amount multiplied by that
    share, rounded **down** to whole cents"

    Design: Difficulty/combinatorial_formula/claim_reimbursement_snapshot_cap_share_order
    """
    retune_config(api, claim_ratio_suspension_threshold=0.9)
    walk = active_certification(api, program)
    first = file_claim(
        api, program.dealer_headers, walk.certification_id, claimed_amount_cents=200000
    )
    second = file_claim(
        api,
        program.dealer_headers,
        walk.certification_id,
        component_category="ELECTRICAL",
        claimed_amount_cents=200000,
    )

    first = approve_claim(api, first["id"])
    assert first["dealer_ratio_snapshot_before"] == 0.00
    assert first["approved_amount_cents"] == 200000

    second = approve_claim(api, second["id"])
    assert second["dealer_ratio_snapshot_before"] == 1.00
    # Headroom is 250000 less the 200000 already approved, so 50000 is trimmed
    # out first and the 0.80 probation share is applied to that, giving 40000 —
    # not the 160000 a share-then-trim reading would produce.
    assert second["approved_amount_cents"] == 40000

    certification = read_certification(api, walk.certification_id)
    assert certification["approved_claim_count"] == 2
    assert certification["approved_claim_amount_cents"] == 240000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_effective"] == 2.00
    assert dealer["privilege_status"] == "SUSPENDED"
    assert dealer["privilege_reason"] == "CLAIM_RATIO_SUSPENSION"


def test_claim_payout_uses_the_snapshot_taken_before_its_own_effect(api, program):
    """A claim's own contribution to the ratio never reduces its own payout.

    PRD §3.9: "A dealer therefore never has this claim's own effect on its ratio
    reduce this claim's payout, but the very next claim does feel it."
    PRD §3.9: "A new claim is created in `SUBMITTED` with `approved_amount_cents`
    0, `dealer_ratio_snapshot_before` null, `denial_reason` null, and
    `adjudicated_at` null."
    PRD §3.9: "Sixth — and only after that — the privilege thresholds are
    re-evaluated against the post-claim ratio."

    Design: Difficulty/combinatorial_formula/claim_reimbursement_snapshot_cap_share_order
    """
    retune_config(api, claim_ratio_suspension_threshold=0.9)
    walk = active_certification(api, program)
    filed = file_claim(
        api, program.dealer_headers, walk.certification_id, claimed_amount_cents=200000
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["dealer_ratio_snapshot_before"] is None
    assert filed["approved_amount_cents"] == 0

    approved = approve_claim(api, filed["id"])
    assert approved["dealer_ratio_snapshot_before"] == 0.00
    assert approved["approved_amount_cents"] == 200000
    assert_instant_equals(
        approved["adjudicated_at"], "2026-08-01T00:00:00Z", "adjudicated_at"
    )

    # The ratio the payout ignored is exactly the ratio the dealer now carries.
    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_effective"] == 1.00
    assert dealer["privilege_status"] == "SUSPENDED"
    assert dealer["privilege_reason"] == "CLAIM_RATIO_SUSPENSION"

    stored = claims_of(api, walk.certification_id)
    assert len(stored) == 1
    assert stored[0]["dealer_ratio_snapshot_before"] == 0.00
    assert stored[0]["approved_amount_cents"] == 200000
