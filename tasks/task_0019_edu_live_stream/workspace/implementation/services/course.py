"""Course-related side-effect logic."""
from db import bump, make_immutable_fields, store


def derive_posture(status: str) -> str:
    if status == "DRAFT":
        return "RESTRICTED"
    if status == "UNDER_REVIEW":
        return "RESTRICTED"
    if status == "PUBLISHED":
        return "OPEN"
    if status == "REJECTED":
        return "RESTRICTED"
    if status == "DELISTED":
        return "FROZEN"
    return "RESTRICTED"


def recompute_aggregates(course):
    """Refresh total_chapters, total_video_seconds, enrollment_count on a course."""
    chapters = [c for c in store.chapters.values() if c["course_id"] == course["id"]]
    course["total_chapters"] = len(chapters)
    course["total_video_seconds"] = sum(int(c["video_duration_seconds"]) for c in chapters)
    enrollment_count = 0
    for e in store.enrollments.values():
        if e["course_id"] != course["id"]:
            continue
        if e.get("learning_status") in ("ACTIVE", "AT_RISK", "COMPLETED") or \
                e.get("payment_status") == "REFUND_PENDING":
            enrollment_count += 1
    course["enrollment_count"] = enrollment_count


def make_syllabus_revision(course):
    """Append a new SyllabusRevision row."""
    existing = [s for s in store.syllabus_revisions.values() if s["course_id"] == course["id"]]
    next_num = max((s["revision_number"] for s in existing), default=0) + 1
    chapters = sorted(
        [c for c in store.chapters.values() if c["course_id"] == course["id"]],
        key=lambda c: int(c["ordinal"]),
    )
    outline = [
        {
            "chapter_title": c["title"],
            "learning_objectives": c.get("learning_objectives", c["title"]),
        }
        for c in chapters
    ]
    revision = {
        **make_immutable_fields(),
        "course_id": course["id"],
        "revision_number": next_num,
        "outline": outline,
        "pricing_snapshot_cents": int(course["list_price_cents"]),
        "discount_snapshot_percent": int(course.get("discount_percent", 0)),
    }
    store.syllabus_revisions[revision["id"]] = revision
    return revision


def latest_syllabus_revision_id(course_id):
    revs = [s for s in store.syllabus_revisions.values() if s["course_id"] == course_id]
    if not revs:
        return None
    revs.sort(key=lambda s: s["revision_number"])
    return revs[-1]["id"]


def cascade_delist(course):
    """Course PUBLISHED → DELISTED depth-3 cascade."""
    from services.refund import reprice_pending_refunds_for_enrollment
    cancelled_lc_ids = []
    # link 1: SCHEDULED LiveClass on this course → CANCELLED
    for lc in list(store.live_classes.values()):
        if lc["course_id"] == course["id"] and lc["status"] == "SCHEDULED":
            lc["status"] = "CANCELLED"
            lc["cancellation_reason"] = "COURSE_DELISTED"
            bump(lc)
            cancelled_lc_ids.append(lc["id"])

    # link 2: ACTIVE enrollments whose attendance window overlaps a cancelled live class → AT_RISK
    flipped_enrollment_ids = set()
    if cancelled_lc_ids:
        for enr in list(store.enrollments.values()):
            if enr["course_id"] != course["id"]:
                continue
            if enr.get("learning_status") != "ACTIVE":
                continue
            # Any cancelled live class overlap. The enrollment is for the same course as the LCs,
            # so cancelled LCs of this course apply to all of its enrollments.
            enr["learning_status"] = "AT_RISK"
            bump(enr)
            flipped_enrollment_ids.add(enr["id"])

    # link 3: Reprice PENDING refund requests for those enrollments
    for eid in flipped_enrollment_ids:
        enr = store.enrollments.get(eid)
        if enr:
            reprice_pending_refunds_for_enrollment(enr)
