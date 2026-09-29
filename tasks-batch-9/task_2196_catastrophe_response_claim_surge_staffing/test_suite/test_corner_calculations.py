"""Queue B — Corner design index, section: calculations.

One test per non-stub `calculations` instance of SCAFFOLD_CORNER_DESIGN.yaml:
boundary values of the posture bands, the clamp-before-round and round-half-up
edges of the two scores, the two opposite rounding orders, and the selector
tie-breaks. Every test carries exactly one design tag naming the instance it
translates.
"""
from test_helpers import validate_success, validate_paginated
from test_helpers.assertions import (
    assert_adjuster,
    assert_claim,
    assert_deployment,
    assert_loss_estimate_snapshot,
    assert_money_equals,
    assert_vendor_assignment,
)
from test_helpers.test_users import (
    make_adjuster_headers,
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CO = make_compliance_officer_headers("co_1")


def _hurricane_event(api, cat_code, **overrides):
    """A DECLARED HURRICANE/FL event at expected_severity_index 0.0400."""
    payload = {
        "cat_code": cat_code,
        "peril_type": "HURRICANE",
        "jurisdiction_state": "FL",
        "event_start_utc": "2026-07-30T00:00:00.000Z",
        "exposure_count": 1000,
        "avg_insured_value": 250000,
        "expected_severity_index": 0.0400,
    }
    payload.update(overrides)
    event = validate_success(api.create_event(payload, CM), 201)
    return validate_success(api.declare_event(event["id"], CM))


def _dwelling_claim(api, event_id, policy_number, **overrides):
    """An INTAKE claim with a single ACCESSIBLE DWELLING coverage line."""
    payload = {
        "policy_number": policy_number,
        "loss_state": "FL",
        "loss_date_utc": "2026-07-30T00:00:00.000Z",
        "reported_loss_amount": 120000,
        "coverage_lines": [
            {
                "coverage_code": "DWELLING",
                "limit_amount": 400000,
                "deductible_amount": 5000,
                "estimated_damage_amount": 150000,
            }
        ],
        "event_id": event_id,
        "access_status": "ACCESSIBLE",
    }
    payload.update(overrides)
    return validate_success(api.create_claim(payload, CE), 201)


def _snapshot(api, event_id, method="EXPOSURE_BASED"):
    """Mint a snapshot against the event's current version."""
    event = validate_success(api.get_event(event_id, CM))
    return validate_success(
        api.create_loss_estimate(
            {
                "event_id": event_id,
                "method": method,
                "expected_event_version": event["version"],
            },
            CM,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Instance — corner_calc_event_posture_restricted_at_strain_exactly_three
# ---------------------------------------------------------------------------
def test_posture_bands_restricted_at_strain_exactly_three(api):
    """PRD §2.9: "The second term contributes 3 when the event's latest
    loss-estimate snapshot is stale, and 0 otherwise; the latest snapshot is the
    one with the greatest `computed_at_utc`, and if several share that instant,
    the one with the earliest `created_at` wins."
    PRD §2.9: "The strain total is the count of unassigned severe claims plus the
    stale contribution plus the moratorium contribution, and it is an exact
    integer that is never rounded."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but
    below 8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."
    PRD §2.9: "Both boundaries are inclusive on their lower edge."
    PRD §3.8: "Its `stale` flag is a computed property re-evaluated on every read:
    it reads true exactly when a ledger entry exists on the event whose
    `sequence_no` is greater than the snapshot's recorded high-water mark."

    Design: Corner/calculations/corner_calc_event_posture_restricted_at_strain_exactly_three
    """
    event = _hurricane_event(api, "CAT-2026-201")
    snapshot = _snapshot(api, event["id"])
    claim = _dwelling_claim(api, event["id"], "POL-201")

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    assert_claim(triaged)
    # base 30.00 * 1.15 = 34.50; +0 ACCESSIBLE; +0 ALE; +0.80 index term.
    assert_money_equals(triaged["severity_score"], 35.30, "severity_score")
    assert triaged["triage_tier"] == "STANDARD"
    assert_money_equals(triaged["case_reserve"], 65250.00, "case_reserve")

    refreshed_snapshot = validate_success(api.get_loss_estimate(snapshot["id"], CM))
    assert_loss_estimate_snapshot(refreshed_snapshot)
    assert refreshed_snapshot["input_reserve_sequence_high_water"] == 0
    assert refreshed_snapshot["stale"] is True

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    # A STANDARD claim is not severe, so strain is 0 + 3 (stale) + 0 = exactly 3.
    assert refreshed_event["posture"] == "RESTRICTED"
    assert refreshed_event["status"] == "DECLARED"
    assert_money_equals(refreshed_event["incurred_total"], 65250.00, "incurred_total")


# ---------------------------------------------------------------------------
# Instance — corner_calc_event_posture_frozen_at_strain_exactly_eight
# ---------------------------------------------------------------------------
def test_posture_bands_frozen_at_strain_exactly_eight(api):
    """PRD §2.9: "The first term is the number of claims belonging to the event
    whose `triage_tier` is either `COMPLEX` or `CAT_SEVERE` and whose
    `handling_status` is either `TRIAGED` or `REOPENED` — in other words, severe
    claims that have been triaged but have no live inspection work."
    PRD §2.9: "The third term contributes 4 when the event's `moratorium_active`
    flag is true, and 0 otherwise."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but
    below 8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."
    PRD §2.9: "Both boundaries are inclusive on their lower edge."
    PRD §2.9: "**Step four takes the stricter of the floor and the band** as the
    event's `posture`, so a `DEMOBILIZING` event whose strain bands `OPEN` still
    reads `RESTRICTED`, and any event whose strain reaches 8 reads `FROZEN` even
    while `SURGE_ACTIVE`."

    Design: Corner/calculations/corner_calc_event_posture_frozen_at_strain_exactly_eight
    """
    event = _hurricane_event(api, "CAT-2026-202")
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-M1",
                "bulletin_type": "CANCELLATION_MORATORIUM",
                "jurisdiction_state": "FL",
                "effective_from": "2026-08-01T00:00:00.000Z",
                "effective_to": "2026-12-01T00:00:00.000Z",
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))
    _snapshot(api, event["id"])
    claim = _dwelling_claim(
        api,
        event["id"],
        "POL-202",
        reported_loss_amount=180000,
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 400000,
                "deductible_amount": 5000,
                "estimated_damage_amount": 300000,
            }
        ],
    )

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    # base 45.00 * 1.15 = 51.75; +0.80 index term -> COMPLEX, so a severe claim
    # sitting in TRIAGED contributes 1.
    assert_money_equals(triaged["severity_score"], 52.55, "severity_score")
    assert triaged["triage_tier"] == "COMPLEX"
    assert triaged["handling_status"] == "TRIAGED"
    assert_money_equals(triaged["case_reserve"], 191750.00, "case_reserve")

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["moratorium_active"] is True
    assert refreshed_event["status"] == "DECLARED"
    # strain = 1 severe + 3 stale + 4 moratorium = exactly 8 -> FROZEN.
    assert refreshed_event["posture"] == "FROZEN"


# ---------------------------------------------------------------------------
# Instance — corner_calc_event_posture_only_latest_snapshot_stale_flag_counts
# ---------------------------------------------------------------------------
def test_posture_stale_term_reads_only_the_latest_snapshot(api):
    """PRD §2.9: "The second term contributes 3 when the event's latest
    loss-estimate snapshot is stale, and 0 otherwise; the latest snapshot is the
    one with the greatest `computed_at_utc`, and if several share that instant,
    the one with the earliest `created_at` wins."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but
    below 8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."
    PRD §3.8: "Each snapshot records `input_reserve_sequence_high_water`, the
    greatest ledger `sequence_no` on the event at snapshot time, or 0 when the
    event had no entries, and `computed_at_utc` at the current logical-clock
    instant, and is born non-stale."
    PRD §3.8: "The `ibnr_component` is that modelled figure less the
    `reported_component`, floored at 0.00 and rounded to 2 decimal places."

    Design: Corner/calculations/corner_calc_event_posture_only_latest_snapshot_stale_flag_counts
    """
    event = _hurricane_event(api, "CAT-2026-203")
    claim = _dwelling_claim(api, event["id"], "POL-203")
    validate_success(api.triage_claim(claim["id"], CE))
    snapshot_a = _snapshot(api, event["id"])
    assert snapshot_a["input_reserve_sequence_high_water"] == 1

    claim_now = validate_success(api.get_claim(claim["id"], CE))
    validate_success(
        api.create_reserve_entry(
            claim["id"],
            {
                "entry_type": "REVISION",
                "delta_case_reserve": 100.00,
                "delta_paid": 0,
                "expected_claim_version": claim_now["version"],
            },
            CE,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-02T00:00:00.000Z", CM))

    snapshot_b = _snapshot(api, event["id"])

    assert_loss_estimate_snapshot(snapshot_b)
    assert snapshot_b["input_reserve_sequence_high_water"] == 2
    assert snapshot_b["stale"] is False
    assert snapshot_b["computed_at_utc"] == "2026-08-02T00:00:00.000Z"
    assert_money_equals(snapshot_b["reported_component"], 65350.00, "reported_component")
    # 1000 * 250000 * 0.0400 * 1.40 = 14000000.00 modelled ultimate.
    assert_money_equals(snapshot_b["ibnr_component"], 13934650.00, "ibnr_component")
    assert_money_equals(snapshot_b["gross_estimate"], 14000000.00, "gross_estimate")

    stale_a = validate_success(api.get_loss_estimate(snapshot_a["id"], CM))
    assert stale_a["stale"] is True

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    # The older snapshot is still stale, but only the latest one is consulted.
    assert refreshed_event["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Instance — corner_calc_claim_severity_round_half_up_at_exact_half_cent
# ---------------------------------------------------------------------------
def test_severity_rounds_half_up_at_an_exact_half_cent(api):
    """PRD §3.6: "Start from the claim's exposure: sum `limit_amount` across every
    coverage line, divide the `reported_loss_amount` by that total (or by 1 if the
    total is smaller than 1, which protects the division), cap the resulting ratio
    at 1, and multiply by 100 to get the base."
    PRD §3.6: "Clamp the result so it is not below 0 and not above 100, and only
    then round half up to 2 decimal places — a single rounding, applied after the
    clamp."
    PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the
    `reported_loss_amount` is 10000.00 or less, the mode is `DESK` — the boundary
    is inclusive, so a reported loss of exactly 10000.00 resolves to `DESK` while
    10000.01 resolves to `FIELD`."
    PRD §2.7: "Unless a rule states otherwise, every monetary quantity is carried
    and stored to 2 decimal places and every rounding operation rounds half up."

    Design: Corner/calculations/corner_calc_claim_severity_round_half_up_at_exact_half_cent
    """
    event = _hurricane_event(
        api,
        "CAT-2026-204",
        peril_type="WILDFIRE",
        jurisdiction_state="CA",
        expected_severity_index=0.0010,
    )
    claim = _dwelling_claim(
        api,
        event["id"],
        "POL-204",
        loss_state="CA",
        reported_loss_amount=10116,
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 100000,
                "deductible_amount": 1000,
                "estimated_damage_amount": 5000,
            }
        ],
    )

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    # 10.116 * 1.25 = 12.645, + 0.02 = 12.665 exactly -> half up gives 12.67.
    assert_money_equals(triaged["severity_score"], 12.67, "severity_score")
    assert triaged["severity_score"] != 12.66
    assert triaged["triage_tier"] == "FAST_TRACK"
    # Reported loss 10116.00 is above the inclusive 10000.00 DESK boundary.
    assert triaged["inspection_mode"] == "FIELD"
    # basis max(raw eligible 4000.00, reported 10116.00) = 10116.00 * 0.25.
    assert_money_equals(triaged["case_reserve"], 2529.00, "case_reserve")


# ---------------------------------------------------------------------------
# Instance — corner_calc_claim_severity_clamped_to_100_before_rounding
# ---------------------------------------------------------------------------
def test_severity_is_clamped_to_100_before_the_single_rounding(api):
    """PRD §3.6: "Multiply the base by the peril weight of the parent event's
    `peril_type` — 1.15 for `HURRICANE`, 1.25 for `WILDFIRE`, 1.20 for `FLOOD`,
    0.95 for `HAIL`, 0.90 for `WINTER_STORM`, and 1.30 for `EARTHQUAKE`."
    PRD §3.6: "To that product add the access adjustment for the claim's
    `access_status`: nothing for `ACCESSIBLE`, 6 points for `RESTRICTED`, and 12
    points for `INACCESSIBLE`."
    PRD §3.6: "Add a further 10 points when any coverage line has a
    `coverage_code` of `ALE` and an `estimated_damage_amount` greater than zero,
    and nothing otherwise."
    PRD §3.6: "Clamp the result so it is not below 0 and not above 100, and only
    then round half up to 2 decimal places — a single rounding, applied after the
    clamp."
    PRD §3.6: "If the claim's `access_status` is `INACCESSIBLE` and its
    `triage_tier` is `COMPLEX` or `CAT_SEVERE`, the mode is `AERIAL` — a severe
    loss nobody can drive to gets flown."
    PRD §2.7: "Clamping likewise precedes rounding wherever both appear: the claim
    severity score and the adjuster surge-capacity score are both clamped into the
    range from 0 to 100 inclusive *before* the single rounding to 2 decimal
    places, never after."

    Design: Corner/calculations/corner_calc_claim_severity_clamped_to_100_before_rounding
    """
    event = _hurricane_event(
        api,
        "CAT-2026-205",
        peril_type="EARTHQUAKE",
        jurisdiction_state="CA",
        expected_severity_index=1.0000,
    )
    claim = _dwelling_claim(
        api,
        event["id"],
        "POL-205",
        loss_state="CA",
        reported_loss_amount=300000,
        access_status="INACCESSIBLE",
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 200000,
                "deductible_amount": 2000,
                "estimated_damage_amount": 250000,
            },
            {
                "coverage_code": "ALE",
                "limit_amount": 50000,
                "deductible_amount": 0,
                "estimated_damage_amount": 40000,
            },
        ],
    )

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    # ratio 1.2 caps at 1 -> base 100 * 1.30 = 130, +12 +10 +20 = 172 -> clamped.
    assert_money_equals(triaged["severity_score"], 100.00, "severity_score")
    assert triaged["triage_tier"] == "CAT_SEVERE"
    assert triaged["inspection_mode"] == "AERIAL"
    # basis max(raw eligible 198000 + 40000 = 238000.00, reported 300000.00) * 0.85.
    assert_money_equals(triaged["case_reserve"], 255000.00, "case_reserve")

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 255000.00, "case_reserve_total")


