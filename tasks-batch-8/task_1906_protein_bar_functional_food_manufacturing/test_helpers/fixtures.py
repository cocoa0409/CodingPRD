"""Composite setup helpers.

Multi-step arrangement builders so tests can focus on assertions. Every helper
builds its preconditions from scratch through the public API (the database is
empty at the start of each test) and uses the lenient get_success_data()
validator so setup failures surface as clear "Setup failed" errors.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_RUN,
    CLOCK_RUN_DAY_EVE,
    QUARTER_START_DEFAULT,
    RECEIVED_AT_DEFAULT,
    SLOT_END,
    SLOT_START,
)
from .factories import (
    create_agreement_payload,
    create_claim_review_payload,
    create_customer_payload,
    create_formula_payload,
    create_ingredient_lot_payload,
    create_ingredient_payload,
    create_line_payload,
    create_retain_sample_payload,
    create_revision_payload,
    create_run_payload,
    create_study_payload,
    create_supplier_payload,
    record_pull_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
LT = TEST_USERS["lab_technician_headers"]


def _must(resp, what):
    """Lenient setup validator with a descriptive failure message."""
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed ({what}): {exc}")


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def create_supplier(name="S1", qualification_status="APPROVED", allergens_handled=None):
    payload = create_supplier_payload(name=name, qualification_status=qualification_status)
    if allergens_handled is not None:
        payload["allergens_handled"] = allergens_handled
    return _must(api_client.create_supplier(payload, ADMIN), "create supplier")


def create_ingredient(name, category, allergen_tags=None, nominal_protein_pct=None,
                      nominal_sweetness_factor=None, status=None):
    payload = create_ingredient_payload(name=name, category=category)
    if allergen_tags is not None:
        payload["allergen_tags"] = allergen_tags
    if nominal_protein_pct is not None:
        payload["nominal_protein_pct"] = nominal_protein_pct
    if nominal_sweetness_factor is not None:
        payload["nominal_sweetness_factor"] = nominal_sweetness_factor
    if status is not None:
        payload["status"] = status
    return _must(api_client.create_ingredient(payload, ADMIN), f"create ingredient {name}")


def receive_lot(ingredient_id, supplier_id, lot_code, qty_kg, coa_protein_pct=None,
                coa_sweetness_factor=None, received_at=RECEIVED_AT_DEFAULT):
    payload = create_ingredient_lot_payload(
        ingredient_id=ingredient_id, supplier_id=supplier_id, lot_code=lot_code,
        received_qty_kg=qty_kg, received_at=received_at,
    )
    if coa_protein_pct is not None:
        payload["coa_protein_pct"] = coa_protein_pct
    if coa_sweetness_factor is not None:
        payload["coa_sweetness_factor"] = coa_sweetness_factor
    return _must(api_client.create_ingredient_lot(payload, ADMIN), f"receive lot {lot_code}")


def receive_and_release_lot(ingredient_id, supplier_id, lot_code, qty_kg,
                            coa_protein_pct=None, coa_sweetness_factor=None,
                            received_at=RECEIVED_AT_DEFAULT):
    lot = receive_lot(ingredient_id, supplier_id, lot_code, qty_kg,
                      coa_protein_pct=coa_protein_pct,
                      coa_sweetness_factor=coa_sweetness_factor, received_at=received_at)
    return _must(api_client.release_lot(lot["id"], QM), f"release lot {lot_code}")


def create_customer(name="C1", email="c1@x.com", status=None):
    payload = create_customer_payload(name=name, contact_email=email)
    if status is not None:
        payload["status"] = status
    return _must(api_client.create_customer(payload, ADMIN), f"create customer {name}")


def create_agreement(customer_id, pricing_mode="MARGINAL", moq=100, committed=300,
                     tier_breaks=None, quarter_start=QUARTER_START_DEFAULT):
    payload = create_agreement_payload(
        customer_id=customer_id, pricing_mode=pricing_mode, moq_cases_per_run=moq,
        committed_cases_per_quarter=committed, quarter_start=quarter_start,
    )
    if tier_breaks is not None:
        payload["tier_breaks"] = tier_breaks
    return _must(api_client.create_agreement(payload, ADMIN), "create agreement")


def create_active_agreement(customer_id, **kwargs):
    agreement = create_agreement(customer_id, **kwargs)
    return _must(
        api_client.activate_agreement(agreement["id"], ADMIN), "activate agreement"
    )


def create_formula(customer_id, name="F1", bar_weight_g=60, serving_count_per_bar=1,
                   status=None):
    payload = create_formula_payload(
        customer_id=customer_id, name=name, bar_weight_g=bar_weight_g,
        serving_count_per_bar=serving_count_per_bar,
    )
    if status is not None:
        payload["status"] = status
    return _must(api_client.create_formula(payload, SCI), f"create formula {name}")


def create_revision(formula_id, lines, batch_size_kg=100, target_protein=15, claim_tags=None):
    payload = create_revision_payload(
        ingredient_lines=lines, batch_size_kg=batch_size_kg,
        target_protein_g_per_serving=target_protein,
    )
    if claim_tags is not None:
        payload["claim_tags"] = claim_tags
    return _must(
        api_client.create_revision(formula_id, payload, SCI), "create revision"
    )


def line(ingredient_id, qty_kg, contributor):
    return {
        "ingredient_id": ingredient_id,
        "qty_kg_per_batch": qty_kg,
        "is_protein_contributor": contributor,
    }


def submit_revision(revision_id):
    return _must(api_client.submit_revision(revision_id, SCI), "submit revision")


def verify_nutrition(revision_id):
    return _must(api_client.verify_nutrition(revision_id, QM), "verify nutrition")


def approve_claim_review_for_tag(revision_id, claim_tag, claim_type="NUTRIENT_CONTENT",
                                 structure_function_disclaimer=None):
    payload = create_claim_review_payload(
        revision_id=revision_id, claim_tag=claim_tag, claim_type=claim_type,
    )
    if structure_function_disclaimer is not None:
        payload["structure_function_disclaimer"] = structure_function_disclaimer
    review = _must(api_client.create_claim_review(payload, SCI), "create claim review")
    _must(api_client.start_claim_review(review["id"], QM), "start claim review")
    _must(api_client.approve_claim_review(review["id"], QM), "approve claim review")
    return review


def march_revision_to_approved(revision_id, claim_tags=None):
    """DRAFT -> SUBMITTED -> NUTRITION_VERIFIED -> CLAIM_REVIEW -> APPROVED.

    Claim reviews (one per claim tag) are opened and approved while the
    revision stands in NUTRITION_VERIFIED, before routing to CLAIM_REVIEW.
    """
    submit_revision(revision_id)
    verify_nutrition(revision_id)
    for tag in (claim_tags or []):
        approve_claim_review_for_tag(revision_id, tag)
    _must(api_client.send_claim_review(revision_id, SCI), "send claim review")
    return _must(api_client.approve_revision(revision_id, QM), "approve revision")


def create_line(name="L1", slab_weight_kg=20, capacity_kg_per_hour=500):
    payload = create_line_payload(
        name=name, capacity_kg_per_hour=capacity_kg_per_hour,
        slab_weight_kg=slab_weight_kg,
    )
    return _must(api_client.create_line(payload, ADMIN), f"create line {name}")


def set_clock(to_iso8601):
    return _must(api_client.set_clock(to_iso8601, ADMIN), f"set clock {to_iso8601}")


def get_agreement_version(agreement_id):
    return _must(api_client.get_agreement(agreement_id, PP), "read agreement")["version"]


def get_line_version(line_id):
    return _must(api_client.get_line(line_id, PP), "read line")["version"]


def create_run(revision_id, agreement_id, line_id, planned_cases):
    """Create a run, threading the agreement's current version (PRD §2.5)."""
    payload = create_run_payload(
        revision_id=revision_id, agreement_id=agreement_id, line_id=line_id,
        planned_cases=planned_cases,
        expected_agreement_version=get_agreement_version(agreement_id),
    )
    return _must(api_client.create_production_run(payload, PP), "create run")


