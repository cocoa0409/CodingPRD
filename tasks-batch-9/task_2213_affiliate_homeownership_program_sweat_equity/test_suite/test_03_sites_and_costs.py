"""Build sites, the readiness ladder, and the append-only construction cost ledger."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, CREW_LEAD


def test_the_cash_basis_hides_the_donation_the_full_fair_market_basis_shows(api):
    """One ledger, two bases, a 750,000-cent spread from a single donated row.

    "The **cash basis** is the site's `acquisition_cost_cents` plus the sum of
    `amount_cents` over that site's `RECORDED` lines that are not in-kind.
    Donated value is the sum of `fair_market_value_cents` over that site's
    `RECORDED` in-kind lines, and the **full fair-market basis** — stored as
    `total_development_cost_cents` — is the cash basis plus that donated value."

    With a 4,000,000-cent lot and one 1,000,000-cent cash materials line both
    bases read 5,000,000; appending a 750,000-cent donation moves only the full
    fair-market basis, and "at the program level, `donated_material_fmv_cents` is
    the donated value summed across every site of the program".

    Design: Difficulty/dual_variant_calc/development_cost_cash_basis_vs_full_fmv_basis
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])
    X.add_cash_cost(api, site["id"], amount_cents=1_000_000, category=C.COST_CATEGORY_MATERIALS)

    before = validate_success(api.get_build_site(site["id"], headers=CREW_LEAD))
    assert before["cash_cost_cents"] == 5_000_000
    assert before["total_development_cost_cents"] == 5_000_000

    donation = validate_success(
        api.create_cost_entry(
            F.in_kind_cost_payload(
                site["id"],
                fair_market_value_cents=750_000,
                category=C.COST_CATEGORY_MATERIALS,
                donor_name="Cedar Lumber Co",
            ),
            headers=CREW_LEAD,
        ),
        201,
    )

    assert donation["status"] == C.COST_RECORDED
    assert donation["amount_cents"] == 0

    after = validate_success(api.get_build_site(site["id"], headers=CREW_LEAD))
    assert after["cash_cost_cents"] == 5_000_000
    assert after["total_development_cost_cents"] == 5_750_000
    assert after["total_development_cost_cents"] - after["cash_cost_cents"] == 750_000

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["donated_material_fmv_cents"] == 750_000


def test_the_donated_line_is_the_only_source_of_the_spread_between_the_bases(api):
    """A cash-only ledger keeps the two bases identical to the cent.

    "Because the two bases are computed from the same set of lines, the full
    fair-market basis is strictly larger than the cash basis whenever any
    recorded in-kind line exists." The contrapositive is the switch delta this
    test pins: with no in-kind line at all the spread is exactly zero and the
    program's donated total stays at its identity value, so the 750,000-cent
    difference of the other variant is attributable to the donation alone.

    Design: Difficulty/dual_variant_calc/development_cost_cash_basis_vs_full_fmv_basis
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])

    X.add_cash_cost(api, site["id"], amount_cents=1_000_000, category=C.COST_CATEGORY_MATERIALS)
    X.add_cash_cost(api, site["id"], amount_cents=750_000, category=C.COST_CATEGORY_LABOR)

    reread = validate_success(api.get_build_site(site["id"], headers=CREW_LEAD))
    # The same 750,000 cents, spent as cash instead of donated, lands on both bases.
    assert reread["cash_cost_cents"] == 5_750_000
    assert reread["total_development_cost_cents"] == 5_750_000
    assert reread["total_development_cost_cents"] - reread["cash_cost_cents"] == 0

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["donated_material_fmv_cents"] == 0


def test_a_voided_donation_survives_as_a_row_while_both_bases_fall_back(api):
    """Voiding is not deletion, and a cost line has neither version nor updated_at.

    "A cost entry is append-only: it carries `id` and `created_at` only, and has
    neither `updated_at` nor `version`." Its only mutation is the void: "a
    `void_reason` moves the line `RECORDED → VOIDED`, and the row itself is never
    removed", while "voided lines leave both bases entirely".

    Design: Corner/entities/cost_entry_ledger_is_append_only_and_void_preserves_the_row
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])
    cash_entry = X.add_cash_cost(api, site["id"], amount_cents=1_000_000, category=C.COST_CATEGORY_MATERIALS)
    donation = X.add_in_kind_cost(api, site["id"], fair_market_value_cents=750_000)

    read_back = validate_success(api.get_cost_entry(cash_entry["id"], headers=ADMIN))
    assert read_back["id"] == cash_entry["id"]
    assert read_back["created_at"]
    assert "version" not in read_back
    assert "updated_at" not in read_back

    voided = validate_success(api.void_cost_entry(donation["id"], F.void_payload(), headers=CREW_LEAD))
    assert voided["id"] == donation["id"]
    assert voided["status"] == C.COST_VOIDED
    # The money is preserved on the row; only the status moved.
    assert voided["fair_market_value_cents"] == 750_000

    _, meta = validate_paginated(api.list_cost_entries({"build_site_id": site["id"]}, headers=ADMIN))
    assert meta["total_count"] == 2

    reread_site = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert reread_site["cash_cost_cents"] == 5_000_000
    assert reread_site["total_development_cost_cents"] == 5_000_000

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["donated_material_fmv_cents"] == 0


