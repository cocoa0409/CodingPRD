"""Request-payload factories.

Every factory returns a complete, valid payload that a test can override field by
field. Monetary amounts are always Python integers of cents — never strings and
never floats — because the service stores integer cents everywhere.
"""

import itertools

_spec_labels = itertools.count(1)
_feature_codes = itertools.count(1)
_member_names = itertools.count(1)
_lab_names = itertools.count(1)
_device_models = itertools.count(1)
_fingerprints = itertools.count(1)
_dac_serials = itertools.count(1)
_firmware_versions = itertools.count(1)


def unique_version_label(prefix="SHIC-"):
    return "{}{}.0".format(prefix, next(_spec_labels))


def unique_feature_code(prefix="FEAT_"):
    return "{}{:04d}".format(prefix, next(_feature_codes))


def unique_legal_name(prefix="Acme Devices "):
    return "{}{}".format(prefix, next(_member_names))


def unique_lab_name(prefix="Northbridge Lab "):
    return "{}{}".format(prefix, next(_lab_names))


def unique_device_model(prefix="AL-"):
    return "{}{}".format(prefix, 100 + next(_device_models))


def unique_fingerprint():
    return "AA:BB:CC:{:02X}".format(next(_fingerprints) % 256)


def unique_dac_serial():
    return "DAC-{:07d}".format(next(_dac_serials))


def unique_firmware_version():
    return "1.{}.0".format(next(_firmware_versions))


# ---------------------------------------------------------------------------
# Specifications and feature sets
# ---------------------------------------------------------------------------


def specification_payload(**overrides):
    payload = {
        "version_label": unique_version_label(),
        "security_baseline_level": "SB1",
        "effective_date": "2026-09-01T00:00:00Z",
        "min_plugfest_credits": 0,
    }
    payload.update(overrides)
    return payload


