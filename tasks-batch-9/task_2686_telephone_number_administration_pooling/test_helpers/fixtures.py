"""Composite setup helpers.

Every helper drives the real API through the same endpoints a client would use,
and returns the server's own view of the rows it created. Setup calls go through
the lenient success reader so a broken precondition surfaces as a setup failure
rather than as a confusing assertion deep inside a test.

Identity threading: CarrierRepresentative is matched against Carrier.id, so
every ownership-gated call below builds its headers from the carrier's real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    CARRIER_PROFILES,
    create_allocation_request_payload,
    create_block_payload,
    create_carrier_payload,
    create_npa_payload,
    create_port_request_payload,
    create_public_comment_payload,
    create_rate_center_payload,
    create_utilization_filing_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    PORTING_HEADERS,
    make_carrier_representative_headers,
)

# --- logical clock -----------------------------------------------------------


def set_clock(current_utc: str = DEFAULT_CLOCK) -> None:
    """Pin the server's logical clock. Mutates no domain row."""
    get_success_data(api_client.set_clock(current_utc, ADMIN_HEADERS))


# --- carriers ----------------------------------------------------------------


def register_carrier(profile: str = "A", **overrides) -> dict:
    """Register a carrier. It opens with no licence and unsubmitted readiness."""
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(profile, **overrides), ADMIN_HEADERS)
    )


def grant_license(carrier: dict, license_expires_on: str = None) -> dict:
    return get_success_data(
        api_client.create_license_action(
            carrier["id"],
            {
                "action": "GRANT",
                "license_expires_on": license_expires_on
                or TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
            },
            ADMIN_HEADERS,
        )
    )


def license_action(carrier: dict, action: str, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.create_license_action(carrier["id"], body, ADMIN_HEADERS)
    )


def attest_readiness(carrier: dict, switch_clli: str = None,
                     interconnection_ready: bool = True) -> dict:
    """The carrier itself attests; the call is ownership gated."""
    return get_success_data(
        api_client.create_readiness_event(
            carrier["id"],
            {
                "event": "ATTEST",
                "switch_clli": switch_clli or TEST_DEFAULTS["SWITCH_CLLI_A"],
                "interconnection_ready": interconnection_ready,
            },
            make_carrier_representative_headers(carrier["id"]),
        )
    )


def verify_readiness(carrier: dict) -> dict:
    return get_success_data(
        api_client.create_readiness_event(carrier["id"], {"event": "VERIFY"}, ADMIN_HEADERS)
    )


def fail_readiness(carrier: dict) -> dict:
    return get_success_data(
        api_client.create_readiness_event(carrier["id"], {"event": "FAIL"}, ADMIN_HEADERS)
    )


def create_eligible_carrier(profile: str = "A", switch_clli: str = None,
                            license_expires_on: str = None, **overrides) -> dict:
    """Register, grant a licence, attest and verify readiness.

    The result reads eligibility_status ELIGIBLE, which is what every allocation
    approval requires.
    """
    carrier = register_carrier(profile, **overrides)
    grant_license(carrier, license_expires_on=license_expires_on)
    attest_readiness(
        carrier,
        switch_clli=switch_clli
        or {"A": TEST_DEFAULTS["SWITCH_CLLI_A"],
            "B": TEST_DEFAULTS["SWITCH_CLLI_B"],
            "C": TEST_DEFAULTS["SWITCH_CLLI_C"]}.get(profile, TEST_DEFAULTS["SWITCH_CLLI_A"]),
    )
    verify_readiness(carrier)
    return read_carrier(carrier["id"])


def create_licensed_carrier(profile: str = "A", license_expires_on: str = None,
                            **overrides) -> dict:
    """Register and grant a licence only -- readiness stays NOT_SUBMITTED."""
    carrier = register_carrier(profile, **overrides)
    grant_license(carrier, license_expires_on=license_expires_on)
    return read_carrier(carrier["id"])


def read_carrier(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, ADMIN_HEADERS))


# --- inventory ---------------------------------------------------------------


def create_npa(npa_code: str = None, state_code: str = None, npa_type: str = None) -> dict:
    payload = create_npa_payload(
        npa_code=npa_code or TEST_DEFAULTS["NPA_CODE"],
        state_code=state_code or TEST_DEFAULTS["STATE_CODE"],
    )
    if npa_type is None:
        payload.pop("npa_type", None)
    else:
        payload["npa_type"] = npa_type
    return get_success_data(api_client.create_npa(payload, ADMIN_HEADERS))


