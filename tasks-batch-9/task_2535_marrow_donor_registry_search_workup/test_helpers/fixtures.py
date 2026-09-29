"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch through the PRD's own endpoints and uses the lenient
`get_success_data` validator so a broken precondition reports "Setup failed"
rather than a confusing assertion deep inside a test.

The helpers share one mutable *context* dictionary so that a test can walk the
programme's pipeline one stage at a time:

    ctx = setup_primary_candidate()
    advance_to_screening_passed(ctx)
    ctx = setup_pipeline("delivered")           # or jump straight to a stage

Context keys, once the corresponding stage has run:

    registry, registry_id, liaison_headers
    center, center_id, center_ops_headers
    donor, donor_id, donors (list), candidates (list)
    patient, patient_id, patient_version
    search, search_id
    candidate, candidate_id
    typing_request, typing_request_id
    workup_case, workup_case_id, workup_case_version
    clearance (dict keyed by item_type), claim, claim_id
    booking, booking_id
    shipment, shipment_id
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TIMELINE
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_liaison_headers,
    make_center_ops_headers,
    COORDINATOR_USER_ID,
    PHYSICIAN_USER_ID,
    SECOND_PHYSICIAN_USER_ID,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
SECOND_PHYSICIAN = TEST_USERS["second_physician_headers"]
OPERATIONS = TEST_USERS["operations_headers"]

# Ages that keep the preliminary score identical (all inside the 26..35 age
# bonus band) while separating the ranking score, so a materialised pool's rank
# order follows the order donors are created in.
DONOR_POOL_AGES = [27, 30, 32, 33, 35]

PIPELINE_STAGES = [
    "primary_candidate",
    "typing_requested",
    "typing_responded",
    "screening_passed",
    "workup_open",
    "cleared",
    "method_set",
    "conditioning_scheduled",
    "booking_held",
    "booking_confirmed",
    "conditioning_started",
    "collected",
    "in_transit",
    "delivered",
]


# ---------------------------------------------------------------------------
# Tier 0 — single-resource builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical UTC clock. Returns {current_utc, previous_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, OPERATIONS))


def create_registry(**overrides) -> dict:
    """Register a domestic registry (the national home registry by default)."""
    payload = f.create_registry_payload(**overrides)
    return get_success_data(api_client.create_registry(payload, OPERATIONS))


def create_international_registry(**overrides) -> dict:
    """Register an international partner registry."""
    payload = f.create_international_registry_payload(**overrides)
    return get_success_data(api_client.create_registry(payload, OPERATIONS))


def create_collection_center(**overrides) -> dict:
    payload = f.create_collection_center_payload(**overrides)
    return get_success_data(api_client.create_collection_center(payload, OPERATIONS))


def create_donor(registry_id, **overrides) -> dict:
    """Register a donor under `registry_id`, acting as that registry's liaison."""
    payload = f.create_donor_payload(registry_id, **overrides)
    return get_success_data(
        api_client.create_donor(payload, make_liaison_headers(registry_id))
    )


def create_patient(headers=None, **overrides) -> dict:
    payload = f.create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(payload, headers or COORDINATOR))


def open_search(patient_id, headers=None, **overrides) -> dict:
    payload = f.create_search_request_payload(patient_id, **overrides)
    return get_success_data(
        api_client.create_search_request(payload, headers or COORDINATOR)
    )


def list_candidates(search_id, headers=None, **params) -> list:
    params = dict(params)
    params["search_request_id"] = search_id
    params.setdefault("limit", 100)
    resp = api_client.list_match_candidates(headers or COORDINATOR, params=params)
    return get_success_data(resp)


def read_patient(patient_id, headers=None) -> dict:
    return get_success_data(api_client.get_patient(patient_id, headers or COORDINATOR))


def read_workup_case(workup_case_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_workup_case(workup_case_id, headers or COORDINATOR)
    )


def read_donor(donor_id, headers=None) -> dict:
    return get_success_data(api_client.get_donor(donor_id, headers or OPERATIONS))


def read_center(center_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_collection_center(center_id, headers or OPERATIONS)
    )


def read_candidate(candidate_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_match_candidate(candidate_id, headers or COORDINATOR)
    )


def read_search(search_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_search_request(search_id, headers or COORDINATOR)
    )


def read_booking(booking_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_collection_booking(booking_id, headers or OPERATIONS)
    )


def read_shipment(shipment_id, headers=None) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, headers or OPERATIONS))


def read_claim(claim_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_reimbursement_claim(claim_id, headers or OPERATIONS)
    )


def find_claim_for_case(workup_case_id) -> dict:
    """The reimbursement claim the workup open created for this case."""
    data = get_success_data(
        api_client.list_reimbursement_claims(
            OPERATIONS, params={"workup_case_id": workup_case_id, "limit": 100}
        )
    )
    assert data, f"Setup failed: no claim exists for workup case {workup_case_id}"
    return data[0]


def find_clearance_items(workup_case_id, headers=None) -> dict:
    """The case's three clearance items, keyed by `item_type` and in creation order."""
    data = get_success_data(
        api_client.list_clearance_items(workup_case_id, headers or PHYSICIAN)
    )
    assert len(data) == 3, (
        f"Setup failed: expected three clearance items, got {len(data)}"
    )
    return {"ordered": data, **{item["item_type"]: item for item in data}}


def find_windows(donor_id, headers=None, **params) -> list:
    params = dict(params)
    params.setdefault("limit", 100)
    return get_success_data(
        api_client.list_unavailability_windows(
            donor_id, headers or OPERATIONS, params=params
        )
    )


def find_booking_windows(booking_id, headers=None) -> list:
    return get_success_data(
        api_client.list_booking_unavailability_windows(
            booking_id, headers or OPERATIONS, params={"limit": 100}
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — the programme's standing infrastructure and a scored donor pool
# ---------------------------------------------------------------------------

def setup_programme(*, with_center=True, center_capacity=1,
                    registry_overrides=None, center_overrides=None) -> dict:
    """A domestic registry (and optionally one collection centre).

    Returns a context carrying `registry`, `registry_id`, `liaison_headers`
    and — when `with_center` — `center`, `center_id`, `center_ops_headers`.
    """
    registry = create_registry(**(registry_overrides or {}))
    ctx = {
        "registry": registry,
        "registry_id": registry["id"],
        "liaison_headers": make_liaison_headers(registry["id"]),
        "coordinator_headers": COORDINATOR,
        "physician_headers": PHYSICIAN,
        "second_physician_headers": SECOND_PHYSICIAN,
        "operations_headers": OPERATIONS,
        "donors": [],
    }
    if with_center:
        center = create_collection_center(**(center_overrides or {}))
        ctx["center"] = center
        ctx["center_id"] = center["id"]
        ctx["center_ops_headers"] = make_center_ops_headers(center["id"])
    return ctx


def add_donor(ctx, **overrides) -> dict:
    """Register one more donor under the context's registry."""
    registry_id = overrides.pop("registry_id", ctx["registry_id"])
    donor = create_donor(registry_id, **overrides)
    ctx.setdefault("donors", []).append(donor)
    ctx["donor"] = donor
    ctx["donor_id"] = donor["id"]
    return donor


def setup_donor_pool(ctx, num_donors=1, donor_overrides=None) -> list:
    """Register `num_donors` donors whose ranking scores strictly descend.

    Donor *i* takes `DONOR_POOL_AGES[i]`, so the materialised pool's
    `rank_position` follows the creation order.  `donor_overrides` may be a
    single dict applied to every donor or a list of per-donor dicts.
    """
    assert num_donors <= len(DONOR_POOL_AGES), (
        f"setup_donor_pool supports at most {len(DONOR_POOL_AGES)} rank-ordered donors"
    )
    donors = []
    for index in range(num_donors):
        if isinstance(donor_overrides, list):
            extra = dict(donor_overrides[index]) if index < len(donor_overrides) else {}
        else:
            extra = dict(donor_overrides or {})
        extra.setdefault("age_years", DONOR_POOL_AGES[index])
        donors.append(add_donor(ctx, **extra))
    ctx["donors"] = donors
    ctx["donor"] = donors[0]
    ctx["donor_id"] = donors[0]["id"]
    return donors


def setup_primary_candidate(*, num_donors=1, donor_overrides=None,
                            patient_overrides=None, search_overrides=None,
                            registry_overrides=None, center_overrides=None,
                            with_center=True, coordinator_headers=None) -> dict:
    """Registry (+ centre) + `num_donors` donors + patient + open search.

    The search materialises the pool, so on return the context carries
    `candidates` in rank order, plus `candidate` / `candidate_id` for the
    rank-1 PRIMARY.
    """
    ctx = setup_programme(
        with_center=with_center,
        registry_overrides=registry_overrides,
        center_overrides=center_overrides,
    )
    setup_donor_pool(ctx, num_donors=num_donors, donor_overrides=donor_overrides)

    headers = coordinator_headers or COORDINATOR
    patient = create_patient(headers=headers, **(patient_overrides or {}))
    ctx["patient"] = patient
    ctx["patient_id"] = patient["id"]
    ctx["patient_version"] = patient["version"]
    ctx["coordinator_headers"] = headers

    search = open_search(patient["id"], headers=headers, **(search_overrides or {}))
    ctx["search"] = search
    ctx["search_id"] = search["id"]

    candidates = list_candidates(search["id"], headers=headers)
    ctx["candidates"] = candidates
    if candidates:
        ctx["candidate"] = candidates[0]
        ctx["candidate_id"] = candidates[0]["id"]
    return ctx


def candidate_by_rank(ctx, rank_position) -> dict:
    """The context's materialised candidate holding `rank_position`."""
    for candidate in ctx["candidates"]:
        if candidate["rank_position"] == rank_position:
            return candidate
    raise AssertionError(
        f"Setup failed: no candidate at rank_position {rank_position} in "
        f"{[c['rank_position'] for c in ctx['candidates']]}"
    )


def refresh_candidates(ctx) -> list:
    """Re-read the search's candidates in `rank_position` order."""
    ctx["candidates"] = list_candidates(ctx["search_id"], headers=ctx["coordinator_headers"])
    return ctx["candidates"]


# ---------------------------------------------------------------------------
# Tier 2 — confirmatory typing and health screening
# ---------------------------------------------------------------------------

def advance_to_typing_requested(ctx, candidate_id=None, **payload_overrides) -> dict:
    """Raise the confirmatory-typing request for the context's primary candidate."""
    candidate_id = candidate_id or ctx["candidate_id"]
    payload = f.create_typing_request_payload(**payload_overrides)
    request = get_success_data(
        api_client.create_typing_request(
            candidate_id, payload, ctx["coordinator_headers"]
        )
    )
    ctx["typing_request"] = request
    ctx["typing_request_id"] = request["id"]
    return request


def advance_to_typing_responded(ctx, typing_request_id=None, liaison_headers=None,
                                **payload_overrides) -> dict:
    """Answer the open typing request with allele-level typing and availability."""
    typing_request_id = typing_request_id or ctx["typing_request_id"]
    payload = f.typing_response_payload(**payload_overrides)
    request = get_success_data(
        api_client.respond_typing_request(
            typing_request_id, payload, liaison_headers or ctx["liaison_headers"]
        )
    )
    ctx["typing_request"] = request
    return request


def advance_to_screening_passed(ctx, candidate_id=None, liaison_headers=None,
                                **payload_overrides) -> dict:
    """Record the donor health screening outcome (a clean PASS by default)."""
    candidate_id = candidate_id or ctx["candidate_id"]
    payload = f.screening_payload(**payload_overrides)
    candidate = get_success_data(
        api_client.record_screening(
            candidate_id, payload, liaison_headers or ctx["liaison_headers"]
        )
    )
    ctx["candidate"] = candidate
    return candidate


def engage_candidate(ctx, candidate_id=None, liaison_headers=None) -> dict:
    """Type, confirm and screen one candidate all the way to SCREENING_PASSED."""
    candidate_id = candidate_id or ctx["candidate_id"]
    advance_to_typing_requested(ctx, candidate_id)
    advance_to_typing_responded(ctx, liaison_headers=liaison_headers)
    return advance_to_screening_passed(
        ctx, candidate_id, liaison_headers=liaison_headers
    )


def sweep(ctx, search_id=None) -> dict:
    """Run the operations deadline sweep over the context's search."""
    search_id = search_id or ctx["search_id"]
    search = get_success_data(api_client.run_deadline_sweep(search_id, OPERATIONS))
    ctx["search"] = search
    return search


# ---------------------------------------------------------------------------
# Tier 3 — the workup case, its clearance ladder and the method decision
# ---------------------------------------------------------------------------

def advance_to_workup_open(ctx, candidate_id=None) -> dict:
    """Open the donor workup, which also writes three clearance items and a claim."""
    candidate_id = candidate_id or ctx["candidate_id"]
    case = get_success_data(
        api_client.open_workup_case(candidate_id, ctx["coordinator_headers"])
    )
    ctx["workup_case"] = case
    ctx["workup_case_id"] = case["id"]
    ctx["workup_case_version"] = case["version"]
    ctx["clearance"] = find_clearance_items(case["id"], ctx["physician_headers"])
    ctx["claim"] = find_claim_for_case(case["id"])
    ctx["claim_id"] = ctx["claim"]["id"]
    return case


def result_clearance_item(ctx, item_type, result="PASS", headers=None, **overrides) -> dict:
    """Record one clearance item's result, refreshing the cached case afterwards."""
    item = ctx["clearance"][item_type]
    payload = f.clearance_result_payload(result=result, **overrides)
    resulted = get_success_data(
        api_client.record_clearance_result(
            item["id"], payload, headers or ctx["physician_headers"]
        )
    )
    ctx["clearance"][item_type] = resulted
    ctx["workup_case"] = read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    ctx["workup_case_version"] = ctx["workup_case"]["version"]
    return resulted


def advance_to_cleared(ctx, clearance_at=None, headers=None) -> dict:
    """Pass all three clearance items in their pinned order.

    The clock is moved to `TIMELINE["CLEARANCE_AT"]` first so the IDM panel's
    thirty-day validity covers the canonical collection date.
    """
    set_clock(clearance_at or TIMELINE["CLEARANCE_AT"])
    headers = headers or ctx["physician_headers"]
    for item_type in ("PHYSICAL_EXAM", "IDM_PANEL", "CONSENT"):
        result_clearance_item(ctx, item_type, "PASS", headers)
    return ctx["workup_case"]


def advance_to_method_set(ctx, method="PBSC", headers=None, **overrides) -> dict:
    """Authorise the collection method through a *second* physician.

    `physical_cleared_by_user_id` holds the clearing physician, so the default
    acting identity here is the second physician.
    """
    payload = f.collection_method_payload(method=method, **overrides)
    case = get_success_data(
        api_client.decide_collection_method(
            ctx["workup_case_id"], payload, headers or ctx["second_physician_headers"]
        )
    )
    ctx["workup_case"] = case
    ctx["workup_case_version"] = case["version"]
    ctx["method"] = case["collection_method"]
    return case


# ---------------------------------------------------------------------------
# Tier 4 — the conditioning timeline, the booking and the harvest
# ---------------------------------------------------------------------------

def drive_conditioning(ctx, action, headers=None, expected_patient_version=None,
                       **overrides) -> dict:
    """Drive one conditioning action, quoting the patient's current version."""
    if expected_patient_version is None:
        expected_patient_version = read_patient(
            ctx["patient_id"], ctx["coordinator_headers"]
        )["version"]
    payload = f.conditioning_payload(action, expected_patient_version, **overrides)
    patient = get_success_data(
        api_client.drive_conditioning(
            ctx["patient_id"], payload, headers or ctx["coordinator_headers"]
        )
    )
    ctx["patient"] = patient
    ctx["patient_version"] = patient["version"]
    return patient


def advance_to_conditioning_scheduled(ctx, conditioning_start_date=None, **overrides) -> dict:
    """Schedule conditioning, which opens the legal collection window."""
    return drive_conditioning(
        ctx,
        "SCHEDULE",
        conditioning_start_date=conditioning_start_date
        or TIMELINE["CONDITIONING_START_DATE"],
        **overrides,
    )


def advance_to_booking_held(ctx, start_at=None, center_id=None, center_ops_headers=None,
                            **overrides) -> dict:
    """Hold a collection slot at the centre, acting as that centre's operator."""
    center_id = center_id or ctx["center_id"]
    ctx["workup_case"] = read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    ctx["workup_case_version"] = ctx["workup_case"]["version"]
    payload = f.create_booking_payload(
        ctx["workup_case_id"],
        center_id,
        start_at or TIMELINE["BOOKING_START_AT"],
        ctx["workup_case_version"],
        **overrides,
    )
    booking = get_success_data(
        api_client.create_collection_booking(
            payload, center_ops_headers or make_center_ops_headers(center_id)
        )
    )
    ctx["booking"] = booking
    ctx["booking_id"] = booking["id"]
    return booking


def advance_to_booking_confirmed(ctx, booking_id=None, center_ops_headers=None) -> dict:
    """Confirm the held slot, which blocks the donor's collection-window calendar."""
    booking_id = booking_id or ctx["booking_id"]
    center_id = ctx["booking"]["collection_center_id"]
    booking = get_success_data(
        api_client.confirm_collection_booking(
            booking_id, center_ops_headers or make_center_ops_headers(center_id)
        )
    )
    ctx["booking"] = booking
    return booking


def advance_to_conditioning_started(ctx, started_at=None, **overrides) -> dict:
    """Move the clock onto the conditioning start date and start the regimen."""
    set_clock(started_at or TIMELINE["CONDITIONING_START_AT"])
    return drive_conditioning(ctx, "START", **overrides)


def advance_to_collected(ctx, collected_at=None, center_ops_headers=None,
                         **overrides) -> dict:
    """Record the harvested product against the confirmed booking."""
    set_clock(collected_at or TIMELINE["COLLECTED_AT"])
    center_id = ctx["booking"]["collection_center_id"]
    payload = f.create_shipment_payload(**overrides)
    shipment = get_success_data(
        api_client.create_shipment(
            ctx["booking_id"],
            payload,
            center_ops_headers or make_center_ops_headers(center_id),
        )
    )
    ctx["shipment"] = shipment
    ctx["shipment_id"] = shipment["id"]
    return shipment


def file_shipment_event(ctx, event_type, headers=None, **overrides) -> dict:
    """File one courier chain-of-custody event against the context's shipment."""
    payload = f.shipment_event_payload(event_type, **overrides)
    shipment = get_success_data(
        api_client.create_shipment_event(
            ctx["shipment_id"], payload, headers or OPERATIONS
        )
    )
    ctx["shipment"] = shipment
    return shipment


def advance_shipment_departed(ctx, **overrides) -> dict:
    return file_shipment_event(ctx, "DEPARTED", **overrides)


def advance_shipment_delivered(ctx, delivered_at=None, **overrides) -> dict:
    """Move the clock inside the viability allowance and deliver the product."""
    set_clock(delivered_at or TIMELINE["DELIVERY_AT"])
    return file_shipment_event(ctx, "DELIVERED", **overrides)


# ---------------------------------------------------------------------------
# Tier 5 — calendar, follow-up, cancellation and claim closure helpers
# ---------------------------------------------------------------------------

def block_calendar(ctx, date_from, date_to, reason="PERSONAL", donor_id=None,
                   liaison_headers=None, **overrides) -> dict:
    """Block a donor's calendar by hand over a closed inclusive date range."""
    donor_id = donor_id or ctx["donor_id"]
    payload = f.create_unavailability_window_payload(
        date_from, date_to, reason, **overrides
    )
    window = get_success_data(
        api_client.create_unavailability_window(
            donor_id, payload, liaison_headers or ctx["liaison_headers"]
        )
    )
    ctx["window"] = window
    ctx["window_id"] = window["id"]
    return window


def file_follow_up(ctx, event_type="DAY_7_CONTACT", severity_grade=0, donor_id=None,
                   headers=None, **overrides) -> dict:
    """File one follow-up or adverse-event row against a donor."""
    donor_id = donor_id or ctx["donor_id"]
    payload = f.create_follow_up_payload(event_type, severity_grade, **overrides)
    row = get_success_data(
        api_client.create_follow_up(
            donor_id, payload, headers or ctx["liaison_headers"]
        )
    )
    ctx["follow_up"] = row
    return row


def cancel_booking(ctx, booking_id=None, headers=None, **overrides) -> dict:
    """Cancel the context's booking (as the collection centre by default)."""
    booking_id = booking_id or ctx["booking_id"]
    center_id = ctx["booking"]["collection_center_id"]
    payload = f.cancel_booking_payload(**overrides)
    booking = get_success_data(
        api_client.cancel_collection_booking(
            booking_id, payload, headers or make_center_ops_headers(center_id)
        )
    )
    ctx["booking"] = booking
    return booking


def finalize_claim(ctx, claim_id=None) -> dict:
    """Recompute the case's claim with the FINAL variant and close it."""
    claim_id = claim_id or ctx["claim_id"]
    claim = get_success_data(
        api_client.finalize_reimbursement_claim(claim_id, OPERATIONS)
    )
    ctx["claim"] = claim
    return claim


def refresh(ctx) -> dict:
    """Re-read every entity the context currently tracks."""
    if "patient_id" in ctx:
        ctx["patient"] = read_patient(ctx["patient_id"], ctx["coordinator_headers"])
        ctx["patient_version"] = ctx["patient"]["version"]
    if "search_id" in ctx:
        ctx["search"] = read_search(ctx["search_id"], ctx["coordinator_headers"])
    if "candidate_id" in ctx:
        ctx["candidate"] = read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    if "workup_case_id" in ctx:
        ctx["workup_case"] = read_workup_case(
            ctx["workup_case_id"], ctx["coordinator_headers"]
        )
        ctx["workup_case_version"] = ctx["workup_case"]["version"]
        ctx["clearance"] = find_clearance_items(
            ctx["workup_case_id"], ctx["physician_headers"]
        )
    if "booking_id" in ctx:
        ctx["booking"] = read_booking(ctx["booking_id"])
    if "shipment_id" in ctx:
        ctx["shipment"] = read_shipment(ctx["shipment_id"])
    if "claim_id" in ctx:
        ctx["claim"] = read_claim(ctx["claim_id"])
    if "donor_id" in ctx:
        ctx["donor"] = read_donor(ctx["donor_id"])
    if "center_id" in ctx:
        ctx["center"] = read_center(ctx["center_id"])
    return ctx


# ---------------------------------------------------------------------------
# The one-shot pipeline driver
# ---------------------------------------------------------------------------

def setup_pipeline(stage="primary_candidate", *, method="PBSC", **options) -> dict:
    """Build the programme all the way to `stage` and return the context.

    `stage` must be one of `PIPELINE_STAGES`; every earlier stage runs first, in
    the only order the PRD's preconditions allow — clearance before the method
    decision, the method decision before conditioning is scheduled, the schedule
    before a slot can be held, a confirmed slot before conditioning may start,
    and a started regimen before any product may be taken.
    """
    assert stage in PIPELINE_STAGES, (
        f"unknown pipeline stage {stage!r}; expected one of {PIPELINE_STAGES}"
    )
    target = PIPELINE_STAGES.index(stage)

    def reached(name):
        return target >= PIPELINE_STAGES.index(name)

    ctx = setup_primary_candidate(**options)
    ctx["method"] = method
    if reached("typing_requested"):
        advance_to_typing_requested(ctx)
    if reached("typing_responded"):
        advance_to_typing_responded(ctx)
    if reached("screening_passed"):
        advance_to_screening_passed(ctx)
    if reached("workup_open"):
        advance_to_workup_open(ctx)
    if reached("cleared"):
        advance_to_cleared(ctx)
    if reached("method_set"):
        advance_to_method_set(ctx, method=method)
    if reached("conditioning_scheduled"):
        advance_to_conditioning_scheduled(ctx)
    if reached("booking_held"):
        advance_to_booking_held(ctx)
    if reached("booking_confirmed"):
        advance_to_booking_confirmed(ctx)
    if reached("conditioning_started"):
        advance_to_conditioning_started(ctx)
    if reached("collected"):
        advance_to_collected(ctx)
    if reached("in_transit"):
        advance_shipment_departed(ctx)
    if reached("delivered"):
        advance_shipment_delivered(ctx)
    return ctx
