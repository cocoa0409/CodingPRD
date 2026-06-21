"""Payload factories — one per writable entity, input fields only.

Required vs optional follows the PRD:
  - Client: name, billing_email (both required)
  - Linguist: full_name, native_locale, qualified_pairs (required);
              can_review (default false), daily_throughput_words (default 2500) optional
  - RateCard: source_locale, target_locale, base_rate_cents_per_word,
              linguist_rate_cents_per_word (required); active (default true) optional
  - Project: client_id, rate_card_id, name (required);
             rush_tier (default STANDARD), certification_mode (default NONE) optional
  - ProjectJob: filename (required); four quoted_*_words bands optional (default 0)
  - Assignment: job_id, linguist_id, role, window_start, window_end,
                expected_job_version (all required)
  - QAReport: reviewer_assignment_id, scored_word_count (required);
              critical_count/major_count/minor_count optional (default 0)
  - Invoice issue: expected_project_version (required)
"""
from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme",
        "billing_email": "ar@acme.test",
    }
    defaults.update(overrides)
    return defaults


def create_linguist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Trans One",
        "native_locale": TEST_DEFAULTS["TARGET_LOCALE"],
        "qualified_pairs": [
            {
                "source_locale": TEST_DEFAULTS["SOURCE_LOCALE"],
                "target_locale": TEST_DEFAULTS["TARGET_LOCALE"],
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "source_locale": TEST_DEFAULTS["SOURCE_LOCALE"],
        "target_locale": TEST_DEFAULTS["TARGET_LOCALE"],
        "base_rate_cents_per_word": TEST_DEFAULTS["BASE_RATE_CENTS_PER_WORD"],
        "linguist_rate_cents_per_word": TEST_DEFAULTS["LINGUIST_RATE_CENTS_PER_WORD"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, rate_card_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "rate_card_id": rate_card_id,
        "name": "P1",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(filename="a.docx", **overrides) -> dict:
    defaults = {"filename": filename}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(job_id, linguist_id, role, expected_job_version,
                              window_start="2026-06-01T00:00:00.000Z",
                              window_end="2026-06-02T00:00:00.000Z",
                              **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "linguist_id": linguist_id,
        "role": role,
        "window_start": window_start,
        "window_end": window_end,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def create_qa_report_payload(reviewer_assignment_id, scored_word_count,
                             **overrides) -> dict:
    defaults = {
        "reviewer_assignment_id": reviewer_assignment_id,
        "scored_word_count": scored_word_count,
    }
    defaults.update(overrides)
    return defaults


def deliver_payload(actual_no_match_words=0, actual_fuzzy_words=0,
                    actual_reps_words=0, actual_context_words=0, **overrides) -> dict:
    defaults = {
        "actual_no_match_words": actual_no_match_words,
        "actual_fuzzy_words": actual_fuzzy_words,
        "actual_reps_words": actual_reps_words,
        "actual_context_words": actual_context_words,
    }
    defaults.update(overrides)
    return defaults


def issue_invoice_payload(expected_project_version, **overrides) -> dict:
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults
