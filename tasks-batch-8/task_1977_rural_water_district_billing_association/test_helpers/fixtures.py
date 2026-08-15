"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API (the
harness restarts the server before each test, so no state is shared). Setup
calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DUE_PLUS_10D,
    CLOCK_DUE_PLUS_45D,
    CYCLE_1,
    CYCLE_1_EARLY_DUE,
    CYCLE_2,
    SCHEDULE_S1,
)
from .factories import (
    create_annexation_petition_payload,
    create_billing_cycle_payload,
    create_boil_order_payload,
    create_board_resolution_payload,
    create_compliance_sample_payload,
    create_district_payload,
    create_master_meter_reading_payload,
    create_member_payload,
    create_meter_reading_payload,
    create_notification_payload,
    create_payment_payload,
    create_rate_schedule_payload,
    create_service_area_payload,
    create_tap_payload,
)
from .test_users import TEST_USERS, board_voter_headers

ADMIN = TEST_USERS["system_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
DIRECTOR = TEST_USERS["board_director_headers"]
FIELD = TEST_USERS["field_operator_headers"]


# --- Tier 1: single-entity creation ---------------------------------------

def create_district(annual_debt_service_cents=120_000, district_name="Test District", **overrides):
    """Create a district; returns the district dict."""
    payload = create_district_payload(
        district_name=district_name, annual_debt_service_cents=annual_debt_service_cents, **overrides
    )
    return get_success_data(api_client.create_district(payload, ADMIN), expected_status=201)


def create_area(district_id, **overrides):
    """Create an ACTIVE service area; returns the area dict."""
    return get_success_data(
        api_client.create_service_area(district_id, create_service_area_payload(**overrides), ADMIN),
        expected_status=201,
    )


def create_member(district_id, area_id, **overrides):
    """File a membership application (status APPLIED)."""
    return get_success_data(
        api_client.create_member(district_id, create_member_payload(area_id, **overrides), CLERK),
        expected_status=201,
    )


def approve_member(district_id, member_id):
    return get_success_data(api_client.approve_member(district_id, member_id, CLERK))


def create_active_member(district_id, area_id, **overrides):
    """Member created and approved to ACTIVE."""
    member = create_member(district_id, area_id, **overrides)
    return approve_member(district_id, member["id"])


def propose_resolution(district_id, resolution_type, subject_id, payload=None,
                       expected_district_version=None):
    """Propose a board resolution (status PROPOSED)."""
    body = create_board_resolution_payload(resolution_type, subject_id)
    if payload is not None:
        body["payload"] = payload
    if expected_district_version is not None:
        body["expected_district_version"] = expected_district_version
    return get_success_data(
        api_client.create_board_resolution(district_id, body, DIRECTOR), expected_status=201
    )


def vote_resolution(district_id, resolution_id, vote="FOR"):
    """Cast one vote per distinct board voter id, in order."""
    responses = []
    for headers in board_voter_headers():
        resp = api_client.record_vote(district_id, resolution_id, {"vote": vote}, headers)
        if resp.status_code != 200:
            return responses, resp
        responses.append(resp)
        data = get_success_data(responses[-1])
        if data["status"] != "PROPOSED":
            break
    return responses, responses[-1]


def adopt_resolution(district_id, resolution_type, subject_id, payload=None,
                     expected_district_version=None):
    """Propose + adopt a resolution with three distinct FOR votes."""
    resolution = propose_resolution(
        district_id, resolution_type, subject_id, payload, expected_district_version
    )
    _, final_resp = vote_resolution(district_id, resolution["id"], "FOR")
    return get_success_data(final_resp)


def fail_resolution(district_id, resolution_type, subject_id, payload=None):
    """Propose + fail a resolution with three distinct AGAINST votes."""
    resolution = propose_resolution(district_id, resolution_type, subject_id, payload)
    _, final_resp = vote_resolution(district_id, resolution["id"], "AGAINST")
    return get_success_data(final_resp)


def adopt_rate_schedule(district_id, **schedule_overrides):
    """Draft a rate schedule and adopt it by RATE_ADOPTION resolution."""
    schedule = get_success_data(
        api_client.create_rate_schedule(
            district_id, create_rate_schedule_payload(**schedule_overrides), DIRECTOR
        ),
        expected_status=201,
    )
    adopt_resolution(district_id, "RATE_ADOPTION", schedule["id"])
    return get_success_data(api_client.get_rate_schedule(district_id, schedule["id"], DIRECTOR))


# --- Tier 2: hierarchy builders -------------------------------------------

def setup_district_with_schedule(annual_debt_service_cents=120_000, **schedule_overrides):
    """District + ADOPTED rate schedule. Returns (district, schedule)."""
    district = create_district(annual_debt_service_cents=annual_debt_service_cents)
    schedule = adopt_rate_schedule(district["id"], **schedule_overrides)
    district = get_success_data(api_client.get_district(district["id"], ADMIN))
    return district, schedule


def setup_member_with_installed_tap(annual_debt_service_cents=120_000,
                                    member_class="RESIDENTIAL", tap_fee_paid=None):
    """District + adopted schedule + ACTIVE member + INSTALLED tap.

    Returns dict with district, schedule, area, member, tap.
    """
    district, schedule = setup_district_with_schedule(annual_debt_service_cents)
    area = create_area(district["id"])
    member = create_active_member(district["id"], area["id"], member_class=member_class)
    tap = get_success_data(
        api_client.create_tap(district["id"], create_tap_payload(member["id"]), CLERK),
        expected_status=201,
    )
    amount = tap_fee_paid if tap_fee_paid is not None else tap["tap_fee_cents"]
    tap = get_success_data(
        api_client.pay_tap_fee(district["id"], tap["id"], {"amount_cents": amount}, TREASURER)
    )
    tap = get_success_data(api_client.install_meter(district["id"], tap["id"], FIELD))
    return {
        "district": district,
        "schedule": schedule,
        "area": area,
        "member": get_success_data(api_client.get_member(district["id"], member["id"], CLERK)),
        "tap": tap,
    }


def add_member_with_installed_tap(district_id, area_id, legal_name="Test Member",
                                  member_class="RESIDENTIAL", tap_fee_paid=None):
    """Add one ACTIVE member + INSTALLED tap to an existing district."""
    member = create_active_member(
        district_id, area_id, legal_name=legal_name, member_class=member_class
    )
    tap = get_success_data(
        api_client.create_tap(district_id, create_tap_payload(member["id"]), CLERK),
        expected_status=201,
    )
    amount = tap_fee_paid if tap_fee_paid is not None else tap["tap_fee_cents"]
    get_success_data(
        api_client.pay_tap_fee(district_id, tap["id"], {"amount_cents": amount}, TREASURER)
    )
    tap = get_success_data(api_client.install_meter(district_id, tap["id"], FIELD))
    return member, tap


# --- Tier 3: billing cycle lifecycle --------------------------------------

def open_cycle(district_id, **window_overrides):
    payload = create_billing_cycle_payload(**window_overrides)
    return get_success_data(
        api_client.create_billing_cycle(district_id, payload, CLERK), expected_status=201
    )


def submit_reading(district_id, tap_id, cycle_id, reading_gallons, reading_type="ACTUAL"):
    return get_success_data(
        api_client.create_meter_reading(
            district_id,
            create_meter_reading_payload(tap_id, cycle_id, reading_gallons, reading_type=reading_type),
            FIELD,
        ),
        expected_status=201,
    )


def bill_cycle_with_readings(district_id, cycle_id, readings):
    """Submit readings [(tap_id, gallons[, type])], mark complete, bill."""
    for item in readings:
        tap_id, gallons = item[0], item[1]
        reading_type = item[2] if len(item) > 2 else "ACTUAL"
        submit_reading(district_id, tap_id, cycle_id, gallons, reading_type)
    get_success_data(api_client.mark_readings_complete(district_id, cycle_id, CLERK))
    return get_success_data(api_client.bill_cycle(district_id, cycle_id, CLERK))


def post_master_reading(district_id, cycle_id, master_gallons):
    return get_success_data(
        api_client.create_master_meter_reading(
            district_id, create_master_meter_reading_payload(cycle_id, master_gallons), FIELD
        ),
        expected_status=201,
    )


def get_district_version(district_id) -> int:
    return get_success_data(api_client.get_district(district_id, TREASURER))["version"]


def close_cycle(district_id, cycle_id, master_gallons):
    """Post the master reading and close with a fresh district version."""
    post_master_reading(district_id, cycle_id, master_gallons)
    version = get_district_version(district_id)
    return get_success_data(
        api_client.close_cycle(district_id, cycle_id, {"expected_district_version": version}, TREASURER)
    )


def list_invoices(district_id):
    return get_success_data(api_client.list_invoices(district_id, CLERK))


def get_cycle_invoice(district_id, cycle_id, member_id=None):
    """Client-side selection of an invoice by cycle (and optionally member)."""
    matches = [
        inv for inv in list_invoices(district_id)
        if inv["cycle_id"] == cycle_id and (member_id is None or inv["member_id"] == member_id)
    ]
    assert len(matches) >= 1, f"Setup failed: no invoice for cycle {cycle_id}"
    return matches[0]


def pay_invoice(district_id, member_id, invoice_id, amount_cents):
    return get_success_data(
        api_client.create_payment(
            district_id, create_payment_payload(member_id, invoice_id, amount_cents), TREASURER
        ),
        expected_status=201,
    )


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, CLERK))


