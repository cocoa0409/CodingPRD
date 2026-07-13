"""Validation precedence and cross-entity state preconditions on certificate issuance
and inspection scheduling, plus two numeric/temporal boundaries.

Difficulty queue A: priority_pair_validation_conflict, cross_entity_state_dependency,
boundary_precision_check.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_registered_vessel, setup_certified_vessel,
    set_clock, new_jurisdiction, new_owner, new_inspector, commission, new_vessel,
    new_inspection, raise_deficiency, record_result,
    new_fee_invoice, pay_invoice, vessel_version, file_incident,
    assert_same_instant,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / cert_issue_state_beats_fiscal_returns_invalid_state
# ---------------------------------------------------------------------------
def _state_beats_fiscal_ctx():
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])  # left SCHEDULED
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])       # UNPAID
    ver = vessel_version(ctx["vessel_id"])
    ctx.update({"insp1_id": insp1["id"], "fee1_id": fee1["id"], "ver": ver})
    return ctx


def test_certificate_state_check_beats_fiscal(api):
    """PRD §2.7: "When a single request could fail multiple checks, the checks are
    evaluated in a fixed priority order and the first failure determines the returned
    error."
    PRD §3.7: "the referenced inspection must be in `PASSED` or
    `PASSED_WITH_DEFICIENCIES`, else `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/cert_issue_state_beats_fiscal_returns_invalid_state
    """
    ctx = _state_beats_fiscal_ctx()
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": ctx["insp1_id"],
         "fee_invoice_id": ctx["fee1_id"], "expected_vessel_version": ctx["ver"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_certificate_state_error_not_masked_by_fiscal(api):
    """PRD §2.7: "When a single request could fail multiple checks, the checks are
    evaluated in a fixed priority order and the first failure determines the returned
    error."
    PRD §3.7: "the referenced inspection must be in `PASSED` or
    `PASSED_WITH_DEFICIENCIES`, else `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/cert_issue_state_beats_fiscal_returns_invalid_state
    """
    ctx = _state_beats_fiscal_ctx()
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": ctx["insp1_id"],
         "fee_invoice_id": ctx["fee1_id"], "expected_vessel_version": ctx["ver"]},
        ADMIN,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_FEE_NOT_PAID.value


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / inspection_safety_beats_referential_returns_vessel_not_inspectable
# ---------------------------------------------------------------------------
def _safety_beats_referential_ctx():
    ctx = setup_certified_vessel()
    insp_b = new_inspector(ctx["jur_id"], name="Insp B", commission_number="NBC-B")  # PENDING
    file_incident(ctx["vessel_id"], ctx["owner_id"], severity="CRITICAL",
                  occurred_at="2026-05-30T00:00:00Z", narrative="pressure spike")  # -> SUSPENDED
    ctx["insp_b_id"] = insp_b["id"]
    return ctx


def test_inspection_safety_check_beats_referential(api):
    """PRD §3.4: "A schedule attempt that violates this rule is rejected with
    `ERR_VESSEL_NOT_INSPECTABLE`."
    PRD §2.7: "When a single request could fail multiple checks, the checks are evaluated
    in a fixed priority order and the first failure determines the returned error."

    Design: Difficulty/priority_pair_validation_conflict/inspection_safety_beats_referential_returns_vessel_not_inspectable
    """
    ctx = _safety_beats_referential_ctx()
    resp = api.create_inspection(
        {"vessel_id": ctx["vessel_id"], "inspector_id": ctx["insp_b_id"],
         "inspection_type": "EXTERNAL", "scheduled_start": "2026-06-05T09:00:00Z",
         "scheduled_end": "2026-06-05T11:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_INSPECTABLE.value)


def test_inspection_safety_error_not_masked_by_referential(api):
    """PRD §2.7: "When a single request could fail multiple checks, the checks are
    evaluated in a fixed priority order and the first failure determines the returned
    error."
    PRD §3.4: "A schedule attempt that violates this rule is rejected with
    `ERR_VESSEL_NOT_INSPECTABLE`."

    Design: Difficulty/priority_pair_validation_conflict/inspection_safety_beats_referential_returns_vessel_not_inspectable
    """
    ctx = _safety_beats_referential_ctx()
    resp = api.create_inspection(
        {"vessel_id": ctx["vessel_id"], "inspector_id": ctx["insp_b_id"],
         "inspection_type": "EXTERNAL", "scheduled_start": "2026-06-05T09:00:00Z",
         "scheduled_end": "2026-06-05T11:00:00Z"},
        ADMIN,
    )
    err = validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_INSPECTABLE.value)
    assert err["error_id"] != ApiErrorId.ERR_INSPECTOR_NOT_COMMISSIONED.value


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / inspection_requires_vessel_registered
# ---------------------------------------------------------------------------
def _draft_vessel_ctx():
    set_clock("2026-06-01T00:00:00Z")
    jur = new_jurisdiction()
    owner = new_owner()
    insp_a = new_inspector(jur["id"])
    commission(insp_a["id"])
    vessel = new_vessel(owner["id"], jur["id"])  # never registered -> DRAFT
    return {"jur_id": jur["id"], "owner_id": owner["id"], "insp_a_id": insp_a["id"], "vessel_id": vessel["id"]}


def test_inspection_on_draft_vessel_rejected(api):
    """PRD §3.4: "A vessel is safe to inspect only when its `registration_status` is
    `REGISTERED` and its `service_status` is one of `IN_SERVICE`, `RESTRICTED`, or
    `NOT_IN_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_requires_vessel_registered_pair_inspection_vessel
    """
    ctx = _draft_vessel_ctx()
    resp = api.create_inspection(
        {"vessel_id": ctx["vessel_id"], "inspector_id": ctx["insp_a_id"],
         "inspection_type": "EXTERNAL", "scheduled_start": "2026-06-02T09:00:00Z",
         "scheduled_end": "2026-06-02T11:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_INSPECTABLE.value)


def test_draft_vessel_starts_unregistered(api):
    """PRD §3.2: "A newly created vessel starts with `registration_status` `DRAFT`".

    Design: Difficulty/cross_entity_state_dependency/inspection_requires_vessel_registered_pair_inspection_vessel
    """
    ctx = _draft_vessel_ctx()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["registration_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / certificate_requires_inspection_passed
# ---------------------------------------------------------------------------
def _cert_needs_passed_ctx():
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])  # SCHEDULED
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    pay_invoice(fee1["id"], ctx["owner_id"])
    ver = vessel_version(ctx["vessel_id"])
    ctx.update({"insp1_id": insp1["id"], "fee1_id": fee1["id"], "ver": ver})
    return ctx


def test_certificate_on_scheduled_inspection_rejected(api):
    """PRD §3.7: "the referenced inspection must be in `PASSED` or
    `PASSED_WITH_DEFICIENCIES`, else `ERR_INVALID_STATE`".

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_inspection_passed_pair_certificate_inspection
    """
    ctx = _cert_needs_passed_ctx()
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": ctx["insp1_id"],
         "fee_invoice_id": ctx["fee1_id"], "expected_vessel_version": ctx["ver"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_inspection_remains_scheduled_when_cert_rejected(api):
    """PRD §3.4: "A new inspection begins in `status` `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_inspection_passed_pair_certificate_inspection
    """
    ctx = _cert_needs_passed_ctx()
    api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": ctx["insp1_id"],
         "fee_invoice_id": ctx["fee1_id"], "expected_vessel_version": ctx["ver"]},
        ADMIN,
    )
    data = validate_success(api.get_inspection(ctx["insp1_id"], ADMIN))
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# boundary_precision_check / certificate_expire_at_exact_valid_until_ge_boundary
# ---------------------------------------------------------------------------
def test_certificate_expires_at_exact_valid_until(api):
    """PRD §3.7: "A `JurisdictionAdmin` may expire an `ACTIVE` certificate, advancing it
    `ACTIVE → EXPIRED`, but only when the clock now has reached `valid_until` (at or
    after that instant)".

    Design: Difficulty/boundary_precision_check/certificate_expire_at_exact_valid_until_ge_boundary
    """
    ctx = setup_certified_vessel()  # POWER_BOILER, valid_from 2026-06-01 -> valid_until 2027-06-01
    set_clock("2027-06-01T00:00:00Z")
    data = get_success_data(api.expire_certificate(ctx["cert1_id"], ADMIN))
    assert data["status"] == "EXPIRED"


def test_certificate_valid_until_is_one_year_out(api):
    """PRD §3.7: "otherwise it is the class default — 12 months for a `POWER_BOILER`,
    12 months for a `HEATING_BOILER`, and 24 months for a `PRESSURE_VESSEL`. Then
    `valid_until` is `valid_from` advanced by that many calendar months, keeping the same
    day-of-month."

    Design: Difficulty/boundary_precision_check/certificate_expire_at_exact_valid_until_ge_boundary
    """
    ctx = setup_certified_vessel()
    cert = validate_success(api.get_certificate(ctx["cert1_id"], ADMIN))
    assert_same_instant(cert["valid_until"], "2027-06-01T00:00:00Z")


# ---------------------------------------------------------------------------
# boundary_precision_check / certificate_issue_blocked_by_one_open_critical_deficiency
# ---------------------------------------------------------------------------
def _one_open_critical_ctx():
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    pay_invoice(fee1["id"], ctx["owner_id"])
    insp2 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL",
                           scheduled_start="2026-06-03T09:00:00Z", scheduled_end="2026-06-03T11:00:00Z")
    raise_deficiency(insp2["id"], ctx["insp_a_id"], severity="CRITICAL", description="corroded shell course")
    ver = vessel_version(ctx["vessel_id"])
    ctx.update({"insp1_id": insp1["id"], "fee1_id": fee1["id"], "ver": ver})
    return ctx


def test_vessel_has_one_open_critical_deficiency(api):
    """PRD §3.5: "Raising it increments the vessel's `open_deficiency_count` (and, when
    the severity is `CRITICAL`, its `open_critical_deficiency_count`)".

    Design: Difficulty/boundary_precision_check/certificate_issue_blocked_by_one_open_critical_deficiency_zero_set
    """
    ctx = _one_open_critical_ctx()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["open_critical_deficiency_count"] == 1


def test_certificate_blocked_by_open_critical_deficiency(api):
    """PRD §3.7: "the vessel must have no non-terminal `CRITICAL` deficiency
    (`open_critical_deficiency_count` must be zero), else `ERR_CRITICAL_DEFICIENCY_OPEN`".

    Design: Difficulty/boundary_precision_check/certificate_issue_blocked_by_one_open_critical_deficiency_zero_set
    """
    ctx = _one_open_critical_ctx()
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": ctx["insp1_id"],
         "fee_invoice_id": ctx["fee1_id"], "expected_vessel_version": ctx["ver"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CRITICAL_DEFICIENCY_OPEN.value)
