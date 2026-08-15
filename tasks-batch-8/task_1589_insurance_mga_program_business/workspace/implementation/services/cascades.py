"""Cascading transitions (PRD section 2.10).

Every mutation produced by a cascade refreshes the affected resource's
updated_at and increments its version. The program itself gains a version
increment on each of its own lifecycle transitions.
"""
from db import STORE, touch


def refer_under_review_claims_of_appointment(appointment):
    for c in STORE.claims.values():
        if c.get("_appointment_id") == appointment["id"] and c["status"] == "UNDER_REVIEW":
            c["status"] = "REFERRED"
            c["referral_reason"] = "APPOINTMENT_SUSPENDED"
            touch(c)


def suspend_appointment(appointment):
    """ACTIVE -> SUSPENDED; refers this appointment's UNDER_REVIEW claims."""
    appointment["status"] = "SUSPENDED"
    touch(appointment)
    refer_under_review_claims_of_appointment(appointment)


def suspend_program(program):
    """The fixed suspension cascade: quotes withdrawn, ACTIVE appointments
    suspended (each referring its UNDER_REVIEW claims), DRAFT bordereaux
    cancelled."""
    program["status"] = "SUSPENDED"
    touch(program)
    pid = program["id"]
    for p in STORE.policies.values():
        if p["program_id"] == pid and p["status"] == "QUOTED":
            p["status"] = "WITHDRAWN"
            touch(p)
    for a in STORE.tpa_appointments.values():
        if a["program_id"] == pid and a["status"] == "ACTIVE":
            suspend_appointment(a)
    for b in STORE.bordereaux.values():
        if b["program_id"] == pid and b["status"] == "DRAFT":
            b["status"] = "CANCELLED"
            touch(b)


def _withdraw_open_filings(program_id):
    """Program TERMINATED/DECLINED: filings still in DRAFT or SUBMITTED become
    WITHDRAWN."""
    for f in STORE.rate_filings.values():
        if f["program_id"] == program_id and f["status"] in ("DRAFT", "SUBMITTED"):
            f["status"] = "WITHDRAWN"
            touch(f)


def terminate_program(program, termination_reason):
    """RUN_OFF -> TERMINATED: guidelines INACTIVE, non-terminal tranche
    RELEASED, open filings withdrawn."""
    pid = program["id"]
    for g in STORE.guidelines.values():
        if g["program_id"] == pid and g["status"] == "ACTIVE":
            g["status"] = "INACTIVE"
            touch(g)
    for a in STORE.capacity_allocations.values():
        if a["program_id"] == pid and a["status"] in ("ACTIVE", "EXHAUSTED"):
            a["status"] = "RELEASED"
            touch(a)
    _withdraw_open_filings(pid)
    program["status"] = "TERMINATED"
    program["termination_reason"] = termination_reason
    touch(program)


def decline_program(program, termination_reason):
    program["status"] = "DECLINED"
    program["termination_reason"] = termination_reason
    _withdraw_open_filings(program["id"])
    touch(program)


def supersede_prior_effective_filings(new_filing):
    """mark-effective: the prior EFFECTIVE filing of the same program+state
    becomes SUPERSEDED; every QUOTED policy rated under it is withdrawn."""
    pid = new_filing["program_id"]
    state = new_filing["state_code"]
    for f in STORE.rate_filings.values():
        if (
            f["program_id"] == pid
            and f["state_code"] == state
            and f["status"] == "EFFECTIVE"
            and f["id"] != new_filing["id"]
        ):
            f["status"] = "SUPERSEDED"
            touch(f)
            for p in STORE.policies.values():
                if p["filing_id"] == f["id"] and p["status"] == "QUOTED":
                    p["status"] = "WITHDRAWN"
                    touch(p)
