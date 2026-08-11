"""Composite setup helpers.

Every fixture builds its state exclusively through PRD-declared endpoints — the
storage is wiped before each test, so nothing may be assumed to pre-exist.

Two structurally different journeys run through these helpers and they are kept
apart on purpose:

* **Pipeline R (rental circulation)** — box -> wear -> return -> grade -> clean
  -> restock.  Helpers named `setup_delivered_box`, `start_item_return`,
  `receive_return`, `grade_returned_unit`, ...
* **Pipeline T (trade-in intake)** — member-owned outgrown garments -> grade ->
  credit -> absorb/reject.  Helpers named `setup_received_trade_in`,
  `grade_trade_in_item`, `finalize_trade_in`, ...

Where a helper touches a rung the two pipelines share (labels, shipments,
grading, the ledgers), the caller states which pipeline it is in by choosing the
matching helper, because the applicable gate subsequence differs.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_capsule_allocation_payload,
    create_capsule_payload,
    create_charge_adjustment_payload,
    create_condition_assessment_payload,
    create_credit_adjustment_payload,
    create_credit_application_payload,
    create_garment_style_payload,
    create_garment_unit_payload,
    create_member_payload,
    create_pause_request_payload,
    create_plan_payload,
    create_shipment_payload,
    create_shipping_label_payload,
    create_swap_request_payload,
    create_trade_in_item_payload,
    create_trade_in_submission_payload,
    submit_grade_payload,
)
from .test_users import (
    ADMIN,
    BILLING,
    GRADER,
    LOGISTICS,
    PLANNER,
    VENDOR,
    WAREHOUSE,
    make_grader_headers,
    make_member_headers,
    make_planner_headers,
)

BIG_PAGE = {"limit": 100, "offset": 0}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Drive the logical clock.  Before any call it reads 2026-05-01T00:00:00Z."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_plan(plan_id):
    return get_success_data(api.get_plan(plan_id, ADMIN))


def get_member(member_id):
    return get_success_data(api.get_member(member_id, ADMIN))


def get_cycle(cycle_id):
    return get_success_data(api.get_cycle(cycle_id, ADMIN))


def get_style(style_id):
    return get_success_data(api.get_garment_style(style_id, PLANNER))


def get_unit(unit_id):
    return get_success_data(api.get_garment_unit(unit_id, PLANNER))


def get_box(box_id):
    return get_success_data(api.get_box(box_id, WAREHOUSE))


def get_box_item(box_item_id):
    return get_success_data(api.get_box_item(box_item_id, WAREHOUSE))


def get_swap_request(swap_request_id):
    return get_success_data(api.get_swap_request(swap_request_id, WAREHOUSE))


def get_label(label_id):
    return get_success_data(api.get_shipping_label(label_id, LOGISTICS))


def get_shipment(shipment_id):
    return get_success_data(api.get_shipment(shipment_id, LOGISTICS))


def get_assessment(assessment_id):
    return get_success_data(api.get_condition_assessment(assessment_id, GRADER))


def get_job(job_id):
    return get_success_data(api.get_processing_job(job_id, VENDOR))


def get_submission(submission_id):
    return get_success_data(api.get_trade_in_submission(submission_id, ADMIN))


def get_trade_in_item(item_id):
    return get_success_data(api.get_trade_in_item(item_id, ADMIN))


def get_buy_out_order(order_id):
    return get_success_data(api.get_buy_out_order(order_id, BILLING))


def get_capsule(capsule_id):
    return get_success_data(api.get_capsule(capsule_id, PLANNER))


def get_capsule_allocation(allocation_id):
    return get_success_data(api.get_capsule_allocation(allocation_id, PLANNER))


def get_pause_request(pause_request_id):
    return get_success_data(api.get_pause_request(pause_request_id, ADMIN))


def get_claim(claim_id):
    return get_success_data(api.get_lost_shipment_claim(claim_id, LOGISTICS))


def get_charge_entry(charge_entry_id):
    return get_success_data(api.get_charge_entry(charge_entry_id, BILLING))


def get_credit_entry(credit_entry_id):
    return get_success_data(api.get_credit_entry(credit_entry_id, BILLING))


def get_entitlements(member_id):
    return get_success_data(
        api.get_member_entitlements(member_id, make_member_headers(member_id))
    )


def get_invoice(cycle_id):
    return get_success_data(api.get_cycle_invoice(cycle_id, BILLING))


# ---------------------------------------------------------------------------
# Filtered list reads (all use limit 100 so nothing is truncated)
# ---------------------------------------------------------------------------


def _page(**filters):
    params = dict(BIG_PAGE)
    params.update({k: v for k, v in filters.items() if v is not None})
    return params


def list_box_items(**filters):
    return get_success_data(api.list_box_items(WAREHOUSE, _page(**filters)))


def list_charge_entries(**filters):
    return get_success_data(api.list_charge_entries(BILLING, _page(**filters)))


def list_credit_entries(**filters):
    return get_success_data(api.list_credit_entries(BILLING, _page(**filters)))


def list_assessments(**filters):
    return get_success_data(api.list_condition_assessments(GRADER, _page(**filters)))


def list_jobs(**filters):
    return get_success_data(api.list_processing_jobs(VENDOR, _page(**filters)))


def list_units(**filters):
    return get_success_data(api.list_garment_units(PLANNER, _page(**filters)))


def list_buy_out_orders(**filters):
    return get_success_data(api.list_buy_out_orders(BILLING, _page(**filters)))


def list_claims(**filters):
    return get_success_data(api.list_lost_shipment_claims(LOGISTICS, _page(**filters)))


def list_trade_in_items(**filters):
    return get_success_data(api.list_trade_in_items(ADMIN, _page(**filters)))


# ---------------------------------------------------------------------------
# Tier 1 — plans, members, catalog, stock
# ---------------------------------------------------------------------------


def create_plan(**overrides) -> dict:
    return get_success_data(api.create_plan(create_plan_payload(**overrides), ADMIN))


def create_member(plan_id, **overrides) -> dict:
    """Register a household.  The new member is PENDING."""
    return get_success_data(api.create_member(create_member_payload(plan_id, **overrides), ADMIN))


def activate_member(member_id) -> dict:
    return get_success_data(api.activate_member(member_id, ADMIN))


def create_active_member(plan_id, **overrides) -> dict:
    """Register + activate.  Returns the member as read back after activation."""
    member = create_member(plan_id, **overrides)
    activate_member(member["id"])
    return get_member(member["id"])


def setup_plan_and_member(plan=None, member=None) -> tuple:
    """The two-step preamble almost every scenario starts from."""
    plan_row = create_plan(**(plan or {}))
    member_row = create_active_member(plan_row["id"], **(member or {}))
    return plan_row, member_row


def create_style(**overrides) -> dict:
    return get_success_data(
        api.create_garment_style(create_garment_style_payload(**overrides), PLANNER)
    )


def create_unit(style_id, **overrides) -> dict:
    return get_success_data(
        api.create_garment_unit(create_garment_unit_payload(style_id, **overrides), PLANNER)
    )


def create_style_with_units(count=1, style_overrides=None, unit_overrides=None) -> tuple:
    style = create_style(**(style_overrides or {}))
    units = [create_unit(style["id"], **(unit_overrides or {})) for _ in range(count)]
    return style, units


# ---------------------------------------------------------------------------
# Tier 2 — cycles and boxes (Pipeline R)
# ---------------------------------------------------------------------------


def create_cycle(member_id, start_at="2026-05-01T00:00:00Z") -> dict:
    return get_success_data(
        api.create_cycle({"member_id": member_id, "start_at": start_at}, ADMIN)
    )


def open_cycle(cycle_id) -> dict:
    return get_success_data(api.open_cycle(cycle_id, ADMIN))


def create_open_cycle(member_id, start_at="2026-05-01T00:00:00Z") -> dict:
    cycle = create_cycle(member_id, start_at)
    open_cycle(cycle["id"])
    return get_cycle(cycle["id"])


def create_box(cycle_id) -> dict:
    return get_success_data(api.create_box({"cycle_id": cycle_id}, WAREHOUSE))


def allocate_unit(box_id, unit_id=None, style_id=None) -> dict:
    """Allocate one unit into a DRAFT box.  Returns the created BoxItem, read
    back from the box-item list when the response echoes something else."""
    payload = {}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if style_id is not None:
        payload["style_id"] = style_id
    data = get_success_data(api.allocate_into_box(box_id, payload, WAREHOUSE))
    if isinstance(data, dict) and "fulfillment_status" in data:
        return data
    items = list_box_items(box_id=box_id)
    return items[-1]


def pack_box(box_id) -> dict:
    return get_success_data(api.pack_box(box_id, WAREHOUSE))


def mint_label(member_id, direction) -> dict:
    return get_success_data(
        api.create_shipping_label(create_shipping_label_payload(member_id, direction), LOGISTICS)
    )


def ship_box(box_id, label_id) -> dict:
    """Ship a PACKED box under an OUTBOUND label.  Returns the outbound
    Shipment, resolved through the box's `outbound_shipment_id`."""
    get_success_data(api.ship_box(box_id, {"label_id": label_id}, LOGISTICS))
    box = get_box(box_id)
    assert box.get("outbound_shipment_id"), "Setup failed: box.outbound_shipment_id was not written"
    return get_shipment(box["outbound_shipment_id"])


