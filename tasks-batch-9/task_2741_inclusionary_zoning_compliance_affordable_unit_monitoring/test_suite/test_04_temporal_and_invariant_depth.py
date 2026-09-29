"""Depth coverage for the two interval conventions and the two conserved quantities.

The first half puts a second interval exactly on an existing endpoint, once under
the closed-interval rule and once under the half-open one. The second half reads
a conserved total at every observable point of a compensating cycle.
"""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_fund_inflow_composed,
    assert_fund_money_conserved,
    assert_obligation_equivalents_conserved,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT

RENTAL_UNIT = {
    "bedrooms": 2,
    "sqft": 900,
    "market_comparable_sqft": 1000,
    "tenure": "RENTAL",
    "affordability_level_bps": 5000,
}

TEN_UNIT_PROJECT = {
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-01-15",
}

FEE_PROJECT = {
    "zoning_district": "C-2",
    "total_units": 40,
    "approval_date": "2026-01-15",
}


def build_certified_unit_and_waiting_household() -> dict:
    """One rental unit certified through 2027-08-01 and a second household waiting."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="O-101"),
        project_overrides=dict(TEN_UNIT_PROJECT, name="Overlap Gardens"),
        household_overrides={
            "applicant_name": "Rosa Delgado",
            "household_size": 3,
            "gross_annual_income_cents": 6000000,
        },
        certification_overrides={
            "contract_rent_cents": 140000,
            "effective_date": "2026-08-01",
        },
    )
    ctx["successor_household"] = fixtures.register_household(
        applicant_name="Victor Amaya", household_size=3, gross_annual_income_cents=6000000
    )
    return ctx


def test_a_certification_starting_on_the_incumbents_last_day_collides(
    api, compliance_officer
):
    """Both endpoints are inclusive, so touching the expiry date is an overlap.

    The sitting certification runs through 2027-08-01, and a successor proposing
    to start on that very day is refused rather than being allowed to share the
    day with the tenancy it replaces.

    PRD: "Because both endpoints are inclusive, a new period beginning exactly on an existing period's `expires_at` **is** a collision."

    Design: Difficulty/resource_temporal_overlap/certification_period_touching_endpoint_collides_on_unit
    """
    ctx = build_certified_unit_and_waiting_household()
    assert str(ctx["certification"]["expires_at"]).startswith("2027-08-01")

    response = api.create_certification(
        factories.create_certification_payload(
            ctx["successor_household"]["id"],
            ctx["unit"]["id"],
            contract_rent_cents=140000,
            effective_date="2027-08-01",
        ),
        headers=compliance_officer,
    )

    validate_error(response, "ERR_CERTIFICATION_PERIOD_OVERLAP", 409)
    household = validate_success(
        api.get_household(ctx["successor_household"]["id"], headers=compliance_officer)
    )
    assert household["state"] == "REGISTERED"


def test_a_certification_starting_the_day_after_the_expiry_is_accepted(
    api, compliance_officer
):
    """One day past the incumbent's last day clears the closed-interval scan.

    Moving the successor to 2027-08-02 abuts the sitting period without sharing a
    day with it, so the successor is certified with its own 365-day term while the
    incumbent's certification is left untouched.

    PRD: "The proposed period collides if its start is on or before the existing period's `expires_at` *and* the existing period's `effective_date` is on or before the proposed end; a collision is refused with `ERR_CERTIFICATION_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/certification_period_touching_endpoint_collides_on_unit
    """
    ctx = build_certified_unit_and_waiting_household()
    validate_error(
        api.create_certification(
            factories.create_certification_payload(
                ctx["successor_household"]["id"],
                ctx["unit"]["id"],
                contract_rent_cents=140000,
                effective_date="2027-08-01",
            ),
            headers=compliance_officer,
        ),
        "ERR_CERTIFICATION_PERIOD_OVERLAP",
        409,
    )

    successor = validate_success(
        api.create_certification(
            factories.create_certification_payload(
                ctx["successor_household"]["id"],
                ctx["unit"]["id"],
                contract_rent_cents=140000,
                effective_date="2027-08-02",
            ),
            headers=compliance_officer,
        ),
        201,
    )

    assert successor["state"] == "CERTIFIED"
    assert successor["effective_date"] == "2027-08-02"
    assert str(successor["expires_at"]).startswith("2028-08-01")
    incumbent = validate_success(
        api.get_certification(ctx["certification"]["id"], headers=compliance_officer)
    )
    assert incumbent["state"] == "CERTIFIED"


def build_project_with_first_window(api, developer_headers: dict) -> dict:
    """A screened onsite project carrying one submitted plan for September."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.path_elected_project(
        "ONSITE",
        project_overrides=dict(TEN_UNIT_PROJECT, name="Adjacency Commons"),
        developer_headers=developer_headers,
    )
    ctx["first_plan"] = validate_success(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                ctx["project"]["id"],
                lottery_open_at="2026-09-01T00:00:00Z",
                lottery_close_at="2026-10-01T00:00:00Z",
                preference_categories=["LIVE_WORK", "DISPLACED"],
            ),
            headers=developer_headers,
        ),
        201,
    )
    return ctx


