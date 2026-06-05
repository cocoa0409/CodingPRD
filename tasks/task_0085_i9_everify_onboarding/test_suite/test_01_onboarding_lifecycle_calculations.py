"""Onboarding creation, the three-business-day deadline, and the compliance-risk score.

Covers difficulty rules dual_variant_calc and combinatorial_formula plus corner
instances for entity creation, computed reads, and immediate consistency.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_onboarding, assert_risk_summary,
    create_onboarding_payload,
    create_onboarding, onboarding_through_section2, onboarding_with_tnc_case,
    present_document, attest_section1, complete_section2, set_clock,
    get_backing_form, submit_everify_case, api_client,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
OP = TEST_USERS["everify_operator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_section2_deadline_skips_weekend_and_juneteenth(api):
    """PRD §3.2: "Starting from the calendar date of `hire_date` taken at 00:00:00Z, the system walks forward one calendar day at a time; each day that is neither a Saturday nor a Sunday nor one of the 2026 federal holidays counts as one business day, and the walk stops once three business days have been counted."
    PRD §3.2: "The third counted business day, stamped at 23:59:59.999Z, is the `section2_deadline`."

    Design: Difficulty/combinatorial_formula/section2_deadline_business_day_skip
    """
    resp = api.create_onboarding(
        create_onboarding_payload(
            employee_full_name="Cy Park", employee_email="cy@x.com",
            citizenship_status="US_CITIZEN", hire_date="2026-06-17T00:00:00Z",
        ),
        HR,
    )
    data = validate_success(resp, 201)
    assert data["section2_deadline"] == "2026-06-23T23:59:59.999Z", (
        f"hire 2026-06-17 (Wed) should cross weekend + Juneteenth to 06-23, "
        f"got {data['section2_deadline']}"
    )


def test_section2_deadline_simple_hire_three_business_days(api):
    """PRD §3.2: "The first business day strictly after `hire_date` is day one — the hire date itself never counts. The third counted business day, stamped at 23:59:59.999Z, is the `section2_deadline`."

    Design: Difficulty/combinatorial_formula/section2_deadline_business_day_skip
    """
    resp = api.create_onboarding(
        create_onboarding_payload(
            employee_full_name="Mon Day", employee_email="mon@x.com",
            citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z",
        ),
        HR,
    )
    data = validate_success(resp, 201)
    # Mon 06-01 hire: Tue/Wed/Thu are the three business days -> 06-04.
    assert data["section2_deadline"] == "2026-06-04T23:59:59.999Z", (
        f"hire Mon 06-01 -> third business day 06-04, got {data['section2_deadline']}"
    )


def test_risk_score_sum_then_round_then_clamp_to_100(api):
    """PRD §3.8: "The accumulated total is summed first, then rounded half up, then clamped so that the final `risk_score` never exceeds 100 (and is never below 0); per-term rounding is not performed."
    PRD §3.8: "40 points when `is_overdue` is true; 25 points when the onboarding's E-Verify case is `was_late`; 20 points when the case's `tnc_type` is something other than `NONE` and the onboarding has not reached `AUTHORIZED`; 15 points for each accepted identity document that is a receipt (`is_receipt` true, status `ACCEPTED`) whose `receipt_resolution_deadline` is earlier than the clock"

    Design: Difficulty/combinatorial_formula/onboarding_risk_sum_then_round_clamp
    """
    ob = create_onboarding(
        employee_full_name="Di Wu", employee_email="di@x.com",
        citizenship_status="ALIEN_AUTHORIZED", hire_date="2026-06-01T00:00:00Z",
        work_auth_expiration="2026-06-20T00:00:00Z", requires_everify=True,
    )
    form = get_backing_form(ob["id"])
    fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob["id"], "auth_type": "EAD",
         "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2026-06-20T00:00:00Z"}, HR))
    # Complete Section 2 strictly after the 2026-06-04 deadline so is_overdue
    # latches (+40, PRD §3.2/§3.8). Accept two receipts via the List B + List C
    # path so each contributes the receipt term (+15 each, PRD §3.8); their
    # receipt_resolution_deadline (completed_at + 90d == 2026-09-08) falls before
    # the final clock (2026-09-15), making both unresolved.
    set_clock("2026-06-10T09:00:00Z")
    rcpt_b = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                             document_number="RB1", expiration_date=None, is_receipt=True)
    rcpt_c = present_document(ob["id"], list_category="LIST_C", document_title="SS_CARD",
                             document_number="RC1", expiration_date=None, is_receipt=True)
    ob_v1 = attest_section1(ob["id"])
    ob_v2 = complete_section2(ob["id"], [rcpt_b["id"], rcpt_c["id"]], ob_v1["version"])
    case = submit_everify_case(ob["id"], form["id"], ob_v2["version"], late_reason="delayed paperwork")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "SSA"}, OP))
    set_clock("2026-09-15T09:00:00Z")

    # overdue(40) + late(25) + open_tnc(20) + 2*receipt(30) = 115, clamped to 100.
    data = validate_success(api.get_onboarding_risk(ob["id"], CO))
    assert data["risk_score"] == 100, f"maxed posture should clamp to 100, got {data['risk_score']}"


def test_risk_open_tnc_true_when_unresolved_tnc_present(api):
    """PRD §3.8: "an `open_tnc` boolean indicating whether the case carries an unresolved Tentative Nonconfirmation."
    PRD §3.8: "20 points when the case's `tnc_type` is something other than `NONE` and the onboarding has not reached `AUTHORIZED`"

    Design: Difficulty/combinatorial_formula/onboarding_risk_sum_then_round_clamp
    """
    ob = create_onboarding(
        employee_full_name="Tn Cw", employee_email="tncw@x.com",
        citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z", requires_everify=True,
    )
    form = get_backing_form(ob["id"])
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="TNP", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    ob_v2 = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    case = submit_everify_case(ob["id"], form["id"], ob_v2["version"])
    set_clock("2026-06-10T12:00:00Z")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "DHS"}, OP))

    data = validate_success(api.get_onboarding_risk(ob["id"], CO))
    assert data["open_tnc"] is True, "an issued, unresolved TNC must surface open_tnc=true"


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_stem_cap_gap_within_ceiling_unclamped(api):
    """PRD §3.6: "`cap_gap_days` is the requested number of days but capped at a ceiling of 180, so a request of 180 or fewer days grants exactly that many while a request exceeding 180 clamps to 180."
    PRD §3.6: "The new record's `effective_valid_until` is its base `valid_until` plus `cap_gap_days` days"

    Design: Difficulty/dual_variant_calc/stem_cap_gap_within_vs_clamped
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-09-01T09:00:00Z",
                                  employee_full_name="Aiko Tan", employee_email="aiko@x.com")
    resp = fx.file_stem_extension(ob["id"], base["id"],
                                  valid_from="2026-09-30T00:00:00Z",
                                  valid_until="2028-09-30T00:00:00Z", requested_gap_days=120)
    data = validate_success(resp, 201)
    assert data["cap_gap_days"] == 120, f"expected 120, got {data['cap_gap_days']}"
    assert data["effective_valid_until"] == "2027-01-28T00:00:00.000Z", (
        f"base 09-30 + 120d, got {data['effective_valid_until']}"
    )


