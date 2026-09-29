"""Composite state builders.

Every test in this suite runs against an empty database, so each one has to build
its own preconditions through the API. The functions here do that once: the
low-level ``create_*`` / ``do_*`` wrappers issue a single request and unwrap the
envelope, and the ``setup_*`` builders chain those wrappers into the composite
states the domain actually has — a synchronized patient, an adjudicated cycle, a
roll on the bench, a verified roll, a dispatched split shipment, a saturated
prescriber chase, an approved travel exception, a quarantined roll, a superseded
regimen ready for reissue.

Builders return a :class:`Scenario`, a mutable record of everything created so
far with refresh helpers that re-read the rows from the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    adjudicate_payload,
    albuterol_payload,
    atorvastatin_payload,
    authorization_response_payload,
    autoship_payload,
    cold_chain_shipment_payload,
    deliver_payload,
    dose_events_payload,
    fill_cycle_payload,
    insulin_payload,
    insurance_plan_payload,
    loose_shipment_payload,
    metformin_payload,
    patient_payload,
    pouch_image_payload,
    pouch_roll_shipment_payload,
    prescription_payload,
    refill_authorization_payload,
    regimen_change_payload,
    reissue_payload,
    rivaroxaban_payload,
    roll_images_payload,
    second_patient_payload,
    shipment_payload,
    sitagliptin_payload,
    synchronize_payload,
    third_patient_payload,
    vacation_decision_payload,
    vacation_exception_payload,
)
from .test_users import (
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    admin_headers,
    ops_headers,
    patient_headers,
    pharmacist_headers,
    prescriber_headers,
    technician_headers,
)

__all__ = [
    "DEFAULT_TEST_CLOCK",
    "Scenario",
    "PrescriptionSpec",
    "set_clock",
    "create_plan",
    "create_patient",
    "create_rx",
    "do_synchronize",
    "create_cycle",
    "do_adjudicate",
    "do_generate_roll",
    "do_pack",
    "do_image_roll",
    "do_image_pouch",
    "do_verify",
    "do_rework",
    "do_stage_shipment",
    "do_dispatch",
    "do_deliver",
    "do_confirm_pickup",
    "do_autoship",
    "do_dose_events",
    "do_adherence_review",
    "open_authorization",
    "do_chase",
    "do_escalate",
    "do_respond",
    "request_vacation",
    "decide_vacation",
    "do_regimen_change",
    "do_reissue",
    "read_cycle",
    "read_patient",
    "read_roll",
    "read_prescription",
    "read_lines",
    "read_pouches",
    "read_memos",
    "read_shipments",
    "read_cycle_events",
    "setup_synced_patient",
    "setup_two_synced_patients",
    "setup_draft_cycle",
    "setup_adjudicated_cycle",
    "setup_rolled_cycle",
    "setup_packed_cycle",
    "setup_imaged_cycle",
    "setup_verified_cycle",
    "setup_split_shipment_cycle",
    "setup_shipped_cycle",
    "setup_delivered_cycle",
    "setup_closed_cycle",
    "setup_quarantined_roll",
    "setup_reworked_roll",
    "setup_held_auth_cycle",
    "setup_chase_at_round",
    "setup_saturated_chase",
    "setup_approved_vacation",
    "setup_regimen_changed_cycle",
    "setup_reissued_cycle",
]

# Every builder pins the clock before it writes anything, so that dispense
# history, cycle windows and chase deadlines are all reproducible.
DEFAULT_TEST_CLOCK = "2026-08-10T00:00:00Z"

JsonDict = Dict[str, Any]

#: A prescription is described either by a builder taking the patient id or by a
#: ready-made payload into which the patient id is injected.
PrescriptionSpec = Union[Callable[[str], JsonDict], JsonDict]


# ----------------------------------------------------------------------
# Scenario record
# ----------------------------------------------------------------------
@dataclass
class Scenario:
    """Everything a builder created, with helpers to re-read it."""

    plan: JsonDict = field(default_factory=dict)
    patient: JsonDict = field(default_factory=dict)
    prescriptions: List[JsonDict] = field(default_factory=list)
    cycle: JsonDict = field(default_factory=dict)
    lines: List[JsonDict] = field(default_factory=list)
    roll: JsonDict = field(default_factory=dict)
    pouches: List[JsonDict] = field(default_factory=list)
    shipments: List[JsonDict] = field(default_factory=list)
    authorization: JsonDict = field(default_factory=dict)
    vacation: JsonDict = field(default_factory=dict)
    successor_rx: JsonDict = field(default_factory=dict)
    successor_cycle: JsonDict = field(default_factory=dict)
    clock: str = DEFAULT_TEST_CLOCK

    # -- identifiers ----------------------------------------------------
    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def roll_id(self) -> str:
        return self.roll["id"]

    @property
    def headers(self) -> Dict[str, str]:
        """Headers for this scenario's own patient."""
        return patient_headers(self.patient_id)

    # -- lookups --------------------------------------------------------
    def rx(self, index: int = 0) -> JsonDict:
        """The prescription created at this position."""
        return self.prescriptions[index]

    def rx_id(self, index: int = 0) -> str:
        return self.prescriptions[index]["id"]

    def rx_named(self, drug_name: str) -> JsonDict:
        """The prescription carrying this drug name."""
        matches = [rx for rx in self.prescriptions if rx["drug_name"] == drug_name]
        assert len(matches) == 1, matches
        return matches[0]

    def line_for(self, prescription_id: str) -> JsonDict:
        """The cycle line referencing this prescription, from the latest read."""
        matches = [ln for ln in self.lines if ln["prescription_id"] == prescription_id]
        assert len(matches) == 1, matches
        return matches[0]

    def shipment_of_kind(self, shipment_kind: str) -> JsonDict:
        matches = [s for s in self.shipments if s["shipment_kind"] == shipment_kind]
        assert len(matches) == 1, matches
        return matches[0]

    # -- refreshes ------------------------------------------------------
    def refresh_patient(self) -> JsonDict:
        self.patient = read_patient(self.patient_id)
        return self.patient

    def refresh_cycle(self) -> JsonDict:
        self.cycle = read_cycle(self.cycle_id)
        return self.cycle

    def refresh_lines(self) -> List[JsonDict]:
        self.lines = read_lines(self.cycle_id)
        return self.lines

    def refresh_roll(self) -> JsonDict:
        self.roll = read_roll(self.roll_id)
        return self.roll

    def refresh_pouches(self) -> List[JsonDict]:
        self.pouches = read_pouches(self.roll_id)
        return self.pouches

    def refresh_prescriptions(self) -> List[JsonDict]:
        self.prescriptions = [read_prescription(rx["id"]) for rx in self.prescriptions]
        return self.prescriptions

    def refresh_shipments(self) -> List[JsonDict]:
        self.shipments = read_shipments(self.cycle_id)
        return self.shipments

    def memos(self) -> List[JsonDict]:
        return read_memos(self.patient_id)

    def refresh_all(self) -> "Scenario":
        self.refresh_patient()
        if self.cycle:
            self.refresh_cycle()
            self.refresh_lines()
            self.refresh_shipments()
        if self.roll:
            self.refresh_roll()
            self.refresh_pouches()
        self.refresh_prescriptions()
        return self


