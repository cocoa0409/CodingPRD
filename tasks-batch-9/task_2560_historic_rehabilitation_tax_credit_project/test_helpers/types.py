"""Shape checks for every resource representation the contract returns.

Each ``assert_is_<entity>`` walks the representation described in PRD §3 and
checks that every declared field is present with a value of the declared type,
that every enumerated field carries one of its declared values, and that the
common properties of PRD §2.4 appear exactly where the PRD says they do.
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


def assert_enum(data, field, allowed, label):
    value = data[field]
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


def assert_identity_row_properties(data, label):
    """Developers and Reviewers carry only id and created_at, per PRD §2.4."""
    _assert_keys(data, ("id", "created_at"), label)
    assert_is_uuid(data["id"], "{0}.id".format(label))
    assert_is_timestamp(data["created_at"], "{0}.created_at".format(label))
    assert "updated_at" not in data, (
        "{0} must not carry updated_at; it is never mutated".format(label)
    )
    assert "version" not in data, (
        "{0} must not carry version; it is never mutated".format(label)
    )


def assert_is_developer(data):
    label = "developer"
    assert_identity_row_properties(data, label)
    _assert_keys(
        data, ("legal_name", "taxpayer_id_last4", "entity_type", "contact_email"), label
    )
    assert_is_string(data, "legal_name", label)
    assert_is_string(data, "taxpayer_id_last4", label)
    assert_enum(data, "entity_type", constants.DEVELOPER_ENTITY_TYPES, label)
    assert_is_string(data, "contact_email", label, allow_null=True)


def assert_is_reviewer(data):
    label = "reviewer"
    assert_identity_row_properties(data, label)
    _assert_keys(data, ("full_name", "agency", "state_code", "credential_status"), label)
    assert_is_string(data, "full_name", label)
    assert_enum(data, "agency", constants.AGENCIES, label)
    assert_is_string(data, "state_code", label)
    assert_enum(data, "credential_status", constants.CREDENTIAL_STATUSES, label)


def assert_is_property(data):
    label = "property"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "name",
            "street_address",
            "city",
            "state_code",
            "year_built",
            "listing_status",
            "evaluation_status",
            "certified_at",
            "open_project_count",
        ),
        label,
    )
    assert_is_string(data, "name", label)
    assert_is_string(data, "street_address", label)
    assert_is_string(data, "city", label)
    assert_is_string(data, "state_code", label)
    assert_is_int(data, "year_built", label)
    assert_enum(data, "listing_status", constants.LISTING_STATUSES, label)
    assert_enum(data, "evaluation_status", constants.EVALUATION_STATUSES, label)
    assert_nullable_timestamp(data, "certified_at", label)
    assert_is_int(data, "open_project_count", label, minimum=0)


def assert_is_project(data):
    label = "project"
    assert_common_properties(data, label)
    money_fields = (
        "adjusted_basis_cents",
        "qre_total_final_cents",
        "qre_total_provisional_cents",
        "nonqualified_total_cents",
        "classified_cost_total_cents",
        "developer_fee_disallowed_cents",
        "substantial_test_threshold_cents",
        "annual_credit_cents",
        "total_claimable_credit_cents",
        "credit_claimed_to_date_cents",
        "credit_recaptured_cents",
        "credit_unclaimed_cents",
        "recapture_balance_cents",
    )
    _assert_keys(
        data,
        (
            "property_id",
            "developer_id",
            "project_name",
            "structure_type",
            "measuring_period_months",
            "measuring_period_start_date",
            "measuring_period_end_date",
            "certification_status",
            "compliance_status",
            "substantial_test_status",
            "placed_in_service_date",
            "max_investor_risk_score",
            "frozen_at_certification",
        )
        + money_fields,
        label,
    )
    assert_is_uuid(data["property_id"], "project.property_id")
    assert_is_uuid(data["developer_id"], "project.developer_id")
    assert_is_string(data, "project_name", label)
    assert_enum(data, "structure_type", constants.STRUCTURE_TYPES, label)
    assert_is_int(data, "measuring_period_months", label)
    assert_is_date(data["measuring_period_start_date"], "project.start")
    assert_is_date(data["measuring_period_end_date"], "project.end")
    assert_enum(data, "certification_status", constants.CERTIFICATION_STATUSES, label)
    assert_enum(data, "compliance_status", constants.COMPLIANCE_STATUSES, label)
    assert_enum(
        data, "substantial_test_status", constants.SUBSTANTIAL_TEST_STATUSES, label
    )
    assert_nullable_date(data, "placed_in_service_date", label)
    assert_is_int(data, "max_investor_risk_score", label, minimum=0)
    assert_is_bool(data, "frozen_at_certification", label)
    for field in money_fields:
        assert_is_int(data, field, label, minimum=0)


def assert_is_part_application(data):
    label = "part_application"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "part_number",
            "narrative",
            "status",
            "supersedes_application_id",
            "review_round",
            "shpo_reviewer_id",
            "nps_reviewer_id",
            "submitted_at",
            "review_window_end",
            "decision_at",
            "shpo_recommendation",
            "determination",
            "unresolved_condition_count",
            "unresolved_violation_count",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "part_application.project_id")
    assert_is_int(data, "part_number", label)
    assert data["part_number"] in (1, 2, 3), (
        "part_application.part_number must be 1, 2 or 3, got {0!r}".format(
            data["part_number"]
        )
    )
    assert_is_string(data, "narrative", label)
    assert_enum(data, "status", constants.PART_APPLICATION_STATUSES, label)
    assert_nullable_uuid(data, "supersedes_application_id", label)
    assert_is_int(data, "review_round", label, minimum=1)
    assert_nullable_uuid(data, "shpo_reviewer_id", label)
    assert_nullable_uuid(data, "nps_reviewer_id", label)
    assert_nullable_timestamp(data, "submitted_at", label)
    assert_nullable_timestamp(data, "review_window_end", label)
    assert_nullable_timestamp(data, "decision_at", label)
    assert_enum(data, "shpo_recommendation", constants.SHPO_RECOMMENDATIONS, label)
    assert_enum(data, "determination", constants.DETERMINATIONS, label)
    assert_is_int(data, "unresolved_condition_count", label, minimum=0)
    assert_is_int(data, "unresolved_violation_count", label, minimum=0)


def assert_is_finding(data):
    label = "finding"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "part_application_id",
            "standard_number",
            "severity",
            "description",
            "resolution_state",
        ),
        label,
    )
    assert_is_uuid(data["part_application_id"], "finding.part_application_id")
    assert_is_int(data, "standard_number", label, minimum=constants.STANDARD_NUMBER_MIN)
    assert data["standard_number"] <= constants.STANDARD_NUMBER_MAX
    assert_enum(data, "severity", constants.FINDING_SEVERITIES, label)
    assert_is_string(data, "description", label)
    assert_enum(data, "resolution_state", constants.FINDING_RESOLUTION_STATES, label)


def assert_is_cost_line_item(data):
    label = "cost_line_item"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "vendor_name",
            "category",
            "amount_cents",
            "incurred_date",
            "classification",
            "exclusion_reason",
            "in_measuring_period",
            "reclassification_count",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "cost_line_item.project_id")
    assert_is_string(data, "vendor_name", label)
    assert_enum(data, "category", constants.COST_CATEGORIES, label)
    assert_is_int(data, "amount_cents", label, minimum=1)
    assert_is_date(data["incurred_date"], "cost_line_item.incurred_date")
    assert_enum(data, "classification", constants.COST_CLASSIFICATIONS, label)
    assert_enum(data, "exclusion_reason", constants.EXCLUSION_REASONS, label)
    assert_is_bool(data, "in_measuring_period", label)
    assert_is_int(data, "reclassification_count", label, minimum=0)


def assert_is_amendment(data):
    label = "amendment"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "part_application_id",
            "addresses_finding_id",
            "scope_category",
            "change_description",
            "cost_delta_cents",
            "requires_nps_concurrence",
            "status",
            "shpo_decision",
            "nps_decision",
            "submitted_at",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "amendment.project_id")
    assert_is_uuid(data["part_application_id"], "amendment.part_application_id")
    assert_nullable_uuid(data, "addresses_finding_id", label)
    assert_enum(data, "scope_category", constants.SCOPE_CATEGORIES, label)
    assert_is_string(data, "change_description", label)
    assert_is_int(data, "cost_delta_cents", label)
    assert_is_bool(data, "requires_nps_concurrence", label)
    assert_enum(data, "status", constants.AMENDMENT_STATUSES, label)
    assert_enum(data, "shpo_decision", constants.CONCURRENCE_DECISIONS, label)
    assert_enum(data, "nps_decision", constants.CONCURRENCE_DECISIONS, label)
    assert_nullable_timestamp(data, "submitted_at", label)


def assert_is_investor_interest(data):
    label = "investor_interest"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "kind",
            "party_legal_name",
            "party_tax_status",
            "capital_committed_cents",
            "credit_allocation_pct",
            "lease_term_years",
            "pass_through_election",
            "election_at",
            "status",
            "disqualification_risk_score",
            "risk_variant_applied",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "investor_interest.project_id")
    assert_enum(data, "kind", constants.INTEREST_KINDS, label)
    assert_is_string(data, "party_legal_name", label)
    assert_enum(data, "party_tax_status", constants.PARTY_TAX_STATUSES, label)
    assert_is_int(data, "capital_committed_cents", label, minimum=1)
    assert_is_number(data, "credit_allocation_pct", label)
    if data["lease_term_years"] is not None:
        assert_is_int(data, "lease_term_years", label, minimum=1)
    assert_enum(data, "pass_through_election", constants.PASS_THROUGH_ELECTIONS, label)
    assert_nullable_timestamp(data, "election_at", label)
    assert_enum(data, "status", constants.INTEREST_STATUSES, label)
    assert_is_int(data, "disqualification_risk_score", label, minimum=0)
    assert_enum(data, "risk_variant_applied", constants.RISK_VARIANTS, label)


def assert_is_credit_claim(data):
    label = "credit_claim"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "tax_year",
            "claim_sequence",
            "gross_credit_cents",
            "recapture_offset_cents",
            "net_claim_cents",
            "status",
            "filed_at",
            "filed_by_user_id",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "credit_claim.project_id")
    assert_is_int(data, "tax_year", label)
    assert_is_int(data, "claim_sequence", label, minimum=1)
    assert_is_int(data, "gross_credit_cents", label, minimum=0)
    assert_is_int(data, "recapture_offset_cents", label, minimum=0)
    assert_is_int(data, "net_claim_cents", label, minimum=0)
    assert_enum(data, "status", constants.CLAIM_STATUSES, label)
    assert_nullable_timestamp(data, "filed_at", label)
    assert_is_string(data, "filed_by_user_id", label, allow_null=True)


def assert_is_recapture_event(data):
    label = "recapture_event"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "event_type",
            "event_date",
            "full_years_elapsed",
            "recapture_pct",
            "recapture_amount_cents",
            "status",
            "source",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "recapture_event.project_id")
    assert_enum(data, "event_type", constants.RECAPTURE_EVENT_TYPES, label)
    assert_is_date(data["event_date"], "recapture_event.event_date")
    assert_is_int(data, "full_years_elapsed", label, minimum=0)
    assert_is_number(data, "recapture_pct", label)
    assert_is_int(data, "recapture_amount_cents", label, minimum=0)
    assert_enum(data, "status", constants.RECAPTURE_EVENT_STATUSES, label)
    assert_enum(data, "source", constants.RECAPTURE_SOURCES, label)


def assert_is_compliance_covenant(data):
    label = "compliance_covenant"
    assert_common_properties(data, label)
    _assert_keys(
        data,
        (
            "project_id",
            "covenant_type",
            "monitoring_frequency",
            "window_start_date",
            "window_end_date",
            "status",
            "attestation_count",
            "exception_count",
            "last_attested_period_end",
            "cure_deadline_date",
        ),
        label,
    )
    assert_is_uuid(data["project_id"], "compliance_covenant.project_id")
    assert_enum(data, "covenant_type", constants.COVENANT_TYPES, label)
    assert_enum(data, "monitoring_frequency", constants.MONITORING_FREQUENCIES, label)
    assert_is_date(data["window_start_date"], "covenant.window_start_date")
    assert_is_date(data["window_end_date"], "covenant.window_end_date")
    assert_enum(data, "status", constants.COVENANT_STATUSES, label)
    assert_is_int(data, "attestation_count", label, minimum=0)
    assert_is_int(data, "exception_count", label, minimum=0)
    assert_nullable_date(data, "last_attested_period_end", label)
    assert_nullable_date(data, "cure_deadline_date", label)


def assert_is_qre_summary(data):
    """The computed read of PRD §3.6; it persists nothing of its own."""
    label = "qre_summary"
    integer_fields = (
        "qre_total_cents",
        "hard_qre_cents",
        "developer_fee_claimed_cents",
        "developer_fee_allowed_cents",
        "developer_fee_disallowed_cents",
        "nonqualified_total_cents",
        "classified_cost_total_cents",
        "substantial_test_threshold_cents",
        "in_period_item_count",
        "pending_classification_item_count",
    )
    _assert_keys(
        data,
        ("variant_applied", "substantial_test_status_under_variant") + integer_fields,
        label,
    )
    assert_enum(data, "variant_applied", constants.QRE_VARIANTS, label)
    assert_enum(
        data,
        "substantial_test_status_under_variant",
        constants.SUBSTANTIAL_TEST_STATUSES,
        label,
    )
    for field in integer_fields:
        assert_is_int(data, field, label, minimum=0)