def test_a_window_opening_at_the_instant_the_first_one_closes_is_accepted(
    api, developer
):
    """Half-open windows may touch, because neither half of the scan fires.

    October's window opens at exactly the instant September's closes, which
    satisfies neither strict inequality of the overlap test, so the second plan is
    admitted alongside the first.

    PRD: "Exact adjacency, where the proposed window opens at the very instant an existing window closes, satisfies neither half of that test and is therefore accepted."

    Design: Difficulty/resource_temporal_overlap/marketing_window_exact_adjacency_accepted_on_project
    """
    ctx = build_project_with_first_window(api, developer)
    assert ctx["first_plan"]["state"] == "SUBMITTED"

    second = validate_success(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                ctx["project"]["id"],
                lottery_open_at="2026-10-01T00:00:00Z",
                lottery_close_at="2026-11-01T00:00:00Z",
                preference_categories=["DISPLACED"],
            ),
            headers=developer,
        ),
        201,
    )

    assert second["state"] == "SUBMITTED"
    assert second["lottery_open_at"].startswith("2026-10-01")
    assert second["lottery_close_at"].startswith("2026-11-01")
    assert second["preference_categories"] == ["DISPLACED"]
    assert second["revision_round"] == 0


def test_a_window_enclosed_by_a_live_one_is_refused(api, developer, compliance_officer):
    """A window strictly inside a live window trips both halves of the scan.

    Five days in the middle of September overlap the live September plan on both
    sides, so the third submission is refused and the project is left holding
    exactly the two plans that do not overlap.

    PRD: "Scan every other plan of that project whose `state` is `SUBMITTED`, `APPROVED` or `REVISION_REQUESTED` — a `CLOSED` plan releases its window — and reject with `ERR_MARKETING_WINDOW_OVERLAP` if the proposed `lottery_open_at` is strictly earlier than that plan's `lottery_close_at` *and* that plan's `lottery_open_at` is strictly earlier than the proposed `lottery_close_at`."

    Design: Difficulty/resource_temporal_overlap/marketing_window_exact_adjacency_accepted_on_project
    """
    ctx = build_project_with_first_window(api, developer)
    validate_success(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                ctx["project"]["id"],
                lottery_open_at="2026-10-01T00:00:00Z",
                lottery_close_at="2026-11-01T00:00:00Z",
                preference_categories=["DISPLACED"],
            ),
            headers=developer,
        ),
        201,
    )

    response = api.create_marketing_plan(
        factories.create_marketing_plan_payload(
            ctx["project"]["id"],
            lottery_open_at="2026-09-15T00:00:00Z",
            lottery_close_at="2026-09-20T00:00:00Z",
            preference_categories=["PUBLIC_EMPLOYEE"],
        ),
        headers=developer,
    )

    validate_error(response, "ERR_MARKETING_WINDOW_OVERLAP", 409)
    plans, meta = validate_paginated(
        api.list_marketing_plans(project_id=ctx["project"]["id"], headers=compliance_officer)
    )
    assert meta["total_count"] == 2
    assert sorted(plan["lottery_open_at"][:10] for plan in plans) == [
        "2026-09-01",
        "2026-10-01",
    ]


