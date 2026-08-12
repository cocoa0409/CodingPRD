"""Composite setup helpers.

Every interesting claim in this benchmark requires the system to be in a
state that takes 5-40 API calls to reach (a STERILE tray means: template ->
technician -> sterilizer -> tray -> decontamination -> assembly -> PASS
verification -> load -> start -> complete -> BI incubation -> NEGATIVE result
-> supervisor release). These helpers encapsulate those chains so the tests
read as assertions, not plumbing.

Setup calls use the lenient get_success_data() so a broken precondition
surfaces as a clear "Setup failed" instead of a confusing assertion error.

Identity threading (PRD §2.1): SpdTechnician and SpdSupervisor are
entity-backed roles — every state-changing call they make uses
make_technician_headers(tech_id) / make_supervisor_headers(tech_id) with the
acting Technician's real id. FacilityAdmin / OrScheduler / QualityAuditor are
opaque and use the shared TEST_USERS constants.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    TEST_USERS,
    make_supervisor_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["facility_admin_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]
AUDIT = TEST_USERS["quality_auditor_headers"]

JUSTIFICATION = f.DEFAULTS["JUSTIFICATION"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def create_template(api, **overrides) -> dict:
    return get_success_data(api.create_tray_template(f.create_tray_template_payload(**overrides), ADMIN))


def create_technician(api, **overrides) -> dict:
    return get_success_data(api.create_technician(f.create_technician_payload(**overrides), ADMIN))


def create_sterilizer(api, **overrides) -> dict:
    return get_success_data(api.create_sterilizer(f.create_sterilizer_payload(**overrides), ADMIN))


def create_instrument(api, **overrides) -> dict:
    return get_success_data(api.create_instrument(f.create_instrument_payload(**overrides), ADMIN))


def create_case(api, **overrides) -> dict:
    return get_success_data(api.create_or_case(f.create_or_case_payload(**overrides), SCHED))


def create_loaner(api, case_id, **overrides) -> dict:
    return get_success_data(api.create_loaner_set(f.create_loaner_set_payload(case_id, **overrides), SCHED))


def set_clock(api, to_iso8601) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_tray(api, template_id, tech_id, label="T1") -> dict:
    return get_success_data(
        api.create_tray(f.create_tray_payload(template_id, label=label), make_technician_headers(tech_id))
    )


def decontaminate(api, tray_id, tech_id) -> dict:
    """AWAITING_DECONTAMINATION -> DECONTAMINATED."""
    h = make_technician_headers(tech_id)
    get_success_data(api.start_decontamination(tray_id, h))
    return get_success_data(api.complete_decontamination(tray_id, h))


def create_decontaminated_tray(api, template_id, tech_id, label="T1") -> dict:
    tray = create_tray(api, template_id, tech_id, label=label)
    decontaminate(api, tray["id"], tech_id)
    return get_success_data(api.get_tray(tray["id"], make_technician_headers(tech_id)))


def walk_tray_to_assembled(api, tray_id, tech_id, lines=None) -> dict:
    """DECONTAMINATED -> IN_ASSEMBLY -> ASSEMBLED via a PASS count sheet."""
    h = make_technician_headers(tech_id)
    get_success_data(api.start_assembly(tray_id, h))
    get_success_data(
        api.submit_assembly_verification(tray_id, f.assembly_verification_payload(lines=lines), h)
    )
    return get_success_data(api.get_tray(tray_id, h))


def create_assembled_tray(api, template_id, tech_id, label="T1", lines=None) -> dict:
    tray = create_tray(api, template_id, tech_id, label=label)
    decontaminate(api, tray["id"], tech_id)
    return walk_tray_to_assembled(api, tray["id"], tech_id, lines=lines)


def create_load(api, sterilizer_id, tech_id, planned_start_at="2026-05-01T00:00:00Z") -> dict:
    return get_success_data(
        api.create_sterilization_load(
            f.create_sterilization_load_payload(sterilizer_id, planned_start_at=planned_start_at),
            make_technician_headers(tech_id),
        )
    )


def add_tray_to_load(api, load_id, tray_id, tech_id) -> dict:
    return get_success_data(
        api.add_tray_to_load(load_id, {"tray_id": tray_id}, make_technician_headers(tech_id))
    )


def start_load(api, load_id, tech_id) -> dict:
    return get_success_data(api.start_load(load_id, make_technician_headers(tech_id)))


def complete_load(api, load_id, tech_id) -> dict:
    return get_success_data(api.complete_load(load_id, make_technician_headers(tech_id)))


def first_bi_of_load(api, load_id) -> dict:
    bis = get_success_data(api.list_biological_indicators(ADMIN, params={"load_id": load_id}))
    assert bis, f"Setup failed: no biological indicator found for load {load_id}"
    return bis[0]


def record_bi(api, bi_id, result="NEGATIVE") -> dict:
    return get_success_data(api.record_bi_result(bi_id, {"result": result}, AUDIT))


def release_load(api, load_id, supervisor_id) -> dict:
    return get_success_data(api.release_load(load_id, make_supervisor_headers(supervisor_id)))


def create_sterile_trays(
    api,
    template_id,
    sterilizer_id,
    tech_id,
    supervisor_id,
    labels,
    planned_start_at="2026-05-01T00:00:00Z",
    start_clock=None,
    release_clock="2026-05-01T03:00:00Z",
    lines=None,
):
    """Full pipeline: assemble each tray, run one load, incubate the BI,
    record NEGATIVE, release as the supervisor.

    With the defaults (planned 00:00, released at logical 03:00) a WRAPPED
    tray expires at 2026-05-31T03:00:00Z (PRD §2.10: released_at + 720h).

    ``start_clock`` moves the logical clock forward before the start call —
    required whenever ``planned_start_at`` lies ahead of the current clock
    (PRD §3.4: starting before `planned_start_at` is rejected).

    Returns (trays, load): the post-release tray reads and the released load.
    """
    trays = [
        create_assembled_tray(api, template_id, tech_id, label=label, lines=lines)
        for label in labels
    ]
    load = create_load(api, sterilizer_id, tech_id, planned_start_at=planned_start_at)
    for tray in trays:
        add_tray_to_load(api, load["id"], tray["id"], tech_id)
    if start_clock is not None:
        set_clock(api, start_clock)
    start_load(api, load["id"], tech_id)
    complete_load(api, load["id"], tech_id)
    if release_clock is not None:
        set_clock(api, release_clock)
    bi = first_bi_of_load(api, load["id"])
    record_bi(api, bi["id"], "NEGATIVE")
    release_load(api, load["id"], supervisor_id)
    h = make_technician_headers(tech_id)
    trays = [get_success_data(api.get_tray(t["id"], h)) for t in trays]
    load = get_success_data(api.get_sterilization_load(load["id"], ADMIN))
    return trays, load


def reserve_tray(api, case_id, tray_id, case_version) -> dict:
    return get_success_data(
        api.create_reservation(
            case_id, f.create_reservation_payload(tray_id, case_version), SCHED
        )
    )


# ---------------------------------------------------------------------------
# Difficulty scenario builders (§3 composite states). Each returns a
# SimpleNamespace of the ids/objects the test bodies assert against.
# ---------------------------------------------------------------------------
def setup_availability_projection_scenario(api) -> SimpleNamespace:
    """Two STERILE trays (t1,t2), two IN_LOAD on a RUNNING load whose
    projected release equals the query window, one IN_LOAD on a LOADING load
    projected the next day. Clock ends at 2026-05-01T04:00:00Z."""
    tpl = create_template(
        api, code="ORTHO-01", name="Ortho Major", specialty="ORTHO",
        packaging_type="WRAPPED",
        instrument_requirements=[{"instrument_type": "SCALPEL", "quantity": 2}],
        assembly_minutes=15,
    )
    tech_a = create_technician(
        api, name="Tech A", certification_level=2,
        certified_methods=["STEAM_GRAVITY", "STEAM_PREVAC"],
    )
    tech_s = create_technician(
        api, name="Sup S", certification_level=3,
        certified_methods=["STEAM_GRAVITY", "STEAM_PREVAC", "LOW_TEMP_H2O2"],
    )
    ster = create_sterilizer(api, name="ST-G1", method="STEAM_GRAVITY",
                             chamber_capacity=4, cycle_minutes=60,
                             required_certification_level=1)
    t1 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T1")
    t2 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T2")
    l1 = create_load(api, ster["id"], tech_a["id"], planned_start_at="2026-05-01T00:00:00Z")
    add_tray_to_load(api, l1["id"], t1["id"], tech_a["id"])
    add_tray_to_load(api, l1["id"], t2["id"], tech_a["id"])
    start_load(api, l1["id"], tech_a["id"])
    complete_load(api, l1["id"], tech_a["id"])
    set_clock(api, "2026-05-01T03:00:00Z")
    bi1 = first_bi_of_load(api, l1["id"])
    record_bi(api, bi1["id"], "NEGATIVE")
    release_load(api, l1["id"], tech_s["id"])

    t3 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T3")
    t4 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T4")
    l2 = create_load(api, ster["id"], tech_a["id"], planned_start_at="2026-05-01T04:00:00Z")
    add_tray_to_load(api, l2["id"], t3["id"], tech_a["id"])
    add_tray_to_load(api, l2["id"], t4["id"], tech_a["id"])
    set_clock(api, "2026-05-01T04:00:00Z")
    start_load(api, l2["id"], tech_a["id"])

    t5 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T5")
    l3 = create_load(api, ster["id"], tech_a["id"], planned_start_at="2026-05-02T04:00:00Z")
    add_tray_to_load(api, l3["id"], t5["id"], tech_a["id"])
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           t1=t1, t2=t2, t3=t3, t4=t4, t5=t5,
                           l1=l1, l2=l2, l3=l3)


def setup_iuss_rate_scenario(api) -> SimpleNamespace:
    """Two completed cases, three scheduled-window cases (one cancelled), and
    two IUSS events inside the trailing 168h. Clock ends 2026-05-10T12:00Z."""
    tpl = create_template(api, code="GENS-01", name="General Set", specialty="GEN")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")

    # Case C1 completes 2026-05-08T12:00:00Z with a reserved sterile tray.
    s1, l1 = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                  tech_s["id"], ["S1"])
    s1 = s1[0]
    c1 = create_case(api, case_number="C-1", surgeon="Dr A",
                     scheduled_start_at="2026-05-08T09:00:00Z",
                     scheduled_end_at="2026-05-08T11:00:00Z", priority="ELECTIVE")
    reserve_tray(api, c1["id"], s1["id"], c1["version"])
    set_clock(api, "2026-05-08T08:00:00Z")
    get_success_data(api.start_case(c1["id"], SCHED))
    set_clock(api, "2026-05-08T12:00:00Z")
    get_success_data(api.complete_case(c1["id"], SCHED))

    # Case C2 completes 2026-05-09T12:00:00Z the same way.
    s2, l2 = create_sterile_trays(
        api, tpl["id"], ster["id"], tech_a["id"], tech_s["id"], ["S2"],
        planned_start_at="2026-05-09T06:00:00Z", start_clock="2026-05-09T06:00:00Z",
        release_clock="2026-05-09T09:00:00Z",
    )
    s2 = s2[0]
    c2 = create_case(api, case_number="C-2", surgeon="Dr B",
                     scheduled_start_at="2026-05-09T13:00:00Z",
                     scheduled_end_at="2026-05-09T15:00:00Z", priority="URGENT")
    reserve_tray(api, c2["id"], s2["id"], c2["version"])
    get_success_data(api.start_case(c2["id"], SCHED))
    set_clock(api, "2026-05-09T12:00:00Z")
    get_success_data(api.complete_case(c2["id"], SCHED))

    c3 = create_case(api, case_number="C-3", surgeon="Dr C",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T10:00:00Z", priority="ELECTIVE")
    c4 = create_case(api, case_number="C-4", surgeon="Dr D",
                     scheduled_start_at="2026-05-10T13:00:00Z",
                     scheduled_end_at="2026-05-10T14:00:00Z", priority="ELECTIVE")
    c5 = create_case(api, case_number="C-5", surgeon="Dr E",
                     scheduled_start_at="2026-05-10T15:00:00Z",
                     scheduled_end_at="2026-05-10T16:00:00Z", priority="ELECTIVE")
    get_success_data(api.cancel_case(c5["id"], SCHED))

    u1 = create_decontaminated_tray(api, tpl["id"], tech_a["id"], label="U1")
    u2 = create_decontaminated_tray(api, tpl["id"], tech_a["id"], label="U2")
    set_clock(api, "2026-05-10T10:00:00Z")
    get_success_data(api.create_iuss_exception(
        f.create_iuss_payload(u1["id"], c3["id"]), make_technician_headers(tech_a["id"])))
    get_success_data(api.create_iuss_exception(
        f.create_iuss_payload(u2["id"], c4["id"]), make_technician_headers(tech_a["id"])))
    set_clock(api, "2026-05-10T12:00:00Z")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           c1=c1, c2=c2, c3=c3, c4=c4, c5=c5, u1=u1, u2=u2)


def setup_competency_history_scenario(api) -> SimpleNamespace:
    """Technician B with one FAIL verification (-2) and one FAILED_CYCLE (-8),
    both at 2026-05-01T00:00:00Z; clock then advanced 100 days."""
    tpl = create_template(api, code="CARD-01", name="Cardiac Set", specialty="CARD",
                          assembly_minutes=20)
    tech_b = create_technician(api, name="Tech B", certification_level=2,
                               certification_expires_at="2027-06-01T00:00:00Z")
    ster = create_sterilizer(api, name="ST-G2", chamber_capacity=2)
    hb = make_technician_headers(tech_b["id"])
    v1 = create_tray(api, tpl["id"], tech_b["id"], label="V1")
    decontaminate(api, v1["id"], tech_b["id"])
    get_success_data(api.start_assembly(v1["id"], hb))
    fail_record = get_success_data(api.submit_assembly_verification(
        v1["id"], f.assembly_verification_payload(
            lines=[{"instrument_type": "SCALPEL", "counted_qty": 1}]), hb))
    get_success_data(api.submit_assembly_verification(
        v1["id"], f.assembly_verification_payload(
            lines=[{"instrument_type": "SCALPEL", "counted_qty": 2}]), hb))
    lf = create_load(api, ster["id"], tech_b["id"])
    add_tray_to_load(api, lf["id"], v1["id"], tech_b["id"])
    start_load(api, lf["id"], tech_b["id"])
    get_success_data(api.fail_load_cycle(lf["id"], hb))
    set_clock(api, "2026-08-09T00:00:00Z")
    return SimpleNamespace(tpl=tpl, tech_b=tech_b, ster=ster, v1=v1,
                           fail_record=fail_record)


def setup_repair_ratio_scenario(api) -> SimpleNamespace:
    """Instrument I1 (usage 5 / max 50, replacement 100000) with one completed
    FIXED repair (repair_count 1) and a second order RO2 already SENT."""
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    i1 = create_instrument(api, instrument_type="SCALPEL", serial_number="SN-R1",
                           max_cycles=50, usage_cycles=5,
                           replacement_cost_cents=100000, criticality="ROUTINE")
    ro1 = get_success_data(api.flag_instrument_for_repair(
        i1["id"], make_technician_headers(tech_a["id"])))
    get_success_data(api.send_repair_order(
        ro1["id"], f.send_repair_order_payload(quoted_cost_cents=50000), ADMIN))
    get_success_data(api.receive_repair_order(
        ro1["id"], f.receive_repair_order_payload(actual_cost_cents=50000, outcome="FIXED"), ADMIN))
    ro2 = get_success_data(api.flag_instrument_for_repair(
        i1["id"], make_technician_headers(tech_a["id"])))
    get_success_data(api.send_repair_order(
        ro2["id"], f.send_repair_order_payload(quoted_cost_cents=50000), ADMIN))
    return SimpleNamespace(tech_a=tech_a, i1=i1, ro1=ro1, ro2=ro2)


def setup_prevac_three_tray_load(api) -> SimpleNamespace:
    """Three trays released on a STEAM_PREVAC sterilizer (chargeback per-tray
    rounding scenario)."""
    tpl = create_template(api, code="NEUR-01", name="Neuro Set", specialty="NEUR",
                          assembly_minutes=25)
    tech_a = create_technician(api, name="Tech A", certification_level=2,
                               certified_methods=["STEAM_GRAVITY", "STEAM_PREVAC"])
    tech_s = create_technician(api, name="Sup S", certification_level=3,
                               certified_methods=["STEAM_PREVAC"])
    ster = create_sterilizer(api, name="ST-P1", method="STEAM_PREVAC",
                             chamber_capacity=4, cycle_minutes=45,
                             required_certification_level=1)
    trays, load = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                       tech_s["id"], ["P1", "P2", "P3"])
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           trays=trays, load=load)


def setup_tray_second_loop_scenario(api) -> SimpleNamespace:
    """Tray tz has completed one full loop (released, reserved, case started
    and completed -> back to AWAITING_DECONTAMINATION, cycles_completed 1) and
    has been reprocessed to ASSEMBLED. Clock sits at 2026-05-01T03:00:00Z."""
    tpl = create_template(api, code="ENT-01", name="ENT Set", specialty="ENT",
                          assembly_minutes=12)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, lz1 = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                      tech_s["id"], ["TZ"])
    tz = trays[0]
    cz = create_case(api, case_number="C-Z", surgeon="Dr Z",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    rz = reserve_tray(api, cz["id"], tz["id"], cz["version"])
    get_success_data(api.start_case(cz["id"], SCHED))
    get_success_data(api.complete_case(cz["id"], SCHED))
    # Reprocess the tray back to ASSEMBLED.
    h = make_technician_headers(tech_a["id"])
    get_success_data(api.start_decontamination(tz["id"], h))
    get_success_data(api.complete_decontamination(tz["id"], h))
    get_success_data(api.start_assembly(tz["id"], h))
    get_success_data(api.submit_assembly_verification(
        tz["id"], f.assembly_verification_payload(), h))
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tz=tz, cz=cz, rz=rz, lz1=lz1)


def setup_load_branching_scenario(api) -> SimpleNamespace:
    """Load LA with tray ta is fully RELEASED; load LF with tray tf is RUNNING.
    Clock ends at 2026-05-01T04:00:00Z."""
    tpl = create_template(api, code="OPHT-01", name="Ophthalmic Set", specialty="OPHT",
                          assembly_minutes=8)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, la = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["TA"])
    ta = trays[0]
    tf = create_assembled_tray(api, tpl["id"], tech_a["id"], label="TF")
    lf = create_load(api, ster["id"], tech_a["id"],
                     planned_start_at="2026-05-01T04:00:00Z")
    add_tray_to_load(api, lf["id"], tf["id"], tech_a["id"])
    set_clock(api, "2026-05-01T04:00:00Z")
    start_load(api, lf["id"], tech_a["id"])
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           ta=ta, la=la, tf=tf, lf=lf)


def setup_recall_cascade_scenario(api) -> SimpleNamespace:
    """Tray tq STERILE (load LQ RELEASED) and reserved for case CQ
    (TRAYS_RESERVED); a follow-up BI (lot LOT-9) is INCUBATING on the released
    load. Clock at 2026-05-01T06:00:00Z — past the follow-up BI's due_at."""
    tpl = create_template(api, code="PLAST-01", name="Plastics Set", specialty="PLAST",
                          assembly_minutes=14)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, lq = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["TQ"])
    tq = trays[0]
    cq = create_case(api, case_number="C-Q", surgeon="Dr Q",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="URGENT")
    rq = reserve_tray(api, cq["id"], tq["id"], cq["version"])
    bi2 = get_success_data(api.add_biological_indicator(
        lq["id"], {"lot_number": "LOT-9"}, AUDIT))
    set_clock(api, "2026-05-01T06:00:00Z")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tq=tq, lq=lq, cq=cq, rq=rq, bi2=bi2)