def depart_shipment(shipment_id) -> dict:
    return get_success_data(api.depart_shipment(shipment_id, LOGISTICS))


def receive_shipment(shipment_id) -> dict:
    return get_success_data(api.receive_shipment(shipment_id, WAREHOUSE))


def mark_shipment_lost(shipment_id) -> dict:
    return get_success_data(api.mark_shipment_lost(shipment_id, LOGISTICS))


# ---------------------------------------------------------------------------
# Tier 3 — the full Pipeline R outbound leg
# ---------------------------------------------------------------------------


def setup_allocated_box(member, units=None, style_id=None, cycle=None,
                        start_at="2026-05-01T00:00:00Z") -> dict:
    """Open a cycle (unless one is supplied), open a DRAFT box for it and
    allocate the supplied units.  Returns a scenario dict."""
    cycle_row = cycle or create_open_cycle(member["id"], start_at)
    box = create_box(cycle_row["id"])
    items = []
    for unit in (units or []):
        items.append(allocate_unit(box["id"], unit_id=unit["id"]))
    if style_id is not None and not units:
        items.append(allocate_unit(box["id"], style_id=style_id))
    return {
        "member": member,
        "cycle": get_cycle(cycle_row["id"]),
        "box": get_box(box["id"]),
        "items": items,
    }


def setup_delivered_box(member, units, cycle=None, start_at="2026-05-01T00:00:00Z") -> dict:
    """Pipeline R: allocate every supplied unit, pack, ship under a fresh
    OUTBOUND label, depart and receive.  The box ends DELIVERED and every item
    ends WITH_MEMBER."""
    scenario = setup_allocated_box(member, units=units, cycle=cycle, start_at=start_at)
    pack_box(scenario["box"]["id"])
    label = mint_label(member["id"], "OUTBOUND")
    shipment = ship_box(scenario["box"]["id"], label["id"])
    depart_shipment(shipment["id"])
    receive_shipment(shipment["id"])
    scenario["outbound_label"] = get_label(label["id"])
    scenario["outbound_shipment"] = get_shipment(shipment["id"])
    scenario["box"] = get_box(scenario["box"]["id"])
    scenario["items"] = [get_box_item(i["id"]) for i in scenario["items"]]
    return scenario


def setup_basic_delivered_scenario(plan=None, member=None, style=None,
                                   unit_count=1, unit=None,
                                   start_at="2026-05-01T00:00:00Z") -> dict:
    """The most common Pipeline R preamble: plan -> active member -> style ->
    units -> open cycle -> box -> allocate -> pack -> ship -> deliver."""
    plan_row, member_row = setup_plan_and_member(plan, member)
    style_row, units = create_style_with_units(unit_count, style, unit)
    scenario = setup_delivered_box(member_row, units, start_at=start_at)
    scenario["plan"] = plan_row
    scenario["style"] = style_row
    scenario["units"] = units
    return scenario


