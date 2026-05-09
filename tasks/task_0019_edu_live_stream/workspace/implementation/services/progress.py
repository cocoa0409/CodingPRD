"""Progress recomputation and at-risk evaluation."""
from db import bump, store
from services.rounding import round_half_up_decimals

AT_RISK_PROGRESS_THRESHOLD = 30.0
AT_RISK_ATTENDANCE_THRESHOLD = 70.0
AT_RISK_DAYS_THRESHOLD = 14


def _required_chapters(course_id: str):
    return [c for c in store.chapters.values()
            if c["course_id"] == course_id and c.get("required_for_completion", True)]


def _ws_total_for(enrollment_id: str, chapter_id: str) -> int:
    total = 0
    for ws in store.watch_sessions.values():
        if ws["enrollment_id"] == enrollment_id and ws["chapter_id"] == chapter_id:
            total += int(ws["seconds_watched"])
    return total


def compute_chapter_completion(enrollment) -> float:
    required = _required_chapters(enrollment["course_id"])
    if not required:
        return 0.0
    completed = 0
    for ch in required:
        watched = _ws_total_for(enrollment["id"], ch["id"])
        if watched >= int(ch["video_duration_seconds"]):
            completed += 1
    raw = 100.0 * completed / len(required)
    return round_half_up_decimals(raw, 1)


def compute_watch_duration(enrollment) -> float:
    required = _required_chapters(enrollment["course_id"])
    if not required:
        return 0.0
    total_required = sum(int(ch["video_duration_seconds"]) for ch in required)
    if total_required == 0:
        return 0.0
    capped_sum = 0
    for ch in required:
        watched = _ws_total_for(enrollment["id"], ch["id"])
        capped_sum += min(watched, int(ch["video_duration_seconds"]))
    raw = 100.0 * capped_sum / total_required
    return round_half_up_decimals(raw, 1)


def compute_attendance_count(enrollment_id: str) -> int:
    n = 0
    for a in store.attendances.values():
        if a["enrollment_id"] == enrollment_id and a["mark"] in ("ATTENDED", "LATE"):
            n += 1
    return n


def recompute_progress(enrollment, run_at_risk: bool = True):
    """Step 1: chapter %. Step 2: watch %. Step 3: progress = max with tie-break.
    Step 4: attendance_count. Step 5: at-risk evaluation (also handles COMPLETED).
    """
    cc = compute_chapter_completion(enrollment)
    wd = compute_watch_duration(enrollment)
    enrollment["chapter_completion_percent"] = cc
    enrollment["watch_duration_percent"] = wd
    # tie -> chapter_completion_percent
    if cc >= wd:
        enrollment["progress_percent"] = cc
    else:
        enrollment["progress_percent"] = wd
    enrollment["attendance_count"] = compute_attendance_count(enrollment["id"])
    if run_at_risk:
        evaluate_at_risk(enrollment)


def _enrolled_at_unix(enrollment) -> int:
    """enrolled_at is ISO 8601 UTC; convert to unix seconds."""
    import datetime
    val = enrollment.get("enrolled_at")
    if not val:
        return store.clock_now_ts
    # parse ISO 8601 UTC
    s = val
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return store.clock_now_ts
    return int(dt.timestamp())


def evaluate_at_risk(enrollment):
    """Apply the at-risk evaluation. Also handles COMPLETED based on chapter completion."""
    # First — completion check
    course_id = enrollment["course_id"]
    required = _required_chapters(course_id)
    if required:
        all_done = True
        for ch in required:
            watched = _ws_total_for(enrollment["id"], ch["id"])
            if watched < int(ch["video_duration_seconds"]):
                all_done = False
                break
        if all_done and enrollment["learning_status"] == "ACTIVE":
            enrollment["learning_status"] = "COMPLETED"
            bump(enrollment)
            # external certificate.issued event is emitted; not stored in AuditLogEntry's
            # restricted action set, so we do not append to the audit log here.
            return

    if enrollment["learning_status"] not in ("ACTIVE", "AT_RISK"):
        return

    now_ts = store.clock_now_ts
    enrolled_at_ts = _enrolled_at_unix(enrollment)
    days_since = (now_ts - enrolled_at_ts) // 86400 if now_ts >= enrolled_at_ts else 0

    # attendance_rate
    course_live_classes = [
        lc for lc in store.live_classes.values()
        if lc["course_id"] == course_id
        and lc["status"] in ("LIVE", "ENDED")
        and int(lc["start_ts"]) <= now_ts
    ]
    if not course_live_classes:
        attendance_rate = 1.0
    else:
        attended = 0
        for a in store.attendances.values():
            if a["enrollment_id"] == enrollment["id"] and a["mark"] in ("ATTENDED", "LATE"):
                # check that the live class is in the relevant subset
                lc = store.live_classes.get(a["live_class_id"])
                if lc and lc["course_id"] == course_id and lc["status"] in ("LIVE", "ENDED") and int(lc["start_ts"]) <= now_ts:
                    attended += 1
        attendance_rate = attended / len(course_live_classes)

    progress_percent = float(enrollment["progress_percent"])
    risk_score = (
        0.6 * (AT_RISK_PROGRESS_THRESHOLD - progress_percent)
        + 0.4 * (AT_RISK_ATTENDANCE_THRESHOLD - 100.0 * attendance_rate)
    )

    cur = enrollment["learning_status"]
    if cur == "ACTIVE":
        if days_since >= AT_RISK_DAYS_THRESHOLD and (
            progress_percent < AT_RISK_PROGRESS_THRESHOLD or risk_score > 0
        ):
            enrollment["learning_status"] = "AT_RISK"
            bump(enrollment)
    elif cur == "AT_RISK":
        if progress_percent >= AT_RISK_PROGRESS_THRESHOLD and risk_score <= 0:
            enrollment["learning_status"] = "ACTIVE"
            bump(enrollment)


def sweep_at_risk():
    for enr in list(store.enrollments.values()):
        recompute_progress(enr, run_at_risk=True)
