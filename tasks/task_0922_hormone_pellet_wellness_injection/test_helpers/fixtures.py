"""Composite setup helpers.

Every entity these helpers need is built through declared endpoints; nothing is
assumed to pre-exist.  Setup calls use the lenient `get_success_data` so that a
broken precondition reports as a setup failure rather than as a confusing
assertion inside the test under exercise.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import PELLET_LADDER, TEST_DEFAULTS
from .test_users import TEST_USERS, make_physician_headers

ADMIN = TEST_USERS["clinic_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ══════════════════════════════════════════════════════════════════════════════
# Tier 0 — single-call primitives
# ══════════════════════════════════════════════════════════════════════════════
def set_clock(api, to_iso8601: str) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def new_physician(api, full_name="Dr Ada Reyes", npi=None) -> dict:
    return get_success_data(
        api.create_provider(
            {
                "full_name": full_name,
                "provider_type": "PHYSICIAN",
                "npi": npi or TEST_DEFAULTS["PHYSICIAN_NPI"],
            },
            ADMIN,
        )
    )


def new_nurse(api, full_name="Nina Okafor RN", npi=None) -> dict:
    return get_success_data(
        api.create_provider(
            {
                "full_name": full_name,
                "provider_type": "NURSE_INJECTOR",
                "npi": npi or TEST_DEFAULTS["NURSE_NPI"],
            },
            ADMIN,
        )
    )


def new_patient(
    api, full_name="Pat One", email="p1@example.com", sex_at_birth="MALE",
    date_of_birth="1980-01-01",
) -> dict:
    return get_success_data(
        api.create_patient(
            {
                "full_name": full_name,
                "date_of_birth": date_of_birth,
                "email": email,
                "sex_at_birth": sex_at_birth,
            },
            ADMIN,
        )
    )


def publish_protocol(api, physician_id, hormone_type="TESTOSTERONE", title=None) -> dict:
    return get_success_data(
        api.publish_protocol(
            {
                "hormone_type": hormone_type,
                "title": title or f"{hormone_type} pellet protocol",
                "published_by_provider_id": physician_id,
            },
            make_physician_headers(physician_id),
        )
    )


def sign_consent(
    api, patient_id, hormone_type="TESTOSTERONE", protocol_version=1,
    consented_max_dose_mg=2000,
) -> dict:
    return get_success_data(
        api.sign_consent(
            {
                "patient_id": patient_id,
                "hormone_type": hormone_type,
                "protocol_version": protocol_version,
                "consented_max_dose_mg": consented_max_dose_mg,
            },
            FRONT_DESK,
        )
    )


def record_consult(
    api, patient_id, physician_id, hormone_type="TESTOSTERONE",
    prescribed_dose_mg=1000, symptom_score=55, indication="Hypogonadism",
) -> dict:
    return get_success_data(
        api.create_consult(
            {
                "patient_id": patient_id,
                "physician_id": physician_id,
                "hormone_type": hormone_type,
                "prescribed_dose_mg": prescribed_dose_mg,
                "symptom_score": symptom_score,
                "indication": indication,
            },
            make_physician_headers(physician_id),
        )
    )


def new_standing_order(
    api, physician_id, scope_hormone_types=None, scope_injection_types=None,
    max_dose_mg=None, valid_from=None, valid_until=None,
) -> dict:
    return get_success_data(
        api.create_standing_order(
            {
                "physician_id": physician_id,
                "scope_hormone_types": (
                    ["TESTOSTERONE", "ESTRADIOL"] if scope_hormone_types is None
                    else scope_hormone_types
                ),
                "scope_injection_types": (
                    ["B12", "LIPOTROPIC", "VITAMIN_D", "GLUTATHIONE"]
                    if scope_injection_types is None else scope_injection_types
                ),
                "max_dose_mg": max_dose_mg or TEST_DEFAULTS["STANDING_ORDER_MAX_DOSE_MG"],
                "valid_from": valid_from or TEST_DEFAULTS["STANDING_ORDER_VALID_FROM"],
                "valid_until": valid_until or TEST_DEFAULTS["STANDING_ORDER_VALID_UNTIL"],
            },
            make_physician_headers(physician_id),
        )
    )


def receive_lot(
    api, lot_code, hormone_type="TESTOSTERONE", strength_mg=200,
    expiry_date=None, qty_received=20,
) -> dict:
    return get_success_data(
        api.create_pellet_lot(
            {
                "lot_code": lot_code,
                "hormone_type": hormone_type,
                "strength_mg": strength_mg,
                "expiry_date": expiry_date or TEST_DEFAULTS["LOT_EXPIRY"],
                "qty_received": qty_received,
            },
            INVENTORY,
        )
    )


def release_lot(api, lot_id) -> dict:
    return get_success_data(api.release_pellet_lot(lot_id, INVENTORY))


def receive_and_release_lot(api, lot_code, **kwargs) -> dict:
    lot = receive_lot(api, lot_code, **kwargs)
    release_lot(api, lot["id"])
    return get_success_data(api.get_pellet_lot(lot["id"], INVENTORY))


def record_lab_panel(
    api, patient_id, provider_id, analyte="TOTAL_TESTOSTERONE", value=400,
    drawn_at="2026-05-01T00:00:00Z", is_trough_draw=None,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "ordered_by_provider_id": provider_id,
        "analyte": analyte,
        "value": value,
        "drawn_at": drawn_at,
    }
    if is_trough_draw is not None:
        payload["is_trough_draw"] = is_trough_draw
    return get_success_data(api.create_lab_panel(payload, make_physician_headers(provider_id)))


def book_procedure(
    api, patient_id, provider_id, consult_id, standing_order_id,
    procedure_type="INITIAL", room_code="RM1", scheduled_start="2026-06-01T09:00:00Z",
    lab_panel_id=None, membership_id=None, headers=None,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "consult_id": consult_id,
        "standing_order_id": standing_order_id,
        "procedure_type": procedure_type,
        "room_code": room_code,
        "scheduled_start": scheduled_start,
    }
    if lab_panel_id is not None:
        payload["lab_panel_id"] = lab_panel_id
    if membership_id is not None:
        payload["membership_id"] = membership_id
    return get_success_data(api.create_procedure(payload, headers or FRONT_DESK))


def read_procedure(api, procedure_id) -> dict:
    return get_success_data(api.get_procedure(procedure_id, FRONT_DESK))


def read_patient(api, patient_id) -> dict:
    return get_success_data(api.get_patient(patient_id, ADMIN))


def read_lot(api, lot_id) -> dict:
    return get_success_data(api.get_pellet_lot(lot_id, INVENTORY))


def read_membership(api, membership_id) -> dict:
    return get_success_data(api.get_membership(membership_id, FRONT_DESK))


def read_series_pack(api, pack_id) -> dict:
    return get_success_data(api.get_series_pack(pack_id, FRONT_DESK))


def read_financing_plan(api, plan_id) -> dict:
    return get_success_data(api.get_financing_plan(plan_id, FRONT_DESK))


def read_consent(api, consent_id) -> dict:
    return get_success_data(api.get_consent(consent_id, FRONT_DESK))


def read_standing_order(api, order_id) -> dict:
    return get_success_data(api.get_standing_order(order_id, FRONT_DESK))


def read_injection_visit(api, visit_id) -> dict:
    return get_success_data(api.get_injection_visit(visit_id, FRONT_DESK))


def read_adverse_event(api, event_id) -> dict:
    return get_success_data(api.get_adverse_event(event_id, ADMIN))


def read_notification(api, notification_id) -> dict:
    return get_success_data(api.get_notification(notification_id, FRONT_DESK))


def procedure_version(api, procedure_id) -> int:
    return read_procedure(api, procedure_id)["version"]


def patient_version(api, patient_id) -> int:
    return read_patient(api, patient_id)["version"]


def membership_version(api, membership_id) -> int:
    return read_membership(api, membership_id)["version"]


def attach_consent_to(api, procedure_id, consent_id, headers=None) -> dict:
    return get_success_data(
        api.attach_consent(
            procedure_id, {"consent_record_id": consent_id}, headers or FRONT_DESK
        )
    )


def run_allocation_for(api, procedure_id, expected_version=None) -> list:
    """Read the procedure's live version, then run the FEFO planner against it."""
    version = (
        expected_version if expected_version is not None else procedure_version(api, procedure_id)
    )
    return get_success_data(
        api.run_allocation(procedure_id, {"expected_procedure_version": version}, INVENTORY)
    )


