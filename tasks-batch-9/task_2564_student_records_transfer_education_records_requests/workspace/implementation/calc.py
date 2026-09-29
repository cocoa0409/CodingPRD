"""Calculation rules (PRD 2.12, 3.4, 3.5, 3.6, 3.7, 3.9)."""

from decimal import Decimal

from common import (STORE, add_business_days, add_calendar_days, add_whole_years,
                    clock_now, end_of_day, parse_calendar_date, round_half_up, touch)
from domain import (CERT_TIER_B_FEE_CENTS, CERT_TIER_B_FLOOR_CENTS, CERT_TIER_C_FEE_CENTS,
                    CERT_TIER_C_FLOOR_CENTS, COMPONENT_TYPE_ORDER, COPY_SURCHARGE_PCT,
                    ELIGIBLE_STUDENT_AGE_YEARS, EXPEDITED_CAP_DAYS, PER_PAGE_CENTS,
                    SPED_CONSENT_EXTENSION_DAYS, SUMMARY_PAGE_COUNT,
                    SUMMARY_SUBSTITUTION_THRESHOLD_PAGES, components_of_file,
                    disclosures_of_student, incidents_of_student)


# --------------------------------------------------------------------------- #
# eligible_student_status (PRD 3.1)
# --------------------------------------------------------------------------- #
def whole_years_since(dob_text, now=None):
    dob = parse_calendar_date(dob_text)
    if dob is None:
        return None
    moment = now or clock_now()
    years = moment.year - dob.year
    if (moment.month, moment.day) < (dob.month, dob.day):
        years -= 1
    return years


def is_eligible_student(student_row):
    years = whole_years_since(student_row.get("dob"))
    if years is None:
        return False
    return years >= ELIGIBLE_STUDENT_AGE_YEARS


# --------------------------------------------------------------------------- #
# records_request_due_at (PRD 3.5)
# --------------------------------------------------------------------------- #
def records_request_window(request_row):
    """Returns (statutory_days_allowed, statutory_due_at). Only the RESPONDING
    district's state rule participates; the anchor is always received_at."""
    district = STORE.districts.get(request_row["responding_district_id"])
    rule = STORE.state_rules.get(district["state_code"]) if district else None
    if rule is None:
        return None, None
    if request_row["request_priority"] == "UNACCOMPANIED_YOUTH":
        effective_days = min(int(rule["transfer_response_days"]), EXPEDITED_CAP_DAYS)
    else:
        effective_days = int(rule["transfer_response_days"])
        if request_row["includes_special_education"] and rule["sped_requires_consent"]:
            effective_days = effective_days + SPED_CONSENT_EXTENSION_DAYS
    cursor = add_business_days(request_row["received_at"], effective_days)
    return effective_days, end_of_day(cursor)


# --------------------------------------------------------------------------- #
# discipline_inclusion_set (PRD 3.4)
# --------------------------------------------------------------------------- #
def incident_included(rule, incident):
    if incident["incident_status"] == "DISMISSED":
        return False
    if incident["incident_status"] == "PENDING_INVESTIGATION" and not rule["include_pending_investigations"]:
        return False
    mode = rule["discipline_inclusion_mode"]
    if mode == "ALL_INCIDENTS":
        return True
    if mode == "SUSPENSIONS_AND_EXPULSIONS":
        if incident["action_type"] == "EXPULSION":
            return True
        if incident["action_type"] == "SUSPENSION":
            return int(incident["days_removed"]) >= int(rule["discipline_min_days_removed"])
        return False
    if mode == "EXPULSIONS_ONLY":
        return incident["action_type"] == "EXPULSION" and bool(incident["adjudicated_by_court"])
    return False


