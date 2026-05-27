"""Continuation/CIP filing relationships and the provisional 12-month
conversion lifecycle: continuation-type-mismatch, continuation-off-terminal-
parent rejection, the late-conversion temporal limit, and the single-shot
conversion guard.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock,
    create_applicant, create_application,
    setup_provisional_filed,
    setup_parent_application_abandoned,
    create_application_payload,
    create_convert_provisional_payload,
)


# =============================================================================
# Corner / state_machines / convert_provisional_after_12_months_returns_late
# =============================================================================

def test_convert_provisional_after_12_months_rejected(api):
    """Conversion attempted strictly after filing_date + 12 months is
    rejected with ERR_PROVISIONAL_CONVERSION_LATE.

    PRD §3.9: "A late conversion attempt — `current_utc` strictly after
    that 12-month anchor — is rejected with `ERR_PROVISIONAL_CONVERSION_LATE`."

    Design: Corner/state_machines/convert_provisional_after_12_months_returns_late
    """
    set_clock("2024-01-01T00:00:00.000Z")
    applicant, prov = setup_provisional_filed(entity_size="LARGE")

    set_clock("2026-01-01T00:00:00.000Z")  # >12 months later
    res = api.convert_provisional(
        prov["id"],
        create_convert_provisional_payload(
            title="Converted widget", claim_count=15,
            independent_claim_count=3,
            expected_application_version=prov["version"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROVISIONAL_CONVERSION_LATE.value)


# =============================================================================
# Corner / state_machines / error_provisional_already_converted_double_convert
# =============================================================================

def test_double_convert_provisional_rejected(api):
    """A PROVISIONAL may be converted at most once. After the first
    conversion (status=CONVERTED), a second attempt must be rejected —
    PRD's combined treatment is that this hits either the single-shot guard
    (ERR_PROVISIONAL_ALREADY_CONVERTED) or the terminal-state check
    (ERR_INVALID_STATE), since CONVERTED is a terminal state per §3.9.

    PRD §3.9: "A second conversion attempt against a provisional whose
    status is already `CONVERTED` is rejected with
    `ERR_PROVISIONAL_ALREADY_CONVERTED`, because conversion is single-shot."
    PRD §2.7: "Only after these gates pass does the server evaluate
    state-machine admissibility (`ERR_INVALID_STATE` if the transition is
    not defined out of the current state, `ERR_TERMINAL_STATE` if the
    source state is in the entity's terminal set — namely `ABANDONED`,
    `EXPIRED`, `CONVERTED` for an application..."

    Design: Corner/state_machines/error_provisional_already_converted_double_convert
    """
    from prd_bench_local_runner.testing import validate_error_is_one_of

    set_clock("2026-01-01T00:00:00.000Z")
    applicant, prov = setup_provisional_filed(entity_size="LARGE")

    convert_res = api.convert_provisional(
        prov["id"],
        create_convert_provisional_payload(
            title="First conv", claim_count=15, independent_claim_count=3,
            expected_application_version=prov["version"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    first = validate_success(convert_res, 201)
    # The new child UTILITY was returned; the source provisional is now CONVERTED.
    # Re-read the source provisional to capture its bumped version.
    src_after = validate_success(
        api.get_application(prov["id"], make_applicant_headers(applicant["id"])),
        200,
    )
    assert src_after["status"] == "CONVERTED"

    # Second conversion against the now-CONVERTED source.
    res2 = api.convert_provisional(
        prov["id"],
        create_convert_provisional_payload(
            title="Second conv", claim_count=15, independent_claim_count=3,
            expected_application_version=src_after["version"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error_is_one_of(res2, [
        ApiErrorId.ERR_PROVISIONAL_ALREADY_CONVERTED.value,
        ApiErrorId.ERR_INVALID_STATE.value,
        ApiErrorId.ERR_TERMINAL_STATE.value,
    ])


# =============================================================================
# Corner / validations / continuation_with_terminal_parent_rejected
# =============================================================================

def test_continuation_off_abandoned_parent_rejected(api):
    """Filing a CONTINUATION off a parent in ABANDONED is rejected with
    ERR_CONTINUATION_PARENT_TERMINAL.

    PRD §3.2: "The referenced parent must not be in a terminal lifecycle
    state — that is, not in `ABANDONED`, `EXPIRED`, or `CONVERTED` —
    because dead applications can no longer spawn continuations; a parent
    in `ISSUED` is permitted, since continuations off issued patents are a
    legitimate prosecution strategy. A parent in any other excluded
    terminal state rejects the create with
    `ERR_CONTINUATION_PARENT_TERMINAL`."

    Design: Corner/validations/continuation_with_terminal_parent_rejected
    """
    applicant, parent = setup_parent_application_abandoned()
    assert parent["status"] == "ABANDONED"

    res = api.create_application(
        create_application_payload(
            applicant_id=applicant["id"], application_type="UTILITY",
            title="CT child", claim_count=10, independent_claim_count=2,
            parent_application_id=parent["id"], continuation_type="CONTINUATION",
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTINUATION_PARENT_TERMINAL.value)


# =============================================================================
# Corner / validations / continuation_type_without_parent_rejected
# =============================================================================

def test_continuation_type_without_parent_application_id_rejected(api):
    """continuation_type=CIP but parent_application_id=null is rejected with
    ERR_CONTINUATION_TYPE_MISMATCH.

    PRD §3.2: "The pair must be coherent: when `parent_application_id` is
    null, `continuation_type` must also be null, and when
    `parent_application_id` is set, `continuation_type` must be set to
    `CONTINUATION` or `CIP`; any other combination is rejected with
    `ERR_CONTINUATION_TYPE_MISMATCH`."

    Design: Corner/validations/continuation_type_without_parent_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(legal_name="NoParent Co", entity_size="LARGE")
    res = api.create_application(
        {
            "applicant_id": applicant["id"],
            "application_type": "UTILITY",
            "title": "NoParent widget",
            "claim_count": 10,
            "independent_claim_count": 2,
            "continuation_type": "CIP",  # without parent_application_id
        },
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTINUATION_TYPE_MISMATCH.value)


# =============================================================================
# Corner / validations / extension_months_above_three_rejected
# =============================================================================

def test_extension_months_above_three_rejected(api):
    """extension_months_requested=4 (out of {0,1,2,3}) returns
    ERR_EXTENSION_MONTHS_INVALID.

    PRD §3.5: "The `extension_months_requested` parameter must be an
    integer in the set {0, 1, 2, 3}; anything outside that set is rejected
    with `ERR_EXTENSION_MONTHS_INVALID` before any extension fee is
    computed."

    Design: Corner/validations/extension_months_above_three_rejected
    """
    from test_helpers import (
        setup_application_with_outstanding_oa,
        create_office_action_response_payload,
    )
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    res = api.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=oa["id"],
            extension_months_requested=4, claim_amendment_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EXTENSION_MONTHS_INVALID.value)