# ---------------------------------------------------------------------------
# Instance — corner_calc_initial_case_reserve_basis_is_max_of_reported_and_eligible
# ---------------------------------------------------------------------------
def test_initial_case_reserve_basis_takes_the_greater_of_the_two_candidates(api):
    """PRD §3.6: "First compute the eligible damage of each coverage line as the
    line's `estimated_damage_amount` capped at its `limit_amount`, less its
    `deductible_amount`, with a floor of zero; sum those **raw, unrounded** line
    values; take the greater of that sum and the claim's `reported_loss_amount` as
    the basis; multiply the basis by the tier reserve factor for the claim's
    `triage_tier` — 0.85 for `CAT_SEVERE`, 0.65 for `COMPLEX`, 0.45 for
    `STANDARD`, 0.25 for `FAST_TRACK` — and round half up to 2 decimal places
    **once, at the end**."
    PRD §3.6: "The paid movement of the entry is 0.00."
    PRD §3.6: "Triage stamps `severity_score` and `triage_tier`, stamps
    `inspection_mode`, stamps `deadline_utc`, and appends an `INITIAL_CASE` entry
    to the reserve ledger whose case-reserve movement comes from the
    initial-reserve rule and whose paid movement is exactly 0.00, taking the next
    per-event sequence number."

    Design: Corner/calculations/corner_calc_initial_case_reserve_basis_is_max_of_reported_and_eligible
    """
    event = _hurricane_event(api, "CAT-2026-206")
    claim = _dwelling_claim(
        api,
        event["id"],
        "POL-206",
        reported_loss_amount=180000,
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 400000,
                "deductible_amount": 5000,
                "estimated_damage_amount": 300000,
            }
        ],
    )

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    assert triaged["triage_tier"] == "COMPLEX"
    # eligible 295000.00 beats reported 180000.00, so the eligible sum is the basis.
    assert_money_equals(triaged["case_reserve"], 191750.00, "case_reserve")
    assert_money_equals(triaged["paid_amount"], 0.00, "paid_amount")

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"
    assert rows[0]["sequence_no"] == 1
    assert_money_equals(rows[0]["delta_case_reserve"], 191750.00, "delta_case_reserve")
    assert_money_equals(rows[0]["delta_paid"], 0.00, "delta_paid")

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 191750.00, "case_reserve_total")
    assert_money_equals(refreshed_event["incurred_total"], 191750.00, "incurred_total")


