"""Teardown damage assessment, the dispute cycle, and final lease settlement."""
from test_helpers import (
    DALLAS,
    DALLAS_DAMAGE,
    RURAL_DAMAGE,
    ApiErrorId,
    assert_damage_assessment,
    assert_damage_line_item,
    assert_exposure_matches_leases,
    assert_lease,
    dispute_assessment,
    finalize_assessment,
    get_assessment,
    get_customer,
    get_lease,
    make_customer_headers,
    make_damage_assessor_headers,
    make_fleet_admin_headers,
    setup_dallas_draft_assessment,
    setup_dallas_lease,
    setup_dallas_submitted_assessment,
    setup_rural_draft_assessment,
    setup_rural_submitted_assessment,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── The lease charge total: projection versus actual ────────────────────────

def test_quoted_projection_prices_the_full_contracted_term(api):
    """PRD §3.4: "Finally the system projects `quoted_total_cents`, the
    forward-looking value of the deal as signed: the mobilization fee plus the
    sum of the monthly base rate and the monthly accessory rate, multiplied by
    the contracted `term_months`."
    PRD §3.4: "The projection assumes the full contracted term is served,
    assumes no permit fee because no application exists yet, and assumes no
    damage and no relocation."

    Design: Difficulty/dual_variant_calc/lease_charge_total_quoted_projection_vs_settled_actual
    """
    ctx = setup_dallas_lease()
    lease = get_lease(ctx["lease"]["id"])
    assert_lease(lease)

    assert lease["monthly_base_rate_cents"] == DALLAS["MONTHLY_BASE_RATE_CENTS"], (
        f"Expected 151435, got {lease['monthly_base_rate_cents']}")
    assert lease["monthly_accessory_rate_cents"] == DALLAS["ACCESSORY_RATE_CENTS"], (
        f"Expected 101600, got {lease['monthly_accessory_rate_cents']}")
    assert lease["mobilization_fee_cents"] == DALLAS["MOBILIZATION_FEE_CENTS"], (
        f"Expected 631750, got {lease['mobilization_fee_cents']}")
    assert lease["quoted_total_cents"] == DALLAS["QUOTED_TOTAL_CENTS"], (
        f"Expected 631750 + (151435 + 101600) * 12 = 3668170, got "
        f"{lease['quoted_total_cents']}")
    assert lease["final_settlement_cents"] is None, (
        "the settled figure does not exist until the damage is finalized")
    assert lease["relocation_surcharge_cents"] == 0


def test_settled_actual_replaces_the_projection_at_finalization(api):
    """PRD §3.9: "The billable month count is the actual occupied day count —
    from `start_date` through `actual_vacated_date`, both ends included —
    divided by thirty and rounded up to a whole number, and the rent component
    is the combined monthly rent multiplied by that count."
    PRD §3.9: "The sum of mobilization fee, permit fee, rent, adjustment,
    relocation surcharge and damage chargeback is the final settlement."
    PRD §3.9: "The lease's `billed_to_date_cents` is then set equal to
    `final_settlement_cents`; because that changed, the customer's
    `outstanding_balance_cents` is recomputed; because the balance changed,
    `credit_hold` is recomputed; and if and only if the hold flipped from false
    to true, the customer's `credit_tier` is demoted to `WATCH`."


    PRD §3.9: "An adjustment then reconciles the actual tenancy against the
    contract: when the billable month count is **fewer** than the contracted
    `term_months`, an early-termination charge equal to thirty-five percent of
    the combined monthly rent for each unserved month is added, rounded half up
    to a whole cent; when the billable month count is **greater** than
    `term_months`, a holdover charge equal to twenty-five percent of the
    combined monthly rent for each excess month is added, likewise rounded half
    up; and when the two counts are equal the adjustment is zero."
    PRD §3.9: "To that are added the lease's `mobilization_fee_cents`; the
    `permit_fee_cents` of the permit application on this lease if one reached
    `APPROVED`, and nothing if none did; the lease's accumulated
    `relocation_surcharge_cents`; and the `chargeable_cents` of the finalized
    assessment on this lease."

    Design: Difficulty/dual_variant_calc/lease_charge_total_quoted_projection_vs_settled_actual
    """
    ctx = setup_dallas_submitted_assessment()
    quoted = get_lease(ctx["lease"]["id"])["quoted_total_cents"]
    assert quoted == DALLAS["QUOTED_TOTAL_CENTS"]

    validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "C"},
        make_fleet_admin_headers()))

    lease = get_lease(ctx["lease"]["id"])
    assert lease["actual_vacated_date"] == DALLAS["VACATE_DATE"], (
        f"Expected the clock's 2027-06-15 stamped, got "
        f"{lease['actual_vacated_date']}")
    assert lease["billing_status"] == "SETTLED", (
        f"Expected SETTLED, got {lease['billing_status']}")
    assert lease["final_settlement_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_CENTS"]), (
        f"Expected 631750 mobilization + 167500 permit + 2530350 rent + 177125 "
        f"early-termination + 358250 damage = 3864975, got "
        f"{lease['final_settlement_cents']}")
    assert lease["final_settlement_cents"] - quoted == 196_805, (
        f"the two variants must differ by 196805 on the same lease row, got "
        f"{lease['final_settlement_cents'] - quoted}")
    assert lease["billed_to_date_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_CENTS"]), (
        f"Expected billed_to_date to follow the settlement, got "
        f"{lease['billed_to_date_cents']}")


