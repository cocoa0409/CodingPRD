"""Block and slide production: state gates, per-event tissue accounting,
depletion cascade, recut cycle, and immediate derived-field visibility."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    ApiErrorId,
    accession_specimen,
    assert_block,
    assert_slide,
    cancel_case,
    create_block,
    create_case,
    create_patient,
    create_slide,
    embed_block,
    get_block,
    get_case,
    get_slide,
    get_specimen,
    gross_specimen,
    qc_review_slide,
    recut_slide,
    section_slide,
    setup_workup_case,
    stain_complete_slide,
    validate_error,
    validate_success,
)


def test_block_before_gross_rejected(api):
    """PRD §3.3: "Block creation requires the specimen to be in `GROSSING` or
    `PROCESSING` — attempting it on an `ACCESSIONED` specimen is rejected with
    `ERR_GROSS_NOT_RECORDED` (HTTP 409)"

    Design: Corner/errors/block_before_gross_rejected
    """
    patient = create_patient(mrn="MRN-R1", full_name="Err One")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(case["id"], patient_mrn="MRN-R1")
    resp = api.create_block(specimen["id"], {"block_label": "A1"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_GROSS_NOT_RECORDED)


def test_slide_on_unembedded_block_rejected(api):
    """PRD §3.3: "The block's state is reported precisely: targeting a block
    still in `CREATED` yields `ERR_BLOCK_NOT_EMBEDDED` (HTTP 409), while
    targeting a `DEPLETED` block yields the dedicated `ERR_BLOCK_DEPLETED`
    (HTTP 409) — the same pairing applies to sectioning and recutting."

    Design: Corner/errors/slide_on_unembedded_block_rejected
    """
    ctx = setup_workup_case(mrn="MRN-R2", num_blocks=1, embed_blocks=False)
    block = ctx["blocks"][0]
    resp = api.create_slide(block["id"], {"slide_label": "A1-1"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_EMBEDDED)


def test_embed_twice_returns_state_error(api):
    """PRD §3.3: "A `Histotech` then embeds a `CREATED` block, moving it to
    `EMBEDDED`; embedding from any other state is rejected with
    `ERR_BLOCK_NOT_CREATED` (HTTP 409)."

    Design: Corner/errors/embed_twice_returns_state_error
    """
    ctx = setup_workup_case(mrn="MRN-R3", num_blocks=1)
    block = ctx["blocks"][0]
    assert block["status"] == "EMBEDDED"
    resp = api.embed_block(block["id"], HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_CREATED)
    assert get_block(block["id"])["status"] == "EMBEDDED"


def test_slide_qc_review_from_ordered_rejected(api):
    """PRD §3.3: "Any of these slide actions attempted from the wrong slide
    state is rejected with `ERR_SLIDE_WRONG_STATE` (HTTP 409)."
    PRD §3.3: "QC review of a `STAINED` slide takes a `result` payload"

    Design: Corner/state_machines/slide_qc_review_from_ordered_rejected
    """
    ctx = setup_workup_case(mrn="MRN-S1", num_blocks=1, slides_per_block=1)
    slide = ctx["slides"][0]
    resp = api.qc_review_slide(slide["id"], {"result": "PASS"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SLIDE_WRONG_STATE)
    assert get_slide(slide["id"])["status"] == "ORDERED"


def test_insufficient_tissue_rejected_and_exact_zero_depletes(api):
    """PRD §3.3: "a consumption that would drive the remaining tissue below 0.0
    is rejected outright with `ERR_INSUFFICIENT_TISSUE` (HTTP 422) and no
    mutation is applied"
    PRD §3.3: "When the resulting remainder falls strictly below 5.0 percent,
    the block can no longer be recut and transitions `EMBEDDED → DEPLETED`
    automatically"

    Design: Corner/calculations/insufficient_tissue_rejected_and_exact_zero_depletes
    """
    ctx = setup_workup_case(mrn="MRN-C2", num_blocks=1, slides_per_block=2)
    block = ctx["blocks"][0]
    s1, s2 = ctx["slides"]

    resp = api.section_slide(s1["id"], {"consumption_pct": 100.01}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TISSUE)
    assert get_slide(s1["id"])["status"] == "ORDERED", "rejected section mutates nothing"

    sectioned = section_slide(s2["id"], consumption_pct=100.0)
    assert sectioned["status"] == "SECTIONED"
    block_after = get_block(block["id"])
    assert block_after["tissue_remaining_pct"] == 0.0
    assert block_after["status"] == "DEPLETED", "0.0 is strictly below the 5.0 minimum"


def test_immediate_visibility_of_mutation_and_derived_fields(api):
    """PRD §3.3: "A new block starts in `CREATED` status with
    `tissue_remaining_pct` at exactly 100.0 and `on_loan` false, and the very
    first block created under a specimen moves that specimen
    `GROSSING → PROCESSING`."
    PRD §3.3: "A case's `complexity_score` is the maximum specimen base weight
    among its non-`REJECTED` specimens — 1 for `BIOPSY`, 2 for `EXCISION`, 3
    for `RESECTION`, 0 for `CYTOLOGY`, and 0 when no non-rejected specimen
    exists — plus 1.0 for every block of the case regardless of block status
    (`DEPLETED` included)"
    PRD §2.6: "Hierarchical consistency is maintained by automatic
    reconciliation rather than by client choreography."

    Design: Corner/consistency_model/immediate_visibility_of_mutation_and_derived_fields
    """
    patient = create_patient(mrn="MRN-CM1", full_name="Cons One")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(case["id"], patient_mrn="MRN-CM1")
    gross_specimen(specimen["id"])

    resp = api.create_block(specimen["id"], {"block_label": "A1"}, HISTOTECH_HEADERS)
    block = validate_success(resp, expected_status=201)
    assert_block(block)
    assert block["status"] == "CREATED"
    assert block["tissue_remaining_pct"] == 100.0
    assert block["on_loan"] is False

    # Immediately visible on the parent: BIOPSY base 1 + one block = 2.0.
    case_after = get_case(case["id"])
    assert case_after["complexity_score"] == 2.0
    assert case_after["complexity_class"] == "SIMPLE"
    assert get_specimen(specimen["id"])["status"] == "PROCESSING"


def test_block_tissue_per_event_rounding(api):
    """PRD §2.7: "Tissue percentages (`tissue_remaining_pct`, `consumption_pct`)
    are carried at 1 decimal place using round-half-up. Crucially, rounding is
    applied **per consumption event before summation**: each section or recut
    event's consumption is rounded to 1 decimal first, and only then is the sum
    taken. Summing raw values and rounding once at the end is a different,
    forbidden algorithm — for example, three raw events of 3.33, 3.33, and 3.34
    yield a remainder of 90.1 under the pinned per-event order but 90.0 under
    sum-then-round."

    Design: Difficulty/combinatorial_formula/block_tissue_per_event_rounding
    """
    ctx = setup_workup_case(mrn="MRN-301", num_blocks=1, slides_per_block=2)
    block = ctx["blocks"][0]
    s1, s2 = ctx["slides"]
    section_slide(s1["id"], consumption_pct=3.33)
    section_slide(s2["id"], consumption_pct=3.33)
    stain_complete_slide(s2["id"])
    qc_review_slide(s2["id"], result="FAIL", reason="folded tissue")
    recut_slide(s2["id"], consumption_pct=3.34)

    block_after = get_block(block["id"])
    # Per-event rounding: 100.0 - (3.3 + 3.3 + 3.3) = 90.1.
    assert block_after["tissue_remaining_pct"] == 90.1, (
        f"per-event round-then-sum must yield 90.1, got {block_after['tissue_remaining_pct']}"
    )
    assert block_after["status"] == "EMBEDDED"


def test_block_tissue_per_event_rounding_slide_value_replaced(api):
    """PRD §3.3: "A failed slide is not dead: recutting moves it
    `QC_FAILED → SECTIONED` under exactly the same block-state and consumption
    rules as the original section, replacing the slide's `consumption_pct` with
    the new event's rounded value and debiting the block again."
    PRD §3.3: "The accepted consumption is rounded half-up to 1 decimal and
    recorded on the slide's `consumption_pct`"

    Design: Difficulty/combinatorial_formula/block_tissue_per_event_rounding
    """
    ctx = setup_workup_case(mrn="MRN-301", num_blocks=1, slides_per_block=2)
    s1, s2 = ctx["slides"]
    section_slide(s1["id"], consumption_pct=3.33)
    section_slide(s2["id"], consumption_pct=3.33)
    stain_complete_slide(s2["id"])
    qc_review_slide(s2["id"], result="FAIL", reason="folded tissue")

    recut = recut_slide(s2["id"], consumption_pct=3.34)
    assert_slide(recut)
    assert recut["status"] == "SECTIONED"
    # The recut event's rounded value (3.34 -> 3.3) replaces the prior 3.3.
    assert recut["consumption_pct"] == 3.3


def test_slide_section_tissue_depletion_cascade(api):
    """PRD §3.3: "When the resulting remainder falls strictly below 5.0 percent,
    the block can no longer be recut and transitions `EMBEDDED → DEPLETED`
    automatically"
    PRD §3.3: "Sectioning moves a slide `ORDERED → SECTIONED` and debits the
    block."

    Design: Difficulty/transitive_cascade/slide_section_tissue_depletion_cascade
    """
    ctx = setup_workup_case(mrn="MRN-501", num_blocks=1, slides_per_block=1)
    block = ctx["blocks"][0]
    slide = ctx["slides"][0]

    sectioned = section_slide(slide["id"], consumption_pct=96.0)
    assert sectioned["status"] == "SECTIONED"

    block_after = get_block(block["id"])
    assert block_after["tissue_remaining_pct"] == 4.0, "100.0 - 96.0"
    assert block_after["status"] == "DEPLETED", "4.0 < 5.0 triggers depletion"


def test_slide_section_tissue_depletion_blocks_new_orders(api):
    """PRD §3.3: "The block's state is reported precisely: targeting a block
    still in `CREATED` yields `ERR_BLOCK_NOT_EMBEDDED` (HTTP 409), while
    targeting a `DEPLETED` block yields the dedicated `ERR_BLOCK_DEPLETED`
    (HTTP 409) — the same pairing applies to sectioning and recutting."

    Design: Difficulty/transitive_cascade/slide_section_tissue_depletion_cascade
    """
    ctx = setup_workup_case(mrn="MRN-501", num_blocks=1, slides_per_block=1)
    block = ctx["blocks"][0]
    section_slide(ctx["slides"][0]["id"], consumption_pct=96.0)
    assert get_block(block["id"])["status"] == "DEPLETED"

    resp = api.create_slide(block["id"], {"slide_label": "A1-2"}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_BLOCK_DEPLETED)


def test_slide_qc_recut_cycle(api):
    """PRD §3.3: "Staining completion moves `SECTIONED → STAINED`, and QC review
    of a `STAINED` slide takes a `result` payload: `PASS` moves the slide to
    the terminal `QC_PASSED`, while `FAIL` moves it to `QC_FAILED` and records
    the payload's `reason` in `qc_failure_reason`."
    PRD §3.3: "A failed slide is not dead: recutting moves it
    `QC_FAILED → SECTIONED` under exactly the same block-state and consumption
    rules as the original section, replacing the slide's `consumption_pct` with
    the new event's rounded value and debiting the block again."

    Design: Difficulty/non_linear_state_machine/slide_qc_recut_cycle
    """
    ctx = setup_workup_case(mrn="MRN-401", num_blocks=1, slides_per_block=1)
    slide = ctx["slides"][0]

    section_slide(slide["id"], consumption_pct=10.0)
    stain_complete_slide(slide["id"])
    qc_review_slide(slide["id"], result="FAIL", reason="chatter artifact")
    recut_slide(slide["id"], consumption_pct=5.0)
    stain_complete_slide(slide["id"])
    passed = qc_review_slide(slide["id"], result="PASS")

    assert passed["status"] == "QC_PASSED", (
        "slide traversed SECTIONED -> STAINED -> QC_FAILED -> SECTIONED -> STAINED -> QC_PASSED"
    )
    assert passed["consumption_pct"] == 5.0, "recut value replaced the original 10.0"


def test_slide_qc_recut_cycle_debits_block_again(api):
    """PRD §3.3: "the block's `tissue_remaining_pct` is recomputed as 100.0
    minus the sum of the per-event rounded consumptions of every section or
    recut event ever applied to the block — including events on slides that
    were later `CANCELLED` — with the per-event-rounding-then-summation order
    pinned per §2.7."

    Design: Difficulty/non_linear_state_machine/slide_qc_recut_cycle
    """
    ctx = setup_workup_case(mrn="MRN-401", num_blocks=1, slides_per_block=1)
    block = ctx["blocks"][0]
    slide = ctx["slides"][0]

    section_slide(slide["id"], consumption_pct=10.0)
    stain_complete_slide(slide["id"])
    qc_review_slide(slide["id"], result="FAIL", reason="chatter artifact")
    recut_slide(slide["id"], consumption_pct=5.0)
    stain_complete_slide(slide["id"])
    qc_review_slide(slide["id"], result="PASS")

    block_after = get_block(block["id"])
    assert block_after["tissue_remaining_pct"] == 85.0, (
        "both the section (10.0) and the recut (5.0) debit the block"
    )
    assert block_after["status"] == "EMBEDDED"


def test_section_after_case_cancel_rejected(api):
    """PRD §3.3: "the owning case must not be in `CANCELLED` or `FINAL`
    (otherwise `ERR_CASE_TERMINAL`, HTTP 409; this same guard covers every
    child mutation under a case, including specimen gross and reject, block
    creation and embedding, slide creation, sectioning, staining, QC review
    and recutting, and stain start and result entry)."
    PRD §2.9: "resource-existence checks ordered left to right across path
    identifiers and then body-referenced identifiers (priority 4), which come
    before the case-terminal guard on child mutations (priority 5). The
    specific state, safety, constraint, referential, temporal, and
    tissue-budget rules then follow in their declared order."
    PRD §3.6: "and — for a case cancelled from `WORKUP`, where bench work may
    exist — slides still in `ORDERED`, `SECTIONED`, `STAINED`, or `QC_FAILED`
    become `CANCELLED` as well."

    Design: Corner/endpoints/section_after_case_cancel_rejected
    """
    ctx = setup_workup_case(mrn="MRN-E4", num_blocks=1, slides_per_block=1)
    slide = ctx["slides"][0]
    cancel_case(ctx["case"]["id"], reason="order withdrawn")
    assert get_slide(slide["id"])["status"] == "CANCELLED", (
        "case cancellation cascaded to the ORDERED slide"
    )

    resp = api.section_slide(slide["id"], {"consumption_pct": 5.0}, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CASE_TERMINAL)