def create_rate_center(npa: dict, name: str = None, state_code: str = None,
                       lata_code: str = None) -> dict:
    payload = create_rate_center_payload(
        npa["id"],
        name=name or TEST_DEFAULTS["RATE_CENTER_NAME"],
        state_code=state_code or TEST_DEFAULTS["STATE_CODE"],
        lata_code=lata_code or TEST_DEFAULTS["LATA_CODE"],
    )
    return get_success_data(api_client.create_rate_center(payload, ADMIN_HEADERS))


def read_rate_center(rate_center_id: str) -> dict:
    return get_success_data(api_client.get_rate_center(rate_center_id, ADMIN_HEADERS))


def read_npa(npa_id: str) -> dict:
    return get_success_data(api_client.get_npa(npa_id, ADMIN_HEADERS))


def read_block(block_id: str) -> dict:
    return get_success_data(api_client.get_block(block_id, ADMIN_HEADERS))


def setup_npa_with_rate_center(npa_code: str = None, rate_center_name: str = None,
                               state_code: str = None, lata_code: str = None):
    """One area code with one rate center under it. Returns (npa, rate_center)."""
    npa = create_npa(npa_code=npa_code, state_code=state_code, npa_type="GEOGRAPHIC")
    rate_center = create_rate_center(
        npa, name=rate_center_name, state_code=state_code, lata_code=lata_code
    )
    return npa, rate_center


def load_block(npa: dict, rate_center: dict, nxx_code: str = "554",
               thousands_digit: int = 0, contaminated_count: int = None,
               holder_carrier_id: str = None, mark_activated: bool = None) -> dict:
    """Load one thousand-block into the inventory.

    With no holder the block opens POOL_AVAILABLE. With a holder it opens
    RESERVED and, when mark_activated is true, ASSIGNED.
    """
    payload = create_block_payload(npa["id"], rate_center["id"], nxx_code, thousands_digit)
    if contaminated_count is not None:
        payload["contaminated_count"] = contaminated_count
    if holder_carrier_id is not None:
        payload["holder_carrier_id"] = holder_carrier_id
    if mark_activated is not None:
        payload["mark_activated"] = mark_activated
    return get_success_data(api_client.create_block(payload, ADMIN_HEADERS))


def load_pool_blocks(npa: dict, rate_center: dict, count: int, nxx_code: str = "556",
                     first_thousands_digit: int = 0) -> list:
    """Load `count` pristine unheld blocks, one per consecutive thousands digit."""
    return [
        load_block(npa, rate_center, nxx_code=nxx_code,
                   thousands_digit=first_thousands_digit + offset)
        for offset in range(count)
    ]


def load_held_blocks(npa: dict, rate_center: dict, carrier: dict, count: int,
                     nxx_code: str = "555", first_thousands_digit: int = 0,
                     mark_activated: bool = True) -> list:
    """Load `count` blocks already held by `carrier`."""
    return [
        load_block(npa, rate_center, nxx_code=nxx_code,
                   thousands_digit=first_thousands_digit + offset,
                   holder_carrier_id=carrier["id"], mark_activated=mark_activated)
        for offset in range(count)
    ]


def declare_jeopardy(npa: dict, reason: str = "Exhaust projected inside four quarters") -> dict:
    return get_success_data(
        api_client.declare_jeopardy(npa["id"], {"reason": reason}, ADMIN_HEADERS)
    )


def pooling_transition(rate_center: dict, action: str, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.create_pooling_transition(rate_center["id"], body, ADMIN_HEADERS)
    )


def make_rate_center_pooled(rate_center: dict) -> dict:
    """Walk the pooling axis NON_POOLED -> TRANSITIONAL -> POOLED."""
    pooling_transition(rate_center, "BEGIN_POOLING")
    return pooling_transition(rate_center, "COMPLETE_POOLING")


# --- utilization filings and audits ------------------------------------------


def create_filing(carrier: dict, rate_center: dict, **counts) -> dict:
    """Create a DRAFT utilization filing owned by the carrier."""
    payload = create_utilization_filing_payload(carrier["id"], rate_center["id"], **counts)
    return get_success_data(
        api_client.create_utilization_filing(
            payload, make_carrier_representative_headers(carrier["id"])
        )
    )


def submit_filing(carrier: dict, filing: dict, amendment_note: str = None) -> dict:
    payload = {} if amendment_note is None else {"amendment_note": amendment_note}
    return get_success_data(
        api_client.create_filing_submission(
            filing["id"], payload, make_carrier_representative_headers(carrier["id"])
        )
    )