# ─── Damage chargeback: provisional versus finalized net ─────────────────────

def test_provisional_gross_charges_every_line_at_full_repair_cost(api):
    """PRD §3.9: "Each line's own `repair_cost_cents` is derived immediately as
    the component's base cost multiplied by the severity factor multiplied by
    the quantity, rounded half up to a whole cent."
    PRD §3.9: "Submitting the assessment moves it `DRAFT → SUBMITTED`, and
    re-submitting after a dispute moves it `DISPUTED → SUBMITTED`; in both cases
    the system recomputes `gross_damage_cents` from the current line-item set as
    the sum of every line's `repair_cost_cents`, walked in ascending order of
    the lines' creation timestamps."
    PRD §3.9: "Wear-and-tear lines are fully included in this provisional figure
    and no cap of any kind is applied — this is the inspector's unmitigated view
    of the damage."

    Design: Difficulty/dual_variant_calc/damage_chargeback_provisional_vs_finalized_net
    """
    ctx = setup_dallas_draft_assessment()
    floor_line, wall_line, hvac_line = ctx["line_items"]

    assert floor_line["repair_cost_cents"] == (
        DALLAS_DAMAGE["FLOOR_MODERATE_1_CENTS"]), (
        f"Expected 32000 * 1.00 * 1 = 32000, got "
        f"{floor_line['repair_cost_cents']}")
    assert wall_line["repair_cost_cents"] == DALLAS_DAMAGE["WALL_MINOR_3_CENTS"], (
        f"Expected 18000 * 0.35 * 3 = 18900, got {wall_line['repair_cost_cents']}")
    assert hvac_line["repair_cost_cents"] == DALLAS_DAMAGE["HVAC_SEVERE_1_CENTS"], (
        f"Expected 145000 * 2.25 * 1 = 326250, got "
        f"{hvac_line['repair_cost_cents']}")

    submitted = submit_assessment(ctx["assessment"]["id"])
    assert_damage_assessment(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["gross_damage_cents"] == DALLAS_DAMAGE["GROSS_CENTS"], (
        f"Expected all three lines at full cost = 377150, including the "
        f"wear-and-tear line; got {submitted['gross_damage_cents']}")


def test_finalized_net_deducts_the_wear_allowance_from_the_provisional_gross(api):
    """PRD §3.9: "The `wear_allowance_cents` recorded on the assessment is the
    smaller of the wear-line total and that cap."
    PRD §3.9: "Third it subtracts the allowance from `gross_damage_cents`, with
    the result held at zero if the allowance exceeds the gross. Fourth it clips
    the remainder at forty percent of the model's `replacement_value_cents`,
    rounded half up to a whole cent, and stores the smaller of the two as
    `chargeable_cents`."
    PRD §3.9: "On creation the system stamps `assessor_user_id` with the
    inspector's `X-User-ID` — the handle that later blocks that same operator
    from authorizing the resulting spend — and copies the unit's present
    `condition_grade` into the assessment's `condition_grade_before`, freezing
    the "as returned" grade before any repair is contemplated."


    PRD §3.9: "First it totals the repair cost of the line items whose
    `wear_and_tear` flag is true."
    PRD §3.9: "Second it caps that total by a tenancy-length allowance: count
    the days the building was actually occupied, from the lease's `start_date`
    through its `actual_vacated_date` with both ends included; divide that day
    count by thirty and round the quotient up to a whole number of months;
    multiply the model's `replacement_value_cents` by one quarter of one percent
    per month of that count; and round the result half up to a whole cent."

    Design: Difficulty/dual_variant_calc/damage_chargeback_provisional_vs_finalized_net
    """
    ctx = setup_dallas_submitted_assessment()
    assert ctx["assessment"]["gross_damage_cents"] == DALLAS_DAMAGE["GROSS_CENTS"]

    finalized = validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "C"},
        make_fleet_admin_headers()))
    assert_damage_assessment(finalized)

    assert finalized["wear_allowance_cents"] == (
        DALLAS_DAMAGE["WEAR_ALLOWANCE_CENTS"]), (
        f"the 18900 wear line is well under the 237500 tenancy cap, so the "
        f"allowance is 18900; got {finalized['wear_allowance_cents']}")
    assert finalized["chargeable_cents"] == DALLAS_DAMAGE["CHARGEABLE_CENTS"], (
        f"Expected 377150 - 18900 = 358250, well under the 3800000 clip; got "
        f"{finalized['chargeable_cents']}")
    assert (finalized["gross_damage_cents"] - finalized["wear_allowance_cents"]
            == finalized["chargeable_cents"]), (
        "the finalized net must be the gross less the allowance here")
    assert finalized["condition_grade_before"] == "A", (
        f"the as-returned grade was frozen at creation, got "
        f"{finalized['condition_grade_before']}")
    assert finalized["condition_grade_after"] == "C", (
        f"Expected the supplied grade C, got {finalized['condition_grade_after']}")


