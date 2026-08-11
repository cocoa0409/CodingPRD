"""Composite setup helpers.

Every entity a test needs is built through declared endpoints, so a fixture is
just an API client with a script.  Setup calls use the lenient validator so a
broken precondition surfaces as a clear setup failure rather than a confusing
assertion later.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    CLOCK_START,
    FREEZE_INSTANT,
    MOVE_START,
    create_authority_record_payload,
    create_client_payload,
    create_consignment_lot_payload,
    create_crew_assignment_payload,
    create_crew_member_payload,
    create_destination_residence_payload,
    create_destination_room_payload,
    create_engagement_payload,
    create_family_hold_payload,
    create_inventory_item_payload,
    create_invoice_line_payload,
    create_move_day_plan_payload,
    create_portal_party_payload,
    create_punch_list_item_payload,
    create_sort_plan_payload,
    create_time_entry_payload,
    create_unpack_session_payload,
    create_vendor_assignment_payload,
    create_vendor_payload,
)
from .test_users import (
    BILLING_ADMIN,
    MOVE_MANAGER,
    PLATFORM_ADMIN,
    make_vendor_headers,
)

PACKER_CHECK_IN = "2026-06-15T17:30:00.000Z"
LEAD_CHECK_OUT = "2026-06-15T23:30:00.000Z"


# ---------------------------------------------------------------------------
# Tier 0 - primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601, headers=MOVE_MANAGER):
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def new_client(**overrides):
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), MOVE_MANAGER)
    )


def new_engagement(client_id, **overrides):
    return get_success_data(
        api_client.create_engagement(
            create_engagement_payload(client_id, **overrides), MOVE_MANAGER
        )
    )


def new_portal_party(engagement_id, party_type="CLIENT", **overrides):
    return get_success_data(
        api_client.create_portal_party(
            create_portal_party_payload(engagement_id, party_type, **overrides),
            MOVE_MANAGER,
        )
    )


def new_authority_record(engagement_id, holder_party_id, **overrides):
    return get_success_data(
        api_client.create_authority_record(
            create_authority_record_payload(
                engagement_id, holder_party_id, **overrides
            ),
            MOVE_MANAGER,
        )
    )


def activate_authority(authority_id):
    return get_success_data(
        api_client.activate_authority_record(authority_id, MOVE_MANAGER)
    )


def new_active_authority(engagement_id, holder_party_id, **overrides):
    record = new_authority_record(engagement_id, holder_party_id, **overrides)
    return activate_authority(record["id"])


def new_residence(engagement_id, **overrides):
    return get_success_data(
        api_client.create_destination_residence(
            create_destination_residence_payload(engagement_id, **overrides),
            MOVE_MANAGER,
        )
    )


def new_room(residence_id, **overrides):
    return get_success_data(
        api_client.create_destination_room(
            create_destination_room_payload(residence_id, **overrides), MOVE_MANAGER
        )
    )


def new_item(engagement_id, **overrides):
    return get_success_data(
        api_client.create_inventory_item(
            create_inventory_item_payload(engagement_id, **overrides), MOVE_MANAGER
        )
    )


def designate(item_id, disposition, assigned_room_id=None, headers=MOVE_MANAGER, **extra):
    payload = {"disposition": disposition}
    if assigned_room_id is not None:
        payload["assigned_room_id"] = assigned_room_id
    payload.update(extra)
    return get_success_data(api_client.designate_item(item_id, payload, headers))


def appraise(item_id, appraised_value_cents, appraisal_source, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.appraise_item(
            item_id,
            {
                "appraised_value_cents": appraised_value_cents,
                "appraisal_source": appraisal_source,
            },
            headers,
        )
    )


def advance_handling(item_id, target_handling_state, unpack_session_id=None, headers=MOVE_MANAGER):
    payload = {"target_handling_state": target_handling_state}
    if unpack_session_id is not None:
        payload["unpack_session_id"] = unpack_session_id
    return get_success_data(api_client.advance_handling(item_id, payload, headers))


def new_family_hold(inventory_item_id, raised_by_party_id, headers=MOVE_MANAGER, **overrides):
    return get_success_data(
        api_client.create_family_hold(
            create_family_hold_payload(
                inventory_item_id, raised_by_party_id, **overrides
            ),
            headers,
        )
    )


def read_milestones(engagement_id, headers=MOVE_MANAGER):
    """The milestone list is ordered by sequence_index ascending."""
    body = api_client.list_milestones(headers, params={"engagement_id": engagement_id}).json()
    return body["data"]


def milestone_by_key(engagement_id, milestone_key, headers=MOVE_MANAGER):
    for row in read_milestones(engagement_id, headers):
        if row["milestone_key"] == milestone_key:
            return row
    raise AssertionError(f"Setup failed: no {milestone_key} milestone on {engagement_id}")


def complete_milestone(milestone_id, completed_by_party_id, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.complete_milestone(
            milestone_id, {"completed_by_party_id": completed_by_party_id}, headers
        )
    )


def reopen_milestone(milestone_id, reason="Reopened for rework", headers=MOVE_MANAGER):
    return get_success_data(
        api_client.reopen_milestone(milestone_id, {"reason": reason}, headers)
    )


def engagement_version(engagement_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_engagement(engagement_id, headers))["version"]


def read_engagement(engagement_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_engagement(engagement_id, headers))


def read_item(item_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_inventory_item(item_id, headers))


def read_room(room_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_destination_room(room_id, headers))


def read_residence(residence_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_destination_residence(residence_id, headers))


def read_party(party_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_portal_party(party_id, headers))


def read_authority(authority_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_authority_record(authority_id, headers))


def read_sort_plan(plan_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_sort_plan(plan_id, headers))


def read_move_day_plan(plan_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_move_day_plan(plan_id, headers))


def read_crew_assignment(assignment_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_crew_assignment(assignment_id, headers))


def read_crew_member(crew_member_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_crew_member(crew_member_id, PLATFORM_ADMIN))


def read_time_entry(entry_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_time_entry(entry_id, headers))


def read_vendor(vendor_id, headers=PLATFORM_ADMIN):
    return get_success_data(api_client.get_vendor(vendor_id, headers))


def read_vendor_assignment(assignment_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_vendor_assignment(assignment_id, headers))


def read_lot(lot_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_consignment_lot(lot_id, headers))


def read_hold(hold_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_family_hold(hold_id, headers))


def read_unpack_session(session_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_unpack_session(session_id, headers))


def read_punch_item(item_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_punch_list_item(item_id, headers))


def read_milestone(milestone_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_milestone(milestone_id, headers))


def read_summary(engagement_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.get_engagement_summary(engagement_id, headers))


def invoice_of(engagement_id, headers=BILLING_ADMIN):
    """Every engagement has exactly one invoice, so the filtered read returns it."""
    body = api_client.list_invoices(headers, params={"engagement_id": engagement_id}).json()
    rows = body["data"]
    assert rows, f"Setup failed: no invoice for engagement {engagement_id}"
    return rows[0]


def read_invoice(invoice_id, headers=BILLING_ADMIN):
    return get_success_data(api_client.get_invoice(invoice_id, headers))


def invoice_lines(invoice_id, headers=BILLING_ADMIN, limit=100):
    body = api_client.list_invoice_lines(
        headers, params={"invoice_id": invoice_id, "limit": limit}
    ).json()
    return body["data"]


def append_manual_line(invoice_id, amount_cents, memo="Manual adjustment", headers=BILLING_ADMIN):
    version = read_invoice(invoice_id, headers)["version"]
    return get_success_data(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id, "MANUAL_ADJUSTMENT", amount_cents, memo, version
            ),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 - sort plan progression
# ---------------------------------------------------------------------------


def new_sort_plan(engagement_id, expected_version=None, headers=MOVE_MANAGER, **overrides):
    version = (
        engagement_version(engagement_id) if expected_version is None else expected_version
    )
    return get_success_data(
        api_client.create_sort_plan(
            create_sort_plan_payload(engagement_id, version, **overrides), headers
        )
    )


def submit_sort_plan(plan_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.submit_sort_plan(plan_id, headers))


def approve_sort_plan(plan_id, approved_by_party_id, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.approve_sort_plan(
            plan_id, {"approved_by_party_id": approved_by_party_id}, headers
        )
    )


def drive_sort_plan_to_approved(engagement_id, party_id):
    """Complete ASSESSMENT, then create, submit and approve the sort plan."""
    assessment = milestone_by_key(engagement_id, "ASSESSMENT")
    complete_milestone(assessment["id"], party_id)
    plan = new_sort_plan(engagement_id)
    submit_sort_plan(plan["id"])
    return approve_sort_plan(plan["id"], party_id)


# ---------------------------------------------------------------------------
# Tier 2 - the engagement world
# ---------------------------------------------------------------------------


def setup_engagement(
    billing_mode="HOURLY",
    home_tier="STUDIO",
    package_tier=None,
    mileage_miles=22,
    origin_stairs_flights=2,
    origin_long_carry_feet=100,
    scheduled_move_start_utc=MOVE_START,
    clock=CLOCK_START,
    with_client_party=True,
    with_family_party=False,
    with_poa_party=False,
    with_residence=False,
    room_kwargs=None,
    client_kwargs=None,
):
    """Clock, client, engagement and (optionally) the portal seats and residence."""
    if clock is not None:
        set_clock(clock)
    client = new_client(**(client_kwargs or {}))
    engagement_overrides = {
        "billing_mode": billing_mode,
        "home_tier": home_tier,
        "mileage_miles": mileage_miles,
        "origin_stairs_flights": origin_stairs_flights,
        "origin_long_carry_feet": origin_long_carry_feet,
        "scheduled_move_start_utc": scheduled_move_start_utc,
    }
    if package_tier is not None:
        engagement_overrides["package_tier"] = package_tier
    engagement = new_engagement(client["id"], **engagement_overrides)

    world = {
        "client": client,
        "engagement": engagement,
        "engagement_id": engagement["id"],
        "client_party": None,
        "family_party": None,
        "poa_party": None,
        "residence": None,
        "room": None,
    }
    if with_client_party:
        world["client_party"] = new_portal_party(
            engagement["id"], "CLIENT", client_id=client["id"]
        )
    if with_family_party:
        world["family_party"] = new_portal_party(
            engagement["id"],
            "FAMILY_MEMBER",
            display_name="Marcus Whitfield",
            email="marcus@example.com",
        )
    if with_poa_party:
        world["poa_party"] = new_portal_party(
            engagement["id"],
            "POA",
            display_name="Ruth Whitfield",
            email="ruth@example.com",
        )
    if with_residence:
        world["residence"] = new_residence(engagement["id"])
        world["room"] = new_room(world["residence"]["id"], **(room_kwargs or {}))
    return world


# ---------------------------------------------------------------------------
# Tier 3 - the move-day roster
# ---------------------------------------------------------------------------


def new_crew_member(full_name, crew_role, hourly_rate_cents=None):
    overrides = {}
    if hourly_rate_cents is not None:
        overrides["hourly_rate_cents"] = hourly_rate_cents
    return get_success_data(
        api_client.create_crew_member(
            create_crew_member_payload(full_name, crew_role, **overrides),
            PLATFORM_ADMIN,
        )
    )


def new_move_day_plan(engagement_id, headers=MOVE_MANAGER, **overrides):
    return get_success_data(
        api_client.create_move_day_plan(
            create_move_day_plan_payload(engagement_id, **overrides), headers
        )
    )


def assign_crew(move_day_plan_id, crew_member_id, replaces_assignment_id=None, headers=MOVE_MANAGER):
    """Re-reads the plan's version so the optimistic-concurrency field is fresh."""
    version = read_move_day_plan(move_day_plan_id)["version"]
    overrides = {}
    if replaces_assignment_id is not None:
        overrides["replaces_assignment_id"] = replaces_assignment_id
    return get_success_data(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(
                move_day_plan_id, crew_member_id, version, **overrides
            ),
            headers,
        )
    )


