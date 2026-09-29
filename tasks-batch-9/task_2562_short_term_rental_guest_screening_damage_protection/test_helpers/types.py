"""Shape checks for every resource representation the contract returns.

Each ``assert_is_<entity>`` walks the representation described in PRD §3 and
checks that every declared field is present with a value of the declared type,
that every enumerated field carries one of its declared values, and that the
common properties of PRD §2.4 appear exactly where the PRD says they do — three
rows are written once and never mutated, so they carry only ``id`` and
``created_at``.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants


def _assert_keys(data, field_names, label):
    missing = [name for name in field_names if name not in data]
    assert not missing, "{0} is missing declared fields {1}; got {2}".format(
        label, missing, sorted(data.keys())
    )


def assert_is_uuid(value, label):
    assert isinstance(value, str), "{0} must be a string, got {1!r}".format(label, value)
    assert is_valid_uuid(value), "{0} must be a UUID, got {1!r}".format(label, value)


def assert_is_timestamp(value, label):
    assert isinstance(value, str), "{0} must be a string, got {1!r}".format(label, value)
    assert is_iso8601_timestamp(value), "{0} must be ISO-8601, got {1!r}".format(
        label, value
    )


def assert_is_date(value, label):
    assert isinstance(value, str), "{0} must be a string, got {1!r}".format(label, value)
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        "{0} must be YYYY-MM-DD, got {1!r}".format(label, value)
    )
    year, month, day = value.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit(), (
        "{0} must be YYYY-MM-DD, got {1!r}".format(label, value)
    )


def assert_is_int(data, field, label, minimum=None):
    value = data[field]
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{0}.{1} must be an integer, got {2!r}".format(label, field, value)
    )
    if minimum is not None:
        assert value >= minimum, "{0}.{1} must be >= {2}, got {3}".format(
            label, field, minimum, value
        )


def assert_is_nullable_int(data, field, label, minimum=None):
    if data[field] is None:
        return
    assert_is_int(data, field, label, minimum=minimum)


def assert_is_bool(data, field, label):
    assert isinstance(data[field], bool), "{0}.{1} must be a boolean, got {2!r}".format(
        label, field, data[field]
    )


def assert_is_string(data, field, label, allow_null=False):
    value = data[field]
    if value is None:
        assert allow_null, "{0}.{1} must not be null".format(label, field)
        return
    assert isinstance(value, str), "{0}.{1} must be a string, got {2!r}".format(
        label, field, value
    )


def assert_is_number(data, field, label):
    value = data[field]
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "{0}.{1} must be numeric, got {2!r}".format(label, field, value)
    )


def assert_enum(data, field, allowed, label, allow_null=False):
    value = data[field]
    if value is None and allow_null:
        return
    assert value in allowed, "{0}.{1} must be one of {2}, got {3!r}".format(
        label, field, list(allowed), value
    )


def assert_nullable_uuid(data, field, label):
    if data[field] is not None:
        assert_is_uuid(data[field], "{0}.{1}".format(label, field))


def assert_nullable_timestamp(data, field, label):
    if data[field] is not None:
        assert_is_timestamp(data[field], "{0}.{1}".format(label, field))


def assert_nullable_date(data, field, label):
    if data[field] is not None:
        assert_is_date(data[field], "{0}.{1}".format(label, field))


def assert_common_properties(data, label):
    """id, created_at, updated_at and version, per PRD §2.4."""
    _assert_keys(data, ("id", "created_at", "updated_at", "version"), label)
    assert_is_uuid(data["id"], "{0}.id".format(label))
    assert_is_timestamp(data["created_at"], "{0}.created_at".format(label))
    assert_is_timestamp(data["updated_at"], "{0}.updated_at".format(label))
    assert_is_int(data, "version", label, minimum=1)


def assert_write_once_properties(data, label):
    """Rule sets, evidence and allocations carry only id and created_at (PRD §2.4)."""
    _assert_keys(data, ("id", "created_at"), label)
    assert_is_uuid(data["id"], "{0}.id".format(label))
    assert_is_timestamp(data["created_at"], "{0}.created_at".format(label))
    assert "updated_at" not in data, (
        "{0} must not carry updated_at; the row is never mutated".format(label)
    )
    assert "version" not in data, (
        "{0} must not carry version; the row is never mutated".format(label)
    )


GUEST_FIELDS = (
    "full_name",
    "email",
    "country_code",
    "payment_risk_signal",
    "chargeback_count",
    "verification_state",
    "accepted_doc_count",
    "accepted_gov_id_count",
    "completed_stay_count",
    "substantiated_incident_count",
    "escalated_incident_count",
    "approved_claim_count",
    "risk_score",
    "risk_tier",
    "deposit_held_cents",
    "active_blocklist_scope_count",
)


def assert_is_guest(data, label="guest"):
    """A guest account with its verification, risk and exposure counters."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, GUEST_FIELDS, label)
    assert_is_string(data, "full_name", label)
    assert_is_string(data, "email", label)
    assert_is_string(data, "country_code", label)
    assert_enum(data, "payment_risk_signal", constants.PAYMENT_RISK_SIGNALS, label)
    assert_enum(data, "verification_state", constants.VERIFICATION_STATES, label)
    assert_enum(data, "risk_tier", constants.RISK_TIERS, label)
    for field in (
        "chargeback_count",
        "accepted_doc_count",
        "accepted_gov_id_count",
        "completed_stay_count",
        "substantiated_incident_count",
        "escalated_incident_count",
        "approved_claim_count",
        "deposit_held_cents",
        "active_blocklist_scope_count",
    ):
        assert_is_int(data, field, label, minimum=0)
    assert_is_int(data, "risk_score", label, minimum=constants.SCORE_MIN)
    assert data["risk_score"] <= constants.SCORE_MAX, (
        "{0}.risk_score must be <= {1}, got {2}".format(
            label, constants.SCORE_MAX, data["risk_score"]
        )
    )


