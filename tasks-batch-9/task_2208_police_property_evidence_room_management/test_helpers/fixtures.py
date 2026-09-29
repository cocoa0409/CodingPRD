"""Composite setup helpers for multi-step test prerequisites.

Setup calls go through ``get_success_data`` (the framework's lenient validator) so a
broken prerequisite reports itself as a setup failure rather than as a confusing
assertion failure inside the test body.

The base state built here is the one every scenario in this suite starts from: the
logical clock pinned at its default instant, one property room, the offense statutes
that govern retention, a spread of storage bins covering all four categories, the
custodian roster, and the cases evidence is logged against.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    audit_session_payload,
    authorize_payload,
    case_payload,
    clock_payload,
    custodian_payload,
    custody_transfer_payload,
    disburse_payload,
    disposition_order_payload,
    evidence_item_payload,
    execute_payload,
    file_claim_payload,
    offense_statute_payload,
    owner_claim_payload,
    property_room_payload,
    release_payload,
    report_lost_payload,
    resolve_discrepancy_payload,
    retention_determination_payload,
    return_payload,
    scan_payload,
    settle_payload,
    storage_assignment_payload,
    storage_location_payload,
    suspend_payload,
)
from .test_users import (
    COURT_CLERK,
    MANAGER,
    make_evidence_technician_headers,
    make_internal_auditor_headers,
    make_investigator_headers,
    make_lab_analyst_headers,
)


# ─── Tier 0: the logical clock ───────────────────────────────────────────────

def set_clock(current_utc: str) -> dict:
    """Move the logical clock. Returns the ``current_utc`` / ``previous_utc`` pair."""
    return get_success_data(api_client.set_clock(clock_payload(current_utc), MANAGER))


# ─── Tier 1 / 2: base state ──────────────────────────────────────────────────

def _core_base(with_biological_statute: bool) -> Dict[str, Any]:
    """Clock, room, statutes, custodian roster and cases — the shared spine."""
    set_clock(DEFAULT_CLOCK)

    room = get_success_data(
        api_client.create_property_room(
            property_room_payload(name="Central Property Unit", agency_code="CPD"), MANAGER
        )
    )

    th3 = get_success_data(
        api_client.create_offense_statute(
            offense_statute_payload(
                offense_code="TH-3",
                description="Grand theft third degree",
                preservation_class="STANDARD",
                statutory_retention_days=365,
                appeal_window_days=30,
                destruction_requires_court_order=False,
            ),
            MANAGER,
        )
    )
    ab1 = get_success_data(
        api_client.create_offense_statute(
            offense_statute_payload(
                offense_code="AB-1",
                description="Abandoned property recovery",
                preservation_class="STANDARD",
                statutory_retention_days=0,
                appeal_window_days=0,
                destruction_requires_court_order=False,
            ),
            MANAGER,
        )
    )
    bio = None
    if with_biological_statute:
        bio = get_success_data(
            api_client.create_offense_statute(
                offense_statute_payload(
                    offense_code="BIO-1",
                    description="Sexual assault kit preservation",
                    preservation_class="BIOLOGICAL_INDEFINITE",
                    statutory_retention_days=365,
                    appeal_window_days=30,
                    destruction_requires_court_order=True,
                ),
                MANAGER,
            )
        )

    env: Dict[str, Any] = {
        "room": room,
        "room_id": room["id"],
        "room_version": room["version"],
        "th3": th3,
        "th3_id": th3["id"],
        "ab1": ab1,
        "ab1_id": ab1["id"],
        "bio": bio,
        "bio_id": bio["id"] if bio else None,
        "locations": {},
        "manager": MANAGER,
        "clerk": COURT_CLERK,
    }
    return env


def _add_location(env: Dict[str, Any], code: str, category: str, capacity_slots: int,
                  **extra) -> dict:
    location = get_success_data(
        api_client.create_storage_location(
            storage_location_payload(
                env["room_id"], code=code, category=category,
                capacity_slots=capacity_slots, **extra
            ),
            MANAGER,
        )
    )
    env["locations"][code] = location
    return location


def _add_custodian(env: Dict[str, Any], key: str, badge_number: str, full_name: str,
                   role_type: str,
                   certification_expires_at: str = "2028-01-01T00:00:00Z") -> dict:
    custodian = get_success_data(
        api_client.create_custodian(
            custodian_payload(
                env["room_id"], badge_number=badge_number, full_name=full_name,
                role_type=role_type, certification_expires_at=certification_expires_at,
            ),
            MANAGER,
        )
    )
    env[key] = custodian
    env[f"{key}_id"] = custodian["id"]
    header_builders = {
        "EVIDENCE_TECH": make_evidence_technician_headers,
        "INVESTIGATOR": make_investigator_headers,
        "LAB_ANALYST": make_lab_analyst_headers,
        "AUDITOR": make_internal_auditor_headers,
    }
    env[f"{key}_headers"] = header_builders[role_type](custodian["id"])
    return custodian


def _add_roster(env: Dict[str, Any]) -> None:
    _add_custodian(env, "tech", "T-100", "Tara Ng", "EVIDENCE_TECH")
    _add_custodian(env, "tech2", "T-101", "Tom Reed", "EVIDENCE_TECH")
    _add_custodian(env, "lab", "L-200", "Lena Ruiz", "LAB_ANALYST")
    _add_custodian(env, "inv", "I-300", "Ivan Cole", "INVESTIGATOR")
    _add_custodian(env, "aud", "A-400", "Ada Vance", "AUDITOR")


def _add_case(env: Dict[str, Any], key: str, case_number: str, statute_id: str) -> dict:
    case = get_success_data(
        api_client.create_case(
            case_payload(env["room_id"], statute_id, case_number=case_number), MANAGER
        )
    )
    env[key] = case
    env[f"{key}_id"] = case["id"]
    return case


def setup_difficulty_base() -> Dict[str, Any]:
    """Base state with bins covering all four storage categories.

    G-01 GENERAL (2 slots), V-01 HIGH_VALUE_VAULT (3, dual signature),
    R-01 and R-02 REFRIGERATED (3 each, 3.5 C), Y-01 OVERSIZED_YARD (2);
    cases 26-00001 (TH-3) and 26-00002 (AB-1).
    """
    env = _core_base(with_biological_statute=False)
    _add_location(env, "G-01", "GENERAL", 2)
    _add_location(env, "V-01", "HIGH_VALUE_VAULT", 3, requires_dual_signature=True)
    _add_location(env, "R-01", "REFRIGERATED", 3, temperature_c=3.5)
    _add_location(env, "R-02", "REFRIGERATED", 3, temperature_c=3.5)
    _add_location(env, "Y-01", "OVERSIZED_YARD", 2)
    _add_roster(env)
    _add_case(env, "case1", "26-00001", env["th3_id"])
    _add_case(env, "case2", "26-00002", env["ab1_id"])
    _alias_locations(env)
    return env


def setup_corner_base() -> Dict[str, Any]:
    """Base state with a tight bin, a warm refrigerator and a biological statute.

    G-01 GENERAL (2 slots), G-09 GENERAL (1 slot), V-01 HIGH_VALUE_VAULT (3, dual
    signature), R-01 REFRIGERATED (3, 3.5 C), R-09 REFRIGERATED (3, 6.0 C — recorded
    warm, so ineligible to receive items); cases 26-00001 (TH-3), 26-00002 (AB-1) and
    26-00003 (BIO-1).
    """
    env = _core_base(with_biological_statute=True)
    _add_location(env, "G-01", "GENERAL", 2)
    _add_location(env, "G-09", "GENERAL", 1)
    _add_location(env, "V-01", "HIGH_VALUE_VAULT", 3, requires_dual_signature=True)
    _add_location(env, "R-01", "REFRIGERATED", 3, temperature_c=3.5)
    _add_location(env, "R-09", "REFRIGERATED", 3, temperature_c=6.0)
    _add_roster(env)
    _add_case(env, "case1", "26-00001", env["th3_id"])
    _add_case(env, "case2", "26-00002", env["ab1_id"])
    _add_case(env, "case3", "26-00003", env["bio_id"])
    _alias_locations(env)
    return env


def _alias_locations(env: Dict[str, Any]) -> None:
    """Expose each bin under a short key, e.g. ``loc_g``/``loc_g_id``/``loc_g_version``."""
    aliases = {
        "G-01": "loc_g",
        "G-02": "loc_g2",
        "G-09": "loc_g9",
        "V-01": "loc_v",
        "R-01": "loc_r",
        "R-02": "loc_r2",
        "R-09": "loc_rw",
        "Y-01": "loc_y",
    }
    for code, alias in aliases.items():
        if code in env["locations"]:
            location = env["locations"][code]
            env[alias] = location
            env[f"{alias}_id"] = location["id"]
            env[f"{alias}_version"] = location["version"]


def add_general_bin(env: Dict[str, Any], code: str = "G-02",
                    capacity_slots: int = 4) -> dict:
    """Add one more GENERAL bin to the base room (a roomy spare)."""
    location = _add_location(env, code, "GENERAL", capacity_slots)
    _alias_locations(env)
    return location


def add_oversized_yard(env: Dict[str, Any], code: str = "Y-01",
                       capacity_slots: int = 2) -> dict:
    location = _add_location(env, code, "OVERSIZED_YARD", capacity_slots)
    _alias_locations(env)
    return location


def setup_second_room(env: Dict[str, Any], agency_code: str = "MPD",
                      name: str = "North District Annex") -> Dict[str, Any]:
    """A second property room with its own bin, technician and case.

    Used for cross-room scenarios: barcodes are prefixed by the room's agency code,
    and an item belonging to another room's case is foreign to this room's audits.
    """
    room2 = get_success_data(
        api_client.create_property_room(
            property_room_payload(name=name, agency_code=agency_code), MANAGER
        )
    )
    loc = get_success_data(
        api_client.create_storage_location(
            storage_location_payload(room2["id"], code="G-01", category="GENERAL",
                                     capacity_slots=4),
            MANAGER,
        )
    )
    tech = get_success_data(
        api_client.create_custodian(
            custodian_payload(room2["id"], badge_number="T-100", full_name="Mara Diaz",
                              role_type="EVIDENCE_TECH",
                              certification_expires_at="2028-01-01T00:00:00Z"),
            MANAGER,
        )
    )
    case = get_success_data(
        api_client.create_case(
            case_payload(room2["id"], env["th3_id"], case_number="26-90001"), MANAGER
        )
    )
    second = {
        "room": room2,
        "room_id": room2["id"],
        "loc": loc,
        "loc_id": loc["id"],
        "loc_version": loc["version"],
        "tech": tech,
        "tech_id": tech["id"],
        "tech_headers": make_evidence_technician_headers(tech["id"]),
        "case": case,
        "case_id": case["id"],
    }
    env["second_room"] = second
    return second


# ─── Tier 2: items in bins ───────────────────────────────────────────────────

def log_item(env: Dict[str, Any], case_id: Optional[str] = None, **overrides) -> dict:
    """Log one evidence item as the base technician. Returns the created item."""
    case_id = case_id or env["case1_id"]
    return get_success_data(
        api_client.create_evidence_item(
            evidence_item_payload(case_id, **overrides), env["tech_headers"]
        )
    )


def assign_storage(env: Dict[str, Any], item_id: str,
                   location_id: Optional[str] = None) -> dict:
    """Assign an item to a named bin, or let the service auto-select when omitted."""
    return get_success_data(
        api_client.assign_storage(
            item_id, storage_assignment_payload(location_id), env["tech_headers"]
        )
    )


def log_and_store_item(env: Dict[str, Any], case_id: Optional[str] = None,
                       location_id: Optional[str] = None, **overrides) -> dict:
    """Log an item and walk its custody dimension from LOGGED to STORED."""
    item = log_item(env, case_id=case_id, **overrides)
    return assign_storage(env, item["id"], location_id)


def read_item(env: Dict[str, Any], item_id: str) -> dict:
    return get_success_data(api_client.get_evidence_item(item_id, MANAGER))


def read_room(env: Dict[str, Any]) -> dict:
    return get_success_data(api_client.get_property_room(env["room_id"], MANAGER))


def read_location(env: Dict[str, Any], location_id: str) -> dict:
    return get_success_data(api_client.get_storage_location(location_id, MANAGER))


def read_case(env: Dict[str, Any], case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, MANAGER))


def read_custodian(env: Dict[str, Any], custodian_id: str) -> dict:
    return get_success_data(api_client.get_custodian(custodian_id, MANAGER))


# ─── Tier 3: full-lifecycle shortcuts ────────────────────────────────────────

def charge_case(env: Dict[str, Any], case_id: str) -> dict:
    return get_success_data(api_client.charge_case(case_id, env["inv_headers"]))


def adjudicate_case(env: Dict[str, Any], case_id: str) -> dict:
    return get_success_data(api_client.adjudicate_case(case_id, COURT_CLERK))


def charge_and_adjudicate(env: Dict[str, Any], case_id: str) -> dict:
    """Walk a case OPEN → CHARGED → ADJUDICATED, which re-determines retention."""
    charge_case(env, case_id)
    return adjudicate_case(env, case_id)


def open_appeal(env: Dict[str, Any], case_id: str) -> dict:
    return get_success_data(api_client.appeal_case(case_id, COURT_CLERK))


def resolve_appeal(env: Dict[str, Any], case_id: str) -> dict:
    return get_success_data(api_client.resolve_appeal_case(case_id, COURT_CLERK))


def record_determination(env: Dict[str, Any], item_id: str, basis: str,
                         expected_version: int, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_retention_determination(
            retention_determination_payload(item_id, basis, expected_version),
            headers or env["tech_headers"],
        )
    )


def run_sweep(env: Dict[str, Any]) -> dict:
    """Run the nightly sweep for the base room."""
    return get_success_data(api_client.daily_sweep(env["room_id"], MANAGER))


def make_item_disposal_eligible(env: Dict[str, Any], item_id: str,
                                clock_at: str) -> dict:
    """Mature a stored item's retention: move the clock past its release instant and
    run the sweep, which promotes RETAINED → DISPOSAL_ELIGIBLE."""
    set_clock(clock_at)
    run_sweep(env)
    return read_item(env, item_id)


def setup_disposal_eligible_item(env: Dict[str, Any], case_id: Optional[str] = None,
                                 location_id: Optional[str] = None,
                                 clock_at: str = "2027-08-01T00:00:00Z",
                                 adjudicate: bool = True, **overrides) -> dict:
    """Log → store → (charge, adjudicate) → advance clock → sweep.

    Returns the item once its ``disposition_state`` has reached DISPOSAL_ELIGIBLE,
    which is the precondition for opening a disposition order.
    """
    case_id = case_id or env["case1_id"]
    item = log_and_store_item(env, case_id=case_id, location_id=location_id, **overrides)
    if adjudicate:
        charge_and_adjudicate(env, case_id)
    return make_item_disposal_eligible(env, item["id"], clock_at)


# ─── Custody transfers ───────────────────────────────────────────────────────

def request_transfer(env: Dict[str, Any], item_id: str, to_custodian_id: str,
                     purpose: str, released_at: str, due_back_at: str,
                     headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_custody_transfer(
            custody_transfer_payload(item_id, to_custodian_id, purpose, released_at,
                                     due_back_at),
            headers or env["tech_headers"],
        )
    )


def release_transfer(env: Dict[str, Any], transfer_id: str, released_signature: str,
                     witness_signature: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.release_transfer(
            transfer_id, release_payload(released_signature, witness_signature),
            env["tech_headers"],
        )
    )


def return_transfer(env: Dict[str, Any], transfer_id: str, receipt_signature: str) -> dict:
    return get_success_data(
        api_client.return_transfer(transfer_id, return_payload(receipt_signature),
                                   env["tech_headers"])
    )


def setup_released_transfer(env: Dict[str, Any], item_id: str, to_custodian_id: str,
                            purpose: str, released_at: str, due_back_at: str,
                            released_signature: str = "T.NG-2026-09-16",
                            witness_signature: Optional[str] = None) -> dict:
    """Request a transfer and release the item into the receiving custodian's custody."""
    transfer = request_transfer(env, item_id, to_custodian_id, purpose, released_at,
                               due_back_at)
    return release_transfer(env, transfer["id"], released_signature, witness_signature)