def schedule_run_fresh(run_id, line_id, start_utc=SLOT_START, end_utc=SLOT_END):
    """Schedule a run, threading the line's current version (PRD §2.5)."""
    payload = {
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_line_version": get_line_version(line_id),
    }
    return _must(api_client.schedule_run(run_id, payload, PP), "schedule run")


def get_to_changeover(run_id):
    """The changeover event whose to_run is this run (created at schedule)."""
    events = _must(api_client.list_run_changeovers(run_id, PP), "list run changeovers")
    matching = [e for e in events if e.get("to_run_id") == run_id]
    assert matching, f"Setup failed: no changeover event feeding run {run_id}"
    return matching[0]


def get_run_slot(run_id):
    slots = _must(api_client.list_run_slots(run_id, PP), "list run slots")
    assert slots, f"Setup failed: run {run_id} has no slot"
    return slots[0]


def get_lot_release_for_run(run_id):
    releases = _must(api_client.get_run_lot_release(run_id, QM), "read run lot release")
    assert releases, f"Setup failed: run {run_id} has no lot release"
    return releases[0]


# ---------------------------------------------------------------------------
# Tier 2/3: plant and run lifecycle composites
# ---------------------------------------------------------------------------

def setup_basic_plant(whey_qty=200, syrup_qty=100, whey_coa=0.8, syrup_coa=1.0,
                      moq=100, committed=300, slab_weight_kg=20, claim_tags=None,
                      bar_weight_g=60, revision_target=15, line_name="L1",
                      extra_ingredients=None, extra_lots=None):
    """Approved supplier, WHEY/SYRUP ingredients, RELEASED lots, ACTIVE customer
    + agreement, formula with an APPROVED revision (claims as given), one line.
    """
    sup = create_supplier("S1", "APPROVED", ["MILK"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    wl = receive_and_release_lot(whey["id"], sup["id"], "WL-1", whey_qty,
                                 coa_protein_pct=whey_coa)
    sl = receive_and_release_lot(syr["id"], sup["id"], "SL-1", syrup_qty,
                                 coa_sweetness_factor=syrup_coa)
    extras = {}
    for spec in (extra_ingredients or []):
        extras[spec["key"]] = create_ingredient(
            spec["name"], spec["category"], spec.get("allergen_tags"),
            nominal_protein_pct=spec.get("nominal_protein_pct"),
            nominal_sweetness_factor=spec.get("nominal_sweetness_factor"),
        )
    for spec in (extra_lots or []):
        extras[spec["key"]] = receive_and_release_lot(
            extras[spec["ingredient_key"]]["id"], sup["id"], spec["lot_code"],
            spec["qty_kg"], coa_protein_pct=spec.get("coa_protein_pct"),
            coa_sweetness_factor=spec.get("coa_sweetness_factor"),
        )
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=moq, committed=committed)
    f1 = create_formula(cust["id"], "F1", bar_weight_g=bar_weight_g)
    lines = [
        line(whey["id"], 40, True),
        line(syr["id"], 10, False),
    ]
    r1 = create_revision(f1["id"], lines, target_protein=revision_target,
                         claim_tags=claim_tags or [])
    march_revision_to_approved(r1["id"], claim_tags or [])
    ln1 = create_line(line_name, slab_weight_kg=slab_weight_kg)
    return SimpleNamespace(sup=sup, whey=whey, syr=syr, wl=wl, sl=sl, cust=cust,
                           ag=ag, f1=f1, r1=r1, ln1=ln1, extras=extras)


def setup_run_scheduled(plant=None, planned_cases=100, start_utc=SLOT_START,
                        end_utc=SLOT_END, clock=CLOCK_RUN_DAY_EVE, **plant_kwargs):
    """Basic plant + run created (PLANNED) and scheduled on its line."""
    plant = plant or setup_basic_plant(**plant_kwargs)
    set_clock(clock)
    run = create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], planned_cases)
    schedule_run_fresh(run["id"], plant.ln1["id"], start_utc, end_utc)
    return SimpleNamespace(plant=plant, run=run)