HOST_FIELDS = (
    "legal_name",
    "email",
    "payout_hold",
    "settled_claim_count",
    "denied_claim_count",
    "total_recovered_cents",
)


def assert_is_host(data, label="host"):
    """A host account with its settlement counters and payout-hold flag."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, HOST_FIELDS, label)
    assert_is_string(data, "legal_name", label)
    assert_is_string(data, "email", label)
    assert_is_bool(data, "payout_hold", label)
    for field in ("settled_claim_count", "denied_claim_count", "total_recovered_cents"):
        assert_is_int(data, field, label, minimum=0)


JURISDICTION_RULE_FIELDS = (
    "jurisdiction_code",
    "min_stay_nights",
    "max_occupancy_cap",
    "events_prohibited",
    "registration_required",
    "indoor_camera_allowed",
    "indoor_audio_allowed",
    "sensor_notice_required",
    "noise_threshold_db",
)


def assert_is_jurisdiction_rule(data, label="jurisdiction_rule"):
    """An immutable local rule set; written once, so no updated_at or version."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_write_once_properties(data, label)
    _assert_keys(data, JURISDICTION_RULE_FIELDS, label)
    assert_is_string(data, "jurisdiction_code", label)
    for field in ("min_stay_nights", "max_occupancy_cap", "noise_threshold_db"):
        assert_is_int(data, field, label, minimum=0)
    for field in (
        "events_prohibited",
        "registration_required",
        "indoor_camera_allowed",
        "indoor_audio_allowed",
        "sensor_notice_required",
    ):
        assert_is_bool(data, field, label)


PROPERTY_FIELDS = (
    "host_id",
    "jurisdiction_rule_id",
    "address_line",
    "city",
    "registration_number",
    "max_occupancy",
    "bedrooms",
    "nightly_rate_cents",
    "protection_product",
    "deposit_amount_cents",
    "waiver_nightly_fee_cents",
    "claim_ceiling_cents",
    "event_policy",
    "turnover_buffer_nights",
    "listing_state",
    "suspension_reason",
    "sensor_compliance_state",
    "coverage_posture",
    "open_reservation_count",
    "open_claim_count",
)


