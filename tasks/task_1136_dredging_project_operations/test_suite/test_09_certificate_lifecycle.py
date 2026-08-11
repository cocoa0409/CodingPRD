"""Certificate lifecycle: the audit-hold fork and override, the dispute loop,
certification ledger movement, and void compensation; project close-out
(PRD §3.9).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_project_ledger_invariant,
    set_clock, create_certificate, submit_certificate, certify_certificate,
    get_project, get_reach, complete_event,
    setup_dredging_reach, setup_confirmed_ticket,
    setup_accepted_reach, setup_species_shutdown, setup_approved_claim,
    open_event,
)


def _branching_ctx():
    """IN_PLACE project: 10.0h SPECIES shutdown on one event (resumed and
    completed), one CONFIRMED ticket (in_situ 1005.63), one APPROVED WEATHER
    claim (30000c), reach ACCEPTED with removed 500.00 cy. Clock 2026-05-20."""
    ctx = setup_dredging_reach(
        project_overrides={"name": "P-BR", "measurement_basis": "IN_PLACE"}
    )
    event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                       "2026-05-10T00:00:00Z")
    ctx["event"] = event
    setup_species_shutdown(ctx, species_class="MAMMAL")
    set_clock("2026-05-12T00:00:00Z")
    ctx["event"] = complete_event(event["id"])
    ctx = setup_confirmed_ticket(ctx)
    ctx = setup_approved_claim(ctx)
    ctx = setup_accepted_reach(ctx, post_survey_volume=39500,
                               post_survey_depth=25.0)
    set_clock("2026-05-20T00:00:00Z")
    return ctx


class TestAuditHoldBranch:
    def test_final_high_delta_forks_to_audit_hold_then_override_certify(
        self, api, owner_headers
    ):
        """PRD §3.9: "A final certificate whose reconciliation delta exceeds
        fifteen percent does not reach `SUBMITTED` at all: it moves
        automatically from `DRAFT` to `AUDIT_HOLD`, snapshot frozen exactly as
        on the submitted path, and it cannot be paid until it is
        override-certified."
        PRD §3.9: "certifying out of `AUDIT_HOLD` additionally requires an
        `override_note` in the request".

        Design: Difficulty/non_linear_state_machine/certificate_dispute_loop_and_audit_branch
        """
        ctx = _branching_ctx()
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-15T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        # Survey 500.00 vs scow 1005.63: |500.00 - 1005.63| / 500.00 x 100.
        assert submitted["reconciliation_delta_pct"] == pytest.approx(101.126,
                                                                      abs=0.01)
        assert submitted["status"] == "AUDIT_HOLD"
        certified = certify_certificate(
            cert["id"],
            override_note="survey re-run verified; scow overcount attributed "
                          "to fluff",
        )
        assert certified["status"] == "CERTIFIED"
        # 500.00 x 1500 - 100000 LD (14 actual days vs 13 frozen) = 650000.
        assert certified["total_amount_cents"] == 650000

    def test_interim_dispute_loop_reaches_certified_and_settles_claim(
        self, api, owner_headers, contractor_headers
    ):
        """PRD §3.9: "An `OwnerEngineer` dispute moves a `SUBMITTED` certificate
        to `DISPUTED`, retaining the frozen snapshot for reference with no
        ledger movement; a `ContractorOps` revision returns a `DISPUTED`
        certificate to `DRAFT`, clearing the computed snapshot so the next
        submission recomputes it."
        PRD §3.8: "when a payment certificate listing the claim in
        `standby_claim_ids` is certified, the claim moves from `APPROVED` to
        `SETTLED`."

        Design: Difficulty/non_linear_state_machine/certificate_dispute_loop_and_audit_branch
        """
        ctx = _branching_ctx()
        # FINAL via the audit branch (650000) so the ledger has its first entry.
        cert_f = create_certificate(ctx["project"]["id"], "FINAL",
                                    "2026-05-01T00:00:00Z",
                                    "2026-05-15T00:00:00Z",
                                    [ctx["reach"]["id"]])
        submit_certificate(cert_f["id"])
        certify_certificate(cert_f["id"], override_note="verified by re-survey")

        # INTERIM listing the claim: the full dispute loop in one pass.
        cert_i = create_certificate(ctx["project"]["id"], "INTERIM",
                                    "2026-05-01T00:00:00Z",
                                    "2026-05-31T00:00:00Z",
                                    [ctx["reach"]["id"]],
                                    standby_claim_ids=[ctx["claim"]["id"]])
        s1 = submit_certificate(cert_i["id"])
        assert s1["status"] == "SUBMITTED"
        d = validate_success(api.dispute_payment_certificate(cert_i["id"],
                                                             owner_headers), 200)
        assert d["status"] == "DISPUTED"
        r = validate_success(api.revise_payment_certificate(cert_i["id"],
                                                            contractor_headers),
                             200)
        assert r["status"] == "DRAFT"
        s2 = submit_certificate(cert_i["id"])
        assert s2["status"] == "SUBMITTED"
        certified = certify_certificate(cert_i["id"])
        assert certified["status"] == "CERTIFIED"
        # 1005.63 x 1500 + 30000 standby - 0 LD = 1538445.
        assert certified["total_amount_cents"] == 1538445

        claim_after = validate_success(
            api.get_standby_claim(ctx["claim"]["id"], owner_headers)
        )
        assert claim_after["status"] == "SETTLED"
        project_after = get_project(ctx["project"]["id"])
        # 650000 (FINAL) + 1538445 (INTERIM); the dispute hop moved nothing.
        assert project_after["total_certified_cents"] == 2188445
        assert_project_ledger_invariant(project_after)


def _certified_interim_ctx():
    """SCOW project: 10.0h SPECIES shutdown, completed event, one CONFIRMED
    ticket (in_situ 1005.63), one APPROVED WEATHER claim (30000c), and an
    INTERIM certificate listing the claim, submitted. Clock 2026-05-20."""
    ctx = setup_dredging_reach(
        project_overrides={"name": "P-INV2", "measurement_basis": "SCOW"}
    )
    event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                       "2026-05-10T00:00:00Z")
    ctx["event"] = event
    setup_species_shutdown(ctx, species_class="REPTILE")
    set_clock("2026-05-12T00:00:00Z")
    ctx["event"] = complete_event(event["id"])
    ctx = setup_confirmed_ticket(ctx)
    ctx = setup_approved_claim(ctx)
    cert = create_certificate(ctx["project"]["id"], "INTERIM",
                              "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z",
                              [ctx["reach"]["id"]],
                              standby_claim_ids=[ctx["claim"]["id"]])
    submit_certificate(cert["id"])
    set_clock("2026-05-20T00:00:00Z")
    ctx["cert"] = cert
    return ctx


class TestCertifyVoidCompensation:
    def test_certify_moves_ledger_and_cursor(self, api, owner_headers):
        """PRD §3.9: "Certification from either `SUBMITTED` or `AUDIT_HOLD`
        carries the same three side effects: each reach's
        `cumulative_certified_quantity_cy` increases by its line quantity,
        advancing the waterfall cursor; every listed standby claim moves from
        `APPROVED` to `SETTLED`; and the project's `total_certified_cents`
        increases by `total_amount_cents`, with `outstanding_payable_cents`
        recomputed as certified minus paid."

        Design: Difficulty/compensating_invariant/certify_void_restores_ledger_invariant
        """
        ctx = _certified_interim_ctx()
        certified = certify_certificate(ctx["cert"]["id"])
        # 1005.63 x 1500 tier-1 + 30000 standby - 0 LD = 1538445.
        assert certified["total_amount_cents"] == 1538445
        project_after = get_project(ctx["project"]["id"])
        assert project_after["total_certified_cents"] == 1538445
        assert project_after["outstanding_payable_cents"] == 1538445
        assert_project_ledger_invariant(project_after)
        claim_after = validate_success(
            api.get_standby_claim(ctx["claim"]["id"], owner_headers)
        )
        assert claim_after["status"] == "SETTLED"
        reach_after = get_reach(ctx["reach"]["id"])
        assert reach_after["cumulative_certified_quantity_cy"] == pytest.approx(
            1005.63, abs=1e-4
        )

    def test_void_restores_ledger_invariant(self, api, owner_headers):
        """PRD §3.9: "A void subtracts `total_amount_cents` from
        `total_certified_cents`, so certification plus void leaves the certified
        total unchanged net; decrements each reach's cursor by its line
        quantity; and returns every listed claim from `SETTLED` to `APPROVED`."

        Design: Difficulty/compensating_invariant/certify_void_restores_ledger_invariant
        """
        ctx = _certified_interim_ctx()
        certify_certificate(ctx["cert"]["id"])
        voided = validate_success(
            api.void_payment_certificate(ctx["cert"]["id"], owner_headers), 200
        )
        assert voided["status"] == "VOIDED"
        project_after = get_project(ctx["project"]["id"])
        assert project_after["total_certified_cents"] == 0
        assert project_after["outstanding_payable_cents"] == 0
        assert_project_ledger_invariant(project_after)
        reach_after = get_reach(ctx["reach"]["id"])
        assert reach_after["cumulative_certified_quantity_cy"] == pytest.approx(
            0, abs=1e-4
        )
        claim_after = validate_success(
            api.get_standby_claim(ctx["claim"]["id"], owner_headers)
        )
        assert claim_after["status"] == "APPROVED"


class TestCloseOut:
    def test_closeout_incomplete_rejected(self, api, owner_headers):
        """PRD §3.9: "An `OwnerEngineer` may close out only when every reach of
        the project is `ACCEPTED`, no dredge event remains in `ACTIVE` or
        `SHUTDOWN`, no placement ticket remains in `REPORTED`, no standby claim
        remains in `SUBMITTED` or `APPROVED` — every claim must be `SETTLED` or
        `DENIED` — and at least one `PAID` final certificate exists for the
        project. Any shortfall is rejected with `ERR_CLOSEOUT_INCOMPLETE`
        (HTTP 409)."

        Design: Corner/validations/closeout_incomplete_rejected
        """
        ctx = setup_dredging_reach(
            project_overrides={"name": "P-CLO", "measurement_basis": "SCOW"}
        )
        res = api.close_out_project(ctx["project"]["id"], owner_headers)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_INCOMPLETE,
                       expected_status=409)
        project_after = get_project(ctx["project"]["id"])
        assert project_after["status"] == "ACTIVE"
