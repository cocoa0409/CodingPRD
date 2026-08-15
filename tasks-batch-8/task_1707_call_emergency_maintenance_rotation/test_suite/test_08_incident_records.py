"""Incident documentation: review loop, singleton rule, insurance gates."""
from test_helpers import (
    ApiErrorId,
    api_client,
    arrive_ticket,
    close_ticket,
    create_dispatched_ticket,
    create_incident_record,
    create_incident_record_payload,
    get_incident_record,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_technician_headers,
    make_unit,
    mitigate_ticket,
    publish_shift,
    set_clock,
    start_shift,
    submit_incident_record,
    validate_error,
    validate_success,
)


def _setup_on_scene_ticket(unit_number, category="APPLIANCE"):
    """Technician + supervisor + unit + ACTIVE shift + ticket ON_SCENE."""
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number=unit_number)
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T08:00:00Z")
    start_shift(shift["id"])
    ticket = create_dispatched_ticket(unit["id"], tech["id"], category,
                                      description="sparking outlet")
    arrive_ticket(ticket["id"], tech["id"])
    return tech, sup, unit, ticket


def test_incident_record_return_revision_cycle(api):
    """PRD §3.8: "A `MaintenanceSupervisor` then begins review (`SUBMITTED →
    UNDER_REVIEW`), and from review may either return the record — supplying a
    `reason` that is stored as `return_reason`, moving `UNDER_REVIEW →
    RETURNED` — or finalize it. A returned record goes back to its creator
    through revision: the technician supplies a fresh `narrative` and
    `estimated_damage_cents`, the record moves `RETURNED → DRAFT`, and its
    `version` increments, ready for another submit."

    Design: Corner/state_machines/incident_record_return_revision_cycle
    """
    tech, sup, _unit, ticket = _setup_on_scene_ticket("S-3")
    sup_headers = make_supervisor_headers(sup["id"])
    record = create_incident_record(ticket["id"], tech["id"],
                                    narrative="v1 narrative",
                                    estimated_damage_cents=30000)
    submit_incident_record(record["id"], tech["id"])
    validate_success(
        api_client.begin_review_incident_record(record["id"], sup_headers), 200
    )
    returned = validate_success(
        api_client.return_incident_record(
            record["id"], {"reason": "Need moisture readings"}, sup_headers
        ),
        200,
    )
    assert returned["status"] == "RETURNED"

    revised = validate_success(
        api_client.revise_incident_record(
            record["id"],
            {"narrative": "v2 narrative with readings",
             "estimated_damage_cents": 42000},
            make_technician_headers(tech["id"]),
        ),
        200,
    )
    assert revised["status"] == "DRAFT", "revision returns the record to DRAFT"
    assert revised["estimated_damage_cents"] == 42000, "fields replaced on revise"

    resubmitted = validate_success(
        api_client.submit_incident_record(
            record["id"], make_technician_headers(tech["id"])
        ),
        200,
    )
    assert resubmitted["status"] == "SUBMITTED", (
        "RETURNED -> DRAFT -> SUBMITTED cycle traversed"
    )