# ---------------------------------------------------------------------------
# Instance — corner_calc_advance_cap_mandate_floor_overrides_tiered_cap
# ---------------------------------------------------------------------------
def test_advance_cap_takes_the_mandate_floor_over_a_smaller_tiered_cap(api):
    """PRD §3.8: "Separately, find the governing advance mandate: among the
    bulletins on the claim's event with `bulletin_type` of
    `ADVANCE_PAYMENT_MANDATE`, `status` of `EFFECTIVE`, and a binding window
    containing the current instant with `effective_from` inclusive and
    `effective_to` exclusive, take the one with the greatest
    `mandated_advance_pct`, breaking ties by the earliest `created_at`; the
    mandate floor is the claim's `reported_loss_amount` multiplied by that
    percentage and rounded to 2 decimal places, or exactly 0.00 when no such
    bulletin exists."
    PRD §3.8: "The claim's `advance_cap` is the greater of that tiered figure and
    the mandate floor."
    PRD §3.8: "Otherwise the issued `amount` is the lesser of the
    `requested_amount` and the headroom."

    Design: Corner/calculations/corner_calc_advance_cap_mandate_floor_overrides_tiered_cap
    """
    event = _hurricane_event(
        api,
        "CAT-2026-207",
        peril_type="HAIL",
        jurisdiction_state="TX",
        expected_severity_index=0.0000,
    )
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "TX-2026-A1",
                "bulletin_type": "ADVANCE_PAYMENT_MANDATE",
                "jurisdiction_state": "TX",
                "effective_from": "2026-08-01T00:00:00.000Z",
                "effective_to": "2026-12-01T00:00:00.000Z",
                "mandated_advance_pct": 0.2500,
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))
    claim = _dwelling_claim(
        api,
        event["id"],
        "POL-207",
        loss_state="TX",
        reported_loss_amount=20000,
        coverage_lines=[
            {
                "coverage_code": "DWELLING",
                "limit_amount": 500000,
                "deductible_amount": 1000,
                "estimated_damage_amount": 10000,
            }
        ],
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["triage_tier"] == "FAST_TRACK"
    assert_money_equals(triaged["case_reserve"], 5000.00, "case_reserve")

    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 6000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    # Tiered cap is 2700.00 * 0.40 = 1080.00; the mandate floor 5000.00 wins.
    assert_money_equals(advance["amount"], 5000.00, "amount")
    assert advance["status"] == "ISSUED"
    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["advance_cap"], 5000.00, "advance_cap")
    assert_money_equals(refreshed["advance_paid_total"], 5000.00, "advance_paid_total")
    assert_money_equals(refreshed["paid_amount"], 5000.00, "paid_amount")
    assert_money_equals(refreshed["case_reserve"], 0.00, "case_reserve")
    assert refreshed["payment_status"] == "ADVANCE_ISSUED"
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["incurred_total"], 5000.00, "incurred_total")


# ---------------------------------------------------------------------------
# Instance — corner_calc_advance_paid_total_excludes_voided_advances
# ---------------------------------------------------------------------------
def test_advance_paid_total_ignores_voided_advances_when_reissuing(api):
    """PRD §3.8: "Only the coverage lines present on the claim at issuance time
    participate, and `advance_paid_total` counts only advances whose `status` is
    `ISSUED`, so a voided advance does not consume cap — which is exactly what
    makes issue-then-void-then-reissue land on the same figure."
    PRD §3.8: "Link two, caused by link one, appends a `REVERSAL` ledger entry
    whose `reverses_entry_id` points at the advance's `reserve_entry_id`, whose
    paid movement is the negation of the issued `amount`, and whose case-reserve
    movement is the positive `amount`, taking the next per-event `sequence_no`;
    the event's `incurred_total` is therefore again unchanged."
    PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED →
    NONE` on the payment axis when `advance_paid_total` returns to exactly 0.00 —
    and `advance_issuing_examiner_user_id` is **retained**, because a void does not
    erase the fact that this user once released money on the file."
    PRD §2.10: "The compensating-action guarantee that follows is exact, not
    approximate: issuing an advance payment on a claim and then voiding that same
    advance leaves the event's `incurred_total`, the claim's `case_reserve` and the
    claim's `paid_amount` each exactly equal to their pre-issuance values."

    Design: Corner/calculations/corner_calc_advance_paid_total_excludes_voided_advances
    """
    event = _hurricane_event(api, "CAT-2026-208")
    claim = _dwelling_claim(api, event["id"], "POL-208")
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert_money_equals(triaged["advance_cap"], 26100.00, "advance_cap")

    first = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 10000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    voided = validate_success(
        api.void_advance_payment(first["id"], {"void_reason": "Issued in error"}, CE)
    )
    assert voided["status"] == "VOIDED"

    second = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 26100, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    # The voided 10000.00 consumed no cap, so the full 26100.00 is still available.
    assert_money_equals(second["amount"], 26100.00, "amount")
    assert second["status"] == "ISSUED"
    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["advance_paid_total"], 26100.00, "advance_paid_total")
    assert_money_equals(refreshed["case_reserve"], 39150.00, "case_reserve")
    assert refreshed["advance_issuing_examiner_user_id"] == "ce_1"

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["incurred_total"], 65250.00, "incurred_total")

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 4
    assert [row["entry_type"] for row in rows] == [
        "INITIAL_CASE",
        "PAYMENT",
        "REVERSAL",
        "PAYMENT",
    ]


def _staff_adjuster(api, full_name, **overrides):
    """A registered STAFF adjuster licensed in FL with a long-dated licence."""
    payload = {
        "full_name": full_name,
        "employment_type": "STAFF",
        "home_state": "FL",
        "licensed_states": ["FL"],
        "license_expiry_utc": "2027-06-30T00:00:00.000Z",
        "max_open_claims": 10,
        "daily_rate": 900,
        "per_diem_rate": 150,
        "desk_certified": False,
        "aerial_certified": False,
    }
    payload.update(overrides)
    return validate_success(api.create_adjuster(payload, DC), 201)


