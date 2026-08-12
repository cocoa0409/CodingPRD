"""Payment measurement: the dual quantity traditions, per-ticket rounding
order, the tiered waterfall, frozen allowed-days snapshot, audit-hold fork,
and certificate creation gates (PRD §2.11, §3.1, §3.9).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_payment_certificate_payload,
    assert_certificate_amounts,
    set_clock, create_project, add_permit, add_reach, add_plant, add_plan,
    submit_plan, approve_plan, activate_project, submit_survey, accept_survey,
    begin_dredging, open_event, complete_event, add_site, report_ticket,
    confirm_ticket, create_certificate, submit_certificate, file_claim,
    get_reach, get_project,
    setup_dredging_reach, setup_completed_event, setup_second_completed_event,
    setup_confirmed_ticket, setup_accepted_reach, setup_species_shutdown,
)


def _dual_measurement_ctx():
    """IN_PLACE project with: one completed event, one CONFIRMED ticket
    (witnessed 1609 at bulking 1.60), and an ACCEPTED post-dredge survey
    leaving removed_in_place_cy == 2000.00 (40000 - 38000)."""
    ctx = setup_completed_event(
        project_overrides={"name": "P-DUAL", "measurement_basis": "IN_PLACE"}
    )
    ctx = setup_confirmed_ticket(ctx)
    ctx = setup_accepted_reach(ctx, post_survey_volume=38000,
                               post_survey_depth=25.0)
    set_clock("2026-05-20T00:00:00Z")
    return ctx


class TestDualVariantDivergence:
    def test_final_in_place_pays_survey_derived_quantity(self, api):
        """PRD §3.9: "A final certificate follows `measurement_basis`:
        `IN_PLACE` bills the survey-derived quantity, the all-time sum of
        `removed_in_place_cy` over `reach_ids`".
        PRD §3.4: "it equals the latest accepted pre-dredge volume minus the
        latest accepted post-dredge volume, floored at zero".

        Design: Difficulty/dual_variant_calc/final_certificate_in_place_vs_scow_divergence
        """
        ctx = _dual_measurement_ctx()
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        assert_certificate_amounts(submitted)
        # IN_PLACE: the payable quantity is the survey-derived 2000.00 cy.
        assert submitted["quantity_cy"] == pytest.approx(2000.00, abs=1e-4)
        assert submitted["survey_derived_total_cy"] == pytest.approx(2000.00,
                                                                     abs=1e-4)

    def test_final_certificate_exposes_divergent_scow_total(self, api):
        """PRD §3.9: "Both traditions are also exposed for reconciliation:
        `survey_derived_total_cy` holds the all-time survey-derived total over
        `reach_ids`, and `scow_derived_total_cy` holds the scow total,
        period-bounded on an interim certificate and all-time on a final one."
        PRD §3.9: "A final certificate whose reconciliation delta exceeds
        fifteen percent does not reach `SUBMITTED` at all: it moves
        automatically from `DRAFT` to `AUDIT_HOLD`".

        Design: Difficulty/dual_variant_calc/final_certificate_in_place_vs_scow_divergence
        """
        ctx = _dual_measurement_ctx()
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        # The scow leg for the identical material: round(1609 / 1.60, 2).
        assert submitted["scow_derived_total_cy"] == pytest.approx(1005.63,
                                                                   abs=1e-4)
        # The two traditions MUST diverge on the same physical material...
        assert submitted["quantity_cy"] != pytest.approx(
            submitted["scow_derived_total_cy"], abs=1e-4
        )
        # ...and here the divergence (|2000.00 - 1005.63| / 2000.00 = 49.7%)
        # exceeds fifteen percent, so the certificate forks to AUDIT_HOLD.
        assert submitted["status"] == "AUDIT_HOLD"


class TestPerTicketRoundingOrder:
    def _two_confirmed_tickets_ctx(self):
        """SCOW project, two completed events, two CONFIRMED tickets of
        witnessed 1609 cy each at bulking 1.60."""
        ctx = setup_completed_event(
            project_overrides={"name": "P-RND", "measurement_basis": "SCOW"},
            plant_overrides={"plant_type": "HOPPER"},
        )
        ctx = setup_second_completed_event(ctx)
        site = add_site(name="SITE-B", site_type="UPLAND_CONFINED",
                        capacity_cy=50000, bulking_factor=1.6)
        t1 = report_ticket(ctx["event"]["id"], site["id"],
                           "2026-05-12T12:00:00Z", 1609)
        t1 = confirm_ticket(t1["id"], 1609)
        t2 = report_ticket(ctx["event2"]["id"], site["id"],
                           "2026-05-12T13:00:00Z", 1609)
        t2 = confirm_ticket(t2["id"], 1609)
        set_clock("2026-05-20T00:00:00Z")
        ctx["site"] = site
        ctx["ticket"] = t1
        ctx["ticket2"] = t2
        return ctx

    def test_scow_per_ticket_rounding(self, api):
        """PRD §3.7: "The ticket's `in_situ_volume_cy` is computed as
        `witnessed_volume_cy` divided by the site's `bulking_factor`, rounded
        half up to 2 decimal places — per ticket, at confirm time, before any
        summation".

        Design: Difficulty/combinatorial_formula/scow_per_ticket_rounding_beats_sum_then_divide
        """
        ctx = self._two_confirmed_tickets_ctx()
        # round_half_up(1609 / 1.60, 2) = 1005.63 per ticket.
        assert ctx["ticket"]["in_situ_volume_cy"] == pytest.approx(1005.63,
                                                                   abs=1e-4)
        assert ctx["ticket2"]["in_situ_volume_cy"] == pytest.approx(1005.63,
                                                                    abs=1e-4)

    def test_interim_certificate_sums_per_ticket_rounded(self, api):
        """PRD §2.11: "Scow-derived quantity rounds per ticket first — each
        confirmed ticket's witnessed volume is divided by the site's bulking
        factor and rounded half up to 2 decimal places — and only then sums the
        per-ticket results; dividing after summation is a specification
        violation."
        PRD §3.9: "An interim certificate is always scow-derived, whatever the
        project's `measurement_basis`: it sums the per-ticket-rounded
        `in_situ_volume_cy` over the project's `CONFIRMED`, non-voided placement
        tickets whose `placed_utc` falls inside the closed billing period".

        Design: Difficulty/combinatorial_formula/scow_per_ticket_rounding_beats_sum_then_divide
        """
        ctx = self._two_confirmed_tickets_ctx()
        cert = create_certificate(ctx["project"]["id"], "INTERIM",
                                  "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        # 1005.63 + 1005.63 = 2011.26; the forbidden sum-then-divide order
        # would read round(3218 / 1.6, 2) = 2011.25.
        assert submitted["quantity_cy"] == pytest.approx(2011.26, abs=1e-4)
        assert submitted["scow_derived_total_cy"] == pytest.approx(2011.26,
                                                                   abs=1e-4)


class TestFrozenSettlementSnapshot:
    def _superseded_plan_ctx(self):
        """IN_PLACE project activated under a SAND plan (risk-adjusted 13 days),
        then a CLAY plan (risk-adjusted 18 days) approved over it; reach dredged
        in July and ACCEPTED with removed 1000.00 cy; one CONFIRMED ticket."""
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-FSO", measurement_basis="IN_PLACE")
        add_permit(project["id"])
        reach = add_reach(project["id"])
        plant = add_plant(plant_type="CUTTER_SUCTION")
        plan1 = add_plan(project["id"], plant["id"], material_class="SAND",
                         planned_start_utc="2026-05-10T00:00:00Z",
                         planned_end_utc="2026-06-30T00:00:00Z")
        submit_plan(plan1["id"])
        approve_plan(project["id"], plan1["id"])
        project = activate_project(project["id"])
        # Frozen at activation: risk_adjusted_duration_days of the SAND plan.
        assert project["allowed_days_frozen"] == 13
        plan2 = add_plan(project["id"], plant["id"], material_class="CLAY",
                         planned_start_utc="2026-07-01T00:00:00Z",
                         planned_end_utc="2026-08-31T00:00:00Z")
        submit_plan(plan2["id"])
        plan2 = approve_plan(project["id"], plan2["id"])
        survey_pre = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        accept_survey(reach["id"], survey_pre["id"])
        begin_dredging(reach["id"])
        set_clock("2026-07-05T00:00:00Z")
        event = open_event(reach["id"], plant["id"], "2026-07-05T00:00:00Z")
        set_clock("2026-07-10T00:00:00Z")
        complete_event(event["id"])
        site = add_site(name="SITE-A", site_type="OPEN_WATER",
                        capacity_cy=50000, bulking_factor=1.6)
        ticket = report_ticket(event["id"], site["id"], "2026-07-10T12:00:00Z",
                               1609)
        confirm_ticket(ticket["id"], 1609)
        survey_post = submit_survey(reach["id"], "POST_DREDGE", 39000, 25.0)
        accept_survey(reach["id"], survey_post["id"])
        set_clock("2026-07-20T00:00:00Z")
        return {
            "project": get_project(project["id"]),
            "reach": get_reach(reach["id"]),
            "plant": plant,
            "plan1": plan1,
            "plan2": plan2,
            "event": event,
            "site": site,
            "ticket": ticket,
        }

    def test_final_settlement_uses_frozen_allowed_days(self, api,
                                                       owner_headers):
        """PRD §3.1: "The moment of activation freezes `allowed_days_frozen` to
        the `risk_adjusted_duration_days` of the most recently approved plan.
        That snapshot is taken once and never re-frozen: later approvals that
        supersede the plan leave the frozen value untouched".
        PRD §3.9: "`liquidated_damages_cents` — zero on interim certificates —
        multiplies the project's `liquidated_damages_cents_per_day` by the
        overrun in days, where the overrun is the actual duration minus
        `allowed_days_frozen`, floored at zero, and the actual duration is the
        span between `period_start_utc` and `period_end_utc` divided by
        twenty-four hours and rounded up to whole days."

        Design: Difficulty/combinatorial_formula/final_settlement_frozen_snapshot_order
        """
        ctx = self._superseded_plan_ctx()
        # The superseding CLAY plan would imply 18 days if the snapshot were
        # re-frozen: 4000 x 0.70 x 1.00 x 0.80 = 2240.00; ceil(40000/2240) = 18.
        plan2_after = validate_success(
            api.get_dredge_plan(ctx["plan2"]["id"], owner_headers)
        )
        assert plan2_after["risk_adjusted_duration_days"] == 18
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        # actual days ceil(19d) = 19; frozen allowed 13 -> LD 100000 x 6.
        assert submitted["liquidated_damages_cents"] == 600000

    def test_final_settlement_total_pinned_order(self, api):
        """PRD §3.9: "`total_amount_cents`, computed in the pinned order as
        `quantity_amount_cents` plus `standby_amount_cents` minus
        `liquidated_damages_cents`."
        PRD §3.9: "Any interim certificate, and any final certificate within
        tolerance, moves from `DRAFT` to `SUBMITTED`."

        Design: Difficulty/combinatorial_formula/final_settlement_frozen_snapshot_order
        """
        ctx = self._superseded_plan_ctx()
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        assert_certificate_amounts(submitted)
        # IN_PLACE quantity 1000.00 cy, all tier-1: 1000.00 x 1500 = 1500000.
        assert submitted["quantity_cy"] == pytest.approx(1000.00, abs=1e-4)
        assert submitted["quantity_amount_cents"] == 1500000
        assert submitted["standby_amount_cents"] == 0
        assert submitted["liquidated_damages_cents"] == 600000
        # 1500000 + 0 - 600000, in the pinned order.
        assert submitted["total_amount_cents"] == 900000
        # Delta |1000.00 - 1005.63| / 1000.00 = 0.563% <= 15: within tolerance.
        assert submitted["status"] == "SUBMITTED"


class TestQuantityWaterfall:
    def test_quantity_waterfall_tier_boundary_straddle(self, api):
        """PRD §3.9: "The tier caps are: tier one up to eighty percent of the
        reach's `design_quantity_cy`, that cap rounded half up to 2 decimal
        places; tier two up to the full design quantity; tier three up to the
        design quantity plus `overdepth_allowance_cy`."; "whatever spills enters
        tier two against the room between the cursor, what tier one absorbed,
        and the design quantity, priced at ninety percent of base".

        Design: Corner/calculations/quantity_waterfall_tier_boundary_straddle
        """
        ctx = setup_completed_event(
            project_overrides={"name": "P-WF", "measurement_basis": "SCOW"}
        )
        ctx = setup_confirmed_ticket(
            ctx, declared_volume_cy=33000, witnessed_volume_cy=33000,
            site_overrides={"name": "SITE-W", "bulking_factor": 1.0},
        )
        set_clock("2026-05-20T00:00:00Z")
        cert = create_certificate(ctx["project"]["id"], "INTERIM",
                                  "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        assert submitted["quantity_cy"] == pytest.approx(33000.00, abs=1e-4)
        # 32000 (80% of 40000) x 1500 + 1000 x (1500 x 0.90) = 49350000.
        assert submitted["quantity_amount_cents"] == 49350000


class TestCertificateCreationAndSubmitGates:
    def test_audit_hold_certify_missing_note_rejected(self, api, owner_headers):
        """PRD §3.9: "certifying out of `AUDIT_HOLD` additionally requires an
        `override_note` in the request, and a missing note surfaces as
        `ERR_INVALID_REQUEST` (HTTP 400) before the segregation check is even
        reached, per the evaluation order."

        Design: Corner/state_machines/audit_hold_certify_missing_note_rejected
        """
        ctx = setup_dredging_reach(
            project_overrides={"name": "P-AH", "measurement_basis": "IN_PLACE"}
        )
        ctx = setup_accepted_reach(ctx, post_survey_volume=39500,
                                   post_survey_depth=25.0)
        set_clock("2026-05-20T00:00:00Z")
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        submitted = submit_certificate(cert["id"])
        # Zero scow against 500.00 survey-derived: delta 100% > 15.
        assert submitted["status"] == "AUDIT_HOLD"
        res = api.certify_payment_certificate(cert["id"], {}, owner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        certified = validate_success(
            api.certify_payment_certificate(
                cert["id"], {"override_note": "verified by re-survey"},
                owner_headers,
            ),
            200,
        )
        assert certified["status"] == "CERTIFIED"

    def test_final_certificate_before_acceptance_rejected(self, api,
                                                          contractor_headers):
        """PRD §3.9: "A final certificate requires every reach in `reach_ids` to
        be `ACCEPTED`, else submission fails with
        `ERR_FINAL_ACCEPTANCE_INCOMPLETE` (HTTP 409)."
        PRD §3.9: "The certificate is born `DRAFT`."

        Design: Corner/validations/final_certificate_before_acceptance_rejected
        """
        ctx = setup_dredging_reach(
            project_overrides={"name": "P-FIN", "measurement_basis": "IN_PLACE"}
        )
        set_clock("2026-05-20T00:00:00Z")
        # Reach still DREDGING: creation is not gated, submission is.
        cert = create_certificate(ctx["project"]["id"], "FINAL",
                                  "2026-05-01T00:00:00Z", "2026-05-20T00:00:00Z",
                                  [ctx["reach"]["id"]])
        assert cert["status"] == "DRAFT"
        res = api.submit_payment_certificate(cert["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_FINAL_ACCEPTANCE_INCOMPLETE,
                       expected_status=409)
        cert_after = validate_success(
            api.get_payment_certificate(cert["id"], contractor_headers)
        )
        assert cert_after["status"] == "DRAFT"

    def test_certificate_with_unapproved_claim_rejected(self, api,
                                                        contractor_headers):
        """PRD §3.9: "An optional `standby_claim_ids` lists claims to settle
        with the certificate; it defaults to empty, and each listed claim must
        be `APPROVED`, belong to the same project, and not already be `SETTLED`,
        else creation fails with `ERR_CLAIM_NOT_APPROVED` (HTTP 422)."

        Design: Corner/validations/certificate_with_unapproved_claim_rejected
        """
        ctx = setup_dredging_reach(
            project_overrides={"name": "P-CUA", "measurement_basis": "SCOW"}
        )
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        ctx["event"] = event
        setup_species_shutdown(ctx, observed_utc="2026-05-10T06:00:00Z",
                               resume_at="2026-05-10T14:00:00Z")
        claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                           "2026-05-10T06:00:00Z", "2026-05-10T14:00:00Z",
                           8.0, "WEATHER")
        # Claim deliberately left SUBMITTED (never approved).
        set_clock("2026-05-20T00:00:00Z")
        res = api.create_payment_certificate(
            create_payment_certificate_payload(
                ctx["project"]["id"], [ctx["reach"]["id"]],
                certificate_type="INTERIM",
                period_start_utc="2026-05-01T00:00:00Z",
                period_end_utc="2026-05-31T00:00:00Z",
                standby_claim_ids=[claim["id"]],
            ),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_APPROVED,
                       expected_status=422)
