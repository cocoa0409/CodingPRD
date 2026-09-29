"""Shape and invariant assertions.

Generic envelope, pagination and error checks come from the framework. What
lives here is domain-specific: the field set each entity must expose, and the
conserved quantities the specification promises hold at all times.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _assert_common(entity, entity_name):
    for field in COMMON_FIELDS:
        assert field in entity, f"{entity_name} is missing {field}: {entity}"
    assert is_valid_uuid(entity["id"]), f"{entity_name} id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{entity_name} created_at is not ISO 8601: {entity['created_at']}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{entity_name} updated_at is not ISO 8601: {entity['updated_at']}"
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{entity_name} version must be a positive integer: {entity['version']}"
    )


def _assert_fields(entity, entity_name, fields):
    for field in fields:
        assert field in entity, f"{entity_name} is missing {field}: {sorted(entity)}"


def assert_originator(entity):
    """An originator carries its filed data plus its computed compliance posture."""
    _assert_common(entity, "Originator")
    _assert_fields(
        entity,
        "Originator",
        (
            "nmls_unique_id",
            "legal_name",
            "hire_date",
            "employment_status",
            "compensation_plan_id",
            "monitoring_status",
            "exposure_score",
            "lifetime_accrued_cents",
            "lifetime_clawed_back_cents",
            "net_compensation_cents",
            "authorized_state_codes",
            "open_investigation_count",
        ),
    )
    assert isinstance(entity["authorized_state_codes"], list)
    assert_authorized_states_sorted(entity)
    assert_net_compensation_conserved(entity)
    assert entity["monitoring_status"] in ("STANDARD", "ELEVATED")
    assert 0 <= entity["exposure_score"] <= 100


def assert_license_registration(entity):
    """A licence carries its filed dates plus its computed CE and sponsorship posture."""
    _assert_common(entity, "LicenseRegistration")
    _assert_fields(
        entity,
        "LicenseRegistration",
        (
            "originator_id",
            "state_code",
            "license_number",
            "issue_date",
            "expiration_date",
            "renewal_window_opens_at",
            "status",
            "authority_effective_at",
            "required_ce_hours",
            "ce_hours_applied",
            "ce_reporting_year",
            "ce_satisfied",
            "active_sponsoring_institution_code",
            "active_sponsorship_effective_at",
            "reinstatement_count",
        ),
    )
    assert isinstance(entity["ce_satisfied"], bool)
    assert isinstance(entity["ce_hours_applied"], int)


def assert_sponsorship_transfer(entity):
    """A sponsorship row owns the interval; the licence only mirrors it."""
    _assert_common(entity, "SponsorshipTransfer")
    _assert_fields(
        entity,
        "SponsorshipTransfer",
        (
            "license_registration_id",
            "sponsoring_institution_code",
            "effective_at",
            "relinquished_at",
            "status",
            "superseded_by_created_at",
        ),
    )


def assert_ce_course(entity):
    """A catalogue course carries its award, its category and its provider standing."""
    _assert_common(entity, "CeCourse")
    _assert_fields(
        entity,
        "CeCourse",
        (
            "course_code",
            "credit_hours",
            "category",
            "approved_state_codes",
            "successive_year_blocked",
            "provider_status",
        ),
    )
    assert isinstance(entity["approved_state_codes"], list)
    assert isinstance(entity["successive_year_blocked"], bool)


def assert_ce_credit_record(entity):
    """A credit row carries its attribution verdict alongside the filing."""
    _assert_common(entity, "CeCreditRecord")
    _assert_fields(
        entity,
        "CeCreditRecord",
        (
            "originator_id",
            "ce_course_id",
            "completion_date",
            "reporting_period_year",
            "is_makeup",
            "credit_hours",
            "category",
            "attributed_year",
            "credit_status",
            "void_reason",
        ),
    )
    assert isinstance(entity["is_makeup"], bool)
    assert isinstance(entity["attributed_year"], int)


def assert_compensation_plan(entity):
    """A plan carries its commission arithmetic, its approval trail and its assignment."""
    _assert_common(entity, "CompensationPlan")
    _assert_fields(
        entity,
        "CompensationPlan",
        (
            "plan_name",
            "drafted_by_user_id",
            "approved_by_user_id",
            "base_basis_points",
            "min_fee_cents",
            "max_fee_cents",
            "salary_cents_per_period",
            "volume_tier_enabled",
            "concession_absorption_enabled",
            "status",
            "prohibited_variable_count",
            "assignment_effective_from",
            "assignment_effective_to",
            "assigned_originator_id",
        ),
    )
    assert isinstance(entity["volume_tier_enabled"], bool)
    assert isinstance(entity["concession_absorption_enabled"], bool)


def assert_compensation_variable(entity):
    """A pay variable carries the permissibility the system, not the designer, decided."""
    _assert_common(entity, "CompensationVariable")
    _assert_fields(
        entity,
        "CompensationVariable",
        (
            "compensation_plan_id",
            "variable_type",
            "permissibility",
            "weight_pct",
            "justification_text",
        ),
    )
    assert entity["permissibility"] in ("PERMISSIBLE", "PROHIBITED")


def assert_loan_application(entity):
    """A loan carries two independent state dimensions plus its authority record."""
    _assert_common(entity, "LoanApplication")
    _assert_fields(
        entity,
        "LoanApplication",
        (
            "originator_id",
            "compensation_plan_id",
            "state_code",
            "borrower_reference",
            "application_taken_at",
            "product_type",
            "requested_amount_cents",
            "par_rate_bps",
            "note_rate_bps",
            "locked_amount_cents",
            "funded_amount_cents",
            "funded_at",
            "payoff_date",
            "lender_paid_comp_cents",
            "borrower_paid_comp_cents",
            "file_quality_score",
            "hours_worked_pct",
            "status",
            "compensation_status",
            "authority_flag",
            "closed_unit_index",
        ),
    )
    assert entity["status"] in ("TAKEN", "LOCKED", "CLOSED", "PAID_OFF", "WITHDRAWN")
    assert entity["compensation_status"] in (
        "NOT_APPLICABLE",
        "PENDING",
        "ACCRUED",
        "RECONCILED",
        "CLAWED_BACK",
    )
    assert entity["authority_flag"] in ("VERIFIED", "SUSPENDED", "UNAUTHORIZED")


def assert_pricing_exception(entity):
    """An exception carries its documented justification and its segregated trail."""
    _assert_common(entity, "PricingException")
    _assert_fields(
        entity,
        "PricingException",
        (
            "loan_application_id",
            "requested_by_user_id",
            "requested_rate_bps",
            "concession_cents",
            "reason_code",
            "justification_text",
            "status",
            "requires_second_approval",
            "decided_by_user_id",
            "second_decided_by_user_id",
            "decided_at",
            "decision_note",
            "comp_impact_cents",
        ),
    )
    assert isinstance(entity["requires_second_approval"], bool)


def assert_compensation_record(entity):
    """A ledger line pins its loan, originator and plan, and never re-points them."""
    _assert_common(entity, "CompensationRecord")
    _assert_fields(
        entity,
        "CompensationRecord",
        (
            "loan_application_id",
            "originator_id",
            "compensation_plan_id",
            "variant",
            "tier_bps_adder",
            "base_comp_cents",
            "comp_impact_cents",
            "accrued_cents",
            "paid_cents",
            "clawback_cents",
            "days_held",
            "recapture_pct",
            "status",
            "reconciled_at",
        ),
    )
    assert entity["variant"] in ("PROVISIONAL", "FINAL")
    assert entity["status"] in ("ACCRUED", "RECONCILED", "CLAWED_BACK")
    assert entity["accrued_cents"] == entity["base_comp_cents"] - entity["comp_impact_cents"], (
        "accrued_cents must equal base_comp_cents less comp_impact_cents: " f"{entity}"
    )


def assert_advertisement(entity):
    """Advertising copy carries what it disclosed and what the inspection found."""
    _assert_common(entity, "Advertisement")
    _assert_fields(
        entity,
        "Advertisement",
        (
            "originator_id",
            "medium",
            "content_text",
            "disclosed_nmls_ids",
            "disclosed_license_numbers",
            "target_state_codes",
            "status",
            "disclosure_findings",
            "reviewed_by_user_id",
            "published_at",
        ),
    )
    findings = entity["disclosure_findings"]
    assert isinstance(findings, list)
    assert findings == sorted(set(findings)), (
        f"disclosure_findings must be de-duplicated and ascending: {findings}"
    )


def assert_examination_inquiry(entity):
    """An inquiry carries its deadline, its round count and its escalation reason."""
    _assert_common(entity, "ExaminationInquiry")
    _assert_fields(
        entity,
        "ExaminationInquiry",
        (
            "originator_id",
            "state_code",
            "exam_reference",
            "opened_at",
            "response_due_at",
            "status",
            "response_round_count",
            "last_response_at",
            "escalation_reason",
        ),
    )
    assert isinstance(entity["response_round_count"], int)


def assert_investigation(entity):
    """An investigation carries how it was opened and what it concluded."""
    _assert_common(entity, "UnlicensedActivityInvestigation")
    _assert_fields(
        entity,
        "UnlicensedActivityInvestigation",
        (
            "originator_id",
            "loan_application_id",
            "opened_by",
            "detected_at",
            "trigger_reason",
            "status",
            "finding_by_user_id",
            "restitution_cents",
            "remediated_at",
        ),
    )
    assert entity["opened_by"] in ("CASCADE", "MANUAL")


def assert_audit_event(entity):
    """The audit trail is append-only: no updated_at and no version at all."""
    for field in (
        "id",
        "subject_type",
        "subject_ref",
        "event_type",
        "actor_role",
        "actor_user_id",
        "detail",
        "sequence_no",
        "created_at",
    ):
        assert field in entity, f"AuditEvent is missing {field}: {sorted(entity)}"
    assert "updated_at" not in entity, "an audit entry must not carry updated_at"
    assert "version" not in entity, "an audit entry must not carry version"
    assert is_valid_uuid(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"])
    assert isinstance(entity["sequence_no"], int) and entity["sequence_no"] >= 1


# ---------------------------------------------------------------------------
# Conserved quantities and ordering promises
# ---------------------------------------------------------------------------


def assert_net_compensation_conserved(originator):
    """`net_compensation_cents` is a derived balance with zero drift."""
    expected = originator["lifetime_accrued_cents"] - originator["lifetime_clawed_back_cents"]
    assert originator["net_compensation_cents"] == expected, (
        "net_compensation_cents must be lifetime_accrued_cents less "
        f"lifetime_clawed_back_cents: {originator['net_compensation_cents']} != {expected}"
    )


def assert_authorized_states_sorted(originator):
    """Authorised state codes are held sorted in ascending order."""
    codes = originator["authorized_state_codes"]
    assert codes == sorted(codes), f"authorized_state_codes must be ascending: {codes}"


def assert_ce_hours_total(license_registration, expected_hours):
    """A licence's applied hours equal the hours currently counting for its year."""
    assert license_registration["ce_hours_applied"] == expected_hours, (
        "ce_hours_applied must be the total of the counted set: "
        f"{license_registration['ce_hours_applied']} != {expected_hours}"
    )


def assert_audit_sequence_strictly_increasing(events):
    """Audit entries are ordered by their own monotonic sequence number."""
    numbers = [event["sequence_no"] for event in events]
    assert numbers == sorted(numbers), f"audit sequence must ascend: {numbers}"
    assert len(set(numbers)) == len(numbers), f"audit sequence must be unique: {numbers}"


def assert_event_types_in_order(events, expected_types):
    """The trail reads as the causal chain the cascade executed."""
    actual = [event["event_type"] for event in events]
    assert actual == list(expected_types), (
        f"audit event types out of order: {actual} != {list(expected_types)}"
    )


def assert_ledger_line_terminal_clawback(record):
    """A clawed-back line records the day count, share and recaptured amount."""
    assert record["status"] == "CLAWED_BACK"
    assert record["days_held"] is not None
    assert record["recapture_pct"] is not None
    assert record["clawback_cents"] >= 0
