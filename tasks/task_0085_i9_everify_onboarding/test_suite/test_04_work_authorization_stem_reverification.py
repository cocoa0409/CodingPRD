"""Work authorizations, STEM OPT extensions, and Section 3 reverification.

Covers difficulty rules non_linear_state_machine (WorkAuthorization cycle),
resource_temporal_overlap (STEM filing window), compensating_invariant (active-auth
conservation), and corner state-machine reverification / expiry instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_onboarding, present_document, attest_section1, complete_section2,
    set_clock, get_backing_form, api_client,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine (WorkAuthorization ACTIVE->EXTENDED->SUPERSEDED)
# ===========================================================================
def test_workauth_cycle_extended_then_superseded_by_section3(api):
    """PRD §3.6: "Filing the extension moves the superseded base from `ACTIVE` to `EXTENDED` and the new extension record is itself `ACTIVE` or `EXTENDED`."
    PRD §3.6: "the prior `WorkAuthorization` is marked `SUPERSEDED` while the newly presented one is `ACTIVE` or `EXTENDED`, an `AuditEntry` with action `REVERIFIED` is appended, and the onboarding's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/workauth_cycle_active_extended_superseded
    """
    ob = create_onboarding(employee_full_name="Fi Ng", employee_email="fi@x.com",
                           citizenship_status="ALIEN_AUTHORIZED",
                           work_auth_expiration="2026-09-30T00:00:00Z", requires_everify=False)
    form = get_backing_form(ob["id"])
    set_clock("2026-09-01T09:00:00Z")
    wa_b = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob["id"], "auth_type": "F1_OPT",
         "valid_from": "2026-04-01T00:00:00Z", "valid_until": "2026-09-30T00:00:00Z"}, HR))
    wa_e = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob["id"], "auth_type": "F1_STEM_OPT",
         "valid_from": "2026-09-30T00:00:00Z", "valid_until": "2028-09-30T00:00:00Z",
         "stem_extension_applied": True, "supersedes_id": wa_b["id"], "requested_gap_days": 120}, HR))
    doc = present_document(ob["id"], list_category="LIST_A", document_title="EAD",
                           document_number="E1", expiration_date="2028-09-30T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    fx.get_success_data(api.finalize_onboarding(ob["id"], {}, CO))
    set_clock("2028-09-29T09:00:00Z")
    fx.get_success_data(api.advance_lifecycle(ob["id"], {}, CO))
    wa_new = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob["id"], "auth_type": "EAD",
         "valid_from": "2028-09-29T00:00:00Z", "valid_until": "2031-09-29T00:00:00Z"}, HR))
    fx.get_success_data(api.create_section3(
        form["id"], {"work_authorization_id": wa_new["id"],
                     "reverification_reason": "EXPIRING_AUTH",
                     "new_expiration_date": "2031-09-29T00:00:00Z"}, HR))

    ext = validate_success(api.get_work_authorization(wa_e["id"], HR))
    assert ext["status"] == "SUPERSEDED"
    ob_after = validate_success(api.get_onboarding(ob["id"], HR))
    assert ob_after["status"] == "AUTHORIZED"


def test_stem_filing_extends_base_to_extended_status(api):
    """PRD §3.6: "Filing the extension moves the superseded base from `ACTIVE` to `EXTENDED` and the new extension record is itself `ACTIVE` or `EXTENDED`."

    Design: Difficulty/non_linear_state_machine/workauth_cycle_active_extended_superseded
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-09-01T09:00:00Z",
                                  employee_full_name="Fi Ng2", employee_email="fi2@x.com")
    fx.file_stem_extension(ob["id"], base["id"], valid_from="2026-09-30T00:00:00Z",
                           valid_until="2028-09-30T00:00:00Z", requested_gap_days=120)
    base_after = validate_success(api.get_work_authorization(base["id"], HR))
    assert base_after["status"] == "EXTENDED", "base F1_OPT must move ACTIVE -> EXTENDED"