def setup_repair_send_scenario(api) -> SimpleNamespace:
    """Tray TM ASSEMBLED with instruments i1 (SN-M1) and i2 (SN-M2) verified
    PASS; i1 is FLAGGED_FOR_REPAIR with repair order RO1 OPEN."""
    tpl = create_template(api, code="VASC-01", name="Vascular Set", specialty="VASC",
                          assembly_minutes=18)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tm = create_tray(api, tpl["id"], tech_a["id"], label="TM")
    decontaminate(api, tm["id"], tech_a["id"])
    h = make_technician_headers(tech_a["id"])
    get_success_data(api.start_assembly(tm["id"], h))
    i1 = create_instrument(api, instrument_type="SCALPEL", serial_number="SN-M1",
                           max_cycles=50, usage_cycles=0,
                           replacement_cost_cents=100000, criticality="ROUTINE")
    i2 = create_instrument(api, instrument_type="SCALPEL", serial_number="SN-M2",
                           max_cycles=50, usage_cycles=0,
                           replacement_cost_cents=100000, criticality="ROUTINE")
    get_success_data(api.assign_instrument(i1["id"], {"tray_id": tm["id"]}, h))
    get_success_data(api.assign_instrument(i2["id"], {"tray_id": tm["id"]}, h))
    get_success_data(api.submit_assembly_verification(
        tm["id"], f.assembly_verification_payload(), h))
    ro1 = get_success_data(api.flag_instrument_for_repair(i1["id"], h))
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tm=tm, i1=i1, i2=i2, ro1=ro1)


