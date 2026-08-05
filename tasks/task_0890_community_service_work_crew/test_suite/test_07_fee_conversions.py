"""Fee conversions: provisional quote vs final settlement, the tiered-then-clamped fee,
the zero-outstanding pay boundary, reversal compensation, and the four-eyes / OCC / limit
guards.

Covers Difficulty queue: dual_variant_calc (fee), combinatorial_formula (fee),
boundary_precision_check (pay zero outstanding), compensating_invariant (reverse fee).
Covers Corner queue: fee validations, self-approval, and the OCC layer.
"""
from test_helpers import (
    validate_success, validate_error,
    make_participant_headers,
    create_fee_conversion_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]


# ============================ Difficulty: quote vs settlement divergence
def test_settlement_below_quote_when_outstanding_drops(api):
    """PRD §3.6: "The provisional quote uses the as-requested `hours_to_convert`; the final settlement,
    computed at payment time, uses the actually-settled hours and is therefore no larger
    than the quote whenever outstanding hours fell between request and payment."
    PRD §3.6: "computes `settled_hours` as the smaller of `hours_to_convert` and the referral's current
    `hours_outstanding`".

    Design: Difficulty/dual_variant_calc/dv_fee_provisional_quote_vs_final_settlement
    """
    s = fx.active_placement_scenario(hours_ordered=12, court_case_number="CR-2")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T13:00:00Z")  # 4h -> outstanding 8
    fee = fx.new_fee_conversion(s["referral_id"], 8, s["participant_id"])
    assert fee["quoted_fee_cents"] == 12000
    fx.completed_session(s, "2026-06-02T09:00:00Z", "2026-06-02T15:00:00Z")  # 6h -> outstanding 2
    fx.approve_fee(fee["id"], COORD2)
    paid = fx.pay_fee(fee["id"], 3000, s["participant_id"])
    assert paid["settlement_fee_cents"] == 3000
    assert paid["settled_hours"] == 2
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["status"] == "CONVERTED"


def test_settlement_equals_quote_when_outstanding_unchanged(api):
    """PRD §3.6: "the final settlement, computed at payment time, uses the actually-settled hours and is
    therefore no larger than the quote whenever outstanding hours fell between request and
    payment."

    Design: Difficulty/dual_variant_calc/dv_fee_provisional_quote_vs_final_settlement
    """
    s = fx.active_placement_scenario(hours_ordered=12, court_case_number="CR-2B")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T13:00:00Z")  # 4h -> outstanding 8
    fee = fx.new_fee_conversion(s["referral_id"], 8, s["participant_id"])
    assert fee["quoted_fee_cents"] == 12000
    fx.approve_fee(fee["id"], COORD2)
    paid = fx.pay_fee(fee["id"], 12000, s["participant_id"])  # outstanding still 8
    assert paid["settled_hours"] == 8
    assert paid["settlement_fee_cents"] == 12000
    assert paid["settlement_fee_cents"] == fee["quoted_fee_cents"]


# ============================ Difficulty: tiered rate with MIN clamp
def test_full_tier_two_hours_clamps_up_to_minimum(api):
    """PRD §3.6: "0.25 for `FULL` (three dollars seventy-five an hour). The raw fee is the number of hours
    multiplied by that per-hour rate, rounded half-up to a whole cent. The raw fee is then
    clamped into a band: first raised to a floor of 2500 cents ($25) if below it, then
    capped at a ceiling of 200000 cents ($2000) if above it."

    Design: Difficulty/combinatorial_formula/cf_conversion_fee_tiered_rate_with_min_clamp
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=40, indigency="FULL",
                          offense_class="INFRACTION", court_case_number="CR-3")
    fee = fx.new_fee_conversion(ref["id"], 2, part["id"])
    assert fee["quoted_fee_cents"] == 2500  # raw 2*375=750 clamped up to MIN
    assert fee["indigency_status_snapshot"] == "FULL"


def test_partial_tier_within_band_uses_tiered_rate(api):
    """PRD §3.6: "The per-hour rate is a base of 1500 cents (fifteen dollars per hour) multiplied by an
    indigency factor keyed to the snapshot tier: 1.0 for `NONE` (fifteen dollars an hour),
    0.5 for `PARTIAL` (seven dollars fifty an hour), and 0.25 for `FULL` (three dollars
    seventy-five an hour)."

    Design: Difficulty/combinatorial_formula/cf_conversion_fee_tiered_rate_with_min_clamp
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=40, indigency="PARTIAL",
                          court_case_number="CR-3B")
    fee = fx.new_fee_conversion(ref["id"], 10, part["id"])
    assert fee["quoted_fee_cents"] == 7500  # 10 * (1500*0.5) = 7500, within band
    assert fee["indigency_status_snapshot"] == "PARTIAL"


