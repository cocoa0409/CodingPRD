"""Corner tests — rbac section (role-exclusive and segregation-of-duties)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_fema_claim,
    create_fema_claim_payload,
    create_feeder_record,
    create_outage_payload,
    create_ready_work_order,
    create_switching_order_payload,
    create_work_order_payload,
    get_success_data,
    make_claims_officer_headers,
    make_field_crew_lead_headers,
    make_regulator_headers,
    make_system_operator_headers,
    set_clock,
    setup_demobilized_event_with_claim,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CO1 = TEST_USERS["claims_officer_headers"]
CO2 = TEST_USERS["claims_officer_2_headers"]
REG = TEST_USERS["regulator_headers"]


def test_switching_approve_same_user_sod_then_other_user_succeeds(api):
    """PRD §3.6: "Approval moves `ISSUED` to `APPROVED`, but segregation of
    duties applies — the approver's `X-User-ID` must differ from
    `issuer_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and is recorded in
    `approver_user_id`."

    Design: Corner/rbac/switching_approve_same_user_sod_then_other_user_succeeds
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    wo = get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"],
                work_type="SWITCHING",
                required_crew_type="LINE",
                requires_switching_order=True,
            ),
            DISP,
        )
    )
    so = get_success_data(
        api.create_switching_order(
            create_switching_order_payload(wo["id"]),
            make_system_operator_headers("op-1"),
        )
    )
    get_success_data(
        api.issue_switching_order(so["id"], make_system_operator_headers("op-1"))
    )
    # Same user approving their own issue: rejected.
    resp = api.approve_switching_order(so["id"], make_system_operator_headers("op-1"))
    err = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES"
    # A different SystemOperator succeeds.
    approved = get_success_data(
        api.approve_switching_order(so["id"], make_system_operator_headers("op-2"))
    )
    assert approved["so_status"] == "APPROVED"
    assert approved["approver_user_id"] == "op-2"


def test_fema_full_chain_with_certifier_sod(api):
    """PRD §3.9: "Certification moves `SUBMITTED` to `CERTIFIED` and must be
    performed by a different `ClaimsOfficer` than the preparer: a matching
    `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES`, and the
    certifier is recorded in `certifier_user_id`." And: "The regulator
    completes the cycle: obligating moves `CERTIFIED` to `OBLIGATED`, and
    marking paid moves `OBLIGATED` to `PAID`, terminal."

    Design: Corner/rbac/fema_full_chain_with_certifier_sod
    """
    ev, claim = setup_demobilized_event_with_claim(
        clock_iso="2026-08-10T00:00:00Z", threshold_cents=0
    )
    assert ev["event_status"] == "DEMOBILIZING"
    # 0 >= 0 qualifies on the threshold boundary.
    submitted = get_success_data(
        api.submit_fema_claim(claim["id"], make_claims_officer_headers("co-1"))
    )
    assert submitted["claim_status"] == "SUBMITTED"
    assert submitted["eligible_snapshot_cents"] == 0
    assert submitted["preparer_user_id"] == "co-1"
    # Preparer cannot certify their own submission.
    resp = api.certify_fema_claim(
        claim["id"], make_claims_officer_headers("co-1")
    )
    err = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES"
    # A second officer certifies; the regulator obligates and pays.
    certified = get_success_data(
        api.certify_fema_claim(claim["id"], make_claims_officer_headers("co-2"))
    )
    assert certified["claim_status"] == "CERTIFIED"
    assert certified["certifier_user_id"] == "co-2"
    obligated = get_success_data(
        api.obligate_fema_claim(claim["id"], make_regulator_headers())
    )
    assert obligated["claim_status"] == "OBLIGATED"
    paid = get_success_data(
        api.mark_paid_fema_claim(claim["id"], make_regulator_headers())
    )
    assert paid["claim_status"] == "PAID"


def test_field_crew_lead_cannot_arrive_other_crews_work_order(api):
    """PRD §2.1: "When `X-User-Role` is `FieldCrewLead`, `X-User-ID` is the
    `id` of the acting `Crew`; ownership checks on any resource that
    references a crew — a work order's assignee or a damage assessment's
    assessor — compare the resource's crew-reference field to `X-User-ID`,
    and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/field_crew_lead_cannot_arrive_other_crews_work_order
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l1 = create_crew(crew_type="LINE", crew_code="L-1")
    cr_l2 = create_crew(crew_type="LINE", crew_code="L-2")
    wo = create_ready_work_order(ot["id"])
    get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l1["id"]}, DISP))
    # Crew L-2 attempts to arrive L-1's work order.
    resp = api.arrive_work_order(wo["id"], make_field_crew_lead_headers(cr_l2["id"]))
    err = validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert err["error_id"] == "ERR_OWNERSHIP_MISMATCH"
    wo_read = get_success_data(api.get_work_order(wo["id"], DISP))
    assert wo_read["arrived_at"] is None
    crew_read = get_success_data(api.get_crew(cr_l1["id"], DISP))
    assert crew_read["crew_status"] == "EN_ROUTE"


def test_regulator_cannot_submit_claims(api):
    """PRD §2.7: "The presented role must be authorized for the endpoint
    (`ERR_FORBIDDEN_ROLE`, 403)." Gate 2 (role) fires before gate 4 (state);
    `Regulator` is not in the role list of `POST /om/fema-claims/{id}/submit`.

    Design: Corner/rbac/regulator_cannot_submit_claims
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm R4", event_type="HURRICANE")
    claim = create_fema_claim(ev["id"], county_code="C1", threshold_cents=1000)
    resp = api.submit_fema_claim(claim["id"], REG)
    err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