def setup_release_conflict_scenario(api) -> SimpleNamespace:
    """Load LS with one tray is RUNNING; its operator is technician A (the
    same identity that will attempt the release under the supervisor role)."""
    tpl = create_template(api, code="ORTH-02", name="Ortho Minor", specialty="ORTHO")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    ster = create_sterilizer(api, name="ST-G1")
    ts = create_assembled_tray(api, tpl["id"], tech_a["id"], label="TS")
    ls = create_load(api, ster["id"], tech_a["id"])
    add_tray_to_load(api, ls["id"], ts["id"], tech_a["id"])
    start_load(api, ls["id"], tech_a["id"])
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, ster=ster, ts=ts, ls=ls)


def setup_reservation_priority_scenario(api) -> SimpleNamespace:
    """Tray tx STERILE with sterility_expires_at 2026-06-08T10:00:00Z (released
    2026-05-09T10:00 + 720h WRAPPED); case CA (2026-06-08T09:00-10:00) already
    reserved on tx; case CB (2026-06-08T10:30-11:30) created, version fresh."""
    tpl = create_template(api, code="GU-01", name="GU Set", specialty="GU")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, lx = create_sterile_trays(
        api, tpl["id"], ster["id"], tech_a["id"], tech_s["id"], ["TX"],
        release_clock="2026-05-09T10:00:00Z",
    )
    tx = trays[0]
    ca = create_case(api, case_number="C-A", surgeon="Dr A",
                     scheduled_start_at="2026-06-08T09:00:00Z",
                     scheduled_end_at="2026-06-08T10:00:00Z", priority="ELECTIVE")
    reserve_tray(api, ca["id"], tx["id"], ca["version"])
    cb = create_case(api, case_number="C-B", surgeon="Dr B",
                     scheduled_start_at="2026-06-08T10:30:00Z",
                     scheduled_end_at="2026-06-08T11:30:00Z", priority="ELECTIVE")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tx=tx, lx=lx, ca=ca, cb=cb)


