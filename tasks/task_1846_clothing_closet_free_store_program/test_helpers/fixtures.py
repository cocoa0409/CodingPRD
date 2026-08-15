"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Volunteer/VolunteerLead calls are entity-backed by
Volunteer, Client calls by Client, and ReferralPartner calls by
ReferralPartner. Helpers always build per-instance headers from the real
entity ids via the make_* builders; ownership-gated calls never fall back to
the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SORTING_SHIFT_END, SORTING_SHIFT_START
from .factories import (
    add_line_payload,
    checkin_visit_payload,
    create_client_payload,
    create_donation_batch_payload,
    create_drive_payload,
    create_item_payload,
    create_recycling_batch_payload,
    create_referral_partner_payload,
    create_seasonal_rotation_payload,
    create_shift_payload,
    create_signup_payload,
    create_storage_zone_payload,
    create_volunteer_payload,
    issue_voucher_payload,
    pickup_payload,
    release_quarantine_payload,
    stock_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_program_admin_headers,
    make_referral_partner_headers,
    make_volunteer_headers,
    make_volunteer_lead_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]


def admin_headers(user_id="test-program-admin-1"):
    return make_program_admin_headers(user_id)


def actor_headers_for(volunteer):
    """Per-instance headers for a volunteer actor: leads authenticate with the
    VolunteerLead role, plain volunteers with the Volunteer role."""
    if volunteer.get("is_lead"):
        return make_volunteer_lead_headers(volunteer["id"])
    return make_volunteer_headers(volunteer["id"])


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN), 200)


def register_volunteer(full_name="Vol One", is_lead=False):
    """Register a volunteer (born ACTIVE). Returns the volunteer."""
    return get_success_data(
        api_client.create_volunteer(
            create_volunteer_payload(full_name=full_name, is_lead=is_lead), ADMIN),
        201)


def register_client(full_name="C", household_size=2, eligibility_tier=None,
                    actor_headers=None):
    """Register a client (born ACTIVE). Defaults to a ProgramAdmin caller."""
    payload = create_client_payload(full_name=full_name, household_size=household_size)
    if eligibility_tier is not None:
        payload["eligibility_tier"] = eligibility_tier
    return get_success_data(
        api_client.create_client(payload, actor_headers or ADMIN), 201)


def create_zone(zone_code="Z1", season_policy="ALL_SEASON", capacity_items=10):
    """Create a storage zone (current_stock 0, posture AVAILABLE)."""
    return get_success_data(
        api_client.create_storage_zone(
            create_storage_zone_payload(zone_code=zone_code, season_policy=season_policy,
                                        capacity_items=capacity_items), ADMIN),
        201)


def get_zone(zone_id):
    return get_success_data(api_client.get_storage_zone(zone_id, ADMIN), 200)


def get_item(item_id):
    return get_success_data(api_client.get_item(item_id, ADMIN), 200)


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, ADMIN), 200)


def create_shift(start_at, end_at, role_type="FLOOR", capacity_volunteers=1,
                 actor_headers=None):
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(start_at=start_at, end_at=end_at, role_type=role_type,
                                 capacity_volunteers=capacity_volunteers),
            actor_headers or ADMIN),
        201)


def create_partner(name="Agency", base_voucher_quota=5):
    return get_success_data(
        api_client.create_referral_partner(
            create_referral_partner_payload(name=name, base_voucher_quota=base_voucher_quota),
            ADMIN),
        201)


def issue_voucher(partner, client_id, bonus_items=1, expires_at="2026-12-01T00:00:00Z",
                  waives_frequency=None):
    """Issue a voucher as the partner itself (ownership-gated on the partner id)."""
    payload = issue_voucher_payload(client_id=client_id, bonus_items=bonus_items,
                                    expires_at=expires_at)
    if waives_frequency is not None:
        payload["waives_frequency"] = waives_frequency
    return get_success_data(
        api_client.issue_voucher(partner["id"], payload,
                                 make_referral_partner_headers(partner["id"])),
        201)


