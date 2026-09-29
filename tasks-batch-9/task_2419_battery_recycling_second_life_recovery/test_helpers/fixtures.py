"""Composite state builders.

Every test starts against an empty database, so all preconditions have to be
built from scratch through the public API.  The chains here are the ones the
scenarios need repeatedly:

    bootstrap_network      clock + campus + counterparty + index quotes
    advance_intake         a shipment walked forward along the custody and
                           compliance dimensions, as far as a named stage
    advance_processing     a line, a campaign, triage, a lot, the assay ledger
                           and finalization, as far as a named stage
    build_world            the two above composed into one call

Higher-level wrappers (`posted_final_settlement`, `disputed_settlement`,
`umpire_round_settlement`, `credit_hold_world`, `permit_world`,
`large_four_metal_world` and its posted/disputed/umpire variants) return the
exact state a family of scenarios needs.

Each builder returns a plain ``dict`` context so callers can reach any row it
created; every builder also re-reads rows whose `version` it needs, so callers
never have to guess a version counter.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ASSAY_TECHNICIAN_USER_ID,
    CLOCK_INTAKE,
    CLOCK_PROCESS,
    CO_CLOSER_USER_ID,
    CO_SUBMITTER_USER_ID,
    DEFAULT_QUOTES,
    EIGHT_METAL_QUOTES,
    PLANT_OPERATOR_USER_ID,
    SETTLEMENT_ACCOUNTANT_USER_ID,
    TRIAGE_ENGINEER_USER_ID,
)
from .test_users import (
    TEST_USERS,
    make_assay_technician_headers,
    make_compliance_officer_headers,
    make_plant_operator_headers,
    make_settlement_accountant_headers,
    make_supplier_rep_headers,
    make_triage_engineer_headers,
)

# --------------------------------------------------------------------------
# Canonical actor headers used by the builders
# --------------------------------------------------------------------------
ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["market_analyst_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
OPERATOR = make_plant_operator_headers(PLANT_OPERATOR_USER_ID)
SUBMITTER = make_compliance_officer_headers(CO_SUBMITTER_USER_ID)
CLOSER = make_compliance_officer_headers(CO_CLOSER_USER_ID)
ENGINEER = make_triage_engineer_headers(TRIAGE_ENGINEER_USER_ID)
TECHNICIAN = make_assay_technician_headers(ASSAY_TECHNICIAN_USER_ID)
ACCOUNTANT = make_settlement_accountant_headers(SETTLEMENT_ACCOUNTANT_USER_ID)
CERTIFIER = TEST_USERS["certification_officer_headers"]

# --------------------------------------------------------------------------
# Reusable input specifications
# --------------------------------------------------------------------------

# One 100 kg module whose CONSERVATIVE score lands in grade D, so triage
# routes it to the recovery queue and it becomes chargeable.
DEFAULT_MODULES = ({"serial_code": "M-1"},)

# Two 400 kg modules, an 800 kg charge.
TWO_LARGE_MODULES = (
    {"serial_code": "M-1", "mass_kg": 400.0},
    {"serial_code": "M-2", "mass_kg": 400.0},
)

# The 800 kg shipment that carries all four payable assays plus contamination,
# so every term of the payable waterfall is exercised at once.
LARGE_FOUR_METAL_INTAKE = {
    "gross_mass_kg": 850.0,
    "packaging_tare_kg": 50.0,
    "declared_ni_pct": 12.0,
    "declared_co_pct": 4.0,
    "declared_li_pct": 2.5,
    "declared_cu_pct": 8.0,
    "moisture_pct": 3.0,
    "foreign_material_pct": 2.0,
}

# The single nickel stream booked against the default 100 kg charge.
DEFAULT_OUTPUTS = (("NI", 30.000, 99.20),)

# Six streams, including the two non-payable ones, totalling 312.000 kg.
SIX_METAL_OUTPUTS = (
    ("NI", 68.002, 99.20),
    ("CO", 30.003, 99.00),
    ("LI", 18.000, 98.50),
    ("CU", 60.001, 99.50),
    ("MN", 45.994, 96.00),
    ("GRAPHITE", 90.000, 94.00),
)

INTAKE_STAGES = (
    "intake",
    "identify",
    "modules",
    "discharge",
    "package",
    "manifest",
    "manifest_closed",
    "released",
)
PROCESSING_STAGES = (
    "line",
    "campaign",
    "triaged",
    "process_clock",
    "campaign_started",
    "lot",
    "charged",
    "outputs",
    "finalized",
)
WORLD_STAGES = ("network",) + INTAKE_STAGES + PROCESSING_STAGES


# --------------------------------------------------------------------------
# Internal plumbing
# --------------------------------------------------------------------------

def _ok(response, label):
    """Unwrap a setup response, failing loudly when a precondition did not build."""
    assert response.status_code in (200, 201), (
        f"setup step '{label}' failed with HTTP {response.status_code}: {response.text}"
    )
    return get_success_data(response)


def _reached(stage, target, order):
    """True while `stage` is at or before `target` in `order`."""
    assert target in order, f"unknown stage {target!r}; expected one of {order}"
    return order.index(stage) <= order.index(target)


# --------------------------------------------------------------------------
# Single-call helpers
# --------------------------------------------------------------------------

def move_clock(client, to_iso8601, headers=None):
    return _ok(
        client.set_clock(f.set_clock_payload(to_iso8601), headers or ADMIN),
        f"move clock to {to_iso8601}",
    )


def create_facility(client, headers=None, **overrides):
    return _ok(
        client.create_facility(f.create_facility_payload(**overrides), headers or ADMIN),
        "create campus",
    )


def create_supplier(client, headers=None, **overrides):
    return _ok(
        client.create_supplier(f.create_supplier_payload(**overrides), headers or ADMIN),
        "create counterparty",
    )


def log_quality_strikes(client, supplier_id, incident_codes, headers=None):
    """Drive a counterparty's quality_strike_count up one incident at a time."""
    supplier = None
    for code in incident_codes:
        supplier = _ok(
            client.create_quality_strike(
                supplier_id,
                f.create_quality_strike_payload(code),
                headers or make_compliance_officer_headers(CO_SUBMITTER_USER_ID),
            ),
            f"log quality incident {code}",
        )
    return supplier


