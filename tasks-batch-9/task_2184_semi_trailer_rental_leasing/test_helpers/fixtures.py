"""Composite setup helpers.

The harness restarts the API server before every test, so each test begins
against an empty database.  Everything below therefore builds its
preconditions from scratch, using only endpoints the PRD declares.

The vocabulary used here mirrors the PRD: yards are branches, equipment
classes are trailer types, units are trailers, lessees are customers,
contracts are agreements and contract unit lines are agreement units.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    agreement_payload,
    branch_payload,
    customer_payload,
    damage_assessment_payload,
    east_branch_payload,
    insurance_certificate_payload,
    lease_agreement_payload,
    lease_rate_card_payload,
    maintenance_event_payload,
    rate_card_payload,
    relocation_order_payload,
    return_payload,
    trailer_payload,
    trailer_type_payload,
)
from .test_users import (
    APPROVER_USER_ID,
    INSPECTOR_USER_ID,
    TEST_USERS,
    make_approver_headers,
    make_branch_manager_headers,
    make_customer_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------- clock
def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock and return the answering payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ------------------------------------------------------- reference layer
def create_branch(**overrides) -> dict:
    return get_success_data(api_client.create_branch(branch_payload(**overrides), ADMIN))


def create_east_branch(**overrides) -> dict:
    return get_success_data(
        api_client.create_branch(east_branch_payload(**overrides), ADMIN)
    )


def create_trailer_type(**overrides) -> dict:
    return get_success_data(
        api_client.create_trailer_type(trailer_type_payload(**overrides), ADMIN)
    )


def read_branch(branch_id: str) -> dict:
    return get_success_data(api_client.get_branch(branch_id, ADMIN))


def read_trailer(trailer_id: str) -> dict:
    return get_success_data(api_client.get_trailer(trailer_id, ADMIN))


def read_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def read_agreement_unit(agreement_unit_id: str) -> dict:
    return get_success_data(api_client.get_agreement_unit(agreement_unit_id, ADMIN))


def read_damage_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_damage_assessment(assessment_id, ADMIN))


def read_chargeback(chargeback_id: str) -> dict:
    return get_success_data(api_client.get_chargeback(chargeback_id, ADMIN))


def read_relocation_order(order_id: str) -> dict:
    return get_success_data(api_client.get_relocation_order(order_id, ADMIN))


def publish_rate_card(branch_id: str, trailer_type_id: str, **overrides) -> dict:
    """Publish a card, reading the yard's current version for the guard."""
    branch = read_branch(branch_id)
    payload = rate_card_payload(branch_id, trailer_type_id, branch["version"], **overrides)
    return get_success_data(api_client.create_rate_card(payload, ADMIN))


def publish_lease_rate_card(branch_id: str, trailer_type_id: str, **overrides) -> dict:
    branch = read_branch(branch_id)
    payload = lease_rate_card_payload(
        branch_id, trailer_type_id, branch["version"], **overrides
    )
    return get_success_data(api_client.create_rate_card(payload, ADMIN))


def create_trailer(trailer_type_id: str, home_branch_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trailer(
            trailer_payload(trailer_type_id, home_branch_id, **overrides), ADMIN
        )
    )


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(customer_payload(**overrides), ADMIN))


def file_certificate(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_certificate(
            insurance_certificate_payload(customer_id, **overrides), ADMIN
        )
    )


