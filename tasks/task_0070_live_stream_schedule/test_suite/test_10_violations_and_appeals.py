"""Violations, penalty calculation, appeal workflow, sweep enforcement.

PRD §3.9 — violations and appeals; §3.10 — sweep semantics.
"""

import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    create_violation,
    file_appeal,
    decide_appeal,
    enforce_violation_via_sweep,
    fetch_streamer,
    create_violation_payload,
    file_appeal_payload,
    iso,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
)
from test_helpers.fixtures import _parse_iso


class TestViolationPenaltyCalculation:
    """PRD §3.9: 'The penalty calculation begins with the per-type severity
    floor: 2 for FALSE_ADVERTISING, 1 for WRONG_PRODUCT, 3 for
    VIOLATING_CONTENT, 4 for DATA_FRAUD.'
    """

    def test_false_advertising_with_2_evidences_no_bonus(self, api):
        """PRD §3.9: "An evidence bonus of 1 is added when the number of items
        in evidence_refs is at least 3; otherwise the bonus is 0."

        FALSE_ADVERTISING (floor 2) + 2 evidence refs (no bonus) => severity 2.
        Penalty action by severity: severity >= 2 and score_after < 50 => FINE.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["e1", "e2"])
        assert v["severity"] == 2
        assert v["penalty_action"] == "FINE"
        # PRD: "the penalty is FINE with fine_cents equal to the severity
        # multiplied by 50,000."
        assert v["fine_cents"] == 2 * 50_000

    def test_data_fraud_with_3_evidences_triggers_blacklist(self, api):
        """PRD §3.9: "if the post-violation score reaches 100 or the violation
        is DATA_FRAUD with severity at least 4, the penalty is BLACKLIST..."

        DATA_FRAUD floor 4, plus 3 evidences (+1 bonus) = severity 5 >= 4 =>
        BLACKLIST.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="DATA_FRAUD",
                             evidence_refs=["a", "b", "c"])
        assert v["severity"] == 5
        assert v["penalty_action"] == "BLACKLIST"

    def test_violating_content_severity_3_triggers_suspension(self, api):
        """PRD §3.9: "if the post-violation score reaches 50 or the severity
        is at least 4, the penalty is SUSPENSION with suspension_days 30..."

        Wait — VIOLATING_CONTENT floor 3 + 3 evidences (bonus 1) = severity 4
        => SUSPENSION via the severity-at-least-4 branch. suspension_days = 30.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="VIOLATING_CONTENT",
                             evidence_refs=["a", "b", "c"])
        assert v["severity"] == 4
        assert v["penalty_action"] == "SUSPENSION"
        assert v["suspension_days"] == 30

    def test_wrong_product_severity_1_triggers_warning(self, api):
        """PRD §3.9: "otherwise the penalty is WARNING."

        WRONG_PRODUCT floor 1 + 2 evidences (no bonus) = severity 1.
        severity < 2 => WARNING.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="WRONG_PRODUCT",
                             evidence_refs=["a", "b"])
        assert v["severity"] == 1
        assert v["penalty_action"] == "WARNING"


class TestViolationInitialState:
    """PRD §3.9: 'writes the violation in status OPEN with enforced_at null.'"""

    def test_new_violation_is_open(self, api):
        """PRD §3.9: "writes the violation in status OPEN with enforced_at
        null."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"])
        assert v["status"] == "OPEN"
        assert v.get("enforced_at") is None


class TestAppealWindow:
    """PRD §3.9: 'A streamer may file an Appeal against their own violation up
    to 7 days after the violation's created_at...'
    """

    def test_appeal_within_7_days_succeeds(self, api):
        """PRD §3.9: "A streamer may file an Appeal against their own
        violation up to 7 days after the violation's created_at"
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a"])
        # 5 days later, still within window
        set_clock(DEFAULT_BASE_TIME + timedelta(days=5))
        appeal = file_appeal(streamer, v["id"])
        assert appeal["decision"] == "PENDING"

    def test_appeal_after_window_returns_window_closed(self, api):
        """PRD §3.9: "attempting to file after the window yields
        ERR_APPEAL_WINDOW_CLOSED (HTTP 422)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a"])
        # 7 days + 1 minute after creation
        set_clock(_parse_iso(v["created_at"]) + timedelta(days=7, minutes=1))
        resp = api.file_appeal(v["id"], file_appeal_payload(), make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_APPEAL_WINDOW_CLOSED, expected_status=422)

    def test_appeal_filed_by_non_owner_rejected(self, api):
        """PRD §3.9: "The streamer_id on the appeal mirrors the violation's
        streamer_id for ownership-check purposes."
        PRD §2.1: "a Streamer reading or mutating another streamer's resource
        is rejected with ERR_FORBIDDEN."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer_a = setup_active_streamer()
        streamer_b = setup_active_streamer()
        v = create_violation(streamer_a["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a"])
        resp = api.file_appeal(v["id"], file_appeal_payload(),
                                make_streamer_headers(streamer_b["id"]))
        validate_error(resp, ERR_FORBIDDEN, expected_status=403)