def assert_is_property(data, label="property"):
    """A listing with its three postures and its open counters."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, PROPERTY_FIELDS, label)
    assert_is_uuid(data["host_id"], "{0}.host_id".format(label))
    assert_is_uuid(data["jurisdiction_rule_id"], "{0}.jurisdiction_rule_id".format(label))
    assert_is_string(data, "address_line", label)
    assert_is_string(data, "city", label)
    assert_is_string(data, "registration_number", label, allow_null=True)
    assert_enum(data, "protection_product", constants.PROTECTION_PRODUCTS, label)
    assert_enum(data, "event_policy", constants.EVENT_POLICIES, label)
    assert_enum(data, "listing_state", constants.LISTING_STATES, label)
    assert_enum(
        data, "suspension_reason", constants.SUSPENSION_REASONS, label, allow_null=True
    )
    assert_enum(
        data, "sensor_compliance_state", constants.SENSOR_COMPLIANCE_STATES, label
    )
    assert_enum(data, "coverage_posture", constants.COVERAGE_POSTURES, label)
    for field in (
        "max_occupancy",
        "bedrooms",
        "nightly_rate_cents",
        "deposit_amount_cents",
        "waiver_nightly_fee_cents",
        "claim_ceiling_cents",
        "turnover_buffer_nights",
        "open_reservation_count",
        "open_claim_count",
    ):
        assert_is_int(data, field, label, minimum=0)


MONITORING_DEVICE_FIELDS = (
    "property_id",
    "device_type",
    "placement_zone",
    "records_audio",
    "guest_disclosure_text",
    "disclosure_state",
    "reject_reason_code",
    "reviewed_by_user_id",
)


def assert_is_monitoring_device(data, label="monitoring_device"):
    """A sensor or camera at a listing, with its disclosure review position."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, MONITORING_DEVICE_FIELDS, label)
    assert_is_uuid(data["property_id"], "{0}.property_id".format(label))
    assert_enum(data, "device_type", constants.DEVICE_TYPES, label)
    assert_enum(data, "placement_zone", constants.PLACEMENT_ZONES, label)
    assert_is_bool(data, "records_audio", label)
    assert_is_string(data, "guest_disclosure_text", label, allow_null=True)
    assert_enum(data, "disclosure_state", constants.DISCLOSURE_STATES, label)
    assert_enum(
        data,
        "reject_reason_code",
        constants.DEVICE_REJECT_REASON_CODES,
        label,
        allow_null=True,
    )
    assert_is_string(data, "reviewed_by_user_id", label, allow_null=True)


IDENTITY_DOCUMENT_FIELDS = (
    "guest_id",
    "doc_type",
    "issuing_country",
    "document_ref",
    "expires_on",
    "review_state",
    "reject_reason_code",
    "reviewed_by_user_id",
)


