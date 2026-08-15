"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints — each
test runs against a freshly restarted server with an empty database. Setup calls
use the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors naming the step.

Identity threading: after a helper creates a Nurse, every ownership-gated call
(packet submit/resubmit, item submit-evidence, own completions) uses
make_nurse_headers(nurse["id"]) — never the shared Nurse fallback.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_audit_run_payload,
    create_certification_payload,
    create_competency_completion_payload,
    create_competency_requirement_payload,
    create_competency_session_payload,
    create_credential_packet_payload,
    create_disciplinary_action_payload,
    create_nurse_payload,
    create_shift_assignment_payload,
    create_state_license_payload,
    create_unit_payload,
)
from .test_users import TEST_USERS, make_nurse_headers

SPEC1 = TEST_USERS["specialist_1"]
SPEC2 = TEST_USERS["specialist_2"]
VER1 = TEST_USERS["verifier_1"]
VER2 = TEST_USERS["verifier_2"]
MGR1 = TEST_USERS["manager_1"]
CO1 = TEST_USERS["compliance_1"]
CO2 = TEST_USERS["compliance_2"]
OPS1 = TEST_USERS["operator_1"]


# ---------------------------------------------------------------------------
# Tier 0: clock / sweep primitives
# ---------------------------------------------------------------------------

def set_clock(iso: str = DEFAULT_CLOCK_ISO) -> dict:
    """Move the logical clock (PRD §2.5). Mutates no entity."""
    return get_success_data(api_client.set_logical_clock({"to_iso8601": iso}, OPS1))


def run_sweep() -> dict:
    """Run the expiry-sweep ops checkpoint (PRD §3.9); returns the summary counts."""
    return get_success_data(api_client.run_expiry_sweep(OPS1))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_nurse(**overrides) -> dict:
    return get_success_data(api_client.create_nurse(create_nurse_payload(**overrides), SPEC1), 201)


def create_unit(name: Optional[str] = None, required_cert_types: Optional[List[str]] = None) -> dict:
    overrides: Dict = {}
    if name is not None:
        overrides["name"] = name
    if required_cert_types is not None:
        overrides["required_cert_types"] = required_cert_types
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), MGR1), 201)


def create_requirement(**overrides) -> dict:
    return get_success_data(
        api_client.create_competency_requirement(
            create_competency_requirement_payload(**overrides), CO1
        ),
        201,
    )


def create_license_draft(nurse_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_state_license(create_state_license_payload(nurse_id, **overrides), SPEC1),
        201,
    )


def create_certification(nurse_id: str, cert_type: str = "BLS", **overrides) -> dict:
    return get_success_data(
        api_client.create_certification(
            create_certification_payload(nurse_id, cert_type=cert_type, **overrides), SPEC1
        ),
        201,
    )


def record_completion(nurse_id: str, requirement_id: str, completed_on: str = "2026-07-15",
                      as_nurse_self: bool = True) -> dict:
    """Record a completion. By default the nurse records her own (Nurse role,
    ownership-gated); a specialist may record for anyone (as_nurse_self=False)."""
    headers = make_nurse_headers(nurse_id) if as_nurse_self else SPEC1
    return get_success_data(
        api_client.create_competency_completion(
            create_competency_completion_payload(nurse_id, requirement_id, completed_on=completed_on),
            headers,
        ),
        201,
    )


def activate_nurse(nurse_id: str) -> dict:
    return get_success_data(api_client.activate_nurse(nurse_id, SPEC1))


def terminate_nurse(nurse_id: str) -> dict:
    return get_success_data(api_client.terminate_nurse(nurse_id, SPEC1))


# ---------------------------------------------------------------------------
# Tier 2: license verification pipeline (submit -> PSV -> VERIFIED -> attest)
# ---------------------------------------------------------------------------

def submit_license(license_id: str) -> dict:
    return get_success_data(api_client.submit_license(license_id, SPEC1))


def request_psv(license_id: str, channel: str = "NURSYS", requester_headers=None) -> dict:
    return get_success_data(
        api_client.create_psv(
            {"license_id": license_id, "channel": channel}, requester_headers or SPEC1
        ),
        201,
    )


def record_psv_verified(psv_id: str, recorder_headers=None) -> dict:
    return get_success_data(
        api_client.record_psv_result(psv_id, {"outcome": "VERIFIED"}, recorder_headers or VER1)
    )


def verify_license_via_psv(license_id: str, channel: str = "NURSYS") -> dict:
    """DRAFT -> PENDING_VERIFICATION, then a PSV recorded VERIFIED (license -> VERIFIED).
    Returns the PSV row. Requester (spec-1) and recorder (ver-1) are segregated."""
    submit_license(license_id)
    psv = request_psv(license_id, channel=channel)
    return record_psv_verified(psv["id"])


