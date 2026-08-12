"""Domain thresholds and canonical fixture values drawn from the PRD."""

# Health score constants (PRD §2.9)
HEALTH = {
    "OVERDUE_TRAINING_PENALTY": 15,
    "MISSED_CHECKIN_PENALTY": 10,
    "PROBATION_OVERDUE_PENALTY": 25,
    "PROBATION_OVERDUE_GRACE_DAYS": 7,
    "PROVISIONING_ATTENTION_PENALTY": 20,
    "NO_SHOW_PENALTY": 30,
    "AT_RISK_THRESHOLD": 70,
    "SCORE_FLOOR": 0,
}

# Time-to-productivity slip constants (PRD §3.7)
TTP = {
    "OVERDUE_TRAINING_SLIP_DAYS": 3,
    "MISSED_CHECKIN_SLIP_DAYS": 5,
}

# Survey weights (PRD §3.9)
SURVEY = {
    "W_EXPERIENCE": 0.4,
    "W_MANAGER": 0.3,
    "W_RESOURCES": 0.3,
}

# Check-in cadence (PRD §3.7)
CHECKIN = {
    "BUFFER_MINUTES": 30,
    "MISSED_GRACE_HOURS": 24,
}

# Benefits enrollment window (PRD §3.9)
BENEFITS = {
    "WINDOW_DAYS": 30,
}

# Survey expiry (PRD §3.9)
SURVEY_EXPIRY_DAYS = 14

# Default logical clock at server start (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Canonical profile fixture used across tests. Mirrors the PRD's worked examples:
# 3 tasks (Government ID required DOCUMENT_UPLOAD, NDA required FORM_ACK,
# Handbook optional POLICY_READ), 2 trainings (SEC101 +7d, HR201 +14d),
# 1 equipment (Laptop x1), 1 access (VPN), probation 90d, 1 extension of 30d,
# buddy 2 check-ins at 7-day interval, manager offsets [1, 30], sla 48h.
CANONICAL_PROFILE_PAYLOAD = {
    "name": "SE",
    "preboarding_tasks": [
        {"task_kind": "DOCUMENT_UPLOAD", "title": "Government ID", "is_required": True},
        {"task_kind": "FORM_ACK", "title": "NDA", "is_required": True},
        {"task_kind": "POLICY_READ", "title": "Handbook", "is_required": False},
    ],
    "training_modules": [
        {"module_code": "SEC101", "due_offset_days": 7},
        {"module_code": "HR201", "due_offset_days": 14},
    ],
    "equipment_items": [{"item_name": "Laptop", "quantity": 1}],
    "access_grants": [{"system_name": "VPN", "permission_level": "STANDARD"}],
    "probation_days": 90,
    "max_probation_extensions": 1,
    "extension_days": 30,
    "buddy_checkin_interval_days": 7,
    "buddy_checkin_count": 2,
    "manager_checkin_offsets_days": [1, 30],
    "provisioning_sla_hours": 48,
}

# Canonical case start date used across tests (Monday).
CANONICAL_START_DATE = "2026-05-04"

# Canonical salary figures (mirror the PRD §2.10 worked example).
CANONICAL_BASE_SALARY_CENTS = 90000
CANONICAL_SIGNING_BONUS_CENTS = 10000
CANONICAL_RELOCATION_CENTS = 2500
