"""Term lifecycle, meal plan catalogue, and enrollment assignment rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_term,
    create_and_publish_plan,
    create_holder,
    create_plan,
    create_term,
    create_zone,
    enroll_holder,
    get_success_data,
    open_term,
    publish_plan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DINING = TEST_USERS["dining_manager_headers"]
BURSAR = TEST_USERS["bursar_headers"]
SECURITY = TEST_USERS["security_officer_headers"]


class TestEnrollmentCreationStates:
    def test_enrollment_in_scheduled_term_starts_assigned(self, api):
        """PRD §3.4: "The enrollment's initial status depends on the term:
        `ASSIGNED` while the term is `SCHEDULED`, or `ACTIVE` immediately when the
        term is already `OPEN`."
        PRD §3.4: "The `charge_cents` of an enrollment remains null until it is
        `ACTIVE`, and its `credit_cents` starts at 0."

        Design: Corner/entities/enrollment_in_scheduled_term_starts_assigned
        """
        set_clock("2026-08-20T09:00:00Z")
        term = create_term(term_code="T-ASG")
        plan = create_and_publish_plan(plan_code="P-ASG")
        holder = create_holder(university_id="U90009", full_name="Ira Assigned",
                               email="ira@x.edu")

        enrollment = enroll_holder(holder["id"], plan["id"], term["id"])
        assert enrollment["status"] == "ASSIGNED"
        assert enrollment["charge_cents"] is None
        assert enrollment["credit_cents"] == 0

        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": holder["id"],
                                       "term_id": term["id"]}))
        assert accounts == []

    def test_enrollment_overlap_same_term_rejected(self, api):
        """PRD §3.4: "A holder may have at most one enrollment in `ASSIGNED` or
        `ACTIVE` per term; a second live enrollment in the same term is rejected
        with `ERR_ENROLLMENT_OVERLAP`."

        Design: Corner/entities/enrollment_overlap_same_term_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-EO")
        plan = create_and_publish_plan(plan_code="P-EO",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U90006", full_name="Finn Overlap",
                               email="finn@x.edu")
        enroll_holder(holder["id"], plan["id"], term["id"])

        resp = api.create_enrollment(holder["id"],
                                     {"plan_id": plan["id"],
                                      "term_id": term["id"]}, DINING)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_OVERLAP)