def create_submitted_filing(carrier: dict, rate_center: dict, **counts) -> dict:
    """Create and submit a filing, so it becomes the carrier's effective filing."""
    filing = create_filing(carrier, rate_center, **counts)
    return submit_filing(carrier, filing)


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_utilization_filing(filing_id, ADMIN_HEADERS))


def open_audit_finding(filing: dict, finding_type: str = "OVERSTATED_UTILIZATION",
                       adjusted_numbers_assigned: int = None,
                       adjusted_numbers_administrative: int = None,
                       auditor_headers: dict = None) -> dict:
    """Open a finding against a submitted filing, moving it to UNDER_AUDIT."""
    payload = {"finding_type": finding_type}
    if adjusted_numbers_assigned is not None:
        payload["adjusted_numbers_assigned"] = adjusted_numbers_assigned
    if adjusted_numbers_administrative is not None:
        payload["adjusted_numbers_administrative"] = adjusted_numbers_administrative
    return get_success_data(
        api_client.create_audit_finding(
            filing["id"], payload, auditor_headers or ADMIN_HEADERS
        )
    )


def dispose_finding(finding: dict, disposition: str = "ACCEPT",
                    disposition_note: str = "Finding stands",
                    approver_headers: dict = None) -> dict:
    """The approver accepts or rejects a finding. Must not be the auditor."""
    return get_success_data(
        api_client.create_disposition(
            finding["id"],
            {"disposition": disposition, "disposition_note": disposition_note},
            approver_headers or APPROVER_HEADERS,
        )
    )


def read_finding(finding_id: str) -> dict:
    return get_success_data(api_client.get_audit_finding(finding_id, ADMIN_HEADERS))


def put_carrier_on_probation(carrier: dict, rate_center: dict,
                            numbers_assigned: int = 1600,
                            adjusted_numbers_assigned: int = 1500,
                            blocks_held_at_period_end: int = 2,
                            forecast_quarters=None,
                            reporting_period: str = None) -> dict:
    """Drive the audit programme until the carrier reads PROBATION.

    Files and submits a utilization filing, opens an overstatement finding whose
    delta earns a probation penalty, and accepts it. Returns the filing as the
    server last reported it.
    """
    filing = create_submitted_filing(
        carrier,
        rate_center,
        numbers_assigned=numbers_assigned,
        numbers_intermediate=0,
        numbers_reserved=0,
        numbers_aging=0,
        numbers_administrative=0,
        blocks_held_at_period_end=blocks_held_at_period_end,
        forecast_quarters=forecast_quarters if forecast_quarters is not None
        else [1500, 1500, 1500, 1500],
        reporting_period=reporting_period,
    )
    finding = open_audit_finding(
        filing,
        finding_type="OVERSTATED_UTILIZATION",
        adjusted_numbers_assigned=adjusted_numbers_assigned,
    )
    dispose_finding(finding, "ACCEPT")
    return read_filing(filing["id"])


# --- allocation requests -----------------------------------------------------


def rate_center_version(rate_center_id: str) -> int:
    """Read the rate center's current version for the optimistic-concurrency field."""
    return read_rate_center(rate_center_id)["version"]


def file_allocation_request(carrier: dict, rate_center: dict,
                            request_type: str = "GROWTH",
                            requested_block_count: int = 1,
                            justification: str = "Growth demand in COLUMBUS",
                            expected_rate_center_version: int = None) -> dict:
    """File a resource request as the applicant carrier.

    The rate center version is re-read immediately before the write unless the
    caller pins it, because every accepted request bumps that version.
    """
    payload = create_allocation_request_payload(
        carrier["id"],
        rate_center["id"],
        expected_rate_center_version
        if expected_rate_center_version is not None
        else rate_center_version(rate_center["id"]),
        request_type=request_type,
        requested_block_count=requested_block_count,
        justification=justification,
    )
    return get_success_data(
        api_client.create_allocation_request(
            payload, make_carrier_representative_headers(carrier["id"])
        )
    )


