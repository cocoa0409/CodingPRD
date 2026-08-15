"""Composite setup helpers for multi-step test prerequisites.

The server is relaunched before every test, so each helper builds its entire
precondition chain from an empty database using only PRD-declared endpoints.
All setup calls go through get_success_data() so a setup failure surfaces as
a clear "Setup failed" error rather than a confusing assertion failure.

Header threading: AuthorizedUser is entity-backed, so order-creating calls
use make_authorized_user_headers(au["id"]). Segregation-of-duties-sensitive
operations take explicit operator ids (calibrator vs administrator, sealer vs
certifier, reporter vs clearer).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    F18_PARAMS,
    I131_PARAMS,
    T_ADMIN,
    T_APPT_END,
    T_APPT_START,
    T_CLOCK_START,
    T_PREP,
)
from .factories import (
    create_authorized_user_payload,
    create_dose_order_payload,
    create_dose_vial_payload,
    create_imaging_room_payload,
    create_isotope_delivery_payload,
    create_license_payload,
    create_patient_payload,
    create_procedure_appointment_payload,
    create_radiation_survey_payload,
    create_spill_incident_payload,
    create_waste_container_payload,
)
from .test_users import (
    TEST_USERS,
    make_authorized_user_headers,
    make_radiopharmacist_headers,
    make_rso_headers,
    make_technologist_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Instant arithmetic ───────────────────────────────


def parse_instant(iso: str) -> datetime:
    """Parse an ISO-8601 UTC instant into an aware datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def format_instant(dt: datetime) -> str:
    """Render an aware datetime as an ISO-8601 UTC instant string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_iso(iso: str, **kwargs) -> str:
    """Return the instant `iso` shifted by the given timedelta kwargs."""
    return format_instant(parse_instant(iso) + timedelta(**kwargs))


def instants_equal(a: str, b: str) -> bool:
    """Two timestamp strings denote the same instant (format-insensitive)."""
    return parse_instant(a) == parse_instant(b)


# ─── Low-level building blocks ────────────────────────


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_isotope(params: dict = None, **overrides):
    payload = dict(params or F18_PARAMS)
    payload.update(overrides)
    return get_success_data(api_client.create_isotope_product(payload, ADMIN))


def create_license(isotope_product_id: str, **overrides):
    return get_success_data(
        api_client.create_license(create_license_payload(isotope_product_id, **overrides), ADMIN)
    )


def create_authorized_user(license_id: str, **overrides):
    return get_success_data(
        api_client.create_authorized_user(
            create_authorized_user_payload(license_id, **overrides), ADMIN
        )
    )


def create_patient(**overrides):
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(**overrides), TEST_USERS["technologist_headers"]
        )
    )


def create_room(**overrides):
    return get_success_data(
        api_client.create_imaging_room(create_imaging_room_payload(**overrides), ADMIN)
    )


def schedule_delivery(isotope_product_id: str, **overrides):
    return get_success_data(
        api_client.create_isotope_delivery(
            create_isotope_delivery_payload(isotope_product_id, **overrides),
            TEST_USERS["radiopharmacist_headers"],
        )
    )


def receive_delivery(delivery_id: str, measured_activity_mbq: float, **kwargs):
    payload = {"measured_activity_mbq": measured_activity_mbq}
    payload.update(kwargs)
    return get_success_data(
        api_client.receive_isotope_delivery(
            delivery_id, payload, TEST_USERS["radiopharmacist_headers"]
        )
    )


def create_order(patient_id: str, isotope_product_id: str, authorized_user: dict, **overrides):
    return get_success_data(
        api_client.create_dose_order(
            create_dose_order_payload(patient_id, isotope_product_id, **overrides),
            make_authorized_user_headers(authorized_user["id"]),
        )
    )


def prepare_vial(order_id: str, delivery_id: str):
    return get_success_data(
        api_client.create_dose_vial(
            create_dose_vial_payload(order_id, delivery_id),
            TEST_USERS["radiopharmacist_headers"],
        )
    )


def calibrate_vial(vial_id: str, measured_activity_mbq: float, calibrator_id: str = "rp-1"):
    return get_success_data(
        api_client.calibrate_dose_vial(
            vial_id,
            {"measured_activity_mbq": measured_activity_mbq},
            make_radiopharmacist_headers(calibrator_id),
        )
    )


def administer_vial(vial_id: str, administrator_id: str = "tech-2"):
    return get_success_data(
        api_client.administer_dose_vial(vial_id, make_technologist_headers(administrator_id))
    )


def book_appointment(order_id: str, room_id: str, booker_id: str = "tech-1", **overrides):
    return get_success_data(
        api_client.create_procedure_appointment(
            create_procedure_appointment_payload(order_id, room_id, **overrides),
            make_technologist_headers(booker_id),
        )
    )


def create_container(isotope_product_id: str, room_id: str, creator_id: str = "rso-1"):
    return get_success_data(
        api_client.create_waste_container(
            create_waste_container_payload(isotope_product_id, room_id),
            make_rso_headers(creator_id),
        )
    )


def seal_container(container_id: str, sealer_id: str = "rso-1"):
    """Seal a container, reading its current version first (OCC)."""
    current = get_success_data(api_client.get_waste_container(container_id, ADMIN))
    return get_success_data(
        api_client.seal_waste_container(
            container_id,
            {"expected_container_version": current["version"]},
            make_rso_headers(sealer_id),
        )
    )


def record_survey(room_id: str, result: str = "PASS", surveyor_id: str = "rso-1", **overrides):
    return get_success_data(
        api_client.create_radiation_survey(
            create_radiation_survey_payload(room_id, result=result, **overrides),
            make_rso_headers(surveyor_id),
        )
    )


def report_spill(room_id: str, isotope_product_id: str, reporter_headers=None, **overrides):
    headers = reporter_headers or TEST_USERS["technologist_headers"]
    return get_success_data(
        api_client.create_spill_incident(
            create_spill_incident_payload(room_id, isotope_product_id, **overrides), headers
        )
    )


def advance_spill(spill_id: str, to_state: str, officer_id: str = "rso-1"):
    return get_success_data(
        api_client.advance_spill_incident(
            spill_id, {"to_state": to_state}, make_rso_headers(officer_id)
        )
    )


def get_order(order_id: str):
    return get_success_data(api_client.get_dose_order(order_id, ADMIN))


def get_vial(vial_id: str):
    return get_success_data(api_client.get_dose_vial(vial_id, ADMIN))


def get_room(room_id: str):
    return get_success_data(api_client.get_imaging_room(room_id, ADMIN))


def get_license(license_id: str):
    return get_success_data(api_client.get_license(license_id, ADMIN))


def get_appointment(appointment_id: str):
    return get_success_data(api_client.get_procedure_appointment(appointment_id, ADMIN))


def get_container(container_id: str):
    return get_success_data(api_client.get_waste_container(container_id, ADMIN))


# ─── Tier 1/2: canonical department fixtures ──────────


def setup_f18_department(receive=True, with_room=True, **overrides):
    """Clock 08:00; F-18 isotope (HL 110); license; authorized user; patient;
    delivery 5000 MBq @ 08:00 (received unless receive=False); imaging room;
    clock advanced to 08:30. Returns a dict of the created entities."""
    set_clock(T_CLOCK_START)
    iso = create_isotope()
    lic = create_license(iso["id"], **overrides.pop("license_overrides", {}))
    au = create_authorized_user(lic["id"], **overrides.pop("au_overrides", {}))
    pat = create_patient(**overrides.pop("patient_overrides", {}))
    delivery = schedule_delivery(iso["id"], **overrides.pop("delivery_overrides", {}))
    if receive:
        delivery = receive_delivery(delivery["id"], delivery["reference_activity_mbq"])
    room = create_room(**overrides.pop("room_overrides", {})) if with_room else None
    set_clock(T_PREP)
    return {
        "isotope": iso,
        "license": lic,
        "authorized_user": au,
        "patient": pat,
        "delivery": delivery,
        "room": room,
    }


def setup_i131_department():
    """Clock 08:00; I-131 isotope (HL 11568, long-half-life overage tier);
    license; authorized user; patient; delivery 5000 MBq @ 08:00 received;
    clock 08:30."""
    set_clock(T_CLOCK_START)
    iso = create_isotope(I131_PARAMS)
    lic = create_license(iso["id"], license_number="L-200")
    au = create_authorized_user(lic["id"], full_name="Dr. B")
    pat = create_patient(full_name="P Two", weight_kg=80)
    delivery = schedule_delivery(iso["id"])
    delivery = receive_delivery(delivery["id"], delivery["reference_activity_mbq"])
    set_clock(T_PREP)
    return {
        "isotope": iso,
        "license": lic,
        "authorized_user": au,
        "patient": pat,
        "delivery": delivery,
        "room": None,
    }


# ─── Tier 3: order/vial lifecycle shortcuts ───────────


def setup_f18_order(**order_overrides):
    """F-18 department + one ORDERED dose order (100 MBq @ 10:20)."""
    ctx = setup_f18_department()
    ctx["order"] = create_order(
        ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"], **order_overrides
    )
    return ctx


def setup_f18_prepared_order(**order_overrides):
    """F-18 department + order + PREPARED vial (order now DOSE_PREPARED)."""
    ctx = setup_f18_order(**order_overrides)
    ctx["vial"] = prepare_vial(ctx["order"]["id"], ctx["delivery"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_f18_calibrated_vial(
    measured_activity_mbq=220, calibrator_id="rp-1", with_appointment=False, **order_overrides
):
    """F-18 department + order + vial CALIBRATED at 08:30 with the given assay.
    Optionally also books the 10:00-10:30 appointment for the order."""
    ctx = setup_f18_prepared_order(**order_overrides)
    ctx["vial"] = calibrate_vial(ctx["vial"]["id"], measured_activity_mbq, calibrator_id)
    if with_appointment and ctx.get("room"):
        ctx["appointment"] = book_appointment(
            ctx["order"]["id"],
            ctx["room"]["id"],
            start_at=T_APPT_START,
            end_at=T_APPT_END,
        )
    return ctx


def setup_f18_administered(with_appointment=False, administrator_id="tech-2", **kwargs):
    """F-18 department + vial calibrated 220.000 at 08:30; clock at 10:20
    (exactly one half-life later); vial administered. Adds 'administration'."""
    ctx = setup_f18_calibrated_vial(with_appointment=with_appointment, **kwargs)
    set_clock(T_ADMIN)
    ctx["administration"] = administer_vial(ctx["vial"]["id"], administrator_id)
    ctx["order"] = get_order(ctx["order"]["id"])
    ctx["vial"] = get_vial(ctx["vial"]["id"])
    return ctx


def setup_i131_administered(administrator_id="tech-1", **order_overrides):
    """I-131 department + order (THERAPEUTIC 1000 MBq @ 09:00) + vial
    calibrated 1100.000 at 08:30; clock 09:00; vial administered.
    Returns ctx with 'administration'."""
    ctx = setup_i131_department()
    overrides = {"use_type": "THERAPEUTIC", "prescribed_activity_mbq": 1000,
                 "administration_scheduled_at": "2026-08-01T09:00:00Z"}
    overrides.update(order_overrides)
    ctx["order"] = create_order(
        ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"], **overrides
    )
    ctx["vial"] = prepare_vial(ctx["order"]["id"], ctx["delivery"]["id"])
    ctx["vial"] = calibrate_vial(ctx["vial"]["id"], 1100, "rp-1")
    set_clock("2026-08-01T09:00:00Z")
    ctx["administration"] = administer_vial(ctx["vial"]["id"], administrator_id)
    return ctx


# ─── Tier 4: spill-response fixtures ──────────────────


def setup_f18_spill_contamination(occurred_at="2026-08-01T08:45:00Z", reporter_headers=None):
    """F-18 department + calibrated vial + 10:00-10:30 appointment; clock 08:45;
    MINOR spill reported in the room at 08:45. The report cascade has fired:
    room CONTAMINATED, appointment AUTO_VOIDED, order ON_HOLD, vial QUARANTINED."""
    ctx = setup_f18_calibrated_vial(with_appointment=True)
    set_clock("2026-08-01T08:45:00Z")
    ctx["spill"] = report_spill(
        ctx["room"]["id"],
        ctx["isotope"]["id"],
        reporter_headers=reporter_headers or make_technologist_headers("tech-1"),
        occurred_at=occurred_at,
    )
    return ctx


def work_spill_to_decontaminated(spill_id: str, officer_id="rso-1"):
    """Advance a REPORTED spill through CONTAINED to DECONTAMINATED."""
    advance_spill(spill_id, "CONTAINED", officer_id)
    return advance_spill(spill_id, "DECONTAMINATED", officer_id)


def clear_spill(spill_id: str, room_id: str, officer_id="rso-1", surveyor_id="rso-1"):
    """From DECONTAMINATED: record a PASS survey and advance to CLEARED."""
    record_survey(room_id, "PASS", surveyor_id)
    return advance_spill(spill_id, "CLEARED", officer_id)


def setup_spill_room_only(reporter_headers=None, estimated_activity_mbq=10):
    """Isotope + room only; MINOR spill reported at 08:00 (room CONTAMINATED)."""
    set_clock(T_CLOCK_START)
    iso = create_isotope()
    room = create_room(name="Room-9")
    spill = report_spill(
        room["id"],
        iso["id"],
        reporter_headers=reporter_headers or make_radiopharmacist_headers("rp-9"),
        estimated_activity_mbq=estimated_activity_mbq,
        occurred_at="2026-08-01T08:00:00Z",
    )
    return {"isotope": iso, "room": room, "spill": spill}


# ─── Tier 5: waste decay-in-storage fixtures ──────────


def setup_sealed_container_with_decayed_vial():
    """F-18 department + waste container; order prescribed 15 @ 10:20; vial
    calibrated 20.000 at 08:30; clock 10:21 (sweep decays the vial below the
    10 MBq floor -> DECAYED); vial disposed into the container; container
    sealed at 10:21 (intake 9.937; clearable at +10 half-lives)."""
    ctx = setup_f18_department()
    ctx["container"] = create_container(ctx["isotope"]["id"], ctx["room"]["id"])
    ctx["order"] = create_order(
        ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"],
        prescribed_activity_mbq=15,
    )
    ctx["vial"] = prepare_vial(ctx["order"]["id"], ctx["delivery"]["id"])
    ctx["vial"] = calibrate_vial(ctx["vial"]["id"], 20, "rp-1")
    set_clock("2026-08-01T10:21:00Z")
    ctx["vial"] = get_success_data(
        api_client.dispose_dose_vial(
            ctx["vial"]["id"], {"waste_container_id": ctx["container"]["id"]},
            TEST_USERS["radiopharmacist_headers"],
        )
    )
    ctx["container"] = seal_container(ctx["container"]["id"], "rso-1")
    return ctx


def setup_sealed_container_from_administered_vial():
    """F-18 department + waste container; vial calibrated 220.000 at 08:30;
    administered at 10:20 (assay 110.000); disposed at the same instant
    (residual 110.000); container sealed at 10:20 (intake 110.000)."""
    ctx = setup_f18_administered()
    ctx["container"] = create_container(ctx["isotope"]["id"], ctx["room"]["id"])
    ctx["vial"] = get_success_data(
        api_client.dispose_dose_vial(
            ctx["vial"]["id"], {"waste_container_id": ctx["container"]["id"]},
            TEST_USERS["radiopharmacist_headers"],
        )
    )
    ctx["container"] = seal_container(ctx["container"]["id"], "rso-1")
    return ctx