def confirm_assignment(assignment_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.confirm_crew_assignment(assignment_id, headers))


def check_in(assignment_id, at_utc, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.check_in_crew_assignment(assignment_id, {"at_utc": at_utc}, headers)
    )


def check_out(assignment_id, at_utc, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.check_out_crew_assignment(assignment_id, {"at_utc": at_utc}, headers)
    )


def no_show(assignment_id, note="Called in sick", headers=MOVE_MANAGER):
    return get_success_data(
        api_client.no_show_crew_assignment(assignment_id, {"note": note}, headers)
    )


def new_time_entry(crew_assignment_id, entry_kind, started_at_utc, ended_at_utc, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.create_time_entry(
            create_time_entry_payload(
                crew_assignment_id, entry_kind, started_at_utc, ended_at_utc
            ),
            headers,
        )
    )


def staff_lead_and_packer(plan_id, lead_rate=9500, packer_rate=6800):
    """Two crew members and two assignments: the STUDIO minimum with a lead."""
    lead = new_crew_member("Tom Reyes", "LEAD", lead_rate)
    packer = new_crew_member("Nina Ortiz", "PACKER", packer_rate)
    lead_assignment = assign_crew(plan_id, lead["id"])
    packer_assignment = assign_crew(plan_id, packer["id"])
    return {
        "lead_member": lead,
        "packer_member": packer,
        "lead_assignment": lead_assignment,
        "packer_assignment": packer_assignment,
    }


