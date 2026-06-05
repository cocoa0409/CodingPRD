"""Payload factories — one per creatable entity, input fields only (PRD §3).

Each factory fills required input fields with valid defaults and accepts
**overrides. Unique fields (email, employee_id) get a uuid4 suffix so repeated
calls within one test do not collide on the uniqueness constraints (PRD §3.1).
"""
import uuid


def _uniq() -> str:
    return uuid.uuid4().hex[:10]


# ─── Participant (PRD §3.1) ────────────────────────────────────────
def create_participant_payload(**overrides) -> dict:
    suffix = _uniq()
    payload = {
        "email": f"p-{suffix}@x.com",
        "full_name": "Test Participant",
        "employee_id": f"E-{suffix}",
    }
    payload.update(overrides)
    return payload


# ─── Plan (PRD §3.1) ───────────────────────────────────────────────
def create_plan_payload(**overrides) -> dict:
    payload = {"company_name": f"Co-{_uniq()}"}
    payload.update(overrides)
    return payload


# ─── OfferingPeriod (PRD §3.2) ─────────────────────────────────────
def create_offering_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "grant_date": "2024-01-01T00:00:00.000Z",
        "duration_months": 12,
        "grant_date_fmv_cents": 1000,
    }
    payload.update(overrides)
    return payload


# ─── PurchasePeriod (PRD §3.2) ─────────────────────────────────────
def create_purchase_period_payload(**overrides) -> dict:
    payload = {
        "sequence_index": 1,
        "purchase_date": "2024-06-30T00:00:00.000Z",
        "purchase_date_fmv_cents": 1200,
    }
    payload.update(overrides)
    return payload


# ─── Enrollment (PRD §3.3) ─────────────────────────────────────────
def create_enrollment_payload(participant_id, offering_period_id, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "offering_period_id": offering_period_id,
        "contribution_rate_pct": 10,
    }
    payload.update(overrides)
    return payload


# ─── Contribution (PRD §3.3) ───────────────────────────────────────
def create_contribution_payload(enrollment_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "pay_date": "2024-02-01T00:00:00.000Z",
        "gross_pay_cents": 1000000,
    }
    payload.update(overrides)
    return payload


# ─── Disposition (PRD §3.8) ────────────────────────────────────────
def create_disposition_payload(share_lot_id, participant_id, **overrides) -> dict:
    payload = {
        "share_lot_id": share_lot_id,
        "participant_id": participant_id,
        "sale_date": "2024-06-30T00:00:00.000Z",
        "shares_sold": 1,
        "sale_price_per_share_cents": 1500,
    }
    payload.update(overrides)
    return payload


# ─── run-purchase body (PRD §2.8, §3.5) ────────────────────────────
def run_purchase_payload(expected_version, **overrides) -> dict:
    payload = {"expected_purchase_period_version": expected_version}
    payload.update(overrides)
    return payload