def publish_quote(client, metal, price_cents_per_kg, effective_date, headers=None, **overrides):
    return _ok(
        client.create_metal_index_price(
            f.create_metal_index_price_payload(
                metal=metal,
                price_cents_per_kg=price_cents_per_kg,
                effective_date=effective_date,
                **overrides,
            ),
            headers or ANALYST,
        ),
        f"publish {metal} quote effective {effective_date}",
    )


def publish_quotes(client, quotes, headers=None):
    """Publish a list of {metal, effective_date, price_cents_per_kg} rows."""
    return [
        publish_quote(
            client,
            quote["metal"],
            quote["price_cents_per_kg"],
            quote["effective_date"],
            headers=headers,
        )
        for quote in quotes
    ]


def book_intake(client, supplier_id, facility_id, headers=None, **overrides):
    return _ok(
        client.create_intake(
            f.create_intake_payload(supplier_id, facility_id, **overrides),
            headers or CLERK,
        ),
        "book shipment",
    )


def read_intake(client, intake_id, headers=None):
    return _ok(client.get_intake(intake_id, headers or CLERK), "read shipment")


def identify_chemistry(client, intake_id, identified_chemistry=None, headers=None):
    return _ok(
        client.identify_chemistry(
            intake_id, f.identify_chemistry_payload(identified_chemistry), headers or CLERK
        ),
        "record identified chemistry",
    )


def add_module(client, intake_id, serial_code, headers=None, **overrides):
    """Book one module, threading the shipment's current version into the write."""
    intake = read_intake(client, intake_id, headers=headers or CLERK)
    return _ok(
        client.create_module(
            intake_id,
            f.create_module_payload(serial_code, intake["version"], **overrides),
            headers or CLERK,
        ),
        f"book module {serial_code}",
    )


def add_modules(client, intake_id, specs, headers=None):
    modules = []
    for spec in specs:
        spec = dict(spec)
        serial_code = spec.pop("serial_code")
        modules.append(add_module(client, intake_id, serial_code, headers=headers, **spec))
    return modules


def discharge(client, intake_id, soc_pct=None, headers=None):
    return _ok(
        client.discharge_intake(intake_id, f.discharge_payload(soc_pct), headers or OPERATOR),
        "record state-of-charge measurement",
    )


def package(client, intake_id, packaging_type=None, headers=None):
    return _ok(
        client.package_intake(intake_id, f.package_payload(packaging_type), headers or OPERATOR),
        "package the discharged cells",
    )


def submit_manifest(client, intake_id, headers=None, **overrides):
    return _ok(
        client.submit_manifest(
            intake_id, f.submit_manifest_payload(**overrides), headers or SUBMITTER
        ),
        "submit hazmat manifest",
    )


def close_manifest(client, intake_id, manifest_id, headers=None):
    return _ok(
        client.close_manifest(intake_id, manifest_id, headers or CLOSER),
        "counter-sign hazmat manifest",
    )


def reject_manifest(client, intake_id, manifest_id, rejection_reason, headers=None):
    return _ok(
        client.reject_manifest(
            intake_id,
            manifest_id,
            f.reject_manifest_payload(rejection_reason),
            headers or make_compliance_officer_headers("co-inspector-3"),
        ),
        "reject hazmat manifest",
    )


def release(client, intake_id, headers=None):
    return _ok(client.release_intake(intake_id, headers or OPERATOR), "release custody")


def settlement_for_intake(client, intake_id, headers=None):
    """The provisional settlement is a cascade-created child: find it by list."""
    data = _ok(
        client.list_settlements(headers or ACCOUNTANT, params={"intake_id": intake_id}),
        "list settlements of the shipment",
    )
    assert data, f"release should have cut a settlement for shipment {intake_id}"
    return data[0]


def read_settlement(client, settlement_id, headers=None):
    return _ok(
        client.get_settlement(settlement_id, headers or ACCOUNTANT), "read settlement"
    )


def triage_module(
    client, module_id, scoring_variant="CONSERVATIVE", override_disposition=None, headers=None
):
    return _ok(
        client.create_triage_decision(
            module_id,
            f.create_triage_decision_payload(scoring_variant, override_disposition),
            headers or ENGINEER,
        ),
        "record triage decision",
    )


def create_line(client, facility_id, headers=None, **overrides):
    return _ok(
        client.create_processing_line(
            f.create_processing_line_payload(facility_id, **overrides), headers or ADMIN
        ),
        "commission processing line",
    )


def create_campaign(client, line_id, headers=None, **overrides):
    return _ok(
        client.create_campaign(
            f.create_campaign_payload(line_id, **overrides), headers or OPERATOR
        ),
        "schedule campaign",
    )


def start_campaign(client, campaign_id, headers=None):
    return _ok(client.start_campaign(campaign_id, headers or OPERATOR), "start campaign")


def open_lot(client, campaign_id, lot_code=None, headers=None):
    return _ok(
        client.create_lot(campaign_id, f.create_lot_payload(lot_code), headers or OPERATOR),
        "open recovery lot",
    )


def read_lot(client, lot_id, headers=None):
    return _ok(client.get_lot(lot_id, headers or OPERATOR), "read recovery lot")


def charge_lot(client, lot_id, module_ids, headers=None):
    """Charge modules into a lot, threading the lot's current version into the write."""
    lot = read_lot(client, lot_id, headers=headers or OPERATOR)
    return _ok(
        client.charge_lot(
            lot_id, f.charge_lot_payload(module_ids, lot["version"]), headers or OPERATOR
        ),
        "charge modules into the lot",
    )


