"""Composite setup helpers for the investigational-drug service workflows.

Every helper builds its preconditions from scratch against a fresh server and
returns fully validated response data. Setup calls use the lenient
get_success_data() so failures surface as clear "Setup step failed" errors.

World dict convention: most scenario helpers return a dict with the entities
they created, e.g. {"study": ..., "site": ..., "lot": ..., "kits": [...],
"pharmacist": ..., "pharmacist_headers": ...}.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_study_payload, create_site_payload, create_staff_payload,
    create_lot_payload, create_shipment_payload, create_subject_payload,
    create_dispensing_payload, create_return_payload, create_destruction_payload,
    create_unblinding_payload, create_monitor_visit_payload,
    create_temperature_log_payload, create_fee_schedule_payload,
    replace_slots_payload, slot_spec,
)
from .test_users import TEST_USERS, make_pharmacist_headers, make_unblinded_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]
MONITOR = TEST_USERS["monitor_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource helpers
# ---------------------------------------------------------------------------

def create_study(protocol_number="P-0001", **overrides) -> dict:
    resp = api_client.create_study(create_study_payload(protocol_number=protocol_number, **overrides), SPONSOR)
    return get_success_data(resp)


def create_fee_schedule(study_id, **overrides) -> dict:
    resp = api_client.create_fee_schedule(create_fee_schedule_payload(study_id, **overrides), SPONSOR)
    return get_success_data(resp)


def approve_fee_schedule(schedule_id, expected_study_version) -> dict:
    resp = api_client.approve_fee_schedule(
        schedule_id, {"expected_study_version": expected_study_version}, SPONSOR
    )
    return get_success_data(resp)


def transition_study(study_id, to) -> dict:
    resp = api_client.transition_study(study_id, {"to": to}, SPONSOR)
    return get_success_data(resp)


def create_site(study_id, site_number="S1", **overrides) -> dict:
    resp = api_client.create_site(create_site_payload(study_id, site_number=site_number, **overrides), SPONSOR)
    return get_success_data(resp)


def transition_site(site_id, to) -> dict:
    resp = api_client.transition_site(site_id, {"to": to}, SPONSOR)
    return get_success_data(resp)


def create_staff_member(site_id, license_number="L-0001", full_name="Pharm One",
                        is_unblinded=None) -> dict:
    overrides = {"full_name": full_name, "license_number": license_number}
    if is_unblinded is not None:
        overrides["is_unblinded"] = is_unblinded
    resp = api_client.create_staff(create_staff_payload(site_id, **overrides), SPONSOR)
    return get_success_data(resp)


def create_lot(study_id, lot_number="LOT-0001", **overrides) -> dict:
    resp = api_client.create_lot(create_lot_payload(study_id, lot_number=lot_number, **overrides), SPONSOR)
    return get_success_data(resp)


def ship_kits(lot_id, site_id, kit_numbers, units_per_kit=10) -> list:
    resp = api_client.create_shipment(
        create_shipment_payload(lot_id, site_id, list(kit_numbers), units_per_kit=units_per_kit),
        SPONSOR,
    )
    return get_success_data(resp)


def receive_kit_in_range(kit_id, pharmacist_id, celsius=5.0) -> dict:
    resp = api_client.receive_kit(
        kit_id, {"storage_temp_celsius": celsius}, make_pharmacist_headers(pharmacist_id)
    )
    return get_success_data(resp)


def release_kit_to_available(kit_id, pharmacist_id) -> dict:
    resp = api_client.release_kit(kit_id, make_pharmacist_headers(pharmacist_id))
    return get_success_data(resp)


def make_kits_available(lot_id, site_id, kit_numbers, pharmacist_id, units_per_kit=10) -> list:
    """Ship kits, receive each in range, release each to AVAILABLE. Returns kit list."""
    if not kit_numbers:
        return []
    kits = ship_kits(lot_id, site_id, kit_numbers, units_per_kit=units_per_kit)
    for kit in kits:
        receive_kit_in_range(kit["id"], pharmacist_id)
        release_kit_to_available(kit["id"], pharmacist_id)
    return [get_kit(kit["id"]) for kit in kits]


def get_kit(kit_id) -> dict:
    return get_success_data(api_client.get_kit(kit_id, SPONSOR))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, SPONSOR))


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_site(site_id, SPONSOR))


def get_study(study_id) -> dict:
    return get_success_data(api_client.get_study(study_id, SPONSOR))


def get_subject(subject_id) -> dict:
    return get_success_data(api_client.get_subject(subject_id, SPONSOR))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SPONSOR))


def upload_slots(study_id, expected_study_version, slot_specs) -> list:
    resp = api_client.replace_randomization_slots(
        study_id, replace_slots_payload(slot_specs, expected_study_version), SPONSOR
    )
    return get_success_data(resp)


def standard_slot_specs(kit_numbers, stratum="STANDARD", arm_code="TRT-A") -> list:
    return [slot_spec(i + 1, kn, stratum=stratum, arm_code=arm_code)
            for i, kn in enumerate(kit_numbers)]


def register_subject(site_id, subject_number, pharmacist_id, stratum="STANDARD") -> dict:
    resp = api_client.create_subject(
        create_subject_payload(site_id, subject_number, stratum=stratum),
        make_pharmacist_headers(pharmacist_id),
    )
    return get_success_data(resp)


def randomize_subject(subject_id, pharmacist_id) -> dict:
    resp = api_client.randomize_subject(subject_id, make_pharmacist_headers(pharmacist_id))
    return get_success_data(resp)


def allocate_next_kit(subject_id, pharmacist_id) -> dict:
    resp = api_client.allocate_kit(subject_id, make_pharmacist_headers(pharmacist_id))
    return get_success_data(resp)


def dispense_kit(subject_id, kit_id, visit_number, quantity, pharmacist_id) -> dict:
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(subject_id, kit_id, visit_number, quantity),
        make_pharmacist_headers(pharmacist_id),
    )
    return get_success_data(resp)


def record_return(dispensing_record_id, quantity, pharmacist_id) -> dict:
    resp = api_client.create_return(
        create_return_payload(dispensing_record_id, quantity),
        make_pharmacist_headers(pharmacist_id),
    )
    return get_success_data(resp)


def verify_return(return_id, verifier_staff_id) -> dict:
    resp = api_client.verify_return(return_id, make_pharmacist_headers(verifier_staff_id))
    return get_success_data(resp)


def post_temperature_log(site_id, celsius, pharmacist_id, source="DATALOGGER") -> dict:
    resp = api_client.create_temperature_log(
        create_temperature_log_payload(site_id, celsius, source=source),
        make_pharmacist_headers(pharmacist_id),
    )
    return get_success_data(resp)


def assess_excursion(excursion_id, outcome, rationale="QA review") -> dict:
    resp = api_client.assess_temperature_excursion(
        excursion_id, {"outcome": outcome, "resolution_rationale": rationale}, SPONSOR
    )
    return get_success_data(resp)


def create_monitor_visit(site_id, scheduled_start, scheduled_end, monitor_name="CRA Jo") -> dict:
    resp = api_client.create_monitor_visit(
        create_monitor_visit_payload(site_id, scheduled_start, scheduled_end, monitor_name=monitor_name),
        MONITOR,
    )
    return get_success_data(resp)


def start_visit(visit_id) -> dict:
    return get_success_data(api_client.start_monitor_visit(visit_id, MONITOR))


def close_visit(visit_id, counts) -> dict:
    return get_success_data(api_client.close_monitor_visit(visit_id, {"counts": counts}, MONITOR))


# ---------------------------------------------------------------------------
# Tier 2: composite scenario builders
# ---------------------------------------------------------------------------

def setup_active_study(protocol_number="P-0001", fee_overrides=None, **study_overrides) -> dict:
    """Study created -> fee schedule approved -> study ACTIVE.

    Returns {"study", "study_version", "fee_schedule"}. study_version is the
    version after activation (3: create=1, approve bump=2, activation=3).
    """
    study = create_study(protocol_number=protocol_number, **study_overrides)
    fs = create_fee_schedule(study["id"], **(fee_overrides or {}))
    approve_fee_schedule(fs["id"], expected_study_version=study["version"])
    study = transition_study(study["id"], "ACTIVE")
    return {"study": study, "study_version": study["version"], "fee_schedule": fs}


def setup_pharmacy(protocol_number="P-0001", kit_numbers=("K-1",), units_per_kit=10,
                   study_overrides=None, fee_overrides=None, lot_overrides=None,
                   pharmacist_license="L-0001", extra_licenses=(),
                   unblinded_licenses=(), activate_site=True) -> dict:
    """Active study + site (ACTIVE by default) + staff + lot + kits AVAILABLE.

    Returns a world dict:
      study, study_version, fee_schedule, site, lot, kits (AVAILABLE),
      pharmacist / pharmacist_headers (first blinded staff),
      staff (all blinded PharmacyStaff), unblinded (all unblinded staff).
    """
    ctx = setup_active_study(protocol_number=protocol_number, fee_overrides=fee_overrides,
                             **(study_overrides or {}))
    site = create_site(ctx["study"]["id"])
    if activate_site:
        site = transition_site(site["id"], "ACTIVE")
    pharmacist = create_staff_member(site["id"], license_number=pharmacist_license)
    staff = [pharmacist]
    for i, lic in enumerate(extra_licenses):
        staff.append(create_staff_member(site["id"], license_number=lic,
                                         full_name=f"Pharm Extra {i + 1}"))
    unblinded = []
    for i, lic in enumerate(unblinded_licenses):
        unblinded.append(create_staff_member(site["id"], license_number=lic,
                                             full_name=f"Unblinded {i + 1}", is_unblinded=True))
    lot = create_lot(ctx["study"]["id"], **(lot_overrides or {}))
    kits = make_kits_available(lot["id"], site["id"], kit_numbers,
                               pharmacist["id"], units_per_kit=units_per_kit)
    return {
        **ctx,
        "site": site,
        "lot": lot,
        "kits": kits,
        "pharmacist": pharmacist,
        "pharmacist_headers": make_pharmacist_headers(pharmacist["id"]),
        "staff": staff,
        "unblinded": unblinded,
    }


def setup_randomized_subject(world, subject_number="SUB-1", stratum="STANDARD",
                             slot_kit_numbers=None, slot_specs=None) -> dict:
    """Upload a slot list (if given) and randomize a fresh subject.

    Returns {"subject", "slots"}. The world's study_version is advanced by the
    slot upload (PRD §3.5: replace increments the study version).
    """
    p_id = world["pharmacist"]["id"]
    if slot_specs is None:
        slot_specs = standard_slot_specs(slot_kit_numbers or [k["kit_number"] for k in world["kits"]],
                                         stratum=stratum)
    slots = upload_slots(world["study"]["id"], world["study_version"], slot_specs)
    world["study_version"] += 1
    subject = register_subject(world["site"]["id"], subject_number, p_id, stratum=stratum)
    subject = randomize_subject(subject["id"], p_id)
    # Randomizing increments the study's randomized_subject_count (PRD §3.5), and
    # per PRD §2.4 every mutation of a resource bumps its version — resync so a
    # later OCC-guarded call on this world does not go stale.
    world["study_version"] = get_study(world["study"]["id"])["version"]
    return {"subject": subject, "slots": slots}


def setup_subject_with_allocated_kit(world, subject_number="SUB-1", stratum="STANDARD",
                                     kit_numbers=None) -> dict:
    """Randomize a subject; returns subject plus the kit the slot allocated."""
    result = setup_randomized_subject(world, subject_number=subject_number, stratum=stratum,
                                      slot_kit_numbers=kit_numbers)
    subject = result["subject"]
    kit = next(k for k in [get_kit(k["id"]) for k in world["kits"]]
               if k.get("allocated_subject_id") == subject["id"])
    return {"subject": subject, "kit": kit, "slots": result["slots"]}


def setup_dispensed_subject(world, subject_number="SUB-1", quantity=4, visit_number=1,
                            kit_numbers=None) -> dict:
    """Randomize a subject and dispense their allocated kit once."""
    alloc = setup_subject_with_allocated_kit(world, subject_number=subject_number,
                                             kit_numbers=kit_numbers)
    record = dispense_kit(alloc["subject"]["id"], alloc["kit"]["id"], visit_number,
                          quantity, world["pharmacist"]["id"])
    return {**alloc, "record": record}


def setup_returned_kit(world, subject_number="SUB-1", quantity=4, verifier_id=None,
                       kit_numbers=None) -> dict:
    """Dispense then fully return; kit ends RETURNED, dispensing record RETURNED.

    If verifier_id is given, the return is also verified.
    """
    disp = setup_dispensed_subject(world, subject_number=subject_number, quantity=quantity,
                                   kit_numbers=kit_numbers)
    drug_return = record_return(disp["record"]["id"], quantity, world["pharmacist"]["id"])
    if verifier_id is not None:
        drug_return = verify_return(drug_return["id"], verifier_id)
    return {**disp, "return": drug_return}


def setup_open_excursion(world, readings=((9.0, None),), source="DATALOGGER") -> dict:
    """Post out-of-range readings to open (and optionally extend) an excursion.

    readings: list of (celsius, clock_iso_or_None). A None clock leaves the
    clock untouched. Returns {"excursion_id", "logs"}.
    """
    logs = []
    excursion_id = None
    for celsius, clock in readings:
        if clock is not None:
            set_clock(clock)
        log = post_temperature_log(world["site"]["id"], celsius,
                                   world["pharmacist"]["id"], source=source)
        logs.append(log)
        excursion_id = log["excursion_id"]
    return {"excursion_id": excursion_id, "logs": logs}


def setup_two_reading_both_sides_excursion(protocol_number="P-SEV", lot_budget=600,
                                           kit_numbers=("K-E1", "K-E2")) -> dict:
    """World whose lot is hit by a both-sides excursion: 9.5 at the default
    clock (00:00), then 1.0 at 01:40 — a 100-minute window, deviation 1.5
    degrees above the [2, 8] range. Expected severity: 100 x 4 x 1 = 400."""
    world = setup_pharmacy(protocol_number=protocol_number, kit_numbers=kit_numbers,
                           lot_overrides={"stability_budget_minutes": lot_budget})
    exc = setup_open_excursion(world, readings=((9.5, None), (1.0, "2026-08-01T01:40:00Z")))
    return {**world, **exc}


def setup_started_visit(world, scheduled_start="2026-08-01T00:00:00Z",
                        scheduled_end="2026-08-02T00:00:00Z") -> dict:
    """Monitor visit created and started (default clock lies inside the window)."""
    visit = create_monitor_visit(world["site"]["id"], scheduled_start, scheduled_end)
    return start_visit(visit["id"])


# ---------------------------------------------------------------------------
# Tier 3: heavyweight scenario fixtures (used by calculation/invoice tests)
# ---------------------------------------------------------------------------

def setup_dual_variant_invoice_scenario() -> dict:
    """Study ACTIVE with the full dual-variant invoice activity of PRD §3.9:

    - fees: setup 100000, dispensing 5000/3000 with tier threshold 2,
      monitoring 10000/hr, storage 100/kit-month, unblinding 25000, overhead 10%
    - SUB-A dispensed at visits 1 (08-01), 2 (08-29), 3 (09-26), qty 2 each;
      SUB-B dispensed once (09-26, qty 2)
    - two CLOSED 25-minute monitor visits; one SCHEDULED 60-minute visit
      (2026-09-10) never started; one APPROVED-but-unexecuted unblinding request
    - kits K-5/K-6 remain AVAILABLE
    """
    world = setup_pharmacy(
        protocol_number="P-INV-1",
        kit_numbers=("K-1", "K-2", "K-3", "K-4", "K-5", "K-6"),
        study_overrides={"title": "Invoice Study"},
        fee_overrides={"setup_fee_cents": 100000, "overhead_pct": 10},
        unblinded_licenses=("L-INV-3",),
        pharmacist_license="L-INV-1",
    )
    p_id = world["pharmacist"]["id"]
    kits = {k["kit_number"]: k for k in world["kits"]}
    slots = upload_slots(
        world["study"]["id"], world["study_version"],
        [
            slot_spec(1, "K-1", arm_code="TRT-A"), slot_spec(2, "K-2", arm_code="PBO"),
            slot_spec(3, "K-3", arm_code="TRT-A"), slot_spec(4, "K-4", arm_code="PBO"),
        ],
    )
    world["study_version"] += 1
    sub_a = register_subject(world["site"]["id"], "SUB-A", p_id)
    sub_a = randomize_subject(sub_a["id"], p_id)
    dispense_kit(sub_a["id"], kits["K-1"]["id"], 1, 2, p_id)

    # Two closed 25-minute monitor visits (10:00 -> 10:25).
    for day in ("2026-08-05", "2026-08-12"):
        visit = create_monitor_visit(world["site"]["id"], f"{day}T09:00:00Z", f"{day}T17:00:00Z")
        set_clock(f"{day}T10:00:00Z")
        start_visit(visit["id"])
        set_clock(f"{day}T10:25:00Z")
        close_visit(visit["id"], [
            {"kit_id": kits[kn]["id"], "physical_units": 10}
            for kn in ("K-2", "K-3", "K-4", "K-5", "K-6")
        ])

    allocate_next_kit(sub_a["id"], p_id)
    set_clock("2026-08-29T00:00:00Z")
    dispense_kit(sub_a["id"], kits["K-2"]["id"], 2, 2, p_id)
    allocate_next_kit(sub_a["id"], p_id)
    set_clock("2026-09-26T00:00:00Z")
    dispense_kit(sub_a["id"], kits["K-3"]["id"], 3, 2, p_id)

    sub_b = register_subject(world["site"]["id"], "SUB-B", p_id)
    sub_b = randomize_subject(sub_b["id"], p_id)
    dispense_kit(sub_b["id"], kits["K-4"]["id"], 1, 2, p_id)

    # Pipeline visit: SCHEDULED 60 minutes, never started.
    scheduled_visit = create_monitor_visit(world["site"]["id"],
                                           "2026-09-10T09:00:00Z", "2026-09-10T10:00:00Z")
    # Approved-but-unexecuted unblinding request.
    ub = get_success_data(api_client.create_unblinding_request(
        create_unblinding_payload(sub_a["id"]), INVESTIGATOR))
    set_clock("2026-09-27T00:00:00Z")
    ub = get_success_data(api_client.decide_unblinding_request(
        ub["id"], {"decision": "APPROVED"},
        make_unblinded_pharmacist_headers(world["unblinded"][0]["id"])))

    return {**world, "subjects": {"SUB-A": sub_a, "SUB-B": sub_b},
            "scheduled_visit": scheduled_visit, "unblinding_request": ub}


def setup_book_vs_physical_scenario() -> dict:
    """One kit dispensed (qty 4) and fully returned with the return VERIFIED,
    plus a monitor visit IN_PROGRESS. Book balance is 10 before close."""
    world = setup_pharmacy(protocol_number="P-ACC-1", kit_numbers=("K-A",),
                           study_overrides={"unblinding_suspension_threshold_pct": 50},
                           pharmacist_license="L-ACC-1", extra_licenses=("L-ACC-2",))
    disp = setup_returned_kit(world, subject_number="SUB-R", quantity=4,
                              verifier_id=world["staff"][1]["id"])
    visit = setup_started_visit(world)
    return {**world, **disp, "visit": visit}


def setup_monitor_rounding_scenario() -> dict:
    """Two closed 25-minute monitor visits and nothing else billable; the fee
    schedule prices only monitoring (10000 cents/hour) with 10% overhead."""
    world = setup_pharmacy(
        protocol_number="P-RND-1", kit_numbers=(),
        study_overrides={"phase": "PHASE_I", "blinding_model": "OPEN_LABEL",
                         "max_dose_per_visit_mg": 1000},
        fee_overrides={"dispensing_fee_cents": 0, "dispensing_tier_fee_cents": 0,
                       "storage_fee_cents_per_kit_month": 0, "unblinding_fee_cents": 0,
                       "overhead_pct": 10},
    )
    visits = []
    for day in ("2026-08-05", "2026-08-12"):
        visit = create_monitor_visit(world["site"]["id"], f"{day}T09:00:00Z", f"{day}T17:00:00Z")
        set_clock(f"{day}T10:00:00Z")
        start_visit(visit["id"])
        set_clock(f"{day}T10:25:00Z")
        visits.append(close_visit(visit["id"], []))
    return {**world, "visits": visits}


def setup_returned_kit_for_destruction(protocol_number="P-DES", quantity=4,
                                       witness_license="L-DES-2",
                                       pharmacist_license="L-DES-1") -> dict:
    """Kit RETURNED with book on-hand back at units_received; a second staff
    member exists as designated witness."""
    world = setup_pharmacy(protocol_number=protocol_number, kit_numbers=("K-D",),
                           pharmacist_license=pharmacist_license,
                           extra_licenses=(witness_license,))
    returned = setup_returned_kit(world, subject_number="SUB-D", quantity=quantity)
    return {**world, **returned, "witness": world["staff"][1]}