def feature_set_payload(specification_id, **overrides):
    payload = {
        "specification_id": specification_id,
        "device_type": "LIGHTING",
        "feature_code": unique_feature_code(),
        "obligation": "MANDATORY",
        "test_case_count": 10,
        "security_relevant": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def member_payload(**overrides):
    payload = {
        "legal_name": unique_legal_name(),
        "contact_email": "ops@acme.test",
        "tier": "ADOPTER",
    }
    payload.update(overrides)
    return payload


def ip_commitment_payload(scope_specification_id, **overrides):
    payload = {
        "ip_commitment_type": "RAND_ROYALTY_FREE",
        "essential_patent_count": 2,
        "scope_specification_id": scope_specification_id,
    }
    payload.update(overrides)
    return payload


def tool_access_payload(decision="GRANT", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def credit_purchase_payload(amount_cents=1000000, **overrides):
    payload = {"amount_cents": int(amount_cents)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Laboratories
# ---------------------------------------------------------------------------


def laboratory_payload(**overrides):
    payload = {
        "name": unique_lab_name(),
        "bench_capacity": 2,
        "authorized_device_types": ["LIGHTING"],
        "accreditation_expires_at": "2027-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def accreditation_payload(decision="AUTHORIZE", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def competency_review_payload(variant="ROLLING_90D", **overrides):
    payload = {"variant": variant}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def submission_payload(member_id, specification_id, declared_feature_codes=None, **overrides):
    payload = {
        "member_id": member_id,
        "specification_id": specification_id,
        "device_model": unique_device_model(),
        "device_type": "LIGHTING",
        "declared_feature_codes": list(declared_feature_codes or []),
        "declared_secure_boot": True,
        "declared_firmware_update_capability": "OTA_SIGNED",
        "attestation_key_fingerprint": unique_fingerprint(),
        "review_track": "STANDARD",
    }
    payload.update(overrides)
    return payload


def return_for_info_payload(reason="More evidence required", **overrides):
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def conformance_decision_payload(decision="APPROVE", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def security_decision_payload(decision="APPROVE", **overrides):
    payload = {
        "decision": decision,
        "secure_boot_verified": True,
        "verified_firmware_update_capability": "OTA_SIGNED",
    }
    payload.update(overrides)
    return payload


def issue_credential_payload(dac_serial=None, **overrides):
    payload = {"dac_serial": dac_serial or unique_dac_serial()}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plans and sessions
# ---------------------------------------------------------------------------


def test_plan_payload(submission_id, expected_submission_version, **overrides):
    payload = {
        "submission_id": submission_id,
        "expected_submission_version": expected_submission_version,
    }
    payload.update(overrides)
    return payload


def test_session_payload(
    test_plan_id,
    laboratory_id,
    window_start="2026-09-02T09:00:00Z",
    window_end="2026-09-02T13:00:00Z",
    bench_index=1,
    session_type="INTEROP",
    **overrides
):
    payload = {
        "test_plan_id": test_plan_id,
        "laboratory_id": laboratory_id,
        "bench_index": bench_index,
        "window_start": window_start,
        "window_end": window_end,
        "session_type": session_type,
    }
    payload.update(overrides)
    return payload


# Both payload builders above are named after the resources they build, which
# means pytest would otherwise mistake them for test functions wherever they are
# imported into a module.
test_plan_payload.__test__ = False
test_session_payload.__test__ = False


def results_payload(result_lines, **overrides):
    payload = {"result_lines": list(result_lines)}
    payload.update(overrides)
    return payload


def dispute_line_payload(line_index=0, **overrides):
    payload = {"line_index": line_index}
    payload.update(overrides)
    return payload


def cancel_session_payload(reason="Bench unavailable", **overrides):
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plugfests
# ---------------------------------------------------------------------------


def plugfest_payload(
    host_laboratory_id,
    specification_id,
    window_start="2026-10-05T09:00:00Z",
    window_end="2026-10-06T18:00:00Z",
    registration_deadline="2026-10-01T00:00:00Z",
    min_distinct_vendors=2,
    **overrides
):
    payload = {
        "host_laboratory_id": host_laboratory_id,
        "specification_id": specification_id,
        "window_start": window_start,
        "window_end": window_end,
        "registration_deadline": registration_deadline,
        "min_distinct_vendors": min_distinct_vendors,
    }
    payload.update(overrides)
    return payload


def participation_payload(plugfest_id, member_id, submission_id, **overrides):
    payload = {
        "plugfest_id": plugfest_id,
        "member_id": member_id,
        "submission_id": submission_id,
        "device_model": unique_device_model(),
    }
    payload.update(overrides)
    return payload


def record_outcome_payload(outcome="PASS", interop_pass_count=4, **overrides):
    payload = {"outcome": outcome, "interop_pass_count": interop_pass_count}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Listings and cases
# ---------------------------------------------------------------------------


def listing_payload(submission_id, **overrides):
    payload = {"submission_id": submission_id}
    payload.update(overrides)
    return payload


def listing_withdraw_payload(reason="Consumer safety report", **overrides):
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def firmware_revision_payload(
    expected_listing_version,
    firmware_version=None,
    changed_feature_codes=None,
    security_change=False,
    **overrides
):
    payload = {
        "expected_listing_version": expected_listing_version,
        "firmware_version": firmware_version or unique_firmware_version(),
        "changed_feature_codes": list(changed_feature_codes or []),
        "security_change": security_change,
    }
    payload.update(overrides)
    return payload


def noncompliance_case_payload(
    listing_id,
    category="INTEROP_DEFECT",
    claimed_impact_units=100,
    evidence_summary="Field reports of failed pairings",
    **overrides
):
    payload = {
        "listing_id": listing_id,
        "category": category,
        "evidence_summary": evidence_summary,
        "claimed_impact_units": int(claimed_impact_units),
    }
    payload.update(overrides)
    return payload


def case_advance_payload(disposition="ESCALATE", **overrides):
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload
