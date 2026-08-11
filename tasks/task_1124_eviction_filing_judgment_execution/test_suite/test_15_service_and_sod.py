"""Service of process and segregation-of-duties corners (PRD 3.4, 2.9)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    assert_instant_equal,
    create_service_attempt_payload,
    get_case,
    make_landlord_headers,
    make_process_server_headers,
    serve_all_defendants,
    set_clock,
    setup_case_filed,
    setup_case_hearing_concluded,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestServiceCompletionDefendantSet:
    """Corner instance: only SERVED attempts on distinct named defendants
    count; FAILED adds nothing; the completing SERVED flips the case."""

    def test_failed_then_partial_then_complete(self, api):
        """PRD 3.4: "The case accumulates the distinct names with a SERVED
        attempt in served_defendant_names; FAILED attempts add nothing. A
        SERVED attempt that does not complete the set leaves the case in
        FILED; at the moment the served set covers every name in the accepted
        package's defendant_names ... the case advances from FILED to
        SERVICE_COMPLETE, and service_completed_at is set to the served_at of
        the completing attempt."

        Design: Corner/calculations/service_completion_defendant_set
        """
        ctx = setup_case_filed("CA", defendant_names=["D1", "D2"])
        set_clock("2026-06-01T11:00:00Z")
        ps = make_process_server_headers("ps-1")

        # FAILED attempt on D1 adds nothing.
        failed = validate_success(api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="D1", result="FAILED",
                                           served_at="2026-06-01T10:00:00Z"),
            ps), 201)
        assert failed["result"] == "FAILED"
        assert get_case(ctx["case"]["id"])["status"] == "FILED"

        # SERVED on D1: set not complete -> still FILED.
        validate_success(api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="D1", result="SERVED",
                                           method="SUBSTITUTED",
                                           served_at="2026-06-01T10:30:00Z"),
            ps), 201)
        assert get_case(ctx["case"]["id"])["status"] == "FILED"

        # SERVED on D2 completes the set. served_at must not lie in the
        # future relative to the logical clock (PRD 3.4), so advance the
        # clock to the attempt's instant first.
        set_clock("2026-06-02T09:00:00Z")
        validate_success(api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="D2", result="SERVED",
                                           served_at="2026-06-02T09:00:00Z"),
            ps), 201)
        case = get_case(ctx["case"]["id"])
        assert case["status"] == "SERVICE_COMPLETE"
        assert_instant_equal(
            case["service_completed_at"], "2026-06-02T09:00:00Z")
        assert sorted(case["served_defendant_names"]) == ["D1", "D2"]


class TestServiceDefendantValidation:
    """Corner instance: unknown defendant and duplicate SERVED rejected."""

    def test_unknown_then_duplicate_served(self, api):
        """PRD 3.4: "the named defendant_name must be one of the
        defendant_names on the case's ACCEPTED package (ERR_DEFENDANT_UNKNOWN,
        HTTP 422), and a defendant who already has a SERVED attempt on the
        case may not be served again (ERR_DEFENDANT_ALREADY_SERVED,
        HTTP 409)."

        Design: Corner/validations/service_defendant_validation
        """
        ctx = setup_case_filed("CA", defendant_names=["D1", "D2"])
        set_clock("2026-06-01T11:00:00Z")
        ps = make_process_server_headers("ps-1")

        resp1 = api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="Nobody",
                                           served_at="2026-06-01T10:00:00Z"),
            ps)
        validate_error(resp1, ApiErrorId.ERR_DEFENDANT_UNKNOWN, 422)

        validate_success(api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="D1",
                                           served_at="2026-06-01T10:00:00Z"),
            ps), 201)

        resp2 = api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="D1",
                                           method="SUBSTITUTED",
                                           served_at="2026-06-01T10:05:00Z"),
            ps)
        validate_error(resp2, ApiErrorId.ERR_DEFENDANT_ALREADY_SERVED, 409)


class TestSodPartyCannotServe:
    """Corner instance: the case landlord may not record service."""

    def test_landlord_id_as_server_rejected(self, api):
        """PRD 3.4: "a recorder whose X-User-ID equals the case's landlord_id
        is rejected with ERR_SOD_PARTY_CANNOT_SERVE."

        Design: Corner/validations/sod_party_cannot_serve
        """
        ctx = setup_case_filed("CA")
        set_clock("2026-06-01T11:00:00Z")
        # ProcessServer role but X-User-ID equal to the landlord's id.
        party_server = make_process_server_headers(ctx["landlord"]["id"])
        resp = api.create_service_attempt(
            ctx["case"]["id"],
            create_service_attempt_payload(defendant_name="Dee A",
                                           served_at="2026-06-01T10:00:00Z"),
            party_server,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_PARTY_CANNOT_SERVE, 403)


class TestSodFeeJudgmentSameClerk:
    """Corner instance: the fee-accepting clerk may not enter the judgment."""

    def test_same_clerk_rejected_different_clerk_succeeds(self, api):
        """PRD 3.6: "the entering clerk must differ from the
        accepted_by_clerk_id recorded when the filing fee was accepted
        (ERR_SOD_FEE_JUDGMENT)."

        Design: Corner/validations/sod_fee_judgment_same_clerk
        """
        from test_helpers import make_clerk_headers

        ctx = setup_case_hearing_concluded("CA")
        payload = {"possession_granted": True, "rent_awarded_cents": 50000,
                   "damages_cents": 0, "late_fee_cents": 0,
                   "court_costs_cents": 0,
                   "oldest_unpaid_due_date": "2026-06-01"}
        # clerk-a accepted the package in the fixture.
        resp = api.enter_judgment(
            ctx["case"]["id"], payload, make_clerk_headers("clerk-a"))
        validate_error(resp, ApiErrorId.ERR_SOD_FEE_JUDGMENT, 409)

        ok = api.enter_judgment(
            ctx["case"]["id"], payload, make_clerk_headers("clerk-b"))
        assert validate_success(ok, 201)["status"] == "ENTERED"


class TestServedDateInFutureRejected:
    """Corner instance: served_on after the logical clock's date fails."""

    def test_future_served_on_rejected(self, api):
        """PRD 3.2: "The payload carries the served_on calendar date, which
        must not lie in the future relative to the logical clock
        (ERR_DATE_IN_FUTURE, HTTP 422)".

        Design: Corner/validations/served_date_in_future_rejected
        """
        from test_helpers import setup_case_draft

        ctx = setup_case_draft("CA")
        set_clock("2026-05-02T08:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        case = get_case(ctx["case"]["id"])
        resp = api.create_notice(
            case["id"],
            {"notice_type": "PAY_OR_QUIT", "served_on": "2026-05-03",
             "claimed_rent_owed_cents": 100000,
             "expected_case_version": case["version"]},
            ll,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_IN_FUTURE, 422)
