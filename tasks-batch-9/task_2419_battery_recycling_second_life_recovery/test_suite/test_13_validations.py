"""Field rules, cross-entity link rules and the order the tiers are evaluated in."""
from test_helpers import (
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_INTAKE, CLOCK_PROCESS

_JULY_NICKEL = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600}
]
_PROCESS_WINDOW = {
    "window_start": "2026-08-20T00:00:00.000Z",
    "window_end": "2026-08-21T00:00:00.000Z",
    "planned_input_kg": 1000.0,
}
_UNKNOWN_INTAKE = "55555555-5555-4555-8555-555555555555"
_UNKNOWN_SUPPLIER = "66666666-6666-4666-8666-666666666666"


# --------------------------------------------------------------------------
# The quote series is keyed on the metal and the effective date together
# --------------------------------------------------------------------------

def test_a_second_quote_for_the_same_metal_and_date_is_refused(api):
    """Re-publishing the nickel quote of the first of July at a new price is a
    conflict, and the original quote survives untouched.

    PRD §3.1: "A second quote for the same combination of `metal` and
    `effective_date` is refused with `ERR_DUPLICATE_INDEX_PRICE`."

    Design: Corner/validations/duplicate_index_quote_for_the_same_metal_and_date_is_rejected
    """
    fx.move_clock(api, CLOCK_INTAKE)
    original = fx.publish_quote(api, "NI", 1600, "2026-07-01T00:00:00.000Z")

    response = api.create_metal_index_price(
        f.create_metal_index_price_payload(
            metal="NI", effective_date="2026-07-01T00:00:00.000Z", price_cents_per_kg=1900
        ),
        fx.ANALYST,
    )
    validate_error(response, "ERR_DUPLICATE_INDEX_PRICE", 409)

    listed, meta = validate_paginated(
        api.list_metal_index_prices(fx.ANALYST, params={"metal": "NI"})
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == original["id"]
    assert listed[0]["price_cents_per_kg"] == 1600


def test_the_quote_series_accepts_another_metal_or_another_effective_date(api):
    """Uniqueness binds the pair, not either half of it, and the effective-date
    filter is the same at-or-before lookup the pricing rules apply.

    PRD §3.1: "Quotes can be listed and filtered by `metal` and by
    `effective_on_or_before`, which restricts results to quotes whose `effective_date`
    falls at or before the supplied instant."

    Design: Corner/validations/index_quote_series_accepts_a_distinct_metal_or_a_distinct_date
    """
    fx.move_clock(api, CLOCK_INTAKE)
    july_nickel = fx.publish_quote(api, "NI", 1600, "2026-07-01T00:00:00.000Z")

    july_cobalt = validate_success(
        api.create_metal_index_price(
            f.create_metal_index_price_payload(
                metal="CO", effective_date="2026-07-01T00:00:00.000Z", price_cents_per_kg=3200
            ),
            fx.ANALYST,
        ),
        expected_status=201,
    )
    august_nickel = validate_success(
        api.create_metal_index_price(
            f.create_metal_index_price_payload(
                metal="NI", effective_date="2026-08-15T00:00:00.000Z", price_cents_per_kg=1750
            ),
            fx.ANALYST,
        ),
        expected_status=201,
    )

    assert july_cobalt["metal"] == "CO"
    assert august_nickel["price_cents_per_kg"] == 1750
    assert len({july_nickel["id"], july_cobalt["id"], august_nickel["id"]}) == 3

    _, meta = validate_paginated(
        api.list_metal_index_prices(fx.ANALYST, params={"metal": "NI"})
    )
    assert meta["total_count"] == 2

    filtered, filtered_meta = validate_paginated(
        api.list_metal_index_prices(
            fx.ACCOUNTANT,
            params={"metal": "NI", "effective_on_or_before": "2026-07-31T00:00:00.000Z"},
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["price_cents_per_kg"] == 1600


# --------------------------------------------------------------------------
# Quantitative ceilings on the campaign booking
# --------------------------------------------------------------------------

def test_planned_input_equal_to_the_line_capacity_passes_and_a_gramme_over_fails(api):
    """Twenty-four hours of a hundred-kilogramme-an-hour line is exactly twenty-four
    hundred kilogrammes, and the comparison against the plan is strict.

    PRD §3.6: "the window length in hours multiplied by the line's
    `throughput_kg_per_hour` is the most the line can physically process, and a
    `planned_input_kg` strictly greater than that product is refused with
    `ERR_CAMPAIGN_CAPACITY_EXCEEDED`; a planned input exactly equal to the product is
    accepted."

    Design: Corner/validations/campaign_planned_input_at_exactly_line_capacity_passes_and_one_gramme_over_fails
    """
    ctx = fx.bootstrap_network(api, quotes=None)
    line = fx.create_line(api, ctx["facility"]["id"], throughput_kg_per_hour=100.0)

    on_the_ceiling = fx.create_campaign(
        api,
        line["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=2400.0,
    )
    assert float(on_the_ceiling["planned_input_kg"]) == 2400.0

    over = api.create_campaign(
        f.create_campaign_payload(
            line["id"],
            window_start="2026-08-03T00:00:00.000Z",
            window_end="2026-08-04T00:00:00.000Z",
            planned_input_kg=2400.001,
        ),
        fx.OPERATOR,
    )
    validate_error(over, "ERR_CAMPAIGN_CAPACITY_EXCEEDED", 422)

    retried = fx.create_campaign(
        api,
        line["id"],
        window_start="2026-08-03T00:00:00.000Z",
        window_end="2026-08-04T00:00:00.000Z",
        planned_input_kg=2400.0,
    )
    assert retried["id"] != on_the_ceiling["id"]

    _, meta = validate_paginated(api.list_campaigns(fx.OPERATOR, params={"line_id": line["id"]}))
    assert meta["total_count"] == 2, "the refused booking persisted nothing"


# --------------------------------------------------------------------------
# Cross-entity link integrity
# --------------------------------------------------------------------------

def test_leachable_metals_cannot_be_booked_against_a_mechanical_lot(api):
    """The very same assay body is legal for copper, manganese and graphite and
    illegal for nickel, cobalt and lithium, decided only by the parent line's type.

    PRD §3.7: "a line booked for `NI`, `CO` or `LI` against a lot whose campaign runs
    on a `MECHANICAL` line is refused with `ERR_METAL_NOT_RECOVERABLE_ON_LINE`; `MN`
    and `GRAPHITE` streams carry no such restriction."

    Design: Corner/validations/hydromet_only_metals_cannot_be_booked_on_a_mechanical_line
    """
    ctx = fx.charged_lot(
        api,
        network={"clock": CLOCK_PROCESS, "quotes": _JULY_NICKEL},
        processing={
            "line": {
                "line_code": "MECH-1",
                "line_type": "MECHANICAL",
                "throughput_kg_per_hour": 100.0,
            },
            "campaign": dict(_PROCESS_WINDOW),
            "lot_code": "LOT-1",
        },
    )
    lot_id = ctx["lot"]["id"]
    assert ctx["decisions"][0]["grade"] == "D"
    assert float(ctx["lot"]["charged_mass_kg"]) == 100.0

    mechanical_streams = [
        fx.book_output(api, lot_id, "CU", 10.0, 99.5),
        fx.book_output(api, lot_id, "MN", 5.0, 96.0),
        fx.book_output(api, lot_id, "GRAPHITE", 5.0, 94.0),
    ]
    assert mechanical_streams[0]["metal"] == "CU"
    assert len({output["id"] for output in mechanical_streams}) == 3

    for metal, mass, purity in (("NI", 10.0, 99.2), ("CO", 4.0, 99.0), ("LI", 2.0, 98.5)):
        response = api.create_recovery_output(
            lot_id, f.create_recovery_output_payload(metal, mass, purity), fx.TECHNICIAN
        )
        validate_error(response, "ERR_METAL_NOT_RECOVERABLE_ON_LINE", 422)

    _, meta = validate_paginated(api.list_recovery_outputs(lot_id, fx.TECHNICIAN))
    assert meta["total_count"] == 3, "none of the three refused streams was persisted"


def test_a_module_can_only_be_charged_into_a_campaign_of_its_own_family(api):
    """The nickel-rich module is refused by the iron-phosphate lot and accepted by the
    nickel-rich one, with the same module list and the same version token.

    PRD §3.7: "every named module's `chemistry` must map to the campaign's
    `chemistry_family` under the fixed family mapping — `NMC622`, `NCA` and `LMO` to
    `NICKEL_RICH`, `LFP` to `IRON_PHOSPHATE` — otherwise `ERR_MODULE_CHEMISTRY_MISMATCH`."

    Design: Corner/validations/charge_rejects_a_module_whose_chemistry_family_differs_from_the_campaign
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    chain = fx.advance_intake(ctx, stop_after="released")
    module = chain["modules"][0]
    assert module["chemistry"] == "NMC622"
    fx.triage_module(api, module["id"])

    lots = {}
    for line_code, family, lot_code in (
        ("HYD-F", "IRON_PHOSPHATE", "LOT-F"),
        ("HYD-N", "NICKEL_RICH", "LOT-N"),
    ):
        line = fx.create_line(
            api,
            ctx["facility"]["id"],
            line_code=line_code,
            chemistry_family=family,
            throughput_kg_per_hour=100.0,
        )
        campaign = fx.create_campaign(
            api, line["id"], chemistry_family=family, **_PROCESS_WINDOW
        )
        fx.start_campaign(api, campaign["id"])
        lots[family] = (campaign, fx.open_lot(api, campaign["id"], lot_code=lot_code))

    iron_campaign, iron_lot = lots["IRON_PHOSPHATE"]
    response = api.charge_lot(
        iron_lot["id"],
        f.charge_lot_payload([module["id"]], iron_lot["version"]),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_MODULE_CHEMISTRY_MISMATCH", 422)

    refused = fx.read_lot(api, iron_lot["id"])
    assert refused["status"] == "OPEN"
    assert float(refused["charged_mass_kg"]) == 0.0
    assert refused["version"] == iron_lot["version"]
    untouched = validate_success(api.get_module(module["id"], fx.OPERATOR))
    assert untouched["status"] == "RECOVERY_QUEUE"
    assert untouched["lot_id"] is None
    assert float(
        validate_success(api.get_campaign(iron_campaign["id"], fx.OPERATOR))[
            "committed_input_kg"
        ]
    ) == 0.0

    nickel_campaign, nickel_lot = lots["NICKEL_RICH"]
    charged = fx.charge_lot(api, nickel_lot["id"], [module["id"]])
    assert charged["status"] == "CHARGED"
    assert float(charged["charged_mass_kg"]) == 100.0

    committed = validate_success(api.get_module(module["id"], fx.OPERATOR))
    assert committed["lot_id"] == nickel_lot["id"]
    assert committed["status"] == "CHARGED"
    intake = fx.read_intake(api, chain["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 100.0
    assert float(intake["unassigned_mass_kg"]) == 0.0
    assert float(
        validate_success(api.get_campaign(nickel_campaign["id"], fx.OPERATOR))[
            "committed_input_kg"
        ]
    ) == 100.0


def test_a_campaign_cannot_declare_a_family_its_line_is_not_plumbed_for(api):
    """The booking is refused while the line runs nickel-rich chemistry, and the
    identical body succeeds the moment the line is re-plumbed.

    PRD §3.6: "The campaign's `chemistry_family` must equal the line's current
    `chemistry_family`, otherwise the request is refused with
    `ERR_CAMPAIGN_FAMILY_MISMATCH`."

    Design: Corner/validations/campaign_family_must_equal_the_lines_family
    """
    ctx = fx.bootstrap_network(api, quotes=None)
    line = fx.create_line(api, ctx["facility"]["id"], throughput_kg_per_hour=100.0)
    body = f.create_campaign_payload(
        line["id"],
        chemistry_family="IRON_PHOSPHATE",
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )

    validate_error(api.create_campaign(body, fx.OPERATOR), "ERR_CAMPAIGN_FAMILY_MISMATCH", 422)
    _, meta = validate_paginated(api.list_campaigns(fx.OPERATOR, params={"line_id": line["id"]}))
    assert meta["total_count"] == 0

    replumbed = validate_success(
        api.replumb_processing_line(
            line["id"], f.replumb_payload("IRON_PHOSPHATE"), fx.ADMIN
        )
    )
    assert replumbed["chemistry_family"] == "IRON_PHOSPHATE"
    assert replumbed["version"] == 2

    accepted = validate_success(api.create_campaign(body, fx.OPERATOR), expected_status=201)
    assert accepted["chemistry_family"] == "IRON_PHOSPHATE"
    assert accepted["status"] == "SCHEDULED"
    assert accepted["line_id"] == line["id"]
    assert float(accepted["committed_input_kg"]) == 0.0


# --------------------------------------------------------------------------
# The order the tiers run in
# --------------------------------------------------------------------------

def test_a_malformed_body_is_reported_before_any_missing_row_is_looked_up(api):
    """One request that both names no row and carries an unlisted enum answers with the
    shape error; correcting only the enum flips the same request to the 404.

    PRD §2.7: "Checks are evaluated in the following thirteen tiers, and the **first**
    tier that fails determines the response; no later tier can mask an earlier one."

    Design: Corner/validations/body_shape_error_precedes_path_and_fk_existence_checks
    """
    ctx = fx.bootstrap_network(api, quotes=None)

    validate_error(
        api.identify_chemistry(
            _UNKNOWN_INTAKE, f.identify_chemistry_payload("LTO"), fx.CLERK
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.identify_chemistry(
            _UNKNOWN_INTAKE, f.identify_chemistry_payload("NMC622"), fx.CLERK
        ),
        "ERR_INTAKE_NOT_FOUND",
        404,
    )

    validate_error(
        api.create_intake(
            f.create_intake_payload(
                _UNKNOWN_SUPPLIER,
                ctx["facility"]["id"],
                declared_chemistry="LTO",
                declared_ni_pct=f.OMIT,
            ),
            fx.CLERK,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_intake(
            f.create_intake_payload(
                _UNKNOWN_SUPPLIER, ctx["facility"]["id"], declared_ni_pct=f.OMIT
            ),
            fx.CLERK,
        ),
        "ERR_SUPPLIER_NOT_FOUND",
        404,
    )

    _, meta = validate_paginated(api.list_intakes(fx.CLERK))
    assert meta["total_count"] == 0
    assert fx.read_supplier(api, ctx["supplier"]["id"])["version"] == 1


def test_a_campaign_start_exactly_at_its_window_end_is_too_late(api):
    """One millisecond before the window closes the start is accepted; at the closing
    instant itself an identical campaign on a second line is refused.

    PRD §3.6: "it requires the current clock position to be strictly before the
    campaign's `window_end`, otherwise `ERR_CAMPAIGN_WINDOW_CLOSED`."

    Design: Corner/validations/campaign_start_at_window_end_returns_campaign_window_closed
    """
    ctx = fx.bootstrap_network(api, quotes=None)
    campaigns = []
    for line_code in ("HYD-1", "HYD-2"):
        line = fx.create_line(
            api, ctx["facility"]["id"], line_code=line_code, throughput_kg_per_hour=100.0
        )
        campaigns.append(
            (
                line,
                fx.create_campaign(
                    api,
                    line["id"],
                    window_start="2026-08-01T00:00:00.000Z",
                    window_end="2026-08-02T00:00:00.000Z",
                    planned_input_kg=1000.0,
                ),
            )
        )

    fx.move_clock(api, "2026-08-01T23:59:59.999Z")
    started = fx.start_campaign(api, campaigns[0][1]["id"])
    assert started["status"] == "RUNNING"
    assert started["version"] == 2

    fx.move_clock(api, "2026-08-02T00:00:00.000Z")
    second_line, second_campaign = campaigns[1]
    validate_error(
        api.start_campaign(second_campaign["id"], fx.OPERATOR),
        "ERR_CAMPAIGN_WINDOW_CLOSED",
        422,
    )

    untouched = validate_success(api.get_campaign(second_campaign["id"], fx.OPERATOR))
    assert untouched["status"] == "SCHEDULED"
    assert untouched["version"] == 1
    assert validate_success(api.get_processing_line(second_line["id"], fx.ADMIN))["status"] == (
        "AVAILABLE"
    ), "the refusal is temporal, not a line-availability failure"


def test_finalize_demands_an_assay_line_before_it_computes_the_balance(api):
    """A residue that would clear the mass-balance floor on its own is still refused
    while the ledger is empty, and the same lot finalizes once one stream exists.

    PRD §3.7: "The lot must have at least one assay line, otherwise
    `ERR_NO_RECOVERY_OUTPUTS`."; "Its `mass_balance_pct` is the accounted figure
    divided by `charged_mass_kg`, multiplied by one hundred and rounded half up to two
    decimals."

    Design: Corner/validations/finalize_checks_output_existence_before_computing_the_mass_balance
    """
    ctx = fx.charged_lot(
        api,
        network={"clock": CLOCK_PROCESS, "quotes": _JULY_NICKEL},
        processing={
            "line": {"throughput_kg_per_hour": 100.0},
            "campaign": dict(_PROCESS_WINDOW),
            "lot_code": "LOT-1",
        },
    )
    lot_id = ctx["lot"]["id"]
    assert float(ctx["lot"]["charged_mass_kg"]) == 100.0
    assert ctx["lot"]["version"] == 2

    empty_ledger = api.finalize_lot(lot_id, f.finalize_lot_payload(97.0), fx.TECHNICIAN)
    validate_error(empty_ledger, "ERR_NO_RECOVERY_OUTPUTS", 422)

    still_charged = fx.read_lot(api, lot_id)
    assert still_charged["status"] == "CHARGED"
    assert still_charged["mass_balance_pct"] is None
    assert still_charged["finalized_at"] is None
    assert still_charged["version"] == 2

    fx.book_output(api, lot_id, "NI", 30.0, 99.0)
    finalized = fx.finalize_lot(api, lot_id, 67.0)

    assert finalized["status"] == "FINALIZED"
    assert float(finalized["recovered_mass_kg"]) == 30.000
    assert float(finalized["accounted_mass_kg"]) == 97.000
    assert float(finalized["unaccounted_mass_kg"]) == 3.000
    assert float(finalized["mass_balance_pct"]) == 97.00
    assert float(finalized["recycled_content_pct"]) == 30.00
    assert finalized["finalized_at"] == CLOCK_PROCESS

    assert validate_success(api.get_module(ctx["modules"][0]["id"], fx.OPERATOR))["status"] == (
        "CONSUMED"
    )
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])
    assert settlement["variant"] == "FINAL"
    assert float(settlement["max_variance_pp"]) == 18.00
    assert fx.read_supplier(api, ctx["supplier"]["id"])["quality_strike_count"] == 1


def test_an_override_is_only_accepted_when_the_computed_grade_permits_it(api):
    """A grade-D module may be pushed to shredding but not up to refurbishment or
    second life, while a grade-A module may be routed downward.

    PRD §3.4: "An `override_disposition` of `REFURBISH` is permitted only when the
    computed grade is `A` or `B`; an override of `SECOND_LIFE` is permitted when the
    grade is `A`, `B` or `C`, and therefore refused when the grade is `D`; an override
    of `MATERIAL_RECOVERY` is always permitted, since routing better material into
    shredding is a commercial choice rather than a safety risk."

    Design: Corner/validations/disposition_override_is_only_permitted_for_the_allowed_grades
    """
    ctx = fx.bootstrap_network(api, quotes=None)
    chain = fx.advance_intake(
        ctx,
        stop_after="package",
        intake={"gross_mass_kg": 1010.0, "packaging_tare_kg": 10.0},
        modules=(
            {
                "serial_code": "M-D",
                "min_cell_capacity_pct": 58.0,
                "mean_cell_capacity_pct": 62.0,
                "cycle_count": 1200,
            },
            {
                "serial_code": "M-A",
                "min_cell_capacity_pct": 88.0,
                "mean_cell_capacity_pct": 92.0,
                "cycle_count": 400,
            },
        ),
    )
    weak, strong = chain["modules"]

    for refused_override in ("REFURBISH", "SECOND_LIFE"):
        response = api.create_triage_decision(
            weak["id"],
            f.create_triage_decision_payload("CONSERVATIVE", refused_override),
            fx.ENGINEER,
        )
        validate_error(response, "ERR_DISPOSITION_OVERRIDE_NOT_PERMITTED", 422)

    assert validate_success(api.get_module(weak["id"], fx.OPERATOR))["status"] == (
        "PENDING_TRIAGE"
    )
    _, meta = validate_paginated(api.list_triage_decisions(weak["id"], fx.ENGINEER))
    assert meta["total_count"] == 0

    downgraded = fx.triage_module(
        api, weak["id"], scoring_variant="CONSERVATIVE",
        override_disposition="MATERIAL_RECOVERY",
    )
    assert float(downgraded["score"]) == 48.80
    assert downgraded["grade"] == "D"
    assert downgraded["derived_disposition"] == "MATERIAL_RECOVERY"
    assert downgraded["disposition"] == "MATERIAL_RECOVERY"
    assert validate_success(api.get_module(weak["id"], fx.OPERATOR))["status"] == (
        "RECOVERY_QUEUE"
    )

    routed_down = fx.triage_module(
        api, strong["id"], scoring_variant="FLEET_AVERAGE",
        override_disposition="SECOND_LIFE",
    )
    assert float(routed_down["score"]) == 86.80
    assert routed_down["grade"] == "A"
    assert routed_down["derived_disposition"] == "REFURBISH"
    assert routed_down["disposition"] == "SECOND_LIFE", "the override is honoured downward"
    assert validate_success(api.get_module(strong["id"], fx.OPERATOR))["status"] == (
        "SECOND_LIFE_QUEUE"
    )
