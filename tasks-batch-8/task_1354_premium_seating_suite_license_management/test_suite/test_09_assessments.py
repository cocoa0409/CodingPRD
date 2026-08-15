"""Amenity/renovation assessments: share allocation variants and the levy gate."""
from test_helpers import (
    FIN, REP,
    ApiClient, ApiErrorId,
    get_single_invoice, make_approved_assessment, make_suite, make_venue,
    setup_three_licensed_suites, validate_error, validate_paginated, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


def _assessment_invoice(api: ApiClient, agreement_id):
    return get_single_invoice({"agreement_id": agreement_id, "invoice_type": "ASSESSMENT"})


class TestAssessmentAllocation:
    def test_assessment_equal_split_remainder_by_created_order(self, api: ApiClient):
        """PRD §3.11: "Under `PER_SUITE_EQUAL`, every share is the whole-cent floor of
        the total divided by the number of eligible suites, and the leftover cents —
        the total minus the sum of those floored shares — are distributed one cent each
        to the earliest-created suites until exhausted."
        Design: Corner/calculations/assessment_equal_split_remainder_by_created_order
        """
        s = setup_three_licensed_suites(allocation_method="PER_SUITE_EQUAL")
        validate_success(api.levy_assessment(s["assessment"]["id"], FIN))
        gold = _assessment_invoice(api, s["agreements"][0]["id"])
        silver = _assessment_invoice(api, s["agreements"][1]["id"])
        plat = _assessment_invoice(api, s["agreements"][2]["id"])
        assert gold["subtotal_cents"] == 333334, (
            "earliest-created suite receives the 1-cent remainder of floor(1000000/3)")
        assert silver["subtotal_cents"] == 333333
        assert plat["subtotal_cents"] == 333333
        total = gold["subtotal_cents"] + silver["subtotal_cents"] + plat["subtotal_cents"]
        assert total == 1000000
        assert validate_success(api.get_assessment(s["assessment"]["id"], FIN))["status"] == "LEVIED"
        for inv in (gold, silver, plat):
            assert inv["status"] == "ISSUED"
            assert inv["due_on"].startswith("2026-09-30T00:00:00"), (
                "ASSESSMENT invoices are due sixty days after the 2026-08-01 levy clock")

    def test_assessment_by_seat_largest_fractional_remainder(self, api: ApiClient):
        """PRD §3.11: "Under `BY_SEAT`, each suite's raw share is the total cost
        multiplied by its `capacity_seats` divided by the sum of `capacity_seats`
        across all eligible suites; the share is the whole-cent floor of that raw
        figure, and the leftover cents are distributed one cent each in descending
        order of fractional part — the raw share minus its floor — with ties broken by
        earlier suite `created_at`."
        Design: Corner/calculations/assessment_by_seat_largest_fractional_remainder
        """
        s = setup_three_licensed_suites(allocation_method="BY_SEAT")
        validate_success(api.levy_assessment(s["assessment"]["id"], FIN))
        gold = _assessment_invoice(api, s["agreements"][0]["id"])    # 20 seats
        silver = _assessment_invoice(api, s["agreements"][1]["id"])  # 10 seats
        plat = _assessment_invoice(api, s["agreements"][2]["id"])    # 12 seats
        assert gold["subtotal_cents"] == 476191, "floor 476190 + largest fraction (.476)"
        assert silver["subtotal_cents"] == 238095
        assert plat["subtotal_cents"] == 285714
        assert gold["subtotal_cents"] + silver["subtotal_cents"] + plat["subtotal_cents"] == 1000000

    def test_assessment_levy_without_licensed_suites_rejected(self, api: ApiClient):
        """PRD §3.11: "Levying — the `APPROVED` to `LEVIED` step, reserved to
        `FinanceController` and `StadiumAdmin` — requires at least one suite of the
        venue currently `LICENSED`, else `ERR_NO_LICENSED_SUITES`."
        Design: Corner/validations/assessment_levy_without_licensed_suites_rejected
        """
        venue = make_venue()
        make_suite(venue["id"], **GOLD_SUITE)  # stays AVAILABLE
        asm = make_approved_assessment(venue["id"])
        resp = api.levy_assessment(asm["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_NO_LICENSED_SUITES)
        assert validate_success(api.get_assessment(asm["id"], FIN))["status"] == "APPROVED"
        rows = validate_paginated(api.list_invoices(FIN, params={"assessment_id": asm["id"]}))[0]
        assert rows == [], "a rejected levy must create zero ASSESSMENT invoices"
