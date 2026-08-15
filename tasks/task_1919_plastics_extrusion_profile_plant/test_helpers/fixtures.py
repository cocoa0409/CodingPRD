"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API (the
server is relaunched with an empty database before each test). Setup calls use
the lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_JUNE, CLOCK_AUGUST, DEFAULT_INDEX_POINTS,
    WINDOW_10_12, WINDOW_12_14, IN_CONTROL_MEASUREMENTS, IN_CONTROL_MEASUREMENTS_B,
)
from .factories import (
    create_customer_payload, create_profile_payload, create_die_payload,
    create_line_payload, create_resin_lot_payload, create_formulation_payload,
    create_blend_batch_payload, create_work_order_payload,
    create_line_assignment_payload, create_run_payload, create_spc_sample_payload,
    create_purge_event_payload, create_resin_index_point_payload,
)
from .test_users import TEST_USERS, make_quality_inspector_headers

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]
LO = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]
SE = TEST_USERS["sales_engineer_headers"]


def _ok(resp, what):
    if not (200 <= resp.status_code < 300):
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Granular builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_JUNE):
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, PM), "set clock")


def publish_index_points(points=DEFAULT_INDEX_POINTS):
    out = {}
    for month, value in points:
        out[month] = _ok(
            api_client.create_resin_index_point(
                create_resin_index_point_payload(month, value), PM),
            f"publish index point {month}",
        )
    return out


def create_customer(**overrides):
    return _ok(api_client.create_customer(create_customer_payload(**overrides), PM), "create customer")


def create_profile(customer_id, **overrides):
    return _ok(api_client.create_profile(create_profile_payload(customer_id, **overrides), PE), "create profile")


def create_die(profile_id, **overrides):
    return _ok(api_client.create_die(create_die_payload(profile_id, **overrides), PE), "create die")


def transition_die(die_id, to):
    return _ok(api_client.transition_die(die_id, {"to": to}, PE), f"die -> {to}")


def qualify_die(die_id):
    """Walk DRAFT -> TRIAL -> QUALIFIED; returns the qualified die (rates pinned)."""
    transition_die(die_id, "TRIAL")
    return transition_die(die_id, "QUALIFIED")


def create_line(**overrides):
    return _ok(api_client.create_line(create_line_payload(**overrides), PE), "create line")


def create_lot(lot_kind, resin_type, color_family, received_kg, supplier_lot_ref=None):
    payload = create_resin_lot_payload(
        lot_kind=lot_kind, resin_type=resin_type,
        color_family=color_family, received_kg=received_kg,
    )
    if supplier_lot_ref is not None:
        payload["supplier_lot_ref"] = supplier_lot_ref
    return _ok(api_client.create_resin_lot(payload, LO), "create resin lot")


def pass_lot(lot_id):
    return _ok(api_client.qc_resin_lot(lot_id, {"outcome": "PASS"}, QI), "QC PASS lot")


def qc_passed_lot(lot_kind, resin_type, color_family, received_kg, supplier_lot_ref=None):
    lot = create_lot(lot_kind, resin_type, color_family, received_kg, supplier_lot_ref)
    pass_lot(lot["id"])
    return get_success_data(api_client.get_resin_lot(lot["id"], PM))


def create_formulation(profile_id, **overrides):
    return _ok(api_client.create_formulation(create_formulation_payload(profile_id, **overrides), PE), "create formulation")


def create_batch(formulation_id, virgin_lot_id, colorant_lot_id, regrind_lot_id=None, target_batch_kg=1000.0):
    payload = create_blend_batch_payload(formulation_id, virgin_lot_id, colorant_lot_id,
                                         target_batch_kg=target_batch_kg)
    if regrind_lot_id is not None:
        payload["regrind_lot_id"] = regrind_lot_id
    return _ok(api_client.create_blend_batch(payload, LO), "create blend batch")


def release_batch(batch_id, inspector_id=None):
    headers = make_quality_inspector_headers(inspector_id) if inspector_id else QI
    return _ok(api_client.qc_blend_batch(batch_id, {"action": "RELEASE"}, headers), "release batch")


def released_batch(formulation_id, virgin_lot_id, colorant_lot_id, regrind_lot_id=None, target_batch_kg=1000.0):
    batch = create_batch(formulation_id, virgin_lot_id, colorant_lot_id, regrind_lot_id, target_batch_kg)
    release_batch(batch["id"])
    return get_success_data(api_client.get_blend_batch(batch["id"], PM))