# --- Tier 4: full billing scenarios ---------------------------------------

def setup_billed_invoice(usage_gallons, due_date_utc=None, annual_debt_service_cents=120_000,
                         reading_type="ACTUAL"):
    """Full chain through bill: one member, one tap, one cycle, one invoice.

    Returns dict with district, schedule, area, member, tap, cycle, invoice.
    """
    ctx = setup_member_with_installed_tap(annual_debt_service_cents)
    district = ctx["district"]
    window = dict(CYCLE_1)
    if due_date_utc is not None:
        window["due_date_utc"] = due_date_utc
        # PRD section 3.3: "due_date_utc at or after period_end_utc" — an early
        # due date pulls the period end back with it so the window stays
        # well-formed.
        if window["period_end_utc"] > due_date_utc:
            window["period_end_utc"] = due_date_utc
    cycle = open_cycle(district["id"], **window)
    bill_cycle_with_readings(district["id"], cycle["id"], [(ctx["tap"]["id"], usage_gallons, reading_type)])
    invoice = get_cycle_invoice(district["id"], cycle["id"])
    ctx["cycle"] = cycle
    ctx["invoice"] = invoice
    return ctx


def setup_disconnect_eligible_scenario(first_usage=2001, second_usage_register=2001):
    """Invoice 45 days past due, NOTICED, then advanced to DISCONNECT_ELIGIBLE.

    Chain: C1 billed (early due date) -> clock +10d -> issue-notice (NOTICED)
    -> clock +45d -> C2 billed (bill cascade advances C1's invoice) -> C2's
    fresh invoice paid in full so the tap's disconnect gate is unblocked.
    Returns dict with district, member, tap, cycle1, cycle2, invoice1, invoice2.
    """
    ctx = setup_billed_invoice(first_usage, due_date_utc=CYCLE_1_EARLY_DUE["due_date_utc"])
    district = ctx["district"]
    set_clock(CLOCK_DUE_PLUS_10D)
    get_success_data(api_client.issue_notice(district["id"], ctx["invoice"]["id"], CLERK))
    set_clock(CLOCK_DUE_PLUS_45D)
    cycle2 = open_cycle(district["id"], **CYCLE_2)
    bill_cycle_with_readings(district["id"], cycle2["id"], [(ctx["tap"]["id"], second_usage_register)])
    invoice1 = get_success_data(api_client.get_invoice(district["id"], ctx["invoice"]["id"], CLERK))
    invoice2 = get_cycle_invoice(district["id"], cycle2["id"])
    pay_invoice(district["id"], ctx["member"]["id"], invoice2["id"], invoice2["total_cents"])
    ctx.update({"cycle2": cycle2, "invoice1": invoice1, "invoice2": invoice2})
    return ctx


