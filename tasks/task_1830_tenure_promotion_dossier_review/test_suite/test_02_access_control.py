"""Authentication headers, role permission denials, ownership, the
confidentiality seal, and entity-backed voter identity (PRD §2.1, §2.7, §2.12)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_candidate_headers,
    make_committee_voter_headers,
    open_case,
    open_round,
    read_case,
    register_candidate,
    setup_department_stage_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_headers_rejected_before_existence(api):
    """PRD §2.1: "A request with a missing or empty header is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.12: "**Header presence.** The `X-User-ID` and `X-User-Role` headers
    must be present and non-empty, otherwise
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to
    every endpoint."

    Design: Corner/validations/missing_headers_unauthenticated
    """
    # No X-User-ID / X-User-Role at all, against a nonexistent case id: the
    # header check (priority 1) must fire before existence (priority 3).
    resp = api.get_case(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_not_found_beats_state_and_ownership(api):
    """PRD §2.12: "**Path resource existence.** Resource identifiers
    appearing in the request path must exist, validated left to right along the
    path — before any ownership evaluation, which itself needs the resource."

    Design: Corner/validations/not_found_beats_state_and_ownership
    """
    candidate = register_candidate("E9300", full_name="Cand NF")
    resp = api.submit_dossier(
        NON_EXISTENT_UUID, make_candidate_headers(candidate["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


def test_ownership_mismatch_on_foreign_case(api):
    """PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of
    the acting Candidate; ownership checks on any resource that references a
    Candidate — a case, a dossier item, a clock-extension request, an appeal —
    compare the resource's candidate reference to `X-User-ID`, and a mismatch is
    rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/validations/ownership_mismatch_on_foreign_case
    """
    cand_a = register_candidate("E9301", full_name="Cand OA")
    cand_b = register_candidate("E9302", full_name="Cand OB")
    case = open_case(cand_a["id"])

    resp = api.submit_dossier(case["id"], make_candidate_headers(cand_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert read_case(case["id"])["stage"] == "DOSSIER_ASSEMBLY"


def test_rbac_exclusive_operations_denied(
    api, po_headers, system_admin_headers  # noqa: ARG001 - fixtures document intent
):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.12: "**Role permission.** The role must be permitted for the
    endpoint, otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). This applies to every
    endpoint."
    PRD §4: POST /api/cases is ProvostOfficer-only; POST /api/cases/{id}/archive
    is RecordsOfficer-only; POST /api/appeals/{id}/resolve is AppealOfficer-only;
    POST /api/_clock/set_current_utc is SystemAdmin-only; POST
    /api/rounds/{id}/open is CommitteeChair-only.

    Design: Corner/rbac/rbac_exclusive_operations_denied
    """
    candidate = register_candidate("E9500", full_name="Cand RB")
    case = open_case(candidate["id"])

    # Candidate cannot open cases.
    err1 = api.create_case(
        {
            "candidate_id": candidate["id"],
            "review_cycle": "2026-2027",
            "target_rank": "ASSOCIATE_PROFESSOR",
            "seeking_tenure": True,
            "clock_policy": "ANNIVERSARY",
        },
        make_candidate_headers(candidate["id"]),
    )
    validate_error(err1, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Archival is RecordsOfficer-only (a ProvostOfficer is refused).
    err2 = api.archive_case(case["id"], po_headers)
    validate_error(err2, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Appeal resolution is AppealOfficer-only; the role gate fires even before
    # the nonexistent appeal's existence check.
    err3 = api.resolve_appeal(
        NON_EXISTENT_UUID,
        {"resolution": "DENIED", "resolution_text": "x"},
        po_headers,
    )
    validate_error(err3, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # The logical clock is SystemAdmin-only.
    err4 = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, po_headers)
    validate_error(err4, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Round opening is CommitteeChair-only (a voter is refused).
    err5 = api.open_round(
        NON_EXISTENT_UUID,
        make_committee_voter_headers(NON_EXISTENT_UUID),
    )
    validate_error(err5, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Sanity: the rightful SystemAdmin role passes the role gate.
    ok = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, system_admin_headers)
    validate_success(ok, 200)


def test_confidentiality_seal_conditional_on_waiver(api, po_headers, reader_headers):
    """PRD §2.7: "When a case is opened with `waiver_signed` set to true — the
    default when the field is omitted — the candidate has waived access to the
    review record, and any attempt by a `Candidate` to read invitations, rounds,
    or votes linked to a case whose `waiver_signed` is true is rejected with
    `ERR_CONFIDENTIAL_LETTERS_SEALED`. When `waiver_signed` is false, candidate
    reads of those resources are permitted."

    Design: Corner/rbac/rbac_confidentiality_seal_conditional_on_waiver
    """
    cand_sealed = register_candidate("E9501", full_name="Cand CF")
    cand_open = register_candidate("E9502", full_name="Cand CG")
    case_sealed = open_case(cand_sealed["id"], waiver_signed=True)
    case_open = open_case(cand_open["id"], waiver_signed=False)

    err_inv = api.list_invitations(
        make_candidate_headers(cand_sealed["id"]), {"case_id": case_sealed["id"]}
    )
    validate_error(err_inv, ApiErrorId.ERR_CONFIDENTIAL_LETTERS_SEALED)

    err_rounds = api.list_rounds(
        make_candidate_headers(cand_sealed["id"]), {"case_id": case_sealed["id"]}
    )
    validate_error(err_rounds, ApiErrorId.ERR_CONFIDENTIAL_LETTERS_SEALED)

    data, meta = validate_paginated(
        api.list_invitations(
            make_candidate_headers(cand_open["id"]), {"case_id": case_open["id"]}
        )
    )
    assert data == [] and meta["total_count"] == 0, (
        "waiver_signed false unseals candidate reads"
    )

    # Non-confidential reads (the case itself) remain open to the candidate.
    case_data = validate_success(
        api.get_case(case_sealed["id"], make_candidate_headers(cand_sealed["id"]))
    )
    assert case_data["stage"] == "DOSSIER_ASSEMBLY"


def test_voter_identity_must_be_committee_member(api, reader_headers):
    """PRD §2.12: "Role-scoped writes verify the acting identity — the candidate
    acting on their own case, item, extension, or appeal; the reviewer on their
    own invitation; the committee member or chair on their own committee's round
    — otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §3.5: "The vote's `member_id` is always resolved from the `X-User-ID`
    header, never accepted from the request body."

    Design: Corner/rbac/voter_identity_must_be_committee_member
    """
    ctx = setup_department_stage_case("E9503", member_count=1, email_prefix="vi")
    round_id = ctx["round"]["id"]
    open_round(round_id, ctx["committee_ctx"]["chair"]["id"])

    # The caller's X-User-ID matches no CommitteeMember of this committee.
    resp = api.create_vote(
        {"round_id": round_id, "ballot": "YES"},
        make_committee_voter_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    round_after = validate_success(api.get_round(round_id, reader_headers))
    assert round_after["votes_cast"] == 0, "Rejected identity must not cast"