def create_order(customer_id, profile_id, formulation_id, die_id, **overrides):
    return _ok(
        api_client.create_work_order(
            create_work_order_payload(customer_id, profile_id, formulation_id, die_id, **overrides), SE),
        "create work order",
    )


def confirm_order(work_order_id):
    return _ok(api_client.confirm_work_order(work_order_id, SE), "confirm work order")


def confirmed_order(customer_id, profile_id, formulation_id, die_id, **overrides):
    wo = create_order(customer_id, profile_id, formulation_id, die_id, **overrides)
    confirm_order(wo["id"])
    return get_success_data(api_client.get_work_order(wo["id"], PM))


def create_assignment(work_order_id, die_id, line_id, window=WINDOW_10_12):
    start, end = window
    return _ok(
        api_client.create_line_assignment(
            create_line_assignment_payload(work_order_id, die_id, line_id, start, end), PE),
        "create line assignment",
    )


def activate(assignment_id):
    return _ok(api_client.activate_assignment(assignment_id, PE), "activate assignment")


def activated_assignment(work_order_id, die_id, line_id, window=WINDOW_10_12):
    asg = create_assignment(work_order_id, die_id, line_id, window)
    activate(asg["id"])
    return get_success_data(api_client.get_line_assignment(asg["id"], PM))


def start_run(assignment_id, batch_id, line_speed_mpm=25):
    return _ok(
        api_client.create_run(create_run_payload(assignment_id, batch_id, line_speed_mpm=line_speed_mpm), LO),
        "start run",
    )


def post_sample(run_id, measurements=None, dimension_name="wall"):
    return _ok(
        api_client.create_spc_sample(
            create_spc_sample_payload(run_id, measurements or IN_CONTROL_MEASUREMENTS, dimension_name), LO),
        "post SPC sample",
    )


def complete_run(run_id, good_length_mm, good_weight_kg, trim_scrap_kg):
    return _ok(
        api_client.complete_run(
            run_id,
            {"good_length_mm": good_length_mm, "good_weight_kg": good_weight_kg, "trim_scrap_kg": trim_scrap_kg},
            LO),
        "complete run",
    )


def get_die(die_id):
    return get_success_data(api_client.get_die(die_id, PM))


def get_line(line_id):
    return get_success_data(api_client.get_line(line_id, PM))


def get_lot(lot_id):
    return get_success_data(api_client.get_resin_lot(lot_id, PM))


def get_batch(batch_id):
    return get_success_data(api_client.get_blend_batch(batch_id, PM))


def get_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, PM))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_line_assignment(assignment_id, PM))


def get_run(run_id):
    return get_success_data(api_client.get_run(run_id, PM))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, PM))


# ---------------------------------------------------------------------------
# Composite scenes
# ---------------------------------------------------------------------------

def plant_base(clock=CLOCK_JUNE, points=DEFAULT_INDEX_POINTS, customer_over=None,
               profile_over=None, formulation_over=None, with_formulation=True):
    """Clock set, index points published, customer + profile (+ formulation)."""
    if clock is not None:
        set_clock(clock)
    if points:
        publish_index_points(points)
    cust = create_customer(**(customer_over or {}))
    prof = create_profile(cust["id"], **(profile_over or {}))
    out = {"cust": cust, "prof": prof}
    if with_formulation:
        out["form"] = create_formulation(prof["id"], **(formulation_over or {}))
    return out


def material_scene(customer_over=None, formulation_over=None, regrind_kg=100, virgin_kg=3000,
                   colorant_kg=100, target_batch_kg=1000.0, with_regrind=True, release=True):
    """Customer + profile + formulation + QC-passed lots + one blend batch.

    Composition for the canonical 1000 kg batch (LDR 25.0, MAXP 20): colorant
    38.5 kg; regrind min(192.3, available); virgin = remainder.
    """
    base = plant_base(customer_over=customer_over, formulation_over=formulation_over)
    lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", virgin_kg, "SUP-V1")
    lot_c = qc_passed_lot("COLORANT", "PVC", "RED", colorant_kg, "SUP-C1")
    lot_r = None
    if with_regrind:
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", regrind_kg, "SUP-R1")
    batch = create_batch(
        base["form"]["id"], lot_v["id"], lot_c["id"],
        regrind_lot_id=lot_r["id"] if lot_r else None,
        target_batch_kg=target_batch_kg,
    )
    if release:
        release_batch(batch["id"])
        batch = get_batch(batch["id"])
    base.update({"lot_v": lot_v, "lot_c": lot_c, "lot_r": lot_r, "batch": batch})
    return base