def setup_run_in_production(plant=None, planned_cases=100, **kwargs):
    ns = setup_run_scheduled(plant=plant, planned_cases=planned_cases, **kwargs)
    _must(api_client.verify_pre_run(ns.run["id"], QM), "verify pre-run")
    _must(api_client.start_run(ns.run["id"], PP), "start run")
    return ns


def setup_completed_run(planned_cases=130, produced_cases=130, scrapped_cases=0,
                        complete_clock=CLOCK_AFTER_RUN, **kwargs):
    """Run marched to COMPLETED; returns the run and its LotRelease."""
    ns = setup_run_in_production(planned_cases=planned_cases, **kwargs)
    set_clock(complete_clock)
    _must(
        api_client.complete_run(
            ns.run["id"],
            {"produced_cases": produced_cases, "scrapped_cases": scrapped_cases}, PP,
        ),
        "complete run",
    )
    run = _must(api_client.get_production_run(ns.run["id"], QM), "read completed run")
    release = get_lot_release_for_run(ns.run["id"])
    return SimpleNamespace(plant=ns.plant, run=run, release=release)


def register_retain_sample(run_id, bin_id="BIN-1", cases_count=1,
                           retain_until_utc="2026-09-15T00:00:00Z"):
    payload = create_retain_sample_payload(
        bin_id=bin_id, cases_count=cases_count, retain_until_utc=retain_until_utc,
    )
    return _must(
        api_client.create_retain_sample(run_id, payload, QM), "register retain sample"
    )


def record_qc_passed(release_id, user_id="lt-001"):
    from .test_users import make_lab_technician_headers
    return _must(
        api_client.record_qc(
            release_id, {"qc_disposition": "PASSED"},
            make_lab_technician_headers(user_id),
        ),
        "record QC PASSED",
    )


# ---------------------------------------------------------------------------
# Formula/revision-only composites (no lots, no runs)
# ---------------------------------------------------------------------------

