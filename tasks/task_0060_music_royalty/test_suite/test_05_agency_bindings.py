"""Agency bindings — overlap rules, adjacency, applicability (PRD §3.4,
§2.10 priorities 19 and 20)."""
from __future__ import annotations
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_agency_binding,
    create_agency_binding_payload,
    create_rights_holder,
    iso,
    make_rights_holder_headers,
    now_utc,
    validate_error,
    validate_success,
)


class TestCreateBinding:

    def test_create_binding_minimal(self, api):
        """PRD §3.4: 'Each binding declares a rights_holder_id, an
        agency_kind, a human-readable agency_name of 1 to 200
        characters, a territory (an ISO 3166-1 alpha-2 country code or
        the literal WW for worldwide), a commission_percent between
        0.00 and 50.00 inclusive at two decimal places, an inclusive
        UTC effective_from, and an optional exclusive UTC
        effective_until.'

        Claim: POST /royalty/agency-bindings returns 201 with the
        documented fields and ACTIVE status.
        """
        h = create_rights_holder()
        eff_from = iso(now_utc() - timedelta(days=10))
        eff_until = iso(now_utc() + timedelta(days=30))
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=eff_from,
                effective_until=eff_until,
            ),
            make_rights_holder_headers(h["id"]),
        )
        data = validate_success(resp, 201)
        assert_agency_binding(data)
        assert data["status"] == "ACTIVE"


class TestOverlapAndAdjacency:

    def test_overlapping_binding_rejected(self, api):
        """PRD §3.4 / §2.10 priority 19: 'On agency binding creation,
        effective_from must be strictly less than effective_until when
        effective_until is supplied, and a new binding for the same
        (rights_holder_id, agency_kind, territory) triple must not
        overlap an existing ACTIVE binding's half-open interval; an
        overlap yields ERR_AGENCY_BINDING_OVERLAP (409).'

        Claim: second binding with effective_from strictly inside the
        first binding's window → ERR_AGENCY_BINDING_OVERLAP (409).
        """
        h = create_rights_holder()
        now = now_utc()
        a_from = iso(now - timedelta(days=30))
        a_until = iso(now + timedelta(days=30))
        # First binding — active over the next 60 days.
        api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=a_from, effective_until=a_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        # Second binding starts BEFORE first ends.
        b_from = iso(now + timedelta(days=10))
        b_until = iso(now + timedelta(days=90))
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=b_from, effective_until=b_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENCY_BINDING_OVERLAP.value, 409)

    def test_adjacent_binding_at_exact_handover_permitted(self, api):
        """PRD §3.4 / §2.10 priority 20: 'A successor binding for the
        same (rights_holder_id, agency_kind) and territory must start
        at or after its predecessor's effective_until — strictly
        earlier is rejected with the same ERR_AGENCY_BINDING_OVERLAP;
        the rule allows zero buffer (immediate handover at the same
        instant is valid).'

        Claim: successor effective_from EQUAL to predecessor
        effective_until succeeds (201).
        """
        h = create_rights_holder()
        now = now_utc()
        a_from = iso(now - timedelta(days=30))
        a_until = iso(now + timedelta(days=30))
        api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=a_from, effective_until=a_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        # Successor starts at exact instant predecessor ends.
        b_from = a_until
        b_until = iso(now + timedelta(days=120))
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=b_from, effective_until=b_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        data = validate_success(resp, 201)
        assert data["effective_from"] == b_from

    def test_inverted_effective_from_until_rejected(self, api):
        """PRD §3.4 / §2.10 priority 19: 'effective_from must be
        strictly less than effective_until when effective_until is
        supplied... an overlap yields ERR_AGENCY_BINDING_OVERLAP (409).'

        The first part of priority 19 — temporal ordering — is also
        bucketed under ERR_AGENCY_BINDING_OVERLAP per the validations
        table.

        Claim: effective_from >= effective_until →
        ERR_AGENCY_BINDING_OVERLAP (409).
        """
        h = create_rights_holder()
        now = now_utc()
        bad_from = iso(now + timedelta(days=30))
        bad_until = iso(now + timedelta(days=10))
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=bad_from, effective_until=bad_until,
                territory="US", agency_kind="PUBLISHER",
            ),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENCY_BINDING_OVERLAP.value, 409)


class TestTerminate:

    def test_terminate_binding_succeeds(self, api):
        """PRD §3.4: 'Explicit termination through the terminate
        operation flips status to TERMINATED.'

        Claim: POST /royalty/agency-bindings/{id}/terminate → 200 with
        status==TERMINATED.
        """
        h = create_rights_holder()
        now = now_utc()
        resp = api.create_agency_binding(
            create_agency_binding_payload(
                rights_holder_id=h["id"],
                effective_from=iso(now - timedelta(days=1)),
                effective_until=iso(now + timedelta(days=30)),
                territory="US",
            ),
            make_rights_holder_headers(h["id"]),
        )
        binding = validate_success(resp, 201)
        term_resp = api.terminate_agency_binding(
            binding["id"], make_rights_holder_headers(h["id"]),
        )
        data = validate_success(term_resp, 200)
        assert data["status"] == "TERMINATED"
