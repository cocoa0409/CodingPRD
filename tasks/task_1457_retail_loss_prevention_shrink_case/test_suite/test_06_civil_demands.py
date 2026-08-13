"""Civil demands: tiered statutory penalty schedule, dual basis variants,
issuance gates (SoD, 60-day window, OCC interplay), write-off cap."""
import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    advance_case,
    assert_civil_demand,
    assert_instants_equal,
    attach_evidence,
    document_interview,
    draft_demand,
    get_case,
    hold_interview,
    issue_demand,
    make_analyst_headers,
    make_employee,
    make_manager_headers,
    make_store,
    make_period,
    record_and_post_payment,
    schedule_interview,
    set_clock,
    setup_case_adjudicating,
    setup_case_interviewed,
    setup_case_investigating,
    setup_case_with_issued_demand,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    ADMIN_1,
    ANALYST_1,
    CLOCK_DEFAULT_ISO,
    MANAGER_1,
)


class TestDualBasisVariants:
    """Two demands over identical inputs (loss 75000, priors 2, no recovery
    cost) diverge purely by basis variant."""

    def _issue_pair(self, api, store_id):
        """CA with STATUTORY demand, CB with ACTUAL_LOSS demand, both issued."""
        ctx_a = setup_case_interviewed(store_id, manual_loss_cents=75000,
                                       evidence_type="VIDEO_CLIP")
        ctx_b = setup_case_interviewed(store_id, manual_loss_cents=75000,
                                       evidence_type="TRANSACTION_LOG",
                                       scheduled_start="2026-08-02T13:00:00Z",
                                       scheduled_end="2026-08-02T14:00:00Z")
        da = draft_demand(ctx_a["case"]["id"], ANALYST_1, basis="STATUTORY",
                          priors_offense_count=2)
        db = draft_demand(ctx_b["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS",
                          priors_offense_count=2)
        da = issue_demand(da["id"], MANAGER_1)
        db = issue_demand(db["id"], MANAGER_1)
        return da, db

    def test_statutory_demand_includes_tiered_penalty(self, api):
        """PRD §3.6: "A loss above 50000 and at most 150000 cents draws 25000
        cents plus ten percent of the portion above 50000, that percentage
        rounded half up to whole cents."
        PRD §3.6: "The tier penalty is then multiplied by a prior-offense
        multiplier: one plus one-half times the number of priors counted, where
        at most four priors count and the multiplier itself is capped at 3.0."
        PRD §3.6: "The demand's `amount_due_cents` is `merchandise_loss_cents`
        plus `statutory_penalty_cents` plus `recovery_cost_cents`; on the
        `ACTUAL_LOSS` basis the penalty term is zero, so the amount due is
        merchandise loss plus recovery cost only."

        Loss 75000 -> tier 25000 + 2500 = 27500; priors 2 -> multiplier 2.0;
        penalty 55000; amount due 75000 + 55000 = 130000.

        Design: Difficulty/dual_variant_calc/civil_demand_statutory_vs_actual_loss_same_inputs
        """
        store = make_store(store_number="S100", name="Store 100")
        da, _db = self._issue_pair(api, store["id"])
        assert_civil_demand(da)
        assert da["merchandise_loss_cents"] == 75000
        assert da["statutory_penalty_cents"] == 55000
        assert da["amount_due_cents"] == 130000
        assert da["status"] == "ISSUED"

    def test_actual_loss_demand_carries_zero_penalty(self, api):
        """PRD §3.6: "The demand's `amount_due_cents` is
        `merchandise_loss_cents` plus `statutory_penalty_cents` plus
        `recovery_cost_cents`; on the `ACTUAL_LOSS` basis the penalty term is
        zero, so the amount due is merchandise loss plus recovery cost only."

        Identical inputs (loss 75000, priors 2) on the ACTUAL_LOSS variant:
        penalty 0, amount due 75000 — strictly less than the STATUTORY 130000.

        Design: Difficulty/dual_variant_calc/civil_demand_statutory_vs_actual_loss_same_inputs
        """
        store = make_store(store_number="S100", name="Store 100")
        da, db = self._issue_pair(api, store["id"])
        assert_civil_demand(db)
        assert db["merchandise_loss_cents"] == 75000
        assert db["statutory_penalty_cents"] == 0
        assert db["amount_due_cents"] == 75000
        assert db["amount_due_cents"] != da["amount_due_cents"]


class TestTierRoundingOrder:
    def test_tier2_percentage_rounded_before_multiplication(self, api):
        """PRD §3.6: "A loss above 50000 and at most 150000 cents draws 25000
        cents plus ten percent of the portion above 50000, that percentage
        rounded half up to whole cents."
        PRD §3.6: "`statutory_penalty_cents` is that product rounded half up to
        whole cents — the rounding happens after the multiplication, since each
        tier value is already integral."

        Loss 75555, priors 1: tier excess 0.10 * 25555 = 2555.5 -> 2556 first,
        tier 27556; then 27556 * 1.5 = 41334. (Multiplying before rounding
        would yield 41333.)

        Design: Difficulty/combinatorial_formula/civil_demand_tier2_round_then_multiply_order
        """
        store = make_store(store_number="S120", name="Store 120")
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=75555,
                                     evidence_type="TRANSACTION_LOG")
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=1)
        demand = issue_demand(demand["id"], MANAGER_1)
        assert demand["merchandise_loss_cents"] == 75555
        assert demand["statutory_penalty_cents"] == 41334

    def test_amount_due_composition_uses_rounded_penalty(self, api):
        """PRD §3.6: "The demand's `amount_due_cents` is
        `merchandise_loss_cents` plus `statutory_penalty_cents` plus
        `recovery_cost_cents`; on the `ACTUAL_LOSS` basis the penalty term is
        zero, so the amount due is merchandise loss plus recovery cost only."

        75555 + 41334 = 116889; the multiply-first order would produce 116888.

        Design: Difficulty/combinatorial_formula/civil_demand_tier2_round_then_multiply_order
        """
        store = make_store(store_number="S120", name="Store 120")
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=75555,
                                     evidence_type="TRANSACTION_LOG")
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=1)
        demand = issue_demand(demand["id"], MANAGER_1)
        assert demand["amount_due_cents"] == 116889
        assert demand["amount_due_cents"] != 116888


class TestTierBoundariesAndCaps:
    def test_demand_tier1_boundary_50000_vs_50001(self, api):
        """PRD §3.6: "A loss of at most 50000 cents draws a flat tier penalty
        of 10000 cents. A loss above 50000 and at most 150000 cents draws 25000
        cents plus ten percent of the portion above 50000, that percentage
        rounded half up to whole cents."

        Loss 50000 stays in tier 1 (penalty 10000, due 60000); loss 50001
        enters tier 2 (penalty 25000 + round_half_up(0.10*1) = 25000, due
        75001).

        Design: Corner/calculations/demand_tier1_boundary_50000_vs_50001
        """
        store = make_store(store_number="S052", name="Store 52")
        ctx_a = setup_case_interviewed(store["id"], manual_loss_cents=50000)
        ctx_b = setup_case_interviewed(store["id"], manual_loss_cents=50001,
                                       scheduled_start="2026-08-02T11:00:00Z",
                                       scheduled_end="2026-08-02T12:00:00Z")
        da = draft_demand(ctx_a["case"]["id"], ANALYST_1, basis="STATUTORY",
                          priors_offense_count=0)
        db = draft_demand(ctx_b["case"]["id"], ANALYST_1, basis="STATUTORY",
                          priors_offense_count=0)
        da = issue_demand(da["id"], MANAGER_1)
        db = issue_demand(db["id"], MANAGER_1)
        assert da["statutory_penalty_cents"] == 10000
        assert da["amount_due_cents"] == 60000
        assert db["statutory_penalty_cents"] == 25000
        assert db["amount_due_cents"] == 75001

    def test_demand_priors_counted_clamp_and_multiplier_cap(self, api):
        """PRD §3.6: "A loss above 150000 cents draws 50000 cents plus twenty
        percent of the portion above 150000 — likewise rounded half up — with
        the tier result capped at 100000 cents."
        PRD §3.6: "The tier penalty is then multiplied by a prior-offense
        multiplier: one plus one-half times the number of priors counted, where
        at most four priors count and the multiplier itself is capped at 3.0."

        Loss 200000 -> tier 50000 + round_half_up(0.20 * 50000) = 60000 (under
        the 100000 tier cap). Priors 8 -> at most four count -> multiplier
        exactly 3.0 (the cap). Penalty 180000; amount due 200000 + 180000 =
        380000.

        Design: Corner/calculations/demand_priors_multiplier_and_penalty_caps
        """
        store = make_store(store_number="S053", name="Store 53")
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=200000,
                                     evidence_type="VIDEO_CLIP")
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=8)
        demand = issue_demand(demand["id"], MANAGER_1)
        assert demand["statutory_penalty_cents"] == 180000, (
            "tier 60000 x multiplier 3.0 (priors 8 clamped to 4)"
        )
        assert demand["amount_due_cents"] == 380000


