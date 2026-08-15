"""Transcript submission metrics and quality-review scoring rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_workgroup, create_job, claim_job, submit_job, review_job,
    get_job, get_editor, get_job_transcripts, deliver_job,
    create_submit_payload, create_qa_review_payload,
    make_provider_headers, make_editor_headers, make_qa_supervisor_headers,
    TEST_USERS, TEXT_65_CHARS, TEXT_66_CHARS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_transcript_whitespace_excluded_from_visible_chars(api):
    """PRD §3.5: "Its length is measured two ways from `final_text`:
    `visible_char_count` is the length of the text after removing every
    whitespace character — spaces, tabs, and newlines — and `line_count` is
    that visible length divided into sixty-five-character lines, rounded up to
    a whole line, with zero characters yielding zero lines."

    Design: Corner/entities/transcript_whitespace_excluded_from_visible_chars
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor, final_text="ab cd\nef gh")
    transcripts = get_job_transcripts(job["id"])
    assert len(transcripts) == 1
    assert transcripts[0]["visible_char_count"] == 8, (
        "only the 8 non-whitespace characters 'abcdefgh' count")
    assert transcripts[0]["line_count"] == 1


def test_line_count_65_chars_bills_one_line(api):
    """PRD §3.5: "`visible_char_count` is the length of the text after removing
    every whitespace character — spaces, tabs, and newlines — and `line_count`
    is that visible length divided into sixty-five-character lines, rounded up
    to a whole line, with zero characters yielding zero lines."

    Design: Difficulty/boundary_precision_check/line_count_ceil_boundary_65_66
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor, final_text=TEXT_65_CHARS)
    transcript = get_job_transcripts(job["id"])[0]
    assert transcript["visible_char_count"] == 65
    assert transcript["line_count"] == 1, "ceil(65/65) == 1 — exactly one line"


def test_line_count_66_chars_bills_two_lines(api):
    """PRD §3.5: "`visible_char_count` is the length of the text after removing
    every whitespace character — spaces, tabs, and newlines — and `line_count`
    is that visible length divided into sixty-five-character lines, rounded up
    to a whole line, with zero characters yielding zero lines."

    Design: Difficulty/boundary_precision_check/line_count_ceil_boundary_65_66
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor, final_text=TEXT_66_CHARS)
    transcript = get_job_transcripts(job["id"])[0]
    assert transcript["visible_char_count"] == 66
    assert transcript["line_count"] == 2, "ceil(66/65) == 2 — one char over doubles the bill"


class TestQaWeightedDeduction:
    """Weighted scoring formula boundary combinations."""

    @pytest.mark.parametrize(
        "critical,major,minor,expected_score,expected_outcome",
        [
            (0, 4, 0, 80.0, "PASS"),
            (0, 4, 1, 79.0, "FAIL"),
            (1, 0, 0, 75.0, "FAIL"),
        ],
    )
    def test_qa_score_weighted_deduction_combinations(
            self, api, critical, major, minor, expected_score, expected_outcome):
        """PRD §3.5: "From the three tallies the system computes the review's
        `accuracy_score`: start from 100, subtract 25 points for every critical
        error, 5 points for every major error, and 1 point for every minor
        error, floor the result at zero, and round half-up to two decimal
        places. The review's `outcome` is `PASS` exactly when the score is at
        least 80.0 and the critical error count is zero; otherwise it is
        `FAIL`."

        Design: Difficulty/combinatorial_formula/qa_score_weighted_deduction_with_clamp_and_critical_gate
        """
        wg = setup_workgroup()
        provider, editor = wg["provider"], wg["editor"]
        job = create_job(provider)
        claim_job(job["id"], editor)
        submit_job(job["id"], editor)
        review = review_job(job["id"], critical, major, minor)
        assert review["accuracy_score"] == pytest.approx(expected_score, abs=0.001), (
            f"expected score {expected_score}, got {review['accuracy_score']}")
        assert review["outcome"] == expected_outcome