# ---------------------------------------------------------------------------
# Instance — corner_calc_deployment_cost_desk_role_has_zero_housing_share
# ---------------------------------------------------------------------------
def test_desk_deployment_prices_with_a_zero_housing_share(api):
    """PRD §3.5: "Step three computes the two remaining direct costs: per-diem is
    the adjuster's `per_diem_rate` multiplied by the nights and by a per-diem
    eligibility flag of 1 or 0, rounded to 2 decimal places; and the housing share
    is the block's `nightly_rate` multiplied by the deployment's `rooms_reserved`
    and by the nights, rounded to 2 decimal places, or exactly 0.00 when
    `role_type` is `DESK` or no housing block is named."
    PRD §3.5: "Step four picks the tier **from that subtotal alone, never from the
    post-premium total**, so no iteration is needed and the answer is well-defined
    in a single pass: a subtotal of 20000.00 or more is `TIER_HIGH` at a premium
    rate of 11 percent; a subtotal of 5000.00 or more but below 20000.00 is
    `TIER_MID` at 6 percent; anything below 5000.00 is `TIER_NONE` at zero."
    PRD §3.5: "The created deployment is `REQUESTED`, its `selection_reason`
    records `EXPLICIT_ADJUSTER` when the caller pinned an adjuster and
    `SELECTOR_RANKED` when the server chose, and both `provisional_cost` and
    `final_settled_cost` read 0.00 because a requested deployment has not been
    priced and has drawn no rooms."
    PRD §3.5: "It moves the adjuster `AVAILABLE → DEPLOYED` and recomputes their
    surge-capacity score."

    Design: Corner/calculations/corner_calc_deployment_cost_desk_role_has_zero_housing_share
    """
    event = _hurricane_event(api, "CAT-2026-209")
    adjuster = _staff_adjuster(
        api, "Dana Desk", daily_rate=400, per_diem_rate=100, desk_certified=True
    )
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "rooms_reserved": 0,
            },
            DC,
        ),
        201,
    )
    assert deployment["selection_reason"] == "EXPLICIT_ADJUSTER"

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    assert_deployment(confirmed)
    # labour 400 * 1 * 5 = 2000.00 + per-diem 500.00 + housing 0.00 = 2500.00.
    assert_money_equals(confirmed["provisional_cost"], 2500.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_NONE"
    assert_money_equals(confirmed["final_settled_cost"], 0.00, "final_settled_cost")
    assert confirmed["status"] == "CONFIRMED"

    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["deployment_status"] == "DEPLOYED"
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["surge_adjuster_count"] == 1


# ---------------------------------------------------------------------------
# Instance — corner_calc_deployment_premium_high_floor_inclusive_at_20000
# ---------------------------------------------------------------------------
def test_surge_premium_high_band_floor_is_inclusive_at_20000(api):
    """PRD §3.5: "Step one establishes the number of nights: the whole days from
    the deployment's `window_start_utc` up to but not including a settle-end
    instant, with a floor of 1 night so that a same-day deployment is never free."
    PRD §3.5: "Step two computes labour: the adjuster's `daily_rate` multiplied by
    a rate factor and by the nights, rounded to 2 decimal places, where the rate
    factor is exactly 1 for a `STAFF` adjuster and 1.35 for an `INDEPENDENT` one."
    PRD §3.5: "Step four picks the tier **from that subtotal alone, never from the
    post-premium total**, so no iteration is needed and the answer is well-defined
    in a single pass: a subtotal of 20000.00 or more is `TIER_HIGH` at a premium
    rate of 11 percent; a subtotal of 5000.00 or more but below 20000.00 is
    `TIER_MID` at 6 percent; anything below 5000.00 is `TIER_NONE` at zero."
    PRD §3.5: "The surge premium is the subtotal multiplied by that rate, rounded
    to 2 decimal places, and the total is the rounded sum of subtotal and premium."

    Design: Corner/calculations/corner_calc_deployment_premium_high_floor_inclusive_at_20000
    """
    event = _hurricane_event(api, "CAT-2026-210")
    adjuster = _staff_adjuster(
        api, "Hi Floor", daily_rate=1000, per_diem_rate=0, desk_certified=True
    )
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-21T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "rooms_reserved": 0,
            },
            DC,
        ),
        201,
    )

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    # Subtotal is exactly 20000.00, the inclusive lower edge of TIER_HIGH.
    assert confirmed["surge_premium_tier"] == "TIER_HIGH"
    assert_money_equals(confirmed["provisional_cost"], 22200.00, "provisional_cost")
    assert confirmed["provisional_cost"] != 21200.00
    assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Instance — corner_calc_surge_capacity_expiring_credential_penalty_and_cert_bonus
