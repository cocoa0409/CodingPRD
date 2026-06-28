"""Payload factories — one per writable entity, input fields only.

Each factory provides PRD-valid defaults for the required input fields and lets
tests override any value via **overrides.
"""
import itertools

# Monotonic counters so default unique fields (email, license, sku, serial, code)
# never collide within a single test run.
_email_seq = itertools.count(1)
_license_seq = itertools.count(1)
_sku_seq = itertools.count(1)
_serial_seq = itertools.count(1)
_code_seq = itertools.count(1)


def unique_email() -> str:
    return f"customer{next(_email_seq)}@example.com"


def unique_license() -> str:
    return f"LIC-{next(_license_seq):06d}"


def unique_sku() -> str:
    return f"SKU-{next(_sku_seq):06d}"


def unique_serial() -> str:
    return f"SN-{next(_serial_seq):06d}"


def unique_recall_code() -> str:
    return f"RC-{next(_code_seq):06d}"


# ─── Customer ────────────────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Homeowner",
        "service_address": "1 Generator Lane",
    }
    defaults.update(overrides)
    return defaults


# ─── Technician ──────────────────────────────────────────────────────────────
def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Technician",
        "license_no": unique_license(),
        "gas_certified": True,
    }
    defaults.update(overrides)
    return defaults


# ─── GeneratorModel ──────────────────────────────────────────────────────────
def create_model_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "rated_kw": 26,
        "fuel_types": ["NG"],
        "unit_price_cents": 900000,
        "warranty_months": 60,
    }
    defaults.update(overrides)
    return defaults


# ─── GeneratorProject ────────────────────────────────────────────────────────
def create_project_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "fuel_type": "NG",
    }
    defaults.update(overrides)
    return defaults


# ─── LoadAssessment ──────────────────────────────────────────────────────────
def create_load_assessment_payload(**overrides) -> dict:
    defaults = {
        "method": "STAGGERED",
        "appliances": [{"name": "ac", "running_watts": 3000, "starting_watts": 9000}],
    }
    defaults.update(overrides)
    return defaults


# ─── size / permit / install / activate bodies ──────────────────────────────
def size_payload(assessment_id, model_id, **overrides) -> dict:
    defaults = {"assessment_id": assessment_id, "model_id": model_id}
    defaults.update(overrides)
    return defaults


def permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "PERMIT-1",
        "permit_decision": "APPROVE",
        "fuel_supply_btu_per_hr": 400000,
    }
    defaults.update(overrides)
    return defaults


def install_payload(install_tech_id, **overrides) -> dict:
    defaults = {"install_tech_id": install_tech_id, "ats_amps": 200}
    defaults.update(overrides)
    return defaults


def activate_payload(**overrides) -> dict:
    defaults = {"serial_no": unique_serial()}
    defaults.update(overrides)
    return defaults


# ─── Unit children ───────────────────────────────────────────────────────────
def exercise_log_payload(occurred_at, result, **overrides) -> dict:
    defaults = {"occurred_at": occurred_at, "result": result}
    defaults.update(overrides)
    return defaults


def maintenance_plan_payload(frequency="ANNUAL", **overrides) -> dict:
    defaults = {"frequency": frequency}
    defaults.update(overrides)
    return defaults


def warranty_claim_payload(expected_unit_version, **overrides) -> dict:
    defaults = {
        "description": "Defect description",
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def repair_dispatch_payload(**overrides) -> dict:
    # PAID dispatch; labor/parts default to 0 per PRD.
    defaults = {}
    defaults.update(overrides)
    return defaults


# ─── MaintenanceVisit ────────────────────────────────────────────────────────
def visit_payload(scheduled_for, **overrides) -> dict:
    defaults = {"scheduled_for": scheduled_for}
    defaults.update(overrides)
    return defaults


# ─── RepairDispatch transitions ─────────────────────────────────────────────
def assign_payload(assigned_tech_id, expected_dispatch_version, **overrides) -> dict:
    defaults = {
        "assigned_tech_id": assigned_tech_id,
        "expected_dispatch_version": expected_dispatch_version,
    }
    defaults.update(overrides)
    return defaults


# ─── WarrantyClaim adjudication ─────────────────────────────────────────────
def adjudicate_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ─── RecallCampaign ──────────────────────────────────────────────────────────
def recall_campaign_payload(model_id, severity="MANDATORY", **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "code": unique_recall_code(),
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults
