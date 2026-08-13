"""Census recording, participant-count determination, and the audit threshold."""
from test_helpers import (
    NON_EXISTENT_UUID,
    SPONSOR,
    ApiErrorId,
    add_participant,
    api_client,
    bulk_import,
    bulk_import_payload,
    create_engagement,
    create_engagement_payload,
    create_participant_payload,
    get_success_data,
    recompute_count,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEngagementCreation:

    def test_create_missing_plan_year_start_rejected(self):
        """PRD §3.1: "A `SponsorAdmin` opens an engagement by supplying the plan
        sponsor's employer identification number in `sponsor_ein`, the three-digit
        plan number in `plan_number`, the formal plan name in `plan_name`, and the
        plan-year bounds."
        PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

        Design: Corner/entities/engagement_create_missing_required_field_returns_invalid_request
        """
        payload = create_engagement_payload()
        del payload["plan_year_start"]
        resp = api_client.create_engagement(payload, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_create_returns_computed_defaults_regardless_of_input(self):
        """PRD §3.1: "A new engagement is created in `DRAFT` status with `posture`
        `ON_TRACK`. Its four computed filing-determination fields —
        `participant_count_beginning`, `audit_required`, `required_schedule_type`,
        and `remittance_standard_days` — are all null until the first
        participant-count recomputation."

        Design: Corner/entities/engagement_computed_fields_input_ignored
        """
        payload = create_engagement_payload(
            plan_type="DC", audit_required=True, posture="BLOCKED")
        eng = validate_success(api_client.create_engagement(payload, SPONSOR),
                               expected_status=201)
        assert eng["status"] == "DRAFT"
        assert eng["posture"] == "ON_TRACK", (
            f"client-supplied posture must not stick; got {eng['posture']}"
        )
        assert eng["audit_required"] is None, (
            "audit_required is computed and must be null before the first recompute"
        )
        assert eng["participant_count_beginning"] is None
        assert eng["required_schedule_type"] is None
        assert eng["remittance_standard_days"] is None


class TestParticipantRecording:

    def test_participant_status_defaults_active(self):
        """PRD §3.3: "The `status` field defaults to `ACTIVE` when omitted and may
        otherwise be set to `SEPARATED_WITH_BALANCE`, `SEPARATED_NO_BALANCE`,
        `RETIRED_WITH_BALANCE`, or `DECEASED`."
        PRD §3.3: "It equals the `opening_balance_cents` plus matched contributions
        plus executed corrective deposits, minus executed corrective distributions".

        Design: Corner/entities/participant_default_status_active
        """
        eng = create_engagement()
        participant = validate_success(
            api_client.create_participant(
                create_participant_payload(eng["id"], "P-001", opening_balance_cents=0),
                SPONSOR),
            expected_status=201)
        assert participant["status"] == "ACTIVE"
        assert participant["account_balance_cents"] == 0

    def test_get_nonexistent_participant_returns_404(self):
        """PRD §2.6: "among several identifiers the first one (reading left to
        right) that does not correspond to an existing resource causes immediate
        rejection with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_participant_returns_not_found
        """
        resp = api_client.get_participant(NON_EXISTENT_UUID, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_list_participants_pagination(self):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, with a minimum allowed value of
        1 and a maximum of 100. The `offset` parameter sets the number of items to
        skip and defaults to 0."
        PRD §2.3: "List responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/list_participants_pagination_envelope
        """
        eng = create_engagement()
        bulk_import(eng["id"], 3, "PG", opening_balance_cents=0)
        data, meta = validate_paginated(
            api_client.list_participants(
                SPONSOR, params={"engagement_id": eng["id"], "limit": 2, "offset": 0}))
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_duplicate_external_ref_rejected_but_scoped_per_engagement(self):
        """PRD §3.3: "A duplicate `external_ref` within the same engagement is
        rejected with `ERR_DUPLICATE_PARTICIPANT_REF` (HTTP 409)."
        PRD §3.3: "a sponsor-side `external_ref` that must be unique within the
        engagement".

        Design: Corner/validations/duplicate_participant_ref_rejected
        """
        eng_a = create_engagement(plan_name="DupRef Plan A")
        eng_b = create_engagement(plan_name="DupRef Plan B")
        get_success_data(api_client.create_participant(
            create_participant_payload(eng_a["id"], "P-001"), SPONSOR))
        resp_dup = api_client.create_participant(
            create_participant_payload(eng_a["id"], "P-001"), SPONSOR)
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_PARTICIPANT_REF)
        other = validate_success(
            api_client.create_participant(
                create_participant_payload(eng_b["id"], "P-001"), SPONSOR),
            expected_status=201)
        assert other["engagement_id"] == eng_b["id"]


class TestParticipantCountDetermination:

    def test_count_excludes_zero_balance_separated_and_deceased(self):
        """PRD §3.2: "The counted population is the set of participants of the
        engagement whose `is_eligible` is true and whose `status` is `ACTIVE` or
        `RETIRED_WITH_BALANCE` (always counted), together with participants whose
        `status` is `SEPARATED_WITH_BALANCE` or `DECEASED` and whose
        `account_balance_cents` is greater than zero. Participants in
        `SEPARATED_NO_BALANCE` status, and separated or deceased participants with
        a zero balance, are excluded."

        Design: Corner/calculations/participant_count_excludes_zero_balance_separated
        """
        eng = create_engagement()
        add_participant(eng["id"], "A-001", opening_balance_cents=100_000)
        add_participant(eng["id"], "A-002", opening_balance_cents=100_000)
        add_participant(eng["id"], "S-001", status="SEPARATED_WITH_BALANCE",
                        compensation_cy_cents=0, opening_balance_cents=250_000)
        add_participant(eng["id"], "S-002", status="SEPARATED_NO_BALANCE",
                        compensation_cy_cents=0, opening_balance_cents=0)
        add_participant(eng["id"], "D-001", status="DECEASED",
                        compensation_cy_cents=0, opening_balance_cents=0)
        eng = recompute_count(eng["id"])
        assert eng["participant_count_beginning"] == 3, (
            f"2 ACTIVE + 1 separated-with-balance = 3, got {eng['participant_count_beginning']}"
        )
        assert eng["required_schedule_type"] == "I"

    def test_exactly_100_participants_requires_audit(self):
        """PRD §3.2: "Under the standard rule, the plan is a large plan requiring
        an audit when the count is at least 100 — the comparison is
        boundary-inclusive, so a count of exactly 100 requires the audit."

        Design: Difficulty/boundary_precision_check/participant_count_exactly_100_audit_threshold
        """
        eng = create_engagement(prior_year_schedule_type="NONE_FIRST_YEAR")
        bulk_import(eng["id"], 100, "LP")
        eng = recompute_count(eng["id"])
        assert eng["participant_count_beginning"] == 100
        assert eng["audit_required"] is True
        assert eng["required_schedule_type"] == "H"

    def test_99_participants_stays_small_plan(self):
        """PRD §3.2: "Under the standard rule, the plan is a large plan requiring
        an audit when the count is at least 100 — the comparison is
        boundary-inclusive, so a count of exactly 100 requires the audit."
        PRD §3.2: "`audit_required` is set to that boolean, and
        `required_schedule_type` is `H` when the audit is required, `I` otherwise."

        Design: Difficulty/boundary_precision_check/participant_count_exactly_100_audit_threshold
        """
        eng = create_engagement(prior_year_schedule_type="NONE_FIRST_YEAR")
        bulk_import(eng["id"], 99, "MP")
        eng = recompute_count(eng["id"])
        assert eng["participant_count_beginning"] == 99
        assert eng["audit_required"] is False
        assert eng["required_schedule_type"] == "I"

    def test_standard_variant_110_participants_is_large_plan(self):
        """PRD §3.2: "The two variants therefore diverge sharply for identical
        census data: a 110-participant plan that filed Schedule `I` last year is a
        large plan (Schedule `H`, audit required, 3-day remittance standard) under
        the standard rule, but files as a small plan (Schedule `I`, no audit,
        7-day remittance standard) under a valid election."

        Design: Difficulty/dual_variant_calc/participant_count_standard_vs_80120_election
        """
        eng = create_engagement(prior_year_schedule_type="I", use_80120_election=False)
        bulk_import(eng["id"], 110, "E1P")
        eng = recompute_count(eng["id"])
        assert eng["participant_count_beginning"] == 110
        assert eng["audit_required"] is True
        assert eng["required_schedule_type"] == "H"
        assert eng["remittance_standard_days"] == 3

    def test_80120_election_110_participants_is_small_plan(self):
        """PRD §3.2: "Under the 80-120 election — which applies only when
        `use_80120_election` is true, `prior_year_schedule_type` is `I`, and the
        count is at least 80 and at most 120 — the plan elects small-plan
        treatment: `audit_required` is set to false and `required_schedule_type`
        to `I`."
        PRD §3.2: "The remittance standard itself is 7 business days when
        `required_schedule_type` is `I` and 3 business days otherwise."

        Design: Difficulty/dual_variant_calc/participant_count_standard_vs_80120_election
        """
        eng = create_engagement(prior_year_schedule_type="I", use_80120_election=True)
        bulk_import(eng["id"], 110, "E2P")
        eng = recompute_count(eng["id"])
        assert eng["participant_count_beginning"] == 110
        assert eng["audit_required"] is False
        assert eng["required_schedule_type"] == "I"
        assert eng["remittance_standard_days"] == 7
