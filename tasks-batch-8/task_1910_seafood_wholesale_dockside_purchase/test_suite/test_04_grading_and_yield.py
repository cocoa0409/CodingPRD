"""Grading and yield: the yield-processing formula, assessment lifecycle,
and the ticket auto-grading bubble-up."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_kg,
    create_grade_assessment_payload,
    create_vessel,
    create_catch_area,
    create_species,
    create_and_publish_quote,
    create_dock_ticket,
    land_ticket,
    get_ticket,
    add_landing_line,
    create_assessment,
    finalize_assessment,
    create_and_finalize_assessment,
    get_lot_for_line,
)

OM = TEST_USERS["operations_manager_headers"]
GI = TEST_USERS["grading_inspector_headers"]


class TestYieldProcessingInteraction:
    """The processed-weight formula multiplies landed weight by yield, a
    grade-conditional factor, and a processing-type factor."""

    def test_grade_c_fillet_interaction(self, api):
        """PRD §3.4: "On finalize, the line's `processed_weight_kg` is computed as the smaller of the raw `landed_weight_kg` and the product of `landed_weight_kg` multiplied by the assessment's `yield_pct`, by a condition factor, and by a processing factor, the result rounded half up to two decimal places. The condition factor is 1.00 for an assessed `GRADE_A`, 0.97 for `GRADE_B`, and 0.92 for `GRADE_C`; the processing factor is 1.00 when the line's `processing_type` is `WHOLE` and 0.85 when it is `FILLETED`."
        PRD §3.4: "the final amount is the `processed_weight_kg` multiplied by that quote's `price_per_kg_cents`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/yield_processing_grade_and_processing_interaction
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
        create_and_publish_quote(species["id"], grade="GRADE_C", price_per_kg_cents=700)
        ticket = create_dock_ticket(vessel["id"], area["id"])
        land_ticket(ticket["id"])
        line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                                landed_weight_kg=100.00, processing_type="FILLETED")

        create_and_finalize_assessment(line["id"], assessed_grade="GRADE_C",
                                       yield_pct=0.80)
        line_after = get_success_data(api_client.get_landing_line(line["id"], OM))
        assert_kg(line_after["processed_weight_kg"], 62.56,
                  "100.00 x 0.80 x 0.92 (GRADE_C) x 0.85 (FILLETED)")
        assert line_after["final_amount_cents"] == 43792, "62.56 kg x 700 cents/kg"

    def test_grade_b_fillet_interaction(self, api):
        """PRD §3.4: "On finalize, the line's `processed_weight_kg` is computed as the smaller of the raw `landed_weight_kg` and the product of `landed_weight_kg` multiplied by the assessment's `yield_pct`, by a condition factor, and by a processing factor, the result rounded half up to two decimal places. The condition factor is 1.00 for an assessed `GRADE_A`, 0.97 for `GRADE_B`, and 0.92 for `GRADE_C`; the processing factor is 1.00 when the line's `processing_type` is `WHOLE` and 0.85 when it is `FILLETED`."

        Design: Difficulty/combinatorial_formula/yield_processing_grade_and_processing_interaction
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
        create_and_publish_quote(species["id"], grade="GRADE_B", price_per_kg_cents=950)
        ticket = create_dock_ticket(vessel["id"], area["id"])
        land_ticket(ticket["id"])
        line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                                landed_weight_kg=100.00, processing_type="FILLETED")

        create_and_finalize_assessment(line["id"], assessed_grade="GRADE_B",
                                       yield_pct=0.80)
        line_after = get_success_data(api_client.get_landing_line(line["id"], OM))
        assert_kg(line_after["processed_weight_kg"], 65.96,
                  "100.00 x 0.80 x 0.97 (GRADE_B) x 0.85 (FILLETED)")
        assert line_after["final_amount_cents"] == 62662, "65.96 kg x 950 cents/kg"


def test_processed_weight_rounds_half_up(api):
    """PRD §3.4: "On finalize, the line's `processed_weight_kg` is computed as the smaller of the raw `landed_weight_kg` and the product of `landed_weight_kg` multiplied by the assessment's `yield_pct`, by a condition factor, and by a processing factor, the result rounded half up to two decimal places."
    PRD §2.5: "Weights are expressed in kilograms with exactly two decimal places, rounded half up."

    Design: Corner/calculations/calc_processed_weight_rounding_half_up
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                            landed_weight_kg=33.33)

    create_and_finalize_assessment(line["id"], assessed_grade="GRADE_A",
                                   yield_pct=0.777)
    line_after = get_success_data(api_client.get_landing_line(line["id"], OM))
    assert_kg(line_after["processed_weight_kg"], 25.90,
              "33.33 x 0.777 = 25.89741 rounds half up to 25.90, not 25.89")
    assert line_after["final_amount_cents"] == 31080, "25.90 kg x 1200 cents/kg"