# ─── Finalization cascade: settlement -> exposure -> tier demotion ───────────

def test_finalization_settles_the_lease_and_recomputes_customer_exposure(api):
    """PRD §3.9: "Because the chargeable amount has become final, the lease's
    billing axis moves `ACCRUING → SETTLED` and its `final_settlement_cents` is
    computed as the actual, chronological accounting of the tenancy — as
    distinct from the forward projection made at quote time."
    PRD §2.11: "A customer's `outstanding_balance_cents` is not a stored running
    total that gets nudged; it is recomputed as the sum, over every lease
    belonging to that customer, of that lease's `billed_to_date_cents` minus its
    `credited_cents`, with the leases processed in ascending order of their
    creation timestamp."

    Design: Difficulty/transitive_cascade/assessment_finalization_cascades_settlement_then_exposure_then_tier_demotion
    """
    ctx = setup_dallas_submitted_assessment(
        customer_overrides={"credit_limit_cents": 900_000})

    before = get_customer(ctx["customer"]["id"])
    assert before["outstanding_balance_cents"] == (
        DALLAS["ACTIVATION_CHARGE_CENTS"]), (
        f"Expected the activation charge of 884785 outstanding, got "
        f"{before['outstanding_balance_cents']}")
    assert before["credit_hold"] is False, "884785 is under the 900000 limit"

    finalized = validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "C"},
        make_fleet_admin_headers()))
    assert finalized["status"] == "FINALIZED"
    assert finalized["chargeable_cents"] == DALLAS_DAMAGE["CHARGEABLE_CENTS"]

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billing_status"] == "SETTLED", (
        f"Expected SETTLED, got {lease['billing_status']}")
    assert lease["final_settlement_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_CENTS"])
    assert lease["billed_to_date_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_CENTS"])

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_CENTS"]), (
        f"Expected the recomputed exposure to be 3864975, got "
        f"{customer['outstanding_balance_cents']}")
    assert_exposure_matches_leases(customer, [lease])