# ---------------------------------------------------------------------------
# Tier 3b — the Pipeline R inbound leg
# ---------------------------------------------------------------------------


def create_return_shipment(member_id, item_count=1) -> dict:
    """Mint a RETURN label and create the matching CREATED shipment."""
    label = mint_label(member_id, "RETURN")
    shipment = get_success_data(
        api.create_shipment(
            create_shipment_payload(member_id, label["id"], "RETURN", item_count), LOGISTICS
        )
    )
    return {"label": label, "shipment": shipment}


def start_item_return(member_id, box_item_id, return_shipment_id) -> dict:
    return get_success_data(
        api.start_return(box_item_id, {"return_shipment_id": return_shipment_id},
                         make_member_headers(member_id))
    )


def setup_returned_items(member, box_item_ids) -> dict:
    """Pipeline R: start the return of every named item on one RETURN shipment,
    depart it and receive it.  Receipt moves each item to RECEIVED, each unit to
    PROCESSING and opens a DRAFT RENTAL assessment per unit."""
    ret = create_return_shipment(member["id"], item_count=len(box_item_ids))
    for item_id in box_item_ids:
        start_item_return(member["id"], item_id, ret["shipment"]["id"])
    depart_shipment(ret["shipment"]["id"])
    receive_shipment(ret["shipment"]["id"])
    return {
        "return_label": get_label(ret["label"]["id"]),
        "return_shipment": get_shipment(ret["shipment"]["id"]),
    }


def find_rental_assessment(unit_id) -> dict:
    """The RENTAL assessment a RETURN receipt opens for a unit."""
    rows = list_assessments(unit_id=unit_id, pipeline="RENTAL")
    assert rows, f"Setup failed: no RENTAL assessment was opened for unit {unit_id}"
    return rows[-1]


def find_processing_job(unit_id) -> dict:
    rows = list_jobs(unit_id=unit_id)
    assert rows, f"Setup failed: no ProcessingJob exists for unit {unit_id}"
    return rows[-1]


def submit_grade(assessment_id, grade, defect_codes=None, grader_id="op-grader-1") -> dict:
    return get_success_data(
        api.submit_assessment(assessment_id, submit_grade_payload(grade, defect_codes),
                              make_grader_headers(grader_id))
    )


def confirm_grade(assessment_id, planner_id="op-planner-1") -> dict:
    """Confirmation is a MerchandisePlanner action whose X-User-ID must differ
    from the assessment's graded_by_user_id (segregation of duties)."""
    return get_success_data(
        api.confirm_assessment(assessment_id, make_planner_headers(planner_id))
    )


def grade_returned_unit(unit_id, grade, defect_codes=None,
                        grader_id="op-grader-1", planner_id="op-planner-1") -> dict:
    """Pipeline R: submit and confirm the grade on the unit's open RENTAL
    assessment.  Returns the confirmed assessment."""
    assessment = find_rental_assessment(unit_id)
    submit_grade(assessment["id"], grade, defect_codes, grader_id)
    confirm_grade(assessment["id"], planner_id)
    return get_assessment(assessment["id"])


def setup_returned_and_graded(member, box_item, unit, grade="A",
                              defect_codes=None) -> dict:
    """Ship one item home, bring it back and confirm its grade."""
    ret = setup_returned_items(member, [box_item["id"]])
    assessment = grade_returned_unit(unit["id"], grade, defect_codes)
    ret["assessment"] = assessment
    ret["job"] = find_processing_job(unit["id"])
    return ret


# ---------------------------------------------------------------------------
# Tier 4 — the cycle calendar
# ---------------------------------------------------------------------------


def drive_cycle_to_grace(cycle_id,
                         swap_close_at="2026-05-22T00:00:00Z",
                         grace_at="2026-06-08T00:00:00Z") -> dict:
    """SWAP_CLOSED at `swap_close_at`, then straight into GRACE at `grace_at`
    (a single assess-late call from SWAP_CLOSED once the grace boundary has
    already been passed)."""
    set_clock(swap_close_at)
    get_success_data(api.close_swap_window(cycle_id, ADMIN))
    set_clock(grace_at)
    get_success_data(api.assess_late(cycle_id, BILLING))
    return get_cycle(cycle_id)


