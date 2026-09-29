"""Existence resolution (PRD 2.10 priority 3, PRD 2.11 left-to-right)."""

from db import db
from errors import ApiError

_MAP = (
    ("practice_group", "practice_groups", "ERR_PRACTICE_GROUP_NOT_FOUND"),
    ("search_firm", "search_firms", "ERR_SEARCH_FIRM_NOT_FOUND"),
    ("engagement", "engagements", "ERR_ENGAGEMENT_NOT_FOUND"),
    ("candidate", "candidates", "ERR_CANDIDATE_NOT_FOUND"),
    ("questionnaire", "questionnaires", "ERR_QUESTIONNAIRE_NOT_FOUND"),
    ("client_book_entry", "client_book_entries", "ERR_CLIENT_BOOK_ENTRY_NOT_FOUND"),
    ("collection_record", "collection_records", "ERR_COLLECTION_RECORD_NOT_FOUND"),
    ("assessment", "assessments", "ERR_ASSESSMENT_NOT_FOUND"),
    ("conflict_check", "conflict_checks", "ERR_CONFLICT_CHECK_NOT_FOUND"),
    ("waiver", "waivers", "ERR_WAIVER_NOT_FOUND"),
    ("declination", "declinations", "ERR_DECLINATION_NOT_FOUND"),
    ("offer", "offers", "ERR_OFFER_NOT_FOUND"),
    ("vote", "votes", "ERR_VOTE_NOT_FOUND"),
    ("integration_plan", "integration_plans", "ERR_INTEGRATION_PLAN_NOT_FOUND"),
    ("introduction", "introductions", "ERR_INTRODUCTION_NOT_FOUND"),
    ("performance_review", "performance_reviews", "ERR_PERFORMANCE_REVIEW_NOT_FOUND"),
)


def _make(collection, error_id):
    def getter(row_id):
        if not isinstance(row_id, str):
            raise ApiError(error_id)
        found = getattr(db, collection).get(row_id)
        if found is None:
            raise ApiError(error_id)
        return found
    return getter


get_practice_group = _make("practice_groups", "ERR_PRACTICE_GROUP_NOT_FOUND")
get_search_firm = _make("search_firms", "ERR_SEARCH_FIRM_NOT_FOUND")
get_engagement = _make("engagements", "ERR_ENGAGEMENT_NOT_FOUND")
get_candidate = _make("candidates", "ERR_CANDIDATE_NOT_FOUND")
get_questionnaire = _make("questionnaires", "ERR_QUESTIONNAIRE_NOT_FOUND")
get_entry = _make("client_book_entries", "ERR_CLIENT_BOOK_ENTRY_NOT_FOUND")
get_collection_record = _make("collection_records", "ERR_COLLECTION_RECORD_NOT_FOUND")
get_assessment = _make("assessments", "ERR_ASSESSMENT_NOT_FOUND")
get_conflict_check = _make("conflict_checks", "ERR_CONFLICT_CHECK_NOT_FOUND")
get_waiver = _make("waivers", "ERR_WAIVER_NOT_FOUND")
get_declination = _make("declinations", "ERR_DECLINATION_NOT_FOUND")
get_offer = _make("offers", "ERR_OFFER_NOT_FOUND")
get_vote = _make("votes", "ERR_VOTE_NOT_FOUND")
get_plan = _make("integration_plans", "ERR_INTEGRATION_PLAN_NOT_FOUND")
get_introduction = _make("introductions", "ERR_INTRODUCTION_NOT_FOUND")
get_review = _make("performance_reviews", "ERR_PERFORMANCE_REVIEW_NOT_FOUND")


def entries_of_questionnaire(questionnaire_id, active_only=False):
    rows = [e for e in db.client_book_entries.values()
            if e["questionnaire_id"] == questionnaire_id]
    if active_only:
        rows = [e for e in rows if e["status"] == "ACTIVE"]
    return rows


def questionnaires_of_candidate(candidate_id):
    return [q for q in db.questionnaires.values()
            if q["candidate_id"] == candidate_id]


def assessments_of_questionnaire(questionnaire_id):
    return [a for a in db.assessments.values()
            if a["questionnaire_id"] == questionnaire_id]


def records_of_entry(entry_id):
    return [r for r in db.collection_records.values()
            if r["client_book_entry_id"] == entry_id]


def records_of_candidate(candidate_id):
    return [r for r in db.collection_records.values()
            if r["candidate_id"] == candidate_id]


def checks_of_entry(entry_id):
    return [c for c in db.conflict_checks.values()
            if c["client_book_entry_id"] == entry_id]


def declinations_of_entry(entry_id):
    return [d for d in db.declinations.values()
            if d["client_book_entry_id"] == entry_id]


def offers_of_candidate(candidate_id):
    return [o for o in db.offers.values() if o["candidate_id"] == candidate_id]


def offers_of_assessment(assessment_id):
    return [o for o in db.offers.values()
            if o["portability_assessment_id"] == assessment_id]


def votes_of_offer(offer_id):
    return [v for v in db.votes.values() if v["offer_id"] == offer_id]


def introductions_of_plan(plan_id):
    return [i for i in db.introductions.values()
            if i["integration_plan_id"] == plan_id]


def plans_of_candidate(candidate_id):
    return [p for p in db.integration_plans.values()
            if p["candidate_id"] == candidate_id]