# ---------------------------------------------------------------------------
# Tier 4 - the full move-day drive
# ---------------------------------------------------------------------------


def setup_move_day_plan_confirmed(
    billing_mode="HOURLY",
    home_tier="STUDIO",
    package_tier=None,
    mileage_miles=22,
    origin_stairs_flights=2,
    origin_long_carry_feet=100,
    with_residence=True,
    room_kwargs=None,
    keep_items=None,
    other_items=None,
    lead_rate=9500,
    packer_rate=6800,
    truck_capacity_cft=1000,
    truck_count=1,
    scheduled_start_utc=MOVE_START,
):
    """Engagement -> catalogued items -> APPROVED sort plan -> CONFIRMED move-day plan."""
    world = setup_engagement(
        billing_mode=billing_mode,
        home_tier=home_tier,
        package_tier=package_tier,
        mileage_miles=mileage_miles,
        origin_stairs_flights=origin_stairs_flights,
        origin_long_carry_feet=origin_long_carry_feet,
        with_residence=with_residence,
        room_kwargs=room_kwargs,
    )
    eng_id = world["engagement_id"]
    world["items"] = []
    if keep_items is None:
        keep_items = [
            {"label": "Walnut sideboard", "footprint_linear_inches": 96, "volume_cft": 40}
        ]
    for spec in keep_items:
        item = new_item(eng_id, **spec)
        designate(item["id"], "KEEP", world["room"]["id"])
        world["items"].append(read_item(item["id"]))
    for spec in other_items or []:
        disposition = spec.pop("disposition", "DONATE")
        item = new_item(eng_id, **spec)
        designate(item["id"], disposition)
        world["items"].append(read_item(item["id"]))

    world["sort_plan"] = drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    plan = new_move_day_plan(
        eng_id,
        scheduled_start_utc=scheduled_start_utc,
        truck_capacity_cft=truck_capacity_cft,
        truck_count=truck_count,
    )
    world["plan"] = plan
    world.update(staff_lead_and_packer(plan["id"], lead_rate, packer_rate))
    confirm_assignment(world["lead_assignment"]["id"])
    confirm_assignment(world["packer_assignment"]["id"])
    world["plan"] = get_success_data(api_client.confirm_move_day_plan(plan["id"], MOVE_MANAGER))
    return world