def discipline_inclusion_set(request_row):
    """Runs the governing (responding state) pass, which stamps the incidents,
    and the advisory (requesting state) pass, which only counts."""
    incidents = incidents_of_student(request_row["student_id"])

    responding = STORE.districts.get(request_row["responding_district_id"])
    gov_rule = STORE.state_rules.get(responding["state_code"]) if responding else None
    included = 0
    for incident in incidents:
        verdict = bool(gov_rule) and incident_included(gov_rule, incident)
        stamp = "INCLUDED" if verdict else "WITHHELD"
        if incident["transfer_inclusion_state"] != stamp:
            incident["transfer_inclusion_state"] = stamp
            touch(incident)
        if verdict:
            included += 1
    withheld = len(incidents) - included

    requesting = STORE.districts.get(request_row["requesting_district_id"])
    rcv_rule = STORE.state_rules.get(requesting["state_code"]) if requesting else None
    receiving_count = 0
    if rcv_rule is not None:
        for incident in incidents:
            if incident_included(rcv_rule, incident):
                receiving_count += 1
    return included, withheld, receiving_count


# --------------------------------------------------------------------------- #
# disclosure_packet_page_count (PRD 3.6)
# --------------------------------------------------------------------------- #
def disclosure_packet_page_count(file_row):
    certified = [row for row in components_of_file(file_row["id"]) if row["status"] == "CERTIFIED"]
    raw_pages = sum(int(row["page_count"]) - int(row["redacted_page_count"]) for row in certified)
    discipline_pages = sum(int(row["page_count"]) - int(row["redacted_page_count"])
                           for row in certified if row["component_type"] == "DISCIPLINE")
    if raw_pages > SUMMARY_SUBSTITUTION_THRESHOLD_PAGES:
        return raw_pages - discipline_pages + SUMMARY_PAGE_COUNT
    return raw_pages


def packet_component_types(file_row):
    certified = [row for row in components_of_file(file_row["id"]) if row["status"] == "CERTIFIED"]
    present = set(row["component_type"] for row in certified)
    return [name for name in COMPONENT_TYPE_ORDER if name in present]


# --------------------------------------------------------------------------- #
# cumulative_file_completeness (PRD 3.3)
# --------------------------------------------------------------------------- #
def completeness_pct(certified_count, required_count):
    if required_count <= 0:
        return 0.0
    value = round_half_up(Decimal(100) * Decimal(certified_count) / Decimal(required_count), 1)
    return float(value)


# --------------------------------------------------------------------------- #
# inspection copy fee + certification fee (PRD 3.7)
# --------------------------------------------------------------------------- #
def inspection_copy_fee_cents(file_row, requested_categories, copies_requested):
    if not copies_requested:
        return 0
    total = 0
    per_page = Decimal(PER_PAGE_CENTS)
    surcharge = Decimal(1) + Decimal(COPY_SURCHARGE_PCT)
    for component in components_of_file(file_row["id"]):
        if component["status"] not in ("COLLECTED", "CERTIFIED"):
            continue
        if component["component_type"] not in requested_categories:
            continue
        pages = int(component["page_count"]) - int(component["redacted_page_count"])
        base_c = round_half_up(Decimal(pages) * per_page, 0)
        surcharged_c = round_half_up(base_c * surcharge, 0)
        total += int(surcharged_c)
    return total


def certification_fee_cents(base_copy_fee_cents):
    if base_copy_fee_cents < CERT_TIER_B_FLOOR_CENTS:
        return 0
    if base_copy_fee_cents < CERT_TIER_C_FLOOR_CENTS:
        return CERT_TIER_B_FEE_CENTS
    return CERT_TIER_C_FEE_CENTS


# --------------------------------------------------------------------------- #
# retention_destruction_eligible_at (PRD 3.9)
# --------------------------------------------------------------------------- #
def retention_anchors(schedule_row, student_row, file_row):
    exit_anchor = schedule_row["exit_anchor_at"]
    candidates = [exit_anchor]
    for entry in disclosures_of_student(student_row["id"]):
        candidates.append(entry["disclosed_at"])
    for component in components_of_file(file_row["id"]):
        if component.get("certified_at") is not None:
            candidates.append(component["certified_at"])
    last_activity = max(candidates)
    years = int(schedule_row["destruction_min_age_years"])
    return last_activity, add_whole_years(last_activity, years), add_whole_years(exit_anchor, years)