def test_qa_fail_returns_job_to_editing_with_rework(api):
    """PRD §3.5: "On a `FAIL`, the current transcript version moves to
    `REJECTED`, the job returns from `SUBMITTED` to `EDITING` while remaining
    claimed by the same editor — so `active_claim_count` does not change — and
    the job's `rework_count` is incremented by one."

    Design: Difficulty/combinatorial_formula/qa_score_weighted_deduction_with_clamp_and_critical_gate
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    review_job(job["id"], 1, 0, 0)
    after = get_job(job["id"])
    assert after["workflow_status"] == "EDITING"
    assert after["rework_count"] == 1
    assert after["claimed_by_editor_id"] == editor["id"], (
        "a failed job remains claimed by the same editor")
    assert get_editor(editor["id"])["active_claim_count"] == 1
    transcript = get_job_transcripts(job["id"])[0]
    assert transcript["status"] == "REJECTED"


def test_qa_score_exactly_80_passes_and_delivers(api):
    """PRD §3.5: "The review's `outcome` is `PASS` exactly when the score is at
    least 80.0 and the critical error count is zero; otherwise it is `FAIL`."
    PRD §3.5: "On a `PASS`, the transcript moves from `SUBMITTED` to
    `DELIVERED`, its `delivered_at` is stamped, and its `aging_tier`
    initializes to `NONE` as the signature-queue aging clock of §3.7 starts
    ticking. The parent job moves from `SUBMITTED` to `DELIVERED` in step: its
    own `delivered_at` is stamped, `claimed_by_editor_id` and `claimed_at` are
    cleared, the editor's `active_claim_count` is decremented, and the
    editor-standing cascade of §3.6 runs."

    Design: Difficulty/boundary_precision_check/qa_pass_threshold_exactly_80
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    review = review_job(job["id"], 0, 4, 0)  # 100 - 20 == 80.0
    assert review["accuracy_score"] == pytest.approx(80.0, abs=0.001)
    assert review["outcome"] == "PASS", ">= 80.0 is inclusive at exactly 80.0"
    after = get_job(job["id"])
    assert after["workflow_status"] == "DELIVERED"
    transcript = get_job_transcripts(job["id"])[0]
    assert transcript["status"] == "DELIVERED"
    assert transcript["aging_tier"] == "NONE"
    assert transcript["delivered_at"] is not None


def test_qa_score_79_fails_at_boundary(api):
    """PRD §3.5: "The review's `outcome` is `PASS` exactly when the score is at
    least 80.0 and the critical error count is zero; otherwise it is `FAIL`."

    Design: Difficulty/boundary_precision_check/qa_pass_threshold_exactly_80
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    review = review_job(job["id"], 0, 4, 1)  # 100 - 20 - 1 == 79.0
    assert review["accuracy_score"] == pytest.approx(79.0, abs=0.001)
    assert review["outcome"] == "FAIL"
    after = get_job(job["id"])
    assert after["workflow_status"] == "EDITING"
    assert after["rework_count"] == 1


def test_qa_self_review_forbidden(api):
    """PRD §3.5: "Segregation of duties is hard-enforced: the reviewer's
    `X-User-ID` must differ from the transcript's `editor_id`, and a
    self-review is rejected with `ERR_SELF_REVIEW_FORBIDDEN`."

    Design: Corner/validations/qa_self_review_forbidden
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    # QASupervisor role, but X-User-ID equals the transcript's editor_id.
    resp = api.create_qa_review(
        create_qa_review_payload(job["id"]),
        make_qa_supervisor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN)
    assert get_job(job["id"])["workflow_status"] == "SUBMITTED"
    reviews = validate_success(api.list_job_qa_reviews(job["id"], VENDOR))
    assert reviews == [], "no QAReview may be recorded for a self-review"


def test_sign_submitted_transcript_returns_not_delivered(api):
    """PRD §3.8: "The provider whose job owns the transcript signs it; the
    transcript must be `DELIVERED` (`ERR_TRANSCRIPT_NOT_DELIVERED`), and the
    caller must be that provider (`ERR_FORBIDDEN_OWNERSHIP`)."

    Design: Corner/state_machines/sign_submitted_transcript_returns_not_delivered
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    transcript = get_job_transcripts(job["id"])[0]
    resp = api.sign_transcript(transcript["id"],
                               make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_TRANSCRIPT_NOT_DELIVERED)
    current = validate_success(api.get_transcript(transcript["id"], VENDOR))
    assert current["status"] == "SUBMITTED"
    assert current["signed_at"] is None


def test_addend_delivered_transcript_returns_not_signed(api):
    """PRD §3.8: "A provider may amend a transcript that is `SIGNED` —
    anything else yields `ERR_TRANSCRIPT_NOT_SIGNED`, with the usual ownership
    check — by supplying `addendum_text`."

    Design: Corner/state_machines/addend_delivered_transcript_returns_not_signed
    """
    wg = setup_workgroup()
    provider = wg["provider"]
    delivered = deliver_job(provider, wg["editor"])
    transcript = delivered["transcript"]
    assert transcript["status"] == "DELIVERED"
    resp = api.addend_transcript(transcript["id"], {"addendum_text": "correction"},
                                 make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_TRANSCRIPT_NOT_SIGNED)
    current = validate_success(api.get_transcript(transcript["id"], VENDOR))
    assert current["status"] == "DELIVERED"
