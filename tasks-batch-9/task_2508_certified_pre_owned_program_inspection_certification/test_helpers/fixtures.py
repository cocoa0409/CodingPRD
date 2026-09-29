"""Composite setup helpers and pytest fixtures.

The service has one long spine: a dealer enrols technicians, an administrator
publishes a checklist, a vehicle is registered, the dealer opens an inspection,
the inspection's own technician records a full attempt, the dealer closes it,
the dealer submits a certification with its documentation, and the
administrator approves it — at which point the fee is priced and the coverage
window is fixed. Almost every rule in the PRD is reachable only from somewhere
along that spine, so the helpers here are written as small steps plus a handful
of composites that walk the whole thing.

Three cross-test hazards are handled deliberately:

* **The logical clock is global.** It reads `2026-08-01T00:00:00Z` before any
  request moves it, so `epoch_clock` puts it back there before every test.
* **Publishing a template retires other published templates** whose
  `effective_from` is on or before the new one's. Every helper therefore mints a
  fresh template per test and publishes it immediately before it is used.
* **A technician's slot conflict test spans every dealer and every past
  inspection** of that technician. Every helper therefore mints fresh
  technicians per test, and `spaced_start` hands out start instants four hours
  apart so a chain of inspections by one technician never self-conflicts.
"""

import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .api_client import api_client
from .assertions import iso_shift
from .constants import CLOCK_EPOCH
from .test_users import (
    ADMIN,
    ADVOCATE,
    AUDITOR,
    make_dealer_principal_headers,
    make_inspection_technician_headers,
)

_SEQUENCE = itertools.count(1)

#: Inspection start instants four hours apart, all at or before the epoch clock.
SLOT_BASE = "2026-07-25T00:00:00Z"


def next_sequence() -> int:
    """A process-wide counter for values the PRD requires to be unique."""
    return next(_SEQUENCE)


def unique_franchise_code() -> str:
    return f"FR-{next_sequence():05d}"


def unique_template_code() -> str:
    return f"MPI-{next_sequence():05d}"


def unique_credential_id() -> str:
    return f"CR-{next_sequence():05d}"


def unique_vin() -> str:
    return factories.vin_for(next_sequence())


#: The `effective_from` the first template minted inside a test is dated to.
TEMPLATE_DATE_BASE = "2026-01-01"

_template_mints = itertools.count(0)


def reset_template_dates() -> None:
    """Restart the per-test `effective_from` ladder."""
    global _template_mints
    _template_mints = itertools.count(0)


def next_effective_from() -> str:
    """Hand out an `effective_from` one day earlier than the previous mint's.

    §3.1 retires a published template only when its `effective_from` is on or
    before the newly published template's, so a strictly *decreasing* ladder
    lets several independently published templates coexist inside one test.
    That is what a test needing two dealerships — each bootstrapping its own
    catalogue — requires: without it, the second dealership's publication
    silently retires the first's and every inspection against it is refused
    with `ERR_TEMPLATE_NOT_PUBLISHED`.
    """
    shifted = date.fromisoformat(TEMPLATE_DATE_BASE) - timedelta(
        days=next(_template_mints)
    )
    return shifted.isoformat()


def spaced_start(index: int = 0) -> str:
    """A start instant that cannot collide with any other spaced slot.

    A 120-minute slot buffered by 30 minutes at each end spans three hours, so
    four-hour spacing leaves the buffered intervals strictly disjoint.
    """
    return iso_shift(SLOT_BASE, hours=4 * index)


# ───────────────────────────── logical clock ─────────────────────────────

def set_clock(api, current_utc: str, headers: Optional[dict] = None) -> str:
    """Move the logical clock and return the `current_utc` now in force."""
    response = api.set_clock(
        factories.set_clock_payload(current_utc), headers or ADMIN
    )
    return validate_success(response)["current_utc"]


# ───────────────────────── programme configuration ──────────────────────

def read_config(api, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_program_config(headers or ADMIN))


def retune_config(api, headers: Optional[dict] = None, **tunables) -> dict:
    """Publish a new configuration generation carrying only the named tunables."""
    return validate_success(
        api.update_program_config(
            factories.program_config_payload(**tunables), headers or ADMIN
        )
    )


# ──────────────────────────────── dealers ───────────────────────────────

def create_dealer(api, headers: Optional[dict] = None, **overrides) -> dict:
    overrides.setdefault("franchise_code", unique_franchise_code())
    return get_success_data(
        api.create_dealer(factories.create_dealer_payload(**overrides), headers or ADMIN),
        expected_status=201,
    )


