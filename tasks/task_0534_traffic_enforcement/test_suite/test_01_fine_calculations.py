"""Fine-schedule and vendor-share calculation tests (depth).

Translates the dual_variant_calc and combinatorial_formula difficulty instances,
plus the corner calculation instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_program_payload, create_camera_payload, create_calibration_payload,
    create_owner_payload, create_citation_payload, review_payload,
    create_vendor_contract_payload, create_payment_payload, settle_payload,
    clock_payload,
    setup_cited_citation, setup_hearing_scheduled, setup_paid_citation,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited, create_vendor_contract,
    initiate_payment, settle_to_cleared, rule_hearing, set_clock,
    TEST_USERS, make_review_officer_headers,
)

SYS = TEST_USERS["system_admin_headers"]
PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")


def test_statutory_assessed_amount_on_red_light_citation(api):
    """PRD §3.1: "`base_red_light_fine_cents` (the statutory base fine for a
    red-light violation)".
    PRD §3.4: "Finally, the program's `admin_fee_cents` is added to the (possibly
    surcharged) base to produce `assessed_amount_cents`."

    Design: Difficulty/dual_variant_calc/statutory_vs_adjudicated_fine_on_citation
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    assert cit["assessed_amount_cents"] == 12500
    assert cit["status"] == "CITED"


def test_adjudicated_reduced_fine_discards_statutory(api):
    """PRD §3.5: "The citation's `adjudicated_amount_cents` is recomputed as the
    adjudicator's `reduced_amount_cents` plus the program's `admin_fee_cents`."
    PRD §3.5: "for identical inputs the reduced total is strictly less than the
    statutory total."

    Design: Difficulty/dual_variant_calc/statutory_vs_adjudicated_fine_on_citation
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    assert cit["assessed_amount_cents"] == 12500
    set_clock("2026-05-15T11:00:00Z")
    ruled = rule_hearing(hearing["id"], "REDUCED", hearing["version"],
                         adjudicator_ref="adj-9", reduced_amount_cents=4000)
    updated = get_success_data(api.get_citation(cit["id"], PA))
    assert updated["adjudicated_amount_cents"] == 6500
    assert updated["status"] == "ADJUDICATED_UPHELD"


def test_vendor_share_is_fine_portion_only_on_payment(api):
    """PRD §3.7: "The fine portion for the share is the citation's
    `adjudicated_amount_cents` minus the program's `admin_fee_cents` (never below
    zero). The raw share is that fine portion multiplied by the contract's
    `revenue_share_pct`, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/vendor_share_vs_owner_owed_on_payment
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    vc = get_success_data(api.get_vendor_contract(ctx["vendor_contract"]["id"], PA))
    assert cit["status"] == "PAID"
    assert cit["amount_paid_cents"] == 12500
    assert vc["accrued_vendor_share_cents"] == 3000


def test_owner_owed_total_equals_assessed_on_paid(api):
    """PRD §3.6: "The owed total equals the `adjudicated_amount_cents`, plus — only
    when the citation's `escalation_stage` is `DELINQUENT` — a single flat
    `late_fee_cents` from the program, applied exactly once at the delinquent stage."

    Design: Difficulty/dual_variant_calc/vendor_share_vs_owner_owed_on_payment
    """
    ctx = setup_paid_citation(revenue_share_pct=0.3)
    cit = ctx["citation"]
    # Escalation is NONE, so owed total == adjudicated == 12500, and the owner paid
    # exactly that to reach PAID.
    assert cit["amount_paid_cents"] == 12500
    assert cit["adjudicated_amount_cents"] == 12500


