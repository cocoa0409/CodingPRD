"""Registration activation gates: fees, title, emissions, term overlap, validation precedence."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_owner,
    create_verified_vehicle,
    issue_clear_title,
    create_approved_title,
    create_registration,
    assess_fees,
    assess_and_pay_fees,
    setup_pending_registration_paid,
    setup_active_registration,
)

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# NOTE: Difficulty/priority_pair_validation_conflict/emissions_safety_beats_fees_fiscal is
# SKIPPED. The instance asserts ERR_EMISSIONS_REQUIRED wins when both the fee gate and the
# emissions gate fail. But PRD §3.5 narrates the activation gates in the order fees -> title ->
# emissions ("The registration's `FeeAssessment` must be in status `PAID`, or activation is
# rejected with `ERR_FEES_UNPAID` ... The vehicle must have a `TitleApplication` in status
# `ISSUED` ... If the vehicle's `vehicle_class` is not `MOTORCYCLE` and its `model_year` is 2010
# or later ... `ERR_EMISSIONS_REQUIRED`"), and PRD §2.9 binds precedence to "the operation's
# narrative in §3 states their relative order." A faithful PRD-only implementer would therefore
# return ERR_FEES_UNPAID (fees named first), not ERR_EMISSIONS_REQUIRED. The instance fails
# unique derivability, so no test is emitted (gap stays a gap).


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/vin_referential_beats_transfer_referential_on_submit
# ---------------------------------------------------------------------------
def test_resubmit_submitted_application_returns_invalid_state():
    """PRD §2.9: "then existence of referenced resources (`ERR_NOT_FOUND`), then — on transition
    endpoints — the basic state check (`ERR_INVALID_STATE`). Only after all of those pass are
    the domain-specific business gates of a given operation evaluated."
    PRD §3.2: "From `SUBMITTED`, a clerk may approve the application ... each requires the
    application to actually be in `SUBMITTED` (otherwise `ERR_INVALID_STATE`, HTTP 409)."

    Re-submitting an already-SUBMITTED application is an invalid transition; the structural
    state check (ERR_INVALID_STATE) pre-empts any business gate.

    Design: Difficulty/priority_pair_validation_conflict/vin_referential_beats_transfer_referential_on_submit
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"])
    from test_helpers import create_title_application_payload
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    resp = api_client.submit_title_application(ta["id"], CLERK)  # second submit
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_precedes_business_gate_on_resubmit():
    """PRD §2.9: "then — on transition endpoints — the basic state check (`ERR_INVALID_STATE`).
    Only after all of those pass are the domain-specific business gates of a given operation
    evaluated."

    HTTP-status assertion of the precedence: the second submit of a SUBMITTED application yields
    409 ERR_INVALID_STATE rather than any later business gate.

    Design: Difficulty/priority_pair_validation_conflict/vin_referential_beats_transfer_referential_on_submit
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"])
    from test_helpers import create_title_application_payload
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    resp = api_client.submit_title_application(ta["id"], CLERK)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/emissions_model_year_2010_boundary_required
# ---------------------------------------------------------------------------
def test_model_year_2010_requires_emissions():
    """PRD §3.5: "If the vehicle's `vehicle_class` is not `MOTORCYCLE` and its `model_year` is
    2010 or later, a passing emissions inspection whose half-open validity window contains the
    current clock must exist for the vehicle (per §3.4), or activation is rejected with
    `ERR_EMISSIONS_REQUIRED` (HTTP 409); a motorcycle, or a pre-2010 vehicle, is exempt from
    this check."

    model_year exactly 2010 (>= 2010) requires emissions; activation without one fails.

    Design: Difficulty/boundary_precision_check/emissions_model_year_2010_boundary_required
    """
    owner, veh, reg, fa = setup_pending_registration_paid(model_year=2010)
    resp = api_client.activate_registration(reg["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_EMISSIONS_REQUIRED.value)


def test_model_year_2009_exempt_from_emissions():
    """PRD §3.5: "a motorcycle, or a pre-2010 vehicle, is exempt from this check."

    model_year 2009 (< 2010) is exempt: with fees paid and title issued, activation succeeds
    without any emissions inspection (status -> ACTIVE).

    Design: Difficulty/boundary_precision_check/emissions_model_year_2010_boundary_required
    """
    owner, veh, reg, fa = setup_pending_registration_paid(model_year=2009)
    activated = validate_success(api_client.activate_registration(reg["id"], CLERK), 200)
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/registration_activate_requires_issued_title
# ---------------------------------------------------------------------------
def test_activation_requires_issued_title():
    """PRD §3.5: "The vehicle must have a `TitleApplication` in status `ISSUED` whose
    `applicant_owner_id` equals the registration's `owner_id`, or activation is rejected with
    `ERR_TITLE_NOT_ISSUED` (HTTP 409)."

    A pre-2010 (emissions-exempt) vehicle with fees PAID but the title only APPROVED (never
    ISSUED) fails activation.

    Design: Difficulty/cross_entity_state_dependency/registration_activate_requires_issued_title
    """
    owner, veh, reg, fa = setup_pending_registration_paid(model_year=2008, issue_title=False)
    resp = api_client.activate_registration(reg["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_ISSUED.value)


def test_activation_succeeds_once_title_issued():
    """PRD §3.5: "The vehicle must have a `TitleApplication` in status `ISSUED` whose
    `applicant_owner_id` equals the registration's `owner_id`".

    Positive side of the cross-entity dependency: with the title ISSUED (and emissions-exempt,
    fees paid), activation that fails on an un-issued title now succeeds.

    Design: Difficulty/cross_entity_state_dependency/registration_activate_requires_issued_title
    """
    owner, veh, reg, fa = setup_pending_registration_paid(model_year=2008, issue_title=True)
    activated = validate_success(api_client.activate_registration(reg["id"], CLERK), 200)
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/registration_term_overlap_same_vehicle_rejected
# ---------------------------------------------------------------------------
def test_second_registration_term_overlap_rejected():
    """PRD §3.5: "the new term — the half-open interval from the current clock to the current
    clock plus 365 days — must not overlap the term of any existing `ACTIVE` registration on
    the same vehicle; two intervals overlap when the new term's start is before the existing
    term's end and the existing term's start is before the new term's end ... a genuine overlap
    is rejected with `ERR_REGISTRATION_TERM_OVERLAP` (HTTP 409)."

    Reg1 term [2026-06-01, 2027-06-01) ACTIVE; reg2 activation at 2026-09-09 (100 days in)
    overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/registration_term_overlap_same_vehicle_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(residence_county_code="KING")
    veh = create_verified_vehicle(owner_id=owner["id"], model_year=2008, vehicle_class="PASSENGER")
    issue_clear_title(veh["id"], owner["id"], "INITIAL")
    veh = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    reg1 = create_registration(veh["id"], owner["id"], "INITIAL")
    assess_and_pay_fees(reg1["id"])
    validate_success(api_client.activate_registration(reg1["id"], CLERK), 200)

    reg2 = create_registration(veh["id"], owner["id"], "INITIAL")
    assess_and_pay_fees(reg2["id"])
    set_clock("2026-09-09T00:00:00Z")
    resp = api_client.activate_registration(reg2["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_TERM_OVERLAP.value)


def test_first_registration_activation_stamps_term():
    """PRD §3.5: "On a successful activation, `term_start` is set to the current clock and
    `term_end` to `term_start` plus 365 days".

    The first activation (no prior ACTIVE registration to overlap) succeeds and stamps the term
    window that the overlap check then guards against.

    Design: Difficulty/resource_temporal_overlap/registration_term_overlap_same_vehicle_rejected
    """
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    assert reg["status"] == "ACTIVE"
    assert reg["term_start"] is not None
    assert reg["term_end"] is not None


# ---------------------------------------------------------------------------
# Corner/validations/activate_registration_fees_unpaid_rejected
# ---------------------------------------------------------------------------
def test_activation_fees_unpaid_rejected():
    """PRD §3.5: "The registration's `FeeAssessment` must be in status `PAID`, or activation is
    rejected with `ERR_FEES_UNPAID` (HTTP 402)."

    An emissions-exempt (2008) vehicle with an ISSUED title but its FeeAssessment still ASSESSED
    (unpaid) fails activation — emissions and title gates pass, only the fee gate fails.

    Design: Corner/validations/activate_registration_fees_unpaid_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(residence_county_code="KING")
    veh = create_verified_vehicle(owner_id=owner["id"], model_year=2008, vehicle_class="PASSENGER")
    issue_clear_title(veh["id"], owner["id"], "INITIAL")
    veh = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    reg = create_registration(veh["id"], owner["id"], "INITIAL")
    assess_fees(reg["id"])  # assessed, not paid
    resp = api_client.activate_registration(reg["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_FEES_UNPAID.value)