def open_supply_for(api, procedure_id, physician_id) -> dict:
    return get_success_data(
        api.open_supply(procedure_id, make_physician_headers(physician_id))
    )


def perform_for(api, procedure_id, patient_id, physician_id, pellets_wasted=0) -> dict:
    """Read the patient's live version, then implant."""
    return get_success_data(
        api.perform_procedure(
            procedure_id,
            {
                "expected_patient_version": patient_version(api, patient_id),
                "pellets_wasted": pellets_wasted,
            },
            make_physician_headers(physician_id),
        )
    )


def procedure_allocations(api, procedure_id, params=None) -> list:
    return get_success_data(api.list_procedure_allocations(procedure_id, FRONT_DESK, params))


def lot_allocations(api, lot_id, params=None) -> list:
    return get_success_data(api.list_lot_allocations(lot_id, INVENTORY, params))


def patient_notifications(api, patient_id=None, params=None) -> list:
    query = dict(params or {})
    if patient_id is not None:
        query["patient_id"] = patient_id
    query.setdefault("limit", 100)
    return get_success_data(api.list_notifications(FRONT_DESK, query))


def adverse_events(api, params=None) -> list:
    query = dict(params or {})
    query.setdefault("limit", 100)
    return get_success_data(api.list_adverse_events(ADMIN, query))