def review_request(request: dict, action: str, headers: dict, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(api_client.create_review(request["id"], body, headers))


def approve_request(request: dict, approver_headers: dict = None,
                    granted_block_count: int = None) -> dict:
    payload = {}
    if granted_block_count is not None:
        payload["granted_block_count"] = granted_block_count
    return review_request(
        request, "APPROVE", approver_headers or APPROVER_HEADERS, **payload
    )


def request_info(request: dict, info_note: str = "please attach the switch inventory",
                 headers: dict = None) -> dict:
    return review_request(
        request, "REQUEST_INFO", headers or ADMIN_HEADERS, info_note=info_note
    )


def resubmit_request(request: dict, carrier: dict, revised_requested_block_count: int = 1,
                     response_note: str = "switch inventory attached") -> dict:
    return get_success_data(
        api_client.create_resubmission(
            request["id"],
            {
                "revised_requested_block_count": revised_requested_block_count,
                "response_note": response_note,
            },
            make_carrier_representative_headers(carrier["id"]),
        )
    )


def read_request(request_id: str) -> dict:
    return get_success_data(api_client.get_allocation_request(request_id, ADMIN_HEADERS))


# --- routing and porting -----------------------------------------------------


def publish_routing_record(block: dict, lrn: str = "6145560000", switch_clli: str = None,
                           effective_at: str = DEFAULT_CLOCK,
                           expected_block_version: int = None) -> dict:
    """Publish routing data for a block, re-reading the block version first."""
    payload = {
        "lrn": lrn,
        "switch_clli": switch_clli or TEST_DEFAULTS["SWITCH_CLLI_A"],
        "effective_at": effective_at,
        "expected_block_version": expected_block_version
        if expected_block_version is not None
        else read_block(block["id"])["version"],
    }
    return get_success_data(
        api_client.create_routing_record(block["id"], payload, ADMIN_HEADERS)
    )


def read_routing_records(block_id: str) -> list:
    return get_success_data(
        api_client.list_block_routing_records(block_id, ADMIN_HEADERS)
    )


def confirm_activation(block: dict, carrier: dict, activated_number_count: int = None) -> dict:
    """The holding carrier confirms the block is in service."""
    payload = {}
    if activated_number_count is not None:
        payload["activated_number_count"] = activated_number_count
    return get_success_data(
        api_client.create_activation_confirmation(
            block["id"], payload, make_carrier_representative_headers(carrier["id"])
        )
    )


def file_port_request(block: dict, from_carrier: dict, to_carrier: dict,
                      telephone_number: str, requested_lrn: str = "6145570000",
                      desired_due_at: str = "2026-09-15T00:00:00Z") -> dict:
    """The gaining carrier files the port; the call is ownership gated on it."""
    payload = create_port_request_payload(
        telephone_number,
        block["id"],
        from_carrier["id"],
        to_carrier["id"],
        requested_lrn=requested_lrn,
        desired_due_at=desired_due_at,
    )
    return get_success_data(
        api_client.create_port_request(
            payload, make_carrier_representative_headers(to_carrier["id"])
        )
    )


def port_transition(port_request: dict, action: str, headers: dict, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.create_port_transition(port_request["id"], body, headers)
    )


def concur_port_request(port_request: dict, from_carrier: dict) -> dict:
    return port_transition(
        port_request, "CONCUR", make_carrier_representative_headers(from_carrier["id"])
    )


def activate_port_request(port_request: dict) -> dict:
    return port_transition(port_request, "ACTIVATE", PORTING_HEADERS)


def read_port_request(port_request_id: str) -> dict:
    return get_success_data(api_client.get_port_request(port_request_id, ADMIN_HEADERS))


# --- relief planning ---------------------------------------------------------


def create_relief_plan(npa: dict, planned_relief_type: str = "UNDETERMINED",
                       comment_window_days: int = None, new_npa_code: str = None,
                       effective_at: str = None) -> dict:
    payload = {"planned_relief_type": planned_relief_type}
    if comment_window_days is not None:
        payload["comment_window_days"] = comment_window_days
    if new_npa_code is not None:
        payload["new_npa_code"] = new_npa_code
    if effective_at is not None:
        payload["effective_at"] = effective_at
    return get_success_data(
        api_client.create_relief_plan(npa["id"], payload, ADMIN_HEADERS)
    )


def relief_transition(plan: dict, action: str, headers: dict = None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.create_relief_transition(plan["id"], body, headers or ADMIN_HEADERS)
    )


def open_comment_window(plan: dict) -> dict:
    return relief_transition(plan, "OPEN_COMMENT")


def close_and_recommend(plan: dict, headers: dict = None) -> dict:
    return relief_transition(plan, "CLOSE_AND_RECOMMEND", headers)


def file_comment(plan: dict, commenter_type: str = "CONSUMER",
                 position: str = "SUPPORT_OVERLAY",
                 body: str = "Please keep our existing numbers.",
                 headers: dict = None) -> dict:
    from .test_users import COMMENTER_HEADERS

    payload = create_public_comment_payload(commenter_type, position, body)
    return get_success_data(
        api_client.create_public_comment(
            plan["id"], payload, headers or COMMENTER_HEADERS
        )
    )


def read_relief_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_relief_plan(plan_id, ADMIN_HEADERS))


