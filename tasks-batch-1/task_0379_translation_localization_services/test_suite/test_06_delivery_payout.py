"""Job delivery, the provisional-vs-final linguist payout divergence, the delivery
certificate, and the empty-analysis precondition.

Covers difficulty rule `dual_variant_calc` (linguist payout variant) plus corner
`entities` (delivery certificate, payout ledger) and `validations` instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_client, create_rate_card, create_linguist, create_project, add_job,
    quote_and_approve, assign, accept_as_translator,
    current_job_version, make_translator_headers,
    setup_job_qa_passed, setup_job_in_qa, file_qa_report, deliver,
    DEFAULT_ACTUAL_BANDS,
)

PM = TEST_USERS["pm_headers"]


def _qa_passed_with_bonus_score():
    """EXPRESS+CERTIFIED job through QA_PASSED with a 96.2 (>=95) score, ready to deliver.
    Provisional translator payout is 15975. Returns ctx."""
    return setup_job_qa_passed(rush_tier="EXPRESS", certification_mode="CERTIFIED",
                               critical_count=1, major_count=0, minor_count=0,
                               scored_word_count=2600)


# ─── dual_variant_calc: provisional vs final linguist payout ───────────────
def test_final_payout_diverges_from_provisional_with_qa_bonus(api):
    """PRD §3.9: "The **provisional** variant, applied when an assignment is accepted,
    uses the job's quoted bands and applies no quality adjustment".
    PRD §3.9: "The **final** variant, applied at job delivery, recomputes the base over
    the actual bands and then applies a quality adjustment keyed on the job's
    `latest_qa_score`: if the latest QA score is at least ninety-five, a bonus of the base
    multiplied by five hundredths (rounded half up) is added".
    PRD §3.7: "its `payout_cents` is recomputed via the final payout variant (actual
    bands plus a quality adjustment, see §3.9), its `payout_finalized` flag is set to
    true".

    Provisional 15975 (quoted bands) -> final 17719 (actual bands 1875 weighted, base
    16875, +5% bonus 844).

    Design: Difficulty/dual_variant_calc/dvc_linguist_provisional_vs_final_payout_on_linguist
    """
    ctx = _qa_passed_with_bonus_score()
    provisional = validate_success(
        api.get_assignment(ctx["translator_assignment"]["id"], PM), 200)
    assert provisional["payout_cents"] == 15975, \
        f"expected provisional 15975, got {provisional['payout_cents']}"
    deliver(ctx, actual_bands=dict(DEFAULT_ACTUAL_BANDS))
    final = validate_success(
        api.get_assignment(ctx["translator_assignment"]["id"], PM), 200)
    assert final["payout_cents"] == 17719, \
        f"expected final 17719, got {final['payout_cents']}"
    assert final["payout_finalized"] is True, f"got {final['payout_finalized']}"


def test_final_payout_reconciled_into_committed_payout(api):
    """PRD §3.7: "A `FINAL_ADJUST` ledger entry is appended whose `amount_cents` is the
    final payout minus the provisional payout — which may be negative if the final figure
    is lower — and the linguist's `committed_payout_cents` is reconciled by that same
    provisional-to-final delta."

    Second probe of the variant divergence on the linguist's derived balance: after
    delivery, committed_payout_cents equals the final figure 17719.

    Design: Difficulty/dual_variant_calc/dvc_linguist_provisional_vs_final_payout_on_linguist
    """
    ctx = _qa_passed_with_bonus_score()
    deliver(ctx, actual_bands=dict(DEFAULT_ACTUAL_BANDS))
    ling = validate_success(api.get_linguist(ctx["translator"]["id"], PM), 200)
    assert ling["committed_payout_cents"] == 17719, \
        f"expected 17719, got {ling['committed_payout_cents']}"


# ─── corner entities: delivery certificate, payout ledger ──────────────────
def test_delivery_certificate_minted_on_certified_delivery(api):
    """PRD §3.7: "If the project's `certification_mode` is not `NONE`, delivery mints a
    **delivery certificate** for the job. The certificate copies the project's
    `certification_mode` into its own `certification_mode` ... computes a `page_count`
    equal to the job's actual total source words divided by two hundred fifty words per
    page rounded up to the next whole page".

    Design: Corner/entities/delivery_certificate_minted_on_certified_delivery
    """
    ctx = setup_job_qa_passed(certification_mode="CERTIFIED",
                              critical_count=0, major_count=0, minor_count=1,
                              scored_word_count=2600)
    deliver(ctx, actual_bands=dict(DEFAULT_ACTUAL_BANDS))  # actual total 2600 -> 11 pages
    data, _ = validate_paginated(api.list_job_certificate(ctx["job"]["id"], PM))
    assert len(data) == 1, f"expected 1 certificate, got {len(data)}"
    assert data[0]["certification_mode"] == "CERTIFIED", f"got {data[0]['certification_mode']}"
    assert data[0]["page_count"] == 11, f"expected 11, got {data[0]['page_count']}"


def test_payout_ledger_commit_entry_minted_on_accept(api):
    """PRD §2.9: "The `entry_type` is `COMMIT` when an assignment is accepted".
    PRD §3.5: "a `COMMIT` ledger entry of that amount is appended, and the linguist's
    `committed_payout_cents` is increased by that amount."

    Design: Corner/entities/payout_ledger_commit_entry_minted_on_accept
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="T")
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])  # default bands -> provisional 15975
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], translator["id"])
    data, _ = validate_paginated(
        api.list_linguist_payout_ledger(translator["id"], PM))
    assert len(data) == 1, f"expected 1 ledger entry, got {len(data)}"
    assert data[0]["entry_type"] == "COMMIT", f"got {data[0]['entry_type']}"
    assert data[0]["amount_cents"] == 15975, f"expected +15975, got {data[0]['amount_cents']}"


# ─── corner validations: deliver empty analysis ────────────────────────────
def test_deliver_with_empty_actual_analysis_returns_empty_analysis(api):
    """PRD §3.7: "Delivery requires the four re-analyzed actual band-word counts in the
    body ... which capture what was truly delivered and which must sum to more than zero,
    otherwise `ERR_EMPTY_ANALYSIS`."

    Design: Corner/validations/deliver_with_empty_actual_analysis_returns_empty_analysis
    """
    ctx = setup_job_qa_passed(critical_count=0, major_count=0, minor_count=1,
                              scored_word_count=2600)
    resp = api.deliver_job(ctx["job"]["id"], {
        "actual_no_match_words": 0, "actual_fuzzy_words": 0,
        "actual_reps_words": 0, "actual_context_words": 0,
    }, PM)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ANALYSIS.value, 409)
