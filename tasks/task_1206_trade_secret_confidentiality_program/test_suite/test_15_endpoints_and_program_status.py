"""Endpoint-level reads: counterparty-filtered obligation list and the
program-status computed read (PRD §3.2, §2.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    ApiErrorId,
    create_counterparty,
    create_nda_payload,
    create_obligation_payload,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]


class TestObligationsFilteredByCounterparty:
    def test_obligations_filtered_by_counterparty(self, api):
        """PRD §3.2: "Obligation tracking works by counterparty as well as by
        agreement: the obligations list filters by `nda_id`, `counterparty_id`,
        `status`, or `obligation_type`."

        Design: Corner/endpoints/obligations_filtered_by_counterparty
        """
        cp1 = create_counterparty(legal_name="Alpha One", counterparty_type="VENDOR")
        cp2 = create_counterparty(legal_name="Beta Two", counterparty_type="PARTNER")
        nda1 = validate_success(api.create_nda(
            create_nda_payload(cp1["id"], template_version="tA", governing_law="ID",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z",
                               survival_months=3, classification_ceiling="INTERNAL"), IP
        ), expected_status=201)
        nda2 = validate_success(api.create_nda(
            create_nda_payload(cp2["id"], template_version="tB", governing_law="ID",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z",
                               survival_months=3, classification_ceiling="INTERNAL"), IP
        ), expected_status=201)
        validate_success(api.create_obligation(
            create_obligation_payload(nda1["id"], obligation_type="NON_DISCLOSURE"), IP
        ), expected_status=201)
        validate_success(api.create_obligation(
            create_obligation_payload(nda2["id"], obligation_type="NON_USE"), IP
        ), expected_status=201)

        data, meta = validate_paginated(
            api.list_obligations(IP, params={"counterparty_id": cp1["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["nda_id"] == nda1["id"]
        assert all(row["nda_id"] != nda2["id"] for row in data), \
            "no row from the other counterparty's NDA may appear"


class TestProgramStatus:
    def test_program_status_reflects_clock_and_policy(self, api):
        """PRD §2.5: "Before any operator touches it, the server clock reads
        exactly `2026-05-01T00:00:00Z`."
        PRD §2.5: "A computed program-status read returns the
        `current_policy_version` (which starts at the string `\"v1\"` at server
        initialization), the current clock as `now_iso8601`, and per-entity
        status `counts`."

        Design: Corner/endpoints/program_status_reflects_clock_and_policy
        """
        data = validate_success(api.get_program_status(IP))
        assert data["current_policy_version"] == "v1"
        assert data["now_iso8601"] == "2026-05-01T00:00:00Z", \
            "fixed default logical clock, not wall clock"