def test_onboarding_risk_overdue_plus_late_unclamped_sum(api):
    """PRD §3.8: "40 points when `is_overdue` is true; 25 points when the onboarding's E-Verify case is `was_late`"
    PRD §3.8: "The accumulated total is summed first, then rounded half up, then clamped so that the final `risk_score` never exceeds 100 (and is never below 0); per-term rounding is not performed."

    Design: Difficulty/dual_variant_calc/onboarding_risk_overdue_vs_clamped
    """
    ob = create_onboarding(
        employee_full_name="Bo Li", employee_email="bo@x.com",
        citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z", requires_everify=True,
    )
    form = get_backing_form(ob["id"])
    set_clock("2026-06-10T09:00:00Z")
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="P123", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    ob_v2 = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    submit_everify_case(ob["id"], form["id"], ob_v2["version"], late_reason="system outage")

    data = validate_success(api.get_onboarding_risk(ob["id"], CO))
    assert data["risk_score"] == 65, f"overdue(40)+late(25)=65, got {data['risk_score']}"
    ob_now = validate_success(api.get_onboarding(ob["id"], CO))
    assert ob_now["is_overdue"] is True, "onboarding overdue before late Section 2 must latch is_overdue"


def test_stem_cap_gap_within_ceiling_at_exactly_180(api):
    """PRD §3.6: "a request of 180 or fewer days grants exactly that many while a request exceeding 180 clamps to 180."
    PRD §3.6: "The new record's `effective_valid_until` is its base `valid_until` plus `cap_gap_days` days"

    Design: Difficulty/dual_variant_calc/stem_cap_gap_within_vs_clamped
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-09-01T09:00:00Z",
                                  employee_full_name="Aiko Tan2", employee_email="aiko2@x.com")
    resp = fx.file_stem_extension(ob["id"], base["id"],
                                  valid_from="2026-09-30T00:00:00Z",
                                  valid_until="2028-09-30T00:00:00Z", requested_gap_days=180)
    data = validate_success(resp, 201)
    assert data["cap_gap_days"] == 180, "exactly 180 requested is granted unclamped"
    # 2026-09-30 + 180 days == 2027-03-29.
    assert data["effective_valid_until"] == "2027-03-29T00:00:00.000Z"


def test_onboarding_risk_overdue_late_has_no_open_tnc(api):
    """PRD §3.8: "an `open_tnc` boolean indicating whether the case carries an unresolved Tentative Nonconfirmation."
    PRD §3.8: "40 points when `is_overdue` is true; 25 points when the onboarding's E-Verify case is `was_late`"

    Design: Difficulty/dual_variant_calc/onboarding_risk_overdue_vs_clamped
    """
    ob = create_onboarding(
        employee_full_name="Bo Li2", employee_email="bo2@x.com",
        citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z", requires_everify=True,
    )
    form = get_backing_form(ob["id"])
    set_clock("2026-06-10T09:00:00Z")
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="P124", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    ob_v2 = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    submit_everify_case(ob["id"], form["id"], ob_v2["version"], late_reason="system outage")

    data = validate_success(api.get_onboarding_risk(ob["id"], CO))
    assert data["risk_score"] == 65
    assert data["open_tnc"] is False, "no TNC issued -> open_tnc must be false"


# ===========================================================================
# Queue B — corner: entities (creation, defaults, system fields, listing)
# ===========================================================================
def test_create_onboarding_returns_201_with_computed_deadline(api):
    """PRD §3.1: "At creation the onboarding enters `CREATED` status, the system pins its Section 2 deadline into `section2_deadline` from the `hire_date` (see §3.2 for the arithmetic), and a backing `I9Form` is created in `SECTION1_PENDING` carrying this onboarding's `onboarding_id`."
    PRD §2.4: "`version`** — a system-managed integer that begins at creation and increments by one on every mutation."

    Design: Corner/entities/create_onboarding_returns_201_with_computed_deadline
    """
    resp = api.create_onboarding(
        create_onboarding_payload(employee_full_name="Al Be", employee_email="al@x.com",
                                  citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z"),
        HR,
    )
    data = validate_success(resp, 201)
    assert_onboarding(data)
    assert data["status"] == "CREATED"
    assert data["version"] == 1
    assert data["section2_deadline"] == "2026-06-04T23:59:59.999Z"


def test_get_onboarding_not_found_returns_404(api):
    """PRD §2.5: "the system validates their existence left to right, in the order they appear, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_onboarding_not_found_returns_404
    """
    resp = api.get_onboarding("00000000-0000-4000-8000-000000000000", HR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_onboarding_missing_citizenship_returns_invalid_request(api):
    """PRD §3.1: "The creation payload supplies the new hire's legal name in `employee_full_name`, contact address in `employee_email`, the Section 1 attested `citizenship_status`, and the `hire_date`"
    PRD §2.8: "generic body well-formedness and enum-domain validation (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/create_onboarding_missing_required_field_returns_invalid_request
    """
    resp = api.create_onboarding(
        {"employee_full_name": "No Cs", "employee_email": "nocs@x.com",
         "hire_date": "2026-06-01T00:00:00Z"}, HR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_requires_everify_defaults_true_when_omitted(api):
    """PRD §3.1: "The payload may also set `requires_everify`, which declares whether the worksite is enrolled in E-Verify and gates whether an E-Verify case is ever created; it defaults to true when omitted."

    Design: Corner/entities/create_onboarding_requires_everify_defaults_true
    """
    resp = api.create_onboarding(
        create_onboarding_payload(employee_full_name="De Fa", employee_email="def@x.com",
                                  citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z"),
        HR,
    )
    data = validate_success(resp, 201)
    assert data["requires_everify"] is True


def test_invalid_citizenship_enum_returns_invalid_request(api):
    """PRD §3.1: "The `citizenship_status` is one of `US_CITIZEN`, `NONCITIZEN_NATIONAL`, `LPR`, or `ALIEN_AUTHORIZED`."
    PRD §2.8: "generic body well-formedness and enum-domain validation (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/create_onboarding_invalid_enum_citizenship_returns_invalid_request
    """
    resp = api.create_onboarding(
        create_onboarding_payload(employee_full_name="Ba Dz", employee_email="bad@x.com",
                                  citizenship_status="MARTIAN", hire_date="2026-06-01T00:00:00Z"),
        HR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_system_fields_minted_not_client_supplied(api):
    """PRD §3.1: "At creation the onboarding enters `CREATED` status, the system pins its Section 2 deadline into `section2_deadline` from the `hire_date` (see §3.2 for the arithmetic)"

    Design: Corner/entities/system_fields_ignored_on_onboarding_create
    """
    resp = api.create_onboarding(
        create_onboarding_payload(
            employee_full_name="Sy St", employee_email="sys@x.com",
            citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z",
            status="AUTHORIZED", section2_deadline="2099-01-01T00:00:00.000Z",
        ),
        HR,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "CREATED"
    assert data["section2_deadline"] == "2026-06-04T23:59:59.999Z"


def test_list_onboardings_pagination_envelope(api):
    """PRD §2.3: "Every paginated list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter sets the maximum number of items returned"

    Design: Corner/entities/list_onboardings_pagination_envelope
    """
    create_onboarding(employee_full_name="P1", employee_email="p1@x.com")
    create_onboarding(employee_full_name="P2", employee_email="p2@x.com")
    data, meta = validate_paginated(api.list_onboardings(CO, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_audit_entry_is_append_only_no_version(api):
    """PRD §2.4: "The `AuditEntry` resource is the one exception: it is an append-only event-log record that carries only `id` and `created_at`. An `AuditEntry` has no `updated_at` and no `version`, because it is never modified after it is written."

    Design: Corner/entities/immutable_audit_entry_has_no_version
    """
    ob, _form, _doc = onboarding_through_section2(
        employee_full_name="Au Di", employee_email="au@x.com", requires_everify=False,
    )
    data, meta = validate_paginated(api.list_audit_entries(CO, params={"onboarding_id": ob["id"]}))
    assert meta["total_count"] >= 1, "Section 2 completion must append an AuditEntry"
    for entry in data:
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry, "AuditEntry must not expose version"
        assert "updated_at" not in entry, "AuditEntry must not expose updated_at"


# ===========================================================================
# Queue B — corner: endpoints (computed read) and consistency_model
# ===========================================================================
def test_risk_endpoint_fresh_onboarding_scores_zero(api):
    """PRD §3.8: "A read-only compliance-risk summary is available for any onboarding and is recomputed after every onboarding-affecting mutation. It returns three values: an integer `risk_score`, the boolean `is_overdue` flag, and an `open_tnc` boolean indicating whether the case carries an unresolved Tentative Nonconfirmation."
    PRD §3.8: "Starting from zero, the score accumulates"

    Design: Corner/endpoints/get_onboarding_risk_computed_read
    """
    ob = create_onboarding(employee_full_name="Ri Sk", employee_email="ri@x.com",
                           citizenship_status="US_CITIZEN", hire_date="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    data = validate_success(api.get_onboarding_risk(ob["id"], CO))
    assert_risk_summary(data)
    assert data["risk_score"] == 0
    assert data["is_overdue"] is False


def test_section2_complete_returns_section2_complete_in_same_response(api):
    """PRD §2.9: "When an operation completes, it both advances the directly targeted resource and applies any cascade onto the related resources, in the same transaction"
    PRD §3.3: "An `AuditEntry` with action `SECTION2_COMPLETED` is appended, the onboarding moves to `SECTION2_COMPLETE`, and its `version` increments by one."

    Design: Corner/consistency_model/immediate_consistency_section2_visible_in_same_response
    """
    ob_after, _form, doc = fx.setup_section1_with_list_a_doc(
        doc_overrides={"document_number": "IM"},
        employee_full_name="Im Co", employee_email="im@x.com", requires_everify=False,
    )
    resp = api.section2_complete(
        ob_after["id"], {"document_ids": [doc["id"]],
                         "expected_onboarding_version": ob_after["version"]}, HR)
    data = validate_success(resp)
    assert data["status"] == "SECTION2_COMPLETE", "Section 2 status must be visible immediately"