# ---------------------------------------------------------------------------
def test_surge_score_combines_expiring_penalty_with_the_certification_bonus(api):
    """PRD §3.3: "The **availability term** starts from the adjuster's
    `open_assignment_count` — the number of their inspection assignments currently
    in `SCHEDULED` or `IN_PROGRESS` — divided by their `max_open_claims`; that load
    ratio is capped at 1, subtracted from 1, and multiplied by 100, so an idle
    adjuster contributes 100 points and a fully loaded one contributes zero."
    PRD §3.3: "From that, the **credential penalty** for the adjuster's current
    `credential_status` is subtracted: zero points for `VALID`, 15 points for
    `EXPIRING`, 8 points for `WAIVED`, and 100 points for `EXPIRED`."
    PRD §3.3: "Finally the **certification bonus** is added: 5 points if
    `desk_certified` is true plus a further 5 points if `aerial_certified` is true,
    for a maximum of 10."
    PRD §3.3: "Thirty days before the licence lapses — that is, once the clock
    reaches or passes `license_expiry_utc` less the warning period while still
    being earlier than `license_expiry_utc` — the adjuster moves `VALID →
    EXPIRING` and their score is recomputed with a 15-point credential penalty."
    PRD §3.3: "Deployments in other statuses contribute nothing."

    Design: Corner/calculations/corner_calc_surge_capacity_expiring_credential_penalty_and_cert_bonus
    """
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Ida Expiring",
                "employment_type": "INDEPENDENT",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2026-08-20T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": 900,
                "per_diem_rate": 150,
                "desk_certified": True,
                "aerial_certified": True,
            },
            DC,
        ),
        201,
    )

    assert_adjuster(adjuster)
    # The clock starts inside the 30-day warning window for 2026-08-20.
    assert adjuster["credential_status"] == "EXPIRING"
    assert adjuster["deployment_status"] == "AVAILABLE"
    assert adjuster["open_assignment_count"] == 0
    assert_money_equals(adjuster["cumulative_deployed_hours"], 0.00, "cumulative_deployed_hours")
    # 100 - 15 + 0 fatigue + 10 certification = 95.00.
    assert_money_equals(adjuster["surge_capacity_score"], 95.00, "surge_capacity_score")


# ---------------------------------------------------------------------------
# Instance — corner_calc_surge_capacity_clamped_to_100_before_rounding
# ---------------------------------------------------------------------------
def test_surge_score_is_clamped_to_100_before_rounding(api):
    """PRD §3.3: "Finally the **certification bonus** is added: 5 points if
    `desk_certified` is true plus a further 5 points if `aerial_certified` is true,
    for a maximum of 10."
    PRD §3.3: "The result is clamped so that it is not below 0 and not above 100,
    and only then rounded half up to 2 decimal places into `surge_capacity_score`."
    PRD §2.7: "Clamping likewise precedes rounding wherever both appear: the claim
    severity score and the adjuster surge-capacity score are both clamped into the
    range from 0 to 100 inclusive *before* the single rounding to 2 decimal
    places, never after."

    Design: Corner/calculations/corner_calc_surge_capacity_clamped_to_100_before_rounding
    """
    adjuster = _staff_adjuster(
        api,
        "Cap Ceiling",
        license_expiry_utc="2027-06-30T00:00:00.000Z",
        desk_certified=True,
        aerial_certified=True,
    )

    assert adjuster["credential_status"] == "VALID"
    # 100 availability + 10 certification = 110, clamped to the 100 ceiling.
    assert_money_equals(adjuster["surge_capacity_score"], 100.00, "surge_capacity_score")


# ---------------------------------------------------------------------------
# Instance — corner_calc_surge_capacity_fatigue_penalty_capped_at_thirty
# ---------------------------------------------------------------------------
def test_fatigue_penalty_stops_growing_at_thirty_points(api):
    """PRD §3.3: "Then the **fatigue penalty** is subtracted: the adjuster's
    `cumulative_deployed_hours` divided by 24 and rounded down to a whole number of
    full days, multiplied by 3 points per full day, and capped at 30 points — so
    fatigue stops biting after ten full days of accumulated deployment."
    PRD §3.3: "The `cumulative_deployed_hours` input is itself computed: the sum,
    over the adjuster's deployments whose status is `ON_SITE` or `DEMOBILIZED`, of
    the number of hours from that deployment's `window_start_utc` to its
    `window_end_utc`, to 2 decimal places."
    PRD §3.5: "Check-in recomputes the adjuster's `cumulative_deployed_hours` and,
    with it, their surge-capacity score."
    PRD §3.5: "It adds the deployment's `rooms_reserved` to the block's
    `rooms_occupied` and recomputes `rooms_available`, taking the block `ACTIVE →
    EXHAUSTED` if availability lands on zero."

    Design: Corner/calculations/corner_calc_surge_capacity_fatigue_penalty_capped_at_thirty
    """
    event = _hurricane_event(api, "CAT-2026-211")
    adjuster = _staff_adjuster(api, "Fay Tigue")
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Bay Lodge",
                "city": "Tampa",
                "rooms_total": 40,
                "nightly_rate": 200,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-15T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-12T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(deployment["id"], DC))
    validate_success(api.set_clock("2026-09-01T00:00:00.000Z", CM))

    on_site = validate_success(api.check_in_deployment(deployment["id"], DC))

    assert on_site["status"] == "ON_SITE"
    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    # 11 whole days of window -> 264 hours -> 11 full days * 3 = 33, capped at 30.
    assert_money_equals(
        refreshed_adjuster["cumulative_deployed_hours"], 264.00, "cumulative_deployed_hours"
    )
    assert refreshed_adjuster["credential_status"] == "VALID"
    assert_money_equals(refreshed_adjuster["surge_capacity_score"], 70.00, "surge_capacity_score")
    assert refreshed_adjuster["surge_capacity_score"] != 67.00

    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["rooms_occupied"] == 1
    assert refreshed_block["rooms_available"] == 39


