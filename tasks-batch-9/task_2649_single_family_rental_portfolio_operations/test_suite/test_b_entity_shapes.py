"""What the catalogue rows look like the instant they are created or revised.

Every field a client supplies must survive verbatim, every field the PRD declares as a
default must appear at that default rather than as null, and every derived figure must be
computed at creation time -- including on a PATCH that tries to overwrite it.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    assert_version,
    created,
    ok,
)
from test_helpers.constants import (
    ASSET_PIPELINE,
    CLOCK_AUG_01,
    FRAUD_VARIANT_PRE,
    IDENTITY_UNVERIFIED,
    OCC_VACANT,
    POSTURE_RESTRICTED,
    WO_PENDING_DISPATCH,
)


def test_market_creation_stores_all_twenty_four_policy_fields_verbatim(api):
    """The registered market reads back every declared policy dial at version 1.

    PRD SS3.1: "Before any home can be underwritten, a `PortfolioAdmin` registers the market
    whose policy will govern it, supplying every field described in the market policy section
    above."  PRD SS2.10 declares those dials, among them "`millage_bps` is the annual
    property-tax rate in basis points of a home's assessed value", "`cost_index_bps` is the
    market cost multiplier applied to national scope benchmarks", "`restricted_breeds` is an
    array of uppercase breed tokens the market forbids" and "`disposition_yield_floor_bps` is
    the realized-yield line below which a home is flagged for disposition review".  PRD SS2.4:
    `version` is "an integer that starts at 1 when the row is created".

    Design: Corner/entities/market_creation_persists_every_policy_field
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = created(api.create_market(f.market_payload(), x.ADMIN))
    assert_fields(
        market,
        code="ATL",
        name="Atlanta",
        tax_jurisdiction_code="GA-FULTON",
        millage_bps=125,
        cost_index_bps=10250,
        cost_variance_tolerance_bps=1000,
        make_ready_target_days=30,
        turn_holdback_cap_bps=1500,
        showing_buffer_minutes=30,
        min_showing_duration_minutes=30,
        max_pets=2,
        restricted_breeds=["PIT_BULL", "ROTTWEILER"],
        standard_lease_term_months=12,
        fraud_block_threshold_bps=6000,
        rent_to_income_max_bps=4000,
        vacancy_loss_bps=500,
        bad_debt_bps=100,
        mgmt_fee_bps=800,
        underwriting_yield_floor_bps=500,
        disposition_yield_floor_bps=540,
        max_rent_concession_bps=500,
    )
    assert_money_group(
        market,
        rent_index_cents=210000,
        pet_deposit_per_pet_cents=30000,
        pet_deposit_cap_cents=50000,
    )
    assert_version(market, 1)