# --------------------------------------------------- the standing fleet
def setup_reference_data(
    branch=None,
    trailer_type=None,
    rate_card=None,
    trailer=None,
    customer=None,
    certificate=None,
    with_rate_card=True,
    with_trailer=True,
    with_customer=True,
    with_certificate=True,
    lease_rate_card=False,
) -> dict:
    """One yard, one equipment class, one published card, one unit, one lessee
    and one certificate — the standing bootstrap almost every scenario needs.

    Every argument is an overrides dict passed straight to the matching factory.
    Returns a context dict whose keys the layered helpers below extend.
    """
    ctx = {}
    branch_row = create_branch(**(branch or {}))
    ctx["branch"] = branch_row
    ctx["branch_id"] = branch_row["id"]
    ctx["branch_manager_headers"] = make_branch_manager_headers(branch_row["id"])

    type_row = create_trailer_type(**(trailer_type or {}))
    ctx["trailer_type"] = type_row
    ctx["trailer_type_id"] = type_row["id"]

    if with_rate_card:
        publisher = publish_lease_rate_card if lease_rate_card else publish_rate_card
        card = publisher(branch_row["id"], type_row["id"], **(rate_card or {}))
        ctx["rate_card"] = card
        ctx["rate_card_id"] = card["id"]

    if with_trailer:
        trailer_row = create_trailer(type_row["id"], branch_row["id"], **(trailer or {}))
        ctx["trailer"] = trailer_row
        ctx["trailer_id"] = trailer_row["id"]

    if with_customer:
        customer_row = create_customer(**(customer or {}))
        ctx["customer"] = customer_row
        ctx["customer_id"] = customer_row["id"]
        ctx["customer_headers"] = make_customer_headers(customer_row["id"])
        if with_certificate:
            cert = file_certificate(customer_row["id"], **(certificate or {}))
            ctx["certificate"] = cert
            ctx["certificate_id"] = cert["id"]

    return ctx


def add_east_branch(ctx: dict, **overrides) -> dict:
    """Add a second yard so drop-offs and repositioning have somewhere to go."""
    branch_row = create_east_branch(**overrides)
    ctx["east_branch"] = branch_row
    ctx["east_branch_id"] = branch_row["id"]
    ctx["east_branch_manager_headers"] = make_branch_manager_headers(branch_row["id"])
    return branch_row


def add_branch(ctx: dict, key: str, **overrides) -> dict:
    """Add an arbitrarily named extra yard, keyed under `key` in the context."""
    branch_row = create_branch(**overrides)
    ctx[key] = branch_row
    ctx[key + "_id"] = branch_row["id"]
    ctx[key + "_manager_headers"] = make_branch_manager_headers(branch_row["id"])
    return branch_row


def add_trailer(ctx: dict, key: str, **overrides) -> dict:
    """Add another unit at the primary yard, keyed under `key` in the context."""
    trailer_row = create_trailer(ctx["trailer_type_id"], ctx["branch_id"], **overrides)
    ctx[key] = trailer_row
    ctx[key + "_id"] = trailer_row["id"]
    return trailer_row


def add_customer(ctx: dict, key: str, with_certificate=True,
                 certificate=None, **overrides) -> dict:
    """Add another lessee, keyed under `key` in the context."""
    customer_row = create_customer(**overrides)
    ctx[key] = customer_row
    ctx[key + "_id"] = customer_row["id"]
    ctx[key + "_headers"] = make_customer_headers(customer_row["id"])
    if with_certificate:
        cert = file_certificate(customer_row["id"], **(certificate or {}))
        ctx[key + "_certificate"] = cert
        ctx[key + "_certificate_id"] = cert["id"]
    return customer_row


# ------------------------------------------------------ contract lifecycle
def open_agreement(ctx: dict, as_customer=False, lease=False, **overrides) -> dict:
    """Open a draft contract at the context's yard for the context's lessee."""
    builder = lease_agreement_payload if lease else agreement_payload
    payload = builder(ctx["customer_id"], ctx["branch_id"], ctx["trailer_type_id"],
                      **overrides)
    headers = ctx["customer_headers"] if as_customer else ADMIN
    return get_success_data(api_client.create_agreement(payload, headers))


def submit_for_underwriting(ctx: dict, agreement_id: str, as_customer=False) -> dict:
    headers = ctx["customer_headers"] if as_customer else ADMIN
    return get_success_data(api_client.submit_agreement(agreement_id, headers))


def verify_insurance(ctx: dict, agreement_id: str, as_branch_manager=False) -> dict:
    headers = ctx["branch_manager_headers"] if as_branch_manager else ADMIN
    return get_success_data(api_client.verify_agreement_insurance(agreement_id, headers))


def setup_agreement_pending_allocation(ctx=None, as_customer=False, lease=False,
                                       reference=None, **overrides) -> dict:
    """Open a contract, submit it for underwriting and verify its insurance, so
    it sits in PENDING_ALLOCATION with no units attached.

    Returns a scenario dict: every reference-layer key plus `agreement`,
    `agreement_id` and `agreement_version`.
    """
    scn = dict(ctx if ctx is not None else setup_reference_data(**(reference or {})))
    agreement = open_agreement(scn, as_customer=as_customer, lease=lease, **overrides)
    submit_for_underwriting(scn, agreement["id"], as_customer=as_customer)
    agreement = verify_insurance(scn, agreement["id"])
    scn["agreement"] = agreement
    scn["agreement_id"] = agreement["id"]
    scn["agreement_version"] = agreement["version"]
    return scn


def allocate_agreement(scn: dict, expected_version=None, as_branch_manager=False) -> dict:
    headers = scn["branch_manager_headers"] if as_branch_manager else ADMIN
    version = expected_version if expected_version is not None else scn["agreement_version"]
    agreement = get_success_data(
        api_client.allocate_agreement(
            scn["agreement_id"], {"expected_agreement_version": version}, headers
        )
    )
    scn["agreement"] = agreement
    scn["agreement_version"] = agreement["version"]
    return agreement


def attach_unit(scn: dict, trailer_id: str, expected_version=None,
                as_branch_manager=False) -> dict:
    headers = scn["branch_manager_headers"] if as_branch_manager else ADMIN
    version = expected_version if expected_version is not None else scn["agreement_version"]
    unit = get_success_data(
        api_client.attach_agreement_unit(
            scn["agreement_id"],
            {"trailer_id": trailer_id, "expected_agreement_version": version},
            headers,
        )
    )
    scn["agreement"] = read_agreement(scn["agreement_id"])
    scn["agreement_version"] = scn["agreement"]["version"]
    return unit


def setup_agreement_reserved(ctx=None, lease=False, reference=None, **overrides) -> dict:
    """Run the server-side selector so the contract reaches RESERVED with a
    pinned rate card and a written quote."""
    scn = setup_agreement_pending_allocation(
        ctx=ctx, lease=lease, reference=reference, **overrides
    )
    allocate_agreement(scn)
    return scn


def list_units(agreement_id=None, trailer_id=None, headers=None, **extra) -> list:
    params = dict(extra)
    if agreement_id:
        params["agreement_id"] = agreement_id
    if trailer_id:
        params["trailer_id"] = trailer_id
    response = api_client.list_agreement_units(headers or ADMIN, params=params)
    return get_success_data(response)


def setup_agreement_active(ctx=None, lease=False, reference=None,
                           checkout_date=None, **overrides) -> dict:
    """Check the reserved units out of the yard, so the contract is ACTIVE and
    every line is OUT."""
    scn = setup_agreement_reserved(ctx=ctx, lease=lease, reference=reference, **overrides)
    date = checkout_date or scn["agreement"]["start_date"]
    agreement = get_success_data(
        api_client.activate_agreement(
            scn["agreement_id"], {"checkout_date": date}, ADMIN
        )
    )
    scn["agreement"] = agreement
    scn["agreement_version"] = agreement["version"]
    scn["checkout_date"] = date
    units = list_units(agreement_id=scn["agreement_id"])
    scn["units"] = units
    scn["unit"] = units[0]
    scn["unit_id"] = units[0]["id"]
    return scn


def return_unit(scn: dict, unit_id=None, return_branch_id=None, **overrides) -> dict:
    """Accept a unit back.  The acting BranchManager is the yard receiving it."""
    branch_id = return_branch_id or scn["branch_id"]
    payload = return_payload(branch_id, **overrides)
    unit = get_success_data(
        api_client.return_agreement_unit(
            unit_id or scn["unit_id"], payload, make_branch_manager_headers(branch_id)
        )
    )
    return unit


def setup_returned_unit(ctx=None, lease=False, reference=None, checkout_date=None,
                        return_branch_id=None, return_overrides=None, **overrides) -> dict:
    """Full run to a unit accepted back into a yard: the line is RETURNED and the
    contract has bubbled up to PENDING_SETTLEMENT.

    Adds `unit`, `unit_id` and `unit_version` to the scenario dict.
    """
    scn = setup_agreement_active(
        ctx=ctx, lease=lease, reference=reference, checkout_date=checkout_date, **overrides
    )
    unit = return_unit(
        scn, return_branch_id=return_branch_id, **(return_overrides or {})
    )
    scn["unit"] = unit
    scn["unit_id"] = unit["id"]
    scn["unit_version"] = unit["version"]
    scn["agreement"] = read_agreement(scn["agreement_id"])
    scn["agreement_version"] = scn["agreement"]["version"]
    return scn


