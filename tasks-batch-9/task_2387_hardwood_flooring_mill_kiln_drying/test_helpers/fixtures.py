"""Composite setup helpers.

Every helper builds its preconditions from scratch through the PRD's own
endpoints, because each test starts against an empty database.  Helpers use the
lenient ``get_success_data`` validator so a broken preamble surfaces as a setup
failure rather than a confusing assertion failure.

The returned ``ctx`` dict accumulates the entities each stage created, so a test
can reach for any ancestor it needs:

    ctx = setup_graded_lot(api)
    ctx["species"], ctx["schedule"], ctx["chamber"], ctx["charge"],
    ctx["receipts"], ctx["product_line"], ctx["lot"], ctx["grade_run"],
    ctx["bundles"], ctx["batches"]
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _default_api
from .constants import TEST_DEFAULTS
from .factories import (
    accept_receipt_payload,
    adjudicate_claim_payload,
    allocate_receipt_payload,
    complete_milling_payload,
    create_byproduct_sale_payload,
    create_core_stock_payload,
    create_drying_schedule_payload,
    create_flooring_lot_payload,
    create_grade_bundle_payload,
    create_grade_run_payload,
    create_green_receipt_payload,
    create_kiln_chamber_payload,
    create_kiln_charge_payload,
    create_prefinish_line_payload,
    create_prefinish_run_payload,
    create_product_line_payload,
    create_species_profile_payload,
    create_warranty_claim_payload,
    finalize_lot_payload,
    record_stress_test_payload,
)
from .test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    CLAIM_SUBMITTER_USER_ID,
    TEST_USERS,
    make_warranty_adjudicator_headers,
)

CLOCK_BASE_UTC = TEST_DEFAULTS["CLOCK_BASE_UTC"]
CLOCK_WARRANTY_UTC = TEST_DEFAULTS["CLOCK_WARRANTY_UTC"]

ADMIN = TEST_USERS["mill_admin_headers"]
CLERK = TEST_USERS["procurement_clerk_headers"]
OPERATOR = TEST_USERS["kiln_operator_headers"]
SUPERVISOR = TEST_USERS["mill_supervisor_headers"]
INSPECTOR = TEST_USERS["grade_inspector_headers"]
SCHEDULER = TEST_USERS["prefinish_scheduler_headers"]
BROKER = TEST_USERS["byproduct_broker_headers"]
ADJUDICATOR = TEST_USERS["warranty_adjudicator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creates
# ---------------------------------------------------------------------------


def set_logical_clock(api=None, current_utc=CLOCK_BASE_UTC) -> dict:
    api = api or _default_api
    return get_success_data(api.set_clock(current_utc, ADMIN))


def create_species(api=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_species_profile(create_species_profile_payload(**overrides), ADMIN)
    )


def create_schedule(api=None, species=None, expected_version=None, **overrides) -> dict:
    api = api or _default_api
    version = expected_version if expected_version is not None else species["version"]
    return get_success_data(
        api.create_drying_schedule(
            create_drying_schedule_payload(species["id"], version, **overrides), ADMIN
        )
    )


def create_chamber(api=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_kiln_chamber(create_kiln_chamber_payload(**overrides), ADMIN)
    )


def create_charge(api=None, schedule=None, chamber=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_kiln_charge(
            create_kiln_charge_payload(schedule["id"], chamber["id"], **overrides),
            OPERATOR,
        )
    )


def create_receipt(api=None, species=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_green_receipt(
            create_green_receipt_payload(species["id"], **overrides), CLERK
        )
    )


def create_accepted_receipt(
    api=None,
    species=None,
    received_board_feet=6000,
    accepted_board_feet=5800,
    moisture_pct_at_receipt=46.0,
    receipt_grade="FAS",
    supplier_name=TEST_DEFAULTS["SUPPLIER_NAME"],
) -> dict:
    """Record a receipt at the deck and scale it down to its accepted volume."""
    api = api or _default_api
    receipt = create_receipt(
        api,
        species,
        received_board_feet=received_board_feet,
        moisture_pct_at_receipt=moisture_pct_at_receipt,
        receipt_grade=receipt_grade,
        supplier_name=supplier_name,
    )
    return get_success_data(
        api.accept_green_receipt(
            receipt["id"], accept_receipt_payload(accepted_board_feet), CLERK
        )
    )


def create_product_line(api=None, species=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_product_line(
            create_product_line_payload(species["id"], **overrides), ADMIN
        )
    )


def create_core_stock(api=None, product_line=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_core_stock(
            create_core_stock_payload(product_line["id"], **overrides), ADMIN
        )
    )


def create_prefinish_line(api=None, **overrides) -> dict:
    api = api or _default_api
    return get_success_data(
        api.create_prefinish_line(create_prefinish_line_payload(**overrides), ADMIN)
    )


def refetch_species(api, species_profile_id) -> dict:
    return get_success_data(api.get_species_profile(species_profile_id, ADMIN))


def refetch_charge(api, charge_id) -> dict:
    return get_success_data(api.get_kiln_charge(charge_id, ADMIN))


def refetch_receipt(api, receipt_id) -> dict:
    return get_success_data(api.get_green_receipt(receipt_id, ADMIN))


def refetch_chamber(api, chamber_id) -> dict:
    return get_success_data(api.get_kiln_chamber(chamber_id, ADMIN))


def refetch_lot(api, lot_id) -> dict:
    return get_success_data(api.get_flooring_lot(lot_id, ADMIN))


def refetch_product_line(api, product_line_id) -> dict:
    return get_success_data(api.get_product_line(product_line_id, ADMIN))


def refetch_grade_run(api, grade_run_id) -> dict:
    return get_success_data(api.get_grade_run(grade_run_id, ADMIN))


def refetch_prefinish_run(api, prefinish_run_id) -> dict:
    return get_success_data(api.get_prefinish_run(prefinish_run_id, ADMIN))


def refetch_claim(api, claim_id) -> dict:
    return get_success_data(api.get_warranty_claim(claim_id, ADMIN))


def refetch_core_stock(api, core_stock_id) -> dict:
    return get_success_data(api.get_core_stock(core_stock_id, ADMIN))


def refetch_batch(api, batch_id) -> dict:
    return get_success_data(api.get_byproduct_batch(batch_id, ADMIN))


def fetch_lot_batches(api, lot_id) -> dict:
    """Return the lot's three byproduct batches keyed by stream."""
    body = api.list_byproduct_batches(ADMIN, params={"flooring_lot_id": lot_id, "limit": 100})
    rows = body.json()["data"]
    return {row["byproduct_type"]: row for row in rows}