def drive_cycle_to_return_due(cycle_id,
                              swap_close_at="2026-05-22T00:00:00Z",
                              return_due_at="2026-06-01T00:00:00Z") -> dict:
    """SWAP_CLOSED, then RETURN_DUE — the edge on which no late fee accrues."""
    set_clock(swap_close_at)
    get_success_data(api.close_swap_window(cycle_id, ADMIN))
    set_clock(return_due_at)
    get_success_data(api.assess_late(cycle_id, BILLING))
    return get_cycle(cycle_id)


def close_cycle(cycle_id) -> dict:
    return get_success_data(api.close_cycle(cycle_id, BILLING))


def complete_one_empty_cycle(member_id, start_at="2026-05-01T00:00:00Z") -> dict:
    """Open, run and CLOSE a cycle holding no items, so the member's
    `completed_cycles` reaches 1 and capsule eligibility is met."""
    cycle = create_open_cycle(member_id, start_at)
    drive_cycle_to_return_due(cycle["id"])
    close_cycle(cycle["id"])
    return get_cycle(cycle["id"])


# ---------------------------------------------------------------------------
# Tier 4b — swaps
# ---------------------------------------------------------------------------


def create_swap_request(member_id, cycle_id, return_box_item_ids, requested_style_ids,
                        expected_cycle_version=None) -> dict:
    version = expected_cycle_version
    if version is None:
        version = get_cycle(cycle_id)["version"]
    return get_success_data(
        api.create_swap_request(
            cycle_id,
            create_swap_request_payload(return_box_item_ids, requested_style_ids, version),
            make_member_headers(member_id),
        )
    )


def submit_swap(member_id, swap_request_id) -> dict:
    return get_success_data(
        api.submit_swap_request(swap_request_id, make_member_headers(member_id))
    )


def approve_swap(swap_request_id) -> dict:
    return get_success_data(api.approve_swap_request(swap_request_id, WAREHOUSE))


def fulfill_swap(swap_request_id) -> dict:
    return get_success_data(api.fulfill_swap_request(swap_request_id, WAREHOUSE))


# ---------------------------------------------------------------------------
# Tier 4c — buy-outs
# ---------------------------------------------------------------------------


def mint_buy_out_quote(member_id, box_item_id, quote_variant="CYCLES_WORN",
                       expected_box_item_version=None) -> dict:
    """Mint a quote and return the BuyOutOrder, resolved through the buy-out
    list filtered by box item so the assertion never depends on which resource
    the mutation response echoes."""
    version = expected_box_item_version
    if version is None:
        version = get_box_item(box_item_id)["version"]
    get_success_data(
        api.create_buy_out_quote(
            box_item_id,
            {"quote_variant": quote_variant, "expected_box_item_version": version},
            make_member_headers(member_id),
        )
    )
    orders = list_buy_out_orders(box_item_id=box_item_id)
    assert orders, f"Setup failed: no BuyOutOrder exists for box item {box_item_id}"
    return orders[-1]


# ---------------------------------------------------------------------------
# Tier 5 — Pipeline T (trade-in intake)
# ---------------------------------------------------------------------------


def create_trade_in_submission(member_id, declared_item_count=3) -> dict:
    return get_success_data(
        api.create_trade_in_submission(
            create_trade_in_submission_payload(member_id, declared_item_count),
            make_member_headers(member_id),
        )
    )


def add_trade_in_item(member_id, submission_id, declared_brand_tier="STANDARD",
                      declared_size_code="6") -> dict:
    return get_success_data(
        api.add_trade_in_item(
            submission_id,
            create_trade_in_item_payload(declared_brand_tier, declared_size_code),
            make_member_headers(member_id),
        )
    )


def issue_trade_in_label(submission_id, label_id) -> str:
    """Attach a TRADE_IN_INBOUND label; returns the created inbound shipment id
    read back from the submission."""
    get_success_data(api.issue_trade_in_label(submission_id, {"label_id": label_id}, LOGISTICS))
    submission = get_submission(submission_id)
    assert submission.get("inbound_shipment_id"), (
        "Setup failed: submission.inbound_shipment_id was not written"
    )
    return submission["inbound_shipment_id"]


