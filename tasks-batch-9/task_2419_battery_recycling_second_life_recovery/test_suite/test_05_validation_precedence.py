"""Pairs of simultaneously violated rules, resolved by the thirteen-tier order."""
from test_helpers import (
    NON_EXISTENT_UUID,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

_SINGLE_NICKEL_QUOTE = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600}
]
_SINGLE_COPPER_QUOTE = [
    {"metal": "CU", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 850}
]


# --------------------------------------------------------------------------
# Tier 2 role authorisation beats tier 5 path existence
# --------------------------------------------------------------------------

def _plant_without_feedstock(api):
    """A campus, a line, a scheduled campaign and one open lot — no shipment."""
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(api, ctx["line"]["id"])
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"])
    return ctx


def test_role_denial_precedes_path_resolution_on_lot_finalize(api):
    """An accountant finalizing a lot that does not exist is told about the role,
    not about the missing lot.

    PRD §2.7: "the **first** tier that fails determines the response; no later tier
    can mask an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/role_denial_precedes_path_not_found_on_lot_finalize
    """
    ctx = _plant_without_feedstock(api)

    response = api.finalize_lot(
        NON_EXISTENT_UUID, f.finalize_lot_payload(10.0), fx.ACCOUNTANT
    )
    validate_error(response, "ERR_FORBIDDEN_ROLE", 403)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"
    assert lot["residue_mass_kg"] is None


def test_authorised_role_on_the_same_unknown_lot_reports_the_missing_lot(api):
    """With the authorised role in the header the masked tier surfaces, proving the
    403 was the earlier failure rather than a mis-resolved path.

    PRD §2.7: "**Path existence**, left to right, as described in §2.6. The
    applicable 404 code."

    Design: Difficulty/priority_pair_validation_conflict/role_denial_precedes_path_not_found_on_lot_finalize
    """
    ctx = _plant_without_feedstock(api)

    response = api.finalize_lot(
        NON_EXISTENT_UUID, f.finalize_lot_payload(10.0), fx.TECHNICIAN
    )
    validate_error(response, "ERR_LOT_NOT_FOUND", 404)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"


# --------------------------------------------------------------------------
# Tier 7 optimistic concurrency beats tier 11 quantitative ceilings
# --------------------------------------------------------------------------

def _lot_under_a_tight_plan(api):
    """A running campaign planned for half the mass waiting in the recovery queue."""
    return fx.build_world(
        api,
        stop_after="lot",
        network={"quotes": _SINGLE_NICKEL_QUOTE},
        processing={"campaign": {"planned_input_kg": 50.0}},
    )


