"""Versions quoted from a stale read, and a cascade read back at once.

The two concurrency-guarded writes are exercised the same way: a first write that
succeeds and silently moves the parent's version, a second write that still quotes
the pre-write version, and a replay after re-reading.  The last group shows the
opposite property — a cascade that is already complete in the response that
triggered it.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import FINANCE_APPROVER, OFFICER, REGISTRAR


class TestScheduleAppendGuardsTheTilingFrontier:
    @pytest.fixture()
    def contract_with_one_card(self, client):
        """One rate card appended, so the contract's version has already moved on."""
        agency = fx.register_agency(client, legal_name="OCC Contract Agency")
        fx.clear_agency(client, agency["id"])
        contract = fx.draft_contract(
            client,
            agency["id"],
            contract_ref="CTR-OCC",
            term_start_date="2026-08-01",
            term_end_date="2027-07-31",
            annual_commission_cap_cents=5000000,
        )
        stale_version = contract["version"]

        first_card = validate_success(
            client.append_commission_schedule(
                contract["id"],
                F.schedule_payload(
                    stale_version,
                    effective_from="2026-08-01",
                    effective_to="2026-10-01",
                ),
                OFFICER,
            ),
            201,
        )
        return {
            "contract_id": contract["id"],
            "stale_version": stale_version,
            "first_card": first_card,
        }

    def second_card_payload(self, expected_contract_version):
        """The card that tiles exactly onto the first one's trailing edge."""
        return F.schedule_payload(
            expected_contract_version,
            effective_from="2026-10-01",
            effective_to="2027-07-31",
            deposit_rate_bps=300,
            enrollment_rate_bps=400,
            census_rate_bps=200,
            persistence_rate_bps=100,
        )

    def test_the_successful_append_moves_the_contract_version_by_one(
        self, client, contract_with_one_card
    ):
        """The writer's view of the contract is stale the moment the card lands.

        "Note also that a successful append itself increments the contract's `version`
        by one, so a client adding two cards in sequence must re-read between them."

        "The server assigns `version_no` itself as the 1-based sequence number of the
        card in creation order within the contract, so the first card on a contract is
        1 and each subsequent card is one higher."

        Design: Corner/cross-cutting complexity layers/schedule_append_with_stale_contract_version_returns_412
        """
        env = contract_with_one_card

        assert env["first_card"]["version_no"] == 1
        assert (
            fx.contract_version(client, env["contract_id"]) == env["stale_version"] + 1
        )

    def test_the_second_append_is_refused_on_the_version_not_on_the_geometry(
        self, client, contract_with_one_card
    ):
        """The interval tiles exactly, so only the stale version can be at fault.

        "If that value does not equal the contract's current `version`, the append is
        rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        "In both cases the version field is a required input, not an optional one, and
        a mismatch is rejected before any side effect runs."

        Design: Corner/cross-cutting complexity layers/schedule_append_with_stale_contract_version_returns_412
        """
        env = contract_with_one_card

        refused = client.append_commission_schedule(
            env["contract_id"],
            self.second_card_payload(env["stale_version"]),
            OFFICER,
        )
        body = validate_error(refused, E.ERR_STALE_CONTRACT_VERSION, 412)
        assert body["error_id"] != E.ERR_SCHEDULE_GAP
        assert body["error_id"] != E.ERR_SCHEDULE_INTERVAL_CONFLICT

        assert len(fx.read_schedules(client, env["contract_id"])) == 1
        assert (
            fx.contract_version(client, env["contract_id"]) == env["stale_version"] + 1
        )

    def test_re_reading_the_contract_lets_the_identical_body_through(
        self, client, contract_with_one_card
    ):
        """The two cards then tile the term in order, numbered one and two.

        "every later card must begin precisely where the latest existing card ended"

        "Cards may be listed for a contract in tiling order."

        Design: Corner/cross-cutting complexity layers/schedule_append_with_stale_contract_version_returns_412
        """
        env = contract_with_one_card

        client.append_commission_schedule(
            env["contract_id"], self.second_card_payload(env["stale_version"]), OFFICER
        )

        fresh_version = fx.contract_version(client, env["contract_id"])
        second_card = validate_success(
            client.append_commission_schedule(
                env["contract_id"], self.second_card_payload(fresh_version), OFFICER
            ),
            201,
        )
        assert second_card["version_no"] == 2

        cards, meta = validate_paginated(
            client.list_commission_schedules(env["contract_id"], FINANCE_APPROVER)
        )
        assert meta["total_count"] == 2
        assert [card["effective_from"] for card in cards] == [
            "2026-08-01",
            "2026-10-01",
        ]
        assert [card["effective_to"] for card in cards] == ["2026-10-01", "2027-07-31"]