def setup_iuss_boundary_scenario(api) -> SimpleNamespace:
    """Four DECONTAMINATED trays (u1..u4) and one EMERGENCY case CU; no IUSS
    events logged yet. Clock at the 2026-05-01T00:00:00Z default."""
    tpl = create_template(api, code="TRM-01", name="Trauma Set", specialty="TRM",
                          assembly_minutes=8)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    cu = create_case(api, case_number="C-U", surgeon="Dr U",
                     scheduled_start_at="2026-05-02T09:00:00Z",
                     scheduled_end_at="2026-05-02T10:00:00Z", priority="EMERGENCY")
    trays = [create_decontaminated_tray(api, tpl["id"], tech_a["id"], label=f"U{i}")
             for i in range(1, 5)]
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, cu=cu, trays=trays)


def setup_count_sheet_scenario(api) -> SimpleNamespace:
    """Template requires SCALPEL x2 + FORCEPS x1; trays ta and tb both sit
    IN_ASSEMBLY awaiting their count sheets."""
    tpl = create_template(
        api, code="SP-01", name="Spine Set", specialty="SPINE",
        packaging_type="RIGID_CONTAINER",
        instrument_requirements=[
            {"instrument_type": "SCALPEL", "quantity": 2},
            {"instrument_type": "FORCEPS", "quantity": 1},
        ],
        assembly_minutes=30,
    )
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    ta = create_tray(api, tpl["id"], tech_a["id"], label="TA")
    decontaminate(api, ta["id"], tech_a["id"])
    h = make_technician_headers(tech_a["id"])
    get_success_data(api.start_assembly(ta["id"], h))
    tb = create_tray(api, tpl["id"], tech_a["id"], label="TB")
    decontaminate(api, tb["id"], tech_a["id"])
    get_success_data(api.start_assembly(tb["id"], h))
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, ta=ta, tb=tb)