def book_output(client, lot_id, metal, recovered_mass_kg, assay_purity_pct, headers=None):
    return _ok(
        client.create_recovery_output(
            lot_id,
            f.create_recovery_output_payload(metal, recovered_mass_kg, assay_purity_pct),
            headers or TECHNICIAN,
        ),
        f"book {metal} assay line",
    )


def book_outputs(client, lot_id, specs, headers=None):
    return [
        book_output(client, lot_id, metal, mass, purity, headers=headers)
        for metal, mass, purity in specs
    ]


def finalize_lot(client, lot_id, residue_mass_kg, headers=None):
    return _ok(
        client.finalize_lot(
            lot_id, f.finalize_lot_payload(residue_mass_kg), headers or TECHNICIAN
        ),
        "finalize the lot",
    )


def create_allotment(client, facility_id, headers=None, **overrides):
    return _ok(
        client.create_permit_allotment(
            f.create_permit_allotment_payload(facility_id, **overrides),
            headers or make_compliance_officer_headers(CO_SUBMITTER_USER_ID),
        ),
        "record permit allotment",
    )


def book_discharge_event(
    client, lot_id, allotment_id, event_date, mass_kg, headers=None, **overrides
):
    return _ok(
        client.create_discharge_event(
            lot_id,
            f.create_discharge_event_payload(allotment_id, event_date, mass_kg, **overrides),
            headers or make_compliance_officer_headers(CO_SUBMITTER_USER_ID),
        ),
        "book discharge event",
    )


def post_settlement(client, settlement_id, headers=None):
    return _ok(
        client.post_settlement(settlement_id, headers or ACCOUNTANT), "post settlement"
    )


def dispute_settlement(client, settlement_id, supplier_id, dispute_reason, headers=None):
    return _ok(
        client.dispute_settlement(
            settlement_id,
            f.dispute_settlement_payload(dispute_reason),
            headers or make_supplier_rep_headers(supplier_id),
        ),
        "dispute settlement",
    )


def record_umpire_assay(client, settlement_id, metal, umpire_contained_kg, headers=None):
    return _ok(
        client.record_umpire_assay(
            settlement_id,
            f.umpire_assay_payload(metal, umpire_contained_kg),
            headers or TECHNICIAN,
        ),
        "record umpire assay",
    )


def apply_umpire(client, settlement_id, headers=None):
    return _ok(
        client.apply_umpire(settlement_id, headers or ACCOUNTANT), "apply umpire result"
    )


def void_settlement(client, settlement_id, void_reason, headers=None):
    return _ok(
        client.void_settlement(
            settlement_id, f.void_settlement_payload(void_reason), headers or ACCOUNTANT
        ),
        "void settlement",
    )


def issue_passport(client, lot_id, headers=None, **overrides):
    return _ok(
        client.issue_passport(lot_id, f.issue_passport_payload(**overrides), headers or CERTIFIER),
        "issue battery passport",
    )


# --------------------------------------------------------------------------
# Composite builders
# --------------------------------------------------------------------------

def bootstrap_network(
    client,
    *,
    clock=CLOCK_INTAKE,
    facility=None,
    supplier=None,
    quotes=DEFAULT_QUOTES,
):
    """Clock, campus, counterparty and the published price feed.

    `facility` and `supplier` are override dicts for their creation payloads;
    `quotes` is a list of quote rows, or None to publish no price feed at all.
    """
    ctx = {"client": client, "intakes": [], "modules": [], "outputs": []}
    if clock is not None:
        ctx["clock"] = move_clock(client, clock)
    ctx["facility"] = create_facility(client, **(facility or {}))
    ctx["supplier"] = create_supplier(client, **(supplier or {}))
    ctx["quotes"] = publish_quotes(client, quotes) if quotes else []
    return ctx


