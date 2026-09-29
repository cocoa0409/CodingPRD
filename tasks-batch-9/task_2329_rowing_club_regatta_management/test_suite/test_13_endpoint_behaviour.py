"""Endpoints doing their declared job: reading a hull back out of storage, the
triage action, the bulk delinquency sweep with its per-row predicate, a declared
transition whose precondition is not yet met, and the lineup association call.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    api_client,
    assert_damage_report,
    assert_dues_invoice,
    assert_lineup_seat,
    assert_member,
    assert_regatta,
    assert_regatta_entry,
    assert_shell,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import seat
from test_helpers.fixtures import (
    add_shell,
    add_single,
    declare_lineup,
    enrol_athlete,
    file_damage,
    issue_invoice,
    open_entry,
    open_regatta,
    read_invoice,
    read_member,
    read_report,
    read_regatta,
    read_shell,
    run_delinquency,
    triage_report,
)

RECREATIONAL_SEASON_ASSESSMENT_CENTS = 74000


class TestHullReadBack:
    def test_a_freshly_added_hull_reads_back_exactly_as_stored(self):
        """Every declared input and every unsent default survives the round trip.

        PRD: "A new hull is `AVAILABLE`, its `slot_units` derived from
        `boat_class` as the trailer rack units it occupies (a single or a double
        occupies 1 unit, a four occupies 2, an eight occupies 3), and both
        condition indices — `condition_index_conservative` and
        `condition_index_optimistic` — initialised to 100."

        Design: Corner/endpoints/corner_shell_get_after_create_returns_the_stored_row
        """
        created = add_single(hull_name="Kingfisher", hull_weight_kg=14.0, home_bay="BAY-1")
        assert is_valid_uuid(created["id"]), (
            f"the server mints a uuid identifier, got {created['id']!r}"
        )

        stored = assert_shell(
            validate_success(api_client.get_shell(created["id"], CLUB_ADMIN_HEADERS))
        )
        assert stored["id"] == created["id"], (
            f"the read-back names the same row, got {stored['id']}"
        )
        assert stored["hull_name"] == "Kingfisher", (
            f"the painted name is persisted, got {stored['hull_name']}"
        )
        assert stored["boat_class"] == "1X", (
            f"the declared class is persisted, got {stored['boat_class']}"
        )
        assert stored["hull_weight_kg"] == pytest.approx(14.0, abs=0.01), (
            f"the weight is persisted at one decimal place, got {stored['hull_weight_kg']}"
        )
        assert stored["home_bay"] == "BAY-1", (
            f"the bay label is persisted, got {stored['home_bay']}"
        )
        assert stored["status"] == "AVAILABLE", (
            f"a new hull is available to row, got {stored['status']}"
        )
        assert stored["tier_restriction"] == "ANY", (
            "the unsent restriction takes its declared default, got "
            f"{stored['tier_restriction']}"
        )
        assert stored["condition_index_conservative"] == 100, (
            f"an undamaged hull reads 100, got {stored['condition_index_conservative']}"
        )
        assert stored["condition_index_optimistic"] == 100, (
            f"an undamaged hull reads 100, got {stored['condition_index_optimistic']}"
        )
        assert stored["version"] == 1, (
            f"the row has never been rewritten, got {stored['version']}"
        )
        assert stored["created_at"] == stored["updated_at"], (
            "no write has followed creation, so the two stamps agree: "
            f"{stored['created_at']} against {stored['updated_at']}"
        )
        assert stored["created_at"].startswith("2026-08-01T00:00:00"), (
            f"the row was minted at the season-start instant, got {stored['created_at']}"
        )


class TestTriageAction:
    def test_triage_records_the_disposition_and_the_acting_boatman(self, cast, single_shell):
        """The action endpoint moves the report and stamps who moved it.

        PRD: "A `disposition` of `REPAIR` moves it `REPORTED → TRIAGED` and stamps
        `triaged_by_user_id`."

        Design: Corner/endpoints/corner_damage_report_triage_action_endpoint_records_disposition
        """
        report = file_damage(
            single_shell["id"],
            cast["coach"]["id"],
            cast["coach_headers"],
            severity="MINOR",
            narrative="loose foot stretcher",
        )
        assert report["status"] == "REPORTED", (
            f"a new report starts REPORTED, got {report['status']}"
        )

        triaged = assert_damage_report(
            triage_report(report["id"], cast["boatman_headers"], disposition="REPAIR")
        )
        assert triaged["status"] == "TRIAGED", (
            f"the report moves REPORTED -> TRIAGED, got {triaged['status']}"
        )
        assert triaged["triaged_by_user_id"] == cast["boatman"]["id"], (
            "the acting equipment manager is stamped, expected "
            f"{cast['boatman']['id']}, got {triaged['triaged_by_user_id']}"
        )
        assert triaged["assigned_repair_bay"] is None, (
            "triage does not book a bay, got "
            f"{triaged['assigned_repair_bay']}"
        )
        assert triaged["severity_points"] == pytest.approx(6.0, abs=0.01), (
            "a fresh MINOR report deducts its full 6 points, got "
            f"{triaged['severity_points']}"
        )
        assert read_report(report["id"])["status"] == "TRIAGED", (
            "the stored report agrees with the action response"
        )

    def test_a_minor_report_leaves_the_hull_in_service_at_ninety_four(
        self, cast, single_shell
    ):
        """Only the two heavier severities take a hull off the water.

        PRD: "`COSMETIC` and `MINOR` reports leave the hull's status untouched.
        Either way both condition indices and the report's own `severity_points`
        are recomputed."

        Design: Corner/endpoints/corner_damage_report_triage_action_endpoint_records_disposition
        """
        report = file_damage(
            single_shell["id"],
            cast["coach"]["id"],
            cast["coach_headers"],
            severity="MINOR",
            narrative="loose foot stretcher",
        )
        triage_report(report["id"], cast["boatman_headers"], disposition="REPAIR")

        hull = assert_shell(read_shell(single_shell["id"]))
        assert hull["status"] == "AVAILABLE", (
            f"a MINOR report does not take the hull out of service, got {hull['status']}"
        )
        assert hull["condition_index_conservative"] == 94, (
            "100 less the 6 points a TRIAGED MINOR report still contributes is 94, got "
            f"{hull['condition_index_conservative']}"
        )
        assert hull["condition_index_optimistic"] == 94, (
            "a TRIAGED report counts in both input sets, so the optimistic index "
            f"agrees at 94, got {hull['condition_index_optimistic']}"
        )


class TestDelinquencySweep:
    def test_the_sweep_moves_only_the_invoice_whose_due_date_has_passed(self):
        """A per-row predicate, not a blanket pass over every open invoice.

        PRD: "Every invoice in status `ISSUED` or `PARTIALLY_PAID` whose `due_at`
        is strictly before the logical clock and whose `paid_cents` is still below
        `assessed_cents` moves to `DELINQUENT` — `ISSUED → DELINQUENT` or
        `PARTIALLY_PAID → DELINQUENT` — and the billed member's
        `dues_balance_cents` is recomputed."

        Design: Corner/endpoints/corner_delinquency_run_sweeps_only_past_due_invoices
        """
        overdue_member = enrol_athlete("Anna Overdue", "RECREATIONAL", 70.0)
        current_member = enrol_athlete("Ben Current", "RECREATIONAL", 72.0)
        overdue_invoice = issue_invoice(overdue_member["id"], due_at="2026-07-01T00:00:00Z")
        current_invoice = issue_invoice(current_member["id"], due_at="2026-09-01T00:00:00Z")

        swept = validate_success(run_delinquency(season_year=2026))
        assert len(swept) == 1, (
            f"exactly one invoice is behind its due date, got {len(swept)} rows"
        )
        assert swept[0]["id"] == overdue_invoice["id"], (
            f"the swept row is the past-due invoice, got {swept[0]['id']}"
        )

        assert assert_dues_invoice(read_invoice(overdue_invoice["id"]))["status"] == "DELINQUENT", (
            "the past-due invoice moves ISSUED -> DELINQUENT"
        )
        assert read_invoice(current_invoice["id"])["status"] == "ISSUED", (
            "the invoice due next month is left alone"
        )

    def test_only_the_swept_member_lands_on_hold(self):
        """Owing money is not itself the trigger; falling past due is.

        PRD: "Hop two: any member for whom at least one invoice transitioned into
        `DELINQUENT` *inside this same run* moves `ACTIVE → DUES_HOLD`, with
        `boathouse_access_level` recomputed to `NONE`."

        Design: Corner/endpoints/corner_delinquency_run_sweeps_only_past_due_invoices
        """
        overdue_member = enrol_athlete("Anna Overdue", "RECREATIONAL", 70.0)
        current_member = enrol_athlete("Ben Current", "RECREATIONAL", 72.0)
        issue_invoice(overdue_member["id"], due_at="2026-07-01T00:00:00Z")
        issue_invoice(current_member["id"], due_at="2026-09-01T00:00:00Z")
        run_delinquency(season_year=2026)

        held = assert_member(read_member(overdue_member["id"]))
        assert held["membership_status"] == "DUES_HOLD", (
            f"the swept member moves ACTIVE -> DUES_HOLD, got {held['membership_status']}"
        )
        assert held["boathouse_access_level"] == "NONE", (
            f"a member on hold loses boathouse access, got {held['boathouse_access_level']}"
        )

        untouched = assert_member(read_member(current_member["id"]))
        assert untouched["membership_status"] == "ACTIVE", (
            f"the member who is merely billed stays ACTIVE, got {untouched['membership_status']}"
        )
        assert untouched["dues_balance_cents"] == RECREATIONAL_SEASON_ASSESSMENT_CENTS, (
            "a non-zero balance on its own does not trigger the hold, got "
            f"{untouched['dues_balance_cents']}"
        )


class TestPreconditionOnADeclaredTransition:
    def test_entries_may_not_be_closed_before_the_deadline_arrives(self):
        """A declared path still refuses while its clock precondition is unmet.

        PRD: "`OPEN_FOR_ENTRY → ENTRIES_CLOSED` requires the logical clock to have
        reached `entry_deadline_at`, and thereafter no entry may be opened or
        submitted."

        Design: Corner/endpoints/corner_close_entries_before_deadline_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        assert regatta["entry_deadline_at"] == "2026-08-10T00:00:00Z", (
            f"the deadline is still nine days off, got {regatta['entry_deadline_at']}"
        )

        response = api_client.transition_regatta(
            regatta["id"], {"to_status": "ENTRIES_CLOSED"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATUS_TRANSITION.value)

        stored = assert_regatta(read_regatta(regatta["id"]))
        assert stored["status"] == "OPEN_FOR_ENTRY", (
            f"the regatta is still taking entries, got {stored['status']}"
        )
        assert stored["version"] == 1, (
            f"the refused transition consumed no version, got {stored['version']}"
        )


class TestLineupAssociation:
    def test_the_lineup_call_materialises_one_seat_per_declared_place(self, cast):
        """The association endpoint writes the seat rows and bumps the entry once.

        PRD: "A first declaration moves the entry `DRAFT → LINEUP_DECLARED` and
        creates a `LineupSeat` row per declared seat, each carrying its
        `regatta_entry_id`."

        Design: Corner/endpoints/corner_lineup_declaration_links_seats_to_entry_and_members
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_shell(
            hull_name="Grebe", boat_class="2X", hull_weight_kg=27.0, home_bay="BAY-2"
        )
        rowers = [
            enrol_athlete("Row One", "COMPETITIVE", 82.0),
            enrol_athlete("Row Two", "COMPETITIVE", 83.0),
        ]
        entry = open_entry(
            regatta["id"],
            shell["id"],
            cast["coach_headers"],
            event_code="M2X_OPEN",
            boat_class="2X",
            seed_time_seconds=400.0,
        )
        assert entry["version"] == 1, (
            f"a new entry starts at version 1, got {entry['version']}"
        )

        declared = assert_regatta_entry(
            declare_lineup(
                entry,
                [seat(rowers[0]["id"], 1, "ROWER"), seat(rowers[1]["id"], 2, "ROWER")],
                cast["coach_headers"],
            )
        )
        assert declared["status"] == "LINEUP_DECLARED", (
            f"the entry moves DRAFT -> LINEUP_DECLARED, got {declared['status']}"
        )
        assert declared["version"] == 2, (
            f"the whole batch costs one version bump, got {declared['version']}"
        )

        rows, meta = validate_paginated(
            api_client.list_lineup_seats(
                cast["coach_headers"], {"regatta_entry_id": entry["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"a 2X carries two seats, got {meta['total_count']}"
        )
        by_number = {row["seat_number"]: row for row in rows}
        assert sorted(by_number) == [1, 2], (
            f"the seats are numbered 1 and 2 from bow to stern, got {sorted(by_number)}"
        )
        assert by_number[1]["member_id"] == rowers[0]["id"], (
            f"the bow seat holds the first rower, got {by_number[1]['member_id']}"
        )
        assert by_number[2]["member_id"] == rowers[1]["id"], (
            f"the stern seat holds the second rower, got {by_number[2]['member_id']}"
        )
        for number, row in by_number.items():
            assert row["regatta_entry_id"] == entry["id"], (
                f"seat {number} carries its parent entry, got {row['regatta_entry_id']}"
            )

    def test_each_new_seat_is_unweighed_and_eligible(self, cast):
        """Seats are born with the weigh-in fields empty and the gates cleared.

        PRD: "Each seat is born with `weighed_kg`, `weighed_by_user_id` and
        `deadweight_kg` null, a `weigh_in_status` of `NOT_REQUIRED`, and a computed
        `eligibility_status`."

        Design: Corner/endpoints/corner_lineup_declaration_links_seats_to_entry_and_members
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_shell(
            hull_name="Grebe", boat_class="2X", hull_weight_kg=27.0, home_bay="BAY-2"
        )
        rowers = [
            enrol_athlete("Row One", "COMPETITIVE", 82.0),
            enrol_athlete("Row Two", "COMPETITIVE", 83.0),
        ]
        entry = open_entry(
            regatta["id"],
            shell["id"],
            cast["coach_headers"],
            event_code="M2X_OPEN",
            boat_class="2X",
            seed_time_seconds=400.0,
        )
        declare_lineup(
            entry,
            [seat(rowers[0]["id"], 1, "ROWER"), seat(rowers[1]["id"], 2, "ROWER")],
            cast["coach_headers"],
        )

        rows, _meta = validate_paginated(
            api_client.list_lineup_seats(
                cast["coach_headers"], {"regatta_entry_id": entry["id"]}
            )
        )
        for row in rows:
            row = assert_lineup_seat(row)
            assert row["seat_role"] == "ROWER", (
                f"a double carries no coxswain, got {row['seat_role']}"
            )
            assert row["weigh_in_status"] == "NOT_REQUIRED", (
                f"nothing is weighed until submission, got {row['weigh_in_status']}"
            )
            assert row["eligibility_status"] == "ELIGIBLE", (
                "a member clearing the dues, certification and safety gates is "
                f"ELIGIBLE, got {row['eligibility_status']}"
            )
            assert row["weighed_kg"] is None, (
                f"no weight has been recorded, got {row['weighed_kg']}"
            )
            assert row["weighed_by_user_id"] is None, (
                f"nobody has weighed the seat, got {row['weighed_by_user_id']}"
            )
            assert row["deadweight_kg"] is None, (
                f"no sandbag has been computed, got {row['deadweight_kg']}"
            )

        mine, meta = validate_paginated(
            api_client.list_lineup_seats(
                cast["coach_headers"], {"member_id": rowers[0]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the seat is reachable from the member side too, got "
            f"{meta['total_count']} rows"
        )
        assert mine[0]["regatta_entry_id"] == entry["id"], (
            f"and it points back at the entry, got {mine[0]['regatta_entry_id']}"
        )
