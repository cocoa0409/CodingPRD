"""Deposit assessment variants, tiers, boundary, and the deposit ledger."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_deposit_transaction,
    create_developer,
    create_project,
    find_ledger_entry,
    get_project,
    list_deposit_ledger,
    make_developer_headers,
    post_deposit,
    setup_developer_and_cluster,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_project,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestDepositVariantSelection:
    def test_deposit_expedited_flat_for_small_storage(self, api):
        """PRD §3.2: "if the `technology` is `STORAGE` and the `capacity_mw` is at
        most five MW, the project follows the **EXPEDITED** track and its required
        deposit is a flat 300000 cents, regardless of capacity or service type."
        PRD §3.2: "Concretely, an identical five-MW `ENERGY_ONLY` project would owe
        500000 cents under STANDARD but pays only 300000 cents under EXPEDITED —
        the divergence between the two tracks is intentional."

        Design: Difficulty/dual_variant_calc/deposit_standard_vs_expedited_storage_flat
        """
        developer, cluster = setup_developer_and_cluster()
        storage = create_project(developer["id"], cluster["id"],
                                 project_name="Battery A", technology="STORAGE",
                                 capacity_mw=5, point_of_interconnection="SUB-7")
        assert storage["deposit_required_cents"] == 300000, (
            "EXPEDITED flat 300000 for STORAGE at exactly 5 MW"
        )
        assert storage["status"] == "SUBMITTED"

    def test_deposit_standard_for_identical_solar(self, api):
        """PRD §3.2: "Every other project follows the **STANDARD** track: the first
        twenty MW of nameplate are billed at 100000 cents per MW"
        PRD §3.2: "Concretely, an identical five-MW `ENERGY_ONLY` project would owe
        500000 cents under STANDARD but pays only 300000 cents under EXPEDITED —
        the divergence between the two tracks is intentional."

        Design: Difficulty/dual_variant_calc/deposit_standard_vs_expedited_storage_flat
        """
        developer, cluster = setup_developer_and_cluster()
        solar = create_project(developer["id"], cluster["id"], project_name="Solar A",
                               technology="SOLAR", capacity_mw=5,
                               point_of_interconnection="SUB-8")
        assert solar["deposit_required_cents"] == 500000, (
            "STANDARD: 5 * 100000 = 500000; identical capacity and service type "
            "isolate the variant selection"
        )
        assert solar["status"] == "SUBMITTED"

    def test_deposit_expedited_cutoff_at_6mw_storage(self, api):
        """PRD §3.2: "if the `technology` is `STORAGE` and the `capacity_mw` is at
        most five MW, the project follows the **EXPEDITED** track"
        PRD §3.2: "Every other project follows the **STANDARD** track: the first
        twenty MW of nameplate are billed at 100000 cents per MW"

        Design: Corner/calculations/deposit_expedited_cutoff_boundary
        """
        developer, cluster = setup_developer_and_cluster()
        battery = create_project(developer["id"], cluster["id"], project_name="Bat6",
                                 technology="STORAGE", capacity_mw=6,
                                 point_of_interconnection="SUB-6")
        assert battery["deposit_required_cents"] == 600000, (
            "6 MW STORAGE is above the five-MW EXPEDITED window: 6 * 100000 "
            "STANDARD tier 1"
        )


class TestDepositTieringAndMultiplier:
    def test_deposit_25mw_capacity_service(self, api):
        """PRD §3.2: "the first twenty MW of nameplate are billed at 100000 cents
        per MW, any nameplate beyond twenty MW is billed at 250000 cents per MW,
        and the resulting base is then multiplied by 1.0 for `ENERGY_ONLY` service
        or by 1.2 for `CAPACITY` service, with the product rounded half-up to whole
        cents."

        Design: Difficulty/combinatorial_formula/deposit_tiered_multifactor_capacity_service
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"],
                                 project_name="WindCap", technology="WIND",
                                 capacity_mw=25, service_type="CAPACITY",
                                 point_of_interconnection="SUB-10")
        assert project["deposit_required_cents"] == 3900000, (
            "(20*100000 + 5*250000) * 1.2 = 3900000"
        )

    def test_deposit_25mw_energy_only(self, api):
        """PRD §3.2: "the resulting base is then multiplied by 1.0 for
        `ENERGY_ONLY` service or by 1.2 for `CAPACITY` service, with the product
        rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/deposit_tiered_multifactor_capacity_service
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"], project_name="WindEo",
                                 technology="WIND", capacity_mw=25,
                                 service_type="ENERGY_ONLY",
                                 point_of_interconnection="SUB-11")
        assert project["deposit_required_cents"] == 3250000, (
            "20*100000 + 5*250000 = 3250000; the 650000-cent delta vs CAPACITY "
            "isolates the service-type multiplier at a tier-straddling capacity"
        )

    def test_deposit_at_exactly_20mw_tier1_only(self, api):
        """PRD §3.2: "the first twenty MW of nameplate are billed at 100000 cents
        per MW, any nameplate beyond twenty MW is billed at 250000 cents per MW"

        Design: Difficulty/boundary_precision_check/deposit_tier_boundary_at_20mw
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"], project_name="At20",
                                 capacity_mw=20, point_of_interconnection="SUB-20")
        assert project["deposit_required_cents"] == 2000000, (
            "exactly 20 MW stays entirely in tier 1: 20 * 100000"
        )

    def test_deposit_just_over_20mw_spills_into_tier2(self, api):
        """PRD §3.2: "the first twenty MW of nameplate are billed at 100000 cents
        per MW, any nameplate beyond twenty MW is billed at 250000 cents per MW"

        Design: Difficulty/boundary_precision_check/deposit_tier_boundary_at_20mw
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"], project_name="Over20",
                                 capacity_mw=20.5, point_of_interconnection="SUB-21")
        assert project["deposit_required_cents"] == 2125000, (
            "2000000 + 0.5 * 250000 = 2125000: the 0.5 MW spill bills at tier 2"
        )


class TestDepositLedger:
    def test_deposit_ledger_immutable_running_balance(self, api):
        """PRD §3.2: "Each posting carries an `amount_cents` and appends a ledger
        entry whose `tx_type` is `DEPOSIT`, whose `project_id` ties it to the
        project, and whose `balance_after_cents` records the running
        `deposit_posted_cents` immediately after the entry is applied"
        PRD §2.4: "Two resource kinds are deliberately lighter: `DepositTransaction`
        and `CurtailmentLimit` and `TransparencyReport` carry only `id` and
        `created_at` — `updated_at` and `version` are absent from them entirely"

        Design: Corner/entities/deposit_ledger_immutable_and_running_balance
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])

        resp = api.post_deposit(project["id"], {"amount_cents": 600000},
                                make_developer_headers(developer["id"]))
        tx1 = validate_success(resp, expected_status=201)
        assert_deposit_transaction(tx1)
        assert tx1["tx_type"] == "DEPOSIT"
        assert tx1["balance_after_cents"] == 600000

        resp = api.post_deposit(project["id"], {"amount_cents": 400000},
                                make_developer_headers(developer["id"]))
        tx2 = validate_success(resp, expected_status=201)
        assert_deposit_transaction(tx2)
        assert tx2["balance_after_cents"] == 1000000, "running balance accumulates"

        ledger = list_deposit_ledger(project["id"])
        assert len(ledger) == 2
        for entry in ledger:
            assert_deposit_transaction(entry)

        after = get_project(project["id"])
        assert after["status"] == "QUEUED"
        assert after["queue_position"] == 1

    def test_deposit_overpayment_rejected(self, api):
        """PRD §3.2: "A deposit that would push `deposit_posted_cents` above
        `deposit_required_cents` is refused with `ERR_DEPOSIT_OVERPAYMENT`
        (HTTP 422) — overpayment is never booked."

        Design: Corner/validations/deposit_overpayment_rejected
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        post_deposit(project["id"], developer["id"], 600000)

        resp = api.post_deposit(project["id"], {"amount_cents": 400001},
                                make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_OVERPAYMENT)
        assert get_project(project["id"])["deposit_posted_cents"] == 600000, (
            "rejected deposit did not apply"
        )

    def test_deposit_ownership_violation_forbidden(self, api):
        """PRD §2.1: "In practice this means a `Developer` caller may only act on
        projects whose `developer_id` equals their `X-User-ID` — for child
        resources such as deposit ledger entries, milestone submissions, and
        agreements, ownership is resolved through the parent project. A `Developer`
        caller who touches a project belonging to someone else is rejected with
        `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/deposit_ownership_violation_forbidden
        """
        dev_a = create_developer(legal_name="Acme Renewables LLC",
                                 contact_email="a@acme.example")
        dev_b = create_developer(legal_name="Beta Power Co",
                                 contact_email="q@beta.example",
                                 developer_type="UTILITY_SCALE")
        _dev, cluster = setup_developer_and_cluster(developer_name="Gamma Grid LLC")
        project = create_project(dev_a["id"], cluster["id"])

        resp = api.post_deposit(project["id"], {"amount_cents": 100000},
                                make_developer_headers(dev_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)
        assert get_project(project["id"])["deposit_posted_cents"] == 0


class TestDepositValidationPriority:
    def test_deposit_on_withdrawn_project_reports_state_error(self, api):
        """PRD §2.8: "Sixth, state preconditions of the target resource are
        evaluated (the state-rejection family, all HTTP 409)."
        PRD §2.8: "Tenth and last, the deposit-ledger fiscal check runs
        (`ERR_DEPOSIT_OVERPAYMENT`, HTTP 422). Where two rules from different
        categories could both fire on the same request, the earlier category's
        error wins."
        PRD §3.2: "Deposits are accepted only while the project is in `SUBMITTED`
        or `QUEUED`; a posting at any other time is rejected with
        `ERR_PROJECT_NOT_ACCEPTING_DEPOSITS`."

        Design: Difficulty/priority_pair_validation_conflict/deposit_state_beats_fiscal_on_withdrawn_project
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        withdraw_project(project["id"])

        # 1500000 would also overpay the 1000000 requirement; the state error
        # (category six) must win over the fiscal error (category ten).
        resp = api.post_deposit(project["id"], {"amount_cents": 1500000},
                                make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACCEPTING_DEPOSITS)

    def test_deposit_on_withdrawn_project_leaves_ledger_untouched(self, api):
        """PRD §3.7: "When `deposit_posted_cents` is greater than zero, the system
        appends a `FORFEIT` ledger entry for the forfeited amount and — only when
        the refund portion is itself greater than zero — a `REFUND` entry for the
        remainder"
        PRD §3.2: "Deposits are accepted only while the project is in `SUBMITTED`
        or `QUEUED`; a posting at any other time is rejected with
        `ERR_PROJECT_NOT_ACCEPTING_DEPOSITS`."

        Design: Difficulty/priority_pair_validation_conflict/deposit_state_beats_fiscal_on_withdrawn_project
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        withdraw_project(project["id"])

        api.post_deposit(project["id"], {"amount_cents": 1500000},
                         make_developer_headers(developer["id"]))
        ledger, meta = _list_ledger(api, project["id"])
        assert meta["total_count"] == 0 and ledger == [], (
            "no DEPOSIT booked; the SUBMITTED withdrawal posted 0 so no "
            "FORFEIT/REFUND rows either"
        )



def _list_ledger(api, project_id):
    return validate_paginated(api.list_deposits(project_id, ADMIN))
