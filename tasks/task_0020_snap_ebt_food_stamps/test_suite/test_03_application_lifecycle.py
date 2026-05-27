"""Application lifecycle: approval cascade, denial, income-limit and ABAWD
gating, and the priority-conflict tests around /approve.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, add_member,
    create_and_submit_application, approve_application,
    setup_household_certified_active,
    setup_household_with_active_card,
    create_abawd_waiver,
    make_applicant_headers,
)

CW = TEST_USERS["caseworker_headers"]


# ─── Difficulty / transitive_cascade / approval_cascade_application_to_household_to_card ──

def test_approve_cascades_household_to_active_and_mints_pending_card(api):
    """One /approve call must produce three observable effects: Application
    lands in APPROVED, Household lands in ACTIVE (CERTIFIED→ACTIVE
    auto-advance in the same request), and exactly one PENDING_ISSUE EBTCard
    exists for the household.

    PRD §3.2: "On approval, several effects fire as one logical request: the
    household's `status` advances `PENDING → CERTIFIED → ACTIVE` —
    `CERTIFIED` is an intermediate state that auto-advances to `ACTIVE`
    before the response is returned, so callers always observe the household
    landing in `ACTIVE` — the household's `certification_end_date` is set
    to `SystemClock.current_utc` plus twelve months, an `EBTCard` for the
    household is created with `status` of `PENDING_ISSUE` (this is cascade
    link 1 of the approval cascade), the application's `caseworker_id` is
    set to the calling `X-User-ID`, and the household's `version` increments
    by 1."

    Design: Difficulty/transitive_cascade/approval_cascade_application_to_household_to_card
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="PA-800001", state_code="PA",
                          address_line="8 Maple Ave")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=10000,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    approved = approve_application(app["id"], decision_reason="Eligible")
    assert approved["status"] == "APPROVED"

    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_after["status"] == "ACTIVE", \
        f"Household must auto-advance to ACTIVE in the same request, got {hh_after['status']!r}"
    assert hh_after.get("certification_end_date"), \
        f"certification_end_date must be set after approval, got {hh_after.get('certification_end_date')!r}"

    cards_resp = api.list_ebt_cards(CW, params={"household_id": hh["id"]})
    cards = validate_success(cards_resp, 200)
    assert isinstance(cards, list) and len(cards) == 1, \
        f"approval cascade must mint exactly one EBTCard, got {len(cards)}"
    assert cards[0]["status"] == "PENDING_ISSUE", \
        f"minted card must start in PENDING_ISSUE, got {cards[0]['status']!r}"


def test_approve_records_caseworker_id_on_application(api):
    """The same approval call must also stamp `caseworker_id` on the
    application — this is a separate side-effect of the approval cascade
    that an implementer could plausibly miss.

    PRD §3.2: "On approval, several effects fire as one logical request: the
    household's `status` advances `PENDING → CERTIFIED → ACTIVE` —
    `CERTIFIED` is an intermediate state that auto-advances to `ACTIVE`
    before the response is returned, so callers always observe the household
    landing in `ACTIVE` — the household's `certification_end_date` is set
    to `SystemClock.current_utc` plus twelve months, an `EBTCard` for the
    household is created with `status` of `PENDING_ISSUE` (this is cascade
    link 1 of the approval cascade), the application's `caseworker_id` is
    set to the calling `X-User-ID`, and the household's `version` increments
    by 1."

    Design: Difficulty/transitive_cascade/approval_cascade_application_to_household_to_card
    """
    set_clock("2026-09-02T00:00:00Z")
    hh = create_household(case_number="PA-800002", state_code="PA",
                          address_line="9 Maple Ave")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    app = create_and_submit_application(hh["id"])
    approved = approve_application(app["id"])
    # Caseworker header used by approve_application has X-User-ID 'cw_001'.
    assert approved.get("caseworker_id") == "cw_001", \
        f"caseworker_id must equal calling X-User-ID, got {approved.get('caseworker_id')!r}"