# ----------------------------------------------------------------------
# Single-request wrappers
# ----------------------------------------------------------------------
def set_clock(current_utc: str) -> str:
    """Move the logical clock and return the new instant."""
    response = api_client.set_clock(current_utc)
    return get_success_data(response)["current_utc"]


def create_plan(**overrides: Any) -> JsonDict:
    """Register a payer plan."""
    response = api_client.create_insurance_plan(
        insurance_plan_payload(**overrides), admin_headers()
    )
    return get_success_data(response, expected_status=201)


def create_patient(plan_id: str, which: int = 1, **overrides: Any) -> JsonDict:
    """Enrol one of the three canonical patients against a plan."""
    builder = {1: patient_payload, 2: second_patient_payload, 3: third_patient_payload}[which]
    response = api_client.create_patient(builder(plan_id, **overrides), ops_headers())
    return get_success_data(response, expected_status=201)


def create_rx(patient_id: str, spec: Optional[PrescriptionSpec] = None) -> JsonDict:
    """Record one prescription described by a builder or a ready payload."""
    if spec is None:
        payload = prescription_payload(patient_id)
    elif callable(spec):
        payload = spec(patient_id)
    else:
        payload = dict(spec)
        payload["patient_id"] = patient_id
    response = api_client.create_prescription(payload, ops_headers())
    return get_success_data(response, expected_status=201)


