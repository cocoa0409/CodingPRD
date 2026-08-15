"""Suspect-product investigations: quarantine cascades, the cyclic
OPEN -> QUARANTINED -> CLEARED -> OPEN state machine with its reopen cap,
segregation of duties, confirm-illegitimate decommission cascade, and RBAC."""
from test_helpers import (
    ApiErrorId,
    CaseStatus,
    InvestigationStatus,
    UnitStatus,
    clear_investigation,
    create_case_with_units,
    create_product,
    get_case,
    get_investigation,
    get_unit,
    make_qa_lead_headers,
    open_investigation,
    quarantine_investigation,
    reopen_investigation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQuarantineCascade:
    def test_cascade_units_follow_case_on_quarantine(self, api, qa_lead_headers):
        """PRD §3.6: "The cascade then moves the linked case to `QUARANTINED` —
        the case must be `COMMISSIONED`, `SHIPPED`, or `RECEIVED`, else
        `ERR_CASE_NOT_QUARANTINABLE` — sets the case's `quarantine_link_id` to
        the investigation's `id`, moves every unit of the case that is not
        already `DECOMMISSIONED` to `QUARANTINED`, appends a `QUARANTINE` event
        for the case, and increments both the investigation's `version` and the
        case's `version`."

        Only the linked case and its units are carried; an unrelated case with
        its own unit is untouched.

        Design: Corner/cross_cutting_layers/cascade_units_follow_case_on_quarantine
        """
        set_clock()
        product = create_product()
        case1, units1 = create_case_with_units(product["id"], num_units=2)
        case2, units2 = create_case_with_units(product["id"], num_units=1)
        inv = open_investigation(case1["id"], qa_user_id="qa-cc")

        data = quarantine_investigation(inv["id"], "qa-cc")
        assert data["investigation_status"] == InvestigationStatus.QUARANTINED.value

        case1_after = get_case(case1["id"])
        assert case1_after["case_status"] == CaseStatus.QUARANTINED.value
        assert case1_after["quarantine_link_id"] == inv["id"]
        for unit in units1:
            assert get_unit(unit["id"])["unit_status"] == UnitStatus.QUARANTINED.value

        # Unrelated case and unit untouched.
        assert get_case(case2["id"])["case_status"] == CaseStatus.COMMISSIONED.value
        assert get_unit(units2[0]["id"])["unit_status"] == UnitStatus.COMMISSIONED.value


class TestInvestigationCycle:
    """The cyclic state machine: OPEN -> QUARANTINED -> CLEARED -> OPEN."""

    def _setup_cleared_investigation(self):
        set_clock()
        product = create_product()
        case, _units = create_case_with_units(product["id"], num_units=0)
        inv = open_investigation(case["id"], qa_user_id="qa-opener-1",
                                 reason="suspect serial drift")
        quarantine_investigation(inv["id"], "qa-opener-1")
        cleared = clear_investigation(inv["id"], "qa-reviewer-2")
        return product, case, cleared

    def test_reopen_returns_investigation_to_open_with_incremented_count(
        self, api, qa_lead_headers
    ):
        """PRD §3.6: "While `reopen_count` remains below three, a
        `QualityAssuranceLead` may reopen it, returning it from `CLEARED` to
        `OPEN`, incrementing `reopen_count` by one, and bumping the
        investigation's `version`."

        Design: Difficulty/non_linear_state_machine/investigation_clear_reopen_cycle
        """
        _p, _case, cleared = self._setup_cleared_investigation()
        assert cleared["investigation_status"] == InvestigationStatus.CLEARED.value

        data = reopen_investigation(cleared["id"], "qa-opener-1")
        assert data["investigation_status"] == InvestigationStatus.OPEN.value, (
            "the cycle loops back to the initial state"
        )
        assert data["reopen_count"] == 1

    def test_clear_releases_case_to_pre_quarantine_state(self, api, qa_lead_headers):
        """PRD §3.6: "Clearing requires the investigation to be `QUARANTINED`
        (`ERR_INVESTIGATION_NOT_QUARANTINED`) and releases the case: the case's
        status is restored to what it was before quarantine — `RECEIVED` when
        it was quarantined from `RECEIVED`, otherwise `COMMISSIONED` — its
        `quarantine_link_id` returns to null, every `QUARANTINED` unit follows
        to the same restored status, a `RELEASE` event is appended, and the
        investigation becomes `CLEARED`."

        This case was quarantined from COMMISSIONED, so the release restores
        COMMISSIONED.

        Design: Difficulty/non_linear_state_machine/investigation_clear_reopen_cycle
        """
        _p, case, cleared = self._setup_cleared_investigation()
        case_after = get_case(case["id"])
        assert case_after["case_status"] == CaseStatus.COMMISSIONED.value, (
            f"release must restore the pre-quarantine state, got "
            f"{case_after['case_status']}"
        )
        assert case_after["quarantine_link_id"] is None


class TestReopenLimit:
    """Zero-remaining boundary: the third reopen succeeds; the fourth fails."""

    def _cycle_three_times(self):
        """Drive reopen_count to 3 via three full laps, honoring segregation
        of duties by alternating QA users."""
        set_clock()
        product = create_product()
        case, _units = create_case_with_units(product["id"], num_units=0)
        inv = open_investigation(case["id"], qa_user_id="qa-1")
        # Lap 1: qa-1 quarantines, qa-2 clears, qa-1 reopens (count 1).
        quarantine_investigation(inv["id"], "qa-1")
        clear_investigation(inv["id"], "qa-2")
        inv = reopen_investigation(inv["id"], "qa-1")
        # Lap 2: qa-2 quarantines, qa-1 clears, qa-2 reopens (count 2).
        quarantine_investigation(inv["id"], "qa-2")
        clear_investigation(inv["id"], "qa-1")
        inv = reopen_investigation(inv["id"], "qa-2")
        # Lap 3: qa-1 quarantines, qa-2 clears, qa-1 reopens (count 3).
        quarantine_investigation(inv["id"], "qa-1")
        clear_investigation(inv["id"], "qa-2")
        inv = reopen_investigation(inv["id"], "qa-1")
        return case, inv

    def test_third_reopen_succeeds_at_count_boundary(self, api, qa_lead_headers):
        """PRD §3.6: "While `reopen_count` remains below three, a
        `QualityAssuranceLead` may reopen it, returning it from `CLEARED` to
        `OPEN`, incrementing `reopen_count` by one, and bumping the
        investigation's `version`."

        The third reopen is taken while reopen_count == 2 — below three — and
        lands the count at exactly 3.

        Design: Difficulty/boundary_precision_check/reopen_limit_zero_remaining_rejects
        """
        _case, inv = self._cycle_three_times()
        assert inv["reopen_count"] == 3
        assert inv["investigation_status"] == InvestigationStatus.OPEN.value

    def test_fourth_reopen_rejected_at_limit(self, api, qa_lead_headers):
        """PRD §3.6: "one that has already been reopened three times is
        rejected with `ERR_REOPEN_LIMIT_REACHED`."

        With reopen_count == 3 the reopen budget is exhausted: a further
        quarantine/clear lap succeeds, but the fourth reopen is refused.

        Design: Difficulty/boundary_precision_check/reopen_limit_zero_remaining_rejects
        """
        _case, inv = self._cycle_three_times()
        quarantine_investigation(inv["id"], "qa-2")
        clear_investigation(inv["id"], "qa-1")

        resp = api.reopen_investigation(inv["id"], make_qa_lead_headers("qa-2"))
        validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_REACHED)
        after = get_investigation(inv["id"])
        assert after["investigation_status"] == InvestigationStatus.CLEARED.value
        assert after["reopen_count"] == 3


class TestConfirmIllegitimateCascade:
    """Depth-3 cascade: investigation disposition -> case -> units -> ledger."""

    def _setup_quarantined_case_with_units(self):
        set_clock()
        product = create_product()
        case, units = create_case_with_units(product["id"], num_units=2)
        inv = open_investigation(case["id"], qa_user_id="qa-a",
                                 reason="verification failure")
        quarantine_investigation(inv["id"], "qa-a")
        return product, case, units, inv

    def test_confirm_illegitimate_decommissions_case_and_units(
        self, api, qa_lead_headers
    ):
        """PRD §3.6: "Confirming illegitimacy likewise requires `QUARANTINED`
        (`ERR_INVESTIGATION_NOT_QUARANTINED`) and destroys the product: the
        case moves to `DECOMMISSIONED`, every `QUARANTINED` unit moves to
        `DECOMMISSIONED`, a `DECOMMISSION` event is appended, and the
        investigation lands in the terminal `CONFIRMED_ILLEGITIMATE` state."

        Design: Difficulty/transitive_cascade/confirm_illegitimate_cascade_depth3
        """
        _p, case, units, inv = self._setup_quarantined_case_with_units()

        resp = api.confirm_illegitimate(inv["id"], make_qa_lead_headers("qa-b"))
        data = validate_success(resp)
        assert data["investigation_status"] == InvestigationStatus.CONFIRMED_ILLEGITIMATE.value

        assert get_case(case["id"])["case_status"] == CaseStatus.DECOMMISSIONED.value
        for unit in units:
            assert get_unit(unit["id"])["unit_status"] == UnitStatus.DECOMMISSIONED.value

    def test_confirm_illegitimate_appends_chained_decommission_event(
        self, api, qa_lead_headers
    ):
        """PRD §3.6: "a `DECOMMISSION` event is appended".
        PRD §3.3: "The first event recorded for a case carries an empty string.
        Thereafter the system locates the previous event for the same case —
        the one with the greatest `event_time`, ties broken by the greatest
        `recorded_at` — and computes a hex SHA-256-style digest over the
        concatenation of that previous event's `txn_history_hash`...".

        The quarantine machinery already appended a QUARANTINE event, so the
        DECOMMISSION event's hash chains onto it: non-empty and distinct.

        Design: Difficulty/transitive_cascade/confirm_illegitimate_cascade_depth3
        """
        _p, case, _units, inv = self._setup_quarantined_case_with_units()
        validate_success(api.confirm_illegitimate(inv["id"], make_qa_lead_headers("qa-b")))

        resp = api.list_epcis_events(
            make_qa_lead_headers("qa-b"),
            params={"subject_case_id": case["id"]},
        )
        events, meta = validate_paginated(resp)
        by_type = {}
        for ev in events:
            by_type.setdefault(ev["event_type"], []).append(ev)

        assert "QUARANTINE" in by_type, "quarantine must append a QUARANTINE event"
        assert "DECOMMISSION" in by_type, "confirm-illegitimate must append a DECOMMISSION event"
        quarantine_ev = by_type["QUARANTINE"][0]
        decommission_ev = by_type["DECOMMISSION"][0]
        assert decommission_ev["txn_history_hash"] != ""
        assert decommission_ev["txn_history_hash"] != quarantine_ev["txn_history_hash"]


class TestSegregationOfDuties:
    def test_same_user_cannot_clear_but_different_user_can(self, api, qa_lead_headers):
        """PRD §3.6: "Disposition comes in two forms, both guarded by
        segregation of duties: the acting lead's `X-User-ID` must differ from
        the stored `quarantined_by_user_id`, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.1: "the quarantine action on a suspect investigation stamps
        `quarantined_by_user_id` with the caller's `X-User-ID`, and the
        segregation-of-duties checks on clearing or confirming that same
        investigation compare the new caller's header against the stored value".

        Design: Corner/rbac/segregation_of_duties_same_user_clear_rejected
        """
        set_clock()
        product = create_product()
        case, _units = create_case_with_units(product["id"], num_units=0)
        inv = open_investigation(case["id"], qa_user_id="qa-same")
        quarantine_investigation(inv["id"], "qa-same")

        same_user = api.clear_investigation(inv["id"], make_qa_lead_headers("qa-same"))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert (
            get_investigation(inv["id"])["investigation_status"]
            == InvestigationStatus.QUARANTINED.value
        )

        other = api.clear_investigation(inv["id"], make_qa_lead_headers("qa-other"))
        data = validate_success(other)
        assert data["investigation_status"] == InvestigationStatus.CLEARED.value


class TestInvestigationRbac:
    def test_billing_clerk_cannot_quarantine(self, api, billing_clerk_headers):
        """PRD §2.1: "A request whose declared role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403);
        the permission matrix itself is given by the Authorized Role(s) column
        of §4."
        PRD §4: POST /wholesale/suspect-investigations/{investigationId}/
        quarantine — QualityAssuranceLead only.

        Design: Corner/rbac/billing_clerk_cannot_quarantine
        """
        set_clock()
        product = create_product()
        case, _units = create_case_with_units(product["id"], num_units=0)
        inv = open_investigation(case["id"], qa_user_id="qa-rb")

        resp = api.quarantine_investigation(inv["id"], billing_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert (
            get_investigation(inv["id"])["investigation_status"]
            == InvestigationStatus.OPEN.value
        )
