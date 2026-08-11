"""Writ lifecycle: issue/expire/re-request cycle, execute cascade (PRD 3.7).

Writ expiry tests read expires_on from the issued writ's response at runtime
(the PRD pins the computation — "issued_at plus the jurisdiction's writ
validity period" — but not the day count), then advance the logical clock
past it. Scheduling-window tests likewise derive bounds from expires_on.
"""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    assert_instant_equal,
    create_writ_payload,
    get_case,
    get_judgment,
    get_storage_record,
    get_tenancy,
    get_unit,
    get_writ,
    make_deputy_headers,
    make_landlord_headers,
    request_and_issue_writ,
    run_ops,
    set_clock,
    setup_executed_with_storage,
    setup_judgment_final,
    setup_writ_issued,
    setup_writ_scheduled,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _one_second_after(iso_ts: str) -> str:
    from datetime import datetime, timedelta, timezone

    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestWritIssueExpireRerequestCycle:
    """Depth instance: Writ ISSUED -> EXPIRED (ops run) -> new REQUESTED ->
    ISSUED; the case falls back to JUDGMENT_ENTERED on expiry."""

    def test_expiry_reverts_case_and_allows_new_writ(self, api):
        """PRD 3.7: "Should an ISSUED writ sit past its expires_on, the sweep
        instead moves it to the terminal EXPIRED and drops the case back to
        JUDGMENT_ENTERED, where the landlord may request a fresh writ."

        Design: Difficulty/non_linear_state_machine/writ_issue_expire_rerequest_cycle
        """
        ctx = setup_writ_issued("CA")
        w1 = ctx["writ"]
        assert w1["status"] == "ISSUED"
        expires_on = w1["expires_on"]
        assert expires_on is not None

        set_clock(_one_second_after(expires_on))
        summary = run_ops()
        assert summary["writs_expired"] == 1

        assert get_writ(w1["id"])["status"] == "EXPIRED"
        assert get_case(ctx["case"]["id"])["status"] == "JUDGMENT_ENTERED"

        # The landlord may request a fresh writ on the same judgment.
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll)
        w2 = validate_success(resp, 201)
        assert w2["status"] == "REQUESTED"
        w2 = validate_success(api.issue_writ(w2["id"], CLERK_A), 200)
        assert w2["status"] == "ISSUED"
        # The fresh writ gets its own validity window computed at issuance.
        assert w2["expires_on"] > w2["issued_at"]

    def test_issued_sets_issued_at_and_expires_on(self, api):
        """PRD 3.7: "Issuance stamps issued_at and computes expires_on as the
        issuance instant plus the jurisdiction's writ validity period; the
        writ becomes ISSUED and the case advances from JUDGMENT_ENTERED to
        WRIT_ISSUED."

        Design: Difficulty/non_linear_state_machine/writ_issue_expire_rerequest_cycle
        """
        ctx = setup_judgment_final("CA")
        writ = request_and_issue_writ(ctx)
        assert writ["status"] == "ISSUED"
        assert writ["issued_at"] is not None
        assert writ["expires_on"] is not None
        assert get_case(ctx["case"]["id"])["status"] == "WRIT_ISSUED"


class TestLockoutExecuteCascadeDepth3:
    """Depth instance: execute -> case EXECUTED -> tenancy ENDED -> unit
    VACANT, plus the storage record created on link 1."""

    def test_execute_cascades_through_case_tenancy_unit(self, api):
        """PRD 3.7: "On execution the writ becomes EXECUTED with executed_at
        stamped, and a PropertyStorageRecord springs into existence in STORED
        status ... The cascade then runs (§2.10): the case moves from
        LOCKOUT_SCHEDULED to the terminal EXECUTED, the tenancy moves from
        ACTIVE to ENDED with ended_at stamped, and the unit returns from
        OCCUPIED to VACANT."

        Design: Difficulty/transitive_cascade/lockout_execute_cascade_depth3
        """
        ctx = setup_executed_with_storage("CA", items_summary="two sofas, boxes")
        writ = ctx["writ"]
        assert writ["status"] == "EXECUTED"
        assert_instant_equal(writ["executed_at"], "2026-06-26T09:00:00Z")

        storage = ctx["storage"]
        assert storage["status"] == "STORED"
        assert storage["writ_id"] == writ["id"]

        assert get_case(ctx["case"]["id"])["status"] == "EXECUTED"
        tenancy = get_tenancy(ctx["tenancy"]["id"])
        assert tenancy["status"] == "ENDED"
        assert_instant_equal(tenancy["ended_at"], "2026-06-26T09:00:00Z")
        assert get_unit(ctx["unit"]["id"])["status"] == "VACANT"

    def test_execute_stamps_jurisdiction_storage_terms(self, api):
        """PRD 3.7: "The record's daily_fee_cents is 1500 in CA, 1000 in TX,
        and 800 in OH, and its billing_mode is CALENDAR_INCLUSIVE in CA but
        ELAPSED_24H in TX and OH."

        Design: Difficulty/transitive_cascade/lockout_execute_cascade_depth3
        """
        ctx = setup_executed_with_storage("CA")
        storage = get_storage_record(ctx["storage"]["id"])
        assert storage["daily_fee_cents"] == 1500
        assert storage["billing_mode"] == "CALENDAR_INCLUSIVE"
        assert_instant_equal(storage["stored_at"], "2026-06-26T09:00:00Z")
        # disposal_eligible_on = stored_at + CA 15 days.
        assert_instant_equal(
            storage["disposal_eligible_on"], "2026-07-11T09:00:00Z")
