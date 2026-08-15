"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All identities are opaque operator ids (PRD
user/role section): segregation-of-duties-sensitive steps take explicit named
operators — result as tech-a / validate as tech-b, order as doc-1 / verify as
tech-a, report as tech-a / investigate as qo-1.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    BASE_NOW,
    DEFAULT_MIN_SHELF_HOURS,
    TECH_A_ID,
    TECH_B_ID,
)
from .factories import (
    conclude_payload,
    create_cooler_checkout_payload,
    create_cooler_payload,
    create_crossmatch_payload,
    create_issue_record_payload,
    create_mtp_activation_payload,
    create_par_level_policy_payload,
    create_patient_payload,
    create_reaction_payload,
    create_recall_case_payload,
    create_supplier_order_payload,
    create_supplier_payload,
    create_transfusion_order_payload,
    create_type_and_screen_payload,
    crossmatch_result_payload,
    dispatch_pack_payload,
    receive_payload,
    receive_unit_descriptor,
    record_notification_payload,
    return_issue_payload,
    supplier_order_line,
    ts_result_payload,
    workup_payload,
)
from .test_users import TEST_USERS

# Named operator header aliases used across setup chains.
TECH_A = TEST_USERS["tech_a_headers"]
TECH_B = TEST_USERS["tech_b_headers"]
TECH_C = TEST_USERS["tech_c_headers"]
DOC_1 = TEST_USERS["doc_1_headers"]
DOC_2 = TEST_USERS["doc_2_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
QO_1 = TEST_USERS["qo_1_headers"]
QO_2 = TEST_USERS["qo_2_headers"]

SPECIMEN_TIME = "2026-08-10T08:00:00Z"
DEFAULT_COLLECTED = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=BASE_NOW):
    return get_success_data(api_client.set_clock(to_iso8601, SUPERVISOR))


def run_sweep():
    return get_success_data(api_client.sweep(SUPERVISOR))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def make_supplier(name="SanguiServe", license_number="LIC-100",
                  default_lead_time_hours=48):
    payload = create_supplier_payload(
        name=name, license_number=license_number,
        default_lead_time_hours=default_lead_time_hours)
    return get_success_data(api_client.create_supplier(payload, SUPERVISOR))


def make_policy(product_type="RBC", abo_type="O", rh_type="NEG",
                watch_threshold=6, shortage_threshold=4, critical_threshold=2,
                min_shelf_life_hours=DEFAULT_MIN_SHELF_HOURS):
    payload = create_par_level_policy_payload(
        product_type=product_type, abo_type=abo_type, rh_type=rh_type,
        watch_threshold=watch_threshold, shortage_threshold=shortage_threshold,
        critical_threshold=critical_threshold,
        min_shelf_life_hours=min_shelf_life_hours)
    return get_success_data(api_client.create_par_level_policy(payload, SUPERVISOR))


def make_patient(mrn="M-9001", full_name="Pat One", date_of_birth="1979-04-15",
                 special_requirements=None):
    payload = create_patient_payload(mrn=mrn, full_name=full_name,
                                     date_of_birth=date_of_birth)
    if special_requirements is not None:
        payload["special_requirements"] = special_requirements
    return get_success_data(api_client.create_patient(payload, TECH_A))


def make_cooler(cooler_tag="C-1"):
    return get_success_data(
        api_client.create_cooler(create_cooler_payload(cooler_tag), SUPERVISOR))


# ---------------------------------------------------------------------------
# Tier 1: thin re-read helpers (any role may GET; use tech-a by default)
# ---------------------------------------------------------------------------

def get_patient(patient_id):
    return get_success_data(api_client.get_patient(patient_id, TECH_A))


def get_unit(unit_id):
    return get_success_data(api_client.get_blood_unit(unit_id, TECH_A))


def get_supplier_order(order_id):
    return get_success_data(api_client.get_supplier_order(order_id, TECH_A))


def get_order(order_id):
    return get_success_data(api_client.get_transfusion_order(order_id, TECH_A))


def get_ts(ts_id):
    return get_success_data(api_client.get_type_and_screen(ts_id, TECH_A))


def get_crossmatch(crossmatch_id):
    return get_success_data(api_client.get_crossmatch(crossmatch_id, TECH_A))


def get_issue(issue_id):
    return get_success_data(api_client.get_issue_record(issue_id, TECH_A))