def procedures_of(api, params=None) -> list:
    query = dict(params or {})
    query.setdefault("limit", 100)
    return get_success_data(api.list_procedures(FRONT_DESK, query))


def new_membership(api, patient_id, tier="PLUS") -> dict:
    return get_success_data(
        api.create_membership({"patient_id": patient_id, "tier": tier}, FRONT_DESK)
    )


def new_series_pack(api, patient_id, series_type="B12") -> dict:
    return get_success_data(
        api.create_series_pack({"patient_id": patient_id, "series_type": series_type}, FRONT_DESK)
    )


def book_injection_visit(
    api, patient_id, provider_id, standing_order_id, injection_type="B12",
    room_code="RM1", scheduled_start="2026-06-01T09:00:00Z",
    series_pack_id=None, membership_id=None, headers=None,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "standing_order_id": standing_order_id,
        "injection_type": injection_type,
        "room_code": room_code,
        "scheduled_start": scheduled_start,
    }
    if series_pack_id is not None:
        payload["series_pack_id"] = series_pack_id
    if membership_id is not None:
        payload["membership_id"] = membership_id
    return get_success_data(api.create_injection_visit(payload, headers or FRONT_DESK))


def administer_visit(api, visit_id, physician_id) -> dict:
    return get_success_data(
        api.administer_injection_visit(visit_id, make_physician_headers(physician_id))
    )


def new_financing_plan(
    api, patient_id, procedure_id, principal_cents=58300, down_payment_cents=11660,
    installment_count=6, first_due_date="2026-08-01T00:00:00Z",
) -> dict:
    return get_success_data(
        api.create_financing_plan(
            {
                "patient_id": patient_id,
                "procedure_id": procedure_id,
                "principal_cents": principal_cents,
                "down_payment_cents": down_payment_cents,
                "installment_count": installment_count,
                "first_due_date": first_due_date,
            },
            FRONT_DESK,
        )
    )


def activate_financing_plan(api, plan_id) -> dict:
    return get_success_data(api.activate_financing_plan(plan_id, FRONT_DESK))


def pay_installment(api, plan_id, installment_index, amount_cents) -> dict:
    return get_success_data(
        api.pay_installment(
            plan_id,
            {"installment_index": installment_index, "amount_cents": amount_cents},
            FRONT_DESK,
        )
    )


def run_delinquency(api) -> dict:
    return get_success_data(api.run_delinquency(FRONT_DESK))


def set_hold(api, patient_id, hold_kind, hold_action, physician_id=None, reason=None) -> dict:
    """A Physician drives the clinical hold; only a ClinicAdmin drives the financial one."""
    payload = {"hold_kind": hold_kind, "hold_action": hold_action}
    if reason is not None:
        payload["reason"] = reason
    if hold_kind == "CLINICAL":
        assert physician_id, "A clinical hold action needs the acting physician's Provider id"
        headers = make_physician_headers(physician_id)
    else:
        headers = ADMIN
    return get_success_data(api.set_eligibility_hold(patient_id, payload, headers))


def file_adverse_event(
    api, patient_id, reported_by_provider_id, severity="MILD",
    narrative="Transient soreness at the insertion site",
    onset_at="2026-05-01T06:00:00Z", **references,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "reported_by_provider_id": reported_by_provider_id,
        "severity": severity,
        "narrative": narrative,
        "onset_at": onset_at,
    }
    payload.update({k: v for k, v in references.items() if v is not None})
    return get_success_data(
        api.create_adverse_event(payload, make_physician_headers(reported_by_provider_id))
    )


