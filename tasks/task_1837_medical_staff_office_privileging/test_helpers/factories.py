"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import DEFAULT_SPECIALTY


def create_member_payload(full_name="Dr. Test", npdb_subject_id="NPDB-TEST",
                          primary_specialty_code="EMED", **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "npdb_subject_id": npdb_subject_id,
        "primary_specialty_code": primary_specialty_code,
    }
    payload.update(overrides)
    return payload


def create_specialty_criteria_payload(**overrides) -> dict:
    payload = {
        "specialty_code": DEFAULT_SPECIALTY["specialty_code"],
        "privilege_line": DEFAULT_SPECIALTY["privilege_line"],
        "min_training_months": DEFAULT_SPECIALTY["min_training_months"],
        "min_case_volume_24mo": DEFAULT_SPECIALTY["min_case_volume_24mo"],
        "required_board_cert": DEFAULT_SPECIALTY["required_board_cert"],
        "fppe_case_count": DEFAULT_SPECIALTY["fppe_case_count"],
        "volume_tier_table": [
            dict(row) for row in DEFAULT_SPECIALTY["volume_tier_table"]],
    }
    payload.update(overrides)
    return payload


def create_application_payload(member_id, expected_member_version,
                               application_kind="INITIAL",
                               supersedes_application_id=None,
                               **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "application_kind": application_kind,
        "expected_member_version": expected_member_version,
    }
    if supersedes_application_id is not None:
        payload["supersedes_application_id"] = supersedes_application_id
    payload.update(overrides)
    return payload


def create_verification_item_payload(application_id, item_kind="WORK_HISTORY",
                                     is_primary_source=False,
                                     **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "item_kind": item_kind,
        "is_primary_source": is_primary_source,
    }
    payload.update(overrides)
    return payload


def create_delineation_payload(application_id, expected_application_version,
                               privilege_line="EMED-GEN",
                               documented_training_months=24,
                               documented_cases_24mo=100,
                               **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "privilege_line": privilege_line,
        "documented_training_months": documented_training_months,
        "documented_cases_24mo": documented_cases_24mo,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def create_performance_review_payload(member_id, privilege_grant_id,
                                      review_kind="FPPE",
                                      period_start="2026-09-01T00:00:00Z",
                                      period_end="2026-10-01T00:00:00Z",
                                      **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "privilege_grant_id": privilege_grant_id,
        "review_kind": review_kind,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_performance_metric_payload(review_id, metric_domain="CLINICAL_QUALITY",
                                      raw_value=1.0, domain_weight=1.0,
                                      collected_at="2026-09-05T00:00:00Z",
                                      passed_fppe_case=None,
                                      **overrides) -> dict:
    payload = {
        "review_id": review_id,
        "metric_domain": metric_domain,
        "raw_value": raw_value,
        "domain_weight": domain_weight,
        "collected_at": collected_at,
    }
    if passed_fppe_case is not None:
        payload["passed_fppe_case"] = passed_fppe_case
    payload.update(overrides)
    return payload


def create_expirable_credential_payload(member_id, credential_kind="STATE_LICENSE",
                                        credential_number="CRED-1",
                                        issued_on="2026-01-01T00:00:00Z",
                                        expires_on="2027-08-01T00:00:00Z",
                                        supersedes_credential_id=None,
                                        **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "credential_kind": credential_kind,
        "credential_number": credential_number,
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    if supersedes_credential_id is not None:
        payload["supersedes_credential_id"] = supersedes_credential_id
    payload.update(overrides)
    return payload


def create_temporary_privilege_payload(member_id, sponsor_member_id,
                                       temp_kind="TEMPORARY",
                                       privilege_line="EMED-GEN",
                                       window_start="2026-09-01T00:00:00Z",
                                       window_end="2026-09-15T00:00:00Z",
                                       disaster_declaration_ref=None,
                                       **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "sponsor_member_id": sponsor_member_id,
        "temp_kind": temp_kind,
        "privilege_line": privilege_line,
        "window_start": window_start,
        "window_end": window_end,
    }
    if disaster_declaration_ref is not None:
        payload["disaster_declaration_ref"] = disaster_declaration_ref
    payload.update(overrides)
    return payload


def create_adverse_action_case_payload(subject_member_id, proposed_by_member_id,
                                       case_kind="SUSPENSION",
                                       restriction_days=None,
                                       linked_review_id=None,
                                       **overrides) -> dict:
    payload = {
        "subject_member_id": subject_member_id,
        "proposed_by_member_id": proposed_by_member_id,
        "case_kind": case_kind,
    }
    if restriction_days is not None:
        payload["restriction_days"] = restriction_days
    if linked_review_id is not None:
        payload["linked_review_id"] = linked_review_id
    payload.update(overrides)
    return payload


def create_hearing_panel_payload(case_id, panel_member_id, panel_role="MEMBER",
                                 **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "panel_member_id": panel_member_id,
        "panel_role": panel_role,
    }
    payload.update(overrides)
    return payload


def create_npdb_report_payload(member_id, report_kind="QUERY_INITIAL",
                               case_id=None, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "report_kind": report_kind,
    }
    if case_id is not None:
        payload["case_id"] = case_id
    payload.update(overrides)
    return payload


def create_agenda_item_payload(item_kind, ref_application_id=None,
                               ref_delineation_id=None, ref_case_id=None,
                               **overrides) -> dict:
    payload = {"item_kind": item_kind}
    if ref_application_id is not None:
        payload["ref_application_id"] = ref_application_id
    if ref_delineation_id is not None:
        payload["ref_delineation_id"] = ref_delineation_id
    if ref_case_id is not None:
        payload["ref_case_id"] = ref_case_id
    payload.update(overrides)
    return payload