def do_synchronize(
    patient_id: str, anchor_fill_day: int = 15, sync_mode: str = "BRIDGE_TO_START"
) -> JsonDict:
    """Pin the patient's anchor day and alignment policy."""
    response = api_client.synchronize_patient(
        patient_id, synchronize_payload(anchor_fill_day, sync_mode), ops_headers()
    )
    return get_success_data(response)


def create_cycle(
    patient_id: str,
    cycle_start_date: str = "2026-08-15",
    day_supply_days: int = 28,
    **overrides: Any,
) -> JsonDict:
    """Open a fill cycle and stage its planned lines."""
    response = api_client.create_fill_cycle(
        fill_cycle_payload(patient_id, cycle_start_date, day_supply_days, **overrides),
        ops_headers(),
    )
    return get_success_data(response, expected_status=201)


def do_adjudicate(
    cycle_id: str,
    force_pouch_prescription_ids: Optional[List[str]] = None,
    vacation_exception_id: Optional[str] = None,
) -> JsonDict:
    """Run the payer edits over the cycle's planned lines."""
    response = api_client.adjudicate_fill_cycle(
        cycle_id,
        pharmacist_headers(),
        adjudicate_payload(force_pouch_prescription_ids, vacation_exception_id),
    )
    return get_success_data(response)


def do_generate_roll(cycle_id: str, user_id: str = TECHNICIAN_ID) -> JsonDict:
    """Build the dose-time pouch roll for the cycle."""
    response = api_client.generate_roll(cycle_id, technician_headers(user_id))
    return get_success_data(response, expected_status=201)


def do_pack(roll_id: str, user_id: str = TECHNICIAN_ID) -> JsonDict:
    """Claim the roll as packed, pinning the identity barred from verifying it."""
    response = api_client.pack_roll(roll_id, technician_headers(user_id))
    return get_success_data(response)


def do_image_roll(
    roll_id: str,
    image_confidence_pct: int = 97,
    overrides: Optional[List[JsonDict]] = None,
    user_id: str = TECHNICIAN_ID_2,
) -> JsonDict:
    """Run one whole-roll scanner pass, by default as a technician who did not pack."""
    response = api_client.capture_roll_images(
        roll_id,
        roll_images_payload(image_confidence_pct, overrides),
        technician_headers(user_id),
    )
    return get_success_data(response)


def do_image_pouch(
    pouch_id: str,
    detected_pill_count: int,
    image_confidence_pct: int = 97,
    user_id: str = TECHNICIAN_ID_2,
) -> JsonDict:
    """Record one single-pouch verification image."""
    response = api_client.capture_pouch_image(
        pouch_id,
        pouch_image_payload(detected_pill_count, image_confidence_pct),
        technician_headers(user_id),
    )
    return get_success_data(response)


def do_verify(roll_id: str, user_id: str = PHARMACIST_ID) -> JsonDict:
    """Second-person verification of a fully imaged roll."""
    response = api_client.verify_roll(roll_id, pharmacist_headers(user_id))
    return get_success_data(response)


def do_rework(roll_id: str, user_id: str = PHARMACIST_ID) -> JsonDict:
    """Return a quarantined roll to the bench."""
    response = api_client.rework_roll(roll_id, pharmacist_headers(user_id))
    return get_success_data(response)


def do_stage_shipment(cycle_id: str, payload: JsonDict) -> JsonDict:
    """Stage one parcel of the cycle's split shipment."""
    response = api_client.stage_shipment(cycle_id, payload, ops_headers())
    return get_success_data(response, expected_status=201)


