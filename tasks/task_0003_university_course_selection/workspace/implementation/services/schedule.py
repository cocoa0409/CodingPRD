"""Schedule conflict detection."""
import db


def parse_days(days_str):
    """Parse schedule_days string like 'MWF' or 'TR' into a set of day characters."""
    result = set()
    i = 0
    while i < len(days_str):
        if i + 1 < len(days_str) and days_str[i] == 'T' and days_str[i + 1] == 'R':
            result.add('TR')
            i += 2
        elif i + 1 < len(days_str) and days_str[i] == 'T' and days_str[i + 1] == 'H':
            result.add('TH')
            i += 2
        else:
            result.add(days_str[i])
            i += 1
    return result


def time_to_minutes(time_str):
    """Convert HH:MM to minutes since midnight."""
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def check_schedule_conflict(student_id, proposed_section, semester_id=None):
    """Check if proposed_section conflicts with any of the student's ENROLLED sections.
    Returns list of conflict dicts, or empty list if no conflicts.
    """
    conflicts = []

    # Get all sections where the student is ENROLLED
    enrolled_sections = []
    for enr in db.enrollments.values():
        if enr["student_id"] == student_id and enr["status"] == "ENROLLED":
            section = db.sections.get(enr["section_id"])
            if section and section["id"] != proposed_section["id"]:
                enrolled_sections.append(section)

    proposed_days = parse_days(proposed_section["schedule_days"])
    proposed_start = time_to_minutes(proposed_section["schedule_start"])
    proposed_end = time_to_minutes(proposed_section["schedule_end"])

    for existing in enrolled_sections:
        existing_days = parse_days(existing["schedule_days"])
        common_days = proposed_days & existing_days

        if not common_days:
            continue

        existing_start = time_to_minutes(existing["schedule_start"])
        existing_end = time_to_minutes(existing["schedule_end"])

        # Check for different-building buffer
        different_location = proposed_section.get("location") != existing.get("location")

        # Apply travel buffer if different locations
        if different_location:
            # 10-minute travel buffer
            effective_proposed_start = proposed_start - 10
            effective_proposed_end = proposed_end + 10
            effective_existing_start = existing_start - 10
            effective_existing_end = existing_end + 10

            # Check: proposed starts before existing ends + buffer,
            # and existing starts before proposed ends + buffer
            if proposed_start < existing_end + 10 and existing_start < proposed_end + 10:
                # Calculate actual overlap minutes (without buffer for the record)
                overlap_start = max(proposed_start, existing_start)
                overlap_end = min(proposed_end, existing_end)
                if overlap_end > overlap_start:
                    overlap_minutes = overlap_end - overlap_start
                else:
                    # It's a buffer-only conflict (no actual time overlap, but within travel buffer)
                    overlap_minutes = 0
                    # Calculate the gap and report it
                    if proposed_start >= existing_end:
                        overlap_minutes = 10 - (proposed_start - existing_end)
                    elif existing_start >= proposed_end:
                        overlap_minutes = 10 - (existing_start - proposed_end)

                overlap_days_str = _days_to_string(common_days)
                conflicts.append({
                    "student_id": student_id,
                    "section_a_id": existing["id"],
                    "section_b_id": proposed_section["id"],
                    "overlap_days": overlap_days_str,
                    "overlap_minutes": max(overlap_minutes, 1)
                })
        else:
            # Same location - strict overlap check
            if proposed_start < existing_end and existing_start < proposed_end:
                overlap_start = max(proposed_start, existing_start)
                overlap_end = min(proposed_end, existing_end)
                overlap_minutes = overlap_end - overlap_start

                overlap_days_str = _days_to_string(common_days)
                conflicts.append({
                    "student_id": student_id,
                    "section_a_id": existing["id"],
                    "section_b_id": proposed_section["id"],
                    "overlap_days": overlap_days_str,
                    "overlap_minutes": overlap_minutes
                })

    return conflicts


def _days_to_string(days_set):
    """Convert a set of day identifiers back to a compact string."""
    # Order: M, T, W, TR/TH, F
    order = ["M", "T", "W", "TH", "TR", "F", "S"]
    result = ""
    for d in order:
        if d in days_set:
            result += d
    # If nothing matched with our order, just join
    if not result:
        result = "".join(sorted(days_set))
    return result