def freeze_and_start(world, freeze_at=FREEZE_INSTANT, start_at=MOVE_START):
    plan_id = world["plan"]["id"]
    set_clock(freeze_at)
    world["plan"] = get_success_data(api_client.freeze_move_day_plan(plan_id, MOVE_MANAGER))
    set_clock(start_at)
    world["plan"] = get_success_data(api_client.start_move_day_plan(plan_id, MOVE_MANAGER))
    return world


def setup_completed_move_day(
    lead_in=MOVE_START,
    packer_in=PACKER_CHECK_IN,
    lead_out=LEAD_CHECK_OUT,
    packer_out=None,
    complete_at=LEAD_CHECK_OUT,
    actual_loaded_volume_cft=2200,
    **setup_kwargs,
):
    """Drive an engagement all the way through move-day completion.

    ``packer_out=None`` leaves the packer CHECKED_IN so the completion cascade
    closes the assignment itself.
    """
    world = setup_move_day_plan_confirmed(**setup_kwargs)
    freeze_and_start(world)
    if lead_in is not None:
        check_in(world["lead_assignment"]["id"], lead_in)
    if packer_in is not None:
        check_in(world["packer_assignment"]["id"], packer_in)
    if packer_out is not None:
        set_clock(packer_out)
        check_out(world["packer_assignment"]["id"], packer_out)
    if lead_out is not None:
        set_clock(lead_out)
        check_out(world["lead_assignment"]["id"], lead_out)
    set_clock(complete_at)
    world["invoice"] = invoice_of(world["engagement_id"])
    world["plan"] = get_success_data(
        api_client.complete_move_day_plan(
            world["plan"]["id"],
            {"actual_loaded_volume_cft": actual_loaded_volume_cft},
            MOVE_MANAGER,
        )
    )
    world["invoice"] = read_invoice(world["invoice"]["id"])
    return world