def setup_sterility_boundary_scenario(api) -> SimpleNamespace:
    """Tray te STERILE with sterility_expires_at exactly 2026-05-31T03:00:00Z;
    case CE1 scheduled exactly at the expiry instant, case CE2 one minute
    earlier."""
    tpl = create_template(api, code="ENT-02", name="ENT Basic", specialty="ENT")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, le = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["TE"])
    te = trays[0]
    ce1 = create_case(api, case_number="C-E1", surgeon="Dr E",
                      scheduled_start_at="2026-05-31T03:00:00Z",
                      scheduled_end_at="2026-05-31T04:00:00Z", priority="ELECTIVE")
    ce2 = create_case(api, case_number="C-E2", surgeon="Dr E",
                      scheduled_start_at="2026-05-31T02:59:00Z",
                      scheduled_end_at="2026-05-31T04:00:00Z", priority="ELECTIVE")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           te=te, le=le, ce1=ce1, ce2=ce2)


def setup_sterilizer_idle_scenario(api) -> SimpleNamespace:
    """Load L1 (with t1) RUNNING on sterilizer SG, holding it RUNNING; load L2
    (with t2, planned 2026-05-01T02:00:00Z, non-overlapping) waits LOADING.
    Clock at 2026-05-01T02:00:00Z."""
    tpl = create_template(api, code="LAP-01", name="Lap Set", specialty="GEN")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    sg = create_sterilizer(api, name="SG")
    t1 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T1")
    l1 = create_load(api, sg["id"], tech_a["id"], planned_start_at="2026-05-01T00:00:00Z")
    add_tray_to_load(api, l1["id"], t1["id"], tech_a["id"])
    start_load(api, l1["id"], tech_a["id"])
    t2 = create_assembled_tray(api, tpl["id"], tech_a["id"], label="T2")
    l2 = create_load(api, sg["id"], tech_a["id"], planned_start_at="2026-05-01T02:00:00Z")
    add_tray_to_load(api, l2["id"], t2["id"], tech_a["id"])
    set_clock(api, "2026-05-01T02:00:00Z")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, sg=sg,
                           t1=t1, t2=t2, l1=l1, l2=l2)