# ============================ Difficulty: pay rejected at zero outstanding
def _approved_fee_then_complete_by_work(court_case_number):
    """Referral (4h) with an APPROVED conversion for 4h, then all 4h verified by work so
    the referral completes and outstanding reaches 0."""
    base = fx.accepting_site_with_supervisor()
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=4, court_case_number=court_case_number)
    fee = fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=ref["version"])
    fx.approve_fee(fee["id"], COORD2)
    plc = fx.new_placement(ref["id"], base["site"]["id"], base["supervisor"]["id"])
    fx.sign_waiver(plc["id"], part["id"])
    fx.activate_placement(plc["id"])
    scenario = {"placement_id": plc["id"], "supervisor_id": base["supervisor"]["id"]}
    fx.completed_session(scenario, "2026-06-01T09:00:00Z", "2026-06-01T13:00:00Z")  # 4h
    return part, ref, fee


def test_pay_rejected_when_outstanding_is_zero(api):
    """PRD §3.6: "The referral must have outstanding hours to settle: if `hours_outstanding` is 0 the payment
    is refused with `ERR_NO_REMAINING_HOURS` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_fee_pay_zero_outstanding_rejected
    """
    part, ref, fee = _approved_fee_then_complete_by_work("CR-12")
    res = api.pay_fee_conversion(fee["id"], {"amount_cents": 6000},
                                 make_participant_headers(part["id"]))
    validate_error(res, "ERR_NO_REMAINING_HOURS", 409)
    after = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert after["status"] == "COMPLETED"


def test_pay_rejected_leaves_conversion_approved_and_no_money(api):
    """PRD §3.6: "if `hours_outstanding` is 0 the payment is refused with `ERR_NO_REMAINING_HOURS` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_fee_pay_zero_outstanding_rejected
    """
    part, ref, fee = _approved_fee_then_complete_by_work("CR-12B")
    api.pay_fee_conversion(fee["id"], {"amount_cents": 6000},
                           make_participant_headers(part["id"]))  # rejected
    fee_after = validate_success(api.get_fee_conversion(fee["id"], COORD), 200)
    assert fee_after["status"] == "APPROVED"
    ref_after = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert ref_after["fees_settled_cents"] == 0


# ============================ Difficulty: reverse preserves money ledger
def test_reverse_paid_conversion_restores_money_ledger(api):
    """PRD §3.6: "Reversing a `PAID` conversion unwinds the ledger: it subtracts the conversion's
    `settled_hours` from the referral's `hours_converted`, subtracts its
    `settlement_fee_cents` from `fees_settled_cents`, and recomputes `hours_outstanding`."

    Design: Difficulty/compensating_invariant/ci_reverse_fee_preserves_money_ledger
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=10, court_case_number="CR-18")
    fee = fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=ref["version"])
    fx.approve_fee(fee["id"], COORD2)
    fx.pay_fee(fee["id"], 6000, part["id"])  # converted 4, fees 6000, outstanding 6
    reversed_fee = validate_success(api.reverse_fee_conversion(
        fee["id"], COORD, {"reason": "refunded"}), 200)
    assert reversed_fee["status"] == "REVERSED"
    ref_after = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert ref_after["fees_settled_cents"] == 0
    assert ref_after["hours_converted"] == 0
    assert ref_after["hours_outstanding"] == 10


def test_reverse_sole_conversion_restores_referral_active(api):
    """PRD §3.6: "If the referral had reached `CONVERTED` solely because of this conversion, reversing it
    restores the referral to `ACTIVE`, so that both the hours partition and the money total
    return to their pre-conversion values."

    Design: Difficulty/compensating_invariant/ci_reverse_fee_preserves_money_ledger
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=4, court_case_number="CR-18B")
    fee = fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=ref["version"])
    fx.approve_fee(fee["id"], COORD2)
    fx.pay_fee(fee["id"], 6000, part["id"])  # outstanding 0 -> CONVERTED
    converted = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert converted["status"] == "CONVERTED"
    validate_success(api.reverse_fee_conversion(fee["id"], COORD), 200)
    ref_after = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert ref_after["status"] == "ACTIVE"
    assert ref_after["hours_outstanding"] == 4
    assert ref_after["fees_settled_cents"] == 0


# ============================ Corner: fee validations & OCC
def test_fee_convert_more_than_outstanding_rejected(api):
    """PRD §3.6: "The requested hours may not exceed the referral's current `hours_outstanding`, else
    `ERR_HOURS_EXCEED_OUTSTANDING` (HTTP 422)."

    Design: Corner/validations/fee_convert_more_than_outstanding_rejected
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D10")
    res = api.create_fee_conversion(
        create_fee_conversion_payload(ref["id"], 30, ref["version"]),
        make_participant_headers(part["id"]))
    validate_error(res, "ERR_HOURS_EXCEED_OUTSTANDING", 422)


def test_approve_fee_on_noncompliant_referral_rejected(api):
    """PRD §3.6: "The referral must also still be `ACTIVE`, else `ERR_REFERRAL_NOT_ACTIVE`."

    Design: Corner/validations/approve_fee_on_noncompliant_referral_rejected
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D14")
    fee = fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=ref["version"])
    fx.report_back(ref["id"], reason="Missed")
    res = api.approve_fee_conversion(fee["id"], COORD2)
    validate_error(res, "ERR_REFERRAL_NOT_ACTIVE", 409)


def test_fee_self_approval_by_requester_rejected(api):
    """PRD §3.6: "the approver's `X-User-ID` must differ from the `requested_by_user_id`; a self-approval is
    refused with `ERR_SELF_APPROVAL` (HTTP 403)."

    Design: Corner/rbac/fee_self_approval_by_requester_rejected
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D17")
    # A ProgramCoordinator (coord-1) requests, then the same coord-1 approves.
    fee = validate_success(api.create_fee_conversion(
        create_fee_conversion_payload(ref["id"], 4, ref["version"]), COORD), 201)
    res = api.approve_fee_conversion(fee["id"], COORD)
    validate_error(res, "ERR_SELF_APPROVAL", 403)


def test_stale_referral_version_on_fee_create_rejected(api):
    """PRD §2.5: "The create request must carry `expected_referral_version`, holding the `version` of the
    referral the client last observed. If that value does not match the referral's current
    `version` at the moment the create is processed, the request is rejected with
    `ERR_STALE_REFERRAL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_referral_version_on_fee_create_rejected
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D22")
    v0 = ref["version"]
    fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=v0)  # bumps version
    res = api.create_fee_conversion(
        create_fee_conversion_payload(ref["id"], 6, v0),
        make_participant_headers(part["id"]))
    validate_error(res, "ERR_STALE_REFERRAL_VERSION", 412)


def test_matching_referral_version_supersedes_prior(api):
    """PRD §3.6: "A new request supersedes any prior conversion still in `REQUESTED` status for the same
    referral by moving that prior one to `DENIED`, and it advances the referral's `version`
    by 1".

    Design: Corner/cross_cutting_complexity_layers/occ_matching_referral_version_supersedes_prior
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D23")
    fee_a = fx.new_fee_conversion(ref["id"], 4, part["id"], expected_version=ref["version"])
    v1 = fx.referral_version(ref["id"])
    res = api.create_fee_conversion(
        create_fee_conversion_payload(ref["id"], 6, v1),
        make_participant_headers(part["id"]))
    fee_b = validate_success(res, 201)
    fee_a_after = validate_success(api.get_fee_conversion(fee_a["id"], COORD), 200)
    assert fee_a_after["status"] == "DENIED"
    assert fee_b["status"] == "REQUESTED"