def test_second_active_assessment_on_line_rejected(api):
    """PRD §3.4: "Each line supports only one active assessment: if a `DRAFT` or `FINAL` assessment already exists for the line, the new record is rejected with `ERR_ASSESSMENT_ALREADY_ACTIVE` (409)."

    Design: Corner/state_machines/sm_duplicate_active_assessment_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                            landed_weight_kg=50.00)
    create_assessment(line["id"], assessed_grade="GRADE_A", yield_pct=1.00)

    resp = api_client.create_grade_assessment(
        create_grade_assessment_payload(landing_line_id=line["id"],
                                        assessed_grade="GRADE_B", yield_pct=0.90), GI)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_ALREADY_ACTIVE)

    _, meta = validate_paginated(
        api_client.list_grade_assessments(OM, params={"landing_line_id": line["id"]}))
    assert meta["total_count"] == 1


def test_yield_fraction_bounds(api):
    """PRD §3.4: "The yield fraction must be greater than zero and no more than one; anything outside that range is rejected with `ERR_INVALID_YIELD` (400)."

    Design: Corner/validations/val_yield_outside_range_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                            landed_weight_kg=10.00)

    for bad_yield in (0, 1.01):
        resp = api_client.create_grade_assessment(
            create_grade_assessment_payload(landing_line_id=line["id"],
                                            assessed_grade="GRADE_A",
                                            yield_pct=bad_yield), GI)
        validate_error(resp, ApiErrorId.ERR_INVALID_YIELD)

    ok = api_client.create_grade_assessment(
        create_grade_assessment_payload(landing_line_id=line["id"],
                                        assessed_grade="GRADE_A", yield_pct=1.00), GI)
    data = validate_success(ok, expected_status=201)
    assert data["status"] == "DRAFT", "Exactly 1.00 is inside the permitted range"


def test_ticket_auto_grades_when_last_line_finalizes(api):
    """PRD §3.4: "Back on the ticket, `final_total_cents` — the sum of `final_amount_cents` over lines with a `FINAL` assessment — is recomputed, and when every non-voided line of a ticket holding at least one line has reached a `FINAL` assessment, the ticket itself transitions automatically from `LANDED` to `GRADED`."
    PRD §3.4: "Its `received_weight_kg` is the line's `processed_weight_kg`, its `available_weight_kg` equals the received weight, and every other weight bucket starts at zero; its `unit_cost_cents` is derived per §2.9."

    Design: Corner/state_machines/sm_ticket_auto_grades_when_last_line_final
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    line1 = add_landing_line(ticket["id"], species["id"], landed_weight_kg=50.00)
    line2 = add_landing_line(ticket["id"], species["id"], landed_weight_kg=25.00)
    ga1 = create_assessment(line1["id"], assessed_grade="GRADE_A", yield_pct=1.00)
    ga2 = create_assessment(line2["id"], assessed_grade="GRADE_A", yield_pct=1.00)

    finalize_assessment(ga1["id"])
    assert get_ticket(ticket["id"])["status"] == "LANDED", (
        "One unfinalized line keeps the ticket LANDED")

    finalize_assessment(ga2["id"])
    assert get_ticket(ticket["id"])["status"] == "GRADED", (
        "The last finalize flips the ticket to GRADED")

    lot1 = get_lot_for_line(line1["id"])
    lot2 = get_lot_for_line(line2["id"])
    assert_kg(lot1["received_weight_kg"], 50.00, "lot 1 received")
    assert_kg(lot2["received_weight_kg"], 25.00, "lot 2 received")
    assert_kg(lot1["available_weight_kg"], 50.00, "lot 1 available")
    assert_kg(lot2["available_weight_kg"], 25.00, "lot 2 available")