# ---------------------------------------------------------------------------
# Tier 1: mill configuration
# ---------------------------------------------------------------------------


# The canonical configuration: a dense red oak dried on a one-inch schedule from
# 45.0 percent down to 7.0 percent, in a 12000 board-foot chamber.
def setup_mill_configuration(
    api=None,
    clock=CLOCK_BASE_UTC,
    species_overrides=None,
    schedule_overrides=None,
    chamber_overrides=None,
) -> dict:
    api = api or _default_api
    set_logical_clock(api, clock)
    species = create_species(api, **(species_overrides or {}))
    schedule = create_schedule(api, species, **(schedule_overrides or {}))
    # PRD 2.5: "A successful create increments `SpeciesProfile.version`, so a
    # caller that holds a pre-write version is refused on its next attempt until
    # it re-reads the profile."  The schedule create above bumped the profile, so
    # the ctx must carry the re-read row rather than the pre-write snapshot.
    species = refetch_species(api, species["id"])
    chamber = create_chamber(api, **(chamber_overrides or {}))
    return {
        "api": api,
        "species": species,
        "schedule": schedule,
        "chamber": chamber,
    }


# ---------------------------------------------------------------------------
# Tier 2: the kiln charge lifecycle
# ---------------------------------------------------------------------------

# Two receipts of the same supplier: 5800 accepted board feet at 46.0 percent and
# 3900 at 44.0 percent, giving 9700 charged board feet at a weighted 45.2.
CANONICAL_RECEIPTS = (
    {
        "received_board_feet": 6000,
        "accepted_board_feet": 5800,
        "moisture_pct_at_receipt": 46.0,
        "receipt_grade": "FAS",
    },
    {
        "received_board_feet": 4000,
        "accepted_board_feet": 3900,
        "moisture_pct_at_receipt": 44.0,
        "receipt_grade": "SELECT",
    },
)