def setup_formula_with_revision(lines=None, claim_tags=None, target_protein=15,
                                bar_weight_g=60, formula_name="F1", march_to=None):
    """Supplier (unused for lots), WHEY/SYRUP ingredients, customer, formula and
    one DRAFT revision; optionally marched to a later pipeline stage.
    march_to: None | "SUBMITTED" | "NUTRITION_VERIFIED" | "CLAIM_REVIEW" | "APPROVED".
    """
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    cust = create_customer("C1")
    f1 = create_formula(cust["id"], formula_name, bar_weight_g=bar_weight_g)
    lines = lines if lines is not None else [
        line(whey["id"], 40, True),
        line(syr["id"], 10, False),
    ]
    r1 = create_revision(f1["id"], lines, target_protein=target_protein,
                         claim_tags=claim_tags or [])
    if march_to in ("SUBMITTED", "NUTRITION_VERIFIED", "CLAIM_REVIEW", "APPROVED"):
        submit_revision(r1["id"])
    if march_to in ("NUTRITION_VERIFIED", "CLAIM_REVIEW", "APPROVED"):
        verify_nutrition(r1["id"])
    if march_to == "APPROVED":
        for tag in (claim_tags or []):
            approve_claim_review_for_tag(r1["id"], tag)
    if march_to in ("CLAIM_REVIEW", "APPROVED"):
        _must(api_client.send_claim_review(r1["id"], SCI), "send claim review")
    if march_to == "APPROVED":
        _must(api_client.approve_revision(r1["id"], QM), "approve revision")
    return SimpleNamespace(whey=whey, syr=syr, cust=cust, f1=f1, r1=r1)


# ---------------------------------------------------------------------------
# Scenario composites driven by deep multi-step claims
# ---------------------------------------------------------------------------