def test_credit_hold_flip_demotes_the_tier_without_re_rating_the_lease(api):
    """PRD §2.11: "One consequence of the hold deserves its own sentence,
    because it is permanent in a way the balance is not: when a recomputation
    flips `credit_hold` from false to true as part of lease settlement, the
    customer's `credit_tier` is demoted to `WATCH`."
    PRD §2.11: "A demotion never re-rates leases that already exist, because
    each lease priced itself against a snapshot of the tier taken when it was
    created."
    PRD §3.4: "When the customer passes, the system snapshots the lessee's
    current `credit_tier` into the lease's own `pinned_credit_tier`."

    Design: Difficulty/transitive_cascade/assessment_finalization_cascades_settlement_then_exposure_then_tier_demotion
    """
    ctx = setup_dallas_submitted_assessment(
        customer_overrides={"credit_limit_cents": 900_000})
    assert get_customer(ctx["customer"]["id"])["credit_tier"] == "GOLD"

    validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "C"},
        make_fleet_admin_headers()))

    customer = get_customer(ctx["customer"]["id"])
    assert customer["credit_hold"] is True, (
        f"3864975 is strictly over the 900000 limit, so the hold must flip on; "
        f"got {customer['credit_hold']}")
    assert customer["credit_tier"] == "WATCH", (
        f"the false-to-true flip demotes the tier, got {customer['credit_tier']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["pinned_credit_tier"] == "GOLD", (
        f"the demotion must not rewrite the lease's pinned tier, got "
        f"{lease['pinned_credit_tier']}")
    assert lease["monthly_base_rate_cents"] == DALLAS["MONTHLY_BASE_RATE_CENTS"], (
        f"the demotion must not re-rate an existing lease, got "
        f"{lease['monthly_base_rate_cents']}")


# ─── Boundary: an assessment with no line items ──────────────────────────────

def test_assessment_with_no_line_items_finalizes_at_zero(api):
    """PRD §3.9: "An assessment with no lines yields zero."
    PRD §3.9: "For an identical set of line items the finalized figure is
    therefore never greater than the provisional one, and an assessment with no
    lines finalizes at zero across the board."
    PRD §3.9: "A fresh assessment begins at `DRAFT` with `dispute_rounds` at 0,
    with `gross_damage_cents`, `wear_allowance_cents` and `chargeable_cents` all
    at 0, and with `condition_grade_after` and `dispute_reason` both null."

    Design: Difficulty/boundary_precision_check/empty_line_item_set_finalizes_to_zero_chargeback
    """
    ctx = setup_dallas_submitted_assessment(lines=[])

    _, meta = validate_paginated(api.list_damage_line_items(
        ctx["assessment"]["id"], make_damage_assessor_headers()))
    assert meta["total_count"] == 0, (
        f"the assessment carries no lines, got {meta['total_count']}")
    assert ctx["assessment"]["gross_damage_cents"] == 0, (
        f"an empty line set submits at zero, got "
        f"{ctx['assessment']['gross_damage_cents']}")

    finalized = validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "A"},
        make_fleet_admin_headers()))
    assert finalized["status"] == "FINALIZED"
    assert finalized["gross_damage_cents"] == 0
    assert finalized["wear_allowance_cents"] == 0, (
        f"there is no wear line to allow for, got "
        f"{finalized['wear_allowance_cents']}")
    assert finalized["chargeable_cents"] == 0, (
        f"Expected a zero chargeback, got {finalized['chargeable_cents']}")


def test_settlement_without_damage_still_includes_the_approved_permit_fee(api):
    """PRD §3.9: "To that are added the lease's `mobilization_fee_cents`; the
    `permit_fee_cents` of the permit application on this lease if one reached
    `APPROVED`, and nothing if none did; the lease's accumulated
    `relocation_surcharge_cents`; and the `chargeable_cents` of the finalized
    assessment on this lease."
    PRD §3.9: "An adjustment then reconciles the actual tenancy against the
    contract: when the billable month count is **fewer** than the contracted
    `term_months`, an early-termination charge equal to thirty-five percent of
    the combined monthly rent for each unserved month is added, rounded half up
    to a whole cent; when the billable month count is **greater** than
    `term_months`, a holdover charge equal to twenty-five percent of the
    combined monthly rent for each excess month is added, likewise rounded half
    up; and when the two counts are equal the adjustment is zero."

    Design: Difficulty/boundary_precision_check/empty_line_item_set_finalizes_to_zero_chargeback
    """
    ctx = setup_dallas_submitted_assessment(lines=[])
    assert ctx["permit"]["permit_fee_cents"] == DALLAS["PERMIT_FEE_CENTS"], (
        f"Expected 145000 + 15 blocks * 1500 = 167500, got "
        f"{ctx['permit']['permit_fee_cents']}")

    validate_success(api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "A"},
        make_fleet_admin_headers()))

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billing_status"] == "SETTLED"
    assert lease["final_settlement_cents"] == (
        DALLAS_DAMAGE["FINAL_SETTLEMENT_WITHOUT_DAMAGE_CENTS"]), (
        f"Expected the full settlement less the 358250 damage leg = 3506725, "
        f"got {lease['final_settlement_cents']}")