def setup_received_trade_in(member, item_count=3, declared_brand_tier="STANDARD",
                            declared_size_code="6") -> dict:
    """Pipeline T: open a submission, declare `item_count` garments, attach a
    TRADE_IN_INBOUND label, depart and receive the parcel.  The submission ends
    RECEIVED and ownership of every declared garment has transferred."""
    submission = create_trade_in_submission(member["id"], item_count)
    items = [
        add_trade_in_item(member["id"], submission["id"], declared_brand_tier, declared_size_code)
        for _ in range(item_count)
    ]
    label = mint_label(member["id"], "TRADE_IN_INBOUND")
    shipment_id = issue_trade_in_label(submission["id"], label["id"])
    depart_shipment(shipment_id)
    receive_shipment(shipment_id)
    return {
        "submission": get_submission(submission["id"]),
        "items": [get_trade_in_item(i["id"]) for i in items],
        "inbound_label": get_label(label["id"]),
        "inbound_shipment": get_shipment(shipment_id),
    }


def open_trade_in_assessment(trade_in_item_id, grader_id="op-grader-1") -> dict:
    return get_success_data(
        api.create_condition_assessment(
            create_condition_assessment_payload("TRADE_IN", trade_in_item_id=trade_in_item_id),
            make_grader_headers(grader_id),
        )
    )


def grade_trade_in_item(trade_in_item_id, grade, grader_id="op-grader-1",
                        planner_id="op-planner-1") -> dict:
    """Pipeline T: open, submit and confirm a TRADE_IN assessment against one
    declared garment.  Returns the confirmed assessment."""
    assessment = open_trade_in_assessment(trade_in_item_id, grader_id)
    submit_grade(assessment["id"], grade, grader_id=grader_id)
    confirm_grade(assessment["id"], planner_id)
    return get_assessment(assessment["id"])


def setup_graded_trade_in(member, grades, declared_brand_tier="STANDARD",
                          declared_size_code="6") -> dict:
    """Receive a submission of `len(grades)` garments and confirm each grade."""
    scenario = setup_received_trade_in(
        member, len(grades), declared_brand_tier, declared_size_code
    )
    for item, grade in zip(scenario["items"], grades):
        grade_trade_in_item(item["id"], grade)
    scenario["submission"] = get_submission(scenario["submission"]["id"])
    scenario["items"] = [get_trade_in_item(i["id"]) for i in scenario["items"]]
    return scenario


def finalize_trade_in(submission_id) -> dict:
    return get_success_data(api.finalize_trade_in_submission(submission_id, BILLING))


def setup_credited_trade_in(member, grades, declared_brand_tier="STANDARD",
                            declared_size_code="6") -> dict:
    """Receive, grade and finalise a submission, so credit has been granted."""
    scenario = setup_graded_trade_in(member, grades, declared_brand_tier, declared_size_code)
    finalize_trade_in(scenario["submission"]["id"])
    scenario["submission"] = get_submission(scenario["submission"]["id"])
    scenario["items"] = [get_trade_in_item(i["id"]) for i in scenario["items"]]
    return scenario


# ---------------------------------------------------------------------------
# Tier 5b — ledgers, pauses, capsules
# ---------------------------------------------------------------------------


def raise_charge(member_id, charge_type, amount_cents) -> dict:
    return get_success_data(
        api.create_charge_adjustment(
            member_id, create_charge_adjustment_payload(charge_type, amount_cents), BILLING
        )
    )


def grant_credit(member_id, amount_cents, reason="goodwill") -> dict:
    return get_success_data(
        api.create_credit_adjustment(
            member_id, create_credit_adjustment_payload(amount_cents, reason), BILLING
        )
    )


def apply_credit(member_id, charge_entry_id, expected_member_version=None) -> dict:
    version = expected_member_version
    if version is None:
        version = get_member(member_id)["version"]
    return get_success_data(
        api.create_credit_application(
            member_id, create_credit_application_payload(charge_entry_id, version), BILLING
        )
    )