def advance_intake(
    ctx,
    *,
    stop_after="released",
    intake=None,
    identified_chemistry=None,
    modules=DEFAULT_MODULES,
    soc_pct=None,
    packaging_type=None,
    manifest=None,
    submitter=None,
    closer=None,
):
    """Walk one shipment forward through the custody and compliance dimensions.

    Stages, in order: intake, identify, modules, discharge, package, manifest,
    manifest_closed, released.  Every row created is recorded on `ctx` and the
    freshly built chain is also returned as its own dict.
    """
    client = ctx["client"]
    reached = lambda stage: _reached(stage, stop_after, INTAKE_STAGES)  # noqa: E731
    chain = {"modules": [], "manifest": None, "settlement": None}

    chain["intake"] = book_intake(
        client, ctx["supplier"]["id"], ctx["facility"]["id"], **(intake or {})
    )
    intake_id = chain["intake"]["id"]

    if reached("identify"):
        chain["intake"] = identify_chemistry(client, intake_id, identified_chemistry)
    if reached("modules") and modules:
        chain["modules"] = add_modules(client, intake_id, modules)
        chain["intake"] = read_intake(client, intake_id)
    if reached("discharge"):
        chain["intake"] = discharge(client, intake_id, soc_pct)
    if reached("package"):
        chain["intake"] = package(client, intake_id, packaging_type)
    if reached("manifest"):
        chain["manifest"] = submit_manifest(
            client, intake_id, headers=submitter, **(manifest or {})
        )
        chain["intake"] = read_intake(client, intake_id)
    if reached("manifest_closed"):
        chain["manifest"] = close_manifest(
            client, intake_id, chain["manifest"]["id"], headers=closer
        )
        chain["intake"] = read_intake(client, intake_id)
    if reached("released"):
        chain["intake"] = release(client, intake_id)
        chain["settlement"] = settlement_for_intake(client, intake_id)

    ctx["intakes"].append(chain)
    ctx["intake"] = chain["intake"]
    ctx["modules"] = chain["modules"]
    ctx["manifest"] = chain["manifest"]
    ctx["settlement"] = chain["settlement"]
    return chain


def advance_processing(
    ctx,
    *,
    stop_after="finalized",
    line=None,
    campaign=None,
    scoring_variant="CONSERVATIVE",
    override_disposition=None,
    process_clock=CLOCK_PROCESS,
    lot_code=None,
    module_ids=None,
    outputs=DEFAULT_OUTPUTS,
    residue_mass_kg=67.0,
):
    """Commission a line, schedule and start a campaign, triage the shipment's
    modules into the recovery queue, then open, charge, assay and finalize a lot.

    Stages, in order: line, campaign, triaged, process_clock, campaign_started,
    lot, charged, outputs, finalized.
    """
    client = ctx["client"]
    reached = lambda stage: _reached(stage, stop_after, PROCESSING_STAGES)  # noqa: E731

    ctx["line"] = create_line(client, ctx["facility"]["id"], **(line or {}))
    if reached("campaign"):
        ctx["campaign"] = create_campaign(client, ctx["line"]["id"], **(campaign or {}))
    if reached("triaged"):
        ctx["decisions"] = [
            triage_module(
                client,
                module["id"],
                scoring_variant=scoring_variant,
                override_disposition=override_disposition,
            )
            for module in ctx["modules"]
        ]
        ctx["modules"] = [
            _ok(client.get_module(module["id"], OPERATOR), "read module")
            for module in ctx["modules"]
        ]
    if reached("process_clock") and process_clock is not None:
        ctx["clock"] = move_clock(client, process_clock)
    if reached("campaign_started"):
        ctx["campaign"] = start_campaign(client, ctx["campaign"]["id"])
    if reached("lot"):
        ctx["lot"] = open_lot(client, ctx["campaign"]["id"], lot_code)
    if reached("charged"):
        ids = module_ids if module_ids is not None else [m["id"] for m in ctx["modules"]]
        ctx["lot"] = charge_lot(client, ctx["lot"]["id"], ids)
    if reached("outputs") and outputs:
        ctx["outputs"] = book_outputs(client, ctx["lot"]["id"], outputs)
        ctx["lot"] = read_lot(client, ctx["lot"]["id"])
    if reached("finalized"):
        ctx["lot"] = finalize_lot(client, ctx["lot"]["id"], residue_mass_kg)
        if ctx["intakes"] and ctx["intakes"][0]["settlement"]:
            ctx["settlement"] = read_settlement(
                client, ctx["intakes"][0]["settlement"]["id"]
            )
            ctx["intakes"][0]["settlement"] = ctx["settlement"]
    return ctx