class TestIssuanceGates:
    def test_demand_issue_twice_returns_invalid_state(self, api):
        """PRD §3.6: "Only a `DRAFT` demand can be issued, and only while its
        case is `INTERVIEWED` or `ADJUDICATING`; moreover, once the case
        carries an `adjudicated_at`, issuance must happen no later than sixty
        days after that instant (`ERR_DEMAND_WINDOW_CLOSED`)."
        PRD §3.6: "At issuance the money fields are snapshotted and never
        change afterwards: `merchandise_loss_cents` takes the case's
        `total_loss_cents` at that instant, and `statutory_penalty_cents` is
        computed from the tier schedule — zero when the basis is `ACTUAL_LOSS`."

        Design: Corner/state_machines/demand_issue_twice_returns_invalid_state
        """
        store = make_store(store_number="S041", name="Store 41")
        ctx = setup_case_with_issued_demand(store["id"], manual_loss_cents=30000)
        resp = api.issue_civil_demand(
            ctx["demand"]["id"], make_manager_headers(MANAGER_1)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(
            api.get_civil_demand(ctx["demand"]["id"], make_manager_headers(MANAGER_1))
        )
        assert after["amount_due_cents"] == 30000, "ACTUAL_LOSS snapshot unchanged"
        assert after["status"] == "ISSUED"

    def test_state_gate_beats_occ_on_demand_create(self, api):
        """PRD §2.7: "7. Cross-entity state guards: the store must be `ACTIVE`
        (`ERR_STORE_CLOSED`), the employee must not be `TERMINATED`
        (`ERR_EMPLOYEE_NOT_ACTIVE`), shrink-period locking
        (`ERR_PERIOD_LOCKED`), group linkability (`ERR_GROUP_NOT_LINKABLE`),
        packet acknowledgement for referral-dependent actions
        (`ERR_CASE_NOT_REFERRABLE`), and the case-state gates on interview
        scheduling, evidence attachment, demand drafting, and packet drafting
        (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §2.7: "8. Optimistic-concurrency version equality
        (`ERR_STALE_CASE_VERSION`, `ERR_STALE_PERIOD_VERSION`)."
        PRD §2.7: "Every request passes through a single ordered validation
        pipeline, and the first failing check produces the response — later
        checks are not evaluated."

        Drafting against an INVESTIGATING case with a stale version fails the
        case-state gate (409) before the version check is reached.

        Design: Corner/validations/state_beats_occ_on_demand_create
        """
        store = make_store(store_number="S060", name="Store 60")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        stale_version = ctx["case"]["version"] - 1  # creation version, pre-assign
        resp = api.create_civil_demand(
            {"case_id": ctx["case"]["id"], "basis": "ACTUAL_LOSS",
             "expected_case_version": stale_version},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_sod_demand_issuer_is_drafter(self, api):
        """PRD §3.6: "Issuance is a manager's act, and the issuer must differ
        from the analyst who drafted the demand (`ERR_SOD_DEMAND_ISSUER`)."
        PRD §2.9: "Independently, the manager issuing a civil demand must not
        be the analyst recorded as that demand's `created_by`
        (`ERR_SOD_DEMAND_ISSUER`)."
        PRD §2.5: "The logical clock stamps `conducted_at` when an interview
        outcome is recorded, `documented_at` when documentation is filed,
        `adjudicated_at` and `closed_at` at adjudication or early closure,
        `issued_at` at demand issuance, `submitted_at` at packet submission,
        and `counted_at` at each accepted physical count."

        The same person wearing the manager hat cannot issue; another manager
        can, and issued_at reads the default logical clock instant.

        Design: Corner/validations/sod_demand_issuer_is_drafter
        """
        store = make_store(store_number="S062", name="Store 62")
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=30000)
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS")
        # Same X-User-ID as the drafter, LPManager role.
        resp = api.issue_civil_demand(demand["id"], make_manager_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_SOD_DEMAND_ISSUER)
        issued = issue_demand(demand["id"], MANAGER_1)
        assert issued["status"] == "ISSUED"
        assert_instants_equal(issued["issued_at"], CLOCK_DEFAULT_ISO, "issued_at")

    def test_demand_statutory_basis_on_employee_case_rejected(self, api):
        """PRD §3.6: "`ACTUAL_LOSS` is the only basis allowed on an
        `EMPLOYEE`-subject case — choosing `STATUTORY` there fails with
        `ERR_BASIS_NOT_ALLOWED` — while external-subject cases may elect
        either."

        Design: Corner/validations/demand_statutory_basis_on_employee_case_rejected
        """
        store = make_store(store_number="S064", name="Store 64")
        emp = make_employee(store["id"], employee_ref="E-640", full_name="Emp 640")
        ctx = setup_case_interviewed(
            store["id"], subject_type="EMPLOYEE", employee_id=emp["id"],
            manual_loss_cents=20000, evidence_type="TRANSACTION_LOG",
        )
        version = get_case(ctx["case"]["id"])["version"]
        resp = api.create_civil_demand(
            {"case_id": ctx["case"]["id"], "basis": "STATUTORY",
             "expected_case_version": version},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_BASIS_NOT_ALLOWED)
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS")
        assert demand["status"] == "DRAFT"

    def test_demand_issue_window_closes_60_days_after_adjudication(self, api):
        """PRD §3.6: "Only a `DRAFT` demand can be issued, and only while its
        case is `INTERVIEWED` or `ADJUDICATING`; moreover, once the case
        carries an `adjudicated_at`, issuance must happen no later than sixty
        days after that instant (`ERR_DEMAND_WINDOW_CLOSED`)."

        The "only while INTERVIEWED or ADJUDICATING" gate forecloses issuing
        on a closed case, so the window is exercised the one way PRD admits:
        each case is adjudicated at the default instant 2026-08-01T00:00:00Z,
        then reopened (§3.5 reopen clears `closed_at` and cancels DRAFT
        demands; `adjudicated_at` persists) and walked back to ADJUDICATING,
        where a fresh demand is drafted. Issuance at exactly +60 days
        succeeds; at +60d+1s it fails with ERR_DEMAND_WINDOW_CLOSED.

        Design: Corner/validations/demand_issue_window_closes_60_days_after_adjudication
        """
        store = make_store(store_number="S067", name="Store 67")
        make_period(store["id"])
        demands = []
        for start, end in (("2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"),
                           ("2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")):
            ctx = setup_case_interviewed(store["id"], manual_loss_cents=10000,
                                         scheduled_start=start, scheduled_end=end)
            case_id = ctx["case"]["id"]
            draft_demand(case_id, ANALYST_1, basis="ACTUAL_LOSS")
            advance_case(case_id, ANALYST_1)  # INTERVIEWED -> ADJUDICATING
            adjudicate_case(case_id, MANAGER_1, decision="SUBSTANTIATED")
            # Reopen within the 30-day window, then walk back to ADJUDICATING
            # (evidence from setup is still ACTIVE, so the evidence gate and
            # the documented-interview road out of READY_FOR_INTERVIEW pass).
            validate_success(api.reopen_case(
                case_id, {"reason": "new leads"}, make_manager_headers(MANAGER_1)
            ))
            advance_case(case_id, ANALYST_1)  # INVESTIGATING -> READY_FOR_INTERVIEW
            interview = schedule_interview(case_id, ANALYST_1, ANALYST_1,
                                           scheduled_start=start,
                                           scheduled_end=end)
            hold_interview(interview["id"], ANALYST_1)
            document_interview(interview["id"], ANALYST_1)  # -> INTERVIEWED
            advance_case(case_id, ANALYST_1)  # INTERVIEWED -> ADJUDICATING
            demands.append(draft_demand(case_id, ANALYST_1, basis="ACTUAL_LOSS"))
        set_clock("2026-09-30T00:00:00Z")  # adjudicated_at + 60 days exactly
        resp_ok = api.issue_civil_demand(demands[0]["id"],
                                         make_manager_headers(MANAGER_1))
        assert validate_success(resp_ok)["status"] == "ISSUED", (
            "exactly 60 days is inside the window"
        )
        set_clock("2026-09-30T00:00:01Z")  # one second past
        resp_late = api.issue_civil_demand(demands[1]["id"],
                                           make_manager_headers(MANAGER_1))
        validate_error(resp_late, ApiErrorId.ERR_DEMAND_WINDOW_CLOSED)


class TestWriteOffCap:
    def test_write_off_cap_boundary_50000_inclusive(self, api):
        """PRD §3.6: "A write-off moves an `ISSUED` or `PARTIALLY_PAID` demand
        to `WRITTEN_OFF`, but only when `outstanding_cents` is at most 50000
        cents (`ERR_WRITE_OFF_CAP_EXCEEDED`); the case's `restitution_status`
        then recomputes, becoming `NONE` if that was the last collectible
        demand."

        Outstanding 60000 is over the cap; after a 10000 payment posts,
        outstanding 50000 is exactly at the cap and write-off succeeds.

        Design: Corner/errors/write_off_cap_boundary_50000_inclusive
        """
        store = make_store(store_number="S088", name="Store 88")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=50000, basis="STATUTORY",
            priors_offense_count=0,
        )
        demand_id = ctx["demand"]["id"]
        assert ctx["demand"]["amount_due_cents"] == 60000
        resp = api.write_off_civil_demand(demand_id, make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_CAP_EXCEEDED)
        record_and_post_payment(demand_id, 10000)
        after_pay = validate_success(
            api.get_civil_demand(demand_id, make_manager_headers(MANAGER_1))
        )
        assert after_pay["outstanding_cents"] == 50000, "exactly at the cap"
        resp2 = api.write_off_civil_demand(demand_id, make_manager_headers(MANAGER_1))
        assert validate_success(resp2)["status"] == "WRITTEN_OFF"


class TestDemandOcc:
    def test_occ_demand_create_stale_case_version_and_supersede(self, api):
        """PRD §2.8: "Drafting a civil demand requires the request to carry
        `expected_case_version` equal to the target case's current `version`.
        If the case's version has advanced since the client last observed it —
        for instance because an earlier draft already superseded and cancelled
        a prior draft — the request is rejected with `ERR_STALE_CASE_VERSION`
        (HTTP 412). Because a fresh draft legitimately supersedes a prior
        `DRAFT` (the prior draft is automatically cancelled), a second request
        carrying the now-current version succeeds; only a stale
        `expected_case_version` fails."
        PRD §3.6: "Drafting supersedes: any existing `DRAFT` demand on the case
        is automatically `CANCELLED`, the new demand starts in `DRAFT` with
        `created_by` stamped, and the case's `version` increments by one, which
        is exactly what makes a second drafter's stale `expected_case_version`
        fail."

        Design: Corner/cross_cutting_complexity_layers/occ_demand_create_stale_case_version_and_supersede
        """
        store = make_store(store_number="S400", name="Store 400")
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=10000)
        v = get_case(ctx["case"]["id"])["version"]
        d1 = draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS",
                          expected_case_version=v)
        assert d1["status"] == "DRAFT"
        # Same stale version again -> 412.
        resp = api.create_civil_demand(
            {"case_id": ctx["case"]["id"], "basis": "ACTUAL_LOSS",
             "recovery_cost_cents": 2500, "expected_case_version": v},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)
        v2 = get_case(ctx["case"]["id"])["version"]
        assert v2 == v + 1, "one version increment per successful draft"
        d2 = draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS",
                          recovery_cost_cents=2500, expected_case_version=v2)
        assert d2["status"] == "DRAFT"
        d1_after = validate_success(
            api.get_civil_demand(d1["id"], make_manager_headers(MANAGER_1))
        )
        assert d1_after["status"] == "CANCELLED", "superseded by the newer draft"
        assert get_case(ctx["case"]["id"])["version"] == v + 2