def setup_scheduled_charge(api=None, charge_overrides=None, ctx=None, **kwargs) -> dict:
    """Configuration plus one `SCHEDULED` charge holding no wood yet."""
    ctx = ctx or setup_mill_configuration(api, **kwargs)
    api = ctx["api"]
    ctx["charge"] = create_charge(
        api, ctx["schedule"], ctx["chamber"], **(charge_overrides or {})
    )
    return ctx


def setup_charge_with_receipts(api=None, receipts=None, ctx=None, **kwargs) -> dict:
    """Scheduled charge with its green receipts accepted and allocated."""
    ctx = ctx or setup_scheduled_charge(api, **kwargs)
    api = ctx["api"]
    specs = list(receipts) if receipts is not None else [dict(r) for r in CANONICAL_RECEIPTS]
    built = []
    for spec in specs:
        receipt = create_accepted_receipt(api, ctx["species"], **spec)
        get_success_data(
            api.allocate_receipt(
                ctx["charge"]["id"], allocate_receipt_payload(receipt["id"]), OPERATOR
            )
        )
        built.append(refetch_receipt(api, receipt["id"]))
    ctx["receipts"] = built
    ctx["charge"] = refetch_charge(api, ctx["charge"]["id"])
    return ctx


def setup_loaded_charge(api=None, ctx=None, **kwargs) -> dict:
    """Charge advanced to `LOADED`, which consumes its receipts and occupies the
    chamber."""
    ctx = ctx or setup_charge_with_receipts(api, **kwargs)
    api = ctx["api"]
    ctx["charge"] = get_success_data(api.load_charge(ctx["charge"]["id"], OPERATOR))
    return ctx


def setup_conditioning_charge(api=None, ctx=None, **kwargs) -> dict:
    """Charge advanced through the drying leg into `CONDITIONING`, ready for a
    stress test."""
    ctx = ctx or setup_loaded_charge(api, **kwargs)
    api = ctx["api"]
    get_success_data(api.start_drying(ctx["charge"]["id"], OPERATOR))
    ctx["charge"] = get_success_data(
        api.begin_conditioning(ctx["charge"]["id"], OPERATOR)
    )
    return ctx


def setup_released_charge(
    api=None,
    shell_moisture_pct=6.4,
    core_moisture_pct=8.2,
    ctx=None,
    **kwargs,
) -> dict:
    """Charge released by a passing stress test, with its kiln-dry output
    computed.  The canonical readings of 6.4 shell against 8.2 core give a
    gradient of 1.8 and an average of 7.3."""
    ctx = ctx or setup_conditioning_charge(api, **kwargs)
    api = ctx["api"]
    ctx["stress_test"] = get_success_data(
        api.record_stress_test(
            ctx["charge"]["id"],
            record_stress_test_payload(shell_moisture_pct, core_moisture_pct),
            OPERATOR,
        )
    )
    ctx["charge"] = refetch_charge(api, ctx["charge"]["id"])
    ctx["chamber"] = refetch_chamber(api, ctx["chamber"]["id"])
    return ctx


def setup_redried_charge(api=None, ctx=None, **kwargs) -> dict:
    """Charge sent back for redry by a failing stress test (5.9 shell against
    8.0 core gives a gradient of 2.1)."""
    return setup_released_charge(
        api, shell_moisture_pct=5.9, core_moisture_pct=8.0, ctx=ctx, **kwargs
    )


# ---------------------------------------------------------------------------
# Tier 3: milling
# ---------------------------------------------------------------------------


def setup_planned_lot(
    api=None,
    input_dry_bf=6000,
    line_overrides=None,
    core_stock_overrides=None,
    with_core_stock=False,
    lot_overrides=None,
    ctx=None,
    **kwargs,
) -> dict:
    """Released charge plus a product line and one `PLANNED` lot drawing from the
    charge."""
    ctx = ctx or setup_released_charge(api, **kwargs)
    api = ctx["api"]
    ctx["product_line"] = create_product_line(api, ctx["species"], **(line_overrides or {}))
    extra = dict(lot_overrides or {})
    if with_core_stock:
        ctx["core_stock"] = create_core_stock(
            api, ctx["product_line"], **(core_stock_overrides or {})
        )
        extra.setdefault("core_stock_id", ctx["core_stock"]["id"])
    ctx["lot"] = get_success_data(
        api.create_flooring_lot(
            create_flooring_lot_payload(
                ctx["product_line"]["id"], ctx["charge"]["id"], input_dry_bf, **extra
            ),
            SUPERVISOR,
        )
    )
    ctx["charge"] = refetch_charge(api, ctx["charge"]["id"])
    return ctx