def review_adverse_event(api, event_id, physician_id, disposition, note="Reviewed") -> dict:
    return get_success_data(
        api.review_adverse_event(
            event_id,
            {"disposition": disposition, "disposition_note": note},
            make_physician_headers(physician_id),
        )
    )


def recall_lot(api, lot_id, severity_class="CLASS_II", recall_reason="Sterility excursion") -> dict:
    return get_success_data(
        api.recall_pellet_lot(
            lot_id, {"severity_class": severity_class, "recall_reason": recall_reason}, INVENTORY
        )
    )


def recall_impact(api, lot_id, variant, assume_severity=None) -> dict:
    params = {"variant": variant}
    if assume_severity is not None:
        params["assume_severity"] = assume_severity
    return get_success_data(api.get_recall_impact(lot_id, INVENTORY, params))


# ══════════════════════════════════════════════════════════════════════════════
# Tier 1 — the clinic backdrop every clinical scenario needs
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_LOT_SPECS = {
    "TESTOSTERONE": [
        {"lot_code": "T200-A", "strength_mg": 200, "qty_received": 20},
        {"lot_code": "T100-B", "strength_mg": 100, "qty_received": 20},
    ],
    "ESTRADIOL": [
        {"lot_code": "E25-A", "strength_mg": 25, "qty_received": 20},
        {"lot_code": "E10-A", "strength_mg": 10, "qty_received": 20},
    ],
}