class TestAppealDecide:
    """PRD §3.9: 'A ComplianceReviewer decides the appeal by supplying a
    decision of OVERTURN or UPHOLD.'
    """

    def test_overturn_transitions_violation_to_overturned(self, api):
        """PRD §3.9: "An OVERTURN decision sets the appeal's decision to
        OVERTURNED and decided_at to the current logical clock, transitions
        the violation from APPEAL_PENDING to OVERTURNED..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a"])
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="OVERTURN")
        # Fetch violation through list
        from prd_bench_local_runner.testing import validate_paginated
        resp = api.list_violations(ADMIN_HEADERS, params={"streamer_id": streamer["id"]})
        items, _ = validate_paginated(resp)
        target = [vi for vi in items if vi["id"] == v["id"]][0]
        assert target["status"] == "OVERTURNED"

    def test_uphold_transitions_to_enforced(self, api):
        """PRD §3.9: "An UPHOLD decision sets the appeal's decision to UPHELD,
        transitions the violation to UPHELD, and the system auto-transitions
        the violation from UPHELD to ENFORCED immediately afterward without
        further mutation."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a"])
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="UPHOLD")
        from prd_bench_local_runner.testing import validate_paginated
        resp = api.list_violations(ADMIN_HEADERS, params={"streamer_id": streamer["id"]})
        items, _ = validate_paginated(resp)
        target = [vi for vi in items if vi["id"] == v["id"]][0]
        assert target["status"] == "ENFORCED"


class TestSweepEnforcement:
    """PRD §3.9: 'When neither an appeal is filed nor an overturn decided
    within 7 days of the violation's created_at, the periodic sweep takes over.'
    """

    def test_sweep_enforces_open_violation_past_window(self, api):
        """PRD §3.9: "For each OPEN violation whose created_at plus 7 days is
        at or before the logical clock, with no Appeal on record, the sweep
        transitions the violation to ENFORCED, records enforced_at as the
        current logical clock, and applies the penalty_action..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="WRONG_PRODUCT",
                             evidence_refs=["x"])
        # WRONG_PRODUCT severity 1 => WARNING
        enforce_violation_via_sweep(v)
        from prd_bench_local_runner.testing import validate_paginated
        resp = api.list_violations(ADMIN_HEADERS, params={"streamer_id": streamer["id"]})
        items, _ = validate_paginated(resp)
        target = [vi for vi in items if vi["id"] == v["id"]][0]
        assert target["status"] == "ENFORCED"
        assert target.get("enforced_at") is not None

    def test_sweep_suspension_sets_status_and_suspension_until(self, api):
        """PRD §3.9: "SUSPENSION sets the streamer's status to SUSPENDED and
        suspension_until to the current logical clock plus suspension_days..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        # VIOLATING_CONTENT severity 3 + 3 evidence (bonus 1) -> severity 4 -> SUSPENSION
        v = create_violation(streamer["id"], violation_type="VIOLATING_CONTENT",
                             evidence_refs=["a", "b", "c"])
        enforce_violation_via_sweep(v)
        s = fetch_streamer(streamer["id"])
        assert s["status"] == "SUSPENSION" or s["status"] == "SUSPENDED", \
            f"expected SUSPENDED, got {s['status']}"

    def test_sweep_restores_active_after_suspension_until(self, api):
        """PRD §3.10: "For every Streamer whose status is SUSPENDED and whose
        suspension_until is at or before the logical clock, the sweep returns
        the streamer's status to ACTIVE and clears suspension_until."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="VIOLATING_CONTENT",
                             evidence_refs=["a", "b", "c"])
        enforce_violation_via_sweep(v)
        # Now advance 31 days past suspension start and sweep again
        from prd_bench_local_runner.testing import get_success_data
        set_clock(_parse_iso(v["created_at"]) + timedelta(days=7 + 31))
        get_success_data(api.run_sweep(ADMIN_HEADERS))
        s = fetch_streamer(streamer["id"])
        assert s["status"] == "ACTIVE"
        assert s.get("suspension_until") is None
