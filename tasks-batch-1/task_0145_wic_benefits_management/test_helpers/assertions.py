"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape/types of a returned resource using
the framework's generic validators. Append-only entities (IncomeRecord,
Redemption) are asserted WITHOUT updated_at / version, matching the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_VENDOR_STATES = {"PENDING", "AUTHORIZED", "SUSPENDED", "TERMINATED"}
_PARTICIPANT_STATES = {"APPLICANT", "ACTIVE", "SUSPENDED", "TERMINATED"}
_APPLICATION_STATES = {"DRAFT", "INCOME_DETERMINED", "RISK_ASSESSED", "APPROVED", "DENIED"}
_CERT_STATES = {"ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"}
_RX_STATES = {"ISSUED", "REDEEMED_PARTIAL", "REDEEMED_FULL", "VOIDED"}
_EBT_STATES = {"OPEN", "FROZEN"}
_APPT_STATES = {"SCHEDULED", "RESCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"}
_SESSION_STATES = {"SCHEDULED", "COMPLETED", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not carry version"
    assert "updated_at" not in data, "append-only entity must not carry updated_at"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["caseload_cap"], int)
    assert isinstance(data["active_caseload_count"], int)
    assert data["active_caseload_count"] >= 0, "caseload count must not be negative"
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["appointment_buffer_minutes"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["legal_name"], str)
    assert data["peer_group"] in {"SMALL", "MEDIUM", "LARGE"}
    assert data["status"] in _VENDOR_STATES, f"unexpected vendor status {data['status']!r}"
    assert isinstance(data["violation_points"], int)
    assert data["violation_points"] >= 0


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["pregnancy_count"], int)
    assert data["adjunctive_program"] in {"NONE", "SNAP", "MEDICAID", "TANF"}


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["ssn_last4"], str)
    assert data["category"] in {"PREGNANT", "POSTPARTUM", "BREASTFEEDING", "INFANT", "CHILD"}
    assert isinstance(data["breastfeeding_opt_in"], bool)
    assert data["status"] in _PARTICIPANT_STATES, f"unexpected participant status {data['status']!r}"
    # priority_level is null until certification assigns it
    assert data["priority_level"] is None or isinstance(data["priority_level"], int)


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert data["income_method"] in {"ANNUALIZE_RECENT", "AVERAGE_ALL"}
    assert data["status"] in _APPLICATION_STATES, f"unexpected application status {data['status']!r}"
    assert isinstance(data["risk_factor_codes"], list)


def assert_certification(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["application_id"], str)
    assert is_iso8601_timestamp(data["period_start_utc"]), "period_start_utc must be ISO 8601"
    assert is_iso8601_timestamp(data["period_end_utc"]), "period_end_utc must be ISO 8601"
    assert isinstance(data["cert_length_days"], int)
    assert data["status"] in _CERT_STATES, f"unexpected certification status {data['status']!r}"


def assert_food_prescription(data: dict):
    _assert_common(data)
    assert isinstance(data["certification_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["issuance_mode"] in {"FULL", "PRORATED"}
    assert isinstance(data["line_items"], list)
    assert isinstance(data["prescribed_value_cents"], int)
    assert data["prescribed_value_cents"] >= 0
    assert data["status"] in _RX_STATES, f"unexpected prescription status {data['status']!r}"


def assert_ebt_account(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["balance_units"], dict)
    assert isinstance(data["issued_value_cents"], int)
    assert isinstance(data["redeemed_value_cents"], int)
    assert isinstance(data["voided_value_cents"], int)
    assert isinstance(data["remaining_value_cents"], int)
    assert data["status"] in _EBT_STATES, f"unexpected EBT status {data['status']!r}"
    assert_ebt_conservation(data)


def assert_income_record(data: dict):
    _assert_append_only(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert data["pay_frequency"] in {"WEEKLY", "BIWEEKLY", "MONTHLY", "ANNUAL"}
    assert isinstance(data["sequence_index"], int)
    assert data["sequence_index"] >= 0


def assert_redemption(data: dict):
    _assert_append_only(data)
    assert isinstance(data["ebt_account_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["food_category"], str)
    assert isinstance(data["units"], int)
    assert isinstance(data["value_cents"], int)
    assert isinstance(data["sequence_index"], int)
    assert data["sequence_index"] >= 0


def assert_clinic_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["clinic_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["purpose"] in {"INITIAL_CERT", "RECERT", "NUTRITION_ED", "BF_SUPPORT"}
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in _APPT_STATES, f"unexpected appointment status {data['status']!r}"


def assert_peer_session(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["peer_counselor_id"], str)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in _SESSION_STATES, f"unexpected session status {data['status']!r}"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_ebt_conservation(data: dict):
    """The conserved-quantity invariant the EBT ledger always maintains:
    remaining_value_cents == issued - redeemed - voided, and is never negative.
    """
    issued = data["issued_value_cents"]
    redeemed = data["redeemed_value_cents"]
    voided = data["voided_value_cents"]
    remaining = data["remaining_value_cents"]
    assert remaining == issued - redeemed - voided, (
        f"remaining_value_cents ({remaining}) must equal issued ({issued}) - "
        f"redeemed ({redeemed}) - voided ({voided})"
    )
    assert remaining >= 0, f"remaining_value_cents must never be negative, got {remaining}"
