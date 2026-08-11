"""Resource temporal overlap (PRD §3.3, §3.9): half-open mandatory event
windows vs closed statement coverage intervals.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_security, make_event_source, make_scrubbed_event,
    split_terms, create_source_notification_payload,
)
from test_helpers.fixtures import ADMIN, VENDOR, ANALYST_1, CUSTODIAN
from test_helpers import api_client


class TestMandatoryEventHalfOpenWindowAdjacency:
    def _setup_ev1(self):
        sec = make_security(ticker="ACME")
        s1 = make_event_source(name="Vendor Alpha", source_type="VENDOR",
                               reliability_weight=10)
        s2 = make_event_source(name="Vendor Beta", source_type="VENDOR",
                               reliability_weight=5)
        ev1, _, _ = make_scrubbed_event(
            sec["id"], "SPLIT", split_terms(),
            record_date="2026-05-15", payable_date="2026-05-29",
            source_a=s1, source_b=s2)
        return sec, s1, s2, ev1

    def _push_pair_and_scrub(self, sec_id, s1, s2, event_type, terms,
                             record_date, payable_date):
        n1 = get_success_data(api_client.create_source_notification(
            create_source_notification_payload(
                source_id=s1["id"], security_id=sec_id, event_type=event_type,
                record_date=record_date, announced_terms=terms), VENDOR))
        n2 = get_success_data(api_client.create_source_notification(
            create_source_notification_payload(
                source_id=s2["id"], security_id=sec_id, event_type=event_type,
                record_date=record_date, announced_terms=terms), VENDOR))
        return api_client.create_event(
            {"security_id": sec_id, "event_type": event_type, "terms": terms,
             "record_date": record_date, "payable_date": payable_date,
             "source_notification_ids": [n1["id"], n2["id"]]},
            ANALYST_1)

    def test_touching_window_accepted(self, api):
        """PRD §3.3: "a mandatory event — one with `election_required` false — must not collide with another live mandatory event on the same security: their half-open windows, from `record_date` inclusive to `payable_date` exclusive, must not overlap, though windows that merely touch at an endpoint are allowed."

        Design: Difficulty/resource_temporal_overlap/mandatory_event_half_open_window_adjacency
        """
        sec, s1, s2, ev1 = self._setup_ev1()
        terms2 = split_terms(ratio_num=11, ratio_den=10,
                             price_per_share_cents=1000,
                             fractional_policy="ROUND_DOWN")
        # EV2 record == EV1 payable: touching endpoints, allowed.
        resp = self._push_pair_and_scrub(
            sec["id"], s1, s2, "STOCK_DIVIDEND", terms2,
            record_date="2026-05-29", payable_date="2026-06-05")
        ev2 = validate_success(resp, 201)
        assert ev2["status"] == "DRAFT"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "A collision is rejected with `ERR_EVENT_WINDOW_OVERLAP` (HTTP 409)." and "their half-open windows, from `record_date` inclusive to `payable_date` exclusive, must not overlap".

        Design: Difficulty/resource_temporal_overlap/mandatory_event_half_open_window_adjacency
        """
        sec, s1, s2, ev1 = self._setup_ev1()
        terms3 = split_terms(ratio_num=3, ratio_den=1)
        # EV3 record 2026-05-20 < EV1 payable 2026-05-29: true overlap.
        resp = self._push_pair_and_scrub(
            sec["id"], s1, s2, "SPLIT", terms3,
            record_date="2026-05-20", payable_date="2026-06-02")
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)


class TestStatementCoverageClosedIntervalSharedDay:
    def test_shared_day_conflicts_and_day_after_accepted(self, api):
        """PRD §3.9: "The coverage window is a closed interval, inclusive of
        both days" and "two statements from the same source must not share even a single day; an overlapping submission is rejected with `ERR_STATEMENT_COVERAGE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/statement_coverage_closed_interval_shared_day
        """
        cust = make_event_source(name="Custodian Prime", source_type="CUSTODIAN",
                                 reliability_weight=20)
        st1 = validate_success(api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-05-01",
             "coverage_end_date": "2026-05-31", "lines": []},
            CUSTODIAN), 201)
        # [2026-05-31, 2026-06-15] shares 2026-05-31 with S1 -> conflict.
        resp = api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-05-31",
             "coverage_end_date": "2026-06-15", "lines": []},
            CUSTODIAN)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_COVERAGE_OVERLAP)
        # [2026-06-01, 2026-06-15] shares no day -> accepted.
        st3 = validate_success(api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-06-01",
             "coverage_end_date": "2026-06-15", "lines": []},
            CUSTODIAN), 201)
        assert st3["status"] == "RECONCILED"

    def test_shared_single_day_is_a_conflict(self, api):
        """PRD §3.9: "two statements from the same source must not share even a single day; an overlapping submission is rejected with `ERR_STATEMENT_COVERAGE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/statement_coverage_closed_interval_shared_day
        """
        cust = make_event_source(name="Custodian Prime", source_type="CUSTODIAN",
                                 reliability_weight=20)
        validate_success(api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-05-01",
             "coverage_end_date": "2026-05-31", "lines": []},
            CUSTODIAN), 201)
        resp = api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-05-31",
             "coverage_end_date": "2026-05-31", "lines": []},
            CUSTODIAN)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_STATEMENT_COVERAGE_OVERLAP"
        assert resp.status_code == 409
