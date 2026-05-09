"""Rights-conflict checks: exclusivity, territory, term overlap, half-open
interval semantics, RIGHTS_CONFLICT_DETECTED audit row (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_offered_license,
    accept_offered_license,
    setup_effective_license,
    submit_round,
    list_audit_logs_filtered,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Exclusive-vs-exclusive conflicts
# ---------------------------------------------------------------------------

class TestExclusiveLicenseConflicts:
    """PRD §3.4: "If there exists at least one incumbent license whose
    exclusivity is EXCLUSIVE and which conflicts with the candidate, the
    candidate cannot be accepted and the server raises
    ERR_EXCLUSIVE_LICENSE_VIOLATION — an exclusive incumbent blocks anyone
    else on the overlapping slice."
    """

    def test_accept_exclusive_with_exclusive_incumbent_rejected(self, api):
        """PRD §3.4: exclusive incumbent + overlapping exclusive candidate →
        ERR_EXCLUSIVE_LICENSE_VIOLATION.

        # difficulty: dual_variant_calc/rights_conflict_exclusive_vs_nonexclusive_check
        """
        licensor = create_rights_holder(api, legal_name="L_owner")
        rh_b = create_rights_holder(api, legal_name="RH_B")
        rh_c = create_rights_holder(api, legal_name="RH_C")
        # Incumbent EXCLUSIVE license (bring it to EFFECTIVE).
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-31T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        # Candidate EXCLUSIVE license overlapping in territory + media + term.
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        # rh_c (licensee) attempts ACCEPT on candidate.
        from test_helpers import round_payload
        headers = make_rights_holder_headers(rh_c["id"])
        resp = api.submit_round(candidate["id"],
                                  round_payload(action="ACCEPT",
                                                  version=candidate["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_VIOLATION.value)

    def test_non_exclusive_overlap_logs_audit_and_succeeds(self, api):
        """PRD §3.4: 'If neither the candidate nor any conflicting incumbent
        is exclusive (both are NON_EXCLUSIVE), the conflict is allowed but is
        not silent: the server appends an AuditLog row of change_type
        RIGHTS_CONFLICT_DETECTED whose before is null and whose after
        snapshots the candidate license, then permits the acceptance.'

        # difficulty: dual_variant_calc/rights_conflict_exclusive_vs_nonexclusive_check
        """
        licensor = create_rights_holder(api, legal_name="L_owner")
        rh_b = create_rights_holder(api, legal_name="RH_B")
        rh_c = create_rights_holder(api, legal_name="RH_C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-31T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"],
            exclusivity="NON_EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"],
            exclusivity="NON_EXCLUSIVE",
        )
        accepted = accept_offered_license(api, candidate, rh_c)
        assert accepted["status"] == "ACCEPTED"
        # AuditLog row should record RIGHTS_CONFLICT_DETECTED for the candidate.
        logs = list_audit_logs_filtered(api,
                                          subject_id=candidate["id"],
                                          change_type="RIGHTS_CONFLICT_DETECTED")
        assert len(logs) >= 1, (
            "PRD §3.4: NON_EXCLUSIVE-NON_EXCLUSIVE overlap must append "
            "AuditLog with change_type=RIGHTS_CONFLICT_DETECTED"
        )

    def test_exclusive_candidate_with_any_conflict_rejected(self, api):
        """PRD §3.4: 'Symmetrically, if the candidate's own exclusivity is
        EXCLUSIVE and any other license at all conflicts with it, the
        candidate is again rejected with ERR_EXCLUSIVE_LICENSE_VIOLATION.'"""
        licensor = create_rights_holder(api, legal_name="L_owner")
        rh_b = create_rights_holder(api, legal_name="RH_B")
        rh_c = create_rights_holder(api, legal_name="RH_C")
        # Incumbent NON_EXCLUSIVE license.
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-31T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"],
            exclusivity="NON_EXCLUSIVE",
        )
        work = bundle["work"]
        # Candidate is EXCLUSIVE — should fail because any conflict triggers it.
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        from test_helpers import round_payload
        headers = make_rights_holder_headers(rh_c["id"])
        resp = api.submit_round(candidate["id"],
                                  round_payload(action="ACCEPT",
                                                  version=candidate["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_VIOLATION.value)


# ---------------------------------------------------------------------------
# Half-open interval semantics: adjacency does not overlap
# ---------------------------------------------------------------------------

class TestHalfOpenIntervalSemantics:
    """PRD §3.4: "Term overlap uses half-open interval semantics with the
    lower bound inclusive and the upper bound exclusive: the two terms
    overlap when the incumbent's term_start is strictly less than the
    candidate's term_end and, simultaneously, the candidate's term_start is
    strictly less than the incumbent's term_end. Adjacency — where one term
    ends at the same instant the other begins — therefore does not constitute
    overlap."
    """

    def test_adjacent_terms_do_not_conflict(self, api):
        """PRD §3.4: incumbent ends 2099-06-01, candidate starts 2099-06-01:
        adjacency is NON-overlapping; candidate accept succeeds.

        # difficulty: resource_temporal_overlap/license_term_half_open_overlap_check
        """
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-06-01T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",  # adjacency: meets at instant
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        accepted = accept_offered_license(api, candidate, rh_c)
        assert accepted["status"] == "ACCEPTED", (
            "PRD §3.4: half-open intervals — adjacency does NOT overlap"
        )

    def test_one_second_overlap_conflicts(self, api):
        """PRD §3.4: incumbent ends 2099-06-01T00:00:00Z; candidate starts
        2099-05-31T23:59:59Z (1-second overlap). Term overlap is true; with
        territory and media also overlapping, candidate rejected.

        # difficulty: resource_temporal_overlap/license_term_half_open_overlap_check
        """
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-06-01T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        # Candidate starts 1 second BEFORE incumbent ends — overlap.
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-05-31T23:59:59.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        from test_helpers import round_payload
        headers = make_rights_holder_headers(rh_c["id"])
        resp = api.submit_round(candidate["id"],
                                  round_payload(action="ACCEPT",
                                                  version=candidate["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_VIOLATION.value)


# ---------------------------------------------------------------------------
# Disjoint dimensions: no conflict if any of territory/media/term is disjoint
# ---------------------------------------------------------------------------

class TestDisjointConflictDimensions:
    """PRD §3.4: "A pair is in conflict if and only if territory overlap and
    media overlap and term overlap all hold."
    """

    def test_disjoint_territory_no_conflict(self, api):
        """PRD §3.4: incumbent territory=['US'], candidate territory=['CA'] →
        no territory overlap → no conflict, accept succeeds."""
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["CA"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        accepted = accept_offered_license(api, candidate, rh_c)
        assert accepted["status"] == "ACCEPTED"

    def test_disjoint_media_no_conflict(self, api):
        """PRD §3.4: media_types disjoint → no conflict."""
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["PRINT"], exclusivity="EXCLUSIVE",
        )
        accepted = accept_offered_license(api, candidate, rh_c)
        assert accepted["status"] == "ACCEPTED"