def report_lost(env: Dict[str, Any], transfer_id: str,
                reason: str = "Item not produced at the laboratory bench") -> dict:
    return get_success_data(
        api_client.report_transfer_lost(transfer_id, report_lost_payload(reason), MANAGER)
    )


def suspend_custodian(env: Dict[str, Any], custodian_id: str,
                      reason: str = "Pending internal review") -> dict:
    return get_success_data(
        api_client.suspend_custodian(custodian_id, suspend_payload(reason), MANAGER)
    )


# ─── Owner claims ────────────────────────────────────────────────────────────

def issue_notice(env: Dict[str, Any], item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_owner_claim(
            owner_claim_payload(item_id, **overrides), env["tech_headers"]
        )
    )


def file_claim(env: Dict[str, Any], claim_id: str,
               proof_document_ref: str = "PROOF-2026-3311") -> dict:
    return get_success_data(
        api_client.file_claim(claim_id, file_claim_payload(proof_document_ref),
                              env["tech_headers"])
    )


def verify_claim(env: Dict[str, Any], claim_id: str) -> dict:
    return get_success_data(api_client.verify_claim(claim_id, MANAGER))


def setup_verified_claim(env: Dict[str, Any], item_id: str,
                         proof_document_ref: str = "PROOF-2026-3311",
                         **notice_overrides) -> dict:
    """Notice → filing → verification, the chain a return-to-owner execution needs."""
    claim = issue_notice(env, item_id, **notice_overrides)
    file_claim(env, claim["id"], proof_document_ref)
    return verify_claim(env, claim["id"])


# ─── Disposition orders ──────────────────────────────────────────────────────

def open_order(env: Dict[str, Any], item_id: str, order_type: str,
               requested_by_custodian_id: Optional[str] = None,
               headers: Optional[dict] = None, **overrides) -> dict:
    """Open a disposition order. The requester defaults to the base technician, whose
    id must equal ``X-User-ID`` when an entity-backed role opens the order."""
    requested_by = requested_by_custodian_id or env["tech_id"]
    return get_success_data(
        api_client.create_disposition_order(
            disposition_order_payload(item_id, order_type, requested_by, **overrides),
            headers or env["tech_headers"],
        )
    )


def authorize_order(env: Dict[str, Any], order_id: str, court_order_number: str) -> dict:
    return get_success_data(
        api_client.authorize_order(order_id, authorize_payload(court_order_number),
                                   COURT_CLERK)
    )


def execute_order(env: Dict[str, Any], order_id: str, executed_by: str,
                  witness: str) -> dict:
    return get_success_data(
        api_client.execute_order(order_id, execute_payload(executed_by, witness), MANAGER)
    )


def settle_order(env: Dict[str, Any], order_id: str, gross_sale_cents: int) -> dict:
    return get_success_data(
        api_client.settle_order(order_id, settle_payload(gross_sale_cents), MANAGER)
    )


def disburse_order(env: Dict[str, Any], order_id: str,
                   payee_reference: str = "TREAS-2027-0088") -> dict:
    return get_success_data(
        api_client.disburse_order(order_id, disburse_payload(payee_reference), MANAGER)
    )


def setup_authorized_order(env: Dict[str, Any], item_id: str, order_type: str,
                           court_order_number: str,
                           requested_by_custodian_id: Optional[str] = None,
                           **overrides) -> dict:
    """Open an order and record court authorization against it."""
    order = open_order(env, item_id, order_type, requested_by_custodian_id, **overrides)
    return authorize_order(env, order["id"], court_order_number)


def setup_executed_order(env: Dict[str, Any], item_id: str, order_type: str,
                         court_order_number: str,
                         executed_by: Optional[str] = None,
                         witness: Optional[str] = None,
                         requested_by_custodian_id: Optional[str] = None,
                         execute_clock: Optional[str] = None, **overrides) -> dict:
    """Open → authorize → execute, honouring segregation of duties by default.

    The executor defaults to the second technician and the witness to the
    investigator, so the executor differs from the requester and from the witness.
    """
    order = setup_authorized_order(env, item_id, order_type, court_order_number,
                                   requested_by_custodian_id, **overrides)
    if execute_clock:
        set_clock(execute_clock)
    return execute_order(env, order["id"], executed_by or env["tech2_id"],
                         witness or env["inv_id"])