def setup_reservation_gated_scenario(api) -> SimpleNamespace:
    """Tray tj is IN_LOAD on load LJ which has RUN its course to COMPLETED
    (cycle done, BI still incubating); case CJ created with version captured."""
    tpl = create_template(api, code="GYN-01", name="GYN Set", specialty="GYN")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    tj = create_assembled_tray(api, tpl["id"], tech_a["id"], label="TJ")
    lj = create_load(api, ster["id"], tech_a["id"])
    add_tray_to_load(api, lj["id"], tj["id"], tech_a["id"])
    start_load(api, lj["id"], tech_a["id"])
    complete_load(api, lj["id"], tech_a["id"])
    cj = create_case(api, case_number="C-J", surgeon="Dr J",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tj=tj, lj=lj, cj=cj)


def setup_loaner_gate_scenario(api) -> SimpleNamespace:
    """Tray tl STERILE; case CL (2026-05-10T09:00-11:00) TRAYS_RESERVED on tl;
    loaner LN (3 trays) BOOKED for CL with due_by 2026-05-09T09:00:00Z."""
    tpl = create_template(api, code="CARD-02", name="Cardiac Valve", specialty="CARD",
                          assembly_minutes=20)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, ll = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["TL"])
    tl = trays[0]
    cl = create_case(api, case_number="C-L", surgeon="Dr L",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    ln = create_loaner(api, cl["id"], vendor="VendorMed", tray_count=3)
    reserve_tray(api, cl["id"], tl["id"], cl["version"])
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tl=tl, ll=ll, cl=cl, ln=ln)


def setup_sterilizer_window_scenario(api) -> SimpleNamespace:
    """Just a technician and an empty STEAM_GRAVITY sterilizer (60 min)."""
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    sg = create_sterilizer(api, name="SG", method="STEAM_GRAVITY",
                           chamber_capacity=4, cycle_minutes=60,
                           required_certification_level=1)
    return SimpleNamespace(tech_a=tech_a, sg=sg)


def setup_buffered_gap_scenario(api) -> SimpleNamespace:
    """Tray tr STERILE; cases CA (09:00-12:00), CB (12:45-14:00) and CC
    (12:44-14:00) on 2026-05-10 exist unreserved, versions fresh."""
    tpl = create_template(api, code="THOR-01", name="Thoracic Set", specialty="THOR",
                          assembly_minutes=15)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, lr = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["TR"])
    tr = trays[0]
    ca = create_case(api, case_number="C-A", surgeon="Dr A",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T12:00:00Z", priority="ELECTIVE")
    cb = create_case(api, case_number="C-B", surgeon="Dr B",
                     scheduled_start_at="2026-05-10T12:45:00Z",
                     scheduled_end_at="2026-05-10T14:00:00Z", priority="ELECTIVE")
    cc = create_case(api, case_number="C-C", surgeon="Dr C",
                     scheduled_start_at="2026-05-10T12:44:00Z",
                     scheduled_end_at="2026-05-10T14:00:00Z", priority="URGENT")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           tr=tr, lr=lr, ca=ca, cb=cb, cc=cc)