# ===========================================================================
# Queue A — resource_temporal_overlap (STEM filing window inclusive boundary)
# ===========================================================================
def test_stem_filed_after_base_valid_until_is_rejected(api):
    """PRD §3.6: "It is timely only when the base authorization it supersedes is of `auth_type` `F1_OPT` and is currently `ACTIVE`, and when the extension is filed (its creation clock) on or before the base's `valid_until` — the comparison is inclusive, so filing exactly on the base `valid_until` is still timely. If the base is not an `F1_OPT` record, or if the filing clock is strictly after the base `valid_until`, the extension is rejected with `ERR_STEM_WINDOW_MISSED`."

    Design: Difficulty/resource_temporal_overlap/stem_extension_filing_window_inclusive_boundary
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-10-01T09:00:00Z",
                                  employee_full_name="Pa Te", employee_email="pa@x.com")
    resp = fx.file_stem_extension(ob["id"], base["id"], valid_from="2026-10-01T00:00:00Z",
                                  valid_until="2028-10-01T00:00:00Z", requested_gap_days=120)
    validate_error(resp, ApiErrorId.ERR_STEM_WINDOW_MISSED.value, 422)


def test_stem_filed_exactly_on_base_valid_until_is_timely(api):
    """PRD §3.6: "the comparison is inclusive, so filing exactly on the base `valid_until` is still timely."

    Design: Difficulty/resource_temporal_overlap/stem_extension_filing_window_inclusive_boundary
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-09-30T00:00:00Z",
                                  employee_full_name="Pa Te2", employee_email="pa2@x.com")
    resp = fx.file_stem_extension(ob["id"], base["id"], valid_from="2026-09-30T00:00:00Z",
                                  valid_until="2028-09-30T00:00:00Z", requested_gap_days=120)
    validate_success(resp, 201)


# ===========================================================================
# Queue A — compensating_invariant (single active authorization conservation)
# ===========================================================================
def test_active_authorization_count_stays_one_across_reverification(api):
    """PRD §3.6: "the prior `WorkAuthorization` is marked `SUPERSEDED` while the newly presented one is `ACTIVE` or `EXTENDED`, an `AuditEntry` with action `REVERIFIED` is appended, and the onboarding's `version` increments by one."
    PRD §2.5: "Several list endpoints also accept a `status` query parameter that restricts results to resources whose `status` field equals the supplied value — onboardings, identity documents, E-Verify cases, and work authorizations all support this filter."

    Design: Difficulty/compensating_invariant/work_authorization_active_record_invariant
    """
    ob_due, form, wa_old = fx.onboarding_reverification_due(
        auth_valid_until="2026-12-31T00:00:00Z", clock_past="2027-01-02T09:00:00Z",
        employee_full_name="Sa Tu", employee_email="sa@x.com",
        work_auth_expiration="2026-12-31T00:00:00Z",
    )
    wa_succ = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob_due["id"], "auth_type": "EAD",
         "valid_from": "2027-01-02T00:00:00Z", "valid_until": "2030-01-02T00:00:00Z"}, HR))
    fx.get_success_data(api.create_section3(
        form["id"], {"work_authorization_id": wa_succ["id"],
                     "reverification_reason": "EXPIRING_AUTH",
                     "new_expiration_date": "2030-01-02T00:00:00Z"}, HR))

    old_after = validate_success(api.get_work_authorization(wa_old["id"], HR))
    succ_after = validate_success(api.get_work_authorization(wa_succ["id"], HR))
    assert old_after["status"] == "SUPERSEDED"
    assert succ_after["status"] == "ACTIVE"
    _data, meta = validate_paginated(api.list_work_authorizations(
        HR, params={"onboarding_id": ob_due["id"], "status": "ACTIVE"}))
    assert meta["total_count"] == 1, "exactly one ACTIVE work authorization after reverification"


