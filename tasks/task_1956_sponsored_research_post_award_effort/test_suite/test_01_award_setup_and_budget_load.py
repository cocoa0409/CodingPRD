"""Award creation defaults, budget load rules, and the activation gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_sponsor_payload, create_person_payload, create_award_payload,
    create_budget_line_payload, create_effort_commitment_payload,
    make_sponsor, make_person, make_award, make_budget_line,
    setup_sponsor_pi, create_active_award, assert_effort_commitment,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]


class TestAwardCreateDefaults:
    def test_award_create_copies_sponsor_terms(self, api):
        """PRD §3.1: "Three fields are copied from the sponsor at creation and
        pinned to the award forever: `salary_cap_annual_cents`,
        `f_and_a_rate_bps`, and `payment_method` — later sponsor edits never
        propagate."

        Design: Corner/entities/award_create_copies_sponsor_terms_and_defaults
        """
        sponsor = make_sponsor(salary_cap_annual_cents=20_000_000,
                               f_and_a_rate_bps=5000,
                               payment_method="LETTER_OF_CREDIT")
        pi = make_person()
        award = validate_success(api.create_award(
            create_award_payload(sponsor["id"], pi["id"], award_number="C-001"),
            SPO), 201)
        assert award["salary_cap_annual_cents"] == 20_000_000
        assert award["f_and_a_rate_bps"] == 5000
        assert award["payment_method"] == "LETTER_OF_CREDIT"

    def test_award_create_defaults(self, api):
        """PRD §3.1: "The new award starts in `PENDING_SETUP` with `posture`
        `OPEN`, `current_end_date` equal to `original_end_date`, `nce_count` 0,
        all computed aggregates (`mtdc_spent_cents`, `f_and_a_accrued_cents`,
        `total_direct_spent_cents`, `cost_share_met_cents`,
        `cumulative_drawn_cents`, `reserved_draw_cents`,
        `available_draw_pool_cents`) at 0, `residual_deobligated_cents` null,
        and a system-created `F_AND_A` budget line with `authorized_cents` 0."

        Design: Corner/entities/award_create_copies_sponsor_terms_and_defaults
        """
        sponsor = make_sponsor()
        pi = make_person()
        award = validate_success(api.create_award(
            create_award_payload(sponsor["id"], pi["id"], award_number="C-001",
                                 total_obligated_cents=150_000), SPO), 201)
        assert award["status"] == "PENDING_SETUP"
        assert award["posture"] == "OPEN"
        assert award["version"] == 1
        assert award["current_end_date"] == "2026-12-31T00:00:00Z"
        assert award["nce_count"] == 0
        assert award["residual_deobligated_cents"] is None
        fa_lines = validate_success(api.list_budget_lines(
            GA, params={"award_id": award["id"], "category": "F_AND_A"}), 200)
        fa_rows = fa_lines if isinstance(fa_lines, list) else fa_lines
        assert fa_rows[0]["authorized_cents"] == 0


class TestActivationExactCent:
    """Difficulty boundary instance: activation grand-total equality."""

    def _award_with_travel_100k(self, api, award_number, obligated):
        sponsor, pi = setup_sponsor_pi()
        award = make_award(sponsor["id"], pi["id"], award_number, obligated)
        make_budget_line(award["id"], "TRAVEL", 100_000)
        return award

    def test_activation_one_cent_short_rejected(self, api):
        """PRD §3.1: "A `SponsoredProgramsOfficer` activates the award only when
        the grand total — directs-authorized plus the computed `F_AND_A`
        authorization — equals `total_obligated_cents` exactly; one cent under
        or over fails with `ERR_BUDGET_NOT_FULLY_ALLOCATED`."

        Design: Difficulty/boundary_precision_check/activation_allocation_exact_cent
        """
        award = self._award_with_travel_100k(api, "A1-001", 149_999)
        res = api.activate_award(award["id"], SPO)
        validate_error(res, ApiErrorId.ERR_BUDGET_NOT_FULLY_ALLOCATED.value)

    def test_activation_exact_match_activates(self, api):
        """PRD §3.1: "On success the award moves `PENDING_SETUP → ACTIVE`,
        every line's `baseline_authorized_cents` is set equal to its current
        `authorized_cents` (the sponsor-approved baseline against which later
        rebudget significance is measured), posture is recomputed, and the
        award's `version` increments."

        Design: Difficulty/boundary_precision_check/activation_allocation_exact_cent
        """
        award = self._award_with_travel_100k(api, "A2-001", 150_000)
        activated = validate_success(api.activate_award(award["id"], SPO), 200)
        assert activated["status"] == "ACTIVE"


class TestBudgetLoadGuards:
    def test_f_and_a_line_manual_create_rejected(self, api):
        """PRD §3.1: "The `F_AND_A` category is system-managed: attempting to
        create or modify an `F_AND_A` line by hand is rejected with
        `ERR_F_AND_A_LINE_SYSTEM_MANAGED`."

        Design: Corner/errors/f_and_a_line_manual_create_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award = make_award(sponsor["id"], pi["id"], "FA-001", 150_000)
        res = api.create_budget_line(
            create_budget_line_payload(award["id"], category="F_AND_A",
                                       authorized_cents=50_000), GC)
        validate_error(res, ApiErrorId.ERR_F_AND_A_LINE_SYSTEM_MANAGED.value)

    def test_subaward_mtdc_eligible_exceeds_authorized_rejected(self, api):
        """PRD §3.1: "On a `SUBAWARDS` line the caller may declare
        `mtdc_eligible_cents` — the portion counting toward MTDC, typically
        the first 25,000 USD per planned subaward — which must not exceed the
        line's `authorized_cents` (`ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED`) and
        defaults to 0; on any other category the field is meaningless."

        Design: Corner/errors/subaward_line_mtdc_eligible_exceeds_authorized_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award = make_award(sponsor["id"], pi["id"], "ME-001", 150_000)
        res = api.create_budget_line(
            create_budget_line_payload(award["id"], category="SUBAWARDS",
                                       authorized_cents=100_000,
                                       mtdc_eligible_cents=250_000), GC)
        validate_error(res, ApiErrorId.ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED.value)


class TestCommitmentDefaultsAndImmutability:
    def _active_award(self, api, award_number):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], award_number,
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        return sponsor, pi, award

    def test_commitment_default_is_key_personnel_false(self, api):
        """PRD §3.2: "A `GrantCoordinator` records an `EffortCommitment`
        naming `award_id`, `person_id`, `committed_effort_pct` (greater than 0
        and at most 100, with two decimal places), and optionally
        `is_key_personnel` (default false) — key personnel trigger the 75%
        reduction floor at certification time."

        Design: Corner/entities/commitment_default_is_key_personnel_false
        """
        _, pi, award = self._active_award(api, "C-003")
        commitment = validate_success(api.create_effort_commitment(
            create_effort_commitment_payload(award["id"], pi["id"],
                                             committed_effort_pct=25.0), GC), 201)
        assert commitment["is_key_personnel"] is False

    def test_commitment_immutability_no_version_field(self, api):
        """PRD §2.4: "The exception is `EffortCommitment`: commitments carry
        only `id` and `created_at`, with no `updated_at` and no `version`,
        because a commitment is immutable once recorded."

        Design: Corner/entities/commitment_immutability_no_version_field
        """
        _, pi, award = self._active_award(api, "C-007")
        commitment = validate_success(api.create_effort_commitment(
            create_effort_commitment_payload(award["id"], pi["id"],
                                             committed_effort_pct=25.0,
                                             is_key_personnel=True), GC), 201)
        assert_effort_commitment(commitment)

    def test_duplicate_commitment_rejected(self, api):
        """PRD §3.2: "Commitments may be recorded while the award is
        `PENDING_SETUP` or `ACTIVE`, the pair (`award_id`, `person_id`) is
        unique (a duplicate returns `ERR_DUPLICATE_COMMITMENT`), and — unlike
        other resources — a commitment carries only `id` and `created_at`,
        never `updated_at` or `version`."

        Design: Corner/errors/duplicate_commitment_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        pa = make_person(ibs=24_000_000, full_name="P. Alpha")
        award, _ = create_active_award(
            sponsor["id"], pi["id"], "DC-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        validate_success(api.create_effort_commitment(
            create_effort_commitment_payload(award["id"], pa["id"],
                                             committed_effort_pct=25.0), GC), 201)
        res = api.create_effort_commitment(
            create_effort_commitment_payload(award["id"], pa["id"],
                                             committed_effort_pct=30.0), GC)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_COMMITMENT.value)


class TestFAndAEvaluationOrder:
    """Difficulty instance: pinned F&A evaluation order at budget load."""

    _LINES = [
        {"category": "PERSONNEL_SALARIES", "authorized_cents": 5_000_000},
        {"category": "FRINGE_BENEFITS", "authorized_cents": 1_500_000},
        {"category": "EQUIPMENT", "authorized_cents": 2_000_000},
        {"category": "TRAVEL", "authorized_cents": 500_000},
        {"category": "SUBAWARDS", "authorized_cents": 3_000_000,
         "mtdc_eligible_cents": 2_500_000},
        {"category": "OTHER_DIRECT", "authorized_cents": 1_000_000},
    ]

    def _build(self, api, award_number, obligated):
        sponsor, pi = setup_sponsor_pi()
        award = make_award(sponsor["id"], pi["id"], award_number, obligated)
        for spec in self._LINES:
            kwargs = {}
            if "mtdc_eligible_cents" in spec:
                kwargs["mtdc_eligible_cents"] = spec["mtdc_eligible_cents"]
            make_budget_line(award["id"], spec["category"],
                             spec["authorized_cents"], **kwargs)
        return award

    def test_f_and_a_computed_over_mtdc_base(self, api):
        """PRD §3.1: "after each direct-line load the system recomputes the
        `F_AND_A` line's authorization over authorized bases: it sums
        `authorized_cents` over every non-`F_AND_A` line to get
        directs-authorized, subtracts the authorizations of `EQUIPMENT`,
        `PARTICIPANT_SUPPORT`, and `SUBAWARDS` lines and adds back the
        `mtdc_eligible_cents` declared on `SUBAWARDS` lines to get the
        MTDC-authorized base, multiplies by the award's pinned
        `f_and_a_rate_bps` (basis points over ten thousand), rounds half-up to
        cents, and stamps the result as the `F_AND_A` line's
        `authorized_cents`."

        Design: Difficulty/combinatorial_formula/f_and_a_evaluation_order_at_budget_load
        """
        award = self._build(api, "H-001", 18_250_000)
        fa_lines = validate_success(api.list_budget_lines(
            GA, params={"award_id": award["id"], "category": "F_AND_A"}), 200)
        # MTDC base = 13000000 - 2000000 - 3000000 + 2500000 = 10500000;
        # F&A = round(0.5 * 10500000) = 5250000.
        assert fa_lines[0]["authorized_cents"] == 5_250_000

    def test_activation_succeeds_at_exact_total_and_fails_one_cent_over(self, api):
        """PRD §3.1: "A `SponsoredProgramsOfficer` activates the award only when
        the grand total — directs-authorized plus the computed `F_AND_A`
        authorization — equals `total_obligated_cents` exactly; one cent under
        or over fails with `ERR_BUDGET_NOT_FULLY_ALLOCATED`."

        Design: Difficulty/combinatorial_formula/f_and_a_evaluation_order_at_budget_load
        """
        award = self._build(api, "H-001", 18_250_000)
        activated = validate_success(api.activate_award(award["id"], SPO), 200)
        assert activated["status"] == "ACTIVE"

        award2 = self._build(api, "H-002", 18_250_001)
        res = api.activate_award(award2["id"], SPO)
        validate_error(res, ApiErrorId.ERR_BUDGET_NOT_FULLY_ALLOCATED.value)


class TestShapeAndExistence:
    def test_get_award_not_found_returns_404(self, api):
        """PRD §2.7: "When several validation rules could fire on the same
        request, the server evaluates them in a fixed priority order and
        returns only the first failure." The order includes "(4) existence of
        path ids and body foreign-key references, validated left-to-right —
        path first, then body fields in declared order — with one 404 error per
        resource type" — including `ERR_AWARD_NOT_FOUND`.

        Design: Corner/entities/get_award_not_found_returns_404
        """
        res = api.get_award("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", GA)
        validate_error(res, ApiErrorId.ERR_AWARD_NOT_FOUND.value)

    def test_sponsor_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.7: the validation order ends with "(13) request shape
        (`ERR_INVALID_REQUEST`)." PRD §3.1: "A `SponsoredProgramsOfficer`
        registers the sponsor with its `name`, a `sponsor_type` drawn from
        `FEDERAL`, `FEDERAL_FLOW_THROUGH`, `INDUSTRY`, `FOUNDATION`, or
        `STATE`, and a `payment_method` of `LETTER_OF_CREDIT`,
        `COST_REIMBURSABLE_INVOICE`, or `FIXED_PRICE_SCHEDULE` — the payment
        method is inherited by every award created under the sponsor."

        Design: Corner/entities/sponsor_create_missing_required_returns_invalid_request
        """
        res = api.create_sponsor(
            {"sponsor_type": "FEDERAL", "payment_method": "LETTER_OF_CREDIT",
             "f_and_a_rate_bps": 5000}, SPO)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_subaward_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.5: "An officer creates it in `DRAFT` under `award_id`,
        naming `subrecipient_name`, a `total_subaward_cents` ceiling strictly
        greater than zero, a `risk_rating` of `LOW`, `MEDIUM`, or `HIGH`, and
        the subaward period `start_date` to `end_date` (end strictly after
        start)." PRD §2.7: the validation order ends with "(13) request shape
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/subaward_create_invalid_enum_returns_invalid_request
        """
        sponsor, pi = setup_sponsor_pi()
        award, _ = create_active_award(
            sponsor["id"], pi["id"], "C-006",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        res = api.create_subaward(
            {"award_id": award["id"], "subrecipient_name": "Sub X",
             "total_subaward_cents": 100_000, "risk_rating": "EXTREME",
             "start_date": "2026-01-01T00:00:00Z",
             "end_date": "2026-12-31T00:00:00Z"}, SPO)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