def do_dispatch(shipment_id: str) -> JsonDict:
    """Hand the parcel to the carrier."""
    response = api_client.dispatch_shipment(shipment_id, ops_headers())
    return get_success_data(response)


def do_deliver(
    shipment_id: str, cold_chain_excursion_minutes: Optional[int] = None
) -> JsonDict:
    """Record carrier delivery, optionally reporting a temperature excursion."""
    response = api_client.deliver_shipment(
        shipment_id, ops_headers(), deliver_payload(cold_chain_excursion_minutes)
    )
    return get_success_data(response)


def do_confirm_pickup(shipment_id: str, patient_id: str) -> JsonDict:
    """Confirm collection as the owning patient."""
    response = api_client.confirm_pickup(shipment_id, patient_headers(patient_id))
    return get_success_data(response)


def do_autoship(patient_id: str, action: str, as_patient: bool = False) -> JsonDict:
    """Pause, resume or cancel auto-ship."""
    headers = patient_headers(patient_id) if as_patient else ops_headers()
    response = api_client.set_autoship(patient_id, autoship_payload(action), headers)
    return get_success_data(response)


def do_dose_events(
    patient_id: str, cycle_id: str, events: List[JsonDict], as_patient: bool = False
) -> JsonDict:
    """Append a batch of dose events and re-evaluate the pause gate."""
    headers = patient_headers(patient_id) if as_patient else ops_headers()
    response = api_client.report_dose_events(
        patient_id, dose_events_payload(cycle_id, events), headers
    )
    return get_success_data(response, expected_status=201)


def do_adherence_review(patient_id: str) -> JsonDict:
    """Sweep delivered parcels for an expired pickup grace period."""
    response = api_client.run_adherence_review(patient_id, ops_headers())
    return get_success_data(response)


def open_authorization(prescription_id: str, requested_refills: int = 3) -> JsonDict:
    """Open a refill authorization chase against the prescriber."""
    response = api_client.create_refill_authorization(
        refill_authorization_payload(prescription_id, requested_refills), ops_headers()
    )
    return get_success_data(response, expected_status=201)


def do_chase(auth_id: str) -> JsonDict:
    """Record prescriber silence, or re-send, depending on the current state."""
    response = api_client.chase_refill_authorization(auth_id, ops_headers())
    return get_success_data(response)


def do_escalate(auth_id: str) -> JsonDict:
    """Escalate an exhausted chase."""
    response = api_client.escalate_refill_authorization(auth_id, ops_headers())
    return get_success_data(response)


def do_respond(
    auth_id: str,
    decision: str,
    approved_refills: Optional[int] = None,
    denial_reason: Optional[str] = None,
) -> JsonDict:
    """Answer the chase as the prescriber."""
    response = api_client.respond_refill_authorization(
        auth_id,
        authorization_response_payload(decision, approved_refills, denial_reason),
        prescriber_headers(),
    )
    return get_success_data(response)


def request_vacation(patient_id: str, **overrides: Any) -> JsonDict:
    """Request a travel early-supply exception."""
    response = api_client.create_vacation_exception(
        vacation_exception_payload(patient_id, **overrides), ops_headers()
    )
    return get_success_data(response, expected_status=201)


def decide_vacation(
    exception_id: str,
    decision: str,
    approved_extra_days: Optional[int] = None,
    denial_reason: Optional[str] = None,
) -> JsonDict:
    """Decide a travel exception as the pharmacist."""
    response = api_client.decide_vacation_exception(
        exception_id,
        vacation_decision_payload(decision, approved_extra_days, denial_reason),
        pharmacist_headers(),
    )
    return get_success_data(response)


def do_regimen_change(prescription_id: str, expected_version: int, **overrides: Any) -> JsonDict:
    """Supersede a prescription; the response is the successor."""
    response = api_client.regimen_change(
        prescription_id,
        regimen_change_payload(expected_version, **overrides),
        prescriber_headers(),
    )
    return get_success_data(response, expected_status=201)