def setup_sterile_pair_scenario(api) -> SimpleNamespace:
    """Trays k1 and k2 STERILE via one shared load; case CK
    (2026-05-10T09:00-11:00) created. Exactly two STERILE trays of the
    template exist."""
    tpl = create_template(api, code="ONC-01", name="Oncology Set", specialty="ONC")
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tech_s = create_technician(api, name="Sup S", certification_level=3)
    ster = create_sterilizer(api, name="ST-G1")
    trays, lk = create_sterile_trays(api, tpl["id"], ster["id"], tech_a["id"],
                                     tech_s["id"], ["K1", "K2"])
    ck = create_case(api, case_number="C-K", surgeon="Dr K",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tech_s=tech_s, ster=ster,
                           k1=trays[0], k2=trays[1], lk=lk, ck=ck)


def setup_repair_cycle_scenario(api) -> SimpleNamespace:
    """Tray TM ASSEMBLED with instruments i1 (SN-M1) and i2 (SN-M2) assigned
    and a PASS verification on file; exactly two instruments exist."""
    tpl = create_template(api, code="OMFS-01", name="OMFS Set", specialty="OMFS",
                          assembly_minutes=12)
    tech_a = create_technician(api, name="Tech A", certification_level=2)
    tm = create_tray(api, tpl["id"], tech_a["id"], label="TM")
    decontaminate(api, tm["id"], tech_a["id"])
    h = make_technician_headers(tech_a["id"])
    get_success_data(api.start_assembly(tm["id"], h))
    i1 = create_instrument(api, instrument_type="SCALPEL", serial_number="SN-M1",
                           max_cycles=50, usage_cycles=0,
                           replacement_cost_cents=100000, criticality="ROUTINE")
    i2 = create_instrument(api, instrument_type="SCALPEL", serial_number="SN-M2",
                           max_cycles=50, usage_cycles=0,
                           replacement_cost_cents=100000, criticality="ROUTINE")
    get_success_data(api.assign_instrument(i1["id"], {"tray_id": tm["id"]}, h))
    get_success_data(api.assign_instrument(i2["id"], {"tray_id": tm["id"]}, h))
    get_success_data(api.submit_assembly_verification(
        tm["id"], f.assembly_verification_payload(), h))
    return SimpleNamespace(tpl=tpl, tech_a=tech_a, tm=tm, i1=i1, i2=i2)


