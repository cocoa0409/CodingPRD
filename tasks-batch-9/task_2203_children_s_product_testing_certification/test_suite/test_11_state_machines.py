"""Nine machines: their entry nodes, their legal hops, their guards and their exits."""

from test_helpers import (
    ApiErrorId,
    assert_distribution_ledger,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "limit_comparator": "AT_OR_BELOW",
    "periodic_interval_months": 12,
    "base_method_fee_cents": 18700,
}


class TestInitialStatesOfEveryMachine:
    """Every machine read at its entry node, before any transition is attempted."""

    def test_registration_rows_start_at_their_earliest_state(self, api):
        """PRD 3.3: "At registration the product's `certification_state` is `DRAFT`, its
        `compliance_posture` is `UNSCOPED`, and its `required_rule_ids` is the empty array
        — rule derivation deliberately does not run at registration, only at scoping." PRD
        3.3: "A new part's `reliance_status` is `PENDING` and its `last_material_change_at`
        is null." PRD 3.2: "A new scope begins in `accreditation_state` `ACCREDITED` with a
        null `suspension_reason`."

        Design: Corner/state_machines/corner_state_machines_initial_states_of_all_nine_machines_on_creation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(
            api, rule_specs=[dict(LEAD_RULE)], category=dict(FLAT_CATEGORY), submit=False
        )
        assert env["product"]["certification_state"] == "DRAFT"
        assert env["product"]["compliance_posture"] == "UNSCOPED"

        assert env["parts"][0]["reliance_status"] == "PENDING"
        assert env["parts"][0]["last_material_change_at"] is None

        assert env["accreditations"][0]["accreditation_state"] == "ACCREDITED"
        assert env["accreditations"][0]["suspension_reason"] is None

    def test_a_new_plan_and_a_booked_order_wait_at_their_first_node(self, api):
        """PRD 3.5: "A new plan begins in `plan_state` `DRAFT` with `resample_trigger`
        `NONE`, with `activated_at`, `last_verified_at` and `periodic_due_at` all null."
        PRD 3.6: "On creation the order's `order_state` is `SCHEDULED`, its
        `ordered_by_user_id` is the acting `X-User-ID`, `is_retest` is false and
        `retest_case_id` is null; `measured_value`, `result`, `reported_at` and
        `reported_by_user_id` are all null."

        Design: Corner/state_machines/corner_state_machines_initial_states_of_all_nine_machines_on_creation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(
            api, rule_specs=[dict(LEAD_RULE)], category=dict(FLAT_CATEGORY)
        )
        plan = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
        assert plan["plan_state"] == "DRAFT"
        assert plan["resample_trigger"] == "NONE"
        assert plan["activated_at"] is None
        assert plan["periodic_due_at"] is None

        fx.activate_plan(api, plan["id"])
        order = fx.book_order(
            api,
            env["product"]["id"],
            plan["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=1,
        )
        assert order["order_state"] == "SCHEDULED"
        assert order["order_state"] != "IN_TESTING"
        assert order["is_retest"] is False
        assert order["result"] is None

    def test_a_certificate_enters_on_two_axes_at_once_and_a_batch_enters_held(self, api):
        """PRD 3.7: "The draft is created with `issuance_status` `DRAFT` and
        `accompaniment_status` `NOT_FURNISHED`, with `issued_by_user_id` and `issued_at`
        both null." PRD 3.8: "A new batch begins in `distribution_state` `HELD` with
        `released_at` null and `release_rescind_count` at 0, and its `quantity` is added to
        the product's `units_held`."

        Design: Corner/state_machines/corner_state_machines_initial_states_of_all_nine_machines_on_creation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(
            api,
            rule_specs=[dict(LEAD_RULE)],
            category=dict(FLAT_CATEGORY),
            measured_value=40,
        )
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        assert certificate["issuance_status"] == "DRAFT"
        assert certificate["accompaniment_status"] == "NOT_FURNISHED"
        assert certificate["issued_at"] is None
        assert certificate["issued_by_user_id"] is None

        batch = fx.create_batch(
            api,
            product["id"],
            certificate["id"],
            batch_code="INITST-000801",
            produced_on="2026-08-04T00:00:00Z",
            quantity=300,
        )
        assert batch["distribution_state"] == "HELD"
        assert batch["released_at"] is None
        assert batch["release_rescind_count"] == 0

    def test_a_supplier_certificate_starts_submitted_and_a_case_is_born_open(self, api):
        """PRD 3.4: "On acceptance the system copies the part's `supplier_id` onto the
        certificate, sets `reliance_state` to `SUBMITTED`, leaves
        `reliance_documentation_ref` and `reliance_recorded_by_user_id` null, and increments
        the supplier's `certificates_issued_count` by 1." PRD 3.9: "A new case begins in
        `case_state` `OPEN`, with `retest_round_count` 0, `active_retest_order_id` null,
        `scope_variant` `BATCH_SCOPED`, `scope_units` 0, `corrective_action_ref` null,
        `corrective_action_revision` 0 and `closed_by_user_id` null."

        Design: Corner/state_machines/corner_state_machines_initial_states_of_all_nine_machines_on_creation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        reliance = fx.scoped_product_env(
            api,
            evidence_path="COMPONENT_RELIANCE",
            rule_specs=[dict(LEAD_RULE, component_reliance_allowed=True)],
            category=dict(FLAT_CATEGORY),
            supplier={"reliance_agreement_state": "ON_FILE"},
        )
        part_certificate = fx.submit_part_certificate(
            api,
            reliance["parts"][0]["id"],
            reliance["supplier"]["id"],
            reliance["laboratory"]["id"],
            reliance["rules"][0]["id"],
            measured_value=40,
        )
        assert part_certificate["reliance_state"] == "SUBMITTED"

        tested = fx.booking_env(
            api,
            rule_specs=[dict(LEAD_RULE)],
            category=dict(FLAT_CATEGORY),
            plan_overrides={"plan_type": "INITIAL"},
        )
        fx.fail_an_order(api, tested, measured_value=250, sample_count=1)
        case = fx.sole_case_for_product(api, tested["product"]["id"])
        assert case["case_state"] == "OPEN"
        assert case["retest_round_count"] == 0
        assert case["active_retest_order_id"] is None
        assert case["scope_variant"] == "BATCH_SCOPED"
        assert case["scope_units"] == 0
        assert case["closed_by_user_id"] is None


def _drafted_product_env(api):
    """A registered single-rule product with one part, still in DRAFT."""
    fx.set_clock(api, STARTUP_CLOCK)
    return fx.scoped_product_env(
        api, rule_specs=[dict(LEAD_RULE)], category=dict(FLAT_CATEGORY), submit=False
    )


class TestValidTransitionsWalkTheProductToCertified:
    """The forward happy path, asserted at every intermediate node."""

    def test_submission_scopes_and_forks_in_a_single_request(self, api):
        """PRD 3.4: "Both moves are automatic — no separate operator action drives them —
        and each increments the product's `version` by 1 in its own right, so a submission
        that scopes and then forks advances `version` twice." PRD 3.3: "Because a freshly
        scoped product has no evidence at all, its gap score is non-zero and its posture
        moves from `UNSCOPED` to `RESTRICTED`."

        Design: Corner/state_machines/corner_state_machines_valid_transition_walks_the_full_product_lifecycle_to_certified
        """
        env = _drafted_product_env(api)
        # Read the product fresh: PRD 3.3 bumps its version when the bill of
        # materials was built, so the registration response is a stale snapshot.
        before = fx.get_product(api, env["product"]["id"])

        scoped = fx.submit_for_certification(api, before["id"], "FULL_PRODUCT_TEST")
        assert scoped["certification_state"] == "FULL_TEST_PROGRAM"
        assert scoped["certification_state"] != "SCOPED"
        assert scoped["required_rule_ids"] == [env["rules"][0]["id"]]
        assert scoped["risk_weighted_gap_score"] > 0
        assert scoped["compliance_posture"] == "RESTRICTED"
        assert scoped["version"] == before["version"] + 2

    def test_a_passing_report_carries_the_product_to_evidence_complete(self, api):
        """PRD 3.6: "The product's `risk_weighted_gap_score` and `compliance_posture` are
        recomputed, and when the product sits in `FULL_TEST_PROGRAM` and the recomputed
        score is 0, the product advances `FULL_TEST_PROGRAM → EVIDENCE_COMPLETE` with
        `compliance_posture` set to `CLEARED` — the join point at which both evidence
        branches converge, each having had its own branch-specific evidence kind counted."

        Design: Corner/state_machines/corner_state_machines_valid_transition_walks_the_full_product_lifecycle_to_certified
        """
        env = _drafted_product_env(api)
        fx.submit_for_certification(api, env["product"]["id"], "FULL_PRODUCT_TEST")
        plan = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
        fx.activate_plan(api, plan["id"])
        scoped = fx.get_product(api, env["product"]["id"])

        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            plan["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            measured_value=40,
        )
        evidenced = fx.get_product(api, env["product"]["id"])
        assert evidenced["certification_state"] == "EVIDENCE_COMPLETE"
        assert evidenced["risk_weighted_gap_score"] == 0
        assert evidenced["compliance_posture"] == "CLEARED"
        assert evidenced["version"] > scoped["version"]

    def test_issuance_is_the_last_hop_and_stamps_the_clock(self, api):
        """PRD 3.7: "On success, `issued_by_user_id` is set to the acting `X-User-ID` and
        `issued_at` to the logical clock instant; the predecessor named by
        `supersedes_certificate_id`, when non-null, moves `ISSUED → SUPERSEDED`; and the
        product advances `EVIDENCE_COMPLETE → CERTIFIED` with `compliance_posture`
        `CLEARED`."

        Design: Corner/state_machines/corner_state_machines_valid_transition_walks_the_full_product_lifecycle_to_certified
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(
            api,
            rule_specs=[dict(LEAD_RULE)],
            category=dict(FLAT_CATEGORY),
            measured_value=40,
        )
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        drafted_product = fx.get_product(api, product["id"])

        issued = fx.issue_certificate(api, certificate["id"])
        assert issued["issuance_status"] == "ISSUED"
        assert issued["issued_at"] == STARTUP_CLOCK
        assert issued["issued_by_user_id"] == OFFICER_USER_ID

        certified = fx.get_product(api, product["id"])
        assert certified["certification_state"] == "CERTIFIED"
        assert certified["compliance_posture"] == "CLEARED"
        assert certified["version"] == drafted_product["version"] + 1


def _five_machines_env(api):
    """An active plan, a scheduled order, a draft certificate, a held batch, an open case."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.evidence_complete_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        measured_value=40,
    )
    product = fx.get_product(api, env["product"]["id"])
    env["certificate"] = fx.draft_certificate(
        api, product["id"], product["version"], manufacture_date_month="2026-08"
    )
    env["batch"] = fx.create_batch(
        api,
        product["id"],
        env["certificate"]["id"],
        batch_code="BADHOP-000901",
        produced_on="2026-08-04T00:00:00Z",
        quantity=300,
    )
    env["scheduled_order"] = fx.book_order(
        api,
        product["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=1,
    )
    fx.fail_an_order(api, env, measured_value=250, sample_count=1)
    env["case"] = fx.sole_case_for_product(api, product["id"])
    return env


class TestInvalidTransitionsAreRefusedWithTheOwnersStateError:
    """Five machines, five out-of-order hops, five distinct state codes."""

    def test_a_report_before_the_start_and_a_second_activation_are_refused(self, api):
        """PRD 2.11: "Test order state — `SCHEDULED` for taking into testing, `IN_TESTING`
        for filing a report, and either `SCHEDULED` or `IN_TESTING` for cancellation →
        `ERR_ORDER_STATE_INVALID` (409)." PRD 3.5: "Activation is accepted from `DRAFT`,
        moving the plan `DRAFT → ACTIVE`, and from `RESAMPLE_DUE`, moving it `RESAMPLE_DUE →
        ACTIVE` after resampling has been arranged; any other `plan_state` is refused with
        `ERR_PLAN_STATE_INVALID`."

        Design: Corner/state_machines/corner_state_machines_invalid_transitions_rejected_with_the_entity_state_error
        """
        env = _five_machines_env(api)
        order = env["scheduled_order"]
        lab_id = env["laboratory"]["id"]

        validate_error(
            api.report_result(
                order["id"],
                {"measured_value": 40},
                headers=make_laboratory_user_headers(lab_id),
            ),
            ApiErrorId.ORDER_STATE_INVALID.value,
            409,
        )
        untouched = fx.get_order(api, order["id"])
        assert untouched["order_state"] == "SCHEDULED"
        assert untouched["measured_value"] is None
        assert untouched["version"] == order["version"]

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["plan_state"] == "ACTIVE"
        validate_error(
            api.activate_sampling_plan(plan["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )
        assert fx.get_plan(api, plan["id"])["version"] == plan["version"]

    def test_rescinding_a_never_released_batch_and_furnishing_a_draft_are_refused(self, api):
        """PRD 2.11: "Production batch state — `HELD` for release, `RELEASED` for
        rescinding a release, and either `HELD` or `STOP_DISTRIBUTION` for tracking-label
        edits (a `DESTROYED` batch accepts no label edit) → `ERR_BATCH_STATE_INVALID`
        (409)." PRD 3.7: "This is the single cross-axis coupling in the whole machine:
        furnishing requires the issuance axis to have reached `ISSUED`, and attempting it on
        a draft is refused with `ERR_CERTIFICATE_STATE_INVALID`."

        Design: Corner/state_machines/corner_state_machines_invalid_transitions_rejected_with_the_entity_state_error
        """
        env = _five_machines_env(api)
        batch = fx.get_batch(api, env["batch"]["id"])
        assert batch["distribution_state"] == "HELD"

        validate_error(
            api.rescind_release(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        after_batch = fx.get_batch(api, batch["id"])
        assert after_batch["release_rescind_count"] == 0
        assert after_batch["version"] == batch["version"]

        certificate = fx.get_certificate(api, env["certificate"]["id"])
        assert certificate["issuance_status"] == "DRAFT"
        validate_error(
            api.furnish_certificate(certificate["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        after_certificate = fx.get_certificate(api, certificate["id"])
        assert after_certificate["accompaniment_status"] == "NOT_FURNISHED"
        assert after_certificate["version"] == certificate["version"]

    def test_closing_a_case_that_is_still_open_is_refused(self, api):
        """PRD 3.9: "Each of the four case operations demands a specific `case_state` and
        refuses any other with `ERR_CASE_STATE_INVALID`: `OPEN` to issue the
        stop-distribution instruction, either `STOP_DISTRIBUTION_ISSUED` or `RETEST_FAILED`
        to order a retest, either `RETEST_PASSED` or `CORRECTIVE_ACTION_APPROVED` to file a
        corrective action, and `CORRECTIVE_ACTION_APPROVED` to close."

        Design: Corner/state_machines/corner_state_machines_invalid_transitions_rejected_with_the_entity_state_error
        """
        env = _five_machines_env(api)
        case = env["case"]
        assert case["case_state"] == "OPEN"

        validate_error(
            api.close_case(case["id"], headers=OFFICER_HEADERS),
            ApiErrorId.CASE_STATE_INVALID.value,
            409,
        )
        after = fx.get_case(api, case["id"])
        assert after["case_state"] == "OPEN"
        assert after["closed_by_user_id"] is None
        assert after["version"] == case["version"]


def _issuable_env(api):
    """An EVIDENCE_COMPLETE, CLEARED product ready to carry a certificate."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.evidence_complete_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        measured_value=40,
    )
    env["product"] = fx.get_product(api, env["product"]["id"])
    assert env["product"]["certification_state"] == "EVIDENCE_COMPLETE"
    assert env["product"]["compliance_posture"] == "CLEARED"
    return env


class TestIssuancePreconditionsBeyondTheCertificatesOwnAxis:
    """A perfectly legal DRAFT is still refused by the substantive gates."""

    def test_a_blank_content_slot_costs_the_certificate_its_issuance(self, api):
        """PRD 3.7: "The seven slots are: `certifier_legal_name` is non-empty after
        trimming; `certifier_contact_email` contains an at-sign; `manufacture_place` is
        non-empty after trimming; `manufacture_date_month` matches the four-digit-year,
        hyphen, two-digit-month-between-01-and-12 pattern; `testing_place` is non-empty after
        trimming; `cited_rule_ids` is non-empty and equals the product's `required_rule_ids`
        when compared as sets; and `cited_evidence_count` is at least as large as the number
        of entries in `cited_rule_ids`." PRD 3.7: "All seven satisfied yields exactly 100;
        six of seven yields 85."

        Design: Corner/state_machines/corner_state_machines_precondition_enforcement_on_certificate_issuance
        """
        env = _issuable_env(api)
        product = env["product"]

        incomplete = fx.draft_certificate(
            api,
            product["id"],
            product["version"],
            manufacture_place="   ",
            manufacture_date_month="2026-08",
        )
        assert incomplete["content_completeness_pct"] == 85
        assert incomplete["issuance_status"] == "DRAFT"

        validate_error(
            api.issue_certificate(incomplete["id"], headers=OFFICER_HEADERS),
            ApiErrorId.CERTIFICATE_CONTENT_INCOMPLETE.value,
            422,
        )
        refused = fx.get_certificate(api, incomplete["id"])
        assert refused["issuance_status"] == "DRAFT"
        assert refused["issued_at"] is None

    def test_a_restricted_posture_blocks_a_complete_certificate(self, api):
        """PRD 3.7: "Issuing a certificate moves it `DRAFT → ISSUED` on the issuance axis
        and requires five things: `issuance_status` is `DRAFT`; `content_completeness_pct`
        equals 100, or the request is refused with `ERR_CERTIFICATE_CONTENT_INCOMPLETE`; the
        product's `compliance_posture` is `CLEARED`, or the request is refused with
        `ERR_PRODUCT_POSTURE_NOT_CLEARED`; the product's `certification_state` is
        `EVIDENCE_COMPLETE`; and the acting `X-User-ID` differs from the
        `ordered_by_user_id` of every test order cited as evidence by this certificate, or
        the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/corner_state_machines_precondition_enforcement_on_certificate_issuance
        """
        env = _issuable_env(api)
        product = env["product"]
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        assert certificate["content_completeness_pct"] == 100

        fx.record_material_change(
            api, product["id"], change_kind="MATERIAL_SUBSTITUTION"
        )
        restricted = fx.get_product(api, product["id"])
        assert restricted["compliance_posture"] == "RESTRICTED"
        assert restricted["certification_state"] == "EVIDENCE_COMPLETE"

        validate_error(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )
        refused = fx.get_certificate(api, certificate["id"])
        assert refused["issuance_status"] == "DRAFT"
        assert refused["issued_at"] is None

    def test_a_complete_certificate_on_a_cleared_product_issues(self, api):
        """PRD 3.7: "**Content completeness** is then computed as a percentage over exactly
        seven required-content slots, and the certificate's `content_completeness_pct` is the
        count of satisfied slots multiplied by 100, divided by 7, with the result floored to
        a whole number."

        Design: Corner/state_machines/corner_state_machines_precondition_enforcement_on_certificate_issuance
        """
        env = _issuable_env(api)
        product = env["product"]
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        assert certificate["content_completeness_pct"] == 100

        issued = validate_success(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS), 200
        )
        assert issued["issuance_status"] == "ISSUED"
        assert issued["issued_at"] == STARTUP_CLOCK


def _draft_plan_env(api):
    """A 2000-unit product on the testing branch carrying one DRAFT INITIAL plan."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.scoped_product_env(
        api,
        rule_specs=[dict(LEAD_RULE, periodic_interval_months=12)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
    )
    env["plan"] = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
    return env


class TestPlanActivationRunsItsWholeSideEffectSet:
    """Four writes from one request, none of them supplied by the client."""

    def test_activation_stamps_the_clock_and_computes_the_periodic_due_instant(self, api):
        """PRD 3.5: "Activation stamps both `activated_at` and `last_verified_at` with the
        logical clock instant, recomputes `periodic_due_at`, resets `resample_trigger` to
        `NONE` on the resampling re-entry edge, and increments the plan's `version` by 1."
        PRD 3.5: "Otherwise, add that number of calendar months to the plan's
        `last_verified_at`, clamping the day of month to the last day of the target month
        where the source day does not exist there, and preserving the time of day exactly."

        Design: Corner/state_machines/corner_state_machines_side_effect_execution_on_plan_activation_stamps_and_sizes
        """
        env = _draft_plan_env(api)
        draft = env["plan"]
        assert draft["periodic_due_at"] is None
        assert draft["version"] == 1

        activated = fx.activate_plan(api, draft["id"])
        assert activated["plan_state"] == "ACTIVE"
        assert activated["activated_at"] == STARTUP_CLOCK
        assert activated["last_verified_at"] == STARTUP_CLOCK
        assert activated["periodic_due_at"] == "2027-08-01T00:00:00Z"
        assert activated["version"] == 2

    def test_the_sizing_figure_is_settled_at_creation_and_survives_activation(self, api):
        """PRD 3.5: "At creation, `units_committed` is 0 and `units_available` equals
        `units_authorized`; whenever `units_authorized` is recomputed, `units_available` is
        refreshed as `units_authorized` minus `units_committed`."

        Design: Corner/state_machines/corner_state_machines_side_effect_execution_on_plan_activation_stamps_and_sizes
        """
        env = _draft_plan_env(api)
        draft = env["plan"]
        assert draft["units_authorized"] == 4
        assert draft["units_committed"] == 0
        assert draft["units_available"] == 4

        activated = fx.activate_plan(api, draft["id"])
        assert activated["units_authorized"] == 4
        assert activated["units_committed"] == 0
        assert activated["units_available"] == 4

    def test_a_plan_of_the_other_type_is_left_alone_by_the_activation(self, api):
        """PRD 3.5: "It also supersedes competition: any other plan on the same product with
        the same `plan_type` whose `plan_state` is `DRAFT`, `ACTIVE` or `RESAMPLE_DUE` moves
        to `SUPERSEDED` with its own `version` incremented by 1."

        Design: Corner/state_machines/corner_state_machines_side_effect_execution_on_plan_activation_stamps_and_sizes
        """
        env = _draft_plan_env(api)
        periodic = fx.create_plan(
            api, env["product"]["id"], plan_type="PERIODIC", baseline_units_produced=5000
        )
        assert periodic["plan_state"] == "DRAFT"

        fx.activate_plan(api, env["plan"]["id"])
        untouched = fx.get_plan(api, periodic["id"])
        assert untouched["plan_state"] == "DRAFT"
        assert untouched["version"] == periodic["version"]
        assert untouched["activated_at"] is None


def _certified_no_batches_env(api):
    """A certified product with a furnished certificate and no goods recorded yet."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.certified_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
    )
    fx.furnish_certificate(api, env["certificate"]["id"])
    return env


class TestTerminalStatesRefuseEveryFurtherWrite:
    """ARCHIVED locks the aggregate; a finished order cannot be walked back."""

    def test_archiving_locks_every_later_write_but_no_read(self, api):
        """PRD 3.3: "On success the product moves `CERTIFIED → ARCHIVED`, its
        `compliance_posture` becomes `UNSCOPED`, every sampling plan of the product whose
        `plan_state` is `DRAFT`, `ACTIVE` or `RESAMPLE_DUE` moves to `SUPERSEDED`, and the
        product's `version` increments by 1." PRD 3.3: "`ARCHIVED` is terminal, and every
        subsequent write against the product or its children raises `ERR_PRODUCT_ARCHIVED`."

        Design: Corner/state_machines/corner_state_machines_terminal_state_lockdown_archived_product_and_finished_orders
        """
        env = _certified_no_batches_env(api)
        product_id = env["product"]["id"]

        archived = validate_success(
            api.archive_product(product_id, headers=ADMIN_HEADERS), 200
        )
        assert archived["certification_state"] == "ARCHIVED"
        assert archived["compliance_posture"] == "UNSCOPED"
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "SUPERSEDED"

        validate_error(
            api.create_sampling_plan(
                product_id, {"plan_type": "INITIAL"}, headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )
        validate_error(
            api.create_production_batch(
                product_id,
                factories.batch_payload(
                    env["certificate"]["id"],
                    batch_code="LOCKED-001001",
                    produced_on="2026-08-04T00:00:00Z",
                ),
                headers=MANAGER_HEADERS,
            ),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )
        validate_error(
            api.archive_product(product_id, headers=ADMIN_HEADERS),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )

        still_readable = fx.get_product(api, product_id)
        assert still_readable["certification_state"] == "ARCHIVED"

    def test_a_finished_order_cannot_be_walked_back_to_free_its_units(self, api):
        """PRD 2.11: "Test order state — `SCHEDULED` for taking into testing, `IN_TESTING`
        for filing a report, and either `SCHEDULED` or `IN_TESTING` for cancellation →
        `ERR_ORDER_STATE_INVALID` (409). Applies to those three operations."

        Design: Corner/state_machines/corner_state_machines_terminal_state_lockdown_archived_product_and_finished_orders
        """
        env = _certified_no_batches_env(api)
        lab_id = env["laboratory"]["id"]
        passed_order = env["orders"][0]
        assert passed_order["order_state"] == "REPORTED_PASS"

        spare = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            lab_id,
            env["rules"][0]["id"],
            sample_count=1,
        )
        cancelled = validate_success(
            api.cancel_test_order(spare["id"], headers=COORDINATOR_HEADERS), 200
        )
        assert cancelled["order_state"] == "CANCELLED"

        validate_error(
            api.start_testing(spare["id"], headers=make_laboratory_user_headers(lab_id)),
            ApiErrorId.ORDER_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.cancel_test_order(passed_order["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.ORDER_STATE_INVALID.value,
            409,
        )
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 1


LATER_CLOCK = "2026-08-10T00:00:00Z"


def _released_batch_env(api):
    """A furnished certificate over one released batch of 300, then the clock moves on."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.distributed_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
        batch_specs=[
            {
                "batch_code": "REPEAT-001101",
                "produced_on": "2026-08-04T00:00:00Z",
                "quantity": 300,
            }
        ],
    )
    fx.set_clock(api, LATER_CLOCK)
    return env


class TestRepeatedActionRequestsDoNotDoubleApply:
    """The second call is refused by the state guard and runs no side effect."""

    def test_a_repeated_issue_and_furnish_neither_restamp_nor_advance(self, api):
        """PRD 2.11: "Certificate axis state — `issuance_status` `DRAFT` for issuing and for
        voiding, `issuance_status` `ISSUED` for furnishing, `accompaniment_status`
        `FURNISHED` for recalling accompaniment, and on batch release the referenced
        certificate must be `ISSUED` on the issuance axis **and** `FURNISHED` on the
        accompaniment axis simultaneously → `ERR_CERTIFICATE_STATE_INVALID` (409)." PRD 3.7:
        "On success, `issued_by_user_id` is set to the acting `X-User-ID` and `issued_at` to
        the logical clock instant; the predecessor named by `supersedes_certificate_id`, when
        non-null, moves `ISSUED → SUPERSEDED`; and the product advances `EVIDENCE_COMPLETE →
        CERTIFIED` with `compliance_posture` `CLEARED`." PRD 2.11: "When issuing a
        certificate, product state comes first, then the certificate's own axis state" — the
        first issuance carried the product to `CERTIFIED`, so the replayed issuance is
        decided at rank 9 with `ERR_PRODUCT_STATE_INVALID`.

        Design: Corner/state_machines/corner_state_machines_idempotency_repeated_action_requests_do_not_double_apply
        """
        env = _released_batch_env(api)
        before = fx.get_certificate(api, env["certificate"]["id"])
        assert before["issued_at"] == STARTUP_CLOCK
        assert before["accompaniment_status"] == "FURNISHED"

        validate_error(
            api.issue_certificate(before["id"], headers=OFFICER_HEADERS),
            ApiErrorId.PRODUCT_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.furnish_certificate(before["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        after = fx.get_certificate(api, before["id"])
        assert after["issued_at"] == STARTUP_CLOCK
        assert after["issued_at"] != LATER_CLOCK
        assert after["accompaniment_status"] == "FURNISHED"
        assert after["version"] == before["version"]

    def test_a_repeated_release_does_not_double_count_the_ledger(self, api):
        """PRD 3.8: "On success the batch moves `HELD → RELEASED`, `released_at` is stamped
        with the logical clock, and the batch's `quantity` moves from the product's
        `units_held` to its `units_released`; both the batch's and the product's `version`
        increment by 1."

        Design: Corner/state_machines/corner_state_machines_idempotency_repeated_action_requests_do_not_double_apply
        """
        env = _released_batch_env(api)
        batch = fx.get_batch(api, env["batches"][0]["id"])
        assert batch["distribution_state"] == "RELEASED"
        assert batch["released_at"] == STARTUP_CLOCK

        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        after = fx.get_batch(api, batch["id"])
        assert after["released_at"] == STARTUP_CLOCK
        assert after["version"] == batch["version"]

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_released"] == 300
        assert summary["units_held"] == 0
        assert_distribution_ledger(summary)


def _looped_batch_env(api):
    """One 300-unit batch that has already traversed the release loop twice."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.distributed_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
        release=False,
        batch_specs=[
            {
                "batch_code": "CYCLIC-001201",
                "produced_on": "2026-08-12T00:00:00Z",
                "quantity": 300,
            }
        ],
    )
    batch_id = env["batches"][0]["id"]
    for _ in range(2):
        fx.release_batch(api, batch_id)
        fx.rescind_release(api, batch_id)
    env["batch"] = fx.get_batch(api, batch_id)
    return env


def _open_a_case_and_stop_the_batch(api, env):
    """Fail a product-level order, then stop the batch the failure implicates."""
    fx.fail_an_order(api, env, measured_value=250, sample_count=1)
    case = fx.sole_case_for_product(api, env["product"]["id"])
    return fx.issue_stop_distribution(api, case["id"], "BATCH_SCOPED")


def _run_one_retest_round(api, env, case_id, measured_value):
    """Order a retest round, take it into testing and report the given measurement."""
    case = fx.order_retest(
        api, case_id, env["plan"]["id"], env["laboratory"]["id"], sample_count=1
    )
    order_id = case["active_retest_order_id"]
    fx.start_order(api, order_id, env["laboratory"]["id"])
    fx.report(api, order_id, env["laboratory"]["id"], measured_value)
    return fx.get_case(api, case_id)


class TestTheBatchLoopReentersHeldAndExitsOnlyThroughDestroyed:
    """Two different loops re-enter HELD; the single exit is terminal."""

    def test_the_release_loop_may_be_walked_twice_and_the_counter_only_rises(self, api):
        """PRD 3.8: "Rescinding a release moves the batch `RELEASED → HELD`, moves the same
        `quantity` from the product's `units_released` back to `units_held`, clears
        `released_at` to null, increments `release_rescind_count` by 1, and increments both
        the batch's and the product's `version` by 1."

        Design: Corner/state_machines/corner_state_machines_cyclic_batch_hold_release_stop_loop_terminates_in_destroyed
        """
        env = _looped_batch_env(api)
        batch = env["batch"]
        assert batch["distribution_state"] == "HELD"
        assert batch["release_rescind_count"] == 2
        assert batch["released_at"] is None

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_held"] == 300
        assert summary["units_released"] == 0
        assert_distribution_ledger(summary)

    def test_the_stop_loop_returns_the_batch_to_held_from_another_predecessor(self, api):
        """PRD 3.8: "A stopped batch returns `STOP_DISTRIBUTION → HELD` when its case is
        closed, provided its `tracking_label_compliant` is true, moving its `quantity` back
        from `units_stopped` to `units_held`; a batch may be stopped and reinstated
        repeatedly over its life."

        Design: Corner/state_machines/corner_state_machines_cyclic_batch_hold_release_stop_loop_terminates_in_destroyed
        """
        env = _looped_batch_env(api)
        batch_id = env["batch"]["id"]

        case = _open_a_case_and_stop_the_batch(api, env)
        assert case["case_state"] == "STOP_DISTRIBUTION_ISSUED"
        stopped = fx.get_batch(api, batch_id)
        assert stopped["distribution_state"] == "STOP_DISTRIBUTION"
        stopped_summary = fx.get_summary(api, env["product"]["id"])
        assert stopped_summary["units_stopped"] == 300
        assert stopped_summary["units_held"] == 0
        assert_distribution_ledger(stopped_summary)

        _run_one_retest_round(api, env, case["id"], 40)
        current = fx.get_case(api, case["id"])
        assert current["case_state"] == "RETEST_PASSED"
        fx.file_corrective_action(api, case["id"], current["version"])
        closed = fx.close_case(api, case["id"])
        assert closed["case_state"] == "CLOSED"

        reinstated = fx.get_batch(api, batch_id)
        assert reinstated["distribution_state"] == "HELD"
        assert reinstated["release_rescind_count"] == 2
        closed_summary = fx.get_summary(api, env["product"]["id"])
        assert closed_summary["units_held"] == 300
        assert closed_summary["units_stopped"] == 0
        assert_distribution_ledger(closed_summary)

        # The batch is back on the node where label edits are legal.
        relabelled = validate_success(
            api.update_tracking_label(
                batch_id, factories.tracking_label_payload(), headers=MANAGER_HEADERS
            ),
            200,
        )
        assert relabelled["tracking_label_compliant"] is True

    def test_escalation_destroys_the_batch_and_locks_the_loop(self, api):
        """PRD 3.9: "Instead the case's `scope_variant` is forced to `LOT_TRACEBACK`
        regardless of what it previously held, `scope_units` is recomputed under that widest
        variant, every production batch of the product in `HELD`, `RELEASED` or
        `STOP_DISTRIBUTION` moves to `DESTROYED`, the product's `units_held`,
        `units_released`, `units_stopped` and `units_destroyed` are all recomputed, and both
        the case's and the product's `version` increment by 1." PRD 3.8: "A `DESTROYED` batch
        accepts no label edit and the attempt is refused with `ERR_BATCH_STATE_INVALID`."

        Design: Corner/state_machines/corner_state_machines_cyclic_batch_hold_release_stop_loop_terminates_in_destroyed
        """
        env = _looped_batch_env(api)
        batch_id = env["batch"]["id"]
        case = _open_a_case_and_stop_the_batch(api, env)

        for _ in range(3):
            case = _run_one_retest_round(api, env, case["id"], 250)
            assert case["case_state"] == "RETEST_FAILED"
        assert case["retest_round_count"] == 3

        escalated = fx.order_retest(
            api, case["id"], env["plan"]["id"], env["laboratory"]["id"], sample_count=1
        )
        assert escalated["case_state"] == "ESCALATED_RECALL"
        assert escalated["scope_variant"] == "LOT_TRACEBACK"

        destroyed = fx.get_batch(api, batch_id)
        assert destroyed["distribution_state"] == "DESTROYED"
        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_destroyed"] == 300
        assert summary["units_stopped"] == 0
        assert_distribution_ledger(summary)

        validate_error(
            api.rescind_release(batch_id, headers=MANAGER_HEADERS),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.update_tracking_label(
                batch_id, factories.tracking_label_payload(), headers=MANAGER_HEADERS
            ),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        assert fx.get_batch(api, batch_id)["distribution_state"] == "DESTROYED"


def _forked_pair_env(api):
    """Two products of one category taken through the fork on opposite branches."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.scoped_product_env(
        api,
        rule_specs=[dict(LEAD_RULE, component_reliance_allowed=True)],
        category=dict(FLAT_CATEGORY),
        supplier={"reliance_agreement_state": "ON_FILE"},
        submit=False,
    )
    beta = fx.create_product(api, env["category"]["id"], model_name="Beta stroller frame")
    beta_part = fx.add_part(api, beta["id"], env["supplier"]["id"], part_name="Beta grip")

    env["alpha"] = fx.submit_for_certification(
        api, env["product"]["id"], "COMPONENT_RELIANCE"
    )
    env["alpha_part"] = env["parts"][0]
    env["beta"] = fx.submit_for_certification(api, beta["id"], "FULL_PRODUCT_TEST")
    env["beta_part"] = beta_part
    return env


class TestTheEvidencePathGuardSelectsOneOfTwoSuccessors:
    """One source state, one trigger, two successors chosen by the declared path."""

    def test_the_same_trigger_lands_the_two_products_on_different_branches(self, api):
        """PRD 3.4: "On the **component reliance branch**, taken when `evidence_path` is
        `COMPONENT_RELIANCE`, the product advances `SCOPED → EVIDENCE_RELIANCE`." PRD 3.4:
        "On the **full product testing branch**, taken when `evidence_path` is
        `FULL_PRODUCT_TEST`, the product advances `SCOPED → FULL_TEST_PROGRAM`."

        Design: Corner/state_machines/corner_state_machines_guarded_fork_evidence_path_selects_one_of_two_successor_states
        """
        env = _forked_pair_env(api)
        assert env["alpha"]["certification_state"] == "EVIDENCE_RELIANCE"
        assert env["beta"]["certification_state"] == "FULL_TEST_PROGRAM"
        assert env["alpha"]["evidence_path"] == "COMPONENT_RELIANCE"
        assert env["beta"]["evidence_path"] == "FULL_PRODUCT_TEST"
        # The fork is driven by the declared path, not by rule identification.
        assert env["alpha"]["required_rule_ids"] == env["beta"]["required_rule_ids"]

    def test_each_branch_leaves_its_parts_where_that_branch_wants_them(self, api):
        """PRD 3.4: "The branch's distinguishing side effect is that every component part of
        the product whose `reliance_status` is `PENDING` becomes `VALID`, making the parts
        eligible to carry reliance; no laboratory fee is billed anywhere on this branch, since
        the evidence arrives from the suppliers." PRD 3.4: "Its distinguishing side effect is
        precisely the opposite: every component part is left at `reliance_status` `PENDING`, so
        no component certificate can ever be counted as evidence for this product and
        finished-product test orders are the only admissible evidence."

        Design: Corner/state_machines/corner_state_machines_guarded_fork_evidence_path_selects_one_of_two_successor_states
        """
        env = _forked_pair_env(api)
        assert fx.get_part(api, env["alpha_part"]["id"])["reliance_status"] == "VALID"
        assert fx.get_part(api, env["beta_part"]["id"])["reliance_status"] == "PENDING"

    def test_the_unchosen_branch_s_operation_is_refused_afterwards(self, api):
        """PRD 3.4: "and the product's `evidence_path` is `COMPONENT_RELIANCE`, or the
        request is refused with `ERR_EVIDENCE_PATH_MISMATCH`."

        Design: Corner/state_machines/corner_state_machines_guarded_fork_evidence_path_selects_one_of_two_successor_states
        """
        env = _forked_pair_env(api)
        certificate = fx.submit_part_certificate(
            api,
            env["beta_part"]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            measured_value=40,
        )
        assert certificate["reliance_state"] == "SUBMITTED"

        validate_error(
            api.record_reliance_documentation(
                certificate["id"],
                {
                    "reliance_decision": "RELY",
                    "reliance_documentation_ref": "RELIANCE-PKG-BETA",
                },
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.EVIDENCE_PATH_MISMATCH.value,
            422,
        )
        assert fx.get_part(api, env["beta_part"]["id"])["reliance_status"] == "PENDING"
        assert (
            fx.get_part_certificate(api, certificate["id"])["reliance_state"] == "SUBMITTED"
        )


FIRST_DUE_INSTANT = "2027-08-01T00:00:00Z"


def _resample_due_env(api):
    """An ACTIVE plan driven into resampling by the periodic deadline alone."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE, periodic_interval_months=12)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["periodic_due_at"] == FIRST_DUE_INSTANT

    fx.set_clock(api, FIRST_DUE_INSTANT)
    env["plan"] = fx.periodic_review(api, env["plan"]["id"])
    env["product"] = fx.get_product(api, env["product"]["id"])
    assert env["plan"]["plan_state"] == "RESAMPLE_DUE"
    assert env["plan"]["resample_trigger"] == "PERIODIC_INTERVAL"
    return env


class TestOnePassingReportBubblesUpToPlanAndProduct:
    """No request names the plan or the product, yet both are written."""

    def test_the_plan_climbs_out_of_resampling_without_being_addressed(self, api):
        """PRD 3.5: "When a test order booked under a `RESAMPLE_DUE` plan reaches
        `REPORTED_PASS`, the plan moves `RESAMPLE_DUE → ACTIVE`, its `resample_trigger`
        returns to `NONE`, `last_verified_at` is stamped with the logical clock and
        `periodic_due_at` recomputed, and its `version` increments by 1."

        Design: Corner/state_machines/corner_state_machines_side_effect_bubbles_up_from_report_to_plan_and_product
        """
        env = _resample_due_env(api)
        before = env["plan"]

        reported = fx.run_order_to_pass(
            api,
            env["product"]["id"],
            before["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            measured_value=40,
            sample_count=1,
            window_start="2027-08-02T00:00:00Z",
            window_end="2027-08-03T00:00:00Z",
        )
        assert reported["order_state"] == "REPORTED_PASS"
        assert reported["result"] == "PASS"

        after = fx.get_plan(api, before["id"])
        assert after["plan_state"] == "ACTIVE"
        assert after["resample_trigger"] == "NONE"
        assert after["last_verified_at"] == FIRST_DUE_INSTANT
        assert after["periodic_due_at"] == "2028-08-01T00:00:00Z"
        assert after["version"] > before["version"]

    def test_the_product_is_recomputed_without_being_addressed(self, api):
        """PRD 3.6: "The product's `risk_weighted_gap_score` and `compliance_posture` are
        recomputed, and when the product sits in `FULL_TEST_PROGRAM` and the recomputed score
        is 0, the product advances `FULL_TEST_PROGRAM → EVIDENCE_COMPLETE` with
        `compliance_posture` set to `CLEARED` — the join point at which both evidence branches
        converge, each having had its own branch-specific evidence kind counted."

        Design: Corner/state_machines/corner_state_machines_side_effect_bubbles_up_from_report_to_plan_and_product
        """
        env = _resample_due_env(api)
        before = env["product"]
        assert before["compliance_posture"] == "RESTRICTED"

        fx.run_order_to_pass(
            api,
            before["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            measured_value=40,
            sample_count=1,
            window_start="2027-08-02T00:00:00Z",
            window_end="2027-08-03T00:00:00Z",
        )
        after = fx.get_product(api, before["id"])
        assert after["risk_weighted_gap_score"] == 0
        assert after["compliance_posture"] == "CLEARED"
        assert after["certification_state"] == "EVIDENCE_COMPLETE"
        assert after["version"] > before["version"]


def _two_initial_plans_env(api):
    """One product carrying an older ACTIVE plan and a newer plan of the same type."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        plan_overrides={"plan_type": "INITIAL"},
    )
    env["first_plan"] = env["plan"]
    second = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
    env["second_plan"] = fx.activate_plan(api, second["id"])
    return env


class TestActivatingANewerPlanRetiresTheOlderOne:
    """The write targets the new row and the old row changes state as a consequence."""

    def test_the_older_plan_of_the_same_type_is_superseded(self, api):
        """PRD 3.5: "It also supersedes competition: any other plan on the same product with
        the same `plan_type` whose `plan_state` is `DRAFT`, `ACTIVE` or `RESAMPLE_DUE` moves
        to `SUPERSEDED` with its own `version` incremented by 1."

        Design: Corner/state_machines/corner_state_machines_supersession_side_effects_retire_the_previous_plan_and_certificate
        """
        env = _two_initial_plans_env(api)
        assert env["second_plan"]["plan_state"] == "ACTIVE"

        retired = fx.get_plan(api, env["first_plan"]["id"])
        assert retired["plan_state"] == "SUPERSEDED"
        assert retired["version"] == env["first_plan"]["version"] + 1

        rows, meta = validate_paginated(
            api.list_sampling_plans(
                params={"product_id": env["product"]["id"], "plan_state": "ACTIVE"},
                headers=COORDINATOR_HEADERS,
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == env["second_plan"]["id"]

    def test_a_superseded_plan_refuses_the_periodic_review(self, api):
        """PRD 2.11: "Sampling plan state — `DRAFT` for activation, either `ACTIVE` or
        `RESAMPLE_DUE` for periodic review, and either `ACTIVE` or `RESAMPLE_DUE` to accept a
        new test order → `ERR_PLAN_STATE_INVALID` (409). Applies to plan activation, periodic
        review, and test order booking." PRD 3.5: "`LAPSED` and `SUPERSEDED` are both
        terminal."

        Design: Corner/state_machines/corner_state_machines_supersession_side_effects_retire_the_previous_plan_and_certificate
        """
        env = _two_initial_plans_env(api)
        retired = fx.get_plan(api, env["first_plan"]["id"])

        validate_error(
            api.periodic_review(retired["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )
        after = fx.get_plan(api, retired["id"])
        assert after["plan_state"] == "SUPERSEDED"
        assert after["version"] == retired["version"]


def _two_accreditation_env(api):
    """One laboratory holding an in-coverage scope and an elapsed scope for one method."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        plan_overrides={"plan_type": "INITIAL"},
        accreditation_overrides=[
            {"valid_from": "2026-01-01T00:00:00Z", "valid_through": "2027-01-01T00:00:00Z"}
        ],
    )
    env["current_scope"] = env["accreditations"][0]
    env["elapsed_scope"] = fx.accredit(
        api,
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        valid_from="2026-01-01T00:00:00Z",
        valid_through="2026-06-01T00:00:00Z",
    )
    return env


class TestSuspendingAScopeForksOnReasonAndClock:
    """One endpoint, two identically shaped rows, two different terminal states."""

    def test_the_reason_and_the_clock_together_pick_the_destination(self, api):
        """PRD 3.2: "Ordinarily the scope moves `ACCREDITED → SUSPENDED` with the submitted
        reason stored." PRD 3.2: "There is one variant: when the submitted reason is the
        literal `COVERAGE_ELAPSED` and the logical clock is already strictly past the scope's
        `valid_through`, the scope moves `ACCREDITED → EXPIRED` instead."

        Design: Corner/state_machines/corner_state_machines_accreditation_suspend_endpoint_branches_to_suspended_or_expired
        """
        env = _two_accreditation_env(api)

        suspended = fx.suspend_accreditation(
            api, env["current_scope"]["id"], "WITNESS_AUDIT_FINDING"
        )
        assert suspended["accreditation_state"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "WITNESS_AUDIT_FINDING"

        expired = fx.suspend_accreditation(
            api, env["elapsed_scope"]["id"], "COVERAGE_ELAPSED"
        )
        assert expired["accreditation_state"] == "EXPIRED"
        assert expired["accreditation_state"] != "SUSPENDED"

    def test_both_destinations_are_terminal_for_a_second_attempt(self, api):
        """PRD 3.2: "Both `SUSPENDED` and `EXPIRED` are terminal, and a second suspension
        attempt against a row already in either is refused with
        `ERR_ACCREDITATION_STATE_INVALID`."

        Design: Corner/state_machines/corner_state_machines_accreditation_suspend_endpoint_branches_to_suspended_or_expired
        """
        env = _two_accreditation_env(api)
        fx.suspend_accreditation(api, env["current_scope"]["id"], "WITNESS_AUDIT_FINDING")
        fx.suspend_accreditation(api, env["elapsed_scope"]["id"], "COVERAGE_ELAPSED")

        for scope_id in (env["current_scope"]["id"], env["elapsed_scope"]["id"]):
            validate_error(
                api.suspend_accreditation(
                    scope_id,
                    {"suspension_reason": "WITNESS_AUDIT_FINDING"},
                    headers=ADMIN_HEADERS,
                ),
                ApiErrorId.ACCREDITATION_STATE_INVALID.value,
                409,
            )

    def test_the_suspended_method_can_no_longer_take_new_work(self, api):
        """PRD 2.10: "Exactly one accreditation record must exist for the target laboratory
        whose `test_method_code` equals the test method of the rule under test, whose
        `accreditation_state` is `ACCREDITED`, and whose closed coverage interval — from
        `valid_from` through `valid_through`, both endpoints inclusive — contains the logical
        clock instant."

        Design: Corner/state_machines/corner_state_machines_accreditation_suspend_endpoint_branches_to_suspended_or_expired
        """
        env = _two_accreditation_env(api)
        fx.suspend_accreditation(api, env["current_scope"]["id"], "WITNESS_AUDIT_FINDING")

        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                    sample_count=1,
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.LAB_METHOD_NOT_ACCREDITED.value,
            422,
        )
        assert fx.get_plan(api, env["plan"]["id"])["units_committed"] == 0
