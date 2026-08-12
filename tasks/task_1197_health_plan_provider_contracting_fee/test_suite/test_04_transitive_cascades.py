"""Transitive cascades: go-live activation and termination finalization."""
from test_helpers import (
    get_success_data,
    add_continuity_case, create_paid_claim_payload,
    setup_contract_active, setup_contract_with_retro_run, setup_issued_notice,
    set_clock, create_termination_notice_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CM = TEST_USERS["contract_manager_headers"]
PI = TEST_USERS["payment_integrity_headers"]


class TestGoLiveRetroCascade:
    def _setup(self, api):
        """Contract ACTIVE (v1 EFFECTIVE) -> paid claims -> amendment v2 VALIDATED
        with retro date -> READY_FOR_GO_LIVE. Returns artefacts before second
        approve-go-live."""
        return setup_contract_with_retro_run(
            claim_specs=[
                {"claim_number": "CLM-1", "service_date": "2026-08-10",
                 "billed_cents": 15000, "paid_cents": 10000},
                {"claim_number": "CLM-2", "service_date": "2026-08-20",
                 "billed_cents": 20000, "paid_cents": 15000},
            ],
            v2_effective_date="2026-09-01", v2_retro_effective_date="2026-08-01",
            v2_pct_of_medicare_bps=12000,
        )

    def test_approve_go_live_drives_contract_and_version_transitions(self, api):
        """PRD §3.7: "The contract moves from `READY_FOR_GO_LIVE` to `ACTIVE` and
        its `version` increments; its `VALIDATED` version cascades from
        `VALIDATED` to `EFFECTIVE`, appending `VERSION_EFFECTIVE`; any previously
        `EFFECTIVE` version of the same contract cascades from `EFFECTIVE` to
        `SUPERSEDED`, appending `VERSION_SUPERSEDED`"

        Design: Difficulty/transitive_cascade/go_live_retro_cascade
        """
        artefacts = self._setup(api)
        contract = get_success_data(api.get_contract(artefacts["contract"]["id"], ADMIN))
        assert contract["contract_status"] == "ACTIVE"

        v2 = get_success_data(api.get_contract_version(artefacts["v2"]["id"], ADMIN))
        v1 = get_success_data(api.get_contract_version(artefacts["v1"]["id"], ADMIN))
        assert v2["version_status"] == "EFFECTIVE"
        assert v1["version_status"] == "SUPERSEDED"

    def test_retro_run_spawned_with_half_open_window(self, api):
        """PRD §3.7: "when the newly effective version carries a
        `retro_effective_date` earlier than its own `effective_date`, a retro
        adjustment run is spawned under that version in `CREATED` state (its
        `run_status`), with `window_start_date` set to the retro date and
        `window_end_date` set to the effective date."

        Design: Difficulty/transitive_cascade/go_live_retro_cascade
        """
        artefacts = self._setup(api)
        run = artefacts["run"]
        assert run["run_status"] == "CREATED"
        assert run["window_start_date"] == "2026-08-01"
        assert run["window_end_date"] == "2026-09-01"


class TestTerminationFinalizeCascade:
    def _setup(self, api):
        """ACTIVE contract with PASSED batch; ISSUED notice; one NOTIFIED case and
        one IDENTIFIED case; clock advanced to termination_date."""
        artefacts = setup_issued_notice()
        contract = artefacts["contract"]
        notice = artefacts["notice"]

        case_n = add_continuity_case(
            notice["id"], member_ref="M-N",
            condition_category="ONCOLOGY_TREATMENT", treatment_end_date="2026-12-01")
        get_success_data(api.notify_case(case_n["id"], CM))
        case_i = add_continuity_case(
            notice["id"], member_ref="M-I",
            condition_category="DIALYSIS", treatment_end_date="2026-10-01")
        set_clock("2026-08-15T00:00:00Z")
        return artefacts, case_n, case_i

    def test_finalize_drives_notice_and_contract_transitions(self, api):
        """PRD §3.9: "A successful finalization moves the notice from `ISSUED` to
        `EFFECTIVE` and fires the termination cascade: the contract moves from
        `TERMINATION_NOTICE` to `TERMINATED`"

        Design: Difficulty/transitive_cascade/termination_finalize_cascade
        """
        artefacts, _, _ = self._setup(api)
        notice = artefacts["notice"]
        finalized = get_success_data(api.finalize_notice(notice["id"], ADMIN))
        assert finalized["notice_status"] == "EFFECTIVE"
        contract = get_success_data(api.get_contract(artefacts["contract"]["id"], ADMIN))
        assert contract["contract_status"] == "TERMINATED"

    def test_finalize_conditional_cascade_hits_only_notified_cases(self, api):
        """PRD §3.9: "every continuity-of-care case of the notice standing
        `NOTIFIED` moves to `ACTIVE_COVERAGE`, while cases still `IDENTIFIED` are
        left untouched; and every simulation batch under every version of the
        contract standing `OPEN`, `PRICED`, or `FAILED` moves to `CLOSED`, while
        `PASSED` batches are preserved untouched."

        Design: Difficulty/transitive_cascade/termination_finalize_cascade
        """
        artefacts, case_n, case_i = self._setup(api)
        notice = artefacts["notice"]
        get_success_data(api.finalize_notice(notice["id"], ADMIN))

        case_n_after = get_success_data(api.get_continuity_case(case_n["id"], ADMIN))
        case_i_after = get_success_data(api.get_continuity_case(case_i["id"], ADMIN))
        assert case_n_after["case_status"] == "ACTIVE_COVERAGE"
        assert case_i_after["case_status"] == "IDENTIFIED"

        batch = get_success_data(api.get_simulation_batch(artefacts["batch"]["id"], ADMIN))
        assert batch["batch_status"] == "PASSED"

    def test_coverage_end_date_is_min_of_termination_plus_90_and_treatment_end(self, api):
        """PRD §3.9: "At creation the case computes its `coverage_end_date` as the
        earlier of two dates: the notice's `termination_date` advanced by ninety
        days, or the case's own `treatment_end_date`."

        Design: Difficulty/transitive_cascade/termination_finalize_cascade
        """
        artefacts, case_n, _ = self._setup(api)
        # min(2026-08-15 + 90 days, 2026-12-01) = 2026-11-13
        assert case_n["coverage_end_date"] == "2026-11-13"