def build_world(client, *, stop_after="finalized", network=None, intake=None, processing=None):
    """Bootstrap the network and walk one shipment as far as `stop_after`.

    `stop_after` names any stage of WORLD_STAGES.  `network`, `intake` and
    `processing` are keyword-argument dicts forwarded to the three builders.
    """
    assert stop_after in WORLD_STAGES, (
        f"unknown stage {stop_after!r}; expected one of {WORLD_STAGES}"
    )
    ctx = bootstrap_network(client, **(network or {}))
    if stop_after == "network":
        return ctx
    if stop_after in INTAKE_STAGES:
        advance_intake(ctx, stop_after=stop_after, **(intake or {}))
        return ctx
    advance_intake(ctx, stop_after="released", **(intake or {}))
    advance_processing(ctx, stop_after=stop_after, **(processing or {}))
    return ctx


# --------------------------------------------------------------------------
# Named worlds the scenarios ask for repeatedly
# --------------------------------------------------------------------------

def released_intake(client, **kwargs):
    """A shipment released with its provisional settlement cut."""
    return build_world(client, stop_after="released", **kwargs)


def charged_lot(client, **kwargs):
    """A running campaign with one charged lot and no assay lines yet."""
    return build_world(client, stop_after="charged", **kwargs)


def finalized_lot(client, **kwargs):
    """A finalized lot whose contributing settlement has flipped to FINAL."""
    return build_world(client, stop_after="finalized", **kwargs)


def posted_final_settlement(client, **kwargs):
    """A FINAL settlement moved DRAFT -> POSTED."""
    ctx = finalized_lot(client, **kwargs)
    ctx["settlement"] = post_settlement(ctx["client"], ctx["settlement"]["id"])
    ctx["supplier"] = _ok(
        ctx["client"].get_supplier(ctx["supplier"]["id"], ACCOUNTANT), "read counterparty"
    )
    return ctx


def disputed_settlement(
    client, dispute_reason="Nickel assay 3.50 pp below declared", **kwargs
):
    """A POSTED FINAL settlement disputed by the counterparty's representative."""
    ctx = posted_final_settlement(client, **kwargs)
    ctx["settlement"] = dispute_settlement(
        ctx["client"], ctx["settlement"]["id"], ctx["supplier"]["id"], dispute_reason
    )
    return ctx


def umpire_round_settlement(
    client, metal="NI", umpire_contained_kg=80.000, **kwargs
):
    """A disputed settlement with an umpire laboratory result on the record."""
    ctx = disputed_settlement(client, **kwargs)
    ctx["settlement"] = record_umpire_assay(
        ctx["client"], ctx["settlement"]["id"], metal, umpire_contained_kg
    )
    return ctx