def setup_label_composite_scenario():
    """Four-ingredient revision carrying HIGH_PROTEIN, with reserved lots whose
    CoA protein assays drift below nominal; run created and scheduled (PRD §3.4
    LABEL vs §3.8 COMPOSITE substantiation).
    """
    sup = create_supplier("S1", "APPROVED", ["MILK", "SOY"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    mpi = create_ingredient("MPI", "PROTEIN", ["MILK"], nominal_protein_pct=0.85)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    oats = create_ingredient("OATS", "BINDER", ["WHEAT"])
    wl = receive_and_release_lot(whey["id"], sup["id"], "WL-1", 200, coa_protein_pct=0.76)
    ml = receive_and_release_lot(mpi["id"], sup["id"], "ML-1", 100, coa_protein_pct=0.85)
    sl = receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=1.0)
    ol = receive_and_release_lot(oats["id"], sup["id"], "OL-1", 200)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=300)
    f1 = create_formula(cust["id"], "F1", bar_weight_g=60)
    lines = [
        line(whey["id"], 40, True),
        line(mpi["id"], 10, True),
        line(syr["id"], 10, False),
        line(oats["id"], 40, False),
    ]
    r1 = create_revision(f1["id"], lines, target_protein=20, claim_tags=["HIGH_PROTEIN"])
    submit_revision(r1["id"])
    verified = verify_nutrition(r1["id"])
    approve_claim_review_for_tag(r1["id"], "HIGH_PROTEIN")
    _must(api_client.send_claim_review(r1["id"], SCI), "send claim review")
    _must(api_client.approve_revision(r1["id"], QM), "approve revision")
    ln1 = create_line("L1", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    run1 = create_run(r1["id"], ag["id"], ln1["id"], 130)
    schedule_run_fresh(run1["id"], ln1["id"])
    return SimpleNamespace(sup=sup, whey=whey, mpi=mpi, syr=syr, oats=oats, wl=wl,
                           ml=ml, sl=sl, ol=ol, cust=cust, ag=ag, f1=f1, r1=r1,
                           verified=verified, ln1=ln1, run1=run1)


def setup_provisional_final_scenario():
    """Syrup lot with CoA sweetness factor 0.8 (nominal 1.0); run created and
    scheduled (PRD §3.6 PROVISIONAL vs §3.8 FINAL sweetener adjustment).
    """
    sup = create_supplier("S1", "APPROVED", ["MILK"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    wl = receive_and_release_lot(whey["id"], sup["id"], "WL-1", 200, coa_protein_pct=0.8)
    sl = receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=0.8)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=300)
    f2 = create_formula(cust["id"], "F2", bar_weight_g=60)
    r2 = create_revision(f2["id"], [line(whey["id"], 40, True), line(syr["id"], 10, False)],
                         target_protein=15, claim_tags=[])
    march_revision_to_approved(r2["id"])
    ln1 = create_line("L1", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    run1 = create_run(r2["id"], ag["id"], ln1["id"], 100)
    schedule_run_fresh(run1["id"], ln1["id"])
    return SimpleNamespace(sup=sup, whey=whey, syr=syr, wl=wl, sl=sl, cust=cust,
                           ag=ag, f2=f2, r2=r2, ln1=ln1, run1=run1)


def _approve_revision_on_formula(formula_id, lines, target_protein, claim_tags=None):
    revision = create_revision(formula_id, lines, target_protein=target_protein,
                               claim_tags=claim_tags or [])
    march_revision_to_approved(revision["id"], claim_tags or [])
    return revision


def _complete_run_now(run_id, produced_cases=100):
    _must(api_client.verify_pre_run(run_id, QM), "verify pre-run")
    _must(api_client.start_run(run_id, PP), "start run")
    _must(api_client.complete_run(
        run_id, {"produced_cases": produced_cases, "scrapped_cases": 0}, PP,
    ), "complete run")


def setup_staleness_chain_through_c():
    """Runs A (profile [MILK,SOY]) and B ([SOY]) completed on one line; run B's
    SWAB_VALIDATE changeover validated at logical clock 2026-08-02T11:00Z, so the
    line carries a wet-clean timestamp. Run C ([MILK]) completed after a
    WET_CLEAN changeover validated at 2026-08-02T15:45Z (PRD §3.7 matrix).
    """
    sup = create_supplier("S1", "APPROVED", ["MILK", "SOY"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    soy = create_ingredient("SOYPROT", "PROTEIN", ["SOY"], nominal_protein_pct=0.85)
    mpi = create_ingredient("MPI", "PROTEIN", ["MILK"], nominal_protein_pct=0.85)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    receive_and_release_lot(whey["id"], sup["id"], "WL-1", 300, coa_protein_pct=0.8)
    receive_and_release_lot(soy["id"], sup["id"], "SPL-1", 200, coa_protein_pct=0.85)
    receive_and_release_lot(mpi["id"], sup["id"], "ML-1", 100, coa_protein_pct=0.85)
    receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=1.0)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=3000)
    fm = create_formula(cust["id"], "FM", bar_weight_g=60)
    ln1 = create_line("L1", slab_weight_kg=20)

    ra = _approve_revision_on_formula(
        fm["id"], [line(whey["id"], 40, True), line(soy["id"], 20, True)], 25)
    set_clock("2026-08-02T06:00:00Z")
    run_a = create_run(ra["id"], ag["id"], ln1["id"], 100)
    schedule_run_fresh(run_a["id"], ln1["id"], "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")
    _complete_run_now(run_a["id"])

    rb = _approve_revision_on_formula(fm["id"], [line(soy["id"], 30, True)], 15)
    set_clock("2026-08-02T10:30:00Z")
    run_b = create_run(rb["id"], ag["id"], ln1["id"], 100)
    schedule_run_fresh(run_b["id"], ln1["id"], "2026-08-02T12:00:00Z", "2026-08-02T14:00:00Z")
    co_b = get_to_changeover(run_b["id"])
    _must(api_client.log_cleaning(co_b["id"], PP), "log cleaning B")
    _must(api_client.record_swab(co_b["id"], {"swab_allergen_ppm": 10}, LT), "swab B")
    set_clock("2026-08-02T11:00:00Z")
    _must(api_client.validate_changeover(co_b["id"], QM), "validate B")
    _complete_run_now(run_b["id"])

    rc = _approve_revision_on_formula(
        fm["id"], [line(whey["id"], 40, True), line(mpi["id"], 10, True)], 20)
    set_clock("2026-08-02T15:30:00Z")
    run_c = create_run(rc["id"], ag["id"], ln1["id"], 100)
    schedule_run_fresh(run_c["id"], ln1["id"], "2026-08-02T16:00:00Z", "2026-08-02T18:00:00Z")
    co_c = get_to_changeover(run_c["id"])
    slot_c = get_run_slot(run_c["id"])
    _must(api_client.log_cleaning(co_c["id"], PP), "log cleaning C")
    set_clock("2026-08-02T15:45:00Z")
    _must(api_client.validate_changeover(co_c["id"], QM), "validate C")
    _complete_run_now(run_c["id"])

    return SimpleNamespace(sup=sup, whey=whey, soy=soy, mpi=mpi, syr=syr, cust=cust,
                           ag=ag, fm=fm, ln1=ln1, ra=ra, rb=rb, rc=rc,
                           run_a=run_a, run_b=run_b, run_c=run_c,
                           co_b=co_b, co_c=co_c, slot_c=slot_c)


def setup_peanut_line_scenario():
    """A PEANUT-profile run scheduled on a line, and a second run (empty
    profile) created but not yet scheduled (PRD §3.6/§3.7 buffer rules).
    """
    sup = create_supplier("S1", "APPROVED", ["PEANUT"])
    pfl = create_ingredient("PEANUT_FLOUR", "PROTEIN", ["PEANUT"], nominal_protein_pct=0.5)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    coc = create_ingredient("COCOA", "FLAVOR", [])
    receive_and_release_lot(pfl["id"], sup["id"], "PFL-1", 100, coa_protein_pct=0.5)
    receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=1.0)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=300)
    fp = create_formula(cust["id"], "FP", bar_weight_g=60)
    rp = _approve_revision_on_formula(
        fp["id"], [line(pfl["id"], 30, True), line(syr["id"], 10, False)], 9)
    f0 = create_formula(cust["id"], "F0", bar_weight_g=60)
    r0 = _approve_revision_on_formula(
        f0["id"], [line(syr["id"], 10, False), line(coc["id"], 5, False)], 0)
    lp = create_line("LP", slab_weight_kg=20)
    set_clock("2026-08-04T06:00:00Z")
    run_p = create_run(rp["id"], ag["id"], lp["id"], 100)
    schedule_run_fresh(run_p["id"], lp["id"], "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z")
    run_0 = create_run(r0["id"], ag["id"], lp["id"], 100)
    return SimpleNamespace(sup=sup, pfl=pfl, syr=syr, coc=coc, cust=cust, ag=ag,
                           fp=fp, rp=rp, f0=f0, r0=r0, lp=lp, run_p=run_p, run_0=run_0)


