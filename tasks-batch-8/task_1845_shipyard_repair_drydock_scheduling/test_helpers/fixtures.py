"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
and uses get_success_data() so a setup failure surfaces as a clear
"Setup step failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CONTRACT_DELIVERY_DATE,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    create_change_order_payload,
    create_dock_payload,
    create_dock_reservation_payload,
    create_permit_payload,
    create_repair_project_payload,
    create_subcontractor_payload,
    create_survey_payload,
    create_vessel_payload,
    create_warranty_claim_payload,
    create_work_item_payload,
)
from .test_users import TEST_USERS, make_shipowner_rep_headers

# Role header aliases (PRD §2.1).
ADMIN = TEST_USERS["yard_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
PM2 = TEST_USERS["project_manager_2_headers"]
COMM = TEST_USERS["commercial_approver_headers"]
COMM2 = TEST_USERS["commercial_approver_2_headers"]
OWNER = TEST_USERS["shipowner_rep_headers"]
SV1 = TEST_USERS["class_surveyor_headers"]
SV2 = TEST_USERS["class_surveyor_2_headers"]
EO = TEST_USERS["environmental_officer_headers"]


# ─── Tier 0: registry primitives ──────────────────────

def create_dock(**overrides) -> dict:
    """Register a dock/berth (PRD §3.1). Returns the created DockBerth."""
    return get_success_data(
        api_client.create_dock(create_dock_payload(**overrides), ADMIN), 201
    )


def create_vessel(**overrides) -> dict:
    """Register a vessel (PRD §3.1). Returns the created Vessel."""
    return get_success_data(
        api_client.create_vessel(create_vessel_payload(**overrides), PM), 201
    )


def create_subcontractor(**overrides) -> dict:
    """Register a trade firm (PRD §3.1). Returns the created Subcontractor."""
    return get_success_data(
        api_client.create_subcontractor(
            create_subcontractor_payload(**overrides), ADMIN
        ),
        201,
    )


# ─── Tier 1: project state progression ────────────────

def create_draft_project(dock_id=None, vessel_id=None, **overrides) -> dict:
    """Open a project in DRAFT (PRD §3.2). Creates its own dock/vessel when the
    caller does not supply ids. Returns the created RepairProject."""
    if dock_id is None:
        dock_id = create_dock()["id"]
    if vessel_id is None:
        vessel_id = create_vessel()["id"]
    return get_success_data(
        api_client.create_repair_project(
            create_repair_project_payload(vessel_id, dock_id, **overrides), PM
        ),
        201,
    )


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_repair_project(project_id, PM))


def get_project_version(project_id: str) -> int:
    return get_project(project_id)["version"]


def add_base_work_item(project_id: str, **overrides) -> dict:
    """Add a base-spec work line to a DRAFT or BID_SUBMITTED project (PRD §3.2)."""
    return get_success_data(
        api_client.create_work_item(
            create_work_item_payload(project_id, **overrides), PM
        ),
        201,
    )


def submit_bid(project_id: str) -> dict:
    return get_success_data(api_client.submit_bid(project_id, PM))


def award_project(project_id: str) -> dict:
    return get_success_data(api_client.award_project(project_id, COMM))


def deliver_project(project_id: str) -> dict:
    return get_success_data(api_client.deliver_project(project_id, PM))


# ─── Tier 2: dock bookings ────────────────────────────

def book_reservation(
    project_id: str,
    start_utc: str = DEFAULT_WINDOW_START,
    end_utc: str = DEFAULT_WINDOW_END,
    expected_project_version=None,
) -> dict:
    """Book a dock window with OCC on the project version (PRD §2.8, §3.3).
    Reads the fresh project version when one is not supplied."""
    if expected_project_version is None:
        expected_project_version = get_project_version(project_id)
    return get_success_data(
        api_client.create_dock_reservation(
            create_dock_reservation_payload(
                project_id,
                expected_project_version,
                start_utc=start_utc,
                end_utc=end_utc,
            ),
            PM,
        ),
        201,
    )


def activate_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.activate_dock_reservation(reservation_id, PM))


# ─── Tier 3: full lifecycle shortcuts ─────────────────

