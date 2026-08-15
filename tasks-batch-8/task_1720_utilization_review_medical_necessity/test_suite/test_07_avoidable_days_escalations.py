"""Avoidable-day tracking: per-day attribution variants, uniqueness, the
escalation tier thresholds, and the pinned credit evaluation order
(PRD §2.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_avoidable_day,
    apply_credit_payload,
    assert_avoidable_day,
    assert_escalation_case,
    create_avoidable_day_payload,
    discharge_case,
    get_case,
    list_avoidable_days,
    list_escalations,
    make_case,
    make_payer,
    make_physician,
    resolve_escalation_payload,
    setup_avoidable_days,
    setup_case,
    stagger_clock,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
DIRECTOR = TEST_USERS["ur_director_headers"]


class TestAttributionVariants:
    def test_first_cause_attributes_earliest_barrier(self, api):
        """PRD §3.7: "Attribution is computed per calendar day. For the set of a case's records sharing a `day_date` and not yet `OVERTURNED`, exactly one record owns the day: under the payer's `FIRST_CAUSE` method the owner is the earliest-created record, with ties broken by `barrier_code` in lexicographic order"
        PRD §3.7: "`open_avoidable_day_count` counts the distinct `day_date` values having at least one `OPEN` record."

        Design: Difficulty/dual_variant_calc/avoidable_attribution_first_cause_vs_dominant
        """
        payer = make_payer(name="Payer FC", plan_class="COMMERCIAL",
                           avoidable_attribution_method="FIRST_CAUSE")
        attending = make_physician()
        case = make_case(payer["id"], attending["id"], patient_mrn="MRN-FC")
        stagger_clock(0)
        first = add_avoidable_day(case["id"], "2026-08-04",
                                  "TRANSPORT_DELAY", 2)
        stagger_clock(1)
        second = add_avoidable_day(case["id"], "2026-08-04",
                                   "PLACEMENT_DELAY", 5)

        days = list_avoidable_days(case["id"])
        assert len(days) == 2
        for day in days:
            assert_avoidable_day(day)
        assert days[0]["id"] == first["id"], (
            "same-day records list in created_at ascending order")
        by_barrier = {d["barrier_code"]: d for d in days}
        assert by_barrier["TRANSPORT_DELAY"]["is_attributed"] is True, (
            "FIRST_CAUSE attributes the day to the earliest-created record")
        assert by_barrier["PLACEMENT_DELAY"]["is_attributed"] is False

        case_after = get_case(case["id"])
        assert case_after["open_avoidable_day_count"] == 1, (
            "two records on one calendar day count as a single open day")
        assert case_after["escalation_tier"] == 0
        assert list_escalations(case["id"]) == []

    def test_dominant_cause_attributes_heaviest_barrier(self, api):
        """PRD §3.7: "under `DOMINANT_CAUSE` the owner is the record with the highest `barrier_weight`, with ties broken by earliest creation and then `barrier_code` lexicographic."
        PRD §3.7: "identical inputs yield different owners across the two variants whenever the earliest barrier is not the heaviest."

        Design: Difficulty/dual_variant_calc/avoidable_attribution_first_cause_vs_dominant
        """
        payer = make_payer(name="Payer DC", plan_class="COMMERCIAL",
                           avoidable_attribution_method="DOMINANT_CAUSE")
        attending = make_physician()
        case = make_case(payer["id"], attending["id"], patient_mrn="MRN-DC")
        stagger_clock(0)
        add_avoidable_day(case["id"], "2026-08-04", "TRANSPORT_DELAY", 2)
        stagger_clock(1)
        add_avoidable_day(case["id"], "2026-08-04", "PLACEMENT_DELAY", 5)

        days = list_avoidable_days(case["id"])
        by_barrier = {d["barrier_code"]: d for d in days}
        assert by_barrier["TRANSPORT_DELAY"]["is_attributed"] is False
        assert by_barrier["PLACEMENT_DELAY"]["is_attributed"] is True, (
            "DOMINANT_CAUSE attributes the day to the heaviest barrier")

        case_after = get_case(case["id"])
        assert case_after["open_avoidable_day_count"] == 1
        assert case_after["escalation_tier"] == 0
        assert list_escalations(case["id"]) == []


class TestUniquenessAndClosure:
    def test_avoidable_day_duplicate_rejected(self, api):
        """PRD §3.7: "The triple of case, `day_date`, and `barrier_code` is unique — a duplicate is rejected with `ERR_AVOIDABLE_DAY_DUPLICATE`."

        Design: Corner/validations/avoidable_day_duplicate_rejected
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Commercial PPO",
                         patient_mrn="MRN-DUP")
        case_id = ctx["case"]["id"]
        add_avoidable_day(case_id, "2026-08-02", "PLACEMENT_DELAY", 3)

        resp = api.create_avoidable_day(
            case_id,
            create_avoidable_day_payload("2026-08-02", "PLACEMENT_DELAY", 4),
            CASE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_AVOIDABLE_DAY_DUPLICATE,
                       expected_status=409)

        other = validate_success(api.create_avoidable_day(
            case_id,
            create_avoidable_day_payload("2026-08-02", "TRANSPORT_DELAY", 1),
            CASE_MANAGER), expected_status=201)
        assert other["status"] == "OPEN", (
            "a different barrier on the same calendar day is not a duplicate")
        assert get_case(case_id)["open_avoidable_day_count"] == 1

    def test_avoidable_day_on_closed_case_rejected(self, api):
        """PRD §2.4: "Once a case is `CLOSED`, any attempt to create or mutate a child under it — a new review, a new authorization request, a concurrent review, an avoidable-day record — is rejected with `ERR_CASE_CLOSED`."

        Design: Corner/validations/avoidable_day_on_closed_case_rejected
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Commercial PPO",
                         patient_mrn="MRN-CL")
        discharge_case(ctx["case"]["id"], "2026-08-03T09:00:00Z")
        resp = api.create_avoidable_day(
            ctx["case"]["id"],
            create_avoidable_day_payload("2026-08-02", "PLACEMENT_DELAY", 3),
            CASE_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSED, expected_status=409)


class TestEscalationTiers:
    def test_escalation_tier_boundary_at_two_days(self, api):
        """PRD §3.7: "`escalation_tier` maps that raw count through three thresholds: at least 6 open days yields tier 3, at least 4 yields tier 2, at least 2 yields tier 1, and fewer than 2 yields tier 0."
        PRD §3.7: "When a create pushes the raw tier from 0 to at least 1 and no escalation case is currently `OPEN` or `ACKNOWLEDGED` for the case, the system creates an **EscalationCase** in `OPEN` with its `tier` set to the raw tier and `trigger_open_day_count` snapshotting the raw count at that moment"

        Design: Corner/complexity_layers/escalation_tier_boundary_at_two_days
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Commercial PPO",
                         patient_mrn="MRN-TIER")
        case_id = ctx["case"]["id"]
        add_avoidable_day(case_id, "2026-08-02", "PLACEMENT_DELAY", 3)
        assert list_escalations(case_id) == [], (
            "a single open day stays below the tier-1 threshold")
        assert get_case(case_id)["escalation_tier"] == 0

        add_avoidable_day(case_id, "2026-08-03", "TRANSPORT_DELAY", 2)
        escalations = list_escalations(case_id)
        assert len(escalations) == 1, (
            "the second distinct open day crosses the tier-1 threshold")
        escalation = escalations[0]
        assert_escalation_case(escalation)
        assert escalation["status"] == "OPEN"
        assert escalation["tier"] == 1
        assert escalation["trigger_open_day_count"] == 2

        case_after = get_case(case_id)
        assert case_after["open_avoidable_day_count"] == 2
        assert case_after["escalation_tier"] == 1

    def test_escalation_credit_raw_tier_gates_first_credit(self, api):
        """PRD §3.7: "eligibility for a credit is evaluated against the **raw** tier — the tier computed from the raw open-day count before any credits — and only a raw tier of exactly 3 is eligible; once applied, the net count is the raw count minus cumulative `director_credit_days`, floored at zero, and `effective_tier` is the tier of that net count through the same thresholds; eligibility is not re-checked after crediting."
        PRD §3.7: "Applying a credit appends `ESCALATION_CREDIT_APPLIED` and leaves the stored raw `tier` untouched."

        Design: Difficulty/combinatorial_formula/escalation_credit_evaluation_order
        """
        ctx = setup_avoidable_days(6, patient_mrn="MRN-ESC")
        escalation = list_escalations(ctx["case"]["id"])[0]
        assert escalation["tier"] == 3

        credited = validate_success(api.apply_escalation_credit(
            escalation["id"], apply_credit_payload(2), DIRECTOR))
        assert credited["tier"] == 3, "the stored raw tier is sticky"
        assert credited["director_credit_days"] == 2
        assert credited["effective_tier"] == 2, (
            "net count 6 - 2 = 4 maps to tier 2")

    def test_escalation_second_credit_still_eligible(self, api):
        """PRD §3.7: "eligibility for a credit is evaluated against the **raw** tier — the tier computed from the raw open-day count before any credits — and only a raw tier of exactly 3 is eligible; once applied, the net count is the raw count minus cumulative `director_credit_days`, floored at zero, and `effective_tier` is the tier of that net count through the same thresholds; eligibility is not re-checked after crediting."

        Design: Difficulty/combinatorial_formula/escalation_credit_evaluation_order
        """
        ctx = setup_avoidable_days(6, patient_mrn="MRN-ESC2")
        escalation = list_escalations(ctx["case"]["id"])[0]

        validate_success(api.apply_escalation_credit(
            escalation["id"], apply_credit_payload(2), DIRECTOR))
        # The second credit remains eligible even though effective_tier is
        # already 2, because eligibility reads the raw pre-credit tier (3).
        credited = validate_success(api.apply_escalation_credit(
            escalation["id"], apply_credit_payload(2), DIRECTOR))
        assert credited["director_credit_days"] == 4
        assert credited["effective_tier"] == 1, "net count 6 - 4 = 2 maps to tier 1"
        assert credited["tier"] == 3
        assert get_case(ctx["case"]["id"])["open_avoidable_day_count"] == 6, (
            "credits never rewrite the underlying day records")

    def test_escalation_acknowledge_resolve_chain(self, api):
        """PRD §3.7: "Escalations are worked by the `CaseManager`: acknowledging moves `OPEN` → `ACKNOWLEDGED` (`ESCALATION_ACKNOWLEDGED`), and resolving — from either `OPEN` or `ACKNOWLEDGED` — sets the `resolution_note` and closes the escalation `RESOLVED` (`ESCALATION_RESOLVED`)."

        Design: Corner/state_machines/escalation_acknowledge_resolve_chain
        """
        ctx = setup_avoidable_days(2, patient_mrn="MRN-ESCH")
        escalation = list_escalations(ctx["case"]["id"])[0]
        assert escalation["status"] == "OPEN"

        acknowledged = validate_success(api.acknowledge_escalation(
            escalation["id"], {}, CASE_MANAGER))
        assert acknowledged["status"] == "ACKNOWLEDGED"

        resolved = validate_success(api.resolve_escalation(
            escalation["id"],
            resolve_escalation_payload("SNF bed secured for 2026-08-04"),
            CASE_MANAGER))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "SNF bed secured for 2026-08-04"
