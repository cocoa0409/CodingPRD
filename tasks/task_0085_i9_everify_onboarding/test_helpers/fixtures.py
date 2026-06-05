"""Composite setup helpers.

Each function builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of every test.
Setup calls use get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Role identities are opaque (PRD §2.1); the helpers default to the shared role
headers and accept overrides where a test needs a specific X-User-ID (e.g.
segregation-of-duties tests).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_hr_reviewer_headers,
    make_compliance_officer_headers,
)
from . import factories as f

HR = TEST_USERS["hr_reviewer_headers"]
OP = TEST_USERS["everify_operator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the deterministic server clock (ComplianceOfficer capability)."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), CO))


# ---------------------------------------------------------------------------
# Tier 1: Onboarding creation and the I9Form lookup
# ---------------------------------------------------------------------------
def create_onboarding(**overrides):
    """Create an onboarding. Returns the onboarding dict."""
    payload = f.create_onboarding_payload(**overrides)
    return get_success_data(api_client.create_onboarding(payload, HR))


def get_backing_form(onboarding_id, headers=HR):
    """Fetch the auto-created backing I9Form for an onboarding."""
    data, _ = _list(api_client.list_i9_forms(headers, params={"onboarding_id": onboarding_id}))
    assert data, f"no backing I9Form for onboarding {onboarding_id}"
    return data[0]


def present_document(onboarding_id, **overrides):
    """Present an identity document against an onboarding."""
    payload = f.create_identity_document_payload(onboarding_id, **overrides)
    return get_success_data(api_client.create_identity_document(payload, HR))


def attest_section1(onboarding_id, headers=HR, **payload_overrides):
    """Attest Section 1. Returns the updated onboarding dict."""
    payload = f.section1_attest_payload(**payload_overrides)
    return get_success_data(api_client.section1_attest(onboarding_id, payload, headers))


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 2: Reach Section 1 complete and Section 2 complete
# ---------------------------------------------------------------------------
def onboarding_past_section1(**overrides):
    """Create an onboarding and attest Section 1.
    Returns (onboarding_after_attest, form). The onboarding is in SECTION1_COMPLETE."""
    ob = create_onboarding(**overrides)
    form = get_backing_form(ob["id"])
    ob_after = attest_section1(ob["id"])
    return ob_after, form


def setup_section1_with_list_a_doc(doc_overrides=None, **ob_overrides):
    """Onboarding in SECTION1_COMPLETE with one PRESENTED List A passport.
    Returns (onboarding_after_attest, form, document). Document presented BEFORE
    attest so the version captured after attest is the right one for section2."""
    ob = create_onboarding(**ob_overrides)
    form = get_backing_form(ob["id"])
    doc = present_document(ob["id"], **(doc_overrides or {}))
    ob_after = attest_section1(ob["id"])
    return ob_after, form, doc


def complete_section2(onboarding_id, document_ids, expected_version, headers=HR):
    """Complete Section 2 with a chosen documentary set. Returns the updated onboarding."""
    payload = f.section2_complete_payload(document_ids, expected_version)
    return get_success_data(api_client.section2_complete(onboarding_id, payload, headers))


def onboarding_through_section2(doc_overrides=None, **ob_overrides):
    """Onboarding driven through Section 2 with a single List A passport.
    Returns (onboarding_after_section2, form, document). Status SECTION2_COMPLETE."""
    ob_after, form, doc = setup_section1_with_list_a_doc(
        doc_overrides=doc_overrides, **ob_overrides
    )
    ob_s2 = complete_section2(ob_after["id"], [doc["id"]], ob_after["version"])
    return ob_s2, form, doc


# ---------------------------------------------------------------------------
# Tier 3: E-Verify lifecycle shortcuts
# ---------------------------------------------------------------------------
def submit_everify_case(onboarding_id, i9_form_id, expected_version, **overrides):
    """Submit an E-Verify case (EVerifyOperator). Returns the case dict."""
    payload = f.create_everify_case_payload(
        onboarding_id, i9_form_id, expected_version, **overrides
    )
    return get_success_data(api_client.create_everify_case(payload, OP))


def onboarding_with_submitted_case(**ob_overrides):
    """Onboarding in EVERIFY_PENDING with a SUBMITTED E-Verify case.
    Returns (onboarding_after_section2, form, case)."""
    ob_overrides.setdefault("requires_everify", True)
    ob_s2, form, _doc = onboarding_through_section2(**ob_overrides)
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    return ob_s2, form, case


def onboarding_with_tnc_case(agency="DHS", **ob_overrides):
    """Onboarding in EVERIFY_PENDING with a case in TNC_ISSUED.
    Returns (onboarding, form, case_after_tnc)."""
    ob_s2, form, case = onboarding_with_submitted_case(**ob_overrides)
    case_tnc = get_success_data(
        api_client.everify_result(case["id"], f.everify_result_payload("TNC", agency=agency), OP)
    )
    return ob_s2, form, case_tnc


# ---------------------------------------------------------------------------
# Tier 4: Non-E-Verify AUTHORIZED + reverification setups
# ---------------------------------------------------------------------------
def finalize_onboarding(onboarding_id, headers=CO):
    """Finalize a non-E-Verify onboarding to AUTHORIZED. Returns updated onboarding."""
    return get_success_data(api_client.finalize_onboarding(onboarding_id, {}, headers))


def advance_lifecycle(onboarding_id, headers=CO):
    """Re-derive deadlines and apply due automatic transitions. Returns updated onboarding."""
    return get_success_data(api_client.advance_lifecycle(onboarding_id, {}, headers))


def authorized_non_everify_with_auth(auth_valid_until, doc_expiration=None, **ob_overrides):
    """Build a non-E-Verify onboarding driven to AUTHORIZED with a controlling
    WorkAuthorization (auth_type EAD) whose valid_until = auth_valid_until.
    Returns (onboarding, form, work_authorization, document).

    Note: the work authorization and identity document are created BEFORE
    Section 1 attest so the post-attest version is correct for section2."""
    ob_overrides.setdefault("requires_everify", False)
    ob_overrides.setdefault("citizenship_status", "ALIEN_AUTHORIZED")
    ob_overrides.setdefault("work_auth_expiration", auth_valid_until)
    ob = create_onboarding(**ob_overrides)
    form = get_backing_form(ob["id"])
    wa = get_success_data(
        api_client.create_work_authorization(
            f.create_work_authorization_payload(
                ob["id"], auth_type="EAD",
                valid_from="2026-01-01T00:00:00Z", valid_until=auth_valid_until,
            ),
            HR,
        )
    )
    doc = present_document(
        ob["id"], list_category="LIST_A", document_title="EAD",
        document_number="EAD1", expiration_date=doc_expiration or auth_valid_until,
    )
    ob_after = attest_section1(ob["id"])
    complete_section2(ob_after["id"], [doc["id"]], ob_after["version"])
    ob_auth = finalize_onboarding(ob["id"])
    return ob_auth, form, wa, doc


def onboarding_reverification_due(auth_valid_until, clock_past, **ob_overrides):
    """Drive a non-E-Verify onboarding to REVERIFICATION_DUE by advancing the clock
    past the controlling auth's effective_valid_until and invoking advance-lifecycle.
    Returns (onboarding_now_due, form, work_authorization)."""
    ob_auth, form, wa, _doc = authorized_non_everify_with_auth(
        auth_valid_until, **ob_overrides
    )
    set_clock(clock_past)
    ob_due = advance_lifecycle(ob_auth["id"])
    return ob_due, form, wa


# ---------------------------------------------------------------------------
# Tier 5: STEM OPT base authorization
# ---------------------------------------------------------------------------
def setup_stem_base(base_valid_until="2026-09-30T00:00:00Z", filing_clock="2026-09-01T09:00:00Z",
                    **ob_overrides):
    """Onboarding (ALIEN_AUTHORIZED) with a base F1_OPT WorkAuthorization (ACTIVE),
    clock set to a timely filing instant. Returns (onboarding, base_work_authorization)."""
    ob_overrides.setdefault("requires_everify", False)
    ob_overrides.setdefault("citizenship_status", "ALIEN_AUTHORIZED")
    ob_overrides.setdefault("work_auth_expiration", base_valid_until)
    ob = create_onboarding(**ob_overrides)
    if filing_clock is not None:
        set_clock(filing_clock)
    base = get_success_data(
        api_client.create_work_authorization(
            f.create_work_authorization_payload(
                ob["id"], auth_type="F1_OPT",
                valid_from="2026-04-01T00:00:00Z", valid_until=base_valid_until,
            ),
            HR,
        )
    )
    return ob, base


def file_stem_extension(onboarding_id, base_id, valid_from, valid_until,
                        requested_gap_days, **overrides):
    """File a STEM OPT extension superseding a base F1_OPT authorization.
    Returns the raw Response (so callers can assert success OR error)."""
    payload = f.create_work_authorization_payload(
        onboarding_id, auth_type="F1_STEM_OPT", valid_from=valid_from,
        valid_until=valid_until, stem_extension_applied=True, supersedes_id=base_id,
        requested_gap_days=requested_gap_days, **overrides,
    )
    return api_client.create_work_authorization(payload, HR)