def setup_disconnected_tap_scenario(**kwargs):
    """Eligible scenario plus the disconnect: tap DISCONNECTED, member SUSPENDED."""
    ctx = setup_disconnect_eligible_scenario(**kwargs)
    district = ctx["district"]
    tap = get_success_data(api_client.disconnect_tap(district["id"], ctx["tap"]["id"], FIELD))
    ctx["tap"] = tap
    ctx["invoice1"] = get_success_data(
        api_client.get_invoice(district["id"], ctx["invoice1"]["id"], CLERK)
    )
    ctx["member"] = get_success_data(
        api_client.get_member(district["id"], ctx["member"]["id"], CLERK)
    )
    return ctx


# --- Tier 5: boil orders / annexation -------------------------------------

def issue_boil_order(district_id, at_iso=None, reason="Main break loss of pressure"):
    if at_iso is not None:
        set_clock(at_iso)
    return get_success_data(
        api_client.create_boil_order(district_id, create_boil_order_payload(reason=reason), FIELD),
        expected_status=201,
    )


def notify_member(district_id, order_id, member_id, channel="DOOR_HANGER"):
    return get_success_data(
        api_client.create_notification(
            district_id, order_id, create_notification_payload(member_id, channel=channel), FIELD
        ),
        expected_status=201,
    )


def collect_sample(district_id, order_id, collected_utc, sample_point="SP-1"):
    return get_success_data(
        api_client.create_compliance_sample(
            district_id,
            create_compliance_sample_payload(order_id, collected_utc, sample_point=sample_point),
            FIELD,
        ),
        expected_status=201,
    )


def create_petition(district_id, area_id, deposit_cents=100_000, **overrides):
    return get_success_data(
        api_client.create_annexation_petition(
            district_id,
            create_annexation_petition_payload(area_id, deposit_cents=deposit_cents, **overrides),
            CLERK,
        ),
        expected_status=201,
    )


def advance_petition_to_vote(district_id, petition_id):
    """SUBMITTED -> FEASIBILITY_REVIEW -> APPROVED_PENDING_VOTE."""
    get_success_data(api_client.begin_petition_review(district_id, petition_id, CLERK))
    return get_success_data(api_client.recommend_petition(district_id, petition_id, FIELD))
