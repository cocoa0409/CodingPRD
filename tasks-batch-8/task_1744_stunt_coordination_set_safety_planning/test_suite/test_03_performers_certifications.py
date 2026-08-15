"""Performers and certifications: qualification lifecycle, suspension and
reinstatement, immutable certification records, and expiry boundary semantics
(PRD §2.4, §3.3)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    SAFETY,
    create_acknowledged_active_production,
    create_certification,
    create_certification_payload,
    create_locked_sequence,
    create_performer,
    create_production,
    create_qualified_performer,
    create_rehearsal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCertificationRecord:
    def test_certification_is_immutable_record(self, api):
        """PRD §2.4: "Two resources are immutable records and therefore carry
        only `id` and `created_at`: a Certification and an Inspection have
        neither `updated_at` nor `version`. A certification, once recorded,
        changes only through revocation; an inspection, once recorded, never
        changes at all."

        Design: Corner/entities/ent_certification_immutable_no_version_field
        """
        prod = create_production(name="P", budget=5000000)
        perf = create_performer(prod["id"], first_name="Im", last_name="Mut")
        cert = create_certification(perf["id"], discipline="FIGHT", level="BASIC")
        data = validate_success(api.get_certification(cert["id"], COORD))
        assert "id" in data and "created_at" in data
        assert "version" not in data, "immutable record must not carry version"
        assert "updated_at" not in data, "immutable record must not carry updated_at"


class TestPerformerListing:
    def test_performer_list_pagination(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0." and "The `meta` object
        of every list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/ent_performer_list_pagination
        """
        prod = create_production(name="P", budget=5000000)
        for first, last in [("A", "One"), ("B", "Two"), ("C", "Three")]:
            create_performer(prod["id"], first_name=first, last_name=last)
        page1, meta1 = validate_paginated(
            api.list_performers(COORD, params={"production_id": prod["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_performers(COORD, params={"production_id": prod["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestSuspensionCycle:
    def test_suspend_reinstate_round_trip(self, api):
        """PRD §3.3: "Adding a performer's first valid certification moves them
        `REGISTERED → QUALIFIED`" and "A `SafetyOfficer` may suspend a performer
        — with a `reason` — only from `QUALIFIED` (`ERR_PERFORMER_NOT_QUALIFIED`
        otherwise), moving them to `SUSPENDED`, and may reinstate only from
        `SUSPENDED` (again `ERR_PERFORMER_NOT_QUALIFIED` otherwise), provided at
        least one valid certification exists at reinstatement time (else
        `ERR_NO_VALID_CERTIFICATION`)."

        Design: Corner/state_machines/sm_performer_suspend_reinstate_cycle
        """
        prod = create_production(name="P", budget=5000000)
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        read = validate_success(api.get_performer(perf["id"], COORD))
        assert read["status"] == "QUALIFIED", "first valid certification promotes REGISTERED -> QUALIFIED"
        suspended = validate_success(api.suspend_performer(perf["id"], {"reason": "incident review"}, SAFETY))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_performer(perf["id"], SAFETY))
        assert reinstated["status"] == "QUALIFIED"

    def test_reinstate_without_valid_certification_rejected(self, api):
        """PRD §3.3: "may reinstate only from `SUSPENDED` (again
        `ERR_PERFORMER_NOT_QUALIFIED` otherwise), provided at least one valid
        certification exists at reinstatement time (else
        `ERR_NO_VALID_CERTIFICATION`)."
        PRD §3.3: "`SUSPENDED` when the stored status is `SUSPENDED`"

        Design: Corner/state_machines/sm_performer_reinstate_without_valid_cert_rejected
        """
        prod = create_production(name="P", budget=5000000)
        perf, cert = create_qualified_performer(prod["id"], discipline="FIGHT")
        validate_success(api.suspend_performer(perf["id"], {"reason": "review"}, SAFETY))
        validate_success(api.revoke_certification(cert["id"], SAFETY, {"reason": "credential fraud"}))
        resp = api.reinstate_performer(perf["id"], SAFETY)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_CERTIFICATION)
        read = validate_success(api.get_performer(perf["id"], COORD))
        assert read["status"] == "SUSPENDED", "failed reinstate mutates nothing"


class TestCertificationExpiryBoundary:
    def test_cert_expiring_exactly_at_rehearsal_start_is_expired(self, api):
        """PRD §3.3: "A certification is valid exactly when `revoked` is false
        and `expires_at` lies strictly after the comparison instant — a
        certification expiring exactly at the comparison instant is already
        expired." and "The comparison instant depends on context: the current
        logical time for status derivation, reinstatement, and pay agreement;
        the rehearsal's own `scheduled_start` for rehearsal scheduling; and the
        current logical time again for rehearsal completion." and "must hold a
        valid certification whose `discipline` equals the sequence's
        `hazard_class`, validity measured against the rehearsal's
        `scheduled_start` (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`)."

        Design: Corner/calculations/calc_cert_expiry_equality_rejected
        """
        prod = create_acknowledged_active_production(name="P", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Cert Seq", hazard_class="FIGHT", risk_category="LOW")
        perf = create_performer(prod["id"], first_name="Ab", last_name="Ex")
        # Certification expires exactly at the rehearsal's scheduled_start.
        validate_success(
            api.create_certification(
                create_certification_payload(perf["id"], discipline="FIGHT", level="BASIC",
                                             expires_at="2026-08-02T10:00:00Z"),
                COORD,
            ),
            201,
        )
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T10:00:00Z", scheduled_end="2026-08-02T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING_OR_EXPIRED)
