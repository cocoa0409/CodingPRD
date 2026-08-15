"""Escalation write visibility, matter resolution preconditions, and the
record challenge-resolution cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_alert,
    assert_enforcement_matter,
    assert_instant_equal,
    create_alert,
    docket_deadline,
    escalate_alert,
    get_alert,
    get_matter,
    get_record,
    make_associate_headers,
    make_paralegal_headers,
    make_partner_headers,
    satisfy_deadline,
    setup_escalated_matter,
    setup_published_record,
    triage_alert,
    validate_error,
    validate_success,
    verify_deadline,
)


class TestEscalationWriteVisibility:
    def test_immediate_visibility_of_escalate_writes(
        self, api, paralegal_headers, associate_headers
    ):
        """PRD §3.4: "A successful escalation creates the matter — the response body
        is the created matter, not the alert — with `client_id`,
        `trademark_record_id`, and `watch_alert_id` copied from the alert and its
        record, `matter_type` as supplied, `status` `ACTIVE`, `posture` `NORMAL`,
        `accrued_fees_cents` and `open_deadline_count` at zero, and
        `resolution_outcome` null. The alert moves to `ESCALATED`."
        PRD §2.7: "The index and posture are recomputed whenever a matter is created
        by escalation, resolved, or reopened, and whenever any linked deadline flips
        to `MISSED` or is satisfied late."

        Design: Corner/consistency_model/immediate_visibility_of_escalate_writes
        """
        client, record = setup_published_record(classes=(9,))
        alert = create_alert(record["id"], 80, 70, 60)
        alert = triage_alert(alert["id"])
        alert = assess_alert(alert["id"], alert["version"])

        res = api.escalate_alert(alert["id"], {"matter_type": "INFRINGEMENT"},
                                 associate_headers)
        matter = validate_success(res, 201)
        assert_enforcement_matter(matter)
        assert matter["status"] == "ACTIVE"
        assert matter["posture"] == "NORMAL"
        assert matter["accrued_fees_cents"] == 0
        assert matter["open_deadline_count"] == 0
        assert matter["resolution_outcome"] is None
        assert matter["client_id"] == client["id"]
        assert matter["trademark_record_id"] == record["id"]
        assert matter["watch_alert_id"] == alert["id"]

        assert get_alert(alert["id"])["status"] == "ESCALATED"
        refreshed_client = validate_success(
            api.get_client(client["id"], paralegal_headers), 200)
        assert refreshed_client["exposure_index"] == 20
        assert refreshed_client["watch_posture"] == "STANDARD"


class TestRecordChallengeLifecycle:
    def test_register_from_under_challenge_returns_invalid_state(
        self, api, paralegal_headers
    ):
        """PRD §3.2: "Escalating an alert into an `OPPOSITION` matter flips a
        `PUBLISHED` record to `UNDER_CHALLENGE`"
        PRD §3.2: "Registration, also by a `Paralegal`, carries the
        `registration_date` and moves the record from `PUBLISHED` to `REGISTERED`"
        PRD §2.10: "State — the target entity is in a state from which the requested
        transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/register_from_under_challenge_returns_invalid_state
        """
        _, record, _, _ = setup_escalated_matter(
            matter_type="OPPOSITION", publication_date="2026-07-31T00:00:00Z")
        assert get_record(record["id"])["status"] == "UNDER_CHALLENGE"

        res = api.register_record(record["id"],
                                  {"registration_date": "2026-08-10T00:00:00Z"},
                                  paralegal_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_record(record["id"])["status"] == "UNDER_CHALLENGE"

    def test_resolve_favorable_restores_published_then_register_succeeds(
        self, api, paralegal_headers, partner_headers
    ):
        """PRD §3.2: "Resolution cascades back: a `FAVORABLE` or `SETTLED` outcome on
        an opposition matter returns the record to `PUBLISHED`, the same outcomes on
        a cancellation matter return it to `REGISTERED`, and an `ADVERSE` outcome on
        either matter type cancels the record outright."
        PRD §3.2: "Registration, also by a `Paralegal`, carries the
        `registration_date` and moves the record from `PUBLISHED` to `REGISTERED`,
        computing the three maintenance horizons: `maintenance_window_open` five
        years after registration, `maintenance_window_close` six years after
        registration, and `maintenance_grace_close` six months beyond the window
        close."

        Design: Corner/state_machines/resolve_favorable_restores_published_then_register_succeeds
        """
        _, record, _, matter = setup_escalated_matter(
            matter_type="OPPOSITION", publication_date="2026-07-31T00:00:00Z")

        res = api.resolve_matter(matter["id"], {"outcome": "FAVORABLE"}, partner_headers)
        resolved = validate_success(res, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_outcome"] == "FAVORABLE"
        assert get_record(record["id"])["status"] == "PUBLISHED"

        registered = validate_success(
            api.register_record(record["id"],
                                {"registration_date": "2026-08-10T00:00:00Z"},
                                paralegal_headers), 200)
        assert registered["status"] == "REGISTERED"
        assert_instant_equal(registered["maintenance_window_open"],
                             "2031-08-10T00:00:00Z", "maintenance_window_open")
        assert_instant_equal(registered["maintenance_window_close"],
                             "2032-08-10T00:00:00Z", "maintenance_window_close")
        assert_instant_equal(registered["maintenance_grace_close"],
                             "2033-02-10T00:00:00Z", "maintenance_grace_close")


class TestMatterResolutionGates:
    def test_resolve_blocked_by_open_deadlines(
        self, api, paralegal_headers, partner_headers
    ):
        """PRD §3.4: "Resolution belongs to a `PartnerAttorney` and requires the
        matter to have no open deadlines — `open_deadline_count` counts linked
        deadlines in `DOCKETED`, `PENDING`, or `EXTENDED`, and a nonzero count is
        rejected with `ERR_PENDING_DEADLINES`."

        Design: Corner/validations/resolve_blocked_by_open_deadlines
        """
        _, _, _, matter = setup_escalated_matter()
        deadline = docket_deadline(matter["id"], user_id="para_1")
        assert deadline["status"] == "DOCKETED"

        res = api.resolve_matter(matter["id"], {"outcome": "FAVORABLE"}, partner_headers)
        validate_error(res, ApiErrorId.ERR_PENDING_DEADLINES, expected_status=409)

        verify_deadline(deadline["id"], user_id="assoc_2")
        satisfy_deadline(deadline["id"])
        ok = api.resolve_matter(matter["id"], {"outcome": "FAVORABLE"}, partner_headers)
        resolved = validate_success(ok, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["open_deadline_count"] == 0

    def test_docket_on_resolved_matter_rejected(self, api, partner_headers):
        """PRD §3.5: "Deadlines are docketed onto an `ACTIVE` matter by a `Paralegal`
        or `AssociateAttorney`; docketing against a matter in any other status is
        rejected with `ERR_MATTER_NOT_ACTIVE`."

        Design: Corner/validations/docket_on_resolved_matter_rejected
        """
        _, _, _, matter = setup_escalated_matter()
        validate_success(
            api.resolve_matter(matter["id"], {"outcome": "FAVORABLE"}, partner_headers),
            200)

        res = api.docket_deadline(
            matter["id"],
            {
                "deadline_type": "RESPONSE_DUE",
                "statutory_basis": "37 CFR 2.196",
                "basis_date": "2026-08-07T09:00:00Z",
                "offset_days": 5,
            },
            make_paralegal_headers("para_1"),
        )
        validate_error(res, ApiErrorId.ERR_MATTER_NOT_ACTIVE, expected_status=409)

    def test_paralegal_cannot_resolve_matter(self, api, paralegal_headers):
        """PRD §3.4: "Resolution belongs to a `PartnerAttorney` and requires the
        matter to have no open deadlines"
        PRD §2.1: "Once authenticated, the caller's role must appear in the
        endpoint's authorized role list, or the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/paralegal_cannot_resolve_matter
        """
        _, _, _, matter = setup_escalated_matter()
        res = api.resolve_matter(matter["id"], {"outcome": "FAVORABLE"},
                                 paralegal_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_matter(matter["id"])["status"] == "ACTIVE"