def assert_is_identity_document(data, label="identity_document"):
    """One verification artifact belonging to a guest."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, IDENTITY_DOCUMENT_FIELDS, label)
    assert_is_uuid(data["guest_id"], "{0}.guest_id".format(label))
    assert_enum(data, "doc_type", constants.DOC_TYPES, label)
    assert_is_string(data, "issuing_country", label)
    assert_is_string(data, "document_ref", label)
    assert_is_timestamp(data["expires_on"], "{0}.expires_on".format(label))
    assert_enum(data, "review_state", constants.DOC_REVIEW_STATES, label)
    assert_enum(
        data,
        "reject_reason_code",
        constants.DOC_REJECT_REASON_CODES,
        label,
        allow_null=True,
    )
    assert_is_string(data, "reviewed_by_user_id", label, allow_null=True)


RESERVATION_FIELDS = (
    "guest_id",
    "property_id",
    "check_in",
    "check_out",
    "guest_count",
    "event_declared",
    "nights",
    "check_in_at",
    "check_out_at",
    "claim_window_ends_at",
    "screening_state",
    "screening_reason_code",
    "risk_score_at_booking",
    "risk_tier_at_booking",
    "screening_decided_by_user_id",
    "stay_state",
    "cancel_reason_code",
    "deposit_state",
    "deposit_hold_cents",
    "deposit_applied_cents",
    "deposit_refunded_cents",
    "accommodation_cents",
    "waiver_fee_cents",
    "pre_fee_subtotal_cents",
    "trust_fee_pct",
    "trust_fee_cents",
    "total_charged_cents",
)


def assert_is_reservation(data, label="reservation"):
    """A booking across its screening, stay and deposit dimensions."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, RESERVATION_FIELDS, label)
    assert_is_uuid(data["guest_id"], "{0}.guest_id".format(label))
    assert_is_uuid(data["property_id"], "{0}.property_id".format(label))
    assert_is_date(data["check_in"], "{0}.check_in".format(label))
    assert_is_date(data["check_out"], "{0}.check_out".format(label))
    assert_is_bool(data, "event_declared", label)
    assert_is_timestamp(data["check_in_at"], "{0}.check_in_at".format(label))
    assert_is_timestamp(data["check_out_at"], "{0}.check_out_at".format(label))
    assert_nullable_timestamp(data, "claim_window_ends_at", label)
    assert_enum(data, "screening_state", constants.SCREENING_STATES, label)
    assert_enum(
        data,
        "screening_reason_code",
        constants.SCREENING_REASON_CODES,
        label,
        allow_null=True,
    )
    assert_enum(data, "risk_tier_at_booking", constants.RISK_TIERS, label)
    assert_is_string(data, "screening_decided_by_user_id", label, allow_null=True)
    assert_enum(data, "stay_state", constants.STAY_STATES, label)
    assert_enum(
        data, "cancel_reason_code", constants.CANCEL_REASON_CODES, label, allow_null=True
    )
    assert_enum(data, "deposit_state", constants.DEPOSIT_STATES, label)
    assert_is_number(data, "trust_fee_pct", label)
    for field in (
        "guest_count",
        "nights",
        "risk_score_at_booking",
        "deposit_hold_cents",
        "deposit_applied_cents",
        "deposit_refunded_cents",
        "accommodation_cents",
        "waiver_fee_cents",
        "pre_fee_subtotal_cents",
        "trust_fee_cents",
        "total_charged_cents",
    ):
        assert_is_int(data, field, label, minimum=0)


INCIDENT_FIELDS = (
    "reservation_id",
    "sensor_device_id",
    "incident_type",
    "severity",
    "source",
    "detected_at",
    "description",
    "decibel_reading",
    "observed_occupancy",
    "complainant_ref",
    "incident_state",
    "substantiated",
    "escalated",
    "law_enforcement_ref",
    "response_due_at",
    "response_sla_breached",
    "dismiss_reason_code",
)


