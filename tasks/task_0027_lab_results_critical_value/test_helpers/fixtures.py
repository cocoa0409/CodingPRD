"""Composite setup helpers for the Lab Results & Critical Value benchmark.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.1–§3.9). The runner restarts the API server before every individual
pytest test, so each test starts from an empty database — no entities, no clock
state. These helpers use `get_success_data()` (lenient validator) so a setup
failure surfaces as a clear "Setup failed" trace rather than a cryptic assertion
deep inside a test.

Identity threading (PRD §2.1): the four operator roles are all entity_backed on
Clinician. After creating a Clinician of a given role_type, ownership-gated calls
MUST use `make_<role>_headers(clinician["id"])` — never the shared TEST_USERS
constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    amend_result_payload,
    create_acknowledgement_payload,
    create_clinician_payload,
    create_instrument_payload,
    create_instrument_run_payload,
    create_lab_order_payload,
    create_patient_payload,
    create_result_payload,
    create_specimen_payload,
    reject_specimen_payload,
    release_result_payload,
    set_clock_payload,
)
from .test_users import (
    make_anonymous_headers,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    make_phlebotomist_headers,
)


# Counter used to mint deterministic, unique NPIs / MRNs / instrument codes
# WITHIN a single test (server is restarted before each test, so the counter
# starts from zero per process).
class _SeqAllocator:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


_SEQ = _SeqAllocator()


# ─── Tier 0: clock control (PRD §3.9) ────────────────────────────────────────


def set_clock(iso8601: str, director_id: str) -> dict:
    """POST /_clock/set_current_utc as LabDirector (PRD §3.9)."""
    res = api_client.set_clock(
        set_clock_payload(iso8601), make_lab_director_headers(director_id)
    )
    return get_success_data(res)


# ─── Tier 1: bootstrap (PRD §3.1) ────────────────────────────────────────────


def _next_npi() -> str:
    n = _SEQ.next()
    # 10-digit NPI per PRD §3.1.
    return f"{1000000000 + n:010d}"


def _next_phone() -> str:
    n = _SEQ.next()
    return f"+1202555{n:04d}"


def _next_mrn() -> str:
    n = _SEQ.next()
    # MRN pattern per PRD §3.1: MRN-<6 uppercase alphanumeric>.
    return f"MRN-{n:06X}"


def _next_instrument_code() -> str:
    n = _SEQ.next()
    return f"BCM-{n}"


def register_director(
    full_name: str = "Director Bootstrap",
    phone_e164: str = None,
    npi: str = None,
) -> dict:
    """POST /clinicians as Anonymous (PRD §3.1) — the very first LabDirector.

    PRD §3.1: "Only a LAB_DIRECTOR may register with backup_clinician_id omitted."
    """
    res = api_client.create_clinician(
        create_clinician_payload(
            npi=npi or _next_npi(),
            full_name=full_name,
            role_type="LAB_DIRECTOR",
            phone_e164=phone_e164 or _next_phone(),
        ),
        make_anonymous_headers(),
    )
    return get_success_data(res)


def register_clinician(
    role_type: str,
    director_id: str,
    full_name: str = None,
    npi: str = None,
    phone_e164: str = None,
    backup_clinician_id: str = None,
) -> dict:
    """POST /clinicians as LabDirector (PRD §3.1). Non-director roles require a backup."""
    payload = create_clinician_payload(
        npi=npi or _next_npi(),
        full_name=full_name or f"Clinician {role_type}",
        role_type=role_type,
        phone_e164=phone_e164 or _next_phone(),
        backup_clinician_id=backup_clinician_id or director_id,
    )
    res = api_client.create_clinician(payload, make_lab_director_headers(director_id))
    return get_success_data(res)


def register_lab_tech(director_id: str, **overrides) -> dict:
    return register_clinician("LAB_TECH", director_id, **overrides)


def register_phlebotomist(director_id: str, **overrides) -> dict:
    return register_clinician("PHLEBOTOMIST", director_id, **overrides)


def register_ordering_provider(director_id: str, **overrides) -> dict:
    return register_clinician("ORDERING_PROVIDER", director_id, **overrides)


def register_instrument(
    director_id: str,
    instrument_code: str = None,
    analyte_panels_supported: list = None,
    qc_buffer_minutes: int = 5,
) -> dict:
    """POST /instruments as LabDirector (PRD §3.4)."""
    res = api_client.create_instrument(
        create_instrument_payload(
            instrument_code=instrument_code or _next_instrument_code(),
            analyte_panels_supported=analyte_panels_supported or ["CMP", "CBC", "TROP", "GLUC"],
            qc_buffer_minutes=qc_buffer_minutes,
        ),
        make_lab_director_headers(director_id),
    )
    return get_success_data(res)


def register_patient(
    lt_id: str,
    mrn: str = None,
    full_name: str = "Test Patient",
    date_of_birth: str = "1980-01-01",
) -> dict:
    """POST /patients as LabTech (PRD §3.1)."""
    res = api_client.create_patient(
        create_patient_payload(
            mrn=mrn or _next_mrn(),
            full_name=full_name,
            date_of_birth=date_of_birth,
        ),
        make_lab_tech_headers(lt_id),
    )
    return get_success_data(res)


# ─── Tier 2: actors bundle — director + lt + phleb + op + instrument ─────────


class Actors:
    """Bundle of core clinicians and (optionally) an instrument for a test.

    All fields are populated using the entity-backed-headers convention; tests
    that build ownership-gated calls should use `actors.lt_headers` etc., which
    are pre-bound to the real Clinician.id.
    """

    def __init__(
        self,
        director: dict,
        lt: dict,
        phleb: dict,
        op: dict,
        instrument: dict = None,
    ) -> None:
        self.director = director
        self.lt = lt
        self.phleb = phleb
        self.op = op
        self.instrument = instrument

    @property
    def director_id(self) -> str:
        return self.director["id"]

    @property
    def lt_id(self) -> str:
        return self.lt["id"]

    @property
    def phleb_id(self) -> str:
        return self.phleb["id"]

    @property
    def op_id(self) -> str:
        return self.op["id"]

    @property
    def instrument_id(self) -> str:
        return self.instrument["id"]

    @property
    def director_headers(self) -> dict:
        return make_lab_director_headers(self.director_id)

    @property
    def lt_headers(self) -> dict:
        return make_lab_tech_headers(self.lt_id)

    @property
    def phleb_headers(self) -> dict:
        return make_phlebotomist_headers(self.phleb_id)

    @property
    def op_headers(self) -> dict:
        return make_ordering_provider_headers(self.op_id)


def bootstrap_actors(
    clock: str = "2026-05-28T08:00:00Z",
    with_instrument: bool = True,
    panels: list = None,
    qc_buffer_minutes: int = 5,
) -> Actors:
    """Standard preamble: register director, pin clock, register LT/phleb/OP,
    optionally register an instrument.
    """
    director = register_director()
    set_clock(clock, director["id"])
    lt = register_lab_tech(director["id"])
    phleb = register_phlebotomist(director["id"])
    op = register_ordering_provider(director["id"])
    inst = None
    if with_instrument:
        inst = register_instrument(
            director["id"],
            analyte_panels_supported=panels or ["CMP", "CBC", "TROP", "GLUC"],
            qc_buffer_minutes=qc_buffer_minutes,
        )
    return Actors(director, lt, phleb, op, inst)


# ─── Tier 3: lab-order + specimen progression (PRD §3.2, §3.3) ───────────────


def create_order(
    actors: Actors,
    patient_id: str,
    panel_code: str = "CMP",
    priority: str = "ROUTINE",
) -> dict:
    """POST /patients/{id}/lab-orders as the OrderingProvider (PRD §3.2)."""
    res = api_client.create_lab_order(
        patient_id,
        create_lab_order_payload(actors.op_id, panel_code=panel_code, priority=priority),
        actors.op_headers,
    )
    return get_success_data(res)


def create_specimen(
    actors: Actors,
    lab_order_id: str,
    container_code: str = "GREEN",
    collector_id: str = None,
) -> dict:
    """POST /lab-orders/{id}/specimens as Phlebotomist (PRD §3.3)."""
    collector_id = collector_id or actors.phleb_id
    res = api_client.create_specimen(
        lab_order_id,
        create_specimen_payload(collector_id, container_code=container_code),
        actors.phleb_headers,
    )
    return get_success_data(res)


def collect_specimen(actors: Actors, specimen_id: str) -> dict:
    res = api_client.collect_specimen(specimen_id, actors.phleb_headers)
    return get_success_data(res)


def transit_specimen(actors: Actors, specimen_id: str) -> dict:
    res = api_client.transit_specimen(specimen_id, actors.phleb_headers)
    return get_success_data(res)


def accession_specimen(actors: Actors, specimen_id: str) -> dict:
    res = api_client.accession_specimen(specimen_id, actors.lt_headers)
    return get_success_data(res)


def reject_specimen(
    actors: Actors, specimen_id: str, reason: str = "HEMOLYZED"
) -> dict:
    res = api_client.reject_specimen(
        specimen_id, reject_specimen_payload(reason), actors.lt_headers
    )
    return get_success_data(res)


def walk_specimen_to_accessioned(
    actors: Actors,
    lab_order_id: str,
    container_code: str = "GREEN",
) -> dict:
    """Create → collect → transit → accession a specimen on the given order.

    The order's status will advance DRAFT → ACCESSIONED on the first accession
    (PRD §3.3).
    """
    sp = create_specimen(actors, lab_order_id, container_code=container_code)
    collect_specimen(actors, sp["id"])
    transit_specimen(actors, sp["id"])
    return accession_specimen(actors, sp["id"])


# ─── Tier 4: instrument run + result (PRD §3.4, §3.5) ────────────────────────


def create_instrument_run(
    actors: Actors,
    specimen_id: str,
    scheduled_start: str,
    scheduled_end: str,
    instrument_id: str = None,
) -> dict:
    """POST /instrument-runs as LabTech (PRD §3.4)."""
    res = api_client.create_instrument_run(
        create_instrument_run_payload(
            instrument_id or actors.instrument_id,
            specimen_id,
            scheduled_start,
            scheduled_end,
        ),
        actors.lt_headers,
    )
    return get_success_data(res)


def complete_instrument_run(actors: Actors, run_id: str) -> dict:
    res = api_client.complete_instrument_run(run_id, actors.lt_headers)
    return get_success_data(res)


def create_result(
    actors: Actors,
    lab_order_id: str,
    specimen_id: str,
    run_id: str,
    **overrides,
) -> dict:
    """POST /results as LabTech (PRD §3.5). overrides may include analyte_code,
    numeric_value, unit, reference_low, reference_high, critical_low, critical_high.
    """
    res = api_client.create_result(
        create_result_payload(lab_order_id, specimen_id, run_id, **overrides),
        actors.lt_headers,
    )
    return get_success_data(res)


def get_lab_order(actors: Actors, lab_order_id: str, **params) -> dict:
    res = api_client.get_lab_order(
        lab_order_id, actors.lt_headers, params=params or None
    )
    return get_success_data(res)


def get_lab_order_version(actors: Actors, lab_order_id: str) -> int:
    return get_lab_order(actors, lab_order_id)["version"]


def release_result(
    actors: Actors, result_id: str, expected_lab_order_version: int
) -> dict:
    """POST /results/{id}/release with the supplied OCC parent version (PRD §2.6, §3.5)."""
    res = api_client.release_result(
        result_id,
        release_result_payload(expected_lab_order_version),
        actors.lt_headers,
    )
    return get_success_data(res)


def amend_result(
    actors: Actors,
    result_id: str,
    expected_result_version: int,
    numeric_value: float,
) -> dict:
    res = api_client.amend_result(
        result_id,
        amend_result_payload(expected_result_version, numeric_value),
        actors.lt_headers,
    )
    return get_success_data(res)


def invalidate_result(actors: Actors, result_id: str) -> dict:
    """POST /results/{id}/invalidate as LabDirector (PRD §3.8)."""
    res = api_client.invalidate_result(result_id, actors.director_headers)
    return get_success_data(res)


# ─── Tier 5: full pipeline to a released result (PRD §3.2–§3.5) ──────────────


def setup_released_result(
    actors: Actors,
    patient: dict,
    *,
    panel_code: str = "CMP",
    priority: str = "ROUTINE",
    container_code: str = "GREEN",
    analyte_code: str = "K",
    numeric_value: float = 4.20,
    unit: str = "mmol/L",
    reference_low: float = 3.50,
    reference_high: float = 5.10,
    critical_low: float = 2.50,
    critical_high: float = 6.00,
    run_start: str = "2026-05-28T09:00:00Z",
    run_end: str = "2026-05-28T09:20:00Z",
) -> dict:
    """End-to-end: create order → specimen → walk to ACCESSIONED → create run →
    complete run → create Result → release Result.

    Returns {"order", "specimen", "run", "result"} where every value is a fresh
    dict captured from the corresponding endpoint response.
    """
    order = create_order(actors, patient["id"], panel_code=panel_code, priority=priority)
    sp = create_specimen(actors, order["id"], container_code=container_code)
    collect_specimen(actors, sp["id"])
    transit_specimen(actors, sp["id"])
    accession_specimen(actors, sp["id"])
    run = create_instrument_run(actors, sp["id"], run_start, run_end)
    complete_instrument_run(actors, run["id"])
    result = create_result(
        actors,
        order["id"],
        sp["id"],
        run["id"],
        analyte_code=analyte_code,
        numeric_value=numeric_value,
        unit=unit,
        reference_low=reference_low,
        reference_high=reference_high,
        critical_low=critical_low,
        critical_high=critical_high,
    )
    ord_v = get_lab_order_version(actors, order["id"])
    released = release_result(actors, result["id"], ord_v)
    return {
        "order": order,
        "specimen": sp,
        "run": run,
        "result": released,
    }


def setup_provisional_result(
    actors: Actors,
    patient: dict,
    *,
    panel_code: str = "CMP",
    priority: str = "ROUTINE",
    container_code: str = "GREEN",
    analyte_code: str = "K",
    numeric_value: float = 4.20,
    unit: str = "mmol/L",
    reference_low: float = 3.50,
    reference_high: float = 5.10,
    critical_low: float = 2.50,
    critical_high: float = 6.00,
    run_start: str = "2026-05-28T09:00:00Z",
    run_end: str = "2026-05-28T09:20:00Z",
) -> dict:
    """Same chain as `setup_released_result` but stops at PROVISIONAL Result."""
    order = create_order(actors, patient["id"], panel_code=panel_code, priority=priority)
    sp = create_specimen(actors, order["id"], container_code=container_code)
    collect_specimen(actors, sp["id"])
    transit_specimen(actors, sp["id"])
    accession_specimen(actors, sp["id"])
    run = create_instrument_run(actors, sp["id"], run_start, run_end)
    complete_instrument_run(actors, run["id"])
    result = create_result(
        actors,
        order["id"],
        sp["id"],
        run["id"],
        analyte_code=analyte_code,
        numeric_value=numeric_value,
        unit=unit,
        reference_low=reference_low,
        reference_high=reference_high,
        critical_low=critical_low,
        critical_high=critical_high,
    )
    return {"order": order, "specimen": sp, "run": run, "result": result}


# ─── Tier 6: critical notification helpers (PRD §3.7) ────────────────────────


def get_notification_for_result(actors: Actors, result_id: str) -> dict:
    """GET /critical-notifications?result_id=...; expects exactly one row."""
    res = api_client.list_critical_notifications(
        actors.lt_headers, params={"result_id": result_id}
    )
    data = get_success_data(res)
    assert isinstance(data, list) and len(data) >= 1, (
        f"expected at least one notification for result {result_id}, got {data!r}"
    )
    return data[0]


def send_notification(actors: Actors, notif_id: str) -> dict:
    res = api_client.send_critical_notification(notif_id, actors.lt_headers)
    return get_success_data(res)


def escalate_notification(actors: Actors, notif_id: str) -> dict:
    res = api_client.escalate_critical_notification(notif_id, actors.lt_headers)
    return get_success_data(res)


def setup_sent_critical_notification(
    actors: Actors,
    patient: dict,
    *,
    panel_code: str = "TROP",
    priority: str = "STAT",
    container_code: str = "RED",
    analyte_code: str = "TROPONIN",
    numeric_value: float = 5.00,
    unit: str = "ng/mL",
    reference_low: float = 0.00,
    reference_high: float = 0.04,
    critical_low: float = 0.00,
    critical_high: float = 0.40,
    run_start: str = "2026-05-28T08:30:00Z",
    run_end: str = "2026-05-28T08:40:00Z",
) -> dict:
    """End-to-end: setup released critical Result → look up the auto-created
    PENDING notification → POST /critical-notifications/{id}/send → return SENT
    notification.

    Returns {"order", "specimen", "run", "result", "notification"}.
    """
    bundle = setup_released_result(
        actors,
        patient,
        panel_code=panel_code,
        priority=priority,
        container_code=container_code,
        analyte_code=analyte_code,
        numeric_value=numeric_value,
        unit=unit,
        reference_low=reference_low,
        reference_high=reference_high,
        critical_low=critical_low,
        critical_high=critical_high,
        run_start=run_start,
        run_end=run_end,
    )
    notif = get_notification_for_result(actors, bundle["result"]["id"])
    sent = send_notification(actors, notif["id"])
    bundle["notification"] = sent
    return bundle


def setup_pending_critical_notification(
    actors: Actors,
    patient: dict,
    **overrides,
) -> dict:
    """Same as `setup_sent_critical_notification` but stops at PENDING (no send)."""
    bundle_overrides = {
        "panel_code": overrides.pop("panel_code", "TROP"),
        "priority": overrides.pop("priority", "STAT"),
        "container_code": overrides.pop("container_code", "RED"),
        "analyte_code": overrides.pop("analyte_code", "TROPONIN"),
        "numeric_value": overrides.pop("numeric_value", 5.00),
        "unit": overrides.pop("unit", "ng/mL"),
        "reference_low": overrides.pop("reference_low", 0.00),
        "reference_high": overrides.pop("reference_high", 0.04),
        "critical_low": overrides.pop("critical_low", 0.00),
        "critical_high": overrides.pop("critical_high", 0.40),
        "run_start": overrides.pop("run_start", "2026-05-28T08:30:00Z"),
        "run_end": overrides.pop("run_end", "2026-05-28T08:40:00Z"),
    }
    bundle = setup_released_result(actors, patient, **bundle_overrides)
    notif = get_notification_for_result(actors, bundle["result"]["id"])
    bundle["notification"] = notif
    return bundle


def acknowledge_notification(
    actors: Actors,
    notif_id: str,
    *,
    recipient_id: str,
    ack_method: str = "WEB_UI",
    attestation_text: str = "Reviewed and acknowledged.",
) -> dict:
    """POST /critical-notifications/{id}/acknowledgements as the OrderingProvider
    bound to the notification's recipient_clinician_id.

    PRD §3.7 / §2.1: X-User-ID MUST equal Notification.recipient_clinician_id
    (entity-backed ownership).
    """
    res = api_client.create_acknowledgement(
        notif_id,
        create_acknowledgement_payload(ack_method=ack_method, attestation_text=attestation_text),
        make_ordering_provider_headers(recipient_id),
    )
    return get_success_data(res)