def credit_hold_world(client, *, second_intake_stop_after="intake", second_intake=None):
    """Two shipments from one counterparty whose credit limit the first
    settlement breaches when it posts.

    The first shipment is finalized and its FINAL settlement posted, which puts
    the counterparty on credit hold; the second shipment is walked only as far
    as `second_intake_stop_after`.
    """
    ctx = bootstrap_network(client, supplier={"credit_limit_cents": 20_000})
    first = advance_intake(ctx, stop_after="released")
    second_opts = dict(second_intake or {})
    second_opts.setdefault("intake", {"gross_mass_kg": 60.0, "declared_ni_pct": 11.0})
    second_opts["intake"] = dict(second_opts["intake"])
    second_opts["intake"].setdefault("packaging_tare_kg", 10.0)
    # The second shipment carries no modules: its 50 kg net mass is smaller than
    # the default module, and none of the credit scenarios process it.
    second_opts.setdefault("modules", ())
    second = advance_intake(ctx, stop_after=second_intake_stop_after, **second_opts)

    ctx["modules"] = first["modules"]
    advance_processing(ctx, stop_after="finalized")
    ctx["settlement"] = post_settlement(client, first["settlement"]["id"])
    ctx["first_intake"] = read_intake(client, first["intake"]["id"])
    ctx["second_intake"] = read_intake(client, second["intake"]["id"])
    ctx["supplier"] = _ok(
        client.get_supplier(ctx["supplier"]["id"], ACCOUNTANT), "read counterparty"
    )
    ctx["first"] = first
    ctx["second"] = second
    return ctx


def read_supplier(client, supplier_id, headers=None):
    return _ok(
        client.get_supplier(supplier_id, headers or ACCOUNTANT), "read counterparty"
    )


def large_four_metal_world(
    client,
    *,
    stop_after="finalized",
    residue_mass_kg=464.0,
    outputs=SIX_METAL_OUTPUTS,
    credit_limit_cents=200_000,
    modules=TWO_LARGE_MODULES,
    intake=None,
):
    """The 800 kg shipment priced on both quote curves.

    Both price series are published, so the provisional pricing reads the July
    quotes at received_at and the final re-pricing reads the August quotes at
    finalized_at.  Six assay streams totalling 312.000 kg are booked and the
    default residue puts `mass_balance_pct` exactly on the 97.00 floor.

    `stop_after` may name any stage of WORLD_STAGES.
    """
    return build_world(
        client,
        stop_after=stop_after,
        network={
            "quotes": EIGHT_METAL_QUOTES,
            "supplier": {"credit_limit_cents": credit_limit_cents},
        },
        intake={
            "intake": dict(LARGE_FOUR_METAL_INTAKE, **(intake or {})),
            "modules": modules,
        },
        processing={"outputs": outputs, "residue_mass_kg": residue_mass_kg},
    )


def large_four_metal_posted(client, **kwargs):
    """The 800 kg world with its FINAL settlement moved DRAFT -> POSTED."""
    ctx = large_four_metal_world(client, **kwargs)
    ctx["settlement"] = post_settlement(client, ctx["settlement"]["id"])
    ctx["supplier"] = read_supplier(client, ctx["supplier"]["id"])
    return ctx


def large_four_metal_disputed(
    client, dispute_reason="Nickel assay 3.50 pp below declared", **kwargs
):
    """The 800 kg world with the posted settlement under dispute."""
    ctx = large_four_metal_posted(client, **kwargs)
    ctx["settlement"] = dispute_settlement(
        client, ctx["settlement"]["id"], ctx["supplier"]["id"], dispute_reason
    )
    return ctx


def large_four_metal_umpire_round(
    client, metal="NI", umpire_contained_kg=80.000, **kwargs
):
    """The 800 kg world with an umpire laboratory result on the record."""
    ctx = large_four_metal_disputed(client, **kwargs)
    ctx["settlement"] = record_umpire_assay(
        client, ctx["settlement"]["id"], metal, umpire_contained_kg
    )
    return ctx


def permit_world(client, *, allotment=None, **kwargs):
    """A charged lot plus an active water permit allotment on the same campus."""
    ctx = charged_lot(client, **kwargs)
    ctx["allotment"] = create_allotment(
        ctx["client"], ctx["facility"]["id"], **(allotment or {})
    )
    return ctx


def read_allotment(client, allotment_id, headers=None):
    return _ok(
        client.get_permit_allotment(
            allotment_id, headers or make_compliance_officer_headers(CO_SUBMITTER_USER_ID)
        ),
        "read permit allotment",
    )