def do_reissue(
    cycle_id: str,
    effective_date: str,
    replacement_prescription_ids: List[str],
    expected_cycle_version: int,
) -> JsonDict:
    """Reissue the untaken tail; the response is the new partial cycle."""
    response = api_client.reissue_fill_cycle(
        cycle_id,
        reissue_payload(effective_date, replacement_prescription_ids, expected_cycle_version),
        ops_headers(),
    )
    return get_success_data(response, expected_status=201)


# ----------------------------------------------------------------------
# Read wrappers
# ----------------------------------------------------------------------
def read_cycle(cycle_id: str) -> JsonDict:
    return get_success_data(api_client.get_fill_cycle(cycle_id, ops_headers()))


def read_patient(patient_id: str) -> JsonDict:
    return get_success_data(api_client.get_patient(patient_id, ops_headers()))


def read_roll(roll_id: str) -> JsonDict:
    return get_success_data(api_client.get_pouch_roll(roll_id, ops_headers()))


def read_prescription(prescription_id: str) -> JsonDict:
    return get_success_data(api_client.get_prescription(prescription_id, ops_headers()))


def read_lines(cycle_id: str) -> List[JsonDict]:
    """Every line of a cycle, in creation order."""
    rows, _ = validate_paginated(
        api_client.list_cycle_lines(ops_headers(), {"cycle_id": cycle_id, "limit": 100})
    )
    return rows


def read_pouches(roll_id: str) -> List[JsonDict]:
    """Every pouch of a roll, in ascending pouch index."""
    collected: List[JsonDict] = []
    offset = 0
    while True:
        rows, meta = validate_paginated(
            api_client.list_pouches(
                ops_headers(), {"roll_id": roll_id, "limit": 100, "offset": offset}
            )
        )
        collected.extend(rows)
        if not meta["has_more"]:
            break
        offset += len(rows)
    return collected


def read_memos(patient_id: str) -> List[JsonDict]:
    """Every credit memo of a patient, in creation order."""
    rows, _ = validate_paginated(
        api_client.list_credit_memos(ops_headers(), {"patient_id": patient_id, "limit": 100})
    )
    return rows


def read_shipments(cycle_id: str) -> List[JsonDict]:
    """Every parcel of a cycle, in creation order."""
    rows, _ = validate_paginated(
        api_client.list_shipments(ops_headers(), {"cycle_id": cycle_id, "limit": 100})
    )
    return rows


def read_cycle_events(cycle_id: str) -> List[JsonDict]:
    """A cycle's adherence event stream, in occurrence order."""
    rows, _ = validate_paginated(
        api_client.list_cycle_adherence_events(cycle_id, ops_headers(), {"limit": 100})
    )
    return rows


# ----------------------------------------------------------------------
# Tier 1 and 2: entity hierarchy and state progression
# ----------------------------------------------------------------------
def setup_synced_patient(
    *,
    clock: str = DEFAULT_TEST_CLOCK,
    plan_overrides: Optional[JsonDict] = None,
    patient_overrides: Optional[JsonDict] = None,
    prescriptions: Optional[List[PrescriptionSpec]] = None,
    anchor_fill_day: int = 15,
    sync_mode: str = "BRIDGE_TO_START",
    synchronize: bool = True,
) -> Scenario:
    """A payer plan, a patient enrolled against it, prescriptions and a pinned anchor."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    patient = create_patient(plan["id"], **(patient_overrides or {}))
    specs = prescriptions if prescriptions is not None else [metformin_payload]
    created = [create_rx(patient["id"], spec) for spec in specs]
    if synchronize:
        patient = do_synchronize(patient["id"], anchor_fill_day, sync_mode)
        created = [read_prescription(rx["id"]) for rx in created]
    return Scenario(plan=plan, patient=patient, prescriptions=created, clock=clock)


def setup_two_synced_patients(
    *,
    clock: str = DEFAULT_TEST_CLOCK,
    plan_overrides: Optional[JsonDict] = None,
    prescriptions: Optional[List[PrescriptionSpec]] = None,
    anchor_fill_day: int = 15,
    sync_mode: str = "BRIDGE_TO_START",
) -> Dict[str, Scenario]:
    """Two synchronized patients on one shared plan, for cross-boundary probes."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    specs = prescriptions if prescriptions is not None else [metformin_payload]
    scenarios: Dict[str, Scenario] = {}
    for key, which in (("first", 1), ("second", 2)):
        patient = create_patient(plan["id"], which=which)
        created = [create_rx(patient["id"], spec) for spec in specs]
        patient = do_synchronize(patient["id"], anchor_fill_day, sync_mode)
        scenarios[key] = Scenario(
            plan=plan,
            patient=patient,
            prescriptions=[read_prescription(rx["id"]) for rx in created],
            clock=clock,
        )
    return scenarios


