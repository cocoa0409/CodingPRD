"""Role authorisation, resource ownership, and segregation of duties (PRD §2.1, §3.7)."""

from test_helpers import (
    ApiErrorId,
    create_alert,
    create_confirmed_fraud_alert,
    create_specialist,
    create_verified_subscriber,
    expense,
    get_claim,
    get_specialist,
    get_subscriber,
    make_admin_headers,
    make_role_only_headers,
    make_specialist_headers,
    make_subscriber_headers,
    setup_approved_claim,
    setup_in_progress_case,
    validate_error,
    validate_success,
)


class TestRoleAuthorisation:
    def test_a_subscriber_may_not_escalate_their_own_confirmed_fraud_alert(self, api):
        """PRD §2.1: "Once the caller is authenticated, the acting role must additionally appear in
        the authorised-role list of the endpoint being called (see §4); a role acting outside its
        remit is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.5: "An administrator may **escalate** a confirmed-fraud alert, moving it
        `CONFIRMED_FRAUD → ESCALATED`; escalation is covered in detail below."

        Design: Corner/rbac/subscriber_cannot_escalate_alert
        """
        _, subscriber = create_verified_subscriber(full_name="Role Test", ssn_last4="5050")
        sub_headers = make_subscriber_headers(subscriber["id"])
        alert, _case = create_confirmed_fraud_alert(
            subscriber["id"],
            alert_type="SSN_TRACE",
            severity="MEDIUM",
            source_detail="ssn hit",
        )

        resp = api.escalate_alert(alert["id"], sub_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        after = validate_success(api.get_alert(alert["id"], sub_headers))
        assert after["status"] == "CONFIRMED_FRAUD"
        assert after["escalation_tier"] is None

    def test_a_subscriber_role_without_an_x_user_id_is_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is absent or is not one of these five is
        rejected with `ERR_UNAUTHENTICATED`. `X-User-ID` is mandatory for every role except
        `Anonymous`; if it is missing for any of the other four roles, the same
        `ERR_UNAUTHENTICATED` rejection applies."

        Design: Corner/rbac/subscriber_read_missing_x_user_id_returns_unauthenticated
        """
        _, subscriber = create_verified_subscriber(full_name="No Id", ssn_last4="5555")

        headers = make_role_only_headers("Subscriber")
        assert "X-User-ID" not in headers

        resp = api.get_subscriber(subscriber["id"], headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestResourceOwnership:
    def test_a_subscriber_may_not_read_another_households_alert(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a Subscriber compare the
        resource's owning-subscriber reference to `X-User-ID` — directly for the subscriber record
        itself, through `subscriber_id` for family members, bureau profiles, alerts, restoration
        cases, insurance claims and wallet items, and through the owning bureau profile's
        `subscriber_id` for thaw windows. A `Subscriber` reaching for another household's resource
        is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/subscriber_cannot_read_another_subscribers_alerts
        """
        plan, owner = create_verified_subscriber(full_name="Owner A", ssn_last4="5151")
        _, intruder = create_verified_subscriber(
            plan=plan, full_name="Intruder B", ssn_last4="5252"
        )
        alert = create_alert(
            owner["id"], alert_type="DARK_WEB", severity="LOW", source_detail="A's leak"
        )

        resp = api.get_alert(alert["id"], make_subscriber_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        mine = validate_success(
            api.get_alert(alert["id"], make_subscriber_headers(owner["id"]))
        )
        assert mine["id"] == alert["id"], "the owner reads the very same alert successfully"

    def test_a_specialist_may_not_resolve_a_case_assigned_to_someone_else(self, api):
        """PRD §2.1: "When `X-User-Role` is `RestorationSpecialist`, `X-User-ID` is the `id` of the
        acting Specialist. For actions on a restoration case, `X-User-ID` must equal that case's
        `specialist_id`; for booking a work window, `X-User-ID` must equal the `specialist_id` named
        in the booking. A specialist reaching for a case that is not theirs is likewise rejected
        with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/specialist_cannot_resolve_case_assigned_to_another_specialist
        """
        ctx = setup_in_progress_case(
            specialist_overrides={"full_name": "Spec One", "tier": "TIER2", "max_caseload": 3},
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM"},
            window_start="2026-05-26T09:00:00Z",
            window_end="2026-05-26T11:00:00Z",
        )
        assigned_specialist = ctx["specialist"]
        outsider = create_specialist(full_name="Spec Two", tier="TIER2", max_caseload=3)

        resp = api.resolve_case(
            ctx["case"]["id"],
            {"resolution_summary": "Stealing someone else's case"},
            make_specialist_headers(outsider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        case = validate_success(
            api.get_restoration_case(
                ctx["case"]["id"], make_specialist_headers(assigned_specialist["id"])
            )
        )
        assert case["status"] == "IN_PROGRESS"
        assert case["specialist_id"] == assigned_specialist["id"]

        assert get_specialist(assigned_specialist["id"])["active_case_count"] == 1
        assert get_specialist(outsider["id"])["active_case_count"] == 0


class TestSegregationOfDuties:
    def test_the_approving_operator_may_not_also_pay_the_claim(self, api):
        """PRD §3.7: "An `APPROVED` claim is disbursed, carrying it `APPROVED → PAID`, but only if
        the paying administrator's `X-User-ID` differs from the `approved_by_user_id` stored on the
        claim. An operator attempting to pay a claim they themselves approved is refused with
        `ERR_SEGREGATION_OF_DUTIES` — the same human may not both authorise and disburse."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_approve_then_pay
        """
        ctx = setup_approved_claim(
            expenses=[expense("LEGAL_FEES", 50000, True)],
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM",
                             "source_detail": "ssn hit"},
            adjuster_user_id="ops-7",
        )
        assert ctx["claim"]["approved_by_user_id"] == "ops-7"
        assert ctx["claim"]["approved_cents"] == 47500

        resp = api.pay_claim(ctx["claim"]["id"], make_admin_headers("ops-7"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_claim(ctx["claim"]["id"])["status"] == "APPROVED", "the claim is untouched"

        paid = validate_success(
            api.pay_claim(ctx["claim"]["id"], make_admin_headers("ops-8"))
        )
        assert paid["status"] == "PAID", "a different operator id disburses it fine"

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["insurance_remaining_cents"] == 452500