def test_stale_lot_version_precedes_the_charge_plan_ceiling(api):
    """A charge sheet built on an outdated lot version is rejected on the version
    even though the same request would also overrun the campaign plan.

    PRD §3.7: "The checks run in the global precedence order of §2.7, which means the
    stale-version check is evaluated before any state check: a mismatch between
    `expected_lot_version` and the lot's current `version` is rejected with
    `ERR_STALE_LOT_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/stale_lot_version_precedes_charge_exceeds_plan
    """
    ctx = _lot_under_a_tight_plan(api)
    module_ids = [module["id"] for module in ctx["modules"]]

    response = api.charge_lot(
        ctx["lot"]["id"],
        f.charge_lot_payload(module_ids, ctx["lot"]["version"] - 1),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_STALE_LOT_VERSION", 412)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"
    assert float(lot["charged_mass_kg"]) == 0.0

    module = validate_success(api.get_module(module_ids[0], fx.OPERATOR))
    assert module["status"] == "RECOVERY_QUEUE"
    assert module["lot_id"] is None

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert float(campaign["committed_input_kg"]) == 0.0


def test_current_lot_version_exposes_the_masked_charge_plan_ceiling(api):
    """The identical charge carrying the lot's current version is refused on the
    campaign plan instead.

    PRD §3.7: "the campaign's current `committed_input_kg` plus the total mass of the
    modules being charged must be at most the campaign's `planned_input_kg`, and
    exceeding it is refused with `ERR_LOT_CHARGE_EXCEEDS_PLAN`."

    Design: Difficulty/priority_pair_validation_conflict/stale_lot_version_precedes_charge_exceeds_plan
    """
    ctx = _lot_under_a_tight_plan(api)
    module_ids = [module["id"] for module in ctx["modules"]]

    response = api.charge_lot(
        ctx["lot"]["id"],
        f.charge_lot_payload(module_ids, ctx["lot"]["version"]),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_LOT_CHARGE_EXCEEDS_PLAN", 422)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"
    assert float(lot["charged_mass_kg"]) == 0.0


# --------------------------------------------------------------------------
# Tier 9 safety gates beat tier 10 interval geometry
# --------------------------------------------------------------------------

def _campaign_on_a_closed_window(api, *, line_status):
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(
        api, ctx["facility"]["id"], line_code="HYD-M", status=line_status
    )
    ctx["campaign"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    fx.move_clock(api, "2026-08-05T00:00:00.000Z")
    return ctx


def test_line_maintenance_precedes_the_closed_campaign_window(api):
    """A campaign on a line under maintenance reports the line, not the window that
    has already closed.

    PRD §3.6: "it requires the line's `status` to be `AVAILABLE`, since a line in
    `MAINTENANCE` accepts no start and yields `ERR_LINE_NOT_AVAILABLE`"

    Design: Difficulty/priority_pair_validation_conflict/line_maintenance_safety_precedes_campaign_window_closed
    """
    ctx = _campaign_on_a_closed_window(api, line_status="MAINTENANCE")

    response = api.start_campaign(ctx["campaign"]["id"], fx.OPERATOR)
    validate_error(response, "ERR_LINE_NOT_AVAILABLE", 422)

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert campaign["status"] == "SCHEDULED"


def test_available_line_exposes_the_masked_closed_window(api):
    """The same start against an available line surfaces the window check that the
    safety gate had masked.

    PRD §3.6: "it requires the current clock position to be strictly before the
    campaign's `window_end`, otherwise `ERR_CAMPAIGN_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/line_maintenance_safety_precedes_campaign_window_closed
    """
    ctx = _campaign_on_a_closed_window(api, line_status="AVAILABLE")

    response = api.start_campaign(ctx["campaign"]["id"], fx.OPERATOR)
    validate_error(response, "ERR_CAMPAIGN_WINDOW_CLOSED", 422)

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert campaign["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Tier 11 quantitative floors beat the tier 13 money gate
# --------------------------------------------------------------------------

def _iron_phosphate_lot_without_a_nickel_quote(api):
    """A charged LFP lot carrying a nickel assay line the price feed cannot price."""
    ctx = fx.bootstrap_network(api, quotes=_SINGLE_COPPER_QUOTE)
    fx.advance_intake(
        ctx,
        stop_after="released",
        intake={
            "declared_chemistry": "LFP",
            "gross_mass_kg": 220.0,
            "packaging_tare_kg": 20.0,
            "declared_ni_pct": 0.0,
            "declared_cu_pct": 8.0,
        },
        identified_chemistry="LFP",
        modules=({"serial_code": "M-1", "mass_kg": 200.0},),
        soc_pct=9.0,
    )
    fx.advance_processing(
        ctx,
        stop_after="charged",
        line={"line_code": "HYD-2", "chemistry_family": "IRON_PHOSPHATE"},
        campaign={"chemistry_family": "IRON_PHOSPHATE"},
    )
    fx.book_output(api, ctx["lot"]["id"], "NI", 50.000, 99.00)
    return ctx


def test_mass_balance_floor_precedes_the_missing_index_quote_on_finalize(api):
    """A lot that is both out of tolerance and unpriceable reports the tolerance
    failure, because money gates are evaluated last.

    PRD §2.7: "a lot whose mass balance is out of tolerance reports the tolerance
    failure even when an index quote is also missing."

    Design: Difficulty/priority_pair_validation_conflict/mass_balance_constraint_precedes_missing_index_price_on_finalize
    """
    ctx = _iron_phosphate_lot_without_a_nickel_quote(api)

    settlement = fx.read_settlement(api, ctx["settlement"]["id"])
    assert settlement["gross_cents"] == 4896

    response = api.finalize_lot(ctx["lot"]["id"], f.finalize_lot_payload(100.0), fx.TECHNICIAN)
    validate_error(response, "ERR_MASS_BALANCE_OUT_OF_TOLERANCE", 422)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "CHARGED"
    assert lot["mass_balance_pct"] is None
    assert lot["residue_mass_kg"] is None

    module = validate_success(api.get_module(ctx["modules"][0]["id"], fx.OPERATOR))
    assert module["status"] == "CHARGED"

    settlement = fx.read_settlement(api, ctx["settlement"]["id"])
    assert settlement["variant"] == "PROVISIONAL"
    assert settlement["state"] == "DRAFT"


def test_a_reconcilable_residue_exposes_the_masked_missing_index_quote(api):
    """With a residue that clears the tolerance floor, the same lot fails on the
    missing nickel quote instead.

    PRD §3.7: "a published index quote with an `effective_date` at or before the
    current clock position must exist for every payable metal that has an assay line
    on this lot, otherwise `ERR_INDEX_PRICE_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/mass_balance_constraint_precedes_missing_index_price_on_finalize
    """
    ctx = _iron_phosphate_lot_without_a_nickel_quote(api)

    response = api.finalize_lot(ctx["lot"]["id"], f.finalize_lot_payload(145.0), fx.TECHNICIAN)
    validate_error(response, "ERR_INDEX_PRICE_UNAVAILABLE", 422)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "CHARGED"
    assert lot["mass_balance_pct"] is None