def setup_draft_cycle(
    *,
    cycle_start_date: str = "2026-08-15",
    day_supply_days: int = 28,
    cycle_overrides: Optional[JsonDict] = None,
    **patient_kwargs: Any,
) -> Scenario:
    """A patient with one open cycle sitting at ``DRAFT`` and ``NOT_ADJUDICATED``."""
    scenario = setup_synced_patient(**patient_kwargs)
    scenario.cycle = create_cycle(
        scenario.patient_id,
        cycle_start_date,
        day_supply_days,
        **(cycle_overrides or {}),
    )
    scenario.refresh_lines()
    return scenario


def setup_adjudicated_cycle(
    *,
    force_pouch_prescription_ids: Optional[List[str]] = None,
    vacation_exception_id: Optional[str] = None,
    **cycle_kwargs: Any,
) -> Scenario:
    """A cycle whose payer edits have run: ``LINES_ADJUDICATED``."""
    scenario = setup_draft_cycle(**cycle_kwargs)
    scenario.cycle = do_adjudicate(
        scenario.cycle_id, force_pouch_prescription_ids, vacation_exception_id
    )
    scenario.refresh_lines()
    scenario.refresh_prescriptions()
    return scenario


def setup_rolled_cycle(*, packer: str = TECHNICIAN_ID, **kwargs: Any) -> Scenario:
    """A cycle whose pouch roll has been generated: ``ROLL_GENERATED`` and ``BUILT``."""
    scenario = setup_adjudicated_cycle(**kwargs)
    scenario.roll = do_generate_roll(scenario.cycle_id, packer)
    scenario.refresh_cycle()
    scenario.refresh_pouches()
    return scenario


def setup_packed_cycle(*, packer: str = TECHNICIAN_ID, **kwargs: Any) -> Scenario:
    """A roll claimed by ``packer``, which arms the segregation-of-duties control."""
    scenario = setup_rolled_cycle(packer=packer, **kwargs)
    scenario.roll = do_pack(scenario.roll_id, packer)
    scenario.refresh_cycle()
    return scenario


def setup_imaged_cycle(
    *,
    image_confidence_pct: int = 97,
    overrides: Optional[List[JsonDict]] = None,
    imager: str = TECHNICIAN_ID_2,
    **kwargs: Any,
) -> Scenario:
    """A packed roll that has been through one whole-roll scanner pass."""
    scenario = setup_packed_cycle(**kwargs)
    scenario.roll = do_image_roll(
        scenario.roll_id, image_confidence_pct, overrides, imager
    )
    scenario.refresh_pouches()
    return scenario


def setup_verified_cycle(**kwargs: Any) -> Scenario:
    """A fully matching roll signed off by the pharmacist: ``PASSED`` and ``VERIFIED``."""
    scenario = setup_imaged_cycle(**kwargs)
    scenario.roll = do_verify(scenario.roll_id)
    scenario.refresh_cycle()
    return scenario


# ----------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ----------------------------------------------------------------------
def setup_split_shipment_cycle(**kwargs: Any) -> Scenario:
    """A verified cycle carrying all three fulfilment routes, none staged yet.

    The prescription set deliberately spans the three routes: two pouch tablets, a
    refrigerated pen and a non-packable inhaler.
    """
    kwargs.setdefault(
        "prescriptions",
        [metformin_payload, rivaroxaban_payload, insulin_payload, albuterol_payload],
    )
    return setup_verified_cycle(**kwargs)