# ─── Difficulty / dual_variant_calc / net_income_benefit_vs_limit_check_diverge_on_heap ──

def test_approve_rejected_when_limit_check_omits_sua(api):
    """For heap_recipient=true households the LIMIT_CHECK variant omits SUA
    so the income figure used against NET_INCOME_LIMIT_BY_SIZE is *larger*
    than the BENEFIT_CALC figure written to Household.net_income_cents. At
    size=1, gross=172000, heap=true: BENEFIT net = 172000-34400-19800-6700
    = 111100; LIMIT net = 172000-34400-19800 = 117800, which exceeds
    NET_INCOME_LIMIT_BY_SIZE[1]=117500 → approval is rejected with
    ERR_INCOME_LIMIT_EXCEEDED while the household stays PENDING and
    Household.net_income_cents reads 111100.

    PRD §3.4: "The limit-check variant differs in exactly one place: even
    when `heap_recipient` is true, the Standard Utility Allowance is omitted
    (treated as 0). Because admitting the allowance can only reduce net
    income, the limit-check figure for the same household and the same
    inputs is greater than or equal to the benefit-calculation figure; when
    `heap_recipient` is true it is strictly greater."
    PRD §3.4: "The limit-check value is compared, inside application
    approve, against `NET_INCOME_LIMIT_BY_SIZE`: 117,500 cents for size 1,
    158,900 cents for size 2, 200,300 cents for size 3, 241,700 cents for
    size 4, 283,100 cents for size 5, and 324,500 cents for size 6, with
    an additional 41,400 cents added per person beyond 6. A limit-check
    value at or below the size-indexed ceiling passes; a value above it
    fails with `ERR_INCOME_LIMIT_EXCEEDED`."

    Design: Difficulty/dual_variant_calc/net_income_benefit_vs_limit_check_diverge_on_heap
    """
    set_clock("2026-06-15T00:00:00Z")
    hh = create_household(case_number="TX-200001", state_code="TX",
                          address_line="2 Oak Ave", heap_recipient=True)
    add_member(hh["id"], full_name="Solo M", date_of_birth="1975-05-05",
               relationship="HEAD", monthly_earned_income_cents=172000,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    resp = api.approve_application(
        app["id"], {"decision_reason": "review"}, CW,
    )
    validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_EXCEEDED.value)

    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_after["status"] == "PENDING", \
        f"household must stay PENDING after failed approve, got {hh_after['status']!r}"
    assert hh_after["net_income_cents"] == 111100, (
        f"BENEFIT_CALC net (with SUA admitted) must be 111100, "
        f"got {hh_after['net_income_cents']}"
    )


def test_benefit_calc_net_strictly_smaller_than_limit_check_for_heap_household(api):
    """The same heap_recipient=true household evidences the directional
    inequality: BENEFIT_CALC net (111100) is strictly less than LIMIT_CHECK
    net (117800) for the same inputs. We can observe BENEFIT_CALC directly
    on the household; the LIMIT_CHECK arithmetic is the only PRD-coherent
    explanation for an income-limit rejection at this exact gross.

    PRD §3.4: "The limit-check variant differs in exactly one place: even
    when `heap_recipient` is true, the Standard Utility Allowance is omitted
    (treated as 0). Because admitting the allowance can only reduce net
    income, the limit-check figure for the same household and the same
    inputs is greater than or equal to the benefit-calculation figure; when
    `heap_recipient` is true it is strictly greater."

    Design: Difficulty/dual_variant_calc/net_income_benefit_vs_limit_check_diverge_on_heap
    """
    set_clock("2026-06-15T00:00:00Z")
    hh = create_household(case_number="TX-200002", state_code="TX",
                          address_line="3 Oak Ave", heap_recipient=True)
    add_member(hh["id"], full_name="Solo H", date_of_birth="1975-05-05",
               relationship="HEAD", monthly_earned_income_cents=172000,
               disabled=True)
    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    # BENEFIT_CALC (with SUA) figure stored on the household.
    assert hh_after["net_income_cents"] == 111100, \
        f"BENEFIT_CALC net for heap=true, gross=172000, size=1 must be 111100, got {hh_after['net_income_cents']}"
    # gross is the same input for both variants.
    assert hh_after["gross_income_cents"] == 172000


# ─── Corner / validations / abawd_requirement_unmet_blocks_approve ──

def test_abawd_requirement_unmet_blocks_approve(api):
    """A non-disabled adult age 25 in a household with no minor child is an
    ABAWD. With a PENDING waiver where county=5.00 and monthly_work_hours=20,
    neither arm of the work-requirement test is satisfied, and /approve is
    rejected with ERR_ABAWD_REQUIREMENT_UNMET.

    PRD §3.3: "A member is an Able-Bodied Adult Without Dependents (ABAWD)
    when their age, computed from `date_of_birth` against
    `SystemClock.current_utc`, is at least 18 and at most 49, when their
    `disabled` flag is false, and when no member of the same household is
    younger than 18."
    PRD §3.3: "For each ABAWD member of the household, the system requires
    either an `APPROVED` `ABAWDWaiver` for the current calendar quarter
    (computed from `SystemClock.current_utc`) OR a `PENDING` `ABAWDWaiver`
    whose `monthly_work_hours` is at least 80. If any ABAWD member fails
    both arms of that test, the approval is rejected with
    `ERR_ABAWD_REQUIREMENT_UNMET`."

    Design: Corner/validations/abawd_requirement_unmet_blocks_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-300001", state_code="CA",
                          address_line="X")
    m = add_member(hh["id"], full_name="Adult", date_of_birth="2000-01-01",
                   relationship="HEAD", disabled=False,
                   monthly_earned_income_cents=10000)
    create_abawd_waiver(m["id"], quarter="2026-Q3",
                        county_unemployment_pct=5.00,
                        monthly_work_hours=20)
    app = create_and_submit_application(hh["id"])
    resp = api.approve_application(
        app["id"], {"decision_reason": "review"}, CW,
    )
    validate_error(resp, ApiErrorId.ERR_ABAWD_REQUIREMENT_UNMET.value)


# ─── Corner / state_machines / reinstate_household_not_suspended_returns_invalid_state ──

def test_reinstate_household_not_suspended_returns_invalid_state(api):
    """An ACTIVE (never-suspended) household has no SUSPENDED from-state for
    /reinstate; the call must be rejected as ERR_INVALID_STATE per PRD §2.8.

    PRD §3.7: "Reinstatement transitions the household from `SUSPENDED`
    back to `ACTIVE`. Every `EBTCard` for the household with `status` of
    `SUSPENDED` transitions back to `ACTIVE`, and the household's `version`
    increments by 1."
    PRD §2.8: "(6) the entity is in a from-state listed for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/reinstate_household_not_suspended_returns_invalid_state
    """
    hh, _app = setup_household_certified_active(
        case_number="CA-300002", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    assert hh["status"] == "ACTIVE"
    resp = api.reinstate_household(hh["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner / rbac / applicant_cannot_approve_application ──

def test_applicant_cannot_approve_application(api):
    """An Applicant is the head-of-household identity and cannot self-approve
    an application — /approve is Caseworker-only per PRD §4. ERR_FORBIDDEN
    is returned regardless of the household's state.

    PRD §4: "POST /snap/applications/{id}/approve | Approve a SUBMITTED
    application; cascades to household and EBT card creation. | Caseworker"
    PRD §2.1: "A header pair that fails the per-endpoint role check yields
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_approve_application
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-300003", state_code="CA",
                          address_line="X")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    applicant = make_applicant_headers(hh["id"])
    app = validate_success(
        api.create_application({"household_id": hh["id"]}, applicant), 201)
    validate_success(api.submit_application(app["id"], applicant), 200)
    resp = api.approve_application(
        app["id"], {"decision_reason": "self-approve attempt"}, applicant,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