def find_charge(member_id, charge_type) -> dict:
    rows = list_charge_entries(member_id=member_id, charge_type=charge_type)
    assert rows, f"Setup failed: no {charge_type} charge exists for member {member_id}"
    return rows[-1]


def make_member_delinquent(member_id, amount_cents=20000, charge_type="LOST_LIABILITY") -> dict:
    """Push the outstanding balance over the 15000-cent threshold."""
    raise_charge(member_id, charge_type, amount_cents)
    return get_member(member_id)


def request_pause(member_id, start_at="2026-05-05T00:00:00Z", days_requested=10) -> dict:
    return get_success_data(
        api.create_pause_request(
            member_id, create_pause_request_payload(start_at, days_requested),
            make_member_headers(member_id),
        )
    )


def activate_pause(pause_request_id) -> dict:
    return get_success_data(api.activate_pause_request(pause_request_id, BILLING))


def end_pause(member_id, pause_request_id) -> dict:
    return get_success_data(
        api.end_pause_request(pause_request_id, make_member_headers(member_id))
    )


def setup_paused_member(member_id, start_at="2026-05-05T00:00:00Z", days_requested=10) -> dict:
    pause = request_pause(member_id, start_at, days_requested)
    activate_pause(pause["id"])
    return get_pause_request(pause["id"])


def create_capsule(**overrides) -> dict:
    return get_success_data(api.create_capsule(create_capsule_payload(**overrides), PLANNER))


def announce_capsule(capsule_id) -> dict:
    return get_success_data(api.announce_capsule(capsule_id, PLANNER))


def open_capsule(capsule_id) -> dict:
    return get_success_data(api.open_capsule(capsule_id, PLANNER))


def setup_open_capsule(release_at="2026-06-01T00:00:00Z",
                       close_at="2026-08-01T00:00:00Z",
                       season="SS", name="Test Wave",
                       quota_per_member=2,
                       open_at="2026-06-01T00:00:00Z") -> dict:
    """DRAFT -> ANNOUNCED (before release_at) -> OPEN (at or after release_at)."""
    capsule = create_capsule(season=season, name=name, release_at=release_at,
                             close_at=close_at, quota_per_member=quota_per_member)
    announce_capsule(capsule["id"])
    set_clock(open_at)
    open_capsule(capsule["id"])
    return get_capsule(capsule["id"])


def claim_capsule_allocation(member_id, capsule_id, units_allocated=1) -> dict:
    return get_success_data(
        api.create_capsule_allocation(
            capsule_id, create_capsule_allocation_payload(member_id, units_allocated),
            make_member_headers(member_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5c — lost parcels
# ---------------------------------------------------------------------------


def file_claim(member_id, shipment_id) -> dict:
    return get_success_data(
        api.create_lost_shipment_claim({"shipment_id": shipment_id},
                                       make_member_headers(member_id))
    )


def setup_lost_return(member, box_item_ids, scanned=True) -> dict:
    """Pipeline R: put the named items on a RETURN shipment and lose it.

    `scanned=True` departs the parcel first (so `ever_scanned` is true and the
    loss is taken from IN_TRANSIT); `scanned=False` marks it lost straight from
    CREATED, which is the only way a never-scanned loss can occur.
    """
    ret = create_return_shipment(member["id"], item_count=len(box_item_ids))
    for item_id in box_item_ids:
        start_item_return(member["id"], item_id, ret["shipment"]["id"])
    if scanned:
        depart_shipment(ret["shipment"]["id"])
    mark_shipment_lost(ret["shipment"]["id"])
    return {
        "return_label": get_label(ret["label"]["id"]),
        "return_shipment": get_shipment(ret["shipment"]["id"]),
    }


def setup_investigating_claim(member, box_item_ids, scanned=True) -> dict:
    lost = setup_lost_return(member, box_item_ids, scanned)
    claim = file_claim(member["id"], lost["return_shipment"]["id"])
    get_success_data(api.investigate_claim(claim["id"], LOGISTICS))
    lost["claim"] = get_claim(claim["id"])
    return lost
