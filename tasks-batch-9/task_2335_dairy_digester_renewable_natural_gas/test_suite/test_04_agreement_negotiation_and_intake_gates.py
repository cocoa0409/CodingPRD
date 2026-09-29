"""The bounded negotiation cycle and the ordered gates that guard a booked load."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    book_delivery,
    close_day,
    create_active_agreement,
    create_dairy,
    create_draft_agreement,
    create_facility,
    create_ops_day,
    make_dairy_partner_headers,
    offer_agreement,
    override_posture,
    set_clock,
    validate_error,
    validate_success,
)

DAIRY_ONE = {
    "name": "Vista Verde Dairy",
    "county": "Tulare",
    "herd_size": 3000,
    "manure_management_baseline": "LAGOON",
    "haul_distance_km": 12.0,
    "annual_nitrogen_budget_kg": 18000.000,
}
DAIRY_TWO = {
    "name": "Kings River Dairy",
    "county": "Kings",
    "herd_size": 2200,
    "manure_management_baseline": "SOLID_STORAGE",
    "haul_distance_km": 30.0,
    "annual_nitrogen_budget_kg": 12000.000,
}


def _exhausted_negotiation(api):
    """Three complete counter/revise rounds, then a fourth offer awaiting signature."""
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy(**DAIRY_ONE)
    facility = create_facility()
    agreement = create_draft_agreement(
        dairy["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    dairy_headers = make_dairy_partner_headers(dairy["id"])
    rounds = [
        ("Round 1 offer", 200.000, 0.2600, "Need more volume", 185.000, 0.2300),
        ("Round 2 offer", 198.000, 0.2550, "Still short", 190.000, 0.2350),
        ("Round 3 offer", 195.000, 0.2500, "Final ask", 192.000, 0.2400),
    ]
    for note, tonnes, share, comment, revised_tonnes, revised_share in rounds:
        offer_agreement(agreement["id"], note)
        validate_success(
            api.counter_agreement(
                agreement["id"],
                {
                    "countered_tonnes_per_day": tonnes,
                    "countered_revenue_share_pct": share,
                    "comment": comment,
                },
                dairy_headers,
            )
        )
        validate_success(
            api.revise_agreement(
                agreement["id"],
                {
                    "committed_tonnes_per_day": revised_tonnes,
                    "minimum_total_solids_pct": 8.0,
                    "revenue_share_pct": revised_share,
                },
                OPERATOR,
            )
        )
    agreement = offer_agreement(agreement["id"], "Round 4 offer - best and final")
    return {"dairy": dairy, "facility": facility, "agreement": agreement, "headers": dairy_headers}


def _two_dairy_facility():
    dairy_one = create_dairy(**DAIRY_ONE)
    dairy_two = create_dairy(**DAIRY_TWO)
    facility = create_facility()
    return dairy_one, dairy_two, facility


def test_01_a_fourth_counter_is_refused_once_three_rounds_are_spent(api):
    """The negotiation cycle is bounded at three counters per agreement.

    PRD: "A counter is permitted only while `negotiation_round` is still below three; a fourth counter attempt on an agreement whose `negotiation_round` has already reached three is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/nlsm_agreement_fourth_counter_rejected_after_three_negotiation_rounds
    """
    negotiation = _exhausted_negotiation(api)
    assert negotiation["agreement"]["negotiation_round"] == 3

    validate_error(
        api.counter_agreement(
            negotiation["agreement"]["id"],
            {
                "countered_tonnes_per_day": 194.000,
                "countered_revenue_share_pct": 0.2450,
                "comment": "One more try",
            },
            negotiation["headers"],
        ),
        "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
        422,
    )


def test_02_the_refused_counter_leaves_the_last_revised_terms_intact(api):
    """The agreement keeps the third revision's terms and stays awaiting signature.

    PRD: "Revising closes the cycle, moving the agreement `COUNTERED → DRAFT`: the `ProjectOperator` supplies fresh values for `committed_tonnes_per_day`, `minimum_total_solids_pct` and `revenue_share_pct`, which overwrite the previous terms, while `countered_tonnes_per_day` and `countered_revenue_share_pct` are cleared back to null and the agreement's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/nlsm_agreement_fourth_counter_rejected_after_three_negotiation_rounds
    """
    negotiation = _exhausted_negotiation(api)
    validate_error(
        api.counter_agreement(
            negotiation["agreement"]["id"],
            {
                "countered_tonnes_per_day": 194.000,
                "countered_revenue_share_pct": 0.2450,
                "comment": "One more try",
            },
            negotiation["headers"],
        ),
        "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
        422,
    )

    agreement = validate_success(
        api.get_agreement(negotiation["agreement"]["id"], OPERATOR)
    )
    assert agreement["status"] == "PENDING_DAIRY_SIGNATURE"
    assert agreement["countered_tonnes_per_day"] is None
    assert agreement["countered_revenue_share_pct"] is None
    assert agreement["committed_tonnes_per_day"] == 192.000
    assert agreement["revenue_share_pct"] == 0.2400
    assert agreement["version"] == 11

    dairy = validate_success(api.get_dairy(negotiation["dairy"]["id"], ADMIN))
    assert dairy["status"] == "PROSPECT"


def test_03_a_draft_agreement_reports_the_state_error_not_the_solids_error(api):
    """An off-spec load on a draft agreement is refused for the agreement, not the solids.

    PRD: "Booking is gated by five business rules in the order established in §2.9: the supplying agreement must be `ACTIVE`, or the request fails with `ERR_AGREEMENT_NOT_ACTIVE`; the receiving facility's `ops_posture` must not be `UPSET`, or the request fails with `ERR_FACILITY_UPSET`; the day's `ops_date` must fall inside the inclusive term bounded by the agreement's `term_start_date` and `term_end_date`, or the request fails with `ERR_OUTSIDE_AGREEMENT_TERM`; the measured `total_solids_pct` must be greater than or equal to the agreement's `minimum_total_solids_pct`, with exact equality accepted, or the request fails with `ERR_SOLIDS_BELOW_MINIMUM`; and finally the sum of `net_tonnes` across the day's already-`ACCEPTED` deliveries plus the new load's `net_tonnes` must be less than or equal to the facility's `hydraulic_capacity_tonnes_per_day`, with equality accepted, or the request fails with `ERR_HYDRAULIC_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/ppv_state_agreement_not_active_wins_over_business_constraint_solids_minimum
    """
    set_clock("2026-08-03T09:00:00Z")
    dairy_one, dairy_two, facility = _two_dairy_facility()
    draft = create_draft_agreement(
        dairy_one["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    create_active_agreement(
        dairy_two["id"],
        facility["id"],
        committed_tonnes_per_day=120.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.1500,
        revenue_share_basis="GROSS",
        curtailable=False,
    )
    ops_day = create_ops_day(facility["id"], "2026-08-03")

    validate_error(
        api.create_delivery(
            {
                "agreement_id": draft["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 5.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_AGREEMENT_NOT_ACTIVE",
        409,
    )

    unchanged = validate_success(api.get_agreement(draft["id"], OPERATOR))
    assert unchanged["status"] == "DRAFT"


def test_04_the_same_off_spec_load_on_an_active_agreement_reports_the_solids_error(api):
    """With the state gate satisfied, the solids gate is the one that fires.

    PRD: "the measured `total_solids_pct` must be greater than or equal to the agreement's `minimum_total_solids_pct`, with exact equality accepted, or the request fails with `ERR_SOLIDS_BELOW_MINIMUM`"

    Design: Difficulty/priority_pair_validation_conflict/ppv_state_agreement_not_active_wins_over_business_constraint_solids_minimum
    """
    set_clock("2026-08-03T09:00:00Z")
    dairy_one, dairy_two, facility = _two_dairy_facility()
    create_draft_agreement(
        dairy_one["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    active = create_active_agreement(
        dairy_two["id"],
        facility["id"],
        committed_tonnes_per_day=120.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.1500,
        revenue_share_basis="GROSS",
        curtailable=False,
    )
    ops_day = create_ops_day(facility["id"], "2026-08-03")

    validate_error(
        api.create_delivery(
            {
                "agreement_id": active["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 5.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_SOLIDS_BELOW_MINIMUM",
        422,
    )

    day = validate_success(api.get_ops_day(ops_day["id"], OPERATOR))
    assert day["organic_loading_rate"] == 0.000
    plant = validate_success(api.get_facility(facility["id"], ADMIN))
    assert plant["total_manure_received_tonnes"] == 0.000


def _upset_facility_with_a_second_day():
    """Day one drives the digester into upset; day two is open and empty."""
    set_clock("2026-08-03T09:00:00Z")
    dairy_one, dairy_two, facility = _two_dairy_facility()
    agreement_one = create_active_agreement(
        dairy_one["id"],
        facility["id"],
        committed_tonnes_per_day=400.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    agreement_two = create_active_agreement(
        dairy_two["id"],
        facility["id"],
        committed_tonnes_per_day=120.000,
        minimum_total_solids_pct=6.5,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.1500,
        revenue_share_basis="GROSS",
        curtailable=False,
    )
    day_one = create_ops_day(facility["id"], "2026-08-03")
    day_two = create_ops_day(facility["id"], "2026-08-04")
    book_delivery(
        agreement_one["id"],
        day_one["id"],
        gross_tonnes=400.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    close_day(day_one["id"], vfa_mg_per_l=3600.0)
    return {
        "facility": facility,
        "agreement_two": agreement_two,
        "day_one": day_one,
        "day_two": day_two,
    }


def test_05_an_upset_digester_refuses_an_oversized_load_on_safety_grounds_first(api):
    """A 900-tonne booking into an upset digester fails for the upset, not the capacity.

    PRD: "the receiving facility's `ops_posture` must not be `UPSET`, or the request fails with `ERR_FACILITY_UPSET`"

    Design: Difficulty/priority_pair_validation_conflict/ppv_business_safety_facility_upset_wins_over_business_fiscal_hydraulic_capacity
    """
    plant = _upset_facility_with_a_second_day()
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["ops_posture"] == "UPSET"

    validate_error(
        api.create_delivery(
            {
                "agreement_id": plant["agreement_two"]["id"],
                "ops_day_id": plant["day_two"]["id"],
                "gross_tonnes": 900.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_FACILITY_UPSET",
        422,
    )


def test_06_clearing_the_upset_by_override_exposes_the_hydraulic_ceiling(api):
    """Once the safety gate is lifted the fiscal capacity gate reports instead.

    PRD: "and finally the sum of `net_tonnes` across the day's already-`ACCEPTED` deliveries plus the new load's `net_tonnes` must be less than or equal to the facility's `hydraulic_capacity_tonnes_per_day`, with equality accepted, or the request fails with `ERR_HYDRAULIC_CAPACITY_EXCEEDED`"

    Design: Difficulty/priority_pair_validation_conflict/ppv_business_safety_facility_upset_wins_over_business_fiscal_hydraulic_capacity
    """
    plant = _upset_facility_with_a_second_day()
    load = {
        "agreement_id": plant["agreement_two"]["id"],
        "ops_day_id": plant["day_two"]["id"],
        "gross_tonnes": 900.000,
        "tare_tonnes": 0.000,
        "total_solids_pct": 8.0,
        "volatile_solids_pct_of_ts": 82.0,
    }
    validate_error(api.create_delivery(dict(load), OPERATOR), "ERR_FACILITY_UPSET", 422)

    facility = override_posture(
        plant["facility"]["id"],
        "OPS",
        "Engineering cleared the digester after acid dosing",
    )
    assert facility["ops_posture"] == "RESTRICTED"
    assert facility["posture_override_active"] is True

    validate_error(
        api.create_delivery(dict(load), OPERATOR), "ERR_HYDRAULIC_CAPACITY_EXCEEDED", 422
    )

    agreement = validate_success(api.get_agreement(plant["agreement_two"]["id"], OPERATOR))
    assert agreement["status"] == "ACTIVE"
    day_two = validate_success(api.get_ops_day(plant["day_two"]["id"], OPERATOR))
    assert day_two["organic_loading_rate"] == 0.000
    reread = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert reread["total_manure_received_tonnes"] == 400.000


def test_07_total_solids_exactly_at_the_agreement_minimum_is_accepted(api):
    """A load measured at precisely the contractual floor is booked.

    PRD: "`vs_tonnes`, the volatile-solids mass, is `net_tonnes` multiplied by `total_solids_pct` divided by 100 and then multiplied by `volatile_solids_pct_of_ts` divided by 100, rounded to 3 decimal places."

    Design: Difficulty/boundary_precision_check/bpc_total_solids_exactly_equal_to_agreement_minimum_is_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy(**DAIRY_ONE)
    facility = create_facility()
    agreement = create_active_agreement(
        dairy["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    ops_day = create_ops_day(facility["id"], "2026-08-03")

    delivery = validate_success(
        api.create_delivery(
            {
                "agreement_id": agreement["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        201,
    )
    assert delivery["status"] == "ACCEPTED"
    assert delivery["net_tonnes"] == 150.000
    assert delivery["vs_tonnes"] == 9.840
    assert delivery["haul_tonne_km"] == 1800.00


def test_08_a_tenth_of_a_point_below_the_minimum_is_rejected(api):
    """Just under the floor is off-spec, and the accepted load's loading rate stands.

    PRD: "The quotient, rounded to 3 decimal places, is `organic_loading_rate`."

    Design: Difficulty/boundary_precision_check/bpc_total_solids_exactly_equal_to_agreement_minimum_is_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy(**DAIRY_ONE)
    facility = create_facility()
    agreement = create_active_agreement(
        dairy["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    ops_day = create_ops_day(facility["id"], "2026-08-03")
    book_delivery(
        agreement["id"],
        ops_day["id"],
        gross_tonnes=150.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )

    validate_error(
        api.create_delivery(
            {
                "agreement_id": agreement["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 100.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 7.9,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_SOLIDS_BELOW_MINIMUM",
        422,
    )

    day = validate_success(api.get_ops_day(ops_day["id"], OPERATOR))
    assert day["organic_loading_rate"] == 1.640
    plant = validate_success(api.get_facility(facility["id"], ADMIN))
    assert plant["total_manure_received_tonnes"] == 150.000