def create_drive(drive_type="WINTER_COATS", target_category="COATS",
                 start_at="2026-08-05T00:00:00Z", end_at="2026-08-10T00:00:00Z",
                 bonus_items_per_client=1):
    return get_success_data(
        api_client.create_drive(
            create_drive_payload(drive_type=drive_type, target_category=target_category,
                                 start_at=start_at, end_at=end_at,
                                 bonus_items_per_client=bonus_items_per_client),
            ADMIN),
        201)


def create_rotation(target_season="WINTER", window_start="2026-09-01T00:00:00Z",
                    window_end="2026-09-02T00:00:00Z"):
    return get_success_data(
        api_client.create_seasonal_rotation(
            create_seasonal_rotation_payload(target_season=target_season,
                                             window_start=window_start,
                                             window_end=window_end),
            ADMIN),
        201)


def open_recycling_batch(recycler_name="TexCycle", capacity_kg=50):
    return get_success_data(
        api_client.create_recycling_batch(
            create_recycling_batch_payload(recycler_name=recycler_name,
                                           capacity_kg=capacity_kg),
            ADMIN),
        201)


# ---------------------------------------------------------------------------
# Tier 2: shift staffing (sorting-table precondition chains)
# ---------------------------------------------------------------------------

def signup_volunteer(shift_id, volunteer):
    """Sign a volunteer onto a shift acting as that volunteer (self-signup)."""
    return get_success_data(
        api_client.create_signup(shift_id, create_signup_payload(volunteer["id"]),
                                 actor_headers_for(volunteer)),
        201)


def checkin_signup(shift_id, signup_id, volunteer):
    """Check in a signup acting as the owning volunteer (ownership-gated)."""
    return get_success_data(
        api_client.checkin_signup(shift_id, signup_id, actor_headers_for(volunteer)),
        200)


def setup_sorting_staff(full_name="Vol One", is_lead=False, capacity=1,
                        start_at=SORTING_SHIFT_START, end_at=SORTING_SHIFT_END,
                        check_in=True):
    """Volunteer + SORTING shift covering the default clock + signup.

    With check_in=True (the default) the signup is CHECKED_IN, satisfying the
    staffed-sorting requirement; with check_in=False the signup stays
    SIGNED_UP. Returns {"volunteer", "headers", "shift", "signup"}.
    """
    volunteer = register_volunteer(full_name, is_lead)
    shift = create_shift(start_at, end_at, role_type="SORTING",
                         capacity_volunteers=capacity)
    signup = signup_volunteer(shift["id"], volunteer)
    if check_in:
        signup = checkin_signup(shift["id"], signup["id"], volunteer)
    return {
        "volunteer": volunteer,
        "headers": actor_headers_for(volunteer),
        "shift": shift,
        "signup": signup,
    }


# ---------------------------------------------------------------------------
# Tier 2: donation batch pipeline
# ---------------------------------------------------------------------------

def open_batch_in_sort(actor_headers, donor_name="Donor", item_count_declared=1):
    """Intake a batch and start sorting as the given actor. Returns IN_SORT batch."""
    batch = get_success_data(
        api_client.create_donation_batch(
            create_donation_batch_payload(donor_name=donor_name,
                                          item_count_declared=item_count_declared),
            actor_headers),
        201)
    return get_success_data(api_client.start_sorting(batch["id"], actor_headers), 200)


def grade_items(batch_id, specs, actor_headers):
    """Create+grade one item per spec against an IN_SORT batch.

    Each spec is a dict of create_item_payload kwargs (category, season,
    quality_grade, optional drive_id). Returns the created items in order.
    """
    items = []
    for spec in specs:
        items.append(get_success_data(
            api_client.create_batch_item(batch_id, create_item_payload(**spec),
                                         actor_headers),
            201))
    return items


def stock_items(item_ids, zone_id, actor_headers):
    """Stock each item into the zone. Returns the STOCKED items in order."""
    return [
        get_success_data(
            api_client.stock_item(item_id, stock_item_payload(zone_id), actor_headers),
            200)
        for item_id in item_ids
    ]