def test_a_new_home_reads_back_its_initial_dimensions_and_derived_figures(api):
    """One GET pins both dimensions, the derived tax, the derived posture and the zeroes.

    PRD SS3.1: "A newly registered home starts with `asset_status` `PIPELINE`,
    `occupancy_status` `VACANT`, `booked_showing_count` 0, `disposition_mode` `NONE`,
    `lot_code` the empty string, `bpo_value_cents` 0, `net_sale_proceeds_cents` 0,
    `realized_gain_cents` 0, `hold_sell_score_bps` 0 and `disposition_flagged` false. Its
    `property_tax_annual_cents` is computed immediately as the home's `assessed_value_cents`
    multiplied by the market's `millage_bps`, divided by 10,000 and rounded half up ... Its
    `leasing_posture` is derived at once, which for a pipeline home with a live binder and no
    blocking obligation yields `RESTRICTED`."

    Design: Corner/entities/home_retrieval_returns_stored_and_derived_fields
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home_id = x.create_home(api, market["id"])["id"]

    home = ok(api.get_home(home_id, x.OPS))
    assert_fields(
        home,
        market_id=market["id"],
        address_line1="118 Peachtree Way",
        asset_status=ASSET_PIPELINE,
        occupancy_status=OCC_VACANT,
        leasing_posture=POSTURE_RESTRICTED,
        booked_showing_count=0,
        disposition_mode="NONE",
        disposition_flagged=False,
    )
    assert_money_group(
        home,
        assessed_value_cents=28000000,
        asking_rent_cents=215000,
        property_tax_annual_cents=350000,
        bpo_value_cents=0,
        net_sale_proceeds_cents=0,
        realized_gain_cents=0,
    )
    assert_absent_or_empty(home, "lot_code")
    # The design index expects ``hold_sell_score_bps`` to read as null before any APPROVED
    # case exists, but the PRD states both that a new home "starts with ...
    # `hold_sell_score_bps` 0" (SS3.1) and that "it is null while the home has no `APPROVED`
    # case at all" (SS3.2), so the initial value of that one field is not uniquely derivable
    # and is left unasserted here.
    assert_version(home, 1)


def test_property_tax_rounds_half_up_on_the_exact_half_cent(api):
    """28000000 gives exactly 350000; 28000040 gives 350000.5 and must round up.

    PRD SS3.1: a home's `property_tax_annual_cents` "is computed immediately as the home's
    `assessed_value_cents` multiplied by the market's `millage_bps`, divided by 10,000 and
    rounded half up".  PRD SS2.5: "Wherever a computation divides, the result is rounded
    **half up** to the nearest whole unit -- whole cents for money, whole basis points for
    rates. There is exactly one rounding convention in this system and no computation ever
    truncates."

    Design: Corner/entities/home_property_tax_is_derived_with_round_half_up
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)

    exact = created(api.create_home(f.home_payload(market["id"]), x.ANALYST))
    half = created(
        api.create_home(
            f.home_payload(
                market["id"],
                address_line1="119 Peachtree Way",
                assessed_value_cents=28000040,
            ),
            x.ANALYST,
        )
    )
    assert_money_group(exact, property_tax_annual_cents=350000)
    assert_money_group(
        half, assessed_value_cents=28000040, property_tax_annual_cents=350001
    )