# ---------------------------------------------------------------------------
# Instance — corner_calc_claim_deadline_effective_extensions_sum_draft_contributes_zero
# ---------------------------------------------------------------------------
def test_deadline_sums_effective_extensions_and_ignores_drafts(api):
    """PRD §3.2: "Its anchor is the claim's `reported_at_utc` when the claim has
    never been reopened — that is, when `reopen_count` is zero — and otherwise the
    logical-clock instant stamped by the claim's most recent reopen."
    PRD §3.2: "The base deadline is that anchor advanced by 15 whole days."
    PRD §3.2: "To it the system adds the **sum** of `deadline_extension_days` over
    every bulletin on the claim's event whose `bulletin_type` is
    `CLAIM_DEADLINE_EXTENSION`, whose `status` is `EFFECTIVE`, and whose binding
    window contains the current instant with `effective_from` inclusive and
    `effective_to` exclusive, iterating in `created_at` ascending order."
    PRD §3.2: "Concurrently effective extensions therefore **stack** rather than
    competing: two effective ten-day extensions produce twenty days of relief, not
    ten."
    PRD §3.2: "Bulletins in `DRAFT`, `EXPIRED` or `WITHDRAWN` contribute zero
    days."

    Design: Corner/calculations/corner_calc_claim_deadline_effective_extensions_sum_draft_contributes_zero
    """
    event = _hurricane_event(api, "CAT-2026-212")

    def _extension(number, days):
        return validate_success(
            api.create_bulletin(
                {
                    "event_id": event["id"],
                    "bulletin_number": number,
                    "bulletin_type": "CLAIM_DEADLINE_EXTENSION",
                    "jurisdiction_state": "FL",
                    "effective_from": "2026-08-01T00:00:00.000Z",
                    "effective_to": "2026-12-01T00:00:00.000Z",
                    "deadline_extension_days": days,
                },
                CO,
            ),
            201,
        )

    first = _extension("FL-2026-D1", 10)
    second = _extension("FL-2026-D2", 20)
    draft = _extension("FL-2026-D3", 20)
    validate_success(api.activate_bulletin(first["id"], CO))
    validate_success(api.activate_bulletin(second["id"], CO))
    assert draft["status"] == "DRAFT"

    claim = _dwelling_claim(api, event["id"], "POL-212")
    triaged = validate_success(api.triage_claim(claim["id"], CE))

    assert triaged["reported_at_utc"] == "2026-08-01T00:00:00.000Z"
    # 15 base + 10 + 20 effective days; the DRAFT extension adds nothing.
    assert triaged["deadline_utc"] == "2026-09-15T00:00:00.000Z"
    assert triaged["handling_status"] == "TRIAGED"