def setup_issued_invoice(**kwargs):
    """A completed move day whose invoice has then been issued by billing."""
    world = setup_completed_move_day(**kwargs)
    world["invoice"] = get_success_data(
        api_client.issue_invoice(world["invoice"]["id"], BILLING_ADMIN)
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5 - settle-in and close-out
# ---------------------------------------------------------------------------


def new_unpack_session(engagement_id, scheduled_start_utc, priority, headers=MOVE_MANAGER):
    return get_success_data(
        api_client.create_unpack_session(
            create_unpack_session_payload(
                engagement_id, scheduled_start_utc, priority
            ),
            headers,
        )
    )


def start_unpack_session(session_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.start_unpack_session(session_id, headers))


def complete_unpack_session(session_id, headers=MOVE_MANAGER):
    return get_success_data(api_client.complete_unpack_session(session_id, headers))


def new_punch_item(engagement_id, description, severity, unpack_session_id=None, headers=MOVE_MANAGER):
    overrides = {}
    if unpack_session_id is not None:
        overrides["unpack_session_id"] = unpack_session_id
    return get_success_data(
        api_client.create_punch_list_item(
            create_punch_list_item_payload(
                engagement_id, description, severity, **overrides
            ),
            headers,
        )
    )


def resolve_punch_item(item_id, resolution_note="Fixed on site", headers=MOVE_MANAGER):
    return get_success_data(
        api_client.resolve_punch_list_item(
            item_id, {"resolution_note": resolution_note}, headers
        )
    )


def setup_settle_in(settle_in_clock="2026-06-20T09:00:00.000Z", **kwargs):
    """A completed move day with the clock advanced into the settle-in window."""
    world = setup_completed_move_day(**kwargs)
    set_clock(settle_in_clock)
    return world


def complete_remaining_milestones(engagement_id, party_id):
    """Complete SETTLE_IN and CLOSE_OUT once move day is done."""
    for key in ("SETTLE_IN", "CLOSE_OUT"):
        milestone = milestone_by_key(engagement_id, key)
        complete_milestone(milestone["id"], party_id)


# ---------------------------------------------------------------------------
# Tier 6 - vendors and consignment
# ---------------------------------------------------------------------------


def new_vendor(name, vendor_type, coi_expires_on, **overrides):
    return get_success_data(
        api_client.create_vendor(
            create_vendor_payload(name, vendor_type, coi_expires_on, **overrides),
            PLATFORM_ADMIN,
        )
    )


def new_vendor_assignment(engagement_id, vendor_id, service_kind, service_date, quoted_cents):
    return get_success_data(
        api_client.create_vendor_assignment(
            create_vendor_assignment_payload(
                engagement_id, vendor_id, service_kind, service_date, quoted_cents
            ),
            MOVE_MANAGER,
        )
    )


def accept_vendor_assignment(assignment_id, vendor_id):
    """The vendor accepts its own order, so the actor is that vendor."""
    return get_success_data(
        api_client.accept_vendor_assignment(assignment_id, make_vendor_headers(vendor_id))
    )


def schedule_vendor_assignment(assignment_id):
    return get_success_data(
        api_client.schedule_vendor_assignment(assignment_id, MOVE_MANAGER)
    )


def perform_vendor_assignment(assignment_id, vendor_id, performed_at_utc):
    return get_success_data(
        api_client.perform_vendor_assignment(
            assignment_id,
            {"performed_at_utc": performed_at_utc},
            make_vendor_headers(vendor_id),
        )
    )


def setup_scheduled_vendor_assignment(
    engagement_id,
    vendor_type="CLEANING",
    service_kind="CLEANING",
    service_date="2026-06-16",
    quoted_cents=85000,
    coi_expires_on="2027-01-31",
    vendor_name="Bright Path Cleaning",
    **vendor_overrides,
):
    vendor = new_vendor(vendor_name, vendor_type, coi_expires_on, **vendor_overrides)
    assignment = new_vendor_assignment(
        engagement_id, vendor["id"], service_kind, service_date, quoted_cents
    )
    accept_vendor_assignment(assignment["id"], vendor["id"])
    assignment = schedule_vendor_assignment(assignment["id"])
    return vendor, assignment


def new_consignment_lot(engagement_id, vendor_id, list_price_cents, listed_on, item_ids):
    return get_success_data(
        api_client.create_consignment_lot(
            create_consignment_lot_payload(
                engagement_id, vendor_id, list_price_cents, listed_on, item_ids
            ),
            MOVE_MANAGER,
        )
    )


THREE_SELL_ITEMS = [
    {
        "label": "Silver tea service",
        "category": "MISC",
        "footprint_linear_inches": 24,
        "volume_cft": 6,
        "appraised_value_cents": 90000,
        "appraisal_source": "APPRAISED",
    },
    {
        "label": "Oil landscape",
        "category": "ARTWORK",
        "footprint_linear_inches": 40,
        "volume_cft": 8,
        "appraised_value_cents": 120000,
        "appraisal_source": "APPRAISED",
    },
    {
        "label": "Mantel clock",
        "category": "MISC",
        "footprint_linear_inches": 12,
        "volume_cft": 3,
        "appraised_value_cents": 45000,
        "appraisal_source": "APPRAISED",
    },
]


def setup_consignment_lot(
    item_specs=None,
    list_price_cents=240000,
    listed_on="2026-05-05",
    vendor_name="Hollis Estate Gallery",
    coi_expires_on="2027-01-31",
    engagement_kwargs=None,
):
    """An engagement whose SELL items sit in one LISTED consignment lot."""
    world = setup_engagement(with_client_party=False, **(engagement_kwargs or {}))
    eng_id = world["engagement_id"]
    vendor = new_vendor(vendor_name, "CONSIGNMENT", coi_expires_on, daily_capacity=3, holdback_pct=0.1)
    items = []
    for spec in item_specs if item_specs is not None else THREE_SELL_ITEMS:
        item = new_item(eng_id, **spec)
        designate(item["id"], "SELL")
        items.append(item)
    lot = new_consignment_lot(
        eng_id, vendor["id"], list_price_cents, listed_on, [i["id"] for i in items]
    )
    world["vendor"] = vendor
    world["items"] = items
    world["lot"] = lot
    world["invoice"] = invoice_of(eng_id)
    return world


def setup_sold_lot(gross_sale_price_cents=250000, sold_on="2026-05-20", **kwargs):
    world = setup_consignment_lot(**kwargs)
    world["lot"] = get_success_data(
        api_client.record_lot_sale(
            world["lot"]["id"],
            {
                "gross_sale_price_cents": gross_sale_price_cents,
                "sold_on": sold_on,
            },
            MOVE_MANAGER,
        )
    )
    return world


__all__ = [name for name in dir() if not name.startswith("_")]
