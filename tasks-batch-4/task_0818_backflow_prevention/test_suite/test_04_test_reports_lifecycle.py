"""Test-report result computation, accept/reject branching, and adjudication lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/relief_differential_exactly_at_threshold_passes
# --------------------------------------------------------------------------- #
def test_rp_result_pass_at_exact_thresholds(api):
    """PRD §3.3: "For an `RP` device, the result is `PASS` only when the relief-valve
    differential is at least 2.0 psid and the first check valve holds at least 1.0 psid."
    PRD §2.8: "a reading exactly equal to a threshold satisfies it (the comparisons are
    inclusive)."

    Design: Difficulty/boundary_precision_check/relief_differential_exactly_at_threshold_passes
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=2.0, check_valve_1_psid=1.0)
    assert report["result"] == "PASS", \
        f"relief 2.0 == threshold and check1 1.0 == threshold, both inclusive -> PASS, got {report['result']}"


def test_rp_result_fail_just_below_relief_threshold(api):
    """PRD §3.3: "For an `RP` device, the result is `PASS` only when the relief-valve
    differential is at least 2.0 psid and the first check valve holds at least 1.0 psid."
    PRD §3.3: "Any reading below its threshold makes the result `FAIL`."

    Design: Difficulty/boundary_precision_check/relief_differential_exactly_at_threshold_passes
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=1.99, check_valve_1_psid=1.0)
    assert report["result"] == "FAIL", \
        f"relief 1.99 < 2.0 threshold -> FAIL, got {report['result']}"


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/test_report_branch_accept_vs_reject
# --------------------------------------------------------------------------- #
def test_reject_report_stores_reason_and_sets_rejected(api):
    """PRD §3.3: "Rejecting a submitted report instead moves it from `SUBMITTED` to
    `REJECTED` and requires a `rejection_reason`, which is stored on the report".

    Design: Difficulty/non_linear_state_machine/test_report_branch_accept_vs_reject
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    data = validate_success(api.reject_report(report["id"],
                                              {"rejection_reason": "gauge reading illegible"}, ADMIN))
    assert data["status"] == "REJECTED", f"got {data['status']}"
    assert data["rejection_reason"] == "gauge reading illegible", \
        f"got {data['rejection_reason']}"


def test_reject_report_leaves_device_untouched(api):
    """PRD §3.3: "A rejection changes no device or connection state — it neither updates due
    dates nor touches posture, notices, or counts."
    PRD §3.1: "A new device starts with its `status` field set to `ACTIVE` and its
    `last_pass_date` unset (it has no accepted passing test yet)."

    Design: Difficulty/non_linear_state_machine/test_report_branch_accept_vs_reject
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    fixtures.reject_report(report["id"], "gauge reading illegible", api, ADMIN)
    data = validate_success(api.get_device(dev["id"], ADMIN))
    assert data["last_pass_date"] in (None, ""), \
        f"REJECTED branch must not set last_pass_date, got {data['last_pass_date']}"


# --------------------------------------------------------------------------- #
# Corner/state_machines/accept_already_accepted_report_returns_report_not_pending
# --------------------------------------------------------------------------- #
def test_accept_already_accepted_report_returns_not_pending(api):
    """PRD §3.3: "Adjudicating a report that is not in `SUBMITTED` status — whether accept
    or reject — is rejected with `ERR_REPORT_NOT_PENDING`."

    Design: Corner/state_machines/accept_already_accepted_report_returns_report_not_pending
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    fixtures.accept_report(report["id"], api, ADMIN)
    validate_error(api.accept_report(report["id"], ADMIN), ApiErrorId.ERR_REPORT_NOT_PENDING)