def get_reaction(reaction_id):
    return get_success_data(api_client.get_transfusion_reaction(reaction_id, TECH_A))


def get_recall(recall_id):
    return get_success_data(api_client.get_recall_case(recall_id, TECH_A))


def get_mtp(mtp_id):
    return get_success_data(api_client.get_mtp_activation(mtp_id, TECH_A))


def get_cooler(cooler_id):
    return get_success_data(api_client.get_cooler(cooler_id, TECH_A))


def get_checkout(checkout_id):
    return get_success_data(api_client.get_cooler_checkout(checkout_id, TECH_A))


def get_policy(policy_id):
    return get_success_data(api_client.get_par_level_policy(policy_id, TECH_A))


def get_posture(policy_id):
    return get_success_data(api_client.get_policy_posture(policy_id, SUPERVISOR))


def list_wastage(params=None):
    data, _meta = validate_paginated(api_client.list_wastage_records(QO_1, params=params))
    return data


def find_unit_by_number(supplier_order_id, unit_number):
    data, _meta = validate_paginated(api_client.list_blood_units(
        TECH_A, params={"supplier_order_id": supplier_order_id,
                        "unit_number": unit_number}))
    assert len(data) == 1, (
        f"expected exactly one unit {unit_number} on order {supplier_order_id}, "
        f"got {len(data)}"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2: supplier order intake -> received units -> released stock
# ---------------------------------------------------------------------------

def create_draft_order(supplier_id, lines, is_emergency=False,
                       expected_delivery_at=None, creator=COORDINATOR):
    payload = create_supplier_order_payload(supplier_id, lines,
                                            is_emergency=is_emergency)
    if expected_delivery_at is not None:
        payload["expected_delivery_at"] = expected_delivery_at
    return get_success_data(api_client.create_supplier_order(payload, creator))


def submit_order(order_id, actor=COORDINATOR):
    return get_success_data(api_client.submit_supplier_order(order_id, actor))


def acknowledge_order(order_id, actor=COORDINATOR):
    return get_success_data(api_client.acknowledge_supplier_order(order_id, actor))


def receive_units(order_id, unit_descriptors, actor=COORDINATOR):
    """Receive a manifest. Returns the updated supplier order."""
    return get_success_data(api_client.receive_supplier_order(
        order_id, receive_payload(unit_descriptors), actor))


def receive_order_units(supplier_id, lines, unit_descriptors, is_emergency=False,
                        expected_delivery_at=None, actor=COORDINATOR):
    """Create -> submit -> acknowledge -> receive. Returns (order, units dict
    keyed by unit_number)."""
    order = create_draft_order(supplier_id, lines, is_emergency=is_emergency,
                               expected_delivery_at=expected_delivery_at,
                               creator=actor)
    submit_order(order["id"], actor)
    acknowledge_order(order["id"], actor)
    order = receive_units(order["id"], unit_descriptors, actor)
    units = {}
    for descriptor in unit_descriptors:
        units[descriptor["unit_number"]] = find_unit_by_number(
            order["id"], descriptor["unit_number"])
    return order, units


def release_unit(unit_id, actor=TECH_A):
    return get_success_data(api_client.release_unit_from_quarantine(unit_id, actor))


def make_stock(unit_descriptors, supplier=None, release=True, clock=BASE_NOW):
    """One supplier, one supplier order covering every descriptor (lines grouped
    by bucket), all units received; optionally released to AVAILABLE.

    Returns {"supplier":..., "supply_order":..., "units": {number: unit}}.
    """
    if clock is not None:
        set_clock(clock)
    if supplier is None:
        supplier = make_supplier()
    bucket_counts = {}
    for descriptor in unit_descriptors:
        key = (descriptor["product_type"], descriptor["abo_type"],
               descriptor["rh_type"])
        bucket_counts[key] = bucket_counts.get(key, 0) + 1
    lines = [supplier_order_line(product_type=pt, abo_type=abo, rh_type=rh,
                                 quantity=qty)
             for (pt, abo, rh), qty in bucket_counts.items()]
    order, units = receive_order_units(supplier["id"], lines, unit_descriptors)
    if release:
        for number, unit in list(units.items()):
            units[number] = release_unit(unit["id"])
    return {"supplier": supplier, "supply_order": order, "units": units}


# ---------------------------------------------------------------------------
# Tier 2: patient typing (collect -> result -> validate, two operators)
# ---------------------------------------------------------------------------

def collect_ts(patient, specimen_collected_at=SPECIMEN_TIME, collector=TECH_A):
    """Collect a specimen, threading the patient's current version (OCC)."""
    fresh = get_patient(patient["id"])
    payload = create_type_and_screen_payload(
        fresh["id"], specimen_collected_at, fresh["version"])
    return get_success_data(api_client.create_type_and_screen(payload, collector))


def result_ts(ts_id, abo_result="A", rh_result="POS", antibody_screen="NEGATIVE",
              antibody_identifications=None, actor=TECH_A):
    payload = ts_result_payload(
        abo_result=abo_result, rh_result=rh_result, antibody_screen=antibody_screen,
        antibody_identifications=antibody_identifications)
    return get_success_data(api_client.result_type_and_screen(ts_id, payload, actor))


def validate_ts(ts_id, actor=TECH_B):
    return get_success_data(api_client.validate_type_and_screen(ts_id, actor))


def collect_result_validate_ts(patient, specimen_collected_at=SPECIMEN_TIME,
                               abo_result="A", rh_result="POS",
                               antibody_screen="NEGATIVE",
                               antibody_identifications=None):
    """Full typing chain ending in an ACTIVE type-and-screen."""
    ts = collect_ts(patient, specimen_collected_at)
    result_ts(ts["id"], abo_result=abo_result, rh_result=rh_result,
              antibody_screen=antibody_screen,
              antibody_identifications=antibody_identifications)
    return validate_ts(ts["id"])


def make_typed_patient(mrn="M-9001", abo="A", rh="POS", screen="NEGATIVE",
                       antibodies=None, specimen_collected_at=SPECIMEN_TIME,
                       special_requirements=None, full_name="Pat One",
                       date_of_birth="1979-04-15"):
    """Patient with one ACTIVE type-and-screen. Returns (fresh patient, ts)."""
    patient = make_patient(mrn=mrn, full_name=full_name,
                           date_of_birth=date_of_birth,
                           special_requirements=special_requirements)
    ts = collect_result_validate_ts(
        patient, specimen_collected_at=specimen_collected_at, abo_result=abo,
        rh_result=rh, antibody_screen=screen, antibody_identifications=antibodies)
    return get_patient(patient["id"]), ts


# ---------------------------------------------------------------------------
# Tier 3: orders, crossmatches, issues
# ---------------------------------------------------------------------------

def make_order(patient_id, product_type="RBC", units_requested=1,
               urgency="ROUTINE", indication_code="ANEMIA", physician=DOC_1):
    payload = create_transfusion_order_payload(
        patient_id, product_type=product_type, units_requested=units_requested,
        urgency=urgency, indication_code=indication_code)
    return get_success_data(api_client.create_transfusion_order(payload, physician))


def verify_order(order_id, verifier=TECH_A):
    return get_success_data(api_client.verify_order(order_id, verifier))


def make_verified_order(patient_id, product_type="RBC", units_requested=1,
                        urgency="ROUTINE", indication_code="ANEMIA"):
    order = make_order(patient_id, product_type=product_type,
                       units_requested=units_requested, urgency=urgency,
                       indication_code=indication_code)
    return verify_order(order["id"])


def make_pending_crossmatch(order_id, unit_id=None, creator=TECH_A):
    payload = create_crossmatch_payload(order_id, unit_id=unit_id)
    return get_success_data(api_client.create_crossmatch(payload, creator))


def make_compatible_crossmatch(order_id, unit_id, creator=TECH_A, recorder=TECH_B):
    xm = make_pending_crossmatch(order_id, unit_id=unit_id, creator=creator)
    return get_success_data(api_client.record_crossmatch_result(
        xm["id"], crossmatch_result_payload("COMPATIBLE"), recorder))


def make_issue(order_id, unit_id=None, issuer=TECH_A, verifier_id=TECH_B_ID,
               is_emergency_release=None, emergency_justification=None):
    payload = create_issue_record_payload(
        order_id, verifier_id, unit_id=unit_id,
        is_emergency_release=is_emergency_release,
        emergency_justification=emergency_justification)
    return get_success_data(api_client.create_issue_record(payload, issuer))


# ---------------------------------------------------------------------------
# Tier 4: full standard scenario — stock + typed patient + verified order
# ---------------------------------------------------------------------------

def setup_order_with_reserved_units(num_units=1, units_requested=None,
                                    mrn="M-9010", patient_abo="A",
                                    patient_rh="POS", screen="NEGATIVE",
                                    antibodies=None, unit_numbers=None,
                                    unit_product="RBC", unit_abo="O",
                                    unit_rh="NEG",
                                    collected_at=DEFAULT_COLLECTED,
                                    donor_prefix="D-500", lot_number="LOT-1",
                                    urgency="ROUTINE", indication="ANEMIA",
                                    clock=BASE_NOW):
    """Stock of N units + typed patient + verified order + one COMPATIBLE
    crossmatch per unit. Returns a context dict."""
    if units_requested is None:
        units_requested = num_units
    if unit_numbers is None:
        unit_numbers = ["U-%03d" % (100 + i) for i in range(num_units)]
    descriptors = [
        receive_unit_descriptor(
            number, product_type=unit_product, abo_type=unit_abo, rh_type=unit_rh,
            collected_at=collected_at, donor_id="%s-%d" % (donor_prefix, i),
            lot_number=lot_number)
        for i, number in enumerate(unit_numbers)
    ]
    stock = make_stock(descriptors, clock=clock)
    patient, ts = make_typed_patient(mrn=mrn, abo=patient_abo, rh=patient_rh,
                                     screen=screen, antibodies=antibodies)
    order = make_verified_order(patient["id"], product_type=unit_product,
                                units_requested=units_requested, urgency=urgency,
                                indication_code=indication)
    crossmatches = {}
    for number in unit_numbers:
        crossmatches[number] = make_compatible_crossmatch(
            order["id"], stock["units"][number]["id"])
    return {
        "supplier": stock["supplier"],
        "supply_order": stock["supply_order"],
        "units": stock["units"],
        "patient": patient,
        "ts": ts,
        "order": order,
        "crossmatches": crossmatches,
    }


def issue_all(ctx, issuer=TECH_A, verifier_id=TECH_B_ID):
    """Issue every reserved unit of the context against its order."""
    issues = {}
    for number, unit in ctx["units"].items():
        issues[number] = make_issue(ctx["order"]["id"], unit["id"],
                                    issuer=issuer, verifier_id=verifier_id)
    ctx["issues"] = issues
    return issues


def expire_patient_typing(ctx, to_iso="2026-08-14T09:00:00Z"):
    """Advance past the ACTIVE specimen's expiry and sweep; refresh the
    context's patient, order, crossmatches and units in place."""
    set_clock(to_iso)
    sweep_data = run_sweep()
    ctx["patient"] = get_patient(ctx["patient"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    ctx["ts"] = get_ts(ctx["ts"]["id"])
    ctx["crossmatches"] = {
        number: get_crossmatch(xm["id"])
        for number, xm in ctx["crossmatches"].items()
    }
    ctx["units"] = {
        number: get_unit(unit["id"]) for number, unit in ctx["units"].items()
    }
    ctx["sweep"] = sweep_data
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: emergency flows
# ---------------------------------------------------------------------------

def setup_emergency_order_untyped(unit_numbers=("U-100",), unit_product="RBC",
                                  unit_abo="O", unit_rh="NEG", mrn="M-4001",
                                  order_product="RBC", units_requested=1,
                                  collected_at=DEFAULT_COLLECTED, clock=BASE_NOW):
    """Stock + UNTYPED patient + EMERGENCY order verified without a specimen.
    Returns a context dict (order carries the emergency type restriction)."""
    descriptors = [
        receive_unit_descriptor(number, product_type=unit_product,
                                abo_type=unit_abo, rh_type=unit_rh,
                                collected_at=collected_at,
                                donor_id="D-600-%d" % i)
        for i, number in enumerate(unit_numbers)
    ]
    stock = make_stock(descriptors, clock=clock)
    patient = make_patient(mrn=mrn, full_name="Em Doe", date_of_birth="1990-10-10")
    order = make_verified_order(patient["id"], product_type=order_product,
                                units_requested=units_requested,
                                urgency="EMERGENCY", indication_code="TRAUMA")
    return {"supplier": stock["supplier"], "supply_order": stock["supply_order"],
            "units": stock["units"], "patient": patient, "order": order}


def make_emergency_issue(order_id, unit_id=None, issuer=TECH_A,
                         verifier_id=TECH_B_ID,
                         justification="emergency release: trauma bay hemorrhage"):
    return make_issue(order_id, unit_id=unit_id, issuer=issuer,
                      verifier_id=verifier_id, is_emergency_release=True,
                      emergency_justification=justification)


# ---------------------------------------------------------------------------
# Tier 4: massive transfusion protocol
# ---------------------------------------------------------------------------

def make_mtp(patient_id, activation_reason="trauma bay hemorrhage protocol",
             physician=DOC_1):
    payload = create_mtp_activation_payload(patient_id, activation_reason)
    return get_success_data(api_client.create_mtp_activation(payload, physician))


def dispatch_mtp_pack(mtp_id, dispatcher=TECH_A, verifier_id=TECH_B_ID):
    return get_success_data(api_client.dispatch_pack(
        mtp_id, dispatch_pack_payload(verifier_id), dispatcher))


# ---------------------------------------------------------------------------
# Tier 4: reactions and recalls
# ---------------------------------------------------------------------------

def report_reaction(issue_id, reaction_type="SEPTIC", severity="LIFE_THREATENING",
                    symptoms=None, reporter=TECH_A):
    payload = create_reaction_payload(issue_id, reaction_type=reaction_type,
                                      severity=severity, symptoms=symptoms)
    return get_success_data(api_client.create_transfusion_reaction(payload, reporter))


def investigate_reaction(reaction_id, officer=QO_1):
    return get_success_data(api_client.begin_investigation(reaction_id, officer))


def record_reaction_workup(reaction_id, clerical_check_passed=True,
                           dat_result="NEGATIVE", hemolysis_present=False,
                           officer=QO_1):
    payload = workup_payload(clerical_check_passed, dat_result, hemolysis_present)
    return get_success_data(api_client.record_workup(reaction_id, payload, officer))


def conclude_reaction(reaction_id, conclusion="CONFIRMED", final_classification=None,
                      officer=QO_1):
    payload = conclude_payload(conclusion, final_classification)
    return get_success_data(api_client.conclude_reaction(reaction_id, payload, officer))


def setup_started_issue(mrn="M-2005", unit_number="U-100", **overrides):
    """Standard reserved scenario + issue + start-transfusion."""
    ctx = setup_order_with_reserved_units(mrn=mrn, unit_numbers=[unit_number],
                                          **overrides)
    issue_all(ctx)
    issue = ctx["issues"][unit_number]
    issue = get_success_data(api_client.start_transfusion(issue["id"], TECH_A))
    ctx["issue"] = issue
    return ctx


def setup_transfused_issue(mrn="M-4005", unit_number="U-100", **overrides):
    """Standard reserved scenario driven to TRANSFUSED."""
    ctx = setup_started_issue(mrn=mrn, unit_number=unit_number, **overrides)
    issue = get_success_data(
        api_client.complete_transfusion(ctx["issue"]["id"], TECH_A))
    ctx["issue"] = issue
    return ctx


def setup_investigating_reaction(reaction_type="SEPTIC", severity="LIFE_THREATENING",
                                 with_workup=False, **overrides):
    """Started issue + reported reaction + investigation begun."""
    ctx = setup_started_issue(**overrides)
    reaction = report_reaction(ctx["issue"]["id"], reaction_type=reaction_type,
                               severity=severity)
    reaction = investigate_reaction(reaction["id"])
    if with_workup:
        reaction = record_reaction_workup(reaction["id"])
    ctx["reaction"] = reaction
    return ctx


def make_donor_recall(donor_id, reason="donor deferral notice",
                      disposition="DESTRUCTION", implicated_since=None):
    payload = create_recall_case_payload(
        scope_type="DONOR", reason=reason, disposition=disposition,
        donor_id=donor_id, implicated_since=implicated_since)
    return get_success_data(api_client.create_recall_case(payload, QO_1))


def identify_recall(recall_id):
    return get_success_data(api_client.identify_recall_units(recall_id, QO_1))


def quarantine_recall(recall_id):
    return get_success_data(api_client.execute_recall_quarantine(recall_id, QO_1))


def notify_recall(recall_id, issue_record_id):
    return get_success_data(api_client.record_recall_notification(
        recall_id, record_notification_payload(issue_record_id), QO_1))


# ---------------------------------------------------------------------------
# Tier 4: coolers
# ---------------------------------------------------------------------------

def book_checkout(cooler_id, planned_start, planned_end, actor=TECH_A):
    payload = create_cooler_checkout_payload(cooler_id, planned_start, planned_end)
    return get_success_data(api_client.create_cooler_checkout(payload, actor))
