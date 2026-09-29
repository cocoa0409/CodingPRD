"""State machine transitions: initial states, legal edges, guarded refusals, loops and lockdown.

Every test in this module translates exactly one instance of the `state_machines`
section of SCAFFOLD_CORNER_DESIGN.yaml.  Each test starts against an empty
database whose logical clock reads its startup value of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    OFFICER_ASSEMBLER_ID,
    OFFICER_PREPARER_ID,
    REVIEWER_ONE_ID,
    SIMPLE_REQUIREMENT_SPECS,
    TEST_USERS,
    ApiErrorId,
    acknowledge_calendar,
    api_client,
    assemble,
    assert_score,
    assert_version_incremented,
    attest_item,
    classify_placement,
    confirm,
    create_annual_report_filing,
    create_bond_issue,
    create_content_requirement,
    create_cycle,
    create_engagement,
    create_failure_notice_filing,
    create_notice,
    create_official_statement,
    create_placement,
    create_undertaking,
    defease_issue,
    determine_notice,
    get_success_data,
    is_iso8601_timestamp,
    item_of_kind,
    list_content_items,
    list_notices,
    make_agent_headers,
    make_officer_headers,
    prepare_item,
    read_bond_issue,
    read_content_item,
    read_cycle,
    read_engagement,
    read_filing,
    read_undertaking,
    record_rating_action,
    reject,
    resubmit,
    run_sweep,
    set_clock,
    setup_cycle,
    setup_cycle_with_engagement,
    setup_issue_with_undertaking,
    submit,
    validate_error,
    validate_paginated,
    waive_item,
)

FD = TEST_USERS["finance_director_headers"]
OFFICER = TEST_USERS["disclosure_officer_headers"]
ASSEMBLER = TEST_USERS["assembler_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
SECOND_REVIEWER = TEST_USERS["second_reviewer_headers"]

# The design's issues all carry one hundred million cents of par, which is the
# denominator the placement materiality ratio and the legal escrow floor read.
DESIGN_PAR_CENTS = 100000000

# PRD §3.3 opens a FY2026 cycle over 2025-07-01..2026-06-30; with the default
# 210-day filing window that lands the due date on 2027-01-26.
FY2026_DUE_DATE = "2027-01-26"

SPLIT_WEIGHT_SPECS = [
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 6000},
    {
        "kind": "BUDGET_SUMMARY",
        "label": "Adopted Budget Summary",
        "weight_bp": 4000,
        "waivable": True,
    },
]

AUDITED_ONLY_SPECS = [
    {"kind": "AUDITED_FINANCIALS", "label": "Audited Financial Statements", "weight_bp": 10000},
]

WAIVABLE_PAIR_SPECS = [
    {"kind": "DEBT_SERVICE_SCHEDULE", "label": "Debt Service Schedule", "weight_bp": 5000},
    {
        "kind": "ENTERPRISE_STATISTICS",
        "label": "Enterprise Statistics",
        "weight_bp": 5000,
        "waivable": True,
    },
]

DESIGN_ENGAGEMENT = {
    "agent_name": "Meridian Dissemination LLC",
    "effective_date": "2026-08-01",
    "expiration_date": "2027-12-31",
    "retainer_cents": 400000,
}


def assert_startup_clock_stamp(value, label: str = "timestamp"):
    """PRD §2.5 pins every `*_at` field to the logical clock, which starts at 2026-08-01T00:00:00Z."""
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )
    assert str(value)[:19] == "2026-08-01T00:00:00", (
        f"{label} must be stamped from the logical clock's startup instant "
        f"2026-08-01T00:00:00.000Z, got {value!r}"
    )


def total_count_of(response) -> int:
    """The size of a list endpoint's full filtered result set (PRD §2.3)."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# --------------------------------------------------------------------------- #
# Composite preconditions the framework's fixtures.py does not already build
# --------------------------------------------------------------------------- #

def setup_split_weight_cycle() -> dict:
    """A FY2026 cycle over a 6000-bp non-waivable item and a 4000-bp waivable one."""
    return setup_cycle(
        specs=SPLIT_WEIGHT_SPECS,
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
    )


def setup_audited_cycle() -> dict:
    """A FY2026 cycle whose single 10000-bp item demands an audit opinion."""
    return setup_cycle(
        specs=AUDITED_ONLY_SPECS,
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
    )


def setup_waivable_pair_cycle() -> dict:
    """A FY2026 cycle carrying one waivable and one non-waivable 5000-bp item."""
    return setup_cycle(
        specs=WAIVABLE_PAIR_SPECS,
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
    )


def setup_drafted_annual_report() -> dict:
    """A READY_TO_FILE FY2026 cycle, an ACTIVE engagement, and a DRAFT ANNUAL_REPORT filing."""
    context = setup_cycle_with_engagement(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
        engagement=dict(DESIGN_ENGAGEMENT),
    )
    context["filing"] = create_annual_report_filing(
        context["issue"]["id"], context["cycle"]["id"]
    )
    return context


def setup_delinquent_cycle_with_live_failure_filing() -> dict:
    """A swept-DELINQUENT FY2025 cycle carrying one SUBMITTED FAILURE_TO_FILE_NOTICE filing."""
    context = setup_cycle(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue={"dated_date": "2024-04-01", "original_par_amount_cents": DESIGN_PAR_CENTS},
        cycle={
            "fiscal_year_label": "FY2025",
            "period_start_date": "2024-07-01",
            "period_end_date": "2025-06-30",
        },
    )
    context["sweep"] = run_sweep()
    context["cycle"] = read_cycle(context["cycle"]["id"])
    context["engagement"] = create_engagement(
        context["undertaking"]["id"], **dict(DESIGN_ENGAGEMENT)
    )
    filing = create_failure_notice_filing(context["issue"]["id"], context["cycle"]["id"])
    context["filing"] = submit(filing["id"], context["engagement"]["id"])
    return context


class TestInitialStates:
    """The declared initial state of every entity that owns a state machine."""

    def test_every_entity_starts_in_its_declared_initial_state(self):
        """A freshly created row of each entity reports the initial state its machine declares.

        PRD §3.1: "A freshly registered issue opens in `status` `OUTSTANDING` with `version` 1."
        PRD §3.2: "A new undertaking opens with `status` `ACTIVE`, `compliance_posture` `COMPLIANT`, `remediation_tier` `TIER_0`, `disclosure_risk_score` 0.00, `version` 1, and null `suspended_reason` and `termination_cause`."
        PRD §3.3: "The cycle itself opens in `status` `DRAFTING` with `version` 1, `completeness_score_pct` 0.00, `days_late` 0, and null `assembled_by_user_id`, `assembled_at`, `filed_filing_id`, `filed_at`, `timeliness_basis_applied`, and `withdrawal_reason`."
        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.5: "The notice opens in `status` `DETERMINATION_PENDING`, `version` 1, `days_late` 0, and records `created_by_user_id` from `X-User-ID`; `determination_note`, `determined_by_user_id`, `determined_at`, `rating_agency`, `prior_rating`, `new_rating`, and `filed_filing_id` all start null."
        PRD §3.6: "The placement opens at `status` `RECEIVED`, `version` 1, with `linked_notice_id` and `waiver_reason` null."
        PRD §3.9: "The draft opens at `status` `DRAFT`, `version` 1, `disclosure_adequacy` `UNKNOWN`, `required_disclosure_event_ids` empty, and `required_disclosure_event_count` 0, with `reviewed_by_user_id`, `reviewed_at`, `posted_by_user_id`, and `posted_at` all null."
        PRD §3.10: "The engagement opens at `status` `ACTIVE`, `version` 1, `billable_filing_count` 0, with `superseded_by_engagement_id` and `termination_reason` null."
        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        issue = create_bond_issue(original_par_amount_cents=DESIGN_PAR_CENTS)
        assert issue["status"] == "OUTSTANDING", (
            f"A freshly registered issue must open OUTSTANDING, got {issue['status']}"
        )

        undertaking = create_undertaking(issue["id"], fiscal_year_end_month_day="06-30")
        assert undertaking["status"] == "ACTIVE", (
            f"A new undertaking must open ACTIVE, got {undertaking['status']}"
        )
        assert undertaking["compliance_posture"] == "COMPLIANT", (
            "The undertaking's second state machine must independently open COMPLIANT, "
            f"got {undertaking['compliance_posture']}"
        )

        requirement = create_content_requirement(
            undertaking["id"],
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=10000,
        )
        cycle = create_cycle(
            undertaking["id"],
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        assert cycle["status"] == "DRAFTING", (
            f"A new cycle must open DRAFTING, got {cycle['status']}"
        )

        items = list_content_items(cycle["id"], content_requirement_id=requirement["id"])
        assert len(items) == 1, (
            f"Cycle creation must cascade exactly one item per requirement, got {len(items)}"
        )
        assert items[0]["status"] == "NOT_STARTED", (
            "The cascade-created content item must land in its own initial state "
            f"NOT_STARTED, got {items[0]['status']}"
        )

        notice = create_notice(
            issue["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
        )
        assert notice["status"] == "DETERMINATION_PENDING", (
            f"A new notice must open DETERMINATION_PENDING, got {notice['status']}"
        )

        placement = create_placement(
            issue["id"],
            lender_name="Harbor Trust Bank",
            principal_amount_cents=3000000,
            execution_date="2026-07-28",
            review_window_start_date="2026-08-01",
            review_window_end_date="2026-08-10",
            disclosure_practice="VOLUNTARY",
        )
        assert placement["status"] == "RECEIVED", (
            f"A new direct placement must open RECEIVED, got {placement['status']}"
        )

        statement = create_official_statement(issue["id"], dated_date="2027-03-01")
        assert statement["status"] == "DRAFT", (
            f"A new official statement must open DRAFT, got {statement['status']}"
        )

        engagement = create_engagement(undertaking["id"], **dict(DESIGN_ENGAGEMENT))
        assert engagement["status"] == "ACTIVE", (
            f"A new engagement must open ACTIVE, got {engagement['status']}"
        )


class TestAssembleTransition:
    """DRAFTING -> READY_TO_FILE, with all three declared side effects."""

    def test_item_progression_records_draft_ready_and_waived_readiness_factors(self):
        """Preparing, attesting and waiving move an item through its own three readiness factors.

        PRD §3.3: "Supplied fields overwrite their stored values and omitted fields are left untouched, so partial preparation is a legitimate repeat operation rather than an error: the first such update advances the item from `NOT_STARTED` to `DRAFT`, and every subsequent one is a `DRAFT` to `DRAFT` self-loop."
        PRD §3.3: "Either way `readiness_factor` becomes 0.5 and the cycle's `completeness_score_pct` is re-derived, which matters even on the self-loop because changing `audit_opinion_type` changes the item's opinion multiplier."
        PRD §3.3: "On success the item records `attested_by_user_id` from `X-User-ID` and `attested_at` from the logical clock, and `readiness_factor` becomes 1.0."
        PRD §3.3: "A waived item takes `readiness_factor` 1.0 and contributes its **full** weight to completeness."
        Design: Corner/state_machines/assemble_moves_the_cycle_to_ready_to_file_and_stamps_the_assembler
        """
        context = setup_split_weight_cycle()
        item_a = item_of_kind(context["items"], context["requirements"], "OPERATING_DATA_TABLE")
        item_b = item_of_kind(context["items"], context["requirements"], "BUDGET_SUMMARY")

        drafted = prepare_item(
            item_a["id"],
            data_as_of_date="2026-06-30",
            source_document_ref="OPDATA-FY2026.pdf",
        )
        assert drafted["status"] == "DRAFT", (
            f"The first progress update must advance the item to DRAFT, got {drafted['status']}"
        )
        assert float(drafted["readiness_factor"]) == pytest.approx(0.5, abs=0.01), (
            f"A DRAFT item carries readiness_factor 0.5, got {drafted['readiness_factor']}"
        )

        readied = attest_item(item_a["id"], user_id=OFFICER_PREPARER_ID)
        assert readied["status"] == "READY", (
            f"Attesting a DRAFT item must move it to READY, got {readied['status']}"
        )
        assert float(readied["readiness_factor"]) == pytest.approx(1.0, abs=0.01), (
            f"A READY item carries readiness_factor 1.0, got {readied['readiness_factor']}"
        )
        assert readied["attested_by_user_id"] == OFFICER_PREPARER_ID, (
            "attested_by_user_id must be stamped from X-User-ID, got "
            f"{readied['attested_by_user_id']}"
        )
        assert_startup_clock_stamp(readied["attested_at"], "attested_at")

        waived = waive_item(
            item_b["id"],
            waiver_reason="Budget adopted after the reporting deadline; no comparable table exists.",
        )
        assert waived["status"] == "WAIVED", (
            f"A waivable item must move to WAIVED, got {waived['status']}"
        )
        assert float(waived["readiness_factor"]) == pytest.approx(1.0, abs=0.01), (
            f"A waived item takes readiness_factor 1.0, got {waived['readiness_factor']}"
        )

    def test_assemble_stamps_the_assembler_and_scores_a_waived_item_at_full_weight(self):
        """Assembling a 6000-READY plus 4000-WAIVED cycle lands READY_TO_FILE at 100.00.

        PRD §3.4: "Either way the cycle lands in `READY_TO_FILE`."
        PRD §3.4: "A successful assembly stamps `assembled_by_user_id` from `X-User-ID` and `assembled_at` from the logical clock, and re-derives `completeness_score_pct`."
        PRD §3.3: "A waived item takes `readiness_factor` 1.0 and contributes its **full** weight to completeness."
        PRD §2.4: "The `version` field is the value optimistic concurrency compares against, so its discipline is strict: if a request changes any persisted field of a row, that row's `version` advances by one and its `updated_at` is refreshed."
        Design: Corner/state_machines/assemble_moves_the_cycle_to_ready_to_file_and_stamps_the_assembler
        """
        context = setup_split_weight_cycle()
        assert context["cycle"]["due_date"] == FY2026_DUE_DATE, (
            "A period ending 2026-06-30 plus the default 210-day window rolls forward to "
            f"{FY2026_DUE_DATE}, got {context['cycle']['due_date']}"
        )

        item_a = item_of_kind(context["items"], context["requirements"], "OPERATING_DATA_TABLE")
        item_b = item_of_kind(context["items"], context["requirements"], "BUDGET_SUMMARY")
        prepare_item(
            item_a["id"],
            data_as_of_date="2026-06-30",
            source_document_ref="OPDATA-FY2026.pdf",
        )
        attest_item(item_a["id"], user_id=OFFICER_PREPARER_ID)
        waive_item(
            item_b["id"],
            waiver_reason="Budget adopted after the reporting deadline; no comparable table exists.",
        )

        before = read_cycle(context["cycle"]["id"])
        assembled = assemble(context["cycle"]["id"], user_id=OFFICER_ASSEMBLER_ID)

        assert assembled["status"] == "READY_TO_FILE", (
            f"Assembly must land the cycle in READY_TO_FILE, got {assembled['status']}"
        )
        assert assembled["assembled_by_user_id"] == OFFICER_ASSEMBLER_ID, (
            "assembled_by_user_id must be stamped from X-User-ID, got "
            f"{assembled['assembled_by_user_id']}"
        )
        assert_startup_clock_stamp(assembled["assembled_at"], "assembled_at")
        assert_score(
            assembled["completeness_score_pct"], 100.00, "completeness_score_pct"
        )
        assert_version_incremented(
            assembled["version"], before["version"], min_increment=1
        )

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["open_obligation_count"] == 1, (
            "A READY_TO_FILE cycle is still an open obligation, so open_obligation_count "
            f"must be 1, got {undertaking['open_obligation_count']}"
        )
        assert undertaking["compliance_posture"] == "COMPLIANT", (
            f"Nothing here is late, so the posture stays COMPLIANT, got {undertaking['compliance_posture']}"
        )


class TestAttestReadinessOrder:
    """DRAFT -> READY, guarded by two readiness sub-checks in a pinned order."""

    def test_attest_reports_the_missing_data_as_of_before_the_missing_audit_opinion(self):
        """With both readiness fields absent the data-as-of refusal fires, not the opinion refusal.

        PRD §3.3: "Two readiness conditions are checked in order: `source_document_ref` and `data_as_of_date` must both be non-null, failing which the attestation is refused with `ERR_CONTENT_DATA_AS_OF_REQUIRED`; and then, when the item's underlying `ContentRequirement` has `requires_audit_opinion` true, `audit_opinion_type` must be non-null, failing which the attestation is refused with `ERR_AUDIT_OPINION_REQUIRED`."
        Design: Corner/state_machines/attest_enforces_data_as_of_before_audit_opinion
        """
        context = setup_audited_cycle()
        requirement = context["requirements"][0]
        assert requirement["requires_audit_opinion"] is True, (
            "An AUDITED_FINANCIALS requirement must compute requires_audit_opinion true, got "
            f"{requirement['requires_audit_opinion']}"
        )
        item = context["items"][0]
        preparer = make_officer_headers(OFFICER_PREPARER_ID)

        drafted = get_success_data(
            api_client.update_content_item(
                item["id"], {"source_document_ref": "CAFR-FY2026.pdf"}, preparer
            )
        )
        assert drafted["status"] == "DRAFT", (
            f"The first progress update must advance the item to DRAFT, got {drafted['status']}"
        )

        validate_error(
            api_client.attest_content_item(item["id"], preparer),
            ApiErrorId.ERR_CONTENT_DATA_AS_OF_REQUIRED.value,
        )

        get_success_data(
            api_client.update_content_item(
                item["id"], {"data_as_of_date": "2026-06-30"}, preparer
            )
        )
        validate_error(
            api_client.attest_content_item(item["id"], preparer),
            ApiErrorId.ERR_AUDIT_OPINION_REQUIRED.value,
        )

    def test_attest_succeeds_once_the_qualified_opinion_lands_and_scores_eighty(self):
        """A QUALIFIED opinion lets the item reach READY while capping the cycle score at 80.00.

        PRD §3.3: "Supplied fields overwrite their stored values and omitted fields are left untouched, so partial preparation is a legitimate repeat operation rather than an error: the first such update advances the item from `NOT_STARTED` to `DRAFT`, and every subsequent one is a `DRAFT` to `DRAFT` self-loop."
        PRD §3.3: "On success the item records `attested_by_user_id` from `X-User-ID` and `attested_at` from the logical clock, and `readiness_factor` becomes 1.0."
        PRD §3.3: "Where the requirement does demand an opinion, the multiplier is 1.0 for an `UNMODIFIED` opinion, 0.8 for a `QUALIFIED` one, 0.5 for `UNAUDITED_INTERIM`, and 0.0 when `audit_opinion_type` is still null."
        Design: Corner/state_machines/attest_enforces_data_as_of_before_audit_opinion
        """
        context = setup_audited_cycle()
        item = context["items"][0]
        preparer = make_officer_headers(OFFICER_PREPARER_ID)

        get_success_data(
            api_client.update_content_item(
                item["id"], {"source_document_ref": "CAFR-FY2026.pdf"}, preparer
            )
        )
        get_success_data(
            api_client.update_content_item(
                item["id"], {"data_as_of_date": "2026-06-30"}, preparer
            )
        )
        still_draft = get_success_data(
            api_client.update_content_item(
                item["id"], {"audit_opinion_type": "QUALIFIED"}, preparer
            )
        )
        assert still_draft["status"] == "DRAFT", (
            "A second progress update is a DRAFT to DRAFT self-loop, not a promotion, got "
            f"{still_draft['status']}"
        )

        readied = attest_item(item["id"], user_id=OFFICER_PREPARER_ID)
        assert readied["status"] == "READY", (
            f"Attestation must move the item to READY, got {readied['status']}"
        )
        assert float(readied["readiness_factor"]) == pytest.approx(1.0, abs=0.01), (
            f"A READY item carries readiness_factor 1.0, got {readied['readiness_factor']}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert_score(cycle["completeness_score_pct"], 80.00, "completeness_score_pct")


class TestDefeasanceEscrowFloor:
    """OUTSTANDING -> DEFEASED, guarded by a defeasance_type dependent escrow floor."""

    def test_the_escrow_floor_depends_on_the_defeasance_type(self):
        """The same 99999999 cents is refused as a LEGAL escrow yet accepted as an ECONOMIC one.

        PRD §3.1: "Escrow must actually fund the retirement: for a `LEGAL` defeasance, `escrow_deposit_cents` must be at least the issue's current `outstanding_par_amount_cents`; for an `ECONOMIC` defeasance, `escrow_deposit_cents` must be at least 1 cent."
        PRD §3.1: "A shortfall is refused with `ERR_ESCROW_INSUFFICIENT`, and because this is a fiscal check it sits near the bottom of the ladder — a defeasance attempt on an already-`DEFEASED` issue reports `ERR_INVALID_STATE_TRANSITION` instead."
        PRD §3.1: "Both endings drive `outstanding_par_amount_cents` to 0, advance the issue's `version`, and fire the same four-hop termination cascade."
        Design: Corner/state_machines/defease_requires_escrow_at_least_equal_to_outstanding_par
        """
        issue_a = create_bond_issue(
            series_designation="2026A", original_par_amount_cents=DESIGN_PAR_CENTS
        )
        issue_b = create_bond_issue(
            series_designation="2026B", original_par_amount_cents=DESIGN_PAR_CENTS
        )

        validate_error(
            api_client.defease_bond_issue(
                issue_a["id"],
                {
                    "defeasance_type": "LEGAL",
                    "escrow_deposit_cents": 99999999,
                    "occurrence_date": "2026-08-01",
                },
                FD,
            ),
            ApiErrorId.ERR_ESCROW_INSUFFICIENT.value,
        )
        validate_error(
            api_client.defease_bond_issue(
                issue_b["id"],
                {
                    "defeasance_type": "ECONOMIC",
                    "escrow_deposit_cents": 0,
                    "occurrence_date": "2026-08-01",
                },
                FD,
            ),
            ApiErrorId.ERR_ESCROW_INSUFFICIENT.value,
        )

        defeased_b = defease_issue(
            issue_b["id"],
            defeasance_type="ECONOMIC",
            escrow_deposit_cents=99999999,
            occurrence_date="2026-08-01",
        )
        assert defeased_b["status"] == "DEFEASED", (
            "The very escrow LEGAL refused clears the ECONOMIC one-cent floor, got "
            f"{defeased_b['status']}"
        )
        assert defeased_b["defeasance_type"] == "ECONOMIC", (
            f"defeasance_type must be stamped ECONOMIC, got {defeased_b['defeasance_type']}"
        )
        assert defeased_b["escrow_deposit_cents"] == 99999999, (
            "escrow_deposit_cents must record the deposit exactly, got "
            f"{defeased_b['escrow_deposit_cents']}"
        )
        assert defeased_b["outstanding_par_amount_cents"] == 0, (
            "Defeasance drives outstanding_par_amount_cents to 0, got "
            f"{defeased_b['outstanding_par_amount_cents']}"
        )
        assert_startup_clock_stamp(defeased_b["defeased_at"], "defeased_at")
        assert defeased_b["open_material_event_count"] == 1, (
            "The defeasance notice minted after the void pass is the one surviving open "
            f"event, so open_material_event_count must be 1, got {defeased_b['open_material_event_count']}"
        )

    def test_legal_defeasance_accepts_escrow_exactly_equal_to_par_and_mints_its_own_notice(self):
        """Escrow equal to outstanding par satisfies the LEGAL floor and mints a DEFEASANCE notice.

        PRD §3.1: "Escrow must actually fund the retirement: for a `LEGAL` defeasance, `escrow_deposit_cents` must be at least the issue's current `outstanding_par_amount_cents`; for an `ECONOMIC` defeasance, `escrow_deposit_cents` must be at least 1 cent."
        PRD §3.1: "Defeasance is itself a listed event, so after the void pass has finished the defeasance path mints one further `MaterialEventNotice` on the issue: `event_type` `DEFEASANCE`, `occurrence_date` taken from the request body, `status` `DETERMINATION_PENDING`, `per_se_material` true, `created_by_user_id` set from `X-User-ID`, and `filing_deadline_date` derived from the ten-business-day rule."
        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        Design: Corner/state_machines/defease_requires_escrow_at_least_equal_to_outstanding_par
        """
        issue = create_bond_issue(
            series_designation="2026A", original_par_amount_cents=DESIGN_PAR_CENTS
        )

        defeased = defease_issue(
            issue["id"],
            defeasance_type="LEGAL",
            escrow_deposit_cents=DESIGN_PAR_CENTS,
            occurrence_date="2026-08-01",
        )
        assert defeased["status"] == "DEFEASED", (
            "Escrow exactly equal to outstanding par clears the LEGAL floor because the "
            f"comparison is at-least, not strictly-greater, got {defeased['status']}"
        )
        assert defeased["outstanding_par_amount_cents"] == 0, (
            "Defeasance drives outstanding_par_amount_cents to 0, got "
            f"{defeased['outstanding_par_amount_cents']}"
        )

        notices = list_notices(issue_id=issue["id"])
        assert total_count_of(
            api_client.list_material_event_notices(
                FD, params={"issue_id": issue["id"], "limit": 100}
            )
        ) == 1, "Defeasance mints exactly one notice of its own"
        notice = notices[0]
        assert notice["event_type"] == "DEFEASANCE", (
            f"The minted notice must carry event_type DEFEASANCE, got {notice['event_type']}"
        )
        assert notice["status"] == "DETERMINATION_PENDING", (
            "The defeasance notice is minted after the void pass, so it survives in "
            f"DETERMINATION_PENDING, got {notice['status']}"
        )
        assert notice["per_se_material"] is True, (
            f"DEFEASANCE is a per-se listed event, got per_se_material {notice['per_se_material']}"
        )
        assert notice["filing_deadline_date"] == "2026-08-14", (
            "The tenth business day strictly after 2026-08-01 is 2026-08-14, got "
            f"{notice['filing_deadline_date']}"
        )


class TestWaiveGate:
    """NOT_STARTED -> WAIVED, gated on the snapshot parent's waivable flag."""

    def test_a_stated_reason_does_not_unlock_a_non_waivable_requirement(self):
        """Waiving an item whose requirement is not waivable is refused even with a reason supplied.

        PRD §3.2: "An optional `waivable` flag, false when omitted, records whether a `ComplianceReviewer` is permitted to waive the item on a cycle."
        PRD §3.3: "An item in `NOT_STARTED` or `DRAFT` moves to `WAIVED` on supply of a `waiver_reason`, but only when its underlying `ContentRequirement` has `waivable` true; otherwise the attempt is refused with `ERR_REQUIREMENT_NOT_WAIVABLE`."
        Design: Corner/state_machines/waive_requires_a_waivable_requirement_and_a_stated_reason
        """
        context = setup_waivable_pair_cycle()
        fixed_requirement = next(
            r for r in context["requirements"] if r["kind"] == "DEBT_SERVICE_SCHEDULE"
        )
        assert fixed_requirement["waivable"] is False, (
            "An omitted waivable flag must take its declared default of false, got "
            f"{fixed_requirement['waivable']}"
        )
        fixed_item = item_of_kind(
            context["items"], context["requirements"], "DEBT_SERVICE_SCHEDULE"
        )

        validate_error(
            api_client.waive_content_item(
                fixed_item["id"], {"waiver_reason": "Schedule unavailable."}, REVIEWER
            ),
            ApiErrorId.ERR_REQUIREMENT_NOT_WAIVABLE.value,
        )

        unchanged = read_content_item(fixed_item["id"])
        assert unchanged["status"] == "NOT_STARTED", (
            f"The refused waive must leave the item untouched, got {unchanged['status']}"
        )
        assert unchanged["waiver_reason"] is None, (
            f"The refused waive must not store a reason, got {unchanged['waiver_reason']!r}"
        )

    def test_waiving_the_waivable_half_scores_fifty_and_leaves_the_cycle_drafting(self):
        """A waived 5000-bp item contributes its full weight while its NOT_STARTED partner contributes nothing.

        PRD §3.3: "An item in `NOT_STARTED` or `DRAFT` moves to `WAIVED` on supply of a `waiver_reason`, but only when its underlying `ContentRequirement` has `waivable` true; otherwise the attempt is refused with `ERR_REQUIREMENT_NOT_WAIVABLE`."
        PRD §3.3: "A waived item takes `readiness_factor` 1.0 and contributes its **full** weight to completeness."
        PRD §3.3: "Each item in the set has a readiness factor — 1.0 when its `status` is `READY` or `WAIVED`, 0.5 when `DRAFT`, and 0.0 when `NOT_STARTED` — and an opinion multiplier that reflects the quality of the audit opinion behind it."
        Design: Corner/state_machines/waive_requires_a_waivable_requirement_and_a_stated_reason
        """
        context = setup_waivable_pair_cycle()
        open_item = item_of_kind(
            context["items"], context["requirements"], "ENTERPRISE_STATISTICS"
        )
        reason = "Enterprise statistics not produced for this fiscal year."

        waived = waive_item(open_item["id"], waiver_reason=reason)
        assert waived["status"] == "WAIVED", (
            f"A waivable item must move to WAIVED, got {waived['status']}"
        )
        assert float(waived["readiness_factor"]) == pytest.approx(1.0, abs=0.01), (
            f"A waived item takes readiness_factor 1.0, got {waived['readiness_factor']}"
        )
        assert waived["waiver_reason"] == reason, (
            f"waiver_reason must record the supplied text, got {waived['waiver_reason']!r}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert_score(cycle["completeness_score_pct"], 50.00, "completeness_score_pct")
        assert cycle["status"] == "DRAFTING", (
            f"Waiving one item does not assemble the cycle, got {cycle['status']}"
        )


class TestPerSeDetermination:
    """DETERMINATION_PENDING -> NOT_MATERIAL, closed off for per-se listed events."""

    def test_a_per_se_notice_cannot_be_determined_not_material_but_can_be_determined_material(self):
        """A RATING_CHANGE notice refuses the NOT_MATERIAL branch and accepts the MATERIAL one.

        PRD §3.1: "A rating change is a per-se listed event, so a single call both records the action and arms the disclosure clock: the service mints a `MaterialEventNotice` with `event_type` `RATING_CHANGE`, `per_se_material` set to true, `status` `DETERMINATION_PENDING`, its `rating_agency`, `prior_rating`, and `new_rating` stamped from the payload, and its `filing_deadline_date` derived from the ten-business-day rule of §3.5."
        PRD §3.1: "The issue's own `current_rating` and `current_rating_agency` are overwritten with `new_rating` and `rating_agency`, the issue's `version` advances, and `open_material_event_count` on the issue and `open_obligation_count` on the undertaking are both recomputed."
        PRD §3.5: "A per-se listed event can never be determined immaterial."
        PRD §3.5: "When `per_se_material` is true, a `NOT_MATERIAL` determination is refused with `ERR_PER_SE_EVENT_IS_MATERIAL`."
        Design: Corner/state_machines/determine_cannot_mark_a_per_se_material_event_not_material
        """
        issue = create_bond_issue(original_par_amount_cents=DESIGN_PAR_CENTS)

        notice = record_rating_action(
            issue["id"],
            rating_agency="MOODYS",
            prior_rating="Aa2",
            new_rating="Aa3",
            occurrence_date="2026-07-28",
        )
        assert notice["event_type"] == "RATING_CHANGE", (
            "The rating-actions call returns the minted MaterialEventNotice, got event_type "
            f"{notice['event_type']}"
        )
        assert notice["per_se_material"] is True, (
            f"RATING_CHANGE is a per-se listed event, got {notice['per_se_material']}"
        )
        assert notice["rating_agency"] == "MOODYS", (
            f"rating_agency must be stamped from the payload, got {notice['rating_agency']}"
        )
        assert notice["prior_rating"] == "Aa2", (
            f"prior_rating must be stamped from the payload, got {notice['prior_rating']}"
        )
        assert notice["new_rating"] == "Aa3", (
            f"new_rating must be stamped from the payload, got {notice['new_rating']}"
        )
        assert notice["filing_deadline_date"] == "2026-08-11", (
            "The tenth business day strictly after 2026-07-28 is 2026-08-11, got "
            f"{notice['filing_deadline_date']}"
        )

        reread_issue = read_bond_issue(issue["id"])
        assert reread_issue["current_rating"] == "Aa3", (
            f"current_rating must be overwritten with new_rating, got {reread_issue['current_rating']}"
        )
        assert reread_issue["current_rating_agency"] == "MOODYS", (
            "current_rating_agency must be overwritten with rating_agency, got "
            f"{reread_issue['current_rating_agency']}"
        )

        validate_error(
            api_client.determine_material_event_notice(
                notice["id"],
                {
                    "determination": "NOT_MATERIAL",
                    "determination_note": "Downgrade within the investment-grade band.",
                },
                REVIEWER,
            ),
            ApiErrorId.ERR_PER_SE_EVENT_IS_MATERIAL.value,
        )

        determined = determine_notice(
            notice["id"],
            determination="MATERIAL",
            determination_note="One-notch downgrade is material to holders.",
        )
        assert determined["status"] == "MATERIAL", (
            f"A per-se notice may still be determined MATERIAL, got {determined['status']}"
        )

    def test_only_the_material_notice_remains_in_the_open_set(self):
        """A non-per-se notice takes the NOT_MATERIAL branch and leaves the open event set.

        PRD §3.5: "`per_se_material` is true if and only if `event_type` is one of the four per-se listed events — `PRINCIPAL_PAYMENT_DELINQUENCY`, `RATING_CHANGE`, `DEFEASANCE`, `BOND_CALL` — and false for the other four."
        PRD §3.5: "Either way the notice records `determined_by_user_id` from `X-User-ID` and `determined_at` from the logical clock, and either way the source status must be `DETERMINATION_PENDING`."
        PRD §3.5: "A `NOT_MATERIAL` determination is terminal and releases the obligation: the notice leaves the open set, both counters fall, no `filing_deadline_date` enforcement ever applies to it again, the calendar sweep skips it permanently, and any later filing that names it is refused with `ERR_FILING_SUBJECT_MISMATCH`."
        Design: Corner/state_machines/determine_cannot_mark_a_per_se_material_event_not_material
        """
        issue = create_bond_issue(original_par_amount_cents=DESIGN_PAR_CENTS)
        rating_notice = record_rating_action(
            issue["id"],
            rating_agency="MOODYS",
            prior_rating="Aa2",
            new_rating="Aa3",
            occurrence_date="2026-07-28",
        )
        trustee_notice = create_notice(
            issue["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
        )
        assert trustee_notice["per_se_material"] is False, (
            "TRUSTEE_SUBSTITUTION is not one of the four per-se events, got "
            f"{trustee_notice['per_se_material']}"
        )
        assert trustee_notice["filing_deadline_date"] == "2026-08-11", (
            "The ten-business-day window is event-type independent, so the deadline is "
            f"2026-08-11, got {trustee_notice['filing_deadline_date']}"
        )

        immaterial = determine_notice(
            trustee_notice["id"],
            determination="NOT_MATERIAL",
            determination_note="Successor trustee is an affiliate; no economic effect.",
            user_id=REVIEWER_ONE_ID,
        )
        assert immaterial["status"] == "NOT_MATERIAL", (
            "A non-per-se notice may take the NOT_MATERIAL branch, got "
            f"{immaterial['status']}"
        )
        assert immaterial["determined_by_user_id"] == REVIEWER_ONE_ID, (
            "determined_by_user_id must be stamped from X-User-ID, got "
            f"{immaterial['determined_by_user_id']}"
        )
        assert_startup_clock_stamp(immaterial["determined_at"], "determined_at")

        determine_notice(rating_notice["id"], determination="MATERIAL")

        reread_issue = read_bond_issue(issue["id"])
        assert reread_issue["open_material_event_count"] == 1, (
            "Only the MATERIAL notice remains open once NOT_MATERIAL has left the open set, "
            f"so open_material_event_count must be 1, got {reread_issue['open_material_event_count']}"
        )


class TestSubmissionAttemptCeiling:
    """REJECTED -> SUBMITTED, and the shared three-attempt ceiling that ends it."""

    def test_a_rejection_does_not_refund_the_attempt_it_consumed(self):
        """submit, reject and resubmit share one counter, so a rejected attempt keeps its slot.

        PRD §3.7: "The draft opens at `status` `DRAFT`, `version` 1, `submission_attempt_count` 0, with `submitted_at`, `submitted_by_user_id`, `submitting_engagement_id`, `repository_receipt_id`, `repository_confirmed_at`, `rejection_reason`, and `superseded_by_filing_id` all null."
        PRD §3.7: "A successful submission sets `submitted_at` from the logical clock, `submitted_by_user_id` from `X-User-ID`, `submitting_engagement_id` to the resolved engagement, and raises `submission_attempt_count` by 1."
        PRD §3.7: "Recording a repository rejection requires a `rejection_reason` and moves a `SUBMITTED` filing to `REJECTED`; only the engagement in `submitting_engagement_id` may do it, and any other agent is refused with `ERR_AGENT_NOT_ENGAGED`."
        PRD §3.7: "It clears `rejection_reason` to null, **overwrites** `submitted_at` with the current clock instant, raises `submission_attempt_count`, re-stamps `submitting_engagement_id`, and drives the subject back into `FILING_IN_PROGRESS`."
        Design: Corner/state_machines/resubmit_requires_a_correction_reason_and_halts_after_three_attempts
        """
        context = setup_drafted_annual_report()
        filing_id = context["filing"]["id"]
        engagement_id = context["engagement"]["id"]

        assert context["filing"]["submission_attempt_count"] == 0, (
            "A DRAFT filing opens with submission_attempt_count 0, got "
            f"{context['filing']['submission_attempt_count']}"
        )

        submitted = submit(filing_id, engagement_id)
        assert submitted["status"] == "SUBMITTED", (
            f"Submission must move the filing to SUBMITTED, got {submitted['status']}"
        )
        assert submitted["submission_attempt_count"] == 1, (
            "The first submission raises submission_attempt_count to 1, got "
            f"{submitted['submission_attempt_count']}"
        )
        assert submitted["submitting_engagement_id"] == engagement_id, (
            "submitting_engagement_id must be the resolved engagement, got "
            f"{submitted['submitting_engagement_id']}"
        )

        rejected = reject(
            filing_id,
            engagement_id,
            rejection_reason="Repository schema validation failed on the operating-data table.",
        )
        assert rejected["status"] == "REJECTED", (
            f"Rejection must move the filing to REJECTED, got {rejected['status']}"
        )
        assert rejected["submission_attempt_count"] == 1, (
            "A rejection does not refund the attempt it consumed, so the count stays 1, got "
            f"{rejected['submission_attempt_count']}"
        )

        resubmitted = resubmit(
            filing_id, engagement_id, correction_reason="Reformatted the operating-data table."
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"Resubmission must move the filing back to SUBMITTED, got {resubmitted['status']}"
        )
        assert resubmitted["submission_attempt_count"] == 2, (
            "Resubmission consumes the second of the three shared attempts, got "
            f"{resubmitted['submission_attempt_count']}"
        )
        assert resubmitted["rejection_reason"] is None, (
            "Resubmission clears rejection_reason to null, got "
            f"{resubmitted['rejection_reason']!r}"
        )

    def test_the_fourth_attempt_is_refused_and_leaves_the_filing_rejected(self):
        """After three attempts the fourth resubmit is refused and changes nothing.

        PRD §3.7: "The filing must be `DRAFT`; the acting `X-User-ID` must resolve to a `DisseminationEngagement` whose `undertaking_id` is the undertaking of the filing's issue, failing which the call is refused with `ERR_AGENT_NOT_ENGAGED`; that engagement's `status` must be `ACTIVE`, failing which the call is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`; and the submission must not be the fourth attempt on this filing, since at most three submissions and resubmissions are permitted in total and the fourth is refused with `ERR_SUBMISSION_ATTEMPTS_EXHAUSTED`."
        PRD §3.7: "Resubmission takes a fresh `correction_reason`, requires `status` `REJECTED`, re-resolves an `ACTIVE` engagement for the filing's undertaking, and is subject to the same three-attempt ceiling."
        PRD §3.7: "Rejection is a compensating transition: it returns the cycle from `FILING_IN_PROGRESS` to `READY_TO_FILE`, or the notice from `FILING_IN_PROGRESS` back to `MATERIAL`, and it mints no failure event."
        Design: Corner/state_machines/resubmit_requires_a_correction_reason_and_halts_after_three_attempts
        """
        context = setup_drafted_annual_report()
        filing_id = context["filing"]["id"]
        engagement_id = context["engagement"]["id"]

        submit(filing_id, engagement_id)
        reject(
            filing_id,
            engagement_id,
            rejection_reason="Repository schema validation failed on the operating-data table.",
        )
        resubmit(
            filing_id, engagement_id, correction_reason="Reformatted the operating-data table."
        )
        second_rejection = reject(
            filing_id, engagement_id, rejection_reason="Checksum mismatch."
        )
        assert second_rejection["status"] == "REJECTED", (
            f"The second rejection must land REJECTED, got {second_rejection['status']}"
        )

        third = resubmit(
            filing_id,
            engagement_id,
            correction_reason="Regenerated the package with a corrected checksum.",
        )
        assert third["status"] == "SUBMITTED", (
            f"The third attempt is still within the ceiling, got {third['status']}"
        )
        assert third["submission_attempt_count"] == 3, (
            "The third attempt exhausts the ceiling, so the count must be 3, got "
            f"{third['submission_attempt_count']}"
        )

        third_rejection = reject(
            filing_id, engagement_id, rejection_reason="Repository outage."
        )
        assert third_rejection["status"] == "REJECTED", (
            f"The third rejection must land REJECTED, got {third_rejection['status']}"
        )

        validate_error(
            api_client.resubmit_filing(
                filing_id,
                {"correction_reason": "Fourth attempt after the outage cleared."},
                make_agent_headers(engagement_id),
            ),
            ApiErrorId.ERR_SUBMISSION_ATTEMPTS_EXHAUSTED.value,
        )

        final = read_filing(filing_id)
        assert final["status"] == "REJECTED", (
            f"The refused fourth attempt leaves the filing REJECTED, got {final['status']}"
        )
        assert final["submission_attempt_count"] == 3, (
            "The refused attempt must not raise the counter past 3, got "
            f"{final['submission_attempt_count']}"
        )
        assert final["rejection_reason"] == "Repository outage.", (
            "The refused attempt must not clear the last rejection_reason, got "
            f"{final['rejection_reason']!r}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "READY_TO_FILE", (
            "The last rejection returned the cycle to READY_TO_FILE and the refused "
            f"resubmit did not re-arm it, got {cycle['status']}"
        )


class TestLiveFilingBlocks:
    """A live SUBMITTED filing sits next to a DELINQUENT cycle and locks the agent down."""

    def test_a_failure_to_file_notice_submission_leaves_the_cycle_delinquent(self):
        """Only an ANNUAL_REPORT submission advances its cycle, so the DELINQUENT cycle stays put.

        PRD §3.11: "**Step 2 — delinquency.** Every `AnnualReportCycle` in `status` `DRAFTING` or `READY_TO_FILE` whose `due_date` is strictly before the logical clock's date moves to `DELINQUENT`, with `assembled_by_user_id` and `assembled_at` cleared."
        PRD §3.11: "The response is not an entity row. It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        PRD §3.7: "It then advances the subject: an `ANNUAL_REPORT` filing drives its cycle from `READY_TO_FILE` to `FILING_IN_PROGRESS`, and a `MATERIAL_EVENT_NOTICE` filing drives its notice from `MATERIAL` to `FILING_IN_PROGRESS`."
        Design: Corner/state_machines/withdrawal_and_agent_termination_are_blocked_while_a_filing_is_live
        """
        context = setup_delinquent_cycle_with_live_failure_filing()

        assert context["cycle"]["due_date"] == "2026-01-26", (
            "A period ending 2025-06-30 plus the default 210-day window rolls forward to "
            f"2026-01-26, got {context['cycle']['due_date']}"
        )
        sweep = context["sweep"]
        assert sweep["delinquent_cycle_count"] == 1, (
            f"The sweep must report one delinquent cycle, got {sweep['delinquent_cycle_count']}"
        )
        assert sweep["failure_event_created_count"] == 1, (
            "The delinquency step mints one FailureToFileEvent, got "
            f"{sweep['failure_event_created_count']}"
        )
        assert sweep["matured_issue_count"] == 0, (
            f"No issue has matured, got {sweep['matured_issue_count']}"
        )
        assert context["cycle"]["status"] == "DELINQUENT", (
            f"The overdue cycle must be swept to DELINQUENT, got {context['cycle']['status']}"
        )
        assert context["engagement"]["status"] == "ACTIVE", (
            "An engagement created at the clock's own date has no lapse, so it is ACTIVE, got "
            f"{context['engagement']['status']}"
        )
        assert context["filing"]["status"] == "SUBMITTED", (
            f"The failure-to-file notice must reach SUBMITTED, got {context['filing']['status']}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "DELINQUENT", (
            "A FAILURE_TO_FILE_NOTICE submission moves no subject, so the cycle stays "
            f"DELINQUENT, got {cycle['status']}"
        )

    def test_termination_is_blocked_while_the_agents_filing_is_live_and_clears_on_rejection(self):
        """Terminating the submitting engagement is refused until the repository rejects.

        PRD §3.10: "It is refused with `ERR_ENGAGEMENT_HAS_LIVE_FILING` while any `Filing` whose `submitting_engagement_id` is this engagement still sits in `SUBMITTED`, since only the submitting agent may carry the repository's response back and terminating first would strand the filing."
        PRD §3.10: "A successful termination sets `termination_reason` to `ISSUER_TERMINATED` and freezes `invoice_total_cents`: the invoice calculation is never re-run for a `TERMINATED` engagement, whatever later happens to filings or posture."
        PRD §3.7: "Recording a repository rejection requires a `rejection_reason` and moves a `SUBMITTED` filing to `REJECTED`; only the engagement in `submitting_engagement_id` may do it, and any other agent is refused with `ERR_AGENT_NOT_ENGAGED`."
        Design: Corner/state_machines/withdrawal_and_agent_termination_are_blocked_while_a_filing_is_live
        """
        context = setup_delinquent_cycle_with_live_failure_filing()
        engagement_id = context["engagement"]["id"]
        filing_id = context["filing"]["id"]

        validate_error(
            api_client.terminate_engagement(engagement_id, FD),
            ApiErrorId.ERR_ENGAGEMENT_HAS_LIVE_FILING.value,
        )
        still_active = read_engagement(engagement_id)
        assert still_active["status"] == "ACTIVE", (
            f"The refused termination must leave the engagement ACTIVE, got {still_active['status']}"
        )

        rejected = reject(
            filing_id,
            engagement_id,
            rejection_reason="Wrong form type for a failure-to-file notice.",
        )
        assert rejected["status"] == "REJECTED", (
            f"The rejection must move the filing out of SUBMITTED, got {rejected['status']}"
        )

        terminated = get_success_data(api_client.terminate_engagement(engagement_id, FD))
        assert terminated["status"] == "TERMINATED", (
            "With no live filing left the termination must succeed, got "
            f"{terminated['status']}"
        )
        assert terminated["termination_reason"] == "ISSUER_TERMINATED", (
            "A director's own termination records ISSUER_TERMINATED, got "
            f"{terminated['termination_reason']}"
        )


class TestReopenEditableGate:
    """READY -> DRAFT, gated on the parent cycle's status, and the cyclic edge it drags.

    The item is a perfectly reopenable READY throughout, so the refusal can only come
    from the owning cycle.
    """

    def test_reopen_is_refused_while_the_owning_cycle_is_filing_in_progress(self):
        """A READY item cannot be reopened while its cycle sits in FILING_IN_PROGRESS.

        PRD §3.3: "And the owning cycle's `status` must be `DRAFTING`, `READY_TO_FILE`, or `DELINQUENT`, or the request is refused with `ERR_CYCLE_NOT_EDITABLE`."
        PRD §3.3: "A delinquent cycle deliberately stays editable, because curing and reassembling it is the only path back; a cycle that has moved to `FILING_IN_PROGRESS`, or that has reached any terminal status, accepts none of the four."
        PRD §3.7: "It then advances the subject: an `ANNUAL_REPORT` filing drives its cycle from `READY_TO_FILE` to `FILING_IN_PROGRESS`, and a `MATERIAL_EVENT_NOTICE` filing drives its notice from `MATERIAL` to `FILING_IN_PROGRESS`."
        Design: Corner/state_machines/reopen_is_blocked_while_the_cycle_is_filing_in_progress
        """
        context = setup_drafted_annual_report()
        item = context["items"][0]
        submit(context["filing"]["id"], context["engagement"]["id"])

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "FILING_IN_PROGRESS", (
            "An ANNUAL_REPORT submission drives the cycle to FILING_IN_PROGRESS, got "
            f"{cycle['status']}"
        )
        assert read_content_item(item["id"])["status"] == "READY", (
            "The item itself is a perfectly reopenable READY, so only the parent's status "
            "can be the cause of the refusal"
        )

        validate_error(
            api_client.reopen_content_item(
                item["id"], make_officer_headers(OFFICER_PREPARER_ID)
            ),
            ApiErrorId.ERR_CYCLE_NOT_EDITABLE.value,
        )

    def test_reopen_after_rejection_drags_the_cycle_back_from_ready_to_file_to_drafting(self):
        """Once the repository rejects, reopening the sole item un-assembles the cycle.

        PRD §3.3: "When the underlying data changes, a `DisclosureOfficer` returns a `READY` item to `DRAFT`, which clears `attested_by_user_id` and `attested_at` back to null and drops `readiness_factor` to 0.5."
        PRD §3.3: "Reopening also has a reach beyond the item: if the owning cycle had already advanced to `READY_TO_FILE`, it is dragged back to `DRAFTING` and its `assembled_by_user_id` and `assembled_at` are cleared."
        PRD §3.7: "Rejection is a compensating transition: it returns the cycle from `FILING_IN_PROGRESS` to `READY_TO_FILE`, or the notice from `FILING_IN_PROGRESS` back to `MATERIAL`, and it mints no failure event."
        PRD §3.3: "Each item in the set has a readiness factor — 1.0 when its `status` is `READY` or `WAIVED`, 0.5 when `DRAFT`, and 0.0 when `NOT_STARTED` — and an opinion multiplier that reflects the quality of the audit opinion behind it."
        Design: Corner/state_machines/reopen_is_blocked_while_the_cycle_is_filing_in_progress
        """
        context = setup_drafted_annual_report()
        item = context["items"][0]
        submit(context["filing"]["id"], context["engagement"]["id"])

        rejected = reject(
            context["filing"]["id"],
            context["engagement"]["id"],
            rejection_reason="Missing signature page.",
        )
        assert rejected["status"] == "REJECTED", (
            f"The rejection must land the filing in REJECTED, got {rejected['status']}"
        )
        assert read_cycle(context["cycle"]["id"])["status"] == "READY_TO_FILE", (
            "Rejection returns the cycle from FILING_IN_PROGRESS to READY_TO_FILE"
        )

        reopened = get_success_data(
            api_client.reopen_content_item(
                item["id"], make_officer_headers(OFFICER_PREPARER_ID)
            )
        )
        assert reopened["status"] == "DRAFT", (
            f"Reopening returns a READY item to DRAFT, got {reopened['status']}"
        )
        assert float(reopened["readiness_factor"]) == pytest.approx(0.5, abs=0.01), (
            f"A reopened item drops to readiness_factor 0.5, got {reopened['readiness_factor']}"
        )
        assert reopened["attested_by_user_id"] is None, (
            "Reopening clears attested_by_user_id, got "
            f"{reopened['attested_by_user_id']!r}"
        )
        assert reopened["attested_at"] is None, (
            f"Reopening clears attested_at, got {reopened['attested_at']!r}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "DRAFTING", (
            "The reopen cascade drags a READY_TO_FILE cycle back to DRAFTING, got "
            f"{cycle['status']}"
        )
        assert cycle["assembled_by_user_id"] is None, (
            f"The cascade clears assembled_by_user_id, got {cycle['assembled_by_user_id']!r}"
        )
        assert cycle["assembled_at"] is None, (
            f"The cascade clears assembled_at, got {cycle['assembled_at']!r}"
        )
        assert_score(cycle["completeness_score_pct"], 50.00, "completeness_score_pct")


class TestFilingActionsOutOfOrder:
    """Which rung catches an out-of-order filing action decides the error it earns."""

    def test_confirming_or_resubmitting_a_draft_filing_reports_the_agent_not_engaged(self):
        """With submitting_engagement_id still null the agent-identity rung fires before status.

        PRD §2.1: "On a confirm, a reject, or a resubmit, `X-User-ID` must equal the filing's `submitting_engagement_id` exactly, so that only the agent that handed the document over may carry the repository's answer back."
        PRD §2.10: "6. Agent identity — the three arms described in §2.1 → `ERR_AGENT_NOT_ENGAGED` (403). Applies to `POST /disclosure/filings/{id}/submit`, `/confirm`, `/reject`, `/resubmit`, and to `POST /disclosure/dissemination-engagements/{id}/acknowledge-calendar`. This is distinct from rule 2: the role is permitted, the identity is wrong."
        PRD §3.7: "The draft opens at `status` `DRAFT`, `version` 1, `submission_attempt_count` 0, with `submitted_at`, `submitted_by_user_id`, `submitting_engagement_id`, `repository_receipt_id`, `repository_confirmed_at`, `rejection_reason`, and `superseded_by_filing_id` all null."
        Design: Corner/state_machines/filing_actions_taken_out_of_order_are_refused
        """
        context = setup_drafted_annual_report()
        filing = context["filing"]
        agent = make_agent_headers(context["engagement"]["id"])

        assert filing["status"] == "DRAFT", (
            f"The filing must open in DRAFT, got {filing['status']}"
        )
        assert filing["submitting_engagement_id"] is None, (
            "submitting_engagement_id starts null, which is why no X-User-ID can match it, got "
            f"{filing['submitting_engagement_id']!r}"
        )

        validate_error(
            api_client.confirm_filing(
                filing["id"], {"repository_receipt_id": "EMMA-PREMATURE-1"}, agent
            ),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )
        validate_error(
            api_client.resubmit_filing(
                filing["id"], {"correction_reason": "Nothing to correct yet."}, agent
            ),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )

    def test_a_second_submit_and_a_premature_resubmit_report_an_invalid_state_transition(self):
        """Once the engagement is on the row the status rung becomes the visible answer.

        PRD §2.10: "8. Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint and to `PATCH /disclosure/cycle-content-items/{id}`."
        PRD §3.7: "The filing must be `DRAFT`; the acting `X-User-ID` must resolve to a `DisseminationEngagement` whose `undertaking_id` is the undertaking of the filing's issue, failing which the call is refused with `ERR_AGENT_NOT_ENGAGED`; that engagement's `status` must be `ACTIVE`, failing which the call is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`; and the submission must not be the fourth attempt on this filing, since at most three submissions and resubmissions are permitted in total and the fourth is refused with `ERR_SUBMISSION_ATTEMPTS_EXHAUSTED`."
        PRD §3.7: "Resubmission takes a fresh `correction_reason`, requires `status` `REJECTED`, re-resolves an `ACTIVE` engagement for the filing's undertaking, and is subject to the same three-attempt ceiling."
        Design: Corner/state_machines/filing_actions_taken_out_of_order_are_refused
        """
        context = setup_drafted_annual_report()
        filing_id = context["filing"]["id"]
        engagement_id = context["engagement"]["id"]
        agent = make_agent_headers(engagement_id)

        submitted = submit(filing_id, engagement_id)
        assert submitted["status"] == "SUBMITTED", (
            f"The first submission must land SUBMITTED, got {submitted['status']}"
        )

        validate_error(
            api_client.submit_filing(filing_id, agent),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.resubmit_filing(
                filing_id, {"correction_reason": "Premature correction."}, agent
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

    def test_a_confirmed_filing_refuses_a_rejection_and_keeps_its_receipt(self):
        """Rejecting a CONFIRMED filing is refused and none of the refused calls mutate the row.

        PRD §2.10: "8. Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint and to `PATCH /disclosure/cycle-content-items/{id}`."
        PRD §3.7: "Recording a repository rejection requires a `rejection_reason` and moves a `SUBMITTED` filing to `REJECTED`; only the engagement in `submitting_engagement_id` may do it, and any other agent is refused with `ERR_AGENT_NOT_ENGAGED`."
        PRD §3.7: "Recording the repository's confirmation takes a `repository_receipt_id`, requires `status` `SUBMITTED`, requires the acting `X-User-ID` to be the `submitting_engagement_id`, and requires the receipt id to be unique across every `Filing` row, failing which the call is refused with `ERR_RECEIPT_ID_DUPLICATE`."
        Design: Corner/state_machines/filing_actions_taken_out_of_order_are_refused
        """
        context = setup_drafted_annual_report()
        filing_id = context["filing"]["id"]
        engagement_id = context["engagement"]["id"]
        agent = make_agent_headers(engagement_id)

        submit(filing_id, engagement_id)
        confirmed = confirm(
            filing_id, engagement_id, repository_receipt_id="EMMA-2026-000001"
        )
        assert confirmed["status"] == "CONFIRMED", (
            f"Confirmation must land the filing in CONFIRMED, got {confirmed['status']}"
        )

        validate_error(
            api_client.reject_filing(
                filing_id,
                {"rejection_reason": "Too late to reject a confirmed filing."},
                agent,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

        final = read_filing(filing_id)
        assert final["status"] == "CONFIRMED", (
            f"The refused rejection must leave the filing CONFIRMED, got {final['status']}"
        )
        assert final["submission_attempt_count"] == 1, (
            "Only one attempt was ever consumed, got "
            f"{final['submission_attempt_count']}"
        )
        assert final["repository_receipt_id"] == "EMMA-2026-000001", (
            "The receipt must survive the refused rejection, got "
            f"{final['repository_receipt_id']!r}"
        )


def setup_defeased_terminal_cascade() -> dict:
    """A LEGAL defeasance funded to par, driving four entities into terminal states at once."""
    context = setup_cycle(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
    )
    item = context["items"][0]
    context["item"] = prepare_item(item["id"], source_document_ref="OPDATA-FY2026.pdf")
    context["issue"] = defease_issue(
        context["issue"]["id"],
        defeasance_type="LEGAL",
        escrow_deposit_cents=DESIGN_PAR_CENTS,
        occurrence_date="2026-08-01",
    )
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    context["cycle"] = read_cycle(context["cycle"]["id"])
    context["item"] = read_content_item(item["id"])
    return context


class TestTerminalStateLockdown:
    """One defeasance drives four machines terminal, and each then refuses its own triggers."""

    def test_one_defeasance_drives_issue_undertaking_cycle_and_item_terminal(self):
        """The four-hop cascade closes the cycle, voids its item and zeroes the score.

        PRD §3.1: "Both endings drive `outstanding_par_amount_cents` to 0, advance the issue's `version`, and fire the same four-hop termination cascade."
        PRD §3.1: "Hop 1: the `Undertaking` whose `issue_id` names this issue, if its `status` is `ACTIVE` or `SUSPENDED`, moves to `TERMINATED`, with `termination_cause` set to `DEFEASANCE` for the defeasance path and `MATURITY` for the maturity path."
        PRD §3.1: "Hop 2: every `AnnualReportCycle` of that undertaking whose `status` is `DRAFTING`, `READY_TO_FILE`, or `DELINQUENT` moves to `CLOSED_NOT_REQUIRED`, processed in ascending `created_at` order; where such a cycle was `DELINQUENT`, leaving that status also forces a fresh derivation of `delinquent_cycle_count` and a re-run of the risk score of §3.8."
        PRD §3.1: "Hop 3: every `CycleContentItem` of each closed cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0 — though an item that had been attested keeps its `attested_by_user_id` for the audit trail — and each affected cycle's `completeness_score_pct` falls to 0.00 because its entire input set has left."
        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        context = setup_cycle(
            specs=SIMPLE_REQUIREMENT_SPECS,
            issue={"original_par_amount_cents": DESIGN_PAR_CENTS},
        )
        drafted = prepare_item(
            context["items"][0]["id"], source_document_ref="OPDATA-FY2026.pdf"
        )
        assert drafted["status"] == "DRAFT", (
            f"Recording progress must move the item to DRAFT, got {drafted['status']}"
        )

        defeased = defease_issue(
            context["issue"]["id"],
            defeasance_type="LEGAL",
            escrow_deposit_cents=DESIGN_PAR_CENTS,
            occurrence_date="2026-08-01",
        )
        assert defeased["status"] == "DEFEASED", (
            f"A funded LEGAL defeasance must move the issue to DEFEASED, got {defeased['status']}"
        )

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["status"] == "TERMINATED", (
            f"Hop 1 must terminate the undertaking, got {undertaking['status']}"
        )
        assert undertaking["termination_cause"] == "DEFEASANCE", (
            "The defeasance path sets termination_cause DEFEASANCE, got "
            f"{undertaking['termination_cause']!r}"
        )

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "CLOSED_NOT_REQUIRED", (
            f"Hop 2 must close the DRAFTING cycle, got {cycle['status']}"
        )
        assert_score(cycle["completeness_score_pct"], 0.00, "completeness_score_pct")

        item = read_content_item(context["items"][0]["id"])
        assert item["status"] == "VOID", (
            f"Hop 3 must void the cycle's DRAFT item, got {item['status']}"
        )
        assert float(item["readiness_factor"]) == 0.0, (
            f"A VOID item carries readiness_factor 0.0, got {item['readiness_factor']}"
        )

    def test_every_terminal_row_refuses_its_own_further_triggers(self):
        """Each terminal row answers with its own status rule, not with a lower gate's error.

        PRD §2.10: "8. Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint and to `PATCH /disclosure/cycle-content-items/{id}`. This rule inspects the `status` field only and never a derived field such as `disclosure_adequacy`; publishing a statement that is in `COMPLIANCE_REVIEW` but whose disclosure is inadequate therefore passes this rung and is caught at rule 32. This is the highest-priority business check and wins every conflict with the rules below it."
        PRD §3.1: "A shortfall is refused with `ERR_ESCROW_INSUFFICIENT`, and because this is a fiscal check it sits near the bottom of the ladder — a defeasance attempt on an already-`DEFEASED` issue reports `ERR_INVALID_STATE_TRANSITION` instead."
        PRD §3.2: "A `FinanceDirector` may suspend an `ACTIVE` undertaking — pending a legal opinion, for instance — by supplying a `suspended_reason`, which is stamped on the row; suspension blocks new reporting cycles, all content preparation, assembly, and all new engagements, while filings already in flight continue undisturbed."
        PRD §3.2: "Reinstating a `SUSPENDED` undertaking takes no payload at all, returns it to `ACTIVE`, and clears `suspended_reason` back to null."
        PRD §3.4: "The cycle's own `status` is tested first, so assembling a cycle that is `FILING_IN_PROGRESS`, `WITHDRAWN`, `CLOSED_NOT_REQUIRED`, or already filed yields `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.4: "It is available from `DRAFTING` and from `READY_TO_FILE`; attempting it from any other status yields `ERR_INVALID_STATE_TRANSITION`."
        Design: Corner/state_machines/terminal_states_reject_every_further_trigger
        """
        context = setup_defeased_terminal_cascade()
        issue_id = context["issue"]["id"]
        undertaking_id = context["undertaking"]["id"]
        cycle_id = context["cycle"]["id"]
        item_id = context["item"]["id"]

        validate_error(
            api_client.defease_bond_issue(
                issue_id,
                {
                    "defeasance_type": "ECONOMIC",
                    "escrow_deposit_cents": 1,
                    "occurrence_date": "2026-08-01",
                },
                FD,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.suspend_undertaking(
                undertaking_id,
                {"suspended_reason": "Attempting to suspend a terminated undertaking."},
                FD,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.reinstate_undertaking(undertaking_id, FD),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.assemble_cycle(cycle_id, ASSEMBLER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.withdraw_cycle(
                cycle_id, {"withdrawal_reason": "Attempting to withdraw a closed cycle."}, OFFICER
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.update_content_item(
                item_id, {"source_document_ref": "OPDATA-FY2026-v2.pdf"}, OFFICER
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.attest_content_item(item_id, OFFICER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )


def setup_assembled_split_weight_cycle() -> dict:
    """A READY_TO_FILE cycle whose 6000-bp item is READY and whose 4000-bp item is WAIVED."""
    context = setup_split_weight_cycle()
    item_a = item_of_kind(context["items"], context["requirements"], "OPERATING_DATA_TABLE")
    item_b = item_of_kind(context["items"], context["requirements"], "BUDGET_SUMMARY")
    prepare_item(item_a["id"], source_document_ref="OPDATA-FY2026.pdf")
    context["item_a"] = attest_item(item_a["id"])
    context["item_b"] = waive_item(
        item_b["id"], waiver_reason="Budget adopted after the reporting deadline."
    )
    context["cycle"] = assemble(context["cycle"]["id"])
    return context


class TestNoIdempotencyOnContentActions:
    """None of attest, waive or assemble is idempotent; the second call is refused."""

    def test_a_second_attest_waive_and_assemble_are_each_refused(self):
        """Each duplicate call finds its target row already past the status the action demands.

        PRD §3.3: "Attesting an item is the preparer's assertion that it is complete and accurate, and it moves a `DRAFT` item to `READY`."
        PRD §3.3: "An item in `NOT_STARTED` or `DRAFT` moves to `WAIVED` on supply of a `waiver_reason`, but only when its underlying `ContentRequirement` has `waivable` true; otherwise the attempt is refused with `ERR_REQUIREMENT_NOT_WAIVABLE`."
        PRD §3.4: "It is available from two starting statuses: `DRAFTING`, the ordinary path, and `DELINQUENT`, which is how a cycle that already blew its deadline becomes fileable again."
        PRD §2.10: "8. Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint and to `PATCH /disclosure/cycle-content-items/{id}`."
        Design: Corner/state_machines/repeating_attest_assemble_and_waive_fails_on_the_second_attempt
        """
        context = setup_assembled_split_weight_cycle()

        assert context["item_a"]["status"] == "READY", (
            f"The attested item must be READY, got {context['item_a']['status']}"
        )
        assert context["item_b"]["status"] == "WAIVED", (
            f"The waived item must be WAIVED, got {context['item_b']['status']}"
        )
        assert context["cycle"]["status"] == "READY_TO_FILE", (
            f"Assembly must land the cycle in READY_TO_FILE, got {context['cycle']['status']}"
        )

        validate_error(
            api_client.attest_content_item(context["item_a"]["id"], OFFICER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.waive_content_item(
                context["item_b"]["id"],
                {"waiver_reason": "A different reason entirely."},
                SECOND_REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.assemble_cycle(context["cycle"]["id"], ASSEMBLER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

    def test_the_refused_duplicates_re_stamp_nothing_and_bump_no_version(self):
        """A refused action leaves the first stamp, the first reason and the version alone.

        PRD §3.3: "On success the item records `attested_by_user_id` from `X-User-ID` and `attested_at` from the logical clock, and `readiness_factor` becomes 1.0."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including cascaded mutations."
        PRD §2.10: "8. Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint and to `PATCH /disclosure/cycle-content-items/{id}`."
        Design: Corner/state_machines/repeating_attest_assemble_and_waive_fails_on_the_second_attempt
        """
        context = setup_assembled_split_weight_cycle()
        item_a_before = context["item_a"]
        item_b_before = context["item_b"]
        cycle_before = context["cycle"]

        validate_error(
            api_client.attest_content_item(item_a_before["id"], OFFICER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.waive_content_item(
                item_b_before["id"],
                {"waiver_reason": "A different reason entirely."},
                SECOND_REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.assemble_cycle(cycle_before["id"], ASSEMBLER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

        item_a_after = read_content_item(item_a_before["id"])
        assert item_a_after["attested_at"] == item_a_before["attested_at"], (
            "The refused attest must not re-stamp attested_at: expected "
            f"{item_a_before['attested_at']!r}, got {item_a_after['attested_at']!r}"
        )
        assert item_a_after["version"] == item_a_before["version"], (
            f"The refused attest must not bump version: expected {item_a_before['version']}, "
            f"got {item_a_after['version']}"
        )

        item_b_after = read_content_item(item_b_before["id"])
        assert item_b_after["waiver_reason"] == item_b_before["waiver_reason"], (
            "The second reviewer's replacement reason must not be written: expected "
            f"{item_b_before['waiver_reason']!r}, got {item_b_after['waiver_reason']!r}"
        )

        cycle_after = read_cycle(cycle_before["id"])
        assert cycle_after["assembled_at"] == cycle_before["assembled_at"], (
            "The refused assemble must not re-stamp assembled_at: expected "
            f"{cycle_before['assembled_at']!r}, got {cycle_after['assembled_at']!r}"
        )
        assert cycle_after["version"] == cycle_before["version"], (
            f"The refused assemble must not bump version: expected {cycle_before['version']}, "
            f"got {cycle_after['version']}"
        )

    def test_the_requirement_filter_matches_no_row_when_handed_an_item_id(self):
        """content_requirement_id walks back along that foreign key, so an item id matches nothing.

        PRD §2.12: "The list endpoints are their only discovery channel, and each list endpoint therefore accepts the filters needed to walk backwards along a foreign key."
        PRD §2.12: "Content items are filterable by `cycle_id`, `content_requirement_id`, and `status`."
        Design: Corner/state_machines/repeating_attest_assemble_and_waive_fails_on_the_second_attempt
        """
        context = setup_assembled_split_weight_cycle()
        item_a = context["item_a"]

        by_item_id = total_count_of(
            api_client.list_content_items(
                FD,
                params={
                    "cycle_id": context["cycle"]["id"],
                    "content_requirement_id": item_a["id"],
                },
            )
        )
        assert by_item_id == 0, (
            "Passing an item id where a requirement id belongs must match no row, got "
            f"{by_item_id}"
        )

        by_requirement_id = total_count_of(
            api_client.list_content_items(
                FD,
                params={
                    "cycle_id": context["cycle"]["id"],
                    "content_requirement_id": item_a["content_requirement_id"],
                },
            )
        )
        assert by_requirement_id == 1, (
            "The real requirement id must match exactly its own item, got "
            f"{by_requirement_id}"
        )


# The lapse instance measures monitoring from the effective date, so the
# engagement is dated a month before the clock's startup value.
LAPSE_ENGAGEMENT = {
    "agent_name": "Meridian Dissemination LLC",
    "effective_date": "2026-07-01",
    "expiration_date": "2027-12-31",
    "retainer_cents": 400000,
}


def setup_engagement_with_month_old_effective_date() -> dict:
    """An ACTIVE engagement effective 2026-07-01, with last_calendar_ack_date omitted."""
    context = setup_issue_with_undertaking(
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS}
    )
    context["engagement"] = create_engagement(
        context["undertaking"]["id"], **dict(LAPSE_ENGAGEMENT)
    )
    return context


def suspend_engagement_by_sweep(engagement_id: str) -> dict:
    """Drive the lapse to 46 days at clock 2026-08-16 and let the sweep suspend the agent."""
    set_clock("2026-08-16T00:00:00Z")
    run_sweep()
    return read_engagement(engagement_id)


class TestEngagementSuspensionLoop:
    """ACTIVE to SUSPENDED and back, with the same ack trigger serving both edges."""

    def test_a_new_engagement_opens_active_with_its_lapse_already_derived(self):
        """With no ack recorded the lapse runs from the effective date to the clock's date.

        PRD §3.10: "The engagement opens at `status` `ACTIVE`, `version` 1, `billable_filing_count` 0, with `superseded_by_engagement_id` and `termination_reason` null."
        PRD §3.10: "`monitoring_lapse_days` is the whole calendar days from the later-of-nothing baseline — `last_calendar_ack_date` when it is set, and `effective_date` when it is null — to the logical clock's date, floored at 0."
        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`; until the clock is explicitly set, that instant is what all rules read, and the service must never fall back on real wall-clock time."
        Design: Corner/state_machines/engagement_returns_from_suspended_to_active_and_self_loops_on_routine_acks
        """
        context = setup_engagement_with_month_old_effective_date()
        engagement = context["engagement"]

        assert engagement["status"] == "ACTIVE", (
            f"A new engagement opens ACTIVE, got {engagement['status']}"
        )
        assert engagement["monitoring_lapse_days"] == 31, (
            "2026-07-01 to the startup clock date 2026-08-01 is 31 whole calendar days, got "
            f"{engagement['monitoring_lapse_days']}"
        )
        assert engagement["version"] == 1, (
            f"A new engagement opens at version 1, got {engagement['version']}"
        )
        assert engagement["last_calendar_ack_date"] is None, (
            "last_calendar_ack_date was omitted at creation, got "
            f"{engagement['last_calendar_ack_date']!r}"
        )

    def test_a_lapse_of_exactly_forty_five_days_survives_the_sweep_and_forty_six_does_not(self):
        """The suspension test is strictly greater than 45, so the boundary day is compliant.

        PRD §3.10: "Suspension is a sweep-only transition and fires when `monitoring_lapse_days` is **strictly greater than** 45, so a lapse of exactly 45 days is still compliant while 46 days suspends."
        PRD §3.11: "**Step 4 — monitoring lapse.** Every `DisseminationEngagement` in `status` `ACTIVE` whose refreshed `monitoring_lapse_days` exceeds 45 moves to `SUSPENDED`."
        PRD §3.11: "The response is not an entity row. It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        Design: Corner/state_machines/engagement_returns_from_suspended_to_active_and_self_loops_on_routine_acks
        """
        context = setup_engagement_with_month_old_effective_date()
        engagement_id = context["engagement"]["id"]

        clock_at_45 = set_clock("2026-08-15T00:00:00Z")
        assert clock_at_45["current_utc"][:19] == "2026-08-15T00:00:00", (
            f"The clock must echo the instant it was set to, got {clock_at_45['current_utc']!r}"
        )
        sweep_at_45 = run_sweep()
        assert sweep_at_45["suspended_engagement_count"] == 0, (
            "A lapse of exactly 45 days is not strictly greater than 45, got "
            f"suspended_engagement_count {sweep_at_45['suspended_engagement_count']}"
        )
        at_45 = read_engagement(engagement_id)
        assert at_45["status"] == "ACTIVE", (
            f"The engagement must still be ACTIVE at a 45-day lapse, got {at_45['status']}"
        )

        clock_at_46 = set_clock("2026-08-16T00:00:00Z")
        assert clock_at_46["current_utc"][:19] == "2026-08-16T00:00:00", (
            f"The clock must echo the instant it was set to, got {clock_at_46['current_utc']!r}"
        )
        sweep_at_46 = run_sweep()
        assert sweep_at_46["suspended_engagement_count"] == 1, (
            "A 46-day lapse must suspend exactly one engagement, got "
            f"{sweep_at_46['suspended_engagement_count']}"
        )
        assert sweep_at_46["swept_at"] == "2026-08-16T00:00:00.000Z", (
            "swept_at is the logical-clock instant of the sweep, got "
            f"{sweep_at_46['swept_at']!r}"
        )

        at_46 = read_engagement(engagement_id)
        assert at_46["status"] == "SUSPENDED", (
            f"A 46-day lapse must move the engagement to SUSPENDED, got {at_46['status']}"
        )
        assert at_46["monitoring_lapse_days"] == 46, (
            "2026-07-01 to 2026-08-16 is 46 whole calendar days, got "
            f"{at_46['monitoring_lapse_days']}"
        )

    def test_an_ack_date_outside_the_window_is_refused_at_either_edge(self):
        """The ack window is bounded below by the effective date and above by the clock's date.

        PRD §3.10: "Acknowledgement is the agent's own act: it takes a `last_calendar_ack_date`, requires the acting `X-User-ID` to equal the engagement's own id (else `ERR_AGENT_NOT_ENGAGED`), and requires that date to be at or after `effective_date` and at or before the logical clock's date (else `ERR_ACK_DATE_OUT_OF_RANGE`)."
        Design: Corner/state_machines/engagement_returns_from_suspended_to_active_and_self_loops_on_routine_acks
        """
        context = setup_engagement_with_month_old_effective_date()
        engagement_id = context["engagement"]["id"]
        suspend_engagement_by_sweep(engagement_id)
        agent = make_agent_headers(engagement_id)

        validate_error(
            api_client.acknowledge_calendar(
                engagement_id, {"last_calendar_ack_date": "2026-06-01"}, agent
            ),
            ApiErrorId.ERR_ACK_DATE_OUT_OF_RANGE.value,
        )
        validate_error(
            api_client.acknowledge_calendar(
                engagement_id, {"last_calendar_ack_date": "2026-09-01"}, agent
            ),
            ApiErrorId.ERR_ACK_DATE_OUT_OF_RANGE.value,
        )

    def test_the_ack_cures_the_suspension_and_then_self_loops_on_an_active_engagement(self):
        """The same trigger closes the SUSPENDED to ACTIVE edge and the ACTIVE self-loop.

        PRD §3.10: "From `ACTIVE` it is a self-loop that resets the lapse clock; from `SUSPENDED` it is the cure that restores the engagement to `ACTIVE` and re-enables submissions."
        PRD §3.10: "Either way it stamps the new `last_calendar_ack_date` and refreshes `monitoring_lapse_days`."
        PRD §3.10: "The `ACTIVE`-to-`SUSPENDED`-to-`ACTIVE` cycle can repeat without limit."
        PRD §3.11: "The sweep is idempotent for a fixed clock: a second sweep at the same clock instant finds no candidates and returns all five counts as 0."
        Design: Corner/state_machines/engagement_returns_from_suspended_to_active_and_self_loops_on_routine_acks
        """
        context = setup_engagement_with_month_old_effective_date()
        engagement_id = context["engagement"]["id"]
        suspended = suspend_engagement_by_sweep(engagement_id)
        assert suspended["status"] == "SUSPENDED", (
            f"The sweep must have suspended the engagement first, got {suspended['status']}"
        )

        cured = acknowledge_calendar(engagement_id, "2026-08-16")
        assert cured["status"] == "ACTIVE", (
            f"The ack must cure the suspension back to ACTIVE, got {cured['status']}"
        )
        assert cured["monitoring_lapse_days"] == 0, (
            "Acknowledging on the clock's own date resets the lapse to 0, got "
            f"{cured['monitoring_lapse_days']}"
        )
        assert cured["last_calendar_ack_date"] == "2026-08-16", (
            f"The new ack date must be stamped, got {cured['last_calendar_ack_date']!r}"
        )

        looped = acknowledge_calendar(engagement_id, "2026-08-16")
        assert looped["status"] == "ACTIVE", (
            f"The ACTIVE self-loop stays ACTIVE rather than erroring, got {looped['status']}"
        )
        assert looped["monitoring_lapse_days"] == 0, (
            f"The self-loop keeps the lapse at 0, got {looped['monitoring_lapse_days']}"
        )

        rerun = run_sweep()
        assert rerun["suspended_engagement_count"] == 0, (
            "The cured engagement must not be re-suspended by the same-clock sweep, got "
            f"{rerun['suspended_engagement_count']}"
        )
        final = read_engagement(engagement_id)
        assert final["status"] == "ACTIVE", (
            f"The cure must hold against a re-run of the sweep, got {final['status']}"
        )


# Placement A is exactly 500 bp of the design par; placement B is 300 bp, and
# their review windows are disjoint so the aggregate capacity rule never engages.
PLACEMENT_AT_THE_BOUNDARY = {
    "lender_name": "Harbor Trust Bank",
    "principal_amount_cents": 5000000,
    "execution_date": "2026-07-28",
    "review_window_start_date": "2026-08-01",
    "review_window_end_date": "2026-08-10",
    "disclosure_practice": "VOLUNTARY",
}

PLACEMENT_BELOW_THE_BOUNDARY = {
    "lender_name": "Cornerstone Savings",
    "principal_amount_cents": 3000000,
    "execution_date": "2026-07-28",
    "review_window_start_date": "2026-08-15",
    "review_window_end_date": "2026-08-25",
    "disclosure_practice": "VOLUNTARY",
}


def setup_two_placements_across_the_boundary() -> dict:
    """An issue with a 500-bp placement and a 300-bp placement on disjoint review windows."""
    context = setup_issue_with_undertaking(
        issue={"original_par_amount_cents": DESIGN_PAR_CENTS}
    )
    context["placement_a"] = create_placement(
        context["issue"]["id"], **dict(PLACEMENT_AT_THE_BOUNDARY)
    )
    context["placement_b"] = create_placement(
        context["issue"]["id"], **dict(PLACEMENT_BELOW_THE_BOUNDARY)
    )
    return context


def notice_count_for_placement(issue_id: str, placement_id: str) -> int:
    """How many listed-event notices point back at one placement (PRD §2.12)."""
    return total_count_of(
        api_client.list_material_event_notices(
            FD, params={"issue_id": issue_id, "financial_obligation_ref": placement_id}
        )
    )


class TestPlacementClassificationBranches:
    """One classify call, two disjoint cascades chosen at the 500-basis-point boundary."""

    def test_the_five_hundred_basis_point_boundary_mints_a_back_dated_notice(self):
        """A ratio of exactly 500 bp requires disclosure and mints its notice on the execution date.

        PRD §3.6: "The placement opens at `status` `RECEIVED`, `version` 1, with `linked_notice_id` and `waiver_reason` null."
        PRD §3.6: "`materiality_ratio_bp` is derived once, at creation, as `principal_amount_cents` multiplied by 10000, divided by the issue's `outstanding_par_amount_cents`, rounded half-up to a whole basis point."
        PRD §3.6: "The placement becomes `DISCLOSURE_REQUIRED` when `materiality_ratio_bp` is **greater than or equal to** 500, or when `disclosure_practice` is `MANDATORY_MATERIAL_EVENT` regardless of the ratio."
        PRD §3.6: "That branch mints a `MaterialEventNotice` with `event_type` `FINANCIAL_OBLIGATION_INCURRENCE`, `issue_id` copied from the placement, `occurrence_date` set to the placement's `execution_date`, `financial_obligation_ref` pointing back at the placement, `per_se_material` false, and `status` `DETERMINATION_PENDING`, with its own `filing_deadline_date` ten business days after that occurrence date; the new notice's id is stored in `linked_notice_id`, and the issue's `open_material_event_count` and the undertaking's `open_obligation_count` are both re-derived."
        PRD §3.6: "A principal of 5,000,000 cents against outstanding par of 100,000,000 cents is exactly 500 basis points and classifies as `DISCLOSURE_REQUIRED`; a principal of 4,990,000 cents against the same par rounds to 499 basis points and classifies as `DISCLOSURE_WAIVED`."
        Design: Corner/state_machines/classify_mints_a_notice_only_on_the_disclosure_required_branch
        """
        context = setup_two_placements_across_the_boundary()
        placement_a = context["placement_a"]

        assert placement_a["materiality_ratio_bp"] == 500, (
            "5,000,000 cents of 100,000,000 cents of par is exactly 500 bp, got "
            f"{placement_a['materiality_ratio_bp']}"
        )
        assert placement_a["status"] == "RECEIVED", (
            f"A new placement opens RECEIVED, got {placement_a['status']}"
        )
        assert placement_a["linked_notice_id"] is None, (
            f"linked_notice_id starts null, got {placement_a['linked_notice_id']!r}"
        )
        assert context["placement_b"]["materiality_ratio_bp"] == 300, (
            "3,000,000 cents of 100,000,000 cents of par is 300 bp, got "
            f"{context['placement_b']['materiality_ratio_bp']}"
        )

        classified = classify_placement(placement_a["id"])
        assert classified["status"] == "DISCLOSURE_REQUIRED", (
            "500 bp meets the >= 500 threshold exactly, so the placement requires disclosure, got "
            f"{classified['status']}"
        )
        assert classified["linked_notice_id"] is not None, (
            "The minted notice's id must be stored in linked_notice_id, got null"
        )

        assert notice_count_for_placement(context["issue"]["id"], placement_a["id"]) == 1, (
            "Exactly one notice must point back at the classified placement"
        )
        notices = list_notices(
            context["issue"]["id"], financial_obligation_ref=placement_a["id"]
        )
        notice = notices[0]
        assert notice["id"] == classified["linked_notice_id"], (
            "The notice found through the placement filter must be the one linked on the row: "
            f"expected {classified['linked_notice_id']!r}, got {notice['id']!r}"
        )
        assert notice["event_type"] == "FINANCIAL_OBLIGATION_INCURRENCE", (
            f"The minted notice discloses an incurred obligation, got {notice['event_type']}"
        )
        assert notice["status"] == "DETERMINATION_PENDING", (
            f"The minted notice opens DETERMINATION_PENDING, got {notice['status']}"
        )
        assert notice["per_se_material"] is False, (
            "FINANCIAL_OBLIGATION_INCURRENCE is not one of the four per-se events, got "
            f"{notice['per_se_material']!r}"
        )
        assert notice["occurrence_date"] == "2026-07-28", (
            "The occurrence date is the placement's execution_date, not the classification date, "
            f"got {notice['occurrence_date']!r}"
        )
        assert notice["filing_deadline_date"] == "2026-08-11", (
            "The tenth business day strictly after 2026-07-28 is 2026-08-11, got "
            f"{notice['filing_deadline_date']!r}"
        )

    def test_the_waived_branch_demands_a_reason_and_mints_nothing(self):
        """Below the boundary the placement is waived, needs a reason, and moves no counter.

        PRD §3.6: "Otherwise — ratio strictly below 500 basis points **and** `disclosure_practice` not `MANDATORY_MATERIAL_EVENT` — the placement becomes `DISCLOSURE_WAIVED`, which requires a `waiver_reason` in the body and is refused with `ERR_WAIVER_REASON_REQUIRED` without one."
        PRD §3.6: "The waived branch creates no notice, leaves `linked_notice_id` null, and moves no counter at all."
        PRD §2.10: "40. Branch-specific required fields — a non-empty `waiver_reason` on the waived branch of placement classification → `ERR_WAIVER_REASON_REQUIRED` (422) on `POST /disclosure/direct-placements/{id}/classify`; and a refusal to declare a per-se listed event immaterial → `ERR_PER_SE_EVENT_IS_MATERIAL` (422) on `POST /disclosure/material-event-notices/{id}/determine`."
        Design: Corner/state_machines/classify_mints_a_notice_only_on_the_disclosure_required_branch
        """
        context = setup_two_placements_across_the_boundary()
        issue_id = context["issue"]["id"]
        placement_a = context["placement_a"]
        placement_b = context["placement_b"]

        classify_placement(placement_a["id"])

        validate_error(
            api_client.classify_direct_placement(placement_b["id"], REVIEWER),
            ApiErrorId.ERR_WAIVER_REASON_REQUIRED.value,
        )

        waived = classify_placement(
            placement_b["id"],
            waiver_reason="300 bp of par; no covenant differing from the public bonds.",
        )
        assert waived["status"] == "DISCLOSURE_WAIVED", (
            f"300 bp falls below the 500-bp threshold, got {waived['status']}"
        )
        assert waived["linked_notice_id"] is None, (
            "The waived branch mints no notice, so linked_notice_id stays null, got "
            f"{waived['linked_notice_id']!r}"
        )
        assert waived["waiver_reason"] == (
            "300 bp of par; no covenant differing from the public bonds."
        ), f"The supplied waiver_reason must be recorded, got {waived['waiver_reason']!r}"

        assert notice_count_for_placement(issue_id, placement_b["id"]) == 0, (
            "No notice may point at the waived placement"
        )

        issue = read_bond_issue(issue_id)
        assert issue["open_material_event_count"] == 1, (
            "Only the required branch consumed an obligation slot, got "
            f"open_material_event_count {issue['open_material_event_count']}"
        )
        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["open_obligation_count"] == 1, (
            "Only the required branch consumed an obligation slot, got "
            f"open_obligation_count {undertaking['open_obligation_count']}"
        )


class TestBillableLedgerSync:
    """Only a CONFIRMED filing enters the agent's ledger; submit and reject move nothing."""

    def test_the_ledger_moves_only_when_the_repository_confirms(self):
        """Across submit, reject and resubmit the ledger holds; the confirmation alone moves it.

        PRD §3.10: "The first input is the conserved filing count: let F be the number of `Filing` rows whose `submitting_engagement_id` is this engagement and whose `status` is exactly `CONFIRMED`."
        PRD §3.10: "The second input is a **marginal**, never averaged, tier allocation over F. The first four confirmed filings are billed at 450 dollars each; filings five through nine are billed at 325 dollars each; filings ten and beyond are billed at 250 dollars each."
        PRD §3.10: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
        PRD §3.7: "It does not raise `billable_filing_count` — a rejected submission is not billable."
        PRD §3.7: "It sets `repository_confirmed_at` from the logical clock and stamps the receipt."
        Design: Corner/state_machines/confirmation_syncs_the_engagement_billable_ledger
        """
        context = setup_drafted_annual_report()
        engagement_id = context["engagement"]["id"]
        filing_id = context["filing"]["id"]

        at_creation = context["engagement"]
        assert at_creation["billable_filing_count"] == 0, (
            "No filing is confirmed yet, got billable_filing_count "
            f"{at_creation['billable_filing_count']}"
        )
        assert at_creation["invoice_total_cents"] == 400000, (
            "The 400000 retainer alone, with the 300000 floor not binding, got "
            f"{at_creation['invoice_total_cents']}"
        )

        submit(filing_id, engagement_id)
        after_submit = read_engagement(engagement_id)
        assert after_submit["billable_filing_count"] == 0, (
            "A SUBMITTED filing is not billable, got "
            f"{after_submit['billable_filing_count']}"
        )
        assert after_submit["invoice_total_cents"] == 400000, (
            f"The invoice must still be the retainer, got {after_submit['invoice_total_cents']}"
        )

        reject(filing_id, engagement_id, rejection_reason="Cover page missing.")
        after_reject = read_engagement(engagement_id)
        assert after_reject["billable_filing_count"] == 0, (
            "A rejection never enters the ledger, got "
            f"{after_reject['billable_filing_count']}"
        )
        assert after_reject["invoice_total_cents"] == 400000, (
            f"The invoice must still be the retainer, got {after_reject['invoice_total_cents']}"
        )

        resubmit(filing_id, engagement_id, correction_reason="Cover page added.")
        confirmed = confirm(
            filing_id, engagement_id, repository_receipt_id="EMMA-2026-000042"
        )
        assert confirmed["status"] == "CONFIRMED", (
            f"The confirmation must land the filing in CONFIRMED, got {confirmed['status']}"
        )
        assert_startup_clock_stamp(
            confirmed["repository_confirmed_at"], "repository_confirmed_at"
        )

        after_confirm = read_engagement(engagement_id)
        assert after_confirm["billable_filing_count"] == 1, (
            "Exactly one filing now sits in CONFIRMED, got "
            f"{after_confirm['billable_filing_count']}"
        )
        assert after_confirm["invoice_total_cents"] == 445000, (
            "400000 retainer plus one first-tier filing at 45000, got "
            f"{after_confirm['invoice_total_cents']}"
        )

    def test_a_timely_confirmation_files_the_cycle_and_mints_no_failure_event(self):
        """Hop 1 discharges the cycle as FILED_TIMELY on the submission basis with no days late.

        PRD §3.7: "Hop 1 discharges the subject. For an `ANNUAL_REPORT` filing the timeliness assessment of §3.8 runs and moves the cycle from `FILING_IN_PROGRESS` to `FILED_TIMELY` or `FILED_LATE`, writing `filed_at`, `days_late`, `timeliness_basis_applied`, and `filed_filing_id`."
        PRD §3.8: "Under `SUBMISSION_BASIS`, the default, the basis instant is the filing's `submitted_at` — the moment the agent handed the document to the repository — so a document submitted on the due date is timely even if the repository confirms it days later."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        PRD §3.8: "A cycle reaching `FILED_TIMELY` mints nothing, but every event on that cycle still `OPEN` moves to `REMEDIATION_PENDING`."
        Design: Corner/state_machines/confirmation_syncs_the_engagement_billable_ledger
        """
        context = setup_drafted_annual_report()
        engagement_id = context["engagement"]["id"]
        filing_id = context["filing"]["id"]

        assert context["cycle"]["due_date"] == FY2026_DUE_DATE, (
            "A FY2026 period ending 2026-06-30 with the default 210-day window is due "
            f"{FY2026_DUE_DATE}, got {context['cycle']['due_date']!r}"
        )

        submit(filing_id, engagement_id)
        confirm(filing_id, engagement_id, repository_receipt_id="EMMA-2026-000042")

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "FILED_TIMELY", (
            "A filing submitted a year before the due date is timely, got "
            f"{cycle['status']}"
        )
        assert cycle["days_late"] == 0, (
            f"A timely cycle carries days_late 0, got {cycle['days_late']}"
        )
        assert cycle["timeliness_basis_applied"] == "SUBMISSION_BASIS", (
            "SUBMISSION_BASIS is the undertaking's default and must be recorded on the cycle, got "
            f"{cycle['timeliness_basis_applied']!r}"
        )
        assert cycle["filed_filing_id"] == filing_id, (
            f"filed_filing_id must name the confirmed filing, got {cycle['filed_filing_id']!r}"
        )

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["open_obligation_count"] == 0, (
            "The filed cycle is no longer an open obligation, got "
            f"{undertaking['open_obligation_count']}"
        )
        assert undertaking["late_filing_count"] == 0, (
            f"A timely filing raises no late count, got {undertaking['late_filing_count']}"
        )
        assert undertaking["compliance_posture"] == "COMPLIANT", (
            "With no failure event the posture stays COMPLIANT, got "
            f"{undertaking['compliance_posture']}"
        )