# ─── Corner coverage ─────────────────────────────────────────────────────────

def test_damage_line_items_are_append_only_with_no_version(api):
    """PRD §2.4: "Damage line items are the one exception. A `DamageLineItem` is
    an append-only audit record: it is never edited after it is written, so it
    carries only `id` and `created_at`. It has no `updated_at` field and no
    `version` field, and neither appears in its representation."
    PRD §3.9: "Each line's own `repair_cost_cents` is derived immediately as the
    component's base cost multiplied by the severity factor multiplied by the
    quantity, rounded half up to a whole cent."
    PRD §2.3: "Unless a specific endpoint says otherwise, every list is returned
    sorted by the resource's creation timestamp in ascending order — oldest
    first."

    Design: Corner/entities/damage_line_item_is_immutable_append_only_with_no_version
    """
    ctx = setup_rural_draft_assessment(lines=[
        ("DOOR", "MINOR", 2, False),
        ("ROOF", "MODERATE", 1, False),
    ])
    door_line, roof_line = ctx["line_items"]

    assert_damage_line_item(door_line)
    assert_damage_line_item(roof_line)
    assert door_line["repair_cost_cents"] == 28_700, (
        f"Expected 41000 * 0.35 * 2 = 28700, got {door_line['repair_cost_cents']}")
    assert roof_line["repair_cost_cents"] == 96_000, (
        f"Expected 96000 * 1.00 * 1 = 96000, got {roof_line['repair_cost_cents']}")

    rows, meta = validate_paginated(api.list_damage_line_items(
        ctx["assessment"]["id"], make_damage_assessor_headers()))
    assert meta["total_count"] == 2, (
        f"Expected the two appended lines, got {meta['total_count']}")
    assert [row["component"] for row in rows] == ["DOOR", "ROOF"], (
        f"the log must be returned oldest first, got "
        f"{[row['component'] for row in rows]}")
    for row in rows:
        assert "version" not in row, "a damage line item carries no version"
        assert "updated_at" not in row, "a damage line item carries no updated_at"


def test_the_dispute_cycle_stops_at_the_second_round(api):
    """PRD §3.9: "A `Customer` whose `X-User-ID` matches the `customer_id` of
    the lease behind the assessment may push a `SUBMITTED` assessment back with
    a mandatory `dispute_reason`, moving it `SUBMITTED → DISPUTED` and
    incrementing `dispute_rounds` by one."
    PRD §3.9: "The lessee gets two such rounds and no more: a dispute attempted
    when `dispute_rounds` has already reached 2 is refused with
    `ERR_DISPUTE_LIMIT_REACHED`."
    PRD §3.9: "The cycle `SUBMITTED → DISPUTED → SUBMITTED` may therefore run
    twice before the assessment can only go forward."

    Design: Corner/state_machines/assessment_dispute_cycle_stops_at_the_second_round
    """
    ctx = setup_rural_submitted_assessment()
    customer_id = ctx["customer"]["id"]

    first = dispute_assessment(ctx["assessment"]["id"], customer_id,
                               "HVAC was already noisy at delivery")
    assert first["status"] == "DISPUTED", (
        f"Expected DISPUTED, got {first['status']}")
    assert first["dispute_rounds"] == 1
    resubmitted = submit_assessment(ctx["assessment"]["id"])
    assert resubmitted["status"] == "SUBMITTED"

    second = dispute_assessment(ctx["assessment"]["id"], customer_id,
                                "Still disagree")
    assert second["dispute_rounds"] == 2
    submit_assessment(ctx["assessment"]["id"])

    third = api.dispute_damage_assessment(
        ctx["assessment"]["id"], {"dispute_reason": "Third try"},
        make_customer_headers(customer_id))
    validate_error(third, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value)

    assessment = get_assessment(ctx["assessment"]["id"])
    assert assessment["dispute_rounds"] == 2, (
        f"the refused dispute must not count, got {assessment['dispute_rounds']}")
    assert assessment["status"] == "SUBMITTED", (
        f"the assessment stays SUBMITTED, got {assessment['status']}")
    assert assessment["gross_damage_cents"] == RURAL_DAMAGE["GROSS_CENTS"], (
        f"Expected the single HVAC line at 145000, got "
        f"{assessment['gross_damage_cents']}")
    assert get_lease(ctx["lease"]["id"])["billing_status"] == "ACCRUING", (
        "settlement still waits on finalization")