def attest_license(license_id: str, attester_headers=None) -> dict:
    """VERIFIED -> ACTIVE. Attester (ver-1) differs from creator (spec-1)."""
    return get_success_data(api_client.attest_license(license_id, attester_headers or VER1))


def surrender_license(license_id: str, headers=None) -> dict:
    """Any non-terminal status -> SURRENDERED (terminal), by a ComplianceOfficer."""
    return get_success_data(api_client.surrender_license(license_id, headers or CO1))


def create_active_license(nurse_id: str, **overrides) -> dict:
    """Create a license and walk it DRAFT -> ... -> ACTIVE. Returns the ACTIVE license."""
    lic = create_license_draft(nurse_id, **overrides)
    verify_license_via_psv(lic["id"])
    return attest_license(lic["id"])


# ---------------------------------------------------------------------------
# Tier 3: fully credentialed nurse (license + BLS + mandatory competency) and
# the ACTIVE/CLEAR gating state (PRD §3.5 ladder rungs 1-5 all satisfied).
# ---------------------------------------------------------------------------

def setup_credentialed_nurse(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    primary_state_of_residence: str = "AZ",
    employment_type: str = "STAFF",
    hire_date: str = "2026-07-01",
    license_expires_on: str = "2027-06-30",
    license_state_code: str = "AZ",
    bls_expires_on: str = "2027-03-31",
    completed_on: str = "2026-07-15",
    requirement: Optional[dict] = None,
    requirement_overrides: Optional[dict] = None,
    activate: bool = True,
) -> dict:
    """Nurse with an ACTIVE (attested) multistate license, an ACTIVE BLS cert and a
    CURRENT completion for a mandatory requirement covering her employment type.
    With activate=True she is ACTIVE and (barring unit extras) posture CLEAR.
    Returns {nurse, license, bls, requirement, completion}."""
    req = requirement
    if req is None:
        req = create_requirement(**(requirement_overrides or {}))
    nurse_kwargs: Dict = {
        "primary_state_of_residence": primary_state_of_residence,
        "employment_type": employment_type,
        "hire_date": hire_date,
    }
    if full_name is not None:
        nurse_kwargs["full_name"] = full_name
    if email is not None:
        nurse_kwargs["email"] = email
    nurse = create_nurse(**nurse_kwargs)
    lic = create_active_license(
        nurse["id"], state_code=license_state_code, expires_on=license_expires_on
    )
    bls = create_certification(nurse["id"], "BLS", expires_on=bls_expires_on)
    completion = record_completion(nurse["id"], req["id"], completed_on=completed_on)
    if activate:
        nurse = activate_nurse(nurse["id"])
    return {
        "nurse": nurse,
        "license": lic,
        "bls": bls,
        "requirement": req,
        "completion": completion,
    }


def get_nurse(nurse_id: str) -> dict:
    return get_success_data(api_client.get_nurse(nurse_id, SPEC1))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, SPEC1))


def get_license(license_id: str) -> dict:
    return get_success_data(api_client.get_state_license(license_id, SPEC1))


def get_shift(shift_id: str) -> dict:
    return get_success_data(api_client.get_shift_assignment(shift_id, SPEC1))


def get_packet(packet_id: str) -> dict:
    return get_success_data(api_client.get_credential_packet(packet_id, SPEC1))


def get_packet_item(item_id: str) -> dict:
    return get_success_data(api_client.get_packet_item(item_id, SPEC1))


# ---------------------------------------------------------------------------
# Tier 4: shifts (book / start / complete / cancel) with clock choreography
# ---------------------------------------------------------------------------

def book_shift(nurse_id: str, unit_id: str, starts_at: str, ends_at: str) -> dict:
    return get_success_data(
        api_client.create_shift_assignment(
            create_shift_assignment_payload(nurse_id, unit_id, starts_at, ends_at), MGR1
        ),
        201,
    )


def run_shift_to_completion(shift_id: str, at_iso: str) -> dict:
    """Move the clock inside the shift window, start it, complete it (PRD §3.6).
    `at_iso` must satisfy starts_at <= at_iso < ends_at."""
    set_clock(at_iso)
    get_success_data(api_client.start_shift(shift_id, MGR1))
    return get_success_data(api_client.complete_shift(shift_id, MGR1))