def build_funded_fund(api, admin_headers: dict, developer_headers: dict) -> dict:
    """One C-2 development on the fee path with its whole assessment settled."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.fee_path_project(
        project_overrides=dict(FEE_PROJECT, name="Ledgerworks")
    )
    ctx["fee"] = validate_success(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(
                ctx["project"]["id"], ctx["project"]["version"], basis="FULL"
            ),
            headers=admin_headers,
        ),
        201,
    )
    ctx["fee"] = validate_success(
        api.pay_in_lieu_fee(
            ctx["fee"]["id"], ctx["fee"]["assessed_amount_cents"], headers=developer_headers
        )
    )
    return ctx


def test_disbursing_a_draw_moves_cents_between_buckets_without_touching_unencumbered(
    api, program_admin, developer
):
    """Encumbering and then disbursing shifts buckets, never the free balance.

    189120000 cents of settled fee sit unencumbered; requesting 5000000 pulls them
    into the encumbered bucket, and disbursing that same draw carries them on to
    the disbursed bucket while the unencumbered balance holds at 184120000
    throughout, with the three buckets summing to the inflow at every reading.

    PRD: "Requesting a draw moves cents from unencumbered to encumbered; disbursing that draw moves the same cents from encumbered to disbursed and leaves the unencumbered balance untouched; voiding a draw from either state returns the cents, so the unencumbered balance comes back to exactly its pre-request value."

    Design: Difficulty/compensating_invariant/void_disbursed_draw_restores_fund_money_conservation_exactly
    """
    ctx = build_funded_fund(api, program_admin, developer)
    assert ctx["fee"]["state"] == "PAID"
    assert ctx["fee"]["assessed_amount_cents"] == 189120000

    before = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert_fund_money_conserved(before)
    assert_fund_inflow_composed(before)
    assert before["total_inflow_cents"] == 189120000
    assert before["encumbered_cents"] == 0
    assert before["disbursed_cents"] == 0
    assert before["unencumbered_balance_cents"] == 189120000
    assert before["admin_cap_cents"] == 18912000
    assert before["admin_committed_cents"] == 0

    draw = validate_success(
        api.create_disbursement(
            factories.create_disbursement_payload(ctx["fee"]["id"], 5000000),
            headers=program_admin,
        ),
        201,
    )
    requested = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert_fund_money_conserved(requested)
    assert requested["encumbered_cents"] == 5000000
    assert requested["disbursed_cents"] == 0
    assert requested["unencumbered_balance_cents"] == 184120000

    validate_success(api.disburse(draw["id"], headers=program_admin))

    disbursed = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert_fund_money_conserved(disbursed)
    assert disbursed["encumbered_cents"] == 0
    assert disbursed["disbursed_cents"] == 5000000
    assert disbursed["unencumbered_balance_cents"] == 184120000
    assert disbursed["total_inflow_cents"] == 189120000


def test_voiding_a_disbursed_draw_returns_the_fund_to_its_pre_request_reading(
    api, program_admin, developer
):
    """The unwind of an already-disbursed draw is exact, not approximate.

    After the draw has been requested and disbursed, voiding it takes the 5000000
    cents back out of the disbursed bucket, so the unencumbered balance returns to
    exactly the 189120000 it read before the request while the voided draw keeps
    the amount it once carried.

    PRD: "A void from either state removes the cents from whichever bucket held them, so `unencumbered_balance_cents` returns to exactly its pre-request value and `admin_committed_cents` returns to exactly its pre-request value too."

    PRD: "Draws in `state` `VOIDED` contribute nothing to any of these figures."

    Design: Difficulty/compensating_invariant/void_disbursed_draw_restores_fund_money_conservation_exactly
    """
    ctx = build_funded_fund(api, program_admin, developer)
    draw = validate_success(
        api.create_disbursement(
            factories.create_disbursement_payload(ctx["fee"]["id"], 5000000),
            headers=program_admin,
        ),
        201,
    )
    validate_success(api.disburse(draw["id"], headers=program_admin))

    voided = validate_success(
        api.void_disbursement(
            draw["id"], "Grantee withdrew before construction started.",
            headers=program_admin,
        )
    )

    assert voided["state"] == "VOIDED"
    assert voided["amount_cents"] == 5000000
    after = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert_fund_money_conserved(after)
    assert_fund_inflow_composed(after)
    assert after["encumbered_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["unencumbered_balance_cents"] == 189120000
    assert after["total_inflow_cents"] == 189120000
    assert after["admin_committed_cents"] == 0
    fee = validate_success(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))
    assert fee["state"] == "PAID"


def build_planned_onsite_unit() -> dict:
    """A ten-unit R-2 development whose single obligation is met by one unit."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    return fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="BC-101"),
        project_overrides=dict(TEN_UNIT_PROJECT, name="Balance Court"),
    )


def test_withdrawing_the_unit_moves_ten_thousand_basis_points_across_the_two_terms(
    api, developer, program_admin
):
    """Losing the dwelling shifts the obligation from bricks to money, not away.

    Before the withdrawal the whole 10000-basis-point obligation sits in the onsite
    term; afterwards the onsite term is empty and the cascaded substitution
    assessment carries the identical 10000 basis points in the fee term, so the sum
    still equals the obligation exactly.

    PRD: "Withdrawing a unit removes 10000 basis points from the onsite term and the cascaded substitution assessment adds exactly 10000 basis points to the fee term; reinstating the unit adds 10000 back to the onsite term and supersedes that assessment, removing 10000 from the fee term."

    Design: Difficulty/compensating_invariant/withdraw_reinstate_cycle_restores_unit_equivalents_exactly
    """
    ctx = build_planned_onsite_unit()
    before = ctx["project"]
    assert_obligation_equivalents_conserved(before)
    assert before["total_obligation_bps"] == 10000
    assert before["onsite_unit_equivalents_bps"] == 10000
    assert before["fee_covered_equivalents_bps"] == 0
    assert before["compliance_posture"] == "COMPLIANT_ONSITE"

    validate_success(
        api.withdraw_unit(
            ctx["unit"]["id"], "The stacked flat came out of the redesign.",
            headers=developer,
        )
    )

    after = fixtures.live_project(ctx["project"]["id"])
    assert_obligation_equivalents_conserved(after)
    assert after["total_obligation_bps"] == 10000
    assert after["onsite_unit_equivalents_bps"] == 0
    assert after["fee_covered_equivalents_bps"] == 10000
    assert after["compliance_posture"] == "COMPLIANT_BY_FEE"
    fees, meta = validate_paginated(
        api.list_in_lieu_fees(project_id=ctx["project"]["id"], headers=program_admin)
    )
    assert meta["total_count"] == 1
    assert fees[0]["basis"] == "SUBSTITUTION"
    assert fees[0]["state"] == "ASSESSED"
    assert fees[0]["assessed_amount_cents"] == 24467400
    assert fees[0]["paid_amount_cents"] == 0


def test_reinstating_the_unit_restores_both_terms_to_their_opening_readings(
    api, developer, program_admin
):
    """The compensating action unwinds the assessment rather than paying it.

    Reinstatement returns the 10000 basis points to the onsite term and takes the
    same 10000 out of the fee term by superseding the substitution assessment with
    no replacement, leaving the project reading exactly as it did before the
    withdrawal and the fund still holding nothing.

    PRD: "Ten thousand basis points return to the onsite term and ten thousand leave the fee term, restoring the sum exactly."

    PRD: "The selected assessment transitions to `SUPERSEDED` with its `superseded_by_fee_id` left null — there is no replacement assessment, this is an unwind — and its `version` increments."

    Design: Difficulty/compensating_invariant/withdraw_reinstate_cycle_restores_unit_equivalents_exactly
    """
    ctx = build_planned_onsite_unit()
    opening = ctx["project"]
    validate_success(
        api.withdraw_unit(
            ctx["unit"]["id"], "The stacked flat came out of the redesign.",
            headers=developer,
        )
    )
    substitution = validate_paginated(
        api.list_in_lieu_fees(project_id=ctx["project"]["id"], headers=program_admin)
    )[0][0]

    unit = validate_success(api.reinstate_unit(ctx["unit"]["id"], headers=developer))

    assert unit["occupancy_status"] == "PLANNED"
    assert unit["withdrawn_reason"] is None
    closing = fixtures.live_project(ctx["project"]["id"])
    assert_obligation_equivalents_conserved(closing)
    assert closing["onsite_unit_equivalents_bps"] == opening["onsite_unit_equivalents_bps"]
    assert closing["fee_covered_equivalents_bps"] == opening["fee_covered_equivalents_bps"]
    assert closing["total_obligation_bps"] == opening["total_obligation_bps"]
    assert closing["required_affordable_units"] == opening["required_affordable_units"]
    assert closing["compliance_posture"] == "COMPLIANT_ONSITE"
    fee = validate_success(api.get_in_lieu_fee(substitution["id"], headers=program_admin))
    assert fee["state"] == "SUPERSEDED"
    assert fee["superseded_by_fee_id"] is None
    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["total_paid_fees_cents"] == 0
    assert summary["total_inflow_cents"] == 0
    assert_fund_money_conserved(summary)
