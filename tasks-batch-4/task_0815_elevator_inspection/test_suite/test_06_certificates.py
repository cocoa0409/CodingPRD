"""Operating-certificate issuance: expiry, supersession, the source-inspection
and empty-deficiency-set guards, optimistic concurrency, and the
referential-over-fiscal validation-priority conflict."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Corner: calculations / certificate_expiry_period_computed_escalator
# --------------------------------------------------------------------------
def test_certificate_expiry_period_computed_escalator(api):
    """PRD §3.7: "its expiry_period is the issue_period plus the device-category
    interval — 12 months for a PASSENGER_ELEVATOR or FREIGHT_ELEVATOR, 6 months for
    an ESCALATOR or MOVING_WALK, and 24 months for a DUMBWAITER."

    Design: Corner/calculations/certificate_expiry_period_computed_escalator
    """
    ctx = th.setup_device_with_passed_inspection(api, category="ESCALATOR")
    cert = th.issue_certificate(api, ctx["device"]["id"], ctx["inspection"]["id"])
    assert cert["issue_period"] == 0
    assert cert["expiry_period"] == 6, "0 + INTERVAL_MONTHS[ESCALATOR]=6"


# --------------------------------------------------------------------------
# Corner: state_machines / certificate_supersede_prior_marks_superseded
# --------------------------------------------------------------------------
def test_certificate_supersede_prior_marks_superseded(api):
    """PRD §3.7: "Issuance is a supersede-in-place: the device's prior active
    certificate, if any, transitions to the terminal SUPERSEDED state; the device's
    current_certificate_id is set to the new certificate".

    Design: Corner/state_machines/certificate_supersede_prior_marks_superseded
    """
    ctx = th.setup_posted_certificate(api, category="PASSENGER_ELEVATOR")
    cert1 = ctx["certificate"]
    ins2 = th.passed_inspection(api, ctx["device"]["id"], ctx["inspector"]["id"], itype="ANNUAL", start=5, end=6)
    cert2 = th.issue_certificate(api, ctx["device"]["id"], ins2["id"])
    reloaded1 = th.validate_success(api.get_certificate(cert1["id"], th.REG))
    assert reloaded1["status"] == "SUPERSEDED"
    assert cert2["status"] == "ISSUED"
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["current_certificate_id"] == cert2["id"]


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / certificate_requires_source_inspection_passed
# --------------------------------------------------------------------------
def test_certificate_rejected_when_source_inspection_in_progress(api):
    """PRD §3.7: "The source inspection must be in `PASSED` status, or the request
    is rejected with `ERR_SOURCE_INSPECTION_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_source_inspection_passed
    """
    ctx = th.setup_device_fee_paid(api, category="PASSENGER_ELEVATOR")
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    ins = th.inspection_in_progress(api, ctx["device"]["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    version = th.device_version(api, ctx["device"]["id"])
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ins["id"], version), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_SOURCE_INSPECTION_NOT_PASSED.value)


def test_certificate_issues_from_passed_source_inspection(api):
    """PRD §3.7: "When those guards pass, a new `Certificate` is created in `ISSUED`
    status with a system-minted `certificate_number`." A source inspection already
    in PASSED status satisfies the source-state guard.

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_source_inspection_passed
    """
    ctx = th.setup_device_with_passed_inspection(api, category="PASSENGER_ELEVATOR")
    version = th.device_version(api, ctx["device"]["id"])
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ctx["inspection"]["id"], version), th.REG)
    cert = th.validate_success(resp, expected_status=201)
    assert cert["status"] == "ISSUED"


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / certificate_zero_open_deficiencies_empty_set
# --------------------------------------------------------------------------
def test_certificate_rejected_with_one_open_deficiency(api):
    """PRD §3.7: "The device must have zero deficiencies in `OPEN` status — an
    empty-set requirement — or issuance is rejected with `ERR_OPEN_DEFICIENCIES_EXIST`."

    Design: Difficulty/boundary_precision_check/certificate_zero_open_deficiencies_empty_set
    """
    ctx = th.setup_device_fee_paid(api, category="PASSENGER_ELEVATOR")
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                   severity="MINOR", code="OPN-1", start=1, end=2)
    ins_pass = th.passed_inspection(api, ctx["device"]["id"], inspector["id"], itype="ANNUAL", start=5, end=6)
    version = th.device_version(api, ctx["device"]["id"])
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ins_pass["id"], version), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_OPEN_DEFICIENCIES_EXIST.value)


def test_certificate_issues_once_deficiency_set_is_empty(api):
    """PRD §3.7: "The device must have zero deficiencies in `OPEN` status — an
    empty-set requirement" — resolving the sole OPEN deficiency empties the set and
    permits issuance.

    Design: Difficulty/boundary_precision_check/certificate_zero_open_deficiencies_empty_set
    """
    ctx = th.setup_device_fee_paid(api, category="PASSENGER_ELEVATOR")
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    _, deficiency = th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                                   severity="MINOR", code="OPN-1", start=1, end=2)
    ins_pass = th.passed_inspection(api, ctx["device"]["id"], inspector["id"], itype="ANNUAL", start=5, end=6)
    th.validate_success(api.resolve_deficiency(deficiency["id"], th.make_licensed_inspector_headers(inspector["id"])))
    version = th.device_version(api, ctx["device"]["id"])
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ins_pass["id"], version), th.REG)
    cert = th.validate_success(resp, expected_status=201)
    assert cert["status"] == "ISSUED"


# --------------------------------------------------------------------------
# Corner: errors / certificate_outstanding_balance_blocks_issue
# --------------------------------------------------------------------------
def test_certificate_outstanding_balance_blocks_issue(api):
    """PRD §3.7: "And the device's outstanding_balance_cents must be exactly 0, or
    issuance is rejected with ERR_OUTSTANDING_BALANCE (HTTP 402)."

    Design: Corner/errors/certificate_outstanding_balance_blocks_issue
    """
    ctx = th.setup_device_with_passed_inspection(api, category="PASSENGER_ELEVATOR", fee_paid=False)
    version = th.device_version(api, ctx["device"]["id"])
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ctx["inspection"]["id"], version), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value)


# --------------------------------------------------------------------------
# Corner: cross_cutting / certificate_stale_device_version_returns_conflict
# --------------------------------------------------------------------------
def test_certificate_stale_device_version_returns_conflict(api):
    """PRD §2.5: "If expected_device_version does not equal the device's current
    version — for example because another writer has issued a certificate or
    otherwise advanced the device since the client last read it — the request is
    rejected with ERR_STALE_DEVICE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting/certificate_stale_device_version_returns_conflict
    """
    ctx = th.setup_device_with_passed_inspection(api, category="PASSENGER_ELEVATOR")
    version_pre = th.device_version(api, ctx["device"]["id"])
    th.validate_success(
        api.create_certificate(
            th.create_certificate_payload(ctx["device"]["id"], ctx["inspection"]["id"], version_pre), th.REG),
        expected_status=201)
    resp = api.create_certificate(
        th.create_certificate_payload(ctx["device"]["id"], ctx["inspection"]["id"], version_pre), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_STALE_DEVICE_VERSION.value)


# --------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / certificate_referential_over_fiscal
# --------------------------------------------------------------------------
def _setup_referential_over_fiscal(api):
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    dev_a = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="A-wing")
    dev_b = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="B-wing")
    ins_b = th.passed_inspection(api, dev_b["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    dev_a_v = th.device_version(api, dev_a["id"])
    return dev_a, ins_b, dev_a_v


def test_certificate_device_mismatch_precedes_outstanding_balance(api):
    """PRD §3.7: "The source inspection's device_id must equal the device_id on the
    request, or the request is rejected with ERR_INSPECTION_DEVICE_MISMATCH. And the
    device's outstanding_balance_cents must be exactly 0, or issuance is rejected
    with ERR_OUTSTANDING_BALANCE" — narrated (and per §2.9 evaluated) in that order.

    Design: Difficulty/priority_pair_validation_conflict/certificate_referential_over_fiscal
    """
    dev_a, ins_b, dev_a_v = _setup_referential_over_fiscal(api)
    resp = api.create_certificate(th.create_certificate_payload(dev_a["id"], ins_b["id"], dev_a_v), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_INSPECTION_DEVICE_MISMATCH.value)


def test_certificate_mismatch_does_not_surface_outstanding_error(api):
    """PRD §2.9: "Later checks never mask an earlier one: if a higher-priority
    condition fails, its error is returned before any lower-priority check runs" —
    the referential device-mismatch check pre-empts the lower-priority fiscal
    outstanding-balance check.

    Design: Difficulty/priority_pair_validation_conflict/certificate_referential_over_fiscal
    """
    dev_a, ins_b, dev_a_v = _setup_referential_over_fiscal(api)
    resp = api.create_certificate(th.create_certificate_payload(dev_a["id"], ins_b["id"], dev_a_v), th.REG)
    assert resp.status_code == 409
    error_id = resp.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_OUTSTANDING_BALANCE.value, \
        "referential mismatch must pre-empt the lower-priority outstanding-balance error"