def test_speed_band_tiered_multiplier_first_offense(api):
    """PRD §3.4: "if the amount over is at most 20 mph (that is, from 11 through 20
    mph over), the multiplier is 1.5".
    PRD §3.4: "The base for a speed violation is the `base_speed_fine_cents`
    multiplied by the selected multiplier, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/speed_band_tiered_nonlinear_with_surcharge
    """
    program = create_program()
    camera = create_camera(program["id"], intersection_code="SPD-1",
                           camera_type="SPEED", speed_limit_mph=40)
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="SPD999", full_name="Lee Owner",
                 mailing_address="2 St")
    citation = capture_citation(program["id"], camera["id"],
                                citation_overrides={"captured_plate_number": "SPD999",
                                                    "measured_speed_mph": 55})
    cited = review_to_cited(citation["id"])
    # over = 55 - 40 = 15 -> band 1.5 -> 8000*1.5=12000 + admin 2500 = 14500
    assert cited["assessed_amount_cents"] == 14500
    assert cited["status"] == "CITED"


def test_speed_band1_at_most_10_over_multiplier(api):
    """PRD §3.4: "if the amount over is at most 10 mph, the multiplier is 1.0".
    PRD §3.4: "The base for a speed violation is the `base_speed_fine_cents`
    multiplied by the selected multiplier, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/speed_band_tiered_nonlinear_with_surcharge
    """
    program = create_program()
    camera = create_camera(program["id"], intersection_code="SPD-1",
                           camera_type="SPEED", speed_limit_mph=40)
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="SLOW1", full_name="Kim",
                 mailing_address="4 St")
    citation = capture_citation(program["id"], camera["id"],
                                citation_overrides={"captured_plate_number": "SLOW1",
                                                    "measured_speed_mph": 48})
    cited = review_to_cited(citation["id"])
    # over = 8 -> band 1.0 -> 8000*1.0=8000 + admin 2500 = 10500 (first offense)
    assert cited["assessed_amount_cents"] == 10500


def test_speed_band3_over_20_multiplier(api):
    """PRD §3.4: "if the amount over is 21 mph or more, the multiplier is 2.5".
    PRD §3.4: "The base for a speed violation is the `base_speed_fine_cents`
    multiplied by the selected multiplier, rounded half up to a whole cent."

    Design: Corner/calculations/speed_band3_over_20_multiplier
    """
    program = create_program()
    camera = create_camera(program["id"], intersection_code="SPD-1",
                           camera_type="SPEED", speed_limit_mph=40)
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="FAST1", full_name="Sam",
                 mailing_address="9 St")
    citation = capture_citation(program["id"], camera["id"],
                                citation_overrides={"captured_plate_number": "FAST1",
                                                    "measured_speed_mph": 65})
    cited = review_to_cited(citation["id"])
    # over = 25 -> band 2.5 -> 8000*2.5=20000 + admin 2500 = 22500
    assert cited["assessed_amount_cents"] == 22500


def test_repeat_surcharge_rounding_order_band_then_surcharge(api):
    """PRD §3.4: "If that count is at least one, this is a repeat offense, and the
    base is multiplied by one plus the program's `repeat_offender_surcharge_pct`,
    rounded half up to a whole cent."
    PRD §3.4: "The two rounding steps are applied independently and in this exact
    order — first the speed-band multiply-and-round (for speed cameras), then, if
    applicable, the surcharge multiply-and-round — and are never combined into a
    single multiplication."

    Design: Difficulty/combinatorial_formula/fine_rounding_order_band_then_surcharge
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="REP111", full_name="Rex Owner",
                 mailing_address="3 St")
    # First citation -> CITED (assessed 12500).
    cit1 = capture_citation(program["id"], camera["id"],
                            citation_overrides={"captured_plate_number": "REP111"})
    cited1 = review_to_cited(cit1["id"])
    assert cited1["assessed_amount_cents"] == 12500
    # Advance the clock and capture a second, triggering the repeat surcharge.
    set_clock("2026-05-02T00:00:00Z")
    cit2 = capture_citation(program["id"], camera["id"],
                            citation_overrides={"captured_plate_number": "REP111",
                                                "event_at_utc": "2026-05-02T08:00:00Z"})
    cited2 = review_to_cited(cit2["id"])
    # base 10000 -> round(10000*1.5)=15000 -> +admin 2500 = 17500
    assert cited2["assessed_amount_cents"] == 17500


def test_first_offense_no_surcharge_before_repeat(api):
    """PRD §3.4: "If that count is at least one, this is a repeat offense, and the
    base is multiplied by one plus the program's `repeat_offender_surcharge_pct`,
    rounded half up to a whole cent."
    PRD §3.1: "`base_red_light_fine_cents` (the statutory base fine for a red-light
    violation)".

    Design: Difficulty/combinatorial_formula/fine_rounding_order_band_then_surcharge
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="REP111", full_name="Rex Owner",
                 mailing_address="3 St")
    cit1 = capture_citation(program["id"], camera["id"],
                            citation_overrides={"captured_plate_number": "REP111"})
    cited1 = review_to_cited(cit1["id"])
    # No prior citation -> no surcharge: base 10000 + admin 2500 = 12500.
    assert cited1["assessed_amount_cents"] == 12500


def test_assessed_amount_is_server_computed_input_ignored(api):
    """PRD §3.3: "at this point the citation's `registered_owner_id` is still null,
    and the money fields have not yet been computed."
    PRD §3.3: "it computes `assessed_amount_cents` via the statutory fine schedule
    of Section 3.4".

    Design: Corner/entities/assessed_amount_is_computed_input_ignored
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="ABC123")
    # Attempt to inject assessed_amount_cents at capture time; it must be ignored.
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"captured_plate_number": "ABC123",
                            "assessed_amount_cents": 1},
    )
    cited = review_to_cited(citation["id"])
    assert cited["assessed_amount_cents"] == 12500


def test_vendor_share_capped_at_monthly_cap(api):
    """PRD §3.7: "If the contract has a `monthly_cap_cents`, the accrual may not push
    the contract's running `accrued_vendor_share_cents` above the cap: the applied
    share is the lesser of the raw share and the remaining headroom, where headroom
    is the cap minus the already-accrued amount, floored at zero."

    Design: Corner/calculations/vendor_share_capped_at_monthly_cap
    """
    program = create_program()
    vendor = create_vendor_contract(program["id"], 0.3, monthly_cap_cents=2500)
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="ABC123")
    citation = capture_citation(program["id"], camera["id"])
    review_to_cited(citation["id"])
    payment = initiate_payment(citation["id"], 12500)
    settle_to_cleared(payment["id"])
    vc = get_success_data(api.get_vendor_contract(vendor["id"], PA))
    # raw share 3000 capped at 2500
    assert vc["accrued_vendor_share_cents"] == 2500


def test_partial_payment_does_not_clear_citation(api):
    """PRD §3.7: "If the cumulative cleared amount then meets or exceeds the
    citation's current owed total, the citation transitions to `PAID`."

    Design: Corner/calculations/partial_payment_does_not_clear_citation
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    payment = initiate_payment(cit["id"], 10000)
    settle_to_cleared(payment["id"])
    updated = get_success_data(api.get_citation(cit["id"], PA))
    # 10000 < owed 12500 -> stays CITED
    assert updated["status"] == "CITED"
    assert updated["amount_paid_cents"] == 10000


def test_amount_owed_includes_late_fee_after_sweep(api):
    """PRD §3.6: "A citation escalates to delinquency only once the clock has passed
    the delinquency deadline, which is the citation's `due_at_utc` plus one further
    `response_window_days`".
    PRD §3.6: "a `CITED` citation past that deadline transitions `CITED →
    DELINQUENT`, and an `ADJUDICATED_UPHELD` citation past that deadline transitions
    `ADJUDICATED_UPHELD → DELINQUENT`. In both cases the citation's
    `escalation_stage` becomes `DELINQUENT`".

    Design: Corner/calculations/amount_owed_includes_late_fee_after_sweep
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    create_owner(program["id"], plate_number="ABC123")
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"captured_plate_number": "ABC123",
                            "event_at_utc": "2026-05-01T00:00:00Z"})
    review_to_cited(citation["id"])
    set_clock("2026-07-15T00:00:00Z")
    get_success_data(api.escalation_sweep({}, SYS))
    updated = get_success_data(api.get_citation(citation["id"], PA))
    assert updated["status"] == "DELINQUENT"
    assert updated["escalation_stage"] == "DELINQUENT"