def setup_settled_auction(env: Dict[str, Any], item_id: str, court_order_number: str,
                          reserve_price_cents: int, gross_sale_cents: int,
                          execute_clock: Optional[str] = None,
                          requested_by_custodian_id: Optional[str] = None) -> dict:
    """Open → authorize → execute → settle an auction, leaving the net in escrow."""
    order = setup_executed_order(
        env, item_id, "AUCTION", court_order_number,
        requested_by_custodian_id=requested_by_custodian_id,
        execute_clock=execute_clock, reserve_price_cents=reserve_price_cents,
    )
    return settle_order(env, order["id"], gross_sale_cents)


# ─── Audits and discrepancies ────────────────────────────────────────────────

def schedule_audit(env: Dict[str, Any], location_id: str, expected_version: int,
                   scheduled_start_at: str, scheduled_end_at: str,
                   auditor_id: Optional[str] = None,
                   headers: Optional[dict] = None) -> dict:
    """Schedule an audit. ``auditor_id`` must equal the acting auditor's ``X-User-ID``."""
    auditor_id = auditor_id or env["aud_id"]
    return get_success_data(
        api_client.create_audit_session(
            audit_session_payload(location_id, auditor_id, scheduled_start_at,
                                  scheduled_end_at, expected_version),
            headers or env["aud_headers"],
        )
    )