def test_incident_record_double_submit_rejected(api):
    """PRD §3.8: "Every transition in the record's lifecycle — submit,
    begin-review, return, revise, and finalize alike — is valid only from its
    stated source state; attempting any of them from a different state is
    rejected with `ERR_INCIDENT_RECORD_INVALID_STATE`."
    PRD §3.8: "The drafting technician alone submits the record (`DRAFT →
    SUBMITTED`; a non-creator is rejected with `ERR_NOT_ASSIGNED_TECHNICIAN`)."

    Design: Corner/state_machines/incident_record_double_submit_rejected
    """
    tech, _sup, _unit, ticket = _setup_on_scene_ticket("S-7")
    record = create_incident_record(ticket["id"], tech["id"], narrative="doc",
                                    estimated_damage_cents=5000)
    submit_incident_record(record["id"], tech["id"])
    resp = api_client.submit_incident_record(
        record["id"], make_technician_headers(tech["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_RECORD_INVALID_STATE)
    assert get_incident_record(record["id"])["status"] == "SUBMITTED"


def test_incident_record_singleton_enforced(api):
    """PRD §3.8: "Every ticket supports exactly one incident record — a second
    create against the same ticket is rejected with
    `ERR_INCIDENT_RECORD_EXISTS`."

    Design: Corner/validations/incident_record_singleton_enforced
    """
    tech, _sup, _unit, ticket = _setup_on_scene_ticket("M-5")
    create_incident_record(ticket["id"], tech["id"], narrative="first",
                           estimated_damage_cents=1000)
    resp = api_client.create_incident_record(
        ticket["id"],
        create_incident_record_payload(narrative="second",
                                       estimated_damage_cents=2000),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_RECORD_EXISTS)


class TestInsuranceNotificationDeadline:
    def _setup_two_under_review_records(self):
        """Two FLOOD tickets closed 12:00 and 14:00; both records UNDER_REVIEW.

        Returns (tech, sup, record_a, record_b).
        """
        set_clock("2026-08-03T09:00:00Z")
        tech = make_technician()
        sup = make_supervisor()
        unit = make_unit(unit_number="C-5", building_code="BC")
        shift = publish_shift(tech["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T18:00:00Z")
        start_shift(shift["id"])
        sup_headers = make_supervisor_headers(sup["id"])

        records = []
        for (dispatch_at, mitigate_at, close_at, narrative) in (
            ("2026-08-03T10:00:00Z", "2026-08-03T11:30:00Z",
             "2026-08-03T12:00:00Z", "flood A doc"),
            ("2026-08-03T12:30:00Z", "2026-08-03T13:30:00Z",
             "2026-08-03T14:00:00Z", "flood B doc"),
        ):
            ticket = create_dispatched_ticket(
                unit["id"], tech["id"], "FLOOD", at=dispatch_at,
                description=narrative,
            )
            arrive_ticket(ticket["id"], tech["id"])
            set_clock(mitigate_at)
            mitigate_ticket(ticket["id"], tech["id"], mitigation_notes="done")
            record = create_incident_record(ticket["id"], tech["id"],
                                            narrative=narrative,
                                            estimated_damage_cents=150000)
            submit_incident_record(record["id"], tech["id"])
            set_clock(close_at)
            close_ticket(ticket["id"])
            validate_success(
                api_client.begin_review_incident_record(record["id"], sup_headers),
                200,
            )
            records.append(record)
        return tech, sup, records[0], records[1]

    def test_insurance_notification_deadline_boundary(self, api):
        """PRD §3.8: "At that moment the system also sets
        `insurance_notification_late`: notification is late only when
        `insurance_notified_at` is strictly later than the parent ticket's
        `closed_at` plus 24 hours — a notification landing exactly at the
        deadline is not late."

        Design: Corner/calculations/insurance_notification_deadline_boundary
        """
        _tech, sup, record_a, record_b = self._setup_two_under_review_records()
        sup_headers = make_supervisor_headers(sup["id"])

        set_clock("2026-08-04T12:00:00Z")
        notified_a = validate_success(
            api_client.notify_insurance_incident_record(
                record_a["id"], {"claim_number": "CLM-A"}, sup_headers
            ),
            200,
        )
        assert notified_a["insurance_notification_late"] is False, (
            "exactly at closed_at + 24h is not late"
        )

        set_clock("2026-08-04T14:00:01Z")
        notified_b = validate_success(
            api_client.notify_insurance_incident_record(
                record_b["id"], {"claim_number": "CLM-B"}, sup_headers
            ),
            200,
        )
        assert notified_b["insurance_notification_late"] is True, (
            "one second past the deadline is late"
        )
        assert notified_a["insurance_claim_number"] == "CLM-A"
        assert notified_b["insurance_claim_number"] == "CLM-B"


class TestFinalizeRequiresInsuranceDecision:
    def _setup(self):
        """Two closed tickets with records UNDER_REVIEW: A damage 150000,
        B damage 50000. Returns (tech, sup, record_a, record_b)."""
        set_clock("2026-08-03T09:00:00Z")
        tech = make_technician()
        sup = make_supervisor()
        unit = make_unit(unit_number="M-11", building_code="BM")
        shift = publish_shift(tech["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T18:00:00Z")
        start_shift(shift["id"])
        sup_headers = make_supervisor_headers(sup["id"])

        records = []
        for (category, damage, narrative) in (
            ("FLOOD", 150000, "A doc"),
            ("LEAK_MINOR", 50000, "B doc"),
        ):
            ticket = create_dispatched_ticket(
                unit["id"], tech["id"], category, description=narrative,
            )
            arrive_ticket(ticket["id"], tech["id"])
            mitigate_ticket(ticket["id"], tech["id"], mitigation_notes="done")
            record = create_incident_record(ticket["id"], tech["id"],
                                            narrative=narrative,
                                            estimated_damage_cents=damage)
            submit_incident_record(record["id"], tech["id"])
            close_ticket(ticket["id"])
            validate_success(
                api_client.begin_review_incident_record(record["id"], sup_headers),
                200,
            )
            records.append(record)
        return tech, sup, records[0], records[1]

    def test_finalize_requires_insurance_decision(self, api):
        """PRD §3.8: "when `estimated_damage_cents` is at least 100000 cents
        ($1,000.00) — equality requires it — a recorded notification is
        mandatory; below that threshold, finalize still requires either a
        recorded notification or an `insurance_waived_reason` supplied with the
        finalize call, which is then stored. Failing either branch is rejected
        with `ERR_INSURANCE_NOTIFICATION_REQUIRED`."

        Design: Corner/validations/finalize_requires_insurance_decision
        """
        _tech, sup, record_a, record_b = self._setup()
        sup_headers = make_supervisor_headers(sup["id"])

        # A: damage 150000 >= 100000 — notification is mandatory.
        resp_a = api_client.finalize_incident_record(record_a["id"], None,
                                                     sup_headers)
        validate_error(resp_a, ApiErrorId.ERR_INSURANCE_NOTIFICATION_REQUIRED)
        validate_success(
            api_client.notify_insurance_incident_record(
                record_a["id"], {"claim_number": "CLM-A"}, sup_headers
            ),
            200,
        )
        finalized_a = validate_success(
            api_client.finalize_incident_record(record_a["id"], None, sup_headers),
            200,
        )
        assert finalized_a["status"] == "FINALIZED"

        # B: damage 50000 < 100000 — notification or explicit waiver required.
        resp_b = api_client.finalize_incident_record(record_b["id"], None,
                                                     sup_headers)
        validate_error(resp_b, ApiErrorId.ERR_INSURANCE_NOTIFICATION_REQUIRED)
        finalized_b = validate_success(
            api_client.finalize_incident_record(
                record_b["id"],
                {"insurance_waived_reason": "Below notification threshold"},
                sup_headers,
            ),
            200,
        )
        assert finalized_b["status"] == "FINALIZED"
