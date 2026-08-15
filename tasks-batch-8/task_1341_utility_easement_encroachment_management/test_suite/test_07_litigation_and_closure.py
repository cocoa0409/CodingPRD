"""Litigation referral cascades into case closure, and the closure gate."""
from test_helpers import (
    DEPARTMENT_DIRECTOR,
    LITIGATION_COUNSEL,
    ROW_AGENT,
    ApiErrorId,
    add_offer,
    advance_clock,
    api_client,
    counsel_accept_file,
    create_active_case,
    create_encroachment_removed,
    create_encroachment_removal_agreed,
    get_case,
    get_offer,
    get_success_data,
    only_referral,
    tender_offer,
    validate_error,
    validate_success,
)


class TestClosureGate:

    def test_close_blocked_at_count_one_then_succeeds_at_zero(self):
        """PRD section 3.8: "Closing a resolved case moves `ACTIVE_MONITORING →
        CLOSED_RESOLVED`, and the gate is evaluated as the final step of the
        §2.8 pipeline: no encroachment may remain open, meaning
        `open_encroachment_count` must be zero (else
        `ERR_OPEN_ENCROACHMENTS_REMAIN`); no offer may remain in `DRAFT`,
        `TENDERED`, or `COUNTERED` (else `ERR_OPEN_OFFERS_EXIST`); no permit
        may remain `PENDING` (else `ERR_PENDING_PERMITS_EXIST`); and no
        referral may remain in `REFERRED` or `ACCEPTED` (else
        `ERR_PENDING_LITIGATION_EXISTS`)."
        PRD section 3.3: "Confirming the physical removal then moves
        `REMOVAL_AGREED → REMOVED`, permitted only while the case is in
        `ACTIVE_MONITORING` or `RESOLUTION_PENDING`; it decrements
        `open_encroachment_count`, recomputes the pressure score, and when the
        count reaches zero the case automatically returns `RESOLUTION_PENDING →
        ACTIVE_MONITORING`."

        Design: Difficulty/boundary_precision_check/open_encroachment_count_zero_boundary_on_case_close
        """
        case, doc = create_active_case(case_code="ESM-012", parcel_id="P-012")
        enc = create_encroachment_removal_agreed(case["id"], doc["id"])

        first = api_client.close_case(case["id"], DEPARTMENT_DIRECTOR)
        validate_error(first, ApiErrorId.ERR_OPEN_ENCROACHMENTS_REMAIN, expected_status=409)

        get_success_data(api_client.confirm_encroachment_removal(case["id"], enc["id"], ROW_AGENT))
        mid = get_case(case["id"])
        assert mid["open_encroachment_count"] == 0
        assert mid["status"] == "ACTIVE_MONITORING"

        second = api_client.close_case(case["id"], DEPARTMENT_DIRECTOR)
        data = validate_success(second)
        assert data["status"] == "CLOSED_RESOLVED"

    def test_close_succeeds_when_count_already_zero(self):
        """PRD section 3.8: "Closing a resolved case moves `ACTIVE_MONITORING →
        CLOSED_RESOLVED`, and the gate is evaluated as the final step of the
        §2.8 pipeline: no encroachment may remain open, meaning
        `open_encroachment_count` must be zero (else
        `ERR_OPEN_ENCROACHMENTS_REMAIN`); no offer may remain in `DRAFT`,
        `TENDERED`, or `COUNTERED` (else `ERR_OPEN_OFFERS_EXIST`); no permit
        may remain `PENDING` (else `ERR_PENDING_PERMITS_EXIST`); and no
        referral may remain in `REFERRED` or `ACCEPTED` (else
        `ERR_PENDING_LITIGATION_EXISTS`)."

        The encroachment is walked to REMOVED before the close attempt, so the
        count is already at the zero boundary and the gate passes on the first
        attempt.

        Design: Difficulty/boundary_precision_check/open_encroachment_count_zero_boundary_on_case_close
        """
        case, doc = create_active_case(case_code="ESM-012b", parcel_id="P-012b")
        create_encroachment_removed(case["id"], doc["id"])
        mid = get_case(case["id"])
        assert mid["open_encroachment_count"] == 0
        assert mid["status"] == "ACTIVE_MONITORING"

        resp = api_client.close_case(case["id"], DEPARTMENT_DIRECTOR)
        data = validate_success(resp)
        assert data["status"] == "CLOSED_RESOLVED"

    def test_right_of_way_agent_cannot_close_case(self):
        """PRD section 2.1: "A request whose role is valid but not permitted
        for the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403); the per-endpoint role assignments are listed in Section 4."
        PRD section 4: the close-case endpoint lists only DepartmentDirector as
        its authorized role.

        Design: Corner/roles/right_of_way_agent_cannot_close_case
        """
        case, _doc = create_active_case(case_code="ESM-R01", parcel_id="P-R01")
        resp = api_client.close_case(case["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


class TestCondemnationCascade:

    def _tendered_offer_case(self, case_code, parcel_id):
        case, _doc = create_active_case(case_code=case_code, parcel_id=parcel_id)
        offer = add_offer(case["id"], landowner_name="J", offered_area_sqft=100,
                          severance_damages_cents=0)
        tender_offer(case["id"], offer["id"])
        return case, offer

    def _drive_referral_to_judgment(self, case_id):
        referral = only_referral(case_id)
        assert referral["referral_reason"] == "CONDEMNATION"
        counsel_accept_file(case_id, referral["id"])
        judgment = get_success_data(
            api_client.record_litigation_judgment(case_id, referral["id"], LITIGATION_COUNSEL)
        )
        return referral["id"], judgment

    def test_rejected_offer_to_condemnation_judgment_closes_case(self):
        """PRD section 3.5: "A `DepartmentDirector` may then refer an `EXPIRED`
        or `REJECTED_BY_OWNER` offer to condemnation, moving it to
        `CONDEMNATION_REFERRED` and auto-creating a litigation referral in
        `REFERRED` with `referral_reason` `CONDEMNATION`."
        PRD section 3.7: "Recording a judgment moves `FILED →
        JUDGMENT_OBTAINED` with three parallel outcomes: a `NEGOTIATION_FAILED`
        referral removes the linked encroachment; a
        `VEGETATION_REMEDIATION_FAILED` referral marks the linked violation
        `REMEDIATED`; and a `CONDEMNATION` referral moves the case itself to
        `CLOSED_CONDEMNED`."

        Design: Difficulty/transitive_cascade/offer_expire_to_condemnation_referral_to_judgment_to_case_closure
        """
        case, offer = self._tendered_offer_case("ESM-007", "P-007")
        get_success_data(api_client.reject_offer(case["id"], offer["id"], ROW_AGENT))
        assert get_offer(case["id"], offer["id"])["status"] == "REJECTED_BY_OWNER"

        referred = get_success_data(
            api_client.refer_offer_to_condemnation(case["id"], offer["id"], DEPARTMENT_DIRECTOR)
        )
        assert referred["status"] == "CONDEMNATION_REFERRED"

        _ref_id, judgment = self._drive_referral_to_judgment(case["id"])
        assert judgment["status"] == "JUDGMENT_OBTAINED"
        assert get_case(case["id"])["status"] == "CLOSED_CONDEMNED"

    def test_expired_offer_to_condemnation_judgment_closes_case(self):
        """PRD section 3.5: "If the `negotiation_deadline` passes while the
        offer is `TENDERED` or `COUNTERED`, the system automatically moves it
        to `EXPIRED` with the same release."
        PRD section 2.10: "Advancing the clock re-evaluates every
        deadline-based automatic transition in the system — expiring offers
        whose negotiation window has run out, escalating notified encroachments
        whose owner-response window has lapsed, and escalating notified
        vegetation violations whose remediation window has closed."
        PRD section 3.7: "Recording a judgment moves `FILED →
        JUDGMENT_OBTAINED` with three parallel outcomes: a `NEGOTIATION_FAILED`
        referral removes the linked encroachment; a
        `VEGETATION_REMEDIATION_FAILED` referral marks the linked violation
        `REMEDIATED`; and a `CONDEMNATION` referral moves the case itself to
        `CLOSED_CONDEMNED`."

        The clock is advanced 61 days past the 2026-08-01 start, which exceeds
        the negotiation window this suite assumes (see module docstring note in
        the design instance; the window itself is a configured value).

        Design: Difficulty/transitive_cascade/offer_expire_to_condemnation_referral_to_judgment_to_case_closure
        """
        case, offer = self._tendered_offer_case("ESM-007b", "P-007b")
        advance_clock("2026-10-01T00:00:00Z")
        offer_after = get_offer(case["id"], offer["id"])
        assert offer_after["status"] == "EXPIRED", (
            f"lapsed negotiation window must expire the offer, "
            f"got {offer_after['status']}"
        )

        referred = get_success_data(
            api_client.refer_offer_to_condemnation(case["id"], offer["id"], DEPARTMENT_DIRECTOR)
        )
        assert referred["status"] == "CONDEMNATION_REFERRED"

        _ref_id, judgment = self._drive_referral_to_judgment(case["id"])
        assert judgment["status"] == "JUDGMENT_OBTAINED"
        assert get_case(case["id"])["status"] == "CLOSED_CONDEMNED"