def start_audit(env: Dict[str, Any], session_id: str) -> dict:
    return get_success_data(api_client.start_audit_session(session_id, env["aud_headers"]))


def scan_barcode(env: Dict[str, Any], session_id: str, barcode: str) -> dict:
    return get_success_data(
        api_client.scan_audit_session(session_id, scan_payload(barcode), env["aud_headers"])
    )


def reconcile_audit(env: Dict[str, Any], session_id: str) -> dict:
    return get_success_data(
        api_client.reconcile_audit_session(session_id, env["aud_headers"])
    )


def close_audit(env: Dict[str, Any], session_id: str) -> dict:
    return get_success_data(api_client.close_audit_session(session_id, env["aud_headers"]))


def setup_started_audit(env: Dict[str, Any], location_id: str, expected_version: int,
                        scheduled_start_at: str = "2026-08-08T17:00:00Z",
                        scheduled_end_at: str = "2026-08-10T17:00:00Z") -> dict:
    """Schedule and start an audit, which seals the location and snapshots inventory."""
    session = schedule_audit(env, location_id, expected_version, scheduled_start_at,
                             scheduled_end_at)
    return start_audit(env, session["id"])


def setup_sealed_location(env: Dict[str, Any], location_id: str, expected_version: int,
                          scheduled_start_at: str = "2026-08-08T17:00:00Z",
                          scheduled_end_at: str = "2026-08-10T17:00:00Z") -> dict:
    """Seal a bin by starting an audit against it. Returns the in-progress session."""
    return setup_started_audit(env, location_id, expected_version, scheduled_start_at,
                               scheduled_end_at)


def setup_reconciled_audit(env: Dict[str, Any], location_id: str, expected_version: int,
                           barcodes: Optional[List[str]] = None,
                           scheduled_start_at: str = "2026-08-08T17:00:00Z",
                           scheduled_end_at: str = "2026-08-10T17:00:00Z") -> dict:
    """Schedule → start → scan the given barcodes → reconcile.

    Anything expected but not scanned becomes a MISSING discrepancy and drives its
    item out of the occupancy set.
    """
    session = setup_started_audit(env, location_id, expected_version,
                                 scheduled_start_at, scheduled_end_at)
    for barcode in barcodes or []:
        scan_barcode(env, session["id"], barcode)
    return reconcile_audit(env, session["id"])


def list_discrepancies(env: Dict[str, Any], **params) -> List[dict]:
    response = api_client.list_discrepancies(MANAGER, params=params or None)
    return get_success_data(response)


def investigate_discrepancy(env: Dict[str, Any], discrepancy_id: str) -> dict:
    return get_success_data(api_client.investigate_discrepancy(discrepancy_id, MANAGER))