def setup_clinic(
    api,
    *,
    hormone_type="TESTOSTERONE",
    patient_name="Pat One",
    patient_email="p1@example.com",
    sex_at_birth="MALE",
    prescribed_dose_mg=1000,
    symptom_score=55,
    consented_max_dose_mg=None,
    publish=True,
    lot_specs=None,
    release_lots=True,
    standing_order_kwargs=None,
) -> dict:
    """One physician, one patient, a published protocol, a signed consent, a
    consult with its pellet plan, a standing order, and released inventory."""
    physician = new_physician(api)
    patient = new_patient(
        api, full_name=patient_name, email=patient_email, sex_at_birth=sex_at_birth
    )
    protocol = publish_protocol(api, physician["id"], hormone_type) if publish else None
    consent = (
        sign_consent(
            api, patient["id"], hormone_type, 1,
            consented_max_dose_mg if consented_max_dose_mg is not None else (
                2000 if hormone_type == "TESTOSTERONE" else 150
            ),
        )
        if publish else None
    )
    consult = record_consult(
        api, patient["id"], physician["id"], hormone_type,
        prescribed_dose_mg=prescribed_dose_mg, symptom_score=symptom_score,
    )
    order = new_standing_order(api, physician["id"], **(standing_order_kwargs or {}))

    lots = {}
    for spec in (lot_specs if lot_specs is not None else DEFAULT_LOT_SPECS[hormone_type]):
        spec = dict(spec)
        code = spec.pop("lot_code")
        maker = receive_and_release_lot if release_lots else receive_lot
        lots[code] = maker(api, code, hormone_type=hormone_type, **spec)

    return {
        "physician": physician,
        "physician_id": physician["id"],
        "patient": patient,
        "patient_id": patient["id"],
        "protocol": protocol,
        "consent": consent,
        "consult": consult,
        "consult_id": consult["id"],
        "standing_order": order,
        "standing_order_id": order["id"],
        "lots": lots,
        "hormone_type": hormone_type,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Tier 2 — walk a procedure to any point on its primary axis
# ══════════════════════════════════════════════════════════════════════════════
def setup_pellet_procedure(
    api,
    *,
    target_status="SCHEDULED",
    hormone_type="TESTOSTERONE",
    prescribed_dose_mg=1000,
    symptom_score=55,
    consented_max_dose_mg=None,
    room_code="RM1",
    scheduled_start="2026-06-01T09:00:00Z",
    perform_at=None,
    pellets_wasted=0,
    membership_tier=None,
    attach_membership=False,
    lot_specs=None,
    release_lots=True,
    patient_name="Pat One",
    patient_email="p1@example.com",
    sex_at_birth="MALE",
    standing_order_kwargs=None,
) -> dict:
    """Build a clinic and drive one procedure to `target_status`.

    target_status is one of SCHEDULED, CONSENTED, SUPPLY_OPENED, COMPLETED.
    `perform_at` moves the logical clock immediately before the insertion.
    """
    assert target_status in ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED", "COMPLETED")
    ctx = setup_clinic(
        api,
        hormone_type=hormone_type,
        patient_name=patient_name,
        patient_email=patient_email,
        sex_at_birth=sex_at_birth,
        prescribed_dose_mg=prescribed_dose_mg,
        symptom_score=symptom_score,
        consented_max_dose_mg=consented_max_dose_mg,
        lot_specs=lot_specs,
        release_lots=release_lots,
        standing_order_kwargs=standing_order_kwargs,
    )

    membership = None
    if membership_tier is not None:
        membership = new_membership(api, ctx["patient_id"], membership_tier)
    ctx["membership"] = membership

    procedure = book_procedure(
        api,
        ctx["patient_id"],
        ctx["physician_id"],
        ctx["consult_id"],
        ctx["standing_order_id"],
        room_code=room_code,
        scheduled_start=scheduled_start,
        membership_id=membership["id"] if (membership and attach_membership) else None,
    )
    ctx["procedure"] = procedure
    ctx["procedure_id"] = procedure["id"]

    if target_status == "SCHEDULED":
        return ctx

    attach_consent_to(api, procedure["id"], ctx["consent"]["id"])
    ctx["allocations"] = run_allocation_for(api, procedure["id"])
    if target_status == "CONSENTED":
        ctx["procedure"] = read_procedure(api, procedure["id"])
        return ctx

    open_supply_for(api, procedure["id"], ctx["physician_id"])
    if target_status == "SUPPLY_OPENED":
        ctx["procedure"] = read_procedure(api, procedure["id"])
        return ctx

    if perform_at is not None:
        set_clock(api, perform_at)
    ctx["procedure"] = perform_for(
        api, procedure["id"], ctx["patient_id"], ctx["physician_id"], pellets_wasted
    )
    return ctx


def setup_consented_procedure(api, **kwargs) -> dict:
    return setup_pellet_procedure(api, target_status="CONSENTED", **kwargs)


def setup_supply_opened_procedure(api, **kwargs) -> dict:
    return setup_pellet_procedure(api, target_status="SUPPLY_OPENED", **kwargs)


def setup_completed_procedure(api, **kwargs) -> dict:
    return setup_pellet_procedure(api, target_status="COMPLETED", **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# Tier 3 — the re-dose scenario: a completed anchor plus a supporting trough
# ══════════════════════════════════════════════════════════════════════════════
def setup_redose_ready(
    api,
    *,
    hormone_type="TESTOSTERONE",
    anchor_performed_at="2026-05-10T09:00:00Z",
    trough_drawn_at="2026-07-25T09:00:00Z",
    trough_value=400,
    trough_analyte=None,
    is_trough_draw=True,
    follow_up_symptom_score=55,
    follow_up_dose_mg=1000,
    anchor_dose_mg=1000,
    room_code="RM1",
    now=None,
    patient_email="p1@example.com",
) -> dict:
    """A patient whose insertion COMPLETED at `anchor_performed_at`, a trough
    panel drawn at `trough_drawn_at`, and a follow-up consult to re-dose from."""
    ctx = setup_pellet_procedure(
        api,
        target_status="COMPLETED",
        hormone_type=hormone_type,
        prescribed_dose_mg=anchor_dose_mg,
        room_code=room_code,
        scheduled_start=anchor_performed_at,
        perform_at=anchor_performed_at,
        patient_email=patient_email,
        standing_order_kwargs={"valid_until": "2026-12-01T00:00:00Z"},
        lot_specs=[
            {"lot_code": "T200-A", "strength_mg": 200, "qty_received": 20},
            {"lot_code": "T100-B", "strength_mg": 100, "qty_received": 20},
        ] if hormone_type == "TESTOSTERONE" else None,
    )
    set_clock(api, trough_drawn_at)
    ctx["trough_panel"] = record_lab_panel(
        api,
        ctx["patient_id"],
        ctx["physician_id"],
        analyte=trough_analyte or ("TOTAL_TESTOSTERONE" if hormone_type == "TESTOSTERONE"
                                   else "ESTRADIOL"),
        value=trough_value,
        drawn_at=trough_drawn_at,
        is_trough_draw=is_trough_draw,
    )
    ctx["follow_up_consult"] = record_consult(
        api,
        ctx["patient_id"],
        ctx["physician_id"],
        hormone_type,
        prescribed_dose_mg=follow_up_dose_mg,
        symptom_score=follow_up_symptom_score,
        indication="Trough below optimal",
    )
    if now is not None:
        set_clock(api, now)
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# Tier 4 — money: an activated installment plan on a booked procedure
# ══════════════════════════════════════════════════════════════════════════════
def setup_active_financing_plan(
    api,
    *,
    principal_cents=58300,
    down_payment_cents=11660,
    installment_count=6,
    first_due_date="2026-06-01T00:00:00Z",
    scheduled_start="2026-08-01T09:00:00Z",
    patient_email="p1@example.com",
    pay_first_installment=None,
) -> dict:
    """A SCHEDULED procedure carrying an ACTIVE plan, optionally with
    installment one already PAID."""
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", scheduled_start=scheduled_start,
        patient_email=patient_email,
    )
    plan = new_financing_plan(
        api, ctx["patient_id"], ctx["procedure_id"],
        principal_cents=principal_cents,
        down_payment_cents=down_payment_cents,
        installment_count=installment_count,
        first_due_date=first_due_date,
    )
    activate_financing_plan(api, plan["id"])
    if pay_first_installment is not None:
        pay_installment(api, plan["id"], 1, pay_first_installment)
    ctx["plan"] = read_financing_plan(api, plan["id"])
    ctx["plan_id"] = plan["id"]
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# Tier 5 — wellness injections, memberships and prepaid series
# ══════════════════════════════════════════════════════════════════════════════
def setup_injection_visit(
    api,
    *,
    injection_type="B12",
    with_series_pack=False,
    series_type=None,
    membership_tier=None,
    room_code="RM1",
    scheduled_start="2026-05-15T09:00:00Z",
    administer_at=None,
    patient_email="p1@example.com",
    patient_name="Pat One",
    standing_order_kwargs=None,
) -> dict:
    """A physician, a patient, an optional pack and membership, and one booked
    wellness-injection visit."""
    physician = new_physician(api)
    patient = new_patient(api, full_name=patient_name, email=patient_email, sex_at_birth="FEMALE")
    order = new_standing_order(api, physician["id"], **(standing_order_kwargs or {}))

    pack = new_series_pack(api, patient["id"], series_type or injection_type) if with_series_pack else None
    membership = new_membership(api, patient["id"], membership_tier) if membership_tier else None

    visit = book_injection_visit(
        api, patient["id"], physician["id"], order["id"],
        injection_type=injection_type, room_code=room_code, scheduled_start=scheduled_start,
        series_pack_id=pack["id"] if pack else None,
        membership_id=membership["id"] if membership else None,
    )
    if administer_at is not None:
        set_clock(api, administer_at)
    return {
        "physician": physician,
        "physician_id": physician["id"],
        "patient": patient,
        "patient_id": patient["id"],
        "standing_order": order,
        "standing_order_id": order["id"],
        "pack": pack,
        "membership": membership,
        "visit": visit,
        "visit_id": visit["id"],
    }


def setup_notified_consent_requirement(api, *, patient_email="p1@example.com") -> dict:
    """A CONSENTED procedure de-consented by a fresh protocol publication, so the
    patient carries exactly one PENDING CONSENT_REQUIRED notification."""
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", scheduled_start="2026-06-11T09:00:00Z",
        patient_email=patient_email,
    )
    attach_consent_to(api, ctx["procedure_id"], ctx["consent"]["id"])
    publish_protocol(api, ctx["physician_id"], "TESTOSTERONE", "T pellet protocol v2")
    notes = patient_notifications(api, ctx["patient_id"])
    assert len(notes) == 1, f"Setup expected exactly one notification, got {len(notes)}"
    ctx["notification"] = notes[0]
    ctx["notification_id"] = notes[0]["id"]
    return ctx


def pellet_plan_for(hormone_type: str, prescribed_dose_mg: float) -> dict:
    """The greedy ladder conversion, for fixture arithmetic only."""
    import math

    large = PELLET_LADDER[hormone_type]["large"]
    small = PELLET_LADDER[hormone_type]["small"]
    large_count = int(prescribed_dose_mg // large)
    remainder = prescribed_dose_mg - large_count * large
    small_count = 0 if remainder == 0 else math.ceil(remainder / small)
    return {
        "planned_large_count": large_count,
        "planned_small_count": small_count,
        "planned_pellet_count": large_count + small_count,
        "planned_total_mg": large_count * large + small_count * small,
    }