def running_scene(samples=0, customer_over=None, die_over=None, order_over=None,
                  window=WINDOW_10_12, with_regrind=False, line_speed_mpm=25):
    """Full activation chain ending in a RUNNING production run.

    Returns dict keys: cust, prof, form, die, line, lot_v, lot_c, lot_r,
    batch, wo, asg, run.
    """
    base = plant_base(customer_over=customer_over)
    die = qualify_die(create_die(base["prof"]["id"], **(die_over or {}))["id"])
    line = create_line()
    lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
    lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
    lot_r = None
    if with_regrind:
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
    batch = released_batch(
        base["form"]["id"], lot_v["id"], lot_c["id"],
        regrind_lot_id=lot_r["id"] if lot_r else None,
    )
    wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"],
                         die["id"], **(order_over or {}))
    asg = activated_assignment(wo["id"], die["id"], line["id"], window)
    run = start_run(asg["id"], batch["id"], line_speed_mpm)
    for i in range(samples):
        post_sample(run["id"], IN_CONTROL_MEASUREMENTS if i % 2 == 0 else IN_CONTROL_MEASUREMENTS_B)
    base.update({"die": die, "line": line, "lot_v": lot_v, "lot_c": lot_c, "lot_r": lot_r,
                 "batch": batch, "wo": wo, "asg": asg, "run": get_run(run["id"])})
    return base


def cascade_scene():
    """Run1 RUNNING on asg1; a second order's assignment asg2 SCHEDULED on the
    same line (adjacent half-open window, different die).

    Returns dict keys: cust, prof, form, die_a, die_b, line, lot_v, lot_c,
    batch, wo1, wo2, asg1, asg2, run1.
    """
    base = plant_base(customer_over={"credit_limit_cents": 20000000})
    die_a = qualify_die(create_die(base["prof"]["id"], die_code="D-A")["id"])
    die_b = qualify_die(create_die(base["prof"]["id"], die_code="D-B")["id"])
    line = create_line()
    lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
    lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
    batch = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
    wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_a["id"])
    wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_b["id"],
                          ordered_length_m=3000)
    asg1 = activated_assignment(wo1["id"], die_a["id"], line["id"], WINDOW_10_12)
    asg2 = create_assignment(wo2["id"], die_b["id"], line["id"], WINDOW_12_14)
    run1 = start_run(asg1["id"], batch["id"])
    base.update({"die_a": die_a, "die_b": die_b, "line": line, "lot_v": lot_v, "lot_c": lot_c,
                 "batch": batch, "wo1": wo1, "wo2": wo2, "asg1": asg1, "asg2": asg2,
                 "run1": get_run(run1["id"])})
    return base


def closed_order_scene():
    """Two completed runs (4000 m each) bubble the order IN_PRODUCTION -> CLOSED;
    assignment then closed. Clock stays 2026-06 so pass-through adj is 0.

    Die credits: 2 x 200,000 = 400,000; remaining balance 100,000.
    Returns dict keys: cust, prof, form, die, line, lot_v, lot_c, lot_r,
    batch1, batch2, wo, asg, run1, run2.
    """
    base = plant_base()
    die = qualify_die(create_die(base["prof"]["id"])["id"])
    line = create_line()
    lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
    lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
    lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
    batch1 = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"], regrind_lot_id=lot_r["id"])
    wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
    asg = activated_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)
    run1 = start_run(asg["id"], batch1["id"])
    post_sample(run1["id"], IN_CONTROL_MEASUREMENTS)
    post_sample(run1["id"], IN_CONTROL_MEASUREMENTS_B)
    complete_run(run1["id"], 4000000, 3000, 50)
    batch2 = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
    run2 = start_run(asg["id"], batch2["id"])
    post_sample(run2["id"], IN_CONTROL_MEASUREMENTS)
    post_sample(run2["id"], IN_CONTROL_MEASUREMENTS_B)
    complete_run(run2["id"], 4000000, 3000, 50)
    _ok(api_client.close_assignment(asg["id"], PE), "close assignment")
    base.update({"die": die, "line": line, "lot_v": lot_v, "lot_c": lot_c, "lot_r": lot_r,
                 "batch1": batch1, "batch2": batch2, "wo": get_order(wo["id"]),
                 "asg": get_assignment(asg["id"]), "run1": get_run(run1["id"]),
                 "run2": get_run(run2["id"])})
    return base