def setup_contracted_project(item_specs=None, **project_overrides) -> dict:
    """DRAFT -> BID_SUBMITTED -> CONTRACTED with a base specification.
    item_specs: list of work-item override dicts (default: one small line).
    Returns {"dock", "vessel", "project", "items"}."""
    if item_specs is None:
        item_specs = [{}]
    project = create_draft_project(**project_overrides)
    items = [add_base_work_item(project["id"], **spec) for spec in item_specs]
    submit_bid(project["id"])
    awarded = award_project(project["id"])
    return {
        "dock": get_success_data(api_client.get_dock(awarded["dock_id"], PM)),
        "vessel": get_success_data(api_client.get_vessel(awarded["vessel_id"], PM)),
        "project": awarded,
        "items": items,
    }


def setup_in_dock_project(
    item_specs=None,
    start_utc: str = DEFAULT_WINDOW_START,
    end_utc: str = DEFAULT_WINDOW_END,
    **project_overrides,
) -> dict:
    """CONTRACTED project plus a BOOKED reservation, activated at the default
    logical clock so the project is IN_DOCK (PRD §3.3).
    Returns {"dock", "vessel", "project", "items", "reservation"}."""
    ctx = setup_contracted_project(item_specs=item_specs, **project_overrides)
    reservation = book_reservation(ctx["project"]["id"], start_utc, end_utc)
    activated = activate_reservation(reservation["id"])
    ctx["reservation"] = activated
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def start_item(work_item_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.start_work_item(work_item_id, headers or PM)
    )


def complete_item(work_item_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.complete_work_item(work_item_id, headers or PM)
    )


def setup_delivered_project(
    item_specs=None,
    deliver_clock: str = None,
    **project_overrides,
) -> dict:
    """Full lifecycle through DELIVERED (PRD §3.7). When deliver_clock is given,
    the logical clock advances to that instant before the items are completed
    and the vessel is delivered, so the final liquidated-damages variant runs
    against that delivery date. Returns the setup context dict."""
    ctx = setup_in_dock_project(item_specs=item_specs, **project_overrides)
    if deliver_clock is not None:
        set_clock(deliver_clock)
    for item in ctx["items"]:
        start_item(item["id"])
        complete_item(item["id"])
    ctx["project"] = deliver_project(ctx["project"]["id"])
    return ctx


# ─── Tier 4: growth work, surveys, permits, claims ────

def create_change_order(project_id: str, expected_project_version=None, **overrides) -> dict:
    """Propose growth work against an IN_DOCK project (PRD §3.5). Reads the
    fresh project version when one is not supplied."""
    if expected_project_version is None:
        expected_project_version = get_project_version(project_id)
    return get_success_data(
        api_client.create_change_order(
            create_change_order_payload(
                project_id, expected_project_version, **overrides
            ),
            PM,
        ),
        201,
    )


def approve_change_order(change_order_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.approve_change_order(change_order_id, headers or COMM)
    )


def schedule_survey(
    project_id: str,
    survey_type: str = "CLASS_RENEWAL",
    start: str = "2026-08-02T09:00:00Z",
    end: str = "2026-08-02T12:00:00Z",
    headers=None,
) -> dict:
    """Book a survey against the creating surveyor's own calendar (PRD §3.6)."""
    return get_success_data(
        api_client.create_survey(
            create_survey_payload(
                project_id,
                survey_type=survey_type,
                scheduled_start_utc=start,
                scheduled_end_utc=end,
            ),
            headers or SV1,
        ),
        201,
    )


def apply_permit(
    project_id: str,
    permit_type: str = "HOT_WORK",
    valid_from: str = "2026-08-01T00:00:00Z",
    valid_to: str = "2026-08-15T23:59:59Z",
) -> dict:
    """Apply for an environmental permit window (PRD §3.6). Returns APPLIED permit."""
    return get_success_data(
        api_client.create_permit(
            create_permit_payload(
                project_id,
                permit_type=permit_type,
                valid_from=valid_from,
                valid_to=valid_to,
            ),
            EO,
        ),
        201,
    )


def grant_permit(permit_id: str) -> dict:
    return get_success_data(api_client.grant_permit(permit_id, EO))


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5). Runs the permit-expiry and
    warranty-closure sweeps as a side effect."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    )


def file_warranty_claim(project_id: str, work_item_id: str, owner_user_id: str = "owner_9",
                        **overrides) -> dict:
    """File a defect claim against a delivered work item (PRD §3.8)."""
    return get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(project_id, work_item_id, **overrides),
            make_shipowner_rep_headers(owner_user_id),
        ),
        201,
    )