def book_and_complete_shift(nurse_id: str, unit_id: str, date: str,
                            start_hh: str = "07:00", end_hh: str = "19:00",
                            clock_hh: str = "07:30") -> dict:
    """Book a shift on `date` and run it to COMPLETED at date+clock_hh."""
    shift = book_shift(
        nurse_id, unit_id, f"{date}T{start_hh}:00Z", f"{date}T{end_hh}:00Z"
    )
    return run_shift_to_completion(shift["id"], f"{date}T{clock_hh}:00Z")


# ---------------------------------------------------------------------------
# Tier 5: credential packets (materialized items -> evidence -> verify/waive ->
# submit -> review -> approve), per PRD §3.7.
# ---------------------------------------------------------------------------

def create_packet(nurse_id: str, unit_id: str) -> dict:
    return get_success_data(
        api_client.create_credential_packet(
            create_credential_packet_payload(nurse_id, unit_id), SPEC1
        ),
        201,
    )


def list_packet_items(packet_id: str) -> List[dict]:
    data, _meta = _list_packet_items(packet_id)
    return data


def _list_packet_items(packet_id: str):
    return validate_paginated(
        api_client.list_packet_items(SPEC1, params={"packet_id": packet_id})
    )


def packet_items_by_type(packet_id: str) -> Dict[str, dict]:
    """Items materialized by packet creation, keyed by item_type (PRD §3.7 fixed set)."""
    return {item["item_type"]: item for item in list_packet_items(packet_id)}


def fill_packet_items(packet_id: str, nurse_id: str, verify_types: List[str],
                      waive_types: Optional[List[str]] = None,
                      skip_types: Optional[List[str]] = None) -> Dict[str, dict]:
    """Submit evidence for the given item types (as the owning nurse), verify or
    waive per the lists (as the assembling specialist). skip_types stay MISSING.
    Returns the item map keyed by item_type."""
    items = packet_items_by_type(packet_id)
    nurse_headers = make_nurse_headers(nurse_id)
    skip = set(skip_types or [])
    waive = set(waive_types or [])
    for item_type, item in items.items():
        if item_type in skip:
            continue
        get_success_data(
            api_client.submit_item_evidence(
                item["id"], {"evidence_ref": f"ev-{item_type.lower()}"}, nurse_headers
            )
        )
    for item_type in verify_types:
        if item_type in skip:
            continue
        get_success_data(api_client.verify_packet_item(items[item_type]["id"], SPEC1))
    for item_type in waive:
        if item_type in skip:
            continue
        get_success_data(
            api_client.waive_packet_item(
                items[item_type]["id"], {"waive_reason": "on file"}, SPEC1
            )
        )
    return items


def setup_submitted_packet(nurse_id: str, unit_id: str,
                           attestation: str = "waive") -> Dict[str, dict]:
    """DRAFT packet whose items are all SUBMITTED/VERIFIED/WAIVED, then submitted by
    the owning nurse. attestation="waive" waives the attestation item; "verify"
    verifies it (attestation evidence is only its evidence_ref, PRD §3.7).
    Returns {packet, items}."""
    packet = create_packet(nurse_id, unit_id)
    items = packet_items_by_type(packet["id"])
    verify_types = [t for t in ("LICENSE_VERIFICATION", "BLS", "ACLS", "COMPETENCY_ANNUAL")
                    if t in items]
    waive_types: List[str] = []
    if attestation == "waive":
        waive_types = ["ATTESTATION"]
    else:
        verify_types = verify_types + ["ATTESTATION"]
    items = fill_packet_items(packet["id"], nurse_id, verify_types, waive_types=waive_types)
    get_success_data(api_client.submit_packet(packet["id"], make_nurse_headers(nurse_id)))
    return {"packet": packet, "items": items}


def setup_approved_packet(nurse_id: str, unit_id: str, attestation: str = "waive") -> Dict[str, dict]:
    """Full happy path to APPROVED: packet assembled by spec-1, review steps by
    spec-2 (segregated from the assembler). Returns {packet, items}."""
    ctx = setup_submitted_packet(nurse_id, unit_id, attestation=attestation)
    get_success_data(api_client.start_packet_review(ctx["packet"]["id"], SPEC2))
    approved = get_success_data(api_client.approve_packet(ctx["packet"]["id"], SPEC2))
    ctx["packet"] = approved
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: disciplinary actions (report -> acknowledge -> adjudicate -> resolve)
# ---------------------------------------------------------------------------

def report_discipline(nurse_id: str, scope: str = "PRIVILEGE", action_type: str = "REPRIMAND",
                      effective_on: str = "2026-08-01", license_id: Optional[str] = None,
                      reporter_headers=None) -> dict:
    payload = create_disciplinary_action_payload(
        nurse_id, scope=scope, action_type=action_type, effective_on=effective_on
    )
    if license_id is not None:
        payload["license_id"] = license_id
    return get_success_data(
        api_client.create_disciplinary_action(payload, reporter_headers or CO1), 201
    )


