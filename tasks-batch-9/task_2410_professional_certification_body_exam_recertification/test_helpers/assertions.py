"""Domain-specific assertion helpers.

Two families live here.

The ``assert_<entity>`` helpers check the shape that the PRD guarantees for
every representation of that entity: the four common fields plus the fields the
entity table declares non-nullable. They deliberately do NOT assert business
values — a test asserts those itself, inline, so the expectation is readable at
the call site.

The invariant helpers check relationships the PRD states must hold at every
observable moment (a derived counter agreeing with its inputs, a ledger never
going negative, a rounding discipline being honoured).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity in this system carries ``id``, ``created_at``, ``updated_at``
    and ``version``; no entity is exempt.
    """
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO 8601: {entity['created_at']!r}")
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']!r}")
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"version is not an integer: {entity['version']!r}")
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']!r}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}")


def assert_fields_present(entity: Dict[str, Any], field_names: Sequence[str]) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"missing fields: {missing}"


def assert_nullable_fields_null(entity: Dict[str, Any], field_names: Sequence[str]) -> None:
    non_null = {name: entity[name] for name in field_names if entity.get(name) is not None}
    assert not non_null, f"expected these fields to be null: {non_null}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_certification_program(program: Dict[str, Any],
                                 expected_version: Optional[int] = None) -> None:
    assert_common_fields(program, expected_version)
    assert_fields_present(program, [
        "name", "credential_code", "jta_version", "status", "domain_specs",
        "form_length", "accepted_education_credentials", "psychometric_stat_basis",
        "min_discrimination", "min_p_value", "max_p_value", "min_responses_for_stats",
        "form_retirement_tolerance_pct", "min_panelists", "panel_trim_count",
        "cut_score_sem_multiplier", "education_recency_years", "min_experience_months",
        "audit_every_nth", "eligibility_valid_days", "exam_fee_cents",
        "max_attempts_per_cycle", "retake_wait_days", "cycle_length_months",
        "required_ceu_credits", "ceu_credit_accrual_basis", "ceu_carryover_max_credits",
        "recert_grace_days", "operational_item_count", "deficient_domain_codes",
        "blueprint_posture", "verified_application_counter", "certificants_issued_count",
    ])
    assert program["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert program["blueprint_posture"] in ("DEFICIENT", "COMPLETE")
    assert isinstance(program["domain_specs"], list)
    assert isinstance(program["deficient_domain_codes"], list)


def assert_item(item: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(item, expected_version)
    assert_fields_present(item, [
        "program_id", "domain_code", "cognitive_level", "stem", "status",
        "author_user_id", "approver_user_ids", "review_round",
        "pretest_response_count", "pretest_correct_count", "pretest_upper_n",
        "pretest_upper_correct", "pretest_lower_n", "pretest_lower_correct",
        "operational_response_count", "operational_correct_count", "operational_upper_n",
        "operational_upper_correct", "operational_lower_n", "operational_lower_correct",
        "p_value", "discrimination_index", "flag_reason", "stat_basis_applied",
        "retirement_reason", "retired_at",
    ])
    assert item["status"] in ("DRAFT", "IN_REVIEW", "REVISION_REQUESTED", "APPROVED",
                             "REJECTED", "PRETEST", "OPERATIONAL", "FLAGGED", "RETIRED")
    assert isinstance(item["approver_user_ids"], list)
    assert isinstance(item["review_round"], int)
    assert item["stat_basis_applied"] in ("INSUFFICIENT_DATA", "OPERATIONAL_ONLY", "POOLED")


def assert_exam_form(form: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(form, expected_version)
    assert_fields_present(form, [
        "program_id", "form_code", "status", "item_ids", "pretest_item_ids",
        "scored_item_count", "retired_item_count", "panel_method", "panelist_user_ids",
        "panel_ratings", "panel_status", "mean_expected_pass_rate", "raw_cut_score",
    ])
    assert form["status"] in ("ASSEMBLED", "CUT_SCORE_SET", "PUBLISHED", "NEEDS_REBUILD")
    assert form["panel_status"] in ("OPEN", "RATINGS_COMPLETE", "ADOPTED")
    assert isinstance(form["item_ids"], list)
    assert isinstance(form["pretest_item_ids"], list)
    assert isinstance(form["panel_ratings"], list)
    assert isinstance(form["panelist_user_ids"], list)


def assert_candidate(candidate: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(candidate, expected_version)
    assert_fields_present(candidate, ["email", "full_name", "status", "bar_reason",
                                      "barred_until"])
    assert candidate["status"] in ("ACTIVE", "BARRED")


def assert_eligibility_application(application: Dict[str, Any],
                                   expected_version: Optional[int] = None) -> None:
    assert_common_fields(application, expected_version)
    assert_fields_present(application, [
        "candidate_id", "program_id", "status", "education_credential",
        "education_completion_year", "experience_months", "attestation_signed",
        "education_status", "experience_status", "denial_reason", "verifier_user_ids",
        "attempts_consumed", "eligibility_expires_on", "audit_sequence_number",
        "auditor_user_id",
    ])
    assert application["status"] in ("SUBMITTED", "UNDER_REVIEW", "AUDIT_SELECTED",
                                     "APPROVED", "DENIED", "EXPIRED")
    assert isinstance(application["verifier_user_ids"], list)


def assert_exam_session(session: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(session, expected_version)
    assert_fields_present(session, [
        "modality", "starts_at", "ends_at", "seat_capacity", "center_code", "room_code",
        "proctor_pool_code", "seats_reserved", "status",
    ])
    assert session["modality"] in ("TEST_CENTER", "ONLINE_PROCTORED")
    assert session["status"] in ("OPEN", "FULL", "CLOSED")
    assert_seat_ledger_within_bounds(session)


def assert_exam_registration(registration: Dict[str, Any],
                             expected_version: Optional[int] = None) -> None:
    assert_common_fields(registration, expected_version)
    assert_fields_present(registration, [
        "application_id", "form_id", "session_id", "attempt_number", "fee_paid_cents",
        "seat_status", "score_status", "raw_score", "scaled_score", "outcome",
        "score_status_before_hold", "session_ends_at", "form_reassignment_required",
        "eligibility_expires_on_snapshot",
    ])
    assert registration["seat_status"] in ("UNSCHEDULED", "SCHEDULED", "CHECKED_IN",
                                           "COMPLETED", "NO_SHOW", "CANCELLED")
    assert registration["score_status"] in ("NOT_APPLICABLE", "PENDING", "SCORED",
                                            "WITHHELD", "VOIDED", "REPORTED")
    assert isinstance(registration["attempt_number"], int)
    assert registration["attempt_number"] >= 1


def assert_security_incident(incident: Dict[str, Any],
                             expected_version: Optional[int] = None) -> None:
    assert_common_fields(incident, expected_version)
    assert_fields_present(incident, [
        "registration_id", "incident_type", "severity", "description", "status",
        "outcome_note", "placed_hold",
    ])
    assert incident["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert incident["status"] in ("OPEN", "SUBSTANTIATED", "UNSUBSTANTIATED")
    assert isinstance(incident["placed_hold"], bool)


def assert_certificant(certificant: Dict[str, Any],
                       expected_version: Optional[int] = None) -> None:
    assert_common_fields(certificant, expected_version)
    assert_fields_present(certificant, [
        "candidate_id", "program_id", "certificate_number", "status", "issued_on",
        "valid_through", "current_cycle_id", "suspension_until", "publication_status",
        "ceu_credits_applied",
    ])
    assert certificant["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
    assert certificant["publication_status"] in ("PUBLISHED", "WITHHELD", "REMOVED")


def assert_recertification_cycle(cycle: Dict[str, Any],
                                 expected_version: Optional[int] = None) -> None:
    assert_common_fields(cycle, expected_version)
    assert_fields_present(cycle, [
        "certificant_id", "cycle_number", "starts_on", "ends_on", "grace_ends_on",
        "required_credits", "credits_applied", "carryover_credits_in",
        "carryover_credits_out", "status", "path", "reinstatement_fee_cents",
        "accrual_basis_snapshot", "reexam_registration_id",
    ])
    assert cycle["status"] in ("OPEN", "SATISFIED", "CLOSED", "LAPSED", "VOID")
    assert cycle["path"] in ("CEU", "RE_EXAM")
    assert isinstance(cycle["cycle_number"], int)


def assert_ceu_activity(activity: Dict[str, Any],
                        expected_version: Optional[int] = None) -> None:
    assert_common_fields(activity, expected_version)
    assert_fields_present(activity, [
        "cycle_id", "activity_date", "category", "provider", "contact_hours",
        "credits_awarded", "status", "reviewer_user_id", "audit_verifier_user_id",
        "counted", "credits_counted", "review_note",
    ])
    assert activity["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "AUDIT_SELECTED",
                                  "VERIFIED", "REVOKED")
    assert isinstance(activity["counted"], bool)


def assert_disciplinary_case(case: Dict[str, Any],
                             expected_version: Optional[int] = None) -> None:
    assert_common_fields(case, expected_version)
    assert_fields_present(case, [
        "certificant_id", "allegation_type", "description", "status",
        "opened_by_user_id", "response_round", "response_text", "outcome",
        "sanction_months", "decided_on",
    ])
    assert case["status"] in ("OPENED", "RESPONSE_REQUESTED", "UNDER_REVIEW", "CLOSED")
    assert isinstance(case["response_round"], int)


def assert_registry_verification(verification: Dict[str, Any]) -> None:
    """The public projection: exactly the nine published fields, no internals."""
    assert_fields_present(verification, [
        "certificate_number", "credential_code", "full_name", "credential_status",
        "issued_on", "valid_through", "publication_status", "verified_at",
    ])
    assert is_iso8601_timestamp(verification["verified_at"])


def assert_maintenance_run_report(report: Dict[str, Any]) -> None:
    """The run answers with a report object listing every identifier it touched."""
    assert_fields_present(report, [
        "run_at", "no_show_registration_ids", "expired_application_ids",
        "lapsed_cycle_ids", "expired_certificant_ids", "reactivated_certificant_ids",
        "unbarred_candidate_ids",
    ])
    for key in ("no_show_registration_ids", "expired_application_ids", "lapsed_cycle_ids",
                "expired_certificant_ids", "reactivated_certificant_ids",
                "unbarred_candidate_ids"):
        assert isinstance(report[key], list), f"{key} must be a list, got {report[key]!r}"


# ---------------------------------------------------------------------------
# Invariants the PRD guarantees at every observable moment
# ---------------------------------------------------------------------------


def assert_seat_ledger_within_bounds(session: Dict[str, Any]) -> None:
    """``seats_reserved`` is a count of live seats: never negative, never above
    the session's capacity.
    """
    reserved = session["seats_reserved"]
    capacity = session["seat_capacity"]
    assert isinstance(reserved, int), f"seats_reserved must be an integer: {reserved!r}"
    assert reserved >= 0, f"seats_reserved went negative: {reserved}"
    assert reserved <= capacity, (
        f"seats_reserved {reserved} exceeds seat_capacity {capacity}")


def assert_blueprint_posture_agrees_with_counts(program: Dict[str, Any]) -> None:
    """``blueprint_posture`` is ``COMPLETE`` exactly when no domain is deficient."""
    expected = "DEFICIENT" if program["deficient_domain_codes"] else "COMPLETE"
    assert program["blueprint_posture"] == expected, (
        f"blueprint_posture {program['blueprint_posture']!r} disagrees with "
        f"deficient_domain_codes {program['deficient_domain_codes']!r}")


def assert_publication_status_agrees_with_status(certificant: Dict[str, Any]) -> None:
    """``publication_status`` is derived: ``REMOVED`` once revoked, ``WITHHELD``
    while suspended or expired, ``PUBLISHED`` while active.
    """
    status = certificant["status"]
    expected = {
        "REVOKED": "REMOVED",
        "SUSPENDED": "WITHHELD",
        "EXPIRED": "WITHHELD",
        "ACTIVE": "PUBLISHED",
    }[status]
    assert certificant["publication_status"] == expected, (
        f"certificant status {status!r} implies publication_status {expected!r}, "
        f"got {certificant['publication_status']!r}")


def assert_credits_applied_matches_counted_children(cycle: Dict[str, Any],
                                                    activities: List[Dict[str, Any]]) -> None:
    """``credits_applied`` is re-derived from scratch as the carry-in plus the
    credits of the activities that are currently counting.
    """
    total = Decimal(str(cycle["carryover_credits_in"]))
    for activity in activities:
        if activity["counted"]:
            total += Decimal(str(activity["credits_counted"]))
    expected = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    actual = float(cycle["credits_applied"])
    assert abs(actual - expected) < 0.005, (
        f"credits_applied {actual} does not match the counted children plus "
        f"carry-in ({expected})")


def assert_uncounted_activity_is_inert(activity: Dict[str, Any]) -> None:
    """An activity that is not counting contributes zero, while the credits it
    earned on its own merits remain on the record.
    """
    assert activity["counted"] is False
    assert float(activity["credits_counted"]) == 0.0, (
        f"an uncounted activity must contribute 0.00, got {activity['credits_counted']!r}")


def assert_decimal_places(value: Any, decimal_places: int) -> None:
    """The value carries at most ``decimal_places`` digits after the point."""
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    assert places <= decimal_places, (
        f"{value!r} carries {places} decimal places, at most {decimal_places} allowed")


def assert_item_stat_precision(value: Any) -> None:
    """Item statistics are stored to four decimal places."""
    assert_decimal_places(value, 4)


def assert_standard_setting_precision(value: Any) -> None:
    """Standard-setting intermediates are stored to six decimal places."""
    assert_decimal_places(value, 6)


def assert_credit_precision(value: Any) -> None:
    """Continuing-education credit amounts are stored to two decimal places."""
    assert_decimal_places(value, 2)


def assert_integer_cents(value: Any) -> None:
    """Money is stored as an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be integer cents, got {value!r}")


def round_half_up(value: float, decimal_places: int) -> float:
    """The PRD's single rounding rule: round half away from zero, upward."""
    quantum = Decimal(1).scaleb(-decimal_places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