def setup_day_availability_scenario():
    """Line with run A scheduled [08:00,10:00) and run C scheduled [12:30,14:00)
    on 2026-08-05 (PRD §3.6 day availability).
    """
    plant = setup_basic_plant(whey_qty=300, syrup_qty=100, committed=3000,
                              line_name="LD")
    set_clock("2026-08-04T06:00:00Z")
    run_a = create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 100)
    schedule_run_fresh(run_a["id"], plant.ln1["id"],
                       "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z")
    run_c = create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 100)
    schedule_run_fresh(run_c["id"], plant.ln1["id"],
                       "2026-08-05T12:30:00Z", "2026-08-05T14:00:00Z")
    return SimpleNamespace(plant=plant, run_a=run_a, run_c=run_c)


def setup_supersede_scenario():
    """Formula F9 with APPROVED R9a carrying a SCHEDULED run, and successor
    R9b standing in CLAIM_REVIEW (PRD §3.4 CASCADE-SUPERSEDE).
    """
    plant = setup_basic_plant()
    set_clock(CLOCK_RUN_DAY_EVE)
    run_x = create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 100)
    schedule_run_fresh(run_x["id"], plant.ln1["id"])
    r9b = create_revision(
        plant.f1["id"],
        [line(plant.whey["id"], 42, True), line(plant.syr["id"], 10, False)],
        target_protein=16, claim_tags=[],
    )
    submit_revision(r9b["id"])
    verify_nutrition(r9b["id"])
    _must(api_client.send_claim_review(r9b["id"], SCI), "send claim review R9b")
    return SimpleNamespace(plant=plant, run_x=run_x, r9a=plant.r1, r9b=r9b)