def acknowledge_discipline(action_id: str, headers=None) -> dict:
    return get_success_data(api_client.acknowledge_disciplinary_action(action_id, headers or CO1))


def adjudicate_discipline(action_id: str, outcome: str = "SUSTAINED", headers=None) -> dict:
    """Adjudicator (co-2) is segregated from the acknowledger (co-1) by default."""
    return get_success_data(
        api_client.adjudicate_disciplinary_action(action_id, {"outcome": outcome}, headers or CO2)
    )


def resolve_discipline(action_id: str, resolution_note: str = "resolved", headers=None) -> dict:
    return get_success_data(
        api_client.resolve_disciplinary_action(action_id, {"resolution_note": resolution_note},
                                               headers or CO1)
    )


# ---------------------------------------------------------------------------
# Tier 7: competency sessions & bookings (PRD §3.4)
# ---------------------------------------------------------------------------

def create_session(requirement_id: str, capacity: int = 2,
                   starts_at: str = "2026-08-05T09:00:00Z",
                   ends_at: str = "2026-08-05T12:00:00Z", title: Optional[str] = None) -> dict:
    overrides: Dict = {"capacity": capacity, "starts_at": starts_at, "ends_at": ends_at}
    if title is not None:
        overrides["title"] = title
    return get_success_data(
        api_client.create_competency_session(
            create_competency_session_payload(requirement_id, **overrides), MGR1
        ),
        201,
    )


def book_session(session_id: str, nurse_id: str) -> dict:
    return get_success_data(api_client.book_session(session_id, {"nurse_id": nurse_id}, MGR1), 201)


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_competency_session(session_id, SPEC1))


# ---------------------------------------------------------------------------
# Tier 8: audit runs (PRD §3.10)
# ---------------------------------------------------------------------------

def create_audit_run(window_start: str = "2026-07-01", window_end: str = "2026-08-01",
                     per_unit_sample_size: int = 5) -> dict:
    return get_success_data(
        api_client.create_audit_run(
            create_audit_run_payload(
                window_start=window_start,
                window_end=window_end,
                per_unit_sample_size=per_unit_sample_size,
            ),
            CO1,
        ),
        201,
    )


def begin_fieldwork(run_id: str) -> dict:
    return get_success_data(api_client.begin_audit_fieldwork(run_id, CO1))


def issue_findings(run_id: str) -> dict:
    return get_success_data(api_client.issue_audit_findings(run_id, CO1))


def get_audit_run(run_id: str) -> dict:
    return get_success_data(api_client.get_audit_run(run_id, CO1))


def list_run_findings(run_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_audit_findings(CO1, params={"audit_run_id": run_id})
    )
    return data


def list_privilege_evals(nurse_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_privilege_evaluations(SPEC1, params={"nurse_id": nurse_id})
    )
    return data


def setup_survey_nurse(unit_id: str, requirement_id: str, bls_expires_on: str,
                       shift_dates: List[str], full_name: Optional[str] = None) -> dict:
    """A fully credentialed ACTIVE nurse (PRD §3.5 rungs all satisfied) with one
    COMPLETED 12h shift in `unit_id` per date in `shift_dates`. Shifts are booked
    first, then each is started and completed at 07:30 on its own date (the clock
    is advanced per shift, so callers must book every shift of every nurse before
    the first run_shift_to_completion when interleaving matters — use
    book_shift/run_shift_to_completion directly in that case).
    Returns {nurse, license, bls, completion, shifts}."""
    nurse_kwargs: Dict = {"primary_state_of_residence": "AZ", "employment_type": "STAFF",
                          "hire_date": "2026-06-01"}
    if full_name is not None:
        nurse_kwargs["full_name"] = full_name
    nurse = create_nurse(**nurse_kwargs)
    lic = create_active_license(nurse["id"], state_code="AZ", expires_on="2027-06-30")
    bls = create_certification(nurse["id"], "BLS", obtained_on="2025-07-20",
                               expires_on=bls_expires_on)
    completion = record_completion(nurse["id"], requirement_id, completed_on="2026-06-15")
    nurse = activate_nurse(nurse["id"])
    shifts = [
        book_shift(nurse["id"], unit_id, f"{d}T07:00:00Z", f"{d}T19:00:00Z")
        for d in shift_dates
    ]
    return {"nurse": nurse, "license": lic, "bls": bls, "completion": completion,
            "shifts": shifts}