def setup_shipped_cycle(
    *, shipments: Optional[List[JsonDict]] = None, **kwargs: Any
) -> Scenario:
    """A verified cycle whose parcels are all staged and dispatched: ``SHIPPED``."""
    scenario = setup_verified_cycle(**kwargs)
    payloads = shipments if shipments is not None else [pouch_roll_shipment_payload()]
    for payload in payloads:
        do_stage_shipment(scenario.cycle_id, payload)
    scenario.refresh_shipments()
    for shipment in scenario.shipments:
        do_dispatch(shipment["id"])
    scenario.refresh_shipments()
    scenario.refresh_cycle()
    scenario.refresh_lines()
    return scenario


def setup_delivered_cycle(
    *, cold_chain_excursion_minutes: Optional[int] = None, **kwargs: Any
) -> Scenario:
    """A shipped cycle whose parcels have all been delivered."""
    scenario = setup_shipped_cycle(**kwargs)
    for shipment in scenario.shipments:
        minutes = (
            cold_chain_excursion_minutes
            if shipment["shipment_kind"] == "COLD_CHAIN"
            else None
        )
        do_deliver(shipment["id"], minutes)
    scenario.refresh_shipments()
    scenario.refresh_cycle()
    return scenario


def setup_closed_cycle(**kwargs: Any) -> Scenario:
    """A delivered cycle whose every parcel has been collected: ``CLOSED``."""
    scenario = setup_delivered_cycle(**kwargs)
    for shipment in scenario.shipments:
        if shipment["status"] == "DELIVERED":
            do_confirm_pickup(shipment["id"], scenario.patient_id)
    scenario.refresh_shipments()
    scenario.refresh_cycle()
    scenario.refresh_patient()
    return scenario


# ----------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ----------------------------------------------------------------------
def setup_quarantined_roll(
    *, mismatch_pouch_index: int = 1, **kwargs: Any
) -> Scenario:
    """A roll that failed verification: ``FAILED_QUARANTINED`` with a goodwill memo.

    One pouch is read as empty, so the roll's mismatch count is non-zero when the
    pharmacist signs.
    """
    scenario = setup_imaged_cycle(
        overrides=[{"pouch_index": mismatch_pouch_index, "detected_pill_count": 0}],
        **kwargs,
    )
    scenario.roll = do_verify(scenario.roll_id)
    scenario.refresh_cycle()
    scenario.refresh_patient()
    scenario.refresh_pouches()
    return scenario


def setup_reworked_roll(*, rework_rounds: int = 1, **kwargs: Any) -> Scenario:
    """A roll driven around the failure/rework loop the requested number of times."""
    scenario = setup_quarantined_roll(**kwargs)
    for _ in range(rework_rounds):
        scenario.roll = do_rework(scenario.roll_id)
        # Re-pack, re-image with the same mismatch and re-verify, so the roll is
        # quarantined again at the higher rework count.
        do_pack(scenario.roll_id, TECHNICIAN_ID)
        do_image_roll(
            scenario.roll_id,
            97,
            [{"pouch_index": 1, "detected_pill_count": 0}],
            TECHNICIAN_ID_2,
        )
        scenario.roll = do_verify(scenario.roll_id)
    scenario.refresh_cycle()
    scenario.refresh_patient()
    return scenario


def setup_held_auth_cycle(**kwargs: Any) -> Scenario:
    """A cycle holding a line because its prescription has no refills left.

    The prescription is written with ``refills_authorized`` 0, so adjudication puts
    the line on an authorization hold and moves the prescription to
    ``PENDING_AUTHORIZATION``.
    """
    kwargs.setdefault(
        "prescriptions",
        [
            metformin_payload,
            lambda pid: rivaroxaban_payload(pid, refills_authorized=0),
        ],
    )
    return setup_adjudicated_cycle(**kwargs)