def resolve_discrepancy(env: Dict[str, Any], discrepancy_id: str, resolution: str,
                        resolution_note: str) -> dict:
    return get_success_data(
        api_client.resolve_discrepancy(
            discrepancy_id, resolve_discrepancy_payload(resolution, resolution_note),
            MANAGER,
        )
    )


# ─── Tier 4: threshold and posture targeting ─────────────────────────────────

def setup_locked_down_room_via_missing_high_risk(
    env: Dict[str, Any], location_code: str = "V-01",
    category: str = "CURRENCY", packaging_type: str = "SEALED_ENVELOPE",
    appraised_value_cents: int = 300000,
    item_description: str = "Bundled banknotes",
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive the room to LOCKED_DOWN through a single missing high-risk item.

    A high-risk item is stored, audited without being scanned, and reconciliation
    raises a MISSING discrepancy; ``missing_high_risk_count`` of 1 is enough on its own
    to lock the room down.
    Returns the item, session and discrepancy involved.
    """
    location = env["locations"][location_code]
    item = log_and_store_item(
        env, case_id=case_id or env["case1_id"], location_id=location["id"],
        item_description=item_description, category=category,
        packaging_type=packaging_type, appraised_value_cents=appraised_value_cents,
    )
    fresh_location = read_location(env, location["id"])
    session = setup_reconciled_audit(env, location["id"], fresh_location["version"])
    discrepancies = list_discrepancies(env, audit_session_id=session["id"])
    return {
        "item": read_item(env, item["id"]),
        "session": session,
        "discrepancy": discrepancies[0] if discrepancies else None,
        "location": read_location(env, location["id"]),
        "room": read_room(env),
    }


def setup_room_with_open_discrepancies(env: Dict[str, Any], count: int,
                                       location_code: str = "G-01") -> Dict[str, Any]:
    """Raise ``count`` MISSING discrepancies on plain GENERAL items in one bin.

    Useful for the ``open_discrepancy_count`` posture branch, which locks the room
    down once the count reaches 5.
    """
    location = env["locations"][location_code]
    items = []
    for index in range(count):
        items.append(
            log_and_store_item(
                env, location_id=location["id"],
                item_description=f"Plain item {index + 1}",
                category="GENERAL", packaging_type="PAPER_BAG",
                appraised_value_cents=1000,
            )
        )
    fresh_location = read_location(env, location["id"])
    session = setup_reconciled_audit(env, location["id"], fresh_location["version"])
    return {
        "items": items,
        "session": session,
        "discrepancies": list_discrepancies(env, audit_session_id=session["id"]),
        "room": read_room(env),
    }


# ─── Tier 5: terminal states ─────────────────────────────────────────────────

def setup_disposed_item(env: Dict[str, Any], case_id: Optional[str] = None,
                        location_id: Optional[str] = None,
                        court_order_number: str = "CO-2026-7788",
                        clock_at: str = "2027-08-01T00:00:00Z") -> Dict[str, Any]:
    """Carry one item all the way to PURGED / DISPOSED through a destruction order."""
    case_id = case_id or env["case1_id"]
    item = setup_disposal_eligible_item(env, case_id=case_id, location_id=location_id,
                                       clock_at=clock_at)
    order = setup_executed_order(env, item["id"], "DESTRUCTION", court_order_number)
    return {"item": read_item(env, item["id"]), "order": order}


def setup_disbursed_auction(env: Dict[str, Any], item_id: str,
                            court_order_number: str = "CO-2026-1199",
                            reserve_price_cents: int = 50000,
                            gross_sale_cents: int = 90000,
                            execute_clock: str = "2027-05-01T00:00:00Z",
                            payee_reference: str = "TREAS-2027-0088") -> Dict[str, Any]:
    """Settle an auction and then disburse it, returning escrow to its prior value."""
    order = setup_settled_auction(env, item_id, court_order_number, reserve_price_cents,
                                 gross_sale_cents, execute_clock=execute_clock)
    disbursed = disburse_order(env, order["id"], payee_reference)
    return {"settled": order, "disbursed": disbursed, "room": read_room(env)}
