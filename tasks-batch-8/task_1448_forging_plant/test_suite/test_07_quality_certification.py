"""Quality certification: submission state gating and the rejection /
resubmission cycle under segregation of duties (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    first_order_cert,
    get_success_data,
    setup_production_ctx,
    submit_cert,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

QE1 = TEST_USERS["quality_engineer_headers"]
QE2 = TEST_USERS["quality_engineer_2_headers"]
SP = TEST_USERS["sales_planner_headers"]


class TestCertStateGate:
    def test_certify_pending_cert_rejected(self, api):
        """PRD §3.7: "Submission moves a cert from `PENDING` to `SUBMITTED` and
        records the `submitter_id` from the caller's `X-User-ID`; a `REJECTED`
        cert may be resubmitted the same way with fresh readings, updating
        `submitter_id` to the resubmitting user — the resubmission cycle."
        PRD §2.10: "Source-state validity for the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, alongside the dedicated state-flavored
        codes `ERR_CHARGE_NOT_READY`, `ERR_PART_NOT_INSPECTED`, and
        `ERR_RUN_NO_HEATS`)."

        The auto-created cert is PENDING; certifying applies to submitted
        readings, so a PENDING cert is refused.

        Design: Corner/state_machines/certify_pending_cert_rejected
        """
        ctx = setup_production_ctx(qty=2)  # trim 100/86/2 -> PRODUCED
        cert = first_order_cert(ctx["wo"]["id"])
        assert cert["status"] == "PENDING"
        resp = api.certify_quality_cert(cert["id"], QE2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_quality_cert(cert["id"], QE1))
        assert after["status"] == "PENDING"


class TestCertResubmissionCycle:
    def test_quality_cert_resubmission_cycle(self, api):
        """PRD §3.7: "a `REJECTED` cert may be resubmitted the same way with
        fresh readings, updating `submitter_id` to the resubmitting user — the
        resubmission cycle."
        PRD §3.7: "Rejection is likewise guarded: the rejecter — who supplies a
        `reason` — must differ from the submitter, on pain of the same
        `ERR_CERT_SOD_VIOLATION`, and the cert returns to `REJECTED`, from
        which resubmission remains possible."
        PRD §3.7: "when coverage completes on a `PRODUCED` order, the order
        advances to `CERTIFIED`; when a newly consumed heat leaves coverage
        incomplete on a `CERTIFIED` order, the order is demoted back to
        `PRODUCED` — the contagion rule."

        qe-1 submits, qe-2 rejects (SoD satisfied), qe-1 resubmits, qe-2
        certifies; the completed coverage promotes the order.

        Design: Corner/state_machines/quality_cert_resubmission_cycle
        """
        ctx = setup_production_ctx(qty=2)
        cert = first_order_cert(ctx["wo"]["id"])
        submitted = submit_cert(cert["id"], grain_flow_rating=4,
                                macro_etch_result="PASS", submitter_headers=QE1)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitter_id"] == "qe-1"
        rejected = get_success_data(api.reject_quality_cert(
            cert["id"], {"reason": "etch photo illegible"}, QE2))
        assert rejected["status"] == "REJECTED", (
            f"qe-2 rejecting qe-1's submission satisfies SoD, got {rejected['status']}"
        )
        resubmitted = submit_cert(cert["id"], grain_flow_rating=6,
                                  macro_etch_result="PASS", submitter_headers=QE1)
        assert resubmitted["status"] == "SUBMITTED", (
            "REJECTED -> SUBMITTED is the resubmission cycle edge"
        )
        certified = get_success_data(api.certify_quality_cert(cert["id"], QE2))
        assert certified["status"] == "CERTIFIED"
        wo = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo["status"] == "CERTIFIED", (
            "completed heat coverage must promote the PRODUCED order to CERTIFIED"
        )
