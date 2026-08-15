"""Plan change requests: proposal, modeling, communication, acknowledgment,
activation cascade, repin, and OCC on create."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_plan,
    create_comp_plan_payload,
    create_fmv_approved_plan,
    create_pcr,
    create_pcr_payload,
    get_success_data,
    set_clock,
    setup_pcr_activated,
    setup_pcr_communicated,
    setup_successor_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMITTEE = TEST_USERS["committee_headers"]


class TestSuccessionCascade:
    def test_activation_moves_both_plans(self, api):
        """PRD §3.9: "On activation the request becomes `EFFECTIVE`; the successor plan moves `FMV_APPROVED → ACTIVE`; the changed plan moves `ACTIVE → SUPERSEDED`; every `EFFECTIVE` agreement on the superseded plan flips to `AMENDMENT_REQUIRED` (awaiting the re-pin of §3.3); and each flipped agreement voids its own `DRAFT` statements."

        Design: Difficulty/transitive_cascade/plan_change_activation_cascade
        """
        scenario = setup_pcr_activated(with_capture_and_statement=True,
                                       npi="1000000040")
        pcr = scenario["pcr"]
        assert pcr["status"] == "EFFECTIVE"
        assert pcr["modeled_delta_cents"] == 0, (
            "no FINALIZED statements exist, so the projection base is zero"
        )
        # The model ran while no finalized payment history existed.
        assert scenario["modeled_delta_cents"] == 0
        changed = get_success_data(api.get_comp_plan(scenario["plan"]["id"], ANALYST))
        assert changed["status"] == "SUPERSEDED", "hop 1b: the changed plan is superseded"
        successor = get_success_data(api.get_comp_plan(scenario["successor"]["id"], ANALYST))
        assert successor["status"] == "ACTIVE", "hop 1a: the successor activates"

    def test_activation_cascades_to_agreement_and_draft_statement(self, api):
        """PRD §3.9: "every `EFFECTIVE` agreement on the superseded plan flips to `AMENDMENT_REQUIRED` (awaiting the re-pin of §3.3); and each flipped agreement voids its own `DRAFT` statements."
        PRD §3.7: "System cascades void `DRAFT` statements without any cash impact, since a `DRAFT` statement never paid"

        Design: Difficulty/transitive_cascade/plan_change_activation_cascade
        """
        scenario = setup_pcr_activated(with_capture_and_statement=True,
                                       npi="1000000040")
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert agreement["status"] == "AMENDMENT_REQUIRED", "hop 2: agreement flips"
        assert agreement["plan_id"] == scenario["plan"]["id"], (
            "the agreement still points at the superseded plan until repin is called"
        )
        statement = get_success_data(api.get_statement(scenario["statement"]["id"], ANALYST))
        assert statement["status"] == "VOIDED", "hop 3: the DRAFT statement is voided"

    def test_repin_moves_agreement_to_successor(self, api):
        """PRD §3.3: "re-pinning requires an `ACTIVE` plan whose `supersedes_plan_id` equals the agreement's current `plan_id`, sets the agreement's `plan_id` to that successor and its `pinned_plan_version` to the successor's current `version`, and returns the agreement to `EFFECTIVE`."
        PRD §3.3: "At creation the agreement snapshots the plan's current `version` into `pinned_plan_version` — version-pinning on approval"

        Design: Corner/cross_cutting_layers/version_pinning_repin_after_supersede
        """
        scenario = setup_pcr_activated(npi="1000000280")
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert agreement["status"] == "AMENDMENT_REQUIRED"
        original_pin = agreement["pinned_plan_version"]
        assert agreement["plan_id"] == scenario["plan"]["id"], (
            "the pin is preserved through the cascade"
        )
        successor = get_success_data(api.get_comp_plan(scenario["successor"]["id"], ANALYST))
        repinned = validate_success(
            api.repin_agreement(scenario["agreement"]["id"], ANALYST), 200
        )
        assert repinned["status"] == "EFFECTIVE"
        assert repinned["plan_id"] == scenario["successor"]["id"]
        assert repinned["pinned_plan_version"] == successor["version"], (
            "repin snapshots the successor's CURRENT version"
        )
        assert repinned["pinned_plan_version"] != original_pin, (
            "the stale pin is observably replaced"
        )


class TestPcrWorkflow:
    def test_revise_clears_acknowledgments(self, api):
        """PRD §3.9: "If the numbers change, an analyst revises the request, moving `COMMUNICATED → MODELED`, clearing `acknowledged_physician_ids` — prior acknowledgments are invalidated by the revision — and recomputing the model"

        Design: Corner/state_machines/pcr_revise_clears_acknowledgments
        """
        scenario = setup_pcr_communicated(acknowledge=True, npi="1000000219")
        pcr_id = scenario["pcr"]["id"]
        assert scenario["physician"]["id"] in scenario["pcr"]["acknowledged_physician_ids"]
        revised = validate_success(api.revise_plan_change(pcr_id, ANALYST), 200)
        assert revised["status"] == "MODELED", "revise reverts COMMUNICATED to MODELED"
        assert revised["acknowledged_physician_ids"] == [], (
            "prior acknowledgments are compensated away"
        )

    def test_communicate_and_activate_timing_guards(self, api):
        """PRD §3.9: "Communicating moves a `MODELED` request to `COMMUNICATED` and requires the `effective_date` to be strictly after the logical-clock date, otherwise `ERR_PCR_TIMING`."
        PRD §3.9: "Activating a `COMMUNICATED` request requires the logical-clock date to be at least the `effective_date` (`ERR_PCR_TIMING`)"

        Design: Corner/validations/pcr_timing_violations_rejected
        """
        # Clock stays at 2026-01-01; effective_date 2026-03-01 is strictly future.
        scenario = setup_pcr_communicated(acknowledge=True, npi="1000000249")
        pcr_id = scenario["pcr"]["id"]
        assert scenario["pcr"]["status"] == "COMMUNICATED", (
            "effective_date strictly after the clock date allows communication"
        )
        resp = api.activate_plan_change(pcr_id, COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_PCR_TIMING)
        after = get_success_data(api.get_plan_change_request(pcr_id, ANALYST))
        assert after["status"] == "COMMUNICATED", (
            "the scheduled action cannot fire before its effective date"
        )

    def test_activation_requires_full_acknowledgment(self, api):
        """PRD §3.9: "Activating a `COMMUNICATED` request requires the logical-clock date to be at least the `effective_date` (`ERR_PCR_TIMING`), every physician with an `EFFECTIVE` agreement on the changed plan to appear in `acknowledged_physician_ids` (`ERR_ACK_INCOMPLETE`), and the successor to still be `FMV_APPROVED` (`ERR_SUCCESSOR_MISMATCH`)."

        Design: Corner/validations/pcr_ack_incomplete_blocks_activation
        """
        scenario = setup_pcr_communicated(acknowledge=False, npi="1000000250")
        pcr_id = scenario["pcr"]["id"]
        set_clock("2026-03-01T00:00:00Z")  # effective date reached
        resp = api.activate_plan_change(pcr_id, COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_ACK_INCOMPLETE)
        after = get_success_data(api.get_plan_change_request(pcr_id, ANALYST))
        assert after["status"] == "COMMUNICATED"


class TestPcrLinkage:
    def test_second_nonterminal_successor_rejected(self, api):
        """PRD §3.1: "At most one non-terminal successor — one whose `status` is `DRAFT`, `PENDING_REVIEW`, or `FMV_APPROVED` — may exist per superseded plan; drafting a second is rejected with `ERR_SUCCESSOR_EXISTS`."
        PRD §3.1: "a dedicated listing answers the plans whose `supersedes_plan_id` points at a given plan, so the office can trace the succession chain in reverse."

        Design: Corner/validations/successor_exists_rejected
        """
        set_clock()
        p1, p2 = setup_successor_pair(p1_name="P1S", p2_name="P2S")
        assert p2["status"] == "FMV_APPROVED"  # a non-terminal successor already exists
        resp = api.create_comp_plan(
            create_comp_plan_payload(name="P3S", quality_pool_cents=130000,
                                     supersedes_plan_id=p1["id"]),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SUCCESSOR_EXISTS)
        rows, meta = validate_paginated(api.list_successor_plans(p1["id"], ANALYST))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == p2["id"]

    def test_successor_must_supersede_the_changed_plan(self, api):
        """PRD §3.9: "The successor must be `FMV_APPROVED` and its `supersedes_plan_id` must equal the changed plan's `id`, otherwise `ERR_SUCCESSOR_MISMATCH`."

        Design: Corner/validations/successor_mismatch_rejected
        """
        set_clock()
        p1, _ = create_active_plan(name="P1M")
        p2, _ = create_active_plan(name="P2M")
        # P3 is FMV_APPROVED but supersedes P2, not P1.
        p3, _ = create_fmv_approved_plan(name="P3M", supersedes_plan_id=p2["id"])
        current = get_success_data(api.get_comp_plan(p1["id"], ANALYST))
        resp = api.create_plan_change_request(
            create_pcr_payload(
                plan_id=p1["id"], successor_plan_id=p3["id"],
                effective_date="2026-03-01", summary="bad link",
                expected_comp_plan_version=current["version"],
            ),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SUCCESSOR_MISMATCH)

    def test_pcr_create_with_stale_plan_version_rejected(self, api):
        """PRD §2.6: "Proposing a plan-change request likewise requires `expected_comp_plan_version`. Creating a plan-change request legitimately withdraws any existing `PROPOSED` or `MODELED` change requests for the same plan (a create-with-supersede), so a client holding a stale plan `version` would silently supersede a change request it never saw; the stale create is refused with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "Creation is a create-with-supersede: any existing `PROPOSED` or `MODELED` requests for the same plan are withdrawn, and the changed plan's `version` increments."
        PRD §3.9: "a plan-scoped listing with an optional `status` filter enumerates a plan's change requests."

        Design: Corner/cross_cutting_layers/occ_pcr_create_stale_plan_version
        """
        set_clock()
        p1, p2 = setup_successor_pair(p1_name="P1O", p2_name="P2O")
        observed = get_success_data(api.get_comp_plan(p1["id"], ANALYST))
        first = create_pcr(p1["id"], p2["id"], effective_date="2026-03-01",
                           summary="first",
                           expected_comp_plan_version=observed["version"])
        assert first["status"] == "PROPOSED"
        bumped = get_success_data(api.get_comp_plan(p1["id"], ANALYST))
        assert bumped["version"] == observed["version"] + 1, (
            "the create-with-supersede increments the changed plan's version"
        )
        resp = api.create_plan_change_request(
            create_pcr_payload(
                plan_id=p1["id"], successor_plan_id=p2["id"],
                effective_date="2026-04-01", summary="second",
                expected_comp_plan_version=observed["version"],  # now stale
            ),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        rows, meta = validate_paginated(api.list_plan_change_requests(p1["id"], ANALYST))
        assert meta["total_count"] == 1, "the stale create superseded nothing"
        assert rows[0]["id"] == first["id"]