def setup_h2o2_gate_scenario(api) -> SimpleNamespace:
    """Technician A (level 3, GRAVITY + H2O2 certified) is driven to exactly
    competency 70 (two FAILED_CYCLEs = -16, seven FAIL verifications = -14),
    starts an H2O2 load G1 successfully at 70, then an eighth FAIL drops him
    to 68 with a second H2O2 load G2 waiting in LOADING."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=3,
                           certified_methods=["STEAM_GRAVITY", "LOW_TEMP_H2O2"])
    sg = create_sterilizer(api, name="SG", method="STEAM_GRAVITY",
                           chamber_capacity=4, cycle_minutes=60,
                           required_certification_level=1)
    sh = create_sterilizer(api, name="SH", method="LOW_TEMP_H2O2",
                           chamber_capacity=2, cycle_minutes=90,
                           required_certification_level=1)
    h = make_technician_headers(ta["id"])
    v1 = create_tray(api, tpl["id"], ta["id"], label="V1")
    decontaminate(api, v1["id"], ta["id"])
    get_success_data(api.start_assembly(v1["id"], h))
    for _ in range(7):
        get_success_data(api.submit_assembly_verification(
            v1["id"], f.assembly_verification_payload(
                lines=[{"instrument_type": "SCALPEL", "counted_qty": 1}]), h))
    get_success_data(api.submit_assembly_verification(
        v1["id"], f.assembly_verification_payload(), h))
    for _ in range(2):
        lf = create_load(api, sg["id"], ta["id"])
        add_tray_to_load(api, lf["id"], v1["id"], ta["id"])
        start_load(api, lf["id"], ta["id"])
        get_success_data(api.fail_load_cycle(lf["id"], h))
    g1 = create_load(api, sh["id"], ta["id"])
    add_tray_to_load(api, g1["id"], v1["id"], ta["id"])
    g1_started = start_load(api, g1["id"], ta["id"])
    complete_load(api, g1["id"], ta["id"])
    v2 = create_tray(api, tpl["id"], ta["id"], label="V2")
    decontaminate(api, v2["id"], ta["id"])
    get_success_data(api.start_assembly(v2["id"], h))
    get_success_data(api.submit_assembly_verification(
        v2["id"], f.assembly_verification_payload(
            lines=[{"instrument_type": "SCALPEL", "counted_qty": 1}]), h))
    get_success_data(api.submit_assembly_verification(
        v2["id"], f.assembly_verification_payload(), h))
    g2 = create_load(api, sh["id"], ta["id"])
    add_tray_to_load(api, g2["id"], v2["id"], ta["id"])
    return SimpleNamespace(tpl=tpl, ta=ta, sg=sg, sh=sh, v1=v1, v2=v2,
                           g1=g1, g1_started=g1_started, g2=g2)


def setup_expired_reservation_scenario(api) -> SimpleNamespace:
    """Tray te STERILE (expiry 2026-05-31T03:00:00Z) reserved for case CX
    (TRAYS_RESERVED); the logical clock is then advanced past the expiry to
    2026-06-01T00:00:00Z without touching the tray."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2)
    ts = create_technician(api, name="Sup S", certification_level=3)
    sg = create_sterilizer(api, name="SG")
    trays, le = create_sterile_trays(api, tpl["id"], sg["id"], ta["id"],
                                     ts["id"], ["TE"])
    te = trays[0]
    cx = create_case(api, case_number="C-X", surgeon="Dr X",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    rx = reserve_tray(api, cx["id"], te["id"], cx["version"])
    set_clock(api, "2026-06-01T00:00:00Z")
    return SimpleNamespace(tpl=tpl, ta=ta, ts=ts, sg=sg, te=te, le=le,
                           cx=cx, rx=rx)


def setup_occ_reservation_scenario(api) -> SimpleNamespace:
    """Trays o1 and o2 STERILE via one load; case CO created at version 1."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2)
    ts = create_technician(api, name="Sup S", certification_level=3)
    sg = create_sterilizer(api, name="SG")
    trays, lo = create_sterile_trays(api, tpl["id"], sg["id"], ta["id"],
                                     ts["id"], ["O1", "O2"])
    co = create_case(api, case_number="C-O", surgeon="Dr O",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    return SimpleNamespace(tpl=tpl, ta=ta, ts=ts, sg=sg,
                           o1=trays[0], o2=trays[1], lo=lo, co=co)


def setup_case_terminal_gate_scenario(api) -> SimpleNamespace:
    """Trays g1,g2 STERILE; case CG cancelled (fresh version re-read); case CH
    holds reservation RH on g1."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2)
    ts = create_technician(api, name="Sup S", certification_level=3)
    sg = create_sterilizer(api, name="SG")
    trays, lg = create_sterile_trays(api, tpl["id"], sg["id"], ta["id"],
                                     ts["id"], ["G1", "G2"])
    g1, g2 = trays
    cg = create_case(api, case_number="C-G", surgeon="Dr G",
                     scheduled_start_at="2026-05-10T09:00:00Z",
                     scheduled_end_at="2026-05-10T11:00:00Z", priority="ELECTIVE")
    get_success_data(api.cancel_case(cg["id"], SCHED))
    cg = get_success_data(api.get_or_case(cg["id"], SCHED))
    ch = create_case(api, case_number="C-H", surgeon="Dr H",
                     scheduled_start_at="2026-05-10T13:00:00Z",
                     scheduled_end_at="2026-05-10T15:00:00Z", priority="ELECTIVE")
    rh = reserve_tray(api, ch["id"], g1["id"], ch["version"])
    return SimpleNamespace(tpl=tpl, ta=ta, ts=ts, sg=sg, g1=g1, g2=g2, lg=lg,
                           cg=cg, ch=ch, rh=rh)


def setup_cert_expiry_scenario(api) -> SimpleNamespace:
    """Load LOADING with one ASSEMBLED tray; technician A's certification
    expired at 2026-05-01T01:00:00Z and the clock now reads 02:00."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2,
                           certification_expires_at="2026-05-01T01:00:00Z")
    sg = create_sterilizer(api, name="SG")
    s2 = create_assembled_tray(api, tpl["id"], ta["id"], label="S2")
    ld = create_load(api, sg["id"], ta["id"])
    add_tray_to_load(api, ld["id"], s2["id"], ta["id"])
    set_clock(api, "2026-05-01T02:00:00Z")
    return SimpleNamespace(tpl=tpl, ta=ta, sg=sg, s2=s2, ld=ld)


def setup_suspended_start_scenario(api) -> SimpleNamespace:
    """Load LOADING with one ASSEMBLED tray; technician A is then SUSPENDED by
    supervisor S. Every other load-start gate would pass."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2)
    ts = create_technician(api, name="Sup S", certification_level=3)
    sg = create_sterilizer(api, name="SG")
    s1 = create_assembled_tray(api, tpl["id"], ta["id"], label="S1")
    ld = create_load(api, sg["id"], ta["id"])
    add_tray_to_load(api, ld["id"], s1["id"], ta["id"])
    get_success_data(api.suspend_technician(ta["id"], make_supervisor_headers(ts["id"])))
    return SimpleNamespace(tpl=tpl, ta=ta, ts=ts, sg=sg, s1=s1, ld=ld)


def setup_completed_load_scenario(api, label="E1") -> SimpleNamespace:
    """Load with one tray driven to COMPLETED; its auto-created BI is still
    INCUBATING (due at completed_at + 3h = 2026-05-01T03:00:00Z)."""
    tpl = create_template(api, code="GEN-01", name="General", specialty="GEN")
    ta = create_technician(api, name="Tech A", certification_level=2)
    ts = create_technician(api, name="Sup S", certification_level=3)
    sg = create_sterilizer(api, name="SG")
    tray = create_assembled_tray(api, tpl["id"], ta["id"], label=label)
    ld = create_load(api, sg["id"], ta["id"])
    add_tray_to_load(api, ld["id"], tray["id"], ta["id"])
    start_load(api, ld["id"], ta["id"])
    complete_load(api, ld["id"], ta["id"])
    return SimpleNamespace(tpl=tpl, ta=ta, ts=ts, sg=sg, tray=tray, ld=ld)