def settle_agreement(scn: dict) -> dict:
    agreement = get_success_data(api_client.settle_agreement(scn["agreement_id"], ADMIN))
    scn["agreement"] = agreement
    scn["agreement_version"] = agreement["version"]
    return agreement


# ------------------------------------------------ damage recovery lifecycle
def open_assessment(scn: dict, line_items=None, unit_id=None, unit_version=None,
                    inspector_user_id=INSPECTOR_USER_ID, **overrides) -> dict:
    """Open a draft damage assessment against a contract unit line.

    Reads the line's live version for the guard unless one is supplied.
    """
    target_unit_id = unit_id or scn["unit_id"]
    version = unit_version
    if version is None:
        version = read_agreement_unit(target_unit_id)["version"]
    payload = damage_assessment_payload(version, line_items=line_items, **overrides)
    assessment = get_success_data(
        api_client.create_damage_assessment(
            target_unit_id, payload, make_inspector_headers(inspector_user_id)
        )
    )
    return assessment


def submit_assessment(assessment_id: str,
                      inspector_user_id=INSPECTOR_USER_ID) -> dict:
    return get_success_data(
        api_client.submit_damage_assessment(
            assessment_id, make_inspector_headers(inspector_user_id)
        )
    )


def find_chargeback(damage_assessment_id: str) -> dict:
    rows = get_success_data(
        api_client.list_chargebacks(
            ADMIN, params={"damage_assessment_id": damage_assessment_id}
        )
    )
    assert rows, f"expected a chargeback for assessment {damage_assessment_id}"
    return rows[0]


def setup_draft_assessment(ctx=None, line_items=None, reference=None,
                           inspector_user_id=INSPECTOR_USER_ID,
                           return_branch_id=None, **overrides) -> dict:
    """A returned unit carrying one DRAFT damage assessment.

    Adds `assessment` and `assessment_id` to the scenario dict.
    """
    scn = setup_returned_unit(
        ctx=ctx, reference=reference, return_branch_id=return_branch_id, **overrides
    )
    assessment = open_assessment(
        scn, line_items=line_items, unit_version=scn["unit_version"],
        inspector_user_id=inspector_user_id,
    )
    scn["assessment"] = assessment
    scn["assessment_id"] = assessment["id"]
    return scn


def setup_pending_chargeback(ctx=None, line_items=None, reference=None,
                             inspector_user_id=INSPECTOR_USER_ID,
                             return_branch_id=None, **overrides) -> dict:
    """Submit the assessment so it prices the damage and raises a PENDING
    chargeback.

    Adds `chargeback`, `chargeback_id` and `chargeback_amount` to the scenario.
    """
    scn = setup_draft_assessment(
        ctx=ctx, line_items=line_items, reference=reference,
        inspector_user_id=inspector_user_id, return_branch_id=return_branch_id,
        **overrides
    )
    scn["assessment"] = submit_assessment(scn["assessment_id"], inspector_user_id)
    chargeback = find_chargeback(scn["assessment_id"])
    scn["chargeback"] = chargeback
    scn["chargeback_id"] = chargeback["id"]
    scn["chargeback_amount"] = chargeback["amount_cents"]
    return scn


def setup_approved_chargeback(ctx=None, line_items=None, reference=None,
                              approver_user_id=APPROVER_USER_ID,
                              inspector_user_id=INSPECTOR_USER_ID, **overrides) -> dict:
    """Push the chargeback through adjudication so it stands APPROVED and its
    assessment stands APPROVED with it."""
    scn = setup_pending_chargeback(
        ctx=ctx, line_items=line_items, reference=reference,
        inspector_user_id=inspector_user_id, **overrides
    )
    scn["chargeback"] = get_success_data(
        api_client.approve_chargeback(
            scn["chargeback_id"], make_approver_headers(approver_user_id)
        )
    )
    return scn


