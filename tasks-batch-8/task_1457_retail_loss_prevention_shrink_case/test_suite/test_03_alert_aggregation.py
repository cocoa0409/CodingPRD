"""Exception intake, weighted alert scoring, alert lifecycle (dismiss /
convert), and alert list filtering."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_alert,
    list_alert_dicts,
    make_analyst_headers,
    make_employee,
    make_manager_headers,
    make_pos_feed_headers,
    make_store,
    post_event,
    post_events,
    the_only_alert,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ANALYST_1, MANAGER_1


def _score_of(alert):
    return pytest.approx(alert["score"], abs=0.001)


class TestEventIntakeValidation:
    def test_event_invalid_exception_type_returns_invalid_request(self, api):
        """PRD §3.2: "The `PosFeed` machine account ingests one exception event
        at a time, supplying `store_id`, `register_ref`, `txn_ref`, an
        `exception_type` drawn from `REFUND_NO_RECEIPT`, `HIGH_VALUE_VOID`,
        `PRICE_OVERRIDE`, `NO_SALE_DRAWER`, `SUSPEND_CANCEL`,
        `SWEETHEART_SCAN`, and `SELF_CHECKOUT_MISMATCH`, the exception value
        `amount_cents` (which must be greater than zero), the feed-provided
        `occurred_at` timestamp, and optionally `employee_id` — left null for
        self-checkout or otherwise unattributed events."
        PRD §2.7: "4. Request well-formedness: required fields present, types
        correct, enum values within their declared domains, amounts positive
        where required, `scheduled_end` strictly after `scheduled_start`,
        `period_end` on or after `period_start`, `limit` inside its permitted
        range, `offset` at least 0 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/event_invalid_exception_type_returns_invalid_request
        """
        store = make_store(store_number="S020", name="Store 20")
        resp = api.create_exception_event(
            {"store_id": store["id"], "register_ref": "R1", "txn_ref": "T1",
             "exception_type": "BOGUS_TYPE", "amount_cents": 5000,
             "occurred_at": "2026-07-10T10:00:00Z"},
            make_pos_feed_headers("feed-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        alerts = list_alert_dicts(make_analyst_headers(ANALYST_1), store_id=store["id"])
        assert alerts == [], "a rejected event must not aggregate into an alert"

    def test_event_zero_amount_returns_invalid_request(self, api):
        """PRD §3.2: "the exception value `amount_cents` (which must be greater
        than zero)"
        PRD §3.2: "Every event is born `UNAGGREGATED`, and the moment it lands,
        the weighted scoring algorithm runs."

        Design: Corner/entities/event_zero_amount_returns_invalid_request
        """
        store = make_store(store_number="S021", name="Store 21")
        resp = api.create_exception_event(
            {"store_id": store["id"], "register_ref": "R1", "txn_ref": "T0",
             "exception_type": "NO_SALE_DRAWER", "amount_cents": 0,
             "occurred_at": "2026-07-10T10:00:00Z"},
            make_pos_feed_headers("feed-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Boundary: smallest legal amount 1 is accepted; score 6.0 < 40.00, no alert.
        ev = post_event(store["id"], "NO_SALE_DRAWER", 1, "2026-07-10T10:00:00Z",
                        txn_ref="T1")
        assert ev["status"] == "UNAGGREGATED"
        assert list_alert_dicts(make_analyst_headers(ANALYST_1),
                                store_id=store["id"]) == []


class TestAlertScoring:
    def test_alert_computed_fields_populated_on_create(self, api):
        """PRD §3.2: "An alert carries its `store_id` and (possibly null)
        `employee_id` from the group, a derived `subject_type` that reads
        `EMPLOYEE` when `employee_id` is set and `UNKNOWN` otherwise, the
        computed `score`, the `event_count` of member events, their summed
        `total_amount_cents`, and `window_start` / `window_end` spanning the
        earliest and latest member `occurred_at`."
        PRD §3.2: "Each event contributes its type weight — ten points for
        `REFUND_NO_RECEIPT`, fourteen for `HIGH_VALUE_VOID`, eight for
        `PRICE_OVERRIDE`, six for `NO_SALE_DRAWER`, eight for `SUSPEND_CANCEL`,
        twelve for `SWEETHEART_SCAN`, and nine for `SELF_CHECKOUT_MISMATCH` —
        multiplied by an amount band: 1.0 when `amount_cents` is below 5000,
        1.5 when it is at least 5000 but below 20000, and 2.0 when it is at
        least 20000."

        HIGH_VALUE_VOID at 40000 and 35000 both draw the 2.0 band:
        14*2 + 14*2 = 56.0 >= 40.00, so the second event creates the alert.

        Design: Corner/entities/alert_computed_fields_populated_on_create
        """
        store = make_store(store_number="S023", name="Store 23")
        emp = make_employee(store["id"], employee_ref="E-230", full_name="Emp 230")
        post_event(store["id"], "HIGH_VALUE_VOID", 40000, "2026-07-12T10:00:00Z",
                   employee_id=emp["id"], txn_ref="T1")
        post_event(store["id"], "HIGH_VALUE_VOID", 35000, "2026-07-12T12:00:00Z",
                   employee_id=emp["id"], txn_ref="T2")
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert_alert(alert)
        assert alert["score"] == pytest.approx(56.0, abs=0.001)
        assert alert["event_count"] == 2
        assert alert["total_amount_cents"] == 75000
        assert alert["subject_type"] == "EMPLOYEE"
        assert alert["window_start"].startswith("2026-07-12T10:00:00")
        assert alert["window_end"].startswith("2026-07-12T12:00:00")

    def test_alert_creation_threshold_accumulation(self, api):
        """PRD §3.2: "A new alert is created if and only if the candidate set's
        score is at least 40.00; creation aggregates the candidate events into
        the alert, flipping each member to `AGGREGATED`."

        Candidate sum 6 + 8 + 24 = 38.0 stays below 40.00 (no alert); adding a
        15.0-point event pushes the set to 53.0 and the alert aggregates ALL
        FOUR candidate events.

        Design: Corner/calculations/alert_creation_threshold_38_vs_53_accumulation
        """
        store = make_store(store_number="S050", name="Store 50")
        emp = make_employee(store["id"], employee_ref="E-500", full_name="Emp 500")
        headers = make_analyst_headers(ANALYST_1)
        post_events(store["id"], [
            ("NO_SALE_DRAWER", 4000, "2026-07-10T10:00:00Z"),
            ("PRICE_OVERRIDE", 3000, "2026-07-10T11:00:00Z"),
            ("SWEETHEART_SCAN", 20000, "2026-07-10T12:00:00Z"),
        ], employee_id=emp["id"])
        assert list_alert_dicts(headers, store_id=store["id"],
                                employee_id=emp["id"]) == [], "38.0 < 40.00"
        post_event(store["id"], "REFUND_NO_RECEIPT", 5000, "2026-07-10T13:00:00Z",
                   employee_id=emp["id"], txn_ref="T4")
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert alert["score"] == pytest.approx(53.0, abs=0.001)
        assert alert["event_count"] == 4
        assert alert["status"] == "OPEN"
        events, meta = validate_paginated(api.list_exception_events(
            headers, params={"store_id": store["id"], "status": "AGGREGATED"}))
        assert meta["total_count"] == 4

    def test_alert_window_excludes_events_older_than_30_days(self, api):
        """PRD §3.2: "When no open alert exists for the group, the system
        builds a candidate set: every `UNAGGREGATED` event of the same group
        whose `occurred_at` falls within the window from thirty days before the
        new event's `occurred_at` up to and including that instant."

        The triggering event lands at 2026-07-10T11:30:00Z, so the candidate
        window is [2026-06-10T11:30:00Z, 2026-07-10T11:30:00Z]: the event
        exactly 30 days old is included, the 31-day-old one is not. (The
        31-day-old event is deliberately low-weight (6.0) so that no alert
        forms before the trigger event — preserving the instance's pinned
        outcome: score 56.0 over the two in-window events.)

        Design: Corner/calculations/alert_window_excludes_events_older_than_30_days
        """
        store = make_store(store_number="S051", name="Store 51")
        emp = make_employee(store["id"], employee_ref="E-510", full_name="Emp 510")
        old = post_event(store["id"], "NO_SALE_DRAWER", 4000,
                         "2026-06-09T11:30:00Z", employee_id=emp["id"],
                         txn_ref="T-OLD")
        post_event(store["id"], "HIGH_VALUE_VOID", 50000, "2026-06-10T11:30:00Z",
                   employee_id=emp["id"], txn_ref="T-EDGE")
        # No alert yet: 28.0 (+6.0 if the old event were counted) < 40.00.
        assert list_alert_dicts(make_analyst_headers(ANALYST_1),
                                store_id=store["id"], employee_id=emp["id"]) == []
        post_event(store["id"], "HIGH_VALUE_VOID", 50000, "2026-07-10T11:30:00Z",
                   employee_id=emp["id"], txn_ref="T-NEW")
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert alert["score"] == pytest.approx(56.0, abs=0.001), (
            "only the two in-window events (28.0 + 28.0) aggregate"
        )
        assert alert["event_count"] == 2
        assert alert["status"] == "OPEN"
        old_after = validate_success(
            api.get_exception_event(old["id"], make_analyst_headers(ANALYST_1))
        )
        assert old_after["status"] == "UNAGGREGATED"


class TestAlertEscalationBoundary:
    """Difficulty: exactly-75.00 escalates (inclusive); 74.00 stays OPEN."""

    def _post_group(self, store_id, employee_id, events, register_ref):
        post_events(store_id, events, employee_id=employee_id,
                    register_ref=register_ref)

    def test_alert_escalates_at_exactly_75(self, api):
        """PRD §3.2: "Whenever a score — computed at creation or recomputed on
        attach — reaches 75.00 or more, the alert escalates: the boundary is
        inclusive, so exactly 75.00 escalates, while anything below stays
        `OPEN`."

        E1 accumulates 15.0 + 21.0 + 24.0 = 60.0 (alert created), then 9.0 and
        6.0 attach for a recomputed 75.0 -> ESCALATED.

        Design: Difficulty/boundary_precision_check/alert_escalation_exactly_75_vs_74
        """
        store = make_store(store_number="S200", name="Store 200")
        emp = make_employee(store["id"], employee_ref="E-001", full_name="Emp One")
        self._post_group(store["id"], emp["id"], [
            ("REFUND_NO_RECEIPT", 5000, "2026-07-10T10:00:00Z"),
            ("HIGH_VALUE_VOID", 5000, "2026-07-10T11:00:00Z"),
            ("SWEETHEART_SCAN", 20000, "2026-07-10T12:00:00Z"),
            ("SELF_CHECKOUT_MISMATCH", 4000, "2026-07-10T13:00:00Z"),
            ("NO_SALE_DRAWER", 4000, "2026-07-10T14:00:00Z"),
        ], register_ref="R01")
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert alert["score"] == pytest.approx(75.0, abs=0.001)
        assert alert["status"] == "ESCALATED", "75.00 meets the inclusive threshold"
        assert alert["event_count"] == 5

    def test_alert_stays_open_at_74(self, api):
        """PRD §3.2: "Whenever a score — computed at creation or recomputed on
        attach — reaches 75.00 or more, the alert escalates: the boundary is
        inclusive, so exactly 75.00 escalates, while anything below stays
        `OPEN`."

        E2 accumulates 15.0 + 21.0 + 24.0 = 60.0 (alert created), then 8.0 and
        6.0 attach for a recomputed 74.0 -> stays OPEN, one weighted point
        below the boundary.

        Design: Difficulty/boundary_precision_check/alert_escalation_exactly_75_vs_74
        """
        store = make_store(store_number="S200", name="Store 200")
        emp = make_employee(store["id"], employee_ref="E-002", full_name="Emp Two")
        self._post_group(store["id"], emp["id"], [
            ("REFUND_NO_RECEIPT", 5000, "2026-07-10T10:00:00Z"),
            ("HIGH_VALUE_VOID", 5000, "2026-07-10T11:00:00Z"),
            ("SWEETHEART_SCAN", 20000, "2026-07-10T12:00:00Z"),
            ("PRICE_OVERRIDE", 4000, "2026-07-10T13:00:00Z"),
            ("NO_SALE_DRAWER", 4000, "2026-07-10T14:00:00Z"),
        ], register_ref="R02")
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert alert["score"] == pytest.approx(74.0, abs=0.001)
        assert alert["status"] == "OPEN"


class TestAlertDismissAndConvert:
    def _make_alert_56(self, store_id, employee_id=None):
        """Two HIGH_VALUE_VOID events (40000 + 35000) -> score 56.0 OPEN."""
        post_event(store_id, "HIGH_VALUE_VOID", 40000, "2026-07-12T10:00:00Z",
                   employee_id=employee_id, txn_ref="T1")
        post_event(store_id, "HIGH_VALUE_VOID", 35000, "2026-07-12T11:00:00Z",
                   employee_id=employee_id, txn_ref="T2")
        return the_only_alert(store_id, employee_id=employee_id)

    def test_alert_dismiss_open_by_analyst_releases_events(self, api):
        """PRD §3.2: "An `OPEN` alert may be dismissed by an `LPAnalyst` or an
        `LPManager`; an `ESCALATED` alert can be dismissed only by an
        `LPManager`. Either way the caller supplies a `reason`, which is
        recorded as the alert's `dismiss_reason`, the alert becomes
        `DISMISSED`, and every member event reverts from `AGGREGATED` to
        `UNAGGREGATED`, released for re-aggregation into some future candidate
        set."

        Design: Corner/state_machines/alert_dismiss_open_by_analyst_releases_events
        """
        store = make_store(store_number="S030", name="Store 30")
        emp = make_employee(store["id"], employee_ref="E-300", full_name="Emp 300")
        alert = self._make_alert_56(store["id"], emp["id"])
        resp = api.dismiss_alert(
            alert["id"], {"reason": "Investigated; legitimate voids"},
            make_analyst_headers(ANALYST_1),
        )
        dismissed = validate_success(resp)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["dismiss_reason"] == "Investigated; legitimate voids"
        _events, meta = validate_paginated(api.list_exception_events(
            make_analyst_headers(ANALYST_1),
            params={"store_id": store["id"], "status": "UNAGGREGATED"}))
        assert meta["total_count"] == 2, "both member events released"

    def test_alert_dismiss_escalated_by_analyst_forbidden(self, api):
        """PRD §3.2: "An `OPEN` alert may be dismissed by an `LPAnalyst` or an
        `LPManager`; an `ESCALATED` alert can be dismissed only by an
        `LPManager`."
        PRD §3.2: "Escalation has two consequences: dismissing that alert now
        requires an `LPManager` rather than an analyst, and any case later
        converted from it is born with `priority` HIGH."

        Design: Corner/state_machines/alert_dismiss_escalated_by_analyst_forbidden
        """
        store = make_store(store_number="S031", name="Store 31")
        emp = make_employee(store["id"], employee_ref="E-310", full_name="Emp 310")
        # 28.0 + 24.0 = 52.0 (alert created OPEN), then +24.0 -> 76.0 ESCALATED.
        post_events(store["id"], [
            ("HIGH_VALUE_VOID", 25000, "2026-07-12T10:00:00Z"),
            ("SWEETHEART_SCAN", 30000, "2026-07-12T11:00:00Z"),
            ("SWEETHEART_SCAN", 30000, "2026-07-12T12:00:00Z"),
        ], employee_id=emp["id"])
        alert = the_only_alert(store["id"], employee_id=emp["id"])
        assert alert["score"] == pytest.approx(76.0, abs=0.001)
        assert alert["status"] == "ESCALATED"
        resp = api.dismiss_alert(
            alert["id"], {"reason": "Analyst attempt"},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp = api.dismiss_alert(
            alert["id"], {"reason": "Manager override dismissal"},
            make_manager_headers(MANAGER_1),
        )
        assert validate_success(resp)["status"] == "DISMISSED"

    def test_alert_convert_twice_returns_invalid_state(self, api):
        """PRD §3.2: "The alert must be `OPEN` or `ESCALATED`
        (`ERR_INVALID_STATE_TRANSITION` otherwise), its store must still be
        `ACTIVE` (`ERR_STORE_CLOSED`), and the payload declares a
        `subject_type`."
        PRD §3.2: "`CONVERTED` and `DISMISSED` are terminal."

        Design: Corner/state_machines/alert_convert_twice_returns_invalid_state
        """
        store = make_store(store_number="S032", name="Store 32")
        alert = self._make_alert_56(store["id"])
        resp = api.convert_alert(
            alert["id"], {"subject_type": "EXTERNAL"},
            make_analyst_headers(ANALYST_1),
        )
        validate_success(resp, expected_status=201)
        resp2 = api.convert_alert(
            alert["id"], {"subject_type": "EXTERNAL"},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        _cases, meta = validate_paginated(
            api.list_cases(make_analyst_headers(ANALYST_1),
                           params={"store_id": store["id"]})
        )
        assert meta["total_count"] == 1, "no duplicate case from a second convert"

    def test_subject_mismatch_on_convert(self, api):
        """PRD §3.2: "Declaring `EMPLOYEE` requires that the alert's
        `employee_id` is non-null, that the payload `employee_id` equals it
        exactly, and that the employee is not `TERMINATED` — mismatches fail
        with `ERR_SUBJECT_MISMATCH`, a terminated employee with
        `ERR_EMPLOYEE_NOT_ACTIVE`."
        PRD §2.7: "Existence validation (step 5) proceeds left to right: path
        identifiers are validated first, in the order they appear in the URL,
        and then body-referenced foreign keys in their declared input order."

        A bogus (nonexistent) employee_id fails existence (step 5) before the
        subject-consistency gate; the exact employee_id then converts.

        Design: Corner/validations/subject_mismatch_on_convert
        """
        store = make_store(store_number="S063", name="Store 63")
        emp = make_employee(store["id"], employee_ref="E-630", full_name="Emp 630")
        alert = self._make_alert_56(store["id"], emp["id"])
        resp_missing = api.convert_alert(
            alert["id"],
            {"subject_type": "EMPLOYEE", "employee_id": NON_EXISTENT_UUID},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp_missing, ApiErrorId.ERR_NOT_FOUND)
        resp_ok = api.convert_alert(
            alert["id"], {"subject_type": "EMPLOYEE", "employee_id": emp["id"]},
            make_analyst_headers(ANALYST_1),
        )
        case = validate_success(resp_ok, expected_status=201)
        assert case["subject_type"] == "EMPLOYEE"
        assert case["source"] == "ALERT"
        assert case["employee_id"] == emp["id"]


class TestAlertFiltering:
    def test_list_filter_alerts_by_min_score(self, api):
        """PRD §3.2: "Alerts support list filtering by `store_id`,
        `employee_id`, `case_id`, `status`, `subject_type`, and `min_score`,
        and a detail read by `alert_id`; events likewise list by `store_id`,
        `employee_id`, `status`, and `exception_type`, with a detail read by
        `event_id`."

        min_score is an inclusive minimum: the 56.0 alert matches
        min_score=56.0 but not 56.01.

        Design: Corner/endpoints/list_filter_alerts_by_min_score
        """
        store = make_store(store_number="S213", name="Store 213")
        post_event(store["id"], "HIGH_VALUE_VOID", 40000, "2026-07-12T10:00:00Z",
                   txn_ref="T1")
        post_event(store["id"], "HIGH_VALUE_VOID", 35000, "2026-07-12T11:00:00Z",
                   txn_ref="T2")
        headers = make_analyst_headers(ANALYST_1)
        _d, meta_in = validate_paginated(api.list_alerts(
            headers, params={"store_id": store["id"], "min_score": 56.0}))
        assert meta_in["total_count"] == 1
        d_out, meta_out = validate_paginated(api.list_alerts(
            headers, params={"store_id": store["id"], "min_score": 56.01}))
        assert meta_out["total_count"] == 0 and d_out == []