def setup_milled_lot(api=None, milling=None, ctx=None, **kwargs) -> dict:
    """Lot advanced to `MILLED` with its mass balance and provisional yield
    recorded, and its three byproduct batches opened."""
    ctx = ctx or setup_planned_lot(api, **kwargs)
    api = ctx["api"]
    ctx["lot"] = get_success_data(
        api.complete_milling(
            ctx["lot"]["id"], complete_milling_payload(**(milling or {})), SUPERVISOR
        )
    )
    ctx["batches"] = fetch_lot_batches(api, ctx["lot"]["id"])
    return ctx


def setup_lot_with_byproduct_sale(
    api=None,
    sale_overrides=None,
    stream="SAWDUST",
    ctx=None,
    **kwargs,
) -> dict:
    """Milled lot with one sale recorded against one of its byproduct batches."""
    ctx = ctx or setup_milled_lot(api, **kwargs)
    api = ctx["api"]
    batch = ctx["batches"][stream]
    ctx["sale"] = get_success_data(
        api.create_byproduct_sale(
            create_byproduct_sale_payload(batch["id"], **(sale_overrides or {})), BROKER
        )
    )
    ctx["batches"] = fetch_lot_batches(api, ctx["lot"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: grading and closeout
# ---------------------------------------------------------------------------

# The canonical tally: four bundles totalling 4491.40 board feet, credited at
# 3970.2625 and valued at 2168327 cents.
CANONICAL_BUNDLES = (
    {"grade_class": "CLEAR", "bundle_board_feet": 1187.25, "average_length_in": 50},
    {"grade_class": "SELECT", "bundle_board_feet": 1502.60, "average_length_in": 36},
    {"grade_class": "NO1_COMMON", "bundle_board_feet": 1098.45, "average_length_in": 30},
    {"grade_class": "CHARACTER", "bundle_board_feet": 703.10, "average_length_in": 20},
)


def setup_draft_grade_run(
    api=None,
    ruleset="MILL_CHARACTER",
    bundles=None,
    ctx=None,
    **kwargs,
) -> dict:
    """Milled lot with an open `DRAFT` grade run and its bundles tallied on."""
    ctx = ctx or setup_milled_lot(api, **kwargs)
    api = ctx["api"]
    ctx["grade_run"] = get_success_data(
        api.create_grade_run(
            create_grade_run_payload(
                ctx["lot"]["id"], ctx["lot"]["version"], inspector_ruleset=ruleset
            ),
            INSPECTOR,
        )
    )
    ctx["lot"] = refetch_lot(api, ctx["lot"]["id"])
    specs = list(bundles) if bundles is not None else [dict(b) for b in CANONICAL_BUNDLES]
    ctx["bundles"] = [
        get_success_data(
            api.create_grade_bundle(
                ctx["grade_run"]["id"], create_grade_bundle_payload(**spec), INSPECTOR
            )
        )
        for spec in specs
    ]
    return ctx


def setup_finalized_grade_run(api=None, ctx=None, **kwargs) -> dict:
    """Grade run finalized, turning its bundle lines into the run tally."""
    ctx = ctx or setup_draft_grade_run(api, **kwargs)
    api = ctx["api"]
    ctx["grade_run"] = get_success_data(
        api.finalize_grade_run(ctx["grade_run"]["id"], INSPECTOR)
    )
    return ctx


def setup_graded_lot(api=None, ctx=None, **kwargs) -> dict:
    """Lot closed out against its finalized run.  With the canonical tally the
    final yield is 66.17 percent, above the floor, so the lot grades out."""
    ctx = ctx or setup_finalized_grade_run(api, **kwargs)
    api = ctx["api"]
    ctx["lot"] = get_success_data(
        api.finalize_flooring_lot(
            ctx["lot"]["id"], finalize_lot_payload(ctx["grade_run"]["id"]), SUPERVISOR
        )
    )
    return ctx


QUARANTINE_BUNDLES = (
    {"grade_class": "NO2_COMMON", "bundle_board_feet": 900.00, "average_length_in": 36},
    {"grade_class": "CHARACTER", "bundle_board_feet": 500.00, "average_length_in": 40},
    {"grade_class": "CABIN", "bundle_board_feet": 400.00, "average_length_in": 30},
)

# A small 2900 board-foot lot milled down to 2500 net board feet.
QUARANTINE_MILLING = {
    "actual_milled_width_in": 3.190,
    "net_flooring_bf": 2500,
    "shorts_bf": 100,
    "sawdust_tons": 0.80,
    "shavings_tons": 0.20,
}


def setup_quarantined_lot(api=None, ctx=None, **kwargs) -> dict:
    """A character-heavy tally credits too little to clear the yield floor, so
    the lot is quarantined instead of graded.  The 2900 board-foot lot mills to
    2500 net board feet for an 86.21 percent provisional yield, but the three
    low-credit bundles only credit 1090.0000, a final yield of 37.59 percent."""
    kwargs.setdefault("bundles", QUARANTINE_BUNDLES)
    kwargs.setdefault("input_dry_bf", 2900)
    kwargs.setdefault("milling", dict(QUARANTINE_MILLING))
    return setup_graded_lot(api, ctx=ctx, **kwargs)


# ---------------------------------------------------------------------------
# Tier 5: prefinishing
# ---------------------------------------------------------------------------


def setup_prefinish_ready(api=None, prefinish_line_overrides=None, ctx=None, **kwargs) -> dict:
    """Graded lot plus a prefinishing line with a 9000 linear-foot capacity and
    three coating passes."""
    ctx = ctx or setup_graded_lot(api, **kwargs)
    api = ctx["api"]
    ctx["prefinish_line"] = create_prefinish_line(api, **(prefinish_line_overrides or {}))
    return ctx


def setup_scheduled_prefinish_run(api=None, run_overrides=None, ctx=None, **kwargs) -> dict:
    """One `SCHEDULED` prefinish run from 06:00 to 14:00 pushing 5000 linear
    feet, which consumes 47.85 litres of coating."""
    ctx = ctx or setup_prefinish_ready(api, **kwargs)
    api = ctx["api"]
    ctx["prefinish_run"] = get_success_data(
        api.create_prefinish_run(
            create_prefinish_run_payload(
                ctx["prefinish_line"]["id"], ctx["lot"]["id"], **(run_overrides or {})
            ),
            SCHEDULER,
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: warranty
# ---------------------------------------------------------------------------


def setup_submitted_claim(
    api=None,
    clock=CLOCK_WARRANTY_UTC,
    claim_overrides=None,
    submitter_user_id=CLAIM_SUBMITTER_USER_ID,
    link_lot=True,
    ctx=None,
    **kwargs,
) -> dict:
    """A `SUBMITTED` claim against the canonical product line, filed by an
    identifier distinct from the one that will adjudicate it."""
    ctx = ctx or setup_graded_lot(api, **kwargs)
    api = ctx["api"]
    if clock:
        set_logical_clock(api, clock)
    extra = dict(claim_overrides or {})
    if link_lot:
        extra.setdefault("flooring_lot_id", ctx["lot"]["id"])
    ctx["claim_submitter_user_id"] = submitter_user_id
    ctx["claim"] = get_success_data(
        api.create_warranty_claim(
            create_warranty_claim_payload(ctx["product_line"]["id"], **extra),
            make_warranty_adjudicator_headers(submitter_user_id),
        )
    )
    return ctx


def setup_approved_claim(
    api=None,
    adjudication_overrides=None,
    adjudicator_user_id=CLAIM_ADJUDICATOR_USER_ID,
    ctx=None,
    **kwargs,
) -> dict:
    """Claim approved on inspector-verified figures, charging the reserve.  On
    the canonical line a verified 210 square feet commits 151474 cents."""
    ctx = ctx or setup_submitted_claim(api, **kwargs)
    api = ctx["api"]
    ctx["claim_adjudicator_user_id"] = adjudicator_user_id
    ctx["claim"] = get_success_data(
        api.adjudicate_claim(
            ctx["claim"]["id"],
            adjudicate_claim_payload(**(adjudication_overrides or {})),
            make_warranty_adjudicator_headers(adjudicator_user_id),
        )
    )
    ctx["product_line"] = refetch_product_line(api, ctx["product_line"]["id"])
    return ctx


def setup_warranty_line(api=None, clock=CLOCK_WARRANTY_UTC, line_overrides=None) -> dict:
    """Just a species and a product line carrying a funded reserve — the whole
    precondition for a warranty claim that names no installed lot."""
    api = api or _default_api
    set_logical_clock(api, clock)
    species = create_species(api)
    return {
        "api": api,
        "species": species,
        "product_line": create_product_line(api, species, **(line_overrides or {})),
    }


def setup_line_only_submitted_claim(
    api=None,
    clock=CLOCK_WARRANTY_UTC,
    line_overrides=None,
    claim_overrides=None,
    submitter_user_id=CLAIM_SUBMITTER_USER_ID,
) -> dict:
    """A `SUBMITTED` claim on a bare product line with no `flooring_lot_id`, so
    the reference moisture for adjudication is the species target."""
    ctx = setup_warranty_line(api, clock=clock, line_overrides=line_overrides)
    return setup_submitted_claim(
        ctx["api"],
        clock=clock,
        claim_overrides=claim_overrides,
        submitter_user_id=submitter_user_id,
        link_lot=False,
        ctx=ctx,
    )


def setup_line_only_approved_claim(
    api=None,
    adjudication_overrides=None,
    adjudicator_user_id=CLAIM_ADJUDICATOR_USER_ID,
    **kwargs,
) -> dict:
    """The same claim carried through an approval that commits 151474 cents."""
    ctx = setup_line_only_submitted_claim(api, **kwargs)
    return setup_approved_claim(
        ctx["api"],
        adjudication_overrides=adjudication_overrides,
        adjudicator_user_id=adjudicator_user_id,
        ctx=ctx,
    )


def setup_claim_with_scheduled_prefinish_run(api=None, ctx=None, **kwargs) -> dict:
    """A graded lot carrying a `SCHEDULED` prefinish run and a `SUBMITTED` claim
    on the same product line, so an approval can be watched cascading onto the
    run."""
    ctx = ctx or setup_scheduled_prefinish_run(api, **kwargs)
    return setup_submitted_claim(ctx["api"], ctx=ctx)


# ---------------------------------------------------------------------------
# Tier 7: multi-charge and multi-lot arrangements
# ---------------------------------------------------------------------------


def setup_two_charges_on_one_chamber(
    api=None,
    second_start_utc="2026-09-05T00:00:00.000Z",
    second_receipt=None,
    ctx=None,
    **kwargs,
) -> dict:
    """The canonical charge in `CONDITIONING` plus a downstream `SCHEDULED`
    charge on the same chamber holding its own allocated receipt, so an
    extension can be watched displacing it."""
    ctx = ctx or setup_conditioning_charge(api, **kwargs)
    api = ctx["api"]
    ctx["charge_b"] = create_charge(
        api,
        ctx["schedule"],
        ctx["chamber"],
        planned_start_utc=second_start_utc,
    )
    spec = second_receipt or {
        "received_board_feet": 3000,
        "accepted_board_feet": 2900,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    }
    receipt = create_accepted_receipt(api, ctx["species"], **spec)
    get_success_data(
        api.allocate_receipt(
            ctx["charge_b"]["id"], allocate_receipt_payload(receipt["id"]), OPERATOR
        )
    )
    ctx["receipt_b"] = refetch_receipt(api, receipt["id"])
    ctx["charge_b"] = refetch_charge(api, ctx["charge_b"]["id"])
    return ctx


def setup_second_lot_on_charge(
    api=None,
    input_dry_bf=100,
    lot_overrides=None,
    ctx=None,
    **kwargs,
) -> dict:
    """A second lot drawn from the same released charge and the same product
    line, for reservation and remaining-volume aggregation."""
    ctx = ctx or setup_planned_lot(api, **kwargs)
    api = ctx["api"]
    extra = dict(lot_overrides or {})
    if ctx.get("core_stock") is not None:
        extra.setdefault("core_stock_id", ctx["core_stock"]["id"])
    ctx["lot_b"] = get_success_data(
        api.create_flooring_lot(
            create_flooring_lot_payload(
                ctx["product_line"]["id"], ctx["charge"]["id"], input_dry_bf, **extra
            ),
            SUPERVISOR,
        )
    )
    ctx["charge"] = refetch_charge(api, ctx["charge"]["id"])
    return ctx


def setup_foreign_core_stock(api=None, ctx=None, **kwargs) -> dict:
    """A second engineered product line carrying its own core stock, so a lot on
    the first line can name a core row that belongs to somebody else."""
    ctx = ctx or setup_released_charge(api, **kwargs)
    api = ctx["api"]
    ctx["other_product_line"] = create_product_line(
        api,
        ctx["species"],
        line_code="ENG-RO-425",
        construction_type="ENGINEERED",
        nominal_width_in=4.250,
        material_value_cents_per_sf=690,
        warranty_funded_total_cents=350000,
    )
    ctx["foreign_core_stock"] = create_core_stock(
        api,
        ctx["other_product_line"],
        core_material="BIRCH_PLY",
        lot_reference="BP-2026-07",
        available_square_feet=20000.00,
    )
    return ctx


def setup_second_species_receipt(
    api=None,
    species_overrides=None,
    receipt_overrides=None,
    ctx=None,
    **kwargs,
) -> dict:
    """A receipt of a different species than the charge's governing schedule."""
    ctx = ctx or setup_scheduled_charge(api, **kwargs)
    api = ctx["api"]
    defaults = {
        "species_code": "HARD_MAPLE",
        "common_name": "Hard Maple",
        "density_class": "MEDIUM",
        "tangential_shrinkage_coefficient": 0.135,
    }
    defaults.update(species_overrides or {})
    ctx["other_species"] = create_species(api, **defaults)
    spec = {
        "received_board_feet": 3000,
        "accepted_board_feet": 2900,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    }
    spec.update(receipt_overrides or {})
    ctx["other_species_receipt"] = create_accepted_receipt(
        api, ctx["other_species"], **spec
    )
    return ctx


__all__ = [
    "CLOCK_BASE_UTC",
    "CLOCK_WARRANTY_UTC",
    "ADMIN",
    "CLERK",
    "OPERATOR",
    "SUPERVISOR",
    "INSPECTOR",
    "SCHEDULER",
    "BROKER",
    "ADJUDICATOR",
    "CANONICAL_RECEIPTS",
    "CANONICAL_BUNDLES",
    "QUARANTINE_BUNDLES",
    "QUARANTINE_MILLING",
    "set_logical_clock",
    "create_species",
    "create_schedule",
    "create_chamber",
    "create_charge",
    "create_receipt",
    "create_accepted_receipt",
    "create_product_line",
    "create_core_stock",
    "create_prefinish_line",
    "refetch_charge",
    "refetch_receipt",
    "refetch_chamber",
    "refetch_lot",
    "refetch_product_line",
    "refetch_grade_run",
    "refetch_prefinish_run",
    "refetch_claim",
    "refetch_core_stock",
    "refetch_batch",
    "fetch_lot_batches",
    "setup_mill_configuration",
    "setup_scheduled_charge",
    "setup_charge_with_receipts",
    "setup_loaded_charge",
    "setup_conditioning_charge",
    "setup_released_charge",
    "setup_redried_charge",
    "setup_planned_lot",
    "setup_milled_lot",
    "setup_lot_with_byproduct_sale",
    "setup_draft_grade_run",
    "setup_finalized_grade_run",
    "setup_graded_lot",
    "setup_quarantined_lot",
    "setup_prefinish_ready",
    "setup_scheduled_prefinish_run",
    "setup_submitted_claim",
    "setup_approved_claim",
    "setup_warranty_line",
    "setup_line_only_submitted_claim",
    "setup_line_only_approved_claim",
    "setup_claim_with_scheduled_prefinish_run",
    "setup_two_charges_on_one_chamber",
    "setup_second_lot_on_charge",
    "setup_foreign_core_stock",
    "setup_second_species_receipt",
]
