"""Every write's own response body already carries what an immediate read reports."""
from test_helpers import (
    CASE_MANAGER_ALT,
    CASE_MANAGER_TWO,
    admit_panelist,
    answer_verification,
    assert_all_mandatory_grounds,
    build_docket,
    clear_compliance,
    dispatch_notification,
    file_complaint,
    file_response,
    first_verification,
    load_of,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_domain,
    record_delivery,
    screen_seat,
)

IMMEDIATE_DOCKET = {
    "iana_id": "IANA-9044",
    "domain_name": "immediate.example",
    "legal_name": "Immediate Ltd",
    "country_code": "GB",
    "registrar_name": "Immediate Registrar",
    "verification_response_hours": 48,
}


class TestDerivedValuesSettleInsideTheWrite:
    def test_three_writes_report_the_same_derived_state_an_immediate_read_reports(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.2: "Finally, `honoraria_pool_cents` is 70 percent of
        `assessed_fee_cents`, rounded half up to a whole cent; the remaining 30 percent
        is the provider's administrative retention and is not stored on the case."
        PRD §3.3: "After every ledger write, and after every refund cascade, the case's
        three derived money fields are recomputed from the whole ledger rather than
        adjusted in place: `complainant_paid_cents` is the sum of `amount_cents` over
        the case's lines attributed to `COMPLAINANT`, `respondent_paid_cents` is the
        same sum over lines attributed to `RESPONDENT`, and `paid_cents` is the sum over
        every line on the case regardless of payer."
        PRD §3.4: "A successful clearance records the clearing officer on the case as
        `compliance_cleared_by_user_id`, moves the case from `FILED` to
        `VERIFICATION_PENDING`, and cascades into the registrar: a verification request
        row is created for the case in `status` `REQUESTED`, with `requested_at` at the
        current logical-clock instant and `due_at` that many hours later, where the
        number of hours is the sponsoring registrar's own `verification_response_hours`."
        PRD §3.4: "A domain sitting in `UNLOCKED` moves to `LOCKED` with `locked_at`
        stamped from the clock and the domain's `version` advancing; a domain already
        locked is left as it stands."
        PRD §3.6: "Anything below 30 seats the neutral directly: the engagement-window
        and capacity checks are re-run at this moment against the same half-open window
        and the same closed blackout interval, and if they pass, the seat moves to
        `ACCEPTED` with `accepted_at` stamped from the clock, `decision_due_at` set 14
        days later, and the neutral's `active_case_load` incremented by one."
        PRD §3.6: "A `SOLE` seat takes 100 percent of the pool exactly."

        Design: Corner/consistency_model/derived_fields_and_counters_are_already_settled_in_the_mutating_response
        """
        docket = build_docket(**IMMEDIATE_DOCKET)
        complainant = docket["complainant"]
        panelist = admit_panelist(
            full_name="Bram de Vries", nationality_code="NL",
            roster_admitted_at="2020-03-01T00:00:00Z",
            specializations=["TRADEMARK"], max_overlapping_engagements=3,
        )
        case = file_complaint(complainant, docket["domain"])
        case_id = case["id"]
        assert case["paid_cents"] == 0
        assert case["assessed_fee_cents"] == 150000
        assert case["honoraria_pool_cents"] == 105000
        assert_all_mandatory_grounds(case, complainant, evidence_count=1)

        # Write one: the ledger line, and the reconciliation an immediate read reports.
        line = post_ledger_line(case_id, 150000, reference="WIRE-9044")
        assert line["amount_cents"] == 150000
        assert line["recorded_at"] == "2026-08-01T00:00:00.000Z"
        after_fee = read_case(case_id)
        assert after_fee["paid_cents"] == 150000
        assert after_fee["complainant_paid_cents"] == 150000
        assert after_fee["respondent_paid_cents"] == 0

        # Write two: the clearance body, and the cascade it never returns.
        cleared = clear_compliance(
            case_id, headers=CASE_MANAGER_ALT, reviewer_notes="Complete."
        )
        assert cleared["status"] == "VERIFICATION_PENDING"
        assert cleared["compliance_cleared_by_user_id"] == CASE_MANAGER_TWO
        verification = first_verification(case_id)
        assert verification["status"] == "REQUESTED"
        assert verification["requested_at"] == "2026-08-01T00:00:00.000Z"
        assert verification["due_at"] == "2026-08-03T00:00:00.000Z"

        docket["case"] = read_case(case_id)
        docket["verification"] = verification
        answered = answer_verification(docket)
        assert answered["status"] == "RESPONDED"
        locked = read_domain(docket["domain"]["id"])
        assert locked["lock_status"] == "LOCKED"
        assert locked["locked_at"] == "2026-08-01T00:00:00.000Z"
        assert locked["version"] > docket["domain"]["version"]

        docket["notification"] = dispatch_notification(case_id)
        delivered = record_delivery(docket, "DELIVERED", deemed_received_at="2026-08-01T00:00:00Z")
        assert delivered["status"] == "DELIVERED"
        docket["case"] = read_case(case_id)
        file_response(docket)

        nominated = nominate_seat(case_id, "SOLE", panelist["id"])
        assert nominated["status"] == "NOMINATED"
        assert nominated["conflict_score"] is None
        assert nominated["honoraria_cents"] == 0
        assert load_of(panelist["id"]) == 0

        # Write three: one screening settles score, honoraria, timestamps and two
        # rows it does not return at all.
        screened = screen_seat(nominated["id"], panelist["id"])
        assert screened["status"] == "ACCEPTED"
        assert float(screened["conflict_score"]) == 0.00
        assert screened["honoraria_cents"] == 105000
        assert screened["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert screened["decision_due_at"] == "2026-08-15T00:00:00.000Z"

        reread = read_appointment(nominated["id"])
        assert reread["status"] == screened["status"]
        assert reread["conflict_score"] == screened["conflict_score"]
        assert reread["honoraria_cents"] == screened["honoraria_cents"]
        assert reread["accepted_at"] == screened["accepted_at"]
        assert reread["decision_due_at"] == screened["decision_due_at"]
        assert reread["version"] == screened["version"]
        assert reread["updated_at"] == screened["updated_at"]

        assert load_of(panelist["id"]) == 1, (
            "the panelist row moved inside the screening write, though it was never returned"
        )
        constituted = read_case(case_id)
        assert constituted["status"] == "PANEL_CONSTITUTED"
