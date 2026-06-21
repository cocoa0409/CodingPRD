"""Serializers — produce the exact public field set per entity (scaffold Table 1)."""


def client_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "billing_email": c["billing_email"],
        "ar_balance_cents": c["ar_balance_cents"],
        "status": c["status"],
    }


def linguist_out(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "full_name": l["full_name"],
        "native_locale": l["native_locale"],
        "qualified_pairs": l["qualified_pairs"],
        "can_review": l["can_review"],
        "daily_throughput_words": l["daily_throughput_words"],
        "committed_payout_cents": l["committed_payout_cents"],
        "status": l["status"],
    }


def rate_card_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "source_locale": r["source_locale"],
        "target_locale": r["target_locale"],
        "base_rate_cents_per_word": r["base_rate_cents_per_word"],
        "linguist_rate_cents_per_word": r["linguist_rate_cents_per_word"],
        "active": r["active"],
    }


def project_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "client_id": p["client_id"],
        "rate_card_id": p["rate_card_id"],
        "name": p["name"],
        "rush_tier": p["rush_tier"],
        "certification_mode": p["certification_mode"],
        "pinned_base_rate_cents_per_word": p["pinned_base_rate_cents_per_word"],
        "pinned_linguist_rate_cents_per_word": p["pinned_linguist_rate_cents_per_word"],
        "quoted_total_cents": p["quoted_total_cents"],
        "status": p["status"],
    }


def job_out(j):
    return {
        "id": j["id"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
        "project_id": j["project_id"],
        "filename": j["filename"],
        "quoted_no_match_words": j["quoted_no_match_words"],
        "quoted_fuzzy_words": j["quoted_fuzzy_words"],
        "quoted_reps_words": j["quoted_reps_words"],
        "quoted_context_words": j["quoted_context_words"],
        "actual_no_match_words": j["actual_no_match_words"],
        "actual_fuzzy_words": j["actual_fuzzy_words"],
        "actual_reps_words": j["actual_reps_words"],
        "actual_context_words": j["actual_context_words"],
        "weighted_source_words": j["weighted_source_words"],
        "revision_rounds": j["revision_rounds"],
        "latest_qa_score": j["latest_qa_score"],
        "status": j["status"],
    }


def assignment_out(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "job_id": a["job_id"],
        "linguist_id": a["linguist_id"],
        "role": a["role"],
        "window_start": a["window_start"],
        "window_end": a["window_end"],
        "payout_cents": a["payout_cents"],
        "payout_finalized": a["payout_finalized"],
        "expected_job_version": a["expected_job_version"],
        "status": a["status"],
    }


def qa_report_out(q):
    return {
        "id": q["id"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
        "job_id": q["job_id"],
        "reviewer_assignment_id": q["reviewer_assignment_id"],
        "critical_count": q["critical_count"],
        "major_count": q["major_count"],
        "minor_count": q["minor_count"],
        "scored_word_count": q["scored_word_count"],
        "score": q["score"],
        "outcome": q["outcome"],
    }


def invoice_out(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "project_id": i["project_id"],
        "client_id": i["client_id"],
        "translation_subtotal_cents": i["translation_subtotal_cents"],
        "volume_discount_cents": i["volume_discount_cents"],
        "rush_surcharge_cents": i["rush_surcharge_cents"],
        "revision_surcharge_cents": i["revision_surcharge_cents"],
        "certification_cents": i["certification_cents"],
        "total_cents": i["total_cents"],
        "expected_project_version": i["expected_project_version"],
        "status": i["status"],
    }


def payout_ledger_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "linguist_id": e["linguist_id"],
        "assignment_id": e["assignment_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "reason": e["reason"],
    }


def certificate_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "job_id": c["job_id"],
        "certification_mode": c["certification_mode"],
        "page_count": c["page_count"],
        "certificate_number": c["certificate_number"],
    }