class TestMilestoneRegistrationGuardsTheApplicationVersion:
    @pytest.fixture()
    def admitted_file(self, client):
        """An admitted file and the version its registrar last observed."""
        partner = fx.build_active_partner(client, legal_name="OCC Application Agency")
        admitted = fx.build_admitted_application(
            client,
            partner,
            student_ref="STU-001",
            passport_hash="hash-occ-001",
            applicant_user_id="applicant-001",
        )
        return {
            "application_id": admitted["application_id"],
            "stale_version": admitted["version"],
        }

    def test_the_deposit_registration_consumes_and_advances_the_version(
        self, client, admitted_file
    ):
        """The first registration succeeds and leaves the quoted version behind.

        "Every milestone registration therefore recomputes the application's
        `net_commission_cents` and the agency's `net_earned_commission_cents`, and
        increments the application's `version` by one."

        Design: Corner/cross-cutting complexity layers/milestone_register_with_stale_application_version_returns_412
        """
        env = admitted_file

        registered = validate_success(
            client.register_milestone(
                env["application_id"],
                F.milestone_payload(
                    C.MILESTONE_DEPOSIT_PAID,
                    C.DEFAULT_CLOCK_DATE,
                    env["stale_version"],
                ),
                REGISTRAR,
            )
        )
        assert registered["status"] == C.APPLICATION_DEPOSIT_PAID
        assert registered["version"] == env["stale_version"] + 1

    def test_the_next_milestone_quoting_the_old_version_is_refused_before_ordering(
        self, client, admitted_file
    ):
        """Enrollment is the legal successor, so ordering was never the problem.

        "If that value does not equal the application's current `version`, the
        registration is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

        "The milestone chain is strictly ordered — `ADMITTED → DEPOSIT_PAID →
        ENROLLED → CENSUS_CONFIRMED → PERSISTED` — and only the immediate successor of
        the application's current `status` may be registered."

        Design: Corner/cross-cutting complexity layers/milestone_register_with_stale_application_version_returns_412
        """
        env = admitted_file
        fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            C.DEFAULT_CLOCK_DATE,
            env["stale_version"],
        )

        refused = client.register_milestone(
            env["application_id"],
            F.milestone_payload(
                C.MILESTONE_ENROLLED, C.DEFAULT_CLOCK_DATE, env["stale_version"]
            ),
            REGISTRAR,
        )
        body = validate_error(refused, E.ERR_STALE_APPLICATION_VERSION, 412)
        assert body["error_id"] != E.ERR_MILESTONE_OUT_OF_ORDER

        assert (
            fx.application_version(client, env["application_id"])
            == env["stale_version"] + 1
        )

    def test_the_replay_after_a_re_read_registers_the_enrollment(
        self, client, admitted_file
    ):
        """Two accruals stand once the registrar acts on the version it re-read.

        "so the registrar must prove it is acting on the version against which it
        evaluated milestone ordering"

        Design: Corner/cross-cutting complexity layers/milestone_register_with_stale_application_version_returns_412
        """
        env = admitted_file
        fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            C.DEFAULT_CLOCK_DATE,
            env["stale_version"],
        )
        client.register_milestone(
            env["application_id"],
            F.milestone_payload(
                C.MILESTONE_ENROLLED, C.DEFAULT_CLOCK_DATE, env["stale_version"]
            ),
            REGISTRAR,
        )

        fresh_version = fx.application_version(client, env["application_id"])
        enrolled = validate_success(
            client.register_milestone(
                env["application_id"],
                F.milestone_payload(
                    C.MILESTONE_ENROLLED, C.DEFAULT_CLOCK_DATE, fresh_version
                ),
                REGISTRAR,
            )
        )
        assert enrolled["status"] == C.APPLICATION_ENROLLED

        _, meta = validate_paginated(
            client.list_commission_entries(
                FINANCE_APPROVER,
                {
                    "application_id": env["application_id"],
                    "kind": C.ENTRY_KIND_ACCRUAL,
                },
            )
        )
        assert meta["total_count"] == 2


class TestUploadCascadeIsVisibleImmediately:
    @pytest.fixture()
    def flagged_upload(self, client):
        """A financial proof carrying four signals, and the response that created it."""
        agency = fx.register_agency(client, legal_name="Immediate Agency")
        fx.clear_agency(client, agency["id"])
        program = fx.create_program(client, annual_tuition_cents=2000000)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        assert application["integrity_hold"] is False

        created = validate_success(
            client.upload_document(
                application["id"],
                F.document_payload(
                    doc_type=C.DOC_FINANCIAL_PROOF,
                    content_hash="hash-imm-001",
                    issuer_name="Unknown Bank",
                    declared_signals=[
                        C.SIGNAL_ISSUER_UNVERIFIED,
                        C.SIGNAL_TRANSCRIPT_ANOMALY,
                        C.SIGNAL_TRANSLATION_MISMATCH,
                        C.SIGNAL_DATE_INCONSISTENCY,
                    ],
                ),
                fx.make_agency_owner_headers(agency["id"]),
            ),
            201,
        )
        return {
            "agency_id": agency["id"],
            "application_id": application["id"],
            "created": created,
        }

    def test_the_creating_response_already_carries_the_index_and_the_flag(
        self, client, flagged_upload
    ):
        """Nothing else was called between the upload and this assertion.

        "`fraud_index` is then the sum of the weights of the distinct signals in
        `fraud_signals`, capped at 100."

        "A document whose index reaches 60 is auto-flagged at upload: it lands in
        `verification_state` `FLAGGED` rather than `PENDING`"

        "Where this document says a cascade "runs", it means the whole chain runs
        inside the originating request, before the response is produced."

        Design: Corner/consistency model/document_upload_cascade_visible_in_the_same_response
        """
        created = flagged_upload["created"]

        assert created["fraud_index"] == 70
        assert created["verification_state"] == C.VERIFICATION_FLAGGED

    def test_the_owning_application_is_already_held_and_the_filter_already_finds_it(
        self, client, flagged_upload
    ):
        """The very next read sees the hold with no intervening write.

        "and the owning application's `integrity_hold` is set to true, which
        recomputes the agency's `reviewed_document_count`"

        "listed per application filtered by `doc_type` and `verification_state`"

        Design: Corner/consistency model/document_upload_cascade_visible_in_the_same_response
        """
        env = flagged_upload

        held = fx.read_application(client, env["application_id"])
        assert held["integrity_hold"] is True

        rows, meta = validate_paginated(
            client.list_application_documents(
                env["application_id"],
                OFFICER,
                {"verification_state": C.VERIFICATION_FLAGGED},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == env["created"]["id"]