def read_dealer(api, dealer_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_dealer(dealer_id, headers or ADMIN))


def set_privilege(
    api,
    dealer_id: str,
    privilege_status: str,
    privilege_reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return validate_success(
        api.update_dealer_privilege(
            dealer_id,
            factories.privilege_payload(privilege_status, privilege_reason),
            headers or ADMIN,
        )
    )


# ────────────────────────────── technicians ─────────────────────────────

def create_technician(api, dealer_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    overrides.setdefault("credential_id", unique_credential_id())
    return get_success_data(
        api.create_technician(
            dealer_id, factories.create_technician_payload(**overrides), headers or ADMIN
        ),
        expected_status=201,
    )


# ────────────────────────── checklist catalogue ─────────────────────────

def create_template(api, headers: Optional[dict] = None, **overrides) -> dict:
    overrides.setdefault("code", unique_template_code())
    overrides.setdefault("effective_from", next_effective_from())
    return get_success_data(
        api.create_checklist_template(
            factories.create_template_payload(**overrides), headers or ADMIN
        ),
        expected_status=201,
    )


def add_item(api, template_id: str, payload: dict, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.add_checklist_item(template_id, payload, headers or ADMIN),
        expected_status=201,
    )


def publish_template(api, template_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.publish_checklist_template(template_id, headers or ADMIN))


def canonical_items() -> List[dict]:
    """The three-point checklist the composites use.

    `P1` is CRITICAL and uncurable, so a failure there ends the inspection;
    `S1` is CRITICAL but repairable; `B1` is a measured MAJOR point. The
    template satisfies publication's demand for at least one point and at least
    one CRITICAL point.
    """
    return [
        factories.item_p1_payload(),
        factories.item_s1_payload(),
        factories.item_b1_payload(),
    ]


def create_published_template(
    api,
    items: Optional[List[dict]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Author a template, add its points, publish it, and return the published row."""
    template = create_template(api, headers=headers, **overrides)
    for item in canonical_items() if items is None else items:
        add_item(api, template["id"], item, headers=headers)
    return publish_template(api, template["id"], headers=headers)


def create_draft_template(
    api,
    items: Optional[List[dict]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Author a template with its points but leave it in `DRAFT`."""
    template = create_template(api, headers=headers, **overrides)
    for item in canonical_items() if items is None else items:
        add_item(api, template["id"], item, headers=headers)
    return validate_success(api.get_checklist_template(template["id"], headers or ADMIN))


# ──────────────────────────────── vehicles ──────────────────────────────

def create_vehicle(api, headers: Optional[dict] = None, **overrides) -> dict:
    overrides.setdefault("vin", unique_vin())
    return get_success_data(
        api.create_vehicle(factories.create_vehicle_payload(**overrides), headers or ADMIN),
        expected_status=201,
    )


def read_vehicle(api, vehicle_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_vehicle(vehicle_id, headers or ADMIN))


def vehicle_version(api, vehicle_id: str, headers: Optional[dict] = None) -> int:
    """Read the vehicle's current `version`, which a submission must echo."""
    return read_vehicle(api, vehicle_id, headers)["version"]


def record_history_event(
    api, vehicle_id: str, event_type: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return validate_success(
        api.create_history_event(
            vehicle_id,
            factories.history_event_payload(event_type, **overrides),
            headers or ADMIN,
        )
    )


# ─────────────────────────────── inspections ────────────────────────────

def open_inspection(
    api,
    dealer_headers: dict,
    vehicle_id: str,
    technician_id: str,
    template_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_inspection(
            factories.create_inspection_payload(
                vehicle_id, technician_id, template_id, **overrides
            ),
            dealer_headers,
        ),
        expected_status=201,
    )


def record_results(api, inspection_id: str, technician_headers: dict, rows: List[dict]) -> dict:
    return validate_success(
        api.record_results(
            inspection_id, factories.results_payload(rows), technician_headers
        )
    )


def submit_inspection(api, inspection_id: str, dealer_headers: dict) -> dict:
    """Close the current attempt. The operation takes no request body at all."""
    return validate_success(api.submit_inspection(inspection_id, dealer_headers))


def read_inspection(api, inspection_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_inspection(inspection_id, headers or ADMIN))


def reconditioning_items(api, inspection_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    """The repair listing is the only channel through which repair ids are discovered."""
    response = api.list_reconditioning_items(
        inspection_id, headers or ADMIN, params=params or None
    )
    return validate_success(response)


def reconditioning_item_for(
    api, inspection_id: str, item_code: str, headers: Optional[dict] = None
) -> dict:
    rows = reconditioning_items(api, inspection_id, headers)
    matches = [row for row in rows if row["item_code"] == item_code]
    assert matches, f"no reconditioning item was generated for {item_code}"
    return matches[0]


def complete_reconditioning(
    api, item_id: str, actual_cost_cents: int, technician_headers: dict
) -> dict:
    """`COMPLETED` is the technician-exclusive resolution and carries a cost."""
    return validate_success(
        api.complete_reconditioning_item(
            item_id,
            factories.complete_reconditioning_payload(actual_cost_cents),
            technician_headers,
        )
    )


def waive_reconditioning(
    api, item_id: str, waiver_reason: str = "goodwill", headers: Optional[dict] = None
) -> dict:
    """`WAIVED` is the administrator-exclusive resolution and carries a reason."""
    return validate_success(
        api.complete_reconditioning_item(
            item_id,
            factories.waive_reconditioning_payload(waiver_reason),
            headers or ADMIN,
        )
    )


# ────────────────────────────── certifications ──────────────────────────

def submit_certification(
    api,
    dealer_headers: dict,
    vehicle_id: str,
    inspection_id: str,
    expected_vehicle_version: Optional[int] = None,
    documents: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    if expected_vehicle_version is None:
        expected_vehicle_version = vehicle_version(api, vehicle_id, dealer_headers)
    return get_success_data(
        api.create_certification(
            factories.create_certification_payload(
                vehicle_id,
                inspection_id,
                expected_vehicle_version,
                documents=documents,
                **overrides,
            ),
            dealer_headers,
        ),
        expected_status=201,
    )


def read_certification(api, certification_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_certification(certification_id, headers or ADMIN))


def certification_documents(
    api, certification_id: str, headers: Optional[dict] = None, **params
) -> List[dict]:
    return validate_success(
        api.list_certification_documents(
            certification_id, headers or ADMIN, params=params or None
        )
    )


def approve_certification(api, certification_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(
        api.adjudicate_certification(
            certification_id, factories.adjudication_payload("APPROVE"), headers or ADMIN
        )
    )


def reject_certification(
    api,
    certification_id: str,
    rejection_reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return validate_success(
        api.adjudicate_certification(
            certification_id,
            factories.adjudication_payload("REJECT", rejection_reason),
            headers or ADMIN,
        )
    )


def decertify(
    api,
    certification_id: str,
    decertification_reason: str = "ADMIN_ACTION",
    headers: Optional[dict] = None,
) -> dict:
    return validate_success(
        api.decertify_certification(
            certification_id,
            factories.decertify_payload(decertification_reason),
            headers or ADMIN,
        )
    )


# ──────────────────────────────── listings ──────────────────────────────

def create_listing(api, dealer_headers: dict, certification_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_listing(
            factories.create_listing_payload(certification_id, **overrides), dealer_headers
        ),
        expected_status=201,
    )


def syndicate_listing(
    api,
    listing_id: str,
    dealer_headers: dict,
    expected_certification_version: int,
) -> dict:
    return validate_success(
        api.syndicate_listing(
            listing_id,
            factories.syndicate_payload(expected_certification_version),
            dealer_headers,
        )
    )


def listings_of(api, certification_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return validate_success(
        api.list_listings(certification_id, headers or ADMIN, params=params or None)
    )


# ───────────────────────────── warranty claims ──────────────────────────

def file_claim(api, dealer_headers: dict, certification_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_warranty_claim(
            factories.create_claim_payload(certification_id, **overrides), dealer_headers
        ),
        expected_status=201,
    )


def approve_claim(api, claim_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(
        api.adjudicate_warranty_claim(
            claim_id, factories.claim_adjudication_payload("APPROVE"), headers or ADMIN
        )
    )


def deny_claim(
    api,
    claim_id: str,
    denial_reason: str = "INSUFFICIENT_EVIDENCE",
    headers: Optional[dict] = None,
) -> dict:
    return validate_success(
        api.adjudicate_warranty_claim(
            claim_id,
            factories.claim_adjudication_payload("DENY", denial_reason),
            headers or ADMIN,
        )
    )


def claims_of(api, certification_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return validate_success(
        api.list_warranty_claims(certification_id, headers or ADMIN, params=params or None)
    )


# ─────────────────────────────── complaints ─────────────────────────────

def file_complaint(api, certification_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_complaint(
            factories.create_complaint_payload(certification_id, **overrides),
            headers or ADVOCATE,
        ),
        expected_status=201,
    )


def read_complaint(api, complaint_id: str, headers: Optional[dict] = None) -> dict:
    return validate_success(api.get_complaint(complaint_id, headers or ADVOCATE))


def complaints_of(api, certification_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return validate_success(
        api.list_complaints(certification_id, headers or ADMIN, params=params or None)
    )


# ────────────────────────────── audit sampling ──────────────────────────

def draw_audit_run(api, headers: Optional[dict] = None) -> dict:
    """An audit run returns a summary object and always answers 201 Created."""
    return get_success_data(
        api.create_audit_run(headers or AUDITOR), expected_status=201
    )


def audit_samples_of(api, certification_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return validate_success(
        api.list_audit_samples(certification_id, headers or AUDITOR, params=params or None)
    )


def record_finding(
    api,
    sample_id: str,
    finding: str,
    finding_code: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return validate_success(
        api.record_audit_finding(
            sample_id,
            factories.audit_finding_payload(finding, finding_code),
            headers or AUDITOR,
        )
    )


def sample_certification(api, certification_id: str, headers: Optional[dict] = None) -> dict:
    """Draw runs until this certification is sampled, then return its sample row."""
    for _ in range(40):
        run = draw_audit_run(api, headers)
        if certification_id in run["selected_certification_ids"]:
            samples = audit_samples_of(api, certification_id, headers)
            assert samples, "a selected certification must expose its audit sample"
            return samples[-1]
        if run["pool_size"] == 0:
            break
    raise AssertionError(
        f"certification {certification_id} was never drawn by an audit run"
    )


# ───────────────────────── composite programme setup ────────────────────

@dataclass
class Program:
    """A dealer with two technicians and a published checklist to inspect against."""

    dealer: dict
    dealer_headers: dict
    technician: dict
    technician_headers: dict
    other_technician: dict
    other_technician_headers: dict
    template: dict
    slot_index: int = 0

    @property
    def dealer_id(self) -> str:
        return self.dealer["id"]

    @property
    def technician_id(self) -> str:
        return self.technician["id"]

    @property
    def other_technician_id(self) -> str:
        return self.other_technician["id"]

    @property
    def template_id(self) -> str:
        return self.template["id"]

    def next_start(self) -> str:
        """Hand out the next non-conflicting start instant for this programme."""
        start = spaced_start(self.slot_index)
        self.slot_index += 1
        return start


@dataclass
class Certified:
    """One walk of the spine, from vehicle registration to a live certification."""

    program: Program
    vehicle: dict
    inspection: dict
    certification: Optional[dict] = None
    listings: List[dict] = field(default_factory=list)

    @property
    def vehicle_id(self) -> str:
        return self.vehicle["id"]

    @property
    def inspection_id(self) -> str:
        return self.inspection["id"]

    @property
    def certification_id(self) -> str:
        return self.certification["id"]

    @property
    def dealer_headers(self) -> dict:
        return self.program.dealer_headers


def bootstrap_program(api, items: Optional[List[dict]] = None, **dealer_overrides) -> Program:
    """Enrol a dealer, register two technicians under it, and publish a checklist."""
    dealer = create_dealer(api, **dealer_overrides)
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    technician = create_technician(api, dealer["id"], name="Ada Tech")
    other = create_technician(api, dealer["id"], name="Ben Tech")
    template = create_published_template(api, items=items)
    return Program(
        dealer=dealer,
        dealer_headers=dealer_headers,
        technician=technician,
        technician_headers=make_inspection_technician_headers(technician["id"]),
        other_technician=other,
        other_technician_headers=make_inspection_technician_headers(other["id"]),
        template=template,
    )


def open_inspection_for(
    api,
    program: Program,
    vehicle: Optional[dict] = None,
    technician_id: Optional[str] = None,
    started_at: Optional[str] = None,
    **overrides,
) -> Certified:
    """Register a vehicle if needed and open an inspection on it."""
    if vehicle is None:
        vehicle = create_vehicle(api)
    inspection = open_inspection(
        api,
        program.dealer_headers,
        vehicle["id"],
        technician_id or program.technician_id,
        program.template_id,
        started_at=started_at or program.next_start(),
        **overrides,
    )
    return Certified(program=program, vehicle=vehicle, inspection=inspection)


def pass_inspection(
    api,
    program: Program,
    walk: Certified,
    rows: Optional[List[dict]] = None,
    technician_headers: Optional[dict] = None,
) -> Certified:
    """Record one clean whole-checklist attempt and close the inspection as `PASSED`."""
    record_results(
        api,
        walk.inspection_id,
        technician_headers or program.technician_headers,
        factories.clean_attempt_rows() if rows is None else rows,
    )
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    return walk


def passed_inspection(
    api,
    program: Program,
    vehicle: Optional[dict] = None,
    started_at: Optional[str] = None,
    technician_id: Optional[str] = None,
    **overrides,
) -> Certified:
    """Open an inspection and drive it all the way to `PASSED`."""
    walk = open_inspection_for(
        api,
        program,
        vehicle=vehicle,
        technician_id=technician_id,
        started_at=started_at,
        **overrides,
    )
    technician_headers = (
        program.technician_headers
        if technician_id in (None, program.technician_id)
        else make_inspection_technician_headers(technician_id)
    )
    return pass_inspection(api, program, walk, technician_headers=technician_headers)


def submitted_certification(
    api,
    program: Program,
    vehicle: Optional[dict] = None,
    documents: Optional[List[dict]] = None,
    **overrides,
) -> Certified:
    """Walk to `PASSED` and submit the certification, leaving it `SUBMITTED`."""
    walk = passed_inspection(api, program, vehicle=vehicle, **overrides)
    walk.certification = submit_certification(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        walk.inspection_id,
        documents=documents,
    )
    return walk


def active_certification(
    api,
    program: Program,
    vehicle: Optional[dict] = None,
    documents: Optional[List[dict]] = None,
    **overrides,
) -> Certified:
    """Walk the whole spine and approve, producing a live `ACTIVE` certification."""
    walk = submitted_certification(
        api, program, vehicle=vehicle, documents=documents, **overrides
    )
    walk.certification = approve_certification(api, walk.certification["id"])
    walk.vehicle = read_vehicle(api, walk.vehicle_id)
    return walk


def activate_many(api, program: Program, count: int) -> List[Certified]:
    """Drive `count` independent cars to `ACTIVE` under one dealer.

    Each car gets its own vehicle and its own four-hour-spaced slot, so the
    technician's calendar never self-conflicts.
    """
    return [active_certification(api, program) for _ in range(count)]


def syndicated_listing(api, walk: Certified, **overrides) -> dict:
    """Draft a listing on a live certification and publish it to its channel."""
    listing = create_listing(api, walk.dealer_headers, walk.certification_id, **overrides)
    certification = read_certification(api, walk.certification_id)
    listing = syndicate_listing(
        api, listing["id"], walk.dealer_headers, certification["version"]
    )
    walk.listings.append(listing)
    walk.certification = read_certification(api, walk.certification_id)
    return listing


# ──────────────────────────── pytest fixtures ───────────────────────────

@pytest.fixture(scope="session")
def api():
    """The API client, mounted on the `/cpo` service root."""
    return api_client


@pytest.fixture(autouse=True)
def epoch_clock(api):
    """Put the logical clock back to the instant it reads before any request moves it."""
    reset_template_dates()
    set_clock(api, CLOCK_EPOCH)
    return CLOCK_EPOCH


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def auditor_headers():
    return AUDITOR


@pytest.fixture
def advocate_headers():
    return ADVOCATE


@pytest.fixture
def program(api):
    """A dealer, two technicians, and a freshly published checklist template."""
    return bootstrap_program(api)


@pytest.fixture
def peer_program(api):
    """A second, unrelated dealership, for cross-dealer scope checks."""
    return bootstrap_program(api, name=factories.DEFAULTS["PEER_DEALER_NAME"])


@pytest.fixture
def vehicle(api):
    """A registered, eligible vehicle sitting in dealer inventory."""
    return create_vehicle(api)


@pytest.fixture
def open_walk(api, program):
    """A vehicle with an inspection opened against it, still in `DRAFT`."""
    return open_inspection_for(api, program)


@pytest.fixture
def passed_walk(api, program):
    """A vehicle whose inspection has reached `PASSED`."""
    return passed_inspection(api, program)


@pytest.fixture
def submitted_walk(api, program):
    """A `SUBMITTED` certification awaiting adjudication."""
    return submitted_certification(api, program)


@pytest.fixture
def active_walk(api, program):
    """A live `ACTIVE` certification with its fee priced and coverage fixed."""
    return active_certification(api, program)