def test_wear_allowance_is_capped_by_the_months_on_lease(api):
    """PRD §3.9: "Second it caps that total by a tenancy-length allowance: count
    the days the building was actually occupied, from the lease's `start_date`
    through its `actual_vacated_date` with both ends included; divide that day
    count by thirty and round the quotient up to a whole number of months;
    multiply the model's `replacement_value_cents` by one quarter of one percent
    per month of that count; and round the result half up to a whole cent."
    PRD §3.9: "The `wear_allowance_cents` recorded on the assessment is the
    smaller of the wear-line total and that cap."
    PRD §3.9: "The sum of mobilization fee, permit fee, rent, adjustment,
    relocation surcharge and damage chargeback is the final settlement."

    Design: Corner/calculations/damage_wear_allowance_is_capped_by_months_on_lease
    """
    ctx = setup_rural_submitted_assessment()

    finalized = finalize_assessment(ctx["assessment"]["id"], "B")
    assert finalized["gross_damage_cents"] == RURAL_DAMAGE["GROSS_CENTS"], (
        f"Expected the HVAC line at 145000, got "
        f"{finalized['gross_damage_cents']}")
    assert finalized["wear_allowance_cents"] == (
        RURAL_DAMAGE["WEAR_ALLOWANCE_CENTS"]), (
        f"one month on lease caps the allowance at 6200000 * 0.0025 = 15500, "
        f"got {finalized['wear_allowance_cents']}")
    assert finalized["chargeable_cents"] == RURAL_DAMAGE["CHARGEABLE_CENTS"], (
        f"Expected 145000 - 15500 = 129500, got {finalized['chargeable_cents']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["actual_vacated_date"] == "2026-10-20"
    assert lease["billing_status"] == "SETTLED"
    assert lease["final_settlement_cents"] == (
        RURAL_DAMAGE["FINAL_SETTLEMENT_CENTS"]), (
        f"Expected 351500 + 127065 + 489200 + 129500 = 1097265, got "
        f"{lease['final_settlement_cents']}")
    assert get_customer(ctx["customer"]["id"])["outstanding_balance_cents"] == (
        RURAL_DAMAGE["FINAL_SETTLEMENT_CENTS"])


def test_finalizing_a_draft_assessment_is_refused(api):
    """PRD §3.9: "It is a `FleetAdmin` act, permitted only on a `SUBMITTED`
    assessment — anything else is refused with `ERR_ASSESSMENT_NOT_SUBMITTED` —
    and only once the lease's occupancy axis has reached `VACATED`."
    PRD §3.9: "A fresh assessment begins at `DRAFT` with `dispute_rounds` at 0,
    with `gross_damage_cents`, `wear_allowance_cents` and `chargeable_cents` all
    at 0, and with `condition_grade_after` and `dispute_reason` both null."

    Design: Corner/errors/finalize_a_draft_assessment_returns_assessment_not_submitted
    """
    ctx = setup_rural_draft_assessment()
    assert ctx["assessment"]["status"] == "DRAFT"

    response = api.finalize_damage_assessment(
        ctx["assessment"]["id"], {"condition_grade_after": "B"},
        make_fleet_admin_headers())
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTED.value)

    assessment = get_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "DRAFT", (
        f"the refused finalization must leave the assessment in DRAFT, got "
        f"{assessment['status']}")
    assert assessment["gross_damage_cents"] == 0, (
        f"the provisional gross is only computed on submit, got "
        f"{assessment['gross_damage_cents']}")
    assert assessment["chargeable_cents"] == 0

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billing_status"] == "ACCRUING", (
        f"no settlement may cascade, got {lease['billing_status']}")
    assert lease["final_settlement_cents"] is None
