"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_contact_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Contact",
        "email": f"contact-{_suffix()}@example.com",
        "role_title": "Staff",
    }
    defaults.update(overrides)
    return defaults


def create_process_payload(**overrides) -> dict:
    defaults = {
        "name": f"Proc-{_suffix()}",
        "business_unit": "Ops",
        "owner_contact_id": None,
        "criticality_tier": "TIER_2",
    }
    defaults.update(overrides)
    return defaults


def create_bia_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "cycle_label": "FY2026-H1",
        "rto_target_hours": 8,
        "rpo_target_hours": 2,
        "mtpd_hours": 24,
        "peak_period_flag": False,
        "impact_financial_per_hour": 300,
        "impact_regulatory": "NONE",
        "impact_reputational": "NONE",
        "impact_operational": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "title": f"DR Plan {_suffix()}",
        "version_no": 1,
        "strategy_type": "WARM_SITE",
        "rto_committed_hours": 8,
        "rpo_committed_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_plan_section_payload(**overrides) -> dict:
    defaults = {
        "section_type": "SCOPE",
        "content": "section body",
        "order_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_dependency_payload(**overrides) -> dict:
    defaults = {
        "from_process_id": None,
        "to_process_id": None,
        "dependency_type": "DATA",
        "criticality": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_third_party_payload(**overrides) -> dict:
    defaults = {
        "name": f"Vendor-{_suffix()}",
        "service_category": "Cloud",
        "criticality_rating": "HIGH",
        "owner_contact_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "third_party_id": None,
        "process_id": None,
        "assessment_type": "ANNUAL",
        "assessed_rto_hours": 4,
        "assessed_rpo_hours": 1,
        "rto_required_hours": 6,
        "rpo_required_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_alternate_site_payload(**overrides) -> dict:
    defaults = {
        "name": f"Site-{_suffix()}",
        "site_type": "HOT",
        "region": "us-east",
        "capacity_seats": 10,
        "contracted_through": "2027-01-01T00:00:00Z",
        "monthly_cost": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_site_reservation_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "process_id": None,
        "purpose": "EXERCISE",
        "seats_reserved": 1,
        "starts_at": "2026-07-10T09:00:00Z",
        "ends_at": "2026-07-10T12:00:00Z",
        "created_by_contact_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_exercise_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "plan_id": None,
        "exercise_type": "TABLETOP",
        "scheduled_start": "2026-05-10T09:00:00Z",
        "scheduled_end": "2026-05-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "exercise_id": None,
        "process_id": None,
        "severity": "HIGH",
        "description": "finding narrative",
        "due_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_capability_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "capability_type": "DATA_RESTORE",
        "capability_ref_id": f"ref-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_validation_run_payload(**overrides) -> dict:
    defaults = {
        "capability_id": None,
        "measured_rto_hours": 4,
        "measured_rpo_hours": 1,
        "method": "COMPONENT_TEST",
        "evidence_ref": "ev-1",
    }
    defaults.update(overrides)
    return defaults


def create_gap_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "severity": "MEDIUM",
        "description": "gap narrative",
        "due_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_comm_node_payload(**overrides) -> dict:
    defaults = {
        "tree_label": "TREE_Default",
        "contact_name": "Duty Officer",
        "role_title": "Duty",
        "parent_node_id": None,
        "order_index": 1,
        "channel": "PHONE",
        "ack_deadline_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_activation_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "declared_severity": "SEV2",
        "activation_criterion": "CRITERION_A",
        "criterion_justification": "drill",
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(**overrides) -> dict:
    defaults = {
        "process_id": None,
        "attestation_type": "REGULATORY",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
