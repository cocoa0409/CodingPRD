"""Path-id (priority 5) and body-FK (priority 6) resolution."""
from db import store
from errors import ApiError

TARGETS = {
    "facility": ("facilities", "ERR_FACILITY_NOT_FOUND"),
    "provider": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "infant": ("infants", "ERR_INFANT_NOT_FOUND"),
    "encounter": ("encounters", "ERR_ENCOUNTER_NOT_FOUND"),
    "episode": ("episodes", "ERR_EPISODE_NOT_FOUND"),
    "slot": ("slots", "ERR_SLOT_NOT_FOUND"),
    "appointment": ("appointments", "ERR_APPOINTMENT_NOT_FOUND"),
    "evaluation": ("evaluations", "ERR_EVALUATION_NOT_FOUND"),
    "referral": ("referrals", "ERR_REFERRAL_NOT_FOUND"),
    "risk_entry": ("risk_entries", "ERR_RISK_ENTRY_NOT_FOUND"),
    "task": ("tasks", "ERR_TASK_NOT_FOUND"),
    "period": ("periods", "ERR_PERIOD_NOT_FOUND"),
    "report": ("reports", "ERR_REPORT_NOT_FOUND"),
}

# Body foreign keys are resolved in this fixed order (PRD 2.11 step 6).
FK_ORDER = (
    ("birth_facility_id", "facility"),
    ("facility_id", "facility"),
    ("provider_id", "provider"),
    ("performed_by_provider_id", "provider"),
    ("infant_id", "infant"),
    ("episode_id", "episode"),
    ("slot_id", "slot"),
    ("appointment_id", "appointment"),
    ("prior_encounter_id", "encounter"),
    ("supersedes_episode_id", "episode"),
    ("supersedes_report_id", "report"),
    ("reporting_period_id", "period"),
    ("assigned_provider_id", "provider"),
    ("ei_program_facility_id", "facility"),
)


def one(kind, identifier):
    collection, error_id = TARGETS[kind]
    row = getattr(store, collection).get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def fks(values):
    """Resolve the supplied body foreign keys in the pinned order."""
    resolved = {}
    for key, kind in FK_ORDER:
        if key in values and values[key] is not None:
            resolved[key] = one(kind, values[key])
    return resolved