def setup_plan_in_public_comment(comment_window_days: int = None,
                                 planned_relief_type: str = "UNDETERMINED",
                                 npa_code: str = None):
    """An area code declared in jeopardy with an open comment window on its plan.

    Returns (npa, plan) with the plan read back after the window opened.
    """
    npa = create_npa(npa_code=npa_code, npa_type="GEOGRAPHIC")
    declare_jeopardy(npa)
    plan = create_relief_plan(
        npa, planned_relief_type=planned_relief_type,
        comment_window_days=comment_window_days,
    )
    plan = open_comment_window(plan)
    return npa, plan


# --- reclamation -------------------------------------------------------------


def run_sweep(rate_center_id: str = None, reason_filter: str = None) -> dict:
    payload = {}
    if rate_center_id is not None:
        payload["rate_center_id"] = rate_center_id
    if reason_filter is not None:
        payload["reason_filter"] = reason_filter
    return get_success_data(api_client.create_reclamation_sweep(payload, ADMIN_HEADERS))


def list_orders(**params) -> list:
    return get_success_data(
        api_client.list_reclamation_orders(ADMIN_HEADERS, params=params or None)
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_reclamation_order(order_id, ADMIN_HEADERS))


def reclamation_transition(order: dict, action: str, headers: dict = None, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.create_reclamation_transition(
            order["id"], body, headers or ADMIN_HEADERS
        )
    )


def surrender_order(order: dict, carrier: dict) -> dict:
    return reclamation_transition(
        order, "SURRENDER", make_carrier_representative_headers(carrier["id"])
    )


def execute_order(order: dict) -> dict:
    return reclamation_transition(order, "EXECUTE", ADMIN_HEADERS)


# --- composite scenarios -----------------------------------------------------


def setup_eligible_carrier_with_inventory(profile: str = "A", pool_block_count: int = 1,
                                         held_block_count: int = 0,
                                         pooled: bool = False,
                                         clock: str = DEFAULT_CLOCK,
                                         pool_nxx: str = "556",
                                         held_nxx: str = "555",
                                         sibling_rate_center: bool = False):
    """The spine every allocation scenario starts from.

    Pins the clock, brings one carrier to ELIGIBLE, opens area code 614 with the
    COLUMBUS rate center, optionally completes the pooling transition before any
    block is loaded, then loads the held and pooled blocks.

    Returns a dict with carrier, npa, rate_center, sibling, held_blocks and
    pool_blocks.
    """
    set_clock(clock)
    carrier = create_eligible_carrier(profile)
    npa, rate_center = setup_npa_with_rate_center()
    sibling = (
        create_rate_center(npa, name=TEST_DEFAULTS["SIBLING_RATE_CENTER_NAME"])
        if sibling_rate_center
        else None
    )
    if pooled:
        make_rate_center_pooled(rate_center)
    held_blocks = (
        load_held_blocks(npa, rate_center, carrier, held_block_count, nxx_code=held_nxx)
        if held_block_count
        else []
    )
    pool_blocks = (
        load_pool_blocks(npa, rate_center, pool_block_count, nxx_code=pool_nxx)
        if pool_block_count
        else []
    )
    return {
        "carrier": carrier,
        "npa": npa,
        "rate_center": rate_center,
        "sibling": sibling,
        "held_blocks": held_blocks,
        "pool_blocks": pool_blocks,
    }


def setup_pending_allocation_request(profile: str = "A",
                                     request_type: str = "GROWTH",
                                     requested_block_count: int = 1,
                                     pool_block_count: int = 1,
                                     held_block_count: int = 5,
                                     pooled: bool = False,
                                     numbers_assigned: int = 2500,
                                     numbers_intermediate: int = 400,
                                     numbers_reserved: int = 200,
                                     numbers_aging: int = 300,
                                     numbers_administrative: int = 200,
                                     blocks_held_at_period_end: int = 5,
                                     forecast_quarters=(1800, 1200, 900, 600),
                                     clock: str = DEFAULT_CLOCK,
                                     sibling_rate_center: bool = False,
                                     justification: str = "Growth demand in COLUMBUS"):
    """A submitted utilization filing plus one request awaiting review.

    Returns the spine dict from setup_eligible_carrier_with_inventory with
    filing and request added.
    """
    scenario = setup_eligible_carrier_with_inventory(
        profile=profile,
        pool_block_count=pool_block_count,
        held_block_count=held_block_count,
        pooled=pooled,
        clock=clock,
        sibling_rate_center=sibling_rate_center,
    )
    scenario["filing"] = create_submitted_filing(
        scenario["carrier"],
        scenario["rate_center"],
        numbers_assigned=numbers_assigned,
        numbers_intermediate=numbers_intermediate,
        numbers_reserved=numbers_reserved,
        numbers_aging=numbers_aging,
        numbers_administrative=numbers_administrative,
        blocks_held_at_period_end=blocks_held_at_period_end,
        forecast_quarters=list(forecast_quarters),
    )
    scenario["request"] = file_allocation_request(
        scenario["carrier"],
        scenario["rate_center"],
        request_type=request_type,
        requested_block_count=requested_block_count,
        justification=justification,
    )
    return scenario


def setup_reserved_block(profile: str = "A", clock: str = DEFAULT_CLOCK,
                         mark_activated: bool = False, block_count: int = 1,
                         nxx_code: str = "555"):
    """One eligible carrier holding `block_count` blocks it has never activated.

    Returns (carrier, npa, rate_center, blocks).
    """
    set_clock(clock)
    carrier = create_eligible_carrier(profile)
    npa, rate_center = setup_npa_with_rate_center()
    blocks = load_held_blocks(
        npa, rate_center, carrier, block_count, nxx_code=nxx_code,
        mark_activated=mark_activated,
    )
    return carrier, npa, rate_center, blocks


def setup_activation_deadline_order(sweep_at: str = "2027-01-29T00:00:00Z",
                                    profile: str = "A"):
    """A block that missed its activation deadline and the order the sweep issued.

    Returns (carrier, npa, rate_center, block, order).
    """
    carrier, npa, rate_center, blocks = setup_reserved_block(profile=profile)
    set_clock(sweep_at)
    run_sweep()
    orders = list_orders(number_block_id=blocks[0]["id"])
    return carrier, npa, rate_center, read_block(blocks[0]["id"]), orders[0]


def setup_routed_assigned_block(profile: str = "A", lrn: str = "6145580000",
                                nxx_code: str = "558", thousands_digit: int = 3,
                                effective_at: str = DEFAULT_CLOCK,
                                clock: str = DEFAULT_CLOCK):
    """An ASSIGNED block with routing published and in effect.

    Returns (carrier, npa, rate_center, block, record).
    """
    set_clock(clock)
    carrier = create_eligible_carrier(profile)
    npa, rate_center = setup_npa_with_rate_center()
    block = load_block(
        npa, rate_center, nxx_code=nxx_code, thousands_digit=thousands_digit,
        holder_carrier_id=carrier["id"], mark_activated=True,
    )
    record = publish_routing_record(
        block, lrn=lrn, switch_clli=TEST_DEFAULTS["SWITCH_CLLI_A"],
        effective_at=effective_at,
    )
    return carrier, npa, rate_center, read_block(block["id"]), record


def setup_submitted_port_request(telephone_number: str = "6145583000",
                                 lrn: str = "6145580000",
                                 requested_lrn: str = "6145570000",
                                 nxx_code: str = "558", thousands_digit: int = 3,
                                 desired_due_at: str = "2026-09-15T00:00:00Z"):
    """A port request awaiting the losing carrier's concurrence.

    Returns (from_carrier, to_carrier, npa, rate_center, block, port_request).
    """
    from_carrier, npa, rate_center, block, _record = setup_routed_assigned_block(
        profile="A", lrn=lrn, nxx_code=nxx_code, thousands_digit=thousands_digit
    )
    to_carrier = create_eligible_carrier("B")
    port_request = file_port_request(
        block, from_carrier, to_carrier, telephone_number,
        requested_lrn=requested_lrn, desired_due_at=desired_due_at,
    )
    return from_carrier, to_carrier, npa, rate_center, read_block(block["id"]), port_request


def setup_concurred_port_request(**kwargs):
    """The same scenario with the losing carrier's concurrence recorded."""
    from_carrier, to_carrier, npa, rate_center, block, port_request = (
        setup_submitted_port_request(**kwargs)
    )
    port_request = concur_port_request(port_request, from_carrier)
    return from_carrier, to_carrier, npa, rate_center, read_block(block["id"]), port_request