# ------------------------------------------------ repositioning lifecycle
def request_relocation(scn: dict, trailer_id=None, destination_branch_id=None,
                       requester_branch_id=None, **overrides) -> dict:
    origin = requester_branch_id or scn["branch_id"]
    payload = relocation_order_payload(
        trailer_id or scn["trailer_id"],
        destination_branch_id or scn["east_branch_id"],
        **overrides
    )
    return get_success_data(
        api_client.create_relocation_order(payload, make_branch_manager_headers(origin))
    )


def setup_relocation_requested(ctx=None, reference=None, **overrides) -> dict:
    """One idle unit at the primary yard and a REQUESTED move to a second yard.

    Adds `east_branch_id`, `order`, `order_id` and `order_estimate` to the context.
    """
    scn = dict(ctx if ctx is not None else setup_reference_data(**(reference or {})))
    if "east_branch_id" not in scn:
        add_east_branch(scn)
    order = request_relocation(scn, **overrides)
    scn["order"] = order
    scn["order_id"] = order["id"]
    scn["order_estimate"] = order["estimated_cost_cents"]
    return scn


def approve_relocation(scn: dict, order_id=None, destination_branch_id=None) -> dict:
    dest = destination_branch_id or scn["east_branch_id"]
    order = get_success_data(
        api_client.approve_relocation_order(
            order_id or scn["order_id"], make_branch_manager_headers(dest)
        )
    )
    scn["order"] = order
    return order


def setup_relocation_approved(ctx=None, reference=None, **overrides) -> dict:
    scn = setup_relocation_requested(ctx=ctx, reference=reference, **overrides)
    approve_relocation(scn)
    return scn


def setup_relocation_in_transit(ctx=None, reference=None, **overrides) -> dict:
    scn = setup_relocation_approved(ctx=ctx, reference=reference, **overrides)
    scn["order"] = get_success_data(
        api_client.dispatch_relocation_order(
            scn["order_id"], make_branch_manager_headers(scn["branch_id"])
        )
    )
    return scn


# ------------------------------------------------------------ shop events
def file_maintenance_event(trailer_id: str, event_type="PM_SERVICE",
                           inspector_user_id=INSPECTOR_USER_ID, **overrides) -> dict:
    payload = maintenance_event_payload(trailer_id, event_type=event_type, **overrides)
    return get_success_data(
        api_client.create_maintenance_event(
            payload, make_inspector_headers(inspector_user_id)
        )
    )


def fail_dot_inspection(trailer_id: str, performed_on="2026-08-10",
                        hub_miles_at_event=None, cost_cents=9500,
                        **overrides) -> dict:
    """File a failed federal periodic inspection — the head of the deepest cascade."""
    return file_maintenance_event(
        trailer_id,
        event_type="DOT_INSPECTION",
        performed_on=performed_on,
        hub_miles_at_event=(
            hub_miles_at_event if hub_miles_at_event is not None
            else TEST_DEFAULTS["TRAILER_HUB_MILES"]
        ),
        passed=False,
        cost_cents=cost_cents,
        **overrides
    )


# ---------------------------------------------- lease-end purchase option
def setup_settled_lease_with_purchase_option() -> dict:
    """A single-unit full-service lease running 2024-09-01 to 2026-09-01 (730
    days), returned to its own yard at 200000 hub miles with the logical clock
    moved to 2026-09-01, then settled — so the lease-end option is OFFERED.
    """
    ctx = setup_reference_data(
        trailer={"unit_number": "T-3001"},
        lease_rate_card=True,
    )
    scn = setup_agreement_active(ctx=ctx, lease=True, checkout_date="2024-09-01")
    unit = return_unit(
        scn, return_hub_miles=200_000, return_date="2026-09-01"
    )
    scn["unit"] = unit
    scn["unit_id"] = unit["id"]
    scn["unit_version"] = unit["version"]
    set_clock("2026-09-01T00:00:00Z")
    scn["trailer_at_settlement"] = read_trailer(scn["trailer_id"])
    settle_agreement(scn)
    return scn
