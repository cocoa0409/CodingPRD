"""Derived fields on a Course: lesson counts, enrollment count, ratings.

These helpers persist the recomputed values onto the course record. Whether a
recompute is a *mutation* (touch -> updated_at/version bump) depends on the
caller and the PRD: rating cascades from review transitions ARE mutations;
plain read-time refreshes of counts are convenience recomputes that should not
spuriously bump version on a GET unless a real change occurred.
"""
from db import db
from services.common import round_2dp, touch


def lessons_of(course_id):
    return [l for l in db.lessons.values() if l["course_id"] == course_id]


def recompute_counts(course):
    """Recompute lesson_count and published_lesson_count in place (no touch)."""
    cid = course["id"]
    lessons = lessons_of(cid)
    course["lesson_count"] = len(lessons)
    course["published_lesson_count"] = sum(1 for l in lessons if l.get("is_published"))


def recompute_enrollment_count(course):
    """enrollment_count = count of Enrollment children NOT in REFUNDED."""
    cid = course["id"]
    course["enrollment_count"] = sum(
        1 for e in db.enrollments.values()
        if e["course_id"] == cid and e["status"] != "REFUNDED"
    )


def recompute_ratings(course):
    """average_rating (mean stars over PUBLISHED reviews, 2dp, null when none)
    and rating_count (count of PUBLISHED reviews). In place, no touch."""
    cid = course["id"]
    published = [r for r in db.reviews.values()
                 if r["course_id"] == cid and r["status"] == "PUBLISHED"]
    course["rating_count"] = len(published)
    if published:
        course["average_rating"] = round_2dp(
            sum(r["stars"] for r in published) / len(published)
        )
    else:
        course["average_rating"] = None


def recompute_ratings_mutation(course):
    """Rating cascade from a review transition: recompute AND bump version."""
    recompute_ratings(course)
    touch(course)