class TestTermLifecycleGuards:
    def test_term_open_before_start_rejected(self, api):
        """PRD §3.4: "Opening a term is a `DiningServicesManager` action gated on
        the logical clock reading at or after the term's `start_date` (otherwise
        `ERR_TERM_NOT_YET_STARTED`)."

        Design: Corner/state_machines/term_open_before_start_rejected
        """
        set_clock("2026-08-20T09:00:00Z")
        term = create_term(term_code="T-EARLY")
        resp = api.open_term(term["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_YET_STARTED)
        still = get_success_data(api.get_term(term["id"], DINING))
        assert still["status"] == "SCHEDULED"
        assert still["current_week_index"] == 0

    def test_term_close_before_end_rejected(self, api):
        """PRD §3.7: "Closing a term is a `DiningServicesManager` action gated on
        the logical clock reading at or after the term's `end_date` (otherwise
        `ERR_TERM_NOT_ENDED`)."

        Design: Corner/state_machines/term_close_before_end_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-NC")
        open_term(term["id"])
        resp = api.close_term(term["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_ENDED)
        still = get_success_data(api.get_term(term["id"], DINING))
        assert still["status"] == "OPEN"

    def test_advance_week_beyond_total_weeks_rejected(self, api):
        """PRD §3.4: "Advancing requires `current_week_index` strictly below
        `total_weeks` (otherwise `ERR_TERM_WEEKS_EXHAUSTED`)"

        Design: Corner/state_machines/advance_week_beyond_total_weeks_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-1W", end_date="2026-08-30T23:59:59Z",
                           add_drop_deadline="2026-08-26T23:59:59Z",
                           total_weeks=1)
        open_term(term["id"])
        resp = api.advance_term_week(term["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_TERM_WEEKS_EXHAUSTED)
        still = get_success_data(api.get_term(term["id"], DINING))
        assert still["current_week_index"] == 1


class TestPlanCatalogue:
    def test_plan_retire_blocked_while_enrollments_live(self, api):
        """PRD §3.3: "a published plan can be retired to `RETIRED` only while no
        enrollment in `ASSIGNED` or `ACTIVE` references it — otherwise the retire
        is rejected with `ERR_PLAN_IN_USE`."

        Design: Corner/state_machines/plan_retire_blocked_while_enrollments_live
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-RIU")
        plan = create_and_publish_plan(plan_code="P-RIU",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U90017", full_name="Rey Inuse",
                               email="rey@x.edu")
        enroll_holder(holder["id"], plan["id"], term["id"])

        resp = api.retire_meal_plan(plan["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_PLAN_IN_USE)
        still = get_success_data(api.get_meal_plan(plan["id"], DINING))
        assert still["status"] == "PUBLISHED"

    def test_config_entities_reject_duplicate_natural_keys(self, api):
        """PRD §3.3: "creating a **term** with a unique `term_code` (duplicates
        rejected with `ERR_DUPLICATE_NATURAL_KEY`)"
        PRD §3.8: "A **door zone** is created with a unique `zone_code`
        (`ERR_DUPLICATE_NATURAL_KEY` on collision)"
        PRD §3.9: "`BursarOffice` onboards off-campus merchants with a unique
        `merchant_code` (`ERR_DUPLICATE_NATURAL_KEY` on collision)"

        Design: Corner/entities/config_entities_reject_duplicate_natural_keys
        """
        set_clock("2026-08-25T09:00:00Z")
        create_term(term_code="T-DUP")
        create_zone(zone_code="Z-DUP")
        from test_helpers import create_merchant
        create_merchant(merchant_code="M-DUP")

        dup_term = api.create_term(
            {"term_code": "T-DUP", "name": "T2",
             "start_date": "2026-08-24T00:00:00Z",
             "end_date": "2026-12-13T23:59:59Z",
             "add_drop_deadline": "2026-09-20T23:59:59Z",
             "total_weeks": 16, "proration_mode": "DAILY"}, DINING)
        validate_error(dup_term, ApiErrorId.ERR_DUPLICATE_NATURAL_KEY)

        dup_zone = api.create_door_zone(
            {"zone_code": "Z-DUP", "building": "B2", "security_level": "ELEVATED",
             "access_windows": [{"day_of_week": "TUE", "start_minute": 480,
                                 "end_minute": 1080}]}, SECURITY)
        validate_error(dup_zone, ApiErrorId.ERR_DUPLICATE_NATURAL_KEY)

        dup_merchant = api.create_merchant(
            {"merchant_code": "M-DUP", "legal_name": "Dup2", "category": "COFFEE",
             "commission_bps": 200, "contact_email": "d2@x.com"}, BURSAR)
        validate_error(dup_merchant, ApiErrorId.ERR_DUPLICATE_NATURAL_KEY)


class TestEnrollmentEligibility:
    def test_commuter_blocked_from_resident_plan(self, api):
        """PRD §3.4: "a plan with `requires_on_campus_housing` true admits only
        holders whose `housing_status` is `ON_CAMPUS`
        (`ERR_HOUSING_INELIGIBLE_FOR_PLAN`)"

        Design: Corner/validations/commuter_blocked_from_resident_plan
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-ELI")
        plan = create_and_publish_plan(
            plan_code="P-ELI", requires_on_campus_housing=True,
            eligible_holder_types=["STUDENT_COMMUTER", "STUDENT_RESIDENT"])
        open_term(term["id"])
        holder = create_holder(university_id="U92008", full_name="Rob Commuter",
                               email="rob@x.edu", housing_status="COMMUTER")

        resp = api.create_enrollment(holder["id"],
                                     {"plan_id": plan["id"],
                                      "term_id": term["id"]}, DINING)
        validate_error(resp, ApiErrorId.ERR_HOUSING_INELIGIBLE_FOR_PLAN)

    def test_holder_type_not_in_plan_eligible_list(self, api):
        """PRD §3.4: "the holder's `holder_type` must appear in the plan's
        `eligible_holder_types` (`ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN`)"

        Design: Corner/validations/holder_type_not_in_plan_eligible_list
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-ELT")
        plan = create_and_publish_plan(plan_code="P-ELT",
                                       eligible_holder_types=["STUDENT_RESIDENT"])
        open_term(term["id"])
        holder = create_holder(university_id="U92009", full_name="Sue Staff",
                               email="sue@x.edu", holder_type="STAFF",
                               housing_status="ON_CAMPUS")

        resp = api.create_enrollment(holder["id"],
                                     {"plan_id": plan["id"],
                                      "term_id": term["id"]}, DINING)
        validate_error(resp, ApiErrorId.ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN)

    def test_draft_plan_cannot_be_enrolled(self, api):
        """PRD §3.4: "the plan must be `PUBLISHED` (`ERR_PLAN_NOT_PUBLISHED`)"

        Design: Corner/validations/draft_plan_cannot_be_enrolled
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-DPF")
        plan = create_plan(plan_code="P-DPF",
                           eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U92010", full_name="Tad Draft",
                               email="tad@x.edu")

        resp = api.create_enrollment(holder["id"],
                                     {"plan_id": plan["id"],
                                      "term_id": term["id"]}, DINING)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_PUBLISHED)


class TestEnrollmentCancelCredit:
    def test_enrollment_cancel_proration_credit(self, api):
        """PRD §3.4: "The credit is the enrollment's `charge_cents` minus the
        earned amount, floored at zero, and is recorded as `credit_cents` and
        posted as a `PRORATION_CREDIT` to the enrollment-linked `DINING_DOLLARS`
        account when it is positive, recomputing the account's `balance_cents`."
        PRD §3.4: "Cancelling an `ASSIGNED` enrollment posts nothing, because
        nothing was charged"

        Design: Corner/calculations/enrollment_cancel_proration_credit
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-CXL")
        term2 = create_term(term_code="T-CXL2", start_date="2026-08-31T00:00:00Z",
                            total_weeks=15)
        plan = create_and_publish_plan(plan_code="P-CXL",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        ha = create_holder(university_id="U91004", full_name="Xia Cancel",
                           email="xia@x.edu")
        hb = create_holder(university_id="U91005", full_name="Yus Assigned",
                           email="yus@x.edu")
        ea = enroll_holder(ha["id"], plan["id"], term["id"])
        eb = enroll_holder(hb["id"], plan["id"], term2["id"])
        assert eb["status"] == "ASSIGNED"
        from test_helpers import advance_term_week
        advance_term_week(term["id"])
        advance_term_week(term["id"])  # now week 3; ea ACTIVE since week 1

        cancelled = validate_success(api.cancel_enrollment(ea["id"], DINING), 200)
        assert cancelled["status"] == "CANCELLED"
        # WEEKLY: consumed = 3 - 1 = 2; earned = round_half_up(90000*2/16) = 11250
        assert cancelled["credit_cents"] == 78750

        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ha["id"],
                                       "term_id": term["id"]}))
        assert len(accounts) == 1
        assert accounts[0]["balance_cents"] == 88750  # 10000 grant + 78750 credit

        credits, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": accounts[0]["id"],
                                             "entry_type": "PRORATION_CREDIT"}))
        assert len(credits) == 1
        assert credits[0]["amount_cents"] == 78750

        cancelled_b = validate_success(api.cancel_enrollment(eb["id"], DINING), 200)
        assert cancelled_b["status"] == "CANCELLED"
        assert cancelled_b["credit_cents"] == 0
        accounts_b, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": hb["id"],
                                       "term_id": term2["id"]}))
        assert accounts_b == []


class TestEnrollmentPricingVariants:
    def test_weekly_vs_daily_activation_charge_diverges(self, api):
        """PRD §3.4 (WEEKLY): "The `charge_cents` is the plan's `price_cents`
        multiplied by the remaining weeks and divided by `total_weeks`, rounded
        half-up to whole cents" — remaining weeks "is the term's `total_weeks`
        minus the current `current_week_index` plus 1 — the current week always
        counts as fully remaining."
        PRD §3.4 (DAILY): "the days consumed are the calendar days elapsed since
        `start_date`, never below zero; and the remaining days are the total minus
        the consumed. Charge and grant are the plan's `price_cents` and
        `dining_dollar_allocation_cents` respectively multiplied by the remaining
        days and divided by the total days, each rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/enrollment_pricing_weekly_vs_daily_terms
        """
        ids = _setup_dual_terms(api)
        enr_w, enr_d = _enroll_in_both(api, ids)
        # WEEKLY: 90000 * 14/16 = 78750; DAILY: 90000 * 96/112 -> 77143
        assert enr_w["charge_cents"] == 78750
        assert enr_d["charge_cents"] == 77143
        assert enr_w["charge_cents"] != enr_d["charge_cents"]
        assert enr_w["status"] == "ACTIVE" and enr_d["status"] == "ACTIVE"
        assert enr_w["enrolled_week_index"] == 3
        assert enr_d["enrolled_week_index"] == 3

    def test_weekly_vs_daily_activation_grant_diverges(self, api):
        """PRD §3.4: "posts the grant as an `ALLOCATION_GRANT` ledger entry to the
        holder's `DINING_DOLLARS` account for that term, auto-creating the account
        `OPEN` when none exists and recomputing its `balance_cents`."
        PRD §3.4 (DAILY): "A mid-week activation under `DAILY` therefore charges
        less than the same activation under `WEEKLY`."

        Design: Difficulty/dual_variant_calc/enrollment_pricing_weekly_vs_daily_terms
        """
        ids = _setup_dual_terms(api)
        _enroll_in_both(api, ids)
        acct_w, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ids["h_id"],
                                       "term_id": ids["tw_id"]}))
        acct_d, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ids["h_id"],
                                       "term_id": ids["td_id"]}))
        assert len(acct_w) == 1 and len(acct_d) == 1
        # WEEKLY grant: 10000 * 14/16 = 8750; DAILY grant: 10000 * 96/112 -> 8571
        assert acct_w[0]["balance_cents"] == 8750
        assert acct_d[0]["balance_cents"] == 8571


class TestEnrollmentTermStateDependency:
    def test_enrollment_into_closed_term_rejected(self, api):
        """PRD §3.4: "The enrollment's initial status depends on the term:
        `ASSIGNED` while the term is `SCHEDULED`, or `ACTIVE` immediately when the
        term is already `OPEN`."
        PRD §2.10: "**Cross-entity referenced state** — the states of related
        resources permit the action: term open where required
        (`ERR_TERM_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_term_open_or_scheduled
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="FALLXS")
        plan = create_and_publish_plan(plan_code="COMM5-XS",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        set_clock("2026-12-14T00:00:00Z")
        close_term(term["id"])
        holder = create_holder(university_id="U8001", full_name="Pat Late",
                               email="pat@x.edu")

        resp = api.create_enrollment(holder["id"],
                                     {"plan_id": plan["id"],
                                      "term_id": term["id"]}, DINING)
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_OPEN)

    def test_enrollment_into_closed_term_persists_nothing(self, api):
        """PRD §3.4: "A `DiningServicesManager` assigns a meal plan to a holder by
        posting the target `plan_id` and `term_id`; the holder is taken from the
        creation path, and the body-referenced plan and term must exist."
        PRD §2.10: "**Cross-entity referenced state** — the states of related
        resources permit the action: term open where required
        (`ERR_TERM_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_term_open_or_scheduled
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="FALLXS")
        plan = create_and_publish_plan(plan_code="COMM5-XS",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        set_clock("2026-12-14T00:00:00Z")
        close_term(term["id"])
        holder = create_holder(university_id="U8001", full_name="Pat Late",
                               email="pat@x.edu")

        api.create_enrollment(holder["id"],
                              {"plan_id": plan["id"], "term_id": term["id"]},
                              DINING)
        enrollments, _ = validate_paginated(
            api.list_enrollments(DINING, {"holder_id": holder["id"],
                                          "term_id": term["id"]}))
        assert enrollments == []


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _setup_dual_terms(api):
    """FALLW (WEEKLY) and FALLD (DAILY), both OPEN at week 3; plan COMM5
    published; clock 2026-09-09T10:00:00Z; one commuter holder."""
    from test_helpers import advance_term_week
    set_clock("2026-08-24T09:00:00Z")
    tw = create_term(term_code="FALLW", name="Fall W", proration_mode="WEEKLY")
    td = create_term(term_code="FALLD", name="Fall D", proration_mode="DAILY")
    plan = create_and_publish_plan(plan_code="COMM5")
    open_term(tw["id"])
    open_term(td["id"])
    advance_term_week(tw["id"])
    advance_term_week(tw["id"])
    advance_term_week(td["id"])
    advance_term_week(td["id"])
    set_clock("2026-09-09T10:00:00Z")
    holder = create_holder(university_id="U1001", full_name="Ana Commuter",
                           email="ana@x.edu", holder_type="STUDENT_COMMUTER",
                           housing_status="COMMUTER")
    return {"tw_id": tw["id"], "td_id": td["id"], "plan_id": plan["id"],
            "h_id": holder["id"]}


def _enroll_in_both(api, ids):
    enr_w = enroll_holder(ids["h_id"], ids["plan_id"], ids["tw_id"])
    enr_d = enroll_holder(ids["h_id"], ids["plan_id"], ids["td_id"])
    return enr_w, enr_d
