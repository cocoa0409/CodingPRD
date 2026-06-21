"""Case opening, CRUD, listing, config immutability, and simple status side effects.

Translates queue B (Corner) instances from the `entities` and `state_machines`
sections that exercise creation, not-found, required-field, listing, immutability,
defaults, and case-status side effects.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS,
    assert_case, assert_guideline_schedule,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX

CLERK = TEST_USERS["clerk_headers"]


def test_create_case_returns_201_with_system_fields(api):
    """PRD §3.1: "A newly opened case enters `FILED` status with `version` 1, its
    `net_fees_collected_cents` initialized to the supplied `filing_fee_cents`, and
    its `active_support_total_cents` initialized to 0."

    Design: Corner/entities/create_case_returns_201_with_system_fields
    """
    FX.register_schedule(state_code="CA")
    resp = api.create_case(
        F.case_payload(state_code="CA", caption="In re Marriage of Test",
                       marriage_months=84, filing_fee_cents=43500), CLERK)
    data = validate_success(resp, 201)
    assert_case(data)
    assert data["status"] == "FILED"
    assert data["version"] == 1
    assert data["net_fees_collected_cents"] == 43500
    assert data["active_support_total_cents"] == 0


def test_get_case_not_found_returns_404(api):
    """PRD §2.4: "the first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any
    business rule is evaluated."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_party_missing_required_field_returns_invalid_request(api):
    """PRD §2.5: "the request body is checked for schema conformance — required fields
    present, enumerations valid, and numeric ranges respected — failing which the
    response is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.2: "Each party is created with the `case_id` it belongs to, a `role` of
    either `PETITIONER` or `RESPONDENT`, the operator `user_id` the party is bound to
    ... a `full_name`, and a declared `gross_monthly_income_cents`".

    Design: Corner/validations/create_party_missing_required_field_returns_invalid_request
    """
    case = FX.create_case()
    payload = {"case_id": case["id"], "user_id": "u-x", "full_name": "No Role",
               "gross_monthly_income_cents": 100000}  # role omitted
    resp = api.create_party(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_support_order_amount_is_computed_not_client_supplied(api):
    """PRD §3.6: "The server computes the order's `monthly_amount_cents` and
    `support_term_months`; these are never client-supplied."

    Combined declared gross 400000+400000=800000 -> tier base 100000 (1 child),
    payor=respondent share 400000/800000 -> 50000; payor_time_pct 85/365=0.2329<0.40
    so no offset.

    Design: Corner/entities/support_order_amount_is_computed_input_ignored
    """
    ctx = FX.setup_default_pending(pet_gross=400000, res_gross=400000, children=1)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 280, 85)
    resp = api.create_support_order(
        F.support_order_payload(case["id"], "CHILD", res["id"], pet["id"], "TEMPORARY"), CLERK)
    data = validate_success(resp, 201)
    assert data["monthly_amount_cents"] == 50000


def test_list_cases_paginated_envelope(api):
    """PRD §2.3: "Every list response includes the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_cases_paginated_envelope
    """
    FX.register_schedule(state_code="CA")
    FX.create_case(register=False, caption="Case 1", marriage_months=60)
    FX.create_case(register=False, caption="Case 2", marriage_months=72)
    resp = api.list_cases(CLERK, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is False


def test_guideline_schedule_immutable_no_version_field(api):
    """PRD §2.4: "The `GuidelineSchedule` entity is configuration data and is immutable
    after creation; it therefore carries only `id` and `created_at` — it has neither an
    `updated_at` field nor a `version` field."

    Design: Corner/entities/guideline_schedule_immutable_no_version_field
    """
    gs = FX.register_schedule(state_code="CA", long_marriage_months=120)
    resp = api.get_guideline_schedule(gs["id"], CLERK)
    data = validate_success(resp, 200)
    assert_guideline_schedule(data)
    assert data["state_code"] == "CA"
    assert data["long_marriage_months"] == 120
    assert "updated_at" not in data
    assert "version" not in data


def test_defaults_applied_for_optional_schedule_pcts(api):
    """PRD §3.1: "`spousal_payor_pct` ... defaulting to 0.40 when omitted),
    `spousal_payee_offset_pct` (the payee's offset share, same open range, defaulting
    to 0.50), `shared_custody_threshold_pct` ... defaulting to 0.40), and
    `long_marriage_months` ... defaulting to 120)."

    Design: Corner/entities/defaults_applied_for_optional_schedule_pcts
    """
    payload = {"state_code": "NY", "basic_obligation_tiers": [
        {"min_combined_monthly_cents": 0, "max_combined_monthly_cents": 99999999,
         "base_cents_one_child": 100000, "marginal_pct_per_extra_child": 0.50}]}
    resp = api.create_guideline_schedule(payload, CLERK)
    data = validate_success(resp, 201)
    assert data["spousal_payor_pct"] == 0.40
    assert data["shared_custody_threshold_pct"] == 0.40
    assert data["long_marriage_months"] == 120


def test_serve_petition_drives_case_to_awaiting_response(api):
    """PRD §3.2: "Serving the petition drives the case from `FILED` to
    `AWAITING_RESPONSE` and increments the case `version`."

    Design: Corner/state_machines/serve_petition_drives_case_to_awaiting_response
    """
    case, pet, petition = FX.setup_filed_case_with_petitioner()
    assert case["version"] == 1
    FX.serve_pleading(petition["id"])
    data = validate_success(api.get_case(case["id"], CLERK), 200)
    assert data["status"] == "AWAITING_RESPONSE"
    assert data["version"] == 2


def test_dismiss_case_refunds_fee_and_recomputes_ledger(api):
    """PRD §3.8: "The case `status` moves to `DISMISSED`. The case's
    `net_fees_collected_cents` is set to 0, modeling the refund of the filing fee. And
    every `SupportOrder` on the case that is not already `VACATED` is moved to
    `VACATED`, after which the case's `active_support_total_cents` is recomputed to 0."

    Design: Corner/state_machines/dismiss_case_refunds_fee_and_vacates_support
    """
    case, pet, petition = FX.setup_awaiting_response()
    resp = api.dismiss_case(case["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "DISMISSED"
    assert data["net_fees_collected_cents"] == 0
    assert data["active_support_total_cents"] == 0


def test_case_default_blocked_when_answer_exists(api):
    """PRD §3.2: "if no answer pleading exists for the case, a clerk may default the
    respondent ... if an answer pleading does exist, the default attempt is rejected
    with `ERR_ANSWER_EXISTS`."

    Design: Corner/state_machines/case_default_blocked_when_answer_exists
    """
    case, pet, petition = FX.setup_awaiting_response()
    res = FX.add_respondent(case["id"])
    FX.file_pleading(case["id"], "ANSWER", res["id"])  # DRAFT answer exists
    resp = api.default_case(case["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_ANSWER_EXISTS.value)