def test_superseded_authorization_count_grows_by_exactly_one_on_reverification(api):
    """PRD §3.6: "the prior `WorkAuthorization` is marked `SUPERSEDED` while the newly presented one is `ACTIVE` or `EXTENDED`"
    PRD §2.5: "Several list endpoints also accept a `status` query parameter that restricts results to resources whose `status` field equals the supplied value — onboardings, identity documents, E-Verify cases, and work authorizations all support this filter."

    Design: Difficulty/compensating_invariant/work_authorization_active_record_invariant
    """
    ob_due, form, _wa_old = fx.onboarding_reverification_due(
        auth_valid_until="2026-12-31T00:00:00Z", clock_past="2027-01-02T09:00:00Z",
        employee_full_name="Sa Tu2", employee_email="sa2@x.com",
        work_auth_expiration="2026-12-31T00:00:00Z",
    )
    # Before reverification: no SUPERSEDED authorizations yet for this onboarding.
    _d0, meta0 = validate_paginated(api.list_work_authorizations(
        HR, params={"onboarding_id": ob_due["id"], "status": "SUPERSEDED"}))
    assert meta0["total_count"] == 0
    wa_succ = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob_due["id"], "auth_type": "EAD",
         "valid_from": "2027-01-02T00:00:00Z", "valid_until": "2030-01-02T00:00:00Z"}, HR))
    fx.get_success_data(api.create_section3(
        form["id"], {"work_authorization_id": wa_succ["id"],
                     "reverification_reason": "EXPIRING_AUTH",
                     "new_expiration_date": "2030-01-02T00:00:00Z"}, HR))
    _d1, meta1 = validate_paginated(api.list_work_authorizations(
        HR, params={"onboarding_id": ob_due["id"], "status": "SUPERSEDED"}))
    assert meta1["total_count"] == 1, "exactly the prior authorization flips to SUPERSEDED"


# ===========================================================================
# Queue B — corner: state_machines (auto transitions on clock advance)
# ===========================================================================
def test_authorized_to_reverification_due_on_clock_advance(api):
    """PRD §3.6: "Once an onboarding is `AUTHORIZED`, the system watches the controlling authorization's `effective_valid_until`. When the clock crosses that date — and no later recorded Section 3 block already covers it — the onboarding automatically moves from `AUTHORIZED` to `REVERIFICATION_DUE` (audited with action `REVERIFICATION_DUE`, onboarding `version` bumped)."

    Design: Corner/state_machines/reverification_due_auto_transition_on_clock_advance
    """
    ob_due, _form, _wa = fx.onboarding_reverification_due(
        auth_valid_until="2026-12-31T00:00:00Z", clock_past="2027-01-02T09:00:00Z",
        employee_full_name="Rv Du", employee_email="rv@x.com",
        work_auth_expiration="2026-12-31T00:00:00Z",
    )
    assert ob_due["status"] == "REVERIFICATION_DUE"


def test_reverification_lapse_moves_to_expired_unauthorized(api):
    """PRD §3.6: "If, by contrast, the clock moves past the controlling authorization's `effective_valid_until` while the onboarding sits in `REVERIFICATION_DUE` and no covering Section 3 block is recorded, the onboarding moves automatically to the terminal `EXPIRED_UNAUTHORIZED` (audited with action `EXPIRED_UNAUTHORIZED`, `version` bumped)."

    Design: Corner/state_machines/expired_unauthorized_when_reverification_lapses
    """
    ob_due, _form, _wa = fx.onboarding_reverification_due(
        auth_valid_until="2026-12-31T00:00:00Z", clock_past="2027-01-02T09:00:00Z",
        employee_full_name="Ex Un", employee_email="ex@x.com",
        work_auth_expiration="2026-12-31T00:00:00Z",
    )
    set_clock("2027-02-01T09:00:00Z")
    ob_after = fx.get_success_data(api.advance_lifecycle(ob_due["id"], {}, CO))
    assert ob_after["status"] == "EXPIRED_UNAUTHORIZED"
