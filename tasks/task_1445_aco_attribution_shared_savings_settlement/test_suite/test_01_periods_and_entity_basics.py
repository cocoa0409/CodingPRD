"""Period registration, overlap semantics, and entity field defaults."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_beneficiary,
    add_election,
    assert_agreement_period,
    assert_beneficiary,
    create_agreement_period_payload,
    create_beneficiary_payload,
    create_period,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPeriodRegistration:
    def test_get_period_not_found_returns_404(self, api, admin_headers):
        """PRD §2.10: "an unresolvable segment anywhere in the chain yields
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before any body validation beyond
        step 3 of §2.5 is consulted".

        Design: Corner/entities/get_period_not_found_returns_404
        """
        res = api.get_agreement_period(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)

    def test_period_create_invalid_track_enum(self, api, admin_headers):
        """PRD §3.1: "the `track`, which is either `ONE_SIDED` or `TWO_SIDED`".
        PRD §2.5: "required fields present, types valid, enum members valid, and
        unknown fields rejected, else `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/validations/period_create_invalid_track_enum
        """
        payload = create_agreement_period_payload(track="THREE_SIDED")
        res = api.create_agreement_period(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_period_double_open_rejected(self, api, admin_headers):
        """PRD §3.1: "Attempting to open a period that is not in `SETUP` is
        rejected with `ERR_PERIOD_NOT_OPEN` (HTTP 409)."

        Design: Corner/state_machines/period_double_open_rejected
        """
        period = create_period()
        validate_success(api.open_agreement_period(period["id"], admin_headers), 200)
        res = api.open_agreement_period(period["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_OPEN, expected_status=409)


class TestPeriodSpanOverlapClosedInterval:
    def test_adjacent_period_span_conflicts_closed_interval(self, api, admin_headers):
        """PRD §3.1: "a new span conflicts with an existing one whenever the new
        start falls on or before the existing end and the existing start falls on
        or before the new end — and under closed-interval semantics mere
        adjacency (sharing a boundary date) already counts as conflict. An
        overlapping registration is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/period_span_overlap_closed_interval
        """
        create_period(tax_id="ACO-OV", start="2026-01-01", end="2026-12-31")
        res = api.create_agreement_period(
            create_agreement_period_payload(
                aco_tax_id="ACO-OV", aco_name="OV-adj",
                performance_start_date="2026-12-31", performance_end_date="2027-12-31",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP, expected_status=409)

    def test_disjoint_span_and_other_tax_id_accepted(self, api, admin_headers):
        """PRD §3.1: "Because periods are closed intervals, two periods for the
        same `aco_tax_id` may not overlap".

        Design: Difficulty/resource_temporal_overlap/period_span_overlap_closed_interval
        """
        create_period(tax_id="ACO-OV", start="2026-01-01", end="2026-12-31")
        p2 = validate_success(
            api.create_agreement_period(
                create_agreement_period_payload(
                    aco_tax_id="ACO-OV", aco_name="OV-ok",
                    performance_start_date="2027-01-01", performance_end_date="2027-12-31",
                ),
                admin_headers,
            ),
            201,
        )
        assert_agreement_period(p2)
        p3 = validate_success(
            api.create_agreement_period(
                create_agreement_period_payload(
                    aco_tax_id="ACO-OTHER", aco_name="OTHER",
                    performance_start_date="2026-01-01", performance_end_date="2026-12-31",
                    track="TWO_SIDED",
                ),
                admin_headers,
            ),
            201,
        )
        assert_agreement_period(p3)


class TestBeneficiaryDefaults:
    def test_beneficiary_flag_defaults_applied(self, api, admin_headers):
        """PRD §3.1: "A beneficiary registration captures the globally unique
        `medicare_id`, the four-digit `birth_year`, and three boolean risk flags
        — `dual_eligible`, `disabled`, and `esrd` — each defaulting to false
        when omitted."

        Design: Corner/entities/beneficiary_flag_defaults_applied
        """
        res = api.create_beneficiary(
            create_beneficiary_payload(medicare_id="MBI-E2", birth_year=1985),
            admin_headers,
        )
        beneficiary = validate_success(res, 201)
        assert_beneficiary(beneficiary)
        assert beneficiary["dual_eligible"] is False
        assert beneficiary["disabled"] is False
        assert beneficiary["esrd"] is False

    def test_beneficiary_create_extra_field_rejected(self, api, admin_headers):
        """PRD §2.5: "required fields present, types valid, enum members valid,
        and unknown fields rejected, else `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/beneficiary_create_extra_field_rejected
        """
        payload = create_beneficiary_payload(medicare_id="MBI-E4", birth_year=1985)
        payload["nickname"] = "x"
        res = api.create_beneficiary(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestDataSharingElectionShape:
    def test_data_sharing_election_has_no_version_field(self, api, admin_headers):
        """PRD §2.4: "The exception is the `DataSharingElection`, which is an
        append-only event log entry: it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/data_sharing_election_has_no_version_field
        """
        beneficiary = add_beneficiary("MBI-E3", 1975)
        validate_success(
            api.create_data_sharing_election(
                beneficiary["id"],
                {"direction": "OPT_OUT", "effective_date": "2026-02-01"},
                admin_headers,
            ),
            201,
        )
        res = api.list_data_sharing_elections(beneficiary["id"], admin_headers)
        elections, _meta = validate_paginated(res)
        assert len(elections) == 1
        election = elections[0]
        assert election["direction"] == "OPT_OUT"
        assert is_valid_uuid(election["id"])
        assert "version" not in election, "append-only election must not expose version"
        assert "updated_at" not in election, "append-only election must not expose updated_at"

    def test_elections_sorted_by_effective_date(self, api, admin_headers):
        """PRD §2.3: "a beneficiary's data-sharing elections are sorted by
        `effective_date` ascending, ties broken by `created_at` ascending".

        Design: Corner/endpoints/elections_sorted_by_effective_date
        """
        beneficiary = add_beneficiary("MBI-N4", 1970)
        add_election(beneficiary["id"], "OPT_OUT", "2026-03-01")
        add_election(beneficiary["id"], "OPT_IN", "2026-01-15")
        res = api.list_data_sharing_elections(beneficiary["id"], admin_headers)
        elections, _ = validate_paginated(res)
        assert [e["direction"] for e in elections] == ["OPT_IN", "OPT_OUT"]
        assert elections[0]["effective_date"] == "2026-01-15"
        assert elections[1]["effective_date"] == "2026-03-01"
