"""Catalog and order-placement claims: gene/panel/provider/order creation,
defaults, computed snapshots, parent relationships, enum/type constraints.

Translates queue B (Corner) section `entities` instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
GENETIC = TEST_USERS["counselor_headers"]


def test_create_gene_defaults_active_and_acmg_false(api):
    """PRD §3.1: "A gene is created with its HGNC `symbol` (for example, BRCA1),
    which must be unique across all gene rows and is compared case-sensitively,
    and an optional `is_acmg_reportable` flag that defaults to `false` and marks
    the gene as belonging to the ACMG secondary-findings list. A newly created
    gene begins in `ACTIVE` `status`."

    Design: Corner/entities/gene_create_returns_201_with_active_status_and_default_acmg_false
    """
    FX.set_clock()
    resp = api.create_gene({"symbol": "CDH1"}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["symbol"] == "CDH1"
    assert data["status"] == "ACTIVE"
    assert data["is_acmg_reportable"] is False
    assert data["version"] == 1


def test_create_gene_missing_symbol_rejected(api):
    """PRD §2.8: "Body well-formedness — required fields present, enums in range,
    integers non-negative, timestamps parseable ... surfaces as `ERR_INVALID_REQUEST`
    (HTTP 422)."
    PRD §3.1: "A gene is created with its HGNC `symbol`."

    Design: Corner/entities/gene_missing_symbol_returns_invalid_request
    """
    FX.set_clock()
    resp = api.create_gene({"is_acmg_reportable": True}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_get_unknown_gene_returns_gene_not_found(api):
    """PRD §2.5: "the server validates the path identifiers from left to right and
    rejects the request at the first identifier that does not resolve, returning
    that identifier's specific not-found error ... `ERR_GENE_NOT_FOUND`."

    Design: Corner/entities/gene_get_not_found_returns_gene_not_found
    """
    FX.set_clock()
    resp = api.get_gene("00000000-0000-4000-8000-000000000000", DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_GENE_NOT_FOUND.value, 404)


def test_create_panel_defaults_draft_zero_count_consent_true(api):
    """PRD §3.1: "A panel is created with a display `name`, a `list_price_cents`
    catalog price that must be a non-negative integer, and an optional
    `requires_consent` flag that defaults to `true`. A panel begins in `DRAFT`
    `status` with a `gene_count` of zero."

    Design: Corner/entities/panel_create_returns_draft_zero_gene_count_default_requires_consent_true
    """
    FX.set_clock()
    resp = api.create_panel({"name": "Default Panel", "list_price_cents": 12345}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["gene_count"] == 0
    assert data["requires_consent"] is True
    assert data["list_price_cents"] == 12345


def test_panel_gene_count_recomputed_on_add(api):
    """PRD §3.1: "The panel's `gene_count` is a derived figure equal to the number
    of `PanelGene` rows for that panel whose `status` is `INCLUDED`; memberships
    in `REMOVED` status are excluded from the count, and the count is recomputed
    whenever memberships change."

    Design: Corner/entities/panel_gene_count_recomputed_on_add
    """
    FX.set_clock()
    g1 = FX.create_gene("GC1A")
    g2 = FX.create_gene("GC1B")
    panel = get_success_data(api.create_panel(
        F.create_panel_payload(name="Count Panel"), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(g1["id"]), DIRECTOR))
    resp = api.add_panel_gene(panel["id"], F.add_panel_gene_payload(g2["id"]), DIRECTOR)
    validate_success(resp, 201)
    reread = validate_success(api.get_panel(panel["id"], DIRECTOR), 200)
    assert reread["gene_count"] == 2


def test_testorder_list_price_and_consent_snapshot_from_panel(api):
    """PRD §3.2: "The order captures an immutable snapshot of the panel's
    `list_price_cents` into its own `list_price_cents`, and a snapshot of the
    panel's `requires_consent` flag into `report_required_consent`."
    PRD §3.2: "Upon successful placement the order's `pipeline_status` is `ORDERED`
    and its `financial_status` is `PENDING`."

    Design: Corner/entities/testorder_list_price_snapshot_immutable_from_panel
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(list_price_cents=80000, requires_consent=False,
                                         gene_symbols=("GSNAP",), name="Snap Panel")
    provider = FX.create_provider()
    resp = api.create_test_order(
        F.create_test_order_payload(panel["id"], provider["id"], patient_mrn="MRN-SNAP"),
        INTAKE)
    data = validate_success(resp, 201)
    assert data["list_price_cents"] == 80000
    assert data["report_required_consent"] is False
    assert data["pipeline_status"] == "ORDERED"
    assert data["financial_status"] == "PENDING"


def test_order_against_draft_panel_rejected(api):
    """PRD §3.2: "The chosen panel must be in `PUBLISHED` status at order time; an
    order against a panel not in `PUBLISHED` status is rejected with
    `ERR_PANEL_NOT_PUBLISHED` (HTTP 409)."

    Design: Corner/entities/testorder_create_against_draft_panel_rejected_panel_not_published
    """
    FX.set_clock()
    g1 = FX.create_gene("GDRAFT")
    panel = get_success_data(api.create_panel(F.create_panel_payload(name="Draft Panel"), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(g1["id"]), DIRECTOR))
    provider = FX.create_provider()
    resp = api.create_test_order(
        F.create_test_order_payload(panel["id"], provider["id"], patient_mrn="MRN-DR"),
        INTAKE)
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_PUBLISHED.value, 409)


def test_order_unknown_provider_returns_provider_not_found(api):
    """PRD §2.5: "an unknown order id yields `ERR_ORDER_NOT_FOUND` ... The not-found
    errors are resource-specific: ... `ERR_PROVIDER_NOT_FOUND`."
    PRD §3.2: "The provider must have been registered beforehand."

    Design: Corner/entities/testorder_create_unknown_provider_returns_provider_not_found
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GPROV",), name="Prov Panel")
    resp = api.create_test_order(
        F.create_test_order_payload(panel["id"], "00000000-0000-4000-8000-0000000000aa",
                                    patient_mrn="MRN-NP"),
        INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value, 404)


def test_requisition_invalid_payer_enum_rejected(api):
    """PRD §3.2: "Creating it requires a `clinical_indication` (the ICD-like reason
    for testing) and an `insurance_payer`, which is one of `MEDICARE`,
    `COMMERCIAL`, or `SELF_PAY`."
    PRD §2.8: "enums in range ... surfaces as `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/requisition_invalid_payer_enum_returns_invalid_request
    """
    ctx = FX.setup_ordered(gene_symbols=("GPAY",), name="Pay Panel")
    resp = api.create_requisition(
        ctx["order"]["id"],
        {"clinical_indication": "dx", "insurance_payer": "TRICARE"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_specimen_invalid_type_enum_rejected(api):
    """PRD §3.4: "An `AccessioningTech` registers a physical specimen against the
    order with its `specimen_type` — one of `BLOOD`, `SALIVA`, or `TISSUE`."
    PRD §2.8: "enums in range ... surfaces as `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/specimen_invalid_type_enum_returns_invalid_request
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GSPEC",), name="Spec Panel")
    resp = api.create_specimen(
        ctx["order"]["id"],
        {"specimen_type": "URINE", "collected_at": "2026-06-18T00:00:00.000Z",
         "quantity_ng": 80}, ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_run_window_end_not_after_start_rejected(api):
    """PRD §2.8: "the two interval-ordering checks (a run's end strictly after its
    start, a slot's end strictly after its start) — surfaces as
    `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.5: "its `window_end` must be strictly after `window_start`."

    Design: Corner/entities/sequencer_run_window_end_not_after_start_returns_invalid_request
    """
    FX.set_clock()
    seq = FX.create_sequencer(instrument_name="NovaSeq-WIN")
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY",
                                 gene_symbols=("GWIN",), name="Win Panel")
    resp = api.schedule_run(
        seq["id"],
        F.schedule_run_payload(ctx["order"]["id"], "2026-06-20T10:00:00.000Z",
                               "2026-06-20T10:00:00.000Z"),
        ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_sequencer_default_turnaround_buffer_and_online(api):
    """PRD §3.5: "A `LabDirector` registers a `Sequencer` with a unique
    `instrument_name` and an optional `turnaround_buffer_minutes` that defaults to
    60; the instrument begins `ONLINE`."

    Design: Corner/entities/sequencer_create_default_turnaround_buffer_60
    """
    FX.set_clock()
    resp = api.create_sequencer({"instrument_name": "NovaSeq-DEF"}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["turnaround_buffer_minutes"] == 60
    assert data["status"] == "ONLINE"


def test_counselor_create_default_active(api):
    """PRD §3.11: "A genetic-counselor profile is registered by a `LabDirector` with
    a unique `counselor_name`; it begins `ACTIVE` and may be `INACTIVE`."

    Design: Corner/entities/counselor_create_default_active_status
    """
    FX.set_clock()
    resp = api.create_counselor({"counselor_name": "GC Alpha"}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"


def test_referral_optional_triggering_variant_defaults_null(api):
    """PRD §3.11: "an optional `triggering_variant_id` may name the variant that
    motivated it. A new referral begins in `REQUESTED` `status` with `slot_start`
    and `slot_end` null."

    Design: Corner/entities/referral_optional_triggering_variant_defaults_null
    """
    FX.set_clock()
    gc = FX.create_counselor("GC Opt")
    ctx = FX.setup_ordered(gene_symbols=("GREF",), name="Ref Panel")
    resp = api.create_referral(
        ctx["order"]["id"], F.create_referral_payload(gc["id"], reason="PATIENT_REQUEST"),
        GENETIC)
    data = validate_success(resp, 201)
    assert data["triggering_variant_id"] is None
    assert data["slot_start"] is None
    assert data["status"] == "REQUESTED"


def test_variant_is_incidental_true_for_offpanel_acmg_gene(api):
    """PRD §3.5: "At call time the server computes the variant's `is_incidental`
    flag: it is `true` precisely when the variant's gene is **not** on the order's
    panel gene list **and** the gene is ACMG-reportable, marking it as a secondary
    finding; otherwise it is `false`."
    PRD §3.5: "it starts with `classification` `UNCLASSIFIED`."

    Design: Corner/entities/variant_is_incidental_computed_true_for_offpanel_acmg_gene
    """
    FX.set_clock()
    on_gene = FX.create_gene("GONPANEL")
    off_gene = FX.create_gene("GOFFACMG", is_acmg_reportable=True)
    panel = get_success_data(api.create_panel(
        F.create_panel_payload(name="Inc Panel", requires_consent=False), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(on_gene["id"]), DIRECTOR))
    panel = get_success_data(api.publish_panel(panel["id"], DIRECTOR))
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_mrn="MRN-INC")
    FX.add_requisition(order["id"], "SELF_PAY")
    FX.submit_requisition(order["id"])
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    resp = api.create_variant(order["id"], F.create_variant_payload(off_gene["id"], hgvs="c.50A>G"),
                              TEST_USERS["molecular_headers"])
    data = validate_success(resp, 201)
    assert data["is_incidental"] is True
    assert data["classification"] == "UNCLASSIFIED"


def test_variant_offpanel_nonacmg_gene_rejected(api):
    """PRD §3.5: "The gene must either be `INCLUDED` on the order's panel, or — if it
    is not on the panel — must be an ACMG-reportable gene; a variant whose gene is
    neither included on the panel nor ACMG-reportable is rejected with
    `ERR_GENE_NOT_ON_PANEL` (HTTP 409)."

    Design: Corner/entities/variant_offpanel_nonacmg_gene_rejected_gene_not_on_panel
    """
    FX.set_clock()
    on_gene = FX.create_gene("GINC2")
    off_gene = FX.create_gene("GOFFPLAIN", is_acmg_reportable=False)
    panel = get_success_data(api.create_panel(
        F.create_panel_payload(name="Inc2 Panel", requires_consent=False), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(on_gene["id"]), DIRECTOR))
    panel = get_success_data(api.publish_panel(panel["id"], DIRECTOR))
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_mrn="MRN-INC2")
    FX.add_requisition(order["id"], "SELF_PAY")
    FX.submit_requisition(order["id"])
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    resp = api.create_variant(order["id"], F.create_variant_payload(off_gene["id"], hgvs="c.51A>G"),
                              TEST_USERS["molecular_headers"])
    validate_error(resp, ApiErrorId.ERR_GENE_NOT_ON_PANEL.value, 409)


def test_labclock_reflects_set_value(api):
    """PRD §2.4: "it advances only when an operator sets it explicitly by supplying
    the new instant as `to_iso8601`, which becomes the clock's `current_utc`."

    Design: Corner/entities/labclock_immutable_entity_initial_value_on_first_boot
    """
    get_success_data(api.set_clock("2026-03-15T08:30:00.000Z", DIRECTOR))
    resp = api.get_clock(ACCESSIONING)
    data = validate_success(resp, 200)
    assert data["current_utc"] == "2026-03-15T08:30:00.000Z"
