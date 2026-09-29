"""Periodic performance review self-assessments: the shared denominator, the
overstatement escalation route into AT_RISK, and the reassessment cycle that
ends in attestation."""

from test_helpers import (
    ApiErrorId,
    create_standard,
    file_ppr,
    read_chapter,
    revise_ppr,
    setup_mapped_chapter,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains this file needs and test_helpers does not provide.
# ---------------------------------------------------------------------------


def _assessments_by_id(api, headers, chapter_id):
    """Every self-assessment of a chapter, keyed by identifier."""
    assessments, _meta = validate_paginated(
        api.list_ppr_self_assessments(chapter_id, headers)
    )
    return {item["id"]: item for item in assessments}


def _chapter_with_two_overstated_periods():
    """Provision-of-Care chapter with one mapped, evidence-free standard rated
    COMPLIANT twice, so two assessments are flagged for overstatement."""
    built = setup_mapped_chapter(
        code="PC",
        name="Provision of Care",
        weight_pct=100,
        evidence_min_count=1,
        standard_code="PC.01.02.03",
        title="Care planning",
        risk_tier="DIRECT_IMPACT",
    )
    ratings = [{"standard_id": built["standard"]["id"], "rating": "COMPLIANT"}]
    built["first_ppr"] = file_ppr(built["chapter"]["id"], "2026-H1", ratings)
    built["second_ppr"] = file_ppr(built["chapter"]["id"], "2026-H2", ratings)
    return built


# ===========================================================================
# Corner/state_machines
# ===========================================================================


def test_chapter_readiness_flag_derives_from_two_flagged_assessments(
    api, director_headers
):
    """PRD §3.9: "Each supplied rating earns points — one hundred for `COMPLIANT`, fifty for `PARTIAL`, zero for `NON_COMPLIANT` — and `self_score` is the sum of those points divided by the denominator, rounded half up to two decimal places."

    PRD §3.9: "Each standard of the chapter earns points from its `compliance_state` — one hundred for `EVIDENCE_COMPLETE`, fifty for `MAPPED`, and zero for both `UNMAPPED` and `DEFICIENT` — and `verified_score` is the sum of those points across every standard of the chapter, divided by the same denominator, rounded half up to two decimal places."

    PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."

    PRD §3.9: "A flagged assessment increments the owning chapter's `ppr_escalation_count` by one, and once that counter reaches two the chapter's `readiness_flag` becomes `AT_RISK` — the second of the two independent routes into `AT_RISK` described in §3.1."

    PRD §3.1: "It flips from `ON_TRACK` to `AT_RISK` as soon as either the chapter accumulates two or more deficient standards or its overstatement escalations reach two."

    PRD §3.9: "Every assessment of that chapter still in `SUBMITTED` moves `SUBMITTED → RETURNED_FOR_REASSESSMENT` with `requires_reassessment` set to true and its `version` advanced."

    Design: Corner/state_machines/chapter_readiness_flag_derives_from_two_flagged_ppr_assessments
    """
    built = setup_mapped_chapter(
        code="PC",
        name="Provision of Care",
        weight_pct=100,
        evidence_min_count=1,
        standard_code="PC.01.02.03",
        title="Care planning",
        risk_tier="DIRECT_IMPACT",
    )
    ratings = [{"standard_id": built["standard"]["id"], "rating": "COMPLIANT"}]

    first = file_ppr(built["chapter"]["id"], "2026-H1", ratings)

    assert float(first["self_score"]) == 100.00
    assert float(first["verified_score"]) == 50.00
    assert float(first["gap"]) == 50.00
    assert first["flagged_overstatement"] is True

    after_first = read_chapter(built["chapter"]["id"])

    assert after_first["ppr_escalation_count"] == 1
    assert after_first["readiness_flag"] == "ON_TRACK"

    second = file_ppr(built["chapter"]["id"], "2026-H2", ratings)

    after_second = read_chapter(built["chapter"]["id"])

    assert after_second["ppr_escalation_count"] == 2
    assert after_second["readiness_flag"] == "AT_RISK"

    by_id = _assessments_by_id(api, director_headers, built["chapter"]["id"])

    assert by_id[first["id"]]["state"] == "RETURNED_FOR_REASSESSMENT"
    assert by_id[first["id"]]["requires_reassessment"] is True
    assert second["flagged_overstatement"] is True


def test_revision_clears_reassessment_then_attestation_reaches_attested(
    api, director_headers
):
    """PRD §3.9: "Nothing a client does moves an assessment into `RETURNED_FOR_REASSESSMENT`: it happens when the owning chapter's `readiness_flag` flips `ON_TRACK → AT_RISK`, whether that flip came from deficient standards accumulating (§3.4, §3.7) or from overstatement escalations accumulating here."

    PRD §3.9: "Revision recomputes `self_score`, `verified_score` and `gap` under both variants, sets `requires_reassessment` back to false, and moves the assessment `RETURNED_FOR_REASSESSMENT → SUBMITTED`."

    PRD §3.9: "It also increments the chapter's `ppr_escalation_count` by one, but only when the recomputed `gap` is at least 10.00 **and** `flagged_overstatement` had previously been false — a chapter is not charged twice for the same overstatement."

    PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."

    PRD §3.9: "On success the assessment moves `SUBMITTED → ATTESTED` and `attested_by_user_id` is stamped with the attesting principal's identifier."

    Design: Corner/state_machines/ppr_revise_clears_reassessment_then_attest_reaches_attested
    """
    built = _chapter_with_two_overstated_periods()
    by_id = _assessments_by_id(api, director_headers, built["chapter"]["id"])

    assert by_id[built["first_ppr"]["id"]]["state"] == "RETURNED_FOR_REASSESSMENT"

    revised = revise_ppr(
        built["first_ppr"]["id"],
        [{"standard_id": built["standard"]["id"], "rating": "NON_COMPLIANT"}],
    )

    assert revised["state"] == "SUBMITTED"
    assert float(revised["self_score"]) == 0.00
    assert float(revised["gap"]) == -50.00
    assert revised["requires_reassessment"] is False
    assert read_chapter(built["chapter"]["id"])["ppr_escalation_count"] == 2

    attested = validate_success(
        api.attest_ppr_self_assessment(
            built["first_ppr"]["id"],
            {"attestation_note": "Reassessment reflects the evidence"},
            director_headers,
        )
    )

    assert attested["state"] == "ATTESTED"
    assert attested["attested_by_user_id"] == "dir-1"

    by_id_after = _assessments_by_id(api, director_headers, built["chapter"]["id"])

    assert by_id_after[built["first_ppr"]["id"]]["state"] == "ATTESTED"
    assert by_id_after[built["first_ppr"]["id"]]["requires_reassessment"] is False


def test_attesting_an_already_attested_assessment_rejected(api, director_headers):
    """PRD §2.11: "Attestation requires `state` to be `SUBMITTED`, rejecting an already-attested assessment with `ERR_PPR_ALREADY_ATTESTED`, and requires `requires_reassessment` to be false, rejecting otherwise with `ERR_PPR_REASSESSMENT_REQUIRED` — both 409, on `POST /accreditation/ppr-self-assessments/{id}/attest`."

    PRD §3.9: "An `AccreditationDirector` attests, optionally recording an `attestation_note`, and two conditions apply: the assessment must be in `SUBMITTED` — an assessment already in `ATTESTED` is refused with `ERR_PPR_ALREADY_ATTESTED` — and its `requires_reassessment` must be false, or the attempt is refused with `ERR_PPR_REASSESSMENT_REQUIRED`."

    PRD §3.9: "On success the assessment moves `SUBMITTED → ATTESTED` and `attested_by_user_id` is stamped with the attesting principal's identifier."

    PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."

    Design: Corner/state_machines/ppr_attest_twice_returns_already_attested
    """
    built = setup_mapped_chapter(
        code="EM",
        name="Emergency Management",
        weight_pct=20,
        evidence_min_count=1,
        standard_code="EM.02.01.01",
        title="Emergency operations plan",
        risk_tier="INDIRECT_IMPACT",
    )

    ppr = file_ppr(
        built["chapter"]["id"],
        "2026-H2",
        [{"standard_id": built["standard"]["id"], "rating": "PARTIAL"}],
    )

    assert float(ppr["self_score"]) == 50.00
    assert float(ppr["gap"]) == 0.00
    assert ppr["flagged_overstatement"] is False
    assert read_chapter(built["chapter"]["id"])["ppr_escalation_count"] == 0

    attested = validate_success(
        api.attest_ppr_self_assessment(
            ppr["id"], {"attestation_note": "Signed off"}, director_headers
        )
    )

    assert attested["state"] == "ATTESTED"

    repeated = api.attest_ppr_self_assessment(
        ppr["id"], {"attestation_note": "Second attempt"}, director_headers
    )

    validate_error(repeated, ApiErrorId.ERR_PPR_ALREADY_ATTESTED)

    reread = _assessments_by_id(api, director_headers, built["chapter"]["id"])[ppr["id"]]

    assert reread["state"] == "ATTESTED"
    assert reread["attested_by_user_id"] == "dir-1"


# ===========================================================================
# Corner/validations
# ===========================================================================


def test_attesting_while_reassessment_required_rejected(api, director_headers):
    """PRD §2.11: "Attestation requires `state` to be `SUBMITTED`, rejecting an already-attested assessment with `ERR_PPR_ALREADY_ATTESTED`, and requires `requires_reassessment` to be false, rejecting otherwise with `ERR_PPR_REASSESSMENT_REQUIRED` — both 409, on `POST /accreditation/ppr-self-assessments/{id}/attest`."

    PRD §3.9: "An `AccreditationDirector` attests, optionally recording an `attestation_note`, and two conditions apply: the assessment must be in `SUBMITTED` — an assessment already in `ATTESTED` is refused with `ERR_PPR_ALREADY_ATTESTED` — and its `requires_reassessment` must be false, or the attempt is refused with `ERR_PPR_REASSESSMENT_REQUIRED`."

    PRD §3.9: "Every assessment of that chapter still in `SUBMITTED` moves `SUBMITTED → RETURNED_FOR_REASSESSMENT` with `requires_reassessment` set to true and its `version` advanced."

    Design: Corner/validations/ppr_attest_while_reassessment_required_rejected
    """
    built = _chapter_with_two_overstated_periods()
    returned = _assessments_by_id(api, director_headers, built["chapter"]["id"])[
        built["first_ppr"]["id"]
    ]

    assert returned["state"] == "RETURNED_FOR_REASSESSMENT"
    assert returned["requires_reassessment"] is True

    rejected = api.attest_ppr_self_assessment(
        returned["id"], {"attestation_note": "Attempting to sign off"}, director_headers
    )

    validate_error(rejected, ApiErrorId.ERR_PPR_REASSESSMENT_REQUIRED)

    reread = _assessments_by_id(api, director_headers, built["chapter"]["id"])[
        returned["id"]
    ]

    assert reread["state"] == "RETURNED_FOR_REASSESSMENT"
    assert reread["requires_reassessment"] is True
    assert reread["attested_by_user_id"] is None


# ===========================================================================
# Corner/calculations
# ===========================================================================


def test_ppr_denominator_counts_unrated_chapter_standards(api, director_headers):
    """PRD §3.9: "The whole value of this exercise is that the same chapter is scored twice from two different sources, and the two scores share one denominator: the chapter's `standard_count`, meaning **every** standard in the chapter, not merely the ones that were rated."

    PRD §3.9: "A chapter standard with no rating supplied contributes nothing to the numerator but still counts in the denominator, so silence is scored as zero."

    PRD §3.9: "Each supplied rating earns points — one hundred for `COMPLIANT`, fifty for `PARTIAL`, zero for `NON_COMPLIANT` — and `self_score` is the sum of those points divided by the denominator, rounded half up to two decimal places."

    PRD §3.9: "Each standard of the chapter earns points from its `compliance_state` — one hundred for `EVIDENCE_COMPLETE`, fifty for `MAPPED`, and zero for both `UNMAPPED` and `DEFICIENT` — and `verified_score` is the sum of those points across every standard of the chapter, divided by the same denominator, rounded half up to two decimal places."

    PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."

    PRD §3.9: "A flagged assessment increments the owning chapter's `ppr_escalation_count` by one, and once that counter reaches two the chapter's `readiness_flag` becomes `AT_RISK` — the second of the two independent routes into `AT_RISK` described in §3.1."

    PRD §3.9: "A new assessment begins at `state` `SUBMITTED` with `requires_reassessment` false and `attested_by_user_id` null."

    Design: Corner/calculations/ppr_denominator_counts_unrated_chapter_standards
    """
    built = setup_mapped_chapter(
        code="PC",
        name="Provision of Care",
        weight_pct=100,
        evidence_min_count=1,
        standard_code="PC.01.02.03",
        title="Care planning",
        risk_tier="DIRECT_IMPACT",
    )
    create_standard(
        built["chapter"]["id"], "PC.02.01.21", "Pain assessment", "INDIRECT_IMPACT"
    )

    ppr = file_ppr(
        built["chapter"]["id"],
        "2026-H1",
        [{"standard_id": built["standard"]["id"], "rating": "COMPLIANT"}],
    )

    assert float(ppr["self_score"]) == 50.00
    assert float(ppr["verified_score"]) == 25.00
    assert float(ppr["gap"]) == 25.00
    assert ppr["flagged_overstatement"] is True
    assert ppr["state"] == "SUBMITTED"

    chapter = read_chapter(built["chapter"]["id"])

    assert chapter["standard_count"] == 2
    assert chapter["ppr_escalation_count"] == 1
    assert chapter["readiness_flag"] == "ON_TRACK"