def test_prospect_registration_manufactures_its_identity_and_audit_fields(api):
    """Seven inputs in; the identity dimension, the variant and the 4850 score come back.

    PRD SS3.6: "Nothing has been proven at this point, so a new prospect is created with
    `identity_status` `UNVERIFIED`, `verification_attempt_count` 0,
    `verified_monthly_income_cents` 0, `document_type` `NONE`, `document_match_score_bps` 0,
    `selfie_liveness_pass` false, `device_reputation_bps` 0 and `ip_geo_distance_km` 0. Its
    `fraud_risk_score_bps` is nevertheless computed immediately, by the pre-verification
    variant described below, and `fraud_score_variant` is stamped `PRE_VERIFICATION`."  PRD
    SS3.6 scores exactly this prospect: "A prospect declaring 700000 with credit `B` and no
    evictions scores identity 10000, income 0 ... history 1500 and device 7000, which weighs
    out to 35000000 plus 0 plus 3000000 plus 10500000, or 48500000, and after the single final
    division 4850 basis points."  PRD SS2.4: every resource carries a server-minted `id`,
    "`created_at`, an ISO 8601 UTC timestamp ... fixed at creation" and an `updated_at`.

    Design: Corner/entities/prospect_identity_and_audit_fields_are_server_generated
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)

    prospect = created(api.create_prospect(f.prospect_payload(market["id"]), x.ANON))
    assert_fields(
        prospect,
        identity_status=IDENTITY_UNVERIFIED,
        fraud_score_variant=FRAUD_VARIANT_PRE,
        fraud_risk_score_bps=4850,
        verification_attempt_count=0,
        document_type="NONE",
        document_match_score_bps=0,
        selfie_liveness_pass=False,
        device_reputation_bps=0,
        ip_geo_distance_km=0,
    )
    assert_money_group(prospect, verified_monthly_income_cents=0)
    assert_version(prospect, 1)
    for field in ("id", "created_at", "updated_at"):
        assert prospect.get(field), "expected server-generated {!r}".format(field)


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """No HOA pair means "" and 0; no project_id means "" -- and nothing stops computing.

    PRD SS3.1: a home carries "the optional pair `hoa_name`, which defaults to the empty
    string when the home sits in no association, and `hoa_annual_cents`, which defaults to
    0."  PRD SS3.3: "`project_id` is optional: standalone resident-maintenance work that is
    not part of any project leaves it as the empty string".  PRD SS3.3 on the same row: "A new
    work order is created in `PENDING_DISPATCH` with `vendor_id` the empty string,
    `actual_cost_cents` 0, `completed_on` the empty string and `void_reason` the empty string.
    Two figures are computed at creation. `benchmark_total_cents` is the single-line benchmark
    for this work order's scope and quantity ... `variance_bps` is then the quoted cost less
    that benchmark, multiplied by 10,000, divided by the benchmark and rounded half up ...
    `crew_days` ... equals `crew_size` multiplied by the number of whole days in the window
    counted inclusively at both ends."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    bare = created(
        api.create_home(
            f.home_payload(
                market["id"],
                address_line1="440 Boulevard NE",
                postal_code="30312",
                square_feet=1500,
                year_built=1990,
                assessed_value_cents=22000000,
                asking_rent_cents=185000,
                insurance_annual_premium_cents=160000,
                hoa_name=None,
                hoa_annual_cents=None,
            ),
            x.ANALYST,
        )
    )
    assert_absent_or_empty(bare, "hoa_name")
    assert_money_group(
        bare, hoa_annual_cents=0, property_tax_annual_cents=275000
    )

    order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                crew_size=2,
                scheduled_end_date="2026-08-11",
            ),
            x.OPS,
        )
    )
    assert_absent_or_empty(order, "project_id")
    assert_absent_or_empty(order, "vendor_id")
    assert_absent_or_empty(order, "completed_on")
    assert_absent_or_empty(order, "void_reason")
    assert_fields(
        order, status=WO_PENDING_DISPATCH, crew_days=4, variance_bps=268
    )
    assert_money_group(order, actual_cost_cents=0, benchmark_total_cents=292176)


def test_patching_a_home_ignores_state_dimensions_and_recomputes_the_tax(api):
    """The revision writes the two mutable figures and drops asset_status and the tax input.

    PRD SS3.1: "The mutable facts of a home can be revised later by an `AcquisitionAnalyst` or
    `PortfolioAdmin`: `asking_rent_cents`, `assessed_value_cents`, `insurance_carrier_name`,
    `insurance_annual_premium_cents`, `insurance_binder_expires_on`, `hoa_name` and
    `hoa_annual_cents` are each optional in that payload and only the supplied fields are
    overwritten. Neither state dimension nor any computed field may be written this way;
    `asset_status`, `occupancy_status` and every derived figure are ignored if a client sends
    them. Revising `assessed_value_cents` recomputes `property_tax_annual_cents`. ... Either
    way the home's `version` increments by 1."

    Design: Corner/entities/patch_home_extra_field_asset_status_input_ignored
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    assert_money_group(home, property_tax_annual_cents=350000)

    revised = ok(
        api.patch_home(
            home["id"],
            {
                "assessed_value_cents": 24800000,
                "asking_rent_cents": 220000,
                "asset_status": "STABILIZED",
                "property_tax_annual_cents": 1,
                "occupancy_status": "OCCUPIED",
            },
            x.ANALYST,
        )
    )
    assert_money_group(
        revised,
        assessed_value_cents=24800000,
        asking_rent_cents=220000,
        property_tax_annual_cents=310000,
    )
    assert_fields(revised, asset_status=ASSET_PIPELINE, occupancy_status=OCC_VACANT)
    assert_version(revised, 2)
    stored = ok(api.get_home(home["id"], x.ANALYST))
    assert_fields(stored, asset_status=ASSET_PIPELINE, occupancy_status=OCC_VACANT)