# ---------------------------------------------------------------------------
# Instance — corner_calc_reserve_revision_delta_is_negative_when_verified_below_reserve
# ---------------------------------------------------------------------------
def test_inspection_revision_delta_goes_negative_below_the_standing_reserve(api):
    """PRD §3.7: "Sum the `deductible_amount` of every coverage line on the claim."
    PRD §3.7: "Subtract that total from the claim's newly refreshed
    `verified_damage_amount`, floor the result at zero, and round half up to 2
    decimal places to obtain the target case reserve."
    PRD §3.7: "The entry's case-reserve movement is that target less the claim's
    `case_reserve` as it stands immediately before the append, rounded half up to 2
    decimal places — a figure that is frequently **negative**, when an inspection
    verifies less damage than the first notice suggested."
    PRD §3.7: "The entry's paid movement is 0.00."
    PRD §3.7: "Completion stamps `report_submitted_at_utc` at the current logical-clock
    instant, recomputes the adjuster's `open_assignment_count` and
    `surge_capacity_score`, and pushes the claim `INSPECTION_PENDING → INSPECTED`."

    Design: Corner/calculations/corner_calc_reserve_revision_delta_is_negative_when_verified_below_reserve
    """
    event = _hurricane_event(api, "CAT-2026-213")
    adjuster = _staff_adjuster(api, "Ray Verify")
    claim = _dwelling_claim(api, event["id"], "POL-213")
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert_money_equals(triaged["case_reserve"], 65250.00, "case_reserve")

    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-05T00:00:00.000Z",
                "window_end_utc": "2026-08-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-05T00:00:00.000Z", CM))
    adjuster_headers = make_adjuster_headers(adjuster["id"])
    validate_success(api.start_inspection(assignment["id"], adjuster_headers))

    completed = validate_success(
        api.complete_inspection(
            assignment["id"], {"verified_damage_amount": 30000}, adjuster_headers
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["report_submitted_at_utc"] == "2026-08-05T00:00:00.000Z"

    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed["handling_status"] == "INSPECTED"
    assert_money_equals(refreshed["verified_damage_amount"], 30000.00, "verified_damage_amount")
    # target 30000.00 - 5000.00 deductible = 25000.00, from a standing 65250.00.
    assert_money_equals(refreshed["case_reserve"], 25000.00, "case_reserve")

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2
    assert rows[0]["sequence_no"] == 1
    assert_money_equals(rows[0]["delta_case_reserve"], 65250.00, "delta_case_reserve")
    assert rows[1]["sequence_no"] == 2
    assert rows[1]["entry_type"] == "REVISION"
    assert_money_equals(rows[1]["delta_case_reserve"], -40250.00, "delta_case_reserve")
    assert_money_equals(rows[1]["delta_paid"], 0.00, "delta_paid")

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 25000.00, "case_reserve_total")


# ---------------------------------------------------------------------------
# Instance — corner_calc_incurred_development_ultimate_claim_count_uses_ceil
# ---------------------------------------------------------------------------
def test_incurred_development_takes_the_ceiling_of_the_ultimate_claim_count(api):
    """PRD §3.8: "Count the distinct claims among the event's `INITIAL_CASE` ledger
    entries to get the reported claim count."
    PRD §3.8: "Divide the `reported_component` by that count — or by 1 when the
    count is zero — to get the average incurred per reported claim."
    PRD §3.8: "Separately, multiply the event's `exposure_count` by its
    `expected_severity_index` by a report rate of 35 percent and round the product
    **up** to the next whole number to get the ultimate claim count; this ceiling is
    taken on the exact value, never via a floating-point shortcut."
    PRD §3.8: "The `ibnr_component` is the average incurred per claim multiplied by
    the ultimate claim count less the reported claim count (with that difference
    floored at zero), the whole product floored at 0.00 and rounded to 2 decimal
    places."
    PRD §3.8: "Both methods share a common base: the `reported_component` is the
    event's `incurred_total`, that is its `case_reserve_total` plus its `paid_total`."

    Design: Corner/calculations/corner_calc_incurred_development_ultimate_claim_count_uses_ceil
    """
    event = _hurricane_event(api, "CAT-2026-214", exposure_count=1001)
    claim = _dwelling_claim(api, event["id"], "POL-214")
    validate_success(api.triage_claim(claim["id"], CE))

    snapshot = _snapshot(api, event["id"], method="INCURRED_DEVELOPMENT")

    assert_loss_estimate_snapshot(snapshot)
    assert snapshot["method"] == "INCURRED_DEVELOPMENT"
    assert_money_equals(snapshot["reported_component"], 65250.00, "reported_component")
    # 1001 * 0.0400 * 0.35 = 14.014 -> ceiling 15, so 14 unreported claims remain.
    assert_money_equals(snapshot["ibnr_component"], 913500.00, "ibnr_component")
    assert snapshot["ibnr_component"] != 848250.00
    assert_money_equals(snapshot["gross_estimate"], 978750.00, "gross_estimate")
    assert snapshot["input_reserve_sequence_high_water"] == 1
    assert snapshot["stale"] is False


# ---------------------------------------------------------------------------
# Instance — corner_calc_adjuster_selector_tiebreak_max_open_claims_desc
# ---------------------------------------------------------------------------
def test_adjuster_selector_breaks_an_exact_score_tie_on_max_open_claims(api):
    """PRD §3.5: "Survivors are ranked by `surge_capacity_score` descending,
    comparing the stored two-decimal values exactly."
    PRD §3.5: "When scores tie exactly, the higher `max_open_claims` wins; when
    that ties too, the earlier `created_at` wins."
    PRD §3.5: "Record identifiers are never used as a tie-break."
    PRD §3.5: "The first row is selected."
    PRD §3.5: "The created deployment is `REQUESTED`, its `selection_reason`
    records `EXPLICIT_ADJUSTER` when the caller pinned an adjuster and
    `SELECTOR_RANKED` when the server chose, and both `provisional_cost` and
    `final_settled_cost` read 0.00 because a requested deployment has not been
    priced and has drawn no rooms."

    Design: Corner/calculations/corner_calc_adjuster_selector_tiebreak_max_open_claims_desc
    """
    event = _hurricane_event(api, "CAT-2026-215")
    early = _staff_adjuster(api, "Amy Early", max_open_claims=5)
    bigger = _staff_adjuster(api, "Bo Bigger", max_open_claims=20)
    assert_money_equals(early["surge_capacity_score"], 100.00, "surge_capacity_score")
    assert_money_equals(bigger["surge_capacity_score"], 100.00, "surge_capacity_score")

    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-05T00:00:00.000Z",
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )

    # Both candidates score exactly 100.00; the higher max_open_claims wins even
    # though the other adjuster was created first.
    assert deployment["adjuster_id"] == bigger["id"]
    assert deployment["adjuster_id"] != early["id"]
    assert deployment["selection_reason"] == "SELECTOR_RANKED"
    assert deployment["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Instance — corner_calc_vendor_selector_excludes_non_activated_firms
# ---------------------------------------------------------------------------
def test_vendor_selector_skips_a_higher_scoring_non_activated_firm(api):
    """PRD §3.9: "The selector's eligibility filter admits a firm only when its
    `status` is `ACTIVATED` — `NETWORK_INACTIVE`, `CAPACITY_HOLD` and `SUSPENDED`
    firms are excluded even when they have spare capacity — and its
    `activated_for_event_id` matches the claim's event, and the claim's
    `loss_state` appears in the firm's `service_states`, and its `open_job_count`
    is strictly below its `max_concurrent_jobs`, and its `vendor_type` equals the
    requested `required_vendor_type`."
    PRD §3.9: "Survivors are ranked by `performance_score` descending, comparing
    stored two-decimal values exactly; ties are broken by the greatest spare
    capacity, meaning `max_concurrent_jobs` less `open_job_count`, and remaining
    ties by the earliest `created_at`, never by identifier."
    PRD §3.9: "A created assignment is `DISPATCHED`, stamps `dispatched_at_utc` at
    the current logical-clock instant, records `EXPLICIT_VENDOR` or
    `SELECTOR_RANKED` in `selection_reason`, and triggers a recompute of the firm's
    `open_job_count`."

    Design: Corner/calculations/corner_calc_vendor_selector_excludes_non_activated_firms
    """
    event = _hurricane_event(api, "CAT-2026-216")
    inactive = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Apex Mitigation",
                "vendor_type": "MITIGATION",
                "service_states": ["FL"],
                "max_concurrent_jobs": 10,
                "performance_score": 99.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    activated = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Basic Mitigation",
                "vendor_type": "MITIGATION",
                "service_states": ["FL"],
                "max_concurrent_jobs": 10,
                "performance_score": 70.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    assert inactive["status"] == "NETWORK_INACTIVE"
    validate_success(
        api.activate_vendor_firm(
            activated["id"],
            {"event_id": event["id"]},
            make_vendor_coordinator_headers(activated["id"]),
        )
    )
    claim = _dwelling_claim(api, event["id"], "POL-216")

    assignment = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 12000,
                "required_vendor_type": "MITIGATION",
            },
            CE,
        ),
        201,
    )

    assert_vendor_assignment(assignment)
    # The 99.00 firm never entered the pool, so the 70.00 ACTIVATED firm wins.
    assert assignment["vendor_firm_id"] == activated["id"]
    assert assignment["vendor_firm_id"] != inactive["id"]
    assert assignment["selection_reason"] == "SELECTOR_RANKED"
    assert assignment["status"] == "DISPATCHED"
    assert assignment["dispatched_at_utc"] == "2026-08-01T00:00:00.000Z"

    refreshed_firm = validate_success(
        api.get_vendor_firm(activated["id"], make_vendor_coordinator_headers(activated["id"]))
    )
    assert refreshed_firm["open_job_count"] == 1
