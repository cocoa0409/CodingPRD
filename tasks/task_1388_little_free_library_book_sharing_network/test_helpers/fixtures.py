"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh database
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error rather than a
confusing assertion failure deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_batch_payload,
    create_book_items,
    create_box_payload,
    create_complaint_payload,
    create_drive_payload,
    create_inspection_payload,
    create_maintenance_request_payload,
    create_resolve_payload,
    create_school_payload,
    create_steward_payload,
    create_training_completion_payload,
    create_training_module_payload,
    create_triage_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_school_liaison_headers,
    make_steward_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
MOD1 = TEST_USERS["mod1_headers"]
MOD2 = TEST_USERS["mod2_headers"]
HUB = TEST_USERS["hub_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and catalog primitives
# ---------------------------------------------------------------------------

def pin_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Pin the logical clock (server default is 2026-08-01T00:00:00Z)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep(headers=ADMIN):
    return get_success_data(api_client.run_map_sweep(headers))


def ensure_module(code: str, title: str = None, level: int = 1,
                  prerequisite_module_id: str = None):
    """Return the module with the given code, creating it if absent.

    Module codes are unique, so scenario builders that run several times in
    one test (e.g. multi-steward setups) must reuse the existing module.
    """
    data, _meta = validate_paginated(
        api_client.list_training_modules(ADMIN, params={"limit": 100})
    )
    for module in data:
        if module["code"] == code:
            return module
    payload = create_training_module_payload(
        code=code, title=title or code.title(), level=level
    )
    if prerequisite_module_id is not None:
        payload["prerequisite_module_id"] = prerequisite_module_id
    return get_success_data(api_client.create_training_module(payload, ADMIN))


def ensure_orientation_module():
    return ensure_module("ORIENTATION", "Orientation", 1)


# ---------------------------------------------------------------------------
# Tier 1: steward state progression
# ---------------------------------------------------------------------------

def register_steward(full_name: str = "Test Steward", email: str = None,
                     region_code: str = "OR"):
    """Register a steward (status APPLIED) as an anonymous applicant."""
    payload = create_steward_payload(
        full_name=full_name,
        email=email or unique_email("steward"),
        region_code=region_code,
    )
    return get_success_data(api_client.create_steward(payload, ANON))


def record_completion(steward_id: str, module_id: str, score: int = 90):
    """Record a module completion as the steward themself (self-service)."""
    return get_success_data(
        api_client.create_training_completion(
            steward_id,
            create_training_completion_payload(module_id, score),
            make_steward_headers(steward_id),
        )
    )


def create_active_steward(full_name: str = "Test Steward", email: str = None,
                          region_code: str = "OR",
                          orientation_score: int = 90):
    """Steward registered, ORIENTATION passed, activated by NetworkAdmin."""
    module = ensure_orientation_module()
    steward = register_steward(full_name=full_name, email=email,
                               region_code=region_code)
    record_completion(steward["id"], module["id"], score=orientation_score)
    return get_success_data(api_client.activate_steward(steward["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: box state progression
# ---------------------------------------------------------------------------

def create_draft_box(steward, name: str = "Test Box", capacity_books: int = 10,
                     region_code: str = None, latitude: float = 45.52,
                     longitude: float = -122.68):
    """Create a DRAFT/UNLISTED box owned by the given steward (self create)."""
    payload = create_box_payload(
        steward["id"],
        name=name,
        capacity_books=capacity_books,
        region_code=region_code or steward["region_code"],
        latitude=latitude,
        longitude=longitude,
    )
    return get_success_data(
        api_client.create_box(payload, make_steward_headers(steward["id"]))
    )


def charter_box(box_id: str):
    return get_success_data(
        api_client.transition_box_status(box_id, "CHARTERED", ADMIN)
    )


def inspect_box(box_id: str, result: str = "CONFIRMED", headers=MOD1, notes=None):
    payload = create_inspection_payload(result)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_inspection(box_id, payload, headers))


def create_chartered_box(steward, **box_kwargs):
    """DRAFT box moved to CHARTERED by NetworkAdmin."""
    box = create_draft_box(steward, **box_kwargs)
    return charter_box(box["id"])


def create_active_box(steward, **box_kwargs):
    """Box walked DRAFT -> CHARTERED -> ACTIVE (CONFIRMED inspection first)."""
    box = create_chartered_box(steward, **box_kwargs)
    inspect_box(box["id"], "CONFIRMED")
    return get_success_data(
        api_client.transition_box_status(box["id"], "ACTIVE", ADMIN)
    )


def create_steward_with_active_box(steward_name: str = "Test Steward",
                                   region_code: str = "OR",
                                   capacity_books: int = 10,
                                   box_name: str = "Test Box"):
    """Most common setup: an ACTIVE steward plus their ACTIVE/LISTED box."""
    steward = create_active_steward(full_name=steward_name,
                                    region_code=region_code)
    box = create_active_box(steward, name=box_name,
                            capacity_books=capacity_books,
                            region_code=region_code)
    return steward, box


# ---------------------------------------------------------------------------
# Tier 2: maintenance pipeline
# ---------------------------------------------------------------------------

def report_maintenance(box_id: str, category: str = "WEAR",
                       description: str = "Routine wear observed"):
    return get_success_data(
        api_client.create_maintenance_request(
            create_maintenance_request_payload(
                box_id, category=category, description=description
            ),
            ANON,
        )
    )


def triage_maintenance(request_id: str, severity: str = "LOW",
                       scheduled_date: str = "2026-08-02", headers=MOD1):
    return get_success_data(
        api_client.triage_maintenance_request(
            request_id,
            create_triage_payload(severity=severity,
                                  scheduled_date=scheduled_date),
            headers,
        )
    )


def resolve_maintenance(request_id: str, headers=MOD1, **resolve_kwargs):
    return get_success_data(
        api_client.resolve_maintenance_request(
            request_id, create_resolve_payload(**resolve_kwargs), headers
        )
    )


def create_scheduled_maintenance(box_id: str, severity: str = "LOW",
                                 scheduled_date: str = "2026-08-02",
                                 category: str = "WEAR",
                                 description: str = "Routine wear observed"):
    """REPORTED -> SCHEDULED via triage. Returns the triaged request."""
    request = report_maintenance(box_id, category=category,
                                 description=description)
    triage_maintenance(request["id"], severity=severity,
                       scheduled_date=scheduled_date)
    return get_success_data(api_client.get_maintenance_request(request["id"], MOD1))


def resolve_box_maintenance(box_id: str, severity: str = "LOW",
                            category: str = "WEAR",
                            description: str = "Routine wear observed"):
    """Full report -> triage -> resolve cycle (earns the owner +40)."""
    request = create_scheduled_maintenance(
        box_id, severity=severity, category=category, description=description
    )
    return resolve_maintenance(request["id"])


# ---------------------------------------------------------------------------
# Tier 2: complaint pipeline (segregation of duties baked in)
# ---------------------------------------------------------------------------

def file_complaint(box_id: str, category: str = "OTHER",
                   description: str = "Something needs attention",
                   target_category: str = None):
    payload = create_complaint_payload(
        box_id, category=category, description=description
    )
    if target_category is not None:
        payload["target_category"] = target_category
    return get_success_data(api_client.create_complaint(payload, ANON))


def triage_complaint(complaint_id: str, headers=MOD1):
    return get_success_data(api_client.triage_complaint(complaint_id, headers))


def respond_to_complaint(complaint_id: str, steward_id: str,
                         response_text: str = "Taken care of."):
    """Steward response; the actor must own the complained box."""
    return get_success_data(
        api_client.respond_complaint(
            complaint_id, response_text, make_steward_headers(steward_id)
        )
    )


def resolve_complaint(complaint_id: str, outcome: str, headers=MOD2,
                      resolution_notes: str = None):
    payload = {"outcome": outcome}
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    return get_success_data(
        api_client.resolve_complaint(complaint_id, payload, headers)
    )


def create_under_review_complaint(box_id: str, steward_id: str,
                                  category: str = "OTHER",
                                  description: str = "Something needs attention",
                                  target_category: str = None,
                                  triager_headers=MOD1):
    """Complaint walked FILED -> STEWARD_RESPONSE_PENDING -> UNDER_REVIEW."""
    complaint = file_complaint(box_id, category=category,
                               description=description,
                               target_category=target_category)
    triage_complaint(complaint["id"], headers=triager_headers)
    respond_to_complaint(complaint["id"], steward_id)
    return get_success_data(api_client.get_complaint(complaint["id"], MOD1))


def create_upheld_complaint(box_id: str, steward_id: str,
                            category: str = "OTHER",
                            description: str = "Guideline breach",
                            target_category: str = None,
                            triager_headers=MOD1, resolver_headers=MOD2):
    """Complaint resolved UPHELD (triager and resolver are distinct actors)."""
    complaint = create_under_review_complaint(
        box_id, steward_id, category=category, description=description,
        target_category=target_category, triager_headers=triager_headers,
    )
    return resolve_complaint(complaint["id"], "UPHELD", headers=resolver_headers)


# ---------------------------------------------------------------------------
# Tier 2: schools and drives
# ---------------------------------------------------------------------------

def create_school(name: str = "Test School", region_code: str = "OR",
                  restricted_categories=None):
    return get_success_data(
        api_client.create_school(
            create_school_payload(
                name=name, region_code=region_code,
                restricted_categories=restricted_categories or [],
            ),
            ADMIN,
        )
    )


def create_active_school(**school_kwargs):
    school = create_school(**school_kwargs)
    return get_success_data(
        api_client.transition_school_status(school["id"], "ACTIVE", ADMIN)
    )


def propose_drive(school_id: str, coordinator_id: str, goal_books: int = 10,
                  starts_at: str = "2026-09-01T00:00:00Z",
                  ends_at: str = "2026-10-01T00:00:00Z"):
    """Steward proposes a drive (coordinator = acting steward)."""
    return get_success_data(
        api_client.create_drive(
            create_drive_payload(
                school_id, goal_books=goal_books, starts_at=starts_at,
                ends_at=ends_at,
            ),
            make_steward_headers(coordinator_id),
        )
    )


def approve_drive(drive_id: str, school_id: str):
    """Both fork-join approvals: school liaison APPROVE + network APPROVE."""
    get_success_data(
        api_client.drive_school_decision(
            drive_id, "APPROVE", make_school_liaison_headers(school_id)
        )
    )
    return get_success_data(api_client.drive_network_decision(drive_id, "APPROVE", ADMIN))


def get_linked_batch(drive_id: str):
    """The single DonationBatch minted by the drive's approval join."""
    data, meta = validate_paginated(
        api_client.list_batches(HUB, params={"drive_id": drive_id})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one linked batch for drive {drive_id}, "
        f"got {meta['total_count']}"
    )
    return data[0]


def create_approved_drive(school, coordinator, goal_books: int = 10,
                          starts_at: str = "2026-09-01T00:00:00Z",
                          ends_at: str = "2026-10-01T00:00:00Z"):
    """Drive fully approved (join complete; linked batch minted)."""
    drive = propose_drive(school["id"], coordinator["id"],
                          goal_books=goal_books, starts_at=starts_at,
                          ends_at=ends_at)
    approve_drive(drive["id"], school["id"])
    return get_success_data(api_client.get_drive(drive["id"], ADMIN))


def create_open_drive_with_batch(school, coordinator, goal_books: int = 10,
                                 starts_at: str = "2026-08-01T00:00:00Z",
                                 ends_at: str = "2026-08-20T00:00:00Z"):
    """Drive approved and swept to OPEN; returns (drive, linked_batch)."""
    drive = create_approved_drive(school, coordinator, goal_books=goal_books,
                                  starts_at=starts_at, ends_at=ends_at)
    run_sweep()
    batch = get_linked_batch(drive["id"])
    drive = get_success_data(api_client.get_drive(drive["id"], ADMIN))
    assert drive["status"] == "OPEN", (
        f"drive should be OPEN after sweep, got {drive['status']}"
    )
    return drive, batch


# ---------------------------------------------------------------------------
# Tier 2/3: donation intake and distribution
# ---------------------------------------------------------------------------

def create_batch(source_type: str = "PUBLIC_DROP", region_code: str = "OR",
                 drive_id: str = None):
    payload = create_batch_payload(source_type=source_type,
                                   region_code=region_code)
    if drive_id is not None:
        payload["drive_id"] = drive_id
    return get_success_data(api_client.create_batch(payload, HUB))


def intake_items(batch_id: str, items: list):
    """Bulk intake; returns the summary payload (created_count, ids, rejected)."""
    return get_success_data(api_client.intake_batch_items(batch_id, items, HUB))


def list_batch_items(batch_id: str):
    data, _meta = validate_paginated(
        api_client.list_book_items(HUB, params={"batch_id": batch_id, "limit": 100})
    )
    return data


def create_batch_with_items(item_count: int = 2, region_code: str = "OR",
                            category: str = "FICTION", graded: bool = True,
                            source_type: str = "PUBLIC_DROP",
                            drive_id: str = None):
    """RECEIVED batch plus `item_count` freshly intaked items."""
    batch = create_batch(source_type=source_type, region_code=region_code,
                         drive_id=drive_id)
    items = create_book_items(item_count, category=category, graded=graded)
    intake_items(batch["id"], items)
    return batch, list_batch_items(batch["id"])


def create_sorted_batch(item_count: int = 2, region_code: str = "OR",
                        category: str = "FICTION"):
    """Batch walked to SORTED (all items graded). Returns the SORTED batch
    (whose version is the correct expected_batch_version for run creation)
    and its items."""
    batch, items = create_batch_with_items(
        item_count=item_count, region_code=region_code, category=category
    )
    sorted_batch = get_success_data(api_client.sort_complete_batch(batch["id"], HUB))
    return sorted_batch, items


def create_run_for_batch(batch_id: str):
    """Create a DRAFT distribution run, reading the batch version first."""
    batch = get_success_data(api_client.get_batch(batch_id, HUB))
    return get_success_data(
        api_client.create_distribution_run(batch_id, batch["version"], HUB)
    )


def list_run_allocations(run_id: str):
    data, _meta = validate_paginated(
        api_client.list_run_allocations(run_id, HUB, params={"limit": 100})
    )
    return data


def confirm_run(run_id: str):
    return get_success_data(api_client.confirm_distribution_run(run_id, HUB))


def dispatch_run(run_id: str):
    return get_success_data(api_client.dispatch_distribution_run(run_id, HUB))


def setup_confirmed_run(item_count: int = 2, capacity_books: int = 10,
                        region_code: str = "OR"):
    """ACTIVE steward + ACTIVE LISTED box + SORTED batch + CONFIRMED run.

    Returns dict(steward, box, batch, run, allocations, items).
    """
    steward, box = create_steward_with_active_box(region_code=region_code,
                                                  capacity_books=capacity_books)
    batch, items = create_sorted_batch(item_count=item_count,
                                       region_code=region_code)
    run = create_run_for_batch(batch["id"])
    confirm_run(run["id"])
    allocations = list_run_allocations(run["id"])
    return {
        "steward": steward,
        "box": box,
        "batch": batch,
        "run": run,
        "allocations": allocations,
        "items": items,
    }


def setup_dispatched_run(item_count: int = 2, capacity_books: int = 10,
                         region_code: str = "OR"):
    """CONFIRMED run walked to DISPATCHED (allocations DISPATCHED)."""
    scenario = setup_confirmed_run(item_count=item_count,
                                   capacity_books=capacity_books,
                                   region_code=region_code)
    dispatch_run(scenario["run"]["id"])
    scenario["allocations"] = list_run_allocations(scenario["run"]["id"])
    return scenario


def receive_allocation(allocation_id: str, steward_id: str):
    """Box owner confirms a dispatched allocation as received."""
    return get_success_data(
        api_client.receive_allocation(
            allocation_id, make_steward_headers(steward_id)
        )
    )


def cancel_allocation(allocation_id: str):
    return get_success_data(api_client.cancel_allocation(allocation_id, HUB))


# ---------------------------------------------------------------------------
# Tier 4: recognition accumulation
# ---------------------------------------------------------------------------

def list_recognition_events(steward_id: str):
    data, _meta = validate_paginated(
        api_client.list_recognition_events(
            steward_id, ADMIN, params={"limit": 100}
        )
    )
    return data


def events_of_type(events: list, event_type: str) -> list:
    return [e for e in events if e["event_type"] == event_type]


def get_steward(steward_id: str):
    return get_success_data(api_client.get_steward(steward_id, ADMIN))


def get_box(box_id: str):
    return get_success_data(api_client.get_box(box_id, ADMIN))
