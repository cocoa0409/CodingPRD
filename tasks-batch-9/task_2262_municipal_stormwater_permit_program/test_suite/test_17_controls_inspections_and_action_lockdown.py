"""Agreements, frozen inspections and terminal enforcement actions."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import INSPECTOR_HEADERS, INSPECTOR_ONE, OFFICER_HEADERS


def _record_agreement(facility_id, reference, months=12):
    return api_client.record_agreement(
        facility_id,
        factories.record_agreement_payload(
            "2026-08-01T00:00:00Z", months, agreement_reference=reference
        ),
        INSPECTOR_HEADERS,
    )


def _close_site(site_id, note):
    return api_client.close_construction_site(
        site_id,
        factories.close_site_payload(final_stabilization_note=note),
        INSPECTOR_HEADERS,
    )


def _add_finding(inspection_id, severity, description):
    return api_client.add_inspection_finding(
        inspection_id,
        factories.finding_payload(severity, description=description),
        INSPECTOR_HEADERS,
    )


def _finalize(inspection_id):
    return api_client.finalize_inspection(inspection_id, INSPECTOR_HEADERS)


def _issue_site_action(site_id):
    return validate_success(
        api_client.create_enforcement_action(
            factories.enforcement_action_payload(
                "NOTICE_OF_VIOLATION", violation_days=0, construction_site_id=site_id
            ),
            OFFICER_HEADERS,
        ),
        201,
    )


class TestClosingATwoAcreSiteNeedsARecordedAgreement:
    """The gate a 1.50 acre site never faces, and what actually satisfies it."""

    @pytest.fixture
    def large_approved_site(self, active_program):
        """SITE-F at 2.50 acres, plan APPROVED, field ACTIVE_DISTURBANCE, no facility."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-F",
            site_name="SITE-F",
            operator_name="Northgate Civil",
            disturbed_acres=2.50,
        )
        return {"term_id": active_program["term_id"], "site": site}

    def test_01_closure_is_refused_when_no_permanent_control_exists(
        self, large_approved_site
    ):
        """2.50 acres puts the site under the post-construction requirement.

        PRD: "Where `post_construction_control_required` is true — that is, on every
        site of two acres or more — closure additionally requires at least one permanent
        control inventoried for the site whose `agreement_status` is `RECORDED` or
        `NOT_REQUIRED`; a site with no such facility is refused with
        `ERR_CLOSE_REQUIRES_MAINTENANCE_AGREEMENT`."

        Design: Corner/state_machines/closing_a_two_acre_site_requires_a_recorded_maintenance_agreement
        """
        site = fx.read_site(large_approved_site["site"]["id"])
        assert site["post_construction_control_required"] is True, (
            "two and a half acres requires a permanent control"
        )

        response = _close_site(large_approved_site["site"]["id"], "Stabilized")

        validate_error(
            response, ApiErrorId.ERR_CLOSE_REQUIRES_MAINTENANCE_AGREEMENT.value, 422
        )

        after = fx.read_site(large_approved_site["site"]["id"])
        assert after["field_status"] == "ACTIVE_DISTURBANCE", "the site stays open"
        assert after["closed_at"] is None, "nothing was stamped"

    def test_02_a_facility_that_merely_exists_does_not_satisfy_the_gate(
        self, large_approved_site
    ):
        """A PENDING agreement is not one of the two accepted statuses.

        PRD: "closure additionally requires at least one permanent control inventoried
        for the site whose `agreement_status` is `RECORDED` or `NOT_REQUIRED`; a site
        with no such facility is refused with
        `ERR_CLOSE_REQUIRES_MAINTENANCE_AGREEMENT`."

        Design: Corner/state_machines/closing_a_two_acre_site_requires_a_recorded_maintenance_agreement
        """
        facility = fx.create_facility(
            large_approved_site["site"]["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=5200.00,
            service_area_acres=2.50,
        )
        assert facility["agreement_status"] == "PENDING", (
            "a private control opens on the agreement track"
        )

        response = _close_site(large_approved_site["site"]["id"], "Stabilized")

        validate_error(
            response, ApiErrorId.ERR_CLOSE_REQUIRES_MAINTENANCE_AGREEMENT.value, 422
        )

    def test_03_recording_the_agreement_opens_the_gate(self, large_approved_site):
        """The same closure call succeeds once the instrument is on record.

        PRD: "The call writes `RECORDED` into `agreement_status`, copies `recorded_at`
        into `agreement_recorded_at`, stores the interval, and recomputes the three
        currency fields described below." And: "`credit_eligible` is true exactly when
        `ownership` is `PRIVATE`, `agreement_status` is `RECORDED`, and
        `inspection_overdue` is false — the three conditions the utility credit
        programme leans on in §3.8."

        Design: Corner/state_machines/closing_a_two_acre_site_requires_a_recorded_maintenance_agreement
        """
        facility = fx.create_facility(
            large_approved_site["site"]["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=5200.00,
            service_area_acres=2.50,
        )
        _close_site(large_approved_site["site"]["id"], "Stabilized")

        recorded = validate_success(
            _record_agreement(facility["id"], "BK-4412-PG-119", 12)
        )
        assert recorded["agreement_status"] == "RECORDED", "the agreement is on record"
        assert recorded["agreement_reference"] == "BK-4412-PG-119", (
            "the instrument reference is stored"
        )
        assert recorded["inspection_interval_months"] == 12, "the interval is stored"
        assert recorded["months_since_last_inspection"] == 0, (
            "recordation and the clock are the same instant"
        )
        assert recorded["inspection_overdue"] is False, "nothing is overdue yet"
        assert recorded["credit_eligible"] is True, (
            "a private control with a current agreement is credit eligible"
        )

        closed = validate_success(
            _close_site(large_approved_site["site"]["id"], "Stabilized and agreement recorded")
        )
        assert closed["field_status"] == "CLOSED", "the unblocked closure succeeds"


class TestAgreementRecordingHappensOnce:
    """One error code for two quite different states."""

    @pytest.fixture
    def two_facilities(self, active_program):
        """SITE-G at 2.50 acres carrying one PRIVATE and one MUNICIPAL control."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-G",
            operator_name="Northgate Civil",
            disturbed_acres=2.50,
        )
        private = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=4200.00,
            service_area_acres=1.20,
        )
        municipal = fx.create_facility(
            site["id"],
            "MUNICIPAL",
            facility_type="UNDERGROUND_DETENTION",
            design_capacity_cf=9000.00,
            service_area_acres=1.30,
        )
        return {"site": site, "private": private, "municipal": municipal}

    def test_04_a_municipal_control_needs_no_agreement_at_all(self, two_facilities):
        """Ownership decides the track at creation, and it decides it once.

        PRD: "Ownership decides the agreement track immediately: a `MUNICIPAL` facility
        is created with `agreement_status` `NOT_REQUIRED`, while a `PRIVATE` facility is
        created with `agreement_status` `PENDING` because a privately owned control must
        carry a recorded maintenance agreement."

        Design: Corner/state_machines/agreement_recording_happens_once_and_never_on_a_municipal_facility
        """
        municipal = fx.read_facility(two_facilities["municipal"]["id"])

        assert municipal["agreement_status"] == "NOT_REQUIRED", (
            "a municipal control is off the agreement track"
        )
        assert municipal["credit_eligible"] is False, (
            "a municipal control is never credit eligible"
        )
        assert municipal["agreement_reference"] is None, "no instrument was recorded"

    def test_05_the_first_recording_on_a_private_control_succeeds(self, two_facilities):
        """A six month interval is stored exactly as agreed.

        PRD: "Recording the agreement supplies the instrument's `agreement_reference`,
        the `recorded_at` instant of recordation and the `inspection_interval_months`
        agreed for maintenance inspection, which must be between 1 and 60 inclusive."

        Design: Corner/state_machines/agreement_recording_happens_once_and_never_on_a_municipal_facility
        """
        recorded = validate_success(
            _record_agreement(two_facilities["private"]["id"], "BK-5000-PG-01", 6)
        )

        assert recorded["agreement_status"] == "RECORDED", "the agreement is on record"
        assert recorded["inspection_interval_months"] == 6, "the agreed interval is stored"
        assert recorded["agreement_recorded_at"] == "2026-08-01T00:00:00Z", (
            "the recordation instant is copied from the request"
        )

    def test_06_a_second_recording_is_refused_and_overwrites_nothing(
        self, two_facilities
    ):
        """The stored reference and interval survive the refused second call.

        PRD: "Recording twice, or recording against a `MUNICIPAL` facility whose
        `agreement_status` is `NOT_REQUIRED`, is refused with
        `ERR_AGREEMENT_ALREADY_RECORDED`."

        Design: Corner/state_machines/agreement_recording_happens_once_and_never_on_a_municipal_facility
        """
        facility_id = two_facilities["private"]["id"]
        validate_success(_record_agreement(facility_id, "BK-5000-PG-01", 6))

        response = _record_agreement(facility_id, "BK-5000-PG-02", 12)

        validate_error(response, ApiErrorId.ERR_AGREEMENT_ALREADY_RECORDED.value, 409)

        facility = fx.read_facility(facility_id)
        assert facility["agreement_reference"] == "BK-5000-PG-01", (
            "the first instrument still stands"
        )
        assert facility["inspection_interval_months"] == 6, (
            "the refused call did not change the interval"
        )

    def test_07_recording_against_a_municipal_control_reports_the_same_code(
        self, two_facilities
    ):
        """NOT_REQUIRED is refused by the very same error as RECORDED.

        PRD: "Recording twice, or recording against a `MUNICIPAL` facility whose
        `agreement_status` is `NOT_REQUIRED`, is refused with
        `ERR_AGREEMENT_ALREADY_RECORDED`."

        Design: Corner/state_machines/agreement_recording_happens_once_and_never_on_a_municipal_facility
        """
        response = _record_agreement(
            two_facilities["municipal"]["id"], "BK-5000-PG-03", 12
        )

        validate_error(response, ApiErrorId.ERR_AGREEMENT_ALREADY_RECORDED.value, 409)

        facility = fx.read_facility(two_facilities["municipal"]["id"])
        assert facility["agreement_status"] == "NOT_REQUIRED", "the track is unchanged"
        assert facility["agreement_reference"] is None, "nothing was recorded"
        assert facility["inspection_interval_months"] is None, "no interval was stored"


class TestFindingsAndFinalizeLockTogether:
    """An empty inspection cannot be frozen, and a frozen one accepts nothing."""

    @pytest.fixture
    def draft_inspection(self, active_program):
        """SITE-H under active disturbance with one DRAFT erosion-control inspection."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-H",
            site_name="SITE-H",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        inspection = validate_success(
            api_client.create_inspection(
                factories.esc_inspection_payload(
                    site["id"], "2026-08-01", "2026-08-31", rainfall_trigger=False
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )
        return {"site": site, "inspection": inspection}

    def test_08_an_empty_inspection_cannot_be_finalized(self, draft_inspection):
        """A frozen score of zero would be meaningless, so it is refused.

        PRD: "Finalizing freezes the score. It requires the `findings` list to hold at
        least one entry, refusing an empty inspection with
        `ERR_INSPECTION_NO_FINDINGS`, because a frozen score of 0 would be
        meaningless."

        Design: Corner/state_machines/inspection_findings_and_finalize_lock_once_the_inspection_is_finalized
        """
        response = _finalize(draft_inspection["inspection"]["id"])

        validate_error(response, ApiErrorId.ERR_INSPECTION_NO_FINDINGS.value, 422)

        inspection = fx.read_inspection(draft_inspection["inspection"]["id"])
        assert inspection["status"] == "DRAFT", "the refused finalize froze nothing"
        assert inspection["deficiency_score"] == 0, "no score was computed"
        assert inspection["finalized_at"] is None, "nothing was stamped"

    def test_09_a_finding_raises_its_counter_without_scoring_anything(
        self, draft_inspection
    ):
        """The score exists only from finalize onward.

        PRD: "Each append adds an entry to the append-only `findings` list and raises
        the matching counter — `minor_finding_count`, `major_finding_count` or
        `critical_finding_count`." And: "The **deficiency score** is computed once, at
        finalize, and never recomputed afterwards."

        Design: Corner/state_machines/inspection_findings_and_finalize_lock_once_the_inspection_is_finalized
        """
        appended = validate_success(
            _add_finding(
                draft_inspection["inspection"]["id"],
                "MINOR",
                "Inlet protection displaced at station 4",
            )
        )

        assert appended["minor_finding_count"] == 1, "the minor counter rose"
        assert appended["major_finding_count"] == 0, "no major finding exists"
        assert appended["critical_finding_count"] == 0, "no critical finding exists"
        assert appended["deficiency_score"] == 0, (
            "the score is only frozen at finalize"
        )
        assert len(appended["findings"]) == 1, "the append-only list holds one entry"

    def test_10_finalizing_freezes_a_single_minor_finding_at_eight_points(
        self, draft_inspection
    ):
        """Eight points is well below the escalation threshold.

        PRD: "The base is 8 points for each finding counted in `minor_finding_count`,
        plus 22 points for each finding counted in `major_finding_count`, plus 34 points
        for each finding counted in `critical_finding_count`." And: "`deficiency_score`
        is the resulting figure capped at 100, and `escalation_triggered` is set true
        exactly when `deficiency_score` is 70 or more."

        Design: Corner/state_machines/inspection_findings_and_finalize_lock_once_the_inspection_is_finalized
        """
        inspection_id = draft_inspection["inspection"]["id"]
        validate_success(
            _add_finding(inspection_id, "MINOR", "Inlet protection displaced at station 4")
        )

        finalized = validate_success(_finalize(inspection_id))

        assert finalized["status"] == "FINALIZED", "the inspection is frozen"
        assert finalized["deficiency_score"] == 8, (
            f"one minor finding scores eight points, got {finalized['deficiency_score']}"
        )
        assert finalized["escalation_triggered"] is False, "eight is below seventy"
        assert finalized["finalized_at"] is not None, "finalization stamps its instant"
        assert finalized["finalized_by_user_id"] == INSPECTOR_ONE, (
            "the acting inspector is recorded"
        )

        site = fx.read_site(draft_inspection["site"]["id"])
        assert site["field_status"] == "ACTIVE_DISTURBANCE", (
            "a score below the threshold drives no stop-work order"
        )

    @pytest.mark.parametrize("operation", ["add_finding", "finalize_again"])
    def test_11_a_finalized_inspection_accepts_nothing_further(
        self, draft_inspection, operation
    ):
        """Both the append and the freeze report the same locked state.

        PRD: "Appending to an inspection that has already been finalized is refused
        with `ERR_INSPECTION_NOT_DRAFT`, and an unknown inspection identifier is
        `ERR_INSPECTION_NOT_FOUND`." And: "Finalizing an inspection that is not in
        `DRAFT` is `ERR_INSPECTION_NOT_DRAFT`."

        Design: Corner/state_machines/inspection_findings_and_finalize_lock_once_the_inspection_is_finalized
        """
        inspection_id = draft_inspection["inspection"]["id"]
        validate_success(
            _add_finding(inspection_id, "MINOR", "Inlet protection displaced at station 4")
        )
        validate_success(_finalize(inspection_id))

        calls = {
            "add_finding": lambda: _add_finding(
                inspection_id, "CRITICAL", "Late addition"
            ),
            "finalize_again": lambda: _finalize(inspection_id),
        }

        validate_error(calls[operation](), ApiErrorId.ERR_INSPECTION_NOT_DRAFT.value, 409)

        inspection = fx.read_inspection(inspection_id)
        assert inspection["critical_finding_count"] == 0, "no late finding was appended"
        assert inspection["deficiency_score"] == 8, "the frozen score is never recomputed"


class TestMaintenanceFinalizeWaitsOnTheAgreement:
    """Creation is allowed against a PENDING agreement; finalization is not."""

    @pytest.fixture
    def pending_facility_inspection(self, active_program):
        """A DRAFT maintenance inspection with one MINOR finding on a PENDING control."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-I",
            operator_name="Northgate Civil",
            disturbed_acres=2.50,
        )
        facility = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="WET_POND",
            design_capacity_cf=7000.00,
            service_area_acres=2.50,
        )
        inspection = validate_success(
            api_client.create_inspection(
                factories.maintenance_inspection_payload(
                    facility["id"], "2026-07-01", "2026-07-31"
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )
        validate_success(
            _add_finding(
                inspection["id"],
                "MINOR",
                "Forebay sediment at 40 percent of design depth",
            )
        )
        return {
            "measure_id": active_program["measures"]["POST_CONSTRUCTION"]["id"],
            "facility": facility,
            "inspection": inspection,
        }

    def test_12_finalizing_against_a_pending_agreement_is_refused(
        self, pending_facility_inspection
    ):
        """The maintenance branch guards the subject facility, not the site.

        PRD: "For an erosion-control inspection the subject site's `field_status` must
        be `ACTIVE_DISTURBANCE` or `STOP_WORK`; for a maintenance inspection the subject
        facility's `agreement_status` must be `RECORDED` or `NOT_REQUIRED`, and a
        facility still in `PENDING` is refused with `ERR_AGREEMENT_NOT_RECORDED`."

        Design: Corner/state_machines/maintenance_inspection_cannot_be_finalized_against_a_pending_agreement
        """
        response = _finalize(pending_facility_inspection["inspection"]["id"])

        validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_RECORDED.value, 422)

        inspection = fx.read_inspection(pending_facility_inspection["inspection"]["id"])
        assert inspection["status"] == "DRAFT", "the refused finalize froze nothing"
        assert inspection["deficiency_score"] == 0, "no score was computed"

    def test_13_recording_the_agreement_lets_the_same_finalize_through(
        self, pending_facility_inspection
    ):
        """Neither maintenance adder applies once the agreement is current.

        PRD: "For a `POST_CONSTRUCTION_MAINTENANCE` inspection, `rainfall_trigger` is
        ignored entirely. Instead, if the subject facility's `inspection_overdue` is
        true, 15 points are added; then, if that facility's `ownership` is `PRIVATE` and
        its `agreement_status` is anything other than `RECORDED`, a further 25 points are
        added."

        Design: Corner/state_machines/maintenance_inspection_cannot_be_finalized_against_a_pending_agreement
        """
        validate_success(
            _record_agreement(
                pending_facility_inspection["facility"]["id"], "BK-6100-PG-77", 12
            )
        )

        finalized = validate_success(
            _finalize(pending_facility_inspection["inspection"]["id"])
        )

        assert finalized["status"] == "FINALIZED", "the guard is satisfied"
        assert finalized["deficiency_score"] == 8, (
            "neither the overdue adder nor the no-agreement adder applies, got "
            f"{finalized['deficiency_score']}"
        )

    def test_14_finalization_back_fills_the_facility_bookkeeping(
        self, pending_facility_inspection
    ):
        """The maintenance cascade refreshes all four currency fields.

        PRD: "A maintenance inspection refreshes the subject facility's
        `last_inspection_finalized_at`, `months_since_last_inspection`,
        `inspection_overdue` and `credit_eligible`, which can newly qualify — or newly
        disqualify — that facility for the credit programme."

        Design: Corner/state_machines/maintenance_inspection_cannot_be_finalized_against_a_pending_agreement
        """
        validate_success(
            _record_agreement(
                pending_facility_inspection["facility"]["id"], "BK-6100-PG-77", 12
            )
        )
        finalized = validate_success(
            _finalize(pending_facility_inspection["inspection"]["id"])
        )

        facility = fx.read_facility(pending_facility_inspection["facility"]["id"])
        assert facility["last_inspection_finalized_at"] == finalized["finalized_at"], (
            "the facility now points at its newest finalized inspection"
        )
        assert facility["months_since_last_inspection"] == 0, (
            "the inspection and the clock are the same instant"
        )
        assert facility["inspection_overdue"] is False, "nothing is overdue"
        assert facility["credit_eligible"] is True, (
            "a current private control is credit eligible"
        )

    def test_15_finalization_reports_no_measurable_goal_progress(
        self, pending_facility_inspection
    ):
        """Inspecting a control is not the same as reporting a goal actual.

        PRD: "The manager or a `MunicipalOperationsSupervisor` reports progress by
        supplying `measurable_goal_actual`, which requires the measure's `status` to be
        `ACTIVE`; the call stamps `last_progress_reported_at` from the logical clock."
        And: "If `last_progress_reported_at` is null and `measurable_goal_actual` is 0,
        the result is `PENDING`."

        Design: Corner/state_machines/maintenance_inspection_cannot_be_finalized_against_a_pending_agreement
        """
        validate_success(
            _record_agreement(
                pending_facility_inspection["facility"]["id"], "BK-6100-PG-77", 12
            )
        )
        validate_success(_finalize(pending_facility_inspection["inspection"]["id"]))

        measure = fx.read_measure(pending_facility_inspection["measure_id"])
        assert measure["measurable_goal_actual"] == pytest.approx(0.00, abs=0.01), (
            "finalizing an inspection reports no progress"
        )
        assert measure["goal_status"] == "PENDING", "the measure is still unreported"


class TestEnforcementActionsLockAfterClosureOrRescission:
    """Two terminal states, one code, and a ledger that remembers each of them."""

    @pytest.fixture
    def enforced_site(self, active_program):
        """SITE-J approved and under active disturbance."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-J",
            site_name="SITE-J",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        return {
            "term_id": active_program["term_id"],
            "measure_id": active_program["measures"]["CONSTRUCTION_RUNOFF"]["id"],
            "site": site,
        }

    def test_16_the_first_action_is_priced_without_a_multiplier(self, enforced_site):
        """No prior action means the notice base stands alone.

        PRD: "Third, `escalation_multiplier` is read from that prior total: 1.00 when
        `prior_assessed_total_cents` is 0; 1.50 when it is greater than 0 but less than
        100000 cents; and 2.25 when it is 100000 cents or more."

        Design: Corner/state_machines/enforcement_actions_lock_after_closure_or_rescission
        """
        first = _issue_site_action(enforced_site["site"]["id"])

        assert first["prior_assessed_total_cents"] == 0, "nothing preceded it"
        assert first["escalation_multiplier"] == pytest.approx(1.00, abs=0.01), (
            "a zero prior total leaves the multiplier at one"
        )
        assert first["penalty_cents"] == 25000, (
            f"the notice base stands alone, got {first['penalty_cents']}"
        )

    def test_17_a_closed_action_still_counts_toward_the_next_prior_total(
        self, enforced_site
    ):
        """CLOSED is one of the three counted statuses, so the second action escalates.

        PRD: "Second, `prior_assessed_total_cents` is the sum of `penalty_cents` over
        the *other* enforcement actions on the same subject whose `status` is `ISSUED`,
        `ESCALATED` or `CLOSED`, excluding this action's own row and frozen before this
        row's own penalty is written."

        Design: Corner/state_machines/enforcement_actions_lock_after_closure_or_rescission
        """
        first = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.close_enforcement_action(
                first["id"],
                factories.close_enforcement_payload(
                    compliance_note="Corrected within 3 days"
                ),
                OFFICER_HEADERS,
            )
        )

        second = _issue_site_action(enforced_site["site"]["id"])

        assert second["prior_assessed_total_cents"] == 25000, (
            "the closed first action still counts"
        )
        assert second["escalation_multiplier"] == pytest.approx(1.50, abs=0.01), (
            "a prior total under 100000 cents earns the middle multiplier"
        )
        assert second["penalty_cents"] == 37500, (
            f"25000 times 1.50 is 37500 cents, got {second['penalty_cents']}"
        )

        term = fx.read_term(enforced_site["term_id"])
        assert term["total_assessed_penalty_cents"] == 62500, (
            f"the ledger carries both actions, got "
            f"{term['total_assessed_penalty_cents']}"
        )

    def test_18_rescission_reverses_the_money_of_the_second_action(self, enforced_site):
        """The ledger drops back to the closed action's penalty alone.

        PRD: "From `ISSUED` or `ESCALATED`, and carrying a `reason`, rescission writes
        `RESCINDED` into `status`, stamps `rescinded_at`, records the reason in
        `rescinded_reason`, subtracts the action's `penalty_cents` from the term's
        `total_assessed_penalty_cents` and then sets `penalty_cents` to 0."

        Design: Corner/state_machines/enforcement_actions_lock_after_closure_or_rescission
        """
        first = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.close_enforcement_action(
                first["id"],
                factories.close_enforcement_payload(
                    compliance_note="Corrected within 3 days"
                ),
                OFFICER_HEADERS,
            )
        )
        second = _issue_site_action(enforced_site["site"]["id"])

        rescinded = validate_success(
            api_client.rescind_enforcement_action(
                second["id"],
                factories.rescind_payload(reason="Issued against the wrong operator"),
                OFFICER_HEADERS,
            )
        )

        assert rescinded["status"] == "RESCINDED", "the action is rescinded"
        assert rescinded["penalty_cents"] == 0, "its money is zeroed"
        assert rescinded["rescinded_at"] is not None, "rescission stamps its instant"

        term = fx.read_term(enforced_site["term_id"])
        assert term["total_assessed_penalty_cents"] == 25000, (
            f"only the closed action remains in the ledger, got "
            f"{term['total_assessed_penalty_cents']}"
        )

    @pytest.mark.parametrize(
        "target, operation",
        [
            ("rescinded", "escalate"),
            ("closed", "escalate"),
            ("closed", "close"),
            ("closed", "rescind"),
        ],
    )
    def test_19_neither_terminal_state_accepts_any_further_trigger(
        self, enforced_site, target, operation
    ):
        """CLOSED and RESCINDED are equally final for all three triggers.

        PRD: "Both `CLOSED` and `RESCINDED` are terminal; escalating, closing or
        rescinding an action already in either is refused with
        `ERR_ENFORCEMENT_NOT_OPEN`."

        Design: Corner/state_machines/enforcement_actions_lock_after_closure_or_rescission
        """
        first = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.close_enforcement_action(
                first["id"],
                factories.close_enforcement_payload(
                    compliance_note="Corrected within 3 days"
                ),
                OFFICER_HEADERS,
            )
        )
        second = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.rescind_enforcement_action(
                second["id"],
                factories.rescind_payload(reason="Issued against the wrong operator"),
                OFFICER_HEADERS,
            )
        )

        action_id = first["id"] if target == "closed" else second["id"]
        calls = {
            "escalate": lambda: api_client.escalate_enforcement_action(
                action_id, factories.escalate_payload(violation_days=5), OFFICER_HEADERS
            ),
            "close": lambda: api_client.close_enforcement_action(
                action_id,
                factories.close_enforcement_payload(compliance_note="Again"),
                OFFICER_HEADERS,
            ),
            "rescind": lambda: api_client.rescind_enforcement_action(
                action_id,
                factories.rescind_payload(reason="Change of heart"),
                OFFICER_HEADERS,
            ),
        }

        validate_error(calls[operation](), ApiErrorId.ERR_ENFORCEMENT_NOT_OPEN.value, 409)

    def test_20_the_rescission_lowers_the_construction_runoff_gate_count(
        self, enforced_site
    ):
        """One live count is short of the gate that trips at two.

        PRD: "It lowers the subject site's `open_enforcement_count` and the
        `CONSTRUCTION_RUNOFF` control measure's `enforcement_count`, recomputes that
        measure's `goal_status` — which is one of the two ways a tripped gate clears —
        recomputes the term's `compliance_posture`, and may push a `COMPILED` or
        `CERTIFIED` annual report back to `DRAFT`."

        Design: Corner/state_machines/enforcement_actions_lock_after_closure_or_rescission
        """
        first = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.close_enforcement_action(
                first["id"],
                factories.close_enforcement_payload(
                    compliance_note="Corrected within 3 days"
                ),
                OFFICER_HEADERS,
            )
        )
        second = _issue_site_action(enforced_site["site"]["id"])
        validate_success(
            api_client.rescind_enforcement_action(
                second["id"],
                factories.rescind_payload(reason="Issued against the wrong operator"),
                OFFICER_HEADERS,
            )
        )

        measure = fx.read_measure(enforced_site["measure_id"])
        assert measure["enforcement_count"] == 1, (
            f"the rescission leaves one counted action, got "
            f"{measure['enforcement_count']}"
        )
        assert measure["goal_status"] != "BEHIND", (
            "one enforcement action does not trip the gate that needs two"
        )