def setup_gluten_free_line_scenario():
    """A line whose current allergen profile is [MILK, WHEAT] (a completed run
    of a WHEAT-carrying revision), plus an APPROVED GLUTEN_FREE-claimed revision
    whose profile excludes WHEAT (PRD §2.7 segregation rule).
    """
    sup = create_supplier("S1", "APPROVED", ["MILK", "WHEAT"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    mpi = create_ingredient("MPI", "PROTEIN", ["MILK"], nominal_protein_pct=0.85)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    oats = create_ingredient("OATS", "BINDER", ["WHEAT"])
    receive_and_release_lot(whey["id"], sup["id"], "WL-1", 200, coa_protein_pct=0.8)
    receive_and_release_lot(mpi["id"], sup["id"], "ML-1", 100, coa_protein_pct=0.85)
    receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=1.0)
    receive_and_release_lot(oats["id"], sup["id"], "OL-1", 200)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=300)
    fw = create_formula(cust["id"], "FW", bar_weight_g=60)
    rw = _approve_revision_on_formula(fw["id"], [
        line(whey["id"], 40, True), line(syr["id"], 10, False),
        line(oats["id"], 40, False),
    ], 15)
    lw = create_line("LW", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    run_w = create_run(rw["id"], ag["id"], lw["id"], 100)
    schedule_run_fresh(run_w["id"], lw["id"])
    _complete_run_now(run_w["id"])
    fgf = create_formula(cust["id"], "FGF", bar_weight_g=60)
    rgf = create_revision(fgf["id"], [
        line(whey["id"], 40, True), line(mpi["id"], 10, True),
        line(syr["id"], 10, False),
    ], target_protein=20, claim_tags=["GLUTEN_FREE"])
    submit_revision(rgf["id"])
    verify_nutrition(rgf["id"])
    review = approve_claim_review_for_tag(rgf["id"], "GLUTEN_FREE")
    _must(api_client.send_claim_review(rgf["id"], SCI), "send claim review GF")
    _must(api_client.approve_revision(rgf["id"], QM), "approve GF revision")
    return SimpleNamespace(sup=sup, whey=whey, mpi=mpi, syr=syr, oats=oats, cust=cust,
                           ag=ag, fw=fw, rw=rw, lw=lw, run_w=run_w, fgf=fgf, rgf=rgf,
                           gf_review=review)


def setup_swab_gated_run(swab_ppm=10, swab_user_id="lt-001"):
    """Line with a completed [MILK, WHEAT] run, and a second run ([SOY]) whose
    changeover computed SWAB_VALIDATE; cleaning logged and a swab recorded by
    the given technician user id (PRD §3.7/§3.8 pre-run changeover gate).
    """
    from .test_users import make_lab_technician_headers
    sup = create_supplier("S1", "APPROVED", ["MILK", "SOY", "WHEAT"])
    whey = create_ingredient("WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8)
    oats = create_ingredient("OATS", "BINDER", ["WHEAT"])
    soy = create_ingredient("SOYPROT", "PROTEIN", ["SOY"], nominal_protein_pct=0.85)
    syr = create_ingredient("SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0)
    receive_and_release_lot(whey["id"], sup["id"], "WL-1", 200, coa_protein_pct=0.8)
    receive_and_release_lot(oats["id"], sup["id"], "OL-1", 200)
    receive_and_release_lot(soy["id"], sup["id"], "SPL-1", 200, coa_protein_pct=0.85)
    receive_and_release_lot(syr["id"], sup["id"], "SL-1", 100, coa_sweetness_factor=1.0)
    cust = create_customer("C1")
    ag = create_active_agreement(cust["id"], moq=100, committed=300)
    fw = create_formula(cust["id"], "FW", bar_weight_g=60)
    rw = _approve_revision_on_formula(fw["id"], [
        line(whey["id"], 40, True), line(oats["id"], 40, False),
        line(syr["id"], 10, False),
    ], 15)
    lx = create_line("LX", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    run_a = create_run(rw["id"], ag["id"], lx["id"], 100)
    schedule_run_fresh(run_a["id"], lx["id"], SLOT_START, SLOT_END)
    _complete_run_now(run_a["id"])
    fb = create_formula(cust["id"], "FB", bar_weight_g=60)
    rb = _approve_revision_on_formula(
        fb["id"], [line(soy["id"], 30, True), line(syr["id"], 10, False)], 15)
    run_b = create_run(rb["id"], ag["id"], lx["id"], 100)
    schedule_run_fresh(run_b["id"], lx["id"], "2026-08-06T12:00:00Z", "2026-08-06T14:00:00Z")
    co_b = get_to_changeover(run_b["id"])
    _must(api_client.log_cleaning(co_b["id"], PP), "log cleaning")
    _must(
        api_client.record_swab(
            co_b["id"], {"swab_allergen_ppm": swab_ppm},
            make_lab_technician_headers(swab_user_id),
        ),
        "record swab",
    )
    return SimpleNamespace(sup=sup, whey=whey, oats=oats, soy=soy, syr=syr, cust=cust,
                           ag=ag, fw=fw, rw=rw, lx=lx, run_a=run_a, fb=fb, rb=rb,
                           run_b=run_b, co_b=co_b)


def setup_yield_pair():
    """Two runs on separate lines, both completed with QC PASSED and a STORED
    retain sample: run A produced 105 vs planned 100, run B produced 106
    (PRD §3.8 yield gate).
    """
    plant = setup_basic_plant(whey_qty=400, syrup_qty=200, committed=1000)
    lb = create_line("LB", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    runs = {}
    for key, line_id, produced in (("a", plant.ln1["id"], 105), ("b", lb["id"], 106)):
        run = create_run(plant.r1["id"], plant.ag["id"], line_id, 100)
        schedule_run_fresh(run["id"], line_id)
        _must(api_client.verify_pre_run(run["id"], QM), f"verify pre-run {key}")
        _must(api_client.start_run(run["id"], PP), f"start {key}")
        _must(api_client.complete_run(
            run["id"], {"produced_cases": produced, "scrapped_cases": 0}, PP,
        ), f"complete {key}")
        release = get_lot_release_for_run(run["id"])
        record_qc_passed(release["id"])
        register_retain_sample(run["id"], bin_id=f"BIN-{key.upper()}",
                               retain_until_utc="2026-09-20T00:00:00Z")
        runs[key] = SimpleNamespace(run=run, release=release)
    return SimpleNamespace(plant=plant, lb=lb, a=runs["a"], b=runs["b"])


def setup_quarter_window_pair():
    """run X completed at 2026-09-29T23:59Z (inside the quarter window) and
    RELEASED; run Y completed at 2026-09-30T00:00Z (the exclusive window end)
    with QC PASSED and a retain sample, not yet decided (PRD §3.3 window).
    """
    plant = setup_basic_plant(whey_qty=400, syrup_qty=200, committed=1000)
    lb = create_line("LB", slab_weight_kg=20)
    set_clock(CLOCK_RUN_DAY_EVE)
    # Run X on the first line.
    run_x = create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 130)
    schedule_run_fresh(run_x["id"], plant.ln1["id"])
    _must(api_client.verify_pre_run(run_x["id"], QM), "verify pre-run X")
    _must(api_client.start_run(run_x["id"], PP), "start X")
    set_clock("2026-09-29T23:59:00Z")
    _must(api_client.complete_run(
        run_x["id"], {"produced_cases": 130, "scrapped_cases": 0}, PP,
    ), "complete X")
    rel_x = get_lot_release_for_run(run_x["id"])
    record_qc_passed(rel_x["id"])
    register_retain_sample(run_x["id"], bin_id="BIN-X",
                           retain_until_utc="2026-11-08T00:00:00Z")
    _must(
        api_client.decide_lot_release(rel_x["id"], {"decision": "RELEASED"}, QM),
        "decide X RELEASED",
    )
    # Run Y on the second line; completed exactly at the exclusive window end.
    run_y = create_run(plant.r1["id"], plant.ag["id"], lb["id"], 130)
    schedule_run_fresh(run_y["id"], lb["id"],
                       "2026-09-30T08:00:00Z", "2026-09-30T10:00:00Z")
    _must(api_client.verify_pre_run(run_y["id"], QM), "verify pre-run Y")
    _must(api_client.start_run(run_y["id"], PP), "start Y")
    set_clock("2026-09-30T00:00:00Z")
    _must(api_client.complete_run(
        run_y["id"], {"produced_cases": 130, "scrapped_cases": 0}, PP,
    ), "complete Y")
    rel_y = get_lot_release_for_run(run_y["id"])
    record_qc_passed(rel_y["id"])
    register_retain_sample(run_y["id"], bin_id="BIN-Y",
                           retain_until_utc="2026-11-09T00:00:00Z")
    return SimpleNamespace(plant=plant, lb=lb, run_x=run_x, rel_x=rel_x,
                           run_y=run_y, rel_y=rel_y)


def setup_study_pair(limit_a=152.86, limit_b=150.0):
    """Two ACTIVE shelf-life studies (limits as given) with one baseline pull
    each at study start; clock advanced to the second pull's due date.
    """
    ns = setup_formula_with_revision(march_to="APPROVED")
    st1 = _must(api_client.create_shelf_life_study(create_study_payload(
        revision_id=ns.r1["id"], chamber_id="CH-A", shelf_position="P1",
        hardness_limit_n=limit_a, pull_interval_days=7,
    ), LT), "create study A")
    st2 = _must(api_client.create_shelf_life_study(create_study_payload(
        revision_id=ns.r1["id"], chamber_id="CH-B", shelf_position="P1",
        hardness_limit_n=limit_b, pull_interval_days=7,
    ), LT), "create study B")
    _must(api_client.record_pull(st1["id"], record_pull_payload(
        hardness_n=50.0, recorded_utc="2026-08-01T00:00:00Z"), LT), "baseline pull A")
    _must(api_client.record_pull(st2["id"], record_pull_payload(
        hardness_n=50.0, recorded_utc="2026-08-01T00:00:00Z"), LT), "baseline pull B")
    set_clock("2026-08-08T00:00:00Z")
    return SimpleNamespace(base=ns, st1=st1, st2=st2)


def setup_approved_revision_for_study():
    """An APPROVED revision (claims []) usable for shelf-life study tests."""
    ns = setup_formula_with_revision(march_to="APPROVED")
    return ns


def create_study(revision_id, chamber_id="CH1", shelf_position="P1",
                 start_utc="2026-08-01T00:00:00Z", expiry_utc="2026-10-30T00:00:00Z",
                 hardness_limit_n=200.0, pull_interval_days=None):
    payload = create_study_payload(
        revision_id=revision_id, chamber_id=chamber_id, shelf_position=shelf_position,
        start_utc=start_utc, expiry_utc=expiry_utc, hardness_limit_n=hardness_limit_n,
    )
    if pull_interval_days is not None:
        payload["pull_interval_days"] = pull_interval_days
    return _must(api_client.create_shelf_life_study(payload, LT), "create study")