def setup_chase_at_round(
    *, rounds: int = 1, leave_at_no_response: bool = True, **kwargs: Any
) -> Scenario:
    """An open chase driven around the silence loop ``rounds`` times.

    Each silence step needs the clock to have reached ``next_chase_due_at``, so the
    clock advances by 72 hours per round.
    """
    scenario = setup_held_auth_cycle(**kwargs)
    held_rx = scenario.rx_named("Rivaroxaban")
    scenario.authorization = open_authorization(held_rx["id"], 3)
    clock = scenario.clock
    for index in range(rounds):
        clock = _advance_hours(clock, 72 * (index + 1))
        set_clock(clock)
        scenario.authorization = do_chase(scenario.authorization["id"])
        if not (leave_at_no_response and index + 1 == rounds):
            scenario.authorization = do_chase(scenario.authorization["id"])
    scenario.clock = clock
    return scenario


def setup_saturated_chase(**kwargs: Any) -> Scenario:
    """A chase whose ``chase_round`` has reached its ceiling, sitting at ``NO_RESPONSE``."""
    return setup_chase_at_round(rounds=3, leave_at_no_response=True, **kwargs)


def setup_approved_vacation(
    *,
    decision: str = "APPROVE_PHARMACIST",
    approved_extra_days: int = 14,
    requested_extra_days: int = 14,
    travel_start_date: str = "2026-08-20",
    travel_end_date: str = "2026-09-10",
    **kwargs: Any,
) -> Scenario:
    """A synchronized patient holding a decided travel exception."""
    scenario = setup_synced_patient(**kwargs)
    scenario.vacation = request_vacation(
        scenario.patient_id,
        travel_start_date=travel_start_date,
        travel_end_date=travel_end_date,
        requested_extra_days=requested_extra_days,
    )
    scenario.vacation = decide_vacation(
        scenario.vacation["id"], decision, approved_extra_days
    )
    scenario.refresh_patient()
    return scenario


# ----------------------------------------------------------------------
# Tier 5: finalization and terminal states
# ----------------------------------------------------------------------
def setup_regimen_changed_cycle(
    *, changed_drug: str = "Metformin ER", **kwargs: Any
) -> Scenario:
    """A cycle whose roll was unwound by a mid-cycle regimen change.

    The addressed prescription is superseded, its line moves to
    ``SUPERSEDED_PENDING_REISSUE`` and the cycle carries ``reissue_required``.
    """
    scenario = setup_rolled_cycle(**kwargs)
    target = read_prescription(scenario.rx_named(changed_drug)["id"])
    scenario.successor_rx = do_regimen_change(target["id"], target["version"])
    scenario.refresh_cycle()
    scenario.refresh_lines()
    scenario.refresh_prescriptions()
    return scenario


def setup_reissued_cycle(
    *, effective_date: str = "2026-08-25", changed_drug: str = "Metformin ER", **kwargs: Any
) -> Scenario:
    """A regimen-changed cycle whose untaken tail has been reissued as a child cycle."""
    scenario = setup_regimen_changed_cycle(changed_drug=changed_drug, **kwargs)
    scenario.successor_cycle = do_reissue(
        scenario.cycle_id,
        effective_date,
        [scenario.successor_rx["id"]],
        scenario.cycle["version"],
    )
    scenario.refresh_cycle()
    scenario.refresh_lines()
    scenario.refresh_patient()
    return scenario


# ----------------------------------------------------------------------
# Clock arithmetic used by the accumulation builders
# ----------------------------------------------------------------------
def _advance_hours(instant: str, hours: int) -> str:
    """The instant moved forward by whole hours, in the same wire format."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.strptime(instant.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    moved = parsed.astimezone(timezone.utc) + timedelta(hours=hours)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ += ["advance_hours", "advance_days"]


def advance_hours(instant: str, hours: int) -> str:
    """The instant moved forward by whole hours."""
    return _advance_hours(instant, hours)


def advance_days(instant: str, days: int) -> str:
    """The instant moved forward by whole days."""
    return _advance_hours(instant, 24 * days)