def assert_is_incident(data, label="incident"):
    """A trust-and-safety report against a stay, with its triage position."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, INCIDENT_FIELDS, label)
    assert_is_uuid(data["reservation_id"], "{0}.reservation_id".format(label))
    assert_nullable_uuid(data, "sensor_device_id", label)
    assert_enum(data, "incident_type", constants.INCIDENT_TYPES, label)
    assert_enum(data, "severity", constants.INCIDENT_SEVERITIES, label)
    assert_enum(data, "source", constants.INCIDENT_SOURCES, label)
    assert_is_timestamp(data["detected_at"], "{0}.detected_at".format(label))
    assert_is_string(data, "description", label)
    if data["decibel_reading"] is not None:
        assert_is_number(data, "decibel_reading", label)
    assert_is_nullable_int(data, "observed_occupancy", label, minimum=0)
    assert_is_string(data, "complainant_ref", label, allow_null=True)
    assert_enum(data, "incident_state", constants.INCIDENT_STATES, label)
    assert_is_bool(data, "substantiated", label)
    assert_is_bool(data, "escalated", label)
    assert_is_string(data, "law_enforcement_ref", label, allow_null=True)
    assert_nullable_timestamp(data, "response_due_at", label)
    assert_is_bool(data, "response_sla_breached", label)
    assert_enum(
        data, "dismiss_reason_code", constants.DISMISS_REASON_CODES, label, allow_null=True
    )


DAMAGE_CLAIM_FIELDS = (
    "reservation_id",
    "incident_id",
    "host_id",
    "claimed_amount_cents",
    "description",
    "claim_state",
    "evidence_round",
    "evidence_count",
    "submitted_for_review_at",
    "adjudication_due_at",
    "sla_lapsed",
    "decided_at",
    "decided_by_user_id",
    "decision_reason_code",
    "approved_amount_cents",
    "projected_recovery_cents",
    "deposit_applied_cents",
    "recovered_cents",
    "uncovered_cents",
    "host_absorbed_cents",
    "appeal_due_at",
    "appeal_round",
    "appealed_by_role",
    "appeal_decided_by_user_id",
    "appeal_decision",
)


def assert_is_damage_claim(data, label="damage_claim"):
    """A claim with its adjudication deadlines, appeal position and money split."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, DAMAGE_CLAIM_FIELDS, label)
    assert_is_uuid(data["reservation_id"], "{0}.reservation_id".format(label))
    assert_nullable_uuid(data, "incident_id", label)
    assert_is_uuid(data["host_id"], "{0}.host_id".format(label))
    assert_is_string(data, "description", label)
    assert_enum(data, "claim_state", constants.CLAIM_STATES, label)
    assert_nullable_timestamp(data, "submitted_for_review_at", label)
    assert_nullable_timestamp(data, "adjudication_due_at", label)
    assert_is_bool(data, "sla_lapsed", label)
    assert_nullable_timestamp(data, "decided_at", label)
    assert_is_string(data, "decided_by_user_id", label, allow_null=True)
    assert_enum(
        data,
        "decision_reason_code",
        constants.DECISION_REASON_CODES,
        label,
        allow_null=True,
    )
    assert_nullable_timestamp(data, "appeal_due_at", label)
    assert_enum(
        data, "appealed_by_role", constants.APPEALING_ROLES, label, allow_null=True
    )
    assert_is_string(data, "appeal_decided_by_user_id", label, allow_null=True)
    assert_enum(data, "appeal_decision", constants.APPEAL_DECISIONS, label, allow_null=True)
    for field in (
        "claimed_amount_cents",
        "evidence_round",
        "evidence_count",
        "approved_amount_cents",
        "projected_recovery_cents",
        "deposit_applied_cents",
        "recovered_cents",
        "uncovered_cents",
        "host_absorbed_cents",
        "appeal_round",
    ):
        assert_is_int(data, field, label, minimum=0)


CLAIM_EVIDENCE_FIELDS = (
    "claim_id",
    "evidence_type",
    "amount_cents",
    "captured_at",
    "file_ref",
    "uploaded_by_role",
    "uploaded_by_user_id",
    "evidence_round",
)


def assert_is_claim_evidence(data, label="claim_evidence"):
    """One uploaded artifact; written once, so no updated_at or version."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_write_once_properties(data, label)
    _assert_keys(data, CLAIM_EVIDENCE_FIELDS, label)
    assert_is_uuid(data["claim_id"], "{0}.claim_id".format(label))
    assert_enum(data, "evidence_type", constants.EVIDENCE_TYPES, label)
    assert_is_nullable_int(data, "amount_cents", label, minimum=0)
    assert_is_timestamp(data["captured_at"], "{0}.captured_at".format(label))
    assert_is_string(data, "file_ref", label)
    assert_enum(data, "uploaded_by_role", constants.EVIDENCE_UPLOADER_ROLES, label)
    assert_is_string(data, "uploaded_by_user_id", label)
    assert_is_int(data, "evidence_round", label, minimum=1)


COVERAGE_LAYER_FIELDS = (
    "source",
    "layer_order",
    "limit_cents",
    "deductible_cents",
    "coverage_pct",
    "scope",
    "property_id",
    "layer_state",
    "consumed_cents",
)


def assert_is_coverage_layer(data, label="coverage_layer"):
    """One rung of the settlement waterfall with the capacity it has spent."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, COVERAGE_LAYER_FIELDS, label)
    assert_enum(data, "source", constants.COVERAGE_SOURCES, label)
    assert_enum(data, "scope", constants.COVERAGE_SCOPES, label)
    assert_enum(data, "layer_state", constants.LAYER_STATES, label)
    assert_nullable_uuid(data, "property_id", label)
    assert_is_number(data, "coverage_pct", label)
    for field in ("layer_order", "limit_cents", "deductible_cents", "consumed_cents"):
        assert_is_int(data, field, label, minimum=0)