def test_the_in_kind_flag_decides_which_money_field_is_mandatory(api):
    """One boolean flips which of the two money fields must be zero.

    "A cash line must carry a positive `amount_cents` and a
    `fair_market_value_cents` of 0; an in-kind line must carry an `amount_cents`
    of 0, a positive `fair_market_value_cents` documenting the donation, and a
    `donor_name` of record (1 to 120 characters). Any other combination is
    refused with `ERR_IN_KIND_AMOUNT_MISMATCH`."

    Design: Corner/validations/in_kind_and_cash_cost_entry_field_pairs_are_enforced
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])

    validate_error(
        api.create_cost_entry(
            {
                "build_site_id": site["id"],
                "category": C.COST_CATEGORY_MATERIALS,
                "is_in_kind": True,
                "amount_cents": 500_000,
                "fair_market_value_cents": 0,
                "donor_name": "Cedar Lumber Co",
            },
            headers=CREW_LEAD,
        ),
        E.ERR_IN_KIND_AMOUNT_MISMATCH,
        422,
    )
    validate_error(
        api.create_cost_entry(
            {
                "build_site_id": site["id"],
                "category": C.COST_CATEGORY_MATERIALS,
                "is_in_kind": True,
                "amount_cents": 0,
                "fair_market_value_cents": 250_000,
            },
            headers=CREW_LEAD,
        ),
        E.ERR_IN_KIND_AMOUNT_MISMATCH,
        422,
    )
    validate_error(
        api.create_cost_entry(
            {
                "build_site_id": site["id"],
                "category": C.COST_CATEGORY_LABOR,
                "is_in_kind": False,
                "amount_cents": 0,
                "fair_market_value_cents": 250_000,
            },
            headers=CREW_LEAD,
        ),
        E.ERR_IN_KIND_AMOUNT_MISMATCH,
        422,
    )

    gift = validate_success(
        api.create_cost_entry(
            {
                "build_site_id": site["id"],
                "category": C.COST_CATEGORY_MATERIALS,
                "is_in_kind": True,
                "amount_cents": 0,
                "fair_market_value_cents": 250_000,
                "donor_name": "Cedar Lumber Co",
            },
            headers=CREW_LEAD,
        ),
        201,
    )
    assert gift["status"] == C.COST_RECORDED
    assert gift["fair_market_value_cents"] == 250_000
    assert gift["amount_cents"] == 0

    cash = validate_success(
        api.create_cost_entry(
            {
                "build_site_id": site["id"],
                "category": C.COST_CATEGORY_LABOR,
                "is_in_kind": False,
                "amount_cents": 500_000,
                "fair_market_value_cents": 0,
            },
            headers=CREW_LEAD,
        ),
        201,
    )
    assert cash["status"] == C.COST_RECORDED
    assert cash["amount_cents"] == 500_000
    assert cash["fair_market_value_cents"] == 0

    # The three refusals appended nothing to the append-only ledger.
    _, meta = validate_paginated(api.list_cost_entries({"build_site_id": site["id"]}, headers=ADMIN))
    assert meta["total_count"] == 2

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["donated_material_fmv_cents"] == 250_000


def test_each_readiness_step_flips_one_flag_and_refuses_to_go_out_of_order(api):
    """The ladder is walked one documented rung at a time, in order.

    "A `step` of `TITLE` moves the site `RAW_LAND → TITLE_CLEAR` and sets
    `title_cleared`, and is only available while `title_cleared` is still false. A
    `step` of `ENVIRONMENTAL` moves it `TITLE_CLEAR → ENV_CLEARED` and sets
    `environmental_cleared`. A `step` of `UTILITIES` moves it `ENV_CLEARED →
    READY_TO_BUILD` and sets `utilities_cleared`, and requires that both
    `title_cleared` and `environmental_cleared` are already true."

    A step whose origin state is wrong fails the tenth precondition: "The
    addressed row is in a state the requested transition declares as a legal
    origin for the dimension being moved — `ERR_TRANSITION_NOT_ALLOWED` (409)."
    `FINAL_INSPECTION` is no shortcut either, since it "closes the build, moving
    the site `UNDER_CONSTRUCTION → COMPLETED`".

    Design: Corner/state_machines/site_readiness_ladder_advances_one_documented_step_at_a_time
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])

    validate_error(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_UTILITIES), headers=ADMIN),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )
    still_raw = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert still_raw["readiness_status"] == C.SITE_RAW_LAND
    assert still_raw["utilities_cleared"] is False

    titled = validate_success(api.advance_readiness(site["id"], F.readiness_payload(C.STEP_TITLE), headers=ADMIN))
    assert titled["readiness_status"] == C.SITE_TITLE_CLEAR
    assert titled["title_cleared"] is True
    assert titled["environmental_cleared"] is False
    assert titled["utilities_cleared"] is False

    validate_error(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_FINAL_INSPECTION), headers=CREW_LEAD),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )

    cleared = validate_success(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_ENVIRONMENTAL), headers=ADMIN)
    )
    assert cleared["readiness_status"] == C.SITE_ENV_CLEARED
    assert cleared["title_cleared"] is True
    assert cleared["environmental_cleared"] is True
    assert cleared["utilities_cleared"] is False

    ready = validate_success(api.advance_readiness(site["id"], F.readiness_payload(C.STEP_UTILITIES), headers=ADMIN))
    assert ready["readiness_status"] == C.SITE_READY_TO_BUILD
    assert ready["title_cleared"] is True
    assert ready["environmental_cleared"] is True
    assert ready["utilities_cleared"] is True
    assert ready["safety_posture"] == C.POSTURE_CLEAR
    assert ready["assigned_household_id"] is None