def setup_stocked_items(specs, zone_code="Z1", season_policy="ALL_SEASON",
                        capacity_items=10, staff=None):
    """Full pipeline: sorting staff + batch graded per specs + zone + every
    item stocked. Returns {"staff", "batch", "zone", "items"}.

    Only usable with non-REJECT grades (REJECT items never reach PENDING_STOCK).
    """
    staff = staff or setup_sorting_staff()
    batch = open_batch_in_sort(staff["headers"], item_count_declared=len(specs))
    items = grade_items(batch["id"], specs, staff["headers"])
    zone = create_zone(zone_code, season_policy, capacity_items)
    stocked = stock_items([item["id"] for item in items], zone["id"], staff["headers"])
    return {"staff": staff, "batch": batch, "zone": zone, "items": stocked}


def setup_rejected_items(specs, staff=None):
    """Sorting staff + one batch of REJECT-graded items (status REJECTED,
    awaiting the recycling sweep). Returns {"staff", "batch", "items"}."""
    staff = staff or setup_sorting_staff()
    batch = open_batch_in_sort(staff["headers"], item_count_declared=len(specs))
    items = grade_items(batch["id"], specs, staff["headers"])
    return {"staff": staff, "batch": batch, "items": items}


# ---------------------------------------------------------------------------
# Tier 3: visits, lines, checkout
# ---------------------------------------------------------------------------

def checkin_visit(client_id, actor_headers, voucher_id=None):
    """Check a client in, optionally redeeming a voucher. Returns the visit."""
    return get_success_data(
        api_client.checkin_visit(client_id, checkin_visit_payload(voucher_id),
                                 actor_headers),
        201)


def add_line(visit_id, item_id, actor_headers):
    return get_success_data(
        api_client.add_line(visit_id, add_line_payload(item_id), actor_headers), 201)


def add_lines(visit_id, item_ids, actor_headers):
    return [add_line(visit_id, item_id, actor_headers) for item_id in item_ids]


def checkout_visit(visit_id, actor_headers):
    return get_success_data(api_client.checkout_visit(visit_id, actor_headers), 200)


def setup_client_with_visit(full_name="C", household_size=2, eligibility_tier=None,
                            actor_headers=None, voucher_id=None):
    """Client + CHECKED_IN visit. Returns (client, visit)."""
    client = register_client(full_name, household_size, eligibility_tier, actor_headers)
    visit = checkin_visit(client["id"], actor_headers or ADMIN, voucher_id)
    return client, visit


# ---------------------------------------------------------------------------
# Tier 4: recycling pipeline
# ---------------------------------------------------------------------------

def sweep_recycling_batch(batch_id):
    return get_success_data(api_client.sweep_recycling_batch(batch_id, ADMIN), 200)


def seal_recycling_batch(batch_id, admin_user_id="admin-1"):
    """Seal as a ProgramAdmin; admin_user_id anchors the segregation-of-duties
    identity recorded in sealed_by_user_id."""
    return get_success_data(
        api_client.seal_recycling_batch(batch_id, admin_headers(admin_user_id)), 200)


def pickup_recycling_batch(batch_id, actual_weight_kg, admin_user_id="admin-2"):
    """Record pickup as a ProgramAdmin with a distinct admin identifier."""
    return get_success_data(
        api_client.pickup_recycling_batch(batch_id, pickup_payload(actual_weight_kg),
                                          admin_headers(admin_user_id)),
        200)


def setup_swept_recycling_batch(specs, capacity_kg=50, recycler_name="TexCycle"):
    """REJECT-graded items + an ACCUMULATING recycling batch + sweep applied.

    Returns {"staff", "items", "recycling_batch"} where recycling_batch is the
    post-sweep batch state.
    """
    rejected = setup_rejected_items(specs)
    batch = open_recycling_batch(recycler_name, capacity_kg)
    batch = sweep_recycling_batch(batch["id"])
    return {"staff": rejected["staff"], "donation_batch": rejected["batch"],
            "items": rejected["items"], "recycling_batch": batch}


# ---------------------------------------------------------------------------
# Tier 5: item-release helpers
# ---------------------------------------------------------------------------

def quarantine_item(item_id, actor_headers):
    return get_success_data(api_client.quarantine_item(item_id, actor_headers), 200)


def release_quarantine(item_id, outcome, actor_headers):
    return get_success_data(
        api_client.release_quarantine(item_id, release_quarantine_payload(outcome),
                                      actor_headers),
        200)