SETTLEMENT_ALLOCATION_FIELDS = (
    "claim_id",
    "coverage_layer_id",
    "sequence_index",
    "gross_cents",
    "deductible_cents",
    "allocated_cents",
    "voided",
)


def assert_is_settlement_allocation(data, label="settlement_allocation"):
    """One waterfall line; emitted by a cascade and never updated in place."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_write_once_properties(data, label)
    _assert_keys(data, SETTLEMENT_ALLOCATION_FIELDS, label)
    assert_is_uuid(data["claim_id"], "{0}.claim_id".format(label))
    assert_is_uuid(data["coverage_layer_id"], "{0}.coverage_layer_id".format(label))
    assert_is_bool(data, "voided", label)
    for field in (
        "sequence_index",
        "gross_cents",
        "deductible_cents",
        "allocated_cents",
    ):
        assert_is_int(data, field, label, minimum=0)


BLOCKLIST_ENTRY_FIELDS = (
    "guest_id",
    "scope",
    "property_id",
    "host_id",
    "supersedes_entry_id",
    "reason_code",
    "created_by_role",
    "created_by_user_id",
    "auto_generated",
    "entry_state",
    "dispute_window_state",
    "dispute_due_at",
    "dispute_statement_code",
    "dispute_decided_by_user_id",
    "dispute_reason_code",
)


def assert_is_blocklist_entry(data, label="blocklist_entry"):
    """A ban across its enforcement dimension and its dispute-window dimension."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    assert_common_properties(data, label)
    _assert_keys(data, BLOCKLIST_ENTRY_FIELDS, label)
    assert_is_uuid(data["guest_id"], "{0}.guest_id".format(label))
    assert_enum(data, "scope", constants.BLOCKLIST_SCOPES, label)
    assert_nullable_uuid(data, "property_id", label)
    assert_nullable_uuid(data, "host_id", label)
    assert_nullable_uuid(data, "supersedes_entry_id", label)
    assert_enum(data, "reason_code", constants.BLOCKLIST_REASON_CODES, label)
    assert_enum(data, "created_by_role", constants.CREATED_BY_ROLES, label)
    assert_is_string(data, "created_by_user_id", label)
    assert_is_bool(data, "auto_generated", label)
    assert_enum(data, "entry_state", constants.ENTRY_STATES, label)
    assert_enum(data, "dispute_window_state", constants.DISPUTE_WINDOW_STATES, label)
    assert_nullable_timestamp(data, "dispute_due_at", label)
    assert_enum(
        data,
        "dispute_statement_code",
        constants.DISPUTE_STATEMENT_CODES,
        label,
        allow_null=True,
    )
    assert_is_string(data, "dispute_decided_by_user_id", label, allow_null=True)
    assert_enum(
        data,
        "dispute_reason_code",
        constants.DISPUTE_REASON_CODES,
        label,
        allow_null=True,
    )


def assert_is_sweep_report(data, label="sweep_report"):
    """The seven phase counters plus the clock reading the sweep used (PRD §3.10)."""
    assert isinstance(data, dict), "{0} must be an object, got {1!r}".format(label, data)
    _assert_keys(data, ("swept_at",) + constants.SWEEP_COUNTER_FIELDS, label)
    assert_is_timestamp(data["swept_at"], "{0}.swept_at".format(label))
    for field in constants.SWEEP_COUNTER_FIELDS:
        assert_is_int(data, field, label, minimum=0)