def two_mode_dies_scene():
    """Two dies on one profile — PER_METER (die_a) and PER_KG (die_b) — each with
    a completed run of identical output: 4000 m / 3000 kg / 50 kg trim.

    Returns dict keys: cust, prof, form, die_a, die_b, line_a, line_b, lot_v,
    lot_c, lot_r, batch_a, batch_b, wo_a, wo_b, asg_a, asg_b, run_a, run_b.
    """
    base = plant_base()
    die_a = qualify_die(create_die(base["prof"]["id"], die_code="D-A", amortization_mode="PER_METER")["id"])
    die_b = qualify_die(create_die(base["prof"]["id"], die_code="D-B", amortization_mode="PER_KG")["id"])
    line_a = create_line(line_code="L-1")
    line_b = create_line(line_code="L-2")
    lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
    lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
    lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
    batch_a = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"], regrind_lot_id=lot_r["id"])
    batch_b = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
    wo_a = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_a["id"])
    wo_b = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_b["id"])
    asg_a = activated_assignment(wo_a["id"], die_a["id"], line_a["id"], WINDOW_10_12)
    asg_b = activated_assignment(wo_b["id"], die_b["id"], line_b["id"], WINDOW_10_12)
    run_a = start_run(asg_a["id"], batch_a["id"])
    post_sample(run_a["id"], IN_CONTROL_MEASUREMENTS)
    post_sample(run_a["id"], IN_CONTROL_MEASUREMENTS_B)
    complete_run(run_a["id"], 4000000, 3000, 50)
    run_b = start_run(asg_b["id"], batch_b["id"])
    post_sample(run_b["id"], IN_CONTROL_MEASUREMENTS)
    post_sample(run_b["id"], IN_CONTROL_MEASUREMENTS_B)
    complete_run(run_b["id"], 4000000, 3000, 50)
    base.update({"die_a": die_a, "die_b": die_b, "line_a": line_a, "line_b": line_b,
                 "lot_v": lot_v, "lot_c": lot_c, "lot_r": lot_r, "batch_a": batch_a,
                 "batch_b": batch_b, "wo_a": wo_a, "wo_b": wo_b, "asg_a": asg_a,
                 "asg_b": asg_b, "run_a": get_run(run_a["id"]), "run_b": get_run(run_b["id"])})
    return base


def two_basis_orders_scene():
    """Two customers differing only in resin_index_basis, each with a QUOTED
    order written at clock 2026-06 (quote index 100.00); clock then advanced to
    2026-08-01. Index points 2026-06=100.00, 2026-07=120.00, 2026-08=140.00.

    Returns dict keys: cust_ma, cust_sd, prof_ma, prof_sd, die_ma, die_sd,
    form_ma, form_sd, wo_ma, wo_sd.
    """
    set_clock(CLOCK_JUNE)
    publish_index_points()
    cust_ma = create_customer(name="Avg Co", resin_index_basis="MONTHLY_AVG")
    cust_sd = create_customer(name="Spot Co", resin_index_basis="SHIPMENT_DATE")
    prof_ma = create_profile(cust_ma["id"], profile_code="P-MA")
    die_ma = create_die(prof_ma["id"], die_code="D-MA")
    form_ma = create_formulation(prof_ma["id"], formula_code="F-MA")
    prof_sd = create_profile(cust_sd["id"], profile_code="P-SD")
    die_sd = create_die(prof_sd["id"], die_code="D-SD")
    form_sd = create_formulation(prof_sd["id"], formula_code="F-SD")
    wo_ma = create_order(cust_ma["id"], prof_ma["id"], form_ma["id"], die_ma["id"])
    wo_sd = create_order(cust_sd["id"], prof_sd["id"], form_sd["id"], die_sd["id"])
    set_clock(CLOCK_AUGUST)
    return {"cust_ma": cust_ma, "cust_sd": cust_sd, "prof_ma": prof_ma, "prof_sd": prof_sd,
            "die_ma": die_ma, "die_sd": die_sd, "form_ma": form_ma, "form_sd": form_sd,
            "wo_ma": wo_ma, "wo_sd": wo_sd}
